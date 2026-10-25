"""Resolve persisted Disk receipts without another transcription or overwrite."""
from sqlalchemy import select

from .job_output_reconciliation import (
    DriveReconciliationCandidate, OutputReconciliationCheckResult,
    OutputReconciliationError, OutputReconciliationReason,
    persist_verified_reconciliation_output,
)
from .models import JobStatus, OutputReconciliationStatus, Project, TranscriptionJob, TranscriptionOutputReconciliation
from .source_creation import parse_authoritative_source_created_at
from .transcript_docx import DOCX_MIME_TYPE
from .yandex_disk import YandexDiskClient, YandexDiskError, disk_web_url
from .yandex_disk_access import access_token, active_connection, register_resource, verify_selected_resource
from .yandex_docx_output import verify_document


def _snapshot(case):
    return (case.owner_user_id, case.project_id, case.job_id, case.job_source_id,
        case.expected_output_provider, case.expected_output_drive_folder_id,
        case.expected_docx_path, case.expected_document_sha256, case.expected_document_md5,
        case.expected_document_size_bytes, case.expected_document_character_count,
        case.reconciliation_token, case.lease_generation, case.status)


def _job_authority(db, owner_id, job_id, *, lock=False):
    statement = select(TranscriptionJob).where(TranscriptionJob.id == job_id)
    if lock:
        statement = statement.with_for_update()
    job = db.scalar(statement.execution_options(populate_existing=True))
    project = db.get(Project, job.project_id, populate_existing=True) if job else None
    if (job is None or job.owner_user_id != owner_id or job.output_provider != "yandex_disk"
            or job.status not in {JobStatus.failed, JobStatus.cancelled}
            or project is None or project.owner_user_id != owner_id or project.archived_at is not None):
        raise OutputReconciliationError(OutputReconciliationReason.not_allowed)
    return job


def check_yandex_output_reconciliation(db, *, owner_user_id, job_id, settings, now,
        resource_verifier=verify_selected_resource, token_resolver=access_token,
        client_factory=YandexDiskClient):
    job = _job_authority(db, owner_user_id, job_id)
    case_ids = list(db.scalars(select(TranscriptionOutputReconciliation.id).where(
        TranscriptionOutputReconciliation.job_id == job.id,
        TranscriptionOutputReconciliation.owner_user_id == owner_user_id,
        TranscriptionOutputReconciliation.expected_output_provider == "yandex_disk",
        TranscriptionOutputReconciliation.status.in_((OutputReconciliationStatus.prepared,
            OutputReconciliationStatus.creation_returned, OutputReconciliationStatus.reconciliation_required,
            OutputReconciliationStatus.conflict)),
    ).order_by(TranscriptionOutputReconciliation.id).limit(50)))
    checked = resolved = absent = conflicts = unavailable = 0
    for case_id in case_ids:
        case = db.get(TranscriptionOutputReconciliation, case_id, populate_existing=True)
        snapshot = _snapshot(case)
        checked += 1
        folder_id, path, sha, md5, size = snapshot[5:10]
        if (not path or not sha or not md5 or size is None or size <= 0
                or job.output_drive_folder_id != folder_id):
            unavailable += 1
            continue
        db.rollback()
        outcome, resource = "unavailable", None
        try:
            folder = resource_verifier(db, owner_user_id=owner_user_id,
                resource_id=folder_id, settings=settings, is_folder=True)
            if path.rpartition("/")[0] != folder.path.rstrip("/"):
                raise YandexDiskError("document_conflict")
            token = token_resolver(db, user_id=owner_user_id, settings=settings)
            connection = active_connection(db, owner_user_id=owner_user_id)
            connection_identity = (connection.account_uid, connection.credential_revision)
            db.rollback()
            client = client_factory(token)
            try:
                resource = client.metadata(path)
            except YandexDiskError as error:
                if error.reason != "not_found":
                    raise
            if resource is not None:
                verify_document(client, resource, path=path, size_bytes=size, sha256=sha, md5=md5)
                outcome = "found"
            else:
                outcome = "absent"
            resource_verifier(db, owner_user_id=owner_user_id,
                resource_id=folder_id, settings=settings, is_folder=True)
            connection = active_connection(db, owner_user_id=owner_user_id)
            if (connection.account_uid, connection.credential_revision) != connection_identity:
                raise YandexDiskError("connection_changed")
        except YandexDiskError as error:
            outcome = "conflict" if error.reason == "document_conflict" else "unavailable"
        # Close all I/O transactions before the final serialized write decision.
        db.rollback()
        current_job = _job_authority(db, owner_user_id, job_id, lock=True)
        case = db.get(TranscriptionOutputReconciliation, case_id,
            populate_existing=True, with_for_update=True)
        if (case is None or _snapshot(case) != snapshot
                or current_job.output_drive_folder_id != folder_id):
            raise OutputReconciliationError(OutputReconciliationReason.conflict)
        case.last_checked_at = case.updated_at = now
        if outcome == "found":
            handle = register_resource(db, owner_user_id=owner_user_id, resource=resource,
                expected_connection=connection_identity)
            candidate = DriveReconciliationCandidate(handle.id, DOCX_MIME_TYPE, disk_web_url(path),
                (folder_id,), parse_authoritative_source_created_at(resource.created) or now, {})
            persist_verified_reconciliation_output(db, case=case, candidate=candidate, now=now)
            resolved += 1
        elif outcome == "absent":
            connection = active_connection(db, owner_user_id=owner_user_id, lock=True)
            if (connection.account_uid, connection.credential_revision) != connection_identity:
                raise OutputReconciliationError(OutputReconciliationReason.conflict)
            # Resolve only the uncertainty, not the job. A standard explicit
            # retry must still prove a full cached provider result before export.
            case.status = OutputReconciliationStatus.resolved
            case.uncertainty_reason = "yandex_output_absent"
            case.resolved_at = now
            case.resolved_output_id = None
            case.returned_document_id = case.returned_web_view_url = None
            case.returned_document_created_at = None
            absent += 1
        elif outcome == "conflict":
            case.status = OutputReconciliationStatus.conflict
            case.uncertainty_reason = "yandex_disk_document_conflict"
            conflicts += 1
        else:
            unavailable += 1
        db.commit()
        # Resolving the last required output can complete the job.
        if current_job.status == JobStatus.completed:
            break
    return OutputReconciliationCheckResult(checked, resolved, absent, conflicts, unavailable)
