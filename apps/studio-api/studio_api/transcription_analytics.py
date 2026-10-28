from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any
from decimal import Decimal

from .transcription_metadata import selected_provider, analytics_bucket
from .transcription_options import browser_language_mode, job_diarization_enabled


JOB_STATUSES = ("queued", "processing", "completed", "failed", "cancelled")


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return raw if isinstance(raw, str) else ""


def _duration_seconds(
    started_at: datetime | None,
    finished_at: datetime | None,
) -> float | None:
    if started_at is None or finished_at is None:
        return None
    seconds = (finished_at - started_at).total_seconds()
    return seconds if seconds >= 0 else None


def _duration_summary(values: Iterable[float]) -> dict[str, int | float | None]:
    samples = sorted(value for value in values if math.isfinite(value) and value >= 0)
    if not samples:
        return {
            "sample_count": 0,
            "average_seconds": None,
            "p50_seconds": None,
            "p95_seconds": None,
        }

    def nearest_rank(percentile: float) -> float:
        return samples[max(0, math.ceil(percentile * len(samples)) - 1)]

    return {
        "sample_count": len(samples),
        "average_seconds": round(sum(samples) / len(samples), 1),
        "p50_seconds": round(statistics.median(samples), 1),
        "p95_seconds": round(nearest_rank(0.95), 1),
    }


def _selected_provider(
    job: Any,
    provider_by_credential_id: Mapping[str, str],
) -> str:
    credential_id = getattr(job, "provider_credential_id", None)
    return selected_provider(getattr(job, "provider", None), provider_by_credential_id.get(credential_id))


def build_transcription_analytics_payload(
    *,
    jobs: Iterable[Any],
    source_count: int,
    output_count: int,
    attempts: Iterable[Any],
    provider_by_credential_id: Mapping[str, str],
    since: datetime | None = None,
) -> dict[str, Any]:
    job_rows = list(jobs)
    attempt_rows = list(attempts)
    outcomes = {status: 0 for status in JOB_STATUSES}
    provider_model = {"elevenlabs_scribe_v2": 0, "yandex_general": 0, "yandex_deferred_general": 0, "mistral_voxtral_small_transcribe_3": 0, "gemini_35_transcribe": 0, "tbank_default": 0, "unknown": 0}
    language_mode = {"ru": 0, "en": 0, "detect": 0, "other": 0}
    diarization = {"enabled": 0, "disabled": 0}
    queue_durations: list[float] = []
    processing_durations: list[float] = []
    billed_duration_ms = 0
    confirmed_cost = Decimal("0")
    accounting_counts = {
        "complete_jobs": 0,
        "uncertain_jobs": 0,
        "unavailable_jobs": 0,
        "in_progress_jobs": 0,
    }

    for job in job_rows:
        status = _enum_value(getattr(job, "status", ""))
        if status in outcomes:
            outcomes[status] += 1

        provider_key = analytics_bucket(_selected_provider(job, provider_by_credential_id),
            getattr(job, "options_json", None), getattr(job, "operating_mode", None))
        provider_model[provider_key] += 1

        selected_language = browser_language_mode(getattr(job, "language", None))
        language_key = (
            selected_language
            if selected_language in {"ru", "en", "detect"}
            else "other"
        )
        language_mode[language_key] += 1

        diarization_key = (
            "enabled"
            if job_diarization_enabled(getattr(job, "options_json", None))
            else "disabled"
        )
        diarization[diarization_key] += 1

        queue_duration = _duration_seconds(
            getattr(job, "created_at", None),
            getattr(job, "started_at", None),
        )
        if queue_duration is not None:
            queue_durations.append(queue_duration)
        processing_duration = _duration_seconds(
            getattr(job, "started_at", None),
            getattr(job, "finished_at", None),
        )
        if processing_duration is not None:
            processing_durations.append(processing_duration)
        raw_duration = getattr(job, "provider_billed_duration_ms", None)
        if raw_duration is None:
            accounting_counts["unavailable_jobs"] += 1
        elif getattr(job, "provider_accounting_uncertain", False):
            accounting_counts["uncertain_jobs"] += 1
        elif getattr(job, "provider_accounting_complete", False):
            accounting_counts["complete_jobs"] += 1
        else:
            accounting_counts["in_progress_jobs"] += 1
        if raw_duration is not None:
            billed_duration_ms += max(0, int(raw_duration))
            confirmed_cost += Decimal(
                str(getattr(job, "provider_cost_amount", None) or 0)
            )

    provider_durations: list[float] = []
    post_provider_durations: list[float] = []
    for attempt in attempt_rows:
        provider_duration = _duration_seconds(
            getattr(attempt, "provider_request_started_at", None),
            getattr(attempt, "provider_response_returned_at", None),
        )
        if provider_duration is not None:
            provider_durations.append(provider_duration)
        post_provider_duration = _duration_seconds(
            getattr(attempt, "provider_response_returned_at", None),
            getattr(attempt, "completed_at", None),
        )
        if post_provider_duration is not None:
            post_provider_durations.append(post_provider_duration)

    terminal_jobs = sum(
        outcomes[status] for status in ("completed", "failed", "cancelled")
    )
    successful_jobs = outcomes["completed"]

    return {
        "scope": "project_since_reset" if since is not None else "project_all_time",
        "totals": {
            "jobs": len(job_rows),
            "sources": max(0, int(source_count)),
            "outputs": max(0, int(output_count)),
        },
        "outcomes": outcomes,
        "success": {
            "successful_jobs": successful_jobs,
            "terminal_jobs": terminal_jobs,
            "percentage": (
                round(successful_jobs / terminal_jobs * 100, 1)
                if terminal_jobs > 0
                else None
            ),
        },
        "configuration": {
            "provider_model": provider_model,
            "language_mode": language_mode,
            "diarization": diarization,
        },
        "usage_cost": _usage_cost_payload(
            billed_duration_ms, confirmed_cost, accounting_counts
        ),
        "durations": {
            "queue": _duration_summary(queue_durations),
            "processing": _duration_summary(processing_durations),
            "provider_processing": _duration_summary(provider_durations),
            "post_provider_output": _duration_summary(post_provider_durations),
        },
    }


def load_transcription_analytics_payload(
    db: Any,
    *,
    owner_user_id: str,
    project_id: str,
    since: datetime | None = None,
):
    from sqlalchemy import and_, case, func

    from .models import (
        ProviderCredential,
        TranscriptionJob,
        TranscriptionJobOutput,
        TranscriptionJobSource,
        TranscriptionJobSourceAttempt,
    )

    scope_filters = [
        TranscriptionJob.owner_user_id == owner_user_id,
        TranscriptionJob.project_id == project_id,
    ]
    if since is not None:
        scope_filters.append(TranscriptionJob.created_at > since)

    outcomes = {status: 0 for status in JOB_STATUSES}
    provider_model = {"elevenlabs_scribe_v2": 0, "yandex_general": 0, "yandex_deferred_general": 0, "mistral_voxtral_small_transcribe_3": 0, "gemini_35_transcribe": 0, "tbank_default": 0, "unknown": 0}
    language_mode = {"ru": 0, "en": 0, "detect": 0, "other": 0}
    diarization = {"enabled": 0, "disabled": 0}
    total_jobs = 0

    configuration_rows = (
        db.query(
            TranscriptionJob.status,
            TranscriptionJob.provider,
            ProviderCredential.provider,
            TranscriptionJob.language,
            TranscriptionJob.options_json,
            TranscriptionJob.operating_mode,
            func.count(TranscriptionJob.id),
        )
        .outerjoin(
            ProviderCredential,
            and_(
                ProviderCredential.id == TranscriptionJob.provider_credential_id,
                ProviderCredential.user_id == owner_user_id,
            ),
        )
        .filter(*scope_filters)
        .group_by(
            TranscriptionJob.status,
            TranscriptionJob.provider,
            ProviderCredential.provider,
            TranscriptionJob.language,
            TranscriptionJob.options_json,
            TranscriptionJob.operating_mode,
        )
        .yield_per(500)
    )
    for (
        status,
        explicit_provider,
        credential_provider,
        language,
        options_json,
        operating_mode,
        raw_count,
    ) in configuration_rows:
        count = max(0, int(raw_count or 0))
        total_jobs += count
        status_key = _enum_value(status)
        if status_key in outcomes:
            outcomes[status_key] += count
        provider_model[analytics_bucket(selected_provider(explicit_provider, _enum_value(credential_provider)), options_json, operating_mode)] += count
        selected_language = browser_language_mode(language)
        language_mode[
            selected_language
            if selected_language in {"ru", "en", "detect"}
            else "other"
        ] += count
        diarization[
            "enabled" if job_diarization_enabled(options_json) else "disabled"
        ] += count

    def related_count(model: Any) -> int:
        return int(
            db.query(func.count(model.id))
            .join(TranscriptionJob, TranscriptionJob.id == model.job_id)
            .filter(*scope_filters)
            .scalar()
            or 0
        )

    def duration_summary(
        *,
        started_column: Any,
        finished_column: Any,
        join_job: bool = False,
    ) -> dict[str, int | float | None]:
        bind = db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""
        query = db.query(started_column, finished_column)
        if join_job:
            query = query.select_from(TranscriptionJobSourceAttempt).join(
                TranscriptionJob,
                TranscriptionJob.id == TranscriptionJobSourceAttempt.job_id,
            )
        query = query.filter(
            *scope_filters,
            started_column.is_not(None),
            finished_column.is_not(None),
            finished_column >= started_column,
        )
        if dialect_name == "postgresql":
            seconds = func.extract("epoch", finished_column - started_column)
            count, average, p50, p95 = query.with_entities(
                func.count(),
                func.avg(seconds),
                func.percentile_cont(0.5).within_group(seconds),
                func.percentile_disc(0.95).within_group(seconds),
            ).one()
            return {
                "sample_count": int(count or 0),
                "average_seconds": round(float(average), 1) if average is not None else None,
                "p50_seconds": round(float(p50), 1) if p50 is not None else None,
                "p95_seconds": round(float(p95), 1) if p95 is not None else None,
            }
        # SQLite is used by local/unit validation. Stream its small test rows;
        # production PostgreSQL always uses the exact server-side aggregate.
        return _duration_summary(
            (finished - started).total_seconds()
            for started, finished in query.yield_per(500)
        )

    source_count = related_count(TranscriptionJobSource)
    output_count = related_count(TranscriptionJobOutput)
    terminal_jobs = sum(
        outcomes[status] for status in ("completed", "failed", "cancelled")
    )
    successful_jobs = outcomes["completed"]
    (
        billed_duration_ms,
        confirmed_cost,
        complete_jobs,
        uncertain_jobs,
        unavailable_jobs,
    ) = db.query(
        func.coalesce(func.sum(TranscriptionJob.provider_billed_duration_ms), 0),
        func.coalesce(func.sum(TranscriptionJob.provider_cost_amount), 0),
        func.coalesce(
            func.sum(case((TranscriptionJob.provider_accounting_complete.is_(True), 1), else_=0)),
            0,
        ),
        func.coalesce(
            func.sum(case((TranscriptionJob.provider_accounting_uncertain.is_(True), 1), else_=0)),
            0,
        ),
        func.coalesce(
            func.sum(case((TranscriptionJob.provider_billed_duration_ms.is_(None), 1), else_=0)),
            0,
        ),
    ).filter(*scope_filters).one()
    accounting_counts = {
        "complete_jobs": int(complete_jobs or 0),
        "uncertain_jobs": int(uncertain_jobs or 0),
        "unavailable_jobs": int(unavailable_jobs or 0),
        "in_progress_jobs": max(
            0,
            total_jobs
            - int(complete_jobs or 0)
            - int(uncertain_jobs or 0)
            - int(unavailable_jobs or 0),
        ),
    }
    return {
        "scope": "project_since_reset" if since is not None else "project_all_time",
        "totals": {
            "jobs": total_jobs,
            "sources": source_count,
            "outputs": output_count,
        },
        "outcomes": outcomes,
        "success": {
            "successful_jobs": successful_jobs,
            "terminal_jobs": terminal_jobs,
            "percentage": (
                round(successful_jobs / terminal_jobs * 100, 1)
                if terminal_jobs > 0
                else None
            ),
        },
        "configuration": {
            "provider_model": provider_model,
            "language_mode": language_mode,
            "diarization": diarization,
        },
        "usage_cost": _usage_cost_payload(
            int(billed_duration_ms or 0),
            Decimal(str(confirmed_cost or 0)),
            accounting_counts,
        ),
        "durations": {
            "queue": duration_summary(
                started_column=TranscriptionJob.created_at,
                finished_column=TranscriptionJob.started_at,
            ),
            "processing": duration_summary(
                started_column=TranscriptionJob.started_at,
                finished_column=TranscriptionJob.finished_at,
            ),
            "provider_processing": duration_summary(
                started_column=TranscriptionJobSourceAttempt.provider_request_started_at,
                finished_column=TranscriptionJobSourceAttempt.provider_response_returned_at,
                join_job=True,
            ),
            "post_provider_output": duration_summary(
                started_column=TranscriptionJobSourceAttempt.provider_response_returned_at,
                finished_column=TranscriptionJobSourceAttempt.completed_at,
                join_job=True,
            ),
        },
    }


def _usage_cost_payload(
    billed_duration_ms: int,
    confirmed_cost: Decimal,
    counts: Mapping[str, int],
) -> dict[str, Any]:
    return {
        "confirmed_billed_duration_seconds": round(
            max(0, int(billed_duration_ms)) / 1000, 3
        ),
        "confirmed_provider_cost": format(
            max(Decimal("0"), confirmed_cost).quantize(Decimal("0.00000001")),
            "f",
        ),
        "currency": "USD",
        "cost_basis": "confirmed_audio_duration_x_rate_snapshot",
        "complete_jobs": max(0, int(counts.get("complete_jobs", 0))),
        "uncertain_jobs": max(0, int(counts.get("uncertain_jobs", 0))),
        "unavailable_jobs": max(0, int(counts.get("unavailable_jobs", 0))),
        "in_progress_jobs": max(0, int(counts.get("in_progress_jobs", 0))),
    }
