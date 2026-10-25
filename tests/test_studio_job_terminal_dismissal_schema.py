from pathlib import Path
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))
ALEMBIC = ROOT / "apps/studio-api" / "alembic.ini"


def test_job_model_exposes_durable_terminal_dismissal(monkeypatch):
    monkeypatch.setenv("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    from studio_api.config import get_settings

    get_settings.cache_clear()
    from studio_api.models import TranscriptionJob

    assert "terminal_dismissed_at" in TranscriptionJob.__table__.columns


def test_terminal_dismissal_is_part_of_unreleased_progress_migration():
    script = ScriptDirectory.from_config(Config(str(ALEMBIC)))

    assert script.get_heads() == ["0043_yandex_disk"]
    revision = script.get_revision("0018_job_part_progress")
    assert revision is not None
    assert revision.down_revision == "0017_google_maintenance_oauth"
    module_text = Path(revision.module.__file__).read_text(encoding="utf-8")
    assert 'release_safety = "additive"' in module_text
    assert "SET terminal_dismissed_at = COALESCE" in module_text
    assert "status IN ('completed', 'failed', 'cancelled')" in module_text
