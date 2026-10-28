from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


def test_provider_identity_survives_credential_rotation_and_future_models():
    from studio_api.transcription_analytics import build_transcription_analytics_payload
    rows = [SimpleNamespace(status="queued", provider=p, provider_credential_id="rotated",
        options_json=json.dumps({"_stt_model": m}), operating_mode="standard", language="ru")
        for p, m in [("yandex", "general"), ("yandex", "deferred-general"), ("elevenlabs", "scribe_v2"), ("yandex", "future-model")]]
    payload = build_transcription_analytics_payload(jobs=rows, source_count=4, output_count=0,
        attempts=[], provider_by_credential_id={"rotated": "elevenlabs"})
    assert payload["configuration"]["provider_model"] == {
        "elevenlabs_scribe_v2": 1, "yandex_general": 1, "yandex_deferred_general": 1, "mistral_voxtral_small_transcribe_3": 0, "gemini_35_transcribe": 0, "tbank_default": 0, "unknown": 1}


def enum(value: str):
    return SimpleNamespace(value=value)


def job(
    status: str,
    *,
    created_at: datetime,
    started_after: int | None,
    finished_after: int | None,
    credential_id: str | None,
    provider: str | None = None,
    language: str | None = "ru",
    options_json: str | None = None,
    billed_duration_ms: int | None = None,
    cost_amount: str | None = None,
    accounting_complete: bool | None = None,
    accounting_uncertain: bool | None = None,
):
    return SimpleNamespace(
        status=enum(status),
        created_at=created_at,
        started_at=(
            created_at + timedelta(seconds=started_after)
            if started_after is not None
            else None
        ),
        finished_at=(
            created_at + timedelta(seconds=finished_after)
            if finished_after is not None
            else None
        ),
        provider_credential_id=credential_id,
        provider=provider,
        language=language,
        options_json=options_json,
        provider_billed_duration_ms=billed_duration_ms,
        provider_cost_amount=cost_amount,
        provider_accounting_complete=accounting_complete,
        provider_accounting_uncertain=accounting_uncertain,
        title="private title",
        output_drive_folder_url="https://drive.google.com/private-folder",
    )


def attempt(
    start: datetime | None,
    returned: datetime | None,
    completed: datetime | None,
):
    return SimpleNamespace(
        provider_request_started_at=start,
        provider_response_returned_at=returned,
        completed_at=completed,
        failure_code="private-provider-error",
    )


def test_analytics_aggregates_only_safe_durable_counts_and_intervals():
    from studio_api.transcription_analytics import build_transcription_analytics_payload

    now = datetime(2026, 7, 23, tzinfo=timezone.utc)
    payload = build_transcription_analytics_payload(
        jobs=[
            job(
                "completed",
                created_at=now,
                started_after=10,
                finished_after=100,
                credential_id="credential-elevenlabs",
                language="ru",
                options_json='{"diarize":true}',
                billed_duration_ms=3_600_000,
                cost_amount="0.22000000",
                accounting_complete=True,
                accounting_uncertain=False,
            ),
            job(
                "failed",
                created_at=now,
                started_after=20,
                finished_after=80,
                credential_id="credential-missing",
                language=None,
                billed_duration_ms=60_000,
                cost_amount="0.00366667",
                accounting_complete=False,
                accounting_uncertain=True,
            ),
            job(
                "queued",
                created_at=now,
                started_after=None,
                finished_after=None,
                credential_id=None,
                provider="elevenlabs",
                language="en",
            ),
        ],
        source_count=4,
        output_count=1,
        attempts=[
            attempt(
                now + timedelta(seconds=20),
                now + timedelta(seconds=50),
                now + timedelta(seconds=90),
            ),
            attempt(
                now + timedelta(seconds=30),
                now + timedelta(seconds=50),
                now + timedelta(seconds=70),
            ),
            attempt(
                now + timedelta(seconds=60),
                now + timedelta(seconds=50),
                now + timedelta(seconds=40),
            ),
            attempt(now, None, None),
        ],
        provider_by_credential_id={"credential-elevenlabs": "elevenlabs"},
    )

    assert payload == {
        "scope": "project_all_time",
        "totals": {"jobs": 3, "sources": 4, "outputs": 1},
        "outcomes": {
            "queued": 1,
            "processing": 0,
            "completed": 1,
            "failed": 1,
            "cancelled": 0,
        },
        "success": {
            "successful_jobs": 1,
            "terminal_jobs": 2,
            "percentage": 50.0,
        },
        "configuration": {
            "provider_model": {
                "elevenlabs_scribe_v2": 2,
                "yandex_general": 0,
                "yandex_deferred_general": 0, "mistral_voxtral_small_transcribe_3": 0, "gemini_35_transcribe": 0, "tbank_default": 0,
                "unknown": 1,
            },
            "language_mode": {"ru": 1, "en": 1, "detect": 1, "other": 0},
            "diarization": {"enabled": 1, "disabled": 2},
        },
        "usage_cost": {
            "confirmed_billed_duration_seconds": 3660.0,
            "confirmed_provider_cost": "0.22366667",
            "currency": "USD",
            "cost_basis": "confirmed_audio_duration_x_rate_snapshot",
            "complete_jobs": 1,
            "uncertain_jobs": 1,
            "unavailable_jobs": 1,
            "in_progress_jobs": 0,
        },
        "durations": {
            "queue": {
                "sample_count": 2,
                "average_seconds": 15.0,
                "p50_seconds": 15.0,
                "p95_seconds": 20.0,
            },
            "processing": {
                "sample_count": 2,
                "average_seconds": 75.0,
                "p50_seconds": 75.0,
                "p95_seconds": 90.0,
            },
            "provider_processing": {
                "sample_count": 2,
                "average_seconds": 25.0,
                "p50_seconds": 25.0,
                "p95_seconds": 30.0,
            },
            "post_provider_output": {
                "sample_count": 2,
                "average_seconds": 30.0,
                "p50_seconds": 30.0,
                "p95_seconds": 40.0,
            },
        },
    }
    encoded = json.dumps(payload)
    for private_marker in (
        "private title",
        "private-folder",
        "credential-elevenlabs",
        "credential-missing",
        "private-provider-error",
    ):
        assert private_marker not in encoded


def test_analytics_reports_empty_duration_samples_honestly():
    from studio_api.transcription_analytics import build_transcription_analytics_payload

    payload = build_transcription_analytics_payload(
        jobs=[],
        source_count=0,
        output_count=0,
        attempts=[],
        provider_by_credential_id={},
    )

    assert payload["totals"] == {"jobs": 0, "sources": 0, "outputs": 0}
    assert payload["outcomes"] == {
        "queued": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
    }
    assert payload["success"] == {
        "successful_jobs": 0,
        "terminal_jobs": 0,
        "percentage": None,
    }
    assert all(
        summary == {
            "sample_count": 0,
            "average_seconds": None,
            "p50_seconds": None,
            "p95_seconds": None,
        }
        for summary in payload["durations"].values()
    )


def test_analytics_identifies_a_reset_scope_without_exposing_the_timestamp():
    from studio_api.transcription_analytics import build_transcription_analytics_payload

    reset_at = datetime(2026, 8, 21, tzinfo=timezone.utc)
    payload = build_transcription_analytics_payload(
        jobs=[],
        source_count=0,
        output_count=0,
        attempts=[],
        provider_by_credential_id={},
        since=reset_at,
    )

    assert payload["scope"] == "project_since_reset"
    assert reset_at.isoformat() not in json.dumps(payload)


def test_database_analytics_is_exact_and_uses_constant_query_count(monkeypatch):
    monkeypatch.setenv("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    from studio_api.config import get_settings

    get_settings.cache_clear()
    from studio_api.db import Base
    from studio_api.models import (
        JobStatus,
        Project,
        Source,
        SourceType,
        SourceUploadStatus,
        TranscriptionJob,
        TranscriptionJobSource,
        User,
    )
    from studio_api.transcription_analytics import load_transcription_analytics_payload

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    with Session(engine) as db:
        db.add(User(id="owner-analytics", email="analytics@example.test"))
        db.add(
            Project(
                id="project-analytics",
                owner_user_id="owner-analytics",
                title="Analytics",
            )
        )
        for index in range(25):
            created_at = now + timedelta(seconds=index)
            job_row = TranscriptionJob(
                id=f"job-{index}",
                project_id="project-analytics",
                owner_user_id="owner-analytics",
                status=(JobStatus.completed if index % 2 == 0 else JobStatus.failed),
                provider="elevenlabs",
                language="ru" if index % 3 else "en",
                options_json='{"diarize":true}' if index % 4 == 0 else None,
                created_at=created_at,
                started_at=created_at + timedelta(seconds=10),
                finished_at=created_at + timedelta(seconds=40),
            )
            source_row = Source(
                id=f"source-{index}",
                project_id="project-analytics",
                source_type=SourceType.local_upload,
                original_filename=f"{index}.mp3",
                upload_status=SourceUploadStatus.uploaded,
            )
            db.add_all(
                [
                    job_row,
                    source_row,
                    TranscriptionJobSource(
                        id=f"relation-{index}",
                        job_id=job_row.id,
                        source_id=source_row.id,
                        position=0,
                    ),
                ]
            )
        db.commit()

        query_count = 0

        def count_selects(_conn, _cursor, statement, _parameters, _context, _many):
            nonlocal query_count
            if statement.lstrip().upper().startswith("SELECT"):
                query_count += 1

        event.listen(engine, "before_cursor_execute", count_selects)
        payload = load_transcription_analytics_payload(
            db,
            owner_user_id="owner-analytics",
            project_id="project-analytics",
        )
        event.remove(engine, "before_cursor_execute", count_selects)

    engine.dispose()
    assert query_count == 8
    assert payload["totals"] == {"jobs": 25, "sources": 25, "outputs": 0}
    assert payload["outcomes"]["completed"] == 13
    assert payload["outcomes"]["failed"] == 12
    assert payload["success"] == {
        "successful_jobs": 13,
        "terminal_jobs": 25,
        "percentage": 52.0,
    }
    assert payload["configuration"]["provider_model"] == {
        "elevenlabs_scribe_v2": 25,
        "yandex_general": 0,
        "yandex_deferred_general": 0, "mistral_voxtral_small_transcribe_3": 0, "gemini_35_transcribe": 0, "tbank_default": 0,
        "unknown": 0,
    }
    assert payload["usage_cost"] == {
        "confirmed_billed_duration_seconds": 0.0,
        "confirmed_provider_cost": "0.00000000",
        "currency": "USD",
        "cost_basis": "confirmed_audio_duration_x_rate_snapshot",
        "complete_jobs": 0,
        "uncertain_jobs": 0,
        "unavailable_jobs": 0,
        "in_progress_jobs": 25,
    }
    assert payload["durations"]["queue"] == {
        "sample_count": 25,
        "average_seconds": 10.0,
        "p50_seconds": 10.0,
        "p95_seconds": 10.0,
    }
    assert payload["durations"]["processing"] == {
        "sample_count": 25,
        "average_seconds": 30.0,
        "p50_seconds": 30.0,
        "p95_seconds": 30.0,
    }
