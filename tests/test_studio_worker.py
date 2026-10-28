from __future__ import annotations

import logging
import sys
import threading
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


@dataclass
class FakeSettings:
    worker_poll_interval_seconds: int = 5
    worker_error_backoff_seconds: int = 5
    worker_lease_ttl_seconds: int = 3600
    worker_lease_heartbeat_interval_seconds: int = 60


class StopEvent:
    def __init__(self, stop_first=False):
        self.set_calls = 0; self.waits=[]; self._set=stop_first
    def is_set(self): return self._set
    def set(self): self.set_calls += 1; self._set = True
    def wait(self, seconds): self.waits.append(seconds); self._set=True; return True


class Session:
    def __init__(self, events): self.events=events
    def close(self): self.events.append("close")
    def rollback(self): self.events.append("rollback")
    def commit(self): self.events.append("commit")


def test_worker_settings_defaults_and_bounds(monkeypatch):
    from studio_api.config import Settings
    for k in ["STUDIO_WORKER_POLL_INTERVAL_SECONDS", "STUDIO_WORKER_ERROR_BACKOFF_SECONDS", "STUDIO_WORKER_LEASE_TTL_SECONDS", "STUDIO_WORKER_LEASE_HEARTBEAT_INTERVAL_SECONDS"]:
        monkeypatch.delenv(k, raising=False)
    s=Settings()
    assert (s.worker_poll_interval_seconds, s.worker_error_backoff_seconds, s.worker_lease_ttl_seconds, s.worker_lease_heartbeat_interval_seconds)==(5,5,3600,60)
    assert s.source_upload_ttl_seconds==3600
    assert s.realtime_draft_ttl_seconds==259200
    assert Settings(source_upload_ttl_seconds=900)
    assert Settings(source_upload_ttl_seconds=86400)
    assert Settings(source_presign_ttl_seconds=60)
    assert Settings(source_presign_ttl_seconds=900)
    assert Settings(source_max_upload_bytes=1)
    assert Settings(source_max_upload_bytes=2147483647)
    assert Settings(realtime_draft_ttl_seconds=259200)
    assert Settings(worker_poll_interval_seconds=1, worker_error_backoff_seconds=1, worker_lease_ttl_seconds=300, worker_lease_heartbeat_interval_seconds=100)
    assert Settings(worker_poll_interval_seconds=60, worker_error_backoff_seconds=300, worker_lease_ttl_seconds=86400)
    with pytest.raises(ValidationError): Settings(source_upload_ttl_seconds=899)
    with pytest.raises(ValidationError): Settings(source_upload_ttl_seconds=86401)
    with pytest.raises(ValidationError): Settings(source_presign_ttl_seconds=59)
    with pytest.raises(ValidationError): Settings(source_presign_ttl_seconds=901)
    with pytest.raises(ValidationError): Settings(source_max_upload_bytes=0)
    with pytest.raises(ValidationError): Settings(source_max_upload_bytes=2147483648)
    with pytest.raises(ValidationError): Settings(realtime_draft_ttl_seconds=259199)
    with pytest.raises(ValidationError): Settings(realtime_draft_ttl_seconds=259201)
    with pytest.raises(ValidationError): Settings(worker_poll_interval_seconds=0)
    with pytest.raises(ValidationError): Settings(worker_error_backoff_seconds=301)
    with pytest.raises(ValidationError): Settings(worker_lease_ttl_seconds=299)
    with pytest.raises(ValidationError): Settings(worker_lease_ttl_seconds=300, worker_lease_heartbeat_interval_seconds=101)


def test_telegram_configuration_is_honest_and_secret_file_backed(tmp_path):
    from studio_api.config import Settings

    token_file = tmp_path / "telegram-token"
    chat_file = tmp_path / "telegram-chat"
    token_file.write_text("1234567890:unit-test-token-value", encoding="utf-8")
    chat_file.write_text("-1001234567890", encoding="utf-8")
    configured = Settings(
        alert_telegram_enabled=True,
        alert_telegram_bot_token_file=str(token_file),
        alert_telegram_chat_id_file=str(chat_file),
    )
    assert configured.telegram_alerts_configured()
    assert configured.telegram_alert_credentials() == (
        "1234567890:unit-test-token-value",
        "-1001234567890",
    )

    token_file.write_text("", encoding="utf-8")
    assert not configured.telegram_alerts_configured()
    with pytest.raises(RuntimeError, match="token secret is invalid"):
        configured.telegram_alert_credentials()


def test_main_configuration_failure_is_normalized_before_db(monkeypatch, caplog):
    from studio_api import worker
    class BadSettings:
        def __init__(self): raise ValidationError.from_exception_data("Settings", [])
    monkeypatch.setattr("studio_api.config.Settings", BadSettings)
    caplog.set_level(logging.ERROR)
    assert worker.main() == 2
    assert "studio_worker_configuration_invalid" in caplog.text
    assert "999SECRET" not in caplog.text and "ValidationError" not in caplog.text


def test_main_wires_provider_cleanup_before_start_and_stops_backgrounds(monkeypatch):
    from types import SimpleNamespace
    from studio_api import worker, runtime_observability, worker_background
    from studio_api.provider_file_cleanup import process_one_provider_file_cleanup
    events = []
    configured = SimpleNamespace(**vars(FakeSettings()), runtime_worker_heartbeat_interval_seconds=5)
    monkeypatch.setattr("studio_api.config.Settings", lambda: configured)
    monkeypatch.setattr(worker, "install_signal_handlers", lambda stop: None)
    monkeypatch.setattr(runtime_observability, "settings_runtime_identity", lambda *args, **kwargs: object())
    monkeypatch.setattr(runtime_observability, "current_worker_runtime_instance_id", lambda: "synthetic-instance")

    class Heartbeat:
        def __init__(self, **kwargs): pass
        def start(self): events.append("heartbeat_started")
        def stop_and_join(self): events.append("heartbeat_stopped")
    class Background:
        def __init__(self, **kwargs):
            assert kwargs["provider_file_cleanup_runner"] is process_one_provider_file_cleanup
        def start(self): events.append("background_started")
        def stop_and_join(self): events.append("background_stopped")
    def run(**kwargs):
        assert kwargs["independent_background"] is True
        events.append("loop")
        return 0
    monkeypatch.setattr(runtime_observability, "WorkerRuntimeHeartbeat", Heartbeat)
    monkeypatch.setattr(worker_background, "WorkerBackground", Background)
    monkeypatch.setattr(worker, "run_worker_loop", run)
    assert worker.main() == 0
    assert events == ["heartbeat_started", "background_started", "loop", "background_stopped", "heartbeat_stopped"]


def test_owner_id_safe_stable_and_unique():
    from studio_api.worker import build_worker_owner_id
    a=build_worker_owner_id(hostname="raw-host-SECRET")
    b=build_worker_owner_id(hostname="raw-host-SECRET")
    assert a.startswith("studio-worker:") and len(a) <= 128
    assert b.startswith("studio-worker:") and a != b
    assert "raw-host" not in a and "SECRET" not in a


def test_idle_closes_session_then_waits_poll_interval(caplog):
    from studio_api.worker import run_worker_loop
    events=[]; stop=StopEvent(); caplog.set_level(logging.WARNING)
    def sf(): events.append("session"); return Session(events)
    def iteration(db, **kw): events.append(("iteration", kw["lease_owner_id"], kw["lease_ttl"])); return None
    assert run_worker_loop(settings=FakeSettings(), session_factory=sf, stop_event=stop, iteration=iteration, owner_id_factory=lambda:"owner", source_cleanup_runner=lambda db, **kw: events.append("cleanup") and False, alert_evaluator=lambda **kw: None, alert_delivery_runner=lambda **kw: None) == 0
    assert events == ["session", ("iteration", "owner", timedelta(seconds=3600)), "close", "session", "cleanup", "close"]
    assert stop.waits == [5]
    assert caplog.text == ""


def test_idle_physically_expires_realtime_drafts(caplog):
    from studio_api.worker import run_worker_loop
    events=[]; stop=StopEvent(); caplog.set_level(logging.INFO)
    def sf(): events.append("session"); return Session(events)
    def iteration(db, **kw): events.append("iteration"); return None
    run_worker_loop(
        settings=FakeSettings(),
        session_factory=sf,
        stop_event=stop,
        iteration=iteration,
        owner_id_factory=lambda:"owner",
        source_cleanup_runner=lambda db, **kw: False,
        provider_checkpoint_cleanup_runner=lambda db, **kw: 0,
        realtime_draft_cleanup_runner=lambda db, **kw: 2,
        alert_evaluator=lambda **kw: None,
        alert_delivery_runner=lambda **kw: None,
    )
    assert events == [
        "session", "iteration", "close", "session", "commit", "close"
    ]
    assert "studio_worker_realtime_drafts_expired" in caplog.text


def test_idle_runs_bounded_alert_evaluation_then_one_delivery():
    from studio_api.worker import run_worker_loop

    events = []
    stop = StopEvent()

    def session_factory():
        events.append("session")
        return Session(events)

    run_worker_loop(
        settings=FakeSettings(),
        session_factory=session_factory,
        stop_event=stop,
        iteration=lambda db, **kw: None,
        owner_id_factory=lambda: "owner",
        source_cleanup_runner=lambda db, **kw: False,
        provider_checkpoint_cleanup_runner=lambda db, **kw: 0,
        realtime_draft_cleanup_runner=lambda db, **kw: 0,
        job_notification_runner=lambda **kw: events.append(
            "one_job_notification_attempted"
        ),
        alert_evaluator=lambda **kw: events.append("alerts_evaluated"),
        alert_delivery_runner=lambda **kw: events.append("one_delivery_attempted"),
    )

    assert events[-3:] == [
        "one_job_notification_attempted",
        "alerts_evaluated",
        "one_delivery_attempted",
    ]
    assert stop.waits == [5]


def test_success_logs_safe_result_and_uses_new_session(caplog):
    from types import SimpleNamespace
    from studio_api.worker import run_worker_loop
    caplog.set_level(logging.INFO)
    events=[]; stop=StopEvent(); calls={"n":0}
    def sf(): events.append("session"); return Session(events)
    def iteration(db, **kw):
        calls["n"]+=1
        if calls["n"]==1: return SimpleNamespace(job_id="job", final_job_status="completed", attempt_count=1, required_source_count=2, persisted_output_count=2, processed_source_count=2, completion_occurred=True)
        stop.set(); return None
    run_worker_loop(settings=FakeSettings(), session_factory=sf, stop_event=stop, iteration=iteration, owner_id_factory=lambda:"owner", source_cleanup_runner=lambda db, **kw: False)
    assert events.count("session") == 2 and events.count("close") == 2
    assert stop.waits == []
    assert "studio_worker_job_processed" in caplog.text and "SECRET" not in caplog.text


def test_known_and_unexpected_errors_are_redacted_and_continue(caplog):
    from studio_api.worker import run_worker_loop
    class JobProcessingRunnerError(RuntimeError):
        def __init__(self):
            self.reason = type("R", (), {"value":"claim_failed"})()
            super().__init__("claim_failed")
    for unexpected in (False, True):
        caplog.clear(); events=[]; stop=StopEvent(); calls={"n":0}
        def sf(): return Session(events)
        def iteration(db, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                if unexpected: raise RuntimeError("SECRET token traceback")
                raise JobProcessingRunnerError()
            stop.set(); return None
        run_worker_loop(settings=FakeSettings(worker_error_backoff_seconds=7), session_factory=sf, stop_event=stop, iteration=iteration, owner_id_factory=lambda:"owner", source_cleanup_runner=lambda db, **kw: False)
        assert stop.waits == [7]
        assert "SECRET" not in caplog.text and "traceback" not in caplog.text
        assert ("worker_iteration_failed" in caplog.text) is unexpected
        assert events[-1] == "close" and ("rollback" in events) is unexpected


def test_stop_before_claim_and_signal_handler(monkeypatch):
    from studio_api import worker
    stop=StopEvent(stop_first=True)
    assert worker.run_worker_loop(settings=FakeSettings(), session_factory=lambda: (_ for _ in ()).throw(AssertionError()), stop_event=stop, iteration=lambda *a, **k: None) == 0
    registered=[]
    monkeypatch.setattr(worker.signal, "signal", lambda sig, handler: registered.append(handler))
    ev=threading.Event(); worker.install_signal_handlers(ev); registered[0](None, None)
    assert ev.is_set()


def test_stop_during_active_iteration_no_second_claim():
    from studio_api.worker import run_worker_loop
    stop=StopEvent(); calls=[]
    def iteration(db, **kw): calls.append("iteration"); stop.set(); return None
    run_worker_loop(settings=FakeSettings(), session_factory=lambda: Session([]), stop_event=stop, iteration=iteration, owner_id_factory=lambda:"owner", source_cleanup_runner=lambda db, **kw: False)
    assert calls == ["iteration"] and stop.waits == []


def test_stop_between_idle_job_noop_and_source_cleanup_claim_prevents_claim():
    from studio_api.worker import run_worker_loop
    events=[]; stop=StopEvent()
    def sf(): events.append("session"); return Session(events)
    def iteration(db, **kw): events.append("iteration"); return None
    def cleanup_runner(db, **kw):
        stop.set()
        events.append(("cleanup_should_stop", kw["should_stop"]()))
        return False
    run_worker_loop(settings=FakeSettings(), session_factory=sf, stop_event=stop, iteration=iteration, owner_id_factory=lambda:"owner", source_cleanup_runner=cleanup_runner)
    assert events == ["session", "iteration", "close", "session", ("cleanup_should_stop", True), "close"]
    assert stop.waits == []
