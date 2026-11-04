"""Synthetic regeneration, ownership, fencing and transient-byte lifecycle."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import anyio
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
from studio_api.audio_downloads import AudioDownloadError, AudioDownloadManager, stream_audio_download, download_directory, expire_audio_downloads
from studio_api.audio_preparation import AudioPreparationError, AudioPreparationReason
from studio_api.audio_preparation_service import (
    AudioPreparationServiceError, audio_preparation_payload, cancel_audio_preparation_job,
    create_audio_preparation_job, queue_audio_drive_export,
)
from studio_api.db import Base
from studio_api.models import AudioPreparationJob, AudioPreparationStatus, Project, Source, SourceType, SourceUploadStatus, User
from studio_api.source_deletion import deletion_readiness
from test_studio_audio_preparation_processor import Storage, isolated_storage_settings, runner

NOW = datetime(2026, 10, 5, 21, tzinfo=timezone.utc)


@pytest.fixture
def state(tmp_path, monkeypatch):
    engine = create_engine("sqlite+pysqlite:///" + (tmp_path / "downloads.db").as_posix())
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    clock = [NOW]
    roots = []
    root = tmp_path / "artifacts"
    root.mkdir()
    monkeypatch.setattr("studio_api.audio_preparation_processor.utcnow", lambda: clock[0])
    storage = Storage(b"original-audio")
    settings = isolated_storage_settings()
    settings.audio_delivery_directory = str(root)
    manager = AudioDownloadManager(factory, settings, clock=lambda: clock[0], cache_root=root)
    with factory() as db:
        db.add_all([User(id="owner", email="owner@test.example"), User(id="stranger", email="other@test.example"),
                    Project(id="project", title="Рабочая папка", owner_user_id="owner")])
        source = Source(id="original", project_id="project", source_type=SourceType.local_upload,
            original_filename="Лекция 1. Предмет.flac", mime_type="audio/flac", size_bytes=len(storage.payload),
            s3_bucket="private", s3_object_key="original", upload_status=SourceUploadStatus.uploaded,
            expires_at=(NOW + timedelta(days=3)).replace(tzinfo=None))
        db.add(source)
        db.commit()
        job = create_audio_preparation_job(db, owner_user_id="owner", project_id="project", title="Лекция 1. Предмет",
            source_ids=[source.id], ephemeral_source_ids={source.id}, manual_order=True,
            options_payload={"preset": "processing_only", "output_format": "flac"},
            output_destination="download", output_folder=None, now=NOW)
        job.status = AudioPreparationStatus.completed
        # A pre-existing completed result without a recorded recipe models the
        # historical regeneration path; newly processed v2 results keep one.
        job.recipe_version = None
        job.current_stage = "completed"
        job.progress_percent = 100
        job.output_filename = "Лекция 1. Предмет.flac"
        job.output_mime_type = "audio/flac"
        job.output_size_bytes = len(b"processed-audio")
        job.output_duration_ms = 60_000
        db.commit()
        yield SimpleNamespace(db=db, job=job, source=source, manager=manager,
                              root=root, roots=roots, storage=storage, clock=clock, settings=settings, factory=factory)
    manager.close()
    engine.dispose()


def prepare(state, owner="owner"):
    return state.manager.prepare(state.db, owner=owner, job_id=state.job.id)



def render(state, *, media_runner=runner, worker="worker"):
    from studio_api.audio_preparation_service import claim_next_audio_preparation_job
    from studio_api.audio_preparation_processor import process_claimed_audio_preparation_job
    job = claim_next_audio_preparation_job(state.db, lease_owner_id=worker, now=state.clock[0], lease_ttl=timedelta(minutes=10))
    assert job is not None
    state.db.commit()
    return process_claimed_audio_preparation_job(state.db, job_id=job.id, lease_owner_id=worker,
        lease_generation=job.lease_generation, settings=state.settings, now=state.clock[0],
        storage_factory=lambda settings: state.storage, runner=media_runner)


def artifact(state):
    state.db.refresh(state.job)
    return download_directory(state.root, state.job.download_request_id)


def send_response(response, *, fail=False):
    chunks = []
    async def receive():
        return {"type": "http.disconnect"}
    async def send(message):
        if fail:
            raise OSError("synthetic connection closed")
        if message["type"] == "http.response.body":
            chunks.append(message["body"])
    async def run():
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
    anyio.run(run)
    return b"".join(chunks)


def test_regenerate_in_worker_after_reload_stream_and_remove_temporary_bytes(state):
    assert audio_preparation_payload(state.job, now=NOW)["output"]["regeneration_required"]
    assert prepare(state)["state"] == "preparing"
    first_id = state.job.download_request_id
    assert prepare(state)["state"] == "preparing" and state.job.download_request_id == first_id
    # An idle queued request is not an active processing lease.
    assert deletion_readiness(state.db, state.source, now=NOW).value == "available"

    def active_runner(command, **kwargs):
        assert deletion_readiness(state.db, state.source, now=NOW).value == "audio_preparation_uses_source"
        return runner(command, **kwargs)

    render(state, media_runner=active_runner)
    directory = artifact(state)
    assert state.manager.status(owner="owner", job_id=state.job.id) == {"state": "ready", "percent": 100, "reason": None}
    assert state.storage.puts == []
    assert {p.name for p in directory.iterdir()} == {"output", ".studio-render"}
    assert state.job.current_stage == "audio_download_ready" and state.job.lease_owner_id is None
    restarted = AudioDownloadManager(state.factory, state.settings, clock=lambda: state.clock[0])
    assert restarted.status(owner="owner", job_id=state.job.id)["state"] == "ready"
    response = stream_audio_download(restarted, owner="owner", job_id=state.job.id)
    assert response.headers["cache-control"] == "private, no-store"
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert send_response(response) == b"processed-audio"
    assert not directory.exists()
    state.db.refresh(state.job)
    assert state.job.download_slot is None and state.job.download_request_id is None
    assert state.db.query(Source).count() == 1


def test_unversioned_legacy_drive_source_cannot_silently_regenerate_with_current_file(state):
    state.source.source_type = SourceType.google_drive
    state.source.drive_file_id = "legacy-file"
    state.db.commit()
    with pytest.raises(AudioPreparationServiceError, match="source_version_unavailable"):
        prepare(state)
    assert state.job.download_request_id is None and state.job.download_slot is None


def test_disconnect_before_body_starts_cleans_rendered_result(state):
    from starlette.requests import ClientDisconnect
    prepare(state)
    render(state)
    directory = artifact(state)
    response = stream_audio_download(state.manager, owner="owner", job_id=state.job.id)
    with pytest.raises(ClientDisconnect):
        send_response(response, fail=True)
    assert not directory.exists()
    state.db.refresh(state.job)
    assert state.job.download_slot is None


def test_stalled_transfer_has_deadline_and_releases_bytes_and_slot(state, monkeypatch):
    monkeypatch.setattr("studio_api.audio_downloads.READY_TTL_SECONDS", 0.01)
    prepare(state)
    render(state)
    directory = artifact(state)
    response = stream_audio_download(state.manager, owner="owner", job_id=state.job.id)
    async def run():
        async def receive():
            return {"type": "http.disconnect"}
        async def send(message):
            await anyio.sleep(10)
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
    with pytest.raises(TimeoutError):
        anyio.run(run)
    assert not directory.exists()
    state.db.refresh(state.job)
    assert state.job.download_slot is None


def test_reclaimed_attempt_does_not_overwrite_or_publish_stale_worker_bytes(state):
    from studio_api.audio_downloads import create_worker_download_directory, mark_worker_download_ready, remove_worker_download_attempt
    from studio_api.audio_preparation_service import claim_next_audio_preparation_job
    prepare(state)
    old = claim_next_audio_preparation_job(state.db, lease_owner_id="old", now=NOW, lease_ttl=timedelta(seconds=1))
    old_generation, request_id = old.lease_generation, old.download_request_id
    state.db.commit()
    old_directory = create_worker_download_directory(old, state.root)
    old_path = old_directory / "partial.flac"
    old_path.write_bytes(b"stale")
    state.clock[0] += timedelta(seconds=2)
    current = claim_next_audio_preparation_job(state.db, lease_owner_id="new", now=state.clock[0], lease_ttl=timedelta(minutes=10))
    state.db.commit()
    current_directory = create_worker_download_directory(current, state.root)
    current_path = current_directory / "ready.flac"
    current_path.write_bytes(b"current")
    with pytest.raises(AudioPreparationServiceError, match="lease_unavailable"):
        mark_worker_download_ready(state.db, job=current, result=SimpleNamespace(path=old_path, size_bytes=5),
            root=state.root, now=state.clock[0], owner="old", generation=old_generation, request_id=request_id)
    state.db.rollback()
    remove_worker_download_attempt(state.root, request_id, old_generation)
    assert current_path.read_bytes() == b"current"
    state.db.refresh(current)
    mark_worker_download_ready(state.db, job=current, result=SimpleNamespace(path=current_path, size_bytes=7),
        root=state.root, now=state.clock[0], owner="new", generation=current.lease_generation, request_id=request_id)
    state.db.commit()
    assert (artifact(state) / "output").read_bytes() == b"current"


def test_cached_ready_result_is_reusable_after_originals_expire(state):
    prepare(state)
    render(state)
    state.source.expires_at = NOW.replace(tzinfo=None)
    state.db.commit()
    assert not audio_preparation_payload(state.job, now=NOW)["output"]["export_ready"]
    assert audio_preparation_payload(state.job, now=NOW)["output"]["download_ready"]
    assert prepare(state)["state"] == "ready"
    assert send_response(stream_audio_download(state.manager, owner="owner", job_id=state.job.id)) == b"processed-audio"


def test_missing_ready_artifact_requeues_from_retained_sources(state):
    prepare(state)
    render(state)
    directory = artifact(state)
    (directory / "output").unlink()
    request_id = state.job.download_request_id
    assert prepare(state)["state"] == "preparing"
    assert state.job.download_request_id != request_id and not directory.exists()
    render(state)


@pytest.mark.parametrize("failure", ["expired", "deleted", "unfinished", "foreign-owner", "archived-project"])
def test_regeneration_admission_is_owner_scoped_and_source_checked(state, failure):
    if failure == "expired":
        state.source.expires_at = NOW.replace(tzinfo=None)
    elif failure == "deleted":
        state.source.deleted_at = NOW.replace(tzinfo=None)
    elif failure == "unfinished":
        state.source.upload_status = SourceUploadStatus.pending
    elif failure == "archived-project":
        state.db.get(Project, "project").archived_at = NOW.replace(tzinfo=None)
    state.db.commit()
    with pytest.raises(AudioPreparationServiceError):
        prepare(state, owner="stranger" if failure == "foreign-owner" else "owner")
    state.db.rollback()
    state.db.refresh(state.job)
    assert state.job.download_slot is None and state.job.lease_owner_id is None


def test_cache_and_delivery_cannot_be_read_by_another_owner(state):
    prepare(state)
    render(state)
    for operation in [state.manager.status, state.manager.take, state.manager.listen]:
        with pytest.raises(AudioPreparationServiceError, match="not_found"):
            operation(owner="stranger", job_id=state.job.id)
    assert artifact(state).exists()


def test_native_playback_uses_ranges_without_extending_retention_or_consuming_download(state):
    from fastapi import FastAPI
    from fastapi.responses import FileResponse
    from fastapi.testclient import TestClient
    prepare(state)
    render(state)
    state.db.refresh(state.job)
    expires_at = state.job.download_expires_at
    app = FastAPI()
    @app.get("/listen")
    def listen():
        result = state.manager.listen(owner="owner", job_id=state.job.id)
        return FileResponse(result.path, media_type=result.mime_type, headers={"Cache-Control": "private, no-store"})
    client = TestClient(app)
    first = client.get("/listen", headers={"range": "bytes=0-3"})
    assert first.status_code == 206 and first.content == b"proc"
    assert first.headers["content-range"] == "bytes 0-3/15"
    second = client.get("/listen", headers={"range": "bytes=4-7"})
    assert second.status_code == 206 and second.content == b"esse"
    state.db.refresh(state.job)
    assert state.job.download_expires_at == expires_at and state.job.download_slot == 1
    assert send_response(stream_audio_download(state.manager, owner="owner", job_id=state.job.id)) == b"processed-audio"


def test_preview_sample_does_not_become_full_result_or_start_transcription(state):
    import json
    from studio_api.audio_preparation_service import start_audio_preparation_job
    state.job.status = AudioPreparationStatus.preview_ready
    state.job.current_stage = "preview_ready"
    state.job.output_filename = state.job.output_mime_type = state.job.output_size_bytes = state.job.output_duration_ms = None
    state.job.total_input_duration_ms = state.job.estimated_output_duration_ms = 60000
    state.job.visual_analysis_json = json.dumps({"sources": [{"position": 0, "silences": [{"start": 25, "end": 30}]}]})
    state.db.commit()
    assert state.manager.prepare(state.db, owner="owner", job_id=state.job.id, preview=True)["state"] == "preparing"
    commands = []
    def preview_runner(command, **kwargs):
        commands.append(command)
        result = runner(command, **kwargs)
        if command[0] == "ffprobe" and str(command[-1]).endswith("processed-output.wav"):
            payload = json.loads(result.stdout)
            payload["streams"][0]["duration"] = payload["format"]["duration"] = "30"
            return SimpleNamespace(stdout=json.dumps(payload), stderr="")
        return result
    render(state, media_runner=preview_runner)
    state.db.refresh(state.job)
    assert state.job.status is AudioPreparationStatus.preview_ready and state.job.output_filename is None
    assert state.job.output_source_id is None and state.job.output_size_bytes is None and state.storage.puts == []
    command = next(command for command in commands if command[0] == "ffmpeg")
    assert command[command.index("-t") + 1] == "60" and command[-1].endswith(".wav")
    assert command[command.index("-t", command.index("-i")) + 1] == "30"
    assert command[command.index("-ss") + 1] == "20" and command.index("-ss") < command.index("-i")
    sample = state.manager.listen(owner="owner", job_id=state.job.id)
    assert sample.filename == "Фрагмент.wav" and sample.mime_type == "audio/wav"
    with pytest.raises(AudioDownloadError, match="download_not_ready"):
        state.manager.take(owner="owner", job_id=state.job.id)
    with pytest.raises(AudioPreparationServiceError, match="invalid_state"):
        start_audio_preparation_job(state.db, owner_user_id="owner", job_id=state.job.id)
    state.db.rollback()
    state.manager.cancel(state.db, owner="owner", job_id=state.job.id)
    state.db.refresh(state.job)
    assert state.job.status is AudioPreparationStatus.preview_ready and state.job.current_stage == "preview_ready"
    assert state.job.download_slot is None and not sample.path.exists()
    assert start_audio_preparation_job(state.db, owner_user_id="owner", job_id=state.job.id).status is AudioPreparationStatus.queued


def test_drive_export_cannot_steal_queued_download(state):
    prepare(state)
    with pytest.raises(AudioPreparationServiceError, match="lease_unavailable"):
        queue_audio_drive_export(state.db, owner_user_id="owner", job_id=state.job.id,
            folder=SimpleNamespace(id="folder", name="Результаты", web_view_url="https://drive.google.com/drive/folders/folder"), now=NOW)
    state.db.rollback()
    render(state)


def test_worker_failure_preserves_success_and_cleans_shared_partial_bytes(state):
    import subprocess
    prepare(state)
    directory = artifact(state)
    def fail(command, **kwargs):
        if command[0] == "ffmpeg":
            Path(command[-1]).write_bytes(b"partial")
            raise subprocess.CalledProcessError(1, command, stderr="synthetic bad media")
        return runner(command, **kwargs)
    with pytest.raises(AudioPreparationError, match="processing_failed"):
        render(state, media_runner=fail)
    assert not directory.exists()
    state.db.refresh(state.job)
    assert state.job.status is AudioPreparationStatus.completed and state.job.output_filename
    assert state.job.output_source_id is None and state.storage.puts == []
    assert state.job.lease_owner_id is None and state.job.download_slot is None
    assert state.manager.status(owner="owner", job_id=state.job.id)["state"] == "failed"


def test_cancelled_queue_preserves_result_parameters_and_does_not_render(state):
    prepare(state)
    state.manager.cancel(state.db, owner="owner", job_id=state.job.id)
    assert state.manager.status(owner="owner", job_id=state.job.id)["reason"] == "cancellation_requested"
    state.db.refresh(state.job)
    assert state.job.download_slot is None and state.job.status is AudioPreparationStatus.completed
    assert deletion_readiness(state.db, state.source, now=NOW).value == "available"


def test_expired_request_does_not_keep_inputs_or_bytes_locked_forever(state):
    prepare(state)
    state.clock[0] += timedelta(hours=4)
    assert deletion_readiness(state.db, state.source, now=state.clock[0]).value == "available"
    expire_audio_downloads(state.db, root=state.root, now=state.clock[0])
    state.db.commit()
    state.db.refresh(state.job)
    assert state.job.download_slot is None
    assert prepare(state)["state"] == "preparing"
    render(state)


def test_ready_artifact_expiry_cleanup_survives_api_restart(state):
    prepare(state)
    render(state)
    directory = artifact(state)
    state.clock[0] += timedelta(minutes=16)
    assert expire_audio_downloads(state.db, root=state.root, now=state.clock[0]) == 1
    state.db.commit()
    assert not directory.exists()
    with pytest.raises(AudioDownloadError, match="download_expired"):
        state.manager.status(owner="owner", job_id=state.job.id)


def test_one_db_slot_bounds_all_downloads(state):
    prepare(state)
    job = create_audio_preparation_job(state.db, owner_user_id="owner", project_id="project", title="Другая",
        source_ids=[state.source.id], ephemeral_source_ids=set(), manual_order=True,
        options_payload={"preset": "processing_only", "output_format": "flac"},
        output_destination="download", output_folder=None, now=NOW)
    job.status = AudioPreparationStatus.completed
    job.current_stage = "completed"
    job.output_filename = "Другая.flac"
    state.db.commit()
    with pytest.raises(AudioDownloadError, match="download_busy"):
        state.manager.prepare(state.db, owner="owner", job_id=job.id)
    state.db.rollback()
    state.db.refresh(job)
    assert job.download_slot is None


def test_cleanup_preserves_unknown_directory_contents(state):
    prepare(state)
    directory = artifact(state)
    directory.mkdir()
    (directory / "unknown").write_text("preserve")
    state.clock[0] += timedelta(hours=4)
    with pytest.raises(AudioDownloadError, match="download_unavailable"):
        expire_audio_downloads(state.db, root=state.root, now=state.clock[0])
    state.db.rollback()
    assert (directory / "unknown").read_text() == "preserve"


@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_post_reload_drive_export_regenerates_without_s3_output(state, outcome):
    from studio_api.audio_preparation_service import claim_next_audio_preparation_job
    from studio_api.audio_preparation_processor import process_claimed_audio_preparation_job
    folder = SimpleNamespace(id="folder", name="Результаты", web_view_url="https://drive.google.com/drive/folders/folder")
    queue_audio_drive_export(state.db, owner_user_id="owner", job_id=state.job.id, folder=folder, now=NOW)
    state.db.commit()
    job = claim_next_audio_preparation_job(state.db, lease_owner_id="worker", now=NOW, lease_ttl=timedelta(minutes=10))
    state.db.commit()
    calls = []
    def upload(token, **kwargs):
        kwargs["check_cancelled"]()
        calls.append((Path(kwargs["path"]).read_bytes(), kwargs["filename"], kwargs["idempotency_key"]))
        if outcome == "failure":
            raise RuntimeError("synthetic Drive failure")
        return SimpleNamespace(file_id="file", web_view_url="https://drive.google.com/file/d/file/view")
    def process():
        return process_claimed_audio_preparation_job(state.db, job_id=job.id, lease_owner_id="worker",
            lease_generation=job.lease_generation, settings=state.settings, now=NOW,
            storage_factory=lambda settings: state.storage, runner=runner,
            drive_token_resolver=lambda *args, **kwargs: "synthetic-token", drive_uploader=upload)
    if outcome == "failure":
        with pytest.raises(AudioPreparationError):
            process()
    else:
        process()
    state.db.refresh(state.job)
    assert calls == [(b"processed-audio", "Лекция 1. Предмет.flac", state.job.id)]
    assert state.job.status is AudioPreparationStatus.completed and state.job.output_source_id is None
    assert state.storage.puts == [] and state.db.query(Source).count() == 1
    assert state.job.current_stage == ("completed" if outcome == "success" else "google_drive_export_failed")
    if outcome == "success":
        state.source.expires_at = NOW.replace(tzinfo=None)
        state.db.commit()
        assert queue_audio_drive_export(state.db, owner_user_id="owner", job_id=job.id, folder=folder, now=NOW).output_drive_file_id == "file"
        with pytest.raises(AudioPreparationServiceError, match="invalid_destination"):
            queue_audio_drive_export(state.db, owner_user_id="owner", job_id=job.id,
                folder=SimpleNamespace(id="different", name="Другая", web_view_url="https://drive.google.com/drive/folders/different"), now=NOW)
