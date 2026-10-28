"""Disk output through the same source, lease and provenance guards as Docs."""
from contextlib import contextmanager

from .google_docs_output import GoogleDocsCreateResult, new_google_docs_transcript_artifact
from .job_google_docs_output import (
    JobGoogleDocsOutputError, JobGoogleDocsOutputReason,
    _compare_or_after, _compare_or_before, _compare_source_or_after,
    _compare_source_or_before, _load_output_job_snapshot, _load_source_snapshot,
    _require_no_persisted_output, _source_provenance_snapshot, format_job_transcript,
)
from .job_output_reconciliation import (
    OutputReconciliationError, OutputReconciliationReason,
    mark_reconciliation_creation_returned, prepare_output_reconciliation_case,
)
from .transcript_docx import DOCX_MIME_TYPE, DOCX_OUTPUT_KIND
from .yandex_disk import YandexDiskClient, YandexDiskError, disk_web_url
from .yandex_disk_access import (
    access_token, active_connection, register_resource, verify_selected_resource,
)
from .yandex_docx_output import bind_document_receipt, ensure_document, prepare_document_upload


def output_error(error):
    suffix = {
        "quota_exceeded": "quota_exceeded", "document_conflict": "document_conflict",
        "conflict": "document_conflict", "permission_denied": "permission_denied",
        "authentication_rejected": "access_expired",
        "reauthorization_required": "access_expired",
    }.get(error.reason, "unavailable")
    return JobGoogleDocsOutputError(JobGoogleDocsOutputReason("yandex_disk_" + suffix))


@contextmanager
def create_processing_job_yandex_docx(db, *, job_id, job_source_id, lease_owner_id,
        lease_generation, transcript, settings, now, clock,
        resource_verifier=verify_selected_resource, token_resolver=access_token,
        client_factory=YandexDiskClient):
    artifact = None
    snap = _load_output_job_snapshot(db, job_id, lease_owner_id, lease_generation, now)
    if snap.output_provider != "yandex_disk":
        raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.output_folder_unavailable)
    source = _load_source_snapshot(db, job_id, job_source_id, lease_owner_id, lease_generation, now, settings)
    _require_no_persisted_output(db, job_source_id)
    from .work_progress import report_work
    report_work("document_output")
    try:
        folder = resource_verifier(db, owner_user_id=snap.owner_user_id,
            resource_id=snap.output_drive_folder_id, settings=settings, is_folder=True)
        token = token_resolver(db, user_id=snap.owner_user_id, settings=settings)
        connection = active_connection(db, owner_user_id=snap.owner_user_id)
        connection_identity = (connection.account_uid, connection.credential_revision)
        formatted, provenance = format_job_transcript(db, snap, source, transcript)
        def guard(*, after=False):
            current = _load_output_job_snapshot(db, job_id, lease_owner_id, lease_generation, clock())
            (_compare_or_after if after else _compare_or_before)(current, snap)
            current_source = _load_source_snapshot(db, job_id, job_source_id,
                lease_owner_id, lease_generation, clock(), settings)
            (_compare_source_or_after if after else _compare_source_or_before)(current_source, source)
            if _source_provenance_snapshot(db, source) != provenance:
                raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.selected_source_changed)
            connection = active_connection(db, owner_user_id=snap.owner_user_id)
            if (connection.account_uid, connection.credential_revision) != connection_identity:
                raise YandexDiskError("connection_changed")
            db.rollback()
        guard()
        try:
            case = prepare_output_reconciliation_case(db, job_id=job_id, job_source_id=job_source_id,
                lease_owner_id=lease_owner_id, lease_generation=lease_generation,
                document_title=formatted.title, character_count=len(formatted.body), now=clock())
        except OutputReconciliationError as error:
            db.rollback()
            reason = (JobGoogleDocsOutputReason.existing_reconciliation_case
                      if error.reason == OutputReconciliationReason.existing_reconciliation_case
                      else JobGoogleDocsOutputReason.output_reconciliation_conflict)
            raise JobGoogleDocsOutputError(reason) from error
        upload = prepare_document_upload(folder_path=folder.path, title=formatted.title,
            document_text=formatted.body, reconciliation_token=case.reconciliation_token)
        bind_document_receipt(case, upload)
        try:
            db.commit()  # Receipt authority must precede any external creation.
        except Exception:
            db.rollback()
            raise JobGoogleDocsOutputError(JobGoogleDocsOutputReason.reconciliation_case_persistence_failed) from None
        resource = ensure_document(client_factory(token), upload, check=guard)
        guard(after=True)
        handle = register_resource(db, owner_user_id=snap.owner_user_id, resource=resource,
            expected_connection=connection_identity)
        result = GoogleDocsCreateResult(handle.id, resource.name, DOCX_MIME_TYPE,
            disk_web_url(resource.path), (snap.output_drive_folder_id,))
        mark_reconciliation_creation_returned(db, job_source_id=job_source_id,
            document_id=result.document_id, web_view_url=result.web_view_link,
            document_created_at=clock(), now=clock())
        db.commit()
        artifact = new_google_docs_transcript_artifact(result=result, created_at=clock(),
            character_count=len(formatted.body), output_provider="yandex_disk", output_kind=DOCX_OUTPUT_KIND)
        yield artifact
    except YandexDiskError as error:
        raise output_error(error) from error
    finally:
        if artifact is not None:
            artifact.revoke()
