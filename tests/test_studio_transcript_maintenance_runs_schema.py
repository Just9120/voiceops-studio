from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[1]


def test_transcript_maintenance_runs_is_additive_repository_head():
    config = Config(str(ROOT / "apps/studio-api/alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["0044_quality_progress"]
    revision = scripts.get_revision("0028_transcript_maintenance_runs")
    assert revision.down_revision == "0027_query_bounds"
    source = (
        ROOT
        / "apps/studio-api/alembic/versions/0028_transcript_maintenance_runs.py"
    ).read_text(encoding="utf-8")
    assert 'release_safety = "additive"' in source
    assert "transcript_maintenance_runs" in source
