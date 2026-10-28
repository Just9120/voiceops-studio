from __future__ import annotations

import json
import re
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from math import ceil, isfinite
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO, Callable, Iterator

from .source_creation import parse_authoritative_source_created_at
from .preparation_control import PreparationInterrupted, check_preparation_control, controlled_runner
from .audio_preparation import AudioPreparationError, AudioPreparationReason, probe_media, verify_media_integrity
from .work_progress import report_work


FFMPEG_VIDEO_EXTRACTION_TIMEOUT_SECONDS = 1800
FFMPEG_PART_EXTRACTION_TIMEOUT_SECONDS = 1800
FFPROBE_TIMEOUT_SECONDS = 30
FFMPEG_AUDIO_BITRATE = "192k"
ELEVENLABS_PART_AUDIO_BITRATE = "96k"
ELEVENLABS_PART_MAX_BYTES = 25 * 1024 * 1024
ELEVENLABS_PART_TARGET_BYTES = 20 * 1024 * 1024
ELEVENLABS_PART_TARGET_DURATION_SECONDS = 1320.0
ELEVENLABS_PART_MIN_DURATION_SECONDS = 30.0
ELEVENLABS_PART_OVERLAP_SECONDS = 2.0
ELEVENLABS_MAX_PARTS = 256
# Standard single-channel STT request limits; source/resource guards still apply.
ELEVENLABS_WHOLE_MAX_BYTES = 5_000_000_000 - 1
ELEVENLABS_WHOLE_MAX_DURATION_SECONDS = 36_000
YANDEX_MAX_BYTES = 60 * 1024 * 1024
YANDEX_MAX_DURATION_SECONDS = 14400
YANDEX_AUDIO_BITRATE = "24k"
_COPY_CHUNK_SIZE = 1024 * 1024


class MediaPreparationReason(str, Enum):
    ffmpeg_unavailable = "ffmpeg_unavailable"
    media_preparation_timeout = "media_preparation_timeout"
    media_preparation_failed = "media_preparation_failed"
    prepared_media_too_large = "prepared_media_too_large"
    media_duration_unavailable = "media_duration_unavailable"
    media_split_failed = "media_split_failed"
    media_part_too_large = "media_part_too_large"
    media_clip_out_of_bounds = "media_clip_out_of_bounds"
    media_duration_confirmation_required = "media_duration_confirmation_required"
    media_duration_too_long = "media_duration_too_long"


class MediaPreparationError(RuntimeError):
    def __init__(self, reason: MediaPreparationReason, *, duration_seconds: float | None = None):
        self.reason = reason
        self.duration_seconds = duration_seconds
        super().__init__(reason.value)


@dataclass(frozen=True)
class PreparedMediaInput:
    filename: str
    mime_type: str
    byte_count: int
    stream: BinaryIO = field(repr=False)
    audio_extracted: bool = False
    part_index: int = 1
    part_count: int = 1
    timeline_offset_seconds: float = 0.0
    duration_seconds: float | None = None
    source_created_at: datetime | None = None

    def __repr__(self) -> str:
        return (
            "PreparedMediaInput(filename=<redacted>, "
            f"mime_type={self.mime_type!r}, byte_count={self.byte_count!r}, "
            f"audio_extracted={self.audio_extracted!r}, "
            f"part_index={self.part_index!r}, part_count={self.part_count!r}, "
            f"timeline_offset_seconds={self.timeline_offset_seconds!r}, "
            f"duration_seconds={self.duration_seconds!r}, stream=<redacted>)"
        )


@dataclass(frozen=True)
class PreparedMediaBatch:
    parts: tuple[PreparedMediaInput, ...] = field(repr=False)
    duration_seconds: float
    split_reason: str | None = None
    source_created_at: datetime | None = None

    def __repr__(self) -> str:
        return (
            "PreparedMediaBatch(parts=<redacted>, "
            f"part_count={len(self.parts)!r}, "
            f"duration_seconds={self.duration_seconds!r}, "
            f"split_reason={self.split_reason!r})"
        )


def requires_video_audio_extraction(mime_type: str) -> bool:
    normalized = str(mime_type or "").split(";", 1)[0].strip().lower()
    return normalized.startswith("video/")


@contextmanager
def prepare_elevenlabs_media_input(
    *,
    stream: BinaryIO,
    original_filename: str,
    mime_type: str,
    byte_count: int,
    max_output_bytes: int,
    runner: Callable[..., object] = subprocess.run,
    temporary_directory: str | None = None,
    probe_source_creation_time: bool = False,
) -> Iterator[PreparedMediaInput]:
    runner = controlled_runner(runner)
    if not requires_video_audio_extraction(mime_type):
        if not probe_source_creation_time:
            yield PreparedMediaInput(
                filename=original_filename,
                mime_type=mime_type,
                byte_count=byte_count,
                stream=stream,
            )
            return
        with TemporaryDirectory(prefix="studio-metadata-", dir=temporary_directory) as temp_dir:
            input_path = Path(temp_dir) / f"source{_safe_input_suffix(original_filename)}"
            _copy_input(stream, input_path)
            source_created_at = _probe_source_creation_time(runner, input_path)
            stream.seek(0)
            yield PreparedMediaInput(
                filename=original_filename,
                mime_type=mime_type,
                byte_count=byte_count,
                stream=stream,
                source_created_at=source_created_at,
            )
        return

    if max_output_bytes <= 0:
        raise MediaPreparationError(MediaPreparationReason.media_preparation_failed)

    with TemporaryDirectory(
        prefix="studio-media-",
        dir=temporary_directory,
    ) as temp_dir:
        try:
            root = Path(temp_dir)
            input_path = root / f"source{_safe_input_suffix(original_filename)}"
            output_path = root / "prepared-audio.m4a"
            _copy_input(stream, input_path)
            source_created_at = (
                _probe_source_creation_time(runner, input_path)
                if probe_source_creation_time
                else None
            )
            _run_ffmpeg(runner, input_path, output_path)
            prepared_size = _validated_output_size(output_path, max_output_bytes)
            prepared_name = f"{_safe_stem(original_filename)}.m4a"
            prepared_stream = output_path.open("rb")
        except (MediaPreparationError, PreparationInterrupted):
            raise
        except Exception as exc:
            raise MediaPreparationError(
                MediaPreparationReason.media_preparation_failed,
            ) from exc
        try:
            yield PreparedMediaInput(
                filename=prepared_name,
                mime_type="audio/mp4",
                byte_count=prepared_size,
                stream=prepared_stream,
                audio_extracted=True,
                source_created_at=source_created_at,
            )
        finally:
            prepared_stream.close()


@contextmanager
def prepare_elevenlabs_media_parts(
    *,
    stream: BinaryIO,
    original_filename: str,
    mime_type: str,
    byte_count: int,
    max_output_bytes: int,
    media_clip_start_seconds: int | None = None,
    media_clip_end_seconds: int | None = None,
    runner: Callable[..., object] = subprocess.run,
    temporary_directory: str | None = None,
    probe_source_creation_time: bool = False,
    duration_warning_seconds: int = 14400,
    max_duration_seconds: int = 43200,
    long_duration_confirmed: bool = False,
    confirmed_source_duration_seconds: float | None = None,
    prefer_whole_recording: bool = False,
) -> Iterator[PreparedMediaBatch]:
    runner = controlled_runner(runner)
    with prepare_elevenlabs_media_input(
        stream=stream,
        original_filename=original_filename,
        mime_type=mime_type,
        byte_count=byte_count,
        max_output_bytes=max_output_bytes,
        runner=runner,
        temporary_directory=temporary_directory,
        probe_source_creation_time=probe_source_creation_time,
    ) as prepared:
        with TemporaryDirectory(
            prefix="studio-parts-",
            dir=temporary_directory,
        ) as temp_dir:
            part_streams: list[BinaryIO] = []
            try:
                root = Path(temp_dir)
                prepared_path = root / f"prepared-source{_safe_input_suffix(prepared.filename)}"
                _copy_input(prepared.stream, prepared_path)
                prepared_size = _validated_output_size(prepared_path, max_output_bytes)
                duration = _probe_duration_seconds(runner, prepared_path)
                _validate_whole_source_duration(duration, max_duration_seconds, duration_warning_seconds,
                    long_duration_confirmed and (confirmed_source_duration_seconds is None
                        or round(duration, 3) == confirmed_source_duration_seconds))
                _validate_elevenlabs_prepared_audio(prepared_path, prepared.mime_type, runner)
                clip_requested = (
                    media_clip_start_seconds is not None
                    or media_clip_end_seconds is not None
                )
                if clip_requested:
                    clip_start, clip_end = _validated_manual_clip_bounds(
                        start_seconds=media_clip_start_seconds,
                        end_seconds=media_clip_end_seconds,
                        source_duration_seconds=duration,
                    )
                    clip_path = root / "manual-clip.m4a"
                    prepared_size = _create_manual_clip(
                        runner=runner,
                        prepared_path=prepared_path,
                        output_path=clip_path,
                        start_seconds=clip_start,
                        duration_seconds=clip_end - clip_start,
                        max_output_bytes=max_output_bytes,
                    )
                    prepared_path = clip_path
                    duration = _probe_duration_seconds(runner, prepared_path)
                split_reason = _split_reason(
                    prepared_size, duration, prefer_whole_recording=prefer_whole_recording,
                )
                if split_reason is None:
                    if clip_requested:
                        prepared_stream = prepared_path.open("rb")
                        part_streams.append(prepared_stream)
                        part_filename = f"{_safe_stem(prepared.filename)}.m4a"
                        part_mime_type = "audio/mp4"
                        part_size = prepared_size
                    else:
                        prepared.stream.seek(0)
                        prepared_stream = prepared.stream
                        part_filename = prepared.filename
                        part_mime_type = prepared.mime_type
                        part_size = prepared.byte_count
                    batch = PreparedMediaBatch(
                        parts=(
                            PreparedMediaInput(
                                filename=part_filename,
                                mime_type=part_mime_type,
                                byte_count=part_size,
                                stream=prepared_stream,
                                audio_extracted=prepared.audio_extracted,
                                duration_seconds=duration,
                            ),
                        ),
                        duration_seconds=duration,
                        source_created_at=prepared.source_created_at,
                    )
                else:
                    part_specs = _create_split_parts(
                        runner=runner,
                        prepared_path=prepared_path,
                        root=root,
                        prepared_size=prepared_size,
                        duration_seconds=duration,
                        max_total_bytes=max_output_bytes,
                    )
                    part_count = len(part_specs)
                    parts: list[PreparedMediaInput] = []
                    for index, (path, offset, part_duration, part_size) in enumerate(
                        part_specs,
                        start=1,
                    ):
                        part_stream = path.open("rb")
                        part_streams.append(part_stream)
                        parts.append(
                            PreparedMediaInput(
                                filename=f"{_safe_stem(prepared.filename)} - part {index:03d}.m4a",
                                mime_type="audio/mp4",
                                byte_count=part_size,
                                stream=part_stream,
                                audio_extracted=prepared.audio_extracted,
                                part_index=index,
                                part_count=part_count,
                                timeline_offset_seconds=offset,
                                duration_seconds=part_duration,
                            )
                        )
                    batch = PreparedMediaBatch(
                        parts=tuple(parts),
                        duration_seconds=duration,
                        split_reason=split_reason,
                        source_created_at=prepared.source_created_at,
                    )
            except (MediaPreparationError, PreparationInterrupted):
                raise
            except Exception as exc:
                raise MediaPreparationError(
                    MediaPreparationReason.media_split_failed,
                ) from exc
            try:
                yield batch
            finally:
                for part_stream in part_streams:
                    part_stream.close()


@contextmanager
def prepare_yandex_media_file(
    *,
    stream: BinaryIO,
    original_filename: str,
    mime_type: str,
    byte_count: int,
    max_output_bytes: int,
    media_clip_start_seconds: int | None = None,
    media_clip_end_seconds: int | None = None,
    runner: Callable[..., object] = subprocess.run,
    temporary_directory: str | None = None,
    probe_source_creation_time: bool = False,
    duration_warning_seconds: int = 14400,
    max_duration_seconds: int = 43200,
    long_duration_confirmed: bool = False,
    confirmed_source_duration_seconds: float | None = None,
) -> Iterator[PreparedMediaBatch]:
    """Normalize one source to the Yandex v3 OGG/Opus async-file contract."""
    runner = controlled_runner(runner)
    del mime_type, byte_count
    with TemporaryDirectory(prefix="studio-yandex-", dir=temporary_directory) as temp_dir:
        root = Path(temp_dir)
        source_path = root / f"source{_safe_input_suffix(original_filename)}"
        output_path = root / "prepared-audio.ogg"
        _copy_input(stream, source_path)
        source_created_at = (
            _probe_source_creation_time(runner, source_path)
            if probe_source_creation_time
            else None
        )
        source_duration = _probe_duration_seconds(runner, source_path)
        _validate_whole_source_duration(source_duration, max_duration_seconds, duration_warning_seconds,
            long_duration_confirmed and (confirmed_source_duration_seconds is None
                or round(source_duration, 3) == confirmed_source_duration_seconds))
        clip_requested = media_clip_start_seconds is not None or media_clip_end_seconds is not None
        start, end = (0.0, source_duration)
        if clip_requested:
            start, end = _validated_manual_clip_bounds(
                start_seconds=media_clip_start_seconds,
                end_seconds=media_clip_end_seconds,
                source_duration_seconds=source_duration,
            )
        duration = end - start
        hard_limit = min(int(max_duration_seconds), YANDEX_MAX_DURATION_SECONDS)
        if duration > hard_limit:
            raise MediaPreparationError(MediaPreparationReason.media_duration_too_long)
        command = [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(source_path),
            "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "48000",
            "-c:a", "libopus", "-b:a", YANDEX_AUDIO_BITRATE, str(output_path),
        ]
        try:
            runner(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=FFMPEG_VIDEO_EXTRACTION_TIMEOUT_SECONDS)
        except FileNotFoundError as exc:
            raise MediaPreparationError(MediaPreparationReason.ffmpeg_unavailable) from exc
        except subprocess.TimeoutExpired as exc:
            raise MediaPreparationError(MediaPreparationReason.media_preparation_timeout) from exc
        except (subprocess.CalledProcessError, OSError) as exc:
            raise MediaPreparationError(MediaPreparationReason.media_preparation_failed) from exc
        size = _validated_output_size(output_path, min(max_output_bytes, YANDEX_MAX_BYTES))
        prepared_stream = output_path.open("rb")
        try:
            yield PreparedMediaBatch(
                parts=(PreparedMediaInput(
                    filename=f"{_safe_stem(original_filename)}.ogg",
                    mime_type="audio/ogg",
                    byte_count=size,
                    stream=prepared_stream,
                    audio_extracted=True,
                    duration_seconds=duration,
                ),),
                duration_seconds=duration,
                source_created_at=source_created_at,
            )
        finally:
            prepared_stream.close()


def _copy_input(stream: BinaryIO, destination: Path) -> None:
    try:
        stream.seek(0)
        copied = 0
        report_work("source_copy", 0, None, "bytes")
        with destination.open("wb") as target:
            while True:
                check_preparation_control()
                chunk = stream.read(_COPY_CHUNK_SIZE)
                if not chunk:
                    break
                target.write(chunk)
                copied += len(chunk)
                report_work("source_copy", copied, None, "bytes")
    except PreparationInterrupted:
        raise
    except Exception as exc:
        raise MediaPreparationError(
            MediaPreparationReason.media_preparation_failed,
        ) from exc


def _validate_whole_source_duration(duration: float, maximum: int, warning: int, confirmed: bool) -> None:
    # Product limits apply to the original source, before clipping or internal
    # provider splitting. A short clip cannot disguise an oversized source.
    if duration > maximum:
        raise MediaPreparationError(MediaPreparationReason.media_duration_too_long)
    if duration > warning and not confirmed:
        raise MediaPreparationError(MediaPreparationReason.media_duration_confirmation_required, duration_seconds=duration)


def _validated_manual_clip_bounds(
    *,
    start_seconds: int | None,
    end_seconds: int | None,
    source_duration_seconds: float,
) -> tuple[float, float]:
    start = float(start_seconds or 0)
    end = float(end_seconds) if end_seconds is not None else source_duration_seconds
    if (
        start < 0
        or end <= start
        or start >= source_duration_seconds
        or end > source_duration_seconds
    ):
        raise MediaPreparationError(
            MediaPreparationReason.media_clip_out_of_bounds,
        )
    return start, end


def _create_manual_clip(
    *,
    runner: Callable[..., object],
    prepared_path: Path,
    output_path: Path,
    start_seconds: float,
    duration_seconds: float,
    max_output_bytes: int,
) -> int:
    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-xerror",
        "-y",
        "-ss",
        f"{start_seconds:.3f}",
        "-t",
        f"{duration_seconds:.3f}",
        "-i",
        str(prepared_path),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-c:a",
        "aac",
        "-b:a",
        ELEVENLABS_PART_AUDIO_BITRATE,
        str(output_path),
    ]
    try:
        runner(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=FFMPEG_PART_EXTRACTION_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise MediaPreparationError(MediaPreparationReason.ffmpeg_unavailable) from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaPreparationError(
            MediaPreparationReason.media_preparation_timeout,
        ) from exc
    except (subprocess.CalledProcessError, OSError) as exc:
        raise MediaPreparationError(
            MediaPreparationReason.media_preparation_failed,
        ) from exc
    return _validated_output_size(output_path, max_output_bytes)


def _run_ffmpeg(
    runner: Callable[..., object],
    input_path: Path,
    output_path: Path,
) -> None:
    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0:a:0",
        "-vn",
        "-c:a",
        "aac",
        "-b:a",
        FFMPEG_AUDIO_BITRATE,
        str(output_path),
    ]
    try:
        runner(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=FFMPEG_VIDEO_EXTRACTION_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise MediaPreparationError(
            MediaPreparationReason.ffmpeg_unavailable,
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaPreparationError(
            MediaPreparationReason.media_preparation_timeout,
        ) from exc
    except (subprocess.CalledProcessError, OSError) as exc:
        raise MediaPreparationError(
            MediaPreparationReason.media_preparation_failed,
        ) from exc


def _validate_elevenlabs_prepared_audio(path: Path, mime_type: str, runner: Callable[..., object]) -> None:
    """Validate the actual full input before clipping, splitting or any STT call."""
    try:
        actual = probe_media(path, runner=runner)
        declared_containers = {
            "audio/mpeg": {"mp3"}, "audio/mp3": {"mp3"},
            "audio/wav": {"wav"}, "audio/x-wav": {"wav"}, "audio/wave": {"wav"},
            "audio/flac": {"flac"}, "audio/x-flac": {"flac"},
            "audio/ogg": {"ogg"}, "application/ogg": {"ogg"},
            "audio/mp4": {"mov", "mp4", "m4a"}, "audio/x-m4a": {"mov", "mp4", "m4a"},
            "audio/aac": {"aac"}, "audio/webm": {"matroska", "webm"},
        }.get(mime_type.split(";", 1)[0].strip().lower())
        if declared_containers and not declared_containers.intersection(actual.format_name.split(",")):
            raise MediaPreparationError(MediaPreparationReason.media_preparation_failed)
        verify_media_integrity(path, runner=runner)
    except AudioPreparationError as exc:
        reason = MediaPreparationReason.ffmpeg_unavailable if exc.reason is AudioPreparationReason.probe_unavailable else MediaPreparationReason.media_preparation_failed
        raise MediaPreparationError(reason) from exc


def _probe_duration_seconds(
    runner: Callable[..., object],
    prepared_path: Path,
) -> float:
    report_work("media_probe")
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(prepared_path),
    ]
    try:
        completed = runner(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=FFPROBE_TIMEOUT_SECONDS,
        )
        duration = float(str(getattr(completed, "stdout", "") or "").strip())
    except FileNotFoundError as exc:
        raise MediaPreparationError(MediaPreparationReason.ffmpeg_unavailable) from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaPreparationError(
            MediaPreparationReason.media_preparation_timeout,
        ) from exc
    except (subprocess.CalledProcessError, OSError, TypeError, ValueError) as exc:
        raise MediaPreparationError(
            MediaPreparationReason.media_duration_unavailable,
        ) from exc
    if not isfinite(duration) or duration <= 0:
        raise MediaPreparationError(
            MediaPreparationReason.media_duration_unavailable,
        )
    return duration


def _probe_source_creation_time(
    runner: Callable[..., object],
    source_path: Path,
) -> datetime | None:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format_tags=creation_time:stream_tags=creation_time",
        "-of",
        "json",
        str(source_path),
    ]
    try:
        completed = runner(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=FFPROBE_TIMEOUT_SECONDS,
        )
        payload = json.loads(str(getattr(completed, "stdout", "") or ""))
    except FileNotFoundError as exc:
        raise MediaPreparationError(MediaPreparationReason.ffmpeg_unavailable) from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaPreparationError(MediaPreparationReason.media_preparation_timeout) from exc
    except (subprocess.CalledProcessError, OSError):
        return None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    candidates: list[object] = []
    if isinstance(payload, dict):
        format_payload = payload.get("format")
        if isinstance(format_payload, dict) and isinstance(format_payload.get("tags"), dict):
            candidates.append(format_payload["tags"].get("creation_time"))
        streams = payload.get("streams")
        if isinstance(streams, list):
            for stream_payload in streams:
                if isinstance(stream_payload, dict) and isinstance(stream_payload.get("tags"), dict):
                    candidates.append(stream_payload["tags"].get("creation_time"))
    for candidate in candidates:
        parsed = parse_authoritative_source_created_at(candidate if isinstance(candidate, str) else None)
        if parsed is not None:
            return parsed
    return None


def _split_reason(
    size_bytes: int, duration_seconds: float, *, prefer_whole_recording: bool = False,
) -> str | None:
    if (
        prefer_whole_recording
        and size_bytes <= ELEVENLABS_WHOLE_MAX_BYTES
        and duration_seconds <= ELEVENLABS_WHOLE_MAX_DURATION_SECONDS
    ):
        return None
    size_exceeded = size_bytes > ELEVENLABS_PART_MAX_BYTES
    duration_exceeded = duration_seconds > ELEVENLABS_PART_TARGET_DURATION_SECONDS
    if size_exceeded and duration_exceeded:
        return "size_and_duration"
    if size_exceeded:
        return "size"
    if duration_exceeded:
        return "duration"
    return None


def _create_split_parts(
    *,
    runner: Callable[..., object],
    prepared_path: Path,
    root: Path,
    prepared_size: int,
    duration_seconds: float,
    max_total_bytes: int,
) -> list[tuple[Path, float, float, int]]:
    size_target_duration = (
        duration_seconds
        * (ELEVENLABS_PART_TARGET_BYTES / prepared_size)
        * 0.92
    )
    target_duration = max(
        ELEVENLABS_PART_MIN_DURATION_SECONDS,
        min(ELEVENLABS_PART_TARGET_DURATION_SECONDS, size_target_duration),
    )
    estimated_parts = ceil(
        max(1.0, duration_seconds - ELEVENLABS_PART_OVERLAP_SECONDS)
        / max(0.25, target_duration - ELEVENLABS_PART_OVERLAP_SECONDS)
    )
    if estimated_parts > ELEVENLABS_MAX_PARTS:
        raise MediaPreparationError(MediaPreparationReason.media_split_failed)

    specs: list[tuple[Path, float, float, int]] = []
    total_part_bytes = 0
    start = 0.0
    while start < duration_seconds - 0.01:
        if len(specs) >= ELEVENLABS_MAX_PARTS:
            raise MediaPreparationError(MediaPreparationReason.media_split_failed)
        remaining = duration_seconds - start
        part_duration = min(target_duration, remaining)
        part_path = root / f"part-{len(specs) + 1:03d}.m4a"
        part_size = _create_bounded_part(
            runner=runner,
            prepared_path=prepared_path,
            output_path=part_path,
            start_seconds=start,
            duration_seconds=part_duration,
        )
        total_part_bytes += part_size
        if total_part_bytes > max_total_bytes:
            raise MediaPreparationError(
                MediaPreparationReason.prepared_media_too_large,
            )
        specs.append((part_path, start, part_duration, part_size))
        if start + part_duration >= duration_seconds - 0.01:
            break
        overlap = min(
            ELEVENLABS_PART_OVERLAP_SECONDS,
            max(0.0, part_duration / 4),
        )
        next_start = start + part_duration - overlap
        if next_start <= start + 0.25:
            raise MediaPreparationError(MediaPreparationReason.media_split_failed)
        start = next_start
    if not specs:
        raise MediaPreparationError(MediaPreparationReason.media_split_failed)
    return specs


def _create_bounded_part(
    *,
    runner: Callable[..., object],
    prepared_path: Path,
    output_path: Path,
    start_seconds: float,
    duration_seconds: float,
) -> int:
    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{start_seconds:.3f}",
        "-t",
        f"{duration_seconds:.3f}",
        "-i",
        str(prepared_path),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-c:a",
        "aac",
        "-b:a",
        ELEVENLABS_PART_AUDIO_BITRATE,
        str(output_path),
    ]
    try:
        runner(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=FFMPEG_PART_EXTRACTION_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise MediaPreparationError(MediaPreparationReason.ffmpeg_unavailable) from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaPreparationError(
            MediaPreparationReason.media_preparation_timeout,
        ) from exc
    except (subprocess.CalledProcessError, OSError) as exc:
        raise MediaPreparationError(MediaPreparationReason.media_split_failed) from exc
    try:
        return _validated_output_size(output_path, ELEVENLABS_PART_MAX_BYTES)
    except MediaPreparationError as exc:
        if exc.reason is MediaPreparationReason.prepared_media_too_large:
            raise MediaPreparationError(
                MediaPreparationReason.media_part_too_large,
            ) from exc
        raise


def _validated_output_size(output_path: Path, max_output_bytes: int) -> int:
    try:
        size = output_path.stat().st_size
    except OSError as exc:
        raise MediaPreparationError(
            MediaPreparationReason.media_preparation_failed,
        ) from exc
    if size <= 0:
        raise MediaPreparationError(MediaPreparationReason.media_preparation_failed)
    if size > max_output_bytes:
        raise MediaPreparationError(
            MediaPreparationReason.prepared_media_too_large,
        )
    return size


def _safe_input_suffix(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix) else ".media"


def _safe_stem(filename: str) -> str:
    stem = Path(filename).stem.strip().strip(".")
    return stem or "prepared-audio"
