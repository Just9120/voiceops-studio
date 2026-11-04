from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .google_drive import (
    GOOGLE_FOLDER_MIME_TYPE,
    GoogleDriveFolderChildren,
    GoogleDriveMetadata,
    fetch_drive_file_metadata,
    list_drive_folder_children,
)
from .source_creation import parse_authoritative_source_created_at
from .source_policy import is_supported_source_mime_type, normalize_source_mime_type

MAX_DRIVE_SOURCE_FILES = 50
MAX_DRIVE_FOLDER_DEPTH = 8
MAX_DRIVE_FOLDER_PAGES = 100
MAX_DRIVE_FOLDER_ITEMS_SCANNED = 500
DRIVE_FOLDER_PAGE_SIZE = 100


class DriveFolderIntakeReason(str, Enum):
    root_not_folder = "root_not_folder"
    metadata_mismatch = "metadata_mismatch"
    cycle = "cycle"
    duplicate_id = "duplicate_id"
    repeated_page_token = "repeated_page_token"
    depth_limit = "depth_limit"
    page_limit = "page_limit"
    item_limit = "item_limit"
    unavailable = "unavailable"


class DriveFolderIntakeError(RuntimeError):
    def __init__(self, reason: DriveFolderIntakeReason):
        self.reason = reason
        super().__init__(reason.value)


class DriveFolderSkipReason(str, Enum):
    unsupported = "unsupported"
    empty = "empty"
    oversized = "oversized"
    creation_time_unavailable = "creation_time_unavailable"


@dataclass(frozen=True)
class DriveFolderAcceptedItem:
    metadata: GoogleDriveMetadata
    relative_path: str
    mime_type: str


@dataclass(frozen=True)
class DriveFolderSkippedItem:
    id: str
    relative_path: str
    reason: DriveFolderSkipReason


@dataclass(frozen=True)
class DriveFolderPreview:
    folder_id: str
    folder_name: str
    total_file_count: int
    folder_count: int
    supported_count: int
    accepted: tuple[DriveFolderAcceptedItem, ...]
    skipped: tuple[DriveFolderSkippedItem, ...]
    blocker: str | None
    complete: bool


MetadataFetcher = Callable[[str, str], GoogleDriveMetadata]
ChildrenFetcher = Callable[[str, str, int, str | None], GoogleDriveFolderChildren]


def inspect_drive_source_folder(
    access_token: str,
    folder_id: str,
    *,
    max_upload_bytes: int,
    metadata_fetcher: MetadataFetcher = fetch_drive_file_metadata,
    children_fetcher: ChildrenFetcher = list_drive_folder_children,
) -> DriveFolderPreview:
    try:
        root = metadata_fetcher(access_token, folder_id)
    except DriveFolderIntakeError:
        raise
    except Exception as exc:
        raise DriveFolderIntakeError(DriveFolderIntakeReason.unavailable) from exc
    if root.id != folder_id:
        raise DriveFolderIntakeError(DriveFolderIntakeReason.metadata_mismatch)
    if not root.is_folder or root.mime_type != GOOGLE_FOLDER_MIME_TYPE:
        raise DriveFolderIntakeError(DriveFolderIntakeReason.root_not_folder)

    root_name = _safe_path_segment(root.name, folder_id)
    queue = deque([(folder_id, root_name, 0, (folder_id,))])
    seen_ids = {folder_id}
    accepted: list[DriveFolderAcceptedItem] = []
    skipped: list[DriveFolderSkippedItem] = []
    total_file_count = 0
    folder_count = 1
    pages = 0
    scanned_items = 0

    while queue:
        current_id, current_path, depth, ancestors = queue.popleft()
        page_token: str | None = None
        seen_page_tokens: set[str] = set()
        while True:
            pages += 1
            if pages > MAX_DRIVE_FOLDER_PAGES:
                raise DriveFolderIntakeError(DriveFolderIntakeReason.page_limit)
            try:
                page = children_fetcher(
                    access_token,
                    current_id,
                    DRIVE_FOLDER_PAGE_SIZE,
                    page_token,
                )
            except DriveFolderIntakeError:
                raise
            except Exception as exc:
                raise DriveFolderIntakeError(
                    DriveFolderIntakeReason.unavailable
                ) from exc
            if page.folder_id != current_id:
                raise DriveFolderIntakeError(
                    DriveFolderIntakeReason.metadata_mismatch
                )

            for item in sorted(
                page.items,
                key=lambda value: (
                    (value.name or "").casefold(),
                    value.id,
                ),
            ):
                scanned_items += 1
                if scanned_items > MAX_DRIVE_FOLDER_ITEMS_SCANNED:
                    raise DriveFolderIntakeError(DriveFolderIntakeReason.item_limit)
                if not item.id:
                    raise DriveFolderIntakeError(
                        DriveFolderIntakeReason.metadata_mismatch
                    )
                if item.size_bytes is not None and item.size_bytes < 0:
                    raise DriveFolderIntakeError(
                        DriveFolderIntakeReason.metadata_mismatch
                    )
                if item.is_folder != (item.mime_type == GOOGLE_FOLDER_MIME_TYPE):
                    raise DriveFolderIntakeError(
                        DriveFolderIntakeReason.metadata_mismatch
                    )
                if item.id in ancestors:
                    raise DriveFolderIntakeError(DriveFolderIntakeReason.cycle)
                if item.id in seen_ids:
                    raise DriveFolderIntakeError(DriveFolderIntakeReason.duplicate_id)
                seen_ids.add(item.id)
                relative_path = (
                    f"{current_path}/{_safe_path_segment(item.name, item.id)}"
                )
                if item.is_folder:
                    if item.mime_type != GOOGLE_FOLDER_MIME_TYPE:
                        raise DriveFolderIntakeError(
                            DriveFolderIntakeReason.metadata_mismatch
                        )
                    child_depth = depth + 1
                    if child_depth > MAX_DRIVE_FOLDER_DEPTH:
                        raise DriveFolderIntakeError(
                            DriveFolderIntakeReason.depth_limit
                        )
                    folder_count += 1
                    queue.append(
                        (
                            item.id,
                            relative_path,
                            child_depth,
                            (*ancestors, item.id),
                        )
                    )
                    continue

                total_file_count += 1
                normalized_mime = normalize_source_mime_type(item.mime_type)
                reason = _skip_reason(
                    item,
                    normalized_mime,
                    max_upload_bytes=max_upload_bytes,
                )
                if reason is not None:
                    skipped.append(
                        DriveFolderSkippedItem(item.id, relative_path, reason)
                    )
                    continue
                accepted.append(
                    DriveFolderAcceptedItem(item, relative_path, normalized_mime or "")
                )
                if len(accepted) > MAX_DRIVE_SOURCE_FILES:
                    return DriveFolderPreview(
                        folder_id=folder_id,
                        folder_name=root_name,
                        total_file_count=total_file_count,
                        folder_count=folder_count,
                        supported_count=len(accepted),
                        accepted=(),
                        skipped=tuple(skipped),
                        blocker="over_limit",
                        complete=False,
                    )

            next_page_token = page.next_page_token
            if not next_page_token:
                break
            if not isinstance(next_page_token, str) or len(next_page_token) > 512:
                raise DriveFolderIntakeError(
                    DriveFolderIntakeReason.metadata_mismatch
                )
            if next_page_token in seen_page_tokens or next_page_token == page_token:
                raise DriveFolderIntakeError(
                    DriveFolderIntakeReason.repeated_page_token
                )
            seen_page_tokens.add(next_page_token)
            page_token = next_page_token

    accepted.sort(key=lambda value: (value.relative_path.casefold(), value.metadata.id))
    skipped.sort(key=lambda value: (value.relative_path.casefold(), value.id))
    return DriveFolderPreview(
        folder_id=folder_id,
        folder_name=root_name,
        total_file_count=total_file_count,
        folder_count=folder_count,
        supported_count=len(accepted),
        accepted=tuple(accepted),
        skipped=tuple(skipped),
        blocker="empty" if not accepted else None,
        complete=True,
    )


def drive_folder_preview_token(
    preview: DriveFolderPreview,
    *,
    owner_user_id: str,
    project_id: str,
) -> str:
    if not preview.complete or preview.blocker is not None:
        raise ValueError("Only a complete importable preview can be signed")
    canonical = {
        "version": 1,
        "owner_user_id": owner_user_id,
        "project_id": project_id,
        "folder_id": preview.folder_id,
        "accepted": [
            {
                "id": item.metadata.id,
                "name": item.metadata.name,
                "mime_type": item.mime_type,
                "size_bytes": item.metadata.size_bytes,
                "created_time": item.metadata.created_time,
                "revision_id": getattr(item.metadata, "head_revision_id", None),
                "md5_checksum": getattr(item.metadata, "md5_checksum", None),
                "relative_path": item.relative_path,
            }
            for item in preview.accepted
        ],
        "skipped": [
            {
                "id": item.id,
                "relative_path": item.relative_path,
                "reason": item.reason.value,
            }
            for item in preview.skipped
        ],
    }
    serialized = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _skip_reason(
    item: GoogleDriveMetadata,
    normalized_mime: str | None,
    *,
    max_upload_bytes: int,
) -> DriveFolderSkipReason | None:
    if not is_supported_source_mime_type(normalized_mime):
        return DriveFolderSkipReason.unsupported
    if item.size_bytes == 0:
        return DriveFolderSkipReason.empty
    if item.size_bytes is not None and item.size_bytes > max_upload_bytes:
        return DriveFolderSkipReason.oversized
    if parse_authoritative_source_created_at(item.created_time) is None:
        return DriveFolderSkipReason.creation_time_unavailable
    return None


def _safe_path_segment(name: str | None, fallback_id: str) -> str:
    value = (name or "").strip() or f"Google Drive item {fallback_id}"
    return value.replace("/", "／").replace("\\", "＼")[:255]
