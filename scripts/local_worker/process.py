"""Contain and reap only native children created by this companion."""
from contextlib import contextmanager
import ctypes
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time

from .protocol import WorkerError


def memory_headroom():
    """Keep the owner's desktop responsive while a large native model loads."""
    if os.name != "nt":
        return
    class Memory(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong) for name in ("total", "available", "page_total", "page_available",
                                                   "virtual_total", "virtual_available", "extended")]
    state = Memory()
    state.length = ctypes.sizeof(state)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)) or state.available < 4 * 1024**3:
        raise WorkerError("local_memory_unavailable")


class WindowsJob:
    def __init__(self, process):
        self.handle = None
        if os.name != "nt":
            return
        from ctypes import wintypes as wt
        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64), ("flags", wt.DWORD),
                ("min_set", ctypes.c_size_t), ("max_set", ctypes.c_size_t), ("active_limit", wt.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", wt.DWORD), ("scheduling", wt.DWORD)]
        class Counters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]
        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", Counters), ("process_limit", ctypes.c_size_t),
                ("job_limit", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
        kernel.CreateJobObjectW.restype = wt.HANDLE
        kernel.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
        kernel.CloseHandle.argtypes = [wt.HANDLE]
        handle = kernel.CreateJobObjectW(None, None)
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if (not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits))
                or not kernel.AssignProcessToJobObject(handle, int(process._handle))):
            if handle:
                kernel.CloseHandle(handle)
            raise WorkerError("local_process_containment_unavailable")
        self.handle, self.kernel = handle, kernel

    def close(self):
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def child_env(extra=None):
    # No inherited provider keys, Studio machine token, or unrelated native
    # model configuration is passed to model/FFmpeg subprocesses.
    allowed = ("SYSTEMROOT", "WINDIR", "SystemRoot", "SystemDrive", "TEMP", "TMP", "PATH", "LANG", "LC_ALL")
    return {**{key: os.environ[key] for key in allowed if key in os.environ}, **(extra or {})}


class OwnedProcess:
    def __init__(self, args, *, directory, name, env=None):
        self.stdout_path = directory / (name + ".stdout")
        self.stderr_path = directory / (name + ".stderr")
        self.stdout = self.stderr = None
        self.process = None
        self.job = None
        try:
            self.stdout = self.stdout_path.open("wb")
            self.stderr = self.stderr_path.open("wb")
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=self.stdout, stderr=self.stderr,
                shell=False, cwd=directory, env=child_env(env), creationflags=flags, start_new_session=os.name != "nt")
            self.job = WindowsJob(self.process)
        except BaseException:
            self.close()
            raise

    def check_logs(self):
        if any(path.stat().st_size > 8 * 1024 * 1024 for path in (self.stdout_path, self.stderr_path)):
            raise WorkerError("local_runtime_log_limit")

    def wait(self, *, check=lambda: None, timeout=300, progress=None):
        deadline = time.monotonic() + timeout
        try:
            while self.process.poll() is None:
                check()
                self.check_logs()
                if progress:
                    progress(self.stdout_path)
                if time.monotonic() >= deadline:
                    raise WorkerError("local_process_timeout")
                time.sleep(.2)
            if self.process.returncode != 0:
                raise WorkerError("local_process_failed")
            check()
            return self.stdout_path
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.process is not None and self.process.poll() is None:
            if self.job is not None and self.job.handle is not None:
                self.job.close()
            elif os.name != "nt":
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            else:
                self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    os.killpg(self.process.pid, signal.SIGKILL)
                else:
                    self.process.kill()
                self.process.wait(timeout=5)
        if self.job is not None:
            self.job.close()
        if self.stdout is not None:
            self.stdout.close()
        if self.stderr is not None:
            self.stderr.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


@contextmanager
def owned_scratch(root, *, prefix="run-"):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    created = Path(tempfile.mkdtemp(prefix=prefix, dir=root))
    try:
        (created / ".voiceops-owner.json").write_text(json.dumps({"format": "voiceops-local-scratch-v1",
            "directory": created.name, "pid": os.getpid()}), encoding="utf-8")
        yield created
    finally:
        # Verify the final resolved deletion target before recursive cleanup.
        target = created.resolve()
        if target.parent != root or target == root or not target.name.startswith(prefix) or created.is_symlink():
            raise WorkerError("local_cleanup_target_changed")
        if created.exists():
            shutil.rmtree(created)


def _pid_alive(pid):
    if os.name == "nt":
        from ctypes import wintypes as wt
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        kernel.OpenProcess.restype = wt.HANDLE
        kernel.CloseHandle.argtypes = [wt.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if handle:
            kernel.CloseHandle(handle)
            return True
        return ctypes.get_last_error() != 87  # Access denied/unknown is preserved.
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def cleanup_stale_scratch(root):
    """Only recognized inactive run trees, never weights or arbitrary directories."""
    root = Path(root).resolve()
    if not root.exists():
        return {"removed": 0, "preserved": 0}
    allowed_files = {".voiceops-owner.json", "input.media", "prepared.wav", "native.stdout", "native.stderr",
                     "probe.stdout", "probe.stderr", "prepare.stdout", "prepare.stderr"}
    def recognized(directory, prefix):
        if directory.is_symlink() or not directory.is_dir() or not directory.name.startswith(prefix):
            return False
        marker = directory / ".voiceops-owner.json"
        if marker.is_symlink() or not marker.is_file() or marker.stat().st_size > 4096:
            return False
        try:
            with marker.open("rb") as stream:
                data = json.loads(stream.read(4097))
            if (set(data) != {"format", "directory", "pid"} or data["format"] != "voiceops-local-scratch-v1"
                    or data["directory"] != directory.name or type(data["pid"]) is not int
                    or not 0 < data["pid"] <= 2147483647 or _pid_alive(data["pid"])):
                return False
            for path in directory.iterdir():
                if path.is_symlink():
                    return False
                if path.is_dir():
                    if prefix != "run-" or not recognized(path, "job-"):
                        return False
                elif not path.is_file() or path.name not in allowed_files:
                    return False
            return True
        except (OSError, ValueError, TypeError):
            return False
    removed = preserved = 0
    for path in root.iterdir():
        try:
            # Resolve again immediately before the recursive delete.
            if recognized(path, "run-") and path.resolve().parent == root and not path.is_symlink():
                shutil.rmtree(path)
                removed += 1
            else:
                preserved += 1
        except OSError:
            preserved += 1
    return {"removed": removed, "preserved": preserved}


@contextmanager
def recovered_workspace(root):
    result = cleanup_stale_scratch(root)
    with owned_scratch(root) as directory:
        yield directory, result


@contextmanager
def single_instance(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "worker.lock").open("a+b") as stream:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                if stream.read(1) == b"":
                    stream.write(b"0"); stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise WorkerError("local_worker_already_running") from None
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise WorkerError("local_worker_already_running") from None
        yield
