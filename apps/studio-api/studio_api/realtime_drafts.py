from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from sqlalchemy import case, select, func
from sqlalchemy.orm import Session

from .models import Project, RealtimeTranscriptDraft, User
from .security import decrypt, encrypt, master_key_from_b64, utcnow


MAX_COMMITTED_SEGMENTS = 5_000
MAX_COMMITTED_CHARACTERS = 500_000
MAX_PARTIAL_CHARACTERS = 20_000
CLIENT_SESSION_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
ROW_BUDGET_BYTES = 512


class RealtimeDraftReason(str, Enum):
    cleared = "realtime_draft_cleared"
    scope_conflict = "realtime_draft_scope_conflict"
    revision_conflict = "realtime_draft_revision_conflict"
    storage_limit = "realtime_draft_storage_limit"
    payload_too_large = "realtime_draft_payload_too_large"
    payload_invalid = "realtime_draft_payload_invalid"
    crypto_failed = "realtime_draft_crypto_failed"


class RealtimeDraftError(RuntimeError):
    def __init__(self, reason: RealtimeDraftReason):
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True)
class RealtimeDraftContent:
    client_session_id: str
    revision: int
    committed_segments: tuple[str, ...]
    partial: str
    updated_at: datetime
    expires_at: datetime | None
    segment_metadata: tuple[dict | None, ...] | None = None


def save_realtime_draft(
    db: Session,
    *,
    owner_user_id: str,
    project: Project,
    client_session_id: str,
    revision: int,
    committed_segments: list[str],
    partial: str,
    settings,
    now: datetime,
    segment_metadata: list[dict | None] | None = None,
) -> RealtimeDraftContent:
    _require_project_scope(project, owner_user_id)
    client_session_id = _client_session_id(client_session_id)
    payload, segments, partial, metadata = _serialize_payload(committed_segments, partial, segment_metadata)
    key = _key(settings)
    # Serialize every draft admission for this owner, including different client IDs.
    db.execute(select(User.id).where(User.id == owner_user_id).with_for_update()).scalar_one()
    existing = db.execute(
        select(RealtimeTranscriptDraft)
        .where(
            RealtimeTranscriptDraft.owner_user_id == owner_user_id,
            RealtimeTranscriptDraft.client_session_id == client_session_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if existing is not None and existing.project_id != project.id:
        raise RealtimeDraftError(RealtimeDraftReason.scope_conflict)
    if existing is not None and existing.cleared_at is not None:
        raise RealtimeDraftError(RealtimeDraftReason.cleared)
    if existing is not None and revision < existing.revision:
        raise RealtimeDraftError(RealtimeDraftReason.revision_conflict)

    row_id = existing.id if existing is not None else str(uuid.uuid4())
    associated = _draft_aad(
        owner_user_id,
        project.id,
        row_id,
        client_session_id,
        revision,
    )
    payload_hmac = hmac.new(
        key,
        associated + payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if existing is not None and revision == existing.revision:
        if hmac.compare_digest(existing.payload_hmac, payload_hmac):
            return _row_content(existing, settings=settings)
        raise RealtimeDraftError(RealtimeDraftReason.revision_conflict)

    try:
        ciphertext, nonce = encrypt(payload, key, associated)
    except Exception as exc:
        raise RealtimeDraftError(RealtimeDraftReason.crypto_failed) from exc
    count, total_count, stored_bytes = db.execute(
        select(func.coalesce(func.sum(case((RealtimeTranscriptDraft.cleared_at.is_(None), 1), else_=0)), 0),
            func.count(RealtimeTranscriptDraft.id), func.coalesce(func.sum(func.length(RealtimeTranscriptDraft.ciphertext)), 0))
        .where(RealtimeTranscriptDraft.owner_user_id == owner_user_id)
    ).one()
    max_count = getattr(settings, "realtime_draft_max_count", 20)
    max_bytes = getattr(settings, "realtime_draft_max_storage_bytes", 32 * 1024 * 1024)
    if (existing is None and count >= max_count) or (stored_bytes - (len(existing.ciphertext) if existing else 0)
        + len(ciphertext) + (total_count + (existing is None)) * ROW_BUDGET_BYTES > max_bytes):
        raise RealtimeDraftError(RealtimeDraftReason.storage_limit)
    # Only an explicit owner clear retires Live text. Legacy dates are not
    # authority to erase a draft, including one recovered after deployment.
    expires_at = None
    if existing is None:
        row = RealtimeTranscriptDraft(
            id=row_id,
            owner_user_id=owner_user_id,
            project_id=project.id,
            client_session_id=client_session_id,
            revision=revision,
            ciphertext=ciphertext,
            nonce=nonce,
            key_id=settings.credential_key_id,
            payload_hmac=payload_hmac,
            committed_segment_count=len(segments),
            committed_character_count=sum(len(segment) for segment in segments),
            partial_character_count=len(partial),
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )
        db.add(row)
    else:
        row = existing
        row.revision = revision
        row.ciphertext = ciphertext
        row.nonce = nonce
        row.key_id = settings.credential_key_id
        row.payload_hmac = payload_hmac
        row.committed_segment_count = len(segments)
        row.committed_character_count = sum(len(segment) for segment in segments)
        row.partial_character_count = len(partial)
        row.updated_at = now
        row.expires_at = expires_at
    db.flush()
    return RealtimeDraftContent(
        client_session_id=row.client_session_id,
        revision=row.revision,
        committed_segments=segments,
        partial=partial,
        updated_at=row.updated_at,
        expires_at=row.expires_at,
        segment_metadata=metadata,
    )


def load_latest_realtime_draft(
    db: Session,
    *,
    owner_user_id: str,
    project: Project,
    settings,
    now: datetime,
) -> RealtimeDraftContent | None:
    _require_project_scope(project, owner_user_id)
    cleanup_expired_realtime_drafts(
        db,
        now=now,
        owner_user_id=owner_user_id,
        project_id=project.id,
    )
    row = db.execute(
        select(RealtimeTranscriptDraft)
        .where(
            RealtimeTranscriptDraft.owner_user_id == owner_user_id,
            RealtimeTranscriptDraft.project_id == project.id,
            RealtimeTranscriptDraft.cleared_at.is_(None),
        )
        .order_by(
            RealtimeTranscriptDraft.updated_at.desc(),
            RealtimeTranscriptDraft.created_at.desc(),
        )
        .limit(1)
    ).scalar_one_or_none()
    return _row_content(row, settings=settings) if row is not None else None


def delete_realtime_draft(
    db: Session,
    *,
    owner_user_id: str,
    project: Project,
    client_session_id: str,
    settings=None,
    now: datetime | None = None,
) -> bool:
    _require_project_scope(project, owner_user_id)
    normalized = _client_session_id(client_session_id)
    db.execute(select(User.id).where(User.id == owner_user_id).with_for_update()).scalar_one()
    row = db.execute(
        select(RealtimeTranscriptDraft).where(
            RealtimeTranscriptDraft.owner_user_id == owner_user_id,
            RealtimeTranscriptDraft.client_session_id == normalized,
        ).with_for_update()
    ).scalar_one_or_none()
    if row is not None and row.project_id != project.id:
        raise RealtimeDraftError(RealtimeDraftReason.scope_conflict)
    if row is not None and row.cleared_at is not None:
        return False
    deleted = row is not None
    now = now or utcnow()
    if row is None:
        total_count, stored_bytes = db.execute(select(func.count(RealtimeTranscriptDraft.id),
            func.coalesce(func.sum(func.length(RealtimeTranscriptDraft.ciphertext)), 0)).where(
                RealtimeTranscriptDraft.owner_user_id == owner_user_id)).one()
        if stored_bytes + (total_count + 1) * ROW_BUDGET_BYTES > getattr(settings, "realtime_draft_max_storage_bytes", 32 * 1024 * 1024):
            raise RealtimeDraftError(RealtimeDraftReason.storage_limit)
        row = RealtimeTranscriptDraft(id=str(uuid.uuid4()), owner_user_id=owner_user_id,
            project_id=project.id, client_session_id=normalized, revision=1, created_at=now)
        db.add(row)
    row.cleared_at = now
    row.updated_at = now
    row.expires_at = None
    row.ciphertext = b""
    row.nonce = b""
    row.key_id = ""
    row.payload_hmac = "0" * 64
    row.committed_segment_count = row.committed_character_count = row.partial_character_count = 0
    db.flush()
    return deleted


def load_realtime_draft_state(db: Session, *, owner_user_id: str, project: Project,
                              client_session_id: str, settings) -> tuple[RealtimeDraftContent | None, bool]:
    _require_project_scope(project, owner_user_id)
    normalized = _client_session_id(client_session_id)
    row = db.execute(select(RealtimeTranscriptDraft).where(
        RealtimeTranscriptDraft.owner_user_id == owner_user_id, RealtimeTranscriptDraft.project_id == project.id,
        RealtimeTranscriptDraft.client_session_id == normalized)).scalar_one_or_none()
    if row is None:
        return None, False
    if row.cleared_at is not None:
        return None, True
    return _row_content(row, settings=settings), False


DEFAULT_REALTIME_DRAFT_CLEANUP_BATCH_SIZE = 500
MAX_REALTIME_DRAFT_CLEANUP_BATCH_SIZE = 1000


def cleanup_expired_realtime_drafts(
    db: Session,
    *,
    now: datetime,
    owner_user_id: str | None = None,
    project_id: str | None = None,
    limit: int = DEFAULT_REALTIME_DRAFT_CLEANUP_BATCH_SIZE,
) -> int:
    """Compatibility hook for worker schedules; Live has no expiry cleanup.

    Deliberately preserve even legacy expired rows. Owner quotas and explicit
    deletion, rather than elapsed time, bound this encrypted store.
    """
    return 0


def _row_content(row: RealtimeTranscriptDraft, *, settings) -> RealtimeDraftContent:
    if row.key_id != settings.credential_key_id:
        raise RealtimeDraftError(RealtimeDraftReason.crypto_failed)
    key = _key(settings)
    associated = _draft_aad(
        row.owner_user_id,
        row.project_id,
        row.id,
        row.client_session_id,
        row.revision,
    )
    try:
        payload = decrypt(row.ciphertext, row.nonce, key, associated)
    except Exception as exc:
        raise RealtimeDraftError(RealtimeDraftReason.crypto_failed) from exc
    expected_hmac = hmac.new(
        key,
        associated + payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hmac, row.payload_hmac):
        raise RealtimeDraftError(RealtimeDraftReason.payload_invalid)
    try:
        candidate = json.loads(payload)
    except Exception as exc:
        raise RealtimeDraftError(RealtimeDraftReason.payload_invalid) from exc
    if not isinstance(candidate, dict) or set(candidate) not in ({"segments", "partial"}, {"segments", "partial", "segment_metadata"}):
        raise RealtimeDraftError(RealtimeDraftReason.payload_invalid)
    try:
        _serialized, segments, partial, metadata = _serialize_payload(
            candidate["segments"],
            candidate["partial"],
            candidate.get("segment_metadata"),
        )
    except RealtimeDraftError as exc:
        raise RealtimeDraftError(RealtimeDraftReason.payload_invalid) from exc
    if (
        row.committed_segment_count != len(segments)
        or row.committed_character_count != sum(len(item) for item in segments)
        or row.partial_character_count != len(partial)
    ):
        raise RealtimeDraftError(RealtimeDraftReason.payload_invalid)
    return RealtimeDraftContent(
        client_session_id=row.client_session_id,
        revision=row.revision,
        committed_segments=segments,
        partial=partial,
        updated_at=row.updated_at,
        expires_at=row.expires_at,
        segment_metadata=metadata,
    )


def _serialize_payload(segments, partial, metadata=None) -> tuple[str, tuple[str, ...], str, tuple[dict | None, ...] | None]:
    if not isinstance(segments, (list, tuple)) or len(segments) > MAX_COMMITTED_SEGMENTS:
        raise RealtimeDraftError(RealtimeDraftReason.payload_too_large)
    if not isinstance(partial, str):
        raise RealtimeDraftError(RealtimeDraftReason.payload_invalid)
    normalized: list[str] = []
    total = 0
    for segment in segments:
        if not isinstance(segment, str):
            raise RealtimeDraftError(RealtimeDraftReason.payload_invalid)
        if not segment or len(segment) > MAX_PARTIAL_CHARACTERS:
            raise RealtimeDraftError(RealtimeDraftReason.payload_too_large)
        total += len(segment)
        if total > MAX_COMMITTED_CHARACTERS:
            raise RealtimeDraftError(RealtimeDraftReason.payload_too_large)
        normalized.append(segment)
    if len(partial) > MAX_PARTIAL_CHARACTERS:
        raise RealtimeDraftError(RealtimeDraftReason.payload_too_large)
    normalized_metadata = _normalize_segment_metadata(metadata, len(normalized))
    payload = json.dumps(
        {"segments": normalized, "partial": partial, **({"segment_metadata": normalized_metadata} if normalized_metadata is not None else {})},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return payload, tuple(normalized), partial, normalized_metadata


def _normalize_segment_metadata(value, count: int) -> tuple[dict | None, ...] | None:
    if value is None:
        return None  # Legacy text carries no invented timing/speaker data.
    if not isinstance(value, (list, tuple)) or len(value) != count:
        raise RealtimeDraftError(RealtimeDraftReason.payload_invalid)
    seen = set()
    normalized = []
    for item in value:
        if item is None:
            normalized.append(None)
            continue
        if not isinstance(item, dict) or set(item) - {"id", "session_id", "start_seconds", "end_seconds", "speaker", "gap"}:
            raise RealtimeDraftError(RealtimeDraftReason.payload_invalid)
        if "session_id" in item and (not isinstance(item["session_id"], str) or not CLIENT_SESSION_PATTERN.fullmatch(item["session_id"])):
            raise RealtimeDraftError(RealtimeDraftReason.payload_invalid)
        identity = item.get("id")
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", identity) or identity in seen:
            raise RealtimeDraftError(RealtimeDraftReason.payload_invalid)
        seen.add(identity)
        if "gap" in item and not isinstance(item["gap"], bool):
            raise RealtimeDraftError(RealtimeDraftReason.payload_invalid)
        if "speaker" in item and (type(item["speaker"]) is not int or not 1 <= item["speaker"] <= 1000):
            raise RealtimeDraftError(RealtimeDraftReason.payload_invalid)
        if "start_seconds" in item or "end_seconds" in item:
            start, end = item.get("start_seconds"), item.get("end_seconds")
            if (type(start) not in (int, float) or type(end) not in (int, float)
                    or not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end <= 604800):
                raise RealtimeDraftError(RealtimeDraftReason.payload_invalid)
        normalized.append(dict(item))
    return tuple(normalized)


def _client_session_id(value: str) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if not CLIENT_SESSION_PATTERN.fullmatch(normalized):
        raise RealtimeDraftError(RealtimeDraftReason.payload_invalid)
    return normalized


def _require_project_scope(project: Project, owner_user_id: str) -> None:
    if project.owner_user_id != owner_user_id or project.archived_at is not None:
        raise RealtimeDraftError(RealtimeDraftReason.scope_conflict)


def _key(settings) -> bytes:
    try:
        return master_key_from_b64(settings.master_key_b64())
    except Exception as exc:
        raise RealtimeDraftError(RealtimeDraftReason.crypto_failed) from exc


def _draft_aad(owner, project, draft, client_session, revision) -> bytes:
    return (
        f"owner={owner};project={project};draft={draft};client_session={client_session};"
        f"revision={revision};purpose=realtime_transcript_draft_v1"
    ).encode("utf-8")
