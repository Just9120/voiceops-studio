from __future__ import annotations

import re

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePath
from typing import Callable, Iterator, Protocol

from sqlalchemy.orm import Session

from .elevenlabs_transcription import ElevenLabsTranscriptionError
from .google_connection_access import GoogleConnectionAccessError, refresh_user_google_drive_access_token
from .google_docs_output import (
    GoogleDocsOutputError,
    GoogleDocsOutputReason,
    GoogleDocsTranscriptArtifact,
    new_google_docs_transcript_artifact,
)
from .job_claim_lease import is_lease_active
from .job_output_destination import DriveFolderAuthorizationMetadata, OutputDestinationError, _fetch_drive_folder_authorization_metadata, _validate_metadata
from .job_source_materialization import SourceMaterializationError, _load_selected_snapshot
from .models import JobStatus, Project, TranscriptionJob, TranscriptionJobOutput
from .security import utcnow
from .integration_ports import TranscriptDocumentProvider, get_document_provider
from .job_output_reconciliation import OutputReconciliationError, OutputReconciliationReason, prepare_output_reconciliation_case, mark_reconciliation_creation_returned
from .transcription_metadata import selected_provider, selected_model, source_provenance
from .models import SttProviderOperation, TranscriptionProviderPartCheckpoint
from .transcript_document import build_transcript_document_text
from .transcript_document_metadata import compact_provenance_lines, title_has_recording_date
from .transcription_options import document_language, job_diarization_enabled


class TranscriptWordProtocol(Protocol):
    text: str
    speaker_id: str | None


class TranscriptResultProtocol(Protocol):
    text_length: int
    detected_language_code: str | None
    words: tuple[TranscriptWordProtocol, ...]
    @property
    def text(self) -> str: ...


class JobGoogleDocsOutputReason(str, Enum):
    job_not_found = "job_not_found"
    job_not_processing = "job_not_processing"
    lease_not_owned = "lease_not_owned"
    lease_not_active = "lease_not_active"
    cancellation_requested = "cancellation_requested"
    project_unavailable = "project_unavailable"
    output_folder_missing = "output_folder_missing"
    google_connection_unavailable = "google_connection_unavailable"
    output_folder_unavailable = "output_folder_unavailable"
    output_identity_mismatch = "output_identity_mismatch"
    output_not_folder = "output_not_folder"
    output_folder_not_writable = "output_folder_not_writable"
    job_source_not_found = "job_source_not_found"
    job_source_not_processable = "job_source_not_processable"
    selected_source_changed = "selected_source_changed"
    lifecycle_changed_before_output_creation = "lifecycle_changed_before_output_creation"
    output_identity_changed_before_output_creation = "output_identity_changed_before_output_creation"
    transcript_context_closed = "transcript_context_closed"
    google_docs_authentication_rejected = "google_docs_authentication_rejected"
    google_docs_request_rejected = "google_docs_request_rejected"
    google_docs_rate_limited = "google_docs_rate_limited"
    google_docs_unavailable = "google_docs_unavailable"
    google_docs_timeout = "google_docs_timeout"
    malformed_google_docs_response = "malformed_google_docs_response"
    lifecycle_changed_after_output_creation = "lifecycle_changed_after_output_creation"
    context_closed = "context_closed"
    output_already_persisted = "output_already_persisted"
    existing_reconciliation_case = "existing_reconciliation_case"
    output_reconciliation_conflict = "output_reconciliation_conflict"
    reconciliation_case_persistence_failed = "reconciliation_case_persistence_failed"
    yandex_disk_quota_exceeded = "yandex_disk_quota_exceeded"
    yandex_disk_permission_denied = "yandex_disk_permission_denied"
    yandex_disk_reauthorization_required = "yandex_disk_access_expired"
    yandex_disk_document_conflict = "yandex_disk_document_conflict"
    yandex_disk_unavailable = "yandex_disk_unavailable"


class JobGoogleDocsOutputError(RuntimeError):
    def __init__(self, reason: JobGoogleDocsOutputReason):
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True)
class FormattedTranscriptDocument:
    title: str
    body: str
    language: str
    created_at: datetime | None


@dataclass(frozen=True)
class _OutputJobSnapshot:
    job_id: str
    owner_user_id: str
    project_id: str
    title: str | None
    language: str | None
    options_json: str | None
    output_drive_folder_id: str
    lease_owner_id: str | None
    lease_generation: int
    cancel_requested_at: datetime | None
    project_archived_at: datetime | None
    project_owner_user_id: str | None
    provider: str | None
    model: str
    clip_start: int | None
    clip_end: int | None
    output_provider: str = "google_drive"


@contextmanager
def create_processing_job_google_doc_from_transcript(
    db: Session,
    *,
    job_id: str,
    job_source_id: str,
    lease_owner_id: str,
    lease_generation: int,
    transcript: TranscriptResultProtocol,
    settings,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    token_resolver: Callable = refresh_user_google_drive_access_token,
    metadata_fetcher: Callable[[str, str], DriveFolderAuthorizationMetadata] | None = None,
    google_docs_transport: TranscriptDocumentProvider | Callable[..., object] | None = None,
) -> Iterator[GoogleDocsTranscriptArtifact]:
    clock = clock or (lambda: utcnow().replace(tzinfo=None))
    check_now = now or clock()
    artifact: GoogleDocsTranscriptArtifact | None = None
    _require_no_persisted_output(db, job_source_id)
    snap = _load_output_job_snapshot(db, job_id, lease_owner_id, lease_generation, check_now)
    if snap.output_provider == "yandex_disk":
        from .job_yandex_docx_output import create_processing_job_yandex_docx
        with create_processing_job_yandex_docx(db, job_id=job_id, job_source_id=job_source_id,
                lease_owner_id=lease_owner_id, lease_generation=lease_generation,
                transcript=transcript, settings=settings, now=check_now, clock=clock) as disk_artifact:
            yield disk_artifact
        return
    if snap.output_provider != "google_drive":
        raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.output_folder_unavailable)
    source_snap = _load_source_snapshot(db, job_id, job_source_id, lease_owner_id, lease_generation, check_now, settings)
    from .work_progress import report_work
    report_work("document_output")
    try:
        try:
            token = token_resolver(db, user_id=snap.owner_user_id, settings=settings)
        except GoogleConnectionAccessError as exc:
            raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.google_connection_unavailable) from exc
        try:
            meta = metadata_fetcher(token, snap.output_drive_folder_id) if metadata_fetcher else _fetch_drive_folder_authorization_metadata(token, snap.output_drive_folder_id)
            _validate_metadata(meta, snap.output_drive_folder_id)
        except OutputDestinationError as exc:
            raise JobGoogleDocsOutputError(_map_output_folder_reason(exc.reason.value)) from exc
        except Exception as exc:
            raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.output_folder_unavailable) from exc
        _compare_or_before(_load_output_job_snapshot(db, job_id, lease_owner_id, lease_generation, clock()), snap)
        _compare_source_or_before(_load_source_snapshot(db, job_id, job_source_id, lease_owner_id, lease_generation, clock(), settings), source_snap)
        formatted, provenance = format_job_transcript(db, snap, source_snap, transcript)
        _compare_or_before(_load_output_job_snapshot(db, job_id, lease_owner_id, lease_generation, clock()), snap)
        _compare_source_or_before(_load_source_snapshot(db, job_id, job_source_id, lease_owner_id, lease_generation, clock(), settings), source_snap)
        if _source_provenance_snapshot(db, source_snap) != provenance:
            raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.selected_source_changed)
        _require_no_persisted_output(db, job_source_id)
        try:
            case = prepare_output_reconciliation_case(db, job_id=job_id, job_source_id=job_source_id, lease_owner_id=lease_owner_id, lease_generation=lease_generation, document_title=formatted.title, character_count=len(formatted.body), now=clock())
        except OutputReconciliationError as exc:
            if exc.reason == OutputReconciliationReason.existing_reconciliation_case:
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.existing_reconciliation_case) from exc
            db.rollback()
            mapped = JobGoogleDocsOutputReason.output_already_persisted if exc.reason == OutputReconciliationReason.output_conflict else JobGoogleDocsOutputReason.output_reconciliation_conflict
            raise JobGoogleDocsOutputError(mapped) from exc
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.reconciliation_case_persistence_failed)
        transport = google_docs_transport or get_document_provider()
        try:
            result = _call_transport(transport, access_token=token, folder_id=snap.output_drive_folder_id, title=formatted.title, document_text=formatted.body, reconciliation_token=case.reconciliation_token)
        except GoogleDocsOutputError as exc:
            raise JobGoogleDocsOutputError(_map_docs_reason(exc.reason)) from exc
        # PWA-OUTPUT-01B intentionally owns persistence/reconciliation of this irreversible output side effect.
        try:
            _compare_or_after(_load_output_job_snapshot(db, job_id, lease_owner_id, lease_generation, clock()), snap)
            _compare_source_or_after(_load_source_snapshot(db, job_id, job_source_id, lease_owner_id, lease_generation, clock(), settings), source_snap)
            if _source_provenance_snapshot(db, source_snap) != provenance:
                raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.selected_source_changed)
        except Exception as exc:
            raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.lifecycle_changed_after_output_creation) from exc
        try:
            mark_reconciliation_creation_returned(db, job_source_id=job_source_id, document_id=result.document_id, web_view_url=result.web_view_link, document_created_at=clock(), now=clock())
            db.commit()
        except Exception as exc:
            db.rollback()
            raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.lifecycle_changed_after_output_creation) from exc
        artifact = new_google_docs_transcript_artifact(result=result, created_at=clock(), character_count=len(formatted.body))
        yield artifact
    finally:
        if artifact is not None:
            artifact.revoke()


def format_transcript_doc(*, title: str, transcript_text: str, job_language: str | None, detected_language_code: str | None, created_at: datetime | None, diarization_enabled: bool = False, provider: str = "elevenlabs", model: str = "scribe_v2", provenance_lines: tuple[str, ...] = ()) -> FormattedTranscriptDocument:
    safe_title = normalize_document_title(title)
    lang = document_language(job_language, detected_language_code)
    body = build_transcript_document_text(
        title=safe_title,
        metadata_lines=(
            f"Provider: {dict(elevenlabs='ElevenLabs', yandex='Yandex SpeechKit', mistral='Mistral Voxtral', gemini='Google Gemini Transcribe', tbank='T-Bank VoiceKit').get(provider, 'unknown')}",
            f"Model: {model}",
            f"Language: {lang}",
        ) + ((f"Created at: {_utc_iso(created_at)}",) if created_at is not None and not title_has_recording_date(safe_title) else ()) + compact_provenance_lines(provenance_lines),
        transcript_text=transcript_text,
    )
    return FormattedTranscriptDocument(title=safe_title, body=body, language=lang, created_at=created_at)


def build_speaker_labeled_transcript(
    words: tuple[TranscriptWordProtocol, ...],
    *,
    fallback_text: str,
) -> str:
    speaker_numbers: dict[str, int] = {}
    blocks: list[str] = []
    current_speaker: str | None = None
    current_tokens: list[str] = []
    saw_speaker = False

    def flush() -> None:
        nonlocal current_tokens
        if current_speaker is None:
            return
        text = _join_transcript_tokens(current_tokens)
        current_tokens = []
        if not text:
            return
        number = speaker_numbers.setdefault(current_speaker, len(speaker_numbers) + 1)
        blocks.append(f"Спикер {number}:\n{text}")

    for word in words:
        token = word.text
        if not token:
            continue
        speaker_id = (word.speaker_id or "").strip() or None
        if speaker_id is not None:
            saw_speaker = True
            if current_speaker is None:
                current_speaker = speaker_id
            elif speaker_id != current_speaker:
                flush()
                current_speaker = speaker_id
        current_tokens.append(token)

    flush()
    if not saw_speaker or not blocks:
        return fallback_text.strip()
    labeled = "\n\n".join(blocks)
    if any(re.fullmatch(r"part_[1-9]\d*:.*", speaker) for speaker in speaker_numbers):
        notice = "Метки спикеров определены отдельно в каждой части; личность между частями не сопоставлялась."
        return f"{labeled}\n\nПримечание: {notice}"
    return labeled


def _join_transcript_tokens(tokens: list[str]) -> str:
    text = ""
    for token in tokens:
        if (
            text
            and not text[-1].isspace()
            and not token[0].isspace()
            and text[-1].isalnum()
            and token[0].isalnum()
        ):
            text += " "
        text += token
    return text.strip()


def choose_transcript_document_title(*, job_title: str | None, original_filename: str | None) -> str:
    candidate = _first_nonblank(job_title)
    if candidate is None and original_filename:
        name = PurePath(original_filename).name.strip()
        stem = PurePath(name).stem.strip() if name else ""
        candidate = stem or name
    return normalize_document_title(candidate or "Transcript")


def normalize_document_title(value: str) -> str:
    cleaned = " ".join(value.replace("\x00", " ").split())
    return cleaned[:160] if cleaned else "Transcript"


def _load_output_job_snapshot(db: Session, job_id: str, owner: str, generation: int, now: datetime) -> _OutputJobSnapshot:
    db.expire_all()
    job = db.get(TranscriptionJob, job_id)
    if job is None:
        raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.job_not_found)
    if job.status != JobStatus.processing:
        raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.job_not_processing)
    if job.lease_owner_id != owner or job.lease_generation != generation:
        raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.lease_not_owned)
    if not is_lease_active(job, now):
        raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.lease_not_active)
    if job.cancel_requested_at is not None:
        raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.cancellation_requested)
    project = db.get(Project, job.project_id)
    if project is None or project.owner_user_id != job.owner_user_id or project.archived_at is not None:
        raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.project_unavailable)
    if not job.output_drive_folder_id:
        raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.output_folder_missing)
    provider = selected_provider(job.provider or "elevenlabs")
    model = selected_model(provider, job.options_json, job.operating_mode)
    identities = set()
    for table in (SttProviderOperation, TranscriptionProviderPartCheckpoint):
        identities.update(db.query(table.provider, table.model).filter(
            table.job_id == job.id, table.owner_user_id == job.owner_user_id,
            table.project_id == job.project_id).distinct().all())
    if identities:
        model = next(iter(identities))[1] if len(identities) == 1 and next(iter(identities))[0] == provider else "unknown"
    return _OutputJobSnapshot(job.id, job.owner_user_id, project.id, job.title, job.language, job.options_json, job.output_drive_folder_id, job.lease_owner_id, job.lease_generation, job.cancel_requested_at, project.archived_at, project.owner_user_id, job.provider, model, job.media_clip_start_seconds, job.media_clip_end_seconds, job.output_provider)


def _source_provenance_snapshot(db, source_snap):
    try:
        return source_provenance(db, source_snap)
    except ValueError as exc:
        raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.selected_source_changed) from exc


def _load_source_snapshot(db, job_id, job_source_id, owner, generation, now, settings):
    try:
        from .job_cached_transcript import fully_cached_relation
        job = db.get(TranscriptionJob, job_id)
        cached = job is not None and fully_cached_relation(db, job, job_source_id, now)
        return _load_selected_snapshot(db, job_id, job_source_id, owner, generation, now, settings, allow_retired_source=cached)
    except SourceMaterializationError as exc:
        value = exc.reason.value
        mapped = {
            "job_source_not_found": JobGoogleDocsOutputReason.job_source_not_found,
            "job_source_not_processable": JobGoogleDocsOutputReason.job_source_not_processable,
            "selected_source_changed": JobGoogleDocsOutputReason.selected_source_changed,
            "job_not_processing": JobGoogleDocsOutputReason.job_not_processing,
            "lease_not_owned": JobGoogleDocsOutputReason.lease_not_owned,
            "lease_not_active": JobGoogleDocsOutputReason.lease_not_active,
            "cancellation_requested": JobGoogleDocsOutputReason.cancellation_requested,
        }.get(value, JobGoogleDocsOutputReason.lifecycle_changed_before_output_creation)
        raise JobGoogleDocsOutputError(mapped) from exc


def _compare_or_before(current, expected) -> None:
    if current != expected:
        if current.output_drive_folder_id != expected.output_drive_folder_id:
            raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.output_identity_changed_before_output_creation)
        raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.lifecycle_changed_before_output_creation)


def _compare_source_or_before(current, expected) -> None:
    if current != expected:
        raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.lifecycle_changed_before_output_creation)


def _compare_or_after(current, expected) -> None:
    if current != expected:
        raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.lifecycle_changed_after_output_creation)


def _compare_source_or_after(current, expected) -> None:
    if current != expected:
        raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.lifecycle_changed_after_output_creation)


def _call_transport(transport, **kwargs):
    if hasattr(transport, "create_transcript_document"):
        return transport.create_transcript_document(**kwargs)
    return transport(**kwargs)


def _map_output_folder_reason(value: str) -> JobGoogleDocsOutputReason:
    return {
        "output_identity_mismatch": JobGoogleDocsOutputReason.output_identity_mismatch,
        "output_not_folder": JobGoogleDocsOutputReason.output_not_folder,
        "output_folder_not_writable": JobGoogleDocsOutputReason.output_folder_not_writable,
        "metadata_unavailable": JobGoogleDocsOutputReason.output_folder_unavailable,
        "output_folder_missing": JobGoogleDocsOutputReason.output_folder_missing,
    }.get(value, JobGoogleDocsOutputReason.output_folder_unavailable)


def _map_docs_reason(reason: GoogleDocsOutputReason) -> JobGoogleDocsOutputReason:
    return {
        GoogleDocsOutputReason.authentication_rejected: JobGoogleDocsOutputReason.google_docs_authentication_rejected,
        GoogleDocsOutputReason.request_rejected: JobGoogleDocsOutputReason.google_docs_request_rejected,
        GoogleDocsOutputReason.rate_limited: JobGoogleDocsOutputReason.google_docs_rate_limited,
        GoogleDocsOutputReason.unavailable: JobGoogleDocsOutputReason.google_docs_unavailable,
        GoogleDocsOutputReason.timeout: JobGoogleDocsOutputReason.google_docs_timeout,
        GoogleDocsOutputReason.malformed_response: JobGoogleDocsOutputReason.malformed_google_docs_response,
        GoogleDocsOutputReason.context_closed: JobGoogleDocsOutputReason.context_closed,
    }[reason]


def _first_nonblank(*values: str | None) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")



def _require_no_persisted_output(db: Session, job_source_id: str) -> None:
    if db.query(TranscriptionJobOutput.id).filter(TranscriptionJobOutput.job_source_id == job_source_id).first() is not None:
        raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.output_already_persisted)


def format_job_transcript(db, snap, source_snap, transcript):
    try:
        transcript_text = transcript.text
        diarization_enabled = job_diarization_enabled(snap.options_json)
        if diarization_enabled:
            transcript_text = build_speaker_labeled_transcript(
                transcript.words,
                fallback_text=transcript_text,
            )
    except (ElevenLabsTranscriptionError, GoogleDocsOutputError) as exc:
        raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.transcript_context_closed) from exc
    title = choose_transcript_document_title(job_title=snap.title, original_filename=source_snap.original_filename)
    provenance = _source_provenance_snapshot(db, source_snap)
    formatted = format_transcript_doc(
        title=title,
        transcript_text=transcript_text,
        job_language=snap.language,
        detected_language_code=transcript.detected_language_code,
        created_at=provenance[1],
        provider=selected_provider(snap.provider or "elevenlabs"),
        model=snap.model,
        provenance_lines=provenance[0] + ((f"Recording date provenance: {provenance[2]}",) if provenance[1] else ()) + ((f"Clip: {snap.clip_start or 0}-{snap.clip_end if snap.clip_end is not None else 'end'} seconds; source timeline",) if snap.clip_start is not None or snap.clip_end is not None else ()),
        diarization_enabled=diarization_enabled,
    )
    return formatted, provenance
