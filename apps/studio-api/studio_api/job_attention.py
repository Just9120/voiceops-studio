"""Shared read/resolve contract for an acknowledged later transcription result."""
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .models import (
    JobSourceStatus, JobStatus, OutputReconciliationStatus, TranscriptionJob,
    TranscriptionJobOutput, TranscriptionJobSource, TranscriptionOutputReconciliation,
)
from .transcript_catalog import GOOGLE_DOCS_TRANSCRIPT_OUTPUT_KIND
from .transcript_docx import DOCX_OUTPUT_KIND


def confirmed_later_results_query(db: Session, job: TranscriptionJob):
    """Only the same owner, source sequence, clip and a persisted result can link."""
    sources = sorted(job.sources, key=lambda item: item.position)
    source_count = (
        select(func.count(TranscriptionJobSource.id))
        .where(TranscriptionJobSource.job_id == TranscriptionJob.id)
        .correlate(TranscriptionJob)
        .scalar_subquery()
    )
    google_receipt = (
        select(TranscriptionOutputReconciliation.id)
        .where(
            TranscriptionOutputReconciliation.resolved_output_id == TranscriptionJobOutput.id,
            TranscriptionOutputReconciliation.status == OutputReconciliationStatus.resolved,
            TranscriptionOutputReconciliation.expected_output_provider == "google_drive",
            TranscriptionOutputReconciliation.expected_document_sha256.is_not(None),
        )
        .correlate(TranscriptionJobOutput)
        .exists()
    )
    verified_output = (
        select(TranscriptionJobOutput.id)
        .where(
            TranscriptionJobOutput.job_source_id == TranscriptionJobSource.id,
            TranscriptionJobOutput.job_id == TranscriptionJobSource.job_id,
            or_(
                TranscriptionJobOutput.output_kind == DOCX_OUTPUT_KIND,
                (TranscriptionJobOutput.output_kind == GOOGLE_DOCS_TRANSCRIPT_OUTPUT_KIND) & google_receipt,
            ),
        )
        .correlate(TranscriptionJobSource)
        .exists()
    )
    required_source = select(TranscriptionJobSource.id).where(
        TranscriptionJobSource.job_id == TranscriptionJob.id,
        TranscriptionJobSource.status != JobSourceStatus.skipped,
    ).correlate(TranscriptionJob)
    query = db.query(TranscriptionJob).filter(
        TranscriptionJob.owner_user_id == job.owner_user_id,
        TranscriptionJob.project_id == job.project_id,
        TranscriptionJob.id != job.id,
        TranscriptionJob.created_at > job.created_at,
        TranscriptionJob.status == JobStatus.completed,
        TranscriptionJob.media_clip_start_seconds.is_not_distinct_from(job.media_clip_start_seconds),
        TranscriptionJob.media_clip_end_seconds.is_not_distinct_from(job.media_clip_end_seconds),
        source_count == len(sources),
        required_source.exists(),
        ~required_source.where(~verified_output).exists(),
    )
    if not sources:
        return query.filter(False)
    for source in sources:
        query = query.filter(TranscriptionJob.sources.any(
            (TranscriptionJobSource.source_id == source.source_id)
            & (TranscriptionJobSource.position == source.position)
        ))
    return query


def recent_attention_candidates(db: Session, job: TranscriptionJob) -> list[dict]:
    return [
        {"id": candidate.id, "title": (candidate.title or "").strip() or None, "created_at": candidate.created_at.isoformat()}
        for candidate in confirmed_later_results_query(db, job)
        .order_by(TranscriptionJob.created_at.desc(), TranscriptionJob.id.desc())
        .limit(50)
        .all()
    ]
