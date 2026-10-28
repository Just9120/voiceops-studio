from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

import sqlalchemy as sa


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


def test_rfc6238_sha1_totp_vector_and_bounded_window():
    from studio_api.account_security import verify_totp

    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert verify_totp(secret, "287082", timestamp=59)
    assert verify_totp(secret, "287082", timestamp=60)
    assert not verify_totp(secret, "287082", timestamp=120)
    assert not verify_totp(secret, "wrong", timestamp=59)


def test_totp_counter_consumption_is_durable_secret_bound_and_transactional():
    from datetime import datetime
    from sqlalchemy.orm import sessionmaker
    from studio_api.db import Base
    from studio_api.models import User, UserTotpFactor
    from studio_api.account_security import consume_totp_code, matched_totp_counter, _totp

    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert matched_totp_counter(secret, _totp(secret, 0), timestamp=0) == 0
    with factory() as db:
        user = User(email="synthetic-totp@example.test")
        db.add(user); db.flush()
        factor = UserTotpFactor(user_id=user.id, secret_ciphertext=b"synthetic", secret_nonce=b"nonce",
                                key_id="synthetic", confirmed_at=datetime(2026, 10, 24))
        db.add(factor); db.commit()
        user_id = user.id
        assert consume_totp_code(db, factor=factor, secret=secret, code="287082", timestamp=59)
        db.rollback()
        assert consume_totp_code(db, factor=factor, secret=secret, code="287082", timestamp=59)
        db.commit()
    with factory() as db:
        factor = db.get(UserTotpFactor, user_id)
        assert not consume_totp_code(db, factor=factor, secret=secret, code="287082", timestamp=60)
        assert consume_totp_code(db, factor=factor, secret=secret, code=_totp(secret, 2), timestamp=60)
        db.commit()
        assert not consume_totp_code(db, factor=factor, secret=secret, code=_totp(secret, 1), timestamp=60)
        db.rollback()
        stale = type("Snapshot", (), {"user_id": user_id, "secret_nonce": b"previous-secret"})()
        assert not consume_totp_code(db, factor=stale, secret=secret, code=_totp(secret, 3), timestamp=90)
    engine.dispose()


def test_totp_replay_migration_preserves_enrolled_factor_and_adds_nullable_counter(monkeypatch):
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    script = ScriptDirectory.from_config(Config(str(ROOT / "apps/studio-api/alembic.ini")))
    revision = script.get_revision("0042_totp_replay")
    assert revision.down_revision == "0041_source_retention_default"
    assert revision.module.release_safety == "additive"
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE user_totp_factors (user_id TEXT PRIMARY KEY, secret_nonce BLOB NOT NULL)"))
        connection.execute(sa.text("INSERT INTO user_totp_factors VALUES ('synthetic', :nonce)"), {"nonce": b"preserved"})
        monkeypatch.setattr(revision.module, "op", Operations(MigrationContext.configure(connection)))
        revision.module.upgrade()
        revision.module.upgrade()
        row = connection.execute(sa.text("SELECT secret_nonce, last_used_counter FROM user_totp_factors")).one()
        assert row == (b"preserved", None)
        revision.module.downgrade()
        assert connection.execute(sa.text("SELECT secret_nonce FROM user_totp_factors")).scalar_one() == b"preserved"
    engine.dispose()


def test_totp_enrollment_material_is_standard_and_qr_is_local_data():
    from studio_api.account_security import totp_qr_data_uri, totp_uri

    uri = totp_uri(
        secret="JBSWY3DPEHPK3PXP",
        email="owner+studio@example.com",
    )
    assert uri.startswith("otpauth://totp/VoiceOps%20Studio%3Aowner%2Bstudio%40example.com?")
    assert "secret=JBSWY3DPEHPK3PXP" in uri
    assert "issuer=VoiceOps%20Studio" in uri
    assert "algorithm=SHA1&digits=6&period=30" in uri

    data_uri = totp_qr_data_uri(uri)
    assert data_uri.startswith("data:image/svg+xml;base64,")
    svg = base64.b64decode(data_uri.split(",", 1)[1])
    assert svg.startswith(b"<?xml")
    assert b"<svg" in svg
    assert uri.encode() not in svg


def test_recovery_codes_are_one_time_shapes_and_hash_normalized():
    from studio_api.account_security import (
        RECOVERY_CODE_COUNT,
        generate_recovery_codes,
        recovery_code_hash,
    )

    codes = generate_recovery_codes()
    assert len(codes) == RECOVERY_CODE_COUNT
    assert len(set(codes)) == RECOVERY_CODE_COUNT
    assert all(re.fullmatch(r"[0-9A-F]{8}-[0-9A-F]{8}", code) for code in codes)
    first = codes[0]
    assert recovery_code_hash(first) == recovery_code_hash(first.lower().replace("-", " - "))
    assert first not in recovery_code_hash(first)


def test_personal_security_migration_is_one_additive_successor():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(ROOT / "apps/studio-api/alembic.ini")))
    revision = script.get_revision("0034_personal_security")
    assert script.get_heads() == ["0044_quality_progress"]
    assert revision.down_revision == "0033_observability_alerts_audit"
    assert revision.module.release_safety == "additive"


def test_personal_security_migration_accepts_current_metadata_clean_install(monkeypatch):
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    engine = sa.create_engine("sqlite://")
    script = ScriptDirectory.from_config(Config(str(ROOT / "apps/studio-api/alembic.ini")))
    migration = script.get_revision("0034_personal_security").module
    metadata = sa.MetaData()
    sa.Table(
        "sessions",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(migration.SESSION_COLUMN, sa.DateTime(timezone=True)),
    )
    sa.Table(
        "transcription_jobs",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(migration.TRANSCRIPTION_JOB_COLUMN, sa.Boolean(), nullable=False),
    )
    for table, columns in migration.TABLE_COLUMNS.items():
        sa.Table(
            table,
            metadata,
            *(sa.Column(column, sa.String()) for column in sorted(columns)),
        )
    metadata.create_all(engine)

    def unexpected_operation(*_args, **_kwargs):
        raise AssertionError("clean metadata schema must not be recreated by 0034")

    with engine.connect() as connection:
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        monkeypatch.setattr(migration.op, "add_column", unexpected_operation)
        monkeypatch.setattr(migration.op, "create_table", unexpected_operation)
        monkeypatch.setattr(migration.op, "create_index", unexpected_operation)
        migration.upgrade()
