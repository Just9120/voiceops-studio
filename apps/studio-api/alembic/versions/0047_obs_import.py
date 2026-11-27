"""Add scoped OBS import bindings and idempotent draft receipts."""
from alembic import op
import sqlalchemy as sa

revision = "0047_obs_import"
down_revision = "0046_local_model_revision"
branch_labels = None
depends_on = None
release_safety = "additive"


def upgrade():
    # Revision 0001 can create current tables during a fresh bootstrap.
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "obs_import_bindings" not in tables:
        op.create_table(
            "obs_import_bindings",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("label", sa.String(80), nullable=False),
            sa.Column("verifier_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True)),
        )
        op.create_index("ix_obs_import_bindings_owner_user_id", "obs_import_bindings", ["owner_user_id"])
    if "obs_import_drafts" not in tables:
        op.create_table(
            "obs_import_drafts",
            sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("event_id", sa.String(32), primary_key=True),
            sa.Column("source_id", sa.String(36), sa.ForeignKey("sources.id", ondelete="SET NULL"), unique=True),
            sa.Column("content_md5", sa.String(24), nullable=False),
            sa.Column("content_sha256", sa.String(64), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
        )


def downgrade():
    for name in ("obs_import_bindings", "obs_import_drafts"):
        if op.get_bind().execute(sa.select(1).select_from(sa.table(name)).limit(1)).first():
            raise RuntimeError("OBS import data requires backup before reverting this migration")
    op.drop_table("obs_import_drafts")
    op.drop_table("obs_import_bindings")
