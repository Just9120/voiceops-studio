from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


def test_audio_diagnostics_migration_accepts_initial_metadata_bootstrap(monkeypatch):
    monkeypatch.setenv("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    cfg = Config(str(ROOT / "apps/studio-api/alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "apps/studio-api/alembic"))
    scripts = ScriptDirectory.from_config(cfg)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        with Operations.context(MigrationContext.configure(connection)):
            # The actual first migration creates tables from current ORM metadata.
            scripts.get_revision("0001_platform_core").module.upgrade()
            revision = scripts.get_revision("0039_audio_diagnostics")
            revision.module.upgrade()
            revision.module.upgrade()
            fks = inspect(connection).get_foreign_keys("diagnostic_events")
            assert any(fk["name"] == revision.module.FOREIGN_KEY
                       and fk["constrained_columns"] == [revision.module.COLUMN]
                       and fk["referred_table"] == "audio_preparation_jobs"
                       and fk["referred_columns"] == ["id"] for fk in fks)
            # An incomplete bootstrap must still fail rather than bypass safety checks.
            connection.execute(text(f"DROP INDEX {revision.module.INDEX}"))
            with pytest.raises(RuntimeError, match="partial audio-diagnostic schema"):
                revision.module.upgrade()
    engine.dispose()


def test_additive_audio_diagnostics_migration_preserves_legacy_events(monkeypatch):
    monkeypatch.setenv("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    from studio_api.db import Base
    from studio_api import models as m
    cfg = Config(str(ROOT / "apps/studio-api/alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "apps/studio-api/alembic"))
    scripts = ScriptDirectory.from_config(cfg)
    revision = scripts.get_revision("0039_audio_diagnostics")
    assert scripts.get_heads() == ["0044_quality_progress"]
    assert revision.down_revision == "0038_trusted_devices"
    assert revision.module.release_safety == "additive"
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        # Build the real historical diagnostics table, not the new ORM shape.
        Base.metadata.create_all(connection, tables=[table for table in Base.metadata.sorted_tables if table.name != "diagnostic_events"])
        with Operations.context(MigrationContext.configure(connection)):
            scripts.get_revision("0010_diagnostic_events").module.upgrade()
            scripts.get_revision("0033_observability_alerts_audit").module._add_trace_column(connection, "diagnostic_events")
        connection.commit()
        with Session(connection) as db:
            user = m.User(email="migration@example.test")
            db.add(user); db.flush()
            project = m.Project(owner_user_id=user.id, title="Synthetic")
            db.add(project); db.flush()
            transcript = m.TranscriptionJob(owner_user_id=user.id, project_id=project.id)
            audio = m.AudioPreparationJob(owner_user_id=user.id, project_id=project.id,
                title="Synthetic", options_json="{}")
            db.add_all([transcript, audio]); db.commit()
            owner_id, project_id, transcript_id, audio_id = user.id, project.id, transcript.id, audio.id
        now = datetime.now(timezone.utc)
        params = dict(owner=owner_id, project=project_id, job=transcript_id, now=now)
        connection.execute(text("""INSERT INTO diagnostic_events
            (id,owner_user_id,project_id,job_id,level,component,event_code,metadata_json,
             first_occurred_at,last_occurred_at,occurrence_count,dedup_fingerprint,dedup_bucket,expires_at)
            VALUES ('legacy',:owner,:project,:job,'INFO','worker','JOB_CLAIMED','{}',
                    :now,:now,1,'legacy',:now,:now)"""), params)
        connection.commit()
        with Operations.context(MigrationContext.configure(connection)):
            revision.module.upgrade()
            revision.module.upgrade()  # idempotent readback of a complete schema
        connection.commit()
        assert connection.execute(text("SELECT job_id,audio_preparation_job_id FROM diagnostic_events WHERE id='legacy'")).one() == (transcript_id, None)
        fks = inspect(connection).get_foreign_keys("diagnostic_events")
        assert any(fk["constrained_columns"] == ["job_id"] and fk["referred_table"] == "transcription_jobs" for fk in fks)
        assert any(fk["constrained_columns"] == ["audio_preparation_job_id"] and fk["referred_table"] == "audio_preparation_jobs" for fk in fks)
        connection.execute(text("UPDATE diagnostic_events SET job_id=NULL,audio_preparation_job_id=:audio WHERE id='legacy'"), {"audio": audio_id})
        connection.commit()
        for values in ({"audio": "00000000-0000-0000-0000-000000000000", "job": None},
                       {"audio": audio_id, "job": transcript_id}):
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(text("UPDATE diagnostic_events SET job_id=:job,audio_preparation_job_id=:audio WHERE id='legacy'"), values)
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="must be preserved"):
                revision.module.downgrade()
        assert connection.execute(text("SELECT audio_preparation_job_id FROM diagnostic_events WHERE id='legacy'")).scalar() == audio_id
    engine.dispose()
