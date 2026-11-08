"""Install and qualify the Batch dependency lock in a disposable Colab venv."""

from __future__ import annotations

import os
import platform
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import venv


ROOT = Path(__file__).resolve().parents[1]
SMOKE = """
from pathlib import Path
import sys
from unittest.mock import patch

import googleapiclient.discovery
import requests
from google.auth.credentials import AnonymousCredentials
from googleapiclient.discovery import build

assert sys.prefix != sys.base_prefix
for module in (googleapiclient.discovery, requests):
    assert Path(module.__file__).is_relative_to(Path(sys.prefix))
with patch("socket.socket.connect", side_effect=AssertionError("Unexpected network access")):
    drive = build("drive", "v3", credentials=AnonymousCredentials())
    docs = build("docs", "v1", credentials=AnonymousCredentials())
    assert drive.files().get(fileId="synthetic", fields="id").method == "GET"
    assert docs.documents().batchUpdate(documentId="synthetic", body={"requests": []}).method == "POST"
    request = requests.Request(
        "POST", "https://example.test/stt",
        data=[("keyterms", "first"), ("keyterms", "second")],
        files={"file": ("test.wav", b"synthetic", "audio/wav")},
    ).prepare()
    assert b"first" in request.body and b"second" in request.body
"""


def colab_lock_name() -> str:
    version = sys.version_info[:2]
    if (
        platform.system() != "Linux"
        or platform.machine() != "x86_64"
        or platform.python_implementation() != "CPython"
        or version not in {(3, 12), (3, 13)}
    ):
        raise SystemExit("Colab dependency qualification requires Linux x86_64 with CPython 3.12 or 3.13.")
    return f"requirements-colab-linux-x64-py{version[0]}.{version[1]}.lock"


def install_locked_colab_python(lock: Path, directory: Path) -> Path:
    # Hosted Colab supplies pip in the kernel but may omit ensurepip.
    venv.EnvBuilder(with_pip=False).create(directory)
    interpreter = directory / "bin" / "python"
    # pip relaunches under the target interpreter without inheriting Python's -I.
    environment = {
        name: value for name, value in os.environ.items()
        if not name.startswith("PYTHON") and name != "_PIP_RUNNING_IN_SUBPROCESS"
    }
    environment["PIP_CONFIG_FILE"] = os.devnull
    pip = [
        sys.executable, "-I", "-m", "pip", "--python", str(interpreter),
        "--isolated", "--disable-pip-version-check",
    ]
    subprocess.run(
        [
            *pip, "install", "--no-input", "--require-hashes", "--only-binary=:all:",
            "--index-url", "https://pypi.org/simple", "-r", str(lock),
        ],
        env=environment, check=True, timeout=300,
    )
    subprocess.run([*pip, "check"], env=environment, check=True, timeout=30)
    return interpreter


def main() -> None:
    lock = ROOT / colab_lock_name()
    with TemporaryDirectory(prefix="voiceops-colab-dependencies-") as directory:
        interpreter = install_locked_colab_python(lock, Path(directory))
        subprocess.run([str(interpreter), "-I", "-c", SMOKE], check=True, timeout=30)
    print(f"Colab isolated dependency qualification passed for {lock.name}.")


if __name__ == "__main__":
    main()
