"""Owner pairing and narrow machine authentication; never a general user session."""
from datetime import timedelta, timezone
import hashlib
import hmac
import re
import secrets
import uuid

from fastapi import HTTPException
from sqlalchemy import select

from .models import LocalExecutionDevice, User, UserStatus
from .local_model_identity import INITIAL_MODEL_REVISIONS, is_supported_model_revision

DEVICE_ONLINE_SECONDS = 90
MAX_ACTIVE_DEVICES = 8
_TOKEN = re.compile(r"vs-local\.([0-9a-f-]{36})\.([A-Za-z0-9_-]{43})\Z")


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _secret(device_id):
    raw = f"vs-local.{device_id}.{secrets.token_urlsafe(32)}"
    return raw, hashlib.sha256(raw.encode("ascii")).hexdigest()


def device_model_identity(row):
    # Rows written before explicit revision tracking can only represent the
    # original revision. A later catalog promotion must not change their meaning.
    return row.model, row.model_revision or INITIAL_MODEL_REVISIONS.get(row.model)


def device_payload(row, *, now):
    online = bool(row.revoked_at is None and row.last_seen_at is not None
                  and _utc(now) - timedelta(seconds=DEVICE_ONLINE_SECONDS) <= _utc(row.last_seen_at) <= _utc(now))
    model, revision = device_model_identity(row)
    return {"id": row.id, "label": row.label, "credential_revision": row.credential_revision,
            "online": online, "ready": bool(online and row.runtime_status == "ready" and is_supported_model_revision(model, revision)),
            "runtime_status": row.runtime_status, "runtime_version": row.runtime_version, "model": model,
            "model_revision": revision,
            "last_seen_at": _utc(row.last_seen_at).isoformat() if row.last_seen_at else None,
            "revoked_at": _utc(row.revoked_at).isoformat() if row.revoked_at else None}


def pair_device(db, *, owner_user_id, label, creation_key, now, enrollment_verifier=None):
    # Same owner lock serializes the count and idempotency decision on PostgreSQL.
    owner = db.scalar(select(User).where(User.id == owner_user_id, User.status == UserStatus.active).with_for_update())
    if owner is None:
        raise HTTPException(404, "Не найдено")
    existing = db.scalar(select(LocalExecutionDevice).where(
        LocalExecutionDevice.owner_user_id == owner_user_id, LocalExecutionDevice.creation_key == creation_key))
    if existing is not None:
        if existing.label != label:
            raise HTTPException(409, detail={"reason": "local_device_request_changed"})
        if enrollment_verifier is not None:
            expected = hashlib.sha256(f"vs-local.{creation_key}.{enrollment_verifier}".encode("ascii")).hexdigest()
            if existing.id != creation_key or existing.revoked_at is not None or not hmac.compare_digest(existing.token_hash, expected):
                raise HTTPException(409, detail={"reason": "local_device_changed"})
        # Secrets cannot be recovered. A lost response requires explicit rotation.
        return existing, None
    rows = db.scalars(select(LocalExecutionDevice.id).where(
        LocalExecutionDevice.owner_user_id == owner_user_id, LocalExecutionDevice.revoked_at.is_(None))
        .limit(MAX_ACTIVE_DEVICES)).all()
    if len(rows) >= MAX_ACTIVE_DEVICES:
        raise HTTPException(409, detail={"reason": "local_device_limit"})
    if enrollment_verifier is None:
        device_id = str(uuid.uuid4())
        raw, digest = _secret(device_id)
    else:
        device_id = creation_key
        raw = f"vs-local.{device_id}.{enrollment_verifier}"
        digest = hashlib.sha256(raw.encode("ascii")).hexdigest()
    row = LocalExecutionDevice(id=device_id, owner_user_id=owner_user_id, label=label,
        creation_key=creation_key, token_hash=digest, credential_revision=1, runtime_status="unknown",
        created_at=now, updated_at=now)
    db.add(row)
    db.flush()
    return row, raw


def owned_device(db, *, owner_user_id, device_id, lock=False):
    query = select(LocalExecutionDevice).where(LocalExecutionDevice.id == device_id,
        LocalExecutionDevice.owner_user_id == owner_user_id)
    row = db.scalar((query.with_for_update() if lock else query).execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(404, "Не найдено")
    return row


def require_ready_device(db, *, owner_user_id, device_id, now, model, revision, lock=False):
    if not device_id:
        raise HTTPException(422, detail={"reason": "local_device_required"})
    row = owned_device(db, owner_user_id=owner_user_id, device_id=device_id, lock=lock)
    if not device_payload(row, now=now)["ready"]:
        raise HTTPException(409, detail={"reason": "local_device_not_ready"})
    if device_model_identity(row) != (model, revision):
        raise HTTPException(409, detail={"reason": "local_device_model_changed"})
    return row


def rotate_device(row, *, expected_revision, now):
    if row.revoked_at is not None or row.credential_revision != expected_revision:
        raise HTTPException(409, detail={"reason": "local_device_changed"})
    raw, row.token_hash = _secret(row.id)
    row.credential_revision += 1
    row.last_seen_at = None
    row.runtime_status = "unknown"
    row.runtime_version = row.model = row.model_revision = None
    row.updated_at = now
    return raw


def revoke_device(row, *, expected_revision, now):
    if row.revoked_at is not None:
        return False
    if row.credential_revision != expected_revision:
        raise HTTPException(409, detail={"reason": "local_device_changed"})
    row.revoked_at = row.updated_at = now
    row.credential_revision += 1
    row.token_hash = "revoked"  # No usable capability remains in this record.
    return True


def authenticate_device(db, raw):
    match = _TOKEN.fullmatch(raw) if isinstance(raw, str) else None
    row = None
    if match is not None:
        try:
            device_id = str(uuid.UUID(match[1]))
        except ValueError:
            device_id = ""
        if device_id == match[1]:
            row = db.scalar(select(LocalExecutionDevice).where(LocalExecutionDevice.id == device_id)
                            .with_for_update().execution_options(populate_existing=True))
    supplied = hashlib.sha256(raw.encode("utf-8")).hexdigest() if isinstance(raw, str) and len(raw) <= 256 else ""
    valid = hmac.compare_digest(row.token_hash if row else "0" * 64, supplied)
    owner = db.get(User, row.owner_user_id) if row is not None and valid else None
    if row is None or not valid or row.revoked_at is not None or owner is None or owner.status != UserStatus.active:
        raise HTTPException(401, detail={"reason": "local_device_unauthorized"})
    return row
