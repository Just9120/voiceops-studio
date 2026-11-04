from pathlib import Path
import sys
import httpx
import pytest
import hashlib
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))

from studio_api.google_drive_upload import GoogleDriveUploadError, upload_file_resumable


class Response:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
    def json(self): return self._payload


class Client:
    def __init__(self, *, existing=None): self.existing = existing; self.posts = 0; self.puts = 0
    def __enter__(self): return self
    def __exit__(self, *_args): return None
    def get(self, *_args, **_kwargs): return Response(payload={"files": [self.existing] if self.existing else []})
    def post(self, *_args, **_kwargs): self.posts += 1; return Response(headers={"Location": "https://www.googleapis.com/upload/drive/v3/files?upload_id=safe-id"})
    def put(self, *_args, **_kwargs): self.puts += 1; return Response(payload={"id": "file-id", "name": "result.flac", "size": "5", "webViewLink": "https://drive.google.com/file/d/file-id/view", "parents": ["folder-id"], "sha256Checksum": hashlib.sha256(b"audio").hexdigest(), "headRevisionId": "revision-one"})
    def stream(self, *_args, **_kwargs): pytest.fail("Available SHA256 must avoid an extra file download")


def input_file(tmp_path):
    path = tmp_path / "drive-upload.flac"
    path.write_bytes(b"audio")
    return path


def test_resumable_upload_reuses_existing_idempotent_drive_result(tmp_path):
    existing = {**complete_response().json(), "id": "existing-id", "webViewLink": "https://drive.google.com/file/d/existing-id/view"}
    client = Client(existing=existing)
    result = upload_file_resumable("token", folder_id="folder-id", path=input_file(tmp_path), filename="result.flac", mime_type="audio/flac", idempotency_key="job-id", client_factory=lambda **_kwargs: client)
    assert result.file_id == "existing-id"
    assert result.sha256_checksum == hashlib.sha256(b"audio").hexdigest()
    assert result.head_revision_id == "revision-one"
    assert client.posts == 0
    assert client.puts == 0


def test_manifest_export_has_distinct_reconciliation_namespace(tmp_path):
    import json
    class ManifestClient(Client):
        def get(self, *args, **kwargs):
            assert "key='studioManifestSnapshot'" in kwargs["params"]["q"]
            assert "studioAudioPreparationJobId" not in kwargs["params"]["q"]
            return super().get(*args, **kwargs)
        def post(self, *args, **kwargs):
            assert json.loads(kwargs["content"])["appProperties"] == {"studioManifestSnapshot": "snapshot-hash"}
            return super().post(*args, **kwargs)
    client = ManifestClient()
    upload_file_resumable("token", folder_id="folder-id", path=input_file(tmp_path), filename="manifest.json",
        mime_type="application/json", idempotency_key="snapshot-hash", app_property_key="studioManifestSnapshot",
        client_factory=lambda **kwargs: client)
    assert client.posts == 1


def test_resumable_upload_creates_once_after_empty_reconciliation(tmp_path):
    client = Client()
    result = upload_file_resumable("token", folder_id="folder-id", path=input_file(tmp_path), filename="result.flac", mime_type="audio/flac", idempotency_key="job-id", client_factory=lambda **_kwargs: client)
    assert result.file_id == "file-id"
    assert client.posts == 1
    assert client.puts == 1


def _upload(tmp_path, client, **kwargs):
    return upload_file_resumable("token", folder_id="folder-id", path=input_file(tmp_path), filename="result.flac",
        mime_type="audio/flac", idempotency_key="job-id", client_factory=lambda **_kwargs: client, **kwargs)


class ScriptedClient(Client):
    def __init__(self, responses):
        super().__init__()
        self.responses = iter(responses)
        self.requests = []
    def put(self, _url, **kwargs):
        self.puts += 1
        self.requests.append(kwargs)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def complete_response():
    return Client().put()


def test_chunk_ranges_resume_from_confirmed_offset_after_interruption(tmp_path):
    client = ScriptedClient([httpx.ReadTimeout("response lost"), Response(308, headers={"Range": "bytes=0-1"}), complete_response()])
    progress = []
    _upload(tmp_path, client, progress_callback=lambda sent, total: progress.append((sent, total)))
    assert [request["headers"]["Content-Range"] for request in client.requests] == ["bytes 0-4/5", "bytes */5", "bytes 2-4/5"]
    assert client.requests[-1]["content"] == b"dio"
    assert progress == [(2, 5)]
    assert client.posts == 1


def test_lost_final_response_reconciles_same_session_without_another_create(tmp_path):
    client = ScriptedClient([Response(503), complete_response()])
    assert _upload(tmp_path, client).file_id == "file-id"
    assert client.posts == 1 and client.puts == 2
    assert client.requests[-1]["content"] == b""


@pytest.mark.parametrize("range_header", ["bytes=1-2", "bytes=0-5", "invalid"])
def test_malformed_acknowledgement_never_reports_success(tmp_path, range_header):
    with pytest.raises(GoogleDriveUploadError):
        _upload(tmp_path, ScriptedClient([Response(308, headers={"Range": range_header})]))


def test_no_progress_is_bounded(tmp_path):
    client = ScriptedClient([Response(308)] * 3)
    with pytest.raises(GoogleDriveUploadError):
        _upload(tmp_path, client)
    assert client.puts == 3 and client.posts == 1


def test_cancellation_between_chunks_stops_external_work(tmp_path):
    client = ScriptedClient([Response(308, headers={"Range": "bytes=0-1"})])
    cancelled = False
    def check():
        if cancelled:
            raise RuntimeError("cancelled")
    def progress(*_args):
        nonlocal cancelled
        cancelled = True
    with pytest.raises(RuntimeError, match="cancelled"):
        _upload(tmp_path, client, check_cancelled=check, progress_callback=progress)
    assert client.puts == 1


def test_wrong_size_existing_copy_is_not_accepted(tmp_path):
    existing = complete_response().json() | {"size": "4"}
    client = Client(existing=existing)
    with pytest.raises(GoogleDriveUploadError):
        _upload(tmp_path, client)
    assert client.posts == 0


def test_large_file_uses_multiple_bounded_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr("studio_api.google_drive_upload.DRIVE_UPLOAD_CHUNK_SIZE", 256 * 1024)
    path = tmp_path / "large.flac"
    path.write_bytes(b"x" * (256 * 1024 + 1))
    final = complete_response()
    final._payload["size"] = str(path.stat().st_size)
    final._payload["sha256Checksum"] = hashlib.sha256(path.read_bytes()).hexdigest()
    client = ScriptedClient([Response(308, headers={"Range": "bytes=0-262143"}), final])
    upload_file_resumable("token", folder_id="folder-id", path=path, filename="result.flac", mime_type="audio/flac", idempotency_key="job-id", client_factory=lambda **kwargs: client)
    assert [len(r["content"]) for r in client.requests] == [256 * 1024, 1]


def test_same_size_modified_copy_never_creates_or_overwrites_another_result(tmp_path):
    existing = complete_response().json() | {"sha256Checksum": hashlib.sha256(b"wrong").hexdigest()}
    client = Client(existing=existing)
    with pytest.raises(GoogleDriveUploadError, match="content_mismatch"):
        _upload(tmp_path, client)
    assert client.posts == client.puts == 0


@pytest.mark.parametrize("body", [b"audio", b"wrong", b"aud", b"audio-too-long"])
@pytest.mark.parametrize("revision", [None, "revision-one"])
def test_missing_remote_checksum_requires_bounded_actual_content_proof(tmp_path, body, revision):
    existing = complete_response().json()
    existing.pop("sha256Checksum")
    existing["headRevisionId"] = revision
    seen = []
    class LegacyClient(Client):
        @contextmanager
        def stream(self, method, url, **kwargs):
            seen.append((method, url, kwargs))
            yield httpx.Response(200, content=body)
    client = LegacyClient(existing=existing)
    if body == b"audio":
        result = _upload(tmp_path, client)
        assert result.sha256_checksum == hashlib.sha256(body).hexdigest()
    else:
        with pytest.raises(GoogleDriveUploadError, match="content_mismatch"):
            _upload(tmp_path, client)
    assert len(seen) == 1 and client.posts == client.puts == 0
    assert seen[0][0] == "GET" and seen[0][2]["params"]["alt"] == "media"
    assert seen[0][1].endswith("/revisions/revision-one" if revision else "/file-id")


def test_successful_upload_ack_still_requires_matching_content(tmp_path):
    response = complete_response()
    response._payload["sha256Checksum"] = "0" * 64
    client = ScriptedClient([response])
    with pytest.raises(GoogleDriveUploadError, match="content_mismatch"):
        _upload(tmp_path, client)
    assert client.posts == client.puts == 1


def test_final_created_copy_is_verified_even_when_cancel_arrived_with_its_ack(tmp_path):
    cancelled = False
    class CompletionClient(Client):
        def put(self, *args, **kwargs):
            nonlocal cancelled
            response = super().put(*args, **kwargs)
            response._payload.pop("sha256Checksum")
            cancelled = True
            return response
        @contextmanager
        def stream(self, *args, **kwargs):
            yield httpx.Response(200, content=b"audio")
    def check():
        if cancelled:
            raise RuntimeError("cancelled")
    client = CompletionClient()
    result = _upload(tmp_path, client, check_cancelled=check)
    assert result.sha256_checksum == hashlib.sha256(b"audio").hexdigest()
    assert client.posts == client.puts == 1


def test_cancellation_during_local_hash_never_creates_an_external_request(tmp_path):
    def check():
        raise RuntimeError("cancelled_before_transfer")
    with pytest.raises(RuntimeError, match="cancelled_before_transfer"):
        upload_file_resumable("token", folder_id="folder-id", path=input_file(tmp_path), filename="result.flac",
            mime_type="audio/flac", idempotency_key="job-id", check_cancelled=check,
            client_factory=lambda **kwargs: pytest.fail("Cancelled hash must not open an HTTP client"))
