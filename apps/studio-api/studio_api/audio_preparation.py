from __future__ import annotations

import json
import math
import re
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .source_storage import normalize_source_display_filename
from .worker_progress import worker_operation


MAX_AUDIO_INPUTS = 50
MAX_AUDIO_DURATION_SECONDS = 7 * 24 * 60 * 60
FFPROBE_TIMEOUT_SECONDS = 60
FFMPEG_ANALYSIS_TIMEOUT_SECONDS = 1800
FFMPEG_PROCESS_TIMEOUT_SECONDS = 7200
SILENCE_THRESHOLD_DB_RANGE = (-60.0, -10.0)
SILENCE_MIN_DURATION_RANGE = (0.2, 10.0)
SILENCE_KEEP_DURATION_RANGE = (0.0, 5.0)
ALLOWED_TEMPLATE_FIELDS = {"date", "time", "project", "title"}
TEMPLATE_FIELD_PATTERN = re.compile(r"\{([a-z]+)\}")
UNSAFE_OUTPUT_FILENAME_PATTERN = re.compile(r'[<>:"/\\|?*]+')
SILENCE_END_PATTERN = re.compile(
    r"silence_end:\s*(?P<end>[0-9]+(?:\.[0-9]+)?)\s*\|\s*silence_duration:\s*(?P<duration>[0-9]+(?:\.[0-9]+)?)"
)
FFPROBE_CLOCK_DURATION_PATTERN = re.compile(
    r"^(?P<hours>[0-9]{1,6}):(?P<minutes>[0-5][0-9]):(?P<seconds>[0-5][0-9](?:\.[0-9]{1,9})?)$"
)
FFPROBE_TIME_BASE_PATTERN = re.compile(r"^(?P<numerator>[0-9]{1,12})/(?P<denominator>[1-9][0-9]{0,12})$")
FFMPEG_PROGRESS_TIME_PATTERN = re.compile(r"^out_time=(?P<duration>[^\r\n]{1,32})$")


class AudioPreparationReason(str, Enum):
    invalid_options = "invalid_options"
    invalid_input = "invalid_input"
    probe_unavailable = "probe_unavailable"
    probe_failed = "probe_failed"
    media_integrity_failed = "media_integrity_failed"
    copy_incompatible = "copy_incompatible"
    channel_unavailable = "channel_unavailable"
    processing_failed = "processing_failed"
    processing_timeout = "processing_timeout"
    output_too_large = "output_too_large"


class AudioPreparationError(RuntimeError):
    def __init__(self, reason: AudioPreparationReason, *, ffmpeg_exit_code: int | None = None,
                 ffmpeg_failure_category: str | None = None):
        self.reason = reason
        self.ffmpeg_exit_code = ffmpeg_exit_code
        self.ffmpeg_failure_category = ffmpeg_failure_category
        super().__init__(reason.value)


class AudioOutputFormat(str, Enum):
    copy = "copy"
    wav = "wav"
    flac = "flac"


class AudioMonoMode(str, Enum):
    preserve = "preserve"
    mixdown = "mixdown"
    left = "left"
    right = "right"


class AudioPreset(str, Enum):
    lecture = "lecture"
    call = "call"
    processing_only = "processing_only"


@dataclass(frozen=True)
class AudioPreparationOptions:
    output_format: AudioOutputFormat
    mono_mode: AudioMonoMode
    silence_enabled: bool
    silence_threshold_db: float
    silence_min_duration_seconds: float
    silence_keep_duration_seconds: float
    output_name_template: str
    preset: AudioPreset
    trim_start_seconds: float = 0.0
    trim_end_seconds: float | None = None


@dataclass(frozen=True)
class AudioProbe:
    duration_seconds: float
    format_name: str
    codec_name: str
    sample_rate: int
    channels: int
    channel_layout: str | None

    @property
    def copy_signature(self) -> tuple[str, str, int, int, str | None]:
        return (
            self.format_name,
            self.codec_name,
            self.sample_rate,
            self.channels,
            self.channel_layout,
        )


@dataclass(frozen=True)
class AudioPreview:
    input_count: int
    input_duration_seconds: float
    estimated_output_duration_seconds: float
    copy_compatible: bool
    probes: tuple[AudioProbe, ...]


PRESET_DEFAULTS: dict[AudioPreset, dict[str, object]] = {
    AudioPreset.lecture: {
        "output_format": AudioOutputFormat.flac.value,
        "mono_mode": AudioMonoMode.mixdown.value,
        "silence_enabled": True,
        "silence_threshold_db": -38.0,
        "silence_min_duration_seconds": 1.2,
        "silence_keep_duration_seconds": 0.35,
        "output_name_template": "{date}_{title}",
    },
    AudioPreset.call: {
        "output_format": AudioOutputFormat.flac.value,
        "mono_mode": AudioMonoMode.mixdown.value,
        "silence_enabled": True,
        "silence_threshold_db": -42.0,
        "silence_min_duration_seconds": 1.8,
        "silence_keep_duration_seconds": 0.5,
        "output_name_template": "{date}_{time}_{title}",
    },
    AudioPreset.processing_only: {
        "output_format": AudioOutputFormat.wav.value,
        "mono_mode": AudioMonoMode.preserve.value,
        "silence_enabled": False,
        "silence_threshold_db": -40.0,
        "silence_min_duration_seconds": 1.0,
        "silence_keep_duration_seconds": 0.3,
        "output_name_template": "{title}",
    },
}


def normalize_options(payload: dict[str, object]) -> AudioPreparationOptions:
    if not isinstance(payload, dict):
        raise AudioPreparationError(AudioPreparationReason.invalid_options)
    try:
        preset = AudioPreset(str(payload.get("preset") or AudioPreset.processing_only.value))
    except ValueError as exc:
        raise AudioPreparationError(AudioPreparationReason.invalid_options) from exc
    effective = dict(PRESET_DEFAULTS[preset])
    for key in effective:
        if key in payload:
            effective[key] = payload[key]
    try:
        output_format = AudioOutputFormat(str(effective["output_format"]))
        mono_mode = AudioMonoMode(str(effective["mono_mode"]))
    except ValueError as exc:
        raise AudioPreparationError(AudioPreparationReason.invalid_options) from exc
    if not isinstance(effective["silence_enabled"], bool):
        raise AudioPreparationError(AudioPreparationReason.invalid_options)
    threshold = _bounded_number(effective["silence_threshold_db"], SILENCE_THRESHOLD_DB_RANGE)
    minimum = _bounded_number(effective["silence_min_duration_seconds"], SILENCE_MIN_DURATION_RANGE)
    keep = _bounded_number(effective["silence_keep_duration_seconds"], SILENCE_KEEP_DURATION_RANGE)
    if keep > minimum:
        raise AudioPreparationError(AudioPreparationReason.invalid_options)
    template = str(effective["output_name_template"] or "").strip()
    if not template or len(template) > 160:
        raise AudioPreparationError(AudioPreparationReason.invalid_options)
    fields = set(TEMPLATE_FIELD_PATTERN.findall(template))
    if fields - ALLOWED_TEMPLATE_FIELDS or "{" in TEMPLATE_FIELD_PATTERN.sub("", template) or "}" in TEMPLATE_FIELD_PATTERN.sub("", template):
        raise AudioPreparationError(AudioPreparationReason.invalid_options)
    if output_format is AudioOutputFormat.copy and (
        mono_mode is not AudioMonoMode.preserve or effective["silence_enabled"]
        or payload.get("trim_start_seconds", 0) != 0 or payload.get("trim_end_seconds") is not None
    ):
        raise AudioPreparationError(AudioPreparationReason.invalid_options)
    return AudioPreparationOptions(
        output_format=output_format,
        mono_mode=mono_mode,
        silence_enabled=effective["silence_enabled"],
        silence_threshold_db=threshold,
        silence_min_duration_seconds=minimum,
        silence_keep_duration_seconds=keep,
        output_name_template=template,
        preset=preset,
        trim_start_seconds=_bounded_number(payload.get("trim_start_seconds", 0), (0, MAX_AUDIO_DURATION_SECONDS)),
        trim_end_seconds=None if payload.get("trim_end_seconds") is None else _bounded_number(payload["trim_end_seconds"], (0, MAX_AUDIO_DURATION_SECONDS)),
    )


def trim_range(options: AudioPreparationOptions, duration: float) -> tuple[float, float]:
    start = options.trim_start_seconds
    end = duration if options.trim_end_seconds is None else options.trim_end_seconds
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end > duration + 0.001 or end <= start or start >= duration:
        raise AudioPreparationError(AudioPreparationReason.invalid_options)
    return start, min(end, duration)


def estimate_trimmed_duration(options: AudioPreparationOptions, duration: float, visual: dict) -> float:
    """Estimate on the original timeline; clipping precedes pause reduction."""
    start, end = trim_range(options, duration)
    removed, offset = 0.0, 0.0
    if options.silence_enabled:
        for source in visual.get("sources", []):
            for part in source.get("silences", []):
                overlap = max(0.0, min(end, offset + part["end"]) - max(start, offset + part["start"]))
                if overlap >= options.silence_min_duration_seconds:
                    removed += max(0.0, overlap - options.silence_keep_duration_seconds)
            offset += source["duration_seconds"]
    return max(0.0, end - start - removed)


@worker_operation("media_probe", FFPROBE_TIMEOUT_SECONDS + 30)
def probe_media(
    path: Path,
    *,
    runner: Callable = subprocess.run,
) -> AudioProbe:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=FFPROBE_TIMEOUT_SECONDS,
        )
        payload = json.loads(result.stdout)
    except FileNotFoundError as exc:
        raise AudioPreparationError(AudioPreparationReason.probe_unavailable) from exc
    except (subprocess.SubprocessError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AudioPreparationError(AudioPreparationReason.probe_failed) from exc
    streams = payload.get("streams") if isinstance(payload, dict) else None
    format_payload = payload.get("format") if isinstance(payload, dict) else None
    if not isinstance(streams, list) or not isinstance(format_payload, dict):
        raise AudioPreparationError(AudioPreparationReason.invalid_input)
    audio_streams = [item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"]
    if not audio_streams:
        raise AudioPreparationError(AudioPreparationReason.invalid_input)
    stream = audio_streams[0]
    codec = _bounded_token(stream.get("codec_name"), 40)
    format_name = _bounded_token(format_payload.get("format_name"), 120)
    sample_rate = _positive_int(stream.get("sample_rate"), 384000)
    channels = _positive_int(stream.get("channels"), 64)
    channel_layout = stream.get("channel_layout")
    if channel_layout is not None and (not isinstance(channel_layout, str) or len(channel_layout) > 80):
        raise AudioPreparationError(AudioPreparationReason.invalid_input)
    try:
        duration = _first_positive_duration(
            stream.get("duration"),
            format_payload.get("duration"),
            *_ffprobe_tag_durations(stream),
            *_ffprobe_tag_durations(format_payload),
            _ffprobe_time_base_duration(stream),
            *(
                value
                for candidate in streams
                if isinstance(candidate, dict) and candidate is not stream
                for value in (
                    candidate.get("duration"),
                    *_ffprobe_tag_durations(candidate),
                    _ffprobe_time_base_duration(candidate),
                )
            ),
        )
    except AudioPreparationError as exc:
        if exc.reason is not AudioPreparationReason.invalid_input:
            raise
        duration = _scan_audio_duration(path, runner=runner)
    return AudioProbe(duration, format_name, codec, sample_rate, channels, channel_layout)


@worker_operation("media_analysis", FFMPEG_ANALYSIS_TIMEOUT_SECONDS + 30)
def verify_media_integrity(path: Path, *, runner: Callable = subprocess.run) -> None:
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-xerror",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-f",
        "null",
        "-",
    ]
    try:
        runner(command, capture_output=True, check=True, timeout=FFMPEG_ANALYSIS_TIMEOUT_SECONDS)
    except FileNotFoundError as exc:
        raise AudioPreparationError(AudioPreparationReason.probe_unavailable) from exc
    except subprocess.SubprocessError as exc:
        raise AudioPreparationError(AudioPreparationReason.media_integrity_failed) from exc


@worker_operation("media_analysis", FFMPEG_ANALYSIS_TIMEOUT_SECONDS + 30)
def analyze_silence(
    path: Path,
    *,
    threshold_db: float,
    minimum_seconds: float,
    runner: Callable = subprocess.run,
) -> tuple[float, ...]:
    command = [
        "ffmpeg",
        "-v",
        "info",
        "-xerror",
        "-i",
        str(path),
        "-af",
        f"silencedetect=noise={_number(threshold_db)}dB:d={_number(minimum_seconds)}",
        "-f",
        "null",
        "-",
    ]
    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=FFMPEG_ANALYSIS_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise AudioPreparationError(AudioPreparationReason.probe_unavailable) from exc
    except subprocess.SubprocessError as exc:
        raise AudioPreparationError(AudioPreparationReason.media_integrity_failed) from exc
    return tuple(float(match.group("duration")) for match in SILENCE_END_PATTERN.finditer(result.stderr or ""))


def build_preview(
    probes: Sequence[AudioProbe],
    silence_durations: Iterable[float],
    options: AudioPreparationOptions,
) -> AudioPreview:
    if not probes or len(probes) > MAX_AUDIO_INPUTS:
        raise AudioPreparationError(AudioPreparationReason.invalid_input)
    total = sum(probe.duration_seconds for probe in probes)
    if total <= 0 or total > MAX_AUDIO_DURATION_SECONDS:
        raise AudioPreparationError(AudioPreparationReason.invalid_input)
    copy_compatible = all(probe.copy_signature == probes[0].copy_signature for probe in probes[1:])
    if options.output_format is AudioOutputFormat.copy and not copy_compatible:
        raise AudioPreparationError(AudioPreparationReason.copy_incompatible)
    if options.mono_mode is AudioMonoMode.right and any(probe.channels < 2 for probe in probes):
        raise AudioPreparationError(AudioPreparationReason.channel_unavailable)
    removed = 0.0
    if options.silence_enabled:
        removed = sum(max(0.0, float(duration) - options.silence_keep_duration_seconds) for duration in silence_durations)
    start, end = trim_range(options, total)
    estimated = max(0.0, end - start - removed)
    return AudioPreview(len(probes), total, estimated, copy_compatible, tuple(probes))


def build_ffmpeg_command(
    input_paths: Sequence[Path],
    output_path: Path,
    options: AudioPreparationOptions,
    probes: Sequence[AudioProbe],
    *,
    concat_list_path: Path | None = None,
    creation_time: datetime | None = None,
) -> list[str]:
    preview = build_preview(probes, (), options)
    if len(input_paths) != len(probes) or not input_paths:
        raise AudioPreparationError(AudioPreparationReason.invalid_input)
    if options.output_format is AudioOutputFormat.copy:
        if not preview.copy_compatible or concat_list_path is None:
            raise AudioPreparationError(AudioPreparationReason.copy_incompatible)
        command = [
            "ffmpeg",
            "-v",
            "error",
            "-xerror",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            str(concat_list_path),
            "-map",
            "0:a:0",
            "-c:a",
            "copy",
        ]
        if creation_time is not None:
            command.extend(["-metadata", f"creation_time={_iso_creation_time(creation_time)}"])
        command.extend(["-y", str(output_path)])
        return command
    command = ["ffmpeg", "-v", "error", "-xerror"]
    for path in input_paths:
        command.extend(["-i", str(path)])
    filters = []
    labels = []
    start, end = trim_range(options, preview.input_duration_seconds)
    offset = 0.0
    for index in range(len(input_paths)):
        local_start = max(0.0, start - offset)
        local_end = min(probes[index].duration_seconds, end - offset)
        offset += probes[index].duration_seconds
        if local_end <= local_start:
            continue
        chain = []
        if local_start > 0 or local_end < probes[index].duration_seconds:
            chain.append(f"atrim=start={_number(local_start)}:end={_number(local_end)}")
        if options.mono_mode is AudioMonoMode.mixdown:
            chain.append("aformat=channel_layouts=mono")
        elif options.mono_mode is AudioMonoMode.left:
            chain.append("pan=mono|c0=c0")
        elif options.mono_mode is AudioMonoMode.right:
            chain.append("pan=mono|c0=c1")
        if options.silence_enabled:
            chain.append(
                "silenceremove="
                f"start_periods=0:stop_periods=-1:stop_duration={_number(options.silence_min_duration_seconds)}:"
                f"stop_threshold={_number(options.silence_threshold_db)}dB:"
                f"stop_silence={_number(options.silence_keep_duration_seconds)}"
            )
        label = f"a{index}"
        chain.append("asetpts=PTS-STARTPTS")
        filters.append(f"[{index}:a:0]{','.join(chain)}[{label}]")
        labels.append(f"[{label}]")
    if len(labels) > 1:
        filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[outa]")
        output_label = "[outa]"
    else:
        output_label = labels[0]
    command.extend(["-filter_complex", ";".join(filters), "-map", output_label])
    if options.output_format is AudioOutputFormat.wav:
        command.extend(["-c:a", "pcm_s16le", "-f", "wav"])
    else:
        # FFmpeg may otherwise promote filtered AAC/Opus input to 24-bit FLAC.
        # Speech-oriented Studio output is explicitly 16-bit while retaining
        # the source sample rate, avoiding a much larger file with no useful
        # precision gain over the lossy source.
        command.extend(["-c:a", "flac", "-sample_fmt", "s16", "-f", "flac"])
    if creation_time is not None:
        command.extend(["-metadata", f"creation_time={_iso_creation_time(creation_time)}"])
    command.extend(["-y", str(output_path)])
    return command


@worker_operation("media_processing", FFMPEG_PROCESS_TIMEOUT_SECONDS + 30)
def run_processing(
    command: Sequence[str],
    *,
    runner: Callable = subprocess.run,
    expected_duration_seconds: float | None = None,
    progress_callback: Callable[[float], None] | None = None,
) -> None:
    if runner is subprocess.run and progress_callback is not None and expected_duration_seconds:
        _run_processing_with_progress(
            command,
            expected_duration_seconds=expected_duration_seconds,
            progress_callback=progress_callback,
        )
        return
    try:
        runner(list(command), capture_output=True, check=True, timeout=FFMPEG_PROCESS_TIMEOUT_SECONDS)
    except FileNotFoundError as exc:
        raise AudioPreparationError(AudioPreparationReason.probe_unavailable) from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioPreparationError(AudioPreparationReason.processing_timeout) from exc
    except subprocess.CalledProcessError as exc:
        raise AudioPreparationError(
            AudioPreparationReason.processing_failed,
            ffmpeg_exit_code=_safe_ffmpeg_exit_code(exc.returncode),
            ffmpeg_failure_category=_ffmpeg_failure_category(exc.stderr),
        ) from exc
    except subprocess.SubprocessError as exc:
        raise AudioPreparationError(AudioPreparationReason.processing_failed) from exc


def _run_processing_with_progress(
    command: Sequence[str],
    *,
    expected_duration_seconds: float,
    progress_callback: Callable[[float], None],
) -> None:
    # Global options must never split an output option/value pair such as -fs/size.
    progress_command = [command[0]] + [
        "-nostdin",
        "-nostats",
        "-stats_period",
        "5",
        "-progress",
        "pipe:1",
    ] + list(command[1:])
    timed_out = threading.Event()
    process = None
    stderr_reader = None
    stderr_tail = ""
    last_progress_ratio = 0.0

    def drain_stderr(stream) -> None:
        nonlocal stderr_tail
        try:
            while chunk := stream.read(4096):
                # Drain the pipe continuously without retaining raw logs or growing memory.
                stderr_tail = (stderr_tail + chunk)[-16384:]
        except (OSError, ValueError):
            pass

    def terminate_on_timeout() -> None:
        timed_out.set()
        if process is not None:
            process.kill()

    timer = threading.Timer(FFMPEG_PROCESS_TIMEOUT_SECONDS, terminate_on_timeout)
    try:
        process = subprocess.Popen(
            progress_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        timer.start()
        if getattr(process, "stderr", None) is not None:
            stderr_reader = threading.Thread(target=drain_stderr, args=(process.stderr,), daemon=True)
            stderr_reader.start()
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.strip()
            match = FFMPEG_PROGRESS_TIME_PATTERN.fullmatch(line)
            if match is not None:
                try:
                    current = _positive_duration(match.group("duration"))
                except AudioPreparationError:
                    continue
                last_progress_ratio = max(last_progress_ratio, min(0.99, current / expected_duration_seconds))
                progress_callback(last_progress_ratio)
            elif line == "progress=end":
                progress_callback(1.0)
            elif line == "progress=continue":
                # Also check cancellation/lease while FFmpeg has not emitted a
                # usable output timestamp yet (e.g. a long initial pause).
                progress_callback(last_progress_ratio)
        return_code = process.wait()
    except FileNotFoundError as exc:
        raise AudioPreparationError(AudioPreparationReason.probe_unavailable) from exc
    except OSError as exc:
        raise AudioPreparationError(AudioPreparationReason.processing_failed) from exc
    except Exception:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        raise
    finally:
        timer.cancel()
        if stderr_reader is not None:
            stderr_reader.join(timeout=2)
            if not stderr_reader.is_alive():
                process.stderr.close()
        if process is not None and process.stdout is not None:
            process.stdout.close()
    if timed_out.is_set():
        raise AudioPreparationError(AudioPreparationReason.processing_timeout)
    if return_code != 0:
        raise AudioPreparationError(
            AudioPreparationReason.processing_failed,
            ffmpeg_exit_code=_safe_ffmpeg_exit_code(return_code),
            ffmpeg_failure_category=_ffmpeg_failure_category(stderr_tail),
        )


def _safe_ffmpeg_exit_code(value: object) -> int | None:
    return value if type(value) is int and -255 <= value <= 255 else None


def _ffmpeg_failure_category(stderr: object) -> str:
    if isinstance(stderr, bytes):
        stderr = stderr[-16384:].decode("utf-8", errors="replace")
    value = stderr[-16384:].lower() if isinstance(stderr, str) else ""
    categories = {
        "invalid_arguments": ("error parsing options", "unrecognized option", "unable to parse option value"),
        "invalid_media": ("invalid data found when processing input", "could not find codec parameters"),
        "encoder_unavailable": ("unknown encoder", "encoder not found"),
        "output_io_failed": ("no space left on device", "permission denied"),
    }
    return next((category for category, markers in categories.items() if any(marker in value for marker in markers)), "unknown")


def render_output_filename(
    options: AudioPreparationOptions,
    *,
    created_at: datetime | None,
    project_title: str,
    title: str,
) -> str:
    moment = created_at
    if moment is not None and moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    def safe_output_stem(value: str) -> str:
        normalized = normalize_source_display_filename(value, max_length=220)
        # Metadata and the rendered template are already extension-free titles.
        stem = normalized.strip(" ._")
        stem = UNSAFE_OUTPUT_FILENAME_PATTERN.sub("_", stem).strip(" ._")
        return stem or "processed-audio"

    values = {
        "date": moment.astimezone(timezone.utc).strftime("%Y-%m-%d") if moment else "",
        "time": moment.astimezone(timezone.utc).strftime("%H-%M-%SZ") if moment else "",
        "project": safe_output_stem(project_title),
        "title": safe_output_stem(title),
    }
    rendered = TEMPLATE_FIELD_PATTERN.sub(lambda match: values[match.group(1)], options.output_name_template)
    extension = options.output_format.value
    if options.output_format is AudioOutputFormat.copy:
        extension = "audio"
    stem = safe_output_stem(rendered) if rendered.strip(" ._-Z") else values["title"]
    return f"{stem[:220]}.{extension}"


def _bounded_number(value: object, bounds: tuple[float, float]) -> float:
    if isinstance(value, bool):
        raise AudioPreparationError(AudioPreparationReason.invalid_options)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AudioPreparationError(AudioPreparationReason.invalid_options) from exc
    if not math.isfinite(number) or number < bounds[0] or number > bounds[1]:
        raise AudioPreparationError(AudioPreparationReason.invalid_options)
    return number


def _positive_duration(value: object) -> float:
    if isinstance(value, str):
        match = FFPROBE_CLOCK_DURATION_PATTERN.fullmatch(value.strip())
        if match is not None:
            duration = (
                int(match.group("hours")) * 3600
                + int(match.group("minutes")) * 60
                + float(match.group("seconds"))
            )
            if math.isfinite(duration) and 0 < duration <= MAX_AUDIO_DURATION_SECONDS:
                return duration
    try:
        duration = float(value)
    except (TypeError, ValueError) as exc:
        raise AudioPreparationError(AudioPreparationReason.invalid_input) from exc
    if not math.isfinite(duration) or duration <= 0 or duration > MAX_AUDIO_DURATION_SECONDS:
        raise AudioPreparationError(AudioPreparationReason.invalid_input)
    return duration


def _first_positive_duration(*values: object) -> float:
    """Return the first valid ffprobe duration without trusting truthy sentinels.

    Matroska/WebM streams commonly report ``"N/A"`` while the container-level
    duration remains authoritative.  A truthiness fallback therefore rejects
    otherwise valid OBS captures before it considers the format duration.
    """
    for value in values:
        try:
            return _positive_duration(value)
        except AudioPreparationError as exc:
            if exc.reason is not AudioPreparationReason.invalid_input:
                raise
    raise AudioPreparationError(AudioPreparationReason.invalid_input)


def _ffprobe_tag_durations(payload: dict[str, object]) -> tuple[object, ...]:
    tags = payload.get("tags")
    if not isinstance(tags, dict):
        return ()
    return tuple(value for key, value in tags.items() if isinstance(key, str) and key.upper() == "DURATION")


def _ffprobe_time_base_duration(stream: dict[str, object]) -> float | None:
    duration_ts = stream.get("duration_ts")
    time_base = stream.get("time_base")
    if isinstance(duration_ts, bool) or not isinstance(time_base, str):
        return None
    match = FFPROBE_TIME_BASE_PATTERN.fullmatch(time_base.strip())
    if match is None:
        return None
    try:
        ticks = int(duration_ts)
    except (TypeError, ValueError, OverflowError):
        return None
    numerator = int(match.group("numerator"))
    denominator = int(match.group("denominator"))
    if ticks <= 0 or numerator <= 0:
        return None
    return ticks * numerator / denominator


@worker_operation("media_analysis", FFMPEG_ANALYSIS_TIMEOUT_SECONDS + 30)
def _scan_audio_duration(path: Path, *, runner: Callable = subprocess.run) -> float:
    """Decode one audio stream when Matroska metadata has no usable duration.

    OBS captures that were not finalized cleanly can remain decodable while all
    container, stream and tag duration fields are absent.  FFmpeg's progress
    protocol reports a bounded clock value without emitting one row per packet.
    The slow path is used only after the normal ffprobe metadata fallbacks fail.
    """
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-xerror",
        "-nostats",
        "-stats_period",
        "30",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-f",
        "null",
        "-",
        "-progress",
        "pipe:1",
    ]
    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=FFMPEG_ANALYSIS_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise AudioPreparationError(AudioPreparationReason.probe_unavailable) from exc
    except subprocess.SubprocessError as exc:
        raise AudioPreparationError(AudioPreparationReason.media_integrity_failed) from exc
    values = tuple(
        match.group("duration")
        for line in (result.stdout or "").splitlines()
        if (match := FFMPEG_PROGRESS_TIME_PATTERN.fullmatch(line.strip())) is not None
    )
    return _first_positive_duration(*reversed(values))


def _positive_int(value: object, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AudioPreparationError(AudioPreparationReason.invalid_input) from exc
    if parsed <= 0 or parsed > maximum:
        raise AudioPreparationError(AudioPreparationReason.invalid_input)
    return parsed


def _bounded_token(value: object, maximum: int) -> str:
    if not isinstance(value, str):
        raise AudioPreparationError(AudioPreparationReason.invalid_input)
    token = value.strip().lower()
    if not token or len(token) > maximum or not re.fullmatch(r"[a-z0-9_,.-]+", token):
        raise AudioPreparationError(AudioPreparationReason.invalid_input)
    return token


def _number(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _iso_creation_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
