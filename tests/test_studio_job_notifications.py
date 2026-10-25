from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))
os.environ.setdefault("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")

from studio_api.db import Base  # noqa: E402
from studio_api import models as m  # noqa: E402
from studio_api.job_notifications import (  # noqa: E402
    JobNotificationClaim,
    _send_email,
    _send_telegram,
    _send_web_push,
    claim_next_job_notification,
    complete_job_notification,
    ensure_terminal_notification_intents,
    normalize_web_push_subscription,
    upsert_web_push_subscription,
)
from studio_api.job_retry_recovery import schedule_automatic_retry_if_safe  # noqa: E402
from studio_api.security import decrypt, master_key_from_b64  # noqa: E402


MASTER_KEY = base64.b64encode(b"n" * 32).decode("ascii")
NOW = datetime(2026, 9, 3, 8, 0, 0)


class NotificationSettings(SimpleNamespace):
    def job_web_push_configured(self):
        return bool(self.web_push)

    def job_email_configured(self):
        return bool(self.email)

    def job_telegram_configured(self):
        return bool(self.telegram)


def settings(*, web_push=False, email=False, telegram=False, owner=None, max_attempts=2):
    return NotificationSettings(
        web_push=web_push,
        email=email,
        telegram=telegram,
        job_telegram_owner_user_id=owner,
        job_notification_max_attempts=max_attempts,
        job_notification_claim_seconds=60,
        job_notification_retry_seconds=30,
    )


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def job_fixture(db, *, status=m.JobStatus.failed, attempt_count=1):
    owner = m.User(email="owner@example.com", status=m.UserStatus.active)
    db.add(owner)
    db.flush()
    project = m.Project(owner_user_id=owner.id, title="Project", output_drive_folder_id="folder")
    db.add(project)
    db.flush()
    job = m.TranscriptionJob(
        project_id=project.id,
        owner_user_id=owner.id,
        status=status,
        provider="elevenlabs",
        provider_credential_id="credential",
        output_drive_folder_id="folder",
        attempt_count=attempt_count,
        finished_at=NOW if status in {m.JobStatus.failed, m.JobStatus.completed} else None,
    )
    db.add(job)
    db.flush()
    source = m.Source(
        project_id=project.id,
        source_type=m.SourceType.local_upload,
        original_filename="recording.mp3",
        mime_type="audio/mpeg",
        size_bytes=1,
        s3_bucket="bucket",
        s3_object_key="owner/source",
        upload_status=m.SourceUploadStatus.uploaded,
        uploaded_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )
    db.add(source)
    db.flush()
    relation = m.TranscriptionJobSource(
        job_id=job.id,
        source_id=source.id,
        position=0,
        status=m.JobSourceStatus.queued,
    )
    db.add(relation)
    db.commit()
    return owner, job, relation


def test_job_notification_migration_is_additive_single_head():
    script = ScriptDirectory.from_config(Config(str(ROOT / "apps/studio-api/alembic.ini")))
    revision = script.get_revision("0035_job_notifications")
    assert script.get_heads() == ["0043_yandex_disk"]
    assert revision.down_revision == "0034_personal_security"
    assert revision.module.release_safety == "additive"
    assert {"retry_not_before_at", "automatic_retry_reason"} <= set(
        m.TranscriptionJob.__table__.c.keys()
    )
    assert m.JobNotificationDelivery.__table__.name == "job_notification_deliveries"


def test_job_notification_migration_accepts_fresh_metadata_schema():
    script = ScriptDirectory.from_config(Config(str(ROOT / "apps/studio-api/alembic.ini")))
    revision = script.get_revision("0035_job_notifications")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        original_op = revision.module.op
        revision.module.op = Operations(MigrationContext.configure(connection))
        try:
            revision.module.upgrade()
        finally:
            revision.module.op = original_op
    engine.dispose()


def test_web_push_subscription_is_validated_and_encrypted(db):
    owner, _job, _relation = job_fixture(db)
    endpoint = "https://fcm.googleapis.com/fcm/send/safe-subscription-id"
    p256dh = base64.urlsafe_b64encode(b"p" * 65).decode("ascii").rstrip("=")
    auth = base64.urlsafe_b64encode(b"a" * 16).decode("ascii").rstrip("=")
    row = upsert_web_push_subscription(
        db,
        owner_user_id=owner.id,
        endpoint=endpoint,
        p256dh=p256dh,
        auth=auth,
        master_key_b64=MASTER_KEY,
        key_id="test-v1",
        now=NOW,
    )
    db.commit()

    assert endpoint.encode("utf-8") not in row.ciphertext
    plaintext = decrypt(
        row.ciphertext,
        row.nonce,
        master_key_from_b64(MASTER_KEY),
        f"studio:web-push:{owner.id}:{row.id}".encode("utf-8"),
    )
    assert endpoint in plaintext
    with pytest.raises(ValueError, match="invalid_web_push_endpoint"):
        normalize_web_push_subscription(
            endpoint="http://attacker.invalid/push",
            p256dh=p256dh,
            auth=auth,
        )


def test_terminal_intents_are_opt_in_and_deduplicated(db):
    owner, job, _relation = job_fixture(db, status=m.JobStatus.completed)
    db.add(
        m.UserNotificationPreference(
            user_id=owner.id,
            email_enabled=True,
            telegram_enabled=True,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    db.flush()

    assert ensure_terminal_notification_intents(db, job=job, now=NOW) == 1
    assert ensure_terminal_notification_intents(db, job=job, now=NOW) == 0
    db.commit()
    assert {
        (row.channel, row.terminal_status, row.attempt_number)
        for row in db.query(m.JobNotificationDelivery).all()
    } == {("telegram", "completed", 1)}


def test_delivery_claims_retry_with_a_bound_and_then_suppress(db):
    owner, job, _relation = job_fixture(db, status=m.JobStatus.failed)
    db.add(
        m.UserNotificationPreference(
            user_id=owner.id,
            telegram_enabled=True,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    db.flush()
    ensure_terminal_notification_intents(db, job=job, now=NOW)
    db.commit()
    configured = settings(telegram=True, owner=owner.id, max_attempts=2)

    first = claim_next_job_notification(db, settings=configured, now=NOW)
    assert first is not None and first.channel == "telegram"
    assert complete_job_notification(
        db,
        claim=first,
        success=False,
        error_code="transport_timeout",
        settings=configured,
        now=NOW,
    )
    db.commit()
    delivery = db.query(m.JobNotificationDelivery).one()
    assert delivery.state == "failed"
    assert delivery.next_attempt_at == NOW + timedelta(seconds=30)
    assert claim_next_job_notification(db, settings=configured, now=NOW + timedelta(seconds=29)) is None

    second = claim_next_job_notification(db, settings=configured, now=NOW + timedelta(seconds=30))
    assert second is not None
    assert complete_job_notification(
        db,
        claim=second,
        success=False,
        error_code="transport_unavailable",
        settings=configured,
        now=NOW + timedelta(seconds=30),
    )
    db.commit()
    assert delivery.state == "suppressed"
    assert delivery.attempt_count == 2


@pytest.mark.parametrize(
    ("terminal_status", "expected_title"),
    [
        ("completed", "Транскрибация готова"),
        ("failed", "Транскрибация завершилась с ошибкой"),
    ],
)
def test_web_push_transport_uses_only_safe_terminal_payload(
    db,
    terminal_status,
    expected_title,
):
    owner, _job, _relation = job_fixture(db)
    endpoint = "https://fcm.googleapis.com/fcm/send/safe-subscription-id"
    row = upsert_web_push_subscription(
        db,
        owner_user_id=owner.id,
        endpoint=endpoint,
        p256dh=base64.urlsafe_b64encode(b"p" * 65).decode("ascii").rstrip("="),
        auth=base64.urlsafe_b64encode(b"a" * 16).decode("ascii").rstrip("="),
        master_key_b64=MASTER_KEY,
        key_id="test-v1",
        now=NOW,
    )
    db.commit()
    sent = {}

    def sender(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(status_code=201)

    claim = JobNotificationClaim(
        delivery_id="delivery",
        claim_token="claim",
        owner_user_id=owner.id,
        job_id="job",
        terminal_status=terminal_status,
        attempt_number=1,
        channel="web_push",
        destination_id=row.id,
        subscription_ciphertext=bytes(row.ciphertext),
        subscription_nonce=bytes(row.nonce),
    )
    transport_settings = SimpleNamespace(
        master_key_b64=lambda: MASTER_KEY,
        job_web_push_vapid_private_key_file="/run/secrets/private-key",
        job_web_push_vapid_subject="mailto:operator@example.com",
        job_web_push_timeout_seconds=5,
    )

    assert _send_web_push(claim, settings=transport_settings, sender=sender) == (
        True,
        None,
    )
    payload = json.loads(sent["data"])
    assert payload == {
        "title": expected_title,
        "body": (
            "Результат сохранён. Откройте VoiceOps Studio."
            if terminal_status == "completed"
            else "Откройте VoiceOps Studio, чтобы посмотреть подробности."
        ),
        "url": "/transcriptions",
        "kind": f"job_{terminal_status}",
    }
    assert endpoint == sent["subscription_info"]["endpoint"]


@pytest.mark.parametrize("terminal_status", ["completed", "failed"])
def test_email_transport_covers_success_and_failure_without_job_content(
    terminal_status,
):
    sent = {}

    class FakeSmtp:
        def __init__(self, host, port, *, timeout):
            sent.update(host=host, port=port, timeout=timeout)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def starttls(self, *, context):
            sent["tls"] = context is not None

        def login(self, username, password):
            sent.update(username=username, password=password)

        def send_message(self, message):
            sent["message"] = message

    claim = JobNotificationClaim(
        delivery_id="delivery",
        claim_token="claim",
        owner_user_id="owner",
        job_id="job",
        terminal_status=terminal_status,
        attempt_number=1,
        channel="email",
        destination_id="account",
        recipient_email="owner@example.com",
    )
    transport_settings = SimpleNamespace(
        job_smtp_from_email="studio@example.com",
        job_smtp_use_ssl=False,
        job_smtp_starttls=True,
        job_smtp_host="smtp.example.com",
        job_smtp_port=587,
        job_smtp_timeout_seconds=5,
        job_smtp_username="studio",
        job_smtp_password=lambda: "synthetic-password",
        app_origin="https://studio.example.com",
    )

    assert _send_email(
        claim,
        settings=transport_settings,
        smtp_factory=FakeSmtp,
    ) == (True, None)
    assert sent["tls"] is True
    assert sent["username"] == "studio"
    message = sent["message"]
    assert message["To"] == "owner@example.com"
    assert "Транскрибация" in message["Subject"]
    assert "recording.mp3" not in message.get_content()


@pytest.mark.parametrize("terminal_status", ["completed", "failed"])
def test_telegram_transport_covers_success_and_failure_without_job_content(
    terminal_status,
):
    sent = {}

    def post(url, *, json, timeout):
        sent.update(url=url, body=json, timeout=timeout)
        return SimpleNamespace(status_code=200, json=lambda: {"ok": True, "result": {"message_id": 1}})

    claim = JobNotificationClaim(
        delivery_id="delivery",
        claim_token="claim",
        owner_user_id="owner",
        job_id="private-job-123",
        terminal_status=terminal_status,
        attempt_number=1,
        channel="telegram",
        destination_id="configured",
    )
    transport_settings = SimpleNamespace(
        job_telegram_credentials=lambda: ("12345678901234567890:token", "123"),
        job_telegram_timeout_seconds=5,
        app_origin="https://studio.cloud-nodes.net/",
    )

    assert _send_telegram(claim, settings=transport_settings, post=post) == (
        True,
        None,
    )
    assert sent["body"]["chat_id"] == "123"
    assert "Транскрибация" in sent["body"]["text"]
    assert "recording.mp3" not in sent["body"]["text"]
    assert "private-job-123" not in sent["body"]["text"]
    assert sent["body"]["text"].endswith("\nhttps://studio.cloud-nodes.net/transcriptions")


def test_retired_channels_never_enqueue_even_with_legacy_opt_ins(db):
    owner, job, _relation = job_fixture(db, status=m.JobStatus.completed)
    db.add(m.UserNotificationPreference(user_id=owner.id, email_enabled=True, web_push_enabled=True))
    db.flush()
    assert ensure_terminal_notification_intents(db, job=job, now=NOW)==0
    assert claim_next_job_notification(db, settings=settings(email=True,web_push=True),now=NOW) is None
    assert db.query(m.JobNotificationDelivery).count()==0


@pytest.mark.parametrize("reason", ["other_owner", "disabled", "opt_out"])
def test_telegram_cannot_deliver_for_wrong_or_inactive_owner(db, reason):
    owner, job, _relation = job_fixture(db,status=m.JobStatus.completed)
    pref=m.UserNotificationPreference(user_id=owner.id,telegram_enabled=True)
    db.add(pref);db.flush()
    assert ensure_terminal_notification_intents(db,job=job,now=NOW)==1
    config=settings(telegram=True,owner=owner.id)
    if reason=="other_owner":config.job_telegram_owner_user_id="another-owner"
    if reason=="disabled":owner.status=m.UserStatus.disabled
    if reason=="opt_out":pref.telegram_enabled=False
    db.commit()
    assert claim_next_job_notification(db,settings=config,now=NOW) is None
    assert db.query(m.JobNotificationDelivery).one().state=="suppressed"


@pytest.mark.parametrize("ack", [{"ok":False}, {}, {"ok":True}, {"ok":True,"result":{"message_id":True}}])
def test_telegram_http_200_without_message_ack_is_not_delivered(ack):
    claim=JobNotificationClaim("delivery","claim","owner","job","completed",1,"telegram","configured")
    config=SimpleNamespace(job_telegram_credentials=lambda:("12345678901234567890:token","123"),job_telegram_timeout_seconds=5)
    assert _send_telegram(claim,settings=config,post=lambda *a,**kw:SimpleNamespace(status_code=200,json=lambda:ack))==(False,"transport_rejected")


def test_automatic_retry_only_accepts_allowlisted_durable_transient_failure(db):
    owner, job, relation = job_fixture(db, status=m.JobStatus.failed)
    db.add_all(
        [
            m.UserNotificationPreference(
                user_id=owner.id,
                telegram_enabled=True,
                created_at=NOW,
                updated_at=NOW,
            ),
            m.TranscriptionJobSourceAttempt(
                owner_user_id=owner.id,
                project_id=job.project_id,
                job_id=job.id,
                job_source_id=relation.id,
                attempt_number=1,
                stage=m.SourceAttemptStage.failed,
                retry_disposition=m.SourceAttemptRetryDisposition.retry_safe,
                failure_code="provider_rate_limited",
                provider_failure_code="provider_rate_limited",
                failed_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            ),
        ]
    )
    db.flush()
    ensure_terminal_notification_intents(db, job=job, now=NOW)
    assert schedule_automatic_retry_if_safe(db, job=job, now=NOW)
    db.commit()

    assert job.status == m.JobStatus.queued
    assert job.retry_not_before_at == NOW + timedelta(seconds=30)
    assert job.automatic_retry_reason == "provider_rate_limited"
    assert db.query(m.JobNotificationDelivery).one().state == "suppressed"

    job.status = m.JobStatus.failed
    job.finished_at = NOW
    job.retry_not_before_at = None
    attempt = db.query(m.TranscriptionJobSourceAttempt).one()
    attempt.retry_disposition = m.SourceAttemptRetryDisposition.provider_outcome_uncertain
    attempt.failure_code = "provider_timeout"
    attempt.provider_failure_code = "provider_timeout"
    db.commit()
    assert not schedule_automatic_retry_if_safe(db, job=job, now=NOW)
    assert job.status == m.JobStatus.failed
