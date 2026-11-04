"""An older backup must not restore active identities, grants or queued work."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session as DbSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
from studio_api.db import Base
from studio_api.models import (
    AudioPreparationJob, AudioPreparationStatus, GoogleConnection, GoogleConnectionStatus,
    JobStatus, Project, RealtimeTranscriptDraft, Session, TranscriptionJob, TrustedDevice, User, UserStatus,
    JobNotificationDelivery, YandexDiskConnection, UserNotificationPreference, WebPushSubscription, LocalExecutionDevice,
)
from studio_api.recovery_quarantine import quarantine_restored_database, quarantine_statements


def test_pre_local_device_backup_can_still_be_quarantined():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE local_execution_devices"))
    with DbSession(engine) as db:
        user = User(email="old-backup@example.test")
        db.add(user); db.commit()
        assert quarantine_restored_database(db, now=datetime.now(timezone.utc))["automatic_activation"] is False
        db.commit(); db.refresh(user)
        assert user.status == UserStatus.disabled
    engine.dispose()


@pytest.mark.parametrize("execution", ["orm", "literal_sql"])
@pytest.mark.parametrize("connection_status", list(GoogleConnectionStatus))
def test_restore_quarantines_work_and_auth_without_erasing_recovery_content(execution, connection_status):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2026, 10, 6, tzinfo=timezone.utc)
    with DbSession(engine) as db:
        user = User(id="owner", email="owner@example.test")
        project = Project(id="workspace", owner_user_id=user.id, title="Synthetic")
        db.add_all([user, project])
        db.flush()
        session = Session(user_id=user.id, token_hash="s" * 64, csrf_hash="c" * 64,
            expires_at=now + timedelta(days=1), reauthenticated_at=now)
        trusted = TrustedDevice(user_id=user.id, token_hash="t" * 64, expires_at=now + timedelta(days=30))
        local_device = LocalExecutionDevice(owner_user_id=user.id, label="Synthetic PC", creation_key="q" * 36,
            token_hash="l" * 64, credential_revision=1, runtime_status="ready", last_seen_at=now)
        job = TranscriptionJob(owner_user_id=user.id, project_id=project.id, status=JobStatus.processing,
            lease_owner_id="old-worker", lease_generation=9, automatic_retry_reason="provider_rate_limited")
        audio = AudioPreparationJob(owner_user_id=user.id, project_id=project.id,
            status=AudioPreparationStatus.processing, title="Synthetic", options_json="{}", output_destination="download",
            download_slot=1, download_request_id="old-transfer", lease_generation=2)
        # A primary grant can already be revoked while maintenance remains connected.
        connection = GoogleConnection(user_id=user.id, status=connection_status,
            refresh_token_ciphertext=b"opaque", refresh_token_nonce=b"nonce",
            maintenance_refresh_token_ciphertext=b"maintenance", maintenance_refresh_token_nonce=b"m")
        yandex = YandexDiskConnection(user_id=user.id, account_uid="synthetic-account", status="error",
            token_ciphertext=b"disk-recovery-token", token_nonce=b"d", key_id="test", credential_revision=7)
        preferences = UserNotificationPreference(user_id=user.id, web_push_enabled=True, telegram_enabled=True)
        push = WebPushSubscription(owner_user_id=user.id, endpoint_fingerprint="e" * 64,
            ciphertext=b"retained-endpoint", nonce=b"n", key_id="test")
        draft = RealtimeTranscriptDraft(owner_user_id=user.id, project_id=project.id, client_session_id="a" * 20,
            revision=1, ciphertext=b"encrypted-restored-text", nonce=b"n", key_id="test",
            payload_hmac="h" * 64, committed_segment_count=1, committed_character_count=5, partial_character_count=0)
        db.add_all([session, trusted, local_device, job, audio, connection, yandex, preferences, push, draft])
        db.flush()
        notification = JobNotificationDelivery(owner_user_id=user.id, job_id=job.id,
            terminal_status="failed", attempt_number=1, channel="email", destination_id="synthetic",
            state="claimed", claim_token="old-claim", claim_expires_at=now + timedelta(minutes=1))
        db.add(notification)
        db.commit()
        if execution == "literal_sql":
            # This is the same serialization used by the offline psql drill.
            for statement in quarantine_statements(now):
                sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
                db.execute(text(sql))
            result = {"automatic_activation": False}
        else:
            result = quarantine_restored_database(db, now=now)
        db.commit()
        db.expire_all()
        assert result["automatic_activation"] is False
        assert user.status == UserStatus.disabled and project.archived_at is not None
        assert session.revoked_at is not None and session.reauthenticated_at is None and trusted.revoked_at is not None
        assert local_device.revoked_at is not None and local_device.token_hash == "revoked"
        assert local_device.last_seen_at is None and local_device.credential_revision == 2
        assert connection.status == GoogleConnectionStatus.revoked
        assert connection.maintenance_revoked_at is not None
        assert connection.maintenance_refresh_token_ciphertext == b"maintenance"
        assert yandex.status == "revoked" and yandex.revoked_at is not None and yandex.credential_revision == 8
        assert yandex.token_ciphertext == b"disk-recovery-token"
        assert push.revoked_at is not None and push.ciphertext == b"retained-endpoint"
        assert not preferences.web_push_enabled and not preferences.telegram_enabled and not preferences.email_enabled
        assert job.status == JobStatus.failed and job.lease_generation == 10 and job.lease_owner_id is None
        assert job.automatic_retry_reason is None and job.error_code == "restore_manual_review_required"
        assert audio.status == AudioPreparationStatus.failed and audio.download_slot is None
        assert notification.state == "suppressed" and notification.claim_token is None
        assert notification.claim_expires_at is None and notification.next_attempt_at is None
        assert db.scalar(select(RealtimeTranscriptDraft.ciphertext)) == b"encrypted-restored-text"
        assert quarantine_restored_database(db, now=now)["quarantined_rows"] == 0
    engine.dispose()
