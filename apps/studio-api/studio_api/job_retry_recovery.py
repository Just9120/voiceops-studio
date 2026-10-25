from __future__ import annotations
from .media_context import parse_part_plan
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Literal
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .job_claim_lease import is_lease_active, invalidate_job_lease
from .job_claim_readiness import build_claim_readiness_from_preflight
from .job_processing_preflight import build_processing_preflight
from .models import (JobSourceStatus, JobStatus, OutputReconciliationStatus, SourceAttemptRetryDisposition as Disp, SourceAttemptStage as Stage, SttProviderOperation, TranscriptionJob, TranscriptionJobOutput, TranscriptionJobSource, TranscriptionJobSourceAttempt, TranscriptionOutputReconciliation, TranscriptionProviderPartCheckpoint)
from .provider_part_checkpoints import checkpoint_resume_count, complete_provider_attempt, delete_provider_part_checkpoints

MAX_PROCESSING_ATTEMPTS = 3
SAFE_PROVIDER_FAILURES = {
    "provider_authentication_rejected",
    "provider_payment_required",
    "provider_scope_rejected",
    "provider_request_rejected",
    "provider_rate_limited",
}
SAFE_PRE_TRANSPORT_FAILURES = SAFE_PROVIDER_FAILURES | {"provider_usage_accounting_unavailable"}
UNCERTAIN_PROVIDER_FAILURES = {"provider_timeout", "provider_unavailable", "malformed_provider_response", "partial_provider_result", "lifecycle_changed_after_provider_call", "lease_heartbeat_failed", "lease_heartbeat_not_owned", "lease_heartbeat_expired", "lease_heartbeat_commit_failed", "lease_heartbeat_stop_timeout", "context_closed", "unknown"}
PRE_PROVIDER_SAFE_FAILURES = {"prerequisites_unavailable", "source_materialization_unavailable", "ffmpeg_unavailable", "media_preparation_timeout", "media_preparation_failed", "prepared_media_too_large", "media_duration_unavailable", "media_duration_confirmation_required", "media_split_failed", "media_part_too_large", "lifecycle_changed_before_provider_call", "credential_or_output_identity_changed_before_provider_call", "pipeline_retry_state_prepare_failed", "pipeline_retry_state_persistence_failed", "retry_state_persistence_failed", "pipeline_transcription_failed", "pipeline_output_reconciliation_prepare_failed", "provider_pricing_unavailable", "provider_usage_accounting_unavailable"}
AUTOMATIC_RETRY_TRANSIENT_FAILURES = {
    "source_materialization_unavailable",
    "media_preparation_timeout",
    "provider_rate_limited",
    "provider_usage_accounting_unavailable",
}
AUTOMATIC_RETRY_BASE_SECONDS = 30
AUTOMATIC_RETRY_MAX_SECONDS = 300

class RetryReason(str, Enum):
    full_provider_restore_available="full_provider_restore_available"
    available="available"; partial_provider_resume_available="partial_provider_resume_available"; partial_provider_restart_available="partial_provider_restart_available"; job_not_failed="job_not_failed"; cancelled="cancelled"; completed="completed"; attempt_limit_reached="attempt_limit_reached"; provider_outcome_uncertain="provider_outcome_uncertain"; provider_result_lost="provider_result_lost"; output_reconciliation_required="output_reconciliation_required"; legacy_or_unknown_execution_state="legacy_or_unknown_execution_state"; prerequisites_unavailable="prerequisites_unavailable"; non_retryable="non_retryable"

@dataclass(frozen=True)
class RetryReadiness:
    available: bool; reason: RetryReason; attempt_count: int; max_attempts: int; missing_output_count: int; retry_safe_source_count: int; resumable_provider_part_count: int = 0; provider_total_part_count: int = 0; provider_failure_code: str | None = None
    missing_provider_parts: tuple[dict, ...] = ()
    def payload(self, job):
        from .long_media_preflight import long_media_preflight_payload
        return {"job_id": job.id, "job_status": job.status.value, "available": self.available, "reason": self.reason.value, "attempt_count": self.attempt_count, "max_attempts": self.max_attempts, "missing_output_count": self.missing_output_count, "retry_safe_source_count": self.retry_safe_source_count, "resumable_provider_part_count": self.resumable_provider_part_count, "provider_total_part_count": self.provider_total_part_count, "provider_failure_code": self.provider_failure_code, **({"missing_provider_parts": list(self.missing_provider_parts)} if self.missing_provider_parts else {}), **({"long_duration_preflight": quote} if (quote := long_media_preflight_payload(job)) is not None else {})}

@dataclass(frozen=True)
class RetryQueueResult:
    job: TranscriptionJob
    readiness: RetryReadiness
    transitioned: bool

def latest_attempt(db, job_source_id):
    return db.execute(select(TranscriptionJobSourceAttempt).where(TranscriptionJobSourceAttempt.job_source_id==job_source_id).order_by(TranscriptionJobSourceAttempt.attempt_number.desc(), TranscriptionJobSourceAttempt.created_at.desc())).scalars().first()

def current_attempt_for_relation(db, *, job_source_id, attempt_number):
    return db.execute(select(TranscriptionJobSourceAttempt).where(TranscriptionJobSourceAttempt.job_source_id==job_source_id, TranscriptionJobSourceAttempt.attempt_number==attempt_number)).scalar_one_or_none()

def _required(db, job_id):
    return db.execute(select(TranscriptionJobSource).where(TranscriptionJobSource.job_id==job_id, TranscriptionJobSource.status!=JobSourceStatus.skipped).order_by(TranscriptionJobSource.position, TranscriptionJobSource.id)).scalars().all()

def _has_output(db, rel_id):
    return db.execute(select(TranscriptionJobOutput.id).where(TranscriptionJobOutput.job_source_id==rel_id)).first() is not None

def _has_unresolved_reconciliation(db, rel_id):
    return db.execute(select(TranscriptionOutputReconciliation.id).where(TranscriptionOutputReconciliation.job_source_id==rel_id, TranscriptionOutputReconciliation.status != OutputReconciliationStatus.resolved)).first() is not None

def _confirmed_uncheckpointed_partial_result(db, attempt):
    """Allow only an explicit, cost-confirmed restart of a known returned part.

    This is the durable state left when provider usage was confirmed but the
    first immutable part checkpoint could not be inserted. It is distinct from
    an uncertain transport outcome: the normalized provider response returned,
    no provider call remains pending, and no resumable checkpoint exists.
    """
    if (
        attempt.provider_total_parts is None
        or int(attempt.provider_total_parts) <= 1
        or int(attempt.provider_completed_parts or 0) != 0
        or attempt.provider_accounting_status != "confirmed"
        or attempt.provider_pending_part_index is not None
        or attempt.provider_pending_duration_ms is not None
        or int(attempt.provider_billed_duration_ms or 0) <= 0
    ):
        return False
    return db.execute(
        select(TranscriptionProviderPartCheckpoint.id)
        .where(
            TranscriptionProviderPartCheckpoint.job_source_id
            == attempt.job_source_id
        )
        .limit(1)
    ).first() is None

def _require_active_processing(job, owner, generation, now, *, allow_cancel=False):
    if job.status!=JobStatus.processing or job.lease_owner_id!=owner or job.lease_generation!=generation or not is_lease_active(job, now) or (job.cancel_requested_at is not None and not allow_cancel):
        raise RuntimeError("retry_state_processing_context_invalid")

def _current_attempt(db: Session, *, job_id, job_source_id, lease_owner_id=None, lease_generation=None, now: datetime|None=None, require_processing_lease=False, allow_cancel=False):
    job=db.get(TranscriptionJob, job_id); rel=db.get(TranscriptionJobSource, job_source_id)
    if not job or not rel or rel.job_id!=job.id:
        raise RuntimeError("retry_state_scope_conflict")
    attempt_number=int(job.attempt_count or 0)
    if attempt_number < 1:
        raise RuntimeError("retry_state_invalid_attempt_number")
    if require_processing_lease:
        if now is None or lease_owner_id is None or lease_generation is None:
            raise RuntimeError("retry_state_processing_context_required")
        _require_active_processing(job, lease_owner_id, lease_generation, now, allow_cancel=allow_cancel)
    row=db.execute(select(TranscriptionJobSourceAttempt).where(TranscriptionJobSourceAttempt.job_source_id==rel.id, TranscriptionJobSourceAttempt.attempt_number==attempt_number)).scalar_one_or_none()
    if row is None:
        raise RuntimeError("retry_state_current_attempt_missing")
    if row.job_id!=job.id or row.owner_user_id!=job.owner_user_id or row.project_id!=job.project_id:
        raise RuntimeError("retry_state_scope_conflict")
    return job, rel, row

def prepare_source_attempt(db: Session, *, job_id, job_source_id, lease_owner_id, lease_generation, now: datetime):
    job=db.get(TranscriptionJob, job_id); rel=db.get(TranscriptionJobSource, job_source_id)
    if not job or not rel or rel.job_id!=job.id:
        raise RuntimeError("retry_state_prepare_not_allowed")
    _require_active_processing(job, lease_owner_id, lease_generation, now)
    n=int(job.attempt_count or 0)
    if n < 1:
        raise RuntimeError("retry_state_invalid_attempt_number")
    if _has_output(db, rel.id):
        return None
    if _has_unresolved_reconciliation(db, rel.id):
        raise RuntimeError("retry_state_reconciliation_exists")
    row=db.execute(select(TranscriptionJobSourceAttempt).where(TranscriptionJobSourceAttempt.job_source_id==rel.id, TranscriptionJobSourceAttempt.attempt_number==n)).scalar_one_or_none()
    if row:
        if row.owner_user_id!=job.owner_user_id or row.project_id!=job.project_id or row.job_id!=job.id:
            raise RuntimeError("retry_state_scope_conflict")
        return row
    row=TranscriptionJobSourceAttempt(owner_user_id=job.owner_user_id, project_id=job.project_id, job_id=job.id, job_source_id=rel.id, attempt_number=n, stage=Stage.prepared, retry_disposition=Disp.undetermined, created_at=now, updated_at=now)
    db.add(row); db.flush(); return row

def prepare_current_attempt_sources(db: Session, *, job_id, lease_owner_id, lease_generation, now: datetime):
    job=db.get(TranscriptionJob, job_id)
    if job is None:
        raise RuntimeError("retry_state_prepare_not_allowed")
    _require_active_processing(job, lease_owner_id, lease_generation, now)
    n=int(job.attempt_count or 0)
    if n < 1:
        raise RuntimeError("retry_state_invalid_attempt_number")
    created=[]
    for rel in _required(db, job.id):
        if _has_output(db, rel.id):
            continue
        if _has_unresolved_reconciliation(db, rel.id):
            raise RuntimeError("retry_state_reconciliation_exists")
        row=current_attempt_for_relation(db, job_source_id=rel.id, attempt_number=n)
        if row is None:
            row=TranscriptionJobSourceAttempt(owner_user_id=job.owner_user_id, project_id=job.project_id, job_id=job.id, job_source_id=rel.id, attempt_number=n, stage=Stage.prepared, retry_disposition=Disp.undetermined, created_at=now, updated_at=now)
            db.add(row); created.append(row)
            continue
        if row.owner_user_id!=job.owner_user_id or row.project_id!=job.project_id or row.job_id!=job.id:
            raise RuntimeError("retry_state_scope_conflict")
        if row.stage != Stage.prepared:
            raise RuntimeError("retry_state_not_prepared")
    db.flush(); return tuple(created)

def _transition(row, *, allowed_from, to_stage, disposition, now, idempotent=True):
    if row.stage == to_stage and idempotent:
        row.retry_disposition = disposition
        row.updated_at = now; return row
    if row.stage in {Stage.failed, Stage.output_persisted}:
        raise RuntimeError("retry_state_terminal_attempt")
    if row.stage not in allowed_from:
        raise RuntimeError("retry_state_invalid_transition")
    row.stage=to_stage; row.retry_disposition=disposition; row.updated_at=now; return row

def mark_attempt_provider_started(db, *, job_id, job_source_id, lease_owner_id, lease_generation, now, total_parts=None, completed_parts=0, media_plan=None):
    _job,_rel,row=_current_attempt(db, job_id=job_id, job_source_id=job_source_id, lease_owner_id=lease_owner_id, lease_generation=lease_generation, now=now, require_processing_lease=True)
    if media_plan is not None:
        parsed = parse_part_plan(media_plan)
        if len(parsed) != total_parts or (row.provider_media_plan_json and parse_part_plan(row.provider_media_plan_json) != parsed):
            raise RuntimeError("retry_state_media_plan_conflict")
        row.provider_media_plan_json = media_plan
    _transition(row, allowed_from={Stage.prepared}, to_stage=Stage.provider_request_started, disposition=Disp.undetermined, now=now)
    if total_parts is not None:
        total_parts = int(total_parts)
        if total_parts < 1:
            raise RuntimeError("retry_state_provider_part_count_invalid")
        if row.provider_total_parts not in {None, total_parts}:
            raise RuntimeError("retry_state_provider_part_count_conflict")
        row.provider_total_parts = total_parts
        completed_parts = int(completed_parts or 0)
        if completed_parts < 0 or completed_parts > total_parts:
            raise RuntimeError("retry_state_provider_part_progress_invalid")
        row.provider_completed_parts = completed_parts
    row.provider_request_started_at = row.provider_request_started_at or now
    db.flush(); return row

def mark_attempt_provider_part_completed(db, *, job_id, job_source_id, lease_owner_id, lease_generation, completed_parts, now):
    _job,_rel,row=_current_attempt(db, job_id=job_id, job_source_id=job_source_id, lease_owner_id=lease_owner_id, lease_generation=lease_generation, now=now, require_processing_lease=True)
    if row.stage != Stage.provider_request_started or row.provider_total_parts is None:
        raise RuntimeError("retry_state_provider_part_progress_unavailable")
    completed_parts = int(completed_parts)
    current = int(row.provider_completed_parts or 0)
    total = int(row.provider_total_parts)
    if completed_parts == current:
        return row
    if completed_parts != current + 1 or completed_parts > total:
        raise RuntimeError("retry_state_provider_part_progress_invalid")
    row.provider_completed_parts = completed_parts
    row.updated_at = now
    db.flush(); return row

def mark_attempt_provider_returned(db, *, job_id, job_source_id, lease_owner_id=None, lease_generation=None, now):
    _job,_rel,row=_current_attempt(db, job_id=job_id, job_source_id=job_source_id, lease_owner_id=lease_owner_id, lease_generation=lease_generation, now=now, require_processing_lease=lease_owner_id is not None, allow_cancel=True)
    _transition(row, allowed_from={Stage.provider_request_started}, to_stage=Stage.provider_response_returned, disposition=Disp.provider_result_lost, now=now)
    row.provider_response_returned_at = row.provider_response_returned_at or now
    if row.provider_total_parts is not None:
        row.provider_completed_parts = row.provider_total_parts
    db.flush(); return row

def classify_source_attempt_failure(db, *, job_source_id, failure_code, now, job_id=None, lease_owner_id=None, lease_generation=None, provider_failure_code=None):
    try:
        if job_id is not None:
            _job,_rel,row=_current_attempt(db, job_id=job_id, job_source_id=job_source_id, lease_owner_id=lease_owner_id, lease_generation=lease_generation, now=now, require_processing_lease=lease_owner_id is not None)
        else:
            row=latest_attempt(db, job_source_id)
    except RuntimeError:
        raise
    if not row: return None
    if row.retry_disposition == Disp.completed:
        return row
    code=str(failure_code or "unknown")
    row.stage=Stage.failed; row.failure_code=code
    if provider_failure_code:
        row.provider_failure_code=str(provider_failure_code)
    elif code != "partial_provider_result":
        row.provider_failure_code=None
    row.failed_at=row.failed_at or now; row.updated_at=now
    if code in SAFE_PRE_TRANSPORT_FAILURES or (row.provider_request_started_at is None and code in PRE_PROVIDER_SAFE_FAILURES): row.retry_disposition=Disp.retry_safe
    elif code in {"output_reconciliation_required", "existing_reconciliation_case"}: row.retry_disposition=Disp.output_reconciliation_required
    elif row.provider_response_returned_at is not None: row.retry_disposition=Disp.provider_result_lost
    elif row.provider_request_started_at is not None: row.retry_disposition=Disp.provider_outcome_uncertain
    else: row.retry_disposition=Disp.non_retryable
    db.flush(); return row

def mark_attempt_google_handoff(db, *, job_source_id, now, job_id=None):
    row = _current_attempt(db, job_id=job_id, job_source_id=job_source_id)[2] if job_id else latest_attempt(db, job_source_id)
    if row:
        _transition(row, allowed_from={Stage.provider_response_returned}, to_stage=Stage.google_handoff, disposition=Disp.provider_result_lost, now=now); db.flush()
    return row

def mark_attempt_output_reconciliation_required(db, *, job_source_id, failure_code, now, job_id=None):
    row = _current_attempt(db, job_id=job_id, job_source_id=job_source_id)[2] if job_id else latest_attempt(db, job_source_id)
    if row and row.retry_disposition != Disp.completed:
        row.failure_code=str(failure_code or "output_reconciliation_required"); row.retry_disposition=Disp.output_reconciliation_required; row.updated_at=now; db.flush()
    return row

def mark_attempt_completed(db, *, job_source_id, now, job_id=None):
    row = _current_attempt(db, job_id=job_id, job_source_id=job_source_id)[2] if job_id else latest_attempt(db, job_source_id)
    if row:
        if row.stage not in {Stage.google_handoff, Stage.output_persisted, Stage.provider_response_returned}:
            raise RuntimeError("retry_state_invalid_transition")
        row.stage=Stage.output_persisted; row.retry_disposition=Disp.completed; row.completed_at=row.completed_at or now; row.updated_at=now; db.flush()
    return row

def mark_latest_attempt_completed_for_output(db, *, job_source_id, now):
    row=latest_attempt(db, job_source_id)
    if row and row.retry_disposition != Disp.completed:
        row.stage=Stage.output_persisted; row.retry_disposition=Disp.completed; row.completed_at=row.completed_at or now; row.updated_at=now; db.flush()
    return row

def _projected_queued_ready(job, *, now=None) -> bool:
    preflight = build_processing_preflight(job, now=now)
    projected = dict(preflight); projected["status"] = "queued"; projected["blocking_reasons"] = [r for r in preflight["blocking_reasons"] if r != "job_status_not_queued"]
    projected["eligible"] = not projected["blocking_reasons"]
    return bool(build_claim_readiness_from_preflight(projected)["ready_for_future_claim"])


def _has_resumable_yandex_operation(db, job, relation, *, attempt_number: int) -> bool:
    if job.provider != "yandex":
        return False
    return db.execute(
        select(SttProviderOperation.id)
        .where(
            SttProviderOperation.owner_user_id == job.owner_user_id,
            SttProviderOperation.project_id == job.project_id,
            SttProviderOperation.job_id == job.id,
            SttProviderOperation.job_source_id == relation.id,
            SttProviderOperation.attempt_number == attempt_number,
            SttProviderOperation.provider == "yandex",
            SttProviderOperation.status.in_(("pending", "completed")),
        )
        .limit(1)
    ).first() is not None

def _evaluate(db, job, *, mode: Literal["explicit", "recovery"], now: datetime|None=None):
    attempts=int(job.attempt_count or 0)
    if job.status==JobStatus.completed: return RetryReadiness(False, RetryReason.completed, attempts, MAX_PROCESSING_ATTEMPTS, 0, 0)
    if job.cancel_requested_at or job.status==JobStatus.cancelled: return RetryReadiness(False, RetryReason.cancelled, attempts, MAX_PROCESSING_ATTEMPTS, 0, 0)
    if mode=="explicit":
        if job.status==JobStatus.queued: return RetryReadiness(True, RetryReason.available, attempts, MAX_PROCESSING_ATTEMPTS, 0, 0)
        if job.status!=JobStatus.failed: return RetryReadiness(False, RetryReason.job_not_failed, attempts, MAX_PROCESSING_ATTEMPTS, 0, 0)
        if now is not None and is_lease_active(job, now): return RetryReadiness(False, RetryReason.non_retryable, attempts, MAX_PROCESSING_ATTEMPTS, 0, 0)
    else:
        if job.status!=JobStatus.processing: return RetryReadiness(False, RetryReason.job_not_failed, attempts, MAX_PROCESSING_ATTEMPTS, 0, 0)
        if now is not None and is_lease_active(job, now): return RetryReadiness(False, RetryReason.non_retryable, attempts, MAX_PROCESSING_ATTEMPTS, 0, 0)
    rels=_required(db, job.id); missing=[]; safe=0; reason=None; resumable_parts=0; provider_total_parts=0; provider_failure_code=None; fully_cached_sources=0; missing_parts=[]
    for rel in rels:
        if _has_output(db, rel.id): continue
        missing.append(rel)
        if _has_unresolved_reconciliation(db, rel.id): reason=RetryReason.output_reconciliation_required; continue
        if job.provider == "yandex":
            from .job_cached_transcript import completed_yandex_result
            if completed_yandex_result(db, job, rel.id) is not None:
                safe += 1; fully_cached_sources += 1; resumable_parts += 1; provider_total_parts += 1
                continue
        att=current_attempt_for_relation(db, job_source_id=rel.id, attempt_number=attempts)
        complete = complete_provider_attempt(db, job_id=job.id, job_source_id=rel.id)
        if complete is not None:
            resumed = checkpoint_resume_count(
                db, job_source_id=rel.id, total_parts=complete.provider_total_parts,
                completed_parts=int(complete.provider_completed_parts), now=now or datetime.utcnow(),
            ) if mode == "explicit" else 0
            if resumed == complete.provider_total_parts:
                safe+=1; resumable_parts+=resumed; provider_total_parts+=resumed; fully_cached_sources+=1
            else:
                reason=reason or RetryReason.provider_result_lost
            continue
        if not att:
            if job.error_code in {"pipeline_retry_state_prepare_failed", "pipeline_retry_state_persistence_failed"}: safe+=1
            else: reason=reason or RetryReason.legacy_or_unknown_execution_state
        elif _has_resumable_yandex_operation(db, job, rel, attempt_number=attempts):
            # The durable operation ID authorizes polling/result reload only;
            # it does not authorize a second provider submit.
            safe+=1
        elif att.stage==Stage.prepared and att.provider_request_started_at is None: safe+=1
        elif att.retry_disposition==Disp.retry_safe and (att.provider_request_started_at is None or att.failure_code in SAFE_PRE_TRANSPORT_FAILURES):
            safe+=1
            if att.provider_failure_code in SAFE_PROVIDER_FAILURES:
                provider_failure_code=att.provider_failure_code
        elif att.failure_code=="partial_provider_result":
            resumed = (
                checkpoint_resume_count(
                    db,
                    job_source_id=rel.id,
                    total_parts=att.provider_total_parts,
                    completed_parts=int(att.provider_completed_parts or 0),
                    now=now or datetime.utcnow(),
                )
                if mode == "explicit"
                else 0
            )
            if resumed:
                safe+=1; resumable_parts+=resumed; provider_total_parts+=int(att.provider_total_parts or 0); provider_failure_code=att.provider_failure_code
                plan = parse_part_plan(att.provider_media_plan_json)
                if len(plan) == att.provider_total_parts:
                    missing_parts.extend({"source_id": rel.source_id, **part} for part in plan[resumed:])
            elif mode == "explicit" and (
                att.provider_failure_code in SAFE_PROVIDER_FAILURES
                or _confirmed_uncheckpointed_partial_result(db, att)
            ):
                safe+=1; provider_total_parts+=int(att.provider_total_parts or 0); provider_failure_code=att.provider_failure_code
            else:
                reason=reason or RetryReason.provider_outcome_uncertain
        elif att.retry_disposition==Disp.provider_outcome_uncertain or att.stage==Stage.provider_request_started: reason=reason or RetryReason.provider_outcome_uncertain
        elif att.retry_disposition==Disp.provider_result_lost or att.stage in {Stage.provider_response_returned, Stage.google_handoff}: reason=reason or RetryReason.provider_result_lost
        elif att.retry_disposition==Disp.output_reconciliation_required: reason=reason or RetryReason.output_reconciliation_required
        else: reason=reason or RetryReason.non_retryable
    if attempts >= MAX_PROCESSING_ATTEMPTS and fully_cached_sources != len(missing):
        return RetryReadiness(False, RetryReason.attempt_limit_reached, attempts, MAX_PROCESSING_ATTEMPTS, len(missing), safe, resumable_parts, provider_total_parts)
    if not missing: return RetryReadiness(False, RetryReason.completed, attempts, MAX_PROCESSING_ATTEMPTS, 0, safe, resumable_parts, provider_total_parts)
    if safe==len(missing) and _projected_queued_ready(job, now=now):
        if fully_cached_sources == len(missing):
            retry_reason = RetryReason.full_provider_restore_available
        elif provider_total_parts and not resumable_parts:
            retry_reason = RetryReason.partial_provider_restart_available
        else:
            retry_reason = RetryReason.partial_provider_resume_available if resumable_parts else RetryReason.available
        return RetryReadiness(True, retry_reason, attempts, MAX_PROCESSING_ATTEMPTS, len(missing), safe, resumable_parts, provider_total_parts, provider_failure_code, tuple(missing_parts))
    return RetryReadiness(False, reason or RetryReason.prerequisites_unavailable, attempts, MAX_PROCESSING_ATTEMPTS, len(missing), safe, resumable_parts, provider_total_parts, provider_failure_code)

def compute_explicit_retry_readiness(db, job, *, now: datetime|None=None):
    return _evaluate(db, job, mode="explicit", now=now)

def requires_provider_cost_confirmation(readiness: RetryReadiness) -> bool:
    return readiness.reason in {
        RetryReason.partial_provider_resume_available,
        RetryReason.partial_provider_restart_available,
    }

def compute_expired_recovery_readiness(db, job, *, now: datetime):
    return _evaluate(db, job, mode="recovery", now=now)

def compute_retry_readiness(db, job):
    return compute_explicit_retry_readiness(db, job)

def queue_retry(db, *, owner_user_id, job_id, now):
    job=db.execute(select(TranscriptionJob).where(TranscriptionJob.id==job_id, TranscriptionJob.owner_user_id==owner_user_id).with_for_update()).scalar_one_or_none()
    if not job: return None
    ready=compute_explicit_retry_readiness(db, job, now=now)
    if job.status==JobStatus.queued:
        return RetryQueueResult(job=job, readiness=ready, transitioned=False)
    if ready.available and not is_lease_active(job, now):
        from .job_notifications import suppress_obsolete_job_notification_intents
        if ready.reason == RetryReason.partial_provider_restart_available:
            delete_provider_part_checkpoints(db, job_id=job.id)
        suppress_obsolete_job_notification_intents(db, job_id=job.id, now=now)
        job.status=JobStatus.queued; job.finished_at=None; job.error_code=None; job.error_message=None; job.retry_not_before_at=None; job.automatic_retry_reason=None; job.terminal_dismissed_at=None; job.updated_at=now; invalidate_job_lease(job); db.flush()
        return RetryQueueResult(job=job, readiness=compute_explicit_retry_readiness(db, job, now=now), transitioned=True)
    return RetryQueueResult(job=job, readiness=ready, transitioned=False)


def schedule_automatic_retry_if_safe(db, *, job: TranscriptionJob, now: datetime) -> bool:
    """Requeue only an allowlisted, durable, non-ambiguous transient failure."""
    if job.status != JobStatus.failed or int(job.attempt_count or 0) >= MAX_PROCESSING_ATTEMPTS:
        return False
    readiness = compute_explicit_retry_readiness(db, job, now=now)
    if not readiness.available or requires_provider_cost_confirmation(readiness):
        return False
    missing = [rel for rel in _required(db, job.id) if not _has_output(db, rel.id)]
    saw_transient = False
    reason = None
    for rel in missing:
        attempt = current_attempt_for_relation(
            db,
            job_source_id=rel.id,
            attempt_number=int(job.attempt_count or 0),
        )
        if attempt is None:
            return False
        if (
            attempt.stage == Stage.prepared
            and attempt.provider_request_started_at is None
            and attempt.failure_code is None
        ):
            continue
        failure = attempt.provider_failure_code or attempt.failure_code
        if (
            attempt.retry_disposition != Disp.retry_safe
            or failure not in AUTOMATIC_RETRY_TRANSIENT_FAILURES
        ):
            return False
        saw_transient = True
        reason = reason or failure
    if not saw_transient:
        return False
    from .job_notifications import suppress_obsolete_job_notification_intents

    delay = min(
        AUTOMATIC_RETRY_BASE_SECONDS * (2 ** max(0, int(job.attempt_count or 0) - 1)),
        AUTOMATIC_RETRY_MAX_SECONDS,
    )
    suppress_obsolete_job_notification_intents(db, job_id=job.id, now=now)
    job.status = JobStatus.queued
    job.finished_at = None
    job.error_code = None
    job.error_message = None
    job.retry_not_before_at = now + timedelta(seconds=delay)
    job.automatic_retry_reason = reason
    job.terminal_dismissed_at = None
    job.updated_at = now
    invalidate_job_lease(job)
    db.flush()
    return True
