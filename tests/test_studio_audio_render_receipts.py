"""Prepared bytes and original clock must travel as one recorded receipt."""
import json
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
