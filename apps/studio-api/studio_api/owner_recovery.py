"""Local operator-only recovery. No HTTP entrypoint, mail or external I/O."""
from sqlalchemy import select

from .audit import audit
from .models import (
    LocalIdentity, PasswordResetChallenge, SecurityEmailDelivery, Session,
    TrustedDevice, User, UserRole, UserStatus, UserTotpFactor, UserTotpRecoveryCode,
)
from .security import hash_password, normalize_email, utcnow


def recover_local_owner(db, *, owner_user_id: str, confirmed_email: str,
                        new_password: str, reset_totp: bool = False, now=None):
    """Caller commits atomically. Keep 2FA unless separately explicitly selected."""
    if not isinstance(new_password, str) or not 12 <= len(new_password) <= 1024:
        raise ValueError("invalid_password_length")
    owner = db.execute(select(User).where(User.id == owner_user_id).with_for_update()).scalar_one_or_none()
    if (owner is None or owner.role != UserRole.admin or owner.status != UserStatus.active
            or owner.email != normalize_email(confirmed_email)):
        raise ValueError("owner_confirmation_failed")
    identity = db.get(LocalIdentity, owner.id)
    if identity is None:
        raise ValueError("local_identity_required")
    current = now or utcnow()
    identity.password_hash = hash_password(new_password)
    db.query(Session).filter(Session.user_id == owner.id, Session.revoked_at.is_(None)).update(
        {Session.revoked_at: current}, synchronize_session=False)
    db.query(TrustedDevice).filter(TrustedDevice.user_id == owner.id, TrustedDevice.revoked_at.is_(None)).update(
        {TrustedDevice.revoked_at: current}, synchronize_session=False)
    db.query(PasswordResetChallenge).filter_by(user_id=owner.id, used_at=None).update(
        {PasswordResetChallenge.used_at: current}, synchronize_session=False)
    db.query(SecurityEmailDelivery).filter(
        SecurityEmailDelivery.owner_user_id == owner.id,
        SecurityEmailDelivery.kind == "password_reset",
        SecurityEmailDelivery.state.in_(["pending", "failed", "claimed"]),
    ).update({SecurityEmailDelivery.state: "cancelled", SecurityEmailDelivery.payload_ciphertext: None,
              SecurityEmailDelivery.payload_nonce: None, SecurityEmailDelivery.finished_at: current}, synchronize_session=False)
    if reset_totp:
        factor = db.get(UserTotpFactor, owner.id)
        if factor is not None:
            factor.disabled_at = current
            factor.updated_at = current
        db.query(UserTotpRecoveryCode).filter_by(user_id=owner.id, used_at=None).update(
            {UserTotpRecoveryCode.used_at: current}, synchronize_session=False)
        audit(db, "admin.owner_totp_recovered", subject_user_id=owner.id, outcome="success")
    audit(db, "admin.owner_password_recovered", subject_user_id=owner.id, outcome="success")
