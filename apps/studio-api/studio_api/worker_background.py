from __future__ import annotations

import threading
from datetime import datetime, timezone


class WorkerBackground:
    """One serial housekeeping pass, with sessions independent of active work."""

    def __init__(self, *, settings, session_factory, stop_event, logger, owner_id,
                 source_cleanup_runner=None, provider_checkpoint_cleanup_runner=None,
                 realtime_draft_cleanup_runner=None, alert_evaluator=None,
                 alert_delivery_runner=None, job_notification_runner=None, provider_file_cleanup_runner=None):
        self.settings = settings
        self.session_factory = session_factory
        self.stop_event = stop_event
        self.logger = logger
        self.owner_id = owner_id
        self.source_cleanup_runner = source_cleanup_runner
        self.provider_checkpoint_cleanup_runner = provider_checkpoint_cleanup_runner
        self.realtime_draft_cleanup_runner = realtime_draft_cleanup_runner
        self.alert_evaluator = alert_evaluator
        self.alert_delivery_runner = alert_delivery_runner
        self.job_notification_runner = job_notification_runner
        self.provider_file_cleanup_runner = provider_file_cleanup_runner
        self.last_alert_evaluation_at = None
        self.thread = None

    def start(self):
        if self.thread is not None:
            raise RuntimeError("worker_background_already_started")
        self.thread = threading.Thread(target=self.run, name="studio-worker-background", daemon=True)
        self.thread.start()

    def stop_and_join(self, timeout_seconds=None):
        self.stop_event.set()
        if self.thread is not None:
            # An operator observation timeout must not terminate an in-flight
            # cleanup/delivery. Each boundary retains its own network/DB limits.
            self.thread.join(timeout_seconds)

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                self.logger.warning("studio_worker_background_pass_failed")
            self.stop_event.wait(self.settings.worker_poll_interval_seconds)

    def run_once(self):
        from .worker import _safe_rollback
        settings, session_factory, stop_event = self.settings, self.session_factory, self.stop_event
        logger, owner_id = self.logger, self.owner_id
        source_cleanup_runner = self.source_cleanup_runner
        provider_checkpoint_cleanup_runner = self.provider_checkpoint_cleanup_runner
        realtime_draft_cleanup_runner = self.realtime_draft_cleanup_runner
        alert_evaluator, alert_delivery_runner = self.alert_evaluator, self.alert_delivery_runner
        job_notification_runner = self.job_notification_runner
        last_alert_evaluation_at = self.last_alert_evaluation_at
        if not stop_event.is_set():
            cleanup_db = session_factory()
            try:
                if (
                    provider_checkpoint_cleanup_runner is None
                    and source_cleanup_runner is None
                    and realtime_draft_cleanup_runner is None
                ):
                    from .provider_part_checkpoints import cleanup_expired_provider_part_checkpoints as checkpoint_cleanup_runner
                    from .realtime_drafts import cleanup_expired_realtime_drafts as draft_cleanup_runner
                else:
                    checkpoint_cleanup_runner = provider_checkpoint_cleanup_runner
                    draft_cleanup_runner = realtime_draft_cleanup_runner
                if source_cleanup_runner is None:
                    from .source_deletion import run_one_source_cleanup as cleanup_runner
                else:
                    cleanup_runner = source_cleanup_runner

                cleanup_now = datetime.now(timezone.utc)
                expired_checkpoint_count = (
                    checkpoint_cleanup_runner(cleanup_db, now=cleanup_now)
                    if checkpoint_cleanup_runner is not None
                    else 0
                )
                expired_draft_count = (
                    draft_cleanup_runner(cleanup_db, now=cleanup_now)
                    if draft_cleanup_runner is not None
                    else 0
                )
                if expired_checkpoint_count or expired_draft_count:
                    cleanup_db.commit()
                if expired_checkpoint_count:
                    logger.info(
                        "studio_worker_provider_part_checkpoints_expired",
                        extra={
                            "event": "studio_worker_provider_part_checkpoints_expired",
                            "checkpoint_count": expired_checkpoint_count,
                        },
                    )
                if expired_draft_count:
                    logger.info(
                        "studio_worker_realtime_drafts_expired",
                        extra={
                            "event": "studio_worker_realtime_drafts_expired",
                            "draft_count": expired_draft_count,
                        },
                    )
                if cleanup_runner(cleanup_db, settings=settings, owner_id=f"{owner_id}:source-cleanup", now=cleanup_now, should_stop=stop_event.is_set):
                    logger.info("studio_worker_source_cleanup_processed", extra={"event": "studio_worker_source_cleanup_processed"})
            except Exception:
                _safe_rollback(cleanup_db, logger)
                logger.warning("studio_worker_source_cleanup_failed", extra={"event": "studio_worker_source_cleanup_failed", "reason": "source_cleanup_failed"})
            finally:
                try:
                    cleanup_db.close()
                except Exception:
                    logger.warning("worker_session_close_failed")
            if stop_event.is_set():
                return
            alert_now = datetime.now(timezone.utc)
            if self.provider_file_cleanup_runner is not None:
                try:
                    self.provider_file_cleanup_runner(session_factory=session_factory, settings=settings, now=alert_now)
                except Exception:
                    logger.warning("studio_worker_provider_file_cleanup_failed")
            if stop_event.is_set():
                return
            try:
                from .security_email import process_one_security_email
                process_one_security_email(session_factory=session_factory, settings=settings, now=alert_now)
            except Exception:
                logger.warning("studio_worker_security_email_failed", extra={"event": "studio_worker_security_email_failed"})
            if stop_event.is_set():
                return
            try:
                if job_notification_runner is None:
                    from .job_notifications import process_one_job_notification as deliver_job_notification
                else:
                    deliver_job_notification = job_notification_runner
                deliver_job_notification(session_factory=session_factory, settings=settings, now=alert_now)
            except Exception:
                logger.warning("studio_worker_job_notification_failed", extra={"event": "studio_worker_job_notification_failed"})
            if stop_event.is_set():
                return
            alert_interval = max(30, int(getattr(settings, "alert_evaluation_interval_seconds", 60)))
            if (
                last_alert_evaluation_at is None
                or (alert_now - last_alert_evaluation_at).total_seconds() >= alert_interval
            ):
                try:
                    if alert_evaluator is None:
                        from .operational_alerts import evaluate_all_owner_incidents as evaluate_alerts
                    else:
                        evaluate_alerts = alert_evaluator
                    evaluate_alerts(session_factory=session_factory, settings=settings, now=alert_now)
                    last_alert_evaluation_at = alert_now
                except Exception:
                    logger.warning("studio_worker_alert_evaluation_failed", extra={"event": "studio_worker_alert_evaluation_failed"})
            if stop_event.is_set():
                return
            try:
                if alert_delivery_runner is None:
                    from .operational_alerts import process_one_delivery as deliver_alert
                else:
                    deliver_alert = alert_delivery_runner
                deliver_alert(session_factory=session_factory, settings=settings, now=alert_now)
            except Exception:
                logger.warning("studio_worker_alert_delivery_failed", extra={"event": "studio_worker_alert_delivery_failed"})
        self.last_alert_evaluation_at = last_alert_evaluation_at
