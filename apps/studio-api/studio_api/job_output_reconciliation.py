from __future__ import annotations

import hashlib, secrets
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .google_docs_output import GOOGLE_DOC_MIME_TYPE, OUTPUT_RECONCILIATION_APP_PROPERTY
from .job_output_persistence import GOOGLE_DOCS_TRANSCRIPT_OUTPUT_KIND, TRANSCRIPT_STANDARD
from .models import JobSourceStatus, JobStatus, OutputReconciliationStatus, Project, Source, TranscriptionJob, TranscriptionJobOutput, TranscriptionJobSource, TranscriptionOutputReconciliation
from .provider_usage_accounting import finalize_job_provider_accounting
from .security import utcnow
from .job_retry_recovery import mark_latest_attempt_completed_for_output

OUTPUT_RECONCILIATION_ERROR_CODE = "output_reconciliation_required"
SAFE_REASONS = {"google_docs_timeout","google_docs_unavailable","malformed_google_docs_response","lifecycle_changed_after_output_creation","commit_failed","context_closed","unknown","job_not_processable","lease_not_owned","lease_not_active","cancellation_requested","existing_reconciliation_case","lease_heartbeat_failed","lease_heartbeat_not_owned","lease_heartbeat_expired","lease_heartbeat_commit_failed","lease_heartbeat_stop_timeout"}
SAFE_REASONS |= {"yandex_disk_quota_exceeded", "yandex_disk_permission_denied", "yandex_disk_access_expired", "yandex_disk_document_conflict", "yandex_disk_unavailable"}

class OutputReconciliationReason(str, Enum):
    unavailable="unavailable"; not_found="not_found"; conflict="conflict"; invalid_candidate="invalid_candidate"; not_allowed="not_allowed"; missing_case="missing_case"; output_conflict="output_conflict"; google_connection_unavailable="google_connection_unavailable"; existing_reconciliation_case="existing_reconciliation_case"

class OutputReconciliationError(RuntimeError):
    def __init__(self, reason: OutputReconciliationReason): self.reason=reason; super().__init__(reason.value)

@dataclass(frozen=True)
class DriveReconciliationCandidate:
    document_id: str; mime_type: str; web_view_link: str; parents: tuple[str,...]; created_time: datetime; app_properties: dict[str,str]

@dataclass(frozen=True)
class OutputReconciliationCheckResult:
    checked:int=0; resolved:int=0; unresolved:int=0; conflicts:int=0; unavailable:int=0

def new_reconciliation_token() -> str:
    return "or_" + secrets.token_urlsafe(32).rstrip("=")

def title_hash(title: str|None) -> str|None:
    return hashlib.sha256((title or "").encode()).hexdigest() if title is not None else None

def prepare_output_reconciliation_case(db: Session, *, job_id: str, job_source_id: str, lease_owner_id: str, lease_generation: int, document_title: str, character_count: int, now: datetime) -> TranscriptionOutputReconciliation:
    job=db.get(TranscriptionJob, job_id)
    if not job or job.status!=JobStatus.processing or job.lease_owner_id!=lease_owner_id or job.lease_generation!=lease_generation or job.cancel_requested_at is not None or not job.output_drive_folder_id:
        raise OutputReconciliationError(OutputReconciliationReason.not_allowed)
    rel=db.get(TranscriptionJobSource, job_source_id)
    if not rel or rel.job_id!=job.id or rel.status==JobSourceStatus.skipped: raise OutputReconciliationError(OutputReconciliationReason.not_allowed)
    project=db.get(Project, job.project_id)
    if not project or project.owner_user_id!=job.owner_user_id or project.archived_at is not None: raise OutputReconciliationError(OutputReconciliationReason.not_allowed)
    if db.execute(select(TranscriptionJobOutput.id).where(TranscriptionJobOutput.job_source_id==rel.id)).first():
        raise OutputReconciliationError(OutputReconciliationReason.output_conflict)
    case=db.execute(select(TranscriptionOutputReconciliation).where(TranscriptionOutputReconciliation.job_source_id==rel.id)).scalar_one_or_none()
    if case:
        if (case.owner_user_id!=job.owner_user_id or case.project_id!=job.project_id or case.job_id!=job.id
                or case.expected_output_drive_folder_id!=job.output_drive_folder_id
                or case.expected_output_provider != job.output_provider):
            raise OutputReconciliationError(OutputReconciliationReason.conflict)
        if (job.output_provider == "yandex_disk" and case.status == OutputReconciliationStatus.resolved
                and case.uncertainty_reason == "yandex_output_absent" and case.resolved_output_id is None
                and case.returned_document_id is None
                and case.expected_document_title_hash == title_hash(document_title)
                and case.expected_document_character_count == character_count):
            case.status = OutputReconciliationStatus.prepared
            case.lease_generation = lease_generation
            case.attempt_number = job.attempt_count or 0
            case.creation_started_at = case.updated_at = now
            db.flush()
            return case
        if case.status==OutputReconciliationStatus.resolved:
            if case.resolved_output_id and db.get(TranscriptionJobOutput, case.resolved_output_id):
                raise OutputReconciliationError(OutputReconciliationReason.output_conflict)
            if db.execute(select(TranscriptionJobOutput.id).where(TranscriptionJobOutput.job_source_id==rel.id)).first():
                raise OutputReconciliationError(OutputReconciliationReason.output_conflict)
            raise OutputReconciliationError(OutputReconciliationReason.conflict)
        if case.status==OutputReconciliationStatus.conflict:
            raise OutputReconciliationError(OutputReconciliationReason.conflict)
        if case.status==OutputReconciliationStatus.prepared:
            case.status=OutputReconciliationStatus.reconciliation_required; case.uncertainty_reason="existing_reconciliation_case"; case.updated_at=now; db.flush()
        raise OutputReconciliationError(OutputReconciliationReason.existing_reconciliation_case)
    case=TranscriptionOutputReconciliation(owner_user_id=job.owner_user_id, project_id=job.project_id, job_id=job.id, job_source_id=rel.id, reconciliation_token=new_reconciliation_token(), lease_generation=lease_generation, attempt_number=job.attempt_count or 0, status=OutputReconciliationStatus.prepared, expected_output_drive_folder_id=job.output_drive_folder_id, expected_output_provider=job.output_provider, expected_document_title=document_title, expected_document_title_hash=title_hash(document_title), expected_document_character_count=character_count, prepared_at=now, creation_started_at=now, created_at=now, updated_at=now)
    db.add(case); db.flush(); return case

def mark_reconciliation_creation_returned(db: Session, *, job_source_id: str, document_id: str, web_view_url: str, document_created_at: datetime, now: datetime) -> None:
    case=db.execute(select(TranscriptionOutputReconciliation).where(TranscriptionOutputReconciliation.job_source_id==job_source_id)).scalar_one_or_none()
    if not case: raise OutputReconciliationError(OutputReconciliationReason.missing_case)
    case.returned_document_id=document_id; case.returned_web_view_url=web_view_url; case.returned_document_created_at=document_created_at; case.status=OutputReconciliationStatus.creation_returned; case.updated_at=now; db.flush()

def mark_reconciliation_required(db: Session, *, job_id: str, lease_generation: int|None=None, reason: str="unknown", now: datetime|None=None) -> int:
    now=now or utcnow().replace(tzinfo=None); reason = reason if reason in SAFE_REASONS else "unknown"
    q=select(TranscriptionOutputReconciliation).where(TranscriptionOutputReconciliation.job_id==job_id)
    if lease_generation is not None: q=q.where(TranscriptionOutputReconciliation.lease_generation==lease_generation)
    rows=db.execute(q).scalars().all()
    for c in rows:
        if c.status not in {OutputReconciliationStatus.resolved, OutputReconciliationStatus.conflict}:
            c.status=OutputReconciliationStatus.reconciliation_required; c.uncertainty_reason=reason; c.updated_at=now
    db.flush(); return len(rows)

def reconciliation_status_payload(db: Session, *, owner_user_id: str, job_id: str) -> dict:
    job=db.get(TranscriptionJob, job_id)
    if not job or job.owner_user_id!=owner_user_id: raise OutputReconciliationError(OutputReconciliationReason.not_found)
    cases=db.execute(select(TranscriptionOutputReconciliation).where(TranscriptionOutputReconciliation.job_id==job.id).order_by(TranscriptionOutputReconciliation.prepared_at, TranscriptionOutputReconciliation.id)).scalars().all()
    counts={s.value:0 for s in OutputReconciliationStatus}
    for c in cases: counts[c.status.value]+=1
    available= job.status in {JobStatus.failed, JobStatus.cancelled} and any(c.status in {OutputReconciliationStatus.reconciliation_required, OutputReconciliationStatus.creation_returned, OutputReconciliationStatus.conflict} or (c.expected_output_provider == "yandex_disk" and c.status == OutputReconciliationStatus.prepared) for c in cases)
    return {"job_id":job.id,"job_status":job.status.value,"available":available,"counts":counts,"cases":[{"job_source_id":c.job_source_id,"status":c.status.value,"reason":c.uncertainty_reason,"prepared_at":c.prepared_at.isoformat() if c.prepared_at else None,"last_checked_at":c.last_checked_at.isoformat() if c.last_checked_at else None,"resolved":c.status==OutputReconciliationStatus.resolved,"resolved_at":c.resolved_at.isoformat() if c.resolved_at else None} for c in cases]}

def persist_verified_reconciliation_output(db: Session, *, case: TranscriptionOutputReconciliation, candidate: DriveReconciliationCandidate, now: datetime) -> bool:
    job=db.execute(select(TranscriptionJob).where(TranscriptionJob.id==case.job_id).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if not job or job.owner_user_id!=case.owner_user_id or job.project_id!=case.project_id or job.status in {JobStatus.queued, JobStatus.processing}: raise OutputReconciliationError(OutputReconciliationReason.not_allowed)
    rel=db.execute(select(TranscriptionJobSource).where(TranscriptionJobSource.id==case.job_source_id).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if not rel or rel.job_id!=job.id or rel.status==JobSourceStatus.skipped or job.output_drive_folder_id!=case.expected_output_drive_folder_id or job.output_provider!=case.expected_output_provider: raise OutputReconciliationError(OutputReconciliationReason.not_allowed)
    source=db.get(Source, rel.source_id)
    if not source or source.project_id!=job.project_id: raise OutputReconciliationError(OutputReconciliationReason.not_allowed)
    existing=db.execute(select(TranscriptionJobOutput).where(TranscriptionJobOutput.job_source_id==rel.id)).scalar_one_or_none()
    if existing:
        if existing.document_id==candidate.document_id and existing.output_drive_folder_id==case.expected_output_drive_folder_id:
            case.status=OutputReconciliationStatus.resolved; case.resolved_output_id=existing.id; case.resolved_at=case.resolved_at or now; case.updated_at=now; mark_latest_attempt_completed_for_output(db, job_source_id=rel.id, now=now); return False
        raise OutputReconciliationError(OutputReconciliationReason.output_conflict)
    if db.execute(select(TranscriptionJobOutput.id).where(TranscriptionJobOutput.document_id==candidate.document_id)).first(): raise OutputReconciliationError(OutputReconciliationReason.output_conflict)
    output=TranscriptionJobOutput(job_id=job.id, job_source_id=rel.id, document_id=candidate.document_id, web_view_url=candidate.web_view_link, output_drive_folder_id=case.expected_output_drive_folder_id, output_kind=_case_output_kind(case), transcript_standard=TRANSCRIPT_STANDARD, document_character_count=case.expected_document_character_count, document_created_at=candidate.created_time, persisted_at=now, lease_generation=case.lease_generation)
    db.add(output); db.flush(); case.status=OutputReconciliationStatus.resolved; case.resolved_output_id=output.id; case.resolved_at=now; case.updated_at=now; mark_latest_attempt_completed_for_output(db, job_source_id=rel.id, now=now)
    from .job_cached_transcript import retire_cached_yandex_result
    retire_cached_yandex_result(db, job_id=job.id, job_source_id=rel.id)
    required=[r.id for r in db.execute(select(TranscriptionJobSource).where(TranscriptionJobSource.job_id==job.id)).scalars().all() if r.status!=JobSourceStatus.skipped]
    count=db.execute(select(func.count(TranscriptionJobOutput.id)).where(TranscriptionJobOutput.job_id==job.id, TranscriptionJobOutput.job_source_id.in_(required or ["__none__"]))).scalar_one()
    if job.status==JobStatus.failed and job.error_code==OUTPUT_RECONCILIATION_ERROR_CODE and required and int(count)==len(required):
        from .job_notifications import ensure_terminal_notification_intents
        job.status=JobStatus.completed; job.finished_at=now; job.error_code=None; job.error_message=None; job.updated_at=now; finalize_job_provider_accounting(db, job=job, now=now); ensure_terminal_notification_intents(db, job=job, now=now)
    return True

def _case_output_kind(case):
    from .transcript_docx import DOCX_OUTPUT_KIND
    if case.expected_output_provider == "yandex_disk":
        return DOCX_OUTPUT_KIND
    if case.expected_output_provider == "google_drive":
        return GOOGLE_DOCS_TRANSCRIPT_OUTPUT_KIND
    raise OutputReconciliationError(OutputReconciliationReason.invalid_candidate)


def verify_candidate(case, candidate):
    if case.expected_output_provider!="google_drive" or candidate.mime_type!=GOOGLE_DOC_MIME_TYPE or case.expected_output_drive_folder_id not in candidate.parents or candidate.app_properties.get(OUTPUT_RECONCILIATION_APP_PROPERTY)!=case.reconciliation_token or not candidate.document_id or not candidate.web_view_link.startswith("https://docs.google.com/"):
        raise OutputReconciliationError(OutputReconciliationReason.invalid_candidate)

def check_job_output_reconciliation(db: Session, *, owner_user_id: str, job_id: str, lookup: Callable[[str,str], list[DriveReconciliationCandidate]], now: datetime|None=None) -> OutputReconciliationCheckResult:
    now=now or utcnow().replace(tzinfo=None); job=db.get(TranscriptionJob, job_id)
    if not job or job.owner_user_id!=owner_user_id: raise OutputReconciliationError(OutputReconciliationReason.not_found)
    if job.status in {JobStatus.queued, JobStatus.processing}: raise OutputReconciliationError(OutputReconciliationReason.not_allowed)
    cases=db.execute(select(TranscriptionOutputReconciliation).where(TranscriptionOutputReconciliation.job_id==job.id, TranscriptionOutputReconciliation.status.in_([OutputReconciliationStatus.reconciliation_required, OutputReconciliationStatus.creation_returned, OutputReconciliationStatus.conflict]))).scalars().all()
    checked=resolved=unresolved=conflicts=unavailable=0
    for case in cases:
        checked+=1
        if case.status==OutputReconciliationStatus.conflict:
            conflicts+=1; continue
        matches=lookup(case.reconciliation_token, case.expected_output_drive_folder_id)
        case.last_checked_at=now; case.updated_at=now
        if len(matches)==0: unresolved+=1; continue
        if len(matches)>1: case.status=OutputReconciliationStatus.conflict; conflicts+=1; continue
        try:
            verify_candidate(case, matches[0]); created=persist_verified_reconciliation_output(db, case=case, candidate=matches[0], now=now); resolved+=1
        except OutputReconciliationError:
            case.status=OutputReconciliationStatus.conflict; conflicts+=1
    return OutputReconciliationCheckResult(checked,resolved,unresolved,conflicts,unavailable)
