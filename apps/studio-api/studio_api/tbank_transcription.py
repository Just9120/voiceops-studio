import base64
import hashlib
import hmac
import json
import time
import uuid

from .batch_stt_transport import BatchHttpTransport, malformed
from .elevenlabs_transcription import normalize_elevenlabs_transcript_response, ElevenLabsTranscriptionError, ElevenLabsTranscriptionReason
from .work_progress import report_work


def credential_pair(raw):
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {"api_key", "secret_key"}: raise ValueError()
        api_key, secret = value["api_key"], value["secret_key"]
        if not isinstance(api_key, str) or not 1 <= len(api_key) <= 256 or not api_key.isascii() or any(c.isspace() or ord(c) < 32 for c in api_key): raise ValueError()
        if not isinstance(secret, str) or len(secret) > 512: raise ValueError()
        key = base64.b64decode(secret + "=" * (-len(secret) % 4), altchars=b"-_", validate=True)
        if not 16 <= len(key) <= 256: raise ValueError()
        return api_key, key
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("Укажите JSON с полями api_key и secret_key для VoiceKit. Секретный ключ должен быть в Base64.") from exc


def voicekit_token(raw, *, clock=time.time):
    try:
        api_key, key = credential_pair(raw)
    except ValueError as exc:
        raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.provider_authentication_rejected) from exc
    now = int(clock())
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=")
    header = encode({"alg": "HS256", "typ": "JWT", "kid": api_key})
    payload = encode({"iss": "voiceops-studio", "sub": "voiceops-user", "aud": "tinkoff.cloud.stt",
        "iat": now, "nbf": now - 5, "exp": now + 300, "jti": str(uuid.uuid4())})
    signed = header + b"." + payload
    return (signed + b"." + base64.urlsafe_b64encode(hmac.new(key, signed, hashlib.sha256).digest()).rstrip(b"=")).decode("ascii")


def normalize_tbank_response(payload):
    results = payload.get("results")
    if not isinstance(results, list) or not results or len(results) > 100000: raise malformed()
    phrases = []
    for result in results:
        if not isinstance(result, dict): raise malformed()
        alternatives = result.get("alternatives")
        if not isinstance(alternatives, list) or not alternatives or not isinstance(alternatives[0], dict): raise malformed()
        text = alternatives[0].get("transcript")
        if not isinstance(text, str) or not text.strip(): raise malformed()
        phrases.append(text.strip())
    return normalize_elevenlabs_transcript_response({"text": " ".join(phrases), "language_code": "ru"})


class TbankTranscriptionTransport(BatchHttpTransport):
    def transcribe(self, *, api_key, stream, filename, mime_type, language_code=None, diarize=False, keyterms=(), model_id="default"):
        if diarize or language_code not in {None, "ru"}: raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.provider_request_rejected)
        stream.seek(0)
        content = stream.read(24 * 1024 * 1024 + 1)
        if not content or len(content) > 24 * 1024 * 1024: raise malformed()
        config = {"encoding": "MPEG_AUDIO", "sampleRateHertz": 16000, "numChannels": 1,
            "enableAutomaticPunctuation": True, "enableDenormalization": True, "profanityFilter": False, "maxAlternatives": 1}
        if keyterms: config["speechContexts"] = [{"phrases": [{"text": term, "score": 1} for term in keyterms]}]
        body = json.dumps({"config": config, "audio": {"content": base64.b64encode(content).decode("ascii")}}, separators=(",", ":")).encode()
        def upload():
            sent = 0
            for offset in range(0, len(body), 1024 * 1024):
                self.check()
                chunk = body[offset:offset + 1024 * 1024]
                sent += len(chunk)
                report_work("provider_upload", sent, len(body), "bytes")
                yield chunk
            report_work("provider_wait")
        with self.connection() as client:
            response = self.request(client, "POST", "https://api.tbank.ru/v1/stt:recognize",
                headers={"Authorization": "Bearer " + voicekit_token(api_key), "Content-Type": "application/json", "Content-Length": str(len(body))}, content=upload())
        return normalize_tbank_response(response)
