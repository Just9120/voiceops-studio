"""Owner-bound Yandex Disk credentials, selected resource handles and destinations."""
from alembic import op
import sqlalchemy as sa

revision = "0043_yandex_disk"
down_revision = "0042_totp_replay"
branch_labels = None
depends_on = None
release_safety = "additive"


def creation_authority_constraint(bind, *, include_yandex):
    allowed = "'google_drive_created_time', 'embedded_media_metadata'"
    if include_yandex:
        allowed += ", 'yandex_disk_created_time'"
    checks = {item["name"]: item["sqltext"] for item in sa.inspect(bind).get_check_constraints("sources")}
    existing = checks.get("ck_sources_creation_authority")
    if existing and ("yandex_disk_created_time" in existing) == include_yandex:
        return
    with op.batch_alter_table("sources") as batch:
        if existing:
            batch.drop_constraint("ck_sources_creation_authority", type_="check")
        batch.create_check_constraint("ck_sources_creation_authority",
            "((source_created_at IS NULL AND source_created_at_provenance IS NULL) OR "
            "(source_created_at IS NOT NULL AND source_created_at_provenance IN (" + allowed + ")))" )


def upgrade():
    bind=op.get_bind()
    if bind.dialect.name=="postgresql":
        op.execute("ALTER TYPE sourcetype ADD VALUE IF NOT EXISTS 'yandex_disk'")
    creation_authority_constraint(bind, include_yandex=True)
    tables=set(sa.inspect(bind).get_table_names())
    if "yandex_disk_connections" not in tables:
        op.create_table("yandex_disk_connections",
            sa.Column("user_id",sa.String(36),sa.ForeignKey("users.id"),primary_key=True),
            sa.Column("account_uid",sa.String(128),nullable=False),
            sa.Column("status",sa.String(16),nullable=False),
            sa.Column("token_ciphertext",sa.LargeBinary(),nullable=True),
            sa.Column("token_nonce",sa.LargeBinary(),nullable=True),
            sa.Column("key_id",sa.String(80),nullable=False),
            sa.Column("credential_revision",sa.Integer(),nullable=False),
            sa.Column("connected_at",sa.DateTime(timezone=True),nullable=False),
            sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False),
            sa.Column("revoked_at",sa.DateTime(timezone=True),nullable=True),
            sa.CheckConstraint("status IN ('active','revoked','error')",name="ck_yandex_disk_connection_status"))
    if "yandex_disk_resources" not in tables:
        op.create_table("yandex_disk_resources",
            sa.Column("id",sa.String(36),primary_key=True),
            sa.Column("owner_user_id",sa.String(36),sa.ForeignKey("users.id"),nullable=False),
            sa.Column("account_uid",sa.String(128),nullable=False),
            sa.Column("path",sa.Text(),nullable=False),
            sa.Column("is_folder",sa.Boolean(),nullable=False),
            sa.Column("version_fingerprint",sa.String(64),nullable=False),
            sa.Column("metadata_json",sa.Text(),nullable=False),
            sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
        op.create_index("ix_yandex_disk_resources_owner_user_id","yandex_disk_resources",["owner_user_id"])
    for table in ["projects","transcription_jobs"]:
        if "output_provider" not in {c["name"] for c in sa.inspect(bind).get_columns(table)}:
            op.add_column(table,sa.Column("output_provider",sa.String(32),nullable=False,server_default="google_drive"))


def downgrade():
    bind=op.get_bind()
    # Never discard OAuth credentials, source handles or new destinations.
    for table in ["yandex_disk_connections","yandex_disk_resources"]:
        if bind.execute(sa.text("SELECT count(*) FROM "+table)).scalar():
            raise RuntimeError("Yandex Disk data must be retired before downgrade")
    for table in ["projects","transcription_jobs"]:
        if bind.execute(sa.text("SELECT count(*) FROM "+table+" WHERE output_provider <> 'google_drive'")).scalar():
            raise RuntimeError("Yandex destinations prevent downgrade")
    if bind.execute(sa.text("SELECT count(*) FROM sources WHERE source_type = 'yandex_disk'")).scalar():
        raise RuntimeError("Yandex sources prevent downgrade")
    if bind.execute(sa.text("SELECT count(*) FROM sources WHERE source_created_at_provenance = 'yandex_disk_created_time'")).scalar():
        raise RuntimeError("Yandex source authority prevents downgrade")
    creation_authority_constraint(bind, include_yandex=False)
    for table in ["projects","transcription_jobs"]:op.drop_column(table,"output_provider")
    op.drop_table("yandex_disk_resources")
    op.drop_table("yandex_disk_connections")
    # The harmless additional PG enum label is retained; removing it would
    # require destructive type rewriting and is not part of additive rollback.
