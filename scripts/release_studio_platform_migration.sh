#!/usr/bin/env bash
set -euo pipefail
umask 077

PREFIX="[studio-migration-release]"
FIXED_PATH="${STUDIO_RELEASE_FIXED_PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"
COMPOSE_FILE="deploy/studio/compose.platform.yml"
ENV_FILE="deploy/studio/.env"
API_IMAGE="elevenlabs-studio-api:local"
BACKUP_SCRIPT="scripts/backup_studio_postgres_r2.sh"
MIGRATION_SCRIPT="scripts/migrate_studio_platform.sh"
WORKER_ROLE_SCRIPT="scripts/configure_studio_worker_db_role.sh"
DATABASE_ROLE_SCRIPT="scripts/configure_studio_database_roles.sh"
BACKUP_ENV_FILE="${STUDIO_BACKUP_ENV_FILE:-/etc/elevenlabs-studio/backup.env}"
PYTHON_BIN="${STUDIO_RELEASE_PYTHON_BIN:-python3}"
phase="preflight"
snapshot_id=""
migration_applied="no"
database_role_change_attempted="no"
worker_role_change_attempted="no"
release_mode="migration"
release_workspace=""

cleanup() {
  [[ -z "$release_workspace" ]] || rm -rf -- "$release_workspace"
}
trap cleanup EXIT

blocked() {
  local reason="$1"
  local recovery="no"
  [[ "$migration_applied" == "yes" || "$database_role_change_attempted" == "yes" || "$worker_role_change_attempted" == "yes" ]] \
    && recovery="yes"
  printf '%s BLOCKED phase=%s reason=%s snapshot=%s migration_applied=%s database_role_change_attempted=%s worker_role_change_attempted=%s manual_recovery_required=%s\n' \
    "$PREFIX" \
    "$phase" \
    "$reason" \
    "${snapshot_id:0:12}" \
    "$migration_applied" \
    "$database_role_change_attempted" \
    "$worker_role_change_attempted" \
    "$recovery" >&2
  exit 2
}

run_worker_role() {
  local operation="$1"
  # Apply needs the root-only worker password, while the tracked checkout must
  # be inspected by its validated repository owner. Never mutate root's Git
  # configuration or relax secret permissions.
  env \
    GIT_OPTIONAL_LOCKS=0 \
    STUDIO_DEPLOY_DIR="$STUDIO_DEPLOY_DIR" \
    STUDIO_REPOSITORY_USER="$STUDIO_REPOSITORY_USER" \
    bash "$WORKER_ROLE_SCRIPT" "$operation" </dev/null
}

unexpected_failure() {
  local rc=$?
  trap - ERR
  blocked "unexpected_command_failure_rc_${rc}"
}
trap unexpected_failure ERR

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

repo_git() {
  runuser -u "$STUDIO_REPOSITORY_USER" -- \
    git -c core.hooksPath=/dev/null -C "$STUDIO_DEPLOY_DIR" "$@"
}

require_protected_file() {
  local path="$1"
  local label="$2"
  [[ -f "$path" && ! -L "$path" ]] || blocked "${label}_missing"
  [[ "$(stat -c %u -- "$path")" == "0" ]] || blocked "${label}_not_root_owned"
  case "$(stat -c %a -- "$path")" in
    400 | 600) ;;
    *) blocked "${label}_permissions" ;;
  esac
}

require_healthy_service() {
  local service="$1"
  local container_id health
  container_id="$(compose ps -q "$service" 2>/dev/null)" \
    || blocked "${service}_container_probe_failed"
  [[ -n "$container_id" && "$container_id" != *$'\n'* ]] \
    || blocked "${service}_container_count"
  health="$(docker inspect --format \
    '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
    "$container_id" 2>/dev/null)" \
    || blocked "${service}_health_probe_failed"
  [[ "$health" == "healthy" ]] || blocked "${service}_not_healthy"
}

require_running_service() {
  local service="$1"
  local container_id state
  container_id="$(compose ps -q "$service" 2>/dev/null)" \
    || blocked "${service}_container_probe_failed"
  [[ -n "$container_id" && "$container_id" != *$'\n'* ]] \
    || blocked "${service}_container_count"
  state="$(docker inspect --format '{{.State.Status}}' "$container_id" 2>/dev/null)" \
    || blocked "${service}_state_probe_failed"
  [[ "$state" == "running" ]] || blocked "${service}_not_running"
  printf '%s\n' "$container_id"
}

require_worker_stopped() {
  local raw
  raw="$(compose ps -a -q studio-worker 2>/dev/null)" \
    || blocked "worker_container_probe_failed"
  local -a containers=()
  mapfile -t containers < <(printf '%s\n' "$raw" | sed '/^$/d')
  [[ "${#containers[@]}" -le 1 ]] || blocked "multiple_worker_containers"
  [[ "${#containers[@]}" -eq 0 ]] && return

  local state exit_code
  state="$(docker inspect --format '{{.State.Status}}' "${containers[0]}" 2>/dev/null)" \
    || blocked "worker_state_probe_failed"
  exit_code="$(docker inspect --format '{{.State.ExitCode}}' "${containers[0]}" 2>/dev/null)" \
    || blocked "worker_exit_probe_failed"
  [[ "$state" == "exited" && "$exit_code" == "0" ]] \
    || blocked "worker_not_safely_stopped"
}

capture_revision_ids() {
  awk '$1 ~ /^[[:alnum:]_]+$/ && (NF == 1 || $2 ~ /^\(/) {print $1}'
}

probe_current_revision() {
  local raw
  if ! raw="$(
    compose exec -T postgres \
      psql -X -Atq -U studio -d studio \
      -c 'SELECT version_num FROM alembic_version' </dev/null 2>/dev/null
  )"; then
    blocked "current_revision_probe_failed"
  fi
  local -a revisions=()
  mapfile -t revisions < <(printf '%s\n' "$raw" | capture_revision_ids)
  [[ "${#revisions[@]}" -eq 1 && -n "${revisions[0]}" ]] \
    || blocked "current_revision_count"
  printf '%s\n' "${revisions[0]}"
}

probe_running_api_head() {
  local container_id="$1"
  local raw
  # A running container can outlive its image-store entry. Read only its baked
  # migration metadata as the application UID; `heads` does not connect to DB.
  if ! raw="$(
    docker exec \
      --user 10001:10001 \
      --workdir /app \
      --env PYTHONDONTWRITEBYTECODE=1 \
      "$container_id" \
      alembic -c /app/alembic.ini heads </dev/null 2>/dev/null
  )"; then
    blocked "running_api_head_probe_failed"
  fi
  local -a revisions=()
  mapfile -t revisions < <(printf '%s\n' "$raw" | capture_revision_ids)
  [[ "${#revisions[@]}" -eq 1 && -n "${revisions[0]}" ]] \
    || blocked "running_api_head_count"
  printf '%s\n' "${revisions[0]}"
}

capture_snapshot_ids() {
  local destination="$1"
  local metadata_file="$2"
  if ! restic --password-file "$RESTIC_PASSWORD_FILE" \
    snapshots --json \
    --host studio-postgres \
    --tag studio-postgres,pre-migration >"$metadata_file"; then
    blocked "snapshot_inventory_failed"
  fi
  if ! "$PYTHON_BIN" - "$metadata_file" >"$destination" <<'PY'
import json
import re
import sys

items = json.load(open(sys.argv[1], encoding="utf-8"))
seen = set()
for item in items:
    snapshot_id = item.get("id", "")
    tags = set(item.get("tags") or ())
    if (
        not re.fullmatch(r"[0-9a-f]{64}", snapshot_id)
        or item.get("hostname") != "studio-postgres"
        or not {"studio-postgres", "pre-migration"} <= tags
        or snapshot_id in seen
    ):
        raise SystemExit(1)
    seen.add(snapshot_id)
for snapshot_id in sorted(seen):
    print(snapshot_id)
PY
  then
    blocked "snapshot_inventory_invalid"
  fi
}

[[ "$(id -u)" -eq 0 ]] || blocked "not_root"
[[ "${STUDIO_RELEASE_LOCK_HELD:-}" == "yes" ]] || blocked "release_lock_not_held"
[[ -n "${STUDIO_DEPLOY_DIR:-}" ]] || blocked "deploy_directory_missing"
[[ -n "${STUDIO_EXPECTED_COMMIT:-}" ]] || blocked "expected_commit_missing"
[[ "${STUDIO_REQUESTED_MIGRATION_TARGET:-}" =~ ^(head|[[:alnum:]_]+)$ ]] \
  || blocked "requested_migration_target_invalid"
[[ "${STUDIO_REPOSITORY_USER:-}" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] \
  || blocked "repository_user_invalid"
[[ "$STUDIO_EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ ]] \
  || blocked "expected_commit_invalid"

for tool in curl docker find id restic runuser sed stat "$PYTHON_BIN"; do
  command -v "$tool" >/dev/null || blocked "required_tool_missing"
done
id "$STUDIO_REPOSITORY_USER" >/dev/null 2>&1 \
  || blocked "repository_user_missing"
[[ -d "$STUDIO_DEPLOY_DIR/.git" ]] || blocked "deploy_repository_missing"
cd "$STUDIO_DEPLOY_DIR"
[[ "$(pwd -P)" == "$STUDIO_DEPLOY_DIR" ]] || blocked "deploy_directory_mismatch"
[[ "$(repo_git rev-parse --abbrev-ref HEAD 2>/dev/null)" == "main" ]] \
  || blocked "unexpected_branch"
[[ "$(repo_git rev-parse HEAD 2>/dev/null)" == "$STUDIO_EXPECTED_COMMIT" ]] \
  || blocked "checkout_commit_mismatch"
export STUDIO_RELEASE_SHA="$STUDIO_EXPECTED_COMMIT"
export STUDIO_RELEASE_VERSION="${STUDIO_RELEASE_VERSION:-0.1.0}"
[[ "$STUDIO_RELEASE_VERSION" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$ ]] \
  || blocked "release_version_invalid"
tracked_state="$(repo_git status --porcelain --untracked-files=no 2>/dev/null)" \
  || blocked "tracked_tree_probe_failed"
[[ -z "$tracked_state" ]] || blocked "tracked_tree_dirty"
api_context_state="$(
  repo_git status --porcelain --untracked-files=all -- apps/studio-api 2>/dev/null
)" || blocked "api_build_context_probe_failed"
[[ -z "$api_context_state" ]] || blocked "api_build_context_dirty"
for required in \
  "$COMPOSE_FILE" \
  "$ENV_FILE" \
  "$BACKUP_SCRIPT" \
  "$MIGRATION_SCRIPT" \
  "$WORKER_ROLE_SCRIPT" \
  "$DATABASE_ROLE_SCRIPT" \
  deploy/studio/database-roles.sql \
  apps/studio-api/Dockerfile \
  apps/studio-api/alembic.ini; do
  [[ -f "$required" ]] || blocked "release_file_missing"
done

# A protected, exact-SHA recovery lane for the only expected post-migration
# worker failure: a reviewed allowlist gained newly created tables after the
# migration committed. It deliberately performs no backup, migration, image
# build, API recreation, provider call, or worker start. The forced-command
# wrapper, environment approval and release lock remain identical to the
# migration lane, and the worker must already be safely stopped.
if [[ "$STUDIO_REQUESTED_MIGRATION_TARGET" == "worker_role" ]]; then
  phase="worker_role"
  compose config --quiet >/dev/null 2>&1 || blocked "compose_config_invalid"
  require_healthy_service postgres
  require_healthy_service redis
  require_running_service studio-api >/dev/null
  require_worker_stopped

  worker_role_change_attempted="yes"
  if ! run_worker_role apply; then
    blocked "worker_role_apply_failed"
  fi
  if ! run_worker_role verify; then
    blocked "worker_role_verify_failed"
  fi

  curl -fsS -o /dev/null --max-time 5 \
    http://127.0.0.1:8182/api/readyz </dev/null \
    || blocked "localhost_api_health_failed"
  phase="complete"
  printf '%s OK commit=%s operation=worker_role\n' \
    "$PREFIX" "${STUDIO_EXPECTED_COMMIT:0:12}"
  exit 0
fi

release_workspace="$(mktemp -d /tmp/studio-migration-release.XXXXXX)"
runtime_metadata="$release_workspace/runtime-metadata"
before_ids="$release_workspace/snapshots-before"
after_ids="$release_workspace/snapshots-after"
before_json="$release_workspace/snapshots-before.json"
after_json="$release_workspace/snapshots-after.json"
restore_dir="$release_workspace/restore"

if ! "$PYTHON_BIN" - "$ENV_FILE" >"$runtime_metadata" <<'PY'
from pathlib import Path
from urllib.parse import urlsplit
import os
import sys

values = {}
for raw_line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if not raw_line or raw_line.startswith("#"):
        continue
    if raw_line[:1].isspace() or "=" not in raw_line:
        raise SystemExit(1)
    key, value = raw_line.split("=", 1)
    if not key.replace("_", "").isalnum() or not key[:1].isalpha() or key in values:
        raise SystemExit(1)
    if value != value.strip():
        raise SystemExit(1)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    values[key] = value

required = (
    "APP_PUBLIC_URL",
    "STUDIO_GOOGLE_OAUTH_CLIENT_ID",
    "STUDIO_GOOGLE_OAUTH_CLIENT_SECRET_FILE",
    "STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_ID",
    "STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_SECRET_FILE",
    "STUDIO_GOOGLE_MAINTENANCE_OAUTH_REDIRECT_URI",
    "STUDIO_GOOGLE_MAINTENANCE_OAUTH_SCOPES",
)
if any(not values.get(key) for key in required):
    raise SystemExit(1)
if values["STUDIO_GOOGLE_OAUTH_CLIENT_ID"] == values["STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_ID"]:
    raise SystemExit(1)
primary_secret = values["STUDIO_GOOGLE_OAUTH_CLIENT_SECRET_FILE"]
maintenance_secret = values["STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_SECRET_FILE"]
if (
    not os.path.isabs(primary_secret)
    or not os.path.isabs(maintenance_secret)
    or primary_secret == maintenance_secret
    or any(character.isspace() for character in primary_secret + maintenance_secret)
):
    raise SystemExit(1)
expected_scopes = (
    "openid email "
    "https://www.googleapis.com/auth/drive.metadata.readonly "
    "https://www.googleapis.com/auth/documents"
)
if values["STUDIO_GOOGLE_MAINTENANCE_OAUTH_SCOPES"] != expected_scopes:
    raise SystemExit(1)
for key in ("APP_PUBLIC_URL", "STUDIO_GOOGLE_MAINTENANCE_OAUTH_REDIRECT_URI"):
    parsed = urlsplit(values[key])
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise SystemExit(1)
public_url = values["APP_PUBLIC_URL"].rstrip("/")
if any(character.isspace() or character == "\t" for character in public_url):
    raise SystemExit(1)
print(public_url, primary_secret, maintenance_secret, sep="\t")
PY
then
  blocked "runtime_config_invalid"
fi
IFS=$'\t' read -r public_url primary_oauth_secret maintenance_oauth_secret \
  <"$runtime_metadata"
[[ -n "$public_url" && -n "$primary_oauth_secret" && -n "$maintenance_oauth_secret" ]] \
  || blocked "runtime_config_incomplete"
require_protected_file "$primary_oauth_secret" "primary_oauth_secret"
require_protected_file "$maintenance_oauth_secret" "maintenance_oauth_secret"

require_protected_file "$BACKUP_ENV_FILE" "backup_env"
release_deploy_dir="$STUDIO_DEPLOY_DIR"
set -a
# shellcheck disable=SC1090
source "$BACKUP_ENV_FILE"
set +a
PATH="$FIXED_PATH"
export PATH
[[ -n "${RESTIC_REPOSITORY:-}" ]] || blocked "restic_repository_missing"
[[ -n "${RESTIC_PASSWORD_FILE:-}" ]] || blocked "restic_password_file_missing"
[[ -n "${AWS_ACCESS_KEY_ID_FILE:-}" ]] || blocked "r2_access_key_file_missing"
[[ -n "${AWS_SECRET_ACCESS_KEY_FILE:-}" ]] || blocked "r2_secret_key_file_missing"
[[ "${STUDIO_DEPLOY_DIR:-}" == "$release_deploy_dir" ]] \
  || blocked "backup_deploy_directory_mismatch"
require_protected_file "$RESTIC_PASSWORD_FILE" "restic_password"
require_protected_file "$AWS_ACCESS_KEY_ID_FILE" "r2_access_key"
require_protected_file "$AWS_SECRET_ACCESS_KEY_FILE" "r2_secret_key"
export AWS_ACCESS_KEY_ID
export AWS_SECRET_ACCESS_KEY
AWS_ACCESS_KEY_ID="$(<"$AWS_ACCESS_KEY_ID_FILE")"
AWS_SECRET_ACCESS_KEY="$(<"$AWS_SECRET_ACCESS_KEY_FILE")"
[[ -n "$AWS_ACCESS_KEY_ID" && -n "$AWS_SECRET_ACCESS_KEY" ]] \
  || blocked "r2_credentials_empty"
[[ "$AWS_ACCESS_KEY_ID" != *$'\n'* && "$AWS_SECRET_ACCESS_KEY" != *$'\n'* ]] \
  || blocked "r2_credentials_multiline"

compose config --quiet >/dev/null 2>&1 || blocked "compose_config_invalid"
require_healthy_service postgres
require_healthy_service redis
api_container_id="$(require_running_service studio-api)"
require_worker_stopped

api_health_status="$(
  docker inspect --format \
    '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
    "$api_container_id" 2>/dev/null
)" || blocked "studio-api_health_probe_failed"
[[ "$api_health_status" =~ ^[[:alnum:]_-]+$ ]] \
  || blocked "studio-api_health_invalid"
running_api_image_id="$(
  docker inspect --format '{{.Image}}' "$api_container_id" 2>/dev/null
)" || blocked "studio-api_image_probe_failed"
[[ "$running_api_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] \
  || blocked "studio-api_image_invalid"

postgres_container_id="$(compose ps -q postgres 2>/dev/null)" \
  || blocked "postgres_container_probe_failed"
[[ -n "$postgres_container_id" && "$postgres_container_id" != *$'\n'* ]] \
  || blocked "postgres_container_count"
postgres_image_id="$(
  docker inspect --format '{{.Image}}' "$postgres_container_id" 2>/dev/null
)" || blocked "postgres_image_probe_failed"
[[ "$postgres_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] \
  || blocked "postgres_image_invalid"

curl -fsS -o /dev/null --max-time 5 \
  http://127.0.0.1:8182/api/livez </dev/null \
  || blocked "pre_migration_api_liveness_failed"

phase="candidate"
compose build studio-api </dev/null || blocked "candidate_build_failed"
candidate_image_id="$(
  docker image inspect --format '{{.Id}}' "$API_IMAGE" 2>/dev/null
)" || blocked "candidate_image_inspect_failed"
[[ "$candidate_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] \
  || blocked "candidate_image_invalid"

if ! migration_metadata="$(
  docker run --rm --entrypoint python "$API_IMAGE" -c '
from alembic.config import Config
from alembic.script import ScriptDirectory
import sys

script = ScriptDirectory.from_config(Config("/app/alembic.ini"))
heads = script.get_heads()
if len(heads) != 1:
    raise SystemExit(1)
repository_head = heads[0]
requested = sys.argv[1]
target = repository_head if requested == "head" else requested
revision = script.get_revision(target)
if revision is None:
    raise SystemExit(1)

cursor = script.get_revision(repository_head)
ancestors = set()
while cursor is not None:
    ancestors.add(cursor.revision)
    parent = cursor.down_revision
    if parent is None:
        break
    if not isinstance(parent, str):
        raise SystemExit(1)
    cursor = script.get_revision(parent)
if target not in ancestors:
    raise SystemExit(1)

down_revision = revision.down_revision
release_safety = getattr(revision.module, "release_safety", None)
if not isinstance(down_revision, str):
    raise SystemExit(1)
source = script.get_revision(down_revision)
if source is None:
    raise SystemExit(1)
source_parent = source.down_revision
if source_parent is None:
    source_parent = "base"
elif not isinstance(source_parent, str):
    raise SystemExit(1)
print(
    target,
    down_revision,
    release_safety or "",
    repository_head,
    source_parent,
    sep="\t",
)
' "$STUDIO_REQUESTED_MIGRATION_TARGET" </dev/null
)"; then
  blocked "candidate_migration_metadata_failed"
fi
[[ "$migration_metadata" != *$'\n'* ]] \
  || blocked "candidate_migration_metadata_count"
IFS=$'\t' read -r target_revision source_revision release_safety repository_head \
  source_parent_revision \
  <<<"$migration_metadata"
[[ "$target_revision" =~ ^[[:alnum:]_]+$ ]] \
  || blocked "candidate_head_invalid"
[[ "$source_revision" =~ ^[[:alnum:]_]+$ ]] \
  || blocked "candidate_down_revision_invalid"
[[ "$repository_head" =~ ^[[:alnum:]_]+$ ]] \
  || blocked "candidate_repository_head_invalid"
[[ "$source_parent_revision" == "base" \
  || "$source_parent_revision" =~ ^[[:alnum:]_]+$ ]] \
  || blocked "candidate_source_parent_invalid"
[[ "$target_revision" != "$source_revision" ]] \
  || blocked "candidate_migration_not_required"
[[ "$release_safety" == "additive" ]] \
  || blocked "candidate_migration_not_additive"

current_revision="$(probe_current_revision)"
if [[ "$current_revision" == "$source_revision" ]]; then
  release_mode="migration"
elif [[ "$current_revision" == "$target_revision" ]]; then
  [[ "$target_revision" == "$repository_head" ]] \
    || blocked "post_migration_recovery_requires_repository_head"
  [[ "$(require_running_service studio-api)" == "$api_container_id" ]] \
    || blocked "running_api_container_changed"
  running_api_head="$(probe_running_api_head "$api_container_id")"
  [[ "$running_api_head" == "$source_revision" ]] \
    || blocked "post_migration_recovery_api_revision_mismatch"
  release_mode="post_migration_recovery"
  migration_applied="yes"
else
  blocked "migration_is_not_exactly_one_linear_revision"
fi

if [[ "$release_mode" == "migration" && "$api_health_status" != "healthy" ]]; then
  [[ "$(require_running_service studio-api)" == "$api_container_id" ]] \
    || blocked "running_api_container_changed"
  running_api_head="$(probe_running_api_head "$api_container_id")"
  [[ "$source_parent_revision" != "base" \
    && "$running_api_head" == "$source_parent_revision" ]] \
    || blocked "unhealthy_api_not_exactly_one_revision_behind"
fi

phase="backup"
capture_snapshot_ids "$before_ids" "$before_json"
if ! STUDIO_BACKUP_TAG=pre-migration \
  STUDIO_DEPLOY_DIR="$STUDIO_DEPLOY_DIR" \
  bash "$BACKUP_SCRIPT" </dev/null; then
  blocked "backup_failed"
fi
capture_snapshot_ids "$after_ids" "$after_json"
if ! snapshot_id="$(
  "$PYTHON_BIN" - "$before_ids" "$after_ids" <<'PY'
import re
import sys

before = set(filter(None, open(sys.argv[1], encoding="utf-8").read().splitlines()))
after = set(filter(None, open(sys.argv[2], encoding="utf-8").read().splitlines()))
new_ids = sorted(after - before)
if len(new_ids) != 1 or not re.fullmatch(r"[0-9a-f]{64}", new_ids[0]):
    raise SystemExit(1)
print(new_ids[0])
PY
)"; then
  blocked "new_backup_snapshot_count"
fi

mkdir "$restore_dir"
if ! restic --password-file "$RESTIC_PASSWORD_FILE" \
  restore "$snapshot_id" --target "$restore_dir" >/dev/null; then
  blocked "backup_restore_verification_failed"
fi
declare -a dump_files=()
mapfile -d '' -t dump_files < <(
  find "$restore_dir" -type f -name studio-postgres.dump -print0
)
[[ "${#dump_files[@]}" -eq 1 && -s "${dump_files[0]}" ]] \
  || blocked "backup_dump_invalid"
if ! docker run --rm \
  --pull never \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 32 \
  --tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,nodev,size=65536 \
  --mount "type=bind,src=${dump_files[0]},dst=/tmp/studio-postgres.dump,readonly" \
  --entrypoint pg_restore \
  "$postgres_image_id" \
  --list /tmp/studio-postgres.dump </dev/null >/dev/null 2>&1; then
  blocked "backup_pg_restore_list_invalid"
fi

phase="migration"
database_role_change_attempted="yes"
if [[ "$release_mode" == "post_migration_recovery" ]]; then
  if ! STUDIO_DEPLOY_DIR="$STUDIO_DEPLOY_DIR" \
    bash "$DATABASE_ROLE_SCRIPT" apply </dev/null; then
    blocked "database_role_recovery_failed"
  fi
else
  if ! STUDIO_DEPLOY_DIR="$STUDIO_DEPLOY_DIR" \
    STUDIO_PRE_MIGRATION_BACKUP_CONFIRMED=yes \
    STUDIO_PRE_MIGRATION_BACKUP_SNAPSHOT="$snapshot_id" \
    STUDIO_EXPECTED_MIGRATION_FROM="$source_revision" \
    STUDIO_EXPECTED_MIGRATION_TO="$target_revision" \
    STUDIO_EXPECTED_REPOSITORY_HEAD="$repository_head" \
    STUDIO_EXPECTED_API_IMAGE_ID="$candidate_image_id" \
    bash "$MIGRATION_SCRIPT" </dev/null; then
    failure_revision="$(probe_current_revision)"
    [[ "$failure_revision" == "$target_revision" ]] \
      && migration_applied="yes"
    blocked "migration_failed"
  fi
  migration_applied="yes"
fi
post_revision="$(probe_current_revision)"
[[ "$post_revision" == "$target_revision" ]] \
  || blocked "post_migration_revision_mismatch"

# New tables receive no implicit studio_worker access. Re-apply the reviewed
# direct-grant allowlist only after the additive migration committed and while
# the release gate still proves the worker is safely stopped.
phase="worker_role"
worker_role_change_attempted="yes"
if ! run_worker_role apply; then
  blocked "worker_role_apply_failed"
fi
if ! run_worker_role verify; then
  blocked "worker_role_verify_failed"
fi

api_deployed="no"
if [[ "$target_revision" == "$repository_head" ]]; then
  phase="api_deploy"
  compose up -d --no-deps --force-recreate studio-api </dev/null \
    || blocked "api_recreate_failed"
  api_container="$(compose ps -q studio-api 2>/dev/null)" \
    || blocked "api_container_probe_failed"
  [[ -n "$api_container" && "$api_container" != *$'\n'* ]] \
    || blocked "api_container_count"
  running_image_id="$(
    docker inspect --format '{{.Image}}' "$api_container" 2>/dev/null
  )" || blocked "api_image_probe_failed"
  [[ "$running_image_id" == "$candidate_image_id" ]] \
    || blocked "api_image_mismatch"
  api_deployed="yes"

  local_health="failed"
  for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null --max-time 5 \
      http://127.0.0.1:8182/api/readyz </dev/null; then
      local_health="ok"
      break
    fi
    sleep 2
  done
  [[ "$local_health" == "ok" ]] || blocked "localhost_api_health_failed"
  curl -fsS -o /dev/null --max-time 8 \
    "${public_url}/api/readyz" </dev/null \
    || blocked "public_api_health_failed"
else
  curl -fsS -o /dev/null --max-time 5 \
    http://127.0.0.1:8182/api/livez </dev/null \
    || blocked "intermediate_api_liveness_failed"
  curl -fsS -o /dev/null --max-time 8 \
    "${public_url}/api/livez" </dev/null \
    || blocked "public_api_liveness_failed"
fi

phase="complete"
if ! timeout 120 restic --password-file "$RESTIC_PASSWORD_FILE" forget \
  --host studio-postgres --tag studio-postgres,pre-migration \
  --group-by host --keep-last 5 --prune >/dev/null 2>&1; then
  printf '%s WARNING pre_migration_backup_retention_failed\n' "$PREFIX" >&2
fi
printf '%s OK commit=%s mode=%s from=%s to=%s head=%s snapshot=%s image=%s api_deployed=%s\n' \
  "$PREFIX" \
  "${STUDIO_EXPECTED_COMMIT:0:12}" \
  "$release_mode" \
  "$source_revision" \
  "$target_revision" \
  "$repository_head" \
  "${snapshot_id:0:12}" \
  "${candidate_image_id:0:19}" \
  "$api_deployed"
