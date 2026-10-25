from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)
from sqlalchemy.orm import Session

from .audit import audit
from .config import get_settings
from .db import get_db
from .deps import current_session, require_csrf
from .rate_limit import RateLimiter
from .security import utcnow
from .models import (
    TranscriptCatalogEntry,
    TranscriptionJob,
    TranscriptionJobOutput,
    User,
)
from .transcript_catalog import TRANSCRIPT_OUTPUT_KINDS
from .transcript_maintenance_dry_run import (
    TranscriptMaintenanceSelectionMode,
)
from .transcript_maintenance_runs import (
    TranscriptMaintenanceOperation,
    TranscriptMaintenanceRunError,
    TranscriptMaintenanceRunReason,
    TranscriptMaintenanceWorkflow,
    create_transcript_maintenance_apply_run,
    create_transcript_maintenance_run,
    latest_transcript_maintenance_run,
    owned_transcript_maintenance_run,
    transcript_maintenance_run_payload,
)


router = APIRouter()
legacy_router = APIRouter(prefix="/api/transcript-catalog/migration")
maintenance_router = APIRouter(prefix="/api/transcript-maintenance")
catalog_limiter = RateLimiter()
_NO_STORE_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
}


class TranscriptMaintenanceFolderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    folder_id: str = Field(min_length=1, max_length=256)

    @field_validator("folder_id")
    @classmethod
    def valid_folder_id(cls, value: str) -> str:
        cleaned = value.strip()
        if (
            not cleaned
            or not all(
                character.isalnum() or character in "_-"
                for character in cleaned
            )
        ):
            raise ValueError("Некорректный ID папки Google Drive")
        return cleaned


class TranscriptCatalogClearIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_clear: StrictBool

    @field_validator("confirm_clear")
    @classmethod
    def clear_must_be_confirmed(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Подтвердите очистку манифеста")
        return value


@router.post("/api/transcript-catalog/export")
def export_transcript_catalog(data: TranscriptMaintenanceFolderIn, response: Response,
    pair=Depends(require_csrf), db: Session = Depends(get_db), settings=Depends(get_settings)):
    from .transcript_manifest_export import export_manifest
    from .google_connection_access import GoogleConnectionAccessError
    from .google_drive import GoogleDriveMetadataError
    from .google_drive_upload import GoogleDriveUploadError
    from .job_output_destination import OutputDestinationError
    _, user = pair
    catalog_limiter.check(f"transcript-catalog:export:{user.id}", 5, 3600)
    _no_store(response)
    try:
        result = export_manifest(db, user_id=user.id, folder_id=data.folder_id, settings=settings)
    except ValueError as exc:
        raise HTTPException(409, detail="manifest_export_limit", headers=_NO_STORE_HEADERS) from exc
    except (GoogleConnectionAccessError, GoogleDriveMetadataError, GoogleDriveUploadError, OutputDestinationError) as exc:
        raise HTTPException(409, detail="manifest_export_unavailable", headers=_NO_STORE_HEADERS) from exc
    audit(db, "transcript_catalog.exported", actor_user_id=user.id, subject_user_id=user.id)
    db.commit()
    return result


@router.post("/api/transcript-catalog/clear")
def clear_transcript_catalog(
    _data: TranscriptCatalogClearIn,
    response: Response,
    pair=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    _, user = pair
    catalog_limiter.check(f"transcript-catalog:clear:{user.id}", 5, 3600)
    _no_store(response)
    reset_at = utcnow()
    catalog_count = (
        db.query(TranscriptCatalogEntry)
        .filter(
            TranscriptCatalogEntry.owner_user_id == user.id,
            TranscriptCatalogEntry.updated_at <= reset_at,
        )
        .count()
    )
    output_count = (
        db.query(TranscriptionJobOutput)
        .join(
            TranscriptionJob,
            TranscriptionJob.id == TranscriptionJobOutput.job_id,
        )
        .filter(
            TranscriptionJob.owner_user_id == user.id,
            TranscriptionJobOutput.output_kind.in_(TRANSCRIPT_OUTPUT_KINDS),
            TranscriptionJobOutput.persisted_at <= reset_at,
        )
        .count()
    )
    user.manifest_reset_at = reset_at
    user.updated_at = reset_at
    audit(
        db,
        "transcript_catalog.cleared",
        actor_user_id=user.id,
        subject_user_id=user.id,
    )
    db.commit()
    return {
        "ok": True,
        "reset_at": reset_at.isoformat(),
        "hidden_evidence_count": catalog_count + output_count,
    }


class TranscriptCatalogMigrationApplyIn(
    TranscriptMaintenanceFolderIn
):
    confirm_apply: StrictBool

    @field_validator("confirm_apply")
    @classmethod
    def apply_must_be_confirmed(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Подтвердите применение миграции")
        return value


class TranscriptMaintenanceTargetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selection_mode: TranscriptMaintenanceSelectionMode
    folder_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )
    document_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )
    target_name: str = Field(min_length=1, max_length=512)
    idempotency_key: str = Field(min_length=16, max_length=64)

    @field_validator("folder_id", "document_id")
    @classmethod
    def valid_target_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if (
            not cleaned
            or not cleaned.isascii()
            or not all(
                character.isalnum() or character in "_-"
                for character in cleaned
            )
        ):
            raise ValueError("Некорректный ID Google Drive")
        return cleaned

    @field_validator("target_name")
    @classmethod
    def valid_target_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Укажите название выбранного объекта")
        return cleaned

    @field_validator("idempotency_key")
    @classmethod
    def valid_idempotency_key(cls, value: str) -> str:
        cleaned = value.strip()
        if not all(character.isalnum() or character in "_-" for character in cleaned):
            raise ValueError("Некорректный idempotency key")
        return cleaned

    @model_validator(mode="after")
    def exactly_one_target(self):
        if self.selection_mode == TranscriptMaintenanceSelectionMode.folder_tree:
            valid = self.folder_id is not None and self.document_id is None
        else:
            valid = self.document_id is not None and self.folder_id is None
        if not valid:
            raise ValueError(
                "Режим обслуживания не соответствует выбранному объекту"
            )
        return self


class TranscriptMaintenanceApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_apply: StrictBool
    preview_run_id: str = Field(min_length=36, max_length=36)
    idempotency_key: str = Field(min_length=16, max_length=64)

    @field_validator("confirm_apply")
    @classmethod
    def maintenance_apply_must_be_confirmed(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Подтвердите применение операции")
        return value

    @field_validator("idempotency_key")
    @classmethod
    def valid_idempotency_key(cls, value: str) -> str:
        cleaned = value.strip()
        if not all(character.isalnum() or character in "_-" for character in cleaned):
            raise ValueError("Некорректный idempotency key")
        return cleaned


@legacy_router.post("/dry-run")
def dry_run_transcript_catalog_migration(
    _data: TranscriptMaintenanceFolderIn,
    response: Response,
    pair=Depends(require_csrf),
):
    _, user = pair
    catalog_limiter.check(
        f"transcript-catalog:dry-run:{user.id}",
        20,
        3600,
    )
    _no_store(response)
    _raise_catalog_error(
        status.HTTP_410_GONE,
        reason="transcript_maintenance_split_required",
        retryable=False,
    )


@legacy_router.post("/apply")
def apply_transcript_catalog_migration(
    _data: TranscriptCatalogMigrationApplyIn,
    response: Response,
    pair=Depends(require_csrf),
):
    _, user = pair
    catalog_limiter.check(
        f"transcript-catalog:apply:{user.id}",
        5,
        3600,
    )
    _no_store(response)
    _raise_catalog_error(
        status.HTTP_410_GONE,
        reason="transcript_maintenance_split_required",
        retryable=False,
    )


@maintenance_router.post("/standardization/dry-run", status_code=status.HTTP_202_ACCEPTED)
def dry_run_transcript_standardization(
    data: TranscriptMaintenanceTargetIn,
    response: Response,
    pair=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    _, user = pair
    catalog_limiter.check(
        f"transcript-maintenance:standardization:dry-run:{user.id}",
        20,
        3600,
    )
    _no_store(response)
    return _create_maintenance_run(
        db,
        owner_user_id=user.id,
        workflow=TranscriptMaintenanceWorkflow.standardization,
        operation=TranscriptMaintenanceOperation.dry_run,
        data=data,
    )


@maintenance_router.post("/catalog-import/dry-run", status_code=status.HTTP_202_ACCEPTED)
def dry_run_transcript_catalog_import(
    data: TranscriptMaintenanceTargetIn,
    response: Response,
    pair=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    _, user = pair
    catalog_limiter.check(
        f"transcript-maintenance:catalog-import:dry-run:{user.id}",
        20,
        3600,
    )
    _no_store(response)
    return _create_maintenance_run(
        db,
        owner_user_id=user.id,
        workflow=TranscriptMaintenanceWorkflow.catalog_import,
        operation=TranscriptMaintenanceOperation.dry_run,
        data=data,
    )


@maintenance_router.post("/standardization/apply", status_code=status.HTTP_202_ACCEPTED)
def apply_transcript_standardization(
    data: TranscriptMaintenanceApplyIn,
    response: Response,
    pair=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    _, user = pair
    catalog_limiter.check(
        f"transcript-maintenance:standardization:apply:{user.id}",
        5,
        3600,
    )
    _no_store(response)
    return _create_maintenance_run(
        db,
        owner_user_id=user.id,
        workflow=TranscriptMaintenanceWorkflow.standardization,
        operation=TranscriptMaintenanceOperation.apply,
        data=data,
    )


@maintenance_router.post("/catalog-import/apply", status_code=status.HTTP_202_ACCEPTED)
def apply_transcript_catalog_import(
    data: TranscriptMaintenanceApplyIn,
    response: Response,
    pair=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    _, user = pair
    catalog_limiter.check(
        f"transcript-maintenance:catalog-import:apply:{user.id}",
        5,
        3600,
    )
    _no_store(response)
    return _create_maintenance_run(
        db,
        owner_user_id=user.id,
        workflow=TranscriptMaintenanceWorkflow.catalog_import,
        operation=TranscriptMaintenanceOperation.apply,
        data=data,
    )


@maintenance_router.get("/runs")
def read_latest_transcript_maintenance_run(
    workflow: TranscriptMaintenanceWorkflow,
    response: Response,
    pair=Depends(current_session),
    db: Session = Depends(get_db),
):
    _, user = pair
    _no_store(response)
    run = latest_transcript_maintenance_run(
        db,
        owner_user_id=user.id,
        workflow=workflow,
    )
    return {"run": transcript_maintenance_run_payload(run) if run else None}


@maintenance_router.get("/runs/{run_id}")
def read_transcript_maintenance_run(
    run_id: str,
    response: Response,
    pair=Depends(current_session),
    db: Session = Depends(get_db),
):
    _, user = pair
    _no_store(response)
    try:
        run = owned_transcript_maintenance_run(
            db,
            owner_user_id=user.id,
            run_id=run_id,
        )
    except TranscriptMaintenanceRunError:
        _raise_catalog_error(
            status.HTTP_404_NOT_FOUND,
            reason=TranscriptMaintenanceRunReason.run_not_found.value,
            retryable=False,
        )
    return transcript_maintenance_run_payload(run)


def _create_maintenance_run(
    db: Session,
    *,
    owner_user_id: str,
    workflow: TranscriptMaintenanceWorkflow,
    operation: TranscriptMaintenanceOperation,
    data: TranscriptMaintenanceTargetIn | TranscriptMaintenanceApplyIn,
) -> dict[str, object]:
    try:
        if isinstance(data, TranscriptMaintenanceApplyIn):
            run = create_transcript_maintenance_apply_run(
                db,
                owner_user_id=owner_user_id,
                workflow=workflow,
                preview_run_id=data.preview_run_id,
                idempotency_key=data.idempotency_key,
            )
        else:
            run = create_transcript_maintenance_run(
                db,
                owner_user_id=owner_user_id,
                workflow=workflow,
                operation=operation,
                selection_mode=data.selection_mode,
                folder_id=data.folder_id,
                document_id=data.document_id,
                target_name=data.target_name,
                idempotency_key=data.idempotency_key,
            )
    except TranscriptMaintenanceRunError as exc:
        db.rollback()
        status_code = (
            status.HTTP_404_NOT_FOUND
            if exc.reason == TranscriptMaintenanceRunReason.run_not_found
            else status.HTTP_409_CONFLICT
        )
        _raise_catalog_error(
            status_code,
            reason=exc.reason.value,
            retryable=False,
        )
    return transcript_maintenance_run_payload(run)


def _no_store(response: Response) -> None:
    for header, value in _NO_STORE_HEADERS.items():
        response.headers[header] = value


def _raise_catalog_error(
    status_code: int,
    *,
    reason: str,
    retryable: bool,
) -> NoReturn:
    raise HTTPException(
        status_code,
        detail={
            "reason": reason,
            "retryable": retryable,
        },
        headers=_NO_STORE_HEADERS,
    )


router.include_router(legacy_router)
router.include_router(maintenance_router)
