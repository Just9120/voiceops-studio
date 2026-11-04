import hashlib
import json
import shutil
import subprocess
import sys
import wave
from array import array
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
from studio_api.audio_preparation import AudioPreparationError, normalize_options, probe_media, run_processing
from studio_api.audio_preparation_service import serialize_options
from studio_api.audio_retained_frames import (RetainedTrack, RetainedRecipe, _retained_samples, _scan_selected,
    build_retained_recipe)
from studio_api.audio_result_rendering import render_audio_result
from studio_api.models import AudioPreparationStatus
from studio_api.audio_timeline import AudioTimeline


def options(**overrides):
    return normalize_options({"preset": "processing_only", "silence_enabled": True,
        "silence_min_duration_seconds": .2, "silence_keep_duration_seconds": .1, **overrides})


def test_sample_ranges_round_cuts_inward_and_keep_both_edges_of_a_pause():
    kept = _retained_samples(16000, 8000, [(.4, 1.6)], .1)
    assert kept == ((0, 3600), (12400, 16000))
    assert sum(end - start for start, end in kept) == 7200
    assert _retained_samples(16000, 8000, [], .1) == ((0, 16000),)
    assert _retained_samples(16003, 8000, [(0, 16003 / 8000)], 0) == ()


def test_recorded_recipe_projects_actual_sample_ranges_and_survives_serialization():
    track = RetainedTrack(0, 8000, 1600, 12800, 0, ((0, 2000), (10800, 12800)))
    recipe = RetainedRecipe(2_000_000, "a" * 64, (track,))
    assert recipe.timeline().retained == ((200_000, 450_000), (1_550_000, 1_800_000))
    assert recipe.timeline().original_interval(.24, .26) == (.44, 1.56)
    assert RetainedRecipe.parse(recipe.serialize()) == recipe
    assert "if(lt(n," in track.select_expression()


def test_many_pause_selection_uses_bounded_depth_not_one_condition_per_pause_per_frame():
    track = RetainedTrack(0, 8000, 0, 160000, 0, tuple((start, start + 80) for start in range(0, 160000, 160)))
    expression = track.select_expression()
    depth = maximum = 0
    for char in expression:
        if char == "(": depth += 1; maximum = max(depth, maximum)
        elif char == ")": depth -= 1
    assert depth == 0 and maximum <= 13
    assert "between" not in expression


@pytest.mark.parametrize("mutation", ["version", "nan", "order", "unaligned", "missing", "extra"])
def test_untrusted_recipe_cannot_supply_a_different_order_or_unrecorded_samples(mutation):
    recipe = RetainedRecipe(1_000_000, "a" * 64, (RetainedTrack(0, 8000, 0, 8000, 0, ((0, 8000),)),))
    payload = json.loads(recipe.serialize())
    if mutation == "version": payload["version"] = True
    if mutation == "nan": payload["tracks"][0]["sample_rate"] = float("nan")
    if mutation == "order": payload["tracks"].append(payload["tracks"][0])
    if mutation == "unaligned": payload["tracks"][0]["kept"] = [[1, 8000]]
    if mutation == "missing": del payload["tracks"][0]["decoded_samples"]
    if mutation == "extra": payload["tracks"][0]["assume_identity"] = True
    with pytest.raises(ValueError): RetainedRecipe.parse(json.dumps(payload))


def test_decoder_must_report_actual_duration_instead_of_accepting_an_estimate():
    with pytest.raises(AudioPreparationError, match="timeline_unavailable"):
        _scan_selected(Path("synthetic.wav"), rate=8000, seek=0, requested=8000, options=options(),
            runner=lambda *a, **k: SimpleNamespace(stdout="", stderr=""))
    with pytest.raises(AudioPreparationError, match="timeline_unavailable"):
        _scan_selected(Path("synthetic.wav"), rate=8000, seek=0, requested=8000, options=options(),
            runner=lambda *a, **k: SimpleNamespace(stdout="out_time_us=2000000\n", stderr=""))


def test_decoded_sample_count_not_last_muxer_packet_timestamp_defines_retained_tail():
    def decoder(command, **_):
        assert "astats=measure_perchannel=0:measure_overall=Number_of_samples" in command[command.index("-af") + 1]
        return SimpleNamespace(stdout="out_time_us=1578957\n", stderr="[Parsed_astats_3] Number of samples: 70560\n")
    decoded, silences = _scan_selected(Path("synthetic.wav"), rate=44100, seek=8820,
        requested=70560, options=options(), runner=decoder)
    assert decoded == 70560 and silences == []
    # The last21ms remain available for both this export and a later trim.
    assert decoded / 44100 == 1.6


@pytest.mark.parametrize("counter", ["0", "8002", "8000\nNumber of samples: 8000"])
def test_invalid_or_ambiguous_decoder_sample_count_cannot_authorize_a_recipe(counter):
    with pytest.raises(AudioPreparationError, match="timeline_unavailable"):
        _scan_selected(Path("synthetic.wav"), rate=8000, seek=0, requested=8000, options=options(),
            runner=lambda *a, **k: SimpleNamespace(stdout="out_time_us=1000000\n",
                stderr=f"Number of samples: {counter}\n"))


@pytest.mark.parametrize("mono_mode", ["preserve", "mixdown", "left", "right"])
def test_real_decoder_counts_sample_frames_once_for_stereo_and_channel_selection(tmp_path, mono_mode):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg unavailable; real sample counting remains required in Linux CI")
    source = tmp_path / "stereo.wav"
    with wave.open(str(source), "wb") as out:
        out.setnchannels(2); out.setsampwidth(2); out.setframerate(8000)
        out.writeframes(array("h", [10000, -15000] * 8000).tobytes())
    decoded, silences = _scan_selected(source, rate=8000, seek=0, requested=8000,
        options=options(mono_mode=mono_mode))
    assert decoded == 8000 and silences == []


def test_cancelled_analysis_kills_and_reaps_its_owned_decoder(monkeypatch):
    children = []
    popen = subprocess.Popen
    def start(_command, **kwargs):
        child = popen([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr("studio_api.audio_retained_frames.subprocess.Popen", start)
    checks = []
    def check():
        checks.append(True)
        if len(checks) >= 2: raise RuntimeError("synthetic_cancel")
    with pytest.raises(RuntimeError, match="synthetic_cancel"):
        _scan_selected(Path("synthetic.wav"), rate=8000, seek=0, requested=8000, options=options(), check=check)
    assert len(children) == 1 and children[0].poll() is not None


@pytest.mark.parametrize("sample_rate", [8000, 44100, 48000])
def test_real_silence_trim_map_matches_every_encoded_sample_without_dynamic_reanalysis(tmp_path, sample_rate):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg unavailable; real decoder qualification remains required in Linux CI")
    rate = sample_rate
    samples = array("h", [10000] * round(.4 * rate) + [0] * round(1.2 * rate) + [-10000] * round(.4 * rate))
    source = tmp_path / "synthetic.wav"
    with wave.open(str(source), "wb") as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(rate); out.writeframes(samples.tobytes())
    opts = options(output_format="wav", trim_start_seconds=.2, trim_end_seconds=1.8)
    serialized = serialize_options(opts)
    recipe = build_retained_recipe([source], [probe_media(source)], opts, serialized)
    recipe.validate_inputs([probe_media(source)], serialized)
    restored = RetainedRecipe.parse(recipe.serialize())
    track = restored.tracks[0]
    target = tmp_path / "edited.wav"
    # Rendering uses recorded blocks, not silenceremove or another detector.
    command = ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(track.seek_sample / rate),
        "-t", str(track.decoded_samples / rate), "-i", str(source), "-af", ",".join(track.filter_chain(opts.mono_mode)),
        "-c:a", "pcm_s16le", "-y", str(target)]
    run_processing(command)
    with wave.open(str(target), "rb") as out:
        rendered = out.readframes(out.getnframes())
        assert out.getframerate() == rate
    expected = b"".join(samples[track.seek_sample + start:track.seek_sample + end].tobytes() for start, end in track.kept)
    assert rendered == expected
    assert len(rendered) / 2 / rate == pytest.approx(restored.timeline().output_duration_seconds, abs=.000002)
    assert restored.timeline().original_interval(0, .01) == pytest.approx((.2, .21), abs=.000002)
    with pytest.raises(ValueError, match="options_changed"):
        restored.validate_inputs([probe_media(source)], serialized + " ")


@pytest.mark.parametrize("output_format", ["wav", "flac"])
def test_real_concat_render_and_reload_regenerate_recorded_edits_without_running_detector_again(tmp_path, monkeypatch, output_format):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg unavailable; real rendering remains required in Linux CI")
    rate = 44100
    paths, originals = [], []
    for index, amplitude in enumerate((10000, 15000)):
        samples = array("h", [amplitude] * round(.4 * rate) + [0] * round(1.2 * rate) + [-amplitude] * round(.4 * rate))
        source = tmp_path / f"input-{index}.wav"
        with wave.open(str(source), "wb") as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(rate); out.writeframes(samples.tobytes())
        paths.append(source); originals.append(samples)
    opts = options(output_format=output_format, trim_start_seconds=.2, trim_end_seconds=3.8)
    job = SimpleNamespace(recipe_version=2, retained_frames_json=None, status=AudioPreparationStatus.processing,
        project_id="p", title="Synthetic", output_filename=None, output_mime_type=None,
        total_input_duration_ms=4000, estimated_output_duration_ms=1400,
        inputs=[SimpleNamespace(source=SimpleNamespace(source_created_at=None, prepared_audio_context_json=None)) for _ in paths],
        options_json=serialize_options(opts))
    db = SimpleNamespace(get=lambda *_: SimpleNamespace(title="Synthetic"))
    settings = SimpleNamespace(source_max_upload_bytes=1024 * 1024)
    probes = [probe_media(path) for path in paths]
    first = render_audio_result(db, job=job, root=tmp_path, paths=paths, probes=probes, settings=settings)
    recipe = RetainedRecipe.parse(first.recipe_json)
    expected = b"".join(originals[track.position][track.seek_sample + start:track.seek_sample + end].tobytes()
        for track in recipe.tracks for start, end in track.kept)
    decoded = subprocess.run(["ffmpeg", "-v", "error", "-i", str(first.path), "-f", "s16le", "-"],
        capture_output=True, check=True, timeout=10).stdout
    assert decoded == expected
    timeline = AudioTimeline.parse(first.timeline_json)
    decoded_samples = array("h")
    decoded_samples.frombytes(decoded)
    first_negative_frame = decoded_samples.index(-10000)
    # A known transition in the original PCM is a separate timing oracle;
    # detector/sample rounding must never shift its original1.6s position.
    instant = first_negative_frame / rate
    assert timeline.original_interval(instant, instant) == pytest.approx((1.6, 1.6), abs=.000002)
    assert timeline.output_duration_seconds == pytest.approx(len(decoded) / 2 / rate, abs=.000002)
    # Cutting inward to10ms block boundaries may keep an extra block at each
    # edge. This bound checks the requested shortening without losing speech.
    assert 1.4 <= timeline.output_duration_seconds <= 1.44
    job.status = AudioPreparationStatus.completed
    job.retained_frames_json = first.recipe_json
    monkeypatch.setattr("studio_api.audio_retained_frames._scan_selected", lambda *a, **k: pytest.fail("Saved edits must not be redetected"))
    second = render_audio_result(db, job=job, root=tmp_path, paths=paths, probes=probes, settings=settings)
    assert second.recipe_json == first.recipe_json and second.timeline_json == first.timeline_json
    assert second.sha256_checksum == first.sha256_checksum


def test_real_repeated_preparation_and_concat_keep_the_root_recording_clock(tmp_path):
    """Actual PCM -> retained edit -> verified Drive body -> second trim/concat."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg unavailable; real nested rendering remains required in Linux CI")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from studio_api.audio_export_receipt import AudioExportReceipt
    from studio_api.media_context import prepared_audio_source_context
    from studio_api.models import Base, User, Project, Source, SourceType, SourceUploadStatus, AudioPreparationJob, AudioPreparationJobInput
    rate = 44100
    originals = [array("h", [10000] * round(.4 * rate) + [0] * round(1.2 * rate) + [-10000] * round(.4 * rate)),
                 array("h", [15000] * rate)]
    source_paths = []
    for index, samples in enumerate(originals):
        path = tmp_path / f"original-{index}.wav"
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(rate); out.writeframes(samples.tobytes())
        source_paths.append(path)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    settings = SimpleNamespace(source_max_upload_bytes=1024 * 1024)
    with Session(engine, expire_on_commit=False) as db:
        db.add_all([User(id="owner", email="nested@example.test"), Project(id="project", owner_user_id="owner", title="Synthetic")]); db.flush()
        sources = [Source(project_id="project", source_type=SourceType.google_drive, drive_file_id=f"original-{i}",
            original_filename=p.name, size_bytes=p.stat().st_size, mime_type="audio/wav", upload_status=SourceUploadStatus.uploaded)
            for i, p in enumerate(source_paths)]
        db.add_all(sources); db.flush()
        first = AudioPreparationJob(project_id="project", owner_user_id="owner", title="Synthetic", recipe_version=2,
            status=AudioPreparationStatus.processing, total_input_duration_ms=2000,
            options_json=serialize_options(options(output_format="wav", trim_start_seconds=.2, trim_end_seconds=1.8)))
        db.add(first); db.flush()
        first.inputs = [AudioPreparationJobInput(source=sources[0], position=0)]
        first_root = tmp_path / "first"; first_root.mkdir()
        rendered = render_audio_result(db, job=first, root=first_root, paths=[source_paths[0]], settings=settings)
        first.status = AudioPreparationStatus.completed
        first.output_duration_ms = rendered.duration_ms
        first.output_timeline_json = rendered.timeline_json
        first.output_drive_file_id = "prepared"
        first.output_drive_web_view_url = "https://drive.google.com/file/d/prepared/view"
        first.retained_frames_json = rendered.recipe_json
        payloads = {"prepared": rendered.path.read_bytes(), "original-1": source_paths[1].read_bytes()}
        receipt = AudioExportReceipt("prepared", rendered.size_bytes, rendered.sha256_checksum, None)
        prepared = Source(project_id="project", source_type=SourceType.google_drive, drive_file_id="prepared",
            original_filename="prepared.wav", size_bytes=rendered.size_bytes, mime_type="audio/wav",
            upload_status=SourceUploadStatus.uploaded, prepared_audio_context_json=prepared_audio_source_context(first, receipt))
        db.add(prepared); db.flush()
        boundary = AudioTimeline.parse(rendered.timeline_json).output_duration_seconds
        second = AudioPreparationJob(project_id="project", owner_user_id="owner", title="Synthetic", recipe_version=2,
            status=AudioPreparationStatus.processing, total_input_duration_ms=round((boundary + 1) * 1000),
            options_json=serialize_options(options(output_format="wav", silence_enabled=False,
                trim_start_seconds=boundary-.1, trim_end_seconds=boundary+.2)))
        db.add(second); db.flush()
        second.inputs = [AudioPreparationJobInput(source=prepared, position=0), AudioPreparationJobInput(source=sources[1], position=1)]
        db.commit()
        class Stream:
            def __init__(self, payload): self.payload = payload; self.closed = False
            def iter_chunks(self, _): yield self.payload
            def close(self): self.closed = True
        streams = []
        def download(token, file_id):
            stream = Stream(payloads[file_id]); streams.append(stream); return stream
        second_root = tmp_path / "second"; second_root.mkdir()
        result = render_audio_result(db, job=second, root=second_root, settings=settings,
            drive_token_resolver=lambda *a, **kw: "synthetic", drive_content_fetcher=download)
        assert all(s.closed for s in streams)
        timeline = AudioTimeline.parse(result.timeline_json)
        assert timeline.original_duration_us == 3_000_000
        assert timeline.retained == ((1_700_000, 1_800_000), (2_000_000, 2_200_000))
        assert timeline.original_interval(.1, .1) == (2, 2)
        with wave.open(str(result.path), "rb") as out:
            pcm = array("h"); pcm.frombytes(out.readframes(out.getnframes()))
        assert pcm == array("h", [-10000] * round(.1 * rate) + [15000] * round(.2 * rate))
    engine.dispose()
