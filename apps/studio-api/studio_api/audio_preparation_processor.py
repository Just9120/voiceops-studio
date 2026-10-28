from __future__ import annotations

from dataclasses import dataclass, replace
import math
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

from sqlalchemy.orm import Session

from .audio_preparation import (
    AudioPreparationError,
    AudioPreparationReason,
    AudioProbe,
    build_preview,
    estimate_trimmed_duration,
    probe_media,
)
from .audio_preparation_service import (
    AudioPreparationServiceError,
    AudioPreparationServiceReason,
    complete_audio_preview,
    complete_audio_drive_export,
    deserialize_options,
    fail_audio_preparation_job,
    finalize_cancelled_audio_preparation_job,
)
from .audio_result_rendering import materialize_audio_inputs as _materialize_inputs, render_audio_result
from .audio_analysis import analyze_audio_visual, visual_payload, MAX_WAVEFORM_POINTS
from .work_progress import measured_work, report_work
from .google_connection_access import refresh_user_google_drive_access_token
from .google_drive import fetch_drive_file_content
from .google_drive_upload import upload_file_resumable
from .diagnostics import write_diagnostic_event
from .models import (
    AudioPreparationJob,
    AudioPreparationStatus,
    Project,
    Source,
    SourceType,
    SourceUploadStatus,
)
from .security import utcnow
from .source_policy import is_source_expired
from .source_storage import (
    get_source_storage,
    reference_storage_bucket,
    reference_storage_isolation_configured,
    reference_storage_settings,
    source_reference_class,
)


_COPY_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class AudioProcessingResult:
    job_id: str
    status: str
    stage: str
    output_created: bool


def process_claimed_audio_preparation_job(
    db: Session,
    *,
    job_id: str,
    lease_owner_id: str,
    lease_generation: int,
    settings,
    now: datetime | None = None,
    storage_factory: Callable = get_source_storage,
    drive_token_resolver: Callable = refresh_user_google_drive_access_token,
    drive_content_fetcher: Callable = fetch_drive_file_content,
    drive_uploader: Callable = upload_file_resumable,
    runner: Callable | None = None,
    temp_directory_factory: Callable = TemporaryDirectory,
) -> AudioProcessingResult:
    operation_now = now or utcnow()
    job = _load_claimed_job(db, job_id, lease_owner_id, lease_generation)
    download_request_id = job.download_request_id if job.current_stage == "audio_download_rendering" else None
    try:
        with measured_work(db, job=job, owner=lease_owner_id, generation=lease_generation, clock=utcnow), temp_directory_factory(prefix="studio-audio-preparation-") as temp_dir:
            root = Path(temp_dir)
            if job.status in {AudioPreparationStatus.completed, AudioPreparationStatus.preview_ready}:
                if job.current_stage == "audio_download_rendering":
                    from .audio_downloads import create_worker_download_directory, mark_worker_download_ready
                    delivery_root = Path(settings.audio_delivery_directory)
                    request_id = job.download_request_id
                    output_root = create_worker_download_directory(job, delivery_root)
                    def check_download():
                        db.refresh(job)
                        if (job.lease_owner_id != lease_owner_id or job.lease_generation != lease_generation
                            or job.current_stage != "audio_download_rendering" or job.download_request_id != request_id
                            or not job.lease_expires_at or _naive_utc(job.lease_expires_at) <= _naive_utc(utcnow())
                            or not job.download_expires_at or _naive_utc(job.download_expires_at) <= _naive_utc(utcnow())):
                            raise AudioPreparationServiceError(AudioPreparationServiceReason.lease_unavailable)
                        if job.cancel_requested_at:
                            raise AudioPreparationServiceError(AudioPreparationServiceReason.cancellation_requested)
                    check_download()
                    result = render_audio_result(db, job=job, root=root, output_root=output_root,
                        settings=settings, storage_factory=storage_factory,
                        drive_token_resolver=drive_token_resolver, drive_content_fetcher=drive_content_fetcher,
                        runner=runner, check=check_download, clock=utcnow, preview=job.download_preview,
                        progress=lambda ratio: _checkpoint(db, job, "audio_download_rendering", max(job.progress_percent, min(99, 10 + round(max(0, min(1, ratio)) * 89)))))
                    check_download()
                    mark_worker_download_ready(db, job=job, result=result, root=delivery_root, now=utcnow(),
                        owner=lease_owner_id, generation=lease_generation, request_id=request_id)
                    db.commit()
                    return AudioProcessingResult(job.id, job.status.value, "audio_download_ready", False)
                return _export_existing_output(db, job=job, root=root, settings=settings, storage_factory=storage_factory, drive_token_resolver=drive_token_resolver, drive_uploader=drive_uploader, lease_owner_id=lease_owner_id, lease_generation=lease_generation, runner=runner, drive_content_fetcher=drive_content_fetcher)
            paths = _materialize_inputs(
                db,
                job=job,
                root=root,
                settings=settings,
                storage_factory=storage_factory,
                drive_token_resolver=drive_token_resolver,
                drive_content_fetcher=drive_content_fetcher, check=lambda: _require_not_cancelled(db, job), clock=utcnow,
            )
            options = deserialize_options(job)
            probes: list[AudioProbe] = []
            analyses = []
            is_preview = job.status is AudioPreparationStatus.analyzing
            if is_preview:
                _checkpoint(db, job, "analyzing", 10)
            else:
                _checkpoint(db, job, "materializing", 10)
            for path in paths:
                _require_not_cancelled(db, job)
                report_work("media_probe", len(probes), len(paths), "files")
                probes.append(probe_media(path, runner=runner) if runner else probe_media(path))
            preview = build_preview(probes, (), options)
            remaining_points, remaining_duration = MAX_WAVEFORM_POINTS, preview.input_duration_seconds
            for index, path in enumerate(paths):
                if is_preview:
                    points = max(1, min(remaining_points - (len(paths) - index - 1),
                        math.floor(remaining_points * probes[index].duration_seconds / remaining_duration)))
                    analysis = analyze_audio_visual(path, duration=probes[index].duration_seconds, channels=probes[index].channels, sample_rate=probes[index].sample_rate, options=options,
                        points=points,
                        progress=lambda seconds: report_work("media_analysis", sum(p.duration_seconds for p in probes[:index]) + seconds, preview.input_duration_seconds, "seconds"),
                        speech_progress=lambda seconds: report_work("speech_analysis", sum(p.duration_seconds for p in probes[:index]) + seconds, preview.input_duration_seconds, "seconds"),
                        runner=runner, check=lambda: _require_not_cancelled(db, job))
                    analyses.append(analysis)
                    remaining_points -= points
                    remaining_duration = max(0.001, remaining_duration - probes[index].duration_seconds)
                if is_preview:
                    _checkpoint(db, job, "analyzing", 10 + round(((index + 1) / len(paths)) * 80))
            if is_preview:
                visual = visual_payload(analyses, [probe.duration_seconds for probe in probes], options.silence_keep_duration_seconds)
                estimate = (estimate_trimmed_duration(options, preview.input_duration_seconds, visual)
                    if options.trim_start_seconds or options.trim_end_seconds is not None
                    else max(0.0, preview.input_duration_seconds - sum(item.removed_seconds for item in analyses)))
                preview = replace(preview, estimated_output_duration_seconds=estimate)
            if job.status is AudioPreparationStatus.analyzing:
                complete_audio_preview(
                    db,
                    job_id=job.id,
                    lease_owner_id=lease_owner_id,
                    lease_generation=lease_generation,
                    total_input_duration_ms=round(preview.input_duration_seconds * 1000),
                    estimated_output_duration_ms=round(preview.estimated_output_duration_seconds * 1000),
                    copy_compatible=preview.copy_compatible,
                    visual_analysis=visual_payload(analyses, [probe.duration_seconds for probe in probes], options.silence_keep_duration_seconds),
                )
                db.commit()
                return AudioProcessingResult(job.id, "preview_ready", "preview_ready", False)
            if job.status is not AudioPreparationStatus.processing:
                raise AudioPreparationServiceError(AudioPreparationServiceReason.invalid_state)
            _require_not_cancelled(db, job)
            _checkpoint(db, job, "processing", 20)
            def report_processing_progress(ratio: float) -> None:
                report_work("audio_processing", max(0.0, min(1.0, ratio)) * preview.estimated_output_duration_seconds, preview.estimated_output_duration_seconds, "seconds")
                percent = min(80, 20 + round(max(0.0, min(1.0, ratio)) * 60))
                if percent > job.progress_percent:
                    _checkpoint(db, job, "processing", percent)

            rendered = render_audio_result(db, job=job, root=root, settings=settings,
                paths=paths, probes=probes, runner=runner, clock=utcnow,
                check=lambda: _require_not_cancelled(db, job), progress=report_processing_progress)
            output_path, output_filename, mime_type = rendered.path, rendered.filename, rendered.mime_type
            # Persist parameters and safe result metadata before optional export.
            # A later download/export regenerates bytes from retained inputs.
            _require_not_cancelled(db, job)
            job.output_source_id = None
            job.output_filename = output_filename
            job.output_mime_type = mime_type
            job.output_size_bytes = rendered.size_bytes
            job.output_duration_ms = rendered.duration_ms
            job.status = AudioPreparationStatus.completed
            job.current_stage = "google_drive_upload" if job.output_destination == "google_drive" else "completed"
            job.progress_percent = 92 if job.output_destination == "google_drive" else 100
            job.finished_at = _naive_utc(operation_now)
            db.flush()
            db.commit()
            if job.output_destination == "google_drive":
                token = drive_token_resolver(db, user_id=job.owner_user_id, settings=settings)
                uploaded = _upload_ready_output(db, job, drive_uploader, token, output_path, output_filename, mime_type, lease_owner_id, lease_generation, start_percent=92)
                complete_audio_drive_export(db, job_id=job.id, lease_owner_id=lease_owner_id,
                    lease_generation=lease_generation, file_id=uploaded.file_id, web_view_url=uploaded.web_view_url)
                db.commit()
                return AudioProcessingResult(job.id, "completed", "completed", True)
            job.status = AudioPreparationStatus.completed
            job.current_stage = "completed"
            job.progress_percent = 100
            job.finished_at = _naive_utc(operation_now)
            job.lease_owner_id = None
            job.lease_expires_at = None
            # Device sources retain their separately selected 3/7/30-day deadline;
            # the request-scoped directory removes FFmpeg files and partial bytes.
            db.flush()
            db.commit()
            return AudioProcessingResult(job.id, "completed", "completed", True)
    except (AudioPreparationError, AudioPreparationServiceError) as exc:
        failure_stage = job.current_stage
        db.rollback()
        reason = getattr(getattr(exc, "reason", None), "value", "processing_failed")
        try:
            _discard_claimed_download(db, job_id, lease_owner_id, lease_generation, download_request_id, settings)
            if reason == AudioPreparationServiceReason.cancellation_requested.value:
                finalize_cancelled_audio_preparation_job(
                    db,
                    job_id=job_id,
                    lease_owner_id=lease_owner_id,
                    lease_generation=lease_generation,
                    now=utcnow(),
                )
            else:
                fail_audio_preparation_job(
                    db,
                    job_id=job_id,
                    lease_owner_id=lease_owner_id,
                    lease_generation=lease_generation,
                    error_code=reason,
                    now=utcnow(),
                )
            failed_job = db.get(AudioPreparationJob, job_id)
            db.commit()
            _record_failure_diagnostic(failed_job, reason, failure_stage, exc)
        except Exception:
            db.rollback()
        raise
    except Exception as exc:
        failure_stage = job.current_stage
        db.rollback()
        try:
            _discard_claimed_download(db, job_id, lease_owner_id, lease_generation, download_request_id, settings)
            fail_audio_preparation_job(
                db,
                job_id=job_id,
                lease_owner_id=lease_owner_id,
                lease_generation=lease_generation,
                error_code="processing_failed",
                now=operation_now,
            )
            failed_job = db.get(AudioPreparationJob, job_id)
            db.commit()
            _record_failure_diagnostic(failed_job, "processing_failed", failure_stage)
        except Exception:
            db.rollback()
        raise AudioPreparationError(AudioPreparationReason.processing_failed) from exc
    finally:
        if download_request_id:
            from .audio_downloads import remove_worker_download_attempt
            remove_worker_download_attempt(Path(settings.audio_delivery_directory), download_request_id, lease_generation)


def _discard_claimed_download(db, job_id, owner, generation, request_id, settings):
    if not request_id:
        return
    from sqlalchemy import select
    from .audio_downloads import remove_download_directory
    current = db.execute(select(AudioPreparationJob.id).where(
        AudioPreparationJob.id == job_id, AudioPreparationJob.lease_owner_id == owner,
        AudioPreparationJob.lease_generation == generation,
        AudioPreparationJob.download_request_id == request_id,
    ).with_for_update()).scalar_one_or_none()
    if current:
        remove_download_directory(Path(settings.audio_delivery_directory), request_id)


def _load_claimed_job(db, job_id, owner, generation) -> AudioPreparationJob:
    job = db.get(AudioPreparationJob, job_id)
    if job is None:
        raise AudioPreparationServiceError(AudioPreparationServiceReason.not_found)
    if job.lease_owner_id != owner or job.lease_generation != generation:
        raise AudioPreparationServiceError(AudioPreparationServiceReason.lease_unavailable)
    if job.status not in {AudioPreparationStatus.analyzing, AudioPreparationStatus.processing} and not ((job.status is AudioPreparationStatus.completed and job.current_stage == "google_drive_upload") or (job.status in {AudioPreparationStatus.completed, AudioPreparationStatus.preview_ready} and job.current_stage == "audio_download_rendering")):
        raise AudioPreparationServiceError(AudioPreparationServiceReason.invalid_state)
    job._processing_lease = (owner, generation)
    return job


def _export_existing_output(db, *, job, root, settings, storage_factory, drive_token_resolver, drive_uploader, lease_owner_id, lease_generation, runner=None, drive_content_fetcher=fetch_drive_file_content):
    def check_export_lease():
        db.refresh(job)
        if (job.lease_owner_id != lease_owner_id or job.lease_generation != lease_generation
            or job.current_stage != "google_drive_upload" or job.lease_expires_at is None
            or _naive_utc(job.lease_expires_at) <= _naive_utc(utcnow())):
            raise AudioPreparationServiceError(AudioPreparationServiceReason.lease_unavailable)
        _require_not_cancelled(db, job)

    check_export_lease()
    if not job.output_source_id:
        if not job.output_filename:
            raise AudioPreparationServiceError(AudioPreparationServiceReason.source_unavailable)
        rendered = render_audio_result(db, job=job, root=root, settings=settings,
            storage_factory=storage_factory, drive_token_resolver=drive_token_resolver,
            drive_content_fetcher=drive_content_fetcher, runner=runner, clock=utcnow,
            check=check_export_lease,
            progress=lambda ratio: _checkpoint(db, job, "google_drive_upload", max(job.progress_percent, 10 + round(max(0.0, min(1.0, ratio)) * 50))))
        check_export_lease()
        token = drive_token_resolver(db, user_id=job.owner_user_id, settings=settings)
        uploaded = _upload_ready_output(db, job, drive_uploader, token, rendered.path,
            rendered.filename, rendered.mime_type, lease_owner_id, lease_generation, start_percent=60)
        complete_audio_drive_export(db, job_id=job.id, lease_owner_id=lease_owner_id,
            lease_generation=lease_generation, file_id=uploaded.file_id, web_view_url=uploaded.web_view_url)
        db.commit()
        return AudioProcessingResult(job.id, "completed", "completed", False)
    # Legacy stored outputs retain their existing compatibility path.
    # Do not access original inputs: ephemeral originals may already be deleted.
    project = db.get(Project, job.project_id)
    source = db.get(Source, job.output_source_id)
    if (project is None or project.owner_user_id != job.owner_user_id or project.archived_at is not None
        or source is None or source.project_id != job.project_id or source.deleted_at is not None
        or source.upload_status is not SourceUploadStatus.uploaded or is_source_expired(source.expires_at, utcnow())
        or source.source_type is not SourceType.local_upload or not source.s3_object_key):
        raise AudioPreparationServiceError(AudioPreparationServiceReason.source_unavailable)
    reference_class = source_reference_class(source)
    if not reference_storage_isolation_configured(settings) or source.s3_bucket != reference_storage_bucket(settings, reference_class):
        raise AudioPreparationServiceError(AudioPreparationServiceReason.source_unavailable)
    _checkpoint(db, job, "google_drive_upload", 10)
    path = root / "ready-output"
    stream = storage_factory(reference_storage_settings(settings, reference_class)).open_read(source.s3_object_key)
    size = 0
    try:
        with path.open("wb") as target:
            for chunk in stream.iter_chunks(_COPY_CHUNK_SIZE):
                check_export_lease()
                size += len(chunk)
                if size > getattr(settings, "audio_preparation_max_output_bytes", settings.source_max_upload_bytes):
                    raise AudioPreparationError(AudioPreparationReason.output_too_large)
                target.write(chunk)
    finally:
        stream.close()
    if size <= 0 or (source.size_bytes is not None and size != source.size_bytes):
        raise AudioPreparationServiceError(AudioPreparationServiceReason.source_unavailable)
    _checkpoint(db, job, "google_drive_upload", 40)
    token = drive_token_resolver(db, user_id=job.owner_user_id, settings=settings)
    check_export_lease()
    uploaded = _upload_ready_output(db, job, drive_uploader, token, path, source.original_filename, source.mime_type, lease_owner_id, lease_generation, start_percent=40)
    complete_audio_drive_export(db, job_id=job.id, lease_owner_id=lease_owner_id,
        lease_generation=lease_generation, file_id=uploaded.file_id, web_view_url=uploaded.web_view_url)
    db.commit()
    return AudioProcessingResult(job.id, "completed", "completed", False)


def _upload_ready_output(db, job, uploader, token, path, filename, mime_type, owner, generation, *, start_percent):
    def check():
        db.refresh(job)
        if (job.lease_owner_id != owner or job.lease_generation != generation
            or job.status is not AudioPreparationStatus.completed or job.current_stage != "google_drive_upload"
            or job.lease_expires_at is None or _naive_utc(job.lease_expires_at) <= _naive_utc(utcnow())):
            raise AudioPreparationServiceError(AudioPreparationServiceReason.lease_unavailable)
        _require_not_cancelled(db, job)

    def progress(sent, total):
        check()
        percent = min(99, start_percent + round((99 - start_percent) * sent / total))
        if percent > job.progress_percent:
            job.progress_percent = percent
            db.commit()

    check()
    return uploader(token, folder_id=job.output_drive_folder_id, path=path,
        filename=filename, mime_type=mime_type, idempotency_key=job.id,
        check_cancelled=check, progress_callback=progress)


def _require_not_cancelled(db, job):
    from .worker_progress import touch_worker_progress
    touch_worker_progress()
    owner, generation = getattr(job, "_processing_lease", (job.lease_owner_id, job.lease_generation))
    db.refresh(job)
    if job.lease_owner_id != owner or job.lease_generation != generation:
        raise AudioPreparationServiceError(AudioPreparationServiceReason.lease_unavailable)
    if job.lease_expires_at is None or _naive_utc(job.lease_expires_at) <= _naive_utc(utcnow()):
        raise AudioPreparationServiceError(AudioPreparationServiceReason.lease_unavailable)
    db_status = job.cancel_requested_at
    if db_status is not None:
        raise AudioPreparationServiceError(AudioPreparationServiceReason.cancellation_requested)


def _checkpoint(db, job, stage, percent):
    _require_not_cancelled(db, job)
    job.current_stage = stage
    job.progress_percent = percent
    db.commit()


def _record_failure_diagnostic(job, reason, stage, error=None):
    if job is None:
        return
    metadata = {
        "error_code": reason if reason in {item.value for item in AudioPreparationReason} else "processing_failed",
        "stage": stage if stage in {"analyzing", "materializing", "processing", "storing", "google_drive_upload", "audio_download_rendering", "failed"} else "failed",
        "input_count": len(job.inputs),
    }
    if isinstance(error, AudioPreparationError):
        if error.ffmpeg_exit_code is not None:
            metadata["ffmpeg_exit_code"] = error.ffmpeg_exit_code
        if error.ffmpeg_failure_category is not None:
            metadata["ffmpeg_failure_category"] = error.ffmpeg_failure_category
    write_diagnostic_event(
        owner_user_id=job.owner_user_id,
        component="worker",
        event_code="AUDIO_PREPARATION_FAILED",
        project_id=job.project_id,
        job_id=job.id,
        metadata=metadata,
    )


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)
