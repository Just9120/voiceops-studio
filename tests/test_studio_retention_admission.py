"""Expiry can be crossed by admitted work, never by idle drafts or new work."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
from studio_api.source_policy import operation_retains_source

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)


@pytest.mark.parametrize("changes", [
    {}, {"lease_owner_id": None}, {"lease_owner_id": ""},
    {"lease_expires_at": NOW}, {"source_access_started_at": NOW - timedelta(seconds=1)},
    {"source_access_started_at": None}, {"cancel_requested_at": NOW},
    {"status": "preview_ready", "current_stage": "preview_ready"},
    {"status": "queued"}, {"status": "failed"},
    {"status": "completed", "current_stage": "audio_download_queued"},
])
def test_current_lease_and_admission_before_expiry_are_both_required(changes):
    job = SimpleNamespace(status="processing", lease_owner_id="worker", lease_expires_at=NOW + timedelta(minutes=1),
        source_access_started_at=NOW - timedelta(seconds=2), cancel_requested_at=None, current_stage="materializing")
    for key, value in changes.items():
        setattr(job, key, value)
    assert operation_retains_source(job, NOW - timedelta(seconds=1), NOW) is (not changes)


@pytest.mark.parametrize("state,stage", [("analyzing", "validating"), ("processing", "materializing"),
    ("preview_ready", "audio_download_rendering"), ("completed", "audio_download_rendering"),
    ("completed", "google_drive_upload")])
def test_actual_audio_work_can_complete_and_recover_across_ttl(state, stage):
    job = SimpleNamespace(status=state, current_stage=stage, lease_owner_id="replacement-worker",
        lease_expires_at=NOW + timedelta(minutes=1), source_access_started_at=(NOW - timedelta(seconds=2)).replace(tzinfo=None),
        cancel_requested_at=None)
    expiry = NOW - timedelta(seconds=1)
    assert operation_retains_source(job, expiry, NOW)
    assert not operation_retains_source(job, expiry, NOW + timedelta(minutes=1))
