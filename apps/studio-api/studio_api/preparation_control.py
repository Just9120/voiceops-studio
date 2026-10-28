"""Cooperative cancellation before STT; only the owned media child is stopped."""
import subprocess
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic

from .worker_progress import touch_worker_progress, worker_phase
from .work_progress import report_work

_check = ContextVar("preparation_check", default=None)


class PreparationInterrupted(RuntimeError):
    pass


@contextmanager
def preparation_control(check):
    token = _check.set(check)
    try:
        yield
    finally:
        _check.reset(token)


def check_preparation_control():
    touch_worker_progress()
    check = _check.get()
    if check is not None:
        try:
            check()
        except Exception as exc:
            raise PreparationInterrupted("preparation_authority_changed") from exc


def controlled_runner(runner):
    def run(command, **kwargs):
        check_preparation_control()
        timeout = kwargs.get("timeout", 1800)
        with worker_phase("media_preparation", timeout + 30):
            if runner is not subprocess.run or _check.get() is None:
                result = runner(command, **kwargs)
                check_preparation_control()
                return result
            if str(command[0]).lower().endswith(("ffmpeg", "ffmpeg.exe")):
                return _measured_ffmpeg(command, kwargs, timeout)
            options = dict(kwargs)
            options.pop("timeout", None)
            check_exit = options.pop("check", False)
            if options.pop("capture_output", False):
                options.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            child = subprocess.Popen(command, **options)
            deadline = monotonic() + timeout
            try:
                while True:
                    check_preparation_control()
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, timeout)
                    try:
                        stdout, stderr = child.communicate(timeout=min(0.25, remaining))
                        break
                    except subprocess.TimeoutExpired:
                        continue
                check_preparation_control()
                if check_exit and child.returncode:
                    raise subprocess.CalledProcessError(child.returncode, command, output=stdout, stderr=stderr)
                return subprocess.CompletedProcess(command, child.returncode, stdout, stderr)
            finally:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=2)
                for stream in (child.stdout, child.stderr):
                    if stream is not None:
                        stream.close()
    return run


def _measured_ffmpeg(command, kwargs, timeout):
    """Drain both pipes with bounded buffers; persist on the controlling thread."""
    measured = [str(command[0]), "-nostats", "-stats_period", "1", "-progress", "pipe:1", *command[1:]]
    state = {"seconds": 0.0, "stderr": b"", "failed": False}
    lock = threading.Lock()
    child = subprocess.Popen(measured, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    def read_progress():
        try:
            while line := child.stdout.readline(1024):
                if line.startswith(b"out_time_us="):
                    try:
                        seconds = int(line.split(b"=", 1)[1]) / 1_000_000
                        if seconds >= 0:
                            with lock:
                                state["seconds"] = seconds
                    except ValueError:
                        pass
        except (OSError, ValueError):
            state["failed"] = True
    def read_errors():
        try:
            while chunk := child.stderr.read(4096):
                state["stderr"] = (state["stderr"] + chunk)[-16384:]
        except (OSError, ValueError):
            state["failed"] = True
    readers = [threading.Thread(target=read_progress, daemon=True), threading.Thread(target=read_errors, daemon=True)]
    for reader in readers:
        reader.start()
    deadline = monotonic() + timeout
    try:
        while child.poll() is None:
            check_preparation_control()
            with lock:
                seconds = state["seconds"]
            report_work("media_processing", seconds, None, "seconds")
            if monotonic() >= deadline:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                child.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                pass
        for reader in readers:
            reader.join(timeout=2)
        if state["failed"] or any(reader.is_alive() for reader in readers):
            raise OSError("media_progress_pipe_failed")
        check_preparation_control()
        report_work("media_processing", state["seconds"], None, "seconds")
        stderr = state["stderr"]
        if kwargs.get("text") or kwargs.get("encoding") or kwargs.get("universal_newlines"):
            stderr = stderr.decode(kwargs.get("encoding") or "utf-8", errors="replace")
        if kwargs.get("check") and child.returncode:
            raise subprocess.CalledProcessError(child.returncode, command, stderr=stderr)
        return subprocess.CompletedProcess(command, child.returncode, "" if isinstance(stderr, str) else b"", stderr)
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
        for reader in readers:
            reader.join(timeout=2)
        child.stdout.close()
        child.stderr.close()
