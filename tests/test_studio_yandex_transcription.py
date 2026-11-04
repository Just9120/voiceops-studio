from __future__ import annotations

import base64
import asyncio
import io
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[1]
STUDIO_API = ROOT / "apps" / "studio-api"
if str(STUDIO_API) not in sys.path:
    sys.path.insert(0, str(STUDIO_API))
os.environ.setdefault("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")

from studio_api.yandex_realtime_relay import (  # noqa: E402
    MAX_AUDIO_CHUNK_BYTES,
    MAX_SESSION_AUDIO_BYTES,
    YandexRealtimeCapabilityError,
    _realtime_health_failure_code,
    _realtime_user_failure_code,
    _session_options,
    _validated_audio_chunk,
    create_yandex_realtime_capability,
    decode_yandex_realtime_capability,
    relay_yandex_realtime,
)
from studio_api.elevenlabs_transcription import (  # noqa: E402
    ElevenLabsTranscriptionError,
    ElevenLabsTranscriptionReason,
)
from studio_api.yandex_transcription import (  # noqa: E402
    YandexTranscriptionTransport,
    _decode_streaming_json,
    normalize_yandex_transcript_response,
)

import grpc  # noqa: E402
from studio_api import yandex_realtime_relay as realtime_relay  # noqa: E402
from studio_api.yandex_realtime_events import YandexRealtimeEvents  # noqa: E402
from studio_api.yandex_realtime_pb2 import StreamingResponse, AlternativeUpdate, Alternative, AudioCursors, FinalRefinement  # noqa: E402


class Settings:
    app_origin = "https://studio.example"
    credential_key_id = "studio-v1"

    @staticmethod
    def master_key_b64():
        return base64.urlsafe_b64encode(b"k" * 32).decode("ascii")


@pytest.mark.parametrize(
    ("status_code", "failure_code"),
    [
        (grpc.StatusCode.RESOURCE_EXHAUSTED, "provider_rate_limited"),
        (grpc.StatusCode.DEADLINE_EXCEEDED, "provider_timeout"),
        (grpc.StatusCode.UNAVAILABLE, "provider_unavailable"),
        (grpc.StatusCode.INTERNAL, "provider_unavailable"),
        (grpc.StatusCode.UNKNOWN, "provider_unavailable"),
        (grpc.StatusCode.UNAUTHENTICATED, None),
        (grpc.StatusCode.PERMISSION_DENIED, None),
        (grpc.StatusCode.INVALID_ARGUMENT, None),
    ],
)
def test_yandex_realtime_health_uses_only_systemic_provider_failures(
    status_code,
    failure_code,
):
    assert _realtime_health_failure_code(status_code) == failure_code


@pytest.mark.parametrize(
    ("status_code", "failure_code"),
    [
        (grpc.StatusCode.RESOURCE_EXHAUSTED, "provider_rate_limited"),
        (grpc.StatusCode.DEADLINE_EXCEEDED, "provider_timeout"),
        (grpc.StatusCode.UNAVAILABLE, "provider_unavailable"),
        (grpc.StatusCode.UNAUTHENTICATED, "provider_authentication_rejected"),
        (grpc.StatusCode.PERMISSION_DENIED, "provider_authentication_rejected"),
        (grpc.StatusCode.INVALID_ARGUMENT, "provider_request_rejected"),
        (grpc.StatusCode.CANCELLED, "provider_unavailable"),
    ],
)
def test_yandex_realtime_maps_grpc_status_to_safe_user_failure(
    status_code,
    failure_code,
):
    assert _realtime_user_failure_code(status_code) == failure_code


def test_yandex_realtime_health_write_is_bounded_and_best_effort(monkeypatch):
    calls = []

    class HealthDb:
        def commit(self):
            calls.append("commit")

        def rollback(self):
            calls.append("rollback")

        def close(self):
            calls.append("close")

    monkeypatch.setattr(realtime_relay, "SessionLocal", HealthDb)
    monkeypatch.setattr(
        realtime_relay,
        "record_provider_failure",
        lambda _db, **kwargs: calls.append(kwargs),
    )
    settings = SimpleNamespace(
        stt_health_failure_threshold=3,
        stt_health_cooldown_seconds=300,
    )

    realtime_relay._record_realtime_provider_health(
        settings=settings,
        failure_code="provider_timeout",
    )

    assert calls[0]["provider"] == "yandex"
    assert calls[0]["operating_mode"] == "realtime"
    assert calls[0]["failure_code"] == "provider_timeout"
    assert calls[0]["threshold"] == 3
    assert calls[0]["cooldown_seconds"] == 300
    assert calls[1:] == ["commit", "close"]


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _YandexDb:
    def __init__(self):
        self.job = SimpleNamespace(
            id="job",
            owner_user_id="owner",
            project_id="project",
            attempt_count=1,
            operating_mode="standard",
        )
        self.operation = None
        self.commits = 0

    def get(self, _model, row_id):
        return self.job if row_id == self.job.id else None

    def execute(self, _statement):
        return _ScalarResult(self.operation)

    def add(self, operation):
        operation.id = str(uuid.uuid4())
        self.operation = operation

    def commit(self):
        self.commits += 1


class _YandexClient:
    def __init__(self, db: _YandexDb):
        self.db = db
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == "POST":
            return httpx.Response(200, json={"id": "operation-safe"})
        assert self.db.operation is not None
        assert self.db.operation.operation_id == "operation-safe"
        assert self.db.operation.status == "pending"
        assert self.db.commits >= 1
        if "/operations/" in url:
            return httpx.Response(200, json={"done": True})
        return httpx.Response(
            200,
            json={
                "streamingResponses": [
                    {
                        "final": {
                            "alternatives": [
                                {
                                    "text": "Проверка завершена",
                                    "words": [
                                        {
                                            "text": "Проверка",
                                            "startTimeMs": "0",
                                            "endTimeMs": "400",
                                        },
                                        {
                                            "text": "завершена",
                                            "startTimeMs": "420",
                                            "endTimeMs": "800",
                                        },
                                    ],
                                }
                            ],
                            "channelTag": "0",
                        },
                        "audioCursors": {"finalIndex": "0"},
                    }
                ]
            },
        )


def test_yandex_normalization_preserves_text_words_language_and_speakers():
    result = normalize_yandex_transcript_response(
        [
            {
                "final": {
                    "alternatives": [
                        {
                            "text": "Добрый день",
                            "words": [
                                {"text": "Добрый", "startTimeMs": 0, "endTimeMs": 300},
                                {"text": "день", "startTimeMs": 320, "endTimeMs": 600},
                            ],
                            "languages": [{"languageCode": "ru-RU", "probability": 0.99}],
                        }
                    ]
                },
                "audioCursors": {"finalIndex": 0},
                "channelTag": "speaker-1",
            }
        ]
    )
    assert result.text == "Добрый день"
    assert result.detected_language_code == "ru-RU"
    assert result.words[0].start == 0
    assert result.words[1].end == 0.6
    assert {word.speaker_id for word in result.words} == {"speaker-1"}


@pytest.mark.parametrize("snake_case", [False, True])
@pytest.mark.parametrize("wire_shape", ["single", "array", "collection", "ndjson"])
def test_yandex_official_rest_wire_preserves_refined_timing_channel_and_probability(snake_case, wire_shape):
    def names(value):
        if isinstance(value, list):
            return [names(item) for item in value]
        if not isinstance(value, dict):
            return value
        aliases = {
            "audioCursors": "audio_cursors", "finalIndex": "final_index",
            "channelTag": "channel_tag", "startTimeMs": "start_time_ms",
            "endTimeMs": "end_time_ms", "languageCode": "language_code",
            "finalRefinement": "final_refinement", "normalizedText": "normalized_text",
        }
        return {(aliases.get(key, key) if snake_case else key): names(item) for key, item in value.items()}

    final = {"result": names({
        "audioCursors": {"finalIndex": "0"},
        "channelTag": "legacy-root",
        "final": {"channelTag": "0", "alternatives": [{
            "text": "Тест", "words": [{"text": "Тест", "startTimeMs": "0", "endTimeMs": "450"}],
            "languages": [{"languageCode": "ru-RU", "probability": "9.9e-1"}],
        }]},
    })}
    refined = {"result": names({"finalRefinement": {
        "finalIndex": "0", "normalizedText": {"channelTag": "0", "alternatives": [{
            "text": "Тест.", "words": [{"text": "Тест.", "startTimeMs": "0", "endTimeMs": "500"}],
            "languages": [{"languageCode": "ru-RU", "probability": "0.99"}],
        }]},
    }})}
    events = [final, refined] if wire_shape != "single" else [final]
    if wire_shape == "ndjson":
        response = httpx.Response(200, text="\n".join(json.dumps(event) for event in events))
    else:
        payload = final if wire_shape == "single" else (events if wire_shape == "array" else {"streamingResponses": events})
        response = httpx.Response(200, json=payload)
    result = normalize_yandex_transcript_response(_decode_streaming_json(response))
    assert result.text == ("Тест" if wire_shape == "single" else "Тест.")
    assert result.word_count == 1  # Refinement replaces, never duplicates, its final.
    assert result.words[0].start == 0
    assert result.words[0].end == (0.45 if wire_shape == "single" else 0.5)
    assert result.words[0].speaker_id == "0"  # Nested tag beats legacy root.
    assert result.detected_language_code == "ru-RU"
    assert result.language_probability == 0.99


def test_yandex_refinement_retains_previous_channel_when_not_repeated():
    result = normalize_yandex_transcript_response([
        {"final": {"channelTag": 0, "alternatives": [{"text": "Первый"}]}, "audioCursors": {"finalIndex": "0"}},
        {"final": {"channelTag": "1", "alternatives": [{"text": "Второй", "words": [{"text": "Второй"}]}]}, "audioCursors": {"finalIndex": "1"}},
        {"finalRefinement": {"finalIndex": "0", "normalizedText": {"alternatives": [{"text": "Первый.", "words": [{"text": "Первый.", "startTimeMs": "0", "endTimeMs": "500"}]}]}}},
    ])
    assert result.text == "Первый. Второй"
    assert [word.speaker_id for word in result.words] == ["0", "1"]
    assert result.words[1].start is None  # No invented timing for absent fields.


@pytest.mark.parametrize("invalid", [-1, "-1", True, False, 1.5, "1.5", "NaN", float("nan"), float("inf"), "9" * 20, 2**63, {}, ""])
@pytest.mark.parametrize("refinement", [False, True])
def test_yandex_invalid_final_index_is_normalized_provider_error(invalid, refinement):
    alternative = {"alternatives": [{"text": "Тест"}]}
    event = ({"finalRefinement": {"finalIndex": invalid, "normalizedText": alternative}}
             if refinement else {"audioCursors": {"finalIndex": invalid}, "final": alternative})
    with pytest.raises(ElevenLabsTranscriptionError) as failure:
        normalize_yandex_transcript_response(event)
    assert failure.value.reason is ElevenLabsTranscriptionReason.malformed_provider_response


@pytest.mark.parametrize("field,invalid", [
    ("startTimeMs", "-1"), ("endTimeMs", "NaN"), ("startTimeMs", True),
    ("startTimeMs", float("nan")), ("endTimeMs", float("inf")),
    ("endTimeMs", 2**63), ("startTimeMs", "9" * 20), ("startTimeMs", "1.5"),
])
def test_yandex_invalid_word_timing_does_not_silently_disappear(field, invalid):
    word = {"text": "Тест", "startTimeMs": "0", "endTimeMs": "500", field: invalid}
    with pytest.raises(ElevenLabsTranscriptionError) as failure:
        normalize_yandex_transcript_response({"final": {"alternatives": [{"text": "Тест", "words": [word]}]}})
    assert failure.value.reason is ElevenLabsTranscriptionReason.malformed_provider_response


@pytest.mark.parametrize("invalid", ["NaN", "Infinity", "1.1", "-0.1", True, float("nan"), float("inf"), {}, "1e999"])
def test_yandex_invalid_language_probability_is_normalized_provider_error(invalid):
    with pytest.raises(ElevenLabsTranscriptionError) as failure:
        normalize_yandex_transcript_response({"final": {"alternatives": [{
            "text": "Тест", "languages": [{"languageCode": "ru-RU", "probability": invalid}],
        }]}})
    assert failure.value.reason is ElevenLabsTranscriptionReason.malformed_provider_response


def test_yandex_realtime_capability_is_bounded_signed_and_origin_scoped():
    capability = create_yandex_realtime_capability(
        owner_user_id="owner",
        project_id="project",
        credential_id="credential",
        credential_version_id="version",
        folder_id="folder",
        language_code="ru-RU",
        model="general",
        settings=Settings(),
        now_epoch=1_000,
    )
    parsed = urlsplit(capability["websocket_url"])
    token = parse_qs(parsed.query)["capability"][0]
    authority = decode_yandex_realtime_capability(token, settings=Settings(), now_epoch=1_010)

    assert capability["provider"] == "yandex"
    assert parsed.scheme == "wss"
    assert parsed.netloc == "studio.example"
    assert authority.folder_id == "folder"
    assert authority.language_code == "ru-RU"
    with pytest.raises(YandexRealtimeCapabilityError):
        decode_yandex_realtime_capability(token + "x", settings=Settings(), now_epoch=1_010)
    with pytest.raises(YandexRealtimeCapabilityError, match="expired_capability"):
        decode_yandex_realtime_capability(token, settings=Settings(), now_epoch=1_301)


def test_yandex_realtime_wire_options_and_audio_budget_match_documented_limits():
    authority = decode_yandex_realtime_capability(
        parse_qs(
            urlsplit(
                create_yandex_realtime_capability(
                    owner_user_id="owner",
                    project_id="project",
                    credential_id="credential",
                    credential_version_id="version",
                    folder_id="folder",
                    language_code="ru-RU",
                    model="general",
                    settings=Settings(),
                    now_epoch=1_000,
                )["websocket_url"]
            ).query
        )["capability"][0],
        settings=Settings(),
        now_epoch=1_001,
    )
    options = _session_options(authority)
    assert options.recognition_model.model == "general"
    assert options.recognition_model.audio_format.raw_audio.sample_rate_hertz == 16_000
    assert options.recognition_model.audio_format.raw_audio.audio_channel_count == 1
    assert options.recognition_model.audio_processing_type == 1
    assert options.speaker_labeling.speaker_labeling == 2
    assert list(options.recognition_model.language_restriction.language_code) == ["ru-RU"]

    encoded = base64.b64encode(b"a" * MAX_AUDIO_CHUNK_BYTES).decode("ascii")
    assert len(_validated_audio_chunk({"audio_base_64": encoded}, received_bytes=0)) == MAX_AUDIO_CHUNK_BYTES
    with pytest.raises(YandexRealtimeCapabilityError, match="audio_limit_exceeded"):
        _validated_audio_chunk(
            {"audio_base_64": base64.b64encode(b"x").decode("ascii")},
            received_bytes=MAX_SESSION_AUDIO_BYTES,
        )


def test_yandex_realtime_relay_streams_audio_and_committed_text(monkeypatch):
    audio = b"pcm-safe"
    messages = [
        {"audio_base_64": base64.b64encode(audio).decode("ascii")},
        {"commit": True},
    ]
    sent = []
    received_audio = []
    health = []

    class WebSocket:
        headers = {"origin": "https://studio.example"}

        async def accept(self):
            sent.append({"accepted": True})

        async def receive_json(self):
            return messages.pop(0)

        async def send_json(self, payload):
            sent.append(payload)

        async def close(self, *, code):
            sent.append({"closed": code})

    class Call:
        def __init__(self, requests):
            self.requests = requests

        def __aiter__(self):
            return self.responses()

        async def responses(self):
            async for request in self.requests:
                if request.WhichOneof("Event") == "chunk":
                    received_audio.append(request.chunk.data)
            yield StreamingResponse(audio_cursors=AudioCursors(final_index=0), final=AlternativeUpdate(alternatives=[Alternative(text="сырой фрагмент", start_time_ms=100, end_time_ms=1200)]))
            yield StreamingResponse(final_refinement=FinalRefinement(final_index=0, normalized_text=AlternativeUpdate(alternatives=[Alternative(text="Готовый фрагмент")])))

    class Stub:
        def __init__(self, _channel):
            pass

        def RecognizeStreaming(self, requests, **_kwargs):
            return Call(requests)

    class Channel:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    authority = SimpleNamespace(
        folder_id="folder-safe",
        language_code="ru-RU",
        model="general",
    )
    settings = SimpleNamespace(
        app_origin="https://studio.example",
        yandex_stt_grpc_endpoint="stt.api.cloud.yandex.net:443",
    )
    monkeypatch.setattr(
        realtime_relay,
        "decode_yandex_realtime_capability",
        lambda *_args, **_kwargs: authority,
    )
    monkeypatch.setattr(
        realtime_relay,
        "_open_api_key",
        lambda *_args, **_kwargs: "api-key-safe",
    )
    monkeypatch.setattr(realtime_relay, "consume_yandex_realtime_capability", lambda *a, **k: None)
    monkeypatch.setattr(realtime_relay, "RecognizerStub", Stub)
    monkeypatch.setattr(
        realtime_relay.grpc.aio,
        "secure_channel",
        lambda *_args, **_kwargs: Channel(),
    )
    monkeypatch.setattr(
        realtime_relay,
        "_record_realtime_provider_health",
        lambda **kwargs: health.append(kwargs),
    )

    asyncio.run(
        relay_yandex_realtime(
            WebSocket(),
            capability="signed-capability",
            settings=settings,
        )
    )

    assert received_audio == [audio]
    assert {"message_type": "session_started"} in sent
    assert {
        "message_type": "committed_transcript",
        "text": "Готовый фрагмент",
        "final_index": 0,
        "start_seconds": 0.1,
        "end_seconds": 1.2,
    } in sent
    assert [item["final_index"] for item in sent if item.get("message_type") == "committed_transcript"] == [0, 0]
    assert health == [{"settings": settings, "failure_code": None}]
    assert sent[-1] == {"closed": 1000}


def test_realtime_events_keep_delayed_refinement_identity_and_real_timing():
    events = YandexRealtimeEvents()
    def final(index, text, start, end):
        message = StreamingResponse(audio_cursors=AudioCursors(final_index=index), final=AlternativeUpdate(alternatives=[Alternative(text=text, start_time_ms=start, end_time_ms=end)]))
        # Test the checked-in descriptor's actual wire decoding, not a mock field.
        return StreamingResponse.FromString(message.SerializeToString())
    assert events.event(final(0, "первая", 100, 200))["final_index"] == 0
    assert events.event(final(1, "вторая", 400, 800))["final_index"] == 1
    correction = StreamingResponse(final_refinement=FinalRefinement(final_index=0, normalized_text=AlternativeUpdate(alternatives=[Alternative(text="Первая.")])))
    assert events.event(correction) == {"message_type": "committed_transcript", "text": "Первая.", "final_index": 0, "start_seconds": 0.1, "end_seconds": 0.2}
    assert events.event(final(0, "старый дубль", 100, 200)) is None
    assert events.event(final(2, "без таймкода", 0, 0)) == {"message_type": "committed_transcript", "text": "без таймкода", "final_index": 2}
    assert events.event(final(3, "некорректный таймкод", -1, 20)) == {"message_type": "committed_transcript", "text": "некорректный таймкод", "final_index": 3}


@pytest.mark.parametrize("kind", ["partial", "final"])
def test_realtime_word_boundaries_allow_the_browser_to_clear_only_preceding_audio(kind):
    from studio_api.yandex_realtime_pb2 import Word
    alternative = Alternative(text="до после", start_time_ms=100, end_time_ms=2200,
        words=[Word(text="до",start_time_ms=100,end_time_ms=600),Word(text="после",start_time_ms=1600,end_time_ms=2200)])
    response = StreamingResponse(**{kind:AlternativeUpdate(alternatives=[alternative])})
    payload = YandexRealtimeEvents().event(StreamingResponse.FromString(response.SerializeToString()))
    assert payload["words"] == [{"text":"до","start":0.1,"end":0.6,"type":"word"},
        {"text":"после","start":1.6,"end":2.2,"type":"word"}]
    assert payload["text"] == "до после"


def test_realtime_finals_without_cursor_do_not_share_an_invented_zero_identity():
    events = YandexRealtimeEvents()
    for text in ("первый фрагмент", "другой фрагмент"):
        message = StreamingResponse(final=AlternativeUpdate(alternatives=[Alternative(text=text)]))
        decoded = StreamingResponse.FromString(message.SerializeToString())
        assert events.event(decoded) == {"message_type": "committed_transcript", "text": text}
    assert not events.finals


@pytest.mark.parametrize("mode,model,diarize", [("standard", "general", True), ("economic", "deferred-general", False)])
def test_yandex_async_operation_is_durable_before_poll_and_completed_result_resumes_without_resubmit(mode, model, diarize):
    db = _YandexDb()
    db.job.operating_mode = mode
    client = _YandexClient(db)
    settings = SimpleNamespace(
        yandex_stt_api_base_url="https://stt.api.cloud.yandex.net",
        yandex_operations_api_base_url="https://operation.api.cloud.yandex.net",
        yandex_operation_timeout_seconds=30,
        yandex_operation_poll_interval_seconds=0,
        credential_key_id="studio-v1",
        master_key_b64=lambda: base64.urlsafe_b64encode(b"k" * 32).decode("ascii"),
    )
    transport = YandexTranscriptionTransport(
        db=db,
        job_id="job",
        job_source_id="job-source",
        settings=settings,
        folder_id="folder-safe",
        clock=lambda: datetime.now(timezone.utc),
        client=client,
        sleeper=lambda _seconds: None,
    )

    result = transport.transcribe(
        api_key="api-key-safe",
        stream=io.BytesIO(b"ogg-opus"),
        filename="source.ogg",
        mime_type="audio/ogg",
        language_code="ru",
        diarize=diarize,
        model_id=model,
    )

    assert result.text == "Проверка завершена"
    assert result.words[0].start == 0
    assert result.words[1].end == 0.8
    assert {word.speaker_id for word in result.words} == {"0"}
    assert db.operation.status == "completed"
    assert db.operation.result_ciphertext
    assert [call[0] for call in client.calls] == ["POST", "GET", "GET"]
    submitted = client.calls[0][2]["json"]
    assert submitted["recognitionModel"]["audioProcessingType"] == "FULL_DATA"
    assert submitted["recognitionModel"]["model"] == model
    assert ("speakerLabeling" in submitted) is diarize

    db.job.attempt_count = 2
    no_network_client = _YandexClient(db)
    resumed = YandexTranscriptionTransport(
        db=db,
        job_id="job",
        job_source_id="job-source",
        settings=settings,
        folder_id="folder-safe",
        clock=lambda: datetime.now(timezone.utc),
        client=no_network_client,
    ).transcribe(
        api_key="api-key-safe",
        stream=io.BytesIO(b"unused"),
        filename="source.ogg",
        mime_type="audio/ogg",
        language_code="ru",
        model_id=model,
    )

    assert resumed.text == result.text
    assert [(word.start, word.end, word.speaker_id) for word in resumed.words] == [
        (word.start, word.end, word.speaker_id) for word in result.words
    ]
    assert no_network_client.calls == []

    db.operation.status = "failed"
    db.operation.attempt_number = db.job.attempt_count
    rejected_client = _YandexClient(db)
    with pytest.raises(ElevenLabsTranscriptionError) as rejected:
        YandexTranscriptionTransport(
            db=db,
            job_id="job",
            job_source_id="job-source",
            settings=settings,
            folder_id="folder-safe",
            clock=lambda: datetime.now(timezone.utc),
            client=rejected_client,
        ).transcribe(
            api_key="api-key-safe",
            stream=io.BytesIO(b"unused"),
            filename="source.ogg",
            mime_type="audio/ogg",
            language_code="ru",
            model_id=model,
        )
    assert rejected.value.reason is ElevenLabsTranscriptionReason.provider_request_rejected
    assert rejected_client.calls == []
