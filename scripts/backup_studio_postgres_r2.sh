#!/usr/bin/env bash
set -euo pipefail
umask 077
LOCK_FILE="${STUDIO_BACKUP_LOCK_FILE:-/tmp/studio-postgres-backup.lock}"
exec 9>"$LOCK_FILE"
flock -n 9 || { echo "backup already running" >&2; exit 1; }
: "${STUDIO_BACKUP_TAG:=scheduled}"
case "$STUDIO_BACKUP_TAG" in
  scheduled|pre-migration) ;;
  *) echo "unsupported backup tag" >&2; exit 2 ;;
esac
: "${RESTIC_REPOSITORY:?set S3-compatible R2 restic repository}"
: "${RESTIC_PASSWORD_FILE:?set restic password file}"
: "${AWS_ACCESS_KEY_ID_FILE:?set R2 access key file}"
: "${AWS_SECRET_ACCESS_KEY_FILE:?set R2 secret key file}"
: "${STUDIO_DEPLOY_DIR:?set deployment checkout path}"
export AWS_ACCESS_KEY_ID; AWS_ACCESS_KEY_ID="$(<"$AWS_ACCESS_KEY_ID_FILE")"
export AWS_SECRET_ACCESS_KEY; AWS_SECRET_ACCESS_KEY="$(<"$AWS_SECRET_ACCESS_KEY_FILE")"
TMPDIR=""
report_backup_outcome() {
  local outcome="$1" owner_user_id="${STUDIO_ALERT_OWNER_USER_ID:-}"
  [[ -n "$owner_user_id" ]] || return 0
  if ! (
    cd "$STUDIO_DEPLOY_DIR"
    docker compose --env-file deploy/studio/.env -f deploy/studio/compose.platform.yml \
      exec -T studio-api python -m studio_api.cli record-postgres-backup-outcome \
      "$owner_user_id" "$outcome" >/dev/null
  ); then
    echo "backup alert outcome could not be recorded" >&2
  fi
}
finish_backup() {
  local exit_code=$?
  trap - EXIT
  if [[ "$exit_code" == "0" ]]; then
    report_backup_outcome success
  else
    report_backup_outcome failed
  fi
  [[ -z "$TMPDIR" ]] || rm -rf -- "$TMPDIR"
  exit "$exit_code"
}
trap finish_backup EXIT
TMPDIR="$(mktemp -d)"
DUMP="$TMPDIR/studio-postgres.dump"
RESTIC_HOST="studio-postgres"
cd "$STUDIO_DEPLOY_DIR"
docker compose --env-file deploy/studio/.env -f deploy/studio/compose.platform.yml exec -T postgres pg_dump -U studio -d studio --format=custom --no-owner --file=/tmp/studio-postgres.dump
docker compose --env-file deploy/studio/.env -f deploy/studio/compose.platform.yml cp postgres:/tmp/studio-postgres.dump "$DUMP" >/dev/null
docker compose --env-file deploy/studio/.env -f deploy/studio/compose.platform.yml exec -T postgres rm -f /tmp/studio-postgres.dump
restic --password-file "$RESTIC_PASSWORD_FILE" backup --host "$RESTIC_HOST" --tag studio-postgres --tag "$STUDIO_BACKUP_TAG" "$DUMP"
if [[ "$STUDIO_BACKUP_TAG" == "scheduled" ]]; then
  restic --password-file "$RESTIC_PASSWORD_FILE" forget --host "$RESTIC_HOST" --tag studio-postgres,scheduled --group-by host,tags --keep-within 7d --keep-daily 30 --keep-monthly 12
fi
echo "studio postgres backup completed tag=$STUDIO_BACKUP_TAG"
