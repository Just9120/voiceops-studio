from __future__ import annotations

import sys
import os
import io
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))
ALEMBIC = ROOT / "apps/studio-api" / "alembic.ini"


def isolated_storage_settings():
    return SimpleNamespace(
        source_s3_endpoint_url="https://r2.test",
        source_s3_region="auto",
        source_s3_bucket="bucket",
        source_s3_access_key_id_file="transcription-access",
        source_s3_secret_access_key_file="transcription-secret",
        source_s3_lifecycle_rule_id="transcription-retention",
        audio_reference_s3_endpoint_url="https://r2.test",
        audio_reference_s3_region="auto",
        audio_reference_s3_bucket="audio-bucket",
        audio_reference_s3_access_key_id_file="audio-access",
        audio_reference_s3_secret_access_key_file="audio-secret",
        audio_reference_s3_lifecycle_rule_id="audio-retention",
        source_max_upload_bytes=100,
    )


@pytest.fixture(scope="module", autouse=True)
def speaker_identity_database_environment():
    database_url = os.environ.get("STUDIO_DATABASE_URL")
    configured_scheme = os.environ.get("STUDIO_DATABASE_SCHEME")
    added_local_fallback = database_url is None and configured_scheme is None
    if added_local_fallback:
        os.environ["STUDIO_DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
    try:
        yield
    finally:
        if added_local_fallback:
            os.environ.pop("STUDIO_DATABASE_URL", None)


@dataclass(frozen=True)
class Word:
    speaker_id: str | None
    start: float | None
    end: float | None


def test_module_does_not_mutate_database_environment_during_collection():
    source = Path(__file__).read_text(encoding="utf-8")
    import_prefix = source.split("@pytest.fixture", 1)[0]
    assert "os.environ" not in import_prefix


def test_speaker_identity_schema_is_owner_scoped_bounded_and_additive():
    from studio_api.models import SpeakerProfile, TranscriptionJobSpeaker

    profile_columns = set(SpeakerProfile.__table__.columns.keys())
    assert {
        "owner_user_id",
        "display_name",
        "normalized_name",
        "role",
        "active",
    } <= profile_columns
    observation_columns = set(TranscriptionJobSpeaker.__table__.columns.keys())
    assert {
        "owner_user_id",
        "job_id",
        "job_source_id",
        "provider_speaker_label",
        "display_ordinal",
        "sample_start_ms",
        "sample_end_ms",
        "speaker_profile_id",
        "applied_display_name",
        "applied_role",
    } <= observation_columns
    assert not ({"audio", "audio_bytes", "transcript", "text", "embedding"} & observation_columns)
    assert {
        constraint.name
        for constraint in TranscriptionJobSpeaker.__table__.constraints
        if constraint.name
    } >= {
        "ck_transcription_job_speakers_sample_bounded",
        "ck_transcription_job_speakers_assignment_complete",
    }

    script = ScriptDirectory.from_config(Config(str(ALEMBIC)))
    revision = script.get_revision("0024_speaker_identity")
    assert revision.down_revision == "0023_realtime_drafts"
    assert script.get_heads() == ["0044_quality_progress"]
    migration = Path(revision.module.__file__).read_text(encoding="utf-8")
    assert 'release_safety = "additive"' in migration


def test_profile_normalization_and_rendering_are_deterministic():
    from studio_api.speaker_identity import (
        normalize_profile_name,
        normalize_profile_role,
        render_profile_label,
    )

    display_name, normalized_name = normalize_profile_name("  Анна   Петрова  ")
    role = normalize_profile_role("  Руководитель  проекта ")

    assert display_name == "Анна Петрова"
    assert normalized_name == "анна петрова"
    assert role == "Руководитель проекта"
    assert render_profile_label(display_name, role) == "Анна Петрова — Руководитель проекта"


def test_speaker_observations_follow_display_order_and_bound_sample():
    from studio_api.speaker_identity import derive_speaker_observations

    observations = derive_speaker_observations(
        [
            Word("speaker-b", 1.0, 2.0),
            Word("speaker-b", 2.1, 12.0),
            Word(None, 3.0, 3.2),
            Word("speaker-a", 20.0, 20.6),
            Word("speaker-a", float("nan"), 21.0),
        ],
        source_offset_seconds=600,
    )

    assert [(item.provider_speaker_label, item.technical_label) for item in observations] == [
        ("speaker-b", "Speaker 1"),
        ("speaker-a", "Speaker 2"),
    ]
    assert observations[0].sample_start_ms == 601_000
    assert observations[0].sample_end_ms == 609_000
    assert observations[1].sample_start_ms == 620_000
    assert observations[1].sample_end_ms == 620_600


def test_persisted_observations_use_job_owner_and_do_not_overwrite_assignment():
    from studio_api.db import Base
    from studio_api.models import (
        Project,
        Source,
        SourceType,
        SpeakerProfile,
        TranscriptionJob,
        TranscriptionJobSource,
        TranscriptionJobSpeaker,
        User,
    )
    from studio_api.speaker_identity import persist_speaker_observations

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc)
    with Session(engine) as db:
        owner = User(id="owner-1", email="owner@example.test")
        project = Project(id="project-1", owner_user_id=owner.id, title="Транскрибации")
        source = Source(
            id="source-1",
            project_id=project.id,
            source_type=SourceType.local_upload,
            original_filename="meeting.mp3",
        )
        job = TranscriptionJob(
            id="job-1",
            project_id=project.id,
            owner_user_id=owner.id,
            media_clip_start_seconds=10,
        )
        relation = TranscriptionJobSource(
            id="job-source-1",
            job_id=job.id,
            source_id=source.id,
            position=0,
        )
        profile = SpeakerProfile(
            id="profile-1",
            owner_user_id=owner.id,
            display_name="Анна",
            normalized_name="анна",
            role="Автор",
        )
        db.add_all([owner, project, source, job, relation, profile])
        db.flush()

        first = persist_speaker_observations(
            db,
            job=job,
            job_source_id=relation.id,
            words=[Word("speaker-1", 1.0, 2.0)],
            now=now,
        )[0]
        db.flush()
        first.speaker_profile_id = profile.id
        first.applied_display_name = profile.display_name
        first.applied_role = profile.role
        first.applied_document_label = "Анна — Автор"
        first.assigned_at = now
        db.flush()

        persisted = persist_speaker_observations(
            db,
            job=job,
            job_source_id=relation.id,
            words=[Word("speaker-1", 40.0, 41.0)],
            now=now,
        )
        db.flush()

        row = db.execute(select(TranscriptionJobSpeaker)).scalar_one()
        assert len(persisted) == 1
        assert row.owner_user_id == owner.id
        assert (row.sample_start_ms, row.sample_end_ms) == (11_000, 12_000)
        assert row.applied_document_label == "Анна — Автор"
    engine.dispose()


def test_speaker_profile_crud_is_owner_scoped_and_soft_deactivates(monkeypatch):
    from fastapi import HTTPException
    from studio_api.db import Base
    from studio_api.main import (
        SpeakerProfileIn,
        SpeakerProfilePatch,
        create_speaker_profile,
        deactivate_speaker_profile,
        list_speaker_profiles,
        update_speaker_profile,
    )
    from studio_api.models import User
    monkeypatch.setattr("studio_api.main.limiter.check", lambda *args, **kwargs: None)

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        owner = User(id="profile-owner-1", email="profile-owner-1@example.test")
        other = User(id="profile-owner-2", email="profile-owner-2@example.test")
        db.add_all([owner, other])
        db.commit()

        created = create_speaker_profile(
            SpeakerProfileIn(display_name="  Анна  ", role=" Автор "),
            pair=(None, owner),
            db=db,
        )
        create_speaker_profile(
            SpeakerProfileIn(display_name="Борис", role="Редактор"),
            pair=(None, other),
            db=db,
        )

        assert list_speaker_profiles(pair=(None, owner), db=db)["profiles"] == [created]
        updated = update_speaker_profile(
            created["id"],
            SpeakerProfilePatch(role="Ведущий автор"),
            pair=(None, owner),
            db=db,
        )
        assert updated["display_name"] == "Анна"
        assert updated["role"] == "Ведущий автор"

        with pytest.raises(HTTPException) as foreign_update:
            update_speaker_profile(
                created["id"],
                SpeakerProfilePatch(role="Чужая роль"),
                pair=(None, other),
                db=db,
            )
        assert foreign_update.value.status_code == 404

        assert deactivate_speaker_profile(created["id"], pair=(None, owner), db=db) == {"ok": True}
        assert list_speaker_profiles(pair=(None, owner), db=db) == {"profiles": []}
        reactivated = create_speaker_profile(
            SpeakerProfileIn(display_name="анна", role="Новая роль"),
            pair=(None, owner),
            db=db,
        )
        assert reactivated["id"] == created["id"]
        assert reactivated["active"] is True
    engine.dispose()


def test_job_payload_exposes_only_safe_speaker_identity_metadata():
    from studio_api.db import Base
    from studio_api.main import job_payload
    from studio_api.models import (
        JobStatus,
        Project,
        Source,
        SourceType,
        SpeakerProfile,
        TranscriptionJob,
        TranscriptionJobSource,
        TranscriptionJobSpeaker,
        User,
    )

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 24, 18, 0, tzinfo=timezone.utc)
    with Session(engine, expire_on_commit=False) as db:
        owner = User(id="history-owner", email="history-owner@example.test")
        project = Project(id="history-project", owner_user_id=owner.id, title="Транскрибации")
        source = Source(id="history-source", project_id=project.id, source_type=SourceType.local_upload, original_filename="call.mp3")
        job = TranscriptionJob(id="history-job", project_id=project.id, owner_user_id=owner.id, status=JobStatus.completed)
        relation = TranscriptionJobSource(id="history-job-source", job_id=job.id, source_id=source.id, position=0)
        profile = SpeakerProfile(id="history-profile", owner_user_id=owner.id, display_name="Анна", normalized_name="анна", role="Автор")
        speaker = TranscriptionJobSpeaker(
            id="history-speaker",
            owner_user_id=owner.id,
            job_id=job.id,
            job_source_id=relation.id,
            provider_speaker_label="provider-secret-label",
            display_ordinal=1,
            sample_start_ms=1000,
            sample_end_ms=2000,
            speaker_profile_id=profile.id,
            applied_display_name="Анна",
            applied_role="Автор",
            applied_document_label="Анна — Автор",
            assigned_at=now,
        )
        db.add_all([owner, project, source, job, relation, profile, speaker])
        db.commit(); db.refresh(job)

        payload = job_payload(job)

        assert payload["speaker_identities"] == [{
            "id": speaker.id,
            "label": "Speaker 1",
            "sample_available": True,
            "profile": {"id": profile.id, "display_name": "Анна", "role": "Автор"},
        }]
        encoded = str(payload)
        assert "provider-secret-label" not in encoded
        assert "sample_start_ms" not in encoded
    engine.dispose()


def test_speaker_sample_is_bounded_owner_scoped_and_not_persisted():
    from studio_api.db import Base
    from studio_api.models import (
        Project,
        Source,
        SourceType,
        SourceUploadStatus,
        TranscriptionJob,
        TranscriptionJobSource,
        TranscriptionJobSpeaker,
        User,
    )
    from studio_api.source_storage import SourceObjectStream
    from studio_api.speaker_sample import (
        SpeakerSampleError,
        SpeakerSampleReason,
        create_speaker_sample_audio,
    )

    class Storage:
        def open_read(self, key):
            assert key == "owner/source.mp3"
            return SourceObjectStream(io.BytesIO(b"source-audio"), "audio/mpeg", 12)

    captured = {}

    def runner(command, **kwargs):
        captured["command"] = command
        captured["input"] = Path(command[command.index("-i") + 1])
        captured["output"] = Path(command[-1])
        captured["output"].write_bytes(b"bounded-mp3")
        return SimpleNamespace(returncode=0)

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 24, 18, 0, tzinfo=timezone.utc)
    with Session(engine) as db:
        owner = User(id="sample-owner", email="sample-owner@example.test")
        project = Project(id="sample-project", owner_user_id=owner.id, title="Транскрибации")
        source = Source(
            id="sample-source",
            project_id=project.id,
            source_type=SourceType.local_upload,
            original_filename="call.mp3",
            s3_bucket="audio-bucket",
            s3_object_key="owner/source.mp3",
            reference_class="audio_processing",
            upload_status=SourceUploadStatus.uploaded,
            expires_at=now.replace(year=2027),
        )
        job = TranscriptionJob(id="sample-job", project_id=project.id, owner_user_id=owner.id)
        relation = TranscriptionJobSource(id="sample-job-source", job_id=job.id, source_id=source.id, position=0)
        speaker = TranscriptionJobSpeaker(
            id="sample-speaker",
            owner_user_id=owner.id,
            job_id=job.id,
            job_source_id=relation.id,
            provider_speaker_label="speaker-a",
            display_ordinal=1,
            sample_start_ms=1250,
            sample_end_ms=6250,
        )
        db.add_all([owner, project, source, job, relation, speaker])
        db.commit()

        selected_buckets = []

        def select_storage(selected_settings):
            selected_buckets.append(selected_settings.source_s3_bucket)
            return Storage()

        sample = create_speaker_sample_audio(
            db,
            owner_user_id=owner.id,
            job_id=job.id,
            speaker_id=speaker.id,
            settings=isolated_storage_settings(),
            storage_factory=select_storage,
            runner=runner,
        )

        assert sample.content == b"bounded-mp3"
        assert sample.media_type == "audio/mpeg"
        assert selected_buckets == ["audio-bucket"]
        assert captured["command"][captured["command"].index("-ss") + 1] == "1.250"
        assert captured["command"][captured["command"].index("-t") + 1] == "5.000"
        assert not captured["input"].exists()
        assert not captured["output"].exists()

        with pytest.raises(SpeakerSampleError) as foreign:
            create_speaker_sample_audio(
                db,
                owner_user_id="other-owner",
                job_id=job.id,
                speaker_id=speaker.id,
                settings=isolated_storage_settings(),
                storage_factory=lambda _: Storage(),
                runner=runner,
            )
        assert foreign.value.reason == SpeakerSampleReason.not_found
    engine.dispose()


def test_manual_assignment_updates_exact_document_headings_and_history_snapshot():
    from studio_api.db import Base
    from studio_api.models import (
        Project,
        Source,
        SourceType,
        SpeakerProfile,
        TranscriptionJob,
        TranscriptionJobOutput,
        TranscriptionJobSource,
        TranscriptionJobSpeaker,
        User,
    )
    from studio_api.speaker_assignment import assign_speaker_profile
    from studio_api.transcript_catalog_standardize import CatalogGoogleDocumentSnapshot

    class Standardizer:
        def __init__(self, document_text):
            self.document_text = document_text
            self.replacements = []

        def read_document(self, *, access_token, document_id):
            assert access_token == "private-token"
            assert document_id == "private-document-id"
            return CatalogGoogleDocumentSnapshot(
                document_id=document_id,
                revision_id="revision-1",
                tab_id="tab-1",
                document_text=self.document_text,
                end_index=len(self.document_text) + 1,
            )

        def replace_document_text(self, *, access_token, snapshot, document_text):
            assert snapshot.revision_id == "revision-1"
            self.replacements.append(document_text)
            self.document_text = document_text

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 24, 18, 30, tzinfo=timezone.utc)
    with Session(engine, expire_on_commit=False) as db:
        owner = User(id="assignment-owner", email="assignment-owner@example.test")
        project = Project(id="assignment-project", owner_user_id=owner.id, title="Транскрибации")
        source = Source(id="assignment-source", project_id=project.id, source_type=SourceType.local_upload, original_filename="call.mp3")
        job = TranscriptionJob(id="assignment-job", project_id=project.id, owner_user_id=owner.id)
        relation = TranscriptionJobSource(id="assignment-job-source", job_id=job.id, source_id=source.id, position=0)
        output = TranscriptionJobOutput(
            id="assignment-output",
            job_id=job.id,
            job_source_id=relation.id,
            document_id="private-document-id",
            web_view_url="https://docs.google.com/document/d/private-document-id/edit",
            output_drive_folder_id="private-folder-id",
            output_kind="google_docs_transcript",
            transcript_standard="transcript_doc_v1.2",
            document_character_count=50,
            document_created_at=now,
            persisted_at=now,
            lease_generation=1,
        )
        profile = SpeakerProfile(id="assignment-profile", owner_user_id=owner.id, display_name="Анна", normalized_name="анна", role="Автор")
        speaker = TranscriptionJobSpeaker(
            id="assignment-speaker",
            owner_user_id=owner.id,
            job_id=job.id,
            job_source_id=relation.id,
            provider_speaker_label="provider-private-label",
            display_ordinal=1,
            sample_start_ms=1000,
            sample_end_ms=2000,
        )
        db.add_all([owner, project, source, job, relation, output, profile, speaker])
        db.commit()

        standardizer = Standardizer("Header\n\nSpeaker 1:\nHello\n\nSpeaker 1:\nAgain\n")
        first = assign_speaker_profile(
            db,
            owner_user_id=owner.id,
            job_id=job.id,
            speaker_id=speaker.id,
            profile_id=profile.id,
            settings=SimpleNamespace(),
            now=now,
            token_resolver=lambda *args, **kwargs: "private-token",
            standardizer=standardizer,
        )
        db.commit()

        assert first.document_changed is True
        assert standardizer.replacements == ["Header\n\nАнна — Автор:\nHello\n\nАнна — Автор:\nAgain\n"]
        assert first.payload["profile"] == {"id": profile.id, "display_name": "Анна", "role": "Автор"}
        assert speaker.applied_document_label == "Анна — Автор"

        second = assign_speaker_profile(
            db,
            owner_user_id=owner.id,
            job_id=job.id,
            speaker_id=speaker.id,
            profile_id=profile.id,
            settings=SimpleNamespace(),
            now=now,
            token_resolver=lambda *args, **kwargs: "private-token",
            standardizer=standardizer,
        )
        assert second.document_changed is False
        assert len(standardizer.replacements) == 1
    engine.dispose()


def test_manual_assignment_rejects_document_without_expected_heading():
    from studio_api.speaker_assignment import (
        SpeakerAssignmentError,
        SpeakerAssignmentReason,
        replace_exact_speaker_heading,
    )

    with pytest.raises(SpeakerAssignmentError) as changed:
        replace_exact_speaker_heading(
            "Header\n\nТекст изменён вручную\n",
            current_heading="Speaker 1:",
            desired_heading="Анна — Автор:",
        )
    assert changed.value.reason == SpeakerAssignmentReason.document_changed
