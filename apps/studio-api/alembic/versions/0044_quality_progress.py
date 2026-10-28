"""Add bounded work progress and independent provider credential kinds."""
from alembic import op
import sqlalchemy as sa

revision = "0044_quality_progress"
down_revision = "0043_yandex_disk"
branch_labels = None
depends_on = None
release_safety = "additive"


def upgrade():
    bind = op.get_bind()
    for table in ("transcription_jobs", "audio_preparation_jobs"):
        if "work_progress_json" not in {c["name"] for c in sa.inspect(bind).get_columns(table)}:
            op.add_column(table, sa.Column("work_progress_json", sa.Text(), nullable=True))
    if bind.dialect.name == "postgresql":
        for value in ("tbank", "mistral", "gemini"):
            op.execute(sa.text(f"ALTER TYPE credentialprovider ADD VALUE IF NOT EXISTS '{value}'"))


def downgrade():
    bind = op.get_bind()
    # Existing credentials must remain readable; PostgreSQL enum labels are
    # additive and intentionally retained. Rollback never deletes credentials.
    for table in ("transcription_jobs", "audio_preparation_jobs"):
        if "work_progress_json" in {c["name"] for c in sa.inspect(bind).get_columns(table)}:
            op.drop_column(table, "work_progress_json")
