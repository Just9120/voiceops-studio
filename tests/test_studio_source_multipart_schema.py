from __future__ import annotations

import sys
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


def test_source_multipart_migration_is_additive_direct_successor():
    scripts = ScriptDirectory.from_config(
        Config(str(ROOT / "apps/studio-api/alembic.ini"))
    )
    assert scripts.get_heads() == ["0043_yandex_disk"]
    revision = scripts.get_revision("0032_source_multipart_authority")
    assert revision is not None
    assert revision.down_revision == "0031_provider_account_snapshots"
    assert revision.module.release_safety == "additive"
    source = (
        ROOT
        / "apps/studio-api/alembic/versions/0032_source_multipart_authority.py"
    ).read_text(encoding="utf-8")
    assert "partial source multipart authority schema" in source
    assert "ck_sources_multipart_authority" in source


def test_source_multipart_model_defaults_legacy_rows_and_fences_partial_authority(
    monkeypatch,
):
    monkeypatch.setenv("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    from studio_api.db import Base
    from studio_api.models import Project, Source, SourceType, User

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        columns = {column["name"]: column for column in inspect(engine).get_columns("sources")}
        assert columns["upload_protocol"]["nullable"] is False
        with Session(engine) as db:
            user = User(email="multipart-schema@example.com")
            db.add(user)
            db.flush()
            project = Project(owner_user_id=user.id, title="Multipart schema")
            db.add(project)
            db.flush()
            legacy = Source(
                project_id=project.id,
                source_type=SourceType.local_upload,
                original_filename="legacy.mp3",
            )
            db.add(legacy)
            db.flush()
            assert legacy.upload_protocol == "single_put"
            invalid = Source(
                project_id=project.id,
                source_type=SourceType.local_upload,
                original_filename="invalid.mp3",
                upload_protocol="multipart",
                multipart_upload_id="upload-id",
                multipart_part_size_bytes=1024,
                multipart_part_count=1,
            )
            db.add(invalid)
            with pytest.raises(IntegrityError):
                db.flush()
    finally:
        engine.dispose()
