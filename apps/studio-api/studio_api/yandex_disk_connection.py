"""Session-bound, one-use OAuth with local-first disconnection.

The shared OAuth-state table is a nonce store, not a Google grant: purpose and
initiating session are checked before any external exchange. Network operations
never keep a database transaction open.
"""
from datetime import timedelta

from sqlalchemy import select

from .audit import audit
from .models import GoogleOAuthState, User, YandexDiskConnection
from .oauth_session import lock_oauth_initiator
from .security import new_token, token_hash, utcnow
from .yandex_disk import YandexDiskClient, YandexDiskError
from .yandex_disk_access import _tokens, store_tokens
from .yandex_disk_oauth import (
    authorization_url, exchange_code, load_config, pkce_verifier, revoke_token,
)

PURPOSE = "yandex_disk"


def _lock_owner(db, owner_id):
    return db.execute(select(User).where(User.id == owner_id).with_for_update()).scalar_one()


def start_connection(db, *, session, user, settings):
    config = load_config(settings)
    now = utcnow()
    _lock_owner(db, user.id)
    # A second start supersedes an outstanding flow for this provider only.
    for prior in db.scalars(select(GoogleOAuthState).where(
        GoogleOAuthState.user_id == user.id,
        GoogleOAuthState.purpose == PURPOSE,
        GoogleOAuthState.expires_at > now,
    ).with_for_update()):
        prior.used_at = now
        prior.expires_at = now
    raw_state = new_token()
    row = GoogleOAuthState(
        user_id=user.id, session_id=session.id, state_hash=token_hash(raw_state),
        purpose=PURPOSE, expires_at=now + timedelta(minutes=10),
    )
    db.add(row)
    audit(db, "yandex_disk.oauth_started", actor_user_id=user.id, subject_user_id=user.id)
    url = authorization_url(
        config, state=raw_state,
        verifier=pkce_verifier(raw_state, settings.master_key_b64()),
        device_id=token_hash("yandex-disk:" + user.id)[:32],
    )
    db.commit()
    return {"authorization_url": url, "expires_at": row.expires_at.isoformat()}


def finish_connection(db, *, state, code, error, raw_session, settings,
                      exchange=exchange_code, client_factory=YandexDiskClient):
    if not isinstance(state, str) or not 1 <= len(state) <= 256:
        return "invalid_state"
    row = db.scalar(select(GoogleOAuthState).where(
        GoogleOAuthState.state_hash == token_hash(state),
        GoogleOAuthState.purpose == PURPOSE,
    ))
    if row is None:
        db.rollback()
        return "invalid_state"
    _lock_owner(db, row.user_id)
    row = db.get(GoogleOAuthState, row.id, populate_existing=True, with_for_update=True)
    now = utcnow()
    if (row is None or row.used_at is not None or row.expires_at <= now
            or lock_oauth_initiator(db, state=row, raw_session=raw_session, now=now) is None):
        db.rollback()
        return "invalid_state"
    owner_id, state_id = row.user_id, row.id
    prior = db.get(YandexDiskConnection, owner_id)
    revision = prior.credential_revision if prior else None
    row.used_at = now
    if error or not isinstance(code, str) or not 1 <= len(code) <= 2048:
        audit(db, "yandex_disk.oauth_failed", subject_user_id=owner_id,
              outcome="rejected", reason="cancelled" if error else "invalid_callback")
        db.commit()
        return "cancelled" if error else "invalid_callback"
    db.commit()  # Consume before exchange: replay never contacts the provider.
    try:
        tokens = exchange(load_config(settings), code=code,
                          verifier=pkce_verifier(state, settings.master_key_b64()), now=now)
        account_uid = client_factory(tokens["access_token"]).account_identity()
    except YandexDiskError:
        return "exchange_failed"
    _lock_owner(db, owner_id)
    row = db.get(GoogleOAuthState, state_id, populate_existing=True)
    # Check the browser and newer starts again after slow provider work. Logout,
    # disconnect, or another successful callback must not be undone by this one.
    if (row.expires_at <= utcnow()
            or lock_oauth_initiator(db, state=row, raw_session=raw_session, now=utcnow()) is None):
        db.rollback()
        return "invalid_state"
    connection = db.get(YandexDiskConnection, owner_id, populate_existing=True)
    current_revision = connection.credential_revision if connection else None
    if revision != current_revision:
        db.rollback()
        return "connection_changed"
    if connection is None:
        connection = YandexDiskConnection(user_id=owner_id, account_uid=account_uid,
            key_id=settings.credential_key_id, credential_revision=0)
        db.add(connection)
    connection.account_uid = account_uid
    connection.status = "active"
    connection.connected_at = now
    connection.revoked_at = None
    store_tokens(connection, payload=tokens, settings=settings, now=now)
    audit(db, "yandex_disk.connected", actor_user_id=owner_id, subject_user_id=owner_id)
    db.commit()
    return "connected"


def disconnect_connection(db, *, owner_id, settings, revoker=revoke_token):
    now = utcnow()
    _lock_owner(db, owner_id)
    row = db.get(YandexDiskConnection, owner_id)
    access = None
    if row and row.token_ciphertext and row.token_nonce:
        try:
            access = _tokens(row, settings)["access_token"]
        except YandexDiskError:
            pass  # Local removal must still work with an unreadable credential.
    if row:
        row.token_ciphertext = row.token_nonce = None
        row.status = "revoked"
        row.revoked_at = row.updated_at = now
        row.credential_revision += 1
    for state in db.scalars(select(GoogleOAuthState).where(
        GoogleOAuthState.user_id == owner_id,
        GoogleOAuthState.purpose == PURPOSE, GoogleOAuthState.expires_at > now,
    )):
        state.used_at = now
        state.expires_at = now
    audit(db, "yandex_disk.disconnected", actor_user_id=owner_id, subject_user_id=owner_id)
    db.commit()  # Revoke local authority even when the provider is unavailable.
    attempted = confirmed = False
    if access:
        try:
            config = load_config(settings)
            attempted = True
            confirmed = revoker(config, access_token=access) is True
        except YandexDiskError:
            pass
    return {"disconnected": True, "remote_revocation_attempted": attempted,
            "remote_revocation_confirmed": confirmed}
