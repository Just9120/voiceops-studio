import sys
from pathlib import Path
import wave

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
from studio_api.audio_speech_analysis import SpeechCollector, analyze_speech, FRAME_BYTES


class Detector:
    def is_speech(self, frame, rate):
        assert len(frame) == FRAME_BYTES and rate == 16000
        return frame[0] == 1


def test_speech_is_not_derived_from_waveform_loudness_and_tail_is_bounded():
    collector = SpeechCollector(0.1, Detector())
    collector.accept(bytes(FRAME_BYTES))
    collector.accept(b"\x01" * FRAME_BYTES)
    collector.accept(b"\x01" * FRAME_BYTES)
    collector.accept(b"\x01" * 3)
    result = collector.finish()
    assert result.status == "available"
    assert result.intervals == ((0.03, 0.1),)


def test_large_speech_interval_set_is_bounded_without_silent_claim_of_completeness():
    collector = SpeechCollector(1000, Detector())
    for _ in range(600):
        collector.accept(b"\x01" * FRAME_BYTES)
        for _ in range(12): collector.accept(bytes(FRAME_BYTES))
    result = collector.finish()
    assert len(result.intervals) == 512 and result.truncated


def test_real_decoder_and_vad_do_not_mark_silence_as_voice(tmp_path):
    pytest.importorskip("webrtcvad")
    path = tmp_path / "synthetic-silence.wav"
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1); target.setsampwidth(2); target.setframerate(16000)
        target.writeframes(bytes(32000))
    updates = []
    result = analyze_speech(path, duration=1, progress=updates.append)
    assert result.status == "available" and result.intervals == ()
    assert updates[-1] == 1
    assert path.exists()


def test_cancellation_stops_only_owned_decoder_and_preserves_source(tmp_path):
    pytest.importorskip("webrtcvad")
    path = tmp_path / "synthetic-cancel.wav"
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1); target.setsampwidth(2); target.setframerate(16000)
        target.writeframes(bytes(32000))
    calls = 0
    def check():
        nonlocal calls
        calls += 1
        if calls > 1: raise RuntimeError("synthetic cancellation")
    with pytest.raises(RuntimeError, match="synthetic cancellation"):
        analyze_speech(path, duration=1, check=check)
    assert path.exists()
