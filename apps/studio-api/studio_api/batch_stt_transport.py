"""Common bounded HTTP and redacted errors for independently keyed STT APIs."""
import json
from contextlib import contextmanager

import httpx

from .elevenlabs_transcription import ElevenLabsTranscriptionError as Error, ElevenLabsTranscriptionReason as Reason
from .work_progress import report_work

MAX_RESPONSE_BYTES = 16 * 1024 * 1024


def malformed():
    return Error(Reason.malformed_provider_response)


def require_success(status):
    if 200 <= status < 300: return
    reason = {401: Reason.provider_authentication_rejected, 402: Reason.provider_payment_required,
        403: Reason.provider_scope_rejected, 429: Reason.provider_rate_limited}.get(status)
    if reason is None: reason = Reason.provider_unavailable if status >= 500 else Reason.provider_request_rejected
    raise Error(reason, http_status=status)


class MeasuredStream:
    def __init__(self, stream, check=lambda: None):
        self.stream, self.check = stream, check
        position = stream.tell()
        stream.seek(0, 2)
        self.total = stream.tell()
        stream.seek(position)
    def read(self, size=-1):
        self.check()
        value = self.stream.read(size)
        if value:
            report_work("provider_upload", self.stream.tell(), self.total, "bytes")
        else:
            report_work("provider_wait")
        return value
    def __getattr__(self, name):
        return getattr(self.stream, name)


class BatchHttpTransport:
    timeout = 1800
    def __init__(self, *, client=None, check=lambda: None):
        self.client, self.check = client, check

    @contextmanager
    def connection(self):
        if self.client is not None:
            yield self.client
        else:
            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                yield client

    def request(self, client, method, url, *, json_result=True, **kwargs):
        self.check()
        try:
            with client.stream(method, url, follow_redirects=False, timeout=self.timeout, **kwargs) as response:
                require_success(response.status_code)
                data = bytearray()
                for chunk in response.iter_bytes():
                    self.check()
                    if len(data) + len(chunk) > MAX_RESPONSE_BYTES: raise malformed()
                    data.extend(chunk)
                if not json_result: return dict(response.headers)
                try:
                    payload = json.loads(data)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise malformed() from exc
                if not isinstance(payload, dict): raise malformed()
                return payload
        except httpx.TimeoutException as exc:
            raise Error(Reason.provider_timeout) from exc
        except httpx.HTTPError as exc:
            raise Error(Reason.provider_unavailable) from exc


def same_text(left, right):
    return " ".join(left.split()) == " ".join(right.split())
