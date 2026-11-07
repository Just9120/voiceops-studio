"""Short-lived browser approval for a Windows instance that owns a verifier."""
import hashlib
import hmac
import json
from uuid import uuid4

from fastapi import HTTPException

PAIRING_SECONDS = 300


class DeviceEnrollment:
    def __init__(self, redis):
        self.redis = redis

    @staticmethod
    def request_key(request_id):
        return "local-device:enrollment:" + str(request_id)

    @staticmethod
    def approval_key(request_id):
        return "local-device:approval:" + str(request_id)

    def begin(self, label, challenge):
        request_id = str(uuid4())
        if not self.redis.set(self.request_key(request_id),
                              json.dumps({"label": label, "challenge": challenge}),
                              ex=PAIRING_SECONDS, nx=True):
            raise HTTPException(503, detail={"reason": "local_enrollment_unavailable"})
        return request_id

    def request(self, request_id):
        value = self.redis.get(self.request_key(request_id))
        if value is None:
            raise HTTPException(410, detail={"reason": "local_enrollment_expired"})
        return json.loads(value)

    def browser_view(self, request_id, user_id):
        pending = self.request(request_id)
        owner = self.redis.get(self.approval_key(request_id))
        if owner is not None and owner != user_id:
            raise HTTPException(404, "Не найдено")
        return {"label": pending["label"], "approved": owner is not None}

    def approve(self, request_id, user_id):
        self.request(request_id)
        ttl = self.redis.ttl(self.request_key(request_id))
        if ttl <= 0:
            raise HTTPException(410, detail={"reason": "local_enrollment_expired"})
        self.redis.set(self.approval_key(request_id), user_id, ex=ttl, nx=True)
        return self.browser_view(request_id, user_id)

    def verify(self, request_id, verifier):
        pending = self.request(request_id)
        challenge = hashlib.sha256(verifier.encode("ascii")).hexdigest()
        if not hmac.compare_digest(challenge, pending["challenge"]):
            raise HTTPException(403, detail={"reason": "local_enrollment_invalid_proof"})
        return pending["label"], self.redis.get(self.approval_key(request_id))
