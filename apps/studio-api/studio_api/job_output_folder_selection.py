from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from fastapi import HTTPException

from .google_drive import GOOGLE_FOLDER_MIME_TYPE, GoogleDriveMetadataError
from .job_output_destination import DriveFolderAuthorizationMetadata, _fetch_drive_folder_authorization_metadata
from .security import utcnow


def normalize_drive_id(value: str | None, label: str = "ID Google Drive") -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > 256 or not all(ch.isalnum() or ch in "_-" for ch in value):
        raise HTTPException(422, f"Некорректный {label}")
    return value


def normalize_drive_url(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > 2000 or not (value.startswith("https://drive.google.com/") or value.startswith("https://docs.google.com/")):
        raise HTTPException(422, "Некорректная ссылка Google Drive")
    return value


def normalize_optional_name(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value[:512] or None


@dataclass(frozen=True)
class VerifiedOutputFolderSelection:
    id: str = field(repr=False)
    name: str | None
    web_view_url: str | None
    verified_at: datetime
    provider: str = "google_drive"

    def __repr__(self) -> str:
        return "VerifiedOutputFolderSelection(id=<redacted>, name={!r}, web_view_url={!r}, verified_at={!r})".format(self.name, self.web_view_url, self.verified_at)


def verify_output_folder_selection(
    access_token: str,
    folder_id: str,
    *,
    metadata_fetcher: Callable[[str, str], object] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> VerifiedOutputFolderSelection:
    expected = normalize_drive_id(folder_id, "ID папки Google Drive")
    if not expected:
        raise HTTPException(422, "Некорректный ID папки Google Drive")
    fetcher = metadata_fetcher or _fetch_drive_folder_authorization_metadata
    try:
        meta = fetcher(access_token, expected)
    except GoogleDriveMetadataError:
        raise HTTPException(422, "Выбранная папка Google Drive недоступна") from None
    except Exception:
        raise HTTPException(502, "Google Drive metadata is unavailable") from None
    meta_id = getattr(meta, "id", "")
    mime_type = getattr(meta, "mime_type", None) or getattr(meta, "mimeType", None)
    trashed = getattr(meta, "trashed", None)
    can_add = getattr(meta, "can_add_children", None)
    if can_add is None:
        caps = getattr(meta, "capabilities", None)
        can_add = caps.get("canAddChildren") if isinstance(caps, dict) else None
    if meta_id != expected:
        raise HTTPException(422, "Выбранная папка Google Drive недоступна")
    if mime_type != GOOGLE_FOLDER_MIME_TYPE:
        raise HTTPException(422, "Выберите папку Google Drive для результатов")
    if trashed is not False:
        raise HTTPException(422, "Выбранная папка Google Drive недоступна")
    if can_add is not True:
        raise HTTPException(422, "Нет доступа для создания файлов в выбранной папке")
    return VerifiedOutputFolderSelection(
        id=expected,
        name=normalize_optional_name(getattr(meta, "name", None)),
        web_view_url=normalize_drive_url(getattr(meta, "web_view_link", None) or getattr(meta, "web_view_url", None)),
        verified_at=(clock or utcnow)(),
    )
