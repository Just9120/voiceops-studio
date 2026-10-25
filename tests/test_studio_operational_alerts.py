from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))
os.environ.setdefault("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("STUDIO_COOKIE_SECURE", "false")
os.environ.setdefault("STUDIO_APP_ORIGIN", "https://studio.test")

from studio_api.audit import audit  # noqa: E402
from studio_api import cli  # noqa: E402
from studio_api.config import Settings  # noqa: E402
from studio_api.db import Base  # noqa: E402
from studio_api.models import (  # noqa: E402
    AuditEvent,
    CredentialProvider,
    CredentialStatus,
    DiagnosticComponent,
    DiagnosticEvent,
    DiagnosticLevel,
    JobStatus,
    OperationalAlertDelivery,
    OperationalIncident,
    Project,
    ProviderAccountSnapshot,
    ProviderCredential,
    ProviderCredentialVersion,
    Source,
    SourceType,
    SourceUploadStatus,
    TranscriptionJob,
    User,
    UserStatus,
)
from studio_api.operational_alerts import (  # noqa: E402
    RuleObservation,
    acknowledge_incident,
    apply_rule_observation,
    claim_next_delivery,
    collect_rule_observations,
    complete_delivery,
    DeliveryClaim,
    _send_telegram,
    process_one_delivery,
    record_postgres_backup_outcome,
    run_observability_canary,
)
from studio_api.trace_context import reset_current_trace_id, set_current_trace_id  # noqa: E402


class AlertSettings(SimpleNamespace):
    def telegram_alerts_configured(self):
        return bool(self.alert_telegram_enabled)

    def telegram_alert_credentials(self):
        return "1234567890:unit-test-token-value", "-1001234567890"


def settings(*, telegram=False):
    return AlertSettings(
        alert_signal_window_seconds=900,
        alert_stuck_queue_seconds=900,
        alert_provider_failure_threshold=3,
        alert_limit_remaining_percent=15,
        alert_storage_limit_bytes=None,
        alert_incident_cooldown_seconds=300,
        alert_delivery_retry_seconds=60,
        alert_delivery_max_attempts=2,
        alert_telegram_timeout_seconds=2,
        alert_telegram_enabled=telegram,
    )


def test_blank_optional_storage_limit_uses_not_configured_state(monkeypatch):
    monkeypatch.setenv("STUDIO_ALERT_STORAGE_LIMIT_BYTES", "")
    assert Settings(_env_file=None).alert_storage_limit_bytes is None


def test_backup_monitor_owner_configuration_is_optional_but_bounded():
    assert Settings(_env_file=None, backup_monitor_owner_user_id="").backup_monitor_owner_user_id is None
    with pytest.raises(ValueError):
        Settings(_env_file=None, backup_monitor_owner_user_id="arbitrary-recipient")


@pytest.mark.parametrize("events,configured,expected", [
    ([], True, False),
    ([], False, False),
    ([(3600, "success")], True, False),
    ([(43199, "success")], True, False),
    ([(43200, "success")], True, False),
    ([(46800, "success")], False, False),
    ([(3600, "success"), (60, "failed")], True, True),
    ([(3600, "failed"), (60, "success")], True, False),
])
def test_cloudkeep_owns_freshness_but_reported_migration_failure_still_alerts(events, configured, expected):
    engine, _factory, db, owner = database()
    now = datetime(2026, 10, 18, 12)
    config = settings()
    config.backup_monitor_owner_user_id = owner.id if configured else None
    for age, outcome in events:
        db.add(AuditEvent(actor_user_id=owner.id, subject_user_id=owner.id,
                          event_type="ops.postgres_backup", outcome=outcome,
                          metadata_json="{}", created_at=now - timedelta(seconds=age)))
    db.flush()
    observation = next(o for o in collect_rule_observations(
        db, owner_user_id=owner.id, settings=config, now=now
    ) if o.incident_kind == "backup_failure")
    assert observation.firing is expected
    assert observation.evidence_count == int(expected)
    db.close()
    engine.dispose()


def test_another_owners_fresh_backup_does_not_mask_reported_failure():
    engine, _factory, db, owner = database()
    now = datetime(2026, 10, 18, 12)
    other = User(email="backup-other@example.test", status=UserStatus.active)
    db.add(other); db.flush()
    db.add(AuditEvent(actor_user_id=owner.id, subject_user_id=owner.id,
                      event_type="ops.postgres_backup", outcome="failed",
                      metadata_json="{}", created_at=now - timedelta(minutes=1)))
    db.add(AuditEvent(actor_user_id=other.id, subject_user_id=other.id,
                      event_type="ops.postgres_backup", outcome="success",
                      metadata_json="{}", created_at=now))
    db.flush()
    config = settings()
    config.backup_monitor_owner_user_id = owner.id
    observation = next(o for o in collect_rule_observations(
        db, owner_user_id=owner.id, settings=config, now=now
    ) if o.incident_kind == "backup_failure")
    assert observation.firing is True
    db.close()
    engine.dispose()


def database():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    owner = User(email="owner@example.com", status=UserStatus.active)
    db.add(owner)
    db.commit()
    return engine, factory, db, owner


def test_warning_requires_repeated_observation_and_deduplicates_recovery():
    engine, _factory, db, owner = database()
    now = datetime(2026, 9, 1, 12, 0, 0)
    observation = RuleObservation(
        "provider_unavailable", True, "warning", "provider_unavailable", 3
    )
    incident = apply_rule_observation(
        db, owner_user_id=owner.id, observation=observation, settings=settings(), now=now
    )
    assert incident is not None and incident.status == "pending"
    assert db.query(OperationalAlertDelivery).count() == 0

    incident = apply_rule_observation(
        db,
        owner_user_id=owner.id,
        observation=observation,
        settings=settings(),
        now=now + timedelta(seconds=60),
    )
    assert incident is not None and incident.status == "firing"
    apply_rule_observation(
        db,
        owner_user_id=owner.id,
        observation=observation,
        settings=settings(),
        now=now + timedelta(seconds=120),
    )
    assert db.query(OperationalAlertDelivery).filter_by(notification_kind="firing").count() == 1

    recovered = RuleObservation(
        "provider_unavailable", False, "warning", "provider_unavailable"
    )
    apply_rule_observation(
        db,
        owner_user_id=owner.id,
        observation=recovered,
        settings=settings(),
        now=now + timedelta(seconds=180),
    )
    apply_rule_observation(
        db,
        owner_user_id=owner.id,
        observation=recovered,
        settings=settings(),
        now=now + timedelta(seconds=240),
    )
    assert db.query(OperationalAlertDelivery).filter_by(notification_kind="recovery").count() == 1
    assert db.query(OperationalIncident).one().status == "resolved"
    db.close()
    engine.dispose()


def test_all_operational_rules_use_owner_scoped_bounded_signals():
    engine, _factory, db, owner = database()
    now = datetime(2026, 9, 1, 12, 0, 0)
    project = Project(owner_user_id=owner.id, title="Project")
    credential = ProviderCredential(
        user_id=owner.id,
        provider=CredentialProvider.elevenlabs,
        label="primary",
        status=CredentialStatus.active,
    )
    db.add_all([project, credential])
    db.flush()
    version = ProviderCredentialVersion(
        credential_id=credential.id,
        version=1,
        ciphertext=b"ciphertext",
        nonce=b"nonce",
        key_id="key-1",
        masked_value="...test",
        fingerprint="a" * 64,
    )
    db.add(version)
    db.flush()
    db.add_all(
        [
            TranscriptionJob(
                project_id=project.id,
                owner_user_id=owner.id,
                trace_id="trace_0123456789abcdef",
                status=JobStatus.queued,
                title="stuck",
                created_at=now - timedelta(seconds=901),
                updated_at=now - timedelta(seconds=901),
            ),
            Source(
                project_id=project.id,
                source_type=SourceType.local_upload,
                original_filename="reference.wav",
                size_bytes=900,
                upload_status=SourceUploadStatus.uploaded,
            ),
            ProviderAccountSnapshot(
                owner_user_id=owner.id,
                credential_id=credential.id,
                credential_version_id=version.id,
                period_limit=1000,
                period_remaining=100,
                period_unit="characters",
                updated_at=now,
            ),
            DiagnosticEvent(
                owner_user_id=owner.id,
                level=DiagnosticLevel.ERROR,
                component=DiagnosticComponent.api,
                event_code="API_UNHANDLED_EXCEPTION",
                trace_id="trace_1111111111111111",
                metadata_json="{}",
                first_occurred_at=now - timedelta(seconds=10),
                last_occurred_at=now - timedelta(seconds=10),
                occurrence_count=1,
                dedup_fingerprint="b" * 64,
                dedup_bucket=now,
                expires_at=now + timedelta(days=1),
            ),
            DiagnosticEvent(
                owner_user_id=owner.id,
                level=DiagnosticLevel.ERROR,
                component=DiagnosticComponent.worker,
                event_code="PROVIDER_REQUEST_FAILED",
                trace_id="trace_2222222222222222",
                metadata_json='{"error_code":"provider_unavailable","http_status_category":"5xx"}',
                first_occurred_at=now - timedelta(seconds=10),
                last_occurred_at=now - timedelta(seconds=10),
                occurrence_count=3,
                dedup_fingerprint="c" * 64,
                dedup_bucket=now,
                expires_at=now + timedelta(days=1),
            ),
            DiagnosticEvent(
                owner_user_id=owner.id,
                level=DiagnosticLevel.WARNING,
                component=DiagnosticComponent.worker,
                event_code="SOURCE_STORAGE_CLEANUP_FAILED",
                trace_id="trace_3333333333333333",
                metadata_json="{}",
                first_occurred_at=now - timedelta(seconds=10),
                last_occurred_at=now - timedelta(seconds=10),
                occurrence_count=1,
                dedup_fingerprint="d" * 64,
                dedup_bucket=now,
                expires_at=now + timedelta(days=1),
            ),
            AuditEvent(
                actor_user_id=owner.id,
                subject_user_id=owner.id,
                event_type="transcript_maintenance.failed",
                outcome="failed",
                metadata_json="{}",
                created_at=now - timedelta(seconds=10),
            ),
            AuditEvent(
                actor_user_id=owner.id,
                subject_user_id=owner.id,
                event_type="ops.postgres_backup",
                outcome="failed",
                metadata_json="{}",
                created_at=now - timedelta(seconds=5),
            ),
        ]
    )
    db.flush()

    alert_settings = settings()
    alert_settings.alert_storage_limit_bytes = 1000
    observations = {
        row.incident_kind: row
        for row in collect_rule_observations(
            db,
            owner_user_id=owner.id,
            settings=alert_settings,
            now=now,
        )
    }
    assert set(observations) == {
        "critical_error",
        "stuck_queue",
        "provider_unavailable",
        "maintenance_failure",
        "backup_failure",
        "storage_limit",
        "api_limit",
    }
    assert all(row.firing for row in observations.values())
    assert observations["provider_unavailable"].evidence_count == 3
    assert observations["maintenance_failure"].evidence_count == 2
    assert observations["storage_limit"].evidence_count == 900
    assert observations["api_limit"].evidence_count == 90
    db.close()
    engine.dispose()


def test_acknowledgement_is_owner_scoped_and_suppresses_pending_delivery():
    engine, _factory, db, owner = database()
    other = User(email="other@example.com", status=UserStatus.active)
    db.add(other)
    db.flush()
    incident = apply_rule_observation(
        db,
        owner_user_id=owner.id,
        observation=RuleObservation(
            "critical_error", True, "critical", "critical_errors", 1
        ),
        settings=settings(),
    )
    assert incident is not None
    assert acknowledge_incident(
        db, owner_user_id=other.id, incident_id=incident.id
    ) is None
    acknowledged = acknowledge_incident(
        db, owner_user_id=owner.id, incident_id=incident.id
    )
    assert acknowledged is not None and acknowledged.status == "acknowledged"
    assert db.query(OperationalAlertDelivery).one().state == "suppressed"
    db.close()
    engine.dispose()


def test_reopened_incident_honors_cooldown_before_new_delivery():
    engine, _factory, db, owner = database()
    now = datetime(2026, 9, 1, 12, 0, 0)
    firing = RuleObservation("critical_error", True, "critical", "critical_errors", 1)
    recovered = RuleObservation("critical_error", False, "critical", "critical_errors")
    incident = apply_rule_observation(
        db, owner_user_id=owner.id, observation=firing, settings=settings(), now=now
    )
    apply_rule_observation(
        db,
        owner_user_id=owner.id,
        observation=recovered,
        settings=settings(),
        now=now + timedelta(seconds=10),
    )
    reopened = apply_rule_observation(
        db,
        owner_user_id=owner.id,
        observation=firing,
        settings=settings(),
        now=now + timedelta(seconds=20),
    )
    assert reopened is not None and reopened.status == "pending"
    assert reopened.lifecycle_generation == 2
    assert db.query(OperationalAlertDelivery).filter_by(
        lifecycle_generation=2, notification_kind="firing"
    ).count() == 0
    apply_rule_observation(
        db,
        owner_user_id=owner.id,
        observation=firing,
        settings=settings(),
        now=now + timedelta(seconds=311),
    )
    assert incident.status == "firing"
    assert db.query(OperationalAlertDelivery).filter_by(
        lifecycle_generation=2, notification_kind="firing"
    ).count() == 1
    db.close()
    engine.dispose()


def test_delivery_claim_is_committed_before_transport_and_result_is_bounded():
    engine, factory, db, owner = database()
    apply_rule_observation(
        db,
        owner_user_id=owner.id,
        observation=RuleObservation(
            "critical_error", True, "critical", "critical_errors", 1
        ),
        settings=settings(telegram=True),
    )
    db.commit()

    def post(_url, *, json, timeout):
        observation_db = factory()
        try:
            row = observation_db.query(OperationalAlertDelivery).one()
            assert row.state == "claimed" and row.attempt_count == 1
        finally:
            observation_db.close()
        assert set(json) == {"chat_id", "text"}
        assert "owner@example.com" not in json["text"]
        assert timeout == 2.0
        return httpx.Response(200)

    assert process_one_delivery(
        session_factory=factory, settings=settings(telegram=True), post=post
    )
    db.expire_all()
    delivery = db.query(OperationalAlertDelivery).one()
    assert delivery.state == "delivered" and delivery.error_code is None

    claim = SimpleNamespace(delivery_id=delivery.id, claim_token="wrong")
    assert not complete_delivery(
        db,
        claim=claim,
        success=False,
        error_code="secret raw provider response",
        settings=settings(telegram=True),
    )
    db.close()
    engine.dispose()


def test_production_telegram_transport_never_logs_token_url(monkeypatch, caplog):
    observed = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, *, timeout):
        observed["request"] = request
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setattr("studio_api.operational_alerts.urlopen", fake_urlopen)
    claim = DeliveryClaim(
        "delivery-id",
        "claim-token",
        "critical_error",
        "critical",
        "critical_errors",
        "firing",
    )
    assert _send_telegram(claim, settings=settings(telegram=True)) == (True, None)
    assert observed["timeout"] == 2.0
    assert observed["request"].method == "POST"
    assert b"unit-test-token-value" not in observed["request"].data
    assert "unit-test-token-value" not in caplog.text


def test_disabled_transport_is_fail_closed_without_claiming_delivery():
    engine, factory, db, owner = database()
    apply_rule_observation(
        db,
        owner_user_id=owner.id,
        observation=RuleObservation(
            "critical_error", True, "critical", "critical_errors", 1
        ),
        settings=settings(),
    )
    db.commit()
    assert not process_one_delivery(session_factory=factory, settings=settings())
    db.expire_all()
    delivery = db.query(OperationalAlertDelivery).one()
    assert delivery.state == "pending" and delivery.attempt_count == 0
    db.close()
    engine.dispose()


def test_transport_rejection_and_timeout_have_bounded_terminal_retry():
    engine, factory, db, owner = database()
    now = datetime(2026, 9, 1, 12, 0, 0)
    alert_settings = settings(telegram=True)
    apply_rule_observation(
        db,
        owner_user_id=owner.id,
        observation=RuleObservation(
            "critical_error", True, "critical", "critical_errors", 1
        ),
        settings=alert_settings,
        now=now,
    )
    db.commit()

    assert process_one_delivery(
        session_factory=factory,
        settings=alert_settings,
        now=now,
        post=lambda *_args, **_kwargs: httpx.Response(503),
    )
    db.expire_all()
    delivery = db.query(OperationalAlertDelivery).one()
    assert delivery.state == "failed"
    assert delivery.attempt_count == 1
    assert delivery.error_code == "transport_rejected"

    def timeout(*_args, **_kwargs):
        raise httpx.ReadTimeout("synthetic timeout")

    assert process_one_delivery(
        session_factory=factory,
        settings=alert_settings,
        now=now + timedelta(seconds=61),
        post=timeout,
    )
    db.expire_all()
    delivery = db.query(OperationalAlertDelivery).one()
    assert delivery.state == "suppressed"
    assert delivery.attempt_count == 2
    assert delivery.error_code == "transport_timeout"
    assert delivery.next_attempt_at is None
    db.close()
    engine.dispose()


def test_expired_final_claim_is_suppressed_instead_of_left_stuck():
    engine, _factory, db, owner = database()
    now = datetime(2026, 9, 1, 12, 0, 0)
    apply_rule_observation(
        db,
        owner_user_id=owner.id,
        observation=RuleObservation(
            "critical_error", True, "critical", "critical_errors", 1
        ),
        settings=settings(telegram=True),
        now=now,
    )
    delivery = db.query(OperationalAlertDelivery).one()
    delivery.state = "claimed"
    delivery.attempt_count = 2
    delivery.claim_token = "a" * 48
    delivery.claim_expires_at = now - timedelta(seconds=1)
    db.flush()

    assert claim_next_delivery(
        db, settings=settings(telegram=True), now=now
    ) is None
    assert delivery.state == "suppressed"
    assert delivery.claim_token is None
    assert delivery.error_code == "delivery_state_changed"
    db.close()
    engine.dispose()


def test_trace_and_outcome_are_persisted_in_append_only_audit_writer():
    engine, _factory, db, owner = database()
    trace = "trace_0123456789abcdef"
    token = set_current_trace_id(trace)
    try:
        audit(
            db,
            "test.rejected",
            actor_user_id=owner.id,
            subject_user_id=owner.id,
            outcome="rejected",
            reason="safe_reason",
        )
        record_postgres_backup_outcome(
            db, owner_user_id=owner.id, succeeded=False
        )
        db.commit()
    finally:
        reset_current_trace_id(token)
    rows = db.query(AuditEvent).all()
    by_event_type = {row.event_type: row for row in rows}
    assert (by_event_type["test.rejected"].outcome, by_event_type["test.rejected"].trace_id) == (
        "rejected",
        trace,
    )
    assert (
        by_event_type["ops.postgres_backup"].outcome,
        by_event_type["ops.postgres_backup"].trace_id,
    ) == ("failed", trace)
    db.close()
    engine.dispose()


def test_operator_canary_is_deduplicated_resolved_and_never_deliverable():
    engine, _factory, db, owner = database()
    now = datetime(2026, 9, 1, 12, 0, 0)
    first = run_observability_canary(
        db,
        owner_user_id=owner.id,
        settings=settings(telegram=True),
        trace_id="trace_4444444444444444",
        now=now,
    )
    db.commit()
    assert first.status == "resolved"
    assert first.lifecycle_generation == 1
    assert first.occurrence_count == 2
    assert {row.state for row in db.query(OperationalAlertDelivery).all()} == {"suppressed"}
    assert {row.notification_kind for row in db.query(OperationalAlertDelivery).all()} == {
        "firing",
        "recovery",
    }

    second = run_observability_canary(
        db,
        owner_user_id=owner.id,
        settings=settings(telegram=True),
        trace_id="trace_5555555555555555",
        now=now + timedelta(seconds=1),
    )
    db.commit()
    assert second.id == first.id
    assert second.status == "resolved"
    assert second.lifecycle_generation == 2
    assert second.occurrence_count == 4
    assert db.query(OperationalIncident).filter_by(incident_kind="operator_canary").count() == 1
    assert db.query(OperationalAlertDelivery).count() == 4
    assert {row.state for row in db.query(OperationalAlertDelivery).all()} == {"suppressed"}
    audits = db.query(AuditEvent).filter_by(event_type="ops.observability_canary").all()
    assert [row.outcome for row in audits] == ["success", "success"]
    assert [row.trace_id for row in audits] == [
        "trace_4444444444444444",
        "trace_5555555555555555",
    ]
    db.close()
    engine.dispose()


def test_operator_canary_cli_emits_only_safe_terminal_evidence(monkeypatch, capsys):
    engine, factory, db, owner = database()
    owner_id = owner.id
    db.close()
    monkeypatch.setattr(cli, "SessionLocal", factory)
    monkeypatch.setattr(cli, "get_settings", lambda: settings(telegram=True))
    monkeypatch.setattr(cli, "new_trace_id", lambda: "trace_8888888888888888")
    monkeypatch.setattr(
        sys,
        "argv",
        ["studio-api", "run-observability-alert-canary", owner_id],
    )

    assert cli.main() == 0
    output = capsys.readouterr().out.strip()
    assert output == (
        "OBSERVABILITY_ALERT_CANARY_OK status=resolved generation=1 "
        "occurrences=2 trace_id=trace_8888888888888888"
    )
    assert "owner@example.com" not in output

    verification_db = factory()
    try:
        assert verification_db.query(OperationalIncident).one().status == "resolved"
        assert {row.state for row in verification_db.query(OperationalAlertDelivery)} == {
            "suppressed"
        }
    finally:
        verification_db.close()
        engine.dispose()
