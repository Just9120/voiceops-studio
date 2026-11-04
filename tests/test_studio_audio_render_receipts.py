"""Prepared bytes and original clock must travel as one recorded receipt."""
import json
import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
from studio_api.audio_preparation import AudioProbe, normalize_options
from studio_api.audio_preparation_service import serialize_options
from studio_api.audio_result_rendering import render_audio_result
from studio_api.audio_timeline import AudioTimeline


@pytest.mark.parametrize("silence,parent_context", [(False, None), (True, None),
    (False, '{"pauses_removed":true,"input_duration_ms":150000,"output_duration_ms":120000}')])
def test_render_receipt_distinguishes_equal_size_bytes_and_records_only_known_timeline(tmp_path, silence, parent_context):
    source = tmp_path / "input.wav"
    source.write_bytes(b"synthetic-original")
    job = SimpleNamespace(project_id="p", title="Synthetic", output_filename=None, output_mime_type=None,
        estimated_output_duration_ms=60_000, total_input_duration_ms=120_000,
        inputs=[SimpleNamespace(source=SimpleNamespace(source_created_at=None, prepared_audio_context_json=parent_context))],
        options_json=serialize_options(normalize_options({"preset": "processing_only", "output_format": "wav",
            "silence_enabled": silence, "trim_start_seconds": 30, "trim_end_seconds": 90})))
    settings = SimpleNamespace(source_max_upload_bytes=1024 * 1024)
    db = SimpleNamespace(get=lambda *_: SimpleNamespace(title="Synthetic"))
    contents = [b"same-size-audio-A", b"same-size-audio-B"]
    def runner(command, **_):
        if command[0] == "ffprobe":
            return SimpleNamespace(stdout=json.dumps({"streams": [{"codec_type": "audio", "duration": "60",
                "codec_name": "pcm_s16le", "sample_rate": "48000", "channels": 1}],
                "format": {"duration": "60", "format_name": "wav"}}))
        Path(command[-1]).write_bytes(contents.pop(0))
        return SimpleNamespace(stdout="", stderr="")
    probe = AudioProbe(120, "wav", "pcm_s16le", 48000, 1, "mono")
    first = render_audio_result(db, job=job, root=tmp_path, paths=[source], probes=[probe], settings=settings, runner=runner)
    second = render_audio_result(db, job=job, root=tmp_path, paths=[source], probes=[probe], settings=settings, runner=runner)
    assert first.size_bytes == second.size_bytes
    assert first.sha256_checksum != second.sha256_checksum
    assert first.md5_checksum != second.md5_checksum
    if silence or parent_context:
        # Legacy silence flags/parent durations do not expose removed ranges.
        assert first.timeline_json is None and second.timeline_json is None
    else:
        timeline = AudioTimeline.parse(first.timeline_json)
        assert timeline == AudioTimeline.from_seconds(120, [(30, 90)])
        assert timeline.original_interval(0, 1) == (30, 31)
        assert timeline.prepared_interval(40, 50) == (10, 20)


@pytest.mark.parametrize("mutation", [None, "body", "context"])
def test_audio_reprocessing_checks_prepared_bytes_and_recipe_before_rendering(tmp_path, mutation):
    from studio_api.audio_result_rendering import materialize_audio_inputs
    from studio_api.audio_preparation_service import AudioPreparationServiceError
    from studio_api.models import SourceType, SourceUploadStatus
    context = dict(version=2, job_id="0" * 36, input_duration_ms=5000, output_duration_ms=3000,
        pauses_removed=True, content_sha256=hashlib.sha256(b"a" * 100).hexdigest(), timeline_sha256=None)
    source = SimpleNamespace(project_id="project", source_type=SourceType.google_drive,
        upload_status=SourceUploadStatus.uploaded, deleted_at=None, expires_at=None, size_bytes=100,
        mime_type="audio/wav", original_filename="prepared.wav", drive_file_id="prepared",
        drive_revision_id=None, drive_md5_checksum=None, prepared_audio_context_json=json.dumps(context))
    class Stream:
        closed = False
        def iter_chunks(self, size):
            yield b"b" * 100 if mutation == "body" else b"a" * 100
            if mutation == "context":
                source.prepared_audio_context_json = json.dumps(dict(context, input_duration_ms=6000))
        def close(self): self.closed = True
    stream = Stream()
    job = SimpleNamespace(project_id="project", owner_user_id="owner", inputs=[SimpleNamespace(source=source, position=0)])
    db = SimpleNamespace(get=lambda *a: SimpleNamespace(owner_user_id="owner", archived_at=None))
    operation = lambda: materialize_audio_inputs(db, job=job, root=tmp_path,
        settings=SimpleNamespace(source_max_upload_bytes=1000), storage_factory=None,
        drive_token_resolver=lambda *a, **kw: "synthetic", drive_content_fetcher=lambda *a, **kw: stream)
    if mutation:
        with pytest.raises(AudioPreparationServiceError, match="source_unavailable"):
            operation()
    else:
        paths = operation()
        assert len(paths) == 1 and paths[0].read_bytes() == b"a" * 100
    assert stream.closed
