"""Shared read/resolve contract for an acknowledged later transcription result."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import JobStatus, TranscriptionJob, TranscriptionJobOutput, TranscriptionJobSource
from .transcript_catalog import TRANSCRIPT_OUTPUT_KINDS


def confirmed_later_results_query(db: Session, job: TranscriptionJob):
    """Only the same owner, source sequence, clip and a persisted result can link."""
    sources = sorted(job.sources, key=lambda item: item.position)
    source_count = (
        select(func.count(TranscriptionJobSource.id))
        .where(TranscriptionJobSource.job_id == TranscriptionJob.id)
        .correlate(TranscriptionJob)
        .scalar_subquery()
    )
    output_exists = (
        select(TranscriptionJobOutput.id)
        .where(
            TranscriptionJobOutput.job_id == TranscriptionJob.id,
            TranscriptionJobOutput.output_kind.in_(TRANSCRIPT_OUTPUT_KINDS),
        )
        .correlate(TranscriptionJob)
        .exists()
    )
    query = db.query(TranscriptionJob).filter(
        TranscriptionJob.owner_user_id == job.owner_user_id,
        TranscriptionJob.project_id == job.project_id,
        TranscriptionJob.id != job.id,
        TranscriptionJob.created_at > job.created_at,
        TranscriptionJob.status == JobStatus.completed,
        TranscriptionJob.media_clip_start_seconds.is_not_distinct_from(job.media_clip_start_seconds),
        TranscriptionJob.media_clip_end_seconds.is_not_distinct_from(job.media_clip_end_seconds),
        source_count == len(sources),
        output_exists,
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
