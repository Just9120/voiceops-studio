"""The browser approves a request. Its verifier stays in the Windows process."""
from dataclasses import dataclass, field
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.request

from .protocol import APIError, NoRedirect, STUDIO_USER_AGENT, StudioClient, WorkerError, canonical_id, origin, response_bytes, strict_json

ENROLLMENT_PATH = "/api/local-execution/enrollment"
OBS_ENROLLMENT_PATH = "/api/obs-import/enrollment"
STUDIO_ORIGIN = "https://studio.cloud-nodes.net"


def _request(base, path, body, *, obs=False):
    endpoint = OBS_ENROLLMENT_PATH if obs else ENROLLMENT_PATH
    request = urllib.request.Request(base + endpoint + path,
        data=json.dumps(body, separators=(",", ":")).encode(), method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "X-VoiceOps-Local-Protocol": "1", "User-Agent": STUDIO_USER_AGENT})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=12) as reply:
            return strict_json(response_bytes(reply, 8192))
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        raise APIError(status, "local_enrollment_expired" if status == 410 else "local_enrollment_rejected") from None
    except (OSError, urllib.error.URLError):
        raise APIError(0, "local_enrollment_unavailable") from None


@dataclass(frozen=True)
class EnrollmentAttempt:
    base: str
    request_id: str
    expires_at: float
    verifier: str = field(repr=False)
    obs: bool = False

    @property
    def browser_url(self):
        flow = "obs" if self.obs else "local"
        return f"{self.base}/settings/connections#{flow}-enrollment={self.request_id}"

    def finish(self):
        if time.monotonic() >= self.expires_at:
            raise WorkerError("local_enrollment_expired")
        reply = _request(self.base, f"/{self.request_id}/finish", {"verifier": self.verifier}, obs=self.obs)
        if reply == {"status": "pending"}:
            return None
        device = reply.get("device") if isinstance(reply, dict) else None
        if not isinstance(device, dict) or reply.get("status") != "connected" or device.get("id") != self.request_id:
            raise WorkerError("local_response_invalid")
        if self.obs:
            return {"origin": self.base, "token": f"vs-obs.{self.request_id}.{self.verifier}"}
        client = StudioClient(self.base, f"vs-local.{self.request_id}.{self.verifier}")
        return {"origin": client.base, "token": client.token}


def begin_enrollment(label, *, studio_origin=STUDIO_ORIGIN, obs=False):
    base = origin(studio_origin)
    verifier = secrets.token_urlsafe(32)
    payload = {"label": label, "challenge": hashlib.sha256(verifier.encode("ascii")).hexdigest()}
    reply = _request(base, "", payload, obs=obs)
    if not isinstance(reply, dict) or not canonical_id(reply.get("request_id")) or type(reply.get("expires_in")) is not int or not 1 <= reply["expires_in"] <= 300:
        raise WorkerError("local_response_invalid")
    return EnrollmentAttempt(base, reply["request_id"], time.monotonic() + reply["expires_in"], verifier, obs)
