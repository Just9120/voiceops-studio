from .batch_stt_transport import BatchHttpTransport, MeasuredStream, malformed, same_text
from .elevenlabs_transcription import normalize_elevenlabs_transcript_response
from .work_progress import report_work


def normalize_mistral_response(payload, *, diarize=False):
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip() or payload.get("finish_reason") not in (None, "stop"):
        raise malformed()
    segments = payload.get("segments", [])
    if not isinstance(segments, list) or len(segments) > 100000: raise malformed()
    words = []
    for segment in segments:
        if not isinstance(segment, dict) or not isinstance(segment.get("text"), str): raise malformed()
        if diarize and (not isinstance(segment.get("speaker_id"), str) or not segment["speaker_id"].strip()): raise malformed()
        words.append(dict(text=segment["text"], start=segment.get("start"), end=segment.get("end"),
            speaker_id=segment.get("speaker_id"), type="word"))
    if diarize and (not words or not same_text("".join(w["text"] for w in words), text)): raise malformed()
    return normalize_elevenlabs_transcript_response({"text": text, "words": words, "language_code": payload.get("language")})


class MistralTranscriptionTransport(BatchHttpTransport):
    def transcribe(self, *, api_key, stream, filename, mime_type, language_code=None, diarize=False, keyterms=(), model_id="voxtral-small-transcribe-3"):
        stream.seek(0)
        measured = MeasuredStream(stream, self.check)
        if measured.total > 256 * 1024 * 1024: raise malformed()
        data = {"model": model_id, "diarize": str(diarize).lower(), "timestamp_granularities": "segment"}
        if language_code: data["language"] = language_code
        if keyterms: data["context_bias"] = list(keyterms)
        report_work("provider_upload", 0, measured.total, "bytes")
        with self.connection() as client:
            payload = self.request(client, "POST", "https://api.mistral.ai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"}, data=data, files={"file": (filename, measured, mime_type)})
        return normalize_mistral_response(payload, diarize=diarize)
