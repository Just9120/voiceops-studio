#!/usr/bin/env python3
"""Lightweight repository hygiene checks for CI."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = ROOT / "notebooks" / "elevenlabs_api_colab.ipynb"
REALTIME_NOTEBOOK_PATH = ROOT / "notebooks" / "elevenlabs_realtime_colab.ipynb"
CANONICAL_PY = ROOT / "elevenlabs_api.py"
REALTIME_PY = ROOT / "elevenlabs_realtime.py"


class CheckError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise CheckError(message)


def check_notebooks() -> None:
    notebook_paths = sorted(ROOT.rglob("*.ipynb"))
    if not notebook_paths:
        print("[ci-checks] No notebooks found; skipping notebook hygiene checks.")
        return

    for path in notebook_paths:
        rel = path.relative_to(ROOT)
        try:
            notebook = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail(f"Notebook is not valid JSON: {rel} ({exc})")

        for idx, cell in enumerate(notebook.get("cells", [])):
            outputs = cell.get("outputs", [])
            exec_count = cell.get("execution_count")
            if outputs:
                fail(f"Notebook has committed outputs: {rel} cell #{idx}")
            if exec_count is not None:
                fail(f"Notebook has execution_count set: {rel} cell #{idx} -> {exec_count}")

    print(f"[ci-checks] Notebook JSON + clean output checks passed ({len(notebook_paths)} file(s)).")


def check_colab_release_refs() -> None:
    git = shutil.which("git")
    if git is None:
        print("[ci-checks] Colab release ancestry requires Git; skipped.")
        return
    checkout = subprocess.run(
        [git, "rev-parse", "--is-shallow-repository"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if checkout.returncode or checkout.stdout.strip() != "false":
        print("[ci-checks] Colab release ancestry requires full Git history; skipped.")
        return

    for path in (NOTEBOOK_PATH, REALTIME_NOTEBOOK_PATH):
        notebook = json.loads(path.read_text(encoding="utf-8"))
        source = "\n".join("".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code")
        refs = re.findall(r'^GITHUB_REF\s*=\s*["\']([0-9a-f]{40})["\']', source, re.MULTILINE)
        if len(refs) != 1:
            fail(f"{path.name} must pin exactly one full Git commit.")
        ancestor = subprocess.run(
            [git, "merge-base", "--is-ancestor", refs[0], "HEAD"],
            cwd=ROOT, capture_output=True,
        )
        if ancestor.returncode:
            fail(f"{path.name} release {refs[0]} is outside the checked-out branch history.")
    print("[ci-checks] Colab release ancestry checks passed.")


def check_launcher_notebook() -> None:
    if not NOTEBOOK_PATH.exists():
        fail("Required launcher notebook missing: notebooks/elevenlabs_api_colab.ipynb")

    nb = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    source_text = "\n".join(
        "".join(cell.get("source", [])) for cell in nb.get("cells", []) if cell.get("cell_type") == "code"
    )

    size = NOTEBOOK_PATH.stat().st_size
    if size > 30_000:
        fail(
            "Launcher notebook is unexpectedly large; expected a thin launcher "
            f"but got {size} bytes (>30000)."
        )

    required_markers = [
        "GITHUB_REF",
        "raw.githubusercontent.com",
        "urllib.request.urlopen",
        "download_verified",
        "hashlib.sha256",
        "ARTIFACT_SHA256",
        "install_locked_colab_python",
        "VOICEOPS_STT_POST",
        "exec(compile",
    ]
    for marker in required_markers:
        if marker not in source_text:
            fail(f"Launcher notebook missing expected thin-launcher marker: {marker}")

    suspicious_markers = [
        "cleanup_stale_project_temp_files",
        "TranscriptionRuntimeOptions",
        "build(\"drive\", \"v3\"",
        "gpt-4o-transcribe",
        "scribe_v2",
    ]
    for marker in suspicious_markers:
        if marker in source_text:
            fail(f"Launcher notebook appears to embed canonical workflow marker: {marker}")

    print("[ci-checks] Launcher notebook thinness checks passed.")



def check_realtime_launcher_notebook() -> None:
    if not REALTIME_NOTEBOOK_PATH.exists():
        fail("Required realtime launcher notebook missing: notebooks/elevenlabs_realtime_colab.ipynb")

    nb = json.loads(REALTIME_NOTEBOOK_PATH.read_text(encoding="utf-8"))
    source_text = "\n".join(
        "".join(cell.get("source", [])) for cell in nb.get("cells", []) if cell.get("cell_type") == "code"
    )

    size = REALTIME_NOTEBOOK_PATH.stat().st_size
    if size > 20_000:
        fail(
            "Realtime launcher notebook is unexpectedly large; expected a thin launcher "
            f"but got {size} bytes (>20000)."
        )

    required_markers = [
        "GITHUB_REF",
        "raw.githubusercontent.com",
        "urllib.request.urlopen",
        "download_verified",
        "hashlib.sha256",
        "elevenlabs_realtime.py",
        "exec(compile",
    ]
    for marker in required_markers:
        if marker not in source_text:
            fail(f"Realtime launcher notebook missing expected thin-launcher marker: {marker}")

    disallowed_markers = [
        "elevenlabs_api.py",
        "build(\"drive\", \"v3\"",
        "manifest",
        "speaker_projects",
    ]
    for marker in disallowed_markers:
        if marker in source_text:
            fail(f"Realtime launcher notebook appears to include batch/runtime marker: {marker}")

    print("[ci-checks] Realtime launcher notebook thinness checks passed.")


def check_realtime_runtime_boundaries() -> None:
    if not REALTIME_PY.exists():
        fail("Required realtime runtime missing: elevenlabs_realtime.py")
    text = REALTIME_PY.read_text(encoding="utf-8")
    disallowed_patterns = [
        r"import\s+elevenlabs_api",
        r"from\s+elevenlabs_api\s+import",
        r"build\(\s*['\"]drive['\"]\s*,\s*['\"]v3['\"]",
        r"build\(\s*['\"]docs['\"]\s*,\s*['\"]v1['\"]",
    ]
    for pattern in disallowed_patterns:
        if re.search(pattern, text):
            fail(f"Realtime runtime boundary violation detected: {pattern}")
    print("[ci-checks] Realtime runtime boundary checks passed.")

def check_no_raw_provider_body_logging() -> None:
    text = CANONICAL_PY.read_text(encoding="utf-8")
    disallowed_patterns = [
        r"print\(\s*resp\.text\s*\)",
        r"print\(\s*response\.text\s*\)",
        r"logging\.(?:error|warning|info|debug|exception)\([^\n]*resp\.text",
        r"logging\.(?:error|warning|info|debug|exception)\([^\n]*response\.text",
    ]
    for pattern in disallowed_patterns:
        if re.search(pattern, text):
            fail(f"Disallowed raw provider response body logging pattern detected: {pattern}")
    print("[ci-checks] Raw provider body logging guard passed.")


def check_temp_cleanup_patterns() -> None:
    text = CANONICAL_PY.read_text(encoding="utf-8")
    disallowed_patterns = [
        r"shutil\.rmtree\(\s*['\"]?/tmp/?['\"]?\s*\)",
        r"rm\s+-rf\s+/tmp\b",
        r"/tmp/\*\.m4a",
        r"glob\(\s*['\"]/tmp/\*\.(?:m4a|mp3|wav|flac|ogg)['\"]\s*\)",
    ]
    for pattern in disallowed_patterns:
        if re.search(pattern, text):
            fail(f"Dangerous broad temp cleanup pattern detected: {pattern}")
    print("[ci-checks] Temp cleanup safety guard passed.")



def check_studio_google_oauth_compose_wiring() -> None:
    compose_path = ROOT / "deploy" / "studio" / "compose.platform.yml"
    env_example_path = ROOT / "deploy" / "studio" / ".env.example"
    optional_secret_path = ROOT / "deploy" / "studio" / "optional-empty-secret"

    compose_text = compose_path.read_text(encoding="utf-8")
    env_example_text = env_example_path.read_text(encoding="utf-8")

    required_compose_markers = [
        "STUDIO_GOOGLE_OAUTH_CLIENT_ID: ${STUDIO_GOOGLE_OAUTH_CLIENT_ID:-}",
        "STUDIO_GOOGLE_OAUTH_CLIENT_SECRET_FILE: /run/studio-runtime-secrets/studio_google_oauth_client_secret",
        "STUDIO_GOOGLE_OAUTH_REDIRECT_URI: ${STUDIO_GOOGLE_OAUTH_REDIRECT_URI:-}",
        "STUDIO_GOOGLE_OAUTH_SCOPES: ${STUDIO_GOOGLE_OAUTH_SCOPES:-openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly}",
        "STUDIO_GOOGLE_OAUTH_STATE_TTL_SECONDS: ${STUDIO_GOOGLE_OAUTH_STATE_TTL_SECONDS:-600}",
        "- studio_google_oauth_client_secret",
        "studio_google_oauth_client_secret:",
        "file: ${STUDIO_GOOGLE_OAUTH_CLIENT_SECRET_FILE:-./optional-empty-secret}",
        "studio_google_maintenance_oauth_client_secret:",
        "file: ${STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_SECRET_FILE:-./optional-empty-secret}",
    ]
    for marker in required_compose_markers:
        if marker not in compose_text:
            fail(f"Studio Google OAuth Compose wiring missing marker: {marker}")

    required_env_markers = [
        "STUDIO_GOOGLE_OAUTH_CLIENT_ID=__REQUIRED_GOOGLE_OAUTH_CLIENT_ID__",
        "STUDIO_GOOGLE_OAUTH_CLIENT_SECRET_FILE=",
        "STUDIO_GOOGLE_OAUTH_REDIRECT_URI=https://studio.cloud-nodes.net/api/google/oauth/callback",
        "STUDIO_GOOGLE_OAUTH_SCOPES=openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly",
        "STUDIO_GOOGLE_OAUTH_STATE_TTL_SECONDS=600",
        "STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_ID=__REQUIRED_GOOGLE_MAINTENANCE_OAUTH_CLIENT_ID__",
        "STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_SECRET_FILE=",
        "STUDIO_GOOGLE_MAINTENANCE_OAUTH_REDIRECT_URI=https://studio.cloud-nodes.net/api/google/oauth/callback",
        "STUDIO_GOOGLE_MAINTENANCE_OAUTH_SCOPES=openid email https://www.googleapis.com/auth/drive.metadata.readonly https://www.googleapis.com/auth/documents",
    ]
    for marker in required_env_markers:
        if marker not in env_example_text:
            fail(f"Studio Google OAuth .env.example schema missing marker: {marker}")

    if not optional_secret_path.exists() or optional_secret_path.stat().st_size != 0:
        fail("Studio Google OAuth optional empty secret placeholder must exist and be zero bytes")

    api_block = compose_text.split("  studio-api:", 1)[1].split(
        "\n  studio-worker:", 1
    )[0]
    worker_block = compose_text.split("  studio-worker:", 1)[1].split(
        "\n  postgres:", 1
    )[0]
    required_api_markers = [
        "STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_ID: ${STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_ID:-}",
        "STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_SECRET_FILE: /run/studio-runtime-secrets/studio_google_maintenance_oauth_client_secret",
        "STUDIO_GOOGLE_MAINTENANCE_OAUTH_REDIRECT_URI: ${STUDIO_GOOGLE_MAINTENANCE_OAUTH_REDIRECT_URI:-}",
        "STUDIO_GOOGLE_MAINTENANCE_OAUTH_SCOPES: ${STUDIO_GOOGLE_MAINTENANCE_OAUTH_SCOPES:-openid email https://www.googleapis.com/auth/drive.metadata.readonly https://www.googleapis.com/auth/documents}",
        "- studio_google_maintenance_oauth_client_secret",
    ]
    for marker in required_api_markers:
        if marker not in api_block:
            fail(f"Studio maintenance OAuth API wiring missing marker: {marker}")
    for marker in required_api_markers:
        if marker not in worker_block:
            fail(
                "Studio maintenance OAuth worker wiring missing marker: "
                f"{marker}"
            )

    print("[ci-checks] Studio primary/maintenance Google OAuth wiring checks passed.")

def main() -> int:
    try:
        check_notebooks()
        check_launcher_notebook()
        check_realtime_launcher_notebook()
        check_colab_release_refs()
        check_realtime_runtime_boundaries()
        check_no_raw_provider_body_logging()
        check_temp_cleanup_patterns()
        check_studio_google_oauth_compose_wiring()
    except CheckError as exc:
        print(f"[ci-checks] FAILED: {exc}")
        return 1

    print("[ci-checks] All lightweight checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
