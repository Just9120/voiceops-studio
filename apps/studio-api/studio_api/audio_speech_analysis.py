"""Bounded local voice activity analysis. No STT, network or speaker identity."""
from dataclasses import dataclass
import queue
import subprocess
import threading
import time

from .audio_preparation import AudioPreparationError, AudioPreparationReason, FFMPEG_ANALYSIS_TIMEOUT_SECONDS

RATE = 16000
FRAME_SECONDS = 0.03
FRAME_BYTES = 960
MAX_SPEECH_INTERVALS = 512


@dataclass(frozen=True)
class SpeechAnalysis:
    status: str
    intervals: tuple[tuple[float, float], ...] = ()
    truncated: bool = False


class SpeechCollector:
    def __init__(self, duration, detector):
        self.duration, self.detector = duration, detector
        self.frames, self.start, self.last_end = 0, None, None
        self.intervals, self.truncated = [], False

    def accept(self, frame):
        start = self.frames * FRAME_SECONDS
        self.frames += 1
        if start >= self.duration: return
        end = min(self.duration, self.frames * FRAME_SECONDS)
        if self.detector.is_speech(frame.ljust(FRAME_BYTES, b"\0"), RATE):
            if self.start is None: self.start = start
            self.last_end = end
        elif self.start is not None and start - self.last_end >= 0.3:
            self._close()

    def _close(self):
        if self.start is None: return
        if len(self.intervals) < MAX_SPEECH_INTERVALS:
            self.intervals.append((round(self.start, 3), round(self.last_end, 3)))
        else:
            self.truncated = True
        self.start, self.last_end = None, None

    def finish(self):
        self._close()
        return SpeechAnalysis("available", tuple(self.intervals), self.truncated)


def analyze_speech(path, *, duration, check=lambda: None, progress=lambda seconds: None):
    try:
        import webrtcvad
    except ImportError:
        return SpeechAnalysis("unavailable")
    collector = SpeechCollector(duration, webrtcvad.Vad(2))
    frames = queue.Queue(maxsize=8)
    stop = threading.Event()
    failed = []
    command = ["ffmpeg", "-nostdin", "-threads", "2", "-filter_threads", "2", "-v", "error", "-xerror",
        "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", str(RATE), "-f", "s16le", "pipe:1"]
    check()
    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    def put(value):
        while not stop.is_set():
            try:
                frames.put(value, timeout=0.1)
                return
            except queue.Full:
                pass
    def read():
        try:
            while not stop.is_set():
                frame = child.stdout.read(FRAME_BYTES)
                if not frame: break
                put(frame)
        except (OSError, ValueError):
            failed.append(True)
        finally:
            put(None)
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    deadline, next_check = time.monotonic() + FFMPEG_ANALYSIS_TIMEOUT_SECONDS, 0.0
    try:
        while True:
            moment = time.monotonic()
            if moment >= deadline: raise AudioPreparationError(AudioPreparationReason.processing_timeout)
            if moment >= next_check:
                check()
                progress(min(duration, collector.frames * FRAME_SECONDS))
                next_check = moment + 3
            try:
                frame = frames.get(timeout=0.25)
            except queue.Empty:
                if not reader.is_alive(): raise AudioPreparationError(AudioPreparationReason.media_integrity_failed)
                continue
            if frame is None: break
            collector.accept(frame)
        child.wait(timeout=10)
        if child.returncode != 0 or failed:
            raise AudioPreparationError(AudioPreparationReason.media_integrity_failed)
        check()
        progress(duration)
        return collector.finish()
    finally:
        stop.set()
        if child.poll() is None:
            child.terminate()
            try: child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
        reader.join(timeout=2)
        child.stdout.close()
