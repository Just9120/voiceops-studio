"""Browser-safe Disk connection and selection endpoints; no tokens in DTOs."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .deps import current_session, require_csrf
from .audit import audit
from .models import Project, Source, SourceType, SourceUploadStatus, SourceStorageCleanupStatus, YandexDiskConnection
from .security import utcnow
from .source_creation import parse_authoritative_source_created_at
from .source_policy import is_supported_source_mime_type, normalize_source_mime_type, validate_source_size
from .source_storage import normalize_source_display_filename
from .yandex_disk import YandexDiskClient, YandexDiskError, disk_web_url, normalize_disk_path
from .yandex_disk_access import access_token, active_connection, register_resource, resource_fingerprint, verify_selected_resource
from .yandex_disk_connection import disconnect_connection, finish_connection, start_connection
from .yandex_disk_oauth import load_config

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class DiskListIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(default="disk:/", max_length=4096)
    offset: StrictInt = Field(default=0, ge=0, le=100000)
    limit: StrictInt = Field(default=50, ge=1, le=100)
    sort: Literal["name", "-name", "modified", "-modified"] = "name"
    folders_only: StrictBool = False
    search: str = Field(default="", max_length=160)

    @field_validator("path")
    @classmethod
    def canonical_path(cls, value):
        try:
            return normalize_disk_path(value)
        except YandexDiskError:
            raise ValueError("Некорректная папка Яндекс Диска") from None


class DiskSelectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=6, max_length=4096)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    is_folder: StrictBool


class DiskSourcesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_ids: list[str] = Field(min_length=1, max_length=50)

    @field_validator("resource_ids")
    @classmethod
    def unique_handles(cls, values):
        from uuid import UUID
        if len(values) != len(set(values)):
            raise ValueError("Повторяющиеся исходники")
        for value in values:
            if str(UUID(value)) != value:
                raise ValueError("Некорректный исходник Яндекс Диска")
        return values


class DiskFolderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folder_id: str = Field(min_length=36, max_length=36)


def verify_yandex_output_folder(db, *, owner_user_id, folder_id, settings):
    from .job_output_folder_selection import VerifiedOutputFolderSelection
    try:
        resource = verify_selected_resource(db, owner_user_id=owner_user_id,
            resource_id=folder_id, settings=settings, is_folder=True)
        return VerifiedOutputFolderSelection(folder_id, resource.name, disk_web_url(resource.path),
                                             utcnow(), provider="yandex_disk")
    except YandexDiskError as error:
        raise disk_http_error(error) from None


def resource_payload(resource):
    return {"path": resource.path, "name": resource.name, "is_folder": resource.is_folder,
            "mime_type": resource.mime_type, "size_bytes": resource.size_bytes,
            "modified": resource.modified, "fingerprint": resource_fingerprint(resource)}


def disk_http_error(error):
    code = 503 if error.reason == "configuration_unavailable" else 409
    return HTTPException(code, detail={"reason": "yandex_disk_" + error.reason}, headers=NO_STORE)


def build_router(*, recent_auth, limiter, project_loader=None, source_serializer=None, project_serializer=None):
    router = APIRouter()

    @router.get("/api/yandex/connection")
    def connection(response: Response, pair=Depends(current_session),
                   db: Session=Depends(get_db), settings=Depends(get_settings)):
        response.headers.update(NO_STORE)
        row = db.get(YandexDiskConnection, pair[1].id)
        configured = True
        try:
            load_config(settings)
        except YandexDiskError:
            configured = False
        return {"configured": configured, "connected": bool(row and row.status == "active"
                    and row.token_ciphertext and row.token_nonce),
                "status": row.status if row else "not_connected"}

    @router.post("/api/yandex/oauth/start")
    def start(request: Request, response: Response, pair=Depends(require_csrf),
              db: Session=Depends(get_db), settings=Depends(get_settings)):
        session, user = recent_auth(pair, request=request, db=db)
        limiter.check("yandex-disk:oauth:" + user.id, 20, 3600)
        response.headers.update(NO_STORE)
        try:
            return start_connection(db, session=session, user=user, settings=settings)
        except YandexDiskError as error:
            raise disk_http_error(error) from None

    @router.get("/api/yandex/oauth/callback")
    def callback(request: Request, state: str | None=None, code: str | None=None,
                 error: str | None=None, db: Session=Depends(get_db), settings=Depends(get_settings)):
        result = finish_connection(db, state=state, code=code, error=error,
            raw_session=request.cookies.get(settings.cookie_name), settings=settings)
        return RedirectResponse(settings.app_origin.rstrip("/") + "/settings/connections?yandex_oauth=" + result,
                                status_code=303, headers=NO_STORE)

    @router.delete("/api/yandex/connection")
    def disconnect(request: Request, response: Response, pair=Depends(require_csrf),
                   db: Session=Depends(get_db), settings=Depends(get_settings)):
        _, user = recent_auth(pair, request=request, db=db)
        limiter.check("yandex-disk:disconnect:" + user.id, 20, 3600)
        response.headers.update(NO_STORE)
        return disconnect_connection(db, owner_id=user.id, settings=settings)

    @router.post("/api/yandex/resources/list")
    def list_resources(data: DiskListIn, response: Response, pair=Depends(require_csrf),
                       db: Session=Depends(get_db), settings=Depends(get_settings)):
        _, user = pair
        limiter.check("yandex-disk:list:" + user.id, 120, 60)
        response.headers.update(NO_STORE)
        try:
            token = access_token(db, user_id=user.id, settings=settings)
            connection = active_connection(db, owner_user_id=user.id)
            account, revision = connection.account_uid, connection.credential_revision
            db.rollback()
            folder, rows, offset = YandexDiskClient(token).children(
                data.path, offset=data.offset, limit=data.limit, sort=data.sort)
            connection = active_connection(db, owner_user_id=user.id)
            if (connection.account_uid, connection.credential_revision) != (account, revision):
                raise YandexDiskError("connection_changed")
            return {"folder": resource_payload(folder), "items": [resource_payload(r) for r in rows
                if (not data.folders_only or r.is_folder)
                and data.search.casefold() in r.name.casefold()], "next_offset": offset,
                "search_scope": "current_folder"}
        except YandexDiskError as error:
            raise disk_http_error(error) from None

    @router.post("/api/yandex/resources/select")
    def select_resource(data: DiskSelectIn, response: Response, pair=Depends(require_csrf),
                        db: Session=Depends(get_db), settings=Depends(get_settings)):
        _, user = pair
        limiter.check("yandex-disk:select:" + user.id, 120, 60)
        response.headers.update(NO_STORE)
        try:
            token = access_token(db, user_id=user.id, settings=settings)
            connection = active_connection(db, owner_user_id=user.id)
            account, revision = connection.account_uid, connection.credential_revision
            db.rollback()
            resource = YandexDiskClient(token).metadata(data.path)
            connection = active_connection(db, owner_user_id=user.id)
            if ((connection.account_uid, connection.credential_revision) != (account, revision)
                    or resource.is_folder != data.is_folder
                    or resource_fingerprint(resource) != data.fingerprint):
                raise YandexDiskError("resource_changed")
            handle = register_resource(db, owner_user_id=user.id, resource=resource,
                expected_connection=(account, revision))
            db.commit()
            return {"id": handle.id, **resource_payload(resource)}
        except YandexDiskError as error:
            db.rollback()
            raise disk_http_error(error) from None

    @router.post("/api/projects/{project_id}/sources/yandex-disk")
    def intake_sources(project_id: str, data: DiskSourcesIn, response: Response,
                       pair=Depends(require_csrf), db: Session=Depends(get_db), settings=Depends(get_settings)):
        _, user = pair
        limiter.check("yandex-disk:intake:" + user.id, 60, 3600)
        response.headers.update(NO_STORE)
        project_loader(db, user, project_id)
        resources = []
        expected_connection = None
        try:
            for handle in data.resource_ids:
                resource = verify_selected_resource(db, owner_user_id=user.id, resource_id=handle,
                    settings=settings, is_folder=False)
                mime = normalize_source_mime_type(resource.mime_type)
                if not is_supported_source_mime_type(mime):
                    raise YandexDiskError("unsupported_media_type")
                if resource.size_bytes is None or not validate_source_size(resource.size_bytes, settings.source_max_upload_bytes):
                    raise YandexDiskError("too_large")
                resources.append((handle, resource, mime))
                connection = active_connection(db, owner_user_id=user.id)
                identity = (connection.account_uid, connection.credential_revision)
                if expected_connection is not None and identity != expected_connection:
                    raise YandexDiskError("connection_changed")
                expected_connection = identity
                db.rollback()
            # A single project lock also makes repeated intake idempotent.
            db.scalar(select(Project).where(Project.id == project_id).with_for_update())
            project_loader(db, user, project_id)
            connection = active_connection(db, owner_user_id=user.id, lock=True)
            if (connection.account_uid, connection.credential_revision) != expected_connection:
                raise YandexDiskError("connection_changed")
            created = []
            for handle, resource, mime in resources:
                row = db.scalar(select(Source).where(Source.project_id == project_id,
                    Source.source_type == SourceType.yandex_disk, Source.drive_file_id == handle,
                    Source.deleted_at.is_(None), Source.upload_status == SourceUploadStatus.uploaded))
                if row is None:
                    timestamp = parse_authoritative_source_created_at(resource.created)
                    row = Source(project_id=project_id, source_type=SourceType.yandex_disk,
                        original_filename=normalize_source_display_filename(resource.name), mime_type=mime,
                        size_bytes=resource.size_bytes, drive_file_id=handle, drive_file_url=disk_web_url(resource.path),
                        upload_status=SourceUploadStatus.uploaded, uploaded_at=utcnow(),
                        source_created_at=timestamp,
                        source_created_at_provenance="yandex_disk_created_time" if timestamp else None,
                        storage_cleanup_status=SourceStorageCleanupStatus.not_applicable)
                    db.add(row)
                    db.flush()
                created.append(row)
            audit(db, "source.yandex_disk.created", actor_user_id=user.id, subject_user_id=user.id)
            db.commit()
            return {"sources": [source_serializer(row) for row in created]}
        except YandexDiskError as error:
            db.rollback()
            raise disk_http_error(error) from None

    @router.post("/api/projects/{project_id}/output-folders/yandex-disk/verify")
    def verify_folder(project_id: str, data: DiskFolderIn, response: Response,
                      pair=Depends(require_csrf), db: Session=Depends(get_db), settings=Depends(get_settings)):
        _, user = pair
        limiter.check("yandex-disk:folder:verify:" + user.id, 120, 3600)
        response.headers.update(NO_STORE)
        project_loader(db, user, project_id)
        selected = verify_yandex_output_folder(db, owner_user_id=user.id, folder_id=data.folder_id, settings=settings)
        return {"name": selected.name, "web_view_url": selected.web_view_url, "provider": "yandex_disk"}

    @router.post("/api/projects/{project_id}/output-folder/yandex-disk")
    def set_folder(project_id: str, data: DiskFolderIn, response: Response,
                   pair=Depends(require_csrf), db: Session=Depends(get_db), settings=Depends(get_settings)):
        _, user = pair
        limiter.check("yandex-disk:folder:set:" + user.id, 60, 3600)
        response.headers.update(NO_STORE)
        project_loader(db, user, project_id)
        selected = verify_yandex_output_folder(db, owner_user_id=user.id, folder_id=data.folder_id, settings=settings)
        project = project_loader(db, user, project_id)
        project.output_provider = "yandex_disk"
        project.output_drive_folder_id = selected.id
        project.output_drive_folder_url = selected.web_view_url
        project.output_drive_folder_name = selected.name
        project.updated_at = utcnow()
        audit(db, "project.output_folder.yandex_disk_set", actor_user_id=user.id, subject_user_id=user.id)
        db.commit()
        return project_serializer(project)

    return router
