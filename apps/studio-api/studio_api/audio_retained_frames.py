"""Versioned silence edits with recorded sample ranges, bounded streaming I/O.

Silence is detected after channel selection. Cuts keep complete 10ms blocks;
the recorded map describes those actual blocks, not estimated waveform bins.
FFmpeg uses a balanced selection expression, so long recordings do not test
every pause for every frame or buffer a separate stream for every retained span.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .audio_preparation import (AudioMonoMode, AudioPreparationError, AudioPreparationReason,
    FFMPEG_ANALYSIS_TIMEOUT_SECONDS, MAX_AUDIO_DURATION_SECONDS, trim_range)
from .audio_timeline import AudioTimeline, MAX_TIMELINE_INTERVALS, MAX_TIMELINE_JSON_BYTES, NoRetainedAudio
from .worker_progress import worker_operation

_SILENCE = re.compile(r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)\s*\|\s*silence_duration:\s*([0-9]+(?:\.[0-9]+)?)")
_ELAPSED = re.compile(r"out_time_us=([0-9]{1,15})$")


def channel_filters(mode):
    if mode is AudioMonoMode.mixdown:
        return ["aformat=channel_layouts=mono"]
    if mode is AudioMonoMode.left:
        return ["pan=mono|c0=c0"]
    if mode is AudioMonoMode.right:
        return ["pan=mono|c0=c1"]
    return []


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("audio_edit_recipe_invalid")
    return value


@dataclass(frozen=True)
class RetainedTrack:
    position: int
    sample_rate: int
    seek_sample: int
    decoded_samples: int
    original_offset_us: int
    kept: tuple[tuple[int, int], ...]

    def __post_init__(self):
        _integer(self.position, 0, 49)
        _integer(self.sample_rate, 1, 768000)
        _integer(self.seek_sample, 0, MAX_AUDIO_DURATION_SECONDS * self.sample_rate)
        _integer(self.decoded_samples, 1, MAX_AUDIO_DURATION_SECONDS * self.sample_rate)
        _integer(self.original_offset_us, 0, MAX_AUDIO_DURATION_SECONDS * 1_000_000)
        if not isinstance(self.kept, tuple) or not 0 <= len(self.kept) <= MAX_TIMELINE_INTERVALS:
            raise ValueError("audio_edit_recipe_invalid")
        previous_end = 0
        for pair in self.kept:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise ValueError("audio_edit_recipe_invalid")
            start, end = pair
            _integer(start, previous_end, self.decoded_samples - 1)
            _integer(end, start + 1, self.decoded_samples)
            if start % self.frame_samples or (end != self.decoded_samples and end % self.frame_samples):
                raise ValueError("audio_edit_recipe_unaligned")
            previous_end = end

    @property
    def frame_samples(self):
        return max(1, round(self.sample_rate / 100))

    def select_expression(self):
        """Lazy balanced if tree over frame-index runs, not a linear OR chain."""
        runs = []
        cursor = 0
        total = math.ceil(self.decoded_samples / self.frame_samples)
        for start, end in self.kept:
            first, last = start // self.frame_samples, math.ceil(end / self.frame_samples)
            if cursor < first:
                runs.append((cursor, "0"))
            runs.append((first, "1"))
            cursor = last
        if cursor < total:
            runs.append((cursor, "0"))
        if not runs:
            return "0"
        def expression(start, end):
            if end - start == 1:
                return runs[start][1]
            middle = (start + end) // 2
            return f"if(lt(n,{runs[middle][0]}),{expression(start, middle)},{expression(middle, end)})"
        return expression(0, len(runs))

    def filter_chain(self, mono_mode):
        return ["asetpts=N/SR/TB", f"atrim=end_sample={self.decoded_samples}",
            *channel_filters(mono_mode), f"asetnsamples=n={self.frame_samples}:p=0",
            "aselect='" + self.select_expression() + "'", "asetpts=N/SR/TB"]


@dataclass(frozen=True)
class RetainedRecipe:
    original_duration_us: int
    options_sha256: str
    tracks: tuple[RetainedTrack, ...]

    def __post_init__(self):
        _integer(self.original_duration_us, 1, MAX_AUDIO_DURATION_SECONDS * 1_000_000)
        if not isinstance(self.options_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", self.options_sha256):
            raise ValueError("audio_edit_recipe_invalid")
        if not isinstance(self.tracks, tuple) or not 1 <= len(self.tracks) <= 50:
            raise ValueError("audio_edit_recipe_invalid")
        previous_position = -1
        ranges = []
        for track in self.tracks:
            if not isinstance(track, RetainedTrack) or track.position <= previous_position:
                raise ValueError("audio_edit_recipe_invalid")
            previous_position = track.position
            for start, end in track.kept:
                ranges.append((track.original_offset_us + round((track.seek_sample + start) * 1_000_000 / track.sample_rate),
                    track.original_offset_us + round((track.seek_sample + end) * 1_000_000 / track.sample_rate)))
            if len(ranges) > MAX_TIMELINE_INTERVALS:
                raise ValueError("audio_edit_recipe_interval_limit")
        if not ranges:
            raise NoRetainedAudio("audio_timeline_no_retained_audio")
        AudioTimeline(self.original_duration_us, tuple(ranges))

    def timeline(self):
        ranges = tuple((track.original_offset_us + round((track.seek_sample + start) * 1_000_000 / track.sample_rate),
            track.original_offset_us + round((track.seek_sample + end) * 1_000_000 / track.sample_rate))
            for track in self.tracks for start, end in track.kept)
        return AudioTimeline(self.original_duration_us, ranges)

    def validate_inputs(self, probes, options_json):
        if self.options_sha256 != hashlib.sha256(options_json.encode()).hexdigest():
            raise ValueError("audio_edit_recipe_options_changed")
        durations = [round(probe.duration_seconds * 1_000_000) for probe in probes]
        if sum(durations) != self.original_duration_us:
            raise ValueError("audio_edit_recipe_sources_changed")
        for track in self.tracks:
            if (track.position >= len(probes) or probes[track.position].sample_rate != track.sample_rate
                    or sum(durations[:track.position]) != track.original_offset_us
                    or track.seek_sample + track.decoded_samples > round(probes[track.position].duration_seconds * track.sample_rate) + 1):
                raise ValueError("audio_edit_recipe_sources_changed")

    def serialize(self):
        return json.dumps({"version": 1, "original_duration_us": self.original_duration_us,
            "options_sha256": self.options_sha256, "tracks": [dict(position=t.position, sample_rate=t.sample_rate,
                seek_sample=t.seek_sample, decoded_samples=t.decoded_samples, original_offset_us=t.original_offset_us,
                kept=t.kept) for t in self.tracks]}, separators=(",", ":"))

    @classmethod
    def parse(cls, value):
        try:
            if not isinstance(value, str) or not 0 < len(value) <= MAX_TIMELINE_JSON_BYTES:
                raise ValueError()
            p = json.loads(value)
            if not isinstance(p, dict) or set(p) != {"version", "original_duration_us", "options_sha256", "tracks"}:
                raise ValueError()
            if type(p["version"]) is not int or p["version"] != 1 or not isinstance(p["tracks"], list) or not 1 <= len(p["tracks"]) <= 50:
                raise ValueError()
            tracks = []
            for t in p["tracks"]:
                if not isinstance(t, dict) or set(t) != {"position", "sample_rate", "seek_sample", "decoded_samples", "original_offset_us", "kept"}:
                    raise ValueError()
                kept = t["kept"]
                if not isinstance(kept, list) or len(kept) > MAX_TIMELINE_INTERVALS or any(not isinstance(x, list) for x in kept):
                    raise ValueError()
                tracks.append(RetainedTrack(**{**t, "kept": tuple(tuple(pair) for pair in kept)}))
            return cls(p["original_duration_us"], p["options_sha256"], tuple(tracks))
        except (ValueError, TypeError, KeyError, RecursionError) as exc:
            raise ValueError("audio_edit_recipe_invalid") from exc


def _retained_samples(samples, rate, silences, keep_seconds):
    """Keep the requested pause across both edges, rounding cuts inward."""
    block = max(1, round(rate / 100))
    keep = round(keep_seconds * rate)
    result = []
    cursor = 0
    for start, end in silences:
        left = max(0, round(start * rate))
        right = min(samples, round(end * rate))
        cut_start = math.ceil((left + math.ceil(keep / 2)) / block) * block
        cut_end = (right - keep // 2) // block * block
        if keep == 0 and right == samples:
            cut_end = samples
        if cut_end <= cut_start:
            continue
        if cut_start > cursor:
            result.append((cursor, cut_start))
        cursor = max(cursor, cut_end)
    if cursor < samples:
        result.append((cursor, samples))
    return tuple(result)


@worker_operation("media_analysis", FFMPEG_ANALYSIS_TIMEOUT_SECONDS + 30)
def _scan_selected(path, *, rate, seek, requested, options, runner=None, check=lambda: None, progress=lambda _: None):
    filters = ["asetpts=N/SR/TB", f"atrim=end_sample={requested}", *channel_filters(options.mono_mode)]
    if options.silence_enabled:
        filters.append(f"silencedetect=noise={options.silence_threshold_db}dB:d={options.silence_min_duration_seconds}")
    command = ["ffmpeg", "-nostdin", "-v", "info", "-xerror", "-threads", "2", "-filter_threads", "2",
        "-ss", format(seek / rate, ".12f"), "-t", format(requested / rate, ".12f"), "-i", str(path),
        "-map", "0:a:0", "-af", ",".join(filters), "-f", "null", "-", "-nostats", "-stats_period", "5", "-progress", "pipe:1"]
    silence = []
    elapsed_us = None
    failures = []
    def consume(line, *, stderr):
        nonlocal elapsed_us
        if stderr:
            match = _SILENCE.search(line)
            if match:
                end, duration = map(float, match.groups())
                if not all(math.isfinite(x) for x in (end, duration)) or duration <= 0 or end <= 0:
                    raise AudioPreparationError(AudioPreparationReason.timeline_unavailable)
                pair = (max(0.0, end - duration), min(end, requested / rate))
                if pair[1] > pair[0]:
                    if len(silence) >= MAX_TIMELINE_INTERVALS - 1:
                        raise AudioPreparationError(AudioPreparationReason.timeline_unavailable)
                    if silence and pair[0] < silence[-1][1] - .00001:
                        raise AudioPreparationError(AudioPreparationReason.timeline_unavailable)
                    silence.append(pair)
        else:
            match = _ELAPSED.fullmatch(line.strip())
            if match:
                elapsed_us = max(elapsed_us or 0, int(match.group(1)))
    check()
    if runner is not None:
        try:
            result = runner(command, capture_output=True, text=True, check=True, timeout=FFMPEG_ANALYSIS_TIMEOUT_SECONDS)
        except (OSError, subprocess.SubprocessError) as exc:
            raise AudioPreparationError(AudioPreparationReason.media_integrity_failed) from exc
        for line in (result.stdout or "").splitlines(): consume(line, stderr=False)
        for line in (result.stderr or "").splitlines(): consume(line, stderr=True)
    else:
        process = None
        threads = []
        def drain(stream, stderr):
            try:
                while line := stream.readline(4096): consume(line, stderr=stderr)
            except Exception as exc:
                failures.append(exc)
                if process.poll() is None: process.kill()
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
            for stream, is_error in ((process.stdout, False), (process.stderr, True)):
                thread = threading.Thread(target=drain, args=(stream, is_error), daemon=True)
                thread.start(); threads.append(thread)
            deadline, next_check = time.monotonic() + FFMPEG_ANALYSIS_TIMEOUT_SECONDS, time.monotonic()
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise AudioPreparationError(AudioPreparationReason.processing_timeout)
                if time.monotonic() >= next_check:
                    check(); progress(min(requested / rate, (elapsed_us or 0) / 1_000_000))
                    next_check = time.monotonic() + 5
                time.sleep(.1)
            for thread in threads: thread.join(timeout=2)
            if failures:
                raise AudioPreparationError(AudioPreparationReason.timeline_unavailable) from failures[0]
            if process.returncode or any(t.is_alive() for t in threads):
                raise AudioPreparationError(AudioPreparationReason.media_integrity_failed)
        except FileNotFoundError as exc:
            raise AudioPreparationError(AudioPreparationReason.probe_unavailable) from exc
        finally:
            if process:
                if process.poll() is None: process.kill()
                process.wait()
                for thread in threads: thread.join(timeout=2)
                process.stdout.close(); process.stderr.close()
    check()
    if elapsed_us is None or elapsed_us <= 0:
        raise AudioPreparationError(AudioPreparationReason.timeline_unavailable)
    decoded = round(elapsed_us * rate / 1_000_000)
    if not 0 < decoded <= requested + 1:
        raise AudioPreparationError(AudioPreparationReason.timeline_unavailable)
    decoded = min(decoded, requested)
    progress(decoded / rate)
    return decoded, silence


def build_retained_recipe(paths, probes, options, options_json, *, runner=None, check=lambda: None, progress=lambda _: None):
    total = sum(probe.duration_seconds for probe in probes)
    start, end = trim_range(options, total)
    offset_us = 0
    completed_seconds = 0.0
    tracks = []
    for position, (path, probe) in enumerate(zip(paths, probes, strict=True)):
        offset = offset_us / 1_000_000
        duration = round(probe.duration_seconds * 1_000_000)
        local_start, local_end = max(0.0, start - offset), min(probe.duration_seconds, end - offset)
        if local_end > local_start:
            seek = round(local_start * probe.sample_rate)
            requested = round(local_end * probe.sample_rate) - seek
            if requested <= 0: raise AudioPreparationError(AudioPreparationReason.timeline_unavailable)
            if options.silence_enabled:
                decoded, silence = _scan_selected(path, rate=probe.sample_rate, seek=seek, requested=requested,
                    options=options, runner=runner, check=check, progress=lambda seconds: progress(completed_seconds + seconds))
            else:
                # No samples are removed inside the selected interval. Avoid a
                # redundant decode: the final rendered duration is checked
                # against these sample bounds before its receipt can persist.
                check()
                decoded, silence = requested, ()
            kept = _retained_samples(decoded, probe.sample_rate, silence, options.silence_keep_duration_seconds)
            tracks.append(RetainedTrack(position, probe.sample_rate, seek, decoded, offset_us, kept))
            completed_seconds += decoded / probe.sample_rate
        offset_us += duration
    try:
        return RetainedRecipe(offset_us, hashlib.sha256(options_json.encode()).hexdigest(), tuple(tracks))
    except NoRetainedAudio as exc:
        raise AudioPreparationError(AudioPreparationReason.no_retained_audio) from exc
    except ValueError as exc:
        raise AudioPreparationError(AudioPreparationReason.timeline_unavailable) from exc
