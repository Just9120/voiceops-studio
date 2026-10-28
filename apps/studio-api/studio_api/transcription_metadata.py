"""Provider identity and bounded provenance without credentials or inferred dates."""
from __future__ import annotations

import json

MODEL_OPTION = "_stt_model"
SUPPORTED_MODELS = {
    ("mistral", "voxtral-small-transcribe-3"): "mistral_voxtral_small_transcribe_3",
    ("gemini", "gemini-3.5-transcribe"): "gemini_35_transcribe",
    ("tbank", "default"): "tbank_default",
    ("elevenlabs", "scribe_v2"): "elevenlabs_scribe_v2",
    ("yandex", "general"): "yandex_general",
    ("yandex", "deferred-general"): "yandex_deferred_general",
}


def selected_provider(explicit, credential=None) -> str:
    # The job is the durable selection; mutable/deleted credentials are fallback
    # only for legacy jobs that predate explicit provider selection.
    value = str(explicit or credential or "").strip().lower()
    return value if value in {"elevenlabs", "yandex", "mistral", "gemini", "tbank"} else "unknown"


def stored_model(options_json: str | None) -> str | None:
    try:
        payload = json.loads(options_json or "{}")
        value = payload.get(MODEL_OPTION) if isinstance(payload, dict) else None
    except (ValueError, TypeError):
        return None
    if isinstance(value, str) and 0 < len(value) <= 80 and not any(ord(c) < 32 for c in value):
        return value
    return None


def selected_model(provider: str, options_json: str | None, mode: str | None = None) -> str:
    model = stored_model(options_json)
    if model:
        return model
    # Historical job contracts had fixed models; never consult current config.
    if provider == "elevenlabs":
        return "scribe_v2"
    if provider == "yandex":
        return "deferred-general" if mode == "economic" else "general"
    return "unknown"


def analytics_bucket(provider: str, options_json: str | None, mode: str | None = None) -> str:
    return SUPPORTED_MODELS.get((provider, selected_model(provider, options_json, mode)), "unknown")


def source_provenance(db, snapshot):
    """Return immutable comparable metadata for owned prepared Drive/legacy audio.

    A Drive export's creation time is not the recording time. Original inputs
    and the preparation recipe supply provenance even after their bytes expire.
    No filename matching or foreign-owner inference is permitted.
    """
    from sqlalchemy import or_, select
    from .models import AudioPreparationJob, Project

    filters = [AudioPreparationJob.output_source_id == snapshot.source_id]
    if snapshot.drive_file_id:
        filters.append(AudioPreparationJob.output_drive_file_id == snapshot.drive_file_id)
    prepared = db.execute(select(AudioPreparationJob).where(
        AudioPreparationJob.owner_user_id == snapshot.job_owner_user_id,
        AudioPreparationJob.project_id == snapshot.source_project_id,
        or_(*filters),
    ).order_by(AudioPreparationJob.id).limit(2)).scalars().all()
    lines = [f"Source: {snapshot.source_id} · {_line(snapshot.original_filename)}"]
    if not prepared:
        return tuple(lines), snapshot.source_created_at, snapshot.source_created_at_provenance
    if len(prepared) != 1:
        raise ValueError("ambiguous preparation provenance")
    preparation = prepared[0]
    lines += [f"Preparation: {preparation.id}", "Timeline: prepared audio", f"Transformations: {_line(preparation.options_json)}"]
    dates = []
    originals = []
    inputs = preparation.inputs
    if not inputs or len(inputs) > 50:
        raise ValueError("invalid preparation inputs")
    for item in inputs:
        source = item.source
        project = db.get(Project, source.project_id) if source else None
        if source is None or project is None or project.owner_user_id != snapshot.job_owner_user_id:
            raise ValueError("foreign preparation source")
        original = {"position": item.position, "source_id": source.id, "filename": _line(source.original_filename)}
        if source.source_created_at is not None and source.source_created_at_provenance:
            dates.append((source.source_created_at, source.source_created_at_provenance))
            original.update(recording_date=source.source_created_at.isoformat(), date_provenance=source.source_created_at_provenance)
        originals.append(original)
    lines.append("Original source: " + json.dumps(originals, ensure_ascii=False, separators=(",", ":")))
    # Do not manufacture a whole-recording date from a partially known concat.
    date, authority = min(dates, key=lambda pair: pair[0]) if len(dates) == len(inputs) else (None, None)
    return tuple(lines), date, authority


def _line(value) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split())[:4096]
