from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

SUPPORTED_SOURCE_MIME_PREFIXES = ("audio/", "video/")
SUPPORTED_SOURCE_MIME_TYPES = {"application/ogg"}
DEFAULT_SOURCE_RETENTION_TTL_SECONDS = 259200
SOURCE_RETENTION_TTL_OPTIONS_SECONDS = (259200, 604800, 2592000)


def effective_source_retention_seconds(stored_seconds: int) -> int:
    """Apply the current policy only to future uploads, retaining legacy rows."""
    if stored_seconds in SOURCE_RETENTION_TTL_OPTIONS_SECONDS:
        return stored_seconds
    return DEFAULT_SOURCE_RETENTION_TTL_SECONDS


def browser_source_upload_policy(
    max_upload_bytes: int,
    *,
    local_upload_enabled: bool,
    multipart_threshold_bytes: int,
    multipart_part_size_bytes: int,
) -> dict[str, object]:
    return {
        "local_upload_enabled": local_upload_enabled,
        "max_upload_bytes": max_upload_bytes,
        "multipart_threshold_bytes": multipart_threshold_bytes,
        "multipart_part_size_bytes": multipart_part_size_bytes,
        "supported_mime_prefixes": list(SUPPORTED_SOURCE_MIME_PREFIXES),
        "supported_mime_types": sorted(SUPPORTED_SOURCE_MIME_TYPES),
    }


class UploadedObjectMetadataIssue(str, Enum):
    metadata_unavailable = "metadata_unavailable"
    source_too_large = "source_too_large"
    unsupported_mime_type = "unsupported_mime_type"
    source_size_mismatch = "source_size_mismatch"
    source_mime_mismatch = "source_mime_mismatch"


def normalize_source_mime_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def is_supported_source_mime_type(value: str | None) -> bool:
    normalized = normalize_source_mime_type(value)
    if not normalized:
        return False
    return normalized.startswith(SUPPORTED_SOURCE_MIME_PREFIXES) or normalized in SUPPORTED_SOURCE_MIME_TYPES


def validate_source_size(size_bytes: int | None, max_bytes: int) -> bool:
    if size_bytes is None:
        return True
    return 0 <= size_bytes <= max_bytes


def is_source_expired(expires_at: datetime | None, now: datetime) -> bool:
    if expires_at is None:
        return False
    return _as_utc_aware(expires_at) <= _as_utc_aware(now)


def _as_utc_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def operation_retains_source(job, expires_at: datetime | None, now: datetime) -> bool:
    """Finish an admitted operation across TTL; never admit a new one after TTL."""
    admitted = getattr(job, "source_access_started_at", None)
    lease_end = getattr(job, "lease_expires_at", None)
    status = str(getattr(getattr(job, "status", None), "value", getattr(job, "status", "")))
    running = status in {"processing", "analyzing"} or (
        status in {"completed", "preview_ready"}
        and getattr(job, "current_stage", None) in {"audio_download_rendering", "google_drive_upload"}
    )
    return bool(running and admitted and expires_at and lease_end
        and getattr(job, "lease_owner_id", None)
        and getattr(job, "cancel_requested_at", None) is None
        and _as_utc_aware(admitted) < _as_utc_aware(expires_at)
        and _as_utc_aware(lease_end) > _as_utc_aware(now))


def uploaded_object_metadata_issue(
    *,
    expected_size_bytes: int | None,
    expected_mime_type: str | None,
    actual_size_bytes: int | None,
    actual_mime_type: str | None,
    max_bytes: int,
) -> UploadedObjectMetadataIssue | None:
    expected_mime = normalize_source_mime_type(expected_mime_type)
    actual_mime = normalize_source_mime_type(actual_mime_type)
    if (
        expected_size_bytes is None
        or expected_mime is None
        or actual_size_bytes is None
        or actual_size_bytes < 0
        or actual_mime is None
    ):
        return UploadedObjectMetadataIssue.metadata_unavailable
    if actual_size_bytes > max_bytes:
        return UploadedObjectMetadataIssue.source_too_large
    if not is_supported_source_mime_type(actual_mime):
        return UploadedObjectMetadataIssue.unsupported_mime_type
    if actual_size_bytes != expected_size_bytes:
        return UploadedObjectMetadataIssue.source_size_mismatch
    if actual_mime != expected_mime:
        return UploadedObjectMetadataIssue.source_mime_mismatch
    return None
