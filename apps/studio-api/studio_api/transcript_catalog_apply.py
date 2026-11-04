from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Iterable, Mapping

from sqlalchemy import select

from .transcript_catalog import (
    CURRENT_TRANSCRIPT_STANDARD,
    CatalogSourceIdentity,
    CatalogSourceIdentityKind,
    EffectiveTranscriptionSettings,
)
from .transcript_catalog_migration import (
    CatalogMigrationBlockReason,
    CatalogMigrationCandidate,
    CatalogMigrationDecision,
    CatalogMigrationOperation,
    CatalogSettingsAuthorityStatus,
    TranscriptCatalogImportDecision,
    TranscriptMaintenanceWorkflow,
    classify_catalog_migration_candidate,
    classify_transcript_catalog_import_candidate,
)


class CatalogMetadataApplyOutcome(str, Enum):
    imported = "imported"
    already_applied = "already_applied"
    unchanged = "unchanged"
    blocked = "blocked"
    standardization_required = "standardization_required"
    conflict = "conflict"


class CatalogMetadataApplyReason(str, Enum):
    catalog_conflict = "catalog_conflict"
    document_unreadable = "document_unreadable"
    standardization_required = "standardization_required"
    catalog_metadata_conflict = "catalog_metadata_conflict"


@dataclass(frozen=True)
class CatalogApplyMetadata:
    """Private exact authority supplied independently of document display text."""

    settings: EffectiveTranscriptionSettings | None = None
    source_identity: CatalogSourceIdentity | None = None


def apply_catalog_migration_metadata(
    db: Any,
    *,
    owner_user_id: str,
    candidates: Iterable[CatalogMigrationCandidate],
    metadata_by_document_id: Mapping[str, CatalogApplyMetadata] | None = None,
    applied_at: datetime | None = None,
) -> dict:
    """Idempotently persist eligible catalog metadata without Google mutation.

    Only a freshly classified current document can be imported here. Documents
    that still need in-place standardization remain explicitly deferred so the
    durable catalog cannot get ahead of Google document state. The caller owns
    the surrounding transaction.
    """

    return _apply_catalog_metadata(
        db,
        owner_user_id=owner_user_id,
        candidates=candidates,
        metadata_by_document_id=metadata_by_document_id,
        applied_at=applied_at,
        classifier=classify_catalog_migration_candidate,
        workflow=None,
    )


def apply_transcript_catalog_import_metadata(
    db: Any,
    *,
    owner_user_id: str,
    candidates: Iterable[CatalogMigrationCandidate],
    metadata_by_document_id: Mapping[str, CatalogApplyMetadata] | None = None,
    applied_at: datetime | None = None,
    progress: Callable[[str, int, int | None], None] | None = None,
) -> dict:
    """Persist only eligible selected catalog metadata; never touch Google."""

    return _apply_catalog_metadata(
        db,
        owner_user_id=owner_user_id,
        candidates=candidates,
        metadata_by_document_id=metadata_by_document_id,
        applied_at=applied_at,
        classifier=classify_transcript_catalog_import_candidate,
        workflow=TranscriptMaintenanceWorkflow.catalog_import.value,
        progress=progress,
    )


def _apply_catalog_metadata(
    db: Any,
    *,
    owner_user_id: str,
    candidates: Iterable[CatalogMigrationCandidate],
    metadata_by_document_id: Mapping[str, CatalogApplyMetadata] | None,
    applied_at: datetime | None,
    classifier: Callable[
        [CatalogMigrationCandidate],
        CatalogMigrationDecision | TranscriptCatalogImportDecision,
    ],
    workflow: str | None,
    progress: Callable[[str, int, int | None], None] | None = None,
) -> dict:
    from .models import TranscriptCatalogEntry

    owner_id = _bounded_identity(owner_user_id, label="owner", maximum=36)
    candidate_rows = tuple(candidates)
    if any(
        not isinstance(candidate, CatalogMigrationCandidate)
        for candidate in candidate_rows
    ):
        raise ValueError("Catalog migration candidate is required")
    document_ids = tuple(
        _bounded_identity(
            candidate.drive_document_id,
            label="document",
            maximum=256,
        )
        for candidate in candidate_rows
    )
    if len(document_ids) != len(set(document_ids)):
        raise ValueError("Catalog migration candidates must be unique")
    private_metadata = _normalize_private_metadata(
        (
            metadata_by_document_id
            if metadata_by_document_id is not None
            else {}
        ),
        allowed_document_ids=set(document_ids),
    )
    timestamp = applied_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Catalog apply timestamp must be timezone-aware")

    existing_rows = tuple(
        db.execute(
            select(TranscriptCatalogEntry).where(
                TranscriptCatalogEntry.owner_user_id == owner_id,
                TranscriptCatalogEntry.document_id.in_(document_ids),
            )
        )
        .scalars()
        .all()
    )
    existing_by_document = {
        _bounded_identity(
            row.document_id,
            label="document",
            maximum=256,
        ): row
        for row in existing_rows
    }
    if len(existing_by_document) != len(existing_rows):
        raise ValueError("Catalog metadata authority is ambiguous")

    items = []
    outcomes = []
    for position, (candidate, document_id) in enumerate(
        zip(candidate_rows, document_ids, strict=True)
    ):
        decision = classifier(candidate)
        outcome, reason = _apply_one_candidate(
            db,
            owner_user_id=owner_id,
            document_id=document_id,
            decision=decision,
            metadata=private_metadata.get(
                document_id,
                CatalogApplyMetadata(),
            ),
            existing=existing_by_document.get(document_id),
            applied_at=timestamp,
        )
        outcomes.append(outcome)
        items.append(
            {
                "position": position,
                "name": decision.name,
                "action": decision.action.value,
                "outcome": outcome.value,
                "reason_code": reason.value if reason else None,
            }
        )
        if progress is not None:
            progress("applying", position + 1, len(candidate_rows))

    db.flush()
    payload = {
        "operation": CatalogMigrationOperation.apply.value,
        "target_standard": CURRENT_TRANSCRIPT_STANDARD,
        "items": items,
        "summary": {
            f"{outcome.value}_count": outcomes.count(outcome)
            for outcome in CatalogMetadataApplyOutcome
        },
    }
    if workflow is not None:
        payload = {"workflow": workflow, **payload}
    return payload


def _apply_one_candidate(
    db: Any,
    *,
    owner_user_id: str,
    document_id: str,
    decision: CatalogMigrationDecision | TranscriptCatalogImportDecision,
    metadata: CatalogApplyMetadata,
    existing: Any | None,
    applied_at: datetime,
) -> tuple[
    CatalogMetadataApplyOutcome,
    CatalogMetadataApplyReason | None,
]:
    action = decision.action.value
    if action == "blocked":
        reasons = {
            CatalogMigrationBlockReason.catalog_conflict: (
                CatalogMetadataApplyReason.catalog_conflict
            ),
            CatalogMigrationBlockReason.document_unreadable: (
                CatalogMetadataApplyReason.document_unreadable
            ),
            CatalogMigrationBlockReason.standardization_required: (
                CatalogMetadataApplyReason.standardization_required
            ),
        }
        if decision.reason not in reasons:
            raise ValueError("Catalog migration block reason is invalid")
        reason = reasons[decision.reason]
        return CatalogMetadataApplyOutcome.blocked, reason
    if action == "standardize_document":
        return (
            CatalogMetadataApplyOutcome.standardization_required,
            CatalogMetadataApplyReason.standardization_required,
        )
    if action == "unchanged":
        return CatalogMetadataApplyOutcome.unchanged, None
    if action not in {"import_metadata", "standardize_and_import"}:
        raise ValueError("Catalog migration action is invalid")

    desired = _desired_import_values(
        owner_user_id=owner_user_id,
        document_id=document_id,
        document_name=decision.name,
        settings_status=decision.settings_status,
        metadata=metadata,
        applied_at=applied_at,
    )
    if action == "standardize_and_import":
        if existing is not None and not _same_catalog_authority(
            existing,
            desired,
        ):
            return (
                CatalogMetadataApplyOutcome.conflict,
                CatalogMetadataApplyReason.catalog_metadata_conflict,
            )
        return (
            CatalogMetadataApplyOutcome.standardization_required,
            CatalogMetadataApplyReason.standardization_required,
        )
    if existing is not None:
        if not _same_catalog_authority(existing, desired):
            return (
                CatalogMetadataApplyOutcome.conflict,
                CatalogMetadataApplyReason.catalog_metadata_conflict,
            )
        _refresh_catalog_observation(
            existing,
            desired=desired,
            applied_at=applied_at,
        )
        return CatalogMetadataApplyOutcome.already_applied, None

    inserted = _insert_catalog_entry_if_absent(db, desired)
    persisted = (
        db.execute(
            select(inserted.model).where(
                inserted.model.owner_user_id == owner_user_id,
                inserted.model.document_id == document_id,
            )
        )
        .scalars()
        .one()
    )
    if not _same_catalog_authority(persisted, desired):
        return (
            CatalogMetadataApplyOutcome.conflict,
            CatalogMetadataApplyReason.catalog_metadata_conflict,
        )
    if inserted.created:
        return CatalogMetadataApplyOutcome.imported, None
    _refresh_catalog_observation(
        persisted,
        desired=desired,
        applied_at=applied_at,
    )
    return CatalogMetadataApplyOutcome.already_applied, None


@dataclass(frozen=True)
class _InsertResult:
    model: Any
    created: bool


def _insert_catalog_entry_if_absent(
    db: Any,
    values: dict[str, Any],
) -> _InsertResult:
    from .models import TranscriptCatalogEntry

    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise RuntimeError("Catalog apply requires PostgreSQL or SQLite")
    statement = (
        insert(TranscriptCatalogEntry)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=["owner_user_id", "document_id"],
        )
        .returning(TranscriptCatalogEntry.id)
    )
    inserted_id = db.execute(statement).scalar_one_or_none()
    if inserted_id is not None and inserted_id != values["id"]:
        raise RuntimeError("Catalog insert returned an unexpected identity")
    return _InsertResult(
        model=TranscriptCatalogEntry,
        created=inserted_id is not None,
    )


def _desired_import_values(
    *,
    owner_user_id: str,
    document_id: str,
    document_name: str,
    settings_status: CatalogSettingsAuthorityStatus,
    metadata: CatalogApplyMetadata,
    applied_at: datetime,
) -> dict[str, Any]:
    from .models import (
        TranscriptCatalogDocumentStandardStatus,
        TranscriptCatalogSettingsStatus,
        TranscriptCatalogSourceIdentityKind,
    )

    if not isinstance(metadata, CatalogApplyMetadata):
        raise ValueError("Catalog apply metadata is invalid")
    if settings_status == CatalogSettingsAuthorityStatus.exact:
        if metadata.settings is None:
            raise ValueError(
                "Exact catalog settings require exact private authority"
            )
        provider, model, language_mode, diarization_enabled = (
            _exact_settings_columns(metadata.settings)
        )
        persisted_settings_status = TranscriptCatalogSettingsStatus.exact
    elif settings_status == CatalogSettingsAuthorityStatus.indeterminate:
        if metadata.settings is not None:
            raise ValueError(
                "Indeterminate catalog settings cannot include exact authority"
            )
        provider = model = language_mode = diarization_enabled = None
        persisted_settings_status = (
            TranscriptCatalogSettingsStatus.indeterminate
        )
    else:
        raise ValueError("Catalog settings authority is invalid")

    source_kind = source_value = None
    if metadata.source_identity is not None:
        if not isinstance(metadata.source_identity, CatalogSourceIdentity):
            raise ValueError("Catalog source identity is invalid")
        if not isinstance(
            metadata.source_identity.kind,
            CatalogSourceIdentityKind,
        ):
            raise ValueError("Catalog source identity kind is invalid")
        source_kind = TranscriptCatalogSourceIdentityKind(
            metadata.source_identity.kind.value
        )
        source_value = _bounded_identity(
            metadata.source_identity.value,
            label="source",
            maximum=1024,
        )

    return {
        "id": str(uuid.uuid4()),
        "owner_user_id": owner_user_id,
        "document_id": document_id,
        "document_name": document_name,
        "transcript_standard": CURRENT_TRANSCRIPT_STANDARD,
        "standard_status": (
            TranscriptCatalogDocumentStandardStatus.current
        ),
        "settings_status": persisted_settings_status,
        "provider": provider,
        "model": model,
        "language_mode": language_mode,
        "diarization_enabled": diarization_enabled,
        "source_identity_kind": source_kind,
        "source_identity_value": source_value,
        "imported_at": applied_at,
        "updated_at": applied_at,
    }


def _same_catalog_authority(
    existing: Any,
    desired: Mapping[str, Any],
) -> bool:
    return (
        _enum_value(existing.settings_status)
        == _enum_value(desired["settings_status"])
        and existing.provider == desired["provider"]
        and existing.model == desired["model"]
        and existing.language_mode == desired["language_mode"]
        and existing.diarization_enabled
        == desired["diarization_enabled"]
        and _enum_value(existing.source_identity_kind)
        == _enum_value(desired["source_identity_kind"])
        and existing.source_identity_value
        == desired["source_identity_value"]
    )


def _refresh_catalog_observation(
    existing: Any,
    *,
    desired: Mapping[str, Any],
    applied_at: datetime,
) -> None:
    existing.document_name = desired["document_name"]
    existing.transcript_standard = desired["transcript_standard"]
    existing.standard_status = desired["standard_status"]
    existing.updated_at = applied_at


def _normalize_private_metadata(
    metadata_by_document_id: Mapping[str, CatalogApplyMetadata],
    *,
    allowed_document_ids: set[str],
) -> dict[str, CatalogApplyMetadata]:
    normalized = {}
    for raw_document_id, metadata in metadata_by_document_id.items():
        document_id = _bounded_identity(
            raw_document_id,
            label="document",
            maximum=256,
        )
        if document_id in normalized:
            raise ValueError("Catalog apply metadata identities must be unique")
        if document_id not in allowed_document_ids:
            raise ValueError("Catalog apply metadata is out of scope")
        if not isinstance(metadata, CatalogApplyMetadata):
            raise ValueError("Catalog apply metadata is invalid")
        normalized[document_id] = metadata
    return normalized


def _exact_settings_columns(
    settings: EffectiveTranscriptionSettings,
) -> tuple[str, str, str, bool]:
    if not isinstance(settings, EffectiveTranscriptionSettings):
        raise ValueError("Catalog exact settings authority is invalid")
    if not isinstance(settings.diarization_enabled, bool):
        raise ValueError("Catalog exact diarization authority is invalid")
    return (
        _bounded_identity(
            settings.provider,
            label="provider",
            maximum=40,
        ).lower(),
        _bounded_identity(
            settings.model,
            label="model",
            maximum=80,
        ),
        _bounded_identity(
            settings.language_mode,
            label="language",
            maximum=40,
        ).lower(),
        settings.diarization_enabled,
    )


def _bounded_identity(
    value: object,
    *,
    label: str,
    maximum: int,
) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned or len(cleaned) > maximum:
        raise ValueError(f"Catalog {label} identity is invalid")
    return cleaned


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    raw = getattr(value, "value", value)
    return raw if isinstance(raw, str) else None
