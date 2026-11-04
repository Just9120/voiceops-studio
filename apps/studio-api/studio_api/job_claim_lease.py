from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .job_claim_readiness import build_claim_readiness
from .models import JobStatus, TranscriptionJob

MAX_LEASE_OWNER_ID_LENGTH = 128
MAX_LEASE_TTL = timedelta(hours=24)


class JobLeaseFailureReason(str, Enum):
    invalid_owner = "invalid_owner"
    invalid_ttl = "invalid_ttl"
    job_not_found = "job_not_found"
    job_not_queued = "job_not_queued"
    job_not_ready = "job_not_ready"
    lease_active = "lease_active"
    lease_not_owned = "lease_not_owned"
    lease_not_active = "lease_not_active"
    lease_not_releasable = "lease_not_releasable"


class JobLeaseError(RuntimeError):
    def __init__(self, reason: JobLeaseFailureReason):
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True)
class JobLeaseHandle:
    job_id: str
    lease_owner_id: str
    lease_generation: int
    claimed_at: datetime
    lease_expires_at: datetime


def is_lease_active(job: TranscriptionJob, now: datetime) -> bool:
    if not job.lease_owner_id or not job.lease_expires_at:
        return False
    return _as_utc_aware(job.lease_expires_at) > _as_utc_aware(now)


def _as_utc_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def acquire_next_ready_job_lease(
    db: Session,
    *,
    lease_owner_id: str,
    now: datetime,
    lease_ttl: timedelta,
) -> JobLeaseHandle | None:
    owner = _validated_owner(lease_owner_id)
    expires_at = now + _validated_ttl(lease_ttl)
    excluded_job_ids: set[str] = set()
    while True:
        filters = [
            TranscriptionJob.status == JobStatus.queued,
            # The PC performs local inference. VPS can only export its accepted
            # encrypted result; it must never seize a pending local execution.
            or_(TranscriptionJob.provider.is_(None), TranscriptionJob.provider != "nemotron",
                TranscriptionJob.local_result_ready_at.is_not(None)),
            or_(
                TranscriptionJob.retry_not_before_at.is_(None),
                TranscriptionJob.retry_not_before_at <= now,
            ),
            or_(
                TranscriptionJob.lease_owner_id.is_(None),
                TranscriptionJob.lease_expires_at.is_(None),
                TranscriptionJob.lease_expires_at <= now,
            ),
        ]
        if excluded_job_ids:
            filters.append(TranscriptionJob.id.not_in(excluded_job_ids))

        job = db.execute(
            select(TranscriptionJob)
            .where(*filters)
            .order_by(TranscriptionJob.created_at.asc(), TranscriptionJob.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if job is None:
            return None
        if job.status != JobStatus.queued or is_lease_active(job, now):
            excluded_job_ids.add(job.id)
            continue
        if not build_claim_readiness(job, now=now)["ready_for_future_claim"]:
            excluded_job_ids.add(job.id)
            continue
        return _apply_job_lease(db, job=job, owner=owner, claimed_at=now, expires_at=expires_at)


def acquire_job_lease(
    db: Session,
    *,
    job_id: str,
    lease_owner_id: str,
    now: datetime,
    lease_ttl: timedelta,
    local_device_id: str | None = None,
) -> JobLeaseHandle:
    owner = _validated_owner(lease_owner_id)
    expires_at = now + _validated_ttl(lease_ttl)
    job = _locked_job(db, job_id)
    if job is None:
        raise JobLeaseError(JobLeaseFailureReason.job_not_found)
    if job.status != JobStatus.queued:
        raise JobLeaseError(JobLeaseFailureReason.job_not_queued)
    if job.provider == "nemotron" and job.local_result_ready_at is None:
        if local_device_id is None or job.local_device_id != local_device_id or owner != "local:" + local_device_id:
            raise JobLeaseError(JobLeaseFailureReason.job_not_ready)
    elif local_device_id is not None:
        raise JobLeaseError(JobLeaseFailureReason.job_not_ready)
    if job.retry_not_before_at is not None and _as_utc_aware(job.retry_not_before_at) > _as_utc_aware(now):
        raise JobLeaseError(JobLeaseFailureReason.job_not_ready)
    if not build_claim_readiness(job, now=now)["ready_for_future_claim"]:
        raise JobLeaseError(JobLeaseFailureReason.job_not_ready)
    if is_lease_active(job, now):
        raise JobLeaseError(JobLeaseFailureReason.lease_active)

    return _apply_job_lease(db, job=job, owner=owner, claimed_at=now, expires_at=expires_at)


def renew_job_lease(
    db: Session,
    *,
    job_id: str,
    lease_owner_id: str,
    lease_generation: int,
    now: datetime,
    lease_ttl: timedelta,
) -> JobLeaseHandle:
    owner = _validated_owner(lease_owner_id)
    expires_at = now + _validated_ttl(lease_ttl)
    job = _locked_job(db, job_id)
    if job is None:
        raise JobLeaseError(JobLeaseFailureReason.job_not_found)
    if job.status not in {JobStatus.queued, JobStatus.processing}:
        raise JobLeaseError(JobLeaseFailureReason.job_not_queued)
    _require_current_owner(job, owner, lease_generation)
    if not is_lease_active(job, now):
        raise JobLeaseError(JobLeaseFailureReason.lease_not_active)

    job.lease_expires_at = expires_at
    db.flush()
    return _handle(job)


def release_job_lease(
    db: Session, *, job_id: str, lease_owner_id: str, lease_generation: int) -> bool:
    owner = _validated_owner(lease_owner_id)
    job = _locked_job(db, job_id)
    if job is None:
        raise JobLeaseError(JobLeaseFailureReason.job_not_found)
    _require_current_owner(job, owner, lease_generation)
    if job.status == JobStatus.processing:
        raise JobLeaseError(JobLeaseFailureReason.lease_not_releasable)
    if job.lease_expires_at is None:
        raise JobLeaseError(JobLeaseFailureReason.lease_not_active)
    job.lease_owner_id = None
    job.lease_expires_at = None
    db.flush()
    return True


def invalidate_job_lease(job: TranscriptionJob) -> None:
    job.lease_owner_id = None
    job.lease_expires_at = None


def _apply_job_lease(
    db: Session,
    *,
    job: TranscriptionJob,
    owner: str,
    claimed_at: datetime,
    expires_at: datetime,
) -> JobLeaseHandle:
    job.lease_generation = (job.lease_generation or 0) + 1
    job.lease_owner_id = owner
    job.claimed_at = claimed_at
    job.lease_expires_at = expires_at
    db.flush()
    return _handle(job)


def _locked_job(db: Session, job_id: str) -> TranscriptionJob | None:
    return db.execute(select(TranscriptionJob).where(TranscriptionJob.id == job_id).with_for_update()).scalar_one_or_none()


def _validated_owner(value: str) -> str:
    owner = value.strip() if isinstance(value, str) else ""
    if not owner or len(owner) > MAX_LEASE_OWNER_ID_LENGTH:
        raise JobLeaseError(JobLeaseFailureReason.invalid_owner)
    return owner


def _validated_ttl(value: timedelta) -> timedelta:
    if value <= timedelta(0) or value > MAX_LEASE_TTL:
        raise JobLeaseError(JobLeaseFailureReason.invalid_ttl)
    return value


def _require_current_owner(job: TranscriptionJob, owner: str, generation: int) -> None:
    if job.lease_owner_id != owner or job.lease_generation != generation:
        raise JobLeaseError(JobLeaseFailureReason.lease_not_owned)


def _handle(job: TranscriptionJob) -> JobLeaseHandle:
    if not job.lease_owner_id or not job.claimed_at or not job.lease_expires_at:
        raise JobLeaseError(JobLeaseFailureReason.lease_not_active)
    return JobLeaseHandle(
        job_id=job.id,
        lease_owner_id=job.lease_owner_id,
        lease_generation=job.lease_generation,
        claimed_at=job.claimed_at,
        lease_expires_at=job.lease_expires_at,
    )
