from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Iterator

from sqlalchemy.orm import Session

from .job_claim_lease import is_lease_active
from .models import CredentialProvider, CredentialStatus, JobStatus, Project, ProviderCredential, ProviderCredentialVersion, TranscriptionJob
from .security import aad, decrypt, master_key_from_b64, utcnow

SUPPORTED_PROVIDERS = {
    CredentialProvider.elevenlabs.value,
    CredentialProvider.yandex.value,
    CredentialProvider.openai.value,
    CredentialProvider.tbank.value,
    CredentialProvider.mistral.value,
    CredentialProvider.gemini.value,
}


class ProviderCredentialAccessReason(str, Enum):
    job_not_found = "job_not_found"
    job_not_processing = "job_not_processing"
    lease_not_owned = "lease_not_owned"
    lease_not_active = "lease_not_active"
    cancellation_requested = "cancellation_requested"
    project_unavailable = "project_unavailable"
    credential_missing = "credential_missing"
    credential_unavailable = "credential_unavailable"
    provider_unsupported = "provider_unsupported"
    provider_mismatch = "provider_mismatch"
    version_missing = "version_missing"
    version_unavailable = "version_unavailable"
    encrypted_material_missing = "encrypted_material_missing"
    key_boundary_mismatch = "key_boundary_mismatch"
    decrypt_failed = "decrypt_failed"
    credential_changed = "credential_changed"
    context_closed = "context_closed"


class ProviderCredentialAccessError(RuntimeError):
    def __init__(self, reason: ProviderCredentialAccessReason):
        self.reason = reason
        super().__init__(reason.value)


class _RevocableCredentialSecret:
    def __init__(self, value: str):
        self._value = value
        self._revoked = False

    def get(self) -> str:
        if self._revoked:
            raise ProviderCredentialAccessError(ProviderCredentialAccessReason.context_closed)
        return self._value

    def revoke(self) -> None:
        self._value = ""
        self._revoked = True

    def __repr__(self) -> str:
        return "<redacted>"


@dataclass(frozen=True)
class ProcessingJobProviderCredential:
    credential_id: str
    credential_version_id: str
    provider: str
    _secret: _RevocableCredentialSecret = field(repr=False)

    @property
    def raw_secret(self) -> str:
        return self._secret.get()

    def __repr__(self) -> str:
        return (
            "ProcessingJobProviderCredential("
            f"credential_id={self.credential_id!r}, credential_version_id={self.credential_version_id!r}, "
            f"provider={self.provider!r}, raw_secret=<redacted>)"
        )


@dataclass(frozen=True)
class _CredentialSnapshot:
    job_id: str
    owner_user_id: str
    project_id: str
    provider_credential_id: str
    job_provider: str | None
    credential_id: str
    credential_user_id: str
    credential_provider: str
    credential_status: str
    credential_deleted_at: datetime | None
    active_version_id: str
    version_id: str
    version_credential_id: str
    version_revoked_at: datetime | None
    version_deleted_at: datetime | None
    ciphertext: bytes
    nonce: bytes
    key_id: str
    lease_owner_id: str | None
    lease_generation: int
    lease_expires_at: datetime | None
    cancel_requested_at: datetime | None


@contextmanager
def open_processing_job_provider_credential(
    db: Session,
    *,
    job_id: str,
    lease_owner_id: str,
    lease_generation: int,
    settings,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    master_key_resolver: Callable[[object], bytes] | None = None,
    decryptor: Callable[[bytes, bytes, bytes, bytes], str] = decrypt,
) -> Iterator[ProcessingJobProviderCredential]:
    clock = clock or (lambda: utcnow().replace(tzinfo=None))
    snap = _load_snapshot(db, job_id, lease_owner_id, lease_generation, now or clock(), settings)
    secret_holder: _RevocableCredentialSecret | None = None
    try:
        try:
            key = master_key_resolver(settings) if master_key_resolver else master_key_from_b64(settings.master_key_b64())
            secret_holder = _RevocableCredentialSecret(decryptor(snap.ciphertext, snap.nonce, key, aad(snap.owner_user_id, snap.credential_id, snap.version_id, snap.credential_provider)))
        except Exception as exc:
            raise ProviderCredentialAccessError(ProviderCredentialAccessReason.decrypt_failed) from exc
        _compare_snapshot(snap, _load_snapshot(db, job_id, lease_owner_id, lease_generation, clock(), settings))
        yield ProcessingJobProviderCredential(snap.credential_id, snap.version_id, snap.credential_provider, secret_holder)
    finally:
        if secret_holder is not None:
            secret_holder.revoke()


def _load_snapshot(db: Session, job_id: str, owner: str, generation: int, now: datetime, settings) -> _CredentialSnapshot:
    db.expire_all()
    job = db.get(TranscriptionJob, job_id)
    if job is None:
        raise ProviderCredentialAccessError(ProviderCredentialAccessReason.job_not_found)
    if job.status != JobStatus.processing:
        raise ProviderCredentialAccessError(ProviderCredentialAccessReason.job_not_processing)
    if job.lease_owner_id != owner or job.lease_generation != generation:
        raise ProviderCredentialAccessError(ProviderCredentialAccessReason.lease_not_owned)
    if not is_lease_active(job, now):
        raise ProviderCredentialAccessError(ProviderCredentialAccessReason.lease_not_active)
    if job.cancel_requested_at is not None:
        raise ProviderCredentialAccessError(ProviderCredentialAccessReason.cancellation_requested)
    project = db.get(Project, job.project_id)
    if project is None or project.owner_user_id != job.owner_user_id or project.archived_at is not None:
        raise ProviderCredentialAccessError(ProviderCredentialAccessReason.project_unavailable)
    if not job.provider_credential_id:
        raise ProviderCredentialAccessError(ProviderCredentialAccessReason.credential_missing)
    cred = db.get(ProviderCredential, job.provider_credential_id)
    if cred is None or cred.user_id != job.owner_user_id or cred.status != CredentialStatus.active or cred.deleted_at is not None:
        raise ProviderCredentialAccessError(ProviderCredentialAccessReason.credential_unavailable)
    provider = str(getattr(cred.provider, "value", cred.provider))
    if provider not in SUPPORTED_PROVIDERS:
        raise ProviderCredentialAccessError(ProviderCredentialAccessReason.provider_unsupported)
    if job.provider is not None and job.provider != provider:
        raise ProviderCredentialAccessError(ProviderCredentialAccessReason.provider_mismatch)
    if not cred.active_version_id:
        raise ProviderCredentialAccessError(ProviderCredentialAccessReason.version_missing)
    version = db.get(ProviderCredentialVersion, cred.active_version_id)
    if version is None or version.credential_id != cred.id:
        raise ProviderCredentialAccessError(ProviderCredentialAccessReason.version_missing)
    if version.revoked_at is not None or version.deleted_at is not None:
        raise ProviderCredentialAccessError(ProviderCredentialAccessReason.version_unavailable)
    if not version.ciphertext or not version.nonce or not version.key_id:
        raise ProviderCredentialAccessError(ProviderCredentialAccessReason.encrypted_material_missing)
    if version.key_id != settings.credential_key_id:
        raise ProviderCredentialAccessError(ProviderCredentialAccessReason.key_boundary_mismatch)
    return _CredentialSnapshot(job.id, job.owner_user_id, job.project_id, job.provider_credential_id, job.provider, cred.id, cred.user_id, provider, str(getattr(cred.status, "value", cred.status)), cred.deleted_at, cred.active_version_id, version.id, version.credential_id, version.revoked_at, version.deleted_at, bytes(version.ciphertext), bytes(version.nonce), version.key_id, job.lease_owner_id, job.lease_generation, job.lease_expires_at, job.cancel_requested_at)


def _compare_snapshot(before: _CredentialSnapshot, after: _CredentialSnapshot) -> None:
    if before != after:
        raise ProviderCredentialAccessError(ProviderCredentialAccessReason.credential_changed)
