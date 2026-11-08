"""Pairing is session/CSRF/step-up protected; companion routes accept only its token."""
from typing import Literal
import json
from uuid import UUID, uuid4
from contextlib import ExitStack
from functools import partial

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, field_validator, model_validator
from redis.exceptions import RedisError
from sqlalchemy import select

from .audit import audit
from .companion_release import INSTALLER, available_release
from .db import get_db
from .config import get_settings
from .client_ip import get_client_ip
from .deps import current_session, require_csrf
from .local_device_enrollment import DeviceEnrollment, PAIRING_SECONDS
from .local_model_catalog import CatalogUnavailable, catalog_page
from .local_model_identity import INITIAL_MODEL_REVISIONS, LEGACY_NEMOTRON_REVISION, MODEL_REVISIONS, PARAKEET_MODEL, is_supported_model_revision
from .local_execution_devices import (
    authenticate_device, device_model_identity, device_payload, owned_device, pair_device, revoke_device, rotate_device,
)
from .models import LocalExecutionDevice
from .nemotron_local_result import NEMOTRON_MODEL
from .security import utcnow
from .trace_context import new_trace_id, set_current_trace_id, valid_trace_id
from .local_execution_jobs import claim_local_job, device_model_in_use, fail_local_job, fence_device_jobs, heartbeat_local_job, local_job_payload
from .local_execution_transfer import accept_local_result, decode_local_result, open_local_input, prepare_local_input

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class DeviceLabelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=80)

    @field_validator("label")
    @classmethod
    def clean_label(cls, value):
        value = value.strip()
        if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Некорректное название компьютера")
        return value


class DevicePairIn(DeviceLabelIn):
    creation_key: UUID


class DeviceRevisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: StrictInt = Field(ge=1, le=2147483646)


class DeviceEnrollmentStartIn(DeviceLabelIn):
    challenge: str = Field(pattern=r"^[a-f0-9]{64}$")


class DeviceEnrollmentFinishIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verifier: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")



class DeviceHeartbeatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runtime_status: Literal["loading_model", "ready", "model_missing", "runtime_missing", "runtime_error"]
    runtime_version: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9.+_-]+$")
    model: Literal[NEMOTRON_MODEL, PARAKEET_MODEL] | None = None
    model_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")


class LocalGPUIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    vram_bytes: StrictInt | None = Field(default=None, gt=0, le=2**50)


class LocalModelProbeIn(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    model: Literal[NEMOTRON_MODEL, PARAKEET_MODEL]
    audio_seconds: StrictFloat | StrictInt = Field(gt=0, le=60)
    elapsed_seconds: StrictFloat | StrictInt = Field(gt=0, le=10800)


class LocalModelVersionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: Literal[NEMOTRON_MODEL, PARAKEET_MODEL]
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")


class LocalModelInventoryVersionIn(LocalModelVersionIn):
    verified: StrictBool
    probe: LocalModelProbeIn | None = None

    @model_validator(mode="after")
    def validate_version(self):
        if (not is_supported_model_revision(self.model, self.revision)
                or (self.probe is not None and (not self.verified or self.probe.model != self.model))):
            raise ValueError("Invalid model version inventory")
        return self


class LocalInventoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cpu: str = Field(min_length=1, max_length=120)
    cpu_threads: StrictInt | None = Field(default=None, ge=1, le=4096)
    ram_bytes: StrictInt | None = Field(default=None, gt=0, le=2**50)
    gpus: list[LocalGPUIn] = Field(max_length=8)
    disk_free_bytes: StrictInt | None = Field(default=None, ge=0, le=2**60)
    execution: list[Literal["cpu"]] = Field(max_length=1)
    installed: list[Literal[NEMOTRON_MODEL, PARAKEET_MODEL]] = Field(max_length=2)
    verified_installations: list[Literal[NEMOTRON_MODEL, PARAKEET_MODEL]] = Field(default_factory=list, max_length=2)
    probes: list[LocalModelProbeIn] = Field(default_factory=list, max_length=2)
    model_versions: list[LocalModelInventoryVersionIn] | None = Field(default=None, max_length=16)

    @field_validator("model_versions")
    @classmethod
    def unique_versions(cls, value):
        if value is not None and len({(item.model, item.revision) for item in value}) != len(value):
            raise ValueError("Duplicate model version")
        return value


def _inventory_key(device):
    return f"local-device:inventory:{device.id}:{device.credential_revision}"


def _model_request_key(device):
    return f"local-device:model-request:{device.id}:{device.credential_revision}"


class LocalJobHeartbeatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation: StrictInt = Field(ge=1, le=2147483647)
    sequence: StrictInt = Field(ge=1, le=2147483647)
    stage: Literal["source_download", "media_processing", "local_transcription", "local_result_upload"]
    completed: StrictFloat | StrictInt | None = None
    total: StrictFloat | StrictInt | None = None
    unit: Literal["bytes", "seconds"] | None = None


class LocalJobFailureIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation: StrictInt = Field(ge=1, le=2147483647)
    reason: Literal["local_input_unavailable", "local_model_unavailable", "local_runtime_unavailable",
                    "local_processing_failed", "local_worker_interrupted", "local_result_invalid"]


class LocalInputPrepareIn(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    generation: StrictInt = Field(ge=1, le=2147483647)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_duration_seconds: StrictFloat | StrictInt = Field(gt=0, le=604800)


class LocalInputResponse(StreamingResponse):
    def __init__(self, stream, *, cleanup, headers):
        super().__init__(stream, media_type="application/octet-stream", headers=headers)
        self.cleanup = cleanup

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Runs also when the client disconnects before the first byte.
            await run_in_threadpool(self.cleanup)


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


def _bind_job_trace(request, job):
    # Called only after owner, device and lease (or exact result replay) are checked.
    if not valid_trace_id(job.trace_id):
        job.trace_id = new_trace_id()
    request.state.job_trace_id = job.trace_id
    set_current_trace_id(job.trace_id)


def require_companion_enrollment_request(request):
    if request.headers.get("origin") or request.headers.get("x-voiceops-local-protocol") != "1":
        raise HTTPException(403, detail={"reason": "local_device_protocol_required"}, headers=NO_STORE)


def build_router(*, recent_auth, limiter):
    router = APIRouter()

    @router.get("/api/local-execution/companion-release")
    def companion_release(response: Response, pair=Depends(current_session), settings=Depends(get_settings)):
        response.headers.update(NO_STORE)
        return available_release(settings, pair[1].id).metadata()

    @router.get("/api/local-execution/companion-release/{sha256}/download")
    def companion_download(sha256: str, pair=Depends(current_session), settings=Depends(get_settings)):
        release = available_release(settings, pair[1].id)
        if sha256 != release.sha256:
            raise HTTPException(404, "Эта сборка больше недоступна", headers=NO_STORE)
        return FileResponse(release.path, media_type="application/octet-stream", filename=INSTALLER,
                            headers={**NO_STORE, "X-Content-Type-Options": "nosniff"})

    @router.get("/api/local-execution/catalog")
    def catalog(response: Response, search: str = Query(default="", max_length=120),
                language: str = Query(default="", pattern=r"^(?:[a-z]{2,3})?$"),
                sort: Literal["downloads", "likes"] = "downloads",
                supported: bool = False,
                cursor: str = Query(default="", pattern=r"^[A-Za-z0-9_+/=-]{0,1024}$"),
                pair=Depends(current_session)):
        limiter.check("local-device:catalog:" + pair[1].id, 30, 60)
        response.headers.update(NO_STORE)
        try:
            return catalog_page(search=search, language=language, sort=sort, cursor=cursor, supported=supported)
        except CatalogUnavailable:
            raise HTTPException(503, "Каталог Hugging Face временно недоступен", headers=NO_STORE) from None

    @router.get("/api/local-execution/devices/{device_id}/inventory")
    def read_inventory(device_id: UUID, response: Response, pair=Depends(current_session), db=Depends(get_db)):
        row = owned_device(db, owner_user_id=pair[1].id, device_id=str(device_id))
        if row.revoked_at is not None:
            raise HTTPException(404, "Не найдено", headers=NO_STORE)
        limiter.check("local-device:inventory-read:" + pair[1].id, 30, 60)
        response.headers.update(NO_STORE)
        try:
            raw = limiter.redis.get(_inventory_key(row))
        except RedisError:
            raise HTTPException(503, "Сведения о компьютере временно недоступны", headers=NO_STORE) from None
        inventory = json.loads(raw) if raw is not None else None
        if inventory is not None and inventory.get("model_versions") is None:
            verified = set(inventory.get("verified_installations", []))
            probes = {item["model"]: item for item in inventory.get("probes", [])}
            inventory["model_versions"] = [{
                "model": model, "revision": INITIAL_MODEL_REVISIONS[model], "verified": model in verified,
                "probe": probes.get(model) if model in verified else None,
            } for model in dict.fromkeys(inventory["installed"])]
        return {"inventory": inventory}

    @router.post("/api/local-execution/devices/{device_id}/model-install")
    def request_model_install(device_id: UUID, data: LocalModelVersionIn, response: Response,
                              pair=Depends(require_csrf), db=Depends(get_db)):
        row = owned_device(db, owner_user_id=pair[1].id, device_id=str(device_id), lock=True)
        if row.revoked_at is not None:
            raise HTTPException(404, "Не найдено", headers=NO_STORE)
        if data.revision != MODEL_REVISIONS[data.model]:
            raise HTTPException(422, "Эта версия не поддерживается", headers=NO_STORE)
        limiter.check("local-device:model-request:" + pair[1].id, 20, 60)
        key = _model_request_key(row)
        try:
            raw = limiter.redis.get(key)
            if raw is not None:
                existing = json.loads(raw)
                if existing["model"] != data.model or existing["revision"] != data.revision:
                    raise HTTPException(409, "На ПК уже ожидает другой запрос установки", headers=NO_STORE)
            else:
                limiter.redis.set(key, json.dumps({"id": str(uuid4()), **data.model_dump()}), ex=300)
        except RedisError:
            raise HTTPException(503, "Не удалось отправить запрос на ПК", headers=NO_STORE) from None
        response.headers.update(NO_STORE)
        return {"pending": True}

    @router.post("/api/local-execution/enrollment")
    def begin_enrollment(data: DeviceEnrollmentStartIn, request: Request, response: Response):
        require_companion_enrollment_request(request)
        limiter.check("local-device:enrollment-start:" + get_client_ip(request, get_settings()), 12, 300)
        request_id = DeviceEnrollment(limiter.redis).begin(data.label, data.challenge)
        response.headers.update(NO_STORE)
        return {"request_id": request_id, "expires_in": PAIRING_SECONDS}

    @router.get("/api/local-execution/enrollment/{request_id}")
    def enrollment_view(request_id: UUID, response: Response, pair=Depends(current_session)):
        limiter.check("local-device:enrollment-view:" + pair[1].id, 60, 60)
        response.headers.update(NO_STORE)
        return DeviceEnrollment(limiter.redis).browser_view(request_id, pair[1].id)

    @router.post("/api/local-execution/enrollment/{request_id}/approve")
    def approve_enrollment(request_id: UUID, request: Request, response: Response,
                           pair=Depends(require_csrf), db=Depends(get_db)):
        _, user = recent_auth(pair, request=request, db=db)
        limiter.check("local-device:enrollment-approve:" + user.id, 20, 300)
        response.headers.update(NO_STORE)
        return DeviceEnrollment(limiter.redis).approve(request_id, user.id)

    @router.post("/api/local-execution/enrollment/{request_id}/finish")
    def finish_enrollment(request_id: UUID, data: DeviceEnrollmentFinishIn, request: Request,
                          response: Response, db=Depends(get_db)):
        require_companion_enrollment_request(request)
        limiter.check("local-device:enrollment-finish:" + get_client_ip(request, get_settings()), 120, 300)
        label, owner_id = DeviceEnrollment(limiter.redis).verify(request_id, data.verifier)
        response.headers.update(NO_STORE)
        if owner_id is None:
            response.status_code = 202
            return {"status": "pending"}
        now = utcnow()
        row, first_secret = pair_device(db, owner_user_id=owner_id, label=label,
            creation_key=str(request_id), now=now, enrollment_verifier=data.verifier)
        if first_secret is not None:
            audit(db, "local_device.paired", actor_user_id=owner_id, subject_user_id=owner_id, device_id=row.id)
        db.commit()
        return {"status": "connected", "device": device_payload(row, now=now)}

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
        fence_device_jobs(db, device_id=row.id, owner_user_id=user.id, now=utcnow())
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
            fence_device_jobs(db, device_id=row.id, owner_user_id=user.id, now=utcnow())
            audit(db, "local_device.revoked", actor_user_id=user.id, subject_user_id=user.id, device_id=row.id)
        db.commit()
        response.headers.update(NO_STORE)
        return {"device": device_payload(row, now=utcnow())}

    @router.post("/api/local-execution/companion/heartbeat")
    def heartbeat(data: DeviceHeartbeatIn, response: Response,
                  device=Depends(companion_device), db=Depends(get_db)):
        limiter.check("local-device:heartbeat:" + device.id, 120, 60)
        revision = data.model_revision
        if revision is None and data.model == NEMOTRON_MODEL:
            revision = LEGACY_NEMOTRON_REVISION
        if ((revision is not None and not is_supported_model_revision(data.model, revision))
                or (data.runtime_status == "ready" and (revision is None or data.runtime_version is None))):
            raise HTTPException(422, detail={"reason": "local_runtime_identity_required"}, headers=NO_STORE)
        active = device_model_identity(device)
        if active[0] is not None and (data.model, revision) != active and device_model_in_use(db, device, *active, active_only=True):
            raise HTTPException(409, detail={"reason": "local_model_in_use"}, headers=NO_STORE)
        device.runtime_status, device.runtime_version, device.model = data.runtime_status, data.runtime_version, data.model
        device.model_revision = revision
        device.last_seen_at = device.updated_at = utcnow()
        db.commit()
        response.headers.update(NO_STORE)
        return {"device": device_payload(device, now=utcnow()), "protocol": 1}

    @router.post("/api/local-execution/companion/inventory")
    def report_inventory(data: LocalInventoryIn, response: Response, device=Depends(companion_device)):
        limiter.check("local-device:inventory:" + device.id, 10, 60)
        response.headers.update(NO_STORE)
        try:
            limiter.redis.set(_inventory_key(device), json.dumps({
                **data.model_dump(), "checked_at": utcnow().isoformat()
            }), ex=300)
        except RedisError:
            raise HTTPException(503, "Сведения о компьютере временно недоступны", headers=NO_STORE) from None
        return {"ok": True}

    @router.post("/api/local-execution/companion/model-removal")
    def model_removal(data: LocalModelVersionIn, response: Response, device=Depends(companion_device), db=Depends(get_db)):
        limiter.check("local-device:model-removal:" + device.id, 10, 60)
        if (not is_supported_model_revision(data.model, data.revision)
                or device_model_in_use(db, device, data.model, data.revision)):
            raise HTTPException(409, detail={"reason": "local_model_in_use"}, headers=NO_STORE)
        if device_model_identity(device) == (data.model, data.revision):
            device.runtime_status = "unknown"
            device.last_seen_at = None
            device.updated_at = utcnow()
        db.commit()
        response.headers.update(NO_STORE)
        return {"allowed": True}

    @router.post("/api/local-execution/companion/model-install-request")
    def pending_model_install(response: Response, request_id: UUID | None = Body(default=None, embed=True),
                              device=Depends(companion_device)):
        limiter.check("local-device:install-read:" + device.id, 12, 60)
        key = _model_request_key(device)
        response.headers.update(NO_STORE)
        try:
            raw = limiter.redis.get(key)
            pending = json.loads(raw) if raw is not None else None
            if request_id is not None and pending is not None and pending["id"] == str(request_id):
                limiter.redis.delete(key)
                return {"request": None}
        except RedisError:
            raise HTTPException(503, "Запрос установки временно недоступен", headers=NO_STORE) from None
        return {"request": pending}

    @router.post("/api/local-execution/companion/stopped")
    def stopped(response: Response, device=Depends(companion_device), db=Depends(get_db)):
        limiter.check("local-device:stopped:" + device.id, 20, 60)
        device.runtime_status = "unknown"
        device.last_seen_at = None
        device.updated_at = utcnow()
        db.commit()
        response.headers.update(NO_STORE)
        return {"device": device_payload(device, now=utcnow())}

    @router.post("/api/local-execution/companion/claim")
    def claim(request: Request, response: Response, device=Depends(companion_device), db=Depends(get_db)):
        limiter.check("local-device:claim:" + device.id, 30, 60)
        job = claim_local_job(db, device=device, now=utcnow())
        if job is not None:
            _bind_job_trace(request, job)
        payload = local_job_payload(job) if job is not None else None
        db.commit()
        response.headers.update(NO_STORE)
        return {"job": payload}

    @router.post("/api/local-execution/companion/jobs/{job_id}/heartbeat")
    def job_heartbeat(job_id: UUID, data: LocalJobHeartbeatIn, request: Request, response: Response,
                      device=Depends(companion_device), db=Depends(get_db)):
        limiter.check("local-device:job-heartbeat:" + device.id, 120, 60)
        result = heartbeat_local_job(db, device=device, job_id=str(job_id), generation=data.generation,
            stage=data.stage, sequence=data.sequence, completed=data.completed, total=data.total, unit=data.unit, now=utcnow(),
            on_scoped=partial(_bind_job_trace, request))
        db.commit()
        response.headers.update(NO_STORE)
        return result

    @router.post("/api/local-execution/companion/jobs/{job_id}/failure")
    def job_failure(job_id: UUID, data: LocalJobFailureIn, request: Request, response: Response,
                    device=Depends(companion_device), db=Depends(get_db)):
        limiter.check("local-device:failure:" + device.id, 30, 60)
        result = fail_local_job(db, device=device, job_id=str(job_id), generation=data.generation,
            reason=data.reason, now=utcnow(), on_scoped=partial(_bind_job_trace, request))
        db.commit()
        response.headers.update(NO_STORE)
        return result

    @router.get("/api/local-execution/companion/jobs/{job_id}/source")
    def source(job_id: UUID, generation: int, request: Request,
               device=Depends(companion_device), db=Depends(get_db), settings=Depends(get_settings)):
        limiter.check("local-device:source:" + device.id, 10, 60)
        if not 1 <= generation <= 2147483647:
            raise HTTPException(422, detail={"reason": "local_generation_invalid"}, headers=NO_STORE)
        stack = ExitStack()
        try:
            chunks, receipt = stack.enter_context(open_local_input(db, device=device,
                raw_token=request.headers["authorization"][7:], job_id=str(job_id), generation=generation, settings=settings,
                on_scoped=partial(_bind_job_trace, request)))
            return LocalInputResponse(chunks, cleanup=stack.close, headers={**NO_STORE,
                "Content-Length": str(receipt["byte_count"]), "X-VoiceOps-Input-SHA256": receipt["source_sha256"],
                "Content-Disposition": 'attachment; filename="input.media"'})
        except Exception:
            stack.close()
            raise

    @router.post("/api/local-execution/companion/jobs/{job_id}/prepare")
    def prepare(job_id: UUID, data: LocalInputPrepareIn, request: Request, response: Response,
                device=Depends(companion_device), db=Depends(get_db), settings=Depends(get_settings)):
        limiter.check("local-device:prepare:" + device.id, 30, 60)
        result = prepare_local_input(db, device=device, job_id=str(job_id), generation=data.generation,
            source_sha256=data.source_sha256, source_duration_seconds=data.source_duration_seconds, settings=settings,
            now=utcnow(), on_scoped=partial(_bind_job_trace, request))
        db.commit()
        response.headers.update(NO_STORE)
        return result

    @router.post("/api/local-execution/companion/jobs/{job_id}/result")
    def result(job_id: UUID, request: Request, response: Response, body: bytes=Body(media_type="application/gzip"),
               device=Depends(companion_device), db=Depends(get_db), settings=Depends(get_settings)):
        limiter.check("local-device:result:" + device.id, 10, 60)
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/gzip":
            raise HTTPException(415, detail={"reason": "local_result_encoding_required"}, headers=NO_STORE)
        # Compressed transfer preserves the general 4MiB pre-auth body limit;
        # only this authenticated boundary expands to a bounded full JSON result.
        envelope, digest = decode_local_result(body)
        result = accept_local_result(db, device=device, job_id=str(job_id), envelope=envelope,
            digest=digest, settings=settings, now=utcnow(), on_scoped=partial(_bind_job_trace, request))
        db.commit()
        response.headers.update(NO_STORE)
        return result

    return router
