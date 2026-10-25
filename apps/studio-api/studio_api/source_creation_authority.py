from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable

from sqlalchemy import and_


SOURCE_CREATION_PROVENANCES = {
    "google_drive_created_time",
    "yandex_disk_created_time",
    "embedded_media_metadata",
}


class SourceCreationAuthorityStatus(str, Enum):
    authoritative = "authoritative"
    unavailable = "unavailable"
    conflict = "conflict"


@dataclass(frozen=True)
class DocumentSourceCreationAuthority:
    """Private source-time authority for one selected transcript document."""

    status: SourceCreationAuthorityStatus
    created_at: datetime | None = field(default=None, repr=False)
    provenance: str | None = None

    @property
    def iso8601(self) -> str | None:
        if self.status != SourceCreationAuthorityStatus.authoritative:
            return None
        if self.created_at is None:
            return None
        return format_source_created_at(self.created_at)


def format_source_created_at(value: datetime) -> str:
    normalized = _normalized_datetime(value)
    if normalized is None:
        raise ValueError("Source creation time is invalid")
    return (
        normalized.replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def load_document_source_creation_authorities(
    db: Any,
    *,
    owner_user_id: str,
    document_ids: Iterable[str],
) -> dict[str, DocumentSourceCreationAuthority]:
    """Resolve selected Docs to owner-scoped persisted source authority.

    A direct Studio output relation is exact evidence. A persisted catalog
    source identity may also resolve a legacy document. Google Doc clocks and
    display text never participate in this resolver.
    """

    from .models import (
        Project,
        Source,
        TranscriptCatalogEntry,
        TranscriptCatalogSourceIdentityKind,
        TranscriptionJob,
        TranscriptionJobOutput,
        TranscriptionJobSource,
    )

    owner_id = _private_identity(owner_user_id, label="owner")
    requested_ids = tuple(
        _private_identity(value, label="document") for value in document_ids
    )
    if len(requested_ids) != len(set(requested_ids)):
        raise ValueError("Source creation document identities must be unique")
    if not requested_ids:
        return {}

    evidence: dict[str, list[tuple[datetime | None, str | None]]] = {
        document_id: [] for document_id in requested_ids
    }

    output_rows = (
        db.query(
            TranscriptionJobOutput.document_id,
            Source.source_created_at,
            Source.source_created_at_provenance,
        )
        .join(
            TranscriptionJob,
            and_(
                TranscriptionJob.id == TranscriptionJobOutput.job_id,
                TranscriptionJob.owner_user_id == owner_id,
            ),
        )
        .join(
            TranscriptionJobSource,
            and_(
                TranscriptionJobSource.id
                == TranscriptionJobOutput.job_source_id,
                TranscriptionJobSource.job_id
                == TranscriptionJobOutput.job_id,
            ),
        )
        .join(
            Source,
            and_(
                Source.id == TranscriptionJobSource.source_id,
                Source.project_id == TranscriptionJob.project_id,
            ),
        )
        .join(
            Project,
            and_(
                Project.id == Source.project_id,
                Project.owner_user_id == owner_id,
            ),
        )
        .filter(TranscriptionJobOutput.document_id.in_(requested_ids))
        .all()
    )
    for document_id, created_at, provenance in output_rows:
        normalized_id = _private_identity(document_id, label="document")
        if normalized_id not in evidence:
            raise ValueError("Source creation evidence is out of scope")
        evidence[normalized_id].append((created_at, provenance))

    catalog_rows = (
        db.query(
            TranscriptCatalogEntry.document_id,
            TranscriptCatalogEntry.source_identity_kind,
            TranscriptCatalogEntry.source_identity_value,
        )
        .filter(
            TranscriptCatalogEntry.owner_user_id == owner_id,
            TranscriptCatalogEntry.document_id.in_(requested_ids),
        )
        .all()
    )
    studio_source_ids = {
        value
        for _document_id, kind, value in catalog_rows
        if _enum_value(kind)
        == TranscriptCatalogSourceIdentityKind.studio_source.value
        and isinstance(value, str)
        and value.strip()
    }
    drive_source_ids = {
        value
        for _document_id, kind, value in catalog_rows
        if _enum_value(kind)
        == TranscriptCatalogSourceIdentityKind.google_drive_file.value
        and isinstance(value, str)
        and value.strip()
    }

    studio_sources = _load_sources_by_identity(
        db,
        owner_id=owner_id,
        identity_kind="studio_source",
        identity_values=studio_source_ids,
    )
    drive_sources = _load_sources_by_identity(
        db,
        owner_id=owner_id,
        identity_kind="google_drive_file",
        identity_values=drive_source_ids,
    )

    for document_id, raw_kind, raw_value in catalog_rows:
        normalized_id = _private_identity(document_id, label="document")
        if normalized_id not in evidence:
            raise ValueError("Source creation evidence is out of scope")
        kind = _enum_value(raw_kind)
        value = raw_value.strip() if isinstance(raw_value, str) else ""
        if not kind and not value:
            continue
        if not kind or not value:
            evidence[normalized_id].append((None, "conflict"))
            continue
        if kind == TranscriptCatalogSourceIdentityKind.studio_source.value:
            rows = studio_sources.get(value, ())
        elif kind == TranscriptCatalogSourceIdentityKind.google_drive_file.value:
            rows = drive_sources.get(value, ())
        else:
            rows = ()
        if not rows:
            evidence[normalized_id].append((None, None))
        else:
            evidence[normalized_id].extend(rows)

    return {
        document_id: _reconcile_authority(values)
        for document_id, values in evidence.items()
    }


def _load_sources_by_identity(
    db: Any,
    *,
    owner_id: str,
    identity_kind: str,
    identity_values: set[str],
) -> dict[str, tuple[tuple[datetime | None, str | None], ...]]:
    from .models import Project, Source

    if not identity_values:
        return {}
    identity_column = (
        Source.id if identity_kind == "studio_source" else Source.drive_file_id
    )
    rows = (
        db.query(
            identity_column,
            Source.source_created_at,
            Source.source_created_at_provenance,
        )
        .join(
            Project,
            and_(
                Project.id == Source.project_id,
                Project.owner_user_id == owner_id,
            ),
        )
        .filter(identity_column.in_(identity_values))
        .all()
    )
    grouped: dict[str, list[tuple[datetime | None, str | None]]] = {
        value: [] for value in identity_values
    }
    for raw_identity, created_at, provenance in rows:
        identity = _private_identity(raw_identity, label="source")
        if identity not in grouped:
            raise ValueError("Source creation identity is out of scope")
        grouped[identity].append((created_at, provenance))
    return {key: tuple(values) for key, values in grouped.items()}


def _reconcile_authority(
    evidence: list[tuple[datetime | None, str | None]],
) -> DocumentSourceCreationAuthority:
    if not evidence:
        return DocumentSourceCreationAuthority(
            SourceCreationAuthorityStatus.unavailable
        )
    normalized: list[tuple[datetime, str]] = []
    unavailable = False
    for created_at, provenance in evidence:
        timestamp = _normalized_datetime(created_at)
        if timestamp is None and provenance is None:
            unavailable = True
            continue
        if (
            timestamp is None
            or provenance not in SOURCE_CREATION_PROVENANCES
        ):
            return DocumentSourceCreationAuthority(
                SourceCreationAuthorityStatus.conflict
            )
        normalized.append((timestamp, provenance))
    distinct = set(normalized)
    if len(distinct) > 1 or (distinct and unavailable):
        return DocumentSourceCreationAuthority(
            SourceCreationAuthorityStatus.conflict
        )
    if not distinct:
        return DocumentSourceCreationAuthority(
            SourceCreationAuthorityStatus.unavailable
        )
    created_at, provenance = next(iter(distinct))
    return DocumentSourceCreationAuthority(
        SourceCreationAuthorityStatus.authoritative,
        created_at=created_at,
        provenance=provenance,
    )


def _normalized_datetime(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _private_identity(value: object, *, label: str) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        raise ValueError(f"Source creation {label} identity is invalid")
    return cleaned


def _enum_value(value: object) -> str | None:
    raw = getattr(value, "value", value)
    return raw if isinstance(raw, str) and raw else None
