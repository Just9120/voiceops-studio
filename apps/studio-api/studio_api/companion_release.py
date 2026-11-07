"""Closed distribution of a verified, operator-staged Windows build."""
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

from fastapi import HTTPException

INSTALLER = "VoiceOpsCompanion-Setup.exe"
MAX_INSTALLER_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class CompanionRelease:
    version: str
    source_commit: str
    sha256: str
    size: int
    path: Path

    def metadata(self):
        return {"version": self.version, "source_commit": self.source_commit,
                "sha256": self.sha256, "bytes": self.size, "signed": False}


def _stamp(path):
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@lru_cache(maxsize=4)
def _verified_sha256(path, stamp):
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return digest if _stamp(path) == stamp else None


def available_release(settings, owner_id):
    not_found = HTTPException(404, "Установщик пока недоступен", headers={"Cache-Control": "no-store"})
    sha = settings.companion_release_sha256
    if (not settings.companion_release_owner_id or owner_id != str(settings.companion_release_owner_id)
            or not sha or not re.fullmatch(r"[0-9a-f]{64}", sha)):
        raise not_found
    # Each enabled artifact has its own read-only directory. The browser can
    # request only the configured build and never supplies a filesystem path.
    directory = Path(settings.companion_release_directory) / sha
    manifest, path = directory / "installer.json", directory / INSTALLER
    try:
        if directory.is_symlink() or manifest.is_symlink() or path.is_symlink():
            raise ValueError()
        with manifest.open("rb") as stream:
            data = json.loads(stream.read(4097))
        if (not isinstance(data, dict) or data.get("file") != INSTALLER
                or data.get("source_dirty") is not False or data.get("smoke") is not False
                or data.get("sha256") != sha or not re.fullmatch(r"[0-9a-f]{40}", str(data.get("source_commit")))
                or not re.fullmatch(r"[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}", str(data.get("version")))
                or type(data.get("bytes")) is not int or not 0 < data["bytes"] <= MAX_INSTALLER_BYTES
                or not path.is_file()):
            raise ValueError()
        stamp = _stamp(path)
        if stamp[2] != data["bytes"] or _verified_sha256(path, stamp) != sha:
            raise ValueError()
        return CompanionRelease(data["version"], data["source_commit"], sha, data["bytes"], path)
    except (OSError, ValueError, TypeError):
        raise not_found from None
