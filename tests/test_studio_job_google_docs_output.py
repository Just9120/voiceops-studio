from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))

CANONICAL_DOCUMENT_TEXT = (
    "Title\n\nМетаданные транскрипта\n"
    "Provider: ElevenLabs\nModel: scribe_v2\nLanguage: ru\n"
    "Speakers: no\nCreated at: 2026-01-01T00:00:00Z\n\n"
    "Транскрипция\n\nBody"
)


@dataclass(frozen=True)
class Settings:
    source_max_upload_bytes: int = 1000
    source_s3_bucket: str = "bucket"


@pytest.fixture(autouse=True)
def isolated_studio_database_url(monkeypatch):
    monkeypatch.setenv("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")


@pytest.fixture()
def db():
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


def make_job(db, m, *, title="Job Title", language="en", options_json=None):
    now = datetime(2026, 1, 2, 3, 4, 5)
    user = m.User(email=f"{id(db)}@example.com", role=m.UserRole.user, status=m.UserStatus.active)
    db.add(user); db.flush()
    project = m.Project(owner_user_id=user.id, title="p", output_drive_folder_id="folder-private")
    db.add(project); db.flush()
    src = m.Source(project_id=project.id, source_type=m.SourceType.local_upload, original_filename="тайна meeting.mp3", mime_type="audio/mpeg", size_bytes=5, s3_bucket="bucket", s3_object_key="private/object", upload_status=m.SourceUploadStatus.uploaded, uploaded_at=now, source_created_at=datetime(2025, 12, 31, 22, 33, 44), source_created_at_provenance="embedded_media_metadata", expires_at=now + timedelta(hours=1))
    db.add(src); db.flush()
    job = m.TranscriptionJob(project_id=project.id, owner_user_id=user.id, status=m.JobStatus.processing, provider="elevenlabs", title=title, language=language, options_json=options_json, output_drive_folder_id="folder-private", output_drive_folder_url="https://drive.google.com/drive/folders/folder-private", output_drive_folder_name="Private", lease_owner_id="worker", lease_generation=7, claimed_at=now, lease_expires_at=now + timedelta(minutes=5), started_at=now)
    db.add(job); db.flush()
    rel = m.TranscriptionJobSource(job_id=job.id, source_id=src.id, position=0)
    db.add(rel); db.commit()
    return user, project, src, job, rel, now


class Transcript:
    text_length = 12
    detected_language_code = "ru"
    def __init__(self, text="Привет\nмир", words=()):
        self._text = text; self.words = tuple(words); self.closed = False
    @property
    def text(self):
        if self.closed:
            from studio_api.elevenlabs_transcription import ElevenLabsTranscriptionError, ElevenLabsTranscriptionReason
            raise ElevenLabsTranscriptionError(ElevenLabsTranscriptionReason.context_closed)
        return self._text


class FakeTransport:
    def __init__(self, mutate=None):
        self.calls = []; self.delete_calls = 0; self.mutate = mutate
    def create_transcript_document(self, **kwargs):
        self.calls.append(kwargs)
        if self.mutate:
            self.mutate()
        from studio_api.google_docs_output import normalize_google_docs_create_response
        return normalize_google_docs_create_response({"id":"doc-private","name":kwargs["title"],"mimeType":"application/vnd.google-apps.document","webViewLink":"https://docs.example/private","parents":[kwargs["folder_id"]]}, expected_folder_id=kwargs["folder_id"])


def good_meta(token, folder):
    from studio_api.google_drive import GOOGLE_FOLDER_MIME_TYPE
    from studio_api.job_output_destination import DriveFolderAuthorizationMetadata
    return DriveFolderAuthorizationMetadata(folder, GOOGLE_FOLDER_MIME_TYPE, False, True)


@pytest.mark.parametrize("provider,model,label", [("yandex", "general", "Yandex SpeechKit"), ("yandex", "deferred-general", "Yandex SpeechKit"), ("elevenlabs", "reviewed-new-model", "ElevenLabs")])
def test_selected_model_and_unknown_recording_date(db, models, provider, model, label):
    from studio_api.job_google_docs_output import create_processing_job_google_doc_from_transcript
    _, _, source, job, relation, now = make_job(db, models)
    job.provider = provider
    job.options_json = '{"_stt_model":"' + model + '"}'
    job.media_clip_start_seconds = 10
    job.media_clip_end_seconds = 20
    source.source_created_at = source.source_created_at_provenance = None
    db.commit()
    transport = FakeTransport()
    with create_processing_job_google_doc_from_transcript(db, job_id=job.id, job_source_id=relation.id,
            lease_owner_id="worker", lease_generation=7, transcript=Transcript(), settings=Settings(),
            clock=lambda: now, token_resolver=lambda *a, **k: "token", metadata_fetcher=good_meta,
            google_docs_transport=transport):
        pass
    body = transport.calls[0]["document_text"]
    assert f"Provider: {label}" in body and f"Model: {model}" in body
    assert "Created at:" not in body
    assert "Source:" not in body and "Clip: 10-20 seconds; source timeline" in body


def test_metadata_change_before_creation_blocks_side_effect(db, models):
    from studio_api.job_google_docs_output import create_processing_job_google_doc_from_transcript, JobGoogleDocsOutputError
    _, _, _, job, relation, now = make_job(db, models)
    def mutate(token, folder):
        job.media_clip_start_seconds = 10
        job.media_clip_end_seconds = 20
        db.commit()
        return good_meta(token, folder)
    transport = FakeTransport()
    with pytest.raises(JobGoogleDocsOutputError, match="lifecycle_changed_before"):
        with create_processing_job_google_doc_from_transcript(db, job_id=job.id, job_source_id=relation.id,
                lease_owner_id="worker", lease_generation=7, transcript=Transcript(), settings=Settings(),
                clock=lambda: now, token_resolver=lambda *a, **k: "token", metadata_fetcher=mutate,
                google_docs_transport=transport): pass
    assert transport.calls == []


@pytest.mark.parametrize("case", ["unknown_date", "known_original_date", "foreign_source", "recipe_changed_after_creation"])
def test_prepared_document_retains_inputs_recipe_not_export_date(db, models, case):
    from studio_api.job_google_docs_output import create_processing_job_google_doc_from_transcript, JobGoogleDocsOutputError
    user, project, source, job, relation, now = make_job(db, models)
    original = models.Source(project_id=project.id, source_type=models.SourceType.local_upload,
        original_filename="original.wav", mime_type="audio/wav", size_bytes=5,
        upload_status=models.SourceUploadStatus.uploaded)
    if case == "known_original_date":
        original.source_created_at = datetime(2024, 1, 1)
        original.source_created_at_provenance = "embedded_media_metadata"
    elif case == "foreign_source":
        other = models.User(email="foreign-metadata@example.test", role=models.UserRole.user, status=models.UserStatus.active)
        db.add(other); db.flush()
        foreign = models.Project(owner_user_id=other.id, title="foreign")
        db.add(foreign); db.flush()
        original.project_id = foreign.id
    db.add(original); db.flush()
    preparation = models.AudioPreparationJob(owner_user_id=user.id, project_id=project.id,
        title="Prepared", options_json='{"silence_enabled":true,"output_format":"flac"}',
        output_destination="download", status=models.AudioPreparationStatus.completed,
        output_source_id=source.id)
    db.add(preparation); db.flush()
    db.add(models.AudioPreparationJobInput(job_id=preparation.id, source_id=original.id, position=0))
    db.commit()
    def mutate_recipe():
        preparation.options_json = '{"output_format":"wav"}'
        db.commit()
    transport = FakeTransport(mutate_recipe if case == "recipe_changed_after_creation" else None)
    context = create_processing_job_google_doc_from_transcript(db, job_id=job.id, job_source_id=relation.id,
            lease_owner_id="worker", lease_generation=7, transcript=Transcript(), settings=Settings(),
            clock=lambda: now, token_resolver=lambda *a, **k: "token", metadata_fetcher=good_meta,
            google_docs_transport=transport)
    if case in {"foreign_source", "recipe_changed_after_creation"}:
        with pytest.raises(JobGoogleDocsOutputError, match="selected_source_changed" if case == "foreign_source" else "lifecycle_changed_after"):
            with context: pass
        assert len(transport.calls) == (0 if case == "foreign_source" else 1)
        return
    with context: pass
    body = transport.calls[0]["document_text"]
    if case == "known_original_date":
        assert "Created at: 2024-01-01T00:00:00Z" in body
    else:
        assert "Created at:" not in body
    assert "Preparation:" not in body and preparation.id not in body
    assert 'Original source: original.wav' in body and original.id not in body
    assert 'длинные паузы сокращены' in body and "Timeline: prepared audio" in body
    assert "Transformations:" not in body and '"silence_enabled"' not in body
    from studio_api.transcript_catalog_scan import classify_transcript_document_standard
    from studio_api.transcript_catalog_standardize import build_standardized_transcript_document_text
    assert classify_transcript_document_standard(body).value == "current"
    rewritten = build_standardized_transcript_document_text(document_name="Reviewed", existing_document_text=body, created_time=None)
    for prefix in ("Timeline:", "Audio processing:", "Original source:"):
        assert next(line for line in body.splitlines() if line.startswith(prefix)) in rewritten


@pytest.mark.parametrize("proof", ["none", "verified", "different_content", "changed_during_write"])
def test_drive_preparation_provenance_requires_the_exact_verified_content(db, models, proof):
    from studio_api.audio_export_receipt import AudioExportReceipt
    from studio_api.media_context import prepared_audio_source_context
    from studio_api.job_google_docs_output import create_processing_job_google_doc_from_transcript, JobGoogleDocsOutputError
    user, project, source, job, relation, now = make_job(db, models)
    source.source_type = models.SourceType.google_drive
    source.drive_file_id = "prepared-drive-file"
    source.source_created_at_provenance = "google_drive_created_time"
    original = models.Source(project_id=project.id, source_type=models.SourceType.local_upload,
        original_filename="actual-recording.wav", mime_type="audio/wav", size_bytes=5,
        source_created_at=datetime(2024, 1, 1), source_created_at_provenance="embedded_media_metadata",
        upload_status=models.SourceUploadStatus.uploaded)
    db.add(original); db.flush()
    receipt = AudioExportReceipt(source.drive_file_id, 5, "a" * 64, None)
    preparation = models.AudioPreparationJob(owner_user_id=user.id, project_id=project.id,
        title="Prepared", options_json='{"silence_enabled":true,"output_format":"flac"}',
        status=models.AudioPreparationStatus.completed, output_drive_file_id=source.drive_file_id,
        output_drive_web_view_url="https://drive.google.com/file/d/prepared-drive-file/view",
        output_drive_receipt_json=receipt.serialize(), total_input_duration_ms=2000, output_duration_ms=1000)
    db.add(preparation); db.flush()
    db.add(models.AudioPreparationJobInput(job_id=preparation.id, source_id=original.id, position=0))
    if proof != "none":
        source.prepared_audio_context_json = prepared_audio_source_context(preparation, receipt)
    if proof == "different_content":
        preparation.output_drive_receipt_json = AudioExportReceipt(source.drive_file_id, 5, "b" * 64, None).serialize()
    db.commit()
    def mutate():
        source.prepared_audio_context_json = None
        db.commit()
    transport = FakeTransport(mutate if proof == "changed_during_write" else None)
    context = create_processing_job_google_doc_from_transcript(db, job_id=job.id, job_source_id=relation.id,
        lease_owner_id="worker", lease_generation=7, transcript=Transcript(), settings=Settings(),
        clock=lambda: now, token_resolver=lambda *a, **k: "synthetic", metadata_fetcher=good_meta,
        google_docs_transport=transport)
    if proof in {"different_content", "changed_during_write"}:
        expected = "selected_source_changed" if proof == "different_content" else "lifecycle_changed_after"
        with pytest.raises(JobGoogleDocsOutputError, match=expected):
            with context: pytest.fail("a changed body/context must not acquire old recording provenance")
        assert len(transport.calls) == (0 if proof == "different_content" else 1)
    else:
        with context: pass
        body = transport.calls[0]["document_text"]
        assert ("Original source: actual-recording.wav" in body) == (proof == "verified")
        assert ("Created at: 2024-01-01" in body) == (proof == "verified")
        assert "Created at: 2025-12-31" not in body


@pytest.mark.parametrize("diarize", [False, True])
@pytest.mark.parametrize("mutate_clock", [False, True])
def test_new_documents_show_original_clock_anchors_and_fence_the_map_during_creation(db, models, diarize, mutate_clock):
    from studio_api.audio_timeline import AudioTimeline
    from studio_api.elevenlabs_transcription import normalize_elevenlabs_transcript_response
    from studio_api.job_google_docs_output import create_processing_job_google_doc_from_transcript, JobGoogleDocsOutputError
    _, _, _, job, relation, now = make_job(db, models, options_json='{"diarize":' + str(diarize).lower() + '}')
    job.media_timeline_version = 2
    job.media_clip_start_seconds, job.media_clip_end_seconds = 4, 12
    relation.transcript_timeline_json = AudioTimeline.from_seconds(20, [(4, 5), (10, 12)]).serialize()
    db.commit()
    transcript = normalize_elevenlabs_transcript_response({"text":"Первый второй", "words":[
        {"text":"Первый", "start":4, "end":5, "speaker_id":"speaker_0"},
        {"text":"второй", "start":10, "end":11, "speaker_id":"speaker_1"}]})
    def mutate():
        relation.transcript_timeline_json = AudioTimeline.identity(20).serialize()
        db.commit()
    transport = FakeTransport(mutate if mutate_clock else None)
    context = create_processing_job_google_doc_from_transcript(db, job_id=job.id, job_source_id=relation.id,
        lease_owner_id="worker", lease_generation=7, transcript=transcript, settings=Settings(), clock=lambda: now,
        token_resolver=lambda *a, **kw: "synthetic", metadata_fetcher=good_meta, google_docs_transport=transport)
    if mutate_clock:
        with pytest.raises(JobGoogleDocsOutputError, match="lifecycle_changed_after"):
            with context: pytest.fail("a different map must not be accepted after the external write")
    else:
        with context: pass
    body = transport.calls[0]["document_text"]
    assert "[00:00:04] Первый" in body and "[00:00:10] второй" in body
    assert ("Спикер 1:" in body and "Спикер 2:" in body) == diarize
    assert "Timeline: original recording" in body
    assert "Source clock receipt:" not in body and "original_duration_us" not in body
    transcript.revoke()


def test_timed_formatter_keeps_full_text_when_word_alignment_is_incomplete():
    from types import SimpleNamespace
    from studio_api.job_google_docs_output import build_timed_transcript
    word = SimpleNamespace(text="retained", start=0, end=1, speaker_id="speaker_0")
    for diarize in (False, True):
        assert build_timed_transcript([word], fallback_text="retained and otherwise omitted", diarize=diarize) == "retained and otherwise omitted"


def test_transport_multipart_and_redaction():
    from studio_api.google_docs_output import GoogleDocsTranscriptTransport
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        payload = (
            {"documentId": "doc-private"}
            if url.endswith("/doc-private:batchUpdate")
            else {"id":"doc-private","name":"Secret Title","mimeType":"application/vnd.google-apps.document","webViewLink":"https://docs.example/private","parents":["folder-private"]}
        )
        return httpx.Response(200, json=payload)
    result = GoogleDocsTranscriptTransport(post=post).create_transcript_document(access_token="token-secret", folder_id="folder-private", title="Secret Title", document_text=CANONICAL_DOCUMENT_TEXT)
    url, kwargs = calls[0]
    parsed = urlparse(url)
    assert parsed.scheme == "https" and parsed.netloc == "www.googleapis.com" and parsed.path == "/upload/drive/v3/files"
    assert parse_qs(parsed.query) == {"uploadType":["multipart"], "supportsAllDrives":["true"], "fields":["id,name,mimeType,webViewLink,parents"]}
    assert kwargs["headers"]["Authorization"] == "Bearer token-secret"
    assert kwargs["timeout"] == 120.0
    assert "multipart/related" in kwargs["headers"]["Content-Type"]
    body = kwargs["content"]
    assert body.index(b"application/json") < body.index(b"text/plain; charset=UTF-8")
    assert b'"name":"Secret Title"' in body and b'"mimeType":"application/vnd.google-apps.document"' in body and b'"parents":["folder-private"]' in body
    assert CANONICAL_DOCUMENT_TEXT.encode() in body
    assert len(calls) == 2
    docs_url, docs_kwargs = calls[1]
    assert docs_url == "https://docs.googleapis.com/v1/documents/doc-private:batchUpdate"
    assert docs_kwargs["headers"]["Authorization"] == "Bearer token-secret"
    requests = docs_kwargs["json"]["requests"]
    assert requests[0]["updateParagraphStyle"]["paragraphStyle"] == {
        "namedStyleType": "HEADING_2"
    }
    assert requests[1]["updateTextStyle"]["textStyle"]["fontSize"] == {
        "magnitude": 11,
        "unit": "PT",
    }
    assert result.document_id == "doc-private" and result.web_view_link == "https://docs.example/private"
    assert all(secret not in repr(result) for secret in ["doc-private", "Secret Title", "folder-private", "https://docs.example/private"])


@pytest.mark.parametrize("status,reason", [(401,"authentication_rejected"),(403,"authentication_rejected"),(400,"request_rejected"),(404,"request_rejected"),(409,"request_rejected"),(422,"request_rejected"),(429,"rate_limited"),(500,"unavailable")])
def test_transport_error_mapping_redacts(status, reason):
    from studio_api.google_docs_output import GoogleDocsOutputError, GoogleDocsTranscriptTransport
    def post(*a, **k): return httpx.Response(status, content=b"raw secret response doc-private folder-private Secret Title body")
    with pytest.raises(GoogleDocsOutputError) as exc:
        GoogleDocsTranscriptTransport(post=post).create_transcript_document(access_token="token-secret", folder_id="folder-private", title="Secret Title", document_text=CANONICAL_DOCUMENT_TEXT)
    assert str(exc.value) == reason
    assert all(s not in str(exc.value) and s not in repr(exc.value) for s in ["token-secret","folder-private","doc-private","Secret Title","body","raw secret"])


@pytest.mark.parametrize("exc_obj,reason", [(httpx.TimeoutException("token-secret"),"timeout"),(httpx.ConnectError("folder-private"),"unavailable")])
def test_transport_network_mapping_redacts(exc_obj, reason):
    from studio_api.google_docs_output import GoogleDocsOutputError, GoogleDocsTranscriptTransport
    def post(*a, **k): raise exc_obj
    with pytest.raises(GoogleDocsOutputError, match=reason):
        GoogleDocsTranscriptTransport(post=post).create_transcript_document(access_token="token-secret", folder_id="folder-private", title="Secret Title", document_text=CANONICAL_DOCUMENT_TEXT)


def test_transport_malformed_response_rejected():
    from studio_api.google_docs_output import GoogleDocsOutputError, GoogleDocsTranscriptTransport
    def post(*a, **k): return httpx.Response(200, json={"id":"", "mimeType":"text/plain", "parents":[]})
    with pytest.raises(GoogleDocsOutputError, match="malformed_response"):
        GoogleDocsTranscriptTransport(post=post).create_transcript_document(access_token="token", folder_id="folder", title="title", document_text=CANONICAL_DOCUMENT_TEXT)


def test_transport_fails_closed_when_rich_text_formatting_is_rejected():
    from studio_api.google_docs_output import (
        GoogleDocsOutputError,
        GoogleDocsTranscriptTransport,
    )

    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/doc-private:batchUpdate"):
            return httpx.Response(
                400,
                content=b"private formatting rejection",
            )
        return httpx.Response(
            200,
            json={
                "id": "doc-private",
                "name": "Title",
                "mimeType": "application/vnd.google-apps.document",
                "webViewLink": "https://docs.example/private",
                "parents": ["folder-private"],
            },
        )

    with pytest.raises(GoogleDocsOutputError, match="request_rejected"):
        GoogleDocsTranscriptTransport(post=post).create_transcript_document(
            access_token="private-access",
            folder_id="folder-private",
            title="Title",
            document_text=CANONICAL_DOCUMENT_TEXT,
            reconciliation_token="or_private_marker",
        )

    assert len(calls) == 2
    assert b"or_private_marker" in calls[0][1]["content"]


def test_formatting_contract_title_language_unicode_empty_body():
    from studio_api.job_google_docs_output import build_speaker_labeled_transcript, choose_transcript_document_title, format_transcript_doc
    created = datetime(2026,1,2,3,4,5)
    doc = format_transcript_doc(title=" My Job ", transcript_text="Привет\nмир", job_language=" ", detected_language_code="ru", created_at=created)
    assert doc.body == "My Job\n\nМетаданные транскрипта\nProvider: ElevenLabs\nModel: scribe_v2\nLanguage: ru\nCreated at: 2026-01-02T03:04:05Z\n\nТранскрипция\n\nПривет\nмир"
    assert "Source file:" not in doc.body and "Source mode:" not in doc.body
    detected = format_transcript_doc(title="Auto", transcript_text="Text", job_language="detect", detected_language_code="en", created_at=created)
    assert detected.language == "en" and "Language: en" in detected.body
    words = (
        type("Word", (), {"text": "Привет", "speaker_id": "speaker_b"})(),
        type("Word", (), {"text": ",", "speaker_id": "speaker_b"})(),
        type("Word", (), {"text": "мир", "speaker_id": "speaker_a"})(),
        type("Word", (), {"text": " снова", "speaker_id": "speaker_b"})(),
    )
    labeled = build_speaker_labeled_transcript(words, fallback_text="fallback")
    assert labeled == "Спикер 1:\nПривет,\n\nСпикер 2:\nмир\n\nСпикер 1:\nснова"
    diarized = format_transcript_doc(title="Call", transcript_text=labeled, job_language="ru", detected_language_code="ru", created_at=created, diarization_enabled=True)
    assert "Speakers:" not in diarized.body and diarized.body.endswith(labeled)
    assert choose_transcript_document_title(job_title=" ", original_filename="folder/audio.name.mp3") == "audio.name"
    empty = format_transcript_doc(title="\x00", transcript_text="", job_language=None, detected_language_code=None, created_at=created)
    assert empty.title == "Transcript" and empty.body.endswith("Транскрипция\n\n") and "Language: unknown" in empty.body
    unknown = format_transcript_doc(title="Unknown", transcript_text="Text", job_language="en", detected_language_code=None, created_at=None)
    assert "Created at:" not in unknown.body


def test_success_job_boundary_one_token_one_create_lifetime_and_no_mutation(db, models):
    from studio_api.job_google_docs_output import create_processing_job_google_doc_from_transcript
    user, project, src, job, rel, now = make_job(db, models)
    tokens = []; metadata_calls = []; transport = FakeTransport()
    before = (job.status, job.finished_at, job.error_code, job.error_message, rel.status, src.deleted_at, project.output_drive_folder_id)
    with create_processing_job_google_doc_from_transcript(db, job_id=job.id, job_source_id=rel.id, lease_owner_id="worker", lease_generation=7, transcript=Transcript(), settings=Settings(), now=now, clock=lambda: now, token_resolver=lambda *a, **k: tokens.append(1) or "token-secret", metadata_fetcher=lambda token, folder: metadata_calls.append((token, folder)) or good_meta(token, folder), google_docs_transport=transport) as artifact:
        retained = artifact
        assert artifact.document_id == "doc-private" and artifact.web_view_link == "https://docs.example/private"
        assert "doc-private" not in repr(artifact) and "https://docs.example/private" not in repr(artifact) and "Job Title" not in repr(artifact)
    assert tokens == [1] and len(metadata_calls) == 1 and len(transport.calls) == 1
    assert metadata_calls[0][0] == transport.calls[0]["access_token"] == "token-secret"
    assert "Created at: 2025-12-31T22:33:44Z" in transport.calls[0]["document_text"]
    assert (job.status, job.finished_at, job.error_code, job.error_message, rel.status, src.deleted_at, project.output_drive_folder_id) == before
    from studio_api.google_docs_output import GoogleDocsOutputError
    with pytest.raises(GoogleDocsOutputError, match="context_closed"):
        retained.document_id


def test_diarized_job_creates_deterministic_speaker_document(db, models):
    from studio_api.job_google_docs_output import create_processing_job_google_doc_from_transcript
    user, project, src, job, rel, now = make_job(
        db,
        models,
        options_json='{"diarize":true}',
    )
    words = (
        type("Word", (), {"text": "Добрый", "speaker_id": "speaker_7"})(),
        type("Word", (), {"text": " день", "speaker_id": "speaker_7"})(),
        type("Word", (), {"text": "Здравствуйте", "speaker_id": "speaker_2"})(),
    )
    transcript = Transcript("Добрый день Здравствуйте", words)
    transport = FakeTransport()

    with create_processing_job_google_doc_from_transcript(
        db,
        job_id=job.id,
        job_source_id=rel.id,
        lease_owner_id="worker",
        lease_generation=7,
        transcript=transcript,
        settings=Settings(),
        now=now,
        clock=lambda: now,
        token_resolver=lambda *a, **k: "token-secret",
        metadata_fetcher=lambda token, folder: good_meta(token, folder),
        google_docs_transport=transport,
    ):
        pass

    document_text = transport.calls[0]["document_text"]
    assert "Speakers:" not in document_text
    assert document_text.endswith("Спикер 1:\nДобрый день\n\nСпикер 2:\nЗдравствуйте")


@pytest.mark.parametrize("mutate,reason", [
    (lambda m,p,s,j,r,n: setattr(j,"status",m.JobStatus.failed), "job_not_processing"),
    (lambda m,p,s,j,r,n: setattr(j,"lease_owner_id","other"), "lease_not_owned"),
    (lambda m,p,s,j,r,n: setattr(j,"lease_generation",8), "lease_not_owned"),
    (lambda m,p,s,j,r,n: setattr(j,"lease_expires_at",n-timedelta(seconds=1)), "lease_not_active"),
    (lambda m,p,s,j,r,n: setattr(j,"cancel_requested_at",n), "cancellation_requested"),
    (lambda m,p,s,j,r,n: setattr(p,"archived_at",n), "project_unavailable"),
    (lambda m,p,s,j,r,n: setattr(p,"owner_user_id","other"), "project_unavailable"),
    (lambda m,p,s,j,r,n: setattr(j,"output_drive_folder_id","changed"), "output_identity_changed_before_output_creation"),
    (lambda m,p,s,j,r,n: setattr(r,"status",m.JobSourceStatus.skipped), "job_source_not_processable"),
    (lambda m,p,s,j,r,n: setattr(s,"project_id","other"), "job_source_not_processable"),
    (lambda m,p,s,j,r,n: setattr(s,"upload_status",m.SourceUploadStatus.pending), "job_source_not_processable"),
    (lambda m,p,s,j,r,n: setattr(s,"deleted_at",n), "job_source_not_processable"),
    (lambda m,p,s,j,r,n: setattr(s,"expires_at",n-timedelta(seconds=1)), "job_source_not_processable"),
])
def test_fail_closed_mutations_before_create(db, models, mutate, reason):
    from studio_api.job_google_docs_output import JobGoogleDocsOutputError, create_processing_job_google_doc_from_transcript
    user, project, src, job, rel, now = make_job(db, models)
    transport = FakeTransport()
    def metadata(token, folder):
        mutate(models, project, src, job, rel, now); db.flush(); return good_meta(token, folder)
    with pytest.raises(JobGoogleDocsOutputError, match=reason):
        with create_processing_job_google_doc_from_transcript(db, job_id=job.id, job_source_id=rel.id, lease_owner_id="worker", lease_generation=7, transcript=Transcript(), settings=Settings(), now=now, clock=lambda: now, token_resolver=lambda *a, **k: "token-secret", metadata_fetcher=metadata, google_docs_transport=transport): pass
    assert transport.calls == []


def test_transcript_closed_folder_failure_and_token_unavailable_block_create(db, models):
    from studio_api.google_connection_access import GoogleConnectionAccessError, GoogleConnectionAccessReason
    from studio_api.job_google_docs_output import JobGoogleDocsOutputError, create_processing_job_google_doc_from_transcript
    user, project, src, job, rel, now = make_job(db, models)
    t = Transcript(); t.closed = True
    transport = FakeTransport()
    with pytest.raises(JobGoogleDocsOutputError, match="transcript_context_closed"):
        with create_processing_job_google_doc_from_transcript(db, job_id=job.id, job_source_id=rel.id, lease_owner_id="worker", lease_generation=7, transcript=t, settings=Settings(), now=now, clock=lambda: now, token_resolver=lambda *a, **k: "token", metadata_fetcher=good_meta, google_docs_transport=transport): pass
    with pytest.raises(JobGoogleDocsOutputError, match="google_connection_unavailable"):
        with create_processing_job_google_doc_from_transcript(db, job_id=job.id, job_source_id=rel.id, lease_owner_id="worker", lease_generation=7, transcript=Transcript(), settings=Settings(), now=now, clock=lambda: now, token_resolver=lambda *a, **k: (_ for _ in ()).throw(GoogleConnectionAccessError(GoogleConnectionAccessReason.missing)), metadata_fetcher=good_meta, google_docs_transport=transport): pass
    assert transport.calls == []


def test_post_create_mutation_safe_no_retry_no_success(db, models):
    from studio_api.job_google_docs_output import JobGoogleDocsOutputError, create_processing_job_google_doc_from_transcript
    user, project, src, job, rel, now = make_job(db, models)
    transport = FakeTransport(mutate=lambda: (setattr(job, "output_drive_folder_id", "changed"), db.flush()))
    with pytest.raises(JobGoogleDocsOutputError) as exc:
        with create_processing_job_google_doc_from_transcript(db, job_id=job.id, job_source_id=rel.id, lease_owner_id="worker", lease_generation=7, transcript=Transcript(), settings=Settings(), now=now, clock=lambda: now, token_resolver=lambda *a, **k: "token-secret", metadata_fetcher=good_meta, google_docs_transport=transport): pass
    assert str(exc.value) == "lifecycle_changed_after_output_creation"
    assert len(transport.calls) == 1 and transport.delete_calls == 0
    assert all(s not in str(exc.value) and s not in repr(exc.value) for s in ["doc-private","https://docs.example/private","Job Title","folder-private","token-secret","Привет"])


def test_caller_exception_propagates_and_artifact_revoked(db, models):
    from studio_api.job_google_docs_output import create_processing_job_google_doc_from_transcript
    user, project, src, job, rel, now = make_job(db, models)
    sentinel = RuntimeError("caller")
    retained = None
    with pytest.raises(RuntimeError) as exc:
        with create_processing_job_google_doc_from_transcript(db, job_id=job.id, job_source_id=rel.id, lease_owner_id="worker", lease_generation=7, transcript=Transcript(), settings=Settings(), now=now, clock=lambda: now, token_resolver=lambda *a, **k: "token", metadata_fetcher=good_meta, google_docs_transport=FakeTransport()) as artifact:
            retained = artifact; raise sentinel
    assert exc.value is sentinel
    from studio_api.google_docs_output import GoogleDocsOutputError
    with pytest.raises(GoogleDocsOutputError, match="context_closed"):
        retained.web_view_link


def test_artifact_folder_id_lifetime_redacted():
    from studio_api.google_docs_output import GoogleDocsCreateResult, GoogleDocsOutputError, new_google_docs_transcript_artifact
    artifact = new_google_docs_transcript_artifact(result=GoogleDocsCreateResult("doc-private", "Secret", "application/vnd.google-apps.document", "https://docs.example/private", ("folder-private",)), created_at=datetime(2026,1,2), character_count=1)
    assert artifact.document_id == "doc-private" and artifact.web_view_link == "https://docs.example/private" and artifact.output_folder_id == "folder-private"
    assert all(s not in repr(artifact) for s in ["doc-private", "https://docs.example/private", "folder-private", "Secret"])
    artifact.revoke()
    for attr in ["document_id", "web_view_link", "output_folder_id"]:
        with pytest.raises(GoogleDocsOutputError, match="context_closed"):
            getattr(artifact, attr)


def test_existing_persisted_output_blocks_token_and_create(db, models):
    from studio_api.job_google_docs_output import JobGoogleDocsOutputError, create_processing_job_google_doc_from_transcript
    user, project, src, job, rel, now = make_job(db, models)
    db.add(models.TranscriptionJobOutput(job_id=job.id, job_source_id=rel.id, document_id="doc-private", web_view_url="https://docs.example/private", output_drive_folder_id="folder-private", output_kind="google_docs_transcript", transcript_standard="transcript_doc_v1.2", document_character_count=1, document_created_at=now, persisted_at=now, lease_generation=7)); db.commit()
    transport = FakeTransport(); token_calls=[]
    with pytest.raises(JobGoogleDocsOutputError, match="output_already_persisted"):
        with create_processing_job_google_doc_from_transcript(db, job_id=job.id, job_source_id=rel.id, lease_owner_id="worker", lease_generation=7, transcript=Transcript(), settings=Settings(), now=now, clock=lambda: now, token_resolver=lambda *a, **k: token_calls.append(1) or "token", metadata_fetcher=good_meta, google_docs_transport=transport): pass
    assert token_calls == [] and transport.calls == []


def test_output_inserted_before_final_check_blocks_google_create(db, models):
    from studio_api.job_google_docs_output import JobGoogleDocsOutputError, create_processing_job_google_doc_from_transcript
    user, project, src, job, rel, now = make_job(db, models)
    transport = FakeTransport(); inserted = {"done": False}
    def closed_transcript_text_once():
        if not inserted["done"]:
            db.add(models.TranscriptionJobOutput(job_id=job.id, job_source_id=rel.id, document_id="doc-private", web_view_url="https://docs.example/private", output_drive_folder_id="folder-private", output_kind="google_docs_transcript", transcript_standard="transcript_doc_v1.2", document_character_count=1, document_created_at=now, persisted_at=now, lease_generation=7)); db.flush(); inserted["done"] = True
        return "text"
    class T(Transcript):
        @property
        def text(self): return closed_transcript_text_once()
    with pytest.raises(JobGoogleDocsOutputError, match="output_already_persisted"):
        with create_processing_job_google_doc_from_transcript(db, job_id=job.id, job_source_id=rel.id, lease_owner_id="worker", lease_generation=7, transcript=T(), settings=Settings(), now=now, clock=lambda: now, token_resolver=lambda *a, **k: "token", metadata_fetcher=good_meta, google_docs_transport=transport): pass
    assert transport.calls == []

def test_transport_adds_reconciliation_app_property_without_visible_token():
    from studio_api.google_docs_output import GoogleDocsTranscriptTransport, OUTPUT_RECONCILIATION_APP_PROPERTY
    calls=[]
    def post(url, **kwargs):
        calls.append(kwargs)
        payload = {"documentId": "doc-private"} if url.endswith("/doc-private:batchUpdate") else {"id":"doc-private","name":"Title","mimeType":"application/vnd.google-apps.document","webViewLink":"https://docs.example/private","parents":["folder-private"]}
        return httpx.Response(200, json=payload)
    token="or_opaqueRandomOnly"
    GoogleDocsTranscriptTransport(post=post).create_transcript_document(access_token="access", folder_id="folder-private", title="Title", document_text=CANONICAL_DOCUMENT_TEXT, reconciliation_token=token)
    body=calls[0]["content"]
    assert f'"appProperties":{{"{OUTPUT_RECONCILIATION_APP_PROPERTY}":"{token}"}}'.encode() in body
    assert body.count(token.encode()) == 1
    text_part = body.split(b"text/plain; charset=UTF-8", 1)[1]
    assert token.encode() not in text_part


@pytest.mark.parametrize("status,expected_reason", [
    ("prepared", "existing_reconciliation_case"),
    ("creation_returned", "existing_reconciliation_case"),
    ("reconciliation_required", "existing_reconciliation_case"),
    ("conflict", "output_reconciliation_conflict"),
])
def test_existing_reconciliation_case_blocks_second_google_create(db, models, status, expected_reason):
    from studio_api.job_google_docs_output import JobGoogleDocsOutputError, create_processing_job_google_doc_from_transcript
    user, project, src, job, rel, now = make_job(db, models)
    case = models.TranscriptionOutputReconciliation(
        owner_user_id=user.id,
        project_id=project.id,
        job_id=job.id,
        job_source_id=rel.id,
        reconciliation_token=f"or_existing_{status}",
        lease_generation=7,
        attempt_number=1,
        status=models.OutputReconciliationStatus(status),
        uncertainty_reason=None,
        expected_output_drive_folder_id="folder-private",
        expected_document_title="Job Title",
        expected_document_title_hash="h",
        expected_document_character_count=10,
        prepared_at=now,
        creation_started_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(case); db.commit()
    transport = FakeTransport()
    with pytest.raises(JobGoogleDocsOutputError, match=expected_reason):
        with create_processing_job_google_doc_from_transcript(db, job_id=job.id, job_source_id=rel.id, lease_owner_id="worker", lease_generation=7, transcript=Transcript(), settings=Settings(), now=now, clock=lambda: now, token_resolver=lambda *a, **k: "token", metadata_fetcher=good_meta, google_docs_transport=transport): pass
    db.refresh(case)
    if status == "prepared":
        assert case.status == models.OutputReconciliationStatus.reconciliation_required
        assert case.uncertainty_reason == "existing_reconciliation_case"
    assert transport.calls == []


def test_reconciliation_case_commit_failure_is_not_output_race(db, models, monkeypatch):
    from studio_api.job_google_docs_output import JobGoogleDocsOutputError, create_processing_job_google_doc_from_transcript
    user, project, src, job, rel, now = make_job(db, models)
    original_commit = db.commit
    fail = {"enabled": True}
    def commit():
        if fail["enabled"]:
            raise RuntimeError("SECRET database failure")
        return original_commit()
    monkeypatch.setattr(db, "commit", commit)
    transport = FakeTransport()
    with pytest.raises(JobGoogleDocsOutputError) as excinfo:
        with create_processing_job_google_doc_from_transcript(db, job_id=job.id, job_source_id=rel.id, lease_owner_id="worker", lease_generation=7, transcript=Transcript(), settings=Settings(), now=now, clock=lambda: now, token_resolver=lambda *a, **k: "token", metadata_fetcher=good_meta, google_docs_transport=transport): pass
    assert excinfo.value.reason.value == "reconciliation_case_persistence_failed"
    assert excinfo.value.reason.value != "output_already_persisted"
    assert transport.calls == []


def test_heartbeat_only_lease_expiry_change_before_create_does_not_trip_lifecycle(db, models):
    from studio_api.job_google_docs_output import create_processing_job_google_doc_from_transcript
    user, project, src, job, rel, now = make_job(db, models)
    transport = FakeTransport()
    def metadata(token, folder):
        job.lease_expires_at = now + timedelta(minutes=10)
        db.flush()
        return good_meta(token, folder)
    with create_processing_job_google_doc_from_transcript(db, job_id=job.id, job_source_id=rel.id, lease_owner_id="worker", lease_generation=7, transcript=Transcript(), settings=Settings(), now=now, clock=lambda: now, token_resolver=lambda *a, **k: "token-secret", metadata_fetcher=metadata, google_docs_transport=transport) as artifact:
        assert artifact.character_count > 0
    assert len(transport.calls) == 1


def test_heartbeat_only_lease_expiry_change_after_create_does_not_require_reconciliation(db, models):
    from studio_api.job_google_docs_output import create_processing_job_google_doc_from_transcript
    user, project, src, job, rel, now = make_job(db, models)
    def mutate_expiry():
        job.lease_expires_at = now + timedelta(minutes=10)
        db.flush()
    transport = FakeTransport(mutate=mutate_expiry)
    with create_processing_job_google_doc_from_transcript(db, job_id=job.id, job_source_id=rel.id, lease_owner_id="worker", lease_generation=7, transcript=Transcript(), settings=Settings(), now=now, clock=lambda: now, token_resolver=lambda *a, **k: "token-secret", metadata_fetcher=good_meta, google_docs_transport=transport) as artifact:
        assert artifact.web_view_link == "https://docs.example/private"
    assert len(transport.calls) == 1
    assert db.query(models.TranscriptionOutputReconciliation).one().status == models.OutputReconciliationStatus.creation_returned
