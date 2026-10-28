import base64
from datetime import datetime, timezone, timedelta
import hashlib
import hmac
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
if "STUDIO_DATABASE_HOST" not in os.environ:
    os.environ.setdefault("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
from studio_api.batch_stt_transport import BatchHttpTransport
from studio_api.elevenlabs_transcription import ElevenLabsTranscriptionError
from studio_api.mistral_transcription import MistralTranscriptionTransport, normalize_mistral_response
from studio_api.gemini_transcription import GeminiTranscriptionTransport, normalize_gemini_response
from studio_api.tbank_transcription import TbankTranscriptionTransport, voicekit_token, credential_pair, normalize_tbank_response
from studio_api.models import User, Project, Source, SourceType, SourceUploadStatus, TranscriptionJob, TranscriptionJobSource, SttProviderOperation, ProviderCredential, ProviderCredentialVersion, CredentialProvider
from studio_api.security import encrypt, aad, fingerprint
from studio_api.db import Base
from studio_api.provider_result_cache import load_operation_result
from studio_api.provider_file_cleanup import process_one_provider_file_cleanup

RAW = json.dumps({"api_key": "synthetic-public-id", "secret_key": base64.b64encode(b"s" * 32).decode()})
GEMINI = {"status": "completed", "steps": [{"type": "model_output", "content": [{"type": "text", "text": "Привет, мир!", "annotations": [
    {"type": "word_info", "text": "Привет", "speaker": "spk_1", "start_offset": "0.1s", "end_offset": "0.3s"},
    {"type": "word_info", "text": "мир", "speaker": "spk_2", "start_offset": "0.4s", "end_offset": "0.6s"}]}]}]}


def test_tbank_jwt_uses_separate_pair_and_correct_audience_without_private_job_data():
    token = voicekit_token(RAW, clock=lambda: 1000)
    head, body, signature = token.split(".")
    decode = lambda s: json.loads(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)))
    assert decode(head) == {"alg": "HS256", "typ": "JWT", "kid": "synthetic-public-id"}
    assert decode(body)["aud"] == "tinkoff.cloud.stt"
    assert decode(body)["exp"] == 1300
    expected = base64.urlsafe_b64encode(hmac.new(b"s" * 32, (head + "." + body).encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    assert hmac.compare_digest(signature, expected)
    with pytest.raises(ValueError): credential_pair('{"api_key":"private-example","secret_key":"not-base64"}')


def test_tbank_uses_documented_request_shape_and_never_silently_enables_diarization():
    calls = []
    def respond(request):
        calls.append(request)
        payload = json.loads(request.read())
        assert request.url == "https://api.tbank.ru/v1/stt:recognize"
        assert payload["config"]["speechContexts"] == [{"phrases": [{"text": "Kubernetes", "score": 1}]}]
        assert payload["config"]["encoding"] == "MPEG_AUDIO"
        assert base64.b64decode(payload["audio"]["content"]) == b"synthetic-audio"
        return httpx.Response(200, json={"results": [{"alternatives": [{"transcript": "Русский Kubernetes"}]}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        transport = TbankTranscriptionTransport(client=client)
        result = transport.transcribe(api_key=RAW, stream=BytesIO(b"synthetic-audio"), filename="x.mp3", mime_type="audio/mpeg", language_code="ru", keyterms=["Kubernetes"])
        assert result.text == "Русский Kubernetes"
        result.revoke()
        with pytest.raises(ElevenLabsTranscriptionError):
            transport.transcribe(api_key=RAW, stream=BytesIO(b"a"), filename="x", mime_type="audio/mpeg", diarize=True)
    assert len(calls) == 1


def test_mistral_upload_keeps_full_file_segment_speakers_and_dictionary():
    def respond(request):
        body = request.read()
        assert request.url == "https://api.mistral.ai/v1/audio/transcriptions"
        assert request.headers["Authorization"] == "Bearer synthetic-key"
        assert b"synthetic-audio" in body and b"Kubernetes" in body
        assert b'voxtral-small-transcribe-3' in body
        assert b'name="timestamp_granularities"\r\n\r\nsegment' in body
        return httpx.Response(200, json={"text": "Привет. Мир.", "language": "ru", "finish_reason": None, "segments": [
            {"text": "Привет.", "start": 0, "end": 1, "speaker_id": "speaker_0"},
            {"text": " Мир.", "start": 1, "end": 2, "speaker_id": "speaker_1"}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = MistralTranscriptionTransport(client=client).transcribe(api_key="synthetic-key", stream=BytesIO(b"synthetic-audio"),
            filename="x.flac", mime_type="audio/flac", diarize=True, keyterms=["Kubernetes"])
    assert result.text == "Привет. Мир."
    assert [w.speaker_id for w in result.words] == ["speaker_0", "speaker_1"]
    assert "Привет" not in repr(result)
    result.revoke()
    with pytest.raises(ElevenLabsTranscriptionError): _ = result.text


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
def test_paid_requests_are_not_retried_or_redirected_and_errors_are_redacted(status):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://untrusted.test/steal"}, json={"secret": "private-key-plaintext", "text": "private transcript"})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ElevenLabsTranscriptionError) as error:
            MistralTranscriptionTransport(client=client).transcribe(api_key="private-key-plaintext", stream=BytesIO(b"audio"), filename="x", mime_type="audio/flac")
    assert len(calls) == 1
    assert "private" not in str(error.value)


@pytest.fixture
def gemini_state():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(User(id="owner", email="owner@example.test"))
        db.add(Project(id="project", owner_user_id="owner", title="Synthetic"))
        credential = ProviderCredential(id="credential", user_id="owner", provider=CredentialProvider.gemini, label="Synthetic")
        db.add(credential)
        ciphertext, nonce = encrypt("synthetic-key", b"k" * 32, aad("owner", "credential", "version", "gemini"))
        db.add(ProviderCredentialVersion(id="version", credential_id="credential", version=1, ciphertext=ciphertext,
            nonce=nonce, key_id="synthetic", masked_value="synthetic", fingerprint=fingerprint("synthetic-key")))
        db.flush()
        credential.active_version_id = "version"
        db.add(Source(id="source", project_id="project", source_type=SourceType.local_upload, original_filename="synthetic.flac", upload_status=SourceUploadStatus.uploaded))
        db.add(TranscriptionJob(id="job", owner_user_id="owner", project_id="project", provider="gemini", provider_credential_id="credential", operating_mode="standard", attempt_count=1))
        db.add(TranscriptionJobSource(id="relation", job_id="job", source_id="source", position=0))
        db.commit()
        settings = SimpleNamespace(credential_key_id="synthetic", master_key_b64=lambda: base64.b64encode(b"k" * 32).decode())
        yield db, settings


@pytest.mark.parametrize("failure", [None, "malformed", "request", "cleanup"])
def test_gemini_verbatim_and_file_cleanup_on_success_and_failure(gemini_state, failure):
    db, settings = gemini_state
    calls = []
    def respond(request):
        calls.append((request.method, request.url.path))
        assert request.url.host == "generativelanguage.googleapis.com"
        if request.url.path == "/upload/v1beta/files" and not request.url.query:
            return httpx.Response(200, headers={"x-goog-upload-url": "https://generativelanguage.googleapis.com/upload/v1beta/files?upload_id=synthetic"})
        if request.url.path.startswith("/upload/"):
            assert request.read() == b"synthetic-audio"
            return httpx.Response(200, json={"file": {"name": "files/synthetic", "state": "ACTIVE"}})
        if request.method == "DELETE": return httpx.Response(503 if failure == "cleanup" else 204)
        payload = json.loads(request.read())
        assert payload["store"] is False
        assert payload["generation_config"]["transcription_config"]["mode"] == {"type": "verbatim", "diarization_mode": "speaker"}
        if failure == "request": return httpx.Response(503, text="private-error")
        return httpx.Response(200, json={} if failure == "malformed" else GEMINI)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        transport = GeminiTranscriptionTransport(db=db, job_id="job", job_source_id="relation", settings=settings,
            clock=lambda: datetime(2026, 10, 28, tzinfo=timezone.utc), client=client)
        def run():
            return transport.transcribe(api_key="synthetic-key", stream=BytesIO(b"synthetic-audio"), filename="x.flac", mime_type="audio/flac", diarize=True)
        if failure in {"malformed", "request"}:
            with pytest.raises(ElevenLabsTranscriptionError): run()
        else:
            result = run()
            assert result.text == "Привет, мир!"
            assert "".join(w.text for w in result.words) == result.text
            result.revoke()
    operation = db.scalar(select(SttProviderOperation))
    assert (operation.external_file_deleted_at is None) is (failure == "cleanup")
    assert calls[-1] == ("DELETE", "/v1beta/files/synthetic")
    if failure in {None, "cleanup"}:
        restored = load_operation_result(operation, settings=settings)
        assert restored.text == "Привет, мир!"
        restored.revoke()
        assert "Привет" not in str(operation.result_ciphertext)


@pytest.mark.parametrize("url", ["https://untrusted.test/steal", "https://generativelanguage.googleapis.com:invalid/upload/x", "https://generativelanguage.googleapis.com:443/upload/x"])
def test_gemini_rejects_returned_upload_host_before_sending_audio_or_key(gemini_state, url):
    db, settings = gemini_state
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, headers={"x-goog-upload-url": url})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        transport = GeminiTranscriptionTransport(db=db, job_id="job", job_source_id="relation", settings=settings, clock=lambda: datetime.now(timezone.utc), client=client)
        with pytest.raises(ElevenLabsTranscriptionError):
            transport.transcribe(api_key="synthetic-key", stream=BytesIO(b"audio"), filename="x", mime_type="audio/flac")
    assert len(calls) == 1


@pytest.mark.parametrize("status", [204, 404, 503])
def test_cleanup_retries_only_receipted_inactive_files_and_preserves_cache(gemini_state, status):
    db, settings = gemini_state
    now = datetime(2026, 10, 29, tzinfo=timezone.utc)
    operation = SttProviderOperation(id="operation", owner_user_id="owner", project_id="project", job_id="job",
        job_source_id="relation", attempt_number=1, provider="gemini", model="gemini-3.5-transcribe", operating_mode="standard",
        operation_id="files/owned", external_file_id="files/owned", external_file_credential_version_id="version",
        status="failed", updated_at=now - timedelta(hours=1))
    db.add(operation)
    job = db.get(TranscriptionJob, "job")
    job.lease_owner_id, job.lease_expires_at = "active-worker", now + timedelta(minutes=5)
    db.commit()
    calls = []
    def respond(request):
        calls.append(request)
        assert request.method == "DELETE" and request.url == "https://generativelanguage.googleapis.com/v1beta/files/owned"
        assert request.headers["x-goog-api-key"] == "synthetic-key"
        return httpx.Response(status)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        factory = lambda: Session(db.get_bind())
        assert not process_one_provider_file_cleanup(session_factory=factory, settings=settings, now=now, client=client)
        assert not calls
        job.lease_owner_id, job.lease_expires_at = None, None
        db.commit()
        assert process_one_provider_file_cleanup(session_factory=factory, settings=settings, now=now, client=client) is (status != 503)
    db.refresh(operation)
    assert (operation.external_file_deleted_at is not None) is (status != 503)
    assert operation.status == "failed"
    assert len(calls) == 1


@pytest.mark.parametrize("unavailable", ["erased", "foreign"])
def test_cleanup_cannot_use_foreign_credentials_or_erase_erased_key(gemini_state, unavailable):
    db, settings = gemini_state
    now = datetime(2026, 10, 29, tzinfo=timezone.utc)
    operation = SttProviderOperation(id="operation", owner_user_id="owner", project_id="project", job_id="job",
        job_source_id="relation", attempt_number=1, provider="gemini", model="gemini-3.5-transcribe", operating_mode="standard",
        operation_id="files/owned", external_file_id="files/owned", external_file_credential_version_id="version",
        status="failed", updated_at=now - timedelta(hours=1))
    db.add(operation)
    if unavailable == "erased":
        db.get(ProviderCredentialVersion, "version").ciphertext = None
    else:
        db.add(User(id="foreign", email="foreign@example.test"))
        db.get(ProviderCredential, "credential").user_id = "foreign"
    db.commit()
    with httpx.Client(transport=httpx.MockTransport(lambda request: pytest.fail("erased keys cannot be used"))) as client:
        assert not process_one_provider_file_cleanup(session_factory=lambda: Session(db.get_bind()), settings=settings, now=now, client=client)
    db.refresh(operation)
    assert operation.external_file_deleted_at is None


@pytest.mark.parametrize("payload", [{}, {"text": "partial", "finish_reason": "length"}, {"text": "full", "segments": [{"text": "part", "speaker_id": "0"}]}])
def test_partial_mistral_is_not_success(payload):
    with pytest.raises(ElevenLabsTranscriptionError): normalize_mistral_response(payload, diarize=True)


def test_malformed_tbank_and_incomplete_gemini_are_not_success():
    with pytest.raises(ElevenLabsTranscriptionError): normalize_tbank_response({"results": [{"alternatives": []}]})
    with pytest.raises(ElevenLabsTranscriptionError): normalize_gemini_response({"status": "in_progress", "steps": []})
