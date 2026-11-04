"""Pairing is session/CSRF/step-up protected; companion routes accept only its token."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from sqlalchemy import select

from .audit import audit
from .db import get_db
from .deps import current_session, require_csrf
from .local_execution_devices import (
    authenticate_device, device_payload, owned_device, pair_device, revoke_device, rotate_device,
)
from .models import LocalExecutionDevice
from .nemotron_local_result import NEMOTRON_MODEL
from .security import utcnow

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class DevicePairIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=80)
    creation_key: UUID

    @field_validator("label")
    @classmethod
    def clean_label(cls, value):
        value = value.strip()
        if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Некорректное название компьютера")
        return value


class DeviceRevisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: StrictInt = Field(ge=1, le=2147483646)


class DeviceHeartbeatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runtime_status: Literal["ready", "model_missing", "runtime_missing", "runtime_error"]
    runtime_version: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9.+_-]+$")
    model: Literal[NEMOTRON_MODEL] | None = None


def companion_device(request: Request, db=Depends(get_db)):
    # No cookies, browser trusted-device bypass, CORS, or user/provider key fallback.
    if request.headers.get("origin") or request.headers.get("x-voiceops-local-protocol") != "1":
        raise HTTPException(403, detail={"reason": "local_device_protocol_required"}, headers=NO_STORE)
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer ") or len(authorization) > 264:
        raise HTTPException(401, detail={"reason": "local_device_unauthorized"}, headers=NO_STORE)
    try:
        device = authenticate_device(db, authorization[7:])
    except HTTPException as error:
        error.headers = NO_STORE
        raise
    request.state.owner_user_id = device.owner_user_id
    return device


def build_router(*, recent_auth, limiter):
    router = APIRouter()

    @router.get("/api/local-execution/devices")
    def devices(response: Response, pair=Depends(current_session), db=Depends(get_db)):
        response.headers.update(NO_STORE)
        rows = db.scalars(select(LocalExecutionDevice).where(
            LocalExecutionDevice.owner_user_id == pair[1].id, LocalExecutionDevice.revoked_at.is_(None)
        ).order_by(LocalExecutionDevice.created_at, LocalExecutionDevice.id)).all()
        return {"devices": [device_payload(row, now=utcnow()) for row in rows]}

    @router.post("/api/local-execution/devices")
    def pair(data: DevicePairIn, request: Request, response: Response,
             pair=Depends(require_csrf), db=Depends(get_db)):
        _, user = recent_auth(pair, request=request, db=db)
        limiter.check("local-device:pair:" + user.id, 10, 3600)
        row, secret = pair_device(db, owner_user_id=user.id, label=data.label,
            creation_key=str(data.creation_key), now=utcnow())
        if secret is not None:
            audit(db, "local_device.paired", actor_user_id=user.id, subject_user_id=user.id, device_id=row.id)
        db.commit()
        response.headers.update(NO_STORE)
        return {"device": device_payload(row, now=utcnow()), "pairing_token": secret,
                "token_available_once": secret is not None}

    @router.post("/api/local-execution/devices/{device_id}/rotate")
    def rotate(device_id: UUID, data: DeviceRevisionIn, request: Request, response: Response,
               pair=Depends(require_csrf), db=Depends(get_db)):
        _, user = recent_auth(pair, request=request, db=db)
        limiter.check("local-device:rotate:" + user.id, 10, 3600)
        row = owned_device(db, owner_user_id=user.id, device_id=str(device_id), lock=True)
        secret = rotate_device(row, expected_revision=data.expected_revision, now=utcnow())
        audit(db, "local_device.rotated", actor_user_id=user.id, subject_user_id=user.id, device_id=row.id)
        db.commit()
        response.headers.update(NO_STORE)
        return {"device": device_payload(row, now=utcnow()), "pairing_token": secret, "token_available_once": True}

    @router.post("/api/local-execution/devices/{device_id}/revoke")
    def revoke(device_id: UUID, data: DeviceRevisionIn, request: Request, response: Response,
               pair=Depends(require_csrf), db=Depends(get_db)):
        _, user = recent_auth(pair, request=request, db=db)
        limiter.check("local-device:revoke:" + user.id, 10, 3600)
        row = owned_device(db, owner_user_id=user.id, device_id=str(device_id), lock=True)
        if revoke_device(row, expected_revision=data.expected_revision, now=utcnow()):
            audit(db, "local_device.revoked", actor_user_id=user.id, subject_user_id=user.id, device_id=row.id)
        db.commit()
        response.headers.update(NO_STORE)
        return {"device": device_payload(row, now=utcnow())}

    @router.post("/api/local-execution/companion/heartbeat")
    def heartbeat(data: DeviceHeartbeatIn, response: Response,
                  device=Depends(companion_device), db=Depends(get_db)):
        limiter.check("local-device:heartbeat:" + device.id, 120, 60)
        if data.runtime_status == "ready" and (data.model != NEMOTRON_MODEL or data.runtime_version is None):
            raise HTTPException(422, detail={"reason": "local_runtime_identity_required"}, headers=NO_STORE)
        device.runtime_status, device.runtime_version, device.model = data.runtime_status, data.runtime_version, data.model
        device.last_seen_at = device.updated_at = utcnow()
        db.commit()
        response.headers.update(NO_STORE)
        return {"device": device_payload(device, now=utcnow()), "protocol": 1}

    return router
