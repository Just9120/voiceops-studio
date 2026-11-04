import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
from studio_api.audio_export_receipt import AudioExportReceipt, verified_upload_receipt
from studio_api.audio_timeline import AudioTimeline, AudioTimelineError
from studio_api.media_context import (prepared_audio_source_context, prepared_audio_context_payload,
    parse_prepared_audio_context, load_prepared_audio_timeline)
from studio_api.models import Base, User, Project, Source, SourceType, AudioPreparationJob, AudioPreparationStatus


@pytest.mark.parametrize("sha,revision,size,expected", [
    ("a" * 64, "new-revision", 100, "matches"),
    ("b" * 64, "old-revision", 100, "changed"),
    (None, "old-revision", 100, "matches"),
    (None, "new-revision", 100, "changed"),
    (None, None, 100, "unverified"),
    ("a" * 64, "old-revision", 101, "changed"),
])
def test_receipt_checks_bytes_or_captured_revision_and_distinguishes_missing_evidence(sha, revision, size, expected):
    receipt = AudioExportReceipt("export", 100, "a" * 64, "old-revision")
    metadata = SimpleNamespace(id="export", size_bytes=size, sha256_checksum=sha, head_revision_id=revision)
    assert AudioExportReceipt.parse(receipt.serialize()).metadata_state(metadata) == expected


def test_legacy_upload_without_proof_cannot_acquire_a_verified_receipt():
    assert verified_upload_receipt(SimpleNamespace(file_id="legacy")) is None
    result = SimpleNamespace(file_id="export", size_bytes=100, sha256_checksum="a" * 64, head_revision_id="revision")
    assert AudioExportReceipt.parse(verified_upload_receipt(result)).sha256 == result.sha256_checksum
    with pytest.raises(ValueError):
        AudioExportReceipt.parse('{"version":true,"file_id":"export","size_bytes":100,"sha256":"' + "a" * 64 + '","revision_id":null}')


def test_source_context_is_a_small_owner_project_and_map_bound_pointer_not_a_copied_map():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add_all([User(id="owner", email="receipt@example.test"), Project(id="project", owner_user_id="owner", title="Synthetic")])
        db.flush()
        timeline = AudioTimeline.from_seconds(15, [(0, 5), (10, 15)])
        job = AudioPreparationJob(project_id="project", owner_user_id="owner", title="Synthetic", options_json="{}",
            status=AudioPreparationStatus.completed, total_input_duration_ms=15000, output_duration_ms=10000,
            output_drive_file_id="export", output_drive_web_view_url="https://drive.google.com/file/d/export/view",
            output_timeline_json=timeline.serialize())
        db.add(job); db.flush()
        receipt = AudioExportReceipt("export", 100, "a" * 64, "revision")
        context = prepared_audio_source_context(job, receipt)
        assert len(context) < 512 and "retained" not in context
        source = Source(project_id="project", source_type=SourceType.google_drive, original_filename="synthetic.wav",
            drive_file_id="export", prepared_audio_context_json=context)
        db.add(source); db.commit()
        assert prepared_audio_context_payload(context)["original_timeline_available"] is True
        assert "content_sha256" not in prepared_audio_context_payload(context)
        assert parse_prepared_audio_context(context)["content_sha256"] == "a" * 64
        assert load_prepared_audio_timeline(db, source, owner_user_id="owner") == timeline
        for attribute, value in (("drive_file_id", "different-file"), ("project_id", "different-project")):
            previous = getattr(source, attribute)
            setattr(source, attribute, value)
            with pytest.raises(AudioTimelineError):
                load_prepared_audio_timeline(db, source, owner_user_id="owner")
            setattr(source, attribute, previous)
        with pytest.raises(AudioTimelineError):
            load_prepared_audio_timeline(db, source, owner_user_id="other-owner")
        job.output_timeline_json = AudioTimeline.identity(15).serialize()
        with pytest.raises(AudioTimelineError):
            load_prepared_audio_timeline(db, source, owner_user_id="owner")
        source.prepared_audio_context_json = json.dumps({"job_id": job.id, "input_duration_ms":15000,
            "output_duration_ms":10000,"pauses_removed":True})
        assert load_prepared_audio_timeline(db, source, owner_user_id="owner") is None
    engine.dispose()


def test_reuse_handler_preserves_original_map_and_creates_no_source_on_same_size_conflict(monkeypatch):
    """Actual handler/SQLite; auth/CSRF/PostgreSQL are separately required in CI."""
    from fastapi import HTTPException
    from studio_api import main as api
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(api.limiter, "check", lambda *_: None)
    monkeypatch.setattr(api, "refreshed_google_drive_access_token", lambda *_: "synthetic-token")
    metadata_state = {"sha256_checksum": "a" * 64, "head_revision_id": "revision-one"}
    calls = []
    def metadata(db, user, file_id, **kwargs):
        assert not db.in_transaction()
        calls.append(file_id)
        return SimpleNamespace(id=file_id, name="synthetic.flac", size_bytes=100, is_folder=False,
            md5_checksum="c" * 32, created_time="2026-11-04T10:00:00Z", modified_time="2026-11-04T10:00:00Z",
            web_view_link="https://drive.google.com/file/d/export/view", **metadata_state), "audio/flac"
    monkeypatch.setattr(api, "_validated_google_drive_source_metadata", metadata)
    with Session(engine, expire_on_commit=False) as db:
        owner = User(id="owner", email="handler-owner@example.test")
        foreign = User(id="foreign", email="handler-foreign@example.test")
        db.add_all([owner, foreign, Project(id="project", owner_user_id="owner", title="Synthetic")]); db.flush()
        job = AudioPreparationJob(project_id="project", owner_user_id="owner", title="Synthetic", options_json="{}",
            status=AudioPreparationStatus.completed, recipe_version=2, total_input_duration_ms=15000, output_duration_ms=10000,
            output_drive_file_id="export", output_drive_web_view_url="https://drive.google.com/file/d/export/view",
            output_timeline_json=AudioTimeline.from_seconds(15, [(0, 5), (10, 15)]).serialize(),
            output_drive_receipt_json=AudioExportReceipt("export", 100, "a" * 64, "revision-one").serialize())
        db.add(job); db.commit()
        job_id = job.id
        first = api.reuse_prepared_audio(job_id, pair=(None, owner), db=db, _=None)
        second = api.reuse_prepared_audio(job_id, pair=(None, owner), db=db, _=None)
        assert first["id"] == second["id"]
        assert first["prepared_audio"]["original_timeline_available"] is True
        source = db.get(Source, first["id"])
        original_context = source.prepared_audio_context_json
        assert source.s3_object_key is None
        db.commit()
        for changed, reason in (({"sha256_checksum":"b" * 64,"head_revision_id":"revision-two"}, "output_copy_changed"),
                                ({"sha256_checksum":None,"head_revision_id":None}, "output_copy_unverified")):
            metadata_state.update(changed)
            with pytest.raises(HTTPException) as error:
                api.reuse_prepared_audio(job_id, pair=(None, owner), db=db, _=None)
            assert error.value.status_code == 409 and error.value.detail["reason"] == reason
            db.rollback()
            assert db.scalar(select(func.count(Source.id))) == 1
            assert db.get(Source, source.id).prepared_audio_context_json == original_context
            db.commit()
        before = len(calls)
        with pytest.raises(HTTPException) as error:
            api.reuse_prepared_audio(job_id, pair=(None, foreign), db=db, _=None)
        assert error.value.status_code == 404 and len(calls) == before
    engine.dispose()
