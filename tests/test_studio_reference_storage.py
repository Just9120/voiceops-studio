from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


def isolated_settings(**overrides):
    values = {
        "source_s3_endpoint_url": "https://storage.test",
        "source_s3_region": "auto",
        "source_s3_bucket": "transcription-private",
        "source_s3_access_key_id_file": "/run/secrets/transcription-id",
        "source_s3_secret_access_key_file": "/run/secrets/transcription-secret",
        "source_s3_lifecycle_rule_id": "transcription-reference-retention",
        "audio_reference_s3_endpoint_url": "https://storage.test",
        "audio_reference_s3_region": "auto",
        "audio_reference_s3_bucket": "audio-private",
        "audio_reference_s3_access_key_id_file": "/run/secrets/audio-id",
        "audio_reference_s3_secret_access_key_file": "/run/secrets/audio-secret",
        "audio_reference_s3_lifecycle_rule_id": "audio-reference-retention",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_reference_storage_selects_exact_boundary_without_fallback():
    from studio_api.source_storage import (
        AUDIO_PROCESSING_REFERENCE_CLASS,
        TRANSCRIPTION_REFERENCE_CLASS,
        SourceStorageError,
        reference_storage_settings,
    )

    settings = isolated_settings()
    transcription = reference_storage_settings(
        settings, TRANSCRIPTION_REFERENCE_CLASS
    )
    audio = reference_storage_settings(settings, AUDIO_PROCESSING_REFERENCE_CLASS)

    assert transcription.source_s3_bucket == "transcription-private"
    assert transcription.source_s3_access_key_id_file.endswith("transcription-id")
    assert audio.source_s3_bucket == "audio-private"
    assert audio.source_s3_access_key_id_file.endswith("audio-id")

    missing_audio = isolated_settings(audio_reference_s3_bucket=None)
    assert (
        reference_storage_settings(
            missing_audio, AUDIO_PROCESSING_REFERENCE_CLASS
        ).source_s3_bucket
        is None
    )
    with pytest.raises(SourceStorageError):
        reference_storage_settings(settings, "unknown")


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_s3_bucket": None},
        {"audio_reference_s3_bucket": None},
        {"audio_reference_s3_bucket": "transcription-private"},
        {
            "audio_reference_s3_access_key_id_file": "/run/secrets/transcription-id"
        },
        {
            "audio_reference_s3_secret_access_key_file": "/run/secrets/transcription-secret"
        },
        {"source_s3_lifecycle_rule_id": None},
        {"audio_reference_s3_lifecycle_rule_id": None},
        {
            "audio_reference_s3_lifecycle_rule_id": "transcription-reference-retention"
        },
    ],
)
def test_reference_storage_isolation_fails_closed(overrides):
    from studio_api.source_storage import reference_storage_isolation_configured

    assert reference_storage_isolation_configured(isolated_settings()) is True
    assert (
        reference_storage_isolation_configured(isolated_settings(**overrides))
        is False
    )


def test_reference_class_schema_defaults_legacy_rows_and_rejects_unknown_values(
    monkeypatch,
):
    monkeypatch.setenv("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    from studio_api.db import Base
    from studio_api.models import Project, Source, SourceType, User

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        columns = {column["name"]: column for column in inspect(engine).get_columns("sources")}
        assert columns["reference_class"]["nullable"] is False
        with Session(engine) as db:
            user = User(email="storage-schema@example.com")
            db.add(user)
            db.flush()
            project = Project(owner_user_id=user.id, title="Storage schema")
            db.add(project)
            db.flush()
            legacy = Source(
                project_id=project.id,
                source_type=SourceType.local_upload,
                original_filename="legacy.mp3",
                mime_type="audio/mpeg",
                size_bytes=10,
            )
            db.add(legacy)
            db.flush()
            assert legacy.reference_class == "transcription"
            invalid = Source(
                project_id=project.id,
                source_type=SourceType.local_upload,
                original_filename="invalid.mp3",
                mime_type="audio/mpeg",
                size_bytes=10,
                reference_class="unknown",
            )
            db.add(invalid)
            with pytest.raises(IntegrityError):
                db.flush()
    finally:
        engine.dispose()


def test_reference_class_migration_is_additive_repository_head():
    scripts = ScriptDirectory.from_config(
        Config(str(ROOT / "apps/studio-api/alembic.ini"))
    )
    assert scripts.get_heads() == ["0044_quality_progress"]
    revision = scripts.get_revision("0029_source_reference_class")
    assert revision.down_revision == "0028_transcript_maintenance_runs"
    assert revision.module.release_safety == "additive"
    source = (
        ROOT
        / "apps/studio-api/alembic/versions/0029_source_reference_class.py"
    ).read_text(encoding="utf-8")
    assert "server_default=sa.text(\"'transcription'\")" in source
    assert "audio_processing" in source
    assert "create_index" in source


def test_s3_storage_multipart_and_verified_delete_are_bounded():
    from botocore.exceptions import ClientError
    from studio_api.source_storage import S3SourceStorage

    class Client:
        def __init__(self):
            self.list_calls = []
            self.completed = None
            self.deleted = []

        def list_parts(self, **kwargs):
            self.list_calls.append(kwargs)
            if kwargs["PartNumberMarker"] == 0:
                return {
                    "Parts": [{"PartNumber": 1, "ETag": '"one"', "Size": 8}],
                    "IsTruncated": True,
                    "NextPartNumberMarker": 1,
                }
            return {
                "Parts": [{"PartNumber": 2, "ETag": '"two"', "Size": 3}],
                "IsTruncated": False,
            }

        def complete_multipart_upload(self, **kwargs):
            self.completed = kwargs

        def delete_object(self, **kwargs):
            self.deleted.append(kwargs)

        def get_bucket_versioning(self, **kwargs):
            return {}

        def head_object(self, **kwargs):
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
                "HeadObject",
            )

    storage = object.__new__(S3SourceStorage)
    storage.bucket = "private"
    storage.client = Client()
    parts = storage.list_multipart_parts("owner/key", "upload-id")
    assert [(part.part_number, part.size_bytes) for part in parts] == [(1, 8), (2, 3)]
    assert [call["PartNumberMarker"] for call in storage.client.list_calls] == [0, 1]
    storage.complete_multipart_upload("owner/key", "upload-id", parts)
    assert storage.client.completed["MultipartUpload"] == {
        "Parts": [
            {"PartNumber": 1, "ETag": '"one"'},
            {"PartNumber": 2, "ETag": '"two"'},
        ]
    }
    assert storage.delete_object_verified("owner/key", bucket="private") is True
    assert storage.client.deleted == [{"Bucket": "private", "Key": "owner/key"}]


def test_s3_inventory_requires_typed_owner_scoped_metadata():
    from studio_api.source_storage import S3SourceStorage

    modified = datetime(2026, 9, 1, tzinfo=timezone.utc)

    class Client:
        def list_objects_v2(self, **kwargs):
            assert kwargs == {
                "Bucket": "private",
                "Prefix": "transcription/users/owner/",
                "MaxKeys": 25,
            }
            return {
                "Contents": [
                    {
                        "Key": "transcription/users/owner/file",
                        "Size": 7,
                        "ETag": '"etag"',
                        "LastModified": modified,
                    }
                ],
                "IsTruncated": False,
            }

    storage = object.__new__(S3SourceStorage)
    storage.bucket = "private"
    storage.client = Client()
    page = storage.list_objects_page(
        "transcription/users/owner/",
        max_keys=25,
    )
    assert page.next_token is None
    assert [(item.key, item.size_bytes, item.last_modified) for item in page.objects] == [
        ("transcription/users/owner/file", 7, modified)
    ]


@pytest.mark.parametrize("status", ["Enabled", "Suspended"])
def test_verified_deletion_removes_all_exact_key_versions_and_markers(status):
    from botocore.exceptions import ClientError
    from studio_api.source_storage import S3SourceStorage

    class Client:
        def __init__(self):
            self.calls = []
            self.remaining = True

        def get_bucket_versioning(self, **kwargs):
            return {"Status": status}

        def delete_object(self, **kwargs):
            self.calls.append(kwargs)

        def list_object_versions(self, **kwargs):
            assert kwargs["Bucket"] == "private"
            assert kwargs["Prefix"] == "owner/key"
            if not self.remaining:
                return {"IsTruncated": False}
            if "KeyMarker" not in kwargs:
                return {"Versions": [{"Key": "owner/key", "VersionId": "old"}],
                        "IsTruncated": True, "NextKeyMarker": "owner/key", "NextVersionIdMarker": "old"}
            return {"DeleteMarkers": [{"Key": "owner/key", "VersionId": "marker"}],
                    "Versions": [{"Key": "owner/key-other", "VersionId": "neighbor"}], "IsTruncated": False}

        def delete_objects(self, **kwargs):
            self.calls.append(kwargs)
            self.remaining = False
            return {}

        def head_object(self, **kwargs):
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "HeadObject")

    storage = object.__new__(S3SourceStorage)
    storage.bucket, storage.client = "private", Client()
    assert storage.delete_object_verified("owner/key") is True
    assert storage.client.calls == [
        {"Bucket": "private", "Key": "owner/key"},
        {"Bucket": "private", "Delete": {"Objects": [
            {"Key": "owner/key", "VersionId": "old"},
            {"Key": "owner/key", "VersionId": "marker"}], "Quiet": True}},
    ]


@pytest.mark.parametrize("mode", ["unknown", "denied", "repeated_cursor", "partial_delete", "new_version"])
def test_version_cleanup_never_reports_success_for_unconfirmed_storage(mode):
    from botocore.exceptions import ClientError
    from studio_api.source_storage import S3SourceStorage, SourceStorageError

    class Client:
        def get_bucket_versioning(self, **kwargs):
            if mode == "denied":
                raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetBucketVersioning")
            return {"Status": "invalid" if mode == "unknown" else "Enabled"}

        def delete_object(self, **kwargs):
            pass

        def list_object_versions(self, **kwargs):
            return {"Versions": [{"Key": "owner/key", "VersionId": "old"}],
                    "IsTruncated": mode == "repeated_cursor", "NextKeyMarker": "owner/key", "NextVersionIdMarker": "old"}

        def delete_objects(self, **kwargs):
            return {"Errors": [{"Code": "AccessDenied"}]} if mode == "partial_delete" else {}

    storage = object.__new__(S3SourceStorage)
    storage.bucket, storage.client = "private", Client()
    if mode == "new_version":
        assert storage.delete_object_verified("owner/key") is False
    else:
        with pytest.raises((SourceStorageError, ClientError)):
            storage.delete_object_verified("owner/key")


def test_documented_r2_endpoint_does_not_call_unsupported_versioning():
    from botocore.exceptions import ClientError
    from studio_api.source_storage import S3SourceStorage

    class Client:
        def delete_object(self, **kwargs):
            pass

        def head_object(self, **kwargs):
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

    storage = object.__new__(S3SourceStorage)
    storage.settings = SimpleNamespace(source_s3_endpoint_url="https://synthetic.r2.cloudflarestorage.com")
    storage.bucket, storage.client = "private", Client()
    assert storage.delete_object_verified("owner/key") is True
