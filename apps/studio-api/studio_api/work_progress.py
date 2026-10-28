"""Measured user progress, separate from worker liveness and durable lifecycle."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timezone
import json
import math
from time import monotonic

from sqlalchemy import update, select

from .security import utcnow

_reporter = ContextVar("work_progress_reporter", default=None)
STAGES = frozenset({"source_download", "source_copy", "media_probe", "media_processing", "media_analysis", "speech_analysis",
    "provider_upload", "provider_wait", "part_merge", "document_output", "audio_processing"})
UNITS = frozenset({"bytes", "seconds", "files", "parts"})


def report_work(stage, completed=None, total=None, unit=None):
    reporter = _reporter.get()
    if reporter is not None:
        reporter(stage, completed, total, unit)


def progress_payload(raw):
    try:
        value = json.loads(raw or "null")
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict) or value.get("stage") not in STAGES:
        return None
    if value.get("unit") not in UNITS | {None}:
        return None
    for key in ("completed", "total"):
        number = value.get(key)
        if number is not None and (isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number < 0):
            return None
    return {key: value.get(key) for key in ("stage", "completed", "total", "unit", "started_at", "updated_at", "sequence", "generation")}


@contextmanager
def measured_work(db, *, job, owner, generation, clock=utcnow):
    """Persist only while the exact active lease still owns this job.

    Calls run on the worker's main thread, outside critical lifecycle writes.
    Reader threads may collect measurements but never touch the DB session.
    """
    previous = progress_payload(db.scalar(select(type(job).work_progress_json).where(type(job).id == job.id))) or {}
    sequence = previous.get("sequence") if previous.get("generation") == generation else 0
    if not isinstance(sequence, int) or sequence < 0:
        sequence = 0
    last_stage, last_value, last_time = None, None, -math.inf
    started_at = None
    def record(stage, completed, total, unit):
        nonlocal last_stage, last_value, last_time, sequence, started_at
        if stage not in STAGES or unit not in UNITS | {None}:
            raise ValueError("invalid_work_progress")
        for number in (completed, total):
            if number is not None and (isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number < 0):
                raise ValueError("invalid_work_measurement")
        now = clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        moment = monotonic()
        same = stage == last_stage
        if same and (last_value == (completed, total, unit) or moment - last_time < 3):
            return
        if not same:
            started_at = now.isoformat()
        sequence += 1
        payload = dict(stage=stage, completed=completed, total=total, unit=unit,
            started_at=started_at, updated_at=now.isoformat(), sequence=sequence, generation=generation)
        model = type(job)
        from .models import AudioPreparationJob, AudioPreparationStatus, JobStatus
        statuses = ([AudioPreparationStatus.analyzing, AudioPreparationStatus.processing,
            AudioPreparationStatus.completed, AudioPreparationStatus.preview_ready] if model is AudioPreparationJob else [JobStatus.processing])
        result = db.execute(update(model).where(model.id == job.id, model.owner_user_id == job.owner_user_id,
            model.lease_owner_id == owner, model.lease_generation == generation,
            model.lease_expires_at > (now.astimezone(timezone.utc).replace(tzinfo=None) if now.tzinfo else now),
            model.cancel_requested_at.is_(None), model.status.in_(statuses))
            .values(work_progress_json=json.dumps(payload, separators=(",", ":"))).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            db.rollback()
            if model is AudioPreparationJob:
                from .audio_preparation_service import AudioPreparationServiceError, AudioPreparationServiceReason
                db.refresh(job)
                reason = (AudioPreparationServiceReason.cancellation_requested if job.cancel_requested_at is not None
                    else AudioPreparationServiceReason.lease_unavailable)
                raise AudioPreparationServiceError(reason)
            from .preparation_control import PreparationInterrupted
            raise PreparationInterrupted("work_progress_authority_changed")
        db.commit()
        last_stage, last_value, last_time = stage, (completed, total, unit), moment
    token = _reporter.set(record)
    try:
        yield
    finally:
        _reporter.reset(token)
