from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest

_counter = 0
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


@dataclass(frozen=True)
class SimpleSettings:
    source_s3_endpoint_url: str | None = "https://r2.test"
    source_s3_region: str = "auto"
    source_s3_bucket: str | None = "studio-temp"
    source_s3_access_key_id_file: str | None = "transcription-access"
    source_s3_secret_access_key_file: str | None = "transcription-secret"
    source_s3_lifecycle_rule_id: str | None = "transcription-retention"
    audio_reference_s3_endpoint_url: str | None = "https://r2.test"
    audio_reference_s3_region: str = "auto"
    audio_reference_s3_bucket: str | None = "studio-audio"
    audio_reference_s3_access_key_id_file: str | None = "audio-access"
    audio_reference_s3_secret_access_key_file: str | None = "audio-secret"
    audio_reference_s3_lifecycle_rule_id: str | None = "audio-retention"
    source_max_upload_bytes: int = 1000

    def source_storage_configured(self) -> bool:
        return bool(self.source_s3_endpoint_url and self.source_s3_bucket)


class FakeBody:
    def __init__(self, chunks, exc=None, before_eof=None):
        self._chunks = list(chunks)
        self.exc = exc
        self.closed = False
        self.before_eof = before_eof

    def read(self, _size=-1):
        if self.exc:
            raise self.exc
        if self._chunks:
            return self._chunks.pop(0)
        if self.before_eof:
            self.before_eof(); self.before_eof = None
        return b""

    def close(self):
        self.closed = True


class FakeStream:
    def __init__(self, body, content_type="audio/mpeg", content_length=100):
        self.body = body
        self.content_type = content_type
        self.content_length = content_length

    def iter_chunks(self, size):
        while True:
            chunk = self.body.read(size)
            if not chunk:
                break
            yield chunk

    def close(self):
        self.body.close()


class FakeStorage:
    def __init__(self, stream=None, exc=None, head_exc=None, head_content_type=None):
        self.stream = stream
        self.exc = exc
        self.head_exc = head_exc
        self.head_content_type = head_content_type

    def head_object(self, key):
        from studio_api.source_storage import ObjectHead
        if self.head_exc:
            raise self.head_exc
        length = 100 if self.exc and self.stream is None else self.stream.content_length
        ctype = "audio/mpeg" if self.exc and self.stream is None else self.stream.content_type
        return ObjectHead(size_bytes=length, content_type=self.head_content_type or ctype)

    def open_read(self, key):
        if self.exc:
            raise self.exc
        return self.stream


@pytest.fixture()
def sqlite_session(monkeypatch):
    monkeypatch.setenv("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    from studio_api.db import Base
    import studio_api.models  # noqa
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close(); Base.metadata.drop_all(engine); engine.dispose()


@pytest.fixture()
def models():
    from studio_api import models as m
    return m


def make_job(db, m, *, source_type=None, source_kwargs=None, job_kwargs=None, rel_kwargs=None, max_delta=timedelta(minutes=5)):
    global _counter
    _counter += 1
    from studio_api.security import hash_password, utcnow
    now = utcnow().replace(tzinfo=None)
    user = m.User(email=f"u-{id(db)}-{_counter}@example.com", role=m.UserRole.admin, status=m.UserStatus.active)
    db.add(user); db.flush()
    db.add(m.LocalIdentity(user_id=user.id, password_hash=hash_password("password-123")))
    project = m.Project(owner_user_id=user.id, title="Project")
    db.add(project); db.flush()
    st = source_type or m.SourceType.local_upload
    skw = dict(project_id=project.id, source_type=st, original_filename="meeting.mp3", mime_type="audio/mpeg", size_bytes=100, upload_status=m.SourceUploadStatus.uploaded, uploaded_at=now)
    if st == m.SourceType.local_upload:
        skw.update(s3_bucket="studio-temp", s3_object_key="private/key", expires_at=now + timedelta(hours=1))
    else:
        skw.update(drive_file_id="drive-1")
    skw.update(source_kwargs or {})
    src = m.Source(**skw); db.add(src); db.flush()
    jkw = dict(project_id=project.id, owner_user_id=user.id, status=m.JobStatus.processing, lease_owner_id="worker-1", lease_generation=1, claimed_at=now, lease_expires_at=now + max_delta, started_at=now)
    jkw.update(job_kwargs or {})
    job = m.TranscriptionJob(**jkw); db.add(job); db.flush()
    rkw = dict(job_id=job.id, source_id=src.id, position=0); rkw.update(rel_kwargs or {})
    rel = m.TranscriptionJobSource(**rkw); db.add(rel); db.commit()
    return job, src, rel, project, now, user


def materialize(db, job, rel, *, settings=None, storage=None, storage_factory=None, token_resolver=None, drive_fetcher=None, drive_meta=None, now=None):
    from studio_api.job_source_materialization import materialize_processing_job_source
    return materialize_processing_job_source(db, job_id=job.id, job_source_id=rel.id, lease_owner_id="worker-1", lease_generation=1, settings=settings or SimpleSettings(), now=now, storage_factory=storage_factory or (lambda _s: storage), drive_token_resolver=token_resolver or (lambda *a, **k: "token-secret"), drive_content_fetcher=drive_fetcher or (lambda *_: None), drive_metadata_fetcher=drive_meta or fake_drive_meta)


def fake_drive_meta(token, drive_file_id):
    from studio_api.google_drive import GoogleDriveMetadata
    return GoogleDriveMetadata(id=drive_file_id, name="meeting.mp3", mime_type="audio/mpeg", size_bytes=100, web_view_link=None, created_time=None, modified_time=None, is_folder=False)


@pytest.mark.parametrize("failure", [None, "changed", "cancelled"])
def test_yandex_source_is_revalidated_streamed_and_controlled(sqlite_session, models, monkeypatch, failure):
    from studio_api import job_source_materialization as materialization
    from studio_api.yandex_disk import YandexDiskError, resource_from_payload
    job, source, relation, _, now, user = make_job(sqlite_session, models,
        source_type=models.SourceType.yandex_disk)
    resource = resource_from_payload({"type": "file", "path": "disk:/meeting.mp3",
        "name": "meeting.mp3", "size": 100, "mime_type": "audio/mpeg"})
    reads, checks = [], []
    ticks = iter(range(100))
    monkeypatch.setattr(materialization, "monotonic", lambda: next(ticks) * 2)
    def verify(db, **kwargs):
        assert kwargs["owner_user_id"] == user.id and kwargs["resource_id"] == source.drive_file_id
        checks.append(kwargs)
        if failure == "changed" and reads:
            raise YandexDiskError("resource_changed")
        return resource
    class DiskClient:
        def download_to(self, selected, target, *, maximum_bytes, check):
            assert selected == resource and maximum_bytes == 1000
            assert not sqlite_session.in_transaction()
            reads.append(target)
            target.write(b"a" * 50)
            if failure == "cancelled":
                job.cancel_requested_at = now
                sqlite_session.commit()
            check()
            target.write(b"b" * 50)
            return 100
    context = materialization.materialize_processing_job_source(sqlite_session,
        job_id=job.id, job_source_id=relation.id, lease_owner_id="worker-1", lease_generation=1,
        settings=SimpleSettings(), now=now, clock=lambda: now,
        disk_resource_verifier=verify, disk_token_resolver=lambda *a, **kw: "synthetic",
        disk_client_factory=lambda token: DiskClient(),
        drive_token_resolver=lambda *a, **kw: pytest.fail("must not use Google"))
    if failure:
        expected = "cancellation_requested" if failure == "cancelled" else "external_source_unavailable"
        with pytest.raises(materialization.SourceMaterializationError, match=expected):
            with context:
                pytest.fail("failed download must not reach STT")
    else:
        with context as handle:
            assert handle.stream.read() == b"a" * 50 + b"b" * 50
            assert handle.source_type == "yandex_disk"
        assert len(checks) == 3  # Availability, before and after reading.
    assert reads and reads[0].closed


def assert_safe(text):
    for value in ["private/key", "studio-temp", "drive-1", "token-secret", "Authorization", "https://", "source-bytes"]:
        assert value not in text


def test_test_module_has_no_import_time_env_file_or_schema_side_effects():
    source = Path(__file__).read_text(encoding="utf-8")
    before_fixtures = source.split("@pytest.fixture", 1)[0]
    assert "os.environ" not in before_fixtures
    assert "write_text" not in before_fixtures
    assert "create_all" not in before_fixtures


def test_local_upload_success_rewinds_metadata_repr_and_closes(sqlite_session, models):
    job, src, rel, _, now, _ = make_job(sqlite_session, models)
    body = FakeBody([b"a" * 40, b"b" * 60])
    storage = FakeStorage(FakeStream(body))
    with materialize(sqlite_session, job, rel, storage=storage, now=now) as handle:
        assert handle.position == 0 and handle.byte_count == 100 and handle.stream.tell() == 0
        assert handle.stream.read(1) == b"a"
        assert handle.identity.source_id == src.id
        assert_safe(repr(handle))
    assert body.closed
    assert handle.stream.closed


def test_download_observes_cancellation_between_chunks_and_closes_stream(sqlite_session, models, monkeypatch):
    from studio_api import job_source_materialization as materialization
    job, _, rel, _, now, _ = make_job(sqlite_session, models)
    ticks = iter(range(100))
    monkeypatch.setattr(materialization, "monotonic", lambda: next(ticks) * 2)
    reads = []
    class CancellingBody(FakeBody):
        def read(self, size=-1):
            reads.append(1)
            if len(reads) == 2:
                job.cancel_requested_at = now
                sqlite_session.commit()
            return super().read(size)
    body = CancellingBody([b"a" * 30, b"b" * 30, b"c" * 40])
    with pytest.raises(materialization.SourceMaterializationError, match="cancellation_requested"):
        with materialize(sqlite_session, job, rel, storage=FakeStorage(FakeStream(body)), now=now):
            pytest.fail("cancelled download must not reach preparation or STT")
    assert len(reads) == 2 and body.closed


def test_source_download_runs_without_idle_database_transaction(
    sqlite_session,
    models,
):
    job, _, rel, _, now, _ = make_job(sqlite_session, models)
    body = FakeBody([b"a" * 100])
    observed = []

    class TransactionAwareStorage(FakeStorage):
        def open_read(self, key):
            observed.append(sqlite_session.in_transaction())
            return super().open_read(key)

    storage = TransactionAwareStorage(FakeStream(body))
    with materialize(sqlite_session, job, rel, storage=storage, now=now) as handle:
        assert handle.byte_count == 100

    assert observed == [False]


def test_audio_reference_materialization_uses_only_audio_bucket_boundary(sqlite_session, models):
    job, _, rel, _, now, _ = make_job(
        sqlite_session,
        models,
        source_kwargs={
            "reference_class": "audio_processing",
            "s3_bucket": "studio-audio",
        },
    )
    storage = FakeStorage(FakeStream(FakeBody([b"a" * 100])))
    selected_buckets = []

    def select_storage(selected_settings):
        selected_buckets.append(selected_settings.source_s3_bucket)
        return storage

    with materialize(
        sqlite_session,
        job,
        rel,
        storage=storage,
        storage_factory=select_storage,
        now=now,
    ) as handle:
        assert handle.byte_count == 100

    assert selected_buckets == ["studio-audio", "studio-audio"]


def test_local_missing_failure_too_large_size_and_mime_are_safe(sqlite_session, models):
    from studio_api.job_source_materialization import SourceMaterializationError
    from studio_api.source_storage import SourceObjectReadError, SourceObjectReadReason
    cases = [
        (FakeStorage(exc=SourceObjectReadError(SourceObjectReadReason.missing)), "source_object_missing"),
        (FakeStorage(exc=SourceObjectReadError(SourceObjectReadReason.unavailable)), "external_source_unavailable"),
        (FakeStorage(FakeStream(FakeBody([b"x" * 1001]), content_length=1001)), "source_too_large"),
        (FakeStorage(FakeStream(FakeBody([b"x" * 80]), content_length=100)), "size_mismatch"),
        (FakeStorage(FakeStream(FakeBody([b"x" * 100]), content_type="video/mp4"), head_content_type="audio/mpeg"), "mime_mismatch"),
    ]
    for index, (storage, reason) in enumerate(cases):
        job, _, rel, _, now, _ = make_job(sqlite_session, models, source_kwargs={"original_filename": f"case{index}.mp3"})
        with pytest.raises(SourceMaterializationError) as exc:
            with materialize(sqlite_session, job, rel, storage=storage, now=now):
                pass
        assert str(exc.value) == reason
        assert_safe(str(exc.value))
        if storage.stream and reason not in {"source_too_large", "mime_mismatch"}:
            assert storage.stream.body.closed


def test_drive_success_uses_one_token_and_alt_media_reader(sqlite_session, models):
    job, _, rel, _, now, _ = make_job(sqlite_session, models, source_type=models.SourceType.google_drive)
    body = FakeBody([b"g" * 100])
    calls = {"token": 0, "fetch": 0}
    def token(*a, **k):
        calls["token"] += 1; return "token-secret"
    def fetch(access_token, drive_file_id):
        calls["fetch"] += 1
        assert access_token == "token-secret" and drive_file_id == "drive-1"
        return FakeStream(body)
    with materialize(sqlite_session, job, rel, storage=FakeStorage(FakeStream(FakeBody([b"x"*100]))), token_resolver=token, drive_fetcher=fetch, now=now) as handle:
        assert handle.stream.read() == b"g" * 100
    assert calls == {"token": 1, "fetch": 1}
    assert body.closed


def test_drive_failures_are_normalized_and_safe(sqlite_session, models):
    from studio_api.google_drive import GoogleDriveContentError, GoogleDriveContentReason
    from studio_api.job_source_materialization import SourceMaterializationError
    for exc_obj, reason in [
        (GoogleDriveContentError(GoogleDriveContentReason.not_found), "source_object_missing"),
        (GoogleDriveContentError(GoogleDriveContentReason.unavailable), "external_source_unavailable"),
        (RuntimeError("raw response body drive-1 token-secret"), "external_source_unavailable"),
    ]:
        job, _, rel, _, now, _ = make_job(sqlite_session, models, source_type=models.SourceType.google_drive)
        def fetch(*_):
            if isinstance(exc_obj, RuntimeError) and not isinstance(exc_obj, GoogleDriveContentError):
                return FakeStream(FakeBody([], exc=exc_obj))
            raise exc_obj
        with pytest.raises(SourceMaterializationError) as err:
            with materialize(sqlite_session, job, rel, storage=FakeStorage(FakeStream(FakeBody([b"x"*100]))), drive_fetcher=fetch, now=now):
                pass
        assert str(err.value) == reason
        assert_safe(str(err.value))


def test_lifecycle_and_toctou_fail_closed(sqlite_session, models):
    from studio_api.job_source_materialization import SourceMaterializationError
    cases = [
        ({"job_kwargs": {"status": models.JobStatus.queued}}, "job_not_processing"),
        ({"job_kwargs": {"lease_owner_id": "other"}}, "lease_not_owned"),
        ({"job_kwargs": {"lease_generation": 2}}, "lease_not_owned"),
        ({"max_delta": timedelta(seconds=-1)}, "lease_not_active"),
        ({"job_kwargs": {"cancel_requested_at": None}}, None),
        ({"rel_kwargs": {"status": models.JobSourceStatus.skipped}}, "job_source_not_processable"),
        ({"source_kwargs": {"deleted_at": None, "upload_status": models.SourceUploadStatus.deleted}}, "availability_verification_failed"),
    ]
    for kwargs, reason in cases:
        if reason is None:
            continue
        job, _, rel, _, now, _ = make_job(sqlite_session, models, **kwargs)
        with pytest.raises(SourceMaterializationError) as err:
            with materialize(sqlite_session, job, rel, storage=FakeStorage(FakeStream(FakeBody([b"x"*100]))), now=now):
                pass
        assert str(err.value) == reason


def test_mutations_during_copy_clean_temp(sqlite_session, models):
    from studio_api.job_source_materialization import SourceMaterializationError
    mutations = [
        lambda job, src, project: setattr(src, "s3_object_key", "changed/key"),
        lambda job, src, project: setattr(job, "lease_owner_id", "other"),
        lambda job, src, project: setattr(job, "cancel_requested_at", job.started_at),
        lambda job, src, project: setattr(project, "archived_at", job.started_at),
    ]
    for mutate in mutations:
        job, src, rel, project, now, _ = make_job(sqlite_session, models)
        def before_eof(job=job, src=src, project=project):
            mutate(job, src, project); sqlite_session.commit()
        body = FakeBody([b"x" * 100], before_eof=before_eof)
        with pytest.raises(SourceMaterializationError) as err:
            with materialize(sqlite_session, job, rel, storage=FakeStorage(FakeStream(body)), now=now):
                pass
        assert str(err.value) in {"selected_source_changed", "lease_not_owned", "cancellation_requested", "availability_verification_failed"}
        assert body.closed


def test_caller_exception_propagates_unchanged_and_stream_closes(sqlite_session, models):
    class SentinelCallerError(Exception):
        pass

    job, _, rel, _, now, _ = make_job(sqlite_session, models)
    body = FakeBody([b"a" * 100])
    storage = FakeStorage(FakeStream(body))
    yielded_stream = None

    with pytest.raises(SentinelCallerError) as err:
        with materialize(sqlite_session, job, rel, storage=storage, now=now) as handle:
            yielded_stream = handle.stream
            assert yielded_stream.read(1) == b"a"
            raise SentinelCallerError("caller sentinel")

    assert type(err.value) is SentinelCallerError
    assert str(err.value) == "caller sentinel"
    assert yielded_stream is not None
    assert yielded_stream.closed


def test_heartbeat_only_lease_expiry_change_does_not_trip_source_snapshot(sqlite_session, models):
    from datetime import timedelta
    job, _, rel, _, now, _ = make_job(sqlite_session, models)
    def heartbeat_only():
        job.lease_expires_at = now + timedelta(minutes=10)
        sqlite_session.flush()
    body = FakeBody([b"a" * 100], before_eof=heartbeat_only)
    storage = FakeStorage(FakeStream(body))
    with materialize(sqlite_session, job, rel, storage=storage, now=now, drive_meta=fake_drive_meta) as handle:
        assert handle.byte_count == 100


@pytest.mark.parametrize("mutate,reason", [
    (lambda m,j,r,s,n: setattr(j, "lease_owner_id", "other"), "lease_not_owned"),
    (lambda m,j,r,s,n: setattr(j, "lease_generation", 2), "lease_not_owned"),
    (lambda m,j,r,s,n: setattr(j, "lease_expires_at", n - timedelta(seconds=1)), "lease_not_active"),
    (lambda m,j,r,s,n: setattr(j, "cancel_requested_at", n), "cancellation_requested"),
    (lambda m,j,r,s,n: setattr(s, "s3_object_key", "changed"), "selected_source_changed"),
])
def test_source_snapshot_still_fails_closed_for_authority_mutations(sqlite_session, models, mutate, reason):
    from studio_api.job_source_materialization import SourceMaterializationError
    job, src, rel, _, now, _ = make_job(sqlite_session, models)
    def mutation():
        mutate(models, job, rel, src, now)
        sqlite_session.flush()
    storage = FakeStorage(FakeStream(FakeBody([b"a" * 100], before_eof=mutation)))
    with pytest.raises(SourceMaterializationError) as exc:
        with materialize(sqlite_session, job, rel, storage=storage, now=now):
            pass
    assert exc.value.reason.value == reason
