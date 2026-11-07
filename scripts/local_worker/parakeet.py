"""Pinned Parakeet complete-file adapter; a successful child and output are required."""
import json
from pathlib import Path

from .process import OwnedProcess
from .protocol import MAX_RESULT_BYTES, WorkerError, strict_json


def _validated_result(data, *, duration):
    try:
        if (not isinstance(data, dict) or set(data) != {"file", "text", "confidence", "duration", "languages", "words"}
                or not isinstance(data["text"], str) or not data["text"].strip()
                or type(data["duration"]) not in (int, float) or not 0 < data["duration"] <= 3600
                or abs(data["duration"] - duration) > .05
                or not isinstance(data["words"], list) or not 0 < len(data["words"]) <= 500000
                or not isinstance(data["languages"], list) or len(data["languages"]) > 32):
            raise ValueError()
        words = []
        for item in data["words"]:
            start, end = item["start"], item["end"]
            if (not isinstance(item["word"], str) or not item["word"].strip()
                    or type(start) not in (int, float) or type(end) not in (int, float)
                    or not 0 <= start <= end <= data["duration"] + .05):
                raise ValueError()
            words.append({"word": item["word"], "start": start, "end": end, "confidence": 0})
        languages = [value for value in data["languages"]
                     if isinstance(value, str) and len(value) in {2, 3} and value.isascii() and value.isalpha()]
        result = {"file": "prepared.wav", "text": data["text"].strip(), "confidence": 0,
                  "duration": data["duration"], "languages": languages, "words": words}
        if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > MAX_RESULT_BYTES:
            raise ValueError()
        return result
    except (KeyError, TypeError, ValueError):
        raise WorkerError("local_result_incomplete") from None


def transcribe_parakeet(runtime, model, audio, *, duration, language, diarize, check):
    if diarize or language not in {"ru", "en"}:
        raise WorkerError("local_model_unavailable")
    directory = Path(audio).parent
    output = directory / "parakeet-result.json"
    if output.exists():
        raise WorkerError("local_result_invalid")
    args = [str(runtime), "transcribe", str(audio), "--model", str(model), "--format", "json",
            "--output", str(output), "--word-times", "--device", "cpu", "--no-warmup"]
    with OwnedProcess(args, directory=directory, name="parakeet") as process:
        process.wait(check=check, timeout=7200)
        try:
            with output.open("rb") as stream:
                raw = stream.read(MAX_RESULT_BYTES + 1)
        except OSError:
            raise WorkerError("local_result_incomplete") from None
        if len(raw) > MAX_RESULT_BYTES:
            raise WorkerError("local_result_incomplete")
        return _validated_result(strict_json(raw), duration=duration)
