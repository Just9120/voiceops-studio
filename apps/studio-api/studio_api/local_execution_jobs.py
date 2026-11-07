"""Local inference leases: owner/device/job fenced, no cloud transport."""
from datetime import timedelta
import json

from fastapi import HTTPException
from sqlalchemy import or_, select, tuple_

from .job_claim_lease import acquire_job_lease, is_lease_active, renew_job_lease
from .job_claim_readiness import build_claim_readiness
from .job_processing_lifecycle import acknowledge_job_cancellation, begin_job_processing, fail_job_processing
from .job_retry_recovery import classify_source_attempt_failure, prepare_current_attempt_sources
from .local_execution_devices import _utc, device_payload
from .models import JobSourceStatus, JobStatus, Project, TranscriptionJob
from .local_model_identity import job_model_identity

LOCAL_LEASE_TTL = timedelta(seconds=90)
LOCAL_CLAIM_PAGE_SIZE = 50
LOCAL_STAGES = ("source_download", "media_processing", "local_transcription", "local_result_upload")
LOCAL_FAILURES = frozenset({"local_input_unavailable", "local_model_unavailable", "local_runtime_unavailable",
                            "local_processing_failed", "local_worker_interrupted", "local_result_invalid"})


def device_model_in_use(db, device, model, *, active_only=False):
    statuses = (JobStatus.processing,) if active_only else (JobStatus.queued, JobStatus.processing)
    rows = db.scalars(select(TranscriptionJob.options_json).where(
        TranscriptionJob.owner_user_id == device.owner_user_id,
        TranscriptionJob.local_device_id == device.id, TranscriptionJob.provider == "nemotron",
        TranscriptionJob.local_result_ready_at.is_(None), TranscriptionJob.status.in_(statuses),
    ).execution_options(yield_per=100))
    try:
        return any(job_model_identity(options)[0] == model for options in rows)
    finally:
        rows.close()


def local_job_payload(job):
    relations = [relation for relation in job.sources if relation.status != JobSourceStatus.skipped]
    if len(relations) != 1:
        raise HTTPException(409, detail={"reason": "local_job_shape_invalid"})
    source = relations[0].source
    try:
        options = json.loads(job.options_json or "{}")
    except (TypeError, ValueError):
        options = {}
    model, revision = job_model_identity(job.options_json)
    return {"id": job.id, "lease_generation": job.lease_generation,
            "lease_expires_at": _utc(job.lease_expires_at).isoformat(),
            "source_id": source.id, "source_name": source.original_filename, "size_bytes": source.size_bytes,
            "model": model, "model_revision": revision, "language": job.language or "detect", "diarize": options.get("diarize", False),
            "progress": json.loads(job.work_progress_json) if job.work_progress_json else None}


def _scope(db, *, device, job_id, generation, now, allow_cancel=False):
    job = db.scalar(select(TranscriptionJob).where(TranscriptionJob.id == job_id,
        TranscriptionJob.owner_user_id == device.owner_user_id, TranscriptionJob.local_device_id == device.id
    ).with_for_update().execution_options(populate_existing=True))
    project = db.get(Project, job.project_id) if job is not None else None
    if job is None or project is None or project.owner_user_id != device.owner_user_id or project.archived_at is not None:
        raise HTTPException(404, detail={"reason": "local_job_unavailable"})
    model, _ = job_model_identity(job.options_json)
    if (job.provider != "nemotron" or model is None or model != device.model or job.media_timeline_version != 2
            or job.status != JobStatus.processing or job.local_result_ready_at is not None
            or job.lease_owner_id != "local:" + device.id or job.lease_generation != generation
            or not is_lease_active(job, now)):
        raise HTTPException(409, detail={"reason": "local_job_lease_changed"})
    if job.cancel_requested_at is not None and not allow_cancel:
        raise HTTPException(409, detail={"reason": "local_job_cancelled"})
    return job


def claim_local_job(db, *, device, now):
    if not device_payload(device, now=now)["ready"]:
        raise HTTPException(409, detail={"reason": "local_device_not_ready"})
    # Authentication holds the device row lock: a device has one active model
    # execution. Lost claim responses return the same lease, not a second job.
    active = db.scalar(select(TranscriptionJob).where(
        TranscriptionJob.local_device_id == device.id, TranscriptionJob.owner_user_id == device.owner_user_id,
        TranscriptionJob.provider == "nemotron", TranscriptionJob.local_result_ready_at.is_(None),
        TranscriptionJob.status == JobStatus.processing, TranscriptionJob.lease_expires_at > now,
    ).order_by(TranscriptionJob.created_at, TranscriptionJob.id).limit(1).with_for_update())
    if active is not None:
        active = _scope(db, device=device, job_id=active.id, generation=active.lease_generation, now=now, allow_cancel=True)
        if active.cancel_requested_at is not None:
            acknowledge_job_cancellation(db, job_id=active.id, lease_owner_id="local:" + device.id,
                lease_generation=active.lease_generation, now=now, retire_part_checkpoints=False)
            return None
        return active
    candidates = select(TranscriptionJob).join(Project, Project.id == TranscriptionJob.project_id).where(
        TranscriptionJob.local_device_id == device.id, TranscriptionJob.owner_user_id == device.owner_user_id,
        Project.owner_user_id == device.owner_user_id, Project.archived_at.is_(None),
        TranscriptionJob.provider == "nemotron", TranscriptionJob.local_result_ready_at.is_(None),
        TranscriptionJob.media_timeline_version == 2,
        TranscriptionJob.status == JobStatus.queued, TranscriptionJob.cancel_requested_at.is_(None),
        or_(TranscriptionJob.lease_expires_at.is_(None), TranscriptionJob.lease_expires_at <= now),
        or_(TranscriptionJob.retry_not_before_at.is_(None), TranscriptionJob.retry_not_before_at <= now),
    )
    queue_order = (TranscriptionJob.created_at, TranscriptionJob.id)
    page = candidates.order_by(*queue_order).limit(LOCAL_CLAIM_PAGE_SIZE)
    while True:
        jobs = db.scalars(page).all()
        if not jobs:
            return None
        for job in jobs:
            if not _matches_local_claim(job, device, now):
                continue
            # Lock and refresh only the candidate that could be claimed. A
            # cancellation or another transition may have changed it during the scan.
            locked_job = db.scalar(candidates.where(TranscriptionJob.id == job.id)
                .with_for_update(of=TranscriptionJob, skip_locked=True)
                .execution_options(populate_existing=True))
            if locked_job is None or not _matches_local_claim(locked_job, device, now):
                continue
            lease = acquire_job_lease(db, job_id=locked_job.id, lease_owner_id="local:" + device.id,
                local_device_id=device.id, now=now, lease_ttl=LOCAL_LEASE_TTL)
            begin_job_processing(db, job_id=locked_job.id, lease_owner_id=lease.lease_owner_id,
                lease_generation=lease.lease_generation, now=now)
            prepare_current_attempt_sources(db, job_id=locked_job.id, lease_owner_id=lease.lease_owner_id,
                lease_generation=lease.lease_generation, now=now)
            locked_job.local_input_receipt_json = None
            locked_job.work_progress_json = None
            return locked_job
        last = jobs[-1]
        page = candidates.where(tuple_(*queue_order) > (last.created_at, last.id)).order_by(*queue_order).limit(LOCAL_CLAIM_PAGE_SIZE)


def _matches_local_claim(job, device, now):
    return (job_model_identity(job.options_json)[0] == device.model
            and sum(relation.status != JobSourceStatus.skipped for relation in job.sources) == 1
            and build_claim_readiness(job, now=now)["ready_for_future_claim"])


def heartbeat_local_job(db, *, device, job_id, generation, stage, sequence, completed, total, unit, now):
    job = _scope(db, device=device, job_id=job_id, generation=generation, now=now, allow_cancel=True)
    if job.cancel_requested_at is not None:
        acknowledge_job_cancellation(db, job_id=job.id, lease_owner_id="local:" + device.id,
            lease_generation=generation, now=now, retire_part_checkpoints=False)
        return {"cancelled": True}
    if stage not in LOCAL_STAGES or type(sequence) is not int or not 1 <= sequence <= 2147483647:
        raise HTTPException(422, detail={"reason": "local_progress_invalid"})
    # Inference has no trusted progress fraction. Only downloaded/uploaded
    # bytes or actual media seconds from preparation may be reported.
    if completed is None and total is None and unit is None:
        pass
    elif (stage == "local_transcription" or unit not in {"bytes", "seconds"}
            or type(completed) not in {int, float} or type(total) not in {int, float}
            or not 0 <= completed <= total <= (2147483647 if unit == "bytes" else 43200)
            or (stage in {"source_download", "local_result_upload"} and unit != "bytes")):
        raise HTTPException(422, detail={"reason": "local_progress_invalid"})
    previous = json.loads(job.work_progress_json) if job.work_progress_json else None
    content = {"stage": stage, "completed": completed, "total": total, "unit": unit}
    if previous is not None:
        if (sequence < previous["sequence"] or LOCAL_STAGES.index(stage) < LOCAL_STAGES.index(previous["stage"])
                or (sequence == previous["sequence"] and any(previous.get(key) != value for key, value in content.items()))
                or (stage == previous["stage"] and previous["completed"] is not None and completed is not None
                    and (completed < previous["completed"] or total != previous["total"]))):
            raise HTTPException(409, detail={"reason": "local_progress_changed"})
    renew_job_lease(db, job_id=job.id, lease_owner_id="local:" + device.id, lease_generation=generation,
        now=now, lease_ttl=LOCAL_LEASE_TTL)
    device.last_seen_at = device.updated_at = now
    # A same-sequence liveness retry renews the lease but does not pretend the
    # measured work advanced. API/UI keep the previous progress timestamp.
    if previous is None or sequence > previous["sequence"]:
        started = previous["started_at"] if previous is not None and stage == previous["stage"] else now.isoformat()
        job.work_progress_json = json.dumps({**content, "sequence": sequence, "generation": generation,
            "started_at": started, "updated_at": now.isoformat()}, separators=(",", ":"))
    db.flush()
    return {"cancelled": False, "lease_expires_at": _utc(job.lease_expires_at).isoformat()}


def fail_local_job(db, *, device, job_id, generation, reason, now):
    if reason not in LOCAL_FAILURES:
        raise HTTPException(422, detail={"reason": "local_failure_invalid"})
    job = _scope(db, device=device, job_id=job_id, generation=generation, now=now, allow_cancel=True)
    if job.cancel_requested_at is not None:
        acknowledge_job_cancellation(db, job_id=job.id, lease_owner_id="local:" + device.id,
            lease_generation=generation, now=now, retire_part_checkpoints=False)
        return {"cancelled": True}
    for relation in job.sources:
        if relation.status != JobSourceStatus.skipped:
            classify_source_attempt_failure(db, job_source_id=relation.id, failure_code=reason, now=now,
                job_id=job.id, lease_owner_id="local:" + device.id, lease_generation=generation)
    fail_job_processing(db, job_id=job.id, lease_owner_id="local:" + device.id, lease_generation=generation,
        now=now, error_code=reason, error_message=reason)
    return {"failed": True}


def fence_device_jobs(db, *, device_id, owner_user_id, now):
    # An already accepted result no longer needs the PC: preserve VPS export.
    jobs = db.scalars(select(TranscriptionJob).where(TranscriptionJob.local_device_id == device_id,
        TranscriptionJob.owner_user_id == owner_user_id, TranscriptionJob.provider == "nemotron",
        TranscriptionJob.local_result_ready_at.is_(None), TranscriptionJob.status.in_((JobStatus.queued, JobStatus.processing))
    ).with_for_update()).all()
    for job in jobs:
        for relation in job.sources:
            if relation.status != JobSourceStatus.skipped:
                classify_source_attempt_failure(db, job_source_id=relation.id, failure_code="local_device_revoked", now=now)
        job.status = JobStatus.cancelled if job.cancel_requested_at is not None else JobStatus.failed
        job.error_code = job.error_message = "local_device_revoked"
        job.finished_at = job.updated_at = now
        job.lease_owner_id = job.lease_expires_at = None
        job.lease_generation += 1
        job.retry_not_before_at = job.automatic_retry_reason = None
    db.flush()
    return len(jobs)
