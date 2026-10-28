from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
STUDIO_API = ROOT / "apps" / "studio-api"
if str(STUDIO_API) not in sys.path:
    sys.path.insert(0, str(STUDIO_API))

from studio_api.stt_provider import (  # noqa: E402
    SttCapabilityError,
    SttCapabilityReason,
    SttOperatingMode,
    SttProvider,
    catalog_payload,
    resolve_capability,
    validate_selection,
)
from studio_api.stt_provider_health import (  # noqa: E402
    provider_health,
    record_provider_failure,
    record_provider_success,
)


def settings(**overrides):
    values = {
        "media_max_duration_seconds": 43_200,
        "elevenlabs_byok_enabled": True,
        "yandex_byok_enabled": True,
        "elevenlabs_economic_model": "scribe_v2",
        "elevenlabs_standard_model": "scribe_v2",
        "elevenlabs_premium_model": "scribe_v2",
        "elevenlabs_realtime_model": "scribe_v2_realtime",
        "yandex_economic_model": "deferred-general",
        "yandex_standard_model": "general",
        "yandex_premium_model": "general",
        "yandex_realtime_model": "general",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_catalog_exposes_provider_neutral_modes_and_limits():
    payload = catalog_payload(settings())
    providers = {entry["provider"]: entry for entry in payload["providers"]}

    assert set(providers) == {"elevenlabs", "yandex", "tbank", "mistral", "gemini"}
    assert [mode["mode"] for mode in providers["elevenlabs"]["modes"]] == [
        "economic",
        "standard",
        "premium",
        "realtime",
    ]
    yandex_modes = {mode["mode"]: mode for mode in providers["yandex"]["modes"]}
    assert yandex_modes["economic"]["transport"] == "deferred"
    assert yandex_modes["standard"]["file_constraints"] == {
        "max_bytes": 60 * 1024 * 1024,
        "max_duration_seconds": 14_400,
        "audio_channels": [1],
    }
    assert yandex_modes["realtime"]["transport"] == "grpc_relay"
    assert yandex_modes["realtime"]["file_constraints"]["max_duration_seconds"] == 300
    assert yandex_modes["realtime"]["diarization"] is False
    assert yandex_modes["standard"]["diarization"] is True
    assert yandex_modes["premium"]["diarization"] is True


@pytest.mark.parametrize("provider", ["tbank", "mistral", "gemini"])
def test_new_provider_configuration_is_explicit_and_does_not_claim_live(provider):
    config = settings(**{f"{provider}_byok_enabled": False})
    with pytest.raises(SttCapabilityError) as failure:
        resolve_capability(config, provider, "standard")
    assert failure.value.reason is SttCapabilityReason.provider_disabled
    with pytest.raises(SttCapabilityError): resolve_capability(settings(), provider, "realtime")


def test_gemini_checks_combination_and_selected_duration_before_dispatch():
    with pytest.raises(SttCapabilityError) as failure:
        validate_selection(settings(), provider="gemini", mode="standard", language="ru", diarization=True, dictionary_count=1)
    assert failure.value.reason is SttCapabilityReason.options_incompatible
    with pytest.raises(SttCapabilityError) as failure:
        validate_selection(settings(), provider="gemini", mode="standard", language="ru", diarization=True, duration_seconds=1800.01)
    assert failure.value.reason is SttCapabilityReason.duration_too_long
    validate_selection(settings(), provider="gemini", mode="standard", language="ru", diarization=True, duration_seconds=1800)
    validate_selection(settings(), provider="gemini", mode="standard", language="detect", diarization=False, dictionary_count=1, duration_seconds=3600)
    with pytest.raises(SttCapabilityError):
        validate_selection(settings(), provider="tbank", mode="standard", language="en", diarization=False)


def test_yandex_interactive_live_rejects_diarization_but_preserves_live_and_batch():
    live = validate_selection(settings(), provider="yandex", mode="realtime",
        language="ru", diarization=False)
    assert live.transport == "grpc_relay"
    with pytest.raises(SttCapabilityError) as failure:
        validate_selection(settings(), provider="yandex", mode="realtime",
            language="ru", diarization=True)
    assert failure.value.reason is SttCapabilityReason.diarization_unsupported
    for mode in ("standard", "premium"):
        batch = validate_selection(settings(), provider="yandex", mode=mode,
            language="ru", diarization=True)
        assert batch.diarization is True


def test_selection_enforces_capabilities_without_cross_provider_fallback():
    capability = validate_selection(
        settings(),
        provider=SttProvider.elevenlabs,
        mode=SttOperatingMode.premium,
        language="ru",
        diarization=True,
        dictionary_count=2,
    )
    assert capability.model == "scribe_v2"

    with pytest.raises(SttCapabilityError) as unsupported_dictionary:
        validate_selection(
            settings(),
            provider="yandex",
            mode="standard",
            language="ru",
            diarization=False,
            dictionary_count=1,
        )
    assert unsupported_dictionary.value.reason is SttCapabilityReason.dictionaries_unsupported

    with pytest.raises(SttCapabilityError) as disabled:
        resolve_capability(settings(yandex_byok_enabled=False), "yandex", "standard")
    assert disabled.value.reason is SttCapabilityReason.provider_disabled

    with pytest.raises(SttCapabilityError) as too_long:
        validate_selection(
            settings(),
            provider="yandex",
            mode="standard",
            language="detect",
            diarization=False,
            duration_seconds=14_401,
        )
    assert too_long.value.reason is SttCapabilityReason.duration_too_long


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _HealthDb:
    def __init__(self):
        self.row = None

    def get(self, _model, identity):
        if self.row and identity == (self.row.provider, self.row.operating_mode):
            return self.row
        return None

    def execute(self, _statement):
        return _ScalarResult(self.row)

    def add(self, row):
        self.row = row


def test_health_circuit_counts_only_provider_failures_and_accepts_aware_database_times():
    db = _HealthDb()
    now = datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)

    record_provider_failure(
        db,
        provider="yandex",
        operating_mode="standard",
        failure_code="media_preparation_failed",
        threshold=2,
        cooldown_seconds=300,
        now=now,
    )
    assert db.row is None

    record_provider_failure(
        db,
        provider="yandex",
        operating_mode="standard",
        failure_code="malformed_provider_response",
        threshold=2,
        cooldown_seconds=300,
        now=now,
    )
    assert db.row.consecutive_failures == 1

    record_provider_success(
        db,
        provider="yandex",
        operating_mode="standard",
        now=now,
    )

    for _ in range(2):
        record_provider_failure(
            db,
            provider="yandex",
            operating_mode="standard",
            failure_code="provider_unavailable",
            threshold=2,
            cooldown_seconds=300,
            now=now,
        )
    db.row.circuit_open_until = db.row.circuit_open_until.replace(tzinfo=timezone.utc)
    blocked = provider_health(db, provider="yandex", operating_mode="standard", now=now)
    assert blocked.available is False
    assert blocked.consecutive_failures == 2
    assert blocked.retry_after_seconds == 300

    record_provider_success(
        db,
        provider="yandex",
        operating_mode="standard",
        now=now,
    )
    assert provider_health(db, provider="yandex", operating_mode="standard", now=now).available


def test_byok_quota_failures_never_open_shared_circuit_and_legacy_state_is_ignored():
    from studio_api.models import SttProviderHealth

    db = _HealthDb()
    now = datetime(2026, 10, 24, 10, tzinfo=timezone.utc)
    for provider in ("elevenlabs", "yandex"):
        db.row = None
        for _ in range(5):
            record_provider_failure(db, provider=provider, operating_mode="realtime",
                failure_code="provider_rate_limited", threshold=3, cooldown_seconds=300, now=now)
        assert db.row is None
        assert provider_health(db, provider=provider, operating_mode="realtime", now=now).available
        db.row = SttProviderHealth(provider=provider, operating_mode="realtime", consecutive_failures=5,
            last_failure_code="provider_rate_limited", circuit_open_until=now + timedelta(seconds=300), updated_at=now)
        state = provider_health(db, provider=provider, operating_mode="realtime", now=now)
        assert state.available and state.consecutive_failures == 0
        record_provider_failure(db, provider=provider, operating_mode="realtime",
            failure_code="provider_unavailable", threshold=3, cooldown_seconds=300, now=now)
        assert db.row.consecutive_failures == 1
        assert db.row.circuit_open_until is None
