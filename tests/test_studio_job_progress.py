from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


def enum(value: str):
    return SimpleNamespace(value=value)


def source_relation(
    relation_id: str,
    position: int,
    *,
    filename: str,
    mime_type: str,
    status: str = "queued",
):
    return SimpleNamespace(
        id=relation_id,
        position=position,
        status=enum(status),
        source=SimpleNamespace(
            original_filename=filename,
            mime_type=mime_type,
            drive_file_id="private-drive-id",
            drive_file_url="https://drive.google.com/private-source",
            s3_bucket="private-bucket",
            s3_object_key="private/object",
        ),
    )


def attempt(
    relation_id: str,
    stage: str,
    *,
    number: int = 1,
    provider_started=False,
    provider_returned=False,
    provider_total_parts=None,
    provider_completed_parts=0,
    failure_code=None,
):
    return SimpleNamespace(
        job_source_id=relation_id,
        attempt_number=number,
        stage=enum(stage),
        provider_request_started_at=datetime(2026, 7, 23)
        if provider_started
        else None,
        provider_response_returned_at=datetime(2026, 7, 23)
        if provider_returned
        else None,
        provider_total_parts=provider_total_parts,
        provider_completed_parts=provider_completed_parts,
        failure_code=failure_code,
    )


def job(status: str, *, attempt_count: int = 1):
    return SimpleNamespace(id="job-public", status=enum(status), attempt_count=attempt_count)


def stages_by_key(payload: dict, source_index=0):
    return {
        stage["key"]: stage for stage in payload["sources"][source_index]["stages"]
    }


def test_progress_projects_checkpoint_authority_without_private_execution_fields():
    from studio_api.job_progress import build_browser_job_progress_payload

    relations = [
        source_relation(
            "relation-video",
            0,
            filename="Interview.mp4",
            mime_type="video/mp4",
        ),
        source_relation(
            "relation-audio",
            1,
            filename="Call.ogg",
            mime_type="audio/ogg",
        ),
    ]
    payload = build_browser_job_progress_payload(
        job=job("processing"),
        relations=relations,
        attempts=[
            attempt(
                "relation-video",
                "provider_request_started",
                provider_started=True,
                provider_total_parts=4,
                provider_completed_parts=1,
            ),
            attempt("relation-audio", "prepared"),
        ],
        output_job_source_ids=set(),
    )

    assert set(payload) == {
        "job_id",
        "work",
        "job_status",
        "tracking_precision",
        "completed_source_count",
        "total_source_count",
        "active_source_position",
        "current_stage",
        "sources",
    }
    assert payload["active_source_position"] == 0
    assert payload["current_stage"] == "provider_processing"
    assert payload["sources"][0]["status"] == "processing"
    assert payload["sources"][1]["status"] == "queued"
    assert payload["sources"][0]["provider_parts"] == {
        "completed": 1,
        "total": 4,
    }
    assert payload["sources"][1]["provider_parts"] is None
    first = stages_by_key(payload)
    assert first["preparation"]["status"] == "completed"
    assert first["audio_extraction"] == {
        "key": "audio_extraction",
        "status": "completed",
        "applicability": "required",
    }
    assert first["splitting"]["status"] == "completed"
    assert first["splitting"]["applicability"] == "conditional"
    assert first["provider_processing"]["status"] == "active"
    second = stages_by_key(payload, 1)
    assert second["audio_extraction"]["status"] == "not_applicable"
    assert second["audio_extraction"]["applicability"] == "not_applicable"

    encoded = json.dumps(payload)
    for marker in (
        "relation-video",
        "relation-audio",
        "private-drive-id",
        "private-source",
        "private-bucket",
        "private/object",
        "lease",
        "claim",
        "failure_code",
        "provider_total_parts",
        "provider_completed_parts",
    ):
        assert marker not in encoded


def test_progress_maps_merge_google_failure_completion_and_queued_retry_honestly():
    from studio_api.job_progress import build_browser_job_progress_payload

    relation = source_relation(
        "relation-1",
        0,
        filename="Long recording.mp3",
        mime_type="audio/mpeg",
    )
    merge = build_browser_job_progress_payload(
        job=job("processing"),
        relations=[relation],
        attempts=[
            attempt(
                "relation-1",
                "provider_response_returned",
                provider_started=True,
                provider_returned=True,
            )
        ],
        output_job_source_ids=set(),
    )
    assert merge["current_stage"] == "part_merge"
    assert stages_by_key(merge)["part_merge"]["status"] == "active"

    google_failed = build_browser_job_progress_payload(
        job=job("failed"),
        relations=[relation],
        attempts=[
            attempt(
                "relation-1",
                "failed",
                provider_started=True,
                provider_returned=True,
                failure_code="google_docs_unavailable",
            )
        ],
        output_job_source_ids=set(),
    )
    assert google_failed["current_stage"] == "google_docs_output"
    assert stages_by_key(google_failed)["part_merge"]["status"] == "completed"
    assert stages_by_key(google_failed)["google_docs_output"]["status"] == "failed"

    completed = build_browser_job_progress_payload(
        job=job("completed"),
        relations=[relation],
        attempts=[attempt("relation-1", "output_persisted")],
        output_job_source_ids={"relation-1"},
    )
    assert completed["completed_source_count"] == 1
    assert completed["active_source_position"] is None
    assert all(stage["status"] != "active" for stage in completed["sources"][0]["stages"])

    queued_retry = build_browser_job_progress_payload(
        job=job("queued"),
        relations=[relation],
        attempts=[
            attempt(
                "relation-1",
                "failed",
                provider_started=True,
                failure_code="provider_request_rejected",
            )
        ],
        output_job_source_ids=set(),
    )
    assert queued_retry["current_stage"] is None
    assert queued_retry["sources"][0]["status"] == "queued"
    assert stages_by_key(queued_retry)["provider_processing"]["status"] == "pending"
