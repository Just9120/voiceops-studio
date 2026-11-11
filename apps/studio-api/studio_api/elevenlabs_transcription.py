from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, BinaryIO, Callable, Mapping, Sequence

import httpx

from .transcript_catalog import CURRENT_TRANSCRIPTION_MODEL

ELEVENLABS_SPEECH_TO_TEXT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
# Only documented machine identifiers may cross the provider boundary. Messages,
# parameters, request IDs, and unknown future codes remain untrusted and redacted.
SAFE_PROVIDER_ERROR_CODES = frozenset(
    {
        "audio_too_long",
        "audio_too_short",
        "bad_request",
        "concurrent_limit_exceeded",
        "feature_not_available",
        "forbidden",
        "insufficient_credits",
        "insufficient_permissions",
        "invalid_api_key",
        "invalid_audio",
        "invalid_audio_format",
        "invalid_authorization_header",
        "invalid_content_type",
        "invalid_file_type",
        "invalid_parameters",
        "internal_error",
        "maintenance",
        "malformed_json",
        "missing_api_key",
        "missing_required_field",
        "model_access_denied",
        "quota_exceeded",
        "rate_limit_exceeded",
        "request_too_large",
        "service_unavailable",
        "sign_in_required",
        "subscription_required",
        "system_busy",
        "unauthorized",
        "unsupported_model",
        "workspace_access_denied",
    }
)


class ElevenLabsTranscriptionReason(str, Enum):
    provider_authentication_rejected = "provider_authentication_rejected"
    provider_payment_required = "provider_payment_required"
    provider_scope_rejected = "provider_scope_rejected"
    provider_request_rejected = "provider_request_rejected"
    provider_rate_limited = "provider_rate_limited"
    provider_unavailable = "provider_unavailable"
    provider_timeout = "provider_timeout"
    malformed_provider_response = "malformed_provider_response"
    context_closed = "context_closed"


class ElevenLabsTranscriptionError(RuntimeError):
    def __init__(
        self,
        reason: ElevenLabsTranscriptionReason,
        *,
        provider_error_code: str | None = None,
        http_status: int | None = None,
        assembly_code: str | None = None,
    ):
        self.reason = reason
        self.assembly_code = assembly_code if assembly_code in {
            "transcript_part_words_missing", "transcript_overlap_timestamps_missing", "transcript_assembly_empty",
        } else None
        self.provider_error_code = (
            provider_error_code
            if provider_error_code in SAFE_PROVIDER_ERROR_CODES
            else None
        )
        self.http_status = (
            http_status
            if type(http_status) is int and 100 <= http_status <= 599
            else None
        )
        super().__init__(reason.value)


def _safe_provider_error_code(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except Exception:
        return None
    if not isinstance(payload, Mapping):
        return None
    detail = payload.get("detail")
    if not isinstance(detail, Mapping):
        return None
    for field_name in ("code", "status"):
        candidate = detail.get(field_name)
        if isinstance(candidate, str) and candidate in SAFE_PROVIDER_ERROR_CODES:
            return candidate
    return None


def _raise_for_provider_error(response: httpx.Response) -> None:
    status = response.status_code
    reason = {
        401: ElevenLabsTranscriptionReason.provider_authentication_rejected,
        402: ElevenLabsTranscriptionReason.provider_payment_required,
        403: ElevenLabsTranscriptionReason.provider_scope_rejected,
        429: ElevenLabsTranscriptionReason.provider_rate_limited,
    }.get(status)
    if reason is None and status in {400, 404, 409, 422}:
        reason = ElevenLabsTranscriptionReason.provider_request_rejected
    if reason is None and status >= 500:
        reason = ElevenLabsTranscriptionReason.provider_unavailable
    if reason is None and not 200 <= status < 300:
        reason = ElevenLabsTranscriptionReason.provider_request_rejected
    if reason is not None:
        raise ElevenLabsTranscriptionError(
            reason,
            provider_error_code=_safe_provider_error_code(response),
            http_status=status,
        )


class _RevocableTranscript:
    def __init__(self, text: str, words: tuple["_WordData", ...]):
        self._text = text
        self._words = words
        self._revoked = False

    def text(self) -> str:
        if self._revoked:
            raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.context_closed)
        return self._text

    def words(self) -> tuple["ElevenLabsTranscriptWord", ...]:
        if self._revoked:
            raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.context_closed)
        return tuple(ElevenLabsTranscriptWord(_holder=self, _index=i) for i in range(len(self._words)))

    def word_text(self, index: int) -> str:
        if self._revoked:
            raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.context_closed)
        return self._words[index].text

    def word_data(self, index: int) -> "_WordData":
        if self._revoked:
            raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.context_closed)
        return self._words[index]

    def revoke(self) -> None:
        self._text = ""
        self._words = ()
        self._revoked = True


@dataclass(frozen=True)
class _WordData:
    text: str
    start: float | None = None
    end: float | None = None
    type: str | None = None
    speaker_id: str | None = None


@dataclass(frozen=True)
class ElevenLabsTranscriptWord:
    _holder: _RevocableTranscript = field(repr=False)
    _index: int = field(repr=False)

    @property
    def text(self) -> str:
        return self._holder.word_text(self._index)

    @property
    def start(self) -> float | None:
        return self._holder.word_data(self._index).start

    @property
    def end(self) -> float | None:
        return self._holder.word_data(self._index).end

    @property
    def type(self) -> str | None:
        return self._holder.word_data(self._index).type

    @property
    def speaker_id(self) -> str | None:
        return self._holder.word_data(self._index).speaker_id

    def __repr__(self) -> str:
        return "ElevenLabsTranscriptWord(text=<redacted>)"


@dataclass(frozen=True)
class ElevenLabsTranscriptResult:
    _holder: _RevocableTranscript = field(repr=False)
    text_length: int
    word_count: int
    detected_language_code: str | None = None
    language_probability: float | None = None

    @property
    def text(self) -> str:
        return self._holder.text()

    @property
    def words(self) -> tuple[ElevenLabsTranscriptWord, ...]:
        return self._holder.words()

    def revoke(self) -> None:
        self._holder.revoke()

    def __repr__(self) -> str:
        return (
            "ElevenLabsTranscriptResult(text=<redacted>, words=<redacted>, "
            f"text_length={self.text_length!r}, word_count={self.word_count!r}, "
            f"detected_language_code={self.detected_language_code!r}, language_probability={self.language_probability!r})"
        )


@dataclass(frozen=True)
class ElevenLabsTranscriptionTransport:
    endpoint: str = ELEVENLABS_SPEECH_TO_TEXT_URL
    timeout: float = 1800.0
    client: httpx.Client | None = field(default=None, repr=False)
    post: Callable[..., httpx.Response] | None = field(default=None, repr=False)

    def transcribe(
        self, *, api_key: str, stream: BinaryIO, filename: str, mime_type: str, language_code: str | None = None, diarize: bool = False, keyterms: Sequence[str] = (), model_id: str = CURRENT_TRANSCRIPTION_MODEL
    ) -> ElevenLabsTranscriptResult:
        data: dict[str, str | list[str]] = {
            "model_id": model_id,
            "no_verbatim": "false",
            "temperature": "0",
            "tag_audio_events": "false",
            "diarize": str(diarize).lower(),
            "use_multi_channel": "false",
            "timestamps_granularity": "word",
        }
        if language_code:
            data["language_code"] = language_code
        if keyterms:
            data["keyterms"] = list(keyterms[:100])
        files = {"file": (filename, stream, mime_type)}
        headers = {"xi-api-key": api_key}
        try:
            if self.post is not None:
                response = self.post(self.endpoint, headers=headers, data=data, files=files, timeout=self.timeout)
            elif self.client is not None:
                response = self.client.post(self.endpoint, headers=headers, data=data, files=files, timeout=self.timeout)
            else:
                with httpx.Client() as client:
                    response = client.post(self.endpoint, headers=headers, data=data, files=files, timeout=self.timeout)
        except httpx.TimeoutException as exc:
            raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.provider_timeout) from exc
        except httpx.HTTPError as exc:
            raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.provider_unavailable) from exc
        _raise_for_provider_error(response)
        try:
            payload = response.json()
        except Exception as exc:
            raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.malformed_provider_response) from exc
        result = normalize_elevenlabs_transcript_response(payload)
        if diarize and (result.text.strip() or result.word_count) and not any((word.speaker_id or "").strip() for word in result.words):
            result.revoke()
            raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.malformed_provider_response)
        return result

    def __repr__(self) -> str:
        return f"ElevenLabsTranscriptionTransport(endpoint={self.endpoint!r})"


def merge_elevenlabs_transcript_results(
    parts: Sequence[tuple[ElevenLabsTranscriptResult, float, float]],
) -> ElevenLabsTranscriptResult:
    if not parts:
        raise ElevenLabsTranscriptionError(
            ElevenLabsTranscriptionReason.malformed_provider_response,
        )

    merged_words: list[_WordData] = []
    language_codes: list[str | None] = []
    probabilities: list[float | None] = []
    for index, (result, timeline_offset, overlap_seconds) in enumerate(parts):
        if not math.isfinite(timeline_offset) or timeline_offset < 0:
            raise ElevenLabsTranscriptionError(
                ElevenLabsTranscriptionReason.malformed_provider_response,
            )
        if not math.isfinite(overlap_seconds) or overlap_seconds < 0:
            raise ElevenLabsTranscriptionError(
                ElevenLabsTranscriptionReason.malformed_provider_response,
            )
        current_words = tuple(
            _WordData(
                text=word.text,
                start=word.start,
                end=word.end,
                type=word.type,
                speaker_id=(f"part_{index + 1}:{word.speaker_id}" if len(parts) > 1 and word.speaker_id else word.speaker_id),
            )
            for word in result.words
        )
        if not current_words:
            if not result.text.strip():
                # A silent part is valid; its position still determines overlap
                # ownership for the following part.
                continue
            raise ElevenLabsTranscriptionError(
                ElevenLabsTranscriptionReason.malformed_provider_response,
                assembly_code="transcript_part_words_missing",
            )
        drop_count = 0
        if index:
            try:
                # Ownership ends at the actual overlap boundary. Identical
                # words after that boundary are separate speech.
                drop_count = _owned_overlap_prefix_count(current_words, overlap_seconds)
            except ElevenLabsTranscriptionError as exc:
                raise ElevenLabsTranscriptionError(
                    exc.reason, assembly_code="transcript_overlap_timestamps_missing",
                ) from exc
        for word in current_words[drop_count:]:
            merged_words.append(
                _WordData(
                    text=word.text,
                    start=_shift_timestamp(word.start, timeline_offset),
                    end=_shift_timestamp(word.end, timeline_offset),
                    type=word.type,
                    speaker_id=word.speaker_id,
                )
            )
        language_codes.append(result.detected_language_code)
        probabilities.append(result.language_probability)

    text = _join_transcript_tokens([word.text for word in merged_words])
    if not text.strip():
        raise ElevenLabsTranscriptionError(
            ElevenLabsTranscriptionReason.malformed_provider_response,
            assembly_code="transcript_assembly_empty",
        )
    language_code, probability = _merged_language(language_codes, probabilities)
    holder = _RevocableTranscript(text, tuple(merged_words))
    return ElevenLabsTranscriptResult(
        holder,
        text_length=len(text),
        word_count=len(merged_words),
        detected_language_code=language_code,
        language_probability=probability,
    )


def normalize_elevenlabs_transcript_response(payload: Any) -> ElevenLabsTranscriptResult:
    if not isinstance(payload, Mapping):
        raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.malformed_provider_response)
    text = payload.get("text")
    if not isinstance(text, str):
        raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.malformed_provider_response)
    language_code = payload.get("language_code") if isinstance(payload.get("language_code"), str) else None
    probability = payload.get("language_probability")
    if probability is not None:
        if not isinstance(probability, (int, float)) or isinstance(probability, bool) or not math.isfinite(float(probability)) or not 0 <= float(probability) <= 1:
            raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.malformed_provider_response)
        probability = float(probability)
    raw_words = payload.get("words", [])
    if raw_words is None:
        raw_words = []
    if not isinstance(raw_words, list):
        raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.malformed_provider_response)
    words = tuple(_normalize_word(item) for item in raw_words)
    holder = _RevocableTranscript(text, words)
    return ElevenLabsTranscriptResult(
        holder,
        text_length=len(text),
        word_count=len(words),
        detected_language_code=language_code,
        language_probability=probability,
    )


def _normalize_word(item: Any) -> _WordData:
    if not isinstance(item, Mapping):
        raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.malformed_provider_response)
    text = item.get("text")
    if not isinstance(text, str):
        raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.malformed_provider_response)
    start = _optional_timestamp(item.get("start"))
    end = _optional_timestamp(item.get("end"))
    if start is not None and end is not None and start > end:
        raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.malformed_provider_response)
    typ = item.get("type") if isinstance(item.get("type"), str) else None
    speaker = item.get("speaker_id") if isinstance(item.get("speaker_id"), str) else None
    return _WordData(text=text, start=start, end=end, type=typ, speaker_id=speaker)


def _optional_timestamp(value: Any) -> float | None:
    if value is None:
        return None
    valid_timestamp = (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0
    )
    if not valid_timestamp:
        raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.malformed_provider_response)
    return float(value)


def _owned_overlap_prefix_count(
    words: Sequence[_WordData],
    overlap_seconds: float,
) -> int:
    if overlap_seconds <= 0:
        return 0
    drop_count = 0
    saw_timestamp = False
    for index, word in enumerate(words):
        if word.start is None:
            if drop_count == index:
                drop_count = index + 1
            continue
        saw_timestamp = True
        if word.start < overlap_seconds:
            drop_count = index + 1
            continue
        break
    if not saw_timestamp:
        raise ElevenLabsTranscriptionError(
            ElevenLabsTranscriptionReason.malformed_provider_response,
        )
    return drop_count


def _shift_timestamp(value: float | None, offset: float) -> float | None:
    return None if value is None else value + offset


def _join_transcript_tokens(tokens: Sequence[str]) -> str:
    text = ""
    for token in tokens:
        if not token:
            continue
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


def _merged_language(
    codes: Sequence[str | None],
    probabilities: Sequence[float | None],
) -> tuple[str | None, float | None]:
    normalized = [code.strip().lower() if code else None for code in codes]
    if not normalized or normalized[0] is None or any(code != normalized[0] for code in normalized):
        return None, None
    available_probabilities = [value for value in probabilities if value is not None]
    probability = min(available_probabilities) if len(available_probabilities) == len(probabilities) else None
    return normalized[0], probability
