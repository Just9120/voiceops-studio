"""Persist the companion's active revision independently of the catalog."""
from alembic import op
import sqlalchemy as sa

revision = "0046_local_model_revision"
down_revision = "0045_personal_audit"
branch_labels = None
depends_on = None
release_safety = "additive"


def upgrade():
    op.add_column("local_execution_devices", sa.Column("model_revision", sa.String(40), nullable=True))


def downgrade():
    # Legacy code infers the original revision from the model name. Discarding
    # a different recorded revision would let it present the wrong weights as ready.
    devices = sa.table("local_execution_devices", sa.column("model"), sa.column("model_revision"))
    previous = sa.or_(
        sa.and_(devices.c.model == "NVIDIA-Nemotron-3.5-Transcribe-30B-A4B",
                devices.c.model_revision == "dbd06c5cad7a2f33c8e06be2fb3ef814dbd9aa59"),
        sa.and_(devices.c.model == "parakeet-tdt-0.6b-v3.q8_0", devices.c.model_revision == "541d1f99c6b0c3cd0b11a95167540bb8edefd82b"),
    )
    if op.get_bind().execute(sa.select(1).where(
        devices.c.model_revision.is_not(None),
        ~sa.func.coalesce(previous, False),
    ).limit(1)).first():
        raise RuntimeError("Reset devices with newer model revisions before downgrading")
    op.drop_column("local_execution_devices", "model_revision")
