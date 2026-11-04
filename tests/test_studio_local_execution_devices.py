"""A paired PC receives a narrow capability, never an owner/provider session."""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
os.environ.setdefault("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")

from studio_api.local_execution_devices import authenticate_device, device_payload, pair_device
from studio_api.models import AuditEvent, Base, LocalExecutionDevice, Session, User, UserStatus
from studio_api.nemotron_local_result import NEMOTRON_MODEL
from studio_api.security import token_hash


@pytest.fixture
def local_app(monkeypatch):
    from studio_api import deps, main
    from studio_api.config import Settings, get_settings
    from studio_api.db import get_db
    settings = Settings(database_url="sqlite+pysqlite:///:memory:", app_origin="https://studio.test", cookie_secure=False)
    monkeypatch.setattr(main, "settings", settings)
    naive_now = lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    monkeypatch.setattr(main, "utcnow", naive_now)
    monkeypatch.setattr(deps, "utcnow", naive_now)
    monkeypatch.setattr(main.limiter, "check", lambda *_args: None)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)
    def get_test_db():
        with maker() as db:
            yield db
    main.app.dependency_overrides[get_db] = get_test_db
    main.app.dependency_overrides[get_settings] = lambda: settings
    with maker() as db:
        owner, other = User(email="local-owner@example.test"), User(email="local-other@example.test")
        db.add_all([owner, other]); db.flush()
        db.add(Session(user_id=owner.id, token_hash=token_hash("owner-session"), csrf_hash=token_hash("test-csrf"),
            expires_at=naive_now() + timedelta(days=1), reauthenticated_at=naive_now()))
        db.add(Session(user_id=other.id, token_hash=token_hash("other-session"), csrf_hash=token_hash("test-csrf"),
            expires_at=naive_now() + timedelta(days=1), reauthenticated_at=naive_now()))
        db.commit()
        ids = owner.id, other.id
    client = TestClient(main.app, base_url=settings.app_origin)
    client.cookies.set(settings.cookie_name, "owner-session")
    try:
        yield client, maker, settings, ids
    finally:
        client.close()
        main.app.dependency_overrides.pop(get_db, None)
        main.app.dependency_overrides.pop(get_settings, None)
        engine.dispose()


OWNER_HEADERS = {"origin": "https://studio.test", "x-csrf-token": "test-csrf"}
BASE = "/api/local-execution"
READY = {"runtime_status": "ready", "runtime_version": "0.2.0+nightly.66d50d9", "model": NEMOTRON_MODEL}


def pair(client, **changes):
    data = {"label": "Synthetic PC", "creation_key": str(uuid4()), **changes}
    reply = client.post(BASE + "/devices", headers=OWNER_HEADERS, json=data)
    assert reply.status_code == 200, reply.text
    return reply, data


def pc_headers(token):
    return {"authorization": "Bearer " + token, "x-voiceops-local-protocol": "1"}


def test_pair_is_once_only_idempotent_and_does_not_persist_or_list_secret(local_app):
    client, maker, settings, (owner_id, _) = local_app
    reply, data = pair(client)
    token, device = reply.json()["pairing_token"], reply.json()["device"]
    assert not device["online"] and not device["ready"]
    assert reply.headers["cache-control"] == "no-store"
    replay = client.post(BASE + "/devices", headers=OWNER_HEADERS, json=data)
    assert replay.status_code == 200
    assert replay.json()["device"]["id"] == device["id"]
    assert replay.json()["pairing_token"] is None and not replay.json()["token_available_once"]
    listed = client.get(BASE + "/devices")
    assert len(listed.json()["devices"]) == 1 and token not in listed.text
    with maker() as db:
        row = db.scalar(select(LocalExecutionDevice))
        assert row.owner_user_id == owner_id and row.token_hash != token and len(row.token_hash) == 64
        assert authenticate_device(db, token).id == row.id
        assert token not in str(db.scalars(select(AuditEvent.metadata_json)).all())
    # A machine token cannot act as a browser session.
    client.cookies.clear()
    assert client.get(BASE + "/devices", headers=pc_headers(token)).status_code == 401


def test_pair_requires_csrf_and_step_up(local_app):
    client, maker, _, _ = local_app
    data = {"label": "PC", "creation_key": str(uuid4())}
    assert client.post(BASE + "/devices", json=data).status_code == 403
    with maker() as db:
        row = db.scalar(select(Session).where(Session.token_hash == token_hash("owner-session")))
        row.reauthenticated_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
    blocked = client.post(BASE + "/devices", json=data, headers=OWNER_HEADERS)
    assert blocked.status_code == 409 and blocked.json()["detail"]["reason"] == "recent_reauthentication_required"
    with maker() as db:
        assert db.scalar(select(LocalExecutionDevice)) is None


def test_ready_requires_bound_model_identity_and_heartbeat_freshness(local_app):
    client, maker, _, _ = local_app
    reply, _ = pair(client)
    token = reply.json()["pairing_token"]
    heartbeat = client.post(BASE + "/companion/heartbeat", headers=pc_headers(token), json=READY)
    assert heartbeat.status_code == 200 and heartbeat.json()["device"]["ready"]
    assert heartbeat.headers["cache-control"] == "no-store"
    with maker() as db:
        row = db.scalar(select(LocalExecutionDevice))
        now = datetime.now(timezone.utc)
        assert not device_payload(row, now=now + timedelta(seconds=91))["online"]
        row.last_seen_at = now + timedelta(minutes=1)
        assert not device_payload(row, now=now)["ready"]
    missing = {"runtime_status": "ready"}
    assert client.post(BASE + "/companion/heartbeat", headers=pc_headers(token), json=missing).status_code == 422
    bad = {**READY, "model": "wrong-model", "runtime_version": "private-path-or-text"}
    rejected = client.post(BASE + "/companion/heartbeat", headers=pc_headers(token), json=bad)
    assert rejected.status_code == 422 and "wrong-model" not in rejected.text and "private-path" not in rejected.text
    unavailable = client.post(BASE + "/companion/heartbeat", headers=pc_headers(token), json={"runtime_status": "model_missing"})
    assert unavailable.status_code == 200 and not unavailable.json()["device"]["ready"]


@pytest.mark.parametrize("case", ["browser_origin", "cookie_only", "wrong_token", "no_protocol", "disabled_owner"])
def test_machine_auth_has_no_cookie_or_provider_fallback(local_app, case):
    client, maker, _, (owner_id, _) = local_app
    reply, _ = pair(client)
    headers = pc_headers(reply.json()["pairing_token"])
    if case == "browser_origin":
        headers["origin"] = "https://studio.test"
    elif case == "cookie_only":
        headers.pop("authorization")
    elif case == "wrong_token":
        headers["authorization"] = "Bearer sk-provider-not-a-device"
    elif case == "no_protocol":
        headers.pop("x-voiceops-local-protocol")
    else:
        with maker() as db:
            db.get(User, owner_id).status = UserStatus.disabled
            db.commit()
    assert client.post(BASE + "/companion/heartbeat", headers=headers, json=READY).status_code in {401, 403}


def test_owner_isolation_rotation_and_revocation_fence_old_tokens(local_app):
    client, maker, settings, _ = local_app
    reply, _ = pair(client)
    token = reply.json()["pairing_token"]
    device_id = reply.json()["device"]["id"]
    client.cookies.set(settings.cookie_name, "other-session")
    assert client.get(BASE + "/devices").json() == {"devices": []}
    for action in ("rotate", "revoke"):
        assert client.post(f"{BASE}/devices/{device_id}/{action}", headers=OWNER_HEADERS,
            json={"expected_revision": 1}).status_code == 404
    client.cookies.set(settings.cookie_name, "owner-session")
    rotated = client.post(f"{BASE}/devices/{device_id}/rotate", headers=OWNER_HEADERS, json={"expected_revision": 1})
    assert rotated.status_code == 200
    new_token = rotated.json()["pairing_token"]
    assert new_token != token
    assert client.post(BASE + "/companion/heartbeat", headers=pc_headers(token), json=READY).status_code == 401
    assert client.post(BASE + "/companion/heartbeat", headers=pc_headers(new_token), json=READY).status_code == 200
    assert client.post(f"{BASE}/devices/{device_id}/rotate", headers=OWNER_HEADERS, json={"expected_revision": 1}).status_code == 409
    revoked = client.post(f"{BASE}/devices/{device_id}/revoke", headers=OWNER_HEADERS, json={"expected_revision": 2})
    assert revoked.status_code == 200
    assert client.post(BASE + "/companion/heartbeat", headers=pc_headers(new_token), json=READY).status_code == 401
    assert client.get(BASE + "/devices").json() == {"devices": []}
    assert client.post(f"{BASE}/devices/{device_id}/rotate", headers=OWNER_HEADERS, json={"expected_revision": 3}).status_code == 409


def test_pair_capacity_and_changed_replay_are_atomic():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        user = User(email="capacity@example.test")
        db.add(user); db.flush()
        now = datetime.now(timezone.utc)
        key = str(uuid4())
        first, _ = pair_device(db, owner_user_id=user.id, label="First", creation_key=key, now=now)
        with pytest.raises(HTTPException) as changed:
            pair_device(db, owner_user_id=user.id, label="Changed", creation_key=key, now=now)
        assert changed.value.status_code == 409
        for index in range(7):
            pair_device(db, owner_user_id=user.id, label=f"PC {index}", creation_key=str(uuid4()), now=now)
        replay, secret = pair_device(db, owner_user_id=user.id, label="First", creation_key=key, now=now)
        assert replay.id == first.id and secret is None
        with pytest.raises(HTTPException) as capacity:
            pair_device(db, owner_user_id=user.id, label="Ninth", creation_key=str(uuid4()), now=now)
        assert capacity.value.detail["reason"] == "local_device_limit"
    engine.dispose()


def seed_local_jobs(maker, owner_id, device_id, count=1, **overrides):
    from studio_api.models import JobStatus, Project, Source, SourceType, SourceUploadStatus, TranscriptionJob, TranscriptionJobSource
    import json
    with maker() as db:
        project = Project(owner_user_id=owner_id, title="Synthetic local jobs")
        db.add(project); db.flush()
        ids = []
        for index in range(count):
            source = Source(project_id=project.id, source_type=SourceType.local_upload,
                upload_status=SourceUploadStatus.uploaded, original_filename=f"synthetic-{index}.wav",
                mime_type="audio/wav", size_bytes=32044, s3_bucket="synthetic", s3_object_key=str(uuid4()))
            db.add(source); db.flush()
            fields = {"project_id": project.id, "owner_user_id": owner_id, "provider": "nemotron",
                "local_device_id": device_id, "status": JobStatus.queued, "output_drive_folder_id": "synthetic-folder",
                "options_json": json.dumps({"_stt_model": NEMOTRON_MODEL, "diarize": False}), **overrides}
            job = TranscriptionJob(**fields)
            db.add(job); db.flush()
            db.add(TranscriptionJobSource(job_id=job.id, source_id=source.id, position=0))
            ids.append(job.id)
        db.commit()
        return ids


def prepare_pc(client):
    reply, _ = pair(client)
    headers = pc_headers(reply.json()["pairing_token"])
    assert client.post(BASE + "/companion/heartbeat", headers=headers, json=READY).status_code == 200
    return reply.json()["device"]["id"], headers


def test_only_assigned_pc_can_claim_and_vps_cannot_seize_inference(local_app):
    from studio_api.job_claim_lease import acquire_next_ready_job_lease, acquire_job_lease, JobLeaseError
    client, maker, _, (owner_id, _) = local_app
    device_id, headers = prepare_pc(client)
    other_device, other_headers = prepare_pc(client)
    job_ids = seed_local_jobs(maker, owner_id, device_id, count=2)
    with maker() as db:
        now = datetime.now(timezone.utc)
        assert acquire_next_ready_job_lease(db, lease_owner_id="vps-worker", now=now, lease_ttl=timedelta(minutes=1)) is None
        with pytest.raises(JobLeaseError):
            acquire_job_lease(db, job_id=job_ids[0], lease_owner_id="vps-worker", now=now, lease_ttl=timedelta(minutes=1))
    assert client.post(BASE + "/companion/claim", headers=other_headers).json() == {"job": None}
    first = client.post(BASE + "/companion/claim", headers=headers)
    assert first.status_code == 200
    claimed = first.json()["job"]
    assert claimed["id"] == job_ids[0] and claimed["model"] == NEMOTRON_MODEL
    assert claimed["progress"] is None  # No fabricated elapsed percentage.
    replay = client.post(BASE + "/companion/claim", headers=headers)
    assert replay.json()["job"] == claimed
    with maker() as db:
        from studio_api.models import JobStatus, TranscriptionJob
        assert db.get(TranscriptionJob, job_ids[0]).attempt_count == 1
        assert db.get(TranscriptionJob, job_ids[1]).status == JobStatus.queued
        assert db.get(TranscriptionJob, job_ids[0]).source_access_started_at is not None


def test_local_progress_is_fenced_monotone_and_liveness_does_not_invent_advancement(local_app):
    import json
    from studio_api.models import TranscriptionJob
    client, maker, _, (owner_id, _) = local_app
    device_id, headers = prepare_pc(client)
    job_id = seed_local_jobs(maker, owner_id, device_id)[0]
    generation = client.post(BASE + "/companion/claim", headers=headers).json()["job"]["lease_generation"]
    path = f"{BASE}/companion/jobs/{job_id}/heartbeat"
    data = {"generation": generation, "sequence": 1, "stage": "source_download", "completed": 10, "total": 100, "unit": "bytes"}
    assert client.post(path, headers=headers, json=data).status_code == 200
    with maker() as db:
        previous = db.get(TranscriptionJob, job_id).work_progress_json
    assert client.post(path, headers=headers, json=data).status_code == 200
    with maker() as db:
        assert db.get(TranscriptionJob, job_id).work_progress_json == previous
    assert client.post(path, headers=headers, json={**data, "completed": 11}).status_code == 409
    assert client.post(path, headers=headers, json={**data, "sequence": 2, "completed": 9}).status_code == 409
    unknown = {"generation": generation, "sequence": 2, "stage": "local_transcription"}
    assert client.post(path, headers=headers, json={**unknown, "completed": 20, "total": 100, "unit": "seconds"}).status_code == 422
    assert client.post(path, headers=headers, json=unknown).status_code == 200
    assert client.post(path, headers=headers, json={**data, "sequence": 3}).status_code == 409
    assert client.post(path, headers=headers, json={**unknown, "generation": generation + 1, "sequence": 3}).status_code == 409
    with maker() as db:
        progress = json.loads(db.get(TranscriptionJob, job_id).work_progress_json)
        assert progress["completed"] is None and progress["total"] is None and progress["unit"] is None


def test_local_cancel_is_acknowledged_without_cloud_or_second_job(local_app):
    from studio_api.job_processing_lifecycle import request_job_cancellation
    from studio_api.models import JobStatus, TranscriptionJob
    client, maker, _, (owner_id, _) = local_app
    device_id, headers = prepare_pc(client)
    job_id = seed_local_jobs(maker, owner_id, device_id)[0]
    generation = client.post(BASE + "/companion/claim", headers=headers).json()["job"]["lease_generation"]
    with maker() as db:
        request_job_cancellation(db, job_id=job_id, now=datetime.now(timezone.utc))
        db.commit()
    path = f"{BASE}/companion/jobs/{job_id}/heartbeat"
    reply = client.post(path, headers=headers, json={"generation": generation, "sequence": 1, "stage": "local_transcription"})
    assert reply.status_code == 200 and reply.json() == {"cancelled": True}
    assert client.post(path, headers=headers, json={"generation": generation, "sequence": 2, "stage": "local_transcription"}).status_code == 409
    with maker() as db:
        row = db.get(TranscriptionJob, job_id)
        assert row.status == JobStatus.cancelled and row.lease_owner_id is None
        assert row.provider == "nemotron" and row.provider_credential_id is None


def test_sleeping_pc_becomes_recoverable_failure_instead_of_automatic_dispatch(local_app):
    from studio_api.job_retry_recovery import compute_explicit_retry_readiness
    from studio_api.models import JobStatus, TranscriptionJob
    from studio_api.worker_recovery import recover_expired_worker_jobs
    client, maker, _, (owner_id, _) = local_app
    device_id, headers = prepare_pc(client)
    job_id = seed_local_jobs(maker, owner_id, device_id)[0]
    client.post(BASE + "/companion/claim", headers=headers)
    now = datetime.now(timezone.utc) + timedelta(seconds=100)
    with maker() as db:
        assert recover_expired_worker_jobs(db, now=now) == 1
        db.commit()
        row = db.get(TranscriptionJob, job_id)
        assert row.status == JobStatus.failed and row.error_code == "local_device_offline"
        assert row.lease_owner_id is None and row.retry_not_before_at is None
        assert compute_explicit_retry_readiness(db, row, now=now).available


@pytest.mark.parametrize("action", ["rotate", "revoke"])
def test_credential_changes_fence_pending_and_active_local_jobs_but_preserve_accepted_export(local_app, action):
    from studio_api.models import JobStatus, TranscriptionJob
    client, maker, _, (owner_id, _) = local_app
    device_id, headers = prepare_pc(client)
    job_ids = seed_local_jobs(maker, owner_id, device_id, count=3)
    generation = client.post(BASE + "/companion/claim", headers=headers).json()["job"]["lease_generation"]
    with maker() as db:
        accepted = db.get(TranscriptionJob, job_ids[2])
        accepted.local_result_ready_at = datetime.now(timezone.utc)
        db.commit()
    reply = client.post(f"{BASE}/devices/{device_id}/{action}", headers=OWNER_HEADERS, json={"expected_revision": 1})
    assert reply.status_code == 200
    with maker() as db:
        first, queued, accepted = [db.get(TranscriptionJob, item) for item in job_ids]
        assert first.status == queued.status == JobStatus.failed
        assert first.error_code == queued.error_code == "local_device_revoked"
        assert first.lease_generation > generation and first.lease_owner_id is None
        assert accepted.status == JobStatus.queued and accepted.local_result_ready_at is not None


def test_missing_runtime_and_archived_or_foreign_project_are_not_dispatched(local_app):
    from studio_api.models import Project, TranscriptionJob
    client, maker, _, (owner_id, other_id) = local_app
    device_id, headers = prepare_pc(client)
    job_ids = seed_local_jobs(maker, owner_id, device_id, count=2)
    with maker() as db:
        first = db.get(TranscriptionJob, job_ids[0])
        db.get(Project, first.project_id).archived_at = datetime.now(timezone.utc)
        db.commit()
    assert client.post(BASE + "/companion/claim", headers=headers).json() == {"job": None}
    with maker() as db:
        first = db.get(TranscriptionJob, job_ids[0])
        project = db.get(Project, first.project_id)
        project.archived_at = None
        project.owner_user_id = other_id
        db.commit()
    assert client.post(BASE + "/companion/claim", headers=headers).json() == {"job": None}
    client.post(BASE + "/companion/heartbeat", headers=headers, json={"runtime_status": "runtime_missing"})
    unavailable = client.post(BASE + "/companion/claim", headers=headers)
    assert unavailable.status_code == 409 and unavailable.json()["detail"]["reason"] == "local_device_not_ready"
