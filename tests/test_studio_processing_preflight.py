from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "studio_processing_preflight.sh"
WORKFLOW = ROOT / ".github/workflows/studio-processing-preflight.yml"
SHA = "a" * 40
SECRET_MARKERS = ["SUPERSECRET", "TOKEN123", "container-alpha", "private@example.com", "https://secret.example"]
IMAGE_ID = "sha256:" + "c" * 64
BASH = str(Path("C:/Program Files/Git/bin/bash.exe")) if Path("C:/Program Files/Git/bin/bash.exe").exists() else "bash"


def invoke_preflight(repo: Path, bin_dir: Path, *, cwd: Path | None = None):
    # Resolve paths inside Bash, including native Windows Python + Git Bash.
    return subprocess.run(
        [BASH, "-c", 'export PREFLIGHT_TEST_PYTHON="$(command -v python)"; '
         'export PATH="$(cd "$1" && pwd):$PATH"; '
         'target="$(cd "$3" && pwd)"; exec bash "$2" "$target" main '
         'Just9120/voiceops-studio "$4"', "preflight-test",
         bin_dir.as_posix(), SCRIPT.as_posix(), repo.as_posix(), SHA],
        cwd=cwd or repo, env=os.environ.copy(), text=True, capture_output=True, timeout=15,
    )


def _write_exe(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def make_repo(tmp_path: Path, **state: str) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "apps/studio-api/alembic", repo / "apps/studio-api/alembic", ignore=shutil.ignore_patterns("__pycache__"))
    (repo / "apps/studio-api/Dockerfile").parent.mkdir(parents=True, exist_ok=True)
    (repo / "apps/studio-api/Dockerfile").write_text("FROM scratch\n", encoding="utf-8", newline="\n")
    (repo / "apps/studio/Dockerfile").parent.mkdir(parents=True, exist_ok=True)
    (repo / "apps/studio/Dockerfile").write_text("FROM scratch\n", encoding="utf-8", newline="\n")
    (repo / "deploy/studio").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "deploy/studio/compose.platform.yml", repo / "deploy/studio/compose.platform.yml")
    shutil.copy2(ROOT / "deploy/studio/worker-db-role.sql", repo / "deploy/studio/worker-db-role.sql")
    shutil.copy2(ROOT / "deploy/studio/database-roles.sql", repo / "deploy/studio/database-roles.sql")
    (repo / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "scripts/check_studio_worker_secret.py", repo / "scripts/check_studio_worker_secret.py")
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    secrets = {}
    for name in [
        "pg",
        "api_pg",
        "migrator_pg",
        "worker_pg",
        "master",
        "s3id",
        "s3secret",
        "audio_s3id",
        "audio_s3secret",
        "google",
        "google_maintenance",
    ]:
        p = secret_dir / name
        value = {
            "s3id": "a" * 32,
            "s3secret": "b" * 64,
            "audio_s3id": "c" * 32,
            "audio_s3secret": "d" * 64,
        }.get(name, f"SUPERSECRET-{name}-TOKEN123")
        p.write_text(value + "\n", encoding="utf-8", newline="\n")
        # These paths are deliberately unavailable to the simulated deploy user.
        secrets[name] = f"/protected-studio-secrets/{name}"
    env_text = f"""APP_PUBLIC_URL=https://secret.example
STUDIO_POSTGRES_PASSWORD_FILE={secrets['pg']}
STUDIO_API_POSTGRES_PASSWORD_FILE={secrets['api_pg']}
STUDIO_MIGRATOR_POSTGRES_PASSWORD_FILE={secrets['migrator_pg']}
STUDIO_WORKER_POSTGRES_PASSWORD_FILE={secrets['worker_pg']}
STUDIO_CREDENTIAL_MASTER_KEY_FILE={secrets['master']}
STUDIO_SOURCE_S3_ENDPOINT_URL=https://private-r2.invalid
STUDIO_SOURCE_S3_REGION=auto
STUDIO_SOURCE_S3_BUCKET=bucket
STUDIO_SOURCE_S3_ACCESS_KEY_ID_FILE={secrets['s3id']}
STUDIO_SOURCE_S3_SECRET_ACCESS_KEY_FILE={secrets['s3secret']}
STUDIO_SOURCE_S3_LIFECYCLE_RULE_ID=transcription-reference-retention
STUDIO_AUDIO_REFERENCE_S3_ENDPOINT_URL=https://private-r2.invalid
STUDIO_AUDIO_REFERENCE_S3_REGION=auto
STUDIO_AUDIO_REFERENCE_S3_BUCKET=audio-bucket
STUDIO_AUDIO_REFERENCE_S3_ACCESS_KEY_ID_FILE={secrets['audio_s3id']}
STUDIO_AUDIO_REFERENCE_S3_SECRET_ACCESS_KEY_FILE={secrets['audio_s3secret']}
STUDIO_AUDIO_REFERENCE_S3_LIFECYCLE_RULE_ID=audio-reference-retention
STUDIO_SOURCE_UPLOAD_TTL_SECONDS=3600
STUDIO_SOURCE_PRESIGN_TTL_SECONDS=900
STUDIO_SOURCE_MAX_UPLOAD_BYTES=10
STUDIO_RECENT_AUTH_SECONDS=600
STUDIO_MEDIA_DURATION_WARNING_SECONDS=14400
STUDIO_MEDIA_MAX_DURATION_SECONDS=43200
STUDIO_GOOGLE_OAUTH_CLIENT_ID=client-private@example.com
STUDIO_GOOGLE_OAUTH_CLIENT_SECRET_FILE={secrets['google']}
STUDIO_GOOGLE_OAUTH_REDIRECT_URI=https://secret.example/api/google/oauth/callback
STUDIO_GOOGLE_OAUTH_SCOPES=openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly
STUDIO_GOOGLE_OAUTH_STATE_TTL_SECONDS=600
STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_ID=maintenance-client-private@example.com
STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_SECRET_FILE={secrets['google_maintenance']}
STUDIO_GOOGLE_MAINTENANCE_OAUTH_REDIRECT_URI=https://secret.example/api/google/oauth/callback
STUDIO_GOOGLE_MAINTENANCE_OAUTH_SCOPES=openid email https://www.googleapis.com/auth/drive.metadata.readonly https://www.googleapis.com/auth/documents
STUDIO_GOOGLE_PICKER_API_KEY=public-picker-key
STUDIO_GOOGLE_PICKER_APP_ID=123456789012
STUDIO_WORKER_POLL_INTERVAL_SECONDS=5
STUDIO_WORKER_ERROR_BACKOFF_SECONDS=5
STUDIO_WORKER_LEASE_TTL_SECONDS=3600
STUDIO_WORKER_LEASE_HEARTBEAT_INTERVAL_SECONDS=60
STUDIO_WORKER_CPU_LIMIT=2.0
STUDIO_WORKER_MEMORY_LIMIT=4g
STUDIO_WORKER_MEMORY_SWAP_LIMIT=4g
STUDIO_WORKER_PIDS_LIMIT=256
STUDIO_WORKER_TMPFS_SIZE=3g
STUDIO_ELEVENLABS_SCRIBE_V2_RATE_PER_HOUR_USD=0.22
STUDIO_ELEVENLABS_PRICING_EFFECTIVE_DATE=2026-08-30
STUDIO_ELEVENLABS_PRICING_SOURCE=elevenlabs_public_api_pricing
"""
    if state.pop("omit_heartbeat", ""):
        env_text = env_text.replace("STUDIO_WORKER_LEASE_HEARTBEAT_INTERVAL_SECONDS=60\n", "")
    (repo / "deploy/studio/.env").write_text(state.pop("env_text", env_text), encoding="utf-8", newline="\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_exe(bin_dir / "python", '#!/usr/bin/env bash\nset -euo pipefail\n"$PREFLIGHT_TEST_PYTHON" "$@" | tr -d "\\r"\n')
    log = tmp_path / "calls.log"
    _write_exe(
        repo / "scripts/configure_studio_worker_db_role.sh",
        f"#!/usr/bin/env bash\nprintf 'worker-role %s\\n' \"$*\" >> {log.as_posix()!r}\n"
        f"[[ {state.get('worker_role', 'ready')!r} == ready ]]\n",
    )
    _write_exe(
        repo / "scripts/configure_studio_database_roles.sh",
        f"#!/usr/bin/env bash\nprintf 'database-roles %s\\n' \"$*\" >> {log.as_posix()!r}\n"
        f"[[ {state.get('application_role', 'ready')!r} == ready ]]\n",
    )
    branch = state.get("branch", "main")
    remote = state.get("remote", "git@github.com:Just9120/voiceops-studio.git")
    commit = state.get("commit", SHA)
    dirty = state.get("dirty", "")
    _write_exe(bin_dir / "git", f"""#!/usr/bin/env bash
set -euo pipefail
printf 'git %s\n' "$*" >> {log.as_posix()!r}
case "$*" in
 'rev-parse --abbrev-ref HEAD') echo {branch!r} ;;
 'config --get remote.origin.url') echo {remote!r} ;;
 'rev-parse HEAD') echo {commit!r} ;;
 'status --porcelain --untracked-files=no') [[ {state.get('git_error', '')!r} != yes ]] || exit 3; echo {dirty!r} ;;
 *) echo unexpected git >&2; exit 9 ;;
esac
""")
    service = {
        "postgres": state.get("postgres", "healthy"),
        "redis": state.get("redis", "healthy"),
        "studio-api": state.get("api", "healthy"),
        "studio-web": state.get("web", "healthy"),
        "studio-worker": state.get("worker", "missing"),
    }
    worker_count = int(state.get("worker_count", "0"))
    current = state.get("current", "0043_yandex_disk")
    invalid_storage_kind = state.get("invalid_storage_kind", "")
    invalid_mounted_key = state.get("invalid_mounted_key", "")
    _write_exe(bin_dir / "docker", f"""#!/usr/bin/env bash
set -euo pipefail
printf 'docker %s\n' "$*" >> {log.as_posix()!r}
joined="$*"
if [[ "$1" != run ]]; then
  case "$joined" in *config*|*build*|*pull*|*up*|*down*|*restart*|*stop*|*start*|*kill*|*logs*|*upgrade*|*downgrade*|*stamp*) exit 44;; esac
fi
if [[ "$1" == "compose" ]]; then
  shift
  while [[ "$1" == "--env-file" || "$1" == "-f" ]]; do shift 2; done
  if [[ "$1" == "ps" ]]; then
    if [[ "$*" == 'ps -q studio-api' && -f {(tmp_path / 'probe-ran').as_posix()!r} && {state.get('replacement', '')!r} == yes ]]; then
      echo container-alpha-replaced; exit 0
    fi
    svc="${{@: -1}}"
    statuses=""
    case "$svc" in
      postgres) statuses={service['postgres']!r};; redis) statuses={service['redis']!r};; studio-api) statuses={service['studio-api']!r};; studio-web) statuses={service['studio-web']!r};; studio-worker) statuses={state.get('worker', 'missing')!r};; *) exit 4;;
    esac
    [[ "$statuses" == "missing" ]] && exit 0
    if [[ "$svc" == "studio-worker" ]]; then count={worker_count}; else IFS=',' read -ra parts <<< "$statuses"; count="${{#parts[@]}}"; fi
    for i in $(seq 1 "$count"); do echo "container-alpha-$svc-$i"; done
    exit 0
  elif [[ "$1" == "exec" ]]; then
    [[ "$2" == "-T" ]] || exit 45
    if [[ "$*" == *--validate-mounted-secret* ]]; then
      if [[ -n {invalid_mounted_key!r} && "$*" == *{invalid_mounted_key!r}* ]]; then exit 1; fi
      if [[ {invalid_storage_kind!r} == "source_access_key_id" && "$*" == *STUDIO_SOURCE_S3_ACCESS_KEY_ID_FILE* ]]; then exit 1; fi
      if [[ {invalid_storage_kind!r} == "source_secret_access_key" && "$*" == *STUDIO_SOURCE_S3_SECRET_ACCESS_KEY_FILE* ]]; then exit 1; fi
      if [[ {invalid_storage_kind!r} == "audio_access_key_id" && "$*" == *STUDIO_AUDIO_REFERENCE_S3_ACCESS_KEY_ID_FILE* ]]; then exit 1; fi
      if [[ {invalid_storage_kind!r} == "audio_secret_access_key" && "$*" == *STUDIO_AUDIO_REFERENCE_S3_SECRET_ACCESS_KEY_FILE* ]]; then exit 1; fi
      exit 0
    fi
    if read -r unexpected; then echo stdin-leak >> {log.as_posix()!r}; fi
    printf '%s\n' {current!r}
  else exit 5; fi
elif [[ "$1" == "image" ]]; then
  [[ "$*" == 'image inspect --format {{{{.Id}}}} {IMAGE_ID}' ]] || exit 49
  [[ {state.get('image_missing', '')!r} != yes ]] || exit 1
  echo {IMAGE_ID}; exit 0
elif [[ "$1" == "run" ]]; then
  [[ "$*" =~ ^run\ --rm\ --pull\ never\ --network\ none\ --read-only\ --user\ 0:0\ --cap-drop\ ALL\ --security-opt\ no-new-privileges\ --pids-limit\ 32\ --memory\ 64m\ --memory-swap\ 64m\ --cpus\ 0.25\ --log-driver\ none\ --mount\ type=bind,src=/protected-studio-secrets,dst=/run/studio-worker-secret-probe,readonly,bind-recursive=disabled\ --entrypoint\ python\ -i\ {IMAGE_ID}\ -I\ -S\ -\ (worker_pg|pg|migrator_pg)$ ]] || exit 50
  input="$(cat)"
  [[ "$input" == *'def validate_metadata('* ]] || exit 51
  touch {(tmp_path / 'probe-ran').as_posix()!r}
  [[ {state.get('worker_secret', 'valid')!r} == valid ]] || exit 1
  exit 0
elif [[ "$1" == "inspect" ]]; then
  if [[ "$2 $3" == '--format {{{{.Image}}}}' ]]; then echo {state.get('image_id', IMAGE_ID)!r}; exit 0; fi
  id="${{@: -1}}"; rest="${{id#container-alpha-}}"; idx="${{rest##*-}}"; svc="${{rest%-*}}"
  case "$svc" in
    postgres) statuses={service['postgres']!r};; redis) statuses={service['redis']!r};; studio-api) statuses={service['studio-api']!r};; studio-web) statuses={service['studio-web']!r};; studio-worker) statuses={state.get('worker', 'healthy')!r};; *) statuses=unknown;;
  esac
  IFS=',' read -ra parts <<< "$statuses"
  status="${{parts[$((idx-1))]:-unknown}}"
  if [[ "$*" == *State.Health* ]]; then [[ "$status" == "stopped" ]] && echo none || echo "$status"; else [[ "$status" == "stopped" || "$status" == "missing" ]] && echo exited || echo running; fi
else exit 6; fi
""")
    _write_exe(bin_dir / "curl", f"#!/usr/bin/env bash\nprintf 'curl %s\\n' \"$*\" >> {log.as_posix()!r}\nexit {state.get('curl_exit', '0')}\n")
    return repo, bin_dir


def run_preflight(tmp_path: Path, **state: str):
    repo, bin_dir = make_repo(tmp_path, **state)
    proc = invoke_preflight(repo, bin_dir)
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8").splitlines() if (tmp_path / "calls.log").exists() else []
    return proc, calls, repo


def assert_no_secret_output(proc: subprocess.CompletedProcess[str]) -> None:
    combined = proc.stdout + proc.stderr
    for marker in SECRET_MARKERS:
        assert marker not in combined


def assert_no_forbidden(calls: list[str]) -> None:
    joined = "\n".join(calls).lower()
    for word in ["fetch", "merge", "build", " pull", " up", " down", "restart", " stop", " start", "kill", "upgrade", "downgrade", "backup", "migration", "provider", " job", "logs"]:
        assert word not in joined


def test_successful_host_preflight(tmp_path: Path) -> None:
    proc, calls, _ = run_preflight(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.count("STUDIO_PROCESSING_HOST_PREFLIGHT_OK") == 1
    assert "STUDIO_PROCESSING_HOST_PREFLIGHT_BLOCKED" not in proc.stdout
    assert "authenticated smoke-account login | not-run" in proc.stdout
    assert "repository Alembic head | pass | exactly one repository Alembic head matches expected source head: 0043_yandex_disk" in proc.stdout
    assert "production Alembic revision | pass | exactly one known production database revision was reported: 0043_yandex_disk" in proc.stdout
    assert "revision equality | pass | production database revision 0043_yandex_disk equals repository head 0043_yandex_disk" in proc.stdout
    assert any(
        "exec -T studio-api python -m studio_api.container_entrypoint "
        "--drop-only alembic current" in c
        for c in calls
    )
    mounted_validation_calls = [
        call for call in calls if "--validate-mounted-secret" in call
    ]
    assert len(mounted_validation_calls) == 8
    for key in [
        "STUDIO_POSTGRES_PASSWORD_FILE",
        "STUDIO_CREDENTIAL_MASTER_KEY_FILE",
        "STUDIO_SOURCE_S3_ACCESS_KEY_ID_FILE",
        "STUDIO_SOURCE_S3_SECRET_ACCESS_KEY_FILE",
        "STUDIO_AUDIO_REFERENCE_S3_ACCESS_KEY_ID_FILE",
        "STUDIO_AUDIO_REFERENCE_S3_SECRET_ACCESS_KEY_FILE",
        "STUDIO_GOOGLE_OAUTH_CLIENT_SECRET_FILE",
        "STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_SECRET_FILE",
    ]:
        assert any(key in call for call in mounted_validation_calls)
    assert_no_secret_output(proc)
    assert_no_forbidden(calls)


def test_identity_failures_block_before_docker(tmp_path: Path) -> None:
    for kwargs in [
        {"wrong_cwd": "1"},
        {"remote": "git@github.com:Other/Repo.git"},
        {"branch": "feature"},
        {"commit": "b" * 40},
        {"dirty": " M secret-file"},
    ]:
        case = tmp_path / str(len(list(tmp_path.iterdir())))
        case.mkdir()
        if kwargs.pop("wrong_cwd", None):
            repo, bin_dir = make_repo(case)
            proc = invoke_preflight(repo, bin_dir, cwd=case)
            calls = (case / "calls.log").read_text().splitlines() if (case / "calls.log").exists() else []
        else:
            proc, calls, _ = run_preflight(case, **kwargs)
        assert proc.returncode != 0
        assert "STUDIO_PROCESSING_HOST_PREFLIGHT_BLOCKED" in proc.stdout
        assert not any(c.startswith("docker ") for c in calls)
        assert_no_secret_output(proc)


def test_root_only_database_secrets_use_metadata_probe_not_host_reads(tmp_path):
    proc, calls, _ = run_preflight(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "protected metadata probe confirmed" in proc.stdout
    probes = [call for call in calls if call.startswith("docker run ")]
    assert len(probes) == 3
    assert all("--network none --read-only --user 0:0" in probe for probe in probes)
    assert all("readonly,bind-recursive=disabled" in probe for probe in probes)
    assert all(IMAGE_ID in probe for probe in probes)
    assert {probe.rsplit(" ", 1)[-1] for probe in probes} == {"worker_pg", "pg", "migrator_pg"}
    assert not any("worker_pg" in call for call in calls if "exec -T studio-api" in call)
    assert_no_secret_output(proc)
    assert_no_forbidden(calls)


@pytest.mark.parametrize("state", [
    {"worker_secret": "invalid"}, {"image_missing": "yes"},
    {"image_id": "mutable-tag"}, {"replacement": "yes"},
    {"api": "healthy,healthy"},
])
def test_worker_secret_probe_fails_closed(tmp_path, state):
    proc, calls, _ = run_preflight(tmp_path, **state)
    assert proc.returncode != 0
    assert row_statuses(proc.stdout)["WORKER_POSTGRES_PASSWORD secret-file presence"] == "blocked"
    assert_no_secret_output(proc)
    assert_no_forbidden(calls)


def test_unavailable_git_status_blocks_before_docker(tmp_path):
    proc, calls, _ = run_preflight(tmp_path, git_error="yes")
    assert proc.returncode != 0
    assert row_statuses(proc.stdout)["tracked working tree"] == "blocked"
    assert not any(call.startswith("docker ") for call in calls)


@pytest.mark.parametrize("value", [
    "", "relative/path", "/password", "/x/password,readonly=false",
    "/x/../password", "/x/./password", "/x/..", "/x/.", "/x//password",
    "/x/", "/x/pass word", "/x/REQUIRED_password",
])
def test_unsafe_worker_secret_mount_path_blocks_before_docker(tmp_path, value):
    proc, calls = with_env_override(tmp_path, "STUDIO_WORKER_POSTGRES_PASSWORD_FILE", value)
    assert proc.returncode != 0
    assert row_statuses(proc.stdout)["WORKER_POSTGRES_PASSWORD secret-file presence"] == "blocked"
    assert not any(call.startswith("docker ") for call in calls)


def test_runtime_gate_failures_block_before_service_inspection(tmp_path: Path) -> None:
    cases = [
        {"remove_env": True},
        {"env_text": "APP_PUBLIC_URL=https://x\nAPP_PUBLIC_URL=https://y\n"},
        {"env_text": "APP_PUBLIC_URL=\n"},
        {"env_text": "APP_PUBLIC_URL=__REQUIRED_VALUE__\n"},
    ]
    for i, kwargs in enumerate(cases):
        case = tmp_path / str(i); case.mkdir()
        proc, calls, repo = run_preflight(case, **{k: v for k, v in kwargs.items() if k == "env_text"})
        if kwargs.get("remove_env"):
            repo, bin_dir = make_repo(case / "x")
            (repo / "deploy/studio/.env").unlink()
            proc = invoke_preflight(repo, bin_dir)
            calls = (case / "x/calls.log").read_text().splitlines() if (case / "x/calls.log").exists() else []
        assert proc.returncode != 0
        assert not any(c.startswith("docker ") for c in calls)
        assert_no_secret_output(proc)


def test_missing_or_unreadable_mounted_secret_blocks_inside_runtime_boundary(
    tmp_path: Path,
) -> None:
    key = "STUDIO_GOOGLE_OAUTH_CLIENT_SECRET_FILE"
    proc, calls, _ = run_preflight(tmp_path, invalid_mounted_key=key)
    assert proc.returncode != 0
    assert row_statuses(proc.stdout)["GOOGLE_OAUTH_CLIENT_SECRET secret-file presence"] == "blocked"
    assert "current allowlisted runtime mount is missing, unreadable, invalid, or placeholder content" in proc.stdout
    assert any("--validate-mounted-secret" in call and key in call for call in calls)
    assert_no_secret_output(proc)


def test_source_storage_placeholder_secrets_block_inside_runtime_boundary(tmp_path: Path) -> None:
    cases = [
        ("source_access_key_id", "SOURCE_S3_ACCESS_KEY_ID secret-file presence"),
        ("source_secret_access_key", "SOURCE_S3_SECRET_ACCESS_KEY secret-file presence"),
        ("audio_access_key_id", "AUDIO_REFERENCE_S3_ACCESS_KEY_ID secret-file presence"),
        ("audio_secret_access_key", "AUDIO_REFERENCE_S3_SECRET_ACCESS_KEY secret-file presence"),
    ]
    for index, (kind, row) in enumerate(cases):
        case = tmp_path / str(index)
        proc, calls, _ = run_preflight(case, invalid_storage_kind=kind)
        assert proc.returncode != 0
        assert row_statuses(proc.stdout)[row] == "blocked"
        assert "current allowlisted runtime mount is missing, unreadable, invalid, or placeholder content" in proc.stdout
        assert any("--validate-mounted-secret" in call for call in calls)
        assert_no_secret_output(proc)


def test_worker_running_blocks_without_mutation(tmp_path: Path) -> None:
    for count in (1, 2):
        proc, calls, _ = run_preflight(tmp_path / str(count), worker_count=str(count), worker="healthy")
        assert proc.returncode != 0
        assert "studio-worker running count is not zero" in proc.stdout
        assert_no_forbidden(calls)


def test_service_safety_blocks_unhealthy_dependencies(tmp_path: Path) -> None:
    for index, kwargs in enumerate([{"postgres": "missing"}, {"postgres": "unhealthy"}, {"redis": "missing"}, {"redis": "unhealthy"}, {"api": "unhealthy"}, {"web": "unhealthy"}]):
        proc, calls, _ = run_preflight(tmp_path / str(index), **kwargs)
        assert proc.returncode != 0
        assert "STUDIO_PROCESSING_HOST_PREFLIGHT_BLOCKED" in proc.stdout
        assert_no_forbidden(calls)


def test_worker_database_role_is_a_read_only_preflight_gate(tmp_path: Path) -> None:
    proc, calls, _ = run_preflight(tmp_path, worker_role="missing")
    assert proc.returncode != 0
    assert row_statuses(proc.stdout)["worker database role"] == "blocked"
    assert calls.count("worker-role verify") == 1
    assert not any("worker-role apply" in call or "worker-role disable" in call for call in calls)
    assert_no_secret_output(proc)
    assert_no_forbidden(calls)


def test_application_database_roles_are_a_read_only_preflight_gate(tmp_path: Path) -> None:
    proc, calls, _ = run_preflight(tmp_path, application_role="missing")
    assert proc.returncode != 0
    assert row_statuses(proc.stdout)["application database roles"] == "blocked"
    assert calls.count("database-roles verify") == 1
    assert not any("database-roles apply" in call or "database-roles disable" in call for call in calls)
    assert_no_secret_output(proc)
    assert_no_forbidden(calls)


def test_revision_safety_cases(tmp_path: Path) -> None:
    # no/multiple repository heads by changing down_revision graph in copied files
    proc, _, repo = run_preflight(tmp_path / "ok")
    assert proc.returncode == 0
    case = tmp_path / "nohead"
    proc, calls, repo = run_preflight(case)
    f = repo / "apps/studio-api/alembic/versions/0043_yandex_disk.py"
    f.write_text(f.read_text().replace('revision = "0043_yandex_disk"', 'revision = "0034_wrong_head"'), encoding="utf-8", newline="\n")
    proc = invoke_preflight(repo, case / "bin")
    assert proc.returncode != 0

    case = tmp_path / "multi"
    proc, calls, repo = run_preflight(case)
    alt = repo / "apps/studio-api/alembic/versions/0013_alt_head.py"
    alt.write_text('''"""alternate 0013 head for preflight test"""
revision = "0013_alt_head"
down_revision = "0012_output_reconciliation_cases"
branch_labels = None
depends_on = None

def upgrade():
    pass

def downgrade():
    pass
''', encoding="utf-8", newline="\n")
    proc = invoke_preflight(repo, case / "bin")
    assert proc.returncode != 0
    for current in ["", "abc\ndef", "0007_job_processing_lifecycle"]:
        proc, calls, _ = run_preflight(tmp_path / ("cur" + (current or "empty").replace("\n", "_")), current=current)
        assert proc.returncode != 0
        assert_no_forbidden(calls)


def test_revision_output_is_known_normalized_metadata_only(tmp_path: Path) -> None:
    mismatch, calls, _ = run_preflight(
        tmp_path / "known-mismatch",
        current="0011_diagnostic_debug_sessions (branchpoint) SUPERSECRET",
    )
    assert mismatch.returncode != 0
    assert "production Alembic revision | pass | exactly one known production database revision was reported: 0011_diagnostic_debug_sessions" in mismatch.stdout
    assert "revision equality | blocked | production database revision 0011_diagnostic_debug_sessions does not equal repository head 0043_yandex_disk" in mismatch.stdout
    assert_no_secret_output(mismatch)
    assert_no_forbidden(calls)

    unknown, calls, _ = run_preflight(tmp_path / "unknown", current="TOKEN123")
    assert unknown.returncode != 0
    assert "single production database revision is not present in the repository migration inventory" in unknown.stdout
    assert_no_secret_output(unknown)
    assert_no_forbidden(calls)


def test_workflow_contract() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    on = data[True]  # PyYAML 1.1 parses "on" as True.
    assert set(on) == {"workflow_dispatch"}
    assert on["workflow_dispatch"]["inputs"]["expected_commit"]["required"] is True
    assert data["permissions"] == {"contents": "read"}
    assert data["concurrency"] == {"group": "studio-platform-production", "cancel-in-progress": False}
    assert "refs/heads/main" in text
    assert "StrictHostKeyChecking=yes" in text and "BatchMode=yes" in text
    assert "mktemp /tmp/studio-processing-preflight" in text and "rm -f -- $(shell_quote" in text
    assert "deploy_studio_platform_component.sh" not in text
    assert "bash -s" not in text
    assert "git fetch" not in text and "git pull" not in text and "docker compose" not in text
    assert "mapfile -t mktemp_lines" in text and "${#mktemp_lines[@]}" in text
    assert "^/tmp/studio-processing-preflight\\.[A-Za-z0-9]{6,32}$" in text
    assert 'execute_command="chmod 700 -- $(shell_quote' in text

REQUIRED_ROWS = [
    "deploy directory identity", "repository remote identity", "branch identity", "commit identity", "tracked working tree",
    "runtime env presence", "runtime setting completeness",
    "POSTGRES_PASSWORD secret-file presence", "API_POSTGRES_PASSWORD secret-file presence", "MIGRATOR_POSTGRES_PASSWORD secret-file presence", "WORKER_POSTGRES_PASSWORD secret-file presence", "CREDENTIAL_MASTER_KEY secret-file presence", "SOURCE_S3_ACCESS_KEY_ID secret-file presence", "SOURCE_S3_SECRET_ACCESS_KEY secret-file presence", "AUDIO_REFERENCE_S3_ACCESS_KEY_ID secret-file presence", "AUDIO_REFERENCE_S3_SECRET_ACCESS_KEY secret-file presence", "GOOGLE_OAUTH_CLIENT_SECRET secret-file presence", "GOOGLE_MAINTENANCE_OAUTH_CLIENT_SECRET secret-file presence",
    "postgres service count/status", "redis service count/status", "studio-api service count/status", "studio-web service count/status", "studio-worker service count/status",
    "PostgreSQL health", "application database roles", "worker database role", "Redis health", "localhost API health", "localhost web health", "public API health", "public web health",
    "repository Alembic head", "production Alembic revision", "revision equality",
    "authenticated smoke-account login", "active Google connection", "exactly one active ElevenLabs BYOK credential", "writable output folder selected", "one small supported source available",
]


def row_statuses(stdout: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in stdout.splitlines():
        if " | " not in line or line.startswith("check |") or line.startswith("--- |"):
            continue
        name, status, _ = line.split(" | ", 2)
        rows[name] = status
    return rows


def assert_complete_table(proc: subprocess.CompletedProcess[str]) -> None:
    rows = row_statuses(proc.stdout)
    assert list(rows) == REQUIRED_ROWS
    assert len(rows) == len(REQUIRED_ROWS)


def test_blocked_results_emit_complete_table(tmp_path: Path) -> None:
    scenarios = [
        ("directory", lambda d: invoke_preflight(make_repo(d)[0], d / "bin", cwd=d)),
        ("remote", lambda d: run_preflight(d, remote="git@github.com:Other/Repo.git")[0]),
        ("runtime", lambda d: run_preflight(d, env_text="APP_PUBLIC_URL=not-a-url\n")[0]),
        ("worker", lambda d: run_preflight(d, worker_count="1", worker="healthy")[0]),
        ("health", lambda d: run_preflight(d, api="unhealthy")[0]),
        ("revision", lambda d: run_preflight(d, current="0007_job_processing_lifecycle")[0]),
    ]
    for name, runner in scenarios:
        proc = runner(tmp_path / name)
        assert proc.returncode != 0
        assert proc.stdout.count("STUDIO_PROCESSING_HOST_PREFLIGHT_BLOCKED") == 1
        assert_complete_table(proc)


def with_env_override(tmp_path: Path, key: str, value: str):
    repo, bin_dir = make_repo(tmp_path)
    env_path = repo / "deploy/studio/.env"
    lines = env_path.read_text(encoding="utf-8").splitlines()
    env_path.write_text("\n".join((f"{key}={value}" if line.startswith(f"{key}=") else line) for line in lines) + "\n", encoding="utf-8", newline="\n")
    proc = invoke_preflight(repo, bin_dir)
    calls = (tmp_path / "calls.log").read_text().splitlines() if (tmp_path / "calls.log").exists() else []
    return proc, calls


def test_semantic_runtime_validation_blocks_before_docker(tmp_path: Path) -> None:
    cases = [
        ("APP_PUBLIC_URL", "http://studio.example"),
        ("STUDIO_SOURCE_S3_ENDPOINT_URL", "not-a-url"),
        ("STUDIO_GOOGLE_OAUTH_REDIRECT_URI", "http://studio.example/callback"),
        ("STUDIO_GOOGLE_MAINTENANCE_OAUTH_REDIRECT_URI", "http://studio.example/callback"),
        ("STUDIO_GOOGLE_OAUTH_SCOPES", "openid email"),
        ("STUDIO_GOOGLE_MAINTENANCE_OAUTH_SCOPES", "openid email https://www.googleapis.com/auth/documents"),
        ("STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_ID", "client-private@example.com"),
        ("STUDIO_WORKER_POLL_INTERVAL_SECONDS", "abc"),
        ("STUDIO_WORKER_ERROR_BACKOFF_SECONDS", "-1"),
        ("STUDIO_SOURCE_MAX_UPLOAD_BYTES", "0"),
        ("STUDIO_SOURCE_MAX_UPLOAD_BYTES", "2147483648"),
        ("STUDIO_WORKER_POLL_INTERVAL_SECONDS", "61"),
        ("STUDIO_WORKER_LEASE_TTL_SECONDS", "299"),
        ("STUDIO_WORKER_CPU_LIMIT", "0.5"),
        ("STUDIO_WORKER_MEMORY_LIMIT", "2g"),
        ("STUDIO_WORKER_MEMORY_SWAP_LIMIT", "8g"),
        ("STUDIO_WORKER_PIDS_LIMIT", "0"),
        ("STUDIO_WORKER_TMPFS_SIZE", "1g"),
        ("STUDIO_ELEVENLABS_SCRIBE_V2_RATE_PER_HOUR_USD", "0"),
        ("STUDIO_ELEVENLABS_PRICING_EFFECTIVE_DATE", "not-a-date"),
        ("STUDIO_ELEVENLABS_PRICING_SOURCE", "operator_guess"),
        ("STUDIO_SOURCE_UPLOAD_TTL_SECONDS", "899"),
        ("STUDIO_SOURCE_PRESIGN_TTL_SECONDS", "901"),
    ]
    for i, (key, value) in enumerate(cases):
        proc, calls = with_env_override(tmp_path / str(i), key, value)
        assert proc.returncode != 0
        assert row_statuses(proc.stdout)["runtime setting completeness"] == "blocked"
        assert f"invalid non-secret runtime setting: {key}:" in proc.stdout
        assert not any(c.startswith("docker ") for c in calls)
        assert_complete_table(proc)


def test_runtime_validation_reports_key_and_reason_without_value(tmp_path: Path) -> None:
    unsafe_value = "http://do-not-print.example/private"
    proc, calls = with_env_override(
        tmp_path,
        "APP_PUBLIC_URL",
        unsafe_value,
    )

    assert proc.returncode != 0
    assert (
        "invalid non-secret runtime setting: "
        "APP_PUBLIC_URL:invalid_https_url"
    ) in proc.stdout
    assert unsafe_value not in proc.stdout + proc.stderr
    assert not any(call.startswith("docker ") for call in calls)
    assert_complete_table(proc)


def test_maintenance_oauth_requires_separate_secret_file(tmp_path: Path) -> None:
    repo, bin_dir = make_repo(tmp_path)
    env_path = repo / "deploy/studio/.env"
    lines = env_path.read_text(encoding="utf-8").splitlines()
    primary_secret = next(
        line.split("=", 1)[1]
        for line in lines
        if line.startswith("STUDIO_GOOGLE_OAUTH_CLIENT_SECRET_FILE=")
    )
    env_path.write_text(
        "\n".join(
            (
                f"STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_SECRET_FILE={primary_secret}"
                if line.startswith(
                    "STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_SECRET_FILE="
                )
                else line
            )
            for line in lines
        )
        + "\n",
        encoding="utf-8", newline="\n",
    )

    proc = invoke_preflight(repo, bin_dir)
    calls = (
        (tmp_path / "calls.log").read_text(encoding="utf-8").splitlines()
        if (tmp_path / "calls.log").exists()
        else []
    )

    assert proc.returncode != 0
    assert (
        row_statuses(proc.stdout)[
            "GOOGLE_MAINTENANCE_OAUTH_CLIENT_SECRET secret-file presence"
        ]
        == "blocked"
    )
    assert "maintenance OAuth requires a separate client secret file" in proc.stdout
    assert not any(call.startswith("docker ") for call in calls)
    assert_complete_table(proc)


def test_audio_references_require_separate_storage_boundary(tmp_path: Path) -> None:
    cases = [
        (
            "STUDIO_AUDIO_REFERENCE_S3_BUCKET",
            "bucket",
            "STUDIO_AUDIO_REFERENCE_S3_BUCKET:must_differ_from_transcription_bucket",
        ),
        (
            "STUDIO_AUDIO_REFERENCE_S3_LIFECYCLE_RULE_ID",
            "transcription-reference-retention",
            "STUDIO_AUDIO_REFERENCE_S3_LIFECYCLE_RULE_ID:must_differ_from_transcription_lifecycle",
        ),
    ]
    for index, (key, value, reason) in enumerate(cases):
        proc, calls = with_env_override(tmp_path / str(index), key, value)
        assert proc.returncode != 0
        assert reason in proc.stdout
        assert not any(call.startswith("docker ") for call in calls)
        assert_complete_table(proc)


def test_audio_references_require_separate_credential_files(tmp_path: Path) -> None:
    repo, bin_dir = make_repo(tmp_path)
    env_path = repo / "deploy/studio/.env"
    lines = env_path.read_text(encoding="utf-8").splitlines()
    source_access_file = next(
        line.split("=", 1)[1]
        for line in lines
        if line.startswith("STUDIO_SOURCE_S3_ACCESS_KEY_ID_FILE=")
    )
    env_path.write_text(
        "\n".join(
            (
                f"STUDIO_AUDIO_REFERENCE_S3_ACCESS_KEY_ID_FILE={source_access_file}"
                if line.startswith("STUDIO_AUDIO_REFERENCE_S3_ACCESS_KEY_ID_FILE=")
                else line
            )
            for line in lines
        )
        + "\n",
        encoding="utf-8", newline="\n",
    )
    proc = invoke_preflight(repo, bin_dir)
    calls = (
        (tmp_path / "calls.log").read_text(encoding="utf-8").splitlines()
        if (tmp_path / "calls.log").exists()
        else []
    )
    assert proc.returncode != 0
    assert "audio references require a separate credential file pair" in proc.stdout
    assert not any(call.startswith("docker ") for call in calls)
    assert_complete_table(proc)


def test_service_aggregation_fail_closed(tmp_path: Path) -> None:
    cases = [
        ({"postgres": "healthy,unhealthy"}, "postgres service count/status", "total count 2; running count 2; status unhealthy"),
        ({"postgres": "healthy,unknown"}, "postgres service count/status", "total count 2; running count 2; status unknown"),
        ({"postgres": "stopped"}, "postgres service count/status", "total count 1; running count 0; status stopped"),
        ({"postgres": "missing"}, "postgres service count/status", "total count 0; running count 0; status missing"),
        ({"postgres": "healthy,healthy"}, "postgres service count/status", "total count 2; running count 2; status healthy"),
        ({"worker_count": "1", "worker": "healthy"}, "studio-worker service count/status", "studio-worker running count is not zero"),
        ({"worker_count": "2", "worker": "healthy"}, "studio-worker service count/status", "studio-worker running count is not zero"),
    ]
    for i, (kwargs, row, observation) in enumerate(cases):
        proc, calls, _ = run_preflight(tmp_path / str(i), **kwargs)
        assert observation in proc.stdout
        assert_no_forbidden(calls)
        assert_complete_table(proc)


def validate_remote_path_candidate(value: str) -> bool:
    script = r'''
set -euo pipefail
mktemp_output="$PREFLIGHT_MKTEMP_OUTPUT"
if [[ "$mktemp_output" == *$'\n'* || "$mktemp_output" == *$'\r'* ]]; then exit 1; fi
mapfile -t mktemp_lines <<<"$mktemp_output"
if [[ "${#mktemp_lines[@]}" -ne 1 || -z "${mktemp_lines[0]}" ]]; then exit 1; fi
remote_script="${mktemp_lines[0]}"
[[ "$remote_script" =~ ^/tmp/studio-processing-preflight\.[A-Za-z0-9]{6,32}$ ]]
'''
    env = os.environ.copy()
    env["PREFLIGHT_MKTEMP_OUTPUT"] = value
    return subprocess.run([BASH, "-c", script], env=env, text=True).returncode == 0


def test_remote_temp_path_validation_cases() -> None:
    assert validate_remote_path_candidate("/tmp/studio-processing-preflight.Abc123")
    for value in [
        "/tmp/studio-processing-preflight.Abc123\n/tmp/studio-processing-preflight.Def456",
        "banner\n/tmp/studio-processing-preflight.Abc123",
        "/tmp/studio-processing-preflight.Abc'123",
        "/tmp/studio-processing-preflight.Abc123;rm -rf /",
        "/var/tmp/studio-processing-preflight.Abc123",
        "",
    ]:
        assert not validate_remote_path_candidate(value)


def workflow_step_run(name: str) -> str:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in data["jobs"]["host-preflight"]["steps"]:
        if step.get("name") == name:
            return step["run"]
    raise AssertionError(f"missing workflow step {name}")


def test_dispatch_input_reaches_shell_only_as_environment_data() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    validate_step = next(step for step in data["jobs"]["host-preflight"]["steps"] if step.get("name") == "Validate dispatch inputs and branch")
    assert validate_step["env"]["EXPECTED_COMMIT"] == "${{ inputs.expected_commit }}"
    assert validate_step["env"]["DISPATCH_REF"] == "${{ github.ref }}"
    for step in data["jobs"]["host-preflight"]["steps"]:
        run = step.get("run", "")
        assert "${{ inputs.expected_commit }}" not in run
        assert "${{ github.event.inputs" not in run
    run = validate_step["run"]
    assert '"$EXPECTED_COMMIT" =~ ^[0-9a-fA-F]{40}$' in run
    assert '"$DISPATCH_REF" != "refs/heads/main"' in run
    hostile = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa$(touch /tmp/owned)"
    assert not __import__("re").fullmatch(r"[0-9a-fA-F]{40}", hostile)


def run_workflow_transport(tmp_path: Path, *, scp_fail: bool = False, exec_fail: bool = False) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    log = tmp_path / "transport.log"
    remote_path = "/tmp/studio-processing-preflight.Abc123"
    remote_storage = tmp_path / "remote-uploaded-script"
    _write_exe(
        bin_dir / "python3",
        '#!/usr/bin/env bash\nexec "$PREFLIGHT_TRANSPORT_PYTHON" "$@"\n',
    )
    _write_exe(
        bin_dir / "ssh",
        f'''#!/usr/bin/env python3
import os, shlex, subprocess, sys
log={log.as_posix()!r}
remote={remote_path!r}
storage={remote_storage.as_posix()!r}
args=sys.argv[1:]
cmd=args[-1]
with open(log, 'a', encoding='utf-8') as f: f.write('ssh-argc %d\\n' % len(args)); f.write('ssh-cmd '+cmd+'\\n')
if cmd == 'mktemp /tmp/studio-processing-preflight.XXXXXX':
    print(remote); sys.exit(0)
parts=shlex.split(cmd)
with open(log, 'a', encoding='utf-8') as f: f.write('ssh-parts '+repr(parts)+'\\n')
if parts[:3] == ['rm', '-f', '--']:
    with open(log, 'a', encoding='utf-8') as f: f.write('cleanup-path '+parts[3]+'\\n')
    if parts[3] == remote and os.path.exists(storage): os.remove(storage)
    sys.exit(0)
if {str(exec_fail)}: sys.exit(23)
expected=['chmod','700','--',remote,'&&','cd','/opt/elevenlabs-studio','&&',remote,'/opt/elevenlabs-studio','main','Just9120/voiceops-studio',os.environ['EXPECTED_COMMIT']]
if parts != expected:
    with open(log, 'a', encoding='utf-8') as f: f.write('unexpected-parts '+repr(parts)+'\\n')
    sys.exit(24)
subprocess.run([os.environ['PREFLIGHT_TRANSPORT_BASH'], storage, '/opt/elevenlabs-studio', 'main', 'Just9120/voiceops-studio', os.environ['EXPECTED_COMMIT']], check=True)
sys.exit(0)
''',
    )
    _write_exe(
        bin_dir / "scp",
        f'''#!/usr/bin/env python3
import os, shutil, sys
log={log.as_posix()!r}
with open(log, 'a', encoding='utf-8') as f: f.write('scp-args '+repr(sys.argv[1:])+'\\n')
if {str(scp_fail)}: sys.exit(22)
target=sys.argv[-1]
assert target == 'deployer@example.invalid:{remote_path}'
shutil.copyfile(sys.argv[-2], {remote_storage.as_posix()!r})
os.chmod({remote_storage.as_posix()!r}, 0o700)
''',
    )
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "studio_processing_preflight.sh").write_text(
        f"#!/usr/bin/env bash\nprintf 'remote-preflight-args %s\\n' \"$*\" >> {log.as_posix()!r}\n",
        encoding="utf-8", newline="\n",
    )
    (script_dir / "studio_processing_preflight.sh").chmod(0o700)
    env = os.environ.copy()
    env.update(
        {
            "DEPLOY_HOST": "example.invalid",
            "DEPLOY_USER": "deployer",
            "EXPECTED_COMMIT": SHA,
            "PREFLIGHT_TRANSPORT_BASH": BASH,
            "PREFLIGHT_TRANSPORT_PYTHON": os.sys.executable,
        }
    )
    run = (
        'export PATH="$(cd "$1" && pwd):$PATH"\n'
        + workflow_step_run("Run read-only Studio processing host preflight")
    )
    proc = subprocess.run(
        [BASH, "-c", run, "workflow-transport-test", bin_dir.as_posix()],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return proc, lines


def test_workflow_ssh_transport_quotes_and_cleans_up_after_success(tmp_path: Path) -> None:
    proc, lines = run_workflow_transport(tmp_path)
    assert proc.returncode == 0, proc.stderr + proc.stdout + "\n" + "\n".join(lines)
    assert any("mktemp /tmp/studio-processing-preflight.XXXXXX" in line for line in lines)
    assert any("scp-args" in line and "deployer@example.invalid:/tmp/studio-processing-preflight.Abc123" in line for line in lines)
    assert any("remote-preflight-args /opt/elevenlabs-studio main Just9120/voiceops-studio " + SHA in line for line in lines)
    assert lines.count("cleanup-path /tmp/studio-processing-preflight.Abc123") == 1
    joined = "\n".join(lines)
    for forbidden in ["deploy_studio_platform_component.sh", "git fetch", "git pull", "docker compose", "compose build", "compose up", "compose restart", "alembic upgrade", "backup", "provider", "Google API", "job creation"]:
        assert forbidden not in joined


def test_workflow_cleanup_runs_after_upload_or_execution_failure(tmp_path: Path) -> None:
    proc, lines = run_workflow_transport(tmp_path / "upload", scp_fail=True)
    assert proc.returncode != 0
    assert lines.count("cleanup-path /tmp/studio-processing-preflight.Abc123") == 1
    proc, lines = run_workflow_transport(tmp_path / "exec", exec_fail=True)
    assert proc.returncode != 0
    assert lines.count("cleanup-path /tmp/studio-processing-preflight.Abc123") == 1
    assert not any("cleanup-path /opt/elevenlabs-studio" in line or "cleanup-path /tmp" == line for line in lines)


def test_missing_worker_lease_heartbeat_setting_uses_safe_default(tmp_path: Path) -> None:
    proc, _, _ = run_preflight(tmp_path, env_text="""APP_PUBLIC_URL=https://secret.example
STUDIO_POSTGRES_PASSWORD_FILE=/tmp/nonexistent-bootstrap
STUDIO_API_POSTGRES_PASSWORD_FILE=/tmp/nonexistent-api
STUDIO_MIGRATOR_POSTGRES_PASSWORD_FILE=/tmp/nonexistent-migrator
STUDIO_WORKER_POSTGRES_PASSWORD_FILE=/tmp/nonexistent-worker
STUDIO_CREDENTIAL_MASTER_KEY_FILE=/tmp/nonexistent-master
STUDIO_SOURCE_S3_ENDPOINT_URL=https://private-r2.invalid
STUDIO_SOURCE_S3_REGION=auto
STUDIO_SOURCE_S3_BUCKET=bucket
STUDIO_SOURCE_S3_ACCESS_KEY_ID_FILE=/tmp/nonexistent-source-id
STUDIO_SOURCE_S3_SECRET_ACCESS_KEY_FILE=/tmp/nonexistent-source-secret
STUDIO_SOURCE_S3_LIFECYCLE_RULE_ID=transcription-reference-retention
STUDIO_AUDIO_REFERENCE_S3_ENDPOINT_URL=https://private-r2.invalid
STUDIO_AUDIO_REFERENCE_S3_REGION=auto
STUDIO_AUDIO_REFERENCE_S3_BUCKET=audio-bucket
STUDIO_AUDIO_REFERENCE_S3_ACCESS_KEY_ID_FILE=/tmp/nonexistent-audio-id
STUDIO_AUDIO_REFERENCE_S3_SECRET_ACCESS_KEY_FILE=/tmp/nonexistent-audio-secret
STUDIO_AUDIO_REFERENCE_S3_LIFECYCLE_RULE_ID=audio-reference-retention
STUDIO_SOURCE_UPLOAD_TTL_SECONDS=3600
STUDIO_SOURCE_PRESIGN_TTL_SECONDS=900
STUDIO_SOURCE_MAX_UPLOAD_BYTES=10
STUDIO_RECENT_AUTH_SECONDS=600
STUDIO_MEDIA_DURATION_WARNING_SECONDS=14400
STUDIO_MEDIA_MAX_DURATION_SECONDS=43200
STUDIO_GOOGLE_OAUTH_CLIENT_ID=client
STUDIO_GOOGLE_OAUTH_CLIENT_SECRET_FILE=/tmp/nonexistent-google
STUDIO_GOOGLE_OAUTH_REDIRECT_URI=https://secret.example/api/google/oauth/callback
STUDIO_GOOGLE_OAUTH_SCOPES=openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly
STUDIO_GOOGLE_OAUTH_STATE_TTL_SECONDS=600
STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_ID=maintenance-client
STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_SECRET_FILE=/tmp/nonexistent-google-maintenance
STUDIO_GOOGLE_MAINTENANCE_OAUTH_REDIRECT_URI=https://secret.example/api/google/oauth/callback
STUDIO_GOOGLE_MAINTENANCE_OAUTH_SCOPES=openid email https://www.googleapis.com/auth/drive.metadata.readonly https://www.googleapis.com/auth/documents
STUDIO_GOOGLE_PICKER_API_KEY=picker
STUDIO_GOOGLE_PICKER_APP_ID=123
STUDIO_WORKER_POLL_INTERVAL_SECONDS=5
STUDIO_WORKER_ERROR_BACKOFF_SECONDS=5
STUDIO_WORKER_LEASE_TTL_SECONDS=3600
STUDIO_WORKER_CPU_LIMIT=2.0
STUDIO_WORKER_MEMORY_LIMIT=4g
STUDIO_WORKER_MEMORY_SWAP_LIMIT=4g
STUDIO_WORKER_PIDS_LIMIT=256
STUDIO_WORKER_TMPFS_SIZE=3g
STUDIO_ELEVENLABS_SCRIBE_V2_RATE_PER_HOUR_USD=0.22
STUDIO_ELEVENLABS_PRICING_EFFECTIVE_DATE=2026-08-30
STUDIO_ELEVENLABS_PRICING_SOURCE=elevenlabs_public_api_pricing
""")
    assert proc.returncode != 0
    assert "runtime setting completeness | pass" in proc.stdout
    assert "secret-file presence | blocked" in proc.stdout

def test_worker_lease_heartbeat_too_large_blocks_preflight(tmp_path: Path) -> None:
    env = (ROOT / "deploy/studio/.env.example").read_text(encoding="utf-8")
    env = (
        env.replace("__REQUIRED_TEMP_SOURCE_S3_ENDPOINT_URL__", "https://private-r2.invalid")
        .replace("__REQUIRED_TEMP_SOURCE_S3_REGION__", "auto")
        .replace("__REQUIRED_TEMP_SOURCE_S3_BUCKET__", "bucket")
        .replace("__REQUIRED_AUDIO_REFERENCE_S3_ENDPOINT_URL__", "https://private-r2.invalid")
        .replace("__REQUIRED_AUDIO_REFERENCE_S3_REGION__", "auto")
        .replace("__REQUIRED_AUDIO_REFERENCE_S3_BUCKET__", "audio-bucket")
        .replace("__REQUIRED_GOOGLE_OAUTH_CLIENT_ID__", "client")
        .replace("__REQUIRED_GOOGLE_MAINTENANCE_OAUTH_CLIENT_ID__", "maintenance-client")
        .replace("__REQUIRED_PUBLIC_RESTRICTED_PICKER_API_KEY__", "picker")
        .replace("__REQUIRED_GOOGLE_CLOUD_PROJECT_NUMBER__", "123")
        .replace("STUDIO_GOOGLE_OAUTH_CLIENT_SECRET_FILE=", "STUDIO_GOOGLE_OAUTH_CLIENT_SECRET_FILE=/tmp/nonexistent")
        .replace("STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_SECRET_FILE=", "STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_SECRET_FILE=/tmp/nonexistent-maintenance")
    )
    env = env.replace("STUDIO_WORKER_LEASE_TTL_SECONDS=3600", "STUDIO_WORKER_LEASE_TTL_SECONDS=300").replace("STUDIO_WORKER_LEASE_HEARTBEAT_INTERVAL_SECONDS=60", "STUDIO_WORKER_LEASE_HEARTBEAT_INTERVAL_SECONDS=101")
    proc, _, _ = run_preflight(tmp_path, env_text=env)
    assert proc.returncode != 0
    assert "runtime setting completeness | blocked" in proc.stdout


def test_old_env_without_worker_lease_heartbeat_key_passes_preflight_runtime_validation(tmp_path: Path) -> None:
    proc, calls, _ = run_preflight(tmp_path, omit_heartbeat="1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "runtime setting completeness | pass" in proc.stdout


def test_explicit_valid_worker_lease_heartbeat_value_passes_preflight(tmp_path: Path) -> None:
    proc, _, _ = run_preflight(tmp_path, env_text=None) if False else run_preflight(tmp_path)
    assert proc.returncode == 0
