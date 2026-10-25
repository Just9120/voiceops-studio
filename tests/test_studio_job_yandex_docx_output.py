"""Worker output and recovery using real guards/DB, synthetic Disk only."""
from datetime import datetime, timedelta
import base64
import hashlib
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))
os.environ.setdefault("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
from studio_api import models as m
from studio_api.db import Base
from studio_api.job_google_docs_output import JobGoogleDocsOutputError
from studio_api.job_output_persistence import persist_processing_job_source_output_and_maybe_complete
from studio_api.job_output_reconciliation import prepare_output_reconciliation_case
from studio_api.job_yandex_docx_output import create_processing_job_yandex_docx
from studio_api.transcript_docx import DOCX_MIME_TYPE, DOCX_OUTPUT_KIND
from studio_api.yandex_disk import YandexDiskError, resource_from_payload
from studio_api.yandex_output_reconciliation import check_yandex_output_reconciliation

NOW = datetime(2026, 10, 25, 12)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


def setup(db):
    user = m.User(email="docx-owner@example.test")
    db.add(user)
    db.flush()
    project = m.Project(owner_user_id=user.id, title="Docs")
    db.add(project)
    db.flush()
    source = m.Source(project_id=project.id, source_type=m.SourceType.local_upload,
        original_filename="Meeting 25.10.2026.flac", size_bytes=1, mime_type="audio/flac",
        upload_status=m.SourceUploadStatus.uploaded, s3_bucket="synthetic", s3_object_key="synthetic")
    db.add(source)
    db.flush()
    job = m.TranscriptionJob(project_id=project.id, owner_user_id=user.id,
        output_provider="yandex_disk", output_drive_folder_id="folder-handle",
        title="Meeting 25.10.2026", provider="elevenlabs", status=m.JobStatus.processing,
        lease_owner_id="worker", lease_generation=1, claimed_at=NOW, lease_expires_at=NOW + timedelta(hours=1), attempt_count=1)
    db.add(job)
    db.flush()
    relation = m.TranscriptionJobSource(job_id=job.id, source_id=source.id, position=0)
    db.add(relation)
    db.add(m.YandexDiskConnection(user_id=user.id, account_uid="uid", token_ciphertext=b"synthetic",
        token_nonce=b"synthetic", key_id="test", credential_revision=1))
    db.commit()
    folder = resource_from_payload({"path": "disk:/Docs", "name": "Docs", "type": "dir"})
    transcript = SimpleNamespace(text="Полный текст без повторного STT", words=(), detected_language_code="ru")
    settings = SimpleNamespace(source_max_upload_bytes=1000)
    return user, project, source, job, relation, folder, transcript, settings


class Disk:
    def __init__(self, db, job, *, error=None, after_upload=None):
        self.db, self.job_id = db, job.id
        self.resources = {}
        self.error = error
        self.after_upload = after_upload
        self.uploads = 0

    def metadata(self, path):
        if path not in self.resources:
            raise YandexDiskError("not_found")
        return self.resources[path]

    def upload_new(self, path, data):
        assert not self.db.in_transaction(), "external I/O must not hold a worker transaction"
        receipt = self.db.scalar(select(m.TranscriptionOutputReconciliation).where(
            m.TranscriptionOutputReconciliation.job_id == self.job_id))
        assert receipt.expected_docx_path == path
        assert receipt.expected_document_sha256 == hashlib.sha256(data).hexdigest()
        self.db.rollback()
        self.uploads += 1
        if self.error:
            raise YandexDiskError(self.error)
        result = resource_from_payload({"type": "file", "resource_id": "opaque",
            "path": path, "name": path.rsplit("/", 1)[1], "size": len(data), "mime_type": DOCX_MIME_TYPE,
            "md5": hashlib.md5(data, usedforsecurity=False).hexdigest(), "sha256": hashlib.sha256(data).hexdigest()})
        self.resources[path] = result
        if self.after_upload:
            self.after_upload()
        return result


def opener(db, job, relation, folder, transcript, settings, disk):
    return create_processing_job_yandex_docx(db, job_id=job.id, job_source_id=relation.id,
        lease_owner_id="worker", lease_generation=job.lease_generation,
        transcript=transcript, settings=settings, now=NOW, clock=lambda: NOW,
        resource_verifier=lambda *a, **kw: folder,
        token_resolver=lambda *a, **kw: "synthetic", client_factory=lambda token: disk)


def failed(db, job):
    job.status = m.JobStatus.failed
    job.error_code = "output_reconciliation_required"
    job.lease_expires_at = NOW - timedelta(seconds=1)
    for case in db.scalars(select(m.TranscriptionOutputReconciliation)):
        case.status = m.OutputReconciliationStatus.reconciliation_required
    db.commit()


def reconcile(db, owner, job, folder, settings, disk):
    return check_yandex_output_reconciliation(db, owner_user_id=owner.id, job_id=job.id,
        settings=settings, now=NOW, resource_verifier=lambda *a, **kw: folder,
        token_resolver=lambda *a, **kw: "synthetic", client_factory=lambda token: disk)


def test_worker_persists_docx_kind_only_after_confirmed_full_upload(db):
    owner, _, _, job, relation, folder, transcript, settings = setup(db)
    disk = Disk(db, job)
    with opener(db, job, relation, folder, transcript, settings, disk) as artifact:
        assert db.query(m.TranscriptionJobOutput).count() == 0
        assert artifact.output_provider == "yandex_disk" and artifact.output_kind == DOCX_OUTPUT_KIND
        outcome = persist_processing_job_source_output_and_maybe_complete(db, job_id=job.id,
            job_source_id=relation.id, lease_owner_id="worker", lease_generation=1,
            artifact=artifact, now=NOW)
        db.commit()
        assert outcome.completed
    row = db.scalar(select(m.TranscriptionJobOutput))
    assert row.output_kind == DOCX_OUTPUT_KIND and row.web_view_url.startswith("https://disk.yandex.ru/client/disk/")
    assert job.status == m.JobStatus.completed and disk.uploads == 1
    assert db.get(m.YandexDiskResource, row.document_id).owner_user_id == owner.id
    from studio_api.transcript_manifest_export import manifest_snapshot
    import json
    payload, count = manifest_snapshot(db, user_id=owner.id)
    assert count == 1
    assert json.loads(payload)["entries"][0]["output_provider"] == "yandex_disk"


def test_upload_that_completed_after_lost_lease_can_be_reconciled_without_resubmit(db):
    owner, _, _, job, relation, folder, transcript, settings = setup(db)
    def lose_lease():
        job.lease_generation += 1
        db.commit()
    disk = Disk(db, job, after_upload=lose_lease)
    with pytest.raises(JobGoogleDocsOutputError):
        with opener(db, job, relation, folder, transcript, settings, disk):
            pytest.fail("lost lease must not persist output")
    assert db.query(m.TranscriptionJobOutput).count() == 0 and disk.uploads == 1
    failed(db, job)
    result = reconcile(db, owner, job, folder, settings, disk)
    assert result.resolved == 1 and job.status == m.JobStatus.completed
    assert disk.uploads == 1 and db.scalar(select(m.TranscriptionJobOutput)).output_kind == DOCX_OUTPUT_KIND


@pytest.mark.parametrize("error", ["quota_exceeded", "permission_denied", "timeout"])
def test_confirmed_absence_allows_create_only_export_retry_with_same_receipt(db, error):
    owner, _, _, job, relation, folder, transcript, settings = setup(db)
    disk = Disk(db, job, error=error)
    with pytest.raises(JobGoogleDocsOutputError, match="yandex_disk_"):
        with opener(db, job, relation, folder, transcript, settings, disk):
            pytest.fail("failed export is not success")
    case = db.scalar(select(m.TranscriptionOutputReconciliation))
    fingerprint, receipt = case.expected_document_sha256, case.reconciliation_token
    failed(db, job)
    checked = reconcile(db, owner, job, folder, settings, disk)
    assert checked.unresolved == 1 and checked.resolved == 0
    assert case.status == m.OutputReconciliationStatus.resolved and case.uncertainty_reason == "yandex_output_absent"
    assert job.status == m.JobStatus.failed and db.query(m.TranscriptionJobOutput).count() == 0
    job.status = m.JobStatus.processing
    job.attempt_count = 2
    job.lease_generation = 2
    job.lease_expires_at = NOW + timedelta(hours=1)
    db.commit()
    disk.error = None
    with opener(db, job, relation, folder, transcript, settings, disk) as artifact:
        assert artifact.output_kind == DOCX_OUTPUT_KIND
    assert case.expected_document_sha256 == fingerprint and case.reconciliation_token == receipt
    assert disk.uploads == 2


def test_unknown_permission_error_cannot_be_recorded_as_absence(db):
    owner, _, _, job, relation, folder, transcript, settings = setup(db)
    disk = Disk(db, job, error="quota_exceeded")
    with pytest.raises(JobGoogleDocsOutputError):
        with opener(db, job, relation, folder, transcript, settings, disk):
            pass
    failed(db, job)
    def denied(path):
        raise YandexDiskError("permission_denied")
    disk.metadata = denied
    checked = reconcile(db, owner, job, folder, settings, disk)
    assert checked.unavailable == 1 and checked.unresolved == 0
    assert db.scalar(select(m.TranscriptionOutputReconciliation)).status == m.OutputReconciliationStatus.reconciliation_required


def test_edited_docx_becomes_conflict_without_overwrite(db):
    from dataclasses import replace
    owner, _, _, job, relation, folder, transcript, settings = setup(db)
    disk = Disk(db, job)
    with opener(db, job, relation, folder, transcript, settings, disk):
        pass
    failed(db, job)
    path = next(iter(disk.resources))
    disk.resources[path] = replace(disk.resources[path], sha256="0" * 64)
    checked = reconcile(db, owner, job, folder, settings, disk)
    assert checked.conflicts == 1 and checked.resolved == 0 and disk.uploads == 1
    assert job.status == m.JobStatus.failed and db.query(m.TranscriptionJobOutput).count() == 0


def test_other_owner_cannot_probe_receipt_or_change_result(db):
    owner, _, _, job, _, folder, _, settings = setup(db)
    calls = []
    from studio_api.job_output_reconciliation import OutputReconciliationError
    failed(db, job)
    with pytest.raises(OutputReconciliationError):
        check_yandex_output_reconciliation(db, owner_user_id="other-owner", job_id=job.id,
            settings=settings, now=NOW, client_factory=lambda token: calls.append(token))
    assert calls == [] and db.query(m.TranscriptionJobOutput).count() == 0


def cached_yandex(db):
    from studio_api.elevenlabs_transcription import normalize_elevenlabs_transcript_response
    from studio_api.yandex_transcription import YandexTranscriptionTransport
    owner, project, source, job, relation, folder, _, settings = setup(db)
    settings.master_key_b64 = lambda: base64.b64encode(b"s" * 32).decode()
    settings.credential_key_id = "test-v1"
    job.provider = "yandex"
    job.operating_mode = "standard"
    job.options_json = '{"_stt_model":"general","diarize":false}'
    job.attempt_count = 2
    source.upload_status = m.SourceUploadStatus.expired
    source.expires_at = NOW - timedelta(days=1)
    source.s3_bucket = source.s3_object_key = None
    operation = m.SttProviderOperation(owner_user_id=owner.id, project_id=project.id,
        job_id=job.id, job_source_id=relation.id, attempt_number=1, provider="yandex",
        operating_mode="standard", model="general", operation_id="synthetic-operation", status="pending")
    db.add(operation)
    db.flush()
    result = normalize_elevenlabs_transcript_response({"text": "Готовый сохранённый текст",
        "language_code": "ru", "words": [{"text": "Готовый сохранённый текст", "type": "word", "start": 0, "end": 1}]})
    YandexTranscriptionTransport(db, job.id, relation.id, settings, "synthetic-folder", lambda: NOW)._persist_result(operation, result)
    result.revoke()
    return owner, project, source, job, relation, folder, operation, settings


def test_cached_speechkit_exports_without_source_provider_key_or_request_and_retires_text(db, monkeypatch):
    from studio_api.job_retry_recovery import prepare_current_attempt_sources
    from studio_api.job_stt_transcription import transcribe_processing_job_source
    from studio_api.yandex_transcription import YandexTranscriptionTransport
    owner, _, _, job, relation, folder, operation, settings = cached_yandex(db)
    monkeypatch.setattr(YandexTranscriptionTransport, "_request", lambda *a, **kw: pytest.fail("must not call STT"))
    monkeypatch.setattr(YandexTranscriptionTransport, "_submit", lambda *a, **kw: pytest.fail("must not resubmit STT"))
    prepare_current_attempt_sources(db, job_id=job.id, lease_owner_id="worker", lease_generation=1, now=NOW)
    db.commit()
    disk = Disk(db, job)
    with transcribe_processing_job_source(db, job_id=job.id, job_source_id=relation.id,
            lease_owner_id="worker", lease_generation=1, settings=settings, now=NOW, clock=lambda: NOW) as transcript:
        assert transcript.text == "Готовый сохранённый текст"
        with opener(db, job, relation, folder, transcript, settings, disk) as artifact:
            result = persist_processing_job_source_output_and_maybe_complete(db, job_id=job.id,
                job_source_id=relation.id, lease_owner_id="worker", lease_generation=1, artifact=artifact, now=NOW)
            db.commit()
            assert result.completed
    assert operation.result_ciphertext is operation.result_nonce is operation.result_key_id is operation.result_hmac is None
    assert operation.status == "completed" and operation.operation_id == "synthetic-operation"
    assert db.query(m.ProviderCredential).count() == 0 and disk.uploads == 1


def test_full_cached_export_is_not_a_new_paid_attempt_when_transport_retry_limit_is_reached(db):
    from studio_api.job_retry_recovery import compute_explicit_retry_readiness, requires_provider_cost_confirmation
    _, _, _, job, _, _, operation, _ = cached_yandex(db)
    job.status = m.JobStatus.failed
    job.attempt_count = 5
    job.lease_expires_at = NOW - timedelta(seconds=1)
    db.commit()
    result = compute_explicit_retry_readiness(db, job, now=NOW)
    assert result.available and result.reason.value == "full_provider_restore_available"
    assert not requires_provider_cost_confirmation(result) and operation.result_ciphertext is not None


def test_corrupt_cached_result_does_not_fall_back_to_paid_transcription(db, monkeypatch):
    from studio_api.job_retry_recovery import prepare_current_attempt_sources
    from studio_api.job_stt_transcription import transcribe_processing_job_source
    from studio_api.elevenlabs_transcription import ElevenLabsTranscriptionError
    from studio_api.yandex_transcription import YandexTranscriptionTransport
    _, _, _, job, relation, _, operation, settings = cached_yandex(db)
    operation.result_ciphertext = b"corrupt"
    prepare_current_attempt_sources(db, job_id=job.id, lease_owner_id="worker", lease_generation=1, now=NOW)
    db.commit()
    monkeypatch.setattr(YandexTranscriptionTransport, "_request", lambda *a, **kw: pytest.fail("no fallback request"))
    with pytest.raises(ElevenLabsTranscriptionError):
        with transcribe_processing_job_source(db, job_id=job.id, job_source_id=relation.id,
                lease_owner_id="worker", lease_generation=1, settings=settings, now=NOW, clock=lambda: NOW):
            pytest.fail("corrupt result is not a transcript")
    assert operation.result_ciphertext == b"corrupt" and db.query(m.TranscriptionJobOutput).count() == 0


def test_authorized_cancellation_retires_only_text_and_keeps_operation_metadata(db):
    from studio_api.job_processing_lifecycle import acknowledge_job_cancellation, request_job_cancellation
    _, _, _, job, _, _, operation, _ = cached_yandex(db)
    request_job_cancellation(db, job_id=job.id, now=NOW)
    assert operation.result_ciphertext is not None  # Still processing until acknowledgment.
    acknowledge_job_cancellation(db, job_id=job.id, lease_owner_id="worker", lease_generation=1, now=NOW)
    db.commit()
    assert operation.result_ciphertext is operation.result_nonce is None
    assert operation.operation_id == "synthetic-operation" and operation.provider == "yandex"
    assert job.status == m.JobStatus.cancelled


def test_failed_export_cannot_discard_text_or_turn_missing_document_into_success(db):
    from studio_api.job_cached_transcript import retire_cached_yandex_result
    _, _, _, job, relation, _, operation, _ = cached_yandex(db)
    with pytest.raises(ValueError, match="Verified output"):
        retire_cached_yandex_result(db, job_id=job.id, job_source_id=relation.id)
    assert operation.result_ciphertext is not None
    assert db.query(m.TranscriptionJobOutput).count() == 0


def test_full_worker_orchestration_restores_cached_speechkit_to_disk_without_paid_calls(db, monkeypatch):
    from studio_api.job_processing_orchestrator import orchestrate_processing_job
    from studio_api.yandex_transcription import YandexTranscriptionTransport
    _, _, _, job, _, folder, operation, settings = cached_yandex(db)
    monkeypatch.setattr(YandexTranscriptionTransport, "_request", lambda *a, **kw: pytest.fail("no STT transport"))
    disk = Disk(db, job)
    def output(db, **kwargs):
        return create_processing_job_yandex_docx(db, **kwargs,
            resource_verifier=lambda *a, **kw: folder,
            token_resolver=lambda *a, **kw: "synthetic", client_factory=lambda token: disk)
    outcome = orchestrate_processing_job(db, job_id=job.id, lease_owner_id="worker", lease_generation=1,
        settings=settings, clock=lambda: NOW, lease_ttl=timedelta(hours=1), google_docs_opener=output)
    assert outcome.final_job_status == m.JobStatus.completed and outcome.completion_occurred
    assert outcome.persisted_output_count == disk.uploads == 1
    assert operation.result_ciphertext is None
    assert (job.provider_billed_duration_ms or 0) == 0
    assert all((attempt.provider_billed_duration_ms or 0) == 0 and attempt.provider_accounting_status == "not_started"
               for attempt in db.scalars(select(m.TranscriptionJobSourceAttempt)))


def test_output_and_text_retirement_roll_back_together(db):
    from studio_api.job_retry_recovery import prepare_current_attempt_sources
    from studio_api.job_stt_transcription import transcribe_processing_job_source
    _, _, _, job, relation, folder, operation, settings = cached_yandex(db)
    prepare_current_attempt_sources(db, job_id=job.id, lease_owner_id="worker", lease_generation=1, now=NOW)
    db.commit()
    disk = Disk(db, job)
    with transcribe_processing_job_source(db, job_id=job.id, job_source_id=relation.id,
            lease_owner_id="worker", lease_generation=1, settings=settings, now=NOW, clock=lambda: NOW) as transcript:
        with opener(db, job, relation, folder, transcript, settings, disk) as artifact:
            persist_processing_job_source_output_and_maybe_complete(db, job_id=job.id,
                job_source_id=relation.id, lease_owner_id="worker", lease_generation=1, artifact=artifact, now=NOW)
            db.rollback()
    db.expire_all()
    assert db.query(m.TranscriptionJobOutput).count() == 0
    assert operation.result_ciphertext is not None
    assert job.status == m.JobStatus.processing


def test_batch_api_preserves_disk_folder_snapshot_and_legacy_google_adapter(db, monkeypatch):
    from fastapi.testclient import TestClient
    from studio_api import main
    from studio_api.job_output_folder_selection import VerifiedOutputFolderSelection
    from studio_api import yandex_disk_routes
    owner = m.User(email="batch-owner@example.test")
    db.add(owner); db.flush()
    project = m.Project(owner_user_id=owner.id, title="Batch")
    db.add(project); db.flush()
    sources = [m.Source(project_id=project.id, source_type=m.SourceType.local_upload,
        original_filename=f"source-{i}.wav", size_bytes=10, mime_type="audio/wav",
        upload_status=m.SourceUploadStatus.uploaded, s3_bucket="synthetic", s3_object_key=f"key-{i}") for i in range(2)]
    db.add_all(sources)
    credential = m.ProviderCredential(user_id=owner.id, provider=m.CredentialProvider.elevenlabs,
        label="Synthetic", status=m.CredentialStatus.active)
    db.add(credential); db.commit()
    handle = "6f5d76f9-1ced-44a4-abf5-9ff96092687e"
    monkeypatch.setitem(main.app.dependency_overrides, main.get_db, lambda: db)
    monkeypatch.setitem(main.app.dependency_overrides, main.require_csrf, lambda: (None, owner))
    monkeypatch.setattr(main.limiter, "check", lambda *a, **kw: None)
    monkeypatch.setattr(main, "refreshed_google_drive_access_token", lambda *a: "synthetic")
    # Existing adapters may return the historical four-field protocol object.
    monkeypatch.setattr(main, "verify_output_folder_selection", lambda token, fid: SimpleNamespace(
        id=fid, name="Google", web_view_url="https://drive.google.com/drive/folders/synthetic", verified_at=NOW))
    monkeypatch.setattr(yandex_disk_routes, "verify_yandex_output_folder", lambda *a, **kw:
        VerifiedOutputFolderSelection(handle, "Disk", "https://disk.yandex.ru/client/disk/Docs", NOW, provider="yandex_disk"))
    payload = {"language":"ru", "provider_credential_id":credential.id, "items":[
        {"source_id":sources[0].id,"output_folder_id":"google-folder","title":"First"},
        {"source_id":sources[1].id,"output_folder_id":handle,"output_provider":"yandex_disk","title":"Second"}]}
    url = f"/api/projects/{project.id}/jobs/batch"
    with TestClient(main.app) as client:
        response = client.post(url, json=payload, headers={"Idempotency-Key":"synthetic-batch-key"})
        assert response.status_code == 200, response.text
        assert [item["output_provider"] for item in response.json()["jobs"]] == ["google_drive","yandex_disk"]
        assert response.json()["jobs"][1]["output_folder"]["web_view_url"] == "https://disk.yandex.ru/client/disk/Docs"
        replay = client.post(url, json=payload, headers={"Idempotency-Key":"synthetic-batch-key"})
        assert replay.status_code == 200 and replay.json()["replayed"]
