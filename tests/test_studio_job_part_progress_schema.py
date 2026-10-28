from pathlib import Path
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))
ALEMBIC = ROOT / "apps/studio-api" / "alembic.ini"


def test_job_part_progress_model_exposes_only_bounded_counters(monkeypatch):
    monkeypatch.setenv("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    from studio_api.config import get_settings

    get_settings.cache_clear()
    from studio_api.models import TranscriptionJobSourceAttempt

    columns = set(TranscriptionJobSourceAttempt.__table__.columns.keys())
    assert {"provider_total_parts", "provider_completed_parts"} <= columns
    checks = {
        constraint.name
        for constraint in TranscriptionJobSourceAttempt.__table__.constraints
        if constraint.name
    }
    assert {
        "ck_source_attempt_provider_total_parts_positive",
        "ck_source_attempt_provider_completed_parts_nonnegative",
        "ck_source_attempt_provider_parts_bounded",
    } <= checks


def test_job_part_progress_migration_is_additive_single_head():
    script = ScriptDirectory.from_config(Config(str(ALEMBIC)))

    assert script.get_heads() == ["0044_quality_progress"]
    revision = script.get_revision("0018_job_part_progress")
    assert revision is not None
    assert revision.down_revision == "0017_google_maintenance_oauth"
    module_text = Path(revision.module.__file__).read_text(encoding="utf-8")
    assert 'release_safety = "additive"' in module_text
