"""One local execution at a time; liveness never fabricates model progress."""
import gzip
from contextlib import ExitStack, nullcontext
import hashlib
import http.client
import json
from pathlib import Path
import re
import shutil
import threading
import time

from .native import NativePaths, NativeServer, model_scratch_root, prepare_audio, probe_audio, verify_installation
from .parakeet import transcribe_parakeet
from .process import owned_scratch, recovered_workspace, single_instance
from .model_profiles import INITIAL_MODEL_REVISIONS
from .protocol import APIError, MAX_RESULT_BYTES, MODEL, PARAKEET_MODEL, Stopped, StudioClient, WorkerError, checked_job, response_bytes


class DevicePulse:
    def __init__(self, client, check_stop=lambda: None):
        self.client = client
        self.check_stop = check_stop
        self.status = "loading_model"
        self.failure = None
        self.closed = threading.Event()
        self.thread = None
        self.last_success = time.monotonic()

    def _loop(self):
        while not self.closed.is_set():
            try:
                self.client.heartbeat(self.status)
                self.last_success = time.monotonic()
            except APIError as error:
                if error.status in (401, 403):
                    self.failure = Stopped("local_device_unauthorized")
                    return
            except WorkerError:
                self.failure = Stopped("local_response_invalid")
                return
            if self.closed.wait(15):
                return

    def check(self):
        self.check_stop()
        if self.failure is not None:
            raise self.failure
        if time.monotonic() - self.last_success > 60:
            raise Stopped("local_connection_lost")

    def __enter__(self):
        self.thread = threading.Thread(target=self._loop, name="voiceops-device-heartbeat", daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.closed.set()
        self.thread.join(25)


class JobPulse:
    def __init__(self, client, job, global_check=lambda: None):
        self.client, self.job, self.global_check = client, job, global_check
        self.failure = None
        self.lock = threading.Lock()
        self.closed = threading.Event()
        self.sequence = 1
        self.value = ("source_download", None, None, None)
        self.thread = None
        self.last_success = time.monotonic()

    def phase(self, stage, completed=None, total=None, unit=None):
        value = stage, completed, total, unit
        with self.lock:
            if value != self.value:
                self.value = value
                self.sequence += 1

    def _send(self):
        with self.lock:
            stage, completed, total, unit = self.value
            data = {"generation": self.job["generation"], "sequence": self.sequence, "stage": stage,
                    "completed": completed, "total": total, "unit": unit}
        reply = self.client.json(f"/jobs/{self.job['id']}/heartbeat", data)
        if not isinstance(reply, dict) or type(reply.get("cancelled")) is not bool:
            raise WorkerError("local_response_invalid")
        if reply["cancelled"]:
            raise Stopped("local_job_cancelled")
        self.last_success = time.monotonic()

    def _loop(self):
        while not self.closed.wait(2):
            try:
                self._send()
            except APIError as error:
                if error.status in (401, 403):
                    self.failure = Stopped("local_device_unauthorized")
                    return
                if error.status in (404, 409):
                    self.failure = Stopped("local_job_lease_changed")
                    return
            except WorkerError as error:
                self.failure = error
                return

    def check(self):
        self.global_check()
        if self.failure is not None:
            raise self.failure
        if time.monotonic() - self.last_success > 60:
            raise Stopped("local_connection_lost")

    def __enter__(self):
        self._send()  # No native process/file work starts before this authority check.
        self.thread = threading.Thread(target=self._loop, name="voiceops-job-heartbeat", daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.closed.set()
        if self.thread is not None:
            self.thread.join(25)


def download_source(client, job, destination, pulse):
    digest = hashlib.sha256()
    count = 0
    try:
        with client.open(f"/jobs/{job['id']}/source?generation={job['generation']}", method="GET", timeout=60) as response:
            expected = response.headers.get("X-VoiceOps-Input-SHA256", "")
            if re.fullmatch(r"[a-f0-9]{64}", expected) is None or int(response.headers.get("Content-Length", "-1")) != job["size_bytes"]:
                raise WorkerError("local_input_unavailable")
            with destination.open("xb") as stream:
                while chunk := response.read(1024 * 1024):
                    pulse.check()
                    count += len(chunk)
                    if count > job["size_bytes"]:
                        raise WorkerError("local_input_unavailable")
                    stream.write(chunk); digest.update(chunk)
                    pulse.phase("source_download", count, job["size_bytes"], "bytes")
        if count != job["size_bytes"] or digest.hexdigest() != expected:
            raise WorkerError("local_input_unavailable")
        return expected
    except (OSError, ValueError, http.client.HTTPException):
        raise WorkerError("local_input_unavailable") from None


def submit_result(client, job, result, sha, pulse):
    envelope = {"generation": job["generation"], "source_sha256": sha, "result": result}
    if "model_revision" in job:
        envelope.update(model=job["model"], model_revision=job["model_revision"])
    raw = json.dumps(envelope, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    if len(raw) > MAX_RESULT_BYTES + 4096:
        raise WorkerError("local_result_invalid")
    body = gzip.compress(raw, mtime=0)
    if len(body) > 4 * 1024 * 1024:
        raise WorkerError("local_result_invalid")
    pulse.phase("local_result_upload")
    # An ambiguous commit response is retried with the exact same full body.
    # A heartbeat may already be fenced by the accepted export handoff; that
    # alone must not suppress this readback/idempotent acknowledgement.
    for attempt in range(3):
        try:
            with client.open(f"/jobs/{job['id']}/result", body=body, content_type="application/gzip", timeout=30) as response:
                from .protocol import strict_json
                reply = strict_json(response_bytes(response, 65536))
            if not isinstance(reply, dict) or reply.get("accepted") is not True:
                raise WorkerError("local_response_invalid")
            return reply
        except APIError as error:
            if error.status not in (0, 429, 502, 503, 504) or attempt == 2:
                raise
            pulse.global_check()
            if isinstance(pulse.failure, Stopped) and pulse.failure.code in {"local_device_unauthorized", "local_job_cancelled"}:
                raise pulse.failure
            time.sleep(2)
    raise WorkerError("local_result_persistence_unavailable")


def run_job(client, job, paths, server, directory, *, global_check=lambda: None):
    if job["progress"] is not None:
        # A restarted companion cannot safely reset a live lease's measured
        # stages or duplicate its orphaned compute. Owner can explicitly retry.
        client.json(f"/jobs/{job['id']}/failure", {"generation": job["generation"], "reason": "local_worker_interrupted"})
        return False
    if shutil.disk_usage(directory).free < job["size_bytes"] + 512 * 1024 * 1024:
        raise WorkerError("local_disk_space_unavailable")
    with owned_scratch(directory, prefix="job-") as scratch, JobPulse(client, job, global_check) as pulse:
        source = scratch / "input.media"
        sha = download_source(client, job, source, pulse)
        pulse.phase("media_processing")
        duration = probe_audio(paths, source, scratch, pulse.check)
        plan = client.json(f"/jobs/{job['id']}/prepare", {"generation": job["generation"],
            "source_sha256": sha, "source_duration_seconds": duration})
        try:
            if plan["source_sha256"] != sha or type(plan["prepared_duration_seconds"]) not in (int, float):
                raise ValueError()
            start, selected = plan["clip_start_seconds"], plan["prepared_duration_seconds"]
        except (KeyError, TypeError, ValueError):
            raise WorkerError("local_response_invalid") from None
        prepared = scratch / "prepared.wav"
        measured = prepare_audio(paths, source, prepared, start=start, duration=selected, directory=scratch, check=pulse.check,
            progress=lambda done, total: pulse.phase("media_processing", done, total, "seconds"))
        pulse.phase("local_transcription")
        arguments = {"duration": measured, "language": job["language"], "diarize": job["diarize"], "check": pulse.check}
        if server is None:
            result = transcribe_parakeet(paths.runtime, paths.decoder, prepared, **arguments)
        else:
            result = server.transcribe(prepared, **arguments)
        pulse.check()
        submit_result(client, job, result, sha, pulse)
        return True


def run(profile, *, root, notice=print, check_stop=lambda: None):
    model = profile.get("model", MODEL)
    revision = profile.get("model_revision", INITIAL_MODEL_REVISIONS.get(model))
    parakeet = model == PARAKEET_MODEL
    client = StudioClient(profile["origin"], profile["token"], model=model, revision=revision)
    with single_instance(root), ExitStack() as workspace, DevicePulse(client, check_stop) as device:
        try:
            paths = NativePaths.from_dict(profile["paths"], model=model)
            verify_installation(paths, check=device.check, verified_files=profile["verified_files"], model=model, revision=revision)
        except Stopped:
            raise
        except WorkerError as error:
            client.heartbeat("model_missing" if error.code == "local_model_unavailable" else "runtime_missing")
            raise
        directory, cleanup = workspace.enter_context(recovered_workspace(model_scratch_root(root, paths)))
        if cleanup["preserved"]:
            notice("Некоторые временные папки заняты или содержат неизвестные файлы и сохранены для проверки.")
        with (nullcontext() if parakeet else NativeServer(paths, directory)) as server:
            if parakeet:
                device.status = "ready"
                client.heartbeat("ready")
                notice("Модель Parakeet проверена. Ожидаю задачи Studio.")
            while True:
                device.check()
                if server is not None and server.process is not None and server.process.process.poll() is not None:
                    device.status = "runtime_error"
                    client.heartbeat("runtime_error")
                    raise WorkerError("local_runtime_unavailable")
                if server is not None and server.process is None:
                    device.status = "loading_model"
                    client.heartbeat("loading_model")
                    notice("Загрузка локальной модели…")
                    try:
                        server.start(device.check)
                    except Stopped:
                        raise
                    except WorkerError as error:
                        device.status = "runtime_error"
                        client.heartbeat("runtime_error")
                        raise
                    device.status = "ready"
                    client.heartbeat("ready")
                    notice("Локальный обработчик готов. Ожидаю задачи Studio. Остановка: Ctrl+C.")
                try:
                    reply = client.json("/claim")
                except APIError as error:
                    if error.status in {0, 429, 502, 503, 504} or error.code == "local_device_not_ready":
                        device.check()
                        time.sleep(3)
                        continue
                    raise
                if not isinstance(reply, dict) or "job" not in reply:
                    raise WorkerError("local_response_invalid")
                if reply["job"] is None:
                    time.sleep(3)
                    continue
                job = checked_job(reply["job"], model=model, revision=revision)
                client.job_trace = (job["id"], job["trace_id"]) if job["trace_id"] is not None else None
                notice("Распознаю запись, назначенную в Studio…")
                try:
                    done = run_job(client, job, paths, server, directory, global_check=device.check)
                    notice("Результат передан Studio для сохранения документа." if done else "Прерванная задача сохранена. Повторите её в Studio.")
                except Stopped as error:
                    if server is not None:
                        server.close()
                    if error.code == "local_worker_interrupted":
                        try:
                            client.json(f"/jobs/{job['id']}/failure", {"generation": job["generation"],
                                        "reason": "local_worker_interrupted"})
                        except APIError:
                            pass  # A superseding lease or accepted result already has authority.
                        raise
                    if error.code in {"local_device_unauthorized", "local_connection_lost"}:
                        raise
                    notice("Локальная задача остановлена. Состояние сохранено в Studio.")
                except WorkerError as error:
                    try:
                        client.json(f"/jobs/{job['id']}/failure", {"generation": job["generation"], "reason":
                            "local_input_unavailable" if error.code in {"local_input_unavailable", "local_disk_space_unavailable"}
                            else "local_result_invalid" if error.code in {"local_result_incomplete", "local_result_invalid"}
                            else "local_runtime_unavailable" if error.code == "local_runtime_unavailable" else "local_processing_failed"})
                    except APIError:
                        pass  # Owner cancellation/accepted result/expired lease already has authority.
                    notice("Не удалось завершить локальную задачу. Проверьте её состояние в Studio.")
                    if server is not None and server.process is not None and server.process.process.poll() is not None:
                        server.close()
                finally:
                    client.job_trace = None
