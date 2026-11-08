from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from math import ceil
from typing import Callable

from sqlalchemy import select, union
from sqlalchemy.orm import Session

from .models import Source, SourceType
from .signed_cursor import decode_signed_cursor, encode_signed_cursor
from .source_storage import (
    AUDIO_PROCESSING_REFERENCE_CLASS,
    TRANSCRIPTION_REFERENCE_CLASS,
    StoredObject,
    get_source_storage,
    reference_storage_bucket,
    reference_storage_isolation_configured,
    reference_storage_settings,
)


_PLAN_NAMESPACE = "studio-storage-reconciliation-plan-v1"


class StorageReconciliationReason(str, Enum):
    unavailable = "unavailable"
    scan_truncated = "scan_truncated"
    plan_invalid = "plan_invalid"
    plan_changed = "plan_changed"


class StorageReconciliationError(RuntimeError):
    def __init__(self, reason: StorageReconciliationReason):
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True)
class OrphanCandidate:
    reference_class: str
    bucket: str
    object: StoredObject


@dataclass(frozen=True)
class StorageReconciliationScan:
    scanned_count: int
    protected_recent_count: int
    candidates: tuple[OrphanCandidate, ...]
    candidate_bytes: int
    truncated: bool


@dataclass(frozen=True)
class StorageReconciliationApplyResult:
    planned_count: int
    deleted_count: int
    failed_count: int
    deleted_bytes: int


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _owner_prefixes(owner_user_id: str) -> tuple[tuple[str, str], ...]:
    return (
        (TRANSCRIPTION_REFERENCE_CLASS, f"transcription/users/{owner_user_id}/"),
        (TRANSCRIPTION_REFERENCE_CLASS, f"users/{owner_user_id}/"),
        (AUDIO_PROCESSING_REFERENCE_CLASS, f"audio_processing/users/{owner_user_id}/"),
        (AUDIO_PROCESSING_REFERENCE_CLASS, f"audio-preparation/{owner_user_id}/"),
    )


def _referenced_storage_keys(db: Session, *, bucket: str, keys: tuple[str, ...]) -> set[str]:
    if not keys:
        return set()
    matches = select(Source.s3_object_key).where(
        Source.source_type == SourceType.local_upload,
        Source.s3_bucket == bucket,
        Source.s3_object_key.in_(keys),
    )
    return set(db.scalars(union(
        matches.where(Source.reference_class == TRANSCRIPTION_REFERENCE_CLASS),
        matches.where(Source.reference_class == AUDIO_PROCESSING_REFERENCE_CLASS),
    )))


def _candidate_digest(candidates: tuple[OrphanCandidate, ...]) -> str:
    payload = [
        {
            "class": item.reference_class,
            "bucket": item.bucket,
            "key": item.object.key,
            "size": item.object.size_bytes,
            "etag": item.object.etag,
            "modified": _as_utc(item.object.last_modified).isoformat(),
        }
        for item in candidates
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _plan_context(owner_user_id: str, scan: StorageReconciliationScan) -> dict[str, str]:
    return {
        "owner": owner_user_id,
        "count": str(len(scan.candidates)),
        "bytes": str(scan.candidate_bytes),
    }


def scan_owner_storage(
    db: Session,
    *,
    owner_user_id: str,
    settings,
    now: datetime,
    storage_factory: Callable = get_source_storage,
) -> StorageReconciliationScan:
    if not reference_storage_isolation_configured(settings):
        raise StorageReconciliationError(StorageReconciliationReason.unavailable)
    db.rollback()
    minimum_modified_at = _as_utc(now) - timedelta(seconds=settings.storage_orphan_min_age_seconds)
    scanned = 0
    protected_recent = 0
    truncated = False
    candidates: list[OrphanCandidate] = []
    observed: set[tuple[str, str, str]] = set()
    prefixes = _owner_prefixes(owner_user_id)
    # A provider may return short or empty pages even with a fresh cursor.
    pages_left = ceil(settings.storage_reconciliation_scan_limit / settings.storage_reconciliation_page_size) + len(prefixes) - 1
    for reference_class, prefix in prefixes:
        if scanned >= settings.storage_reconciliation_scan_limit:
            truncated = True
            break
        bucket = reference_storage_bucket(settings, reference_class)
        if not bucket:
            raise StorageReconciliationError(StorageReconciliationReason.unavailable)
        storage = storage_factory(reference_storage_settings(settings, reference_class))
        token = None
        seen_tokens: set[str] = set()
        while True:
            remaining = settings.storage_reconciliation_scan_limit - scanned
            if remaining <= 0 or pages_left <= 0:
                truncated = True
                break
            page_limit = min(settings.storage_reconciliation_page_size, remaining)
            pages_left -= 1
            page = storage.list_objects_page(
                prefix,
                continuation_token=token,
                max_keys=page_limit,
            )
            if len(page.objects) > page_limit or any(not item.key.startswith(prefix) for item in page.objects):
                raise StorageReconciliationError(StorageReconciliationReason.unavailable)
            # A reference protects physical bytes regardless of its owner or class.
            known = _referenced_storage_keys(db, bucket=bucket, keys=tuple(item.key for item in page.objects))
            db.rollback()
            for stored in page.objects:
                if not stored.key.startswith(prefix):
                    raise StorageReconciliationError(StorageReconciliationReason.unavailable)
                identity = (reference_class, bucket, stored.key)
                if identity in observed:
                    continue
                observed.add(identity)
                scanned += 1
                if stored.key in known:
                    continue
                if _as_utc(stored.last_modified) > minimum_modified_at:
                    protected_recent += 1
                    continue
                candidates.append(OrphanCandidate(reference_class, bucket, stored))
            token = page.next_token
            if token is None:
                break
            if token in seen_tokens:
                raise StorageReconciliationError(StorageReconciliationReason.unavailable)
            seen_tokens.add(token)
            if scanned >= settings.storage_reconciliation_scan_limit:
                truncated = True
                break
        if truncated:
            break
    ordered = tuple(sorted(candidates, key=lambda item: (item.reference_class, item.object.key)))
    return StorageReconciliationScan(
        scanned_count=scanned,
        protected_recent_count=protected_recent,
        candidates=ordered,
        candidate_bytes=sum(item.object.size_bytes for item in ordered),
        truncated=truncated,
    )


def issue_reconciliation_plan(
    *,
    owner_user_id: str,
    scan: StorageReconciliationScan,
    secret: str,
    now: datetime,
    ttl_seconds: int,
) -> tuple[str | None, datetime | None]:
    if scan.truncated:
        return None, None
    expires_at = _as_utc(now) + timedelta(seconds=ttl_seconds)
    token = encode_signed_cursor(
        expires_at,
        _candidate_digest(scan.candidates),
        _plan_context(owner_user_id, scan),
        secret,
        namespace=_PLAN_NAMESPACE,
    )
    return token, expires_at


def _plan_is_valid(
    token: str,
    *,
    owner_user_id: str,
    scan: StorageReconciliationScan,
    secret: str,
    now: datetime,
) -> bool:
    decoded = decode_signed_cursor(
        token,
        _plan_context(owner_user_id, scan),
        secret,
        namespace=_PLAN_NAMESPACE,
        max_length=1600,
    )
    if decoded is None:
        return False
    expires_at, digest = decoded
    return _as_utc(expires_at) > _as_utc(now) and digest == _candidate_digest(scan.candidates)


def apply_reconciliation_plan(
    db: Session,
    *,
    owner_user_id: str,
    plan_token: str,
    secret: str,
    settings,
    now: datetime,
    storage_factory: Callable = get_source_storage,
) -> StorageReconciliationApplyResult:
    scan = scan_owner_storage(
        db,
        owner_user_id=owner_user_id,
        settings=settings,
        now=now,
        storage_factory=storage_factory,
    )
    if scan.truncated or len(scan.candidates) > settings.storage_reconciliation_apply_limit:
        raise StorageReconciliationError(StorageReconciliationReason.scan_truncated)
    if not _plan_is_valid(
        plan_token,
        owner_user_id=owner_user_id,
        scan=scan,
        secret=secret,
        now=now,
    ):
        raise StorageReconciliationError(StorageReconciliationReason.plan_changed)
    deleted = 0
    deleted_bytes = 0
    failed = 0
    storages: dict[str, object] = {}
    for item in scan.candidates:
        try:
            storage = storages.get(item.reference_class)
            if storage is None:
                storage = storage_factory(reference_storage_settings(settings, item.reference_class))
                storages[item.reference_class] = storage
            head = storage.head_object(item.object.key)
            if (
                not item.object.etag
                or head.size_bytes != item.object.size_bytes
                or head.etag != item.object.etag
                or head.last_modified is None
                or _as_utc(head.last_modified) != _as_utc(item.object.last_modified)
            ):
                failed += 1
                continue
        except Exception:
            failed += 1
            continue
        referenced = _referenced_storage_keys(db, bucket=item.bucket, keys=(item.object.key,))
        db.rollback()
        if referenced:
            failed += 1
            continue
        try:
            if not storage.delete_object_verified(item.object.key, bucket=item.bucket):
                failed += 1
                continue
            deleted += 1
            deleted_bytes += item.object.size_bytes
        except Exception:
            failed += 1
    return StorageReconciliationApplyResult(
        planned_count=len(scan.candidates),
        deleted_count=deleted,
        failed_count=failed,
        deleted_bytes=deleted_bytes,
    )


def storage_lifecycle_payload(user, settings) -> dict[str, object]:
    ready = reference_storage_isolation_configured(settings)
    classes = []
    for reference_class, label in (
        (TRANSCRIPTION_REFERENCE_CLASS, "Транскрибации"),
        (AUDIO_PROCESSING_REFERENCE_CLASS, "Подготовка аудио"),
    ):
        selected = reference_storage_settings(settings, reference_class)
        classes.append(
            {
                "reference_class": reference_class,
                "label": label,
                "storage_ready": bool(ready and selected.source_storage_configured()),
                "provider_lifecycle_declared": bool((selected.source_s3_lifecycle_rule_id or "").strip()),
                "effective_retention_seconds": user.source_retention_ttl_seconds,
                "retention_applies_to_new_uploads_only": True,
            }
        )
    return {
        "classes": classes,
        "multipart": {
            "threshold_bytes": settings.source_multipart_threshold_bytes,
            "part_size_bytes": settings.source_multipart_part_size_bytes,
            "abandoned_session_ttl_seconds": settings.source_upload_ttl_seconds,
        },
        "reconciliation": {
            "available": ready,
            "dry_run_default": True,
            "apply_requires_confirmation": True,
            "minimum_orphan_age_seconds": settings.storage_orphan_min_age_seconds,
            "scan_limit": settings.storage_reconciliation_scan_limit,
            "apply_limit": settings.storage_reconciliation_apply_limit,
        },
    }
