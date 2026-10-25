from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Callable, Iterator
from time import monotonic

from sqlalchemy.orm import Session, selectinload

from .google_connection_access import GoogleConnectionAccessError, refresh_user_google_drive_access_token
from .google_drive import GoogleDriveContentError, GoogleDriveContentReason, fetch_drive_file_content, fetch_drive_file_metadata
from .job_claim_lease import is_lease_active
from .job_source_availability import verify_processing_job_sources
from .models import JobSourceStatus, JobStatus, Project, SourceType, SourceUploadStatus, TranscriptionJob, TranscriptionJobSource
from .security import utcnow
from .yandex_disk import YandexDiskClient, YandexDiskError
from .yandex_disk_access import access_token as disk_access_token, verify_selected_resource
from .source_policy import is_source_expired, is_supported_source_mime_type, normalize_source_mime_type, validate_source_size
from .source_storage import (
    SourceObjectReadError,
    SourceObjectReadReason,
    get_source_storage,
    reference_storage_bucket,
    reference_storage_isolation_configured,
    reference_storage_settings,
    safe_filename,
    source_reference_class,
)

_CHUNK_SIZE = 1024 * 1024


class SourceMaterializationReason(str, Enum):
    job_not_found = "job_not_found"
    job_not_processing = "job_not_processing"
    lease_not_owned = "lease_not_owned"
    lease_not_active = "lease_not_active"
    cancellation_requested = "cancellation_requested"
    availability_verification_failed = "availability_verification_failed"
    job_source_not_found = "job_source_not_found"
    job_source_not_processable = "job_source_not_processable"
    selected_source_changed = "selected_source_changed"
    source_object_missing = "source_object_missing"
    external_source_unavailable = "external_source_unavailable"
    source_too_large = "source_too_large"
    mime_mismatch = "mime_mismatch"
    size_mismatch = "size_mismatch"
    temporary_materialization_failure = "temporary_materialization_failure"


class SourceMaterializationError(RuntimeError):
    def __init__(self, reason: SourceMaterializationReason):
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True)
class MaterializedSourceIdentity:
    job_id: str
    job_source_id: str
    source_id: str


@dataclass
class MaterializedJobSource:
    identity: MaterializedSourceIdentity
    position: int
    original_filename: str
    mime_type: str
    byte_count: int
    stream: BinaryIO = field(repr=False)
    source_type: str | None = None
    source_created_at: datetime | None = None
    source_created_at_provenance: str | None = None

    def __repr__(self) -> str:
        return (
            "MaterializedJobSource("
            f"identity={self.identity!r}, position={self.position!r}, "
            f"original_filename=<redacted>, mime_type={self.mime_type!r}, "
            f"byte_count={self.byte_count!r}, stream=<redacted>)"
        )


@dataclass(frozen=True)
class _SourceSnapshot:
    job_id: str
    job_source_id: str
    source_id: str
    position: int
    relation_status: str
    source_type: str
    source_project_id: str
    drive_file_id: str | None
    s3_bucket: str | None
    s3_object_key: str | None
    reference_class: str
    mime_type: str | None
    size_bytes: int | None
    upload_status: str
    deleted_at: datetime | None
    expires_at: datetime | None
    source_created_at: datetime | None
    source_created_at_provenance: str | None
    lease_owner_id: str | None
    lease_generation: int
    cancel_requested_at: datetime | None
    job_status: str
    project_archived_at: datetime | None
    project_owner_user_id: str | None
    job_owner_user_id: str
    job_project_id: str
    original_filename: str


@contextmanager
def materialize_processing_job_source(
    db: Session,
    *,
    job_id: str,
    job_source_id: str,
    lease_owner_id: str,
    lease_generation: int,
    settings,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    storage_factory: Callable = get_source_storage,
    drive_token_resolver: Callable = refresh_user_google_drive_access_token,
    drive_content_fetcher: Callable = fetch_drive_file_content,
    drive_metadata_fetcher: Callable = fetch_drive_file_metadata,
    disk_resource_verifier: Callable = verify_selected_resource,
    disk_token_resolver: Callable = disk_access_token,
    disk_client_factory: Callable = YandexDiskClient,
) -> Iterator[MaterializedJobSource]:
    clock = clock or (lambda: utcnow().replace(tzinfo=None))
    check_now = now or clock()
    temp: BinaryIO | None = None
    try:
        try:
            cached_token: dict[str, str] = {}

            def _cached_drive_token_resolver(*args, **kwargs):
                if "token" not in cached_token:
                    cached_token["token"] = drive_token_resolver(*args, **kwargs)
                return cached_token["token"]

            availability = verify_processing_job_sources(
                db,
                job_id=job_id,
                lease_owner_id=lease_owner_id,
                lease_generation=lease_generation,
                now=check_now,
                settings=settings,
                storage_factory=storage_factory,
                drive_token_resolver=_cached_drive_token_resolver,
                drive_metadata_fetcher=drive_metadata_fetcher,
                now_provider=clock,
                disk_resource_verifier=disk_resource_verifier,
            )
            if not availability.ready:
                raise SourceMaterializationError(_availability_reason(availability.blocking_reasons))
            snap = _load_selected_snapshot(db, job_id, job_source_id, lease_owner_id, lease_generation, check_now, settings)
            # All authority fields needed for the download are now immutable
            # scalars. A fresh snapshot is compared after the external I/O.
            db.rollback()
            temp = SpooledTemporaryFile(max_size=min(settings.source_max_upload_bytes, 8 * 1024 * 1024), mode="w+b")
            check = processing_source_control(db, job_id=job_id, job_source_id=job_source_id,
                lease_owner_id=lease_owner_id, lease_generation=lease_generation,
                clock=clock, settings=settings, expected=snap)
            byte_count, response_mime, response_length = _copy_source_bytes(
                snap,
                temp,
                settings,
                storage_factory,
                _cached_drive_token_resolver,
                drive_content_fetcher,
                db,
                check,
                disk_resource_verifier=disk_resource_verifier,
                disk_token_resolver=disk_token_resolver,
                disk_client_factory=disk_client_factory,
            )
            _validate_materialized_metadata(snap, byte_count, response_mime, response_length, settings)
            _compare_snapshot(snap, _load_selected_snapshot(db, job_id, job_source_id, lease_owner_id, lease_generation, clock(), settings))
            temp.seek(0)
            handle = MaterializedJobSource(
                identity=MaterializedSourceIdentity(job_id=snap.job_id, job_source_id=snap.job_source_id, source_id=snap.source_id),
                position=snap.position,
                original_filename=safe_filename(snap.original_filename),
                mime_type=normalize_source_mime_type(response_mime) or snap.mime_type or "application/octet-stream",
                byte_count=byte_count,
                stream=temp,
                source_type=snap.source_type,
                source_created_at=snap.source_created_at,
                source_created_at_provenance=snap.source_created_at_provenance,
            )
        except SourceMaterializationError:
            raise
        except Exception as exc:
            raise SourceMaterializationError(SourceMaterializationReason.temporary_materialization_failure) from exc

        yield handle
    finally:
        if temp is not None:
            temp.close()


def _load_selected_snapshot(db, job_id, job_source_id, owner, generation, now, settings, *, allow_retired_source=False) -> _SourceSnapshot:
    db.expire_all()
    job = db.query(TranscriptionJob).options(selectinload(TranscriptionJob.sources).selectinload(TranscriptionJobSource.source)).filter_by(id=job_id).first()
    if job is None:
        raise SourceMaterializationError(SourceMaterializationReason.job_not_found)
    if job.status != JobStatus.processing:
        raise SourceMaterializationError(SourceMaterializationReason.job_not_processing)
    if job.lease_owner_id != owner or job.lease_generation != generation:
        raise SourceMaterializationError(SourceMaterializationReason.lease_not_owned)
    if not is_lease_active(job, now):
        raise SourceMaterializationError(SourceMaterializationReason.lease_not_active)
    if job.cancel_requested_at is not None:
        raise SourceMaterializationError(SourceMaterializationReason.cancellation_requested)
    project = db.get(Project, job.project_id)
    if project is None or project.owner_user_id != job.owner_user_id or project.archived_at is not None:
        raise SourceMaterializationError(SourceMaterializationReason.availability_verification_failed)
    rel = next((item for item in job.sources if item.id == job_source_id), None)
    if rel is None or rel.job_id != job.id or rel.source is None:
        raise SourceMaterializationError(SourceMaterializationReason.job_source_not_found)
    src = rel.source
    mime = normalize_source_mime_type(src.mime_type)
    if rel.status == JobSourceStatus.skipped or src.project_id != job.project_id or (not allow_retired_source and (src.upload_status != SourceUploadStatus.uploaded or src.deleted_at is not None)):
        raise SourceMaterializationError(SourceMaterializationReason.job_source_not_processable)
    if not allow_retired_source and is_source_expired(src.expires_at, now):
        raise SourceMaterializationError(SourceMaterializationReason.job_source_not_processable)
    if src.source_type not in {SourceType.local_upload, SourceType.google_drive, SourceType.yandex_disk} or not is_supported_source_mime_type(mime):
        raise SourceMaterializationError(SourceMaterializationReason.job_source_not_processable)
    if not validate_source_size(src.size_bytes, settings.source_max_upload_bytes):
        raise SourceMaterializationError(SourceMaterializationReason.source_too_large)
    return _SourceSnapshot(job.id, rel.id, src.id, rel.position, _value(rel.status), _value(src.source_type), src.project_id, src.drive_file_id, src.s3_bucket, src.s3_object_key, source_reference_class(src), mime, src.size_bytes, _value(src.upload_status), src.deleted_at, src.expires_at, src.source_created_at, src.source_created_at_provenance, job.lease_owner_id, job.lease_generation, job.cancel_requested_at, _value(job.status), project.archived_at, project.owner_user_id, job.owner_user_id, job.project_id, src.original_filename)


def processing_source_control(db, *, job_id, job_source_id, lease_owner_id, lease_generation, clock, settings, expected=None):
    last_check = None

    def check():
        nonlocal last_check
        from .worker_progress import touch_worker_progress
        touch_worker_progress()
        current = monotonic()
        if last_check is not None and current - last_check < 1:
            return
        try:
            snapshot = _load_selected_snapshot(db, job_id, job_source_id, lease_owner_id,
                lease_generation, clock(), settings)
            if expected is not None:
                _compare_snapshot(expected, snapshot)
        finally:
            db.rollback()
        last_check = current
    return check


def _copy_source_bytes(snap, temp, settings, storage_factory, drive_token_resolver, drive_content_fetcher, db, check=lambda: None,
                       *, disk_resource_verifier=verify_selected_resource, disk_token_resolver=disk_access_token,
                       disk_client_factory=YandexDiskClient):
    if snap.source_type == SourceType.yandex_disk.value:
        if not snap.drive_file_id:
            raise SourceMaterializationError(SourceMaterializationReason.job_source_not_processable)
        try:
            resource = disk_resource_verifier(db, owner_user_id=snap.job_owner_user_id,
                resource_id=snap.drive_file_id, settings=settings, is_folder=False)
            token = disk_token_resolver(db, user_id=snap.job_owner_user_id, settings=settings)
            db.rollback()
            count = disk_client_factory(token).download_to(resource, temp,
                maximum_bytes=settings.source_max_upload_bytes, check=check)
            # The selected resource must still be the same version after reading.
            disk_resource_verifier(db, owner_user_id=snap.job_owner_user_id,
                resource_id=snap.drive_file_id, settings=settings, is_folder=False)
            db.rollback()
            return count, resource.mime_type, resource.size_bytes
        except YandexDiskError as exc:
            raise SourceMaterializationError(SourceMaterializationReason.external_source_unavailable) from exc
    if snap.source_type == SourceType.local_upload.value:
        if (
            not reference_storage_isolation_configured(settings)
            or snap.s3_bucket
            != reference_storage_bucket(settings, snap.reference_class)
            or not snap.s3_object_key
        ):
            raise SourceMaterializationError(SourceMaterializationReason.job_source_not_processable)
        try:
            stream = storage_factory(
                reference_storage_settings(settings, snap.reference_class)
            ).open_read(snap.s3_object_key)
        except SourceObjectReadError as exc:
            raise SourceMaterializationError(SourceMaterializationReason.source_object_missing if exc.reason == SourceObjectReadReason.missing else SourceMaterializationReason.external_source_unavailable) from exc
    else:
        if not snap.drive_file_id:
            raise SourceMaterializationError(SourceMaterializationReason.job_source_not_processable)
        try:
            token = drive_token_resolver(db, user_id=snap.job_owner_user_id, settings=settings)
            db.rollback()
            stream = drive_content_fetcher(token, snap.drive_file_id)
        except GoogleConnectionAccessError as exc:
            raise SourceMaterializationError(SourceMaterializationReason.external_source_unavailable) from exc
        except GoogleDriveContentError as exc:
            raise SourceMaterializationError(SourceMaterializationReason.source_object_missing if exc.reason == GoogleDriveContentReason.not_found else SourceMaterializationReason.external_source_unavailable) from exc
    try:
        count = 0
        for chunk in stream.iter_chunks(_CHUNK_SIZE):
            check()
            if not chunk:
                continue
            count += len(chunk)
            if count > settings.source_max_upload_bytes:
                raise SourceMaterializationError(SourceMaterializationReason.source_too_large)
            temp.write(chunk)
        return count, stream.content_type, stream.content_length
    except SourceMaterializationError:
        raise
    except Exception as exc:
        raise SourceMaterializationError(SourceMaterializationReason.external_source_unavailable) from exc
    finally:
        stream.close()


def _validate_materialized_metadata(snap, count, response_mime, response_length, settings):
    if not validate_source_size(count, settings.source_max_upload_bytes):
        raise SourceMaterializationError(SourceMaterializationReason.source_too_large)
    if snap.size_bytes is not None and count != snap.size_bytes:
        raise SourceMaterializationError(SourceMaterializationReason.size_mismatch)
    if response_length is not None and count != response_length:
        raise SourceMaterializationError(SourceMaterializationReason.size_mismatch)
    mime = normalize_source_mime_type(response_mime)
    if mime is not None:
        if not is_supported_source_mime_type(mime) or (snap.mime_type and mime != snap.mime_type):
            raise SourceMaterializationError(SourceMaterializationReason.mime_mismatch)


def _compare_snapshot(before, after):
    if before != after:
        raise SourceMaterializationError(SourceMaterializationReason.selected_source_changed)


def _availability_reason(reasons):
    if "job_not_found" in reasons:
        return SourceMaterializationReason.job_not_found
    if "job_not_processing" in reasons:
        return SourceMaterializationReason.job_not_processing
    if "lease_not_owned" in reasons:
        return SourceMaterializationReason.lease_not_owned
    if "lease_not_active" in reasons:
        return SourceMaterializationReason.lease_not_active
    if "cancellation_requested" in reasons:
        return SourceMaterializationReason.cancellation_requested
    if "source_too_large" in reasons:
        return SourceMaterializationReason.source_too_large
    return SourceMaterializationReason.availability_verification_failed


def _value(value):
    return str(getattr(value, "value", value))
