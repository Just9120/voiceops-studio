"""Synthetic Drive revision contracts; no Google requests or source bytes."""
import hashlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
from studio_api import google_drive as drive
from studio_api.models import Base, Project, Source, SourceType, SourceUploadStatus
from studio_api.transcript_catalog import _drive_identity_sql, catalog_source_identity


def response(payload):
    result = io.BytesIO(json.dumps(payload).encode())
    result.headers = {}
    return result


def test_revision_metadata_and_content_address_the_same_immutable_revision(monkeypatch):
    requests = []
    digest = hashlib.md5(b"synthetic", usedforsecurity=False).hexdigest()

    def open_request(request, **kwargs):
        requests.append(request.full_url)
        assert request.get_header("Authorization") == "Bearer synthetic-token"
        if "fields=" in request.full_url:
            return response({"id": "revision-old", "mimeType": "audio/mpeg", "size": "9", "md5Checksum": digest})
        result = io.BytesIO(b"synthetic")
        result.headers = {"Content-Length": "9", "Content-Type": "audio/mpeg"}
        return result

    monkeypatch.setattr(drive, "urlopen", open_request)
    meta = drive.fetch_drive_file_metadata("synthetic-token", "recording", revision_id="revision-old")
    assert (meta.id, meta.head_revision_id, meta.md5_checksum) == ("recording", "revision-old", digest)
    content = drive.fetch_drive_file_content("synthetic-token", "recording", revision_id="revision-old")
    try:
        assert b"".join(content.iter_chunks(3)) == b"synthetic"
    finally:
        content.close()
    assert len(requests) == 2
    assert all(urlsplit(url).path.endswith("/recording/revisions/revision-old") for url in requests)
    assert parse_qs(urlsplit(requests[1]).query) == {"alt": ["media"]}


@pytest.mark.parametrize("status", [403, 404, 410])
def test_missing_or_denied_revision_never_falls_back_to_latest(monkeypatch, status):
    requests = []

    def refuse(request, **kwargs):
        requests.append(request.full_url)
        raise HTTPError(request.full_url, status, "synthetic", {}, None)

    monkeypatch.setattr(drive, "urlopen", refuse)
    with pytest.raises(drive.GoogleDriveContentError):
        drive.fetch_drive_file_content("synthetic-token", "recording", revision_id="old")
    assert len(requests) == 1 and "/revisions/old?" in requests[0]


@pytest.mark.parametrize("field,value", [("headRevisionId", "../latest"), ("headRevisionId", ""), ("md5Checksum", "bad"), ("md5Checksum", 42)])
def test_malformed_version_metadata_is_not_treated_as_unversioned(field, value):
    with pytest.raises(drive.GoogleDriveMetadataError):
        drive.normalize_drive_file_metadata({"id": "recording", "mimeType": "audio/mpeg", field: value})


def test_catalog_version_identity_matches_sql_and_separates_replaced_and_legacy_files():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    old = Source(id="old", project_id="p", source_type=SourceType.google_drive,
        drive_file_id="same-file", original_filename="call.mp3", drive_revision_id="v1", drive_md5_checksum="a"*32)
    same = Source(id="reselected", project_id="p", source_type=SourceType.google_drive,
        drive_file_id="same-file", original_filename="call.mp3", drive_revision_id="v1", drive_md5_checksum="a"*32)
    changed = Source(id="new", project_id="p", source_type=SourceType.google_drive,
        drive_file_id="same-file", original_filename="call.mp3", drive_revision_id="v2", drive_md5_checksum="b"*32)
    legacy = Source(id="legacy", project_id="p", source_type=SourceType.google_drive,
        drive_file_id="same-file", original_filename="call.mp3")
    checksum_only = Source(id="checksum", project_id="p", source_type=SourceType.google_drive,
        drive_file_id="same-file", original_filename="call.mp3", drive_md5_checksum="c"*32)
    assert catalog_source_identity(old) == catalog_source_identity(same)
    assert len({catalog_source_identity(item) for item in (old, changed, legacy, checksum_only)}) == 4
    with engine.begin() as connection:
        for item in (old, changed, legacy, checksum_only):
            connection.execute(Source.__table__.insert().values(id=item.id, project_id="p", source_type=item.source_type,
                original_filename=item.original_filename, drive_file_id=item.drive_file_id,
                drive_revision_id=item.drive_revision_id, drive_md5_checksum=item.drive_md5_checksum))
        rows = dict(connection.execute(select(Source.id, _drive_identity_sql(Source))).all())
    assert rows == {item.id: catalog_source_identity(item).value for item in (old, changed, legacy, checksum_only)}
    engine.dispose()


def test_postgres_version_grouping_has_no_independently_numbered_literal_parameters():
    from sqlalchemy.dialects import postgresql
    query = select(_drive_identity_sql(Source)).group_by(_drive_identity_sql(Source))
    compiled = query.compile(dialect=postgresql.dialect())
    assert not compiled.params
    selection, grouping = str(compiled).split("GROUP BY")
    assert selection.split("SELECT ", 1)[1].split(" AS ", 1)[0].strip() == grouping.strip()


@pytest.mark.parametrize("wrong_bytes", [False, True])
def test_audio_regeneration_reads_pinned_revision_and_rejects_same_size_replacement(tmp_path, wrong_bytes):
    from studio_api.audio_result_rendering import materialize_audio_inputs
    from studio_api.audio_preparation_service import AudioPreparationServiceError
    data = b"original"
    source = Source(id="s", project_id="p", source_type=SourceType.google_drive,
        original_filename="clip.mp3", mime_type="audio/mpeg", size_bytes=len(data),
        upload_status=SourceUploadStatus.uploaded, drive_file_id="file", drive_revision_id="v1",
        drive_md5_checksum=hashlib.md5(data, usedforsecurity=False).hexdigest())
    job = SimpleNamespace(project_id="p", owner_user_id="owner", inputs=[SimpleNamespace(source=source, position=0)])
    project = Project(id="p", owner_user_id="owner", title="synthetic")
    settings = SimpleNamespace(source_max_upload_bytes=100)
    calls, closed = [], []

    class Stream:
        def iter_chunks(self, size):
            yield b"replaced" if wrong_bytes else data
        def close(self):
            closed.append(True)

    def fetch(token, file_id, *, revision_id):
        calls.append((file_id, revision_id))
        return Stream()

    def render():
        return materialize_audio_inputs(SimpleNamespace(get=lambda *args: project), job=job, root=tmp_path,
            settings=settings, storage_factory=None, drive_token_resolver=lambda *a, **k: "synthetic", drive_content_fetcher=fetch)

    if wrong_bytes:
        with pytest.raises(AudioPreparationServiceError, match="source_unavailable"):
            render()
    else:
        assert render()[0].read_bytes() == data
    assert calls == [("file", "v1")] and closed == [True]
