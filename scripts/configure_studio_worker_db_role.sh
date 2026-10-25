#!/usr/bin/env bash
set -euo pipefail

EXPECTED_DIR="${STUDIO_DEPLOY_DIR:-$(pwd)}"
COMPOSE_FILE="deploy/studio/compose.platform.yml"
ENV_FILE="deploy/studio/.env"
ROLE_SQL="deploy/studio/worker-db-role.sql"
ROLE_NAME="studio_worker"

log() { printf '[studio-worker-db-role] %s\n' "$*"; }
fail() { printf '[studio-worker-db-role] ERROR: %s\n' "$*" >&2; exit 1; }
compose() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }

tracked_checkout_status() {
  local repository_user="${STUDIO_REPOSITORY_USER:-}" current_uid repository_uid

  if [[ -z "$repository_user" ]]; then
    env GIT_OPTIONAL_LOCKS=0 \
      git -c core.hooksPath=/dev/null -C "$EXPECTED_DIR" \
      status --porcelain --untracked-files=no
    return
  fi

  [[ "$repository_user" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || return 1
  repository_uid="$(id -u "$repository_user" 2>/dev/null)" || return 1
  current_uid="$(id -u)" || return 1
  if [[ "$current_uid" == "$repository_uid" ]]; then
    env GIT_OPTIONAL_LOCKS=0 \
      git -c core.hooksPath=/dev/null -C "$EXPECTED_DIR" \
      status --porcelain --untracked-files=no
    return
  fi

  [[ "$current_uid" == "0" ]] || return 1
  command -v runuser >/dev/null || return 1
  runuser -u "$repository_user" -- \
    env GIT_OPTIONAL_LOCKS=0 \
    git -c core.hooksPath=/dev/null -C "$EXPECTED_DIR" \
    status --porcelain --untracked-files=no
}

require_runtime() {
  local tracked_status
  cd "$EXPECTED_DIR"
  [[ -f "$ENV_FILE" && -f "$COMPOSE_FILE" && -f "$ROLE_SQL" ]] || fail "missing runtime contract"
  tracked_status="$(tracked_checkout_status)" || fail "cannot inspect tracked checkout"
  [[ -z "$tracked_status" ]] || fail "tracked checkout is dirty"
}

env_value_once() {
  local key="$1" count value
  count="$(grep -c "^${key}=" "$ENV_FILE" || true)"
  [[ "$count" == "1" ]] || fail "expected exactly one ${key}"
  value="$(sed -n "s|^${key}=||p" "$ENV_FILE")"
  [[ -n "$value" && "$value" != __REQUIRED_* ]] || fail "${key} is unresolved"
  printf '%s\n' "$value"
}

require_secret_file() {
  local path="$1" mode
  [[ "$path" == /* && -f "$path" && ! -L "$path" ]] || fail "worker password file is unavailable"
  mode="$(stat -c '%a' "$path")"
  [[ "$mode" == "600" || "$mode" == "400" ]] || fail "worker password file mode must be 0600 or 0400"
  [[ "$(stat -c '%U' "$path")" == "root" ]] || fail "worker password file must be root-owned"
}

psql_admin() {
  compose exec -T postgres psql -X --set ON_ERROR_STOP=1 -U studio -d studio "$@"
}

verify_role() {
  local result
  # Evaluate attributes in PostgreSQL; concat_ws emits t/f, not true/false.
  # EXISTS also rejects an absent role without accepting an empty result.
  result="$(psql_admin -Atqc "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${ROLE_NAME}' AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls AND NOT rolinherit)")"
  [[ "$result" == "t" ]] || fail "worker role attributes invalid"
  [[ "$(psql_admin -Atqc "SELECT NOT EXISTS (SELECT 1 FROM pg_auth_members AS membership JOIN pg_roles AS member_role ON member_role.oid = membership.member WHERE member_role.rolname = '${ROLE_NAME}')")" == "t" ]] || fail "worker role memberships invalid"
  [[ "$(psql_admin -Atqc "SELECT has_schema_privilege('${ROLE_NAME}', 'public', 'USAGE') AND NOT has_schema_privilege('${ROLE_NAME}', 'public', 'CREATE')")" == "t" ]] || fail "worker schema privileges invalid"
  [[ "$(psql_admin -Atqc "SELECT has_table_privilege('${ROLE_NAME}', 'alembic_version', 'SELECT') AND NOT (has_table_privilege('${ROLE_NAME}', 'alembic_version', 'INSERT') OR has_table_privilege('${ROLE_NAME}', 'alembic_version', 'UPDATE') OR has_table_privilege('${ROLE_NAME}', 'alembic_version', 'DELETE') OR has_table_privilege('${ROLE_NAME}', 'alembic_version', 'TRUNCATE'))")" == "t" ]] || fail "worker schema revision read-only privilege invalid"
  [[ "$(psql_admin -Atqc "SELECT has_table_privilege('${ROLE_NAME}', 'transcription_jobs', 'SELECT') AND has_table_privilege('${ROLE_NAME}', 'transcription_jobs', 'UPDATE') AND has_table_privilege('${ROLE_NAME}', 'transcription_job_outputs', 'SELECT') AND has_table_privilege('${ROLE_NAME}', 'transcription_job_outputs', 'INSERT') AND has_table_privilege('${ROLE_NAME}', 'transcription_provider_part_checkpoints', 'SELECT') AND has_table_privilege('${ROLE_NAME}', 'transcription_provider_part_checkpoints', 'INSERT') AND has_table_privilege('${ROLE_NAME}', 'transcription_provider_part_checkpoints', 'DELETE') AND NOT has_table_privilege('${ROLE_NAME}', 'transcription_provider_part_checkpoints', 'UPDATE') AND NOT has_table_privilege('${ROLE_NAME}', 'transcription_provider_part_checkpoints', 'TRUNCATE') AND has_table_privilege('${ROLE_NAME}', 'stt_provider_operations', 'SELECT') AND has_table_privilege('${ROLE_NAME}', 'stt_provider_operations', 'INSERT') AND has_table_privilege('${ROLE_NAME}', 'stt_provider_operations', 'UPDATE') AND NOT has_table_privilege('${ROLE_NAME}', 'stt_provider_operations', 'DELETE') AND NOT has_table_privilege('${ROLE_NAME}', 'stt_provider_operations', 'TRUNCATE') AND has_table_privilege('${ROLE_NAME}', 'stt_provider_health', 'SELECT') AND has_table_privilege('${ROLE_NAME}', 'stt_provider_health', 'INSERT') AND has_table_privilege('${ROLE_NAME}', 'stt_provider_health', 'UPDATE') AND NOT has_table_privilege('${ROLE_NAME}', 'stt_provider_health', 'DELETE') AND NOT has_table_privilege('${ROLE_NAME}', 'stt_provider_health', 'TRUNCATE') AND has_table_privilege('${ROLE_NAME}', 'diagnostic_events', 'DELETE') AND has_table_privilege('${ROLE_NAME}', 'provider_account_snapshots', 'SELECT') AND has_table_privilege('${ROLE_NAME}', 'operational_incidents', 'INSERT') AND has_table_privilege('${ROLE_NAME}', 'operational_incidents', 'UPDATE') AND has_table_privilege('${ROLE_NAME}', 'operational_alert_deliveries', 'INSERT') AND has_table_privilege('${ROLE_NAME}', 'operational_alert_deliveries', 'UPDATE') AND NOT has_table_privilege('${ROLE_NAME}', 'audit_events', 'UPDATE') AND NOT has_table_privilege('${ROLE_NAME}', 'audit_events', 'DELETE') AND NOT has_table_privilege('${ROLE_NAME}', 'audit_events', 'TRUNCATE')")" == "t" ]] || fail "worker required table privileges missing"
  [[ "$(psql_admin -Atqc "SELECT NOT (has_table_privilege('${ROLE_NAME}', 'sessions', 'SELECT') OR has_table_privilege('${ROLE_NAME}', 'sessions', 'INSERT') OR has_table_privilege('${ROLE_NAME}', 'sessions', 'UPDATE') OR has_table_privilege('${ROLE_NAME}', 'sessions', 'DELETE') OR has_table_privilege('${ROLE_NAME}', 'provider_credentials', 'INSERT') OR has_table_privilege('${ROLE_NAME}', 'provider_credentials', 'UPDATE') OR has_table_privilege('${ROLE_NAME}', 'provider_credentials', 'DELETE') OR has_table_privilege('${ROLE_NAME}', 'provider_account_snapshots', 'INSERT') OR has_table_privilege('${ROLE_NAME}', 'provider_account_snapshots', 'UPDATE') OR has_table_privilege('${ROLE_NAME}', 'provider_account_snapshots', 'DELETE'))")" == "t" ]] || fail "worker prohibited table privileges present"
  [[ "$(psql_admin -Atqc "SELECT has_table_privilege('${ROLE_NAME}', 'yandex_disk_connections', 'SELECT') AND has_column_privilege('${ROLE_NAME}', 'yandex_disk_connections', 'token_ciphertext', 'UPDATE') AND has_column_privilege('${ROLE_NAME}', 'yandex_disk_connections', 'credential_revision', 'UPDATE') AND NOT has_column_privilege('${ROLE_NAME}', 'yandex_disk_connections', 'account_uid', 'UPDATE') AND NOT has_column_privilege('${ROLE_NAME}', 'yandex_disk_connections', 'status', 'UPDATE') AND NOT has_table_privilege('${ROLE_NAME}', 'yandex_disk_connections', 'INSERT') AND NOT has_table_privilege('${ROLE_NAME}', 'yandex_disk_connections', 'DELETE') AND has_table_privilege('${ROLE_NAME}', 'yandex_disk_resources', 'SELECT') AND has_table_privilege('${ROLE_NAME}', 'yandex_disk_resources', 'INSERT') AND NOT has_table_privilege('${ROLE_NAME}', 'yandex_disk_resources', 'UPDATE') AND NOT has_table_privilege('${ROLE_NAME}', 'yandex_disk_resources', 'DELETE')")" == "t" ]] || fail "worker Disk privileges invalid"
  echo STUDIO_WORKER_DB_ROLE_OK
}

apply_role() {
  local password_file password escaped
  password_file="$(env_value_once STUDIO_WORKER_POSTGRES_PASSWORD_FILE)"
  require_secret_file "$password_file"
  password="$(<"$password_file")"
  [[ ${#password} -ge 24 && ${#password} -le 256 && "$password" != *$'\n'* && "$password" != *$'\r'* ]] || fail "worker password shape invalid"

  psql_admin -f - < "$ROLE_SQL"
  escaped="${password//\'/\'\'}"
  printf "ALTER ROLE %s WITH LOGIN PASSWORD '%s';\n" "$ROLE_NAME" "$escaped" | psql_admin >/dev/null
  unset password escaped
  verify_role
}

disable_role() {
  psql_admin -c "ALTER ROLE ${ROLE_NAME} NOLOGIN;" >/dev/null
  echo STUDIO_WORKER_DB_ROLE_DISABLED
}

require_runtime
case "${1:-}" in
  apply) apply_role ;;
  verify) verify_role ;;
  disable) disable_role ;;
  *) fail "usage: $0 apply|verify|disable" ;;
esac
