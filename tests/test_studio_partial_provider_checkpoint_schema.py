from pathlib import Path
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


def test_partial_provider_checkpoint_model_is_encrypted_bounded_and_scoped():
    from studio_api.models import (
        TranscriptionJobSourceAttempt,
        TranscriptionProviderPartCheckpoint,
    )

    table = TranscriptionProviderPartCheckpoint.__table__
    assert {
        "owner_user_id",
        "project_id",
        "job_id",
        "job_source_id",
        "part_index",
        "total_parts",
        "timeline_offset_seconds",
        "duration_seconds",
        "ciphertext",
        "nonce",
        "key_id",
        "payload_hmac",
        "expires_at",
    } <= set(table.c.keys())
    assert "plaintext" not in set(table.c.keys())
    assert "transcript" not in set(table.c.keys())
    assert "provider_failure_code" in TranscriptionJobSourceAttempt.__table__.c
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("job_source_id", "part_index") in unique_columns
    assert {index.name for index in table.indexes} >= {
        "ix_provider_part_checkpoints_expiry",
        "ix_provider_part_checkpoints_job",
        "ix_provider_part_checkpoints_job_source",
    }


def test_partial_provider_checkpoint_migration_has_one_direct_additive_successor():
    config = Config("apps/studio-api/alembic.ini")
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision("0020_provider_part_checkpoints")
    successor = script.get_revision("0021_source_creation_favorites")
    assert revision.down_revision == "0019_job_media_clip"
    assert successor.down_revision == "0020_provider_part_checkpoints"
    assert script.get_current_head() == "0043_yandex_disk"

    migration = (
        ROOT
        / "apps/studio-api/alembic/versions/0020_provider_part_checkpoints.py"
    ).read_text(encoding="utf-8")
    assert 'release_safety = "additive"' in migration
    successor_migration = (
        ROOT
        / "apps/studio-api/alembic/versions/0021_source_creation_and_folder_favorites.py"
    ).read_text(encoding="utf-8")
    assert 'release_safety = "additive"' in successor_migration
