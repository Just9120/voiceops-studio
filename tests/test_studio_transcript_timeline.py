import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
from studio_api.audio_timeline import AudioTimeline, AudioTimelineError, NoRetainedAudio
from studio_api.transcript_timeline import select_transcript_clock, _project_words
from studio_api.elevenlabs_transcription import normalize_elevenlabs_transcript_response, ElevenLabsTranscriptionError


def job(version=2, start=None, end=None):
    return SimpleNamespace(media_timeline_version=version, media_clip_start_seconds=start, media_clip_end_seconds=end)


def test_original_clip_selects_only_retained_audio_and_records_the_root_clock():
    timeline = AudioTimeline.from_seconds(20, [(0, 5), (10, 20)])
    source = SimpleNamespace(prepared_audio_context_json="bounded-claim", original_timeline=timeline)
    selected = select_transcript_clock(job(start=4, end=12), source)
    assert (selected.prepared_start, selected.prepared_end) == (4, 7)
    recorded = AudioTimeline.parse(selected.record(15))
    assert recorded.retained == ((4_000_000, 5_000_000), (10_000_000, 12_000_000))
    assert recorded.original_interval(1, 2) == (10, 11)
    with pytest.raises(NoRetainedAudio):
        select_transcript_clock(job(start=6, end=9), source)
    with pytest.raises(AudioTimelineError, match="duration_changed"):
        selected.record(15.1)


def test_legacy_jobs_keep_their_saved_clip_semantics_and_legacy_prepared_audio_cannot_invent_an_original_clock():
    source = SimpleNamespace(prepared_audio_context_json="legacy-summary", original_timeline=None)
    old = select_transcript_clock(job(version=None, start=4, end=12), source)
    assert (old.prepared_start, old.prepared_end, old.record(None)) == (4, 12, None)
    with pytest.raises(AudioTimelineError, match="timeline_unavailable"):
        select_transcript_clock(job(start=4, end=12), source)
    full = select_transcript_clock(job(), source)
    assert '"clock":"prepared_unavailable"' in full.record(15)


def test_plain_recording_fragment_includes_its_original_offset_instead_of_starting_at_zero():
    source = SimpleNamespace(prepared_audio_context_json=None, original_timeline=None)
    selected = select_transcript_clock(job(start=10, end=20), source)
    assert AudioTimeline.parse(selected.record(60)).original_interval(0, 1) == (10, 11)


def test_projected_words_preserve_paid_text_and_speakers_with_independent_revocable_lifetime():
    raw = normalize_elevenlabs_transcript_response({"text":"first second uncertain", "language_code":"ru", "words":[
        {"text":"first", "start":0, "end":1, "speaker_id":"speaker_0", "type":"word"},
        {"text":"second", "start":1, "end":2, "speaker_id":"speaker_1", "type":"word"},
        {"text":"uncertain", "start":1, "end":200, "speaker_id":"speaker_1", "type":"word"}]})
    timeline = AudioTimeline.from_seconds(20, [(4, 5), (10, 12)])
    projected = _project_words(raw, timeline)
    assert [(w.start, w.end) for w in projected.words] == [(4, 5), (10, 11), (None, None)]
    assert projected.text == raw.text
    assert [w.speaker_id for w in projected.words] == [w.speaker_id for w in raw.words]
    saved_word = projected.words[0]
    projected.revoke()
    with pytest.raises(ElevenLabsTranscriptionError, match="context_closed"):
        _ = saved_word.text
    assert raw.words[0].start == 0 and raw.text == "first second uncertain"
    raw.revoke()


def test_batch_admission_checks_original_bounds_and_fully_removed_intervals_before_creating_jobs(monkeypatch):
    from sqlalchemy import create_engine, select, func
    from sqlalchemy.orm import Session
    from fastapi import HTTPException
    monkeypatch.setenv("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    from studio_api.main import _require_known_batch_clip_bounds
    from studio_api.models import Base, User, Project, Source, SourceType, AudioPreparationJob, AudioPreparationStatus, TranscriptionJob
    from studio_api.media_context import prepared_audio_source_context
    from studio_api.audio_export_receipt import AudioExportReceipt
    from studio_api.media_clip import normalize_media_clip_range
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        owner = User(id="owner", email="clip-admission@example.test")
        db.add_all([owner, Project(id="p", owner_user_id="owner", title="Synthetic")]); db.flush()
        parent = AudioPreparationJob(project_id="p", owner_user_id="owner", title="Synthetic", options_json="{}",
            status=AudioPreparationStatus.completed, total_input_duration_ms=20000, output_duration_ms=15000,
            output_drive_file_id="prepared", output_drive_web_view_url="https://drive.google.com/file/d/prepared/view",
            output_timeline_json=AudioTimeline.from_seconds(20, [(0, 5), (10, 20)]).serialize())
        db.add(parent); db.flush()
        source = Source(project_id="p", source_type=SourceType.google_drive, drive_file_id="prepared", original_filename="prepared.wav",
            prepared_audio_context_json=prepared_audio_source_context(parent, AudioExportReceipt("prepared", 100, "a" * 64, None)))
        db.add(source); db.commit()
        def validate(start, end):
            _require_known_batch_clip_bounds(db, owner, [source], [normalize_media_clip_range(start, end)])
        validate(18, 20)  # Beyond the15s prepared body, inside the20s original.
        validate(None, None)
        for start, end, message in [(6, 9, "не осталось аудио"), (19, 21, "длительность исходной")]:
            with pytest.raises(HTTPException) as error:
                validate(start, end)
            assert error.value.status_code == 422 and message in error.value.detail
        source.prepared_audio_context_json = source.prepared_audio_context_json.replace('"version":2,', '')
        with pytest.raises(HTTPException, match="422"):
            validate(1, 3)
        validate(None, None)
        assert db.scalar(select(func.count(TranscriptionJob.id))) == 0
    engine.dispose()
