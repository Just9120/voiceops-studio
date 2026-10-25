"""Owner-selected metadata snapshot; no transcript bodies or credentials."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from sqlalchemy import select

from .google_connection_access import active_google_connection_for_user, require_drive_file_scope, refresh_user_google_drive_access_token
from .google_drive_upload import upload_file_resumable, GoogleDriveUploadError, GoogleDriveUploadReason, _safe_drive_identifier
from .job_output_destination import _fetch_drive_folder_authorization_metadata, _validate_metadata
from .models import TranscriptCatalogEntry, TranscriptionJob, TranscriptionJobOutput, TranscriptionJobSource, User
from .transcript_catalog import TRANSCRIPT_OUTPUT_KINDS
from .transcription_options import job_diarization_enabled

MAX_ENTRIES = 5000
MAX_BYTES = 8 * 1024 * 1024


def manifest_snapshot(db, *, user_id):
    # Serialize export and clear for this owner, including repeated uploads.
    user = db.execute(select(User).where(User.id == user_id).with_for_update()
        .execution_options(populate_existing=True)).scalar_one()
    outputs = select(TranscriptionJobOutput, TranscriptionJob, TranscriptionJobSource).join(
        TranscriptionJob, TranscriptionJob.id == TranscriptionJobOutput.job_id).join(
        TranscriptionJobSource, TranscriptionJobSource.id == TranscriptionJobOutput.job_source_id).where(
        TranscriptionJob.owner_user_id == user_id,
        TranscriptionJobOutput.output_kind.in_(TRANSCRIPT_OUTPUT_KINDS),
        TranscriptionJobOutput.document_character_count > 0)
    catalog = select(TranscriptCatalogEntry).where(TranscriptCatalogEntry.owner_user_id == user_id)
    if user.manifest_reset_at is not None:
        outputs = outputs.where(TranscriptionJobOutput.persisted_at > user.manifest_reset_at)
        catalog = catalog.where(TranscriptCatalogEntry.updated_at > user.manifest_reset_at)
    rows = db.execute(outputs.order_by(TranscriptionJobOutput.id).limit(MAX_ENTRIES + 1)).all()
    imported = db.scalars(catalog.order_by(TranscriptCatalogEntry.id).limit(MAX_ENTRIES + 1)).all()
    if len(rows) + len(imported) > MAX_ENTRIES:
        raise ValueError("manifest_export_limit")
    entries = [{"origin": "studio", "document_id": output.document_id,
        "output_provider": job.output_provider, "output_kind": output.output_kind,
        "source_id": source.source_id, "provider": job.provider, "operating_mode": job.operating_mode,
        "language": job.language, "diarization_enabled": job_diarization_enabled(job.options_json),
        "clip_start_seconds": job.media_clip_start_seconds, "clip_end_seconds": job.media_clip_end_seconds,
        "transcript_standard": output.transcript_standard,
        "document_created_at": output.document_created_at.isoformat()}
        for output, job, source in rows]
    entries.extend({"origin": "imported", "document_id": entry.document_id,
        "document_name": entry.document_name, "transcript_standard": entry.transcript_standard,
        "settings_status": entry.settings_status.value, "provider": entry.provider,
        "model": entry.model, "language": entry.language_mode,
        "diarization_enabled": entry.diarization_enabled,
        "source_identity_kind": entry.source_identity_kind.value if entry.source_identity_kind else None,
        "source_identity_value": entry.source_identity_value} for entry in imported)
    payload = json.dumps({"format": "studio-manifest-snapshot-v1", "entries": entries},
        ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if len(payload) > MAX_BYTES:
        raise ValueError("manifest_export_limit")
    return payload, len(entries)


def export_manifest(db, *, user_id, folder_id, settings):
    conn = active_google_connection_for_user(db, user_id=user_id)
    require_drive_file_scope(conn)
    payload, count = manifest_snapshot(db, user_id=user_id)
    token = refresh_user_google_drive_access_token(db, user_id=user_id, settings=settings)
    _validate_metadata(_fetch_drive_folder_authorization_metadata(token, folder_id), folder_id)
    identity = hashlib.sha256(user_id.encode() + b"\0" + payload).hexdigest()
    with tempfile.TemporaryDirectory(prefix="studio-manifest-") as directory:
        path = Path(directory) / "manifest.json"
        path.write_bytes(payload)
        result = upload_file_resumable(token, folder_id=folder_id, path=path,
            filename="Studio manifest.json", mime_type="application/json",
            idempotency_key=identity, app_property_key="studioManifestSnapshot")
    if not _safe_drive_identifier(result.file_id):
        raise GoogleDriveUploadError(GoogleDriveUploadReason.malformed_response)
    return {"ok": True, "entry_count": count, "web_view_url": f"https://drive.google.com/file/d/{result.file_id}/view"}
