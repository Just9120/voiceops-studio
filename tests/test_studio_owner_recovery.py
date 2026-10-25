import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
os.environ.setdefault("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
from studio_api.db import Base
from studio_api.models import (
    AuditEvent, LocalIdentity, PasswordResetChallenge, Session, TrustedDevice,
    User, UserRole, UserStatus, UserTotpFactor, UserTotpRecoveryCode,
)
from studio_api.owner_recovery import recover_local_owner
from studio_api.security import hash_password, verify_password

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)


@pytest.fixture
def database():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        owner = User(email="owner@example.test", role=UserRole.admin, status=UserStatus.active)
        other = User(email="other@example.test", role=UserRole.user, status=UserStatus.active)
        db.add_all([owner, other]); db.flush()
        for u in [owner, other]:
            db.add(LocalIdentity(user_id=u.id, password_hash=hash_password("old-test-password")))
            db.add(Session(user_id=u.id, token_hash=u.id, csrf_hash=u.id, expires_at=NOW+timedelta(days=1)))
            db.add(TrustedDevice(user_id=u.id, token_hash=u.id, expires_at=NOW+timedelta(days=1)))
            db.add(PasswordResetChallenge(user_id=u.id, token_hash=u.id, request_fingerprint="synthetic",
                                          expires_at=NOW+timedelta(minutes=5)))
            db.add(UserTotpFactor(user_id=u.id, secret_ciphertext=b"synthetic", secret_nonce=b"test",
                                  key_id="synthetic", confirmed_at=NOW))
            db.add(UserTotpRecoveryCode(user_id=u.id, code_hash=u.id))
        db.commit()
        yield db, owner, other
    engine.dispose()


@pytest.mark.parametrize("reset_totp", [False, True])
def test_operator_recovery_revokes_only_owner_and_keeps_2fa_unless_explicit(database, reset_totp):
    db, owner, other = database
    recover_local_owner(db, owner_user_id=owner.id, confirmed_email=owner.email,
                        new_password="new-synthetic-password", reset_totp=reset_totp, now=NOW)
    db.commit(); db.expire_all()
    assert verify_password(db.get(LocalIdentity, owner.id).password_hash, "new-synthetic-password")
    assert verify_password(db.get(LocalIdentity, other.id).password_hash, "old-test-password")
    for model, field in [(Session,"revoked_at"),(TrustedDevice,"revoked_at"),(PasswordResetChallenge,"used_at")]:
        assert getattr(db.query(model).filter_by(user_id=owner.id).one(), field) is not None
        assert getattr(db.query(model).filter_by(user_id=other.id).one(), field) is None
    assert (db.get(UserTotpFactor, owner.id).disabled_at is not None) is reset_totp
    assert db.get(UserTotpFactor, other.id).disabled_at is None
    assert (db.query(UserTotpRecoveryCode).filter_by(user_id=owner.id).one().used_at is not None) is reset_totp
    events = db.query(AuditEvent).all()
    assert {e.event_type for e in events} == {"admin.owner_password_recovered"} | ({"admin.owner_totp_recovered"} if reset_totp else set())
    assert all(e.actor_user_id is None and e.subject_user_id==owner.id for e in events)
    assert all("password" not in e.metadata_json for e in events)


@pytest.mark.parametrize("case", ["wrong_email","ordinary_user","disabled","unknown","short_password","no_local_identity"])
def test_recovery_rejects_wrong_identity_without_side_effects(database, case):
    db, owner, other = database
    owner_id, email, password = owner.id, owner.email, "new-synthetic-password"
    if case=="wrong_email":email=other.email
    if case=="ordinary_user":owner_id,email=other.id,other.email
    if case=="disabled":owner.status=UserStatus.disabled;db.commit()
    if case=="unknown":owner_id="unknown"
    if case=="short_password":password="short"
    if case=="no_local_identity":db.delete(db.get(LocalIdentity,owner.id));db.commit()
    with pytest.raises(ValueError):
        recover_local_owner(db,owner_user_id=owner_id,confirmed_email=email,new_password=password,now=NOW)
    db.rollback()
    assert db.query(AuditEvent).count()==0
    assert db.query(Session).filter(Session.revoked_at.is_not(None)).count()==0
    assert db.query(TrustedDevice).filter(TrustedDevice.revoked_at.is_not(None)).count()==0


def test_recovery_cli_refuses_noninteractive_password_input(monkeypatch,capsys):
    from studio_api import cli
    monkeypatch.setattr(sys,"argv",["studio_api.cli","00000000-0000-0000-0000-000000000001"])
    monkeypatch.setattr(sys.stdin,"isatty",lambda:False)
    assert cli.recover_owner()==2
    assert "interactive terminal" in capsys.readouterr().err
