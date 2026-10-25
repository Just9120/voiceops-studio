from pathlib import Path
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))
ALEMBIC = ROOT / "apps/studio-api" / "alembic.ini"


def test_google_maintenance_grant_has_separate_encrypted_columns(
    monkeypatch,
):
    monkeypatch.setenv(
        "STUDIO_DATABASE_URL",
        "sqlite+pysqlite:///:memory:",
    )
    from studio_api.models import GoogleConnection, GoogleOAuthState

    connection_columns = set(GoogleConnection.__table__.columns.keys())
    assert {
        "maintenance_google_subject",
        "maintenance_google_email",
        "maintenance_scopes",
        "maintenance_refresh_token_ciphertext",
        "maintenance_refresh_token_nonce",
        "maintenance_key_id",
        "maintenance_connected_at",
        "maintenance_revoked_at",
    } <= connection_columns
    assert "purpose" in GoogleOAuthState.__table__.columns


def test_google_maintenance_oauth_migration_precedes_current_head():
    script = ScriptDirectory.from_config(Config(str(ALEMBIC)))

    assert script.get_heads() == ["0043_yandex_disk"]
    assert script.get_current_head() == "0043_yandex_disk"
    revision = script.get_revision("0017_google_maintenance_oauth")
    assert revision is not None
    assert revision.down_revision == "0016_transcript_catalog_entries"
