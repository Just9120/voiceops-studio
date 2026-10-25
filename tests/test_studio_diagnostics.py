from __future__ import annotations

import json, sys, threading, tomllib
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))

@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("STUDIO_COOKIE_SECURE", "false")
    monkeypatch.setenv("STUDIO_APP_ORIGIN", "https://studio.test")

@pytest.fixture()
def db():
    from studio_api.db import Base
    import studio_api.models  # noqa
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close(); Base.metadata.drop_all(engine); engine.dispose()

def user_project_job(db):
    from studio_api import models as m
    u=m.User(email="u@example.com", role=m.UserRole.user, status=m.UserStatus.active); db.add(u); db.flush()
    p=m.Project(owner_user_id=u.id, title="Secret Project"); db.add(p); db.flush()
    j=m.TranscriptionJob(project_id=p.id, owner_user_id=u.id, status=m.JobStatus.queued); db.add(j); db.commit()
    return u,p,j

def uploaded_source(db, project_id):
    from studio_api import models as m
    src=m.Source(project_id=project_id, source_type=m.SourceType.local_upload, original_filename="secret.mp3", mime_type="audio/mpeg", size_bytes=1, s3_bucket="bucket", s3_object_key="private/key", upload_status=m.SourceUploadStatus.uploaded, uploaded_at=datetime(2026,7,16), expires_at=None)
    db.add(src); db.commit()
    return src

def test_model_table_constraints_and_audit_separate(db):
    from studio_api import models as m
    names=set(inspect(db.bind).get_table_names())
    assert "diagnostic_events" in names and "audit_events" in names
    assert {c.name for c in m.DiagnosticEvent.__table__.columns} >= {"owner_user_id","project_id","job_id","level","component","event_code","metadata_json","dedup_fingerprint","expires_at"}
    assert "dedup_fingerprint" not in {c.name for c in m.AuditEvent.__table__.columns}

def test_assembly_failure_is_safe_structured_diagnostic(db):
    from studio_api.diagnostics import write_diagnostic_event
    from studio_api import models as m
    user, project, job = user_project_job(db)
    Session = sessionmaker(bind=db.bind, expire_on_commit=False)
    metadata = {"boundary": "transcript_assembly", "error_code": "transcript_part_words_missing", "retryable": False, "attempt_number": 1}
    result = write_diagnostic_event(owner_user_id=user.id, component="worker", event_code="PROVIDER_REQUEST_FAILED", project_id=project.id, job_id=job.id, metadata=metadata, session_factory=Session)
    assert result.persisted
    row = db.query(m.DiagnosticEvent).filter_by(event_code="PROVIDER_REQUEST_FAILED").one()
    assert json.loads(row.metadata_json) == metadata
    assert not write_diagnostic_event(owner_user_id=user.id, component="worker", event_code="PROVIDER_REQUEST_FAILED", metadata={**metadata, "transcript": "private text"}, session_factory=Session).accepted


def test_writer_sanitizes_retains_and_deduplicates(db, monkeypatch):
    import studio_api.diagnostics as diagnostics
    from studio_api import models as m
    from studio_api.diagnostics import write_diagnostic_event
    u,p,j=user_project_job(db)
    Session=sessionmaker(bind=db.bind, expire_on_commit=False)
    now=datetime(2026,7,16,12,0,0)
    monkeypatch.setattr(diagnostics, "cleanup_expired_diagnostics", lambda *a, **k: None)
    assert write_diagnostic_event(owner_user_id=u.id, component="api", event_code="UNKNOWN", session_factory=Session).accepted is False
    assert write_diagnostic_event(owner_user_id=u.id, component="api", event_code="JOB_CREATED", project_id=p.id, job_id=j.id, metadata={"source_count": 1, "token": "secret"}, session_factory=Session).accepted is False
    assert write_diagnostic_event(owner_user_id=u.id, component="api", event_code="JOB_CREATED", project_id=p.id, job_id=j.id, metadata={"source_count": 1, "credential_selected": True}, session_factory=Session, now=now).persisted
    assert write_diagnostic_event(owner_user_id=u.id, component="api", event_code="JOB_CREATED", project_id=p.id, job_id=j.id, metadata={"source_count": 1, "credential_selected": True}, session_factory=Session, now=now+timedelta(minutes=1)).persisted
    db.expire_all(); row=db.query(m.DiagnosticEvent).one(); db.refresh(row)
    assert row.occurrence_count == 2 and json.loads(row.metadata_json) == {"credential_selected": True, "source_count": 1}
    assert timedelta(days=13, hours=23) < row.expires_at - now <= timedelta(days=14)
    from studio_api.diagnostics import expiry_for
    assert expiry_for("DEBUG", now) - now <= timedelta(hours=24)

def test_unhandled_api_event_registry_accepts_only_safe_aggregate_metadata(db):
    from studio_api import models as m
    from studio_api.diagnostics import write_diagnostic_event
    u,_,_=user_project_job(db)
    Session=sessionmaker(bind=db.bind, expire_on_commit=False)
    result=write_diagnostic_event(owner_user_id=u.id, component="api", event_code="API_UNHANDLED_EXCEPTION", metadata={"endpoint_group":"jobs", "http_status_category":"5xx"}, session_factory=Session)
    assert result.persisted
    row=db.query(m.DiagnosticEvent).filter_by(event_code="API_UNHANDLED_EXCEPTION").one()
    assert row.level == m.DiagnosticLevel.ERROR
    assert json.loads(row.metadata_json) == {"endpoint_group":"jobs", "http_status_category":"5xx"}
    rejected=write_diagnostic_event(owner_user_id=u.id, component="api", event_code="API_UNHANDLED_EXCEPTION", metadata={"endpoint_group":"jobs", "http_status_category":"5xx", "exception":"private"}, session_factory=Session)
    assert rejected.accepted is False
    catalog=write_diagnostic_event(owner_user_id=u.id, component="api", event_code="API_UNHANDLED_EXCEPTION", metadata={"endpoint_group":"transcript_catalog", "http_status_category":"5xx"}, session_factory=Session)
    assert catalog.persisted


def test_google_picker_failure_event_accepts_only_safe_reason(db):
    from studio_api import models as m
    from studio_api.diagnostics import write_diagnostic_event
    u,_,_=user_project_job(db)
    Session=sessionmaker(bind=db.bind, expire_on_commit=False)
    result=write_diagnostic_event(
        owner_user_id=u.id,
        component="api",
        event_code="GOOGLE_PICKER_SESSION_FAILED",
        metadata={
            "reason":"google_reauthorization_required",
            "retryable":False,
            "http_status_category":"4xx",
        },
        session_factory=Session,
    )
    assert result.persisted
    row=db.query(m.DiagnosticEvent).filter_by(event_code="GOOGLE_PICKER_SESSION_FAILED").one()
    assert json.loads(row.metadata_json) == {
        "http_status_category":"4xx",
        "reason":"google_reauthorization_required",
        "retryable":False,
    }
    rejected=write_diagnostic_event(
        owner_user_id=u.id,
        component="api",
        event_code="GOOGLE_PICKER_SESSION_FAILED",
        metadata={
            "reason":"invalid_grant",
            "retryable":False,
            "http_status_category":"4xx",
        },
        session_factory=Session,
    )
    assert rejected.accepted is False


def test_audio_preparation_failure_event_accepts_owned_audio_job_only(db):
    from studio_api import models as m
    from studio_api.diagnostics import write_diagnostic_event

    u, p, _ = user_project_job(db)
    audio_job = m.AudioPreparationJob(
        project_id=p.id,
        owner_user_id=u.id,
        status=m.AudioPreparationStatus.failed,
        title="Audio",
        options_json="{}",
        output_destination="download",
        current_stage="failed",
        progress_percent=45,
    )
    db.add(audio_job); db.commit()
    from sqlalchemy import text
    db.execute(text("PRAGMA foreign_keys = ON"))
    assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1
    Session = sessionmaker(bind=db.bind, expire_on_commit=False)
    metadata = {"error_code": "processing_failed", "stage": "processing", "input_count": 3,
                "ffmpeg_exit_code": 1, "ffmpeg_failure_category": "invalid_arguments"}

    result = write_diagnostic_event(
        owner_user_id=u.id,
        component="worker",
        event_code="AUDIO_PREPARATION_FAILED",
        project_id=p.id,
        job_id=audio_job.id,
        metadata=metadata,
        session_factory=Session,
    )

    assert result.persisted
    row = db.query(m.DiagnosticEvent).filter_by(event_code="AUDIO_PREPARATION_FAILED").one()
    assert row.job_id is None
    assert row.audio_preparation_job_id == audio_job.id
    assert row.operation_job_id == audio_job.id
    assert json.loads(row.metadata_json) == metadata
    assert write_diagnostic_event(owner_user_id=u.id, component="worker", event_code="AUDIO_PREPARATION_FAILED",
        project_id=p.id, job_id=audio_job.id, metadata=metadata, session_factory=Session).persisted
    db.expire_all()
    assert db.query(m.DiagnosticEvent).count() == 1
    assert db.query(m.DiagnosticEvent).one().occurrence_count == 2
    stranger = m.User(email="stranger@example.test")
    db.add(stranger); db.commit()
    assert not write_diagnostic_event(owner_user_id=stranger.id, component="worker", event_code="AUDIO_PREPARATION_FAILED",
        job_id=audio_job.id, metadata=metadata, session_factory=Session).accepted
    transcript = db.query(m.TranscriptionJob).filter_by(owner_user_id=u.id).one()
    assert not write_diagnostic_event(owner_user_id=u.id, component="worker", event_code="AUDIO_PREPARATION_FAILED",
        project_id=p.id, job_id=transcript.id, metadata=metadata, session_factory=Session).accepted
    from studio_api import main
    from fastapi import HTTPException
    query, _, _ = main._diag_filters(db, u, job_id=audio_job.id)
    assert [event.operation_job_id for event in query.all()] == [audio_job.id]
    assert main._diag_payload(query.one())["job_id"] == audio_job.id
    with pytest.raises(HTTPException) as forbidden:
        main._diag_filters(db, stranger, job_id=audio_job.id)
    assert forbidden.value.status_code == 404
    rejected = write_diagnostic_event(
        owner_user_id=u.id,
        component="worker",
        event_code="AUDIO_PREPARATION_FAILED",
        project_id=p.id,
        job_id=audio_job.id,
        metadata={**metadata, "error_code": "private/path.flac"},
        session_factory=Session,
    )
    assert rejected.accepted is False


def test_secret_like_request_and_correlation_ids_are_rejected(db):
    from studio_api import models as m
    from studio_api.diagnostics import valid_correlation_id, valid_request_id, write_diagnostic_event
    u,p,j=user_project_job(db)
    Session=sessionmaker(bind=db.bind, expire_on_commit=False)
    bad_corr = ["corr_sk_live_secret_1234567890", "corr_access_token_abcdefghijklmnop", "corr_refresh_token_abcdefghijklmnop"]
    for value in bad_corr:
        assert not valid_correlation_id(value)
        assert write_diagnostic_event(owner_user_id=u.id, component="api", event_code="JOB_CREATED", project_id=p.id, job_id=j.id, correlation_id=value, metadata={"source_count": 1, "credential_selected": False}, session_factory=Session).accepted is False
    assert not valid_request_id("req_sk_live_secret_1234567890")
    assert write_diagnostic_event(owner_user_id=u.id, component="api", event_code="JOB_CREATED", project_id=p.id, job_id=j.id, request_id="req_sk_live_secret_1234567890", metadata={"source_count": 1, "credential_selected": False}, session_factory=Session).accepted is False
    assert db.query(m.DiagnosticEvent).count() == 0


def test_pwa_failure_correlation_accepts_only_exact_safe_fields(db):
    from studio_api.diagnostics import write_diagnostic_event
    u,p,j=user_project_job(db); Session=sessionmaker(bind=db.bind, expire_on_commit=False)
    accepted=write_diagnostic_event(
        owner_user_id=u.id,
        component="web",
        event_code="PWA_API_REQUEST_FAILED",
        project_id=p.id,
        job_id=j.id,
        metadata={
            "boundary":"api_request",
            "error_code":"api_request_failed",
            "retryable":False,
            "endpoint_group":"transcript_maintenance",
            "http_status_category":"4xx",
            "http_status":422,
            "upstream_request_id":"req_abcdefghijklmnop",
        },
        session_factory=Session,
    )
    assert accepted.accepted is True
    rejected=write_diagnostic_event(
        owner_user_id=u.id,
        component="web",
        event_code="PWA_API_REQUEST_FAILED",
        metadata={"endpoint_group":"jobs", "http_status_category":"4xx", "http_status":404, "upstream_request_id":"Bearer secret"},
        session_factory=Session,
    )
    assert rejected.accepted is False
    unhandled=write_diagnostic_event(
        owner_user_id=u.id,
        component="web",
        event_code="PWA_UNHANDLED_REJECTION",
        metadata={"boundary":"app", "error_code":"unhandled_rejection", "retryable":False, "rejection_category":"type_error"},
        session_factory=Session,
    )
    assert unhandled.accepted is True
    from studio_api.models import DiagnosticEvent
    assert db.query(DiagnosticEvent).count() == 2

def test_event_registry_is_event_specific_and_redacts_values(db):
    from studio_api.diagnostics import sanitize_metadata, write_diagnostic_event
    u,p,j=user_project_job(db)
    Session=sessionmaker(bind=db.bind, expire_on_commit=False)
    assert sanitize_metadata("JOB_CREATED", {"source_count": 1, "credential_selected": False, "attempt_number": 1}) is None
    assert sanitize_metadata("PROCESSING_STARTED", {"attempt_number": 1, "source_count": 1}) is None
    assert sanitize_metadata("PROVIDER_REQUEST_FAILED", {"boundary": "provider_transport", "error_code": "provider_scope_rejected", "provider_error_code": "insufficient_permissions", "retryable": False, "attempt_number": 1, "http_status_category": "4xx", "http_status": 403}) == {
        "attempt_number": 1,
        "boundary": "provider_transport",
        "error_code": "provider_scope_rejected",
        "http_status": 403,
        "http_status_category": "4xx",
        "provider_error_code": "insufficient_permissions",
        "retryable": False,
    }
    assert sanitize_metadata(
        "PROVIDER_REQUEST_FAILED",
        {
            "boundary": "provider_checkpoint",
            "error_code": "provider_part_checkpoint_persistence_failed",
            "retryable": False,
            "attempt_number": 1,
        },
    ) == {
        "attempt_number": 1,
        "boundary": "provider_checkpoint",
        "error_code": "provider_part_checkpoint_persistence_failed",
        "retryable": False,
    }
    assert sanitize_metadata("REALTIME_CAPABILITY_ISSUED", {"model": "scribe_v2_realtime", "expires_in_seconds": 300})
    assert sanitize_metadata("REALTIME_CAPABILITY_FAILED", {"reason": "provider_timeout", "retryable": True, "http_status_category": "5xx"})
    assert sanitize_metadata("API_REQUEST_FAILED", {"endpoint_group": "realtime", "http_status_category": "5xx"})
    assert sanitize_metadata("REALTIME_CAPABILITY_ISSUED", {"model": "scribe_v2", "expires_in_seconds": 300}) is None
    assert sanitize_metadata("REALTIME_CAPABILITY_FAILED", {"reason": "provider_secret", "retryable": False, "http_status_category": "4xx"}) is None
    bad_values = [
        "sk_live_secret_123",
        "Bearer abcdef",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig",
        "user@example.com",
        "https://example.invalid/path",
        "folder/object/key",
        "secret.mp3",
        "first line\nsecond line",
        "Traceback (most recent call last)",
    ]
    for value in bad_values:
        assert sanitize_metadata("PROVIDER_REQUEST_FAILED", {"boundary": "provider_transport", "error_code": value, "retryable": False, "attempt_number": 1}) is None
        assert write_diagnostic_event(owner_user_id=u.id, component="worker", event_code="PROVIDER_REQUEST_FAILED", project_id=p.id, job_id=j.id, metadata={"boundary": value, "error_code": "unknown", "retryable": False, "attempt_number": 1}, session_factory=Session).accepted is False
    assert sanitize_metadata("PROVIDER_REQUEST_FAILED", {"boundary": "provider_transport", "error_code": "provider_scope_rejected", "provider_error_code": "private_dynamic_value", "retryable": False, "attempt_number": 1, "http_status": 403}) is None


def test_provider_diagnostic_allowlists_match_transport_boundary():
    from studio_api.diagnostics import PROVIDER_ERROR_CODES
    from studio_api.elevenlabs_transcription import SAFE_PROVIDER_ERROR_CODES

    assert PROVIDER_ERROR_CODES == SAFE_PROVIDER_ERROR_CODES

def test_writer_scope_ownership_and_project_job_coherence(db):
    from studio_api import models as m
    from studio_api.diagnostics import write_diagnostic_event
    u,p,j=user_project_job(db)
    other=m.User(email="other-scope@example.com", role=m.UserRole.user, status=m.UserStatus.active); db.add(other); db.flush()
    other_project=m.Project(owner_user_id=other.id, title="Other"); db.add(other_project); db.flush()
    other_job=m.TranscriptionJob(project_id=other_project.id, owner_user_id=other.id, status=m.JobStatus.queued); db.add(other_job); db.commit()
    Session=sessionmaker(bind=db.bind, expire_on_commit=False)
    meta={"source_count": 1, "credential_selected": False}
    assert write_diagnostic_event(owner_user_id=u.id, component="api", event_code="JOB_CREATED", project_id=other_project.id, job_id=j.id, metadata=meta, session_factory=Session).accepted is False
    assert write_diagnostic_event(owner_user_id=u.id, component="api", event_code="JOB_CREATED", project_id=p.id, job_id=other_job.id, metadata=meta, session_factory=Session).accepted is False
    assert write_diagnostic_event(owner_user_id=u.id, component="api", event_code="JOB_CREATED", project_id=other_project.id, job_id=other_job.id, metadata=meta, session_factory=Session).accepted is False
    assert db.query(m.DiagnosticEvent).count() == 0

def test_concurrent_dedup_increments_are_not_lost(tmp_path, monkeypatch):
    from studio_api.db import Base
    import studio_api.diagnostics as diagnostics
    import studio_api.models as m
    from studio_api.diagnostics import write_diagnostic_event
    monkeypatch.setattr(diagnostics, "cleanup_expired_diagnostics", lambda *a, **k: None)
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path/'diag.db'}", connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as setup:
        u=m.User(email="concurrent@example.com", role=m.UserRole.user, status=m.UserStatus.active); setup.add(u); setup.flush()
        p=m.Project(owner_user_id=u.id, title="P"); setup.add(p); setup.flush()
        j=m.TranscriptionJob(project_id=p.id, owner_user_id=u.id, status=m.JobStatus.queued); setup.add(j); setup.commit()
        uid,pid,jid=u.id,p.id,j.id
    results=[]
    def write_one():
        results.append(write_diagnostic_event(owner_user_id=uid, component="api", event_code="JOB_CREATED", project_id=pid, job_id=jid, metadata={"source_count": 1, "credential_selected": False}, session_factory=Session, now=datetime(2026,7,16,12,0,0)).persisted)
    threads=[threading.Thread(target=write_one) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    with Session() as check:
        row=check.query(m.DiagnosticEvent).one()
        assert all(results)
        assert row.occurrence_count == 8
    Base.metadata.drop_all(engine); engine.dispose()

def test_writer_failure_does_not_raise_or_commit_caller(db):
    from studio_api import models as m
    from studio_api.diagnostics import write_diagnostic_event
    u,p,j=user_project_job(db)
    pending=m.Project(owner_user_id=u.id, title="caller state"); db.add(pending)
    class BadSession:
        def query(self, *a, **k): raise RuntimeError("boom secret-token")
        def rollback(self): pass
        def close(self): pass
    result=write_diagnostic_event(owner_user_id=u.id, component="api", event_code="JOB_CREATED", project_id=p.id, job_id=j.id, metadata={"source_count": 1, "credential_selected": False}, session_factory=lambda: BadSession())
    assert result.accepted and not result.persisted
    db.rollback()
    assert db.query(m.Project).filter_by(title="caller state").count() == 0

def test_request_ids_headers(monkeypatch, db):
    from fastapi.testclient import TestClient
    import studio_api.main as main
    monkeypatch.setattr(main.limiter, "check", lambda *a, **k: None)
    monkeypatch.setattr(main.limiter, "check", lambda *a, **k: None)
    monkeypatch.setattr(main, "cleanup_expired_diagnostics", lambda *a, **k: None)
    def override_db(): yield db
    main.app.dependency_overrides[main.get_db]=override_db
    client=TestClient(main.app)
    r=client.get("/api/auth/bootstrap-status", headers={"X-Correlation-ID":"bad https://evil.test/token"})
    assert r.headers["X-Request-ID"].startswith("req_")
    assert r.headers["X-Correlation-ID"].startswith("corr_") and "evil" not in r.headers["X-Correlation-ID"]
    good="corr_Abcdefgh1234567890"
    r=client.get("/api/auth/bootstrap-status", headers={"X-Correlation-ID":good})
    assert r.headers["X-Correlation-ID"] == good
    for bad in ["corr_sk_live_secret_1234567890", "corr_access_token_abcdefghijklmnop", "corr_refresh_token_abcdefghijklmnop"]:
        r=client.get("/api/auth/bootstrap-status", headers={"X-Correlation-ID":bad})
        assert r.headers["X-Correlation-ID"].startswith("corr_") and r.headers["X-Correlation-ID"] != bad
        assert "sk_live" not in r.headers["X-Correlation-ID"] and "access_token" not in r.headers["X-Correlation-ID"] and "refresh_token" not in r.headers["X-Correlation-ID"]
    r=client.get("/api/diagnostics/events?page_size=999", headers={"X-Correlation-ID":"Bearer abc"})
    assert r.status_code in {401, 422}
    assert r.headers["X-Request-ID"].startswith("req_")
    assert r.headers["X-Correlation-ID"].startswith("corr_") and "Bearer" not in r.headers["X-Correlation-ID"]
    if not any(
        getattr(route, "path", None) == "/__diagnostics_test_boom"
        for route in main.app.routes
    ):
        @main.app.get("/__diagnostics_test_boom")
        def _diagnostics_test_boom():
            raise RuntimeError("secret stack trace should not escape")
    r=client.get("/__diagnostics_test_boom")
    assert r.status_code == 500 and r.json() == {"detail": "Internal server error"}
    assert r.headers["X-Request-ID"].startswith("req_") and r.headers["X-Correlation-ID"].startswith("corr_")
    assert "secret" not in r.text
    main.app.dependency_overrides.clear()

def test_authenticated_session_marks_owner_and_throttles_activity_writes(db, monkeypatch):
    from studio_api import models as m
    from studio_api.deps import current_session
    from studio_api.security import token_hash, utcnow
    u,_,_=user_project_job(db)
    raw="runtime-session-value"
    session=m.Session(user_id=u.id, token_hash=token_hash(raw), csrf_hash="csrf", expires_at=utcnow()+timedelta(hours=1))
    db.add(session); db.commit()
    request=SimpleNamespace(cookies={"studio_session":raw}, state=SimpleNamespace())
    settings=SimpleNamespace(cookie_name="studio_session", session_last_seen_write_interval_seconds=300)
    commit_calls=0
    original_commit=db.commit
    def counted_commit():
        nonlocal commit_calls
        commit_calls += 1
        original_commit()
    monkeypatch.setattr(db, "commit", counted_commit)
    pair=current_session(request, db=db, settings=settings)
    assert pair == (session, u)
    assert request.state.owner_user_id == u.id
    assert commit_calls == 1
    first_seen=session.last_seen_at
    pair=current_session(request, db=db, settings=settings)
    assert pair == (session, u)
    assert session.last_seen_at == first_seen
    assert commit_calls == 1

def test_unhandled_middleware_emits_safe_owner_event_without_exception_text(monkeypatch, caplog):
    import asyncio
    from starlette.requests import Request
    import studio_api.main as main
    owner="11111111-1111-4111-8111-111111111111"
    events=[]
    monkeypatch.setattr(main, "write_diagnostic_event", lambda **kwargs: events.append(kwargs) or SimpleNamespace(accepted=True, persisted=True))
    caplog.set_level("ERROR", logger="studio_api.api")
    request=Request({"type":"http", "http_version":"1.1", "method":"GET", "scheme":"https", "path":"/api/jobs/private-job-id", "raw_path":b"/api/jobs/private-job-id", "query_string":b"token=private", "headers":[(b"x-correlation-id", b"Bearer private")], "client":("127.0.0.1", 1234), "server":("studio.test", 443)})

    async def fail_after_auth(current_request):
        current_request.state.owner_user_id=owner
        raise RuntimeError("private exception text")

    response=asyncio.run(main.request_correlation_middleware(request, fail_after_auth))
    assert response.status_code == 500
    assert json.loads(response.body) == {"detail":"Internal server error"}
    assert response.headers["X-Request-ID"].startswith("req_")
    assert response.headers["X-Correlation-ID"].startswith("corr_")
    assert response.headers["X-Trace-ID"].startswith("trace_")
    assert events == [{
        "owner_user_id":owner,
        "component":"api",
        "event_code":"API_UNHANDLED_EXCEPTION",
        "trace_id":response.headers["X-Trace-ID"],
        "correlation_id":response.headers["X-Correlation-ID"],
        "request_id":response.headers["X-Request-ID"],
        "metadata":{"endpoint_group":"jobs", "http_status_category":"5xx"},
    }]
    evidence=response.body.decode()+" "+caplog.text+" "+json.dumps(events)
    for forbidden in ["private exception text", "private-job-id", "token=private", "Bearer private"]:
        assert forbidden not in evidence

def test_unhandled_middleware_keeps_diagnostic_writer_failure_non_recursive(monkeypatch, caplog):
    import asyncio
    from starlette.requests import Request
    import studio_api.main as main
    def fail_writer(**kwargs):
        raise RuntimeError("private writer failure")
    monkeypatch.setattr(main, "write_diagnostic_event", fail_writer)
    caplog.set_level("WARNING", logger="studio_api.api")
    request=Request({"type":"http", "http_version":"1.1", "method":"GET", "scheme":"https", "path":"/api/projects/private-project-id", "raw_path":b"/api/projects/private-project-id", "query_string":b"", "headers":[], "client":("127.0.0.1", 1234), "server":("studio.test", 443)})

    async def fail_after_auth(current_request):
        current_request.state.owner_user_id="11111111-1111-4111-8111-111111111111"
        raise RuntimeError("private route failure")

    response=asyncio.run(main.request_correlation_middleware(request, fail_after_auth))
    assert response.status_code == 500
    assert "api_unhandled_diagnostic_write_failed" in caplog.text
    assert "private writer failure" not in caplog.text
    assert "private route failure" not in caplog.text
    assert "private-project-id" not in caplog.text

def test_default_period_signed_cursor_can_be_used_without_repeating_period(db, monkeypatch):
    from fastapi.testclient import TestClient
    import studio_api.main as main
    import studio_api.diagnostics as diagnostics
    from studio_api import models as m
    from studio_api.diagnostics import write_diagnostic_event
    u,p,j=user_project_job(db)
    other=m.User(email="cursor-other@example.com", role=m.UserRole.user, status=m.UserStatus.active); db.add(other); db.commit()
    Session=sessionmaker(bind=db.bind, expire_on_commit=False)
    monkeypatch.setattr(diagnostics, "cleanup_expired_diagnostics", lambda *a, **k: None)
    for i in range(4):
        write_diagnostic_event(owner_user_id=u.id, component="api", event_code="JOB_CREATED", project_id=p.id, job_id=j.id, metadata={"source_count": i+1, "credential_selected": False}, session_factory=Session, now=datetime(2026,7,16,12,i,0))
    sess=m.Session(user_id=u.id, token_hash="hash", csrf_hash="csrf", expires_at=datetime(2027,1,1)); db.add(sess); db.commit()
    def override_db(): yield db
    def override_current(): return sess,u
    main.app.dependency_overrides[main.get_db]=override_db
    main.app.dependency_overrides[main.current_session]=override_current
    monkeypatch.setattr(main, "utcnow", lambda: datetime(2026,7,16,13,0,0))
    monkeypatch.setattr(main.limiter, "check", lambda *a, **k: None)
    monkeypatch.setattr(main, "cleanup_expired_diagnostics", lambda *a, **k: None)
    try:
        client=TestClient(main.app)
        first=client.get("/api/diagnostics/events?page_size=2")
        assert first.status_code == 200 and len(first.json()["events"]) == 2 and first.json()["next_cursor"]
        cursor=first.json()["next_cursor"]
        second=client.get(f"/api/diagnostics/events?page_size=2&cursor={cursor}")
        assert second.status_code == 200 and len(second.json()["events"]) == 2
        assert {e["id"] for e in first.json()["events"]}.isdisjoint({e["id"] for e in second.json()["events"]})
        explicit=client.get(f"/api/diagnostics/events?page_size=2&start={first.json()['period']['start']}&end={first.json()['period']['end']}&cursor={cursor}")
        assert explicit.status_code == 200
        assert client.get(f"/api/diagnostics/events?page_size=2&level=ERROR&cursor={cursor}").status_code == 422
        assert client.get(f"/api/diagnostics/events?page_size=2&cursor={cursor}A").status_code == 422
        other_sess=m.Session(user_id=other.id, token_hash="otherhash", csrf_hash="csrf", expires_at=datetime(2027,1,1)); db.add(other_sess); db.commit()
        main.app.dependency_overrides[main.current_session]=lambda: (other_sess, other)
        assert client.get(f"/api/diagnostics/events?page_size=2&cursor={cursor}").status_code == 422
    finally:
        main.app.dependency_overrides.clear()

def test_query_cursor_system_and_markdown_report(db, monkeypatch):
    from fastapi.testclient import TestClient
    import studio_api.main as main
    import studio_api.diagnostics as diagnostics
    from studio_api import models as m
    from studio_api.diagnostics import write_diagnostic_event
    from studio_api.runtime_observability import RuntimeIdentity
    u,p,j=user_project_job(db)
    other=m.User(email="other@example.com", role=m.UserRole.user, status=m.UserStatus.active); db.add(other); db.commit()
    Session=sessionmaker(bind=db.bind, expire_on_commit=False)
    monkeypatch.setattr(diagnostics, "cleanup_expired_diagnostics", lambda *a, **k: None)
    for i in range(3):
        write_diagnostic_event(owner_user_id=u.id, component="api", event_code="JOB_CREATED", project_id=p.id, job_id=j.id, metadata={"source_count": i+1, "credential_selected": False}, session_factory=Session, now=datetime(2026,7,16,12,i,0))
    write_diagnostic_event(owner_user_id=other.id, component="api", event_code="JOB_CREATED", metadata={"source_count": 1, "credential_selected": False}, session_factory=Session)
    incident_now=datetime(2026,7,17,11,0,0)
    owned_incident=m.OperationalIncident(
        owner_user_id=u.id,
        incident_kind="provider_unavailable",
        severity="warning",
        status="firing",
        summary_code="provider_unavailable",
        first_detected_at=incident_now,
        last_detected_at=incident_now,
        last_transition_at=incident_now,
        created_at=incident_now,
        updated_at=incident_now,
    )
    other_incident=m.OperationalIncident(
        owner_user_id=other.id,
        incident_kind="critical_error",
        severity="critical",
        status="firing",
        summary_code="critical_errors",
        first_detected_at=incident_now,
        last_detected_at=incident_now,
        last_transition_at=incident_now,
        created_at=incident_now,
        updated_at=incident_now,
    )
    db.add_all([owned_incident,other_incident]); db.commit()
    sess=m.Session(user_id=u.id, token_hash="hash", csrf_hash="csrf", expires_at=datetime(2027,1,1)); db.add(sess); db.commit()
    def override_db(): yield db
    def override_current(): return sess,u
    def override_csrf(): return sess,u
    main.app.dependency_overrides[main.get_db]=override_db
    main.app.dependency_overrides[main.current_session]=override_current
    main.app.dependency_overrides[main.require_csrf]=override_csrf
    monkeypatch.setattr(main.limiter, "check", lambda *a, **k: None)
    monkeypatch.setattr(main, "cleanup_expired_diagnostics", lambda *a, **k: None)
    monkeypatch.setattr(main, "utcnow", lambda: datetime(2026,7,17,12,0,0))
    web_identity=RuntimeIdentity("web", "0.1.0", "web-"+"a"*40, "a"*40)
    api_identity=RuntimeIdentity("api", "0.1.0", "api-"+"a"*40, "a"*40)
    monkeypatch.setattr(main, "load_web_runtime_identity", lambda: web_identity)
    monkeypatch.setattr(main, "settings_runtime_identity", lambda *a, **k: api_identity)
    monkeypatch.setattr(main, "load_worker_runtime_status", lambda *a, **k: {"status":"ready", "component":"worker", "release_version":"0.1.0", "build_id":"worker-"+"a"*40, "commit_sha":"a"*40, "heartbeat_age_seconds":5})
    monkeypatch.setattr(main, "database_schema_revision", lambda db: "0026_runtime_component_status")
    monkeypatch.setattr(main, "source_storage_runtime_status", lambda settings: {"status":"ready", "probe":"read_only_head"})
    try:
        client=TestClient(main.app)
        db.expire_all()
        r=client.get("/api/diagnostics/events?page_size=2&start=2026-07-16T00:00:00&end=2026-07-17T00:00:00")
        assert r.status_code == 200 and len(r.json()["events"]) == 2 and r.json()["next_cursor"]
        cursor = r.json()["next_cursor"]
        second=client.get(f"/api/diagnostics/events?page_size=2&start=2026-07-16T00:00:00&end=2026-07-17T00:00:00&cursor={cursor}")
        assert second.status_code == 200 and {e["id"] for e in second.json()["events"]}.isdisjoint({e["id"] for e in r.json()["events"]})
        replacement = "A" if cursor[0] != "A" else "B"
        tampered = replacement + cursor[1:]
        assert tampered != cursor
        assert client.get(f"/api/diagnostics/events?page_size=2&start=2026-07-16T00:00:00&end=2026-07-17T00:00:00&cursor={tampered}").status_code == 422
        assert client.get(f"/api/diagnostics/events?page_size=2&start=2026-07-16T00:00:00&end=2026-07-17T00:00:00&level=ERROR&cursor={cursor}").status_code == 422
        assert client.get("/api/diagnostics/events?cursor=" + ("a"*1201)).status_code == 422
        assert "dedup_fingerprint" not in str(r.json()) and "expires_at" not in str(r.json()) and "other@example.com" not in str(r.json())
        assert client.get("/api/diagnostics/events?start=2026-01-01T00:00:00&end=2026-01-10T00:00:00").status_code == 422
        sysr=client.get("/api/diagnostics/system").json()
        assert set(sysr["build"]) == {"web","api","worker"} and "sqlite" not in str(sysr) and "example.com" not in str(sysr)
        assert sysr["release_version"] == "0.1.0" and sysr["schema_revision"] == "0026_runtime_component_status"
        assert {sysr["components"][key]["commit_sha"] for key in ("web","api","worker")} == {"a"*40}
        assert sysr["health"]["object_storage"] == {"status":"ready", "probe":"read_only_head"}
        assert sysr["alerts"]["api_limit"] == "unavailable"
        assert [row["id"] for row in sysr["alerts"]["incidents"]] == [owned_incident.id]
        incidents=client.get("/api/diagnostics/incidents")
        assert incidents.status_code == 200
        assert [row["id"] for row in incidents.json()["incidents"]] == [owned_incident.id]
        mutation_headers={
            "Origin":"https://studio.test",
            "X-CSRF-Token":"x",
            "X-Trace-ID":"trace_1234567890abcdef",
        }
        assert client.post(
            f"/api/diagnostics/incidents/{other_incident.id}/acknowledge",
            headers=mutation_headers,
        ).status_code == 404
        acknowledged=client.post(
            f"/api/diagnostics/incidents/{owned_incident.id}/acknowledge",
            headers=mutation_headers,
        )
        assert acknowledged.status_code == 200 and acknowledged.json()["status"] == "acknowledged"
        db.expire_all()
        acknowledgement_audit=db.query(m.AuditEvent).filter_by(
            event_type="operational_incident.acknowledged",
            subject_user_id=u.id,
        ).one()
        assert acknowledgement_audit.outcome == "success"
        assert acknowledgement_audit.trace_id == "trace_1234567890abcdef"
        report=client.post("/api/diagnostics/report.md", json={"start":"2026-07-16T00:00:00","end":"2026-07-17T00:00:00","project_id":p.id,"job_id":j.id,"problem_description":"Задача не завершилась","operation_reference":"canary 14:20"}, headers={"Origin":"https://studio.test", "X-CSRF-Token":"x"})
        assert report.status_code == 200
        assert report.headers["content-type"].startswith("text/markdown") and "studio-diagnostics-report.md" in report.headers["content-disposition"]
        text=report.text
        assert "Chronological diagnostic timeline" in text and "Event counts by level" in text and "Задача не завершилась" in text and "canary 14:20" in text and "Secret Project" not in text and "<script" not in text and "http://" not in text and "https://" not in text
        structured_reports = {}
        for extension, media_type in {
            "json": "application/json",
            "yaml": "application/yaml",
            "toml": "application/toml",
        }.items():
            response = client.post(
                f"/api/diagnostics/report.{extension}",
                json={"start":"2026-07-16T00:00:00","end":"2026-07-17T00:00:00","project_id":p.id,"job_id":j.id},
                headers={"Origin":"https://studio.test", "X-CSRF-Token":"x"},
            )
            assert response.status_code == 200, extension
            assert response.headers["content-type"].startswith(media_type)
            assert f"studio-diagnostics-report.{extension}" in response.headers["content-disposition"]
            assert response.headers["cache-control"] == "no-store"
            structured_reports[extension] = response.text
        json_payload = json.loads(structured_reports["json"])
        assert tomllib.loads(structured_reports["toml"]) == json_payload
        assert yaml.safe_load(structured_reports["yaml"]) == json_payload
        assert "Secret Project" not in "".join(structured_reports.values())
    finally:
        main.app.dependency_overrides.clear()

def test_report_requires_real_same_origin_and_csrf(db, monkeypatch):
    from fastapi.testclient import TestClient
    import studio_api.main as main
    import studio_api.deps as deps
    from studio_api import models as m
    from studio_api.security import hash_password
    u,p,j=user_project_job(db)
    password = "synthetic-password-123"
    db.add(m.LocalIdentity(user_id=u.id, password_hash=hash_password(password))); db.commit()
    def override_db(): yield db
    main.app.dependency_overrides[main.get_db]=override_db
    main.app.dependency_overrides[deps.get_db]=override_db
    monkeypatch.setattr(main.limiter, "check", lambda *a, **k: None)
    now = datetime(2026, 7, 16, 12, 0, 0)
    monkeypatch.setattr(main, "utcnow", lambda: now)
    monkeypatch.setattr(main, "expires", lambda days=14: now + timedelta(days=days))
    monkeypatch.setattr(deps, "utcnow", lambda: now)
    try:
        client=TestClient(main.app)
        login_context=client.post("/api/auth/login-context", headers={"Origin":"https://studio.test"})
        assert login_context.status_code == 200
        login=client.post("/api/auth/login", json={"email":u.email, "password":password, "login_csrf_token":login_context.json()["login_csrf_token"]}, headers={"Origin":"https://studio.test"})
        assert login.status_code == 200
        csrf_token = login.json()["csrf_token"]
        payload={"start":"2026-07-16T00:00:00","end":"2026-07-17T00:00:00","project_id":p.id,"job_id":j.id}
        assert client.post("/api/diagnostics/report.md", json=payload, headers={"Origin":"https://evil.test", "X-CSRF-Token":csrf_token}).status_code == 403
        assert client.post("/api/diagnostics/report.md", json=payload, headers={"Origin":"https://studio.test", "X-CSRF-Token":"wrong"}).status_code == 403
        ok=client.post("/api/diagnostics/report.md", json=payload, headers={"Origin":"https://studio.test", "X-CSRF-Token":csrf_token})
        assert ok.status_code == 200
        assert ok.headers["content-type"] == "text/markdown; charset=utf-8"
        assert ok.headers["cache-control"] == "no-store"
    finally:
        main.app.dependency_overrides.clear()

def test_api_job_create_batch_replay_and_cancel_diagnostics(monkeypatch, db):
    from fastapi.testclient import TestClient
    import studio_api.main as main
    from studio_api import models as m
    u,p,_=user_project_job(db)
    p.output_drive_folder_id = "legacy-output-folder"
    p.output_drive_folder_url = "https://drive.google.com/drive/folders/legacy-output-folder"
    p.output_drive_folder_name = "Legacy output"
    cred = m.ProviderCredential(
        user_id=u.id,
        provider=m.CredentialProvider.elevenlabs,
        label="diagnostics-test",
        status=m.CredentialStatus.active,
    )
    db.add(cred)
    db.commit()
    db.refresh(cred)
    s1=uploaded_source(db, p.id); s2=uploaded_source(db, p.id)
    sess=m.Session(user_id=u.id, token_hash="hash", csrf_hash="csrf", expires_at=datetime(2027,1,1)); db.add(sess); db.commit()
    def override_db(): yield db
    def override_current(): return sess,u
    monkeypatch.setitem(main.app.dependency_overrides, main.get_db, override_db)
    monkeypatch.setitem(main.app.dependency_overrides, main.current_session, override_current)
    monkeypatch.setitem(main.app.dependency_overrides, main.require_csrf, override_current)
    monkeypatch.setattr(main.limiter, "check", lambda *a, **k: None)
    events=[]
    def capture(**kw):
        assert db.get(m.TranscriptionJob, kw["job_id"]) is not None
        events.append(kw)
        return SimpleNamespace(accepted=True, persisted=True)
    monkeypatch.setattr(main, "write_diagnostic_event", capture)
    client=TestClient(main.app)
    r=client.post(f"/api/projects/{p.id}/jobs", json={"source_ids":[s1.id]}, headers={"X-Correlation-ID":"corr_abcdefghijklmnop"})
    assert r.status_code == 200
    assert [e["event_code"] for e in events] == ["JOB_CREATED"]
    monkeypatch.setattr(main, "refreshed_google_drive_access_token", lambda db_, user_: "token")
    monkeypatch.setattr(main, "verify_output_folder_selection", lambda token, fid: SimpleNamespace(id=fid, web_view_url=f"https://drive.google.com/drive/folders/{fid}", name="Folder"))
    events.clear()
    batch_body={"provider_credential_id":cred.id,"items":[{"source_id":s1.id,"output_folder_id":"folder-a"},{"source_id":s2.id,"output_folder_id":"folder-b"}]}
    r=client.post(f"/api/projects/{p.id}/jobs/batch", json=batch_body, headers={"Idempotency-Key":"batch-key"})
    assert r.status_code == 200 and [e["event_code"] for e in events] == ["JOB_CREATED","JOB_CREATED"]
    events.clear()
    r=client.post(f"/api/projects/{p.id}/jobs/batch", json=batch_body, headers={"Idempotency-Key":"batch-key"})
    assert r.status_code == 200 and r.json()["replayed"] is True and events == []
    queued=m.TranscriptionJob(project_id=p.id, owner_user_id=u.id, status=m.JobStatus.queued); db.add(queued)
    processing=m.TranscriptionJob(project_id=p.id, owner_user_id=u.id, status=m.JobStatus.processing, lease_owner_id="worker", lease_generation=1); db.add(processing)
    done=m.TranscriptionJob(project_id=p.id, owner_user_id=u.id, status=m.JobStatus.completed); db.add(done); db.commit()
    events.clear(); assert client.post(f"/api/jobs/{queued.id}/cancel").status_code == 200
    assert [e["event_code"] for e in events] == ["JOB_CANCELLED"]
    events.clear(); assert client.post(f"/api/jobs/{processing.id}/cancel").status_code == 200
    assert [e["event_code"] for e in events] == ["JOB_CANCEL_REQUESTED"]
    events.clear(); assert client.post(f"/api/jobs/{done.id}/cancel").status_code == 200
    assert events == []
    monkeypatch.setattr(main, "write_diagnostic_event", lambda **kw: SimpleNamespace(accepted=True, persisted=False))
    s3=uploaded_source(db, p.id)
    assert client.post(f"/api/projects/{p.id}/jobs", json={"source_ids":[s3.id]}).status_code == 200
    main.app.dependency_overrides.clear()
