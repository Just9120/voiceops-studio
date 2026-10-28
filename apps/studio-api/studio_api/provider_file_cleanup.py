"""Retry deletion of exactly receipted temporary provider files, never user files."""
from datetime import timedelta, timezone
import re

import httpx
from sqlalchemy import or_, select

from .batch_stt_transport import BatchHttpTransport
from .models import SttProviderOperation, TranscriptionJob, ProviderCredential, ProviderCredentialVersion, CredentialProvider
from .security import aad, decrypt, master_key_from_b64
from .job_claim_lease import is_lease_active

FILE_NAME = re.compile(r"files/[A-Za-z0-9_-]{1,120}\Z")


def process_one_provider_file_cleanup(*, session_factory, settings, now, client=None):
    with session_factory() as db:
        operation = db.scalar(select(SttProviderOperation).join(TranscriptionJob, TranscriptionJob.id == SttProviderOperation.job_id).where(
            SttProviderOperation.provider == "gemini", SttProviderOperation.external_file_id.is_not(None),
            SttProviderOperation.external_file_deleted_at.is_(None), SttProviderOperation.updated_at < now - timedelta(minutes=5),
            or_(TranscriptionJob.lease_owner_id.is_(None), TranscriptionJob.lease_expires_at.is_(None), TranscriptionJob.lease_expires_at <= now)
        ).order_by(SttProviderOperation.updated_at, SttProviderOperation.id).limit(1).with_for_update(skip_locked=True))
        if operation is None: return False
        job = db.get(TranscriptionJob, operation.job_id)
        if job is None or job.owner_user_id != operation.owner_user_id or is_lease_active(job, now): return False
        version = db.get(ProviderCredentialVersion, operation.external_file_credential_version_id) if operation.external_file_credential_version_id else None
        credential = db.get(ProviderCredential, version.credential_id) if version else None
        # Mark observation even if the key was erased, so an unavailable receipt
        # cannot monopolize the serial cleanup queue. No secret is resurrected.
        operation.updated_at = now
        db.commit()
        if (not version or not credential or credential.user_id != operation.owner_user_id
            or credential.provider != CredentialProvider.gemini or version.key_id != settings.credential_key_id
            or not version.ciphertext or not version.nonce or not FILE_NAME.fullmatch(operation.external_file_id)):
            return False
        try:
            key = decrypt(version.ciphertext, version.nonce, master_key_from_b64(settings.master_key_b64()),
                aad(credential.user_id, credential.id, version.id, credential.provider.value))
            transport = BatchHttpTransport(client=client)
            transport.timeout = 10
            with transport.connection() as connection:
                try:
                    transport.request(connection, "DELETE", "https://generativelanguage.googleapis.com/v1beta/" + operation.external_file_id,
                        headers={"x-goog-api-key": key}, json_result=False)
                except Exception as exc:
                    # Authenticated 404 means the exact receipted file is absent.
                    if getattr(exc, "http_status", None) != 404: raise
            operation.external_file_deleted_at = now
            db.commit()
            return True
        except (ValueError, httpx.HTTPError, RuntimeError):
            db.rollback()
            return False
