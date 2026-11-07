"""Current-user Windows DPAPI seals the origin, token and executable paths together."""
import base64
import ctypes
import json
import os
from pathlib import Path
import tempfile

from .protocol import MODEL, MODEL_REVISIONS, PARAKEET_MODEL, StudioClient, WorkerError, strict_json

FORMAT = "voiceops-local-worker-v1"
IDENTITY_FORMAT = "voiceops-local-companion-identity-v1"
ENTROPY = b"VoiceOpsStudio.local-worker.profile.v1"


def protect(raw, *, decrypt=False):
    if os.name != "nt":
        raise WorkerError("local_windows_profile_required")
    from ctypes import wintypes as wt
    class Blob(ctypes.Structure):
        _fields_ = [("size", wt.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    def blob(value):
        buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
        return Blob(len(value), buffer), buffer
    incoming, incoming_buffer = blob(raw)
    entropy, entropy_buffer = blob(ENTROPY)
    outgoing = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p,
                        ctypes.c_void_p, wt.DWORD, ctypes.POINTER(Blob)]
    function.restype = wt.BOOL
    try:
        if not function(ctypes.byref(incoming), None, ctypes.byref(entropy), None, None, 1, ctypes.byref(outgoing)):
            raise WorkerError("local_profile_unavailable")
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        ctypes.memset(incoming_buffer, 0, len(raw))
        if outgoing.data:
            ctypes.memset(outgoing.data, 0, outgoing.size)
            kernel.LocalFree(outgoing.data)


def default_profile():
    if os.name != "nt" or not os.environ.get("LOCALAPPDATA"):
        raise WorkerError("local_windows_profile_required")
    return Path(os.environ["LOCALAPPDATA"]) / "VoiceOpsStudio" / "local-worker" / "profile.json"


def read_profile(path, *, unseal=None, identity_only=False):
    unseal = unseal or (lambda value: protect(value, decrypt=True))
    try:
        if Path(path).stat().st_size > 65536:
            raise ValueError()
        outer = strict_json(Path(path).read_bytes())
        expected_format = IDENTITY_FORMAT if identity_only else FORMAT
        if not isinstance(outer, dict) or set(outer) != {"format", "sealed"} or outer["format"] != expected_format:
            raise ValueError()
        raw = unseal(base64.b64decode(outer["sealed"], validate=True))
        if len(raw) > 32768:
            raise ValueError()
        data = strict_json(raw)
        if identity_only:
            if not isinstance(data, dict) or set(data) != {"origin", "token"}:
                raise ValueError()
            StudioClient(data["origin"], data["token"])
            return data
        fields = {"origin", "token", "paths", "verified_files"}
        if (not isinstance(data, dict) or not fields <= data.keys() <= fields | {"model", "managed_root"}
                or not isinstance(data["verified_files"], dict)):
            raise ValueError()
        model = data.get("model", MODEL)
        if not isinstance(model, str) or model not in MODEL_REVISIONS:
            raise ValueError()
        managed = data.get("managed_root")
        if managed is not None and (not isinstance(managed, str) or not Path(managed).is_absolute()):
            raise ValueError()
        StudioClient(data["origin"], data["token"], model=model)
        if not isinstance(data["paths"], dict) or set(data["paths"]) != {"runtime", "decoder", "encoder", "ffmpeg", "ffprobe"}:
            raise ValueError()
        for key, value in data["paths"].items():
            if key == "encoder" and model == PARAKEET_MODEL and value is None:
                continue
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise ValueError()
        return data
    except (OSError, ValueError, TypeError, KeyError, WorkerError):
        raise WorkerError("local_profile_unavailable") from None


def write_profile(path, data, *, replace=False, seal=None, unseal=None, identity_only=False):
    seal = seal or protect
    path = Path(path)
    previous = None
    if path.exists():
        # Never overwrite an unrelated file or silently replace another pairing.
        read_profile(path, unseal=unseal, identity_only=identity_only)
        if not replace:
            raise WorkerError("local_profile_already_exists")
        previous = path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    if len(raw) > 32768:
        raise WorkerError("local_profile_unavailable")
    outer = json.dumps({"format": IDENTITY_FORMAT if identity_only else FORMAT,
                        "sealed": base64.b64encode(seal(raw)).decode()}, separators=(",", ":")).encode()
    descriptor, temporary = tempfile.mkstemp(prefix=".pairing-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(outer); stream.flush(); os.fsync(stream.fileno())
        if previous is not None:
            if not path.exists() or path.read_bytes() != previous:
                raise WorkerError("local_profile_changed")
            os.replace(temporary, path)
        else:
            try:
                # Windows rename is create-only; POSIX link supplies that same
                # guarantee without rename's replace-existing semantics.
                if os.name == "nt":
                    os.rename(temporary, path)
                else:
                    os.link(temporary, path)
            except FileExistsError:
                raise WorkerError("local_profile_changed") from None
        if read_profile(path, unseal=unseal, identity_only=identity_only) != data:
            raise WorkerError("local_profile_unavailable")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
