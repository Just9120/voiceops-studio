from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Mapping

import httpx

from .transcript_document_metadata import compact_provenance_lines, title_has_recording_date
from .transcript_catalog_migration import CatalogDocumentStandardStatus
from .transcript_catalog_scan import (
    DRIVE_ID_PATTERN,
    GOOGLE_DOCS_DOCUMENTS_URL,
    TRANSCRIPT_BODY_LABEL,
    TRANSCRIPT_DATE_METADATA_PREFIX,
    TRANSCRIPT_METADATA_LABEL,
    TRANSCRIPT_OPTIONAL_METADATA_PREFIXES,
    TRANSCRIPT_REQUIRED_METADATA_PREFIXES,
    classify_transcript_document_standard,
    normalize_transcript_document_text,
)
from .source_creation import parse_authoritative_source_created_at
from .transcript_document import (
    LEGACY_TRANSCRIPT_BODY_LABEL,
    LEGACY_TRANSCRIPT_METADATA_LABEL,
    build_transcript_document_style_requests,
    build_transcript_document_text,
)


CATALOG_STANDARDIZATION_MAX_TEXT_CHARS = 1_000_000
CATALOG_STANDARDIZATION_GET_FIELDS = "revisionId,tabs"


class CatalogGoogleWriteReason(str, Enum):
    authentication_rejected = "authentication_rejected"
    request_rejected = "request_rejected"
    rate_limited = "rate_limited"
    unavailable = "unavailable"
    timeout = "timeout"
    malformed_response = "malformed_response"
    document_not_found = "document_not_found"
    revision_conflict_or_rejected = "revision_conflict_or_rejected"
    multiple_tabs = "multiple_tabs"
    unsupported_content = "unsupported_content"
    classification_changed = "classification_changed"
    empty_transcript = "empty_transcript"
    limit_exceeded = "limit_exceeded"


class CatalogGoogleWriteError(RuntimeError):
    def __init__(self, reason: CatalogGoogleWriteReason):
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True)
class CatalogGoogleDocumentSnapshot:
    document_id: str = field(repr=False)
    revision_id: str = field(repr=False)
    tab_id: str = field(repr=False)
    document_text: str = field(repr=False)
    end_index: int

    def __repr__(self) -> str:
        return (
            "CatalogGoogleDocumentSnapshot("
            "document_id=<redacted>, revision_id=<redacted>, "
            "tab_id=<redacted>, document_text=<redacted>, "
            f"end_index={self.end_index!r})"
        )


@dataclass(frozen=True)
class CatalogStandardizationResult:
    status: CatalogDocumentStandardStatus
    changed: bool
    character_count: int


@dataclass(frozen=True)
class GoogleTranscriptCatalogStandardizer:
    """Read and replace one Google Doc under exact revision control."""

    docs_endpoint: str = GOOGLE_DOCS_DOCUMENTS_URL
    timeout: float = 30.0
    client: httpx.Client | None = field(default=None, repr=False)
    get: Callable[..., httpx.Response] | None = field(
        default=None,
        repr=False,
    )
    post: Callable[..., httpx.Response] | None = field(
        default=None,
        repr=False,
    )

    def read_document(
        self,
        *,
        access_token: str,
        document_id: str,
    ) -> CatalogGoogleDocumentSnapshot:
        token = _private_value(access_token, label="access token")
        private_document_id = _document_id(document_id)
        response = self._request(
            "get",
            f"{self.docs_endpoint}/{private_document_id}",
            headers=_google_headers(token),
            params={
                "fields": CATALOG_STANDARDIZATION_GET_FIELDS,
                "includeTabsContent": "true",
                "suggestionsViewMode": "SUGGESTIONS_INLINE",
            },
        )
        _raise_for_read_status(response.status_code)
        payload = _response_mapping(response)
        return normalize_standardization_snapshot(
            payload,
            expected_document_id=private_document_id,
        )

    def replace_document_text(
        self,
        *,
        access_token: str,
        snapshot: CatalogGoogleDocumentSnapshot,
        document_text: str,
    ) -> None:
        token = _private_value(access_token, label="access token")
        if not isinstance(snapshot, CatalogGoogleDocumentSnapshot):
            raise ValueError("Catalog Google document snapshot is required")
        private_document_id = _document_id(snapshot.document_id)
        replacement = _bounded_document_text(document_text)
        requests = []
        if snapshot.end_index > 2:
            requests.append(
                {
                    "deleteContentRange": {
                        "range": {
                            "startIndex": 1,
                            "endIndex": snapshot.end_index - 1,
                            "tabId": snapshot.tab_id,
                        }
                    }
                }
            )
        requests.append(
            {
                "insertText": {
                    "location": {
                        "index": 1,
                        "tabId": snapshot.tab_id,
                    },
                    "text": replacement,
                }
            }
        )
        try:
            requests.extend(
                build_transcript_document_style_requests(
                    replacement,
                    tab_id=snapshot.tab_id,
                )
            )
        except ValueError as exc:
            raise CatalogGoogleWriteError(
                CatalogGoogleWriteReason.malformed_response
            ) from exc
        response = self._request(
            "post",
            (
                f"{self.docs_endpoint}/{private_document_id}"
                ":batchUpdate"
            ),
            headers={
                **_google_headers(token),
                "Content-Type": "application/json",
            },
            json={
                "requests": requests,
                "writeControl": {
                    "requiredRevisionId": snapshot.revision_id,
                },
            },
        )
        _raise_for_write_status(response.status_code)
        payload = _response_mapping(response)
        if payload.get("documentId") != private_document_id:
            raise CatalogGoogleWriteError(
                CatalogGoogleWriteReason.malformed_response
            )

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        kwargs["timeout"] = self.timeout
        try:
            injected = self.get if method == "get" else self.post
            if injected is not None:
                return injected(url, **kwargs)
            if self.client is not None:
                return getattr(self.client, method)(url, **kwargs)
            with httpx.Client() as client:
                return getattr(client, method)(url, **kwargs)
        except httpx.TimeoutException as exc:
            raise CatalogGoogleWriteError(
                CatalogGoogleWriteReason.timeout
            ) from exc
        except httpx.HTTPError as exc:
            raise CatalogGoogleWriteError(
                CatalogGoogleWriteReason.unavailable
            ) from exc

    def __repr__(self) -> str:
        return (
            "GoogleTranscriptCatalogStandardizer("
            f"docs_endpoint={self.docs_endpoint!r})"
        )


def standardize_transcript_document_in_place(
    *,
    access_token: str,
    document_id: str,
    document_name: str | None,
    expected_status: CatalogDocumentStandardStatus,
    created_time: str | None = None,
    standardizer: GoogleTranscriptCatalogStandardizer | None = None,
) -> CatalogStandardizationResult:
    """Re-read and replace one eligible document without creating artifacts."""

    if (
        not isinstance(expected_status, CatalogDocumentStandardStatus)
        or expected_status
        not in {
            CatalogDocumentStandardStatus.current,
            CatalogDocumentStandardStatus.outdated,
            CatalogDocumentStandardStatus.unstructured,
        }
    ):
        raise ValueError("Catalog standardization status is invalid")
    authoritative_created_at = (
        parse_authoritative_source_created_at(created_time)
        if created_time is not None
        else None
    )
    if created_time is not None and authoritative_created_at is None:
        raise ValueError(
            "Authoritative source creation time is invalid"
        )
    transport = standardizer or GoogleTranscriptCatalogStandardizer()
    snapshot = transport.read_document(
        access_token=access_token,
        document_id=document_id,
    )
    actual_status = classify_transcript_document_standard(
        snapshot.document_text,
        authoritative_created_at=authoritative_created_at,
    )
    if actual_status == CatalogDocumentStandardStatus.current:
        return CatalogStandardizationResult(
            status=CatalogDocumentStandardStatus.current,
            changed=False,
            character_count=len(snapshot.document_text),
        )
    if actual_status != expected_status:
        raise CatalogGoogleWriteError(
            CatalogGoogleWriteReason.classification_changed
        )

    replacement = build_standardized_transcript_document_text(
        document_name=document_name,
        existing_document_text=snapshot.document_text,
        created_time=created_time,
    )
    if (
        classify_transcript_document_standard(
            replacement,
            authoritative_created_at=authoritative_created_at,
        )
        != CatalogDocumentStandardStatus.current
    ):
        raise CatalogGoogleWriteError(
            CatalogGoogleWriteReason.malformed_response
        )
    transport.replace_document_text(
        access_token=access_token,
        snapshot=snapshot,
        document_text=replacement,
    )
    return CatalogStandardizationResult(
        status=CatalogDocumentStandardStatus.current,
        changed=True,
        character_count=len(replacement),
    )


def normalize_standardization_snapshot(
    payload: Mapping[str, Any],
    *,
    expected_document_id: str,
) -> CatalogGoogleDocumentSnapshot:
    if not isinstance(payload, Mapping):
        raise CatalogGoogleWriteError(
            CatalogGoogleWriteReason.malformed_response
        )
    revision_id = _opaque_revision_id(payload.get("revisionId"))
    tabs = _flatten_tabs(payload.get("tabs"))
    if len(tabs) != 1:
        raise CatalogGoogleWriteError(
            CatalogGoogleWriteReason.multiple_tabs
        )
    tab = tabs[0]
    tab_properties = tab.get("tabProperties")
    tab_id = (
        tab_properties.get("tabId")
        if isinstance(tab_properties, Mapping)
        else None
    )
    private_tab_id = _private_value(tab_id, label="tab identity")
    document_tab = tab.get("documentTab")
    if isinstance(document_tab, Mapping) and any(
        document_tab.get(container)
        for container in ("headers", "footers", "footnotes")
    ):
        raise CatalogGoogleWriteError(
            CatalogGoogleWriteReason.unsupported_content
        )
    body = (
        document_tab.get("body")
        if isinstance(document_tab, Mapping)
        else None
    )
    content = body.get("content") if isinstance(body, Mapping) else None
    if not isinstance(content, list) or not content:
        raise CatalogGoogleWriteError(
            CatalogGoogleWriteReason.malformed_response
        )
    text_parts = []
    end_index = 1
    for structural_element in content:
        if not isinstance(structural_element, Mapping):
            raise CatalogGoogleWriteError(
                CatalogGoogleWriteReason.malformed_response
            )
        raw_end_index = structural_element.get("endIndex")
        if isinstance(raw_end_index, bool) or not isinstance(
            raw_end_index,
            int,
        ):
            raise CatalogGoogleWriteError(
                CatalogGoogleWriteReason.malformed_response
        )
        end_index = max(end_index, raw_end_index)
        paragraph = structural_element.get("paragraph")
        if paragraph is None:
            raw_start_index = structural_element.get("startIndex", 0)
            if (
                "sectionBreak" in structural_element
                and not isinstance(raw_start_index, bool)
                and isinstance(raw_start_index, int)
                and raw_start_index == 0
                and raw_end_index == 1
            ):
                continue
            raise CatalogGoogleWriteError(
                CatalogGoogleWriteReason.unsupported_content
            )
        elements = (
            paragraph.get("elements")
            if isinstance(paragraph, Mapping)
            else None
        )
        if not isinstance(elements, list):
            raise CatalogGoogleWriteError(
                CatalogGoogleWriteReason.malformed_response
            )
        for element in elements:
            if not isinstance(element, Mapping):
                raise CatalogGoogleWriteError(
                    CatalogGoogleWriteReason.malformed_response
                )
            text_run = element.get("textRun")
            if text_run is None:
                raise CatalogGoogleWriteError(
                    CatalogGoogleWriteReason.unsupported_content
                )
            text = (
                text_run.get("content")
                if isinstance(text_run, Mapping)
                else None
            )
            if not isinstance(text, str):
                raise CatalogGoogleWriteError(
                    CatalogGoogleWriteReason.malformed_response
                )
            text_parts.append(text)
    if end_index < 2:
        raise CatalogGoogleWriteError(
            CatalogGoogleWriteReason.malformed_response
        )
    document_text = normalize_transcript_document_text(
        "".join(text_parts)
    )
    if len(document_text) > CATALOG_STANDARDIZATION_MAX_TEXT_CHARS:
        raise CatalogGoogleWriteError(
            CatalogGoogleWriteReason.limit_exceeded
        )
    return CatalogGoogleDocumentSnapshot(
        document_id=_document_id(expected_document_id),
        revision_id=revision_id,
        tab_id=private_tab_id,
        document_text=document_text,
        end_index=end_index,
    )


def build_standardized_transcript_document_text(
    *,
    document_name: str | None,
    existing_document_text: str,
    created_time: str | None,
) -> str:
    title = _document_title(document_name)
    normalized = normalize_transcript_document_text(
        existing_document_text
    )
    metadata, transcript_body = _metadata_and_transcript_body(
        normalized,
        document_title=title,
    )
    if not transcript_body:
        raise CatalogGoogleWriteError(
            CatalogGoogleWriteReason.empty_transcript
        )
    if created_time is not None:
        created_at = _visible_timestamp(created_time)
        if created_at is None:
            raise ValueError(
                "Authoritative source creation time is invalid"
            )
    else:
        created_at = _preserved_visible_timestamp(
            metadata.get("Created at")
        )
    required_values = {
        "Provider": _metadata_value(metadata.get("Provider")),
        "Model": _metadata_value(metadata.get("Model")),
        "Language": _metadata_value(metadata.get("Language")),
    }
    metadata_lines = [
        f"{label}: {required_values[label]}"
        for label in ("Provider", "Model", "Language")
    ]
    if created_at is not None and not title_has_recording_date(title):
        metadata_lines.append(f"Created at: {created_at}")
    provenance_lines = []
    for prefix in TRANSCRIPT_OPTIONAL_METADATA_PREFIXES:
        label = prefix.removesuffix(":")
        value = metadata.get(label)
        if value:
            provenance_lines.append(f"{label}: {_metadata_value(value)}")
    metadata_lines.extend(compact_provenance_lines(provenance_lines))
    result = build_transcript_document_text(
        title=title,
        metadata_lines=metadata_lines,
        transcript_text=transcript_body,
    )
    return _bounded_document_text(result)


def _metadata_and_transcript_body(
    document_text: str,
    *,
    document_title: str,
) -> tuple[dict[str, str], str]:
    lines = document_text.split("\n")
    stripped = [line.strip() for line in lines]
    metadata = {}
    metadata_index = transcript_index = -1
    for metadata_label, body_label in (
        (TRANSCRIPT_METADATA_LABEL, TRANSCRIPT_BODY_LABEL),
        (LEGACY_TRANSCRIPT_METADATA_LABEL, LEGACY_TRANSCRIPT_BODY_LABEL),
    ):
        try:
            metadata_index = stripped.index(metadata_label)
            transcript_index = stripped.index(
                body_label,
                metadata_index + 1,
            )
        except ValueError:
            continue
        break
    if metadata_index >= 1 and transcript_index > metadata_index:
        allowed_labels = {
            prefix.removesuffix(":")
            for prefix in (
                *TRANSCRIPT_REQUIRED_METADATA_PREFIXES,
                TRANSCRIPT_DATE_METADATA_PREFIX,
                *TRANSCRIPT_OPTIONAL_METADATA_PREFIXES,
            )
        }
        for line in stripped[metadata_index + 1 : transcript_index]:
            if ":" not in line:
                continue
            label, value = line.split(":", 1)
            if label.strip() in allowed_labels and value.strip():
                metadata.setdefault(label.strip(), value.strip())
        body = normalize_transcript_document_text(
            "\n".join(lines[transcript_index + 1 :])
        )
        return metadata, body

    title_key = _comparison_key(document_title)
    first_line_key = _comparison_key(lines[0]) if lines else ""
    body_lines = (
        lines[1:]
        if title_key and first_line_key == title_key
        else lines
    )
    metadata, transcript_lines = _unstructured_legacy_metadata(body_lines)
    return metadata, normalize_transcript_document_text(
        "\n".join(transcript_lines)
    )


def _unstructured_legacy_metadata(
    lines: list[str],
) -> tuple[dict[str, str], list[str]]:
    metadata = {}
    body_lines = []
    metadata_prefix = True
    allowed_labels = {
        prefix.removesuffix(":")
        for prefix in (
            *TRANSCRIPT_REQUIRED_METADATA_PREFIXES,
            TRANSCRIPT_DATE_METADATA_PREFIX,
            *TRANSCRIPT_OPTIONAL_METADATA_PREFIXES,
        )
    }
    discarded_labels = {"Source file", "Source mode"}
    metadata_markers = {
        TRANSCRIPT_METADATA_LABEL,
        LEGACY_TRANSCRIPT_METADATA_LABEL,
    }
    body_markers = {TRANSCRIPT_BODY_LABEL, LEGACY_TRANSCRIPT_BODY_LABEL}

    for line in lines:
        stripped = line.strip()
        if metadata_prefix and not stripped:
            continue
        if metadata_prefix and stripped in metadata_markers:
            continue
        if metadata_prefix and stripped in body_markers:
            metadata_prefix = False
            continue
        if metadata_prefix and ":" in stripped:
            label, value = stripped.split(":", 1)
            normalized_label = label.strip()
            if normalized_label in allowed_labels:
                if value.strip():
                    metadata.setdefault(normalized_label, value.strip())
                continue
            if normalized_label in discarded_labels:
                continue
        metadata_prefix = False
        body_lines.append(line)

    return metadata, body_lines


def _flatten_tabs(raw_tabs: object) -> list[Mapping[str, Any]]:
    if not isinstance(raw_tabs, list) or not raw_tabs:
        raise CatalogGoogleWriteError(
            CatalogGoogleWriteReason.malformed_response
        )
    flattened = []

    def visit(raw_tab: object) -> None:
        if not isinstance(raw_tab, Mapping):
            raise CatalogGoogleWriteError(
                CatalogGoogleWriteReason.malformed_response
            )
        flattened.append(raw_tab)
        children = raw_tab.get("childTabs", [])
        if not isinstance(children, list):
            raise CatalogGoogleWriteError(
                CatalogGoogleWriteReason.malformed_response
            )
        for child in children:
            visit(child)

    for tab in raw_tabs:
        visit(tab)
    return flattened


def _response_mapping(response: httpx.Response) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:
        raise CatalogGoogleWriteError(
            CatalogGoogleWriteReason.malformed_response
        ) from exc
    if not isinstance(payload, Mapping):
        raise CatalogGoogleWriteError(
            CatalogGoogleWriteReason.malformed_response
        )
    return payload


def _raise_for_read_status(status_code: int) -> None:
    if 200 <= status_code < 300:
        return
    if status_code == 401:
        reason = CatalogGoogleWriteReason.authentication_rejected
    elif status_code == 403:
        reason = CatalogGoogleWriteReason.request_rejected
    elif status_code == 404:
        reason = CatalogGoogleWriteReason.document_not_found
    elif status_code == 429:
        reason = CatalogGoogleWriteReason.rate_limited
    elif status_code >= 500:
        reason = CatalogGoogleWriteReason.unavailable
    else:
        reason = CatalogGoogleWriteReason.request_rejected
    raise CatalogGoogleWriteError(reason)


def _raise_for_write_status(status_code: int) -> None:
    if 200 <= status_code < 300:
        return
    if status_code == 401:
        reason = CatalogGoogleWriteReason.authentication_rejected
    elif status_code == 403:
        reason = CatalogGoogleWriteReason.request_rejected
    elif status_code == 404:
        reason = CatalogGoogleWriteReason.document_not_found
    elif status_code == 429:
        reason = CatalogGoogleWriteReason.rate_limited
    elif status_code >= 500:
        reason = CatalogGoogleWriteReason.unavailable
    elif status_code in {400, 409}:
        reason = CatalogGoogleWriteReason.revision_conflict_or_rejected
    else:
        reason = CatalogGoogleWriteReason.request_rejected
    raise CatalogGoogleWriteError(reason)


def _visible_timestamp(value: object) -> str | None:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned or cleaned.casefold() == "unknown":
        return None
    parse_value = cleaned[:-1] + "+00:00" if cleaned.endswith("Z") else cleaned
    try:
        parsed = datetime.fromisoformat(parse_value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return (
        parsed.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _preserved_visible_timestamp(value: object) -> str | None:
    cleaned = value.strip() if isinstance(value, str) else ""
    if parse_authoritative_source_created_at(cleaned) is None:
        return None
    return cleaned


def _metadata_value(value: object) -> str:
    cleaned = (
        " ".join(value.replace("\x00", " ").split())
        if isinstance(value, str)
        else ""
    )
    return cleaned or "unknown"


def _document_title(value: object) -> str:
    cleaned = (
        " ".join(value.replace("\x00", " ").split())
        if isinstance(value, str)
        else ""
    )
    return cleaned or "Google Docs transcript"


def _bounded_document_text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Catalog standardized text must be a string")
    if not value or len(value) > CATALOG_STANDARDIZATION_MAX_TEXT_CHARS:
        raise CatalogGoogleWriteError(
            CatalogGoogleWriteReason.limit_exceeded
        )
    return value


def _document_id(value: object) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not DRIVE_ID_PATTERN.fullmatch(cleaned):
        raise ValueError("Catalog Google document identity is invalid")
    return cleaned


def _opaque_revision_id(value: object) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned or len(cleaned) > 1024:
        raise CatalogGoogleWriteError(
            CatalogGoogleWriteReason.malformed_response
        )
    return cleaned


def _private_value(value: object, *, label: str) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        raise ValueError(f"Catalog Google {label} is required")
    return cleaned


def _google_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _comparison_key(value: object) -> str:
    return (
        re.sub(r"\s+", " ", value).strip().casefold()
        if isinstance(value, str)
        else ""
    )
