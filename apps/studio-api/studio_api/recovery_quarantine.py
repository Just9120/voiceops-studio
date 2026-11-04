"""Offline restore safety, never called from ordinary runtime processing.

Restored content is retained for reconciliation, but cannot silently become
active. Re-enabling identities/workspaces requires a separately approved
recovery with current deletion evidence; this module has no release shortcut.
"""
from sqlalchemy import and_, inspect, or_, update

from .models import (
    AudioPreparationJob, AudioPreparationStatus, CredentialStatus,
    GoogleConnection, GoogleConnectionStatus, GoogleOAuthState, JobStatus, JobNotificationDelivery, OperationalAlertDelivery,
    Project, ProviderCredential, Session, TranscriptMaintenanceRun, SecurityEmailDelivery, PasswordResetChallenge,
    TranscriptMaintenanceRunStatus, TranscriptionJob, TrustedDevice, User, UserStatus, YandexDiskConnection,
    UserNotificationPreference, WebPushSubscription, LocalExecutionDevice,
)


def quarantine_statements(now, *, available_tables=None):
    """Caller must have established an offline, isolated restored target."""
    # Explicit timestamps work both through SQLAlchemy and compiled offline SQL;
    # Python onupdate callbacks are not evaluated by literal SQL compilation.
    yield update(User).where(User.status == UserStatus.active).values(status=UserStatus.disabled, disabled_at=now, updated_at=now)
    yield update(Project).where(Project.archived_at.is_(None)).values(archived_at=now, updated_at=now)
    yield update(Session).where(Session.revoked_at.is_(None)).values(revoked_at=now, reauthenticated_at=None)
    yield update(TrustedDevice).where(TrustedDevice.revoked_at.is_(None)).values(revoked_at=now)
    if available_tables is None or "local_execution_devices" in available_tables:
        yield update(LocalExecutionDevice).where(LocalExecutionDevice.revoked_at.is_(None)).values(
            revoked_at=now, updated_at=now, token_hash="revoked", last_seen_at=None,
            credential_revision=LocalExecutionDevice.credential_revision + 1)
    yield update(GoogleOAuthState).where(GoogleOAuthState.used_at.is_(None)).values(used_at=now)
    yield update(PasswordResetChallenge).where(PasswordResetChallenge.used_at.is_(None)).values(used_at=now)
    yield update(SecurityEmailDelivery).where(SecurityEmailDelivery.state.in_(("pending", "claimed", "failed"))).values(
        state="cancelled", payload_ciphertext=None, payload_nonce=None, claim_token=None, claim_expires_at=None,
        next_attempt_at=None, finished_at=now)
    yield update(ProviderCredential).where(ProviderCredential.status == CredentialStatus.active).values(status=CredentialStatus.revoked, updated_at=now)
    # Maintenance consent is independent of the primary connection status.
    # A revoked/error primary grant can still carry an active maintenance grant.
    yield update(GoogleConnection).where(or_(
        GoogleConnection.status != GoogleConnectionStatus.revoked,
        and_(GoogleConnection.maintenance_refresh_token_ciphertext.is_not(None),
             GoogleConnection.maintenance_revoked_at.is_(None)),
    )).values(
        status=GoogleConnectionStatus.revoked, revoked_at=now, maintenance_revoked_at=now, updated_at=now)
    yield update(YandexDiskConnection).where(YandexDiskConnection.status != "revoked").values(
        status="revoked", revoked_at=now, updated_at=now,
        credential_revision=YandexDiskConnection.credential_revision + 1)
    yield update(WebPushSubscription).where(WebPushSubscription.revoked_at.is_(None)).values(revoked_at=now, updated_at=now)
    yield update(UserNotificationPreference).where(or_(
        UserNotificationPreference.web_push_enabled.is_(True), UserNotificationPreference.email_enabled.is_(True),
        UserNotificationPreference.telegram_enabled.is_(True),
    )).values(web_push_enabled=False, email_enabled=False, telegram_enabled=False, updated_at=now)
    for model in (JobNotificationDelivery, OperationalAlertDelivery):
        yield update(model).where(model.state.in_(("pending", "claimed", "failed"))).values(
            state="suppressed", claim_token=None, claim_expires_at=None, next_attempt_at=None, updated_at=now)
    yield update(TranscriptionJob).where(TranscriptionJob.status.in_((JobStatus.queued, JobStatus.processing))).values(
        status=JobStatus.failed, error_code="restore_manual_review_required", finished_at=now, updated_at=now,
        retry_not_before_at=None, automatic_retry_reason=None, lease_owner_id=None, lease_expires_at=None,
        lease_generation=TranscriptionJob.lease_generation + 1)
    yield update(AudioPreparationJob).where(AudioPreparationJob.status.in_((
        AudioPreparationStatus.preview_queued, AudioPreparationStatus.analyzing,
        AudioPreparationStatus.queued, AudioPreparationStatus.processing,
    ))).values(status=AudioPreparationStatus.failed, error_code="restore_manual_review_required",
        finished_at=now, updated_at=now, lease_owner_id=None, lease_expires_at=None,
        lease_generation=AudioPreparationJob.lease_generation + 1)
    yield update(AudioPreparationJob).where(AudioPreparationJob.download_slot.is_not(None)).values(
        download_slot=None, download_request_id=None, download_expires_at=None, download_size_bytes=None,
        download_error_code="restore_manual_review_required", updated_at=now)
    yield update(TranscriptMaintenanceRun).where(TranscriptMaintenanceRun.status.in_((
        TranscriptMaintenanceRunStatus.queued, TranscriptMaintenanceRunStatus.running,
    ))).values(status=TranscriptMaintenanceRunStatus.failed, error_code="restore_manual_review_required",
        error_retryable=False, finished_at=now, updated_at=now, lease_owner_id=None, lease_expires_at=None,
        lease_generation=TranscriptMaintenanceRun.lease_generation + 1)


def quarantine_restored_database(db, *, now):
    """Apply atomically; caller commits. No text/bytes/credential is decrypted."""
    counts = []
    for statement in quarantine_statements(now, available_tables=set(inspect(db.get_bind()).get_table_names())):
        counts.append(int(db.execute(statement).rowcount or 0))
    db.flush()
    return {"quarantined_rows": sum(counts), "automatic_activation": False}
