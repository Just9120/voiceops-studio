from datetime import datetime, timezone
from pathlib import Path
from subprocess import CompletedProcess
from io import StringIO
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))

from studio_api.audio_preparation import (
    AudioMonoMode,
    AudioOutputFormat,
    AudioPreparationError,
    AudioPreparationReason,
    AudioPreset,
    AudioProbe,
    analyze_silence,
    build_ffmpeg_command,
    build_preview,
    normalize_options,
    probe_media,
    render_output_filename,
    run_processing,
    verify_media_integrity,
)


def options(**overrides):
    payload = {"preset": "processing_only"}
    payload.update(overrides)
    return normalize_options(payload)


def probe(*, channels=2, codec="pcm_s16le", fmt="wav"):
    return AudioProbe(60.0, fmt, codec, 48000, channels, "stereo" if channels == 2 else "mono")


def test_presets_are_effective_and_user_overrides_remain_explicit():
    lecture = normalize_options({"preset": "lecture", "silence_threshold_db": -35})
    assert lecture.preset is AudioPreset.lecture
    assert lecture.output_format is AudioOutputFormat.flac
    assert lecture.mono_mode is AudioMonoMode.mixdown
    assert lecture.silence_enabled is True
    assert lecture.silence_threshold_db == -35


def test_trim_uses_original_concat_timeline_before_silence_processing():
    opts = options(trim_start_seconds=45, trim_end_seconds=90, silence_enabled=True)
    command = build_ffmpeg_command([Path("first.wav"), Path("second.wav")], Path("out.wav"), opts, [probe(), probe()])
    filters = command[command.index("-filter_complex") + 1]
    assert "atrim=start=45:end=60" in filters
    assert "atrim=start=0:end=30" in filters
    assert filters.index("atrim") < filters.index("silenceremove")
    assert "concat=n=2" in filters
    assert build_preview([probe(), probe()], (), opts).estimated_output_duration_seconds == 45


def test_trim_skips_inputs_outside_selection_without_empty_concat_streams():
    command = build_ffmpeg_command([Path("a.wav"), Path("b.wav")], Path("out.flac"),
        options(output_format="flac", trim_start_seconds=70, trim_end_seconds=80), [probe(), probe()])
    filters = command[command.index("-filter_complex") + 1]
    assert "[0:a:0]" not in filters
    assert "[1:a:0]atrim=start=10:end=20" in filters
    assert "concat=" not in filters


@pytest.mark.parametrize("start,end", [(0, 0), (20, 10), (60, None), (0, 61), (-1, 3), (float("nan"), 3), (0, float("inf")), (True, 4)])
def test_invalid_trim_is_rejected_before_render(start, end):
    with pytest.raises(AudioPreparationError):
        build_preview([probe()], (), options(trim_start_seconds=start, trim_end_seconds=end))


def test_exact_trim_requires_explicit_conversion_and_legacy_recipe_stays_valid():
    with pytest.raises(AudioPreparationError):
        options(output_format="copy", trim_start_seconds=1)
    assert options(output_format="copy").trim_end_seconds is None


@pytest.mark.parametrize(
    "payload",
    [
        {"preset": "unknown"},
        {"preset": "processing_only", "silence_threshold_db": -100},
        {"preset": "processing_only", "silence_min_duration_seconds": 0},
        {"preset": "processing_only", "silence_keep_duration_seconds": 6},
        {"preset": "processing_only", "silence_min_duration_seconds": 1, "silence_keep_duration_seconds": 2},
        {"preset": "processing_only", "output_name_template": "{secret}"},
        {"preset": "processing_only", "output_format": "copy", "mono_mode": "left"},
        {"preset": "processing_only", "output_format": "copy", "silence_enabled": True},
    ],
)
def test_options_fail_closed(payload):
    with pytest.raises(AudioPreparationError) as caught:
        normalize_options(payload)
    assert caught.value.reason is AudioPreparationReason.invalid_options


def test_probe_uses_allowlisted_command_and_reduces_metadata():
    def runner(command, **kwargs):
        assert command[:3] == ["ffprobe", "-v", "error"]
        assert kwargs == {"capture_output": True, "text": True, "check": True, "timeout": 60}
        return CompletedProcess(
            command,
            0,
            stdout='{"format":{"format_name":"wav","duration":"12.5"},"streams":[{"codec_type":"video"},{"codec_type":"audio","codec_name":"pcm_s16le","sample_rate":"48000","channels":2,"channel_layout":"stereo"}]}',
            stderr="private",
        )

    result = probe_media(Path("private-input.wav"), runner=runner)
    assert result == AudioProbe(12.5, "wav", "pcm_s16le", 48000, 2, "stereo")
    assert "private" not in repr(result)


def test_probe_falls_back_to_container_duration_for_obs_matroska_stream_sentinel():
    def runner(command, **kwargs):
        return CompletedProcess(
            command,
            0,
            stdout=(
                '{"format":{"format_name":"matroska,webm","duration":"12.5"},'
                '"streams":[{"codec_type":"audio","duration":"N/A","codec_name":"aac",'
                '"sample_rate":"48000","channels":2,"channel_layout":"stereo"}]}'
            ),
            stderr="private",
        )

    result = probe_media(Path("obs-capture.mkv"), runner=runner)

    assert result.duration_seconds == 12.5
    assert result.format_name == "matroska,webm"


def test_probe_uses_obs_matroska_duration_tag_when_numeric_durations_are_sentinels():
    def runner(command, **kwargs):
        return CompletedProcess(
            command,
            0,
            stdout=(
                '{"format":{"format_name":"matroska,webm","duration":"N/A"},'
                '"streams":[{"codec_type":"audio","duration":"N/A","codec_name":"aac",'
                '"sample_rate":"48000","channels":2,"channel_layout":"stereo",'
                '"tags":{"DURATION":"00:12:34.567000000"}}]}'
            ),
            stderr="private",
        )

    result = probe_media(Path("obs-capture.mkv"), runner=runner)

    assert result.duration_seconds == pytest.approx(754.567)


def test_probe_uses_bounded_time_base_duration_when_obs_tags_are_absent():
    def runner(command, **kwargs):
        return CompletedProcess(
            command,
            0,
            stdout=(
                '{"format":{"format_name":"matroska,webm"},'
                '"streams":[{"codec_type":"audio","codec_name":"opus","sample_rate":"48000",'
                '"channels":2,"duration_ts":"15025","time_base":"1/1000"}]}'
            ),
            stderr="private",
        )

    result = probe_media(Path("obs-capture.mkv"), runner=runner)

    assert result.duration_seconds == pytest.approx(15.025)


def test_probe_can_use_container_stream_duration_tag_but_rejects_malformed_clock_values():
    payloads = iter(
        (
            (
                '{"format":{"format_name":"matroska,webm"},"streams":['
                '{"codec_type":"video","codec_name":"h264","tags":{"DURATION":"00:01:02.5"}},'
                '{"codec_type":"audio","codec_name":"aac","sample_rate":"48000","channels":2}]}'
            ),
            (
                '{"format":{"format_name":"matroska,webm","tags":{"DURATION":"private"}},'
                '"streams":[{"codec_type":"audio","codec_name":"aac","sample_rate":"48000",'
                '"channels":2,"duration_ts":"12","time_base":"broken"}]}'
            ),
        )
    )

    def runner(command, **kwargs):
        if command[0] == "ffmpeg":
            return CompletedProcess(command, 0, stdout="progress=end\n", stderr="private")
        return CompletedProcess(command, 0, stdout=next(payloads), stderr="private")

    assert probe_media(Path("obs-capture.mkv"), runner=runner).duration_seconds == pytest.approx(62.5)
    with pytest.raises(AudioPreparationError) as caught:
        probe_media(Path("obs-capture.mkv"), runner=runner)
    assert caught.value.reason is AudioPreparationReason.invalid_input


def test_probe_scans_decodable_audio_when_obs_matroska_has_no_duration_metadata():
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == "ffprobe":
            return CompletedProcess(
                command,
                0,
                stdout=(
                    '{"format":{"format_name":"matroska,webm"},'
                    '"streams":[{"codec_type":"audio","codec_name":"aac",'
                    '"sample_rate":"48000","channels":2,"channel_layout":"stereo"}]}'
                ),
                stderr="private",
            )
        return CompletedProcess(
            command,
            0,
            stdout="out_time=00:00:30.000000\nprogress=continue\nout_time=00:10:10.125000\nprogress=end\n",
            stderr="private",
        )

    result = probe_media(Path("unfinished-obs-capture.mkv"), runner=runner)

    assert result.duration_seconds == pytest.approx(610.125)
    assert [call[0][0] for call in calls] == ["ffprobe", "ffmpeg"]
    assert calls[1][0][calls[1][0].index("-stats_period") + 1] == "30"
    assert calls[1][1]["timeout"] == 1800


def test_probe_rejects_obs_duration_scan_without_bounded_progress_clock():
    def runner(command, **kwargs):
        if command[0] == "ffprobe":
            return CompletedProcess(
                command,
                0,
                stdout=(
                    '{"format":{"format_name":"matroska,webm"},'
                    '"streams":[{"codec_type":"audio","codec_name":"aac",'
                    '"sample_rate":"48000","channels":2}]}'
                ),
                stderr="private",
            )
        return CompletedProcess(command, 0, stdout="out_time=private\nprogress=end\n", stderr="private")

    with pytest.raises(AudioPreparationError) as caught:
        probe_media(Path("unfinished-obs-capture.mkv"), runner=runner)

    assert caught.value.reason is AudioPreparationReason.invalid_input


def test_probe_rejects_missing_audio_and_malformed_values():
    def runner(command, **kwargs):
        return CompletedProcess(command, 0, stdout='{"format":{"duration":"4"},"streams":[]}', stderr="")

    with pytest.raises(AudioPreparationError) as caught:
        probe_media(Path("x"), runner=runner)
    assert caught.value.reason is AudioPreparationReason.invalid_input


def test_integrity_check_decodes_audio_without_shell():
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return CompletedProcess(command, 0)

    verify_media_integrity(Path("input.flac"), runner=runner)
    command, kwargs = calls[0]
    assert command == ["ffmpeg", "-v", "error", "-xerror", "-i", "input.flac", "-map", "0:a:0", "-f", "null", "-"]
    assert "shell" not in kwargs


def test_silence_analysis_parses_only_bounded_scalar_durations():
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return CompletedProcess(
            command,
            0,
            stdout="",
            stderr="[silencedetect] silence_end: 12.4 | silence_duration: 2.4\n[silencedetect] silence_end: 25 | silence_duration: 5",
        )

    assert analyze_silence(Path("private.wav"), threshold_db=-40, minimum_seconds=1, runner=runner) == (2.4, 5.0)
    assert "-xerror" in calls[0]


def test_preview_sums_duration_estimates_truncated_silence_and_copy_compatibility():
    result = build_preview([probe(), probe()], [2.0, 3.0], options(silence_enabled=True, silence_keep_duration_seconds=0.5))
    assert result.input_count == 2
    assert result.input_duration_seconds == 120
    assert result.estimated_output_duration_seconds == 116
    assert result.copy_compatible is True


def test_preview_rejects_copy_mismatch_and_right_channel_for_mono():
    with pytest.raises(AudioPreparationError) as mismatch:
        build_preview([probe(), probe(codec="flac", fmt="flac")], [], options(output_format="copy"))
    assert mismatch.value.reason is AudioPreparationReason.copy_incompatible
    with pytest.raises(AudioPreparationError) as channel:
        build_preview([probe(channels=1)], [], options(mono_mode="right"))
    assert channel.value.reason is AudioPreparationReason.channel_unavailable


def test_copy_command_requires_compatible_inputs_and_concat_manifest():
    command = build_ffmpeg_command(
        [Path("a.wav"), Path("b.wav")],
        Path("out.wav"),
        options(output_format="copy"),
        [probe(), probe()],
        concat_list_path=Path("inputs.txt"),
    )
    assert command == [
        "ffmpeg", "-v", "error", "-xerror", "-f", "concat", "-safe", "1", "-i", "inputs.txt",
        "-map", "0:a:0", "-c:a", "copy", "-y", "out.wav",
    ]


@pytest.mark.parametrize(
    ("mono_mode", "expected_filter"),
    [
        ("preserve", None),
        ("mixdown", "aformat=channel_layouts=mono"),
        ("left", "pan=mono|c0=c0"),
        ("right", "pan=mono|c0=c1"),
    ],
)
def test_conversion_command_composes_channel_silence_concat_and_exact_codec(mono_mode, expected_filter):
    configured = options(
        output_format="flac",
        mono_mode=mono_mode,
        silence_enabled=True,
        silence_threshold_db=-41,
        silence_min_duration_seconds=1.5,
        silence_keep_duration_seconds=0.4,
    )
    command = build_ffmpeg_command([Path("a.wav"), Path("b.wav")], Path("out.flac"), configured, [probe(), probe()])
    filter_value = command[command.index("-filter_complex") + 1]
    if expected_filter is not None:
        assert expected_filter in filter_value
    assert "silenceremove=" in filter_value
    assert filter_value.count("asetpts=PTS-STARTPTS") == 2
    assert "concat=n=2:v=0:a=1[outa]" in filter_value
    assert command[-8:] == [
        "-c:a", "flac", "-sample_fmt", "s16", "-f", "flac", "-y", "out.flac",
    ]
    assert "-ar" not in command
    assert "shell" not in command


@pytest.mark.parametrize("output_format", ["wav", "flac", "copy"])
def test_processing_reports_bounded_ffmpeg_progress(monkeypatch, output_format):
    class Process:
        def __init__(self):
            self.stdout = StringIO(
                "out_time=00:00:10.000000\nprogress=continue\n"
                "out_time=00:01:40.000000\nprogress=end\n"
            )
        def wait(self): return 0
        def poll(self): return 0
        def kill(self): raise AssertionError("successful process must not be killed")

    captured = {}

    def popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr("studio_api.audio_preparation.subprocess.Popen", popen)
    progress = []
    command = build_ffmpeg_command([Path("input.wav")], Path(f"output.{output_format}"),
                                   options(output_format=output_format), [probe()],
                                   concat_list_path=Path("inputs.txt") if output_format == "copy" else None)
    command[-1:-1] = ["-fs", "1048576"]
    original = list(command)
    run_processing(
        command,
        expected_duration_seconds=100,
        progress_callback=progress.append,
    )

    assert progress == [0.1, 0.1, 0.99, 1.0]
    assert captured["command"][1:8] == ["-nostdin", "-nostats", "-stats_period", "5", "-progress", "pipe:1", "-v"]
    assert captured["command"][7:] == original[1:]
    assert captured["command"][captured["command"].index("-fs") + 1] == "1048576"
    assert command == original
    assert captured["kwargs"]["stderr"] == -1


def test_processing_cancellation_before_first_timestamp_kills_subprocess(monkeypatch):
    class Cancelled(RuntimeError):
        pass
    class Process:
        stdout = StringIO("out_time=N/A\nprogress=continue\n")
        stderr = StringIO("")
        killed = False
        def poll(self): return 0 if self.killed else None
        def kill(self): self.killed = True
        def wait(self): return -9
    process = Process()
    monkeypatch.setattr("studio_api.audio_preparation.subprocess.Popen", lambda *args, **kwargs: process)
    def check(_ratio):
        raise Cancelled()
    with pytest.raises(Cancelled):
        run_processing(["ffmpeg", "-y", "output.wav"], expected_duration_seconds=100, progress_callback=check)
    assert process.killed


@pytest.mark.parametrize("stderr,category", [
    ("Error parsing options: Invalid argument", "invalid_arguments"),
    ("Invalid data found when processing input", "invalid_media"),
    ("Unknown encoder 'private'", "encoder_unavailable"),
    ("No space left on device", "output_io_failed"),
    ("Bearer private-token https://private.test/audio.wav", "unknown"),
])
def test_processing_drains_large_stderr_but_exposes_only_safe_category(monkeypatch, caplog, stderr, category):
    diagnostic_stream = StringIO("private-output\n" * 10000 + stderr)
    class Process:
        stdout = StringIO("")
        stderr = diagnostic_stream
        def wait(self): return 1
        def poll(self): return 1
    monkeypatch.setattr("studio_api.audio_preparation.subprocess.Popen", lambda *a, **kw: Process())
    with pytest.raises(AudioPreparationError) as caught:
        run_processing(["ffmpeg", "-y", "output.wav"], expected_duration_seconds=1, progress_callback=lambda _: None)
    assert caught.value.reason is AudioPreparationReason.processing_failed
    assert caught.value.ffmpeg_exit_code == 1
    assert caught.value.ffmpeg_failure_category == category
    assert str(caught.value) == "processing_failed"
    assert "private" not in caplog.text


@pytest.mark.parametrize("output_format", ["wav", "flac", "copy"])
def test_real_ffmpeg_processing_with_size_budget_and_progress(tmp_path, output_format):
    import shutil
    import wave
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("real FFmpeg smoke requires installed ffmpeg and ffprobe")
    source = tmp_path / "synthetic.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(48000)
        audio.writeframes(b"\0\0" * 4800)
    output = tmp_path / ("processed.wav" if output_format == "copy" else f"processed.{output_format}")
    concat = tmp_path / "inputs.txt"
    concat.write_text("file 'synthetic.wav'\n", encoding="utf-8")
    command = build_ffmpeg_command([source], output, options(output_format=output_format),
                                   [probe_media(source)], concat_list_path=concat)
    command[-1:-1] = ["-fs", "1048576"]
    progress = []
    run_processing(command, expected_duration_seconds=0.1, progress_callback=progress.append)
    assert 0 < output.stat().st_size < 1048576
    assert probe_media(output).duration_seconds == pytest.approx(0.1, abs=0.01)
    assert progress[-1] == 1.0


def test_processing_drains_real_pipe_above_os_buffer_capacity(monkeypatch):
    import subprocess
    popen = subprocess.Popen
    script = "import sys; sys.stderr.write('x' * 1048576 + 'No space left on device'); sys.stderr.flush(); sys.exit(1)"
    monkeypatch.setattr("studio_api.audio_preparation.subprocess.Popen",
                        lambda _command, **kwargs: popen([sys.executable, "-c", script], **kwargs))
    with pytest.raises(AudioPreparationError) as caught:
        run_processing(["ffmpeg", "-y", "output.wav"], expected_duration_seconds=1, progress_callback=lambda _: None)
    assert caught.value.ffmpeg_failure_category == "output_io_failed"
    assert caught.value.ffmpeg_exit_code == 1


@pytest.mark.parametrize("output_format", ["wav", "flac", "copy"])
def test_render_filename_preserves_dots_in_title_project_and_template(output_format):
    configured = options(output_format=output_format, output_name_template="{project}.{title}.v2")
    filename = render_output_filename(configured, created_at=datetime(2026,9,6,tzinfo=timezone.utc), project_title="Семестр 1. Психология", title="Лекция 1. Предмет, задачи и методы социальной психологии")
    suffix = "audio" if output_format == "copy" else output_format
    assert filename == f"Семестр 1. Психология.Лекция 1. Предмет, задачи и методы социальной психологии.v2.{suffix}"


def test_render_filename_uses_only_allowlisted_metadata_and_extension():
    configured = options(output_format="wav", output_name_template="{date}_{time}_{project}_{title}")
    filename = render_output_filename(
        configured,
        created_at=datetime(2026, 8, 24, 18, 5, 6, tzinfo=timezone.utc),
        project_title="Проект/секрет",
        title="Созвон: команда",
    )
    assert filename.startswith("2026-08-24_18-05-06Z_")
    assert filename.endswith(".wav")
    assert "/" not in filename and "\\" not in filename
    assert "Проект_секрет" in filename
    assert "Созвон_ команда" in filename


def test_missing_creation_time_keeps_title_without_inventing_today():
    configured = options(output_format="flac", output_name_template="{date}_{time}_{title}")
    assert render_output_filename(configured, created_at=None, project_title="Studio", title="Лекция 1. Предмет") == "Лекция 1. Предмет.flac"
