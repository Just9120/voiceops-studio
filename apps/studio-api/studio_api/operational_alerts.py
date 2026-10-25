from __future__ import annotations

import json
import logging
import secrets
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit import audit
from .models import (
    AuditEvent,
    DiagnosticEvent,
    JobStatus,
    OperationalAlertDelivery,
    OperationalIncident,
    ProviderAccountSnapshot,
    Source,
    SourceType,
    TranscriptionJob,
    User,
    UserStatus,
)
from .trace_context import valid_trace_id


LOGGER = logging.getLogger("studio_api.operational_alerts")
ACTIVE_INCIDENT_STATUSES = frozenset({"pending", "firing", "acknowledged"})
CRITICAL_EVENT_CODES = frozenset(
    {"API_UNHANDLED_EXCEPTION", "LEASE_HEARTBEAT_FAILED", "AUDIO_PREPARATION_FAILED"}
)
PROVIDER_FAILURE_CODES = frozenset({"provider_unavailable", "provider_timeout"})
SUMMARY_CODES = frozenset(
    {
        "critical_errors",
        "queue_stuck",
        "provider_unavailable",
        "maintenance_failure",
        "backup_failure",
        "storage_limit_near",
        "api_limit_near",
        "operator_canary_ok",
    }
)
INCIDENT_KINDS = frozenset(
    {
        "critical_error",
        "stuck_queue",
        "provider_unavailable",
        "maintenance_failure",
        "backup_failure",
        "storage_limit",
        "api_limit",
        "operator_canary",
    }
)
SAFE_DELIVERY_ERRORS = frozenset(
    {
        "configuration_unavailable",
        "transport_timeout",
        "transport_unavailable",
        "transport_rejected",
        "delivery_state_changed",
    }
)


def _utc_naive(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _metadata(event: DiagnosticEvent) -> dict[str, object]:
    try:
        value = json.loads(event.metadata_json or "{}")
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


@dataclass(frozen=True)
class RuleObservation:
    incident_kind: str
    firing: bool
    severity: str
    summary_code: str
    evidence_count: int = 0
    trace_id: str | None = None

    def __post_init__(self):
        if self.incident_kind not in INCIDENT_KINDS:
            raise ValueError("unsupported incident kind")
        if self.severity not in {"warning", "critical"}:
            raise ValueError("unsupported incident severity")
        if self.summary_code not in SUMMARY_CODES:
            raise ValueError("unsupported incident summary")
        if self.evidence_count < 0:
            raise ValueError("invalid evidence count")
        if self.trace_id is not None and not valid_trace_id(self.trace_id):
            raise ValueError("invalid incident trace id")


def collect_rule_observations(
    db: Session,
    *,
    owner_user_id: str,
    settings,
    now: datetime | None = None,
) -> list[RuleObservation]:
    now_dt = _utc_naive(now)
    window_start = now_dt - timedelta(seconds=settings.alert_signal_window_seconds)
    recent_events = (
        db.query(DiagnosticEvent)
        .filter(
            DiagnosticEvent.owner_user_id == owner_user_id,
            DiagnosticEvent.last_occurred_at >= window_start,
            DiagnosticEvent.expires_at > now_dt,
        )
        .order_by(DiagnosticEvent.last_occurred_at.desc(), DiagnosticEvent.id.desc())
        .limit(500)
        .all()
    )

    critical_events = [event for event in recent_events if event.event_code in CRITICAL_EVENT_CODES]
    provider_events = []
    for event in recent_events:
        if event.event_code != "PROVIDER_REQUEST_FAILED":
            continue
        metadata = _metadata(event)
        if (
            metadata.get("error_code") in PROVIDER_FAILURE_CODES
            or metadata.get("http_status_category") == "5xx"
        ):
            provider_events.append(event)
    maintenance_events = [
        event for event in recent_events if event.event_code == "SOURCE_STORAGE_CLEANUP_FAILED"
    ]
    maintenance_audit_count = (
        db.query(func.count(AuditEvent.id))
        .filter(
            AuditEvent.subject_user_id == owner_user_id,
            AuditEvent.event_type == "transcript_maintenance.failed",
            AuditEvent.outcome == "failed",
            AuditEvent.created_at >= window_start,
        )
        .scalar()
        or 0
    )

    stuck_before = now_dt - timedelta(seconds=settings.alert_stuck_queue_seconds)
    stuck_jobs = (
        db.query(TranscriptionJob)
        .filter(
            TranscriptionJob.owner_user_id == owner_user_id,
            or_(
                (TranscriptionJob.status == JobStatus.queued)
                & (TranscriptionJob.created_at <= stuck_before),
                (TranscriptionJob.status == JobStatus.processing)
                & (TranscriptionJob.lease_expires_at.is_not(None))
                & (TranscriptionJob.lease_expires_at <= now_dt),
            ),
        )
        .order_by(TranscriptionJob.created_at.asc(), TranscriptionJob.id.asc())
        .limit(100)
        .all()
    )

    latest_backup = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.subject_user_id == owner_user_id,
            AuditEvent.event_type == "ops.postgres_backup",
        )
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .first()
    )
    # Regular backups and their schedule/target verification belong to Cloudkeep.
    # Its health cannot be inferred from the age of a Studio migration snapshot.
    # Retain alerts for an actual reported failure of the protected Studio backup
    # operation; absence or age is neither external failure nor external success.
    backup_unhealthy = bool(latest_backup is not None and latest_backup.outcome == "failed")

    storage_firing = False
    storage_evidence = 0
    if settings.alert_storage_limit_bytes is not None:
        storage_evidence = int(
            db.query(func.coalesce(func.sum(Source.size_bytes), 0))
            .filter(
                Source.source_type == SourceType.local_upload,
                Source.deleted_at.is_(None),
                Source.project.has(owner_user_id=owner_user_id),
            )
            .scalar()
            or 0
        )
        threshold = (
            int(settings.alert_storage_limit_bytes)
            * (100 - int(settings.alert_limit_remaining_percent))
            // 100
        )
        storage_firing = storage_evidence >= threshold

    snapshot = (
        db.query(ProviderAccountSnapshot)
        .filter(ProviderAccountSnapshot.owner_user_id == owner_user_id)
        .order_by(ProviderAccountSnapshot.updated_at.desc(), ProviderAccountSnapshot.id.desc())
        .first()
    )
    api_firing = False
    api_remaining_percent = 100
    if snapshot and snapshot.period_limit and snapshot.period_remaining is not None:
        api_remaining_percent = max(
            0,
            min(100, int(snapshot.period_remaining) * 100 // int(snapshot.period_limit)),
        )
        api_firing = api_remaining_percent <= int(settings.alert_limit_remaining_percent)

    latest_trace = lambda rows: next(
        (row.trace_id for row in rows if valid_trace_id(row.trace_id)),
        None,
    )
    provider_count = sum(int(event.occurrence_count or 1) for event in provider_events)
    maintenance_count = sum(int(event.occurrence_count or 1) for event in maintenance_events) + int(maintenance_audit_count)
    critical_count = sum(int(event.occurrence_count or 1) for event in critical_events)
    return [
        RuleObservation("critical_error", critical_count > 0, "critical", "critical_errors", critical_count, latest_trace(critical_events)),
        RuleObservation("stuck_queue", bool(stuck_jobs), "critical", "queue_stuck", len(stuck_jobs), next((job.trace_id for job in stuck_jobs if valid_trace_id(job.trace_id)), None)),
        RuleObservation("provider_unavailable", provider_count >= int(settings.alert_provider_failure_threshold), "warning", "provider_unavailable", provider_count, latest_trace(provider_events)),
        RuleObservation("maintenance_failure", maintenance_count > 0, "warning", "maintenance_failure", maintenance_count, latest_trace(maintenance_events)),
        RuleObservation("backup_failure", backup_unhealthy, "critical", "backup_failure", int(backup_unhealthy), latest_backup.trace_id if latest_backup and valid_trace_id(latest_backup.trace_id) else None),
        RuleObservation("storage_limit", storage_firing, "warning", "storage_limit_near", storage_evidence),
        RuleObservation("api_limit", api_firing, "warning", "api_limit_near", 100 - api_remaining_percent),
    ]


def _ensure_delivery(
    db: Session,
    *,
    incident: OperationalIncident,
    notification_kind: str,
    now: datetime,
) -> None:
    exists = (
        db.query(OperationalAlertDelivery.id)
        .filter(
            OperationalAlertDelivery.incident_id == incident.id,
            OperationalAlertDelivery.lifecycle_generation == incident.lifecycle_generation,
            OperationalAlertDelivery.notification_kind == notification_kind,
            OperationalAlertDelivery.channel == "telegram",
        )
        .first()
    )
    if exists:
        return
    db.add(
        OperationalAlertDelivery(
            owner_user_id=incident.owner_user_id,
            incident_id=incident.id,
            lifecycle_generation=incident.lifecycle_generation,
            notification_kind=notification_kind,
            channel="telegram",
            state="pending",
            next_attempt_at=now,
            created_at=now,
            updated_at=now,
        )
    )


def apply_rule_observation(
    db: Session,
    *,
    owner_user_id: str,
    observation: RuleObservation,
    settings,
    now: datetime | None = None,
) -> OperationalIncident | None:
    now_dt = _utc_naive(now)
    incident = db.execute(
        select(OperationalIncident)
        .where(
            OperationalIncident.owner_user_id == owner_user_id,
            OperationalIncident.incident_kind == observation.incident_kind,
        )
        .with_for_update()
    ).scalar_one_or_none()

    if not observation.firing:
        if incident is None or incident.status == "resolved":
            return incident
        previous_status = incident.status
        incident.status = "resolved"
        incident.resolved_at = now_dt
        incident.last_transition_at = now_dt
        incident.updated_at = now_dt
        if previous_status in {"firing", "acknowledged"}:
            _ensure_delivery(db, incident=incident, notification_kind="recovery", now=now_dt)
        return incident

    target_status = "firing" if observation.severity == "critical" else "pending"
    if incident is None:
        incident = OperationalIncident(
            owner_user_id=owner_user_id,
            incident_kind=observation.incident_kind,
            severity=observation.severity,
            status=target_status,
            summary_code=observation.summary_code,
            trace_id=observation.trace_id,
            lifecycle_generation=1,
            occurrence_count=1,
            evidence_count=observation.evidence_count,
            first_detected_at=now_dt,
            last_detected_at=now_dt,
            last_transition_at=now_dt,
            cooldown_until=(
                now_dt + timedelta(seconds=settings.alert_incident_cooldown_seconds)
                if target_status == "firing"
                else None
            ),
            created_at=now_dt,
            updated_at=now_dt,
        )
        db.add(incident)
        db.flush()
        if incident.status == "firing":
            _ensure_delivery(db, incident=incident, notification_kind="firing", now=now_dt)
        return incident

    incident.occurrence_count = int(incident.occurrence_count or 0) + 1
    incident.evidence_count = observation.evidence_count
    incident.last_detected_at = now_dt
    incident.severity = observation.severity
    incident.summary_code = observation.summary_code
    incident.trace_id = observation.trace_id
    incident.updated_at = now_dt
    if incident.status == "resolved":
        incident.lifecycle_generation = int(incident.lifecycle_generation or 0) + 1
        still_cooling_down = bool(incident.cooldown_until and incident.cooldown_until > now_dt)
        incident.status = "pending" if still_cooling_down else target_status
        incident.first_detected_at = now_dt
        incident.last_transition_at = now_dt
        incident.acknowledged_at = None
        incident.resolved_at = None
        if not still_cooling_down and incident.status == "firing":
            incident.cooldown_until = now_dt + timedelta(
                seconds=settings.alert_incident_cooldown_seconds
            )
    elif incident.status == "pending":
        if incident.cooldown_until is None or incident.cooldown_until <= now_dt:
            incident.status = "firing"
            incident.last_transition_at = now_dt
            incident.cooldown_until = now_dt + timedelta(
                seconds=settings.alert_incident_cooldown_seconds
            )
    if incident.status == "firing":
        _ensure_delivery(db, incident=incident, notification_kind="firing", now=now_dt)
    return incident


def evaluate_owner_incidents(
    db: Session,
    *,
    owner_user_id: str,
    settings,
    now: datetime | None = None,
) -> list[OperationalIncident]:
    observations = collect_rule_observations(
        db,
        owner_user_id=owner_user_id,
        settings=settings,
        now=now,
    )
    rows = []
    for observation in observations:
        row = apply_rule_observation(
            db,
            owner_user_id=owner_user_id,
            observation=observation,
            settings=settings,
            now=now,
        )
        if row is not None:
            rows.append(row)
    return rows


def evaluate_all_owner_incidents(*, session_factory, settings, now: datetime | None = None) -> int:
    db = session_factory()
    try:
        owner_ids = [
            row[0]
            for row in db.query(User.id)
            .filter(User.status == UserStatus.active)
            .order_by(User.id.asc())
            .limit(100)
            .all()
        ]
        for owner_user_id in owner_ids:
            evaluate_owner_incidents(
                db,
                owner_user_id=owner_user_id,
                settings=settings,
                now=now,
            )
        db.commit()
        return len(owner_ids)
    except IntegrityError:
        db.rollback()
        LOGGER.warning("operational_incident_concurrent_evaluation")
        return 0
    except Exception:
        db.rollback()
        LOGGER.warning("operational_incident_evaluation_failed")
        return 0
    finally:
        db.close()


def acknowledge_incident(
    db: Session,
    *,
    owner_user_id: str,
    incident_id: str,
    now: datetime | None = None,
) -> OperationalIncident | None:
    incident = db.execute(
        select(OperationalIncident)
        .where(
            OperationalIncident.id == incident_id,
            OperationalIncident.owner_user_id == owner_user_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if incident is None:
        return None
    if incident.status in {"pending", "firing"}:
        now_dt = _utc_naive(now)
        incident.status = "acknowledged"
        incident.acknowledged_at = now_dt
        incident.last_transition_at = now_dt
        incident.updated_at = now_dt
        db.query(OperationalAlertDelivery).filter(
            OperationalAlertDelivery.incident_id == incident.id,
            OperationalAlertDelivery.lifecycle_generation == incident.lifecycle_generation,
            OperationalAlertDelivery.notification_kind == "firing",
            OperationalAlertDelivery.state.in_(["pending", "failed"]),
        ).update({"state": "suppressed", "updated_at": now_dt}, synchronize_session=False)
    return incident


def run_observability_canary(
    db: Session,
    *,
    owner_user_id: str,
    settings,
    trace_id: str,
    now: datetime | None = None,
) -> OperationalIncident:
    """Exercise incident lifecycle without exposing a delivery to the worker.

    The dedicated incident kind cannot collide with a real signal. All lifecycle
    transitions and delivery suppression happen in one database transaction, so
    another worker can never claim the synthetic firing/recovery notifications.
    """
    if not valid_trace_id(trace_id):
        raise ValueError("invalid canary trace id")
    owner = db.get(User, owner_user_id)
    if owner is None or owner.status != UserStatus.active:
        raise ValueError("active alert owner is required")

    now_dt = _utc_naive(now)
    existing = db.execute(
        select(OperationalIncident)
        .where(
            OperationalIncident.owner_user_id == owner_user_id,
            OperationalIncident.incident_kind == "operator_canary",
        )
        .with_for_update()
    ).scalar_one_or_none()
    if existing is not None:
        existing.cooldown_until = None

    firing = RuleObservation(
        "operator_canary",
        True,
        "warning",
        "operator_canary_ok",
        evidence_count=1,
        trace_id=trace_id,
    )
    recovered = RuleObservation(
        "operator_canary",
        False,
        "warning",
        "operator_canary_ok",
        trace_id=trace_id,
    )
    incident = apply_rule_observation(
        db,
        owner_user_id=owner_user_id,
        observation=firing,
        settings=settings,
        now=now_dt,
    )
    incident = apply_rule_observation(
        db,
        owner_user_id=owner_user_id,
        observation=firing,
        settings=settings,
        now=now_dt + timedelta(microseconds=1),
    )
    if incident is None or incident.status != "firing":
        raise RuntimeError("canary did not reach firing state")
    incident = apply_rule_observation(
        db,
        owner_user_id=owner_user_id,
        observation=recovered,
        settings=settings,
        now=now_dt + timedelta(microseconds=2),
    )
    if incident is None or incident.status != "resolved":
        raise RuntimeError("canary did not reach resolved state")

    db.query(OperationalAlertDelivery).filter(
        OperationalAlertDelivery.incident_id == incident.id,
        OperationalAlertDelivery.lifecycle_generation == incident.lifecycle_generation,
    ).update(
        {
            "state": "suppressed",
            "claim_token": None,
            "claim_expires_at": None,
            "next_attempt_at": None,
            "error_code": None,
            "updated_at": now_dt + timedelta(microseconds=3),
        },
        synchronize_session=False,
    )
    audit(
        db,
        "ops.observability_canary",
        actor_user_id=owner_user_id,
        subject_user_id=owner_user_id,
        outcome="success",
        trace_id=trace_id,
    )
    db.flush()
    return incident


def incident_payload(
    incident: OperationalIncident,
    *,
    delivery: OperationalAlertDelivery | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": incident.id,
        "kind": incident.incident_kind,
        "severity": incident.severity,
        "status": incident.status,
        "summary_code": incident.summary_code,
        "occurrence_count": int(incident.occurrence_count),
        "evidence_count": int(incident.evidence_count),
        "first_detected_at": incident.first_detected_at.isoformat(),
        "last_detected_at": incident.last_detected_at.isoformat(),
        "last_transition_at": incident.last_transition_at.isoformat(),
        "delivery": {
            "channel": delivery.channel if delivery else "telegram",
            "state": delivery.state if delivery else "not_attempted",
            "attempt_count": int(delivery.attempt_count) if delivery else 0,
            "notification_kind": delivery.notification_kind if delivery else "not_applicable",
        },
    }
    if valid_trace_id(incident.trace_id):
        payload["trace_id"] = incident.trace_id
    return payload


@dataclass(frozen=True)
class DeliveryClaim:
    delivery_id: str
    claim_token: str
    incident_kind: str
    severity: str
    summary_code: str
    notification_kind: str


def claim_next_delivery(
    db: Session,
    *,
    settings,
    now: datetime | None = None,
) -> DeliveryClaim | None:
    if not settings.telegram_alerts_configured():
        return None
    now_dt = _utc_naive(now)
    row = db.execute(
        select(OperationalAlertDelivery, OperationalIncident)
        .join(OperationalIncident, OperationalIncident.id == OperationalAlertDelivery.incident_id)
        .where(
            or_(
                (OperationalAlertDelivery.state.in_(["pending", "failed"]))
                & (OperationalAlertDelivery.attempt_count < settings.alert_delivery_max_attempts)
                & or_(
                    OperationalAlertDelivery.next_attempt_at.is_(None),
                    OperationalAlertDelivery.next_attempt_at <= now_dt,
                ),
                (OperationalAlertDelivery.state == "claimed")
                & (OperationalAlertDelivery.claim_expires_at <= now_dt),
            ),
        )
        .order_by(OperationalAlertDelivery.created_at.asc(), OperationalAlertDelivery.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if row is None:
        return None
    delivery, incident = row
    if (
        delivery.state == "claimed"
        and delivery.attempt_count >= settings.alert_delivery_max_attempts
    ):
        delivery.state = "suppressed"
        delivery.claim_token = None
        delivery.claim_expires_at = None
        delivery.next_attempt_at = None
        delivery.error_code = "delivery_state_changed"
        delivery.updated_at = now_dt
        return None
    valid_lifecycle = (
        delivery.lifecycle_generation == incident.lifecycle_generation
        and (
            (delivery.notification_kind == "firing" and incident.status == "firing")
            or (delivery.notification_kind == "recovery" and incident.status == "resolved")
        )
    )
    if not valid_lifecycle:
        delivery.state = "suppressed"
        delivery.updated_at = now_dt
        return None
    token = secrets.token_hex(24)
    delivery.state = "claimed"
    delivery.claim_token = token
    delivery.claim_expires_at = now_dt + timedelta(seconds=60)
    delivery.last_attempt_at = now_dt
    delivery.attempt_count = int(delivery.attempt_count or 0) + 1
    delivery.updated_at = now_dt
    return DeliveryClaim(
        delivery.id,
        token,
        incident.incident_kind,
        incident.severity,
        incident.summary_code,
        delivery.notification_kind,
    )


def _telegram_text(claim: DeliveryClaim) -> str:
    summary = {
        "critical_errors": "критические ошибки Studio",
        "queue_stuck": "очередь обработки не продвигается",
        "provider_unavailable": "STT provider временно недоступен",
        "maintenance_failure": "ошибка обслуживания или очистки",
        "backup_failure": "защищённое резервное копирование PostgreSQL завершилось ошибкой",
        "storage_limit_near": "временное хранилище близко к лимиту",
        "api_limit_near": "API credits близки к лимиту",
        "operator_canary_ok": "проверка контура предупреждений завершена",
    }[claim.summary_code]
    state = "ВОССТАНОВЛЕНО" if claim.notification_kind == "recovery" else "ТРЕБУЕТ ВНИМАНИЯ"
    return f"VoiceOps Studio · {state}\n{summary}\nУровень: {claim.severity}. Подробности: Настройки → Для поддержки."


def _send_telegram(
    claim: DeliveryClaim,
    *,
    settings,
    post: Callable[..., httpx.Response] | None = None,
) -> tuple[bool, str | None]:
    try:
        token, chat_id = settings.telegram_alert_credentials()
    except Exception:
        return False, "configuration_unavailable"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": _telegram_text(claim)}
    timeout = float(settings.alert_telegram_timeout_seconds)
    if post is not None:
        try:
            response = post(url, json=payload, timeout=timeout)
        except httpx.TimeoutException:
            return False, "transport_timeout"
        except (httpx.HTTPError, OSError):
            return False, "transport_unavailable"
        return (True, None) if 200 <= response.status_code < 300 else (False, "transport_rejected")

    # httpx logs complete request URLs at INFO. Telegram embeds the bot token in
    # that URL, so the production transport deliberately uses urllib and never
    # logs or returns the URL, exception, or response body.
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS origin
            status_code = int(response.status)
    except HTTPError:
        return False, "transport_rejected"
    except (TimeoutError, socket.timeout):
        return False, "transport_timeout"
    except URLError as exc:
        return (
            (False, "transport_timeout")
            if isinstance(exc.reason, (TimeoutError, socket.timeout))
            else (False, "transport_unavailable")
        )
    except OSError:
        return False, "transport_unavailable"
    return (True, None) if 200 <= status_code < 300 else (False, "transport_rejected")


def complete_delivery(
    db: Session,
    *,
    claim: DeliveryClaim,
    success: bool,
    error_code: str | None,
    settings,
    now: datetime | None = None,
) -> bool:
    now_dt = _utc_naive(now)
    row = db.execute(
        select(OperationalAlertDelivery)
        .where(OperationalAlertDelivery.id == claim.delivery_id)
        .with_for_update()
    ).scalar_one_or_none()
    if row is None or row.state != "claimed" or row.claim_token != claim.claim_token:
        return False
    row.claim_token = None
    row.claim_expires_at = None
    row.updated_at = now_dt
    if success:
        row.state = "delivered"
        row.delivered_at = now_dt
        row.error_code = None
        row.next_attempt_at = None
    else:
        safe_error = error_code if error_code in SAFE_DELIVERY_ERRORS else "transport_unavailable"
        row.error_code = safe_error
        if row.attempt_count >= settings.alert_delivery_max_attempts:
            row.state = "suppressed"
            row.next_attempt_at = None
        else:
            row.state = "failed"
            row.next_attempt_at = now_dt + timedelta(seconds=settings.alert_delivery_retry_seconds)
    return True


def process_one_delivery(
    *,
    session_factory,
    settings,
    now: datetime | None = None,
    post: Callable[..., httpx.Response] | None = None,
) -> bool:
    claim_db = session_factory()
    try:
        claim = claim_next_delivery(claim_db, settings=settings, now=now)
        claim_db.commit()
    except Exception:
        claim_db.rollback()
        LOGGER.warning("operational_alert_claim_failed")
        return False
    finally:
        claim_db.close()
    if claim is None:
        return False

    success, error_code = _send_telegram(claim, settings=settings, post=post)
    finish_db = session_factory()
    try:
        completed = complete_delivery(
            finish_db,
            claim=claim,
            success=success,
            error_code=error_code,
            settings=settings,
            now=now,
        )
        finish_db.commit()
        return completed
    except Exception:
        finish_db.rollback()
        LOGGER.warning("operational_alert_completion_failed")
        return False
    finally:
        finish_db.close()


def record_postgres_backup_outcome(
    db: Session,
    *,
    owner_user_id: str,
    succeeded: bool,
) -> None:
    owner = db.get(User, owner_user_id)
    if owner is None or owner.status != UserStatus.active:
        raise ValueError("active alert owner is required")
    audit(
        db,
        "ops.postgres_backup",
        actor_user_id=owner_user_id,
        subject_user_id=owner_user_id,
        outcome="success" if succeeded else "failed",
    )
