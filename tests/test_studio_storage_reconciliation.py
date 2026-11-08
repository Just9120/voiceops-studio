from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


@pytest.fixture
def sqlite_db(monkeypatch):
    monkeypatch.setenv("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    from studio_api.config import get_settings

    get_settings.cache_clear()
    from studio_api.db import Base
    import studio_api.models  # noqa: F401

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _settings(**overrides):
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
        "source_upload_ttl_seconds": 3600,
        "source_multipart_threshold_bytes": 16 * 1024 * 1024,
        "source_multipart_part_size_bytes": 8 * 1024 * 1024,
        "storage_orphan_min_age_seconds": 24 * 60 * 60,
        "storage_reconciliation_scan_limit": 100,
        "storage_reconciliation_page_size": 20,
        "storage_reconciliation_plan_ttl_seconds": 600,
        "storage_reconciliation_apply_limit": 20,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class InventoryStorage:
    def __init__(self, bucket, objects):
        self.bucket = bucket
        self.objects = {item.key: item for item in objects}
        self.deleted = []

    def list_objects_page(self, prefix, *, continuation_token=None, start_after=None, max_keys=100):
        from studio_api.source_storage import StoredObjectPage

        rows = sorted(
            (item for item in self.objects.values() if item.key.startswith(prefix) and item.key > (start_after or "")),
            key=lambda item: item.key,
        )
        start = int(continuation_token or "0")
        page = tuple(rows[start : start + max_keys])
        next_index = start + len(page)
        return StoredObjectPage(
            page,
            str(next_index) if next_index < len(rows) else None,
        )

    def head_object(self, key):
        from studio_api.source_storage import ObjectHead

        item = self.objects[key]
        return ObjectHead(
            item.size_bytes,
            "application/octet-stream",
            item.etag,
            item.last_modified,
        )

    def delete_object_verified(self, key, *, bucket=None):
        assert bucket == self.bucket
        self.deleted.append(key)
        self.objects.pop(key, None)
        return key not in self.objects


def _owner(db):
    from studio_api import models as m

    user = m.User(email="reconciliation@example.com")
    db.add(user)
    db.flush()
    project = m.Project(owner_user_id=user.id, title="Storage")
    db.add(project)
    db.flush()
    return m, user, project


def _inventory(owner_id, now):
    from studio_api.source_storage import StoredObject

    old = now - timedelta(days=3)
    recent = now - timedelta(hours=1)
    return {
        "transcription-private": InventoryStorage(
            "transcription-private",
            [
                StoredObject(
                    f"transcription/users/{owner_id}/known/source",
                    10,
                    '"known"',
                    old,
                ),
                StoredObject(
                    f"transcription/users/{owner_id}/orphan/source",
                    20,
                    '"orphan"',
                    old,
                ),
                StoredObject(
                    f"transcription/users/{owner_id}/recent/source",
                    30,
                    '"recent"',
                    recent,
                ),
            ],
        ),
        "audio-private": InventoryStorage(
            "audio-private",
            [
                StoredObject(
                    f"audio_processing/users/{owner_id}/orphan/source",
                    40,
                    '"audio"',
                    old,
                )
            ],
        ),
    }


def test_owner_reconciliation_is_dry_run_first_and_deletes_only_exact_plan(sqlite_db):
    from studio_api import models as m
    from studio_api.storage_reconciliation import (
        apply_reconciliation_plan,
        issue_reconciliation_plan,
        scan_owner_storage,
    )

    _, user, project = _owner(sqlite_db)
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    storages = _inventory(user.id, now)
    known_key = f"transcription/users/{user.id}/known/source"
    sqlite_db.add(
        m.Source(
            project_id=project.id,
            source_type=m.SourceType.local_upload,
            original_filename="known.mp3",
            reference_class="transcription",
            s3_bucket="transcription-private",
            s3_object_key=known_key,
        )
    )
    sqlite_db.commit()
    factory = lambda selected: storages[selected.source_s3_bucket]

    scan = scan_owner_storage(
        sqlite_db,
        owner_user_id=user.id,
        settings=_settings(),
        now=now,
        storage_factory=factory,
    )
    assert scan.scanned_count == 4
    assert scan.protected_recent_count == 1
    assert len(scan.candidates) == 2
    assert scan.candidate_bytes == 60
    assert all(not storage.deleted for storage in storages.values())
    token, expires_at = issue_reconciliation_plan(
        owner_user_id=user.id,
        scan=scan,
        secret="session-secret",
        now=now,
        ttl_seconds=600,
    )
    assert token and expires_at == now + timedelta(minutes=10)
    assert "orphan" not in token and known_key not in token

    result = apply_reconciliation_plan(
        sqlite_db,
        owner_user_id=user.id,
        plan_token=token,
        secret="session-secret",
        settings=_settings(),
        now=now,
        storage_factory=factory,
    )
    assert result.planned_count == 2
    assert result.deleted_count == 2
    assert result.failed_count == 0
    assert result.deleted_bytes == 60
    assert known_key in storages["transcription-private"].objects
    assert f"transcription/users/{user.id}/recent/source" in storages["transcription-private"].objects


def test_reconciliation_rejects_changed_or_truncated_plan_without_deletion(sqlite_db):
    from studio_api.source_storage import StoredObject
    from studio_api.storage_reconciliation import (
        StorageReconciliationError,
        StorageReconciliationReason,
        apply_reconciliation_plan,
        issue_reconciliation_plan,
        scan_owner_storage,
    )

    _, user, _ = _owner(sqlite_db)
    sqlite_db.commit()
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    storages = _inventory(user.id, now)
    factory = lambda selected: storages[selected.source_s3_bucket]
    settings = _settings()
    scan = scan_owner_storage(
        sqlite_db,
        owner_user_id=user.id,
        settings=settings,
        now=now,
        storage_factory=factory,
    )
    token, _ = issue_reconciliation_plan(
        owner_user_id=user.id,
        scan=scan,
        secret="session-secret",
        now=now,
        ttl_seconds=600,
    )
    assert token
    changed_key = f"transcription/users/{user.id}/orphan/source"
    previous = storages["transcription-private"].objects[changed_key]
    storages["transcription-private"].objects[changed_key] = StoredObject(
        previous.key,
        previous.size_bytes,
        '"changed"',
        previous.last_modified,
    )
    with pytest.raises(StorageReconciliationError) as changed:
        apply_reconciliation_plan(
            sqlite_db,
            owner_user_id=user.id,
            plan_token=token,
            secret="session-secret",
            settings=settings,
            now=now,
            storage_factory=factory,
        )
    assert changed.value.reason == StorageReconciliationReason.plan_changed
    assert all(not storage.deleted for storage in storages.values())

    truncated = scan_owner_storage(
        sqlite_db,
        owner_user_id=user.id,
        settings=_settings(storage_reconciliation_scan_limit=1),
        now=now,
        storage_factory=factory,
    )
    assert truncated.truncated is True
    assert issue_reconciliation_plan(
        owner_user_id=user.id,
        scan=truncated,
        secret="session-secret",
        now=now,
        ttl_seconds=600,
    ) == (None, None)


def test_lifecycle_payload_is_user_facing_and_contains_no_storage_identity(sqlite_db):
    from studio_api.storage_reconciliation import storage_lifecycle_payload

    _, user, _ = _owner(sqlite_db)
    user.source_retention_ttl_seconds = 3 * 24 * 60 * 60
    payload = storage_lifecycle_payload(user, _settings())
    assert payload["reconciliation"] == {
        "available": True,
        "dry_run_default": True,
        "apply_requires_confirmation": True,
        "minimum_orphan_age_seconds": 86400,
        "scan_limit": 100,
        "apply_limit": 20,
    }
    assert {item["effective_retention_seconds"] for item in payload["classes"]} == {
        259200
    }
    serialized = repr(payload).lower()
    assert "bucket" not in serialized
    assert "access_key" not in serialized
    assert "object_key" not in serialized


def test_storage_scan_stops_a_repeated_provider_cursor(sqlite_db):
    from studio_api.source_storage import StoredObjectPage
    from studio_api.storage_reconciliation import scan_owner_storage, StorageReconciliationError
    _, user, _ = _owner(sqlite_db)
    sqlite_db.commit()
    calls = []
    class LoopingStorage:
        def list_objects_page(self, prefix, **kwargs):
            calls.append(kwargs)
            return StoredObjectPage((), "unchanged-cursor")
    with pytest.raises(StorageReconciliationError, match="unavailable"):
        scan_owner_storage(sqlite_db, owner_user_id=user.id, settings=_settings(), now=datetime.now(timezone.utc), storage_factory=lambda _: LoopingStorage())
    assert len(calls) == 2


def test_empty_pages_with_fresh_cursors_exhaust_the_request_budget(sqlite_db):
    from studio_api.source_storage import StoredObjectPage
    from studio_api.storage_reconciliation import (
        StorageReconciliationError,
        apply_reconciliation_plan,
    )

    _, user, _ = _owner(sqlite_db)
    sqlite_db.commit()
    calls = []

    class EmptyPagesStorage:
        def list_objects_page(self, prefix, **kwargs):
            calls.append(prefix)
            return StoredObjectPage((), str(len(calls)))

    with pytest.raises(StorageReconciliationError, match="scan_truncated"):
        apply_reconciliation_plan(
            sqlite_db,
            owner_user_id=user.id,
            settings=_settings(storage_reconciliation_scan_limit=1, storage_reconciliation_apply_limit=1),
            now=datetime.now(timezone.utc),
            secret="test-secret",
            plan_token="not-used-for-truncated-scan",
            storage_factory=lambda _: EmptyPagesStorage(),
        )
    assert len(calls) == 4


@pytest.mark.parametrize("reference_appears_during_head", [False, True])
def test_reconciliation_protects_a_physical_key_referenced_by_another_owner_and_class(
    sqlite_db, monkeypatch, reference_appears_during_head,
):
    from studio_api.storage_reconciliation import scan_owner_storage

    m, owner, _ = _owner(sqlite_db)
    other = m.User(email="other-owner@example.com")
    sqlite_db.add(other)
    sqlite_db.flush()
    project = m.Project(owner_user_id=other.id, title="Other storage")
    sqlite_db.add(project)
    sqlite_db.flush()
    key = f"transcription/users/{owner.id}/orphan/source"
    sqlite_db.commit()
    now = datetime.now(timezone.utc)
    storages = _inventory(owner.id, now)

    def publish_reference():
        sqlite_db.add(m.Source(
            project_id=project.id,
            source_type=m.SourceType.local_upload,
            original_filename="known.mp3",
            reference_class="audio_processing",
            s3_bucket="transcription-private",
            s3_object_key=key,
        ))
        sqlite_db.commit()

    storage = storages["transcription-private"]
    if reference_appears_during_head:
        original_head = storage.head_object

        def head_and_publish(object_key):
            head = original_head(object_key)
            if object_key == key:
                publish_reference()
            return head

        monkeypatch.setattr(storage, "head_object", head_and_publish)
    else:
        publish_reference()

    settings = _settings()
    factory = lambda selected: storages[selected.source_s3_bucket]
    scan = scan_owner_storage(
        sqlite_db,
        owner_user_id=owner.id,
        settings=settings,
        now=now,
        storage_factory=factory,
    )
    candidates = {item.object.key for item in scan.candidates}
    assert (key in candidates) == reference_appears_during_head
    if reference_appears_during_head:
        from studio_api.storage_reconciliation import apply_reconciliation_plan, issue_reconciliation_plan

        token, _ = issue_reconciliation_plan(
            owner_user_id=owner.id, scan=scan, secret="test-secret", now=now, ttl_seconds=600,
        )
        assert token
        result = apply_reconciliation_plan(
            sqlite_db, owner_user_id=owner.id, plan_token=token, secret="test-secret",
            settings=settings, now=now, storage_factory=factory,
        )
        assert result.failed_count == 1
        assert key in storage.objects
        assert key not in storage.deleted


def test_storage_scan_looks_up_only_each_page_and_protects_pending_deletions(sqlite_db):
    from sqlalchemy import event
    from studio_api.storage_reconciliation import scan_owner_storage
    m, user, project = _owner(sqlite_db)
    known_key = f"transcription/users/{user.id}/known/source"
    sqlite_db.add(m.Source(project_id=project.id, source_type=m.SourceType.local_upload, original_filename="known.mp3", reference_class="transcription",
                          s3_bucket="transcription-private", s3_object_key=known_key, deleted_at=datetime.now(timezone.utc)))
    # The owner can have a large history, unrelated to this small provider page.
    sqlite_db.add_all([m.Source(project_id=project.id, source_type=m.SourceType.local_upload, original_filename="synthetic.mp3", reference_class="transcription",
                               s3_bucket="transcription-private", s3_object_key=f"transcription/users/{user.id}/outside/{index}") for index in range(1001)])
    sqlite_db.commit()
    queries = []
    plans = []
    def capture(connection, _cursor, statement, parameters, _context, _many):
        if statement.startswith("SELECT sources.s3_object_key"):
            queries.append((statement, parameters))
            plans.extend(row[3] for row in connection.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, parameters))
    engine = sqlite_db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    now = datetime.now(timezone.utc)
    storages = _inventory(user.id, now)
    try:
        scan = scan_owner_storage(sqlite_db, owner_user_id=user.id, settings=_settings(storage_reconciliation_page_size=2), now=now,
                                  storage_factory=lambda selected: storages[selected.source_s3_bucket])
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert known_key not in [item.object.key for item in scan.candidates]
    assert len(scan.candidates) == 2
    assert queries
    assert all("sources.s3_object_key IN" in statement and len(parameters) <= 10 for statement, parameters in queries)
    assert not any("SCAN sources" in plan for plan in plans)
    assert any("ix_sources_storage_identity" in plan for plan in plans)


def test_automatic_sweep_advances_across_deleted_pages_and_buckets(sqlite_db):
    from studio_api.source_storage import StoredObject
    from studio_api.storage_reconciliation import AutomaticStorageReconciliation

    m, user, project = _owner(sqlite_db)
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=3)
    prefix = f"transcription/users/{user.id}/projects/{project.id}/sources/"
    first, second, protected, recent = [f"{prefix}00000000-0000-4000-8000-{i:012d}/source" for i in range(4)]
    audio_key = first.replace("transcription/", "audio_processing/")
    unknown = prefix + "unrecognized/source"
    sqlite_db.add(m.Source(
        project_id=project.id, source_type=m.SourceType.local_upload, original_filename="pending.mp3",
        reference_class="transcription", s3_bucket="transcription-private", s3_object_key=protected,
    ))
    sqlite_db.commit()
    storages = {
        "transcription-private": InventoryStorage("transcription-private", [
            StoredObject(key, 10, '"etag"', old) for key in (first, second, protected, unknown)
        ] + [StoredObject(recent, 10, '"etag"', now - timedelta(hours=47))]),
        "audio-private": InventoryStorage("audio-private", [StoredObject(audio_key, 10, '"etag"', old)]),
    }
    r2 = "https://synthetic.r2.cloudflarestorage.com"
    settings = _settings(
        source_s3_endpoint_url=r2, audio_reference_s3_endpoint_url=r2,
        storage_reconciliation_page_size=1,
    )
    sweep = AutomaticStorageReconciliation()
    for _ in range(10):
        sweep.run_page(
            sqlite_db, settings=settings, now=now, should_stop=lambda: False,
            storage_factory=lambda selected: storages[selected.source_s3_bucket],
        )
    assert storages["transcription-private"].deleted == [first, second]
    assert storages["audio-private"].deleted == [audio_key]
    assert sweep.markers == {}


@pytest.mark.parametrize("fault", ["generic_endpoint", "foreign_page", "changed_head", "reference_during_head", "stop"])
def test_automatic_sweep_refuses_unsafe_deletion(sqlite_db, monkeypatch, fault):
    from studio_api.source_storage import ObjectHead, StoredObject
    from studio_api.storage_reconciliation import AutomaticStorageReconciliation, StorageReconciliationError

    m, user, project = _owner(sqlite_db)
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=3)
    key = f"transcription/users/{user.id}/projects/{project.id}/sources/00000000-0000-4000-8000-000000000001/source"
    storage = InventoryStorage("transcription-private", [StoredObject(key, 10, '"etag"', old)])
    r2 = "https://synthetic.r2.cloudflarestorage.com"
    settings = _settings(source_s3_endpoint_url=r2, audio_reference_s3_endpoint_url=r2)
    if fault == "generic_endpoint":
        settings.source_s3_endpoint_url = "https://other-storage.test"
    if fault == "foreign_page":
        from studio_api.source_storage import StoredObjectPage

        monkeypatch.setattr(storage, "list_objects_page", lambda *a, **kw: StoredObjectPage(
            (StoredObject("unrelated/object", 10, '"etag"', old),), None,
        ))
    stopped = False

    def head(_):
        nonlocal stopped
        if fault == "reference_during_head":
            sqlite_db.add(m.Source(
                project_id=project.id, source_type=m.SourceType.local_upload,
                original_filename="linked.mp3", reference_class="transcription",
                s3_bucket="transcription-private", s3_object_key=key,
            ))
            sqlite_db.commit()
        stopped = fault == "stop"
        return ObjectHead(10, None, '"changed"' if fault == "changed_head" else '"etag"', old)

    sqlite_db.commit()
    monkeypatch.setattr(storage, "head_object", head)
    sweep = AutomaticStorageReconciliation()

    def run_page():
        return sweep.run_page(
            sqlite_db, settings=settings, now=now, should_stop=lambda: stopped,
            storage_factory=lambda _: storage,
        )

    if fault in {"generic_endpoint", "foreign_page"}:
        with pytest.raises(StorageReconciliationError, match="unavailable"):
            run_page()
    else:
        assert run_page() == (0, 0)
    assert not storage.deleted
