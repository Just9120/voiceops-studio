from __future__ import annotations

import hashlib
import hmac
import json
import math
from datetime import datetime
from enum import Enum

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .elevenlabs_transcription import (
    ElevenLabsTranscriptResult,
    normalize_elevenlabs_transcript_response,
)
from .models import (
    TranscriptionJob,
    TranscriptionJobSource,
    TranscriptionJobSourceAttempt,
    TranscriptionProviderPartCheckpoint,
    JobStatus,
)
from .security import decrypt, encrypt, master_key_from_b64
from .transcription_metadata import selected_model


class ProviderPartCheckpointReason(str, Enum):
    scope_conflict = "provider_part_checkpoint_scope_conflict"
    shape_conflict = "provider_part_checkpoint_shape_conflict"
    persistence_failed = "provider_part_checkpoint_persistence_failed"
    decryption_failed = "provider_part_checkpoint_decryption_failed"
    payload_invalid = "provider_part_checkpoint_payload_invalid"
    complete_set_unavailable = "provider_complete_checkpoint_set_unavailable"


class ProviderPartCheckpointError(RuntimeError):
    def __init__(self, reason: ProviderPartCheckpointReason):
        self.reason = reason
        super().__init__(reason.value)


def save_provider_part_checkpoint(
    db: Session,
    *,
    job_id: str,
    job_source_id: str,
    part_index: int,
    total_parts: int,
    timeline_offset_seconds: float,
    duration_seconds: float,
    result: ElevenLabsTranscriptResult,
    settings,
    now: datetime,
) -> TranscriptionProviderPartCheckpoint:
    job, relation = _scope(db, job_id, job_source_id)
    _validate_shape(part_index, total_parts, timeline_offset_seconds, duration_seconds)
    serialized = json.loads(_serialize(result))
    serialized["_checkpoint_shape"] = [job.owner_user_id, job.project_id, job.id,
        relation.id, part_index, total_parts, float(timeline_offset_seconds), float(duration_seconds)]
    payload = json.dumps(serialized, ensure_ascii=False, separators=(",", ":"))
    key = master_key_from_b64(settings.master_key_b64())
    payload_hmac = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    # Checkpoints are immutable and the worker deliberately has no UPDATE
    # privilege on this table. PostgreSQL treats SELECT ... FOR UPDATE as an
    # UPDATE-capable operation even when no row exists, so the active job lease
    # is the concurrency boundary and this idempotency read must stay unlocked.
    existing = db.execute(
        select(TranscriptionProviderPartCheckpoint)
        .where(
            TranscriptionProviderPartCheckpoint.job_source_id == relation.id,
            TranscriptionProviderPartCheckpoint.part_index == part_index,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if not _row_shape_matches(
            existing,
            job,
            total_parts,
            timeline_offset_seconds,
            duration_seconds,
        ) or not hmac.compare_digest(existing.payload_hmac, payload_hmac):
            raise ProviderPartCheckpointError(ProviderPartCheckpointReason.shape_conflict)
        return existing

    checkpoint_id = _new_checkpoint_id()
    try:
        ciphertext, nonce = encrypt(
            payload,
            key,
            _checkpoint_aad(
                job.owner_user_id,
                job.project_id,
                job.id,
                relation.id,
                checkpoint_id,
                part_index,
            ),
        )
    except Exception as exc:
        raise ProviderPartCheckpointError(ProviderPartCheckpointReason.persistence_failed) from exc
    row = TranscriptionProviderPartCheckpoint(
        id=checkpoint_id,
        owner_user_id=job.owner_user_id,
        project_id=job.project_id,
        job_id=job.id,
        job_source_id=relation.id,
        part_index=part_index,
        total_parts=total_parts,
        timeline_offset_seconds=timeline_offset_seconds,
        duration_seconds=duration_seconds,
        provider=job.provider or "elevenlabs",
        model=selected_model(job.provider or "elevenlabs", job.options_json, job.operating_mode),
        ciphertext=ciphertext,
        nonce=nonce,
        key_id=settings.credential_key_id,
        payload_hmac=payload_hmac,
        created_at=now,
        expires_at=None,
    )
    db.add(row)
    db.flush()
    return row


def load_provider_part_checkpoints(
    db: Session,
    *,
    job_id: str,
    job_source_id: str,
    parts,
    settings,
    now: datetime,
    require_complete: bool = False,
) -> tuple[ElevenLabsTranscriptResult, ...]:
    job, relation = _scope(db, job_id, job_source_id)
    rows = db.execute(
        select(TranscriptionProviderPartCheckpoint)
        .where(TranscriptionProviderPartCheckpoint.job_source_id == relation.id)
        .order_by(TranscriptionProviderPartCheckpoint.part_index)
    ).scalars().all()
    if require_complete and len(rows) != len(parts):
        raise ProviderPartCheckpointError(ProviderPartCheckpointReason.complete_set_unavailable)
    if not rows:
        return ()
    total_parts = len(parts)
    if total_parts < 1 or len(rows) > total_parts:
        raise ProviderPartCheckpointError(ProviderPartCheckpointReason.shape_conflict)
    key = master_key_from_b64(settings.master_key_b64())
    loaded: list[ElevenLabsTranscriptResult] = []
    try:
        for expected_index, row in enumerate(rows):
            part = parts[expected_index]
            if row.part_index != expected_index or not _row_shape_matches(
                row,
                job,
                total_parts,
                part.timeline_offset_seconds,
                part.duration_seconds,
            ):
                raise ProviderPartCheckpointError(ProviderPartCheckpointReason.shape_conflict)
            try:
                payload = decrypt(
                    row.ciphertext,
                    row.nonce,
                    key,
                    _checkpoint_aad(
                        row.owner_user_id,
                        row.project_id,
                        row.job_id,
                        row.job_source_id,
                        row.id,
                        row.part_index,
                    ),
                )
            except Exception as exc:
                raise ProviderPartCheckpointError(ProviderPartCheckpointReason.decryption_failed) from exc
            expected_hmac = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected_hmac, row.payload_hmac):
                raise ProviderPartCheckpointError(ProviderPartCheckpointReason.payload_invalid)
            try:
                decoded = json.loads(payload)
                shape = decoded.get("_checkpoint_shape")
                if shape is not None and shape != [row.owner_user_id, row.project_id, row.job_id,
                    row.job_source_id, row.part_index, row.total_parts,
                    float(row.timeline_offset_seconds), float(row.duration_seconds)]:
                    raise ProviderPartCheckpointError(ProviderPartCheckpointReason.shape_conflict)
                normalized = normalize_elevenlabs_transcript_response(decoded)
            except Exception as exc:
                raise ProviderPartCheckpointError(ProviderPartCheckpointReason.payload_invalid) from exc
            loaded.append(normalized)
        return tuple(loaded)
    except BaseException:
        for result in loaded:
            result.revoke()
        raise


def checkpoint_resume_count(
    db: Session,
    *,
    job_source_id: str,
    total_parts: int | None,
    completed_parts: int,
    now: datetime,
) -> int:
    if total_parts is None or total_parts < 1 or completed_parts <= 0 or completed_parts > total_parts:
        return 0
    rows = db.execute(
        select(TranscriptionProviderPartCheckpoint)
        .where(TranscriptionProviderPartCheckpoint.job_source_id == job_source_id)
        .order_by(TranscriptionProviderPartCheckpoint.part_index)
    ).scalars().all()
    if len(rows) != completed_parts:
        return 0
    if [row.part_index for row in rows] != list(range(completed_parts)):
        return 0
    if any(row.total_parts != total_parts for row in rows):
        return 0
    return completed_parts


def complete_provider_attempt(db: Session, *, job_id: str, job_source_id: str, before_attempt: int | None = None) -> TranscriptionJobSourceAttempt | None:
    job, relation = _scope(db, job_id, job_source_id)
    statement = select(TranscriptionJobSourceAttempt).where(
        TranscriptionJobSourceAttempt.job_id == job.id,
        TranscriptionJobSourceAttempt.job_source_id == relation.id,
        TranscriptionJobSourceAttempt.owner_user_id == job.owner_user_id,
        TranscriptionJobSourceAttempt.project_id == job.project_id,
        TranscriptionJobSourceAttempt.attempt_number <= int(job.attempt_count or 0),
        TranscriptionJobSourceAttempt.provider_total_parts >= 1,
        TranscriptionJobSourceAttempt.provider_completed_parts == TranscriptionJobSourceAttempt.provider_total_parts,
    )
    if before_attempt is not None:
        statement = statement.where(TranscriptionJobSourceAttempt.attempt_number < before_attempt)
    return db.execute(statement.order_by(TranscriptionJobSourceAttempt.attempt_number.desc()).limit(1)).scalar_one_or_none()


def requires_complete_checkpoint_restore(db: Session, *, job_id: str, job_source_id: str) -> bool:
    """A fully returned earlier attempt never authorizes another provider call.

    Use the durable attempt record rather than checkpoint presence: loss or
    cleanup between enqueue and execution must not turn restore into paid STT.
    """
    job, _ = _scope(db, job_id, job_source_id)
    return complete_provider_attempt(
        db, job_id=job_id, job_source_id=job_source_id, before_attempt=int(job.attempt_count or 0),
    ) is not None


def delete_provider_part_checkpoints(
    db: Session,
    *,
    job_id: str | None = None,
    job_source_id: str | None = None,
) -> int:
    if not job_id and not job_source_id:
        raise ValueError("checkpoint deletion scope is required")
    statement = delete(TranscriptionProviderPartCheckpoint)
    if job_id:
        statement = statement.where(TranscriptionProviderPartCheckpoint.job_id == job_id)
    if job_source_id:
        statement = statement.where(TranscriptionProviderPartCheckpoint.job_source_id == job_source_id)
    return int(db.execute(statement).rowcount or 0)


DEFAULT_CHECKPOINT_CLEANUP_BATCH_SIZE = 500
MAX_CHECKPOINT_CLEANUP_BATCH_SIZE = 1000


def cleanup_expired_provider_part_checkpoints(
    db: Session,
    *,
    now: datetime,
    limit: int = DEFAULT_CHECKPOINT_CLEANUP_BATCH_SIZE,
) -> int:
    safe_limit = max(1, min(int(limit), MAX_CHECKPOINT_CLEANUP_BATCH_SIZE))
    # Keep unfinished text regardless of old expiry timestamps. Retirement is
    # authorized only by full success or explicit cancellation/resolution.
    retired_jobs = select(TranscriptionJob.id).where(
        (TranscriptionJob.status.in_((JobStatus.completed, JobStatus.cancelled)))
        | (TranscriptionJob.history_attention_resolved_at.is_not(None))
    )
    retired_ids = (
        select(TranscriptionProviderPartCheckpoint.id)
        .where(TranscriptionProviderPartCheckpoint.job_id.in_(retired_jobs))
        .order_by(
            TranscriptionProviderPartCheckpoint.created_at.asc(),
            TranscriptionProviderPartCheckpoint.id.asc(),
        )
        .limit(safe_limit)
    )
    return int(
        db.execute(
            delete(TranscriptionProviderPartCheckpoint).where(
                TranscriptionProviderPartCheckpoint.id.in_(retired_ids)
            )
        ).rowcount
        or 0
    )


def _scope(db: Session, job_id: str, job_source_id: str):
    job = db.get(TranscriptionJob, job_id)
    relation = db.get(TranscriptionJobSource, job_source_id)
    if job is None or relation is None or relation.job_id != job.id:
        raise ProviderPartCheckpointError(ProviderPartCheckpointReason.scope_conflict)
    return job, relation


def _validate_shape(part_index, total_parts, offset, duration):
    if (
        not isinstance(part_index, int)
        or not isinstance(total_parts, int)
        or total_parts < 1
        or part_index < 0
        or part_index >= total_parts
        or not math.isfinite(float(offset))
        or float(offset) < 0
        or not math.isfinite(float(duration))
        or float(duration) <= 0
    ):
        raise ProviderPartCheckpointError(ProviderPartCheckpointReason.shape_conflict)


def _row_shape_matches(row, job, total_parts, offset, duration) -> bool:
    return (
        row.owner_user_id == job.owner_user_id
        and row.project_id == job.project_id
        and row.job_id == job.id
        and row.total_parts == total_parts
        and row.provider == (job.provider or "elevenlabs")
        and row.model == selected_model(job.provider or "elevenlabs", job.options_json, job.operating_mode)
        and math.isclose(float(row.timeline_offset_seconds), float(offset), abs_tol=0.001)
        and math.isclose(float(row.duration_seconds), float(duration), abs_tol=0.001)
    )


def _serialize(result: ElevenLabsTranscriptResult) -> str:
    payload = {
        "text": result.text,
        "language_code": result.detected_language_code,
        "language_probability": result.language_probability,
        "words": [
            {
                "text": word.text,
                "start": word.start,
                "end": word.end,
                "type": word.type,
                "speaker_id": word.speaker_id,
            }
            for word in result.words
        ],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _checkpoint_aad(owner, project, job, relation, checkpoint, part_index) -> bytes:
    return (
        f"owner={owner};project={project};job={job};job_source={relation};"
        f"checkpoint={checkpoint};part={part_index};purpose=provider_part_checkpoint_v1"
    ).encode("utf-8")




def _new_checkpoint_id() -> str:
    import uuid

    return str(uuid.uuid4())
