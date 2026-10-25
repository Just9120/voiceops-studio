"""Synthetic OAuth/owner/resource boundaries: never contacts Yandex."""
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))
os.environ.setdefault("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")

from studio_api import models as m
from studio_api import yandex_disk_access as access
from studio_api import yandex_disk_connection as flows
from studio_api import yandex_disk_routes as routes
from studio_api.config import get_settings
from studio_api.db import Base, get_db
from studio_api.deps import current_session
from studio_api.security import token_hash
from studio_api.yandex_disk import YandexDiskError, resource_from_payload
from studio_api.yandex_disk_oauth import (
    SCOPES, YandexOAuthConfig, authorization_url, exchange_code,
    pkce_verifier, refresh_tokens, revoke_token, token_payload,
)

NOW = datetime(2026, 10, 25, 12)
KEY = base64.b64encode(b"s" * 32).decode()


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    original = httpx.Client.send
    def send(client, *args, **kwargs):
        assert not isinstance(client._transport, httpx.HTTPTransport), "real HTTP forbidden in synthetic tests"
        return original(client, *args, **kwargs)
    monkeypatch.setattr(httpx.Client, "send", send)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        # SQLite strips timezone info; this fixture uses a consistent UTC clock.
        monkeypatch.setattr(flows, "utcnow", lambda: NOW)
        monkeypatch.setattr(access, "utcnow", lambda: NOW)
        yield session
    engine.dispose()


@pytest.fixture
def config(tmp_path):
    secret = tmp_path / "synthetic-secret"
    secret.write_text("synthetic-client-secret", encoding="utf-8")
    return SimpleNamespace(
        app_origin="https://studio.example.test", cookie_name="session",
        yandex_disk_oauth_client_id="synthetic-client",
        yandex_disk_oauth_client_secret_file=str(secret),
        master_key_b64=lambda: KEY, credential_key_id="test-v1",
    )


def owner_session(db):
    user = m.User(email="disk-owner@example.test", status=m.UserStatus.active)
    db.add(user)
    db.flush()
    session = m.Session(user_id=user.id, token_hash=token_hash("browser"),
        csrf_hash=token_hash("csrf"), expires_at=NOW + timedelta(days=1),
        last_seen_at=NOW, created_at=NOW)
    db.add(session)
    db.commit()
    return user, session


def tokens():
    return token_payload({"access_token": "synthetic-access", "refresh_token": "synthetic-refresh",
                          "expires_in": 3600, "scope": SCOPES}, now=NOW)


def start(db, config, user, session):
    result = flows.start_connection(db, session=session, user=user, settings=config)
    query = parse_qs(urlsplit(result["authorization_url"]).query)
    return query["state"][0], result


def finish(db, config, state, **kwargs):
    return flows.finish_connection(db, state=state, code="synthetic-code", error=None,
        raw_session=kwargs.pop("raw_session", "browser"), settings=config,
        exchange=kwargs.pop("exchange", lambda *a, **kw: tokens()),
        client_factory=lambda token: SimpleNamespace(account_identity=lambda: "account-1"), **kwargs)


def connected(db, config):
    user, session = owner_session(db)
    state, _ = start(db, config, user, session)
    assert finish(db, config, state) == "connected"
    return user, session, db.get(m.YandexDiskConnection, user.id)


def test_oauth_pkce_scopes_secret_is_not_in_authorization_url():
    config = YandexOAuthConfig("client", "private-secret", "https://studio.example.test/api/yandex/oauth/callback")
    verifier = pkce_verifier("nonce", KEY)
    assert len(verifier) == 43
    assert verifier != pkce_verifier("other", KEY)
    query = parse_qs(urlsplit(authorization_url(config, state="nonce", verifier=verifier, device_id="device")).query)
    assert set(query["scope"][0].split()) == set(SCOPES.split())
    assert query["code_challenge_method"] == ["S256"]
    assert verifier not in str(query) and "private-secret" not in repr(config)
    assert "client_secret" not in query


def test_exchange_refresh_revoke_are_body_only_and_bounded():
    requests = []
    def handler(request):
        requests.append(request)
        assert "secret" not in str(request.url)
        if request.url.path == "/revoke_token":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json={"access_token": "synthetic-access",
            "refresh_token": "synthetic-refresh", "expires_in": 3600, "scope": SCOPES})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        cfg = YandexOAuthConfig("client", "secret", "https://studio.example.test/callback")
        assert exchange_code(cfg, code="code", verifier="verifier", now=NOW, client=client)["access_token"]
        assert refresh_tokens(cfg, refresh_token="refresh", now=NOW, client=client)["refresh_token"]
        assert revoke_token(cfg, access_token="access", client=client)
    forms = [parse_qs(r.content.decode()) for r in requests]
    assert forms[0]["code_verifier"] == ["verifier"]
    assert forms[1]["grant_type"] == ["refresh_token"]
    assert forms[2]["access_token"] == ["access"]


@pytest.mark.parametrize("patch", [
    {"expires_in": True}, {"expires_in": 0}, {"refresh_token": None},
    {"scope": "cloud_api:disk.info"}, {"access_token": "bad\nheader"},
])
def test_partial_or_malformed_credentials_are_rejected(patch):
    payload = {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600, "scope": SCOPES}
    payload.update(patch)
    with pytest.raises(YandexDiskError):
        token_payload(payload, now=NOW)


def test_huge_token_expiry_cannot_overflow_or_skip_quarterly_check():
    payload = token_payload({"access_token": "a", "refresh_token": "r", "expires_in": 2**63-1}, now=NOW)
    assert datetime.fromisoformat(payload["check_at"]) == NOW.replace(tzinfo=timezone.utc) + timedelta(days=90)


@pytest.mark.parametrize("raw_session", [None, "wrong-browser"])
def test_stolen_state_cannot_link_another_browser(db, config, raw_session):
    user, session = owner_session(db)
    state, _ = start(db, config, user, session)
    calls = []
    assert finish(db, config, state, raw_session=raw_session,
                  exchange=lambda *a, **kw: calls.append(kw)) == "invalid_state"
    assert calls == [] and db.get(m.YandexDiskConnection, user.id) is None


def test_success_is_encrypted_owner_bound_and_callback_is_one_use(db, config):
    user, session = owner_session(db)
    state, _ = start(db, config, user, session)
    assert finish(db, config, state) == "connected"
    row = db.get(m.YandexDiskConnection, user.id)
    assert row.account_uid == "account-1" and row.status == "active"
    assert b"synthetic" not in row.token_ciphertext
    assert access.access_token(db, user_id=user.id, settings=config, now=NOW) == "synthetic-access"
    calls = []
    assert finish(db, config, state, exchange=lambda *a, **kw: calls.append(kw)) == "invalid_state"
    assert calls == []


@pytest.mark.parametrize("interruption", ["logout", "disconnect", "new_start"])
def test_slow_exchange_cannot_undo_newer_owner_decision(db, config, interruption):
    user, session = owner_session(db)
    state, _ = start(db, config, user, session)
    def exchange(*args, **kwargs):
        if interruption == "logout":
            session.revoked_at = NOW
            db.commit()
        elif interruption == "disconnect":
            flows.disconnect_connection(db, owner_id=user.id, settings=config)
        else:
            start(db, config, user, session)
        return tokens()
    assert finish(db, config, state, exchange=exchange) == "invalid_state"
    assert db.get(m.YandexDiskConnection, user.id) is None


def test_google_purpose_cannot_be_consumed_as_disk_callback(db, config):
    user, session = owner_session(db)
    state, _ = start(db, config, user, session)
    row = db.scalar(select(m.GoogleOAuthState))
    row.purpose = "primary"
    db.commit()
    assert finish(db, config, state) == "invalid_state"
    assert row.used_at is None


def test_disconnect_clears_local_authority_when_provider_revoke_fails(db, config):
    user, _, connection = connected(db, config)
    def fail(*a, **kw):
        assert connection.token_ciphertext is None
        raise YandexDiskError("timeout")
    result = flows.disconnect_connection(db, owner_id=user.id, settings=config, revoker=fail)
    assert result == {"disconnected": True, "remote_revocation_attempted": True,
                      "remote_revocation_confirmed": False}
    assert connection.token_ciphertext is connection.token_nonce is None
    with pytest.raises(YandexDiskError, match="reauthorization_required"):
        access.access_token(db, user_id=user.id, settings=config)


def test_registered_resource_is_versioned_and_not_transferable(db, config):
    user, _, connection = connected(db, config)
    resource = resource_from_payload({"name": "input.flac", "path": "disk:/input.flac",
        "type": "file", "size": 4, "md5": "a" * 32, "modified": "2026-10-25T12:00:00Z"})
    row = access.register_resource(db, owner_user_id=user.id, resource=resource)
    assert access.register_resource(db, owner_user_id=user.id, resource=resource).id == row.id
    assert access.selected_resource(db, owner_user_id=user.id, resource_id=row.id).id == row.id
    other = m.User(email="other@example.test", status=m.UserStatus.active)
    db.add(other)
    db.flush()
    with pytest.raises(YandexDiskError):
        access.selected_resource(db, owner_user_id=other.id, resource_id=row.id)
    connection.account_uid = "different-account"
    with pytest.raises(YandexDiskError, match="resource_unavailable"):
        access.selected_resource(db, owner_user_id=user.id, resource_id=row.id)


def test_refresh_cannot_resurrect_disconnected_connection(db, config):
    user, _, row = connected(db, config)
    expired = tokens()
    expired["check_at"] = (NOW.replace(tzinfo=timezone.utc) - timedelta(seconds=1)).isoformat()
    access.store_tokens(row, payload=expired, settings=config)
    db.commit()
    def refresh(*a, **kw):
        flows.disconnect_connection(db, owner_id=user.id, settings=config, revoker=lambda *a, **kw: True)
        return tokens()
    with pytest.raises(YandexDiskError, match="connection_changed"):
        access.access_token(db, user_id=user.id, settings=config, now=NOW, refresher=refresh)
    assert db.get(m.YandexDiskConnection, user.id).token_ciphertext is None


def test_routes_keep_csrf_and_hide_tokens_with_empty_folder_selection(db, config, monkeypatch):
    user, session, _ = connected(db, config)
    app = FastAPI()
    app.include_router(routes.build_router(recent_auth=lambda pair, **kw: pair,
        limiter=SimpleNamespace(check=lambda *a: None)))
    app.dependency_overrides[current_session] = lambda: (session, user)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: config
    folder = resource_from_payload({"type": "dir", "name": "Empty", "path": "disk:/Empty"})
    monkeypatch.setattr(routes, "YandexDiskClient", lambda token: SimpleNamespace(
        children=lambda *a, **kw: (folder, (), None), metadata=lambda path: folder))
    with TestClient(app) as client:
        status = client.get("/api/yandex/connection")
        assert status.json() == {"configured": True, "connected": True, "status": "active"}
        assert status.headers["cache-control"] == "no-store"
        assert client.post("/api/yandex/resources/list", json={}).status_code == 403
        headers = {"origin": config.app_origin, "x-csrf-token": "csrf"}
        page = client.post("/api/yandex/resources/list", headers=headers,
                           json={"path": folder.path, "folders_only": True})
        assert page.status_code == 200 and page.json()["items"] == []
        selected = client.post("/api/yandex/resources/select", headers=headers, json={
            "path": folder.path, "is_folder": True, "fingerprint": page.json()["folder"]["fingerprint"]})
        assert selected.status_code == 200
        handle = selected.json()["id"]
        assert access.selected_resource(db, owner_user_id=user.id, resource_id=handle, is_folder=True)
        assert "synthetic-access" not in json.dumps(page.json())
        changed = client.post("/api/yandex/resources/select", headers=headers, json={
            "path": folder.path, "is_folder": True, "fingerprint": "0" * 64})
        assert changed.status_code == 409


def test_migration_is_single_additive_successor_and_refuses_data_loss(db):
    script = ScriptDirectory.from_config(Config(str(ROOT / "apps/studio-api/alembic.ini")))
    assert script.get_heads() == ["0043_yandex_disk"]
    revision = script.get_revision("0043_yandex_disk")
    assert revision.down_revision == "0042_totp_replay"
    assert revision.module.release_safety == "additive"
    with db.get_bind().begin() as connection:
        previous = revision.module.op
        revision.module.op = Operations(MigrationContext.configure(connection))
        try:
            revision.module.upgrade()  # Current metadata is accepted unchanged.
            connection.execute(m.User.__table__.insert().values(id="owner", email="owner@example.test"))
            connection.execute(m.YandexDiskConnection.__table__.insert().values(
                user_id="owner", account_uid="uid", key_id="test-v1"))
            with pytest.raises(RuntimeError, match="retired"):
                revision.module.downgrade()
        finally:
            revision.module.op = previous


def test_migration_widens_legacy_authority_and_empty_schema_roundtrips(db):
    from sqlalchemy import inspect
    script = ScriptDirectory.from_config(Config(str(ROOT / "apps/studio-api/alembic.ini")))
    revision = script.get_revision("0043_yandex_disk")
    with db.get_bind().begin() as connection:
        previous = revision.module.op
        revision.module.op = Operations(MigrationContext.configure(connection))
        try:
            revision.module.creation_authority_constraint(connection, include_yandex=False)
            for table in ["projects", "transcription_jobs"]:
                revision.module.op.drop_column(table, "output_provider")
            revision.module.op.drop_table("yandex_disk_resources")
            revision.module.op.drop_table("yandex_disk_connections")
            revision.module.upgrade()
            constraints = inspect(connection).get_check_constraints("sources")
            assert any(c["name"] == "ck_sources_creation_authority"
                       and "yandex_disk_created_time" in c["sqltext"] for c in constraints)
            revision.module.downgrade()
            assert "yandex_disk_connections" not in inspect(connection).get_table_names()
            assert "output_provider" not in {c["name"] for c in inspect(connection).get_columns("projects")}
            revision.module.upgrade()
            assert "yandex_disk_resources" in inspect(connection).get_table_names()
        finally:
            revision.module.op = previous


def test_intake_is_owner_checked_versioned_idempotent_and_uses_server_metadata(db, config, monkeypatch):
    from fastapi import HTTPException
    user, session, _ = connected(db, config)
    project = m.Project(owner_user_id=user.id, title="Disk sources")
    db.add(project)
    db.commit()
    resource = resource_from_payload({"type": "file", "path": "disk:/meeting.flac",
        "name": "meeting.flac", "size": 4, "mime_type": "audio/flac", "created": "2026-10-20T10:00:00Z"})
    handle = access.register_resource(db, owner_user_id=user.id, resource=resource).id
    db.commit()
    def loader(db, actor, project_id):
        row = db.get(m.Project, project_id)
        if row is None or row.owner_user_id != actor.id or row.archived_at:
            raise HTTPException(404)
        return row
    def verifier(db, **kwargs):
        access.selected_resource(db, owner_user_id=kwargs["owner_user_id"], resource_id=kwargs["resource_id"])
        return resource
    monkeypatch.setattr(routes, "verify_selected_resource", verifier)
    app = FastAPI()
    app.include_router(routes.build_router(recent_auth=lambda pair, **kw: pair,
        limiter=SimpleNamespace(check=lambda *a: None), project_loader=loader,
        source_serializer=lambda row: {"id": row.id, "source_type": row.source_type.value,
                                      "name": row.original_filename, "size": row.size_bytes}))
    app.dependency_overrides[current_session] = lambda: (session, user)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: config
    config.source_max_upload_bytes = 100
    with TestClient(app) as client:
        headers = {"origin": config.app_origin, "x-csrf-token": "csrf"}
        url = f"/api/projects/{project.id}/sources/yandex-disk"
        first = client.post(url, headers=headers, json={"resource_ids": [handle]})
        assert first.status_code == 200 and first.json()["sources"][0]["name"] == "meeting.flac"
        second = client.post(url, headers=headers, json={"resource_ids": [handle]})
        assert first.json() == second.json() and db.query(m.Source).count() == 1
        assert client.post(url, headers=headers, json={"resource_ids": [handle, handle]}).status_code == 422
        assert client.post("/api/projects/another-owner/sources/yandex-disk", headers=headers,
                           json={"resource_ids": [handle]}).status_code == 404
    row = db.scalar(select(m.Source))
    assert row.source_created_at_provenance == "yandex_disk_created_time"
    assert row.storage_cleanup_status == m.SourceStorageCleanupStatus.not_applicable
    assert row.s3_bucket is row.s3_object_key is None


@pytest.mark.parametrize("outcome", ["success", "changed", "cancelled", "budget"])
def test_audio_preparation_can_materialize_disk_without_copying_to_storage(db, config, tmp_path, monkeypatch, outcome):
    from studio_api import audio_result_rendering as rendering
    from studio_api import yandex_disk as transport
    from studio_api.audio_preparation_service import AudioPreparationServiceError
    user, _, _ = connected(db, config)
    project = m.Project(owner_user_id=user.id, title="Audio")
    db.add(project)
    db.flush()
    source = m.Source(project_id=project.id, source_type=m.SourceType.yandex_disk,
        original_filename="input.flac", mime_type="audio/flac", size_bytes=4,
        drive_file_id="handle", upload_status=m.SourceUploadStatus.uploaded)
    db.add(source)
    db.commit()
    job = SimpleNamespace(project_id=project.id, owner_user_id=user.id,
                          inputs=[SimpleNamespace(position=0, source=source)])
    resource = resource_from_payload({"type": "file", "path": "disk:/input.flac",
        "name": "input.flac", "size": 4, "mime_type": "audio/flac"})
    checks = []
    def verify(db, **kwargs):
        assert kwargs["owner_user_id"] == user.id and kwargs["resource_id"] == "handle"
        checks.append(1)
        if outcome == "changed" and len(checks) == 2:
            raise YandexDiskError("resource_changed")
        return resource
    def download(resource, target, *, maximum_bytes, check):
        assert not db.in_transaction()
        check()
        target.write(b"test")
        return 4
    monkeypatch.setattr(access, "verify_selected_resource", verify)
    monkeypatch.setattr(access, "access_token", lambda *a, **kw: "synthetic")
    monkeypatch.setattr(transport, "YandexDiskClient", lambda token: SimpleNamespace(download_to=download))
    config.source_max_upload_bytes = 100
    config.audio_preparation_max_input_bytes = 3 if outcome == "budget" else 100
    def check():
        if outcome == "cancelled" and checks:
            raise AudioPreparationServiceError(rendering.AudioPreparationServiceReason.cancellation_requested)
    kwargs = dict(job=job, root=tmp_path, settings=config, check=check,
                  drive_token_resolver=lambda *a, **kw: pytest.fail("must not use Google"),
                  drive_content_fetcher=lambda *a, **kw: pytest.fail("must not use Google"),
                  storage_factory=lambda *a: pytest.fail("external source must not use Studio storage"))
    if outcome == "success":
        paths = rendering.materialize_audio_inputs(db, **kwargs)
        assert len(paths) == 1 and paths[0].read_bytes() == b"test"
        assert db.query(m.Source).count() == 1 and source.s3_object_key is None
    else:
        with pytest.raises(AudioPreparationServiceError):
            rendering.materialize_audio_inputs(db, **kwargs)
        if outcome == "budget":
            assert checks == []
