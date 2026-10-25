from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import smtplib
import socket
import ssl
from types import SimpleNamespace
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import (
    JobNotificationDelivery,
    JobStatus,
    TranscriptionJob,
    User,
    UserStatus,
    UserNotificationPreference,
    WebPushSubscription,
)
from .security import decrypt, encrypt, master_key_from_b64


LOGGER = logging.getLogger("studio_api.job_notifications")
TERMINAL_NOTIFICATION_STATUSES = frozenset({JobStatus.completed, JobStatus.failed})
SAFE_DELIVERY_ERRORS = frozenset(
    {
        "configuration_unavailable",
        "destination_unavailable",
        "subscription_gone",
        "transport_timeout",
        "transport_unavailable",
        "transport_rejected",
        "delivery_state_changed",
    }
)
_B64URL = re.compile(r"^[A-Za-z0-9_-]+$")
_PUSH_HOST_SUFFIXES = (
    ".googleapis.com",
    ".push.services.mozilla.com",
    ".push.apple.com",
    ".notify.windows.com",
)


def _utc_naive(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is not None:
        current = current.astimezone(timezone.utc).replace(tzinfo=None)
    return current


def notification_preference(db: Session, *, owner_user_id: str, now: datetime | None = None) -> UserNotificationPreference:
    row = db.get(UserNotificationPreference, owner_user_id)
    if row is None:
        current = _utc_naive(now)
        row = UserNotificationPreference(user_id=owner_user_id, created_at=current, updated_at=current)
        db.add(row)
        db.flush()
    return row


def web_push_subscription_aad(owner_user_id: str, subscription_id: str) -> bytes:
    return f"studio:web-push:{owner_user_id}:{subscription_id}".encode("utf-8")


def _decode_b64url(value: str, *, minimum: int, maximum: int) -> bytes:
    if not (minimum <= len(value) <= maximum) or not _B64URL.fullmatch(value):
        raise ValueError("invalid_web_push_key")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid_web_push_key") from exc
    if not decoded:
        raise ValueError("invalid_web_push_key")
    return decoded


def normalize_web_push_subscription(*, endpoint: str, p256dh: str, auth: str) -> dict:
    endpoint_value = endpoint.strip() if isinstance(endpoint, str) else ""
    if not (20 <= len(endpoint_value) <= 2048):
        raise ValueError("invalid_web_push_endpoint")
    parsed = urlparse(endpoint_value)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not any(host == suffix[1:] or host.endswith(suffix) for suffix in _PUSH_HOST_SUFFIXES)
    ):
        raise ValueError("invalid_web_push_endpoint")
    _decode_b64url(p256dh, minimum=40, maximum=256)
    _decode_b64url(auth, minimum=12, maximum=64)
    return {"endpoint": endpoint_value, "keys": {"p256dh": p256dh, "auth": auth}}


def endpoint_fingerprint(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


def upsert_web_push_subscription(
    db: Session,
    *,
    owner_user_id: str,
    endpoint: str,
    p256dh: str,
    auth: str,
    master_key_b64: str,
    key_id: str,
    now: datetime | None = None,
) -> WebPushSubscription:
    payload = normalize_web_push_subscription(endpoint=endpoint, p256dh=p256dh, auth=auth)
    current = _utc_naive(now)
    fingerprint = endpoint_fingerprint(payload["endpoint"])
    row = db.execute(
        select(WebPushSubscription)
        .where(
            WebPushSubscription.owner_user_id == owner_user_id,
            WebPushSubscription.endpoint_fingerprint == fingerprint,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        row = WebPushSubscription(
            owner_user_id=owner_user_id,
            endpoint_fingerprint=fingerprint,
            ciphertext=b"pending",
            nonce=b"pending",
            key_id=key_id,
            created_at=current,
            updated_at=current,
        )
        db.add(row)
        db.flush()
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    ciphertext, nonce = encrypt(
        raw,
        master_key_from_b64(master_key_b64),
        web_push_subscription_aad(owner_user_id, row.id),
    )
    row.ciphertext = ciphertext
    row.nonce = nonce
    row.key_id = key_id
    row.revoked_at = None
    row.updated_at = current
    db.flush()
    return row


def revoke_web_push_subscription(
    db: Session,
    *,
    owner_user_id: str,
    subscription_id: str,
    now: datetime | None = None,
) -> bool:
    row = db.execute(
        select(WebPushSubscription)
        .where(
            WebPushSubscription.id == subscription_id,
            WebPushSubscription.owner_user_id == owner_user_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        return False
    row.revoked_at = row.revoked_at or _utc_naive(now)
    row.updated_at = _utc_naive(now)
    db.flush()
    return True


def _delivery_exists(
    db: Session,
    *,
    job: TranscriptionJob,
    terminal_status: str,
    channel: str,
    destination_id: str,
) -> bool:
    return db.execute(
        select(JobNotificationDelivery.id).where(
            JobNotificationDelivery.job_id == job.id,
            JobNotificationDelivery.terminal_status == terminal_status,
            JobNotificationDelivery.attempt_number == int(job.attempt_count or 0),
            JobNotificationDelivery.channel == channel,
            JobNotificationDelivery.destination_id == destination_id,
        )
    ).first() is not None


def ensure_terminal_notification_intents(
    db: Session,
    *,
    job: TranscriptionJob,
    now: datetime | None = None,
) -> int:
    if job.status not in TERMINAL_NOTIFICATION_STATUSES or int(job.attempt_count or 0) < 1:
        return 0
    preference = db.get(UserNotificationPreference, job.owner_user_id)
    if preference is None:
        return 0
    current = _utc_naive(now)
    terminal_status = job.status.value
    destinations: list[tuple[str, str]] = []
    # Retired email/push preferences remain readable for rolling compatibility,
    # but can never create a new task notification.
    if preference.telegram_enabled:
        destinations.append(("telegram", "configured"))
    created = 0
    for channel, destination_id in destinations:
        if _delivery_exists(
            db,
            job=job,
            terminal_status=terminal_status,
            channel=channel,
            destination_id=destination_id,
        ):
            continue
        db.add(
            JobNotificationDelivery(
                owner_user_id=job.owner_user_id,
                job_id=job.id,
                terminal_status=terminal_status,
                attempt_number=int(job.attempt_count or 0),
                channel=channel,
                destination_id=destination_id,
                state="pending",
                created_at=current,
                updated_at=current,
            )
        )
        created += 1
    if created:
        db.flush()
    return created


def suppress_obsolete_job_notification_intents(
    db: Session,
    *,
    job_id: str,
    now: datetime | None = None,
) -> int:
    current = _utc_naive(now)
    rows = db.execute(
        select(JobNotificationDelivery).where(
            JobNotificationDelivery.job_id == job_id,
            JobNotificationDelivery.state.in_(["pending", "failed", "claimed"]),
        )
    ).scalars().all()
    for row in rows:
        row.state = "suppressed"
        row.error_code = "delivery_state_changed"
        row.claim_token = None
        row.claim_expires_at = None
        row.next_attempt_at = None
        row.updated_at = current
    if rows:
        db.flush()
    return len(rows)


def _configured_channels(settings) -> tuple[str, ...]:
    if (getattr(settings, "job_telegram_owner_user_id", None)
            and getattr(settings, "job_telegram_configured", lambda: False)()):
        return ("telegram",)
    return ()


def telegram_owner_allowed(settings, owner_user_id: str) -> bool:
    return (getattr(settings, "job_telegram_owner_user_id", None) == owner_user_id
            and "telegram" in _configured_channels(settings))


def _channel_enabled(preference: UserNotificationPreference, channel: str) -> bool:
    return bool(getattr(preference, f"{channel}_enabled", False))


@dataclass(frozen=True)
class JobNotificationClaim:
    delivery_id: str
    claim_token: str
    owner_user_id: str
    job_id: str
    terminal_status: str
    attempt_number: int
    channel: str
    destination_id: str
    recipient_email: str | None = None
    subscription_ciphertext: bytes | None = None
    subscription_nonce: bytes | None = None


def claim_next_job_notification(
    db: Session,
    *,
    settings,
    now: datetime | None = None,
) -> JobNotificationClaim | None:
    channels = _configured_channels(settings)
    if not channels:
        return None
    current = _utc_naive(now)
    while True:
        row = db.execute(
            select(JobNotificationDelivery)
            .where(
                JobNotificationDelivery.channel.in_(channels),
                or_(
                    (
                        JobNotificationDelivery.state.in_(["pending", "failed"])
                        & (JobNotificationDelivery.attempt_count < settings.job_notification_max_attempts)
                        & or_(
                            JobNotificationDelivery.next_attempt_at.is_(None),
                            JobNotificationDelivery.next_attempt_at <= current,
                        )
                    ),
                    (
                        JobNotificationDelivery.state == "claimed"
                    )
                    & (JobNotificationDelivery.claim_expires_at <= current),
                ),
            )
            .order_by(JobNotificationDelivery.created_at, JobNotificationDelivery.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if row is None:
            return None
        job = db.get(TranscriptionJob, row.job_id)
        preference = db.get(UserNotificationPreference, row.owner_user_id)
        user = db.get(User, row.owner_user_id)
        valid = bool(
            job
            and preference
            and user and user.status == UserStatus.active
            and job.owner_user_id == row.owner_user_id
            and job.status.value == row.terminal_status
            and int(job.attempt_count or 0) == row.attempt_number
            and _channel_enabled(preference, row.channel)
            and telegram_owner_allowed(settings, row.owner_user_id)
        )
        if not valid or (
            row.state == "claimed"
            and row.attempt_count >= settings.job_notification_max_attempts
        ):
            row.state = "suppressed"
            row.error_code = "delivery_state_changed"
            row.claim_token = None
            row.claim_expires_at = None
            row.next_attempt_at = None
            row.updated_at = current
            db.flush()
            continue
        token = secrets.token_hex(24)
        row.state = "claimed"
        row.claim_token = token
        row.claim_expires_at = current + timedelta(seconds=settings.job_notification_claim_seconds)
        row.last_attempt_at = current
        row.attempt_count = int(row.attempt_count or 0) + 1
        row.updated_at = current
        db.flush()
        return JobNotificationClaim(
            delivery_id=row.id,
            claim_token=token,
            owner_user_id=row.owner_user_id,
            job_id=row.job_id,
            terminal_status=row.terminal_status,
            attempt_number=row.attempt_number,
            channel=row.channel,
            destination_id=row.destination_id,
        )


def _notification_payload(claim: JobNotificationClaim) -> dict[str, str]:
    if claim.terminal_status == "completed":
        return {
            "title": "Транскрибация готова",
            "body": "Результат сохранён. Откройте VoiceOps Studio.",
            "url": "/transcriptions",
            "kind": "job_completed",
        }
    return {
        "title": "Транскрибация завершилась с ошибкой",
        "body": "Откройте VoiceOps Studio, чтобы посмотреть подробности.",
        "url": "/transcriptions",
        "kind": "job_failed",
    }


def _send_web_push(
    claim: JobNotificationClaim,
    *,
    settings,
    sender: Callable | None = None,
) -> tuple[bool, str | None]:
    if not claim.subscription_ciphertext or not claim.subscription_nonce:
        return False, "destination_unavailable"
    try:
        raw = decrypt(
            claim.subscription_ciphertext,
            claim.subscription_nonce,
            master_key_from_b64(settings.master_key_b64()),
            web_push_subscription_aad(claim.owner_user_id, claim.destination_id),
        )
        subscription = json.loads(raw)
        normalize_web_push_subscription(
            endpoint=subscription["endpoint"],
            p256dh=subscription["keys"]["p256dh"],
            auth=subscription["keys"]["auth"],
        )
        if sender is None:
            from pywebpush import webpush

            sender = webpush
        response = sender(
            subscription_info=subscription,
            data=json.dumps(_notification_payload(claim), ensure_ascii=False),
            vapid_private_key=settings.job_web_push_vapid_private_key_file,
            vapid_claims={"sub": settings.job_web_push_vapid_subject},
            ttl=3600,
            timeout=float(settings.job_web_push_timeout_seconds),
        )
        status_code = int(getattr(response, "status_code", 201))
        return (True, None) if 200 <= status_code <= 202 else (False, "transport_rejected")
    except Exception as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code in {404, 410}:
            return False, "subscription_gone"
        if isinstance(exc, (TimeoutError, socket.timeout)):
            return False, "transport_timeout"
        return False, "transport_unavailable"


def _send_email(
    claim: JobNotificationClaim,
    *,
    settings,
    smtp_factory: Callable | None = None,
) -> tuple[bool, str | None]:
    if not claim.recipient_email:
        return False, "destination_unavailable"
    payload = _notification_payload(claim)
    message = EmailMessage()
    message["Subject"] = payload["title"]
    message["From"] = str(settings.job_smtp_from_email)
    message["To"] = claim.recipient_email
    message.set_content(f"{payload['body']}\n\n{settings.app_origin}/transcriptions")
    factory = smtp_factory or (smtplib.SMTP_SSL if settings.job_smtp_use_ssl else smtplib.SMTP)
    try:
        tls_options = {"context": ssl.create_default_context()} if settings.job_smtp_use_ssl else {}
        with factory(
            settings.job_smtp_host,
            settings.job_smtp_port,
            timeout=float(settings.job_smtp_timeout_seconds),
            **tls_options,
        ) as smtp:
            if settings.job_smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.job_smtp_username:
                smtp.login(settings.job_smtp_username, settings.job_smtp_password())
            smtp.send_message(message)
    except (TimeoutError, socket.timeout):
        return False, "transport_timeout"
    except (OSError, smtplib.SMTPException):
        return False, "transport_unavailable"
    return True, None


def _send_telegram(
    claim: JobNotificationClaim,
    *,
    settings,
    post: Callable | None = None,
) -> tuple[bool, str | None]:
    try:
        token, chat_id = settings.job_telegram_credentials()
    except Exception:
        return False, "configuration_unavailable"
    payload = _notification_payload(claim)
    text = f"VoiceOps Studio\n{payload['title']}\n{payload['body']}"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = {"chat_id": chat_id, "text": text}
    timeout = float(settings.job_telegram_timeout_seconds)
    if post is not None:
        try:
            response = post(url, json=body, timeout=timeout)
        except (TimeoutError, socket.timeout):
            return False, "transport_timeout"
        except OSError:
            return False, "transport_unavailable"
        try:
            ack = response.json()
        except (AttributeError, ValueError, TypeError):
            return False, "transport_rejected"
        return (True, None) if 200 <= int(response.status_code) < 300 and _telegram_acknowledged(ack) else (False, "transport_rejected")
    request = Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS origin
            status_code = int(response.status)
            ack = json.loads(response.read(65537))
    except HTTPError:
        return False, "transport_rejected"
    except (TimeoutError, socket.timeout):
        return False, "transport_timeout"
    except URLError as exc:
        return (False, "transport_timeout") if isinstance(exc.reason, (TimeoutError, socket.timeout)) else (False, "transport_unavailable")
    except OSError:
        return False, "transport_unavailable"
    except (ValueError, UnicodeError):
        return False, "transport_rejected"
    return (True, None) if 200 <= status_code < 300 and _telegram_acknowledged(ack) else (False, "transport_rejected")


def _telegram_acknowledged(ack) -> bool:
    result = ack.get("result") if isinstance(ack, dict) and ack.get("ok") is True else None
    message_id = result.get("message_id") if isinstance(result, dict) else None
    return type(message_id) is int and message_id > 0


def complete_job_notification(
    db: Session,
    *,
    claim: JobNotificationClaim,
    success: bool,
    error_code: str | None,
    settings,
    now: datetime | None = None,
) -> bool:
    current = _utc_naive(now)
    row = db.execute(
        select(JobNotificationDelivery)
        .where(JobNotificationDelivery.id == claim.delivery_id)
        .with_for_update()
    ).scalar_one_or_none()
    if row is None or row.state != "claimed" or row.claim_token != claim.claim_token:
        return False
    row.claim_token = None
    row.claim_expires_at = None
    row.updated_at = current
    if success:
        row.state = "delivered"
        row.delivered_at = current
        row.error_code = None
        row.next_attempt_at = None
    else:
        safe_error = error_code if error_code in SAFE_DELIVERY_ERRORS else "transport_unavailable"
        row.error_code = safe_error
        if safe_error == "subscription_gone":
            subscription = db.get(WebPushSubscription, row.destination_id)
            if subscription and subscription.owner_user_id == row.owner_user_id:
                subscription.revoked_at = subscription.revoked_at or current
                subscription.updated_at = current
            row.state = "suppressed"
            row.next_attempt_at = None
        elif row.attempt_count >= settings.job_notification_max_attempts:
            row.state = "suppressed"
            row.next_attempt_at = None
        else:
            delay = min(
                settings.job_notification_retry_seconds * (2 ** max(0, row.attempt_count - 1)),
                3600,
            )
            row.state = "failed"
            row.next_attempt_at = current + timedelta(seconds=delay)
    db.flush()
    return True


def process_one_job_notification(
    *,
    session_factory,
    settings,
    now: datetime | None = None,
    web_push_sender: Callable | None = None,
    smtp_factory: Callable | None = None,
    telegram_post: Callable | None = None,
) -> bool:
    if not _configured_channels(settings):
        return False
    claim_db = session_factory()
    try:
        claim = claim_next_job_notification(claim_db, settings=settings, now=now)
        claim_db.commit()
    except Exception:
        claim_db.rollback()
        LOGGER.warning("job_notification_claim_failed")
        return False
    finally:
        claim_db.close()
    if claim is None:
        return False
    success, error_code = _send_telegram(claim, settings=settings, post=telegram_post)
    finish_db = session_factory()
    try:
        completed = complete_job_notification(
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
        LOGGER.warning("job_notification_completion_failed")
        return False
    finally:
        finish_db.close()


def notification_preferences_payload(db: Session, *, owner_user_id: str, settings) -> dict:
    preference = db.get(UserNotificationPreference, owner_user_id) or SimpleNamespace(
        web_push_enabled=False,
        email_enabled=False,
        telegram_enabled=False,
    )
    subscription_count = db.execute(
        select(WebPushSubscription.id).where(
            WebPushSubscription.owner_user_id == owner_user_id,
            WebPushSubscription.revoked_at.is_(None),
        )
    ).scalars().all()
    deliveries = db.execute(
        select(JobNotificationDelivery)
        .where(JobNotificationDelivery.owner_user_id == owner_user_id)
        .order_by(JobNotificationDelivery.created_at.desc(), JobNotificationDelivery.id.desc())
        .limit(20)
    ).scalars().all()
    return {
        "channels": {
            "web_push": {
                "enabled": False,
                "configured": False,
                "subscription_count": len(subscription_count),
                "vapid_public_key": None,
            },
            "email": {
                "enabled": False,
                "configured": False,
            },
            "telegram": {
                "enabled": bool(preference.telegram_enabled),
                "configured": telegram_owner_allowed(settings, owner_user_id),
            },
        },
        "recent_deliveries": [
            {
                "id": row.id,
                "job_id": row.job_id,
                "terminal_status": row.terminal_status,
                "channel": row.channel,
                "state": row.state,
                "attempt_count": int(row.attempt_count or 0),
                "error_code": row.error_code,
                "created_at": row.created_at.isoformat(),
                "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
            }
            for row in deliveries
        ],
    }
