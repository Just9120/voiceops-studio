"""Dedicated Gemini Transcribe, verbatim only; no generative rewriting."""
import re
import time
from urllib.parse import urlsplit
from sqlalchemy import select

from .batch_stt_transport import BatchHttpTransport, malformed, same_text
from .elevenlabs_transcription import normalize_elevenlabs_transcript_response, ElevenLabsTranscriptionError, ElevenLabsTranscriptionReason
from .models import SttProviderOperation, TranscriptionJob, ProviderCredentialVersion
from .security import fingerprint
from .provider_result_cache import persist_operation_result
from .work_progress import report_work

BASE = "https://generativelanguage.googleapis.com"
FILE_NAME = re.compile(r"files/[A-Za-z0-9_-]{1,120}\Z")


def _seconds(value):
    if value is None: return None
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d{1,9})?s", value): raise malformed()
    return float(value[:-1])


def normalize_gemini_response(payload, *, diarize=False):
    if payload.get("status") != "completed": raise malformed()
    steps = payload.get("steps")
    if not isinstance(steps, list) or len(steps) > 10000: raise malformed()
    texts, annotations = [], []
    for step in steps:
        if not isinstance(step, dict): raise malformed()
        if step.get("type") != "model_output": continue
        content = step.get("content")
        if not isinstance(content, list): raise malformed()
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text" or not isinstance(item.get("text"), str): raise malformed()
            texts.append(item["text"])
            info = item.get("annotations", [])
            if not isinstance(info, list): raise malformed()
            annotations.extend(info)
    text = "".join(texts)
    if not text.strip() or len(annotations) > 200000: raise malformed()
    if payload.get("output_text") is not None and (not isinstance(payload["output_text"], str) or not same_text(text, payload["output_text"])): raise malformed()
    words, cursor = [], 0
    for item in annotations:
        if not isinstance(item, dict): raise malformed()
        if item.get("type") != "word_info": continue
        token = item.get("text")
        if not isinstance(token, str) or not token: raise malformed()
        position = text.find(token, cursor)
        if position < 0 or any(c.isalnum() for c in text[cursor:position]): raise malformed()
        speaker = item.get("speaker")
        if diarize and (not isinstance(speaker, str) or not speaker.strip()): raise malformed()
        words.append(dict(text=text[cursor:position + len(token)], start=_seconds(item.get("start_offset")),
            end=_seconds(item.get("end_offset")), speaker_id=speaker, type="word"))
        cursor = position + len(token)
    if words:
        if any(c.isalnum() for c in text[cursor:]): raise malformed()
        words[-1]["text"] += text[cursor:]
    if diarize and not words: raise malformed()
    return normalize_elevenlabs_transcript_response({"text": text, "words": words})


class GeminiTranscriptionTransport(BatchHttpTransport):
    def __init__(self, *, db, job_id, job_source_id, settings, clock, client=None, check=lambda: None, sleeper=time.sleep):
        super().__init__(client=client, check=check)
        self.db, self.job_id, self.job_source_id, self.settings, self.clock = db, job_id, job_source_id, settings, clock
        self.sleeper = sleeper

    def _register_file(self, name, model, api_key):
        job = self.db.get(TranscriptionJob, self.job_id)
        self.check()
        version_id = self.db.scalar(select(ProviderCredentialVersion.id).where(
            ProviderCredentialVersion.credential_id == job.provider_credential_id,
            ProviderCredentialVersion.fingerprint == fingerprint(api_key)).order_by(ProviderCredentialVersion.version.desc()).limit(1))
        if version_id is None: raise malformed()
        operation = SttProviderOperation(owner_user_id=job.owner_user_id, project_id=job.project_id,
            job_id=job.id, job_source_id=self.job_source_id, attempt_number=max(1, job.attempt_count or 1),
            provider="gemini", operating_mode=job.operating_mode, model=model, operation_id=name,
            external_file_id=name, external_file_credential_version_id=version_id, status="pending", submitted_at=self.clock())
        self.db.add(operation)
        self.db.commit()
        return operation

    def transcribe(self, *, api_key, stream, filename, mime_type, language_code=None, diarize=False, keyterms=(), model_id="gemini-3.5-transcribe"):
        if diarize and keyterms: raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.provider_request_rejected)
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(0)
        if not 0 < size <= 256 * 1024 * 1024: raise malformed()
        headers = {"x-goog-api-key": api_key}
        with self.connection() as client:
            report_work("provider_upload", 0, size, "bytes")
            upload = self.request(client, "POST", BASE + "/upload/v1beta/files", json_result=False,
                headers={**headers, "X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
                    "X-Goog-Upload-Header-Content-Length": str(size), "X-Goog-Upload-Header-Content-Type": mime_type},
                json={"file": {"display_name": "VoiceOps temporary transcription input"}})
            url = upload.get("x-goog-upload-url", "")
            try:
                parsed = urlsplit(url)
                trusted = (parsed.scheme == "https" and parsed.hostname == "generativelanguage.googleapis.com"
                    and not parsed.username and not parsed.password and parsed.port is None
                    and parsed.path.startswith("/upload/") and not parsed.fragment)
            except (ValueError, TypeError):
                trusted = False
            if not trusted: raise malformed()
            def content():
                sent = 0
                while chunk := stream.read(1024 * 1024):
                    self.check()
                    sent += len(chunk)
                    report_work("provider_upload", sent, size, "bytes")
                    yield chunk
                report_work("provider_wait")
            resource = self.request(client, "POST", url,
                headers={**headers, "Content-Length": str(size), "X-Goog-Upload-Offset": "0", "X-Goog-Upload-Command": "upload, finalize"}, content=content()).get("file")
            if not isinstance(resource, dict) or not isinstance(resource.get("name"), str) or not FILE_NAME.fullmatch(resource["name"]): raise malformed()
            name, operation = resource["name"], None
            try:
                operation = self._register_file(name, model_id, api_key)
                deadline = time.monotonic() + 120
                while resource.get("state") == "PROCESSING":
                    if time.monotonic() >= deadline: raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.provider_timeout)
                    self.check()
                    self.sleeper(2)
                    resource = self.request(client, "GET", BASE + "/v1beta/" + name, headers=headers)
                if resource.get("state") != "ACTIVE": raise malformed()
                config = {"mode": {"type": "verbatim"}, "language_codes": [{"ru": "ru-RU", "en": "en-US"}[language_code]] if language_code in {"ru", "en"} else []}
                if diarize: config["mode"]["diarization_mode"] = "speaker"
                if keyterms: config["custom_vocabulary"] = list(keyterms)
                report_work("provider_wait")
                response = self.request(client, "POST", BASE + "/v1beta/interactions", headers=headers,
                    json={"model": model_id, "store": False, "input": [{"type": "audio", "uri": BASE + "/v1beta/" + name, "mime_type": mime_type}],
                          "generation_config": {"transcription_config": config}})
                result = normalize_gemini_response(response, diarize=diarize)
                try:
                    persist_operation_result(self.db, operation, result, settings=self.settings, now=self.clock())
                except Exception:
                    result.revoke()
                    raise
                return result
            finally:
                # Cleanup is still allowed after cancellation, for this exact
                # confirmed file only. The API key never goes to a returned host.
                try:
                    BatchHttpTransport(client=client).request(client, "DELETE", BASE + "/v1beta/" + name,
                        headers=headers, json_result=False)
                    if operation is not None:
                        operation.external_file_deleted_at = self.clock()
                        self.db.commit()
                except Exception:
                    self.db.rollback()
                    # The durable receipt remains pending for operator recovery;
                    # provider Files expiry is a fallback, never a cleanup PASS.
                    if operation is not None:
                        from .diagnostics import write_diagnostic_event
                        try:
                            write_diagnostic_event(owner_user_id=operation.owner_user_id, component="worker",
                                event_code="PROVIDER_TEMPORARY_FILE_CLEANUP_PENDING", job_id=self.job_id,
                                metadata={"provider": "gemini"})
                        except Exception:
                            # The durable receipt is the recovery authority;
                            # optional diagnostics cannot discard a paid result.
                            pass
