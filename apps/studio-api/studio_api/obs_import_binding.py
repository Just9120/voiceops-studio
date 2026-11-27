"""Enroll a Windows recorder with access limited to submitting OBS audio."""
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select

from .audit import audit
from .client_ip import get_client_ip
from .config import get_settings
from .db import get_db
from .deps import current_session, require_csrf
from .local_device_enrollment import DeviceEnrollment, PAIRING_SECONDS
from .local_execution_routes import (
    NO_STORE, DeviceEnrollmentFinishIn, DeviceEnrollmentStartIn, require_companion_enrollment_request,
)
from .models import ObsImportBinding, User, UserStatus
from .security import safe_eq, token_hash, utcnow


_TOKEN = re.compile(r"Bearer vs-obs\.([0-9a-f-]{36})\.([A-Za-z0-9_-]{43})", re.ASCII | re.IGNORECASE)


def authenticate_recorder(request: Request, db=Depends(get_db)):
    require_companion_enrollment_request(request)
    match = _TOKEN.fullmatch(request.headers.get("authorization", ""))
    if match:
        binding = db.execute(select(ObsImportBinding).where(
            ObsImportBinding.id == match[1], ObsImportBinding.revoked_at.is_(None),
        ).with_for_update()).scalar_one_or_none()
        if binding is not None and safe_eq(binding.verifier_hash, token_hash(match[2])):
            user = db.get(User, binding.owner_user_id)
            if user is not None and user.status == UserStatus.active:
                request.state.owner_user_id = user.id
                return user
    raise HTTPException(401, "Привяжите импорт OBS в Studio", headers=NO_STORE)


def _binding_payload(binding):
    return {"id": binding.id, "label": binding.label, "created_at": binding.created_at.isoformat()}


def build_router(*, recent_auth, limiter):
    router = APIRouter(prefix="/api/obs-import")
    def enrollment():
        return DeviceEnrollment(limiter.redis, namespace="obs-import")

    @router.post("/enrollment")
    def start(data: DeviceEnrollmentStartIn, request: Request, response: Response):
        require_companion_enrollment_request(request)
        limiter.check("obs-import:enrollment-start:" + get_client_ip(request, get_settings()), 12, 300)
        response.headers.update(NO_STORE)
        return {"request_id": enrollment().begin(data.label, data.challenge), "expires_in": PAIRING_SECONDS}

    @router.get("/enrollment/{request_id}")
    def view(request_id: UUID, response: Response, pair=Depends(current_session)):
        limiter.check("obs-import:enrollment-view:" + pair[1].id, 60, 60)
        response.headers.update(NO_STORE)
        return enrollment().browser_view(request_id, pair[1].id)

    @router.post("/enrollment/{request_id}/approve")
    def approve(request_id: UUID, request: Request, response: Response, pair=Depends(require_csrf), db=Depends(get_db)):
        _, user = recent_auth(pair, request=request, db=db)
        limiter.check("obs-import:enrollment-approve:" + user.id, 20, 300)
        response.headers.update(NO_STORE)
        return enrollment().approve(request_id, user.id)

    @router.post("/enrollment/{request_id}/finish")
    def finish(request_id: UUID, data: DeviceEnrollmentFinishIn, request: Request, response: Response, db=Depends(get_db)):
        require_companion_enrollment_request(request)
        limiter.check("obs-import:enrollment-finish:" + get_client_ip(request, get_settings()), 120, 300)
        label, owner_id = enrollment().verify(request_id, data.verifier)
        response.headers.update(NO_STORE)
        if owner_id is None:
            response.status_code = 202
            return {"status": "pending"}
        user = db.execute(select(User).where(User.id == owner_id).with_for_update()).scalar_one_or_none()
        if user is None or user.status != UserStatus.active:
            raise HTTPException(404, "Не найдено", headers=NO_STORE)
        binding_id = str(request_id)
        verifier_hash = token_hash(data.verifier)
        binding = db.get(ObsImportBinding, binding_id)
        if binding is None:
            binding = ObsImportBinding(id=binding_id, owner_user_id=user.id, label=label, verifier_hash=verifier_hash)
            db.add(binding)
            audit(db, "obs_import.paired", actor_user_id=user.id, subject_user_id=user.id, binding_id=binding_id)
        elif binding.revoked_at is not None or binding.owner_user_id != user.id or not safe_eq(binding.verifier_hash, verifier_hash):
            raise HTTPException(404, "Не найдено", headers=NO_STORE)
        db.commit()
        return {"status": "connected", "device": _binding_payload(binding)}

    @router.get("/bindings")
    def bindings(response: Response, pair=Depends(current_session), db=Depends(get_db)):
        response.headers.update(NO_STORE)
        rows = db.scalars(select(ObsImportBinding).where(
            ObsImportBinding.owner_user_id == pair[1].id, ObsImportBinding.revoked_at.is_(None),
        ).order_by(ObsImportBinding.created_at, ObsImportBinding.id)).all()
        return {"bindings": [_binding_payload(row) for row in rows]}

    @router.delete("/bindings/{binding_id}")
    def revoke(binding_id: UUID, request: Request, response: Response, pair=Depends(require_csrf), db=Depends(get_db)):
        _, user = recent_auth(pair, request=request, db=db)
        response.headers.update(NO_STORE)
        binding = db.execute(select(ObsImportBinding).where(
            ObsImportBinding.id == str(binding_id), ObsImportBinding.owner_user_id == user.id,
        ).with_for_update()).scalar_one_or_none()
        if binding is None:
            raise HTTPException(404, "Не найдено", headers=NO_STORE)
        if binding.revoked_at is None:
            binding.revoked_at = utcnow()
            audit(db, "obs_import.revoked", actor_user_id=user.id, subject_user_id=user.id, binding_id=binding.id)
        db.commit()
        return {"ok": True}

    return router
