import json
import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
from studio_api.audio_timeline import AudioTimeline, AudioTimelineError, NoRetainedAudio


@pytest.fixture
def edited():
    return AudioTimeline.from_seconds(100, [(10, 20), (40, 50), (90, 100)])


def test_word_boundaries_on_a_removed_pause_have_distinct_start_and_end_ownership(edited):
    assert edited.output_duration_seconds == 30
    assert edited.original_interval(9, 10) == (19, 20)
    assert edited.original_interval(10, 11) == (40, 41)
    assert edited.original_interval(10, 10) == (40, 40)
    assert edited.original_interval(9, 11) == (19, 41)
    assert edited.original_interval(30, 30) == (100, 100)


def test_fragments_are_selected_on_original_clock_and_never_implicitly_include_removed_speech(edited):
    assert edited.prepared_interval(0, 100) == (0, 30)
    assert edited.prepared_interval(18, 45) == (8, 15)
    assert edited.prepared_interval(20, 41) == (10, 11)
    assert edited.prepared_interval(19, 40) == (9, 10)
    with pytest.raises(NoRetainedAudio):
        edited.prepared_interval(20, 40)


def test_repeat_processing_composes_against_first_original_instead_of_adding_one_offset(edited):
    child = AudioTimeline.from_seconds(30, [(5, 15), (22, 28)])
    result = edited.compose(child)
    assert result == AudioTimeline.from_seconds(100, [(15, 20), (40, 45), (92, 98)])
    assert result.original_interval(4, 7) == (19, 42)
    assert result.output_duration_seconds == child.output_duration_seconds
    with pytest.raises(AudioTimelineError):
        edited.compose(AudioTimeline.identity(31))


def test_concatenation_offsets_original_lengths_in_order_not_processed_lengths(edited):
    tail = AudioTimeline.from_seconds(40, [(5, 10), (30, 40)])
    combined = AudioTimeline.concatenate([edited, tail])
    assert combined.original_duration_seconds == 140
    assert combined.output_duration_seconds == 45
    assert combined.original_interval(30, 31) == (105, 106)
    assert combined.original_interval(35, 36) == (130, 131)
    assert AudioTimeline.parse(combined.serialize()) == combined


def test_roundtrip_is_stable_across_sample_boundaries_without_accumulating_float_drift():
    timeline = AudioTimeline.from_seconds(3, [(1 / 48000, 1), (1.5, 2.0)])
    for _ in range(20):
        timeline = AudioTimeline.parse(timeline.serialize())
    assert timeline.retained == ((21, 1_000_000), (1_500_000, 2_000_000))
    assert timeline.output_duration_us == 1_499_979


@pytest.mark.parametrize("ranges", [[], [(2, 2)], [(3, 2)], [(-1, 2)], [(0, 11)], [(0, 5), (4, 8)], [(0, math.inf)]])
def test_invalid_or_empty_maps_do_not_fall_back_to_identity(ranges):
    with pytest.raises(AudioTimelineError):
        AudioTimeline.from_seconds(10, ranges)


@pytest.mark.parametrize("value", ["null", "[]", "{}", "not json", '[1]',
    json.dumps({"version": True, "original_duration_us": 10, "retained": [[0, 10]]}),
    json.dumps({"version": 1, "original_duration_us": 10, "retained": [[False, 10]]}),
    json.dumps({"version": 1, "original_duration_us": 10, "retained": [[0, 10]], "assume_identity": True})])
def test_corrupt_legacy_or_untrusted_payload_cannot_establish_original_timeline(value):
    with pytest.raises(AudioTimelineError):
        AudioTimeline.parse(value)


def test_adjacent_ranges_coalesce_and_point_projection_agrees_with_inverse_without_gaps():
    randomizer = random.Random(20261104)
    for _ in range(30):
        cursor = 0
        ranges = []
        for _ in range(20):
            cursor += randomizer.randrange(1, 15)
            end = cursor + randomizer.randrange(1, 15)
            ranges.append((cursor, end))
            cursor = end
        timeline = AudioTimeline.from_seconds(cursor, ranges)
        prepared_offset = 0
        for start, end in ranges:
            assert timeline.prepared_interval(start, end) == (prepared_offset, prepared_offset + end - start)
            assert timeline.original_interval(prepared_offset, prepared_offset + end - start) == (start, end)
            prepared_offset += end - start
    assert AudioTimeline.from_seconds(3, [(0, 1), (1, 2), (2, 3)]) == AudioTimeline.identity(3)
