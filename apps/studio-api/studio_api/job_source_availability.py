from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from sqlalchemy.orm import Session, selectinload

from .google_connection_access import GoogleConnectionAccessError, refresh_user_google_drive_access_token
from .google_drive import GOOGLE_FOLDER_MIME_TYPE, GoogleDriveMetadataError, GoogleDriveMetadataReason, fetch_drive_file_metadata
from .job_claim_lease import is_lease_active
from .models import JobStatus, Project, SourceType, SourceUploadStatus, TranscriptionJob, TranscriptionJobSource
from .security import utcnow
from .yandex_disk import YandexDiskError
from .yandex_disk_access import verify_selected_resource
from .source_policy import is_source_expired, is_supported_source_mime_type, normalize_source_mime_type, validate_source_size
from .source_storage import (
    get_source_storage,
    reference_storage_bucket,
    reference_storage_isolation_configured,
    reference_storage_settings,
    source_reference_class,
)


@dataclass(frozen=True)
class ProcessingSourceAvailabilitySourceSummary:
    source_id: str | None
    position: int
    source_type: str | None
    original_filename: str | None
    mime_type: str | None
    size_bytes: int | None
    available: bool
    blocking_reasons: list[str]


@dataclass(frozen=True)
class ProcessingSourceAvailabilitySummary:
    job_id: str
    project_id: str | None
    verified_at: datetime
    lease_generation: int
    ready: bool
    blocking_reasons: list[str]
    sources: list[ProcessingSourceAvailabilitySourceSummary]


@dataclass(frozen=True)
class JobBoundarySnapshot:
    id: str
    owner_user_id: str
    project_id: str
    status: str
    lease_owner_id: str | None
    lease_generation: int
    lease_expires_at: datetime | None
    cancel_requested_at: datetime | None


@dataclass(frozen=True)
class ProjectBoundarySnapshot:
    id: str | None
    owner_user_id: str | None
    archived_at: datetime | None


@dataclass(frozen=True)
class SourceRelationSnapshot:
    job_source_id: str
    job_id: str
    source_id: str
    position: int
    job_source_status: str
    source_type: str | None
    project_id: str | None
    drive_file_id: str | None
    s3_bucket: str | None
    s3_object_key: str | None
    reference_class: str | None
    mime_type: str | None
    size_bytes: int | None
    upload_status: str | None
    deleted_at: datetime | None
    expires_at: datetime | None


@dataclass(frozen=True)
class ProcessingBoundarySnapshot:
    job: JobBoundarySnapshot
    project: ProjectBoundarySnapshot
    relations: tuple[SourceRelationSnapshot, ...]


@dataclass(frozen=True)
class RevalidationResult:
    blocking_reasons: tuple[str, ...]
    changed_source_ids: frozenset[str]
    source_set_changed: bool = False


def verify_processing_job_sources(
    db: Session,
    *,
    job_id: str,
    lease_owner_id: str,
    lease_generation: int,
    now: datetime,
    settings,
    storage_factory: Callable = get_source_storage,
    drive_token_resolver: Callable = refresh_user_google_drive_access_token,
    drive_metadata_fetcher: Callable = fetch_drive_file_metadata,
    now_provider: Callable[[], datetime] | None = None,
    disk_resource_verifier: Callable = verify_selected_resource,
) -> ProcessingSourceAvailabilitySummary:
    job = _load_job(db, job_id)
    initial_reasons = _job_boundary_reasons(job, lease_owner_id, lease_generation, now)
    project = db.get(Project, job.project_id) if job else None
    if job and (project is None or project.owner_user_id != job.owner_user_id):
        initial_reasons.append("project_missing")
    if project and project.archived_at is not None:
        initial_reasons.append("project_archived")
    job_sources = sorted(job.sources, key=lambda item: item.position) if job else []
    if job and not job_sources:
        initial_reasons.append("job_has_no_sources")

    if initial_reasons:
        return _summary(job_id, job.project_id if job else None, now, lease_generation, initial_reasons, [])

    boundary_snapshot = _boundary_snapshot(job, project, job_sources)
    snapshots = [_snapshot(job, js) for js in job_sources]
    # The immutable snapshot is sufficient for external checks. Do not leave the
    # restricted worker connection idle while R2 or Google Drive responds.
    db.rollback()
    token: str | None = None
    token_failed_reason: str | None = None
    source_summaries: list[ProcessingSourceAvailabilitySourceSummary] = []
    for snap in snapshots:
        reasons = list(snap["reasons"])
        if not validate_source_size(snap["size_bytes"], settings.source_max_upload_bytes):
            reasons.append("source_too_large")
        effective_mime = snap["mime_type"]
        effective_size = snap["size_bytes"]
        if not reasons:
            if snap["source_type"] == SourceType.local_upload.value:
                mime, size, more = _verify_local(snap, now, settings, storage_factory)
                effective_mime = mime if mime is not None else effective_mime
                effective_size = size if size is not None else effective_size
                reasons.extend(more)
            elif snap["source_type"] == SourceType.google_drive.value:
                if token is None and token_failed_reason is None:
                    try:
                        token = drive_token_resolver(
                            db,
                            user_id=boundary_snapshot.job.owner_user_id,
                            settings=settings,
                        )
                        db.rollback()
                    except GoogleConnectionAccessError as exc:
                        token_failed_reason = "google_token_unavailable" if exc.reason.value == "google_config_unavailable" else exc.reason.value
                    except Exception:
                        token_failed_reason = "google_token_unavailable"
                if token_failed_reason:
                    reasons.append(token_failed_reason)
                else:
                    mime, size, more = _verify_drive(snap, token, settings, drive_metadata_fetcher)
                    effective_mime = mime if mime is not None else effective_mime
                    effective_size = size if size is not None else effective_size
                    reasons.extend(more)
            elif snap["source_type"] == SourceType.yandex_disk.value:
                try:
                    resource = disk_resource_verifier(db, owner_user_id=boundary_snapshot.job.owner_user_id,
                        resource_id=snap["drive_file_id"], settings=settings, is_folder=False)
                    effective_mime = normalize_source_mime_type(resource.mime_type)
                    effective_size = resource.size_bytes
                    if effective_mime != snap["mime_type"]:
                        reasons.append("source_mime_mismatch")
                    if effective_size != snap["size_bytes"]:
                        reasons.append("source_size_mismatch")
                except YandexDiskError as exc:
                    reasons.append("yandex_disk_" + exc.reason)
                finally:
                    db.rollback()
            else:
                reasons.append("unsupported_source_type")
        source_summaries.append(_source_summary(snap, effective_mime, effective_size, reasons))

    recheck_now = now_provider() if now_provider else utcnow().replace(tzinfo=None)
    recheck = _revalidate(db, boundary_snapshot, lease_owner_id, lease_generation, recheck_now)
    if recheck.changed_source_ids:
        source_summaries = [
            _with_extra_reason(s, "source_state_changed") if s.source_id in recheck.changed_source_ids else s
            for s in source_summaries
        ]
    all_reasons = _dedupe([r for s in source_summaries for r in s.blocking_reasons] + list(recheck.blocking_reasons))
    return _summary(
        boundary_snapshot.job.id,
        boundary_snapshot.job.project_id,
        recheck_now,
        lease_generation,
        all_reasons,
        source_summaries,
    )


def _load_job(db: Session, job_id: str):
    return db.query(TranscriptionJob).options(selectinload(TranscriptionJob.sources).selectinload(TranscriptionJobSource.source)).filter(TranscriptionJob.id == job_id).first()


def _job_boundary_reasons(job, owner, generation, now):
    if job is None:
        return ["job_not_found"]
    reasons = []
    if job.status != JobStatus.processing:
        reasons.append("job_not_processing")
    if job.lease_owner_id != owner or job.lease_generation != generation:
        reasons.append("lease_not_owned")
    if not is_lease_active(job, now):
        reasons.append("lease_not_active")
    if job.cancel_requested_at is not None:
        reasons.append("cancellation_requested")
    return reasons


def _snapshot(job, js):
    src = js.source
    reasons = []
    if src is None:
        return {"source_id": None, "position": js.position, "source_type": None, "original_filename": None, "mime_type": None, "size_bytes": None, "reasons": ["source_missing"]}
    source_type = str(src.source_type.value)
    mime = normalize_source_mime_type(src.mime_type)
    if src.project_id != job.project_id:
        reasons.append("source_project_mismatch")
    if src.deleted_at is not None or src.upload_status == SourceUploadStatus.deleted:
        reasons.append("source_deleted")
    if src.upload_status != SourceUploadStatus.uploaded:
        reasons.append("source_not_uploaded")
    if source_type not in {SourceType.local_upload.value, SourceType.google_drive.value, SourceType.yandex_disk.value}:
        reasons.append("unsupported_source_type")
    if not is_supported_source_mime_type(mime):
        reasons.append("unsupported_mime_type")
    return {"source_id": src.id, "position": js.position, "source_type": source_type, "original_filename": src.original_filename, "mime_type": mime, "size_bytes": src.size_bytes, "project_id": src.project_id, "upload_status": str(src.upload_status.value), "deleted_at": src.deleted_at, "expires_at": src.expires_at, "s3_bucket": src.s3_bucket, "s3_object_key": src.s3_object_key, "reference_class": source_reference_class(src), "drive_file_id": src.drive_file_id, "reasons": reasons}


def _verify_local(snap, now, settings, storage_factory):
    reasons = []
    if is_source_expired(snap["expires_at"], now):
        reasons.append("source_expired")
    if not snap["s3_bucket"] or not snap["s3_object_key"]:
        reasons.append("source_missing_required_identity")
    if not reference_storage_isolation_configured(settings):
        reasons.append("source_storage_not_configured")
    if snap["s3_bucket"] != reference_storage_bucket(
        settings, snap["reference_class"]
    ):
        reasons.append("source_bucket_mismatch")
    if reasons:
        return None, None, reasons
    try:
        head = storage_factory(
            reference_storage_settings(settings, snap["reference_class"])
        ).head_object(snap["s3_object_key"])
    except FileNotFoundError:
        return None, None, ["storage_object_missing"]
    except Exception:
        return None, None, ["external_metadata_unavailable"]
    actual_mime = normalize_source_mime_type(head.content_type) or snap["mime_type"]
    actual_size = head.size_bytes if head.size_bytes is not None else snap["size_bytes"]
    if not is_supported_source_mime_type(actual_mime):
        reasons.append("unsupported_mime_type")
    if not validate_source_size(actual_size, settings.source_max_upload_bytes):
        reasons.append("source_too_large")
    if snap["size_bytes"] is not None and head.size_bytes is not None and snap["size_bytes"] != head.size_bytes:
        reasons.append("source_size_mismatch")
    if snap["mime_type"] and head.content_type and snap["mime_type"] != actual_mime:
        reasons.append("source_mime_mismatch")
    return actual_mime, actual_size, reasons


def _verify_drive(snap, token, settings, fetcher):
    if not snap["drive_file_id"]:
        return None, None, ["source_missing_required_identity"]
    try:
        meta = fetcher(token, snap["drive_file_id"])
    except GoogleDriveMetadataError as exc:
        if exc.reason == GoogleDriveMetadataReason.not_found:
            return None, None, ["drive_file_missing"]
        return None, None, ["drive_metadata_unavailable"]
    except FileNotFoundError:
        return None, None, ["drive_file_missing"]
    except Exception:
        return None, None, ["drive_metadata_unavailable"]
    reasons = []
    mime = normalize_source_mime_type(meta.mime_type)
    if meta.id != snap["drive_file_id"]:
        reasons.append("drive_file_identity_mismatch")
    if getattr(meta, "is_folder", False) or mime == GOOGLE_FOLDER_MIME_TYPE:
        reasons.append("drive_file_is_folder")
    if not is_supported_source_mime_type(mime):
        reasons.append("unsupported_mime_type")
    if not validate_source_size(meta.size_bytes, settings.source_max_upload_bytes):
        reasons.append("source_too_large")
    return mime, meta.size_bytes, reasons


def _boundary_snapshot(job, project, job_sources) -> ProcessingBoundarySnapshot:
    return ProcessingBoundarySnapshot(
        job=JobBoundarySnapshot(
            id=job.id,
            owner_user_id=job.owner_user_id,
            project_id=job.project_id,
            status=_enum_value(job.status),
            lease_owner_id=job.lease_owner_id,
            lease_generation=job.lease_generation,
            lease_expires_at=job.lease_expires_at,
            cancel_requested_at=job.cancel_requested_at,
        ),
        project=ProjectBoundarySnapshot(
            id=project.id if project else None,
            owner_user_id=project.owner_user_id if project else None,
            archived_at=project.archived_at if project else None,
        ),
        relations=tuple(_relation_source_identity(js) for js in sorted(job_sources, key=lambda item: item.position)),
    )


def _relation_source_identity(job_source) -> SourceRelationSnapshot:
    src = job_source.source
    return SourceRelationSnapshot(
        job_source_id=job_source.id,
        job_id=job_source.job_id,
        source_id=job_source.source_id,
        position=job_source.position,
        job_source_status=_enum_value(job_source.status),
        source_type=_enum_value(src.source_type) if src else None,
        project_id=src.project_id if src else None,
        drive_file_id=src.drive_file_id if src else None,
        s3_bucket=src.s3_bucket if src else None,
        s3_object_key=src.s3_object_key if src else None,
        reference_class=source_reference_class(src) if src else None,
        mime_type=normalize_source_mime_type(src.mime_type) if src else None,
        size_bytes=src.size_bytes if src else None,
        upload_status=_enum_value(src.upload_status) if src else None,
        deleted_at=src.deleted_at if src else None,
        expires_at=src.expires_at if src else None,
    )


def _revalidate(db, snapshot: ProcessingBoundarySnapshot, owner, generation, now) -> RevalidationResult:
    db.expire_all()
    job = _load_job(db, snapshot.job.id)
    lifecycle_reasons = _job_boundary_reasons(job, owner, generation, now)
    if job is None:
        return RevalidationResult(tuple(_dedupe(lifecycle_reasons)), frozenset())

    project = db.get(Project, job.project_id)
    if project is None or project.owner_user_id != job.owner_user_id or _project_identity_changed(project, snapshot):
        lifecycle_reasons.append("project_missing")
    elif project.archived_at is not None:
        lifecycle_reasons.append("project_archived")

    if _job_identity_changed(job, snapshot):
        lifecycle_reasons.append("project_missing")
    if job.lease_expires_at != snapshot.job.lease_expires_at and "lease_not_active" not in lifecycle_reasons:
        lifecycle_reasons.append("lease_not_active")

    current_relations = tuple(_relation_source_identity(js) for js in sorted(job.sources, key=lambda item: item.position))
    relation_recheck = _relation_revalidation(snapshot.relations, current_relations, now)
    return RevalidationResult(
        tuple(_dedupe(lifecycle_reasons + relation_recheck["top_level_reasons"])),
        frozenset(relation_recheck["changed_source_ids"]),
        relation_recheck["source_set_changed"],
    )


def _relation_revalidation(original: tuple[SourceRelationSnapshot, ...], current: tuple[SourceRelationSnapshot, ...], now: datetime):
    changed_source_ids: set[str] = set()
    top_level_reasons: list[str] = []
    original_by_relation_id = {item.job_source_id: item for item in original}
    current_by_relation_id = {item.job_source_id: item for item in current}
    source_set_changed = False

    if len(original) != len(current):
        return {
            "top_level_reasons": ["source_set_changed"],
            "changed_source_ids": changed_source_ids,
            "source_set_changed": True,
        }
    if len(original_by_relation_id) != len(original) or len(current_by_relation_id) != len(current):
        source_set_changed = True
    if set(original_by_relation_id) != set(current_by_relation_id):
        removed = set(original_by_relation_id) - set(current_by_relation_id)
        added = set(current_by_relation_id) - set(original_by_relation_id)
        source_set_changed = True
        if removed and not added:
            top_level_reasons.append("source_set_changed")
        elif added and not removed:
            top_level_reasons.append("source_set_changed")
        else:
            for relation_id in removed:
                original_relation = original_by_relation_id[relation_id]
                replacement = _matching_relation_replacement(original_relation, [current_by_relation_id[item] for item in added])
                if replacement is None:
                    top_level_reasons.append("source_set_changed")
                else:
                    changed_source_ids.add(original_relation.source_id)
    for original_relation in original:
        current_relation = current_by_relation_id.get(original_relation.job_source_id)
        if current_relation is None:
            continue
        if current_relation != original_relation:
            changed_source_ids.add(original_relation.source_id)
        if current_relation.upload_status != SourceUploadStatus.uploaded.value:
            changed_source_ids.add(original_relation.source_id)
        if current_relation.deleted_at is not None:
            changed_source_ids.add(original_relation.source_id)
        if is_source_expired(current_relation.expires_at, now):
            changed_source_ids.add(original_relation.source_id)

    if _ordered_relation_keys(original) != _ordered_relation_keys(current):
        for original_relation, current_relation in zip(original, current, strict=False):
            if original_relation.job_source_id == current_relation.job_source_id:
                changed_source_ids.add(original_relation.source_id)
            elif (
                original_relation.source_id == current_relation.source_id
                and original_relation.position == current_relation.position
            ):
                changed_source_ids.add(original_relation.source_id)
            else:
                source_set_changed = True
                top_level_reasons.append("source_set_changed")

    return {
        "top_level_reasons": _dedupe(top_level_reasons),
        "changed_source_ids": changed_source_ids,
        "source_set_changed": source_set_changed,
    }


def _matching_relation_replacement(original_relation: SourceRelationSnapshot, candidates: list[SourceRelationSnapshot]) -> SourceRelationSnapshot | None:
    matches = [
        item
        for item in candidates
        if item.source_id == original_relation.source_id and item.position == original_relation.position
    ]
    return matches[0] if len(matches) == 1 else None


def _ordered_relation_keys(relations: tuple[SourceRelationSnapshot, ...]) -> tuple[tuple[str, str, int], ...]:
    return tuple((item.job_source_id, item.source_id, item.position) for item in relations)


def _project_identity_changed(project, snapshot: ProcessingBoundarySnapshot) -> bool:
    return (
        project is None
        or project.id != snapshot.project.id
        or project.owner_user_id != snapshot.project.owner_user_id
    )


def _job_identity_changed(job, snapshot: ProcessingBoundarySnapshot) -> bool:
    return job.owner_user_id != snapshot.job.owner_user_id or job.project_id != snapshot.job.project_id


def _enum_value(value):
    return str(getattr(value, "value", value))


def _source_summary(snap, mime, size, reasons):
    deduped = _dedupe(reasons)
    return ProcessingSourceAvailabilitySourceSummary(snap["source_id"], snap["position"], snap["source_type"], snap["original_filename"], normalize_source_mime_type(mime), size, not deduped, deduped)


def _with_extra_reason(summary, reason):
    reasons = _dedupe(summary.blocking_reasons + [reason])
    return ProcessingSourceAvailabilitySourceSummary(summary.source_id, summary.position, summary.source_type, summary.original_filename, summary.mime_type, summary.size_bytes, False, reasons)


def _summary(job_id, project_id, now, generation, reasons, sources):
    deduped = _dedupe(reasons)
    return ProcessingSourceAvailabilitySummary(job_id, project_id, now, generation, not deduped, deduped, sources)


def _dedupe(values):
    out = []
    for value in values:
        if value not in out:
            out.append(value)
    return out
