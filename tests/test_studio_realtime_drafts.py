from __future__ import annotations

import base64
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


class DraftSettings:
    credential_key_id = "test-v1"
    realtime_draft_ttl_seconds = 259200

    @staticmethod
    def master_key_b64() -> str:
        return base64.b64encode(b"d" * 32).decode("ascii")


@pytest.fixture()
def draft_db():
    from studio_api.db import Base
    from studio_api.models import Project, RealtimeTranscriptDraft, User

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[User.__table__, Project.__table__, RealtimeTranscriptDraft.__table__],
    )
    with Session(engine) as db:
        owner = User(id="owner-1", email="owner-1@example.test")
        project = Project(
            id="project-1",
            owner_user_id=owner.id,
            title="Транскрибации",
        )
        other_owner = User(id="owner-2", email="owner-2@example.test")
        other_project = Project(
            id="project-2",
            owner_user_id=other_owner.id,
            title="Чужие транскрибации",
        )
        db.add_all([owner, project, other_owner, other_project])
        db.commit()
        yield db, project, other_project
    engine.dispose()


def test_timed_live_metadata_survives_restart_encrypted_and_revision_protected(draft_db):
    from studio_api.models import RealtimeTranscriptDraft
    from studio_api.realtime_drafts import save_realtime_draft, load_latest_realtime_draft, RealtimeDraftError

    db, project, _ = draft_db
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    metadata = [{"id": "capture.0", "session_id": "session_capture_123456", "start_seconds": 1.25, "end_seconds": 3.5, "speaker": 2}, None]
    kwargs = dict(owner_user_id="owner-1", project=project, client_session_id="session_123456789",
                  revision=1, committed_segments=["Спикер", "Старый фрагмент"], partial="",
                  settings=DraftSettings(), now=now, segment_metadata=metadata)
    saved = save_realtime_draft(db, **kwargs)
    db.commit()
    assert saved.segment_metadata == tuple(metadata)
    row = db.execute(select(RealtimeTranscriptDraft)).scalar_one()
    assert b"capture.0" not in row.ciphertext
    db.expire_all()
    restored = load_latest_realtime_draft(db, owner_user_id="owner-1", project=project,
                                         settings=DraftSettings(), now=now + timedelta(days=90))
    assert restored.segment_metadata == tuple(metadata)
    with pytest.raises(RealtimeDraftError):
        save_realtime_draft(db, **{**kwargs, "segment_metadata": [{**metadata[0], "end_seconds": 4}, None]})


@pytest.mark.parametrize("metadata", [[], [{"id": "x", "start_seconds": -1, "end_seconds": 2}],
    [{"id": "x", "start_seconds": 0, "end_seconds": float("inf")}],
    [{"id": "x", "speaker": True}], [{"id": "x", "raw_audio": "forbidden"}],
    [{"id": "x", "session_id": "../unsafe"}],
    [{"id": "../unsafe"}], [{"id": "x"}, {"id": "x"}]])
def test_live_metadata_rejects_invalid_shape_or_unsafe_timing(draft_db, metadata):
    from studio_api.realtime_drafts import save_realtime_draft, RealtimeDraftError
    db, project, _ = draft_db
    with pytest.raises(RealtimeDraftError):
        save_realtime_draft(db, owner_user_id="owner-1", project=project, client_session_id="session_123456789",
                            revision=1, committed_segments=["Фрагмент"] * max(1, len(metadata)), partial="",
                            settings=DraftSettings(), now=datetime.now(timezone.utc), segment_metadata=metadata)


def test_realtime_draft_schema_is_encrypted_scoped_bounded_and_additive():
    from studio_api.models import RealtimeTranscriptDraft

    table = RealtimeTranscriptDraft.__table__
    assert {
        "owner_user_id",
        "project_id",
        "client_session_id",
        "revision",
        "ciphertext",
        "nonce",
        "key_id",
        "payload_hmac",
        "committed_segment_count",
        "committed_character_count",
        "partial_character_count",
        "expires_at",
    } <= set(table.c.keys())
    assert "plaintext" not in table.c
    assert "transcript" not in table.c
    assert {index.name for index in table.indexes} >= {
        "ix_realtime_drafts_owner_project_updated",
        "ix_realtime_drafts_expiry",
    }

    script = ScriptDirectory.from_config(Config("apps/studio-api/alembic.ini"))
    revision = script.get_revision("0023_realtime_drafts")
    assert revision.down_revision == "0022_account_operability"
    assert script.get_heads() == ["0044_quality_progress"]
    migration = (
        ROOT
        / "apps/studio-api/alembic/versions/0023_realtime_transcript_drafts.py"
    ).read_text(encoding="utf-8")
    assert 'release_safety = "additive"' in migration


def test_realtime_draft_round_trip_is_encrypted_and_revision_monotonic(draft_db):
    from studio_api.models import RealtimeTranscriptDraft
    from studio_api.realtime_drafts import (
        RealtimeDraftError,
        RealtimeDraftReason,
        load_latest_realtime_draft,
        save_realtime_draft,
    )

    db, project, _ = draft_db
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    first = save_realtime_draft(
        db,
        owner_user_id="owner-1",
        project=project,
        client_session_id="session_123456789",
        revision=1,
        committed_segments=["Секретный первый фрагмент"],
        partial="незавершённый текст",
        settings=DraftSettings(),
        now=now,
    )
    db.commit()
    row = db.execute(select(RealtimeTranscriptDraft)).scalar_one()
    assert "Секретный".encode("utf-8") not in row.ciphertext
    assert "незавершённый".encode("utf-8") not in row.ciphertext
    assert row.committed_segment_count == 1
    assert row.committed_character_count == len("Секретный первый фрагмент")
    assert first.expires_at is None

    repeated = save_realtime_draft(
        db,
        owner_user_id="owner-1",
        project=project,
        client_session_id="session_123456789",
        revision=1,
        committed_segments=["Секретный первый фрагмент"],
        partial="незавершённый текст",
        settings=DraftSettings(),
        now=now + timedelta(minutes=1),
    )
    assert repeated.revision == 1

    with pytest.raises(RealtimeDraftError) as changed_same_revision:
        save_realtime_draft(
            db,
            owner_user_id="owner-1",
            project=project,
            client_session_id="session_123456789",
            revision=1,
            committed_segments=["другой текст"],
            partial="",
            settings=DraftSettings(),
            now=now + timedelta(minutes=2),
        )
    assert changed_same_revision.value.reason == RealtimeDraftReason.revision_conflict

    second = save_realtime_draft(
        db,
        owner_user_id="owner-1",
        project=project,
        client_session_id="session_123456789",
        revision=2,
        committed_segments=["Первый", "Второй"],
        partial="",
        settings=DraftSettings(),
        now=now + timedelta(minutes=3),
    )
    db.commit()
    latest = load_latest_realtime_draft(
        db,
        owner_user_id="owner-1",
        project=project,
        settings=DraftSettings(),
        now=now + timedelta(minutes=4),
    )
    assert second.revision == 2
    assert latest is not None
    assert latest.committed_segments == ("Первый", "Второй")
    assert latest.partial == ""

    with pytest.raises(RealtimeDraftError) as stale:
        save_realtime_draft(
            db,
            owner_user_id="owner-1",
            project=project,
            client_session_id="session_123456789",
            revision=1,
            committed_segments=["старый"],
            partial="",
            settings=DraftSettings(),
            now=now + timedelta(minutes=5),
        )
    assert stale.value.reason == RealtimeDraftReason.revision_conflict


def test_realtime_draft_owner_scope_tamper_fail_closed_without_expiry_cleanup(draft_db):
    from studio_api.models import RealtimeTranscriptDraft
    from studio_api.realtime_drafts import (
        RealtimeDraftError,
        RealtimeDraftReason,
        cleanup_expired_realtime_drafts,
        load_latest_realtime_draft,
        save_realtime_draft,
    )

    db, project, other_project = draft_db
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    save_realtime_draft(
        db,
        owner_user_id="owner-1",
        project=project,
        client_session_id="session_123456789",
        revision=1,
        committed_segments=["private transcript"],
        partial="",
        settings=DraftSettings(),
        now=now,
    )
    db.commit()
    row = db.execute(select(RealtimeTranscriptDraft)).scalar_one()
    row.ciphertext = bytes([row.ciphertext[0] ^ 1]) + row.ciphertext[1:]
    db.commit()
    with pytest.raises(RealtimeDraftError) as tampered:
        load_latest_realtime_draft(
            db,
            owner_user_id="owner-1",
            project=project,
            settings=DraftSettings(),
            now=now + timedelta(minutes=1),
        )
    assert tampered.value.reason == RealtimeDraftReason.crypto_failed

    with pytest.raises(RealtimeDraftError) as wrong_owner:
        load_latest_realtime_draft(
            db,
            owner_user_id="owner-1",
            project=other_project,
            settings=DraftSettings(),
            now=now,
        )
    assert wrong_owner.value.reason == RealtimeDraftReason.scope_conflict

    row.expires_at = now - timedelta(seconds=1)
    db.commit()
    assert cleanup_expired_realtime_drafts(db, now=now + timedelta(days=90)) == 0
    db.commit()
    assert db.execute(select(RealtimeTranscriptDraft)).scalar_one().id == row.id


def test_legacy_expired_drafts_survive_restart_and_cleanup_until_explicit_clear(draft_db):
    from studio_api.models import RealtimeTranscriptDraft
    from studio_api.realtime_drafts import cleanup_expired_realtime_drafts, save_realtime_draft, load_latest_realtime_draft, delete_realtime_draft
    db, project, other_project = draft_db
    now = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)
    for index in range(4):
        save_realtime_draft(db, owner_user_id=project.owner_user_id, project=project,
            client_session_id=f"session_{index}_123456789", revision=1,
            committed_segments=[str(index)], partial="", settings=DraftSettings(), now=now + timedelta(minutes=index))
    db.commit()
    from sqlalchemy import update
    # Legacy expiry metadata must not rewrite the user's last edit timestamp.
    db.execute(update(RealtimeTranscriptDraft).values(
        expires_at=now - timedelta(seconds=1), updated_at=RealtimeTranscriptDraft.updated_at))
    db.commit()
    db.expire_all()  # Read fresh persisted ciphertext, not the response object.
    later = now + timedelta(days=90)
    assert cleanup_expired_realtime_drafts(db, now=later, limit=2) == 0
    latest = load_latest_realtime_draft(db, owner_user_id=project.owner_user_id,
        project=project, settings=DraftSettings(), now=later)
    assert latest.committed_segments == ("3",)
    assert not delete_realtime_draft(db, owner_user_id=other_project.owner_user_id,
        project=other_project, client_session_id=latest.client_session_id)
    assert delete_realtime_draft(db, owner_user_id=project.owner_user_id,
        project=project, client_session_id=latest.client_session_id)
    db.commit()
    assert db.query(RealtimeTranscriptDraft).count() == 3
    assert load_latest_realtime_draft(db, owner_user_id=project.owner_user_id,
        project=project, settings=DraftSettings(), now=later).committed_segments == ("2",)
    assert not delete_realtime_draft(db, owner_user_id=project.owner_user_id,
        project=project, client_session_id=latest.client_session_id)


def test_owner_draft_budget_rejects_new_ids_without_losing_existing_text(draft_db):
    from studio_api.realtime_drafts import save_realtime_draft, load_latest_realtime_draft, delete_realtime_draft, RealtimeDraftError
    from studio_api.models import RealtimeTranscriptDraft
    db, project, other_project = draft_db
    settings = DraftSettings()
    settings.realtime_draft_max_count = 2
    settings.realtime_draft_max_storage_bytes = 400
    now = datetime(2026, 10, 3)
    def save(client, revision=1, text="saved text", target=project):
        return save_realtime_draft(db, owner_user_id=target.owner_user_id, project=target,
            client_session_id=client, revision=revision, committed_segments=[text], partial="", settings=settings, now=now)
    save("session_123456789a"); save("session_123456789b"); db.commit()
    with pytest.raises(RealtimeDraftError, match="realtime_draft_storage_limit"):
        save("session_123456789c")
    db.rollback()
    assert db.query(RealtimeTranscriptDraft).count() == 2
    save("session_123456789a", 2, "updated text"); db.commit()
    with pytest.raises(RealtimeDraftError, match="realtime_draft_storage_limit"):
        save("session_123456789a", 3, "x" * 390)
    db.rollback()
    assert db.query(RealtimeTranscriptDraft).filter_by(client_session_id="session_123456789a").one().revision == 2
    save("session_123456789c", target=other_project); db.commit()
    assert delete_realtime_draft(db, owner_user_id=project.owner_user_id, project=project, client_session_id="session_123456789b")
    save("session_123456789c"); db.commit()
    assert db.query(RealtimeTranscriptDraft).count() == 3
