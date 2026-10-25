from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect


ROOT = Path(__file__).resolve().parents[1]
STUDIO_API = ROOT / "apps" / "studio-api"
if str(STUDIO_API) not in sys.path:
    sys.path.insert(0, str(STUDIO_API))
os.environ.setdefault("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")

from studio_api.db import Base  # noqa: E402
from studio_api.models import CredentialProvider, TranscriptionJob  # noqa: E402


def test_stt_multiprovider_migration_is_additive_single_head():
    script = ScriptDirectory.from_config(
        Config(str(STUDIO_API / "alembic.ini"))
    )
    revision = script.get_revision("0036_stt_multiprovider")

    assert script.get_heads() == ["0043_yandex_disk"]
    assert revision.down_revision == "0035_job_notifications"
    assert revision.module.release_safety == "additive"
    assert CredentialProvider.yandex.value == "yandex"
    assert "operating_mode" in TranscriptionJob.__table__.c


def test_stt_multiprovider_migration_accepts_fresh_metadata_schema():
    script = ScriptDirectory.from_config(
        Config(str(STUDIO_API / "alembic.ini"))
    )
    revision = script.get_revision("0036_stt_multiprovider")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with engine.begin() as connection:
        original_op = revision.module.op
        revision.module.op = Operations(MigrationContext.configure(connection))
        try:
            revision.module.upgrade()
        finally:
            revision.module.op = original_op

        inspector = inspect(connection)
        assert {
            "stt_dictionaries",
            "stt_dictionary_entries",
            "stt_provider_operations",
            "stt_provider_health",
        } <= set(inspector.get_table_names())
        assert "config_json" in {
            column["name"]
            for column in inspector.get_columns("provider_credentials")
        }
        assert "operating_mode" in {
            column["name"]
            for column in inspector.get_columns("transcription_jobs")
        }
