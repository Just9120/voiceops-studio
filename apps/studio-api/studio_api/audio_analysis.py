"""Bounded waveform envelope and silence metadata; no audio retained or logged."""
from __future__ import annotations

import math
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field

from .audio_preparation import AudioMonoMode, AudioPreparationError, AudioPreparationReason, FFMPEG_ANALYSIS_TIMEOUT_SECONDS, SILENCE_END_PATTERN

MAX_VISUAL_INTERVALS = 512
MAX_WAVEFORM_POINTS = 512
_LEVEL = re.compile(r"lavfi\.astats\.Overall\.Peak_level=(-?\d+(?:\.\d+)?|-inf)")


@dataclass
class AudioVisualAnalysis:
    peaks: list[float] = field(default_factory=list)
    intervals: list[tuple[float, float]] = field(default_factory=list)
    removed_seconds: float = 0.0
    silence_count: int = 0
    intervals_truncated: bool = False
    bin_duration_seconds: float = 0.0
    speech_status: str = "unavailable"
    speech_intervals: tuple[tuple[float, float], ...] = ()
    speech_truncated: bool = False


def analyze_audio_visual(path, *, duration, options, channels=1, sample_rate=48000, points=MAX_WAVEFORM_POINTS, runner=None, check=lambda: None, progress=lambda seconds: None, speech_progress=lambda seconds: None):
    if not math.isfinite(duration) or duration <= 0 or not isinstance(sample_rate, int) or sample_rate <= 0:
        raise AudioPreparationError(AudioPreparationReason.invalid_input)
    points = max(1, min(MAX_WAVEFORM_POINTS, points))
    frames = max(1, math.ceil(duration * sample_rate / points))
    filters = []
    if options.mono_mode is AudioMonoMode.mixdown:
        filters.append("aformat=channel_layouts=mono")
        channels = 1
    elif options.mono_mode in {AudioMonoMode.left, AudioMonoMode.right}:
        filters.append("pan=mono|c0=" + ("c1" if options.mono_mode is AudioMonoMode.right else "c0"))
        channels = 1
    if options.silence_enabled:
        filters.append(f"silencedetect=noise={options.silence_threshold_db}dB:d={options.silence_min_duration_seconds}")
    # Measure peaks in original-rate bins. Downsampling short recordings can
    # discard every frame in the resampler delay and hide real sound entirely.
    envelope = "abs(val(0))"
    for channel in range(1, min(channels, 64)):
        envelope = f"max({envelope}\\,abs(val({channel})))"
    filters.extend(["aeval=" + envelope,
        f"asetnsamples=n={frames}:p=0", "astats=metadata=1:reset=1",
        "ametadata=print:key=lavfi.astats.Overall.Peak_level:file=-"])
    command = ["ffmpeg", "-nostdin", "-threads", "2", "-filter_threads", "2", "-v", "info", "-xerror",
        "-i", str(path), "-map", "0:a:0", "-af", ",".join(filters), "-f", "null", "-"]
    result = AudioVisualAnalysis(bin_duration_seconds=frames / sample_rate)
    def stdout(line):
        match = _LEVEL.search(line)
        if match and len(result.peaks) < points:
            level = float(match.group(1))
            result.peaks.append(round(min(1.0, 10 ** (min(0.0, level) / 20)) if math.isfinite(level) else 0.0, 5))
    def stderr(line):
        match = SILENCE_END_PATTERN.search(line)
        if not match:
            return
        end = min(duration, float(match.group("end")))
        start = max(0.0, end - float(match.group("duration")))
        if end <= start:
            return
        result.silence_count += 1
        result.removed_seconds += max(0.0, end - start - options.silence_keep_duration_seconds)
        if len(result.intervals) < MAX_VISUAL_INTERVALS:
            result.intervals.append((round(start, 3), round(end, 3)))
        else:
            result.intervals_truncated = True
    check()
    if runner:
        try:
            output = runner(command, capture_output=True, text=True, check=True, timeout=FFMPEG_ANALYSIS_TIMEOUT_SECONDS)
        except (OSError, subprocess.SubprocessError) as exc:
            raise AudioPreparationError(AudioPreparationReason.media_integrity_failed) from exc
        for line in (output.stdout or "").splitlines(): stdout(line)
        for line in (output.stderr or "").splitlines(): stderr(line)
        check()
        progress(duration)
        return result
    process = None
    readers = []
    failures = []
    def drain(stream, consume):
        try:
            while line := stream.readline(4096):
                consume(line)
        except (OSError, ValueError):
            failures.append(True)
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace")
        for stream, consume in ((process.stdout, stdout), (process.stderr, stderr)):
            thread = threading.Thread(target=drain, args=(stream, consume), daemon=True)
            thread.start()
            readers.append(thread)
        deadline = time.monotonic() + FFMPEG_ANALYSIS_TIMEOUT_SECONDS
        next_check = time.monotonic() + 5
        while process.poll() is None:
            if time.monotonic() >= deadline:
                raise AudioPreparationError(AudioPreparationReason.processing_timeout)
            if time.monotonic() >= next_check:
                check()
                progress(min(duration, len(result.peaks) * frames / sample_rate))
                next_check = time.monotonic() + 5
            time.sleep(0.2)
        for thread in readers: thread.join(timeout=2)
        if process.returncode != 0 or failures or any(thread.is_alive() for thread in readers):
            raise AudioPreparationError(AudioPreparationReason.media_integrity_failed)
        check()
        progress(duration)
        from .audio_speech_analysis import analyze_speech
        speech = analyze_speech(path, duration=duration, check=check, progress=speech_progress)
        result.speech_status, result.speech_intervals, result.speech_truncated = speech.status, speech.intervals, speech.truncated
        return result
    except FileNotFoundError as exc:
        raise AudioPreparationError(AudioPreparationReason.probe_unavailable) from exc
    finally:
        if process:
            if process.poll() is None:
                process.kill()
            process.wait()
            for thread in readers: thread.join(timeout=2)
            process.stdout.close()
            process.stderr.close()


def visual_payload(analyses, durations, keep_seconds):
    """Keep per-source timelines to avoid distorting unequal concat durations."""
    sources = []
    remaining = MAX_VISUAL_INTERVALS
    remaining_speech = MAX_VISUAL_INTERVALS
    for position, (analysis, duration) in enumerate(zip(analyses, durations, strict=True)):
        intervals = analysis.intervals[:remaining]
        remaining -= len(intervals)
        speech = analysis.speech_intervals[:remaining_speech]
        remaining_speech -= len(speech)
        sources.append({"position": position, "duration_seconds": duration, "peaks": analysis.peaks,
            "bin_duration_seconds": analysis.bin_duration_seconds,
            "speech_status": analysis.speech_status,
            "speech_intervals": [{"start": start, "end": end} for start, end in speech],
            "speech_truncated": analysis.speech_truncated or len(speech) < len(analysis.speech_intervals),
            "silences": [{"start": start, "end": end, "removed_seconds": round(max(0.0, end - start - keep_seconds), 3)} for start, end in intervals],
            "silence_count": analysis.silence_count,
            "intervals_truncated": analysis.intervals_truncated or len(intervals) < len(analysis.intervals)})
    return {"sources": sources, "removed_seconds": round(sum(item.removed_seconds for item in analyses), 3)}
