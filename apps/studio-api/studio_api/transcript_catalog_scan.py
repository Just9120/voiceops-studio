from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Callable, Mapping

import httpx

from .google_drive import GOOGLE_FOLDER_MIME_TYPE
from .google_docs_output import GOOGLE_DOC_MIME_TYPE
from .source_creation import parse_authoritative_source_created_at
from .transcript_catalog_migration import CatalogDocumentStandardStatus
from .transcript_document_selection import (
    TranscriptDocumentSelectionError,
    TranscriptDocumentSelectionReason,
    normalize_transcript_document_selection,
)
from .transcript_document import (
    LEGACY_TRANSCRIPT_BODY_LABEL,
    LEGACY_TRANSCRIPT_METADATA_LABEL,
    TRANSCRIPT_BODY_LABEL,
    TRANSCRIPT_METADATA_LABEL,
    segment_transcript_for_readability,
)


GOOGLE_DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
GOOGLE_DOCS_DOCUMENTS_URL = "https://docs.googleapis.com/v1/documents"
CATALOG_SCAN_PAGE_SIZE = 100
CATALOG_SCAN_MAX_ITEMS = 5_000
CATALOG_SCAN_MAX_PAGES = 100
CATALOG_DRIVE_FIELDS = (
    "nextPageToken,incompleteSearch,"
    "files(id,name,mimeType,createdTime,modifiedTime)"
)
CATALOG_SELECTED_DRIVE_FIELDS = (
    "id,name,mimeType,parents,trashed,createdTime,modifiedTime"
)
CATALOG_DOCS_TEXT_FIELDS = (
    "body(content(paragraph(elements(textRun(content)))))"
)
DRIVE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,256}$")

TRANSCRIPT_REQUIRED_METADATA_PREFIXES = (
    "Provider:",
    "Model:",
    "Language:",
)
TRANSCRIPT_DATE_METADATA_PREFIX = "Created at:"
TRANSCRIPT_OPTIONAL_METADATA_PREFIXES = (
    "Speakers:",  # Read old documents; new output does not require this boolean.
    "Audio processing:",
    "Segment project:",
    "Segment time range:",
    "Original source:",
    "Source:",
    "Preparation:",
    "Timeline:",
    "Transformations:",
    "Recording date provenance:",
    "Clip:",
)
TRANSCRIPT_LEGACY_METADATA_PREFIXES = (
    "Source file:",
    "Source mode:",
)


class CatalogGoogleReadReason(str, Enum):
    authentication_rejected = "authentication_rejected"
    request_rejected = "request_rejected"
    rate_limited = "rate_limited"
    unavailable = "unavailable"
    timeout = "timeout"
    malformed_response = "malformed_response"
    incomplete_search = "incomplete_search"
    limit_exceeded = "limit_exceeded"
    document_not_found = "document_not_found"


class CatalogGoogleReadError(RuntimeError):
    def __init__(self, reason: CatalogGoogleReadReason):
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True)
class CatalogGoogleDocumentMetadata:
    drive_document_id: str = field(repr=False)
    name: str | None
    created_time: str | None
    modified_time: str | None


@dataclass(frozen=True)
class CatalogGoogleFolderScan:
    documents: tuple[CatalogGoogleDocumentMetadata, ...]
    nested_folder_count: int
    skipped_non_document_count: int
    pages_scanned: int


@dataclass(frozen=True)
class CatalogGoogleDocumentSelection:
    documents: tuple[CatalogGoogleDocumentMetadata, ...]

    def __repr__(self) -> str:
        return (
            "CatalogGoogleDocumentSelection("
            f"document_count={len(self.documents)!r}, documents=<redacted>)"
        )


@dataclass(frozen=True)
class GoogleTranscriptCatalogReader:
    """Read an explicitly approved folder without persisting Google payloads."""

    drive_endpoint: str = GOOGLE_DRIVE_FILES_URL
    docs_endpoint: str = GOOGLE_DOCS_DOCUMENTS_URL
    timeout: float = 30.0
    client: httpx.Client | None = field(default=None, repr=False)
    get: Callable[..., httpx.Response] | None = field(default=None, repr=False)

    def inspect_selected_documents(
        self,
        *,
        access_token: str,
        folder_id: str,
        document_ids: tuple[str, ...],
    ) -> CatalogGoogleDocumentSelection:
        """Revalidate one Picker-selected folder and its explicit documents."""

        token = _private_value(access_token, label="access token")
        selection = normalize_transcript_document_selection(
            folder_id=folder_id,
            document_ids=document_ids,
        )
        folder_payload = self._get_json(
            f"{self.drive_endpoint}/{selection.folder_id}",
            access_token=token,
            params={
                "fields": CATALOG_SELECTED_DRIVE_FIELDS,
                "supportsAllDrives": "true",
            },
            not_found_reason=CatalogGoogleReadReason.request_rejected,
        )
        _validate_selected_folder(
            folder_payload,
            expected_folder_id=selection.folder_id,
        )

        documents = []
        for document_id in selection.document_ids:
            payload = self._get_json(
                f"{self.drive_endpoint}/{document_id}",
                access_token=token,
                params={
                    "fields": CATALOG_SELECTED_DRIVE_FIELDS,
                    "supportsAllDrives": "true",
                },
                not_found_reason=CatalogGoogleReadReason.document_not_found,
            )
            documents.append(
                _selected_document_metadata(
                    payload,
                    expected_document_id=document_id,
                    selected_folder_id=selection.folder_id,
                )
            )
        documents.sort(
            key=lambda item: (
                (item.name or "").casefold(),
                item.drive_document_id,
            )
        )
        return CatalogGoogleDocumentSelection(documents=tuple(documents))

    def inspect_document(
        self,
        *,
        access_token: str,
        document_id: str,
    ) -> CatalogGoogleDocumentMetadata:
        """Revalidate one explicitly selected native Google Doc."""

        token = _private_value(access_token, label="access token")
        private_document_id = _drive_id(document_id, label="document")
        payload = self._get_json(
            f"{self.drive_endpoint}/{private_document_id}",
            access_token=token,
            params={
                "fields": CATALOG_SELECTED_DRIVE_FIELDS,
                "supportsAllDrives": "true",
            },
            not_found_reason=CatalogGoogleReadReason.document_not_found,
            forbidden_reason=CatalogGoogleReadReason.request_rejected,
        )
        return _standalone_document_metadata(
            payload,
            expected_document_id=private_document_id,
        )

    def scan_folder(
        self,
        *,
        access_token: str,
        folder_id: str,
        max_items: int = CATALOG_SCAN_MAX_ITEMS,
        max_pages: int = CATALOG_SCAN_MAX_PAGES,
        progress: Callable[[str, int, int | None], None] | None = None,
    ) -> CatalogGoogleFolderScan:
        """Recursively list one explicitly selected folder and descendants."""

        token = _private_value(access_token, label="access token")
        selected_folder_id = _drive_id(folder_id, label="folder")
        safe_max_items = _bounded_limit(
            max_items,
            maximum=CATALOG_SCAN_MAX_ITEMS,
            label="catalog scan items",
        )
        safe_max_pages = _bounded_limit(
            max_pages,
            maximum=CATALOG_SCAN_MAX_PAGES,
            label="catalog scan pages",
        )
        folder_payload = self._get_json(
            f"{self.drive_endpoint}/{selected_folder_id}",
            access_token=token,
            params={
                "fields": CATALOG_SELECTED_DRIVE_FIELDS,
                "supportsAllDrives": "true",
            },
            not_found_reason=CatalogGoogleReadReason.request_rejected,
        )
        _validate_selected_folder(
            folder_payload,
            expected_folder_id=selected_folder_id,
        )
        documents: list[CatalogGoogleDocumentMetadata] = []
        nested_folder_count = 0
        skipped_non_document_count = 0
        seen_ids: set[str] = {selected_folder_id}
        pending_folders = deque([selected_folder_id])
        pages_scanned = 0
        items_scanned = 0

        while pending_folders:
            current_folder_id = pending_folders.popleft()
            seen_page_tokens: set[str] = set()
            page_token: str | None = None
            while True:
                if pages_scanned >= safe_max_pages:
                    raise CatalogGoogleReadError(
                        CatalogGoogleReadReason.limit_exceeded
                    )
                params = {
                    "q": (
                        f"'{current_folder_id}' in parents "
                        "and trashed = false"
                    ),
                    "fields": CATALOG_DRIVE_FIELDS,
                    "pageSize": str(CATALOG_SCAN_PAGE_SIZE),
                    "spaces": "drive",
                    "supportsAllDrives": "true",
                    "includeItemsFromAllDrives": "true",
                }
                if page_token:
                    params["pageToken"] = page_token
                payload = self._get_json(
                    self.drive_endpoint,
                    access_token=token,
                    params=params,
                    not_found_reason=(
                        CatalogGoogleReadReason.request_rejected
                    ),
                )
                pages_scanned += 1
                if progress is not None:
                    progress("scanning", pages_scanned, None)
                incomplete_search = payload.get("incompleteSearch")
                if incomplete_search is not None and not isinstance(
                    incomplete_search,
                    bool,
                ):
                    raise CatalogGoogleReadError(
                        CatalogGoogleReadReason.malformed_response
                    )
                if incomplete_search is True:
                    raise CatalogGoogleReadError(
                        CatalogGoogleReadReason.incomplete_search
                    )
                raw_items = payload.get("files")
                if not isinstance(raw_items, list):
                    raise CatalogGoogleReadError(
                        CatalogGoogleReadReason.malformed_response
                    )
                for raw_item in raw_items:
                    items_scanned += 1
                    if items_scanned > safe_max_items:
                        raise CatalogGoogleReadError(
                            CatalogGoogleReadReason.limit_exceeded
                        )
                    (
                        item_id,
                        name,
                        mime_type,
                        created_time,
                        modified_time,
                    ) = _normalize_drive_item(raw_item)
                    if item_id in seen_ids:
                        raise CatalogGoogleReadError(
                            CatalogGoogleReadReason.malformed_response
                        )
                    seen_ids.add(item_id)
                    if mime_type == GOOGLE_DOC_MIME_TYPE:
                        documents.append(
                            CatalogGoogleDocumentMetadata(
                                drive_document_id=item_id,
                                name=name,
                                created_time=created_time,
                                modified_time=modified_time,
                            )
                        )
                    elif mime_type == GOOGLE_FOLDER_MIME_TYPE:
                        nested_folder_count += 1
                        pending_folders.append(item_id)
                    else:
                        skipped_non_document_count += 1

                next_page_token = payload.get("nextPageToken")
                if next_page_token is None:
                    break
                if (
                    not isinstance(next_page_token, str)
                    or not next_page_token.strip()
                    or next_page_token in seen_page_tokens
                ):
                    raise CatalogGoogleReadError(
                        CatalogGoogleReadReason.malformed_response
                    )
                seen_page_tokens.add(next_page_token)
                page_token = next_page_token

        documents.sort(
            key=lambda item: (
                (item.name or "").casefold(),
                item.drive_document_id,
            )
        )
        return CatalogGoogleFolderScan(
            documents=tuple(documents),
            nested_folder_count=nested_folder_count,
            skipped_non_document_count=skipped_non_document_count,
            pages_scanned=pages_scanned,
        )

    def read_document_text(
        self,
        *,
        access_token: str,
        document_id: str,
    ) -> str:
        """Read first-tab plain text transiently for standard classification."""

        token = _private_value(access_token, label="access token")
        private_document_id = _drive_id(document_id, label="document")
        payload = self._get_json(
            f"{self.docs_endpoint}/{private_document_id}",
            access_token=token,
            params={
                "fields": CATALOG_DOCS_TEXT_FIELDS,
                "includeTabsContent": "false",
            },
            not_found_reason=CatalogGoogleReadReason.document_not_found,
            forbidden_reason=CatalogGoogleReadReason.request_rejected,
        )
        return extract_google_document_plain_text(payload)

    def _get_json(
        self,
        url: str,
        *,
        access_token: str,
        params: Mapping[str, str],
        not_found_reason: CatalogGoogleReadReason,
        forbidden_reason: CatalogGoogleReadReason = (
            CatalogGoogleReadReason.authentication_rejected
        ),
    ) -> Mapping[str, Any]:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        try:
            if self.get is not None:
                response = self.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=self.timeout,
                )
            elif self.client is not None:
                response = self.client.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=self.timeout,
                )
            else:
                with httpx.Client() as client:
                    response = client.get(
                        url,
                        headers=headers,
                        params=params,
                        timeout=self.timeout,
                    )
        except httpx.TimeoutException as exc:
            raise CatalogGoogleReadError(
                CatalogGoogleReadReason.timeout
            ) from exc
        except httpx.HTTPError as exc:
            raise CatalogGoogleReadError(
                CatalogGoogleReadReason.unavailable
            ) from exc

        _raise_for_catalog_status(
            response.status_code,
            not_found_reason=not_found_reason,
            forbidden_reason=forbidden_reason,
        )
        try:
            payload = response.json()
        except Exception as exc:
            raise CatalogGoogleReadError(
                CatalogGoogleReadReason.malformed_response
            ) from exc
        if not isinstance(payload, Mapping):
            raise CatalogGoogleReadError(
                CatalogGoogleReadReason.malformed_response
            )
        return payload


def extract_google_document_plain_text(payload: Mapping[str, Any]) -> str:
    """Extract only paragraph text from a Google Docs response."""

    if not isinstance(payload, Mapping):
        raise CatalogGoogleReadError(
            CatalogGoogleReadReason.malformed_response
        )
    body = payload.get("body")
    content = body.get("content") if isinstance(body, Mapping) else None
    if not isinstance(content, list):
        raise CatalogGoogleReadError(
            CatalogGoogleReadReason.malformed_response
        )
    parts: list[str] = []
    for structural_element in content:
        if not isinstance(structural_element, Mapping):
            raise CatalogGoogleReadError(
                CatalogGoogleReadReason.malformed_response
            )
        paragraph = structural_element.get("paragraph")
        if paragraph is None:
            continue
        elements = (
            paragraph.get("elements")
            if isinstance(paragraph, Mapping)
            else None
        )
        if not isinstance(elements, list):
            raise CatalogGoogleReadError(
                CatalogGoogleReadReason.malformed_response
            )
        for element in elements:
            if not isinstance(element, Mapping):
                raise CatalogGoogleReadError(
                    CatalogGoogleReadReason.malformed_response
                )
            text_run = element.get("textRun")
            if text_run is None:
                continue
            text = (
                text_run.get("content")
                if isinstance(text_run, Mapping)
                else None
            )
            if not isinstance(text, str):
                raise CatalogGoogleReadError(
                    CatalogGoogleReadReason.malformed_response
                )
            parts.append(text)
    return normalize_transcript_document_text("".join(parts))


def classify_transcript_document_standard(
    document_text: str,
    *,
    authoritative_created_at: datetime | None = None,
) -> CatalogDocumentStandardStatus:
    """Classify transient document text without retaining or returning it."""

    normalized = normalize_transcript_document_text(document_text)
    if not normalized:
        return CatalogDocumentStandardStatus.unstructured
    lines = [line.strip() for line in normalized.split("\n")]
    structure = _transcript_structure(lines)
    if structure is None:
        return CatalogDocumentStandardStatus.unstructured
    metadata_index, transcript_index, localized = structure
    if metadata_index < 1 or transcript_index <= metadata_index + 1:
        return CatalogDocumentStandardStatus.unstructured

    metadata_lines = [
        line for line in lines[metadata_index + 1 : transcript_index] if line
    ]
    if any(
        line.startswith(prefix)
        for line in metadata_lines
        for prefix in TRANSCRIPT_LEGACY_METADATA_PREFIXES
    ):
        return CatalogDocumentStandardStatus.outdated
    required_count = len(TRANSCRIPT_REQUIRED_METADATA_PREFIXES)
    required_lines = metadata_lines[:required_count]
    required_match = len(required_lines) == required_count and all(
        line.startswith(prefix)
        for line, prefix in zip(
            required_lines,
            TRANSCRIPT_REQUIRED_METADATA_PREFIXES,
        )
    )
    remaining_lines = metadata_lines[required_count:]
    if remaining_lines and remaining_lines[0].startswith("Speakers:"):
        remaining_lines = remaining_lines[1:]
    visible_created_at = None
    if remaining_lines and remaining_lines[0].startswith(
        TRANSCRIPT_DATE_METADATA_PREFIX
    ):
        visible_created_at = parse_transcript_document_created_at(
            remaining_lines[0]
        )
        if visible_created_at is None:
            return CatalogDocumentStandardStatus.outdated
        remaining_lines = remaining_lines[1:]
    optional_match = all(
        line.startswith(TRANSCRIPT_OPTIONAL_METADATA_PREFIXES)
        for line in remaining_lines
    )
    if required_match and optional_match:
        expected_created_at = _normalized_datetime(
            authoritative_created_at
        )
        if (
            expected_created_at is not None
            and (
                visible_created_at is not None
                and visible_created_at != expected_created_at
            )
        ):
            return CatalogDocumentStandardStatus.outdated
        body = "\n".join(normalized.split("\n")[transcript_index + 1:]).strip()
        if not body:
            return CatalogDocumentStandardStatus.unstructured
        if segment_transcript_for_readability(body) != body:
            return CatalogDocumentStandardStatus.outdated
        return (
            CatalogDocumentStandardStatus.current
            if localized
            else CatalogDocumentStandardStatus.outdated
        )
    if any(
        line.startswith(prefix)
        for line in metadata_lines
        for prefix in (
            *TRANSCRIPT_REQUIRED_METADATA_PREFIXES,
            TRANSCRIPT_DATE_METADATA_PREFIX,
            *TRANSCRIPT_OPTIONAL_METADATA_PREFIXES,
        )
    ):
        return CatalogDocumentStandardStatus.outdated
    return CatalogDocumentStandardStatus.unstructured


def _transcript_structure(
    lines: list[str],
) -> tuple[int, int, bool] | None:
    for metadata_label, body_label, localized in (
        (TRANSCRIPT_METADATA_LABEL, TRANSCRIPT_BODY_LABEL, True),
        (
            LEGACY_TRANSCRIPT_METADATA_LABEL,
            LEGACY_TRANSCRIPT_BODY_LABEL,
            False,
        ),
    ):
        try:
            metadata_index = lines.index(metadata_label)
            transcript_index = lines.index(body_label, metadata_index + 1)
        except ValueError:
            continue
        if metadata_index >= 1 and transcript_index > metadata_index + 1:
            return metadata_index, transcript_index, localized
    return None


def parse_transcript_document_created_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.startswith("Created at:"):
        return None
    parsed = parse_authoritative_source_created_at(
        value.removeprefix("Created at:").strip()
    )
    return _normalized_datetime(parsed)


def _normalized_datetime(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0)


def normalize_transcript_document_text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Transcript document text must be a string")
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _normalize_drive_item(
    raw_item: object,
) -> tuple[str, str | None, str, str | None, str | None]:
    if not isinstance(raw_item, Mapping):
        raise CatalogGoogleReadError(
            CatalogGoogleReadReason.malformed_response
        )
    try:
        item_id = _drive_id(raw_item.get("id"), label="document")
    except ValueError as exc:
        raise CatalogGoogleReadError(
            CatalogGoogleReadReason.malformed_response
        ) from exc
    mime_type = raw_item.get("mimeType")
    if not isinstance(mime_type, str) or not mime_type.strip():
        raise CatalogGoogleReadError(
            CatalogGoogleReadReason.malformed_response
        )
    name = raw_item.get("name")
    if name is not None and not isinstance(name, str):
        raise CatalogGoogleReadError(
            CatalogGoogleReadReason.malformed_response
        )
    return (
        item_id,
        name,
        mime_type,
        _optional_string(raw_item.get("createdTime")),
        _optional_string(raw_item.get("modifiedTime")),
    )


def _validate_selected_folder(
    payload: Mapping[str, Any],
    *,
    expected_folder_id: str,
) -> None:
    item_id, _name, mime_type, _created_time, _modified_time = (
        _normalize_drive_item(payload)
    )
    if item_id != expected_folder_id or mime_type != GOOGLE_FOLDER_MIME_TYPE:
        raise TranscriptDocumentSelectionError(
            TranscriptDocumentSelectionReason.folder_invalid
        )
    if _required_bool(payload.get("trashed")):
        raise TranscriptDocumentSelectionError(
            TranscriptDocumentSelectionReason.folder_invalid
        )


def _selected_document_metadata(
    payload: Mapping[str, Any],
    *,
    expected_document_id: str,
    selected_folder_id: str,
) -> CatalogGoogleDocumentMetadata:
    metadata = _standalone_document_metadata(
        payload,
        expected_document_id=expected_document_id,
    )
    parents = payload.get("parents")
    if (
        not isinstance(parents, list)
        or any(not isinstance(parent, str) for parent in parents)
        or selected_folder_id not in parents
    ):
        raise TranscriptDocumentSelectionError(
            TranscriptDocumentSelectionReason.document_out_of_folder
        )
    return metadata


def _standalone_document_metadata(
    payload: Mapping[str, Any],
    *,
    expected_document_id: str,
) -> CatalogGoogleDocumentMetadata:
    item_id, name, mime_type, created_time, modified_time = (
        _normalize_drive_item(payload)
    )
    if item_id != expected_document_id:
        raise TranscriptDocumentSelectionError(
            TranscriptDocumentSelectionReason.document_invalid
        )
    if _required_bool(payload.get("trashed")):
        raise TranscriptDocumentSelectionError(
            TranscriptDocumentSelectionReason.document_trashed
        )
    if mime_type != GOOGLE_DOC_MIME_TYPE:
        raise TranscriptDocumentSelectionError(
            TranscriptDocumentSelectionReason.document_not_google_doc
        )
    return CatalogGoogleDocumentMetadata(
        drive_document_id=item_id,
        name=name,
        created_time=created_time,
        modified_time=modified_time,
    )


def _raise_for_catalog_status(
    status_code: int,
    *,
    not_found_reason: CatalogGoogleReadReason,
    forbidden_reason: CatalogGoogleReadReason = (
        CatalogGoogleReadReason.authentication_rejected
    ),
) -> None:
    if 200 <= status_code < 300:
        return
    if status_code == 401:
        reason = CatalogGoogleReadReason.authentication_rejected
    elif status_code == 403:
        reason = forbidden_reason
    elif status_code == 404:
        reason = not_found_reason
    elif status_code == 429:
        reason = CatalogGoogleReadReason.rate_limited
    elif status_code >= 500:
        reason = CatalogGoogleReadReason.unavailable
    else:
        reason = CatalogGoogleReadReason.request_rejected
    raise CatalogGoogleReadError(reason)


def _drive_id(value: object, *, label: str) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not DRIVE_ID_PATTERN.fullmatch(cleaned):
        raise ValueError(f"Catalog Google {label} identity is invalid")
    return cleaned


def _private_value(value: object, *, label: str) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        raise ValueError(f"Catalog Google {label} is required")
    return cleaned


def _bounded_limit(value: object, *, maximum: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Catalog {label} limit is invalid")
    if value < 1 or value > maximum:
        raise ValueError(f"Catalog {label} limit is invalid")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CatalogGoogleReadError(
            CatalogGoogleReadReason.malformed_response
        )
    return value


def _required_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise CatalogGoogleReadError(
            CatalogGoogleReadReason.malformed_response
        )
    return value
