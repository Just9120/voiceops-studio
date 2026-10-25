from __future__ import annotations

import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


def test_observability_alert_migration_is_additive_direct_successor():
    scripts = ScriptDirectory.from_config(
        Config(str(ROOT / "apps/studio-api/alembic.ini"))
    )
    assert scripts.get_heads() == ["0043_yandex_disk"]
    revision = scripts.get_revision("0033_observability_alerts_audit")
    assert revision is not None
    assert revision.down_revision == "0032_source_multipart_authority"
    assert revision.module.release_safety == "additive"
    source = (
        ROOT
        / "apps/studio-api/alembic/versions/0033_observability_alerts_audit.py"
    ).read_text(encoding="utf-8")
    assert "BEFORE UPDATE OR DELETE ON audit_events" in source
    assert "audit_events is append-only" in source
    assert "operational_incidents" in source
    assert "operational_alert_deliveries" in source


def test_observability_models_expose_trace_outcome_and_durable_incidents(monkeypatch):
    monkeypatch.setenv("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    from studio_api.db import Base
    import studio_api.models  # noqa: F401

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        tables = set(inspect(engine).get_table_names())
        assert {"operational_incidents", "operational_alert_deliveries"} <= tables
        for table in ("transcription_jobs", "audio_preparation_jobs", "diagnostic_events"):
            assert "trace_id" in {
                column["name"] for column in inspect(engine).get_columns(table)
            }
        assert {"outcome", "trace_id"} <= {
            column["name"] for column in inspect(engine).get_columns("audit_events")
        }
    finally:
        engine.dispose()
