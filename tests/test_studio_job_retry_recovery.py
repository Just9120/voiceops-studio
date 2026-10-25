import base64
import os
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


@pytest.fixture
def studio_model_modules(monkeypatch, tmp_path):
    password_file = tmp_path / "studio_test_pg_password"
    master_key_file = tmp_path / "studio_test_master_key"
    password_file.write_text(os.environ.get("STUDIO_TEST_POSTGRES_PASSWORD", "studio_test_password"), encoding="utf-8")
    master_key_file.write_text(base64.b64encode(b"1" * 32).decode(), encoding="utf-8")
    monkeypatch.setenv("STUDIO_DATABASE_SCHEME", "postgresql+psycopg")
    monkeypatch.setenv("STUDIO_DATABASE_HOST", "127.0.0.1")
    monkeypatch.setenv("STUDIO_DATABASE_PORT", "5432")
    monkeypatch.setenv("STUDIO_DATABASE_NAME", "studio_test")
    monkeypatch.setenv("STUDIO_DATABASE_USER", "studio_test")
    monkeypatch.setenv("STUDIO_POSTGRES_PASSWORD_FILE", str(password_file))
    monkeypatch.setenv("STUDIO_CREDENTIAL_MASTER_KEY_FILE", str(master_key_file))
    from studio_api.job_retry_recovery import MAX_PROCESSING_ATTEMPTS, PRE_PROVIDER_SAFE_FAILURES, SAFE_PRE_TRANSPORT_FAILURES, SAFE_PROVIDER_FAILURES, UNCERTAIN_PROVIDER_FAILURES
    from studio_api.models import SourceAttemptRetryDisposition, SourceAttemptStage, TranscriptionJobSourceAttempt
    return {
        "MAX_PROCESSING_ATTEMPTS": MAX_PROCESSING_ATTEMPTS,
        "SAFE_PROVIDER_FAILURES": SAFE_PROVIDER_FAILURES,
        "SAFE_PRE_TRANSPORT_FAILURES": SAFE_PRE_TRANSPORT_FAILURES,
        "UNCERTAIN_PROVIDER_FAILURES": UNCERTAIN_PROVIDER_FAILURES,
        "PRE_PROVIDER_SAFE_FAILURES": PRE_PROVIDER_SAFE_FAILURES,
        "SourceAttemptRetryDisposition": SourceAttemptRetryDisposition,
        "SourceAttemptStage": SourceAttemptStage,
        "TranscriptionJobSourceAttempt": TranscriptionJobSourceAttempt,
    }


def test_retry_recovery_model_metadata_contract(studio_model_modules):
    table = studio_model_modules["TranscriptionJobSourceAttempt"].__table__
    assert table.name == "transcription_job_source_attempts"
    assert studio_model_modules["MAX_PROCESSING_ATTEMPTS"] == 3
    assert {e.value for e in studio_model_modules["SourceAttemptStage"]} == {
        "prepared", "provider_request_started", "provider_response_returned", "google_handoff", "output_persisted", "failed"
    }
    assert {e.value for e in studio_model_modules["SourceAttemptRetryDisposition"]} == {
        "undetermined", "retry_safe", "provider_outcome_uncertain", "provider_result_lost", "output_reconciliation_required", "non_retryable", "completed"
    }
    assert {"provider_authentication_rejected", "provider_payment_required", "provider_scope_rejected", "provider_request_rejected", "provider_rate_limited"} <= studio_model_modules["SAFE_PROVIDER_FAILURES"]
    assert "provider_usage_accounting_unavailable" in studio_model_modules["SAFE_PRE_TRANSPORT_FAILURES"]
    assert "provider_usage_outcome_uncertain" not in studio_model_modules["SAFE_PRE_TRANSPORT_FAILURES"]
    assert {"provider_timeout", "provider_unavailable", "malformed_provider_response", "partial_provider_result", "unknown"} <= studio_model_modules["UNCERTAIN_PROVIDER_FAILURES"]
    assert {"ffmpeg_unavailable", "media_preparation_timeout", "media_preparation_failed", "prepared_media_too_large", "media_duration_unavailable", "media_duration_confirmation_required", "media_split_failed", "media_part_too_large"} <= studio_model_modules["PRE_PROVIDER_SAFE_FAILURES"]
    assert "media_duration_too_long" not in studio_model_modules["PRE_PROVIDER_SAFE_FAILURES"]
    assert "media_clip_out_of_bounds" not in studio_model_modules["PRE_PROVIDER_SAFE_FAILURES"]
    assert {"owner_user_id", "project_id", "job_id", "job_source_id", "attempt_number", "stage", "retry_disposition"} <= set(table.c.keys())
    assert {tuple(c.name for c in constraint.columns) for constraint in table.constraints if getattr(constraint, "columns", None)} >= {("job_source_id", "attempt_number")}
    indexes = {idx.name: tuple(col.name for col in idx.columns) for idx in table.indexes}
    assert indexes["ix_source_attempts_job_id"] == ("job_id",)
    assert indexes["ix_source_attempts_job_source_id"] == ("job_source_id",)
    assert indexes["ix_source_attempts_retry_disposition"] == ("retry_disposition",)
    assert indexes["ix_source_attempts_job_retry_disposition"] == ("job_id", "retry_disposition")


def test_alembic_single_head_is_partial_provider_checkpoints():
    cfg = Config("apps/studio-api/alembic.ini")
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["0043_yandex_disk"]
    assert script.get_current_head() == "0043_yandex_disk"


def test_partial_provider_actions_require_explicit_cost_confirmation():
    from studio_api.job_retry_recovery import (
        RetryReadiness,
        RetryReason,
        requires_provider_cost_confirmation,
    )

    common = dict(
        available=True,
        attempt_count=1,
        max_attempts=3,
        missing_output_count=1,
        retry_safe_source_count=1,
    )
    assert requires_provider_cost_confirmation(
        RetryReadiness(reason=RetryReason.partial_provider_resume_available, **common)
    )
    assert requires_provider_cost_confirmation(
        RetryReadiness(reason=RetryReason.partial_provider_restart_available, **common)
    )
    assert not requires_provider_cost_confirmation(
        RetryReadiness(reason=RetryReason.available, **common)
    )

from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def sqlite_db(monkeypatch):
    monkeypatch.setenv("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    from studio_api.config import get_settings
    get_settings.cache_clear()
    from studio_api.db import Base
    import studio_api.models  # noqa
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close(); Base.metadata.drop_all(engine); engine.dispose()


def _job_with_sources(db, *, source_count=2, status="processing", attempt_count=1, expired=False):
    from studio_api import models as m
    now = datetime(2026, 1, 2, 3, 4, 5)
    user = m.User(email=f"retry-{id(db)}-{source_count}-{attempt_count}-{status}@example.com", role=m.UserRole.user, status=m.UserStatus.active)
    db.add(user); db.flush()
    project = m.Project(owner_user_id=user.id, title="p", output_drive_folder_id="folder")
    db.add(project); db.flush()
    job = m.TranscriptionJob(project_id=project.id, owner_user_id=user.id, status=getattr(m.JobStatus, status), provider="elevenlabs", provider_credential_id="cred", output_drive_folder_id="folder", lease_owner_id="worker", lease_generation=7, claimed_at=now, lease_expires_at=now + (-timedelta(seconds=1) if expired else timedelta(minutes=10)), attempt_count=attempt_count, started_at=now)
    db.add(job); db.flush()
    rels=[]
    for idx in range(source_count):
        src = m.Source(project_id=project.id, source_type=m.SourceType.local_upload, original_filename=f"s{idx}.mp3", mime_type="audio/mpeg", size_bytes=1, s3_bucket="bucket", s3_object_key=f"key-{idx}", upload_status=m.SourceUploadStatus.uploaded, uploaded_at=now, expires_at=now+timedelta(hours=1))
        db.add(src); db.flush()
        rel = m.TranscriptionJobSource(job_id=job.id, source_id=src.id, position=idx, status=m.JobSourceStatus.queued)
        db.add(rel); db.flush(); rels.append(rel)
    db.commit(); return m, now, user, project, job, rels


def _attempt(db, m, job, rel, *, number=None, stage=None, disposition=None, started=False, returned=False):
    now = datetime(2026, 1, 2, 3, 4, 5)
    row = m.TranscriptionJobSourceAttempt(owner_user_id=job.owner_user_id, project_id=job.project_id, job_id=job.id, job_source_id=rel.id, attempt_number=number or job.attempt_count, stage=stage or m.SourceAttemptStage.prepared, retry_disposition=disposition or m.SourceAttemptRetryDisposition.undetermined, provider_request_started_at=now if started else None, provider_response_returned_at=now if returned else None, created_at=now, updated_at=now)
    db.add(row); db.commit(); return row


def test_prepare_current_attempt_sources_creates_all_missing_and_is_idempotent(sqlite_db):
    from studio_api.job_retry_recovery import prepare_current_attempt_sources
    m, now, _user, _project, job, rels = _job_with_sources(sqlite_db, source_count=2)
    created = prepare_current_attempt_sources(sqlite_db, job_id=job.id, lease_owner_id="worker", lease_generation=7, now=now)
    sqlite_db.commit()
    assert [row.job_source_id for row in created] == [rel.id for rel in rels]
    assert sqlite_db.query(m.TranscriptionJobSourceAttempt).count() == 2
    assert prepare_current_attempt_sources(sqlite_db, job_id=job.id, lease_owner_id="worker", lease_generation=7, now=now) == ()
    sqlite_db.commit()
    assert sqlite_db.query(m.TranscriptionJobSourceAttempt).count() == 2


def test_prepare_current_attempt_sources_skips_outputs_blocks_reconciliation_and_later_stage(sqlite_db):
    from studio_api.job_retry_recovery import prepare_current_attempt_sources
    m, now, _user, _project, job, rels = _job_with_sources(sqlite_db, source_count=3)
    sqlite_db.add(m.TranscriptionJobOutput(job_id=job.id, job_source_id=rels[0].id, document_id="doc-1", web_view_url="https://docs.example/doc-1", output_drive_folder_id="folder", output_kind="google_docs_transcript", transcript_standard="transcript_doc_v1.2", document_character_count=1, document_created_at=now, persisted_at=now, lease_generation=7))
    _attempt(sqlite_db, m, job, rels[2], stage=m.SourceAttemptStage.provider_request_started, disposition=m.SourceAttemptRetryDisposition.undetermined, started=True)
    with pytest.raises(RuntimeError, match="retry_state_not_prepared"):
        prepare_current_attempt_sources(sqlite_db, job_id=job.id, lease_owner_id="worker", lease_generation=7, now=now)
    sqlite_db.rollback()
    sqlite_db.query(m.TranscriptionJobSourceAttempt).delete(); sqlite_db.flush()
    sqlite_db.add(m.TranscriptionOutputReconciliation(owner_user_id=job.owner_user_id, project_id=job.project_id, job_id=job.id, job_source_id=rels[1].id, reconciliation_token="tok", lease_generation=7, attempt_number=1, status=m.OutputReconciliationStatus.reconciliation_required, expected_output_drive_folder_id="folder", expected_document_character_count=1, prepared_at=now, created_at=now, updated_at=now))
    sqlite_db.commit()
    with pytest.raises(RuntimeError, match="retry_state_reconciliation_exists"):
        prepare_current_attempt_sources(sqlite_db, job_id=job.id, lease_owner_id="worker", lease_generation=7, now=now)


def test_prepare_current_attempt_sources_requires_exact_processing_context_and_attempt_number(sqlite_db):
    from studio_api.job_retry_recovery import prepare_current_attempt_sources
    m, now, _user, _project, job, _rels = _job_with_sources(sqlite_db, source_count=1, attempt_count=0)
    with pytest.raises(RuntimeError, match="retry_state_invalid_attempt_number"):
        prepare_current_attempt_sources(sqlite_db, job_id=job.id, lease_owner_id="worker", lease_generation=7, now=now)
    job.attempt_count = 1; sqlite_db.commit()
    with pytest.raises(RuntimeError, match="retry_state_processing_context_invalid"):
        prepare_current_attempt_sources(sqlite_db, job_id=job.id, lease_owner_id="wrong", lease_generation=7, now=now)
    with pytest.raises(RuntimeError, match="retry_state_processing_context_invalid"):
        prepare_current_attempt_sources(sqlite_db, job_id=job.id, lease_owner_id="worker", lease_generation=8, now=now)


def test_pre_transport_accounting_failure_is_retry_safe_but_uncertain_outcome_is_not(sqlite_db):
    from studio_api.job_retry_recovery import classify_source_attempt_failure

    m, now, _user, _project, job, rels = _job_with_sources(
        sqlite_db, source_count=2
    )
    safe_attempt = _attempt(sqlite_db, m, job, rels[0], started=True)
    uncertain_attempt = _attempt(sqlite_db, m, job, rels[1], started=True)

    classify_source_attempt_failure(
        sqlite_db,
        job_id=job.id,
        job_source_id=rels[0].id,
        lease_owner_id="worker",
        lease_generation=7,
        failure_code="provider_usage_accounting_unavailable",
        now=now,
    )
    classify_source_attempt_failure(
        sqlite_db,
        job_id=job.id,
        job_source_id=rels[1].id,
        lease_owner_id="worker",
        lease_generation=7,
        failure_code="provider_usage_outcome_uncertain",
        now=now,
    )
    assert safe_attempt.retry_disposition == m.SourceAttemptRetryDisposition.retry_safe
    assert (
        uncertain_attempt.retry_disposition
        == m.SourceAttemptRetryDisposition.provider_outcome_uncertain
    )


def test_safe_provider_rejection_retains_user_facing_category(sqlite_db):
    from studio_api.job_retry_recovery import (
        classify_source_attempt_failure,
        compute_explicit_retry_readiness,
    )

    m, now, _user, _project, job, rels = _job_with_sources(
        sqlite_db,
        source_count=1,
    )
    _attempt(sqlite_db, m, job, rels[0], started=True)
    classify_source_attempt_failure(
        sqlite_db,
        job_id=job.id,
        job_source_id=rels[0].id,
        lease_owner_id="worker",
        lease_generation=7,
        failure_code="provider_scope_rejected",
        provider_failure_code="provider_scope_rejected",
        now=now,
    )
    job.status = m.JobStatus.failed
    job.lease_owner_id = None
    job.lease_expires_at = None
    sqlite_db.commit()

    readiness = compute_explicit_retry_readiness(sqlite_db, job, now=now)
    assert readiness.available is True
    assert readiness.reason.value == "available"
    assert readiness.provider_failure_code == "provider_scope_rejected"


def test_immutable_media_plan_cannot_be_replaced_or_mismatched_before_provider_start(sqlite_db):
    import json
    from studio_api.job_retry_recovery import mark_attempt_provider_started
    m, now, _user, _project, job, rels = _job_with_sources(sqlite_db, source_count=1)
    row = _attempt(sqlite_db, m, job, rels[0])
    plan = json.dumps({"version": 1, "parts": [
        {"part_index": 0, "start_seconds": 0, "end_seconds": 10},
        {"part_index": 1, "start_seconds": 8, "end_seconds": 20}]})
    row.provider_media_plan_json = plan; sqlite_db.commit()
    kwargs = dict(job_id=job.id, job_source_id=rels[0].id, lease_owner_id="worker", lease_generation=7, now=now)
    for proposed, count in [(plan, 3), (plan.replace('20', '21'), 2)]:
        with pytest.raises(RuntimeError, match="media_plan_conflict"):
            mark_attempt_provider_started(sqlite_db, **kwargs, total_parts=count, media_plan=proposed)
        assert row.stage == m.SourceAttemptStage.prepared and row.provider_media_plan_json == plan
    mark_attempt_provider_started(sqlite_db, **kwargs, total_parts=2, media_plan=plan)
    sqlite_db.commit()
    assert row.provider_media_plan_json == plan and row.stage == m.SourceAttemptStage.provider_request_started


def test_provider_part_progress_is_durable_monotonic_and_bounded(sqlite_db):
    from studio_api.job_retry_recovery import (
        mark_attempt_provider_part_completed,
        mark_attempt_provider_returned,
        mark_attempt_provider_started,
    )

    m, now, _user, _project, job, rels = _job_with_sources(
        sqlite_db,
        source_count=1,
    )
    _attempt(sqlite_db, m, job, rels[0])

    row = mark_attempt_provider_started(
        sqlite_db,
        job_id=job.id,
        job_source_id=rels[0].id,
        lease_owner_id="worker",
        lease_generation=7,
        total_parts=2,
        now=now,
    )
    sqlite_db.commit()
    assert (row.provider_completed_parts, row.provider_total_parts) == (0, 2)

    row = mark_attempt_provider_part_completed(
        sqlite_db,
        job_id=job.id,
        job_source_id=rels[0].id,
        lease_owner_id="worker",
        lease_generation=7,
        completed_parts=1,
        now=now,
    )
    sqlite_db.commit()
    assert row.provider_completed_parts == 1

    with pytest.raises(RuntimeError, match="provider_part_progress_invalid"):
        mark_attempt_provider_part_completed(
            sqlite_db,
            job_id=job.id,
            job_source_id=rels[0].id,
            lease_owner_id="worker",
            lease_generation=7,
            completed_parts=3,
            now=now,
        )
    sqlite_db.rollback()

    row = mark_attempt_provider_returned(
        sqlite_db,
        job_id=job.id,
        job_source_id=rels[0].id,
        lease_owner_id="worker",
        lease_generation=7,
        now=now,
    )
    sqlite_db.commit()
    assert row.provider_completed_parts == row.provider_total_parts == 2


def test_multisource_prepared_rows_allow_recovery_and_explicit_retry(sqlite_db):
    from studio_api.job_processing_lifecycle import recover_expired_processing_job
    from studio_api.job_retry_recovery import compute_explicit_retry_readiness, queue_retry
    m, now, _user, _project, job, rels = _job_with_sources(sqlite_db, source_count=2, expired=True)
    for rel in rels: _attempt(sqlite_db, m, job, rel)
    result = recover_expired_processing_job(sqlite_db, job_id=job.id, now=now)
    assert result.status == m.JobStatus.queued
    job.status = m.JobStatus.failed; job.lease_owner_id = None; job.lease_expires_at = None; job.terminal_dismissed_at = now; sqlite_db.commit()
    assert compute_explicit_retry_readiness(sqlite_db, job, now=now).available is True
    retry = queue_retry(sqlite_db, owner_user_id=job.owner_user_id, job_id=job.id, now=now)
    assert retry is not None and retry.transitioned is True
    assert retry.job.terminal_dismissed_at is None


@pytest.mark.parametrize("state", ["safe", "uncertain", "cancelled", "active"])
def test_real_worker_entry_recovers_expired_jobs_without_dispatch(sqlite_db, monkeypatch, state):
    from studio_api import audio_preparation_worker as worker
    from studio_api import job_processing_runner, transcript_maintenance_worker
    m, now, _user, _project, job, rels = _job_with_sources(sqlite_db, source_count=1, expired=state != "active")
    _attempt(sqlite_db, m, job, rels[0], started=state == "uncertain",
             stage=m.SourceAttemptStage.provider_request_started if state == "uncertain" else None)
    if state == "cancelled":
        job.cancel_requested_at = now
        sqlite_db.commit()
    monkeypatch.setattr(worker, "utcnow", lambda: now)
    monkeypatch.setattr(worker, "claim_next_and_process_audio_preparation", lambda *a, **k: None)
    monkeypatch.setattr(job_processing_runner, "claim_next_and_orchestrate_processing_job", lambda *a, **k: None)
    monkeypatch.setattr(transcript_maintenance_worker, "claim_next_and_process_transcript_maintenance", lambda *a, **k: None)
    worker.claim_next_studio_work(sqlite_db)
    assert job.status.value == {"safe": "queued", "uncertain": "failed", "cancelled": "cancelled", "active": "processing"}[state]
    if state == "uncertain":
        assert job.error_code == "provider_outcome_uncertain"
    assert job.attempt_count == 1


def test_expired_yandex_attempt_with_durable_operation_recovers_without_new_submit_authority(sqlite_db):
    from studio_api.job_processing_lifecycle import recover_expired_processing_job

    m, now, _user, _project, job, rels = _job_with_sources(
        sqlite_db,
        source_count=1,
        expired=True,
    )
    job.provider = "yandex"
    job.operating_mode = "standard"
    attempt = _attempt(
        sqlite_db,
        m,
        job,
        rels[0],
        stage=m.SourceAttemptStage.provider_request_started,
        disposition=m.SourceAttemptRetryDisposition.provider_outcome_uncertain,
        started=True,
    )
    sqlite_db.add(
        m.SttProviderOperation(
            owner_user_id=job.owner_user_id,
            project_id=job.project_id,
            job_id=job.id,
            job_source_id=rels[0].id,
            attempt_number=attempt.attempt_number,
            provider="yandex",
            operating_mode="standard",
            model="general",
            operation_id="operation-resume-safe",
            status="pending",
            submitted_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    sqlite_db.commit()

    result = recover_expired_processing_job(sqlite_db, job_id=job.id, now=now)

    assert result.status == m.JobStatus.queued
    assert sqlite_db.query(m.SttProviderOperation).count() == 1


def test_partial_output_preserved_and_prepared_next_source_is_safe(sqlite_db):
    from studio_api.job_retry_recovery import compute_explicit_retry_readiness, prepare_current_attempt_sources
    m, now, _user, _project, job, rels = _job_with_sources(sqlite_db, source_count=2, status="failed")
    job.lease_owner_id = None; job.lease_expires_at = None
    sqlite_db.add(m.TranscriptionJobOutput(job_id=job.id, job_source_id=rels[0].id, document_id="doc-1", web_view_url="https://docs.example/doc-1", output_drive_folder_id="folder", output_kind="google_docs_transcript", transcript_standard="transcript_doc_v1.2", document_character_count=1, document_created_at=now, persisted_at=now, lease_generation=7))
    _attempt(sqlite_db, m, job, rels[1])
    assert compute_explicit_retry_readiness(sqlite_db, job, now=now).available is True
    job.status = m.JobStatus.processing; job.lease_owner_id = "worker"; job.lease_expires_at = now + timedelta(minutes=1); sqlite_db.commit()
    assert prepare_current_attempt_sources(sqlite_db, job_id=job.id, lease_owner_id="worker", lease_generation=7, now=now) == ()
    assert sqlite_db.query(m.TranscriptionJobSourceAttempt).filter_by(job_source_id=rels[0].id).count() == 0


@pytest.mark.parametrize("source_count", [1, 2])
def test_cached_restore_does_not_hide_cost_of_an_unstarted_source(sqlite_db, source_count):
    from studio_api.job_retry_recovery import compute_explicit_retry_readiness, compute_expired_recovery_readiness, requires_provider_cost_confirmation
    m, now, _, _, job, rels = _job_with_sources(sqlite_db, source_count=source_count, status="failed")
    job.lease_owner_id = None
    job.lease_expires_at = None
    attempt = _attempt(sqlite_db, m, job, rels[0], stage=m.SourceAttemptStage.failed, disposition=m.SourceAttemptRetryDisposition.provider_result_lost, started=True)
    attempt.provider_total_parts = attempt.provider_completed_parts = 2
    for index in range(2):
        sqlite_db.add(m.TranscriptionProviderPartCheckpoint(
            owner_user_id=job.owner_user_id, project_id=job.project_id, job_id=job.id,
            job_source_id=rels[0].id, part_index=index, total_parts=2,
            timeline_offset_seconds=index * 8, duration_seconds=10,
            provider="elevenlabs", model="scribe_v2", ciphertext=b"synthetic", nonce=b"synthetic",
            key_id="key-v1", payload_hmac="a" * 64, created_at=now, expires_at=now + timedelta(hours=1),
        ))
    if source_count == 2:
        _attempt(sqlite_db, m, job, rels[1])
    sqlite_db.commit()
    readiness = compute_explicit_retry_readiness(sqlite_db, job, now=now)
    assert readiness.available
    assert readiness.reason.value == ("full_provider_restore_available" if source_count == 1 else "partial_provider_resume_available")
    assert requires_provider_cost_confirmation(readiness) == (source_count == 2)
    job.status = m.JobStatus.processing
    job.lease_expires_at = now - timedelta(seconds=1)
    assert not compute_expired_recovery_readiness(sqlite_db, job, now=now).available


@pytest.mark.parametrize("with_plan", [False, True])
def test_legacy_expired_partial_checkpoint_resumes_without_losing_returned_text(sqlite_db, with_plan):
    from studio_api.job_retry_recovery import compute_explicit_retry_readiness, queue_retry

    m, now, _user, _project, job, rels = _job_with_sources(
        sqlite_db,
        source_count=1,
        status="failed",
    )
    job.lease_owner_id = None
    job.lease_expires_at = None
    attempt = _attempt(
        sqlite_db,
        m,
        job,
        rels[0],
        stage=m.SourceAttemptStage.failed,
        disposition=m.SourceAttemptRetryDisposition.provider_outcome_uncertain,
        started=True,
    )
    attempt.failure_code = "partial_provider_result"
    attempt.provider_failure_code = "provider_rate_limited"
    attempt.provider_total_parts = 2
    attempt.provider_completed_parts = 1
    if with_plan:
        import json
        attempt.provider_media_plan_json = json.dumps({"version": 1, "parts": [
            {"part_index": 0, "start_seconds": 0, "end_seconds": 10},
            {"part_index": 1, "start_seconds": 8, "end_seconds": 20},
        ]})
    sqlite_db.add(
        m.TranscriptionProviderPartCheckpoint(
            owner_user_id=job.owner_user_id,
            project_id=job.project_id,
            job_id=job.id,
            job_source_id=rels[0].id,
            part_index=0,
            total_parts=2,
            timeline_offset_seconds=0,
            duration_seconds=10,
            provider="elevenlabs",
            model="scribe_v2",
            ciphertext=b"ciphertext",
            nonce=b"nonce",
            key_id="key-v1",
            payload_hmac="a" * 64,
            created_at=now - timedelta(hours=2),
            expires_at=now - timedelta(seconds=1),
        )
    )
    sqlite_db.commit()

    readiness = compute_explicit_retry_readiness(sqlite_db, job, now=now)
    assert readiness.available is True
    assert readiness.reason.value == "partial_provider_resume_available"
    assert readiness.resumable_provider_part_count == 1
    if with_plan:
        assert readiness.payload(job)["missing_provider_parts"] == [{"source_id": rels[0].source_id,
            "part_index": 1, "start_seconds": 8, "end_seconds": 20}]
    else:
        assert "missing_provider_parts" not in readiness.payload(job)
    queued = queue_retry(
        sqlite_db,
        owner_user_id=job.owner_user_id,
        job_id=job.id,
        now=now,
    )
    assert queued is not None and queued.transitioned is True
    assert sqlite_db.query(m.TranscriptionProviderPartCheckpoint).count() == 1


def test_confirmed_first_part_without_checkpoint_requires_explicit_full_restart(sqlite_db):
    from studio_api.job_retry_recovery import (
        compute_explicit_retry_readiness,
        requires_provider_cost_confirmation,
    )

    m, now, _user, _project, job, rels = _job_with_sources(
        sqlite_db,
        source_count=1,
        status="failed",
    )
    job.lease_owner_id = None
    job.lease_expires_at = None
    attempt = _attempt(
        sqlite_db,
        m,
        job,
        rels[0],
        stage=m.SourceAttemptStage.failed,
        disposition=m.SourceAttemptRetryDisposition.provider_outcome_uncertain,
        started=True,
    )
    attempt.failure_code = "partial_provider_result"
    attempt.provider_total_parts = 4
    attempt.provider_completed_parts = 0
    attempt.provider_accounting_status = "confirmed"
    attempt.provider_pending_part_index = None
    attempt.provider_pending_duration_ms = None
    attempt.provider_billed_duration_ms = 801_689
    sqlite_db.commit()

    readiness = compute_explicit_retry_readiness(sqlite_db, job, now=now)
    assert readiness.available is True
    assert readiness.reason.value == "partial_provider_restart_available"
    assert readiness.resumable_provider_part_count == 0
    assert readiness.provider_total_part_count == 4
    assert requires_provider_cost_confirmation(readiness) is True

    attempt.provider_accounting_status = "uncertain"
    sqlite_db.commit()
    uncertain = compute_explicit_retry_readiness(sqlite_db, job, now=now)
    assert uncertain.available is False
    assert uncertain.reason.value == "provider_outcome_uncertain"


def test_retired_checkpoint_cleanup_is_bounded_and_preserves_unfinished_text(sqlite_db):
    from studio_api.provider_part_checkpoints import (
        cleanup_expired_provider_part_checkpoints,
    )

    m, now, _user, _project, job, rels = _job_with_sources(
        sqlite_db,
        source_count=4,
        status="failed",
    )
    for index, relation in enumerate(rels):
        sqlite_db.add(
            m.TranscriptionProviderPartCheckpoint(
                owner_user_id=job.owner_user_id,
                project_id=job.project_id,
                job_id=job.id,
                job_source_id=relation.id,
                part_index=0,
                total_parts=2,
                timeline_offset_seconds=0,
                duration_seconds=10,
                provider="elevenlabs",
                model="scribe_v2",
                ciphertext=b"ciphertext",
                nonce=b"nonce",
                key_id="key-v1",
                payload_hmac="a" * 64,
                created_at=now - timedelta(hours=2),
                expires_at=(
                    now - timedelta(seconds=1)
                    if index < 3
                    else now + timedelta(hours=1)
                ),
            )
        )
    sqlite_db.commit()

    assert cleanup_expired_provider_part_checkpoints(sqlite_db, now=now + timedelta(days=90), limit=2) == 0
    assert sqlite_db.query(m.TranscriptionProviderPartCheckpoint).count() == 4
    job.status = m.JobStatus.cancelled
    sqlite_db.commit()
    assert cleanup_expired_provider_part_checkpoints(
        sqlite_db,
        now=now,
        limit=2,
    ) == 2
    sqlite_db.commit()
    assert cleanup_expired_provider_part_checkpoints(
        sqlite_db,
        now=now,
        limit=2,
    ) == 2
    sqlite_db.commit()
    assert cleanup_expired_provider_part_checkpoints(
        sqlite_db,
        now=now,
        limit=2,
    ) == 0
    assert sqlite_db.query(m.TranscriptionProviderPartCheckpoint).count() == 0


@pytest.mark.parametrize("stage,disp,reason", [
    ("provider_request_started", "provider_outcome_uncertain", "provider_outcome_uncertain"),
    ("provider_response_returned", "provider_result_lost", "provider_result_lost"),
])
def test_any_unsafe_current_source_blocks_later_prepared_source(sqlite_db, stage, disp, reason):
    from studio_api.job_retry_recovery import compute_explicit_retry_readiness
    m, now, _user, _project, job, rels = _job_with_sources(sqlite_db, source_count=2, status="failed")
    job.lease_owner_id = None; job.lease_expires_at = None; sqlite_db.commit()
    _attempt(sqlite_db, m, job, rels[0], stage=getattr(m.SourceAttemptStage, stage), disposition=getattr(m.SourceAttemptRetryDisposition, disp), started=True, returned=stage == "provider_response_returned")
    _attempt(sqlite_db, m, job, rels[1])
    ready = compute_explicit_retry_readiness(sqlite_db, job, now=now)
    assert ready.available is False and ready.reason.value == reason


def test_missing_current_row_ignores_older_retry_safe_attempt(sqlite_db):
    from studio_api.job_retry_recovery import compute_explicit_retry_readiness
    m, now, _user, _project, job, rels = _job_with_sources(sqlite_db, source_count=1, status="failed", attempt_count=2)
    job.lease_owner_id = None; job.lease_expires_at = None; sqlite_db.commit()
    _attempt(sqlite_db, m, job, rels[0], number=1, stage=m.SourceAttemptStage.failed, disposition=m.SourceAttemptRetryDisposition.retry_safe)
    ready = compute_explicit_retry_readiness(sqlite_db, job, now=now)
    assert ready.available is False and ready.reason.value == "legacy_or_unknown_execution_state"


def test_reconciliation_and_attempt_limit_override_prepared_sources(sqlite_db):
    from studio_api.job_retry_recovery import compute_explicit_retry_readiness
    m, now, _user, _project, job, rels = _job_with_sources(sqlite_db, source_count=2, status="failed")
    job.lease_owner_id = None; job.lease_expires_at = None; sqlite_db.commit()
    for rel in rels: _attempt(sqlite_db, m, job, rel)
    sqlite_db.add(m.TranscriptionOutputReconciliation(owner_user_id=job.owner_user_id, project_id=job.project_id, job_id=job.id, job_source_id=rels[0].id, reconciliation_token="tok", lease_generation=7, attempt_number=1, status=m.OutputReconciliationStatus.reconciliation_required, expected_output_drive_folder_id="folder", expected_document_character_count=1, prepared_at=now, created_at=now, updated_at=now))
    sqlite_db.commit()
    ready = compute_explicit_retry_readiness(sqlite_db, job, now=now)
    assert ready.available is False and ready.reason.value == "output_reconciliation_required"
    sqlite_db.query(m.TranscriptionOutputReconciliation).delete(); job.attempt_count = 3; sqlite_db.commit()
    ready = compute_explicit_retry_readiness(sqlite_db, job, now=now)
    assert ready.available is False and ready.reason.value == "attempt_limit_reached"


def test_all_outputs_recovery_completes_without_new_attempt_rows(sqlite_db):
    from studio_api.job_processing_lifecycle import recover_expired_processing_job
    m, now, _user, _project, job, rels = _job_with_sources(sqlite_db, source_count=2, expired=True)
    for idx, rel in enumerate(rels):
        sqlite_db.add(m.TranscriptionJobOutput(job_id=job.id, job_source_id=rel.id, document_id=f"doc-{idx}", web_view_url=f"https://docs.example/doc-{idx}", output_drive_folder_id="folder", output_kind="google_docs_transcript", transcript_standard="transcript_doc_v1.2", document_character_count=1, document_created_at=now, persisted_at=now, lease_generation=7))
    sqlite_db.commit()
    result = recover_expired_processing_job(sqlite_db, job_id=job.id, now=now)
    assert result.status == m.JobStatus.completed
    assert sqlite_db.query(m.TranscriptionJobSourceAttempt).count() == 0
