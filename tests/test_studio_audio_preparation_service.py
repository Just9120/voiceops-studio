from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))
if "STUDIO_DATABASE_HOST" not in os.environ:
    os.environ.setdefault("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")

from studio_api.audio_preparation_service import (
    AudioPreparationServiceError,
    AudioPreparationServiceReason,
    audio_preparation_payload,
    cancel_audio_preparation_job,
    claim_next_audio_preparation_job,
    complete_audio_preview,
    create_audio_preparation_job,
    load_owned_audio_preparation_job,
    renew_audio_preparation_lease,
    start_audio_preparation_job,
)
from studio_api.db import Base
from studio_api.models import (
    AudioPreparationStatus,
    Project,
    Source,
    SourceType,
    SourceUploadStatus,
    User,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def seed(db):
    owner = User(id="owner", email="owner@example.test")
    stranger = User(id="stranger", email="stranger@example.test")
    project = Project(id="project", owner_user_id=owner.id, title="Рабочая папка")
    other_project = Project(id="other-project", owner_user_id=stranger.id, title="Чужая папка")
    early = Source(
        id="early",
        project_id=project.id,
        source_type=SourceType.local_upload,
        original_filename="early.wav",
        mime_type="audio/wav",
        size_bytes=10,
        s3_bucket="private-bucket",
        s3_object_key="private/early",
        upload_status=SourceUploadStatus.uploaded,
        source_created_at=datetime(2026, 1, 1, 10, 0),
        source_created_at_provenance="embedded_media_metadata",
        expires_at=datetime(2026, 9, 1),
    )
    late = Source(
        id="late",
        project_id=project.id,
        source_type=SourceType.google_drive,
        original_filename="late.flac",
        mime_type="audio/flac",
        size_bytes=20,
        drive_file_id="private-drive-id",
        upload_status=SourceUploadStatus.uploaded,
        source_created_at=datetime(2026, 1, 2, 10, 0),
        source_created_at_provenance="google_drive_created_time",
        expires_at=datetime(2026, 9, 1),
    )
    private = Source(
        id="private",
        project_id=other_project.id,
        source_type=SourceType.local_upload,
        original_filename="secret.wav",
        mime_type="audio/wav",
        size_bytes=10,
        s3_bucket="private-bucket",
        s3_object_key="private/secret",
        upload_status=SourceUploadStatus.uploaded,
        expires_at=datetime(2026, 9, 1),
    )
    db.add_all([owner, stranger, project, other_project, early, late, private])
    db.commit()
    return owner, stranger, project, early, late, private


def create(db, *, source_ids=None, ephemeral=None, manual_order=False, destination="download"):
    folder = (
        SimpleNamespace(folder_id="folder-id", folder_url="https://drive.google.com/drive/folders/folder-id", folder_name="Результаты")
        if destination == "google_drive"
        else None
    )
    return create_audio_preparation_job(
        db,
        owner_user_id="owner",
        project_id="project",
        title="Запись созвона",
        source_ids=source_ids or ["late", "early"],
        ephemeral_source_ids=set(ephemeral or []),
        manual_order=manual_order,
        options_payload={"preset": "call", "output_format": "flac"},
        output_destination=destination,
        output_folder=folder,
        now=datetime(2026, 8, 24, 20, 0, tzinfo=timezone.utc),
    )


def test_create_defaults_to_authoritative_creation_order_and_safe_snapshot(db):
    seed(db)
    job = create(db, destination="google_drive")
    assert job.status is AudioPreparationStatus.preview_queued
    assert [item.source_id for item in job.inputs] == ["early", "late"]
    assert job.output_drive_folder_id == "folder-id"
    assert json.loads(job.options_json)["preset"] == "call"


def test_manual_order_is_preserved(db):
    seed(db)
    job = create(db, manual_order=True)
    assert [item.source_id for item in job.inputs] == ["late", "early"]


@pytest.mark.parametrize("days", [3, 7, 30])
def test_audio_reference_preserves_selected_upload_retention(db, days):
    seed(db)
    deadline = datetime(2026, 8, 24, 20, 0) + timedelta(days=days)
    db.get(Source, "early").expires_at = deadline
    job = create(db, source_ids=["early"], ephemeral=["early"])
    source = db.get(Source, "early")
    assert source.expires_at == deadline
    assert job.inputs[0].ephemeral_reference is True


def test_drive_source_cannot_be_marked_ephemeral(db):
    seed(db)
    with pytest.raises(AudioPreparationServiceError) as caught:
        create(db, source_ids=["late"], ephemeral=["late"])
    assert caught.value.reason is AudioPreparationServiceReason.invalid_sources


def test_owner_and_project_boundaries_fail_closed(db):
    seed(db)
    with pytest.raises(AudioPreparationServiceError) as caught:
        create(db, source_ids=["private"])
    assert caught.value.reason is AudioPreparationServiceReason.source_unavailable
    job = create(db, source_ids=["early"])
    db.commit()
    with pytest.raises(AudioPreparationServiceError) as hidden:
        load_owned_audio_preparation_job(db, owner_user_id="stranger", job_id=job.id)
    assert hidden.value.reason is AudioPreparationServiceReason.not_found


def test_claim_preview_complete_start_and_processing_claim_are_durable(db):
    seed(db)
    job = create(db, source_ids=["early"])
    db.commit()
    claimed = claim_next_audio_preparation_job(
        db,
        lease_owner_id="worker",
        now=datetime(2026, 8, 24, 20, 1),
        lease_ttl=timedelta(minutes=10),
    )
    assert claimed.id == job.id
    assert claimed.status is AudioPreparationStatus.analyzing
    generation = claimed.lease_generation
    db.commit()
    preview = complete_audio_preview(
        db,
        job_id=job.id,
        lease_owner_id="worker",
        lease_generation=generation,
        total_input_duration_ms=60_000,
        estimated_output_duration_ms=50_000,
        copy_compatible=True,
    )
    assert preview.status is AudioPreparationStatus.preview_ready
    db.commit()
    queued = start_audio_preparation_job(db, owner_user_id="owner", job_id=job.id)
    assert queued.status is AudioPreparationStatus.queued
    db.commit()
    processing = claim_next_audio_preparation_job(
        db,
        lease_owner_id="worker-2",
        now=datetime(2026, 8, 24, 20, 2),
        lease_ttl=timedelta(minutes=10),
    )
    assert processing.status is AudioPreparationStatus.processing
    assert processing.lease_generation == generation + 1


def test_trim_edit_is_owner_scoped_preview_only_and_preserves_source(db):
    from studio_api.audio_preparation_service import update_audio_trim, deserialize_options
    seed(db)
    job = create(db, source_ids=["early"])
    db.commit()
    with pytest.raises(AudioPreparationServiceError):
        update_audio_trim(db, owner_user_id="owner", job_id=job.id, start_seconds=1, end_seconds=20, output_format="wav")
    job.status = AudioPreparationStatus.preview_ready
    job.total_input_duration_ms = 60_000
    job.estimated_output_duration_ms = 60_000
    job.copy_compatible = True
    db.commit()
    with pytest.raises(AudioPreparationServiceError) as caught:
        update_audio_trim(db, owner_user_id="stranger", job_id=job.id, start_seconds=1, end_seconds=20, output_format="wav")
    assert caught.value.reason is AudioPreparationServiceReason.not_found
    updated = update_audio_trim(db, owner_user_id="owner", job_id=job.id, start_seconds=10.25, end_seconds=40.5, output_format="flac")
    db.commit()
    db.expire_all()
    assert deserialize_options(updated).trim_start_seconds == 10.25
    assert updated.estimated_output_duration_ms == 30_250
    assert db.get(Source, "early").original_filename == "early.wav"
    updated.download_slot = 1
    db.commit()
    with pytest.raises(AudioPreparationServiceError):
        update_audio_trim(db, owner_user_id="owner", job_id=job.id, start_seconds=0, end_seconds=None, output_format="wav")


def test_trim_reanalyzes_truncated_silence_snapshot_instead_of_guessing(db):
    import json
    from studio_api.audio_preparation_service import update_audio_trim
    seed(db)
    job = create(db, source_ids=["early"])
    job.status = AudioPreparationStatus.preview_ready
    job.total_input_duration_ms = 60_000
    job.estimated_output_duration_ms = 55_000
    job.copy_compatible = True
    payload = json.loads(job.options_json)
    payload["silence_enabled"] = True
    job.options_json = json.dumps(payload)
    job.visual_analysis_json = json.dumps({"sources": [{"duration_seconds": 60, "intervals_truncated": True, "silences": []}]})
    db.commit()
    updated = update_audio_trim(db, owner_user_id="owner", job_id=job.id, start_seconds=10, end_seconds=40, output_format="wav")
    assert updated.status is AudioPreparationStatus.preview_queued
    assert updated.estimated_output_duration_ms is None
    assert updated.current_stage == "preview_queued" and updated.progress_percent == 0


def test_start_requires_preview_ready_and_cancel_is_idempotent(db):
    seed(db)
    job = create(db, source_ids=["early"])
    with pytest.raises(AudioPreparationServiceError) as caught:
        start_audio_preparation_job(db, owner_user_id="owner", job_id=job.id)
    assert caught.value.reason is AudioPreparationServiceReason.invalid_state
    cancelled = cancel_audio_preparation_job(
        db,
        owner_user_id="owner",
        job_id=job.id,
        now=datetime(2026, 8, 24, 20, 5),
    )
    assert cancelled.status is AudioPreparationStatus.cancelled
    again = cancel_audio_preparation_job(
        db,
        owner_user_id="owner",
        job_id=job.id,
        now=datetime(2026, 8, 24, 20, 6),
    )
    assert again.status is AudioPreparationStatus.cancelled


def test_browser_payload_omits_source_ids_storage_and_drive_identity(db):
    seed(db)
    job = create(db, source_ids=["early"], destination="google_drive")
    payload = audio_preparation_payload(job)
    rendered = json.dumps(payload, ensure_ascii=False)
    assert payload["inputs"] == [
        {
            "position": 0,
            "filename": "early.wav",
            "source_type": "local_upload",
            "ephemeral_reference": False,
        }
    ]
    for private in ["early\"", "private-bucket", "private/early", "private-drive-id"]:
        assert private not in rendered


def test_active_lease_can_be_renewed_only_by_exact_owner_and_generation(db):
    seed(db)
    job = create(db, source_ids=["early"])
    db.commit()
    claimed = claim_next_audio_preparation_job(db, lease_owner_id="worker", now=datetime(2026, 8, 24, 20, 1), lease_ttl=timedelta(minutes=10))
    generation = claimed.lease_generation
    db.commit()
    renewed = renew_audio_preparation_lease(db, job_id=job.id, lease_owner_id="worker", lease_generation=generation, now=datetime(2026, 8, 24, 20, 5), lease_ttl=timedelta(minutes=10))
    assert renewed.lease_expires_at == datetime(2026, 8, 24, 20, 15)
    with pytest.raises(AudioPreparationServiceError) as caught:
        renew_audio_preparation_lease(db, job_id=job.id, lease_owner_id="other", lease_generation=generation, now=datetime(2026, 8, 24, 20, 6), lease_ttl=timedelta(minutes=10))
    assert caught.value.reason is AudioPreparationServiceReason.lease_unavailable


def test_aggregate_audio_admission_fails_before_job_or_retention_mutation(db):
    from studio_api.models import AudioPreparationJob
    _, _, _, early, late, _ = seed(db)
    old_expiry = early.expires_at
    with pytest.raises(AudioPreparationServiceError, match="input_too_large"):
        create_audio_preparation_job(db, owner_user_id="owner", project_id="project", title="Test",
            source_ids=[early.id, late.id], ephemeral_source_ids={early.id}, manual_order=True,
            options_payload={"output_format": "flac"}, output_destination="download", output_folder=None,
            now=datetime(2026, 8, 24), max_total_input_bytes=29)
    assert db.query(AudioPreparationJob).count() == 0
    assert early.expires_at == old_expiry
