"""Exact retained intervals on the original ordered recording clock.

Only recorded intervals may establish this mapping. Waveform bins, estimates,
or a silence-enabled flag are never enough to reconstruct removed time.
Integer microseconds keep serialization and repeated composition stable.
"""
from __future__ import annotations

import json
import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from itertools import accumulate
from typing import Iterable

TIMEBASE = 1_000_000
MAX_TIMELINE_US = 7 * 24 * 3600 * TIMEBASE
MAX_TIMELINE_INTERVALS = 65_536
MAX_TIMELINE_JSON_BYTES = 4 * 1024 * 1024


class AudioTimelineError(ValueError):
    """A missing/invalid timeline is unavailable, never an identity fallback."""


class NoRetainedAudio(AudioTimelineError):
    pass


def _microseconds(value: float) -> int:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= MAX_TIMELINE_US / TIMEBASE:
        raise AudioTimelineError("audio_timeline_time_invalid")
    return round(value * TIMEBASE)


@dataclass(frozen=True)
class AudioTimeline:
    original_duration_us: int
    retained: tuple[tuple[int, int], ...]
    _starts: tuple[int, ...] = field(init=False, repr=False, compare=False)
    _ends: tuple[int, ...] = field(init=False, repr=False, compare=False)
    _output_ends: tuple[int, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        if type(self.original_duration_us) is not int or not 0 < self.original_duration_us <= MAX_TIMELINE_US:
            raise AudioTimelineError("audio_timeline_duration_invalid")
        if not isinstance(self.retained, tuple) or not 1 <= len(self.retained) <= MAX_TIMELINE_INTERVALS:
            raise AudioTimelineError("audio_timeline_intervals_invalid")
        previous_end = 0
        canonical = []
        for item in self.retained:
            if not isinstance(item, tuple) or len(item) != 2:
                raise AudioTimelineError("audio_timeline_interval_invalid")
            start, end = item
            if (type(start) is not int or type(end) is not int
                    or not previous_end <= start < end <= self.original_duration_us):
                raise AudioTimelineError("audio_timeline_interval_invalid")
            if canonical and canonical[-1][1] == start:
                canonical[-1] = (canonical[-1][0], end)
            else:
                canonical.append((start, end))
            previous_end = end
        intervals = tuple(canonical)
        object.__setattr__(self, "retained", intervals)
        object.__setattr__(self, "_starts", tuple(start for start, _ in intervals))
        object.__setattr__(self, "_ends", tuple(end for _, end in intervals))
        object.__setattr__(self, "_output_ends", tuple(accumulate(end - start for start, end in intervals)))

    @classmethod
    def from_seconds(cls, duration: float, retained: Iterable[tuple[float, float]]) -> AudioTimeline:
        ranges = []
        for index, (start, end) in enumerate(retained):
            if index >= MAX_TIMELINE_INTERVALS:
                raise AudioTimelineError("audio_timeline_interval_limit")
            ranges.append((_microseconds(start), _microseconds(end)))
        if not ranges:
            raise NoRetainedAudio("audio_timeline_no_retained_audio")
        return cls(_microseconds(duration), tuple(ranges))

    @classmethod
    def identity(cls, duration: float) -> AudioTimeline:
        total = _microseconds(duration)
        return cls(total, ((0, total),))

    @property
    def output_duration_us(self) -> int:
        return self._output_ends[-1]

    @property
    def original_duration_seconds(self) -> float:
        return self.original_duration_us / TIMEBASE

    @property
    def output_duration_seconds(self) -> float:
        return self.output_duration_us / TIMEBASE

    def _original_point(self, output_us: int, *, end: bool) -> int:
        if not 0 <= output_us <= self.output_duration_us:
            raise AudioTimelineError("audio_timeline_output_out_of_bounds")
        if output_us == self.output_duration_us:
            return self.retained[-1][1]
        # A word ending at a join belongs to the left interval; a word starting
        # there belongs to the right. This prevents shifting words across gaps.
        index = bisect_left(self._output_ends, output_us) if end else bisect_right(self._output_ends, output_us)
        offset = self._output_ends[index - 1] if index else 0
        return self.retained[index][0] + output_us - offset

    def original_interval(self, start: float, end: float) -> tuple[float, float]:
        start_us, end_us = _microseconds(start), _microseconds(end)
        if end_us < start_us:
            raise AudioTimelineError("audio_timeline_interval_invalid")
        left = self._original_point(start_us, end=False)
        # Zero-duration punctuation retains one coordinate at a join.
        right = left if end_us == start_us else self._original_point(end_us, end=True)
        return left / TIMEBASE, right / TIMEBASE

    def prepared_interval(self, start: float, end: float) -> tuple[float, float]:
        """Translate an original-clock fragment, omitting removed silence."""
        start_us, end_us = _microseconds(start), _microseconds(end)
        if not 0 <= start_us < end_us <= self.original_duration_us:
            raise AudioTimelineError("audio_timeline_original_out_of_bounds")
        first = bisect_right(self._ends, start_us)
        last = bisect_left(self._starts, end_us) - 1
        if first > last or first >= len(self.retained):
            raise NoRetainedAudio("audio_timeline_fragment_has_no_audio")
        left_offset = self._output_ends[first - 1] if first else 0
        right_offset = self._output_ends[last - 1] if last else 0
        left = left_offset + max(0, start_us - self.retained[first][0])
        right = right_offset + min(end_us, self.retained[last][1]) - self.retained[last][0]
        return left / TIMEBASE, right / TIMEBASE

    def compose(self, child: AudioTimeline) -> AudioTimeline:
        """Child original time is this result's prepared time (repeat processing)."""
        if child.original_duration_us != self.output_duration_us:
            raise AudioTimelineError("audio_timeline_composition_duration_mismatch")
        result = []
        index = 0
        for start, end in child.retained:
            while self._output_ends[index] <= start:
                index += 1
            current = index
            while current < len(self.retained):
                offset = self._output_ends[current - 1] if current else 0
                left, right = max(start, offset), min(end, self._output_ends[current])
                if right > left:
                    result.append((self.retained[current][0] + left - offset,
                                   self.retained[current][0] + right - offset))
                    if len(result) > MAX_TIMELINE_INTERVALS:
                        raise AudioTimelineError("audio_timeline_interval_limit")
                if self._output_ends[current] >= end:
                    break
                current += 1
        return AudioTimeline(self.original_duration_us, tuple(result))

    @classmethod
    def concatenate(cls, timelines: Iterable[AudioTimeline]) -> AudioTimeline:
        intervals = []
        offset = 0
        for timeline in timelines:
            if len(intervals) + len(timeline.retained) > MAX_TIMELINE_INTERVALS:
                raise AudioTimelineError("audio_timeline_interval_limit")
            intervals.extend((start + offset, end + offset) for start, end in timeline.retained)
            offset += timeline.original_duration_us
        if not intervals:
            raise NoRetainedAudio("audio_timeline_no_retained_audio")
        return cls(offset, tuple(intervals))

    def serialize(self) -> str:
        return json.dumps({"version": 1, "original_duration_us": self.original_duration_us,
                           "retained": self.retained}, separators=(",", ":"), allow_nan=False)

    @classmethod
    def parse(cls, value: str) -> AudioTimeline:
        if not isinstance(value, str) or not 1 <= len(value) <= MAX_TIMELINE_JSON_BYTES:
            raise AudioTimelineError("audio_timeline_payload_invalid")
        try:
            payload = json.loads(value)
            if (not isinstance(payload, dict) or set(payload) != {"version", "original_duration_us", "retained"}
                    or type(payload["version"]) is not int or payload["version"] != 1
                    or not isinstance(payload["retained"], list)):
                raise AudioTimelineError("audio_timeline_payload_invalid")
            ranges = payload["retained"]
            if not 1 <= len(ranges) <= MAX_TIMELINE_INTERVALS or any(not isinstance(x, list) for x in ranges):
                raise AudioTimelineError("audio_timeline_payload_invalid")
            return cls(payload["original_duration_us"], tuple(tuple(item) for item in ranges))
        except (TypeError, ValueError, RecursionError, KeyError) as exc:
            raise AudioTimelineError("audio_timeline_payload_invalid") from exc
