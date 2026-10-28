from pathlib import Path
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))
ALEMBIC = ROOT / "apps/studio-api" / "alembic.ini"


def test_job_model_exposes_bounded_optional_clip_range(monkeypatch):
    monkeypatch.setenv("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    from studio_api.config import get_settings

    get_settings.cache_clear()
    from studio_api.models import TranscriptionJob

    columns = set(TranscriptionJob.__table__.columns.keys())
    assert {"media_clip_start_seconds", "media_clip_end_seconds"} <= columns
    checks = {
        constraint.name
        for constraint in TranscriptionJob.__table__.constraints
        if constraint.name
    }
    assert "ck_transcription_jobs_media_clip_range" in checks


def test_job_media_clip_migration_is_additive_single_head():
    script = ScriptDirectory.from_config(Config(str(ALEMBIC)))

    assert script.get_heads() == ["0044_quality_progress"]
    revision = script.get_revision("0019_job_media_clip")
    assert revision is not None
    assert revision.down_revision == "0018_job_part_progress"
    module_text = Path(revision.module.__file__).read_text(encoding="utf-8")
    assert 'release_safety = "additive"' in module_text
