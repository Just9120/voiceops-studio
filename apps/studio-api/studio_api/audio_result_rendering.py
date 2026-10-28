"""Request-scoped materialization/rendering used by the separate media worker."""
from __future__ import annotations

import shutil
import json
import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from .audio_preparation import AudioOutputFormat, AudioPreparationError, AudioPreparationReason, build_ffmpeg_command, probe_media, render_output_filename, run_processing
from .audio_preparation_service import AudioPreparationServiceError, AudioPreparationServiceReason, deserialize_options
from .google_connection_access import refresh_user_google_drive_access_token
from .google_drive import fetch_drive_file_content
from .models import Project, SourceType, SourceUploadStatus
from .security import utcnow
from .work_progress import report_work
from .source_policy import is_source_expired, is_supported_source_mime_type
from .source_storage import SourceObjectReadError, get_source_storage, reference_storage_bucket, reference_storage_isolation_configured, reference_storage_settings, safe_filename, source_reference_class

_COPY_CHUNK_SIZE = 1024 * 1024
_SCRATCH_RESERVE_BYTES = 64 * 1024 * 1024

def materialize_audio_inputs(
    db,
    *,
    job,
    root,
    settings,
    storage_factory,
    drive_token_resolver,
    drive_content_fetcher,
    check=lambda: None,
    clock=utcnow,
) -> list[Path]:
    project = db.get(Project, job.project_id)
    if project is None or project.owner_user_id != job.owner_user_id or project.archived_at is not None:
        raise AudioPreparationServiceError(AudioPreparationServiceReason.project_unavailable)
    token_cache: dict[str, str] = {}
    paths = []
    total_copied = 0
    total_bytes = sum(max(0, item.source.size_bytes or 0) for item in job.inputs if item.source)
    report_work("source_download", 0, total_bytes or None, "bytes")
    budget = min(
        getattr(settings, "audio_preparation_max_input_bytes", 1024**3),
        getattr(settings, "audio_preparation_max_scratch_bytes", 3 * 1024**3) - _SCRATCH_RESERVE_BYTES,
        shutil.disk_usage(root).free - _SCRATCH_RESERVE_BYTES,
    )
    if sum(max(0, item.source.size_bytes or 0) for item in job.inputs if item.source) > budget:
        raise AudioPreparationServiceError(AudioPreparationServiceReason.input_too_large)
    for item in job.inputs:
        check()
        source = item.source
        if (
            source is None
            or source.project_id != job.project_id
            or source.upload_status is not SourceUploadStatus.uploaded
            or source.deleted_at is not None
            or is_source_expired(source.expires_at, clock())
            or not is_supported_source_mime_type(source.mime_type)
        ):
            raise AudioPreparationServiceError(AudioPreparationServiceReason.source_unavailable)
        extension = safe_filename(source.original_filename).rsplit(".", 1)[-1].lower()
        if not extension or len(extension) > 12:
            extension = "media"
        path = root / f"input-{item.position:03d}.{extension}"
        if source.source_type is SourceType.local_upload:
            reference_class = source_reference_class(source)
            if (
                not reference_storage_isolation_configured(settings)
                or source.s3_bucket
                != reference_storage_bucket(settings, reference_class)
                or not source.s3_object_key
            ):
                raise AudioPreparationServiceError(AudioPreparationServiceReason.source_unavailable)
            try:
                stream = storage_factory(
                    reference_storage_settings(settings, reference_class)
                ).open_read(source.s3_object_key)
            except SourceObjectReadError as exc:
                raise AudioPreparationServiceError(AudioPreparationServiceReason.source_unavailable) from exc
        elif source.source_type is SourceType.yandex_disk and source.drive_file_id:
            from .yandex_disk import YandexDiskClient, YandexDiskError
            from .yandex_disk_access import access_token, verify_selected_resource
            owner_id, handle = job.owner_user_id, source.drive_file_id
            try:
                resource = verify_selected_resource(db, owner_user_id=owner_id,
                    resource_id=handle, settings=settings, is_folder=False)
                token = access_token(db, user_id=owner_id, settings=settings)
                db.rollback()
                def disk_check():
                    check()
                    if shutil.disk_usage(root).free < _SCRATCH_RESERVE_BYTES:
                        raise AudioPreparationServiceError(AudioPreparationServiceReason.input_too_large)
                with path.open("wb") as target:
                    copied = YandexDiskClient(token).download_to(resource, target,
                        maximum_bytes=min(settings.source_max_upload_bytes, max(0, budget-total_copied)),
                        check=disk_check)
                verify_selected_resource(db, owner_user_id=owner_id,
                    resource_id=handle, settings=settings, is_folder=False)
                db.rollback()
            except YandexDiskError as exc:
                raise AudioPreparationServiceError(AudioPreparationServiceReason.source_unavailable) from exc
            if copied <= 0:
                raise AudioPreparationServiceError(AudioPreparationServiceReason.source_unavailable)
            total_copied += copied
            paths.append(path)
            continue
        elif source.source_type is SourceType.google_drive and source.drive_file_id:
            if "token" not in token_cache:
                token_cache["token"] = drive_token_resolver(db, user_id=job.owner_user_id, settings=settings)
            stream = drive_content_fetcher(token_cache["token"], source.drive_file_id)
        else:
            raise AudioPreparationServiceError(AudioPreparationServiceReason.source_unavailable)
        copied = 0
        try:
            with path.open("wb") as target:
                for chunk in stream.iter_chunks(_COPY_CHUNK_SIZE):
                    check()
                    if not chunk:
                        continue
                    copied += len(chunk)
                    total_copied += len(chunk)
                    if total_copied > budget or shutil.disk_usage(root).free - len(chunk) < _SCRATCH_RESERVE_BYTES:
                        raise AudioPreparationServiceError(AudioPreparationServiceReason.input_too_large)
                    if copied > settings.source_max_upload_bytes:
                        raise AudioPreparationServiceError(AudioPreparationServiceReason.source_unavailable)
                    target.write(chunk)
                    report_work("source_download", total_copied, total_bytes or None, "bytes")
        finally:
            stream.close()
        if copied <= 0 or (source.size_bytes is not None and copied != source.size_bytes):
            raise AudioPreparationServiceError(AudioPreparationServiceReason.source_unavailable)
        paths.append(path)
    return paths



@dataclass(frozen=True)
class RenderedAudio:
    path: Path
    filename: str
    mime_type: str
    size_bytes: int
    duration_ms: int


def render_audio_result(db, *, job, root, settings, output_root=None, paths=None, probes=None,
                        storage_factory=get_source_storage,
                        drive_token_resolver=refresh_user_google_drive_access_token,
                        drive_content_fetcher=fetch_drive_file_content,
                        runner=None, check=lambda: None, progress=lambda ratio: None, clock=utcnow, preview=False):
    """Render into the caller's temporary directory; never persist finished bytes."""
    check()
    if paths is None:
        paths = materialize_audio_inputs(db, job=job, root=root, settings=settings,
            storage_factory=storage_factory, drive_token_resolver=drive_token_resolver,
            drive_content_fetcher=drive_content_fetcher, check=check, clock=clock)
    if probes is None:
        probes = []
        for path in paths:
            check()
            probes.append(probe_media(path, runner=runner) if runner else probe_media(path))
    # All originals remain in scratch even when the sample selects one input.
    input_bytes = sum(path.stat().st_size for path in paths)
    options = deserialize_options(job)
    preview_start = 0.0
    if preview:
        options = replace(options, output_format=AudioOutputFormat.wav)
    if preview and options.trim_start_seconds == 0 and options.trim_end_seconds is None:
        position = 0
        if job.visual_analysis_json:
            for source in json.loads(job.visual_analysis_json).get("sources", []):
                pauses = source.get("silences", [])
                if pauses:
                    position = source["position"]
                    preview_start = max(0.0, pauses[0]["start"] - 5)
                    break
        if (not isinstance(position, int) or position < 0 or position >= len(paths)
            or not math.isfinite(preview_start) or preview_start >= probes[position].duration_seconds):
            raise AudioPreparationServiceError(AudioPreparationServiceReason.invalid_state)
        paths, probes = [paths[position]], [probes[position]]
    creation_time = _earliest_creation_time(job)
    extension = _output_extension(job, options, paths)
    output_root = output_root or root
    output_path = output_root / f"processed-output.{extension}"
    concat_path = None
    if options.output_format is AudioOutputFormat.copy:
        concat_path = root / "concat-inputs.txt"
        concat_path.write_text(
            "".join(f"file '{path.name}'\n" for path in paths),
            encoding="utf-8",
        )
    command = build_ffmpeg_command(
        paths,
        output_path,
        options,
        probes,
        concat_list_path=concat_path,
        creation_time=creation_time,
    )
    output_budget = min(
        getattr(settings, "audio_preparation_max_output_bytes", settings.source_max_upload_bytes),
        getattr(settings, "audio_preparation_max_scratch_bytes", 3 * 1024**3) - input_bytes - _SCRATCH_RESERVE_BYTES,
        shutil.disk_usage(output_root).free - _SCRATCH_RESERVE_BYTES,
    )
    if output_budget <= 0:
        raise AudioPreparationError(AudioPreparationReason.output_too_large)
    # FFmpeg limits the file while writing, rather than after exhausting tmpfs.
    command[1:1] = ["-filter_threads", "2", "-filter_complex_threads", "2"]
    command[-1:-1] = ["-threads", "2", "-fs", str(output_budget)]
    if preview and options.trim_start_seconds == 0 and options.trim_end_seconds is None:
        command[command.index("-i"):command.index("-i")] = ["-ss", str(preview_start), "-t", "60"]
    if preview:
        command[-1:-1] = ["-t", "30"]
    expected_duration_seconds = max(
        1.0,
        (job.estimated_output_duration_ms or job.total_input_duration_ms or 1000) / 1000,
    )
    if preview:
        expected_duration_seconds = min(30.0, expected_duration_seconds)
    if runner:
        run_processing(command, runner=runner)
    else:
        run_processing(
            command,
            expected_duration_seconds=expected_duration_seconds,
            progress_callback=lambda ratio: (check(), progress(ratio)),
        )
    check()
    output_size = output_path.stat().st_size
    if output_size >= output_budget:
        raise AudioPreparationError(AudioPreparationReason.output_too_large)
    output_probe = probe_media(output_path, runner=runner) if runner else probe_media(output_path)
    if preview and output_probe.duration_seconds > 31:
        raise AudioPreparationError(AudioPreparationReason.processing_failed)
    if output_size <= 0:
        raise AudioPreparationError(AudioPreparationReason.processing_failed)
    if output_size > getattr(
        settings,
        "audio_preparation_max_output_bytes",
        settings.source_max_upload_bytes,
    ):
        raise AudioPreparationError(AudioPreparationReason.output_too_large)
    check()
    output_filename = render_output_filename(
        options,
        created_at=creation_time,
        project_title=db.get(Project, job.project_id).title,
        title=job.title,
    )
    if options.output_format is AudioOutputFormat.copy:
        output_filename = f"{Path(output_filename).stem}.{extension}"
    mime_type = _output_mime(options, job)
    return RenderedAudio(output_path, "Фрагмент.wav" if preview else job.output_filename or output_filename,
        "audio/wav" if preview else job.output_mime_type or mime_type, output_size, round(output_probe.duration_seconds * 1000))

def _earliest_creation_time(job) -> datetime | None:
    values = [item.source.source_created_at for item in job.inputs if item.source and item.source.source_created_at]
    return min((_naive_utc(value) for value in values), default=None)


def _output_extension(job, options, paths) -> str:
    if options.output_format is AudioOutputFormat.copy:
        return paths[0].suffix.lstrip(".").lower() or "audio"
    return options.output_format.value


def _output_mime(options, job) -> str:
    if options.output_format is AudioOutputFormat.wav:
        return "audio/wav"
    if options.output_format is AudioOutputFormat.flac:
        return "audio/flac"
    return job.inputs[0].source.mime_type or "application/octet-stream"


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)
