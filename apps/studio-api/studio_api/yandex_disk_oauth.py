"""Confidential, PKCE-bound Disk OAuth; tokens never enter browser DTOs."""
import base64
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
from urllib.parse import urlencode

import httpx

from .security import master_key_from_b64
from .yandex_disk import YandexDiskError

AUTHORIZE_URL="https://oauth.yandex.ru/authorize"
TOKEN_URL="https://oauth.yandex.ru/token"
REVOKE_URL="https://oauth.yandex.ru/revoke_token"
SCOPES="cloud_api:disk.read cloud_api:disk.write cloud_api:disk.info"


@dataclass(frozen=True)
class YandexOAuthConfig:
    client_id: str
    client_secret: str=field(repr=False)
    redirect_uri: str


def load_config(settings) -> YandexOAuthConfig:
    identity=(getattr(settings,"yandex_disk_oauth_client_id",None) or "").strip()
    file=getattr(settings,"yandex_disk_oauth_client_secret_file",None)
    if not identity or len(identity)>200 or any(ord(c)<33 for c in identity) or not file:
        raise YandexDiskError("configuration_unavailable")
    try:secret=Path(file).read_text(encoding="utf-8").strip()
    except (OSError,UnicodeError):raise YandexDiskError("configuration_unavailable") from None
    if not secret or len(secret)>4096 or any(ord(c)<33 for c in secret):
        raise YandexDiskError("configuration_unavailable")
    return YandexOAuthConfig(identity,secret,settings.app_origin.rstrip("/")+"/api/yandex/oauth/callback")


def pkce_verifier(state: str,master_key_b64: str) -> str:
    # Only the opaque nonce is stored/passed via OAuth. A stolen nonce alone
    # does not reveal the verifier; changing the server key invalidates the flow.
    digest=hmac.new(master_key_from_b64(master_key_b64),b"studio:yandex-disk:pkce:"+state.encode(),hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def authorization_url(config: YandexOAuthConfig,*,state: str,verifier: str,device_id: str) -> str:
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return AUTHORIZE_URL+"?"+urlencode(dict(response_type="code",client_id=config.client_id,
        redirect_uri=config.redirect_uri,scope=SCOPES,state=state,code_challenge=challenge,
        code_challenge_method="S256",force_confirm="yes",device_id=device_id,device_name="VoiceOps Studio"))


def _post_form(url: str,form: dict,*,client=None):
    owned=client is None
    client=client or httpx.Client(timeout=10,follow_redirects=False,trust_env=False)
    try:
        with client.stream("POST",url,data=form,follow_redirects=False) as response:
            if response.status_code in (400,401,403):raise YandexDiskError("authentication_rejected")
            if not 200<=response.status_code<300:raise YandexDiskError("unavailable")
            raw=bytearray()
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw)>65536:raise YandexDiskError("malformed_response")
            result=json.loads(raw)
            if not isinstance(result,dict):raise YandexDiskError("malformed_response")
            return result
    except httpx.TimeoutException:raise YandexDiskError("timeout") from None
    except httpx.HTTPError:raise YandexDiskError("unavailable") from None
    except (ValueError,UnicodeError):raise YandexDiskError("malformed_response") from None
    finally:
        if owned:client.close()


def token_payload(payload: dict,*,now: datetime) -> dict:
    access=payload.get("access_token");refresh=payload.get("refresh_token")
    expires=payload.get("expires_in");scopes=payload.get("scope",SCOPES)
    if (not isinstance(access,str) or not 1<=len(access)<=8192 or any(ord(c)<33 for c in access)
            or not isinstance(refresh,str) or not 1<=len(refresh)<=8192
            or any(ord(c)<33 for c in refresh)
            or type(expires) is not int or not 1<=expires<=2**63-1
            or not isinstance(scopes,str) or len(scopes)>8192 or not set(SCOPES.split())<=set(scopes.split())):
        raise YandexDiskError("scope_or_token_unavailable")
    current=now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    # Refresh at least quarterly as recommended by the provider. A huge
    # expires_in must not overflow datetime or keep a credential unchecked.
    check_at=current+timedelta(seconds=min(expires,90*86400))
    return {"access_token":access,"refresh_token":refresh,"check_at":check_at.isoformat(),"scopes":scopes}


def exchange_code(config: YandexOAuthConfig,*,code: str,verifier: str,now: datetime,client=None):
    payload=_post_form(TOKEN_URL,dict(grant_type="authorization_code",code=code,client_id=config.client_id,
        client_secret=config.client_secret,redirect_uri=config.redirect_uri,code_verifier=verifier),client=client)
    return token_payload(payload,now=now)


def refresh_tokens(config: YandexOAuthConfig,*,refresh_token: str,now: datetime,client=None):
    return token_payload(_post_form(TOKEN_URL,dict(grant_type="refresh_token",refresh_token=refresh_token,
        client_id=config.client_id,client_secret=config.client_secret),client=client),now=now)


def revoke_token(config: YandexOAuthConfig,*,access_token: str,client=None) -> bool:
    result=_post_form(REVOKE_URL,dict(access_token=access_token,client_id=config.client_id,
        client_secret=config.client_secret),client=client)
    return result.get("status")=="ok"
