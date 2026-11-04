"""Real additive source-version migration, historical nulls and rollback guard."""
import sys
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest
import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
from studio_api.models import Base


def test_source_version_migration_preserves_legacy_identity_and_guards_rollback():
    config = Config("apps/studio-api/alembic.ini")
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("0045_personal_audit")
    assert scripts.get_heads() == [revision.revision]
    assert revision.down_revision == "0044_quality_progress"
    assert revision.module.release_safety == "additive"
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        for column in ("drive_revision_id", "drive_md5_checksum"):
            connection.execute(sa.text(f"ALTER TABLE sources DROP COLUMN {column}"))
        for table in ("transcription_jobs", "audio_preparation_jobs"):
            connection.execute(sa.text(f"ALTER TABLE {table} DROP COLUMN source_access_started_at"))
        connection.execute(sa.text("""INSERT INTO sources
            (id,project_id,source_type,original_filename,drive_file_id,upload_status,created_at,updated_at)
            VALUES ('legacy','p','google_drive','call.mp3','same-file','uploaded',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"""))
        previous = revision.module.op
        revision.module.op = Operations(MigrationContext.configure(connection))
        try:
            revision.module.upgrade()
            for table in ("transcription_jobs", "audio_preparation_jobs"):
                column = next(c for c in sa.inspect(connection).get_columns(table) if c["name"] == "source_access_started_at")
                assert column["nullable"] and column["default"] is None
            assert connection.execute(sa.text("SELECT drive_file_id,drive_revision_id,drive_md5_checksum FROM sources")).one() == ("same-file", None, None)
            connection.execute(sa.text("UPDATE sources SET drive_revision_id='v1' WHERE id='legacy'"))
            with pytest.raises(RuntimeError, match="forward recovery"):
                revision.module.downgrade()
            assert connection.execute(sa.text("SELECT drive_revision_id FROM sources")).scalar_one() == "v1"
            connection.execute(sa.text("UPDATE sources SET drive_revision_id=NULL"))
            revision.module.downgrade()
            assert not {"drive_revision_id", "drive_md5_checksum"} & {c["name"] for c in sa.inspect(connection).get_columns("sources")}
            revision.module.upgrade()
        finally:
            revision.module.op = previous
    engine.dispose()
