from __future__ import annotations

import base64
import json
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, BinaryIO, Callable, Mapping, Sequence
from urllib.parse import quote

import httpx
from sqlalchemy import select

from .elevenlabs_transcription import (
    ElevenLabsTranscriptResult,
    ElevenLabsTranscriptionError,
    ElevenLabsTranscriptionReason,
    normalize_elevenlabs_transcript_response,
)
from .models import SttProviderOperation, TranscriptionJob


SAFE_YANDEX_ERROR_CODES = frozenset({
    "UNAUTHENTICATED", "PERMISSION_DENIED", "RESOURCE_EXHAUSTED",
    "INVALID_ARGUMENT", "DEADLINE_EXCEEDED", "UNAVAILABLE", "INTERNAL",
})


def _language_code(value: str | None) -> str | None:
    return {"ru": "ru-RU", "en": "en-US"}.get((value or "").lower())


def _provider_error(response: httpx.Response) -> ElevenLabsTranscriptionError:
    reason = {
        401: ElevenLabsTranscriptionReason.provider_authentication_rejected,
        403: ElevenLabsTranscriptionReason.provider_scope_rejected,
        429: ElevenLabsTranscriptionReason.provider_rate_limited,
    }.get(response.status_code)
    if reason is None and response.status_code in {400, 404, 409, 422}:
        reason = ElevenLabsTranscriptionReason.provider_request_rejected
    if reason is None:
        reason = ElevenLabsTranscriptionReason.provider_unavailable
    code = None
    try:
        payload = response.json()
        candidate = payload.get("code") if isinstance(payload, Mapping) else None
        code = candidate if candidate in SAFE_YANDEX_ERROR_CODES else None
    except Exception:
        pass
    return ElevenLabsTranscriptionError(reason, provider_error_code=code, http_status=response.status_code)


@dataclass
class YandexTranscriptionTransport:
    db: Any = field(repr=False)
    job_id: str
    job_source_id: str
    settings: Any = field(repr=False)
    folder_id: str = field(repr=False)
    clock: Callable[[], datetime] = field(repr=False)
    client: httpx.Client | None = field(default=None, repr=False)
    sleeper: Callable[[float], None] = field(default=time.sleep, repr=False)

    def transcribe(
        self,
        *,
        api_key: str,
        stream: BinaryIO,
        filename: str,
        mime_type: str,
        language_code: str | None = None,
        diarize: bool = False,
        keyterms: Sequence[str] = (),
        model_id: str = "general",
    ) -> ElevenLabsTranscriptResult:
        del filename, mime_type, keyterms
        job = self.db.get(TranscriptionJob, self.job_id)
        if job is None:
            raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.provider_request_rejected)
        attempt_number = max(1, int(job.attempt_count or 1))
        operation = self.db.execute(
            select(SttProviderOperation)
            .where(
                SttProviderOperation.job_source_id == self.job_source_id,
                SttProviderOperation.job_id == job.id,
                SttProviderOperation.owner_user_id == job.owner_user_id,
                SttProviderOperation.project_id == job.project_id,
                SttProviderOperation.provider == "yandex",
            )
            .order_by(SttProviderOperation.attempt_number.desc())
            .limit(1)
            .with_for_update()
        ).scalar_one_or_none()
        if operation is not None and (
            operation.attempt_number > attempt_number
            or operation.operating_mode != job.operating_mode
            or operation.model != model_id
        ):
            raise ElevenLabsTranscriptionError(
                ElevenLabsTranscriptionReason.provider_request_rejected
            )
        if operation is not None and operation.status == "completed":
            return self._load_result(operation)
        if (
            operation is not None
            and operation.status == "failed"
            and operation.attempt_number == attempt_number
        ):
            raise ElevenLabsTranscriptionError(
                ElevenLabsTranscriptionReason.provider_request_rejected
            )
        if operation is not None and operation.status == "failed":
            operation = None
        if operation is None:
            operation_id = self._submit(
                api_key=api_key,
                stream=stream,
                model_id=model_id,
                language_code=_language_code(language_code),
                diarize=diarize,
            )
            operation = SttProviderOperation(
                owner_user_id=job.owner_user_id,
                project_id=job.project_id,
                job_id=job.id,
                job_source_id=self.job_source_id,
                attempt_number=attempt_number,
                provider="yandex",
                operating_mode=job.operating_mode,
                model=model_id,
                operation_id=operation_id,
                status="pending",
                submitted_at=self.clock(),
                created_at=self.clock(),
                updated_at=self.clock(),
            )
            self.db.add(operation)
            self.db.commit()  # Durable provider authority exists before the first poll.
        payload = self._poll_and_load(api_key=api_key, operation=operation)
        result = normalize_yandex_transcript_response(payload)
        self._persist_result(operation, result)
        return result

    def _headers(self, api_key: str) -> dict[str, str]:
        key = api_key.strip()
        if not key:
            raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.provider_authentication_rejected)
        return {
            "Authorization": f"Api-Key {key}",
            "x-folder-id": self.folder_id,
            "Accept": "application/json",
        }

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            if self.client is not None:
                response = self.client.request(method, url, **kwargs)
            else:
                with httpx.Client() as client:
                    response = client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.provider_timeout) from exc
        except httpx.HTTPError as exc:
            raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.provider_unavailable) from exc
        if not 200 <= response.status_code < 300:
            raise _provider_error(response)
        return response

    def _submit(self, *, api_key: str, stream: BinaryIO, model_id: str, language_code: str | None, diarize: bool) -> str:
        stream.seek(0)
        encoded = base64.b64encode(stream.read()).decode("ascii")
        recognition_model: dict[str, Any] = {
            "model": model_id,
            "audioFormat": {"containerAudio": {"containerAudioType": "OGG_OPUS"}},
            "textNormalization": {
                "textNormalization": "TEXT_NORMALIZATION_ENABLED",
                "profanityFilter": False,
                "literatureText": True,
            },
            "audioProcessingType": "FULL_DATA",
        }
        if language_code:
            recognition_model["languageRestriction"] = {
                "restrictionType": "WHITELIST",
                "languageCode": [language_code],
            }
        payload: dict[str, Any] = {"content": encoded, "recognitionModel": recognition_model}
        if diarize:
            payload["speakerLabeling"] = {"speakerLabeling": "SPEAKER_LABELING_ENABLED"}
        response = self._request(
            "POST",
            self.settings.yandex_stt_api_base_url.rstrip("/") + "/stt/v3/recognizeFileAsync",
            headers={**self._headers(api_key), "Content-Type": "application/json"},
            json=payload,
            timeout=1800.0,
        )
        try:
            operation_id = response.json().get("id")
        except Exception as exc:
            raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.malformed_provider_response) from exc
        if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 256:
            raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.malformed_provider_response)
        return operation_id

    def _poll_and_load(self, *, api_key: str, operation: SttProviderOperation) -> Any:
        deadline = time.monotonic() + self.settings.yandex_operation_timeout_seconds
        operation_url = self.settings.yandex_operations_api_base_url.rstrip("/") + "/operations/" + quote(operation.operation_id, safe="")
        while True:
            if time.monotonic() >= deadline:
                raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.provider_timeout)
            response = self._request("GET", operation_url, headers=self._headers(api_key), timeout=30.0)
            try:
                state = response.json()
            except Exception as exc:
                raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.malformed_provider_response) from exc
            operation.last_polled_at = self.clock()
            operation.updated_at = self.clock()
            self.db.commit()
            if state.get("done") is True:
                if state.get("error"):
                    operation.status = "failed"
                    operation.completed_at = self.clock()
                    operation.updated_at = self.clock()
                    self.db.commit()
                    raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.provider_request_rejected)
                break
            self.sleeper(self.settings.yandex_operation_poll_interval_seconds)
        result_url = self.settings.yandex_stt_api_base_url.rstrip("/") + "/stt/v3/getRecognition?operationId=" + quote(operation.operation_id, safe="")
        response = self._request("GET", result_url, headers=self._headers(api_key), timeout=1800.0)
        return _decode_streaming_json(response)

    def _persist_result(self, operation: SttProviderOperation, result: ElevenLabsTranscriptResult) -> None:
        from .provider_result_cache import persist_operation_result
        persist_operation_result(self.db, operation, result, settings=self.settings, now=self.clock())

    def _load_result(self, operation: SttProviderOperation) -> ElevenLabsTranscriptResult:
        from .provider_result_cache import load_operation_result
        return load_operation_result(operation, settings=self.settings)


def _decode_streaming_json(response: httpx.Response) -> list[Mapping[str, Any]]:
    try:
        payload = response.json()
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, Mapping)]
        if isinstance(payload, Mapping):
            items = payload.get("streamingResponses") or payload.get("streaming_responses")
            if isinstance(items, list):
                return [item for item in items if isinstance(item, Mapping)]
            return [payload]
    except Exception:
        pass
    result: list[Mapping[str, Any]] = []
    for line in response.text.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, Mapping):
            result.append(item)
    if not result:
        raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.malformed_provider_response)
    return result


def _nonnegative_int64(value: Any) -> int:
    # REST protobuf int64 fields use decimal strings; retain legacy numbers.
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,19}", value):
        value = int(value)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 <= value <= 9_223_372_036_854_775_807
        or (isinstance(value, float) and not value.is_integer())
    ):
        raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.malformed_provider_response)
    return int(value)


def _word_timestamp(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = _nonnegative_int64(value)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 <= value <= 9_223_372_036_854_775_807
    ):
        raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.malformed_provider_response)
    return float(value) / 1000


def _language_probability(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and len(value) <= 64 and re.fullmatch(
        r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value
    ):
        value = float(value)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 <= value <= 1
        or not math.isfinite(value)
    ):
        raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.malformed_provider_response)
    return float(value)


def normalize_yandex_transcript_response(payload: Any) -> ElevenLabsTranscriptResult:
    events = payload if isinstance(payload, list) else [payload]
    final_by_index: dict[int, Mapping[str, Any]] = {}
    final_order: list[int] = []
    detected_language = None
    probability = None
    for sequence, event in enumerate(events):
        if not isinstance(event, Mapping):
            continue
        if isinstance(event.get("result"), Mapping):
            event = event["result"]  # HTTP streaming gateway envelope.
        refinement = event.get("finalRefinement") or event.get("final_refinement")
        final = event.get("final")
        if isinstance(refinement, Mapping):
            index = _nonnegative_int64(refinement.get("finalIndex", refinement.get("final_index", sequence)))
            update = refinement.get("normalizedText") or refinement.get("normalized_text")
        elif isinstance(final, Mapping):
            cursors = event.get("audioCursors") or event.get("audio_cursors") or {}
            index = _nonnegative_int64(cursors.get("finalIndex", cursors.get("final_index", sequence))) if isinstance(cursors, Mapping) else sequence
            update = final
        else:
            continue
        alternatives = update.get("alternatives") if isinstance(update, Mapping) else None
        if not isinstance(alternatives, list) or not alternatives or not isinstance(alternatives[0], Mapping):
            continue
        alternative = alternatives[0]
        # AlternativeUpdate owns channelTag in REST; root tags are legacy.
        channel_tag = update.get("channelTag", update.get("channel_tag"))
        if channel_tag in (None, ""):
            channel_tag = event.get("channelTag", event.get("channel_tag"))
        if channel_tag in (None, ""):
            channel_tag = final_by_index.get(index, {}).get("speaker_id")
        if channel_tag is not None and (
            isinstance(channel_tag, bool) or not isinstance(channel_tag, (str, int))
        ):
            raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.malformed_provider_response)
        final_by_index[index] = {**alternative, "speaker_id": str(channel_tag) if channel_tag is not None else None}
        if index not in final_order:
            final_order.append(index)
        languages = alternative.get("languages")
        if isinstance(languages, list) and languages and isinstance(languages[0], Mapping):
            language = languages[0]
            detected_language = language.get("languageCode") or language.get("language_code") or detected_language
            probability = _language_probability(language.get("probability"))
    normalized_words: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for index in final_order:
        alternative = final_by_index[index]
        text = alternative.get("text")
        if isinstance(text, str) and text.strip():
            text_parts.append(text.strip())
        words = alternative.get("words")
        if isinstance(words, list):
            for word in words:
                if not isinstance(word, Mapping) or not isinstance(word.get("text"), str):
                    continue
                start = word.get("startTimeMs", word.get("start_time_ms"))
                end = word.get("endTimeMs", word.get("end_time_ms"))
                normalized_words.append({
                    "text": word["text"],
                    "start": _word_timestamp(start),
                    "end": _word_timestamp(end),
                    "type": "word",
                    "speaker_id": alternative.get("speaker_id"),
                })
    if not text_parts and not normalized_words:
        raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.malformed_provider_response)
    text = " ".join(text_parts).strip() or " ".join(word["text"] for word in normalized_words).strip()
    return normalize_elevenlabs_transcript_response({
        "text": text,
        "words": normalized_words,
        "language_code": detected_language,
        "language_probability": probability,
    })
