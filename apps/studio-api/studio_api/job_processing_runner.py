from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Callable

from sqlalchemy.orm import Session

from .job_claim_lease import JobLeaseError, acquire_job_lease, acquire_next_ready_job_lease
from .job_processing_orchestrator import (
    JobProcessingOrchestrationError,
    JobProcessingOrchestrationResult,
    orchestrate_processing_job,
)
from .security import utcnow
from .diagnostics import resolve_job_correlation_id, write_diagnostic_event
from .models import TranscriptionJob


class JobProcessingRunnerReason(str, Enum):
    claim_failed = "claim_failed"
    claim_commit_failed = "claim_commit_failed"
    orchestration_failed = "orchestration_failed"


class JobProcessingRunnerError(RuntimeError):
    def __init__(self, reason: JobProcessingRunnerReason):
        self.reason = reason
        super().__init__(reason.value)


def claim_next_and_orchestrate_processing_job(
    db: Session,
    *,
    lease_owner_id: str,
    lease_ttl: timedelta,
    settings,
    clock: Callable[[], datetime] | None = None,
    next_lease_acquirer: Callable = acquire_next_ready_job_lease,
    orchestrator: Callable = orchestrate_processing_job,
    heartbeat_session_factory: Callable | None = None,
) -> JobProcessingOrchestrationResult | None:
    """Claim the next ready queued job, commit the lease, then run the orchestrator once.

    Idle state is represented by ``None`` and ends the selection transaction.
    """

    clock = clock or (lambda: utcnow().replace(tzinfo=None))
    now = clock()
    try:
        handle = next_lease_acquirer(
            db,
            lease_owner_id=lease_owner_id,
            now=now,
            lease_ttl=lease_ttl,
        )
    except JobLeaseError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise JobProcessingRunnerError(JobProcessingRunnerReason.claim_failed) from exc

    if handle is None:
        db.rollback()
        return None

    return _commit_and_orchestrate(
        db,
        handle=handle,
        settings=settings,
        clock=clock,
        orchestrator=orchestrator,
        lease_ttl=lease_ttl,
        heartbeat_session_factory=heartbeat_session_factory,
    )


def claim_and_orchestrate_processing_job(
    db: Session,
    *,
    job_id: str,
    lease_owner_id: str,
    lease_ttl: timedelta,
    settings,
    clock: Callable[[], datetime] | None = None,
    lease_acquirer: Callable = acquire_job_lease,
    orchestrator: Callable = orchestrate_processing_job,
    heartbeat_session_factory: Callable | None = None,
) -> JobProcessingOrchestrationResult:
    """Claim one explicit queued job, commit the lease, then run the orchestrator once."""

    clock = clock or (lambda: utcnow().replace(tzinfo=None))
    now = clock()
    try:
        handle = lease_acquirer(
            db,
            job_id=job_id,
            lease_owner_id=lease_owner_id,
            now=now,
            lease_ttl=lease_ttl,
        )
    except JobLeaseError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise JobProcessingRunnerError(JobProcessingRunnerReason.claim_failed) from exc

    return _commit_and_orchestrate(
        db,
        handle=handle,
        settings=settings,
        clock=clock,
        orchestrator=orchestrator,
        lease_ttl=lease_ttl,
        heartbeat_session_factory=heartbeat_session_factory,
    )


def _commit_and_orchestrate(
    db: Session,
    *,
    handle,
    settings,
    clock: Callable[[], datetime],
    orchestrator: Callable,
    lease_ttl: timedelta,
    heartbeat_session_factory: Callable | None,
) -> JobProcessingOrchestrationResult:
    try:
        job = db.get(TranscriptionJob, handle.job_id)
        if job:
            correlation_id = resolve_job_correlation_id(
                owner_user_id=job.owner_user_id, job_id=job.id, now=clock(), transaction=db,
            )
            event = write_diagnostic_event(
                owner_user_id=job.owner_user_id, component="worker", event_code="JOB_CLAIMED",
                project_id=job.project_id, job_id=job.id, correlation_id=correlation_id,
                metadata={}, now=clock(), transaction=db,
            )
            if not event.persisted:
                raise JobProcessingRunnerError(JobProcessingRunnerReason.claim_commit_failed)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise JobProcessingRunnerError(JobProcessingRunnerReason.claim_commit_failed) from exc

    try:
        kwargs = dict(
            job_id=handle.job_id,
            lease_owner_id=handle.lease_owner_id,
            lease_generation=handle.lease_generation,
            settings=settings,
            clock=clock,
            lease_ttl=lease_ttl,
        )
        if heartbeat_session_factory is not None:
            kwargs["heartbeat_session_factory"] = heartbeat_session_factory
        return orchestrator(db, **kwargs)
    except JobProcessingOrchestrationError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise JobProcessingRunnerError(JobProcessingRunnerReason.orchestration_failed) from exc
