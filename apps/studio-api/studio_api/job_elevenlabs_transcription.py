from __future__ import annotations
from .preparation_control import PreparationInterrupted

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from .elevenlabs_transcription import (
    ElevenLabsTranscriptResult,
    ElevenLabsTranscriptionError,
    ElevenLabsTranscriptionReason,
    ElevenLabsTranscriptionTransport,
    merge_elevenlabs_transcript_results,
)
from .job_claim_lease import is_lease_active
from .job_execution_context import (
    JobExecutionContextError,
    ProcessingJobExecutionPrerequisites,
    open_processing_job_execution_prerequisites,
)
from .job_output_destination import _load_snapshot as _load_output_snapshot
from .job_source_materialization import (
    MaterializedJobSource,
    SourceMaterializationError,
    _load_selected_snapshot,
    materialize_processing_job_source,
)
from .media_preparation import (
    MediaPreparationError,
    MediaPreparationReason,
    PreparedMediaBatch,
    PreparedMediaInput,
    prepare_elevenlabs_media_parts,
)
from .models import CredentialStatus, JobStatus, Project, ProviderCredential, ProviderCredentialVersion, Source, TranscriptionJob, TranscriptionJobSource, TranscriptionJobSourceAttempt
from .security import utcnow
from .provider_part_checkpoints import (
    ProviderPartCheckpointError,
    load_provider_part_checkpoints,
    requires_complete_checkpoint_restore,
    save_provider_part_checkpoint,
)
from .provider_usage_accounting import (
    ProviderUsageAccountingError,
    begin_provider_part_usage,
    confirm_provider_part_usage,
    mark_pending_provider_usage_uncertain,
    resolve_pricing_snapshot,
)
from .diagnostics import resolve_job_correlation_id, write_diagnostic_event
from .job_retry_recovery import classify_source_attempt_failure, mark_attempt_provider_part_completed, mark_attempt_provider_returned, mark_attempt_provider_started
from .source_storage import safe_filename
from .stt_dictionaries import dictionary_terms_from_options
from .transcript_catalog import (
    ExistingResultMatchStatus,
    elevenlabs_effective_settings,
    provider_effective_settings,
    has_competing_provider_attempt_conflict,
    load_existing_result_matches,
    lock_catalog_source_identities,
)
from .transcription_options import (
    TranscriptionProviderSettings,
    browser_language_mode,
    job_diarization_enabled,
    job_existing_result_reprocess_authorized,
    provider_transcription_settings,
)


class JobElevenLabsTranscriptionReason(str, Enum):
    provider_mismatch = "provider_mismatch"
    prerequisites_unavailable = "prerequisites_unavailable"
    source_materialization_unavailable = "source_materialization_unavailable"
    ffmpeg_unavailable = "ffmpeg_unavailable"
    media_preparation_timeout = "media_preparation_timeout"
    media_preparation_failed = "media_preparation_failed"
    prepared_media_too_large = "prepared_media_too_large"
    media_duration_unavailable = "media_duration_unavailable"
    media_split_failed = "media_split_failed"
    media_part_too_large = "media_part_too_large"
    media_clip_out_of_bounds = "media_clip_out_of_bounds"
    media_duration_confirmation_required = "media_duration_confirmation_required"
    media_duration_too_long = "media_duration_too_long"
    existing_result_conflict = "existing_result_conflict"
    lifecycle_changed_before_provider_call = "lifecycle_changed_before_provider_call"
    credential_or_output_identity_changed_before_provider_call = "credential_or_output_identity_changed_before_provider_call"
    provider_authentication_rejected = "provider_authentication_rejected"
    provider_payment_required = "provider_payment_required"
    provider_scope_rejected = "provider_scope_rejected"
    provider_request_rejected = "provider_request_rejected"
    provider_rate_limited = "provider_rate_limited"
    provider_unavailable = "provider_unavailable"
    provider_timeout = "provider_timeout"
    malformed_provider_response = "malformed_provider_response"
    partial_provider_result = "partial_provider_result"
    lifecycle_changed_after_provider_call = "lifecycle_changed_after_provider_call"
    context_closed = "context_closed"
    retry_state_persistence_failed = "retry_state_persistence_failed"
    provider_pricing_unavailable = "provider_pricing_unavailable"
    provider_usage_accounting_unavailable = "provider_usage_accounting_unavailable"
    provider_usage_outcome_uncertain = "provider_usage_outcome_uncertain"


class JobElevenLabsTranscriptionError(RuntimeError):
    def __init__(self, reason: JobElevenLabsTranscriptionReason):
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True)
class _LifecycleSnapshot:
    job_id: str
    owner_user_id: str
    project_id: str
    lease_owner_id: str | None
    lease_generation: int
    lease_expires_at: datetime | None
    cancel_requested_at: datetime | None
    project_archived_at: datetime | None


@contextmanager
def transcribe_processing_job_source_with_elevenlabs(
    db: Session,
    *,
    job_id: str,
    job_source_id: str,
    lease_owner_id: str,
    lease_generation: int,
    settings,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    prerequisites_opener: Callable = open_processing_job_execution_prerequisites,
    source_materializer: Callable = materialize_processing_job_source,
    media_preparer: Callable = prepare_elevenlabs_media_parts,
    elevenlabs_transport: ElevenLabsTranscriptionTransport | Callable[..., ElevenLabsTranscriptResult] | None = None,
    expected_provider: str = "elevenlabs",
    provider_model: str = "scribe_v2",
    usage_accounting_enabled: bool = True,
    part_checkpoints_enabled: bool = True,
    **kwargs,
) -> Iterator[ElevenLabsTranscriptResult]:
    clock = clock or (lambda: utcnow().replace(tzinfo=None))
    # A complete prior provider result is an export-only operation. It must
    # never download a retired source, probe/encode media or read a provider key.
    if part_checkpoints_enabled and requires_complete_checkpoint_restore(db, job_id=job_id, job_source_id=job_source_id):
        from .job_cached_transcript import restore_cached_transcript
        try:
            with restore_cached_transcript(db, job_id=job_id, job_source_id=job_source_id,
                lease_owner_id=lease_owner_id, lease_generation=lease_generation,
                settings=settings, now=clock()) as restored:
                yield restored
            return
        except ProviderPartCheckpointError as exc:
            raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.retry_state_persistence_failed) from exc
    transport = elevenlabs_transport or ElevenLabsTranscriptionTransport()
    result: ElevenLabsTranscriptResult | None = None
    try:
        try:
            prereq_cm = prerequisites_opener(
                db,
                job_id=job_id,
                lease_owner_id=lease_owner_id,
                lease_generation=lease_generation,
                settings=settings,
                now=now,
                clock=clock,
                **kwargs,
            )
            prereq: ProcessingJobExecutionPrerequisites = prereq_cm.__enter__()
        except JobExecutionContextError as exc:
            raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.prerequisites_unavailable) from exc
        try:
            if prereq.provider != expected_provider:
                raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.provider_mismatch)
            try:
                _emit_provider(db, job_id, "SOURCE_VALIDATION_STARTED", {"attempt_number": _attempt(db, job_id)})
                source_cm = source_materializer(
                    db,
                    job_id=job_id,
                    job_source_id=job_source_id,
                    lease_owner_id=lease_owner_id,
                    lease_generation=lease_generation,
                    settings=settings,
                    now=now,
                    clock=clock,
                    **_source_kwargs(kwargs),
                )
                source: MaterializedJobSource = source_cm.__enter__()
            except SourceMaterializationError as exc:
                raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.source_materialization_unavailable) from exc
            try:
                try:
                    initial_job_snapshot = _load_credential_db_only(
                        db,
                        job_id,
                        lease_owner_id,
                        lease_generation,
                        clock(),
                        settings,
                        expected_provider=expected_provider,
                        provider_model=provider_model,
                    )
                    media_clip = initial_job_snapshot["catalog_settings"]
                    from .long_media_preflight import confirmed_source_duration
                    confirmed_duration = confirmed_source_duration(db.get(TranscriptionJob, job_id), job_source_id)
                    # Preserve an existing multipart checkpoint/usage plan on recovery.
                    prior_part_count = db.scalar(
                        select(TranscriptionJobSourceAttempt.provider_total_parts)
                        .where(
                            TranscriptionJobSourceAttempt.job_source_id == job_source_id,
                            TranscriptionJobSourceAttempt.provider_total_parts.is_not(None),
                        )
                        .order_by(TranscriptionJobSourceAttempt.attempt_number.desc())
                        .limit(1)
                    ) if expected_provider == "elevenlabs" and media_clip.diarization_enabled else None
                    _close_read_transaction_before_media_preparation(db)
                    prepared_cm = media_preparer(
                        stream=source.stream,
                        original_filename=safe_filename(source.original_filename),
                        mime_type=source.mime_type,
                        byte_count=source.byte_count,
                        max_output_bytes=settings.source_max_upload_bytes,
                        **({"prefer_whole_recording": (
                            media_clip.diarization_enabled and (prior_part_count is None or prior_part_count == 1)
                        )} if expected_provider == "elevenlabs" else {}),
                        media_clip_start_seconds=media_clip.media_clip_start_seconds,
                        media_clip_end_seconds=media_clip.media_clip_end_seconds,
                        duration_warning_seconds=settings.media_duration_warning_seconds,
                        max_duration_seconds=settings.media_max_duration_seconds,
                        long_duration_confirmed=confirmed_duration is not None,
                        **({"confirmed_source_duration_seconds": confirmed_duration} if confirmed_duration is not None else {}),
                        **(
                            {"probe_source_creation_time": True}
                            if source.source_type == "local_upload"
                            and source.source_created_at is None
                            else {}
                        ),
                    )
                    from .preparation_control import preparation_control
                    from .job_source_materialization import processing_source_control
                    with preparation_control(processing_source_control(
                        db, job_id=job_id, job_source_id=job_source_id,
                        lease_owner_id=lease_owner_id, lease_generation=lease_generation,
                        clock=clock, settings=settings,
                    )):
                        prepared_batch = _enter_prepared_media_batch(prepared_cm)
                    if (
                        source.source_type == "local_upload"
                        and source.source_created_at is None
                        and prepared_batch.source_created_at is not None
                    ):
                        _persist_embedded_source_creation_time(
                            db,
                            job_id=job_id,
                            job_source_id=job_source_id,
                            source_id=source.identity.source_id,
                            created_at=prepared_batch.source_created_at,
                            now=clock(),
                        )
                except PreparationInterrupted as exc:
                    raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.lifecycle_changed_before_provider_call) from exc
                except MediaPreparationError as exc:
                    if exc.reason is MediaPreparationReason.media_duration_confirmation_required:
                        from .long_media_preflight import record_long_media_preflight
                        record_long_media_preflight(db, job_id=job_id, relation_id=job_source_id,
                            duration=exc.duration_seconds, settings=settings, owner=lease_owner_id,
                            generation=lease_generation, now=clock())
                    mapped = _map_media_preparation_reason(exc.reason)
                    _best_effort_classify(db, job_id, job_source_id, lease_owner_id, lease_generation, mapped.value, clock)
                    raise JobElevenLabsTranscriptionError(mapped) from exc
                except JobElevenLabsTranscriptionError:
                    raise
                except Exception as exc:
                    _best_effort_classify(db, job_id, job_source_id, lease_owner_id, lease_generation, "media_preparation_failed", clock)
                    raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.media_preparation_failed) from exc
                try:
                    provider_settings = _final_pre_provider_revalidate(
                        db,
                        job_id,
                        job_source_id,
                        lease_owner_id,
                        lease_generation,
                        settings,
                        clock(),
                        prereq,
                        source,
                        expected_catalog_settings=initial_job_snapshot["catalog_settings"],
                        expected_provider=expected_provider,
                        provider_model=provider_model,
                    )
                    _emit_provider(db, job_id, "SOURCE_READY", {"attempt_number": _attempt(db, job_id)})
                    part_results: list[ElevenLabsTranscriptResult] = []
                    if part_checkpoints_enabled:
                        try:
                            part_results.extend(
                                load_provider_part_checkpoints(
                                    db,
                                    job_id=job_id,
                                    job_source_id=job_source_id,
                                    parts=prepared_batch.parts,
                                    settings=settings,
                                    now=clock(),
                                    require_complete=requires_complete_checkpoint_restore(
                                        db, job_id=job_id, job_source_id=job_source_id,
                                    ),
                                )
                            )
                        except ProviderPartCheckpointError as exc:
                            _emit_provider_failure(
                                db, job_id, JobElevenLabsTranscriptionReason.retry_state_persistence_failed,
                                boundary="provider_checkpoint", diagnostic_code=exc.reason.value,
                            )
                            _best_effort_classify(
                                db,
                                job_id,
                                job_source_id,
                                lease_owner_id,
                                lease_generation,
                                exc.reason.value,
                                clock,
                            )
                            raise JobElevenLabsTranscriptionError(
                                JobElevenLabsTranscriptionReason.retry_state_persistence_failed
                            ) from exc
                    if usage_accounting_enabled:
                        try:
                            resolve_pricing_snapshot(db.get(TranscriptionJob, job_id), settings)
                        except ProviderUsageAccountingError as exc:
                            _best_effort_classify(
                                db,
                                job_id,
                                job_source_id,
                                lease_owner_id,
                                lease_generation,
                                JobElevenLabsTranscriptionReason.provider_pricing_unavailable.value,
                                clock,
                            )
                            raise JobElevenLabsTranscriptionError(
                                JobElevenLabsTranscriptionReason.provider_pricing_unavailable
                            ) from exc
                    _emit_provider(db, job_id, "PROVIDER_REQUEST_STARTED", {"attempt_number": _attempt(db, job_id)})
                    try:
                        from .media_context import serialize_part_plan
                        mark_attempt_provider_started(db, job_id=job_id, job_source_id=job_source_id, lease_owner_id=lease_owner_id, lease_generation=lease_generation, now=clock(), total_parts=len(prepared_batch.parts), completed_parts=len(part_results), media_plan=serialize_part_plan(prepared_batch.parts))
                        db.commit()
                    except Exception as exc:
                        db.rollback()
                        for checkpoint_result in part_results:
                            checkpoint_result.revoke()
                        raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.retry_state_persistence_failed) from exc
                    try:
                        for part_index, prepared in enumerate(prepared_batch.parts):
                            if part_index < len(part_results):
                                continue
                            if part_index:
                                _post_provider_revalidate_or_fail(
                                    db,
                                    job_id,
                                    job_source_id,
                                    lease_owner_id,
                                    lease_generation,
                                    clock,
                                )
                            if usage_accounting_enabled:
                                try:
                                    begin_provider_part_usage(
                                    db,
                                    job_id=job_id,
                                    job_source_id=job_source_id,
                                    lease_owner_id=lease_owner_id,
                                    lease_generation=lease_generation,
                                    part_index=part_index,
                                    duration_seconds=prepared.duration_seconds,
                                    settings=settings,
                                    now=clock(),
                                )
                                    db.commit()
                                except ProviderUsageAccountingError as exc:
                                    db.rollback()
                                    mapped = (
                                        JobElevenLabsTranscriptionReason.provider_pricing_unavailable
                                        if exc.reason.value == "provider_pricing_unavailable"
                                        else JobElevenLabsTranscriptionReason.provider_usage_outcome_uncertain
                                        if exc.reason.value == "provider_usage_outcome_uncertain"
                                        else JobElevenLabsTranscriptionReason.provider_usage_accounting_unavailable
                                    )
                                    _best_effort_classify(db, job_id, job_source_id, lease_owner_id, lease_generation, mapped.value, clock)
                                    raise JobElevenLabsTranscriptionError(mapped) from exc
                                except Exception as exc:
                                    db.rollback()
                                    mapped = JobElevenLabsTranscriptionReason.provider_usage_accounting_unavailable
                                    _best_effort_classify(db, job_id, job_source_id, lease_owner_id, lease_generation, mapped.value, clock)
                                    raise JobElevenLabsTranscriptionError(mapped) from exc
                            try:
                                part_result = _call_transport(
                                    transport,
                                    api_key=prereq.raw_credential_secret,
                                    stream=prepared.stream,
                                    filename=safe_filename(prepared.filename),
                                    mime_type=prepared.mime_type,
                                    language_code=provider_settings.language_code,
                                    diarize=provider_settings.diarize,
                                    keyterms=dictionary_terms_from_options(initial_job_snapshot.get("options_json")),
                                    model_id=provider_model,
                                )
                            except ElevenLabsTranscriptionError as exc:
                                provider_failure = _map_provider_reason(exc.reason)
                                mapped = (
                                    JobElevenLabsTranscriptionReason.partial_provider_result
                                    if part_results
                                    else provider_failure
                                )
                                _emit_provider_failure(
                                    db,
                                    job_id,
                                    mapped,
                                    diagnostic_code=provider_failure.value,
                                    provider_error_code=exc.provider_error_code,
                                    http_status=exc.http_status,
                                )
                                _best_effort_classify(db, job_id, job_source_id, lease_owner_id, lease_generation, mapped.value, clock, provider_failure_code=provider_failure.value)
                                raise JobElevenLabsTranscriptionError(mapped) from exc
                            except Exception as exc:
                                mapped = (
                                    JobElevenLabsTranscriptionReason.partial_provider_result
                                    if part_results
                                    else JobElevenLabsTranscriptionReason.provider_unavailable
                                )
                                _emit_provider_failure(
                                    db,
                                    job_id,
                                    mapped,
                                    diagnostic_code=(
                                        mapped.value if part_results else "unknown"
                                    ),
                                )
                                _best_effort_classify(db, job_id, job_source_id, lease_owner_id, lease_generation, mapped.value, clock)
                                raise JobElevenLabsTranscriptionError(mapped) from exc
                            if usage_accounting_enabled:
                                try:
                                    usage = confirm_provider_part_usage(
                                    db,
                                    job_id=job_id,
                                    job_source_id=job_source_id,
                                    lease_owner_id=lease_owner_id,
                                    lease_generation=lease_generation,
                                    part_index=part_index,
                                    now=clock(),
                                )
                                    db.commit()
                                    _emit_provider(
                                    db,
                                    job_id,
                                    "PROVIDER_USAGE_CONFIRMED",
                                    {
                                        "duration_ms": usage.duration_ms,
                                        "cost_eight_decimal_units": int(
                                            usage.cost_amount * 100_000_000
                                        ),
                                        "currency": usage.currency,
                                    },
                                    )
                                except Exception as exc:
                                    db.rollback()
                                    mapped = JobElevenLabsTranscriptionReason.provider_usage_outcome_uncertain
                                    _best_effort_classify(db, job_id, job_source_id, lease_owner_id, lease_generation, mapped.value, clock)
                                    part_result.revoke()
                                    raise JobElevenLabsTranscriptionError(mapped) from exc
                            part_results.append(part_result)
                            _post_provider_revalidate_or_fail(
                                db,
                                job_id,
                                job_source_id,
                                lease_owner_id,
                                lease_generation,
                                clock,
                            )
                            try:
                                if part_checkpoints_enabled:
                                    save_provider_part_checkpoint(
                                        db,
                                        job_id=job_id,
                                        job_source_id=job_source_id,
                                        part_index=part_index,
                                        total_parts=len(prepared_batch.parts),
                                        timeline_offset_seconds=prepared.timeline_offset_seconds,
                                        duration_seconds=prepared.duration_seconds,
                                        result=part_result,
                                        settings=settings,
                                        now=clock(),
                                    )
                                mark_attempt_provider_part_completed(
                                    db,
                                    job_id=job_id,
                                    job_source_id=job_source_id,
                                    lease_owner_id=lease_owner_id,
                                    lease_generation=lease_generation,
                                    completed_parts=len(part_results),
                                    now=clock(),
                                )
                                db.commit()
                            except ProviderPartCheckpointError as exc:
                                db.rollback()
                                mapped = JobElevenLabsTranscriptionReason.partial_provider_result
                                _emit_provider_failure(
                                    db,
                                    job_id,
                                    mapped,
                                    boundary="provider_checkpoint",
                                    diagnostic_code=exc.reason.value,
                                )
                                _best_effort_classify(db, job_id, job_source_id, lease_owner_id, lease_generation, mapped.value, clock)
                                raise JobElevenLabsTranscriptionError(mapped) from exc
                            except Exception as exc:
                                db.rollback()
                                mapped = JobElevenLabsTranscriptionReason.partial_provider_result
                                _emit_provider_failure(
                                    db,
                                    job_id,
                                    mapped,
                                    boundary="provider_checkpoint",
                                    diagnostic_code="provider_part_progress_persistence_failed",
                                )
                                _best_effort_classify(db, job_id, job_source_id, lease_owner_id, lease_generation, mapped.value, clock)
                                raise JobElevenLabsTranscriptionError(mapped) from exc
                        try:
                            mark_attempt_provider_returned(db, job_id=job_id, job_source_id=job_source_id, lease_owner_id=lease_owner_id, lease_generation=lease_generation, now=clock())
                            db.commit()
                        except Exception as exc:
                            db.rollback()
                            raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.provider_unavailable) from exc
                        try:
                            if len(part_results) == 1:
                                result = part_results.pop()
                            else:
                                result = merge_elevenlabs_transcript_results(
                                    _merge_inputs(prepared_batch, part_results),
                                )
                            if not result.text.strip():
                                raise ElevenLabsTranscriptionError(
                                    ElevenLabsTranscriptionReason.malformed_provider_response,
                                    assembly_code="transcript_assembly_empty",
                                )
                        except ElevenLabsTranscriptionError as exc:
                            mapped = _map_provider_reason(exc.reason)
                            _emit_provider_failure(
                                db, job_id, mapped, boundary="transcript_assembly",
                                diagnostic_code=exc.assembly_code,
                            )
                            _best_effort_classify(db, job_id, job_source_id, lease_owner_id, lease_generation, mapped.value, clock)
                            raise JobElevenLabsTranscriptionError(mapped) from exc
                        _post_provider_revalidate_or_fail(
                            db,
                            job_id,
                            job_source_id,
                            lease_owner_id,
                            lease_generation,
                            clock,
                        )
                    finally:
                        for part_result in part_results:
                            part_result.revoke()
                finally:
                    prepared_cm.__exit__(None, None, None)
                _emit_provider(db, job_id, "PROVIDER_REQUEST_COMPLETED", {"attempt_number": _attempt(db, job_id)})
                yield result
            finally:
                source_cm.__exit__(None, None, None)
        finally:
            prereq_cm.__exit__(None, None, None)
    finally:
        if result is not None:
            result.revoke()


def _source_kwargs(kwargs):
    allowed = {"storage_factory", "drive_token_resolver", "drive_content_fetcher", "drive_metadata_fetcher"}
    return {k: v for k, v in kwargs.items() if k in allowed}


def _call_transport(transport, **kwargs):
    from .work_progress import report_work
    report_work("provider_wait")
    from .worker_progress import worker_phase
    timeout = getattr(transport, "timeout", None)
    if timeout is None:
        timeout = getattr(getattr(transport, "settings", None), "yandex_operation_timeout_seconds", 1800)
    with worker_phase("provider_request", float(timeout) + 30):
        if hasattr(transport, "transcribe"):
            return transport.transcribe(**kwargs)
        return transport(**kwargs)


def _persist_embedded_source_creation_time(
    db: Session,
    *,
    job_id: str,
    job_source_id: str,
    source_id: str,
    created_at: datetime,
    now: datetime,
) -> None:
    relation = db.execute(
        select(TranscriptionJobSource)
        .where(
            TranscriptionJobSource.id == job_source_id,
            TranscriptionJobSource.job_id == job_id,
            TranscriptionJobSource.source_id == source_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    source = db.execute(
        select(Source).where(Source.id == source_id).with_for_update()
    ).scalar_one_or_none()
    if relation is None or source is None:
        raise JobElevenLabsTranscriptionError(
            JobElevenLabsTranscriptionReason.lifecycle_changed_before_provider_call
        )
    if source.source_created_at is None:
        source.source_created_at = created_at
        source.source_created_at_provenance = "embedded_media_metadata"
        source.updated_at = now
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            raise JobElevenLabsTranscriptionError(
                JobElevenLabsTranscriptionReason.lifecycle_changed_before_provider_call
            ) from exc


def _coerce_prepared_media_batch(value) -> PreparedMediaBatch:
    if isinstance(value, PreparedMediaBatch) and value.parts:
        return value
    if isinstance(value, PreparedMediaInput):
        return PreparedMediaBatch(
            parts=(value,),
            duration_seconds=float(value.duration_seconds or 0.0),
            source_created_at=value.source_created_at,
        )
    raise MediaPreparationError(MediaPreparationReason.media_preparation_failed)


def _enter_prepared_media_batch(prepared_cm) -> PreparedMediaBatch:
    value = prepared_cm.__enter__()
    try:
        return _coerce_prepared_media_batch(value)
    except BaseException as exc:
        prepared_cm.__exit__(type(exc), exc, exc.__traceback__)
        raise


def _merge_inputs(
    batch: PreparedMediaBatch,
    results: list[ElevenLabsTranscriptResult],
):
    if len(batch.parts) != len(results) or not results:
        raise ElevenLabsTranscriptionError(
            ElevenLabsTranscriptionReason.malformed_provider_response,
        )
    merged = []
    previous_end = 0.0
    for index, (part, result) in enumerate(zip(batch.parts, results)):
        if part.duration_seconds is None or part.duration_seconds <= 0:
            raise ElevenLabsTranscriptionError(
                ElevenLabsTranscriptionReason.malformed_provider_response,
            )
        overlap = (
            max(0.0, previous_end - part.timeline_offset_seconds)
            if index
            else 0.0
        )
        merged.append((result, part.timeline_offset_seconds, overlap))
        previous_end = part.timeline_offset_seconds + part.duration_seconds
    return tuple(merged)


def _final_pre_provider_revalidate(
    db,
    job_id,
    job_source_id,
    owner,
    generation,
    settings,
    now,
    prereq,
    source,
    *,
    expected_catalog_settings=None,
    expected_provider="elevenlabs",
    provider_model="scribe_v2",
) -> TranscriptionProviderSettings:
    try:
        cred_snap = _load_credential_db_only(db, job_id, owner, generation, now, settings, expected_provider=expected_provider, provider_model=provider_model)
        out_snap = _load_output_snapshot(db, job_id, owner, generation, now)
        src_snap = _load_selected_snapshot(db, job_id, job_source_id, owner, generation, now, settings)
    except JobElevenLabsTranscriptionError:
        raise
    except Exception as exc:
        raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.lifecycle_changed_before_provider_call) from exc
    credential_identity_changed = (
        cred_snap["provider"] != expected_provider
        or cred_snap["credential_id"] != getattr(prereq, "_credential").credential_id
        or cred_snap["version_id"] != prereq.credential_version_id
    )
    settings_identity_changed = (
        expected_catalog_settings is not None
        and cred_snap["catalog_settings"] != expected_catalog_settings
    )
    if (
        credential_identity_changed
        or settings_identity_changed
        or out_snap.output_drive_folder_id != prereq.output_drive_folder_id
    ):
        raise JobElevenLabsTranscriptionError(
            JobElevenLabsTranscriptionReason.credential_or_output_identity_changed_before_provider_call
        )
    if src_snap.job_source_id != source.identity.job_source_id or src_snap.source_id != source.identity.source_id:
        raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.lifecycle_changed_before_provider_call)
    try:
        _require_no_existing_result_conflict(
            db,
            job_id=job_id,
            source_id=src_snap.source_id,
            credential_snapshot=cred_snap,
        )
    except JobElevenLabsTranscriptionError as exc:
        if (
            exc.reason
            == JobElevenLabsTranscriptionReason.existing_result_conflict
        ):
            _best_effort_classify(
                db,
                job_id,
                job_source_id,
                owner,
                generation,
                exc.reason.value,
                lambda: now,
            )
        raise
    return cred_snap["provider_settings"]


def _require_no_existing_result_conflict(
    db,
    *,
    job_id,
    source_id,
    credential_snapshot,
) -> None:
    selected_source = db.get(Source, source_id)
    if selected_source is None:
        raise JobElevenLabsTranscriptionError(
            JobElevenLabsTranscriptionReason.lifecycle_changed_before_provider_call
        )
    locked_sources = lock_catalog_source_identities(
        db,
        owner_user_id=credential_snapshot["owner_user_id"],
        sources=(selected_source,),
    )
    selected_source = next(
        (source for source in locked_sources if source.id == source_id),
        None,
    )
    if selected_source is None:
        raise JobElevenLabsTranscriptionError(
            JobElevenLabsTranscriptionReason.lifecycle_changed_before_provider_call
        )
    matches = load_existing_result_matches(
        db,
        owner_user_id=credential_snapshot["owner_user_id"],
        sources=(selected_source,),
        target_settings=credential_snapshot["catalog_settings"],
    )
    match = matches.get(source_id)
    accepted_conflict = (
        not credential_snapshot["existing_result_reprocess_authorized"]
        and (
            match is None
            or match.status != ExistingResultMatchStatus.no_match
        )
    )
    provider_attempt_conflict = has_competing_provider_attempt_conflict(
        db,
        owner_user_id=credential_snapshot["owner_user_id"],
        sources=(selected_source,),
        target_settings=credential_snapshot["catalog_settings"],
        exclude_job_id=job_id,
    )
    if accepted_conflict or provider_attempt_conflict:
        raise JobElevenLabsTranscriptionError(
            JobElevenLabsTranscriptionReason.existing_result_conflict
        )


def _load_credential_db_only(db, job_id, owner, generation, now, settings, *, expected_provider="elevenlabs", provider_model="scribe_v2"):
    db.expire_all()
    job = db.get(TranscriptionJob, job_id)
    lifecycle_changed = (
        job is None
        or job.status != JobStatus.processing
        or job.lease_owner_id != owner
        or job.lease_generation != generation
        or not is_lease_active(job, now)
        or job.cancel_requested_at is not None
    )
    if lifecycle_changed:
        raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.lifecycle_changed_before_provider_call)
    project = db.get(Project, job.project_id)
    if project is None or project.owner_user_id != job.owner_user_id or project.archived_at is not None:
        raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.lifecycle_changed_before_provider_call)
    cred = db.get(ProviderCredential, job.provider_credential_id) if job.provider_credential_id else None
    if cred is None or cred.user_id != job.owner_user_id or cred.status != CredentialStatus.active or cred.deleted_at is not None:
        raise JobElevenLabsTranscriptionError(
            JobElevenLabsTranscriptionReason.credential_or_output_identity_changed_before_provider_call
        )
    provider = str(getattr(cred.provider, "value", cred.provider))
    if provider != expected_provider or (job.provider is not None and job.provider != provider):
        raise JobElevenLabsTranscriptionError(
            JobElevenLabsTranscriptionReason.credential_or_output_identity_changed_before_provider_call
        )
    ver = db.get(ProviderCredentialVersion, cred.active_version_id) if cred.active_version_id else None
    credential_unusable = (
        ver is None
        or ver.credential_id != cred.id
        or ver.revoked_at is not None
        or ver.deleted_at is not None
        or not ver.ciphertext
        or not ver.nonce
        or ver.key_id != settings.credential_key_id
    )
    if credential_unusable:
        raise JobElevenLabsTranscriptionError(
            JobElevenLabsTranscriptionReason.credential_or_output_identity_changed_before_provider_call
        )
    return {
        "credential_id": cred.id,
        "version_id": ver.id,
        "provider": provider,
        "provider_settings": provider_transcription_settings(job.language, job.options_json),
        "options_json": job.options_json,
        "owner_user_id": job.owner_user_id,
        "catalog_settings": provider_effective_settings(
            provider=expected_provider,
            model=provider_model,
            language_mode=browser_language_mode(job.language),
            diarization_enabled=job_diarization_enabled(job.options_json),
            media_clip_start_seconds=job.media_clip_start_seconds,
            media_clip_end_seconds=job.media_clip_end_seconds,
        ),
        "existing_result_reprocess_authorized": (
            job_existing_result_reprocess_authorized(job.options_json)
        ),
        "long_duration_cost_confirmed": bool(job.long_duration_cost_confirmed),
    }


def _close_read_transaction_before_media_preparation(db) -> None:
    """Do not leave a worker DB transaction idle during long local media I/O."""
    try:
        db.rollback()
    except Exception as exc:
        raise JobElevenLabsTranscriptionError(
            JobElevenLabsTranscriptionReason.lifecycle_changed_before_provider_call
        ) from exc


def _post_provider_lifecycle_revalidate(db, job_id, owner, generation, now) -> None:
    try:
        snap = _load_lifecycle(db, job_id, owner, generation, now)
    except Exception as exc:
        raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.lifecycle_changed_after_provider_call) from exc
    if snap.cancel_requested_at is not None:
        raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.lifecycle_changed_after_provider_call)


def _post_provider_revalidate_or_fail(
    db,
    job_id,
    job_source_id,
    owner,
    generation,
    clock,
) -> None:
    try:
        _post_provider_lifecycle_revalidate(
            db,
            job_id,
            owner,
            generation,
            clock(),
        )
    except JobElevenLabsTranscriptionError:
        reason = JobElevenLabsTranscriptionReason.lifecycle_changed_after_provider_call
        _emit_provider(
            db,
            job_id,
            "PROVIDER_REQUEST_FAILED",
            {
                "boundary": "post_provider_lifecycle",
                "error_code": reason.value,
                "retryable": False,
                "attempt_number": _attempt(db, job_id),
            },
        )
        _best_effort_classify(
            db,
            job_id,
            job_source_id,
            owner,
            generation,
            reason.value,
            clock,
        )
        raise


def _load_lifecycle(db, job_id, owner, generation, now) -> _LifecycleSnapshot:
    db.expire_all()
    job = db.get(TranscriptionJob, job_id)
    lifecycle_changed = (
        job is None
        or job.status != JobStatus.processing
        or job.lease_owner_id != owner
        or job.lease_generation != generation
        or not is_lease_active(job, now)
    )
    if lifecycle_changed:
        raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.lifecycle_changed_after_provider_call)
    project = db.get(Project, job.project_id)
    if project is None or project.owner_user_id != job.owner_user_id or project.archived_at is not None:
        raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.lifecycle_changed_after_provider_call)
    return _LifecycleSnapshot(
        job.id,
        job.owner_user_id,
        job.project_id,
        job.lease_owner_id,
        job.lease_generation,
        job.lease_expires_at,
        job.cancel_requested_at,
        project.archived_at,
    )


def _map_provider_reason(reason: ElevenLabsTranscriptionReason) -> JobElevenLabsTranscriptionReason:
    return JobElevenLabsTranscriptionReason(reason.value)


def _map_media_preparation_reason(reason) -> JobElevenLabsTranscriptionReason:
    return JobElevenLabsTranscriptionReason(reason.value)


def _emit_provider_failure(
    db,
    job_id,
    reason: JobElevenLabsTranscriptionReason,
    *,
    diagnostic_code: str | None = None,
    provider_error_code: str | None = None,
    http_status: int | None = None,
    boundary: str = "provider_transport",
):
    safe_codes = {
        "provider_authentication_rejected",
        "provider_payment_required",
        "provider_scope_rejected",
        "provider_request_rejected",
        "provider_rate_limited",
        "provider_unavailable",
        "provider_timeout",
        "malformed_provider_response",
        "partial_provider_result",
        "provider_part_checkpoint_persistence_failed",
        "provider_part_checkpoint_scope_conflict",
        "provider_part_checkpoint_shape_conflict",
        "provider_part_progress_persistence_failed",
        "transcript_part_words_missing",
        "transcript_overlap_timestamps_missing",
        "transcript_assembly_empty",
        "provider_complete_checkpoint_set_unavailable",
    }
    metadata = {
        "boundary": boundary,
        "error_code": (
            diagnostic_code
            if diagnostic_code in safe_codes | {"unknown"}
            else reason.value if reason.value in safe_codes else "unknown"
        ),
        "retryable": reason.value
        in {"provider_rate_limited", "provider_unavailable", "provider_timeout"},
        "attempt_number": _attempt(db, job_id),
    }
    if provider_error_code is not None:
        metadata["provider_error_code"] = provider_error_code
    if http_status is not None:
        metadata["http_status"] = http_status
        metadata["http_status_category"] = f"{http_status // 100}xx"
    _emit_provider(
        db,
        job_id,
        "PROVIDER_REQUEST_FAILED",
        metadata,
    )


def _attempt(db, job_id) -> int:
    try:
        job = db.get(TranscriptionJob, job_id)
        return int(job.attempt_count or 0) if job else 0
    except Exception:
        return 0

def _emit_provider(db, job_id, event_code, metadata):
    try:
        job = db.get(TranscriptionJob, job_id)
        if job is not None:
            write_diagnostic_event(owner_user_id=job.owner_user_id, component="worker", event_code=event_code, project_id=job.project_id, job_id=job.id, correlation_id=resolve_job_correlation_id(owner_user_id=job.owner_user_id, job_id=job.id), metadata=metadata)
    except Exception:
        pass


def _best_effort_classify(db, job_id, job_source_id, owner, generation, code, clock, *, provider_failure_code=None):
    try:
        now = clock()
        mark_pending_provider_usage_uncertain(db, job_id=job_id, job_source_id=job_source_id, now=now)
        classify_source_attempt_failure(db, job_id=job_id, job_source_id=job_source_id, lease_owner_id=owner, lease_generation=generation, failure_code=code, provider_failure_code=provider_failure_code, now=now)
        db.commit()
    except Exception:
        db.rollback()
