from __future__ import annotations

import json
import sys
import uuid
import base64
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


@dataclass(frozen=True)
class Settings:
    credential_key_id: str = "credential-key-v1"
    source_max_upload_bytes: int = 1000
    source_s3_bucket: str = "bucket"
    media_duration_warning_seconds: int = 14400
    media_max_duration_seconds: int = 43200
    provider_part_checkpoint_ttl_seconds: int = 86400
    elevenlabs_scribe_v2_rate_per_hour_usd: str = "0.22"
    elevenlabs_pricing_effective_date: date = date(2026, 8, 30)
    elevenlabs_pricing_source: str = "elevenlabs_public_api_pricing"

    def master_key_b64(self) -> str:
        return base64.b64encode(b"1" * 32).decode("ascii")


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setenv("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    from studio_api.db import Base
    import studio_api.models  # noqa
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close(); Base.metadata.drop_all(engine); engine.dispose()


@pytest.fixture()
def models():
    from studio_api import models as m
    return m


def make_job(
    db,
    m,
    *,
    provider="elevenlabs",
    language="en",
    options_json=None,
    source_filename="secret meeting.mp3",
    source_mime_type="audio/mpeg",
):
    from studio_api.security import utcnow
    now = utcnow().replace(tzinfo=None)
    user = m.User(email=f"{uuid.uuid4().hex}-{provider}-{language}@example.com", role=m.UserRole.user, status=m.UserStatus.active)
    db.add(user); db.flush()
    project = m.Project(owner_user_id=user.id, title="p", output_drive_folder_id="folder-private")
    db.add(project); db.flush()
    cred = m.ProviderCredential(user_id=user.id, provider=m.CredentialProvider(provider), label="k", status=m.CredentialStatus.active)
    db.add(cred); db.flush()
    version = m.ProviderCredentialVersion(credential_id=cred.id, version=1, ciphertext=b"ct", nonce=b"nonce", key_id="credential-key-v1", masked_value="masked", fingerprint="fp")
    db.add(version); db.flush(); cred.active_version_id = version.id
    src = m.Source(project_id=project.id, source_type=m.SourceType.local_upload, original_filename=source_filename, mime_type=source_mime_type, size_bytes=5, s3_bucket="bucket", s3_object_key="private/object", upload_status=m.SourceUploadStatus.uploaded, uploaded_at=now, expires_at=now + timedelta(hours=1))
    db.add(src); db.flush()
    job = m.TranscriptionJob(project_id=project.id, owner_user_id=user.id, status=m.JobStatus.processing, provider=provider, provider_credential_id=cred.id, language=language, options_json=options_json, output_drive_folder_id="folder-private", output_drive_folder_url="https://drive.google.com/drive/folders/folder-private", output_drive_folder_name="Private", lease_owner_id="worker", lease_generation=7, claimed_at=now, lease_expires_at=now + timedelta(minutes=5), started_at=now, attempt_count=1)
    db.add(job); db.flush()
    rel = m.TranscriptionJobSource(job_id=job.id, source_id=src.id, position=0)
    db.add(rel); db.flush()
    db.add(m.TranscriptionJobSourceAttempt(owner_user_id=user.id, project_id=project.id, job_id=job.id, job_source_id=rel.id, attempt_number=1, stage=m.SourceAttemptStage.prepared, retry_disposition=m.SourceAttemptRetryDisposition.undetermined, created_at=now, updated_at=now))
    db.commit()
    return user, project, cred, version, src, job, rel, now


def add_accepted_output(
    db,
    m,
    *,
    user,
    project,
    credential,
    source,
    now,
    language="en",
    options_json=None,
):
    job = m.TranscriptionJob(
        project_id=project.id,
        owner_user_id=user.id,
        status=m.JobStatus.completed,
        provider="elevenlabs",
        provider_credential_id=credential.id,
        language=language,
        options_json=options_json,
        finished_at=now,
    )
    db.add(job); db.flush()
    rel = m.TranscriptionJobSource(
        job_id=job.id,
        source_id=source.id,
        position=0,
    )
    db.add(rel); db.flush()
    db.add(
        m.TranscriptionJobOutput(
            job_id=job.id,
            job_source_id=rel.id,
            document_id=f"accepted-{job.id}",
            web_view_url=f"https://docs.google.com/document/d/{job.id}/edit",
            output_drive_folder_id="folder-private",
            output_kind="google_docs_transcript",
            transcript_standard="transcript_doc_v1.2",
            document_character_count=5,
            document_created_at=now,
            persisted_at=now,
            lease_generation=1,
        )
    )
    db.commit()
    return job


def add_linked_catalog_entry(
    db,
    m,
    *,
    user,
    source,
    now,
    settings_status="exact",
):
    exact = settings_status == "exact"
    db.add(
        m.TranscriptCatalogEntry(
            owner_user_id=user.id,
            document_id=f"catalog-{uuid.uuid4().hex}",
            document_name="Linked catalog evidence",
            transcript_standard="transcript_doc_v1.2",
            standard_status=m.TranscriptCatalogDocumentStandardStatus.current,
            settings_status=getattr(
                m.TranscriptCatalogSettingsStatus,
                settings_status,
            ),
            provider="elevenlabs" if exact else None,
            model="scribe_v2" if exact else None,
            language_mode="en" if exact else None,
            diarization_enabled=False if exact else None,
            source_identity_kind=(
                m.TranscriptCatalogSourceIdentityKind.studio_source
            ),
            source_identity_value=source.id,
            imported_at=now,
            updated_at=now,
        )
    )
    db.commit()


def add_provider_attempt(
    db,
    m,
    *,
    user,
    project,
    credential,
    source,
    now,
    language="en",
    status="processing",
    retry_disposition="undetermined",
):
    job_status = getattr(m.JobStatus, status)
    disposition = getattr(
        m.SourceAttemptRetryDisposition,
        retry_disposition,
    )
    job = m.TranscriptionJob(
        project_id=project.id,
        owner_user_id=user.id,
        status=job_status,
        provider="elevenlabs",
        provider_credential_id=credential.id,
        language=language,
        lease_owner_id=(
            "other-worker" if job_status == m.JobStatus.processing else None
        ),
        lease_generation=1,
        claimed_at=now if job_status == m.JobStatus.processing else None,
        lease_expires_at=(
            now + timedelta(minutes=5)
            if job_status == m.JobStatus.processing
            else None
        ),
        started_at=now,
        finished_at=(
            now
            if job_status in {m.JobStatus.failed, m.JobStatus.completed}
            else None
        ),
        attempt_count=1,
    )
    db.add(job); db.flush()
    rel = m.TranscriptionJobSource(
        job_id=job.id,
        source_id=source.id,
        position=0,
    )
    db.add(rel); db.flush()
    db.add(
        m.TranscriptionJobSourceAttempt(
            owner_user_id=user.id,
            project_id=project.id,
            job_id=job.id,
            job_source_id=rel.id,
            attempt_number=1,
            stage=(
                m.SourceAttemptStage.provider_request_started
                if job_status == m.JobStatus.processing
                else (
                    m.SourceAttemptStage.output_persisted
                    if job_status == m.JobStatus.completed
                    else m.SourceAttemptStage.failed
                )
            ),
            retry_disposition=disposition,
            provider_request_started_at=now,
            failed_at=now if job_status == m.JobStatus.failed else None,
            completed_at=(
                now if job_status == m.JobStatus.completed else None
            ),
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    return job


class Secret:
    provider = "elevenlabs"
    credential_version_id = ""
    output_drive_folder_id = "folder-private"
    lease_generation = 7
    def __init__(self, credential_id, version_id, provider="elevenlabs"):
        self.provider = provider; self.credential_version_id = version_id
        self._credential = type("Cred", (), {"credential_id": credential_id})()
        self._closed = False
    @property
    def raw_credential_secret(self):
        if self._closed:
            raise RuntimeError("context_closed")
        return "super-secret-key"
    def close(self):
        self._closed = True
    def __repr__(self):
        return "Secret(<redacted>)"


@contextmanager
def fake_prereq(db, *, job_id, lease_owner_id, lease_generation, settings, now=None, clock=None, **kw):
    job = db.get(kw["models"].TranscriptionJob, job_id)
    handle = Secret(job.provider_credential_id, db.get(kw["models"].ProviderCredential, job.provider_credential_id).active_version_id, provider=job.provider)
    try:
        yield handle
    finally:
        handle.close()


@contextmanager
def fake_source(db, *, job_id, job_source_id, lease_owner_id, lease_generation, settings, now=None, clock=None, **kw):
    from studio_api import models as m
    from studio_api.job_source_materialization import MaterializedJobSource, MaterializedSourceIdentity
    rel = db.get(m.TranscriptionJobSource, job_source_id)
    src = rel.source
    stream = BytesIO(b"audio")
    try:
        yield MaterializedJobSource(MaterializedSourceIdentity(job_id, rel.id, src.id), rel.position, src.original_filename, src.mime_type, 5, stream, source_type=src.source_type.value, source_created_at=src.source_created_at, source_created_at_provenance=src.source_created_at_provenance)
    finally:
        stream.close()


@contextmanager
def fake_media_preparer(**kwargs):
    from studio_api.media_preparation import PreparedMediaInput

    yield PreparedMediaInput(
        filename=kwargs["original_filename"],
        mime_type=kwargs["mime_type"],
        byte_count=kwargs["byte_count"],
        stream=kwargs["stream"],
        duration_seconds=1.0,
    )


class CaptureTransport:
    def __init__(self, mutate=None):
        self.calls = []
        self.mutate = mutate
    def transcribe(self, **kwargs):
        self.calls.append(kwargs)
        if self.mutate:
            self.mutate()
        from studio_api.elevenlabs_transcription import normalize_elevenlabs_transcript_response
        return normalize_elevenlabs_transcript_response({"text": "hello", "words": [{"text": "hello", "start": 0, "end": 1, "type": "word", "speaker_id": "speaker_0"}]})


def run_boundary(db, m, job, rel, transport, now, **kwargs):
    from studio_api.job_elevenlabs_transcription import transcribe_processing_job_source_with_elevenlabs
    kwargs.setdefault("media_preparer", fake_media_preparer)
    return transcribe_processing_job_source_with_elevenlabs(db, job_id=job.id, job_source_id=rel.id, lease_owner_id="worker", lease_generation=7, settings=Settings(), now=now, prerequisites_opener=fake_prereq, source_materializer=fake_source, elevenlabs_transport=transport, models=m, **kwargs)


def test_embedded_local_creation_time_is_persisted_before_provider_call(db, models):
    from studio_api.media_preparation import PreparedMediaBatch, PreparedMediaInput

    _user, _project, _cred, _version, source, job, rel, now = make_job(db, models)
    discovered = datetime(2025, 12, 3, 12, 22, 32, tzinfo=timezone.utc)

    @contextmanager
    def prepare(**kwargs):
        assert kwargs["probe_source_creation_time"] is True
        yield PreparedMediaBatch(
            parts=(
                PreparedMediaInput(
                    filename=kwargs["original_filename"],
                    mime_type=kwargs["mime_type"],
                    byte_count=kwargs["byte_count"],
                    stream=kwargs["stream"],
                    duration_seconds=1.0,
                ),
            ),
            duration_seconds=1.0,
            source_created_at=discovered,
        )

    transport = CaptureTransport()
    with run_boundary(
        db,
        models,
        job,
        rel,
        transport,
        now,
        media_preparer=prepare,
    ):
        pass

    db.refresh(source)
    assert source.source_created_at == discovered.replace(tzinfo=None)
    assert source.source_created_at_provenance == "embedded_media_metadata"
    assert len(transport.calls) == 1


def test_media_preparation_runs_without_an_idle_database_transaction(db, models):
    *_, job, rel, now = make_job(db, models)
    observed = []

    @contextmanager
    def prepare(**kwargs):
        observed.append(db.in_transaction())
        with fake_media_preparer(**kwargs) as prepared:
            yield prepared

    transport = CaptureTransport()
    with run_boundary(
        db,
        models,
        job,
        rel,
        transport,
        now,
        media_preparer=prepare,
    ):
        pass

    assert observed == [False]
    assert len(transport.calls) == 1


def test_request_construction_language_and_redaction():
    from studio_api.elevenlabs_transcription import ElevenLabsTranscriptionTransport
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json={"text": "ok", "words": [{"text": "ok", "speaker_id": "speaker_0"}]})
    stream = BytesIO(b"abc")
    result = ElevenLabsTranscriptionTransport(post=post).transcribe(api_key="secret-key", stream=stream, filename="safe.mp3", mime_type="audio/mpeg", language_code="en")
    assert result.text == "ok"
    assert calls[0][0] == "https://api.elevenlabs.io/v1/speech-to-text"
    kwargs = calls[0][1]
    assert kwargs["headers"] == {"xi-api-key": "secret-key"}
    assert kwargs["files"]["file"] == ("safe.mp3", stream, "audio/mpeg")
    assert kwargs["data"] == {"model_id": "scribe_v2", "no_verbatim": "false", "temperature": "0", "tag_audio_events": "false", "diarize": "false", "use_multi_channel": "false", "timestamps_granularity": "word", "language_code": "en"}
    assert kwargs["timeout"] == 1800.0
    assert "secret-key" not in repr(ElevenLabsTranscriptionTransport(post=post)) and "ok" not in repr(result)
    calls.clear(); ElevenLabsTranscriptionTransport(post=post).transcribe(api_key="k", stream=BytesIO(b"x"), filename="a.mp3", mime_type="audio/mpeg", diarize=True)
    assert calls[0][1]["data"]["diarize"] == "true"
    calls.clear(); ElevenLabsTranscriptionTransport(post=post).transcribe(api_key="k", stream=BytesIO(b"x"), filename="a.mp3", mime_type="audio/mpeg")
    assert "language_code" not in calls[0][1]["data"]


def test_diarized_transport_accepts_silent_part_without_speaker_labels():
    from studio_api.elevenlabs_transcription import ElevenLabsTranscriptionTransport
    transport = ElevenLabsTranscriptionTransport(post=lambda *args, **kwargs: httpx.Response(200, json={"text": "", "words": []}))
    result = transport.transcribe(api_key="synthetic", stream=BytesIO(b"silence"), filename="silent.mp3", mime_type="audio/mpeg", diarize=True)
    assert result.text == ""
    assert result.word_count == 0


def test_diarized_transport_rejects_success_without_speaker_labels():
    from studio_api.elevenlabs_transcription import (
        ElevenLabsTranscriptionError,
        ElevenLabsTranscriptionTransport,
    )

    def post(*args, **kwargs):
        return httpx.Response(200, json={"text": "hello", "words": [{"text": "hello"}]})

    with pytest.raises(ElevenLabsTranscriptionError, match="malformed_provider_response"):
        ElevenLabsTranscriptionTransport(post=post).transcribe(
            api_key="secret-key",
            stream=BytesIO(b"abc"),
            filename="safe.mp3",
            mime_type="audio/mpeg",
            diarize=True,
        )


@pytest.mark.parametrize("provider,module,transport_name,model", [
    ("mistral", "mistral_transcription", "MistralTranscriptionTransport", "voxtral-small-transcribe-3"),
    ("tbank", "tbank_transcription", "TbankTranscriptionTransport", "default"),
    ("gemini", "gemini_transcription", "GeminiTranscriptionTransport", "gemini-3.5-transcribe"),
])
def test_new_provider_dispatch_preserves_identity_and_does_not_use_elevenlabs(db, models, monkeypatch, provider, module, transport_name, model):
    import importlib
    from studio_api import provider_media
    from studio_api.config import Settings as AppSettings
    from studio_api.job_stt_transcription import transcribe_processing_job_source
    _user, _project, _credential, _version, _source, job, rel, now = make_job(db, models,
        provider=provider, language="ru", options_json=json.dumps({"_stt_model": model}))
    settings = SimpleNamespace(**AppSettings(database_url="sqlite:///:memory:", credential_key_id="credential-key-v1").model_dump())
    settings.master_key_b64 = Settings().master_key_b64
    transport = CaptureTransport()
    monkeypatch.setattr(importlib.import_module("studio_api." + module), transport_name, lambda **kw: transport)
    monkeypatch.setattr(provider_media, "whole_file_preparer", lambda selected, **kw: fake_media_preparer)
    with transcribe_processing_job_source(db, job_id=job.id, job_source_id=rel.id, lease_owner_id="worker", lease_generation=7,
        settings=settings, now=now, clock=lambda: now, prerequisites_opener=fake_prereq, source_materializer=fake_source, models=models) as result:
        assert result.text == "hello"
    assert len(transport.calls) == 1
    assert transport.calls[0]["model_id"] == model
    assert transport.calls[0]["language_code"] == "ru"
    assert db.get(models.TranscriptionJob, job.id).provider == provider
    checkpoint = db.query(models.TranscriptionProviderPartCheckpoint).one()
    assert checkpoint.provider == provider and checkpoint.model == model
    assert checkpoint.ciphertext and b"hello" not in checkpoint.ciphertext
    if provider != "gemini":
        setattr(settings, f"{provider}_byok_enabled", False)
        source = db.get(models.Source, rel.source_id)
        source.expires_at = now - timedelta(seconds=1)
        db.get(models.ProviderCredentialVersion, _version.id).ciphertext = None
        job.attempt_count = 2
        db.add(models.TranscriptionJobSourceAttempt(owner_user_id=job.owner_user_id, project_id=job.project_id,
            job_id=job.id, job_source_id=rel.id, attempt_number=2, stage=models.SourceAttemptStage.prepared,
            retry_disposition=models.SourceAttemptRetryDisposition.undetermined, created_at=now, updated_at=now))
        db.commit()
        with transcribe_processing_job_source(db, job_id=job.id, job_source_id=rel.id, lease_owner_id="worker", lease_generation=7,
                settings=settings, clock=lambda: now) as cached:
            assert cached.text == "hello"
        assert len(transport.calls) == 1


def test_successful_single_source_flow_lifetime_and_one_call(db, models):
    *_, job, rel, now = make_job(db, models)
    transport = CaptureTransport()
    with run_boundary(db, models, job, rel, transport, now) as result:
        retained = result; word = result.words[0]
        assert result.text == "hello" and word.text == "hello" and word.start == 0
        assert "hello" not in repr(result) and "super-secret-key" not in repr(result)
    assert len(transport.calls) == 1
    from studio_api.elevenlabs_transcription import ElevenLabsTranscriptionError
    with pytest.raises(ElevenLabsTranscriptionError, match="context_closed"):
        retained.text
    with pytest.raises(ElevenLabsTranscriptionError, match="context_closed"):
        word.text
    assert transport.calls[0]["language_code"] == "en"
    assert transport.calls[0]["filename"] == "secret meeting.mp3"


def test_auto_detect_mode_omits_provider_language_code(db, models):
    *_, job, rel, now = make_job(db, models, language="detect")
    transport = CaptureTransport()

    with run_boundary(db, models, job, rel, transport, now):
        pass

    assert transport.calls[0]["language_code"] is None


def test_diarization_option_reaches_provider_boundary(db, models):
    *_, job, rel, now = make_job(
        db,
        models,
        options_json='{"diarize":true}',
    )
    transport = CaptureTransport()

    @contextmanager
    def prepare(**kwargs):
        assert kwargs["prefer_whole_recording"] is True
        with fake_media_preparer(**kwargs) as prepared:
            yield prepared

    with run_boundary(db, models, job, rel, transport, now, media_preparer=prepare):
        pass

    assert transport.calls[0]["diarize"] is True


def test_existing_accepted_result_blocks_provider_and_is_non_retryable(db, models):
    from studio_api.job_elevenlabs_transcription import (
        JobElevenLabsTranscriptionError,
    )

    user, project, credential, _version, source, job, rel, now = make_job(
        db,
        models,
    )
    add_accepted_output(
        db,
        models,
        user=user,
        project=project,
        credential=credential,
        source=source,
        now=now,
    )
    transport = CaptureTransport()

    with pytest.raises(
        JobElevenLabsTranscriptionError,
        match="existing_result_conflict",
    ):
        with run_boundary(db, models, job, rel, transport, now):
            pass

    assert transport.calls == []
    db.expire_all()
    attempt = (
        db.query(models.TranscriptionJobSourceAttempt)
        .filter_by(job_source_id=rel.id)
        .one()
    )
    assert attempt.failure_code == "existing_result_conflict"
    assert (
        attempt.retry_disposition
        == models.SourceAttemptRetryDisposition.non_retryable
    )


@pytest.mark.parametrize("settings_status", ["exact", "indeterminate"])
def test_linked_catalog_result_blocks_provider_and_is_non_retryable(
    db,
    models,
    settings_status,
):
    from studio_api.job_elevenlabs_transcription import (
        JobElevenLabsTranscriptionError,
    )

    user, _project, _credential, _version, source, job, rel, now = (
        make_job(db, models)
    )
    add_linked_catalog_entry(
        db,
        models,
        user=user,
        source=source,
        now=now,
        settings_status=settings_status,
    )
    transport = CaptureTransport()

    with pytest.raises(
        JobElevenLabsTranscriptionError,
        match="existing_result_conflict",
    ):
        with run_boundary(db, models, job, rel, transport, now):
            pass

    assert transport.calls == []
    db.expire_all()
    attempt = (
        db.query(models.TranscriptionJobSourceAttempt)
        .filter_by(job_source_id=rel.id)
        .one()
    )
    assert attempt.failure_code == "existing_result_conflict"
    assert (
        attempt.retry_disposition
        == models.SourceAttemptRetryDisposition.non_retryable
    )


def test_explicit_reprocess_authority_crosses_existing_result_guard(db, models):
    from studio_api.transcription_options import stored_transcription_options

    user, project, credential, _version, source, job, rel, now = make_job(
        db,
        models,
        options_json=stored_transcription_options(
            False,
            existing_result_reprocess_authorized=True,
        ),
    )
    add_accepted_output(
        db,
        models,
        user=user,
        project=project,
        credential=credential,
        source=source,
        now=now,
    )
    transport = CaptureTransport()

    with run_boundary(db, models, job, rel, transport, now):
        pass

    assert len(transport.calls) == 1


def test_explicit_reprocess_authority_crosses_linked_catalog_guard(db, models):
    from studio_api.transcription_options import stored_transcription_options

    user, _project, _credential, _version, source, job, rel, now = (
        make_job(
            db,
            models,
            options_json=stored_transcription_options(
                False,
                existing_result_reprocess_authorized=True,
            ),
        )
    )
    add_linked_catalog_entry(
        db,
        models,
        user=user,
        source=source,
        now=now,
    )
    transport = CaptureTransport()

    with run_boundary(db, models, job, rel, transport, now):
        pass

    assert len(transport.calls) == 1


def test_explicit_reprocess_does_not_bypass_unresolved_provider_attempt(
    db,
    models,
):
    from studio_api.job_elevenlabs_transcription import (
        JobElevenLabsTranscriptionError,
    )
    from studio_api.transcription_options import stored_transcription_options

    user, project, credential, _version, source, job, rel, now = make_job(
        db,
        models,
        options_json=stored_transcription_options(
            False,
            existing_result_reprocess_authorized=True,
        ),
    )
    add_accepted_output(
        db,
        models,
        user=user,
        project=project,
        credential=credential,
        source=source,
        now=now,
    )
    add_provider_attempt(
        db,
        models,
        user=user,
        project=project,
        credential=credential,
        source=source,
        now=now,
    )
    transport = CaptureTransport()

    with pytest.raises(
        JobElevenLabsTranscriptionError,
        match="existing_result_conflict",
    ):
        with run_boundary(db, models, job, rel, transport, now):
            pass
    assert transport.calls == []


def test_competing_equivalent_provider_attempt_wins_source_serialization(
    db,
    models,
):
    from studio_api.job_elevenlabs_transcription import (
        JobElevenLabsTranscriptionError,
    )

    user, project, credential, _version, source, job, rel, now = make_job(
        db,
        models,
    )
    add_provider_attempt(
        db,
        models,
        user=user,
        project=project,
        credential=credential,
        source=source,
        now=now,
    )
    transport = CaptureTransport()

    with pytest.raises(
        JobElevenLabsTranscriptionError,
        match="existing_result_conflict",
    ):
        with run_boundary(db, models, job, rel, transport, now):
            pass
    assert transport.calls == []


def test_competing_provider_attempt_with_different_settings_does_not_block(
    db,
    models,
):
    user, project, credential, _version, source, job, rel, now = make_job(
        db,
        models,
    )
    add_provider_attempt(
        db,
        models,
        user=user,
        project=project,
        credential=credential,
        source=source,
        now=now,
        language="detect",
    )
    transport = CaptureTransport()

    with run_boundary(db, models, job, rel, transport, now):
        pass
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "retry_disposition,blocked",
    [
        ("provider_outcome_uncertain", False),
        ("provider_result_lost", False),
        ("output_reconciliation_required", True),
        ("retry_safe", False),
    ],
)
def test_failed_provider_attempt_blocks_only_while_outcome_is_unresolved(
    db,
    models,
    retry_disposition,
    blocked,
):
    from studio_api.job_elevenlabs_transcription import (
        JobElevenLabsTranscriptionError,
    )

    user, project, credential, _version, source, job, rel, now = make_job(
        db,
        models,
    )
    add_provider_attempt(
        db,
        models,
        user=user,
        project=project,
        credential=credential,
        source=source,
        now=now,
        status="failed",
        retry_disposition=retry_disposition,
    )
    transport = CaptureTransport()

    if blocked:
        with pytest.raises(
            JobElevenLabsTranscriptionError,
            match="existing_result_conflict",
        ):
            with run_boundary(db, models, job, rel, transport, now):
                pass
        assert transport.calls == []
    else:
        with run_boundary(db, models, job, rel, transport, now):
            pass
        assert len(transport.calls) == 1


def test_worker_allows_new_job_after_owner_acknowledges_no_document(db, models):
    user, project, credential, _version, source, job, rel, now = make_job(
        db, models
    )
    prior = add_provider_attempt(
        db,
        models,
        user=user,
        project=project,
        credential=credential,
        source=source,
        now=now,
        status="failed",
        retry_disposition="output_reconciliation_required",
    )
    prior.history_attention_resolved_at = now
    prior.history_attention_resolution = "acknowledged_no_result"
    prior.terminal_dismissed_at = now
    db.commit()
    transport = CaptureTransport()

    with run_boundary(db, models, job, rel, transport, now):
        pass
    assert len(transport.calls) == 1


def test_completed_attempt_without_accepted_output_fails_closed(db, models):
    from studio_api.job_elevenlabs_transcription import (
        JobElevenLabsTranscriptionError,
    )

    user, project, credential, _version, source, job, rel, now = make_job(
        db,
        models,
    )
    add_provider_attempt(
        db,
        models,
        user=user,
        project=project,
        credential=credential,
        source=source,
        now=now,
        status="completed",
        retry_disposition="completed",
    )
    transport = CaptureTransport()

    with pytest.raises(
        JobElevenLabsTranscriptionError,
        match="existing_result_conflict",
    ):
        with run_boundary(db, models, job, rel, transport, now):
            pass
    assert transport.calls == []


def test_video_is_prepared_before_provider_and_revalidated_after_preparation(db, models):
    from studio_api.job_elevenlabs_transcription import (
        JobElevenLabsTranscriptionError,
    )
    from studio_api.media_preparation import PreparedMediaInput

    *_, job, rel, now = make_job(
        db,
        models,
        source_filename="private meeting.mp4",
        source_mime_type="video/mp4",
    )
    transport = CaptureTransport()
    preparation_calls = []
    preparation_state = {"closed": False}

    @contextmanager
    def prepare(**kwargs):
        preparation_calls.append(kwargs)
        stream = BytesIO(b"prepared-audio")
        try:
                yield PreparedMediaInput(
                    filename="private meeting.m4a",
                    mime_type="audio/mp4",
                    byte_count=14,
                    stream=stream,
                    audio_extracted=True,
                    duration_seconds=1.0,
                )
        finally:
            stream.close()
            preparation_state["closed"] = True

    with run_boundary(
        db,
        models,
        job,
        rel,
        transport,
        now,
        media_preparer=prepare,
    ):
        assert preparation_state["closed"] is True

    assert preparation_calls[0]["mime_type"] == "video/mp4"
    assert preparation_calls[0]["max_output_bytes"] == Settings.source_max_upload_bytes
    assert transport.calls[0]["filename"] == "private meeting.m4a"
    assert transport.calls[0]["mime_type"] == "audio/mp4"

    transport = CaptureTransport()

    @contextmanager
    def prepare_then_cancel(**kwargs):
        job.cancel_requested_at = now
        db.flush()
        stream = BytesIO(b"prepared-audio")
        try:
            yield PreparedMediaInput(
                filename="private meeting.m4a",
                mime_type="audio/mp4",
                byte_count=14,
                stream=stream,
                audio_extracted=True,
            )
        finally:
            stream.close()

    with pytest.raises(
        JobElevenLabsTranscriptionError,
        match="lifecycle_changed_before_provider_call",
    ):
        with run_boundary(
            db,
            models,
            job,
            rel,
            transport,
            now,
            media_preparer=prepare_then_cancel,
        ):
            pass
    assert transport.calls == []


def test_cancel_inside_media_preparation_never_calls_provider(db, models):
    from studio_api.preparation_control import check_preparation_control
    from studio_api.job_elevenlabs_transcription import JobElevenLabsTranscriptionError
    *_, job, rel, now = make_job(db, models)
    transport = CaptureTransport()

    @contextmanager
    def prepare(**kwargs):
        job.cancel_requested_at = now
        db.commit()
        check_preparation_control()
        pytest.fail("preparation must stop immediately")
        yield

    with pytest.raises(JobElevenLabsTranscriptionError, match="lifecycle_changed_before_provider_call"):
        with run_boundary(db, models, job, rel, transport, now, media_preparer=prepare):
            pass
    assert transport.calls == []


def test_immutable_media_clip_reaches_preparation_boundary(db, models):
    from studio_api.media_preparation import PreparedMediaInput

    *_, job, rel, now = make_job(db, models)
    job.media_clip_start_seconds = 610
    job.media_clip_end_seconds = None
    db.commit()
    preparation_calls = []
    transport = CaptureTransport()

    @contextmanager
    def prepare(**kwargs):
        preparation_calls.append(kwargs)
        stream = BytesIO(b"second-project")
        try:
            yield PreparedMediaInput(
                filename="second-project.m4a",
                mime_type="audio/mp4",
                byte_count=14,
                stream=stream,
                duration_seconds=590,
            )
        finally:
            stream.close()

    with run_boundary(
        db,
        models,
        job,
        rel,
        transport,
        now,
        media_preparer=prepare,
    ):
        pass

    assert preparation_calls[0]["media_clip_start_seconds"] == 610
    assert preparation_calls[0]["media_clip_end_seconds"] is None
    assert len(transport.calls) == 1


def test_long_recording_warning_persists_quote_before_any_provider_call(db, models):
    from studio_api.media_preparation import MediaPreparationError, MediaPreparationReason
    from studio_api.job_elevenlabs_transcription import JobElevenLabsTranscriptionError
    from studio_api.long_media_preflight import long_media_preflight_payload
    *_, job, rel, now = make_job(db, models)
    transport = CaptureTransport()
    def prepare(**kwargs):
        raise MediaPreparationError(MediaPreparationReason.media_duration_confirmation_required, duration_seconds=18000)
    with pytest.raises(JobElevenLabsTranscriptionError, match="media_duration_confirmation_required"):
        with run_boundary(db, models, job, rel, transport, now, media_preparer=prepare):
            pytest.fail("Long unconfirmed source must not reach the provider")
    db.refresh(job)
    quote = long_media_preflight_payload(job)
    assert quote["nominal_cost"] == "1.10000000" and quote["source_duration_seconds"] == 18000
    assert transport.calls == [] and "private" not in str(quote)


def test_media_preparation_failure_blocks_provider_with_safe_reason(db, models):
    from studio_api.job_elevenlabs_transcription import (
        JobElevenLabsTranscriptionError,
    )
    from studio_api.media_preparation import (
        MediaPreparationError,
        MediaPreparationReason,
    )

    *_, job, rel, now = make_job(
        db,
        models,
        source_filename="private meeting.mp4",
        source_mime_type="video/mp4",
    )
    transport = CaptureTransport()

    def prepare(**kwargs):
        raise MediaPreparationError(MediaPreparationReason.ffmpeg_unavailable)

    with pytest.raises(
        JobElevenLabsTranscriptionError,
        match="ffmpeg_unavailable",
    ) as exc:
        with run_boundary(
            db,
            models,
            job,
            rel,
            transport,
            now,
            media_preparer=prepare,
        ):
            pass

    assert transport.calls == []
    assert "private" not in str(exc.value)


@pytest.mark.parametrize("empty_index", [0, 1, 2])
def test_merge_preserves_timeline_with_a_silent_part(empty_index):
    from studio_api.elevenlabs_transcription import normalize_elevenlabs_transcript_response as normalize, merge_elevenlabs_transcript_results
    parts = []
    for index in range(3):
        payload = {"text": "", "words": []} if index == empty_index else {
            "text": f"word{index}", "words": [{"text": f"word{index}", "start": 3, "end": 4}],
        }
        parts.append((normalize(payload), index * 8, 2 if index else 0))
    result = merge_elevenlabs_transcript_results(parts)
    assert [word.text for word in result.words] == [f"word{i}" for i in range(3) if i != empty_index]
    assert [word.start for word in result.words] == [i * 8 + 3 for i in range(3) if i != empty_index]


def test_merge_does_not_discard_text_without_words():
    from studio_api.elevenlabs_transcription import normalize_elevenlabs_transcript_response as normalize, merge_elevenlabs_transcript_results, ElevenLabsTranscriptionError
    with pytest.raises(ElevenLabsTranscriptionError) as error:
        merge_elevenlabs_transcript_results(((normalize({"text": "speech", "words": []}), 0, 0),))
    assert error.value.assembly_code == "transcript_part_words_missing"


def test_merge_does_not_accept_an_empty_overall_transcript():
    from studio_api.elevenlabs_transcription import normalize_elevenlabs_transcript_response as normalize, merge_elevenlabs_transcript_results, ElevenLabsTranscriptionError
    with pytest.raises(ElevenLabsTranscriptionError) as error:
        merge_elevenlabs_transcript_results(((normalize({"text": "", "words": []}), 0, 0), (normalize({"text": " ", "words": []}), 8, 2)))
    assert error.value.assembly_code == "transcript_assembly_empty"


def test_single_silent_source_does_not_reach_export(db, models):
    from studio_api.elevenlabs_transcription import normalize_elevenlabs_transcript_response as normalize
    from studio_api.job_elevenlabs_transcription import JobElevenLabsTranscriptionError
    *_, job, rel, now = make_job(db, models)
    class SilentProvider:
        def transcribe(self, **kwargs):
            return normalize({"text": "", "words": []})
    with pytest.raises(JobElevenLabsTranscriptionError, match="malformed_provider_response"):
        with run_boundary(db, models, job, rel, SilentProvider(), now):
            pytest.fail("empty overall transcript cannot authorize export")


def test_chunk_transcripts_merge_in_order_without_duplicate_overlap():
    from studio_api.elevenlabs_transcription import (
        merge_elevenlabs_transcript_results,
        normalize_elevenlabs_transcript_response,
    )

    first = normalize_elevenlabs_transcript_response(
        {
            "text": "Hello world",
            "language_code": "en",
            "language_probability": 0.95,
            "words": [
                {"text": "Hello", "start": 0, "end": 0.5, "speaker_id": "speaker_0"},
                {"text": " world", "start": 9, "end": 10, "speaker_id": "speaker_0"},
            ],
        }
    )
    second = normalize_elevenlabs_transcript_response(
        {
            "text": "world again",
            "language_code": "en",
            "language_probability": 0.8,
            "words": [
                {"text": " world", "start": 1, "end": 2, "speaker_id": "speaker_0"},
                {"text": " again", "start": 2.1, "end": 2.5, "speaker_id": "speaker_0"},
            ],
        }
    )

    merged = merge_elevenlabs_transcript_results(
        ((first, 0, 0), (second, 8, 2)),
    )

    assert merged.text == "Hello world again"
    assert [word.text for word in merged.words] == ["Hello", " world", " again"]
    assert merged.words[-1].start == 10.1
    assert [word.speaker_id for word in merged.words] == ["part_1:speaker_0", "part_1:speaker_0", "part_2:speaker_0"]
    from studio_api.job_google_docs_output import build_speaker_labeled_transcript
    rendered = build_speaker_labeled_transcript(tuple(merged.words), fallback_text=merged.text)
    assert "личность между частями не сопоставлялась" in rendered
    assert "— часть" not in rendered
    assert rendered.startswith("Спикер 1:\nHello world")
    assert "Спикер 2:\nagain\n\nПримечание:" in rendered
    assert rendered.endswith("личность между частями не сопоставлялась.")
    assert merged.detected_language_code == "en"
    assert merged.language_probability == 0.8
    assert "Hello" not in repr(merged)


def test_chunk_merge_uses_timeline_ownership_when_boundary_text_differs():
    from studio_api.elevenlabs_transcription import (
        merge_elevenlabs_transcript_results,
        normalize_elevenlabs_transcript_response,
    )

    first = normalize_elevenlabs_transcript_response(
        {"text": "alpha", "words": [{"text": "alpha", "start": 9, "end": 10}]}
    )
    second = normalize_elevenlabs_transcript_response(
        {
            "text": "alternate beta",
            "words": [
                {"text": "alternate", "start": 0.5, "end": 1.5},
                {"text": " beta", "start": 2.1, "end": 2.5},
            ],
        }
    )

    merged = merge_elevenlabs_transcript_results(
        ((first, 0, 0), (second, 8, 2)),
    )

    assert merged.text == "alpha beta"
    assert [word.start for word in merged.words] == [9, 10.1]


def test_chunk_merge_fails_closed_without_word_timestamps():
    from studio_api.elevenlabs_transcription import (
        ElevenLabsTranscriptionError,
        merge_elevenlabs_transcript_results,
        normalize_elevenlabs_transcript_response,
    )

    first = normalize_elevenlabs_transcript_response(
        {"text": "first", "words": [{"text": "first"}]}
    )
    second = normalize_elevenlabs_transcript_response(
        {"text": "different", "words": [{"text": "different"}]}
    )

    with pytest.raises(ElevenLabsTranscriptionError, match="malformed_provider_response"):
        merge_elevenlabs_transcript_results(((first, 0, 0), (second, 8, 2)))


def test_prepared_parts_reach_provider_in_order_and_merge(db, models):
    from studio_api.elevenlabs_transcription import normalize_elevenlabs_transcript_response
    from studio_api.media_preparation import PreparedMediaBatch, PreparedMediaInput

    *_, job, rel, now = make_job(db, models)
    streams = [BytesIO(b"part-one"), BytesIO(b"part-two")]

    @contextmanager
    def prepare(**kwargs):
        try:
            yield PreparedMediaBatch(
                parts=(
                    PreparedMediaInput(
                        filename="part-001.m4a",
                        mime_type="audio/mp4",
                        byte_count=8,
                        stream=streams[0],
                        part_index=1,
                        part_count=2,
                        duration_seconds=10,
                    ),
                    PreparedMediaInput(
                        filename="part-002.m4a",
                        mime_type="audio/mp4",
                        byte_count=8,
                        stream=streams[1],
                        part_index=2,
                        part_count=2,
                        timeline_offset_seconds=8,
                        duration_seconds=5,
                    ),
                ),
                duration_seconds=13,
                split_reason="duration",
            )
        finally:
            for stream in streams:
                stream.close()

    class PartsTransport:
        def __init__(self):
            self.calls = []

        def transcribe(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return normalize_elevenlabs_transcript_response(
                    {
                        "text": "alpha overlap",
                        "words": [
                            {"text": "alpha", "start": 0, "end": 1},
                            {"text": " overlap", "start": 9, "end": 10},
                        ],
                    }
                )
            return normalize_elevenlabs_transcript_response(
                {
                    "text": "overlap beta",
                    "words": [
                        {"text": " overlap", "start": 1, "end": 2},
                        {"text": " beta", "start": 2.1, "end": 3},
                    ],
                }
            )

    transport = PartsTransport()
    with run_boundary(
        db,
        models,
        job,
        rel,
        transport,
        now,
        media_preparer=prepare,
    ) as result:
        assert result.text == "alpha overlap beta"
        assert result.words[-1].start == 10.1

    assert [call["filename"] for call in transport.calls] == [
        "part-001.m4a",
        "part-002.m4a",
    ]
    db.expire_all()
    attempt = (
        db.query(models.TranscriptionJobSourceAttempt)
        .filter_by(job_source_id=rel.id)
        .one()
    )
    assert attempt.provider_total_parts == 2
    assert attempt.provider_completed_parts == 2
    assert all(stream.closed for stream in streams)


def test_second_part_failure_preserves_encrypted_checkpoint_and_safe_cause(db, models):
    from studio_api.elevenlabs_transcription import (
        ElevenLabsTranscriptionError,
        ElevenLabsTranscriptionReason,
        normalize_elevenlabs_transcript_response,
    )
    from studio_api.job_elevenlabs_transcription import JobElevenLabsTranscriptionError
    from studio_api.media_preparation import PreparedMediaBatch, PreparedMediaInput

    *_, job, rel, now = make_job(db, models)

    @contextmanager
    def prepare(**kwargs):
        streams = [BytesIO(b"one"), BytesIO(b"two")]
        try:
            yield PreparedMediaBatch(
                parts=(
                    PreparedMediaInput("part-001.m4a", "audio/mp4", 3, streams[0], part_count=2, duration_seconds=10),
                    PreparedMediaInput("part-002.m4a", "audio/mp4", 3, streams[1], part_index=2, part_count=2, timeline_offset_seconds=8, duration_seconds=5),
                ),
                duration_seconds=13,
                split_reason="duration",
            )
        finally:
            for stream in streams:
                stream.close()

    class PartialFailureTransport:
        calls = 0

        def transcribe(self, **kwargs):
            self.calls += 1
            if self.calls == 2:
                raise ElevenLabsTranscriptionError(
                    ElevenLabsTranscriptionReason.provider_rate_limited,
                )
            return normalize_elevenlabs_transcript_response(
                {"text": "first", "words": [{"text": "first", "start": 0, "end": 1}]}
            )

    transport = PartialFailureTransport()
    with pytest.raises(JobElevenLabsTranscriptionError, match="partial_provider_result"):
        with run_boundary(
            db,
            models,
            job,
            rel,
            transport,
            now,
            media_preparer=prepare,
        ):
            pass

    db.expire_all()
    attempt = db.query(models.TranscriptionJobSourceAttempt).filter_by(job_source_id=rel.id).one()
    assert transport.calls == 2
    assert attempt.provider_total_parts == 2
    assert attempt.provider_completed_parts == 1
    assert attempt.failure_code == "partial_provider_result"
    assert attempt.provider_failure_code == "provider_rate_limited"
    assert attempt.retry_disposition == models.SourceAttemptRetryDisposition.provider_outcome_uncertain
    checkpoint = db.query(models.TranscriptionProviderPartCheckpoint).one()
    assert checkpoint.part_index == 0
    assert checkpoint.total_parts == 2
    assert b"first" not in checkpoint.ciphertext


@pytest.mark.parametrize("diarize", [False, True])
def test_explicit_partial_resume_calls_only_unfinished_provider_part(db, models, diarize):
    from studio_api.elevenlabs_transcription import (
        ElevenLabsTranscriptionError,
        ElevenLabsTranscriptionReason,
        normalize_elevenlabs_transcript_response,
    )
    from studio_api.job_elevenlabs_transcription import JobElevenLabsTranscriptionError
    from studio_api.job_retry_recovery import (
        compute_explicit_retry_readiness,
        compute_expired_recovery_readiness,
        prepare_current_attempt_sources,
        queue_retry,
    )
    from studio_api.media_preparation import PreparedMediaBatch, PreparedMediaInput

    *_, job, rel, now = make_job(db, models, options_json=json.dumps({"diarize": diarize}))
    preparation_preferences = []

    @contextmanager
    def prepare(**kwargs):
        preparation_preferences.append(kwargs["prefer_whole_recording"])
        streams = [BytesIO(b"one"), BytesIO(b"two")]
        try:
            yield PreparedMediaBatch(
                parts=(
                    PreparedMediaInput("part-001.m4a", "audio/mp4", 3, streams[0], part_count=2, duration_seconds=10),
                    PreparedMediaInput("part-002.m4a", "audio/mp4", 3, streams[1], part_index=2, part_count=2, timeline_offset_seconds=8, duration_seconds=5),
                ),
                duration_seconds=13,
                split_reason="duration",
            )
        finally:
            for stream in streams:
                stream.close()

    class FirstAttemptTransport:
        calls = 0

        def transcribe(self, **kwargs):
            self.calls += 1
            if self.calls == 2:
                raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.provider_rate_limited)
            return normalize_elevenlabs_transcript_response(
                {"text": "alpha", "words": [{"text": "alpha", "start": 0, "end": 1}]}
            )

    with pytest.raises(JobElevenLabsTranscriptionError, match="partial_provider_result"):
        with run_boundary(db, models, job, rel, FirstAttemptTransport(), now, media_preparer=prepare):
            pass

    job.lease_expires_at = now - timedelta(seconds=1)
    automatic = compute_expired_recovery_readiness(db, job, now=now)
    assert automatic.available is False
    assert automatic.reason.value == "provider_outcome_uncertain"
    job.status = models.JobStatus.failed
    job.lease_owner_id = None
    job.lease_expires_at = None
    db.commit()
    readiness = compute_explicit_retry_readiness(db, job, now=now)
    assert readiness.available is True
    assert readiness.reason.value == "partial_provider_resume_available"
    assert readiness.resumable_provider_part_count == 1
    assert readiness.provider_total_part_count == 2
    assert readiness.provider_failure_code == "provider_rate_limited"

    queued = queue_retry(db, owner_user_id=job.owner_user_id, job_id=job.id, now=now)
    assert queued is not None and queued.transitioned is True
    job.status = models.JobStatus.processing
    job.attempt_count = 2
    job.lease_owner_id = "worker"
    job.lease_generation = 7
    job.lease_expires_at = now + timedelta(minutes=5)
    db.commit()
    prepare_current_attempt_sources(
        db,
        job_id=job.id,
        lease_owner_id="worker",
        lease_generation=7,
        now=now,
    )
    db.commit()

    class ResumeTransport:
        calls = 0

        def transcribe(self, **kwargs):
            self.calls += 1
            assert kwargs["filename"] == "part-002.m4a"
            return normalize_elevenlabs_transcript_response(
                {"text": " beta", "words": [{"text": " beta", "start": 2, "end": 3}]}
            )

    transport = ResumeTransport()
    with run_boundary(db, models, job, rel, transport, now, media_preparer=prepare) as result:
        assert result.text == "alpha beta"
    assert transport.calls == 1
    attempt = db.query(models.TranscriptionJobSourceAttempt).filter_by(job_source_id=rel.id, attempt_number=2).one()
    assert attempt.provider_completed_parts == attempt.provider_total_parts == 2
    assert preparation_preferences == [diarize, False]


@pytest.mark.parametrize("checkpoint_state", ["intact", "expired", "missing", "corrupt", "wrong_owner", "wrong_shape"])
def test_complete_checkpoint_restore_never_calls_provider(monkeypatch, db, models, checkpoint_state):
    import studio_api.job_elevenlabs_transcription as boundary
    from studio_api.elevenlabs_transcription import normalize_elevenlabs_transcript_response as normalize, ElevenLabsTranscriptionError, ElevenLabsTranscriptionReason
    from studio_api.job_elevenlabs_transcription import JobElevenLabsTranscriptionError
    from studio_api.job_retry_recovery import compute_explicit_retry_readiness, prepare_current_attempt_sources, queue_retry, requires_provider_cost_confirmation
    from studio_api.media_preparation import PreparedMediaBatch, PreparedMediaInput

    *_, job, rel, now = make_job(db, models)

    @contextmanager
    def prepare(**kwargs):
        with BytesIO(b"one") as first, BytesIO(b"two") as second:
            yield PreparedMediaBatch(parts=(
                PreparedMediaInput("part-001.m4a", "audio/mp4", 3, first, part_count=2, duration_seconds=10),
                PreparedMediaInput("part-002.m4a", "audio/mp4", 3, second, part_index=2, part_count=2, timeline_offset_seconds=8, duration_seconds=5),
            ), duration_seconds=13, split_reason="duration")

    class Provider:
        calls = 0
        def transcribe(self, **kwargs):
            self.calls += 1
            return normalize({"text": "alpha", "words": [{"text": "alpha", "start": 0, "end": 1}]}) if self.calls == 1 else normalize({"text": "", "words": []})

    transport = Provider()
    events = []
    monkeypatch.setattr(boundary, "_emit_provider", lambda db, job_id, code, metadata: events.append((code, metadata)))
    with monkeypatch.context() as failing_merge:
        def crash(*args):
            raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.malformed_provider_response, assembly_code="transcript_part_words_missing")
        failing_merge.setattr(boundary, "merge_elevenlabs_transcript_results", crash)
        with pytest.raises(JobElevenLabsTranscriptionError, match="malformed_provider_response"):
            with run_boundary(db, models, job, rel, transport, now, media_preparer=prepare):
                pass
    assert transport.calls == 2
    failure = next(metadata for code, metadata in events if code == "PROVIDER_REQUEST_FAILED")
    assert failure["boundary"] == "transcript_assembly"
    assert failure["error_code"] == "transcript_part_words_missing"
    original = db.query(models.TranscriptionJobSourceAttempt).filter_by(attempt_number=1).one()
    billed = original.provider_billed_duration_ms
    job.status = models.JobStatus.failed
    job.lease_owner_id = None
    job.lease_expires_at = None
    db.commit()
    readiness = compute_explicit_retry_readiness(db, job, now=now)
    assert readiness.available
    assert readiness.reason.value == "full_provider_restore_available"
    assert readiness.resumable_provider_part_count == readiness.provider_total_part_count == 2
    assert not requires_provider_cost_confirmation(readiness)
    first_checkpoint = db.query(models.TranscriptionProviderPartCheckpoint).filter_by(part_index=0).one()
    expiry = first_checkpoint.expires_at
    first_checkpoint.expires_at = now - timedelta(seconds=1)
    db.flush()
    expired_readiness = compute_explicit_retry_readiness(db, job, now=now)
    assert expired_readiness.available
    assert expired_readiness.reason.value == "full_provider_restore_available"
    first_checkpoint.expires_at = expiry
    db.flush()
    assert queue_retry(db, owner_user_id=job.owner_user_id, job_id=job.id, now=now).transitioned
    job.status = models.JobStatus.processing
    job.attempt_count = 2
    job.lease_owner_id = "worker"
    job.lease_generation = 7
    job.lease_expires_at = now + timedelta(minutes=5)
    prepare_current_attempt_sources(db, job_id=job.id, lease_owner_id="worker", lease_generation=7, now=now)
    rows = db.query(models.TranscriptionProviderPartCheckpoint).order_by(models.TranscriptionProviderPartCheckpoint.part_index).all()
    if checkpoint_state == "expired":
        rows[0].expires_at = now - timedelta(seconds=1)
    elif checkpoint_state == "missing":
        db.delete(rows[0])
    elif checkpoint_state == "corrupt":
        rows[0].ciphertext = b"invalid"
    elif checkpoint_state == "wrong_owner":
        rows[0].owner_user_id = "other-owner"
    elif checkpoint_state == "wrong_shape":
        rows[0].timeline_offset_seconds = 1
    db.commit()

    class NeverCallProvider:
        def transcribe(self, **kwargs):
            pytest.fail("restore must not submit paid STT")

    if checkpoint_state in {"intact", "expired"}:
        with run_boundary(db, models, job, rel, NeverCallProvider(), now, media_preparer=prepare) as result:
            assert result.text == "alpha"
        restored = db.query(models.TranscriptionJobSourceAttempt).filter_by(attempt_number=2).one()
        assert restored.provider_completed_parts == restored.provider_total_parts == 2
        assert int(restored.provider_billed_duration_ms or 0) == 0
    else:
        with pytest.raises(JobElevenLabsTranscriptionError, match="retry_state_persistence_failed"):
            with run_boundary(db, models, job, rel, NeverCallProvider(), now, media_preparer=prepare):
                pass
        if checkpoint_state == "missing":
            job.status = models.JobStatus.failed
            job.lease_owner_id = None
            job.lease_expires_at = None
            db.commit()
            unavailable = compute_explicit_retry_readiness(db, job, now=now)
            assert not unavailable.available
            assert unavailable.reason.value == "provider_result_lost"
    assert original.provider_billed_duration_ms == billed


def test_single_part_export_failure_restores_after_30_days_without_new_stt(monkeypatch, db, models):
    from studio_api.job_retry_recovery import compute_explicit_retry_readiness, prepare_current_attempt_sources, queue_retry, requires_provider_cost_confirmation
    from studio_api.elevenlabs_transcription import normalize_elevenlabs_transcript_response
    *_, job, rel, now = make_job(db, models)

    class Provider:
        calls = 0
        def transcribe(self, **kwargs):
            self.calls += 1
            return normalize_elevenlabs_transcript_response({"text": "saved words", "words": [{"text": "saved words", "start": 0, "end": 1}]})

    provider = Provider()
    with run_boundary(db, models, job, rel, provider, now) as transcript:
        assert transcript.text == "saved words"
    assert provider.calls == 1
    checkpoint = db.query(models.TranscriptionProviderPartCheckpoint).one()
    assert checkpoint.total_parts == 1
    assert checkpoint.expires_at is None
    assert b"saved words" not in checkpoint.ciphertext
    # STT returned, then document creation failed. No full output is recorded.
    job.status = models.JobStatus.failed
    job.lease_owner_id = job.lease_expires_at = None
    db.commit()
    later = now + timedelta(days=30)
    db.expire_all()
    ready = compute_explicit_retry_readiness(db, job, now=later)
    assert ready.available and ready.reason.value == "full_provider_restore_available"
    assert not requires_provider_cost_confirmation(ready)
    assert queue_retry(db, owner_user_id=job.owner_user_id, job_id=job.id, now=later).transitioned
    job.status = models.JobStatus.processing
    job.attempt_count = 2
    job.lease_owner_id = "worker"
    job.lease_generation = 7
    job.lease_expires_at = later + timedelta(minutes=5)
    prepare_current_attempt_sources(db, job_id=job.id, lease_owner_id="worker", lease_generation=7, now=later)

    class NoNewSTT:
        def transcribe(self, **kwargs):
            pytest.fail("export recovery must not submit another STT request")

    def no_source_or_credential_io(**kwargs):
        pytest.fail("export recovery must not read source bytes or provider credentials")

    monkeypatch.setattr(sys.modules[__name__], "fake_source", no_source_or_credential_io)
    monkeypatch.setattr(sys.modules[__name__], "fake_prereq", no_source_or_credential_io)

    with run_boundary(db, models, job, rel, NoNewSTT(), later, media_preparer=no_source_or_credential_io) as restored:
        assert restored.text == "saved words"
    assert provider.calls == 1
    second = db.query(models.TranscriptionJobSourceAttempt).filter_by(attempt_number=2).one()
    assert second.provider_completed_parts == second.provider_total_parts == 1
    assert int(second.provider_billed_duration_ms or 0) == 0


def test_diagnostics_source_provider_success_order_and_correlation(monkeypatch, db, models):
    import studio_api.job_elevenlabs_transcription as mod
    *_, job, rel, now = make_job(db, models)
    job.attempt_count = 1; db.commit()
    events = []
    monkeypatch.setattr(mod, "resolve_job_correlation_id", lambda **kw: "corr_abcdefghijklmnop")
    monkeypatch.setattr(mod, "write_diagnostic_event", lambda **kw: events.append(kw) or SimpleNamespace(accepted=True, persisted=True))
    with run_boundary(db, models, job, rel, CaptureTransport(), now):
        pass
    assert [e["event_code"] for e in events] == [
        "SOURCE_VALIDATION_STARTED",
        "SOURCE_READY",
        "PROVIDER_REQUEST_STARTED",
        "PROVIDER_USAGE_CONFIRMED",
        "PROVIDER_REQUEST_COMPLETED",
    ]
    assert all(e["correlation_id"] == "corr_abcdefghijklmnop" and e.get("request_id") is None for e in events)


def test_diagnostics_provider_mapped_and_unexpected_failures(monkeypatch, db, models):
    import studio_api.job_elevenlabs_transcription as mod
    from studio_api.elevenlabs_transcription import ElevenLabsTranscriptionError, ElevenLabsTranscriptionReason
    from studio_api.job_elevenlabs_transcription import JobElevenLabsTranscriptionError
    *_, job, rel, now = make_job(db, models)
    job.attempt_count = 1; db.commit()
    events = []
    monkeypatch.setattr(mod, "resolve_job_correlation_id", lambda **kw: "corr_abcdefghijklmnop")
    monkeypatch.setattr(mod, "write_diagnostic_event", lambda **kw: events.append(kw) or SimpleNamespace(accepted=True, persisted=True))
    class MappedFailure:
        def transcribe(self, **kwargs):
            raise ElevenLabsTranscriptionError(
                ElevenLabsTranscriptionReason.provider_scope_rejected,
                provider_error_code="insufficient_permissions",
                http_status=403,
            )
    with pytest.raises(JobElevenLabsTranscriptionError, match="provider_scope_rejected"):
        with run_boundary(db, models, job, rel, MappedFailure(), now):
            pass
    assert [e["event_code"] for e in events] == ["SOURCE_VALIDATION_STARTED", "SOURCE_READY", "PROVIDER_REQUEST_STARTED", "PROVIDER_REQUEST_FAILED"]
    assert events[-1]["metadata"] == {
        "boundary": "provider_transport",
        "error_code": "provider_scope_rejected",
        "provider_error_code": "insufficient_permissions",
        "retryable": False,
        "attempt_number": job.attempt_count or 0,
        "http_status": 403,
        "http_status_category": "4xx",
    }
    events.clear()
    *_, job, rel, now = make_job(db, models)
    class UnexpectedFailure:
        def transcribe(self, **kwargs):
            raise RuntimeError("raw secret provider payload")
    with pytest.raises(JobElevenLabsTranscriptionError, match="provider_unavailable"):
        with run_boundary(db, models, job, rel, UnexpectedFailure(), now):
            pass
    assert [e["event_code"] for e in events] == ["SOURCE_VALIDATION_STARTED", "SOURCE_READY", "PROVIDER_REQUEST_STARTED", "PROVIDER_REQUEST_FAILED"]
    assert events[-1]["metadata"]["error_code"] == "unknown"


@pytest.mark.parametrize("mutate,reason", [
    (lambda m, project, cred, version, src, job, rel, now: setattr(job, "lease_owner_id", "other"), "lifecycle_changed_before_provider_call"),
    (lambda m, project, cred, version, src, job, rel, now: setattr(job, "cancel_requested_at", now), "lifecycle_changed_before_provider_call"),
    (lambda m, project, cred, version, src, job, rel, now: setattr(cred, "active_version_id", "replaced"), "credential_or_output_identity_changed_before_provider_call"),
    (lambda m, project, cred, version, src, job, rel, now: setattr(job, "output_drive_folder_id", "changed"), "credential_or_output_identity_changed_before_provider_call"),
    (lambda m, project, cred, version, src, job, rel, now: setattr(rel, "status", m.JobSourceStatus.skipped), "lifecycle_changed_before_provider_call"),
])
def test_pre_provider_revalidation_blocks_transport(db, models, mutate, reason):
    user, project, cred, version, src, job, rel, now = make_job(db, models)
    def materializer(*args, **kwargs):
        cm = fake_source(*args, **kwargs)
        class Wrapper:
            def __enter__(self):
                handle = cm.__enter__(); mutate(models, project, cred, version, src, job, rel, now); db.commit(); return handle
            def __exit__(self, *exc):
                return cm.__exit__(*exc)
        return Wrapper()
    from studio_api.job_elevenlabs_transcription import JobElevenLabsTranscriptionError, transcribe_processing_job_source_with_elevenlabs
    transport = CaptureTransport()
    with pytest.raises(JobElevenLabsTranscriptionError, match=reason):
        with transcribe_processing_job_source_with_elevenlabs(db, job_id=job.id, job_source_id=rel.id, lease_owner_id="worker", lease_generation=7, settings=Settings(), now=now, prerequisites_opener=fake_prereq, source_materializer=materializer, media_preparer=fake_media_preparer, elevenlabs_transport=transport, models=models):
            pass
    assert transport.calls == []


def test_provider_mismatch_blocks_before_transport(db, models):
    *_, job, rel, now = make_job(db, models, provider="openai")
    transport = CaptureTransport()
    from studio_api.job_elevenlabs_transcription import JobElevenLabsTranscriptionError
    with pytest.raises(JobElevenLabsTranscriptionError, match="provider_mismatch"):
        with run_boundary(db, models, job, rel, transport, now):
            pass
    assert transport.calls == []


def test_post_provider_lifecycle_change_discards_result_and_no_retry(db, models):
    user, project, cred, version, src, job, rel, now = make_job(db, models)
    transport = CaptureTransport(mutate=lambda: (setattr(job, "cancel_requested_at", now), db.flush()))
    from studio_api.job_elevenlabs_transcription import JobElevenLabsTranscriptionError
    with pytest.raises(JobElevenLabsTranscriptionError, match="lifecycle_changed_after_provider_call"):
        with run_boundary(db, models, job, rel, transport, now):
            pass
    assert len(transport.calls) == 1


def test_caller_exception_propagates_unchanged(db, models):
    *_, job, rel, now = make_job(db, models)
    sentinel = RuntimeError("caller-secret-transcript")
    with pytest.raises(RuntimeError) as exc:
        with run_boundary(db, models, job, rel, CaptureTransport(), now):
            raise sentinel
    assert exc.value is sentinel


@pytest.mark.parametrize("payload", [
    {"text": "", "language_probability": 0},
    {"text": "hi", "language_code": "en", "language_probability": 1, "words": [{"text": "hi", "start": 0.1, "end": 0.2}]},
])
def test_valid_response_shapes(payload):
    from studio_api.elevenlabs_transcription import normalize_elevenlabs_transcript_response
    result = normalize_elevenlabs_transcript_response(payload)
    assert result.text == payload["text"]
    assert result.word_count == len(payload.get("words", []))


@pytest.mark.parametrize("payload", [[], {"text": 1}, {"text": "x", "language_probability": 2}, {"text": "x", "words": {}}, {"text": "x", "words": [1]}, {"text": "x", "words": [{"text": "w", "start": 2, "end": 1}]}, {"text": "x", "words": [{"text": "w", "start": -1}]}, {"text": "x", "words": [{"text": 3}] }])
def test_malformed_success_responses(payload):
    from studio_api.elevenlabs_transcription import ElevenLabsTranscriptionError, normalize_elevenlabs_transcript_response
    with pytest.raises(ElevenLabsTranscriptionError, match="malformed_provider_response"):
        normalize_elevenlabs_transcript_response(payload)


@pytest.mark.parametrize("status,reason", [(401, "provider_authentication_rejected"), (402, "provider_payment_required"), (403, "provider_scope_rejected"), (400, "provider_request_rejected"), (404, "provider_request_rejected"), (409, "provider_request_rejected"), (422, "provider_request_rejected"), (429, "provider_rate_limited"), (500, "provider_unavailable")])
def test_http_error_mapping_redacts_body(status, reason):
    from studio_api.elevenlabs_transcription import ElevenLabsTranscriptionError, ElevenLabsTranscriptionTransport
    def post(*a, **k):
        return httpx.Response(status, content=b"raw secret provider body")
    with pytest.raises(ElevenLabsTranscriptionError, match=reason) as exc:
        ElevenLabsTranscriptionTransport(post=post).transcribe(api_key="key", stream=BytesIO(b"a"), filename="secret.mp3", mime_type="audio/mpeg")
    assert "raw secret" not in str(exc.value) and "key" not in str(exc.value)


@pytest.mark.parametrize(
    "detail,expected",
    [
        ({"code": "insufficient_permissions", "message": "private detail"}, "insufficient_permissions"),
        ({"status": "invalid_api_key", "message": "private legacy detail"}, "invalid_api_key"),
        ({"code": "private_dynamic_value", "message": "private detail"}, None),
    ],
)
def test_http_error_exposes_only_allowlisted_provider_diagnostics(detail, expected):
    from studio_api.elevenlabs_transcription import ElevenLabsTranscriptionError, ElevenLabsTranscriptionTransport

    def post(*args, **kwargs):
        return httpx.Response(403, json={"detail": detail})

    with pytest.raises(ElevenLabsTranscriptionError) as exc:
        ElevenLabsTranscriptionTransport(post=post).transcribe(
            api_key="key",
            stream=BytesIO(b"a"),
            filename="secret.mp3",
            mime_type="audio/mpeg",
        )
    assert exc.value.reason.value == "provider_scope_rejected"
    assert exc.value.provider_error_code == expected
    assert exc.value.http_status == 403
    assert "private" not in str(exc.value)


@pytest.mark.parametrize("exc_obj,reason", [(httpx.TimeoutException("url secret"), "provider_timeout"), (httpx.ConnectError("network secret"), "provider_unavailable")])
def test_network_error_mapping_redacts(exc_obj, reason):
    from studio_api.elevenlabs_transcription import ElevenLabsTranscriptionError, ElevenLabsTranscriptionTransport
    def post(*a, **k):
        raise exc_obj
    with pytest.raises(ElevenLabsTranscriptionError, match=reason) as exc:
        ElevenLabsTranscriptionTransport(post=post).transcribe(api_key="key", stream=BytesIO(b"a"), filename="secret.mp3", mime_type="audio/mpeg")
    assert "secret" not in str(exc.value)


def test_malformed_json_mapping_redacts_body():
    from studio_api.elevenlabs_transcription import ElevenLabsTranscriptionError, ElevenLabsTranscriptionTransport
    def post(*a, **k):
        return httpx.Response(200, content=b"not json raw transcript")
    with pytest.raises(ElevenLabsTranscriptionError, match="malformed_provider_response") as exc:
        ElevenLabsTranscriptionTransport(post=post).transcribe(api_key="key", stream=BytesIO(b"a"), filename="secret.mp3", mime_type="audio/mpeg")
    assert "raw transcript" not in str(exc.value)
