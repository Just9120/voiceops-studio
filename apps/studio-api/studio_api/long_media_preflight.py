"""Safe nominal quote for an unpaid final-recording duration warning.

This is a duration/rate estimate, never an invoice or provider debit. No media,
tokens, storage identities or document content is persisted here.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select

from .job_claim_lease import is_lease_active
from .models import JobStatus, TranscriptionJob, TranscriptionJobSource
from .provider_usage_accounting import ProviderUsageAccountingError, preserve_pricing_snapshot


def record_long_media_preflight(db, *, job_id, relation_id, duration, settings, owner, generation, now):
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        return
    job = db.execute(select(TranscriptionJob).where(TranscriptionJob.id == job_id)
        .with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    relation = db.get(TranscriptionJobSource, relation_id)
    if (not job or not relation or relation.job_id != job.id or job.status is not JobStatus.processing
        or job.lease_owner_id != owner or job.lease_generation != generation or not is_lease_active(job, now)
        or job.cancel_requested_at is not None):
        raise RuntimeError("long_media_preflight_context_invalid")
    # Quote the final requested recording before provider splitting. The original
    # measurement and unchanged interval still bind confirmation to this source.
    from .media_clip import normalize_media_clip_range
    clip = normalize_media_clip_range(job.media_clip_start_seconds, job.media_clip_end_seconds)
    start = clip.start_seconds or 0
    end = min(duration, clip.end_seconds) if clip.end_seconds is not None else duration
    selected_duration = max(0.0, end - start)
    rate = currency = effective = source = amount = None
    if job.provider in {"elevenlabs", "yandex"}:
        try:
            snapshot = preserve_pricing_snapshot(job, settings)
            rate, currency, effective, source = (format(snapshot.rate_per_hour, "f"), snapshot.currency,
                snapshot.effective_date.isoformat(), snapshot.source)
            amount = format((snapshot.rate_per_hour * Decimal(str(selected_duration)) / 3600)
                .quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP), "f")
        except ProviderUsageAccountingError:
            pass  # Unknown pricing is not a zero-cost quote.
    payload = {"job_source_id": relation.id,
        "clip_start_seconds": job.media_clip_start_seconds, "clip_end_seconds": job.media_clip_end_seconds,
        "source_duration_seconds": round(duration, 3), "selected_duration_seconds": round(selected_duration, 3),
        "nominal_cost": amount, "currency": currency, "rate_per_hour": rate,
        "effective_date": effective, "source": source, "provider": job.provider,
        "additional_source_count": max(0, len(job.sources) - 1),
        "maximum_seconds_per_source": settings.media_max_duration_seconds,
        "basis": "measured_duration_x_immutable_public_tariff", "invoice_debit": False}
    job.long_duration_preflight_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    job.long_duration_cost_confirmed = False
    db.flush()


def confirmed_source_duration(job, relation_id):
    """Consent covers only the measured source and unchanged requested interval."""
    if not getattr(job, "long_duration_cost_confirmed", False) or long_media_preflight_payload(job) is None:
        return None
    payload = json.loads(job.long_duration_preflight_json)
    if (payload.get("job_source_id") != relation_id
        or payload.get("clip_start_seconds") != job.media_clip_start_seconds
        or payload.get("clip_end_seconds") != job.media_clip_end_seconds):
        return None
    return payload["source_duration_seconds"]


def long_media_preflight_payload(job):
    raw = getattr(job, "long_duration_preflight_json", None)
    if not isinstance(raw, str) or len(raw) > 4096:
        return None
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("provider") != job.provider:
            return None
        for field in ("source_duration_seconds", "selected_duration_seconds"):
            if type(payload.get(field)) not in {float, int} or not math.isfinite(payload[field]) or payload[field] < 0:
                return None
        if payload["selected_duration_seconds"] > payload["source_duration_seconds"]:
            return None
        if (type(payload.get("additional_source_count")) is not int or not 0 <= payload["additional_source_count"] <= 50
            or type(payload.get("maximum_seconds_per_source")) is not int or payload["maximum_seconds_per_source"] <= 0):
            return None
        pricing = tuple(payload.get(key) for key in ("nominal_cost", "currency", "rate_per_hour", "effective_date", "source"))
        if any(value is not None for value in pricing):
            if (not all(value is not None for value in pricing)
                or pricing[1] != "USD" or pricing[4] != {"elevenlabs": "elevenlabs_public_api_pricing", "yandex": "yandex_public_api_pricing"}.get(payload["provider"])
                or any(not isinstance(pricing[index], str) or not re.fullmatch(r"\d{1,9}(?:\.\d{1,8})?", pricing[index]) for index in (0, 2))
                or Decimal(pricing[2]) <= 0):
                return None
            date.fromisoformat(pricing[3])
        if payload.get("basis") != "measured_duration_x_immutable_public_tariff" or payload.get("invoice_debit") is not False:
            return None
        # Return only fields written by this module; a corrupt/legacy JSON object
        # cannot smuggle private identities into the owner DTO.
        keys = ("source_duration_seconds", "selected_duration_seconds", "nominal_cost", "currency", "rate_per_hour",
            "effective_date", "source", "provider", "additional_source_count", "maximum_seconds_per_source", "basis", "invoice_debit")
        return {**{key: payload.get(key) for key in keys}, "confirmation_token": hashlib.sha256((job.id + raw).encode()).hexdigest()}
    except (ValueError, TypeError):
        return None
