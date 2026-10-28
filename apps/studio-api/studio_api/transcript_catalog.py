from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Sequence

from .media_clip import normalize_media_clip_range
from .transcription_options import (
    TranscriptionLanguageMode,
    browser_language_mode,
    job_diarization_enabled,
)
from .transcript_document import TRANSCRIPT_DOCUMENT_STANDARD


CURRENT_TRANSCRIPTION_PROVIDER = "elevenlabs"
CURRENT_TRANSCRIPTION_MODEL = "scribe_v2"
CURRENT_TRANSCRIPT_STANDARD = TRANSCRIPT_DOCUMENT_STANDARD
GOOGLE_DOCS_TRANSCRIPT_OUTPUT_KIND = "google_docs_transcript"
from .transcript_docx import DOCX_OUTPUT_KIND
TRANSCRIPT_OUTPUT_KINDS = (GOOGLE_DOCS_TRANSCRIPT_OUTPUT_KIND, DOCX_OUTPUT_KIND)
CATALOG_QUERY_EVIDENCE_BUDGET = 1000
CATALOG_SOURCE_LOCK_BUDGET = 1000


class CatalogSourceIdentityKind(str, Enum):
    google_drive_file = "google_drive_file"
    studio_source = "studio_source"


class ExistingResultMatchStatus(str, Enum):
    accepted_match = "accepted_match"
    standardization_required = "standardization_required"
    indeterminate = "indeterminate"
    no_match = "no_match"


class ProviderAttemptAuthorityStatus(str, Enum):
    available = "available"
    in_flight = "in_flight"
    unresolved = "unresolved"


@dataclass(frozen=True)
class CatalogSourceIdentity:
    kind: CatalogSourceIdentityKind
    value: str = field(repr=False)


@dataclass(frozen=True)
class EffectiveTranscriptionSettings:
    provider: str
    model: str
    language_mode: str
    diarization_enabled: bool
    media_clip_start_seconds: int | None = None
    media_clip_end_seconds: int | None = None


@dataclass(frozen=True)
class AcceptedTranscriptEvidence:
    source_identity: CatalogSourceIdentity
    settings: EffectiveTranscriptionSettings | None
    transcript_standard: str
    count: int = 1


@dataclass(frozen=True)
class ExistingResultMatch:
    status: ExistingResultMatchStatus
    accepted_output_count: int
    matching_settings_count: int


@dataclass(frozen=True)
class ProviderAttemptEvidence:
    source_identity: CatalogSourceIdentity
    settings: EffectiveTranscriptionSettings | None
    job_status: str
    retry_disposition: str
    accepted_output_persisted: bool = False
    document_creation_started: bool = False
    absence_acknowledged: bool = False
    attention_resolved: bool = False
    job_id: str | None = None


def current_effective_settings(
    *,
    language_mode: str,
    diarization_enabled: bool,
    media_clip_start_seconds: int | None = None,
    media_clip_end_seconds: int | None = None,
    provider: str = CURRENT_TRANSCRIPTION_PROVIDER,
    model: str = CURRENT_TRANSCRIPTION_MODEL,
) -> EffectiveTranscriptionSettings:
    normalized_language = (
        language_mode.strip().lower() if isinstance(language_mode, str) else ""
    )
    if normalized_language not in {
        mode.value for mode in TranscriptionLanguageMode
    }:
        raise ValueError("Unsupported PWA transcription language mode")
    if not isinstance(diarization_enabled, bool):
        raise ValueError("Diarization selection must be boolean")
    return provider_effective_settings(
        provider=provider,
        model=model,
        language_mode=normalized_language,
        diarization_enabled=diarization_enabled,
        media_clip_start_seconds=media_clip_start_seconds,
        media_clip_end_seconds=media_clip_end_seconds,
    )


def elevenlabs_effective_settings(
    *,
    language_mode: str,
    diarization_enabled: bool,
    media_clip_start_seconds: int | None = None,
    media_clip_end_seconds: int | None = None,
) -> EffectiveTranscriptionSettings:
    return provider_effective_settings(
        provider=CURRENT_TRANSCRIPTION_PROVIDER,
        model=CURRENT_TRANSCRIPTION_MODEL,
        language_mode=language_mode,
        diarization_enabled=diarization_enabled,
        media_clip_start_seconds=media_clip_start_seconds,
        media_clip_end_seconds=media_clip_end_seconds,
    )


def provider_effective_settings(
    *,
    provider: str,
    model: str,
    language_mode: str,
    diarization_enabled: bool,
    media_clip_start_seconds: int | None = None,
    media_clip_end_seconds: int | None = None,
) -> EffectiveTranscriptionSettings:
    normalized_language = _catalog_language_mode(language_mode)
    if normalized_language is None:
        raise ValueError("Unsupported transcription language mode")
    if not isinstance(diarization_enabled, bool):
        raise ValueError("Diarization selection must be boolean")
    clip = normalize_media_clip_range(
        media_clip_start_seconds,
        media_clip_end_seconds,
    )
    return EffectiveTranscriptionSettings(
        provider=provider,
        model=model,
        language_mode=normalized_language,
        diarization_enabled=bool(diarization_enabled),
        media_clip_start_seconds=clip.start_seconds,
        media_clip_end_seconds=clip.end_seconds,
    )


def catalog_source_identity(source: Any) -> CatalogSourceIdentity | None:
    source_id = _clean_private_identity(getattr(source, "id", None))
    source_type = _enum_value(getattr(source, "source_type", None))
    drive_file_id = _clean_private_identity(getattr(source, "drive_file_id", None))
    if source_type == "google_drive" and drive_file_id:
        return CatalogSourceIdentity(
            kind=CatalogSourceIdentityKind.google_drive_file,
            value=drive_file_id,
        )
    if source_id:
        return CatalogSourceIdentity(
            kind=CatalogSourceIdentityKind.studio_source,
            value=source_id,
        )
    return None


def effective_settings_from_persisted_job(
    *,
    job_provider: Any,
    credential_provider: Any,
    language: str | None,
    options_json: str | None,
    media_clip_start_seconds: int | None = None,
    media_clip_end_seconds: int | None = None,
    operating_mode: str | None = None,
    settings: Any | None = None,
) -> EffectiveTranscriptionSettings | None:
    explicit_provider = _enum_value(job_provider).strip().lower()
    selected_provider = explicit_provider or _enum_value(credential_provider).strip().lower()
    language_mode = _catalog_language_mode(browser_language_mode(language))
    if selected_provider not in {"elevenlabs", "yandex", "mistral", "gemini", "tbank"} or language_mode is None:
        return None
    from .transcription_metadata import stored_model
    model = stored_model(options_json)
    if model is not None:
        pass  # Durable request identity wins over later configuration changes.
    elif settings is not None:
        from .stt_provider import resolve_capability
        try:
            model = resolve_capability(settings, selected_provider, operating_mode or "standard").model
        except Exception:
            return None
    elif selected_provider == "yandex":
        model = "deferred-general" if operating_mode == "economic" else "general"
    elif selected_provider == "elevenlabs":
        model = CURRENT_TRANSCRIPTION_MODEL
    else:
        return None  # Never label a new provider with the historical Scribe default.
    return provider_effective_settings(
        provider=selected_provider,
        model=model,
        language_mode=language_mode,
        diarization_enabled=job_diarization_enabled(options_json),
        media_clip_start_seconds=media_clip_start_seconds,
        media_clip_end_seconds=media_clip_end_seconds,
    )


def accepted_evidence_from_rows(
    rows: Iterable[Sequence[Any]],
) -> tuple[AcceptedTranscriptEvidence, ...]:
    evidence: list[AcceptedTranscriptEvidence] = []
    for raw_row in rows:
        row = tuple(raw_row)
        count = 1
        if len(row) in {10, 12, 13}:
            *row_values, raw_count = row
            row = tuple(row_values)
            count = max(1, int(raw_count or 1))
        if len(row) == 9:
            row = (*row[:7], None, None, *row[7:])
        if len(row) not in {11, 12}:
            continue
        operating_mode = None
        if len(row) == 12:
            (
                source_id,
                source_type,
                drive_file_id,
                job_provider,
                credential_provider,
                operating_mode,
                language,
                options_json,
                media_clip_start_seconds,
                media_clip_end_seconds,
                output_kind,
                transcript_standard,
            ) = row
        else:
            (
            source_id,
            source_type,
            drive_file_id,
            job_provider,
            credential_provider,
            language,
            options_json,
            media_clip_start_seconds,
            media_clip_end_seconds,
            output_kind,
            transcript_standard,
            ) = row
        if output_kind not in TRANSCRIPT_OUTPUT_KINDS:
            continue
        identity = catalog_source_identity(
            _SourceIdentityProjection(source_id, source_type, drive_file_id)
        )
        if identity is None:
            continue
        evidence.append(
            AcceptedTranscriptEvidence(
                source_identity=identity,
                settings=effective_settings_from_persisted_job(
                    job_provider=job_provider,
                    credential_provider=credential_provider,
                    language=language,
                    options_json=options_json,
                    media_clip_start_seconds=media_clip_start_seconds,
                    media_clip_end_seconds=media_clip_end_seconds,
                    operating_mode=operating_mode,
                ),
                transcript_standard=str(transcript_standard or ""),
                count=count,
            )
        )
    return tuple(evidence)


def accepted_catalog_evidence_from_rows(
    rows: Iterable[Sequence[Any]],
) -> tuple[AcceptedTranscriptEvidence, ...]:
    """Restore accepted evidence only from explicitly linked catalog metadata."""
    evidence: list[AcceptedTranscriptEvidence] = []
    for raw_row in rows:
        row = tuple(raw_row)
        count = 1
        if len(row) == 9:
            *row_values, raw_count = row
            row = tuple(row_values)
            count = max(1, int(raw_count or 1))
        if len(row) != 8:
            continue
        (
            source_identity_kind,
            source_identity_value,
            settings_status,
            provider,
            model,
            language_mode,
            diarization_enabled,
            transcript_standard,
        ) = row
        try:
            identity_kind = CatalogSourceIdentityKind(
                _enum_value(source_identity_kind)
            )
        except ValueError:
            continue
        identity_value = _clean_private_identity(source_identity_value)
        if not identity_value:
            continue

        settings = None
        if _enum_value(settings_status) == "exact":
            normalized_provider = _clean_private_identity(provider).lower()
            normalized_model = _clean_private_identity(model)
            normalized_language = _catalog_language_mode(language_mode)
            if (
                normalized_provider
                and normalized_model
                and normalized_language is not None
                and isinstance(diarization_enabled, bool)
            ):
                settings = EffectiveTranscriptionSettings(
                    provider=normalized_provider,
                    model=normalized_model,
                    language_mode=normalized_language,
                    diarization_enabled=diarization_enabled,
                )

        evidence.append(
            AcceptedTranscriptEvidence(
                source_identity=CatalogSourceIdentity(
                    kind=identity_kind,
                    value=identity_value,
                ),
                # Malformed or indeterminate metadata stays relevant but
                # cannot silently become an exact no-match decision.
                settings=settings,
                transcript_standard=str(transcript_standard or ""),
                count=count,
            )
        )
    return tuple(evidence)


def classify_existing_results(
    *,
    sources: Iterable[Any],
    evidence: Iterable[AcceptedTranscriptEvidence],
    target_settings: EffectiveTranscriptionSettings,
) -> dict[str, ExistingResultMatch]:
    evidence_rows = tuple(evidence)
    matches: dict[str, ExistingResultMatch] = {}
    for source in sources:
        source_id = _clean_private_identity(getattr(source, "id", None))
        if not source_id:
            continue
        identity = catalog_source_identity(source)
        if identity is None:
            matches[source_id] = ExistingResultMatch(
                status=ExistingResultMatchStatus.indeterminate,
                accepted_output_count=0,
                matching_settings_count=0,
            )
            continue
        relevant = tuple(
            row for row in evidence_rows if row.source_identity == identity
        )
        matching_settings = tuple(
            row for row in relevant if row.settings == target_settings
        )
        if any(
            row.transcript_standard == CURRENT_TRANSCRIPT_STANDARD
            for row in matching_settings
        ):
            status = ExistingResultMatchStatus.accepted_match
        elif matching_settings:
            status = ExistingResultMatchStatus.standardization_required
        elif any(row.settings is None for row in relevant):
            status = ExistingResultMatchStatus.indeterminate
        else:
            status = ExistingResultMatchStatus.no_match
        matches[source_id] = ExistingResultMatch(
            status=status,
            accepted_output_count=sum(row.count for row in relevant),
            matching_settings_count=sum(row.count for row in matching_settings),
        )
    return matches


def _indeterminate_existing_result_matches(
    sources: Iterable[Any],
) -> dict[str, ExistingResultMatch]:
    return {
        source_id: ExistingResultMatch(
            status=ExistingResultMatchStatus.indeterminate,
            accepted_output_count=0,
            matching_settings_count=0,
        )
        for source in sources
        if (source_id := _clean_private_identity(getattr(source, "id", None)))
    }


def load_existing_result_matches(
    db: Any,
    *,
    owner_user_id: str,
    sources: Iterable[Any],
    target_settings: EffectiveTranscriptionSettings,
) -> dict[str, ExistingResultMatch]:
    from sqlalchemy import and_, func, or_

    from .models import (
        Project,
        ProviderCredential,
        Source,
        SourceType,
        TranscriptCatalogEntry,
        TranscriptCatalogSourceIdentityKind,
        TranscriptionJob,
        TranscriptionJobOutput,
        TranscriptionJobSource,
        User,
    )

    manifest_reset_at = db.query(User.manifest_reset_at).filter(User.id == owner_user_id).scalar()

    source_rows = tuple(sources)
    source_ids = {
        identity.value
        for source in source_rows
        if (identity := catalog_source_identity(source)) is not None
        and identity.kind == CatalogSourceIdentityKind.studio_source
    }
    drive_file_ids = {
        identity.value
        for source in source_rows
        if (identity := catalog_source_identity(source)) is not None
        and identity.kind == CatalogSourceIdentityKind.google_drive_file
    }
    identity_filters = []
    if source_ids:
        identity_filters.append(Source.id.in_(source_ids))
    if drive_file_ids:
        identity_filters.append(
            and_(
                Source.source_type == SourceType.google_drive,
                Source.drive_file_id.in_(drive_file_ids),
            )
        )
    if not identity_filters:
        return classify_existing_results(
            sources=source_rows,
            evidence=(),
            target_settings=target_settings,
        )

    output_query = (
        db.query(
            Source.id,
            Source.source_type,
            Source.drive_file_id,
            TranscriptionJob.provider,
            ProviderCredential.provider,
            TranscriptionJob.operating_mode,
            TranscriptionJob.language,
            TranscriptionJob.options_json,
            TranscriptionJob.media_clip_start_seconds,
            TranscriptionJob.media_clip_end_seconds,
            TranscriptionJobOutput.output_kind,
            TranscriptionJobOutput.transcript_standard,
            func.count(TranscriptionJobOutput.id),
        )
        .join(
            TranscriptionJobSource,
            TranscriptionJobSource.source_id == Source.id,
        )
        .join(
            TranscriptionJob,
            TranscriptionJob.id == TranscriptionJobSource.job_id,
        )
        .join(
            TranscriptionJobOutput,
            TranscriptionJobOutput.job_source_id == TranscriptionJobSource.id,
        )
        .join(Project, Project.id == Source.project_id)
        .outerjoin(
            ProviderCredential,
            and_(
                ProviderCredential.id == TranscriptionJob.provider_credential_id,
                ProviderCredential.user_id == owner_user_id,
            ),
        )
        .filter(
            TranscriptionJob.owner_user_id == owner_user_id,
            Project.owner_user_id == owner_user_id,
            TranscriptionJob.project_id == Source.project_id,
            TranscriptionJobOutput.output_kind.in_(TRANSCRIPT_OUTPUT_KINDS),
            or_(*identity_filters),
        )
    )
    if manifest_reset_at is not None:
        output_query = output_query.filter(TranscriptionJobOutput.persisted_at > manifest_reset_at)
    output_query = output_query.group_by(
        Source.id,
        Source.source_type,
        Source.drive_file_id,
        TranscriptionJob.provider,
        ProviderCredential.provider,
        TranscriptionJob.operating_mode,
        TranscriptionJob.language,
        TranscriptionJob.options_json,
        TranscriptionJob.media_clip_start_seconds,
        TranscriptionJob.media_clip_end_seconds,
        TranscriptionJobOutput.output_kind,
        TranscriptionJobOutput.transcript_standard,
    )
    output_rows = output_query.limit(CATALOG_QUERY_EVIDENCE_BUDGET + 1).all()
    if len(output_rows) > CATALOG_QUERY_EVIDENCE_BUDGET:
        return _indeterminate_existing_result_matches(source_rows)
    accepted_evidence = list(
        accepted_evidence_from_rows(output_rows)
    )

    catalog_identity_filters = []
    if source_ids:
        catalog_identity_filters.append(
            and_(
                TranscriptCatalogEntry.source_identity_kind
                == TranscriptCatalogSourceIdentityKind.studio_source,
                TranscriptCatalogEntry.source_identity_value.in_(source_ids),
            )
        )
    if drive_file_ids:
        catalog_identity_filters.append(
            and_(
                TranscriptCatalogEntry.source_identity_kind
                == TranscriptCatalogSourceIdentityKind.google_drive_file,
                TranscriptCatalogEntry.source_identity_value.in_(
                    drive_file_ids
                ),
            )
        )
    catalog_query = db.query(
        TranscriptCatalogEntry.source_identity_kind,
        TranscriptCatalogEntry.source_identity_value,
        TranscriptCatalogEntry.settings_status,
        TranscriptCatalogEntry.provider,
        TranscriptCatalogEntry.model,
        TranscriptCatalogEntry.language_mode,
        TranscriptCatalogEntry.diarization_enabled,
        TranscriptCatalogEntry.transcript_standard,
        func.count(TranscriptCatalogEntry.id),
    ).filter(
        TranscriptCatalogEntry.owner_user_id == owner_user_id,
        or_(*catalog_identity_filters),
    )
    if manifest_reset_at is not None:
        catalog_query = catalog_query.filter(TranscriptCatalogEntry.updated_at > manifest_reset_at)
    # Preserve the old owner/selected-identity dedup boundary without building
    # a cardinality-sized document-id set in application memory.
    output_exists_query = (
        db.query(TranscriptionJobOutput.id)
        .join(
            TranscriptionJobSource,
            TranscriptionJobSource.id == TranscriptionJobOutput.job_source_id,
        )
        .join(
            TranscriptionJob,
            TranscriptionJob.id == TranscriptionJobSource.job_id,
        )
        .join(Source, Source.id == TranscriptionJobSource.source_id)
        .join(Project, Project.id == Source.project_id)
        .filter(
            TranscriptionJobOutput.document_id
            == TranscriptCatalogEntry.document_id,
            TranscriptionJobOutput.output_kind.in_(TRANSCRIPT_OUTPUT_KINDS),
            TranscriptionJob.owner_user_id == owner_user_id,
            Project.owner_user_id == owner_user_id,
            TranscriptionJob.project_id == Source.project_id,
            or_(*identity_filters),
        )
    )
    if manifest_reset_at is not None:
        output_exists_query = output_exists_query.filter(
            TranscriptionJobOutput.persisted_at > manifest_reset_at
        )
    catalog_query = catalog_query.filter(~output_exists_query.exists()).group_by(
        TranscriptCatalogEntry.source_identity_kind,
        TranscriptCatalogEntry.source_identity_value,
        TranscriptCatalogEntry.settings_status,
        TranscriptCatalogEntry.provider,
        TranscriptCatalogEntry.model,
        TranscriptCatalogEntry.language_mode,
        TranscriptCatalogEntry.diarization_enabled,
        TranscriptCatalogEntry.transcript_standard,
    )
    remaining_budget = CATALOG_QUERY_EVIDENCE_BUDGET - len(output_rows)
    catalog_rows = catalog_query.limit(remaining_budget + 1).all()
    if len(catalog_rows) > remaining_budget:
        return _indeterminate_existing_result_matches(source_rows)
    accepted_evidence.extend(accepted_catalog_evidence_from_rows(catalog_rows))

    return classify_existing_results(
        sources=source_rows,
        evidence=accepted_evidence,
        target_settings=target_settings,
    )


def has_competing_provider_attempt_conflict(
    db: Any,
    *,
    owner_user_id: str,
    sources: Iterable[Any],
    target_settings: EffectiveTranscriptionSettings,
    exclude_job_id: str,
) -> bool:
    """Return whether equivalent paid work is in flight or unresolved.

    Callers must hold the catalog-identity source locks while checking this and
    while durably marking their own provider request as started. That makes the
    first worker the only unapproved job allowed across the paid-call boundary.
    A failed or cancelled attempt also remains a conflict unless its outcome is
    explicitly classified retry-safe; a new job must not bypass uncertainty.
    """
    authorities = load_provider_attempt_authorities(
        db,
        owner_user_id=owner_user_id,
        sources=sources,
        target_settings=target_settings,
        exclude_job_id=exclude_job_id,
    )
    return not authorities or any(
        authority != ProviderAttemptAuthorityStatus.available
        for authority in authorities.values()
    )


def load_provider_attempt_authorities(
    db: Any,
    *,
    owner_user_id: str,
    sources: Iterable[Any],
    target_settings: EffectiveTranscriptionSettings,
    exclude_job_id: str | None = None,
    attention_job_ids: dict[str, str] | None = None,
) -> dict[str, ProviderAttemptAuthorityStatus]:
    """Classify owner-scoped paid-call authority; optionally collect recovery IDs."""
    from sqlalchemy import and_, func, or_

    from .models import (
        Project,
        ProviderCredential,
        Source,
        SourceType,
        TranscriptionJob,
        TranscriptionJobOutput,
        TranscriptionJobSource,
        TranscriptionJobSourceAttempt,
        TranscriptionOutputReconciliation,
    )

    source_rows = tuple(sources)
    source_ids = {
        identity.value
        for source in source_rows
        if (identity := catalog_source_identity(source)) is not None
        and identity.kind == CatalogSourceIdentityKind.studio_source
    }
    drive_file_ids = {
        identity.value
        for source in source_rows
        if (identity := catalog_source_identity(source)) is not None
        and identity.kind == CatalogSourceIdentityKind.google_drive_file
    }
    identity_filters = []
    if source_ids:
        identity_filters.append(Source.id.in_(source_ids))
    if drive_file_ids:
        identity_filters.append(
            and_(
                Source.source_type == SourceType.google_drive,
                Source.drive_file_id.in_(drive_file_ids),
            )
        )
    if not identity_filters:
        return {
            source_id: ProviderAttemptAuthorityStatus.unresolved
            for source in source_rows
            if (source_id := _clean_private_identity(getattr(source, "id", None)))
        }

    query = (
        db.query(
            Source.id,
            Source.source_type,
            Source.drive_file_id,
            TranscriptionJob.id,
            TranscriptionJob.provider,
            ProviderCredential.provider,
            TranscriptionJob.operating_mode,
            TranscriptionJob.language,
            TranscriptionJob.options_json,
            TranscriptionJob.media_clip_start_seconds,
            TranscriptionJob.media_clip_end_seconds,
            TranscriptionJob.status,
            TranscriptionJob.history_attention_resolution,
            TranscriptionJobSourceAttempt.retry_disposition,
            func.count(TranscriptionJobOutput.id),
            func.max(TranscriptionOutputReconciliation.creation_started_at),
        )
        .select_from(Source)
        .join(
            TranscriptionJobSource,
            TranscriptionJobSource.source_id == Source.id,
        )
        .join(
            TranscriptionJob,
            TranscriptionJob.id == TranscriptionJobSource.job_id,
        )
        .join(
            TranscriptionJobSourceAttempt,
            and_(
                TranscriptionJobSourceAttempt.job_id == TranscriptionJob.id,
                TranscriptionJobSourceAttempt.job_source_id
                == TranscriptionJobSource.id,
            ),
        )
        .outerjoin(
            TranscriptionJobOutput,
            and_(
                TranscriptionJobOutput.job_source_id
                == TranscriptionJobSource.id,
                TranscriptionJobOutput.output_kind.in_(TRANSCRIPT_OUTPUT_KINDS),
            ),
        )
        .outerjoin(
            TranscriptionOutputReconciliation,
            TranscriptionOutputReconciliation.job_source_id
            == TranscriptionJobSource.id,
        )
        .join(Project, Project.id == Source.project_id)
        .outerjoin(
            ProviderCredential,
            and_(
                ProviderCredential.id
                == TranscriptionJob.provider_credential_id,
                ProviderCredential.user_id == owner_user_id,
            ),
        )
        .filter(
            TranscriptionJob.owner_user_id == owner_user_id,
            Project.owner_user_id == owner_user_id,
            TranscriptionJob.project_id == Source.project_id,
            TranscriptionJobSourceAttempt.provider_request_started_at.is_not(
                None
            ),
            or_(*identity_filters),
        )
    )
    if exclude_job_id is not None:
        query = query.filter(TranscriptionJob.id != exclude_job_id)
    query = query.group_by(
        Source.id,
        Source.source_type,
        Source.drive_file_id,
        TranscriptionJob.id,
        TranscriptionJob.provider,
        ProviderCredential.provider,
        TranscriptionJob.operating_mode,
        TranscriptionJob.language,
        TranscriptionJob.options_json,
        TranscriptionJob.media_clip_start_seconds,
        TranscriptionJob.media_clip_end_seconds,
        TranscriptionJob.status,
        TranscriptionJob.history_attention_resolution,
        TranscriptionJobSourceAttempt.retry_disposition,
    )
    query_rows = query.limit(CATALOG_QUERY_EVIDENCE_BUDGET + 1).all()
    if len(query_rows) > CATALOG_QUERY_EVIDENCE_BUDGET:
        return {
            source_id: ProviderAttemptAuthorityStatus.unresolved
            for source in source_rows
            if (source_id := _clean_private_identity(getattr(source, "id", None)))
        }
    evidence = tuple(
        ProviderAttemptEvidence(
            source_identity=catalog_source_identity(
                _SourceIdentityProjection(source_id, source_type, drive_file_id)
            ),
            settings=effective_settings_from_persisted_job(
                job_provider=job_provider,
                credential_provider=credential_provider,
                operating_mode=operating_mode,
                language=language,
                options_json=options_json,
                media_clip_start_seconds=media_clip_start_seconds,
                media_clip_end_seconds=media_clip_end_seconds,
            ),
            job_status=_enum_value(job_status),
            retry_disposition=_enum_value(retry_disposition),
            accepted_output_persisted=bool(output_count),
            document_creation_started=document_creation_started_at is not None,
            absence_acknowledged=(
                history_attention_resolution == "acknowledged_no_result"
            ),
            attention_resolved=history_attention_resolution is not None,
            job_id=job_id,
        )
        for (
            source_id,
            source_type,
            drive_file_id,
            job_id,
            job_provider,
            credential_provider,
            operating_mode,
            language,
            options_json,
            media_clip_start_seconds,
            media_clip_end_seconds,
            job_status,
            history_attention_resolution,
            retry_disposition,
            output_count,
            document_creation_started_at,
        ) in query_rows
        if catalog_source_identity(
            _SourceIdentityProjection(source_id, source_type, drive_file_id)
        )
        is not None
    )
    authorities = classify_provider_attempt_authorities(
        sources=source_rows,
        evidence=evidence,
        target_settings=target_settings,
    )
    if attention_job_ids is not None:
        attention_job_ids.update(
            actionable_provider_attempt_job_ids(
                sources=source_rows,
                evidence=evidence,
                target_settings=target_settings,
                authorities=authorities,
            )
        )
    return authorities


def actionable_provider_attempt_job_ids(
    *,
    sources: Iterable[Any],
    evidence: Iterable[ProviderAttemptEvidence],
    target_settings: EffectiveTranscriptionSettings,
    authorities: dict[str, ProviderAttemptAuthorityStatus],
) -> dict[str, str]:
    """Point an unresolved preflight at one owned terminal job it can resolve.

    The existing recent-auth endpoint rechecks ownership and eligibility before
    writing. No action is offered if a document is already persisted, work is
    still running, or the catalog query could not establish the evidence.
    """
    evidence_rows = tuple(evidence)
    result: dict[str, str] = {}
    for source in sources:
        source_id = _clean_private_identity(getattr(source, "id", None))
        identity = catalog_source_identity(source)
        if (
            not source_id
            or identity is None
            or authorities.get(source_id) != ProviderAttemptAuthorityStatus.unresolved
        ):
            continue
        relevant = tuple(
            row
            for row in evidence_rows
            if row.source_identity == identity
            and (row.settings is None or row.settings == target_settings)
        )
        if any(row.accepted_output_persisted for row in relevant):
            continue
        candidates = sorted(
            row.job_id
            for row in relevant
            if row.job_id
            and row.job_status in {"completed", "failed", "cancelled"}
            and row.retry_disposition != "retry_safe"
            and not row.absence_acknowledged
            and not row.attention_resolved
        )
        if candidates:
            result[source_id] = candidates[0]
    return result


def classify_provider_attempt_authorities(
    *,
    sources: Iterable[Any],
    evidence: Iterable[ProviderAttemptEvidence],
    target_settings: EffectiveTranscriptionSettings,
) -> dict[str, ProviderAttemptAuthorityStatus]:
    evidence_rows = tuple(evidence)
    authorities: dict[str, ProviderAttemptAuthorityStatus] = {}
    for source in sources:
        source_id = _clean_private_identity(getattr(source, "id", None))
        if not source_id:
            continue
        identity = catalog_source_identity(source)
        if identity is None:
            authorities[source_id] = ProviderAttemptAuthorityStatus.unresolved
            continue
        relevant = tuple(
            row
            for row in evidence_rows
            if row.source_identity == identity
            and (row.settings is None or row.settings == target_settings)
        )
        # A persisted output closes this source attempt even while a multi-source
        # parent job is still processing other sources. A terminal provider
        # failure before Google Docs creation is not a transcript document and
        # must not prevent the owner from starting a new job. The original job
        # remains non-retryable: this only governs a separately created job.
        open_attempts = tuple(
            row
            for row in relevant
            if not (
                row.retry_disposition == "completed"
                and row.accepted_output_persisted
            )
        )
        if any(row.job_status == "processing" for row in open_attempts):
            status = ProviderAttemptAuthorityStatus.in_flight
        # A separate, recent-auth owner acknowledgement closes only a terminal
        # no-result job. It never overrides active work or persisted documents.
        elif any(
            (
                row.document_creation_started
                or row.retry_disposition
                not in {
                    "retry_safe",
                    "provider_outcome_uncertain",
                    "provider_result_lost",
                }
            )
            and not (
                row.job_status in {"failed", "cancelled"}
                and row.absence_acknowledged
                and not row.accepted_output_persisted
            )
            for row in open_attempts
        ):
            status = ProviderAttemptAuthorityStatus.unresolved
        else:
            status = ProviderAttemptAuthorityStatus.available
        authorities[source_id] = status
    return authorities


def lock_catalog_source_identities(
    db: Any,
    *,
    owner_user_id: str,
    sources: Iterable[Any],
) -> tuple[Any, ...]:
    """Serialize create-time decisions with accepted-output persistence.

    Google Drive identity can span multiple Studio source rows, so locking only
    the currently selected row would leave a race with output persistence on an
    older row for the same Drive file. All matching owner-scoped source rows are
    locked in one deterministic order before the accepted-output query runs.
    """
    from sqlalchemy import and_, or_, select

    from .models import Project, Source, SourceType

    source_rows = tuple(sources)
    source_ids = {
        identity.value
        for source in source_rows
        if (identity := catalog_source_identity(source)) is not None
        and identity.kind == CatalogSourceIdentityKind.studio_source
    }
    drive_file_ids = {
        identity.value
        for source in source_rows
        if (identity := catalog_source_identity(source)) is not None
        and identity.kind == CatalogSourceIdentityKind.google_drive_file
    }
    identity_filters = []
    if source_ids:
        identity_filters.append(Source.id.in_(source_ids))
    if drive_file_ids:
        identity_filters.append(
            and_(
                Source.source_type == SourceType.google_drive,
                Source.drive_file_id.in_(drive_file_ids),
            )
        )
    if not identity_filters:
        return ()

    rows = tuple(
        db.execute(
            select(Source)
            .join(Project, Project.id == Source.project_id)
            .where(
                Project.owner_user_id == owner_user_id,
                or_(*identity_filters),
            )
            .order_by(Source.id.asc())
            .limit(CATALOG_SOURCE_LOCK_BUDGET + 1)
            # PostgreSQL FOR NO KEY UPDATE conflicts with the worker's source
            # FOR UPDATE while still allowing unrelated FK KEY SHARE access.
            .with_for_update(key_share=True, of=Source)
            .execution_options(populate_existing=True)
        )
        .scalars()
        .all()
    )
    # Empty is fail-closed for every caller: create-time validation gets an
    # unresolved catalog decision and the worker refuses the paid-call gate.
    return () if len(rows) > CATALOG_SOURCE_LOCK_BUDGET else rows


@dataclass(frozen=True)
class _SourceIdentityProjection:
    id: Any
    source_type: Any
    drive_file_id: Any


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return raw if isinstance(raw, str) else ""


def _clean_private_identity(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _catalog_language_mode(value: Any) -> str | None:
    normalized = value.strip().lower() if isinstance(value, str) else ""
    if (
        not normalized
        or len(normalized) > 40
        or not all(ch.isalnum() or ch in "_-" for ch in normalized)
    ):
        return None
    return normalized
