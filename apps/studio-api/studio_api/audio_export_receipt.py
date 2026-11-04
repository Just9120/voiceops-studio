"""Small immutable content receipt for an accepted audio export."""
import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AudioExportReceipt:
    file_id: str
    size_bytes: int
    sha256: str
    revision_id: str | None

    def __post_init__(self):
        if (not isinstance(self.file_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", self.file_id) is None
                or type(self.size_bytes) is not int or not 0 < self.size_bytes <= 2**63 - 1
                or not isinstance(self.sha256, str) or re.fullmatch(r"[a-f0-9]{64}", self.sha256) is None
                or (self.revision_id is not None and (not isinstance(self.revision_id, str)
                    or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", self.revision_id) is None))):
            raise ValueError("audio_export_receipt_invalid")

    def metadata_state(self, metadata):
        if metadata.id != self.file_id or metadata.size_bytes != self.size_bytes:
            return "changed"
        sha256 = getattr(metadata, "sha256_checksum", None)
        if sha256 is not None:
            return "matches" if sha256 == self.sha256 else "changed"
        revision = getattr(metadata, "head_revision_id", None)
        if revision is not None and self.revision_id is not None:
            return "matches" if revision == self.revision_id else "changed"
        return "unverified"

    def serialize(self):
        return json.dumps({"version": 1, "file_id": self.file_id, "size_bytes": self.size_bytes,
            "sha256": self.sha256, "revision_id": self.revision_id}, separators=(",", ":"))

    @classmethod
    def parse(cls, value):
        try:
            if not isinstance(value, str) or not 0 < len(value) <= 2048:
                raise ValueError()
            payload = json.loads(value)
            if (not isinstance(payload, dict) or set(payload) != {"version", "file_id", "size_bytes", "sha256", "revision_id"}
                    or type(payload["version"]) is not int or payload.pop("version") != 1):
                raise ValueError()
            return cls(**payload)
        except (ValueError, TypeError, KeyError, RecursionError) as exc:
            raise ValueError("audio_export_receipt_invalid") from exc


def verified_upload_receipt(result):
    """Legacy adapters without content proof never acquire a prepared-map claim."""
    digest = getattr(result, "sha256_checksum", None)
    size = getattr(result, "size_bytes", None)
    if digest is None or size is None:
        return None
    return AudioExportReceipt(result.file_id, size, digest, getattr(result, "head_revision_id", None)).serialize()
