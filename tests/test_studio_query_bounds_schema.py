from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


EXPECTED_INDEXES = {
    "projects": {
        "ix_projects_owner_active_updated_id": (
            "owner_user_id",
            "archived_at",
            "updated_at",
            "id",
        ),
    },
    "sources": {
        "ix_sources_project_deleted_created_id": (
            "project_id",
            "deleted_at",
            "created_at",
            "id",
        ),
    },
    "transcription_jobs": {
        "ix_transcription_jobs_project_owner_created_id": (
            "project_id",
            "owner_user_id",
            "created_at",
            "id",
        ),
    },
    "audit_events": {
        "ix_audit_events_subject_created_id": (
            "subject_user_id",
            "created_at",
            "id",
        ),
    },
    "transcription_provider_part_checkpoints": {
        "ix_provider_part_checkpoints_expiry_id": ("expires_at", "id"),
    },
    "realtime_transcript_drafts": {
        "ix_realtime_drafts_expiry_id": ("expires_at", "id"),
    },
    "audio_preparation_jobs": {
        "ix_audio_preparation_jobs_owner_project_created_id": (
            "owner_user_id",
            "project_id",
            "created_at",
            "id",
        ),
    },
}


def test_query_bounds_migration_is_single_additive_successor():
    script = ScriptDirectory.from_config(
        Config(str(ROOT / "apps/studio-api/alembic.ini"))
    )
    assert script.get_heads() == ["0043_yandex_disk"]
    revision = script.get_revision("0027_query_bounds")
    assert revision.down_revision == "0026_runtime_component_status"
    source = (
        ROOT / "apps/studio-api/alembic/versions/0027_query_bounds.py"
    ).read_text(encoding="utf-8")
    assert 'release_safety = "additive"' in source
    assert "inspect(op.get_bind())" in source
    assert 'if name not in existing:' in source
    assert 'if name in existing:' in source


def test_query_bounds_indexes_match_model_query_order():
    from studio_api.db import Base
    import studio_api.models  # noqa: F401

    for table_name, expected in EXPECTED_INDEXES.items():
        table = Base.metadata.tables[table_name]
        actual = {
            index.name: tuple(column.name for column in index.columns)
            for index in table.indexes
        }
        assert actual.items() >= expected.items()


def test_query_bounds_migration_skips_indexes_created_by_fresh_metadata(monkeypatch):
    migration_path = (
        ROOT / "apps/studio-api/alembic/versions/0027_query_bounds.py"
    )
    spec = importlib.util.spec_from_file_location("query_bounds_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    first_name, first_table, _columns = migration.INDEXES[0]

    class FakeInspector:
        def get_indexes(self, table):
            return [{"name": first_name}] if table == first_table else []

    class FakeOp:
        def __init__(self):
            self.created = []

        @staticmethod
        def get_bind():
            return object()

        def create_index(self, name, table, columns, *, unique):
            self.created.append((name, table, tuple(columns), unique))

    fake_op = FakeOp()
    monkeypatch.setattr(migration, "op", fake_op)
    monkeypatch.setattr(migration, "inspect", lambda _bind: FakeInspector())

    migration.upgrade()

    assert first_name not in {row[0] for row in fake_op.created}
    assert {row[0] for row in fake_op.created} == {
        name for name, _table, _columns in migration.INDEXES[1:]
    }
