"""Nominal measured-media quotes: immutable tariff, unknown and fencing."""
import sys
from pathlib import Path
from decimal import Decimal
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
from studio_api.long_media_preflight import record_long_media_preflight, long_media_preflight_payload
from test_studio_provider_usage_accounting import db, _context, _settings


def record(session, *, rate=Decimal("0.22")):
    _, now, job, relation, attempt = _context(session)
    settings = _settings(rate)
    settings.media_max_duration_seconds = 43200
    record_long_media_preflight(session, job_id=job.id, relation_id=relation.id, duration=18000,
        settings=settings, owner="worker", generation=7, now=now)
    return job, relation, now, settings


def test_quote_uses_measured_duration_and_locks_tariff_for_actual_usage(db):
    job, relation, now, settings = record(db)
    quote = long_media_preflight_payload(job)
    assert quote["source_duration_seconds"] == quote["selected_duration_seconds"] == 18000
    assert quote["nominal_cost"] == "1.10000000" and quote["currency"] == "USD"
    assert quote["invoice_debit"] is False and len(quote["confirmation_token"]) == 64
    assert job.provider_rate_per_hour == Decimal("0.220000")
    settings.elevenlabs_scribe_v2_rate_per_hour_usd = Decimal("9")
    record_long_media_preflight(db, job_id=job.id, relation_id=relation.id, duration=18000,
        settings=settings, owner="worker", generation=7, now=now)
    assert long_media_preflight_payload(job) == quote
    from studio_api.provider_usage_accounting import resolve_pricing_snapshot
    assert resolve_pricing_snapshot(job, _settings(None)).rate_per_hour == Decimal("0.220000")
    job.media_clip_start_seconds, job.media_clip_end_seconds = 3600, 7200
    record_long_media_preflight(db, job_id=job.id, relation_id=relation.id, duration=18000,
        settings=settings, owner="worker", generation=7, now=now)
    clipped = long_media_preflight_payload(job)
    assert clipped["selected_duration_seconds"] == 3600 and clipped["nominal_cost"] == "0.22000000"
    assert clipped["confirmation_token"] != quote["confirmation_token"]


def test_unknown_pricing_is_not_a_zero_cost_and_legacy_has_no_fake_estimate(db):
    job, _, _, _ = record(db, rate=None)
    quote = long_media_preflight_payload(job)
    assert quote["nominal_cost"] is None and quote["rate_per_hour"] is None and quote["currency"] is None
    assert long_media_preflight_payload(SimpleNamespace(long_duration_preflight_json=None)) is None


def test_stale_worker_cannot_replace_quote(db):
    job, relation, now, settings = record(db)
    previous = long_media_preflight_payload(job)
    with pytest.raises(RuntimeError, match="context_invalid"):
        record_long_media_preflight(db, job_id=job.id, relation_id=relation.id, duration=20000,
            settings=settings, owner="old-worker", generation=6, now=now)
    assert long_media_preflight_payload(job) == previous


def test_yandex_warning_uses_only_its_nominal_public_rate(db):
    from datetime import date
    _, now, job, relation, _ = _context(db)
    job.provider = "yandex"
    settings = _settings()
    settings.media_max_duration_seconds = 43200
    record_long_media_preflight(db, job_id=job.id, relation_id=relation.id, duration=18000,
        settings=settings, owner="worker", generation=7, now=now)
    assert long_media_preflight_payload(job)["nominal_cost"] is None
    settings.yandex_async_rate_per_hour_usd = Decimal("0.36")
    settings.yandex_pricing_effective_date = date(2026, 10, 6)
    settings.yandex_pricing_source = "yandex_public_api_pricing"
    record_long_media_preflight(db, job_id=job.id, relation_id=relation.id, duration=18000,
        settings=settings, owner="worker", generation=7, now=now)
    quote = long_media_preflight_payload(job)
    assert quote["nominal_cost"] == "1.80000000" and quote["source"] == "yandex_public_api_pricing"
    assert quote["invoice_debit"] is False


def test_consent_is_bound_to_source_and_clip_and_new_quote_revokes_it(db):
    from studio_api.long_media_preflight import confirmed_source_duration
    job, relation, now, settings = record(db)
    assert confirmed_source_duration(job, relation.id) is None
    job.long_duration_cost_confirmed = True
    assert confirmed_source_duration(job, relation.id) == 18000
    assert confirmed_source_duration(job, "other-source") is None
    job.media_clip_end_seconds = 60
    assert confirmed_source_duration(job, relation.id) is None
    job.media_clip_end_seconds = None
    record_long_media_preflight(db, job_id=job.id, relation_id=relation.id, duration=20000,
        settings=settings, owner="worker", generation=7, now=now)
    assert confirmed_source_duration(job, relation.id) is None
    assert job.long_duration_cost_confirmed is False


def test_edited_recording_quote_uses_prepared_duration_and_fences_the_original_clock(db):
    from studio_api.audio_timeline import AudioTimeline
    from studio_api.transcript_timeline import select_transcript_clock
    from studio_api.long_media_preflight import confirmed_source_duration
    import json

    job, relation, now, settings = record(db)
    job.media_timeline_version = 2
    job.media_clip_start_seconds, job.media_clip_end_seconds = 15 * 3600, 21 * 3600
    relation.source.prepared_audio_context_json = "recorded-parent-context"
    db.flush()
    original_duration = 24 * 3600 + .000125
    parent = AudioTimeline.from_seconds(original_duration, [(14 * 3600, original_duration)])
    source = SimpleNamespace(prepared_audio_context_json=relation.source.prepared_audio_context_json, original_timeline=parent)
    selection = select_transcript_clock(job, source)
    record_long_media_preflight(db, job_id=job.id, relation_id=relation.id, duration=parent.output_duration_seconds,
        settings=settings, owner="worker", generation=7, now=now, clock_selection=selection)
    quote = long_media_preflight_payload(job)
    assert quote["selected_duration_seconds"] == 6 * 3600 and quote["nominal_cost"] == "1.32000000"
    assert "clock_digest" not in quote and "clock_source_duration_seconds" not in quote
    assert json.loads(job.long_duration_preflight_json)["clip_start_seconds"] == 15 * 3600
    job.long_duration_cost_confirmed = True
    assert confirmed_source_duration(job, relation.id, clock_selection=selection) == round(parent.output_duration_seconds, 3)
    assert confirmed_source_duration(job, relation.id) is None  # Missing clock cannot reuse v2 consent.

    changed_parent = AudioTimeline.from_seconds(original_duration, [(13 * 3600, 17 * 3600), (18 * 3600, original_duration)])
    changed_selection = select_transcript_clock(job, SimpleNamespace(
        prepared_audio_context_json=source.prepared_audio_context_json, original_timeline=changed_parent))
    assert changed_parent.output_duration_seconds == parent.output_duration_seconds
    assert confirmed_source_duration(job, relation.id, clock_selection=changed_selection) is None
    previous = job.long_duration_preflight_json
    relation.source.prepared_audio_context_json = "changed-parent-context"
    db.flush()
    with pytest.raises(RuntimeError, match="context_invalid"):
        record_long_media_preflight(db, job_id=job.id, relation_id=relation.id, duration=parent.output_duration_seconds,
            settings=settings, owner="worker", generation=7, now=now, clock_selection=selection)
    assert job.long_duration_preflight_json == previous
