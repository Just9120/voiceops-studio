"""Read a completed OBS recording and prepare one local audio-only import."""
import base64
from dataclasses import dataclass
import hashlib
import http.client
import json
from pathlib import Path
import re
import stat
import urllib.error
import urllib.parse
import urllib.request

from .enrollment import STUDIO_ORIGIN
from .process import OwnedProcess, owned_scratch
from .profile import read_profile
from .protocol import APIError, NoRedirect, STUDIO_USER_AGENT, WorkerError, response_bytes, strict_json


_EVENT_ID = re.compile(r"[0-9a-f]{32}")
_VIDEO_FORMATS = frozenset({".mkv", ".mp4", ".mov", ".m4v", ".webm", ".flv", ".ts", ".avi"})
_MAX_AUDIO_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class Recording:
    event_id: str
    path: Path
    track: int
    started_at: int


def read_recording(queue: Path, event_id: str) -> Recording:
    if not _EVENT_ID.fullmatch(event_id):
        raise WorkerError("obs_import_event_invalid")
    entry = queue / f"{event_id}.pending"
    try:
        info = entry.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 16 * 1024:
            raise ValueError()
        version, track_text, started_text, value = entry.read_text(encoding="utf-8").splitlines()
        track, started_at = int(track_text), int(started_text)
        path = Path(value)
        if (version != "voiceops-obs-import-v1" or not 1 <= track <= 6 or started_at < 1
                or not path.is_absolute() or value.startswith(("\\\\", "//"))
                or path.suffix.lower() not in _VIDEO_FORMATS):
            raise ValueError()
        return Recording(event_id, path, track, started_at)
    except (OSError, UnicodeError, ValueError):
        raise WorkerError("obs_import_event_invalid") from None


def _recording_stamp(recording: Recording):
    path = recording.path
    try:
        info = path.lstat()
        reparse_point = getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        if (reparse_point or not stat.S_ISREG(info.st_mode) or not info.st_size
                or info.st_mtime_ns < recording.started_at * 1_000_000_000):
            raise ValueError()
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
    except (OSError, ValueError):
        raise WorkerError("obs_import_recording_unavailable") from None


def import_recording(recording: Recording, ffmpeg: Path, scratch: Path, submit):
    """Submit short-lived FLAC while the caller retains the handoff for retries."""
    stamp = _recording_stamp(recording)
    with owned_scratch(scratch, prefix="obs-") as directory:
        audio = directory / "recording.flac"
        args = [
            str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "error", "-xerror",
            "-protocol_whitelist", "file",
            "-format_whitelist", "matroska,webm,mov,mp4,m4a,3gp,3g2,mj2,flv,mpegts,avi",
            "-i", str(recording.path), "-map", f"0:a:{recording.track - 1}",
            "-vn", "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1",
            "-sample_fmt", "s16", "-ar", "16000", "-ac", "1", "-c:a", "flac",
            "-fs", str(_MAX_AUDIO_BYTES + 65_536), "-f", "flac", str(audio),
        ]
        with OwnedProcess(args, directory=directory, name="extract") as process:
            process.wait(timeout=1800)
        if not audio.is_file() or not 0 < audio.stat().st_size <= _MAX_AUDIO_BYTES:
            raise WorkerError("obs_import_audio_size_invalid")
        if _recording_stamp(recording) != stamp:
            raise WorkerError("obs_import_recording_changed")
        return submit(recording.event_id, recording.path.stem + ".flac", audio)


def submit_recording(identity, event_id, filename, audio):
    if identity["origin"] != STUDIO_ORIGIN or not _EVENT_ID.fullmatch(event_id):
        raise WorkerError("obs_import_identity_invalid")
    opener = urllib.request.build_opener(NoRedirect())
    endpoint = f"{STUDIO_ORIGIN}/api/obs-import/events/{event_id}"
    expected = {"status": "completed", "event_id": event_id}

    def post(action, body):
        request = urllib.request.Request(
            f"{endpoint}/{action}", method="POST", data=json.dumps(body).encode("utf-8") if body else b"",
            headers={
                "Authorization": "Bearer " + identity["token"],
                "Accept": "application/json", "Content-Type": "application/json",
                "X-VoiceOps-Local-Protocol": "1", "User-Agent": STUDIO_USER_AGENT,
            },
        )
        try:
            with opener.open(request, timeout=45) as response:
                return strict_json(response_bytes(response, 16_384))
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            raise APIError(status, "obs_import_request_failed") from None
        except (OSError, http.client.HTTPException):
            raise APIError(0, "obs_import_connection_failed") from None

    md5 = hashlib.md5(usedforsecurity=False)  # The S3 Content-MD5 header verifies receipt of the complete object.
    sha256 = hashlib.sha256()
    with audio.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            md5.update(chunk)
            sha256.update(chunk)
        size = stream.tell()
        checksum = base64.b64encode(md5.digest()).decode("ascii")
        ticket = post("initiate", {"filename": filename, "size_bytes": size, "content_md5": checksum,
                                   "content_sha256": sha256.hexdigest()})
        if ticket == expected:
            return
        expected_headers = {"Content-Type": "audio/flac", "Content-MD5": checksum, "If-None-Match": "*"}
        if (not isinstance(ticket, dict) or ticket.get("status") != "pending" or ticket.get("event_id") != event_id
                or ticket.get("headers") != expected_headers or not isinstance(ticket.get("url"), str)):
            raise WorkerError("obs_import_response_invalid")
        url = ticket["url"]
        try:
            parsed = urllib.parse.urlsplit(url)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                    or parsed.password is not None or parsed.port not in (None, 443)
                    or parsed.fragment or not parsed.query):
                raise ValueError()
        except ValueError:
            raise WorkerError("obs_import_response_invalid") from None
        stream.seek(0)
        request = urllib.request.Request(url, method="PUT", data=stream,
                                         headers={**expected_headers, "Content-Length": str(size)})
        try:
            with opener.open(request, timeout=120) as response:
                if response.status not in {200, 201, 204}:
                    raise WorkerError("obs_import_upload_failed")
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            if status != 412:
                raise APIError(status, "obs_import_upload_failed") from None
        except (OSError, http.client.HTTPException):
            raise APIError(0, "obs_import_upload_failed") from None
    if post("complete", None) != expected:
        raise WorkerError("obs_import_response_invalid")


def process_import(queue: Path, event_id: str, ffmpeg: Path):
    recording = read_recording(queue, event_id)
    identity = read_profile(queue / "identity.json", obs_identity=True)
    import_recording(recording, ffmpeg, queue / "scratch", lambda *args: submit_recording(identity, *args))
    (queue / f"{event_id}.pending").unlink(missing_ok=True)
