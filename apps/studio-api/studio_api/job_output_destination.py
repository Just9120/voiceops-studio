from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable

from sqlalchemy.orm import Session

from .google_connection_access import GoogleConnectionAccessError, refresh_user_google_drive_access_token
from .google_drive import GOOGLE_FOLDER_MIME_TYPE, GoogleDriveMetadataError
from .job_claim_lease import is_lease_active
from .models import JobStatus, Project, TranscriptionJob
from .security import utcnow

DRIVE_FOLDER_CAPABILITY_FIELDS = "id,name,mimeType,trashed,webViewLink,capabilities/canAddChildren"


class OutputDestinationReason(str, Enum):
    job_not_found = "job_not_found"
    job_not_processing = "job_not_processing"
    lease_not_owned = "lease_not_owned"
    lease_not_active = "lease_not_active"
    cancellation_requested = "cancellation_requested"
    project_unavailable = "project_unavailable"
    output_folder_missing = "output_folder_missing"
    google_connection_unavailable = "google_connection_unavailable"
    metadata_unavailable = "metadata_unavailable"
    output_identity_mismatch = "output_identity_mismatch"
    output_not_folder = "output_not_folder"
    output_folder_not_writable = "output_folder_not_writable"
    output_destination_changed = "output_destination_changed"
    yandex_connection_unavailable = "yandex_connection_unavailable"


class OutputDestinationError(RuntimeError):
    def __init__(self, reason: OutputDestinationReason):
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True)
class ProcessingJobOutputDestination:
    job_id: str
    project_id: str
    verified_at: datetime
    drive_folder_id: str = field(repr=False)
    output_provider: str = "google_drive"

    def __repr__(self) -> str:
        return f"ProcessingJobOutputDestination(job_id={self.job_id!r}, project_id={self.project_id!r}, verified_at={self.verified_at!r}, drive_folder_id=<redacted>)"


@dataclass(frozen=True)
class DriveFolderAuthorizationMetadata:
    id: str
    mime_type: str | None
    trashed: bool | None
    can_add_children: bool | None
    name: str | None = None
    web_view_link: str | None = None


@dataclass(frozen=True)
class _OutputSnapshot:
    job_id: str
    owner_user_id: str
    project_id: str
    output_drive_folder_id: str
    lease_owner_id: str | None
    lease_generation: int
    lease_expires_at: datetime | None
    cancel_requested_at: datetime | None
    project_archived_at: datetime | None
    output_provider: str = "google_drive"


def verify_processing_job_output_destination(
    db: Session,
    *,
    job_id: str,
    lease_owner_id: str,
    lease_generation: int,
    settings,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    token_resolver: Callable = refresh_user_google_drive_access_token,
    metadata_fetcher: Callable[[str, str], DriveFolderAuthorizationMetadata] | None = None,
    disk_resource_verifier: Callable | None = None,
) -> ProcessingJobOutputDestination:
    clock = clock or (lambda: utcnow().replace(tzinfo=None))
    snap = _load_snapshot(db, job_id, lease_owner_id, lease_generation, now or clock())
    if snap.output_provider == "yandex_disk":
        from .yandex_disk import YandexDiskError
        from .yandex_disk_access import verify_selected_resource
        try:
            (disk_resource_verifier or verify_selected_resource)(db, owner_user_id=snap.owner_user_id,
                resource_id=snap.output_drive_folder_id, settings=settings, is_folder=True)
        except YandexDiskError as exc:
            raise OutputDestinationError(OutputDestinationReason.yandex_connection_unavailable) from exc
        verified_at = clock()
        _compare_snapshot(snap, _load_snapshot(db, job_id, lease_owner_id, lease_generation, verified_at))
        return ProcessingJobOutputDestination(job_id=snap.job_id, project_id=snap.project_id,
            verified_at=verified_at, drive_folder_id=snap.output_drive_folder_id, output_provider="yandex_disk")
    if snap.output_provider != "google_drive":
        raise OutputDestinationError(OutputDestinationReason.metadata_unavailable)
    try:
        token = token_resolver(db, user_id=snap.owner_user_id, settings=settings)
    except GoogleConnectionAccessError as exc:
        raise OutputDestinationError(OutputDestinationReason.google_connection_unavailable) from exc
    try:
        meta = metadata_fetcher(token, snap.output_drive_folder_id) if metadata_fetcher else _fetch_drive_folder_authorization_metadata(token, snap.output_drive_folder_id)
    except GoogleDriveMetadataError as exc:
        reason = OutputDestinationReason.output_folder_missing if getattr(exc, "reason", None).value == "not_found" else OutputDestinationReason.metadata_unavailable
        raise OutputDestinationError(reason) from exc
    except Exception as exc:
        raise OutputDestinationError(OutputDestinationReason.metadata_unavailable) from exc
    _validate_metadata(meta, snap.output_drive_folder_id)
    verified_at = clock()
    _compare_snapshot(snap, _load_snapshot(db, job_id, lease_owner_id, lease_generation, verified_at))
    return ProcessingJobOutputDestination(job_id=snap.job_id, project_id=snap.project_id, drive_folder_id=snap.output_drive_folder_id, verified_at=verified_at)


def _load_snapshot(db: Session, job_id: str, owner: str, generation: int, now: datetime) -> _OutputSnapshot:
    db.expire_all()
    job = db.get(TranscriptionJob, job_id)
    if job is None:
        raise OutputDestinationError(OutputDestinationReason.job_not_found)
    if job.status != JobStatus.processing:
        raise OutputDestinationError(OutputDestinationReason.job_not_processing)
    if job.lease_owner_id != owner or job.lease_generation != generation:
        raise OutputDestinationError(OutputDestinationReason.lease_not_owned)
    if not is_lease_active(job, now):
        raise OutputDestinationError(OutputDestinationReason.lease_not_active)
    if job.cancel_requested_at is not None:
        raise OutputDestinationError(OutputDestinationReason.cancellation_requested)
    project = db.get(Project, job.project_id)
    if project is None or project.owner_user_id != job.owner_user_id or project.archived_at is not None:
        raise OutputDestinationError(OutputDestinationReason.project_unavailable)
    if not job.output_drive_folder_id:
        raise OutputDestinationError(OutputDestinationReason.output_folder_missing)
    return _OutputSnapshot(job.id, job.owner_user_id, project.id, job.output_drive_folder_id, job.lease_owner_id, job.lease_generation, job.lease_expires_at, job.cancel_requested_at, project.archived_at, job.output_provider)


def _validate_metadata(meta: DriveFolderAuthorizationMetadata, expected_id: str) -> None:
    if meta.id != expected_id:
        raise OutputDestinationError(OutputDestinationReason.output_identity_mismatch)
    if meta.mime_type != GOOGLE_FOLDER_MIME_TYPE:
        raise OutputDestinationError(OutputDestinationReason.output_not_folder)
    if meta.trashed is not False:
        raise OutputDestinationError(OutputDestinationReason.metadata_unavailable)
    if meta.can_add_children is not True:
        raise OutputDestinationError(OutputDestinationReason.output_folder_not_writable)


def _compare_snapshot(before: _OutputSnapshot, after: _OutputSnapshot) -> None:
    if before != after:
        raise OutputDestinationError(OutputDestinationReason.output_destination_changed)


def _fetch_drive_folder_authorization_metadata(access_token: str, folder_id: str) -> DriveFolderAuthorizationMetadata:
    import json
    from urllib.error import HTTPError, URLError
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen
    from .google_drive import DRIVE_FILES_URL, GoogleDriveMetadataReason

    params = urlencode({"fields": DRIVE_FOLDER_CAPABILITY_FIELDS, "supportsAllDrives": "true"})
    req = Request(f"{DRIVE_FILES_URL}/{folder_id}?{params}", headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"})
    try:
        with urlopen(req, timeout=10) as resp:  # nosec - Google Drive endpoint; tests inject metadata_fetcher.
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        raise GoogleDriveMetadataError(GoogleDriveMetadataReason.not_found if exc.code == 404 else GoogleDriveMetadataReason.unavailable) from exc
    except (URLError, OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GoogleDriveMetadataError(GoogleDriveMetadataReason.unavailable) from exc
    if not isinstance(payload, dict):
        raise GoogleDriveMetadataError(GoogleDriveMetadataReason.unavailable)
    caps = payload.get("capabilities")
    return DriveFolderAuthorizationMetadata(
        id=payload.get("id") if isinstance(payload.get("id"), str) else "",
        mime_type=payload.get("mimeType") if isinstance(payload.get("mimeType"), str) else None,
        trashed=payload.get("trashed") if isinstance(payload.get("trashed"), bool) else None,
        can_add_children=caps.get("canAddChildren") if isinstance(caps, dict) and isinstance(caps.get("canAddChildren"), bool) else None,
        name=payload.get("name") if isinstance(payload.get("name"), str) else None,
        web_view_link=payload.get("webViewLink") if isinstance(payload.get("webViewLink"), str) else None,
    )
