from __future__ import annotations

import base64
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

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
    def master_key_b64(self):
        return base64.b64encode(b"0" * 32).decode()


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setenv("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    from studio_api.db import Base
    import studio_api.models  # noqa
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close(); Base.metadata.drop_all(engine); engine.dispose()


@pytest.fixture()
def models():
    from studio_api import models as m
    return m


def make_job(db, m, provider="elevenlabs"):
    from studio_api.security import utcnow
    now = utcnow().replace(tzinfo=None)
    user = m.User(email=f"{id(db)}-{provider}@example.com", role=m.UserRole.user, status=m.UserStatus.active)
    db.add(user); db.flush()
    project = m.Project(owner_user_id=user.id, title="p", output_drive_folder_id="configured-folder")
    db.add(project); db.flush()
    cred = m.ProviderCredential(user_id=user.id, provider=m.CredentialProvider(provider), label="k", status=m.CredentialStatus.active)
    db.add(cred); db.flush()
    version = m.ProviderCredentialVersion(credential_id=cred.id, version=1, ciphertext=b"ct", nonce=b"nonce", key_id="credential-key-v1", masked_value="masked-value", fingerprint="digest")
    db.add(version); db.flush()
    cred.active_version_id = version.id
    job = m.TranscriptionJob(project_id=project.id, owner_user_id=user.id, status=m.JobStatus.processing, provider=provider, provider_credential_id=cred.id, output_drive_folder_id="configured-folder", output_drive_folder_url="https://drive.google.com/drive/folders/configured-folder", output_drive_folder_name="Configured", lease_owner_id="worker", lease_generation=7, lease_expires_at=now + timedelta(minutes=5))
    db.add(job); db.flush()
    return user, project, cred, version, job, now


def test_provider_credential_success_aad_and_redaction(db, models):
    from studio_api.provider_credential_access import open_processing_job_provider_credential
    seen = {}
    user, project, cred, version, job, now = make_job(db, models)
    def decryptor(ct, nonce, key, aad):
        seen.update(ct=ct, nonce=nonce, key=key, aad=aad); return "credential-value"
    with open_processing_job_provider_credential(db, job_id=job.id, lease_owner_id="worker", lease_generation=7, settings=Settings(), now=now, decryptor=decryptor) as handle:
        retained = handle
        assert handle.provider == "elevenlabs"
        assert handle.credential_version_id == version.id
        assert handle.raw_secret == "credential-value"
        assert "credential-value" not in repr(handle)
    assert seen["aad"] == f"user={user.id};credential={cred.id};version={version.id};provider=elevenlabs".encode()
    from studio_api.provider_credential_access import ProviderCredentialAccessError
    with pytest.raises(ProviderCredentialAccessError) as exc:
        retained.raw_secret
    assert str(exc.value) == "context_closed"


def test_provider_credential_openai_success(db, models):
    from studio_api.provider_credential_access import open_processing_job_provider_credential
    *_, job, now = make_job(db, models, provider="openai")
    with open_processing_job_provider_credential(db, job_id=job.id, lease_owner_id="worker", lease_generation=7, settings=Settings(), now=now, decryptor=lambda *_: "openai-value") as handle:
        assert handle.provider == "openai"


@pytest.mark.parametrize("mutate,reason", [
    (lambda m, user, project, cred, version, job, now: setattr(job, "provider_credential_id", None), "credential_missing"),
    (lambda m, user, project, cred, version, job, now: setattr(cred, "user_id", "other"), "credential_unavailable"),
    (lambda m, user, project, cred, version, job, now: setattr(cred, "status", m.CredentialStatus.revoked), "credential_unavailable"),
    (lambda m, user, project, cred, version, job, now: setattr(cred, "active_version_id", "missing"), "version_missing"),
    (lambda m, user, project, cred, version, job, now: setattr(version, "revoked_at", now), "version_unavailable"),
    (lambda m, user, project, cred, version, job, now: setattr(version, "ciphertext", None), "encrypted_material_missing"),
    (lambda m, user, project, cred, version, job, now: setattr(job, "provider", "openai"), "provider_mismatch"),
])
def test_provider_credential_failures_are_normalized(db, models, mutate, reason):
    from studio_api.provider_credential_access import ProviderCredentialAccessError, open_processing_job_provider_credential
    user, project, cred, version, job, now = make_job(db, models)
    mutate(models, user, project, cred, version, job, now); db.flush()
    with pytest.raises(ProviderCredentialAccessError) as exc:
        with open_processing_job_provider_credential(db, job_id=job.id, lease_owner_id="worker", lease_generation=7, settings=Settings(), now=now, decryptor=lambda *_: "credential-value"):
            pass
    assert str(exc.value) == reason
    assert "credential-value" not in str(exc.value) and "ct" not in str(exc.value) and "nonce" not in str(exc.value) and "digest" not in str(exc.value)


def test_provider_credential_revalidates_after_decrypt(db, models):
    from studio_api.provider_credential_access import ProviderCredentialAccessError, open_processing_job_provider_credential
    user, project, cred, version, job, now = make_job(db, models)
    def decryptor(*_):
        version.revoked_at = now; db.flush(); return "credential-value"
    with pytest.raises(ProviderCredentialAccessError) as exc:
        with open_processing_job_provider_credential(db, job_id=job.id, lease_owner_id="worker", lease_generation=7, settings=Settings(), now=now, decryptor=decryptor):
            pass
    assert str(exc.value) == "version_unavailable"


def test_provider_credential_caller_exception_propagates(db, models):
    from studio_api.provider_credential_access import open_processing_job_provider_credential
    *_, job, now = make_job(db, models)
    sentinel = ValueError("sentinel")
    with pytest.raises(ValueError) as exc:
        with open_processing_job_provider_credential(db, job_id=job.id, lease_owner_id="worker", lease_generation=7, settings=Settings(), now=now, decryptor=lambda *_: "credential-value"):
            raise sentinel
    assert exc.value is sentinel


def test_output_destination_success_one_token_and_redaction(db, models):
    from studio_api.google_drive import GOOGLE_FOLDER_MIME_TYPE
    from studio_api.job_output_destination import DriveFolderAuthorizationMetadata, verify_processing_job_output_destination
    *_, job, now = make_job(db, models)
    calls = []
    handle = verify_processing_job_output_destination(db, job_id=job.id, lease_owner_id="worker", lease_generation=7, settings=Settings(), now=now, token_resolver=lambda *a, **k: calls.append(1) or "ephemeral-access", metadata_fetcher=lambda token, folder: DriveFolderAuthorizationMetadata(folder, GOOGLE_FOLDER_MIME_TYPE, False, True))
    assert calls == [1]
    assert handle.drive_folder_id == "configured-folder"
    assert "configured-folder" not in repr(handle) and "ephemeral-access" not in repr(handle)


@pytest.mark.parametrize("meta,reason", [
    (("other", "application/vnd.google-apps.folder", False, True), "output_identity_mismatch"),
    (("configured-folder", "text/plain", False, True), "output_not_folder"),
    (("configured-folder", "application/vnd.google-apps.folder", True, True), "metadata_unavailable"),
    (("configured-folder", "application/vnd.google-apps.folder", None, True), "metadata_unavailable"),
    (("configured-folder", "application/vnd.google-apps.folder", False, False), "output_folder_not_writable"),
    (("configured-folder", "application/vnd.google-apps.folder", False, None), "output_folder_not_writable"),
])
def test_output_destination_metadata_failures(db, models, meta, reason):
    from studio_api.job_output_destination import DriveFolderAuthorizationMetadata, OutputDestinationError, verify_processing_job_output_destination
    *_, job, now = make_job(db, models)
    with pytest.raises(OutputDestinationError) as exc:
        verify_processing_job_output_destination(db, job_id=job.id, lease_owner_id="worker", lease_generation=7, settings=Settings(), now=now, token_resolver=lambda *a, **k: "ephemeral-token", metadata_fetcher=lambda *_: DriveFolderAuthorizationMetadata(*meta))
    assert str(exc.value) == reason
    assert "configured-folder" not in str(exc.value) and "ephemeral-token" not in str(exc.value)


@pytest.mark.parametrize("status", [200, 403])
def test_yandex_output_destination_checks_write_authority_without_creating_file(db, models, monkeypatch, status):
    from studio_api import yandex_disk_access
    from studio_api.job_output_destination import OutputDestinationError, verify_processing_job_output_destination
    from studio_api.yandex_disk import YandexDiskClient, resource_from_payload

    user, *_, job, now = make_job(db, models)
    db.add(models.YandexDiskConnection(
        user_id=user.id, account_uid="synthetic-account", token_ciphertext=b"token",
        token_nonce=b"nonce", key_id="credential-key-v1",
    ))
    db.flush()
    folder = {"path": "disk:/results", "resource_id": "result-folder", "name": "Results", "type": "dir"}
    selection = yandex_disk_access.register_resource(db, owner_user_id=user.id, resource=resource_from_payload(folder))
    job.output_provider = "yandex_disk"
    job.output_drive_folder_id = selection.id
    db.commit()
    calls = []

    def provider(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/upload"):
            assert request.url.params["path"].startswith("disk:/results/.voiceops-write-check-")
            assert request.url.params["overwrite"] == "false"
            return httpx.Response(status, json={"href": "https://uploader.disk.yandex.ru/test", "method": "PUT"})
        return httpx.Response(200, json=folder)

    monkeypatch.setattr(yandex_disk_access, "access_token", lambda *args, **kwargs: "synthetic")
    original_verifier = yandex_disk_access.verify_selected_resource
    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        monkeypatch.setattr(
            yandex_disk_access, "verify_selected_resource",
            lambda *args, **kwargs: original_verifier(
                *args, **kwargs, client_factory=lambda token: YandexDiskClient(token, client=client),
            ),
        )
        kwargs = dict(db=db, job_id=job.id, lease_owner_id="worker", lease_generation=7, settings=Settings(), now=now)
        if status == 403:
            with pytest.raises(OutputDestinationError, match="output_folder_not_writable"):
                verify_processing_job_output_destination(**kwargs)
        else:
            assert verify_processing_job_output_destination(**kwargs).drive_folder_id == selection.id
    assert calls == [("GET", "/v1/disk/resources"), ("GET", "/v1/disk/resources/upload")]


def test_output_destination_revalidates_after_io(db, models):
    from studio_api.google_drive import GOOGLE_FOLDER_MIME_TYPE
    from studio_api.job_output_destination import DriveFolderAuthorizationMetadata, OutputDestinationError, verify_processing_job_output_destination
    user, project, cred, version, job, now = make_job(db, models)
    def fetcher(token, folder):
        job.output_drive_folder_id = "changed-private-id"; db.flush()
        return DriveFolderAuthorizationMetadata(folder, GOOGLE_FOLDER_MIME_TYPE, False, True)
    with pytest.raises(OutputDestinationError) as exc:
        verify_processing_job_output_destination(db, job_id=job.id, lease_owner_id="worker", lease_generation=7, settings=Settings(), now=now, token_resolver=lambda *a, **k: "token", metadata_fetcher=fetcher)
    assert str(exc.value) == "output_destination_changed"


def test_execution_prerequisites_success_redacted_and_caller_exception(db, models):
    from studio_api.google_drive import GOOGLE_FOLDER_MIME_TYPE
    from studio_api.job_execution_context import open_processing_job_execution_prerequisites
    from studio_api.job_output_destination import DriveFolderAuthorizationMetadata
    *_, version, job, now = make_job(db, models)
    verifier_kwargs = {
        "token_resolver": lambda *a, **k: "ephemeral-access",
        "metadata_fetcher": lambda token, folder: DriveFolderAuthorizationMetadata(folder, GOOGLE_FOLDER_MIME_TYPE, False, True),
        "decryptor": lambda *_: "credential-value",
    }
    with open_processing_job_execution_prerequisites(db, job_id=job.id, lease_owner_id="worker", lease_generation=7, settings=Settings(), now=now, **verifier_kwargs) as handle:
        retained = handle
        assert handle.provider == "elevenlabs" and handle.credential_version_id == version.id
        assert handle.raw_credential_secret == "credential-value"
        assert "credential-value" not in repr(handle) and "configured-folder" not in repr(handle)
    from studio_api.provider_credential_access import ProviderCredentialAccessError
    with pytest.raises(ProviderCredentialAccessError) as closed:
        retained.raw_credential_secret
    assert str(closed.value) == "context_closed"
    sentinel = RuntimeError("caller")
    with pytest.raises(RuntimeError) as exc:
        with open_processing_job_execution_prerequisites(db, job_id=job.id, lease_owner_id="worker", lease_generation=7, settings=Settings(), now=now, **verifier_kwargs):
            raise sentinel
    assert exc.value is sentinel


def test_execution_prerequisites_final_revalidation_blocks_credential_mutation(db, models):
    from studio_api.google_drive import GOOGLE_FOLDER_MIME_TYPE
    from studio_api.job_execution_context import JobExecutionContextError, open_processing_job_execution_prerequisites
    from studio_api.job_output_destination import DriveFolderAuthorizationMetadata
    user, project, cred, version, job, now = make_job(db, models)
    def fetcher(token, folder):
        version.revoked_at = now; db.flush()
        return DriveFolderAuthorizationMetadata(folder, GOOGLE_FOLDER_MIME_TYPE, False, True)
    with pytest.raises(JobExecutionContextError) as exc:
        with open_processing_job_execution_prerequisites(db, job_id=job.id, lease_owner_id="worker", lease_generation=7, settings=Settings(), now=now, decryptor=lambda *_: "credential-value", token_resolver=lambda *a, **k: "token", metadata_fetcher=fetcher):
            pass
    assert str(exc.value) == "credential_unavailable"


def test_execution_prerequisites_final_revalidation_blocks_credential_replacement(db, models):
    from studio_api.google_drive import GOOGLE_FOLDER_MIME_TYPE
    from studio_api.job_execution_context import JobExecutionContextError, open_processing_job_execution_prerequisites
    from studio_api.job_output_destination import DriveFolderAuthorizationMetadata
    user, project, cred, version, job, now = make_job(db, models)
    def fetcher(token, folder):
        replacement = models.ProviderCredentialVersion(credential_id=cred.id, version=2, ciphertext=b"ct2", nonce=b"nonce2", key_id="credential-key-v1", masked_value="masked-value", fingerprint="digest2")
        db.add(replacement); db.flush()
        cred.active_version_id = replacement.id; db.flush()
        return DriveFolderAuthorizationMetadata(folder, GOOGLE_FOLDER_MIME_TYPE, False, True)
    with pytest.raises(JobExecutionContextError) as exc:
        with open_processing_job_execution_prerequisites(db, job_id=job.id, lease_owner_id="worker", lease_generation=7, settings=Settings(), now=now, decryptor=lambda *_: "credential-value", token_resolver=lambda *a, **k: "token", metadata_fetcher=fetcher):
            pass
    assert str(exc.value) == "credential_unavailable"


def test_execution_prerequisites_output_verification_blocks_lease_loss_and_cancellation(db, models):
    from studio_api.google_drive import GOOGLE_FOLDER_MIME_TYPE
    from studio_api.job_execution_context import JobExecutionContextError, open_processing_job_execution_prerequisites
    from studio_api.job_output_destination import DriveFolderAuthorizationMetadata
    *_, job, now = make_job(db, models)
    def fetcher(token, folder):
        job.lease_owner_id = "other"; db.flush()
        return DriveFolderAuthorizationMetadata(folder, GOOGLE_FOLDER_MIME_TYPE, False, True)
    with pytest.raises(JobExecutionContextError) as exc:
        with open_processing_job_execution_prerequisites(db, job_id=job.id, lease_owner_id="worker", lease_generation=7, settings=Settings(), now=now, decryptor=lambda *_: "credential-value", token_resolver=lambda *a, **k: "token", metadata_fetcher=fetcher):
            pass
    assert str(exc.value) == "output_destination_unavailable"

    *_, job2, now2 = make_job(db, models, provider="openai")
    def canceling_fetcher(token, folder):
        job2.cancel_requested_at = now2; db.flush()
        return DriveFolderAuthorizationMetadata(folder, GOOGLE_FOLDER_MIME_TYPE, False, True)
    with pytest.raises(JobExecutionContextError) as cancel_exc:
        with open_processing_job_execution_prerequisites(db, job_id=job2.id, lease_owner_id="worker", lease_generation=7, settings=Settings(), now=now2, decryptor=lambda *_: "credential-value", token_resolver=lambda *a, **k: "token", metadata_fetcher=canceling_fetcher):
            pass
    assert str(cancel_exc.value) == "output_destination_unavailable"


def test_execution_prerequisites_preserves_caller_provider_credential_error(db, models):
    from studio_api.google_drive import GOOGLE_FOLDER_MIME_TYPE
    from studio_api.job_execution_context import open_processing_job_execution_prerequisites
    from studio_api.job_output_destination import DriveFolderAuthorizationMetadata
    from studio_api.provider_credential_access import ProviderCredentialAccessError, ProviderCredentialAccessReason
    *_, job, now = make_job(db, models)
    sentinel = ProviderCredentialAccessError(ProviderCredentialAccessReason.credential_changed)
    with pytest.raises(ProviderCredentialAccessError) as exc:
        with open_processing_job_execution_prerequisites(db, job_id=job.id, lease_owner_id="worker", lease_generation=7, settings=Settings(), now=now, decryptor=lambda *_: "credential-value", token_resolver=lambda *a, **k: "token", metadata_fetcher=lambda token, folder: DriveFolderAuthorizationMetadata(folder, GOOGLE_FOLDER_MIME_TYPE, False, True)):
            raise sentinel
    assert exc.value is sentinel
