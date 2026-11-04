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
        connection.execute(sa.text("ALTER TABLE realtime_transcript_drafts DROP COLUMN cleared_at"))
        for name in ("output_sha256_checksum", "output_md5_checksum", "output_timeline_json", "recipe_version", "retained_frames_json"):
            connection.execute(sa.text(f"ALTER TABLE audio_preparation_jobs DROP COLUMN {name}"))
        connection.execute(sa.text("""INSERT INTO sources
            (id,project_id,source_type,original_filename,drive_file_id,upload_status,created_at,updated_at)
            VALUES ('legacy','p','google_drive','call.mp3','same-file','uploaded',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"""))
        previous = revision.module.op
        revision.module.op = Operations(MigrationContext.configure(connection))
        try:
            revision.module.upgrade()
            audio_columns = {column["name"]: column for column in sa.inspect(connection).get_columns("audio_preparation_jobs")}
            for name in ("output_sha256_checksum", "output_md5_checksum", "output_timeline_json", "recipe_version", "retained_frames_json"):
                assert audio_columns[name]["nullable"] and audio_columns[name]["default"] is None
            assert next(c for c in sa.inspect(connection).get_columns("realtime_transcript_drafts") if c["name"] == "cleared_at")["nullable"]
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


@pytest.mark.parametrize("field,value", [
    ("output_sha256_checksum", "a" * 64), ("output_md5_checksum", "b" * 32),
    ("output_timeline_json", '{"version":1,"original_duration_us":1000000,"retained":[[0,1000000]]}'),
    ("recipe_version", 2), ("retained_frames_json", '{"version":1}'),
])
def test_migration_downgrade_cannot_discard_prepared_audio_receipts(field, value):
    revision = ScriptDirectory.from_config(Config("apps/studio-api/alembic.ini")).get_revision("0045_personal_audit")
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        connection.execute(Base.metadata.tables["users"].insert().values(id="u", email="receipt@example.test"))
        connection.execute(Base.metadata.tables["projects"].insert().values(id="p", owner_user_id="u", title="Synthetic"))
        table = Base.metadata.tables["audio_preparation_jobs"]
        connection.execute(table.insert().values(id="receipt", project_id="p", owner_user_id="u", title="Synthetic",
            options_json="{}", **{field: value}))
        previous = revision.module.op
        revision.module.op = Operations(MigrationContext.configure(connection))
        try:
            with pytest.raises(RuntimeError, match="receipts require forward recovery"):
                revision.module.downgrade()
            assert connection.execute(sa.select(table.c[field])).scalar_one() == value
        finally:
            revision.module.op = previous
    engine.dispose()
