import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from local_worker.obs_import import STUDIO_ORIGIN, import_recording, read_recording, submit_recording
from local_worker.protocol import WorkerError


EVENT_ID = "f" * 32
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def write_event(queue, path, *, track=2, started=None):
    moment = int(time.time()) if started is None else started
    (queue / f"{EVENT_ID}.pending").write_text(f"voiceops-obs-import-v1\n{track}\n{moment}\n{path}\n",
                                                   encoding="utf-8")


def test_reads_only_the_requested_local_recording(tmp_path):
    path = tmp_path / "Запись & синк.mkv"
    write_event(tmp_path, path)
    data = read_recording(tmp_path, EVENT_ID)
    assert data.path == path
    assert data.track == 2
    with pytest.raises(WorkerError, match="obs_import_event_invalid"):
        read_recording(tmp_path, "../pending")
    write_event(tmp_path, "//untrusted.example/share/record.mkv")
    with pytest.raises(WorkerError, match="obs_import_event_invalid"):
        read_recording(tmp_path, EVENT_ID)


def test_retry_after_lost_upload_reply_uses_one_conditional_put_and_keeps_token_in_studio(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from io import BytesIO
    import urllib.request

    audio = tmp_path / "synthetic.flac"
    audio.write_bytes(b"fLaC synthetic contents")
    signed_url = "https://storage.test/synthetic?signature=fake"
    history = []

    class Opener:
        @contextmanager
        def open(self, request, timeout):
            history.append((request.method, request.full_url))
            if request.method == "PUT":
                assert request.full_url == signed_url
                assert request.get_header("Authorization") is None
                assert request.get_header("If-none-match") == "*"
                assert request.get_header("Content-length") == str(audio.stat().st_size)
                assert request.data.read() == audio.read_bytes()
                raise urllib.error.HTTPError(signed_url, 412, "Already stored", None, BytesIO())
            assert request.get_header("Authorization") == "Bearer synthetic"
            if request.full_url.endswith("/initiate"):
                data = json.loads(request.data)
                assert data["content_sha256"] == hashlib.sha256(audio.read_bytes()).hexdigest()
                reply = {
                    "status": "pending", "event_id": EVENT_ID, "url": signed_url,
                    "headers": {"Content-Type": "audio/flac", "Content-MD5": data["content_md5"], "If-None-Match": "*"},
                }
            else:
                reply = {"status": "completed", "event_id": EVENT_ID}
            yield BytesIO(json.dumps(reply).encode())

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: Opener())
    submit_recording({"origin": STUDIO_ORIGIN, "token": "synthetic"}, EVENT_ID, audio.name, audio)
    root = f"{STUDIO_ORIGIN}/api/obs-import/events/{EVENT_ID}"
    assert history == [("POST", root + "/initiate"), ("PUT", signed_url), ("POST", root + "/complete")]


@pytest.mark.skipif(not FFMPEG or not FFPROBE, reason="requires real FFmpeg and FFprobe")
def test_recording_import_extracts_only_the_selected_audio_and_keeps_original(tmp_path):
    def ffmpeg(*args):
        return subprocess.run([FFMPEG, "-nostdin", "-v", "error", *map(str, args)],
                              check=True, capture_output=True, timeout=20).stdout

    started = int(time.time())
    video = tmp_path / "Запись & синк.mkv"
    ffmpeg("-f", "lavfi", "-i", "color=size=64x64:rate=2:duration=1",
           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=1",
           "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=16000:duration=1",
           "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "ffv1", "-c:a", "pcm_s16le",
           "-metadata", "title=Private synthetic title", video)
    initial_digest = hashlib.sha256(video.read_bytes()).digest()
    expected = ffmpeg("-i", video, "-map", "0:a:1", "-f", "s16le", "pipe:1")
    write_event(tmp_path, video, started=started)
    data = read_recording(tmp_path, EVENT_ID)
    calls = []

    def submit(identifier, title, audio):
        calls.append(identifier)
        assert identifier == EVENT_ID
        assert title == "Запись & синк.flac"
        probe = subprocess.run([FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(audio)],
                               capture_output=True, check=True, timeout=10)
        contents = json.loads(probe.stdout)
        assert [stream["codec_type"] for stream in contents["streams"]] == ["audio"]
        assert "title" not in contents["format"].get("tags", {})
        assert ffmpeg("-i", audio, "-f", "s16le", "pipe:1") == expected
        return "draft-123"

    scratch = tmp_path / "scratch"
    assert import_recording(data, Path(FFMPEG), scratch, submit) == "draft-123"
    assert not list(scratch.iterdir())
    assert hashlib.sha256(video.read_bytes()).digest() == initial_digest

    write_event(tmp_path, video, track=3, started=started)
    with pytest.raises(WorkerError, match="local_process_failed"):
        import_recording(read_recording(tmp_path, EVENT_ID), Path(FFMPEG), scratch, submit)
    assert calls == [EVENT_ID]
    assert (tmp_path / f"{EVENT_ID}.pending").exists()
    assert not list(scratch.iterdir())
