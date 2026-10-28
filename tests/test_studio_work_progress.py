import json
import sys
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
if "STUDIO_DATABASE_HOST" not in os.environ:
    os.environ.setdefault("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
from studio_api.db import Base
from studio_api.models import User, Project, AudioPreparationJob, AudioPreparationStatus
from studio_api.preparation_control import PreparationInterrupted
from studio_api.audio_preparation_service import AudioPreparationServiceError
from studio_api.work_progress import measured_work, progress_payload, report_work

NOW = datetime(2026, 10, 28, 10, tzinfo=timezone.utc)


@pytest.fixture
def state():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(User(id="owner", email="owner@example.test"))
        db.add(Project(id="project", owner_user_id="owner", title="Synthetic"))
        job = AudioPreparationJob(id="job", owner_user_id="owner", project_id="project", title="Synthetic",
            options_json="{}", output_destination="download", status=AudioPreparationStatus.analyzing,
            lease_owner_id="worker", lease_generation=3, lease_expires_at=NOW + timedelta(minutes=5))
        db.add(job)
        db.commit()
        yield db, job


def test_progress_survives_reload_and_is_not_advanced_by_identical_heartbeats(state):
    db, job = state
    with measured_work(db, job=job, owner="worker", generation=3, clock=lambda: NOW):
        report_work("source_download", 10, 100, "bytes")
        db.refresh(job)
        first = progress_payload(job.work_progress_json)
        report_work("source_download", 10, 100, "bytes")
        db.refresh(job)
        assert progress_payload(job.work_progress_json) == first
        report_work("provider_wait")
    db.expire_all()
    last = progress_payload(db.get(AudioPreparationJob, "job").work_progress_json)
    assert last["stage"] == "provider_wait"
    assert last["completed"] is None and last["total"] is None
    assert last["sequence"] == 2 and last["generation"] == 3
    assert last["started_at"].endswith("+00:00")
    assert progress_payload(job.work_progress_json, generation=4) is None
    with measured_work(db, job=job, owner="worker", generation=3, clock=lambda: NOW):
        report_work("document_output")
    db.refresh(job)
    assert progress_payload(job.work_progress_json)["sequence"] == 3


@pytest.mark.parametrize("change", ["generation", "owner", "expired", "cancelled", "terminal"])
def test_stale_worker_cannot_write_progress_after_lifecycle_change(state, change):
    db, job = state
    if change == "generation": job.lease_generation = 4
    if change == "owner": job.lease_owner_id = "other"
    if change == "expired": job.lease_expires_at = NOW - timedelta(seconds=1)
    if change == "cancelled": job.cancel_requested_at = NOW
    if change == "terminal": job.status = AudioPreparationStatus.failed
    db.commit()
    with measured_work(db, job=job, owner="worker", generation=3, clock=lambda: NOW):
        with pytest.raises(AudioPreparationServiceError): report_work("media_processing", 3, 10, "seconds")
    db.refresh(job)
    assert job.work_progress_json is None


@pytest.mark.parametrize("number", [float("nan"), float("inf"), -1, True])
def test_invalid_measurement_is_never_persisted(state, number):
    db, job = state
    with measured_work(db, job=job, owner="worker", generation=3, clock=lambda: NOW):
        with pytest.raises(ValueError): report_work("media_processing", number, 10, "seconds")
    assert progress_payload(json.dumps({"stage": "media_processing", "completed": number})) is None
