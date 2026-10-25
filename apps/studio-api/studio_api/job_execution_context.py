from __future__ import annotations

import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Iterator

from sqlalchemy.orm import Session

from .job_output_destination import (
    OutputDestinationError,
    OutputDestinationReason,
    ProcessingJobOutputDestination,
    verify_processing_job_output_destination,
    _load_snapshot as _load_output_snapshot,
)
from .provider_credential_access import (
    ProviderCredentialAccessError,
    ProviderCredentialAccessReason,
    ProcessingJobProviderCredential,
    open_processing_job_provider_credential,
    _load_snapshot as _load_credential_snapshot,
)
from .security import utcnow


class JobExecutionContextReason(str, Enum):
    credential_unavailable = "credential_unavailable"
    output_destination_unavailable = "output_destination_unavailable"


class JobExecutionContextError(RuntimeError):
    def __init__(self, reason: JobExecutionContextReason):
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True)
class ProcessingJobExecutionPrerequisites:
    job_id: str
    provider: str
    credential_version_id: str
    verification_timestamp: datetime
    lease_generation: int
    _credential: ProcessingJobProviderCredential = field(repr=False)
    output_drive_folder_id: str = field(repr=False)

    @property
    def raw_credential_secret(self) -> str:
        return self._credential.raw_secret

    def __repr__(self) -> str:
        return (
            "ProcessingJobExecutionPrerequisites("
            f"job_id={self.job_id!r}, provider={self.provider!r}, credential_version_id={self.credential_version_id!r}, "
            f"verification_timestamp={self.verification_timestamp!r}, lease_generation={self.lease_generation!r}, "
            "raw_credential_secret=<redacted>, output_drive_folder_id=<redacted>)"
        )


@contextmanager
def open_processing_job_execution_prerequisites(
    db: Session,
    *,
    job_id: str,
    lease_owner_id: str,
    lease_generation: int,
    settings,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    credential_opener: Callable | None = None,
    output_verifier: Callable | None = None,
    **kwargs,
) -> Iterator[ProcessingJobExecutionPrerequisites]:
    clock = clock or (lambda: utcnow().replace(tzinfo=None))
    credential_opener = credential_opener or open_processing_job_provider_credential
    output_verifier = output_verifier or verify_processing_job_output_destination
    credential_kwargs = {key: value for key, value in kwargs.items() if key in {"master_key_resolver", "decryptor"}}
    output_kwargs = {key: value for key, value in kwargs.items() if key in {"token_resolver", "metadata_fetcher", "disk_resource_verifier"}}
    try:
        credential_cm = credential_opener(
            db,
            job_id=job_id,
            lease_owner_id=lease_owner_id,
            lease_generation=lease_generation,
            settings=settings,
            now=now,
            clock=clock,
            **credential_kwargs,
        )
        cred: ProcessingJobProviderCredential = credential_cm.__enter__()
    except ProviderCredentialAccessError as exc:
        raise JobExecutionContextError(JobExecutionContextReason.credential_unavailable) from exc

    exc_info = (None, None, None)
    try:
        try:
            output: ProcessingJobOutputDestination = output_verifier(
                db,
                job_id=job_id,
                lease_owner_id=lease_owner_id,
                lease_generation=lease_generation,
                settings=settings,
                now=now,
                clock=clock,
                **output_kwargs,
            )
        except OutputDestinationError as exc:
            raise JobExecutionContextError(JobExecutionContextReason.output_destination_unavailable) from exc
        _final_revalidate(db, job_id, lease_owner_id, lease_generation, settings, clock(), cred, output)
        yield _handle(job_id, lease_generation, cred, output, clock())
    except BaseException:
        exc_info = sys.exc_info()
        raise
    finally:
        credential_cm.__exit__(*exc_info)


def _final_revalidate(
    db: Session,
    job_id: str,
    lease_owner_id: str,
    lease_generation: int,
    settings,
    now: datetime,
    cred: ProcessingJobProviderCredential,
    output: ProcessingJobOutputDestination,
) -> None:
    try:
        credential_snapshot = _load_credential_snapshot(db, job_id, lease_owner_id, lease_generation, now, settings)
        output_snapshot = _load_output_snapshot(db, job_id, lease_owner_id, lease_generation, now)
    except ProviderCredentialAccessError as exc:
        raise JobExecutionContextError(JobExecutionContextReason.credential_unavailable) from exc
    except OutputDestinationError as exc:
        raise JobExecutionContextError(JobExecutionContextReason.output_destination_unavailable) from exc
    if (
        credential_snapshot.credential_id != cred.credential_id
        or credential_snapshot.version_id != cred.credential_version_id
        or credential_snapshot.credential_provider != cred.provider
    ):
        raise JobExecutionContextError(JobExecutionContextReason.credential_unavailable) from ProviderCredentialAccessError(
            ProviderCredentialAccessReason.credential_changed
        )
    if (output_snapshot.output_drive_folder_id != output.drive_folder_id
            or output_snapshot.output_provider != output.output_provider):
        raise JobExecutionContextError(JobExecutionContextReason.output_destination_unavailable) from OutputDestinationError(
            OutputDestinationReason.output_destination_changed
        )


def _handle(
    job_id: str,
    lease_generation: int,
    cred: ProcessingJobProviderCredential,
    output: ProcessingJobOutputDestination,
    verified_at: datetime,
) -> ProcessingJobExecutionPrerequisites:
    return ProcessingJobExecutionPrerequisites(
        job_id=job_id,
        provider=cred.provider,
        credential_version_id=cred.credential_version_id,
        _credential=cred,
        output_drive_folder_id=output.drive_folder_id,
        verification_timestamp=verified_at,
        lease_generation=lease_generation,
    )
