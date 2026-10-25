"""Trusted-browser step-up boundary without production credentials or Google calls."""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))
os.environ.setdefault("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("STUDIO_APP_ORIGIN", "https://studio.test")
os.environ.setdefault("STUDIO_COOKIE_SECURE", "false")


@pytest.fixture
def trusted_app(monkeypatch):
    from studio_api.config import Settings, get_settings
    from studio_api.db import Base, get_db
    from studio_api import main
    from studio_api import deps
    from studio_api.models import LocalIdentity, Session, User, UserRole, UserStatus
    from studio_api.security import hash_password, token_hash, utcnow

    monkeypatch.setenv("STUDIO_APP_ORIGIN", "https://studio.test")
    monkeypatch.setenv("STUDIO_COOKIE_SECURE", "false")
    get_settings.cache_clear()
    settings = Settings(database_url="sqlite+pysqlite:///:memory:", app_origin="https://studio.test", cookie_secure=False)
    monkeypatch.setattr(main, "settings", settings)
    # SQLite drops timezone information; the production PostgreSQL path keeps it.
    naive_now = lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    monkeypatch.setattr(main, "utcnow", naive_now)
    monkeypatch.setattr(deps, "utcnow", naive_now)
    monkeypatch.setattr(main.limiter, "check", lambda *_args: None)
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)

    def db_override():
        with maker() as db:
            yield db

    main.app.dependency_overrides[get_db] = db_override
    with maker() as db:
        owner = User(email="owner@example.com", role=UserRole.admin, status=UserStatus.active)
        other = User(email="other@example.com", role=UserRole.user, status=UserStatus.active)
        db.add_all([owner, other]); db.flush()
        db.add(LocalIdentity(user_id=owner.id, password_hash=hash_password("correct password")))
        db.add(Session(
            user_id=owner.id, token_hash=token_hash("session-token"), csrf_hash=token_hash("csrf-token"),
            expires_at=utcnow() + timedelta(days=2),
            reauthenticated_at=utcnow() - timedelta(minutes=11),
        ))
        db.commit()
        owner_id, other_id = owner.id, other.id
    client = TestClient(main.app, base_url="https://studio.test")
    client.cookies.set(settings.cookie_name, "session-token")
    try:
        yield client, maker, main, owner_id, other_id
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        get_settings.cache_clear()
        engine.dispose()


def test_opt_in_cookie_bypasses_only_supported_step_up_and_can_be_revoked(trusted_app):
    from studio_api.models import Session, TrustedDevice
    from studio_api.security import utcnow
    from studio_api.trusted_device import COOKIE_NAME, TRUST_SECONDS

    client, maker, main, owner_id, other_id = trusted_app
    headers = {"origin": "https://studio.test", "x-csrf-token": "csrf-token"}
    stale = client.post("/api/auth/totp/enroll", headers=headers)
    assert stale.status_code == 409
    assert stale.json()["detail"]["reason"] == "recent_reauthentication_required"
    invalid = client.post(
        "/api/auth/reauth", json={"password": "wrong", "remember_device": True}, headers=headers,
    )
    assert invalid.status_code == 401
    assert COOKIE_NAME not in client.cookies

    confirmed = client.post(
        "/api/auth/reauth", json={"password": "correct password", "remember_device": True}, headers=headers,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["trusted_device_expires_at"] is not None
    assert COOKIE_NAME in client.cookies
    cookie = confirmed.headers["set-cookie"]
    assert "httponly" in cookie.lower() and "samesite=lax" in cookie.lower()
    assert f"Max-Age={TRUST_SECONDS}" in cookie
    assert client.cookies[COOKIE_NAME] not in confirmed.text
    with maker() as db:
        row = db.query(TrustedDevice).one()
        assert row.user_id == owner_id
        assert row.token_hash != client.cookies[COOKIE_NAME]
        session = db.query(Session).one()
        session.reauthenticated_at = utcnow() - timedelta(minutes=11)
        db.commit()
        assert main.require_recent_auth((session, db.get(main.User, owner_id)), request=client_request(client), db=db)
        with pytest.raises(HTTPException):
            main.require_recent_auth((session, db.get(main.User, other_id)), request=client_request(client), db=db)
        with pytest.raises(HTTPException):
            main.require_recent_auth((session, db.get(main.User, owner_id)))

    assert client.post("/api/auth/totp/enroll", headers=headers).status_code == 409

    status = client.get("/api/auth/security", headers={"origin": "https://studio.test"})
    assert status.status_code == 200
    assert status.json()["trusted_device_count"] == 1
    assert status.json()["trusted_device_expires_at"] is not None
    revoked = client.post(
        "/api/auth/trusted-device/revoke", json={"all_devices": False}, headers=headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["revoked_count"] == 1
    with maker() as db:
        session = db.query(Session).one()
        with pytest.raises(HTTPException):
            main.require_recent_auth((session, db.get(main.User, owner_id)), request=client_request(client), db=db)


def test_expiry_all_device_revoke_and_login_boundary(trusted_app):
    from studio_api.models import Session, TrustedDevice
    from studio_api.security import token_hash, utcnow
    from studio_api.trusted_device import COOKIE_NAME

    client, maker, main, owner_id, _ = trusted_app
    headers = {"origin": "https://studio.test", "x-csrf-token": "csrf-token"}
    for _ in range(2):
        response = client.post(
            "/api/auth/reauth", json={"password": "correct password", "remember_device": True}, headers=headers,
        )
        assert response.status_code == 200
    session_cookie = client.cookies[main.settings.cookie_name]
    client.cookies.pop(main.settings.cookie_name)
    assert client.get("/api/auth/security", headers={"origin": "https://studio.test"}).status_code == 401
    client.cookies.set(main.settings.cookie_name, session_cookie)
    assert client.post(
        "/api/auth/trusted-device/revoke", json={"all_devices": True},
        headers={"origin": "https://studio.test"},
    ).status_code == 403
    with maker() as db:
        session = db.query(Session).one()
        session.reauthenticated_at = utcnow() - timedelta(minutes=11)
        active = db.query(TrustedDevice).filter(TrustedDevice.revoked_at.is_(None)).one()
        active.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
        with pytest.raises(HTTPException):
            main.require_recent_auth((session, db.get(main.User, owner_id)), request=client_request(client), db=db)
        active.expires_at = utcnow() + timedelta(days=1)
        db.commit()
    all_revoked = client.post(
        "/api/auth/trusted-device/revoke", json={"all_devices": True}, headers=headers,
    )
    assert all_revoked.status_code == 200
    assert all_revoked.json()["revoked_count"] >= 1
    assert COOKIE_NAME not in client.cookies
    with maker() as db:
        assert db.query(TrustedDevice).filter(TrustedDevice.revoked_at.is_(None)).count() == 0
        assert db.query(Session).filter_by(token_hash=token_hash("session-token")).count() == 1


def test_opt_in_requires_second_factor_when_enabled(trusted_app, monkeypatch):
    from studio_api.trusted_device import COOKIE_NAME

    client, maker, main, _, _ = trusted_app
    monkeypatch.setattr(main, "_active_totp_factor", lambda *_args: object())
    monkeypatch.setattr(main, "_verify_second_factor", lambda *_args, **_kwargs: False)
    response = client.post(
        "/api/auth/reauth",
        json={"password": "correct password", "remember_device": True},
        headers={"origin": "https://studio.test", "x-csrf-token": "csrf-token"},
    )
    assert response.status_code == 401
    assert COOKIE_NAME not in client.cookies


def test_password_reset_revokes_all_remembered_browsers(trusted_app):
    from studio_api.models import PasswordResetChallenge, TrustedDevice
    from studio_api.security import token_hash

    client, maker, main, owner_id, _ = trusted_app
    headers = {"origin": "https://studio.test", "x-csrf-token": "csrf-token"}
    assert client.post(
        "/api/auth/reauth",
        json={"password": "correct password", "remember_device": True}, headers=headers,
    ).status_code == 200
    with maker() as db:
        db.add(PasswordResetChallenge(
            user_id=owner_id, token_hash=token_hash("reset-token-" + "x" * 32),
            request_fingerprint="f" * 64, created_at=main.utcnow(),
            expires_at=main.utcnow() + timedelta(minutes=10),
        ))
        db.commit()
    result = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": "reset-token-" + "x" * 32, "new_password": "new strong password"},
        headers={"origin": "https://studio.test"},
    )
    assert result.status_code == 200
    with maker() as db:
        assert db.query(TrustedDevice).filter(TrustedDevice.revoked_at.is_(None)).count() == 0
    assert client.get("/api/auth/security", headers={"origin": "https://studio.test"}).status_code == 401


def test_disabling_second_factor_revokes_remembered_browsers(trusted_app, monkeypatch):
    from studio_api.models import TrustedDevice, UserTotpFactor
    from studio_api.trusted_device import COOKIE_NAME

    client, maker, main, owner_id, _ = trusted_app
    headers = {"origin": "https://studio.test", "x-csrf-token": "csrf-token"}
    assert client.post(
        "/api/auth/reauth",
        json={"password": "correct password", "remember_device": True}, headers=headers,
    ).status_code == 200
    with maker() as db:
        db.add(UserTotpFactor(
            user_id=owner_id, secret_ciphertext=b"synthetic", secret_nonce=b"synthetic",
            key_id="synthetic", confirmed_at=main.utcnow(), created_at=main.utcnow(),
            updated_at=main.utcnow(),
        ))
        db.commit()
    monkeypatch.setattr(main, "_verify_second_factor", lambda *_args, **_kwargs: True)
    result = client.request("DELETE", "/api/auth/totp", json={"verification_code": "123456"}, headers=headers)
    assert result.status_code == 200
    assert COOKIE_NAME not in client.cookies
    with maker() as db:
        assert db.query(TrustedDevice).filter(TrustedDevice.revoked_at.is_(None)).count() == 0


def client_request(client):
    from starlette.requests import Request
    cookie_header = "; ".join(f"{key}={value}" for key, value in client.cookies.items())
    return Request({"type": "http", "headers": [(b"cookie", cookie_header.encode())]})


def test_trusted_device_migration_is_additive_and_repeat_safe(monkeypatch):
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect, text

    script = ScriptDirectory.from_config(Config(str(ROOT / "apps/studio-api/alembic.ini")))
    assert script.get_heads() == ["0043_yandex_disk"]
    migration = script.get_revision("0038_trusted_devices")
    assert migration.down_revision == "0037_ux_audit_controls"
    assert migration.module.release_safety == "additive"
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)"))
        monkeypatch.setattr(migration.module, "op", Operations(MigrationContext.configure(conn)))
        migration.module.upgrade()
        migration.module.upgrade()
        assert "trusted_devices" in inspect(conn).get_table_names()
        assert {"id", "user_id", "token_hash", "created_at", "expires_at", "revoked_at"} == {
            column["name"] for column in inspect(conn).get_columns("trusted_devices")
        }
        migration.module.downgrade()
        assert "trusted_devices" not in inspect(conn).get_table_names()
    engine.dispose()


def test_host_prefixed_cookie_deletion_preserves_secure_attribute():
    from fastapi import Response
    from studio_api.config import Settings
    from studio_api.trusted_device import clear_trusted_device_cookie

    response = Response()
    clear_trusted_device_cookie(response, settings=Settings(cookie_secure=True))
    cookie = response.headers["set-cookie"].lower()
    assert "__host-studio_trusted_device=" in cookie
    assert "secure" in cookie and "httponly" in cookie and "path=/" in cookie
