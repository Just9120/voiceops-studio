from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime

from .elevenlabs_transcription import ElevenLabsTranscriptionError
from .job_elevenlabs_transcription import (
    JobElevenLabsTranscriptionError,
    JobElevenLabsTranscriptionReason,
    transcribe_processing_job_source_with_elevenlabs,
)
from .media_preparation import prepare_yandex_media_file
from .models import ProviderCredential, TranscriptionJob
from .security import utcnow
from .stt_provider import SttCapabilityError, resolve_capability
from .stt_provider_health import provider_health, record_provider_failure, record_provider_success
from .yandex_transcription import YandexTranscriptionTransport
from .transcription_metadata import stored_model
from .provider_usage_accounting import ProviderUsageAccountingError, resolve_pricing_snapshot


def _credential_config(credential: ProviderCredential | None) -> dict:
    try:
        payload = json.loads(credential.config_json or "{}") if credential else {}
    except (TypeError, ValueError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _yandex_usage_available(job, settings):
    try:
        resolve_pricing_snapshot(job, settings)
        return True
    except ProviderUsageAccountingError as exc:
        if exc.reason.value == "provider_pricing_unavailable":
            return False  # Missing optional tariff is explicit unavailable, never free or a new STT blocker.
        raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.provider_pricing_unavailable) from exc


@contextmanager
def transcribe_processing_job_source(
    db,
    *,
    job_id: str,
    job_source_id: str,
    lease_owner_id: str,
    lease_generation: int,
    settings,
    now: datetime | None = None,
    clock=None,
    **kwargs,
):
    clock = clock or (lambda: utcnow().replace(tzinfo=None))
    job = db.get(TranscriptionJob, job_id)
    if job is None:
        raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.prerequisites_unavailable)
    provider = (job.provider or "elevenlabs").strip().lower()
    if provider == "yandex":
        from .job_cached_transcript import completed_yandex_result, restore_cached_yandex_transcript
        if completed_yandex_result(db, job, job_source_id) is not None:
            with restore_cached_yandex_transcript(db, job_id=job_id, job_source_id=job_source_id,
                    lease_owner_id=lease_owner_id, lease_generation=lease_generation, settings=settings,
                    now=clock()) as restored:
                yield restored
            return
    mode = (job.operating_mode or "standard").strip().lower()
    try:
        capability = resolve_capability(settings, provider, mode)
    except SttCapabilityError as exc:
        raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.provider_mismatch) from exc
    model = stored_model(job.options_json) or capability.model
    health = provider_health(db, provider=provider, operating_mode=mode, now=clock())
    if not health.available:
        raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.provider_unavailable)
    db.rollback()

    opener_kwargs = dict(
        db=db,
        job_id=job_id,
        job_source_id=job_source_id,
        lease_owner_id=lease_owner_id,
        lease_generation=lease_generation,
        settings=settings,
        now=now,
        clock=clock,
        expected_provider=provider,
        provider_model=model,
        **kwargs,
    )
    if provider == "elevenlabs":
        opener_kwargs.update(usage_accounting_enabled=True, part_checkpoints_enabled=True)
    elif provider == "yandex":
        credential = db.get(ProviderCredential, job.provider_credential_id) if job.provider_credential_id else None
        folder_id = str(_credential_config(credential).get("folder_id") or "").strip()
        if not folder_id or len(folder_id) > 256:
            raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.prerequisites_unavailable)
        db.rollback()
        opener_kwargs.update(
            media_preparer=prepare_yandex_media_file,
            elevenlabs_transport=YandexTranscriptionTransport(
                db=db,
                job_id=job_id,
                job_source_id=job_source_id,
                settings=settings,
                folder_id=folder_id,
                clock=clock,
            ),
            usage_accounting_enabled=_yandex_usage_available(job, settings),
            part_checkpoints_enabled=False,
        )
    else:
        raise JobElevenLabsTranscriptionError(JobElevenLabsTranscriptionReason.provider_mismatch)

    try:
        with transcribe_processing_job_source_with_elevenlabs(**opener_kwargs) as result:
            try:
                record_provider_success(db, provider=provider, operating_mode=mode, now=clock())
                db.commit()
            except Exception:
                db.rollback()
            yield result
    except (JobElevenLabsTranscriptionError, ElevenLabsTranscriptionError) as exc:
        failure_code = getattr(getattr(exc, "reason", None), "value", "provider_unavailable")
        try:
            db.rollback()
            record_provider_failure(
                db,
                provider=provider,
                operating_mode=mode,
                failure_code=failure_code,
                threshold=settings.stt_health_failure_threshold,
                cooldown_seconds=settings.stt_health_cooldown_seconds,
                now=clock(),
            )
            db.commit()
        except Exception:
            db.rollback()
        raise
