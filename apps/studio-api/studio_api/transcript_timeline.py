"""Recorded provider-clip -> root recording clocks, including cache-only replay."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import math
import hashlib

from .audio_timeline import AudioTimeline, AudioTimelineError
from .job_claim_lease import is_lease_active
from .models import JobStatus, TranscriptionJob, TranscriptionJobSource

_PREPARED_CLOCK = '{"version":2,"clock":"prepared_unavailable"}'


def recorded_transcript_clock(db, *, job_id, job_source_id):
    job = db.get(TranscriptionJob, job_id)
    if job is None:
        raise AudioTimelineError("transcript_clock_scope_changed")
    if job.media_timeline_version is None:
        return "legacy", None, None
    relation = db.get(TranscriptionJobSource, job_source_id)
    if job.media_timeline_version != 2 or relation is None or relation.job_id != job.id or not relation.transcript_timeline_json:
        raise AudioTimelineError("transcript_clock_unavailable")
    record = relation.transcript_timeline_json
    digest = hashlib.sha256(record.encode()).hexdigest()
    if record == _PREPARED_CLOCK:
        return "prepared", None, digest
    return "original", AudioTimeline.parse(record), digest


@dataclass(frozen=True)
class TranscriptClockSelection:
    version: int | None
    original_start: int | None
    original_end: int | None
    prepared_start: float | None
    prepared_end: float | None
    prepared_context: str | None = field(repr=False)
    parent: AudioTimeline | None = field(repr=False)

    def record(self, observed_source_duration):
        if self.version is None:
            return None
        if self.prepared_context and self.parent is None:
            # Full legacy prepared bytes are usable, their missing clock is not.
            return _PREPARED_CLOCK
        if type(observed_source_duration) not in (int, float) or not math.isfinite(observed_source_duration):
            raise AudioTimelineError("transcript_source_duration_unavailable")
        parent = self.parent or AudioTimeline.identity(observed_source_duration)
        if parent.output_duration_us != round(observed_source_duration * 1_000_000):
            raise AudioTimelineError("prepared_audio_duration_changed")
        start = self.prepared_start or 0
        end = self.prepared_end if self.prepared_end is not None else parent.output_duration_seconds
        child = AudioTimeline.from_seconds(parent.output_duration_seconds, [(start, end)])
        return parent.compose(child).serialize()


def select_transcript_clock(job, source):
    version = job.media_timeline_version
    if version not in (None, 2):
        raise AudioTimelineError("transcript_clock_version_invalid")
    start, end = job.media_clip_start_seconds, job.media_clip_end_seconds
    context = getattr(source, "prepared_audio_context_json", None)
    parent = getattr(source, "original_timeline", None) if version == 2 else None
    prepared_start, prepared_end = start, end
    if version == 2 and (start is not None or end is not None) and context:
        if parent is None:
            raise AudioTimelineError("prepared_audio_timeline_unavailable")
        prepared_start, prepared_end = parent.prepared_interval(start or 0,
            end if end is not None else parent.original_duration_seconds)
    return TranscriptClockSelection(version, start, end, prepared_start, prepared_end, context, parent)


def persist_transcript_clock(db, *, job_id, job_source_id, source, selection, observed_source_duration,
                             lease_owner_id, lease_generation, now):
    job = db.get(TranscriptionJob, job_id, populate_existing=True)
    if job is None or job.media_timeline_version != selection.version:
        raise AudioTimelineError("transcript_clock_scope_changed")
    record = selection.record(observed_source_duration)
    if record is None:
        return
    relation = db.get(TranscriptionJobSource, job_source_id, populate_existing=True)
    if (job is None or relation is None or relation.job_id != job.id or relation.source_id != source.identity.source_id
            or job.status is not JobStatus.processing or job.cancel_requested_at is not None
            or job.lease_owner_id != lease_owner_id or job.lease_generation != lease_generation or not is_lease_active(job, now)
            or job.media_timeline_version != selection.version
            or (job.media_clip_start_seconds, job.media_clip_end_seconds) != (selection.original_start, selection.original_end)
            or relation.source is None or relation.source.project_id != job.project_id
            or relation.source.prepared_audio_context_json != selection.prepared_context):
        raise AudioTimelineError("transcript_clock_scope_changed")
    if relation.transcript_timeline_json is not None and relation.transcript_timeline_json != record:
        raise AudioTimelineError("transcript_clock_changed")
    relation.transcript_timeline_json = record
    db.flush()


@contextmanager
def original_clock_transcript(db, *, job_id, job_source_id, result):
    """Map exactly once after assembly; raw encrypted checkpoints stay raw.

    This reads only the job/relation receipt. Expired sources, provider keys,
    parent jobs and external services are never needed for cached replay.
    """
    _mode, timeline, _digest = recorded_transcript_clock(db, job_id=job_id, job_source_id=job_source_id)
    if timeline is None:
        yield result
        return
    projected = _project_words(result, timeline)
    try:
        yield projected
    finally:
        projected.revoke()


def _project_words(result, timeline):
    from .elevenlabs_transcription import ElevenLabsTranscriptResult, _RevocableTranscript, _WordData
    words = []
    for word in result.words:
        start = end = None
        if word.start is not None and word.end is not None:
            try:
                start, end = timeline.original_interval(word.start, word.end)
            except AudioTimelineError:
                # Invalid provider timing must not discard paid text or invent
                # a coordinate by stretching/clamping to the last sample.
                pass
        words.append(_WordData(word.text, start, end, word.type, word.speaker_id))
    text = result.text
    return ElevenLabsTranscriptResult(_RevocableTranscript(text, tuple(words)), len(text), len(words),
        result.detected_language_code, result.language_probability)
