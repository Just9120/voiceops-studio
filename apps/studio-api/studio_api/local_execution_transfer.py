"""Verified input bytes and encrypted full-result handoff for the paired PC."""
from contextlib import contextmanager
from dataclasses import asdict
import gzip
import hashlib
import io
import json
import math
import re
import zlib
from uuid import uuid4
from time import monotonic
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select

from .audio_timeline import AudioTimeline, AudioTimelineError
from .batch_stt_transport import MAX_RESPONSE_BYTES
from .elevenlabs_transcription import ElevenLabsTranscriptionError
from .job_claim_lease import invalidate_job_lease
from .job_processing_lifecycle import fail_job_processing
from .job_retry_recovery import classify_source_attempt_failure, mark_attempt_provider_started, mark_attempt_provider_returned
from .job_source_materialization import materialize_processing_job_source
from .local_execution_devices import authenticate_device
from .local_execution_jobs import _scope
from .models import JobSourceStatus, JobStatus, Project, TranscriptionJob, SttProviderOperation
from .local_model_identity import LEGACY_NEMOTRON_REVISION, PARAKEET_MAX_DURATION_SECONDS, PARAKEET_MODEL, job_model_identity
from .nemotron_local_result import NEMOTRON_MAX_DURATION_SECONDS, NEMOTRON_MODEL, normalize_nemotron_local_result
from .provider_result_cache import persist_operation_result
from .security import utcnow
from .transcript_timeline import TranscriptClockSelection, persist_transcript_clock, select_transcript_clock
from .transcription_options import job_diarization_enabled

MAX_ENVELOPE_BYTES = MAX_RESPONSE_BYTES + 4096


def _error(reason, status=409):
    return HTTPException(status, detail={"reason": reason}, headers={"Cache-Control": "no-store"})


def _source_signature(source):
    fields = ("id", "project_id", "source_type", "reference_class", "mime_type", "size_bytes", "s3_bucket", "s3_object_key",
              "drive_file_id", "drive_revision_id", "drive_md5_checksum", "drive_sha256_checksum", "prepared_audio_context_json")
    data = {field: getattr(getattr(source, field), "value", getattr(source, field)) for field in fields}
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _one_relation(job):
    relations = [relation for relation in job.sources if relation.status != JobSourceStatus.skipped]
    if len(relations) != 1 or relations[0].source is None:
        raise _error("local_job_shape_invalid")
    return relations[0]


def _selection_dict(selection):
    data = asdict(selection)
    data["parent"] = selection.parent.serialize() if selection.parent else None
    return data


def _load_receipt(job, relation, generation):
    try:
        receipt = json.loads(job.local_input_receipt_json or "null")
        if (not isinstance(receipt, dict) or receipt.get("generation") != generation or receipt.get("device_id") != job.local_device_id
                or receipt.get("relation_id") != relation.id or receipt.get("source_id") != relation.source_id
                or receipt.get("source_signature") != _source_signature(relation.source)):
            raise ValueError()
        data = dict(receipt["selection"])
        if data["parent"] is not None:
            data["parent"] = AudioTimeline.parse(data["parent"])
        selection = TranscriptClockSelection(**data)
        if ((selection.version, selection.original_start, selection.original_end)
                != (job.media_timeline_version, job.media_clip_start_seconds, job.media_clip_end_seconds)
                or selection.prepared_context != relation.source.prepared_audio_context_json):
            raise ValueError()
        return receipt, selection
    except (ValueError, TypeError, KeyError, AudioTimelineError):
        raise _error("local_input_changed") from None


@contextmanager
def open_local_input(db, *, device, raw_token, job_id, generation, settings, clock=utcnow, materializer=None, on_scoped=None):
    job = _scope(db, device=device, job_id=job_id, generation=generation, now=clock(), on_scoped=on_scoped)
    relation = _one_relation(job)
    relation_id = relation.id
    expected_clip = (job.media_timeline_version, job.media_clip_start_seconds, job.media_clip_end_seconds)
    device_id = device.id
    db.commit()  # Never hold the device/job row locks while downloading from storage.
    opener = materializer or materialize_processing_job_source
    with opener(db, job_id=job_id, job_source_id=relation_id, lease_owner_id="local:" + device_id,
                lease_generation=generation, settings=settings, clock=clock) as source:
        digest = hashlib.sha256()
        count = 0
        while chunk := source.stream.read(1024 * 1024):
            count += len(chunk)
            if count > settings.source_max_upload_bytes:
                raise _error("local_input_too_large")
            digest.update(chunk)
        if count != source.byte_count:
            raise _error("local_input_changed")
        source.stream.seek(0)
        device = authenticate_device(db, raw_token)
        job = _scope(db, device=device, job_id=job_id, generation=generation, now=clock())
        relation = _one_relation(job)
        if ((job.media_timeline_version, job.media_clip_start_seconds, job.media_clip_end_seconds) != expected_clip
                or relation.id != relation_id or source.identity.source_id != relation.source_id
                or relation.source.prepared_audio_context_json != source.prepared_audio_context_json):
            raise _error("local_input_changed")
        selection = select_transcript_clock(job, source)
        receipt = {"version": 1, "device_id": device_id, "generation": generation, "source_id": relation.source_id,
            "relation_id": relation.id, "source_sha256": digest.hexdigest(), "byte_count": count,
            "source_signature": _source_signature(relation.source), "selection": _selection_dict(selection)}
        # Same-lease download retries cannot overwrite the earlier measured clock.
        if job.local_input_receipt_json is not None:
            previous, _ = _load_receipt(job, relation, generation)
            if any(previous.get(key) != value for key, value in receipt.items()):
                raise _error("local_input_changed")
        else:
            job.local_input_receipt_json = json.dumps(receipt, separators=(",", ":"))
        db.commit()

        def chunks():
            last_check = 0
            while chunk := source.stream.read(1024 * 1024):
                if monotonic() - last_check >= 2:
                    current_device = authenticate_device(db, raw_token)
                    _scope(db, device=current_device, job_id=job_id, generation=generation, now=clock())
                    db.commit()
                    last_check = monotonic()
                yield chunk
        yield chunks(), receipt


def prepare_local_input(db, *, device, job_id, generation, source_sha256, source_duration_seconds, settings, now, on_scoped=None):
    job = _scope(db, device=device, job_id=job_id, generation=generation, now=now, on_scoped=on_scoped)
    relation = _one_relation(job)
    receipt, selection = _load_receipt(job, relation, generation)
    if (source_sha256 != receipt["source_sha256"] or type(source_duration_seconds) not in (int, float)
            or not 0 < source_duration_seconds <= 604800 or not math.isfinite(source_duration_seconds)):
        raise _error("local_input_invalid", 422)
    try:
        record = selection.record(source_duration_seconds)
        duration = (AudioTimeline.parse(record).output_duration_seconds if record and record != '{"version":2,"clock":"prepared_unavailable"}'
                    else source_duration_seconds - (selection.prepared_start or 0))
    except (ValueError, AudioTimelineError):
        raise _error("local_input_duration_changed") from None
    model, _ = job_model_identity(job.options_json)
    model_limit = PARAKEET_MAX_DURATION_SECONDS if model == PARAKEET_MODEL else NEMOTRON_MAX_DURATION_SECONDS
    if not 0 < duration <= min(settings.media_max_duration_seconds, model_limit):
        raise _error("media_duration_too_long", 422)
    measured = receipt.get("source_duration_seconds")
    if measured is not None and abs(measured - source_duration_seconds) > .000001:
        raise _error("local_input_duration_changed")
    from .long_media_preflight import confirmed_source_duration, record_long_media_preflight
    confirmed = confirmed_source_duration(job, relation.id, clock_selection=selection)
    if duration > settings.media_duration_warning_seconds and (confirmed is None or abs(confirmed - source_duration_seconds) > .5):
        # Retain the existing measured-duration/retry confirmation contract. This
        # creates no cost estimate for local compute and makes no cloud request.
        record_long_media_preflight(db, job_id=job.id, relation_id=relation.id, duration=source_duration_seconds,
            settings=settings, owner="local:" + device.id, generation=generation, now=now, clock_selection=selection)
        classify_source_attempt_failure(db, job_source_id=relation.id, failure_code="media_duration_confirmation_required",
            now=now, job_id=job.id, lease_owner_id="local:" + device.id, lease_generation=generation)
        fail_job_processing(db, job_id=job.id, lease_owner_id="local:" + device.id, lease_generation=generation,
            now=now, error_code="media_duration_confirmation_required", error_message="media_duration_confirmation_required")
        db.commit()
        raise _error("media_duration_confirmation_required")
    source = SimpleNamespace(identity=SimpleNamespace(source_id=relation.source_id))
    persist_transcript_clock(db, job_id=job.id, job_source_id=relation.id, source=source, selection=selection,
        observed_source_duration=source_duration_seconds, lease_owner_id="local:" + device.id, lease_generation=generation, now=now)
    receipt["source_duration_seconds"] = source_duration_seconds
    receipt["prepared_duration_seconds"] = duration
    job.local_input_receipt_json = json.dumps(receipt, separators=(",", ":"))
    db.flush()
    return {"clip_start_seconds": selection.prepared_start or 0, "clip_end_seconds": selection.prepared_end,
            "prepared_duration_seconds": duration, "source_sha256": receipt["source_sha256"]}


def decode_local_result(body):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    def invalid_constant(_):
        raise ValueError()
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
            raw = stream.read(MAX_ENVELOPE_BYTES + 1)
        if len(raw) > MAX_ENVELOPE_BYTES:
            raise ValueError()
        data = json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)
        base = {"generation", "source_sha256", "result"}
        if (not isinstance(data, dict) or set(data) not in (base, base | {"model", "model_revision"})
                or type(data["generation"]) is not int or not 1 <= data["generation"] <= 2147483647
                or not isinstance(data["source_sha256"], str) or re.fullmatch(r"[a-f0-9]{64}", data["source_sha256"]) is None):
            raise ValueError()
        if "model" in data and (not isinstance(data["model"], str) or len(data["model"]) > 80
                or not isinstance(data["model_revision"], str) or not re.fullmatch(r"[a-f0-9]{40}", data["model_revision"])):
            raise ValueError()
        digest = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False,
            separators=(",", ":")).encode()).hexdigest()
        return data, digest
    except (OSError, EOFError, ValueError, TypeError, RecursionError, zlib.error):
        raise _error("local_result_invalid", 422) from None


def accept_local_result(db, *, device, job_id, envelope, digest, settings, now, on_scoped=None):
    # A timeout after commit must not start another inference or another export.
    job = db.scalar(select(TranscriptionJob).where(TranscriptionJob.id == job_id,
        TranscriptionJob.owner_user_id == device.owner_user_id, TranscriptionJob.local_device_id == device.id
    ).with_for_update().execution_options(populate_existing=True))
    if job is None:
        raise _error("local_job_unavailable", 404)
    project = db.get(Project, job.project_id)
    model, revision = job_model_identity(job.options_json)
    if (project is None or project.owner_user_id != device.owner_user_id or project.archived_at is not None
            or job.provider != "nemotron" or model is None):
        raise _error("local_job_unavailable", 404)
    if job.status == JobStatus.cancelled or job.cancel_requested_at is not None:
        raise _error("local_job_cancelled")
    if job.local_result_ready_at is not None:
        if job.local_result_generation != envelope["generation"] or job.local_result_digest != digest:
            raise _error("local_result_changed")
        if on_scoped is not None:
            on_scoped(job)
        return {"accepted": True, "already_accepted": True}
    generation = envelope["generation"]
    legacy = (model == NEMOTRON_MODEL and revision == LEGACY_NEMOTRON_REVISION
              and "model" not in envelope)
    if not legacy and (envelope.get("model") != model or envelope.get("model_revision") != revision):
        raise _error("local_result_model_changed")
    job = _scope(db, device=device, job_id=job_id, generation=generation, now=now, on_scoped=on_scoped)
    relation = _one_relation(job)
    receipt, selection = _load_receipt(job, relation, generation)
    if (receipt.get("prepared_duration_seconds") is None or relation.transcript_timeline_json is None
            or envelope["source_sha256"] != receipt["source_sha256"]):
        raise _error("local_input_changed")
    try:
        if relation.transcript_timeline_json != selection.record(receipt["source_duration_seconds"]):
            raise ValueError()
    except (ValueError, TypeError, KeyError, AudioTimelineError):
        raise _error("local_input_changed") from None
    result = None
    try:
        result = normalize_nemotron_local_result(envelope["result"],
            expected_duration_seconds=receipt["prepared_duration_seconds"], diarize=job_diarization_enabled(job.options_json))
    except ElevenLabsTranscriptionError:
        raise _error("local_result_invalid", 422) from None
    try:
        mark_attempt_provider_started(db, job_id=job.id, job_source_id=relation.id,
            lease_owner_id="local:" + device.id, lease_generation=generation, now=now, total_parts=1)
        # API may write operation-cache rows, but cannot modify worker-only part
        # checkpoints. Keep that database boundary; no broader API grant is needed.
        operation = SttProviderOperation(id=str(uuid4()), owner_user_id=job.owner_user_id,
            project_id=job.project_id, job_id=job.id, job_source_id=relation.id,
            attempt_number=int(job.attempt_count), provider="nemotron", operating_mode=job.operating_mode,
            model=model, operation_id=f"local:{job.id}:{device.id}:{generation}:{digest}",
            status="pending", submitted_at=now, created_at=now, updated_at=now)
        db.add(operation)
        persist_operation_result(db, operation, result, settings=settings, now=now, commit=False)
        mark_attempt_provider_returned(db, job_id=job.id, job_source_id=relation.id,
            lease_owner_id="local:" + device.id, lease_generation=generation, now=now)
    except Exception:
        db.rollback()
        raise _error("local_result_persistence_unavailable", 503) from None
    finally:
        if result is not None:
            result.revoke()
    job.local_result_ready_at, job.local_result_generation, job.local_result_digest = now, generation, digest
    job.status = JobStatus.queued  # VPS continues with export of the encrypted text only.
    job.work_progress_json = None
    invalidate_job_lease(job)
    job.updated_at = now
    db.flush()
    return {"accepted": True, "already_accepted": False}
