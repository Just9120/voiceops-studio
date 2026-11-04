"""Actual child lifetime, protected profile and complete native protocol checks."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import gzip
import hashlib
import io
import os
from pathlib import Path
import sys
import threading
import time
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from local_worker import native, profile
from local_worker.process import OwnedProcess, owned_scratch, single_instance
from local_worker.protocol import APIError, MODEL, RUNTIME_VERSION, StudioClient, WorkerError, checked_job, complete_native_result, origin
from local_worker import worker


def chat():
    text = "<spk:0>Hello <spk:1>world."
    return {"model": MODEL, "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
        "transcription": {"schema_version": "1", "task": "transcribe", "transcript_origin": "llm", "language": "en",
            "duration": 1.0, "text": text, "words": [
                {"word": "Hello", "word_index": 0, "start": 0.0, "end": .5, "speaker": "spk:0"},
                {"word": "world.", "word_index": 1, "start": .5, "end": 1.0, "speaker": "spk:1"}]}}


def test_complete_native_result_preserves_text_and_only_selected_diarization():
    for diarize in (True, False):
        value = complete_native_result(chat(), duration=1, language="en", diarize=diarize)
        assert value["text"] == "Hello world."
        assert value["file"] == "prepared.wav" and value["languages"] == ["en"]
        assert [(word.get("speaker")) for word in value["words"]] == (["0", "1"] if diarize else [None, None])
    value = chat()
    value["transcription"]["words"] = value["transcription"]["words"][:1]
    assert complete_native_result(value, duration=1, language="en", diarize=False)["text"] == "Hello world."


@pytest.mark.parametrize("failure", ["length", "content_filter", "wrong_model", "wrong_language", "partial_content", "duration", "nan", "speaker", "no_speakers"])
def test_partial_wrong_or_unaligned_diarization_is_not_accepted_as_complete(failure):
    data = chat()
    if failure in {"length", "content_filter"}:
        data["choices"][0]["finish_reason"] = failure
    elif failure == "wrong_model": data["model"] = "another-model"
    elif failure == "wrong_language": data["transcription"]["language"] = "und"
    elif failure == "partial_content": data["choices"][0]["message"]["content"] = "Hello"
    elif failure == "duration": data["transcription"]["duration"] = 2
    elif failure == "nan": data["transcription"]["words"][0]["end"] = float("nan")
    elif failure == "speaker": data["transcription"]["words"][0]["speaker"] = "private name"
    else: data["transcription"]["words"] = []
    with pytest.raises(WorkerError, match="local_result_incomplete"):
        complete_native_result(data, duration=1, language="en", diarize=True)


def test_job_contract_rejects_server_supplied_commands_urls_or_unsupported_selection():
    job = {"id": str(uuid4()), "source_id": str(uuid4()), "lease_generation": 1, "size_bytes": 32044,
           "model": MODEL, "language": "ru", "diarize": True}
    assert checked_job(job)["generation"] == 1
    for changes in ({"id": "../../private"}, {"source_id": "https://other.test"}, {"size_bytes": True},
                    {"model": "cloud-model"}, {"language": "detect"}, {"lease_generation": -1}, {"diarize": "true"}):
        with pytest.raises(WorkerError, match="local_job_invalid"):
            checked_job({**job, **changes})


@pytest.mark.parametrize("value", ["http://studio.test", "https://user:secret@studio.test", "https://studio.test/another",
                                  "https://studio.test?key=value", "https://studio.test#fragment", "ftp://studio.test"])
def test_profile_cannot_retarget_a_token_to_an_insecure_or_ambiguous_origin(value):
    with pytest.raises(WorkerError, match="local_origin_invalid"):
        origin(value)


def test_redirect_never_forwards_the_studio_token_to_a_different_server():
    received = []
    class Target(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(self.headers.get("authorization")); self.send_response(200); self.end_headers()
        def log_message(self, *_): pass
    sink = ThreadingHTTPServer(("127.0.0.1", 0), Target)
    class Redirect(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(307); self.send_header("Location", f"http://127.0.0.1:{sink.server_port}/steal"); self.end_headers()
        def log_message(self, *_): pass
    redirect = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (sink, redirect)]
    for thread in threads: thread.start()
    token = "vs-local." + str(uuid4()) + "." + "s" * 43
    client = StudioClient(f"http://127.0.0.1:{redirect.server_port}", token, allow_loopback=True)
    try:
        with pytest.raises(APIError) as error:
            client.json("/heartbeat", {"runtime_status": "unknown"})
        assert error.value.status == 307 and received == []
        with pytest.raises(WorkerError, match="local_api_path_invalid"):
            client.open("https://another.test/steal")
    finally:
        for server in (sink, redirect): server.shutdown(); server.server_close()
        for thread in threads: thread.join(2)


def profile_data(tmp_path):
    return {"origin": "https://studio.test", "token": "vs-local." + str(uuid4()) + "." + "s" * 43, "verified_files": {},
            "paths": {name: str((tmp_path / name).resolve()) for name in ("runtime", "decoder", "encoder", "ffmpeg", "ffprobe")}}


def test_profile_seals_origin_paths_and_token_together_and_replacement_is_explicit(tmp_path):
    data = profile_data(tmp_path)
    target = tmp_path / "profile.json"
    sealed = {}
    def seal(raw):
        sealed[b"opaque"] = raw
        return b"opaque"
    def unseal(raw): return sealed[raw]
    profile.write_profile(target, data, seal=seal, unseal=unseal)
    outer = json.loads(target.read_bytes())
    assert set(outer) == {"format", "sealed"} and data["token"] not in target.read_text()
    assert "studio.test" not in target.read_text() and str(tmp_path) not in target.read_text()
    assert profile.read_profile(target, unseal=unseal) == data
    with pytest.raises(WorkerError, match="local_profile_already_exists"):
        profile.write_profile(target, data, seal=seal, unseal=unseal)
    changed = {**data, "origin": "https://new-studio.test"}
    profile.write_profile(target, changed, replace=True, seal=seal, unseal=unseal)
    assert profile.read_profile(target, unseal=unseal) == changed
    target.write_text("unrelated user file")
    with pytest.raises(WorkerError):
        profile.write_profile(target, changed, replace=True, seal=seal, unseal=unseal)
    assert target.read_text() == "unrelated user file"
    assert list(tmp_path.glob(".pairing-*")) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows current-user DPAPI only")
def test_real_current_user_dpapi_roundtrip_and_tamper_rejection():
    raw = b"synthetic profile secret, never a production credential"
    sealed = profile.protect(raw)
    assert raw not in sealed and profile.protect(sealed, decrypt=True) == raw
    with pytest.raises(WorkerError):
        profile.protect(sealed[:-1] + bytes([sealed[-1] ^ 1]), decrypt=True)


def test_owned_process_interrupt_kills_and_reaps_only_the_created_child_and_cleans_logs(tmp_path):
    stop = threading.Event()
    with owned_scratch(tmp_path) as directory:
        process = OwnedProcess([sys.executable, "-c", "import time; time.sleep(30)"], directory=directory, name="synthetic")
        threading.Timer(.3, stop.set).start()
        def check():
            if stop.is_set():
                raise WorkerError("synthetic_cancelled")
        with pytest.raises(WorkerError, match="synthetic_cancelled"):
            process.wait(check=check, timeout=10)
        assert process.process.poll() is not None
        assert process.stdout.closed and process.stderr.closed
    assert list(tmp_path.iterdir()) == []


def test_single_instance_prevents_concurrent_native_executions(tmp_path):
    with single_instance(tmp_path):
        with pytest.raises(WorkerError, match="local_worker_already_running"):
            with single_instance(tmp_path):
                pytest.fail("second local model instance must not start")
    with single_instance(tmp_path):
        pass


def test_native_process_configuration_is_loopback_and_does_not_expose_or_inherit_the_studio_key(tmp_path, monkeypatch):
    captured = {}
    class Child:
        def __init__(self, args, **kwargs): captured.update(args=args, **kwargs); self.process = self
        def poll(self): return None
        def check_logs(self): pass
        def close(self): pass
    monkeypatch.setattr(native, "OwnedProcess", Child)
    monkeypatch.setattr(native.NativeServer, "_request", lambda *_args, **_kwargs: {"data": [{"id": MODEL}]})
    paths = native.NativePaths(*[tmp_path / name for name in ("runtime", "decoder", "encoder", "ffmpeg", "ffprobe")])
    with native.NativeServer(paths, tmp_path) as server:
        server.start()
        args = captured["args"]
        assert args[args.index("--host") + 1] == "127.0.0.1" and "--no-ui" in args
        assert "--api-key" not in args and "--asr.salm.max_new_tokens" not in args
        assert args[args.index("--asr.salm.max_context") + 1] == "73728"
        assert captured["env"] == {"NEMO_SPEECH_HTTP_API_KEY": server.key}
    sys.path.insert(0, str(ROOT / "apps/studio-api"))
    from studio_api.nemotron_local_result import NEMOTRON_MODEL
    assert MODEL == NEMOTRON_MODEL


def test_child_environment_has_no_studio_or_provider_credentials(monkeypatch):
    from local_worker.process import child_env
    monkeypatch.setenv("STUDIO_SECRET", "synthetic-secret")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "synthetic-provider-key")
    monkeypatch.setenv("NEMO_SPEECH_HTTP_API_KEY", "unrelated-runtime-key")
    value = child_env({"NEMO_SPEECH_HTTP_API_KEY": "own-ephemeral-key"})
    assert "STUDIO_SECRET" not in value and "ELEVENLABS_API_KEY" not in value
    assert value["NEMO_SPEECH_HTTP_API_KEY"] == "own-ephemeral-key"


def test_idle_native_exit_withdraws_readiness_before_claiming_another_job(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace

    state = {"dead": False, "claims": 0, "closed": False, "statuses": []}
    class Client:
        def heartbeat(self, status): state["statuses"].append(status)
        def json(self, path):
            assert path == "/claim"
            state["claims"] += 1
            state["dead"] = True  # Native child exits while the PC is idle.
            return {"job": None}
    class Server:
        def __init__(self, *_): self.process = None
        def __enter__(self): return self
        def __exit__(self, *_): state["closed"] = True
        def start(self, _check):
            self.process = SimpleNamespace(process=SimpleNamespace(poll=lambda: 1 if state["dead"] else None))

    pulse = SimpleNamespace(status="loading_model", check=lambda: None)
    monkeypatch.setattr(worker, "StudioClient", lambda *_: Client())
    monkeypatch.setattr(worker, "DevicePulse", lambda *_: nullcontext(pulse))
    monkeypatch.setattr(worker, "NativeServer", Server)
    monkeypatch.setattr(worker, "verify_installation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker.NativePaths, "from_dict", lambda *_: None)
    monkeypatch.setattr(worker.time, "sleep", lambda *_: None)
    with pytest.raises(WorkerError, match="local_runtime_unavailable"):
        worker.run({"origin": "https://example.invalid", "token": "synthetic", "paths": {}, "verified_files": {}},
                   root=tmp_path, notice=lambda *_: None)
    assert state["claims"] == 1 and state["closed"]
    assert state["statuses"] == ["loading_model", "ready", "runtime_error"]
    assert pulse.status == "runtime_error"


def test_verified_weight_cache_reuses_only_unchanged_identity_and_executable_is_always_hashed(tmp_path, monkeypatch):
    paths = native.NativePaths(*[tmp_path / name for name in ("runtime", "decoder", "encoder", "ffmpeg", "ffprobe")])
    for path in (paths.runtime, paths.decoder, paths.encoder, paths.ffmpeg, paths.ffprobe):
        path.write_bytes(b"synthetic")
    digest = hashlib.sha256(b"synthetic").hexdigest()
    monkeypatch.setattr(native, "PINNED_FILES", {name: (9, digest) for name in ("runtime", "decoder", "encoder")})
    hashes = []
    original = native.file_sha256
    def counted(path, check):
        hashes.append(path.name)
        return original(path, check)
    monkeypatch.setattr(native, "file_sha256", counted)
    proof = native.verify_installation(paths)
    assert hashes == ["runtime", "decoder", "encoder"]
    hashes.clear()
    native.verify_installation(paths, verified_files=proof)
    assert hashes == ["runtime"]
    paths.decoder.write_bytes(b"corrupted")
    with pytest.raises(WorkerError, match="local_model_unavailable"):
        native.verify_installation(paths, verified_files=proof)


def test_new_pairing_never_overwrites_a_concurrently_created_file(tmp_path):
    target = tmp_path / "profile.json"
    def race(_):
        target.write_text("unrelated concurrent data")
        return b"sealed"
    with pytest.raises(WorkerError, match="local_profile_changed"):
        profile.write_profile(target, profile_data(tmp_path), seal=race)
    assert target.read_text() == "unrelated concurrent data" and list(tmp_path.glob(".pairing-*")) == []


class Body(io.BytesIO):
    def __init__(self, raw, headers=None):
        super().__init__(raw)
        self.headers = headers or {}


class SyntheticStudio:
    def __init__(self, *, cancel=False, mismatch=False, ambiguous=False):
        self.raw = b"synthetic input bytes"
        self.sha = hashlib.sha256(self.raw).hexdigest()
        self.calls = []
        self.uploads = []
        self.cancel, self.mismatch, self.ambiguous = cancel, mismatch, ambiguous

    def json(self, path, payload):
        self.calls.append((path, payload))
        if path.endswith("/heartbeat"):
            return {"cancelled": self.cancel}
        if path.endswith("/prepare"):
            return {"source_sha256": self.sha, "clip_start_seconds": 0, "prepared_duration_seconds": 1.0}
        return {"failed": True}

    def open(self, path, **kwargs):
        self.calls.append((path, kwargs))
        if "/source?" in path:
            return Body(self.raw, {"X-VoiceOps-Input-SHA256": "a" * 64 if self.mismatch else self.sha,
                "Content-Length": str(len(self.raw))})
        if path.endswith("/result"):
            self.uploads.append(kwargs["body"])
            if self.ambiguous and len(self.uploads) == 1:
                raise APIError(0)
            return Body(b'{"accepted":true,"already_accepted":false}')
        pytest.fail("unexpected synthetic protocol path")


def synthetic_job(client):
    return {"id": str(uuid4()), "generation": 1, "size_bytes": len(client.raw), "language": "en", "diarize": False, "progress": None}


def fake_local_media(monkeypatch):
    monkeypatch.setattr(worker, "probe_audio", lambda *_: 1.0)
    def prepare(paths, source, output, **kwargs):
        kwargs["check"]()
        output.write_bytes(source.read_bytes())
        kwargs["progress"](1, 1)
        return 1.0
    monkeypatch.setattr(worker, "prepare_audio", prepare)


def test_companion_runs_only_one_local_inference_then_uploads_full_result_and_removes_files(tmp_path, monkeypatch):
    fake_local_media(monkeypatch)
    client = SyntheticStudio()
    class Local:
        calls = 0
        def transcribe(self, path, **kwargs):
            self.calls += 1
            kwargs["check"]()
            assert path.read_bytes() == client.raw
            return complete_native_result(chat(), duration=1, language="en", diarize=False)
    server = Local()
    assert worker.run_job(client, synthetic_job(client), None, server, tmp_path)
    assert server.calls == 1 and len(client.uploads) == 1
    envelope = json.loads(gzip.decompress(client.uploads[0]))
    assert envelope["source_sha256"] == client.sha and envelope["result"]["text"] == "Hello world."
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure", ["cancelled", "bad_checksum", "restarted"])
def test_companion_does_not_run_native_or_leave_files_after_cancel_changed_bytes_or_restart(tmp_path, monkeypatch, failure):
    fake_local_media(monkeypatch)
    client = SyntheticStudio(cancel=failure == "cancelled", mismatch=failure == "bad_checksum")
    job = synthetic_job(client)
    class Never:
        def transcribe(self, *_args, **_kwargs): pytest.fail("native inference must not start")
    if failure == "restarted":
        job["progress"] = {"stage": "local_transcription", "sequence": 5}
        assert worker.run_job(client, job, None, Never(), tmp_path) is False
        assert client.calls[0][1]["reason"] == "local_worker_interrupted"
    else:
        with pytest.raises(WorkerError):
            worker.run_job(client, job, None, Never(), tmp_path)
    assert client.uploads == [] and list(tmp_path.iterdir()) == []


def test_lost_commit_reply_reuses_exact_result_even_after_handoff_fences_heartbeat(monkeypatch):
    from local_worker.protocol import Stopped
    client = SyntheticStudio(ambiguous=True)
    class Pulse:
        failure = Stopped("local_job_lease_changed")
        def phase(self, *_): pass
        def global_check(self): pass
    monkeypatch.setattr(worker.time, "sleep", lambda *_: None)
    worker.submit_result(client, synthetic_job(client), {"text": "synthetic"}, client.sha, Pulse())
    assert len(client.uploads) == 2 and client.uploads[0] == client.uploads[1]


def test_stale_cleanup_removes_only_recognized_dead_runs_and_preserves_active_or_unknown_data(tmp_path, monkeypatch):
    from local_worker import process
    def folder(name, pid):
        path = tmp_path / name
        path.mkdir()
        (path / ".voiceops-owner.json").write_text(json.dumps({"format": "voiceops-local-scratch-v1", "directory": name, "pid": pid}))
        (path / "native.stdout").write_text("synthetic diagnostics")
        return path
    dead = folder("run-dead", 999999)
    active = folder("run-active", os.getpid())
    changed = folder("run-with-user-data", 999999)
    (changed / "keep.txt").write_text("unknown user data")
    arbitrary = tmp_path / "another-project"
    arbitrary.mkdir()
    monkeypatch.setattr(process, "_pid_alive", lambda pid: pid == os.getpid())
    result = process.cleanup_stale_scratch(tmp_path)
    assert result == {"removed": 1, "preserved": 3}
    assert not dead.exists() and active.exists() and arbitrary.exists()
    assert (changed / "keep.txt").read_text() == "unknown user data"


def test_truncated_commit_reply_is_reconciled_by_reusing_the_same_complete_upload(monkeypatch):
    import http.client
    class Truncated(Body):
        def read(self, *_): raise http.client.IncompleteRead(b"{", 4)
    class Studio(SyntheticStudio):
        def open(self, path, **kwargs):
            response = super().open(path, **kwargs)
            return Truncated(b"") if len(self.uploads) == 1 else response
    class Pulse:
        failure = None
        def phase(self, *_): pass
        def global_check(self): pass
    client = Studio()
    monkeypatch.setattr(worker.time, "sleep", lambda *_: None)
    worker.submit_result(client, synthetic_job(client), {"text": "complete"}, client.sha, Pulse())
    assert len(client.uploads) == 2 and client.uploads[0] == client.uploads[1]
