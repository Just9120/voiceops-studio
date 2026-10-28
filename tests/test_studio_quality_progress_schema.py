"""Real additive migration and conservative rollback of progress/provider state."""
import os
import sys
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
import pytest

API = Path(__file__).resolve().parents[1] / "apps/studio-api"
sys.path.insert(0, str(API))
os.environ.setdefault("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
from studio_api.db import Base
from studio_api import models  # noqa: F401


def test_quality_progress_upgrade_old_schema_and_repeat_are_additive():
    scripts = ScriptDirectory.from_config(Config(str(API / "alembic.ini")))
    revision = scripts.get_revision("0044_quality_progress")
    assert scripts.get_heads() == [revision.revision]
    assert revision.down_revision == "0043_yandex_disk"
    assert revision.module.release_safety == "additive"
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        original = revision.module.op
        revision.module.op = Operations(MigrationContext.configure(connection))
        try:
            # Establish the actual old layout, not merely current Base metadata.
            revision.module.downgrade()
            assert "work_progress_json" not in {c["name"] for c in inspect(connection).get_columns("transcription_jobs")}
            connection.execute(models.User.__table__.insert().values(id="owner", email="synthetic@example.test"))
            revision.module.upgrade()
            revision.module.upgrade()
            for provider in ("mistral", "gemini", "tbank"):
                connection.execute(models.SttProviderHealth.__table__.insert().values(provider=provider, operating_mode="standard", consecutive_failures=2))
            assert connection.scalar(text("SELECT COUNT(*) FROM stt_provider_health")) == 3
            assert connection.scalar(text("SELECT COUNT(*) FROM users WHERE id='owner'")) == 1
            inspector = inspect(connection)
            for table in ("audio_preparation_jobs", "transcription_jobs"):
                assert "work_progress_json" in {c["name"] for c in inspector.get_columns(table)}
            assert {"external_file_id", "external_file_deleted_at", "external_file_credential_version_id"} <= {c["name"] for c in inspector.get_columns("stt_provider_operations")}
            assert any("external_file_credential_version_id" in fk["constrained_columns"] for fk in inspector.get_foreign_keys("stt_provider_operations"))
            connection.execute(models.ProviderCredential.__table__.insert().values(id="new", user_id="owner", provider="gemini", label="Synthetic"))
            with pytest.raises(RuntimeError, match="forward recovery"):
                revision.module.downgrade()
            assert connection.scalar(text("SELECT COUNT(*) FROM provider_credentials WHERE id='new'")) == 1
        finally:
            revision.module.op = original
