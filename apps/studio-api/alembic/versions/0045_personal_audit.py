"""Preserve selected source content versions; no historical version backfill."""
from alembic import op
import sqlalchemy as sa

revision = "0045_personal_audit"
down_revision = "0044_quality_progress"
branch_labels = None
depends_on = None
release_safety = "additive"


def upgrade():
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
