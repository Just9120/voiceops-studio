from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
from uuid import uuid4

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from .audit import audit
from .diagnostics import write_diagnostic_event
from .job_retry_recovery import compute_explicit_retry_readiness
from .models import (
    AudioPreparationJob,
    AudioPreparationJobInput,
    AudioPreparationStatus,
    JobSourceStatus,
    JobStatus,
    Project,
    Source,
    SourceStorageCleanupStatus,
    SourceType,
    SourceUploadProtocol,
    SourceUploadStatus,
    TranscriptionJob,
    TranscriptionJobOutput,
    TranscriptionJobSource,
)
from .source_storage import (
    get_source_storage,
    reference_storage_bucket,
    reference_storage_isolation_configured,
    reference_storage_settings,
    source_reference_class,
)

SOURCE_CLEANUP_LEASE_TTL = timedelta(minutes=5)
SOURCE_CLEANUP_RETRY_DELAY = timedelta(minutes=10)


STORAGE_CLEANUP_ERROR_CODES = {"storage_unavailable", "storage_delete_failed", "storage_identity_mismatch"}


class SourceDeletionReason(str, Enum):
    available = "available"
    queued_job_uses_source = "queued_job_uses_source"
    processing_job_uses_source = "processing_job_uses_source"
    retryable_failed_job_uses_source = "retryable_failed_job_uses_source"
    audio_preparation_uses_source = "audio_preparation_uses_source"
    project_unavailable = "project_unavailable"
    source_already_deleted = "source_already_deleted"
    unsupported_source_state = "unsupported_source_state"


@dataclass(frozen=True)
class SourceDeletionResult:
    ok: bool
    reason: SourceDeletionReason
    source_state: str
    storage_cleanup: str


@dataclass(frozen=True)
class BulkSourceDeletionPreview:
    eligible_ids: tuple[str, ...]
    preview_token: str
    blocked_reasons: dict[str, int]
    listed_count: int
    hidden_expired_count: int
    eligible_bytes: int
    eligible_unknown_size_count: int
    blocked_bytes: int
    blocked_unknown_size_count: int
    selection_ids: tuple[str, ...] | None = None

    def payload(self) -> dict:
        return {
            "preview_token": self.preview_token,
            "eligible_count": len(self.eligible_ids),
            "listed_count": self.listed_count,
            "hidden_expired_count": self.hidden_expired_count,
            "eligible_bytes": self.eligible_bytes,
            "eligible_unknown_size_count": self.eligible_unknown_size_count,
            "blocked_count": sum(self.blocked_reasons.values()),
            "blocked_bytes": self.blocked_bytes,
            "blocked_unknown_size_count": self.blocked_unknown_size_count,
            "blocked_reasons": dict(sorted(self.blocked_reasons.items())),
            "google_drive_files_deleted": 0,
            **({"selection_ids": list(self.selection_ids)} if self.selection_ids is not None else {}),
        }


@dataclass(frozen=True)
class SourceCleanupClaim:
    source_id: str
    owner_id: str
    generation: int
    s3_bucket: str
    s3_object_key: str
    reference_class: str
    attempt_count: int
    upload_protocol: str = SourceUploadProtocol.single_put.value
    multipart_upload_id: str | None = None


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def is_source_expired(source: Source, now: datetime) -> bool:
    return bool(source.source_type == SourceType.local_upload and source.expires_at is not None and _aware(source.expires_at) <= _aware(now))


def is_source_listed_for_browser(source: Source, now: datetime) -> bool:
    if source.source_type != SourceType.local_upload:
        return True
    return bool(
        source.upload_status != SourceUploadStatus.expired
        and (source.expires_at is None or _aware(source.expires_at) > _aware(now))
    )


def browser_cleanup_status(source: Source) -> str:
    status = source.storage_cleanup_status
    if status == SourceStorageCleanupStatus.not_applicable:
        return "not_applicable"
    if status == SourceStorageCleanupStatus.completed:
        return "completed"
    return "pending"


def _lock_source(db: Session, source_id: str) -> Source | None:
    return db.execute(select(Source).where(Source.id == source_id).with_for_update()).scalar_one_or_none()


def _referencing_jobs(db: Session, source_id: str, *, lock: bool) -> list[TranscriptionJob]:
    stmt = (
        select(TranscriptionJob)
        .join(TranscriptionJobSource, TranscriptionJobSource.job_id == TranscriptionJob.id)
        .where(TranscriptionJobSource.source_id == source_id, TranscriptionJobSource.status != JobSourceStatus.skipped)
        .order_by(TranscriptionJob.created_at.asc(), TranscriptionJob.id.asc())
    )
    if lock:
        stmt = stmt.with_for_update()
    return list(db.execute(stmt).scalars().all())


def _active_audio_reference_predicate(source_id, now):
    input_reference = exists(select(AudioPreparationJobInput.job_id).where(
        AudioPreparationJobInput.job_id == AudioPreparationJob.id,
        AudioPreparationJobInput.source_id == source_id,
    ).correlate(AudioPreparationJob, Source))
    return or_(
        and_(input_reference, AudioPreparationJob.status.in_((
            AudioPreparationStatus.preview_queued, AudioPreparationStatus.analyzing,
            AudioPreparationStatus.preview_ready, AudioPreparationStatus.queued, AudioPreparationStatus.processing,
        ))),
        and_(input_reference, AudioPreparationJob.status == AudioPreparationStatus.completed,
            or_(AudioPreparationJob.current_stage.in_(("google_drive_export_queued", "google_drive_upload")),
                and_(AudioPreparationJob.current_stage.in_(("audio_download_queued", "audio_download_rendering")),
                    AudioPreparationJob.download_slot == 1,
                    or_(AudioPreparationJob.download_expires_at > _aware(now).replace(tzinfo=None),
                        and_(AudioPreparationJob.lease_owner_id.is_not(None),
                             AudioPreparationJob.lease_expires_at > _aware(now).replace(tzinfo=None)))))),
        and_(AudioPreparationJob.output_source_id == source_id,
            AudioPreparationJob.status == AudioPreparationStatus.completed,
            AudioPreparationJob.current_stage.in_(("google_drive_export_queued", "google_drive_upload"))),
    )


def _active_audio_preparation_references(db: Session, source_id: str, *, lock: bool, now: datetime) -> list[AudioPreparationJob]:
    stmt = select(AudioPreparationJob).where(_active_audio_reference_predicate(source_id, now)).order_by(AudioPreparationJob.created_at.asc(), AudioPreparationJob.id.asc())
    if lock:
        stmt = stmt.with_for_update()
    return list(db.execute(stmt).scalars().all())



def _no_processing_reference_predicate():
    return ~exists(
        select(1)
        .select_from(TranscriptionJobSource)
        .join(TranscriptionJob, TranscriptionJob.id == TranscriptionJobSource.job_id)
        .where(
            TranscriptionJobSource.source_id == Source.id,
            TranscriptionJobSource.status != JobSourceStatus.skipped,
            TranscriptionJob.status == JobStatus.processing,
        )
    )

def _project_owner_id(db: Session, project_id: str) -> str | None:
    project = db.get(Project, project_id)
    return project.owner_user_id if project is not None else None


def _no_active_audio_reference_predicate(now):
    return ~exists(select(AudioPreparationJob.id).where(_active_audio_reference_predicate(Source.id, now)))


def deletion_readiness(db: Session, source: Source, *, now: datetime, locked_jobs: list[TranscriptionJob] | None = None, discard_failed_retry: bool = False) -> SourceDeletionReason:
    if source.deleted_at is not None or source.upload_status == SourceUploadStatus.deleted:
        return SourceDeletionReason.source_already_deleted
    if source.source_type not in {SourceType.local_upload, SourceType.google_drive, SourceType.yandex_disk}:
        return SourceDeletionReason.unsupported_source_state
    for job in locked_jobs if locked_jobs is not None else _referencing_jobs(db, source.id, lock=False):
        if job.status == JobStatus.queued:
            return SourceDeletionReason.queued_job_uses_source
        if job.status == JobStatus.processing:
            return SourceDeletionReason.processing_job_uses_source
        if not discard_failed_retry and job.status == JobStatus.failed and compute_explicit_retry_readiness(db, job, now=now).available:
            return SourceDeletionReason.retryable_failed_job_uses_source
    if _active_audio_preparation_references(db, source.id, lock=False, now=now):
        return SourceDeletionReason.audio_preparation_uses_source
    return SourceDeletionReason.available


def validate_bulk_source_selection(source_ids: list[str] | None) -> list[str] | None:
    if source_ids is None:
        return None
    if (not 1 <= len(source_ids) <= 50 or any(not isinstance(value, str) or not 1 <= len(value) <= 36 for value in source_ids)
            or len(set(source_ids)) != len(source_ids)):
        raise ValueError("invalid_source_selection")
    return sorted(source_ids)


def bulk_source_deletion_preview(
    db: Session,
    *,
    owner_user_id: str,
    project_id: str,
    now: datetime,
    lock_sources: bool = False,
    source_ids: list[str] | None = None,
) -> BulkSourceDeletionPreview | None:
    project = db.get(Project, project_id)
    if project is None or project.owner_user_id != owner_user_id or project.archived_at is not None:
        return None
    stmt = (
        select(Source)
        .where(
            Source.project_id == project_id,
            Source.deleted_at.is_(None),
            Source.upload_status != SourceUploadStatus.deleted,
        )
        .order_by(Source.created_at.asc(), Source.id.asc())
    )
    selection = validate_bulk_source_selection(source_ids)
    if selection is not None:
        stmt = stmt.where(Source.id.in_(selection))
    if lock_sources:
        stmt = stmt.with_for_update()
    sources = list(db.execute(stmt).scalars().all())
    eligible_ids: list[str] = []
    blocked_reasons: dict[str, int] = {}
    listed_count = hidden_expired_count = 0
    eligible_bytes = blocked_bytes = 0
    eligible_unknown = blocked_unknown = 0
    preview_entries: list[dict[str, str]] = []
    for source in sources:
        is_listed = is_source_listed_for_browser(source, now)
        if is_listed:
            listed_count += 1
        else:
            hidden_expired_count += 1
        reason = deletion_readiness(db, source, now=now, discard_failed_retry=True)
        preview_entries.append(
            {
                "source_id": source.id,
                "reason": reason.value,
                "visibility": "listed" if is_listed else "hidden_expired",
                "updated_at": _aware(source.updated_at).isoformat(),
            }
        )
        eligible = reason == SourceDeletionReason.available
        if eligible:
            eligible_ids.append(source.id)
        else:
            blocked_reasons[reason.value] = blocked_reasons.get(reason.value, 0) + 1
        if source.size_bytes is None:
            if eligible:
                eligible_unknown += 1
            else:
                blocked_unknown += 1
        elif eligible:
            eligible_bytes += source.size_bytes
        else:
            blocked_bytes += source.size_bytes
    return BulkSourceDeletionPreview(
        tuple(eligible_ids),
        hashlib.sha256(
            json.dumps(
                {
                    "owner_user_id": owner_user_id,
                    "project_id": project_id,
                    "entries": preview_entries,
                    **({"source_ids": selection} if selection is not None else {}),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        blocked_reasons,
        listed_count,
        hidden_expired_count,
        eligible_bytes,
        eligible_unknown,
        blocked_bytes,
        blocked_unknown,
        tuple(selection) if selection is not None else None,
    )


def request_source_deletion(db: Session, *, owner_user_id: str, source_id: str, now: datetime, discard_failed_retry: bool = False) -> SourceDeletionResult | None:
    source = _lock_source(db, source_id)
    if source is None:
        return None
    project = db.get(Project, source.project_id)
    if project is None or project.owner_user_id != owner_user_id or project.archived_at is not None:
        return None
    jobs = _referencing_jobs(db, source.id, lock=True)
    _active_audio_preparation_references(db, source.id, lock=True, now=now)
    already_deleted = source.deleted_at is not None or source.upload_status == SourceUploadStatus.deleted
    reason = deletion_readiness(db, source, now=now, locked_jobs=jobs, discard_failed_retry=discard_failed_retry)
    if reason not in {SourceDeletionReason.available, SourceDeletionReason.source_already_deleted}:
        audit(db, "source.deletion_blocked", actor_user_id=owner_user_id, subject_user_id=owner_user_id, outcome="rejected", project_id=project.id, blocker=reason.value)
        write_diagnostic_event(owner_user_id=owner_user_id, component="api", event_code="SOURCE_DELETION_BLOCKED", project_id=project.id, metadata={"blocker": reason.value, "source_type": source.source_type.value, "boundary": "source_deletion"})
        db.flush()
        return SourceDeletionResult(False, reason, source.upload_status.value, browser_cleanup_status(source))
    prior_upload_status = source.upload_status
    if not already_deleted:
        source.deleted_at = now
        source.delete_reason = "user_deleted"
        source.upload_status = SourceUploadStatus.deleted
        source.updated_at = now
    elif source.delete_reason is None:
        source.delete_reason = "user_deleted"
    if source.source_type in {SourceType.google_drive, SourceType.yandex_disk}:
        source.storage_cleanup_status = SourceStorageCleanupStatus.not_applicable
        source.storage_cleanup_not_before_at = None
    else:
        source.storage_cleanup_status = SourceStorageCleanupStatus.pending if source.storage_cleanup_status != SourceStorageCleanupStatus.completed else SourceStorageCleanupStatus.completed
        source.storage_cleanup_requested_at = source.storage_cleanup_requested_at or now
        not_before = now
        if prior_upload_status == SourceUploadStatus.pending and source.expires_at is not None:
            not_before = max(_aware(now), _aware(source.expires_at)).replace(tzinfo=now.tzinfo)
        source.storage_cleanup_not_before_at = source.storage_cleanup_not_before_at or not_before
        source.storage_cleanup_error_code = None
    if not already_deleted:
        audit(db, "source.deletion_requested", actor_user_id=owner_user_id, subject_user_id=owner_user_id, project_id=project.id, deletion_reason="user_deleted")
        audit(db, "source.deleted", actor_user_id=owner_user_id, subject_user_id=owner_user_id, project_id=project.id, deletion_reason="user_deleted")
        write_diagnostic_event(owner_user_id=owner_user_id, component="api", event_code="SOURCE_DELETION_REQUESTED", project_id=project.id, metadata={"source_type": source.source_type.value, "deletion_reason": "user_deleted", "boundary": "source_deletion"})
        write_diagnostic_event(owner_user_id=owner_user_id, component="api", event_code="SOURCE_DELETION_COMPLETED", project_id=project.id, metadata={"source_type": source.source_type.value, "deletion_reason": "user_deleted", "cleanup_outcome": browser_cleanup_status(source), "boundary": "source_deletion"})
    db.flush()
    return SourceDeletionResult(True, SourceDeletionReason.available, source.upload_status.value, browser_cleanup_status(source))


def mark_one_expired_source_for_cleanup(db: Session, *, now: datetime) -> bool:
    src = db.execute(
        select(Source)
        .where(
            Source.source_type == SourceType.local_upload,
            Source.deleted_at.is_(None),
            Source.expires_at.is_not(None),
            Source.expires_at <= now,
            Source.upload_status != SourceUploadStatus.expired,
            _no_processing_reference_predicate(),
            _no_active_audio_reference_predicate(now),
        )
        .order_by(Source.expires_at.asc(), Source.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if src is None:
        return False
    # Defence in depth for races between candidate selection and source mutation.
    if any(job.status == JobStatus.processing for job in _referencing_jobs(db, src.id, lock=True)):
        return False
    src.upload_status = SourceUploadStatus.expired
    src.delete_reason = "retention_expired"
    src.storage_cleanup_status = SourceStorageCleanupStatus.pending
    src.storage_cleanup_requested_at = src.storage_cleanup_requested_at or now
    src.storage_cleanup_not_before_at = src.storage_cleanup_not_before_at or now
    src.updated_at = now
    audit(db, "source.retention_expired", project_id=src.project_id, deletion_reason="retention_expired")
    owner_id = _project_owner_id(db, src.project_id)
    if owner_id:
        write_diagnostic_event(owner_user_id=owner_id, component="worker", event_code="SOURCE_RETENTION_EXPIRED", project_id=src.project_id, metadata={"source_type": src.source_type.value, "deletion_reason": "retention_expired", "boundary": "source_cleanup"})
    db.flush()
    return True


def mark_one_fully_exported_source_for_cleanup(db: Session, *, now: datetime) -> bool:
    """Retire enrolled device copies only when every requested document exists.

    Source row locking fences new job admission. Historical sources and audio
    preparation references are never enrolled implicitly.
    """
    from .transcript_catalog import TRANSCRIPT_OUTPUT_KINDS
    document = exists(select(TranscriptionJobOutput.id).where(
        TranscriptionJobOutput.job_source_id == TranscriptionJobSource.id,
        TranscriptionJobOutput.job_id == TranscriptionJobSource.job_id,
        TranscriptionJobOutput.output_kind.in_(TRANSCRIPT_OUTPUT_KINDS),
        TranscriptionJobOutput.document_character_count > 0,
        TranscriptionJobOutput.document_id != "",
    ))
    relations = select(TranscriptionJobSource.id).join(TranscriptionJob, TranscriptionJob.id == TranscriptionJobSource.job_id).where(
        TranscriptionJobSource.source_id == Source.id,
        TranscriptionJobSource.status != JobSourceStatus.skipped,
    )
    unmet = relations.where(or_(TranscriptionJob.status != JobStatus.completed, TranscriptionJob.project_id != Source.project_id, ~document))
    src = db.execute(select(Source).where(
        Source.source_type == SourceType.local_upload,
        Source.reference_class == "transcription",
        Source.delete_after_transcripts.is_(True),
        Source.upload_status == SourceUploadStatus.uploaded,
        Source.deleted_at.is_(None),
        exists(relations), ~exists(unmet),
        _no_active_audio_reference_predicate(now),
    ).order_by(Source.created_at, Source.id).limit(1).with_for_update(skip_locked=True)).scalar_one_or_none()
    if src is None:
        return False
    # Both query and readback are conservative: failed/cancelled/queued jobs and
    # active audio leases preserve the source, even if another output exists.
    if _active_audio_preparation_references(db, src.id, lock=False, now=now):
        return False
    if db.execute(unmet.where(TranscriptionJobSource.source_id == src.id).correlate(None).limit(1)).first() is not None:
        return False
    src.deleted_at = now
    src.delete_reason = "all_transcripts_exported"
    src.upload_status = SourceUploadStatus.deleted
    src.storage_cleanup_status = SourceStorageCleanupStatus.pending
    src.storage_cleanup_requested_at = now
    src.storage_cleanup_not_before_at = now
    src.storage_cleanup_error_code = None
    src.updated_at = now
    audit(db, "source.all_transcripts_exported", project_id=src.project_id, deletion_reason="all_transcripts_exported")
    db.flush()
    return True


def claim_next_source_cleanup(db: Session, *, owner_id: str, now: datetime) -> SourceCleanupClaim | None:
    owner = (owner_id or "")[:128] or f"source-cleanup-{uuid4().hex}"
    stale = or_(Source.storage_cleanup_owner_id.is_(None), Source.storage_cleanup_lease_expires_at.is_(None), Source.storage_cleanup_lease_expires_at <= now)
    src = db.execute(
        select(Source)
        .where(
            Source.source_type == SourceType.local_upload,
            Source.storage_cleanup_status.in_([SourceStorageCleanupStatus.pending, SourceStorageCleanupStatus.failed]),
            Source.storage_cleanup_not_before_at <= now,
            Source.s3_bucket.is_not(None),
            Source.s3_bucket != "",
            Source.s3_object_key.is_not(None),
            Source.s3_object_key != "",
            stale,
            or_(Source.deleted_at.is_not(None), Source.expires_at <= now),
            _no_processing_reference_predicate(),
            _no_active_audio_reference_predicate(now),
        )
        .order_by(Source.storage_cleanup_not_before_at.asc(), Source.created_at.asc(), Source.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if src is None:
        return None
    # Defence in depth for races between candidate selection and source mutation.
    if any(job.status == JobStatus.processing for job in _referencing_jobs(db, src.id, lock=True)):
        return None
    src.storage_cleanup_generation = int(src.storage_cleanup_generation or 0) + 1
    src.storage_cleanup_owner_id = owner
    src.storage_cleanup_claimed_at = now
    src.storage_cleanup_lease_expires_at = now + SOURCE_CLEANUP_LEASE_TTL
    src.storage_cleanup_attempt_count = int(src.storage_cleanup_attempt_count or 0) + 1
    src.storage_cleanup_status = SourceStorageCleanupStatus.pending
    src.storage_cleanup_error_code = None
    owner_user_id = _project_owner_id(db, src.project_id)
    if owner_user_id:
        write_diagnostic_event(owner_user_id=owner_user_id, component="worker", event_code="SOURCE_STORAGE_CLEANUP_STARTED", project_id=src.project_id, metadata={"source_type": src.source_type.value, "cleanup_attempt": src.storage_cleanup_attempt_count, "boundary": "source_cleanup"})
    db.flush()
    return SourceCleanupClaim(
        src.id,
        owner,
        src.storage_cleanup_generation,
        src.s3_bucket or "",
        src.s3_object_key or "",
        source_reference_class(src),
        src.storage_cleanup_attempt_count,
        src.upload_protocol,
        src.multipart_upload_id,
    )


def finalize_source_cleanup(db: Session, *, claim: SourceCleanupClaim, now: datetime, success: bool, error_code: str | None = None) -> bool:
    src = _lock_source(db, claim.source_id)
    if (
        src is None
        or src.storage_cleanup_status != SourceStorageCleanupStatus.pending
        or src.storage_cleanup_owner_id != claim.owner_id
        or src.storage_cleanup_generation != claim.generation
        or src.s3_bucket != claim.s3_bucket
        or src.s3_object_key != claim.s3_object_key
        or source_reference_class(src) != claim.reference_class
        or src.upload_protocol != claim.upload_protocol
        or src.multipart_upload_id != claim.multipart_upload_id
    ):
        return False
    owner_user_id = _project_owner_id(db, src.project_id)
    if success:
        src.storage_cleanup_status = SourceStorageCleanupStatus.completed
        src.storage_cleanup_completed_at = now
        src.storage_cleanup_error_code = None
        src.s3_bucket = None
        src.s3_object_key = None
        audit(db, "source.storage_cleanup_completed", subject_user_id=owner_user_id, project_id=src.project_id, cleanup_outcome="completed", cleanup_attempt=src.storage_cleanup_attempt_count)
        if owner_user_id:
            write_diagnostic_event(owner_user_id=owner_user_id, component="worker", event_code="SOURCE_STORAGE_CLEANUP_COMPLETED", project_id=src.project_id, metadata={"cleanup_outcome": "completed", "cleanup_attempt": src.storage_cleanup_attempt_count, "boundary": "source_cleanup"})
    else:
        src.storage_cleanup_status = SourceStorageCleanupStatus.failed
        src.storage_cleanup_error_code = error_code if error_code in STORAGE_CLEANUP_ERROR_CODES else "storage_delete_failed"
        src.storage_cleanup_not_before_at = now + SOURCE_CLEANUP_RETRY_DELAY
        audit(db, "source.storage_cleanup_failed", subject_user_id=owner_user_id, outcome="failed", project_id=src.project_id, cleanup_outcome="failed", cleanup_attempt=src.storage_cleanup_attempt_count)
        if owner_user_id:
            write_diagnostic_event(owner_user_id=owner_user_id, component="worker", event_code="SOURCE_STORAGE_CLEANUP_FAILED", project_id=src.project_id, metadata={"cleanup_outcome": "failed", "cleanup_attempt": src.storage_cleanup_attempt_count, "boundary": "source_cleanup"})
    src.storage_cleanup_owner_id = None
    src.storage_cleanup_claimed_at = None
    src.storage_cleanup_lease_expires_at = None
    src.updated_at = now
    db.flush()
    return True


def run_one_source_cleanup(db: Session, *, settings, owner_id: str, now: datetime, storage_factory=None, should_stop=None) -> bool:
    if should_stop and should_stop():
        return False
    mark_one_expired_source_for_cleanup(db, now=now)
    mark_one_fully_exported_source_for_cleanup(db, now=now)
    db.commit()
    if should_stop and should_stop():
        return False
    claim = claim_next_source_cleanup(db, owner_id=owner_id, now=now)
    if claim is None:
        db.rollback()
        return False
    db.commit()
    ok = True
    code = None
    try:
        configured_bucket = reference_storage_bucket(settings, claim.reference_class)
        if not reference_storage_isolation_configured(settings):
            ok = False
            code = "storage_unavailable"
        elif claim.s3_bucket != configured_bucket:
            ok = False
            code = "storage_identity_mismatch"
        else:
            storage=(storage_factory or get_source_storage)(
                reference_storage_settings(settings, claim.reference_class)
            )
            if claim.upload_protocol == SourceUploadProtocol.multipart.value and claim.multipart_upload_id:
                storage.abort_multipart_upload(claim.s3_object_key,claim.multipart_upload_id)
                if not storage.multipart_upload_absent(claim.s3_object_key,claim.multipart_upload_id):
                    raise RuntimeError("multipart_abort_unconfirmed")
            if not storage.delete_object_verified(claim.s3_object_key,bucket=claim.s3_bucket):
                raise RuntimeError("storage_delete_unconfirmed")
    except Exception as exc:
        ok = False
        code = "storage_unavailable" if type(exc).__name__ in {"SourceStorageError", "EndpointConnectionError"} else "storage_delete_failed"
    finalize_source_cleanup(db, claim=claim, now=now, success=ok, error_code=code)
    db.commit()
    return True
