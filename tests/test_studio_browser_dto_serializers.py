import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


NOW = datetime(2026, 7, 21, tzinfo=timezone.utc)
PROJECT_KEYS = {
    "output_provider",
    "id",
    "title",
    "description",
    "output_drive_folder_id",
    "output_drive_folder_url",
    "output_drive_folder_name",
    "created_at",
    "updated_at",
    "archived_at",
}
JOB_KEYS = {
    "output_provider",
    "id",
    "project_id",
    "status",
    "title",
    "provider",
    "operating_mode",
    "language_mode",
    "diarization_enabled",
    "media_clip",
    "terminal_dismissed_at",
    "history_attention_resolved_at",
    "history_attention_resolution",
    "history_attention_linked_job_id",
    "source_count",
    "source_names",
    "created_at",
    "updated_at",
    "cancelled_at",
    "cancel_requested_at",
    "attempt_count",
    "started_at",
    "finished_at",
    "error_code",
    "error_message",
    "output_folder",
    "speaker_identities",
    "usage_cost",
}


@pytest.fixture
def browser_serializers(monkeypatch):
    monkeypatch.setenv("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("STUDIO_APP_ORIGIN", "https://studio.test")
    monkeypatch.setenv("STUDIO_COOKIE_SECURE", "false")
    from studio_api.main import job_payload, project_payload
    from studio_api.models import JobStatus

    return project_payload, job_payload, JobStatus


def test_module_does_not_mutate_database_environment_during_collection():
    source = Path(__file__).read_text(encoding="utf-8")
    import_prefix = source.split("@pytest.fixture", 1)[0]
    assert "os.environ" not in import_prefix
    assert "setdefault" not in import_prefix


def test_project_browser_payload_has_an_explicit_minimum_contract(
    browser_serializers,
):
    project_payload, _, _ = browser_serializers
    project = SimpleNamespace(
        id="project-public",
        owner_user_id="owner-internal",
        title="Project",
        description=None,
        output_drive_folder_id=None,
        output_drive_folder_url=None,
        output_drive_folder_name=None,
        created_at=NOW,
        updated_at=NOW,
        archived_at=None,
    )

    payload = project_payload(project)

    assert set(payload) == PROJECT_KEYS
    assert "owner_user_id" not in payload


def test_job_browser_payload_omits_credential_and_worker_authority(
    browser_serializers,
):
    _, job_payload, JobStatus = browser_serializers
    job = SimpleNamespace(
        id="job-public",
        project_id="project-public",
        owner_user_id="owner-internal",
        status=JobStatus.queued,
        title="Job",
        provider="elevenlabs",
        provider_credential_id="credential-internal",
        sources=[],
        created_at=NOW,
        updated_at=NOW,
        cancelled_at=None,
        cancel_requested_at=None,
        attempt_count=0,
        started_at=None,
        finished_at=None,
        error_code=None,
        error_message=None,
        output_drive_folder_id=None,
        output_drive_folder_url=None,
        output_drive_folder_name=None,
        lease_owner_id="worker-internal",
        lease_generation=7,
        terminal_dismissed_at=None,
    )

    payload = job_payload(job)

    assert set(payload) == JOB_KEYS
    assert payload["source_names"] == []
    assert "owner_user_id" not in payload
    assert "provider_credential_id" not in payload
    assert "lease_owner_id" not in payload
    assert "lease_generation" not in payload
    assert payload["operating_mode"] == "standard"
    assert payload["language_mode"] == "detect"
    assert payload["diarization_enabled"] is False
    assert payload["media_clip"] is None
    assert payload["terminal_dismissed_at"] is None
    assert payload["history_attention_resolved_at"] is None
    assert payload["history_attention_resolution"] is None
    assert payload["history_attention_linked_job_id"] is None
    assert payload["speaker_identities"] == []
    assert payload["usage_cost"] == {
        "accounting_status": "unavailable",
        "confirmed_billed_duration_seconds": None,
        "confirmed_provider_cost": None,
        "currency": None,
        "cost_basis": None,
        "rate_snapshot": None,
    }


def test_job_browser_payload_exposes_only_safe_clip_bounds(browser_serializers):
    _, job_payload, JobStatus = browser_serializers
    job = SimpleNamespace(
        id="job-clip",
        project_id="project-public",
        status=JobStatus.queued,
        title="Second project",
        provider="elevenlabs",
        sources=[],
        created_at=NOW,
        updated_at=NOW,
        cancelled_at=None,
        cancel_requested_at=None,
        attempt_count=0,
        started_at=None,
        finished_at=None,
        error_code=None,
        error_message=None,
        output_drive_folder_id=None,
        output_drive_folder_url=None,
        output_drive_folder_name=None,
        media_clip_start_seconds=610,
        media_clip_end_seconds=None,
        terminal_dismissed_at=NOW,
    )

    assert job_payload(job)["media_clip"] == {
        "start_seconds": 610,
        "end_seconds": None,
    }
    assert job_payload(job)["terminal_dismissed_at"] == NOW.isoformat()
