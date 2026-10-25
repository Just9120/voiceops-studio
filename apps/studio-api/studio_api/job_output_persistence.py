from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .google_docs_output import GoogleDocsOutputError, GoogleDocsOutputReason, GoogleDocsTranscriptArtifact
from .job_claim_lease import invalidate_job_lease, is_lease_active
from .models import JobSourceStatus, JobStatus, OutputReconciliationStatus, Project, Source, SourceUploadStatus, TranscriptionJob, TranscriptionJobOutput, TranscriptionJobSource, TranscriptionOutputReconciliation
from .transcript_catalog import (
    CURRENT_TRANSCRIPT_STANDARD as TRANSCRIPT_STANDARD,
    GOOGLE_DOCS_TRANSCRIPT_OUTPUT_KIND,
)
from .provider_usage_accounting import finalize_job_provider_accounting


class JobOutputPersistenceReason(str, Enum):
    job_not_found = "job_not_found"
    job_not_processing = "job_not_processing"
    lease_not_owned = "lease_not_owned"
    lease_not_active = "lease_not_active"
    cancellation_requested = "cancellation_requested"
    project_unavailable = "project_unavailable"
    output_folder_changed = "output_folder_changed"
    job_source_not_found = "job_source_not_found"
    job_source_not_processable = "job_source_not_processable"
    artifact_context_closed = "artifact_context_closed"
    output_already_persisted = "output_already_persisted"
    output_conflict = "output_conflict"
    persistence_failure = "persistence_failure"


class JobOutputPersistenceError(RuntimeError):
    def __init__(self, reason: JobOutputPersistenceReason):
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True)
class JobOutputPersistenceResult:
    job_id: str
    job_source_id: str
    output_id: str = field(repr=False)
    job_status: JobStatus
    persisted_output_count: int
    required_output_count: int
    completed: bool
    lease_generation: int


@dataclass(frozen=True)
class _LockedOutputAuthority:
    job: TranscriptionJob
    project: Project
    selected_relation: TranscriptionJobSource
    selected_source: Source
    job_source_relations: tuple[TranscriptionJobSource, ...]


def persist_processing_job_source_output_and_maybe_complete(
    db: Session,
    *,
    job_id: str,
    job_source_id: str,
    lease_owner_id: str,
    lease_generation: int,
    artifact: GoogleDocsTranscriptArtifact,
    now: datetime,
) -> JobOutputPersistenceResult:
    try:
        document_id = artifact.document_id
        web_view_url = artifact.web_view_link
        output_folder_id = artifact.output_folder_id
    except GoogleDocsOutputError as exc:
        if exc.reason == GoogleDocsOutputReason.context_closed:
            raise JobOutputPersistenceError(JobOutputPersistenceReason.artifact_context_closed) from exc
        raise

    authority = _load_locked_output_authority(
        db,
        job_id=job_id,
        job_source_id=job_source_id,
        lease_owner_id=lease_owner_id,
        lease_generation=lease_generation,
        output_folder_id=output_folder_id,
        now=now,
    )
    job = authority.job
    rel = authority.selected_relation
    from .transcript_docx import DOCX_OUTPUT_KIND
    expected_kind = {"google_drive": GOOGLE_DOCS_TRANSCRIPT_OUTPUT_KIND,
                     "yandex_disk": DOCX_OUTPUT_KIND}.get(job.output_provider)
    if (artifact.output_provider != job.output_provider or not expected_kind
            or artifact.output_kind != expected_kind):
        raise JobOutputPersistenceError(JobOutputPersistenceReason.output_conflict)

    existing = db.execute(select(TranscriptionJobOutput).where(TranscriptionJobOutput.job_source_id == job_source_id)).scalar_one_or_none()
    if existing is None:
        output = TranscriptionJobOutput(
            job_id=job.id,
            job_source_id=rel.id,
            document_id=document_id,
            web_view_url=web_view_url,
            output_drive_folder_id=output_folder_id,
            output_kind=expected_kind,
            transcript_standard=TRANSCRIPT_STANDARD,
            document_character_count=artifact.character_count,
            document_created_at=artifact.created_at,
            persisted_at=now,
            lease_generation=lease_generation,
        )
        db.add(output)
        try:
            db.flush()
        except IntegrityError as exc:
            raise JobOutputPersistenceError(JobOutputPersistenceReason.output_conflict) from exc
    else:
        output = existing
        if not _same_output(existing, document_id, web_view_url, output_folder_id, artifact, lease_generation):
            raise JobOutputPersistenceError(JobOutputPersistenceReason.output_conflict)

    case = db.execute(select(TranscriptionOutputReconciliation).where(TranscriptionOutputReconciliation.job_source_id == rel.id)).scalar_one_or_none()
    if case is not None:
        case.status = OutputReconciliationStatus.resolved
        case.resolved_output_id = output.id
        case.resolved_at = now
        case.updated_at = now
    required_ids = [rel.id for rel in authority.job_source_relations if rel.status != JobSourceStatus.skipped]
    from .job_cached_transcript import retire_cached_yandex_result
    retire_cached_yandex_result(db, job_id=job.id, job_source_id=rel.id)
    persisted_count = db.execute(select(func.count(TranscriptionJobOutput.id)).where(TranscriptionJobOutput.job_id == job.id, TranscriptionJobOutput.job_source_id.in_(required_ids or ["__none__"]))).scalar_one()
    required_count = len(required_ids)
    completed = required_count > 0 and persisted_count == required_count
    if completed:
        from .job_notifications import ensure_terminal_notification_intents

        _require_job_boundary(db, job, lease_owner_id, lease_generation, now)
        job.status = JobStatus.completed
        job.finished_at = now
        job.updated_at = now
        job.error_code = None
        job.error_message = None
        finalize_job_provider_accounting(db, job=job, now=now)
        invalidate_job_lease(job)
        ensure_terminal_notification_intents(db, job=job, now=now)
        db.flush()
    return JobOutputPersistenceResult(job.id, rel.id, output.id, job.status, int(persisted_count), required_count, completed, lease_generation)


def _require_job_boundary(db: Session, job: TranscriptionJob, owner: str, generation: int, now: datetime) -> None:
    if job.status != JobStatus.processing:
        raise JobOutputPersistenceError(JobOutputPersistenceReason.job_not_processing)
    if job.lease_owner_id != owner or job.lease_generation != generation:
        raise JobOutputPersistenceError(JobOutputPersistenceReason.lease_not_owned)
    if not is_lease_active(job, now):
        raise JobOutputPersistenceError(JobOutputPersistenceReason.lease_not_active)
    if job.cancel_requested_at is not None:
        raise JobOutputPersistenceError(JobOutputPersistenceReason.cancellation_requested)


def _load_locked_output_authority(
    db: Session,
    *,
    job_id: str,
    job_source_id: str,
    lease_owner_id: str,
    lease_generation: int,
    output_folder_id: str,
    now: datetime,
) -> _LockedOutputAuthority:
    job = db.execute(select(TranscriptionJob).where(TranscriptionJob.id == job_id).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if job is None:
        raise JobOutputPersistenceError(JobOutputPersistenceReason.job_not_found)
    _require_job_boundary(db, job, lease_owner_id, lease_generation, now)

    # Project is a read-only authorization lookup for the worker. The API
    # archive path serializes through the locked job row, so persistence keeps
    # the race guard without granting the worker UPDATE on projects.
    project = db.execute(select(Project).where(Project.id == job.project_id).execution_options(populate_existing=True)).scalar_one_or_none()
    if project is None or project.owner_user_id != job.owner_user_id or project.archived_at is not None:
        raise JobOutputPersistenceError(JobOutputPersistenceReason.project_unavailable)
    if not job.output_drive_folder_id:
        raise JobOutputPersistenceError(JobOutputPersistenceReason.output_folder_changed)
    if job.output_drive_folder_id != output_folder_id:
        raise JobOutputPersistenceError(JobOutputPersistenceReason.output_folder_changed)

    relations = tuple(
        db.execute(
            select(TranscriptionJobSource)
            .where(TranscriptionJobSource.job_id == job.id)
            .order_by(TranscriptionJobSource.position, TranscriptionJobSource.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalars().all()
    )
    selected = next((rel for rel in relations if rel.id == job_source_id), None)
    if selected is None:
        raise JobOutputPersistenceError(JobOutputPersistenceReason.job_source_not_found)
    if selected.status == JobSourceStatus.skipped:
        raise JobOutputPersistenceError(JobOutputPersistenceReason.job_source_not_processable)

    source = db.execute(select(Source).where(Source.id == selected.source_id).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    from .job_cached_transcript import fully_cached_relation
    cached = fully_cached_relation(db, job, selected.id, now)
    if source is None or source.project_id != job.project_id or (not cached and (source.upload_status != SourceUploadStatus.uploaded or source.deleted_at is not None)):
        raise JobOutputPersistenceError(JobOutputPersistenceReason.job_source_not_processable)
    return _LockedOutputAuthority(job, project, selected, source, relations)


def _same_output(existing: TranscriptionJobOutput, document_id: str, web_view_url: str, output_folder_id: str, artifact: GoogleDocsTranscriptArtifact, generation: int) -> bool:
    return (
        existing.document_id == document_id
        and existing.web_view_url == web_view_url
        and existing.output_drive_folder_id == output_folder_id
        and existing.output_kind == artifact.output_kind
        and existing.transcript_standard == TRANSCRIPT_STANDARD
        and existing.document_character_count == artifact.character_count
        and existing.document_created_at == artifact.created_at
        and existing.lease_generation == generation
    )
