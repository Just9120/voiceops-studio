from __future__ import annotations
import sys
from datetime import datetime, timedelta
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT/"apps/studio-api"))
@pytest.fixture()
def db():
    from studio_api.db import Base
    import studio_api.models
    engine=create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread":False}, poolclass=StaticPool); Base.metadata.create_all(engine)
    S=sessionmaker(bind=engine, expire_on_commit=False); s=S()
    try: yield s
    finally: s.close(); Base.metadata.drop_all(engine); engine.dispose()

def make_failed(db, sources=1):
    from studio_api import models as m
    now=datetime(2026,1,2,3,4,5)
    u=m.User(email=f"{id(db)}@e.test", role=m.UserRole.user, status=m.UserStatus.active); db.add(u); db.flush()
    p=m.Project(owner_user_id=u.id,title="p"); db.add(p); db.flush()
    j=m.TranscriptionJob(project_id=p.id, owner_user_id=u.id, status=m.JobStatus.failed, error_code="output_reconciliation_required", output_drive_folder_id="folder-private", lease_generation=7, attempt_count=1); db.add(j); db.flush()
    rels=[]
    for i in range(sources):
        src=m.Source(project_id=p.id, source_type=m.SourceType.local_upload, original_filename=f"a{i}.mp3", upload_status=m.SourceUploadStatus.uploaded, s3_object_key="k", uploaded_at=now); db.add(src); db.flush()
        r=m.TranscriptionJobSource(job_id=j.id, source_id=src.id, position=i); db.add(r); db.flush(); rels.append(r)
    db.commit(); return m,u,p,j,rels,now

def add_case(db,m,u,p,j,r,now):
    c=m.TranscriptionOutputReconciliation(owner_user_id=u.id,project_id=p.id,job_id=j.id,job_source_id=r.id,reconciliation_token="or_safeOpaque",lease_generation=7,attempt_number=1,status=m.OutputReconciliationStatus.reconciliation_required,uncertainty_reason="commit_failed",expected_output_drive_folder_id="folder-private",expected_document_title="Title",expected_document_title_hash="h",expected_document_character_count=44,expected_document_sha256="a" * 64,prepared_at=now,creation_started_at=now,created_at=now,updated_at=now); db.add(c); db.commit(); return c

def cand(token="or_safeOpaque", folder="folder-private", mime="application/vnd.google-apps.document", doc="doc-1"):
    from studio_api.job_output_reconciliation import DriveReconciliationCandidate
    return DriveReconciliationCandidate(doc, mime, "https://docs.google.com/document/d/doc-1/edit", (folder,), datetime(2026,1,2,3,4,6), {"studioOutputReconciliationToken": token})

def confirmed_digest(document_id):
    assert document_id == "doc-1"
    return "a" * 64


def test_exact_candidate_persists_and_completes_failed_job(db):
    from studio_api.job_output_reconciliation import check_job_output_reconciliation
    m,u,p,j,rels,now=make_failed(db); case=add_case(db,m,u,p,j,rels[0],now)
    res=check_job_output_reconciliation(db, owner_user_id=u.id, job_id=j.id, lookup=lambda token, folder: [cand(token, folder)], read_digest=confirmed_digest, now=now)
    assert (res.checked,res.resolved,res.unresolved,res.conflicts)==(1,1,0,0)
    out=db.query(m.TranscriptionJobOutput).one(); assert out.job_source_id==rels[0].id and out.document_id=="doc-1"
    assert case.status==m.OutputReconciliationStatus.resolved and j.status==m.JobStatus.completed

@pytest.mark.parametrize("mode", ["legacy", "mismatch", "unavailable"])
def test_reconciliation_preserves_recovery_until_content_is_verified(db, mode):
    from studio_api.google_docs_output import GoogleDocsOutputError, GoogleDocsOutputReason
    from studio_api.job_output_reconciliation import check_job_output_reconciliation

    m, u, p, job, relations, now = make_failed(db)
    case = add_case(db, m, u, p, job, relations[0], now)
    if mode == "legacy":
        case.expected_document_sha256 = None
        db.commit()
    calls = []

    def read_digest(document_id):
        calls.append(document_id)
        if mode == "unavailable":
            raise GoogleDocsOutputError(GoogleDocsOutputReason.timeout)
        return "b" * 64

    result = check_job_output_reconciliation(
        db, owner_user_id=u.id, job_id=job.id, lookup=lambda token, folder: [cand(token, folder)],
        read_digest=read_digest, now=now,
    )
    assert result.resolved == 0
    assert result.unavailable == (mode == "unavailable")
    assert result.unresolved == (mode != "unavailable")
    assert calls == ([] if mode == "legacy" else ["doc-1"])
    assert db.query(m.TranscriptionJobOutput).count() == 0
    assert case.status == m.OutputReconciliationStatus.reconciliation_required
    assert job.status == m.JobStatus.failed


def test_zero_and_multiple_matches_fail_closed(db):
    from studio_api.job_output_reconciliation import check_job_output_reconciliation
    m,u,p,j,rels,now=make_failed(db); c=add_case(db,m,u,p,j,rels[0],now)
    assert check_job_output_reconciliation(db, owner_user_id=u.id, job_id=j.id, lookup=lambda t,f: [], read_digest=confirmed_digest, now=now).unresolved==1
    assert db.query(m.TranscriptionJobOutput).count()==0 and c.status==m.OutputReconciliationStatus.reconciliation_required
    assert check_job_output_reconciliation(db, owner_user_id=u.id, job_id=j.id, lookup=lambda t,f: [cand(doc="a"), cand(doc="b")], read_digest=confirmed_digest, now=now).conflicts==1
    assert db.query(m.TranscriptionJobOutput).count()==0 and c.status==m.OutputReconciliationStatus.conflict

def test_wrong_identity_blocks_without_body_fetch(db):
    from studio_api.job_output_reconciliation import check_job_output_reconciliation
    m,u,p,j,rels,now=make_failed(db); c=add_case(db,m,u,p,j,rels[0],now)
    res=check_job_output_reconciliation(db, owner_user_id=u.id, job_id=j.id, lookup=lambda t,f: [cand(token="wrong")], read_digest=confirmed_digest, now=now)
    assert res.conflicts==1 and db.query(m.TranscriptionJobOutput).count()==0 and c.status==m.OutputReconciliationStatus.conflict


@pytest.mark.parametrize("status,expected", [
    ("reconciliation_required", True),
    ("creation_returned", True),
    ("conflict", True),
    ("prepared", False),
])
def test_reconciliation_availability_filters_prepared_case(db, status, expected):
    from studio_api.job_output_reconciliation import reconciliation_status_payload
    m,u,p,j,rels,now=make_failed(db); c=add_case(db,m,u,p,j,rels[0],now); c.status=m.OutputReconciliationStatus(status); db.commit()
    payload=reconciliation_status_payload(db, owner_user_id=u.id, job_id=j.id)
    assert payload["available"] is expected


def test_no_cases_unavailable(db):
    from studio_api.job_output_reconciliation import reconciliation_status_payload
    m,u,p,j,rels,now=make_failed(db)
    assert reconciliation_status_payload(db, owner_user_id=u.id, job_id=j.id)["available"] is False


@pytest.mark.parametrize("mutation", ["deleted", "expired"])
def test_source_retention_states_do_not_block_verified_reconciliation(db, mutation):
    from studio_api.job_output_reconciliation import check_job_output_reconciliation
    m,u,p,j,rels,now=make_failed(db); case=add_case(db,m,u,p,j,rels[0],now)
    source=db.get(m.Source, rels[0].source_id)
    if mutation == "deleted":
        source.deleted_at=now; source.upload_status=m.SourceUploadStatus.deleted
    else:
        source.expires_at=now-timedelta(days=1); source.upload_status=m.SourceUploadStatus.expired
    db.commit()
    res=check_job_output_reconciliation(db, owner_user_id=u.id, job_id=j.id, lookup=lambda token, folder: [cand(token, folder)], read_digest=confirmed_digest, now=now)
    assert (res.checked,res.resolved,res.conflicts)==(1,1,0)
    assert db.query(m.TranscriptionJobOutput).count()==1


def test_wrong_project_source_blocks_reconciliation(db):
    from studio_api.job_output_reconciliation import OutputReconciliationError, check_job_output_reconciliation
    m,u,p,j,rels,now=make_failed(db); add_case(db,m,u,p,j,rels[0],now)
    other=m.Project(owner_user_id=u.id,title="other"); db.add(other); db.flush()
    db.get(m.Source, rels[0].source_id).project_id=other.id; db.commit()
    res=check_job_output_reconciliation(db, owner_user_id=u.id, job_id=j.id, lookup=lambda token, folder: [cand(token, folder)], read_digest=confirmed_digest, now=now)
    assert res.conflicts == 1 and db.query(m.TranscriptionJobOutput).count()==0


def test_relation_mismatch_blocks_reconciliation(db):
    from studio_api.job_output_reconciliation import check_job_output_reconciliation
    m,u,p,j,rels,now=make_failed(db); c=add_case(db,m,u,p,j,rels[0],now)
    other_job=m.TranscriptionJob(project_id=p.id, owner_user_id=u.id, status=m.JobStatus.failed, output_drive_folder_id="folder-private"); db.add(other_job); db.flush()
    rels[0].job_id=other_job.id; db.commit()
    res=check_job_output_reconciliation(db, owner_user_id=u.id, job_id=j.id, lookup=lambda token, folder: [cand(token, folder)], read_digest=confirmed_digest, now=now)
    assert res.conflicts == 1 and db.query(m.TranscriptionJobOutput).count()==0


def test_missing_source_row_blocks_reconciliation(db):
    from studio_api.job_output_reconciliation import check_job_output_reconciliation
    m,u,p,j,rels,now=make_failed(db); add_case(db,m,u,p,j,rels[0],now)
    db.delete(db.get(m.Source, rels[0].source_id)); db.commit()
    res=check_job_output_reconciliation(db, owner_user_id=u.id, job_id=j.id, lookup=lambda token, folder: [cand(token, folder)], read_digest=confirmed_digest, now=now)
    assert res.conflicts == 1 and db.query(m.TranscriptionJobOutput).count()==0


def test_existing_conflict_is_stable_without_lookup(db):
    from studio_api.job_output_reconciliation import check_job_output_reconciliation, reconciliation_status_payload
    m,u,p,j,rels,now=make_failed(db); c=add_case(db,m,u,p,j,rels[0],now); c.status=m.OutputReconciliationStatus.conflict; db.commit()
    calls=[]
    assert reconciliation_status_payload(db, owner_user_id=u.id, job_id=j.id)["available"] is True
    res=check_job_output_reconciliation(db, owner_user_id=u.id, job_id=j.id, lookup=lambda t,f: calls.append((t,f)) or [], read_digest=confirmed_digest, now=now)
    assert (res.checked,res.resolved,res.unresolved,res.conflicts)==(1,0,0,1)
    assert calls == [] and db.query(m.TranscriptionJobOutput).count()==0
