"""Preserve selected source content versions; no historical version backfill."""
from alembic import op
import sqlalchemy as sa

revision = "0045_personal_audit"
down_revision = "0044_quality_progress"
branch_labels = None
depends_on = None
release_safety = "additive"


def upgrade():
    audio_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("audio_preparation_jobs")}
    for column in (sa.Column("output_sha256_checksum", sa.String(64), nullable=True),
                   sa.Column("output_md5_checksum", sa.String(32), nullable=True),
                   sa.Column("output_timeline_json", sa.Text(), nullable=True),
                   sa.Column("recipe_version", sa.Integer(), nullable=True),
                   sa.Column("retained_frames_json", sa.Text(), nullable=True),
                   sa.Column("output_drive_receipt_json", sa.Text(), nullable=True)):
        if column.name not in audio_columns:
            op.add_column("audio_preparation_jobs", column)
    if "cleared_at" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("realtime_transcript_drafts")}:
        op.add_column("realtime_transcript_drafts", sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True))
    for table in ("transcription_jobs", "audio_preparation_jobs"):
        if "source_access_started_at" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}:
            op.add_column(table, sa.Column("source_access_started_at", sa.DateTime(timezone=True), nullable=True))
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("sources")}
    for column in (
        sa.Column("drive_revision_id", sa.String(256), nullable=True),
        sa.Column("drive_md5_checksum", sa.String(32), nullable=True),
    ):
        if column.name not in columns:
            op.add_column("sources", column)
    with op.batch_alter_table("transcript_catalog_entries") as batch:
        batch.alter_column("source_identity_value", existing_type=sa.String(256), type_=sa.String(1024), existing_nullable=True)


def downgrade():
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM audio_preparation_jobs WHERE "
            "output_sha256_checksum IS NOT NULL OR output_md5_checksum IS NOT NULL OR output_timeline_json IS NOT NULL "
            "OR recipe_version IS NOT NULL OR retained_frames_json IS NOT NULL OR output_drive_receipt_json IS NOT NULL")).scalar():
        raise RuntimeError("Prepared audio timeline/content receipts require forward recovery")
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM realtime_transcript_drafts WHERE cleared_at IS NOT NULL")).scalar():
        raise RuntimeError("Cleared Live session fences require forward recovery")
    for table in ("transcription_jobs", "audio_preparation_jobs"):
        if op.get_bind().execute(sa.text(f"SELECT COUNT(*) FROM {table} WHERE source_access_started_at IS NOT NULL")).scalar():
            raise RuntimeError("Active-source admission records require forward recovery")
    if op.get_bind().execute(sa.text(
        "SELECT COUNT(*) FROM sources WHERE drive_revision_id IS NOT NULL OR drive_md5_checksum IS NOT NULL"
    )).scalar():
        raise RuntimeError("Selected source versions require forward recovery; do not discard their identity")
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM transcript_catalog_entries WHERE length(source_identity_value) > 256")).scalar():
        raise RuntimeError("Versioned catalog identities require forward recovery")
    with op.batch_alter_table("transcript_catalog_entries") as batch:
        batch.alter_column("source_identity_value", existing_type=sa.String(1024), type_=sa.String(256), existing_nullable=True)
    op.drop_column("sources", "drive_md5_checksum")
    op.drop_column("sources", "drive_revision_id")
    for table in ("transcription_jobs", "audio_preparation_jobs"):
        op.drop_column(table, "source_access_started_at")
    op.drop_column("realtime_transcript_drafts", "cleared_at")
    for column in ("output_sha256_checksum", "output_md5_checksum", "output_timeline_json", "recipe_version", "retained_frames_json", "output_drive_receipt_json"):
        op.drop_column("audio_preparation_jobs", column)
