from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


@pytest.fixture
def catalog_model(monkeypatch, tmp_path):
    password_file = tmp_path / "studio_test_pg_password"
    master_key_file = tmp_path / "studio_test_master_key"
    password_file.write_text(
        os.environ.get(
            "STUDIO_TEST_POSTGRES_PASSWORD",
            "studio_test_password",
        ),
        encoding="utf-8",
    )
    master_key_file.write_text(
        base64.b64encode(b"1" * 32).decode(),
        encoding="utf-8",
    )
    monkeypatch.setenv("STUDIO_DATABASE_SCHEME", "postgresql+psycopg")
    monkeypatch.setenv("STUDIO_DATABASE_HOST", "127.0.0.1")
    monkeypatch.setenv("STUDIO_DATABASE_PORT", "5432")
    monkeypatch.setenv("STUDIO_DATABASE_NAME", "studio_test")
    monkeypatch.setenv("STUDIO_DATABASE_USER", "studio_test")
    monkeypatch.setenv(
        "STUDIO_POSTGRES_PASSWORD_FILE",
        str(password_file),
    )
    monkeypatch.setenv(
        "STUDIO_CREDENTIAL_MASTER_KEY_FILE",
        str(master_key_file),
    )
    from studio_api.models import (
        TranscriptCatalogDocumentStandardStatus,
        TranscriptCatalogEntry,
        TranscriptCatalogSettingsStatus,
        TranscriptCatalogSourceIdentityKind,
    )

    return {
        "entry": TranscriptCatalogEntry,
        "standard_status": TranscriptCatalogDocumentStandardStatus,
        "settings_status": TranscriptCatalogSettingsStatus,
        "source_kind": TranscriptCatalogSourceIdentityKind,
    }


def test_transcript_catalog_model_is_owner_scoped_and_fail_closed(
    catalog_model,
):
    table = catalog_model["entry"].__table__

    assert set(table.c) >= {
        table.c.id,
        table.c.owner_user_id,
        table.c.document_id,
        table.c.document_name,
        table.c.transcript_standard,
        table.c.standard_status,
        table.c.settings_status,
        table.c.provider,
        table.c.model,
        table.c.language_mode,
        table.c.diarization_enabled,
        table.c.source_identity_kind,
        table.c.source_identity_value,
        table.c.imported_at,
        table.c.updated_at,
    }
    constraints = {constraint.name for constraint in table.constraints}
    assert {
        "ck_transcript_catalog_document_id_nonempty",
        "ck_transcript_catalog_document_name_nonempty",
        "ck_transcript_catalog_standard_nonempty",
        "ck_transcript_catalog_source_authority",
        "ck_transcript_catalog_settings_authority",
        "uq_transcript_catalog_owner_document",
    } <= constraints
    indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in table.indexes
    }
    assert indexes["ix_transcript_catalog_owner_updated"] == (
        "owner_user_id",
        "updated_at",
    )
    assert indexes["ix_transcript_catalog_owner_source_settings"] == (
        "owner_user_id",
        "source_identity_kind",
        "source_identity_value",
        "provider",
        "model",
        "language_mode",
        "diarization_enabled",
    )


def test_transcript_catalog_model_enums_match_migration_contract(
    catalog_model,
):
    assert {
        value.value for value in catalog_model["standard_status"]
    } == {"current", "outdated", "unstructured", "unreadable"}
    assert {
        value.value for value in catalog_model["settings_status"]
    } == {"exact", "indeterminate"}
    assert {
        value.value for value in catalog_model["source_kind"]
    } == {"google_drive_file", "studio_source"}


def test_transcript_catalog_migration_remains_in_the_single_head_chain():
    config = Config(str(ROOT / "apps/studio-api/alembic.ini"))
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == ["0044_quality_progress"]
    assert script.get_current_head() == "0044_quality_progress"
    revision = script.get_revision("0016_transcript_catalog_entries")
    assert revision.down_revision == "0015_user_source_retention"
