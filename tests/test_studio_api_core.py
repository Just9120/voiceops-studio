import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))
os.environ.setdefault("STUDIO_DATABASE_SCHEME", "postgresql+psycopg")
os.environ.setdefault("STUDIO_DATABASE_HOST", "127.0.0.1")
os.environ.setdefault("STUDIO_DATABASE_PORT", "5432")
os.environ.setdefault("STUDIO_DATABASE_NAME", "studio_test")
os.environ.setdefault("STUDIO_DATABASE_USER", "studio_test")
os.environ.setdefault("STUDIO_POSTGRES_PASSWORD_FILE", str(Path(tempfile.gettempdir()) / "studio_test_pg_password"))
os.environ.setdefault("STUDIO_REDIS_URL", "redis://127.0.0.1:6379/0")
os.environ.setdefault("STUDIO_APP_ORIGIN", "https://studio.test")
os.environ.setdefault("STUDIO_COOKIE_SECURE", "false")
os.environ.setdefault("STUDIO_CREDENTIAL_MASTER_KEY_FILE", str(Path(tempfile.gettempdir()) / "studio_test_master_key"))
Path(os.environ["STUDIO_POSTGRES_PASSWORD_FILE"]).write_text(os.environ.get("STUDIO_TEST_POSTGRES_PASSWORD", "studio_test_password"), encoding="utf-8")
Path(os.environ["STUDIO_CREDENTIAL_MASTER_KEY_FILE"]).write_text(base64.b64encode(b"1" * 32).decode(), encoding="utf-8")

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError, ProgrammingError
from studio_api.config import Settings
from studio_api.account_security import RECOVERY_CODE_COUNT, _totp, recovery_code_hash
from studio_api.db import SessionLocal, engine
from studio_api.main import app, limiter
from studio_api.models import AuditEvent, DiagnosticDebugSession, DiagnosticEvent, OutputFolderFavorite, RealtimeTranscriptDraft, Session as DbSession, SttProviderHealth, TranscriptionOutputReconciliation, TranscriptionJobSourceAttempt, OutputReconciliationStatus, SourceAttemptRetryDisposition, SourceAttemptStage, CredentialProvider, CredentialStatus, JobSourceStatus, JobStatus, LocalIdentity, Project, ProviderCredential, ProviderCredentialVersion, Source, SourceStorageCleanupStatus, SourceType, SourceUploadStatus, TranscriptionJob, TranscriptionJobOutput, TranscriptionJobSource, User, UserRole, UserStatus, UserTotpFactor, UserTotpRecoveryCode
from studio_api.security import aad, decrypt, encrypt, hash_password, master_key_from_b64, utcnow, verify_password
from studio_api.totp_break_glass import TotpBreakGlassError, disable_owner_totp
from studio_api.job_claim_lease import JobLeaseError, JobLeaseFailureReason, acquire_job_lease, acquire_next_ready_job_lease, invalidate_job_lease, is_lease_active, release_job_lease, renew_job_lease
from studio_api.job_processing_lifecycle import JobProcessingError, JobProcessingFailureReason, acknowledge_job_cancellation, begin_job_processing, fail_job_processing, recover_expired_processing_job
from studio_api.google_docs_output import GoogleDocsCreateResult, new_google_docs_transcript_artifact
from studio_api.job_output_persistence import JobOutputPersistenceError, JobOutputPersistenceReason, _load_locked_output_authority, persist_processing_job_source_output_and_maybe_complete
from studio_api.realtime_capability import RealtimeCapability, RealtimeCapabilityError, RealtimeCapabilityReason
from studio_api.realtime_drafts import RealtimeDraftContent

ALEMBIC = ROOT / "apps/studio-api/alembic.ini"

@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    env = os.environ.copy()
    env.pop("STUDIO_DATABASE_URL", None)
    subprocess.run([sys.executable, "-m", "alembic", "-c", str(ALEMBIC), "upgrade", "head"], cwd=ROOT, env=env, check=True)
    yield

@pytest.fixture(autouse=True)
def clean_state(migrated_database):
    try:
        limiter.redis.flushdb()
    except Exception as exc:
        pytest.skip(f"Redis unavailable for platform tests: {exc}")
    with engine.begin() as conn:
        tables = ["runtime_component_status", "security_email_deliveries", "job_notification_deliveries", "web_push_subscriptions", "user_notification_preferences", "operational_alert_deliveries", "operational_incidents", "audio_preparation_job_inputs", "audio_preparation_jobs", "realtime_transcript_drafts", "transcript_catalog_entries", "stt_provider_operations", "stt_provider_health", "stt_dictionary_entries", "stt_dictionaries", "transcription_job_source_attempts", "transcription_output_reconciliations", "diagnostic_debug_sessions", "diagnostic_events", "audit_events", "google_oauth_states", "google_connections", "provider_account_snapshots", "provider_credential_versions", "provider_credentials", "transcription_job_outputs", "transcription_job_sources", "transcription_jobs", "sources", "output_folder_favorites", "projects", "password_reset_challenges", "user_totp_recovery_codes", "user_totp_factors", "trusted_devices", "sessions", "login_contexts", "local_identities", "users"]
        required_tables = set(tables)
        missing = required_tables - set(inspect(conn).get_table_names())
        assert not missing, f"shared test database schema is not at current head: {sorted(missing)}"
        conn.execute(text("TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE"))
    yield


@contextmanager
def isolated_migration_database(prefix: str):
    temp_db = f"{prefix}_{uuid.uuid4().hex}"
    base_url = make_url(engine.url)
    admin_url = base_url.set(database="postgres")
    temp_url = base_url.set(database=temp_db)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{temp_db}"'))
    except OperationalError as exc:
        admin_engine.dispose()
        pytest.skip(f"PostgreSQL database creation unavailable for isolated migration test: {exc}")
    finally:
        admin_engine.dispose()

    env = os.environ.copy()
    env.pop("STUDIO_DATABASE_URL", None)
    env["STUDIO_DATABASE_NAME"] = temp_db
    temp_engine = create_engine(temp_url)
    try:
        yield temp_engine, env
    finally:
        temp_engine.dispose()
        cleanup_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            with cleanup_engine.connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{temp_db}" WITH (FORCE)'))
        finally:
            cleanup_engine.dispose()


def run_alembic(target: str, *, env: dict[str, str], command: str = "upgrade") -> None:
    subprocess.run([sys.executable, "-m", "alembic", "-c", str(ALEMBIC), command, target], cwd=ROOT, env=env, check=True)


def test_database_role_manifest_lets_real_migrator_extend_existing_enum(tmp_path):
    with isolated_migration_database("studio_enum_owner") as (temp_engine, env):
        run_alembic("0035_job_notifications", env=env)
        temp_db = str(temp_engine.url.database)
        role_sql = (ROOT / "deploy/studio/database-roles.sql").read_text(encoding="utf-8")
        role_sql = role_sql.replace(
            "GRANT CONNECT ON DATABASE studio TO studio_api, studio_migrator",
            f'GRANT CONNECT ON DATABASE "{temp_db}" TO studio_api, studio_migrator',
        )
        raw_connection = temp_engine.raw_connection()
        try:
            with raw_connection.cursor() as cursor:
                cursor.execute(role_sql, prepare=False)
            raw_connection.commit()
        finally:
            raw_connection.close()

        with temp_engine.connect() as conn:
            assert conn.execute(
                text(
                    "SELECT pg_get_userbyid(t.typowner) "
                    "FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace "
                    "WHERE n.nspname='public' AND t.typname='credentialprovider'"
                )
            ).scalar_one() == "studio_owner"

        password = uuid.uuid4().hex + uuid.uuid4().hex
        assert re.fullmatch(r"[0-9a-f]{64}", password)
        password_file = tmp_path / "studio_migrator_password"
        password_file.write_text(password, encoding="utf-8")
        with temp_engine.begin() as conn:
            conn.exec_driver_sql(
                f"ALTER ROLE studio_migrator WITH LOGIN PASSWORD '{password}'"
            )

        migrator_url = make_url(temp_engine.url).set(
            username="studio_migrator",
            password=password,
        )
        migrator_engine = create_engine(migrator_url)
        try:
            with migrator_engine.connect() as conn:
                assert conn.execute(text("SELECT current_user")).scalar_one() == "studio_owner"
            migrator_env = env.copy()
            migrator_env["STUDIO_DATABASE_USER"] = "studio_migrator"
            migrator_env["STUDIO_POSTGRES_PASSWORD_FILE"] = str(password_file)
            run_alembic("head", env=migrator_env)
        finally:
            migrator_engine.dispose()
            with temp_engine.begin() as conn:
                conn.execute(text("ALTER ROLE studio_migrator NOLOGIN"))

        with temp_engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0043_yandex_disk"
            assert conn.execute(
                text(
                    "SELECT count(*) FROM pg_enum e "
                    "JOIN pg_type t ON t.oid=e.enumtypid "
                    "WHERE t.typname='credentialprovider' AND e.enumlabel='yandex'"
                )
            ).scalar_one() == 1


def admin(email="a@example.com", password="correct horse battery"):
    db = SessionLocal()
    u = User(email=email, role=UserRole.admin, status=UserStatus.active)
    db.add(u); db.flush(); db.add(LocalIdentity(user_id=u.id, password_hash=hash_password(password))); db.commit(); db.close()
    return password


def login(c, password, email="a@example.com"):
    r = c.post("/api/auth/login-context", headers={"origin": "https://studio.test"}); assert r.status_code == 200
    token = r.json()["login_csrf_token"]
    r = c.post("/api/auth/login", json={"email": email, "password": password, "login_csrf_token": token}, headers={"origin": "https://studio.test"}); assert r.status_code == 200
    return r.json()["csrf_token"]


def test_password_hashing_argon2id():
    h = hash_password("secret-password-123")
    assert "argon2id" in h
    assert verify_password(h, "secret-password-123")
    assert not verify_password(h, "bad")


def test_operator_totp_break_glass_disables_factor_revokes_sessions_and_audits():
    admin(email="owner@example.com")
    db = SessionLocal()
    user = db.query(User).filter_by(email="owner@example.com").one()
    factor = UserTotpFactor(
        user_id=user.id,
        secret_ciphertext=b"encrypted-secret-is-never-read",
        secret_nonce=b"nonce-is-never-read",
        key_id="test-key",
        confirmed_at=utcnow(),
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session = DbSession(
        user_id=user.id,
        token_hash="a" * 64,
        csrf_hash="b" * 64,
        expires_at=utcnow() + timedelta(days=1),
    )
    recovery = UserTotpRecoveryCode(
        user_id=user.id,
        code_hash="c" * 64,
        created_at=utcnow(),
    )
    db.add_all([factor, session, recovery])
    db.commit()

    result = disable_owner_totp(
        db,
        owner_email=" OWNER@example.com ",
        reason="lost-authenticator",
        now=utcnow(),
    )
    db.expire_all()

    assert result.revoked_sessions == 1
    assert db.get(UserTotpFactor, user.id).disabled_at is not None
    assert db.get(DbSession, session.id).revoked_at is not None
    assert db.query(UserTotpRecoveryCode).filter_by(user_id=user.id, used_at=None).count() == 0
    event = db.query(AuditEvent).filter_by(
        event_type="auth.totp_break_glass_disabled",
        subject_user_id=user.id,
    ).one()
    assert event.actor_user_id is None
    assert json.loads(event.metadata_json) == {"reason": "lost-authenticator"}
    db.close()


def test_operator_totp_break_glass_fails_closed_for_unknown_owner():
    admin(email="owner@example.com")
    db = SessionLocal()
    with pytest.raises(TotpBreakGlassError, match="eligible owner not found"):
        disable_owner_totp(
            db,
            owner_email="unknown@example.com",
            reason="recovery-codes-unavailable",
        )
    assert db.query(AuditEvent).filter_by(
        event_type="auth.totp_break_glass_disabled",
    ).count() == 0
    db.close()


def test_optional_totp_enrollment_login_recovery_and_disable_lifecycle(monkeypatch):
    clock = [int(time.time()) // 30 * 30 + 5]
    monkeypatch.setattr("studio_api.account_security.time.time", lambda: clock[0])
    password = admin(email="owner@example.com")
    owner = TestClient(app)
    csrf = login(owner, password, email="owner@example.com")

    enrolled = owner.post(
        "/api/auth/totp/enroll",
        headers={"origin": "https://studio.test", "x-csrf-token": csrf},
    )
    assert enrolled.status_code == 200
    assert enrolled.headers["cache-control"] == "no-store"
    material = enrolled.json()
    assert material["otpauth_uri"].startswith("otpauth://totp/")
    assert material["qr_svg_data_uri"].startswith("data:image/svg+xml;base64,")
    code = _totp(material["secret"], int(time.time()) // 30)

    confirmed = owner.post(
        "/api/auth/totp/confirm",
        json={"verification_code": code},
        headers={"origin": "https://studio.test", "x-csrf-token": csrf},
    )
    assert confirmed.status_code == 200
    recovery_codes = confirmed.json()["recovery_codes"]
    assert len(recovery_codes) == RECOVERY_CODE_COUNT

    db = SessionLocal()
    user = db.query(User).filter_by(email="owner@example.com").one()
    factor = db.get(UserTotpFactor, user.id)
    assert factor.confirmed_at is not None
    hashes = {
        row.code_hash
        for row in db.query(UserTotpRecoveryCode).filter_by(user_id=user.id).all()
    }
    assert hashes == {recovery_code_hash(value) for value in recovery_codes}
    assert all(value not in hashes for value in recovery_codes)
    db.close()

    without_factor = TestClient(app)
    login_context = without_factor.post(
        "/api/auth/login-context",
        headers={"origin": "https://studio.test"},
    ).json()["login_csrf_token"]
    rejected = without_factor.post(
        "/api/auth/login",
        json={
            "email": "owner@example.com",
            "password": password,
            "login_csrf_token": login_context,
        },
        headers={"origin": "https://studio.test"},
    )
    assert rejected.status_code == 409
    assert rejected.json() == {"detail": {"reason": "second_factor_required"}}

    with_factor = TestClient(app)
    login_context = with_factor.post(
        "/api/auth/login-context",
        headers={"origin": "https://studio.test"},
    ).json()["login_csrf_token"]
    replayed = with_factor.post("/api/auth/login", json={"email": "owner@example.com", "password": password,
        "login_csrf_token": login_context, "verification_code": code}, headers={"origin": "https://studio.test"})
    assert replayed.status_code == 401
    clock[0] += 30
    code = _totp(material["secret"], int(time.time()) // 30)
    accepted = with_factor.post(
        "/api/auth/login",
        json={
            "email": "owner@example.com",
            "password": password,
            "login_csrf_token": login_context,
            "verification_code": code,
        },
        headers={"origin": "https://studio.test"},
    )
    assert accepted.status_code == 200

    with_recovery = TestClient(app)
    login_context = with_recovery.post(
        "/api/auth/login-context",
        headers={"origin": "https://studio.test"},
    ).json()["login_csrf_token"]
    recovered = with_recovery.post(
        "/api/auth/login",
        json={
            "email": "owner@example.com",
            "password": password,
            "login_csrf_token": login_context,
            "recovery_code": recovery_codes[0],
        },
        headers={"origin": "https://studio.test"},
    )
    assert recovered.status_code == 200
    db = SessionLocal()
    assert db.query(UserTotpRecoveryCode).filter_by(
        user_id=user.id,
        code_hash=recovery_code_hash(recovery_codes[0]),
    ).one().used_at is not None
    assert db.query(AuditEvent).filter_by(
        event_type="auth.totp_recovery_consumed",
        actor_user_id=user.id,
        subject_user_id=user.id,
    ).count() == 1
    db.close()

    owner_headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    assert owner.post("/api/auth/reauth", json={"password": password, "verification_code": code}, headers=owner_headers).status_code == 401
    clock[0] += 30
    code = _totp(material["secret"], int(time.time()) // 30)
    assert owner.post("/api/auth/reauth", json={"password": password, "verification_code": code}, headers=owner_headers).status_code == 200
    assert owner.request("DELETE", "/api/auth/totp", json={"verification_code": code}, headers=owner_headers).status_code == 422
    clock[0] += 30
    code = _totp(material["secret"], int(time.time()) // 30)
    disabled = owner.request(
        "DELETE",
        "/api/auth/totp",
        json={"verification_code": code},
        headers={"origin": "https://studio.test", "x-csrf-token": csrf},
    )
    assert disabled.status_code == 200
    assert disabled.json() == {"enabled": False}


def test_recent_auth_and_totp_verification_limits_are_independent():
    password = admin(email="owner@example.com")
    client = TestClient(app)
    csrf = login(client, password, email="owner@example.com")
    db = SessionLocal()
    user = db.query(User).filter_by(email="owner@example.com").one()
    current = db.query(DbSession).filter_by(user_id=user.id, revoked_at=None).one()
    current.reauthenticated_at = utcnow() - timedelta(hours=1)
    db.commit()
    db.close()

    stale = client.post(
        "/api/auth/totp/enroll",
        headers={"origin": "https://studio.test", "x-csrf-token": csrf},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["reason"] == "recent_reauthentication_required"
    assert stale.headers["cache-control"] == "no-store"

    refreshed = client.post(
        "/api/auth/reauth",
        json={"password": password},
        headers={"origin": "https://studio.test", "x-csrf-token": csrf},
    )
    assert refreshed.status_code == 200
    enrolled = client.post(
        "/api/auth/totp/enroll",
        headers={"origin": "https://studio.test", "x-csrf-token": csrf},
    )
    assert enrolled.status_code == 200

    for _ in range(5):
        invalid = client.post(
            "/api/auth/totp/confirm",
            json={"verification_code": "000000"},
            headers={"origin": "https://studio.test", "x-csrf-token": csrf},
        )
        assert invalid.status_code == 422
    limited = client.post(
        "/api/auth/totp/confirm",
        json={"verification_code": "000000"},
        headers={"origin": "https://studio.test", "x-csrf-token": csrf},
    )
    assert limited.status_code == 429

    password_reset = client.post(
        "/api/auth/password-reset/request",
        json={"email": "owner@example.com"},
        headers={"origin": "https://studio.test"},
    )
    assert password_reset.status_code == 200
    assert password_reset.json() == {"accepted": True, "delivery": "not_configured"}


def test_password_reset_request_is_uniform_for_known_and_unknown_accounts():
    admin(email="owner@example.com")
    client = TestClient(app)
    known = client.post(
        "/api/auth/password-reset/request",
        json={"email": "owner@example.com"},
        headers={"origin": "https://studio.test"},
    )
    unknown = client.post(
        "/api/auth/password-reset/request",
        json={"email": "unknown@example.com"},
        headers={"origin": "https://studio.test"},
    )
    assert known.status_code == unknown.status_code == 200
    assert known.headers["cache-control"] == unknown.headers["cache-control"] == "no-store"
    assert known.json() == unknown.json() == {
        "accepted": True,
        "delivery": "not_configured",
    }


def test_configured_password_reset_is_uniform_single_use_and_revokes_sessions(monkeypatch):
    from studio_api import main
    from studio_api.models import PasswordResetChallenge, SecurityEmailDelivery
    from studio_api.security_email import _aad
    monkeypatch.setattr(main.settings, "security_email_enabled", True)
    monkeypatch.setattr(main.settings, "security_email_sender_domain", "example.com")
    monkeypatch.setattr(main.settings, "job_smtp_host", "smtp.example.com")
    monkeypatch.setattr(main.settings, "job_smtp_from_email", "security@example.com")
    monkeypatch.setattr(main.settings, "job_smtp_starttls", True)
    monkeypatch.setattr(main.settings, "job_smtp_use_ssl", False)
    monkeypatch.setattr(main.settings, "job_smtp_username", None)
    pw = admin(email="reset-owner@example.com")
    owner = TestClient(app); login(owner, pw, "reset-owner@example.com")
    anonymous = TestClient(app)
    headers = {"origin": "https://studio.test"}
    known = anonymous.post("/api/auth/password-reset/request", json={"email": "reset-owner@example.com"}, headers=headers)
    unknown = anonymous.post("/api/auth/password-reset/request", json={"email": "missing@example.com"}, headers=headers)
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json() == {"accepted": True, "delivery": "configured"}
    assert known.headers["cache-control"] == unknown.headers["cache-control"] == "no-store"
    with SessionLocal() as db:
        row = db.scalar(select(SecurityEmailDelivery).where(SecurityEmailDelivery.kind == "password_reset"))
        payload = json.loads(decrypt(row.payload_ciphertext, row.payload_nonce, master_key_from_b64(main.settings.master_key_b64()), _aad(row.owner_user_id, row.id)))
        token = re.search(r"#password-reset=([A-Za-z0-9_-]+)", payload["body"]).group(1)
        assert token not in known.text and db.query(PasswordResetChallenge).count() == 1
    body = {"token": token, "new_password": "Synthetic-new-password-123"}
    assert anonymous.post("/api/auth/password-reset/confirm", json=body, headers=headers).status_code == 200
    assert anonymous.post("/api/auth/password-reset/confirm", json=body, headers=headers).status_code == 422
    assert owner.get("/api/auth/security").status_code == 401
    with SessionLocal() as db:
        assert db.query(SecurityEmailDelivery).filter_by(kind="auth.password_reset_completed").count() == 1


def test_alembic_upgrade_and_readiness_current():
    c = TestClient(app)
    r = c.get("/api/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "database": "reachable", "migrations": "current", "schema_revision": "0043_yandex_disk", "redis": "reachable"}
    assert c.get("/api/readyz").json() == r.json()
    assert c.get("/api/livez").json() == {"ok": True, "status": "alive"}


def test_retention_context_mail_migrations_round_trip_preserve_existing_expiry():
    with isolated_migration_database("studio_context_mail_roundtrip") as (target, env):
        run_alembic("0040_text_lifecycle", env=env)
        # Bootstrap metadata includes current nullable columns. Downgrade removes
        # them to reproduce the released schema before the real upgrade.
        run_alembic("0040_text_lifecycle", env=env, command="downgrade")
        with target.begin() as db:
            db.execute(text("ALTER TABLE sources DROP COLUMN IF EXISTS prepared_audio_context_json"))
            db.execute(text("ALTER TABLE transcription_job_source_attempts DROP COLUMN IF EXISTS provider_media_plan_json"))
            db.execute(text("DROP TABLE IF EXISTS security_email_deliveries"))
            db.execute(text("INSERT INTO users(id,email,role,status,created_at,updated_at,source_retention_ttl_seconds) VALUES ('synthetic-user','roundtrip@example.test','user','active',now(),now(),86400)"))
            db.execute(text("INSERT INTO projects(id,owner_user_id,title,created_at,updated_at) VALUES ('synthetic-project','synthetic-user','Roundtrip',now(),now())"))
            db.execute(text("INSERT INTO sources(id,project_id,source_type,original_filename,upload_status,size_bytes,expires_at,created_at,updated_at) VALUES ('synthetic-source','synthetic-project','local_upload','synthetic.wav','uploaded',42,'2026-10-12 10:00:00+00',now(),now())"))
            before = db.execute(text("SELECT expires_at FROM sources WHERE id='synthetic-source'" )).scalar_one()
        try:
            run_alembic("head", env=env)
            assert {"prepared_audio_context_json"} <= {c["name"] for c in inspect(target).get_columns("sources")}
            assert "security_email_deliveries" in inspect(target).get_table_names()
            with target.connect() as db:
                assert db.execute(text("SELECT expires_at FROM sources WHERE id='synthetic-source'")).scalar_one() == before
                assert db.execute(text("SELECT source_retention_ttl_seconds FROM users WHERE id='synthetic-user'")).scalar_one() == 86400
            run_alembic("0040_text_lifecycle", env=env, command="downgrade")
            assert "security_email_deliveries" not in inspect(target).get_table_names()
            assert "prepared_audio_context_json" not in {c["name"] for c in inspect(target).get_columns("sources")}
            with target.connect() as db:
                assert db.execute(text("SELECT expires_at FROM sources WHERE id='synthetic-source'")).scalar_one() == before
        finally:
            run_alembic("head", env=env)


def test_audit_rows_are_database_enforced_append_only():
    db = SessionLocal()
    row = AuditEvent(
        event_type="test.append_only",
        outcome="success",
        metadata_json="{}",
    )
    db.add(row)
    db.commit()
    row_id = row.id
    db.close()

    statements = (
        text("UPDATE audit_events SET outcome='failed' WHERE id=:row_id"),
        text("DELETE FROM audit_events WHERE id=:row_id"),
    )
    for statement in statements:
        with engine.connect() as conn:
            transaction = conn.begin()
            with pytest.raises(DBAPIError) as caught:
                conn.execute(statement, {"row_id": row_id})
            assert getattr(caught.value.orig, "sqlstate", None) == "55000"
            transaction.rollback()

    db = SessionLocal()
    preserved = db.get(AuditEvent, row_id)
    assert preserved is not None and preserved.outcome == "success"
    db.close()


def test_worker_role_operator_predicate_on_real_postgresql():
    script = (ROOT / "scripts/configure_studio_worker_db_role.sh").read_text(encoding="utf-8")
    match = re.search(r'result="\$\(psql_admin -Atqc "([^"]+)"\)', script)
    assert match is not None
    query = match.group(1).replace("${ROLE_NAME}", "studio_worker")
    attributes = (
        "rolcanlogin", "rolsuper", "rolcreatedb", "rolcreaterole",
        "rolreplication", "rolbypassrls", "rolinherit",
    )
    expected = [True, False, False, False, False, False, False]
    cases = [("studio_worker", expected, True), ("other_role", expected, False)]
    for index in range(len(attributes)):
        toggled = expected.copy()
        toggled[index] = not toggled[index]
        cases.append(("studio_worker", toggled, False))
        nullable = expected.copy()
        nullable[index] = None
        cases.append(("studio_worker", nullable, False))
    with engine.connect() as conn:
        # This reproduces the original concat_ws formatting mistake against
        # PostgreSQL itself, not a Python/bool mock or an explicit text cast.
        assert conn.execute(text("SELECT concat_ws(':', TRUE, FALSE)")).scalar_one() == "t:f"
        for name, values, accepted in cases:
            expressions = ", ".join(
                "NULL::boolean" if value is None else "TRUE" if value else "FALSE"
                for value in values
            )
            cte = f"WITH pg_roles(rolname, {', '.join(attributes)}) AS (VALUES ('{name}', {expressions})) "
            assert conn.execute(text(cte + query)).scalar_one() is accepted, (name, values)
        # An absent role must return false, never an empty/implicitly accepted row.
        cte = "WITH pg_roles AS (SELECT * FROM pg_catalog.pg_roles WHERE FALSE) "
        assert conn.execute(text(cte + query)).scalar_one() is False


def test_worker_manifest_supports_readiness_with_restricted_postgresql_login(monkeypatch):
    from studio_api import worker_health
    from studio_api.elevenlabs_transcription import normalize_elevenlabs_transcript_response
    from studio_api.provider_part_checkpoints import save_provider_part_checkpoint
    from studio_api.runtime_observability import check_database_readiness, repository_schema_head
    from sqlalchemy.orm import Session

    role_name = f"studio_worker_test_{uuid.uuid4().hex}"
    password = f"synthetic-{uuid.uuid4().hex}"
    monkeypatch.setattr(worker_health, "EXPECTED_DATABASE_ROLE", role_name)
    worker_engine = None
    try:
        with isolated_migration_database("studio_worker_grants") as (temp_engine, env):
            run_alembic("head", env=env)
            # Execute the production manifest unchanged except for the two
            # isolated test identifiers; never mutate the real studio_worker.
            manifest = (ROOT / "deploy/studio/worker-db-role.sql").read_text(encoding="utf-8")
            manifest = re.sub(r"\bstudio_worker\b", role_name, manifest)
            manifest = manifest.replace("ON DATABASE studio TO", f'ON DATABASE "{temp_engine.url.database}" TO')
            with temp_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.exec_driver_sql(manifest, execution_options={"no_parameters": True})
                conn.exec_driver_sql(f"ALTER ROLE {role_name} LOGIN PASSWORD '{password}'")

            # A new authenticated connection is essential: admin/SET ROLE
            # substitutes cannot prove the worker credential boundary.
            worker_engine = create_engine(temp_engine.url.set(username=role_name, password=password))
            with Session(temp_engine) as admin_session:
                checkpoint_user = User(email=f"checkpoint-{uuid.uuid4().hex}@example.com")
                admin_session.add(checkpoint_user)
                admin_session.flush()
                checkpoint_project = Project(owner_user_id=checkpoint_user.id, title="Checkpoint role probe")
                admin_session.add(checkpoint_project)
                admin_session.flush()
                checkpoint_source = Source(
                    project_id=checkpoint_project.id,
                    source_type=SourceType.local_upload,
                    original_filename="checkpoint.wav",
                )
                checkpoint_job = TranscriptionJob(
                    project_id=checkpoint_project.id,
                    owner_user_id=checkpoint_user.id,
                    status=JobStatus.processing,
                    provider="elevenlabs",
                )
                admin_session.add_all([checkpoint_source, checkpoint_job])
                admin_session.flush()
                checkpoint_relation = TranscriptionJobSource(
                    job_id=checkpoint_job.id,
                    source_id=checkpoint_source.id,
                    position=0,
                )
                admin_session.add(checkpoint_relation)
                admin_session.commit()
                checkpoint_scope = (
                    checkpoint_job.id,
                    checkpoint_relation.id,
                )

            class CheckpointSettings:
                credential_key_id = "worker-role-test-key"
                provider_part_checkpoint_ttl_seconds = 3600

                @staticmethod
                def master_key_b64():
                    return base64.b64encode(b"c" * 32).decode("ascii")

            checkpoint_result = normalize_elevenlabs_transcript_response(
                {
                    "text": "checkpoint",
                    "words": [
                        {"text": "checkpoint", "start": 0, "end": 1}
                    ],
                }
            )
            with Session(worker_engine) as worker_session:
                checkpoint = save_provider_part_checkpoint(
                    worker_session,
                    job_id=checkpoint_scope[0],
                    job_source_id=checkpoint_scope[1],
                    part_index=0,
                    total_parts=2,
                    timeline_offset_seconds=0,
                    duration_seconds=1,
                    result=checkpoint_result,
                    settings=CheckpointSettings(),
                    now=datetime.now(timezone.utc),
                )
                worker_session.commit()
                checkpoint_id = checkpoint.id

            with worker_engine.connect() as conn:
                assert conn.execute(text("SELECT current_user")).scalar_one() == role_name
                assert check_database_readiness(conn)["schema_revision"] == repository_schema_head()
                worker_health.check_worker_database_role(conn)
                # Project metadata is read-only for the worker. PostgreSQL
                # correctly rejects FOR UPDATE here, so processing code must not
                # request that lock merely to validate project ownership/state.
                conn.execute(text("SELECT id FROM projects LIMIT 0"))
                with pytest.raises(ProgrammingError) as failure:
                    conn.execute(text("SELECT id FROM projects LIMIT 0 FOR UPDATE"))
                assert failure.value.orig.sqlstate == "42501"
                conn.rollback()
                assert conn.execute(
                    text(
                        "SELECT id FROM transcription_provider_part_checkpoints "
                        "WHERE id = :checkpoint_id"
                    ),
                    {"checkpoint_id": checkpoint_id},
                ).scalar_one() == checkpoint_id
                # Operational alert evaluation reads the current provider
                # account snapshot, but never mutates provider accounting.
                conn.execute(text("SELECT id FROM provider_account_snapshots LIMIT 0"))
                conn.execute(text("SELECT user_id FROM yandex_disk_connections FOR UPDATE"))
                conn.execute(text("UPDATE yandex_disk_connections SET token_ciphertext=token_ciphertext WHERE false"))
                conn.execute(text("SELECT id FROM yandex_disk_resources LIMIT 0"))
                with pytest.raises(ProgrammingError) as failure:
                    conn.execute(
                        text(
                            "SELECT id FROM transcription_provider_part_checkpoints "
                            "WHERE id = :checkpoint_id FOR UPDATE"
                        ),
                        {"checkpoint_id": checkpoint_id},
                    )
                assert failure.value.orig.sqlstate == "42501"
                conn.rollback()
                for statement in (
                    "INSERT INTO alembic_version (version_num) VALUES ('forbidden')",
                    "UPDATE alembic_version SET version_num = version_num",
                    "DELETE FROM alembic_version",
                    "TRUNCATE alembic_version",
                    "CREATE TABLE public.worker_must_not_create (id integer)",
                    "SELECT * FROM sessions LIMIT 0",
                    "UPDATE yandex_disk_connections SET account_uid=account_uid",
                    "UPDATE yandex_disk_connections SET status=status",
                    "DELETE FROM yandex_disk_connections",
                    "DELETE FROM yandex_disk_resources",
                ):
                    with pytest.raises(ProgrammingError) as failure:
                        conn.execute(text(statement))
                    assert failure.value.orig.sqlstate == "42501", statement
                    conn.rollback()

            script = (ROOT / "scripts/configure_studio_worker_db_role.sh").read_text(encoding="utf-8")
            queries = [query.replace("${ROLE_NAME}", role_name)
                       for query in re.findall(r'psql_admin -Atqc "([^"]+)"', script)]
            assert len(queries) == 7
            assert "has_column_privilege" in queries[-1] and "yandex_disk_connections" in queries[-1]
            with temp_engine.begin() as conn:
                assert all(conn.execute(text(query)).scalar_one() is True for query in queries)
                conn.execute(text(f"REVOKE SELECT ON alembic_version FROM {role_name}"))
            with worker_engine.connect() as conn:
                # Reproduce the missing-grant failure, not just a bool fixture.
                with pytest.raises(ProgrammingError) as failure:
                    check_database_readiness(conn)
                assert failure.value.orig.sqlstate == "42501"
                conn.rollback()
                with pytest.raises(RuntimeError, match="worker_database_privileges_invalid"):
                    worker_health.check_worker_database_role(conn)
            with temp_engine.begin() as conn:
                conn.execute(text(f"GRANT SELECT ON alembic_version TO {role_name}"))
            with worker_engine.connect() as conn:
                assert check_database_readiness(conn)["migrations"] == "current"
                worker_health.check_worker_database_role(conn)
    finally:
        if worker_engine is not None:
            worker_engine.dispose()
        # The isolated database (and its grants) is already gone at this point.
        with engine.begin() as conn:
            conn.execute(text(f"DROP ROLE IF EXISTS {role_name}"))


def test_query_bound_indexes_are_applied_to_postgresql():
    expected = {
        "projects": "ix_projects_owner_active_updated_id",
        "sources": "ix_sources_project_deleted_created_id",
        "transcription_jobs": "ix_transcription_jobs_project_owner_created_id",
        "audit_events": "ix_audit_events_subject_created_id",
        "transcription_provider_part_checkpoints": "ix_provider_part_checkpoints_expiry_id",
        "realtime_transcript_drafts": "ix_realtime_drafts_expiry_id",
        "audio_preparation_jobs": "ix_audio_preparation_jobs_owner_project_created_id",
    }
    with engine.connect() as conn:
        inspector = inspect(conn)
        for table, index_name in expected.items():
            assert index_name in {
                index["name"] for index in inspector.get_indexes(table)
            }


def test_query_bound_index_migration_round_trip():
    expected = {
        "projects": "ix_projects_owner_active_updated_id",
        "sources": "ix_sources_project_deleted_created_id",
        "transcription_jobs": "ix_transcription_jobs_project_owner_created_id",
        "audit_events": "ix_audit_events_subject_created_id",
        "transcription_provider_part_checkpoints": "ix_provider_part_checkpoints_expiry_id",
        "realtime_transcript_drafts": "ix_realtime_drafts_expiry_id",
        "audio_preparation_jobs": "ix_audio_preparation_jobs_owner_project_created_id",
    }
    with isolated_migration_database("studio_query_bounds") as (temp_engine, env):
        run_alembic("0026_runtime_component_status", env=env)
        run_alembic("0027_query_bounds", env=env)
        with temp_engine.connect() as conn:
            inspector = inspect(conn)
            for table, index_name in expected.items():
                assert index_name in {
                    index["name"] for index in inspector.get_indexes(table)
                }
        run_alembic("0026_runtime_component_status", env=env, command="downgrade")
        with temp_engine.connect() as conn:
            inspector = inspect(conn)
            for table, index_name in expected.items():
                assert index_name not in {
                    index["name"] for index in inspector.get_indexes(table)
                }
        run_alembic("head", env=env)


def test_catalog_metadata_apply_is_idempotent_on_postgresql():
    from studio_api.models import TranscriptCatalogEntry
    from studio_api.transcript_catalog_apply import (
        apply_catalog_migration_metadata,
    )
    from studio_api.transcript_catalog_dry_run import (
        load_catalog_import_authorities,
    )
    from studio_api.transcript_catalog_migration import (
        CatalogDocumentStandardStatus,
        CatalogImportAuthorityStatus,
        CatalogMigrationCandidate,
        CatalogSettingsAuthorityStatus,
    )

    db = SessionLocal()
    try:
        owner = User(
            id="catalog-apply-owner",
            email="catalog-apply@example.com",
        )
        db.add(owner)
        db.commit()
        candidate = CatalogMigrationCandidate(
            drive_document_id="catalog-apply-document",
            name="Catalog apply",
            standard_status=CatalogDocumentStandardStatus.current,
            import_status=CatalogImportAuthorityStatus.not_imported,
            settings_status=CatalogSettingsAuthorityStatus.indeterminate,
        )

        first = apply_catalog_migration_metadata(
            db,
            owner_user_id=owner.id,
            candidates=(candidate,),
        )
        db.commit()
        first_row = db.execute(
            select(TranscriptCatalogEntry)
        ).scalar_one()
        first_id = first_row.id
        first_imported_at = first_row.imported_at

        with SessionLocal() as fresh_db:
            authority = load_catalog_import_authorities(
                fresh_db,
                owner_user_id=owner.id,
                document_ids=("catalog-apply-document",),
            )["catalog-apply-document"]

        second = apply_catalog_migration_metadata(
            db,
            owner_user_id=owner.id,
            candidates=(candidate,),
        )
        db.commit()
        repeated = db.execute(
            select(TranscriptCatalogEntry)
        ).scalar_one()

        assert first["items"][0]["outcome"] == "imported"
        assert authority.import_status.value == "imported_exact"
        assert authority.settings_status.value == "indeterminate"
        assert second["items"][0]["outcome"] == "already_applied"
        assert repeated.id == first_id
        assert repeated.imported_at == first_imported_at
    finally:
        db.rollback()
        db.close()


def test_transcript_catalog_migration_routes_require_authentication_and_csrf():
    anonymous = TestClient(app)
    body = {"folder_id": "private-folder"}
    assert anonymous.post(
        "/api/transcript-catalog/migration/dry-run",
        json=body,
    ).status_code == 401
    assert anonymous.post(
        "/api/transcript-catalog/migration/apply",
        json={**body, "confirm_apply": True},
    ).status_code == 401
    assert anonymous.post(
        "/api/transcript-maintenance/standardization/dry-run",
        json=body,
    ).status_code == 401
    assert anonymous.post(
        "/api/transcript-maintenance/catalog-import/dry-run",
        json=body,
    ).status_code == 401
    for path in (
        "/api/transcript-maintenance/standardization/apply",
        "/api/transcript-maintenance/catalog-import/apply",
    ):
        assert anonymous.post(
            path,
            json={**body, "confirm_apply": True},
        ).status_code == 401
    assert anonymous.post(
        "/api/transcript-catalog/clear",
        json={"confirm_clear": True},
    ).status_code == 401

    password = admin("catalog-route-auth@example.com")
    client = TestClient(app)
    login(client, password, "catalog-route-auth@example.com")
    response = client.post(
        "/api/transcript-catalog/migration/dry-run",
        json=body,
        headers={"origin": "https://studio.test"},
    )
    assert response.status_code == 403
    for path in (
        "/api/transcript-maintenance/standardization/dry-run",
        "/api/transcript-maintenance/catalog-import/dry-run",
    ):
        assert client.post(
            path,
            json=body,
            headers={"origin": "https://studio.test"},
        ).status_code == 403
    assert client.post(
        "/api/transcript-catalog/clear",
        json={"confirm_clear": True},
        headers={"origin": "https://studio.test"},
    ).status_code == 403
    for path in (
        "/api/transcript-maintenance/standardization/apply",
        "/api/transcript-maintenance/catalog-import/apply",
    ):
        assert client.post(
            path,
            json={**body, "confirm_apply": True},
            headers={"origin": "https://studio.test"},
        ).status_code == 403


def test_readiness_non_200_when_migrations_pending():
    cfg = Config(str(ALEMBIC)); head = ScriptDirectory.from_config(cfg).get_current_head()
    with engine.begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num='pending_test'"))
    try:
        assert TestClient(app).get("/api/healthz").status_code == 503
    finally:
        with engine.begin() as conn:
            conn.execute(text("UPDATE alembic_version SET version_num=:head"), {"head": head})


def test_login_refresh_csrf_session_cookie_and_logout_after_refresh():
    pw = admin(); c = TestClient(app)
    assert c.post("/api/auth/login", json={"email": "a@example.com", "password": pw, "login_csrf_token": "bad"}, headers={"origin": "https://studio.test"}).status_code == 403
    csrf = login(c, pw)
    assert c.get("/api/auth/session").json()["authenticated"] is True
    refreshed = c.post("/api/auth/csrf", headers={"origin": "https://studio.test"})
    assert refreshed.status_code == 200 and refreshed.json()["csrf_token"] != csrf
    assert c.post("/api/auth/logout", headers={"origin": "https://studio.test", "x-csrf-token": refreshed.json()["csrf_token"]}).status_code == 200
    assert c.get("/api/auth/session").status_code == 401


def test_same_origin_and_authenticated_csrf_required():
    pw = admin(); c = TestClient(app); csrf = login(c, pw)
    assert c.post("/api/auth/logout", headers={"origin": "https://evil.test", "x-csrf-token": csrf}).status_code == 403
    assert c.post("/api/auth/logout", headers={"origin": "https://studio.test", "x-csrf-token": "bad"}).status_code == 403


def test_active_sessions_list_is_owner_scoped_bounded_and_safe():
    email = "session-list@example.com"
    password = admin(email)
    current = TestClient(app)
    other = TestClient(app)
    login(current, password, email)
    login(other, password, email)

    db = SessionLocal()
    try:
        owner = db.query(User).filter_by(email=email).one()
        outsider = User(
            email="session-list-outsider@example.com",
            role=UserRole.user,
            status=UserStatus.active,
        )
        db.add(outsider)
        db.flush()
        now = utcnow()
        db.add_all(
            [
                DbSession(
                    user_id=owner.id,
                    token_hash="e" * 64,
                    csrf_hash="f" * 64,
                    expires_at=now - timedelta(minutes=1),
                ),
                DbSession(
                    user_id=owner.id,
                    token_hash="a" * 64,
                    csrf_hash="b" * 64,
                    expires_at=now + timedelta(days=1),
                    revoked_at=now,
                ),
                DbSession(
                    user_id=outsider.id,
                    token_hash="c" * 64,
                    csrf_hash="d" * 64,
                    expires_at=now + timedelta(days=1),
                ),
                *[
                    DbSession(
                        user_id=owner.id,
                        token_hash=f"{index:064x}",
                        csrf_hash=f"{index + 1000:064x}",
                        expires_at=now + timedelta(days=1),
                        created_at=now - timedelta(minutes=index + 1),
                    )
                    for index in range(100)
                ],
            ]
        )
        db.commit()
    finally:
        db.close()

    anonymous = TestClient(app)
    assert anonymous.get(
        "/api/auth/sessions", headers={"origin": "https://studio.test"}
    ).status_code == 401
    assert current.get(
        "/api/auth/sessions", headers={"origin": "https://evil.test"}
    ).status_code == 403

    response = current.get(
        "/api/auth/sessions", headers={"origin": "https://studio.test"}
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    payload = response.json()
    assert payload["truncated"] is True
    assert payload["limit"] == 100
    assert len(payload["sessions"]) == 100
    assert payload["sessions"][0]["is_current"] is True
    assert sum(row["is_current"] for row in payload["sessions"]) == 1
    assert all(
        set(row) == {
            "id",
            "is_current",
            "created_at",
            "last_seen_at",
            "expires_at",
        }
        for row in payload["sessions"]
    )
    serialized = response.text.lower()
    assert "token" not in serialized
    assert "csrf" not in serialized
    assert "user_id" not in serialized


def test_targeted_session_revoke_is_safe_owner_scoped_and_idempotent():
    email = "session-revoke@example.com"
    password = admin(email)
    current = TestClient(app)
    other = TestClient(app)
    csrf = login(current, password, email)
    login(other, password, email)
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    listed = current.get(
        "/api/auth/sessions", headers={"origin": "https://studio.test"}
    ).json()["sessions"]
    current_id = next(row["id"] for row in listed if row["is_current"])
    other_id = next(row["id"] for row in listed if not row["is_current"])

    cross_owner_password = admin("session-revoke-outsider@example.com")
    cross_owner = TestClient(app)
    login(cross_owner, cross_owner_password, "session-revoke-outsider@example.com")
    cross_owner_id = cross_owner.get(
        "/api/auth/sessions", headers={"origin": "https://studio.test"}
    ).json()["sessions"][0]["id"]

    assert current.delete(
        f"/api/auth/sessions/{other_id}",
        headers={"origin": "https://studio.test", "x-csrf-token": "bad"},
    ).status_code == 403
    current_revoke = current.delete(
        f"/api/auth/sessions/{current_id}", headers=headers
    )
    assert current_revoke.status_code == 409
    assert current_revoke.json()["detail"] == {
        "reason": "current_session_requires_logout"
    }
    assert current.get("/api/auth/session").status_code == 200

    absent = current.delete(
        "/api/auth/sessions/00000000-0000-0000-0000-000000000000",
        headers=headers,
    )
    cross_owner_attempt = current.delete(
        f"/api/auth/sessions/{cross_owner_id}", headers=headers
    )
    assert absent.status_code == 200
    assert cross_owner_attempt.status_code == 200
    assert absent.json() == cross_owner_attempt.json() == {
        "revoked": False,
        "active": False,
    }

    revoked = current.delete(f"/api/auth/sessions/{other_id}", headers=headers)
    assert revoked.status_code == 200
    assert revoked.headers["cache-control"] == "no-store"
    assert revoked.json() == {"revoked": True, "active": False}
    assert other.get("/api/auth/session").status_code == 401
    assert current.delete(
        f"/api/auth/sessions/{other_id}", headers=headers
    ).json() == {"revoked": False, "active": False}
    assert cross_owner.get("/api/auth/session").status_code == 200

    db = SessionLocal()
    try:
        owner = db.query(User).filter_by(email=email).one()
        assert db.query(AuditEvent).filter_by(
            event_type="auth.session_revoked", actor_user_id=owner.id
        ).count() == 1
        event = db.query(AuditEvent).filter_by(
            event_type="auth.session_revoked", actor_user_id=owner.id
        ).one()
        assert json.loads(event.metadata_json) == {
            "reason": "owner_requested",
            "session_id": other_id,
        }
    finally:
        db.close()


def test_revoke_other_sessions_only_revokes_active_rows_and_is_idempotent():
    email = "session-revoke-all@example.com"
    password = admin(email)
    current = TestClient(app)
    other_a = TestClient(app)
    other_b = TestClient(app)
    csrf = login(current, password, email)
    login(other_a, password, email)
    login(other_b, password, email)

    db = SessionLocal()
    try:
        owner = db.query(User).filter_by(email=email).one()
        expired = DbSession(
            user_id=owner.id,
            token_hash="9" * 64,
            csrf_hash="8" * 64,
            expires_at=utcnow() - timedelta(minutes=1),
        )
        db.add(expired)
        db.commit()
        expired_id = expired.id
    finally:
        db.close()

    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    assert current.post("/api/auth/sessions/revoke-other").status_code == 403
    first = current.post("/api/auth/sessions/revoke-other", headers=headers)
    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    assert first.json() == {"revoked": 2}
    assert current.get("/api/auth/session").status_code == 200
    assert other_a.get("/api/auth/session").status_code == 401
    assert other_b.get("/api/auth/session").status_code == 401
    assert current.post(
        "/api/auth/sessions/revoke-other", headers=headers
    ).json() == {"revoked": 0}

    db = SessionLocal()
    try:
        owner = db.query(User).filter_by(email=email).one()
        assert db.get(DbSession, expired_id).revoked_at is None
        assert db.query(AuditEvent).filter_by(
            event_type="auth.sessions_revoked", actor_user_id=owner.id
        ).count() == 1
    finally:
        db.close()


def test_account_source_retention_preferences_are_server_authoritative():
    email = "retention-preferences@example.com"
    pw = admin(email)
    anonymous = TestClient(app)
    assert anonymous.get("/api/account/preferences").status_code == 401

    c = TestClient(app)
    csrf = login(c, pw, email)
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    expected_options = [259200, 604800, 2592000]
    current = c.get("/api/account/preferences")
    assert current.status_code == 200
    assert current.json() == {
        "source_retention_ttl_seconds": 259200,
        "allowed_source_retention_ttl_seconds": expected_options,
        "accent_color": "blue",
        "allowed_accent_colors": ["blue", "violet", "teal", "rose"],
    }
    assert c.patch("/api/account/preferences", json={"source_retention_ttl_seconds": 604800}).status_code == 403
    assert c.patch("/api/account/preferences", json={"source_retention_ttl_seconds": 7200}, headers=headers).status_code == 422
    for legacy_seconds in (3600, 86400):
        assert c.patch("/api/account/preferences", json={"source_retention_ttl_seconds": legacy_seconds}, headers=headers).status_code == 422
    assert c.patch("/api/account/preferences", json={"source_retention_ttl_seconds": 604800, "unknown": True}, headers=headers).status_code == 422
    assert c.patch("/api/account/preferences", json={"accent_color": "orange"}, headers=headers).status_code == 422
    assert c.patch("/api/account/preferences", json={}, headers=headers).status_code == 422

    updated = c.patch("/api/account/preferences", json={"source_retention_ttl_seconds": 604800}, headers=headers)
    assert updated.status_code == 200
    assert updated.json() == {
        "source_retention_ttl_seconds": 604800,
        "allowed_source_retention_ttl_seconds": expected_options,
        "accent_color": "blue",
        "allowed_accent_colors": ["blue", "violet", "teal", "rose"],
    }
    accent = c.patch("/api/account/preferences", json={"accent_color": "teal"}, headers=headers)
    assert accent.status_code == 200
    assert accent.json()["accent_color"] == "teal"
    assert c.patch("/api/account/preferences", json={"source_retention_ttl_seconds": 604800, "accent_color": "teal"}, headers=headers).status_code == 200
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email=email).one()
        assert user.source_retention_ttl_seconds == 604800
        assert user.accent_color == "teal"
        assert db.query(AuditEvent).filter_by(event_type="account.preferences_updated", actor_user_id=user.id).count() == 2
    finally:
        db.close()


def test_job_notification_preferences_are_owner_scoped_opt_in_and_fail_closed():
    email = "notification-preferences@example.com"
    pw = admin(email)
    anonymous = TestClient(app)
    assert anonymous.get("/api/notifications/preferences").status_code == 401

    c = TestClient(app)
    csrf = login(c, pw, email)
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    current = c.get(
        "/api/notifications/preferences", headers={"origin": "https://studio.test"}
    )
    assert current.status_code == 200
    assert current.headers["cache-control"] == "no-store"
    assert current.json() == {
        "channels": {
            "web_push": {
                "enabled": False,
                "configured": False,
                "subscription_count": 0,
                "vapid_public_key": None,
            },
            "email": {"enabled": False, "configured": False},
            "telegram": {"enabled": False, "configured": False},
        },
        "recent_deliveries": [],
    }
    assert c.patch(
        "/api/notifications/preferences",
        json={"email_enabled": True},
    ).status_code == 403
    assert c.patch(
        "/api/notifications/preferences",
        json={"unknown": True},
        headers=headers,
    ).status_code == 422
    blocked = c.patch(
        "/api/notifications/preferences",
        json={"email_enabled": True},
        headers=headers,
    )
    assert blocked.status_code == 410
    assert blocked.json() == {
        "detail": "Для уведомлений о задачах используется только Telegram"
    }
    assert c.post(
        "/api/notifications/web-push/subscriptions",
        json={
            "endpoint": "https://fcm.googleapis.com/fcm/send/browser",
            "p256dh": "A" * 80,
            "auth": "A" * 20,
        },
        headers=headers,
    ).status_code == 410


def test_source_upload_policy_is_authenticated_safe_and_not_cached(monkeypatch):
    email = "source-upload-policy@example.com"
    pw = admin(email)
    anonymous = TestClient(app)
    assert anonymous.get("/api/sources/upload-policy").status_code == 401

    from studio_api import main as main_mod
    monkeypatch.setattr(main_mod.settings, "source_max_upload_bytes", 123456)
    monkeypatch.setattr(main_mod.settings, "source_multipart_threshold_bytes", 16 * 1024 * 1024)
    monkeypatch.setattr(main_mod.settings, "source_multipart_part_size_bytes", 8 * 1024 * 1024)
    monkeypatch.setattr(main_mod.settings, "media_duration_warning_seconds", 7200)
    monkeypatch.setattr(main_mod.settings, "media_max_duration_seconds", 21600)
    monkeypatch.setattr(
        type(main_mod.settings),
        "reference_storage_isolation_configured",
        lambda self: True,
    )
    c = TestClient(app)
    login(c, pw, email)
    response = c.get("/api/sources/upload-policy")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.json() == {
        "local_upload_enabled": True,
        "max_upload_bytes": 123456,
        "multipart_threshold_bytes": 16 * 1024 * 1024,
        "multipart_part_size_bytes": 8 * 1024 * 1024,
        "media_duration_warning_seconds": 7200,
        "media_max_duration_seconds": 21600,
        "supported_mime_prefixes": ["audio/", "video/"],
        "supported_mime_types": ["application/ogg"],
    }
    forbidden = ["bucket", "object", "presigned", "endpoint", "access_key", "secret"]
    assert all(value not in response.text.lower() for value in forbidden)


def test_storage_lifecycle_and_reconciliation_endpoints_are_safe_and_confirmed(monkeypatch):
    from studio_api import main as main_mod
    from studio_api.source_storage import StoredObject
    from studio_api.storage_reconciliation import (
        OrphanCandidate,
        StorageReconciliationApplyResult,
        StorageReconciliationScan,
    )

    email = "storage-lifecycle-api@example.com"
    pw = admin(email)
    monkeypatch.setattr(
        type(main_mod.settings),
        "reference_storage_isolation_configured",
        lambda self: True,
    )
    anonymous = TestClient(app)
    assert anonymous.get("/api/storage/lifecycle").status_code == 401
    c = TestClient(app)
    csrf = login(c, pw, email)
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    lifecycle = c.get("/api/storage/lifecycle")
    assert lifecycle.status_code == 200
    assert lifecycle.headers["cache-control"] == "no-store"
    assert lifecycle.json()["reconciliation"] == {
        "available": True,
        "dry_run_default": True,
        "apply_requires_confirmation": True,
        "minimum_orphan_age_seconds": main_mod.settings.storage_orphan_min_age_seconds,
        "scan_limit": main_mod.settings.storage_reconciliation_scan_limit,
        "apply_limit": main_mod.settings.storage_reconciliation_apply_limit,
    }
    assert all(
        forbidden not in lifecycle.text.lower()
        for forbidden in ("bucket", "access_key", "object_key")
    )

    private_key = "transcription/users/private-owner/orphan/source"
    candidate = OrphanCandidate(
        "transcription",
        "private-bucket",
        StoredObject(
            private_key,
            123,
            '"etag"',
            datetime(2026, 8, 1, tzinfo=timezone.utc),
        ),
    )
    scan = StorageReconciliationScan(3, 1, (candidate,), 123, False)
    monkeypatch.setattr(main_mod, "scan_owner_storage", lambda *args, **kwargs: scan)
    assert c.post("/api/storage/reconciliation/preview").status_code == 403
    preview = c.post("/api/storage/reconciliation/preview", headers=headers)
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["orphan_count"] == 1
    assert preview_body["orphan_bytes"] == 123
    assert preview_body["apply_available"] is True
    assert private_key not in preview.text and "private-bucket" not in preview.text
    assert c.post(
        "/api/storage/reconciliation/apply",
        json={"plan_token": preview_body["plan_token"], "confirm": False},
        headers=headers,
    ).status_code == 422

    monkeypatch.setattr(
        main_mod,
        "apply_reconciliation_plan",
        lambda *args, **kwargs: StorageReconciliationApplyResult(1, 1, 0, 123),
    )
    applied = c.post(
        "/api/storage/reconciliation/apply",
        json={"plan_token": preview_body["plan_token"], "confirm": True},
        headers=headers,
    )
    assert applied.status_code == 200
    assert applied.json() == {
        "status": "completed",
        "planned_count": 1,
        "deleted_count": 1,
        "failed_count": 0,
        "deleted_bytes": 123,
    }
    assert private_key not in applied.text and "private-bucket" not in applied.text


def test_credential_lifecycle_no_raw_secret_echo_and_audit_safe():
    pw = admin(); raw = "sk-test-secret-value-123456"
    with TestClient(app) as c:
        csrf = login(c, pw)
        r = c.post("/api/credentials", json={"provider": "openai", "label": "main", "raw_value": raw}, headers={"origin": "https://studio.test", "x-csrf-token": csrf}); assert r.status_code == 200; cid = r.json()["id"]; assert raw not in r.text
        r = c.get("/api/credentials"); assert raw not in r.text and "••••" in r.text
        r = c.post(f"/api/credentials/{cid}/replace", json={"provider": "openai", "label": "main", "raw_value": "sk-test-new-secret-abcdef"}, headers={"origin": "https://studio.test", "x-csrf-token": csrf}); assert r.status_code == 200
        r = c.post(f"/api/credentials/{cid}/revoke", headers={"origin": "https://studio.test", "x-csrf-token": csrf}); assert r.status_code == 200
        r = c.delete(f"/api/credentials/{cid}", headers={"origin": "https://studio.test", "x-csrf-token": csrf}); assert r.status_code == 200
    db = SessionLocal()
    try:
        assert raw not in "\n".join(a.metadata_json for a in db.query(AuditEvent).all())
        assert all(v.ciphertext is None for v in db.query(ProviderCredentialVersion).all())
    finally:
        db.close()


@pytest.mark.parametrize("provider", ["tbank", "mistral", "gemini"])
def test_new_provider_keys_are_encrypted_scoped_and_never_echoed(provider):
    pw = admin()
    raw = (json.dumps({"api_key": "synthetic-voicekit-public", "secret_key": base64.b64encode(b"x" * 32).decode()})
        if provider == "tbank" else "synthetic-independent-provider-secret")
    with TestClient(app) as client:
        csrf = login(client, pw)
        response = client.post("/api/credentials", json={"provider": provider, "label": "Synthetic", "raw_value": raw},
            headers={"origin": "https://studio.test", "x-csrf-token": csrf})
        assert response.status_code == 200
        assert response.json()["provider"] == provider
        assert raw not in response.text
        collection = client.get("/api/credentials")
        assert collection.status_code == 200 and raw not in collection.text
        assert client.get("/api/stt/providers").status_code == 200
    with SessionLocal() as db:
        credential = db.get(ProviderCredential, response.json()["id"])
        version = db.get(ProviderCredentialVersion, credential.active_version_id)
        assert version.ciphertext and raw.encode() not in version.ciphertext
        assert raw not in "\n".join(a.metadata_json for a in db.query(AuditEvent).all())


def test_invalid_provider_pair_validation_never_echoes_submitted_secret():
    pw = admin()
    raw = json.dumps({"api_key": "synthetic-sensitive-id", "secret_key": "synthetic-invalid-sensitive-secret"})
    with TestClient(app) as client:
        csrf = login(client, pw)
        response = client.post("/api/credentials", json={"provider": "tbank", "label": "Synthetic", "raw_value": raw},
            headers={"origin": "https://studio.test", "x-csrf-token": csrf})
        assert response.status_code == 422
        assert "synthetic-sensitive" not in response.text
        assert "synthetic-invalid" not in response.text
        assert "input" not in response.json()["detail"][0]
        assert response.headers["cache-control"] == "no-store"


def test_stt_catalog_yandex_byok_and_owner_dictionary_crud_are_safe_and_scoped():
    owner_password = admin(email="stt-owner@example.com")
    other_password = admin(email="stt-other@example.com")
    raw_key = "AQVN-yandex-api-key-private-value"
    headers = {"origin": "https://studio.test"}

    with TestClient(app) as owner:
        owner_csrf = login(owner, owner_password, email="stt-owner@example.com")
        mutation_headers = headers | {"x-csrf-token": owner_csrf}
        catalog = owner.get("/api/stt/providers")
        assert catalog.status_code == 200
        providers = {
            item["provider"]: item for item in catalog.json()["providers"]
        }
        assert set(providers) == {"elevenlabs", "yandex", "tbank", "mistral", "gemini"}
        assert providers["yandex"]["byok_enabled"] is False
        yandex_modes = {mode["mode"]: mode for mode in providers["yandex"]["modes"]}
        assert yandex_modes["realtime"]["diarization"] is False
        assert yandex_modes["standard"]["diarization"] is True
        assert catalog.headers["cache-control"] == "no-store"

        missing_folder = owner.post(
            "/api/credentials",
            json={"provider": "yandex", "label": "SpeechKit", "raw_value": raw_key},
            headers=mutation_headers,
        )
        assert missing_folder.status_code == 422
        created_credential = owner.post(
            "/api/credentials",
            json={
                "provider": "yandex",
                "label": "SpeechKit",
                "raw_value": raw_key,
                "folder_id": "folder-public-identifier",
            },
            headers=mutation_headers,
        )
        assert created_credential.status_code == 200
        assert raw_key not in created_credential.text
        listed_credentials = owner.get("/api/credentials").json()["credentials"]
        yandex = next(item for item in listed_credentials if item["provider"] == "yandex")
        assert yandex["folder_id"] == "folder-public-identifier"
        assert raw_key not in json.dumps(listed_credentials)

        created_dictionary = owner.post(
            "/api/stt/dictionaries",
            json={
                "name": "Команда проекта",
                "entries": [
                    {"kind": "term", "value": "VoiceOps"},
                    {"kind": "surname", "value": "Иванов"},
                    {"kind": "name", "value": "Алёна"},
                    {"kind": "abbreviation", "value": "API"},
                ],
            },
            headers=mutation_headers,
        )
        assert created_dictionary.status_code == 200
        dictionary_id = created_dictionary.json()["id"]
        assert len(created_dictionary.json()["entries"]) == 4
        duplicate = owner.post(
            "/api/stt/dictionaries",
            json={
                "name": "  команда   проекта ",
                "entries": [{"kind": "term", "value": "другой"}],
            },
            headers=mutation_headers,
        )
        assert duplicate.status_code == 409

    with TestClient(app) as other:
        other_csrf = login(other, other_password, email="stt-other@example.com")
        assert other.get("/api/stt/dictionaries").json() == {"dictionaries": []}
        forbidden_update = other.put(
            f"/api/stt/dictionaries/{dictionary_id}",
            json={
                "name": "Чужой словарь",
                "entries": [{"kind": "term", "value": "чужой"}],
            },
            headers=headers | {"x-csrf-token": other_csrf},
        )
        assert forbidden_update.status_code == 404

    with TestClient(app) as owner:
        owner_csrf = login(owner, owner_password, email="stt-owner@example.com")
        deleted = owner.delete(
            f"/api/stt/dictionaries/{dictionary_id}",
            headers=headers | {"x-csrf-token": owner_csrf},
        )
        assert deleted.status_code == 200
        assert owner.get("/api/stt/dictionaries").json() == {"dictionaries": []}
        recreated = owner.post(
            "/api/stt/dictionaries",
            json={
                "name": "Команда проекта",
                "entries": [{"kind": "term", "value": "VoiceOps"}],
            },
            headers=headers | {"x-csrf-token": owner_csrf},
        )
        assert recreated.status_code == 200


def test_elevenlabs_account_routes_are_owner_scoped_no_store_and_never_echo_secret(monkeypatch):
    from decimal import Decimal
    from studio_api import main as main_mod
    from studio_api.elevenlabs_account import (
        ProductCreditUsage,
        SubscriptionSnapshot,
        WorkspaceUsageSnapshot,
    )

    class AccountTransport:
        def fetch_subscription(self, api_key):
            assert api_key == "private-elevenlabs-account-key"
            return SubscriptionSnapshot(
                tier="creator",
                status="active",
                period_usage=120,
                period_limit=1000,
                period_remaining=880,
                period_unit="characters",
                max_credit_limit_extension="unlimited",
                usage_based_billing_enabled=True,
                current_overage_amount=Decimal("2.50000000"),
                current_overage_currency="USD",
                open_invoice_count=1,
                open_invoice_total_due_cents=250,
                has_open_invoices=True,
                next_invoice_amount_due_cents=2250,
                next_invoice_subtotal_cents=2000,
                next_invoice_tax_cents=250,
                next_payment_attempt_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                subscription_currency="USD",
                billing_period="monthly_period",
                refresh_period="monthly_period",
                reset_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                pending_change_present=False,
            )

        def fetch_workspace_usage(self, api_key, *, subscription, now):
            assert api_key == "private-elevenlabs-account-key"
            assert subscription.tier == "creator"
            return WorkspaceUsageSnapshot(
                window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
                window_end=now,
                window_basis="provider_reset_period",
                unit="credits",
                total_credits=Decimal("42.00000000"),
                products=(
                    ProductCreditUsage("speech-to-text", Decimal("42.00000000")),
                ),
            )

    monkeypatch.setattr(main_mod, "ElevenLabsAccountTransport", AccountTransport)
    assert TestClient(app).get("/api/provider-accounts/elevenlabs").status_code == 401

    owner_email = "provider-account-owner@example.com"
    other_email = "provider-account-other@example.com"
    owner = TestClient(app)
    other = TestClient(app)
    owner_csrf = login(owner, admin(owner_email), owner_email)
    other_csrf = login(other, admin(other_email), other_email)
    secret = "private-elevenlabs-account-key"
    created = owner.post(
        "/api/credentials",
        json={"provider": "elevenlabs", "label": "Основной", "raw_value": secret},
        headers={"origin": "https://studio.test", "x-csrf-token": owner_csrf},
    )
    assert created.status_code == 200, created.text
    credential_id = created.json()["id"]

    response = owner.get("/api/provider-accounts/elevenlabs")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert secret not in response.text
    account = response.json()["accounts"][0]
    assert account["credential"] == {
        "id": credential_id,
        "label": "Основной",
        "active_version": 1,
    }
    assert account["state"] == "current"
    assert account["subscription"]["period_remaining"] == 880
    assert account["subscription"]["current_overage"]["amount"] == "2.50000000"
    assert account["workspace_usage"]["products"] == [
        {"product_type": "speech-to-text", "credits": "42.00000000"}
    ]

    refreshed = owner.post(
        f"/api/provider-accounts/elevenlabs/{credential_id}/refresh",
        headers={"origin": "https://studio.test", "x-csrf-token": owner_csrf},
    )
    assert refreshed.status_code == 200
    assert refreshed.headers["cache-control"] == "no-store"
    assert refreshed.json()["account"]["state"] == "current"
    assert secret not in refreshed.text
    assert (
        other.post(
            f"/api/provider-accounts/elevenlabs/{credential_id}/refresh",
            headers={"origin": "https://studio.test", "x-csrf-token": other_csrf},
        ).status_code
        == 404
    )


def test_deleted_credential_is_terminal_hidden_and_delete_replay_is_idempotent():
    password = admin("credential-terminal@example.com")
    client = TestClient(app)
    csrf = login(client, password, "credential-terminal@example.com")
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    created = client.post(
        "/api/credentials",
        json={
            "provider": "elevenlabs",
            "label": "terminal",
            "raw_value": "terminal-secret-value",
        },
        headers=headers,
    )
    assert created.status_code == 200
    credential_id = created.json()["id"]
    first_revoke = client.post(
        f"/api/credentials/{credential_id}/revoke", headers=headers
    )
    replayed_revoke = client.post(
        f"/api/credentials/{credential_id}/revoke", headers=headers
    )
    assert first_revoke.status_code == 200
    assert replayed_revoke.status_code == 200
    db = SessionLocal()
    try:
        assert (
            db.query(AuditEvent)
            .filter_by(event_type="credential.revoked")
            .count()
            == 1
        )
    finally:
        db.close()

    replaced = client.post(
        f"/api/credentials/{credential_id}/replace",
        json={
            "provider": "elevenlabs",
            "label": "terminal",
            "raw_value": "terminal-replacement-value",
        },
        headers=headers,
    )
    assert replaced.status_code == 200

    first_delete = client.delete(
        f"/api/credentials/{credential_id}", headers=headers
    )
    assert first_delete.status_code == 200
    db = SessionLocal()
    try:
        credential = db.get(ProviderCredential, credential_id)
        assert credential is not None
        first_deleted_at = credential.deleted_at
        assert credential.status == CredentialStatus.deleted
        versions = (
            db.query(ProviderCredentialVersion)
            .filter_by(credential_id=credential_id)
            .order_by(ProviderCredentialVersion.version)
            .all()
        )
        assert len(versions) == 2
        assert all(version.ciphertext is None for version in versions)
        assert all(version.nonce is None for version in versions)
        assert all(version.deleted_at == first_deleted_at for version in versions)
        assert (
            db.query(AuditEvent)
            .filter_by(event_type="credential.deleted")
            .count()
            == 1
        )
    finally:
        db.close()

    replay = client.delete(f"/api/credentials/{credential_id}", headers=headers)
    assert replay.status_code == 200
    assert all(
        item["id"] != credential_id
        for item in client.get("/api/credentials").json()["credentials"]
    )
    assert (
        client.post(
            f"/api/credentials/{credential_id}/replace",
            json={
                "provider": "elevenlabs",
                "label": "terminal",
                "raw_value": "must-not-reactivate",
            },
            headers=headers,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/credentials/{credential_id}/revoke", headers=headers
        ).status_code
        == 404
    )
    db = SessionLocal()
    try:
        credential = db.get(ProviderCredential, credential_id)
        assert credential is not None
        assert credential.deleted_at == first_deleted_at
        assert credential.status == CredentialStatus.deleted
        assert (
            db.query(ProviderCredentialVersion)
            .filter_by(credential_id=credential_id)
            .count()
            == 2
        )
        assert (
            db.query(AuditEvent)
            .filter_by(event_type="credential.deleted")
            .count()
            == 1
        )
    finally:
        db.close()

def test_realtime_capability_route_requires_owner_csrf_and_returns_no_store(monkeypatch):
    from studio_api import main as main_mod

    owner_email = "realtime-owner@example.com"
    other_email = "realtime-other@example.com"
    owner_password = admin(owner_email)
    other_password = admin(other_email)
    owner_client = TestClient(app)
    other_client = TestClient(app)
    owner_csrf = login(owner_client, owner_password, owner_email)
    other_csrf = login(other_client, other_password, other_email)
    owner_headers = {
        "origin": "https://studio.test",
        "x-csrf-token": owner_csrf,
    }
    other_headers = {
        "origin": "https://studio.test",
        "x-csrf-token": other_csrf,
    }

    project = owner_client.post(
        "/api/projects",
        json={"title": "Realtime"},
        headers=owner_headers,
    ).json()
    credential = owner_client.post(
        "/api/credentials",
        json={
            "provider": "elevenlabs",
            "label": "Realtime",
            "raw_value": "sk_realtime_main_secret",
        },
        headers=owner_headers,
    ).json()

    captured = {}

    def fake_capability(api_key, *, language_code):
        captured.update(api_key=api_key, language_code=language_code)
        return RealtimeCapability(
            websocket_url=(
                "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
                "?token=sutkn_browser_only"
            ),
        )

    monkeypatch.setattr(main_mod, "create_realtime_capability", fake_capability)
    path = f"/api/projects/{project['id']}/realtime/capability"
    body = {
        "provider_credential_id": credential["id"],
        "language": "en",
    }

    assert TestClient(app).post(path, json=body).status_code == 401
    assert owner_client.post(
        path,
        json=body,
        headers={"origin": "https://studio.test"},
    ).status_code == 403
    assert owner_client.post(
        path,
        json=body,
        headers={"origin": "https://evil.test", "x-csrf-token": owner_csrf},
    ).status_code == 403
    assert other_client.post(path, json=body, headers=other_headers).status_code == 404

    response = owner_client.post(path, json=body, headers=owner_headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.json() == {
        "websocket_url": (
            "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
            "?token=sutkn_browser_only"
        ),
        "expires_in_seconds": 900,
        "model_id": "scribe_v2_realtime",
        "audio_format": "pcm_16000",
        "commit_strategy": "vad",
    }
    assert captured == {
        "api_key": "sk_realtime_main_secret",
        "language_code": "en",
    }
    assert "sk_realtime_main_secret" not in response.text

    db = SessionLocal()
    try:
        event = db.query(DiagnosticEvent).filter_by(
            event_code="REALTIME_CAPABILITY_ISSUED",
        ).one()
        assert "sk_realtime_main_secret" not in event.metadata_json
        assert "sutkn_browser_only" not in event.metadata_json
    finally:
        db.close()

    def diagnostic_failure(**_kwargs):
        raise RuntimeError("diagnostic storage unavailable")

    monkeypatch.setattr(main_mod, "write_diagnostic_event", diagnostic_failure)
    response_without_diagnostic = owner_client.post(
        path,
        json=body,
        headers=owner_headers,
    )
    assert response_without_diagnostic.status_code == 200
    assert "sutkn_browser_only" in response_without_diagnostic.text
    assert "sk_realtime_main_secret" not in response_without_diagnostic.text


def test_realtime_draft_routes_are_private_monotonic_and_no_store():
    owner_email = "realtime-draft-owner@example.com"
    other_email = "realtime-draft-other@example.com"
    owner_password = admin(owner_email)
    other_password = admin(other_email)
    owner_client = TestClient(app)
    other_client = TestClient(app)
    owner_csrf = login(owner_client, owner_password, owner_email)
    other_csrf = login(other_client, other_password, other_email)
    owner_headers = {
        "origin": "https://studio.test",
        "x-csrf-token": owner_csrf,
    }
    other_headers = {
        "origin": "https://studio.test",
        "x-csrf-token": other_csrf,
    }
    project = owner_client.post(
        "/api/projects",
        json={"title": "Realtime drafts"},
        headers=owner_headers,
    ).json()
    session_id = "session_123456789"
    path = f"/api/projects/{project['id']}/realtime/drafts/{session_id}"
    body = {
        "revision": 1,
        "committed_segments": ["Секретный завершённый фрагмент"],
        "partial": "секретный partial",
    }

    assert TestClient(app).put(path, json=body).status_code == 401
    assert owner_client.put(path, json=body).status_code == 403
    assert other_client.put(path, json=body, headers=other_headers).status_code == 404
    saved = owner_client.put(path, json=body, headers=owner_headers)
    assert saved.status_code == 200
    assert saved.headers["cache-control"] == "no-store"
    assert saved.headers["pragma"] == "no-cache"
    assert "Секретный" not in saved.text
    assert "partial" not in saved.text
    assert saved.json()["draft"]["revision"] == 1

    repeated = owner_client.put(path, json=body, headers=owner_headers)
    assert repeated.status_code == 200
    conflict = owner_client.put(
        path,
        json={**body, "partial": "changed without revision"},
        headers=owner_headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {
        "reason": "realtime_draft_revision_conflict"
    }

    latest_path = f"/api/projects/{project['id']}/realtime/drafts/latest"
    latest = owner_client.get(latest_path)
    assert latest.status_code == 200
    assert latest.headers["cache-control"] == "no-store"
    assert latest.json()["draft"]["committed_segments"] == body["committed_segments"]
    assert latest.json()["draft"]["partial"] == body["partial"]
    assert other_client.get(latest_path).status_code == 404

    db = SessionLocal()
    try:
        row = db.query(RealtimeTranscriptDraft).one()
        assert "Секретный".encode("utf-8") not in row.ciphertext
        assert "секретный partial".encode("utf-8") not in row.ciphertext
        assert db.query(AuditEvent).filter_by(
            event_type="realtime_draft.saved"
        ).count() == 0
    finally:
        db.close()

    assert owner_client.delete(
        path,
        headers={"origin": "https://evil.test", "x-csrf-token": owner_csrf},
    ).status_code == 403
    deleted = owner_client.delete(path, headers=owner_headers)
    assert deleted.status_code == 200
    assert deleted.headers["cache-control"] == "no-store"
    assert deleted.json() == {"ok": True, "deleted": True}
    assert owner_client.get(latest_path).json() == {"draft": None}


def test_realtime_draft_validation_redacts_transcript_input():
    email = "realtime-draft-validation@example.com"
    password = admin(email)
    client = TestClient(app)
    csrf = login(client, password, email)
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    project = client.post(
        "/api/projects",
        json={"title": "Realtime validation"},
        headers=headers,
    ).json()
    secret_marker = "private-transcript-marker"
    response = client.put(
        f"/api/projects/{project['id']}/realtime/drafts/session_123456789",
        json={
            "revision": 1,
            "committed_segments": [],
            "partial": secret_marker + ("x" * 20_000),
        },
        headers=headers,
    )

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert secret_marker not in response.text
    assert all(set(error) == {"type", "loc"} for error in response.json()["detail"])


def test_realtime_draft_identical_first_write_retries_insert_race(monkeypatch):
    from studio_api import main as main_mod

    email = "realtime-draft-insert-race@example.com"
    password = admin(email)
    client = TestClient(app)
    csrf = login(client, password, email)
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    project = client.post(
        "/api/projects",
        json={"title": "Realtime insert race"},
        headers=headers,
    ).json()
    now = datetime.now(timezone.utc)
    calls = []

    def race_then_load(*_args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise IntegrityError("insert", {}, Exception("concurrent insert"))
        return RealtimeDraftContent(
            client_session_id=kwargs["client_session_id"],
            revision=kwargs["revision"],
            committed_segments=tuple(kwargs["committed_segments"]),
            partial=kwargs["partial"],
            updated_at=now,
            expires_at=now + timedelta(hours=72),
        )

    monkeypatch.setattr(main_mod, "save_realtime_draft", race_then_load)
    response = client.put(
        f"/api/projects/{project['id']}/realtime/drafts/session_123456789",
        json={
            "revision": 1,
            "committed_segments": ["first segment"],
            "partial": "partial",
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["draft"]["revision"] == 1
    assert len(calls) == 2


@pytest.mark.parametrize(
    ("reason", "status_code"),
    [
        (RealtimeCapabilityReason.provider_authentication_rejected, 422),
        (RealtimeCapabilityReason.provider_request_rejected, 422),
        (RealtimeCapabilityReason.provider_rate_limited, 429),
        (RealtimeCapabilityReason.provider_timeout, 504),
        (RealtimeCapabilityReason.provider_unavailable, 502),
        (RealtimeCapabilityReason.malformed_provider_response, 502),
    ],
)
def test_realtime_capability_route_reduces_provider_failure_to_safe_reason(
    monkeypatch,
    reason,
    status_code,
):
    from studio_api import main as main_mod

    email = f"realtime-{reason.value}@example.com"
    password = admin(email)
    client = TestClient(app)
    csrf = login(client, password, email)
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    project = client.post(
        "/api/projects",
        json={"title": "Realtime failure"},
        headers=headers,
    ).json()
    client.post(
        "/api/credentials",
        json={
            "provider": "elevenlabs",
            "label": "Realtime",
            "raw_value": "sk_realtime_main_secret",
        },
        headers=headers,
    )

    def fail(*_args, **_kwargs):
        raise RealtimeCapabilityError(reason)

    monkeypatch.setattr(main_mod, "create_realtime_capability", fail)
    response = client.post(
        f"/api/projects/{project['id']}/realtime/capability",
        json={"language": "detect"},
        headers=headers,
    )
    assert response.status_code == status_code
    assert response.json() == {"detail": {"reason": reason.value}}
    assert "sk_realtime_main_secret" not in response.text

    db = SessionLocal()
    try:
        event = db.query(DiagnosticEvent).filter_by(
            event_code="REALTIME_CAPABILITY_FAILED",
        ).one()
        assert reason.value in event.metadata_json
        assert "sk_realtime_main_secret" not in event.metadata_json
        health = db.get(SttProviderHealth, ("elevenlabs", "realtime"))
        if reason.value in {
            "malformed_provider_response",
            "provider_timeout",
            "provider_unavailable",
        }:
            assert health is not None
            assert health.consecutive_failures == 1
            assert health.last_failure_code == reason.value
        else:
            assert health is None
    finally:
        db.close()

    def diagnostic_failure(**_kwargs):
        raise RuntimeError("diagnostic storage unavailable")

    monkeypatch.setattr(main_mod, "write_diagnostic_event", diagnostic_failure)
    response_without_diagnostic = client.post(
        f"/api/projects/{project['id']}/realtime/capability",
        json={"language": "detect"},
        headers=headers,
    )
    assert response_without_diagnostic.status_code == status_code
    assert response_without_diagnostic.json() == {
        "detail": {"reason": reason.value},
    }


def test_realtime_capability_circuit_stops_dispatch_after_systemic_failures(
    monkeypatch,
):
    from studio_api import main as main_mod

    email = "realtime-circuit@example.com"
    password = admin(email)
    client = TestClient(app)
    csrf = login(client, password, email)
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    project = client.post(
        "/api/projects",
        json={"title": "Realtime circuit"},
        headers=headers,
    ).json()
    client.post(
        "/api/credentials",
        json={
            "provider": "elevenlabs",
            "label": "Realtime",
            "raw_value": "sk_realtime_main_secret",
        },
        headers=headers,
    )
    provider_calls = []

    def fail(*_args, **_kwargs):
        provider_calls.append("called")
        raise RealtimeCapabilityError(
            RealtimeCapabilityReason.provider_unavailable,
        )

    monkeypatch.setattr(main_mod, "create_realtime_capability", fail)
    path = f"/api/projects/{project['id']}/realtime/capability"
    for _ in range(main_mod.settings.stt_health_failure_threshold):
        assert client.post(
            path,
            json={"language": "detect"},
            headers=headers,
        ).status_code == 502

    blocked = client.post(
        path,
        json={"language": "detect"},
        headers=headers,
    )
    assert blocked.status_code == 503
    assert blocked.json()["detail"]["reason"] == "provider_mode_unavailable"
    assert len(provider_calls) == main_mod.settings.stt_health_failure_threshold

    db = SessionLocal()
    try:
        health = db.get(SttProviderHealth, ("elevenlabs", "realtime"))
        assert health is not None
        assert health.consecutive_failures == main_mod.settings.stt_health_failure_threshold
        assert health.circuit_open_until is not None
    finally:
        db.close()


def test_realtime_byok_quota_does_not_block_another_owner(monkeypatch):
    from studio_api import main as main_mod

    paths = []
    for index in range(2):
        email = f"quota-owner-{index}@example.com"
        password = admin(email)
        client = TestClient(app)
        csrf = login(client, password, email)
        headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
        project = client.post("/api/projects", json={"title": "Synthetic quota"}, headers=headers).json()
        assert client.post("/api/credentials", json={"provider": "elevenlabs", "label": "Synthetic",
            "raw_value": f"sk_synthetic_owner_{index}"}, headers=headers).status_code == 200
        paths.append((client, headers, f"/api/projects/{project['id']}/realtime/capability"))
    calls = []
    def capability(api_key, **kwargs):
        calls.append(api_key)
        if api_key.endswith("_0"):
            raise RealtimeCapabilityError(RealtimeCapabilityReason.provider_rate_limited)
        return RealtimeCapability(websocket_url="wss://api.elevenlabs.io/v1/speech-to-text/realtime?token=synthetic")
    monkeypatch.setattr(main_mod, "create_realtime_capability", capability)
    client, headers, path = paths[0]
    for _ in range(main_mod.settings.stt_health_failure_threshold):
        assert client.post(path, json={"language": "detect"}, headers=headers).status_code == 429
    client, headers, path = paths[1]
    assert client.post(path, json={"language": "detect"}, headers=headers).status_code == 200
    assert calls[-1] == "sk_synthetic_owner_1"


def test_aes_gcm_unique_nonce_and_aad_binding():
    key = master_key_from_b64(base64.b64encode(b"2" * 32).decode()); associated = aad("u", "c", "v", "openai")
    c1, n1 = encrypt("secret", key, associated); c2, n2 = encrypt("secret", key, associated)
    assert n1 != n2 and c1 != c2 and decrypt(c1, n1, key, associated) == "secret"
    with pytest.raises(Exception): decrypt(c1, n1, key, aad("u", "c", "other", "openai"))


def test_bootstrap_status():
    c = TestClient(app); assert c.get("/api/auth/bootstrap-status").json()["bootstrap_required"] is True; admin(); assert c.get("/api/auth/bootstrap-status").json()["bootstrap_required"] is False


def test_projects_require_authentication():
    c = TestClient(app)
    assert c.get("/api/projects").status_code == 401
    assert c.post("/api/projects", json={"title": "Project"}, headers={"origin": "https://studio.test", "x-csrf-token": "bad"}).status_code == 401
    assert c.post("/api/transcriptions/workspace").status_code == 401


def test_transcription_workspace_reuses_active_and_never_unarchives_legacy_data():
    email = "transcription-workspace@example.com"
    password = admin(email)
    client = TestClient(app)
    csrf = login(client, password, email)
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    existing = client.post(
        "/api/projects",
        json={"title": "Legacy active"},
        headers=headers,
    ).json()

    reused = client.post("/api/transcriptions/workspace", headers=headers)
    assert reused.status_code == 200
    assert reused.json()["created"] is False
    assert reused.json()["project"]["id"] == existing["id"]

    assert client.post(
        f"/api/projects/{existing['id']}/archive",
        headers=headers,
    ).status_code == 200
    created = client.post("/api/transcriptions/workspace", headers=headers)
    assert created.status_code == 200
    assert created.json()["created"] is True
    assert created.json()["project"]["id"] != existing["id"]
    assert created.json()["project"]["title"] == "Транскрибации"
    repeated = client.post("/api/transcriptions/workspace", headers=headers)
    assert repeated.json()["created"] is False
    assert repeated.json()["project"]["id"] == created.json()["project"]["id"]

    db = SessionLocal()
    try:
        archived = db.get(Project, existing["id"])
        assert archived is not None and archived.archived_at is not None
        assert db.query(AuditEvent).filter_by(
            event_type="transcription_workspace.created"
        ).count() == 1
    finally:
        db.close()


def test_audio_preparation_api_create_list_detail_and_owner_boundary():
    from studio_api.models import AudioPreparationJob, AudioPreparationStatus
    email = "audio-preparation-owner@example.com"
    password = admin(email)
    client = TestClient(app)
    csrf = login(client, password, email)
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    workspace = client.post("/api/transcriptions/workspace", headers=headers).json()["project"]
    db = SessionLocal()
    try:
        owner = db.execute(select(User).where(User.email == email)).scalar_one()
        source = Source(
            project_id=workspace["id"],
            source_type=SourceType.local_upload,
            original_filename="meeting.wav",
            mime_type="audio/wav",
            size_bytes=1024,
            s3_bucket="private-test-bucket",
            s3_object_key="private/test/source",
            upload_status=SourceUploadStatus.uploaded,
            uploaded_at=utcnow(),
            source_created_at=utcnow() - timedelta(days=1),
            source_created_at_provenance="embedded_media_metadata",
            expires_at=utcnow() + timedelta(days=1),
        )
        db.add(source)
        db.commit()
        source_id = source.id
        owner_id = owner.id
    finally:
        db.close()
    created = client.post(
        f"/api/projects/{workspace['id']}/audio-preparations",
        headers=headers,
        json={
            "title": "Обработанная встреча",
            "source_ids": [source_id],
            "ephemeral_source_ids": [source_id],
            "manual_order": True,
            "options": {"preset": "processing_only", "output_format": "wav"},
            "output_destination": "download",
            "output_drive_folder_id": None,
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["status"] == "preview_queued"
    assert payload["inputs"] == [{"position": 0, "filename": "meeting.wav", "source_type": "local_upload", "ephemeral_reference": True}]
    assert "private-test-bucket" not in created.text
    assert "private/test/source" not in created.text
    listed = client.get(f"/api/projects/{workspace['id']}/audio-preparations")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()["jobs"]] == [payload["id"]]
    assert client.get(f"/api/audio-preparations/{payload['id']}").status_code == 200
    assert client.post(f"/api/audio-preparations/{payload['id']}/start", headers=headers).status_code == 409
    other_email = "audio-preparation-other@example.com"
    other_password = admin(other_email)
    other_client = TestClient(app)
    login(other_client, other_password, other_email)
    assert other_client.get(f"/api/audio-preparations/{payload['id']}").status_code == 404
    trim_path = f"/api/audio-preparations/{payload['id']}/trim"
    trim = {"start_seconds": 10.25, "end_seconds": 40.5, "output_format": "flac"}
    assert client.patch(trim_path, json=trim, headers={"origin": "https://studio.test"}).status_code == 403
    with SessionLocal() as state:
        job = state.get(AudioPreparationJob, payload["id"])
        job.status = AudioPreparationStatus.preview_ready
        job.current_stage = "preview_ready"
        job.total_input_duration_ms = 60_000
        job.estimated_output_duration_ms = 60_000
        job.copy_compatible = True
        state.commit()
    assert client.patch(trim_path, json={**trim, "end_seconds": 70}, headers=headers).status_code == 422
    assert client.patch(trim_path, json={**trim, "start_seconds": True}, headers=headers).status_code == 422
    response = client.patch(trim_path, json=trim, headers=headers)
    assert response.status_code == 200
    restored = client.get(f"/api/audio-preparations/{payload['id']}").json()
    assert restored["options"]["trim_start_seconds"] == 10.25
    assert restored["options"]["trim_end_seconds"] == 40.5
    assert restored["preview"]["estimated_output_duration_seconds"] == 30.25
    other_csrf = other_client.get("/api/auth/csrf").json()["csrf_token"]
    assert other_client.patch(trim_path, json=trim, headers={"origin": "https://studio.test", "x-csrf-token": other_csrf}).status_code == 404
    db = SessionLocal()
    try:
        assert db.get(User, owner_id) is not None
        persisted = db.get(Source, source_id)
        assert persisted.expires_at <= utcnow() + timedelta(hours=24, minutes=1)
    finally:
        db.close()


def test_project_create_list_update_archive_lifecycle_and_archived_excluded():
    pw = admin(); c = TestClient(app); csrf = login(c, pw)
    r = c.post("/api/projects", json={"title": "  First project  ", "description": "  Notes  "}, headers={"origin": "https://studio.test", "x-csrf-token": csrf})
    assert r.status_code == 200
    created = r.json()
    assert created["title"] == "First project"
    assert created["description"] == "Notes"
    assert "owner_user_id" not in created
    assert created["archived_at"] is None

    r = c.patch(f"/api/projects/{created['id']}", json={"title": "Renamed", "description": ""}, headers={"origin": "https://studio.test", "x-csrf-token": csrf})
    assert r.status_code == 200
    assert r.json()["title"] == "Renamed"
    assert r.json()["description"] is None
    assert "owner_user_id" not in r.json()

    r = c.get("/api/projects")
    assert r.status_code == 200
    assert [p["id"] for p in r.json()["projects"]] == [created["id"]]
    assert all("owner_user_id" not in project for project in r.json()["projects"])

    r = c.post(f"/api/projects/{created['id']}/archive", headers={"origin": "https://studio.test", "x-csrf-token": csrf})
    assert r.status_code == 200
    assert c.get("/api/projects").json()["projects"] == []
    assert c.patch(f"/api/projects/{created['id']}", json={"title": "Nope"}, headers={"origin": "https://studio.test", "x-csrf-token": csrf}).status_code == 404


def test_project_ownership_isolation_between_users():
    pw1 = admin("owner@example.com")
    pw2 = admin("other@example.com")
    c1 = TestClient(app); c2 = TestClient(app)
    csrf1 = login(c1, pw1, "owner@example.com")
    csrf2 = login(c2, pw2, "other@example.com")
    r = c1.post("/api/projects", json={"title": "Owner only"}, headers={"origin": "https://studio.test", "x-csrf-token": csrf1})
    pid = r.json()["id"]
    assert c2.get("/api/projects").json()["projects"] == []
    assert c2.patch(f"/api/projects/{pid}", json={"title": "Stolen"}, headers={"origin": "https://studio.test", "x-csrf-token": csrf2}).status_code == 404
    assert c2.post(f"/api/projects/{pid}/archive", headers={"origin": "https://studio.test", "x-csrf-token": csrf2}).status_code == 404
    assert c1.get("/api/projects").json()["projects"][0]["title"] == "Owner only"


def test_project_validation_failures():
    pw = admin(); c = TestClient(app); csrf = login(c, pw)
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    assert c.post("/api/projects", json={"title": "   "}, headers=headers).status_code == 422
    assert c.post("/api/projects", json={"title": "x" * 161}, headers=headers).status_code == 422
    assert c.post("/api/projects", json={"title": "Ok", "description": "x" * 2001}, headers=headers).status_code == 422


def test_project_pages_are_stable_signed_owner_and_surface_bound():
    email = "project-pages@example.com"
    pw = admin(email)
    client = TestClient(app)
    login(client, pw, email)
    timestamp = (utcnow() + timedelta(days=1)).replace(microsecond=0)
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.email == email).one()
        rows = [
            Project(
                id=str(uuid.uuid4()),
                owner_user_id=owner.id,
                title=f"Page {index}",
                created_at=timestamp,
                updated_at=timestamp,
            )
            for index in range(4)
        ]
        db.add_all(rows)
        db.commit()
        expected = sorted((row.id for row in rows), reverse=True)
    finally:
        db.close()

    first = client.get("/api/projects", params={"page_size": 2})
    assert first.status_code == 200
    first_body = first.json()
    assert [row["id"] for row in first_body["projects"]] == expected[:2]
    assert first_body["page_size"] == 2
    assert isinstance(first_body["next_cursor"], str)

    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.email == email).one()
        db.add(
            Project(
                owner_user_id=owner.id,
                title="Concurrent newer",
                created_at=timestamp + timedelta(minutes=1),
                updated_at=timestamp + timedelta(minutes=1),
            )
        )
        db.commit()
    finally:
        db.close()

    second = client.get(
        "/api/projects",
        params={"page_size": 2, "cursor": first_body["next_cursor"]},
    )
    assert second.status_code == 200
    assert [row["id"] for row in second.json()["projects"]] == expected[2:]
    assert not (
        {row["id"] for row in first_body["projects"]}
        & {row["id"] for row in second.json()["projects"]}
    )

    other_email = "project-pages-other@example.com"
    other_client = TestClient(app)
    login(other_client, admin(other_email), other_email)
    assert other_client.get(
        "/api/projects",
        params={"cursor": first_body["next_cursor"]},
    ).status_code == 422
    assert client.get(
        "/api/audit-events",
        params={"cursor": first_body["next_cursor"]},
    ).status_code == 422


def test_source_job_and_audit_pages_are_non_overlapping_and_scope_bound():
    email = "collection-pages@example.com"
    pw = admin(email)
    client = TestClient(app)
    login(client, pw, email)
    timestamp = (utcnow() + timedelta(days=1)).replace(microsecond=0)
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.email == email).one()
        project = Project(owner_user_id=owner.id, title="Paged collection")
        other_project = Project(owner_user_id=owner.id, title="Other scope")
        db.add_all([project, other_project])
        db.flush()
        sources = [
            Source(
                id=str(uuid.uuid4()),
                project_id=project.id,
                source_type=SourceType.google_drive,
                original_filename=f"source-{index}.mp3",
                upload_status=SourceUploadStatus.uploaded,
                created_at=timestamp,
                updated_at=timestamp,
            )
            for index in range(3)
        ]
        jobs = [
            TranscriptionJob(
                id=str(uuid.uuid4()),
                project_id=project.id,
                owner_user_id=owner.id,
                status=JobStatus.queued,
                created_at=timestamp,
                updated_at=timestamp,
            )
            for _index in range(3)
        ]
        events = [
            AuditEvent(
                id=str(uuid.uuid4()),
                subject_user_id=owner.id,
                event_type=f"page.event.{index}",
                trace_id=f"trace_{index:016d}",
                metadata_json="{}",
                created_at=timestamp,
            )
            for index in range(3)
        ]
        db.add_all([*sources, *jobs, *events])
        db.commit()
        project_id = project.id
        other_project_id = other_project.id
        expected_sources = sorted((row.id for row in sources), reverse=True)
        expected_jobs = sorted((row.id for row in jobs), reverse=True)
        expected_events = sorted((row.id for row in events), reverse=True)
    finally:
        db.close()

    for path, key, expected in (
        (f"/api/projects/{project_id}/sources", "sources", expected_sources),
        (f"/api/projects/{project_id}/jobs", "jobs", expected_jobs),
        ("/api/audit-events", "events", expected_events),
    ):
        first = client.get(path, params={"page_size": 2})
        assert first.status_code == 200
        first_body = first.json()
        assert [row["id"] for row in first_body[key]] == expected[:2]
        second = client.get(
            path,
            params={"page_size": 2, "cursor": first_body["next_cursor"]},
        )
        assert second.status_code == 200
        second_ids = [row["id"] for row in second.json()[key]]
        assert second_ids[: len(expected[2:])] == expected[2:]
        assert not ({row["id"] for row in first_body[key]} & set(second_ids))
        if key != "events":
            assert second.json()["next_cursor"] is None
        else:
            returned = [*first_body["events"], *second.json()["events"]]
            by_id = {row["id"]: row for row in returned}
            for event in events:
                assert by_id[event.id]["trace_id"] == event.trace_id

    source_cursor = client.get(
        f"/api/projects/{project_id}/sources", params={"page_size": 2}
    ).json()["next_cursor"]
    assert client.get(
        f"/api/projects/{other_project_id}/sources",
        params={"cursor": source_cursor},
    ).status_code == 422

class FakeStorage:
    def __init__(self):
        self.deleted = []
        self.head_calls = []
        self.head_size = 10
        self.head_type = "audio/mpeg"
        self.missing = False
        self.multipart_parts = []
        self.signed_lengths = []
        self.multipart_completed = []
        self.multipart_aborted = []
    def presigned_put_url(self, key, content_type, expires_seconds, size_bytes):
        self.signed_lengths.append(("single", size_bytes))
        return f"https://upload.test/{key}?signature=fake"
    def head_object(self, key):
        self.head_calls.append(key)
        if self.missing:
            raise FileNotFoundError(key)
        from studio_api.source_storage import ObjectHead
        return ObjectHead(size_bytes=self.head_size, content_type=self.head_type)
    def create_multipart_upload(self, key, content_type):
        return "multipart-session"
    def presigned_upload_part_url(self, key, upload_id, part_number, expires_seconds, size_bytes):
        self.signed_lengths.append((part_number, size_bytes))
        return f"https://upload.test/part/{part_number}?signature=fake"
    def list_multipart_parts(self, key, upload_id):
        return tuple(self.multipart_parts)
    def complete_multipart_upload(self, key, upload_id, parts):
        self.multipart_completed.append((key, upload_id, tuple(parts)))
    def abort_multipart_upload(self, key, upload_id):
        self.multipart_aborted.append((key, upload_id))
    def multipart_upload_absent(self, key, upload_id):
        return (key, upload_id) in self.multipart_aborted
    def delete_object(self, key, *, bucket=None):
        self.deleted.append((bucket, key))
    def delete_object_verified(self, key, *, bucket=None):
        self.delete_object(key, bucket=bucket)
        return True


def enable_fake_storage(monkeypatch):
    from studio_api import main as main_mod
    fake = FakeStorage()
    main_mod.settings.source_s3_endpoint_url = "https://r2.example"
    main_mod.settings.source_s3_region = "auto"
    main_mod.settings.source_s3_bucket = "studio-temp"
    main_mod.settings.source_s3_access_key_id_file = "/tmp/no-secret-id"
    main_mod.settings.source_s3_secret_access_key_file = "/tmp/no-secret-key"
    main_mod.settings.source_s3_lifecycle_rule_id = "transcription-reference-retention"
    main_mod.settings.audio_reference_s3_endpoint_url = "https://r2.example"
    main_mod.settings.audio_reference_s3_region = "auto"
    main_mod.settings.audio_reference_s3_bucket = "studio-audio"
    main_mod.settings.audio_reference_s3_access_key_id_file = "/tmp/no-audio-secret-id"
    main_mod.settings.audio_reference_s3_secret_access_key_file = "/tmp/no-audio-secret-key"
    main_mod.settings.audio_reference_s3_lifecycle_rule_id = "audio-reference-retention"
    main_mod.settings.source_max_upload_bytes = 1000
    main_mod.settings.source_upload_ttl_seconds = 3600
    main_mod.settings.source_presign_ttl_seconds = 900
    monkeypatch.setattr(
        main_mod,
        "get_reference_storage",
        lambda settings, reference_class: fake,
    )
    return fake


def create_logged_in_project(email="sources@example.com"):
    pw = admin(email)
    c = TestClient(app)
    csrf = login(c, pw, email)
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    r = c.post("/api/projects", json={"title": "Sources"}, headers=headers)
    assert r.status_code == 200
    return c, headers, r.json()["id"]



def create_gdrive_source(_c, _headers, pid, name="meeting.mp4"):
    db = SessionLocal()
    try:
        src = Source(project_id=pid, source_type=SourceType.google_drive, original_filename=name, mime_type="video/mp4", size_bytes=42, drive_file_id=f"file_{name.replace('.', '_')}", drive_file_url="https://drive.google.com/file/d/file_123/view", upload_status=SourceUploadStatus.uploaded, uploaded_at=utcnow(), storage_cleanup_status=SourceStorageCleanupStatus.not_applicable)
        db.add(src); db.commit(); return src.id
    finally:
        db.close()


def prepare_legacy_job_authority(c, headers, pid):
    db = SessionLocal()
    try:
        project = db.get(Project, pid)
        project.output_drive_folder_id = "folder-test"
        project.output_drive_folder_url = "https://drive.google.com/drive/folders/folder-test"
        project.output_drive_folder_name = "Test results"
        db.commit()
    finally:
        db.close()
    r = c.post("/api/credentials", json={"provider":"elevenlabs", "label":f"legacy-{pid}", "raw_value":"test-elevenlabs-key"}, headers=headers)
    assert r.status_code == 200
    return r.json()["id"]


def add_local_source(pid, status=SourceUploadStatus.uploaded, deleted=False):
    db = SessionLocal()
    try:
        src = Source(project_id=pid, source_type=SourceType.local_upload, original_filename="local.mp3", mime_type="audio/mpeg", size_bytes=10, s3_bucket="studio-temp", s3_object_key="safe/object", upload_status=status, uploaded_at=utcnow() if status == SourceUploadStatus.uploaded else None, deleted_at=utcnow() if deleted else None, delete_reason="test" if deleted else None)
        db.add(src); db.commit(); return src.id
    finally:
        db.close()


def assert_job_response_safe(text):
    forbidden = ["raw-provider-secret", "ciphertext", "refresh-token", "oauth-state", "oauth-code", "raw_google", "presigned", "no-secret-key", "temporary-object-bytes", "safe/object"]
    lowered = text.lower()
    for value in forbidden:
        assert value.lower() not in lowered
    assert '"provider_credential_id"' not in lowered


def test_transcription_jobs_auth_and_csrf_required():
    c, headers, pid = create_logged_in_project("jobs-auth@example.com")
    sid = create_gdrive_source(c, headers, pid)
    prepare_legacy_job_authority(c, headers, pid)
    anon = TestClient(app)
    assert anon.get(f"/api/projects/{pid}/jobs").status_code == 401
    assert anon.post(f"/api/projects/{pid}/jobs", json={"source_ids":[sid]}).status_code == 401
    assert c.post(f"/api/projects/{pid}/jobs", json={"source_ids":[sid]}).status_code == 403
    r = c.post(f"/api/projects/{pid}/jobs", json={"source_ids":[sid]}, headers=headers)
    assert r.status_code == 200
    jid = r.json()["id"]
    assert anon.get(f"/api/jobs/{jid}").status_code == 401
    assert anon.post(f"/api/jobs/{jid}/cancel").status_code == 401
    assert c.post(f"/api/jobs/{jid}/cancel").status_code == 403


def test_terminal_job_dismissal_is_durable_owner_scoped_and_idempotent():
    c, headers, pid = create_logged_in_project("job-dismiss-owner@example.com")
    other, other_headers, _ = create_logged_in_project("job-dismiss-other@example.com")
    db = SessionLocal()
    try:
        project = db.get(Project, pid)
        terminal = TranscriptionJob(
            project_id=pid,
            owner_user_id=project.owner_user_id,
            status=JobStatus.completed,
            finished_at=utcnow(),
        )
        active = TranscriptionJob(
            project_id=pid,
            owner_user_id=project.owner_user_id,
            status=JobStatus.processing,
        )
        db.add_all([terminal, active])
        db.commit()
        terminal_id, active_id = terminal.id, active.id
    finally:
        db.close()

    before = c.get(f"/api/projects/{pid}/jobs").json()["jobs"]
    assert next(job for job in before if job["id"] == terminal_id)[
        "terminal_dismissed_at"
    ] is None
    assert c.post(f"/api/jobs/{terminal_id}/dismiss").status_code == 403
    assert other.post(
        f"/api/jobs/{terminal_id}/dismiss", headers=other_headers
    ).status_code == 404
    assert c.post(f"/api/jobs/{active_id}/dismiss", headers=headers).status_code == 409

    first = c.post(f"/api/jobs/{terminal_id}/dismiss", headers=headers)
    assert first.status_code == 200
    dismissed_at = first.json()["terminal_dismissed_at"]
    assert dismissed_at
    second = c.post(f"/api/jobs/{terminal_id}/dismiss", headers=headers)
    assert second.status_code == 200
    assert second.json()["terminal_dismissed_at"] == dismissed_at
    after = c.get(f"/api/projects/{pid}/jobs").json()["jobs"]
    assert next(job for job in after if job["id"] == terminal_id)[
        "terminal_dismissed_at"
    ] == dismissed_at


def test_legacy_job_selects_sole_active_elevenlabs_credential_for_blank_id():
    c, headers, pid = create_logged_in_project("jobs-blank-credential@example.com")
    sid = create_gdrive_source(c, headers, pid)
    missing_authority = c.post(f"/api/projects/{pid}/jobs", json={"source_ids":[sid]}, headers=headers)
    assert missing_authority.status_code == 422
    assert missing_authority.json()["detail"] == "Выберите папку Google Drive для результатов."
    db = SessionLocal()
    try:
        assert db.query(TranscriptionJob).filter_by(project_id=pid).count() == 0
    finally:
        db.close()
    credential_id = prepare_legacy_job_authority(c, headers, pid)
    for value in ["", "   "]:
        r = c.post(f"/api/projects/{pid}/jobs", json={"source_ids":[sid], "provider_credential_id":value}, headers=headers)
        assert r.status_code == 200
        assert app.openapi()["paths"][f"/api/projects/{{project_id}}/jobs"]["post"]["deprecated"] is True
        assert "provider_credential_id" not in r.json()
        assert r.json()["output_folder"] == {"name":"Test results", "web_view_url":"https://drive.google.com/drive/folders/folder-test"}
        assert r.headers["deprecation"] == "true"
        assert r.headers["link"] == f'</api/projects/{pid}/jobs/batch>; rel="successor-version"'
        assert_job_response_safe(r.text)
        assert "raw-provider-secret" not in r.text


def test_legacy_create_job_rejects_openai_and_preserves_source_order_and_safe_metadata():
    c, headers, pid = create_logged_in_project("jobs-create@example.com")
    sid1 = create_gdrive_source(c, headers, pid, "first.mp4")
    sid2 = add_local_source(pid)
    raw = "raw-provider-secret"
    openai_cred = c.post("/api/credentials", json={"provider":"openai", "label":"jobs-openai", "raw_value":raw}, headers=headers).json()["id"]
    cred = prepare_legacy_job_authority(c, headers, pid)
    rejected = c.post(f"/api/projects/{pid}/jobs", json={"source_ids":[sid1, sid2], "provider_credential_id":openai_cred}, headers=headers)
    assert rejected.status_code == 422
    r = c.post(f"/api/projects/{pid}/jobs", json={"source_ids":[sid1, sid2], "provider_credential_id":cred, "title":" Batch ", "language":"EN_us", "options":{"diarize":False}}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "queued"
    assert body["source_count"] == 2
    assert body["usage_cost"] == {
        "accounting_status": "not_started",
        "confirmed_billed_duration_seconds": None,
        "confirmed_provider_cost": None,
        "currency": None,
        "cost_basis": None,
        "rate_snapshot": None,
    }
    assert body["language_mode"] == "en_us"
    assert body["diarization_enabled"] is False
    assert [s["id"] for s in body["sources"]] == [sid1, sid2]
    assert [s["position"] for s in body["sources"]] == [0, 1]
    assert "provider_credential_id" not in body
    assert "drive_file_url" not in body["sources"][0]
    assert_job_response_safe(r.text)
    assert raw not in r.text
    detail = c.get(f"/api/jobs/{body['id']}")
    assert detail.status_code == 200
    assert [s["id"] for s in detail.json()["sources"]] == [sid1, sid2]
    blocked_delete = c.delete(f"/api/sources/{sid1}", headers=headers)
    assert blocked_delete.status_code == 409
    assert blocked_delete.json()["detail"]["reason"] == "queued_job_uses_source"
    active_sources = c.get(f"/api/projects/{pid}/sources")
    assert active_sources.status_code == 200
    assert sid1 in [s["id"] for s in active_sources.json()["sources"]]
    db = SessionLocal()
    try:
        src = db.get(Source, sid1)
        queued = db.get(TranscriptionJob, body["id"])
        assert src.deleted_at is None
        assert src.upload_status == SourceUploadStatus.uploaded
        assert queued.status == JobStatus.queued
        assert queued.language == "en_us"
        assert queued.provider_credential_id == cred
    finally:
        db.close()

    cancel = c.post(f"/api/jobs/{body['id']}/cancel", headers=headers)
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"
    deleted = c.delete(f"/api/sources/{sid1}", headers=headers)
    assert deleted.status_code == 200
    assert sid1 not in [s["id"] for s in c.get(f"/api/projects/{pid}/sources").json()["sources"]]
    historical = c.get(f"/api/jobs/{body['id']}")
    assert historical.status_code == 200
    assert [s["id"] for s in historical.json()["sources"]] == [sid1, sid2]
    first_source = historical.json()["sources"][0]
    assert first_source["upload_status"] == "deleted"
    assert first_source["original_filename"] == "first.mp4"
    assert "drive_file_id" not in first_source
    assert "s3_bucket" not in first_source
    assert "s3_object_key" not in first_source
    listed = c.get(f"/api/projects/{pid}/jobs")
    assert listed.status_code == 200 and listed.json()["jobs"][0]["id"] == body["id"]



def test_legacy_job_creation_queues_without_processing_inline():
    c, headers, pid = create_logged_in_project("jobs-record-only@example.com")
    sid = create_gdrive_source(c, headers, pid)
    prepare_legacy_job_authority(c, headers, pid)
    r = c.post(f"/api/projects/{pid}/jobs", json={"source_ids":[sid]}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "queued"
    assert body["started_at"] is None
    assert body["finished_at"] is None
    assert body["cancelled_at"] is None
    assert body["error_code"] is None
    assert body["error_message"] is None
    assert "output" not in body
    assert "transcript" not in r.text.lower()
    assert "google_doc" not in r.text.lower()
    assert_job_response_safe(r.text)


def test_job_failure_metadata_response_redacts_sensitive_internal_values():
    c, headers, pid = create_logged_in_project("jobs-failure-safe@example.com")
    sid = create_gdrive_source(c, headers, pid)
    prepare_legacy_job_authority(c, headers, pid)
    jid = c.post(f"/api/projects/{pid}/jobs", json={"source_ids":[sid]}, headers=headers).json()["id"]
    db = SessionLocal()
    try:
        job = db.get(TranscriptionJob, jid)
        job.status = JobStatus.failed
        job.error_code = "raw_provider_token"
        job.error_message = "Provider returned bearer token, transcript body, and /run/secrets/file-mounted-value"
        job.finished_at = utcnow()
        db.commit()
    finally:
        db.close()

    detail = c.get(f"/api/jobs/{jid}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "failed"
    assert body["error_code"] == "Недоступно"
    assert body["error_message"] == "Недоступно"
    assert "bearer" not in detail.text.lower()
    assert "transcript body" not in detail.text.lower()
    assert "file-mounted" not in detail.text.lower()
    assert_job_response_safe(detail.text)


def test_cancel_only_transitions_queued_jobs_and_leaves_terminal_jobs_unchanged():
    c, headers, pid = create_logged_in_project("jobs-cancel-terminal@example.com")
    queued_sid = create_gdrive_source(c, headers, pid, "queued.mp4")
    completed_sid = create_gdrive_source(c, headers, pid, "completed.mp4")
    failed_sid = create_gdrive_source(c, headers, pid, "failed.mp4")
    prepare_legacy_job_authority(c, headers, pid)
    queued_id = c.post(f"/api/projects/{pid}/jobs", json={"source_ids":[queued_sid]}, headers=headers).json()["id"]
    completed_id = c.post(f"/api/projects/{pid}/jobs", json={"source_ids":[completed_sid]}, headers=headers).json()["id"]
    failed_id = c.post(f"/api/projects/{pid}/jobs", json={"source_ids":[failed_sid]}, headers=headers).json()["id"]

    db = SessionLocal()
    try:
        completed = db.get(TranscriptionJob, completed_id)
        completed.status = JobStatus.completed
        completed.finished_at = utcnow()
        failed = db.get(TranscriptionJob, failed_id)
        failed.status = JobStatus.failed
        failed.finished_at = utcnow()
        failed.error_code = "provider_unavailable"
        failed.error_message = "Provider unavailable"
        db.commit()
    finally:
        db.close()

    assert c.post(f"/api/jobs/{queued_id}/cancel", headers=headers).json()["status"] == "cancelled"
    completed_cancel = c.post(f"/api/jobs/{completed_id}/cancel", headers=headers)
    failed_cancel = c.post(f"/api/jobs/{failed_id}/cancel", headers=headers)
    assert completed_cancel.status_code == 200
    assert failed_cancel.status_code == 200
    assert completed_cancel.json()["status"] == "completed"
    assert completed_cancel.json()["cancelled_at"] is None
    assert failed_cancel.json()["status"] == "failed"
    assert failed_cancel.json()["cancelled_at"] is None
    assert failed_cancel.json()["error_message"] == "Provider unavailable"

    db = SessionLocal()
    try:
        events = [e.event_type for e in db.query(AuditEvent).filter(AuditEvent.event_type == "job.cancelled").all()]
        assert events == ["job.cancelled"]
    finally:
        db.close()

def test_create_job_rejects_invalid_source_sets_and_archived_project():
    c, headers, pid = create_logged_in_project("jobs-invalid@example.com")
    sid = create_gdrive_source(c, headers, pid)
    assert c.post(f"/api/projects/{pid}/jobs", json={"source_ids":[]}, headers=headers).status_code == 422
    assert c.post(f"/api/projects/{pid}/jobs", json={"source_ids":[sid, sid]}, headers=headers).status_code == 422
    c2, h2, pid2 = create_logged_in_project("jobs-other@example.com")
    sid_other = create_gdrive_source(c2, h2, pid2)
    assert c.post(f"/api/projects/{pid}/jobs", json={"source_ids":[sid_other]}, headers=headers).status_code == 422
    db = SessionLocal(); src = db.get(Source, sid); src.deleted_at = utcnow(); src.upload_status = SourceUploadStatus.deleted; db.commit(); db.close()
    assert c.post(f"/api/projects/{pid}/jobs", json={"source_ids":[sid]}, headers=headers).status_code == 422
    c.post(f"/api/projects/{pid}/archive", headers=headers)
    assert c.post(f"/api/projects/{pid}/jobs", json={"source_ids":[sid]}, headers=headers).status_code == 404


def test_create_job_rejects_unusable_local_upload_statuses():
    for status in [SourceUploadStatus.pending, SourceUploadStatus.expired, SourceUploadStatus.deleted, SourceUploadStatus.failed]:
        c, headers, pid = create_logged_in_project(f"jobs-{status.value}@example.com")
        sid = add_local_source(pid, status=status, deleted=(status == SourceUploadStatus.deleted))
        r = c.post(f"/api/projects/{pid}/jobs", json={"source_ids":[sid]}, headers=headers)
        assert r.status_code == 422


def test_job_list_owner_scope_and_cancel_idempotent_with_audit():
    c1, h1, pid1 = create_logged_in_project("jobs-owner1@example.com")
    c2, h2, pid2 = create_logged_in_project("jobs-owner2@example.com")
    sid1 = create_gdrive_source(c1, h1, pid1)
    sid2 = create_gdrive_source(c2, h2, pid2)
    prepare_legacy_job_authority(c1, h1, pid1)
    prepare_legacy_job_authority(c2, h2, pid2)
    jid1 = c1.post(f"/api/projects/{pid1}/jobs", json={"source_ids":[sid1]}, headers=h1).json()["id"]
    jid2 = c2.post(f"/api/projects/{pid2}/jobs", json={"source_ids":[sid2]}, headers=h2).json()["id"]
    assert [j["id"] for j in c1.get(f"/api/projects/{pid1}/jobs").json()["jobs"]] == [jid1]
    assert c1.get(f"/api/jobs/{jid2}").status_code == 404
    assert c1.post(f"/api/jobs/{jid2}/cancel", headers=h1).status_code == 404
    r1 = c1.post(f"/api/jobs/{jid1}/cancel", headers=h1)
    r2 = c1.post(f"/api/jobs/{jid1}/cancel", headers=h1)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["status"] == "cancelled" and r2.json()["status"] == "cancelled"
    assert r1.json()["cancelled_at"] is not None
    db = SessionLocal()
    try:
        events = [e.event_type for e in db.query(AuditEvent).order_by(AuditEvent.created_at).all()]
        assert "job.created" in events and "job.cancelled" in events
        assert events.count("job.cancelled") == 1
    finally:
        db.close()

def test_project_patch_rejects_unverified_output_folder_binding_fields():
    c, headers, pid = create_logged_in_project("folder@example.com")
    r = c.patch(f"/api/projects/{pid}", json={"title": " Renamed ", "description": " Safe metadata "}, headers=headers)
    assert r.status_code == 200
    assert r.json()["title"] == "Renamed"
    assert r.json()["description"] == "Safe metadata"
    for payload in [
        {"output_drive_folder_id": "abc_123-XYZ"},
        {"output_drive_folder_url": "https://drive.google.com/drive/folders/abc_123-XYZ"},
        {"output_drive_folder_name": "Results"},
        {"unexpected_project_field": "ignored-before-hardening"},
    ]:
        assert c.patch(f"/api/projects/{pid}", json=payload, headers=headers).status_code == 422
    project = next(item for item in c.get("/api/projects").json()["projects"] if item["id"] == pid)
    assert project["output_drive_folder_id"] is None
    assert project["output_drive_folder_url"] is None
    assert project["output_drive_folder_name"] is None




def test_source_display_filename_normalization_preserves_unicode_and_extension():
    from studio_api.source_storage import attachment_content_disposition, normalize_source_display_filename
    cyrillic = "Лекция 1. Личность как психологическое явление.flac"
    assert normalize_source_display_filename(cyrillic) == cyrillic
    assert normalize_source_display_filename(" Mix Лекция-01_(draft).mp3 ") == "Mix Лекция-01_(draft).mp3"
    assert normalize_source_display_filename("../дир/файл.mp3") == ".._дир_файл.mp3"
    assert normalize_source_display_filename("bad\nname\r\x00.mp3") == "badname.mp3"
    assert normalize_source_display_filename("\x00\n") == "source"
    long_name = "Л" * 300 + ".flac"
    normalized = normalize_source_display_filename(long_name)
    assert len(normalized) == 255
    assert normalized.endswith(".flac")
    disposition = attachment_content_disposition("Обработанное аудио.flac")
    assert 'filename="download.flac"' in disposition
    assert "filename*=UTF-8''%D0%9E%D0%B1%D1%80%D0%B0%D0%B1%D0%BE%D1%82%D0%B0%D0%BD%D0%BD%D0%BE%D0%B5%20%D0%B0%D1%83%D0%B4%D0%B8%D0%BE.flac" in disposition

def test_google_drive_source_metadata_lifecycle_owner_scoped(monkeypatch):
    import studio_api.main as main_mod
    from studio_api.google_drive import GoogleDriveMetadata

    def fail_storage(*_args, **_kwargs):
        raise AssertionError("Google Drive source removal must not delete Studio storage")

    monkeypatch.setattr(main_mod, "get_reference_storage", fail_storage)
    c, headers, pid = create_logged_in_project("gdrive@example.com")
    db = SessionLocal()
    user_id = db.query(User).filter_by(email="gdrive@example.com").one().id
    db.close()
    _connect_google_for_test(user_id)
    monkeypatch.setattr(
        "studio_api.google_connection_access.refresh_user_google_drive_access_token", lambda *a, **k: "access"
    )
    metadata = {
        "file_123": GoogleDriveMetadata(
            "file_123",
            "Лекция 1. Личность как психологическое явление.flac",
            "audio/flac",
            42,
            "https://drive.google.com/file/d/file_123/view",
            "2025-12-01T10:20:30Z",
            "2025-12-02T11:21:31Z",
            False,
        ),
        "file_456": GoogleDriveMetadata(
            "file_456",
            "active.mp4",
            "video/mp4",
            43,
            "https://drive.google.com/file/d/file_456/view",
            "2025-12-02T11:21:31Z",
            None,
            False,
        ),
    }
    monkeypatch.setattr(
        "studio_api.google_drive.fetch_drive_file_metadata",
        lambda token, drive_file_id: metadata[drive_file_id],
    )
    r = c.post(
        f"/api/projects/{pid}/sources/google-picker",
        json={"file_ids": ["file_123"]},
        headers=headers,
    )
    assert r.status_code == 200
    created = r.json()["sources"][0]
    sid = created["id"]
    assert created["source_type"] == "google_drive"
    assert created["original_filename"] == "Лекция 1. Личность как психологическое явление.flac"
    assert "s3" not in r.text.lower()
    r2 = c.post(
        f"/api/projects/{pid}/sources/google-picker",
        json={"file_ids": ["file_456"]},
        headers=headers,
    )
    assert r2.status_code == 200
    active_sid = r2.json()["sources"][0]["id"]
    assert [s["id"] for s in c.get(f"/api/projects/{pid}/sources").json()["sources"]] == [active_sid, sid]
    assert c.delete(f"/api/sources/{sid}", headers=headers).status_code == 200
    assert [s["id"] for s in c.get(f"/api/projects/{pid}/sources").json()["sources"]] == [active_sid]
    db = SessionLocal(); src = db.get(Source, sid); db.close()
    assert src is not None
    assert src.deleted_at is not None
    assert src.upload_status == SourceUploadStatus.deleted
    assert src.drive_file_id == "file_123"
    assert c.delete(f"/api/sources/{sid}", headers=headers).status_code == 200


def test_selected_bulk_cleanup_deletes_only_confirmed_subset_and_rejects_replay():
    client, headers, project_id = create_logged_in_project("selected-cleanup@example.com")
    selected_id=create_gdrive_source(client,headers,project_id,"selected-synthetic.mp4")
    untouched_id=create_gdrive_source(client,headers,project_id,"untouched-synthetic.mp4")
    path=f"/api/projects/{project_id}/sources/bulk-deletion"
    preview=client.get(f"{path}/preview",params={"source_ids":[selected_id]})
    assert preview.status_code==200
    payload=preview.json()
    assert payload["eligible_count"]==1 and payload["listed_count"]==1
    body={"confirm_delete":True,"source_ids":[selected_id],"expected_preview_token":payload["preview_token"],"expected_eligible_count":1,"expected_blocked_count":0}
    assert client.post(path,json=body).status_code==403
    applied=client.post(path,json=body,headers=headers)
    assert applied.status_code==200
    assert applied.json()["deleted_count"]==1 and applied.json()["google_drive_files_deleted"]==0
    with SessionLocal() as db:
        assert db.get(Source,selected_id).deleted_at is not None
        assert db.get(Source,untouched_id).deleted_at is None
        assert db.get(Source,selected_id).drive_file_id is not None
    assert client.post(path,json=body,headers=headers).status_code==409


def test_bulk_source_deletion_is_owner_scoped_confirmed_and_drive_safe():
    client, headers, project_id = create_logged_in_project(
        "bulk-source-delete@example.com"
    )
    other, other_headers, _ = create_logged_in_project(
        "bulk-source-delete-other@example.com"
    )
    drive_source_id = create_gdrive_source(
        client, headers, project_id, "bulk-drive.mp4"
    )
    blocked_source_id = create_gdrive_source(
        client, headers, project_id, "bulk-blocked.mp4"
    )
    local_source_id = add_local_source(project_id)
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        blocking_job = TranscriptionJob(
            project_id=project_id,
            owner_user_id=project.owner_user_id,
            status=JobStatus.queued,
        )
        db.add(blocking_job)
        db.flush()
        db.add(
            TranscriptionJobSource(
                job_id=blocking_job.id,
                source_id=blocked_source_id,
                position=0,
                status=JobSourceStatus.queued,
            )
        )
        db.commit()

    path = f"/api/projects/{project_id}/sources/bulk-deletion"
    assert TestClient(app).get(f"{path}/preview").status_code == 401
    assert other.get(f"{path}/preview").status_code == 404
    preview = client.get(f"{path}/preview")
    assert preview.status_code == 200
    preview_payload = preview.json()
    assert len(preview_payload.pop("preview_token")) == 64
    assert preview_payload == {
        "eligible_count": 2,
        "listed_count": 3,
        "hidden_expired_count": 0,
        "eligible_bytes": 52,
        "eligible_unknown_size_count": 0,
        "blocked_count": 1,
        "blocked_bytes": 42,
        "blocked_unknown_size_count": 0,
        "blocked_reasons": {"queued_job_uses_source": 1},
        "google_drive_files_deleted": 0,
    }
    confirmation = {
        "confirm_delete": True,
        "expected_preview_token": preview.json()["preview_token"],
        "expected_eligible_count": 2,
        "expected_blocked_count": 1,
    }
    selected = client.get(f"{path}/preview", params={"source_ids": [drive_source_id]})
    assert selected.status_code == 200
    assert selected.json()["eligible_count"] == 1
    assert selected.json()["blocked_count"] == 0
    assert selected.json()["preview_token"] != confirmation["expected_preview_token"]
    # A selected preview must not authorize a whole-project mutation.
    widened = client.post(path, json={
        "confirm_delete": True,
        "expected_preview_token": selected.json()["preview_token"],
        "expected_eligible_count": 1,
        "expected_blocked_count": 0,
    }, headers=headers)
    assert widened.status_code == 409
    assert client.get(f"{path}/preview", params=[("source_ids", drive_source_id), ("source_ids", drive_source_id)]).status_code == 422
    assert client.post(path, json=confirmation).status_code == 403
    assert client.post(
        path,
        json={**confirmation, "confirm_delete": False},
        headers=headers,
    ).status_code == 422
    assert other.post(path, json=confirmation, headers=other_headers).status_code == 404
    changed = client.post(
        path,
        json={**confirmation, "expected_eligible_count": 3},
        headers=headers,
    )
    assert changed.status_code == 409
    assert changed.json()["detail"]["reason"] == "preview_changed"
    same_counts_stale_snapshot = client.post(
        path,
        json={**confirmation, "expected_preview_token": "f" * 64},
        headers=headers,
    )
    assert same_counts_stale_snapshot.status_code == 409
    assert same_counts_stale_snapshot.json()["detail"]["reason"] == "preview_changed"

    applied = client.post(path, json=confirmation, headers=headers)
    assert applied.status_code == 200
    assert applied.json() == {
        "ok": True,
        "deleted_count": 2,
        "blocked_count": 1,
        "blocked_reasons": {"queued_job_uses_source": 1},
        "cleanup_counts": {"not_applicable": 1, "pending": 1},
        "google_drive_files_deleted": 0,
    }
    assert client.post(path, json=confirmation, headers=headers).status_code == 409

    with SessionLocal() as db:
        drive_source = db.get(Source, drive_source_id)
        local_source = db.get(Source, local_source_id)
        blocked_source = db.get(Source, blocked_source_id)
        assert drive_source.drive_file_id is not None
        assert drive_source.upload_status == SourceUploadStatus.deleted
        assert drive_source.storage_cleanup_status == SourceStorageCleanupStatus.not_applicable
        assert local_source.upload_status == SourceUploadStatus.deleted
        assert local_source.storage_cleanup_status == SourceStorageCleanupStatus.pending
        assert blocked_source.deleted_at is None
        event = db.query(AuditEvent).filter_by(
            event_type="source.bulk_deletion_completed"
        ).one()
        assert json.loads(event.metadata_json) == {
            "blocked_count": 1,
            "deleted_count": 2,
        }


def test_local_upload_initiate_requires_auth_ownership_and_validates(monkeypatch):
    fake = enable_fake_storage(monkeypatch)
    c, headers, pid = create_logged_in_project("local@example.com")
    assert TestClient(app).post(f"/api/projects/{pid}/sources/local-upload/initiate", json={"original_filename":"a.mp3","mime_type":"audio/mpeg","size_bytes":10,"reference_class":"transcription"}).status_code == 401
    assert c.post(f"/api/projects/{pid}/sources/local-upload/initiate", json={"original_filename":"a.txt","mime_type":"text/plain","size_bytes":10,"reference_class":"transcription"}, headers=headers).status_code == 422
    assert c.post(f"/api/projects/{pid}/sources/local-upload/initiate", json={"original_filename":"a.mp3","mime_type":"audio/mpeg","size_bytes":1001,"reference_class":"transcription"}, headers=headers).status_code == 422
    r = c.post(f"/api/projects/{pid}/sources/local-upload/initiate", json={"original_filename":"../secret song.mp3","mime_type":"audio/mpeg","size_bytes":10,"reference_class":"transcription"}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["source_id"]
    assert body["upload"]["method"] == "PUT"
    assert body["upload"]["expires_in"] == 900
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["pragma"] == "no-cache"
    assert "/secret%20song" not in r.text and "secret song.mp3" not in r.text and "secret%20song.mp3" not in r.text
    assert "no-secret-id" not in r.text and "no-secret-key" not in r.text
    db = SessionLocal(); src = db.get(Source, body["source_id"]); object_key = src.s3_object_key; source_id = src.id; original_filename = src.original_filename; db.close()
    assert original_filename == ".._secret song.mp3"
    assert object_key.endswith(f"/projects/{pid}/sources/{source_id}/source")
    assert original_filename not in object_key

    unicode_name = "Лекция 1. Личность как психологическое явление.flac"
    r = c.post(f"/api/projects/{pid}/sources/local-upload/initiate", json={"original_filename": unicode_name,"mime_type":"audio/mpeg","size_bytes":10,"reference_class":"audio_processing"}, headers=headers)
    assert r.status_code == 200
    db = SessionLocal(); src = db.get(Source, r.json()["source_id"]); db.close()
    assert src.original_filename == unicode_name
    assert src.reference_class == "audio_processing"
    assert src.s3_bucket == "studio-audio"


def test_large_local_upload_uses_owner_scoped_multipart_authority(monkeypatch):
    from studio_api import main as main_mod
    from studio_api.source_storage import MultipartPart

    fake = enable_fake_storage(monkeypatch)
    part_size = 5 * 1024 * 1024
    total_size = part_size + 3
    monkeypatch.setattr(main_mod.settings, "source_max_upload_bytes", 20 * 1024 * 1024)
    monkeypatch.setattr(main_mod.settings, "source_multipart_threshold_bytes", part_size)
    monkeypatch.setattr(main_mod.settings, "source_multipart_part_size_bytes", part_size)
    c, headers, pid = create_logged_in_project("multipart-local@example.com")

    initiated = c.post(
        f"/api/projects/{pid}/sources/local-upload/initiate",
        json={
            "original_filename": "long recording.mp4",
            "mime_type": "video/mp4",
            "size_bytes": total_size,
            "reference_class": "transcription",
        },
        headers=headers,
    )
    assert initiated.status_code == 200
    body = initiated.json()
    assert body["upload"] == {
        "mode": "multipart",
        "part_size_bytes": part_size,
        "part_count": 2,
        "expires_in": 3600,
    }
    assert all(
        forbidden not in initiated.text.lower()
        for forbidden in ("bucket", "object_key", "upload_id", "multipart-session")
    )
    source_id = body["source_id"]
    db = SessionLocal()
    try:
        source = db.get(Source, source_id)
        assert source.upload_protocol == "multipart"
        assert source.multipart_upload_id == "multipart-session"
        assert source.multipart_part_count == 2
    finally:
        db.close()

    issued = c.post(
        f"/api/sources/{source_id}/local-upload/multipart/parts/2",
        headers=headers,
    )
    assert issued.status_code == 200
    assert issued.json()["part_number"] == 2
    assert fake.signed_lengths == [(2, 3)]
    assert c.post(f"/api/sources/{source_id}/local-upload/multipart/parts/1", headers=headers).status_code == 200
    assert fake.signed_lengths == [(2, 3), (1, part_size)]
    assert "multipart-session" not in issued.text
    assert c.post(
        f"/api/sources/{source_id}/local-upload/multipart/parts/3",
        headers=headers,
    ).status_code == 422
    assert c.post(
        f"/api/sources/{source_id}/local-upload/complete",
        headers=headers,
    ).status_code == 409

    fake.multipart_parts = [
        MultipartPart(1, '"one"', part_size),
        MultipartPart(2, '"two"', 3),
    ]
    status = c.get(f"/api/sources/{source_id}/local-upload/multipart/status")
    assert status.status_code == 200
    assert status.json() == {"status": "active", "uploaded_parts": [1, 2]}
    fake.head_size = total_size
    fake.head_type = "video/mp4"
    completed = c.post(
        f"/api/sources/{source_id}/local-upload/multipart/complete",
        headers=headers,
    )
    assert completed.status_code == 200
    assert completed.json()["upload_status"] == "uploaded"
    assert len(fake.multipart_completed) == 1
    db = SessionLocal()
    try:
        source = db.get(Source, source_id)
        assert source.multipart_completed_at is not None
        assert source.uploaded_at is not None
    finally:
        db.close()


def test_multipart_abort_is_durable_and_queues_verified_cleanup(monkeypatch):
    from studio_api import main as main_mod

    enable_fake_storage(monkeypatch)
    part_size = 5 * 1024 * 1024
    monkeypatch.setattr(main_mod.settings, "source_max_upload_bytes", 20 * 1024 * 1024)
    monkeypatch.setattr(main_mod.settings, "source_multipart_threshold_bytes", part_size)
    monkeypatch.setattr(main_mod.settings, "source_multipart_part_size_bytes", part_size)
    c, headers, pid = create_logged_in_project("multipart-abort@example.com")
    initiated = c.post(
        f"/api/projects/{pid}/sources/local-upload/initiate",
        json={
            "original_filename": "abandoned.mp4",
            "mime_type": "video/mp4",
            "size_bytes": part_size + 1,
            "reference_class": "audio_processing",
        },
        headers=headers,
    )
    source_id = initiated.json()["source_id"]
    aborted = c.post(
        f"/api/sources/{source_id}/local-upload/multipart/abort",
        headers=headers,
    )
    assert aborted.status_code == 200
    assert aborted.json() == {
        "ok": True,
        "source_state": "deleted",
        "storage_cleanup": "pending",
    }
    replay = c.post(
        f"/api/sources/{source_id}/local-upload/multipart/abort",
        headers=headers,
    )
    assert replay.status_code == 200
    db = SessionLocal()
    try:
        source = db.get(Source, source_id)
        assert source.delete_reason == "upload_aborted"
        assert source.storage_cleanup_status == SourceStorageCleanupStatus.pending
        assert source.storage_cleanup_not_before_at is not None
        assert source.s3_bucket == "studio-audio"
        assert source.multipart_upload_id == "multipart-session"
    finally:
        db.close()


def test_expired_local_source_is_hidden_from_active_collection_but_history_is_preserved():
    c, _headers, pid = create_logged_in_project("expired-active-source@example.com")
    db = SessionLocal()
    try:
        project = db.get(Project, pid)
        source = Source(
            project_id=pid,
            source_type=SourceType.local_upload,
            original_filename="expired.mp3",
            mime_type="audio/mpeg",
            size_bytes=10,
            s3_bucket="bucket",
            s3_object_key="private/expired",
            upload_status=SourceUploadStatus.uploaded,
            uploaded_at=utcnow() - timedelta(days=2),
            expires_at=utcnow() - timedelta(seconds=1),
        )
        db.add(source); db.flush()
        status_expired_source = Source(
            project_id=pid,
            source_type=SourceType.local_upload,
            original_filename="status-expired.mp3",
            mime_type="audio/mpeg",
            size_bytes=10,
            s3_bucket="bucket",
            s3_object_key="private/status-expired",
            upload_status=SourceUploadStatus.expired,
            uploaded_at=utcnow() - timedelta(days=2),
            expires_at=utcnow() + timedelta(days=1),
        )
        db.add(status_expired_source); db.flush()
        job = TranscriptionJob(
            project_id=pid,
            owner_user_id=project.owner_user_id,
            status=JobStatus.completed,
            provider="elevenlabs",
            finished_at=utcnow(),
        )
        db.add(job); db.flush()
        relation = TranscriptionJobSource(job_id=job.id, source_id=source.id, position=0)
        db.add(relation); db.commit()
        source_id = source.id
        status_expired_source_id = status_expired_source.id
        job_id = job.id
    finally:
        db.close()

    active = c.get(f"/api/projects/{pid}/sources")
    assert active.status_code == 200
    assert source_id not in [row["id"] for row in active.json()["sources"]]
    assert status_expired_source_id not in [row["id"] for row in active.json()["sources"]]

    history = c.get(f"/api/jobs/{job_id}")
    assert history.status_code == 200
    assert history.json()["sources"][0]["id"] == source_id
    db = SessionLocal()
    try:
        preserved = db.get(Source, source_id)
        assert preserved is not None
        assert preserved.deleted_at is None
        assert preserved.s3_object_key == "private/expired"
    finally:
        db.close()


def test_local_upload_initiate_fails_closed_without_storage(monkeypatch):
    from studio_api import main as main_mod
    c, headers, pid = create_logged_in_project("nostorage@example.com")
    main_mod.settings.source_s3_endpoint_url = None
    main_mod.settings.source_s3_bucket = None
    r = c.post(f"/api/projects/{pid}/sources/local-upload/initiate", json={"original_filename":"a.mp3","mime_type":"audio/mpeg","size_bytes":10,"reference_class":"transcription"}, headers=headers)
    assert r.status_code == 503


def test_complete_local_upload_missing_object_returns_conflict(monkeypatch):
    fake = enable_fake_storage(monkeypatch)
    c, headers, pid = create_logged_in_project("missing-object@example.com")
    r = c.post(f"/api/projects/{pid}/sources/local-upload/initiate", json={"original_filename":"missing.mp3","mime_type":"audio/mpeg","size_bytes":10,"reference_class":"transcription"}, headers=headers)
    sid = r.json()["source_id"]
    fake.missing = True
    r = c.post(f"/api/sources/{sid}/local-upload/complete", headers=headers)
    assert r.status_code == 409
    db = SessionLocal(); src = db.get(Source, sid); db.close()
    assert src.upload_status.value == "pending"
    assert src.uploaded_at is None


@pytest.mark.parametrize(
    ("head_size", "head_type", "expected_status"),
    [
        (None, "audio/mpeg", 409),
        (10, None, 409),
        (11, "audio/mpeg", 409),
        (10, "audio/wav", 409),
        (1001, "audio/mpeg", 422),
        (10, "text/plain", 422),
    ],
)
def test_complete_local_upload_requires_exact_verified_metadata(monkeypatch, head_size, head_type, expected_status):
    fake = enable_fake_storage(monkeypatch)
    fake.head_size = head_size
    fake.head_type = head_type
    size_label = "missing" if head_size is None else str(head_size)
    c, headers, pid = create_logged_in_project(f"upload-metadata-{size_label}-{expected_status}@example.com")
    initiated = c.post(
        f"/api/projects/{pid}/sources/local-upload/initiate",
        json={"original_filename":"metadata.mp3", "mime_type":"audio/mpeg", "size_bytes":10, "reference_class":"transcription"},
        headers=headers,
    )
    sid = initiated.json()["source_id"]
    pending_expires_at = initiated.json()["expires_at"]

    response = c.post(f"/api/sources/{sid}/local-upload/complete", headers=headers)

    assert response.status_code == expected_status
    db = SessionLocal()
    try:
        src = db.get(Source, sid)
        assert src.upload_status == SourceUploadStatus.pending
        assert src.uploaded_at is None
        assert src.expires_at.isoformat() == pending_expires_at
    finally:
        db.close()


def test_complete_local_upload_and_delete_owner_isolation(monkeypatch):
    fake = enable_fake_storage(monkeypatch)
    c1, h1, pid = create_logged_in_project("owner2@example.com")
    c2, h2, _ = create_logged_in_project("other2@example.com")
    r = c1.post(f"/api/projects/{pid}/sources/local-upload/initiate", json={"original_filename":"a.mp3","mime_type":"audio/mpeg","size_bytes":10,"reference_class":"transcription"}, headers=h1)
    sid = r.json()["source_id"]
    assert c2.post(f"/api/sources/{sid}/local-upload/complete", headers=h2).status_code == 404
    assert c1.post(f"/api/sources/{sid}/local-upload/complete", headers=h1).status_code == 200
    assert c2.get(f"/api/sources/{sid}").status_code == 404
    owned = c1.get(f"/api/sources/{sid}")
    assert owned.status_code == 200
    assert owned.json()["id"] == sid
    assert owned.json()["deleted_at"] is None
    assert c2.delete(f"/api/sources/{sid}", headers=h2).status_code == 404
    assert c1.delete(f"/api/sources/{sid}", headers=h1).status_code == 200
    deleted = c1.get(f"/api/sources/{sid}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted_at"] is not None
    assert c1.delete(f"/api/sources/{sid}", headers=h1).status_code == 200
    assert fake.deleted == []



@pytest.mark.parametrize(
    "mutation",
    ["deleted", "expired", "archived_project", "project_owner", "source_project", "bucket", "key"],
)
def test_complete_local_upload_revalidates_after_head_race(monkeypatch, mutation):
    fake = enable_fake_storage(monkeypatch)
    from studio_api import models as m
    from studio_api.source_storage import ObjectHead

    c, headers, pid = create_logged_in_project(f"complete-race-{mutation}@example.com")
    r = c.post(f"/api/projects/{pid}/sources/local-upload/initiate", json={"original_filename":"race.mp3","mime_type":"audio/mpeg","size_bytes":10,"reference_class":"transcription"}, headers=headers)
    sid = r.json()["source_id"]
    db = SessionLocal()
    try:
        src = db.get(Source, sid)
        original_bucket = src.s3_bucket
        original_key = src.s3_object_key
        if mutation in {"project_owner", "source_project"}:
            other = User(email=f"other-{mutation}@example.com", role=UserRole.user, status=UserStatus.active)
            db.add(other); db.flush()
            other_project = Project(owner_user_id=other.id, title="Other")
            db.add(other_project); db.flush()
            other_project_id = other_project.id
        else:
            other_project_id = None
        db.commit()
    finally:
        db.close()

    def mutate_during_head(key):
        assert key == original_key
        race_db = SessionLocal()
        try:
            src = race_db.get(Source, sid)
            if mutation == "deleted":
                src.deleted_at = utcnow(); src.upload_status = SourceUploadStatus.deleted
            elif mutation == "expired":
                src.expires_at = utcnow() - timedelta(seconds=1)
            elif mutation == "archived_project":
                race_db.get(Project, pid).archived_at = utcnow()
            elif mutation == "project_owner":
                race_db.get(Project, pid).owner_user_id = race_db.get(Project, other_project_id).owner_user_id
            elif mutation == "source_project":
                src.project_id = other_project_id
            elif mutation == "bucket":
                src.s3_bucket = "changed-bucket"
            elif mutation == "key":
                src.s3_object_key = "changed-key"
            race_db.commit()
        finally:
            race_db.close()
        return ObjectHead(size_bytes=10, content_type="audio/mpeg")

    fake.head_object = mutate_during_head
    response = c.post(f"/api/sources/{sid}/local-upload/complete", headers=headers)
    assert response.status_code == 404
    db = SessionLocal()
    try:
        src = db.get(Source, sid)
        assert src.uploaded_at is None
        if mutation not in {"deleted"}:
            assert src.upload_status != SourceUploadStatus.uploaded
    finally:
        db.close()


def test_complete_local_upload_revalidates_successful_unchanged_source(monkeypatch):
    enable_fake_storage(monkeypatch)
    c, headers, pid = create_logged_in_project("complete-race-success@example.com")
    preference = c.patch(
        "/api/account/preferences",
        json={"source_retention_ttl_seconds": 604800},
        headers=headers,
    )
    assert preference.status_code == 200
    r = c.post(f"/api/projects/{pid}/sources/local-upload/initiate", json={"original_filename":"success.mp3","mime_type":"audio/mpeg","size_bytes":10,"reference_class":"transcription"}, headers=headers)
    pending_expires_at = datetime.fromisoformat(r.json()["expires_at"])
    sid = r.json()["source_id"]
    response = c.post(f"/api/sources/{sid}/local-upload/complete", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["upload_status"] == "uploaded"
    uploaded_at = datetime.fromisoformat(body["uploaded_at"])
    retained_until = datetime.fromisoformat(body["expires_at"])
    assert retained_until - uploaded_at == timedelta(seconds=604800)
    assert retained_until > pending_expires_at
    assert "s3_bucket" not in body and "s3_object_key" not in body


def test_complete_local_upload_replay_returns_same_verified_source_without_extending_retention(monkeypatch):
    fake = enable_fake_storage(monkeypatch)
    c, headers, pid = create_logged_in_project("complete-replay@example.com")
    initiated = c.post(
        f"/api/projects/{pid}/sources/local-upload/initiate",
        json={
            "original_filename": "replay.mp3",
            "mime_type": "audio/mpeg",
            "size_bytes": 10,
            "reference_class": "transcription",
        },
        headers=headers,
    )
    sid = initiated.json()["source_id"]

    first = c.post(f"/api/sources/{sid}/local-upload/complete", headers=headers)
    assert first.status_code == 200
    first_body = first.json()
    head_calls = list(fake.head_calls)

    replay = c.post(f"/api/sources/{sid}/local-upload/complete", headers=headers)

    assert replay.status_code == 200
    assert replay.json() == first_body
    assert fake.head_calls == head_calls
    assert replay.json()["uploaded_at"] == first_body["uploaded_at"]
    assert replay.json()["expires_at"] == first_body["expires_at"]


@pytest.mark.parametrize("legacy_seconds", [3600, 86400])
def test_new_upload_normalizes_legacy_preference_without_rewriting_existing_expiry(monkeypatch, legacy_seconds):
    enable_fake_storage(monkeypatch)
    c, headers, pid = create_logged_in_project(f"legacy-retention-{legacy_seconds}@example.com")
    with SessionLocal() as db:
        user = db.get(User, db.get(Project, pid).owner_user_id)
        user.source_retention_ttl_seconds = legacy_seconds
        db.commit()
    prefs = c.get("/api/account/preferences").json()
    assert prefs["source_retention_ttl_seconds"] == 259200
    initiated = c.post(f"/api/projects/{pid}/sources/local-upload/initiate", json={
        "original_filename": "legacy.mp3", "mime_type": "audio/mpeg", "size_bytes": 10,
        "reference_class": "transcription",
    }, headers=headers)
    sid = initiated.json()["source_id"]
    completed = c.post(f"/api/sources/{sid}/local-upload/complete", headers=headers).json()
    assert datetime.fromisoformat(completed["expires_at"]) - datetime.fromisoformat(completed["uploaded_at"]) == timedelta(days=3)
    legacy_expiry = datetime.now(timezone.utc) + timedelta(seconds=legacy_seconds)
    with SessionLocal() as db:
        db.get(Source, sid).expires_at = legacy_expiry
        db.commit()
    replay = c.post(f"/api/sources/{sid}/local-upload/complete", headers=headers).json()
    assert datetime.fromisoformat(replay["expires_at"]) == legacy_expiry
    with SessionLocal() as db:
        assert db.get(User, db.get(Project, pid).owner_user_id).source_retention_ttl_seconds == legacy_seconds


@pytest.mark.parametrize("days", [3, 7, 30, None])
def test_audio_upload_has_separate_selected_retention_after_completion(monkeypatch, days):
    enable_fake_storage(monkeypatch)
    c, headers, pid = create_logged_in_project(f"audio-retention-{days}@example.com".lower())
    preference = c.patch("/api/account/preferences", json={"source_retention_ttl_seconds": 2592000}, headers=headers)
    assert preference.status_code == 200
    payload = {"original_filename": "audio.mp3", "mime_type": "audio/mpeg", "size_bytes": 10, "reference_class": "audio_processing"}
    if days is not None:
        payload["audio_retention_days"] = days
    initiated = c.post(f"/api/projects/{pid}/sources/local-upload/initiate", json=payload, headers=headers)
    assert initiated.status_code == 200
    sid = initiated.json()["source_id"]
    completed = c.post(f"/api/sources/{sid}/local-upload/complete", headers=headers)
    assert completed.status_code == 200
    body = completed.json()
    assert datetime.fromisoformat(body["expires_at"]) - datetime.fromisoformat(body["uploaded_at"]) == timedelta(days=days or 7)
    replay = c.post(f"/api/sources/{sid}/local-upload/complete", headers=headers)
    assert replay.json() == body


@pytest.mark.parametrize("reference_class,days", [("transcription", 7), ("audio_processing", 1), ("audio_processing", True)])
def test_audio_retention_rejects_invalid_or_wrong_class_input(monkeypatch, reference_class, days):
    enable_fake_storage(monkeypatch)
    c, headers, pid = create_logged_in_project(f"invalid-audio-{reference_class}-{days}@example.com".lower())
    response = c.post(f"/api/projects/{pid}/sources/local-upload/initiate", json={
        "original_filename": "audio.mp3", "mime_type": "audio/mpeg", "size_bytes": 10,
        "reference_class": reference_class, "audio_retention_days": days,
    }, headers=headers)
    assert response.status_code == 422


def test_expired_local_upload_cleanup_marks_deleted_and_deletes(monkeypatch):
    fake = enable_fake_storage(monkeypatch)
    from studio_api.models import Source, SourceType, SourceUploadStatus
    from studio_api.source_deletion import run_one_source_cleanup
    c, headers, pid = create_logged_in_project("cleanup@example.com")
    db = SessionLocal()
    try:
        src = Source(project_id=pid, source_type=SourceType.local_upload, original_filename="old.mp3", mime_type="audio/mpeg", size_bytes=10, s3_bucket="studio-temp", s3_object_key="old/key", upload_status=SourceUploadStatus.pending, expires_at=utcnow()-timedelta(seconds=1))
        db.add(src); db.commit()
        assert run_one_source_cleanup(
            db,
            settings=__import__("studio_api.main", fromlist=["settings"]).settings,
            owner_id="legacy-source-cleanup",
            now=utcnow(),
            storage_factory=lambda _settings: fake,
        )
        db.refresh(src)
        assert src.upload_status == SourceUploadStatus.expired
        assert src.deleted_at is None and src.delete_reason == "retention_expired"
        assert fake.deleted == [("studio-temp", "old/key")]
    finally:
        db.close()


def configure_google_oauth(monkeypatch, tmp_path):
    from studio_api import main as main_mod
    secret = tmp_path / "google_client_secret"
    secret.write_text("google-client-secret-test", encoding="utf-8")
    monkeypatch.setattr(
        main_mod.settings,
        "google_oauth_client_id",
        "google-client-id-test.apps.googleusercontent.com",
    )
    monkeypatch.setattr(
        main_mod.settings,
        "google_oauth_client_secret_file",
        str(secret),
    )
    monkeypatch.setattr(
        main_mod.settings,
        "app_origin",
        "https://studio.test",
    )
    monkeypatch.setattr(
        main_mod.settings,
        "google_oauth_redirect_uri",
        "https://studio.test/api/google/oauth/callback",
    )
    monkeypatch.setattr(
        main_mod.settings,
        "google_oauth_scopes",
        (
            "openid email https://www.googleapis.com/auth/drive.file "
            "https://www.googleapis.com/auth/drive.readonly"
        ),
    )
    monkeypatch.setattr(
        main_mod.settings,
        "google_oauth_state_ttl_seconds",
        600,
    )
    return secret


def configure_google_maintenance_oauth(monkeypatch, tmp_path):
    from studio_api import main as main_mod

    secret = tmp_path / "google_maintenance_client_secret"
    secret.write_text(
        "google-maintenance-client-secret-test",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        main_mod.settings,
        "google_maintenance_oauth_client_id",
        "google-maintenance-client-id-test.apps.googleusercontent.com",
    )
    monkeypatch.setattr(
        main_mod.settings,
        "google_maintenance_oauth_client_secret_file",
        str(secret),
    )
    monkeypatch.setattr(
        main_mod.settings,
        "google_maintenance_oauth_redirect_uri",
        "https://studio.test/api/google/oauth/callback",
    )
    monkeypatch.setattr(
        main_mod.settings,
        "google_maintenance_oauth_scopes",
        (
            "openid email "
            "https://www.googleapis.com/auth/drive.metadata.readonly "
            "https://www.googleapis.com/auth/documents"
        ),
    )
    return secret


def test_google_connection_requires_authentication():
    c = TestClient(app)
    assert c.get("/api/google/connection").status_code == 401
    assert c.get("/api/google/maintenance/connection").status_code == 401
    assert c.post("/api/google/maintenance/oauth/start").status_code == 401
    assert c.delete("/api/google/maintenance/connection").status_code == 401


def test_google_connection_status_no_connection():
    pw = admin("google-empty@example.com"); c = TestClient(app); login(c, pw, "google-empty@example.com")
    r = c.get("/api/google/connection")
    assert r.status_code == 200
    assert r.json() == {"connected": False, "status": None, "google_email": None, "scopes": None, "connected_at": None, "revoked_at": None, "picker_configured": False, "picker_scope_ready": False, "picker_ready": False, "reconnect_required": False}


def test_google_oauth_start_requires_csrf_and_fails_closed_when_missing_config(monkeypatch):
    from studio_api import main as main_mod
    pw = admin("google-start@example.com"); c = TestClient(app); csrf = login(c, pw, "google-start@example.com")
    assert c.post("/api/google/oauth/start", headers={"origin": "https://studio.test"}).status_code == 403
    main_mod.settings.google_oauth_client_id = None
    main_mod.settings.google_oauth_client_secret_file = None
    main_mod.settings.google_oauth_redirect_uri = None
    r = c.post("/api/google/oauth/start", headers={"origin": "https://studio.test", "x-csrf-token": csrf})
    assert r.status_code == 503
    assert "secret" not in r.text.lower()


def test_google_oauth_start_returns_safe_url_and_stores_hashed_state(monkeypatch, tmp_path):
    configure_google_oauth(monkeypatch, tmp_path)
    pw = admin("google-url@example.com"); c = TestClient(app); csrf = login(c, pw, "google-url@example.com")
    r = c.post("/api/google/oauth/start", headers={"origin": "https://studio.test", "x-csrf-token": csrf})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["pragma"] == "no-cache"
    body = r.json(); url = body["authorization_url"]
    assert "client_id=google-client-id-test" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    from urllib.parse import parse_qs, urlparse
    query = parse_qs(urlparse(url).query)
    assert "include_granted_scopes" not in query
    assert "google-client-secret-test" not in r.text
    assert "refresh_token" not in r.text and "access_token" not in r.text and "id_token" not in r.text
    state = query["state"][0]
    db = SessionLocal()
    try:
        from studio_api.models import GoogleOAuthState
        rows = db.query(GoogleOAuthState).all()
        assert len(rows) == 1
        assert rows[0].state_hash != state
        assert rows[0].expires_at > utcnow()
    finally:
        db.close()


def assert_oauth_redirect(response, result, forbidden_values=None):
    assert response.status_code == 303
    assert response.headers["cache-control"] == "no-store"
    location = response.headers["location"]
    assert location == f"https://studio.test/?google_oauth={result}"
    forbidden = [
        "code=",
        "state=",
        "access_token=",
        "refresh_token=",
        "id_token=",
        "auth-code",
        "user@gmail.com",
        "google-sub",
        "id-token-raw-test-value",
        "access-token-raw-test-value",
        "refresh-token-raw-test-value",
    ]
    forbidden.extend(forbidden_values or [])
    assert all(value not in location for value in forbidden)

def test_google_oauth_callback_rejects_missing_invalid_expired_and_used_state(monkeypatch, tmp_path):
    configure_google_oauth(monkeypatch, tmp_path)
    pw = admin("google-state@example.com"); c = TestClient(app, follow_redirects=False); csrf = login(c, pw, "google-state@example.com")
    assert_oauth_redirect(c.get("/api/google/oauth/callback"), "invalid_callback")
    assert_oauth_redirect(c.get("/api/google/oauth/callback?state=bad&code=code"), "invalid_state")
    r = c.post("/api/google/oauth/start", headers={"origin": "https://studio.test", "x-csrf-token": csrf})
    from urllib.parse import parse_qs, urlparse
    state = parse_qs(urlparse(r.json()["authorization_url"]).query)["state"][0]
    db = SessionLocal()
    try:
        from studio_api.models import GoogleOAuthState
        row = db.query(GoogleOAuthState).first(); row.expires_at = utcnow() - timedelta(seconds=1); db.commit()
    finally:
        db.close()
    assert_oauth_redirect(c.get(f"/api/google/oauth/callback?state={state}&code=code"), "invalid_state")

    r = c.post("/api/google/oauth/start", headers={"origin": "https://studio.test", "x-csrf-token": csrf})
    state = parse_qs(urlparse(r.json()["authorization_url"]).query)["state"][0]
    from studio_api.google_oauth import GoogleTokenResult
    monkeypatch.setattr("studio_api.google_oauth.exchange_code_for_tokens", lambda cfg, code: GoogleTokenResult("refresh-safe", None, None, "openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly", "sub", "g@example.com"))
    assert_oauth_redirect(c.get(f"/api/google/oauth/callback?state={state}&code=code"), "connected")
    assert_oauth_redirect(c.get(f"/api/google/oauth/callback?state={state}&code=code"), "invalid_state")


def test_google_oauth_callback_stores_encrypted_token_and_safe_metadata_disconnect_wipes(monkeypatch, tmp_path):
    configure_google_oauth(monkeypatch, tmp_path)
    from studio_api.google_oauth import GoogleTokenResult
    raw_refresh = "refresh-token-raw-test-value"
    raw_access = "access-token-raw-test-value"
    raw_id = "id-token-raw-test-value"
    called = {"count": 0}
    def fake_exchange(cfg, code):
        called["count"] += 1
        return GoogleTokenResult(raw_refresh, raw_access, raw_id, "openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly", "google-sub-1", "user@gmail.com")
    monkeypatch.setattr("studio_api.google_oauth.exchange_code_for_tokens", fake_exchange)
    pw = admin("google-connect@example.com"); c = TestClient(app, follow_redirects=False); csrf = login(c, pw, "google-connect@example.com")
    r = c.post("/api/google/oauth/start", headers={"origin": "https://studio.test", "x-csrf-token": csrf})
    from urllib.parse import parse_qs, urlparse
    state = parse_qs(urlparse(r.json()["authorization_url"]).query)["state"][0]
    r = c.get(f"/api/google/oauth/callback?state={state}&code=auth-code&return_url=https://evil.test&next=https://evil.test", headers={"host":"evil.test", "origin":"https://evil.test", "referer":"https://evil.test/path"})
    assert_oauth_redirect(r, "connected")
    assert raw_refresh not in r.text and raw_access not in r.text and raw_id not in r.text
    assert called["count"] == 1
    r = c.get("/api/google/connection")
    assert r.status_code == 200
    assert r.json()["connected"] is True
    assert r.json()["google_email"] == "user@gmail.com"
    assert raw_refresh not in r.text and raw_access not in r.text and raw_id not in r.text
    db = SessionLocal()
    try:
        from studio_api.models import GoogleConnection
        conn = db.query(GoogleConnection).one()
        assert conn.refresh_token_ciphertext and conn.refresh_token_nonce
        assert raw_refresh.encode() not in conn.refresh_token_ciphertext
        assert decrypt(conn.refresh_token_ciphertext, conn.refresh_token_nonce, master_key_from_b64(base64.b64encode(b"1" * 32).decode()), aad(conn.user_id, conn.id, "refresh", "google")) == raw_refresh
        maintenance_ct, maintenance_nonce = encrypt(
            "maintenance-refresh-token-to-wipe",
            master_key_from_b64(base64.b64encode(b"1" * 32).decode()),
            aad(
                conn.user_id,
                conn.id,
                "maintenance-refresh",
                "google",
            ),
        )
        conn.maintenance_refresh_token_ciphertext = maintenance_ct
        conn.maintenance_refresh_token_nonce = maintenance_nonce
        conn.maintenance_key_id = "studio-v1"
        db.commit()
    finally:
        db.close()
    r = c.delete("/api/google/connection", headers={"origin": "https://studio.test", "x-csrf-token": csrf})
    assert r.status_code == 200
    assert r.json()["connected"] is False and r.json()["status"] == "revoked"
    first_disconnected = r.json()
    replay = c.delete("/api/google/connection", headers={"origin": "https://studio.test", "x-csrf-token": csrf})
    assert replay.status_code == 200
    assert replay.json() == first_disconnected
    db = SessionLocal()
    try:
        from studio_api.models import GoogleConnection
        conn = db.query(GoogleConnection).one()
        assert conn.refresh_token_ciphertext is None and conn.refresh_token_nonce is None and conn.key_id is None
        assert conn.maintenance_refresh_token_ciphertext is None
        assert conn.maintenance_refresh_token_nonce is None
        assert conn.maintenance_key_id is None
        assert db.query(AuditEvent).filter_by(
            event_type="google.disconnected",
            actor_user_id=conn.user_id,
        ).count() == 1
    finally:
        db.close()



def test_google_oauth_callback_safe_expected_error_redirects(monkeypatch, tmp_path):
    configure_google_oauth(monkeypatch, tmp_path)
    pw = admin("google-errors@example.com"); c = TestClient(app, follow_redirects=False); csrf = login(c, pw, "google-errors@example.com")
    raw_description = "raw_google_denied_secret"
    r = c.get(f"/api/google/oauth/callback?error=access_denied&error_description={raw_description}")
    assert_oauth_redirect(r, "cancelled", [raw_description])

    from urllib.parse import parse_qs, urlparse
    from studio_api.google_oauth import GoogleTokenResult

    r = c.post("/api/google/oauth/start", headers={"origin": "https://studio.test", "x-csrf-token": csrf})
    state = parse_qs(urlparse(r.json()["authorization_url"]).query)["state"][0]
    raw_exception = "raw exchange secret"
    monkeypatch.setattr("studio_api.google_oauth.exchange_code_for_tokens", lambda cfg, code: (_ for _ in ()).throw(RuntimeError(raw_exception)))
    assert_oauth_redirect(c.get(f"/api/google/oauth/callback?state={state}&code=auth-code"), "exchange_failed", [raw_exception])

    r = c.post("/api/google/oauth/start", headers={"origin": "https://studio.test", "x-csrf-token": csrf})
    state = parse_qs(urlparse(r.json()["authorization_url"]).query)["state"][0]
    monkeypatch.setattr("studio_api.google_oauth.exchange_code_for_tokens", lambda cfg, code: GoogleTokenResult(None, "access-token-test-value", "id-token-test-value", "openid email", "google-sub", "user@gmail.com"))
    assert_oauth_redirect(c.get(f"/api/google/oauth/callback?state={state}&code=auth-code"), "offline_access_missing", ["access-token-test-value", "id-token-test-value"])
    db = SessionLocal()
    try:
        from studio_api.models import GoogleConnection
        assert db.query(GoogleConnection).count() == 0
    finally:
        db.close()

def test_google_connection_user_isolation(monkeypatch, tmp_path):
    configure_google_oauth(monkeypatch, tmp_path)
    from studio_api.models import GoogleConnection, GoogleConnectionStatus, GoogleProvider
    db = SessionLocal()
    try:
        u1 = User(email="g1@example.com", role=UserRole.admin, status=UserStatus.active)
        u2 = User(email="g2@example.com", role=UserRole.admin, status=UserStatus.active)
        db.add_all([u1, u2]); db.flush()
        db.add_all([LocalIdentity(user_id=u1.id, password_hash=hash_password("password-one-long")), LocalIdentity(user_id=u2.id, password_hash=hash_password("password-two-long"))])
        db.add(GoogleConnection(user_id=u1.id, provider=GoogleProvider.google, status=GoogleConnectionStatus.active, google_email="g1@gmail.com", scopes="openid email", connected_at=utcnow()))
        db.commit()
    finally:
        db.close()
    c1 = TestClient(app); c2 = TestClient(app)
    login(c1, "password-one-long", "g1@example.com")
    login(c2, "password-two-long", "g2@example.com")
    assert c1.get("/api/google/connection").json()["google_email"] == "g1@gmail.com"
    assert c2.get("/api/google/connection").json()["connected"] is False


def add_google_connection_for_user(email: str, refresh_token: str, status="active"):
    from studio_api.models import GoogleConnection, GoogleConnectionStatus, GoogleProvider
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email=email).one()
        conn = GoogleConnection(user_id=user.id, provider=GoogleProvider.google, status=GoogleConnectionStatus(status), google_subject="same-google-subject", google_email="drive-user@gmail.com", scopes="openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly", connected_at=utcnow())
        db.add(conn); db.flush()
        ct, nonce = encrypt(refresh_token, master_key_from_b64(base64.b64encode(b"1" * 32).decode()), aad(user.id, conn.id, "refresh", "google"))
        conn.refresh_token_ciphertext = ct
        conn.refresh_token_nonce = nonce
        conn.key_id = "studio-v1"
        db.commit()
        return conn.id
    finally:
        db.close()


def assert_maintenance_oauth_redirect(
    response,
    result,
    forbidden_values=None,
):
    assert response.status_code == 303
    assert response.headers["cache-control"] == "no-store"
    location = response.headers["location"]
    assert (
        location
        == f"https://studio.test/?google_maintenance_oauth={result}"
    )
    forbidden = [
        "code=",
        "state=",
        "access_token=",
        "refresh_token=",
        "id_token=",
        "maintenance-refresh-token",
        "maintenance-access-token",
        "maintenance-id-token",
    ]
    forbidden.extend(forbidden_values or [])
    assert all(value not in location for value in forbidden)


def test_google_maintenance_oauth_requires_primary_connection(
    monkeypatch,
    tmp_path,
):
    configure_google_maintenance_oauth(monkeypatch, tmp_path)
    email = "maintenance-primary-required@example.com"
    password = admin(email)
    client = TestClient(app)
    csrf = login(client, password, email)

    assert (
        client.get("/api/google/maintenance/connection").status_code
        == 200
    )
    assert (
        client.post("/api/google/maintenance/oauth/start").status_code
        == 403
    )
    response = client.post(
        "/api/google/maintenance/oauth/start",
        headers={
            "origin": "https://studio.test",
            "x-csrf-token": csrf,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "google_primary_connection_required"
    assert "secret" not in response.text.lower()


def test_google_maintenance_oauth_is_separate_and_server_only(
    monkeypatch,
    tmp_path,
):
    configure_google_oauth(monkeypatch, tmp_path)
    configure_google_maintenance_oauth(monkeypatch, tmp_path)
    from studio_api.google_oauth import (
        GoogleTokenResult,
        MAINTENANCE_OAUTH_PURPOSE,
    )
    from studio_api.google_connection_access import (
        google_maintenance_token_aad,
    )

    primary_refresh = "primary-refresh-token"
    maintenance_refresh = "maintenance-refresh-token"
    maintenance_access = "maintenance-access-token"
    maintenance_id = "maintenance-id-token"
    email = "maintenance-oauth@example.com"
    password = admin(email)
    client = TestClient(app, follow_redirects=False)
    csrf = login(client, password, email)
    add_google_connection_for_user(email, primary_refresh)

    started = client.post(
        "/api/google/maintenance/oauth/start",
        headers={
            "origin": "https://studio.test",
            "x-csrf-token": csrf,
        },
    )
    assert started.status_code == 200
    assert started.headers["cache-control"] == "no-store"
    assert started.headers["pragma"] == "no-cache"
    from urllib.parse import parse_qs, urlparse
    query = parse_qs(
        urlparse(started.json()["authorization_url"]).query
    )
    assert query["client_id"] == [
        "google-maintenance-client-id-test.apps.googleusercontent.com"
    ]
    assert query["scope"] == [
        (
            "openid email "
            "https://www.googleapis.com/auth/drive.metadata.readonly "
            "https://www.googleapis.com/auth/documents"
        )
    ]
    assert "drive.file" not in query["scope"][0]
    state = query["state"][0]
    db = SessionLocal()
    try:
        from studio_api.models import GoogleOAuthState

        oauth_state = db.query(GoogleOAuthState).one()
        assert oauth_state.purpose == MAINTENANCE_OAUTH_PURPOSE
        assert oauth_state.state_hash != state
    finally:
        db.close()

    def fake_exchange(config, code):
        assert config.client_id.startswith(
            "google-maintenance-client-id-test"
        )
        assert code == "maintenance-code"
        return GoogleTokenResult(
            maintenance_refresh,
            maintenance_access,
            maintenance_id,
            query["scope"][0],
            "same-google-subject",
            "drive-user@gmail.com",
        )

    monkeypatch.setattr(
        "studio_api.google_oauth.exchange_code_for_tokens",
        fake_exchange,
    )
    callback = client.get(
        f"/api/google/oauth/callback?state={state}&code=maintenance-code"
    )
    assert_maintenance_oauth_redirect(callback, "connected")
    status_response = client.get(
        "/api/google/maintenance/connection"
    )
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["connected"] is True
    assert status_payload["configured"] is True
    assert status_payload["account_match"] is True
    assert status_payload["scope_ready"] is True
    assert status_payload["ready"] is True
    assert maintenance_refresh not in status_response.text
    assert maintenance_access not in status_response.text
    assert maintenance_id not in status_response.text

    db = SessionLocal()
    try:
        from studio_api.models import GoogleConnection

        connection = db.query(GoogleConnection).one()
        master_key = master_key_from_b64(
            base64.b64encode(b"1" * 32).decode()
        )
        assert decrypt(
            connection.refresh_token_ciphertext,
            connection.refresh_token_nonce,
            master_key,
            aad(
                connection.user_id,
                connection.id,
                "refresh",
                "google",
            ),
        ) == primary_refresh
        assert decrypt(
            connection.maintenance_refresh_token_ciphertext,
            connection.maintenance_refresh_token_nonce,
            master_key,
            google_maintenance_token_aad(
                connection.user_id,
                connection.id,
            ),
        ) == maintenance_refresh
    finally:
        db.close()

    disconnected = client.delete(
        "/api/google/maintenance/connection",
        headers={
            "origin": "https://studio.test",
            "x-csrf-token": csrf,
        },
    )
    assert disconnected.status_code == 200
    assert disconnected.json()["connected"] is False
    assert disconnected.json()["status"] == "revoked"
    assert client.get("/api/google/connection").json()["connected"] is True
    db = SessionLocal()
    try:
        from studio_api.models import GoogleConnection

        connection = db.query(GoogleConnection).one()
        assert connection.refresh_token_ciphertext is not None
        assert connection.maintenance_refresh_token_ciphertext is None
        assert connection.maintenance_refresh_token_nonce is None
        assert connection.maintenance_key_id is None
    finally:
        db.close()


@pytest.mark.parametrize(
    ("google_subject", "scopes", "expected_result"),
    [
        (
            "different-google-subject",
            (
                "openid email "
                "https://www.googleapis.com/auth/drive.metadata.readonly "
                "https://www.googleapis.com/auth/documents"
            ),
            "account_mismatch",
        ),
        (
            "same-google-subject",
            (
                "openid email "
                "https://www.googleapis.com/auth/drive.metadata.readonly "
                "https://www.googleapis.com/auth/documents "
                "https://www.googleapis.com/auth/drive"
            ),
            "scope_unavailable",
        ),
    ],
)
def test_google_maintenance_oauth_rejects_wrong_account_or_broad_grant(
    monkeypatch,
    tmp_path,
    google_subject,
    scopes,
    expected_result,
):
    configure_google_oauth(monkeypatch, tmp_path)
    configure_google_maintenance_oauth(monkeypatch, tmp_path)
    from studio_api.google_oauth import GoogleTokenResult

    email = f"maintenance-{expected_result}@example.com"
    password = admin(email)
    client = TestClient(app, follow_redirects=False)
    csrf = login(client, password, email)
    add_google_connection_for_user(email, "primary-refresh-token")
    started = client.post(
        "/api/google/maintenance/oauth/start",
        headers={
            "origin": "https://studio.test",
            "x-csrf-token": csrf,
        },
    )
    from urllib.parse import parse_qs, urlparse
    state = parse_qs(
        urlparse(started.json()["authorization_url"]).query
    )["state"][0]
    monkeypatch.setattr(
        "studio_api.google_oauth.exchange_code_for_tokens",
        lambda _config, _code: GoogleTokenResult(
            "rejected-maintenance-refresh-token",
            "rejected-maintenance-access-token",
            "rejected-maintenance-id-token",
            scopes,
            google_subject,
            "other@gmail.com",
        ),
    )

    callback = client.get(
        f"/api/google/oauth/callback?state={state}&code=maintenance-code"
    )

    assert_maintenance_oauth_redirect(
        callback,
        expected_result,
        [
            "rejected-maintenance-refresh-token",
            "rejected-maintenance-access-token",
            "rejected-maintenance-id-token",
        ],
    )
    db = SessionLocal()
    try:
        from studio_api.models import GoogleConnection

        connection = db.query(GoogleConnection).one()
        assert connection.maintenance_refresh_token_ciphertext is None
        assert connection.maintenance_refresh_token_nonce is None
        assert connection.maintenance_key_id is None
    finally:
        db.close()


def test_google_drive_metadata_requires_authentication():
    c = TestClient(app)
    assert c.get("/api/google/drive/files/file_123/metadata").status_code == 401


def test_google_drive_metadata_no_connection_safe_error(monkeypatch, tmp_path):
    configure_google_oauth(monkeypatch, tmp_path)
    pw = admin("drive-none@example.com"); c = TestClient(app); login(c, pw, "drive-none@example.com")
    r = c.get("/api/google/drive/files/file_123/metadata")
    assert r.status_code == 404
    assert "refresh" not in r.text.lower() and "access" not in r.text.lower() and str(tmp_path) not in r.text


def test_google_drive_metadata_revoked_connection_safe_error(monkeypatch, tmp_path):
    configure_google_oauth(monkeypatch, tmp_path)
    pw = admin("drive-revoked@example.com"); c = TestClient(app); login(c, pw, "drive-revoked@example.com")
    add_google_connection_for_user("drive-revoked@example.com", "fake-refresh-token-revoked", status="revoked")
    r = c.get("/api/google/drive/files/file_123/metadata")
    assert r.status_code == 409
    assert "fake-refresh-token-revoked" not in r.text and str(tmp_path) not in r.text


def test_google_drive_metadata_missing_runtime_config_fails_closed(monkeypatch):
    from studio_api import main as main_mod
    pw = admin("drive-noconfig@example.com"); c = TestClient(app); login(c, pw, "drive-noconfig@example.com")
    add_google_connection_for_user("drive-noconfig@example.com", "fake-refresh-token-config")
    main_mod.settings.google_oauth_client_id = None
    main_mod.settings.google_oauth_client_secret_file = None
    main_mod.settings.google_oauth_redirect_uri = None
    r = c.get("/api/google/drive/files/file_123/metadata")
    assert r.status_code == 503
    assert "fake-refresh-token-config" not in r.text and "secret" not in r.text.lower()


def test_google_drive_metadata_active_connection_returns_safe_metadata(monkeypatch, tmp_path):
    configure_google_oauth(monkeypatch, tmp_path)
    raw_refresh = "fake-refresh-token-success"
    raw_access = "fake-access-token-success"
    pw = admin("drive-success@example.com"); c = TestClient(app); login(c, pw, "drive-success@example.com")
    add_google_connection_for_user("drive-success@example.com", raw_refresh)
    calls = {}
    def fake_refresh(cfg, refresh_token):
        calls["refresh_token"] = refresh_token
        return raw_access
    def fake_fetch(access_token, drive_file_id):
        calls["access_token"] = access_token
        calls["drive_file_id"] = drive_file_id
        from studio_api.google_drive import GoogleDriveMetadata
        return GoogleDriveMetadata("file_123", "Meeting.mp4", "video/mp4", 42, "https://drive.google.com/file/d/file_123/view", "2026-01-01T00:00:00.000Z", "2026-01-02T00:00:00.000Z", False)
    monkeypatch.setattr("studio_api.google_drive.refresh_access_token", fake_refresh)
    monkeypatch.setattr("studio_api.google_drive.fetch_drive_file_metadata", fake_fetch)
    r = c.get("/api/google/drive/files/file_123/metadata")
    assert r.status_code == 200
    assert r.json() == {"id":"file_123", "name":"Meeting.mp4", "mime_type":"video/mp4", "size_bytes":42, "web_view_link":"https://drive.google.com/file/d/file_123/view", "created_time":"2026-01-01T00:00:00.000Z", "modified_time":"2026-01-02T00:00:00.000Z", "is_folder":False}
    assert calls == {"refresh_token": raw_refresh, "access_token": raw_access, "drive_file_id": "file_123"}
    forbidden = [raw_refresh, raw_access, "google-client-secret-test", str(tmp_path), "rawPayload", "owners", "permissions"]
    assert all(value not in r.text for value in forbidden)


def test_google_drive_metadata_drive_failure_safe_no_raw_leak(monkeypatch, tmp_path):
    configure_google_oauth(monkeypatch, tmp_path)
    raw_refresh = "fake-refresh-token-failure"
    raw_access = "fake-access-token-failure"
    raw_google_body = "raw google body with permissions and token fake-access-token-failure"
    pw = admin("drive-failure@example.com"); c = TestClient(app); login(c, pw, "drive-failure@example.com")
    add_google_connection_for_user("drive-failure@example.com", raw_refresh)
    monkeypatch.setattr("studio_api.google_drive.refresh_access_token", lambda cfg, refresh_token: raw_access)
    def fake_fetch(access_token, drive_file_id):
        raise RuntimeError(raw_google_body)
    monkeypatch.setattr("studio_api.google_drive.fetch_drive_file_metadata", fake_fetch)
    r = c.get("/api/google/drive/files/file_123/metadata")
    assert r.status_code == 502
    assert raw_refresh not in r.text and raw_access not in r.text and raw_google_body not in r.text and str(tmp_path) not in r.text


def test_google_drive_metadata_user_isolation(monkeypatch, tmp_path):
    configure_google_oauth(monkeypatch, tmp_path)
    pw1 = admin("drive-owner@example.com", "password-one-long")
    pw2 = admin("drive-other@example.com", "password-two-long")
    add_google_connection_for_user("drive-owner@example.com", "fake-refresh-token-owner")
    c1 = TestClient(app); c2 = TestClient(app)
    login(c1, pw1, "drive-owner@example.com")
    login(c2, pw2, "drive-other@example.com")
    monkeypatch.setattr("studio_api.google_drive.refresh_access_token", lambda cfg, refresh_token: "fake-access-token-owner")
    def fake_fetch(access_token, drive_file_id):
        from studio_api.google_drive import GoogleDriveMetadata
        return GoogleDriveMetadata(drive_file_id, "Owner file", "application/vnd.google-apps.folder", None, None, None, None, True)
    monkeypatch.setattr("studio_api.google_drive.fetch_drive_file_metadata", fake_fetch)
    assert c1.get("/api/google/drive/files/folder_123/metadata").status_code == 200
    r = c2.get("/api/google/drive/files/folder_123/metadata")
    assert r.status_code == 404
    assert "fake-refresh-token-owner" not in r.text and "fake-access-token-owner" not in r.text


def test_google_drive_folder_children_requires_authentication():
    c = TestClient(app)
    assert c.get("/api/google/drive/folders/folder_123/children").status_code == 401


def test_google_drive_folder_children_no_connection_safe_error(monkeypatch, tmp_path):
    configure_google_oauth(monkeypatch, tmp_path)
    pw = admin("drive-children-none@example.com"); c = TestClient(app); login(c, pw, "drive-children-none@example.com")
    r = c.get("/api/google/drive/folders/folder_123/children")
    assert r.status_code == 404
    assert "refresh" not in r.text.lower() and "access" not in r.text.lower() and str(tmp_path) not in r.text


def test_google_drive_folder_children_revoked_connection_safe_error(monkeypatch, tmp_path):
    configure_google_oauth(monkeypatch, tmp_path)
    pw = admin("drive-children-revoked@example.com"); c = TestClient(app); login(c, pw, "drive-children-revoked@example.com")
    add_google_connection_for_user("drive-children-revoked@example.com", "fake-refresh-token-children-revoked", status="revoked")
    r = c.get("/api/google/drive/folders/folder_123/children")
    assert r.status_code == 409
    assert "fake-refresh-token-children-revoked" not in r.text and str(tmp_path) not in r.text


def test_google_drive_folder_children_missing_runtime_config_fails_closed(monkeypatch):
    from studio_api import main as main_mod
    pw = admin("drive-children-noconfig@example.com"); c = TestClient(app); login(c, pw, "drive-children-noconfig@example.com")
    add_google_connection_for_user("drive-children-noconfig@example.com", "fake-refresh-token-children-config")
    main_mod.settings.google_oauth_client_id = None
    main_mod.settings.google_oauth_client_secret_file = None
    main_mod.settings.google_oauth_redirect_uri = None
    r = c.get("/api/google/drive/folders/folder_123/children")
    assert r.status_code == 503
    assert "fake-refresh-token-children-config" not in r.text and "secret" not in r.text.lower()


def test_google_drive_folder_children_active_connection_returns_safe_items_and_pagination(monkeypatch, tmp_path):
    configure_google_oauth(monkeypatch, tmp_path)
    raw_refresh = "fake-refresh-token-children-success"
    raw_access = "fake-access-token-children-success"
    pw = admin("drive-children-success@example.com"); c = TestClient(app); login(c, pw, "drive-children-success@example.com")
    add_google_connection_for_user("drive-children-success@example.com", raw_refresh)
    calls = {}
    def fake_refresh(cfg, refresh_token):
        calls["refresh_token"] = refresh_token
        return raw_access
    def fake_list(access_token, folder_id, page_size=50, page_token=None):
        calls.update({"access_token": access_token, "folder_id": folder_id, "page_size": page_size, "page_token": page_token})
        from studio_api.google_drive import GoogleDriveFolderChildren, GoogleDriveMetadata
        return GoogleDriveFolderChildren(folder_id, [
            GoogleDriveMetadata("file_123", "Meeting.mp4", "video/mp4", 42, "https://drive.google.com/file/d/file_123/view", "2026-01-01T00:00:00.000Z", "2026-01-02T00:00:00.000Z", False),
            GoogleDriveMetadata("folder_child", "Nested", "application/vnd.google-apps.folder", None, "https://drive.google.com/drive/folders/folder_child", "2026-01-03T00:00:00.000Z", "2026-01-04T00:00:00.000Z", True),
        ], "safe-next-page-token")
    monkeypatch.setattr("studio_api.google_drive.refresh_access_token", fake_refresh)
    monkeypatch.setattr("studio_api.google_drive.list_drive_folder_children", fake_list)
    r = c.get("/api/google/drive/folders/folder_123/children?page_size=25&page_token=safe-page-token")
    assert r.status_code == 200
    assert r.json() == {"folder_id":"folder_123", "items":[
        {"id":"file_123", "name":"Meeting.mp4", "mime_type":"video/mp4", "size_bytes":42, "web_view_link":"https://drive.google.com/file/d/file_123/view", "created_time":"2026-01-01T00:00:00.000Z", "modified_time":"2026-01-02T00:00:00.000Z", "is_folder":False},
        {"id":"folder_child", "name":"Nested", "mime_type":"application/vnd.google-apps.folder", "size_bytes":None, "web_view_link":"https://drive.google.com/drive/folders/folder_child", "created_time":"2026-01-03T00:00:00.000Z", "modified_time":"2026-01-04T00:00:00.000Z", "is_folder":True},
    ], "next_page_token":"safe-next-page-token"}
    assert calls == {"refresh_token": raw_refresh, "access_token": raw_access, "folder_id": "folder_123", "page_size": 25, "page_token": "safe-page-token"}
    forbidden = [raw_refresh, raw_access, "google-client-secret-test", str(tmp_path), "rawPayload", "owners", "permissions", "labels", "thumbnail"]
    assert all(value not in r.text for value in forbidden)


def test_google_drive_folder_children_drive_failure_safe_no_raw_leak(monkeypatch, tmp_path):
    configure_google_oauth(monkeypatch, tmp_path)
    raw_refresh = "fake-refresh-token-children-failure"
    raw_access = "fake-access-token-children-failure"
    raw_google_body = "raw google body with owners permissions labels thumbnails and token fake-access-token-children-failure"
    pw = admin("drive-children-failure@example.com"); c = TestClient(app); login(c, pw, "drive-children-failure@example.com")
    add_google_connection_for_user("drive-children-failure@example.com", raw_refresh)
    monkeypatch.setattr("studio_api.google_drive.refresh_access_token", lambda cfg, refresh_token: raw_access)
    def fake_list(access_token, folder_id, page_size=50, page_token=None):
        raise RuntimeError(raw_google_body)
    monkeypatch.setattr("studio_api.google_drive.list_drive_folder_children", fake_list)
    r = c.get("/api/google/drive/folders/folder_123/children")
    assert r.status_code == 502
    assert raw_refresh not in r.text and raw_access not in r.text and raw_google_body not in r.text and str(tmp_path) not in r.text


def test_google_drive_folder_children_user_isolation(monkeypatch, tmp_path):
    configure_google_oauth(monkeypatch, tmp_path)
    pw1 = admin("drive-children-owner@example.com", "password-one-long")
    pw2 = admin("drive-children-other@example.com", "password-two-long")
    add_google_connection_for_user("drive-children-owner@example.com", "fake-refresh-token-children-owner")
    c1 = TestClient(app); c2 = TestClient(app)
    login(c1, pw1, "drive-children-owner@example.com")
    login(c2, pw2, "drive-children-other@example.com")
    monkeypatch.setattr("studio_api.google_drive.refresh_access_token", lambda cfg, refresh_token: "fake-access-token-children-owner")
    def fake_list(access_token, folder_id, page_size=50, page_token=None):
        from studio_api.google_drive import GoogleDriveFolderChildren
        return GoogleDriveFolderChildren(folder_id, [], None)
    monkeypatch.setattr("studio_api.google_drive.list_drive_folder_children", fake_list)
    assert c1.get("/api/google/drive/folders/folder_123/children").status_code == 200
    r = c2.get("/api/google/drive/folders/folder_123/children")
    assert r.status_code == 404
    assert "fake-refresh-token-children-owner" not in r.text and "fake-access-token-children-owner" not in r.text


def test_google_drive_folder_children_invalid_folder_id_returns_422(monkeypatch, tmp_path):
    configure_google_oauth(monkeypatch, tmp_path)
    pw = admin("drive-children-invalid@example.com"); c = TestClient(app); login(c, pw, "drive-children-invalid@example.com")
    add_google_connection_for_user("drive-children-invalid@example.com", "fake-refresh-token-children-invalid")
    r = c.get("/api/google/drive/folders/bad:id/children")
    assert r.status_code == 422
    assert "fake-refresh-token-children-invalid" not in r.text


LEASE_TEST_NOW = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
LEASE_TEST_TTL = timedelta(minutes=15)


def lease_test_job(status=JobStatus.queued, ready=True):
    db = SessionLocal()
    try:
        user = User(email=f"lease-{utcnow().timestamp()}@example.com", role=UserRole.admin, status=UserStatus.active)
        db.add(user); db.flush(); db.add(LocalIdentity(user_id=user.id, password_hash=hash_password("correct horse battery")))
        project = Project(owner_user_id=user.id, title="Lease Project", output_drive_folder_id="folder-1")
        db.add(project); db.flush()
        if ready:
            source = Source(project_id=project.id, source_type=SourceType.google_drive, original_filename="a.mp3", upload_status=SourceUploadStatus.uploaded, drive_file_id="drive-file-1")
        else:
            source = Source(project_id=project.id, source_type=SourceType.google_drive, original_filename="a.mp3", upload_status=SourceUploadStatus.pending)
        db.add(source); db.flush()
        job = TranscriptionJob(project_id=project.id, owner_user_id=user.id, status=status, title="Lease Job", output_drive_folder_id="folder-1", output_drive_folder_url="https://drive.google.com/drive/folders/folder-1", output_drive_folder_name="Lease folder")
        db.add(job); db.flush()
        db.add(TranscriptionJobSource(job_id=job.id, source_id=source.id, position=0))
        db.commit()
        return user.id, job.id
    finally:
        db.close()


def assert_lease_reason(exc, reason):
    assert exc.value.reason == reason


def jobstatus_enum_values():
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT e.enumlabel FROM pg_enum e "
            "JOIN pg_type t ON t.oid = e.enumtypid "
            "WHERE t.typname = 'jobstatus' "
            "ORDER BY e.enumsortorder"
        )).scalars().all()


def assert_jobstatus_enum_order():
    assert jobstatus_enum_values() == ["queued", "processing", "cancelled", "failed", "completed"]


def test_job_lease_migration_clean_chain_shape_and_defaults():
    inspector = inspect(engine)
    cols = {c["name"]: c for c in inspector.get_columns("transcription_jobs")}
    assert {"lease_owner_id", "lease_generation", "claimed_at", "lease_expires_at", "attempt_count", "cancel_requested_at"}.issubset(cols)
    assert cols["lease_owner_id"]["nullable"] is True
    assert cols["lease_generation"]["nullable"] is False
    assert cols["attempt_count"]["nullable"] is False
    assert cols["cancel_requested_at"]["nullable"] is True
    indexes = [idx["name"] for idx in inspector.get_indexes("transcription_jobs")]
    assert indexes.count("ix_transcription_jobs_status_lease_expires_created") == 1
    assert_jobstatus_enum_order()
    _, job_id = lease_test_job()
    db = SessionLocal()
    try:
        job = db.get(TranscriptionJob, job_id)
        assert job.lease_generation == 0
        assert job.lease_owner_id is None
        assert job.claimed_at is None
        assert job.lease_expires_at is None
        assert job.attempt_count == 0
    finally:
        db.close()


def test_job_lease_migration_real_0005_shape_upgrades_to_head():
    with isolated_migration_database("studio_migration_0005") as (temp_engine, env):
        run_alembic("0005_transcription_jobs", env=env)
        with temp_engine.begin() as conn:
            # 0001 reflects current metadata; strip 0006-owned lease fields to
            # create a genuine 0005 shape before upgrading through head.
            conn.execute(text("DROP INDEX IF EXISTS ix_transcription_jobs_status_lease_expires_created"))
            for col in ["lease_owner_id", "lease_generation", "claimed_at", "lease_expires_at", "attempt_count", "cancel_requested_at"]:
                conn.execute(text(f"ALTER TABLE transcription_jobs DROP COLUMN IF EXISTS {col}"))
            conn.execute(text("UPDATE alembic_version SET version_num='0005_transcription_jobs'"))
            cols_at_0005 = {c["name"] for c in inspect(conn).get_columns("transcription_jobs")}
            assert "lease_owner_id" not in cols_at_0005
        run_alembic("head", env=env)
        with temp_engine.begin() as conn:
            inspector = inspect(conn)
            cols = {c["name"] for c in inspector.get_columns("transcription_jobs")}
            assert {"lease_owner_id", "lease_generation", "claimed_at", "lease_expires_at", "attempt_count", "cancel_requested_at"}.issubset(cols)
            indexes = [idx["name"] for idx in inspector.get_indexes("transcription_jobs")]
            assert indexes.count("ix_transcription_jobs_status_lease_expires_created") == 1
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0043_yandex_disk"



def test_job_output_migration_clean_chain_constraints_and_0007_roundtrip():
    inspector = inspect(engine)
    assert "transcription_job_outputs" in inspector.get_table_names()
    cols = {c["name"]: c for c in inspector.get_columns("transcription_job_outputs")}
    assert {"id", "job_id", "job_source_id", "document_id", "web_view_url", "output_drive_folder_id", "output_kind", "transcript_standard", "document_character_count", "document_created_at", "persisted_at", "lease_generation"}.issubset(cols)
    uniques = {tuple(u["column_names"]) for u in inspector.get_unique_constraints("transcription_job_outputs")}
    assert ("job_source_id",) in uniques and ("document_id",) in uniques
    indexes = {idx["name"] for idx in inspector.get_indexes("transcription_job_outputs")}
    assert "ix_transcription_job_outputs_job_id" in indexes
    fks = {tuple(fk["constrained_columns"]): fk["referred_table"] for fk in inspector.get_foreign_keys("transcription_job_outputs")}
    assert fks[("job_id",)] == "transcription_jobs" and fks[("job_source_id",)] == "transcription_job_sources"
    with isolated_migration_database("studio_migration_0007") as (temp_engine, env):
        run_alembic("0007_job_processing_lifecycle", env=env)
        with temp_engine.begin() as conn:
            # 0001 reflects current metadata; strip post-0007 dependent
            # objects and post-0007-owned columns in dependency order to create a
            # genuine 0007 shape.
            conn.execute(text("DROP TABLE IF EXISTS provider_account_snapshots"))
            conn.execute(text("DROP TABLE IF EXISTS transcription_job_source_attempts"))
            conn.execute(text("DROP TABLE IF EXISTS transcription_output_reconciliations"))
            conn.execute(text("DROP TABLE IF EXISTS transcription_job_outputs"))
            for constraint in [
                "ck_transcription_jobs_provider_accounting_consistent",
                "ck_transcription_jobs_provider_rate_positive",
                "ck_transcription_jobs_provider_currency",
                "ck_transcription_jobs_provider_cost_nonnegative",
                "ck_transcription_jobs_provider_duration_nonnegative",
            ]:
                conn.execute(
                    text(
                        f"ALTER TABLE transcription_jobs DROP CONSTRAINT IF EXISTS {constraint}"
                    )
                )
            for column in [
                "provider_accounting_uncertain",
                "provider_accounting_complete",
                "provider_rate_source",
                "provider_rate_effective_date",
                "provider_rate_per_hour",
                "provider_cost_currency",
                "provider_cost_amount",
                "provider_billed_duration_ms",
            ]:
                conn.execute(
                    text(
                        f"ALTER TABLE transcription_jobs DROP COLUMN IF EXISTS {column}"
                    )
                )
            conn.execute(text("DROP TYPE IF EXISTS sourceattemptretrydisposition"))
            conn.execute(text("DROP TYPE IF EXISTS sourceattemptstage"))
            conn.execute(text("DROP TYPE IF EXISTS outputreconciliationstatus"))
            conn.execute(text("UPDATE alembic_version SET version_num='0007_job_processing_lifecycle'"))
            tables = set(inspect(conn).get_table_names())
            assert "transcription_job_outputs" not in tables
            assert "transcription_output_reconciliations" not in tables
            assert "transcription_job_source_attempts" not in tables
            assert "transcription_job_sources" in tables
        run_alembic("head", env=env)
        with temp_engine.begin() as conn:
            assert "transcription_job_outputs" in inspect(conn).get_table_names()
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0043_yandex_disk"



def _assert_output_reconciliation_schema(inspector):
    assert "transcription_output_reconciliations" in inspector.get_table_names()
    cols = {c["name"]: c for c in inspector.get_columns("transcription_output_reconciliations")}
    assert {"id", "owner_user_id", "project_id", "job_id", "job_source_id", "reconciliation_token", "lease_generation", "attempt_number", "status", "uncertainty_reason", "expected_output_drive_folder_id", "expected_document_title", "expected_document_title_hash", "expected_document_character_count", "prepared_at", "creation_started_at", "returned_document_id", "returned_web_view_url", "returned_document_created_at", "last_checked_at", "resolved_output_id", "resolved_at", "created_at", "updated_at"}.issubset(cols)
    uniques = {tuple(u["column_names"]) for u in inspector.get_unique_constraints("transcription_output_reconciliations")}
    assert ("job_source_id",) in uniques
    assert ("reconciliation_token",) in uniques
    assert ("returned_document_id",) in uniques
    assert ("resolved_output_id",) in uniques
    assert ("owner_user_id", "project_id", "job_id", "job_source_id") in uniques
    checks = {c["name"] for c in inspector.get_check_constraints("transcription_output_reconciliations")}
    assert "ck_output_reconciliations_character_count_nonnegative" in checks
    indexes = {idx["name"]: tuple(idx["column_names"]) for idx in inspector.get_indexes("transcription_output_reconciliations")}
    assert indexes["ix_output_reconciliations_owner_user_id"] == ("owner_user_id",)
    assert indexes["ix_output_reconciliations_project_id"] == ("project_id",)
    assert indexes["ix_output_reconciliations_job_id"] == ("job_id",)
    assert indexes["ix_output_reconciliations_status"] == ("status",)
    assert indexes["ix_output_reconciliations_job_status"] == ("job_id", "status")
    fks = {tuple(fk["constrained_columns"]): fk["referred_table"] for fk in inspector.get_foreign_keys("transcription_output_reconciliations")}
    assert fks[("owner_user_id",)] == "users"
    assert fks[("project_id",)] == "projects"
    assert fks[("job_id",)] == "transcription_jobs"
    assert fks[("job_source_id",)] == "transcription_job_sources"
    assert fks[("resolved_output_id",)] == "transcription_job_outputs"


def test_output_reconciliation_current_schema_indexes_match_migration():
    _assert_output_reconciliation_schema(inspect(engine))


def test_output_reconciliation_0012_upgrade_downgrade_roundtrip_and_metadata_table(tmp_path):
    from studio_api.db import Base

    with isolated_migration_database("studio_migration_0012") as (temp_engine, env):
        run_alembic("0011_diagnostic_debug_sessions", env=env)
        with temp_engine.begin() as conn:
            # 0001 uses the current SQLAlchemy metadata baseline, so strip
            # 0012-owned reconciliation objects to create a genuine historical
            # revision-0011 shape before testing the 0012 migration itself.
            conn.execute(text("DROP TABLE IF EXISTS transcription_output_reconciliations"))
            conn.execute(text("DROP TYPE IF EXISTS outputreconciliationstatus"))
            assert "transcription_output_reconciliations" not in inspect(conn).get_table_names()
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0011_diagnostic_debug_sessions"
        run_alembic("0012_output_reconciliation_cases", env=env)
        with temp_engine.begin() as conn:
            _assert_output_reconciliation_schema(inspect(conn))
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0012_output_reconciliation_cases"
        run_alembic("0011_diagnostic_debug_sessions", env=env, command="downgrade")
        with temp_engine.begin() as conn:
            assert "transcription_output_reconciliations" not in inspect(conn).get_table_names()
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0011_diagnostic_debug_sessions"
        run_alembic("0012_output_reconciliation_cases", env=env)
        with temp_engine.begin() as conn:
            _assert_output_reconciliation_schema(inspect(conn))
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0012_output_reconciliation_cases"

    with isolated_migration_database("studio_migration_0012_metadata") as (temp_engine, env):
        Base.metadata.create_all(temp_engine)
        run_alembic("0012_output_reconciliation_cases", env=env, command="stamp")
        run_alembic("0011_diagnostic_debug_sessions", env=env, command="downgrade")
        with temp_engine.begin() as conn:
            assert "transcription_output_reconciliations" not in inspect(conn).get_table_names()
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0011_diagnostic_debug_sessions"


def output_persistence_artifact(doc_id="doc-fresh"):
    return new_google_docs_transcript_artifact(
        result=GoogleDocsCreateResult(
            doc_id,
            "Secret Title",
            "application/vnd.google-apps.document",
            f"https://docs.example/{doc_id}",
            ("folder-1",),
        ),
        created_at=LEASE_TEST_NOW,
        character_count=12,
    )


@pytest.mark.parametrize("mutate,reason", [
    (lambda job, project, rel, source: setattr(job, "cancel_requested_at", LEASE_TEST_NOW), JobOutputPersistenceReason.cancellation_requested),
    (lambda job, project, rel, source: setattr(job, "lease_owner_id", "other-owner"), JobOutputPersistenceReason.lease_not_owned),
    (lambda job, project, rel, source: setattr(job, "lease_generation", job.lease_generation + 1), JobOutputPersistenceReason.lease_not_owned),
    (lambda job, project, rel, source: setattr(job, "output_drive_folder_id", "folder-changed"), JobOutputPersistenceReason.output_folder_changed),
    (lambda job, project, rel, source: setattr(project, "archived_at", LEASE_TEST_NOW), JobOutputPersistenceReason.project_unavailable),
])
def test_output_persistence_refreshes_stale_identity_map_before_authorizing(mutate, reason):
    _, job_id = lease_test_job(status=JobStatus.queued, ready=True)
    setup = SessionLocal()
    try:
        handle = acquire_job_lease(setup, job_id=job_id, lease_owner_id="owner-1", now=LEASE_TEST_NOW, lease_ttl=LEASE_TEST_TTL)
        begin_job_processing(setup, job_id=job_id, lease_owner_id=handle.lease_owner_id, lease_generation=handle.lease_generation, now=LEASE_TEST_NOW)
        setup.commit()
    finally:
        setup.close()

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        job_a = session_a.get(TranscriptionJob, job_id)
        project_a = session_a.get(Project, job_a.project_id)
        rel_a = session_a.query(TranscriptionJobSource).filter_by(job_id=job_id).one()
        source_a = session_a.get(Source, rel_a.source_id)
        assert job_a.status == JobStatus.processing and project_a.output_drive_folder_id == "folder-1" and source_a.upload_status == SourceUploadStatus.uploaded

        job_b = session_b.get(TranscriptionJob, job_id)
        project_b = session_b.get(Project, job_b.project_id)
        rel_b = session_b.query(TranscriptionJobSource).filter_by(job_id=job_id).one()
        source_b = session_b.get(Source, rel_b.source_id)
        mutate(job_b, project_b, rel_b, source_b)
        session_b.commit()

        with pytest.raises(JobOutputPersistenceError) as exc:
            persist_processing_job_source_output_and_maybe_complete(
                session_a,
                job_id=job_id,
                job_source_id=rel_a.id,
                lease_owner_id="owner-1",
                lease_generation=handle.lease_generation,
                artifact=output_persistence_artifact(),
                now=LEASE_TEST_NOW,
            )
        assert exc.value.reason == reason
        session_a.rollback()

        verifier = SessionLocal()
        try:
            assert verifier.query(TranscriptionJobOutput).filter_by(job_id=job_id).count() == 0
            assert verifier.get(TranscriptionJob, job_id).status == JobStatus.processing
        finally:
            verifier.close()
    finally:
        session_a.close(); session_b.close()


@pytest.mark.parametrize("mutate", [
    lambda job, project, rel, source: setattr(job, "output_drive_folder_id", "folder-blocked"),
    lambda job, project, rel, source: (setattr(source, "deleted_at", LEASE_TEST_NOW), setattr(source, "upload_status", SourceUploadStatus.deleted)),
])
def test_output_persistence_authority_locks_block_concurrent_mutations(mutate):
    _, job_id = lease_test_job(status=JobStatus.queued, ready=True)
    setup = SessionLocal()
    try:
        handle = acquire_job_lease(setup, job_id=job_id, lease_owner_id="owner-1", now=LEASE_TEST_NOW, lease_ttl=LEASE_TEST_TTL)
        begin_job_processing(setup, job_id=job_id, lease_owner_id=handle.lease_owner_id, lease_generation=handle.lease_generation, now=LEASE_TEST_NOW)
        rel_id = setup.execute(select(TranscriptionJobSource.id).where(TranscriptionJobSource.job_id == job_id)).scalar_one()
        setup.commit()
    finally:
        setup.close()

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        _load_locked_output_authority(
            session_a,
            job_id=job_id,
            job_source_id=rel_id,
            lease_owner_id="owner-1",
            lease_generation=handle.lease_generation,
            output_folder_id="folder-1",
            now=LEASE_TEST_NOW,
        )

        session_b.execute(text("SET LOCAL lock_timeout = '100ms'"))
        job_b = session_b.get(TranscriptionJob, job_id)
        project_b = session_b.get(Project, job_b.project_id)
        rel_b = session_b.query(TranscriptionJobSource).filter_by(job_id=job_id).one()
        source_b = session_b.get(Source, rel_b.source_id)
        mutate(job_b, project_b, rel_b, source_b)
        with pytest.raises(OperationalError):
            session_b.flush()
        session_b.rollback()

        assert session_b.query(TranscriptionJobOutput).filter_by(job_id=job_id).count() == 0
        assert session_b.get(TranscriptionJob, job_id).status == JobStatus.processing
    finally:
        session_a.rollback(); session_a.close(); session_b.close()


def test_output_persistence_job_lock_blocks_project_archive_without_project_update_grant():
    from studio_api.main import _locked_owned_project_for_archive

    user_id, job_id = lease_test_job(status=JobStatus.queued, ready=True)
    setup = SessionLocal()
    try:
        handle = acquire_job_lease(setup, job_id=job_id, lease_owner_id="owner-1", now=LEASE_TEST_NOW, lease_ttl=LEASE_TEST_TTL)
        begin_job_processing(setup, job_id=job_id, lease_owner_id=handle.lease_owner_id, lease_generation=handle.lease_generation, now=LEASE_TEST_NOW)
        rel_id = setup.execute(select(TranscriptionJobSource.id).where(TranscriptionJobSource.job_id == job_id)).scalar_one()
        setup.commit()
    finally:
        setup.close()

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        _load_locked_output_authority(
            session_a,
            job_id=job_id,
            job_source_id=rel_id,
            lease_owner_id="owner-1",
            lease_generation=handle.lease_generation,
            output_folder_id="folder-1",
            now=LEASE_TEST_NOW,
        )

        session_b.execute(text("SET LOCAL lock_timeout = '100ms'"))
        user_b = session_b.get(User, user_id)
        with pytest.raises(OperationalError):
            _locked_owned_project_for_archive(
                session_b,
                user_b,
                session_b.get(TranscriptionJob, job_id).project_id,
            )
        session_b.rollback()

        assert session_b.get(Project, session_b.get(TranscriptionJob, job_id).project_id).archived_at is None
        assert session_b.query(TranscriptionJobOutput).filter_by(job_id=job_id).count() == 0
    finally:
        session_a.rollback(); session_a.close(); session_b.close()

def test_acquire_active_reclaim_stale_fencing_and_no_commit():
    _, job_id = lease_test_job()
    db = SessionLocal()
    try:
        job = db.get(TranscriptionJob, job_id)
        handle = acquire_job_lease(db, job_id=job.id, lease_owner_id="owner-1", now=LEASE_TEST_NOW, lease_ttl=LEASE_TEST_TTL)
        assert handle.lease_generation == 1
        assert handle.claimed_at == LEASE_TEST_NOW
        assert handle.lease_expires_at == LEASE_TEST_NOW + LEASE_TEST_TTL
        assert job.status == JobStatus.queued
        assert job.started_at is None
        other = SessionLocal()
        try:
            assert other.get(TranscriptionJob, job.id).lease_owner_id is None
        finally:
            other.close()
        db.commit()

        with pytest.raises(JobLeaseError) as exc:
            acquire_job_lease(db, job_id=job.id, lease_owner_id="owner-2", now=LEASE_TEST_NOW + timedelta(minutes=1), lease_ttl=LEASE_TEST_TTL)
        assert_lease_reason(exc, JobLeaseFailureReason.lease_active)
        db.rollback(); job = db.get(TranscriptionJob, job.id)
        assert job.lease_owner_id == "owner-1" and job.lease_generation == 1

        reclaimed = acquire_job_lease(db, job_id=job.id, lease_owner_id="owner-2", now=LEASE_TEST_NOW + timedelta(minutes=16), lease_ttl=LEASE_TEST_TTL)
        assert reclaimed.lease_generation == 2
        assert job.lease_owner_id == "owner-2"
        with pytest.raises(JobLeaseError) as exc:
            renew_job_lease(db, job_id=job.id, lease_owner_id="owner-1", lease_generation=1, now=LEASE_TEST_NOW + timedelta(minutes=17), lease_ttl=LEASE_TEST_TTL)
        assert_lease_reason(exc, JobLeaseFailureReason.lease_not_owned)
        with pytest.raises(JobLeaseError) as exc:
            release_job_lease(db, job_id=job.id, lease_owner_id="owner-1", lease_generation=1)
        assert_lease_reason(exc, JobLeaseFailureReason.lease_not_owned)
    finally:
        db.close()


def test_two_sessions_cannot_both_claim_active_lease():
    _, job_id = lease_test_job()
    first = SessionLocal(); second = SessionLocal()
    try:
        first_handle = acquire_job_lease(first, job_id=job_id, lease_owner_id="owner-1", now=LEASE_TEST_NOW, lease_ttl=LEASE_TEST_TTL)
        first.commit()
        with pytest.raises(JobLeaseError) as exc:
            acquire_job_lease(second, job_id=job_id, lease_owner_id="owner-2", now=LEASE_TEST_NOW + timedelta(minutes=1), lease_ttl=LEASE_TEST_TTL)
        assert_lease_reason(exc, JobLeaseFailureReason.lease_active)
        second.rollback()
        stored = second.get(TranscriptionJob, job_id)
        assert stored.lease_owner_id == "owner-1"
        assert stored.lease_generation == first_handle.lease_generation
    finally:
        first.close(); second.close()



def test_claim_next_skip_locked_claims_next_unlocked_job():
    _, oldest_id = lease_test_job()
    _, next_id = lease_test_job()
    setup = SessionLocal()
    try:
        setup.get(TranscriptionJob, oldest_id).created_at = LEASE_TEST_NOW
        setup.get(TranscriptionJob, next_id).created_at = LEASE_TEST_NOW + timedelta(seconds=1)
        setup.commit()
    finally:
        setup.close()

    locker = SessionLocal(); claimer = SessionLocal(); verifier = SessionLocal()
    try:
        locker.execute(
            select(TranscriptionJob)
            .where(TranscriptionJob.id == oldest_id)
            .with_for_update()
        ).scalar_one()

        handle = acquire_next_ready_job_lease(
            claimer,
            lease_owner_id="owner-b",
            now=LEASE_TEST_NOW + timedelta(minutes=1),
            lease_ttl=LEASE_TEST_TTL,
        )
        assert handle is not None
        assert handle.job_id == next_id
        assert handle.lease_owner_id == "owner-b"
        assert handle.lease_generation == 1
        claimer.commit()

        stored = verifier.get(TranscriptionJob, next_id)
        assert stored.lease_owner_id == handle.lease_owner_id
        assert stored.lease_generation == handle.lease_generation
        assert verifier.get(TranscriptionJob, oldest_id).lease_owner_id is None
    finally:
        locker.rollback(); claimer.rollback(); verifier.close(); locker.close(); claimer.close()


def test_concurrent_claim_next_callers_do_not_receive_same_job():
    _, first_id = lease_test_job()
    _, second_id = lease_test_job()
    setup = SessionLocal()
    try:
        setup.get(TranscriptionJob, first_id).created_at = LEASE_TEST_NOW
        setup.get(TranscriptionJob, second_id).created_at = LEASE_TEST_NOW + timedelta(seconds=1)
        setup.commit()
    finally:
        setup.close()

    first = SessionLocal(); second = SessionLocal(); verifier = SessionLocal()
    try:
        first_handle = acquire_next_ready_job_lease(first, lease_owner_id="owner-1", now=LEASE_TEST_NOW + timedelta(minutes=1), lease_ttl=LEASE_TEST_TTL)
        second_handle = acquire_next_ready_job_lease(second, lease_owner_id="owner-2", now=LEASE_TEST_NOW + timedelta(minutes=1), lease_ttl=LEASE_TEST_TTL)
        assert first_handle is not None and second_handle is not None
        assert first_handle.job_id != second_handle.job_id
        first.commit(); second.commit()
        for handle in (first_handle, second_handle):
            stored = verifier.get(TranscriptionJob, handle.job_id)
            assert stored.lease_owner_id == handle.lease_owner_id
            assert stored.lease_generation == handle.lease_generation
    finally:
        first.rollback(); second.rollback(); verifier.close(); first.close(); second.close()


def test_claim_next_with_unready_oldest_does_not_prelock_later_ready_candidate():
    _, unready_id = lease_test_job(ready=False)
    _, first_ready_id = lease_test_job()
    _, second_ready_id = lease_test_job()
    setup = SessionLocal()
    try:
        setup.get(TranscriptionJob, unready_id).created_at = LEASE_TEST_NOW
        setup.get(TranscriptionJob, first_ready_id).created_at = LEASE_TEST_NOW + timedelta(seconds=1)
        setup.get(TranscriptionJob, second_ready_id).created_at = LEASE_TEST_NOW + timedelta(seconds=2)
        setup.commit()
    finally:
        setup.close()

    first = SessionLocal(); second = SessionLocal(); verifier = SessionLocal()
    try:
        first_handle = acquire_next_ready_job_lease(
            first,
            lease_owner_id="owner-1",
            now=LEASE_TEST_NOW + timedelta(minutes=1),
            lease_ttl=LEASE_TEST_TTL,
        )
        assert first_handle is not None
        assert first_handle.job_id == first_ready_id

        second_handle = acquire_next_ready_job_lease(
            second,
            lease_owner_id="owner-2",
            now=LEASE_TEST_NOW + timedelta(minutes=1),
            lease_ttl=LEASE_TEST_TTL,
        )
        assert second_handle is not None
        assert second_handle.job_id == second_ready_id
        assert second_handle.job_id != first_handle.job_id

        first.commit(); second.commit()
        for handle in (first_handle, second_handle):
            stored = verifier.get(TranscriptionJob, handle.job_id)
            assert stored.lease_owner_id == handle.lease_owner_id
            assert stored.lease_generation == handle.lease_generation
        assert verifier.get(TranscriptionJob, unready_id).lease_owner_id is None
    finally:
        first.rollback(); second.rollback(); verifier.close(); first.close(); second.close()

def test_renew_and_strict_release_semantics():
    _, job_id = lease_test_job()
    db = SessionLocal()
    try:
        job = db.get(TranscriptionJob, job_id)
        handle = acquire_job_lease(db, job_id=job.id, lease_owner_id="owner", now=LEASE_TEST_NOW, lease_ttl=LEASE_TEST_TTL)
        renewed = renew_job_lease(db, job_id=job.id, lease_owner_id="owner", lease_generation=handle.lease_generation, now=LEASE_TEST_NOW + timedelta(minutes=5), lease_ttl=timedelta(minutes=30))
        assert renewed.lease_generation == handle.lease_generation
        assert renewed.lease_expires_at == LEASE_TEST_NOW + timedelta(minutes=35)
        assert release_job_lease(db, job_id=job.id, lease_owner_id="owner", lease_generation=handle.lease_generation) is True
        assert job.lease_owner_id is None and job.lease_expires_at is None and job.lease_generation == 1
        with pytest.raises(JobLeaseError) as exc:
            release_job_lease(db, job_id=job.id, lease_owner_id="owner", lease_generation=handle.lease_generation)
        assert_lease_reason(exc, JobLeaseFailureReason.lease_not_owned)
    finally:
        db.close()


def test_expired_terminal_unready_and_invalid_leases_fail_closed():
    _, job_id = lease_test_job(ready=False)
    db = SessionLocal()
    try:
        with pytest.raises(JobLeaseError) as exc:
            acquire_job_lease(db, job_id=job_id, lease_owner_id="owner", now=LEASE_TEST_NOW, lease_ttl=LEASE_TEST_TTL)
        assert_lease_reason(exc, JobLeaseFailureReason.job_not_ready)
        with pytest.raises(JobLeaseError) as exc:
            acquire_job_lease(db, job_id=job_id, lease_owner_id=" ", now=LEASE_TEST_NOW, lease_ttl=LEASE_TEST_TTL)
        assert_lease_reason(exc, JobLeaseFailureReason.invalid_owner)
        with pytest.raises(JobLeaseError) as exc:
            acquire_job_lease(db, job_id=job_id, lease_owner_id="owner", now=LEASE_TEST_NOW, lease_ttl=timedelta(0))
        assert_lease_reason(exc, JobLeaseFailureReason.invalid_ttl)
    finally:
        db.close()

    _, terminal_job_id = lease_test_job(status=JobStatus.completed)
    db = SessionLocal()
    try:
        with pytest.raises(JobLeaseError) as exc:
            acquire_job_lease(db, job_id=terminal_job_id, lease_owner_id="owner", now=LEASE_TEST_NOW, lease_ttl=LEASE_TEST_TTL)
        assert_lease_reason(exc, JobLeaseFailureReason.job_not_queued)
    finally:
        db.close()

    _, expiring_job_id = lease_test_job()
    db = SessionLocal()
    try:
        handle = acquire_job_lease(db, job_id=expiring_job_id, lease_owner_id="owner", now=LEASE_TEST_NOW, lease_ttl=LEASE_TEST_TTL)
        with pytest.raises(JobLeaseError) as exc:
            renew_job_lease(db, job_id=expiring_job_id, lease_owner_id="owner", lease_generation=handle.lease_generation, now=LEASE_TEST_NOW + timedelta(minutes=16), lease_ttl=LEASE_TEST_TTL)
        assert_lease_reason(exc, JobLeaseFailureReason.lease_not_active)
    finally:
        db.close()


def test_cancel_clears_lease_and_public_payloads_are_safe():
    user_id, job_id = lease_test_job()
    db = SessionLocal()
    try:
        job = db.get(TranscriptionJob, job_id)
        user = db.get(User, user_id)
        handle = acquire_job_lease(db, job_id=job.id, lease_owner_id="internal-owner", now=LEASE_TEST_NOW, lease_ttl=LEASE_TEST_TTL)
        db.commit()
        client = TestClient(app); csrf = login(client, "correct horse battery", user.email)
        headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
        r = client.post(f"/api/jobs/{job.id}/cancel", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "cancelled"
        for key in ["lease_owner_id", "lease_generation", "claimed_at", "lease_expires_at"]:
            assert key not in body
        db.refresh(job)
        generation = handle.lease_generation
        assert job.lease_owner_id is None and job.lease_expires_at is None and job.lease_generation == generation

        stale = SessionLocal()
        try:
            with pytest.raises(JobLeaseError) as exc:
                renew_job_lease(stale, job_id=job_id, lease_owner_id="internal-owner", lease_generation=generation, now=LEASE_TEST_NOW, lease_ttl=LEASE_TEST_TTL)
            assert_lease_reason(exc, JobLeaseFailureReason.job_not_queued)
            stale.rollback()
        finally:
            stale.close()

        stale = SessionLocal()
        try:
            with pytest.raises(JobLeaseError) as exc:
                release_job_lease(stale, job_id=job_id, lease_owner_id="internal-owner", lease_generation=generation)
            assert_lease_reason(exc, JobLeaseFailureReason.lease_not_owned)
            stale.rollback()
        finally:
            stale.close()

        assert client.post(f"/api/jobs/{job_id}/cancel", headers=headers).status_code == 200
        db.rollback()
        audit_text = "\n".join(event.metadata_json for event in db.query(AuditEvent).all())
        assert "internal-owner" not in audit_text
    finally:
        db.close()


def test_invalidate_job_lease_preserves_claim_history_and_generation():
    _, job_id = lease_test_job()
    db = SessionLocal()
    try:
        job = db.get(TranscriptionJob, job_id)
        handle = acquire_job_lease(db, job_id=job.id, lease_owner_id="owner", now=LEASE_TEST_NOW, lease_ttl=LEASE_TEST_TTL)
        original_claimed_at = job.claimed_at
        original_generation = job.lease_generation
        assert original_claimed_at == handle.claimed_at
        assert original_generation == handle.lease_generation

        invalidate_job_lease(job)
        db.flush()

        assert job.lease_owner_id is None
        assert job.lease_expires_at is None
        assert job.claimed_at == original_claimed_at
        assert job.lease_generation == original_generation
    finally:
        db.close()


def test_active_lease_helper():
    _, job_id = lease_test_job()
    db = SessionLocal()
    try:
        job = db.get(TranscriptionJob, job_id)
        acquire_job_lease(db, job_id=job.id, lease_owner_id="owner", now=LEASE_TEST_NOW, lease_ttl=LEASE_TEST_TTL)
        assert is_lease_active(job, LEASE_TEST_NOW + timedelta(minutes=14)) is True
        assert is_lease_active(job, (LEASE_TEST_NOW + timedelta(minutes=14)).replace(tzinfo=None)) is True
        assert is_lease_active(job, (LEASE_TEST_NOW + timedelta(minutes=14)).astimezone(timezone(timedelta(hours=3)))) is True
        assert is_lease_active(job, LEASE_TEST_NOW + timedelta(minutes=15)) is False
        assert is_lease_active(job, (LEASE_TEST_NOW + timedelta(minutes=15)).astimezone(timezone(timedelta(hours=3)))) is False
        assert is_lease_active(job, LEASE_TEST_NOW + timedelta(minutes=16)) is False

        job.lease_owner_id = None
        assert is_lease_active(job, LEASE_TEST_NOW + timedelta(minutes=14)) is False
        job.lease_owner_id = "owner"
        job.lease_expires_at = None
        assert is_lease_active(job, LEASE_TEST_NOW + timedelta(minutes=14)) is False
    finally:
        db.close()


def test_reloaded_aware_lease_accepts_naive_worker_clock_for_processing():
    _, job_id = lease_test_job(status=JobStatus.queued, ready=True)
    naive_now = LEASE_TEST_NOW.replace(tzinfo=None)
    db = SessionLocal()
    try:
        handle = acquire_job_lease(db, job_id=job_id, lease_owner_id="owner", now=naive_now, lease_ttl=LEASE_TEST_TTL)
        assert handle.lease_expires_at.tzinfo is None
        db.commit()
        db.expire_all()

        reloaded_job = db.get(TranscriptionJob, job_id)
        assert reloaded_job.lease_expires_at.tzinfo is not None
        assert reloaded_job.lease_expires_at.utcoffset() == timedelta(0)
        assert is_lease_active(reloaded_job, naive_now) is True

        result = begin_job_processing(db, job_id=job_id, lease_owner_id="owner", lease_generation=handle.lease_generation, now=naive_now)
        assert result.status == JobStatus.processing
        assert reloaded_job.status == JobStatus.processing
        assert result.attempt_count == 1
        assert reloaded_job.attempt_count == 1
    finally:
        db.close()


def test_begin_processing_cancellation_failure_and_recovery_lifecycle():
    _, job_id = lease_test_job()
    db = SessionLocal()
    try:
        job = db.get(TranscriptionJob, job_id)
        handle = acquire_job_lease(db, job_id=job.id, lease_owner_id="owner", now=LEASE_TEST_NOW, lease_ttl=LEASE_TEST_TTL)
        result = begin_job_processing(db, job_id=job.id, lease_owner_id="owner", lease_generation=handle.lease_generation, now=LEASE_TEST_NOW + timedelta(minutes=1))
        assert result.status == JobStatus.processing
        assert job.status == JobStatus.processing
        assert job.attempt_count == 1
        assert job.started_at == LEASE_TEST_NOW + timedelta(minutes=1)
        assert job.lease_owner_id == "owner" and job.lease_generation == handle.lease_generation
        other = SessionLocal()
        try:
            assert other.get(TranscriptionJob, job.id).status == JobStatus.queued
        finally:
            other.close()
        with pytest.raises(JobLeaseError) as exc:
            release_job_lease(db, job_id=job.id, lease_owner_id="owner", lease_generation=handle.lease_generation)
        assert_lease_reason(exc, JobLeaseFailureReason.lease_not_releasable)
        renewed = renew_job_lease(db, job_id=job.id, lease_owner_id="owner", lease_generation=handle.lease_generation, now=LEASE_TEST_NOW + timedelta(minutes=2), lease_ttl=LEASE_TEST_TTL)
        assert renewed.lease_generation == handle.lease_generation
        db.commit()

        client = TestClient(app)
        user = db.get(User, job.owner_user_id)
        csrf = login(client, "correct horse battery", user.email)
        headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
        response = client.post(f"/api/jobs/{job.id}/cancel", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "processing"
        assert body["cancel_requested_at"] is not None
        assert body["attempt_count"] == 1
        for key in ["lease_owner_id", "lease_generation", "claimed_at", "lease_expires_at"]:
            assert key not in body
        db.refresh(job)
        original_requested_at = job.cancel_requested_at
        assert job.lease_owner_id == "owner"
        assert client.post(f"/api/jobs/{job.id}/cancel", headers=headers).json()["cancel_requested_at"] == original_requested_at.isoformat()
        events = [e.event_type for e in db.query(AuditEvent).filter(AuditEvent.event_type == "job.cancel_requested").all()]
        assert events == ["job.cancel_requested"]
        with pytest.raises(JobProcessingError) as exc:
            fail_job_processing(db, job_id=job.id, lease_owner_id="owner", lease_generation=handle.lease_generation, now=LEASE_TEST_NOW + timedelta(minutes=3), error_code="provider", error_message="safe")
        assert exc.value.reason == JobProcessingFailureReason.cancellation_requested
        ack = acknowledge_job_cancellation(db, job_id=job.id, lease_owner_id="owner", lease_generation=handle.lease_generation, now=LEASE_TEST_NOW + timedelta(minutes=4))
        assert ack.status == JobStatus.cancelled
        assert job.finished_at == LEASE_TEST_NOW + timedelta(minutes=4)
        assert job.lease_owner_id is None and job.lease_expires_at is None
    finally:
        db.close()


def test_processing_failure_and_expired_recovery_paths():
    _, job_id = lease_test_job()
    db = SessionLocal()
    try:
        job = db.get(TranscriptionJob, job_id)
        handle = acquire_job_lease(db, job_id=job.id, lease_owner_id="owner", now=LEASE_TEST_NOW, lease_ttl=LEASE_TEST_TTL)
        begin_job_processing(db, job_id=job.id, lease_owner_id="owner", lease_generation=handle.lease_generation, now=LEASE_TEST_NOW + timedelta(minutes=1))
        with pytest.raises(JobProcessingError):
            fail_job_processing(db, job_id=job.id, lease_owner_id="stale", lease_generation=handle.lease_generation, now=LEASE_TEST_NOW + timedelta(minutes=2), error_code="x", error_message="x")
        fail_job_processing(db, job_id=job.id, lease_owner_id="owner", lease_generation=handle.lease_generation, now=LEASE_TEST_NOW + timedelta(minutes=2), error_code="raw_provider", error_message="token leaked")
        assert job.status == JobStatus.failed
        assert job.error_code == "Недоступно" and job.error_message == "Недоступно"
        assert job.lease_owner_id is None
    finally:
        db.close()


def test_expired_processing_recovery_fails_closed_without_current_attempt_evidence():
    _, recover_id = lease_test_job()
    db = SessionLocal()
    try:
        job = db.get(TranscriptionJob, recover_id)
        h = acquire_job_lease(db, job_id=job.id, lease_owner_id="owner", now=LEASE_TEST_NOW, lease_ttl=timedelta(minutes=1))
        begin_job_processing(db, job_id=job.id, lease_owner_id="owner", lease_generation=h.lease_generation, now=LEASE_TEST_NOW)
        started_at = job.started_at
        original_claimed_at = job.claimed_at
        original_generation = job.lease_generation
        with pytest.raises(JobProcessingError) as exc:
            recover_expired_processing_job(db, job_id=job.id, now=LEASE_TEST_NOW + timedelta(seconds=30))
        assert exc.value.reason == JobProcessingFailureReason.lease_active
        recover_expired_processing_job(db, job_id=job.id, now=LEASE_TEST_NOW + timedelta(minutes=2))
        assert job.status == JobStatus.failed
        assert job.error_code == "retry_recovery_state_unknown"
        assert job.error_message == "retry_recovery_state_unknown"
        assert job.lease_owner_id is None
        assert job.lease_expires_at is None
        assert job.claimed_at == original_claimed_at
        assert job.lease_generation == original_generation
        assert job.attempt_count == 1 and job.started_at == started_at
    finally:
        db.close()


def test_expired_processing_recovery_requeues_with_current_prepared_attempt_evidence():
    _, recover_id = lease_test_job()
    db = SessionLocal()
    try:
        job = db.get(TranscriptionJob, recover_id)
        h = acquire_job_lease(db, job_id=job.id, lease_owner_id="owner", now=LEASE_TEST_NOW, lease_ttl=timedelta(minutes=1))
        begin_job_processing(db, job_id=job.id, lease_owner_id="owner", lease_generation=h.lease_generation, now=LEASE_TEST_NOW)
        rel = db.query(TranscriptionJobSource).filter_by(job_id=job.id).one()
        db.add(TranscriptionJobSourceAttempt(owner_user_id=job.owner_user_id, project_id=job.project_id, job_id=job.id, job_source_id=rel.id, attempt_number=1, stage=SourceAttemptStage.prepared, retry_disposition=SourceAttemptRetryDisposition.undetermined, created_at=LEASE_TEST_NOW, updated_at=LEASE_TEST_NOW))
        db.commit()
        started_at = job.started_at
        original_claimed_at = job.claimed_at
        original_generation = job.lease_generation
        recover_expired_processing_job(db, job_id=job.id, now=LEASE_TEST_NOW + timedelta(minutes=2))
        assert job.status == JobStatus.queued
        assert job.finished_at is None and job.error_code is None and job.error_message is None
        assert job.lease_owner_id is None
        assert job.lease_expires_at is None
        assert job.claimed_at == original_claimed_at
        assert job.lease_generation == original_generation
        assert job.attempt_count == 1 and job.started_at == started_at
        next_claimed_at = LEASE_TEST_NOW + timedelta(minutes=3)
        next_handle = acquire_job_lease(db, job_id=job.id, lease_owner_id="owner-2", now=next_claimed_at, lease_ttl=LEASE_TEST_TTL)
        assert job.claimed_at == next_claimed_at
        assert job.claimed_at != original_claimed_at
        assert job.lease_owner_id == "owner-2"
        assert job.lease_expires_at == next_claimed_at + LEASE_TEST_TTL
        assert job.lease_generation == original_generation + 1
        begin_job_processing(db, job_id=job.id, lease_owner_id="owner-2", lease_generation=next_handle.lease_generation, now=LEASE_TEST_NOW + timedelta(minutes=4))
        assert job.attempt_count == 2 and job.started_at == started_at
    finally:
        db.close()

JOB_OUTPUT_TOP_KEYS = {"job_id", "job_status", "output_count", "outputs"}
JOB_OUTPUT_ENTRY_KEYS = {"source_id", "source_position", "source_name", "source_type", "output_kind", "transcript_standard", "web_view_url", "link_available", "document_character_count", "document_created_at", "persisted_at"}


def create_job_with_sources(email="job-output@example.com", names=("one.mp4",)):
    c, headers, pid = create_logged_in_project(email)
    source_ids = [create_gdrive_source(c, headers, pid, name) for name in names]
    prepare_legacy_job_authority(c, headers, pid)
    r = c.post(f"/api/projects/{pid}/jobs", json={"source_ids": source_ids}, headers=headers)
    assert r.status_code == 200
    return c, headers, pid, r.json()["id"], source_ids


JOB_PROGRESS_TOP_KEYS = {
    "job_id",
    "job_status",
    "tracking_precision",
    "completed_source_count",
    "total_source_count",
    "active_source_position",
    "current_stage",
    "sources",
}
JOB_PROGRESS_SOURCE_KEYS = {
    "position",
    "name",
    "status",
    "provider_parts",
    "stages",
}
JOB_PROGRESS_STAGE_KEYS = {"key", "status", "applicability"}


def test_project_job_progress_is_owner_scoped_no_store_and_browser_safe():
    c1, _h1, pid1, jid1, _source_ids1 = create_job_with_sources(
        "job-progress-owner@example.com",
        ("progress-video.mp4",),
    )
    c2, _h2, pid2, _jid2, _source_ids2 = create_job_with_sources(
        "job-progress-other@example.com",
        ("other-private.mp4",),
    )

    response = c1.get(f"/api/projects/{pid1}/jobs/progress")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    body = response.json()
    assert set(body) == {"jobs", "limit", "truncated"}
    assert body["limit"] == 100
    assert body["truncated"] is False
    assert len(body["jobs"]) == 1
    progress = body["jobs"][0]
    assert set(progress) == JOB_PROGRESS_TOP_KEYS
    assert progress["job_id"] == jid1
    assert progress["job_status"] == "queued"
    assert progress["tracking_precision"] == "checkpoint"
    assert progress["active_source_position"] is None
    assert progress["current_stage"] is None
    assert set(progress["sources"][0]) == JOB_PROGRESS_SOURCE_KEYS
    assert progress["sources"][0]["name"] == "progress-video.mp4"
    assert all(
        set(stage) == JOB_PROGRESS_STAGE_KEYS
        for stage in progress["sources"][0]["stages"]
    )
    assert "other-private.mp4" not in response.text
    for marker in (
        "lease_owner_id",
        "lease_generation",
        "claimed_at",
        "provider_credential_id",
        "s3_bucket",
        "s3_object_key",
        "drive_file_id",
        "drive_file_url",
        "failure_code",
    ):
        assert marker not in response.text

    explicit = c1.get(
        f"/api/projects/{pid1}/jobs/progress", params=[("job_id", jid1)]
    )
    assert explicit.status_code == 200
    assert explicit.json()["limit"] == 1
    assert explicit.json()["truncated"] is False
    assert [row["job_id"] for row in explicit.json()["jobs"]] == [jid1]
    assert c1.get(
        f"/api/projects/{pid1}/jobs/progress",
        params=[("job_id", jid1), ("job_id", jid1)],
    ).status_code == 422
    assert c1.get(
        f"/api/projects/{pid1}/jobs/progress",
        params=[("job_id", str(uuid.uuid4())) for _ in range(51)],
    ).status_code == 422

    anon = TestClient(app)
    assert anon.get(f"/api/projects/{pid1}/jobs/progress").status_code == 401
    assert c1.get(f"/api/projects/{pid2}/jobs/progress").status_code == 404


def test_project_transcription_analytics_is_owner_scoped_no_store_and_aggregate_only():
    c1, _h1, pid1, _jid1, _source_ids1 = create_job_with_sources(
        "analytics-owner@example.com",
        ("analytics-private-source.mp4",),
    )
    _c2, _h2, pid2, _jid2, _source_ids2 = create_job_with_sources(
        "analytics-other@example.com",
        ("other-private-source.mp4",),
    )

    response = c1.get(f"/api/projects/{pid1}/transcription-analytics")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    body = response.json()
    assert set(body) == {
        "scope",
        "totals",
        "outcomes",
        "success",
        "configuration",
        "usage_cost",
        "durations",
    }
    assert body["scope"] == "project_all_time"
    assert body["totals"] == {"jobs": 1, "sources": 1, "outputs": 0}
    assert body["outcomes"] == {
        "queued": 1,
        "processing": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
    }
    assert body["success"] == {
        "successful_jobs": 0,
        "terminal_jobs": 0,
        "percentage": None,
    }
    assert body["configuration"] == {
        "provider_model": {
            "elevenlabs_scribe_v2": 1,
            "yandex_general": 0,
            "yandex_deferred_general": 0,
            "unknown": 0,
        },
        "language_mode": {"ru": 0, "en": 0, "detect": 1, "other": 0},
        "diarization": {"enabled": 0, "disabled": 1},
    }
    assert body["usage_cost"] == {
        "confirmed_billed_duration_seconds": 0.0,
        "confirmed_provider_cost": "0.00000000",
        "currency": "USD",
        "cost_basis": "confirmed_audio_duration_x_rate_snapshot",
        "complete_jobs": 0,
        "uncertain_jobs": 0,
        "unavailable_jobs": 0,
        "in_progress_jobs": 1,
    }
    assert all(
        summary == {
            "sample_count": 0,
            "average_seconds": None,
            "p50_seconds": None,
            "p95_seconds": None,
        }
        for summary in body["durations"].values()
    )
    for private_marker in (
        pid1,
        "analytics-private-source.mp4",
        "other-private-source.mp4",
        "folder-test",
        "provider_credential_id",
        "document_id",
        "web_view_url",
        "provider_request_started_at",
        "failure_code",
    ):
        assert private_marker not in response.text

    anon = TestClient(app)
    assert (
        anon.get(f"/api/projects/{pid1}/transcription-analytics").status_code
        == 401
    )
    assert (
        c1.get(f"/api/projects/{pid2}/transcription-analytics").status_code
        == 404
    )


def test_history_and_analytics_clear_are_confirmed_owner_scoped_resets():
    c1, headers1, pid1, jid1, source_ids1 = create_job_with_sources(
        "clear-owner@example.com",
        ("clear-owner-source.mp4",),
    )
    _c2, _headers2, pid2, _jid2, _source_ids2 = create_job_with_sources(
        "clear-other@example.com",
        ("clear-other-source.mp4",),
    )
    with SessionLocal() as db:
        job = db.get(TranscriptionJob, jid1)
        job.status = JobStatus.completed
        job.finished_at = utcnow() - timedelta(seconds=1)
        recovery_job = TranscriptionJob(
            project_id=job.project_id,
            owner_user_id=job.owner_user_id,
            status=JobStatus.failed,
            provider="elevenlabs",
            title="Задача, требующая решения",
            attempt_count=1,
            started_at=utcnow() - timedelta(minutes=2),
            finished_at=utcnow() - timedelta(seconds=1),
            error_code="partial_provider_result",
        )
        db.add(recovery_job)
        db.flush()
        recovery_source = TranscriptionJobSource(
            job_id=recovery_job.id,
            source_id=source_ids1[0],
            position=0,
            status=JobSourceStatus.queued,
        )
        db.add(recovery_source)
        db.flush()
        db.add(
            TranscriptionJobSourceAttempt(
                owner_user_id=job.owner_user_id,
                project_id=job.project_id,
                job_id=recovery_job.id,
                job_source_id=recovery_source.id,
                attempt_number=1,
                stage=SourceAttemptStage.failed,
                retry_disposition=(
                    SourceAttemptRetryDisposition.provider_outcome_uncertain
                ),
                failure_code="partial_provider_result",
                provider_request_started_at=utcnow() - timedelta(minutes=1),
                failed_at=utcnow() - timedelta(seconds=1),
            )
        )
        db.commit()
        recovery_job_id = recovery_job.id

    for path in (
        f"/api/projects/{pid1}/history/clear",
        f"/api/projects/{pid1}/transcription-analytics/clear",
    ):
        assert c1.post(
            path,
            json={"confirm_clear": False},
            headers=headers1,
        ).status_code == 422
    assert c1.post(
        f"/api/projects/{pid2}/history/clear",
        json={"confirm_clear": True},
        headers=headers1,
    ).status_code == 404

    history = c1.post(
        f"/api/projects/{pid1}/history/clear",
        json={"confirm_clear": True},
        headers=headers1,
    )
    assert history.status_code == 200
    assert history.json()["hidden_job_count"] == 1
    assert history.json()["preserved_job_count"] == 1
    visible_jobs = c1.get(f"/api/projects/{pid1}/jobs").json()
    assert visible_jobs["next_cursor"] is None
    assert visible_jobs["page_size"] == 50
    assert [row["id"] for row in visible_jobs["jobs"]] == [recovery_job_id]
    assert visible_jobs["jobs"][0]["history_attention_required"] is True

    analytics = c1.post(
        f"/api/projects/{pid1}/transcription-analytics/clear",
        json={"confirm_clear": True},
        headers=headers1,
    )
    assert analytics.status_code == 200
    assert analytics.json()["hidden_job_count"] == 2
    reset_payload = c1.get(
        f"/api/projects/{pid1}/transcription-analytics"
    ).json()
    assert reset_payload["scope"] == "project_since_reset"
    assert reset_payload["totals"] == {"jobs": 0, "sources": 0, "outputs": 0}

    with SessionLocal() as db:
        assert db.query(TranscriptionJob).filter_by(id=jid1).count() == 1
        assert (
            db.query(TranscriptionJob).filter_by(id=recovery_job_id).count()
            == 1
        )
        project = db.get(Project, pid1)
        assert project.history_reset_at is not None
        assert project.analytics_reset_at is not None
        events = {
            row.event_type: row
            for row in db.query(AuditEvent).filter(
                AuditEvent.event_type.in_(["history.cleared", "analytics.cleared"])
            )
        }
        assert set(events) == {"history.cleared", "analytics.cleared"}
        owner_id = db.get(TranscriptionJob, jid1).owner_user_id
        assert all(
            event.actor_user_id == owner_id
            and event.subject_user_id == owner_id
            and event.metadata_json == "{}"
            for event in events.values()
        )


def _add_uncertain_history_job(project_id: str, source_id: str, *, created_at: datetime):
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        job = TranscriptionJob(
            project_id=project_id,
            owner_user_id=project.owner_user_id,
            status=JobStatus.failed,
            provider="elevenlabs",
            title="Старый неопределённый результат",
            attempt_count=1,
            created_at=created_at,
            started_at=created_at,
            finished_at=created_at + timedelta(minutes=1),
            error_code="partial_provider_result",
        )
        db.add(job)
        db.flush()
        relation = TranscriptionJobSource(
            job_id=job.id,
            source_id=source_id,
            position=0,
            status=JobSourceStatus.queued,
        )
        db.add(relation)
        db.flush()
        db.add(
            TranscriptionJobSourceAttempt(
                owner_user_id=project.owner_user_id,
                project_id=project_id,
                job_id=job.id,
                job_source_id=relation.id,
                attempt_number=1,
                stage=SourceAttemptStage.failed,
                retry_disposition=SourceAttemptRetryDisposition.provider_outcome_uncertain,
                failure_code="partial_provider_result",
                provider_request_started_at=created_at,
                failed_at=created_at + timedelta(minutes=1),
            )
        )
        db.commit()
        return job.id


def test_active_provider_attempt_never_requires_history_resolution():
    client, _headers, project_id, job_id, _source_ids = create_job_with_sources(
        "active-attention@example.com",
        ("active-attention-source.mp4",),
    )
    with SessionLocal() as db:
        job = db.get(TranscriptionJob, job_id)
        job.status = JobStatus.processing
        job.started_at = utcnow() - timedelta(minutes=1)
        relation = (
            db.query(TranscriptionJobSource)
            .filter(TranscriptionJobSource.job_id == job_id)
            .one()
        )
        db.add(
            TranscriptionJobSourceAttempt(
                owner_user_id=job.owner_user_id,
                project_id=project_id,
                job_id=job_id,
                job_source_id=relation.id,
                attempt_number=1,
                stage=SourceAttemptStage.provider_request_started,
                retry_disposition=(
                    SourceAttemptRetryDisposition.provider_outcome_uncertain
                ),
                provider_request_started_at=utcnow() - timedelta(seconds=30),
            )
        )
        db.commit()

    response = client.get(f"/api/projects/{project_id}/jobs")
    assert response.status_code == 200
    active_job = next(row for row in response.json()["jobs"] if row["id"] == job_id)
    assert active_job["status"] == "processing"
    assert active_job["history_attention_required"] is False


def test_uncertain_job_attention_resolution_is_explicit_owner_scoped_and_replay_safe(monkeypatch):
    client, headers, project_id = create_logged_in_project(
        "attention-resolution@example.com"
    )
    other, other_headers, _ = create_logged_in_project(
        "attention-resolution-other@example.com"
    )
    source_id = create_gdrive_source(
        client, headers, project_id, "attention-source.mp4"
    )
    old_created_at = utcnow() - timedelta(days=1)
    uncertain_job_id = _add_uncertain_history_job(
        project_id, source_id, created_at=old_created_at
    )
    acknowledged_job_id = _add_uncertain_history_job(
        project_id, source_id, created_at=old_created_at + timedelta(minutes=2)
    )
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        later_job = TranscriptionJob(
            project_id=project_id,
            owner_user_id=project.owner_user_id,
            status=JobStatus.completed,
            provider="elevenlabs",
            title="Подтверждённый поздний результат",
            created_at=old_created_at + timedelta(hours=1),
            finished_at=old_created_at + timedelta(hours=2),
        )
        db.add(later_job)
        db.flush()
        relation = TranscriptionJobSource(
            job_id=later_job.id,
            source_id=source_id,
            position=0,
            status=JobSourceStatus.queued,
        )
        db.add(relation)
        db.flush()
        db.add(
            TranscriptionJobOutput(
                job_id=later_job.id,
                job_source_id=relation.id,
                document_id="confirmed-later-document",
                web_view_url="https://docs.google.com/document/d/confirmed-later-document/edit",
                output_drive_folder_id="confirmed-folder",
                output_kind="google_docs_transcript",
                transcript_standard="transcript_doc",
                document_character_count=42,
                document_created_at=later_job.finished_at,
                persisted_at=later_job.finished_at,
                lease_generation=1,
            )
        )
        db.commit()
        later_job_id = later_job.id

    reconciliation_endpoint = f"/api/jobs/{uncertain_job_id}/output-reconciliation"
    candidates = client.get(reconciliation_endpoint)
    assert candidates.status_code == 200
    assert [row["id"] for row in candidates.json()["attention_candidates"]] == [later_job_id]
    assert other.get(reconciliation_endpoint).status_code == 404
    def unexpected_google_refresh(*args, **kwargs):
        raise AssertionError("No Google request is allowed without reconciliation cases")
    monkeypatch.setattr("studio_api.google_connection_access.refresh_user_google_drive_access_token", unexpected_google_refresh)
    check = client.post(reconciliation_endpoint + "/check", headers=headers)
    assert check.status_code == 200
    assert check.json() == {"job_id": uncertain_job_id, "checked": 0, "resolved": 0, "unresolved": 0, "conflicts": 0}

    endpoint = f"/api/jobs/{uncertain_job_id}/attention-resolution"
    linked_payload = {
        "resolution": "linked_later_result",
        "linked_job_id": later_job_id,
        "confirm_possible_spend": True,
    }
    assert client.post(endpoint, json=linked_payload).status_code == 403
    assert other.post(
        endpoint, json=linked_payload, headers=other_headers
    ).status_code == 404
    assert client.post(
        endpoint,
        json={**linked_payload, "confirm_possible_spend": False},
        headers=headers,
    ).status_code == 422
    assert client.post(
        endpoint,
        json={**linked_payload, "linked_job_id": uncertain_job_id},
        headers=headers,
    ).status_code == 409

    linked = client.post(endpoint, json=linked_payload, headers=headers)
    assert linked.status_code == 200
    assert linked.json()["history_attention_required"] is False
    assert linked.json()["history_attention_resolution"] == "linked_later_result"
    assert linked.json()["history_attention_linked_job_id"] == later_job_id
    assert linked.json()["history_attention_resolved_at"]
    assert linked.json()["terminal_dismissed_at"]
    replay = client.post(endpoint, json=linked_payload, headers=headers)
    assert replay.status_code == 200
    assert replay.json()["history_attention_resolved_at"] == linked.json()[
        "history_attention_resolved_at"
    ]
    conflict = client.post(
        endpoint,
        json={
            "resolution": "acknowledged_no_result",
            "linked_job_id": None,
            "confirm_possible_spend": True,
        },
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["reason"] == "attention_resolution_conflict"

    acknowledge_endpoint = f"/api/jobs/{acknowledged_job_id}/attention-resolution"
    acknowledged = client.post(
        acknowledge_endpoint,
        json={
            "resolution": "acknowledged_no_result",
            "linked_job_id": None,
            "confirm_possible_spend": True,
        },
        headers=headers,
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["history_attention_resolution"] == "acknowledged_no_result"
    assert acknowledged.json()["history_attention_linked_job_id"] is None

    with SessionLocal() as db:
        events = db.query(AuditEvent).filter_by(
            event_type="job.history_attention_resolved"
        ).all()
        assert len(events) == 2
        assert {json.loads(event.metadata_json)["resolution"] for event in events} == {
            "acknowledged_no_result",
            "linked_later_result",
        }
        assert all(
            json.loads(event.metadata_json)["possible_provider_spend_acknowledged"]
            is True
            for event in events
        )


def test_manifest_clear_hides_old_accepted_evidence_without_deleting_it():
    from studio_api.transcript_catalog import (
        ExistingResultMatchStatus,
        current_effective_settings,
        load_existing_result_matches,
    )

    client, headers, _pid, job_id, source_ids = create_job_with_sources(
        "manifest-clear@example.com",
        ("manifest-clear-source.mp4",),
    )
    output_id = add_output_row(
        job_id,
        source_ids[0],
        doc_id="manifest-clear-document",
        persisted_at=utcnow() - timedelta(days=1),
        output_kind="google_docs_transcript",
    )
    with SessionLocal() as db:
        owner_id = db.get(TranscriptionJob, job_id).owner_user_id
        source = db.get(Source, source_ids[0])
        before = load_existing_result_matches(
            db,
            owner_user_id=owner_id,
            sources=[source],
            target_settings=current_effective_settings(
                language_mode="detect",
                diarization_enabled=False,
            ),
        )[source.id]
    assert before.status == ExistingResultMatchStatus.accepted_match

    assert client.post(
        "/api/transcript-catalog/clear",
        json={"confirm_clear": False},
        headers=headers,
    ).status_code == 422
    response = client.post(
        "/api/transcript-catalog/clear",
        json={"confirm_clear": True},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["hidden_evidence_count"] == 1

    with SessionLocal() as db:
        owner_id = db.get(TranscriptionJob, job_id).owner_user_id
        source = db.get(Source, source_ids[0])
        after = load_existing_result_matches(
            db,
            owner_user_id=owner_id,
            sources=[source],
            target_settings=current_effective_settings(
                language_mode="detect",
                diarization_enabled=False,
            ),
        )[source.id]
        assert db.get(TranscriptionJobOutput, output_id) is not None
        assert db.get(User, owner_id).manifest_reset_at is not None
        assert db.query(AuditEvent).filter_by(
            event_type="transcript_catalog.cleared",
            actor_user_id=owner_id,
        ).count() == 1
    assert after.status == ExistingResultMatchStatus.no_match


def add_output_row(job_id, source_id, *, url="https://docs.google.com/document/d/doc/edit", doc_id=None, persisted_at=None, output_id=None, output_kind="google_doc_transcript"):
    db = SessionLocal()
    try:
        rel = db.query(TranscriptionJobSource).filter_by(job_id=job_id, source_id=source_id).one()
        now = persisted_at or utcnow()
        values = {"id": output_id} if output_id is not None else {}
        output = TranscriptionJobOutput(
            **values,
            job_id=job_id,
            job_source_id=rel.id,
            document_id=doc_id or f"doc-{job_id}-{source_id}",
            web_view_url=url,
            output_drive_folder_id="folder-secret-marker",
            output_kind=output_kind,
            transcript_standard="transcript_doc",
            document_character_count=42,
            document_created_at=now,
            persisted_at=now,
            lease_generation=3,
        )
        db.add(output)
        db.commit()
        return output.id
    finally:
        db.close()


def test_transcript_catalog_query_is_owner_scoped_and_uses_accepted_output_authority():
    from studio_api.models import (
        TranscriptCatalogDocumentStandardStatus,
        TranscriptCatalogEntry,
        TranscriptCatalogSettingsStatus,
        TranscriptCatalogSourceIdentityKind,
    )
    from studio_api.transcript_catalog import (
        ExistingResultMatchStatus,
        current_effective_settings,
        load_existing_result_matches,
    )

    _c1, _h1, _pid1, jid1, source_ids1 = create_job_with_sources(
        "catalog-query-owner@example.com",
        ("shared-drive-source.mp4",),
    )
    _c2, _h2, _pid2, jid2, source_ids2 = create_job_with_sources(
        "catalog-query-other@example.com",
        ("shared-drive-source.mp4",),
    )
    add_output_row(
        jid1,
        source_ids1[0],
        doc_id="catalog-owner-doc",
        output_kind="google_docs_transcript",
    )
    add_output_row(
        jid2,
        source_ids2[0],
        doc_id="catalog-other-doc",
        output_kind="google_docs_transcript",
    )

    db = SessionLocal()
    try:
        source_row = db.get(Source, source_ids1[0])
        owner_user_id = db.get(TranscriptionJob, jid1).owner_user_id
        other_owner_user_id = db.get(TranscriptionJob, jid2).owner_user_id
        exact_catalog_values = {
            "document_name": "Catalog evidence",
            "transcript_standard": "transcript_doc",
            "standard_status": TranscriptCatalogDocumentStandardStatus.current,
            "settings_status": TranscriptCatalogSettingsStatus.exact,
            "provider": "elevenlabs",
            "model": "scribe_v2",
            "language_mode": "detect",
            "diarization_enabled": False,
            "source_identity_kind": (
                TranscriptCatalogSourceIdentityKind.google_drive_file
            ),
            "source_identity_value": source_row.drive_file_id,
        }
        db.add_all(
            [
                TranscriptCatalogEntry(
                    owner_user_id=owner_user_id,
                    document_id="catalog-owner-doc",
                    **exact_catalog_values,
                ),
                TranscriptCatalogEntry(
                    owner_user_id=owner_user_id,
                    document_id="catalog-linked-only-doc",
                    **exact_catalog_values,
                ),
                TranscriptCatalogEntry(
                    owner_user_id=other_owner_user_id,
                    document_id="catalog-other-owner-linked-doc",
                    **exact_catalog_values,
                ),
            ]
        )
        db.commit()
        match = load_existing_result_matches(
            db,
            owner_user_id=owner_user_id,
            sources=[source_row],
            target_settings=current_effective_settings(
                language_mode="detect",
                diarization_enabled=False,
            ),
        )[source_ids1[0]]
    finally:
        db.close()

    assert match.status == ExistingResultMatchStatus.accepted_match
    # The linked catalog row extends authority, the same Google document is
    # counted once across both tables, and the other owner's row is ignored.
    assert match.accepted_output_count == 2
    assert match.matching_settings_count == 2


def test_job_output_authentication_and_no_csrf_required():
    c, headers, _pid, jid, source_ids = create_job_with_sources("job-output-auth@example.com")
    add_output_row(jid, source_ids[0], doc_id="doc-output-auth")
    anon = TestClient(app)
    assert anon.get(f"/api/jobs/{jid}/outputs").status_code == 401
    r = c.get(f"/api/jobs/{jid}/outputs")
    assert r.status_code == 200
    assert r.json()["output_count"] == 1


def test_job_output_owner_scoped_success_exact_shapes():
    c1, _h1, _pid1, jid1, source_ids1 = create_job_with_sources("job-output-owner1@example.com")
    c2, _h2, _pid2, jid2, source_ids2 = create_job_with_sources("job-output-owner2@example.com")
    add_output_row(jid1, source_ids1[0], url="https://docs.google.com/document/d/own/edit", doc_id="doc-output-owner-1")
    add_output_row(jid2, source_ids2[0], url="https://docs.google.com/document/d/other/edit", doc_id="doc-output-owner-2")
    body = c1.get(f"/api/jobs/{jid1}/outputs").json()
    assert set(body) == JOB_OUTPUT_TOP_KEYS
    assert body["job_id"] == jid1 and body["job_status"] == "queued" and body["output_count"] == 1
    assert set(body["outputs"][0]) == JOB_OUTPUT_ENTRY_KEYS
    assert body["outputs"][0]["source_id"] == source_ids1[0]
    assert "other" not in repr(body)
    assert c1.get(f"/api/jobs/{jid2}/outputs").status_code == 404


def test_job_output_missing_and_cross_owner_are_generic_404():
    c1, _h1, _pid1, _jid1, _source_ids1 = create_job_with_sources("job-output-404-owner@example.com")
    c2, _h2, _pid2, jid2, _source_ids2 = create_job_with_sources("job-output-404-other@example.com")
    missing = c1.get("/api/jobs/00000000-0000-0000-0000-000000000000/outputs")
    cross = c1.get(f"/api/jobs/{jid2}/outputs")
    assert missing.status_code == 404 and cross.status_code == 404
    assert missing.text == cross.text


def test_job_output_empty_owned_queued_job():
    c, _headers, _pid, jid, _source_ids = create_job_with_sources("job-output-empty@example.com")
    r = c.get(f"/api/jobs/{jid}/outputs")
    assert r.status_code == 200
    assert r.json() == {"job_id": jid, "job_status": "queued", "output_count": 0, "outputs": []}


@pytest.mark.parametrize("status_value", [JobStatus.processing, JobStatus.failed, JobStatus.cancelled, JobStatus.completed])
def test_job_output_partial_outputs_for_non_queued_statuses(status_value):
    c, _headers, _pid, jid, source_ids = create_job_with_sources(f"job-output-partial-{status_value.value}@example.com")
    add_output_row(jid, source_ids[0], doc_id=f"doc-output-partial-{status_value.value}")
    db = SessionLocal()
    try:
        job = db.get(TranscriptionJob, jid)
        job.status = status_value
        db.commit()
    finally:
        db.close()
    body = c.get(f"/api/jobs/{jid}/outputs").json()
    assert body["job_status"] == status_value.value
    assert body["output_count"] == 1


def test_job_output_deterministic_ordering_and_hidden_output_id():
    c, _headers, _pid, jid, source_ids = create_job_with_sources(
        "job-output-order@example.com",
        ("position-primary.mp4", "timestamp-late.mp4", "timestamp-early.mp4", "id-b.mp4", "id-a.mp4"),
    )
    db = SessionLocal()
    try:
        relations = db.query(TranscriptionJobSource).filter_by(job_id=jid).all()
        by_source_id = {rel.source_id: rel for rel in relations}
        by_source_id[source_ids[0]].position = 0
        by_source_id[source_ids[1]].position = 1
        by_source_id[source_ids[2]].position = 1
        by_source_id[source_ids[3]].position = 2
        by_source_id[source_ids[4]].position = 2
        db.commit()
    finally:
        db.close()

    base = datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc)
    id_position_primary = add_output_row(
        jid,
        source_ids[0],
        doc_id="doc-output-order-position",
        persisted_at=base + timedelta(hours=1),
        output_id="order-output-position-primary",
    )
    id_timestamp_late = add_output_row(
        jid,
        source_ids[1],
        doc_id="doc-output-order-timestamp-late",
        persisted_at=base + timedelta(minutes=2),
        output_id="order-output-timestamp-late",
    )
    id_timestamp_early = add_output_row(
        jid,
        source_ids[2],
        doc_id="doc-output-order-timestamp-early",
        persisted_at=base + timedelta(minutes=1),
        output_id="order-output-timestamp-early",
    )
    id_tiebreaker_b = add_output_row(
        jid,
        source_ids[3],
        doc_id="doc-output-order-id-b",
        persisted_at=base + timedelta(minutes=3),
        output_id="order-output-id-b",
    )
    id_tiebreaker_a = add_output_row(
        jid,
        source_ids[4],
        doc_id="doc-output-order-id-a",
        persisted_at=base + timedelta(minutes=3),
        output_id="order-output-id-a",
    )

    response = c.get(f"/api/jobs/{jid}/outputs")
    body = response.json()
    assert [o["source_id"] for o in body["outputs"]] == [
        source_ids[0],
        source_ids[2],
        source_ids[1],
        source_ids[4],
        source_ids[3],
    ]
    assert [o["source_position"] for o in body["outputs"]] == [0, 1, 1, 2, 2]
    assert [o["source_name"] for o in body["outputs"]] == [
        "position-primary.mp4",
        "timestamp-early.mp4",
        "timestamp-late.mp4",
        "id-a.mp4",
        "id-b.mp4",
    ]
    assert all("id" not in o and "output_id" not in o for o in body["outputs"])
    for output_id in [id_position_primary, id_timestamp_late, id_timestamp_early, id_tiebreaker_a, id_tiebreaker_b]:
        assert output_id not in response.text


def test_job_output_mixed_url_safety_preserves_entries_and_hides_secret_url():
    c, _headers, _pid, jid, source_ids = create_job_with_sources("job-output-url@example.com", ("safe.mp4", "unsafe.mp4"))
    safe = "https://docs.google.com/document/d/safe/edit?tab=t#h"
    unsafe = "https://user:secret-output-token@docs.google.com/document/d/unsafe/edit"
    add_output_row(jid, source_ids[0], url=safe, doc_id="doc-output-url-safe")
    add_output_row(jid, source_ids[1], url=unsafe, doc_id="doc-output-url-unsafe")
    r = c.get(f"/api/jobs/{jid}/outputs")
    body = r.json()
    assert body["output_count"] == 2
    assert body["outputs"][0]["web_view_url"] == safe
    assert body["outputs"][0]["link_available"] is True
    assert body["outputs"][1]["web_view_url"] is None
    assert body["outputs"][1]["link_available"] is False
    assert unsafe not in r.text and "secret-output-token" not in r.text


def test_job_output_forbidden_fields_and_secret_markers_absent():
    c, _headers, _pid, jid, source_ids = create_job_with_sources("job-output-forbidden@example.com")
    add_output_row(jid, source_ids[0], doc_id="secret-doc-marker", url="https://docs.google.com/document/d/safe/edit")
    db = SessionLocal()
    try:
        source = db.get(Source, source_ids[0])
        source.drive_file_id = "secret-drive-id-marker"
        source.drive_file_url = "https://drive.google.com/secret-drive-url-marker"
        source.s3_bucket = "secret-bucket-marker"
        source.s3_object_key = "secret-object-key-marker"
        output = db.query(TranscriptionJobOutput).filter_by(job_id=jid).one()
        output.output_drive_folder_id = "secret-folder-marker"
        output.lease_generation = 123
        db.commit()
    finally:
        db.close()
    r = c.get(f"/api/jobs/{jid}/outputs")
    for marker in ["secret-doc-marker", "secret-drive-id-marker", "secret-drive-url-marker", "secret-bucket-marker", "secret-object-key-marker", "secret-folder-marker", "lease_generation", "job_source_id"]:
        assert marker not in r.text


def test_job_output_list_adds_only_safe_primary_document_without_expanding_detail():
    c, _headers, pid, jid, source_ids = create_job_with_sources("job-output-compat@example.com")
    add_output_row(jid, source_ids[0], doc_id="doc-output-compat", url="https://docs.google.com/document/d/compat/edit")
    detail = c.get(f"/api/jobs/{jid}")
    listed = c.get(f"/api/projects/{pid}/jobs")
    for response in [detail, listed]:
        assert response.status_code == 200
        assert "outputs" not in response.json()
        assert "doc-output-compat" not in response.text
    assert "compat/edit" not in detail.text
    assert listed.json()["jobs"][0]["primary_output_url"] == "https://docs.google.com/document/d/compat/edit"
    assert detail.json()["source_names"] == ["one.mp4"]
    assert listed.json()["jobs"][0]["source_names"] == ["one.mp4"]


def test_primary_output_urls_are_owner_scoped_even_for_mixed_requested_job_ids():
    from studio_api.job_output_read import load_primary_output_urls
    c1, _h1, _p1, jid1, sources1 = create_job_with_sources("primary-owner@example.com")
    _c2, _h2, _p2, jid2, sources2 = create_job_with_sources("primary-other@example.com")
    add_output_row(jid1, sources1[0], doc_id="primary-owner-doc", url="https://docs.google.com/document/d/owner/edit")
    add_output_row(jid2, sources2[0], doc_id="primary-other-doc", url="https://docs.google.com/document/d/other/edit")
    with SessionLocal() as db:
        owner = db.get(TranscriptionJob, jid1).owner_user_id
        assert load_primary_output_urls(db, owner_user_id=owner, job_ids=[jid1, jid2]) == {jid1: "https://docs.google.com/document/d/owner/edit"}
        assert load_primary_output_urls(db, owner_user_id=owner, job_ids=[]) == {}


def test_job_output_archived_project_matches_existing_job_detail_authority():
    c, headers, pid, jid, source_ids = create_job_with_sources("job-output-archived@example.com")
    add_output_row(jid, source_ids[0], doc_id="doc-output-archived")
    c.post(f"/api/projects/{pid}/archive", headers=headers)
    detail = c.get(f"/api/jobs/{jid}")
    outputs = c.get(f"/api/jobs/{jid}/outputs")
    assert detail.status_code == outputs.status_code == 200
    assert outputs.json()["output_count"] == 1


def test_job_output_unexpected_query_failure_is_generic(monkeypatch):
    c, _headers, _pid, jid, _source_ids = create_job_with_sources("job-output-failure@example.com")
    secret = "secret-sql-url-token traceback SELECT * FROM transcription_job_outputs"
    def fail(_db, _job_id):
        raise RuntimeError(secret)
    monkeypatch.setattr("studio_api.main.load_browser_job_output_rows", fail)
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.update(c.cookies)
    r = client.get(f"/api/jobs/{jid}/outputs")
    assert r.status_code == 500
    assert secret not in r.text
    for marker in ["secret-sql-url-token", "traceback", "SELECT", jid, "transcription_job_outputs"]:
        assert marker not in r.text


def test_google_scope_parser_exact_primary_boundary():
    from studio_api.google_scopes import has_drive_file_scope, has_drive_readonly_scope, has_picker_browser_scope_boundary
    assert has_drive_file_scope("openid email https://www.googleapis.com/auth/drive.file")
    assert has_drive_file_scope("  https://www.googleapis.com/auth/drive.file   openid ")
    assert not has_drive_file_scope("openid email")
    assert not has_drive_file_scope("https://www.googleapis.com/auth/drive.file.extra")
    assert has_drive_readonly_scope("https://www.googleapis.com/auth/drive.readonly")
    assert not has_drive_readonly_scope("https://www.googleapis.com/auth/drive.readonly.extra")
    assert not has_picker_browser_scope_boundary("openid email https://www.googleapis.com/auth/drive.file")
    assert has_picker_browser_scope_boundary("openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly")
    assert has_picker_browser_scope_boundary("openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly")
    assert not has_picker_browser_scope_boundary("openid email")
    assert not has_picker_browser_scope_boundary("openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/calendar.readonly")


def _connect_google_for_test(user_id: str, scopes: str = "openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly"):
    from studio_api.models import GoogleConnection, GoogleConnectionStatus, GoogleProvider
    from studio_api.google_connection_access import google_token_aad
    db = SessionLocal()
    try:
        conn = GoogleConnection(user_id=user_id, provider=GoogleProvider.google, status=GoogleConnectionStatus.active, google_email="g@example.com", scopes=scopes, created_at=utcnow(), connected_at=utcnow())
        db.add(conn); db.flush()
        ct, nonce = encrypt("refresh-token-test", master_key_from_b64(Path(os.environ["STUDIO_CREDENTIAL_MASTER_KEY_FILE"]).read_text()), google_token_aad(user_id, conn.id))
        conn.refresh_token_ciphertext = ct; conn.refresh_token_nonce = nonce; conn.key_id = "studio-v1"
        db.commit(); return conn.id
    finally:
        db.close()


def test_google_picker_session_csrf_scope_config_and_safe_response(monkeypatch):
    import studio_api.main as main
    pw = admin(); c = TestClient(app); csrf = login(c, pw)
    db = SessionLocal(); user = db.query(User).first(); uid = user.id; db.close()
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    assert c.post("/api/google/picker/session", headers={"origin": "https://evil.test", "x-csrf-token": csrf}).status_code == 403
    assert c.post("/api/google/picker/session", headers={"origin": "https://studio.test", "x-csrf-token": "bad"}).status_code == 403
    unavailable = c.post("/api/google/picker/session", headers=headers)
    assert unavailable.status_code == 503
    assert unavailable.json() == {"detail": "google_picker_not_configured"}
    monkeypatch.setattr(main.settings, "google_picker_api_key", "public-key")
    monkeypatch.setattr(main.settings, "google_picker_app_id", "123456")
    assert c.post("/api/google/picker/session", headers=headers).status_code == 404
    _connect_google_for_test(uid, "openid email")
    assert c.post("/api/google/picker/session", headers=headers).status_code == 409
    with engine.begin() as conn:
        conn.execute(text("UPDATE google_connections SET scopes='openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly'"))
    config_missing = c.post("/api/google/picker/session", headers=headers)
    assert config_missing.status_code == 503
    assert config_missing.json() == {"detail": "google_config_unavailable"}
    from studio_api.google_connection_access import GoogleConnectionAccessError, GoogleConnectionAccessReason
    monkeypatch.setattr(
        "studio_api.google_connection_access.refresh_user_google_drive_access_token",
        lambda *a, **k: (_ for _ in ()).throw(
            GoogleConnectionAccessError(
                GoogleConnectionAccessReason.reauthorization_required
            )
        ),
    )
    reconnect = c.post("/api/google/picker/session", headers=headers)
    assert reconnect.status_code == 409
    assert reconnect.json() == {"detail": "google_reauthorization_required"}
    monkeypatch.setattr(
        "studio_api.google_connection_access.refresh_user_google_drive_access_token",
        lambda *a, **k: (_ for _ in ()).throw(
            GoogleConnectionAccessError(GoogleConnectionAccessReason.token_unavailable)
        ),
    )
    transient = c.post("/api/google/picker/session", headers=headers)
    assert transient.status_code == 502
    assert transient.json() == {"detail": "google_token_unavailable"}
    monkeypatch.setattr("studio_api.google_connection_access.refresh_user_google_drive_access_token", lambda *a, **k: "short-access-token")
    r = c.post("/api/google/picker/session", headers=headers)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["pragma"] == "no-cache"
    body = r.json()
    assert body == {"access_token": "short-access-token", "api_key": "public-key", "app_id": "123456", "scope_ready": True}
    assert "refresh" not in r.text and "cipher" not in r.text and "key_id" not in r.text


def test_direct_drive_upload_session_and_completion_are_bound_and_server_verified(monkeypatch):
    import studio_api.main as main
    from types import SimpleNamespace
    from studio_api.direct_drive_upload import DirectDriveUploadResult

    pw = admin("direct-drive@example.com")
    c = TestClient(app)
    csrf = login(c, pw, "direct-drive@example.com")
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    project_id = c.post(
        "/api/projects", json={"title": "Direct Drive"}, headers=headers
    ).json()["id"]
    other_project_id = c.post(
        "/api/projects", json={"title": "Other"}, headers=headers
    ).json()["id"]
    db = SessionLocal()
    user_id = db.query(User).filter_by(email="direct-drive@example.com").one().id
    db.close()
    _connect_google_for_test(user_id)
    monkeypatch.setattr(
        "studio_api.google_connection_access.refresh_user_google_drive_access_token", lambda *a, **k: "memory-token"
    )
    folder_calls = []

    def verify_folder(token, folder_id):
        folder_calls.append((token, folder_id))
        return SimpleNamespace(id=folder_id, name="Results", web_view_url=None)

    monkeypatch.setattr(main, "verify_output_folder_selection", verify_folder)
    operation_id = "123e4567-e89b-42d3-a456-426614174000"
    file_payload = {
        "operation_id": operation_id,
        "original_filename": "Короткая запись.wav",
        "mime_type": "audio/wav",
        "size_bytes": 5,
    }
    session = c.post(
        f"/api/projects/{project_id}/direct-drive-uploads/session",
        json={"folder_id": "folder-id", "files": [file_payload]},
        headers=headers,
    )
    assert session.status_code == 200
    assert session.headers["cache-control"] == "no-store"
    assert session.headers["pragma"] == "no-cache"
    session_body = session.json()
    assert session_body["access_token"] == "memory-token"
    assert session_body["folder"] == {"name": "Results"}
    assert session_body["policy"]["max_files"] == 20
    assert session_body["uploads"][0]["operation_id"] == operation_id
    capability = session_body["uploads"][0]["capability"]
    assert "refresh-token" not in session.text

    verify_calls = []

    def verify_result(token, *, file_id, folder_id, descriptor):
        verify_calls.append((token, file_id, folder_id, descriptor))
        return DirectDriveUploadResult(
            name=descriptor.original_filename,
            mime_type=descriptor.mime_type,
            size_bytes=descriptor.size_bytes,
            web_view_url="https://drive.google.com/file/d/drive-file-id/view",
        )

    monkeypatch.setattr(main, "verify_direct_drive_upload_result", verify_result)
    complete_payload = {
        **file_payload,
        "folder_id": "folder-id",
        "file_id": "drive-file-id",
        "capability": capability,
    }
    completed = c.post(
        f"/api/projects/{project_id}/direct-drive-uploads/complete",
        json=complete_payload,
        headers=headers,
    )
    assert completed.status_code == 200
    assert completed.headers["cache-control"] == "no-store"
    assert completed.json() == {
        "name": "Короткая запись.wav",
        "mime_type": "audio/wav",
        "size_bytes": 5,
        "web_view_url": "https://drive.google.com/file/d/drive-file-id/view",
    }
    assert "memory-token" not in completed.text
    assert capability not in completed.text
    assert "drive-file-id" not in completed.text.replace(
        "https://drive.google.com/file/d/drive-file-id/view", ""
    )
    assert len(verify_calls) == 1
    assert folder_calls == [
        ("memory-token", "folder-id"),
        ("memory-token", "folder-id"),
    ]
    assert c.post(
        f"/api/projects/{other_project_id}/direct-drive-uploads/complete",
        json=complete_payload,
        headers=headers,
    ).status_code == 409
    assert c.post(
        f"/api/projects/{project_id}/direct-drive-uploads/session",
        json={
            "folder_id": "folder-id",
            "files": [{**file_payload, "mime_type": "text/plain"}],
        },
        headers=headers,
    ).status_code == 422
    db = SessionLocal()
    try:
        assert db.query(Source).filter_by(project_id=project_id).count() == 0
    finally:
        db.close()


def test_google_picker_source_and_output_selection_revalidates_server_metadata(monkeypatch):
    import studio_api.main as main
    from studio_api.google_drive import GoogleDriveMetadata, GOOGLE_FOLDER_MIME_TYPE
    from studio_api.job_output_destination import DriveFolderAuthorizationMetadata
    pw = admin(); c = TestClient(app); csrf = login(c, pw)
    db = SessionLocal(); uid = db.query(User).first().id; db.close(); _connect_google_for_test(uid)
    monkeypatch.setattr("studio_api.google_connection_access.refresh_user_google_drive_access_token", lambda *a, **k: "access")
    metas = {
        "file-a": GoogleDriveMetadata("file-a", "Backend A.mp3", "audio/mpeg", 10, "https://drive.google.com/file/d/file-a/view", "2025-12-01T10:20:30Z", None, False),
        "file-b": GoogleDriveMetadata("file-b", "Backend B.mp4", "video/mp4", 20, "https://drive.google.com/file/d/file-b/view", "2025-12-02T11:21:31+00:00", None, False),
        "folder": GoogleDriveMetadata("folder", "Results", GOOGLE_FOLDER_MIME_TYPE, None, "https://drive.google.com/drive/folders/folder", None, None, True),
        "bad": GoogleDriveMetadata("bad", "Doc", "application/pdf", 5, "https://drive.google.com/file/d/bad/view", None, None, False),
    }
    monkeypatch.setattr("studio_api.google_drive.fetch_drive_file_metadata", lambda token, did: metas[did])
    folder_metas = {
        "folder": DriveFolderAuthorizationMetadata("folder", GOOGLE_FOLDER_MIME_TYPE, False, True, "Results", "https://drive.google.com/drive/folders/folder"),
        "file-a": DriveFolderAuthorizationMetadata("file-a", "audio/mpeg", False, True, "Backend A.mp3", "https://drive.google.com/file/d/file-a/view"),
        "mismatch": DriveFolderAuthorizationMetadata("other-folder", GOOGLE_FOLDER_MIME_TYPE, False, True, "Mismatch", "https://drive.google.com/drive/folders/other-folder"),
        "trashed": DriveFolderAuthorizationMetadata("trashed", GOOGLE_FOLDER_MIME_TYPE, True, True, "Trashed", "https://drive.google.com/drive/folders/trashed"),
        "readonly": DriveFolderAuthorizationMetadata("readonly", GOOGLE_FOLDER_MIME_TYPE, False, False, "Read only", "https://drive.google.com/drive/folders/readonly"),
    }
    monkeypatch.setattr("studio_api.job_output_folder_selection._fetch_drive_folder_authorization_metadata", lambda token, did: folder_metas[did])
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    pid = c.post("/api/projects", json={"title":"Picker"}, headers=headers).json()["id"]
    assert c.post(f"/api/projects/{pid}/sources/google-picker", json={"file_ids": []}, headers=headers).status_code == 422
    assert c.post(f"/api/projects/{pid}/sources/google-picker", json={"file_ids": ["file-a", "file-a"]}, headers=headers).status_code == 422
    assert c.post(f"/api/projects/{pid}/sources/google-picker", json={"file_ids": ["folder"]}, headers=headers).status_code == 422
    assert c.post(f"/api/projects/{pid}/sources/google-picker", json={"file_ids": ["bad"]}, headers=headers).status_code == 422
    r = c.post(f"/api/projects/{pid}/sources/google-picker", json={"file_ids": ["file-b", "file-a"]}, headers=headers)
    assert r.status_code == 200
    assert [s["original_filename"] for s in r.json()["sources"]] == ["Backend B.mp4", "Backend A.mp3"]
    metas["file-c"] = GoogleDriveMetadata("file-c", "Лекция 1. Личность как психологическое явление.flac", "audio/flac", 30, "https://drive.google.com/file/d/file-c/view", "2025-12-03T12:22:32Z", None, False)
    r = c.post(f"/api/projects/{pid}/sources/google-picker", json={"file_ids": ["file-c"]}, headers=headers)
    assert r.status_code == 200
    body = r.json()["sources"][0]
    assert body["original_filename"] == "Лекция 1. Личность как психологическое явление.flac"
    assert "drive_file_id" not in body
    assert "s3_bucket" not in body
    assert "s3_object_key" not in body
    for private_key in ["storage_cleanup_owner_id", "storage_cleanup_generation", "storage_cleanup_claimed_at", "storage_cleanup_lease_expires_at", "storage_cleanup_attempt_count", "storage_cleanup_error_code"]:
        assert private_key not in body
    assert body["drive_file_url"] == "https://drive.google.com/file/d/file-c/view"
    assert body["mime_type"] == "audio/flac"
    assert body["size_bytes"] == 30
    assert body["source_created_at"] == "2025-12-03T12:22:32+00:00"
    assert body["source_created_at_provenance"] == "google_drive_created_time"
    assert "client" not in r.text.lower()
    assert c.post(f"/api/projects/{pid}/output-folder/google-picker", json={"folder_id":"file-a"}, headers=headers).status_code == 422
    assert c.post(f"/api/projects/{pid}/output-folder/google-picker", json={"folder_id":"mismatch"}, headers=headers).status_code == 422
    assert c.post(f"/api/projects/{pid}/output-folder/google-picker", json={"folder_id":"trashed"}, headers=headers).status_code == 422
    assert c.post(f"/api/projects/{pid}/output-folder/google-picker", json={"folder_id":"readonly"}, headers=headers).status_code == 422
    r = c.post(f"/api/projects/{pid}/output-folder/google-picker", json={"folder_id":"folder"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["output_drive_folder_id"] == "folder"
    assert r.json()["output_drive_folder_name"] == "Results"
    assert r.json()["output_drive_folder_url"] == "https://drive.google.com/drive/folders/folder"
    assert "access" not in r.text and "canAddChildren" not in r.text and "capabilities" not in r.text

    saved = c.post(
        "/api/output-folder-favorites/google-picker",
        json={"folder_id": "folder"},
        headers=headers,
    )
    assert saved.status_code == 200
    favorite = saved.json()
    assert favorite["drive_folder_id"] == "folder"
    assert favorite["name"] == "Results"
    assert favorite["web_view_url"] == "https://drive.google.com/drive/folders/folder"
    assert "access" not in saved.text and "capabilities" not in saved.text
    refreshed = c.post(
        "/api/output-folder-favorites/google-picker",
        json={"folder_id": "folder"},
        headers=headers,
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["id"] == favorite["id"]
    listed = c.get("/api/output-folder-favorites")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()["favorites"]] == [favorite["id"]]
    assert c.delete(
        f"/api/output-folder-favorites/{favorite['id']}",
        headers=headers,
    ).status_code == 200
    assert c.get("/api/output-folder-favorites").json() == {"favorites": []}


def test_output_folder_favorite_uses_canonical_url_when_drive_omits_link():
    from studio_api.main import verified_output_folder_url

    assert verified_output_folder_url("safe-folder_123", None) == (
        "https://drive.google.com/drive/folders/safe-folder_123"
    )


def test_google_drive_source_folder_preview_is_side_effect_free_and_apply_rejects_drift(monkeypatch):
    import studio_api.main as main
    import studio_api.google_drive_folder_intake as folder_intake
    from studio_api.google_drive import GoogleDriveMetadata
    from studio_api.google_drive_folder_intake import (
        DriveFolderAcceptedItem,
        DriveFolderPreview,
        DriveFolderSkippedItem,
        DriveFolderSkipReason,
    )

    pw = admin("drive-folder-intake@example.com")
    c = TestClient(app)
    csrf = login(c, pw, "drive-folder-intake@example.com")
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    pid = c.post(
        "/api/projects", json={"title": "Folder intake"}, headers=headers
    ).json()["id"]
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email="drive-folder-intake@example.com").one()
        user_id = user.id
    finally:
        db.close()
    _connect_google_for_test(user_id)
    monkeypatch.setattr(
        main, "refreshed_google_drive_access_token", lambda *a, **k: "access"
    )

    def item(item_id, name):
        meta = GoogleDriveMetadata(
            item_id,
            name,
            "audio/mpeg",
            10,
            f"https://drive.google.com/file/d/{item_id}/view",
            "2026-08-20T10:00:00Z",
            None,
            False,
        )
        return DriveFolderAcceptedItem(meta, f"Calls/{name}", "audio/mpeg")

    current = {
        "preview": DriveFolderPreview(
            folder_id="folder-source",
            folder_name="Calls",
            total_file_count=3,
            folder_count=2,
            supported_count=2,
            accepted=(item("file-a", "a.mp3"), item("file-b", "b.mp3")),
            skipped=(
                DriveFolderSkippedItem(
                    "notes", "Calls/notes.pdf", DriveFolderSkipReason.unsupported
                ),
            ),
            blocker=None,
            complete=True,
        )
    }
    monkeypatch.setattr(
        folder_intake,
        "inspect_drive_source_folder",
        lambda *a, **k: current["preview"],
    )

    preview = c.post(
        f"/api/projects/{pid}/sources/google-folder/preview",
        json={"folder_id": "folder-source"},
        headers=headers,
    )
    assert preview.status_code == 200
    assert preview.headers["cache-control"] == "no-store"
    body = preview.json()
    assert body["folder"] == {"id": "folder-source", "name": "Calls"}
    assert body["supported_count"] == 2
    assert body["skipped_count"] == 1
    assert [row["relative_path"] for row in body["accepted"]] == [
        "Calls/a.mp3",
        "Calls/b.mp3",
    ]
    assert len(body["preview_token"]) == 64
    db = SessionLocal()
    try:
        assert db.query(Source).filter_by(project_id=pid).count() == 0
    finally:
        db.close()

    current["preview"] = DriveFolderPreview(
        **{
            **current["preview"].__dict__,
            "accepted": (item("file-a", "renamed.mp3"), item("file-b", "b.mp3")),
        }
    )
    drifted = c.post(
        f"/api/projects/{pid}/sources/google-folder/apply",
        json={
            "folder_id": "folder-source",
            "preview_token": body["preview_token"],
        },
        headers=headers,
    )
    assert drifted.status_code == 409
    assert drifted.json() == {"detail": "google_drive_folder_changed"}
    db = SessionLocal()
    try:
        assert db.query(Source).filter_by(project_id=pid).count() == 0
    finally:
        db.close()

    refreshed = c.post(
        f"/api/projects/{pid}/sources/google-folder/preview",
        json={"folder_id": "folder-source"},
        headers=headers,
    ).json()
    applied = c.post(
        f"/api/projects/{pid}/sources/google-folder/apply",
        json={
            "folder_id": "folder-source",
            "preview_token": refreshed["preview_token"],
        },
        headers=headers,
    )
    assert applied.status_code == 200
    assert [source["original_filename"] for source in applied.json()["sources"]] == [
        "renamed.mp3",
        "b.mp3",
    ]
    assert applied.headers["cache-control"] == "no-store"
    db = SessionLocal()
    try:
        assert db.query(Source).filter_by(project_id=pid).count() == 2
    finally:
        db.close()


def test_google_drive_source_folder_requires_readonly_reconnect(monkeypatch):
    import studio_api.main as main

    pw = admin("drive-folder-scope@example.com")
    c = TestClient(app)
    csrf = login(c, pw, "drive-folder-scope@example.com")
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    pid = c.post(
        "/api/projects", json={"title": "Folder scope"}, headers=headers
    ).json()["id"]
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email="drive-folder-scope@example.com").one()
        user_id = user.id
    finally:
        db.close()
    _connect_google_for_test(
        user_id,
        "openid email https://www.googleapis.com/auth/drive.file",
    )
    refresh = monkeypatch.setattr(
        main,
        "refreshed_google_drive_access_token",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not refresh")),
    )

    response = c.post(
        f"/api/projects/{pid}/sources/google-folder/preview",
        json={"folder_id": "folder-source"},
        headers=headers,
    )

    assert refresh is None
    assert response.status_code == 409
    assert response.json() == {"detail": "google_scope_unavailable"}


def test_output_folder_favorites_are_owner_scoped():
    c1, _h1, _pid1 = create_logged_in_project("favorite-owner-1@example.com")
    c2, h2, _pid2 = create_logged_in_project("favorite-owner-2@example.com")
    db = SessionLocal()
    try:
        owner = db.query(User).filter_by(email="favorite-owner-1@example.com").one()
        row = OutputFolderFavorite(
            owner_user_id=owner.id,
            drive_folder_id="folder-private",
            name="Private",
            web_view_url="https://drive.google.com/drive/folders/folder-private",
        )
        db.add(row); db.commit(); favorite_id = row.id
    finally:
        db.close()

    assert [row["id"] for row in c1.get("/api/output-folder-favorites").json()["favorites"]] == [favorite_id]
    assert c2.get("/api/output-folder-favorites").json() == {"favorites": []}
    assert c2.delete(
        f"/api/output-folder-favorites/{favorite_id}",
        headers=h2,
    ).status_code == 404


def test_legacy_google_drive_source_ignores_browser_metadata_and_uses_verified_metadata(monkeypatch):
    import studio_api.main as main
    from studio_api.google_drive import GoogleDriveMetadata

    pw = admin("drive-source-compat@example.com")
    c = TestClient(app)
    csrf = login(c, pw, "drive-source-compat@example.com")
    db = SessionLocal()
    uid = db.query(User).first().id
    db.close()
    _connect_google_for_test(uid)
    monkeypatch.setattr("studio_api.google_connection_access.refresh_user_google_drive_access_token", lambda *a, **k: "access")
    verified = GoogleDriveMetadata(
        "verified-file",
        "Verified meeting.mp4",
        "video/mp4",
        42,
        "https://drive.google.com/file/d/verified-file/view",
        "2025-12-04T13:23:33Z",
        None,
        False,
    )
    calls = []

    def fake_fetch(token, drive_file_id):
        calls.append((token, drive_file_id))
        return verified

    monkeypatch.setattr("studio_api.google_drive.fetch_drive_file_metadata", fake_fetch)
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    pid = c.post("/api/projects", json={"title": "Compatibility"}, headers=headers).json()["id"]
    payload = {
        "drive_file_id": "verified-file",
        "drive_file_url": "https://evil.example/spoofed",
        "original_filename": "Spoofed.pdf",
        "mime_type": "application/pdf",
        "size_bytes": main.settings.source_max_upload_bytes + 1,
    }
    r = c.post(f"/api/projects/{pid}/sources/google-drive", json=payload, headers=headers)
    assert r.status_code == 200
    assert app.openapi()["paths"][f"/api/projects/{{project_id}}/sources/google-drive"]["post"]["deprecated"] is True
    assert r.headers["deprecation"] == "true"
    assert r.headers["link"] == f'</api/projects/{pid}/sources/google-picker>; rel="successor-version"'
    assert calls == [("access", "verified-file")]
    body = r.json()
    assert body["original_filename"] == "Verified meeting.mp4"
    assert body["mime_type"] == "video/mp4"
    assert body["size_bytes"] == 42
    assert body["drive_file_url"] == "https://drive.google.com/file/d/verified-file/view"
    assert "Spoofed.pdf" not in r.text and "evil.example" not in r.text
    db = SessionLocal()
    try:
        src = db.get(Source, body["id"])
        assert src.drive_file_id == "verified-file"
    finally:
        db.close()

    mismatched = GoogleDriveMetadata("other-file", "Other.mp4", "video/mp4", 1, None, None, None, False)
    monkeypatch.setattr("studio_api.google_drive.fetch_drive_file_metadata", lambda *_: mismatched)
    mismatch = c.post(f"/api/projects/{pid}/sources/google-drive", json=payload, headers=headers)
    assert mismatch.status_code == 502
    db = SessionLocal()
    try:
        assert db.query(Source).filter_by(project_id=pid).count() == 1
    finally:
        db.close()


def _batch_headers(csrf):
    return {"origin": "https://studio.test", "x-csrf-token": csrf, "Idempotency-Key": "batch-key-1"}


def _create_uploaded_source(db, project_id, name="source.mp3"):
    src = Source(project_id=project_id, source_type=SourceType.local_upload, original_filename=name, mime_type="audio/mpeg", size_bytes=12, s3_bucket="bucket", s3_object_key=f"objects/{name}", upload_status=SourceUploadStatus.uploaded, uploaded_at=utcnow())
    db.add(src); db.flush(); return src


def _create_active_credential(db, user_id, label="main"):
    cred = ProviderCredential(user_id=user_id, provider=CredentialProvider.elevenlabs, label=label, status=CredentialStatus.active)
    db.add(cred); db.flush(); return cred


def _batch_setup(email="batch@example.com"):
    pw = admin(email); c = TestClient(app); csrf = login(c, pw, email)
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email=email).one()
        project = Project(owner_user_id=user.id, title="Batch project")
        db.add(project); db.flush()
        source_a = _create_uploaded_source(db, project.id, "a.mp3")
        source_b = _create_uploaded_source(db, project.id, "b.mp3")
        cred = _create_active_credential(db, user.id)
        db.commit()
        return c, csrf, user.id, project.id, source_a.id, source_b.id, cred.id
    finally:
        db.close()


def _install_batch_folder_mocks(monkeypatch, calls=None, invalid=None):
    import studio_api.main as main
    from studio_api.google_drive import GOOGLE_FOLDER_MIME_TYPE
    from studio_api.job_output_destination import DriveFolderAuthorizationMetadata
    calls = calls if calls is not None else []
    invalid = invalid or {}
    monkeypatch.setattr(main, "refreshed_google_drive_access_token", lambda db, user: calls.append(("token", user.id)) or "access")
    def fetch(token, folder_id):
        calls.append(("folder", folder_id))
        if folder_id in invalid:
            kind = invalid[folder_id]
            if kind == "missing":
                raise RuntimeError("missing")
            if kind == "file":
                return DriveFolderAuthorizationMetadata(folder_id, "audio/mpeg", False, True, "Not folder", "https://drive.google.com/file/d/x/view")
            if kind == "trashed":
                return DriveFolderAuthorizationMetadata(folder_id, GOOGLE_FOLDER_MIME_TYPE, True, True, "Trashed", "https://drive.google.com/drive/folders/trashed")
            if kind == "readonly":
                return DriveFolderAuthorizationMetadata(folder_id, GOOGLE_FOLDER_MIME_TYPE, False, False, "Read only", "https://drive.google.com/drive/folders/readonly")
        return DriveFolderAuthorizationMetadata(folder_id, GOOGLE_FOLDER_MIME_TYPE, False, True, f"Folder {folder_id}", f"https://drive.google.com/drive/folders/{folder_id}")
    monkeypatch.setattr("studio_api.job_output_folder_selection._fetch_drive_folder_authorization_metadata", fetch)
    return calls


def _batch_body(source_a, source_b=None, folder_a="folder-a", folder_b="folder-b", credential_id=None):
    items = [{"source_id": source_a, "output_folder_id": folder_a, "title": "First"}]
    if source_b is not None:
        items.append({"source_id": source_b, "output_folder_id": folder_b, "title": "Second"})
    body = {"language": "ru", "options": {"diarize": True}, "items": items}
    if credential_id:
        body["provider_credential_id"] = credential_id
    return body



def _count_batch_rows():
    db = SessionLocal()
    try:
        return db.query(TranscriptionJob).count(), db.query(TranscriptionJobSource).count()
    finally:
        db.close()


def _add_accepted_batch_output(user_id, project_id, source_id, credential_id):
    db = SessionLocal()
    try:
        now = utcnow()
        job = TranscriptionJob(
            project_id=project_id,
            owner_user_id=user_id,
            status=JobStatus.completed,
            provider_credential_id=credential_id,
            language="ru",
            options_json='{"diarize":true}',
            finished_at=now,
        )
        db.add(job); db.flush()
        rel = TranscriptionJobSource(
            job_id=job.id,
            source_id=source_id,
            position=0,
            status=JobSourceStatus.queued,
        )
        db.add(rel); db.flush()
        db.add(
            TranscriptionJobOutput(
                job_id=job.id,
                job_source_id=rel.id,
                document_id=f"accepted-{job.id}",
                web_view_url=f"https://docs.google.com/document/d/accepted-{job.id}/edit",
                output_drive_folder_id="accepted-folder",
                output_kind="google_docs_transcript",
                transcript_standard="transcript_doc",
                document_character_count=42,
                document_created_at=now,
                persisted_at=now,
                lease_generation=1,
            )
        )
        db.commit()
        return job.id
    finally:
        db.close()


def _add_linked_batch_catalog_entry(
    user_id,
    source_id,
    *,
    document_id="linked-catalog-document",
):
    from studio_api.models import (
        TranscriptCatalogDocumentStandardStatus,
        TranscriptCatalogEntry,
        TranscriptCatalogSettingsStatus,
        TranscriptCatalogSourceIdentityKind,
    )

    db = SessionLocal()
    try:
        db.add(
            TranscriptCatalogEntry(
                owner_user_id=user_id,
                document_id=document_id,
                document_name="Linked catalog evidence",
                transcript_standard="transcript_doc",
                standard_status=(
                    TranscriptCatalogDocumentStandardStatus.current
                ),
                settings_status=TranscriptCatalogSettingsStatus.exact,
                provider="elevenlabs",
                model="scribe_v2",
                language_mode="ru",
                diarization_enabled=True,
                source_identity_kind=(
                    TranscriptCatalogSourceIdentityKind.studio_source
                ),
                source_identity_value=source_id,
            )
        )
        db.commit()
    finally:
        db.close()


def _add_batch_provider_attempt(
    user_id,
    project_id,
    source_id,
    credential_id,
    *,
    status="processing",
    retry_disposition="undetermined",
    language="ru",
    diarization_enabled=True,
    document_creation_started=False,
    absence_acknowledged=False,
):
    db = SessionLocal()
    try:
        now = utcnow()
        job_status = getattr(JobStatus, status)
        disposition = getattr(
            SourceAttemptRetryDisposition,
            retry_disposition,
        )
        job = TranscriptionJob(
            project_id=project_id,
            owner_user_id=user_id,
            status=job_status,
            provider="elevenlabs",
            provider_credential_id=credential_id,
            language=language,
            options_json=(
                '{"diarize":true}'
                if diarization_enabled
                else '{"diarize":false}'
            ),
            started_at=now,
            finished_at=now if job_status == JobStatus.failed else None,
            attempt_count=1,
            history_attention_resolved_at=(
                now if absence_acknowledged else None
            ),
            history_attention_resolution=(
                "acknowledged_no_result" if absence_acknowledged else None
            ),
            terminal_dismissed_at=(now if absence_acknowledged else None),
        )
        db.add(job); db.flush()
        rel = TranscriptionJobSource(
            job_id=job.id,
            source_id=source_id,
            position=0,
            status=JobSourceStatus.queued,
        )
        db.add(rel); db.flush()
        db.add(
            TranscriptionJobSourceAttempt(
                owner_user_id=user_id,
                project_id=project_id,
                job_id=job.id,
                job_source_id=rel.id,
                attempt_number=1,
                stage=(
                    SourceAttemptStage.provider_request_started
                    if job_status == JobStatus.processing
                    else SourceAttemptStage.failed
                ),
                retry_disposition=disposition,
                provider_request_started_at=now,
                failed_at=now if job_status == JobStatus.failed else None,
                created_at=now,
                updated_at=now,
            )
        )
        if document_creation_started:
            db.add(
                TranscriptionOutputReconciliation(
                    owner_user_id=user_id,
                    project_id=project_id,
                    job_id=job.id,
                    job_source_id=rel.id,
                    reconciliation_token=str(uuid.uuid4()),
                    lease_generation=1,
                    attempt_number=1,
                    status=OutputReconciliationStatus.reconciliation_required,
                    expected_output_drive_folder_id="synthetic-folder",
                    expected_document_character_count=1,
                    creation_started_at=now,
                )
            )
        db.commit()
        return job.id
    finally:
        db.close()


def test_legacy_create_cannot_bypass_existing_result_decision_or_set_authority():
    c, headers, pid = create_logged_in_project("legacy-existing-result@example.com")
    sid = create_gdrive_source(c, headers, pid)
    credential_id = prepare_legacy_job_authority(c, headers, pid)
    db = SessionLocal()
    try:
        user_id = db.get(Project, pid).owner_user_id
    finally:
        db.close()
    accepted_job_id = _add_accepted_batch_output(
        user_id,
        pid,
        sid,
        credential_id,
    )
    before = _count_batch_rows()

    blocked = c.post(
        f"/api/projects/{pid}/jobs",
        json={
            "source_ids": [sid],
            "language": "ru",
            "options": {"diarize": True},
        },
        headers=headers,
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == (
        "Используйте пакетную проверку для явного решения"
    )
    assert accepted_job_id not in blocked.text
    assert _count_batch_rows() == before

    reserved = c.post(
        f"/api/projects/{pid}/jobs",
        json={
            "source_ids": [sid],
            "options": {"_existing_result_reprocess_authorized": True},
        },
        headers=headers,
    )
    assert reserved.status_code == 422
    assert reserved.json()["detail"] == (
        "Параметры задания содержат служебное поле"
    )
    assert _count_batch_rows() == before


def test_batch_preflight_is_safe_ordered_and_does_not_create_rows(monkeypatch):
    calls = _install_batch_folder_mocks(monkeypatch)
    c, csrf, _user_id, pid, source_a, source_b, cred_id = _batch_setup(
        "batch-preflight@example.com"
    )
    body = _batch_body(
        source_a,
        source_b,
        folder_a="shared",
        folder_b="shared",
        credential_id=cred_id,
    )
    before = _count_batch_rows()

    r = c.post(
        f"/api/projects/{pid}/jobs/batch/preflight",
        json=body,
        headers={"origin": "https://studio.test", "x-csrf-token": csrf},
    )

    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    data = r.json()
    assert data["language_mode"] == "ru"
    assert data["diarization_enabled"] is True
    assert data["summary"] == {
        "process_count": 2,
        "skip_count": 0,
        "blocked_count": 0,
    }
    assert data["existing_result_authority"] == {
        "status": "partial",
        "reason_code": "unlinked_catalog_entries_excluded",
    }
    assert [item["source"]["name"] for item in data["items"]] == [
        "a.mp3",
        "b.mp3",
    ]
    assert [item["output_destination"]["name"] for item in data["items"]] == [
        "Folder shared",
        "Folder shared",
    ]
    assert all(
        item["existing_result_match"] == {
            "status": "no_match",
            "accepted_output_count": 0,
            "resolution": "not_required",
        }
        and item["provider_attempt_authority"] == {
            "status": "available",
            "reason_code": None,
        }
        and item["planned_outcome"] == "process"
        and item["source"]["duration_seconds"] is None
        and item["media_clip"] is None
        for item in data["items"]
    )
    assert calls.count(("folder", "shared")) == 1
    assert _count_batch_rows() == before
    for private_value in (
        source_a,
        source_b,
        cred_id,
        "objects/a.mp3",
        "objects/b.mp3",
        "https://drive.google.com/drive/folders/shared",
    ):
        assert private_value not in r.text


def test_batch_arbitrary_segments_preflight_and_persist_ordered_jobs(monkeypatch):
    _install_batch_folder_mocks(monkeypatch)
    c, csrf, _user_id, pid, source_a, _source_b, cred_id = _batch_setup(
        "batch-arbitrary-segments@example.com"
    )
    body = {
        "provider_credential_id": cred_id,
        "language": "ru",
        "options": {"diarize": True},
        "items": [
            {
                "source_id": source_a,
                "output_folder_id": "shared-project",
                "title": "Созвон — часть 1",
                "media_clip_start_seconds": 0,
                "media_clip_end_seconds": 610,
            },
            {
                "source_id": source_a,
                "output_folder_id": "shared-project",
                "title": "Созвон — часть 2",
                "media_clip_start_seconds": 610,
                "media_clip_end_seconds": 915,
            },
            {
                "source_id": source_a,
                "output_folder_id": "shared-project",
                "title": "Созвон — часть 3",
                "media_clip_start_seconds": 920,
                "media_clip_end_seconds": None,
            },
        ],
    }
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}

    preview = c.post(
        f"/api/projects/{pid}/jobs/batch/preflight",
        json=body,
        headers=headers,
    )

    assert preview.status_code == 200
    assert preview.json()["summary"] == {
        "process_count": 3,
        "skip_count": 0,
        "blocked_count": 0,
    }
    assert [item["media_clip"] for item in preview.json()["items"]] == [
        {"start_seconds": 0, "end_seconds": 610},
        {"start_seconds": 610, "end_seconds": 915},
        {"start_seconds": 920, "end_seconds": None},
    ]

    created = c.post(
        f"/api/projects/{pid}/jobs/batch",
        json=body,
        headers={**headers, "Idempotency-Key": "batch-arbitrary-segments-key"},
    )

    assert created.status_code == 200
    assert created.json()["created_count"] == 3
    db = SessionLocal()
    try:
        jobs = (
            db.query(TranscriptionJob)
            .filter(TranscriptionJob.project_id == pid)
            .order_by(TranscriptionJob.batch_position)
            .all()
        )
        assert [
            (job.media_clip_start_seconds, job.media_clip_end_seconds)
            for job in jobs
        ] == [(0, 610), (610, 915), (920, None)]
        assert [job.output_drive_folder_id for job in jobs] == [
            "shared-project",
            "shared-project",
            "shared-project",
        ]
        assert [job.batch_position for job in jobs] == [0, 1, 2]
        assert len({job.batch_request_hash for job in jobs}) == 1
    finally:
        db.close()


@pytest.mark.parametrize(
    "items",
    [
        [
            {
                "source_id": "SOURCE",
                "output_folder_id": "one",
            },
            {
                "source_id": "SOURCE",
                "output_folder_id": "two",
                "media_clip_start_seconds": 0,
                "media_clip_end_seconds": 610,
            },
        ],
        [
            {
                "source_id": "SOURCE",
                "output_folder_id": "one",
                "media_clip_start_seconds": 0,
                "media_clip_end_seconds": 610,
            },
            {
                "source_id": "SOURCE",
                "output_folder_id": "two",
                "media_clip_start_seconds": 600,
                "media_clip_end_seconds": None,
            },
        ],
        [
            {
                "source_id": "SOURCE",
                "output_folder_id": "one",
                "media_clip_start_seconds": 610,
                "media_clip_end_seconds": None,
            },
            {
                "source_id": "SOURCE",
                "output_folder_id": "two",
                "media_clip_start_seconds": 700,
                "media_clip_end_seconds": 900,
            },
        ],
        [
            {
                "source_id": "SOURCE",
                "output_folder_id": "one",
                "media_clip_start_seconds": 610,
                "media_clip_end_seconds": 900,
            },
            {
                "source_id": "SOURCE",
                "output_folder_id": "two",
                "media_clip_start_seconds": 0,
                "media_clip_end_seconds": 600,
            },
        ],
    ],
)
def test_batch_segments_accept_independently_valid_mixed_overlapping_open_ended_or_out_of_order_plan(monkeypatch, items):
    _install_batch_folder_mocks(monkeypatch)
    c, csrf, _user_id, pid, source_a, _source_b, cred_id = _batch_setup(
        f"batch-invalid-split-{len(items)}-{items[-1]['output_folder_id']}@example.com"
    )
    for item in items:
        item["source_id"] = source_a

    response = c.post(
        f"/api/projects/{pid}/jobs/batch/preflight",
        json={"provider_credential_id": cred_id, "items": items},
        headers={"origin": "https://studio.test", "x-csrf-token": csrf},
    )

    assert response.status_code == 200
    assert len(response.json()["items"]) == len(items)
    assert response.json()["summary"]["blocked_count"] == 0
    assert response.json()["summary"]["process_count"] == len(items)
    assert _count_batch_rows() == (0, 0)


@pytest.mark.parametrize("endpoint", ["preflight", "create"])
def test_batch_rejects_out_of_bounds_known_prepared_version_before_creating_jobs(monkeypatch, endpoint):
    _install_batch_folder_mocks(monkeypatch)
    c, csrf, _user_id, pid, source_a, _source_b, cred_id = _batch_setup(f"prepared-boundary-{endpoint}@example.com")
    with SessionLocal() as db:
        source = db.get(Source, source_a)
        source.prepared_audio_context_json = json.dumps({
            "job_id": str(uuid.uuid4()), "input_duration_ms": 15000,
            "output_duration_ms": 13226, "pauses_removed": True,
        })
        db.commit()
    suffix = "/preflight" if endpoint == "preflight" else ""
    response = c.post(f"/api/projects/{pid}/jobs/batch{suffix}", json={
        "provider_credential_id": cred_id,
        "items": [{"source_id": source_a, "output_folder_id": "one", "media_clip_start_seconds": 0, "media_clip_end_seconds": 20}],
    }, headers={"origin": "https://studio.test", "x-csrf-token": csrf, "Idempotency-Key": "prepared-boundary-regression-0001"})
    assert response.status_code == 422
    assert "длительность" in response.json()["detail"]
    assert _count_batch_rows() == (0, 0)


def test_batch_create_rechecks_existing_result_and_requires_explicit_reprocessing(monkeypatch):
    _install_batch_folder_mocks(monkeypatch)
    c, csrf, user_id, pid, source_a, _source_b, cred_id = _batch_setup(
        "batch-existing-result@example.com"
    )
    body = _batch_body(source_a, credential_id=cred_id)
    preflight_headers = {
        "origin": "https://studio.test",
        "x-csrf-token": csrf,
    }

    initial = c.post(
        f"/api/projects/{pid}/jobs/batch/preflight",
        json=body,
        headers=preflight_headers,
    )
    assert initial.status_code == 200
    assert initial.json()["items"][0]["existing_result_match"]["status"] == "no_match"

    accepted_job_id = _add_accepted_batch_output(
        user_id,
        pid,
        source_a,
        cred_id,
    )
    before_blocked_create = _count_batch_rows()
    blocked_create = c.post(
        f"/api/projects/{pid}/jobs/batch",
        json=body,
        headers=_batch_headers(csrf),
    )
    assert blocked_create.status_code == 409
    assert _count_batch_rows() == before_blocked_create
    assert accepted_job_id not in blocked_create.text

    blocked_preview = c.post(
        f"/api/projects/{pid}/jobs/batch/preflight",
        json=body,
        headers=preflight_headers,
    )
    assert blocked_preview.status_code == 200
    assert blocked_preview.json()["summary"] == {
        "process_count": 0,
        "skip_count": 0,
        "blocked_count": 1,
    }
    assert blocked_preview.json()["items"][0]["existing_result_match"] == {
        "status": "accepted_match",
        "accepted_output_count": 1,
        "resolution": "required",
    }
    assert blocked_preview.json()["items"][0]["planned_outcome"] == "blocked"
    assert accepted_job_id not in blocked_preview.text

    body["items"][0]["reprocess_existing"] = True
    approved_preview = c.post(
        f"/api/projects/{pid}/jobs/batch/preflight",
        json=body,
        headers=preflight_headers,
    )
    assert approved_preview.status_code == 200
    assert approved_preview.json()["summary"] == {
        "process_count": 1,
        "skip_count": 0,
        "blocked_count": 0,
    }
    assert approved_preview.json()["items"][0]["existing_result_match"]["resolution"] == "reprocess"
    assert approved_preview.json()["items"][0]["planned_outcome"] == "process"

    created = c.post(
        f"/api/projects/{pid}/jobs/batch",
        json=body,
        headers=_batch_headers(csrf),
    )
    assert created.status_code == 200
    assert created.json()["created_count"] == 1
    assert _count_batch_rows() == (
        before_blocked_create[0] + 1,
        before_blocked_create[1] + 1,
    )
    assert "_existing_result_reprocess_authorized" not in created.text
    db = SessionLocal()
    try:
        created_job = (
            db.query(TranscriptionJob)
            .filter(
                TranscriptionJob.project_id == pid,
                TranscriptionJob.id != accepted_job_id,
            )
            .one()
        )
        assert created_job.options_json == (
            '{"_existing_result_reprocess_authorized":true,"_stt_model":"scribe_v2","diarize":true}'
        )
    finally:
        db.close()


def test_batch_preflight_and_create_enforce_linked_catalog_authority(
    monkeypatch,
):
    _install_batch_folder_mocks(monkeypatch)
    c, csrf, user_id, pid, source_a, _source_b, cred_id = _batch_setup(
        "batch-linked-catalog@example.com"
    )
    _add_linked_batch_catalog_entry(user_id, source_a)
    body = _batch_body(source_a, credential_id=cred_id)
    preflight_headers = {
        "origin": "https://studio.test",
        "x-csrf-token": csrf,
    }
    before = _count_batch_rows()

    blocked_preview = c.post(
        f"/api/projects/{pid}/jobs/batch/preflight",
        json=body,
        headers=preflight_headers,
    )

    assert blocked_preview.status_code == 200
    assert blocked_preview.json()["items"][0]["existing_result_match"] == {
        "status": "accepted_match",
        "accepted_output_count": 1,
        "resolution": "required",
    }
    assert blocked_preview.json()["items"][0]["planned_outcome"] == "blocked"
    assert blocked_preview.json()["summary"] == {
        "process_count": 0,
        "skip_count": 0,
        "blocked_count": 1,
    }
    assert source_a not in blocked_preview.text
    assert "linked-catalog-document" not in blocked_preview.text

    blocked_create = c.post(
        f"/api/projects/{pid}/jobs/batch",
        json=body,
        headers=_batch_headers(csrf),
    )

    assert blocked_create.status_code == 409
    assert blocked_create.json()["detail"] == (
        "Для существующего результата требуется явное решение"
    )
    assert _count_batch_rows() == before

    body["items"][0]["reprocess_existing"] = True
    approved_preview = c.post(
        f"/api/projects/{pid}/jobs/batch/preflight",
        json=body,
        headers=preflight_headers,
    )

    assert approved_preview.status_code == 200
    assert approved_preview.json()["items"][0]["existing_result_match"] == {
        "status": "accepted_match",
        "accepted_output_count": 1,
        "resolution": "reprocess",
    }
    assert approved_preview.json()["items"][0]["planned_outcome"] == "process"

    created = c.post(
        f"/api/projects/{pid}/jobs/batch",
        json=body,
        headers=_batch_headers(csrf),
    )

    assert created.status_code == 200
    assert created.json()["created_count"] == 1
    assert _count_batch_rows() == (before[0] + 1, before[1] + 1)
    assert "linked-catalog-document" not in created.text


@pytest.mark.parametrize(
    "status,retry_disposition,reason_code",
    [
        (
            "processing",
            "undetermined",
            "equivalent_provider_work_in_flight",
        ),
        (
            "failed",
            "output_reconciliation_required",
            "equivalent_provider_outcome_unresolved",
        ),
    ],
)
def test_batch_preflight_and_create_block_competing_provider_authority(
    monkeypatch,
    status,
    retry_disposition,
    reason_code,
):
    _install_batch_folder_mocks(monkeypatch)
    c, csrf, user_id, pid, source_a, _source_b, cred_id = _batch_setup(
        f"batch-provider-{status}@example.com"
    )
    competing_job_id = _add_batch_provider_attempt(
        user_id,
        pid,
        source_a,
        cred_id,
        status=status,
        retry_disposition=retry_disposition,
    )
    body = _batch_body(source_a, credential_id=cred_id)
    body["items"][0]["reprocess_existing"] = True
    before = _count_batch_rows()

    preview = c.post(
        f"/api/projects/{pid}/jobs/batch/preflight",
        json=body,
        headers={
            "origin": "https://studio.test",
            "x-csrf-token": csrf,
            "x-studio-preflight-recovery": "1",
        },
    )

    assert preview.status_code == 200
    assert preview.json()["items"][0]["existing_result_match"] == {
        "status": "no_match",
        "accepted_output_count": 0,
        "resolution": "not_required",
    }
    assert preview.json()["items"][0]["provider_attempt_authority"] == {
        "status": "blocked",
        "reason_code": reason_code,
        "attention_job_id": competing_job_id if status == "failed" else None,
    }
    assert preview.json()["items"][0]["planned_outcome"] == "blocked"
    assert preview.json()["summary"] == {
        "process_count": 0,
        "skip_count": 0,
        "blocked_count": 1,
    }
    assert (competing_job_id in preview.text) == (status == "failed")
    assert _count_batch_rows() == before

    create = c.post(
        f"/api/projects/{pid}/jobs/batch",
        json=body,
        headers=_batch_headers(csrf),
    )

    assert create.status_code == 409
    assert create.json()["detail"] == {
        "reason": "provider_authority_conflict"
    }
    assert competing_job_id not in create.text
    assert _count_batch_rows() == before


def test_batch_provider_authority_is_owner_scoped_across_reselected_drive_rows(
    monkeypatch,
):
    _install_batch_folder_mocks(monkeypatch)
    c, csrf, user_id, pid, source_a, source_b, cred_id = _batch_setup(
        "batch-provider-owner@example.com"
    )
    (
        _other_client,
        _other_csrf,
        other_user_id,
        other_pid,
        other_source,
        _other_source_b,
        other_cred_id,
    ) = _batch_setup("batch-provider-other@example.com")
    private_drive_id = "same-private-drive-id"
    db = SessionLocal()
    try:
        old_project = Project(owner_user_id=user_id, title="Old transcription project")
        db.add(old_project)
        db.flush()
        old_project_id = old_project.id
        for source_id in (source_a, source_b, other_source):
            source_row = db.get(Source, source_id)
            source_row.source_type = SourceType.google_drive
            source_row.drive_file_id = private_drive_id
        db.get(Source, source_b).project_id = old_project_id
        db.commit()
    finally:
        db.close()
    other_job_id = _add_batch_provider_attempt(
        other_user_id,
        other_pid,
        other_source,
        other_cred_id,
        status="failed",
        retry_disposition="provider_outcome_uncertain",
    )
    body = _batch_body(source_a, credential_id=cred_id)
    headers = {
        "origin": "https://studio.test",
        "x-csrf-token": csrf,
        "x-studio-preflight-recovery": "1",
    }

    owner_preview = c.post(
        f"/api/projects/{pid}/jobs/batch/preflight",
        json=body,
        headers=headers,
    )

    assert owner_preview.status_code == 200
    assert owner_preview.json()["items"][0]["provider_attempt_authority"] == {
        "status": "available",
        "reason_code": None,
        "attention_job_id": None,
    }
    assert other_job_id not in owner_preview.text
    own_job_id = _add_batch_provider_attempt(
        user_id,
        old_project_id,
        source_b,
        cred_id,
        status="failed",
        retry_disposition="output_reconciliation_required",
    )

    reselected_preview = c.post(
        f"/api/projects/{pid}/jobs/batch/preflight",
        json=body,
        headers=headers,
    )

    assert reselected_preview.status_code == 200
    assert reselected_preview.json()["items"][0][
        "provider_attempt_authority"
    ] == {
        "status": "blocked",
        "reason_code": "equivalent_provider_outcome_unresolved",
        "attention_job_id": own_job_id,
    }
    assert reselected_preview.json()["items"][0]["planned_outcome"] == "blocked"
    assert private_drive_id not in reselected_preview.text
    assert other_job_id not in reselected_preview.text
    assert own_job_id in reselected_preview.text

    resolved = c.post(
        f"/api/jobs/{own_job_id}/attention-resolution",
        json={
            "resolution": "acknowledged_no_result",
            "linked_job_id": None,
            "confirm_possible_spend": True,
        },
        headers=headers,
    )
    assert resolved.status_code == 200
    assert resolved.json()["history_attention_resolution"] == "acknowledged_no_result"
    ready_preview = c.post(
        f"/api/projects/{pid}/jobs/batch/preflight",
        json=body,
        headers=headers,
    )
    assert ready_preview.status_code == 200
    assert ready_preview.json()["items"][0]["provider_attempt_authority"] == {
        "status": "available",
        "reason_code": None,
        "attention_job_id": None,
    }


def test_batch_preflight_blocks_failed_attempt_if_document_creation_started(monkeypatch):
    _install_batch_folder_mocks(monkeypatch)
    c, csrf, user_id, pid, source_a, _source_b, cred_id = _batch_setup(
        "batch-document-uncertain@example.com"
    )
    previous_job_id = _add_batch_provider_attempt(
        user_id,
        pid,
        source_a,
        cred_id,
        status="failed",
        retry_disposition="provider_result_lost",
        document_creation_started=True,
    )
    preview = c.post(
        f"/api/projects/{pid}/jobs/batch/preflight",
        json=_batch_body(source_a, credential_id=cred_id),
        headers={"origin": "https://studio.test", "x-csrf-token": csrf, "x-studio-preflight-recovery": "1"},
    )
    assert preview.status_code == 200
    assert preview.json()["items"][0]["provider_attempt_authority"] == {
        "status": "blocked",
        "reason_code": "equivalent_provider_outcome_unresolved",
        "attention_job_id": previous_job_id,
    }


@pytest.mark.parametrize(
    "retry_disposition,document_creation_started",
    [
        ("provider_result_lost", True),
        ("output_reconciliation_required", True),
    ],
)
def test_acknowledged_no_result_allows_new_batch_after_hidden_failed_job(
    monkeypatch, retry_disposition, document_creation_started
):
    _install_batch_folder_mocks(monkeypatch)
    c, csrf, user_id, pid, source_a, _source_b, cred_id = _batch_setup(
        f"batch-ack-{retry_disposition}@example.com"
    )
    previous_job_id = _add_batch_provider_attempt(
        user_id,
        pid,
        source_a,
        cred_id,
        status="failed",
        retry_disposition=retry_disposition,
        document_creation_started=document_creation_started,
        absence_acknowledged=True,
    )
    body = _batch_body(source_a, credential_id=cred_id)
    preview = c.post(
        f"/api/projects/{pid}/jobs/batch/preflight",
        json=body,
        headers={"origin": "https://studio.test", "x-csrf-token": csrf, "x-studio-preflight-recovery": "1"},
    )
    assert preview.status_code == 200
    assert preview.json()["items"][0]["provider_attempt_authority"] == {
        "status": "available",
        "reason_code": None,
        "attention_job_id": None,
    }
    assert preview.json()["items"][0]["planned_outcome"] == "process"
    assert previous_job_id not in preview.text

    created = c.post(
        f"/api/projects/{pid}/jobs/batch",
        json=body,
        headers=_batch_headers(csrf),
    )
    assert created.status_code == 200
    assert created.json()["created_count"] == 1
    assert previous_job_id not in created.text


@pytest.mark.parametrize(
    "status,retry_disposition,language",
    [
        ("failed", "retry_safe", "ru"),
        ("failed", "provider_outcome_uncertain", "ru"),
        ("failed", "provider_result_lost", "ru"),
        ("processing", "undetermined", "detect"),
    ],
)
def test_batch_provider_authority_allows_retry_safe_or_different_settings(
    monkeypatch,
    status,
    retry_disposition,
    language,
):
    _install_batch_folder_mocks(monkeypatch)
    c, csrf, user_id, pid, source_a, _source_b, cred_id = _batch_setup(
        f"batch-provider-allowed-{status}-{language}@example.com"
    )
    prior_job_id = _add_batch_provider_attempt(
        user_id,
        pid,
        source_a,
        cred_id,
        status=status,
        retry_disposition=retry_disposition,
        language=language,
    )
    body = _batch_body(source_a, credential_id=cred_id)
    headers = {
        "origin": "https://studio.test",
        "x-csrf-token": csrf,
    }

    preview = c.post(
        f"/api/projects/{pid}/jobs/batch/preflight",
        json=body,
        headers=headers,
    )

    assert preview.status_code == 200
    assert preview.json()["items"][0]["provider_attempt_authority"] == {
        "status": "available",
        "reason_code": None,
    }
    assert preview.json()["items"][0]["planned_outcome"] == "process"
    assert prior_job_id not in preview.text
    created = c.post(
        f"/api/projects/{pid}/jobs/batch",
        json=body,
        headers=_batch_headers(csrf),
    )
    assert created.status_code == 200
    assert created.json()["created_count"] == 1
    assert prior_job_id not in created.text


def test_batch_provider_authority_conflict_keeps_mixed_batch_atomic(
    monkeypatch,
):
    _install_batch_folder_mocks(monkeypatch)
    c, csrf, user_id, pid, source_a, source_b, cred_id = _batch_setup(
        "batch-provider-atomic@example.com"
    )
    competing_job_id = _add_batch_provider_attempt(
        user_id,
        pid,
        source_b,
        cred_id,
        status="failed",
        retry_disposition="output_reconciliation_required",
    )
    body = _batch_body(
        source_a,
        source_b,
        credential_id=cred_id,
    )
    headers = {
        "origin": "https://studio.test",
        "x-csrf-token": csrf,
        "x-studio-preflight-recovery": "1",
    }
    before = _count_batch_rows()

    preview = c.post(
        f"/api/projects/{pid}/jobs/batch/preflight",
        json=body,
        headers=headers,
    )

    assert preview.status_code == 200
    assert [
        item["provider_attempt_authority"]
        for item in preview.json()["items"]
    ] == [
        {"status": "available", "reason_code": None, "attention_job_id": None},
        {
            "status": "blocked",
            "reason_code": "equivalent_provider_outcome_unresolved",
            "attention_job_id": competing_job_id,
        },
    ]
    assert [item["planned_outcome"] for item in preview.json()["items"]] == [
        "process",
        "blocked",
    ]
    assert preview.json()["summary"] == {
        "process_count": 1,
        "skip_count": 0,
        "blocked_count": 1,
    }
    assert competing_job_id in preview.text
    assert _count_batch_rows() == before

    create = c.post(
        f"/api/projects/{pid}/jobs/batch",
        json=body,
        headers=_batch_headers(csrf),
    )

    assert create.status_code == 409
    assert create.json()["detail"] == {
        "reason": "provider_authority_conflict"
    }
    assert competing_job_id not in create.text
    assert _count_batch_rows() == before


def test_batch_preflight_requires_csrf_and_rejects_invalid_targets_without_rows(monkeypatch):
    _install_batch_folder_mocks(monkeypatch)
    c, csrf, _user_id, pid, source_a, _source_b, _cred_id = _batch_setup(
        "batch-preflight-reject@example.com"
    )
    body = _batch_body(source_a)
    before = _count_batch_rows()

    assert c.post(f"/api/projects/{pid}/jobs/batch/preflight", json=body).status_code == 403
    assert c.post(
        f"/api/projects/{pid}/jobs/batch/preflight",
        json={"items": [body["items"][0], body["items"][0]]},
        headers={"origin": "https://studio.test", "x-csrf-token": csrf},
    ).status_code == 422
    assert c.post(
        f"/api/projects/{pid}/jobs/batch/preflight",
        json={"items": [{"source_id": "missing-source", "output_folder_id": "folder-a"}]},
        headers={"origin": "https://studio.test", "x-csrf-token": csrf},
    ).status_code == 422
    assert _count_batch_rows() == before


def test_batch_explicit_active_owner_elevenlabs_credential_saved(monkeypatch):
    _install_batch_folder_mocks(monkeypatch)
    c, csrf, user_id, pid, source_a, source_b, cred_id = _batch_setup("batch-explicit-eleven@example.com")
    body = _batch_body(source_a, credential_id=cred_id)
    body["language"] = "detect"
    r = c.post(f"/api/projects/{pid}/jobs/batch", json=body, headers=_batch_headers(csrf))
    assert r.status_code == 200
    assert all("provider_credential_id" not in job for job in r.json()["jobs"])
    assert r.json()["jobs"][0]["language_mode"] == "detect"
    db = SessionLocal()
    try:
        job = db.query(TranscriptionJob).filter_by(project_id=pid).one()
        assert job.provider_credential_id == cred_id
        assert job.language == "detect"
    finally:
        db.close()


def test_batch_null_credential_auto_resolves_single_active_elevenlabs(monkeypatch):
    _install_batch_folder_mocks(monkeypatch)
    c, csrf, user_id, pid, source_a, source_b, cred_id = _batch_setup("batch-auto-eleven@example.com")
    r = c.post(f"/api/projects/{pid}/jobs/batch", json=_batch_body(source_a), headers=_batch_headers(csrf))
    assert r.status_code == 200
    db = SessionLocal()
    try:
        job = db.query(TranscriptionJob).filter_by(project_id=pid).one()
        assert job.provider_credential_id == cred_id
    finally:
        db.close()


def test_batch_null_credential_rejects_zero_active_elevenlabs_without_partial_rows(monkeypatch):
    _install_batch_folder_mocks(monkeypatch)
    c, csrf, user_id, pid, source_a, source_b, cred_id = _batch_setup("batch-zero-eleven@example.com")
    db = SessionLocal()
    try:
        db.get(ProviderCredential, cred_id).status = CredentialStatus.revoked
        db.commit()
    finally:
        db.close()
    before = _count_batch_rows()
    r = c.post(f"/api/projects/{pid}/jobs/batch", json=_batch_body(source_a), headers=_batch_headers(csrf))
    assert r.status_code == 422
    assert _count_batch_rows() == before


def test_batch_null_credential_rejects_multiple_active_elevenlabs_without_partial_rows(monkeypatch):
    _install_batch_folder_mocks(monkeypatch)
    c, csrf, user_id, pid, source_a, source_b, cred_id = _batch_setup("batch-multi-eleven@example.com")
    db = SessionLocal()
    try:
        _create_active_credential(db, user_id, "second")
        db.commit()
    finally:
        db.close()
    before = _count_batch_rows()
    r = c.post(f"/api/projects/{pid}/jobs/batch", json=_batch_body(source_a), headers=_batch_headers(csrf))
    assert r.status_code == 422
    assert _count_batch_rows() == before


@pytest.mark.parametrize("case", ["inactive", "deleted", "foreign", "openai", "missing"])
def test_batch_explicit_credential_rejections_without_partial_rows(monkeypatch, case):
    _install_batch_folder_mocks(monkeypatch)
    c, csrf, user_id, pid, source_a, source_b, cred_id = _batch_setup(f"batch-reject-{case}@example.com")
    requested = cred_id
    db = SessionLocal()
    try:
        if case == "inactive":
            db.get(ProviderCredential, cred_id).status = CredentialStatus.revoked
        elif case == "deleted":
            cred = db.get(ProviderCredential, cred_id)
            cred.status = CredentialStatus.active
            cred.deleted_at = utcnow()
        elif case == "foreign":
            other = User(email=f"foreign-{case}@example.com", role=UserRole.admin, status=UserStatus.active)
            db.add(other); db.flush()
            requested = _create_active_credential(db, other.id, "foreign").id
        elif case == "openai":
            cred = db.get(ProviderCredential, cred_id)
            cred.provider = CredentialProvider.openai
        elif case == "missing":
            requested = "00000000-0000-0000-0000-000000000000"
        db.commit()
    finally:
        db.close()
    before = _count_batch_rows()
    r = c.post(f"/api/projects/{pid}/jobs/batch", json=_batch_body(source_a, credential_id=requested), headers=_batch_headers(csrf))
    assert r.status_code == 422
    assert _count_batch_rows() == before


def test_batch_exact_replay_with_missing_request_credential_uses_existing_id_and_skips_validation(monkeypatch):
    calls = _install_batch_folder_mocks(monkeypatch)
    c, csrf, user_id, pid, source_a, source_b, cred_id = _batch_setup("batch-replay-auto-existing@example.com")
    body = _batch_body(source_a)
    r1 = c.post(f"/api/projects/{pid}/jobs/batch", json=body, headers=_batch_headers(csrf))
    assert r1.status_code == 200 and r1.json()["replayed"] is False
    first_ids = [job["id"] for job in r1.json()["jobs"]]
    db = SessionLocal()
    try:
        db.get(ProviderCredential, cred_id).status = CredentialStatus.revoked
        db.commit()
    finally:
        db.close()
    calls.clear()
    r2 = c.post(f"/api/projects/{pid}/jobs/batch", json=body, headers=_batch_headers(csrf))
    assert r2.status_code == 200 and r2.json()["replayed"] is True
    assert [job["id"] for job in r2.json()["jobs"]] == first_ids
    assert calls == []


def test_batch_jobs_create_two_one_source_jobs_safe_payload_and_same_source_different_folders(monkeypatch):
    calls = _install_batch_folder_mocks(monkeypatch)
    c, csrf, user_id, pid, source_a, source_b, cred_id = _batch_setup("batch-happy@example.com")
    body = _batch_body(source_a, source_b, credential_id=cred_id)
    body["language"] = "en"
    r = c.post(f"/api/projects/{pid}/jobs/batch", json=body, headers=_batch_headers(csrf))
    assert r.status_code == 200
    data = r.json(); assert data["created_count"] == 2 and data["replayed"] is False
    assert [job["title"] for job in data["jobs"]] == ["First", "Second"]
    assert [job["language_mode"] for job in data["jobs"]] == ["en", "en"]
    assert [job["diarization_enabled"] for job in data["jobs"]] == [True, True]
    assert "output_drive_folder_id" not in r.text and "batch-key-1" not in r.text and "batch_request_hash" not in r.text and "batch_position" not in r.text
    batch_refs = [job["batch"] for job in data["jobs"]]
    assert len({batch["id"] for batch in batch_refs}) == 1
    assert re.fullmatch(r"multi_[0-9a-f]{32}", batch_refs[0]["id"])
    assert [batch["position"] for batch in batch_refs] == [0, 1]
    listed = c.get(f"/api/projects/{pid}/jobs")
    assert listed.status_code == 200
    listed_refs = [job["batch"] for job in listed.json()["jobs"]]
    assert {batch["id"] for batch in listed_refs} == {batch_refs[0]["id"]}
    assert sorted(batch["position"] for batch in listed_refs) == [0, 1]
    detail = c.get(f"/api/jobs/{data['jobs'][0]['id']}")
    assert detail.status_code == 200
    assert detail.json()["batch"] == batch_refs[0]
    assert "batch-key-1" not in listed.text and "batch-key-1" not in detail.text
    assert data["jobs"][0]["output_folder"] == {"name": "Folder folder-a", "web_view_url": "https://drive.google.com/drive/folders/folder-a"}
    db = SessionLocal()
    try:
        jobs = db.query(TranscriptionJob).filter_by(project_id=pid).order_by(TranscriptionJob.batch_position).all()
        assert len(jobs) == 2
        assert [j.output_drive_folder_id for j in jobs] == ["folder-a", "folder-b"]
        assert [json.loads(j.options_json) for j in jobs] == [{"_stt_model": "scribe_v2", "diarize": True}] * 2
        assert all(len(j.sources) == 1 and j.sources[0].position == 0 for j in jobs)
    finally:
        db.close()
    same_source_body = _batch_body(source_a, source_a, folder_a="folder-c", folder_b="folder-d")
    headers = _batch_headers(csrf) | {"Idempotency-Key": "batch-key-2"}
    r = c.post(f"/api/projects/{pid}/jobs/batch", json=same_source_body, headers=headers)
    assert r.status_code == 200 and r.json()["created_count"] == 2
    assert calls.count(("folder", "folder-c")) == 1 and calls.count(("folder", "folder-d")) == 1


def test_batch_jobs_duplicate_pair_and_atomic_validation_failures(monkeypatch):
    _install_batch_folder_mocks(monkeypatch, invalid={"bad-folder": "file", "trashed": "trashed", "readonly": "readonly", "missing": "missing"})
    c, csrf, user_id, pid, source_a, source_b, cred_id = _batch_setup("batch-fail@example.com")
    headers = _batch_headers(csrf)
    dup = {"items": [{"source_id": source_a, "output_folder_id": "folder-a"}, {"source_id": source_a, "output_folder_id": "folder-a"}]}
    before = SessionLocal(); job_count = before.query(TranscriptionJob).count(); rel_count = before.query(TranscriptionJobSource).count(); audit_count = before.query(AuditEvent).filter_by(event_type="job.batch_created").count(); before.close()
    assert c.post(f"/api/projects/{pid}/jobs/batch", json=dup, headers=headers).status_code == 422
    after = SessionLocal()
    try:
        assert after.query(TranscriptionJob).count() == job_count
        assert after.query(TranscriptionJobSource).count() == rel_count
        assert after.query(AuditEvent).filter_by(event_type="job.batch_created").count() == audit_count
    finally:
        after.close()
    cases = [
        ({"language": "fr", "items": [{"source_id": source_a, "output_folder_id": "folder-a"}]}, "bad-key-language"),
        ({"options": {"diarize": "yes"}, "items": [{"source_id": source_a, "output_folder_id": "folder-a"}]}, "bad-key-diarize-type"),
        ({"options": {"diarize": True, "keyterms": ["deferred"]}, "items": [{"source_id": source_a, "output_folder_id": "folder-a"}]}, "bad-key-options-extra"),
        ({"items": [{"source_id": source_a, "output_folder_id": "folder-a", "reprocess_existing": "yes"}]}, "bad-key-reprocess-type"),
        ({"items": [{"source_id": source_a, "output_folder_id": "folder-a", "unexpected": True}]}, "bad-key-item-extra"),
        ({"items": [{"source_id": "missing-source", "output_folder_id": "folder-a"}]}, "bad-key-1"),
        ({"provider_credential_id": "missing-cred", "items": [{"source_id": source_a, "output_folder_id": "folder-a"}]}, "bad-key-2"),
        ({"items": [{"source_id": source_a, "output_folder_id": "bad-folder"}]}, "bad-key-3"),
        ({"items": [{"source_id": source_a, "output_folder_id": "trashed"}]}, "bad-key-4"),
        ({"items": [{"source_id": source_a, "output_folder_id": "readonly"}]}, "bad-key-5"),
        ({"items": [{"source_id": source_a, "output_folder_id": "folder-a"}, {"source_id": source_b, "output_folder_id": "missing"}]}, "bad-key-6"),
    ]
    db = SessionLocal();
    try:
        db.get(Source, source_b).deleted_at = utcnow(); db.commit()
    finally:
        db.close()
    cases.append(({"items": [{"source_id": source_b, "output_folder_id": "folder-a"}]}, "bad-key-7"))
    for payload, key in cases:
        before = SessionLocal(); job_count = before.query(TranscriptionJob).count(); rel_count = before.query(TranscriptionJobSource).count(); before.close()
        r = c.post(f"/api/projects/{pid}/jobs/batch", json=payload, headers=headers | {"Idempotency-Key": key})
        assert r.status_code in {422, 502}
        after = SessionLocal();
        try:
            assert after.query(TranscriptionJob).count() == job_count
            assert after.query(TranscriptionJobSource).count() == rel_count
        finally:
            after.close()


def test_batch_jobs_exact_replay_skips_current_validation_and_conflicts_skip_google(monkeypatch):
    calls = _install_batch_folder_mocks(monkeypatch)
    c, csrf, user_id, pid, source_a, source_b, cred_id = _batch_setup("batch-replay@example.com")
    body = _batch_body(source_a, source_b, folder_a="shared", folder_b="shared", credential_id=cred_id)
    r1 = c.post(f"/api/projects/{pid}/jobs/batch", json=body, headers=_batch_headers(csrf))
    assert r1.status_code == 200 and r1.json()["replayed"] is False
    assert [call for call in calls if call == ("folder", "shared")] == [("folder", "shared")]
    first_ids = [j["id"] for j in r1.json()["jobs"]]
    db = SessionLocal()
    try:
        db.get(ProviderCredential, cred_id).status = CredentialStatus.revoked
        db.get(Source, source_a).deleted_at = utcnow()
        db.commit()
    finally:
        db.close()
    calls.clear()
    r2 = c.post(f"/api/projects/{pid}/jobs/batch", json=body, headers=_batch_headers(csrf))
    assert r2.status_code == 200 and r2.json()["replayed"] is True
    assert [j["id"] for j in r2.json()["jobs"]] == first_ids
    assert calls == []
    db = SessionLocal()
    try:
        assert db.query(TranscriptionJob).filter_by(project_id=pid).count() == 2
        assert db.query(TranscriptionJobSource).join(TranscriptionJob).filter(TranscriptionJob.project_id == pid).count() == 2
        assert db.query(AuditEvent).filter_by(event_type="job.batch_created").count() == 1
    finally:
        db.close()
    conflict_bodies = [
        {**body, "items": [{"source_id": source_b, "output_folder_id": "shared", "title": "Dup"}, {"source_id": source_b, "output_folder_id": "shared", "title": "Dup"}]},
        _batch_body(source_b, source_b, folder_a="shared", folder_b="shared", credential_id=cred_id),
        _batch_body(source_a, source_b, folder_a="changed", folder_b="shared", credential_id=cred_id),
        {**body, "language": "detect"},
        {**body, "options": {"diarize": False}},
        {**body, "items": list(reversed(body["items"]))},
        {**body, "items": [{**body["items"][0], "title": "Changed"}, body["items"][1]]},
        {**body, "items": [{**body["items"][0], "reprocess_existing": True}, body["items"][1]]},
    ]
    for idx, conflict in enumerate(conflict_bodies):
        calls.clear()
        r = c.post(f"/api/projects/{pid}/jobs/batch", json=conflict, headers=_batch_headers(csrf))
        assert r.status_code == 409, idx
        assert calls == []


def test_batch_jobs_key_scoped_by_project_and_integrity_replay_guards(monkeypatch):
    _install_batch_folder_mocks(monkeypatch)
    c, csrf, user_id, pid, source_a, source_b, cred_id = _batch_setup("batch-scope@example.com")
    body = _batch_body(source_a, None, folder_a="folder-a")
    assert c.post(f"/api/projects/{pid}/jobs/batch", json=body, headers=_batch_headers(csrf)).status_code == 200
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        p2 = Project(owner_user_id=user.id, title="Second")
        db.add(p2); db.flush(); s2 = _create_uploaded_source(db, p2.id, "second.mp3"); db.commit(); p2_id = p2.id; s2_id = s2.id
    finally:
        db.close()
    assert c.post(f"/api/projects/{p2_id}/jobs/batch", json=_batch_body(s2_id, None, folder_a="folder-a"), headers=_batch_headers(csrf)).status_code == 200
    from studio_api.main import _existing_batch_is_complete, _batch_hash
    db = SessionLocal()
    try:
        existing = db.query(TranscriptionJob).filter_by(project_id=pid, batch_idempotency_key="batch-key-1").order_by(TranscriptionJob.batch_position).all()
        request_hash = existing[0].batch_request_hash
        assert _existing_batch_is_complete(existing, request_hash, 1) is True
        assert _existing_batch_is_complete(existing, "bad", 1) is False
        existing[0].batch_position = 2
        assert _existing_batch_is_complete(existing, request_hash, 1) is False
    finally:
        db.rollback(); db.close()


def test_batch_mixed_drive_destinations_are_provider_bound_and_idempotent(monkeypatch):
    from studio_api.job_output_folder_selection import VerifiedOutputFolderSelection
    import studio_api.yandex_disk_routes as disk_routes
    calls = _install_batch_folder_mocks(monkeypatch)
    c, csrf, user_id, pid, source_a, source_b, cred_id = _batch_setup("batch-disk@example.com")
    disk_calls = []
    handle = "6f5d76f9-1ced-44a4-abf5-9ff96092687e"
    def verify(db, *, owner_user_id, folder_id, settings):
        assert owner_user_id == user_id and folder_id == handle
        disk_calls.append((owner_user_id, folder_id))
        return VerifiedOutputFolderSelection(handle, "Папка Яндекс Диска",
            "https://disk.yandex.ru/client/disk/Docs", utcnow(), provider="yandex_disk")
    monkeypatch.setattr(disk_routes, "verify_yandex_output_folder", verify)
    body = _batch_body(source_a, source_b, folder_a="google-folder", folder_b=handle, credential_id=cred_id)
    body["items"][1]["output_provider"] = "yandex_disk"
    preview = c.post(f"/api/projects/{pid}/jobs/batch/preflight", json=body, headers=_batch_headers(csrf))
    assert preview.status_code == 200
    assert preview.json()["items"][1]["output_destination"]["name"] == "Папка Яндекс Диска"
    created = c.post(f"/api/projects/{pid}/jobs/batch", json=body, headers=_batch_headers(csrf))
    assert created.status_code == 200
    jobs = created.json()["jobs"]
    assert [job["output_provider"] for job in jobs] == ["google_drive", "yandex_disk"]
    assert jobs[1]["output_folder"]["web_view_url"].startswith("https://disk.yandex.ru/")
    calls.clear(); disk_calls.clear()
    replay = c.post(f"/api/projects/{pid}/jobs/batch", json=body, headers=_batch_headers(csrf))
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    assert calls == disk_calls == []
    changed = {**body, "items": [body["items"][0], {**body["items"][1], "output_provider": "google_drive"}]}
    assert c.post(f"/api/projects/{pid}/jobs/batch", json=changed, headers=_batch_headers(csrf)).status_code == 409
    assert calls == disk_calls == []



def test_batch_jobs_integrity_error_replays_concurrent_winner(monkeypatch):
    calls = _install_batch_folder_mocks(monkeypatch)
    c, csrf, user_id, pid, source_a, source_b, cred_id = _batch_setup("batch-race@example.com")
    body = _batch_body(source_a, source_b, credential_id=cred_id)
    import studio_api.main as main
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session as OrmSession
    original_flush = OrmSession.flush
    injected = {"done": False}

    def fake_flush(self, *args, **kwargs):
        if not injected["done"] and any(isinstance(obj, TranscriptionJob) and obj.batch_idempotency_key == "batch-key-1" for obj in self.new):
            injected["done"] = True
            request_data = main.TranscriptionJobBatchCreateIn.model_validate(body)
            language, options_json, _, _, _, _, _, _, _, hash_items = (
                main._normalize_batch_creation_input(request_data)
            )
            request_hash = main._batch_hash(
                pid,
                cred_id,
                language,
                options_json,
                hash_items,
                provider=request_data.provider.value,
                operating_mode=request_data.operating_mode.value,
            )
            winner = SessionLocal()
            try:
                winner.execute(text("SET LOCAL lock_timeout = '3s'"))
                for idx, item in enumerate(body["items"]):
                    job = TranscriptionJob(project_id=pid, owner_user_id=user_id, status=JobStatus.queued, provider_credential_id=cred_id, language=language, options_json=options_json, batch_idempotency_key="batch-key-1", batch_request_hash=request_hash, batch_position=idx)
                    job.apply_output_folder_snapshot(folder_id=item["output_folder_id"], folder_url=f"https://drive.google.com/drive/folders/{item['output_folder_id']}", folder_name=f"Folder {item['output_folder_id']}")
                    winner.add(job); original_flush(winner)
                    winner.add(TranscriptionJobSource(job_id=job.id, source_id=item["source_id"], position=0, status=JobSourceStatus.queued)); original_flush(winner)
                winner.add(AuditEvent(actor_user_id=user_id, subject_user_id=user_id, event_type="job.batch_created", metadata_json='{"count":2}'))
                winner.commit()
            finally:
                winner.close()
            raise IntegrityError("insert", {}, Exception("duplicate"))
        return original_flush(self, *args, **kwargs)

    monkeypatch.setattr(OrmSession, "flush", fake_flush)
    r = c.post(f"/api/projects/{pid}/jobs/batch", json=body, headers=_batch_headers(csrf))
    assert r.status_code == 200
    assert r.json()["replayed"] is True
    assert r.json()["created_count"] == 2
    assert calls.count(("folder", "folder-a")) == 1 and calls.count(("folder", "folder-b")) == 1
    db = SessionLocal()
    try:
        assert db.query(TranscriptionJob).filter_by(project_id=pid).count() == 2
        assert db.query(TranscriptionJobSource).join(TranscriptionJob).filter(TranscriptionJob.project_id == pid).count() == 2
        assert db.query(AuditEvent).filter_by(event_type="job.batch_created").count() == 1
    finally:
        db.close()


def _attempt_enum_values(conn, enum_name: str) -> list[str]:
    return conn.execute(text(
        "SELECT e.enumlabel FROM pg_enum e "
        "JOIN pg_type t ON t.oid = e.enumtypid "
        "WHERE t.typname = :enum_name "
        "ORDER BY e.enumsortorder"
    ), {"enum_name": enum_name}).scalars().all()


def _assert_attempt_enums_absent(conn):
    assert conn.execute(text("SELECT count(*) FROM pg_type WHERE typname IN ('sourceattemptretrydisposition', 'sourceattemptstage')")).scalar_one() == 0


def _assert_job_retry_recovery_schema(inspector, conn):
    assert "transcription_job_source_attempts" in inspector.get_table_names()
    assert "transcription_output_reconciliations" in inspector.get_table_names()
    cols = {c["name"]: c for c in inspector.get_columns("transcription_job_source_attempts")}
    assert {"id", "owner_user_id", "project_id", "job_id", "job_source_id", "attempt_number", "stage", "retry_disposition", "failure_code", "provider_request_started_at", "provider_response_returned_at", "failed_at", "completed_at", "created_at", "updated_at"}.issubset(cols)
    uniques = {tuple(u["column_names"]) for u in inspector.get_unique_constraints("transcription_job_source_attempts")}
    assert ("job_source_id", "attempt_number") in uniques
    checks = {c["name"] for c in inspector.get_check_constraints("transcription_job_source_attempts")}
    assert "ck_source_attempt_attempt_number_positive" in checks
    indexes = {idx["name"]: tuple(idx["column_names"]) for idx in inspector.get_indexes("transcription_job_source_attempts")}
    assert indexes["ix_source_attempts_job_id"] == ("job_id",)
    assert indexes["ix_source_attempts_job_source_id"] == ("job_source_id",)
    assert indexes["ix_source_attempts_retry_disposition"] == ("retry_disposition",)
    assert indexes["ix_source_attempts_job_retry_disposition"] == ("job_id", "retry_disposition")
    fks = {tuple(fk["constrained_columns"]): fk["referred_table"] for fk in inspector.get_foreign_keys("transcription_job_source_attempts")}
    assert fks[("owner_user_id",)] == "users"
    assert fks[("project_id",)] == "projects"
    assert fks[("job_id",)] == "transcription_jobs"
    assert fks[("job_source_id",)] == "transcription_job_sources"
    assert _attempt_enum_values(conn, "sourceattemptstage") == [e.value for e in SourceAttemptStage]
    assert _attempt_enum_values(conn, "sourceattemptretrydisposition") == [e.value for e in SourceAttemptRetryDisposition]



def _source_cleanup_enum_values(conn) -> list[str]:
    return conn.execute(text(
        "SELECT e.enumlabel FROM pg_enum e "
        "JOIN pg_type t ON t.oid = e.enumtypid "
        "WHERE t.typname = 'sourcestoragecleanupstatus' "
        "ORDER BY e.enumsortorder"
    )).scalars().all()


def _strip_0014_source_cleanup_schema(conn) -> None:
    conn.execute(text("DROP INDEX IF EXISTS ix_sources_storage_cleanup_selection"))
    conn.execute(text("ALTER TABLE sources DROP CONSTRAINT IF EXISTS ck_sources_storage_cleanup_attempt_count_nonnegative"))
    conn.execute(text("ALTER TABLE sources DROP CONSTRAINT IF EXISTS ck_sources_storage_cleanup_generation_nonnegative"))
    for col in [
        "storage_cleanup_status",
        "storage_cleanup_requested_at",
        "storage_cleanup_not_before_at",
        "storage_cleanup_completed_at",
        "storage_cleanup_attempt_count",
        "storage_cleanup_error_code",
        "storage_cleanup_owner_id",
        "storage_cleanup_generation",
        "storage_cleanup_claimed_at",
        "storage_cleanup_lease_expires_at",
    ]:
        conn.execute(text(f"ALTER TABLE sources DROP COLUMN IF EXISTS {col}"))
    conn.execute(text("DROP TYPE IF EXISTS sourcestoragecleanupstatus"))


def _assert_source_deletion_0014_schema(inspector, conn):
    cols = {c["name"]: c for c in inspector.get_columns("sources")}
    expected = {
        "storage_cleanup_status",
        "storage_cleanup_requested_at",
        "storage_cleanup_not_before_at",
        "storage_cleanup_completed_at",
        "storage_cleanup_attempt_count",
        "storage_cleanup_error_code",
        "storage_cleanup_owner_id",
        "storage_cleanup_generation",
        "storage_cleanup_claimed_at",
        "storage_cleanup_lease_expires_at",
    }
    assert expected.issubset(cols)
    assert cols["storage_cleanup_status"]["nullable"] is False
    assert cols["storage_cleanup_attempt_count"]["nullable"] is False
    assert cols["storage_cleanup_generation"]["nullable"] is False
    assert str(cols["storage_cleanup_status"].get("default", "")).strip("'::character varying")
    assert str(cols["storage_cleanup_attempt_count"].get("default", "")).startswith("0")
    assert str(cols["storage_cleanup_generation"].get("default", "")).startswith("0")
    checks = {c["name"] for c in inspector.get_check_constraints("sources")}
    assert "ck_sources_storage_cleanup_attempt_count_nonnegative" in checks
    assert "ck_sources_storage_cleanup_generation_nonnegative" in checks
    indexes = {idx["name"]: tuple(idx["column_names"]) for idx in inspector.get_indexes("sources")}
    assert indexes["ix_sources_storage_cleanup_selection"] == ("storage_cleanup_status", "storage_cleanup_not_before_at", "storage_cleanup_lease_expires_at")
    assert "ix_sources_storage_cleanup_status" not in indexes
    assert "ix_sources_storage_cleanup_not_before_at" not in indexes
    assert _source_cleanup_enum_values(conn) == [e.value for e in SourceStorageCleanupStatus]
    model_cols = Source.__table__.c
    for name in expected:
        assert name in model_cols
        assert model_cols[name].nullable == cols[name]["nullable"]


def _assert_source_deletion_0014_absent(inspector, conn):
    cols = {c["name"] for c in inspector.get_columns("sources")}
    assert not {
        "storage_cleanup_status",
        "storage_cleanup_requested_at",
        "storage_cleanup_not_before_at",
        "storage_cleanup_completed_at",
        "storage_cleanup_attempt_count",
        "storage_cleanup_error_code",
        "storage_cleanup_owner_id",
        "storage_cleanup_generation",
        "storage_cleanup_claimed_at",
        "storage_cleanup_lease_expires_at",
    } & cols
    indexes = {idx["name"] for idx in inspector.get_indexes("sources")}
    assert "ix_sources_storage_cleanup_selection" not in indexes
    checks = {c["name"] for c in inspector.get_check_constraints("sources")}
    assert "ck_sources_storage_cleanup_attempt_count_nonnegative" not in checks
    assert "ck_sources_storage_cleanup_generation_nonnegative" not in checks
    assert conn.execute(text("SELECT count(*) FROM pg_type WHERE typname = 'sourcestoragecleanupstatus'")).scalar_one() == 0


def _assert_user_source_retention_0015_absent(inspector):
    assert "source_retention_ttl_seconds" not in {c["name"] for c in inspector.get_columns("users")}
    assert "ck_users_source_retention_ttl_allowed" not in {c["name"] for c in inspector.get_check_constraints("users")}


def test_user_source_retention_0015_upgrade_downgrade_roundtrip_and_metadata_table():
    from studio_api.db import Base

    with isolated_migration_database("studio_migration_0015") as (temp_engine, env):
        run_alembic("0014_source_deletion_retention", env=env)
        with temp_engine.begin() as conn:
            conn.execute(text("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_source_retention_ttl_allowed"))
            conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS source_retention_ttl_seconds"))
            conn.execute(text("UPDATE alembic_version SET version_num='0014_source_deletion_retention'"))
            _assert_user_source_retention_0015_absent(inspect(conn))
            conn.execute(text("INSERT INTO users (id, email, role, status, created_at, updated_at) VALUES ('user-0015', 'migration-0015@example.com', 'user', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))

        run_alembic("0015_user_source_retention", env=env)
        with temp_engine.begin() as conn:
            inspector = inspect(conn)
            columns = {c["name"]: c for c in inspector.get_columns("users")}
            assert columns["source_retention_ttl_seconds"]["nullable"] is False
            assert "ck_users_source_retention_ttl_allowed" in {c["name"] for c in inspector.get_check_constraints("users")}
            assert conn.execute(text("SELECT source_retention_ttl_seconds FROM users WHERE id='user-0015'")).scalar_one() == 86400
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0015_user_source_retention"
        for allowed in (3600, 86400, 259200, 604800, 2592000):
            with temp_engine.begin() as conn:
                conn.execute(text("UPDATE users SET source_retention_ttl_seconds=:allowed WHERE id='user-0015'"), {"allowed": allowed})
        with pytest.raises(Exception):
            with temp_engine.begin() as conn:
                conn.execute(text("UPDATE users SET source_retention_ttl_seconds=7200 WHERE id='user-0015'"))

        run_alembic("0014_source_deletion_retention", env=env, command="downgrade")
        with temp_engine.begin() as conn:
            _assert_user_source_retention_0015_absent(inspect(conn))
            assert conn.execute(text("SELECT count(*) FROM users WHERE id='user-0015'")).scalar_one() == 1
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0014_source_deletion_retention"

    with isolated_migration_database("studio_migration_0015_metadata") as (temp_engine, env):
        Base.metadata.create_all(temp_engine)
        run_alembic("0015_user_source_retention", env=env, command="stamp")
        run_alembic("0014_source_deletion_retention", env=env, command="downgrade")
        with temp_engine.begin() as conn:
            _assert_user_source_retention_0015_absent(inspect(conn))


def _drop_transcript_catalog_0016_schema(conn):
    conn.execute(text("DROP TABLE IF EXISTS transcript_catalog_entries"))
    conn.execute(
        text(
            "DROP TYPE IF EXISTS "
            "transcriptcatalogsourceidentitykind"
        )
    )
    conn.execute(
        text("DROP TYPE IF EXISTS transcriptcatalogsettingsstatus")
    )
    conn.execute(
        text(
            "DROP TYPE IF EXISTS "
            "transcriptcatalogdocumentstandardstatus"
        )
    )


def _assert_transcript_catalog_0016_schema(inspector):
    assert "transcript_catalog_entries" in inspector.get_table_names()
    columns = {
        column["name"]
        for column in inspector.get_columns("transcript_catalog_entries")
    }
    assert {
        "id",
        "owner_user_id",
        "document_id",
        "document_name",
        "transcript_standard",
        "standard_status",
        "settings_status",
        "provider",
        "model",
        "language_mode",
        "diarization_enabled",
        "source_identity_kind",
        "source_identity_value",
        "imported_at",
        "updated_at",
    } == columns
    checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints(
            "transcript_catalog_entries"
        )
    }
    assert {
        "ck_transcript_catalog_document_id_nonempty",
        "ck_transcript_catalog_document_name_nonempty",
        "ck_transcript_catalog_standard_nonempty",
        "ck_transcript_catalog_source_authority",
        "ck_transcript_catalog_settings_authority",
    } <= checks
    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(
            "transcript_catalog_entries"
        )
    }
    assert "uq_transcript_catalog_owner_document" in unique_constraints
    indexes = {
        index["name"]
        for index in inspector.get_indexes(
            "transcript_catalog_entries"
        )
    }
    assert {
        "ix_transcript_catalog_owner_updated",
        "ix_transcript_catalog_owner_source_settings",
    } <= indexes
    foreign_keys = {
        tuple(constraint["constrained_columns"]): (
            constraint["referred_table"]
        )
        for constraint in inspector.get_foreign_keys(
            "transcript_catalog_entries"
        )
    }
    assert foreign_keys[("owner_user_id",)] == "users"


def test_transcript_catalog_0016_upgrade_downgrade_and_constraints():
    from studio_api.db import Base

    with isolated_migration_database(
        "studio_migration_0016"
    ) as (temp_engine, env):
        run_alembic("0015_user_source_retention", env=env)
        with temp_engine.begin() as conn:
            _drop_transcript_catalog_0016_schema(conn)
            assert (
                conn.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
                == "0015_user_source_retention"
            )
            conn.execute(
                text(
                    "INSERT INTO users "
                    "(id, email, role, status, created_at, updated_at) "
                    "VALUES "
                    "('catalog-owner-a', 'catalog-a@example.com', "
                    "'user', 'active', CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP), "
                    "('catalog-owner-b', 'catalog-b@example.com', "
                    "'user', 'active', CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP)"
                )
            )

        run_alembic("0016_transcript_catalog_entries", env=env)
        with temp_engine.begin() as conn:
            _assert_transcript_catalog_0016_schema(inspect(conn))
            assert (
                conn.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
                == "0016_transcript_catalog_entries"
            )
            conn.execute(
                text(
                    "INSERT INTO transcript_catalog_entries "
                    "(id, owner_user_id, document_id, document_name, "
                    "transcript_standard, standard_status, "
                    "settings_status, imported_at, updated_at) "
                    "VALUES "
                    "('catalog-indeterminate', 'catalog-owner-a', "
                    "'google-document-a', 'Document A', "
                    "'transcript_doc_v1.2', 'current', "
                    "'indeterminate', CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO transcript_catalog_entries "
                    "(id, owner_user_id, document_id, document_name, "
                    "transcript_standard, standard_status, "
                    "settings_status, provider, model, language_mode, "
                    "diarization_enabled, source_identity_kind, "
                    "source_identity_value, imported_at, updated_at) "
                    "VALUES "
                    "('catalog-exact', 'catalog-owner-a', "
                    "'google-document-b', 'Document B', "
                    "'transcript_doc_v1.2', 'current', 'exact', "
                    "'elevenlabs', 'scribe_v2', 'ru', true, "
                    "'google_drive_file', 'source-drive-id', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO transcript_catalog_entries "
                    "(id, owner_user_id, document_id, document_name, "
                    "transcript_standard, standard_status, "
                    "settings_status, imported_at, updated_at) "
                    "VALUES "
                    "('catalog-shared-other-owner', "
                    "'catalog-owner-b', 'google-document-a', "
                    "'Document A', 'transcript_doc_v1.2', "
                    "'current', 'indeterminate', CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP)"
                )
            )

        invalid_rows = (
            (
                "catalog-invalid-settings",
                "'exact', NULL, NULL",
            ),
            (
                "catalog-invalid-source",
                "'indeterminate', 'google_drive_file', NULL",
            ),
        )
        for row_id, authority_values in invalid_rows:
            with pytest.raises(Exception):
                with temp_engine.begin() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO transcript_catalog_entries "
                            "(id, owner_user_id, document_id, "
                            "document_name, transcript_standard, "
                            "standard_status, settings_status, "
                            "source_identity_kind, "
                            "source_identity_value, imported_at, "
                            "updated_at) VALUES "
                            f"('{row_id}', 'catalog-owner-a', "
                            f"'{row_id}-doc', 'Invalid', "
                            "'transcript_doc_v1.2', 'current', "
                            f"{authority_values}, CURRENT_TIMESTAMP, "
                            "CURRENT_TIMESTAMP)"
                        )
                    )
        with pytest.raises(Exception):
            with temp_engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO transcript_catalog_entries "
                        "(id, owner_user_id, document_id, "
                        "document_name, transcript_standard, "
                        "standard_status, settings_status, "
                        "imported_at, updated_at) VALUES "
                        "('catalog-duplicate', 'catalog-owner-a', "
                        "'google-document-a', 'Duplicate', "
                        "'transcript_doc_v1.2', 'current', "
                        "'indeterminate', CURRENT_TIMESTAMP, "
                        "CURRENT_TIMESTAMP)"
                    )
                )

        run_alembic(
            "0015_user_source_retention",
            env=env,
            command="downgrade",
        )
        with temp_engine.begin() as conn:
            assert "transcript_catalog_entries" not in (
                inspect(conn).get_table_names()
            )
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM pg_type WHERE typname "
                        "LIKE 'transcriptcatalog%'"
                    )
                ).scalar_one()
                == 0
            )
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM users "
                        "WHERE id LIKE 'catalog-owner-%'"
                    )
                ).scalar_one()
                == 2
            )

    with isolated_migration_database(
        "studio_migration_0016_metadata"
    ) as (temp_engine, env):
        Base.metadata.create_all(temp_engine)
        run_alembic(
            "0016_transcript_catalog_entries",
            env=env,
            command="stamp",
        )
        run_alembic(
            "0015_user_source_retention",
            env=env,
            command="downgrade",
        )
        with temp_engine.begin() as conn:
            assert "transcript_catalog_entries" not in (
                inspect(conn).get_table_names()
            )


def test_source_deletion_0014_upgrade_downgrade_roundtrip_and_metadata_table(tmp_path):
    from studio_api.db import Base

    with isolated_migration_database("studio_migration_0014") as (temp_engine, env):
        run_alembic("0013_job_retry_recovery", env=env)
        with temp_engine.begin() as conn:
            _strip_0014_source_cleanup_schema(conn)
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0013_job_retry_recovery"
            conn.execute(text("INSERT INTO users (id, email, role, status, created_at, updated_at) VALUES ('user-0014', 'migration-0014@example.com', 'user', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
            conn.execute(text("INSERT INTO projects (id, owner_user_id, title, created_at, updated_at) VALUES ('project-0014', 'user-0014', 'Migration 0014', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
            conn.execute(text("""
                INSERT INTO sources (id, project_id, source_type, original_filename, mime_type, size_bytes, drive_file_id, drive_file_url, s3_bucket, s3_object_key, upload_status, uploaded_at, expires_at, deleted_at, delete_reason, created_at, updated_at)
                VALUES
                ('source-active-local', 'project-0014', 'local_upload', 'active.mp3', 'audio/mpeg', 1, NULL, NULL, 'bucket', 'active/key', 'uploaded', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP + INTERVAL '1 day', NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                ('source-deleted-local', 'project-0014', 'local_upload', 'deleted.mp3', 'audio/mpeg', 1, NULL, NULL, 'bucket', 'deleted/key', 'deleted', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP + INTERVAL '1 day', CURRENT_TIMESTAMP, 'user_deleted', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                ('source-expired-local', 'project-0014', 'local_upload', 'expired.mp3', 'audio/mpeg', 1, NULL, NULL, 'bucket', 'expired/key', 'uploaded', CURRENT_TIMESTAMP - INTERVAL '2 days', CURRENT_TIMESTAMP - INTERVAL '1 day', NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                ('source-pending-deleted-local', 'project-0014', 'local_upload', 'pending.mp3', 'audio/mpeg', 1, NULL, NULL, 'bucket', 'pending/key', 'pending', NULL, CURRENT_TIMESTAMP + INTERVAL '2 days', CURRENT_TIMESTAMP, 'user_deleted', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                ('source-drive', 'project-0014', 'google_drive', 'drive.mp3', 'audio/mpeg', 1, 'drive-id-0014', 'https://drive.google.com/file/d/drive-id-0014/view', NULL, NULL, 'uploaded', CURRENT_TIMESTAMP, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """))
        run_alembic("0014_source_deletion_retention", env=env)
        with temp_engine.begin() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0014_source_deletion_retention"
            _assert_source_deletion_0014_schema(inspect(conn), conn)
            rows = {r["id"]: r for r in conn.execute(text("SELECT id, upload_status, deleted_at, delete_reason, s3_bucket, s3_object_key, storage_cleanup_status, storage_cleanup_requested_at, storage_cleanup_not_before_at, storage_cleanup_completed_at, storage_cleanup_attempt_count, storage_cleanup_generation, expires_at FROM sources WHERE project_id='project-0014' ORDER BY id")).mappings().all()}
            assert rows["source-drive"]["storage_cleanup_status"] == "not_applicable"
            assert rows["source-drive"]["storage_cleanup_requested_at"] is None
            assert rows["source-active-local"]["storage_cleanup_status"] == "not_requested"
            assert rows["source-deleted-local"]["storage_cleanup_status"] == "pending"
            assert rows["source-deleted-local"]["s3_bucket"] == "bucket" and rows["source-deleted-local"]["s3_object_key"] == "deleted/key"
            assert rows["source-expired-local"]["upload_status"] == "expired"
            assert rows["source-expired-local"]["delete_reason"] == "retention_expired"
            assert rows["source-expired-local"]["deleted_at"] is None
            assert rows["source-expired-local"]["storage_cleanup_status"] == "pending"
            assert rows["source-pending-deleted-local"]["storage_cleanup_status"] == "pending"
            assert rows["source-pending-deleted-local"]["storage_cleanup_not_before_at"] >= rows["source-pending-deleted-local"]["expires_at"]
            assert {row["storage_cleanup_attempt_count"] for row in rows.values()} == {0}
            assert {row["storage_cleanup_generation"] for row in rows.values()} == {0}
        run_alembic("0013_job_retry_recovery", env=env, command="downgrade")
        with temp_engine.begin() as conn:
            _assert_source_deletion_0014_absent(inspect(conn), conn)
            assert "sources" in inspect(conn).get_table_names()
            assert conn.execute(text("SELECT count(*) FROM sources WHERE project_id='project-0014'")).scalar_one() == 5
            assert conn.execute(text("SELECT s3_bucket, s3_object_key FROM sources WHERE id='source-deleted-local'")).one() == ("bucket", "deleted/key")
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0013_job_retry_recovery"
        run_alembic("0014_source_deletion_retention", env=env)
        with temp_engine.begin() as conn:
            _assert_source_deletion_0014_schema(inspect(conn), conn)

    with isolated_migration_database("studio_migration_0014_metadata") as (temp_engine, env):
        Base.metadata.create_all(temp_engine)
        run_alembic("0014_source_deletion_retention", env=env, command="stamp")
        run_alembic("0013_job_retry_recovery", env=env, command="downgrade")
        with temp_engine.begin() as conn:
            _assert_source_deletion_0014_absent(inspect(conn), conn)
            assert "sources" in inspect(conn).get_table_names()
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0013_job_retry_recovery"


def test_job_retry_recovery_0013_upgrade_downgrade_roundtrip_and_metadata_table(tmp_path):
    from studio_api.db import Base

    with isolated_migration_database("studio_migration_0013") as (temp_engine, env):
        run_alembic("0012_output_reconciliation_cases", env=env)
        with temp_engine.begin() as conn:
            # 0001 uses current metadata, so strip only 0013-owned objects to
            # create a genuine historical 0012 shape.
            conn.execute(text("DROP TABLE IF EXISTS transcription_job_source_attempts"))
            conn.execute(text("DROP TYPE IF EXISTS sourceattemptretrydisposition"))
            conn.execute(text("DROP TYPE IF EXISTS sourceattemptstage"))
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0012_output_reconciliation_cases"
            assert "transcription_output_reconciliations" in inspect(conn).get_table_names()
            assert "transcription_job_source_attempts" not in inspect(conn).get_table_names()
            _assert_attempt_enums_absent(conn)
        run_alembic("0014_source_deletion_retention", env=env)
        with temp_engine.begin() as conn:
            _assert_job_retry_recovery_schema(inspect(conn), conn)
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0014_source_deletion_retention"
        run_alembic("0012_output_reconciliation_cases", env=env, command="downgrade")
        with temp_engine.begin() as conn:
            assert "transcription_job_source_attempts" not in inspect(conn).get_table_names()
            assert "transcription_output_reconciliations" in inspect(conn).get_table_names()
            _assert_attempt_enums_absent(conn)
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0012_output_reconciliation_cases"
        run_alembic("0014_source_deletion_retention", env=env)
        with temp_engine.begin() as conn:
            _assert_job_retry_recovery_schema(inspect(conn), conn)
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0014_source_deletion_retention"

    with isolated_migration_database("studio_migration_0013_metadata") as (temp_engine, env):
        Base.metadata.create_all(temp_engine)
        run_alembic("0014_source_deletion_retention", env=env, command="stamp")
        run_alembic("0012_output_reconciliation_cases", env=env, command="downgrade")
        with temp_engine.begin() as conn:
            assert "transcription_job_source_attempts" not in inspect(conn).get_table_names()
            assert "transcription_output_reconciliations" in inspect(conn).get_table_names()
            _assert_attempt_enums_absent(conn)
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0012_output_reconciliation_cases"


def test_job_destination_migration_0008_0009_upgrade_downgrade_backfill(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    import uuid

    temp_db = f"studio_migration_0009_{uuid.uuid4().hex}"
    base_url = make_url(engine.url)
    admin_url = base_url.set(database="postgres")
    temp_url = base_url.set(database=temp_db)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{temp_db}"'))
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL database creation unavailable for isolated migration test: {exc}")
    finally:
        admin_engine.dispose()

    env = os.environ.copy()
    env.pop("STUDIO_DATABASE_URL", None)
    env["STUDIO_DATABASE_NAME"] = temp_db
    temp_engine = create_engine(temp_url)
    try:
        subprocess.run([sys.executable, "-m", "alembic", "-c", str(ALEMBIC), "upgrade", "0008_transcription_job_outputs"], cwd=ROOT, env=env, check=True)
        with temp_engine.begin() as conn:
            # The repository's 0001 baseline reflects current metadata, so strip
            # the 0009 additions to create a genuine revision-0008 shape before
            # inserting legacy rows and upgrading through 0009.
            conn.execute(text("ALTER TABLE transcription_jobs DROP CONSTRAINT IF EXISTS uq_transcription_jobs_batch_position"))
            conn.execute(text("ALTER TABLE transcription_jobs DROP CONSTRAINT IF EXISTS ck_transcription_jobs_batch_fields_all_or_none"))
            for col in ["batch_position", "batch_request_hash", "batch_idempotency_key", "output_drive_folder_name", "output_drive_folder_url", "output_drive_folder_id"]:
                conn.execute(text(f"ALTER TABLE transcription_jobs DROP COLUMN IF EXISTS {col}"))
            conn.execute(text("UPDATE alembic_version SET version_num='0008_transcription_job_outputs'"))
            conn.execute(text("""
                INSERT INTO users (id, email, role, status, created_at, updated_at)
                VALUES ('user-0009', 'migration-0009-isolated@example.com', 'user', 'active', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
            """))
            conn.execute(text("""
                INSERT INTO projects (id, owner_user_id, title, description, created_at, updated_at, archived_at, output_drive_folder_id, output_drive_folder_url, output_drive_folder_name)
                VALUES
                ('project-with-folder', 'user-0009', 'With folder', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', NULL, 'folder-0009', 'https://drive.google.com/drive/folders/folder-0009', 'Migration folder'),
                ('project-without-folder', 'user-0009', 'Without folder', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', NULL, NULL, NULL, NULL)
            """))
            conn.execute(text("""
                INSERT INTO sources (id, project_id, source_type, original_filename, mime_type, size_bytes, drive_file_id, drive_file_url, s3_bucket, s3_object_key, upload_status, uploaded_at, expires_at, deleted_at, delete_reason, created_at, updated_at)
                VALUES
                ('source-with-folder', 'project-with-folder', 'local_upload', 'with.mp3', 'audio/mpeg', 10, NULL, NULL, 'bucket', 'objects/with', 'uploaded', '2026-01-01T00:00:00Z', NULL, NULL, NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'),
                ('source-without-folder', 'project-without-folder', 'local_upload', 'without.mp3', 'audio/mpeg', 10, NULL, NULL, 'bucket', 'objects/without', 'uploaded', '2026-01-01T00:00:00Z', NULL, NULL, NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
            """))
            conn.execute(text("""
                INSERT INTO transcription_jobs (id, project_id, owner_user_id, status, provider, provider_credential_id, title, language, options_json, created_at, updated_at, cancelled_at, started_at, finished_at, error_code, error_message, lease_owner_id, lease_generation, claimed_at, lease_expires_at, attempt_count, cancel_requested_at)
                VALUES
                ('job-with-folder', 'project-with-folder', 'user-0009', 'queued', NULL, NULL, 'Job with folder', 'en', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', NULL, NULL, NULL, NULL, NULL, NULL, 0, NULL, NULL, 0, NULL),
                ('job-without-folder', 'project-without-folder', 'user-0009', 'queued', NULL, NULL, 'Job without folder', 'en', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', NULL, NULL, NULL, NULL, NULL, NULL, 0, NULL, NULL, 0, NULL)
            """))
            conn.execute(text("""
                INSERT INTO transcription_job_sources (id, job_id, source_id, position, status, created_at)
                VALUES
                ('rel-with-folder', 'job-with-folder', 'source-with-folder', 0, 'queued', '2026-01-01T00:00:00Z'),
                ('rel-without-folder', 'job-without-folder', 'source-without-folder', 0, 'queued', '2026-01-01T00:00:00Z')
            """))
            conn.execute(text("""
                INSERT INTO transcription_job_outputs (id, job_id, job_source_id, document_id, web_view_url, output_drive_folder_id, output_kind, transcript_standard, document_character_count, document_created_at, persisted_at, lease_generation)
                VALUES ('output-with-folder', 'job-with-folder', 'rel-with-folder', 'doc-0009', 'https://docs.google.com/document/d/doc-0009/edit', 'folder-0009', 'google_docs_transcript', 'transcript_doc_v1.2', 12, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 0)
            """))

        subprocess.run([sys.executable, "-m", "alembic", "-c", str(ALEMBIC), "upgrade", "0009_job_output_destinations"], cwd=ROOT, env=env, check=True)
        with temp_engine.begin() as conn:
            cols = {c["name"] for c in inspect(conn).get_columns("transcription_jobs")}
            assert {"output_drive_folder_id", "output_drive_folder_url", "output_drive_folder_name", "batch_idempotency_key", "batch_request_hash", "batch_position"}.issubset(cols)
            rows = conn.execute(text("SELECT id, project_id, owner_user_id, status, output_drive_folder_id, output_drive_folder_url, output_drive_folder_name, batch_idempotency_key, batch_request_hash, batch_position FROM transcription_jobs ORDER BY id")).mappings().all()
            by_id = {row["id"]: row for row in rows}
            assert by_id["job-with-folder"]["output_drive_folder_id"] == "folder-0009"
            assert by_id["job-with-folder"]["output_drive_folder_url"] == "https://drive.google.com/drive/folders/folder-0009"
            assert by_id["job-with-folder"]["output_drive_folder_name"] == "Migration folder"
            assert by_id["job-without-folder"]["output_drive_folder_id"] is None
            assert all(row["batch_idempotency_key"] is None and row["batch_request_hash"] is None and row["batch_position"] is None for row in rows)
            assert conn.execute(text("SELECT count(*) FROM transcription_job_sources WHERE id IN ('rel-with-folder', 'rel-without-folder')")).scalar_one() == 2
            assert conn.execute(text("SELECT output_drive_folder_id, web_view_url FROM transcription_job_outputs WHERE id='output-with-folder'")).one() == ("folder-0009", "https://docs.google.com/document/d/doc-0009/edit")
            conn.execute(text("INSERT INTO transcription_jobs (id, project_id, owner_user_id, status, created_at, updated_at, lease_generation, attempt_count) VALUES ('legacy-null-batch', 'project-with-folder', 'user-0009', 'queued', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 0, 0)"))
            conn.execute(text("INSERT INTO transcription_jobs (id, project_id, owner_user_id, status, created_at, updated_at, lease_generation, attempt_count, batch_idempotency_key, batch_request_hash, batch_position) VALUES ('batch-valid', 'project-with-folder', 'user-0009', 'queued', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 0, 0, 'key', :hash, 0)"), {"hash": "a"*64})
        invalid_inserts = [
            ("INSERT INTO transcription_jobs (id, project_id, owner_user_id, status, created_at, updated_at, lease_generation, attempt_count, batch_idempotency_key) VALUES ('batch-partial', 'project-with-folder', 'user-0009', 'queued', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 0, 0, 'partial')", {}),
            ("INSERT INTO transcription_jobs (id, project_id, owner_user_id, status, created_at, updated_at, lease_generation, attempt_count, batch_idempotency_key, batch_request_hash, batch_position) VALUES ('batch-negative', 'project-with-folder', 'user-0009', 'queued', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 0, 0, 'neg', :hash, -1)", {"hash": "b"*64}),
            ("INSERT INTO transcription_jobs (id, project_id, owner_user_id, status, created_at, updated_at, lease_generation, attempt_count, batch_idempotency_key, batch_request_hash, batch_position) VALUES ('batch-duplicate', 'project-with-folder', 'user-0009', 'queued', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 0, 0, 'key', :hash, 0)", {"hash": "c"*64}),
        ]
        for stmt, params in invalid_inserts:
            with pytest.raises(Exception):
                with temp_engine.begin() as conn:
                    conn.execute(text(stmt), params)
        subprocess.run([sys.executable, "-m", "alembic", "-c", str(ALEMBIC), "downgrade", "0008_transcription_job_outputs"], cwd=ROOT, env=env, check=True)
        with temp_engine.begin() as conn:
            cols = {c["name"] for c in inspect(conn).get_columns("transcription_jobs")}
            assert not {"output_drive_folder_id", "output_drive_folder_url", "output_drive_folder_name", "batch_idempotency_key", "batch_request_hash", "batch_position"} & cols
            constraints = {c["name"] for c in inspect(conn).get_check_constraints("transcription_jobs")} | {c["name"] for c in inspect(conn).get_unique_constraints("transcription_jobs")}
            assert "ck_transcription_jobs_batch_fields_all_or_none" not in constraints
            assert "uq_transcription_jobs_batch_position" not in constraints
            assert conn.execute(text("SELECT count(*) FROM transcription_jobs WHERE id IN ('job-with-folder', 'job-without-folder')")).scalar_one() == 2
            assert conn.execute(text("SELECT count(*) FROM transcription_job_sources WHERE id IN ('rel-with-folder', 'rel-without-folder')")).scalar_one() == 2
            assert conn.execute(text("SELECT count(*) FROM transcription_job_outputs WHERE id='output-with-folder'")).scalar_one() == 1
        subprocess.run([sys.executable, "-m", "alembic", "-c", str(ALEMBIC), "upgrade", "0009_job_output_destinations"], cwd=ROOT, env=env, check=True)
        with temp_engine.begin() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0009_job_output_destinations"
        cfg = Config(str(ALEMBIC))
        assert ScriptDirectory.from_config(cfg).get_current_head() == "0044_quality_progress"
    finally:
        temp_engine.dispose()
        cleanup_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            with cleanup_engine.connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{temp_db}" WITH (FORCE)'))
        finally:
            cleanup_engine.dispose()

def test_job_destination_0009_current_schema_constraints():
    inspector = inspect(engine)
    cols = {c["name"]: c for c in inspector.get_columns("transcription_jobs")}
    assert {"output_drive_folder_id", "output_drive_folder_url", "output_drive_folder_name", "batch_idempotency_key", "batch_request_hash", "batch_position"}.issubset(cols)
    constraints = {c["name"] for c in inspector.get_check_constraints("transcription_jobs")} | {c["name"] for c in inspector.get_unique_constraints("transcription_jobs")}
    assert "ck_transcription_jobs_batch_fields_all_or_none" in constraints
    assert "uq_transcription_jobs_batch_position" in constraints
    db = SessionLocal()
    try:
        user = User(email="migration-0009@example.com", role=UserRole.user, status=UserStatus.active); db.add(user); db.flush()
        p1 = Project(owner_user_id=user.id, title="With folder", output_drive_folder_id="folder-m", output_drive_folder_url="https://drive.google.com/drive/folders/folder-m", output_drive_folder_name="Migrated")
        p2 = Project(owner_user_id=user.id, title="Without folder")
        db.add_all([p1, p2]); db.flush()
        j1 = TranscriptionJob(project_id=p1.id, owner_user_id=user.id, status=JobStatus.queued)
        j1.apply_output_folder_snapshot(folder_id=p1.output_drive_folder_id, folder_url=p1.output_drive_folder_url, folder_name=p1.output_drive_folder_name)
        j2 = TranscriptionJob(project_id=p2.id, owner_user_id=user.id, status=JobStatus.queued)
        batch_ok = TranscriptionJob(project_id=p1.id, owner_user_id=user.id, status=JobStatus.queued, batch_idempotency_key="key", batch_request_hash="a"*64, batch_position=0)
        db.add_all([j1, j2, batch_ok]); db.flush(); db.commit()
        assert j1.output_drive_folder_id == "folder-m" and j1.batch_idempotency_key is None
        assert j2.output_drive_folder_id is None and j2.batch_idempotency_key is None
        db.add(TranscriptionJob(project_id=p1.id, owner_user_id=user.id, status=JobStatus.queued, batch_idempotency_key="partial"));
        with pytest.raises(Exception): db.commit()
        db.rollback()
        db.add(TranscriptionJob(project_id=p1.id, owner_user_id=user.id, status=JobStatus.queued, batch_idempotency_key="neg", batch_request_hash="b"*64, batch_position=-1));
        with pytest.raises(Exception): db.commit()
        db.rollback()
        db.add(TranscriptionJob(project_id=p1.id, owner_user_id=user.id, status=JobStatus.queued, batch_idempotency_key="key", batch_request_hash="c"*64, batch_position=0));
        with pytest.raises(Exception): db.commit()
        db.rollback()
        db.add_all([TranscriptionJob(project_id=p1.id, owner_user_id=user.id, status=JobStatus.queued), TranscriptionJob(project_id=p1.id, owner_user_id=user.id, status=JobStatus.queued)])
        db.commit()
    finally:
        db.close()


def test_diagnostics_debug_session_auth_csrf_bounds_conflict_and_stop_idempotent():
    pw = admin("debug-owner@example.com"); c = TestClient(app)
    assert c.get("/api/diagnostics/debug-session").status_code == 401
    csrf = login(c, pw, "debug-owner@example.com")
    assert c.post("/api/diagnostics/debug-session", json={"duration_minutes": 5}, headers={"origin": "https://evil.test", "x-csrf-token": csrf}).status_code == 403
    assert c.delete("/api/diagnostics/debug-session", headers={"origin": "https://evil.test", "x-csrf-token": csrf}).status_code == 403
    assert c.post("/api/diagnostics/debug-session", json={"duration_minutes": 5}, headers={"origin": "https://studio.test", "x-csrf-token": "bad"}).status_code == 403
    assert c.post("/api/diagnostics/debug-session", json={"duration_minutes": 0}, headers={"origin": "https://studio.test", "x-csrf-token": csrf}).status_code == 422
    assert c.post("/api/diagnostics/debug-session", json={"duration_minutes": 31}, headers={"origin": "https://studio.test", "x-csrf-token": csrf}).status_code == 422
    r = c.post("/api/diagnostics/debug-session", json={"duration_minutes": 5}, headers={"origin": "https://studio.test", "x-csrf-token": csrf})
    assert r.status_code == 200
    body = r.json(); assert body["active"] is True and body["max_duration_minutes"] == 30 and "id" not in body
    first_expiry = body["expires_at"]
    conflict = c.post("/api/diagnostics/debug-session", json={"duration_minutes": 30}, headers={"origin": "https://studio.test", "x-csrf-token": csrf})
    assert conflict.status_code == 409 and conflict.json()["detail"]["expires_at"] == first_expiry
    assert c.delete("/api/diagnostics/debug-session", headers={"origin": "https://studio.test", "x-csrf-token": csrf}).json() == {"active": False, "max_duration_minutes": 30}
    assert c.delete("/api/diagnostics/debug-session", headers={"origin": "https://studio.test", "x-csrf-token": csrf}).json() == {"active": False, "max_duration_minutes": 30}


def test_diagnostics_debug_session_owner_scope_and_expired_inactive():
    pw1 = admin("debug-a@example.com"); pw2 = admin("debug-b@example.com")
    c1 = TestClient(app); c2 = TestClient(app)
    csrf1 = login(c1, pw1, "debug-a@example.com"); csrf2 = login(c2, pw2, "debug-b@example.com")
    r = c1.post("/api/diagnostics/debug-session", json={"duration_minutes": 1}, headers={"origin": "https://studio.test", "x-csrf-token": csrf1})
    assert r.status_code == 200
    assert c2.get("/api/diagnostics/debug-session").json() == {"active": False, "max_duration_minutes": 30}
    assert c2.post("/api/diagnostics/debug-session", json={"duration_minutes": 1}, headers={"origin": "https://studio.test", "x-csrf-token": csrf2}).status_code == 200
    db = SessionLocal(); owner = db.query(User).filter_by(email="debug-a@example.com").one(); assert db.query(DiagnosticDebugSession).count() == 2; row = db.query(DiagnosticDebugSession).filter_by(owner_user_id=owner.id).one(); past_start = utcnow() - timedelta(minutes=2); row.started_at = past_start; row.expires_at = past_start + timedelta(minutes=1); db.commit(); db.close()
    assert c1.get("/api/diagnostics/debug-session").json() == {"active": False, "max_duration_minutes": 30}
    assert c1.post("/api/diagnostics/debug-session", json={"duration_minutes": 2}, headers={"origin": "https://studio.test", "x-csrf-token": csrf1}).status_code == 200
    db = SessionLocal(); assert db.query(DiagnosticDebugSession).count() == 2; db.close()


def test_pwa_diagnostics_ingestion_security_validation_and_visibility():
    pw = admin("pwa@example.com"); c = TestClient(app); csrf = login(c, pw, "pwa@example.com")
    payload = {"events": [{"event_code": "PWA_API_REQUEST_FAILED", "metadata": {"endpoint_group": "jobs", "http_status_category": "5xx", "duration_ms": 123, "retryable": True}}]}
    db = SessionLocal(); audit_count = db.query(AuditEvent).count(); db.close()
    assert TestClient(app).post("/api/diagnostics/pwa-events", json=payload).status_code == 401
    assert c.post("/api/diagnostics/pwa-events", json=payload, headers={"origin": "https://evil.test", "x-csrf-token": csrf}).status_code == 403
    assert c.post("/api/diagnostics/pwa-events", json=payload, headers={"origin": "https://studio.test", "x-csrf-token": "bad"}).status_code == 403
    ok = c.post("/api/diagnostics/pwa-events", json=payload, headers={"origin": "https://studio.test", "x-csrf-token": csrf})
    assert ok.status_code == 200 and ok.json()["accepted"] == 1
    db = SessionLocal(); row = db.query(DiagnosticEvent).one(); assert row.owner_user_id and row.component.value == "web" and row.event_code == "PWA_API_REQUEST_FAILED" and row.level.value == "WARNING" and row.request_id.startswith("req_"); db.close()
    events = c.get("/api/diagnostics/events?component=web&event_code=PWA_API_REQUEST_FAILED").json()["events"]
    assert len(events) == 1 and events[0]["metadata"]["endpoint_group"] == "jobs"
    db = SessionLocal(); audit_rows = db.query(AuditEvent).all(); assert len(audit_rows) == audit_count; assert all("PWA_" not in row.event_type and "PWA_" not in row.metadata_json for row in audit_rows); db.close()


def test_pwa_diagnostics_rejects_unknown_nested_oversized_forbidden_and_debug_without_session():
    pw = admin("pwa-reject@example.com"); c = TestClient(app); csrf = login(c, pw, "pwa-reject@example.com")
    headers={"origin": "https://studio.test", "x-csrf-token": csrf}
    from studio_api.diagnostics import write_diagnostic_event
    db = SessionLocal(); user = db.query(User).filter_by(email="pwa-reject@example.com").one(); user_id = user.id; db.close()
    assert write_diagnostic_event(owner_user_id=user_id, component="web", event_code="PWA_APP_ERROR", level="DEBUG", metadata={"error_code": "unknown"}).accepted is False
    bad_payloads = [
        {"events": [{"event_code": "NOPE", "metadata": {}}]},
        {"events": [{"event_code": "PWA_APP_ERROR", "metadata": {"unknown": "x"}}]},
        {"events": [{"event_code": "PWA_APP_ERROR", "metadata": {"error_code": {"nested": "x"}}}]},
        {"events": [{"event_code": "PWA_APP_ERROR", "metadata": {"duration_ms": 86400001}}]},
        {"events": [{"event_code": "PWA_APP_ERROR", "metadata": {"error_code": "https://example.test/file.mp3?token=value"}}]},
        {"events": [{"event_code": "PWA_APP_ERROR", "level": "DEBUG", "metadata": {"error_code": "unknown"}}]},
    ]
    for payload in bad_payloads:
        assert c.post("/api/diagnostics/pwa-events", json=payload, headers=headers).status_code in {403, 422}
    db=SessionLocal(); assert db.query(DiagnosticEvent).count() == 0; db.close()


def test_pwa_debug_ingestion_requires_active_session_and_does_not_extend_expiry():
    pw = admin("pwa-debug@example.com"); c = TestClient(app); csrf = login(c, pw, "pwa-debug@example.com")
    headers={"origin": "https://studio.test", "x-csrf-token": csrf}
    payload={"events": [{"event_code": "PWA_APP_ERROR", "level": "DEBUG", "metadata": {"error_code": "unknown"}}]}
    assert c.post("/api/diagnostics/pwa-events", json=payload, headers=headers).status_code == 403
    started=c.post("/api/diagnostics/debug-session", json={"duration_minutes": 10}, headers=headers).json(); expiry=started["expires_at"]
    assert c.post("/api/diagnostics/pwa-events", json=payload, headers=headers).status_code == 200
    assert c.get("/api/diagnostics/debug-session").json()["expires_at"] == expiry
    db=SessionLocal(); row=db.query(DiagnosticDebugSession).one(); past_start=utcnow() - timedelta(minutes=2); row.started_at=past_start; row.expires_at=past_start + timedelta(minutes=1); db.commit(); db.close()
    assert c.post("/api/diagnostics/pwa-events", json=payload, headers=headers).status_code == 403


def test_audio_export_api_checks_auth_and_folder_before_queueing(monkeypatch):
    from types import SimpleNamespace
    from studio_api.models import AudioPreparationJob, AudioPreparationStatus
    email = "audio-export-owner@example.com"
    client = TestClient(app)
    csrf = login(client, admin(email), email)
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    project_id = client.post("/api/transcriptions/workspace", headers=headers).json()["project"]["id"]
    with SessionLocal() as db:
        owner = db.execute(select(User).where(User.email == email)).scalar_one()
        source = Source(project_id=project_id, source_type=SourceType.local_upload, original_filename="Готовый.flac",
            mime_type="audio/flac", size_bytes=5, s3_bucket="private", s3_object_key="ready",
            upload_status=SourceUploadStatus.uploaded, expires_at=utcnow() + timedelta(days=1))
        db.add(source); db.flush()
        job = AudioPreparationJob(project_id=project_id, owner_user_id=owner.id, title="Готовый",
            options_json="{}", status=AudioPreparationStatus.completed, current_stage="completed", output_source_id=source.id)
        db.add(job); db.commit()
        job_id = job.id
    external = []
    monkeypatch.setattr("studio_api.google_connection_access.refresh_user_google_drive_access_token", lambda *args, **kwargs: external.append("token") or "synthetic")
    def verify(token, folder_id):
        external.append(folder_id)
        if folder_id == "denied":
            from fastapi import HTTPException
            raise HTTPException(403, "Folder unavailable")
        return SimpleNamespace(id=folder_id, name="Результаты", web_view_url="https://drive.google.com/drive/folders/" + folder_id)
    monkeypatch.setattr("studio_api.main.verify_output_folder_selection", verify)
    route = f"/api/audio-preparations/{job_id}/save-to-drive"
    assert TestClient(app).post(route, headers=headers, json={"folder_id": "folder"}).status_code == 401
    assert client.post(route, headers={"origin": "https://studio.test"}, json={"folder_id": "folder"}).status_code == 403
    assert client.post(route, headers={**headers, "origin": "https://foreign.test"}, json={"folder_id": "folder"}).status_code == 403
    other = TestClient(app)
    other_email = "audio-export-other@example.com"
    other_csrf = login(other, admin(other_email), other_email)
    assert other.post(route, headers={**headers, "x-csrf-token": other_csrf}, json={"folder_id": "folder"}).status_code == 404
    assert external == []
    assert client.post(route, headers=headers, json={"folder_id": "denied"}).status_code == 403
    with SessionLocal() as db:
        assert db.get(AudioPreparationJob, job_id).current_stage == "completed"
    first = client.post(route, headers=headers, json={"folder_id": "folder"})
    assert first.status_code == 200
    assert first.json()["status"] == "completed"
    assert first.json()["progress"]["stage"] == "google_drive_export_queued"
    assert first.json()["output"]["download_ready"] is True
    assert "s3_object_key" not in first.text and "synthetic" not in first.text
    assert client.post(route, headers=headers, json={"folder_id": "folder"}).json()["id"] == job_id


@pytest.mark.parametrize("sample", [False, True])
def test_audio_regeneration_api_is_owner_csrf_scoped_and_only_enqueues(tmp_path, monkeypatch, sample):
    from studio_api.audio_downloads import AudioDownloadManager
    from studio_api.models import AudioPreparationJob, AudioPreparationJobInput, AudioPreparationStatus
    from studio_api import main as api_main
    email = "audio-regeneration-owner@example.com"
    client = TestClient(app)
    csrf = login(client, admin(email), email)
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    project_id = client.post("/api/transcriptions/workspace", headers=headers).json()["project"]["id"]
    root = tmp_path / "transfer"
    root.mkdir()
    monkeypatch.setattr(api_main, "audio_downloads", AudioDownloadManager(SessionLocal, api_main.settings, cache_root=root))
    with SessionLocal() as db:
        owner = db.execute(select(User).where(User.email == email)).scalar_one()
        source = Source(project_id=project_id, source_type=SourceType.local_upload,
            original_filename="Лекция.flac", mime_type="audio/flac", size_bytes=14,
            s3_bucket="private", s3_object_key="original", upload_status=SourceUploadStatus.uploaded,
            expires_at=utcnow() + timedelta(days=7))
        db.add(source)
        db.flush()
        job = AudioPreparationJob(project_id=project_id, owner_user_id=owner.id, title="Лекция",
            options_json='{"output_format":"flac"}',
            status=AudioPreparationStatus.preview_ready if sample else AudioPreparationStatus.completed,
            current_stage="preview_ready" if sample else "completed",
            output_filename=None if sample else "Лекция.flac", output_mime_type="audio/flac", output_size_bytes=14)
        db.add(job)
        db.flush()
        db.add(AudioPreparationJobInput(job_id=job.id, source_id=source.id, position=0, ephemeral_reference=True))
        db.commit()
        job_id = job.id
    route = f"/api/audio-preparations/{job_id}/{'preview-audio' if sample else 'download'}"
    download_route = f"/api/audio-preparations/{job_id}/download"
    listen_route = f"/api/audio-preparations/{job_id}/listen"
    assert TestClient(app).post(route, headers=headers).status_code == 401
    assert client.post(route, headers={"origin": "https://studio.test"}).status_code == 403
    assert client.post(route, headers={**headers, "origin": "https://foreign.test"}).status_code == 403
    other = TestClient(app)
    other_email = "audio-regeneration-other@example.com"
    other_csrf = login(other, admin(other_email), other_email)
    other_headers = {**headers, "x-csrf-token": other_csrf}
    assert other.post(route, headers=other_headers).status_code == 404
    first = client.post(route, headers=headers)
    assert first.status_code == 200 and first.json()["state"] == "preparing"
    with SessionLocal() as db:
        persisted = db.get(AudioPreparationJob, job_id)
        request_id = persisted.download_request_id
        assert persisted.current_stage == "audio_download_queued" and persisted.download_slot == 1
        assert persisted.output_source_id is None and persisted.lease_owner_id is None
        assert persisted.download_preview is sample
        assert db.execute(select(func.count(Source.id)).where(Source.project_id == project_id)).scalar_one() == 1
    assert client.post(route, headers=headers).json()["state"] == "preparing"
    with SessionLocal() as db:
        assert db.get(AudioPreparationJob, job_id).download_request_id == request_id
    for site in ("cross-site", "same-site"):
        assert client.get(download_route, headers={"sec-fetch-site": site}).status_code == 403
        assert client.get(listen_route, headers={"sec-fetch-site": site}).status_code == 403
    assert TestClient(app).get(listen_route).status_code == 401
    assert other.get(listen_route).status_code == 404
    assert client.get(listen_route).status_code == 409
    assert client.get(download_route).status_code == 409
    assert other.get(download_route + "/status").status_code == 404
    assert other.post(download_route + "/cancel", headers=other_headers).status_code == 404
    assert client.post(download_route + "/cancel", headers=headers).status_code == 200
    assert client.get(download_route + "/status").json()["reason"] == "cancellation_requested"


def test_long_recording_confirmation_rejects_stale_quote_and_requires_owner_csrf(monkeypatch):
    from studio_api import main as api_main
    from studio_api.job_retry_recovery import RetryReadiness, RetryReason, RetryQueueResult
    from studio_api.long_media_preflight import long_media_preflight_payload
    email = "long-estimate-owner@example.com"
    client = TestClient(app)
    csrf = login(client, admin(email), email)
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    with SessionLocal() as db:
        owner = db.query(User).filter_by(email=email).one()
        project = Project(owner_user_id=owner.id, title="Synthetic estimate")
        db.add(project); db.flush()
        job = TranscriptionJob(project_id=project.id, owner_user_id=owner.id, provider="elevenlabs",
            status=JobStatus.failed, error_code="media_duration_confirmation_required", attempt_count=1,
            long_duration_preflight_json=json.dumps({"source_duration_seconds": 18000, "selected_duration_seconds": 18000,
                "nominal_cost": "1.10000000", "currency": "USD", "rate_per_hour": "0.220000",
                "effective_date": "2026-10-06", "source": "elevenlabs_public_api_pricing", "provider": "elevenlabs",
                "additional_source_count": 0, "maximum_seconds_per_source": 43200,
                "basis": "measured_duration_x_immutable_public_tariff", "invoice_debit": False}))
        db.add(job); db.commit()
        job_id, quote = job.id, long_media_preflight_payload(job)
    ready = RetryReadiness(True, RetryReason.available, 1, 3, 1, 1)
    monkeypatch.setattr(api_main, "compute_explicit_retry_readiness", lambda *a, **k: ready)
    queued = []
    def queue(db, **kwargs):
        job = db.get(TranscriptionJob, kwargs["job_id"])
        queued.append(job.long_duration_cost_confirmed)
        job.status = JobStatus.queued
        return RetryQueueResult(job, ready, True)
    monkeypatch.setattr(api_main, "queue_retry", queue)
    route = f"/api/jobs/{job_id}/retry"
    data = {"confirm_long_duration_cost": True, "long_duration_confirmation_token": quote["confirmation_token"]}
    assert TestClient(app).post(route, headers=headers, json=data).status_code == 401
    assert client.post(route, json=data).status_code == 403
    for rejected in ({}, {"confirm_long_duration_cost": True}, {**data, "long_duration_confirmation_token": "f" * 64}):
        response = client.post(route, headers=headers, json=rejected)
        assert response.status_code == 409
        assert response.json()["detail"]["preflight"]["nominal_cost"] == "1.10000000"
    assert queued == []
    assert client.post(route, headers=headers, json=data).status_code == 200
    assert queued == [True]


def test_audio_reuse_imports_only_verified_drive_copy_and_is_idempotent(monkeypatch):
    from types import SimpleNamespace
    from studio_api import main as api_main
    from studio_api.models import AudioPreparationJob, AudioPreparationStatus
    email = "audio-reuse-owner@example.com"
    client = TestClient(app)
    csrf = login(client, admin(email), email)
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    project_id = client.post("/api/transcriptions/workspace", headers=headers).json()["project"]["id"]
    with SessionLocal() as db:
        owner = db.execute(select(User).where(User.email == email)).scalar_one()
        job = AudioPreparationJob(project_id=project_id, owner_user_id=owner.id, title="Лекция",
            options_json="{}", status=AudioPreparationStatus.completed, current_stage="completed",
            output_filename="Лекция.flac", output_mime_type="audio/flac", output_size_bytes=14,
            output_drive_file_id="prepared-audio-file", output_drive_web_view_url="https://drive.google.com/file/d/prepared-audio-file/view")
        db.add(job)
        db.commit()
        job_id = job.id
    calls = []
    monkeypatch.setattr(api_main, "refreshed_google_drive_access_token", lambda *args: "synthetic-token")
    def metadata(db, user, file_id, **kwargs):
        assert not db.in_transaction()
        calls.append(file_id)
        return SimpleNamespace(id=file_id, name="Лекция.flac", size_bytes=14, is_folder=False,
            created_time="2026-10-05T21:00:00Z", web_view_link="https://drive.google.com/file/d/prepared-audio-file/view"), "audio/flac"
    monkeypatch.setattr(api_main, "_validated_google_drive_source_metadata", metadata)
    route = f"/api/audio-preparations/{job_id}/reuse-source"
    assert TestClient(app).post(route, headers=headers).status_code == 401
    assert client.post(route, headers={"origin": "https://studio.test"}).status_code == 403
    first = client.post(route, headers=headers)
    assert first.status_code == 200 and first.json()["source_type"] == "google_drive"
    assert first.json()["original_filename"] == "Лекция.flac"
    assert "synthetic-token" not in first.text
    assert client.post(route, headers=headers).json()["id"] == first.json()["id"]
    with SessionLocal() as db:
        assert db.execute(select(func.count(Source.id)).where(Source.project_id == project_id)).scalar_one() == 1
        source = db.get(Source, first.json()["id"])
        assert source.s3_object_key is None and source.s3_bucket is None
    assert calls == ["prepared-audio-file", "prepared-audio-file"]


def test_audio_legacy_recovery_api_is_owner_csrf_scoped_and_never_calls_google(monkeypatch):
    from studio_api.audio_preparation_service import OUTPUT_SOURCE_NAMESPACE
    from studio_api.models import AudioPreparationJob, AudioPreparationStatus
    from studio_api.source_storage import safe_filename
    email = "audio-recovery-owner@example.com"
    client = TestClient(app)
    csrf = login(client, admin(email), email)
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    project_id = client.post("/api/transcriptions/workspace", headers=headers).json()["project"]["id"]
    with SessionLocal() as db:
        owner = db.execute(select(User).where(User.email == email)).scalar_one()
        job = AudioPreparationJob(id=str(uuid.uuid4()), project_id=project_id, owner_user_id=owner.id,
            title="Ready", options_json="{}", status=AudioPreparationStatus.failed, current_stage="failed")
        source = Source(id=str(uuid.uuid5(OUTPUT_SOURCE_NAMESPACE, job.id)), project_id=project_id,
            source_type=SourceType.local_upload, reference_class="audio_processing", original_filename="Ready.flac",
            mime_type="audio/flac", size_bytes=5, s3_bucket="audio-private",
            s3_object_key=f"audio-preparation/{owner.id}/{job.id}/{safe_filename('Ready.flac')}",
            upload_status=SourceUploadStatus.uploaded, expires_at=utcnow() + timedelta(days=1))
        db.add_all([job, source]); db.commit()
        job_id, source_id = job.id, source.id
    def no_google(*args, **kwargs):
        pytest.fail("Recovery must not call Google or a provider")
    monkeypatch.setattr("studio_api.google_connection_access.refresh_user_google_drive_access_token", no_google)
    route = f"/api/audio-preparations/{job_id}/recover-output"
    assert TestClient(app).post(route, headers=headers).status_code == 401
    assert client.post(route, headers={"origin": "https://studio.test"}).status_code == 403
    assert client.post(route, headers={**headers, "origin": "https://foreign.test"}).status_code == 403
    other = TestClient(app)
    other_email = "audio-recovery-other@example.com"
    other_csrf = login(other, admin(other_email), other_email)
    assert other.post(route, headers={**headers, "x-csrf-token": other_csrf}).status_code == 404
    first = client.post(route, headers=headers)
    assert first.status_code == 200 and first.json()["output"]["source_id"] == source_id
    assert first.json()["status"] == "completed" and first.json()["progress"]["stage"] == "google_drive_export_failed"
    assert "s3_object_key" not in first.text and "audio-private" not in first.text
    assert client.post(route, headers=headers).json()["id"] == job_id


@pytest.mark.parametrize("session_mode", ["missing", "other_browser", "other_owner", "revoked", "expired"])
def test_oauth_callback_never_exchanges_outside_initiating_session(monkeypatch, tmp_path, session_mode):
    from urllib.parse import parse_qs, urlparse
    from studio_api.models import GoogleOAuthState, GoogleConnection
    configure_google_oauth(monkeypatch, tmp_path)
    password = admin("oauth-initiator@example.com")
    initiator = TestClient(app, follow_redirects=False)
    csrf = login(initiator, password, "oauth-initiator@example.com")
    started = initiator.post("/api/google/oauth/start", headers={"origin": "https://studio.test", "x-csrf-token": csrf})
    state = parse_qs(urlparse(started.json()["authorization_url"]).query)["state"][0]
    callback_client = initiator
    if session_mode == "missing": callback_client = TestClient(app, follow_redirects=False)
    if session_mode == "other_browser":
        callback_client = TestClient(app, follow_redirects=False)
        login(callback_client, password, "oauth-initiator@example.com")
    if session_mode == "other_owner":
        other_password = admin("oauth-other@example.com")
        callback_client = TestClient(app, follow_redirects=False)
        login(callback_client, other_password, "oauth-other@example.com")
    with SessionLocal() as db:
        pending = db.query(GoogleOAuthState).one()
        sess = db.get(DbSession, pending.session_id)
        if session_mode == "revoked": sess.revoked_at = utcnow()
        if session_mode == "expired": sess.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    monkeypatch.setattr("studio_api.google_oauth.exchange_code_for_tokens", lambda *a: pytest.fail("unauthorized token exchange"))
    assert_oauth_redirect(callback_client.get(f"/api/google/oauth/callback?state={state}&code=synthetic"), "invalid_state")
    with SessionLocal() as db:
        assert db.query(GoogleConnection).count() == 0
        assert db.query(GoogleOAuthState).one().used_at is None


def test_totp_enable_and_recovery_rotation_revoke_other_owner_sessions(monkeypatch):
    clock = [int(time.time()) // 30 * 30 + 5]
    monkeypatch.setattr("studio_api.account_security.time.time", lambda: clock[0])
    password = admin("totp-security@example.com")
    owner = TestClient(app)
    other_session = TestClient(app)
    csrf = login(owner, password, "totp-security@example.com")
    login(other_session, password, "totp-security@example.com")
    stranger_password = admin("totp-stranger@example.com")
    stranger = TestClient(app)
    login(stranger, stranger_password, "totp-stranger@example.com")
    headers = {"origin": "https://studio.test", "x-csrf-token": csrf}
    secret = owner.post("/api/auth/totp/enroll", headers=headers).json()["secret"]
    code = _totp(secret, int(time.time()) // 30)
    assert owner.post("/api/auth/totp/confirm", json={"verification_code": code}, headers=headers).status_code == 200
    assert other_session.get("/api/auth/session").status_code == 401
    assert owner.get("/api/auth/session").status_code == 200
    assert stranger.get("/api/auth/session").status_code == 200
    context = other_session.post("/api/auth/login-context", headers={"origin": "https://studio.test"}).json()["login_csrf_token"]
    clock[0] += 30
    code = _totp(secret, int(time.time()) // 30)
    assert other_session.post("/api/auth/login", json={"email": "totp-security@example.com", "password": password, "login_csrf_token": context, "verification_code": code}, headers={"origin": "https://studio.test"}).status_code == 200
    assert owner.post("/api/auth/totp/recovery-codes", headers=headers).status_code == 200
    assert other_session.get("/api/auth/session").status_code == 401
    assert owner.get("/api/auth/session").status_code == 200
    assert stranger.get("/api/auth/session").status_code == 200


def test_login_account_limit_survives_rotating_network_identity(monkeypatch):
    from studio_api import main
    password = admin("account-throttle@example.com")
    for attempt in range(11):
        monkeypatch.setattr(main, "client_id", lambda _r, attempt=attempt: f"198.51.100.{attempt + 1}")
        client = TestClient(app)
        context = client.post("/api/auth/login-context", headers={"origin": "https://studio.test"}).json()["login_csrf_token"]
        rejected = client.post("/api/auth/login", json={"email": "account-throttle@example.com", "password": "wrong-password", "login_csrf_token": context}, headers={"origin": "https://studio.test"})
        assert rejected.status_code == (401 if attempt < 10 else 429)
    assert rejected.headers["retry-after"]


def test_concurrent_owner_drafts_cannot_overrun_shared_budget(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from studio_api import main
    from studio_api.realtime_drafts import save_realtime_draft, RealtimeDraftError
    admin("draft-budget@example.com")
    with SessionLocal() as db:
        owner = db.query(User).filter_by(email="draft-budget@example.com").one()
        project = Project(owner_user_id=owner.id, title="Budget fixture")
        db.add(project); db.commit()
        owner_id, project_id = owner.id, project.id
    monkeypatch.setattr(main.settings, "realtime_draft_max_count", 1)
    barrier = Barrier(2)
    def save(index):
        with SessionLocal() as db:
            project = db.get(Project, project_id)
            barrier.wait(timeout=5)
            try:
                save_realtime_draft(db, owner_user_id=owner_id, project=project,
                    client_session_id=f"synthetic_session_{index}", revision=1,
                    committed_segments=["synthetic text"], partial="", settings=main.settings, now=utcnow())
                db.commit()
                return True
            except RealtimeDraftError as exc:
                assert exc.reason.value == "realtime_draft_storage_limit"
                db.rollback()
                return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(save, range(2))) == 1
    with SessionLocal() as db:
        assert db.query(RealtimeTranscriptDraft).filter_by(owner_user_id=owner_id).count() == 1


def test_yandex_capability_redis_consume_allows_only_one_concurrent_claim():
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace
    from studio_api.yandex_realtime_relay import consume_yandex_realtime_capability, YandexRealtimeCapabilityError
    authority = SimpleNamespace(nonce="synthetic-redis-replay-regression", expires_epoch=int(time.time()) + 300)
    def consume(_):
        try:
            consume_yandex_realtime_capability(authority, settings=None, redis=limiter.redis)
            return True
        except YandexRealtimeCapabilityError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(consume, range(16))) == 1


def test_totp_counter_consumption_accepts_exactly_one_concurrent_request():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from studio_api.account_security import consume_totp_code

    admin("totp-concurrency@example.test")
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    with SessionLocal() as db:
        user = db.query(User).filter_by(email="totp-concurrency@example.test").one()
        user_id = user.id
        db.add(UserTotpFactor(user_id=user_id, secret_ciphertext=b"synthetic", secret_nonce=b"synthetic-nonce",
                              key_id="synthetic", confirmed_at=utcnow()))
        db.commit()
    barrier = Barrier(2)
    def consume(_):
        with SessionLocal() as db:
            factor = db.get(UserTotpFactor, user_id)
            barrier.wait(timeout=5)
            result = consume_totp_code(db, factor=factor, secret=secret, code=_totp(secret, 6), timestamp=180)
            db.commit()
            return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(consume, range(2))) == 1
