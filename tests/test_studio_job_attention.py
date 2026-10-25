from datetime import datetime, timedelta
from pathlib import Path
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
if "STUDIO_DATABASE_HOST" not in os.environ:
    os.environ.setdefault("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
from studio_api.db import Base
from studio_api.job_attention import confirmed_later_results_query, recent_attention_candidates
from studio_api.models import JobStatus, TranscriptionJob, TranscriptionJobSource, TranscriptionJobOutput, User, Project, Source, SourceType


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([User(id="owner", email="owner@example.test"), User(id="other", email="other@example.test")])
        session.add_all([Project(id="project", owner_user_id="owner", title="Project"), Project(id="other-project", owner_user_id="other", title="Other")])
        session.add_all([Source(id=key, project_id="project", source_type=SourceType.google_drive, original_filename=f"{key}.wav") for key in ["source-a", "source-b", "source-c"]])
        session.flush()
        yield session
    engine.dispose()


def add_job(db, key, *, owner="owner", project="project", sources=("source-a", "source-b"), hours=1, status=JobStatus.completed, start=None, end=None, output=True):
    job = TranscriptionJob(id=key, owner_user_id=owner, project_id=project, status=status, created_at=datetime(2026,9,6)+timedelta(hours=hours), media_clip_start_seconds=start, media_clip_end_seconds=end, title=key)
    db.add(job)
    db.flush()
    for position, source_id in enumerate(sources):
        relation = TranscriptionJobSource(job_id=key, source_id=source_id, position=position)
        db.add(relation)
        db.flush()
        if position == 0 and output:
            db.add(TranscriptionJobOutput(job_id=key, job_source_id=relation.id, document_id=f"doc-{key}", web_view_url=f"https://docs.google.com/document/d/doc-{key}/edit", output_drive_folder_id="synthetic-folder", output_kind="google_docs_transcript", transcript_standard="transcript_doc", document_character_count=12, document_created_at=job.created_at, persisted_at=job.created_at, lease_generation=1))
    db.flush()
    return job


@pytest.mark.parametrize("difference", [
    {"owner":"other"}, {"project":"other-project"}, {"sources":("source-c",)},
    {"sources":("source-b","source-a")}, {"sources":("source-a",)},
    {"sources":()},
    {"hours":0}, {"hours":-1}, {"status":JobStatus.failed},
    {"start":0,"end":12}, {"end":12}, {"output":False},
])
def test_candidates_exclude_different_owner_source_sequence_clip_or_unconfirmed_result(db, difference):
    original = add_job(db,"original",hours=0,status=JobStatus.failed,output=False)
    add_job(db,"matching")
    add_job(db,"rejected",**difference)
    assert [item["id"] for item in recent_attention_candidates(db, original)] == ["matching"]
    assert confirmed_later_results_query(db,original).filter(TranscriptionJob.id=="rejected").first() is None


def test_clip_match_and_recent_order_are_shared_by_listing_and_resolution(db):
    original=add_job(db,"original",hours=0,start=1,end=5,status=JobStatus.failed,output=False)
    add_job(db,"first",hours=1,start=1,end=5)
    add_job(db,"second",hours=2,start=1,end=5)
    add_job(db,"other-clip",hours=3,start=2,end=5)
    assert [item["id"] for item in recent_attention_candidates(db,original)] == ["second","first"]
    assert confirmed_later_results_query(db,original).filter(TranscriptionJob.id=="second").first() is not None


def test_confirmed_yandex_docx_is_a_result_for_attention_recovery(db):
    original = add_job(db, "original", hours=0, status=JobStatus.failed, output=False)
    later = add_job(db, "later", hours=1)
    later.output_provider = "yandex_disk"
    output = db.query(TranscriptionJobOutput).filter_by(job_id=later.id).one()
    output.output_kind = "yandex_disk_docx_transcript"
    db.flush()
    assert [item["id"] for item in recent_attention_candidates(db, original)] == [later.id]
