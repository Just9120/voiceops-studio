from __future__ import annotations

from enum import Enum

import httpx
from sqlalchemy.orm import Session

from .google_oauth import (
    GoogleOAuthConfigError,
    load_google_maintenance_oauth_config,
    load_google_oauth_config,
)
from .models import GoogleConnection, GoogleConnectionStatus, GoogleProvider
from .google_scopes import (
    has_drive_file_scope,
    has_drive_readonly_scope,
    has_maintenance_server_scope_boundary,
    has_picker_browser_scope_boundary,
)
from .google_drive import (
    GoogleAccessTokenRefreshError,
    GoogleAccessTokenRefreshReason,
)
from .security import aad, decrypt, master_key_from_b64


class GoogleConnectionAccessReason(str, Enum):
    missing = "google_connection_missing"
    inactive = "google_connection_inactive"
    reauthorization_required = "google_reauthorization_required"
    token_unavailable = "google_token_unavailable"
    config_unavailable = "google_config_unavailable"
    scope_unavailable = "google_scope_unavailable"
    maintenance_missing = "google_maintenance_connection_missing"
    maintenance_inactive = "google_maintenance_connection_inactive"
    maintenance_account_mismatch = "google_maintenance_account_mismatch"


class GoogleConnectionAccessError(RuntimeError):
    def __init__(self, reason: GoogleConnectionAccessReason):
        self.reason = reason
        super().__init__(reason.value)



def active_google_connection_for_user(db: Session, *, user_id: str) -> GoogleConnection:
    conn = db.query(GoogleConnection).filter_by(user_id=user_id, provider=GoogleProvider.google).first()
    if conn is None:
        raise GoogleConnectionAccessError(GoogleConnectionAccessReason.missing)
    if conn.status != GoogleConnectionStatus.active:
        raise GoogleConnectionAccessError(GoogleConnectionAccessReason.inactive)
    return conn


def require_drive_file_scope(conn: GoogleConnection) -> None:
    if not has_drive_file_scope(conn.scopes):
        raise GoogleConnectionAccessError(GoogleConnectionAccessReason.scope_unavailable)


def require_drive_readonly_scope(conn: GoogleConnection) -> None:
    if not has_drive_readonly_scope(conn.scopes):
        raise GoogleConnectionAccessError(
            GoogleConnectionAccessReason.scope_unavailable
        )


def require_picker_browser_scope_boundary(conn: GoogleConnection) -> None:
    if not has_picker_browser_scope_boundary(conn.scopes):
        raise GoogleConnectionAccessError(GoogleConnectionAccessReason.scope_unavailable)


def require_maintenance_server_scope_boundary(
    conn: GoogleConnection,
) -> None:
    if not has_maintenance_server_scope_boundary(conn.maintenance_scopes):
        raise GoogleConnectionAccessError(
            GoogleConnectionAccessReason.scope_unavailable
        )


def google_token_aad(user_id: str, connection_id: str) -> bytes:
    return aad(user_id, connection_id, "refresh", "google")


def google_maintenance_token_aad(
    user_id: str,
    connection_id: str,
) -> bytes:
    return aad(
        user_id,
        connection_id,
        "maintenance-refresh",
        "google",
    )


def revoke_google_connection_grants(conn: GoogleConnection, *, settings) -> str:
    materials = (
        (conn.refresh_token_ciphertext, conn.refresh_token_nonce, google_token_aad(conn.user_id, conn.id)),
        (conn.maintenance_refresh_token_ciphertext, conn.maintenance_refresh_token_nonce,
         google_maintenance_token_aad(conn.user_id, conn.id)),
    )
    if not any(ciphertext or nonce for ciphertext, nonce, _ in materials):
        return "not_needed"
    try:
        key = master_key_from_b64(settings.master_key_b64())
    except Exception:
        return "unconfirmed"
    tokens = set()
    confirmed = True
    for ciphertext, nonce, aad_value in materials:
        if not ciphertext and not nonce:
            continue
        try:
            tokens.add(decrypt(ciphertext, nonce, key, aad_value))
        except Exception:
            confirmed = False
    # POST form data rather than query parameters so token values stay out of URLs.
    with httpx.Client(timeout=httpx.Timeout(3.0, connect=2.0), follow_redirects=False, trust_env=False) as client:
        for token in tokens:
            try:
                result = client.post("https://oauth2.googleapis.com/revoke", data={"token": token})
                revoked = result.status_code == 200 or (
                    result.status_code == 400 and result.json().get("error") == "invalid_token"
                )
            except (httpx.HTTPError, ValueError, AttributeError):
                revoked = False
            confirmed = confirmed and revoked
    return "confirmed" if confirmed and tokens else "unconfirmed"


def refresh_access_token(config, refresh_token: str) -> str:
    from .google_drive import refresh_access_token as provider_refresh_access_token

    return provider_refresh_access_token(config, refresh_token)


def refresh_user_google_drive_access_token(db: Session, *, user_id: str, settings) -> str:
    conn = active_google_connection_for_user(db, user_id=user_id)
    if not conn.refresh_token_ciphertext or not conn.refresh_token_nonce or not conn.key_id:
        raise GoogleConnectionAccessError(GoogleConnectionAccessReason.inactive)
    try:
        cfg = load_google_oauth_config(settings)
        refresh_token = decrypt(
            conn.refresh_token_ciphertext,
            conn.refresh_token_nonce,
            master_key_from_b64(settings.master_key_b64()),
            google_token_aad(user_id, conn.id),
        )
        return refresh_access_token(cfg, refresh_token)
    except GoogleAccessTokenRefreshError as exc:
        reason = (
            GoogleConnectionAccessReason.reauthorization_required
            if exc.reason == GoogleAccessTokenRefreshReason.authentication_rejected
            else GoogleConnectionAccessReason.token_unavailable
        )
        raise GoogleConnectionAccessError(reason) from exc
    except GoogleConnectionAccessError:
        raise
    except GoogleOAuthConfigError as exc:
        raise GoogleConnectionAccessError(GoogleConnectionAccessReason.config_unavailable) from exc
    except Exception as exc:
        raise GoogleConnectionAccessError(GoogleConnectionAccessReason.token_unavailable) from exc


def refresh_user_google_maintenance_access_token(
    db: Session,
    *,
    user_id: str,
    settings,
) -> str:
    conn = active_google_connection_for_user(db, user_id=user_id)
    if conn.maintenance_revoked_at is not None:
        raise GoogleConnectionAccessError(
            GoogleConnectionAccessReason.maintenance_inactive
        )
    if (
        not conn.maintenance_refresh_token_ciphertext
        or not conn.maintenance_refresh_token_nonce
        or not conn.maintenance_key_id
    ):
        raise GoogleConnectionAccessError(
            GoogleConnectionAccessReason.maintenance_missing
        )
    if (
        not conn.google_subject
        or not conn.maintenance_google_subject
        or conn.google_subject != conn.maintenance_google_subject
    ):
        raise GoogleConnectionAccessError(
            GoogleConnectionAccessReason.maintenance_account_mismatch
        )
    require_maintenance_server_scope_boundary(conn)
    try:
        cfg = load_google_maintenance_oauth_config(settings)
        refresh_token = decrypt(
            conn.maintenance_refresh_token_ciphertext,
            conn.maintenance_refresh_token_nonce,
            master_key_from_b64(settings.master_key_b64()),
            google_maintenance_token_aad(user_id, conn.id),
        )
        return refresh_access_token(cfg, refresh_token)
    except GoogleAccessTokenRefreshError as exc:
        reason = (
            GoogleConnectionAccessReason.reauthorization_required
            if exc.reason
            == GoogleAccessTokenRefreshReason.authentication_rejected
            else GoogleConnectionAccessReason.token_unavailable
        )
        raise GoogleConnectionAccessError(reason) from exc
    except GoogleConnectionAccessError:
        raise
    except GoogleOAuthConfigError as exc:
        raise GoogleConnectionAccessError(
            GoogleConnectionAccessReason.config_unavailable
        ) from exc
    except Exception as exc:
        raise GoogleConnectionAccessError(
            GoogleConnectionAccessReason.token_unavailable
        ) from exc
