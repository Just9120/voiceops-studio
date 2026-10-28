from io import BytesIO
from pathlib import Path
import sys
import wave

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
from studio_api.provider_media import whole_file_preparer
from studio_api.media_preparation import MediaPreparationError
from studio_api.audio_preparation import probe_media


def synthetic_wav():
    data = BytesIO()
    with wave.open(data, "wb") as writer:
        writer.setnchannels(2); writer.setsampwidth(2); writer.setframerate(16000)
        writer.writeframes(bytes(16000 * 2 * 2 * 2))
    return data.getvalue()


@pytest.mark.parametrize("provider", ["mistral", "gemini", "tbank"])
def test_whole_file_preparation_keeps_selected_interval_and_cleans_scratch(provider, tmp_path):
    source = synthetic_wav()
    with whole_file_preparer(provider)(stream=BytesIO(source), original_filename="synthetic.wav", mime_type="audio/wav",
        byte_count=len(source), max_output_bytes=1024 * 1024, media_clip_start_seconds=1, media_clip_end_seconds=2,
        temporary_directory=str(tmp_path)) as prepared:
        assert len(prepared.parts) == 1 and prepared.duration_seconds == 1
        part = prepared.parts[0]
        probe = probe_media(Path(part.stream.name))
        assert abs(probe.duration_seconds - 1) < 0.15
        assert part.mime_type == ("audio/mpeg" if provider == "tbank" else "audio/flac")
        assert probe.channels == (1 if provider == "tbank" else 2)
    assert list(tmp_path.iterdir()) == []


def test_provider_limit_is_checked_before_conversion_or_paid_request(tmp_path, monkeypatch):
    from studio_api import provider_media
    monkeypatch.setattr(provider_media, "_probe_duration_seconds", lambda *args: 1801)
    with pytest.raises(MediaPreparationError):
        with whole_file_preparer("gemini", diarize=True)(stream=BytesIO(b"synthetic"), original_filename="x.wav", mime_type="audio/wav",
            byte_count=9, max_output_bytes=1024, temporary_directory=str(tmp_path)):
            pytest.fail("oversized duration must not reach transport")
    assert list(tmp_path.iterdir()) == []
