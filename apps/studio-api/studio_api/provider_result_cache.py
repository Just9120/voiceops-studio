"""Authenticated local checkpoint for asynchronous or uploaded-file providers."""
import hashlib
import hmac
import json

from .batch_stt_transport import malformed
from .elevenlabs_transcription import normalize_elevenlabs_transcript_response
from .security import aad, encrypt, decrypt, master_key_from_b64


def persist_operation_result(db, operation, result, *, settings, now):
    value = {"text": result.text, "language_code": result.detected_language_code, "language_probability": result.language_probability, "words": [
        dict(text=w.text, start=w.start, end=w.end, type=w.type, speaker_id=w.speaker_id) for w in result.words]}
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    key = master_key_from_b64(settings.master_key_b64())
    boundary = aad(operation.owner_user_id, operation.id, operation.operation_id, f"{operation.provider}-stt-result")
    operation.result_ciphertext, operation.result_nonce = encrypt(payload, key, boundary)
    operation.result_key_id = settings.credential_key_id
    operation.result_hmac = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    operation.status, operation.completed_at, operation.updated_at = "completed", now, now
    db.commit()


def load_operation_result(operation, *, settings):
    if not all((operation.result_ciphertext, operation.result_nonce, operation.result_key_id, operation.result_hmac)):
        raise malformed()
    if operation.result_key_id != settings.credential_key_id: raise malformed()
    key = master_key_from_b64(settings.master_key_b64())
    boundary = aad(operation.owner_user_id, operation.id, operation.operation_id, f"{operation.provider}-stt-result")
    try:
        payload = decrypt(operation.result_ciphertext, operation.result_nonce, key, boundary)
        expected = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, operation.result_hmac): raise malformed()
        return normalize_elevenlabs_transcript_response(json.loads(payload))
    except Exception as exc:
        raise malformed() from exc
