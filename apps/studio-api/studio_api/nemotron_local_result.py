"""Normalize the pinned native NeMo-Speech.cpp JSON without exposing local paths."""
import json
import math
import re

from .batch_stt_transport import MAX_RESPONSE_BYTES, malformed
from .elevenlabs_transcription import normalize_elevenlabs_transcript_response

NEMOTRON_MODEL = "NVIDIA-Nemotron-3.5-Transcribe-30B-A4B"
NATIVE_RESULT_FIELDS = frozenset({"file", "text", "confidence", "duration", "languages", "words"})


def normalize_nemotron_local_result(payload, *, expected_duration_seconds, diarize=False):
    """Input is native complete-file output, on the prepared clip clock.

    A local path, native diagnostics, inferred recording date and generic model
    confidence never become document metadata or a language probability.
    """
    if (not isinstance(payload, dict) or set(payload) != NATIVE_RESULT_FIELDS
            or not isinstance(payload["text"], str) or not payload["text"].strip()
            or not isinstance(payload["words"], list) or len(payload["words"]) > 500000
            or not _duration(payload["duration"]) or not _duration(expected_duration_seconds)
            or abs(payload["duration"] - expected_duration_seconds) > .5):
        raise malformed()
    try:
        if len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise malformed()
    except (ValueError, TypeError, RecursionError) as exc:
        raise malformed() from exc
    languages = payload["languages"]
    if (not isinstance(languages, list) or len(languages) > 32
            or any(not isinstance(value, str) or re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z]{2,8})?", value) is None for value in languages)):
        raise malformed()
    words = []
    for word in payload["words"]:
        if (not isinstance(word, dict) or not isinstance(word.get("word"), str)
                or not set(word) <= {"word", "start", "end", "confidence", "speaker"}):
            raise malformed()
        start, end = word.get("start"), word.get("end")
        if (start is None) != (end is None):
            raise malformed()
        if start is not None and (not _time(start) or not _time(end)
                or start > end or end > payload["duration"] + .5):
            raise malformed()
        speaker = word.get("speaker")
        if speaker is not None:
            if type(speaker) is int and 0 <= speaker <= 1000000:
                speaker = str(speaker)
            elif not isinstance(speaker, str) or re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", speaker) is None:
                raise malformed()
            speaker = "local_" + speaker
        words.append(dict(text=word["word"], start=start, end=end, type="word", speaker_id=speaker if diarize else None))
    if diarize and not any(word["speaker_id"] for word in words):
        raise malformed()
    return normalize_elevenlabs_transcript_response(dict(text=payload["text"], words=words,
        language_code=languages[0] if len(languages) == 1 else None, language_probability=None))


def _time(value):
    return type(value) in (int, float) and 0 <= value <= 43200.5 and math.isfinite(value)


def _duration(value):
    return _time(value) and 0 < value <= 43200
