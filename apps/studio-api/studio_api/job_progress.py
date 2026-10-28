from __future__ import annotations

from collections import defaultdict
from typing import Iterable
from .work_progress import progress_payload


STAGE_KEYS = (
    "preparation",
    "audio_extraction",
    "splitting",
    "provider_processing",
    "part_merge",
    "google_docs_output",
)
_JOB_QUEUED = "queued"
_JOB_CANCELLED = "cancelled"
_JOB_FAILED = "failed"
_JOB_COMPLETED = "completed"
_SOURCE_SKIPPED = "skipped"
_ATTEMPT_PREPARED = "prepared"
_ATTEMPT_PROVIDER_STARTED = "provider_request_started"
_ATTEMPT_PROVIDER_RETURNED = "provider_response_returned"
_ATTEMPT_GOOGLE_HANDOFF = "google_handoff"
_ATTEMPT_OUTPUT_PERSISTED = "output_persisted"
_ATTEMPT_FAILED = "failed"
_GOOGLE_FAILURE_PREFIXES = ("google_", "output_")
_GOOGLE_FAILURE_CODES = {
    "existing_reconciliation_case",
    "lifecycle_changed_after_output_creation",
}


def load_browser_job_progress_payloads(db, jobs: Iterable[object]) -> list[dict]:
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    from .models import (
        TranscriptionJobOutput,
        TranscriptionJobSource,
        TranscriptionJobSourceAttempt,
    )

    ordered_jobs = list(jobs)
    if not ordered_jobs:
        return []
    job_ids = [job.id for job in ordered_jobs]
    relations = (
        db.execute(
            select(TranscriptionJobSource)
            .where(TranscriptionJobSource.job_id.in_(job_ids))
            .options(joinedload(TranscriptionJobSource.source))
            .order_by(
                TranscriptionJobSource.job_id,
                TranscriptionJobSource.position,
                TranscriptionJobSource.id,
            )
        )
        .scalars()
        .all()
    )
    attempts = (
        db.execute(
            select(TranscriptionJobSourceAttempt)
            .where(TranscriptionJobSourceAttempt.job_id.in_(job_ids))
            .order_by(
                TranscriptionJobSourceAttempt.job_id,
                TranscriptionJobSourceAttempt.job_source_id,
                TranscriptionJobSourceAttempt.attempt_number.desc(),
                TranscriptionJobSourceAttempt.created_at.desc(),
            )
        )
        .scalars()
        .all()
    )
    output_rows = db.execute(
        select(
            TranscriptionJobOutput.job_id,
            TranscriptionJobOutput.job_source_id,
        ).where(TranscriptionJobOutput.job_id.in_(job_ids))
    ).all()

    relations_by_job: dict[str, list[object]] = defaultdict(list)
    for relation in relations:
        relations_by_job[relation.job_id].append(relation)
    attempts_by_job: dict[str, list[object]] = defaultdict(list)
    for attempt in attempts:
        attempts_by_job[attempt.job_id].append(attempt)
    outputs_by_job: dict[str, set[str]] = defaultdict(set)
    for job_id, job_source_id in output_rows:
        outputs_by_job[job_id].add(job_source_id)

    return [
        build_browser_job_progress_payload(
            job=job,
            relations=relations_by_job[job.id],
            attempts=attempts_by_job[job.id],
            output_job_source_ids=outputs_by_job[job.id],
        )
        for job in ordered_jobs
    ]


def build_browser_job_progress_payload(
    *,
    job,
    relations: Iterable[object],
    attempts: Iterable[object],
    output_job_source_ids: set[str] | frozenset[str],
) -> dict:
    job_status = _value(job.status)
    ordered_relations = sorted(relations, key=lambda item: (item.position, item.id))
    current_attempt_number = int(getattr(job, "attempt_count", 0) or 0)
    attempts_by_relation: dict[str, object] = {}
    for attempt in attempts:
        if int(attempt.attempt_number) != current_attempt_number:
            continue
        attempts_by_relation.setdefault(attempt.job_source_id, attempt)

    active_relation_id = _active_relation_id(
        job_status=job_status,
        relations=ordered_relations,
        attempts_by_relation=attempts_by_relation,
        output_job_source_ids=output_job_source_ids,
    )
    source_payloads = []
    current_stage = None
    for relation in ordered_relations:
        payload = _source_progress_payload(
            job_status=job_status,
            relation=relation,
            attempt=attempts_by_relation.get(relation.id),
            output_persisted=relation.id in output_job_source_ids,
            active=relation.id == active_relation_id,
        )
        source_payloads.append(payload)
        if relation.id == active_relation_id:
            current_stage = next(
                (
                    stage["key"]
                    for stage in payload["stages"]
                    if stage["status"] in {"active", "failed", "cancelled"}
                ),
                None,
            )

    required = [
        relation
        for relation in ordered_relations
        if _value(relation.status) != _SOURCE_SKIPPED
    ]
    completed_count = sum(
        relation.id in output_job_source_ids for relation in required
    )
    if job_status == _JOB_COMPLETED and completed_count < len(required):
        # Completed is a lifecycle authority that requires full output coverage.
        completed_count = len(required)
    active_position = next(
        (
            relation.position
            for relation in ordered_relations
            if relation.id == active_relation_id
        ),
        None,
    )
    return {
        "job_id": job.id,
        "work": progress_payload(getattr(job, "work_progress_json", None), generation=getattr(job, "lease_generation", None)) if job_status == "processing" else None,
        "job_status": job_status,
        "tracking_precision": "checkpoint",
        "completed_source_count": completed_count,
        "total_source_count": len(required),
        "active_source_position": active_position,
        "current_stage": current_stage,
        "sources": source_payloads,
    }


def _active_relation_id(
    *,
    job_status: str,
    relations: list[object],
    attempts_by_relation: dict[str, object],
    output_job_source_ids: set[str] | frozenset[str],
) -> str | None:
    if job_status == _JOB_QUEUED:
        return None
    unresolved = [
        relation
        for relation in relations
        if _value(relation.status) != _SOURCE_SKIPPED
        and relation.id not in output_job_source_ids
    ]
    if not unresolved or job_status == _JOB_COMPLETED:
        return None
    progressed = [
        relation
        for relation in unresolved
        if _attempt_stage(attempts_by_relation.get(relation.id))
        not in {None, _ATTEMPT_PREPARED}
    ]
    return (progressed or unresolved)[0].id


def _source_progress_payload(
    *,
    job_status: str,
    relation,
    attempt,
    output_persisted: bool,
    active: bool,
) -> dict:
    source = relation.source
    video = str(getattr(source, "mime_type", "") or "").lower().startswith("video/")
    relation_status = _value(relation.status)
    if relation_status == _SOURCE_SKIPPED:
        source_status = "skipped"
        stage_statuses = ["not_applicable"] * len(STAGE_KEYS)
    elif output_persisted or job_status == _JOB_COMPLETED:
        source_status = "completed"
        stage_statuses = ["completed"] * len(STAGE_KEYS)
    elif job_status == _JOB_QUEUED:
        source_status = "queued"
        stage_statuses = ["pending"] * len(STAGE_KEYS)
    elif not active:
        source_status = (
            "cancelled" if job_status == _JOB_CANCELLED else "queued"
        )
        stage_statuses = ["pending"] * len(STAGE_KEYS)
    else:
        phase_index = _attempt_phase_index(attempt)
        terminal_status = (
            "failed"
            if job_status == _JOB_FAILED
            or _attempt_stage(attempt) == _ATTEMPT_FAILED
            else "cancelled"
            if job_status == _JOB_CANCELLED
            else "active"
        )
        source_status = (
            "processing" if terminal_status == "active" else terminal_status
        )
        stage_statuses = [
            "completed"
            if index < phase_index
            else terminal_status
            if index == phase_index
            else "pending"
            for index in range(len(STAGE_KEYS))
        ]

    stages = []
    for index, key in enumerate(STAGE_KEYS):
        applicability = (
            "not_applicable"
            if key == "audio_extraction" and not video
            else "conditional"
            if key in {"splitting", "part_merge"}
            else "required"
        )
        status = (
            "not_applicable"
            if applicability == "not_applicable"
            else stage_statuses[index]
        )
        stages.append(
            {
                "key": key,
                "status": status,
                "applicability": applicability,
            }
        )
    return {
        "position": relation.position,
        "name": str(getattr(source, "original_filename", "") or "").strip()
        or "Файл без имени",
        "status": source_status,
        "provider_parts": _provider_parts_payload(attempt),
        "stages": stages,
    }


def _provider_parts_payload(attempt) -> dict | None:
    if attempt is None:
        return None
    total = getattr(attempt, "provider_total_parts", None)
    completed = getattr(attempt, "provider_completed_parts", 0)
    if total is None:
        return None
    try:
        total = int(total)
        completed = int(completed or 0)
    except (TypeError, ValueError):
        return None
    if total < 1 or completed < 0 or completed > total:
        return None
    return {"completed": completed, "total": total}


def _attempt_phase_index(attempt) -> int:
    stage = _attempt_stage(attempt)
    if stage == _ATTEMPT_PROVIDER_STARTED:
        return 3
    if stage == _ATTEMPT_PROVIDER_RETURNED:
        return 4
    if stage in {
        _ATTEMPT_GOOGLE_HANDOFF,
        _ATTEMPT_OUTPUT_PERSISTED,
    }:
        return 5
    if stage == _ATTEMPT_FAILED:
        if getattr(attempt, "provider_request_started_at", None) is None:
            return 0
        if getattr(attempt, "provider_response_returned_at", None) is None:
            return 3
        failure_code = str(getattr(attempt, "failure_code", "") or "")
        if failure_code.startswith(_GOOGLE_FAILURE_PREFIXES) or (
            failure_code in _GOOGLE_FAILURE_CODES
        ):
            return 5
        return 4
    return 0


def _attempt_stage(attempt) -> str | None:
    return _value(getattr(attempt, "stage", None)) if attempt is not None else None


def _value(value) -> str:
    return str(getattr(value, "value", value))
