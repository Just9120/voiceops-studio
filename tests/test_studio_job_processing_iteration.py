from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

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


@pytest.fixture()
def engine():
    from studio_api.db import Base
    import studio_api.models  # noqa: F401

    e = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(e)
    try:
        yield e
    finally:
        Base.metadata.drop_all(e)
        e.dispose()


@pytest.fixture()
def db(engine):
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


class Clock:
    def __init__(self):
        self.t = datetime(2026, 1, 2, 3, 4, 5)

    def __call__(self):
        self.t += timedelta(seconds=1)
        return self.t


def safe_result(job_id="job"):
    from studio_api.job_processing_orchestrator import JobProcessingOrchestrationResult
    from studio_api.models import JobStatus

    return JobProcessingOrchestrationResult(job_id, JobStatus.completed, 1, 1, 1, 1, True)


def make_job(db, *, job_id: str | None = None, created_at: datetime | None = None, ready=True, owner=None, expires_at=None, generation=0):
    from studio_api import models as m

    now = datetime(2026, 1, 2, 3, 4, 5)
    suffix = job_id or str(id(object()))
    user = m.User(email=f"{suffix}@example.com", role=m.UserRole.user, status=m.UserStatus.active)
    db.add(user)
    db.flush()
    project = m.Project(owner_user_id=user.id, title="p", output_drive_folder_id=("folder" if ready else None))
    db.add(project)
    db.flush()
    job = m.TranscriptionJob(
        id=str(uuid5(NAMESPACE_URL, "voiceops-test-job:" + job_id)) if job_id else None,
        project_id=project.id,
        owner_user_id=user.id,
        status=m.JobStatus.queued,
        provider="elevenlabs" if ready else None,
        provider_credential_id="cred" if ready else None,
        created_at=created_at or now,
        lease_owner_id=owner,
        lease_expires_at=expires_at,
        lease_generation=generation,
    )
    db.add(job)
    db.flush()
    if ready:
        src = m.Source(
            project_id=project.id,
            source_type=m.SourceType.local_upload,
            original_filename="SECRET_PATH.mp3",
            mime_type="audio/mpeg",
            size_bytes=1,
            s3_bucket="bucket",
            s3_object_key="SECRET_STORAGE_KEY",
            upload_status=m.SourceUploadStatus.uploaded,
            uploaded_at=now,
            expires_at=now + timedelta(hours=1),
        )
        db.add(src)
        db.flush()
        db.add(m.TranscriptionJobSource(job_id=job.id, source_id=src.id, position=0, status=m.JobSourceStatus.queued))
    db.commit()
    return job.id


def test_no_candidates_returns_none_rolls_back_and_skips_orchestration(db):
    from studio_api.job_processing_runner import claim_next_and_orchestrate_processing_job

    calls = {"rollback": 0, "orchestrator": 0}
    original = db.rollback
    db.rollback = lambda: (calls.__setitem__("rollback", calls["rollback"] + 1), original())[1]
    result = claim_next_and_orchestrate_processing_job(
        db, lease_owner_id="worker", lease_ttl=timedelta(minutes=5), settings=Settings(), clock=Clock(), orchestrator=lambda *a, **k: calls.__setitem__("orchestrator", 1)
    )
    assert result is None
    assert calls == {"rollback": 1, "orchestrator": 0}


def test_one_ready_job_claims_commits_before_orchestration_and_returns_result(engine, db):
    from studio_api import models as m
    from studio_api.job_processing_runner import claim_next_and_orchestrate_processing_job

    job_id = make_job(db, job_id="ready")
    events = []
    result = safe_result(job_id)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    original_commit = db.commit
    db.commit = lambda: (events.append("commit"), original_commit())[1]

    def orchestrator(db_, **kw):
        fresh = SessionLocal()
        try:
            job = fresh.get(m.TranscriptionJob, job_id)
            events.append(("orchestrate", kw, job.lease_owner_id, job.lease_generation))
        finally:
            fresh.close()
        return result

    assert claim_next_and_orchestrate_processing_job(db, lease_owner_id="worker", lease_ttl=timedelta(minutes=5), settings=Settings(), clock=Clock(), orchestrator=orchestrator) is result
    assert events[0] == "commit"
    assert events[1][1]["job_id"] == job_id
    assert events[1][1]["lease_owner_id"] == "worker"
    assert events[1][1]["lease_generation"] == 1
    assert events[1][2:] == ("worker", 1)


def test_deterministic_selection_created_at_then_job_id(db):
    from studio_api.job_claim_lease import acquire_next_ready_job_lease

    t = datetime(2026, 1, 2)
    first = make_job(db, job_id="b", created_at=t)
    second = make_job(db, job_id="a", created_at=t)
    handle = acquire_next_ready_job_lease(db, lease_owner_id="worker", now=t + timedelta(hours=1), lease_ttl=timedelta(minutes=5))
    assert handle.job_id == min(first, second)


def test_oldest_unready_and_active_lease_are_skipped_without_mutation(db):
    from studio_api import models as m
    from studio_api.job_claim_lease import acquire_next_ready_job_lease

    t = datetime(2026, 1, 2)
    unready = make_job(db, job_id="unready", created_at=t, ready=False)
    active = make_job(db, job_id="active", created_at=t + timedelta(seconds=1), owner="other", expires_at=t + timedelta(hours=3), generation=7)
    ready = make_job(db, job_id="ready", created_at=t + timedelta(seconds=2))
    handle = acquire_next_ready_job_lease(db, lease_owner_id="worker", now=t + timedelta(hours=1), lease_ttl=timedelta(minutes=5))
    assert handle.job_id == ready
    assert db.get(m.TranscriptionJob, unready).lease_generation == 0
    assert db.get(m.TranscriptionJob, active).lease_owner_id == "other"
    assert db.get(m.TranscriptionJob, active).lease_generation == 7


def test_expired_queued_lease_may_be_reacquired_and_committed(db):
    from studio_api import models as m
    from studio_api.job_processing_runner import claim_next_and_orchestrate_processing_job

    now = datetime(2026, 1, 2, 3, 4, 5)
    job_id = make_job(db, job_id="expired", owner="old", expires_at=now - timedelta(seconds=1), generation=4)
    assert claim_next_and_orchestrate_processing_job(db, lease_owner_id="new", lease_ttl=timedelta(minutes=5), settings=Settings(), clock=lambda: now, orchestrator=lambda *a, **k: safe_result(job_id)).job_id == job_id
    job = db.get(m.TranscriptionJob, job_id)
    assert (job.lease_owner_id, job.lease_generation, job.lease_expires_at) == ("new", 5, now + timedelta(minutes=5))


def test_all_candidates_unready_returns_none_without_mutation(db):
    from studio_api import models as m
    from studio_api.job_processing_runner import claim_next_and_orchestrate_processing_job

    j1 = make_job(db, job_id="u1", ready=False)
    j2 = make_job(db, job_id="u2", ready=False)
    calls = {"orchestrator": 0}
    assert claim_next_and_orchestrate_processing_job(db, lease_owner_id="worker", lease_ttl=timedelta(minutes=5), settings=Settings(), clock=Clock(), orchestrator=lambda *a, **k: calls.__setitem__("orchestrator", 1)) is None
    assert calls["orchestrator"] == 0
    assert db.get(m.TranscriptionJob, j1).lease_generation == 0
    assert db.get(m.TranscriptionJob, j2).lease_owner_id is None


@pytest.mark.parametrize("owner,ttl,reason", [(" ", timedelta(minutes=5), "invalid_owner"), ("worker", timedelta(0), "invalid_ttl")])
def test_invalid_owner_and_ttl_preserve_job_lease_error(db, owner, ttl, reason):
    from studio_api.job_claim_lease import JobLeaseError, JobLeaseFailureReason
    from studio_api.job_processing_runner import claim_next_and_orchestrate_processing_job

    with pytest.raises(JobLeaseError) as got:
        claim_next_and_orchestrate_processing_job(db, lease_owner_id=owner, lease_ttl=ttl, settings=Settings(), orchestrator=lambda *a, **k: pytest.fail("orchestrated"))
    assert got.value.reason == JobLeaseFailureReason(reason)


@pytest.mark.parametrize("phase,reason", [("discover", "claim_failed"), ("commit", "claim_commit_failed"), ("orchestrate", "orchestration_failed")])
def test_unexpected_failures_are_normalized_redacted_and_not_retried(db, phase, reason):
    from studio_api.job_claim_lease import JobLeaseHandle
    from studio_api.job_processing_runner import JobProcessingRunnerError, JobProcessingRunnerReason, claim_next_and_orchestrate_processing_job

    clock = Clock()
    handle = JobLeaseHandle("job", "SECRET_OWNER", 99, clock(), clock() + timedelta(minutes=5))
    calls = {"rollback": 0, "orchestrator": 0}
    db.rollback = lambda: calls.__setitem__("rollback", calls["rollback"] + 1)
    if phase == "commit":
        db.commit = lambda: (_ for _ in ()).throw(RuntimeError("SECRET SQL raw payload"))

    def acquirer(*a, **k):
        if phase == "discover":
            raise RuntimeError("SECRET SQL raw payload")
        return handle

    def orchestrator(*a, **k):
        calls["orchestrator"] += 1
        if phase == "orchestrate":
            raise RuntimeError("SECRET_TRANSCRIPT SECRET_TOKEN SECRET_STORAGE_KEY")
        return safe_result("job")

    with pytest.raises(JobProcessingRunnerError) as got:
        claim_next_and_orchestrate_processing_job(db, lease_owner_id="worker", lease_ttl=timedelta(minutes=5), settings=Settings(), clock=clock, next_lease_acquirer=acquirer, orchestrator=orchestrator)
    assert got.value.reason == JobProcessingRunnerReason(reason)
    assert str(got.value) == reason and "SECRET" not in repr(got.value) and "SQL" not in repr(got.value)
    assert calls["rollback"] == 1
    assert calls["orchestrator"] == (1 if phase == "orchestrate" else 0)


def test_known_orchestration_failure_preserves_exact_error(db):
    from studio_api.job_claim_lease import JobLeaseHandle
    from studio_api.job_processing_orchestrator import JobProcessingOrchestrationError, JobProcessingOrchestrationReason
    from studio_api.job_processing_runner import claim_next_and_orchestrate_processing_job

    clock = Clock()
    handle = JobLeaseHandle("job", "owner", 1, clock(), clock() + timedelta(minutes=5))
    err = JobProcessingOrchestrationError(JobProcessingOrchestrationReason.lease_not_active)
    calls = {"orchestrator": 0}

    def orchestrator(*a, **k):
        calls["orchestrator"] += 1
        raise err

    with pytest.raises(JobProcessingOrchestrationError) as got:
        claim_next_and_orchestrate_processing_job(db, lease_owner_id="worker", lease_ttl=timedelta(minutes=5), settings=Settings(), clock=clock, next_lease_acquirer=lambda *a, **k: handle, orchestrator=orchestrator)
    assert got.value is err
    assert calls["orchestrator"] == 1


def test_explicit_runner_regression_still_claims_explicit_job(db):
    from studio_api.job_processing_runner import claim_and_orchestrate_processing_job

    target = make_job(db, job_id="target", created_at=datetime(2026, 1, 3))
    make_job(db, job_id="older", created_at=datetime(2026, 1, 2))
    result = claim_and_orchestrate_processing_job(db, job_id=target, lease_owner_id="worker", lease_ttl=timedelta(minutes=5), settings=Settings(), clock=Clock(), orchestrator=lambda *a, **k: safe_result(k["job_id"]))
    assert result.job_id == target


def test_result_and_error_repr_safety():
    from studio_api.job_processing_runner import JobProcessingRunnerError, JobProcessingRunnerReason

    text = repr(safe_result("safe-job")) + repr(JobProcessingRunnerError(JobProcessingRunnerReason.claim_failed))
    forbidden = ["SECRET_OWNER", "generation=", "SECRET_TRANSCRIPT", "SECRET_DOC", "SECRET_FOLDER", "credential", "token", "SECRET_PATH", "SECRET_STORAGE_KEY", "SQL", "raw payload"]
    assert not any(item in text for item in forbidden)
