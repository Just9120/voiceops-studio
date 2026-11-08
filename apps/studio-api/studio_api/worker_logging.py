"""Allowlisted diagnostics: never exception text, traceback or arbitrary extras."""
import json
import logging
import re
import uuid

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,100}\Z")
_TOKENS = {"event", "stage", "error_type", "reason", "final_job_status", "status", "workflow", "operation"}
_COUNTS = {"attempt_count", "required_source_count", "persisted_output_count", "processed_source_count", "checkpoint_count", "draft_count", "output_created", "completion_occurred", "deleted_count", "failed_count"}


def safe_error_type(exc):
    cls = type(exc)
    if cls.__module__ == "builtins" or cls.__module__.startswith("studio_api."):
        return cls.__name__ if _TOKEN.fullmatch(cls.__name__) else "Exception"
    return "Exception"


class WorkerLogFormatter(logging.Formatter):
    def format(self, record):
        event = str(record.msg)
        result = {"event": event if _TOKEN.fullmatch(event) else "worker_event_redacted"}
        for key in _TOKENS - {"event"}:
            value = getattr(record, key, None)
            if isinstance(value, str) and _TOKEN.fullmatch(value):
                result[key] = value
        for key in _COUNTS:
            value = getattr(record, key, None)
            if isinstance(value, (int, bool)):
                result[key] = value
        for key in ("job_id", "run_id", "iteration_id"):
            try:
                result[key] = str(uuid.UUID(str(getattr(record, key))))
            except (AttributeError, ValueError, TypeError):
                pass
        return json.dumps(result, sort_keys=True)
