"""Pinned CPU NeMo-Speech server, precise FFmpeg preparation and complete output."""
import base64
import http.client
from dataclasses import dataclass
import json
import math
from pathlib import Path
import queue
import secrets
import socket
import threading
import time
import urllib.error
import urllib.request

from .process import OwnedProcess
from .protocol import MODEL, RUNTIME_VERSION, MAX_NATIVE_RESPONSE_BYTES, NoRedirect, WorkerError, complete_native_result, file_sha256, strict_json

RUNTIME_SHA256 = "8d90b48e4ed4f60a7847b86a983dafc183b3448bcf2722777d3209546cb0c1e4"
DECODER_SHA256 = "0c47d4ab6c783e7606ec03714b354fab0b2052027a7ea1991e7e2d3009c345ad"
ENCODER_SHA256 = "4221029c8a565c4a80c507ffa760c716e595acf663f9f4273ce69910050e7ba2"
PINNED_FILES = {"runtime": (1850880, RUNTIME_SHA256), "decoder": (19678656672, DECODER_SHA256),
                "encoder": (1670410080, ENCODER_SHA256)}


@dataclass(frozen=True)
class NativePaths:
    runtime: Path
    decoder: Path
    encoder: Path
    ffmpeg: Path
    ffprobe: Path

    @classmethod
    def from_dict(cls, data):
        try:
            if not isinstance(data, dict) or set(data) != {"runtime", "decoder", "encoder", "ffmpeg", "ffprobe"}:
                raise ValueError()
            return cls(**{key: Path(value).resolve(strict=True) for key, value in data.items()})
        except (OSError, TypeError, ValueError):
            raise WorkerError("local_runtime_missing") from None


def verify_installation(paths, *, check=lambda: None, verified_files=None):
    verified_files = verified_files if isinstance(verified_files, dict) else {}
    verified = {}
    for field, (size, digest) in PINNED_FILES.items():
        path = getattr(paths, field)
        try:
            before = path.stat()
            stamp = [before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns]
            saved = verified_files.get(field)
            # Only a current-user sealed proof can skip rereading unchanged
            # multi-gigabyte weights. The small executable is hashed every run.
            cached = (field != "runtime" and before.st_ino > 0 and isinstance(saved, dict)
                      and saved.get("sha256") == digest and saved.get("stat") == stamp)
            if not path.is_file() or before.st_size != size or (not cached and file_sha256(path, check) != digest):
                raise ValueError()
            after = path.stat()
            if stamp != [after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns]:
                raise ValueError()
            verified[field] = {"sha256": digest, "stat": stamp}
        except (OSError, ValueError):
            raise WorkerError("local_runtime_missing" if field == "runtime" else "local_model_unavailable") from None
    if not paths.ffmpeg.is_file() or not paths.ffprobe.is_file():
        raise WorkerError("local_runtime_missing")
    return verified


def probe_audio(paths, audio, directory, check):
    with OwnedProcess([str(paths.ffprobe), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(audio)],
                      directory=directory, name="probe") as process:
        output = process.wait(check=check, timeout=120)
        if output.stat().st_size > 1024 * 1024:
            raise WorkerError("local_input_unavailable")
        data = strict_json(output.read_bytes())
    try:
        audio_stream = next(stream for stream in data["streams"] if stream.get("codec_type") == "audio")
        value = audio_stream.get("duration", data.get("format", {}).get("duration"))
        if value == "N/A" or value is None:
            value = data.get("format", {}).get("duration")
        duration = float(value)
        if not math.isfinite(duration) or not 0 < duration <= 604800:
            raise ValueError()
        return duration
    except (TypeError, ValueError, KeyError, StopIteration):
        raise WorkerError("local_input_unavailable") from None


def prepare_audio(paths, audio, output, *, start, duration, directory, check, progress):
    if (type(start) not in (int, float) or type(duration) not in (int, float)
            or not 0 <= start <= 604800 or not .02 <= duration <= 3600 or not math.isfinite(start) or not math.isfinite(duration)):
        raise WorkerError("local_input_unavailable")
    args = [str(paths.ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", format(start, ".6f"),
        "-i", str(audio), "-t", format(duration, ".6f"), "-vn", "-map", "0:a:0", "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le", "-progress", "pipe:1", "-nostats", str(output)]
    position = 0
    def measured(path):
        nonlocal position
        with path.open("rb") as stream:
            stream.seek(position)
            lines = stream.readlines()
            position = stream.tell()
        for line in lines:
            if line.startswith(b"out_time_us="):
                try:
                    seconds = max(0, min(duration, int(line.split(b"=", 1)[1]) / 1000000))
                    progress(seconds, duration)
                except ValueError:
                    pass
    with OwnedProcess(args, directory=directory, name="prepare") as process:
        process.wait(check=check, timeout=1800, progress=measured)
        measured(process.stdout_path)
    if not output.is_file() or output.stat().st_size > 115200000 + 1024 * 1024:
        raise WorkerError("local_input_unavailable")
    actual = probe_audio(paths, output, directory, check)
    if abs(actual - duration) > .05:
        raise WorkerError("local_input_unavailable")
    progress(min(actual, duration), duration)
    return actual


class NativeServer:
    def __init__(self, paths, directory):
        self.paths, self.directory = paths, directory
        self.process = None
        self.key = secrets.token_urlsafe(32)
        self.port = None

    def start(self, check=lambda: None):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        args = [str(self.paths.runtime), "serve", "--host", "127.0.0.1", "--port", str(self.port), "--no-ui",
            "--threads", "4", "--max-upload-mb", "192", "--read-timeout", "120", "--write-timeout", "120",
            "--asr-model", str(self.paths.decoder), "--salm-encoder", str(self.paths.encoder),
            "--asr.model.name", MODEL, "--device", "cpu", "--no-warmup", "--asr.backend.threads", "8",
            "--asr.salm.max_sequences", "1", "--asr.salm.n_ctx_per_sequence", "73728", "--asr.salm.max_context", "73728",
            "--asr.salm.mtp_draft", "0", "--asr.salm.n_batch", "512", "--asr.salm.encoder_max_batch", "1"]
        # The duration-derived output budget is supplied by the pinned native
        # recognizer; never copy the old feasibility probe's 512-token cap.
        self.process = OwnedProcess(args, directory=self.directory, name="native",
            env={"NEMO_SPEECH_HTTP_API_KEY": self.key})
        deadline = time.monotonic() + 180
        try:
            while time.monotonic() < deadline:
                check()
                self.process.check_logs()
                if self.process.process.poll() is not None:
                    raise WorkerError("local_runtime_unavailable")
                try:
                    data = self._request("/v1/models", method="GET", maximum=65536, timeout=2)
                    if (isinstance(data, dict) and isinstance(data.get("data"), list)
                            and any(isinstance(model, dict) and model.get("id") == MODEL for model in data["data"])):
                        return
                except WorkerError:
                    pass
                time.sleep(.3)
            raise WorkerError("local_runtime_unavailable")
        except BaseException:
            self.close()
            raise

    def _request(self, path, *, method="POST", body=None, maximum=MAX_NATIVE_RESPONSE_BYTES, timeout=7200):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}" + path, data=body, method=method,
            headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
        try:
            # Loopback must not traverse an environment-configured web proxy.
            with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(request, timeout=timeout) as response:
                raw = response.read(maximum + 1)
            if len(raw) > maximum:
                raise WorkerError("local_result_incomplete")
            return strict_json(raw)
        except urllib.error.HTTPError as error:
            error.close()
            raise WorkerError("local_native_request_failed") from None
        except (OSError, urllib.error.URLError, http.client.HTTPException):
            raise WorkerError("local_native_request_failed") from None

    def transcribe(self, audio, *, duration, language, diarize, check):
        if self.process is None or self.process.process.poll() is not None or language not in {"ru", "en"}:
            raise WorkerError("local_runtime_unavailable")
        if not .02 <= duration <= 3600 or audio.stat().st_size > 115200000 + 1024 * 1024:
            raise WorkerError("local_input_unavailable")
        language_name = {"ru": "Russian", "en": "English"}[language]
        instruction = (f"Transcribe this {language_name} recording verbatim with punctuation and capitalization. "
            "Preserve technical terms and named entities in the language spoken. Do not translate or summarize. "
            "Include all spoken words and verbal fillers. ")
        if diarize:
            instruction += "Start every speaker turn with a stable speaker tag such as <spk:0>, <spk:1>. "
        instruction += "Return only the transcript."
        body = json.dumps({"model": MODEL, "language": language, "temperature": 0, "stream": False,
            "timestamp_granularities": ["word"], "messages": [{"role": "user", "content": [
                {"type": "text", "text": instruction}, {"type": "input_audio", "input_audio": {
                    "data": base64.b64encode(audio.read_bytes()).decode("ascii"), "format": "wav"}}]}]},
            separators=(",", ":")).encode()
        results = queue.Queue(maxsize=1)
        def request():
            try:
                results.put(self._request("/v1/chat/completions", body=body))
            except Exception:
                results.put(WorkerError("local_native_request_failed"))
        task = threading.Thread(target=request, name="voiceops-native-request", daemon=True)
        task.start()
        deadline = time.monotonic() + 7200
        try:
            while task.is_alive():
                check()
                self.process.check_logs()
                if time.monotonic() >= deadline or self.process.process.poll() is not None:
                    raise WorkerError("local_native_request_failed")
                task.join(.2)
            data = results.get_nowait()
            if isinstance(data, Exception):
                raise data
            check()
            return complete_native_result(data, duration=duration, language=language, diarize=diarize)
        except BaseException:
            self.close()  # Stop actual owned inference; dropping an HTTP future is insufficient.
            task.join(timeout=5)
            raise

    def close(self):
        if self.process is not None:
            self.process.close()
            self.process = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
