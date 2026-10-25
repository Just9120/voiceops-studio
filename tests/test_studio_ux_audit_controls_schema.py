from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text


ROOT = Path(__file__).resolve().parents[1]
STUDIO_API = ROOT / "apps" / "studio-api"
if str(STUDIO_API) not in sys.path:
    sys.path.insert(0, str(STUDIO_API))
os.environ.setdefault("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")

from studio_api.db import Base  # noqa: E402
from studio_api.models import TranscriptionJob  # noqa: E402


def _revision():
    script = ScriptDirectory.from_config(Config(str(STUDIO_API / "alembic.ini")))
    return script, script.get_revision("0037_ux_audit_controls")


def _run_upgrade(revision, connection) -> None:
    original_op = revision.module.op
    revision.module.op = Operations(MigrationContext.configure(connection))
    try:
        revision.module.upgrade()
    finally:
        revision.module.op = original_op


def test_ux_audit_controls_migration_is_additive_single_head():
    script, revision = _revision()

    assert script.get_heads() == ["0043_yandex_disk"]
    assert revision.down_revision == "0036_stt_multiprovider"
    assert revision.module.release_safety == "additive"
    assert {
        "history_attention_resolved_at",
        "history_attention_resolution",
        "history_attention_linked_job_id",
    } <= set(TranscriptionJob.__table__.c.keys())


def test_ux_audit_controls_migration_upgrades_previous_boundary():
    _, revision = _revision()
    engine = create_engine("sqlite+pysqlite:///:memory:")

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE transcription_jobs (id VARCHAR(36) PRIMARY KEY)"))
        _run_upgrade(revision, connection)

        assert {
            "history_attention_resolved_at",
            "history_attention_resolution",
            "history_attention_linked_job_id",
        } <= {
            column["name"]
            for column in inspect(connection).get_columns("transcription_jobs")
        }


def test_ux_audit_controls_migration_accepts_fresh_metadata_and_rejects_partial_boundary():
    _, revision = _revision()
    fresh = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(fresh)
    with fresh.begin() as connection:
        _run_upgrade(revision, connection)

    partial = create_engine("sqlite+pysqlite:///:memory:")
    with partial.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE transcription_jobs ("
                "id VARCHAR(36) PRIMARY KEY, history_attention_resolution VARCHAR(40))"
            )
        )
        with pytest.raises(RuntimeError, match="partial job attention resolution schema"):
            _run_upgrade(revision, connection)
