# Studio platform operations runbook

This is the main Studio operations runbook. It covers platform bootstrap, runtime files, secrets, backups, migrations, component deployment, source storage, Google OAuth, worker rollout, and recovery stop conditions. Processing invariants live in `docs/studio-processing-contract.md`. It does not authorize coding agents to deploy, run migrations, start workers, call providers, or mutate production.

## Delivery targets и процедуры

Перенесено из прежнего Project profile при внедрении правил 2026-09-07. Источники: `.github/workflows/*.yml`, `deploy/studio/compose.platform.yml`, repository scripts на origin/main `3e65322e12ba3d1ac2bc9f3ec7ecc412a6e3090b`; настройки доступа — snapshot 2026-09-06, branch/rulesets повторно 2026-09-07. Это описание действующих процедур, не authorization на privileged operations. Перед поставкой заново проверь settings/target и выбранную revision.

CD используется для Studio; Colab не получает VPS deployment автоматически. Public entrypoint — `studio.cloud-nodes.net` (до cutover DOMAIN-STUDIO-20261017 работает прежний `studio.librechat.online`); SSH target identity определяется соответствующими secret references и known-hosts, не догадкой по публичному домену. Directory `/opt/elevenlabs-studio`, repository `Just9120/voiceops-studio`, branch `main`, Compose project `elevenlabs-studio-platform`, compose `deploy/studio/compose.platform.yml`. Config owner — оператор: target-host `deploy/studio/.env` и отдельные root/operator-owned secret files. Не печатай resolved config и не заменяй `.env` шаблоном.

Deployment units: `studio-web`, `studio-api`, `studio-worker`; отдельно один direct additive Alembic successor и allowlisted host security-header snippet. Обычный component CD не использует GitHub Environment. Migration/edge используют единственный Environment `studio-production-migration`, branch policy main, одного reviewer (Just9120), `prevent_self_review=false`. Admin bypass в свежем scoped ответе не перепроверен; не используй bypass. Dedicated forced-command SSH identities/known-hosts разделяют migration/edge boundaries.

Concurrency: platform `studio-platform-production`, edge `studio-edge-production`, probe `studio-migration-environment-probe`; `cancel-in-progress: false`. Общий remote lock между всеми deployment lanes не подтверждён; найденный `flock` относится только к backup script. Перед пересекающимися operations проверь общий target/state и исключи конфликт; разные concurrency groups сами по себе его не исключают. Standard component workflow передаёт `EXPECTED_COMMIT=${{ github.sha }}` в bundle transport; проверяются 40-hex local HEAD, bundle checksum, exact fetched ref и resulting checkout. Target script получает bundle через `STUDIO_DEPLOY_FETCH_BUNDLE`, checkout обновляется `--ff-only`. Устаревший/расходящийся bundle не должен заменять более новый checkout: identity/fast-forward failure останавливает job. Migration/edge требуют exact current remote main SHA. Очередь не доказывает порядок версий: до dispatch/retry сверяй candidate с actual target/remote; intentional rollback — отдельная procedure. Standalone component entrypoint без bundle имеет иной fetch path и не является active workflow transport.

Stateful surfaces: PostgreSQL persistent volume `studio-postgres-data`, Redis coordination, private external S3/R2 storage, Google Docs side effects вне DB transaction. DB owner — отдельная NOLOGIN role; migrator и API/worker runtime roles/secret files разделены. Класс ordinary component deploy — `NONE`; migration lane — `EXPLICITLY_GATED` (старое имя в runbooks/истории `MANUAL_GATED` означает ту же защищённую процедуру, не автоматизацию). `BACKWARD_COMPATIBLE_AUTOMATED` для production migrations сейчас не используется. Не ослабляй protection только потому, что migration additive.

Recovery по умолчанию — diagnosis и согласованный forward-fix. Автоматического application/data rollback нет; edge допускает только narrow exact snippet-backup restore. При failed identity/schema/health останови продвижение, сохрани Evidence, не делай blind retry. После применения migration сначала проверь реальное schema/API state; повтор run не является стандартным recovery.

Health: web `http://127.0.0.1:8181/healthz`, API `http://127.0.0.1:8182/api/healthz`, worker Docker healthcheck `python -m studio_api.worker_health`; edge — nginx syntax, local/public TLS headers и API health. Web identity — `/build-meta.json` плюс deployment records; API/worker — exact source/image records из job/target. Health подтверждает свой узкий сценарий; проверку прикладного поведения привязывай к конкретному AC/версии. Safe public read-only smoke выполняй в разрешённом scope; платный/provider/Google canary — только по согласованной процедуре.

Release model: target-side Docker build на VPS, registry promotion не используется. Immutable built image ID сравнивается с running image ID, source связан с exact Git bundle SHA. Это заново построенный artifact, не проверенный CI binary. Отдельные provenance/attestations не настроены; их добавление — по требованиям/риску Goal. Browser report retention определяется `.github/workflows/studio-ci.yml`; после expiry отсутствие report нельзя выдавать за повторную проверку.

Имена credentials, без значений:

- Repository secrets: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS` — ordinary component/worker/preflight operations.
- Environment migration secrets: `STUDIO_MIGRATION_DEPLOY_HOST`, `STUDIO_MIGRATION_SSH_KEY`, `STUDIO_MIGRATION_KNOWN_HOSTS`.
- Environment edge secrets: `STUDIO_EDGE_DEPLOY_HOST`, `STUDIO_EDGE_SSH_KEY`, `STUDIO_EDGE_KNOWN_HOSTS`.
- Repository variables: `STUDIO_PLATFORM_CD_ENABLED`, `STUDIO_MIGRATION_RELEASE_ENABLED`, `STUDIO_EDGE_RELEASE_ENABLED` — перед action проверять значение, не только имя.

### Выбор component после merge

`.github/workflows/studio-platform-cd.yml` — единственный standard component router:

- automatic push flow включается только при `STUDIO_PLATFORM_CD_ENABLED=true`;
- `apps/studio/**` выбирает `studio-web`;
- non-migration `apps/studio-api/**` выбирает `studio-api`;
- Alembic change не deploy-ит API обычным путём: он выбирает protected migration lane только при `STUDIO_MIGRATION_RELEASE_ENABLED=true`, иначе API/migration остаются intentionally skipped/blocked;
- worker dependency changes не auto-deploy-ят worker; `studio-worker` остаётся manual-only;
- green `deployment-summary` с skipped component jobs не является component deployment Evidence.

Target-side build/recreate ограничен выбранным сервисом через `--no-deps --force-recreate`; schema mismatch или built/running image-ID mismatch останавливает поставку. Compose/process health подтверждает только свой сценарий. Обязательный успешный marker определяется выбранным script; зелёная summary при skipped job поставку не подтверждает.

| Операция | Canonical процедура и условия |
|---|---|
| Обычный web/API CD | [Component deployment](#component-deployment); exact trusted merge SHA через Git bundle, без миграций и worker lifecycle |
| Миграция | [Approval-gated migration release](#approval-gated-migration-release-lane); один direct additive successor, fresh approval/snapshot, worker stopped; не retry после migration_applied=yes |
| Host edge | [Protected Studio host-edge release](#protected-studio-host-edge-release); единственный allowlisted security-header snippet и exact backup recovery |
| Worker | [Official worker lifecycle operations](#official-worker-lifecycle-operations-pwa-worker-ops-01); status → graceful drain → confirmed stopped → deploy → image/health checks; canary отдельно |
| Processing readiness | [Manual processing preflight](#manual-processing-preflight); read-only проверки не разрешают provider/Google call |

Фактический результат восстанавливай из PR merge SHA и соответствующего run/job: target, artifact identity, UTC, terminal result и обязательные post-checks. Отдельные DEPLOY/LIVE поля в реестре и post-merge metadata commit не требуются. При восстановлении не запускай повторный deploy ради статуса; общий flow — [AGENTS](../../AGENTS.md), checks — [validation](validation.md).

## Repository/product rename — VOICEOPS-REBRAND-20261023

Canonical repository после согласованного rename — `Just9120/voiceops-studio`, immutable GitHub repository ID1212324255. Default branch остаётся `main`; protections, required `ci-required`, environment approvals и credential scopes сохраняются. GCP display name — VoiceOps Studio; project ID `braided-potion-499918-k4`, number476316429029 и existing OAuth clients не пересоздаются. Для восстановления источника имени сначала читать GitHub repository по immutable ID, а не создавать replacement repository по прежнему имени.

Порядок owner-authorized перехода:

1. Подготовить/review изменения canonical CI repository identity, deployment remote validation, двух forced-command wrappers и Colab pinned launcher metadata. CI продолжает отвергать foreign/legacy identity, а не принимает произвольный repository из environment.
2. При отсутствии конфликтующих runs переименовать тот же GitHub repository; readback должен сохранить ID1212324255, owner, branch и protections. Обновить local remote и выполнить PR validation уже с новым canonical name. Не использовать повторно прежнее имя для другого repository.
3. После успешных PR gates, перед merge/automatic web CD сверить clean `/opt/elevenlabs-studio`, source HEAD и старый remote. Сохранить recovery metadata и изменить только remote на новый exact GitHub URL; branch/source/config/data не заменять. В этот краткий переход installed legacy migration/edge wrappers закрыты из-за remote mismatch; не запускать эти lanes до следующего шага.
4. После merge получить exact reviewed main. При свободных migration/edge locks сверить каждый installed wrapper с ожидаемым baseline; сделать root-only recovery copy. Единственное разрешённое различие source/installed wrapper в этой операции — новое `EXPECTED_REPOSITORY`. Проверить Bash syntax, установить exact reviewed bytes на прежний root-owned path с прежними permissions, подтвердить hash/owner/mode и remote. Не менять forced SSH commands, secrets, approval gates или логику release. Если фактический файл изменился независимо, остановить этот шаг и согласовать current state.
5. Дождаться existing exact-main web CD; проверить build identity, health и три публичные HTML-страницы. API/worker/source storage/DB не требуют redeploy или migration из-за display name. При failed post-check остановить продвижение, восстановить exact previous remote/wrappers по сохранённым копиям, не откатывать данные.

Stateful compatibility: directory `/opt/elevenlabs-studio`, Compose project `elevenlabs-studio-platform`, image/volume/database/bucket/secret-file identities, manifest filenames и Colab module entrypoints сохраняются. Их names — техническая совместимость, а не ошибочный пользовательский бренд. Historical records сохраняют исходное имя и revision; active docs/scripts используют canonical name.

Google Branding values после web delivery: App name VoiceOps Studio; support/developer contact — согласованный owner email; authorized domain `cloud-nodes.net`; homepage `/about.html`, privacy `/privacy.html`, personal terms `/terms.html` на canonical host. Это реальные public static files без JavaScript/bootstrap auth. Владелец отдельно сохраняет actual requested scopes и меняет Publishing status; агент не утверждает OAuth publication/verification по одному GCP project display name. Personal use и Google brand/scope verification — отдельные условия, не commercial rollout.

## State vocabulary

Различай эти факты при объяснении результата; отдельные статусы в реестре AC не требуются:

- `source-done/merged` — repository source reached the target branch.
- `CI-verified` — checks passed for that source.
- `deployed` — a component is deployed to the target runtime.
- `migration-applied` — production database revision is updated and verified.
- `worker-running` — the intended worker instance is running from the intended image.
- `production-live` — factual controlled end-to-end processing evidence exists.

Do not claim production-live Studio processing without a controlled canary proving exactly one intended output and no unsafe evidence.

## Runtime files and secrets

Studio platform runtime configuration uses operator-managed files and runtime environment paths. Values ending in `_FILE` must contain host file paths, not secret contents.

Required secret-file classes include:

- PostgreSQL password secret file;
- Studio credential master key file;
- primary Google OAuth client secret file when Picker/browser OAuth is enabled;
- separate maintenance Google OAuth client secret file when recursive transcript maintenance is enabled;
- separate transcription-reference and audio-reference access-key files for two private S3/R2-compatible buckets;
- optional Telegram operational-alert bot-token and chat-ID files when that transport is enabled;
- optional VAPID private key, SMTP password and separate job-notification Telegram bot-token/chat-ID files when those owner channels are enabled;
- backup/restic repository/password/access secret files when backup automation is used.

Rules:

- Secret files must be readable only by the deployment operator/runtime boundary, normally `0600`.
- Do not print, `cat`, copy into prompts, or commit secret file contents.
- Do not use unsafe `docker compose config` output as evidence because it can resolve and expose secret values.
- Runtime `.env` review may record variable presence and path shape, but never secret values.

Compose file-backed secrets retain host-file ownership and permissions. The shared
API/worker container therefore starts its reviewed entrypoint as container root
only long enough to copy the mounted allowlisted secrets into a root-owned private
tmpfs runtime directory as `0400` files owned by UID/GID `10001`. It then clears
supplementary groups, drops irreversibly to `10001`, and execs the API, worker,
Alembic, or health command. Do not relax host secret permissions, add broad ACLs,
or bypass the entrypoint for commands that need database/runtime secrets.

## Trusted reverse-proxy peer

### Web host-port publication

The static web container joins `studio-web-ingress` (a web-only non-internal
bridge) and the existing internal `studio-web-api` network. Keep the published
endpoint exactly `127.0.0.1:8181:8080`; do not change it to `0.0.0.0`, host
networking, or attach web to a database/worker/Redis network. Docker 29.7.2 was
observed accepting the configured binding but not publishing it for an
internal-only web container. Delivery validation includes more than container health:
the standard web deployment must also pass host `8181/healthz` and the public
web build/health check. A web-only recreate applies the corrected attachment;
API, worker, databases, volumes and secrets must remain untouched.

Worker status preserves raw capability names but compares the exact allowed
`CAP_CHOWN`, `CAP_SETGID`, `CAP_SETUID` aliases as equivalent to their unprefixed
forms. Additional or malformed capabilities still produce `isolation_match=no`.

### API proxy trust

`STUDIO_TRUSTED_PROXY_IP` is one exact IP address, never a hostname, CIDR, wildcard,
or forwarded client address. The API accepts the last `X-Forwarded-For` value only
when the direct request peer equals that configured address; otherwise it uses the
direct peer and ignores the header. The default `127.0.0.1` is fail-closed for
local direct proxying but must not be assumed correct for a host nginx request
crossing a Docker-published port.

Before changing the production value:

1. Keep the current value and issue one safe public `/api/healthz` request in a
   bounded observation window.
2. Inspect only the matching API access-log row and record the direct peer IP,
   timestamp, endpoint group, and status. Do not retain unrelated request paths,
   headers, query strings, cookies, or bodies.
3. Repeat once to confirm the same direct peer and reconcile it with the intended
   host-nginx-to-published-port topology. Stop if the peer is absent, changes, or
   cannot be distinguished from another proxy hop.
4. Set only the observed exact IP in the operator-managed runtime `.env`. Never
   use `0.0.0.0`, `::`, a subnet, or a value copied from `X-Forwarded-For`.
5. Treat the resulting API deployment and verification as a separate authorized
   runtime action. Confirm distinct safe client requests no longer collapse onto
   one proxy rate-limit key, while a spoofed forwarded header from an untrusted
   direct peer remains ignored.

## Platform bootstrap

Canonical stateful platform deployment uses the platform Compose stack under `deploy/studio/` and the approved platform scripts/runbooks, not the legacy stateless web-only path.

Bootstrap boundary:

1. Verify the intended deploy checkout, branch, remote, and clean/reviewed tracked tree.
2. Start or verify PostgreSQL and Redis as stateful platform services without recreating volumes unless a separate maintenance task authorizes it.
3. Prepare runtime `.env` and secret files before API startup.
4. Start API and web components separately.
5. Bootstrap the initial admin only through the approved server-side bootstrap admin command and without printing credentials.
6. Verify nginx routes browser traffic to the web component and `/api/*` traffic to the API component.
7. Validate the public HTTPS response carries the repository CSP, HSTS, `nosniff`, origin-only referrer policy, permissions, and framing headers; confirm Picker open/select/cancel and one bounded local PUT still work without CSP violations. The local PUT must omit browser credentials, expose no referrer path/query beyond the public Studio origin, and reject a redirected terminal response. Do not infer live header state from the committed nginx file.
8. Verify localhost and public health endpoints for the intended components.

After migrations and successful API/database configuration, bootstrap the first admin with the approved interactive command:

```bash
docker compose \
  --env-file deploy/studio/.env \
  -f deploy/studio/compose.platform.yml \
  run --rm studio-api \
  python -m studio_api.cli admin@example.com
```

Replace `admin@example.com` with the approved admin email. The admin password is entered interactively; never pass it through shell arguments, environment variables, documentation, or logs. The command refuses to create a second active admin. For a restored database, first check whether an active admin already exists instead of running bootstrap automatically.

Health evidence should include only safe status booleans/markers, component names, and revision labels.

## Backup and migration order

Migration rollout order is strict:

1. Verify PostgreSQL and Redis health/stateful-service identity.
2. Build the exact candidate API image and select exactly one direct migration
   target on the repository head's single linear chain. Verify that target is
   the current database revision's direct successor and is classified
   `additive`.
3. Create a new tagged pre-migration PostgreSQL backup through the approved
   backup boundary.
4. Identify that new snapshot relative to the pre-run inventory, restore it only
   into an isolated temporary verification directory, and require one non-empty
   custom dump with a valid `pg_restore --list`. Run that parser in a
   network-disabled, read-only helper container from the immutable image ID of
   the already healthy PostgreSQL service; do not require a separately managed
   host PostgreSQL client.
5. Run the migration once only after explicit operator or protected-environment
   approval.
6. Verify production database revision equals the explicitly reviewed target.
7. For an intermediate target, preserve the running API and recheck localhost
   and public `/api/livez`. The old API can be intentionally unready while its
   Alembic head is one revision behind the migrated database. For the repository
   head, recreate only `studio-api` from
   the already captured candidate image, verify running image identity, then
   verify localhost and public API health.

Ordinary web/API/worker component CD does not own this sequence. The preferred
automated path is the separately protected migration release lane below. The
manual commands remain a fallback for a diagnosed operator task.

### Approval-gated migration release lane

SECURITY-FIVE-20261024 introduces additive `0042_totp_replay` after
`0041_source_retention_default`. It adds nullable `user_totp_factors.last_used_counter`
without changing enrolled secrets, sessions or recovery codes. Apply through the
signed protected backup/direct-successor migration lane, then verify API and
drained compatible worker at0042. New login/reauth/confirm/disable operations
atomically consume their matched counter in the auth transaction; reused codes
are rejected, including concurrent attempts. Secret replacement resets only that
factor's counter. Existing active factors start with no historical counter;
pre-upgrade use cannot be reconstructed, and an old code can remain within the
standard bounded acceptance window during cutover. Existing recovery codes and
the operator break-glass procedure remain available. Production schema downgrade
or direct counter reset is not a normal recovery action.

`.github/workflows/studio-platform-cd.yml` detects Alembic changes but keeps the
lane disabled unless repository variable
`STUDIO_MIGRATION_RELEASE_ENABLED=true`. A selected release job enters GitHub
environment `studio-production-migration`. When that environment is correctly
protected, GitHub pauses the job for its required reviewer before environment
secrets or VPS steps become available. Environment binding or a green job alone
is not evidence that the pause and approval occurred. The job creates a Git
bundle from its exact trusted checkout, verifies the advertised `HEAD` and
SHA-256 checksum, then streams it over stdin while sending exactly
`release-bundle <main-sha> <target> <bundle-sha256> <signature-base64>` to a dedicated root SSH key whose forced command is
`/usr/local/sbin/studio-migration-release-wrapper`.

The signature is Ed25519 over the exact LF-terminated UTF-8 message
`voiceops-studio-migration-release-v1`, `Just9120/voiceops-studio`, main SHA,
target and bundle SHA-256, each on its own line. The protected environment
holds `STUDIO_MIGRATION_SIGNING_KEY`, independently generated from the SSH
identity. The VPS holds only its public key in
`/etc/studio-migration-release/signing.pub`; directory root-owned0700, key
root-owned0400. The wrapper rejects missing/invalid signatures and unsafe
trust-file ownership/modes before receiving/promoting the bundle or executing
its runner. Caller checksum and Git ancestry alone never authorize a release.

The root-owned wrapper accepts only that command (plus the retained legacy
network form for rollback compatibility), where target is `head` or one bounded
Alembic revision identifier. It locks the release, receives at most 128 MiB,
verifies the bundle checksum, structure and exact advertised `HEAD`, then
fast-forwards the clean `studio-deploy` checkout from that local bundle without
VPS-to-GitHub network access. It materializes the versioned runner from that
SHA, clears the SSH
environment, and executes the runner. The runner requires root-owned protected
backup/OAuth secret files, the health/schema conditions below, and a stopped worker.
It requires healthy PostgreSQL/Redis, a running API process and local API
liveness. A non-healthy API is accepted only for diagnosed schema-ahead recovery
when the running image head is exactly the current database revision's direct
predecessor and the selected migration is exactly the current database
revision's direct successor. It builds the API candidate, verifies the selected one direct additive
migration is an ancestor of the single repository head,
creates and restores a new tagged snapshot for dump validation, migrates once,
recreates API from the captured image ID only for the repository-head target,
and emits success only after local/public health. Dump parsing uses the exact running PostgreSQL image ID in
an ephemeral container with no network, a read-only root filesystem, dropped
capabilities, no image pull, and only the restored dump mounted read-only. An
ephemeral tmpfs covers the image-declared PostgreSQL data path so the validation
does not create or attach a persistent Docker volume.

Schema-ahead recovery reads `alembic heads` from the exact captured running API
container ID with `docker exec --user 10001:10001`, bytecode writes disabled and
no database command. A running container can outlive its local image-store
entry; a missing old image must not trigger an image rebuild, API restart or a
skipped schema check. Container replacement, an unsuccessful metadata probe or
anything other than one matching head blocks before backup/migration.

One-time setup must be completed in this order:

1. Merge the reviewed workflow, wrapper, runner, and tests to `main`; keep
   `STUDIO_MIGRATION_RELEASE_ENABLED` absent or `false`.
2. Create GitHub environment `studio-production-migration`, add at least one
   required reviewer, and keep environment secrets scoped to that environment.
   If the sole operator is also the workflow initiator, do not enable
   prevent-self-review or that operator cannot approve the deployment.
3. Add environment secrets `STUDIO_MIGRATION_DEPLOY_HOST`,
   `STUDIO_MIGRATION_SSH_KEY`, `STUDIO_MIGRATION_KNOWN_HOSTS` and
   `STUDIO_MIGRATION_SIGNING_KEY` (Ed25519 PEM, generated independently with
   `openssl genpkey -algorithm Ed25519`). Install the derived public key
   (`openssl pkey -pubout`) as the root-owned trust file above. Do not print,
   commit or deliver the signing private key to the VPS. Use a new
   dedicated Ed25519 key; do not reuse the ordinary deploy key. Verify the host
   key out of band before storing the known-hosts entry.
4. On the VPS, require a clean `main` checkout owned by `studio-deploy`.
   Because the lane is still disabled, the merge-triggered workflow may select
   no VPS deploy job and therefore may not update this checkout. Deliver one
   ordinary component from the reviewed merge through the checksum-verified
   bundle transport, verify `HEAD` equals the reviewed merge SHA, then install
   the wrapper as a root-owned regular file:

   ```bash
   sudo -u studio-deploy \
     git -C /opt/elevenlabs-studio status --short
   sudo -u studio-deploy \
     git -C /opt/elevenlabs-studio rev-parse HEAD

   sudo install \
     -o root -g root -m 0500 \
     /opt/elevenlabs-studio/deploy/studio/studio-migration-release-wrapper.sh \
     /usr/local/sbin/studio-migration-release-wrapper
   ```

   Stop if status is non-empty or the printed SHA is not the reviewed merge
   SHA. Do not fetch/merge this checkout as root and do not add a GitHub
   credential to the VPS.

   For an existing installation, first deliver the reviewed exact-main source
   through the ordinary component lane, verify its SHA and install the new
   wrapper and separate public trust key through the operator boundary. Only
   then approve the signed migration release. Never run the new schema release
   with the old unsigned wrapper. Rotation requires the same protected secret
   and pinned public-key readback; a failed signature blocks release, without
   falling back to an unsigned bundle or copying the signing key to the host.

   When an additive schema prevents ordinary API checkout delivery, the operator
   may bootstrap only the wrapper from the reviewed merged main blob: verify
   current GitHub main/CI, extract this exact regular file locally, transfer to
   private staging, compare its SHA-256 on both sides and install root0500 with
   the public trust key root0400. Verify installed hashes before approving the
   migration. Do not execute staged repository code, update production data or
   use the old unsigned release to bootstrap its own authority. The signed
   migration subsequently performs the normal clean-main fast-forward itself.

5. Add only the dedicated public key to root's `authorized_keys` with this
   forced-command shape; replace the placeholder with the public key, never the
   private key:

   ```text
   restrict,command="/usr/local/sbin/studio-migration-release-wrapper" ssh-ed25519 <DEDICATED_MIGRATION_PUBLIC_KEY>
   ```

6. Verify `/etc/elevenlabs-studio/backup.env`, its referenced restic/R2 files,
   and the primary plus maintenance OAuth secret files are root-owned regular
   files with mode `0400` or `0600`. Runtime `.env` must contain complete,
   distinct primary/maintenance OAuth configuration without multiline or
   placeholder assignments.
7. Keep `STUDIO_MIGRATION_RELEASE_ENABLED=false` and dispatch the separate
   `Studio Migration Environment Probe` workflow from `main`, supplying the
   exact current 40-character `main` SHA. This environment-bound probe has no
   checkout, token permissions, secrets, SSH, database, API, or VPS action.
   Verify that GitHub first shows the job as `Waiting`, approve it as the
   configured required reviewer, and then verify the deployment review history
   records that approval. If the job starts immediately or no review is
   recorded, stop and repair environment protection; a green probe alone is not
   approval evidence.
8. Set `STUDIO_MIGRATION_RELEASE_ENABLED=true` only when a reviewed direct
   migration is actually pending and every release prerequisite is current.
   Dispatch `component=migration` from `main` with `migration_target` set to the
   one direct successor, then approve the waiting environment deployment in the
   GitHub UI. For consecutive pending revisions, repeat this as a new protected
   run for each direct successor; never select the final head while an earlier
   successor is still pending. `migration_target=head` remains appropriate when
   the repository head itself is the one direct successor. Later merged
   migration changes may select the same approval gate automatically. If
   production is already at repository Alembic head, leave the variable `false`
   and do not dispatch the migration release merely to test the gate.

When a merged change modifies the forced-command wrapper contract, reinstall
the reviewed exact-main wrapper before enabling the lane:

```bash
sudo install \
  -o root -g root -m 0500 \
  /opt/elevenlabs-studio/deploy/studio/studio-migration-release-wrapper.sh \
  /usr/local/sbin/studio-migration-release-wrapper
```

The following `0017 -> 0018 -> 0019 -> 0020` sequence is a superseded historical example, not a current migration instruction. Repository head must be read from the current Alembic scripts; literal schema numbers in this historical example are not current-state evidence. For every future release, first read the exact production revision and the exact reviewed repository head, then apply only one direct additive successor per approval and verified backup. Never copy historical literal revisions into a live command:

1. `migration_target=0018_job_part_progress`; approve and require
   `api_deployed=no` plus local/public liveness. Readiness may be intentionally
   unavailable until the repository-head successor recreates the API.
2. `migration_target=0019_job_media_clip`; approve and require
   `api_deployed=no` while repository head remains `0020`.
3. `migration_target=0020_provider_part_checkpoints`; approve and require
   `api_deployed=yes` plus localhost/public API health.
4. Disable the enable variable before the separate worker deployment.

The lane never starts or deploys the worker, calls providers or Google, reloads
nginx, restores into PostgreSQL, downgrades, retries, or rolls back. A manual
dispatch is not retry authority. If a failure marker reports
`migration_applied=yes`, do not rerun that workflow: inspect the exact database
revision and candidate/running API image, then choose a separately approved
forward recovery. The protected lane may perform the next direct successor only
when its schema-ahead proof succeeds; otherwise stop for a manual recovery
decision. If it reports `migration_applied=no`, correct the diagnosed blocker and
obtain a new environment approval before another attempt. A migration helper can
fail after Alembic has committed but before its later role checks finish. The
release script therefore re-probes the database after a helper failure and reports
`migration_applied=yes` whenever the reviewed target is already current. For a
legacy failure produced before that correction, do not trust `migration_applied=no`
alone: reconcile the helper log, exact database revision and running API image
before authorizing any follow-up.

The same reviewed `migration_target=head` has one narrow post-migration recovery
mode; it is not a generic retry. It is selected only when the database already
equals the repository-head target and the unchanged running API image advertises
exactly the target's direct predecessor. With the worker still safely stopped and
a new approved Environment deployment, the lane creates and verifies a fresh
snapshot, re-applies the database and worker role manifests, and recreates the API
from the exact candidate image. It emits `mode=post_migration_recovery` and never
invokes Alembic in this state. Any different database/API chain blocks before the
snapshot or mutation.

### Manual fallback

```bash
cd /opt/elevenlabs-studio

STUDIO_BACKUP_TAG=pre-migration \
  scripts/backup_studio_postgres_r2.sh
```

Only documented backup tags are allowed by the script: `scheduled` and `pre-migration`. Confirm backup success before setting migration confirmation.

The fallback migration command also requires the verified full snapshot ID,
the exact current and target revisions, and the captured API image ID:

```bash
STUDIO_DEPLOY_DIR=/opt/elevenlabs-studio \
STUDIO_PRE_MIGRATION_BACKUP_CONFIRMED=yes \
STUDIO_PRE_MIGRATION_BACKUP_SNAPSHOT=__REQUIRED_64_HEX_SNAPSHOT_ID__ \
STUDIO_EXPECTED_MIGRATION_FROM=__EXACT_CURRENT_PRODUCTION_REVISION__ \
STUDIO_EXPECTED_MIGRATION_TO=__ONE_DIRECT_ADDITIVE_SUCCESSOR__ \
STUDIO_EXPECTED_REPOSITORY_HEAD=__EXACT_REVIEWED_REPOSITORY_HEAD__ \
STUDIO_EXPECTED_API_IMAGE_ID=sha256:__REQUIRED_64_HEX_IMAGE_ID__ \
  scripts/migrate_studio_platform.sh
```

The migration script does not create or verify the backup and does not deploy
API; the caller must establish every value above from the same reviewed
candidate. These commands must not print secret values. Do not use the manual
fallback to bypass the protected lane or to retry a partially applied release.

## Nominal provider tariff configuration

Each job's confirmed duration and immutable public tariff produce a nominal
cost; this is not an invoice, quota/subscription allocation, currency conversion
or proof of a debit. Existing job provenance wins over later configuration.
ElevenLabs keeps its existing required worker rate/date/source settings.
Yandex asynchronous recognition can use the optional complete triple
`STUDIO_YANDEX_ASYNC_RATE_PER_HOUR_USD`, `STUDIO_YANDEX_PRICING_EFFECTIVE_DATE`,
`STUDIO_YANDEX_PRICING_SOURCE=yandex_public_api_pricing`. Configure only a verified
applicable public USD tariff and its effective date. No default is invented
and RUB/KZT prices must not be passed as USD. All three empty means explicitly
unavailable accounting and no new transcription blocker; a partial/invalid
triple fails configuration validation. A preserved valid Yandex snapshot stays
usable if the later optional configuration is removed. Normal and long-media
cost presentations preserve the selected provider's provenance. This narrow
accounting support does not claim completion of the separate Yandex REST
response/parsing workstream.

## Backup and restore rehearsal

Backup/restore rehearsal is manual and isolated:

- restore only into a separate temporary PostgreSQL database/target;
- invalidate restored sessions before any access test;
- run read-only smoke checks only;
- destroy only the temporary target after verification;
- never delete, overwrite, prune, or reset live production data from the rehearsal path.

Regular personal database backups are owned by Cloudkeep from25Oct2026 by the
owner's explicit decision. The Studio host timer was disabled/stopped; existing
R2 snapshots, credentials and protected pre-migration backups remain intact.
Cloudkeep's selected database job and its verified per-target executions are
the source of regular backup/freshness evidence. Studio does not infer their
success or failure from absence/age of a Studio snapshot. A reported failed
Studio pre-migration backup still raises an owner-scoped incident.

The historical Studio backup schedule is defined by
[studio-postgres-backup.timer](../../deploy/studio/systemd/studio-postgres-backup.timer):
every 10 hours after the previous activation. The
[backup script](../../scripts/backup_studio_postgres_r2.sh) keeps scheduled
snapshots within 7 days, 30 daily and 12 monthly snapshots; pre-migration
snapshots are kept within 90 days. These retention rules are not a fixed expiry
for every snapshot. Repository configuration alone does not prove that the
host timer is enabled or that a scheduled backup succeeded. Confirm those
conditions and the latest snapshot age from host/backup records before recovery.
The former fixed12-hour personal RPO and10-hour Studio schedule were superseded
by the owner25Oct2026 in favour of Cloudkeep scheduling. A replacement guaranteed
RPO is UNSET; a schedule and SQL delivery records alone do not establish it.
The4-hour RTO remains unchanged. Recovery measurements must identify the actual
selected Cloudkeep version/target, available Studio decryption keys and complete
application recovery. Existing R2 pre-migration snapshots remain in use.

The following is the historical/reactivation procedure, not an instruction to
enable the disabled timer during delivery. Reactivation needs an explicit owner
decision. Host installation is an explicit operator step, not a consequence of component
CD. From the verified current-main checkout at `/opt/elevenlabs-studio`, verify
the two unit files with `systemd-analyze verify`, install them root-owned0644
into `/etc/systemd/system`, run `systemctl daemon-reload` and
`systemctl enable --now studio-postgres-backup.timer`. Read back enabled/active,
the timer's next activation, the service's actual outcome and the latest
project-tagged restic snapshot. Do not dispatch a second backup while one is
running; the script also holds its existing flock. If first activation fails,
stop the timer and diagnose before retrying; never report enabled as backup
success. Preserve the existing repository, credentials, snapshots and retention.

Configure `STUDIO_ALERT_OWNER_USER_ID` in root0600 host
`/etc/elevenlabs-studio/backup.env` to the verified active personal administrator.
`STUDIO_BACKUP_MONITOR_OWNER_USER_ID` remains a deprecated compatibility input;
it no longer requires regular Studio snapshots. Backup credentials remain
host-only. Studio retains reported success/failure audit events and alerts for
an actual latest failed protected backup; a subsequent reported success clears
that operation's failure. Neither a missing event nor an old success is treated
as a Cloudkeep failure or proof of a healthy external backup. Regular Cloudkeep
delivery/overdue/target failures are evaluated in its existing monitoring contour.

The bounded automated rehearsal is
[rehearse_studio_restore.py](../../scripts/rehearse_studio_restore.py), run from
the repository root with the normal Python test dependencies and a running
Docker engine with the existing `postgres:17` CI image cached. It accepts no
production URL, existing dump, credentials or target. It creates two
network-isolated, read-only-root, tmpfs-only containers with exact image/name/
nonce verification; performs a real custom-format PostgreSQL dump and restore
of current-model synthetic data with encrypted Live drafts; and removes only
its verified containers. Its report includes snapshot age at the synthetic incident, one measured post-snapshot metadata loss, and elapsed time
to a quarantined restored state. The Linux suite requires this rehearsal;
unavailable local Docker remains an explicit local limitation, not PASS. The default comparison uses the owner-approved personal targets12h/4h; an explicit diagnostic override must supply both `--rpo-seconds` and `--rto-seconds`. Invalid or one-sided targets fail before container creation. The loss window is measured at the incident, excluding subsequent restore time; an exceeded RPO or already-over-budget quarantine fails. An in-budget quarantine reports full RTO as PENDING, never PASS, because service reactivation is outside that measurement.

The Linux integration test also checks authenticated application access on the
restored synthetic target. The Linux host accesses the owned internal bridge
directly, without published host ports. Exact image/name/nonce/network/subnet ownership is checked
before access and cleanup. A separately read current inventory authorizes
removal of the fixture cleared after backup before only the synthetic owner
and workspace are reactivated. Restored old sessions remain revoked; a fresh
synthetic session reads and decrypts retained text through the real API.
Elapsed time includes restore, reconciliation and authenticated access and
is compared against4h. Production service recovery remains unverified; no
production restore, provider, Google or notification operation is performed.

The quarantine statements in
[recovery_quarantine.py](../../apps/studio-api/studio_api/recovery_quarantine.py)
disable restored users, archive workspaces, revoke sessions/trusted devices/
Google grants/provider credentials, suppress unsent notifications, and stop
restored work and download slots with fenced leases. Text is retained encrypted
for reconciliation. Apply them in one transaction **on the isolated restored
copy before starting any runtime or allowing access**. The module is not an
ordinary application endpoint and does not grant permission for production
restore or reactivation.

A synthetic deletion after backup is deliberately absent from the restored
snapshot. The rehearsal verifies that the stale content cannot become active.
Do not reactivate identities, workspaces, tasks or exports until owner-approved
reconciliation establishes current deletion evidence from a separately trusted
source. This repository has no independent deletion ledger; if that evidence
is unavailable, retain quarantine and stop. The measured time is restoration
**to quarantine**, not proof of full service recovery, production RPO/RTO,
R2 snapshot validity, Alembic role/grant compatibility or restored source bytes.

## Reference storage isolation

Studio persists every local reference with an exact class: `transcription` or `audio_processing`. Existing rows and objects remain `transcription`; migration `0029_source_reference_class` adds the class with that safe default and does not move or delete objects. New transcription uploads use the transcription-reference boundary. New Audio uploads and reusable Audio outputs use the audio-reference boundary. Transcript outputs remain in Google Drive/Docs, not in either reference bucket.

Configuration requirements:

- `STUDIO_SOURCE_S3_*` configures transcription references and `STUDIO_AUDIO_REFERENCE_S3_*` configures audio references;
- the two bucket identities, access-key file paths, secret-key file paths and non-empty lifecycle rule identifiers must be distinct; equality or any missing boundary fails closed before upload, processing or cleanup;
- each credential pair must be restricted by the storage provider to its own bucket and required object operations only; distinct file paths alone are not permission evidence;
- each bucket must have an independently verified provider-side lifecycle rule matching its declared identifier; the identifier is configuration evidence, not proof that the rule exists or is enabled;
- endpoint URL, region, bucket, lifecycle rule identifier, pending-upload TTL, presign TTL, maximum upload bytes, multipart threshold/part size and bounded reconciliation limits are non-secret runtime settings; maximum upload bytes must be within `1..2147483647`, multipart part size must be `5 MiB..128 MiB` and no larger than the threshold, and only the safe policy subset is exposed through authenticated `no-store` DTOs;
- both access key IDs and secret access keys are provided through separate operator-managed secret files;
- object keys, private bucket names when sensitive, secret-file paths, and source bytes remain server-only;
- only the authenticated owner-scoped upload-initiation/part response may expose a PUT-only presigned URL; it must be `no-store`, expire within 60–900 seconds, and must not appear in logs, diagnostics, evidence, later metadata responses, or browser storage. Multipart upload ID, provider ETags, object key and bucket are server-only; the browser receives only source ID, part number/count/size, progress and short-lived per-part capability;
- `STUDIO_SOURCE_UPLOAD_TTL_SECONDS` defaults to 3600 seconds for unfinished uploads; post-completion retention is an allowlisted per-user PostgreSQL preference managed in PWA settings, not a runtime env value;
- API and worker must receive the same complete isolation config and secret mounts; runtime health performs a read-only `HEAD` against both exact buckets and exposes only safe per-class status values;
- deploy order is external provider setup -> protected additive migration `0029` -> API/web -> stopped-worker config validation -> worker deploy. Do not deploy the fail-closed API/worker against the old one-bucket runtime configuration;
- no rollout step copies, renames or deletes existing objects. Legacy reads and cleanup continue through the persisted/default `transcription` class after both boundaries are configured.

Large browser uploads use multipart at or above `STUDIO_SOURCE_MULTIPART_THRESHOLD_BYTES`. Migration `0032_source_multipart_authority` persists the exact protocol, provider upload-session ID, part size/count and completion time. The API validates owner, project, class, exact persisted bucket/key/session and expiry before issuing each part capability. Completion lists parts server-side, requires contiguous exact sizes, asks storage to complete, then verifies final size/MIME before marking the Source uploaded. An ambiguous part PUT is reconciled through server status before at most one same-part retry. Abort is logical and durable first; the worker later confirms both multipart-session absence and final object absence before clearing private identity. Provider-side abort-incomplete-multipart lifecycle remains required as defence in depth and must not be treated as worker cleanup evidence.

The Files & Storage reconciliation control is owner-scoped and dry-run by default. It lists only fixed owner prefixes under the two configured reference classes, stops at the configured scan/page bounds, excludes every exact Source identity still present in PostgreSQL, and protects objects newer than `STUDIO_STORAGE_ORPHAN_MIN_AGE_SECONDS`. A complete scan returns only counts/bytes plus an opaque session-bound signed plan; object names, keys, buckets and timestamps never reach the browser. Apply additionally requires CSRF, same origin, `confirm=true`, an unexpired unchanged plan, a candidate count within the apply bound, a fresh database authority check, and an exact size/ETag/last-modified match before delete. Each delete is terminal only after a missing-object `HEAD`. Any changed/truncated scan or mismatched candidate fails closed and requires a new preview. Google Drive originals, Google Docs, transcript/history/analytics rows and storage versions are outside this operation.

Before enabling the release, an operator must confirm without recording names or secrets: two distinct private buckets exist; each independently scoped credential can access only its intended bucket; each declared lifecycle rule exists and is enabled; both safe runtime health boundaries are `ready`. Missing evidence is `PENDING_EXTERNAL_GATE`, not authority to reuse the legacy bucket or credential.

## Google OAuth runtime configuration

### Studio domain cutover (DOMAIN-STUDIO-20261017)

Canonical host: `studio.cloud-nodes.net`; previous host: `studio.librechat.online`.
Same VPS167.86.68.98, deployment checkout, database, storage buckets and Google
project; no schema or data migration. The host change is an explicitly authorized
operator task, not an extension of the header-only forced-command release lane.
That lane keeps its existing Environment approval and only changes the snippet.

Preconditions and order:

1. Check exact current main/CI and absence of overlapping deploy/edge activity.
   Preserve the old working site. Back up only the two named vhost files and the
   operator-managed runtime `.env` into a root-only timestamped directory; record
   hashes/modes, never their secret contents. Do not recreate persistent volumes.
2. Add the new host's DNS to the same VPS; retain the existing Cloudflare proxy
   protection. Stage a dedicated HTTP vhost serving only the ACME webroot
   `/var/lib/letsencrypt`; other paths return503. Use the existing ACME account to
   issue the new named certificate. Keep both hosts' HTTP challenge locations for
   renewal. Validate TLS normally; do not bypass certificate verification.
3. In the existing Google project, add the new exact HTTPS origin and
   `/api/google/oauth/callback` URI to both existing primary/maintenance clients.
   Add the new host's `/*` website restriction to the existing Picker key. Preserve
   old origins, scopes, clients, keys and API restrictions during the transition.
   Add the root domain to OAuth authorized domains if Google requires it; any
   domain-verification/publication gate must be satisfied, not bypassed.
4. For each of the two input buckets, append only the new HTTPS origin to the
   existing CORS allowlist. Preserve methods, headers, expose headers and lifecycle
   rules. Do not change backup buckets or expand runtime key permissions. Verify
   actual OPTIONS responses for PUT from the new origin; a policy screenshot alone
   does not prove the browser response. Never retain signed capabilities in logs.
5. Install the merged [new vhost](../../deploy/studio/studio.cloud-nodes.net.nginx.conf)
   as the root-owned enabled site `studio.cloud-nodes.net`. Syntax-test before
   reload; verify local/public TLS, exact security headers and web/API identity.
   Retain the old site until external settings have been confirmed. New-origin
   browser mutations are not ready until the API origin is switched.
6. Check active jobs and gracefully drain the worker through the existing lifecycle
   procedure. Set only `APP_PUBLIC_URL`, `STUDIO_GOOGLE_OAUTH_REDIRECT_URI` and
   `STUDIO_GOOGLE_MAINTENANCE_OAUTH_REDIRECT_URI` to the new origin/callback in the
   protected runtime file, with an atomic update and readback of those three safe
   values. Keep all secrets, config ownership and permissions unchanged. Deploy API
   through the existing exact-main component lane; deploy the compatible stopped
   worker afterwards. No migration, key rotation or grant revocation is required.
7. After new-origin health/auth/navigation, both Google connection states,
   folder selection and bounded upload checks, install the merged
   [old-host redirect](../../deploy/studio/studio.librechat.online.redirect.conf).
   It redirects safe page requests temporarily with302 and drops query strings;
   old API calls return410 instead of replaying mutations or cookies cross-origin.
   Old OAuth callbacks return to the new connection settings without forwarding
   code/state; pending authorization must be started again on the new site.
8. Users sign in on the new origin and optionally trust that browser again.
   Browser-local drafts, cached offline pages, notification subscriptions and the
   installed old-origin PWA do not migrate with DNS. Reinstall the PWA from the new
   site and grant notifications again if desired; do not clear old local data until
   any needed draft inputs are recovered. Never promise session/cookie transfer.

Post-checks: local/public certificate verification, exact headers (including no
raw-query logging), health/readiness/schema, current web/API/worker revision/image,
new-origin authenticated navigation and OAuth/Picker/upload behavior; old root
redirect, old API mutation410 and old callback query stripping. No STT/Live call or
user-file deletion is needed. A blocked owner-console or browser check stays
PENDING and the cutover must not be reported complete.

Recovery: on failure, stop the rollout; restore only the backed-up old vhost and
three runtime settings, syntax-test/reload nginx, redeploy API and stopped worker
with the verified previous configuration and recheck the old origin. Do not roll
back the database, remove certificates, clear browser storage or delete files.
Keep new external allowlists for diagnosis until explicitly cleaned up. Do not
blindly retry an ambiguous config update or provider call.

Google OAuth runtime config is fail-closed. OAuth endpoints must remain unavailable or reject safely until required non-secret settings and a non-empty client secret file are present.

Primary Picker settings include client ID, redirect URI, scopes, state TTL, and the client-secret file path. The client secret itself stays in an operator-managed file. Current Drive/Picker integration permits only exact `openid`, email identity, `https://www.googleapis.com/auth/drive.file`, and `https://www.googleapis.com/auth/drive.readonly`. `drive.readonly` is a restricted broad-read scope required for arbitrary source-folder descendants; `drive.file` remains the output-write boundary. Full `drive` and unrelated scopes are forbidden. A primary connection missing either Drive scope or reporting an additional scope is not Picker-ready and must be disconnected/reconnected before browser-token issuance. Scope rollout may require Google OAuth consent-screen publication/verification or a security assessment; never weaken the boundary to bypass an external Google gate.

Transcript maintenance uses a second OAuth client and a different client-secret file. Its exact server-only grant is `openid email https://www.googleapis.com/auth/drive.metadata.readonly https://www.googleapis.com/auth/documents`. Configure `STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_ID`, `STUDIO_GOOGLE_MAINTENANCE_OAUTH_CLIENT_SECRET_FILE`, `STUDIO_GOOGLE_MAINTENANCE_OAUTH_REDIRECT_URI`, and `STUDIO_GOOGLE_MAINTENANCE_OAUTH_SCOPES` before the dependent API and worker rollout. The maintenance client ID and secret file must differ from the primary client. The redirect may use the same reviewed callback route. The maintenance grant must resolve to the same Google subject as the active primary connection; a mismatch is rejected and must not replace either grant.

Only `studio-api` and `studio-worker` receive and copy the maintenance client secret: API owns consent/status/enqueue authority, while worker refreshes the stored owner grant for durable execution. Do not mount it into `studio-web`, do not issue its access token to a browser, and do not record client IDs, secret paths, grant tokens, Google subjects, or email values as validation evidence.

Picker readiness is separate from OAuth readiness. `STUDIO_GOOGLE_PICKER_API_KEY` and `STUDIO_GOOGLE_PICKER_APP_ID` must be configured, non-empty, and not placeholder values. OAuth connection, Picker configuration, and writable output folder selection are three different preconditions. Do not record Picker key/app ID values in validation evidence.

The host nginx file is the single browser security-header authority. Keep script and frame sources limited to the documented Google Picker hosts; do not add `unsafe-eval` or wildcard script sources. Its `Referrer-Policy` must be `origin`: the website-restricted Picker developer key needs the public origin, while paths and query strings remain undisclosed. Do not weaken the API-key website restriction to compensate for a missing referrer. The PWA's presigned local-upload PUT uses the same origin-only document policy, disables cross-origin browser credentials and never persists or reflects the capability URL. The runtime-configured upload destination currently requires general HTTPS in `connect-src`; narrow it only after all intended production S3/R2 origins are explicit and a real Picker/upload smoke test is available. Standard component CD still does not apply or reload host nginx. Once separately bootstrapped, the protected manual Studio edge lane may update only the canonical security-header snippet under the boundary below.

### Protected Studio host-edge release

Bootstrap is a separate root/operator action. Before enabling the workflow:

1. Review `deploy/studio/studio-edge-release-wrapper.sh`, install it as
   `/usr/local/sbin/studio-edge-release-wrapper`, root-owned and mode `0755`,
   and verify its installed hash against the merged source without printing key
   material.
2. Create a dedicated SSH key for this lane. Add only its public key to root's
   `authorized_keys` with
   `restrict,command="/usr/local/sbin/studio-edge-release-wrapper"`. Do not
   reuse the component or migration deployment identity.
3. Reuse the existing protected GitHub environment
   `studio-production-migration`, already restricted to `main` and the intended
   human reviewer. Add the separately named environment secrets
   `STUDIO_EDGE_DEPLOY_HOST`, `STUDIO_EDGE_SSH_KEY`, and
   `STUDIO_EDGE_KNOWN_HOSTS` without copying their values into evidence. Do not
   reuse the migration SSH identity for the edge lane.
   For an exactly identical `DEPLOY_HOST` and `STUDIO_EDGE_DEPLOY_HOST`, the
   workflow uses the existing component `DEPLOY_KNOWN_HOSTS` as the canonical
   server pin. This shares server host identity, never the component private
   key or permissions. Otherwise only `STUDIO_EDGE_KNOWN_HOSTS` is used.
   The preparation script validates the pinned file and target match without
   network discovery or printing values. Invalid/missing pins fail before SSH;
   strict host verification and the dedicated edge identity remain required.
4. Keep repository variable `STUDIO_EDGE_RELEASE_ENABLED=false` except for one
   reviewed release window. Confirm the active site contains exactly one
   include of `/etc/nginx/snippets/studio-security-headers.conf`; the lane will
   not edit the site to create or repair that include.
   The canonical enabled site may be a regular root-owned file or a root-owned
   symlink to a direct regular root-owned file in `/etc/nginx/sites-available`.
   Link/target directories must be root-owned and not group/world writable.
   Broken links and targets outside that directory remain blocked. The release
   never creates or rewrites a site/link; an absent canonical site needs operator
   bootstrap. Preflight reports `site_layout=trusted_root_symlink` when used.

For a reviewed release, use `Studio Edge CD` manual dispatch with the full
current `main` SHA. Approve only after repository/Studio CI for that SHA is
green and the intended canonical snippet diff is reviewed. The workflow must
show both `[studio-edge-release] OK` and
`[studio-edge-release-wrapper] OK`; then verify the public response and the
feature whose browser policy changed. Return the enable variable to `false`.

On failure, stop. The release program automatically restores the exact prior
snippet only when mutation already began, runs `nginx -t`, and reloads nginx.
Do not blindly rerun a failed release, manually edit the snippet concurrently,
or treat a green skipped job as deployment evidence. Inspect the safe phase,
reason, rollback state, backup path, exact checkout SHA, and public health
before selecting a separate recovery action.

Roll out OAuth/Picker and maintenance config through API deployment only when runtime files are ready and production is migrated through `0017_google_maintenance_oauth`. Validate the primary and maintenance connection states separately with authenticated owner-scoped flows, confirm maintenance consent is required before maintenance actions, and confirm unauthenticated connection/status endpoints still reject as expected.

## Transcript maintenance target-mode canary

Google Docs standardization and **Манифест Studio** are two separately initiated stateful operations. Each panel independently offers one recursive folder tree or one Google Doc. A merged source revision, green CI, successful component deployment, maintenance consent, or an authenticated browser smoke does not authorize any `apply`. Every operation/mode pair requires its own selected target, reviewed dry-run, and explicit apply decision. Standardization may update eligible Google Docs in place; **Манифест Studio** does not change Docs and writes only eligible current-document metadata to PostgreSQL.

### Preconditions

- Use only merged `main` with green required CI and verified web/API commit and image identities.
- Transcript maintenance OAuth was introduced by `0017_google_maintenance_oauth`; durable execution requires additive `0028_transcript_maintenance_runs`. The repository head must be read from current Alembic scripts; actual production revision must be read and checked against the exact deployed API before the canary. Apply only the direct reviewed successor with its own tagged pre-migration backup and protected release before dependent API/worker deployment.
- Verify public and localhost health, API migration readiness, and an authenticated owner-scoped session.
- Verify the primary Picker connection has exact `openid email drive.file drive.readonly`, then complete the separate server-only maintenance consent with the same Google account and exact maintenance scope boundary.
- Prepare a small approved recursive canary root containing copies or otherwise explicitly approved representative documents and one approved single-document canary. The server scans the entire selected root tree in folder mode and only the exact selected native Google Doc in document mode; stop if either boundary differs from the approved target.
- Keep transcription jobs and provider processing out of this operation. Maintenance runs use the worker only for Drive/Docs execution after normal audio/transcription claims; they must not create a transcription job or call a transcription provider. Worker rollout is therefore required for this revision but is not provider-call authority.

### Dry-run and authorization

1. Open `Транскрибации → Подготовка документов`, select the separate **Стандартизация Google Docs** or **Манифест Studio** operation, choose the intended mode, and select exactly one approved root folder or Google Doc through the app-owned Drive dialog.
2. Run that operation's `dry-run` only. Enqueue must return promptly, after which the owner-scoped UI restores persisted stage/progress to a terminal preview. The preview is non-mutating, browser-safe, rate-limited and bound to that workflow/target; apply still performs fresh server revalidation.
3. In folder mode review selected, action, unchanged, blocked, skipped-file, and descendant-folder counts. In document mode verify exactly one document was checked. Current documents must be skipped by standardization; already-cataloged current documents must be skipped by **Манифест Studio**. Stop on an unexpected target boundary, global scan failure, or unexplained blocked candidate.
4. Record only the non-private mode, safe aggregate counts, and the operation-specific decision. Do not record folder IDs, document IDs, document names, document bodies, Google payloads, access tokens, subjects, emails, or URLs.
5. Authorize exactly one apply for exactly one operation/mode/target. A standardization preview or apply never authorizes **Манифест Studio**, the inverse is also true, and changing the mode or target requires a new dry-run.

### Apply and post-check

1. Apply once from the reviewed PWA panel. Do not send the endpoint manually or start parallel apply requests.
2. A per-document inaccessible, unreadable, empty, unsafe, unsupported, or conflicting candidate is reported as blocked without aborting safe siblings. A global authorization, rate-limit, availability, timeout, malformed-scan, or traversal-limit failure aborts the operation. On a global or incomplete result, stop and do not retry blindly.
3. Review aggregate apply outcomes, then run a new dry-run for the same mode,
   target, and operation. Successfully standardized documents should now be
   current; successfully imported catalog entries should now be
   unchanged/already present. If a successfully imported entry is offered for
   import again, do not apply again: record only safe aggregate evidence and
   stop for source/deployed-image/catalog-authority reconciliation.
4. For standardization only, manually inspect approved canary copies or Google version history to confirm content preservation and the intended versionless `transcript_doc` structure: title `Heading 2`, ordinary transcript body `11 pt`, and Russian `Спикер N:` bold `14 pt`. Do not copy transcript text into evidence. **Манифест Studio** must leave Google Docs unchanged.
5. Confirm that neither operation created a transcription job, provider attempt, output document, or worker activity. Record only safe aggregate or normalized audit evidence.

### Recovery boundary and evidence

A PostgreSQL restore can recover catalog metadata, but it does not automatically revert Google Docs changed by standardization before a database failure. Google recovery depends on approved canary copies or Google version history. If standardization may have partially changed external documents, do not automatically rerun apply, delete documents, restore production PostgreSQL, or broaden permissions. Stop and make recovery a separate operator-reviewed stateful task.

Safe evidence includes the merged commit, required CI result, deployed web/API image identities, database revision, backup snapshot ID, public and localhost health, non-private target mode, aggregate dry-run/apply counts, absence of provider/job mutations, and the explicit operator approval. It must exclude private folder/object identifiers, document names or bodies, Google responses, credentials, and tokens.

## Operational incidents and optional Telegram

Migration `0033_observability_alerts_audit` is the additive authority for
cross-boundary `trace_id`, explicit audit outcome, database-enforced append-only
audit rows, owner-scoped operational incidents and bounded delivery attempts. The
PostgreSQL trigger rejects `UPDATE` and `DELETE` on `audit_events`; ordinary API
and worker roles must keep only their required read/insert grants. `TRUNCATE`,
trigger removal and downgrade remain maintenance/migration actions and are never
application recovery mechanisms.

The idle worker evaluates active owners at the configured bounded interval. It
does not evaluate or deliver after a stop signal and it never holds a database
transaction during Telegram network I/O. Current deterministic signals are:

- allowlisted critical API/worker diagnostics;
- queued jobs older than `STUDIO_ALERT_STUCK_QUEUE_SECONDS` or processing jobs
  whose lease is already expired;
- at least `STUDIO_ALERT_PROVIDER_FAILURE_THRESHOLD` provider unavailable,
  timeout or `5xx` occurrences inside `STUDIO_ALERT_SIGNAL_WINDOW_SECONDS`;
- transcript-maintenance or source-storage-cleanup failures;
- the latest owner-scoped PostgreSQL backup outcome when it is `failed`;
- remaining provider-period units at or below
  `STUDIO_ALERT_LIMIT_REMAINING_PERCENT`, but only when an authoritative current
  account snapshot contains both period limit and remaining values;
- Studio-managed local-reference bytes near `STUDIO_ALERT_STORAGE_LIMIT_BYTES`,
  but only when the operator has configured that known limit. An absent storage
  limit is `not_configured`, not zero and not proof of unlimited capacity.

Warning signals require a repeated evaluation before firing. Critical signals
fire immediately. One owner/kind row owns `pending → firing → acknowledged →
resolved`; lifecycle generation, a unique delivery key, cooldown, bounded retry
count and a stale-claim terminal state prevent an unbounded alert storm. An
acknowledgement suppresses only a not-yet-sent firing delivery and does not
resolve the underlying signal. Recovery is produced only after a previously
firing/acknowledged signal clears.

Telegram is optional and disabled by default. To enable it, create two distinct
operator-managed regular secret files outside the checkout, normally root-owned
`0600`: one bot token and one numeric chat ID. Set their host paths in
`STUDIO_ALERT_TELEGRAM_BOT_TOKEN_FILE` and
`STUDIO_ALERT_TELEGRAM_CHAT_ID_FILE`, set
`STUDIO_ALERT_TELEGRAM_ENABLED=true`, and recreate only the reviewed API/worker
components after migration and configuration validation. Never print either
file, pass its content in `.env`, or reuse a reference-storage credential file.
The UI reports Telegram as ready only when both mounted files can be read and
pass their bounded shape checks. Email remains explicitly `not_configured`; no
SMTP transport is implied by this Goal.

Telegram text contains only the product name, lifecycle state, allowlisted
summary and severity. It never includes owner email, source/job/document IDs,
filenames, object keys, transcript text, provider response, URL, token or stack
trace. Delivery timeout is bounded; provider response bodies are discarded; a
failed send records only an allowlisted error code. Disable the transport first
if credential validity is uncertain—do not diagnose by printing a token or by
sending an uncontrolled production message.

For host PostgreSQL backups, configure only the personal owner UUID as
`STUDIO_ALERT_OWNER_USER_ID` in `/etc/elevenlabs-studio/backup.env`. The reviewed
backup script asks the already-running API container to append one `success` or
`failed` outcome after the backup attempt. Failure to record that secondary
outcome is reported safely but never changes the original backup exit code. An
absent owner UUID leaves the legacy backup behavior unchanged. Do not invent a
failure outcome merely to test alerts.

Safe rollout order is: protected additive migration → API/web component delivery
→ stopped-worker configuration/DB-role verification → worker deploy/status. A
green component health check proves neither incident evaluation nor Telegram
delivery. Production verification without external messaging may inspect an
existing naturally occurring safe signal or use the dedicated internal canary;
a real Telegram send requires separate action-time owner authorization. After
the exact migrated API revision is healthy, run the canary once with the approved
active personal owner UUID:

```bash
docker compose \
  --env-file deploy/studio/.env \
  -f deploy/studio/compose.platform.yml \
  exec -T studio-api \
  python -m studio_api.cli run-observability-alert-canary __OWNER_USER_UUID__
```

The command uses a dedicated `operator_canary` kind, creates the warning,
observes it twice, resolves it, and suppresses both firing and recovery delivery
rows before the single transaction becomes visible. It therefore cannot collide
with a real signal and cannot be claimed by the worker, even if Telegram is
configured. Accept only `OBSERVABILITY_ALERT_CANARY_OK` with `status=resolved`,
one incremented generation, two observations for that generation and an opaque
valid `trace_id`. Then confirm through the authenticated owner endpoint/UI that
the recent recovery is visible and carries the same safe trace through its audit
record. Do not print the owner UUID in durable evidence, rerun merely to change a
timestamp, or use a real failure/provider/storage mutation as a substitute.
Stop on duplicate deliveries for one lifecycle generation, cross-owner data,
unbounded retry, secret-bearing output, unknown storage/account limits or an
unexpected provider/Google call. Do not restart services, requeue jobs, mutate
audit history or delete storage as alert remediation.

## Personal access/security email

Personal mail remains deferred by the owner25Oct2026. Task notifications use
Telegram only. The inactive security-mail implementation below is retained for
future separately selected activation, and is not needed for operator recovery.

### Personal owner recovery without email

Use a saved one-time recovery code when only the authenticator is lost. When
the owner has lost the local password, an authorized operator uses the existing
SSH/root boundary on Contabo167.86.68.98. Verify the current deployment, local
active admin identity and absence of another recovery operation first. Determine
the exact existing owner UUID through a private read-only account lookup; never
create another bootstrap account or put a password into shell args/env/history.

From an interactive authorized root console in `/opt/elevenlabs-studio`:

```bash
docker --host unix:///var/run/docker.sock compose \
  --env-file deploy/studio/.env -f deploy/studio/compose.platform.yml \
  exec studio-api python -m studio_api.container_entrypoint --drop-only \
  python -m studio_api.cli recover-local-owner OWNER_UUID
```

The command requires a terminal, exact email confirmation and twice-entered
hidden password. It changes only an existing active local admin, revokes all
its sessions/trusted browsers and pending reset capabilities, and records an
operator recovery event without impersonating a browser session. TOTP remains
enabled by default. If both authenticator and saved codes are unavailable,
select `--reset-totp` only after separately verifying the owner and explicitly
typing the additional second-factor confirmation. This retires only that
owner's factor/codes, records a distinct audit event and requires new TOTP
enrollment after the owner logs in. No email or Telegram reset link is sent.

After a successful command, the owner logs in with the new password and retained
TOTP/recovery code (or enrolls a new factor after explicit factor retirement).
Confirm old sessions/trust are rejected and the scoped audit event exists.
Unknown outcome requires state inspection, not a blind repeat. This procedure
must be tested with synthetic accounts; never reset the real owner's credentials
as a delivery smoke check.

### Deferred security-mail transport

`STUDIO_SECURITY_EMAIL_ENABLED` is false by default. Enable it only after the
owner selects the sender domain, SMTP service and From address. Set
`STUDIO_SECURITY_EMAIL_SENDER_DOMAIN` to the exact From domain; the API and
worker must have matching settings. The transport uses the existing
`STUDIO_JOB_SMTP_*` settings with exactly one TLS mode and a protected password
file. Reuse of a job-notification SMTP account needs explicit owner approval;
security delivery does not enable job notifications or change owner opt-ins.
Do not put SMTP passwords into `.env` or test fixtures.

Migration `0041_source_retention_default` adds the encrypted transactional outbox.
Apply and verify the reviewed worker role manifest after migration: mail
dispatch needs SELECT/UPDATE only; reset challenges remain API-owned. Rollout
follows the existing backup/migration → API/web → stopped-worker config/role
verification → worker order. Without configured mail, reset requests report
`not_configured` uniformly and no email is sent. Health alone does not confirm
domain ownership, SMTP acceptance or inbox delivery.

Reset links expire after 15 minutes and are single use. Requesting a newer
link invalidates earlier challenges and pending mail. Successful reset revokes
sessions and trusted browsers; account security changes create separate
deduplicated notifications. Delivery claims expire after60 seconds, retries
are bounded to3 with backoff, expired/reset-cancelled payloads are erased.
SMTP may accept a message before worker failure or an expired slow-send claim: a retry can
resend its stable Message-ID, but the reset token still works once.

Synthetic transport/transaction/expiry checks run without real mail. An
operator-approved delivery test must use a selected test recipient and verify
the exact deployed revision, settings presence, outbox outcome and inbox;
never print the token, body, ciphertext or credentials. Wrong domain, TLS,
secret or role stops dependent activation without blocking unrelated UI fixes.

## Automatic retry and owner job notifications

Migration `0035_job_notifications` adds the automatic-retry schedule, explicit
owner channel preferences, historical encrypted Web Push subscriptions and a durable
terminal-delivery outbox. From25Oct2026 only Telegram task notifications are supported;
email/Web Push activation is rejected and legacy preferences cannot enqueue sends.
The historical tables/DTO keys remain compatible during rolling delivery. A completed or
failed job creates Telegram delivery rows only when the owner already enabled it;
retry/recovery suppresses obsolete pending rows before a new attempt. Claim and
completion use separate transactions, so Telegram network
I/O never holds a database transaction. Stale claims, retry attempts and
backoff are bounded; transport bodies, provider URLs, transcript text,
filenames, document IDs and credentials are not persisted in delivery status.

Automatic job retry is limited to three total processing attempts. It accepts
only durable `retry_safe` evidence for `source_materialization_unavailable`,
`media_preparation_timeout`, `provider_rate_limited`, or the pre-provider
`provider_usage_accounting_unavailable` boundary. Backoff is 30 seconds after
the first failed attempt and 60 seconds after the second. A missing attempt
record, cancellation, non-allowlisted failure, exhausted limit, provider
timeout/unavailability, partial/returned result, Google handoff or output
reconciliation uncertainty stays terminal and requires the existing explicit
owner recovery flow. Never requeue such a job with direct SQL.

Telegram job notifications are separate from operational alerts and use their
own bot-token/chat-ID files with `STUDIO_JOB_TELEGRAM_ENABLED=true`. Configure
`STUDIO_JOB_TELEGRAM_OWNER_USER_ID` to the exact existing personal owner UUID;
other/disabled owners cannot opt in or claim deliveries for that configured chat.
Keep the token and exact selected chat ID in separate operator-managed secret
files referenced by `STUDIO_JOB_TELEGRAM_BOT_TOKEN_FILE` and
`STUDIO_JOB_TELEGRAM_CHAT_ID_FILE`; never put the token in `.env` or chat/logs.
The recipient must first start the owner-selected bot. Do not reuse an alert
bot or another project's credentials implicitly. Both API and worker need the
same owner/configuration, and Settings still requires the owner's explicit opt-in.
The transport requires Telegram's positive message acknowledgment rather than
HTTP200 alone. Outbox rows/claims are deduplicated; a lost network acknowledgment
can still make a bounded retry send a duplicate externally (at-least-once transport).

Safe rollout order is: reviewed additive migration and grant re-apply/verify →
API/web deployment → stopped-worker configuration and role verification →
worker deployment/status. With Telegram disabled, bounded LIVE may
verify schema, API preferences, service-worker assets, worker health and zero
external sends. Enabling a transport or sending a real notification requires
separate action-time owner authorization. Stop on an unexpected enabled
channel, unreadable/malformed secret, duplicate terminal row, unbounded retry,
cross-owner delivery, sensitive payload or any provider/Google call made only
for notification testing.

## Provider-neutral STT and Yandex SpeechKit

Migration `0036_stt_multiprovider` adds the explicit batch operating mode,
owner dictionaries, durable Yandex operation authority and provider/mode
health state. Apply it only through the protected migration lane, then reapply
and verify API/worker direct grants before recreating either runtime. Deploy
the API and web at the same exact revision, publish the exact nginx edge
configuration for `/api/realtime/yandex`, and deploy the worker last.

`STUDIO_ELEVENLABS_BYOK_ENABLED=true` preserves the existing provider.
Yandex is fail-closed by default and appears unavailable while
`STUDIO_YANDEX_BYOK_ENABLED=false`. Enable it only after the owner has accepted
the provider data boundary and has created a minimum-scope Yandex API key for
the intended catalog. In Settings the owner adds a separate `Yandex
SpeechKit` profile with that key and its catalog/folder ID. Never reuse or
copy an ElevenLabs, Google, R2 or database credential. The folder ID is
configuration metadata; the API key stays encrypted in the existing BYOK
credential boundary.

The provider catalog maps `economic`, `standard`, `premium` and `realtime` to
operator-configured models. Defaults are `scribe_v2` / `scribe_v2_realtime`
for ElevenLabs, `deferred-general` for Yandex economic, and `general` for the
other Yandex modes. No selection performs automatic cross-provider fallback.
Unsupported language, diarization, dictionary or size/duration combinations
fail before dispatch. Owner dictionaries accept at most ten selected
dictionaries and project at most one hundred normalized terms into providers
that advertise dictionary support; Yandex currently rejects dictionary use
instead of silently ignoring it.

Yandex batch preparation produces one mono OGG/Opus object, bounded to 60 MiB
and four hours. The worker commits the opaque provider operation ID before its
first status poll, polls with the configured bounded interval/deadline, then
encrypts the normalized terminal result. A completed operation resumes without
resubmission. A known failed operation remains terminal; do not delete or edit
operation rows to force a retry.

Yandex realtime uses a same-origin, short-lived signed Studio WebSocket
capability and an API-side bidirectional gRPC relay. The relay rechecks the
active credential version and project ownership, accepts mono PCM16 at 16 kHz,
limits each chunk to 256 KiB, the session to 10 MiB and five minutes, and never
persists audio or the long-lived provider key. The exact nginx location disables
access logging because the capability is in the WebSocket query. A new session
always requires a fresh capability.

The browser/OBS overlay receives only partial/committed text through a
project-filtered local browser channel. YouTube closed-caption and generic
HTTPS webhook destinations are explicit ephemeral per-tab values. Generic
webhook hosts must be present in `STUDIO_REALTIME_WEBHOOK_ALLOWED_HOSTS`;
private/non-HTTPS destinations and redirects fail closed. Consumer errors are
shown locally and never stop the primary capture/STT session. Do not put an
ingestion URL into logs, diagnostics or durable configuration.

A no-spend rollout verifies migration/head, exact component identities,
authenticated provider catalog, Yandex-disabled state, dictionary CRUD,
realtime capability rejection without a Yandex profile, and public/API health.
It must not call either paid STT provider, upload audio, mutate Google Drive,
open a real Yandex gRPC session or send a YouTube/webhook caption. Enabling
Yandex or sending a real external caption requires separate action-time owner
authorization and valid provider/destination configuration.

## Component deployment

Web and API are separate deployable components.

- Web deployment rebuilds/recreates only the web component, verifies image identity, then checks localhost health.
- API deployment rebuilds/recreates only the API component, verifies image identity, then checks dependency/schema-aware localhost `/api/readyz`; legacy `/api/healthz` remains a readiness alias.
- A migration mismatch blocks API deploy success/readiness.
- Component CD checks out the exact trusted `main` revision on the GitHub-hosted runner with persisted checkout credentials disabled, creates a commit-identified Git bundle, verifies its SHA-256 after transfer over the existing host-key-verified deployment SSH boundary, and fetches the bundle locally into the production checkout. The temporary bundle is mode `0600`, owner-scoped and deleted after the attempt. Production therefore needs no outbound GitHub credential or anonymous GitHub fetch; the allowlisted repository-local `origin` is still validated, and repository-local credential helpers, URL rewrites and config includes remain fail-closed. Never put a PAT, password or username-bearing capability URL into the production remote.
- Ordinary component CD does not deploy/start/recreate `studio-worker` and does not maintain PostgreSQL, Redis, migrations, backups, restores, nginx, volumes, runtime secrets, or stateful services. The distinct protected migration lane is limited to the sequence documented above.
- Failed component health checks fail loudly and must not trigger unreviewed destructive rollback.

## Manual processing preflight

Before any processing rollout or canary, verify without printing sensitive values:

- target checkout, branch, remote, and deploy directory identity;
- tracked working tree state is clean or explicitly reviewed;
- runtime env/secret files exist where expected, without displaying values;
- PostgreSQL and Redis health;
- both reference-storage boundaries, distinct secret-file paths and declared lifecycle identifiers are complete;
- primary Google OAuth config is complete and authenticated for the smoke account;
- maintenance OAuth uses a separate client/secret, exact server-only scopes, and the same Google account;
- Picker runtime config has non-placeholder `STUDIO_GOOGLE_PICKER_API_KEY` and `STUDIO_GOOGLE_PICKER_APP_ID` values without recording them;
- primary OAuth scopes equal `openid email drive.file drive.readonly`; maintenance scopes equal `openid email drive.metadata.readonly documents`; changed scopes have been handled by the corresponding disconnect/reconnect if needed;
- credential master key and encrypted BYOK records are usable;
- exactly one intended active ElevenLabs BYOK credential exists for the smoke account;
- writable Google output folder selection exists;
- production database revision is known and compared to the exact reviewed repository Alembic head for the intended deployment;
- exactly one worker instance is intended for the canary.

The host preflight validates current API Compose-mounted runtime secret files only
through the reviewed `container_entrypoint --validate-mounted-secret` mode inside
the healthy API container. That mode accepts only keys from the entrypoint's
secret allowlist, performs no copy or write, emits no value, and exits before
starting an application command. Both reference-storage credential pairs additionally receive
their bounded structural/placeholder validation. Do not replace this with direct
deploy-user reads, stale runtime-tmpfs inspection, relaxed host permissions, or
ad-hoc root commands.

The separate worker password is not mounted in the API, and a stopped worker
must not be started to inspect it. Its preflight uses one ephemeral metadata-only
helper on the immutable image ID of the single healthy API container, with
`--pull never`, no network, read-only root filesystem, all capabilities dropped,
no privilege escalation and bounded CPU/memory/PIDs. Only the configured parent
directory is bind-mounted read-only, with submounts excluded, so `lstat` can
reject a symlink leaf without following it. The reviewed stdin program uses
Python isolated/no-site mode; it checks only regular-file type, root ownership,
`0400`/`0600`, nonempty bounded size and a root-owned non-writable-by-others
parent. It never opens secret bytes or lists the directory, receives no runtime
environment secrets, and emits no values. The running API is not changed and
receives no worker credential. Missing helper image, API identity change,
missing file or invalid metadata blocks preflight. A root-only `0700` parent is
valid and does not require deploy-user visibility, chmod, ACLs or credential
copying. This metadata check does not prove DB authentication; the separate role,
schema and deployed worker health gates remain required.

## Controlled worker rollout sequence

1. Keep `studio-worker` stopped until migration and runtime readiness are confirmed.
2. Create/confirm the tagged pre-migration database backup if a migration or stateful rollout is involved.
3. Verify production database revision equals the exact reviewed repository head where the intended deployment is expected to be current.
4. Deploy web/API only through the approved isolated component deployment model.
5. Verify intended commit/image identity, component-baked release/build/commit identity, localhost readiness, public readiness, authenticated session behavior, and output endpoint availability without exposing another owner’s data.
6. Start exactly one `studio-worker` from the intended image with no public HTTP port.
7. Verify worker configuration, bounded opaque process identity, and idle polling without creating or mutating jobs.

Starting or deploying the API does not prove the worker was recreated or that processing is production-live.

## Controlled canary

Run exactly one bounded canary:

- one approved smoke account and project;
- one small supported source;
- existing ElevenLabs path only;
- one active owner-scoped BYOK credential;
- one authenticated Google connection;
- one selected writable output folder;
- one queued job only after prerequisites pass;
- no automatic retry and no second job.

Observe safe metadata only: claim, lifecycle, terminal success/failure, attempt count, output count, and browser-safe output metadata. On success, confirm exactly one persisted output entry and manually verify that the expected Google document opens in the selected folder without recording its URL/ID/body.

## Stop conditions

Stop the worker and do not retry automatically on:

- database revision mismatch;
- missing runtime config or secret file presence;
- unexpected worker startup error;
- lease expiry, lease ambiguity, fencing loss, or cancellation uncertainty;
- provider or Google authentication rejection;
- output side-effect uncertainty;
- duplicate or unexpected Google document creation;
- wrong output folder;
- missing persisted output after possible external document creation;
- unsafe/secret-bearing evidence;
- unknown exception or state transition.

Any exception between claim commit and transition to `processing` blocks the smoke and blocks a production-live claim.

## Recovery boundary

Stopping the worker must not automatically requeue, delete, retry, downgrade, remove output rows, or delete Google documents. Do not clear leases with direct SQL during smoke recovery. Do not run destructive Docker Compose `down`, prune, volume removal, automatic downgrade, automatic job reset, provider retry, Google document deletion/recreation, or output-row deletion.

Output-side-effect uncertainty requires a separate reconciliation item. API/web rollback requires an explicitly reviewed database-compatible operator decision.

### Partial-provider continuation

`partial_provider_result` is not automatic retry authority. On deployments containing migration `0020_provider_part_checkpoints`, the owner-scoped job detail may offer one of two explicit actions:

- continue only missing ElevenLabs parts when an exact contiguous set of encrypted, unexpired completed-part checkpoints validates; or
- restart the full file only when checkpoints are unavailable and either the last durable underlying failure is safely classified as provider authentication rejection, request rejection, or rate limiting, or provider usage for the returned first part is confirmed while no pending provider call and no persisted checkpoint remain.

Both actions require an explicit provider-cost confirmation. A continuation may still charge for every missing part. A full restart may charge for the entire file. Never simulate either action with SQL, direct worker invocation, direct provider calls, or job-status edits. Automatic lease recovery must remain blocked for this state.

Before approving an owner retry, inspect browser-safe metadata only: job status, aggregate error, safe provider category, completed/total parts, checkpoint availability, confirmed accounting state, attempt count, and selected action. Do not inspect transcript content, checkpoint ciphertext, raw provider response, source bytes, secrets, or external document identifiers. Stop if the category is timeout, unavailable, malformed response, lifecycle/lease loss, generic persistence failure, unknown, accounting is uncertain, a provider call remains pending, or readiness reports unavailable. A specifically classified confirmed-but-uncheckpointed first part may offer only the cost-confirmed full restart above; it is not automatic recovery authority. Checkpoints expire within 24 hours and are removed on completed output, cancellation, explicit full restart, or worker cleanup; expiry is expected and is not a reason to bypass the API gate.

## Residual limitations

Current known limitations remain:

- no exactly-once Google document creation guarantee;
- no automated output reconciliation;
- no safe automatic retry/recovery;
- bounded PostgreSQL lease heartbeat is source-level only until deployed/validated; it is not a retry system and does not prove production-live processing;
- no Studio manifest mutation;
- no OpenAI Studio processing parity;
- no multi-worker production validation;
- no production-live claim from documentation, CI, deployment, or idle worker evidence alone.

## Runtime report template

```text
Date:
Operator:
Commit:
Database revision:
Web/API deployed: pass/fail/blocked/not-run
Worker running exactly once: pass/fail/blocked/not-run
Canary job created exactly once: pass/fail/blocked/not-run
Terminal job state:
Persisted output count:
Expected document opened in selected folder: pass/fail/blocked/not-run
Unsafe evidence avoided: pass/fail
Stop condition triggered:
Production-live claim allowed: yes/no
Notes:
```

## Official worker lifecycle operations (`PWA-WORKER-OPS-01`)

The `studio-worker` is an explicit manual-only component. Worker deployment success is operational evidence for a started process and image identity only; it is not queue progress, provider readiness, Google readiness, production-live processing, or canary success. An idle healthy worker is not processing proof.

### Worker operational health meaning

The worker healthcheck runs inside the worker container with:

```bash
python -m studio_api.worker_health --mode readiness
```

Readiness verifies PID 1 has the worker process shape, the runtime has exact UID/GID `10001` with no supplementary groups, the component-baked identity is exact, PostgreSQL answers as login `studio_worker`, that role has the expected non-superuser attributes and required/prohibited grants, the database is at the reviewed Alembic head, and the authoritative heartbeat belongs to this exact container-process incarnation and commit and is not stale. `python -m studio_api.worker_health --mode liveness` checks only PID 1 and process identity and deliberately does not load runtime configuration or touch dependencies. Neither mode claims jobs, reads job payloads, calls providers, calls Google, uses Redis as queue logic, or checks object storage. Readiness updates no state; the worker process owns the heartbeat write.

### Worker status

```bash
cd /opt/elevenlabs-studio
STUDIO_DEPLOY_DIR=/opt/elevenlabs-studio scripts/manage_studio_worker.sh status
```

The status command reports only safe container state, exit code, drain state, Docker health, running/stopped container image ID, current commit tag presence, commit tag image ID, identity match, rollback-candidate presence and effective Docker CPU/memory/swap/PID/read-only/capability/security/network values. `isolation_match=yes` requires the reviewed two-CPU, 4-GiB/no-swap, 256-PID, read-only-root, capability and two-network contract; any other effective state is `no`, not success. Any worker lifecycle operation, including status, drain, pause, resume, deploy, and rollback, blocks fail-closed with `STUDIO_WORKER_OP_BLOCKED reason=multiple_worker_containers` (or the deploy equivalent) if more than one `studio-worker` container is discovered; multiple containers are an invalid topology, not a supported mode. Only `container_state=exited` with `exit_code=0` is `drain_state=gracefully-drained`; non-zero exits, including `137` and `143`, are `abnormal-exit` and are not paused/drained. It prints `STUDIO_WORKER_STATUS_OK` when the read-only status check completes, even when the worker state itself requires operator review.

### Application database roles and credential rotation

The ordinary API must connect as `studio_api`; protected Alembic execution uses
`studio_migrator`; `studio_owner` owns the `public` schema and application
objects but cannot log in. The PostgreSQL bootstrap login `studio` remains only
on the PostgreSQL service and explicit operator path. It must never be mounted
into the API or worker as a rollback shortcut.

Before the first switch, create two different root-owned `0400` or `0600`
password files outside the checkout and set their paths in
`deploy/studio/.env`:

```text
STUDIO_API_POSTGRES_PASSWORD_FILE=/opt/elevenlabs-studio-secrets/studio_api_postgres_password
STUDIO_MIGRATOR_POSTGRES_PASSWORD_FILE=/opt/elevenlabs-studio-secrets/studio_migrator_postgres_password
```

Do not paste either value into `.env`, a command argument, Git, logs or a
diagnostic bundle. `scripts/configure_studio_database_roles.sh apply` accepts
only distinct nonempty root-owned regular files and sends password changes to
`psql` through stdin. On an empty database it prints
`STUDIO_DATABASE_ROLES_BOOTSTRAP_OK`; after schema creation it must print
`STUDIO_DATABASE_ROLES_OK`. Read-only verification is:

```bash
cd /opt/elevenlabs-studio
STUDIO_DEPLOY_DIR=/opt/elevenlabs-studio \
  scripts/configure_studio_database_roles.sh verify
```

For a clean installation, apply the roles before Alembic, identify the empty
revision explicitly as `base`, run the reviewed `base -> head` migration through
the backup-gated migration script, then re-apply/verify both application and
worker grant manifests before starting application services. For an upgrade,
the protected migration lane already applies the application roles before the
migration and both grant manifests after it. A missing new-table grant is a
blocked release, not authority to broaden the role.

Credential rotation is a bounded maintenance window: keep the worker drained,
stage one new protected file atomically, run application-role `apply`, recreate
only the affected API or migrator tool with the same reviewed Compose contract,
then run `verify` and API readiness. Rotate `studio_api` and
`studio_migrator` separately. Keep the immediately previous protected file only
for the bounded recovery window. If readiness fails before the new credential
is verified, restore that one previous file, run `apply` again, recreate the
same component and re-run `verify`; do not change `STUDIO_DATABASE_USER` to
`studio`. After success, destroy the superseded credential through the approved
secret-owner procedure.

`verify` checks non-superuser/non-owner login attributes, the sole migrator-to-
owner membership, absence of API memberships, object ownership, positive CRUD
allowlist and negative DDL/TRUNCATE/audit/Alembic/provider-checkpoint writes.
`disable-logins` is an incident stop action that disables both application
logins; it causes downtime and is not a normal rollback.

### Personal TOTP break-glass

Normal TOTP enrollment, recovery-code replacement and disablement happen only
in the authenticated Account screen after recent password verification.
Recovery codes are displayed once, stored only as hashes and consumed once.
Password-reset delivery is intentionally not configured; do not imply that the
request endpoint sends mail.

If the single owner has lost both the authenticator and every recovery code, an
operator may use the no-HTTP-route break-glass command after independently
confirming the exact owner email:

```bash
cd /opt/elevenlabs-studio
docker compose --env-file deploy/studio/.env \
  -f deploy/studio/compose.platform.yml \
  exec -T studio-api \
  python -m studio_api.container_entrypoint --drop-only \
  python -m studio_api.totp_break_glass \
  --owner-email '__EXACT_OWNER_EMAIL__' \
  --confirm-owner-email '__EXACT_OWNER_EMAIL__' \
  --reason recovery-codes-unavailable \
  --confirm-revoke-all-sessions
```

Allowed reasons are `lost-authenticator` and `recovery-codes-unavailable`.
Success disables only that active owner factor, removes unused recovery codes,
revokes every session and writes `auth.totp_break_glass_disabled`; it prints no
email, TOTP secret or recovery code. The owner must sign in again and perform a
fresh enrollment. Any identity mismatch, inactive/non-admin account, absent
active factor or transaction failure blocks without a silent bypass.

### Dedicated worker database role and tariff snapshot

Before the first isolated worker deploy, stage a separate root-owned password file outside the checkout, set `STUDIO_WORKER_POSTGRES_PASSWORD_FILE` in `deploy/studio/.env`, and configure the three non-secret tariff fields shown in `.env.example`. Do not reuse the PostgreSQL bootstrap password. With the worker absent or gracefully drained and the trusted checkout clean, apply and verify the reviewed direct-grant role:

```bash
cd /opt/elevenlabs-studio
STUDIO_DEPLOY_DIR=/opt/elevenlabs-studio scripts/configure_studio_worker_db_role.sh apply
STUDIO_DEPLOY_DIR=/opt/elevenlabs-studio scripts/configure_studio_worker_db_role.sh verify
```

The script reads the password only from the root-owned `0400`/`0600` file, sends it to `psql` over stdin and prints no credential. It revokes broad table/sequence access and any role memberships before granting the current worker allowlist; new tables receive no implicit worker access. `verify` is read-only. `disable` changes the role to `NOLOGIN` and is an explicit operator recovery action only after a safe worker drain; it is not a normal rollback step.

Attribute verification evaluates one boolean predicate in PostgreSQL and accepts only the single `psql` result `t`; an absent role, unexpected attributes, query failure or unavailable Git status must block. If `apply` committed but a verifier defect stopped the flow, deliver the reviewed correction and run `verify` first. Do not repeat grants/password activation or start the worker merely to bypass a failed verification.

The worker allowlist includes **SELECT only** on `public.alembic_version`: both
deployment's `alembic current` and runtime readiness read the schema revision
through the dedicated worker login. INSERT/UPDATE/DELETE/TRUNCATE on that table
remain forbidden, as do public-schema CREATE and migrations. Operator `verify`
and worker readiness enforce this read-only boundary. A schema probe using the
API/admin credential does not prove worker access. CI applies the actual grant
manifest in an isolated migrated database and connects with a real restricted
login, checks readiness, exercises denied writes/DDL, and reproduces the missing
SELECT regression. If an older manifest was already applied without this grant,
keep the worker stopped and use an explicitly approved, reviewed operator grant
correction followed by `verify`; do not relax the role or run a migration.

Every protected additive migration re-applies and verifies the reviewed direct
grant allowlist after the migration commits and before API recreation. This is
required because PostgreSQL gives `studio_worker` no implicit access to new
tables. If an older release committed a migration but the exact worker image is
unhealthy only because the new allowlist was not applied, keep the worker
gracefully drained and dispatch `Studio Platform CD` from exact `main` with
`component=migration` and `migration_target=worker_role`. The same disabled-by-
default release gate and `studio-production-migration` approval apply. This
recovery target performs only `configure_studio_worker_db_role.sh apply` plus
`verify` and a localhost API readiness check; it does not create a backup, run a
migration, rebuild/recreate API, start the worker, call a provider, or process a
job. The root-only apply keeps the password root-only but delegates the read-only
tracked-checkout inspection to the validated repository owner with optional index
locks disabled. It neither changes global Git trust nor makes the checkout
root-owned. Resume the unchanged exact worker image only after the recovery run
finishes successfully.

`STUDIO_ELEVENLABS_SCRIBE_V2_RATE_PER_HOUR_USD`, `STUDIO_ELEVENLABS_PRICING_EFFECTIVE_DATE` and `STUDIO_ELEVENLABS_PRICING_SOURCE=elevenlabs_public_api_pricing` form one complete snapshot. The operator verifies the value and effective date against the [official ElevenAPI pricing page](https://elevenlabs.io/pricing/api?price.section=speech_to_text) before changing it. Missing/partial/unsupported pricing blocks a provider call. A job keeps the first accepted snapshot across all parts, so changing environment pricing affects only jobs that have not started provider usage. Studio shows attributable confirmed usage cost, not an ElevenLabs invoice debit after free quota or subscription credits.

The same active BYOK key is read server-side for the official `GET /v1/user/subscription` and `POST /v1/workspace/analytics/query/usage-by-product-over-time` account views. It must have the provider read scopes for subscription and workspace analytics and satisfy any configured IP allowlist. No second Studio credential is required. The UI shows an actionable unavailable/stale state when either scope, allowlist, authentication, rate limit or provider availability blocks a read; never broaden or replace a provider key during deploy merely to make this panel green.

Account actuals are refreshed through a five-minute server snapshot and a visible manual refresh. They include provider tier/status, period characters, reset, usage-based billing entitlement/cap, current overage, invoice aggregates and workspace credits by product. They do not replace the immutable job tariff snapshot: ElevenLabs does not expose an official structured price-catalog endpoint, so do not scrape the pricing page or derive an hourly Scribe price from account credits. When public Scribe pricing changes, update the three non-secret tariff fields together in a reviewed deployment; already-started jobs retain their first accepted snapshot.

Provider invoice breakdown fields `subtotal_cents` and `tax_cents` may be omitted or null. Preserve this absence through storage/API/UI as null, never as zero; `amount_due_cents` remains required when an invoice exists. The exact integer `next_payment_attempt_unix=-1` means no scheduled payment and maps to a null payment date only; it is not accepted for quota reset timestamps. The [official InvoiceResponse schema](https://github.com/elevenlabs/elevenlabs-python/blob/a33cb6a262897dc7e453f32cd0770dc515b09634/src/elevenlabs/types/invoice_response.py) documents these cases. A malformed-response UI error alone does not prove which field failed: avoid raw response/credential logging and do not broaden key permissions or retry paid transcription to diagnose it.

Workspace credit normalization supports the documented `credits_used` column and the `total_usage` column confirmed by the owner's secret-free 2026-08-31 runtime diagnostic. `total_usage` requires the explicit `credits` unit; `total_minutes`, `total_cost`, `usage_count` and `total_charge_count` are not substitutes for credits or proof of per-job invoice attribution. Resolve columns by name, reject competing credit columns or malformed rows without partial totals, and retain the existing stale/unavailable behavior. The diagnostic established an HTTP 200 response with a different schema, not a permissions failure; do not broaden API-key scopes to fix this case. Regression fixtures reproduce only schema and use synthetic values.

### Initial worker deploy

A worker deploy is manual-only and must be run only when the worker is absent or already drained/stopped, the dedicated role verifies successfully, the runtime secret/pricing configuration is complete, and the production schema exactly matches the new worker image:

```bash
cd /opt/elevenlabs-studio
STUDIO_DEPLOY_DIR=/opt/elevenlabs-studio scripts/deploy_studio_platform_component.sh worker
```

The deploy script fast-forwards the trusted branch, exports the exact fetched commit and validated release version as component build arguments, preserves a previous stopped `exit_code=0` worker image as `elevenlabs-studio-worker:rollback-candidate` before building, builds only `studio-worker`, verifies PostgreSQL health without requiring Redis, compares current database revision with the new worker image Alembic head, tags the new worker image with the current commit, recreates only `studio-worker` with `--no-deps`, verifies the exact running image identity, waits for process-incarnation-aware Docker readiness, and only then prints `STUDIO_PLATFORM_WORKER_DEPLOY_OK`. API and worker use separate local image tags: `elevenlabs-studio-api:local` and `elevenlabs-studio-worker:local`. Worker operations must not retag or overwrite the API local image. It does not run migrations, recreate API/web/PostgreSQL/Redis, drain an active worker, run a canary, or perform automatic rollback.

### Worker drain and paused state

```bash
cd /opt/elevenlabs-studio
STUDIO_DEPLOY_DIR=/opt/elevenlabs-studio scripts/manage_studio_worker.sh drain
STUDIO_DEPLOY_DIR=/opt/elevenlabs-studio scripts/manage_studio_worker.sh pause
```

Drain sends only SIGTERM (`docker kill --signal SIGTERM`) and observes `docker wait` for the actual configured `STUDIO_WORKER_LEASE_TTL_SECONDS` plus a safety buffer. The observation timeout terminates only the waiting CLI, never the worker. If the container is still running, drain is incomplete and deploy remains blocked: let the active operation finish, then repeat status/drain verification; do not force-kill or replay providers. Active background cleanup/delivery also finishes before process exit. Compose `stop_grace_period: 86460s` covers the maximum supported lease TTL (`86400` seconds) plus a 60-second safety buffer as a fallback, but normal operator updates must still use explicit `status → drain → deploy`; the large Compose grace is not a replacement for operator drain. After SIGTERM, the worker stop flag prevents new claims; the current synchronous iteration and any stage-scoped heartbeat stop/join path finish or fail normally before exit. Heartbeat renewal sessions use transaction-local database timeouts and bounded stop joins; the heartbeat thread is daemon as a final process-exit safety net if a driver/network operation ignores the database timeout. `pause` is an idempotent safe-drain wrapper. Paused means stopped/drained container, never `docker pause`, `SIGSTOP`, or a frozen active process. A graceful drain prints `STUDIO_WORKER_DRAINED`; pause also prints `STUDIO_WORKER_PAUSED`. Repeated drain/pause is safe only when the worker is absent or the single existing container is already `exited` with `exit_code=0`.

If Docker forced-kills the worker, the process exits `143`, another non-zero exit occurs, the container is already stopped abnormally, or the container remains running/restarting, automation stops with a blocked reason and the operator must perform lease/output reconciliation review. Only exit code `0` is a graceful drain; `137` is forced kill, `143` is abnormal SIGTERM termination, and any other non-zero code is abnormal termination. Already stopped abnormal workers are not drained and are not paused; `pause` must not print `STUDIO_WORKER_PAUSED` after a failed drain. Do not automatically resume, redeploy, retry providers, clear leases, reset jobs, or delete/recreate Google documents.

### Worker resume

```bash
cd /opt/elevenlabs-studio
STUDIO_DEPLOY_DIR=/opt/elevenlabs-studio scripts/manage_studio_worker.sh resume
```

Resume only starts an existing single `exited` worker container with `exit_code=0` after checking schema compatibility for that exact stopped image ID. Before `docker start`, it reads the Alembic head from the stopped container image, reads the current production database revision non-interactively through the Compose/API operational boundary, requires exactly one revision on each side, and requires an exact match; schema mismatch prints `STUDIO_WORKER_RESUME_BLOCKED reason=schema_mismatch` and does not start the container. It then verifies the same image identity becomes healthy. It refuses absent, running/restarting, created, dead/unknown, `137`, `143`, or any other non-zero previous exit. It does not build, pull, fast-forward code, retag images, run migrations/downgrades, or recreate API/web/PostgreSQL/Redis. If the container is absent, use the official worker deploy path instead.

### Worker update sequence

Recommended operator sequence:

```text
status
→ drain
→ confirm stopped
→ apply/verify dedicated worker database role and runtime configuration
→ deploy worker manually
→ verify image/commit identity
→ verify `isolation_match=yes` and readiness as `studio_worker`
→ verify healthy
→ leave idle
→ operator separately decides whether to run controlled canary
```

Source merge does not deploy the worker. A successful worker deploy does not by itself prove production-live processing. The bounded `PWA-PROCESSING-ROLLOUT-01A` one-small-source canary is complete with exactly one persisted Google Docs output; broader selected-mode or workload claims still require separate operator evidence.

### Worker rollback

Rollback is an explicit worker-only operator action and requires the worker to be drained/stopped first:

```bash
cd /opt/elevenlabs-studio
STUDIO_DEPLOY_DIR=/opt/elevenlabs-studio scripts/manage_studio_worker.sh rollback
```

Rollback requires the current worker to be absent or `exited` with `exit_code=0`. It requires `elevenlabs-studio-worker:rollback-candidate`, verifies image identity, reads Alembic head directly from the rollback candidate image, compares it with the current database revision, and refuses schema mismatch before changing the worker local tag. It performs no downgrade, does not touch `elevenlabs-studio-api:local`, recreates only `studio-worker`, waits for health, verifies the running rollback image, and prints `STUDIO_WORKER_ROLLBACK_OK`. Automatic rollback is prohibited.

### Image/commit identity evidence

Safe evidence may include the intended repository commit SHA, the commit-specific worker tag `elevenlabs-studio-worker:<commit>`, whether that tag exists, the commit tag image ID, the running/stopped container image ID, explicit `identity_match=yes|no|unknown`, and rollback candidate presence. Do not print `.env`, secret-file contents, provider payloads, Google payloads, transcript bodies, document IDs, source names, or job/output records.

### Manual-only workflow dispatch

GitHub Actions supports manual `workflow_dispatch(component=worker)` using the
ordinary deploy SSH model and a materialized trusted deploy script. Push events
never auto-deploy the worker, including worker-only source changes. The separate
`workflow_dispatch(component=migration)` path uses the protected environment and
dedicated root forced-command identity described above; it is available for
first activation but is not blind retry authority. Neither path drains workers,
runs canaries, calls providers/Google, or performs automatic rollback.

## Output reconciliation operations boundary

`PWA-OUTPUT-RECONCILIATION-01` uses schema introduced by `0012_output_reconciliation_cases` and is part of the operator-evidenced production baseline migrated through `0015_user_source_retention`. The later catalog, maintenance OAuth, and progress migrations `0016_transcript_catalog_entries`, `0017_google_maintenance_oauth`, and `0018_job_part_progress` do not gate reconciliation behavior. Any future API/worker revision still requires schema compatibility and component identity checks; ordinary component CD must not run migrations.

When a job fails with `output_reconciliation_required`, the owner may use the Studio PWA action or API check endpoint to query Drive by the internal opaque appProperty token and the job output-folder snapshot. Operators must not ask users for raw Google document IDs, must not create duplicate Google Docs, must not delete possible duplicates, must not retry provider processing as reconciliation, and must not inspect transcript/document bodies as evidence. Zero matches remain unresolved for later explicit checks. Multiple matches are a conflict requiring manual investigation outside the automated path.

The bounded production canary produced one resolved reconciliation case and required no manual reconciliation mutation. That evidence proves the deployed read path for that case, not arbitrary uncertain-output recovery; an actual `output_reconciliation_required` case must still follow the fail-closed procedure above.


### Studio output reconciliation runtime guardrails

- Existing unresolved reconciliation cases are treated as permanent create blockers for the affected job-source relation; operators must not restart processing to create another Google Doc with the same appProperty token.
- A `prepared` case alone is internal evidence and should not be interpreted as owner reconciliation availability; pre-create persistence failure is a normal safe processing failure, not output uncertainty.
- Source retention cleanup does not block reconciliation because the recovery path uses durable case metadata and a verified Drive candidate rather than source bytes or object storage.
- Conflict is stable and fail-closed: repeated checks may report the conflict, but the system must not choose the first candidate, delete documents, or ask for a manual document ID.

### Explicit resolution of an uncertain provider outcome

An old terminal job with a provider request but no confirmed Google Docs output
remains visible after history cleanup. The owner must first run the ordinary
Drive reconciliation check. If it still cannot confirm an output, the PWA may
resolve the attention state only through the recent-authenticated, CSRF- and
same-origin-protected action: either link a later completed job for the same
project, ordered sources and exact media clip that has a persisted Google Docs
output, or explicitly acknowledge that no confirmed result exists and that the
provider may already have charged for the request. The API locks the job,
stores the resolution once, writes an audit record and then moves the old job
to history. Conflicting replays fail closed. This action never retries STT,
creates or deletes a Google document, removes the old attempt, or claims that
provider spend did not occur.

## Trusted browser for protected actions

The owner can opt in after successful password reauthentication and, when 2FA is enabled, a one-time code. `0038_trusted_devices` adds a hashed, owner-scoped, revocable 30-day capability; the browser holds only a `__Host-` HttpOnly/Secure/SameSite=Lax cookie. This capability may replace the 10-minute step-up for data, Google connection and provider-key actions while an authenticated session is valid. It never bypasses login, login TOTP, TOTP changes or session-management step-up. Password reset and TOTP changes revoke all trusted-browser records. The account security panel shows the current expiry and can revoke the current or every trusted browser; server authorization checks revocation and expiry on each protected action. A logout ends the session but does not silently revoke separately opted-in browser trust. Expired/revoked records are removed by bounded auth-state cleanup. Never log or expose the raw cookie in diagnostics.

The additive migration must pass the protected migration lane before the new API is served. During sequential web/API rollout, the new web form hides the opt-in until `/api/auth/security` advertises trusted-device fields, so it remains compatible with the old API. Verify repository/database direct-successor revision, protected snapshot and role checks before API deployment; inspect exact release records and public health after delivery.

## Source cleanup operations note

Repository Alembic history currently extends through additive `0038_trusted_devices`. The deployed production head must always be read from PostgreSQL and verified rather than inferred from repository source or live screenshots; until protected delivery proves otherwise, production remains at the separately recorded revision. The older source-cleanup and retention schema through `0015_user_source_retention` has separate production evidence. Source cleanup is durable PostgreSQL state on `sources`; the persisted/default `reference_class` plus exact `s3_bucket` and upload protocol/session select the only permitted storage boundary, and mismatch or incomplete isolation fails closed without fallback. The allowlisted per-user retention preference is durable PostgreSQL state on `users`. Cleanup is processed as bounded worker idle maintenance after normal job claim/orchestration finds no job. A cleanup claim becomes completed only after the multipart session (when applicable) and object are both confirmed absent; otherwise the exact persisted identity remains retryable. Safe diagnostics use normalized source deletion/retention/cleanup/reconciliation events and must not log object keys, buckets, filenames, Drive file IDs, presigned URLs, raw storage errors, or secrets. A browser preview is not deletion evidence; bulk removal must revalidate the opaque preview snapshot under locked source/job state, requires recent authentication plus explicit confirmation, skips blocked sources by reason, and never calls Google Drive deletion. The earlier authenticated smoke proved that source removal queued background cleanup, but it did not inspect the later physical R2 deletion outcome.


## Security boundaries after Security findings remediation

OAuth callback accepts only the active initiating Studio session stored in the
single-use OAuth state, including maintenance consent. Other browsers, logout,
revoked/expired sessions and disabled accounts fail before token exchange.
Enabling TOTP and rotating recovery codes revoke other owner sessions and browser
trust atomically; the current session remains available.

Auth uses both per-network and independent per-account throttles. Only the exact
configured direct peer may supply forwarding; the last observed XFF address is
used, so caller-prepended entries cannot select the throttle identity. Canonical
nginx overwrites XFF with its observed remote address. Do not guess a production
proxy IP or broaden trusted proxies. Ordinary component delivery does not replace
an installed host site: its body/forwarding settings must be verified separately.

API JSON is bounded before parsing (4 MiB, auth 16 KiB, including chunked input).
Media PUT goes directly to object storage and is unaffected; SigV4 signs exact
Content-Length for the file or part. Browsers set that header from the Blob body;
application code must not attempt to set a forbidden Content-Length header.
Completion still validates actual storage bytes. Local signing tests do not prove
external storage enforcement or browser/provider availability.

API container Uvicorn uses `uvicorn-log-config.json` to remove query parameters
from HTTP and WebSocket handshake logs. The existing protected edge lane applies
the same allowlisted security snippet, now requiring exactly `access_log off;`
in addition to the six security headers. Other logging destinations/directives
remain rejected; target, backup, rollback, nginx validation and reviewer gate do
not change. API path/status logs remain available without query credentials.
Historical access logs are outside this remediation; no purge is implied.

Yandex capabilities are consumed once with an atomic Redis SET NX/expiry before
WebSocket acceptance and provider connection. Redis failure/replay rejects the
handshake; reconnect obtains a fresh capability. No schema migration is required.

Live encrypted drafts have owner-wide count/byte budgets, serialized on the owner
row: `STUDIO_REALTIME_DRAFT_MAX_COUNT` (20) and
`STUDIO_REALTIME_DRAFT_MAX_STORAGE_BYTES` (32 MiB). Full storage does not remove
text; existing updates within the budget and explicit deletion remain available.
Existing retention requirements drift is tracked separately as F42.

Audio processing admits at most `STUDIO_AUDIO_PREPARATION_MAX_INPUT_BYTES`
(default 1 GiB) aggregate known bytes; unknown Drive sizes are bounded while
copying. `STUDIO_AUDIO_PREPARATION_MAX_SCRATCH_BYTES` defaults to 3 GiB and must
fit worker tmpfs. Both available disk and configured budget reserve 64 MiB;
FFmpeg gets a bounded output size before execution, and hitting that bound is a
failure rather than a successful truncated export. Increase budgets only together
with reviewed worker capacity. These operational ceilings are resource guards,
not commercial billing quotas.

Повторное скачивание готового аудио не использует S3 archive. API ставит задачу
отдельному worker, который собирает файл из доступных исходников и сохранённых
параметров. Общий `studio-audio-delivery` volume — volatile tmpfs2GiB,
uid/gid10001, mode0700, nosuid/nodev/noexec; он смонтирован в API и worker по
`STUDIO_AUDIO_DELIVERY_DIRECTORY=/run/studio-audio-delivery`. Это отдельный
лимит сверх worker scratch3GiB: перед rollout проверь доступный RAM/cgroup budget
обоих контейнеров и mount options, не увеличивай его автоматически. Один unique
DB slot ограничивает сервис одной задачей/готовым файлом. Work deadline3h,
ready/transfer deadline15min. API janitor каждые30s выбирает до10 истёкших rows
по индексу и очищает только UUID/marker-проверенные каталоги; disconnect и
завершение stream также освобождают slot. Нельзя очищать volume вслепую при
активной операции или заменять его persistent S3 хранения результата.

Preview sample также занимает этот slot: отдельный worker обрабатывает60s окно
возле первой обнаруженной паузы или начала записи и отдаёт не более30s WAV.
Sample сохраняет статус preview_ready, не публикует полный результат и не
запускает транскрибацию. Native playback поддерживает byte ranges, не продлевает
TTL; закрытие примера обязательно перед full start. Анализ хранит только bounded
waveform/silence metadata512 points/intervals; raw PCM и decoder output не
попадают в DB/logs. Integrity/visual analysis совмещены в один полный decode.

Migration0040 добавляет nullable result/download metadata и unique slot без
удаления historical output Sources. Она одновременно сохраняет Live/unfinished
provider text до явной retirement, добавляет source lifecycle поля и index.
Применять через protected backup/migration lane0039→0040 с approval точной
revision; затем подтвердить schema/API и поставить совместимый worker с тем же
transfer mount. Перед recreate обоих компонентов дождись drain/отсутствия
active work. Старые S3 outputs остаются на прежнем compatibility path, без
автоматического массового удаления. Rollout не повторяет пользовательские jobs
и не вызывает платный provider для smoke.

The audio-processing hotfix adds `0039_audio_diagnostics`, a direct additive
successor of `0038_trusted_devices`. Diagnostics retain the transcription-job
foreign key and gain a separate nullable audio-job foreign key, a mutually
exclusive job-reference constraint and an owner/audio/time index. The public
diagnostic `job_id` continues to identify the operation in either contour;
filters and exports preserve owner isolation. Apply through the protected
migration/backup lane before the new API/worker. Drain the old worker first,
then deploy its new image only after schema0039 and API health are confirmed.
Preserve old events; downgrade refuses to discard audio-event references.

FFmpeg progress flags are global and do not split option/value pairs, including
the output `-fs` budget. Stderr is drained with a bounded16KiB memory tail;
only an allowlisted failure category and bounded numeric exit code can reach
diagnostics. Raw stderr, private paths and source contents are neither stored
nor logged. Delivery does not retry failed user audio jobs automatically.

### Long-source confirmation

До STT worker проверяет duration всего исходника, включая запрос короткого clip. Для записи выше configured warning сохраняются измеренная whole/selected duration и nominal quote по immutable public tariff snapshot; неизвестный tariff обозначается unavailable. Retry подтверждает exact quote token, конкретный source и неизменённый clip. Повторное измерение другой duration отзывает consent до conversion/provider call; другой длинный source требует собственной оценки. Legacy warning без quote сначала повторяет проверку без long consent. Quote не invoice и не включает overlap/subscription/quota; остальные непромеренные sources не включаются в показанную сумму. Общее ограничение12h не обходится splitting. Отдельные provider limits остаются: current Yandex async adapter ограничен4h и не получает ElevenLabs tariff.

## Personal history and analytics retention

`STORAG-12/13`: historical job/output metadata and analytics inputs remain durable
PostgreSQL records without an automatic TTL. Owner actions reset the visible
history (`projects.history_reset_at`) or analytics interval
(`projects.analytics_reset_at`); they do not physically erase job/output evidence.
Active jobs and unresolved output outcomes remain visible after history reset.
This preserves retries, document-based duplicate protection and operational
integrity. No separate retained full transcript or finished audio is implied.
Source bytes and transient text follow their separate lifecycle rules above;
log/debug retention follows configured diagnostic limits. Any future physical
purge needs its own agreed requirements and reconciliation of those references.

## Explicit manifest snapshot export

In Transcriptions → Обслуживание → Расширенные действия, the owner can save the
manifest JSON to a selected Google Drive folder. This uses the primary
`drive.file` grant and the existing output-folder picker; separate maintenance
consent is not needed for this write. Folder identity, type, trash state and
write permission are rechecked server-side. The owner/reset cutoff applies to
accepted nonempty output records and imported catalog metadata. The snapshot
contains source/document identities and processing metadata; it never contains
transcript bodies, storage keys, credentials or OAuth tokens. It is metadata
export, not an automatic restore/import or a guarantee that every external
Google Doc still exists.

Requests require owner session/CSRF, no-store and a bounded selection: at most
5000 entries and8 MiB; exceeding either fails without a partial snapshot. The
owner row lock serializes export/clear; a dedicated snapshot hash property and
Drive readback before write make an unchanged export to the same folder reuse
its result. A changed snapshot or another folder gets a separate file, with no
overwrite of an existing owner file. Transient metadata bytes are deleted on
success/failure. The JSON file is an owner-selected external copy and remains
in Drive until the owner removes it; clearing Studio never deletes that copy.
Tests use synthetic records and a fake Drive transport, not a real account.


## CI gate для component и edge delivery

06Oct2026 F13/F63: automatic Studio Platform CD запускается после completed `CI` push main, не параллельно независимым push-trigger. `scripts/ci_validation.py deploy-gate` проверяет фиксированный repository, current main SHA, trusted same-repository push run и successful `ci-required`; failed/pending/fork/stale/unknown evidence блокирует jobs до deployment credentials. Проверка повторяется в каждом component job, в protected migration job после approval и в edge validation. Manual component/edge dispatch допустим только от exact current main с таким же successful push CI. Manual CI сам по себе не является release qualification.

Detection checkout и четыре component checkout привязаны к validated revision. Automatic selection сравнивает candidate с первым родителем: web — apps/studio; API — apps/studio-api; Alembic — только существующий защищённый migration lane; worker остаётся manual-only. Stateful concurrency без cancellation, текущие forced-command identities, backup/restore gates, schema/image compatibility, remote main freshness и health/readiness guards не изменяются. После merge с API dependencies worker сначала штатно drain, затем отдельный validated-main worker dispatch и identity/readiness/status checks. Миграция/edge требуют существующего `studio-production-migration` reviewer gate; code-review gate не добавляется.

CI reuse относится к проверенному исходному tree, не к production binary. Deployment по-прежнему строит exact-main bundle/image на VPS, сохраняет persistent state и подтверждает фактическую revision/image/schema/health. Branch feature/fix после merge не нужна поставке. Для trusted CI identity/selection/cost см. [validation](validation.md).
