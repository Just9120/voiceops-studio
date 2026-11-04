from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


@pytest.fixture(autouse=True)
def fake_integrity_for_split_unit_fixtures(monkeypatch):
    # These split/clip unit cases intentionally use fake byte streams. The
    # actual probe/decode contract is covered by transcription_media_integrity.
    from studio_api import media_preparation
    monkeypatch.setattr(media_preparation, "_validate_elevenlabs_prepared_audio", lambda *args: None)


def test_audio_input_is_passed_through_without_ffmpeg():
    from studio_api.media_preparation import prepare_elevenlabs_media_input

    source = BytesIO(b"audio-bytes")

    def unexpected_runner(*args, **kwargs):
        raise AssertionError("ffmpeg must not run for an audio source")

    with prepare_elevenlabs_media_input(
        stream=source,
        original_filename="recording.mp3",
        mime_type="audio/mpeg",
        byte_count=11,
        max_output_bytes=100,
        runner=unexpected_runner,
    ) as prepared:
        assert prepared.stream is source
        assert prepared.filename == "recording.mp3"
        assert prepared.mime_type == "audio/mpeg"
        assert prepared.byte_count == 11
        assert prepared.audio_extracted is False

    assert source.closed is False


def test_audio_creation_time_is_probed_from_authoritative_embedded_metadata(tmp_path):
    from studio_api.media_preparation import prepare_elevenlabs_media_input

    source = BytesIO(b"audio-with-metadata")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        assert command[0] == "ffprobe"
        assert Path(command[-1]).read_bytes() == b"audio-with-metadata"
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"format":{"tags":{"creation_time":"2025-12-03T12:22:32.123Z"}},"streams":[]}',
        )

    with prepare_elevenlabs_media_input(
        stream=source,
        original_filename="recording.mp3",
        mime_type="audio/mpeg",
        byte_count=len(b"audio-with-metadata"),
        max_output_bytes=100,
        runner=runner,
        temporary_directory=str(tmp_path),
        probe_source_creation_time=True,
    ) as prepared:
        assert prepared.source_created_at == datetime(
            2025, 12, 3, 12, 22, 32, 123000, tzinfo=timezone.utc
        )
        assert prepared.stream is source
        assert prepared.stream.read() == b"audio-with-metadata"

    assert len(calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        '{"format":{"tags":{"creation_time":"2025-12-03 12:22:32"}}}',
        '{"format":{"tags":{"creation_time":"not-a-date"}}}',
        "not-json",
        "{}",
    ],
)
def test_unverified_embedded_creation_time_remains_unknown(tmp_path, payload):
    from studio_api.media_preparation import prepare_elevenlabs_media_input

    source = BytesIO(b"audio")

    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=payload)

    with prepare_elevenlabs_media_input(
        stream=source,
        original_filename="recording.mp3",
        mime_type="audio/mpeg",
        byte_count=5,
        max_output_bytes=100,
        runner=runner,
        temporary_directory=str(tmp_path),
        probe_source_creation_time=True,
    ) as prepared:
        assert prepared.source_created_at is None


def test_video_input_is_extracted_to_bounded_aac_m4a_and_cleaned(tmp_path):
    from studio_api.media_preparation import (
        FFMPEG_VIDEO_EXTRACTION_TIMEOUT_SECONDS,
        prepare_elevenlabs_media_input,
    )

    calls = []
    source = BytesIO(b"synthetic-video")

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        input_path = Path(command[command.index("-i") + 1])
        output_path = Path(command[-1])
        assert input_path.read_bytes() == b"synthetic-video"
        output_path.write_bytes(b"prepared-audio")
        return subprocess.CompletedProcess(command, 0)

    with prepare_elevenlabs_media_input(
        stream=source,
        original_filename="private meeting.MP4",
        mime_type="video/mp4; charset=binary",
        byte_count=15,
        max_output_bytes=100,
        runner=runner,
        temporary_directory=str(tmp_path),
    ) as prepared:
        assert prepared.filename == "private meeting.m4a"
        assert prepared.mime_type == "audio/mp4"
        assert prepared.byte_count == len(b"prepared-audio")
        assert prepared.audio_extracted is True
        assert prepared.stream.read() == b"prepared-audio"
        command, kwargs = calls[0]
        assert command[:7] == [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
        ]
        assert command[command.index("-map") + 1] == "0:a:0"
        assert ["-vn", "-c:a", "aac", "-b:a", "192k"] == command[10:15]
        assert kwargs == {
            "check": True,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "timeout": FFMPEG_VIDEO_EXTRACTION_TIMEOUT_SECONDS,
        }
        created_paths = [Path(command[command.index("-i") + 1]), Path(command[-1])]
        assert all(path.exists() for path in created_paths)
        assert "private meeting" not in repr(prepared)

    assert all(not path.exists() for path in created_paths)


@pytest.mark.parametrize(
    "failure, expected_reason",
    [
        (FileNotFoundError("private path"), "ffmpeg_unavailable"),
        (
            subprocess.TimeoutExpired(["ffmpeg"], timeout=1),
            "media_preparation_timeout",
        ),
        (
            subprocess.CalledProcessError(1, ["ffmpeg"], stderr=b"private data"),
            "media_preparation_failed",
        ),
    ],
)
def test_video_extraction_normalizes_tool_failures(
    tmp_path,
    failure,
    expected_reason,
):
    from studio_api.media_preparation import (
        MediaPreparationError,
        prepare_elevenlabs_media_input,
    )

    def runner(*args, **kwargs):
        raise failure

    with pytest.raises(MediaPreparationError, match=expected_reason) as exc:
        with prepare_elevenlabs_media_input(
            stream=BytesIO(b"video"),
            original_filename="private.mp4",
            mime_type="video/mp4",
            byte_count=5,
            max_output_bytes=100,
            runner=runner,
            temporary_directory=str(tmp_path),
        ):
            pass

    assert "private" not in str(exc.value)


def test_video_extraction_rejects_missing_empty_and_oversized_outputs(tmp_path):
    from studio_api.media_preparation import (
        MediaPreparationError,
        prepare_elevenlabs_media_input,
    )

    outputs = [None, b"", b"too-large"]
    reasons = [
        "media_preparation_failed",
        "media_preparation_failed",
        "prepared_media_too_large",
    ]

    for output, reason in zip(outputs, reasons):
        def runner(command, **kwargs):
            if output is not None:
                Path(command[-1]).write_bytes(output)

        with pytest.raises(MediaPreparationError, match=reason):
            with prepare_elevenlabs_media_input(
                stream=BytesIO(b"video"),
                original_filename="clip.mp4",
                mime_type="video/mp4",
                byte_count=5,
                max_output_bytes=5,
                runner=runner,
                temporary_directory=str(tmp_path),
            ):
                pass


def test_prepared_context_preserves_caller_exceptions(tmp_path):
    from studio_api.media_preparation import prepare_elevenlabs_media_input

    sentinel = RuntimeError("caller-owned-error")

    def runner(command, **kwargs):
        Path(command[-1]).write_bytes(b"prepared")

    with pytest.raises(RuntimeError) as exc:
        with prepare_elevenlabs_media_input(
            stream=BytesIO(b"video"),
            original_filename="clip.mp4",
            mime_type="video/mp4",
            byte_count=5,
            max_output_bytes=100,
            runner=runner,
            temporary_directory=str(tmp_path),
        ):
            raise sentinel

    assert exc.value is sentinel


def test_small_media_is_probed_but_not_split(tmp_path):
    from studio_api.media_preparation import prepare_elevenlabs_media_parts

    source = BytesIO(b"small-audio")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        assert command[0] == "ffprobe"
        return subprocess.CompletedProcess(command, 0, stdout="120.5\n")

    with prepare_elevenlabs_media_parts(
        stream=source,
        original_filename="private.mp3",
        mime_type="audio/mpeg",
        byte_count=11,
        max_output_bytes=100,
        runner=runner,
        temporary_directory=str(tmp_path),
    ) as batch:
        assert batch.duration_seconds == 120.5
        assert batch.split_reason is None
        assert len(batch.parts) == 1
        assert batch.parts[0].stream is source
        assert batch.parts[0].duration_seconds == 120.5
        assert "private" not in repr(batch)
        assert calls[0][1] == {
            "check": True,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.DEVNULL,
            "text": True,
            "timeout": 30,
        }

    assert source.closed is False


@pytest.mark.parametrize("mime_type", ["audio/mpeg", "video/mp4"])
@pytest.mark.parametrize("clip", [False, True])
def test_diarized_recording_avoids_size_and_duration_fragmentation(tmp_path, monkeypatch, mime_type, clip):
    from studio_api import media_preparation as media

    monkeypatch.setattr(media, "ELEVENLABS_PART_MAX_BYTES", 8)
    commands = []

    def runner(command, **kwargs):
        commands.append(command)
        if command[0] == "ffprobe":
            duration = 1880 if clip and Path(command[-1]).name in {"manual-clip.m4a", "prepared-source.m4a"} else 4000
            return subprocess.CompletedProcess(command, 0, stdout=str(duration))
        assert command[0] == "ffmpeg"
        assert not Path(command[-1]).name.startswith("part-")
        Path(command[-1]).write_bytes(b"prepared-audio")
        return subprocess.CompletedProcess(command, 0)

    with media.prepare_elevenlabs_media_parts(
        stream=BytesIO(b"synthetic-audio"), original_filename="meeting.mp4",
        mime_type=mime_type, byte_count=15, max_output_bytes=100,
        prefer_whole_recording=True, runner=runner, temporary_directory=str(tmp_path),
        media_clip_start_seconds=120 if clip else None,
        media_clip_end_seconds=2000 if clip else None,
    ) as batch:
        assert len(batch.parts) == 1 and batch.split_reason is None
        assert batch.parts[0].timeline_offset_seconds == 0
        assert batch.parts[0].duration_seconds == (1880 if clip else 4000)
        assert batch.parts[0].stream.read() in (b"synthetic-audio", b"prepared-audio")
        if clip:
            command = next(c for c in commands if Path(c[-1]).name == "manual-clip.m4a" and c[0] == "ffmpeg")
            assert command[command.index("-ss") + 1] == "120.000"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "size,duration,expected",
    [(26 * 1024 * 1024, 4000, None), (4_999_999_999, 36000, None),
     (5_000_000_000, 10, "size"), (10, 36000.001, "duration")],
)
def test_whole_recording_preference_respects_provider_limits(size, duration, expected):
    from studio_api.media_preparation import _split_reason
    assert _split_reason(size, duration, prefer_whole_recording=True) == expected


def test_diarized_recording_beyond_single_request_duration_uses_bounded_parts(tmp_path):
    from studio_api.media_preparation import prepare_elevenlabs_media_parts

    def runner(command, **kwargs):
        if command[0] == "ffprobe":
            return subprocess.CompletedProcess(command, 0, stdout="36001")
        Path(command[-1]).write_bytes(b"part")
        return subprocess.CompletedProcess(command, 0)

    with prepare_elevenlabs_media_parts(
        stream=BytesIO(b"audio"), original_filename="meeting.mp3", mime_type="audio/mpeg",
        byte_count=5, max_output_bytes=1000, prefer_whole_recording=True,
        long_duration_confirmed=True, runner=runner, temporary_directory=str(tmp_path),
    ) as batch:
        assert batch.split_reason == "duration" and len(batch.parts) > 1
        assert max(part.duration_seconds for part in batch.parts) <= 1320
        assert batch.parts[-1].timeline_offset_seconds + batch.parts[-1].duration_seconds == pytest.approx(36001)
    assert list(tmp_path.iterdir()) == []


def test_whole_recording_preference_cannot_bypass_project_byte_limit(tmp_path):
    from studio_api.media_preparation import MediaPreparationError, prepare_elevenlabs_media_parts

    def unexpected_runner(*args, **kwargs):
        raise AssertionError("oversized input must fail before probe/provider preparation")

    with pytest.raises(MediaPreparationError, match="prepared_media_too_large"):
        with prepare_elevenlabs_media_parts(
            stream=BytesIO(b"oversized"), original_filename="meeting.mp3", mime_type="audio/mpeg",
            byte_count=9, max_output_bytes=5, prefer_whole_recording=True,
            runner=unexpected_runner, temporary_directory=str(tmp_path),
        ):
            pytest.fail("project limit was bypassed")


def test_video_extraction_flows_into_probe_and_single_prepared_part(tmp_path):
    from studio_api.media_preparation import prepare_elevenlabs_media_parts

    commands = []

    def runner(command, **kwargs):
        commands.append(command)
        if command[0] == "ffprobe":
            return subprocess.CompletedProcess(command, 0, stdout="30")
        Path(command[-1]).write_bytes(b"extracted-audio")
        return subprocess.CompletedProcess(command, 0)

    with prepare_elevenlabs_media_parts(
        stream=BytesIO(b"video"),
        original_filename="private.mp4",
        mime_type="video/mp4",
        byte_count=5,
        max_output_bytes=100,
        runner=runner,
        temporary_directory=str(tmp_path),
    ) as batch:
        assert [command[0] for command in commands] == ["ffprobe", "ffmpeg", "ffprobe"]
        assert len(batch.parts) == 1
        assert batch.parts[0].audio_extracted is True
        assert batch.parts[0].filename == "private.m4a"
        assert batch.parts[0].mime_type == "audio/mp4"
        assert batch.parts[0].stream.read() == b"extracted-audio"


@pytest.mark.parametrize(
    "start_seconds,end_seconds,expected_start,expected_duration",
    [
        (0, 610, "0.000", "610.000"),
        (610, None, "610.000", "590.000"),
    ],
)
def test_manual_clip_is_created_before_provider_parts(
    tmp_path,
    start_seconds,
    end_seconds,
    expected_start,
    expected_duration,
):
    from studio_api.media_preparation import prepare_elevenlabs_media_parts

    commands = []
    probe_durations = iter(("1200", expected_duration))

    def runner(command, **kwargs):
        commands.append(command)
        if command[0] == "ffprobe":
            return subprocess.CompletedProcess(command, 0, stdout=next(probe_durations))
        Path(command[-1]).write_bytes(b"manual-clip")
        return subprocess.CompletedProcess(command, 0)

    with prepare_elevenlabs_media_parts(
        stream=BytesIO(b"full-source"),
        original_filename="private.mp3",
        mime_type="audio/mpeg",
        byte_count=11,
        max_output_bytes=100,
        media_clip_start_seconds=start_seconds,
        media_clip_end_seconds=end_seconds,
        runner=runner,
        temporary_directory=str(tmp_path),
    ) as batch:
        assert [command[0] for command in commands] == ["ffprobe", "ffmpeg", "ffprobe"]
        clip_command = commands[1]
        assert clip_command[clip_command.index("-ss") + 1] == expected_start
        assert clip_command[clip_command.index("-t") + 1] == expected_duration
        assert batch.duration_seconds == float(expected_duration)
        assert len(batch.parts) == 1
        assert batch.parts[0].mime_type == "audio/mp4"
        assert batch.parts[0].stream.read() == b"manual-clip"


@pytest.mark.parametrize(
    "start_seconds,end_seconds",
    [(1200, None), (1201, None), (0, 1201), (610, 610)],
)
def test_manual_clip_outside_probed_duration_fails_before_ffmpeg(
    tmp_path,
    start_seconds,
    end_seconds,
):
    from studio_api.media_preparation import (
        MediaPreparationError,
        prepare_elevenlabs_media_parts,
    )

    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        assert command[0] == "ffprobe"
        return subprocess.CompletedProcess(command, 0, stdout="1200")

    with pytest.raises(MediaPreparationError, match="media_clip_out_of_bounds"):
        with prepare_elevenlabs_media_parts(
            stream=BytesIO(b"full-source"),
            original_filename="private.mp3",
            mime_type="audio/mpeg",
            byte_count=11,
            max_output_bytes=100,
            media_clip_start_seconds=start_seconds,
            media_clip_end_seconds=end_seconds,
            runner=runner,
            temporary_directory=str(tmp_path),
        ):
            pass

    assert len(calls) == 1


def test_long_media_is_split_in_deterministic_overlapping_order_and_cleaned(tmp_path):
    from studio_api.media_preparation import prepare_elevenlabs_media_parts

    commands = []

    def runner(command, **kwargs):
        commands.append(command)
        if command[0] == "ffprobe":
            return subprocess.CompletedProcess(command, 0, stdout="1325\n")
        assert command[0] == "ffmpeg"
        Path(command[-1]).write_bytes(f"part-{len(commands)}".encode())
        return subprocess.CompletedProcess(command, 0)

    with prepare_elevenlabs_media_parts(
        stream=BytesIO(b"long-audio"),
        original_filename="private recording.wav",
        mime_type="audio/wav",
        byte_count=10,
        max_output_bytes=100,
        runner=runner,
        temporary_directory=str(tmp_path),
    ) as batch:
        assert batch.split_reason == "duration"
        assert batch.duration_seconds == 1325
        assert len(batch.parts) == 2
        first, second = batch.parts
        assert (first.part_index, first.part_count) == (1, 2)
        assert (second.part_index, second.part_count) == (2, 2)
        assert first.timeline_offset_seconds == 0
        assert second.timeline_offset_seconds == 1318
        assert first.duration_seconds == 1320
        assert second.duration_seconds == 7
        assert first.filename.endswith("part 001.m4a")
        assert second.filename.endswith("part 002.m4a")
        assert first.mime_type == second.mime_type == "audio/mp4"
        assert first.stream.read().startswith(b"part-")
        assert second.stream.read().startswith(b"part-")
        created_paths = [Path(command[-1]) for command in commands if command[0] == "ffmpeg"]
        assert all(path.exists() for path in created_paths)
        first_command, second_command = [command for command in commands if command[0] == "ffmpeg"]
        assert first_command[first_command.index("-ss") + 1] == "0.000"
        assert first_command[first_command.index("-t") + 1] == "1320.000"
        assert second_command[second_command.index("-ss") + 1] == "1318.000"
        assert second_command[second_command.index("-t") + 1] == "7.000"
        audio_options = first_command.index("-ac")
        assert ["-ac", "1", "-c:a", "aac", "-b:a", "96k"] == first_command[audio_options:audio_options + 6]

    assert all(not path.exists() for path in created_paths)
    assert first.stream.closed is True
    assert second.stream.closed is True


@pytest.mark.parametrize("prefer_whole_recording", [False, True])
def test_duration_warning_requires_explicit_confirmation_before_splitting(tmp_path, prefer_whole_recording):
    from studio_api.media_preparation import (
        MediaPreparationError,
        prepare_elevenlabs_media_parts,
    )

    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        assert command[0] == "ffprobe"
        return subprocess.CompletedProcess(command, 0, stdout="150")

    with pytest.raises(
        MediaPreparationError,
        match="media_duration_confirmation_required",
    ):
        with prepare_elevenlabs_media_parts(
            stream=BytesIO(b"audio"),
            original_filename="private.mp3",
            mime_type="audio/mpeg",
            byte_count=5,
            max_output_bytes=100,
            duration_warning_seconds=100,
            max_duration_seconds=200,
            prefer_whole_recording=prefer_whole_recording,
            runner=runner,
            temporary_directory=str(tmp_path),
        ):
            pass

    assert [command[0] for command in calls] == ["ffprobe"]


def test_confirmed_duration_between_warning_and_limit_is_processed(tmp_path):
    from studio_api.media_preparation import prepare_elevenlabs_media_parts

    def runner(command, **kwargs):
        assert command[0] == "ffprobe"
        return subprocess.CompletedProcess(command, 0, stdout="150")

    with prepare_elevenlabs_media_parts(
        stream=BytesIO(b"audio"),
        original_filename="private.mp3",
        mime_type="audio/mpeg",
        byte_count=5,
        max_output_bytes=100,
        duration_warning_seconds=100,
        max_duration_seconds=200,
        long_duration_confirmed=True,
        runner=runner,
        temporary_directory=str(tmp_path),
    ) as batch:
        assert batch.duration_seconds == 150
        assert len(batch.parts) == 1


@pytest.mark.parametrize("prefer_whole_recording", [False, True])
def test_hard_duration_limit_stops_before_part_creation_even_if_confirmed(tmp_path, prefer_whole_recording):
    from studio_api.media_preparation import (
        MediaPreparationError,
        prepare_elevenlabs_media_parts,
    )

    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        assert command[0] == "ffprobe"
        return subprocess.CompletedProcess(command, 0, stdout="201")

    with pytest.raises(MediaPreparationError, match="media_duration_too_long"):
        with prepare_elevenlabs_media_parts(
            stream=BytesIO(b"audio"),
            original_filename="private.mp3",
            mime_type="audio/mpeg",
            byte_count=5,
            max_output_bytes=100,
            duration_warning_seconds=100,
            max_duration_seconds=200,
            long_duration_confirmed=True,
            prefer_whole_recording=prefer_whole_recording,
            runner=runner,
            temporary_directory=str(tmp_path),
        ):
            pass

    assert [command[0] for command in calls] == ["ffprobe"]


@pytest.mark.parametrize("provider", ["elevenlabs", "yandex"])
@pytest.mark.parametrize("duration", [43201, 14401])
def test_short_final_clip_is_admitted_from_a_long_source_without_long_cost_consent(tmp_path, provider, duration):
    from studio_api.media_preparation import prepare_elevenlabs_media_parts, prepare_yandex_media_file
    calls = []
    def runner(command, **kwargs):
        calls.append(command)
        if command[0] == "ffprobe":
            measured = 30 if Path(command[-1]).name == "manual-clip.m4a" else duration
            return subprocess.CompletedProcess(command, 0, stdout=str(measured))
        Path(command[-1]).write_bytes(b"selected-short-recording")
        return subprocess.CompletedProcess(command, 0)
    preparer = prepare_elevenlabs_media_parts if provider == "elevenlabs" else prepare_yandex_media_file
    with preparer(stream=BytesIO(b"audio"), original_filename="synthetic.mp3", mime_type="audio/mpeg", byte_count=5,
                  max_output_bytes=100, media_clip_start_seconds=0, media_clip_end_seconds=30,
                  runner=runner, temporary_directory=str(tmp_path)) as result:
        assert result.duration_seconds == 30
        assert len(result.parts) == 1
    assert any(call[0] == "ffmpeg" for call in calls)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("provider", ["elevenlabs", "yandex"])
def test_above_four_hours_still_needs_consent_with_a_higher_configured_warning(tmp_path, provider):
    from studio_api.media_preparation import prepare_elevenlabs_media_parts, prepare_yandex_media_file, MediaPreparationError
    preparer = prepare_elevenlabs_media_parts if provider == "elevenlabs" else prepare_yandex_media_file
    def runner(command, **kwargs):
        assert command[0] == "ffprobe", "No conversion or dispatch before consent"
        return subprocess.CompletedProcess(command, 0, stdout="50000")
    with pytest.raises(MediaPreparationError, match="media_duration_confirmation_required"):
        with preparer(stream=BytesIO(b"audio"), original_filename="synthetic.mp3", mime_type="audio/mpeg", byte_count=5,
            max_output_bytes=100, max_duration_seconds=86400, duration_warning_seconds=60000,
            media_clip_start_seconds=100, media_clip_end_seconds=18100, runner=runner, temporary_directory=str(tmp_path)):
            pytest.fail("Final five-hour recording needs consent even when max exceeds twelve hours")


@pytest.mark.parametrize("provider", ["elevenlabs", "yandex"])
def test_changed_source_duration_revokes_previous_quote_consent(tmp_path, provider):
    from studio_api.media_preparation import MediaPreparationError, prepare_elevenlabs_media_parts, prepare_yandex_media_file
    preparer = prepare_elevenlabs_media_parts if provider == "elevenlabs" else prepare_yandex_media_file
    calls = []
    def runner(command, **kwargs):
        calls.append(command)
        assert command[0] == "ffprobe"
        return subprocess.CompletedProcess(command, 0, stdout="19000")
    with pytest.raises(MediaPreparationError, match="media_duration_confirmation_required") as failure:
        with preparer(stream=BytesIO(b"audio"), original_filename="synthetic.mp3", mime_type="audio/mpeg", byte_count=5,
            max_output_bytes=100, long_duration_confirmed=True, confirmed_source_duration_seconds=18000,
            runner=runner, temporary_directory=str(tmp_path)):
            pass
    assert failure.value.duration_seconds == 19000
    assert len(calls) == 1 and not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "probe_result, expected_reason",
    [
        (FileNotFoundError("private"), "ffmpeg_unavailable"),
        (subprocess.TimeoutExpired(["ffprobe"], timeout=1), "media_preparation_timeout"),
        (subprocess.CalledProcessError(1, ["ffprobe"]), "media_duration_unavailable"),
        (subprocess.CompletedProcess(["ffprobe"], 0, stdout="not-a-duration"), "media_duration_unavailable"),
        (subprocess.CompletedProcess(["ffprobe"], 0, stdout="0"), "media_duration_unavailable"),
    ],
)
def test_media_probe_failures_are_normalized(tmp_path, probe_result, expected_reason):
    from studio_api.media_preparation import (
        MediaPreparationError,
        prepare_elevenlabs_media_parts,
    )

    def runner(*args, **kwargs):
        if isinstance(probe_result, Exception):
            raise probe_result
        return probe_result

    with pytest.raises(MediaPreparationError, match=expected_reason) as exc:
        with prepare_elevenlabs_media_parts(
            stream=BytesIO(b"audio"),
            original_filename="private.mp3",
            mime_type="audio/mpeg",
            byte_count=5,
            max_output_bytes=100,
            runner=runner,
            temporary_directory=str(tmp_path),
        ):
            pass

    assert "private" not in str(exc.value)


def test_split_part_over_limit_fails_before_provider_use(tmp_path):
    from studio_api.media_preparation import (
        ELEVENLABS_PART_MAX_BYTES,
        MediaPreparationError,
        prepare_elevenlabs_media_parts,
    )

    def runner(command, **kwargs):
        if command[0] == "ffprobe":
            return subprocess.CompletedProcess(command, 0, stdout="1321")
        with Path(command[-1]).open("wb") as output:
            output.truncate(ELEVENLABS_PART_MAX_BYTES + 1)
        return subprocess.CompletedProcess(command, 0)

    with pytest.raises(MediaPreparationError, match="media_part_too_large"):
        with prepare_elevenlabs_media_parts(
            stream=BytesIO(b"audio"),
            original_filename="clip.wav",
            mime_type="audio/wav",
            byte_count=5,
            max_output_bytes=100,
            runner=runner,
            temporary_directory=str(tmp_path),
        ):
            pass


def test_split_policy_uses_both_size_and_duration_boundaries():
    from studio_api.media_preparation import (
        ELEVENLABS_PART_MAX_BYTES,
        ELEVENLABS_PART_TARGET_DURATION_SECONDS,
        _split_reason,
    )

    assert _split_reason(ELEVENLABS_PART_MAX_BYTES, ELEVENLABS_PART_TARGET_DURATION_SECONDS) is None
    assert _split_reason(ELEVENLABS_PART_MAX_BYTES + 1, 1) == "size"
    assert _split_reason(1, ELEVENLABS_PART_TARGET_DURATION_SECONDS + 0.001) == "duration"
    assert _split_reason(ELEVENLABS_PART_MAX_BYTES + 1, ELEVENLABS_PART_TARGET_DURATION_SECONDS + 1) == "size_and_duration"


def test_split_parts_are_bounded_in_aggregate(tmp_path):
    from studio_api.media_preparation import (
        MediaPreparationError,
        prepare_elevenlabs_media_parts,
    )

    def runner(command, **kwargs):
        if command[0] == "ffprobe":
            return subprocess.CompletedProcess(command, 0, stdout="1321")
        Path(command[-1]).write_bytes(b"123456")
        return subprocess.CompletedProcess(command, 0)

    with pytest.raises(MediaPreparationError, match="prepared_media_too_large"):
        with prepare_elevenlabs_media_parts(
            stream=BytesIO(b"audio"),
            original_filename="clip.wav",
            mime_type="audio/wav",
            byte_count=5,
            max_output_bytes=10,
            runner=runner,
            temporary_directory=str(tmp_path),
        ):
            pass


def test_long_video_encodes_only_the_admitted_final_interval(tmp_path):
    from studio_api.media_preparation import prepare_elevenlabs_media_parts
    commands = []
    def runner(command, **kwargs):
        commands.append(command)
        if command[0] == "ffprobe":
            duration = "46800" if Path(command[-1]).name == "source.mp4" else "30"
            return subprocess.CompletedProcess(command, 0, stdout=duration)
        assert command[0] == "ffmpeg"
        assert command[command.index("-ss") + 1] == "3600.000"
        assert command[command.index("-t") + 1] == "30.000"
        Path(command[-1]).write_bytes(b"clip")
        return subprocess.CompletedProcess(command, 0)
    with prepare_elevenlabs_media_parts(stream=BytesIO(b"video"), original_filename="long.mp4", mime_type="video/mp4",
        byte_count=5,max_output_bytes=10,media_clip_start_seconds=3600,media_clip_end_seconds=3630,
        runner=runner,temporary_directory=str(tmp_path)) as batch:
        assert batch.duration_seconds == 30 and batch.parts[0].stream.read() == b"clip"
    assert len([command for command in commands if command[0] == "ffmpeg"]) == 1
    assert list(tmp_path.iterdir()) == []


def test_unselected_over_limit_video_is_rejected_before_audio_extraction(tmp_path):
    from studio_api.media_preparation import MediaPreparationError, prepare_elevenlabs_media_parts
    commands = []
    def runner(command, **kwargs):
        commands.append(command)
        assert command[0] == "ffprobe", "inadmissible full video must not start encoding"
        return subprocess.CompletedProcess(command,0,stdout="46800")
    with pytest.raises(MediaPreparationError, match="media_duration_too_long"):
        with prepare_elevenlabs_media_parts(stream=BytesIO(b"video"),original_filename="long.mp4",mime_type="video/mp4",
            byte_count=5,max_output_bytes=10,runner=runner,temporary_directory=str(tmp_path)):
            pytest.fail("over-limit final recording cannot reach provider preparation")
    assert len(commands) == 1 and list(tmp_path.iterdir()) == []
