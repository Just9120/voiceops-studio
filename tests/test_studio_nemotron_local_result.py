import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
from studio_api.nemotron_local_result import normalize_nemotron_local_result
from studio_api.elevenlabs_transcription import ElevenLabsTranscriptionError


def payload():
    return dict(file="private-local-path.wav", text="Первый второй", confidence=0, duration=2,
        languages=["ru"], words=[dict(word="Первый", start=.1, end=.8, confidence=0, speaker=1),
                                dict(word="второй", start=1, end=1.8, confidence=0, speaker=2)])


def test_native_result_uses_shared_revocable_words_and_keeps_paths_and_unknown_confidence_private():
    for diarize in (False, True):
        result = normalize_nemotron_local_result(payload(), expected_duration_seconds=2, diarize=diarize)
        assert result.text == "Первый второй" and result.detected_language_code == "ru"
        assert result.language_probability is None
        assert [(w.start, w.end) for w in result.words] == [(.1, .8), (1, 1.8)]
        assert [w.speaker_id for w in result.words] == (["local_1", "local_2"] if diarize else [None, None])
        assert "private-local-path" not in repr(result)
        word = result.words[0]
        result.revoke()
        with pytest.raises(ElevenLabsTranscriptionError, match="context_closed"):
            _ = word.text


@pytest.mark.parametrize("case", ["duration", "bool", "time", "huge_time", "partial_time", "speaker", "empty", "truncated", "unknown_word", "language", "no_speakers"])
def test_unreviewed_partial_invalid_or_missing_native_output_cannot_become_a_complete_result(case):
    value = payload()
    if case == "duration": value["duration"] = 1
    elif case == "bool": value["words"][0]["start"] = True
    elif case == "time": value["words"][0]["end"] = float("nan")
    elif case == "huge_time": value["words"][0]["start"] = 10**1000
    elif case == "partial_time": del value["words"][0]["end"]
    elif case == "speaker": value["words"][0]["speaker"] = {"unsafe":"value"}
    elif case == "empty": value["text"] = ""
    elif case == "truncated": value["truncated"] = True
    elif case == "unknown_word": value["words"][0]["alternate"] = "unreviewed"
    elif case == "language": value["languages"] = ["ru\nprivate"]
    elif case == "no_speakers":
        for word in value["words"]: word.pop("speaker")
    with pytest.raises(ElevenLabsTranscriptionError) as error:
        normalize_nemotron_local_result(value, expected_duration_seconds=2, diarize=True)
    assert str(error.value) == "malformed_provider_response"


def test_missing_timing_preserves_full_text_without_fabricated_coordinates():
    value = payload()
    value["languages"] = ["ru", "en"]
    for word in value["words"]:
        word.pop("start"); word.pop("end"); word.pop("speaker")
    result = normalize_nemotron_local_result(value, expected_duration_seconds=2)
    assert result.text == value["text"] and result.detected_language_code is None
    assert all(w.start is None and w.end is None for w in result.words)
    result.revoke()
