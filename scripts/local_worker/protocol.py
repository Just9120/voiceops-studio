"""Versioned outbound Studio protocol and complete native SALM response boundary."""
import hashlib
import http.client
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from uuid import UUID

from .model_profiles import INITIAL_MODEL_REVISIONS, MODEL, PARAKEET_MODEL, model_profile
RUNTIME_VERSION = "0.2.0+nightly.66d50d9"
MAX_INPUT_BYTES = 2147483647
MAX_RESULT_BYTES = 16 * 1024 * 1024
MAX_NATIVE_RESPONSE_BYTES = 64 * 1024 * 1024
COMPANION_PATH = "/api/local-execution/companion"
STUDIO_USER_AGENT = "VoiceOpsStudio-Companion/1"


class WorkerError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class APIError(WorkerError):
    def __init__(self, status, reason="local_api_unavailable"):
        self.status = status
        super().__init__(reason)


class Stopped(WorkerError):
    pass


def origin(value, *, allow_loopback=False):
    try:
        parsed = urllib.parse.urlsplit(value)
        local = parsed.hostname in {"127.0.0.1", "localhost"} and allow_loopback
        if (parsed.scheme != "https" and not (local and parsed.scheme == "http")) or not parsed.hostname:
            raise ValueError()
        if (parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment
                or parsed.path not in ("", "/") or not 0 < (parsed.port or 443) < 65536):
            raise ValueError()
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    except (TypeError, ValueError):
        raise WorkerError("local_origin_invalid") from None


def canonical_id(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError()
    except (TypeError, ValueError, AttributeError):
        raise WorkerError("local_job_invalid") from None
    return value


def strict_json(body):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    def bad_constant(_):
        raise ValueError()
    try:
        return json.loads(body, object_pairs_hook=object_pairs, parse_constant=bad_constant)
    except (ValueError, TypeError, RecursionError):
        raise WorkerError("local_response_invalid") from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class StudioClient:
    def __init__(self, base, token, *, allow_loopback=False, model=MODEL, revision=None):
        self.base = origin(base, allow_loopback=allow_loopback)
        if not isinstance(token, str) or re.fullmatch(r"vs-local\.[a-f0-9-]{36}\.[A-Za-z0-9_-]{43}", token) is None:
            raise WorkerError("local_pairing_token_invalid")
        try:
            if str(UUID(token.split(".")[1])) != token.split(".")[1]:
                raise ValueError()
        except ValueError:
            raise WorkerError("local_pairing_token_invalid") from None
        self.token = token
        revision = INITIAL_MODEL_REVISIONS.get(model) if revision is None else revision
        if model_profile(model, revision) is None:
            raise WorkerError("local_model_unavailable")
        self.model = model
        self.revision = revision
        self.job_trace = None

    def open(self, suffix, *, method="POST", body=None, content_type="application/json", timeout=20):
        if not re.fullmatch(r"(?:/heartbeat|/inventory|/model-removal|/model-install-request|/stopped|/claim|/jobs/[a-f0-9-]{36}/(?:heartbeat|failure|prepare|result|source\?generation=[0-9]{1,10}))", suffix):
            raise WorkerError("local_api_path_invalid")
        headers = {"Authorization": "Bearer " + self.token, "X-VoiceOps-Local-Protocol": "1", "User-Agent": STUDIO_USER_AGENT,
                   "Accept": "application/json", "Content-Type": content_type}
        job_trace = self.job_trace
        if job_trace is not None and suffix.startswith(f"/jobs/{job_trace[0]}/"):
            headers["X-Trace-ID"] = job_trace[1]
        request = urllib.request.Request(self.base + COMPANION_PATH + suffix, data=body, method=method, headers=headers)
        try:
            return urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            reason = "local_api_unavailable"
            try:
                data = strict_json(error.read(8193))
                candidate = data.get("detail", {}).get("reason") if isinstance(data, dict) else None
                if isinstance(candidate, str) and re.fullmatch(r"[a-z0-9_]{1,80}", candidate):
                    reason = candidate
            except (WorkerError, OSError, http.client.HTTPException):
                pass
            finally:
                error.close()
            raise APIError(error.code, reason) from None
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
            raise APIError(0) from None

    def json(self, suffix, payload=None):
        body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode() if payload is not None else b""
        with self.open(suffix, body=body) as response:
            data = response_bytes(response, 65536)
        if len(data) > 65536:
            raise WorkerError("local_response_too_large")
        return strict_json(data)

    def heartbeat(self, status):
        payload = {"runtime_status": status,
                   "runtime_version": RUNTIME_VERSION if status == "ready" else None,
                   "model": self.model, "model_revision": self.revision}
        return self.json("/heartbeat", payload)


def response_bytes(response, maximum):
    try:
        data = response.read(maximum + 1)
    except (OSError, TimeoutError, http.client.HTTPException):
        raise APIError(0) from None
    if len(data) > maximum:
        raise WorkerError("local_response_too_large")
    return data


def checked_job(data, *, model=MODEL, revision=None):
    if not isinstance(data, dict):
        raise WorkerError("local_job_invalid")
    job_id = canonical_id(data.get("id"))
    canonical_id(data.get("source_id"))
    generation = data.get("lease_generation")
    size = data.get("size_bytes")
    revision = INITIAL_MODEL_REVISIONS.get(model) if revision is None else revision
    claimed_revision = data.get("model_revision", INITIAL_MODEL_REVISIONS[MODEL] if model == MODEL else None)
    trace = data.get("trace_id")
    if (not isinstance(trace, str) or not re.fullmatch(r"trace_[A-Za-z0-9_-]{16,64}", trace)
            or any(part in trace.lower() for part in ("secret", "token", "bearer", "password"))):
        trace = None
    if (type(generation) is not int or not 1 <= generation <= 2147483647
            or type(size) is not int or not 0 < size <= MAX_INPUT_BYTES
            or data.get("model") != model or data.get("language") not in {"ru", "en"}
            or claimed_revision != revision or model_profile(model, revision) is None
            or (model == PARAKEET_MODEL and data.get("diarize") is not False)
            or type(data.get("diarize")) is not bool):
        raise WorkerError("local_job_invalid")
    return {"id": job_id, "generation": generation, "size_bytes": size, "model": model, "model_revision": revision,
            "trace_id": trace,
            "language": data["language"], "diarize": data["diarize"], "progress": data.get("progress")}


def _plain_text(value):
    return re.sub(r"<spk:[0-9]{1,6}>", "", value).strip()


def complete_native_result(data, *, duration, language, diarize):
    """Chat reports finish_reason, unlike the CLI's compact result JSON."""
    try:
        choices = data["choices"]
        detail = data["transcription"]
        if (data.get("model") != MODEL or not isinstance(choices, list) or len(choices) != 1 or choices[0]["finish_reason"] != "stop"
                or detail["schema_version"] != "1" or detail["task"] != "transcribe"
                or detail["transcript_origin"] != "llm" or detail.get("language") != language or not isinstance(detail["text"], str)
                or not isinstance(choices[0]["message"]["content"], str)
                or _plain_text(choices[0]["message"]["content"]) != _plain_text(detail["text"])):
            raise ValueError()
        measured = detail["duration"]
        if (type(measured) not in (int, float) or not 0 < measured <= 3600 or not math.isfinite(measured)
                or abs(measured - duration) > .05 or not _plain_text(detail["text"])):
            raise ValueError()
        raw_words = detail["words"]
        if not isinstance(raw_words, list) or len(raw_words) > 500000:
            raise ValueError()
        words = []
        for item in raw_words:
            if not isinstance(item, dict) or not isinstance(item["word"], str):
                raise ValueError()
            start, end = item.get("start"), item.get("end")
            if (start is None) != (end is None) or (start is not None and (
                    type(start) not in (int, float) or type(end) not in (int, float)
                    or not 0 <= start <= end <= measured + .05 or not math.isfinite(start) or not math.isfinite(end))):
                raise ValueError()
            word = {"word": item["word"], "start": start, "end": end, "confidence": 0}
            if diarize and item.get("speaker") is not None:
                speaker = item["speaker"]
                if not isinstance(speaker, str) or re.fullmatch(r"spk:[0-9]{1,6}", speaker) is None:
                    raise ValueError()
                word["speaker"] = speaker[4:]
            words.append(word)
        if diarize and not any("speaker" in word for word in words):
            raise ValueError()
        value = {"file": "prepared.wav", "text": _plain_text(detail["text"]), "confidence": 0,
                 "duration": measured, "languages": [language], "words": words}
        if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > MAX_RESULT_BYTES:
            raise ValueError()
        return value
    except (KeyError, TypeError, ValueError, AttributeError):
        raise WorkerError("local_result_incomplete") from None


def file_sha256(path, check=lambda: None):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            check()
            digest.update(chunk)
    return digest.hexdigest()
