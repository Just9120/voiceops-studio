from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


@dataclass(frozen=True)
class Settings:
    value: str = "settings"


@pytest.fixture(autouse=True)
def isolated_studio_database_url(monkeypatch):
    monkeypatch.setenv("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    from studio_api.config import get_settings
    get_settings.cache_clear()


@pytest.fixture()
def engine():
    from studio_api.db import Base
    import studio_api.models  # noqa: F401
    e = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(e)
    try:
        yield e
    finally:
        Base.metadata.drop_all(e); e.dispose()


@pytest.fixture()
def db(engine):
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


class Clock:
    def __init__(self): self.t = datetime(2026, 1, 2, 3, 4, 5)
    def __call__(self): self.t += timedelta(seconds=1); return self.t


def make_ready_job(db):
    from studio_api import models as m
    now = datetime(2026, 1, 2, 3, 4, 5)
    user = m.User(email=f"{id(db)}@example.com", role=m.UserRole.user, status=m.UserStatus.active)
    db.add(user); db.flush()
    project = m.Project(owner_user_id=user.id, title="p", output_drive_folder_id="SECRET_FOLDER")
    db.add(project); db.flush()
    job = m.TranscriptionJob(project_id=project.id, owner_user_id=user.id, status=m.JobStatus.queued, provider="elevenlabs", title="Job", language="en", provider_credential_id="cred")
    db.add(job); db.flush()
    src = m.Source(project_id=project.id, source_type=m.SourceType.local_upload, original_filename="SECRET_PATH.mp3", mime_type="audio/mpeg", size_bytes=1, s3_bucket="bucket", s3_object_key="SECRET_STORAGE_KEY", upload_status=m.SourceUploadStatus.uploaded, uploaded_at=now, expires_at=now + timedelta(hours=1))
    db.add(src); db.flush()
    db.add(m.TranscriptionJobSource(job_id=job.id, source_id=src.id, position=0, status=m.JobSourceStatus.queued))
    db.commit()
    return job.id


def safe_result(job_id="job"):
    from studio_api.job_processing_orchestrator import JobProcessingOrchestrationResult
    from studio_api.models import JobStatus
    return JobProcessingOrchestrationResult(job_id, JobStatus.completed, 1, 1, 1, 1, True)


def test_success_claim_commits_before_orchestration_and_passes_exact_handle(db):
    from studio_api.job_claim_lease import JobLeaseHandle
    from studio_api.job_processing_runner import claim_and_orchestrate_processing_job
    clock = Clock(); settings = Settings(); events = []; result = safe_result("handle-job")
    handle = JobLeaseHandle("handle-job", "committed-owner", 42, clock(), clock() + timedelta(minutes=5))
    def acquirer(db_, **kw):
        events.append(("acquire", kw)); return handle
    def orchestrator(db_, **kw):
        events.append(("orchestrate", kw)); return result
    original_commit = db.commit
    def commit():
        events.append("commit"); original_commit()
    db.commit = commit
    assert claim_and_orchestrate_processing_job(db, job_id="input-job", lease_owner_id="input-owner", lease_ttl=timedelta(minutes=5), settings=settings, clock=clock, lease_acquirer=acquirer, orchestrator=orchestrator) is result
    assert [e if isinstance(e, str) else e[0] for e in events] == ["acquire", "commit", "orchestrate"]
    assert events[0][1]["job_id"] == "input-job" and events[0][1]["lease_owner_id"] == "input-owner"
    assert events[2][1] == {"job_id": "handle-job", "lease_owner_id": "committed-owner", "lease_generation": 42, "settings": settings, "clock": clock, "lease_ttl": timedelta(minutes=5)}


def test_real_lease_integration_commits_before_fake_orchestrator(engine, db):
    from studio_api import models as m
    from studio_api.job_processing_runner import claim_and_orchestrate_processing_job
    job_id = make_ready_job(db); SessionLocal = sessionmaker(bind=engine, expire_on_commit=False); seen = {}
    def orchestrator(db_, **kw):
        fresh = SessionLocal()
        try:
            job = fresh.get(m.TranscriptionJob, job_id)
            seen.update(owner=job.lease_owner_id, generation=job.lease_generation, status=job.status)
        finally:
            fresh.close()
        return safe_result(job_id)
    result = claim_and_orchestrate_processing_job(db, job_id=job_id, lease_owner_id="worker", lease_ttl=timedelta(minutes=5), settings=Settings(), clock=Clock(), orchestrator=orchestrator)
    assert result.job_id == job_id
    assert seen == {"owner": "worker", "generation": 1, "status": m.JobStatus.queued}


def test_job_claimed_diagnostic_commits_with_lease(monkeypatch, engine, db):
    from studio_api import models as m
    import studio_api.job_processing_runner as runner

    job_id = make_ready_job(db)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(runner, "resolve_job_correlation_id", lambda **kw: "corr_abcdefghijklmnop")

    def orchestrator(*args, **kwargs):
        with SessionLocal() as fresh:
            job = fresh.get(m.TranscriptionJob, job_id)
            event = fresh.query(m.DiagnosticEvent).filter_by(job_id=job_id, event_code="JOB_CLAIMED").one()
            assert (job.lease_owner_id, job.lease_generation) == ("worker", 1)
            assert event.correlation_id == "corr_abcdefghijklmnop"
            assert event.metadata_json == "{}"
        return safe_result(job_id)

    result = runner.claim_and_orchestrate_processing_job(
        db, job_id=job_id, lease_owner_id="worker", lease_ttl=timedelta(minutes=5),
        settings=Settings(), clock=Clock(), orchestrator=orchestrator,
    )
    assert result.job_id == job_id


def test_failed_claim_event_rolls_back_lease_and_allows_retry(monkeypatch, db):
    from studio_api import models as m
    import studio_api.job_processing_runner as runner

    job_id = make_ready_job(db)
    def fail(**kwargs):
        assert kwargs["transaction"] is db
        raise RuntimeError("synthetic diagnostic failure")

    with monkeypatch.context() as patch:
        patch.setattr(runner, "write_diagnostic_event", fail)
        with pytest.raises(runner.JobProcessingRunnerError, match="claim_commit_failed"):
            runner.claim_and_orchestrate_processing_job(
                db, job_id=job_id, lease_owner_id="worker", lease_ttl=timedelta(minutes=5),
                settings=Settings(), clock=Clock(), orchestrator=lambda *a, **k: pytest.fail("unrecorded lease"),
            )
    assert db.get(m.TranscriptionJob, job_id).lease_owner_id is None
    runner.claim_and_orchestrate_processing_job(
        db, job_id=job_id, lease_owner_id="worker", lease_ttl=timedelta(minutes=5),
        settings=Settings(), clock=Clock(), orchestrator=lambda *a, **k: safe_result(job_id),
    )
    assert db.query(m.DiagnosticEvent).filter_by(job_id=job_id, event_code="JOB_CLAIMED").count() == 1


def test_known_lease_error_rolls_back_preserves_type_and_skips_orchestrator(db):
    from studio_api.job_claim_lease import JobLeaseError, JobLeaseFailureReason
    from studio_api.job_processing_runner import claim_and_orchestrate_processing_job
    calls = {"rollback": 0, "orchestrator": 0}; original_rollback = db.rollback
    db.rollback = lambda: (calls.__setitem__("rollback", calls["rollback"] + 1), original_rollback())[1]
    err = JobLeaseError(JobLeaseFailureReason.job_not_ready)
    with pytest.raises(JobLeaseError) as got:
        claim_and_orchestrate_processing_job(db, job_id="job", lease_owner_id="owner", lease_ttl=timedelta(minutes=5), settings=Settings(), lease_acquirer=lambda *a, **k: (_ for _ in ()).throw(err), orchestrator=lambda *a, **k: calls.__setitem__("orchestrator", 1))
    assert got.value is err and got.value.reason == JobLeaseFailureReason.job_not_ready
    assert calls == {"rollback": 1, "orchestrator": 0}


@pytest.mark.parametrize("phase,reason", [("acquire", "claim_failed"), ("commit", "claim_commit_failed"), ("orchestrate", "orchestration_failed")])
def test_unexpected_failures_are_normalized_redacted_rollback_and_no_retry(db, phase, reason):
    from studio_api.job_claim_lease import JobLeaseHandle
    from studio_api.job_processing_runner import JobProcessingRunnerError, JobProcessingRunnerReason, claim_and_orchestrate_processing_job
    clock = Clock(); handle = JobLeaseHandle("job", "SECRET_OWNER", 99, clock(), clock() + timedelta(minutes=5)); calls = {"rollback": 0, "orchestrator": 0}
    db.rollback = lambda: calls.__setitem__("rollback", calls["rollback"] + 1)
    if phase == "commit": db.commit = lambda: (_ for _ in ()).throw(RuntimeError("SECRET_TOKEN raw payload"))
    def acquirer(*a, **k):
        if phase == "acquire": raise RuntimeError("SECRET_TOKEN raw payload")
        return handle
    def orchestrator(*a, **k):
        calls["orchestrator"] += 1
        if phase == "orchestrate": raise RuntimeError("SECRET_TRANSCRIPT SECRET_DOC SECRET_STORAGE_KEY")
        return safe_result("job")
    with pytest.raises(JobProcessingRunnerError) as got:
        claim_and_orchestrate_processing_job(db, job_id="job", lease_owner_id="owner", lease_ttl=timedelta(minutes=5), settings=Settings(), clock=clock, lease_acquirer=acquirer, orchestrator=orchestrator)
    assert got.value.reason == JobProcessingRunnerReason(reason)
    assert str(got.value) == reason and "SECRET" not in repr(got.value)
    assert calls["rollback"] == 1
    assert calls["orchestrator"] == (1 if phase == "orchestrate" else 0)


def test_known_orchestration_error_rolls_back_preserves_type_called_once(db):
    from studio_api.job_claim_lease import JobLeaseHandle
    from studio_api.job_processing_orchestrator import JobProcessingOrchestrationError, JobProcessingOrchestrationReason
    from studio_api.job_processing_runner import claim_and_orchestrate_processing_job
    clock = Clock(); handle = JobLeaseHandle("job", "owner", 1, clock(), clock() + timedelta(minutes=5)); err = JobProcessingOrchestrationError(JobProcessingOrchestrationReason.lease_not_active); calls={"rollback":0,"orchestrator":0}
    db.rollback = lambda: calls.__setitem__("rollback", calls["rollback"] + 1)
    def orchestrator(*a, **k): calls.__setitem__("orchestrator", calls["orchestrator"] + 1); raise err
    with pytest.raises(JobProcessingOrchestrationError) as got:
        claim_and_orchestrate_processing_job(db, job_id="job", lease_owner_id="owner", lease_ttl=timedelta(minutes=5), settings=Settings(), clock=clock, lease_acquirer=lambda *a, **k: handle, orchestrator=orchestrator)
    assert got.value is err and got.value.reason == JobProcessingOrchestrationReason.lease_not_active
    assert calls == {"rollback": 1, "orchestrator": 1}


def test_result_and_error_repr_safety():
    from studio_api.job_processing_runner import JobProcessingRunnerError, JobProcessingRunnerReason
    text = repr(safe_result("safe-job")) + repr(JobProcessingRunnerError(JobProcessingRunnerReason.claim_failed))
    forbidden = ["SECRET_OWNER", "generation=", "SECRET_TRANSCRIPT", "SECRET_DOC", "SECRET_FOLDER", "credential", "token", "SECRET_PATH", "SECRET_STORAGE_KEY", "raw payload"]
    assert not any(item in text for item in forbidden)
