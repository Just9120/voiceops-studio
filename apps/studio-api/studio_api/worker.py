from __future__ import annotations

import hashlib
import logging
import signal
import socket
import sys
import threading
import uuid
from enum import Enum
from datetime import timedelta
from typing import Callable

from pydantic import ValidationError
from .worker_progress import WorkerProgress, bind_worker_progress, begin_worker_iteration, failure_stage
from .worker_logging import WorkerLogFormatter, safe_error_type


LOGGER = logging.getLogger("studio_api.worker")


def build_worker_owner_id(*, hostname: str | None = None, process_uuid: uuid.UUID | None = None) -> str:
    host = hostname if hostname is not None else socket.gethostname()
    digest = hashlib.sha256(host.encode("utf-8", errors="ignore")).hexdigest()[:16]
    process_id = process_uuid or uuid.uuid4()
    owner = f"studio-worker:{digest}:{process_id}"
    return owner[:128]


def install_signal_handlers(stop_event: threading.Event) -> None:
    def _handler(_signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def _reason(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    return reason.value if isinstance(reason, Enum) and type(reason).__module__.startswith("studio_api.") else "unknown"


def _safe_log_result(logger: logging.Logger, result) -> None:
    if hasattr(result, "run_id"):
        logger.info(
            "studio_worker_transcript_maintenance_processed",
            extra={
                "event": "studio_worker_transcript_maintenance_processed",
                "run_id": result.run_id,
                "workflow": result.workflow,
                "operation": result.operation,
                "status": result.status,
            },
        )
        return
    if hasattr(result, "stage"):
        logger.info(
            "studio_worker_audio_preparation_processed",
            extra={
                "event": "studio_worker_audio_preparation_processed",
                "job_id": result.job_id,
                "final_job_status": result.status,
                "stage": result.stage,
                "output_created": result.output_created,
            },
        )
        return
    logger.info(
        "studio_worker_job_processed",
        extra={
            "event": "studio_worker_job_processed",
            "job_id": result.job_id,
            "final_job_status": getattr(result.final_job_status, "value", str(result.final_job_status)),
            "attempt_count": result.attempt_count,
            "required_source_count": result.required_source_count,
            "persisted_output_count": result.persisted_output_count,
            "processed_source_count": result.processed_source_count,
            "completion_occurred": result.completion_occurred,
        },
    )


def _safe_rollback(db, logger: logging.Logger) -> None:
    try:
        db.rollback()
    except Exception:
        logger.warning("worker_session_rollback_failed")


def run_worker_loop(
    *,
    settings,
    session_factory: Callable,
    stop_event: threading.Event,
    iteration: Callable | None = None,
    logger: logging.Logger = LOGGER,
    owner_id_factory: Callable[[], str] = build_worker_owner_id,
    source_cleanup_runner: Callable | None = None,
    provider_checkpoint_cleanup_runner: Callable | None = None,
    realtime_draft_cleanup_runner: Callable | None = None,
    alert_evaluator: Callable | None = None,
    alert_delivery_runner: Callable | None = None,
    job_notification_runner: Callable | None = None,
    independent_background: bool = False,
) -> int:
    default_iteration = iteration is None
    if iteration is None:
        from .audio_preparation_worker import claim_next_studio_work

        iteration = claim_next_studio_work
    lease_ttl = timedelta(seconds=settings.worker_lease_ttl_seconds)
    poll_interval = settings.worker_poll_interval_seconds
    error_backoff = settings.worker_error_backoff_seconds
    owner_id = owner_id_factory()
    work_index = 0
    from .worker_background import WorkerBackground
    background = WorkerBackground(
        settings=settings, session_factory=session_factory, stop_event=stop_event,
        logger=logger, owner_id=owner_id, source_cleanup_runner=source_cleanup_runner,
        provider_checkpoint_cleanup_runner=provider_checkpoint_cleanup_runner,
        realtime_draft_cleanup_runner=realtime_draft_cleanup_runner,
        alert_evaluator=alert_evaluator, alert_delivery_runner=alert_delivery_runner,
        job_notification_runner=job_notification_runner,
    )

    while not stop_event.is_set():
        if stop_event.is_set():
            break
        db = session_factory()
        result = None
        wait_seconds = None
        iteration_failed = False
        begin_worker_iteration()
        iteration_id = str(uuid.uuid4())
        try:
            selection = {}
            if default_iteration:
                classes = ("audio", "transcription", "maintenance")
                selection["work_order"] = classes[work_index:] + classes[:work_index]
                selection["should_stop"] = stop_event.is_set
                work_index = (work_index + 1) % len(classes)
            result = iteration(db, lease_owner_id=owner_id, lease_ttl=lease_ttl, settings=settings, heartbeat_session_factory=session_factory, **selection)
        except Exception as exc:
            if type(exc).__name__ not in {"JobLeaseError", "JobProcessingRunnerError", "JobProcessingOrchestrationError", "TranscriptMaintenanceRunError"}:
                _safe_rollback(db, logger)
                logger.error("worker_iteration_failed", extra={"event": "worker_iteration_failed", "error_type": safe_error_type(exc), "stage": failure_stage(), "iteration_id": iteration_id})
                wait_seconds = error_backoff
                iteration_failed = True
            else:
                logger.warning(
                    "studio_worker_iteration_error",
                    extra={"event": "studio_worker_iteration_error", "error_type": safe_error_type(exc), "reason": _reason(exc), "stage": failure_stage(), "iteration_id": iteration_id},
                )
                wait_seconds = error_backoff
                iteration_failed = True
        finally:
            try:
                db.close()
            except Exception:
                logger.warning("worker_session_close_failed")

        if stop_event.is_set():
            break
        if result is not None:
            _safe_log_result(logger, result)
            continue
        if iteration_failed:
            stop_event.wait(wait_seconds if wait_seconds is not None else poll_interval)
            continue
        if not independent_background:
            background.run_once()
        if stop_event.is_set():
            break
        stop_event.wait(wait_seconds if wait_seconds is not None else poll_interval)
    return 0


def main() -> int:
    handler = logging.StreamHandler()
    handler.setFormatter(WorkerLogFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    try:
        from .config import Settings

        settings = Settings()
        # Force worker fields to be resolved before the DB module can construct its engine.
        _ = (settings.worker_poll_interval_seconds, settings.worker_error_backoff_seconds, settings.worker_lease_ttl_seconds, settings.worker_lease_heartbeat_interval_seconds)
    except ValidationError:
        LOGGER.error("studio_worker_configuration_invalid")
        return 2
    except Exception:
        LOGGER.error("studio_worker_configuration_invalid")
        return 2

    from .db import SessionLocal
    from .runtime_observability import (
        WorkerRuntimeHeartbeat,
        current_worker_runtime_instance_id,
        settings_runtime_identity,
    )

    stop_event = threading.Event()
    install_signal_handlers(stop_event)
    identity = settings_runtime_identity(settings, expected_component="worker")
    if identity is None:
        LOGGER.error("studio_worker_runtime_identity_invalid")
        return 2
    try:
        runtime_instance_id = current_worker_runtime_instance_id()
    except Exception:
        LOGGER.error("studio_worker_runtime_instance_invalid")
        return 2
    progress = WorkerProgress(timeout_seconds=max(120, settings.worker_error_backoff_seconds + 30))
    runtime_heartbeat = WorkerRuntimeHeartbeat(
        session_factory=SessionLocal,
        identity=identity,
        instance_id=runtime_instance_id,
        interval_seconds=settings.runtime_worker_heartbeat_interval_seconds,
        logger=LOGGER,
        progress_check=progress.is_current,
    )
    runtime_heartbeat.start()
    from .worker_background import WorkerBackground
    from .provider_file_cleanup import process_one_provider_file_cleanup
    background = WorkerBackground(
        settings=settings, session_factory=SessionLocal, stop_event=stop_event,
        logger=LOGGER, owner_id=runtime_instance_id,
        provider_file_cleanup_runner=process_one_provider_file_cleanup,
    )
    background.start()
    try:
        with bind_worker_progress(progress):
            return run_worker_loop(
                settings=settings,
                session_factory=SessionLocal,
                stop_event=stop_event,
                logger=LOGGER,
                owner_id_factory=lambda: runtime_instance_id,
                independent_background=True,
            )
    finally:
        background.stop_and_join()
        runtime_heartbeat.stop_and_join()


if __name__ == "__main__":
    raise SystemExit(main())
