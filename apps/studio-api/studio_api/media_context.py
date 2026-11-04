"""Bounded, content-free media timeline projections for owner-facing recovery."""
import json
import math
import re
import hashlib


def parse_part_plan(value: str | None) -> tuple[dict, ...]:
    if not value or len(value) > 65536:
        return ()
    try:
        document = json.loads(value)
        parts = document["parts"]
        if type(document["version"]) is not int or document["version"] != 1 or not isinstance(parts, list) or not 1 <= len(parts) <= 256:
            return ()
        result = []
        for index, part in enumerate(parts):
            start, end = part["start_seconds"], part["end_seconds"]
            if type(part["part_index"]) is not int or part["part_index"] != index or isinstance(start, bool) or isinstance(end, bool):
                return ()
            if not all(isinstance(number, (int, float)) and math.isfinite(number) for number in (start, end)) or not 0 <= start < end:
                return ()
            if result and start <= result[-1]["start_seconds"]:
                return ()
            result.append({"part_index": index, "start_seconds": start, "end_seconds": end})
        return tuple(result)
    except (ValueError, TypeError, KeyError, RecursionError):
        return ()


def serialize_part_plan(parts) -> str:
    value = json.dumps({"version": 1, "parts": [
        {"part_index": index, "start_seconds": part.timeline_offset_seconds,
         "end_seconds": part.timeline_offset_seconds + part.duration_seconds}
        for index, part in enumerate(parts)
    ]}, separators=(",", ":"), allow_nan=False)
    if not parse_part_plan(value):
        raise ValueError("media_part_plan_invalid")
    return value


def parse_prepared_audio_context(value: str | None):
    if not value or len(value) > 2048:
        return None
    try:
        item = json.loads(value)
        if not isinstance(item, dict) or len(item.get("job_id", "")) != 36:
            return None
        for key in ("input_duration_ms", "output_duration_ms"):
            if type(item.get(key)) is not int or item[key] <= 0:
                return None
        if type(item.get("pauses_removed")) is not bool:
            return None
        result = {key: item[key] for key in ("job_id", "input_duration_ms", "output_duration_ms", "pauses_removed")}
        if "version" in item:
            if type(item["version"]) is not int or item["version"] != 2:
                return None
            digest, timeline_digest = item.get("content_sha256"), item.get("timeline_sha256")
            if (not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None
                    or (timeline_digest is not None and (not isinstance(timeline_digest, str)
                        or re.fullmatch(r"[a-f0-9]{64}", timeline_digest) is None))):
                return None
            result.update(version=2, content_sha256=digest, timeline_sha256=timeline_digest)
        return result
    except (ValueError, TypeError, KeyError, RecursionError):
        return None


def prepared_audio_context_payload(value: str | None):
    item = parse_prepared_audio_context(value)
    if item is None:
        return None
    result = {key: item[key] for key in ("job_id", "input_duration_ms", "output_duration_ms", "pauses_removed")}
    if item.get("version") == 2:
        result["original_timeline_available"] = item["timeline_sha256"] is not None
    return result


def prepared_audio_source_context(job, receipt):
    """A bounded Source claim points to the canonical job map, never copies it."""
    if not job.total_input_duration_ms or not job.output_duration_ms:
        return None
    from .audio_timeline import AudioTimeline
    from .audio_retained_frames import RetainedRecipe
    timeline_json = getattr(job, "output_timeline_json", None)
    input_ms = job.total_input_duration_ms
    pauses_removed = False
    if timeline_json:
        timeline = AudioTimeline.parse(timeline_json)
        if abs(timeline.output_duration_us - job.output_duration_ms * 1000) > 5000:
            raise ValueError("prepared_audio_duration_changed")
        input_ms = round(timeline.original_duration_us / 1000)
    recipe = getattr(job, "retained_frames_json", None)
    if recipe:
        tracks = RetainedRecipe.parse(recipe).tracks
        pauses_removed = any(sum(end - start for start, end in track.kept) < track.decoded_samples for track in tracks)
    for item in getattr(job, "inputs", ()):
        parent = parse_prepared_audio_context(getattr(getattr(item, "source", None), "prepared_audio_context_json", None))
        pauses_removed = pauses_removed or bool(parent and parent["pauses_removed"])
    payload = dict(version=2, job_id=job.id, input_duration_ms=input_ms, output_duration_ms=job.output_duration_ms,
        pauses_removed=pauses_removed, content_sha256=receipt.sha256,
        timeline_sha256=hashlib.sha256(timeline_json.encode()).hexdigest() if timeline_json else None)
    serialized = json.dumps(payload, separators=(",", ":"))
    if parse_prepared_audio_context(serialized) is None:
        raise ValueError("prepared_audio_context_invalid")
    return serialized


def load_prepared_audio_timeline(db, source, *, owner_user_id):
    """Resolve only the recorded owner/project/map version, with no fallback."""
    from .models import AudioPreparationJob, AudioPreparationStatus, SourceType
    from .audio_timeline import AudioTimeline, AudioTimelineError
    context = parse_prepared_audio_context(getattr(source, "prepared_audio_context_json", None))
    if context is None or context.get("version") != 2 or context["timeline_sha256"] is None:
        return None
    job = db.get(AudioPreparationJob, context["job_id"])
    if (job is None or job.owner_user_id != owner_user_id or job.project_id != source.project_id
            or job.status is not AudioPreparationStatus.completed or not job.output_timeline_json
            or source.source_type is not SourceType.google_drive or source.drive_file_id != job.output_drive_file_id
            or hashlib.sha256(job.output_timeline_json.encode()).hexdigest() != context["timeline_sha256"]):
        raise AudioTimelineError("prepared_audio_timeline_unavailable")
    timeline = AudioTimeline.parse(job.output_timeline_json)
    if (abs(timeline.original_duration_us - context["input_duration_ms"] * 1000) > 1000
            or abs(timeline.output_duration_us - context["output_duration_ms"] * 1000) > 5000):
        raise AudioTimelineError("prepared_audio_timeline_unavailable")
    return timeline


def known_prepared_duration_seconds(source) -> float | None:
    """Duration of the selected prepared version, never the original timeline."""
    context = prepared_audio_context_payload(getattr(source, "prepared_audio_context_json", None))
    if context is None or context["output_duration_ms"] > 604800000:
        return None
    return context["output_duration_ms"] / 1000
