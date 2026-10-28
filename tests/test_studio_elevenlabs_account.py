from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


def _subscription_payload():
    return {
        "tier": "creator",
        "character_count": 2500,
        "character_limit": 10000,
        "max_credit_limit_extension": 5000,
        "can_extend_character_limit": True,
        "allowed_to_extend_character_limit": True,
        "voice_slots_used": 0,
        "professional_voice_slots_used": 0,
        "professional_voice_slots_used_in_workspace": 0,
        "voice_limit": 0,
        "voice_add_edit_counter": 0,
        "professional_voice_limit": 0,
        "can_extend_voice_limit": False,
        "can_use_instant_voice_cloning": False,
        "can_use_professional_voice_cloning": False,
        "current_overage": {"amount": "1.25", "currency": "usd"},
        "status": "active",
        "open_invoices": [
            {
                "amount_due_cents": 125,
                "subtotal_cents": 100,
                "tax_cents": 25,
            }
        ],
        "has_open_invoices": True,
        "next_character_count_reset_unix": 1798761600,
        "currency": "usd",
        "billing_period": "monthly_period",
        "character_refresh_period": "monthly_period",
        "next_invoice": {
            "amount_due_cents": 2299,
            "subtotal_cents": 2000,
            "tax_cents": 299,
            "next_payment_attempt_unix": 1798761600,
        },
        "pending_change": None,
    }


def _usage_payload():
    return {
        "columns": ["timestamp", "product_type", "credits_used"],
        "column_types": ["DateTime", "String", "Float"],
        "rows": [
            ["2026-08-29T00:00:00Z", "speech-to-text", "125.5"],
            ["2026-08-30T00:00:00Z", "speech-to-text", "4.5"],
            ["2026-08-30T00:00:00Z", "text-to-speech", "10"],
        ],
        "column_units": ["s", "", "credits"],
    }


def _runtime_usage_payload():
    # Column names/types/units verified by the owner's 2026-08-31 diagnostic.
    # All products, timestamps and amounts below are synthetic, not a raw export.
    return {
        "columns": ["product_type", "timestamp", "total_usage", "total_minutes", "total_cost", "usage_count", "total_charge_count"],
        "column_types": ["String", "DateTime", "Int", "Float", "Float", "Int", "Float"],
        "column_units": [None, None, "credits", "min", "usd", None, None],
        "rows": [
            ["speech-to-text", "2026-08-29T00:00:00Z", 125, 3.5, 0.75, 1, 1.25],
            ["speech-to-text", "2026-08-30T00:00:00Z", 5, 0, 0, 1, 0],
            ["text-to-speech", "2026-08-30T00:00:00Z", 10, 0.5, 0.25, 1, 0.5],
        ],
    }


@pytest.mark.parametrize("usage_payload", [_usage_payload, _runtime_usage_payload], ids=["documented", "runtime"])
def test_transport_normalizes_subscription_and_product_credit_usage(usage_payload):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request):
        requests.append(request)
        assert request.headers["xi-api-key"] == "private-account-key"
        if request.method == "GET":
            return httpx.Response(200, json=_subscription_payload())
        assert json.loads(request.content)["group_by"] == ["product_type"]
        return httpx.Response(200, json=usage_payload())

    from studio_api.elevenlabs_account import ElevenLabsAccountTransport

    client = httpx.Client(transport=httpx.MockTransport(handler))
    transport = ElevenLabsAccountTransport(client=client)
    subscription = transport.fetch_subscription("private-account-key")
    assert subscription.tier == "creator"
    assert subscription.period_remaining == 7500
    assert subscription.current_overage_amount == Decimal("1.25000000")
    assert subscription.next_invoice_amount_due_cents == 2299
    usage = transport.fetch_workspace_usage(
        "private-account-key",
        subscription=subscription,
        now=datetime(2026, 8, 30, 12, tzinfo=timezone.utc),
    )
    assert usage.unit == "credits"
    assert usage.total_credits == Decimal("140.00000000")
    assert [(item.product_type, item.credits) for item in usage.products] == [
        ("speech-to-text", Decimal("130.00000000")),
        ("text-to-speech", Decimal("10.00000000")),
    ]
    assert len(requests) == 2


def _normalize_usage(payload):
    from studio_api.elevenlabs_account import normalize_workspace_usage

    return normalize_workspace_usage(
        payload,
        window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 30, tzinfo=timezone.utc),
        window_basis="rolling_30_days",
    )


@pytest.mark.parametrize("empty", [False, True])
def test_runtime_usage_resolves_columns_by_name_and_accepts_empty_window(empty):
    payload = _runtime_usage_payload()
    for key in ("columns", "column_types", "column_units"):
        payload[key].reverse()
    payload["rows"] = [] if empty else [list(reversed(row)) for row in payload["rows"]]
    result = _normalize_usage(payload)
    assert result.total_credits == Decimal("0" if empty else "140")
    assert result.unit == "credits"


@pytest.mark.parametrize("unit", [None, "", "min", "usd", "seconds", [], {}])
def test_runtime_total_usage_requires_explicit_credit_unit(unit):
    from studio_api.elevenlabs_account import ElevenLabsAccountError

    payload = _runtime_usage_payload()
    payload["column_units"][2] = unit
    with pytest.raises(ElevenLabsAccountError, match="malformed_provider_response"):
        _normalize_usage(payload)


@pytest.mark.parametrize("value", [None, True, -1, "NaN", "Infinity", "1e19", {}])
def test_runtime_usage_rejects_invalid_credit_cells_without_partial_totals(value):
    from studio_api.elevenlabs_account import ElevenLabsAccountError

    payload = _runtime_usage_payload()
    payload["rows"][-1][2] = value
    with pytest.raises(ElevenLabsAccountError, match="malformed_provider_response"):
        _normalize_usage(payload)


@pytest.mark.parametrize("column", ["credits_used", "total_usage", "unknown_metric", [], {}])
def test_usage_rejects_ambiguous_duplicate_missing_or_nonstring_columns(column):
    from studio_api.elevenlabs_account import ElevenLabsAccountError

    payload = _runtime_usage_payload()
    if column == "unknown_metric":
        payload["columns"][2] = column
    else:
        payload["columns"][3] = column
        payload["column_units"][3] = "credits"
    with pytest.raises(ElevenLabsAccountError, match="malformed_provider_response"):
        _normalize_usage(payload)


# InvoiceResponse permits nullable/omitted subtotal/tax and the exact integer
# -1 for no scheduled payment; do not apply that sentinel to other timestamps.
# https://github.com/elevenlabs/elevenlabs-python/blob/a33cb6a262897dc7e453f32cd0770dc515b09634/src/elevenlabs/types/invoice_response.py
@pytest.mark.parametrize("field", ["subtotal_cents", "tax_cents"])
@pytest.mark.parametrize("case", ["missing", "null", "zero", "positive"])
def test_subscription_accepts_optional_invoice_amounts_without_inventing_zero(field, case):
    from studio_api.elevenlabs_account import normalize_subscription

    payload = _subscription_payload()
    if case == "missing":
        payload["next_invoice"].pop(field)
        expected = None
    else:
        expected = {"null": None, "zero": 0, "positive": 125}[case]
        payload["next_invoice"][field] = expected

    snapshot = normalize_subscription(payload)
    assert getattr(snapshot, "next_invoice_" + field) == expected
    assert snapshot.next_invoice_amount_due_cents == 2299
    assert snapshot.current_overage_amount == Decimal("1.25000000")


@pytest.mark.parametrize("case", ["missing", "null", "not_scheduled", "epoch", "scheduled"])
def test_subscription_accepts_documented_next_payment_attempt_states(case):
    from studio_api.elevenlabs_account import normalize_subscription

    payload = _subscription_payload()
    value = {"null": None, "not_scheduled": -1, "epoch": 0, "scheduled": 1798761600}
    if case == "missing":
        payload["next_invoice"].pop("next_payment_attempt_unix")
    else:
        payload["next_invoice"]["next_payment_attempt_unix"] = value[case]

    snapshot = normalize_subscription(payload)
    if case in {"missing", "null", "not_scheduled"}:
        assert snapshot.next_payment_attempt_at is None
    else:
        assert snapshot.next_payment_attempt_at == datetime.fromtimestamp(value[case], timezone.utc)
    assert snapshot.reset_at == datetime.fromtimestamp(1798761600, timezone.utc)


@pytest.mark.parametrize("field", ["amount_due_cents", "subtotal_cents", "tax_cents"])
@pytest.mark.parametrize("value", [-1, True, 1.5, "0", {}, 9_007_199_254_740_992])
def test_subscription_still_rejects_invalid_invoice_amounts(field, value):
    from studio_api.elevenlabs_account import ElevenLabsAccountError, normalize_subscription

    payload = _subscription_payload()
    payload["next_invoice"][field] = value
    with pytest.raises(ElevenLabsAccountError, match="malformed_provider_response"):
        normalize_subscription(payload)


@pytest.mark.parametrize("missing", [True, False])
def test_subscription_invoice_amount_due_remains_required(missing):
    from studio_api.elevenlabs_account import ElevenLabsAccountError, normalize_subscription

    payload = _subscription_payload()
    if missing:
        payload["next_invoice"].pop("amount_due_cents")
    else:
        payload["next_invoice"]["amount_due_cents"] = None
    with pytest.raises(ElevenLabsAccountError, match="malformed_provider_response"):
        normalize_subscription(payload)


@pytest.mark.parametrize("value", [-2, -1.0, "-1", True, 1.5, {}, 9_007_199_254_740_992])
def test_subscription_rejects_invalid_payment_attempt_values(value):
    from studio_api.elevenlabs_account import ElevenLabsAccountError, normalize_subscription

    payload = _subscription_payload()
    payload["next_invoice"]["next_payment_attempt_unix"] = value
    with pytest.raises(ElevenLabsAccountError, match="malformed_provider_response"):
        normalize_subscription(payload)


def test_subscription_does_not_allow_payment_sentinel_for_reset_date():
    from studio_api.elevenlabs_account import ElevenLabsAccountError, normalize_subscription

    payload = _subscription_payload()
    payload["next_character_count_reset_unix"] = -1
    with pytest.raises(ElevenLabsAccountError, match="malformed_provider_response"):
        normalize_subscription(payload)


@pytest.mark.parametrize("status,reason", [(401, "provider_authentication_rejected"), (403, "provider_scope_rejected"), (429, "provider_rate_limited"), (503, "provider_unavailable")])
def test_transport_classifies_safe_provider_failures(status, reason):
    from studio_api.elevenlabs_account import (
        ElevenLabsAccountError,
        ElevenLabsAccountTransport,
    )

    client = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(status))
    )
    with pytest.raises(ElevenLabsAccountError, match=reason):
        ElevenLabsAccountTransport(client=client).fetch_subscription("never-echo")


def test_transport_rejects_malformed_or_unbounded_usage_without_partial_totals():
    from studio_api.elevenlabs_account import (
        ElevenLabsAccountError,
        normalize_workspace_usage,
    )

    with pytest.raises(ElevenLabsAccountError, match="malformed_provider_response"):
        normalize_workspace_usage(
            {
                "columns": ["timestamp", "product_type", "credits_used"],
                "column_units": ["s", "", "seconds"],
                "rows": [["2026-08-30T00:00:00Z", "speech-to-text", "60"]],
            },
            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 30, tzinfo=timezone.utc),
            window_basis="rolling_30_days",
        )


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    from studio_api.config import get_settings

    get_settings.cache_clear()
    from studio_api.db import Base
    import studio_api.models  # noqa: F401

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()
    get_settings.cache_clear()


class _SuccessfulTransport:
    def fetch_subscription(self, _api_key):
        from studio_api.elevenlabs_account import normalize_subscription

        return normalize_subscription(_subscription_payload())

    def fetch_workspace_usage(self, _api_key, *, subscription, now):
        from studio_api.elevenlabs_account import normalize_workspace_usage

        return normalize_workspace_usage(
            _usage_payload(),
            window_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            window_end=now,
            window_basis="provider_reset_period",
        )


class _FailedTransport:
    def fetch_subscription(self, _api_key):
        from studio_api.elevenlabs_account import (
            ElevenLabsAccountError,
            ElevenLabsAccountReason,
        )

        raise ElevenLabsAccountError(ElevenLabsAccountReason.provider_rate_limited)


class _UnexpectedTransport:
    def fetch_subscription(self, _api_key):
        raise AssertionError("fresh or recently failed snapshot must not call provider")


def _credential(db: Session):
    from studio_api import models as m

    user = m.User(email="account-sync@example.test")
    db.add(user)
    db.flush()
    credential = m.ProviderCredential(
        user_id=user.id,
        provider=m.CredentialProvider.elevenlabs,
        label="Основной",
        status=m.CredentialStatus.active,
    )
    db.add(credential)
    db.flush()
    version = m.ProviderCredentialVersion(
        credential_id=credential.id,
        version=1,
        ciphertext=b"not-used",
        nonce=b"not-used",
        key_id="test",
        masked_value="••••1234",
        fingerprint="f" * 64,
    )
    db.add(version)
    db.flush()
    credential.active_version_id = version.id
    db.commit()
    return user, credential, version


def test_snapshot_is_version_scoped_fresh_and_failed_refresh_becomes_stale(db):
    from studio_api.provider_account_sync import (
        provider_account_payload,
        sync_elevenlabs_account,
    )

    user, credential, version = _credential(db)
    now = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
    row = sync_elevenlabs_account(
        db,
        owner_user_id=user.id,
        credential=credential,
        credential_version_id=version.id,
        api_key="not-returned",
        now=now,
        transport=_SuccessfulTransport(),
    )
    db.commit()
    payload = provider_account_payload(
        row, credential=credential, active_version=1, now=now
    )
    assert payload["state"] == "current"
    assert payload["subscription"]["period_remaining"] == 7500
    assert payload["subscription"]["current_overage"] == {
        "amount": "1.25000000",
        "currency": "USD",
    }
    assert payload["workspace_usage"]["total"] == "140.00000000"
    assert "not-returned" not in json.dumps(payload)

    cached = sync_elevenlabs_account(
        db,
        owner_user_id=user.id,
        credential=credential,
        credential_version_id=version.id,
        api_key="not-returned",
        now=now,
        transport=_UnexpectedTransport(),
    )
    assert cached.id == row.id

    row = sync_elevenlabs_account(
        db,
        owner_user_id=user.id,
        credential=credential,
        credential_version_id=version.id,
        api_key="still-not-returned",
        now=now,
        force=True,
        transport=_FailedTransport(),
    )
    db.commit()
    stale = provider_account_payload(
        row, credential=credential, active_version=1, now=now
    )
    assert stale["state"] == "stale"
    assert stale["error_code"] == "provider_rate_limited"
    assert stale["subscription"]["tier"] == "creator"

    backed_off = sync_elevenlabs_account(
        db,
        owner_user_id=user.id,
        credential=credential,
        credential_version_id=version.id,
        api_key="not-returned",
        now=now,
        transport=_UnexpectedTransport(),
    )
    assert backed_off.last_error_code == "provider_rate_limited"


def test_credential_version_change_never_serves_previous_snapshot_as_stale(db):
    from studio_api.provider_account_sync import (
        provider_account_payload,
        sync_elevenlabs_account,
    )

    user, credential, version = _credential(db)
    now = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
    sync_elevenlabs_account(
        db,
        owner_user_id=user.id,
        credential=credential,
        credential_version_id=version.id,
        api_key="old",
        now=now,
        transport=_SuccessfulTransport(),
    )
    row = sync_elevenlabs_account(
        db,
        owner_user_id=user.id,
        credential=credential,
        credential_version_id="new-version-id",
        api_key="new",
        now=now,
        force=True,
        transport=_FailedTransport(),
    )
    db.commit()
    payload = provider_account_payload(
        row, credential=credential, active_version=2, now=now
    )
    assert payload["state"] == "unavailable"
    assert payload["subscription"] is None
    assert payload["workspace_usage"]["products"] == []


@pytest.mark.parametrize("usage_payload", [_usage_payload, _runtime_usage_payload], ids=["documented", "runtime"])
def test_nullable_invoice_refresh_persists_and_projects_absence_not_old_values(db, usage_payload):
    from studio_api.provider_account_sync import provider_account_payload, sync_elevenlabs_account

    user, credential, version = _credential(db)
    now = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
    row = sync_elevenlabs_account(
        db,
        owner_user_id=user.id,
        credential=credential,
        credential_version_id=version.id,
        api_key="never-returned",
        now=now,
        transport=_SuccessfulTransport(),
    )
    db.commit()
    assert row.next_invoice_tax_cents == 299

    response = _subscription_payload()
    response["next_invoice"].pop("subtotal_cents")
    response["next_invoice"].update(tax_cents=None, next_payment_attempt_unix=-1)
    from studio_api.elevenlabs_account import ElevenLabsAccountTransport

    requests = []

    def handler(request):
        requests.append(request.method)
        return httpx.Response(200, json=response if request.method == "GET" else usage_payload())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        row = sync_elevenlabs_account(
            db,
            owner_user_id=user.id,
            credential=credential,
            credential_version_id=version.id,
            api_key="never-returned",
            now=now,
            force=True,
            transport=ElevenLabsAccountTransport(client=client),
        )
    db.commit()
    db.refresh(row)
    assert row.next_invoice_subtotal_cents is None
    assert row.next_invoice_tax_cents is None
    assert row.next_payment_attempt_at is None
    projected = provider_account_payload(row, credential=credential, active_version=1, now=now)
    assert projected["state"] == "current"
    assert projected["error_code"] is None
    assert projected["subscription"]["next_invoice"] == {
        "amount_due_cents": 2299,
        "subtotal_cents": None,
        "tax_cents": None,
        "currency": "USD",
        "payment_attempt_at": None,
    }
    assert projected["workspace_usage"]["total"] == "140.00000000"
    assert projected["workspace_usage"]["state"] == "current"
    assert projected["workspace_usage"]["error_code"] is None
    assert projected["workspace_usage"]["unit"] == "credits"
    assert all(key not in json.dumps(projected) for key in ("total_minutes", "total_cost", "total_charge_count"))
    assert requests == ["GET", "POST"]
    assert "never-returned" not in json.dumps(projected)


def test_provider_account_snapshot_migration_is_additive_direct_successor():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    scripts = ScriptDirectory.from_config(Config("apps/studio-api/alembic.ini"))
    assert scripts.get_heads() == ["0044_quality_progress"]
    revision = scripts.get_revision("0031_provider_account_snapshots")
    assert revision is not None
    assert revision.down_revision == "0030_provider_usage_accounting"
    source = (
        ROOT
        / "apps/studio-api/alembic/versions/0031_provider_account_snapshots.py"
    ).read_text(encoding="utf-8")
    assert 'release_safety = "additive"' in source
    assert "provider_account_snapshots" in source
    assert "partial provider account snapshot schema" in source
