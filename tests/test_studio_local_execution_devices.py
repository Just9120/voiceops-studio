"""A paired PC receives a narrow capability, never an owner/provider session."""
import hashlib
import json
import os
import secrets
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
from studio_api.local_model_identity import MODEL_REVISIONS, PARAKEET_MODEL
from studio_api.models import AuditEvent, Base, LocalExecutionDevice, Session, User, UserStatus
from studio_api.nemotron_local_result import NEMOTRON_MODEL
from studio_api.security import token_hash


@pytest.fixture
def local_app(monkeypatch):
    from studio_api import deps, main
    from studio_api.config import Settings, get_settings
    from studio_api.db import get_db
    settings = Settings(database_url="sqlite+pysqlite:///:memory:", app_origin="https://studio.test", cookie_secure=False)
    import base64
    monkeypatch.setattr(Settings, "master_key_b64", lambda _self: base64.b64encode(b"s" * 32).decode())
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


def test_closed_installer_download_checks_owner_release_identity_and_bytes(local_app, tmp_path):
    client, _, settings, (owner_id, _) = local_app
    endpoint = BASE + "/companion-release"
    assert client.get(endpoint).status_code == 404
    data = b"MZ synthetic installer"
    sha = hashlib.sha256(data).hexdigest()
    directory = tmp_path / sha
    directory.mkdir()
    installer = directory / "VoiceOpsCompanion-Setup.exe"
    installer.write_bytes(data)
    manifest = directory / "installer.json"
    release = {"version": "0.1.0", "source_commit": "a" * 40, "source_dirty": False,
               "smoke": False, "file": installer.name, "bytes": len(data), "sha256": sha}
    manifest.write_text(json.dumps(release), encoding="utf-8")
    settings.companion_release_owner_id = owner_id
    settings.companion_release_sha256 = sha
    settings.companion_release_directory = str(tmp_path)
    download = f"{endpoint}/{sha}/download"

    metadata = client.get(endpoint)
    assert metadata.json()["sha256"] == sha and metadata.json()["signed"] is False
    response = client.get(download)
    assert response.content == data
    assert response.headers["cache-control"] == "no-store"
    assert "attachment" in response.headers["content-disposition"]
    assert client.get(f"{endpoint}/{'a' * 64}/download").status_code == 404

    client.cookies.set(settings.cookie_name, "other-session")
    assert client.get(endpoint).status_code == client.get(download).status_code == 404
    client.cookies.clear()
    assert client.get(endpoint).status_code == client.get(download).status_code == 401
    client.cookies.set(settings.cookie_name, "owner-session")
    manifest.write_text(json.dumps({**release, "smoke": True}), encoding="utf-8")
    assert client.get(download).status_code == 404
    manifest.write_text(json.dumps(release), encoding="utf-8")
    installer.write_bytes(data[::-1])
    assert client.get(download).status_code == 404


def test_hub_catalog_paginates_without_trusting_external_navigation(local_app, monkeypatch):
    from contextlib import contextmanager
    import httpx
    from studio_api import local_model_catalog as catalog

    @contextmanager
    def stream(method, url, *, params, timeout, follow_redirects):
        assert method == "GET" and url == catalog.HUB_MODELS and not follow_redirects
        assert ("pipeline_tag", catalog.TASK) in params and ("filter", "ru") in params
        assert ("sort", "likes") in params
        linked_host = "untrusted.example" if ("cursor", "opaque=") in params else "huggingface.co"
        yield httpx.Response(200, request=httpx.Request("GET", url),
            headers={"link": f'<https://{linked_host}/api/models?cursor=opaque%3D>; rel="next"'},
            json=[{"id": "nvidia/parakeet-tdt-0.6b-v3", "tags": ["ru", "license:cc-by-4.0"], "pipeline_tag": catalog.TASK, "gated": False},
                  {"id": "other/model", "tags": ["ru"], "likes": 10, "pipeline_tag": catalog.TASK, "gated": "manual"},
                  {"id": "other/diarization", "pipeline_tag": "audio-to-audio", "tags": ["speaker-diarization", catalog.TASK]},
                  {"id": "other/unknown", "tags": ["ru", "speaker-diarization"]},
                  {"id": "https://unexpected.test"}])

    monkeypatch.setattr(catalog.httpx, "stream", stream)
    catalog._page.cache_clear()
    try:
        client, *_ = local_app
        query = BASE + "/catalog?search=test-catalog&language=ru&sort=likes"
        first = client.get(query).json()
        assert [item["id"] for item in first["items"]] == ["nvidia/parakeet-tdt-0.6b-v3", "other/model"]
        assert first["items"][0]["studio"]["download_bytes"] == 713975456
        assert first["items"][0]["access"] == "public"
        assert first["items"][1]["access"] == "gated"
        assert first["items"][1]["studio"] is None and first["next_cursor"] == "opaque="
        assert client.get(query + "&cursor=opaque%3D").json()["next_cursor"] is None
    finally:
        catalog._page.cache_clear()


def test_studio_catalog_sorts_current_metrics_and_links_exact_weights(monkeypatch):
    from studio_api import local_model_catalog as catalog
    supported_ids = list(catalog.STUDIO_PROFILES)
    nemotron_id, parakeet_id = supported_ids
    nemotron = catalog.STUDIO_PROFILES[nemotron_id]
    parakeet = catalog.STUDIO_PROFILES[parakeet_id]
    metrics = {
        nemotron["weights_repository"]: (100, 10),
        parakeet["weights_repository"]: (20, 50),
    }

    def hub_json(url, params):
        repo = url.removeprefix(catalog.HUB_MODELS + "/")
        assert ("expand", "gated") in params
        downloads, likes = metrics[repo]
        return {"id": repo, "pipeline_tag": catalog.TASK, "gated": False,
                "downloads": downloads, "likes": likes, "sha": "b" * 40}, ""

    monkeypatch.setattr(catalog, "_hub_json", hub_json)
    catalog._studio_profile_item.cache_clear()
    try:
        downloads = catalog.catalog_page(search="", language="ru", sort="downloads", cursor="", supported=True)["items"]
        likes = catalog.catalog_page(search="", language="ru", sort="likes", cursor="", supported=True)["items"]
        assert [item["id"] for item in downloads] == supported_ids
        assert [item["id"] for item in likes] == supported_ids[::-1]
        for item, profile in zip(downloads, (nemotron, parakeet), strict=True):
            assert item["studio"]["weights_url"] == (
                f"https://huggingface.co/{profile['weights_repository']}/tree/{profile['revision']}"
            )
            assert item["studio"]["min_ram_bytes"] is None
        assert downloads[0]["hub_revision"] is None
        assert downloads[1]["studio"]["max_audio_seconds"] == 1440
    finally:
        catalog._studio_profile_item.cache_clear()


def test_inventory_is_only_readable_by_owner_and_rotated_with_capability(local_app, monkeypatch):
    from studio_api.main import limiter

    class Store(dict):
        def set(self, key, value, *, ex):
            assert ex == 300
            self[key] = value

    monkeypatch.setattr(limiter, "redis", Store())
    client, _, settings, _ = local_app
    device_id, headers = prepare_pc(client)
    inventory = {"cpu": "Synthetic x64", "cpu_threads": 8, "ram_bytes": 17179869184, "gpus": [],
                 "disk_free_bytes": 1073741824, "execution": ["cpu"], "installed": [PARAKEET_MODEL]}
    reader = f"{BASE}/devices/{device_id}/inventory"
    assert client.get(reader).json() == {"inventory": None}
    assert client.post(BASE + "/companion/inventory", headers=headers, json=inventory).status_code == 200
    assert client.get(reader).json()["inventory"]["installed"] == [PARAKEET_MODEL]
    assert client.get(reader).json()["inventory"]["verified_installations"] == []
    inventory["verified_installations"] = [PARAKEET_MODEL]
    assert client.post(BASE + "/companion/inventory", headers=headers, json=inventory).status_code == 200
    assert client.get(reader).json()["inventory"]["verified_installations"] == [PARAKEET_MODEL]
    client.cookies.set(settings.cookie_name, "other-session")
    assert client.get(reader).status_code == 404
    client.cookies.set(settings.cookie_name, "owner-session")
    assert client.post(f"{BASE}/devices/{device_id}/rotate", headers=OWNER_HEADERS, json={"expected_revision": 1}).status_code == 200
    assert client.get(reader).json() == {"inventory": None}


def test_browser_install_request_requires_owner_and_only_delivers_pinned_version(local_app, monkeypatch):
    from studio_api.main import limiter

    class Store(dict):
        def set(self, key, value, *, ex):
            assert ex == 300
            self[key] = value

        def delete(self, key):
            self.pop(key, None)

    monkeypatch.setattr(limiter, "redis", Store())
    client, _, settings, _ = local_app
    device_id, headers = prepare_pc(client)
    sender = f"{BASE}/devices/{device_id}/model-install"
    receiver = BASE + "/companion/model-install-request"
    selected = {"model": PARAKEET_MODEL, "revision": MODEL_REVISIONS[PARAKEET_MODEL]}
    assert client.post(sender, json=selected).status_code == 403
    assert client.post(sender, headers=OWNER_HEADERS, json={**selected, "revision": "0" * 40}).status_code == 422
    client.cookies.set(settings.cookie_name, "other-session")
    assert client.post(sender, headers=OWNER_HEADERS, json=selected).status_code == 404
    client.cookies.set(settings.cookie_name, "owner-session")
    assert client.post(sender, headers=OWNER_HEADERS, json=selected).json() == {"pending": True}
    request = client.post(receiver, headers=headers, json={}).json()["request"]
    assert {key: request[key] for key in selected} == selected
    assert client.post(sender, headers=OWNER_HEADERS, json=selected).status_code == 200
    assert client.post(receiver, headers=headers, json={}).json()["request"] == request
    assert client.post(receiver, headers=headers, json={"request_id": request["id"]}).json() == {"request": None}
    assert client.post(receiver, headers=headers, json={}).json() == {"request": None}


def pair(client, **changes):
    data = {"label": "Synthetic PC", "creation_key": str(uuid4()), **changes}
    reply = client.post(BASE + "/devices", headers=OWNER_HEADERS, json=data)
    assert reply.status_code == 200, reply.text
    return reply, data


def pc_headers(token):
    return {"authorization": "Bearer " + token, "x-voiceops-local-protocol": "1"}


@pytest.fixture
def enrollment_store(monkeypatch):
    from studio_api.main import limiter

    class Store:
        def __init__(self):
            self.values = {}

        def set(self, key, value, *, ex, nx):
            assert 0 < ex <= 300 and nx
            if key in self.values:
                return False
            self.values[key] = value
            return True

        def get(self, key):
            return self.values.get(key)

        def ttl(self, key):
            return 300 if key in self.values else -2

    store = Store()
    monkeypatch.setattr(limiter, "redis", store)
    return store


def test_browser_enrollment_is_owner_approved_proof_bound_and_replay_safe(local_app, enrollment_store):
    client, maker, settings, (owner_id, _) = local_app
    machine = {"x-voiceops-local-protocol": "1"}
    verifier = secrets.token_urlsafe(32)
    data = {"label": "Synthetic Windows", "challenge": hashlib.sha256(verifier.encode()).hexdigest()}
    enrollment = BASE + "/enrollment"
    assert client.post(enrollment, headers={**machine, "origin": settings.app_origin}, json=data).status_code == 403
    started = client.post(enrollment, headers=machine, json=data)
    assert started.status_code == 200
    device_id = started.json()["request_id"]
    token = f"vs-local.{device_id}.{verifier}"
    path = enrollment + "/" + device_id
    assert client.get(path).json() == {"label": data["label"], "approved": False}
    assert client.post(path + "/finish", headers=machine, json={"verifier": verifier}).status_code == 202
    assert client.post(path + "/approve").status_code == 403
    approved = client.post(path + "/approve", headers=OWNER_HEADERS)
    assert approved.json() == {"label": data["label"], "approved": True}
    assert verifier not in approved.text
    client.cookies.set(settings.cookie_name, "other-session")
    assert client.get(path).status_code == 404
    assert client.post(path + "/approve", headers=OWNER_HEADERS).status_code == 404
    assert client.post(path + "/finish", headers=machine, json={"verifier": "x" * 43}).status_code == 403
    client.cookies.clear()
    for _ in range(2):
        finished = client.post(path + "/finish", headers=machine, json={"verifier": verifier})
        assert finished.status_code == 200
        assert finished.json()["device"]["id"] == device_id
        assert not finished.json()["device"]["ready"]
        assert verifier not in finished.text
        assert finished.headers["cache-control"] == "no-store"
    assert client.post(BASE + "/companion/heartbeat", headers=pc_headers(token), json=READY).status_code == 200
    stopped = client.post(BASE + "/companion/stopped", headers=pc_headers(token)).json()["device"]
    assert not stopped["online"] and not stopped["ready"]
    with maker() as db:
        rows = db.scalars(select(LocalExecutionDevice)).all()
        assert len(rows) == 1 and rows[0].owner_user_id == owner_id
        assert rows[0].token_hash == token_hash(token)
        assert verifier not in str(db.scalars(select(AuditEvent.metadata_json)).all())
    assert verifier not in str(enrollment_store.values)
    client.cookies.set(settings.cookie_name, "owner-session")
    assert client.post(BASE + f"/devices/{device_id}/revoke", headers=OWNER_HEADERS,
                       json={"expected_revision": 1}).status_code == 200
    assert client.post(path + "/finish", headers=machine, json={"verifier": verifier}).status_code == 409
    enrollment_store.values.clear()
    assert client.post(path + "/finish", headers=machine, json={"verifier": verifier}).status_code == 410


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
    for state in ("loading_model",):
        reply = client.post(BASE + "/companion/heartbeat", headers=pc_headers(token), json={"runtime_status": state})
        assert reply.status_code == 200 and not reply.json()["device"]["ready"]
        assert reply.json()["device"]["runtime_status"] == state


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
        created = datetime.now(timezone.utc)
        for index in range(count):
            source = Source(project_id=project.id, source_type=SourceType.local_upload,
                upload_status=SourceUploadStatus.uploaded, original_filename=f"synthetic-{index}.wav",
                mime_type="audio/wav", size_bytes=32044, s3_bucket="synthetic", s3_object_key=str(uuid4()))
            db.add(source); db.flush()
            fields = {"project_id": project.id, "owner_user_id": owner_id, "provider": "nemotron",
                "local_device_id": device_id, "status": JobStatus.queued, "output_drive_folder_id": "synthetic-folder",
                "media_timeline_version": 2,
                "created_at": created + timedelta(microseconds=index),
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


@pytest.mark.parametrize("blocked_by", ["other_model", "expired_source"])
def test_local_claim_finds_ready_job_after_full_page_of_ineligible_jobs(local_app, blocked_by):
    import json
    from studio_api.models import JobStatus, TranscriptionJob

    client, maker, _, (owner_id, _) = local_app
    device_id, headers = prepare_pc(client)
    blocked_ids = seed_local_jobs(maker, owner_id, device_id, count=50)
    ready_id = seed_local_jobs(maker, owner_id, device_id)[0]

    with maker() as db:
        for job_id in blocked_ids:
            job = db.get(TranscriptionJob, job_id)
            if blocked_by == "other_model":
                job.options_json = json.dumps({"_stt_model": PARAKEET_MODEL,
                    "_local_model_revision": MODEL_REVISIONS[PARAKEET_MODEL]})
            else:
                job.sources[0].source.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.commit()

    response = client.post(BASE + "/companion/claim", headers=headers)
    assert response.status_code == 200
    assert response.json()["job"]["id"] == ready_id
    assert client.post(BASE + "/companion/claim", headers=headers).json() == response.json()
    with maker() as db:
        assert all(db.get(TranscriptionJob, job_id).status == JobStatus.queued for job_id in blocked_ids)


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


def input_fixture(monkeypatch):
    from contextlib import contextmanager
    import io
    import wave
    from studio_api import local_execution_transfer as transfer
    from studio_api.job_source_materialization import MaterializedJobSource, MaterializedSourceIdentity
    from studio_api.models import TranscriptionJobSource
    audio = io.BytesIO()
    with wave.open(audio, "wb") as writer:
        writer.setnchannels(1); writer.setsampwidth(2); writer.setframerate(16000)
        writer.writeframes(b"\0\0" * 16000)
    raw = audio.getvalue()
    closed = []
    @contextmanager
    def materialize(db, *, job_id, job_source_id, **kwargs):
        relation = db.get(TranscriptionJobSource, job_source_id)
        stream = io.BytesIO(raw)
        try:
            yield MaterializedJobSource(identity=MaterializedSourceIdentity(job_id, job_source_id, relation.source_id),
                position=0, original_filename="synthetic.wav", mime_type="audio/wav", byte_count=len(raw), stream=stream)
        finally:
            stream.close(); closed.append(True)
    monkeypatch.setattr(transfer, "materialize_processing_job_source", materialize)
    return raw, closed


def stage_local_input(client, maker, owner_id, monkeypatch, model=NEMOTRON_MODEL):
    import hashlib
    raw, closed = input_fixture(monkeypatch)
    device_id, headers = prepare_pc(client)
    job_id = seed_local_jobs(maker, owner_id, device_id)[0]
    if model != NEMOTRON_MODEL:
        from studio_api.models import TranscriptionJob
        with maker() as db:
            job = db.get(TranscriptionJob, job_id)
            job.options_json = json.dumps({**json.loads(job.options_json), "_stt_model": model,
                                           "_local_model_revision": MODEL_REVISIONS[model]})
            db.commit()
        assert client.post(BASE + "/companion/claim", headers=headers).json() == {"job": None}
        ready = client.post(BASE + "/companion/heartbeat", headers=headers,
            json={**READY, "model": model, "model_revision": MODEL_REVISIONS[model]})
        assert ready.status_code == 200, ready.text
    claimed = client.post(BASE + "/companion/claim", headers=headers).json()["job"]
    assert claimed["model"] == model and claimed["model_revision"] == MODEL_REVISIONS[model]
    generation = claimed["lease_generation"]
    source = client.get(f"{BASE}/companion/jobs/{job_id}/source", params={"generation": generation}, headers=headers)
    assert source.status_code == 200, source.text
    assert source.content == raw and len(closed) == 1
    sha = hashlib.sha256(raw).hexdigest()
    assert source.headers["x-voiceops-input-sha256"] == sha
    prepared = client.post(f"{BASE}/companion/jobs/{job_id}/prepare", headers=headers,
        json={"generation": generation, "source_sha256": sha, "source_duration_seconds": 1.0})
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["prepared_duration_seconds"] == 1
    return device_id, headers, job_id, generation, sha


def native_envelope(generation, sha):
    return {"generation": generation, "source_sha256": sha, "result": {"file": "C:/synthetic-private-path/input.wav",
        "text": "Synthetic transcript.", "confidence": 0, "duration": 1.0, "languages": ["en"],
        "words": [{"word": "Synthetic", "start": 0.0, "end": .4, "confidence": 0},
                  {"word": "transcript.", "start": .4, "end": 1.0, "confidence": 0}]}}


def post_native(client, headers, job_id, envelope):
    import gzip
    import json
    return client.post(f"{BASE}/companion/jobs/{job_id}/result",
        headers={**headers, "content-type": "application/gzip"}, content=gzip.compress(json.dumps(envelope).encode()))


@pytest.mark.parametrize("model", [NEMOTRON_MODEL, PARAKEET_MODEL])
def test_complete_local_result_is_encrypted_idempotent_and_exported_without_inputs_or_cloud(local_app, monkeypatch, model):
    from studio_api.job_claim_lease import acquire_next_ready_job_lease
    from studio_api.job_processing_lifecycle import begin_job_processing
    from studio_api.job_retry_recovery import prepare_current_attempt_sources
    from studio_api.job_stt_transcription import transcribe_processing_job_source
    from studio_api.models import JobStatus, SourceUploadStatus, TranscriptionJob, TranscriptionProviderPartCheckpoint
    from studio_api import job_stt_transcription as dispatch
    client, maker, settings, (owner_id, _) = local_app
    _, headers, job_id, generation, sha = stage_local_input(client, maker, owner_id, monkeypatch, model)
    envelope = native_envelope(generation, sha)
    if model == PARAKEET_MODEL:
        assert post_native(client, headers, job_id, envelope).status_code == 409
        assert post_native(client, headers, job_id, {**envelope, "model": model, "model_revision": "0" * 40}).status_code == 409
        envelope.update(model=model, model_revision=MODEL_REVISIONS[model])
        removal = client.post(BASE + "/companion/model-removal", headers=headers,
            json={"model": model, "revision": MODEL_REVISIONS[model]})
        assert removal.status_code == 409
    accepted = post_native(client, headers, job_id, envelope)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {"accepted": True, "already_accepted": False}
    assert "Synthetic transcript" not in accepted.text and "private-path" not in accepted.text
    def forbid_cloud(*args, **kwargs):
        pytest.fail("Local export must not resolve a cloud capability or transport")
    monkeypatch.setattr(dispatch, "resolve_capability", forbid_cloud)
    with maker() as db:
        job = db.get(TranscriptionJob, job_id)
        assert job.status == JobStatus.queued and job.lease_owner_id is None and job.local_result_generation == generation
        from studio_api.models import SttProviderOperation
        assert db.scalar(select(TranscriptionProviderPartCheckpoint)) is None
        checkpoints = db.scalars(select(SttProviderOperation)).all()
        assert len(checkpoints) == 1 and b"Synthetic transcript" not in checkpoints[0].result_ciphertext
        assert checkpoints[0].model == model
        # No source bytes/key are needed to export the complete accepted text.
        source = job.sources[0].source
        source.upload_status = SourceUploadStatus.expired
        source.expires_at = datetime.now(timezone.utc) - timedelta(days=2)
        source.s3_object_key = source.s3_bucket = None
        db.commit()
        now = datetime.now(timezone.utc)
        lease = acquire_next_ready_job_lease(db, lease_owner_id="vps-export-worker", now=now, lease_ttl=timedelta(minutes=2))
        assert lease is not None and lease.job_id == job_id
        begin_job_processing(db, job_id=job_id, lease_owner_id=lease.lease_owner_id, lease_generation=lease.lease_generation, now=now)
        prepare_current_attempt_sources(db, job_id=job_id, lease_owner_id=lease.lease_owner_id, lease_generation=lease.lease_generation, now=now)
        db.commit()
        with transcribe_processing_job_source(db, job_id=job_id, job_source_id=job.sources[0].id,
            lease_owner_id=lease.lease_owner_id, lease_generation=lease.lease_generation, settings=settings, clock=lambda: now) as result:
            assert result.text == "Synthetic transcript." and result.words[1].start == .4
        assert job.attempt_count == 2 and job.provider_credential_id is None
    replay = post_native(client, headers, job_id, envelope)
    assert replay.status_code == 200 and replay.json()["already_accepted"]
    changed = native_envelope(generation, sha)
    changed["result"]["text"] = "Different result"
    assert post_native(client, headers, job_id, changed).status_code == 409
    with maker() as db:
        assert db.scalar(select(TranscriptionProviderPartCheckpoint)) is None
        assert len(db.scalars(select(SttProviderOperation)).all()) == 1


@pytest.mark.parametrize("failure", ["wrong_sha", "stale_generation", "cancelled", "changed_source", "partial_result", "wrong_duration"])
def test_local_result_rejects_stale_partial_or_changed_input_without_checkpoint(local_app, monkeypatch, failure):
    from studio_api.models import TranscriptionJob, TranscriptionProviderPartCheckpoint, SourceAttemptStage
    from studio_api.job_processing_lifecycle import request_job_cancellation
    client, maker, _, (owner_id, _) = local_app
    _, headers, job_id, generation, sha = stage_local_input(client, maker, owner_id, monkeypatch)
    envelope = native_envelope(generation, sha)
    if failure == "wrong_sha":
        envelope["source_sha256"] = "f" * 64
    elif failure == "stale_generation":
        envelope["generation"] += 1
    elif failure == "partial_result":
        envelope["result"]["truncated"] = True
    elif failure == "wrong_duration":
        envelope["result"]["duration"] = 10
    else:
        with maker() as db:
            if failure == "cancelled":
                request_job_cancellation(db, job_id=job_id, now=datetime.now(timezone.utc))
            else:
                db.get(TranscriptionJob, job_id).sources[0].source.drive_sha256_checksum = "a" * 64
            db.commit()
    response = post_native(client, headers, job_id, envelope)
    assert response.status_code in {409, 422}
    assert "private-path" not in response.text and "Synthetic transcript" not in response.text
    with maker() as db:
        assert db.scalar(select(TranscriptionProviderPartCheckpoint)) is None
        assert db.get(TranscriptionJob, job_id).local_result_ready_at is None


def test_local_result_gzip_is_bounded_and_rejects_duplicate_keys_and_unparseable_data():
    import gzip
    from studio_api.local_execution_transfer import decode_local_result, MAX_ENVELOPE_BYTES
    for raw in (b"not-gzip", gzip.compress(b'{"generation":1,"generation":2}'),
                gzip.compress(b"{"), gzip.compress(b"x" * (MAX_ENVELOPE_BYTES + 1))):
        with pytest.raises(HTTPException) as error:
            decode_local_result(raw)
        assert error.value.status_code == 422 and error.value.detail == {"reason": "local_result_invalid"}


@pytest.mark.parametrize("after_flush", [False, True])
def test_result_persistence_failure_rolls_back_and_same_full_payload_can_be_retried(local_app, monkeypatch, after_flush):
    from studio_api import local_execution_transfer as transfer
    from studio_api.models import JobStatus, TranscriptionJob, TranscriptionJobSourceAttempt, TranscriptionProviderPartCheckpoint, SourceAttemptStage
    client, maker, _, (owner_id, _) = local_app
    _, headers, job_id, generation, sha = stage_local_input(client, maker, owner_id, monkeypatch)
    envelope = native_envelope(generation, sha)
    save = transfer.persist_operation_result
    def unavailable(*args, **kwargs):
        if after_flush:
            assert kwargs["commit"] is False
            save(*args, **kwargs)
        raise RuntimeError("synthetic private persistence diagnostic")
    monkeypatch.setattr(transfer, "persist_operation_result", unavailable)
    failed = post_native(client, headers, job_id, envelope)
    assert failed.status_code == 503 and failed.json()["detail"]["reason"] == "local_result_persistence_unavailable"
    assert "private" not in failed.text
    with maker() as db:
        job = db.get(TranscriptionJob, job_id)
        assert job.status == JobStatus.processing and job.local_result_ready_at is None
        assert db.scalar(select(TranscriptionProviderPartCheckpoint)) is None
        from studio_api.models import SttProviderOperation
        assert db.scalar(select(SttProviderOperation)) is None
        assert db.scalar(select(TranscriptionJobSourceAttempt)).stage == SourceAttemptStage.prepared
    monkeypatch.setattr(transfer, "persist_operation_result", save)
    assert post_native(client, headers, job_id, envelope).status_code == 200


def test_same_native_content_on_two_jobs_has_distinct_atomic_cache_identity(local_app, monkeypatch):
    import hashlib
    from studio_api.models import SttProviderOperation
    client, maker, _, (owner_id, _) = local_app
    raw, _ = input_fixture(monkeypatch)
    sha = hashlib.sha256(raw).hexdigest()
    device_id, headers = prepare_pc(client)
    jobs = seed_local_jobs(maker, owner_id, device_id, count=2)
    for job_id in jobs:
        claimed = client.post(BASE + "/companion/claim", headers=headers).json()["job"]
        assert claimed["id"] == job_id
        generation = claimed["lease_generation"]
        assert client.get(f"{BASE}/companion/jobs/{job_id}/source", params={"generation": generation}, headers=headers).status_code == 200
        assert client.post(f"{BASE}/companion/jobs/{job_id}/prepare", headers=headers,
            json={"generation": generation, "source_sha256": sha, "source_duration_seconds": 1}).status_code == 200
        assert post_native(client, headers, job_id, native_envelope(generation, sha)).status_code == 200
    with maker() as db:
        operations = db.scalars(select(SttProviderOperation)).all()
        assert len(operations) == 2 and len({row.operation_id for row in operations}) == 2
        assert {row.job_id for row in operations} == set(jobs)


def test_missing_accepted_local_checkpoint_never_dispatches_a_cloud_provider(local_app, monkeypatch):
    from studio_api.job_claim_lease import acquire_next_ready_job_lease
    from studio_api.job_processing_lifecycle import begin_job_processing
    from studio_api.job_stt_transcription import transcribe_processing_job_source
    from studio_api.job_elevenlabs_transcription import JobElevenLabsTranscriptionError
    from studio_api.models import TranscriptionJob
    from studio_api import job_stt_transcription as dispatch
    client, maker, settings, (owner_id, _) = local_app
    device_id, _ = prepare_pc(client)
    job_id = seed_local_jobs(maker, owner_id, device_id)[0]
    with maker() as db:
        job = db.get(TranscriptionJob, job_id)
        job.local_result_ready_at = datetime.now(timezone.utc)  # A corrupt/missing text checkpoint.
        db.commit()
        now = datetime.now(timezone.utc)
        lease = acquire_next_ready_job_lease(db, lease_owner_id="vps-export-worker", now=now, lease_ttl=timedelta(minutes=2))
        begin_job_processing(db, job_id=job_id, lease_owner_id=lease.lease_owner_id, lease_generation=lease.lease_generation, now=now)
        def forbid_cloud(*args, **kwargs):
            pytest.fail("Missing local text cannot authorize a cloud request")
        monkeypatch.setattr(dispatch, "resolve_capability", forbid_cloud)
        with pytest.raises(JobElevenLabsTranscriptionError) as failure:
            with transcribe_processing_job_source(db, job_id=job_id, job_source_id=job.sources[0].id,
                lease_owner_id=lease.lease_owner_id, lease_generation=lease.lease_generation, settings=settings, clock=lambda: now):
                pytest.fail("Missing local text cannot be returned as a successful transcript")
        assert failure.value.reason.value == "prerequisites_unavailable"


def test_local_capabilities_are_opt_in_so_existing_pwa_catalog_contract_stays_valid(local_app):
    client, *_ = local_app
    legacy = client.get("/api/stt/providers")
    assert legacy.status_code == 200 and len(legacy.json()["providers"]) == 5
    assert all(row["provider"] != "nemotron" for row in legacy.json()["providers"])
    expanded = client.get("/api/stt/providers?include_local=true")
    assert expanded.status_code == 200 and len(expanded.json()["providers"]) == 6
    local = next(row for row in expanded.json()["providers"] if row["provider"] == "nemotron")
    assert len(local["modes"]) == 1
    capability = local["modes"][0]
    assert capability["transport"] == "local_companion" and capability["languages"] == ["ru", "en"]
    assert capability["file_constraints"]["max_duration_seconds"] == 3600
    assert capability["diarization"] and not capability["dictionaries"]


def local_batch_fixture(client, maker, owner_id, monkeypatch):
    from studio_api import main
    from studio_api.models import Project, Source, SourceType, SourceUploadStatus
    from studio_api.job_output_folder_selection import VerifiedOutputFolderSelection
    device_id, headers = prepare_pc(client)
    with maker() as db:
        project = Project(owner_user_id=owner_id, title="Synthetic local batch")
        db.add(project); db.flush()
        source = Source(project_id=project.id, source_type=SourceType.local_upload, upload_status=SourceUploadStatus.uploaded,
            original_filename="synthetic.wav", mime_type="audio/wav", size_bytes=32044, s3_bucket="synthetic", s3_object_key="synthetic-source")
        db.add(source); db.commit()
        project_id, source_id = project.id, source.id
    monkeypatch.setattr(main, "refreshed_google_drive_access_token", lambda *_: "synthetic-token")
    monkeypatch.setattr(main, "verify_output_folder_selection", lambda *_: VerifiedOutputFolderSelection(
        "synthetic-folder", "Synthetic output", "https://drive.google.com/drive/folders/synthetic-folder", datetime.now(timezone.utc)))
    body = {"provider": "nemotron", "local_device_id": device_id, "language": "ru", "options": {"diarize": False},
            "items": [{"source_id": source_id, "output_folder_id": "synthetic-folder", "title": "Synthetic local result"}]}
    return project_id, device_id, headers, body


def test_batch_creation_persists_explicit_local_target_and_model_without_cloud_key(local_app, monkeypatch):
    from studio_api.models import TranscriptionJob
    client, maker, _, (owner_id, _) = local_app
    project_id, device_id, _, body = local_batch_fixture(client, maker, owner_id, monkeypatch)
    preflight = client.post(f"/api/projects/{project_id}/jobs/batch/preflight", headers=OWNER_HEADERS, json=body)
    assert preflight.status_code == 200, preflight.text
    assert preflight.json()["model"] == NEMOTRON_MODEL
    key = str(uuid4())
    response = client.post(f"/api/projects/{project_id}/jobs/batch", headers={**OWNER_HEADERS, "Idempotency-Key": key}, json=body)
    assert response.status_code == 200, response.text
    row = response.json()["jobs"][0]
    assert row["provider"] == "nemotron" and row["local_execution"]["device_id"] == device_id
    assert row["local_execution"]["device_name"] == "Synthetic PC"
    assert "provider_credential_id" not in row
    with maker() as db:
        import json
        saved = db.get(TranscriptionJob, row["id"])
        assert saved.local_device_id == device_id and saved.provider_credential_id is None
        assert json.loads(saved.options_json)["_stt_model"] == NEMOTRON_MODEL
    replay = client.post(f"/api/projects/{project_id}/jobs/batch", headers={**OWNER_HEADERS, "Idempotency-Key": key}, json=body)
    assert replay.status_code == 200 and replay.json()["replayed"]
    second_id, _ = prepare_pc(client)
    changed = client.post(f"/api/projects/{project_id}/jobs/batch", headers={**OWNER_HEADERS, "Idempotency-Key": key},
        json={**body, "local_device_id": second_id})
    assert changed.status_code == 409
    legacy = client.get(f"/api/projects/{project_id}/transcription-analytics").json()["configuration"]["provider_model"]
    expanded = client.get(f"/api/projects/{project_id}/transcription-analytics?include_local=true").json()["configuration"]["provider_model"]
    assert "nemotron_35_transcribe_local" not in legacy and legacy["unknown"] == 1
    assert expanded["nemotron_35_transcribe_local"] == 1 and expanded["unknown"] == 0


@pytest.mark.parametrize("invalid", ["no_device", "cloud_key", "other_owner", "offline", "detect", "dictionaries", "cloud_with_device"])
def test_local_batch_negative_admission_never_reaches_cloud_stt(local_app, monkeypatch, invalid):
    from studio_api import main
    from studio_api.models import LocalExecutionDevice, ProviderCredential, TranscriptionJob
    client, maker, settings, (owner_id, other_id) = local_app
    project_id, device_id, _, body = local_batch_fixture(client, maker, owner_id, monkeypatch)
    if invalid == "no_device": body.pop("local_device_id")
    elif invalid == "cloud_key": body["provider_credential_id"] = str(uuid4())
    elif invalid == "cloud_with_device": body["provider"] = "elevenlabs"
    elif invalid == "detect": body["language"] = "detect"
    elif invalid == "dictionaries": body["options"]["dictionary_ids"] = [str(uuid4())]
    else:
        with maker() as db:
            device = db.get(LocalExecutionDevice, device_id)
            if invalid == "other_owner": device.owner_user_id = other_id
            else: device.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=3)
            db.commit()
    reply = client.post(f"/api/projects/{project_id}/jobs/batch", headers={**OWNER_HEADERS, "Idempotency-Key": str(uuid4())}, json=body)
    assert reply.status_code in {404, 409, 422}, reply.text
    with maker() as db:
        assert db.scalar(select(TranscriptionJob)) is None and db.scalar(select(ProviderCredential)) is None
