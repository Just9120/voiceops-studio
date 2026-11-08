"""Check the additive revision column and its legacy rollback boundary."""
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest
import sqlalchemy as sa


def test_model_revision_upgrade_keeps_legacy_devices_and_protects_downgrade():
    scripts = ScriptDirectory.from_config(Config("apps/studio-api/alembic.ini"))
    revision = scripts.get_revision("0046_local_model_revision")
    assert revision.down_revision == "0045_personal_audit"
    assert revision.module.release_safety == "additive"
    engine = sa.create_engine("sqlite://")
    with engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE local_execution_devices (id INTEGER PRIMARY KEY, model VARCHAR(80))")
        db.execute(sa.text("INSERT INTO local_execution_devices VALUES (1, :model)"),
                   {"model": "NVIDIA-Nemotron-3.5-Transcribe-30B-A4B"})
        with Operations.context(MigrationContext.configure(db)):
            revision.module.upgrade()
            assert db.exec_driver_sql("SELECT id, model_revision FROM local_execution_devices").all() == [(1, None)]
            update = sa.text("UPDATE local_execution_devices SET model_revision = :revision WHERE id = 1")
            db.execute(update, {"revision": "a" * 40})
            with pytest.raises(RuntimeError, match="newer model revisions"):
                revision.module.downgrade()
            db.execute(update, {"revision": "dbd06c5cad7a2f33c8e06be2fb3ef814dbd9aa59"})
            revision.module.downgrade()
            assert {column["name"] for column in sa.inspect(db).get_columns("local_execution_devices")} == {"id", "model"}
            assert db.exec_driver_sql("SELECT id FROM local_execution_devices").scalar_one() == 1


@pytest.mark.parametrize("definition", ["VARCHAR(40)", "VARCHAR(24)", "VARCHAR(40) NOT NULL"])
def test_model_revision_upgrade_handles_a_precreated_column(definition):
    scripts = ScriptDirectory.from_config(Config("apps/studio-api/alembic.ini"))
    revision = scripts.get_revision("0046_local_model_revision")
    engine = sa.create_engine("sqlite://")
    with engine.begin() as db:
        db.exec_driver_sql(f"CREATE TABLE local_execution_devices (id INTEGER PRIMARY KEY, model_revision {definition})")
        db.execute(sa.text("INSERT INTO local_execution_devices VALUES (1, :revision)"), {"revision": "legacy"})
        with Operations.context(MigrationContext.configure(db)):
            if definition == "VARCHAR(40)":
                revision.module.upgrade()
                assert db.exec_driver_sql("SELECT model_revision FROM local_execution_devices").scalar_one() == "legacy"
            else:
                with pytest.raises(RuntimeError, match="incompatible definition"):
                    revision.module.upgrade()
