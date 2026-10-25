"""Owner/account authority for encrypted Disk tokens and selected resources."""
from dataclasses import asdict
from datetime import datetime,timezone
import hashlib
import json
import uuid

from sqlalchemy import select

from .models import YandexDiskConnection,YandexDiskResource
from .security import decrypt,encrypt,master_key_from_b64,utcnow
from .yandex_disk import DiskResource,YandexDiskClient,YandexDiskError
from .yandex_disk_oauth import load_config,refresh_tokens


def token_aad(owner_id: str) -> bytes:
    return ("studio:yandex-disk:token:"+owner_id).encode()


def store_tokens(row,*,payload,settings,now=None):
    raw=json.dumps(payload,ensure_ascii=False,separators=(",",":"))
    row.token_ciphertext,row.token_nonce=encrypt(raw,master_key_from_b64(settings.master_key_b64()),token_aad(row.user_id))
    row.key_id=settings.credential_key_id
    row.credential_revision=int(row.credential_revision or 0)+1
    row.updated_at=now or utcnow()


def _tokens(row,settings):
    try:
        payload=json.loads(decrypt(row.token_ciphertext,row.token_nonce,master_key_from_b64(settings.master_key_b64()),token_aad(row.user_id)))
        if (not isinstance(payload,dict) or not isinstance(payload.get("access_token"),str)
                or not payload["access_token"] or not isinstance(payload.get("refresh_token"),str)
                or not payload["refresh_token"]):raise ValueError()
        return payload
    except Exception:raise YandexDiskError("reauthorization_required") from None


def active_connection(db,*,owner_user_id: str, lock=False):
    row=db.get(YandexDiskConnection,owner_user_id,populate_existing=True,with_for_update=lock)
    if row is None or row.status!="active" or not row.token_ciphertext or not row.token_nonce:
        raise YandexDiskError("reauthorization_required")
    return row


def access_token(db,*,user_id: str,settings,now=None,refresher=refresh_tokens):
    current=now or utcnow()
    if current.tzinfo is None:current=current.replace(tzinfo=timezone.utc)
    row=active_connection(db,owner_user_id=user_id);payload=_tokens(row,settings)
    try:check_at=datetime.fromisoformat(payload["check_at"])
    except (KeyError,ValueError,TypeError):raise YandexDiskError("reauthorization_required") from None
    if check_at.tzinfo is None:raise YandexDiskError("reauthorization_required")
    if check_at>current:
        return payload["access_token"]
    revision,account=row.credential_revision,row.account_uid
    db.rollback()  # External token refresh must not hold a runtime DB transaction.
    config=load_config(settings)
    fresh=refresher(config,refresh_token=payload["refresh_token"],now=current)
    row=db.execute(select(YandexDiskConnection).where(YandexDiskConnection.user_id==user_id).with_for_update()).scalar_one_or_none()
    if row is None or row.status!="active" or row.credential_revision!=revision or row.account_uid!=account:
        db.rollback();raise YandexDiskError("connection_changed")
    store_tokens(row,payload=fresh,settings=settings,now=current)
    db.commit()
    return fresh["access_token"]


def resource_fingerprint(resource: DiskResource) -> str:
    if resource.is_folder:
        identity=(resource.path,resource.resource_id,resource.created)
    else:
        identity=(resource.path,resource.resource_id,resource.created,resource.modified,
                  resource.size_bytes,resource.md5,resource.sha256)
    return hashlib.sha256(json.dumps(identity,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()


def register_resource(db,*,owner_user_id: str,resource: DiskResource,expected_connection=None):
    connection=active_connection(db,owner_user_id=owner_user_id,lock=True)
    if expected_connection is not None and (connection.account_uid,connection.credential_revision)!=expected_connection:
        raise YandexDiskError("connection_changed")
    version=resource_fingerprint(resource)
    identity=str(uuid.uuid5(uuid.NAMESPACE_URL,"studio:yandex-disk:"+owner_user_id+":"+connection.account_uid+":"+version))
    row=db.get(YandexDiskResource,identity)
    if row is None:
        row=YandexDiskResource(id=identity,owner_user_id=owner_user_id,account_uid=connection.account_uid,
            path=resource.path,is_folder=resource.is_folder,version_fingerprint=version,
            metadata_json=json.dumps(asdict(resource),ensure_ascii=False))
        db.add(row);db.flush()
    return row


def selected_resource(db,*,owner_user_id: str,resource_id: str,is_folder: bool|None=None):
    connection=active_connection(db,owner_user_id=owner_user_id)
    row=db.get(YandexDiskResource,resource_id)
    if (row is None or row.owner_user_id!=owner_user_id or row.account_uid!=connection.account_uid
            or (is_folder is not None and row.is_folder!=is_folder)):
        raise YandexDiskError("resource_unavailable")
    return row


def verify_selected_resource(db,*,owner_user_id: str,resource_id: str,settings,is_folder: bool|None=None,client_factory=YandexDiskClient):
    row=selected_resource(db,owner_user_id=owner_user_id,resource_id=resource_id,is_folder=is_folder)
    path,version,account=row.path,row.version_fingerprint,row.account_uid
    token=access_token(db,user_id=owner_user_id,settings=settings)
    revision=active_connection(db,owner_user_id=owner_user_id).credential_revision
    db.rollback()
    current=client_factory(token).metadata(path)
    row=selected_resource(db,owner_user_id=owner_user_id,resource_id=resource_id,is_folder=is_folder)
    if (row.account_uid!=account or row.version_fingerprint!=version or resource_fingerprint(current)!=version
            or active_connection(db,owner_user_id=owner_user_id).credential_revision!=revision):
        raise YandexDiskError("resource_changed")
    return current
