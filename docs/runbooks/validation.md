# Validation runbook

Этот runbook — canonical команды, окружения, CI gates и доступные агенту проверки. Ad-hoc не требует отчётов пользователя. Проверки не доказывают работу production за пределами проверенных сценариев.

## Safe evidence rules

Do not record secrets, provider API keys, OAuth tokens, refresh tokens, document IDs/URLs, folder IDs, account data, source bytes, transcript bodies, document bodies, raw provider responses, raw Google responses, private paths, stack traces with sensitive values, or production credential values.

Результаты Evidence: PASS / PARTIAL / FAIL / PENDING / N/A с основанием; всегда указывай revision, environment, время и ограничения.

## Repository checks

Baseline repository and Studio CI must remain secretless. Используй synthetic configuration и test data. Credentialed integrations требуют отдельного согласованного scope. Production provider/Google mutations, cleanup и restore в CI fixtures не входят.

Рабочий каталог указан отдельно; команды установки выполняй в изолированном environment. Production config/data не использовать. При расхождении сверяй команды с фактическими workflow/package scripts, фиксируя drift.

CI process budget полной Python suite —300s с diagnostic SIGABRT и hard kill через10s; job ограничен15min. Budget не заменяет assertions или успех полного процесса; gates сохраняются. Root Linux CI требует FFmpeg/ffprobe через `STUDIO_REQUIRE_FFMPEG=true`: их отсутствие останавливает suite, а не разрешает green через SKIP. Исторические результаты с отсутствующим binary не подтверждают этот действующий gate. Локальный portable профиль допускает явный SKIP real-media tests, если binaries отсутствуют; такой результат не подтверждает обработку медиа.

| Назначение | Каталог и команда | Применимость / условия |
| --- | --- | --- |
| Install Python | Root: `python -m pip install -r requirements-dev.txt -c constraints-dev.txt` | Изолированный Python 3.11 для CI-equivalent; API-only install — как в `studio-ci.yml` |
| Install web | `apps/studio`: `npm ci` | Canonical npm lock; не менять lock ради локального окружения |
| Lightweight | Root: `python scripts/ci_checks.py` | Существующие notebook/guard checks; быстрый repository gate |
| Format / docs | Root: `git diff --check`; проверить содержимое, links и routing | Отдельного formatter script нет; это не замена configured lint |
| Lint | `apps/studio`: `npm run lint` | ESLint |
| Typecheck | `apps/studio`: `node node_modules/typescript/bin/tsc -b` | Также входит в build |
| Focused tests | Root: `pytest -q <test-path>`; web: `node node_modules/vitest/vitest.mjs run <test-path>` | Выбрать существующие tests затронутого поведения; Python service fixtures требуют соответствующего environment |
| Frontend suite | `apps/studio`: `npm run test -- --run` | Vitest; если local npm wrapper не передаёт `--run`, эквивалент — `node node_modules/vitest/vitest.mjs run`, различие записать |
| Full Python / DB | Root: `alembic -c apps/studio-api/alembic.ini upgrade head`, затем `pytest -q` | Только isolated PostgreSQL 17/Redis 7 + synthetic config по `ci.yml`; Linux/bash, тестовый DB owner/runtime setup из workflow |
| Isolated restore | Root: `python scripts/rehearse_studio_restore.py`; regression: `pytest -q tests/test_studio_restore_rehearsal.py tests/test_studio_recovery_quarantine.py` | Docker с cached `postgres:17`; реальный dump/restore synthetic encrypted data в двух owned tmpfs targets. Required Linux CI; local absence — SKIP с ограничением. Production restore не запускается; измерение до quarantine не доказывает full RTO |
| Compatible release rollback | Root: `python scripts/rehearse_studio_release.py --baseline <40-char-base-SHA> --candidate <40-char-test-merge-SHA>` | Owned tmpfs PostgreSQL/Redis, internal network и exact API/web/worker images; upgrade, drain, schema/credential rollback и readback. REQUIRED affected Linux CI при migrations/runtime-role manifest/drill changes; локально без Docker PENDING. Builds require network; runtime не вызывает providers и не использует production secrets/data. Schema downgrade только synthetic; production recovery определяется operations |
| Browser layout regression | `apps/studio`: `STUDIO_BROWSER_LAYOUT_ONLY=1 npm run test:e2e` (PowerShell: `$env:STUDIO_BROWSER_LAYOUT_ONLY='1'`) | Только frontend, synthetic API/Google responses, desktop1280×720/mobile390×844, history/CTA/picker/menu/focus/overflow/reset. При занятом порте можно указать STUDIO_BROWSER_PORT (1024..65535); существующий сервер не переиспользуется. Обычный CI E2E включает эти сценарии вместе с API suite; отдельный дублирующий workflow не нужен |
| Portable Python | Root: synthetic setup ниже, затем `python -m pytest -q --portable <test-path>` либо без `<test-path>` для всего portable профиля | Ограниченная диагностика; исключает 9 modules по `conftest.py`, оставляет часть shell tests, не гарантирует Windows compatibility |
| Browser E2E | `apps/studio`: `npm run test:e2e`; inventory — `npm run test:e2e:list` | Playwright Chromium, isolated DB `studio_browser_e2e`, Redis, migrations, seed и fake external services по `studio-ci.yml` |
| Build | `apps/studio`: `npm run build` | TypeScript + Vite/PWA + `scripts/write-build-meta.mjs`; отдельный Vite run не равен всей команде |
| Containers / Compose | Команды build и synthetic Compose checks из `.github/workflows/studio-ci.yml` | Docker/Linux; repository build contexts и env из workflow, без production secrets |
| Advisory audit | `apps/studio`: `npm audit --audit-level=high`; Python — isolated constrained `pip-audit` по `dependency-audit.yml` | Scheduled/manual supply-chain check; фиксировать дату, lock/revision и advisories |
| Local web / API | `apps/studio`: `npm run dev`; root: `uvicorn studio_api.main:app` | API требует `PYTHONPATH=apps/studio-api`, isolated DB/Redis/config и synthetic secrets; production `.env` не копировать |

Обязательный итоговый check — `ci-required` workflow `CI`, источник GitHub Actions. Он всегда запускается и требует PASS всех применимых jobs: `checks`, а для Studio scope — reusable `studio-validation / studio` и `studio-validation / browser-e2e`; affected migrations/runtime-role/drill changes дополнительно требуют `release-rehearsal`. Selection failure, неизвестная комбинация outputs, failed/cancelled applicable job не становятся green aggregate. Required protection на main включает PR, strict up-to-date checks, admin enforcement, запрет force/delete; обязательное человеческое review не добавляется. Фактическое применение settings и readback — primary records текущей Goal, до них enforcement остаётся PENDING.

`CI` запускается на любом PR, push main и вручную. `Studio PWA CI` вызывается из него как reusable workflow либо вручную, не дублирует PR/main trigger. `scripts/ci_validation.py select` освобождает от executable suites только известные Markdown-only изменения docs/README/AGENTS; lightweight `scripts/ci_checks.py` остаётся обязательным. Workflows, scripts, deploy, apps, tests и dependency inputs выбирают полный root плюс Studio. Root-only executable changes проверяются root suite. При unknown base/manual CI выполняются обе suite. Services, assertions, isolated PG migration/restore и browser checks сохранены.

На PR default checkout проверяет текущий `refs/pull/<PR>/merge`. Successful aggregate сохраняет только bounded `identity.json` на7дней: checkout/tree/head/base/run/context identity, без executable artifacts, пользовательских данных и secrets. На push main secretless selection может переиспользовать полный successful same-repository PR run только для эквивалентного squash/rebase tree: merged PR связан с target SHA, base равна родителю target, server-side checkout commit имеет проверенные base/head parents и tree; совпадают workflow/script context, RUNNER_OS/ARCH и ImageOS/ImageVersion всех применимых suite hosts (не только aggregate runner) и source-bound aggregate. Forks, merge commits, docs-only proof, direct push, changed tree/base/context/runner image, неизвестная runner identity, expired/missing/ambiguous proof или недоступность API означают полный безопасный прогон. Ни cache hit, ни arbitrary PR artifact не разрешают deployment; после merge production image пересобирается из exact main и проверяется отдельно.

CI concurrency отменяет только superseded PR runs. `cost-report` сохраняет elapsed до последнего завершённого job и sum completed runner seconds (включая retries; сам ещё работающий report job явно исключён). Окончательные значения считаются по всем job timestamps первичного run record. Исходный main1937658: root37430070244 —231runner seconds; Studio37430070238 —263+129=392; combined623runner seconds и263s elapsed, без очереди. До/после сравниваются фактические records, не обещанный budget. Included minutes UNSET; speculative reruns/длительное наблюдение не входят в обычный flow.

Critical scenarios: owner/CSRF/session/TOTP isolation; source multipart reconciliation и storage classes; batch queue/retry/idempotency; Yandex REST timestamp types и realtime final ordering; Google output metadata; unfinished transcript recovery/re-export without STT and owner-cleared Live text; cleanup/backup/recovery; schema compatibility; PWA capture/permissions, 390px viewport и accessibility. AC/риски и нужные проверки выбирай в Validation Plan конкретной Goal. Реальные STT, Google mutation, Telegram notifications и destructive cleanup/restore не входят в обычную suite; live canary требует согласованного scope, тестовых данных и ограниченного побочного эффекта.

Известные gaps: Windows `--portable` всё ещё зависит от bash для части tests; 9 excluded modules; затронутые worker/shell fixtures используют проверенный абсолютный Git Bash executable; POSIX права и symlinks остаются Linux-only. Existing local dependencies не являются clean-install Evidence. Windows Python graph можно проверить изолированным pinned pip-audit; этот результат не покрывает Linux-specific dependencies. Полноценная local Docker/DB/browser suite в последнем аудите не запускалась. Npm advisory findings и результаты отдельных checks — в delivery-plan; запись команд не превращает их в PASS. Универсальный duration/coverage/budget target владельцем не задан; действуют timeout guards конкретных jobs. Ответственность агента за проверки, их ограничения и обратная связь из эксплуатации — по AGENTS.md/плану.

### Portable local Python profile

Root Linux CI задаёт `STUDIO_REQUIRE_FFMPEG=true`: существующий root job обеспечивает FFmpeg/ffprobe, а pytest preflight завершает suite ошибкой при отсутствии инструментов. Synthetic real-decoder/processing cases выполняются в том же прогоне, без дополнительного workflow или повторного полного CI. Локальный portable профиль допускает отсутствие binaries с явным SKIP; это не подтверждает real-media поведение.

Для ограниченной локальной диагностики сначала установите зависимости командой **Install Python** выше в изолированный Python environment. Рабочий каталог — root без production `.env`; production secret files не подключаются. `STUDIO_DATABASE_URL` нужен **до collection**, поскольку импорт API создаёт SQLAlchemy engine. SQLite здесь отключает обращение к deployment password file и служит synthetic import/fixture boundary; он не заменяет PostgreSQL tests.

PowerShell, тот же изолированный Python и root:

```powershell
$env:STUDIO_ENVIRONMENT = 'test'
$env:STUDIO_DATABASE_URL = 'sqlite+pysqlite:///:memory:'
$portableTemp = Join-Path (Get-Location).Path '.tmp/portable-tests'
New-Item -ItemType Directory -Force -Path $portableTemp | Out-Null
$env:TEMP = $portableTemp
$env:TMP = $portableTemp
$env:PYTHONIOENCODING = 'utf-8'
python -m pytest -q --portable tests/test_studio_retention_admission.py
```

Для affected tests замените последний path нужным списком. Не передавайте `PYTHONPATH` от чужого проекта или старого dependency graph; discovery задаётся `pytest.ini`, а service tests подключают свой `apps/studio-api` import path. Для полного portable прогона опустите paths, сохранив тот же synthetic setup. Команда меняет environment только текущего terminal/process и использует project-owned временный каталог.

Bash, root и isolated Python:

```bash
STUDIO_ENVIRONMENT=test STUDIO_DATABASE_URL='sqlite+pysqlite:///:memory:' python -m pytest -q --portable tests/test_studio_retention_admission.py
```

Discovery ограничен `tests/`. `--portable` исключает 9 service/shell modules, перечисленных в `conftest.py`, до их импорта. На Windows `conftest.py` выбирает проверенную установку Git Bash и MSYS utilities перед system bash/WSL только для процесса pytest; затронутые shell fixtures передают абсолютный путь executable, поскольку Windows CreateProcess может иначе разрешать bare name. Пользовательский PATH не изменяется. POSIX права/симлинки и PostgreSQL/Redis остаются Linux CI boundary: это ограниченный диагностический профиль, а не обещание full cross-platform suite. Plain `pytest` с PostgreSQL/Redis/bash остаётся полным CI-профилем. Точные команды, environment и применимость — в [команды и условия](#repository-checks); результаты — в [delivery dashboard](../delivery-plan.md).

For Studio frontend changes, inspect `apps/studio/package.json` and run the relevant existing npm scripts from `apps/studio/` when dependencies are available.

### Studio processing E2E

The deterministic source-level processing scenario is:

```bash
pytest -q tests/test_studio_processing_e2e.py
```

It requires the same PostgreSQL database, current Alembic head, and Redis service used by repository CI. A developer run without those services is reported as skipped; `CI=true` makes either missing service a failure. The test creates the project, credential, source, output destination, and job through the authenticated API, runs the real claim/orchestration/persistence path, replaces only storage, ElevenLabs, and Google network boundaries with controlled fakes, then verifies the completed job and explicit browser-safe output DTO. It is not a real-browser test and does not replace the controlled production canary.

### Studio authenticated browser E2E

From `apps/studio/`, Playwright discovery can be checked without starting a browser:

```bash
npm run test:e2e:list
```

The full scenario is run by the `browser-e2e` job in `.github/workflows/studio-ci.yml`. That job creates an isolated PostgreSQL database named `studio_browser_e2e`, starts Redis, applies the current migrations, seeds synthetic owner-scoped state, starts the real FastAPI and Vite servers, and runs:

```bash
npm run test:e2e
```

The scenario uses headless Chromium through the same-origin Vite proxy. It verifies real login/session/CSRF behavior, authenticated project creation, safe completed-result rendering, and logout. It does not call ElevenLabs, Google, S3/R2, production infrastructure, or the deployed public host, and it does not replace the controlled production canary. On failure, the GitHub job uploads the Playwright trace and screenshot directory as a short-lived artifact.

A full local run requires the same isolated database name, test-only environment, migrations, seed, Redis service, and Playwright Chromium installation as the GitHub job. Do not point the seed at a shared, development, staging, or production database; the seed fails closed unless the exact isolated localhost test boundary is present and the user table is empty.

## Reproducible Python dependencies

Studio npm security overrides включают локальный проверяемый fork `deepmerge` в `apps/studio/vendor/deepmerge`; upstream provenance, узкая security delta и лицензия находятся рядом с исходником. Root direct file dependency и `$deepmerge` override дают один и тот же код для npm10/Node22 и `npm ci --ignore-scripts`, без postinstall mutation. Docker build копирует vendor до dependency install. При обновлении upstream сохраняйте behavior regressions `src/deepmergeBoundary.test.ts`, PWA generateSW и full lint/build; vendor не исключён из lint. Все остальные app imports и gates сохраняются. Доступность advisory endpoint и установленный graph проверяются отдельно; отсутствие findings не заменяет behavioral checks и Linux CI.

Repository/CI development installs use the input requirements together with the committed transitive constraints:

```bash
python -m pip install -r requirements-dev.txt -c constraints-dev.txt
```

The Studio API container applies `apps/studio-api/constraints.txt` to `apps/studio-api/requirements.txt`. These constraints do not replace `requirements-colab.txt` when installing the stable Colab runtime.

To qualify the candidate Batch Colab dependency lock, run the following from the repository root in a disposable Linux x86_64 runtime. Run it once with CPython 3.12 and once with CPython 3.13.

```bash
python scripts/check_colab_dependency_install.py
```

The check selects the matching `requirements-colab-linux-x64-py*.lock`, installs wheel packages by SHA-256 into a disposable venv and verifies its dependency graph. It constructs synthetic Drive, Docs and STT requests without authenticating or sending them. The Batch launcher uses the same installer for its isolated STT subprocess. Google SDK calls, Colab authentication, IPython and widgets use the packages provided by the notebook's kernel. Qualify those flows in a clean hosted Colab session separately. The legacy direct `elevenlabs_api.py` entry point keeps its existing setup.

After an intentional Python dependency change, regenerate both constraints with the pinned generator and review the complete diff before testing:

```bash
python -m pip install pip-tools==7.6.0
python -m piptools compile --resolver=backtracking --strip-extras --newline=LF --output-file=apps/studio-api/constraints.txt apps/studio-api/requirements.txt
python -m piptools compile --resolver=backtracking --strip-extras --newline=LF --output-file=constraints-dev.txt requirements-dev.txt
```

Constraints are installed with `-c`; they are not standalone cross-platform requirements files. This preserves platform-specific dependencies selected by extras while constraining the shared resolution.

### Dependency audit handoff

The `Dependency audit` GitHub Actions workflow runs weekly and via `workflow_dispatch`. It audits the exact npm lock and an installed Linux/Python 3.11 graph. Findings fail only that reporting workflow; ordinary PR/push CI does not call advisory services.

Reproduce the Node graph locally from `apps/studio/` without lifecycle scripts:

```bash
npm ci --ignore-scripts --no-audit
npm audit --audit-level=low
```

Reproduce the constrained Python graph from the repository root in an isolated temporary target:

```bash
audit_graph="$(mktemp -d)"
trap 'rm -rf "$audit_graph"' EXIT
python -m pip install pip-audit==2.10.1
python -m pip install --target "$audit_graph" -r requirements-dev.txt -c constraints-dev.txt
python -m pip_audit --strict --path "$audit_graph"
```

Local success is preparation evidence; the required remote CI check is recorded separately. After the intended branch is clean and published, dispatch the unchanged workflow against that branch and record the expected revision before selecting the run:

```bash
branch="$(git branch --show-current)"
expected_sha="$(git rev-parse HEAD)"
git push -u origin "$branch"
gh workflow run dependency-audit.yml --ref "$branch"
gh run list --workflow dependency-audit.yml --branch "$branch" --event workflow_dispatch --limit 5 --json databaseId,headSha,status,conclusion,url
gh run watch <run-id> --exit-status
gh run view <run-id> --json headSha,conclusion,jobs,url
```

Accept the result only when the selected run's `headSha` equals `expected_sha` and both `node` and `python` jobs conclude `success`. Record only the revision, run URL, job conclusions, and safe aggregate status. Do not publish advisory details, dependency paths, private environment values, or raw audit responses.

An advisory result is `fail`, not an outage and not a reason to rerun. A registry/advisory-service/network outage is `blocked` and may be rerun later. Never use `npm audit fix`, `--force`, advisory ignores, failure masking, or a reduced dependency graph to turn either outcome into a pass.

For docs-only changes, run `git diff --check`, available markdown/link checks, targeted `rg` searches for stale links/conflicting claims, and a docs-only changed-file review. Runtime integration tests are not required unless the task explicitly asks for them.

## Markdown link check pattern

When no dedicated markdown link checker exists, a repository-local script may parse markdown links and verify relative targets. It should ignore external URLs, anchors, mailto links, and intentionally absent generated artifacts only if the task documents that limitation.

## Authority-reset searches

Useful checks for documentation authority work:

```bash
rg -n "record-only|record only" README.md AGENTS.md docs
rg -n "studio-processing-contract.md" README.md AGENTS.md docs
rg -n "production-live|production ready|production-ready" README.md AGENTS.md docs
rg -n "active item|Active item|ACTIVE" docs/delivery-plan.md
```

Migration references should match the factual repository head under `apps/studio-api/alembic/versions/`.

## Studio controlled canary checklist

Use this only with the Studio operations runbook. A successful canary requires all of the following without unsafe evidence:

- [ ] Intended commit/source state identified.
- [ ] Database revision equals repository Alembic head where required.
- [ ] Web/API health and deployment identity verified.
- [ ] Exactly one intended worker instance is running from the intended image.
- [ ] One test account/project/source/credential/Google connection/output folder is approved.
- [ ] One queued job is created; no duplicate job and no automatic retry.
- [ ] Worker claims the job and reaches a terminal normalized state.
- [ ] On success, exactly one persisted output row exists.
- [ ] On success, the operator confirms the expected Google document opens in the selected folder without recording its ID/URL/content.
- [ ] No secrets, transcript bodies, raw external payloads, source bytes, or private account data are recorded.

Failure, uncertainty, duplicate output, wrong folder, missing persisted output after possible document creation, or lease ambiguity blocks a production-live claim and requires follow-up reconciliation/recovery work.

## Colab batch validation checklist

- [ ] Launch `notebooks/elevenlabs_api_colab.ipynb` in Google Colab from the intended revision.
- [ ] Confirm required secrets are available without printing values.
- [ ] Run only approved safe sources.
- [ ] Confirm provider transcription, Google Docs delivery, manifest update/skip behavior, and analytics hygiene.
- [ ] Record only safe pass/fail metadata, not transcript content or raw provider/Google responses.

### Source-mode smoke

Validate each supported source contour when safe fixtures are available:

- [ ] computer single file;
- [ ] computer multiple files;
- [ ] computer folder, including a nested supported file and an ignored unsupported file;
- [ ] Google Drive single file;
- [ ] Google Drive folder.
- [ ] Explicit English mode sends `en`; auto-detection still omits an explicit language code.
- [ ] A source with embedded `creation_time` writes that timezone-aware value as ISO 8601 metadata.
- [ ] A Drive source without embedded creation metadata uses Drive `createdTime`, never `modifiedTime`.
- [ ] A source without authoritative creation metadata writes explicit `unknown`, never job/document/transcription time.

### Manifest and Drive workspace

- [ ] `VoiceOps Workspace/` exists.
- [ ] `VoiceOps Workspace/manifest/elevenlabs_transcription_manifest.json` exists.
- [ ] Legacy `_transcription_state` migration preserves existing history when legacy state is present.
- [ ] A repeated controlled run confirms manifest skip behavior and does not repeat paid transcription without a valid reason.
- [ ] A forced provider or Google Docs failure creates no new source entry in manifest.
- [ ] Manifest source appears only after the created/updated Google Doc ID is confirmed.
- [ ] Safe clear dry-run reports counts without writes.
- [ ] Safe clear apply rejects missing/wrong confirmation, creates a backup first, then leaves an empty v2 catalog without deleting media files or Google Docs.
- [ ] Old state files are not manually deleted before reconciliation when legacy/current manifest conflict is observed.

### Analytics JSONL

Check `VoiceOps Workspace/analytics/elevenlabs_transcription_runs.jsonl`:

- [ ] file exists after a successful or best-effort analytics run;
- [ ] latest line is valid JSON;
- [ ] expected aggregate fields are present;
- [ ] no secrets or API keys;
- [ ] no transcript text;
- [ ] no Google Docs body;
- [ ] no raw provider payload;
- [ ] no raw Drive URLs;
- [ ] no full local paths.

### Provider matrix

Use non-sensitive fixtures only:

- [ ] ElevenLabs short file;
- [ ] OpenAI short file;
- [ ] OpenAI long-but-small file over the safe duration target of 1320 seconds;
- [ ] OpenAI oversized file exercising the 25 MB hard upload limit / 20 MB safe target split behavior;
- [ ] OpenAI diarization with a copied non-sensitive fixture.

### Manual segmentation

- [ ] segmentation is available only in one-source modes;
- [ ] segment order is deterministic;
- [ ] labels/titles are unique according to the UI rules;
- [ ] one output is created or skipped for each intended segment;
- [ ] provider settings remain unchanged per segment;
- [ ] OpenAI technical split can still run inside a segment when required.

### Colab stop conditions

Stop validation and investigate before repeating paid work on:

- manifest history missing after migration;
- unexpected paid retranscription on a repeated controlled run;
- duplicate or missing Google Docs output;
- unsafe analytics content;
- provider success without Google Docs and manifest success;
- unresolved legacy/current manifest conflict.

## Realtime Colab validation

Realtime Colab validation is experimental and lives in `docs/runbooks/realtime-colab.md`.


## CI inventory и восстановление результата

Snapshot: workflows на origin/main `3e65322e12ba3d1ac2bc9f3ec7ecc412a6e3090b`, 2026-09-07; settings snapshot 2026-09-06, branch/rulesets повторно 2026-09-07. Набор workflow не означает authorization на dispatch.

| Workflow | Trigger / назначение | Production capability |
| --- | --- | --- |
| `.github/workflows/ci.yml` — CI | PR/main/manual; PostgreSQL/Redis, Alembic, lightweight, full pytest | Нет |
| `.github/workflows/studio-ci.yml` — Studio PWA CI | Reusable call из CI/manual; studio и authenticated browser-e2e | Нет |
| `.github/workflows/dependency-audit.yml` — Dependency audit | Weekly/manual npm/Python advisory audit | Нет; не regular PR gate |
| `.github/workflows/studio-platform-cd.yml` — Studio Platform CD | Path-filtered main/manual; web/API, gated migration, manual worker | Да |
| `.github/workflows/studio-migration-environment-probe.yml` | Manual main; no-op Environment reviewer probe | Только Environment gate; без checkout/secrets/SSH |
| `.github/workflows/studio-edge-cd.yml` — Studio Edge CD | Manual exact main SHA; security-header release | Да, gated |
| `.github/workflows/studio-processing-preflight.yml` | Manual expected SHA; processing readiness | Read-only SSH |
| `.github/workflows/studio-worker-status.yml` | Manual expected SHA; worker identity/health | Read-only SSH |
| `.github/workflows/studio-worker-drain.yml` | Manual expected SHA; graceful stop | Да, меняет worker process state |

GitHub-hosted Ubuntu runners; token read-only, Actions не могут approve PR reviews. Baseline CI и Studio E2E используют synthetic data/fake integrations, не получают production secrets и не вызывают реальные ElevenLabs/Yandex/Google/R2/production. Credentialed integration flow требует собственного scope/trust boundary. Внешние Actions pinned full SHA по YAML и regression guard; repository settings пока разрешают `allowed_actions: all`, `sha_pinning_required: false`. Это gap platform enforcement, не разрешение mutable refs. Cache keys/install inputs проверяй по lock/OS/runtime и trust context; cache не переносит secrets и не является release artifact.

Для routine delivery используй [Studio operations](studio-platform-ops.md#delivery-targets-и-процедуры). Настройка/ремонт pipeline — [CI/CD rules](../ci-cd-rules.md); обычный Git/Goal flow — [AGENTS](../../AGENTS.md). Для восстановления используй repository ID, PR number, run/job ID и exact SHA; подробные logs остаются в первичных records.

## Configuration для изолированных проверок

`Settings` использует `STUDIO_` prefix и `.env` относительно process cwd. Приоритет: constructor values → environment → dotenv → secret source/defaults; прикладные secret-file methods читают только выбранный файл. `database_url` имеет приоритет перед составным DB URL. Cached settings требуют restart/explicit cache invalidation после изменения config. Synthetic проверки задают `_env_file=None` и SQLite/изолированные PostgreSQL credentials, не используют host production `.env`.

Представительный local audit: `python scripts/ci_checks.py`; frontend `node node_modules/vitest/vitest.mjs run`; portable Python с уникальным basetemp; `npm.cmd audit --package-lock-only --json`. Наличие lock проверяет выбор versions, не фактическое соответствие существующего node_modules. Fresh Python advisory audit требует установленного pinned `pip-audit` и isolated constrained graph из workflow; global pip check unrelated environment его не заменяет. CI job-level records проверяются на exact revision; внешние side effects не запускаются для обычной диагностики.
