"""Export existing output with synthetic storage/Drive; never run FFmpeg or providers."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
if "STUDIO_DATABASE_HOST" not in os.environ:
    os.environ.setdefault("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
from studio_api.audio_preparation_processor import process_claimed_audio_preparation_job
from studio_api.audio_preparation_service import (
    AudioPreparationServiceError, audio_preparation_payload, cancel_audio_preparation_job,
    claim_next_audio_preparation_job, complete_audio_drive_export, queue_audio_drive_export,
    renew_audio_preparation_lease,
    OUTPUT_SOURCE_NAMESPACE, recover_audio_preparation_output,
)
from studio_api.db import Base
from studio_api.models import AudioPreparationJob, AudioPreparationStatus, Project, Source, SourceType, SourceUploadStatus, User
from studio_api.source_deletion import deletion_readiness
from test_studio_audio_preparation_processor import isolated_storage_settings

NOW = datetime(2026, 9, 7, tzinfo=timezone.utc)
FOLDER = SimpleNamespace(id="folder", name="Результаты", web_view_url="https://drive.google.com/drive/folders/folder")
RESULT = SimpleNamespace(file_id="file", web_view_url="https://drive.google.com/file/d/file/view")


@pytest.fixture
def export_state(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr("studio_api.audio_preparation_processor.utcnow", lambda: NOW)
    with Session(engine, autoflush=False, expire_on_commit=False) as db:
        db.add(User(id="owner", email="owner@example.test"))
        db.add(Project(id="project", owner_user_id="owner", title="Studio"))
        source = Source(id="out", project_id="project", source_type=SourceType.local_upload,
            original_filename="Лекция 1. Предмет.flac", mime_type="audio/flac", size_bytes=5,
            s3_bucket="private", s3_object_key="ready", upload_status=SourceUploadStatus.uploaded,
            expires_at=(NOW + timedelta(days=1)).replace(tzinfo=None))
        job = AudioPreparationJob(id="job", project_id="project", owner_user_id="owner", title="Лекция",
            options_json="{}", output_source_id="out", status=AudioPreparationStatus.completed,
            current_stage="completed", progress_percent=100, output_duration_ms=8000)
        db.add_all([source, job]); db.commit()
        yield db, job, source
    engine.dispose()


def queue(db):
    result = queue_audio_drive_export(db, owner_user_id="owner", job_id="job", folder=FOLDER, now=NOW)
    db.commit()
    return result


def claim(db, owner="worker", now=NOW):
    result = claim_next_audio_preparation_job(db, lease_owner_id=owner, now=now, lease_ttl=timedelta(minutes=5))
    db.commit()
    return result


def process(db, job, tmp_path, uploader, *, payload=b"ready", settings=None):
    reads = []
    class Stream:
        def __init__(self): self.body = BytesIO(payload)
        def iter_chunks(self, size):
            while chunk := self.body.read(size): yield chunk
        def close(self): self.body.close()
    class Storage:
        def open_read(self, key):
            reads.append(key)
            return Stream()
    @contextmanager
    def temp_directory_factory(prefix):
        yield str(tmp_path)
    def no_media(*args, **kwargs):
        pytest.fail("Export must not probe or transcode media")
    result = process_claimed_audio_preparation_job(db, job_id=job.id, lease_owner_id=job.lease_owner_id,
        lease_generation=job.lease_generation, settings=settings or isolated_storage_settings(), now=NOW,
        storage_factory=lambda config: Storage(), drive_token_resolver=lambda *args, **kwargs: "synthetic",
        drive_uploader=uploader, runner=no_media, temp_directory_factory=temp_directory_factory)
    return result, reads


def test_export_preserves_ready_output_and_is_idempotent(export_state, tmp_path):
    db, job, source = export_state
    queue(db); queue(db)
    assert job.status is AudioPreparationStatus.completed
    assert job.current_stage == "google_drive_export_queued"
    assert audio_preparation_payload(job, now=NOW)["output"]["download_ready"] is True
    # Waiting without a lease cannot retain a source indefinitely. Protection
    # starts when a worker actually claims the export and lasts through I/O.
    assert deletion_readiness(db, source, now=NOW).value == "available"
    claimed = claim(db)
    assert deletion_readiness(db, source, now=NOW).value == "audio_preparation_uses_source"
    assert claim(db, "second-worker") is None
    seen = []
    def uploader(token, **kwargs):
        seen.append((kwargs["path"].read_bytes(), kwargs["filename"], kwargs["idempotency_key"], kwargs["folder_id"]))
        return RESULT
    result, reads = process(db, claimed, tmp_path, uploader)
    assert result.output_created is False
    assert reads == ["ready"]
    assert seen == [(b"ready", "Лекция 1. Предмет.flac", "job", "folder")]
    assert job.output_source_id == source.id and job.output_duration_ms == 8000
    assert job.output_drive_file_id == "file"
    assert deletion_readiness(db, source, now=NOW).value == "available"
    queue(db)
    assert claim(db) is None


@pytest.mark.parametrize("failure", ["expired", "deleted", "wrong-project", "unfinished", "foreign-owner"])
def test_export_rejects_unavailable_or_foreign_result(export_state, failure):
    db, job, source = export_state
    if failure == "expired": source.expires_at = NOW.replace(tzinfo=None)
    if failure == "deleted": source.deleted_at = NOW.replace(tzinfo=None)
    if failure == "wrong-project": source.project_id = "other"
    if failure == "unfinished": job.status = AudioPreparationStatus.preview_ready
    db.commit()
    with pytest.raises(AudioPreparationServiceError):
        queue_audio_drive_export(db, owner_user_id="stranger" if failure == "foreign-owner" else "owner", job_id="job", folder=FOLDER, now=NOW)
    db.rollback()
    assert job.current_stage != "google_drive_export_queued"


def test_failed_export_can_retry_without_losing_output_or_changing_target(export_state, tmp_path):
    db, job, source = export_state
    queue(db); claim(db)
    def fail(*args, **kwargs): raise RuntimeError("network outcome unknown")
    with pytest.raises(Exception): process(db, job, tmp_path, fail)
    assert job.status is AudioPreparationStatus.completed
    assert job.current_stage == "google_drive_export_failed"
    assert job.output_source_id == source.id
    with pytest.raises(AudioPreparationServiceError):
        queue_audio_drive_export(db, owner_user_id="owner", job_id="job", folder=SimpleNamespace(id="other", name="Other", web_view_url="https://drive.google.com/drive/folders/other"), now=NOW)
    db.rollback()
    queue(db); claim(db)
    def lookup_existing(token, **kwargs):
        assert kwargs["idempotency_key"] == "job"
        return RESULT
    process(db, job, tmp_path, lookup_existing)
    assert job.output_drive_file_id == "file"


@pytest.mark.parametrize("claimed", [False, True])
def test_cancel_export_retains_download_and_allows_explicit_retry(export_state, tmp_path, claimed):
    db, job, source = export_state
    queue(db)
    if claimed: claim(db)
    cancel_audio_preparation_job(db, owner_user_id="owner", job_id="job", now=NOW); db.commit()
    if claimed:
        with pytest.raises(AudioPreparationServiceError):
            process(db, job, tmp_path, lambda *args, **kwargs: pytest.fail("Cancelled export uploaded"))
    assert job.status is AudioPreparationStatus.completed
    assert job.current_stage == "google_drive_export_cancelled"
    assert audio_preparation_payload(job, now=NOW)["output"]["download_ready"]
    queue(db)
    assert job.cancel_requested_at is None


def test_export_lease_renewal_recovery_and_stale_completion(export_state):
    db, job, _ = export_state
    queue(db); claim(db)
    old_generation = job.lease_generation
    renew_audio_preparation_lease(db, job_id="job", lease_owner_id="worker", lease_generation=old_generation,
        now=NOW + timedelta(minutes=1), lease_ttl=timedelta(minutes=5)); db.commit()
    assert claim(db, "other", NOW + timedelta(minutes=5)) is None
    new_claim = claim(db, "other", NOW + timedelta(minutes=7))
    assert new_claim.lease_generation == old_generation + 1
    with pytest.raises(AudioPreparationServiceError):
        complete_audio_drive_export(db, job_id="job", lease_owner_id="worker", lease_generation=old_generation, file_id="stale", web_view_url=RESULT.web_view_url)
    db.rollback()
    assert job.output_drive_file_id is None


@pytest.mark.parametrize("problem", ["bucket", "size"])
def test_export_enforces_storage_identity_and_integrity(export_state, tmp_path, problem):
    db, job, source = export_state
    queue(db); claim(db)
    if problem == "bucket": source.s3_bucket = "foreign"
    else: source.size_bytes = 999
    db.commit()
    with pytest.raises(AudioPreparationServiceError):
        process(db, job, tmp_path, lambda *args, **kwargs: pytest.fail("Unsafe output uploaded"))
    assert job.current_stage == "google_drive_export_failed"


def test_cancel_arriving_after_drive_confirmation_keeps_the_confirmed_link(export_state, tmp_path):
    db, job, source = export_state
    queue(db); claim(db)
    def uploader(*args, **kwargs):
        cancel_audio_preparation_job(db, owner_user_id="owner", job_id="job", now=NOW)
        db.commit()
        return RESULT
    process(db, job, tmp_path, uploader)
    assert job.current_stage == "completed"
    assert job.output_drive_file_id == "file" and job.output_source_id == source.id
    assert job.cancel_requested_at is None


def test_queue_reloads_cached_job_before_changing_a_concurrent_destination(export_state):
    db, job, source = export_state
    with Session(db.bind) as other:
        updated = other.get(AudioPreparationJob, job.id)
        updated.output_drive_folder_name = "Concurrent"
        updated.output_drive_folder_id = "concurrent-folder"
        updated.output_drive_folder_url = "https://drive.google.com/drive/folders/concurrent-folder"
        updated.output_destination = "google_drive"
        updated.current_stage = "google_drive_export_queued"
        other.commit()
    assert job.output_drive_folder_id is None  # stale identity map in the request session
    with pytest.raises(AudioPreparationServiceError): queue(db)
    db.rollback()
    assert job.output_drive_folder_id == "concurrent-folder"


def legacy_output(db, job, source, status):
    import uuid
    from studio_api.source_storage import safe_filename
    source.id = str(uuid.uuid5(OUTPUT_SOURCE_NAMESPACE, job.id))
    source.reference_class = "audio_processing"
    source.s3_bucket = "audio-private"
    source.s3_object_key = f"audio-preparation/owner/{job.id}/{safe_filename(source.original_filename)}"
    source.expires_at = datetime(2099, 1, 1)
    job.output_source_id = None
    job.status = status
    job.current_stage = "google_drive_upload" if status is AudioPreparationStatus.processing else status.value
    job.output_destination = "google_drive"
    job.output_drive_folder_id = FOLDER.id
    job.output_drive_folder_name = FOLDER.name
    job.output_drive_folder_url = FOLDER.web_view_url
    job.lease_owner_id = "old-worker" if status is AudioPreparationStatus.processing else None
    job.lease_expires_at = (NOW + timedelta(minutes=5)).replace(tzinfo=None) if job.lease_owner_id else None
    db.commit()


@pytest.mark.parametrize("status", [AudioPreparationStatus.processing, AudioPreparationStatus.failed, AudioPreparationStatus.cancelled])
def test_legacy_output_recovery_preserves_bytes_and_active_lease(export_state, status):
    db, job, source = export_state
    legacy_output(db, job, source, status)
    lease = job.lease_owner_id, job.lease_generation, job.lease_expires_at
    assert audio_preparation_payload(job, now=NOW)["recoverable_output"] is True
    with pytest.raises(AudioPreparationServiceError):
        recover_audio_preparation_output(db, owner_user_id="other", job_id=job.id, now=NOW)
    result = recover_audio_preparation_output(db, owner_user_id="owner", job_id=job.id, now=NOW)
    db.commit()
    assert result.status is AudioPreparationStatus.completed and result.output_source_id == source.id
    assert (result.lease_owner_id, result.lease_generation, result.lease_expires_at) == lease
    assert recover_audio_preparation_output(db, owner_user_id="owner", job_id=job.id, now=NOW).output_source_id == source.id
    if status is AudioPreparationStatus.processing:
        assert result.current_stage == "google_drive_upload"
        assert claim(db, owner="other-worker") is None
    else:
        assert result.current_stage in {"google_drive_export_failed", "google_drive_export_cancelled"}


def test_legacy_expired_claim_exports_existing_bytes_without_transcoding(export_state, tmp_path):
    db, job, source = export_state
    legacy_output(db, job, source, AudioPreparationStatus.processing)
    generation = job.lease_generation
    claim(db, now=NOW + timedelta(minutes=6))
    assert job.status is AudioPreparationStatus.completed and job.lease_generation == generation + 1
    result, reads = process(db, job, tmp_path, lambda *args, **kwargs: RESULT)
    assert result.output_created is False and reads == [source.s3_object_key]
    assert job.output_drive_file_id == RESULT.file_id


@pytest.mark.parametrize("invalid", ["foreign-project", "wrong-key", "expired", "deleted"])
def test_legacy_recovery_rejects_unusable_or_unrelated_source(export_state, invalid):
    db, job, source = export_state
    legacy_output(db, job, source, AudioPreparationStatus.processing)
    if invalid == "foreign-project": source.project_id = "other-project"
    if invalid == "wrong-key": source.s3_object_key = "unrelated-object"
    if invalid == "expired": source.expires_at = (NOW - timedelta(seconds=1)).replace(tzinfo=None)
    if invalid == "deleted": source.deleted_at = NOW.replace(tzinfo=None)
    db.commit()
    with pytest.raises(AudioPreparationServiceError):
        recover_audio_preparation_output(db, owner_user_id="owner", job_id=job.id, now=NOW)
    assert job.status is AudioPreparationStatus.processing and job.output_source_id is None
