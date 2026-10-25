from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from .job_claim_lease import is_lease_active, invalidate_job_lease
from .job_claim_readiness import build_claim_readiness
from .job_lifecycle import safe_failure_metadata_value
from .models import JobStatus, TranscriptionJob, TranscriptionJobOutput, TranscriptionJobSource, JobSourceStatus
from sqlalchemy import func
from .provider_part_checkpoints import delete_provider_part_checkpoints
from .job_cached_transcript import retire_cached_yandex_result
from .provider_usage_accounting import finalize_job_provider_accounting


class JobProcessingFailureReason(str, Enum):
    job_not_found = "job_not_found"
    job_not_queued = "job_not_queued"
    job_not_processing = "job_not_processing"
    job_not_ready = "job_not_ready"
    lease_not_owned = "lease_not_owned"
    lease_not_active = "lease_not_active"
    lease_active = "lease_active"
    cancellation_requested = "cancellation_requested"
    cancellation_not_requested = "cancellation_not_requested"


class JobProcessingError(RuntimeError):
    def __init__(self, reason: JobProcessingFailureReason):
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True)
class JobProcessingResult:
    job_id: str
    status: JobStatus
    attempt_count: int
    started_at: datetime | None
    cancel_requested_at: datetime | None
    lease_generation: int


def begin_job_processing(db: Session, *, job_id: str, lease_owner_id: str, lease_generation: int, now: datetime) -> JobProcessingResult:
    job = _locked_job(db, job_id)
    if job is None:
        raise JobProcessingError(JobProcessingFailureReason.job_not_found)
    if job.status != JobStatus.queued:
        raise JobProcessingError(JobProcessingFailureReason.job_not_queued)
    _require_active_owner(job, lease_owner_id, lease_generation, now)
    if not build_claim_readiness(job)["ready_for_future_claim"]:
        raise JobProcessingError(JobProcessingFailureReason.job_not_ready)
    if job.cancel_requested_at is not None:
        raise JobProcessingError(JobProcessingFailureReason.cancellation_requested)
    job.status = JobStatus.processing
    job.attempt_count = (job.attempt_count or 0) + 1
    if job.started_at is None:
        job.started_at = now
    job.finished_at = None
    job.error_code = None
    job.error_message = None
    job.retry_not_before_at = None
    job.automatic_retry_reason = None
    job.updated_at = now
    db.flush()
    return _result(job)


def request_job_cancellation(db: Session, *, job_id: str, now: datetime) -> tuple[JobProcessingResult, bool, str | None]:
    job = _locked_job(db, job_id)
    if job is None:
        raise JobProcessingError(JobProcessingFailureReason.job_not_found)
    changed = False
    event_type: str | None = None
    if job.status == JobStatus.queued:
        job.status = JobStatus.cancelled
        job.cancelled_at = now
        job.finished_at = now
        job.cancel_requested_at = None
        job.updated_at = now
        invalidate_job_lease(job)
        changed = True
        event_type = "job.cancelled"
        finalize_job_provider_accounting(db, job=job, now=now)
    elif job.status == JobStatus.processing and job.cancel_requested_at is None:
        job.cancel_requested_at = now
        job.updated_at = now
        changed = True
        event_type = "job.cancel_requested"
    if changed:
        if job.status == JobStatus.cancelled:
            delete_provider_part_checkpoints(db, job_id=job.id)
            retire_cached_yandex_result(db, job_id=job.id)
        db.flush()
    return _result(job), changed, event_type


def acknowledge_job_cancellation(db: Session, *, job_id: str, lease_owner_id: str, lease_generation: int, now: datetime) -> JobProcessingResult:
    job = _processing_job(db, job_id)
    if job.cancel_requested_at is None:
        raise JobProcessingError(JobProcessingFailureReason.cancellation_not_requested)
    _require_active_owner(job, lease_owner_id, lease_generation, now)
    job.status = JobStatus.cancelled
    job.cancelled_at = now
    job.finished_at = now
    job.updated_at = now
    delete_provider_part_checkpoints(db, job_id=job.id)
    retire_cached_yandex_result(db, job_id=job.id)
    invalidate_job_lease(job)
    finalize_job_provider_accounting(db, job=job, now=now)
    db.flush()
    return _result(job)


def fail_job_processing(db: Session, *, job_id: str, lease_owner_id: str, lease_generation: int, now: datetime, error_code: str | None, error_message: str | None) -> JobProcessingResult:
    from .job_notifications import ensure_terminal_notification_intents
    from .job_retry_recovery import schedule_automatic_retry_if_safe

    job = _processing_job(db, job_id)
    _require_active_owner(job, lease_owner_id, lease_generation, now)
    if job.cancel_requested_at is not None:
        raise JobProcessingError(JobProcessingFailureReason.cancellation_requested)
    job.status = JobStatus.failed
    job.finished_at = now
    job.updated_at = now
    job.error_code = safe_failure_metadata_value(error_code)
    job.error_message = safe_failure_metadata_value(error_message)
    invalidate_job_lease(job)
    db.flush()
    if schedule_automatic_retry_if_safe(db, job=job, now=now):
        return _result(job)
    finalize_job_provider_accounting(db, job=job, now=now)
    ensure_terminal_notification_intents(db, job=job, now=now)
    db.flush()
    return _result(job)


def recover_expired_processing_job(db: Session, *, job_id: str, now: datetime) -> JobProcessingResult:
    from .job_retry_recovery import compute_expired_recovery_readiness
    from .job_notifications import ensure_terminal_notification_intents
    job = _processing_job(db, job_id)
    if is_lease_active(job, now):
        raise JobProcessingError(JobProcessingFailureReason.lease_active)
    if job.cancel_requested_at is not None:
        job.status = JobStatus.cancelled
        job.cancelled_at = now
        job.finished_at = now
        delete_provider_part_checkpoints(db, job_id=job.id)
        retire_cached_yandex_result(db, job_id=job.id)
    else:
        rel_ids=[r.id for r in db.execute(select(TranscriptionJobSource).where(TranscriptionJobSource.job_id==job.id, TranscriptionJobSource.status!=JobSourceStatus.skipped)).scalars().all()]
        output_count = db.execute(select(func.count(TranscriptionJobOutput.id)).where(TranscriptionJobOutput.job_id==job.id, TranscriptionJobOutput.job_source_id.in_(rel_ids or ["__none__"]))).scalar_one()
        if rel_ids and int(output_count)==len(rel_ids):
            job.status = JobStatus.completed
            job.finished_at = now
            job.error_code = None
            job.error_message = None
        else:
            ready = compute_expired_recovery_readiness(db, job, now=now)
            if ready.available:
                job.status = JobStatus.queued
                job.finished_at = None
                job.error_code = None
                job.error_message = None
                job.retry_not_before_at = None
                job.automatic_retry_reason = None
            else:
                job.status = JobStatus.failed
                job.finished_at = now
                mapping={"attempt_limit_reached":"retry_attempt_limit_reached","provider_outcome_uncertain":"provider_outcome_uncertain","provider_result_lost":"provider_result_lost","output_reconciliation_required":"output_reconciliation_required"}
                job.error_code = mapping.get(ready.reason.value, "retry_recovery_state_unknown")
                job.error_message = job.error_code
    job.updated_at = now
    if job.status in {JobStatus.cancelled, JobStatus.failed, JobStatus.completed}:
        finalize_job_provider_accounting(db, job=job, now=now)
    if job.status in {JobStatus.failed, JobStatus.completed}:
        ensure_terminal_notification_intents(db, job=job, now=now)
    invalidate_job_lease(job)
    db.flush()
    return _result(job)


def _locked_job(db: Session, job_id: str) -> TranscriptionJob | None:
    return db.execute(select(TranscriptionJob).where(TranscriptionJob.id == job_id).with_for_update()).scalar_one_or_none()


def _processing_job(db: Session, job_id: str) -> TranscriptionJob:
    job = _locked_job(db, job_id)
    if job is None:
        raise JobProcessingError(JobProcessingFailureReason.job_not_found)
    if job.status != JobStatus.processing:
        raise JobProcessingError(JobProcessingFailureReason.job_not_processing)
    return job


def _require_active_owner(job: TranscriptionJob, owner: str, generation: int, now: datetime) -> None:
    if job.lease_owner_id != owner or job.lease_generation != generation:
        raise JobProcessingError(JobProcessingFailureReason.lease_not_owned)
    if not is_lease_active(job, now):
        raise JobProcessingError(JobProcessingFailureReason.lease_not_active)


def _result(job: TranscriptionJob) -> JobProcessingResult:
    return JobProcessingResult(job.id, job.status, job.attempt_count or 0, job.started_at, job.cancel_requested_at, job.lease_generation)
