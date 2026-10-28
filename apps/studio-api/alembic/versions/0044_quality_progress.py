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
    health_checks = {c["name"]: c["sqltext"] for c in sa.inspect(bind).get_check_constraints("stt_provider_health")}
    if "mistral" not in health_checks.get("ck_stt_provider_health_provider", ""):
        with op.batch_alter_table("stt_provider_health") as batch:
            batch.drop_constraint("ck_stt_provider_health_provider", type_="check")
            batch.create_check_constraint("ck_stt_provider_health_provider", "provider IN ('elevenlabs','yandex','mistral','gemini','tbank')")
    existing = {c["name"] for c in sa.inspect(bind).get_columns("stt_provider_operations")}
    for column in (sa.Column("external_file_id", sa.String(256), nullable=True),
                   sa.Column("external_file_credential_version_id", sa.String(36), nullable=True),
                   sa.Column("external_file_deleted_at", sa.DateTime(timezone=True), nullable=True)):
        if column.name not in existing: op.add_column("stt_provider_operations", column)
    checks = {c["name"]: c["sqltext"] for c in sa.inspect(bind).get_check_constraints("stt_provider_operations")}
    if "gemini" not in checks.get("ck_stt_provider_operations_provider", ""):
        with op.batch_alter_table("stt_provider_operations") as batch:
            batch.drop_constraint("ck_stt_provider_operations_provider", type_="check")
            batch.create_check_constraint("ck_stt_provider_operations_provider", "provider IN ('yandex','gemini')")
    if "ix_stt_provider_operations_file_cleanup" not in {i["name"] for i in sa.inspect(bind).get_indexes("stt_provider_operations")}:
        op.create_index("ix_stt_provider_operations_file_cleanup", "stt_provider_operations", ["external_file_deleted_at", "updated_at"])
    if not any("external_file_credential_version_id" in fk["constrained_columns"] for fk in sa.inspect(bind).get_foreign_keys("stt_provider_operations")):
        with op.batch_alter_table("stt_provider_operations") as batch:
            batch.create_foreign_key("fk_stt_provider_file_version", "provider_credential_versions", ["external_file_credential_version_id"], ["id"])


def downgrade():
    bind = op.get_bind()
    if (bind.execute(sa.text("SELECT COUNT(*) FROM stt_provider_operations WHERE provider <> 'yandex'")).scalar()
        or bind.execute(sa.text("SELECT COUNT(*) FROM provider_credentials WHERE provider IN ('tbank','mistral','gemini')")).scalar()
        or bind.execute(sa.text("SELECT COUNT(*) FROM stt_provider_health WHERE provider IN ('tbank','mistral','gemini')")).scalar()):
        raise RuntimeError("New provider records require forward recovery; do not delete credential or usage history for rollback")
    with op.batch_alter_table("stt_provider_health") as batch:
        batch.drop_constraint("ck_stt_provider_health_provider", type_="check")
        batch.create_check_constraint("ck_stt_provider_health_provider", "provider IN ('elevenlabs','yandex')")
    op.drop_index("ix_stt_provider_operations_file_cleanup", table_name="stt_provider_operations")
    with op.batch_alter_table("stt_provider_operations") as batch:
        batch.drop_constraint("ck_stt_provider_operations_provider", type_="check")
        batch.create_check_constraint("ck_stt_provider_operations_provider", "provider IN ('yandex')")
        batch.drop_constraint("fk_stt_provider_file_version", type_="foreignkey")
        batch.drop_column("external_file_id")
        batch.drop_column("external_file_credential_version_id")
        batch.drop_column("external_file_deleted_at")
    # Existing credentials must remain readable; PostgreSQL enum labels are
    # additive and intentionally retained. Rollback never deletes credentials.
    for table in ("transcription_jobs", "audio_preparation_jobs"):
        if "work_progress_json" in {c["name"] for c in sa.inspect(bind).get_columns(table)}:
            op.drop_column(table, "work_progress_json")
