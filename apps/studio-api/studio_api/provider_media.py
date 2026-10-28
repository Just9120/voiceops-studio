"""Whole-file preparation for new batch APIs; never split speakers for progress."""
from contextlib import contextmanager
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from .media_preparation import (PreparedMediaBatch, PreparedMediaInput, MediaPreparationError, MediaPreparationReason,
    _copy_input, _probe_duration_seconds, _probe_source_creation_time, _safe_input_suffix,
    _validated_manual_clip_bounds, _validated_output_size, _validate_whole_source_duration)
from .preparation_control import controlled_runner


def whole_file_preparer(provider, *, diarize=False):
    @contextmanager
    def prepare(*, stream, original_filename, mime_type, byte_count, max_output_bytes,
                media_clip_start_seconds=None, media_clip_end_seconds=None, runner=subprocess.run,
                temporary_directory=None, probe_source_creation_time=False, duration_warning_seconds=14400,
                max_duration_seconds=43200, long_duration_confirmed=False, confirmed_source_duration_seconds=None):
        run = controlled_runner(runner)
        with TemporaryDirectory(prefix="studio-provider-", dir=temporary_directory) as temporary:
            root = Path(temporary)
            source = root / ("source" + _safe_input_suffix(original_filename))
            _copy_input(stream, source)
            creation = _probe_source_creation_time(run, source) if probe_source_creation_time else None
            source_duration = _probe_duration_seconds(run, source)
            _validate_whole_source_duration(source_duration, max_duration_seconds, duration_warning_seconds,
                long_duration_confirmed and (confirmed_source_duration_seconds is None or round(source_duration, 3) == confirmed_source_duration_seconds))
            start, end = _validated_manual_clip_bounds(start_seconds=media_clip_start_seconds, end_seconds=media_clip_end_seconds, source_duration_seconds=source_duration)
            duration = end - start
            if provider == "gemini" and duration > (1800 if diarize else 3600):
                raise MediaPreparationError(MediaPreparationReason.media_duration_too_long)
            extension = "mp3" if provider == "tbank" else "flac"
            target = root / f"prepared.{extension}"
            maximum = min(max_output_bytes, (24 if provider == "tbank" else 256) * 1024 * 1024)
            command = ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-xerror", "-y",
                "-ss", str(start), "-t", str(duration), "-i", str(source), "-map", "0:a:0", "-vn"]
            if provider == "tbank": command += ["-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "64k"]
            else: command += ["-c:a", "flac", "-sample_fmt", "s16"]
            command += ["-threads", "2", "-fs", str(maximum + 65536), str(target)]
            try:
                run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1800)
            except FileNotFoundError as exc:
                raise MediaPreparationError(MediaPreparationReason.ffmpeg_unavailable) from exc
            except subprocess.TimeoutExpired as exc:
                raise MediaPreparationError(MediaPreparationReason.media_preparation_timeout) from exc
            except (subprocess.CalledProcessError, OSError) as exc:
                raise MediaPreparationError(MediaPreparationReason.media_preparation_failed) from exc
            size = _validated_output_size(target, maximum)
            # A size-limited FFmpeg output is never a successful truncated transcript input.
            rendered_duration = _probe_duration_seconds(run, target)
            if abs(rendered_duration - duration) > 0.5:
                raise MediaPreparationError(MediaPreparationReason.prepared_media_too_large)
            with target.open("rb") as prepared:
                yield PreparedMediaBatch(parts=(PreparedMediaInput(filename=target.name,
                    mime_type="audio/mpeg" if extension == "mp3" else "audio/flac", byte_count=size, stream=prepared,
                    audio_extracted=True, duration_seconds=duration, timeline_offset_seconds=start),),
                    duration_seconds=duration, source_created_at=creation)
    return prepare
