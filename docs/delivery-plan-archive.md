# Delivery plan archive

This document is historical. Codex and other coding agents must not read it during ordinary focused tasks. It does not define current scope, current product requirements, active delivery state, or production readiness. Current delivery status is in `docs/delivery-plan.md`; the current product contract is in `docs/project-spec.md`.

The archive preserves traceability from documents consolidated during `DOCS-AUTHORITY-RESET-01`. It intentionally avoids secrets, production credentials, private account data, transcript bodies, document IDs/URLs, raw provider responses, and raw Google responses.

## Archived `STT-MULTIPROVIDER-CONTINUITY-01` delivery — PRs #295–#296

- Final baseline: `main@b9e83131120ef075ea6bcbf6fd64e3d6e594b966`; functional merge `436efcc9997f724ba3ec9107122ef3ed12d50525`, migration-owner recovery merge `b9e83131120ef075ea6bcbf6fd64e3d6e594b966`.
- Outcome: provider-neutral batch/realtime contracts, capability modes, independent BYOK/health boundaries, Yandex v3 batch/deferred/realtime, owner dictionaries, separate capture/STT errors, OBS overlay and explicit YouTube/allowlisted HTTPS consumers; legacy enum ownership recovery preserved least privilege.
- CI: PR #296 exact-head checks passed; exact-main repository run `33817904621` and Studio/browser run `33817904611` succeeded.
- Delivery: web from PR #295 merge; protected migration/API run `33818588686` advanced schema `0035_job_notifications -> 0036_stt_multiprovider` from verified snapshot and deployed API; worker run `33819107379` deployed exact `b9e8313`, final status `33819343560` reported healthy matching image identity.
- LIVE boundary: production Yandex/provider calls and external caption sends were not performed; unavailable/unconfigured states are intentional and no-spend LIVE is sufficient for the approved Goal.
- Cleanup: merged remote working branches were pruned; local `main` and `origin/main` were exact before the next Goal branch was created. Unrelated untracked pnpm files and inaccessible test temp directories remained untouched.

## Archived `PWA-REALTIME-STABILITY-READINESS-01` delivery — PRs #228–#230

- Final baseline: `main@ebbba50a938feb2d06b2ec59e828834ff204988d`.
- Outcome: hardened repeated start/stop and stale async cleanup, added static voice-priority mix, then separate browser-only display/microphone source meters and microphone-triggered display ducking without persisting audio or transcript content.
- Final exact-main CI: repository run `32706218832` ✅; Studio PWA run `32706218892`, jobs `studio` and `browser-e2e` ✅.
- Deployment: Studio Platform CD run `32706218830` ✅ deployed `studio-web`; API, worker and migration correctly skipped as unaffected.
- LIVE: owner-controlled ordinary Chrome canary on laptop speakers confirmed both source signals during mixed capture and microphone speech reaching transcription while display playback continued. Partial acoustic/provider masking of simultaneous speech was explicitly accepted as non-critical; no new capture reset was reported.
- Readiness at closure: `PWA-REALTIME-01 [историческая оценка удалена], Studio PWA [историческая оценка удалена], project [историческая оценка удалена]; denominator remained `120`.
- Cleanup: all three merged Goal branches were ancestor-verified and removed locally/remotely; local `main` fast-forwarded to exact `origin/main`.
- Metadata limitation: approved post-deploy writer remains absent, so final Evidence was recorded in PR #230 and reconciled by the next authorized Goal instead of a docs-only follow-up PR.

## Archived `PWA-TRANSCRIPTIONS-UX-AND-LIVE-RECOVERY-01` delivery — PR #222

- Base: `main@dd194c929d957e822ff618df294dc54e72d5971e`.
- PR: #222, merged as `main@ccb067d05d5225a3178b21cd239bd65c0764f1fb`.
- Outcome: primary UX переведён с ручного Projects lifecycle на `Транскрибации` с ordinary/Live tabs; batch отображается одной multi-transcription; добавлены local IndexedDB и encrypted owner-scoped server Live drafts с 72-hour TTL, recovery/download/delete UX и bounded accessibility/diagnostics remediation.
- Exact-main CI: run `32588711409` ✅; Studio PWA CI run `32588711419`, jobs `studio` и `browser-e2e` ✅.
- Deployment: web run `32588711397` ✅; protected migration `0023_realtime_drafts` run `32589660127` ✅; API run `32589888861` ✅; worker runs `32589929940` и rollback-corrected `32590256878` ✅.
- LIVE/operations: bounded preflight `32590047900` ✅ и worker status `32590305806` ✅; Goal Evidence `SPEC/CODE/TEST/CI/DEPLOY/LIVE ✅`.
- Cleanup: local/remote merged branch удалена после ancestry check; local `main` fast-forward синхронизирован. Post-deploy operational diff перенесён в следующую authorized Goal из именованного stash, поскольку approved metadata writer отсутствует.

## Archived `PWA-REALTIME-CAPTURE-01` delivery — PR #212

- Base: `main@f90e0d7b3b10d345a9ea6ff34f5b8c3025d818d7`.
- Implementation commits: `907ba24d5e0a058bbacf04f28dc98f6d2fac8676`, `25fa508212ec65f1da887b9b0ad01e0fd0b1db5d`, `8d6b061f1cbf9a2967c9860a398916c6f2f9af3f`.
- PR: #212, merged 2026-08-15 as `main@f3a3f33fb0ce019c1916d95f754ed72d1d56ee01`.
- PR-head checks: CI run `31872035202` `checks` ✅; Studio run `31872035197` `studio` ✅ и `browser-e2e` ✅.
- Exact-main checks: CI run `31872181449` ✅; Studio run `31872181421` ✅.
- Deployment: Studio Platform CD run `31872181463` ✅ доставил `studio-web`; API/worker/migration были intentionally skipped. VPS checkout и running image identity соответствовали merge revision, `/healthz` прошёл.
- LIVE: bounded in-app canary прошёл; owner отдельно подтвердил, что Chrome tab capture больше не сбрасывается. Full microphone/display/mixed matrix не выполнялась, поэтому product `PR-06` остался `5/6` и `LIVE ◐`.
- Delivery state: `LIVE_VERIFIED`; metadata synchronization не выполнена, потому что approved writer отсутствует (`metadata_sync.enabled=false`).
- Cleanup: local/remote working branch удалена после merge ancestry check; local `main` fast-forward синхронизирован.

## Archived `DOCS-AGENT-DELIVERY-V2` closure — PR #209

- Base: `main@830bd00754567dfa6809e1e36bb7fcbaa145b824`.
- PR: #209, merged 2026-08-14 as `main@a252a1efa54ba952ec4eb04405fae5722f15d7b5`.
- Outcome: принят `direct-agent-v1`, agent lifecycle был вынесен в отдельный canonical workflow, CI/CD contract получил verified project profile, README navigation обновлена. Эта схема позднее superseded contract `goal-driven-v1`; отдельный workflow больше не является repository document.
- Exact-main CI: run `31823766931`, success.
- Deployment: N/A для docs-only diff; GitHub Deployments API вернул пустой список.
- Metadata sync: автоматический post-deploy writer отсутствует (`metadata_sync.enabled=false`); прямой push для отдельного status commit не выполнялся.
- Branch cleanup: merged working branch удалена локально и в origin после fast-forward local main.

Предыдущий active dashboard с project readiness `N/A`, Colab `[историческая оценка удалена]` и отдельным Studio Live denominator был superseded новой explicit owner baseline от 2026-08-14. Эти проценты не сопоставимы с новым полным product denominator и не являются текущей readiness.

## Archived checkpoint summary

Historical delivery progressed from a Colab-first transcription workflow into a Studio PWA platform contour. Completed source-level slices included platform preparation, authentication/session foundations, projects, sources, Google OAuth/Drive metadata and folder selection, encrypted BYOK credentials, job records and lifecycle guardrails, claim/lease foundations, source availability/materialization, ElevenLabs provider boundaries, Google Docs output boundaries, output persistence/read APIs, frontend output links, batch composer UX, diagnostics, and worker source/Compose wiring.

These historical source-done and CI-verified items explain why Studio must no longer be described as only record-only. They do not prove production-live Studio processing.

## Archived status-chain highlights

- Early Studio job items intentionally described jobs as record-only while worker/provider/output slices did not yet exist.
- Later source-level processing, worker, provider, output, persistence, browser output, and diagnostics slices superseded the record-only-only description.
- Historical rollout/preflight notes recorded partial operator evidence such as migration application, API health, and at one point an idle worker observation.
- At that earlier checkpoint, a controlled rollout smoke was blocked before successful end-to-end completion. The later Gates 0–7 evidence archived below superseded that checkpoint with one bounded successful canary.
- Diagnostics-related work reached source-done/merged and partial deployment/browser evidence, but this did not imply provider execution, Google Docs creation, worker-running, or production-live processing.

## Archived implementation notes preserved from consolidated docs

### Colab-oriented technical specification

Durable information preserved in current docs:

- Colab batch remains the stable ready contour and behavioral baseline.
- Secrets must not be printed or committed.
- Provider and Google raw payloads, transcript bodies, document content, and private source bytes must not be copied into evidence.
- Long-media and manifest behavior are Colab baseline topics for parity, not automatically ready Studio capabilities.

### Validation matrix and runtime checklist

Useful validation commands and evidence rules were moved to `docs/runbooks/validation.md`. Outdated claims that Studio lacked backend/auth/database/workers were removed because source-level components now exist.

### Studio jobs processing contract

Durable guarantees were moved to current authority documents:

- Product rules and readiness criteria: `docs/project-spec.md`.
- Current processing invariants: `docs/studio-processing-contract.md`.
- State machine, data flow, provider/output boundaries, and trust boundaries: `docs/architecture.md`.
- Operator rollout, stop conditions, and recovery procedures: `docs/runbooks/studio-platform-ops.md`.

Historical details from earlier job phases remain non-authoritative here. Current rules are not duplicated in this archive.

### Provider transcription contract

Provider boundaries were consolidated into `docs/project-spec.md` and `docs/architecture.md`: ElevenLabs is the present source-level Studio provider path; OpenAI Studio processing parity remains unfinished. The former standalone provider contract was removed after its current rules were verified as duplicate authority.

### Studio platform prep

Preparation decisions that still matter were consolidated into current product, architecture, CI/CD, and operations docs. The old prep document is historical and no longer source authority.

### Studio deploy runbooks

Current platform operations live in `docs/runbooks/studio-platform-ops.md` and CI/CD safety remains in `docs/ci-cd-rules.md`. The legacy stateless web-only contour and the unreferenced full-platform deploy helper were removed under `PWA-LEGACY-AUTHORITY-01` after documented bootstrap steps and the platform component path became authoritative.

## Archived closed items and PR-chain categories

The following categories are closed historical delivery work, not active items:

- PWA platform preparation and environment boundary definition.
- Studio auth/session/account foundation.
- Projects and sources APIs/UI.
- Google OAuth/Drive connection and safe metadata/folder selection.
- BYOK provider credential storage and selection.
- Job records, list/detail/cancel UI, lifecycle guardrails, preflight, and claim readiness.
- Claim/lease persistence and processing lifecycle foundations.
- Source availability/materialization and execution prerequisites.
- ElevenLabs transcription path.
- Google Docs output creation, safe output persistence, and browser-safe output links.
- Worker source entrypoint and initial Compose source wiring.
- Batch composer UX and source-to-destination rows.
- Diagnostics backend, read-only UI/report export, debug sessions, and UX polish.
- Historical deployment/preflight and partial rollout validation notes that did not produce a successful end-to-end processing canary.

## Archived PR #173–#177 stabilization checkpoint

PR #173 completed source-level safe stage-specific retry/recovery. PR #174 completed source-level Studio source deletion, retention, and storage cleanup. PR #177 merged the following tracked remediation items into `main` at `9f85ffe93102354869f37f60fd525dd60404b878`:

- `DOCS-AUTHORITY-SYNC-02`
- `SECURITY-ENTRYPOINT-01`
- `PWA-LEGACY-AUTHORITY-01`
- `PWA-BROWSER-INTEGRATION-BOUNDARY-01`
- `PWA-WEB-SECURITY-HEADERS-01`
- `PWA-CD-RECOVERY-01`
- `PWA-DEPENDENCY-SECURITY-01`
- `PWA-DEPENDENCY-REPRODUCIBILITY-01`
- `PWA-DEPENDENCY-REPORTING-01`
- `PWA-E2E-FOUNDATION-01A`
- `PWA-BROWSER-DTO-MINIMIZATION-01`
- `PWA-UNHANDLED-DIAGNOSTICS-01`
- `PWA-UPLOAD-VERIFIED-METADATA-01A`
- `REPO-HYGIENE-01`
- `TEST-PORTABLE-PROFILE-01`
- `PWA-FRONTEND-MODULARIZATION-01A`
- `PWA-UPLOAD-RETENTION-CONTRACT-01B`
- `PWA-UPLOAD-RETENTION-PREFERENCES-02`
- `PWA-UPLOAD-POLICY-DISCOVERY-01C`

Repository CI run `29898199041` and Studio PWA CI run `29898198991` passed for the merge revision. Studio Platform CD run `29898198997` deployed and identity-checked the web component only; API deployment, migration `0015_user_source_retention`, worker rollout, public-host header validation, dependency-audit workflow execution, and a controlled processing canary were not proven by that checkpoint.

## Archived PR #180–#191 and processing Gates 0–7

This chain ran from frontend modularization through the first bounded production processing proof and the subsequent source/CI hardening:

- PR #180 `605cbae` and PR #181 `749833c` continued bounded frontend modularization and production-status visibility.
- PR #182 `850bfdf` added the guarded worker-drain path; PR #183 `77a3b39` added rollout/preflight controls.
- PR #184 `89fa7d5` delivered the walkthrough-driven UX/Picker diagnostics batch; PR #185 `900bf5b` delivered upload stabilization and the component deployment baseline used by the first worker/canary.
- PR #186 `39aaaff` closed the result-status and stabilization checkpoint; PR #187 `7362a0c` established the authenticated service-backed browser foundation.
- PR #188 `0b23320` closed the dependency/Actions/CD-observability lane; PR #189 `95d3210` added provider-attempt preflight authority.
- PR #190 `625cd33` merged the catalog source and migration `0016_transcript_catalog_entries`; PR #191 `c02accd` reconciled source-of-truth documentation without changing runtime source.

### Gate 0 — read-only production truth

- Initial preflight `29918894603` proved checkout/config/service facts, then stopped on one running worker before health, revision, and authenticated rows.
- Status run `29925528002` proved a clean `605cbae` checkout and one running worker whose image/rollback identity was not yet trustworthy.
- Drain run `29929528124` proved the old worker `exited`, `exit_code=0`, and `drain_state=gracefully-drained`.
- Preflight `29929607368` then passed repository identity, service health, localhost/public health, and single production-revision detection, and correctly stopped at the pre-migration revision mismatch.

The gate remained read-only: it did not authorize a backup, migration, deploy, worker start, job, provider request, Google mutation, or retry.

### Gates 1–3 — backup, database, and API

- Tagged restic/R2 snapshot `7b03ad00` established the pre-migration rollback boundary.
- The guarded migration applied the known chain through `0015_user_source_retention`; it did not improvise a downgrade.
- Isolated API deployment `30004599136` succeeded.
- Post-deploy preflight `30004696267` proved PostgreSQL/Redis health, database head `0015`, image/database migration equality, and localhost/public API/web health.

### Gate 4 — public browser boundary

The clean 2026-07-24 authenticated smoke opened both Google Picker roles, selected one Drive source and one writable output folder, confirmed one active ElevenLabs credential and a valid Google connection, and completed one local upload without a manual duplicate retry. Removing that disposable local source immediately blocked its composer row and reported queued background storage cleanup. No transcription job or provider call occurred in this smoke.

The active Certbot-managed host configuration was preserved as timestamped backup `studio.librechat.online.pre-security-headers-20260724T154127Z`. The repository-owned six-header policy was applied through a dedicated nginx snippet; `nginx -t`, reload, and service checks passed. Independent checks then returned `200` over TLS 1.3 for `/` and `/api/healthz` with CSP, HSTS, MIME-sniffing, referrer, permissions, and framing headers. An authenticated PWA load under that CSP had no browser-console errors.

### Gate 5 — exactly one worker

Read-only run `30107810563` first proved production at `900bf5b` with the previous worker still safely drained. Worker run `30107907971` initially stopped before build because the prior stopped image bytes were already absent. After separate operator authorization, only the stale stopped container record was removed without volumes. The failed worker job was then rerun: it built the `900bf5b` image, proved database/image Alembic equality, exact running/built/commit-tag image equality, Docker health, and exactly one worker. The status rerun reported `running`, `healthy`, and `identity_match=yes`.

Because the prior image was already absent, the immediate rollback boundary was drain/stop of the new worker; no historical image was invented.

### Gate 6 — one-output canary

After explicit authorization and a no-match preflight, one supported Drive audio source, one owner-scoped ElevenLabs credential, one valid Google connection, and one writable folder produced exactly one submitted job. It completed one ElevenLabs transcription and persisted exactly one `google_docs_transcript`. Read-only Drive metadata confirmed a newly created, non-empty native Google Doc. No manual or automatic second submission occurred.

Post-canary worker-status job `89537922592` in run `30107810563` proved the worker remained `running`/`healthy` at `900bf5b` with `identity_match=yes`. This is evidence only for that bounded scenario.

### Gate 7 — stabilization

Owner-scoped diagnostics recorded one job creation, one processing attempt, one provider request, one output persistence event with `output_count=1`, and one completed terminal state without an error/uncertainty event. Read-only reconciliation reported the case resolved with zero unresolved/conflicting cases; no manual reconciliation or repeated Google side effect was required.

PR #186 and its service-backed browser checks locked the completed-output, relation-queued, resolved-reconciliation, and safe-diagnostics regressions. Web-only CD moved the web component to `39aaaff`; authenticated production verification showed `Статус обработки: Завершена` without exposing the raw relation `queued` label. API and worker correctly remained unchanged.

### Archived CI/CD acceptance chain

- PR #187/post-merge: repository `30129485474`, Studio `30129485476`, and component CD `30129485498`; authenticated Chromium ran with FastAPI, PostgreSQL, Redis, migrations, and seed data, while CD deployed only the changed web component.
- PR #188/post-merge: repository `30174331982` / `30175325342`, Studio `30174331983` / `30175325383`, dependency audit `30175970003`, and component CD `30175325341`. The exact remediation superseded historical failing dependency run `30166841704`.
- PR #189/post-merge: repository `30177377055` / `30177718794`, Studio `30177377357` / `30177718783`, and component CD `30177718793`; source-changed web/API were identity-checked and the worker remained manual-only.
- PR #190/post-merge: repository `30202031053`, Studio `30202031078`, and component CD `30202031076`. Web deployed; API stopped at `manual_migration_required`; worker remained `manual_only`. Chromium failed before project creation and left eight scenarios unrun.
- Exact-main reconciliation at `c02accd`: repository `30207923222` and Studio `30207923262` passed, including all nine authenticated scenarios. Because no application source changed between `625cd33` and `c02accd`, that later pass did not explain or deterministically reproduce the earlier project-navigation race.

These run IDs are historical evidence for their exact revisions and executed jobs only. They do not prove the current working branch, repository migration `0016`, unexecuted CD components, or broader production processing modes.

## Archived PR #207 PWA async reliability batch

PR #207 merged the 30-commit PWA-STABILITY-HARDENING-PR207 batch from base 7871b31dc47158c43c3572612a8d0aa3242d018f as merge commit 26ecae6e6cd0ec0c8a3fd2307b7434970c11edf4. The review diff contained 23 files with 10,446 insertions and 1,387 deletions. Functional numerators/denominators for tasks 03–30 did not change at merge; their separate readiness gates moved to READY after PR-head and exact-main CI.

PR-head repository run 31744423393 and Studio/browser run 31744423370 passed. Exact-main repository run 31744712542 and Studio/browser run 31744712601 passed on the merge SHA. Component CD run 31744712488 selected web and API, fast-forwarded the VPS checkout to 26ecae6, built each selected image, verified running image identity, and emitted STUDIO_PLATFORM_WEB_DEPLOY_OK plus STUDIO_PLATFORM_API_DEPLOY_OK after localhost health. The API probe observed two transient startup failures before the bounded retry succeeded. Migration and worker jobs were correctly skipped because this batch changed neither migrations nor the manual-only worker release scope. Read-only public HTTPS probes returned 200 with successful TLS verification for /healthz and /api/healthz.

Standard component CD does not create GitHub Deployment records or bind web/API to an Environment. The protected studio-production-migration Environment was not selected and no approval was required. Deployment and health are evidenced; no provider/Google call, authenticated workflow, transcript-body observation, or new production transcription canary is claimed. The merged working branch was then removed locally and from origin after local main reached the merge SHA.

### Final active item at publication

`PWA-PREPARATION-PREREQUISITE-BOUNDARY-30` functional acceptance checks:

1. Preparation obtains credentials through the shared validated collection requester and obtains the local-upload policy through its existing runtime validator. The two resources use independent latest-request keys, 15-second deadlines, and teardown AbortSignals.
2. Timeout, transport failure, malformed/duplicate credential data, and malformed policy data fail closed with predefined Russian UI and separate explicit retry controls. Job submission and local device upload remain disabled without valid authority; A → B → A aborts old reads and late settlement cannot alter the active composer or render raw fields.
3. Focused prerequisite regressions `3/3`, complete App suite `187/187`, full Studio Vitest `450/450`, TypeScript, full ESLint, production build, lightweight checks, and `git diff --check` pass.

Functional completion is **[историческая оценка удалена]** on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`.

Readiness gate: branch publication, required PR-head/exact-main CI, and merge remain separately required before READY. They are intentionally open under the current local-only instruction, so lifecycle status remains IN PROGRESS despite [историческая оценка удалена] functional completion.

Non-goals: no credential mutation, local-upload mutation/recovery semantics, Google/Picker behavior, API/schema/migration, deploy, or production mutation.

### Focused acceptance histories

#### Overview collection boundaries

`PWA-OVERVIEW-COLLECTION-BOUNDARY-29` functional acceptance checks:

1. Overview project and credential summaries use the same exact runtime-validated collection requesters as Projects and Settings. Malformed or duplicate IDs fail closed without rendering raw response fields.
2. Both Overview reads are independently latest-request-wins, bounded to 15 seconds, and cancelled on teardown. Each summary exposes its own safe retry; a failed refresh preserves last-known valid data and cannot erase an independently successful summary.
3. Focused Overview boundary regressions `3/3`, complete App suite `184/184`, full Studio Vitest `447/447`, TypeScript, full ESLint, production build, lightweight checks, and `git diff --check` pass.

Functional completion is **[историческая оценка удалена]** locally. Readiness remains IN PROGRESS because branch publication, required PR-head/exact-main CI, and merge are intentionally open under the current local-only instruction.

Non-goals: no Projects mutations, Settings credential mutations, Google/OAuth behavior, API/schema/migration, deploy, or production mutation.
#### Google connection consumers

`PWA-GOOGLE-CONNECTION-CONSUMERS-28` functional acceptance checks:

1. Overview, Projects, and Settings use one exact runtime-validated Google connection requester; no Overview/Projects consumer can accept a malformed or semantically contradictory DTO. The shared request contract carries cancellation without broad component or API churn.
2. Overview and Projects reads are latest-request-wins, bounded to 15 seconds, and cancelled on component teardown. Both expose an explicit safe retry; Projects performs a new authoritative read whenever its persistently mounted page is reactivated after Settings or another route, and a late response from the prior activation cannot replace the newer state.
3. Projects distinguishes loading/unavailable authority from a confirmed disconnected account. While loading or unavailable, source and folder Picker entrypoints are disabled and programmatic folder entry fails closed; raw response fields are not rendered. Focused consumer regressions `3/3`, complete App suite `181/181`, full Studio Vitest `444/444`, TypeScript, full ESLint, production build, lightweight checks, and `git diff --check` pass.

Functional completion is **[историческая оценка удалена]** locally. Readiness remains IN PROGRESS because branch publication, required PR-head/exact-main CI, and merge are intentionally open under the current local-only instruction.

Non-goals: no Overview project/credential read change, OAuth mutation, maintenance OAuth, Picker session/selection change, backend/API/schema/migration, deploy, or production mutation.

#### Primary Google connection lifecycle

`PWA-GOOGLE-CONNECTION-BOUNDARY-27` acceptance checks:

1. The Settings browser surface accepts only the exact server-authoritative Google connection DTO and its semantic invariants: active status is the only connected state, Picker readiness equals configured plus scope-ready, reconnect is required only for a connected account missing Picker scope, and a null status carries no stale account metadata. OAuth start accepts only an HTTPS `accounts.google.com/o/oauth2/v2/auth` capability with the exact single-valued query contract and exact `openid email drive.file` scope set.
2. Initial/repeated `GET /google/connection` requests are latest-request-wins, abortable, and bounded to 15 seconds. OAuth start and disconnect, including any CSRF refresh, are bounded to 20 seconds and guarded synchronously by one parent-owned operation; Settings → Projects → Settings restores disabled/`aria-busy` state and same-act duplicates cannot issue another mutation. Logout/login invalidates stale ownership and a late OAuth success cannot redirect a new session.
3. Timeout, transport loss, HTTP 408/5xx, or malformed mutation success triggers one bounded authoritative connection GET and never automatically repeats POST or DELETE. Disconnect is confirmed only by authoritative revoked/null state; active state is preserved as connected, while OAuth start remains safely unconfirmed because connection state cannot prove capability creation. Sequential backend disconnect replay returns the original terminal metadata without changing the timestamp or duplicating the audit event. Focused Google regressions `11/11`, complete App suite `178/178`, full Studio Vitest `441/441`, TypeScript, full ESLint, production build, Python syntax checks, lightweight checks, and `git diff --check` pass; the authored service-backed regression is not locally executable because bundled Python lacks `pytest`.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no maintenance OAuth, Google Picker composer flow, OAuth callback/start-server business-rule, token format/encryption, API shape, schema/migration, concurrent database-lock redesign, browser persistence, automatic mutation replay, deploy, or production mutation.

#### Retention preference boundary

`PWA-RETENTION-PREFERENCE-BOUNDARY-26` acceptance checks:

1. The browser accepts only the exact server-authoritative five-value retention DTO defined by `project-spec.md` and backend source: one hour, 24 hours, three days, seven days, and 30 days, with the selected value present in that ordered set. The setting remains owner-scoped PostgreSQL state, applies only to future verified local-upload completions, and never changes Google Drive inputs, Google Docs outputs, existing expiry, or browser storage.
2. Initial/repeated `GET /account/preferences` requests are latest-request-wins, abortable, and bounded to 15 seconds. PATCH, including any CSRF refresh, is bounded to 20 seconds and guarded synchronously by one parent-owned operation; Settings → Projects → Settings restores disabled/`aria-busy` state and a same-act duplicate cannot issue a second PATCH.
3. Timeout, transport loss, HTTP 408/5xx, or malformed success triggers one bounded authoritative GET and never automatically repeats PATCH. Exact selected TTL confirms success; a different authoritative TTL restores that value; failed reconciliation restores the last confirmed value. Safe outcomes survive remount, detached settlement gets one post-remount refresh, raw backend detail is never rendered, and logout/login invalidates stale ownership. Focused retention regressions `7/7`, complete App suite `171/171`, full Studio Vitest `434/434`, TypeScript, full ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no retention option/default/business-rule change, backend/API/schema/migration/audit change, storage cleanup execution, browser persistence, automatic PATCH replay, Google OAuth/connection change, deploy, or production mutation.

#### Credential lifecycle boundary

`PWA-CREDENTIAL-LIFECYCLE-BOUNDARY-25` acceptance checks:

1. Repository evidence defines the server authority: create and replace have no idempotency/correlation input and are never replayed automatically; revoked credentials may be replaced explicitly; permanent deletion is terminal, hides the row from owner lists, clears every encrypted version exactly once, and rejects later replace/revoke. Repeated revoke/delete returns success without another state transition or audit event.
2. Settings credential-list reads accept only canonical unique DTOs, are latest-request-wins, abortable, and bounded to 15 seconds. Create, replace, revoke, and delete, including any CSRF refresh, are bounded to 20 seconds and guarded synchronously by create or exact credential ID. Parent-owned pending/outcome state survives Settings remounts, and matching controls expose disabled/`aria-busy` state.
3. Timeout, transport loss, HTTP 408/5xx, or malformed success triggers at most one bounded authoritative list reconciliation and never automatically repeats a mutation. Replace is confirmed only by a newer active version; revoke only by exact revoked state; delete only by exact ID absence; create remains explicitly ambiguous without correlation. Raw key input is cleared immediately after capture, never enters parent/browser state, and raw backend detail is never rendered. Focused credential regressions `11/11`, complete App suite `165/165`, full Studio Vitest `428/428`, TypeScript, full ESLint, production build, Python syntax, lightweight checks, and `git diff --check` pass.
Readiness gate: The new service-backed PostgreSQL/Redis credential regression, branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is open: the bundled local Python runtime has no `pytest`, and the current instruction remains local-only without push or PR.

Non-goals: no automatic create/replace/revoke/delete replay, idempotency-key/API-shape/schema/migration change, browser persistence of secrets or mutation bodies, Google OAuth/connection or retention-preference change, deploy, or production mutation. The existing unique `(user_id, provider, label)` constraint still reserves a deleted label; changing that requires a separate product/schema decision.


#### Project mutation boundary

`PWA-PROJECT-MUTATION-BOUNDARY-24` acceptance checks:

1. Repository evidence defines the safe boundary: project creation has no idempotency/correlation input, update targets one owner-scoped project, archive removes the active row and is not safely replayable from an ambiguous browser outcome. Active project-list responses must contain canonical project DTOs with unique IDs before they can replace browser state.
2. Initial and reconciliation `GET /projects` requests are latest-request-wins, abortable, and bounded to 15 seconds. Create, update, and archive, including any CSRF refresh, are bounded to 20 seconds and guarded synchronously by exact operation/project key; matching controls expose disabled/`aria-busy` pending state and a same-act duplicate cannot issue a second mutation.
3. Timeout, transport loss, HTTP 408/5xx, or malformed success never triggers automatic mutation replay. One authoritative collection read leaves create explicitly ambiguous because no exact correlation exists, confirms update only from exact requested fields plus evidence of change, and confirms archive only from project absence. Outcomes remain project-scoped, raw backend detail is not rendered, a failed create preserves its form, and same-project metadata refresh preserves unrelated composer state. Focused regressions, complete App suite, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no backend idempotency/API/schema/business-rule change, no automatic create/update/archive replay, no durable/browser-storage mutation state, no global API timeout, deploy, or production mutation.

#### Google Picker ownership across project remounts

`PWA-GOOGLE-PICKER-REMOUNT-23` acceptance checks:

1. Replace the unowned global Picker boolean with one synchronous parent-owned operation carrying only `projectId`, `panelId`, `rowId`, and source/first-folder/second-folder kind. A second source or folder attempt in any project is rejected before rerender until the exact matching operation settles; an old or mismatched settlement cannot unlock a newer operation.
2. A → B → A while Picker interaction, source creation, or folder verification is pending preserves a project-scoped pending explanation and disabled controls. Settlement while the originating PreparationPanel is detached stores only predefined safe text and tone for its project; project B cannot see project A's result, and the next explicit project-A Picker attempt clears the prior outcome.
3. Source success explains that authoritative project sources were refreshed and rows must be selected again after remount; folder success explains that the non-persisted row selection must be repeated. No token, Google Drive file/folder ID, selected document, API payload, or raw error enters parent state or browser storage. The focused source/folder remount regression, related Google Picker cluster, complete App suite, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no Picker token or Drive identity persistence, no automatic source/folder replay, no composer draft persistence redesign, no backend/API/schema/OAuth change, deploy, or production mutation.

#### Bounded post-selection Google requests

`PWA-GOOGLE-SELECTION-BOUNDARY-22` acceptance checks:

1. Repository evidence records the recovery boundary: Google Picker source creation is state-changing, accepts no `Idempotency-Key`, and its public source DTO deliberately omits Drive file IDs, so an ambiguous response cannot be matched exactly from the active-sources list. Output-folder verification is non-persisting and therefore needs no mutation replay.
2. Source creation, including any CSRF refresh, stops waiting after 20 seconds and is attempted exactly once per explicit selection. Timeout, transport loss, HTTP 408, or 5xx triggers one authoritative sources reload, predefined safe text, and no automatic POST replay or row placement; definitive 4xx behavior remains explicit. A successful response must contain the exact ordered batch size and canonical project-owned source DTOs before rows are changed.
3. Output-folder verification, including any CSRF refresh, stops waiting after 20 seconds, validates a non-empty name plus nullable/string `web_view_url`, never mutates a row on timeout/failure/malformed data, and always releases source and folder Picker controls. Focused regressions, complete App suite, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no backend/API/schema/idempotency change, no exact automatic recovery where the API exposes no correlation identity, no automatic source-creation replay, no Google Picker remount-ownership redesign, deploy, or production mutation.

#### Bounded Google Picker session and interaction lifecycle

`PWA-GOOGLE-PICKER-TIMEOUT-21` acceptance checks:

1. Both composer entrypoints acquire the secret-bearing Google Picker session through one 20-second request bound shared with any CSRF refresh, and validate non-empty token/public configuration plus `scope_ready === true` before opening Picker. Timeout, transport loss, and malformed payload fail closed with predefined safe text, release composer controls, create no source/folder selection mutation, and are not automatically replayed outside the existing CSRF-rejection contract.
2. The existing 10-second script-loader guard remains intact. Once Picker is built, a five-minute interaction deadline closes it, clears the request-local token copy, settles one safe error, and lets each caller's `finally` release its synchronous ref and shared `pickerBusy` lock. The idempotent settlement guard ignores any callback arriving after timeout.
3. Regressions prove one aborted session POST per explicit attempt, no automatic replay, malformed-session rejection without token exposure, callback-timeout close/unlock, ignored late selection, and no source mutation. Existing cancel/error/duplicate/folder tests, complete App suite, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no backend/API/OAuth/schema change, no automatic source/folder mutation replay, no timeout yet for post-selection source creation or folder verification, no maintenance-panel session refactor, deploy, or production mutation.

#### Local-upload ownership and outcomes across remounts

`PWA-LOCAL-UPLOAD-REMOUNT-20` acceptance checks:

1. `ProjectsPage` owns a synchronous operation registry containing only project, panel-instance, and row IDs. It rejects an exact same-act duplicate before React rerender while preserving independent uploads for different rows in the same mounted panel. Because composer row IDs are regenerated after project remount, any still-pending operation from an older panel instance conservatively blocks all new local intake only in its originating project until settlement.
2. Returning A → B → A while initiation/PUT/completion is pending restores disabled/`aria-busy` input plus a safe pending status. Off-panel settlement stores only predefined project-scoped failure/partial/success text; no `File`, presigned capability, filename, raw response, or failure cause enters parent or browser persistence. A new explicit selection after unlock clears prior outcomes for that project before one new chain begins.
3. One A → B → A regression proves pending restoration, duplicate rejection, project isolation, off-panel safe failure, explicit-retry clearing, later success persistence, authoritative source-list refresh, and exact initiation/PUT/completion counts. Existing same-row dedup/multi-file tests, complete App suite, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no `File`/capability persistence, no automatic initiation or PUT replay, no composer-draft persistence redesign, backend/API/schema/storage change, deploy, or production mutation.

#### Bounded local-upload initiation and object PUT
`PWA-LOCAL-UPLOAD-BOUNDARY-19` acceptance checks:

1. Repository evidence records the recovery boundary: initiation commits a new pending source before returning a presigned capability, accepts no `Idempotency-Key`, and cannot be identified uniquely from active-sources filename/MIME/size data; after a valid response, PUT recovery has exact `source_id` authority and uses only the existing verified completion/reconciliation path.
2. Each initiation POST, any CSRF refresh, and each object PUT stop waiting after 20 seconds. Timeout, transport loss, HTTP 408, or 5xx initiation ambiguity causes one safe sources reload and no automatic POST or PUT; timeout/transport ambiguity after PUT causes no second PUT and invokes only bounded exact-source completion/reconciliation. Definitive storage HTTP rejection remains fail-closed.
3. Regressions cover stalled initiation abort, ambiguous 5xx initiation, stalled PUT abort, exact request counts, source reload, safe unlock/recovery, and absence of raw response/private upload identity. Complete App suite, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no initiation idempotency/API/schema change, no automatic initiation or object PUT replay, no browser persistence of files/capabilities, backend/storage mutation, deploy, or production mutation.


#### Source-deletion ownership and outcomes across remounts
`PWA-SOURCE-DELETE-REMOUNT-18` acceptance checks:

1. A synchronous exact-source deletion registry and its predefined result notices live in persistent `ProjectsPage` memory, remain keyed by source ID and originating project, and cannot be reset by a `PreparationPanel` project remount.
2. Returning A → B → A while DELETE or its authoritative reconciliation is pending restores disabled/`aria-busy` UI and rejects another DELETE before React rerender. Settlement is visible only in the originating project, never renders raw backend detail, and an explicit retry clears only the matching previous outcome before one new request.
3. A project-switch regression proves one DELETE while pending, a fail-closed 5xx/reconciliation outcome after settlement on another project, retry unlock and outcome clearing, a second confirmed deletion, project isolation, authoritative source disappearance, and no raw failure text. Complete App suite, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no automatic DELETE replay, backend/API/schema/business-rule change, browser persistence, storage cleanup execution, deploy, or production mutation.


#### Bounded local-upload completion recovery
`PWA-LOCAL-UPLOAD-COMPLETE-17` acceptance checks:

1. Repository evidence establishes completion replay authority: backend completion returns an already uploaded exact source without another storage `HEAD`, preserves `uploaded_at`/`expires_at`, and does not extend retention; pending completion revalidates exact object metadata and source/project state under a row lock before commit.
2. Each completion POST and any CSRF refresh share a 20-second deadline. Timeout or retryable ambiguity triggers one separately bounded no-store active-sources read: an exact validated `uploaded` source completes locally without replay; only an exact matching `pending` source permits one bounded completion replay. No path repeats source initiation or object PUT.
3. Regressions cover ambiguous PUT recovery, authoritative uploaded suppression, pending-state replay, stalled completion abort/replay, single initiation/PUT counts, safe failure text, and no raw upload identity. Complete App suite, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no initiation/PUT retry, backend/API/schema/storage change, browser persistence of upload capability/source body, source-deletion change, deploy, or production mutation.


#### Bounded source deletion and authoritative absence recovery
`PWA-SOURCE-DELETE-RECOVERY-16` acceptance checks:

1. Repository evidence establishes deletion authority: the backend locks the owner-scoped source and referencing jobs, repeated accepted deletion preserves timestamps and creates no duplicate audit/diagnostic events, and the owner-scoped active-sources list excludes exactly the durably deleted source.
2. A synchronous per-source guard rejects same-act duplicate removal before React rerender. DELETE and any CSRF refresh share a 20-second deadline and are never replayed automatically; timeout, transport loss, HTTP 408, and 5xx trigger one separately bounded active-sources read. Only absence of the exact source ID confirms deletion; presence, malformed data, read failure, or read timeout preserves the source and reports a predefined ambiguous outcome.
3. Regressions cover one DELETE under duplicate clicks, deadline abort plus confirmed absence, fail-closed source presence after transport/5xx ambiguity, safe text, and explicit-retry unlock. Complete App suite, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no automatic DELETE replay, backend/API/schema/business-rule change, browser persistence, storage cleanup execution, local-upload completion change, deploy, or production mutation.



#### Bounded batch creation and exact idempotent recovery
`PWA-BATCH-CREATE-RECOVERY-15` acceptance checks:

1. Repository evidence establishes the recovery authority: a complete exact replay is project/owner/key/request-hash scoped, returns the original ordered jobs with `replayed: true`, and is protected by the backend unique constraint/transaction. The ordinary jobs list is explicitly not treated as batch-membership evidence because its browser DTO omits the idempotency key and batch positions.
2. Batch preflight and create stop waiting after 20 seconds with one shared abort signal across any CSRF refresh. A timed-out or transport-ambiguous create is never repeated automatically; its exact request body and `Idempotency-Key` remain in owner-scoped memory across A → B → A, block a new key, and require one explicit user replay.
3. Regression tests prove one POST before timeout, abort at the deadline, no hidden second POST, project isolation, and byte-identical body/key on explicit replay. Complete App suite, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no automatic POST replay, jobs-list inference, backend/API/schema/business-rule change, browser persistence of request bodies, provider or Google Drive call, deploy, or production mutation.



#### Bounded job mutations and authoritative timeout reconciliation

`PWA-JOB-MUTATION-TIMEOUT-14` acceptance checks:

1. Cancel, provider-cost retry, output reconciliation, and terminal dismissal stop waiting after 20 seconds. The same abort signal also bounds a CSRF refresh, and no timed-out mutation is ever repeated automatically.
2. A timeout triggers one separately bounded authoritative read before ownership is released: job detail confirms cancellation only through `cancelled`/`cancel_requested_at` and dismissal only through `terminal_dismissed_at`; retry readiness confirms queueing/running/completion or an advanced attempt; reconciliation metadata confirms only an observable status/count/check-time transition.
3. Confirmed and still-ambiguous outcomes use predefined safe owner-scoped notices. Integration tests prove exactly one POST for each action, the matching GET reconciliation, and no raw backend/provider/Google response in UI or storage; helper/API tests, complete App suite, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no automatic POST retry, backend idempotency/business-rule change, API/schema change, provider or Google Drive call in local tests, deploy, or production mutation.


#### Safe job mutation outcomes across project switches

`PWA-JOB-MUTATION-OUTCOME-13` acceptance checks:

1. Settlement of cancel, provider retry, output reconciliation, and terminal dismissal produces only predefined safe success/failure notices in persistent ProjectsPage memory, keyed by mutation kind/job and scoped to the originating project; no raw response, path, identifier, or transcript body is copied into notice text or browser storage.
2. A notice remains available after the originating PreparationPanel remounts, is absent in another project, and is cleared when the user explicitly begins the same mutation again. Current-panel retry/reconciliation inline feedback suppresses the owner notice so text is not duplicated; cancel/dismiss feedback uses the owner path directly.
3. Existing four-kind dedup regressions, A → B → A failure/success/clearing/isolation regression, complete App suite, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals for this completed item: no mutation timeout, automatic retry, durable/browser-storage notice persistence, backend idempotency/business-rule change, API/schema change, deploy, or production mutation.


#### Job mutation ownership across projects

`PWA-JOB-MUTATION-OWNERSHIP-12` acceptance checks:

1. A synchronous owner-scoped registry in persistent ProjectsPage tracks cancel, provider retry, output reconciliation, and terminal dismissal independently by mutation kind and job ID; PreparationPanel project remounts cannot clear it.
2. Every covered mutation rejects a duplicate begin before React rerender. Returning to the originating project while the request is pending restores disabled/`aria-busy` UI, and settlement releases only the matching key for one explicit retry without exposing raw backend detail.
3. Existing four-kind dedup regressions, a real A → B → A pending-cancellation regression, complete App suite, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no mutation timeout, automatic retry, backend idempotency/business-rule change, cross-project success/failure message persistence, API/schema change, deploy, or production mutation.


#### Project collection read timeouts

`PWA-PROJECT-COLLECTION-TIMEOUT-11` acceptance checks:

1. Same-project sources and jobs collection GETs receive independent AbortSignals and cannot remain pending beyond 15 seconds; only the matching project/resource key is affected.
2. A newer collection read aborts the older same-key request without committing stale failure or emitting an intentional-abort diagnostic. ProjectsPage teardown invalidates and aborts all active collection reads; real timeout/failure resolves loading to safe Russian UI while preserving last-known successfully loaded items.
3. Focused collection-timeout and failed-refresh preservation regressions, complete App suite, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no mutation timeout or retry, no global API timeout, no backend/API/schema change, no project-list or Google-connection behavior change, deploy, or production mutation.


#### Job detail read timeouts

`PWA-JOB-READ-TIMEOUT-10` acceptance checks:

1. Job detail, outputs, retry metadata, and output-reconciliation metadata GETs receive independent AbortSignals and cannot remain pending beyond 15 seconds; only the matching resource/job key is affected.
2. A newer read aborts the older same-key request without committing stale failure or emitting an intentional-abort diagnostic. PreparationPanel teardown invalidates and aborts all active job reads; a real timeout remains observable and replaces indefinite detail/output loading with existing safe messages.
3. Focused ordering/timeout tests, complete App and latestRequest suites, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no mutation timeout or retry, no global API timeout, no backend/API/schema change, no progress-polling behavior change, deploy, or production mutation.


#### Terminal dismissal deduplication

`PWA-JOB-DISMISS-DEDUP-09` acceptance checks:

1. Two terminal-dismiss attempts for the same job while the first request is in flight produce at most one mutation request; the synchronous per-job guard does not depend on a React rerender.
2. The pinned-terminal dismissal control is disabled and exposes `aria-busy=true` while pending. A safe failure message unlocks one explicit retry, raw backend detail is not rendered, and a successful response preserves the authoritative jobs reload and existing backend idempotency contract.
3. Focused App and JobCard regressions, complete suites, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no terminal-visibility/business-rule change, backend idempotency or audit change, API/schema changes, deploy, or production mutation.

#### Output reconciliation deduplication

`PWA-JOB-RECONCILIATION-DEDUP-08` acceptance checks:

1. Two output-reconciliation checks for the same job while the first request is in flight produce at most one mutation request; the synchronous per-job guard does not depend on a React rerender.
2. The explicit Google Drive check is disabled and exposes `aria-busy=true` while pending. A safe failure message unlocks one explicit retry, raw backend detail is not rendered, and no automatic reconciliation is introduced.
3. Focused App and OutputReconciliationNotice regressions, complete suites, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no reconciliation eligibility/business-rule change, backend idempotency change, automatic Google Drive check, API/schema changes, deploy, or production mutation.

#### Provider-cost retry deduplication

`PWA-JOB-RETRY-DEDUP-07` acceptance checks:

1. Two retry attempts for the same job while the first request is in flight produce at most one mutation request; this includes partial resume/restart requests carrying explicit remaining-provider-cost confirmation and does not depend on a React rerender.
2. An available retry control is disabled and exposes `aria-busy=true` while pending. A safe failure message unlocks one explicit retry, raw backend detail is not rendered, and no automatic provider retry is introduced.
3. Focused App and JobDetailSection regressions, complete suites, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no retry eligibility/business-rule change, backend idempotency change, automatic provider retry, API/schema changes, deploy, or production mutation.

#### Job cancellation deduplication

`PWA-JOB-CANCEL-DEDUP-06` acceptance checks:

1. Two cancellation attempts for the same job while the first request is in flight produce at most one mutation request; the synchronous guard does not depend on a React rerender.
2. Queued and processing cancellation controls are disabled and expose `aria-busy=true` while pending. A safe failure message unlocks one explicit retry, raw backend detail is not rendered, and a successful response preserves the existing authoritative jobs reload.
3. Focused action/component regressions, complete App and JobCard suites, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no backend idempotency contract, API/schema changes, automatic mutation retry, cancellation semantics change, deploy, or production mutation.

#### Job detail ordering

`PWA-JOB-DETAIL-ORDERING-05` acceptance checks:

1. For repeated loads of one job, only the newest detail and outputs requests may commit success or failure state; a stale response cannot restore obsolete source/output data or replace a newer safe error.
2. Retry and output-reconciliation metadata use independent per-job request epochs, so a stale response cannot restore obsolete action availability. After a successful retry or reconciliation mutation, authoritative jobs reload remains immediate and is not blocked by the four detail reads.
3. Shared ordering tests, a component-level repeated-open regression, complete App tests, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no API/backend/schema changes, no global request cache, no mutation retry, no deploy, and no production mutation.

#### Project list ordering

`PWA-PROJECT-LIST-ORDERING-04` acceptance checks:

1. For repeated source-list loads of one project, only the newest request may commit success or failure state; stale responses cannot restore removed sources or erase newly loaded sources.
2. For repeated job-list loads of one project, only the newest request may commit success or failure state; stale responses cannot hide newly created/retried jobs or replace fresh status.
3. Request epochs are isolated by resource and project key. Focused ordering tests, complete App tests, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open under the current local-only instruction.

Non-goals: no request cancellation, API/backend/schema changes, cache persistence, cross-owner state, deploy, or production mutation.

#### Polling resilience

`PWA-JOB-PROGRESS-POLLING-03` acceptance checks:

1. An initial or later transient `/jobs/progress` rejection cannot permanently stop polling; retry does not depend on a previously confirmed response.
2. A stalled request is aborted after 15 seconds and enters the same bounded retry path; project switch/unmount aborts the current request immediately. Intentional cleanup abort is excluded from API-failure diagnostics while timeout/unexpected abort remains observable.
3. Consecutive failures use bounded exponential backoff up to 30 seconds; success resets the normal five-second cadence and outages preserve the last confirmed snapshot.
4. Missing requested jobs trigger authoritative jobs reconciliation without terminating polling; cleanup prevents stale scheduling. Focused tests, full Studio Vitest, TypeScript, ESLint, production build, lightweight checks, and `git diff --check` pass.
Readiness gate: Branch publication, required PR-head/exact-main CI, and merge are separately evidenced before READY.

Functional completion is **[историческая оценка удалена]** locally on `codex/pwa-stability-hardening`, based on `main@7871b31dc47158c43c3572612a8d0aa3242d018f`. The readiness gate is intentionally open: the current instruction is local implementation without push or PR.

Non-goals: no API/worker/schema/provider changes, no changed progress semantics, no fabricated within-request percentage, no deploy, and no production mutation.

### Local validation histories

- `PWA-PREPARATION-PREREQUISITE-BOUNDARY-30` local evidence: focused timeout/retry, malformed-response, and A → B → A teardown regressions `3/3`, complete App suite `187/187`, and full Studio Vitest `450/450` passed. Credential and source-upload-policy reads have independent 15-second latest-request boundaries, timeout and project remount abort their exact signals, and recovery requires separate explicit retry. The credential path reuses the shared duplicate-rejecting validator; malformed policy data is rejected by the existing browser-safe policy validator. Both failures disable their dependent controls and render only predefined text. The first focused runs corrected test-only assumptions about duplicate safe blocker text and shared credential consumers; the first full App run exposed one obsolete fixture that still returned backend-impossible `status=deleted`, which was removed while secret-like extra-field non-rendering coverage remains. TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` pass. No credential/upload mutation, backend/API/schema, deploy, or production state is changed.
- `PWA-OVERVIEW-COLLECTION-BOUNDARY-29` local evidence: focused collection-boundary regressions `3/3`, the two adjusted cross-page timeout regressions `2/2`, complete App suite `184/184`, and full Studio Vitest `447/447` passed. Overview projects and credentials share the exact collection requesters used by their primary consumers; duplicate/malformed collections fail closed without raw-field rendering. Both summaries have independent 15-second latest-request-wins/teardown boundaries and explicit retry while preserving the other summary and any last-known valid data. The first full App run exposed two obsolete signal-count assumptions: navigation now correctly aborts the new Overview request before the destination page creates and times out its own request; the assertions were tightened to verify both aborts. TypeScript, full ESLint, and Vite/PWA production build pass. No backend/API/schema, mutation, deploy, or production state is changed.
- `PWA-GOOGLE-CONNECTION-CONSUMERS-28` local evidence: focused Overview/Projects connection regressions `3/3`, complete App suite `181/181`, and standalone full Studio Vitest `444/444` passed. Overview aborts a stalled read after 15 seconds, reports only safe unavailable state, and succeeds through explicit retry. Projects rejects a contradictory DTO without rendering its raw field, distinguishes unavailable from disconnected, disables source and folder Picker controls, refreshes on every active return, and ignores a late connected response after a newer disconnected read. The two older Settings regressions were updated only for the now-intentional additional Overview/Projects GETs and remain green. TypeScript, full ESLint, and Vite/PWA production build pass. A first parallel four-process gate also completed all `444/444` assertions but hit a post-suite `tinypool` teardown exception; the standalone rerun exited cleanly and is the claimed test evidence. No OAuth mutation, backend/API/schema, deploy, or production mutation is claimed.
- `PWA-GOOGLE-CONNECTION-BOUNDARY-27` local evidence: focused Settings connection regressions `11/11`, complete App suite `178/178`, and full Studio Vitest `441/441` passed. Stalled/malformed connection reads fail closed after 15 seconds with explicit retry and no raw detail. OAuth start and disconnect reject same-act duplicates, expose disabled/`aria-busy`, abort after 20 seconds, perform one authoritative connection read on uncertainty, and never replay POST/DELETE automatically. The exact Google authorization origin/path/query/scope contract rejects hostile or malformed redirect capabilities; logout invalidates late success before navigation. Settings → Projects → Settings preserves detached disconnect ownership/outcome and requests exactly one post-remount refresh. Sequential backend disconnect replay preserves the original terminal timestamp, wipes primary and maintenance token material, and emits one audit event. Python syntax, TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` pass. The backend service regression is authored but was not executed locally because bundled Python lacks `pytest`, so TEST remains partial and CI remains open. No maintenance OAuth, Picker, API shape/schema/migration, deploy, or production mutation is claimed.
- `PWA-RETENTION-PREFERENCE-BOUNDARY-26` local evidence: focused retention regressions `7/7`, complete App suite `171/171`, and full Studio Vitest `434/434` passed. Stalled/malformed initial GET fails closed after 15 seconds without rendering choices; PATCH rejects a same-act duplicate, exposes disabled/`aria-busy`, aborts after 20 seconds, performs exactly one authoritative read, and is never replayed automatically. A → Projects → Settings preserves pending ownership, detached 5xx settlement is confirmed from the exact selected server TTL, then performs one post-remount refresh without repeated extra reads. Failed write plus failed reconciliation restores the last confirmed TTL and renders neither raw write nor read detail. TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` pass. Backend source/test evidence already proves exact five-option validation and repeated-same-value audit idempotence; no backend/API/schema/audit, storage cleanup, Google, deploy, or production mutation is claimed.
- `PWA-CREDENTIAL-LIFECYCLE-BOUNDARY-25` local evidence: focused credential frontend regressions `11/11`, complete App suite `165/165`, and full Studio Vitest `428/428` passed. A stalled/malformed list fails closed after 15 seconds; create clears the raw DOM value immediately, rejects a same-act duplicate, aborts after 20 seconds, performs one authoritative GET, and never replays the POST. Replacement ownership and safe outcomes survive Settings → Projects → Settings without persisting or rendering raw key/backend detail; ambiguous permanent deletion is confirmed only after the exact credential disappears. Backend source now makes deleted credentials terminal/hidden and revoke/delete replay audit-idempotent; a service-backed regression covers two encrypted versions, one revoke/delete audit, crypto erasure, replay stability, hidden list state, and rejected resurrection. Python syntax, full TypeScript/ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` pass. The backend regression was not executed locally because the available bundled Python lacks `pytest`; service-backed CI remains the explicit TEST/CI gate. No API shape/schema/migration, automatic mutation replay, Google/retention, deploy, or production mutation is claimed.
- `PWA-PROJECT-MUTATION-BOUNDARY-24` local evidence: focused project-list/create/update/archive boundary regressions `4/4`, complete App suite `159/159`, and full Studio Vitest `422/422` passed. A stalled project-list read aborts after 15 seconds; a stalled create aborts after 20 seconds, issues one POST plus one list reconciliation, preserves both draft fields, and remains explicitly ambiguous. A deferred update blocks a same-act duplicate, keeps pending/result state scoped across A → B → A, performs one reconciliation after 5xx, and renders no raw detail. An ambiguous archive disappears only after the authoritative list omits the exact project. Existing same-project composer-preservation coverage remains green. TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` passed. No backend/API/schema/idempotency change, automatic replay, PR, CI, deploy, or live evidence is claimed.
- `PWA-GOOGLE-PICKER-REMOUNT-23` local evidence: one A → B → A regression covers both source creation and folder verification `1/1`; the related Google Picker cluster passes `12/12`, complete App suite `155/155`, full Studio Vitest `418/418`, TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` passed. The restored project-A panel exposes a safe pending status and disabled source/folder actions, a programmatic duplicate leaves source/verify mutation counts at one, project B sees only the cross-project busy explanation, and off-panel settlements produce safe project-A notices only after return. A subsequent explicit Picker begin clears the prior project notice. Parent state contains only project/panel/row/kind plus predefined message/tone; token, Drive IDs, selected docs, raw payloads, and raw failures remain request-local and are not persisted. No backend/API/schema/OAuth change, automatic replay, PR, CI, deploy, or live evidence is claimed.
- `PWA-GOOGLE-SELECTION-BOUNDARY-22` local evidence: focused source/folder deadline, ambiguity, validation, and unlock regressions `4/4`, complete App suite `154/154`, full Studio Vitest `417/417`, TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` passed. A stalled source POST is aborted after 20 seconds, a 5xx remains ambiguous, both issue exactly one POST and one authoritative sources reload without row placement or raw detail; stalled folder verification aborts and unlocks all Picker actions, while malformed verification cannot enter row state. The first full regression run exposed six legacy custom fixtures that returned non-canonical `{}` verification payloads; the project-agnostic shared helper now preserves any valid scenario DTO and supplies only the historical canonical fallback, without weakening production validation. No backend/API/schema/idempotency change, automatic mutation replay, PR, CI, deploy, or live evidence is claimed.
- `PWA-GOOGLE-PICKER-TIMEOUT-21` local evidence: focused deadline/validation regressions `3/3`, complete App suite `150/150`, full Studio Vitest `413/413`, TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` passed. A stalled session is aborted after 20 seconds with one POST per explicit attempt and no Picker/selection mutation; malformed capability data is rejected without rendering its token; a Picker that never calls back is hidden after five minutes, releases the source/folder lock, and ignores a late `picked` callback. Six legacy composer tests initially failed because their custom fixtures returned `{}` for the session endpoint while stubbing Picker itself; the shared test helper now supplies the real validated session shape, preserving rather than weakening production validation. No backend/API/OAuth/schema change, automatic selection mutation replay, PR, CI, deploy, or live evidence is claimed.
- `PWA-LOCAL-UPLOAD-REMOUNT-20` local evidence: the A → B → A ownership/outcome regression `1/1`, complete App suite `147/147`, full Studio Vitest `410/410`, TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` passed. The original input returns disabled and `aria-busy`, a programmatic duplicate keeps initiation at one, project B sees neither pending nor result text, and off-panel storage failure is reduced to predefined safe project-A text. Explicit retry clears that outcome, produces exactly one additional initiation/PUT, completes once, refreshes the authoritative source list, and exposes the safe success only after another project-A remount. Parent state contains only operation IDs and predefined notices; `File`, presigned URL/headers, filenames, and raw failure data remain component/request-local and are not persisted. No backend/API/schema/storage change, PR, CI, deploy, or live evidence is claimed.
- `PWA-LOCAL-UPLOAD-BOUNDARY-19` local evidence: backend route/tests show that initiation creates and commits a fresh pending source without idempotency input, while completion is exact-source, owner/project constrained, metadata verified, race revalidated, and replay-safe. Frontend regressions cover stalled initiation `1/1`, ambiguous 5xx initiation `1/1`, and stalled PUT `1/1`; complete App suite `146/146`, full Studio Vitest `409/409`, TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` passed. The initiation cases emit one POST, no PUT/completion, safe text, and one sources refresh; the PUT case aborts one PUT and succeeds only through one exact-source completion, with no second initiation/PUT or raw response/upload identity. No backend/API/schema/storage change, browser persistence, PR, CI, deploy, or live evidence is claimed.
- `PWA-SOURCE-DELETE-REMOUNT-18` local evidence: the A → B → A regression `1/1`, complete App suite `143/143`, full Studio Vitest `406/406`, TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` passed. While the first DELETE and its 5xx reconciliation settle off-panel, the restored source control remains disabled/`aria-busy` and a duplicate begin is rejected synchronously. The predefined ambiguous outcome is absent from project B and retained in project A; explicit retry clears it, one second DELETE can complete while off-panel, and the safe success plus authoritative source disappearance remain visible only on return to project A. Raw backend detail is absent. No backend/API/schema change, automatic DELETE replay, browser persistence, PR, CI, deploy, cleanup execution, or live evidence is claimed.
- `PWA-LOCAL-UPLOAD-COMPLETE-17` local evidence: backend API tests verify replay returns the exact source without another storage `HEAD` and preserves upload/retention timestamps; race tests verify metadata and source lifecycle revalidation before commit. Frontend recovery regressions cover ambiguous PUT `1/1`, authoritative uploaded suppression `1/1`, exact-pending replay `1/1`, and stalled completion deadline/replay `1/1`. Complete App suite `142/142`, full Studio Vitest `405/405`, TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` passed. Each completion attempt and CSRF refresh share a 20-second signal; initiation and object PUT stay single-shot, and no upload URL/private identity or raw error detail is rendered or stored. No backend/API/schema/storage change, PR, CI, deploy, or live evidence is claimed.
- `PWA-SOURCE-DELETE-RECOVERY-16` local evidence: backend source-deletion code/tests verify owner/project locking, job-readiness gates, repeat idempotence, stable deletion/cleanup timestamps, and no duplicate audit/diagnostic events; the active-sources endpoint excludes deleted rows. Recovery regressions cover deadline/dedup/confirmed absence `1/1`, transport ambiguity with source presence `1/1`, and 5xx ambiguity with source presence `1/1`. Complete App suite `140/140`, full Studio Vitest `403/403`, TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` passed. DELETE and CSRF refresh share the 20-second signal; no DELETE is automatically replayed, and raw error detail is absent. The first full run correctly exposed that the old 5xx test treated a state-changing server error as definitive; it now verifies the fail-closed ambiguous outcome after source-list reconciliation. No backend/API/schema change, cleanup execution, PR, CI, deploy, or live evidence is claimed.
- `PWA-BATCH-CREATE-RECOVERY-15` local evidence: backend route/model/tests verify owner/project/idempotency-key/request-hash replay, ordered complete-batch recovery, transaction rollback, and a unique `(owner_id, project_id, batch_idempotency_key, batch_position)` constraint. The ordinary jobs-list DTO omits batch identity, so no unsafe list inference was implemented. Preflight/create timeout regressions `2/2`, A → B → A exact-replay/isolation regression `1/1`, complete App suite `138/138`, full Studio Vitest `401/401`, TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` passed. Preflight and create share a 20-second bound; a timed-out create issues exactly one POST, and explicit recovery reuses the exact body/key without browser storage. No backend/API/schema change, automatic POST replay, PR, CI, deploy, provider/Google call, or live evidence is claimed.
- `PWA-JOB-MUTATION-TIMEOUT-14` local evidence: endpoint audit verified durable idempotency for cancel/dismiss, transactional queue authority for retry, and fail-closed Google reconciliation metadata. Bounded-request helper tests `5/5`, timeout integration regressions `4/4`, API client tests `7/7`, complete App suite `136/136`, full Studio Vitest `399/399`, TypeScript, full ESLint, Vite/PWA production build, and `git diff --check` passed. Each timeout produces exactly one POST followed by the endpoint-specific authoritative GET; provider-cost retry and Google Drive check are never automatically repeated, CSRF refresh shares the deadline signal, and confirmed/ambiguous text is predefined. Initial integration runs exposed two fixture-only assumptions: the test timer also accelerated existing 15-second detail reads, and terminal failed jobs preloaded readiness before explicit open. A distinct 20-second mutation deadline plus abort-driven fixture transition resolved both without weakening production assertions. No PR, CI, deploy, provider/Google call, or live evidence is claimed.
- `PWA-JOB-MUTATION-OUTCOME-13` local evidence: existing same-act mutation regressions plus the expanded project-switch outcome regression `5/5`, complete App suite `132/132`, full Studio Vitest `389/389`, TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` passed. A safe cancellation failure remains visible after remount, disappears on explicit retry, the later safe success is absent in project B and visible on return to project A, and raw backend detail remains absent. Retry/reconciliation current-panel inline feedback suppresses duplicate owner notices; all notice state remains owner-scoped in memory only. One intermediate focused run caught a mechanically malformed template-literal path before tests executed; all four paths were restored by function-bounded replacement and TypeScript plus all final gates pass. No mutation timeout, automatic retry, PR, CI, deploy, or live evidence is claimed.
- `PWA-JOB-MUTATION-OWNERSHIP-12` local evidence: four existing same-act mutation dedup regressions `4/4`, project-switch ownership regression `1/1`, complete App suite `132/132`, full Studio Vitest `389/389`, TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` passed. A pending cancellation remains disabled and `aria-busy` after A → B → A remount, a second POST is rejected synchronously, settlement releases the matching owner-scoped key for explicit retry, and raw backend failures remain absent from the DOM. The same persistent registry is wired to retry, reconciliation, and dismissal, whose existing same-act regressions remain green. No mutation timeout, automatic retry, PR, CI, deploy, or live evidence is claimed.
- `PWA-PROJECT-COLLECTION-TIMEOUT-11` local evidence: focused collection timeout and failed-refresh preservation regressions `2/2`, complete App suite `131/131`, full Studio Vitest `388/388`, TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` passed. Sources/jobs collection requests receive independent signals and abort after 15 seconds; teardown/supersede cancellation is silent, while real failure resolves loading to safe Russian UI and retains last-known items. The production timeout remains 15 seconds; tests accelerate only that exact timer. No PR, CI, deploy, or live evidence is claimed.
- `PWA-JOB-READ-TIMEOUT-10` local evidence: latestRequest ordering/abort/timeout/teardown suite `6/6`, App stalled-read regression `1/1`, complete App suite `130/130`, full Studio Vitest `387/387`, TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` passed. All four job-read signals abort at 15 seconds, detail/output loading resolves to safe retryable UI, a newer same-key request cancels its predecessor without stale failure, and teardown cancellation is explicitly ignored by API diagnostics while timeout aborts remain observable. The first App run exposed the existing terminal auto-load path and was narrowed to a processing-job fixture so timeout and supersede cases remain independent. No PR, CI, deploy, or live evidence is claimed.
- `PWA-JOB-DISMISS-DEDUP-09` local evidence: App terminal-dismiss regression `1/1`, complete JobCard suite `4/4`, complete App suite `129/129`, full Studio Vitest `383/383`, TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` passed. A same-act double click produces one POST; pending action is disabled with `aria-busy`, failure unlocks explicit retry, authoritative jobs reload remains intact, and raw backend detail remains absent from the DOM. The first focused run exposed an incomplete fixture that omitted canonical `terminal_dismissed_at: null`; the corrected fixture and repeated gates pass. No PR, CI, deploy, or live evidence is claimed.
- `PWA-JOB-RECONCILIATION-DEDUP-08` local evidence: App reconciliation regression `1/1`, complete OutputReconciliationNotice suite `2/2`, complete App suite `128/128`, full Studio Vitest `381/381`, TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` passed. A same-act double click produces one POST; pending action is disabled with `aria-busy`, failure unlocks explicit retry, the existing authoritative jobs/detail reload remains intact, and raw backend detail remains absent from the DOM. No PR, CI, deploy, Google Drive call, or live evidence is claimed.
- `PWA-JOB-RETRY-DEDUP-07` local evidence: App provider-cost retry regression `1/1`, complete JobDetailSection suite `8/8`, complete App suite `127/127`, full Studio Vitest `380/380`, TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` passed. A same-act double click produces one POST; pending action is disabled with `aria-busy`, failure unlocks explicit retry, both explicit partial requests preserve `{confirm_remaining_provider_cost: true}`, and raw backend detail remains absent from the DOM. No PR, CI, deploy, provider call, or live evidence is claimed.
- `PWA-JOB-CANCEL-DEDUP-06` local evidence: focused cancellation regressions `6/6`, complete App suite `126/126`, complete JobCardActions suite `8/8`, full Studio Vitest `378/378`, TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` passed. A same-act double click produces one POST; pending queued/processing controls are disabled with `aria-busy`, a failed request unlocks explicit retry, and raw backend detail remains absent from the DOM. No PR, CI, deploy, or live evidence is claimed.
- `PWA-JOB-DETAIL-ORDERING-05` local evidence: ordering helper `3/3`, component repeated-open regression `1/1`, complete App suite `125/125`, full Studio Vitest `375/375`, TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` passed. Evidence covers stale success and failure suppression, independent resource keys, and integration wiring for out-of-order detail/output responses. Jobs reconciliation remains immediate after retry/reconciliation mutations. No PR, CI, deploy, or live evidence is claimed.
- `PWA-PROJECT-LIST-ORDERING-04` local evidence: ordering helper `3/3`, complete App suite `124/124`, full Studio Vitest `374/374`, TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` passed. Tests prove stale success suppression, stale failure suppression, newest failure visibility, and independent resource keys. One pre-commit run caught and prevented an accidental recursive helper implementation; the corrected implementation passed all repeated gates. No PR, CI, deploy, or live evidence is claimed.
- `PWA-JOB-PROGRESS-POLLING-03` local evidence: focused polling Vitest `7/7` plus API abort diagnostics `6/6`; full Studio Vitest `371/371`; TypeScript, full ESLint, Vite/PWA production build, lightweight repository checks, and `git diff --check` passed. Fake-timer evidence covers initial rejection, bounded exponential backoff, cadence reset, 15-second stalled-request abort, retry after timeout, reconciliation continuity, timer cleanup, in-flight abort, suppression of the exact intentional stop reason, and continued timeout-abort diagnostics. The first Vite attempt exposed an incomplete local pnpm link layout (`workbox-window` unresolved); an npm-compatible hoisted local `node_modules` layout fixed the environment without manifest/lockfile changes. No PR, CI, deploy, or live evidence is claimed.

## Archived PR #208 PWA hardening closure

PR #208 (`codex/pwa-session-bootstrap-hardening`) closed the focused PWA hardening sequence 31–47 and was merged into `main` on 2026-08-14.

- Base: `main@26ecae6e6cd0ec0c8a3fd2307b7434970c11edf4`.
- Final PR head: `62f2ea844e71071c151066c2538f6ef9e340c0bd`.
- Merge commit: `830bd00754567dfa6809e1e36bb7fcbaa145b824`.
- Functional denominator for tasks 31–47: [историческая оценка удалена; см. Git history] (17 items × 3 equal-weight criteria).
- Exact-main repository CI run `31818095906`: `checks` success.
- Exact-main Studio run `31818095864`: `studio` and `browser-e2e` success.
- Component CD run `31818095877`: `studio-web` selected and successful; worker/API/migration jobs correctly skipped.
- VPS checkout fast-forwarded to exact merge commit, target-built/running web image identity matched, localhost `/healthz` passed, and `STUDIO_PLATFORM_WEB_DEPLOY_OK` was emitted.
- Local and remote working branches were deleted only after merge ancestry and clean synchronized `main` were verified.

The completed sequence covered bounded/latest-wins auth and collection reads, credential/diagnostics/analytics DTO boundaries, project/job recovery authority, mutation outcome invariants, focused batch review, and CI portability corrections. Detailed code/test history remains recoverable from PR #208 and its atomic commits; this archive does not duplicate raw logs.

Readiness at closure:

- project-wide percentage remained `N/A` because `docs/project-spec.md` had no single closed non-overlapping project denominator;
- Colab batch + Realtime remained [историческая оценка удалена; см. Git history] under owner-accepted scope;
- Studio PWA Live functional contract remained [историческая оценка удалена; см. Git history];
- Studio PWA Live delivery Evidence remained [историческая оценка удалена; см. Git history] because microphone-only, mixed and negative lifecycle canaries were still absent.

## Archived PR #210 product requirements baseline closure

PR #210 (`feature/product-requirements-v2`) зафиксировал owner requirements как два production-продукта, четыре runtime contour и 109 равновесных atomic AC. Он merged в `main` 2026-08-15.

- Base: `main@a252a1efa54ba952ec4eb04405fae5722f15d7b5`.
- Final PR head: `e3d4521c30effbd1baa082d4c49abf543e28146a`.
- Merge commit: `8fe0dd722d0433440b41ef6dfe0fa0489f8f8fb8`.
- Exact PR-head CI run `31842755434`: success.
- Exact-main CI run `31842984066`: success.
- Scope был docs-only; Studio path detection не запускал component CD, GitHub Deployments для revision отсутствовали, поэтому `DEPLOY` и `LIVE` были N/A.
- Baseline readiness: Colab [историческая оценка удалена], Studio PWA [историческая оценка удалена], project [историческая оценка удалена].
- Локальный `main` синхронизирован с exact merge commit; merged local/remote branch удалена после ancestry/clean-state проверки.
- Approved post-deploy metadata writer отсутствует (`metadata_sync.enabled=false`), поэтому отдельный follow-up docs-only PR не создавался; closure переносится в archive при начале следующего авторизованного scope.

## Archived PR #211 language and diagnostics closure

PR #211 (`feature/pwa-language-diagnostics`) закрыл scoped explicit-English, diagnostics-export и analytics-percentage slice и был merged в `main` 2026-08-15.

- Base: `main@8fe0dd722d0433440b41ef6dfe0fa0489f8f8fb8`.
- Final PR head: `f689ab09675ac7d899c040e05c3ed097632a74da`.
- Merge commit: `f90e0d7b3b10d345a9ea6ff34f5b8c3025d818d7`.
- Scoped completion: [историческая оценка удалена]; readiness после merge: Studio PWA [историческая оценка удалена], project [историческая оценка удалена].
- Exact PR-head checks: CI run `31848205846`, Studio/browser run `31848205831` — success.
- Exact-main checks: CI run `31848408225`, Studio/browser run `31848408202` — success.
- Component CD run `31848408276`: `deploy-web` и `deploy-api` success; worker и migration jobs корректно skipped для scope.
- GitHub Deployments API record отсутствует; approved post-deploy metadata writer также отсутствует (`metadata_sync.enabled=false`). Фактический merge/CD state восстановлен в следующем authorized scope без отдельного follow-up PR.

## Archived PR #213 goal-driven repository policy closure

Goal `DOCS-GOAL-DRIVEN-01` migrated the repository policy to `goal-driven-v1` and was merged through PR #213 on 2026-08-20.

- Base: `main@f3a3f33fb0ce019c1916d95f754ed72d1d56ee01`.
- Final PR head: `4ee8f65cf6a16b9190ddedefd4024a2ca03d0978`.
- Merge commit: `3ef4a45e9e17be7ae78bd574f5e0de6f101a4b55`.
- Exact PR-head CI run `32344744575`: `checks` success.
- Exact-main CI run `32345079183`: `checks` success.
- Scope был docs-only: `DEPLOY` и `LIVE` — `N/A`; product readiness не изменилась и осталась [историческая оценка удалена].
- Standalone `docs/agent-delivery-workflow.md` удалён намеренно; session orchestration и Goal lifecycle теперь определяются root `AGENTS.md` и current user instruction.
- Stale active checkpoint обнаружен при начале следующей авторизованной Goal и перенесён в archive без отдельного follow-up PR.

## Archived PR #214 dependency remediation closure

Goal `SECURITY-DEPENDENCY-REMEDIATION-01` removed the current High findings from the installed Node/Python dependency graphs and was merged through PR #214 on 2026-08-20.

- Base: `main@3ef4a45e9e17be7ae78bd574f5e0de6f101a4b55`.
- Final PR head: `f53cd37ee23f8fb77f50500b2bb57937a1672e5c`.
- Merge commit: `50dff6f7401a08393137d5bd5e28162bd8df1133`.
- Fixed graph: `brace-expansion 5.0.9`, `fast-uri 3.1.5`, `nanoid 3.3.18`, `cryptography 50.0.0`; exact-main Dependency audit run `32351941880` completed with both `node` and `python` success.
- Exact-main repository CI run `32351540609` and Studio/browser CI run `32351540560` completed successfully.
- Component CD run `32351540606` deployed web and API. Worker lifecycle used status `32351708257`, graceful drain `32351908990`, manual deploy `32352024954`, and final status `32352126674`; the final running image matched the merge-SHA tag and was healthy.
- Public web/API health returned `200`; API reported reachable database and current migrations. No provider/Google transcription canary was run, so this LIVE evidence is bounded to dependency-bearing runtime health.
- Product readiness remained [историческая оценка удалена]: the Goal changed no product AC or denominator.
- Approved post-deploy metadata writer remained absent; actual closure was reconciled at the start of the next authorized Goal without a follow-up docs-only PR. Local `main` was synchronized and the merged local/remote Goal branch was safely removed.

## Archived PR #215 arbitrary segments closure

Goal `PWA-ARBITRARY-SEGMENTS-01` generalized the segment composer from a narrow two-part case to an ordered arbitrary-`N` plan and was merged through PR #215 on 2026-08-20.

- Base: `main@50dff6f7401a08393137d5bd5e28162bd8df1133`.
- Merge commit: `919e6137ed0e806db168a43d292ab7874293549e`.
- Exact-main repository CI run `32376152400`: `checks` success.
- Exact-main Studio/browser CI run `32376152418`: `studio` and `browser-e2e` success.
- Component CD run `32376152217`: `studio-web` and `studio-api` success; worker rollout correctly `N/A` for unchanged worker runtime.
- Production API/web exact revision and health were confirmed.
- Bounded LIVE canary job `69fe73ed-8769-4806-ae35-7616594cbf13` used one reviewed short synthetic source and clip `00:01–00:05`; it completed with one `transcript_doc_v1.2` Google Docs output. Private URLs, document IDs, source metadata and transcript body are intentionally omitted.
- `PWA-SEGMENTS-01` reached [историческая оценка удалена; см. Git history], status `READY`, Evidence `SPEC/CODE/TEST/CI/DEPLOY/LIVE ✅`.
- The same canary exposed a separate browser-contract regression: canonical English `language_mode=en` was rejected by list/detail parsing, producing false collection/detail errors and stale `[историческая оценка удалена]` while outputs already reported completion. `PB-05` was therefore corrected from ✅ to ❌ at the start of Goal `PWA-JOB-STATE-CONSISTENCY-01`; project readiness changed from `83/109` to `82/109` without denominator change.
- Approved post-deploy metadata writer remained absent (`metadata_sync.enabled=false`); closure was reconciled in the next authorized Goal rather than a follow-up docs-only PR. Local and remote merged branches were safely removed after clean synchronized `main` verification.

## Archived PR #216 job state consistency closure

Goal `PWA-JOB-STATE-CONSISTENCY-01` устранила рассинхронизацию terminal job между list, progress, detail и output UI и была merged через PR #216 2026-08-20.

- Base: `main@919e6137ed0e806db168a43d292ab7874293549e`.
- Final PR head: `ec88934f1dc730a63bcdf076e19e4639a5102938`.
- Merge commit: `ebf02da1636d9362131a1b44161cda1c68f06080`.
- Exact PR-head CI: repository run `32399832182` и Studio/browser run `32399832196` — success; conditional failure-artifact upload единственный ожидаемый skip.
- Exact-main CI: repository run `32400141331` и Studio/browser run `32400141449` — success.
- Component CD run `32400141509`: `deploy-web` и deployment summary success; API, worker и migration корректно skipped для frontend-only diff. VPS fast-forward, running image identity и localhost `/healthz` подтвердили exact merge revision; marker `STUDIO_PLATFORM_WEB_DEPLOY_OK` получен.
- Public API health подтвердил reachable database и current migrations. GitHub Deployment record для merge SHA отсутствовал.
- Fresh authorized production session повторно открыла исходную bounded canary job `69fe73ed-8769-4806-ae35-7616594cbf13`: list/card/detail одновременно показали terminal completed/`100%`, один safe Google Docs output и canonical English без ложных collection/detail errors. Второй provider job не создавался.
- `PB-05` подтверждён; readiness на closure: `PWA-BATCH-01 [историческая оценка удалена], Studio PWA [историческая оценка удалена], project [историческая оценка удалена].
- Required Goal Evidence: `SPEC/CODE/TEST/CI/DEPLOY/LIVE ✅`. Approved post-deploy metadata writer отсутствовал; closure reconciled в начале следующей authorized Goal. Local и remote merged branches удалены после проверки ancestry и clean synchronized `main`.

## Archived PR #217 ingest metadata polish closure

Goal `PWA-INGEST-METADATA-POLISH-01` была merged через PR #217 и завершила source creation metadata, output-folder Favorites и active-source expiry boundary.

- Base: `main@ebf02da1636d9362131a1b44161cda1c68f06080`.
- Final PR head: `5e0f4f40f5cbcb6ce7b7e3edd5234be812ca0c32`.
- Merge commit: `6bcb0ed49aeb6e491765fda45bf74b6e68f7b67e`.
- Exact PR-head checks: repository run `32417379985` (`checks`) success; Studio run `32417379977` (`studio`, `browser-e2e`) success.
- Protected migration `0021_source_creation_and_folder_favorites`: run `32419734240` success.
- Worker rollout: deploy run `32419939486` success; terminal status run `32420035216` success. API/web applicable deployment gates also completed successfully; migration gate returned to closed state.
- Bounded LIVE canary persisted one favorite and created one accepted Google Docs output. Source creation metadata correctly failed closed as `Created at: unknown`, rather than substituting modified/upload/job/output time.
- PR evidence record: https://github.com/Just9120/Elevenlabs-API/pull/217#issuecomment-5362405098.
- Product readiness at closure: Studio PWA [историческая оценка удалена], project [историческая оценка удалена]; `PC-11` and `PI-02` closed, while `PB-10`/`PD-06` remained open because unknown source creation time is honest but does not satisfy their full-scope requirement.
- The same LIVE session exposed a separate duplicate-state inconsistency: an accepted completed output was visible while provider authority was reported unresolved. This was not counted as a new denominator item and is addressed in the next authorized Goal.
- Required Goal Evidence: `SPEC/CODE/TEST/CI/DEPLOY/LIVE ✅`. Approved post-deploy metadata writer remained absent; closure was reconciled at the start of the next authorized Goal without a follow-up docs-only PR.

## Archived PRs #218–#221 PWA operability closure

Goal `PWA-OPERABILITY-POLISH-02` и три bounded production-preflight follow-ups были завершены и merged в `main` 2026-08-22.

- Goal implementation PR #218 merged как `1fc868847377ad059743ac4d1aa3ae0573d27507`; последующие safe diagnostics/runtime-secret validator PRs #219–#221 merged до `main@dd194c929d957e822ff618df294dc54e72d5971e`.
- Exact-main CI для финального revision: repository run `32575534468` success; Studio run `32575534462` success.
- Read-only production preflight `32575670127` success подтвердил reviewed mounted-secret validation boundary без раскрытия values.
- Manual worker deploy `32575720276` success; final worker status `32575774151` success на exact `dd194c9`.
- Protected migration `0022_account_operability`, API deployment и bounded owner LIVE validation были завершены ранее в этом chain; migration gate после release возвращён в закрытое состояние.
- Scope закрыл `PM-03`, `PO-10/11/17/18`, persistent accent и false unresolved provider-attempt defect. Archived/clear destructive paths не запускались в production.
- Approved post-deploy metadata writer отсутствовал; closure reconciled при старте следующей authorized Goal без docs-only follow-up PR.

## Archived PRs #225–#226 source-folder ingestion closure

Goal `PWA-INGEST-FOLDERS-01` завершила bounded local/Google Drive folder intake и shared target-folder semantics 2026-08-23.

- OAuth/source-folder implementation PR #225 merged как `main@17a9fc408a2d352005be08d981325c21de4d1dc0`; exact-main repository CI `32642653678`, Studio/browser CI `32642653695` и component CD `32642653667` завершились успешно.
- Runtime scope correction была доставлена API-only CD `32654826834`, job `97231852416`, marker `STUDIO_PLATFORM_API_DEPLOY_OK`; primary и maintenance OAuth grants были переподключены.
- Shared target propagation fix PR #226 имел exact head `443c61212d6f1f10efa531b34b0d4c1981d7391c` и merged как `cb3a9e9216521c56e07b6f7b6fda9bf8eb8051f8`.
- PR-head repository CI `32656908141`/job `97236994175` и Studio CI `32656908153`/jobs `97236993792`, `97236993909` — success. Exact-main repository CI `32657081954` и Studio CI `32657081982` — success.
- Web deployment run `32657081893`, job `97237430813`, достиг `STUDIO_PLATFORM_WEB_DEPLOY_OK`; target revision и running image identity соответствовали merge SHA, localhost health прошёл. API, migration и worker были корректно skipped для frontend-only diff.
- Bounded LIVE после deployment импортировал девять supported Drive files в девять composer rows. Первая verified target folder заполнила все девять ранее unassigned rows, все флаги `До конца файла` остались включены, status показал `Готово: 9 из 9`, review control был доступен. Provider job не создавался.
- Closure readiness: `PWA-INGEST-01 [историческая оценка удалена], Studio PWA [историческая оценка удалена], project [историческая оценка удалена]; required Evidence `SPEC/CODE/TEST/CI/DEPLOY/LIVE ✅`.
- Approved post-deploy metadata writer отсутствовал (`metadata_sync.enabled=false`), поэтому фактический closure reconciled в начале следующей authorized Goal. После проверки ancestry и clean state локальная/remote branch была удалена, `main` синхронизирован.

## Archived PR #227 timestamp authority closure

Goal `PWA-TIMESTAMP-AUTHORITY-01` закрыла canonical `PB-10` и `PD-06` и была merged через PR #227 2026-08-23.

- Base: `main@cb3a9e9216521c56e07b6f7b6fda9bf8eb8051f8`.
- Final PR head: `e83a497e5364c19eeee48146aa56ea8fa7f7ad4b`.
- Merge commit: `800bcc820529ff3c78214c129c593d182c621c62`.
- Exact PR-head required checks: repository run `32660004784` (`checks`) success; Studio/browser run `32660004726` (`studio`, `browser-e2e`) success.
- Exact-main CI: repository run `32660175995` и Studio/browser run `32660175973` — success.
- Component CD run `32660176008`: `deploy-web`, `deploy-api` и deployment summary success; migration и worker корректно skipped, потому что schema/worker не менялись.
- После explicit owner action-time approval ровно один bounded production canary `00:01–00:05` завершился `100%`, создал один persisted `transcript_doc_v1.2` Google Docs output и не запускался повторно.
- Два последовательных single-document standardization dry-run классифицировали новый документ как current standard с authoritative source creation date: `0` изменений, `1` без изменений, `0` blocked, `0` unreadable. Отдельный recursive dry-run подтвердил fail-closed blocked outcome для двух legacy документов без source authority и не выполнил mutation.
- `PWA-BATCH-01` достиг [историческая оценка удалена; см. Git history], `PWA-STANDARDIZATION-01` — [историческая оценка удалена; см. Git history]; Studio PWA [историческая оценка удалена; см. Git history], project [историческая оценка удалена; см. Git history].
- Required Goal Evidence: `SPEC/CODE/TEST/CI/DEPLOY/LIVE ✅`. Safe delivery record: https://github.com/Just9120/Elevenlabs-API/pull/227#issuecomment-5388439165.
- Approved post-deploy metadata writer отсутствовал (`metadata_sync.enabled=false`); closure reconciled в начале следующей authorized Goal без docs-only follow-up PR. Local `main` был clean и синхронизирован с merge SHA; merged branch удалена local/remote.

## Archived PRs #231–#232 Colab production completion closure

Goal `COLAB-PRODUCTION-COMPLETION-01` завершила canonical Colab batch/realtime scope 2026-08-24.

- Base chain начат от `main@ebbba50a938feb2d06b2ec59e828834ff204988d`; implementation PR `#231` merged как `ceab95988b4a16f36e76134d6312a10c60d72fe5`.
- Auto-detection-default extension PR `#232` merged как `c9ac43fc71a97a868db744088c06c69882a555fa`.
- Exact PR-head CI `32738379146` и exact-main CI `32738787968` завершились success; Studio workflows корректно не запускались из-за Colab-only path filter.
- Bounded batch LIVE обработал nested local-folder fixture, создал один native Google Doc с authoritative `2026-08-01T09:10:11Z` source creation time и подтвердил document-before-manifest ordering. Повторный provider charge не выполнялся.
- Owner-controlled ordinary-Chrome realtime matrix подтвердила microphone/display/mixed, repeated start/stop, permission cancel и resource release; шесть bounded provider sessions не выявили воспроизводимого capture break.
- `COLAB-BATCH-01` достиг `23/23`, `COLAB-REALTIME-01` — `6/6`, Google Colab — `29/29`; project readiness стала [историческая оценка удалена].
- Colab не имеет VPS deployment unit, поэтому `DEPLOY N/A`; reviewed repository revision/launcher и manual runtime составили applicable delivery Evidence.
- Approved post-deploy metadata writer отсутствовал; closure reconciled при старте следующей authorized code-bearing Goal без отдельного docs-only PR.

## Archived PR #233 speaker identity closure

Goal `PWA-SPEAKER-IDENTITY-01` завершена 2026-08-24.

- Base: `main@c9ac43fc71a97a868db744088c06c69882a555fa`; merge commit PR `#233`: `5e4a3aae8b79f2cb69c6c2efc8282d961b0392e6`.
- Exact-main repository CI `32760830338` и Studio/browser CI `32760830386` завершились success.
- Worker drain `32762666106`, protected migration/API release `32762815131` и worker deployment `32763111064` завершились success; production schema достигла `0024_speaker_identity`.
- Bounded synthetic two-speaker LIVE завершил diarized job без повторного canary, создал два owner profiles, отдал bounded samples и persisted explicit label-to-profile assignments в exact Google Docs и History metadata.
- Required Goal Evidence: `SPEC/CODE/TEST/CI/DEPLOY/LIVE ✅`; `PWA-SPEAKER-IDENTITY-01 5/5`.
- Approved post-deploy metadata writer отсутствовал (`metadata_sync.enabled=false`), поэтому closure reconciled в начале следующей authorized code-bearing Goal. После проверки ancestry merged branch была удалена, local `main` синхронизирован с exact merge SHA.

## Archived PRs #234–#235 Audio Preparation closure

Goal `PWA-AUDIO-PREPARATION-01` завершила canonical Audio Preparation scope 2026-08-25.

- Implementation PR `#234` merged как `1751d34ce44a33b8d9f28bff8642fe8d62fe7e4c`; terminal-cleanup hotfix PR `#235` merged как current main `16badb0aa4404ae2616a3d46070925b54b043963`.
- Exact-main repository CI runs `32813529065` и `32813529090` завершились success.
- API deployment run `32813529033`, worker drain `32816893138`, worker deployment `32816951174` и terminal worker status `32818291988` завершились success; running revision identity совпала с exact main.
- Production schema достигла `0025_audio_preparation`; migration release gate после rollout возвращён в закрытое состояние.
- Bounded LIVE operation `2ad99ead-1c45-4439-8e8a-d64c2bcc3037` подтвердила preview `0:04 → 0:02`, terminal `completed · 100%`, retained reusable result и удаление ephemeral source после reload.
- Hotfix устранил production-only cleanup drift при `SessionLocal(autoflush=False)`: terminal state теперь flush-ится до readiness query.
- Required Goal Evidence: `SPEC/CODE/TEST/CI/DEPLOY/LIVE ✅`; `PWA-AUDIO-PREPARATION-01 16/16`, Studio PWA `107/107`, project `136/136`.
- Approved post-deploy metadata writer отсутствовал (`metadata_sync.enabled=false`), поэтому closure reconciled в начале следующей authorized Goal. Local `main` clean и синхронизирован, merged branches удалены.

## Archived PR #236 UX/IA polish closure

Goal `PWA-UX-IA-POLISH-01` завершена 2026-08-25.

- Base: `main@16badb0aa4404ae2616a3d46070925b54b043963`; final PR head `86232adf67d6d3fa5fe8b5a6d910ff04dd951bfd`; merge commit PR `#236`: `091e558ebe5c369486056f2ef94f67f99a459ee0`.
- Exact-head required CI завершился success: repository run `32832630083`; Studio/browser run `32832630155`.
- Exact-main CI завершился success: repository run `32832907020`; Studio/browser run `32832906999`.
- Studio Platform CD run `32832907052` развернул web и API; web job `97755369406`, API job `97755621970` завершились success с exact merge revision. Migration была N/A, worker manual-only unit не изменялся.
- Bounded authenticated LIVE после normal service-worker reload подтвердил task terminology, default-closed fragmentation, пять Settings routes, Files & Storage catalog, simplified diagnostic bundle и Audio source disclosure/terminal actions. Browser console errors не наблюдались; exact click handoff Audio → Transcriptions дополнительно покрыт automated tests, но не был повторно dispatch-нут во встроенном browser из-за CDP timeout.
- Product denominator не менялся: `PWA-AUDIO-PREPARATION-01 16/16`, Studio PWA `107/107`, project `136/136`; required Goal Evidence `SPEC/CODE/TEST/CI/DEPLOY/LIVE ✅` с указанным ограничением handoff observation.
- Approved post-deploy metadata writer отсутствовал (`metadata_sync.enabled=false`), поэтому closure reconciled в начале следующей authorized Goal без docs-only follow-up PR. Local `main` был clean и синхронизирован; merged branch удалена local/remote.

## Archived PRs #237–#243 Audio workspace production completion

Goal `PWA-AUDIO-WORKSPACE-02` завершила production UX/runtime stabilization Audio workspace и observable uploads 2026-08-26.

- Базовый implementation chain завершён PR `#237`; OBS/Matroska duration и long-running concat follow-ups доставлены через PR `#238–#242`.
- Финальный FLAC precision fix PR `#243`: head `0a01c1c3bc11ef4c0e7082caaf30e0e634d1ec35`, merge `018b560035e4ff2219c246f734216f76537875ee`.
- Required PR-head checks: repository `32899723581`, Studio/browser `32899723679` — success. Exact-main CI: repository `32900076070`, Studio/browser `32900076159` — success.
- Component CD `32900076101`, worker drain `32904910880`, deploy `32904997797` и status `32905120372` завершились success на exact merge revision; schema migration не требовалась.
- Production concat `9010f902-145b-4ef0-bfef-0416a20daeaf` подтвердил обработку трёх OBS/MKV (`137:36 → 129:48`). Финальный FLAC output `78da8f8e-dfb4-47f7-b6db-fb9a64995fb0` подтверждён как `s16`, `48 kHz`, mono, `7907.718563` секунд, `334113611` bytes (`318.64 MiB`).
- Audio и Transcriptions production uploads показали реальный per-file/aggregate progress; Transcriptions прошла стадии `16% → 22% → 30% → 34% → 51% → 74% → ready` без запуска provider job.
- Product readiness на closure: `PWA-CORE-01 14/14`, `PWA-AUDIO-PREPARATION-01 24/24`, Studio PWA `116/116`, project `145/145`; required Goal Evidence `SPEC/CODE/TEST/CI/DEPLOY/LIVE ✅`.
- Approved post-deploy metadata writer отсутствовал (`metadata_sync.enabled=false`); closure reconciled в начале следующей authorized code-bearing Goal без отдельного docs-only PR.

## Archived PR #244 source-cache/branding external-gate checkpoint

Goal `PWA-SOURCE-CACHE-01` была merged и deployed 2026-08-27, но осталась в `PENDING_EXTERNAL_GATE` из-за отсутствующего authenticated owner LIVE.

- Base chain завершён PR `#244`, merge `18cbd46e9361a66bfbc1f2265d0820aa72aedf50`.
- Exact-main repository CI `32959921859`, Studio/browser CI `32959921773` и Studio Platform CD `32959921827` — success; web deployed, API/worker/migration N/A.
- Source-cache remediation и user-visible VoiceOps Studio branding находятся в main.
- Required Goal Evidence на перенос: `SPEC/CODE/TEST/CI/DEPLOY ✅ | LIVE —`.
- Remaining external gate: удалить test source через Settings в authenticated owner session, вернуться в уже смонтированные `Транскрибации` и подтвердить authoritative list, сохранность draft и fail-closed selected source без provider call.
- Approved post-deploy metadata writer отсутствует (`metadata_sync.enabled=false`).
- Explicit user instruction 2026-08-27 «ставь цель и приступай» отдельно авторизовала переход к `PWA-GOOGLE-PICKER-UX-01`; это не превращает отсутствующий source-cache LIVE в success.

## Archived PR #245 Google Picker UX delivery

Goal `PWA-GOOGLE-PICKER-UX-01` была реализована и merged через PR `#245`, после чего остановлена как `PENDING_EXTERNAL_GATE`: code, tests, exact-main CI и web deployment подтверждены, но owner-controlled authenticated LIVE исправления не зафиксировано отдельным Evidence record.

- Base: `main@18cbd46e9361a66bfbc1f2265d0820aa72aedf50`.
- Final implementation commits: `a197e39` и `60c4ec23bdd4afa6dcbff25633cdd96121b4704f`.
- Merge commit: `8761e86808e8562eff05588f6f60d15dd04dbcf4`.
- Exact PR-head repository CI `33103790793` и Studio/browser CI `33103790818`: success.
- Exact-main repository CI `33104113256` и Studio/browser CI `33104113243`: success.
- Studio Platform CD `33104113313`: web deployment success; API/migration/worker корректно не выбирались для frontend-only diff.
- Product AC: `PG-01..PG-03 = 3/3`; Evidence на archive: `SPEC ✅ | CODE ✅ | TEST ✅ | CI ✅ | DEPLOY ✅ | LIVE —`.
- Approved post-deploy metadata writer отсутствовал, поэтому stale pre-push checkpoint был reconciled в начале следующей explicitly authorized Goal.
- Explicit user instruction 2026-08-27 «формируй общую цель под техдолгу, документам и CI, и приступай» авторизовала переход к `REPO-HARDENING-01`; она не превращает отсутствующий Picker LIVE в success.

## Archived PRs #246–#247 repository hardening closure

Goal `REPO-HARDENING-01` завершена 2026-08-27 после bounded documentation, manifest MIME и CI-efficiency hardening.

- Основной PR `#246` merged как `5a4115aed22497c7cb5c6a4d38258dbcf27641bd`; cache-hit Playwright fast-path hotfix PR `#247` merged как `f6b0d70e751673ea4edb11c655a732d594ff8f31`.
- Финальный exact-main repository CI `33116072365` и Studio/browser CI `33116072392` завершились success; browser job занял `89s`, Studio job — `97s`.
- Representative warm PR+main runner pair сократился с baseline `874s` до `629s` (`302s + 327s`), то есть на `28,0%`, без удаления pytest, lint, unit, build, authenticated browser E2E, Compose, image, secret или non-root gates.
- Active cache был `1,81 GiB`, ниже bounded limit `4 GiB`; external actions в active workflows pinned на immutable SHA.
- Studio Platform CD `33114690923` доставил web-only manifest remediation; public `/manifest.webmanifest` вернул `200` и `Content-Type: application/manifest+json`.
- Required Goal Evidence: `SPEC/CODE/TEST/CI/DEPLOY/LIVE ✅`; product AC/denominator не менялись.
- После проверки ancestry обе созданные ветки удалены local/remote; local `main` синхронизирован с `origin/main@f6b0d70`. Approved metadata writer отсутствовал, поэтому closure reconciled в начале `SPEC-RECONCILIATION-01`.

## Archived local SPEC reconciliation

Goal `SPEC-RECONCILIATION-01` завершила read-only reconciliation exact upstream Google Doc revision 2026-08-28.

- Полный inventory: `283` source units = `275` list items + `8` narrative paragraphs.
- Атомизация подготовила `142` non-commercial, `50` cross-contour и `192` commercial AC; все `384` новых IDs уникальны.
- Independent actual-state numerator: `55/142` новых non-commercial AC; commercial/cross-contour `0/242`.
- Публикация отдельного non-canonical audit-report была остановлена safety gate; explicit owner instruction затем отказалась от report и отдельно авторизовала перенос требований в canonical `docs/project-spec.md`.
- Локальные reconciliation commits `7e6139c`, `be30f0a`, `a87b254` не публиковались отдельно; дальнейшее состояние отражает `SPEC-CANONICALIZATION-02`.

## Archived PR #248 canonical requirements closure

Goal `SPEC-CANONICALIZATION-02` завершена 2026-08-28 без публикации отдельного audit-report.

- PR `#248` head `6a817f403ece8b33d6c2a55fa6e164fbfe6099e8` merged как `baa55d695c015385ba992b87c505d1a1fc116df3`.
- Exact-head repository CI `33147462748` и exact-main CI `33147622878` завершились success, включая Alembic validation, lightweight checks и полный pytest.
- Canonical denominator стал `532`: `203/290` non-commercial и `0/242` commercial/cross-contour; full readiness [историческая оценка удалена].
- Separate non-canonical reconciliation report отсутствует в main и PR history. Studio CI/CD корректно не запускались по docs-only path; `DEPLOY/LIVE N/A`.
- Remote/local feature branches удалены; `main` синхронизирован с `origin/main@baa55d6`. Approved metadata writer отсутствовал, поэтому closure reconciled в начале `PWA-SESSION-CONTROL-01`.

## Archived PR #249 session-control closure

Goal `PWA-SESSION-CONTROL-01` завершена 2026-08-28 полным delivery flow.

- PR `#249` head `1267358129295cb66d6a34ae62a43136b8a3b0e4` merged как `3e80fef58f8aab94c5727a7fc7acef300fd8b099`.
- Exact PR-head repository CI `33150834580` и Studio/browser CI `33150834557` завершились success.
- Exact-main repository CI `33151098282` и Studio/browser CI `33151098265` завершились success.
- Studio Platform CD `33151098248` доставил API+web; worker и migration корректно были skipped.
- Authenticated production LIVE подтвердил current + четыре другие active sessions, три targeted revoke audit events и один bulk revoke; после reload сохранилась только current session.
- Canonical `PWASEC-07..09` выполнены; required Goal Evidence `SPEC/CODE/TEST/CI/DEPLOY/LIVE ✅`.
- После ancestry/status checks branch удалена local/remote, local `main` синхронизирован с exact merge SHA. Approved metadata writer отсутствовал, поэтому closure reconciled в начале `PWA-OBSERVABILITY-RUNTIME-01`.

## Archived PR #250 runtime observability closure

Goal `PWA-OBSERVABILITY-RUNTIME-01` завершена 2026-08-28 полным protected delivery flow.

- Base: `main@3e80fef58f8aab94c5727a7fc7acef300fd8b099`; PR `#250` merged как `6cb067d1acea09bc82b70be4c415b6babdce31b2`.
- Exact PR-head и exact-main repository/Studio/browser required CI завершились success; confirmed repository failure на initial head был исправлен одним grouped follow-up batch без speculative rerun.
- Web CD `33156427664`, protected migration/API run `33156906021` и manual worker deploy `33157220511` завершились success; final worker status `33157438236` подтвердил `running/healthy/identity_match=yes`.
- Production schema достигла `0026_runtime_component_status`; protected migration прошла `0025_audio_preparation -> 0026_runtime_component_status` с pre-migration snapshot `a8de340691e3`.
- Authenticated bounded LIVE подтвердил exact одинаковый commit SHA для web/API/worker, release `0.1.0`, exact schema `0026_runtime_component_status`, backend/PostgreSQL/queue/worker/object-storage readiness и safe STT `configured/probe=not_run`; queue была `0 queued / 0 processing`, browser console warnings/errors отсутствовали.
- Canonical `OBSERV-06`, `OBSERV-08`, `OBSERV-09`, `OBSERV-11..OBSERV-14`, `OBSERV-22`, `OBSERV-24..OBSERV-28` выполнены (`13/13`); `OBSERVABILITY-AUDIT-02 25/35`, personal PWA `185/259`, non-commercial `216/290`, full canonical `216/532`.
- Required Goal Evidence: `SPEC/CODE/TEST/CI/DEPLOY/LIVE ✅`. Approved post-deploy metadata writer отсутствовал (`metadata_sync.enabled=false`), поэтому closure reconciled в начале следующей authorized code-bearing Goal без отдельного docs-only PR.

## Archived PRs #251–#252 bounded-query closure

Goal `PWA-QUERY-BOUNDS-01` завершена 2026-08-28 полным delivery flow; web presentation defect, найденный authenticated LIVE, исправлен bounded hotfix в той же Goal.

- Base: `main@6cb067d1acea09bc82b70be4c415b6babdce31b2`; implementation PR `#251` merged как `cc4347758ebae849c963cbf11be253862c6a1402`; web-only hotfix PR `#252` merged как current main `ea92ac671a31cb70dd8f59c78561ee1e5fcf4fbe`.
- Exact PR-head и exact-main repository/Studio/browser required CI завершились success. Implementation PR runs `33166365989`/`33166365983`; post-merge runs `33166563412`/`33166563432`.
- Web deploy `33166563572`, worker drain `33166775059`, protected migration/API `33166862214`, worker deploy `33167793153` и terminal status `33168001735` завершились success; pre-migration snapshot `e73c606741e0`, schema `0027_query_bounds`.
- Authenticated LIVE подтвердил deterministic bounded pagination/cursors, exact bounded analytics shape, cleanup readiness, component identities и safe provider `probe=not_run`; первоначально обнаруженный audit-list presentation cap был устранён PR `#252` и доставлен web-only.
- Required Goal Evidence: `SPEC/CODE/TEST/CI/DEPLOY/LIVE ✅`. Goal была infrastructure/performance remediation и не меняла canonical product AC numerator/denominator: closure snapshot оставался `216/532`.
- Approved post-deploy metadata writer отсутствовал (`metadata_sync.enabled=false`), поэтому closure reconciled в начале следующей authorized code-bearing Goal. Local `main` был clean и синхронизирован с `origin/main@ea92ac67`; merged branches удалены после ancestry checks.

## Archived PRs #253–#254 transcription UX closure

Goal `PWA-TRANSCRIPTION-UX-POLISH-01` завершена 2026-08-28 полным web delivery flow без provider call.

- PR `#253` реализовал app-owned source-file/source-folder/output-folder dialogs, bounded search/pagination/current-folder behavior и явные diarization states; PR `#254` исправил обнаруженную LIVE-проверкой canonical Drive query для shared folders.
- Final repository/web revision: `main@535a015dcef211a930faefe443245ee85ace38b8`; production API/worker остались на совместимом `cc4347758ebae849c963cbf11be253862c6a1402`, schema — `0027_query_bounds`.
- Exact-main runs: repository CI `33194034264`, Studio PWA CI `33194034189`, Studio Platform CD `33194034216`; required checks и web deployment завершились success.
- Authenticated LIVE подтвердил три picker modes, folder/file search, current empty folder, shared folders/drives, modal scroll lock/release, source multi-selection `2 → 1 → 2` и обе diarization states. Transcription job/provider call не запускались.
- Canonical closure: `PG 8/8`, `PB 11/11`; readiness [историческая оценка удалена], personal PWA [историческая оценка удалена], non-commercial [историческая оценка удалена]; required Evidence `SPEC/CODE/TEST/CI/DEPLOY/LIVE ✅`.
- После safe ancestry/status checks созданные ветки удалены local/remote, local `main` синхронизирован с exact merge SHA. Approved post-deploy metadata writer отсутствовал (`metadata_sync.enabled=false`), поэтому closure reconciled в начале следующей authorized code-bearing Goal.

## Archived PR #255 direct Drive upload closure

Goal `PWA-AUDIO-DIRECT-DRIVE-UPLOAD-01` завершена 2026-08-28 полным API+web delivery flow без provider call.

- Base: `main@535a015dcef211a930faefe443245ee85ace38b8`; PR `#255` merged squash commit `26fb497496ed2a418a12afc6b3cf081e45075e57`.
- Exact PR-head repository CI `33204929949` и Studio PWA CI `33204929954` завершились success после одного grouped follow-up fix stale E2E selector; browser job `98963445432` выполнил `12` authenticated scenarios.
- Exact-main repository CI `33205123663`, Studio PWA CI `33205123676` и Studio Platform CD `33205123712` завершились success; web и API deployed, worker и migration корректно skipped.
- Authenticated production LIVE подтвердил sidebar/hero `Подготовка аудио`, четыре accessible source tabs, app-owned target-folder picker, cancel обоих файлов, explicit safe retry, aggregate `7.74 MB / 7.74 MB`, `100%`, `2/2` verified Drive results и safe links без transcription/provider action.
- Canonical `AP-01` и `AP-25..30` выполнены; `PWA-AUDIO-PREPARATION-01 30/30`, closure readiness `228/552`, non-commercial `228/310`, personal PWA `197/278`; required Evidence `SPEC/CODE/TEST/CI/DEPLOY/LIVE ✅`.
- Feature branch удалена local/remote после проверки identical tree с `origin/main`; local `main` синхронизирован с exact merge SHA. Approved metadata writer отсутствовал (`metadata_sync.enabled=false`), поэтому closure reconciled в начале `TRANSCRIPT-DOC-STANDARD-01`.

## Archived PR #256 transcript document standard closure

Goal `TRANSCRIPT-DOC-STANDARD-01` завершена 2026-08-28 полным delivery flow.

- Base: `main@26fb497496ed2a418a12afc6b3cf081e45075e57`; PR `#256` merged как `main@c065b629db9875ddd92bf30ce67d8290c018f067`.
- Exact PR-head repository CI `33209885606` и Studio/browser CI `33209885618` завершились success; exact-main repository CI `33210100820` и Studio/browser CI `33210100733` также success.
- Studio Platform CD `33210100650` и reviewed follow-up delivery `33210659993` завершились success; production schema осталась `0027_query_bounds`.
- Canonical `CB-24` и `PD-07..13` реализовали versionless `transcript_doc`, русские structural labels, `Heading 2`, body `11 pt`, speaker labels bold `14 pt` и existing explicit standardization без provider call.
- Closure readiness: `236/552`, non-commercial `236/310`, personal PWA `204/278`; document-format AC `8/8`. Последующий owner report о generic maintenance failure относится к synchronous operation execution/UX и стал отдельным scope `TRANSCRIPT-MAINTENANCE-WORKSPACE-01`, а не откатом document-format contract.
- Approved post-deploy metadata writer отсутствовал (`metadata_sync.enabled=false`), поэтому closure reconciled в начале следующей authorized code-bearing Goal без отдельного docs-only PR.

## Archived PR #257 transcript maintenance workspace delivery

Goal `TRANSCRIPT-MAINTENANCE-WORKSPACE-01` доставила durable maintenance workspace и завершилась как `PENDING_EXTERNAL_GATE`: основной runtime contour развёрнут, но owner LIVE выявил два corrective gaps до representative apply.

- Base: `main@c065b629db9875ddd92bf30ce67d8290c018f067`; PR `#257` head `f95a1c87d853dfff93f3386c61b951b18d34507e` merged как `main@52c2adb4621f23fda34dece8a9096b36ae92504a`.
- Exact PR-head CI: repository `33222109767`, Studio/browser `33222109701`; exact-main CI: repository `33222285752`, Studio/browser `33222285698`; required jobs завершились success.
- Web CD `33222285701`, protected migration/API release `33222544738`, worker deploy `33222813698` и terminal worker status `33222993815` завершились success; schema достигла `0028_transcript_maintenance_runs`.
- Authenticated production dry-run подтвердил app-owned workspace, durable queued/running execution и folder traversal `142/142`, но progress обновлялся только после remount/tab switch, а `141` legacy Google Docs были ошибочно blocked из-за отсутствия исходного media file. Apply не выполнялся.
- Product `PTM-01..08` остался выполненным; Goal Evidence на archive: `SPEC ✅ | CODE ✅ | TEST ✅ | CI ✅ | DEPLOY ✅ | LIVE ◐`. Corrective behavior и новое owner-решение о legacy `Created at` вынесены в explicitly authorized Goal `TRANSCRIPT-MAINTENANCE-LEGACY-DATE-LIVE-01`.

## Archived PR #258 legacy-date/live-progress closure

Goal `TRANSCRIPT-MAINTENANCE-LEGACY-DATE-LIVE-01` завершена 2026-08-29 полным protected delivery flow и explicit owner apply.

- Base: `main@52c2adb4621f23fda34dece8a9096b36ae92504a`; final PR head `6ad41ee81c603f834b2c7e4c3275d8467e9e794b`; PR `#258` merged как `main@a31770eabcd7a97acfa084252de06f26d041bc1b`.
- Exact PR-head checks: repository `33242402182` и Studio/browser `33242402183` — success. Exact-main repository CI `33242536922` и Studio/browser CI `33242536918` — success.
- Platform CD `33242536907` и reviewed follow-up `33242827363`, worker status/drain/status `33242755832`/`33242786300`/`33242964630` завершились success на exact merge revision.
- Authenticated recursive preview проверил `142` Google Docs: `141` eligible, `1` current, `0` blocked. После explicit owner confirmation apply стандартизировал `141/141`, сохранил существующие валидные `Created at`, пропустил отсутствующие/невалидные даты, не сообщил ошибок и не запускал provider call.
- Открытый workspace автоматически обновлял queued/running progress до terminal state без remount/tab switch. `PWA-STANDARDIZATION-01 14/14` и `PWA-TRANSCRIPT-MAINTENANCE-01 9/9` получили required `SPEC/CODE/TEST/CI/DEPLOY/LIVE ✅`.
- Approved post-deploy metadata writer отсутствовал (`metadata_sync.enabled=false`), поэтому factual closure reconciled в начале следующей authorized code-bearing Goal.

## Archived PRs #259–#260 UX/storage isolation closure

Goal `PWA-USER-UX-STORAGE-ISOLATION-01` завершена 2026-08-30 полным protected delivery flow; image-permission defect, найденный pre-migration gate до state mutation, исправлен bounded hotfix в той же Goal.

- Base: `main@a31770eabcd7a97acfa084252de06f26d041bc1b`; PR `#259` merged как `c11de8af22d694540b26d98c2ec40aab064adf25`; hotfix PR `#260` merged как `c443de6855b02c3d0e5e0021ca76d56b52a2a9bc`.
- Exact-main repository/Studio CI завершились success. Финальные delivery runs: protected migration/API `33302350705`, web `33302771083`, worker `33302841078`, terminal worker status `33302990622` — success на exact final revision.
- Production schema достигла `0029_source_reference_class`; web/API/worker получили exact `c443de6855b02c3d0e5e0021ca76d56b52a2a9bc` identity.
- Authenticated bounded LIVE подтвердил user-facing UX, mobile Drive-dialog boundary и distinct transcription/audio reference storage; provider lifecycle rules, independently scoped credentials и cross-bucket denial подтверждены без раскрытия bucket names или secret values.
- Canonical closure: `PWA-USER-EXPERIENCE-02 12/12`, `STORAGE-LIFECYCLE-02 12/21`; readiness `264/574`, non-commercial `264/332`, personal PWA `232/300`; required Goal Evidence `SPEC/CODE/TEST/CI/DEPLOY/LIVE ✅`.
- Release variables возвращены в safe baseline: platform CD enabled, migration/edge releases disabled. Created branches/worktree удалены после ancestry checks; local `main` синхронизирован.
- Approved post-deploy metadata writer отсутствовал (`metadata_sync.enabled=false`), поэтому factual closure reconciled в начале `PWA-WORKER-USAGE-ACCOUNTING-01` без отдельного docs-only PR.

## Current non-authority warning

If this archive conflicts with `docs/project-spec.md`, `docs/delivery-plan.md`, `docs/architecture.md`, `docs/ci-cd-rules.md`, or the current user task, treat the current documents/task as authoritative and this archive as historical context only.


## Перенос завершённых Goals и устаревших checkpoints при AUDIT 2026-09-05

Это historical claims на указанные revisions, не текущая приёмка. Старые pre-merge состояния сохранены только как история. История процентных оценок при переносе исключена.

## Previous Goal closure — `SEGMENT-FOLDER-FAVORITES-HOTFIX-01`

- **State:** `DONE` — PR `#300` merged as `dce709df90d4495f7775be93d631ee9a0d3e6f6d`; exact CI, web delivery and bounded LIVE verified in previous owner-facing final report.
- **Evidence:** `SPEC ✅ | CODE ✅ | TEST ✅ | CI ✅ | DEPLOY ✅ | LIVE ✅`; no provider/Google mutation.

## Previous Goal contract — `SEGMENT-FOLDER-FAVORITES-HOTFIX-01` (pre-merge snapshot)

- **ID / title:** `SEGMENT-FOLDER-FAVORITES-HOTFIX-01` — избранные папки в destination controls каждого фрагмента.
- **State:** `IN_PROGRESS` — shared favorites UI и segment-scoped selection реализованы; frontend validation passed; PR/CI и web delivery pending.
- **Authorization source:** explicit owner browser annotation 2026-09-05: «нет выбора избранных папок как вначале при выборе папки фрагмента»; narrow implementation продолжает существующие `PI-02` и `UXCTL-04/05` без нового product AC.
- **Scope:** переиспользовать основной collapsible favorites list у каждого фрагмента; revalidate selected folder на existing API; применять override только к выбранному segment; сохранять default-folder inheritance, empty/loading/error states и текущие favorites actions; выполнить frontend checks, PR/CI, web delivery и bounded non-mutating LIVE.
- **Non-goals:** backend/schema/worker changes; новые permissions или OAuth scopes; изменение списка избранного/Google Drive в production; запуск транскрибации; commercial contour; расширение product denominator.
- **Goal AC:**
  1. `SFF-01`: каждый включённый fragment имеет «Избранные папки» из того же owner-scoped списка, что и основная папка.
  2. `SFF-02`: выбор требует successful server verification, меняет только нужный fragment, корректно попадает в preflight и допускает возврат к общей папке; failed verification сохраняет прежний destination.
  3. `SFF-03`: shared UI сохраняет loading/empty/error/retry behavior; focused regression, frontend checks, exact CI, web delivery и read-only LIVE подтверждены.
- **Required Evidence:** `SPEC ✅ | CODE ✅ | TEST ✅ | CI — | DEPLOY — | LIVE —`.
- **Known blockers/dependencies:** none; previous pnpm files были удалены по explicit owner instruction, inaccessible pre-existing pytest directories не затрагиваются.
- **Stop condition:** все 3 Goal AC и required Evidence выполнены либо возник external gate; следующий scope не выбирается автоматически.

## Previous execution checkpoint — `SEGMENT-FOLDER-FAVORITES-HOTFIX-01`

- **Updated (UTC):** `2026-09-05T05:42:59Z`.
- **Base branch/SHA:** synced `origin/main@e00febc5f77ebb9bcc8cd797a09ee7c1a94354b7`.
- **Working branch:** `codex/segment-folder-favorites`.
- **Working tree at Goal start:** tracked and visible untracked state clean; pre-existing inaccessible pytest directories preserved.
- **Last verified revision:** implementation commit `921deece027cad2b608667bf2fbd798a9c7c9fa4`, covered by local frontend validation; final checkpoint-only commit не меняет runtime source.
- **Completed:** shared favorites renderer подключён к row и segment folder controls; optional segment identity направляет verified result только в соответствующий segment; regression проверяет empty default, sibling isolation, inheritance reset, rejected verification и preflight destinations.
- **Current step:** PR `#300`, required CI in progress; no review findings as of this checkpoint.
- **Next exact action:** после required checks final PR head выполнить merge и проверить web delivery/LIVE.
- **Validation / Evidence:** focused App suite `3 passed, 225 intentionally filtered`; full frontend `706 passed`; ESLint, TypeScript, Vite/PWA build и diff check passed. Initial sandbox denied esbuild spawn, approved rerun passed. No provider/Google production mutation.
- **PR / CI / deployment:** PR `#300` targets `main`; initial checks `33947907470`, Studio/browser `33947907445` in progress on implementation head. Current Goal delivery/LIVE pending; API/worker/migration N/A.
- **Blockers / unverified assumptions:** none for implementation; LIVE verification ограничивается UI/build identity без folder selection или provider dispatch.

## Previous Goal closure — `AUDIO-OUTPUT-FILENAME-HOTFIX-01`

- **State:** `DONE` — PR `#299` merged as `e00febc5f77ebb9bcc8cd797a09ee7c1a94354b7`; CI, applicable delivery and bounded LIVE verified in the owner-facing final report of the previous Goal.
- **Evidence:** `SPEC ✅ | CODE ✅ | TEST ✅ | CI ✅ | DEPLOY ✅ | LIVE ✅`. Optional result name/source-name fallback confirmed; no new media/provider/Drive action was used for LIVE verification.
- **Metadata reconciliation:** post-deploy facts recorded in the final report are incorporated in this next code-bearing scope; no metadata-only follow-up PR or direct push was used.

## Previous Goal contract — `AUDIO-OUTPUT-FILENAME-HOTFIX-01` (pre-merge snapshot)

- **ID / title:** `AUDIO-OUTPUT-FILENAME-HOTFIX-01` — пользовательское имя результата с fallback на имя исходного файла.
- **State:** `IN_PROGRESS` — production defect `source.flac` локализован; implementation, local validation, reviewable PR и exact implementation-head CI завершены; merge/delivery/LIVE ещё не выполнены.
- **Authorization source:** explicit owner instruction 2026-09-04: «нужно поле для задания имени. Если имя не задано, то переносится имя исходного файла»; owner отдельно подтвердил, что `source.flac` был фактическим именем output до ручного переименования.
- **Scope:** сделать `Название результата` необязательным; при пустом поле использовать stem исходного filename; для separate mode применять имя соответствующего source, для concat — первого файла в подтверждённом порядке; сохранять введённое Unicode/кириллическое имя в Studio Source, Google Drive и browser download; оставить internal object key безопасным и отдельным от user-visible filename; согласовать local/server paths; покрыть regressions, reviewable PR, exact CI, web/API/worker delivery и bounded non-mutating LIVE.
- **Non-goals:** переименование существующих output/Google Drive files; paid STT; обработка или загрузка нового production media ради проверки; изменение audio processing parameters, storage/retention, schema, commercial contour или Google Docs.
- **Goal AC:**
  1. `AOF-01`: UI показывает необязательное поле имени; пустое значение не блокирует запуск и детерминированно использует исходный stem для single/separate/concat plans.
  2. `AOF-02`: явное пользовательское имя имеет приоритет, а multi-output custom plan сохраняет уникальную связь с source без одинаковых имён.
  3. `AOF-03`: кириллица/Unicode сохраняются в persisted output filename, Drive upload и RFC 5987 download metadata; internal storage key остаётся bounded ASCII-safe и не подменяет видимое имя.
  4. `AOF-04`: local и server paths покрыты focused regressions; reviewable PR, exact-head/main CI, applicable web/API/worker delivery и bounded read-only LIVE подтверждают exact revision без provider/Google mutation.
- **Required Evidence:** `SPEC ✅ | CODE ✅ | TEST ✅ | CI ✅ | DEPLOY — | LIVE —`.
- **Known blockers/dependencies:** production end-to-end creation нового файла намеренно не входит в bounded LIVE без отдельного action-time решения; unrelated `apps/studio/pnpm-lock.yaml`, `apps/studio/pnpm-workspace.yaml` и inaccessible temporary pytest directories сохраняются untouched.
- **Stop condition:** все 4 Goal AC и required Evidence выполнены либо Goal достигает `BLOCKED` / `PENDING_EXTERNAL_GATE`; к следующей Goal без новой explicit owner authorization не переходить.

## Previous execution checkpoint — audio filename hotfix (pre-merge snapshot)

- **Updated (UTC):** `2026-09-04T19:02:10Z`.
- **Base branch/SHA:** exact synced `origin/main@924c05385522570066325aab0287f0e5ac7b475a`.
- **Working branch:** `codex/audio-output-filename-hotfix` from exact `origin/main`.
- **Working tree at Goal start:** tracked files clean; unrelated untracked `apps/studio/pnpm-lock.yaml`, `apps/studio/pnpm-workspace.yaml` and inaccessible temporary pytest directories pre-existed and remain untouched.
- **Last verified revision:** exact implementation head `a85bcb986d3728d02590e40736a2a9ceeef0f445` покрыта local checks и required PR CI; содержащий этот factual checkpoint docs-only commit runtime scope не расширяет.
- **Completed:** exact defect path подтверждён: default Cyrillic title проходил через ASCII-only sanitization и становился fallback `source`; UI одновременно не наследовал source name. Поле стало optional, fallback разрешается до dispatch для single/separate/concat, local WAV использует то же правило, server output сохраняет Unicode filename, а presigned download передаёт Unicode через RFC 5987 с безопасным ASCII fallback. Предыдущая Goal `BULK-CLEANUP-VISIBILITY-HOTFIX-01` reconciled по PR `#298`, exact-main CI/CD и authenticated preview-only LIVE: `0` текущих и `7` скрытых истёкших записей показаны раздельно, destructive apply не выполнялся.
- **Current step:** синхронизировать factual pre-merge checkpoint; после final docs-only exact-head gates выполнить merge.
- **Next exact action:** push checkpoint commit, дождаться required checks и merge PR `#299`.
- **Validation / Evidence:** full Studio Vitest `705 passed`; full ESLint и TypeScript/Vite/PWA production build passed; focused Python filename/processor/download suite `32 passed`; portable Python `1363 passed, 5 skipped, 9 host-only shell cases deselected`; lightweight repository checks, Python compileall и `git diff --check` passed. Отдельный unfiltered portable run дал те же `1363 passed, 5 skipped` и `9 failed` только в двух unchanged shell modules: Windows выбрал WSL `bash.exe`, который не может открыть workspace path с кириллицей; Linux exact CI остаётся acceptance gate этих cases.
- **PR / CI / deployment:** PR `#299` MERGEABLE/CLEAN, без comments/reviews. Exact implementation-head CI `33908723893` и Studio/browser CI `33908724010` success; initial browser E2E на `60b64bd` корректно выявил устаревшее ожидание `Обработанное аудио.wav`, после замены на source-derived `browser-local.wav` final head прошёл. Production web/API/worker остаются на `main@924c05385522570066325aab0287f0e5ac7b475a`, schema `0037_ux_audit_controls`.
- **Blockers / unverified assumptions:** implementation blocker не выявлен; production создание нового media output не авторизовано как LIVE fixture и заменяется read-only UI/runtime identity verification плюс exact tests.

## Previous Goal closure — `BULK-CLEANUP-VISIBILITY-HOTFIX-01`

- **State:** `DONE` — PR `#298` merged как `main@924c05385522570066325aab0287f0e5ac7b475a`; exact-main repository CI `33896145219`, Studio/browser CI `33896144865` и Platform CD `33896144420` завершились success.
- **Evidence:** `SPEC N/A | CODE ✅ | TEST ✅ | CI ✅ | DEPLOY ✅ | LIVE ✅`. Web/API deployment подтверждён exact merge identity; worker/migration не затрагивались. Authenticated production preview 2026-09-04 показал «Сейчас в списке файлов: 0» и «Истёкших записей…: 7»; confirmation не нажималась, данные и Google Drive не изменялись.
- **Result:** cleanup preview больше не выдаёт скрытые retention records за видимые файлы; eligibility, blocked reasons, replay-safe token и destructive confirmation boundary сохранены.

## Previous Goal closure — `UX-AUDIT-CONTROLS-01`

- **ID / title:** `UX-AUDIT-CONTROLS-01` — понятные режимы, destinations, recovery, billing, storage cleanup и diagnostics.
- **State:** `DONE` — PR `#297` merged; exact-main CI, protected migration/API/web/worker delivery и bounded read-only LIVE выполнены на `main@83d461ee20cdb0b1275213f9b99397b292c9167d`.
- **Authorization source:** explicit owner instruction 2026-09-04: «сначала обнови документ требований… Затем формируй goal по результатам UX аудита и приступай к правкам».
- **Scope:** реализовать новый canonical `UXCTL-01..14`: показывать только реально различающиеся STT modes и объяснять отличия; включать fragmentation явным checkbox, наследовать общую Drive folder и разрешать per-fragment override с resolved preflight; дать collapsible и explicit resolution flow для provider-uncertain jobs; отделить base plan от PAYG/prepaid balance; добавить preview/confirmation/report для bulk удаления только Studio-owned files; сделать diagnostic events compact, severity-first и human-readable без потери blocker/source context; покрыть API/PWA/data contracts, tests, reviewable PR, exact CI и applicable delivery/LIVE.
- **Non-goals:** commercial contour; изменение provider tariffs или billing calculations; автоматический cross-provider fallback; удаление Google Drive sources/documents; destructive cleanup без отдельного owner action; paid STT/provider canary; изменение Colab; новая design system или полный visual redesign.
- **Goal AC:**
  1. `UXA-01`: canonical product contract содержит ровно `UXCTL-01..14`; operational status меняется только по фактическому Evidence.
  2. `UXA-02`: mode selector не создаёт ложных различий — эквивалентные capabilities объединены, реальные различия объяснены до dispatch.
  3. `UXA-03`: fragmentation имеет explicit off/on state; default output folder наследуется всеми fragments, per-fragment override и resolved destination видимы до подтверждения.
  4. `UXA-04`: attention-required terminal job можно свернуть; recheck/link/acknowledge resolution fail closed, предупреждает об uncertain spend и только после explicit resolution допускает обычный history lifecycle с audit trail.
  5. `UXA-05`: ElevenLabs account UI отдельно и понятным русским языком показывает base subscription и PAYG/prepaid balance, не выдавая raw provider tier за пользовательский тариф.
  6. `UXA-06`: bulk cleanup preview показывает eligible/blocked count и bytes; apply требует явного подтверждения, не затрагивает Google Drive, удаляет только eligible Studio-owned files и возвращает per-reason summary.
  7. `UXA-07`: diagnostic rows сначала показывают human summary/action, сохраняют blocker/source context, а technical codes/IDs/metadata раскрывают отдельно; весь log можно свернуть, ошибки/предупреждения приоритетны и список bounded.
  8. `UXA-08`: новые owner-scoped mutation boundaries имеют CSRF/recent-confirmation/audit, fail-closed replay и concurrency-safe behavior; additive migration используется только для durable resolution state.
  9. `UXA-09`: focused backend/frontend/integration/browser regressions покрывают positive, negative, ownership, concurrency и narrow viewport states.
  10. `UXA-10`: reviewable PR и exact-head CI success; applicable web/API/worker/migration delivery подтверждает exact identities, а bounded LIVE не выполняет paid STT, Google mutation или destructive bulk cleanup без отдельной action-time authorization.
- **Required Evidence:** `SPEC ✅ | CODE ✅ | TEST ✅ | CI ✅ | DEPLOY ✅ | LIVE ✅`.
- **Known blockers/dependencies:** production destructive cleanup, provider call и Google mutation остаются action-time gates и не требуются для safe UI/read-only LIVE; unrelated `apps/studio/pnpm-lock.yaml`, `apps/studio/pnpm-workspace.yaml` и inaccessible temporary pytest directories сохраняются untouched.
- **Stop condition:** все 10 Goal AC и required Evidence выполнены либо Goal достигает `BLOCKED` / `PENDING_EXTERNAL_GATE`; к следующей Goal без новой explicit owner authorization не переходить.

## Previous execution checkpoint — `UX-AUDIT-CONTROLS-01`

- **Updated (UTC):** `2026-09-04T10:00:13Z`.
- **Base branch/SHA:** exact synced `origin/main@b9e83131120ef075ea6bcbf6fd64e3d6e594b966`.
- **Working branch:** `codex/ux-audit-controls` from exact `origin/main`.
- **Working tree at Goal start:** tracked files clean; unrelated untracked `apps/studio/pnpm-lock.yaml`, `apps/studio/pnpm-workspace.yaml` and inaccessible temporary pytest directories pre-existed and remain untouched.
- **Last verified revision:** exact-head implementation revision `c47ce2bf8044744abab37c9c0ee0594346c383d0`.
- **Completed:** Google Doc `Требования к проекту VoiceOps Studio` revision `ANLCKQlhXCiyRDsxLHF_o-wX4fktyA1eq2i7ZHalVZEdAsqB54Zv2QLevIMKSJb-6sd2T69WzDwMMEfmplaJ7Kc7ZzuijNaU0L1YNZliGBg` получил шесть material requirements в существующих sections без structural change; final readback подтвердил по одному list item. Canonical `UXCTL-01..14`, additive schema `0037`, owner-scoped bulk Studio-file deletion preview/apply, explicit uncertain-job resolution, truthful STT mode grouping, explicit fragmentation/default and per-fragment Drive destinations, readable ElevenLabs plan/PAYG labels and compact actionable diagnostics реализованы вместе с API/PWA/schema regressions и operational docs.
- **Current step:** Goal закрыта; destructive bulk cleanup, paid STT и Google mutation не выполнялись.
- **Next exact action:** none; следующий scope требует новой explicit owner authorization.
- **Validation / Evidence:** Google Docs final connector readback; Python compileall и lightweight CI checks passed; focused schema/source/deletion/DTO/account suite `113 passed`; diagnostics/report suite `22 passed, 1 deselected`; full frontend Vitest `703 passed`; ESLint, TypeScript/Vite/PWA production build, focused `JobCard` `5 passed`, Playwright discovery и `git diff --check` passed. Локальный PostgreSQL отсутствует, поэтому новый PostgreSQL-backed active-job regression подтверждён в exact-head CI. Initial CI последовательно выявил invalid enum только в новой fixture, затем устаревшие E2E assumptions о раскрытой attention-card и реальный product defect: processing job с uncertain attempt ошибочно получал `history_attention_required`; fixes нормализовали fixture/selectors и ограничили attention predicate terminal statuses, после чего все exact-head suites прошли.
- **PR / CI / deployment:** PR `#297`, exact-head `9a9daa40cdfc00c46992ce89307a8102bd8151d5`, merge `83d461ee20cdb0b1275213f9b99397b292c9167d`; exact-main CI `33862095356` и Studio/browser `33862095375` success. Web CD `33862095305`; protected migration/API `33863624454` применила `0036 -> 0037_ux_audit_controls` со snapshot `52d07afd08e0`; worker deploy/status `33864051036` / `33864415973` success с exact identity и `health=healthy`.
- **Blockers / unverified assumptions:** none для Goal DoD. Bounded authenticated LIVE подтвердил truthful mode copy, explicit fragmentation checkbox, collapsible old errors, separated subscription/PAYG labels, bulk cleanup boundary и collapsed diagnostics; public `/api/readyz` подтвердил schema `0037`, PostgreSQL и Redis. Provider call, Google mutation и destructive bulk cleanup не выполнялись.

## Previous Goal closure — `JOB-RELIABILITY-NOTIFICATIONS-01`

- **ID / title:** `JOB-RELIABILITY-NOTIFICATIONS-01` — безопасные автоматические retry и гарантированные terminal-уведомления.
- **State:** `DONE` — PR `#294` merged; exact-main CI, protected migration/API/web/worker delivery и bounded no-send LIVE выполнены на `main@0fb499d9b7b65470292df0c2a7f90d0602417b83`.
- **Authorization source:** explicit owner instruction 2026-09-03 после non-commercial gap review: «Бери пару эпиков на реализацию без коммерческого контура»; выбрана связанная пара canonical `JOB-RELIABILITY-02` + `JOB-NOTIFICATIONS-01`.
- **Scope:** закрыть `JOBREL-05`, `JOBREL-09`, `JOBREL-10` и `JOBNOT-01`–`JOBNOT-06`: автоматически повторять только доказуемо safe transient failures с bounded attempts/backoff и без повторного provider/Google/storage side effect; создать owner-scoped durable terminal-notification outbox, атомарно и idempotently связанный с terminal job transition; реализовать opt-in Web Push, email и optional Telegram для success/error; обеспечить claim lease, bounded transport timeout/retry, stale-claim recovery, deduplication, безопасную redaction, понятные настройки/readiness/status в PWA; покрыть additive migration, API/worker/frontend contracts, tests, reviewable PR, exact CI, protected delivery и bounded LIVE без paid STT или несанкционированного внешнего сообщения.
- **Non-goals:** commercial contour; новый STT provider; повтор provider call при timeout/unknown/partial/returned-result uncertainty; автоматический Google Docs retry/reconciliation; SMS/mobile app; marketing notifications; обязательный Telegram/email/Web Push; хранение SMTP/Telegram/VAPID secrets в PostgreSQL или браузере; чтение transcript/source/document content для notification; destructive data cleanup; отправка реального внешнего уведомления без отдельной action-time owner authorization.
- **Goal AC:**
  1. `JRN-01`: canonical `JOBREL-05/09/10` и `JOBNOT-01..06` остаются единственным product denominator; operational status/Evidence меняются только после фактических gates.
  2. `JRN-02`: automatic retry допускается только для allowlisted transient failure с durable proof отсутствия ambiguous external side effect; attempts и exponential backoff bounded, cancel/limit/non-transient/unknown/provider-result/Google uncertainty fail closed.
  3. `JRN-03`: terminal job success/failure атомарно материализует owner-scoped notification intents; unique keys и state machine не допускают duplicate Web Push/email/Telegram при retry, recovery, repeated terminal observation или concurrent workers.
  4. `JRN-04`: Web Push имеет explicit browser opt-in/subscription lifecycle, VAPID-backed server delivery и service-worker handling для success/error без sensitive payload.
  5. `JRN-05`: email имеет explicit owner opt-in, использует account email и TLS-capable secret-file-backed SMTP configuration; success/error delivery bounded и честно unavailable без configuration.
  6. `JRN-06`: Telegram является optional opt-in channel с отдельным secret-file-backed bot/destination contract; success/error payload allowlisted и не смешивается с operational alerts.
  7. `JRN-07`: delivery claim не удерживает DB transaction во время network I/O; stale claims восстанавливаются, retry count/backoff bounded, provider response bodies/URLs/secrets не сохраняются и не логируются.
  8. `JRN-08`: PWA показывает понятные channel readiness/preferences и последний bounded delivery outcome; unsupported/denied/unconfigured состояния не выдаются за success.
  9. `JRN-09`: migration, DB grants, retry classifier, transactional outbox, concurrency/dedup, all transports, redaction, API ownership/CSRF и service-worker/frontend flows покрыты focused/integration tests.
  10. `JRN-10`: reviewable PR и exact-head CI success; protected migration/API/web/worker delivery подтверждает exact identity, а bounded LIVE не делает paid STT и не отправляет внешнее сообщение без отдельного подтверждения владельца.
- **Required Evidence:** `SPEC ✅ | CODE ✅ | TEST ✅ | CI ✅ | DEPLOY ✅ | LIVE ✅`.
- **Known blockers/dependencies:** отсутствуют для Goal DoD. External Web Push/email/Telegram фактически не отправлялись: channels остаются disabled/unconfigured и требуют отдельной action-time authorization. Unrelated files/directories сохранены untouched.
- **Stop condition:** все Goal AC и required Evidence выполнены либо Goal достигает `BLOCKED` / `PENDING_EXTERNAL_GATE`; к следующей Goal без новой explicit owner authorization не переходить.

## Previous execution checkpoint — `JOB-RELIABILITY-NOTIFICATIONS-01`

- **Updated (UTC):** `2026-09-03T17:40:00Z`.
- **Base branch/SHA:** merged and deployed `main@0fb499d9b7b65470292df0c2a7f90d0602417b83`.
- **Working branch:** merged `codex/job-reliability-notifications`.
- **Working tree at Goal start:** tracked files clean; unrelated untracked `apps/studio/pnpm-lock.yaml`, `apps/studio/pnpm-workspace.yaml` and inaccessible temporary pytest directories pre-existed and remain untouched.
- **Last verified revision:** `b3b77c790212cdc7e5563ef595c133a737629eb8`.
- **Completed:** additive `0035_job_notifications` schema/models/grants; allowlisted automatic retry with server-enforced schedule; owner-scoped terminal outbox and Web Push/email/Telegram transports; encrypted browser subscription lifecycle; Settings UI/service-worker handler; deployment configuration, architecture/runbook and migration-head contracts implemented in `1fb819fd56f4b65990061679c8004a3db14df81a`. Initial PR CI exposed fresh-database `Base.metadata.create_all` compatibility in migration `0035`; bootstrap-safe full-boundary detection and a regression test were added in `b3b77c790212cdc7e5563ef595c133a737629eb8`. Production transports remain disabled by default.
- **Current step:** Goal closed; optional notification channels remain owner-controlled and disabled/unconfigured.
- **Next exact action:** none; next Goal required new authorization and is recorded above.
- **Validation / Evidence:** Python compile and `git diff --check` pass; lightweight repository CI checks pass; changed backend/schema suite `220 passed`; processing regression suite `140 passed`; final notification/worker/dependency suite `25 passed`; migration notification suite after fix `12 passed`; frontend ESLint passed, full Vitest `687 passed`, production TypeScript/Vite/PWA build passed. Initial PR head `55e9128de835fe0c61fd86cae566deb77da105a2` failed core CI and browser E2E at the same `DuplicateColumn` migration bootstrap defect. Repeat head `ea3dd35328388209428c1cc92f8931990eebee4b` passed browser E2E and Studio image/Compose CI; core CI reached `1678 passed` with one failure in the newly added API test because its safe same-origin GET omitted the required test `Origin`, while production behavior correctly returned `403`. The test request now matches the existing same-origin contract. PostgreSQL/Redis rerun remains required because those local services are unavailable; unrelated Windows Bash path failures are environmental and not counted as product failures.
- **PR / CI / deployment:** PR `#294` merged; exact-main CI `33761495438` / `33761495442`; web CD `33761495444`; protected migration/API `33781247133` with schema `0035_job_notifications` and backup snapshot `f216e86ca866`; worker deploy/status `33781774924` / `33782320682`.
- **Blockers / unverified assumptions:** none for closed Goal; external delivery remains intentionally untested and is not inferred from source.

## Previous Goal closure — `PERSONAL-SECURITY-UX-01`

- **ID / title:** `PERSONAL-SECURITY-UX-01` — least-privilege PostgreSQL, полный personal security lifecycle и понятный owner UX.
- **State:** `DONE` — все 14 Goal AC и required Evidence закрыты на exact functional merge `e5c43feac06e1649f1bd0903953ef5de7f925b87`; protected recovery завершил already-applied schema без второго Alembic run, API/web/worker доставлены, а bounded authenticated LIVE подтверждён без paid STT или destructive actions.
- **Authorization source:** explicit owner instructions 2026-09-02: «В целом ок, тогда я бы взял эти два эпика как Goal. Плюс UX/UI правки, которые я сейчас дам в аннотациях» и последующие восемь browser comments.
- **Scope:** отделить PostgreSQL bootstrap/owner, protected migrator, API и worker roles/secrets с fail-closed grant verification и совместимым rollout/rollback; закрыть `PWASEC-06`, `PWASEC-10`, `PWASEC-12`–`PWASEC-18`: configurable total transcription duration policy с обычной обработкой до 4 часов, явным предупреждением до 12 часов и hard stop выше 12 часов, recent re-authentication для critical actions, bounded password-reset/TOTP verification, optional RFC 6238 TOTP enrollment, recovery и disable lifecycle; сделать owner dashboard содержательным; переименовать «Готовые документы» в «Подготовка документов»; дать пользователю свернуть/сбросить завершённый план стандартизации; свернуть подробное system state и diagnostic events; оставить в UI diagnostic bundle JSON для модели и Markdown для человека; заменить неясную case-sensitive operation reference понятным optional case-insensitive выбором/поиском; переписать ElevenLabs account/cost explanation человеческим языком. Изменения проходят tests, reviewable PR, exact CI, applicable protected migration/API/web/worker delivery и bounded authenticated LIVE.
- **Non-goals:** commercial contour, RLS/multi-tenant model, новый STT provider, mandatory TOTP, привязка к одному authenticator app, автоматический provider spend/retry, DOCX/YAML/TOML как новые рекомендуемые UI formats, удаление production data, реальная password/TOTP recovery без owner-controlled подтверждения, ослабление worker isolation или audit append-only boundary.
- **Goal AC:**
  1. `PSUX-01`: canonical personal DB/security/UX AC и readiness denominator синхронизированы только по explicit owner scope; pre-existing Evidence не теряется и новые AC не считаются выполненными раньше required gates.
  2. `PSUX-02`: running API подключается отдельной non-superuser/non-owner login role без DDL/role/database privileges; worker сохраняет отдельный `studio_worker`, а bootstrap credential не монтируется в ordinary API/worker runtime.
  3. `PSUX-03`: schema owner остаётся `NOLOGIN`, protected migrator получает только bounded database-local DDL/ownership boundary, reviewed direct grants/default privileges дают API/worker только необходимые table/sequence operations, а новые migrations fail closed до re-apply/verify allowlists.
  4. `PSUX-04`: clean initialization, upgrade, role rotation/switch, API readiness, backup/rollback и negative privilege matrix покрыты tests/runbook/preflight; production switch выполняется после verified backup и допускает explicit recovery без возврата superuser в runtime.
  5. `PSUX-05`: server-authoritative media duration определяется до provider spend; до 4 часов обрабатывается обычно, 4–12 часов требует явного cost warning/confirmation, выше configurable 12-hour hard limit блокируется с переходом в подготовку/разделение, а 22-minute provider part splitting не обходит total limit.
  6. `PSUX-06`: критические account/credential/connection/destructive/security actions требуют bounded recent password re-authentication; proof owner/session scoped, short-lived, one-purpose where required, no-store и audit-safe.
  7. `PSUX-07`: password-reset и TOTP verification имеют независимые bounded rate limits, uniform safe failures и не раскрывают наличие account, secrets или verification material.
  8. `PSUX-08`: optional TOTP использует RFC 6238, encrypted secret, QR/manual setup и становится active только после подтверждения первого code; до enrollment обычный personal login не меняется.
  9. `PSUX-09`: одноразовые recovery codes хранятся только как hashes, показываются один раз, consume/replace audited; TOTP disable требует recent owner verification, а tested operator break-glass не раскрывает secret и не создаёт silent bypass.
  10. `PSUX-10`: dashboard показывает полезные owner actions/status: незавершённые и последние транскрибации, последние документы, connection/system attention и быстрые действия, с корректными empty/loading/error states и без технического шума.
  11. `PSUX-11`: transcription maintenance называется «Подготовка документов»; completed scan/apply summary можно свернуть и явно убрать/reset без отмены durable history или running operation.
  12. `PSUX-12`: diagnostics использует progressive disclosure для system details и event rows, поддерживает bounded pagination; UI рекомендует JSON «для анализа моделью» и Markdown «для человека», а связанная операция выбирается/ищется понятно и case-insensitively без требования угадать точный регистр/ID.
  13. `PSUX-13`: ElevenLabs subscription/cost panel объясняет plan usage, remaining units, overage, invoice и provenance простым русским языком; technical units/evidence остаются в optional disclosure.
  14. `PSUX-14`: backend/frontend/security/migration compatibility покрыты focused/full tests; reviewable PR и exact-head CI success; protected delivery подтверждает exact schema/component/role identity, а bounded LIVE не выполняет paid STT, Google mutation, storage deletion или external notification.
- **Required Evidence:** `SPEC ✅ | CODE ✅ | TEST ✅ | CI ✅ | DEPLOY ✅ | LIVE ✅`.
- **Known blockers/dependencies:** отсутствуют для Goal DoD. Optional TOTP не включался в production LIVE, recovery codes не генерировались, paid STT и destructive session/credential/storage actions не выполнялись; эти действия остаются owner-controlled. Unrelated `apps/studio/pnpm-lock.yaml`, `apps/studio/pnpm-workspace.yaml` и inaccessible `pytest-cache-files-*` directories сохранены untouched.
- **Stop condition:** все Goal AC и required Evidence выполнены либо Goal достигает `BLOCKED` / `PENDING_EXTERNAL_GATE`; к следующей Goal без новой authorization не переходить.

## Previous execution checkpoint — `PERSONAL-SECURITY-UX-01`

- **Updated (UTC):** `2026-09-03T07:05:00Z`.
- **Base branch/SHA:** verified merged and deployed `origin/main@e5c43feac06e1649f1bd0903953ef5de7f925b87` после recovery PR `#292`.
- **Working branch:** `codex/personal-security-ux-closure` от exact merged `origin/main` для operational closure metadata only.
- **Working tree at Goal start:** tracked files clean; unrelated untracked `apps/studio/pnpm-lock.yaml`, `apps/studio/pnpm-workspace.yaml` и inaccessible `pytest-cache-files-*` directories existed before branch and remain untouched.
- **Last verified revision:** functional PR `#292` merged as `e5c43feac06e1649f1bd0903953ef5de7f925b87`; exact-main repository CI `33718805450` и Studio/browser CI `33718805456` завершились success.
- **Completed:** canonical `PWA-UX-POLISH-03`, `PWA-DATABASE-LEAST-PRIVILEGE-03` и remaining `PWA-SECURITY-HARDENING-02` AC реализованы и подтверждены. Production runtime defaults `STUDIO_RECENT_AUTH_SECONDS=600`, duration warning `14400` и hard limit `43200` staged без secret changes; bootstrap/API/migrator/worker credentials являются distinct root-owned `0600` files. Recovery wrapper установлен `root:root 0500`. Reviewer-gated release `33720542771` создал verified snapshot `3b8b9639048c`, выбрал `mode=post_migration_recovery`, не повторял Alembic, re-apply/verify обе role boundaries и развернул API. Final preflight `33725555978` подтвердил configuration, protected secrets, roles, internal/public health и exact schema `0034_personal_security`. Worker delivery `33725645527` и status `33725916595` подтвердили healthy exact image, read-only rootfs, dropped capabilities, no-new-privileges и отдельные DB/egress networks. Authenticated browser LIVE подтвердил active session/security controls, dashboard data, renamed maintenance tab, progressive diagnostics, human-readable ElevenLabs accounting, active Google Drive, exactly one active ElevenLabs BYOK credential, available source list and existing output-folder workflow; browser console warnings/errors отсутствовали.
- **Current step:** Goal закрыта; product code и production state не требуют дополнительных действий.
- **Next exact action:** остановиться после merge closure metadata; следующая Goal требует новой explicit owner authorization.
- **Validation / Evidence:** functional branch: focused recovery `42 passed`, expanded migration/database-role/preflight `97 passed`, Bash syntax, lightweight CI checks и `git diff --check`; exact-main CI `33718805450` и `33718805456` success. Web delivery `33719123640` exact; protected recovery `33720542771` success; final host preflight `33725555978`/job `100553623060` emitted `STUDIO_PROCESSING_HOST_PREFLIGHT_OK`; worker status `33725916595`/job `100554727070` emitted `STUDIO_WORKER_STATUS_OK`, `identity_match=yes`, `isolation_match=yes`. Bounded authenticated LIVE выполнял только read-only navigation/inspection и не запускал provider, Google mutation, secret change, session revocation или deletion.
- **PR / CI / deployment:** implementation PRs `#286`–`#292` merged; final functional merge `e5c43fe`. Exact web `33719123640`/job `100534477741`, recovery `33720542771`/job `100538617088`, worker `33725645527`/job `100553923778` и final worker status `33725916595` success. Production web/API/worker и schema identity соответствуют `e5c43fe` / `0034_personal_security`.
- **Blockers / unverified assumptions:** отсутствуют для Goal DoD. Provider-defined credits всё ещё не преобразуются в минуты без provider Evidence; optional TOTP enrollment/recovery остаётся неактивированным owner choice, а destructive/security actions требуют recent re-authentication.

## Previous Goal closure — `OBSERVABILITY-ALERTS-AUDIT-01`

- **ID / title:** `OBSERVABILITY-ALERTS-AUDIT-01` — сквозная трассировка, неизменяемый audit и bounded operational alerts.
- **State:** `DONE` — все Goal AC и required Evidence закрыты; implementation/recovery PR `#280`–`#284`, exact-main CI, protected schema/API/web/worker delivery и suppressed production alert/recovery canary подтверждены.
- **Authorization source:** explicit owner instruction 2026-09-01 после обсуждения `OBSERVABILITY-ALERTS-AUDIT-01`: «Ставь цель и приступай».
- **Scope:** закрыть canonical `OBSERV-03`, `OBSERV-10`, `OBSERV-15`–`OBSERV-19`, `OBSERV-32`–`OBSERV-34`: безопасный `trace_id` через browser/API/job/worker и события external boundaries; явный audit outcome; database-enforced append-only audit; durable deduplicated operational incidents с bounded cooldown/recovery; правила для critical errors, stuck queue, provider unavailability, backup/cleanup failures и приближения к storage/API limits; optional Telegram operator transport; понятный owner UI в «Для поддержки»; tests, reviewable PR, exact-head CI, applicable protected delivery и non-destructive LIVE alert/recovery canary.
- **Non-goals:** пользовательские job completion/failure notifications; automatic remediation, restart, provider retry или destructive cleanup; передача transcript/provider/storage sensitive content; commercial monitoring stack, Prometheus/Grafana/Sentry; новая retention policy; обязательная email infrastructure; paid provider call, Google Docs mutation или production object mutation в LIVE canary.
- **Goal AC:**
  1. `OAA-01`: canonical observability AC и readiness denominator синхронизированы без изменения unrelated scope и без преждевременного зачёта Evidence.
  2. `OAA-02`: один безопасный `trace_id` создаётся/валидируется на browser/API boundary, возвращается клиенту и сохраняется через job, worker и allowlisted diagnostic/audit события внешних вызовов без sensitive payload.
  3. `OAA-03`: новые audit records имеют явный bounded outcome (`success`, `rejected`, `failed`, `partial`), а legacy records остаются честно различимы без выдуманного результата.
  4. `OAA-04`: PostgreSQL boundary запрещает ordinary application flows изменять или удалять прошлые audit records; downgrade/maintenance contract остаётся explicit и tested.
  5. `OAA-05`: durable owner-scoped incident authority реализует bounded deduplication, pending/firing/acknowledged/resolved lifecycle, cooldown и recovery без alert storm.
  6. `OAA-06`: deterministic rules обнаруживают critical errors, stuck queue, repeated provider unavailability, backup/cleanup failures и приближение к известным storage/API limits, ясно различая configured, unavailable и not-applicable signals.
  7. `OAA-07`: optional Telegram operator transport fail-closed при отсутствии configuration, читает credentials только из secret files, отправляет только allowlisted incident summary и сохраняет bounded delivery outcome без raw provider response.
  8. `OAA-08`: «Для поддержки» показывает понятные system incidents, severity/status/source, последнее безопасное изменение, delivery state и честный email/Telegram configuration status; technical detail остаётся progressive disclosure.
  9. `OAA-09`: evaluation/notification не удерживает DB transaction во время network I/O, конкурентные evaluators не создают duplicate incidents/deliveries, а retry остаётся bounded и idempotent.
  10. `OAA-10`: additive schema, compatibility, owner isolation, trace validation, append-only enforcement, rule thresholds, dedup/cooldown/recovery, transport failure и redaction покрыты unit/integration/frontend tests.
  11. `OAA-11`: focused/full local validation, reviewable PR и exact-head required CI завершаются success; migration/API/web/worker delivery следует protected gates.
  12. `OAA-12`: bounded production LIVE без внешнего spend/mutation подтверждает exact revision, trace continuity, incident create/dedup/resolve и owner UI; реальное Telegram сообщение не отправляется без отдельной action-time authorization.
- **Required Evidence:** `SPEC ✅ | CODE ✅ | TEST ✅ | CI ✅ | DEPLOY ✅ | LIVE ✅`. Exact functional merge `cbbc968096d210425df02dc7bd073dbb610fd1e2`, recovery baseline `368983035a7ae87302ad22a3b4b4945668b956f8`, protected schema `0033`, exact component identity, healthy isolated worker и authenticated suppressed canary подтверждены.
- **Known blockers/dependencies:** отсутствуют для Goal DoD. Telegram остаётся optional и честно `not_configured`; реальное сообщение не отправлялось и по-прежнему требует отдельной action-time authorization и operator-provided secret files. Unrelated `apps/studio/pnpm-lock.yaml`, `apps/studio/pnpm-workspace.yaml` и inaccessible `pytest-cache-files-*` directories сохранены untouched.
- **Stop condition:** все Goal AC и required Evidence выполнены либо Goal достигает `BLOCKED` / `PENDING_EXTERNAL_GATE`; к следующей Goal без новой authorization не переходить.

## Previous execution checkpoint — `OBSERVABILITY-ALERTS-AUDIT-01`

- **Updated (UTC):** `2026-09-02T10:23:57Z`.
- **Base branch/SHA:** verified merged `origin/main@368983035a7ae87302ad22a3b4b4945668b956f8` после fetch и exact-main CI.
- **Working branch:** closure synchronization `codex/observability-goal-closure` от exact merged `origin/main`.
- **Working tree at Goal start:** tracked files clean; unrelated untracked `apps/studio/pnpm-lock.yaml`, `apps/studio/pnpm-workspace.yaml` и inaccessible `pytest-cache-files-*` directories существовали до branch и сохраняются untouched.
- **Last verified revision:** exact merged operational baseline `368983035a7ae87302ad22a3b4b4945668b956f8`; exact functional web/API revision `cbbc968096d210425df02dc7bd073dbb610fd1e2`.
- **Completed:** реализованы additive schema `0033`, browser/API/job/worker trace continuity, explicit audit outcomes и database-enforced append-only boundary, owner-scoped incident/delivery authority с dedup/cooldown/recovery, deterministic provider/queue/maintenance/backup/storage/account rules, optional secret-file-backed Telegram transport, bounded worker evaluation/delivery, Support UI и safe suppressed-delivery canary. Transport не помещает token в URL, application logs или persisted outcome. Local Evidence: affected portable backend `224 passed`; финальный observability/schema/worker/diagnostics subset `73 passed`; frontend full `674 passed`; ESLint, TypeScript, Vite/PWA production build, Python compileall и `git diff --check` success. PR `#280` и recovery PR `#281`–`#284` merged; все exact-head/exact-main required CI success. Protected migration создала verified snapshot `58d4cf20e77d`, обновила schema `0032 -> 0033` и доставила API; web доставлен обычным CD. Reviewed worker grants восстановлены protected lane, one-file `.git/index` ownership drift исправлен без изменения content/mode, а final worker deployment/status подтвердили healthy exact image и isolation. Authenticated owner LIVE показал `Backend/PostgreSQL/queue/worker/object storage` ready, `0` queued/processing, честные `not_configured` limits/transports и recent canary recovery с тем же safe trace в append-only audit.
- **Current step:** Goal закрыта; worker работает healthy/idle, active system incidents отсутствуют.
- **Next exact action:** остановиться и не переходить к следующей Goal без новой owner authorization.
- **PR / CI / deployment:** PR `#280` merged exact `cbbc968`; recovery PR `#281`–`#284` завершились merge `368983035a7ae87302ad22a3b4b4945668b956f8`. Final exact-main repository CI `33564505271` и Studio/browser CI `33564505316` success. Web CD `33557900132` success. Protected migration/API `33558511585`, deployment `6210226421`, применила `0032 -> 0033_observability_alerts_audit` со snapshot `58d4cf20e77d`. Protected worker-role recovery `33563774170`, deployment `6211132217`, success. Final worker deploy `33610692396` и independent status `33610999099` success: `running`, `healthy`, `identity_match=yes`, `isolation_match=yes`, 2 CPU, 4 GiB RAM/swap, 256 PID, read-only rootfs, `cap_drop=ALL`, `no-new-privileges`. Suppressed LIVE canary завершился `resolved`, generation `1`, occurrences `2`; обе delivery rows остались suppressed, provider/Google/storage mutation и Telegram send не выполнялись.
- **Blockers / unverified assumptions:** none для Goal DoD. Telegram credential files не настраивались и не читались; UI честно показывает transport `не настроен`. Storage-limit signal остаётся `not_configured`, а API-limit signal использует authoritative account snapshot. Unrelated `apps/studio/pnpm-lock.yaml`, `apps/studio/pnpm-workspace.yaml` и inaccessible `pytest-cache-files-*` сохранены untouched.

## Previous Goal closure — `STORAGE-LIFECYCLE-FOLLOWUP-01`

- **ID / title:** `STORAGE-LIFECYCLE-FOLLOWUP-01` — multipart uploads, abandoned-session cleanup и безопасная storage reconciliation.
- **State:** `DONE` — все Goal AC и required Evidence закрыты; PR `#278` merged, exact-main CI, protected migration/API/web/worker delivery и bounded non-destructive LIVE подтверждены.
- **Authorization source:** explicit owner instructions 2026-09-01 после обсуждения `STORAGE-LIFECYCLE-FOLLOWUP-01`: «Ставь цель и приступай».
- **Scope:** закрыть canonical `STORAG-01`, `STORAG-02`, `STORAG-04`, `STORAG-09` и безопасную подтверждаемую часть `STORAG-15`: server-authoritative threshold для multipart; owner/project/source-scoped multipart initiation, part capabilities, completion и abort; durable expiring upload-session authority; bounded idempotent abandoned-session cleanup; owner-scoped orphan inventory/reconciliation с dry-run по умолчанию и отдельным явным подтверждением apply; явная effective retention для transcription-reference; physical delete считается успешным только после подтверждения отсутствия exact object; безопасные audit/diagnostics и пользовательский storage-health UX; tests, reviewable PR, exact-head CI и применимый migration/API/web/worker delivery с bounded non-destructive LIVE verification.
- **Non-goals:** удаление Google Drive originals или Google Docs; broad retention/delete внутренних transcript, History или Analytics данных; cleanup obsolete versions при неподтверждённом versioning; commercial/Russian S3 contour; автоматический destructive production reconciliation; logging/возврат object keys, bucket names, upload IDs, presigned URLs или raw storage errors; изменение lifecycle сроков уже существующих объектов; ослабление reference-class/bucket/credential isolation.
- **Goal AC:**
  1. `SLF-01`: canonical storage AC и readiness denominator синхронизированы без изменения unrelated scope и без преждевременного зачёта Evidence.
  2. `SLF-02`: все browser-initiated large reference uploads выше server-authoritative threshold используют S3-compatible multipart protocol; small uploads сохраняют безопасный single-PUT path, а server-side managed uploads остаются multipart-capable.
  3. `SLF-03`: multipart initiation, part issue, completion и abort owner/project/source scoped, fail closed при identity/lifecycle mismatch и возвращают capabilities только в `no-store` responses без browser persistence.
  4. `SLF-04`: durable multipart session хранит только server-side exact storage identity, expected metadata, expiry и terminal state; complete/abort replay idempotent, а completion подтверждается storage metadata до перевода source в uploaded.
  5. `SLF-05`: abandoned multipart sessions периодически выбираются bounded lease/fencing cleanup, abort-ятся idempotently и получают terminal/ retryable state без удержания DB transaction во время S3 I/O.
  6. `SLF-06`: orphan reconciliation строит bounded paginated owner-scoped inventory, сверяет exact reference class/bucket/key с PostgreSQL authority, по умолчанию выполняет dry-run и не удаляет ambiguous, active или too-fresh objects.
  7. `SLF-07`: destructive orphan apply требует отдельного явного подтверждения, удаляет только exact unchanged plan в bounded batch и подтверждает физическое отсутствие каждого object до terminal cleanup status.
  8. `SLF-08`: Settings показывает понятную effective policy для transcription/audio references, состояние lifecycle/reconciliation и безопасный dry-run с counts/volume без storage identifiers; destructive action отделено от preview.
  9. `SLF-09`: source deletion/retention cleanup считается физически завершённым только после verified absence exact object; Google Drive остаётся `not_applicable`, а broader cross-store `STORAG-15` не объявляется выполненным.
  10. `SLF-10`: additive schema, compatibility, owner isolation, concurrency, replay, pagination, timeout/failure и redaction покрыты unit/integration/frontend tests.
  11. `SLF-11`: focused/full local validation, reviewable PR и exact-head required CI завершаются success; required migration/API/web/worker delivery следует protected gates.
  12. `SLF-12`: bounded production LIVE подтверждает safe upload-policy/effective-retention DTO и non-destructive orphan dry-run; никакой production object не удаляется без отдельной action-time authorization.
- **Required Evidence:** `SPEC ✅ | CODE ✅ | TEST ✅ | CI ✅ | DEPLOY ✅ | LIVE ✅`. Exact merge `ac632b5bd2c0a258a44ff6e5e3b829d3aa1c524e`, exact-main CI, protected schema `0032`, API/web/worker identity и authenticated storage-policy/dry-run LIVE подтверждены.
- **Known blockers/dependencies:** отсутствуют для Goal DoD. Destructive production orphan apply не выполнялся и по-прежнему требует отдельной action-time authorization; provider lifecycle rules остаются defence in depth. Unrelated `apps/studio/pnpm-lock.yaml`, `apps/studio/pnpm-workspace.yaml` и inaccessible `pytest-cache-files-*` directories сохранены untouched.
- **Stop condition:** все Goal AC и required Evidence выполнены либо Goal достигает `BLOCKED` / `PENDING_EXTERNAL_GATE`; к следующей Goal без новой authorization не переходить.

## Previous execution checkpoint — `STORAGE-LIFECYCLE-FOLLOWUP-01`

- **Updated (UTC):** `2026-09-01T18:16:16Z`.
- **Base branch/SHA:** verified merged `origin/main@ac632b5bd2c0a258a44ff6e5e3b829d3aa1c524e` после fetch.
- **Working branch:** closure synchronization `codex/storage-lifecycle-closure` от exact merged `origin/main`.
- **Working tree at Goal start:** tracked files clean; unrelated untracked `apps/studio/pnpm-lock.yaml`, `apps/studio/pnpm-workspace.yaml` и inaccessible `pytest-cache-files-*` directories существовали до branch и сохраняются untouched.
- **Last verified revision:** `ac632b5bd2c0a258a44ff6e5e3b829d3aa1c524e`.
- **Completed:** реализованы additive schema `0032`, durable owner-scoped multipart authority и per-part capabilities, server-side completion/status/abort, browser multipart paths для transcription/audio preparation, fenced abandoned-session cleanup с verified absence, bounded owner-scoped reconciliation preview/apply, safe lifecycle DTO/Settings UX, diagnostics/audit redaction, runtime config и operational docs. Local Evidence: backend focused `116 passed`, compatibility regression `78 passed`, frontend full `670 passed`, ESLint, TypeScript/Vite/PWA production build, Python compileall и `git diff --check` success. PR `#278` прошёл review и exact-head required CI; exact-main CI также success.
- **Current step:** Goal закрыта; destructive production orphan apply не выполнялся.
- **Next exact action:** остановиться и не переходить к следующей Goal без новой owner authorization.
- **PR / CI / deployment:** PR `#278`, commits `f00074c`/`aa4a831`, merge `ac632b5`; exact-head CI `33540306329` (`1614 passed`) и Studio/browser `33540306338` success; exact-main CI `33540632446` и Studio/browser `33540632492` success. Web CD `33540632463` success. Protected migration release `33541331595`, job `99968055062`, применила `0031 -> 0032_source_multipart_authority`, сохранила snapshot `93ecba2be2b1` и доставила API. Worker drain `33541234693`, worker deploy `33541844977` / job `99969800397` и status `33542236147` success; exact image/commit identity и `isolation_match=yes` подтверждены.
- **Blockers / unverified assumptions:** authenticated LIVE подтвердил web/API/worker exact `ac632b5`, schema `0032`, backend/PostgreSQL/queue/worker/object-storage readiness, effective retention `3 дня`, multipart threshold `16 MB` и safe orphan dry-run `0` candidates. Read-only processing preflight `33542235820` корректно fail-closed после worker deploy, потому что этот operator preflight допускает только остановленный worker; runtime health отдельно подтверждён status/LIVE. Storage versioning не предполагается, obsolete-version cleanup не заявлен. Ни один production object не удалён.

## Previous Goal closure — `PWA-TRANSCRIPTION-PROGRESS-HOTFIX-01`

- **ID / title:** `PWA-TRANSCRIPTION-PROGRESS-HOTFIX-01` — непрерывный прогресс транскрибации и безопасная граница долгих worker-операций.
- **State:** `DONE` — owner 2026-09-01 принял delivered production outcome и явно разрешил закрыть Goal без дополнительного paid LIVE retry; возможная новая regression будет отдельным hotfix.
- **Authorization source:** explicit owner instructions 2026-09-01: устранить regression, из-за которой длинные записи перестали транскрибироваться; до hotfix улучшить UX единым активным progress bar процесса транскрибации с live-обновлением через подходящий transport; затем explicit «цель поставь еще», «разрешаю» и после повторного сбоя «ну так делай».
- **Scope:** единый пользовательский progress bar с текущим действием, активным файлом и подтверждённым процентом; owner-scoped polling каждые 3 секунды с bounded backoff; технические checkpoints под progressive disclosure; закрытие read-only DB transaction после immutable authoritative snapshots и до долгих R2/Google Drive/source/FFmpeg операций; fresh fail-closed lifecycle/source/credential/output revalidation до provider spend; безопасное различение ElevenLabs `401` / `402` / `403` с allowlisted machine code, exact HTTP status и actionable retry UX без raw provider message; исправление несовместимости immutable provider-part checkpoint с restricted PostgreSQL worker role; явный cost-confirmed полный restart только для подтверждённого provider result, который не успел получить checkpoint; сохранение recovery-задачи в пользовательском списке после очистки истории, если её provider outcome продолжает блокировать новый batch, и прямая навигация к безопасному действию; regression tests, документация, reviewable PR, exact-head CI и применимый web/API/worker delivery с bounded owner-authorized LIVE verification.
- **Non-goals:** realtime STT и новая WebSocket infrastructure; выдуманный time-based процент; ослабление `idle_in_transaction_session_timeout=60s`, worker isolation, lifecycle/provider-cost gates или duplicate protection; automatic retry уже упавшей job; новый provider; commercial contour; paid provider call без отдельной bounded owner authorization.
- **Goal AC:**
  1. `TPH-01`: canonical product AC и readiness denominator синхронизированы без изменения unrelated scope.
  2. `TPH-02`: running transcription отображается одним постоянно активным meter с текущим пользовательским действием, активным файлом и точным процентом подтверждённых checkpoints.
  3. `TPH-03`: owner-scoped automatic polling обновляет прогресс без ручного reload/tab switch, использует bounded backoff и сохраняет последний подтверждённый state при transient failure.
  4. `TPH-04`: технические stages доступны под disclosure; meter имеет корректные ARIA semantics, а reduced-motion отключает animation.
  5. `TPH-05`: external source availability/materialization и media preparation выполняются без idle worker DB transaction после immutable snapshot.
  6. `TPH-06`: после долгого I/O выполняется fresh fail-closed lifecycle/source/credential/output revalidation перед любым provider call; isolation и spend gates не ослаблены.
  7. `TPH-07`: unit/component и real-PostgreSQL regression tests покрывают transaction boundary, concurrency revalidation и progress behavior.
  8. `TPH-08`: focused/full local validation, один initial push, reviewable PR и exact-head required CI завершаются success.
  9. `TPH-09`: exact merge revision доставлена во все применимые web/API/worker components; health и identity gates подтверждены.
  10. `TPH-10`: planned отдельно owner-authorized bounded достаточно длинный paid LIVE retry снят owner как обязательный closure gate 2026-09-01; отсутствие этого дополнительного spend не отменяет подтверждённые CI/DEPLOY/LIVE Evidence, а возможная новая regression оформляется отдельным hotfix.
  11. `TPH-11`: provider rejection различает authentication/payment/scope/request/rate failures, сохраняет только allowlisted machine code и bounded HTTP status, не раскрывает provider message/request ID и даёт безопасное пользовательское объяснение перед explicit retry.
  12. `TPH-12`: immutable provider-part checkpoint сохраняется под exact restricted worker grants без `UPDATE`; verifier и real-PostgreSQL regression закрепляют `SELECT/INSERT/DELETE` и отсутствие `UPDATE/TRUNCATE`.
  13. `TPH-13`: confirmed-but-uncheckpointed partial result не восстанавливается автоматически, но owner получает явный полный restart только после provider-cost confirmation; uncertain accounting остаётся заблокированным.
  14. `TPH-14`: очистка истории скрывает обычные terminal jobs, но не скрывает owner-scoped job с unresolved provider attempt, который продолжает блокировать paid-call authority; такая job закреплена в «Текущих», не может быть повторно убрана в историю и доступна из batch blocker без создания дубля или provider call.
- **Required Evidence:** `SPEC ✅ | CODE ✅ | TEST ✅ | CI ✅ | DEPLOY ✅ | LIVE ✅`. Exact merge `30f21a66bcba966134b07407aa7fbad18f6a88e9`, successful exact-main CI/CD, bounded no-spend production inspection и owner acceptance подтверждены; дополнительный paid retry больше не входит в Goal DoD.
- **Known blockers/dependencies:** последняя production job подтвердила provider usage `801.689 s`, затем завершилась `partial_provider_result` до первого checkpoint. Regression `SELECT ... FOR UPDATE` на immutable checkpoint table исправлена и доставлена без выдачи worker роли `UPDATE`. UX dead-end после `clear history` устранён: unresolved recovery jobs остаются в «Текущих», не могут быть повторно скрыты и показывают безопасное действие. Новый paid provider call не выполняется автоматически. Unrelated `apps/studio/pnpm-lock.yaml`, `apps/studio/pnpm-workspace.yaml` и inaccessible `pytest-cache-files-*` directories сохраняются без изменений.
- **Stop condition:** все Goal AC и required Evidence выполнены либо Goal достигает `BLOCKED` / `PENDING_EXTERNAL_GATE`; к следующей Goal без новой authorization не переходить.

## Previous execution checkpoint — `PWA-TRANSCRIPTION-PROGRESS-HOTFIX-01`

- **Updated (UTC):** `2026-09-01T16:12:26Z`.
- **Base branch/SHA:** verified `origin/main@e73697cc4f0a2d96c0ed420466a65428f5abaf2c`; exact functional production web/API identity `30f21a66`.
- **Working branch:** Goal closure synchronization `codex/transcription-goal-closure` от exact `origin/main@e73697c`.
- **Working tree at Goal start:** tracked files clean; unrelated `apps/studio/pnpm-lock.yaml`, `apps/studio/pnpm-workspace.yaml` и inaccessible `pytest-cache-files-*` directories существовали до branch и сохранены untouched.
- **Last verified revision:** exact merged и delivered functional revision `30f21a66bcba966134b07407aa7fbad18f6a88e9`.
- **Current step:** Goal closure принята owner; дополнительная implementation или provider spend не требуется.
- **Next exact action:** none; остановиться. Новую проблему при её фактическом появлении оформить отдельным hotfix Goal.
- **PR / CI / deployment:** PR `#275` merged как `30f21a66`; exact-main CI `33521901250` success, Studio/browser `33521901245` success, CD `33521901302` success.
- **Blockers / unverified assumptions:** none. Residual risk дополнительного sufficiently-long paid retry явно принят owner и не является blocker закрытой Goal.

## Previous Goal closure — `PWA-WORKER-USAGE-ACCOUNTING-01`

- **ID / title:** `PWA-WORKER-USAGE-ACCOUNTING-01` — worker isolation и reconciled ElevenLabs usage/cost accounting.
- **State:** `DONE` — reconciled 2026-09-01 по exact main `fe58220da1bad9e25332f62d001bdc37ed769fdb`, successful CI `33479803256`, Studio/browser `33479803115`, platform CD `33479803110`, manual worker deploy `33480733237` и subsequent worker status `33481047378` / `33481700306`. Product readiness остаётся независимо evidence-gated в `docs/project-spec.md`.
- **Authorization source:** explicit owner instructions 2026-08-30: следующей единой Goal взять `Worker isolation` и `Usage/cost accounting`; затем расширить её server-side синхронизацией всегда актуальных данных ElevenLabs subscription/usage/overage/invoice и всеми расчётами, которые допускает official provider Evidence. Explicit owner «да» 2026-08-31 approved account refresh and exactly one test transcription of a source up to 30 seconds, with possible ElevenLabs quota/cost; no automatic retry or second job. That transcription authorization was consumed once at `2026-08-31T20:02:51Z`. A separate explicit owner «Да» authorized one existing-output reconciliation check, completed by `2026-08-31T20:24:29Z`; it did not authorize new STT, document creation, worker resume or SQL recovery. Explicit owner «приступай» 2026-09-01 resumed implementation of the remaining Goal scope.
- **Scope:** закрыть canonical `PWAWOR-02..03` и `USAGEC-01..06`: задать и проверить CPU/memory/PID bounds worker; ограничить его writable filesystem, Linux capabilities, privilege escalation и network reachability; отделить worker от API database credential и DDL/superuser capability; сохранять подтверждённую STT duration и immutable nominal tariff snapshot на job; server-side получать official ElevenLabs subscription и workspace product-credit usage, сохранять bounded owner/credential-version-scoped current snapshot с freshness/error provenance; раздельно показывать job nominal estimate и account actual overage/invoices/period units; добавить additive migrations, safe owner API/UI/diagnostics projection, tests/docs, reviewable PR, exact-head CI, applicable protected migration/API/worker delivery и одну bounded owner-authorized LIVE transcription с account refresh.
- **Non-goals:** commercial contour и пользовательский billing; scraping pricing page или автоматическое изменение public tariff snapshot без verified release input; выдуманное распределение account invoice/overage по отдельным jobs; преобразование ElevenLabs credits/characters в минуты без provider Evidence; новый STT provider или automatic fallback; realtime cost accounting; storage/compute/network cost; изменение `docs/ci-cd-rules.md`, GitHub protections или unrelated refactors.
- **Goal AC:**
  1. `WUA-01`: canonical closure предыдущей Goal и baseline readiness reconciled; durable scope/denominator не изменены.
  2. `WUA-02`: worker Compose имеет explicit CPU, memory/swap и PID bounds, а tests проверяют rendered effective configuration.
  3. `WUA-03`: worker root filesystem read-only; writable paths bounded; capabilities dropped; privilege escalation disabled; runtime после secret bootstrap остаётся UID/GID `10001`.
  4. `WUA-04`: Compose networks дают worker только PostgreSQL и отдельный outbound boundary, без API/web/Redis discovery и published ports.
  5. `WUA-05`: worker использует отдельный non-superuser login без DDL/role capability; read/write grants ограничены documented current worker tables и проверены integration test/runtime preflight.
  6. `WUA-06`: каждый фактически подтверждённый provider part идемпотентно учитывается ровно один раз; retries/checkpoint resume не дублируют confirmed usage, а uncertain provider outcome не выдаётся за exact billed usage.
  7. `WUA-07`: job хранит confirmed billed duration, provider cost, currency, rate snapshot/provenance и accounting completeness; unsupported/missing tariff fail closed before spend.
  8. `WUA-08`: owner API/UI и diagnostics показывают безопасную duration/cost summary без credential, raw provider payload или internal request identifiers.
  9. `WUA-09`: additive migration и backward-compatible reads корректны для existing jobs; downgrade/rollback boundary documented и tested.
  10. `WUA-10`: focused/full local validation, один initial push, reviewable PR и exact-head required CI завершаются success; confirmed failure исправляется одним grouped follow-up batch.
  11. `WUA-11`: protected migration/API и manual worker status→drain→deploy→status соответствуют exact merge SHA; resource/network/DB role runtime evidence подтверждено без secret values.
  12. `WUA-12`: одна owner-approved bounded transcription подтверждает persisted billed duration/cost/currency и отсутствие regression; до такого call Goal остаётся `PENDING_EXTERNAL_GATE`.
  13. `WUA-13`: server-side ElevenLabs account transport валидирует bounded official subscription response и workspace product-credit response; API key, raw provider payload и provider user identifiers не попадают в browser/cache/logs.
  14. `WUA-14`: owner/credential-version-scoped snapshot хранит plan/status, provider period usage/limit/remaining, reset, usage-based billing entitlement/cap, actual current overage, invoice aggregates и product credits с explicit units/window provenance.
  15. `WUA-15`: automatic refresh при открытом UI использует максимум пятиминутный successful snapshot, visible timestamp и bounded polling; manual refresh доступен, а provider failure возвращает last successful snapshot как stale либо explicit unavailable без fabricated values.
  16. `WUA-16`: UI и API раздельно обозначают local job nominal estimate, provider account usage units, current overage и invoice; model-specific minutes/remaining или per-job invoice allocation показываются только при direct provider Evidence.
- **Required Evidence:** `SPEC ✅ | CODE ✅ | TEST ✅ | CI ✅ | DEPLOY ✅ | LIVE ✅`. Closure reconciled against exact main/runtime identifiers in the state line above; later transcription regression belongs to the new Goal and does not revoke the completed isolation/accounting Evidence.
- **Known blockers/dependencies:** none remaining for this closed Goal. Historical blockers and execution sequence are preserved below as previous checkpoint Evidence.
- **Stop condition:** все Goal AC и required Evidence выполнены либо Goal достигает `BLOCKED` / `PENDING_EXTERNAL_GATE`; к следующей Goal без новой authorization не переходить.

## Previous execution checkpoint

- Runtime usage Evidence (owner diagnostic 2026-08-31): guarded checkout/API `cb481be1`, HTTP 200; columns `product_type`, `timestamp`, `total_usage` (`credits`, integer cells), `total_minutes` (`min`), `total_cost` (`usd`), `usage_count`, `total_charge_count`; 31 rows, zero invalid row shapes. Validator stopped at `normalize_workspace_usage:325` because `credits_used` was absent. Only schema/type/count evidence received; no keys, amounts, product values or raw rows. Diagnostic did not mutate DB, restart services or call STT.

- Updated (UTC): 2026-09-01T06:51:44Z.
- Session mode: authorized full-delivery Goal; все non-goals выше запрещены.
- Base branch/SHA: verified `origin/main@476c6492b7127d7e06e8d71fb2fca91071275a6a`; local main was safely fast-forwarded to that revision. Open PR check returned none.
- Working branch: `codex/output-reconciliation-job-cost`.
- Isolated worktree: not used; tracked main was clean and unrelated inaccessible `.pytest-*` directories are preserved unmodified.
- Last verified revision: PR head `03addda3aa919107be4f04ea6f492c271ec9c2f0` on base `476c6492`; exact-head required checks are terminal success. Current documentation synchronization is the only tracked change.
- Working tree at Goal start: tracked files clean; unknown/unrelated `.pytest-*` directories were present and remain untouched.
- Completed: implementation PR `#261` и sequential-migration hotfix PR `#262` merged; exact-main CI success. Worker configuration/credential staged, old worker gracefully drained. Protected run `33322760011` verified snapshot `ee9c4b84b51c…` и применил `0029 → 0030`. Run `33328210998` после owner approval остановился до backup/migration (`running_api_head_probe_failed`, `migration_applied=no`). Owner VPS Evidence 2026-08-31 подтвердило: running API container существует, но image `sha256:75cda05ecfcbf87a5b7d86bcc17fce0b42a69c00988296f96ba88d333fd86420` отсутствует в local image store. Local correction читает baked head через exact running container под UID/GID `10001`, сохраняя schema-chain и container-identity gates.
- Current step: PR `#270` was created from initial head `9f3ef7d`. Initial main checks run `33474178200` / job `99749874484` failed exactly one of `1591` tests because the first repair removed the project row lock without transferring the archive race guard. Commit `1c85db7` now locks the project and deterministically locks its job rows in the API archive transaction; worker persistence continues to lock the same mutable job boundary while reading `projects` without UPDATE privilege. Corrected head `03addda` passed main CI `33479042277` / `99764338523` with `1591 passed`, including the new restricted-grant/archive serialization regression. Studio/browser run `33479042292` passed jobs `99764340123` and `99764339404`, including lint, `659` Vitest tests, build, browser E2E and container/runtime probes. Local Evidence after correction: focused output persistence `12 passed`; portable Python `1267 passed, 5 skipped, 15 warnings`; Python compile, lightweight CI and diff checks pass. No upload, STT, reconciliation, worker resume or production mutation occurred.
- Next exact action: publish this explicitly authorized metadata synchronization, wait for exact metadata-head checks, merge PR `#270` and follow applicable API/web delivery. No second provider call before a separate bounded LIVE authorization.
- Canary accounting Evidence: authenticated analytics shows one complete-accounting job, zero uncertain-provider outcomes and nine historical unavailable jobs; rounded duration `13 s`, nominal cost `0.00077073 USD`, explicitly not an invoice debit. Persisted job duration/cost and the current account snapshot support `USAGEC-01/02/03/04/06`. The new per-job presentation is local only and is not counted until exact delivery/LIVE.
- Output failure diagnosis (local 2026-09-01): `job_output_persistence._load_locked_output_authority` locked `Project` with `FOR UPDATE`, which requires `UPDATE` privilege that the intentionally read-only worker role does not have. The local fix removes only the project row lock and preserves locks on mutable job, relation and source rows. Unit SQL-shape tests pass; a real-PostgreSQL SQLSTATE `42501` regression is authored but not claimed locally.
- Worker stop Evidence: pre-canary status `33433536607` / `99624406068` confirmed healthy/isolation; reviewed drain `33433995948` / `99625914547` succeeded at `2026-08-31T20:04:38Z` with `container_state=exited`, `exit_code=0`, `drain_state=gracefully-drained`, unchanged image and isolation. API/web/database/storage were not restarted. Worker remains stopped during this implementation.
- Usage compatibility delivery: PR `#269`, head `b8e7549326d3c048e87b70793e60643e0b512f72`, merged as `476c6492b7127d7e06e8d71fb2fca91071275a6a`. PR CI `33429313935` / `99610511502` and Studio/browser `33429314091` succeeded; main CI `33429652748` / `99611618712` and Studio/browser `33429652780` succeeded. API-only CD `33429652762` / `99611664932` emitted `STUDIO_PLATFORM_API_DEPLOY_OK`; schema stayed `0031`. Authenticated LIVE then showed current subscription/period/remaining/reset/overage/invoice and STT product credits with explicit provenance.
- Invoice fix main CI/DEPLOY: `cb481be1a46a4f1ac091a0de63c518d023f799da`, CI `33425500196` / `99597943848` success (`1561 passed, 2 warnings`), Studio/browser `33425500171` / `99597943747` / `99597943379` success. Standard CD `33425500261` terminal success: web `99597992588` emitted `STUDIO_PLATFORM_WEB_DEPLOY_OK` at `2026-08-31T18:33:24Z`; API `99598504574` emitted `STUDIO_PLATFORM_API_DEPLOY_OK` at `2026-08-31T18:36:59Z`. Exact checkout/image equality and component health gates passed; worker/migration jobs intentionally unselected. Public build metadata at `18:34:45Z` reports exact `cb481be1`; `/api/readyz` at `18:37:43Z` confirms schema `0031` and reachable database/Redis. Local synthetic WAV is 12.612426 seconds / 556254 bytes, not uploaded; no paid provider call made.
- Invoice fix commit/PR: `5f65955bfacc39c9d8f30a0a8ae9a36e39ca6456`, PR `#268`, branch `codex/elevenlabs-invoice-compat`; one initial push after local validation. Exact-head CI `33425125639` / `99596726066` success (`1561 passed, 2 warnings`, nullable persistence regression passed); Studio/browser `33425125599` / `99596725594` / `99596725442` success. MERGEABLE/CLEAN, no review requests/unresolved threads; squash merged at `2026-08-31T18:31:33Z` as `cb481be1a46a4f1ac091a0de63c518d023f799da`. Main CI and selected API/web delivery completed; no follow-up push, speculative rerun or canary. Post-deploy checkpoint updates are local only; no metadata-only commit/PR loop.
- Invoice compatibility validation: red regression `6 failed, 45 passed`; corrected account/accounting/analytics focused suite `60 passed`; full portable suite `1237 passed, 5 skipped, 15 warnings`; frontend `654 passed` in 60 files; lint, typecheck/production build, lightweight CI checks, Python syntax and diff checks passed. Local sandbox initially blocked subprocess/temp access; unsandboxed test execution and explicit installed Git Bash in PATH resolved environment failures without changing tests. PostgreSQL/Redis integration and real Docker/browser CI are not claimed locally. API/web changes only; schema remains `0031`, worker unchanged. Independent epic-row recount: `578` unique AC, `266` completed; non-commercial `266/336`, personal `234/304`, worker `3/3` not READY, usage `0/6`. No new product AC or readiness increase.
- Account recheck Evidence (2026-08-31T18:38:08Z): authenticated Connections panel shows current subscription, a fetched timestamp and provider plan/period/overage/invoice data. Expanded workspace product usage independently reports unsupported format / unavailable breakdown. Subscription success does not establish workspace analytics success or per-job accounting. Switched to Account and handed browser back, stopping account polling. No manual refresh, source upload or transcription submitted. LIVE is partial; no new complete product AC is counted. Temporary operator diagnostic passed Bash/Python syntax checks and mocked valid/invalid-response checks; its output excluded fixture secret and amounts and made exactly one request per invocation. Actual VPS diagnostic remains not-run.
- Account LIVE prerequisite Evidence (2026-08-31T17:43Z): authenticated Studio overview reports ready/Google connected; Connections shows exactly one active ElevenLabs credential version and subscription `Данные недоступны`, fetched timestamp absent, message `ElevenLabs отклонил ключ. Проверьте или замените его.`. Source mapping identifies the HTTP-401-class reason, but no raw provider response or secret was read; exact expiry/permission/credential cause is not proven. Workspace analytics is not reached when subscription fetch fails. No new product AC is counted.
- Post-rollout preflight Evidence: run `33421041673`, job `99583213864`, terminal failure at `2026-08-31T17:43:04Z`; repository/branch/exact SHA/clean worktree and all five services running/healthy were observed. The pre-rollout script then blocks because it requires zero running workers; later secret/role/schema/public checks were not run. This invocation was not applicable to the already-running canary worker and is not a new production failure. Do not drain/redeploy or weaken the preflight to make it green. Independent public `/api/readyz` at `2026-08-31T17:45:11Z` confirms schema `0031`, database/Redis reachable; `/build-meta.json` confirms exact web `7629fde8`.
- Recovery main CI Evidence: `33408271757`, job `99541187721`: `1519 passed, 2 warnings`, `CI_OK`; Studio/browser `33408271682` both success. Actual Docker job `99541187442` emitted `STUDIO_WEB_HOST_PUBLICATION_OK` at `2026-08-31T15:26:09Z`.
- Post-recovery worker Evidence: status `33409097724`, job `99543911523`, SUCCESS at `2026-08-31T15:33:30Z`; running/healthy, same immutable image `sha256:19d8c05f9de9777d87e5694673ed4a931591c5bbef7d577c1ee52fe10fcfa972` previously verified for `8957e974`, rollback candidate present. Limits remain 2 CPU / 4 GiB memory including swap total / 256 PID; read-only rootfs, no-new-privileges, exact permitted capability set and two worker networks; corrected classifier returns `isolation_match=yes`. `identity_match=unknown` compares against the new web-only checkout tag `7629fde8`, which was intentionally never built for worker; it is not a worker image change or successful new worker deployment. No retag/restart was performed.
- Recovery PR Evidence: head `b639ef632df55a45a0075918d4da382fd56779a3`; CI `33407921270`, job `99540011656`: `1519 passed, 2 warnings`. Studio/browser `33407921323` success; real Docker job `99540011635` emitted `STUDIO_WEB_HOST_PUBLICATION_OK` at `2026-08-31T15:22:18Z`. Host publication smoke took about one second and reused the existing CI-built image; no additional monitoring workflow or provider calls.
- Recovery validation: expected red tests reproduced missing ingress and CAP_ false negatives (`3 failed, 15 passed`); corrected focused suite `24 passed`. Portable suite `1195 passed, 5 skipped, 15 warnings`; lightweight repository checks, Bash/Python syntax, actual Docker Compose JSON rendering and diff checks passed. Local Docker daemon is unavailable; actual host-publication smoke remains mandatory in the existing Studio CI job, not claimed as local runtime Evidence. Product AC recount remains `266/578`, non-commercial `266/336`, personal `234/304`; no new AC or scope added by this hotfix.
- Worker delivery Evidence: run `33388441193`, job `99476297938`, success marker at `2026-08-31T11:45:55Z`; deployed commit `8957e974abe8c03224a572389c41aac84c99b609`, image `sha256:19d8c05f9de9777d87e5694673ed4a931591c5bbef7d577c1ee52fe10fcfa972`. Web/API/migration jobs intentionally skipped. Separate status `33388535135`, job `99476560035`, at `2026-08-31T11:46:44Z`: running/healthy, identity match yes, rollback candidate present, CPU `2000000000` nano, memory/swap total `4294967296`, PID limit `256`, read-only rootfs, no-new-privileges and exactly the two worker networks. Raw allowed capability set is `CAP_CHOWN/CAP_SETGID/CAP_SETUID`; no additional capability is present. Legacy text comparison expects names without `CAP_`, causing `isolation_match=no`; this classifier defect is not a runtime privilege drift and is not hidden as a passing marker.
- Historical worker failure Evidence (superseded by successful rollout/status above): `Studio Platform CD` run `33386569656`, job `99470449268`, terminal failure at `2026-08-31T11:24:52Z`: `revision probe failed: Alembic head command exited non-zero`. Build completed; failure precedes database-current probe, commit tag and force-recreate. Selected worker failed; web/API/migration intentionally skipped. Read-only status `33387079622`, job `99472019745`, success at `2026-08-31T11:28:12Z`: old image `sha256:1654e3804607abbba37a83518d10678994010a62f6993b61037884f194dbe681`, exited/zero/gracefully-drained, commit tag absent, rollback candidate present, `isolation_match=no`. Public `/api/readyz` returned HTTP 200, database/Redis reachable, schema `0031` after failure.
- Historical web failure Evidence (resolved by `33408823378`): selected run `33388699857`, job `99477091937`, failed at `2026-08-31T11:51:00Z` after successful build and container replacement. Built/running image identity check passed, but localhost `8181/healthz` refused connection and public web returned `502`; API readiness stayed healthy. Owner Docker 29.7.2 diagnostic then confirmed internal-only web had no actual host-port binding despite healthy nginx. PR `#267` fixed this regression and preserved the loopback-only endpoint and worker boundary.
- Current owner/runtime Evidence: owner output confirms clean fast-forward to `807bc4abc8b0b4791f210a23f5fb7faa62dae007`, corrected preflight as `studio-deploy`, and `STUDIO_PROCESSING_HOST_PREFLIGHT_OK`; PostgreSQL/Redis/API/web healthy, schema `0031`, secrets present without changed permissions. Read-only worker status run `33377366826`, job `99441762605`, succeeded at `2026-08-31T09:23:03Z`: one exited worker, `exit_code=0`, `drain_state=gracefully-drained`, old image `sha256:1654e3804607abbba37a83518d10678994010a62f6993b61037884f194dbe681`, no commit tag/rollback candidate, `isolation_match=no`. No worker deployment was dispatched. Authenticated/provider canary rows remain not-run.
- Schema-readiness validation: focused verifier/worker-health/Compose suite `37 passed`; portable suite `1180 passed, 5 skipped, 15 warnings` under existing service/shell exclusions; lightweight checks, Bash/Python syntax and diff checks passed. PostgreSQL/Docker daemon are unavailable locally. New Linux integration test applies the real manifest in an isolated migrated database, connects as an actual non-superuser login, proves readiness, denies schema-version writes/DDL and prohibited-table reads, revokes SELECT to reproduce the failure, then restores SELECT only. No extra CI infrastructure or workflow reruns are added.
- Schema-readiness CI/merge Evidence: PR `33378597911`, job `99445576092`: `1504 passed, 2 warnings`; actual restricted-login test PASSED at `2026-08-31T09:38:19Z`. PR Studio/browser `33378597846` success. Exact-head merge gates: MERGEABLE/CLEAN, no pending review requests or unresolved threads. Merge at `2026-08-31T09:41:11Z`. Main CI `33378898835`, job `99446506439`: `1504 passed, 2 warnings`, restricted-login test PASSED at `2026-08-31T09:42:01Z`. Main Studio/browser `33378898642` success. Automatic Platform CD `33378898752` completed with all application/migration jobs intentionally skipped; this is not deployment Evidence. VPS checkout still last verified at `807bc4`; no worker rollout was dispatched.
- Readiness reconciliation: atomic-row check found five stale `STORAG-17..21` completion markers, despite their previous Goal closure already recorded in the dashboard and verified delivery chain. Align these operational markers with that existing Evidence; no requirements, denominator or new product completion are added by the worker hotfix. Canonical total remains `264/578`, non-commercial `264/336`, worker `1/3`, usage `0/6`.
- Secret-probe hotfix PR Evidence: PR CI `33376485789`, job `99439016112`: `1499 passed, 2 warnings`, including all Linux SSH/path transport tests. Studio/browser CI `33376485750` passed. Real Docker job `99439016699` emitted `STUDIO_WORKER_SECRET_METADATA_OK` at `2026-08-31T09:14:15Z`; positive root-owned `0700` parent with `0600`/`0400` file and negative wrong permissions/symlink/missing/empty cases passed without reading secret bytes. Exact-head checks all success, mergeable/CLEAN, no pending review requests or unresolved review threads; merge occurred at `2026-08-31T09:15:28Z`. Exact-main CI is confirmed below; runtime files/services were not changed.
- Secret-probe hotfix main Evidence: merge `807bc4abc8b0b4791f210a23f5fb7faa62dae007`, CI `33376764865` and Studio/browser `33376764864` all success. Real Docker main job `99439897723` emitted `STUDIO_WORKER_SECRET_METADATA_OK` at `2026-08-31T09:17:25Z`. This proves the probe in CI, not production preflight or worker deployment. No speculative reruns or follow-up pushes occurred.
- Secret-probe hotfix validation: focused metadata/preflight suite `63 passed, 3 deselected`; three existing Linux-oriented SSH/path transport tests are not local Windows Evidence and remain mandatory in full Linux CI. Portable suite `1176 passed, 5 skipped, 15 warnings` under its existing service/shell exclusions; lightweight checks, Python/YAML/production-script/CI-step Bash syntax and `git diff --check` passed. Native Windows fixture path/CRLF handling was repaired without changing production parsing; copied bytecode caches are excluded from synthetic fixtures. Docker daemon remains unavailable locally; the real root-only Docker test is pending CI. Product denominator/numerator remain `264/578`, non-commercial `264/336`; no additional product AC was closed by this preflight-only correction.
- Validation and Evidence: container-probe local migration/release suite `23 passed`, lightweight CI checks, release/CI shell syntax success. Exact PR CI `33360042003` and Studio/browser CI `33360042022` success; exact merge CI `33360260838` and Studio/browser CI `33360260703` success. Real Docker probe printed `STUDIO_RUNNING_CONTAINER_METADATA_OK` on PR and merge SHA (main job `99390105887`). Regression covers absent old image, container replacement, failed probe and mismatched schema head. Local Docker daemon remains unavailable; runtime-container validation is Linux CI Evidence, not local evidence.
- Verifier-hotfix validation: expected red regression on old script; corrected focused verifier/worker-health/Compose tests `33 passed`, Bash/Python syntax, lightweight checks and diff checks success. Additional existing preflight suite on Windows: `21 failed, 5 passed` due native/MSYS path assumptions and Windows-invalid fixture names; its test/script files match the verified base and are unchanged. This is not passing local Evidence; full Linux CI (including the added real-PostgreSQL predicate test) is required. Native PostgreSQL and Docker daemon are unavailable locally.
- Verifier-hotfix CI: exact PR `ca899051` checks run `33369096462`, Studio/browser run `33369096487` success. Exact merge `1e9cebc4` checks run `33369386542` and Studio/browser run `33369386518` success. Main full suite: `1459 passed, 2 warnings`; log confirms the real-PostgreSQL predicate test and executable verifier/preflight tests passed, not skipped. Owner VPS output now confirms the safe fast-forward and `STUDIO_WORKER_DB_ROLE_OK`; subsequent preflight failure is separate from role verification.
- Blockers: reviewed API/web delivery and authenticated post-deploy verification on the existing canary remain. Proving the repaired output-confirmation path end-to-end would require a new bounded STT call; no such call is authorized. Worker remains gracefully stopped. Residual diagnostic boundaries prohibit raw provider/credential/document content in evidence. Post-deploy metadata writer remains absent; no post-merge metadata-only follow-up PR or direct push is allowed.
- Unverified assumptions: provider account `character_count/character_limit` остаются provider-defined period units и не равны минутам Scribe; product usage endpoint возвращает credits, которые нельзя безопасно распределить по job или перевести в invoice amount без additional provider Evidence.
- Preserved pre-existing changes: `.pytest-tmp-*` directories в основном checkout; текущая Goal их не читает, не изменяет и не удаляет.


## Перенос 2026-09-06: закрытая поставка #301

Исторический текст локального checkpoint сохранён; он не разрешает новую реализацию и не определяет current readiness.


## Current Goal и граница исполнения

Режим: **DELIVERY завершена; ожидание выбора следующей Goal**. Пользователь 2026-09-05 поручил merge и подтвердил включение audio-upload hotfix вместе с документами: «Да делай мердж». Это снимает прежнюю неопределённость publication scope. Следующая продуктовая Goal пока не выбрана.

- **ID / title:** `AUDIO-REFERENCE-UPLOAD-HOTFIX-01` — поставка готового исправления подтверждения audio-reference upload.
- **State:** `DONE` для явно порученного delivery scope: PR #301 merged, post-merge CI/Studio CI/web CD successful, точный deployed web SHA и read-only API health подтверждены, local main синхронизирован. Готовый code commit `d62945912b3e470b2cb8b20912057a4a57c0f6f1` сохранён в истории. Это не присваивает READY всем product AC и не заменяет прежнюю очередь приёмки.
- **Authorization:** исходное поручение исправить audio upload от 2026-09-05; затем отдельные поручения AUDIT/обновить документы и правила; явное подтверждение merge **документов и hotfix** в текущем чате. Ранее разрешённый synthetic silence WAV около 17 МБ уже подтверждал storage/CORS recovery; повторный upload, processing/STT/Google mutation не входят в текущий delivery scope.
- **Встроенная Goal:** активирована и проверена инструментами приложения 2026-09-05; objective — проверка и merge этого batch, стандартная web-поставка/read-only post-checks, sync local main и подготовка вариантов следующей Goal. Активной Goal до этого не было; дубликат не создавался.
- **Scope:** готовый audio multipart hotfix и regression tests; шесть подготовленных документов (AGENTS, README, spec, plan, archive, CI/CD rules); PR в `Just9120/Elevenlabs-API`, applicable CI, merge в main, web CD и public read-only identity/health. Сам текст референса AGENTS сохраняется полностью, проектные пункты только добавляются.
- **Non-goals:** новая продуктовая реализация по findings; изменение workflows/settings/credentials/CORS, backend/worker/migrations/edge; provider/Google/Telegram side effects; удаление пользовательских sources; следующая Goal.
- **Связь с прежними Goal AC:** `ARU-01` — исторически подтверждённая CORS/storage причина; `ARU-02` — bounded same-part reconciliation, остановка при invalid/unavailable status, безопасные сообщения и completed-session handling; `ARU-03` — tests/CI и поставка исправления. Прежний successful synthetic upload остаётся historical Evidence, не выдаётся за повторный LIVE на новой версии.
- **DoD текущего поручения:** согласованный diff проверен; существенные review findings закрыты; required PR CI successful на final revision; PR merged; стандартный web job successful, deployed web SHA совпадает с merge SHA и read-only health/build checks пройдены; local main синхронизирован; факты сохранены в первичных records и локальном durable checkpoint. Приёмка остальных 687 product AC не входит в этот DoD.
- **Required Evidence:** CODE/TEST/FORMAT/LINT/TYPECHECK/BUILD PASS локально; REVIEW self-review PASS; final PR CI и post-merge CI PASS; MERGE confirmed; DEPLOY PASS для web; LIVE PASS в ограниченном scope public web build identity + API health на 2026-09-05 18:00:27 UTC. Исторический real upload покрывает только прежний scenario/revision, не повторялся.
- **Blockers:** перед публикацией актуальных blockers не выявлено. Ранее auto-review отказал в publication из-за scope; новая явная authorization записана выше. Любой новый отказ рассматривается по фактическому результату, без обхода защиты.
- **Stop condition:** после DoD этого delivery поручения остановиться; предложить варианты следующей Goal без её запуска.

### Batch и Validation Plan

Один PR объединяет уже готовый hotfix commit и согласованные документы по явному выбору владельца. Это завершает подготовленное состояние перед новой Goal; новых code fixes в batch нет. Документация описывает весь проект и аудированный backlog, не расширяя hotfix behavior.

| Проверка / риск | Команда / primary record | Среда / этап | Обязательность и текущее состояние |
| --- | --- | --- | --- |
| Reference/routing и AC consistency | Сравнение полного AGENTS prefix и CI/CD §§1–9 с референсами; 687 уникальных AC в spec/plan, 289 source rows, 40 local links | Local worktree перед commit | REQUIRED; PASS |
| Whitespace / patch | `git diff --check`, совокупный diff относительно origin/main | Local pre-commit | REQUIRED; PASS |
| Audio multipart regression | `node node_modules/vitest/vitest.mjs run src/AudioPreparationUpload.test.tsx` из apps/studio | Windows/Node 22, 2026-09-05 | REQUIRED; PASS, 10 tests, без real storage calls |
| Frontend static/build | `node node_modules/eslint/bin/eslint.js .`, `node node_modules/typescript/bin/tsc -b`, `npm run build` | apps/studio, local перед commit | REQUIRED; PASS. Существующий chunk-size warning остаётся F15 |
| Repository / Studio suites | `CI / checks`, `Studio PWA CI / studio`, `Studio PWA CI / browser-e2e` | GitHub Linux, final PR head/test-merge revision | REQUIRED перед merge; PASS на final PR head, точные runs ниже |
| Review | Self-review diff, GitHub comments/conversations/mergeability и фактические protections | Final PR revision | REQUIRED; PASS, final head/base/mergeability и отсутствие review blockers проверены до merge |
| Release | Studio Platform CD selected `deploy-web`, image/commit identity, `/build-meta.json`, `/api/healthz` | production web после merge | REQUIRED; PASS для web, exact deployed merge SHA и public API health. API/worker/migration SKIPPED по scope |
| Human/product scenarios | Новый real upload/capture/provider/export end-to-end и весь audit backlog | По отдельной Manual Validation/продуктовой Goal | Вне текущего merge DoD; прежние ограничения приёмки сохранены |

Будущие условия: CI success → merge → selected web CD success → exact web SHA/read-only health → sync main. Это условия, не прогнозные PASS/READY; второй набор будущих процентов не создаётся. PR/CI/CD records принадлежат ветке `codex/audio-upload-confirmation`; точные IDs записываются после получения и сверяются при AUDIT/RESUME. Post-deploy facts вне records сохраняются в этом локальном tracked файле до следующего содержательного commit, без отдельного служебного PR.

## Active execution checkpoint

- Updated UTC: `2026-09-05T18:01:47Z`.
- Root: `C:/Users/wait9/OneDrive/Документы/GitHub/Elevenlabs-API`; origin: `https://github.com/Just9120/Elevenlabs-API.git`.
- Verified pre-merge base/default: `main@dce709df90d4495f7775be93d631ee9a0d3e6f6d` по GitHub API и успешному `git -c http.sslBackend=openssl fetch origin main`. Разовая настройка TLS backend сохранила certificate verification; repo/global Git config не менялась.
- Working branch: `main`; last verified revision `b8babc257abf7a33cda2df3c36c33570ee043108`. Ветка `codex/audio-upload-confirmation` полностью входит в main; она существовала до этого delivery поручения и сохранена. Все шесть исходных документов и готовый hotfix включены в merged PR. Локальные записи post-deploy/proposed Goal хранятся только в plan.
- Preserved state: existing ignored/inaccessible pytest directories и остальные unknown files не трогались; source/workflows вне готового hotfix не менялись. Tmp diagnostics в ignored `tmp/audit-2026-09-05/` не публикуются.
- Current step: [PR #301](https://github.com/Just9120/Elevenlabs-API/pull/301) MERGED 2026-09-05 17:56:26 UTC; merge SHA `b8babc257abf7a33cda2df3c36c33570ee043108`, final PR head `1c9cab33e6540ef8acf9b7822de07fbad8bb5c69`. Merge выполнен после exact checks SUCCESS и повторной проверки head/base, CLEAN/MERGEABLE, отсутствия review blockers; admin bypass не использовался.
- PR CI на `45801805c8aeb6bdc7baae67af68d9b2e9d2bd73`: [CI 33981927044](https://github.com/Just9120/Elevenlabs-API/actions/runs/33981927044) FAIL в `tests/test_security_policy.py::test_project_spec_owns_durable_colab_security_constraints`: тест ожидает буквальный marker `Baseline repository and Studio CI must remain secretless`. В новой формулировке профиля смысл был сохранён, literal marker — нет. Исходная фраза восстановлена в Project profile; tests и универсальные §§1–9 не ослаблены. [Studio PWA CI 33981927029](https://github.com/Just9120/Elevenlabs-API/actions/runs/33981927029): studio и browser-e2e SUCCESS. После doc correction требуется CI новой revision; прежний FAIL не считается success.
- Local doc-correction validation: `python -m pytest -q --portable -p no:cacheprovider tests/test_security_policy.py` — 3 passed; reference/687 AC/289 sources/40 links consistency и `git diff --check` — PASS. Историческая оценка readiness доступна через Git history; full acceptance numerator тогда не был установлен.
- Final PR validation: `1c9cab33e6540ef8acf9b7822de07fbad8bb5c69`; [CI 33982256655](https://github.com/Just9120/Elevenlabs-API/actions/runs/33982256655) SUCCESS, [Studio PWA CI 33982256604](https://github.com/Just9120/Elevenlabs-API/actions/runs/33982256604) SUCCESS; все три required jobs фактически выполнены, включая browser-e2e. Это исправленная revision; первый failed run сохранён выше как история диагностики.
- Local sync: текущая ветка `main`; HEAD = local main = origin/main = `b8babc257abf7a33cda2df3c36c33570ee043108`. Fast-forward fetch и switch сохранили SHA-256 локального plan. Единственное tracked local изменение — этот durable checkpoint/подготовленный proposal следующей Goal; служебный commit/PR не создаётся.
- Post-merge records для `b8babc257abf7a33cda2df3c36c33570ee043108`: [CI 33982502558](https://github.com/Just9120/Elevenlabs-API/actions/runs/33982502558) SUCCESS; [Studio PWA CI 33982502612](https://github.com/Just9120/Elevenlabs-API/actions/runs/33982502612) SUCCESS; [Studio Platform CD 33982502551](https://github.com/Just9120/Elevenlabs-API/actions/runs/33982502551) SUCCESS, selected deploy-web SUCCESS. API/worker/release-api-migration SKIPPED, это не их deployment Evidence.
- LIVE post-check: Python urllib HTTPS GET с default certificate verification, 2026-09-05 18:00:27 UTC; `/build-meta.json` возвращает `commit_sha=b8babc257abf7a33cda2df3c36c33570ee043108`, `build_id=web-b8babc257abf7a33cda2df3c36c33570ee043108`; `/api/healthz`: `ok=true`, database/Redis reachable, migrations current, schema `0037_ux_audit_controls`. PowerShell TLS client сначала не смог установить HTTPS; это локальное transport limitation, не failure приложения; certificate checks не отключались. Реальный private upload, paid STT, Google mutations и runtime worker identity не проверялись.
- **Next exact action:** владелец выбирает следующую Goal из подготовленных вариантов или задаёт свой результат. До такого выбора новую implementation и provider canaries не начинать. Текущий delivery DoD выполнен; встроенная Goal закрыта через `update_goal(status=complete)`, последующий `get_goal` подтвердил `complete` в текущем чате.
- Primary records до этого batch: PR #300 merged в `dce709df90d4495f7775be93d631ee9a0d3e6f6d`; прошлый main CI/Studio CI successful. Эти runs не заменяют validation новой revision.
- Historical runtime: 2026-09-05 11:03 UTC owner CORS recovery и successful synthetic multipart audio upload на web `dce709df90d4495f7775be93d631ee9a0d3e6f6d`, API/worker `e00febc5f77ebb9bcc8cd797a09ee7c1a94354b7`. Audit public GET позже подтвердили web identity и API health/schema `0037_ux_audit_controls`; private scenarios и worker identity не перепроверялись.

### Локальное обновление repository rules — 2026-09-05

- Основание: пользователь предоставил новые `repository/AGENTS.md` и `repository/ci-cd-rules.md`, поручил заменить старые правила и адаптировать их к проекту. Это отдельная локальная documentation task; предыдущая product Goal не возобновлена, code/workflows/settings и публикация не разрешены этим поручением.
- Результат: после уточнения пользователя root AGENTS содержит полный неизменённый текст нового референса и отдельный §9 с проектными дополнениями; CI/CD §§1–9 заменены новым Safety contract, §10 содержит фактические команды, CI/CD profile, защищённые lanes и durable handoff. Старое имя migration class MANUAL_GATED сопоставлено EXPLICITLY_GATED с сохранением gates. Universal safety policy изменена по этому явному поручению, а не для снятия blocker.
- Сохранены прежние локальные результаты AUDIT в README/spec/plan/archive. В отличие от предыдущего checkpoint, теперь изменены AGENTS и весь CI/CD document. Branch/HEAD не менялись; commit/push/PR/merge/deploy не выполнялись. Built-in product Goal не активировалась: поручена замена документов.
- Validation документации на worktree поверх `d62945912b3e470b2cb8b20912057a4a57c0f6f1`, 2026-09-05: readback и self-review PASS; §§1–9 CI/CD совпадают с новым референсом; четыре проектные lane-секции сохранены с перенумерацией и явным соответствием migration class. Проверены 16 локальных links, 16 profile paths, сохранность README/spec/archive по SHA-256 и отсутствие code/workflow diff. `git diff --check` PASS; `python scripts/ci_checks.py` PASS. Full product suites не повторялись для изменения правил. При source review исключено неподтверждённое утверждение об общем remote deployment lock: найденный flock относится только к backup.
- Размер AGENTS после восстановления полного референса: 127 строк, 24,896 bytes (24.3 KiB); вместе с существующим глобальным AGENTS — 29,298 bytes. Полный исходный файл сохранён byte-for-byte как префикс: удалений и замен в нём нет, добавлен только §9. [OpenAI рекомендует краткие практичные инструкции со ссылками](https://learn.chatgpt.com/guides/best-practices); [32 KiB — default лимит загрузки, а не рекомендуемый целевой размер](https://learn.chatgpt.com/docs/agent-configuration/agents-md). Точного лимита строк эти страницы не задают; global settings не менялись.
- Уточнение пользователя: адаптация AGENTS должна только добавлять проектные строки. Предыдущая версия сокращала формулировки и объединяла разделы; это исправлено восстановлением всего референса без редактирования его текста. Validation: byte-for-byte prefix comparison PASS, ссылки проектного дополнения PASS, общий размер с глобальным AGENTS ниже 32 KiB, `git diff --check` PASS. CI/CD и результаты продуктового аудита этой коррекцией не изменены.
- Documentation task завершена локально. **Next exact action для продукта:** дождаться выбранной владельцем Goal или явного продолжения hotfix.


## UX-STUDIO-20260924 — исторический checkpoint до завершения

Фактическое завершение: PR #309/#310/#311 merged, web/API поставки 35962179284/35966308018/35967953684 PASS; live web 02fc21d. Ниже сохранён прежний pre-merge checkpoint, а не текущий статус.

**UX-STUDIO-20260924 / IN_PROGRESS.** Authorization: владелец 2026-09-24 явно выбрал одной Goal все UX/UI findings F31–F38 предыдущего браузерного аудита. Встроенная Goal активирована. Проверенный base `origin/main` `7d3d609d1dbd5a54b541322eff131cb801966f9c`, main чистый, открытых PR нет, protection/rulesets отсутствуют. Первый branch `codex/ux-core-recovery-20260924` от этого SHA; чужая `codex/audio-upload-confirmation` сохранена.

- Checkpoint 2026-09-24T07:00Z: PR #309 MERGED `0d41180` и web/API CD 35962179284 PASS. Разрешённый владельцем hotfix PR #310 MERGED `44cbd960c72cfe2438646f6c384f2e5a6840943e`: PR checks/studio/browser-e2e и main CI PASS, web-only CD 35966308018 PASS; UI web commit `44cbd96`, API `0d41180`, worker `a56afb8`, schema `0037_ux_audit_controls`. Browser smoke: F31 local synthetic WAV → внутренний переход → тот же доступный blob PASS; F32 ошибка `-` видна рядом с полем с фокусом, без запуска обработки; F33 вертикальное поле и единая подпись, F38 понятный счётчик, F34 исходные имена в истории PASS. Completion audit обнаружил остаточный F34/PUX-07: внутри группы исходное имя показывается дважды — в заголовке элемента и в карточке. Новый узкий branch `codex/ux-history-dedup-20260924` от актуального `origin/main` `44cbd96`; локально PASS 752/752 Vitest, повторный affected App 239/239, ESLint, TypeScript/Vite/PWA build, lightweight checks и `git diff --check`. PR, remote checks, merge, CD PENDING. Main **355/676 READY (52,5%)**, без commercial **355/435 (81,6%)**, denominator прежний: PUX-07 остаётся IN_PROGRESS до устранения дублирования. Чужая ветка `codex/audio-upload-confirmation` сохранена.

- Результат/DoD: F31–F38 закрыты воспроизводимым поведением и подходящими автоматическими проверками, AP-17/PUX-06/PUX-07 переоценены; PR #309 и разрешённые узкие hotfix PR проходят применимые CI/review, объединены и применимая web/API поставка с revision/health/safe smoke подтверждена. Готовность по main до Goal 353/676 (52,2%), без commercial 353/435 (81,1%); незамерженный прогресс отдельно.
- Scope Goal: F31/F32/F35/F36 — сохранность локального результата, видимая validation, начало нового раздела, focus Drive dialog; F33/F34/F37/F38 — компоновка форм, различимость истории, время диагностики, ясность подписей. PR #310 закрыл residual F33/F38 и доставил source names для F34; последний hotfix убирает дублирование source name внутри группы, сохраняя номер задачи и видимое имя в JobCard. Для F37 проверены timezone/источники. Non-goals: новая функциональность поиска/хранения, платные provider calls, OAuth/permissions, настройки pipeline и коммерческий контур.
- Validation Plan: REQUIRED local — focused React/Vitest regressions для затронутых сценариев; `apps/studio`: `npm run lint`, `npm run test -- --run` (если npm wrapper не передаёт `--run`, эквивалент Vitest CLI), `npm run build`; root: Python syntax compile для первого PR, `python scripts/ci_checks.py`, `git diff --check`, review links/AC. REQUIRED remote — API integration regression с изолированными PostgreSQL/Redis в Studio CI, `CI/checks`, `Studio PWA CI/studio` и `Studio PWA CI/browser-e2e` на актуальном head/test-merge, review и mergeability. REQUIRED after merge — automatic `studio-web` CD на merge SHA hotfix при включённом router, exact deployment/health identity и безопасный browser smoke F33/F34/F38; API, worker и migration CD N/A для hotfix: их код и схема не меняются. RECOMMENDED — браузерный keyboard/viewport replay без пользовательских данных. Неуспешные gates исправить в этой Goal.
- Checkpoint 2026-09-24T05:46Z: F31–F38 реализованы в ветке, но остаются OPEN до merge и проверки применимой поставки. F31 local audio result сохраняется при внутренней навигации; F32 ошибочный ввод раскрывает настройки и фокусирует поле с inline/ARIA error; F33 перестроены labels/controls; F34 owner-scoped job DTO добавляет исходное имя и устраняет повтор даты (list eager loading); F35 начало раздела и focus без нарушения keyboard tabs; F36 возврат focus Drive picker; F37 UTC-naive diagnostic timestamps трактуются как UTC и показывают timezone; F38 понятные labels. Локально PASS: 751/751 frontend tests, ESLint, TypeScript/Vite/PWA build, Python syntax и lightweight guards; focused Audio regressions 16/16 после последней правки. Локальный API integration test НЕ ЗАПУЩЕН: он требует отдельные PostgreSQL/Redis и миграции; системный Python имеет несовместимые pydantic/core, попытка isolated uv на Windows упёрлась в сборку http-ece/доступ к temporary files. Полный API integration — обязательный Studio CI gate. Далее self-review/diff, commit, initial push одного PR; remote checks/review, merge, web/API CD PENDING.
- PR #309, head `bda2a67`: `Studio PWA CI/studio` и `browser-e2e` PASS; `CI/checks` run 35961544955 FAIL: 1759 Python tests PASS, один explicit browser DTO key-contract ожидал прежний перечень без нового безопасного `source_names`. Контракт обновлён с сохранением отрицательных проверок owner/credential/worker authority и требует повторного CI на новом head. Merge/CD PENDING.


## Исторические checkpoints до04Nov2026

Исторические pre-merge срезы и прежние оценки перенесены04Nov из dashboard; IN_PROGRESS/PENDING внутри них описывают тот момент, не текущую Goal. PR340/341/342/343/344/345 подтверждены MERGED primary GitHub records; current source main597443b содержит все merge revisions. Актуальные AC, findings, ограничения и единственная Current Goal — в [dashboard](delivery-plan.md). Исходные Evidence/решения сохранены, новые операции этим архивом не разрешаются.

### AUDIO-QUALITY-PROGRESS-TRIM-20261028 — IN_PROGRESS

Основание: явное поручение владельца28Oct2026 — сначала точечно обновить исходный Google Doc, затем реализовать согласованные новые требования единой Goal. Doc `1uaYvnqpbns_iyHTtQDZYjNYygT4ikUhmhuhRDWySrzI` обновлён с revision guard; readback подтвердил все3 изменённых раздела (провайдеры, визуальная обрезка, прогресс), остальные разделы сохранены. Revision `AHj4eMTtyuH0DJOk9_16Rda3GchxdZw-YldmFAyfJ7mRCpj5_hnttmoD6Mrll45uIVkd2zGLQakvZCLw-QOvOdF_xfF53H7bcvLPvTSkw80`.

Base `4fb10e22b8b432b0b447153356fee27262aee562`, branch `codex/audio-quality-progress-trim-20261028`, primary worktree. Свежая main, open PR0, strict `ci-required`, admin enforcement и approvals0 подтверждены Git/GitHub28Oct. Прежняя PERSONAL-INTEGRATIONS завершена PR344/main4fb10e2: CI40221169464/40221580616, web/API40221625314 и worker40222115972 SUCCESS; нижний pre-merge checkpoint исторический, не новая незавершённая Goal. Игнорируемый LOCAL-BACKLOG и другие локальные материалы сохраняются.

Scope/DoD: AQP-01..14 в [расширениях](spec/extensions.md#эпик-audio-quality-progress-trim-01--провайдеры-прогресс-и-обрезка); один основной PR, совместимые API/schema/recipe и synthetic regressions, self-review, current required CI/review, merge, exact-revision web/API/worker delivery на Contabo и безопасные health/readiness checks. Ключи новых сервисов вводятся отдельно штатным защищённым способом; незаполненная конфигурация не означает готовую интеграцию.

Non-goals: коммерция, automatic voice identity, F62/редакторская очистка лекций, изменение старых транскриптов, новый backup scope, платные STT/Live/повторы, многодорожечный монтаж и удаление нескольких внутренних участков. Benchmark методика не даёт разрешения расходовать средства; существующие Google/ElevenLabs credentials не переиспользуются для новых сервисов.

Progress checkpoint28Oct: additive migration0044 добавляет nullable bounded work snapshot; JSON содержит только stage/counters/unit/timestamps/lease generation/sequence. Main-thread writer с точными owner/lease/status/cancel guards, throttling; byte materialization, FFmpeg media time, audio analysis и provider/output phases подключены. Старый checkpoint contract сохранён, новый optional work поддерживает старый ответ API; UI не создаёт второй общий meter и не считает heartbeat продвижением. Root focused progress/media62 PASS; audio processor/download37 PASS; final guard/progress12 PASS, UI32 PASS, TypeScript/lint PASS. Это локальная candidate, не runtime Evidence. Migration/PG rehearsal, новые providers, VAD/local trim и current CI/CD ещё PENDING.

VAD/local checkpoint28Oct: WebRTC VAD2, pinned wheels2.0.14.post1, mono16kHz30ms streaming frames с bounded8-frame queue, intervals≤512 и явным truncation. Только local worker decode, STT/network для разметки не используются; silence/amplitude не объявляются voice detection. Legacy/browser-local metadata показывают speech analysis unavailable. Native synthetic silence/cancel + collector bounds и affected processor18 PASS. Browser-local trim использует original ordered PCM до silence, не изменяет inputs; после применения результат пересобирается из исходных File в текущей вкладке, остаётся WAV. UI/local audio44 PASS, TypeScript PASS. Provider accounts/ключей у владельца пока нет: явное уточнение28Oct — подготовить проект к их добавлению; live configuration/paid tests не входят в текущий DoD, неподключённые providers не выдаются за готовые к запуску.

| Validation Plan / риск | Проверка, cwd и environment | Этап |
|---|---|---|
| Новые провайдеры и credential boundaries | Root focused synthetic transport/capability/owner/credential/worker/output tests: ограничения, несовместимости, invalid/partial response, cancellation, safe retry и отсутствие неявного fallback | REQUIRED local + Linux CI |
| Обрезка и recipe | Root focused audio tests с synthetic media: точные границы, original timeline, concat/channels/silence, bounds, copy/conversion, reload/regeneration/cancel; local-browser path и память ограничены | REQUIRED local + CI |
| Progress | Root/component tests: измеряемые этапы/байты/медиавремя, неизвестный STT progress, lease/cancel/reload, устаревшие ответы и terminal states; без искусственного timer-percent | REQUIRED local + CI |
| UI | `apps/studio` focused Vitest, lint, TypeScript/build; keyboard/touch/zoom/overflow, empty/error/pending states; synthetic browser suite текущего CI | REQUIRED before merge |
| Repository | Root `python scripts/ci_checks.py`, `git diff --check`, IDs/source trace, self-review; migrations/release rehearsal при изменении schema | REQUIRED before push + applicable CI |
| Delivery | Runbook: current CI → merge → applicable exact-main web/API → graceful worker rollout; обязательный environment approval, runtime identity/schema/health/readiness | REQUIRED after merge |
| Реальные STT/benchmark | Нового бюджета нет, старые разрешения не переносятся; оплачиваемые requests не запускаются | N/A для текущего плана проверок |

Checkpoint28Oct: исходный документ обновлён и проверен. Первый локальный блок — additive trim recipe, owner/preview/download-slot guards, original concat timeline до silence, явный format, editor/zoom/range fields и regeneration sample. Backend targeted104 PASS; после service guard test и estimate refactor core/service68 PASS; UI30 PASS, TypeScript/lint/lightweight/diff PASS (Windows synthetic, real FFmpeg sample tests включены). Temp runtime tests перенаправлены в ignored workspace cache из-за запрета записи системного Temp. AQP-08/09/10/13 IN_PROGRESS, локальная обработка/VAD/progress/providers ещё PENDING; новых READY0/14. Следующий шаг — detailed durable progress, speech analysis и provider contracts. Новые credentials/аккаунты ещё не установлены; это блокирует только зависимые live calls. Source main не изменён, CI/PR/CD PENDING.

Checkpoint28Oct перед initial push: Google source edit/readback завершён. Реализованы AQP-01..14: optional Mistral/Gemini/VoiceKit batch adapters и encrypted forms; explicit capabilities/limits/no fallback, source-preserving trim до silence/concat/channel processing, local WAV re-render из originals, waveform handles/keyboard/zoom, local bounded VAD, measured durable progress и generation guards. Для Gemini encrypted result/temporary-file receipt сохраняются до подтверждённой очистки, idle retry удаляет только exact owned file; потеря ключа не выдаётся за cleanup PASS. Unknown price не трактуется как ноль. Новых кабинетов нет; live provider calls не входят в DoD по уточнению владельца.

Validation28Oct:393 focused backend tests PASS (new transports, worker dispatch/cache/recovery, capabilities, metadata, analytics, Yandex, audio/core/processor/download/media);46 отдельные service/schema/VAD/provider-media cases PASS. Vitest selected284:283 PASS, один obsolete provider-specific label исправлен и точечно PASS; TypeScript/ESLint/build PASS. Новые API tests и responsive browser regressions для390/768/1280 добавлены, REQUIRED Linux CI/release-rehearsal PENDING. Lightweight/diff checks PASS. Новая зависимость VAD pinned, constraints регенерируются штатным pip-tools7.6.0; paid APIs/security scans не запускались. Ни synthetic CI, ни отсутствие ключей не доказывают живую совместимость сервисов.

Read-only Contabo baseline28Oct: checked-out4fb10e2, PostgreSQL0043, API health current/reachable, worker healthy/isolation_match=yes, active transcription/audio jobs0. Other server projects не изменяются. Перед rollout заново проверить отсутствие конфликтующей поставки/активных задач, drain, затем protected signed backup/direct0043→0044/API и совместимый worker; reviewer approval обязателен. Root credential/environment config сохраняются.

Scope readiness28Oct на проверенном origin/main4fb10e2 с добавленными14 требованиями: project454/697=65.14%, current personal454/473=95.98%; новая AQP epic0/14 на main. Предыдущая оценка454/683=66.47%, personal454/459=98.91%; изменение вызвано расширением denominator, старые AC не понижены. Незамерженный candidate:468/697=67.14%, personal468/473=98.94%, AQP14/14 CODE READY; CI/merge/delivery остаются незавершёнными. Числитель454 подтверждён текущими реестрами: Colab32 + Studio355 + extensions50 + shared technical17; backlog commercial224 исключён только из personal. Это scoped пересчёт, не новый полный аудит.

Дополнительная validation28Oct:68 focused UI/contract tests PASS после trim-reset regression;38 schema checks PASS,1 platform-dependent SKIP.43 shell preflight cases локально не стартовали из-за недоступного дочернего Git Bash executable в Windows sandbox; это не PASS, их Linux CI остаётся REQUIRED. Оба constraints регенерированы pip-tools7.6.0: только pinned webrtcvad-wheels и generator header, существующие версии сохранены. Credential validation errors редактируются без input/context, чтобы не возвращать присланный секрет; HTTP regression добавлен в PostgreSQL suite.

Следующий шаг: self-review завершён, один initial push/PR; дождаться required CI/release rehearsal на актуальной revision, исправить подтверждённые failures в том же PR, merge и applicable delivery. Закрытие Goal только после runtime identity/schema/health/readiness. Документы не предсказывают успех gates.

PR345 создан и прикреплён к задаче; head c49ff9f. Initial CI40660858128: Studio build/Vitest PASS; root2470 PASS/9 FAIL, browser20 PASS/1 FAIL/9 not-run, release rehearsal FAIL. Подтверждённые причины собраны в один correction batch: актуальные schema/work/analytics expectations, корректный CSRF/invalid-Base64 fixture, human audit label для trim, устранение дублирующей волны (обе duration values сохранены), перенос cleanup import в реальную worker main. Последнее объясняет остановку candidate worker при rehearsal; новый meaningful main startup/shutdown regression предотвращает повторение. Local59 backend/entrypoint/audit/transport +30 UI PASS, build/TypeScript/lint/lightweight/diff PASS. Assertions/CI gates не ослаблены. Следующий required run — только после grouped correction push; предыдущий PASS отдельных jobs не заменяет gate новой revision. PR merge и CD ещё не выполнялись.

CI40662417583 на50ad7d1: root/checks PASS, Studio PASS, release-rehearsal PASS (isolated API/web/worker0043→0044 и compatible rollback). Browser26 PASS/1 FAIL/3 not-run: downstream progress recovery assertion всё ещё искал прежние provider-specific названия этапов. Все8 таких ссылок в browser suite заменены актуальными generic labels, проверки active/waiting/cancel/recovery сохранены без ослабления. Lightweight/diff/discovery30 tests PASS. Финальный grouped push той же PR345, новый required CI PENDING; production не изменён. Protected approval, merge и delivery остаются обязательными.

### PERSONAL-INTEGRATIONS-20261025 — IN_PROGRESS

Hotfix checkpoint25Oct: основной PR343 merged57bbaea, required PR/main CI40204854889/40205373688 PASS; web40205411519, approved signed backup/migration/API40205930427 (0042→0043), final API config40218446867 и worker40218653631 SUCCESS. Contabo API/worker exact57bbaea, roles/schema/readiness/isolation PASS. Владелец сохранил отдельные секреты, подключил Disk и включил owner-bound Telegram; один явно тестовый Telegram send получил положительный ACK точного private recipient. Legacy migration toggle снова false. F79 выявлен обязательным Disk smoke: create-only DOCX и повторный readback PASS, download FAIL unsafe_redirect; оба synthetic файла удалены permanently с metadata404. Диагностика установила302 downloader.disk.yandex.ru → mds.storage.yandex.net →200 с точным SHA256; OAuth не передавался content hosts. Hotfix остаётся частью этой Goal, отдельный необходимый PR после merge разрешён прежним решением владельца; base57bbaea, branch `codex/yandex-download-redirect-20261025`. Scope: только ограниченные download redirects между уже разрешёнными content hosts, без OAuth/ослабления URL, size/hash/owner guards; новые features, paid STT, изменения старых документов, migrations/settings вне scope. YD-02/03 source intake и YD-05/09 DOCX hash-download fallback затронуты F79; OAuth YD-01/08 отдельно подтверждён. Реестр main57bbaea454/459 не учитывал новый дефект: независимый baseline450/459 personal=98.04%,450/683 overall=65.89%; candidate восстанавливает4 AC до454/459=98.91% и454/683=66.47%, denominator не изменён.

Hotfix Validation Plan / DoD: REQUIRED local `pytest -q tests/test_studio_yandex_disk.py tests/test_studio_yandex_docx_output.py` (synthetic redirects, no OAuth per hop, forbidden hosts/scheme/userinfo/port, loops/limit, cancellation, size/hash), affected access/source/output tests, `python scripts/ci_checks.py` и `git diff --check`; REQUIRED current Linux CI/review → merge → API CD → graceful worker drain/compatible worker CD → exact runtime/readiness. REQUIRED новый уникальный Disk synthetic DOCX: create-only/repeat/download/full text/hash и permanent cleanup/readback, без платного STT. До успеха Goal не DONE. Внешний browser tool недоступен; OAuth/opt-in выполнены владельцем, UI coverage ограничено existing synthetic browser/CI и server readback. Raw logs и capability URLs не сохраняются в repository.

Hotfix local validation25Oct:66 transport/DOCX regressions PASS, включая разрешённые301/302/303/307/308 и три перехода, relative Location, forbidden host/scheme/userinfo/port/fragment, missing Location/cycle/limit, cancellation до следующего запроса, size/hash mismatch.75 downstream connection/source/audio/output tests PASS (Windows synthetic SQLite/network). Local проверки используют synthetic configuration и не вызывают provider. Required current CI/merge/CD и исправленный production smoke ещё PENDING; ни новый код, ни результат поставки не предсказываются.

Scope update25Oct before PR344 merge: владелец дополнительно поручил исправить вёрстку Disk picker и предоставил два текущих browser screenshots1230×956 (sources/source-folder). F80: navigation накладывается на первую строку, search input стоит сбоку от подписи, clipped list прячет primary confirmation; fixed-grid Google dialog использован без его scroll-content/footer structure. Исправление ограничено Yandex component/scoped CSS: пять явных областей, search/sort toolbar, отдельная navigation, scrollable body, постоянный footer, aligned row actions и selected state; Google layout/API/business rules не меняются. Known main readiness с F79/F80:449/459 personal=97.82%,449/683 overall=65.74%; дополнительно затронут YD-04, новых AC нет. Candidate возвращает454/459 после проверки исправлений. Local component19 + selected App1 PASS, build/TypeScript/ESLint PASS; browser geometry regression добавлен для3 modes×390/768/1280px, footer/list visibility/overflow/order/scroll/focus, REQUIRED CI PENDING. CI40219642364 PASS относится только к30615ec до UI changes и не принимается за gate новой revision. Browser/CUA/Windows tooling падает при инициализации; production screenshots предоставлены владельцем, локальная прямая Playwright-сессия не запускалась без отдельного согласия. Current required CI, web/API/worker delivery и final Disk smoke остаются обязательными.

CI correction25Oct:40220719285 на853fdc0 — checks/studio PASS, browser390px PASS;768/1280px FAIL strict last-row viewport ratio0.985795, при видимых header/search/navigation/footer. Сохранённые synthetic CI screenshots просмотрены: субпиксельная граница scroll body подрезает рамку последней строки. Scoped6px inner padding сохраняет полную строку и focus ring; assertion ratio1 не ослаблен. Build/TS/lint/diff PASS после CSS correction. Следующий шаг: один grouped push той же PR344, required current CI, merge и web/API/worker delivery. Canary cleanup обоих созданных объектов подтверждён, paid STT не запускался.

Основание: владелец25Oct2026 согласовал единый scope и один PR с поставкой на Contabo: полный personal Яндекс Диск, Telegram уведомления, адаптация мониторинга Cloudkeep, отмена automatic voice identity и email/Web Push task notifications, документированное восстановление через VPS без почты. F62 и personal security email F66 остаются DEFER; commercial не реализуется. Built-in Goal ACTIVE. Base `815b829e8d51dbea073d62e914887593d64895f6`, clean main/origin main; branch `codex/personal-integrations-20261025`, primary worktree. Strict `ci-required`, admin enforcement, approvals0, open PR0 подтверждены. Unrelated `codex/audio-upload-confirmation` и LOCAL-BACKLOG сохраняются.

Scope/DoD: YD-01..05/07..09 и связанные UXN-04/PM-05 — отдельное owner-scoped подключение Disk, files/folders, DOCX destination, bounded quota/access/revocation handling, безопасный export-only recovery без нового STT и незаметной перезаписи; Telegram JOBNOT-05/06 — owner binding, success/error delivery, дедупликация/retry и отсутствие влияния сбоя канала на результат. OBSERV-18/REC — регулярный backup принадлежит Cloudkeep; отключённый Studio timer не создаёт ложную12h тревогу, неизвестное внешнее evidence не считается success; protected pre-migration R2 snapshot сохраняется. Personal recovery — проверенная процедура администратора VPS без SMTP, без сброса пароля/2FA реального владельца при проверках. Отменённые VID и task Web Push/email AC сохраняют ID/основание исключения из denominator; diarization и ручные имена SP остаются. Актуализировать source trace, процедуры и устаревшие F04/F05/F68 по PR338/341; source Google Doc уже scoped edited25Oct с revision guard/readback, остальные требования сохранены.

Non-goals: F62 lecture/cleaned experiments, paid STT/retries, personal security email F66, commercial, voice matcher, изменение старых транскриптов, перенастройка остальных Cloudkeep jobs/targets и удаление существующих backups. Административное восстановление существующего owner не выполняется. Секреты/пользовательский контент в репозиторий не попадают.

| Validation Plan / риск | Tool / cwd / environment / ожидаемый результат | Этап |
|---|---|---|
| Disk OAuth и данные | Root focused synthetic OAuth/client/source/export tests; CSRF/session/state/owner, refresh/revoke, pagination, unsafe URLs, quota/permission/conflict, idempotent retry; без реальных провайдеров | REQUIRED local + Linux CI |
| UI и notifications | `apps/studio` focused Vitest, lint/typecheck/build; settings/source/destination/error/recovery, Telegram-only configuration и pending states. Root Telegram binding/outbox/worker tests, synthetic transports | REQUIRED local + current CI/browser |
| Backup/recovery | Root alert/CLI tests: external pending/failure/stale evidence не подменяется green; отключённый legacy timer не создаёт stale alert; pre-migration guards неизменны. Recovery synthetic credentials, session/trust revocation, audit и negative cases | REQUIRED local + Linux CI |
| Документы/совместимость | Root `python scripts/ci_checks.py`, `git diff --check`, source/spec/plan IDs/relative links и self-review; affected DB/schema/API consumers | REQUIRED before push |
| Delivery | Current CI/review → merge → applicable exact-main web/API → graceful compatible worker rollout; runtime/config owners, required environment gates, identity/schema/readiness/public health; bounded authorized notification/integration checks | REQUIRED after merge |

Checkpoint25Oct: локально готовы backup policy и operator recovery: Cloudkeep owns regular freshness/target monitoring; Studio сохраняет только alerts фактически сообщённого failed pre-migration backup, не оценивает external health по своему audit stream. Operator CLI требует интерактивное подтверждение существующего admin/email, скрытый пароль, атомарную ревокацию sessions/trust/reset capabilities; TOTP сохраняется либо явно retire-ится отдельным флагом/подтверждением с отдельным audit event. Root focused owner-recovery/operational-alert suite32 PASS (Windows/SQLite/synthetic data); lightweight checks/diff PASS. Production owner не изменялся. Остальная реализация/CI/PR/CD PENDING. Следующий шаг — Telegram-only UI/delivery и Disk integration. Внешние настройки Disk OAuth и bot credentials подтверждаются отдельно до dependent live checks; отсутствие конфигурации не выдаётся за live PASS. Предыдущие pre-merge checkpoints ниже исторические; PR342 API/worker40091778574/40092000906 и main CI40091427515 SUCCESS на815b829 подтверждены.

Telegram checkpoint25Oct: task UI предлагает только Telegram, retired enable API возвращает410, legacy flags не создают sends. Claim привязан к operator-configured owner UUID и активному аккаунту; чужой owner/opt-out подавляет intent. Подтверждение доставки требует positive Bot API message ACK, HTTP200 недостаточно. Root52 focused tests PASS (20 notification +32 alert/recovery); UI3 focused Vitest, TypeScript и ESLint PASS. API contract changes требуют PG Linux CI; реальные сообщения не отправлялись. Владелец явно разрешил публичную ссылку на список транскрибаций после automatic approval rejection; она добавлена только для текущего production origin, без filename/transcript/job ID. Bot8819983827, username VoiceOpsStudioNotifyBot; token/chat ID и Disk OAuth credentials ещё не предоставлены. Зависимые live checks остаются PENDING.

Disk transport checkpoint25Oct: новый bounded REST transport и29 synthetic tests PASS: canonical paths, pagination/empty folder, normalized auth/quota/conflict/rate/redirect errors, allowlisted signed-content hosts без переноса OAuth headers, streamed size/hash verification, create-only upload и exact metadata readback. Контракт сверяется с официальной REST документацией/SDK; Google-specific nested fields syntax не используется. Это foundation, ещё не подключённый end-to-end сценарий; OAuth/registry/schema, source/output/worker/UI integration PENDING. Реальные Disk calls/user files не использовались.

Disk connection/source checkpoint25Oct: additive schema0043_yandex_disk (owner/account resource handles, encrypted connection, output provider defaults Google; source-time constraint widened), PKCE/session-bound one-use OAuth, refresh/revoke и optimistic post-I/O guards реализованы. Callback не отменяет logout/disconnect/newer start; local disconnect стирает credentials до попытки provider revoke. List/select/intake API сохраняет CSRF и не выдаёт tokens; selected-version intake идемпотентен в рамках проекта, empty folder selection поддерживается. Batch materialization/availability и audio preparation читают Disk c size/hash/budget/cancellation guards; logical deletion не удаляет external files. Root focused244 PASS, ещё4 новых audio cases PASS; connection/schema group54 PASS включая legacy SQLite upgrade/downgrade. Windows temp требует owned workspace TEMP/TMP; PostgreSQL enum/grants и role/release rehearsal REQUIRED в Linux CI, локально не подтверждены. Lightweight/diff PASS. UI, DOCX output/reconciliation/export-only recovery, final source/spec/plan consolidation и CI/PR/CD остаются PENDING; intermediate commits не объявляются всей Goal READY. Следующий шаг — DOCX destination и recovery, затем UI и сквозные tests. Реальный owner/файлы не изменялись.

DOCX foundation checkpoint25Oct: deterministic OOXML renderer сохраняет весь canonical text, title/metadata/body hierarchy и speaker14pt/body11pt; opaque receipt находится только в hidden custom property. Create-only upload проверяет path/type/size и SHA256, при отсутствии strong metadata hash читает содержимое в hash sink; совпадение filename или одного MD5 не считается результатом. Повтор после lost ACK не пишет второй файл, изменённый документ даёт conflict.18 synthetic formatting/upload/receipt tests PASS; additive migration0043 получила nullable path/hash/size receipts и provider discriminator с fail-closed downgrade, два SQLite legacy/current roundtrip checks PASS. Pipeline/reconciliation/UI ещё не используют этот foundation; YD-05/07/09 остаются IN_PROGRESS, не READY. Commit4d41809 сохраняет предшествующий OAuth/source этап; весь scope остаётся в одной локальной ветке, initial push/PR ещё не выполнен. Следующий шаг — интеграция destination provider и persisted receipts с worker/reconciliation/cache-only retry, затем UI и текущие CI/CD gates.

Pipeline checkpoint25Oct: provider-bound Google/Disk destinations и persisted create-only DOCX receipts подключены к worker, owner-scoped reconciliation и accepted-output catalog/history/lifecycle. Quota/permission/timeout сохраняют результат; confirmed absence допускает export-only retry, modified file не перезаписывается, missing grant не считается отсутствием документа. Сохранённый Yandex STT восстанавливается без source bytes/key/provider request. Владелец отдельно разрешил очищать временный Yandex text только после подтверждённого полного документа либо явной terminal cancellation; metadata/accounting сохраняются, historical sweep отсутствует. Output persistence/text retirement атомарны при rollback. Focused worker/output/cache/OAuth group245 PASS; additional catalog/attention/source-cleanup/manifest group115 PASS (overlap не суммируется), Windows SQLite/synthetic transports. Новые PG API batch/provider tests и migration/grants/release проверки остаются REQUIRED CI. Backend foundation63bdaf9; текущий diff ещё не поставлен. UI находится на отдельном локальном этапе той же ветки/будущего одного PR.

UI checkpoint25Oct: settings connection/reconnect/disconnect c authoritative readback, source files/current folder/empty selection, sort/filter/pagination, DOCX destinations per row/fragment и audio input подключены к Disk API. Reload сохраняет namespace папки, duplicate/preflight signature включает provider; recovery сообщает selected Disk и не обещает Google Doc. Picker отменяется Escape/close, сохраняет порядок файлов, re-reads source-folder и возвращает focus. Focused UI94 PASS, App selected5 PASS including actual picker→verify→preflight без job creation; broader UI834 unchanged cases PASS и4 старых copy assertions исправлены/перепроверены. Build/TypeScript/ESLint PASS; existing bundle-size warning сохранён, не runtime failure. Browser layout, Linux PG/current CI и live external checks остаются PENDING. Root245/115 groups не суммируются. На VPS установлен root-only interactive staging helper с hash/readback; runtime .env не менялся, credentials вводит владелец вне чата. Source requirements повторно прочитаны и изменены ровно3 paragraphs с revision guard/readback: personal console recovery, deferred system mail, Cloudkeep/RPO UNSET/RTO4h; остальные374 paragraphs сохранены.

Pre-push checkpoint25Oct: branch `codex/personal-integrations-20261025`, base815b829, backend23e796f/UI f65c342; one PR, no initial push yet. Fresh origin/main unchanged, open PR0; current/previous readiness и716 stable IDs/local links проверены, unrelated branch/LOCAL-BACKLOG сохранены. App/connection/picker/reconciliation259 PASS; focused UI94 PASS overlaps; Chromium synthetic layout3 PASS390/768/1280, build/typecheck/lint/lightweight/diff PASS. Backend245 + downstream115 + security/alerts/roles subset89 PASS overlap; migration release14 локально не исполняются из-за unavailable Git Bash child,6 Linux/PG-specific cases skipped. Linux PG enum/grants/full release rehearsal и current required CI REQUIRED/PENDING, checks не ослаблены. Следующий шаг — initial push/один PR, collect/fix actual CI failures, merge только после gates. Delivery: signed direct0042→0043 protected migration с pre-migration R2 backup, compatible API, old worker drained/stopped, reviewed config/roles, compatible worker, exact identities/readiness/public smoke. Legacy backup timer не включать; Cloudkeep targets не менять. Реальные owner password/2FA/STT/documents не менялись; stage helper не включает transport. Owner credential staging, private Telegram chat binding и Disk consent/live smoke PENDING. F78 описывает отдельные Cloudkeep retention/RPO/restore gaps, не обещает их устранение текущим мониторингом.

PR343 checkpoint25Oct: initial head6db4cf7, CI40203997538 — release rehearsal и Studio/browser PASS, root2370 PASS/21 FAIL. Причины batch собраны: model snapshot принимал только Google URL; legacy adapter/DTO fixtures не имели output_provider; preflight head остался0042; role verifier fixtures ожидали6 вместо7 gates; новым audit events не хватало human labels. Diagnostic assertion failure оставлял dependency overrides и порождал downstream auth/E2E failures. Исправлены provider-specific snapshot/legacy fallback, isolated test overrides, exact0043 preflight, Disk privilege negative gate и audit labels; assertions не ослаблялись. Новая local API regression проходит mixed Google/Disk create+DTO+replay, backend affected173 PASS и API/diagnostics/ports45 PASS в canonical synthetic origin/cookie environment. Lint/lightweight PASS; Linux shell/PG cases REQUIRE current CI. Один grouped push в тот же PR; merge/CD ещё PENDING. Public Telegram URL разрешён отдельно, staging credentials ещё не подтверждён. Production revision815b829/healthy/clean подтверждена read-only, secrets не выводились.

### CONCISE-METADATA-20261024 — DONE по первичным records

Primary readback25Oct: PR342 merged815b829, CI40091076292, API40091778574 и worker40092000906 SUCCESS. Нижние pre-merge ограничения относятся к историческому checkpoint, Goal не возобновляется.

Основание: владелец24Oct2026 поручил оставить provider/model/language, остальное только при необходимости, исправить текущие Google Docs и шаблон, сохранить совместимость каталога; один PR и поставка на VPS. Built-in Goal ACTIVE. Base `b323cfd799a5be6a8ac44efa3971faf31eabf1af`, clean main/origin main, branch `codex/concise-transcript-metadata-20261024`; unrelated `codex/audio-upload-confirmation` и LOCAL-BACKLOG сохранены. F04/F05 завершены PR341: CI40080175294/main40080567821, API40080899685, graceful drain40081054570, worker40081158508 SUCCESS; exact b323cfd/schema0042/role/readiness подтверждены. Исторический checkpoint ниже не возобновляется.

Scope/DoD: компактный header provider/model/language; без UUID/recipe JSON/diarization boolean и дублирования даты из title. Существенные clip/timeline/concat/transformation особенности остаются понятным текстом; uncertain speaker note сохраняется. Владелец уточнил: только16 ранее исправленных созвонов, остальной архив не менять. Existing documents меняются guarded scoped edits без изменения речи/меток/форматирования. Catalog читает legacy и compact headers, не требует удалённых полей, standardization не возвращает технический шум; legacy dates без даты в title остаются доступны. Связи/даты/рецепты в Studio не удаляются. AC PB-08/09/10, PD-04/05/06/12/13/14 уточняются без новых ID/denominator. Non-goals: paid STT/retries, speaker remapping, provider/config/schema/workflow changes, отложенные Яндекс Диск/почта/commercial/voice identity.

| Validation Plan / риск | Tool / cwd / environment / результат | Этап |
|---|---|---|
| New output / conditional provenance | Root focused job Google Docs / transcript document tests, synthetic SQLite/fake Google; minimal header, clip/preparation notices, immutable model and owner guards | REQUIRED local + CI |
| Catalog compatibility / no body loss | Root focused catalog scan/standardize/source-authority tests; legacy + compact, optional dates, idempotent standardization and unchanged speech | REQUIRED local + CI |
| Existing Docs | Google Drive/Docs native reads + requiredRevisionId edits + readback; only metadata ranges, speech and speaker notes identical | REQUIRED before DONE |
| Local gates | Root `python scripts/ci_checks.py`, `git diff --check`, self-review and spec/plan trace | REQUIRED before push |
| Delivery | Current required CI/review → merge → API CD → graceful drain/compatible worker CD; Contabo exact revision/schema0042/role/readiness and synthetic format smoke, no provider calls | REQUIRED after merge |

Checkpoint24Oct: code commit586c32d implements compact new output and backward-compatible catalog/standardizer, with immutable internal provenance guards unchanged. Local188 focused tests PASS (152 output/format/source-authority/reconciliation/persistence +36 pure catalog/dry-run/migration; synthetic SQLite/fake Google). Extended PostgreSQL-dependent tests unavailable locally; exploratory combined run produced service setup errors, not PASS, and remains REQUIRED in Linux CI. Lightweight/diff checks PASS. Self-review: date recognition only suppresses duplicate display and does not establish source authority; existing visible date mismatch still checked; ordered concat filenames and timeline/clip/processing warnings retained; repeat standardization idempotent. Contabo preflight PASS: API/worker exact b323cfd/schema0042/roles, healthy single worker/image/isolation match; no conflicting run, migrations disabled. Native snapshots of all16 owner-selected Docs inspected: each ordinary header has Provider/Model/Language/Speakers/Source only. Planned edit removes only two paragraphs after compatible API/worker delivery, preserves full speech, labels/notes/styles, requiredRevisionId and readback. PR/current remote checks/merge/CD/16 edits remain PENDING. Next: one initial push/PR, current gates, merge/API/worker, then guarded Docs edits. Baseline and candidate scoped statuses remain total453/692 READY=65.46%, personal448/459=97.60%;9 refined existing AC confirmed by local code/tests, no new IDs or denominator; unchanged AC reuse prior Evidence, not a full audit.

### YANDEX-F04-F05-20261024 — IN_PROGRESS

Основание: владелец24Oct2026 выбрал F04/F05 единой узкой Goal, один PR и поставка на VPS. Built-in Goal ACTIVE. Base `f0c93e0b43d84c989c406f9c7f6dbe034e70bb0f`, clean main/origin main; branch `codex/yandex-f04-f05-20261024`, существующий primary worktree. Проверены strict ci-required/admin enforcement, reviews0 и отсутствие открытых PR. SECURITY-FIVE завершена PR340: final CI40076369294/main40076703568 PASS, approved signed backup/migration/API40078200233 и worker40078807238 SUCCESS; exact f0c93e0/schema0042/readiness/role/isolation PASS, migration toggle restored false, own branch/staging removed. Исторический checkpoint ниже не возобновляется.

Scope/критерии закрытия: F04 — REST int64 numeric strings и legacy numeric values нормализуются без потери word timing и nested channel tags, включая finalRefinement и сохранённый terminal result; невалидные индексы/таймкоды/probability не становятся допустимыми значениями или unhandled exception. F05 — каталог и selection validation честно отражают отсутствие diarization в интерактивном Yandex REAL_TIME, wire options остаются REAL_TIME/SPEAKER_LABELING_DISABLED; batch capability/ElevenLabs/обычный Live сохраняются. Затронутые AC: MC-08/09, YANDEX-01/02/05, STTPRO-05 (6); YANDEX-03 проверяется как совместимость существующего READY. Denominator не меняется.

Non-goals: Яндекс Диск F02 и personal email F66 остаются отложенными; commercial/voice identity, новый FULL_DATA Live, платные calls/retries, user documents, migrations/settings/workflows не входят в Goal. Прямые API schemas24Oct сверены с provider adapter: getRecognition AlternativeUpdate/channelTag, int64 strings и LanguageEstimation probability; speaker labeling FULL_DATA-only. Внешние документы — данные, не полномочия.

DoD: два finding закрыты code/negative и legitimate regression Evidence; один PR/current required CI/review PASS и merge; exact merge API/worker delivered на Contabo167.86.68.98 по existing operations, schema0042 unchanged, role/isolation/readiness/public health PASS; own branch/temp cleanup. Live provider canary N/A: не нужен для parser/capability correction и не разрешён.

| Validation Plan / AC / риск | Tool / working directory / environment / ожидаемый результат | Этап |
|---|---|---|
| F04 / MC-08, YANDEX-01/02/05 | Root `pytest -q tests/test_studio_yandex_transcription.py`: synthetic REST camel/snake final/refinement, numeric/invalid boundaries, deferred completion/persist/reload без resubmit; fake network only | REQUIRED local + CI |
| F05 / MC-09, STTPRO-05, YANDEX-03 compatibility | Root `pytest -q tests/test_studio_stt_provider.py` и targeted `tests/test_studio_api_core.py` catalog scenario; provider catalog/selection, relay wire options в Yandex suite и ordinary Live | REQUIRED focused local + applicable Linux CI |
| Compatibility / UI API | Existing provider contracts/realtime tests и affected API tests; frontend consumers получают unchanged boolean shape, no frontend behavior change planned | REQUIRED local relevant + full selected Studio/browser CI |
| Local gates | Root `python scripts/ci_checks.py`, `git diff --check`, self-review callers/normalization/persisted replay; synthetic configuration | REQUIRED до initial push |
| Delivery | Exact-main CI → applicable API CD → status/drain/manual compatible worker; schema0042, image/runtime identity, role/isolation/readiness, bounded no-paid smoke | REQUIRED после merge через contabo-vps; no new migration |

Checkpoint24Oct: implementation F04/F05 code2/2 и шесть затронутых AC READY в локальных commits854c0d7/7151628. Combined focused root suite193 PASS (Windows Python3.12/SQLite/synthetic HTTP/gRPC/credentials, no external calls); lightweight checks/diff whitespace PASS. Catalog API integration в tests/test_studio_api_core.py требует isolated PostgreSQL/Redis и выполняется REQUIRED в Linux CI, локально не выдаётся за PASS. Self-review: common parser boundary/sole transport caller, bounded numeric conversion исключает bool/non-finite/overflow; nested tags имеют приоритет, missing timing не выдумывается; persist/reload сравнивает timing/speaker без submit; Live remains REAL_TIME, batch retains FULL_DATA. No schema/config/workflow/frontend runtime changes. Следующий шаг: один initial push/PR, current required CI, merge, API CD и graceful compatible worker rollout, bounded identity/schema/role/isolation/synthetic smoke; до этого Goal не DONE. Unrelated codex/audio-upload-confirmation сохраняется.

Baseline24Oct/f0c93e0: personal442/459 READY (96.30%), total447/692 (64.60%). Незамерженный candidate: personal448/459=97.60%, total453/692=65.46%; шесть существующих AC изменили status, denominator unchanged, прочее Evidence переиспользуется после проверки unchanged paths. Это scoped пересчёт, не новый full audit. F02/F66 остаются отложенными прямым решением24Oct; оставшиеся11 personal AC относятся к этим областям.

### SECURITY-FIVE-20261024 — IN_PROGRESS

Основание: владелец24Oct2026 поручил исправить все пять findings локального deep scan одной Goal/одним PR, начать с migration bundle и довести до Contabo VPS. Built-in Goal ACTIVE. Base `858f0a81a6c7ef425ea4c54ee12e2673d394b43c`, clean main/origin main; branch `codex/security-five-findings-20261024`. GitHub protections: strict `ci-required`, admins enforced, approvals0, open PR0. Предыдущая WORKER-RELIABILITY завершена PR339; исторический pre-merge checkpoint ниже не возобновляется.

| Stable scan finding | Приоритет / confidence / Evidence на base | Действие и критерий закрытия |
|---|---|---|
| `csf_81860525e89f7e45e17636fe` | Medium / HIGH; migration wrapper принимает caller bundle/checksum, меняет origin/main и root-exec runner | FIX: независимая подпись exact repository/commit/target/bundle до изменения refs/exec; malicious descendant, другая подпись и metadata mismatch отклоняются; approved bundle проходит |
| `csf_4cad8491958c267ada7237d3` | Low / HIGH; security_email/job_notifications SMTP_SSL без verifying context | FIX: оба implicit TLS sender проверяют CA/hostname; invalid certificate не допускает AUTH/send; STARTTLS и отключённая почта сохраняются |
| `csf_80d2ffe71d5169d9881bbd16` | Low / HIGH; TOTP verification не потребляет counter | FIX: durable atomic consumption для login/reauth/enrollment/disable, конкурентный replay отвергается; следующий code и recovery остаются рабочими |
| `csf_4edee3c08c2498dad21db502` | Low / MEDIUM; локальный Colab bridge GET mint без browser authority | FIX: post/capability boundary до token factory, защита rebinding/cross-origin; legitimate local/Colab proxy получает новый token, unauthorised requests вызывают factory0 |
| `csf_1d65ce1f40b1c92f2dca0ec9` | Low / MEDIUM; BYOK429 открывает shared provider/mode circuit | FIX: quota/account failures не блокируют другого owner, включая legacy persisted429; genuine service failure circuit сохраняется, batch/realtime/relay используют общий enforcement |

Источник Evidence: completed local deep scan24Oct2026 baseline858f0a8, два независимых Standard прохода; исходники без runtime/production exploitation. Полный отчёт хранится вне repository. Scope включает эти пять boundaries, regression tests, минимальную additive schema для TOTP, delivery signing configuration и canonical procedures. Non-goals: новый аудит/scan, paid calls, commercial features, включение personal email, перенос на Cloudflare, user data/старые транскрипты, ослабление gates или ручные SQL resets. Findings не создают новые AC/denominator. Baseline readiness и затронутые AC пересматриваются по финальному diff/Evidence; старый PASS не доказывает исправление этих дефектов.

DoD: пять критериев подтверждены security trigger и legitimate controls; один PR, final required checks/review PASS, merge; exact merge API/worker/schema и installed root migration wrapper/signing trust подтверждены на Contabo167.86.68.98. Migration — protected lane с новым backup/direct-successor/required reviewer approval; worker status→drain→deploy, no automatic retry/force kill. Signing key создаётся отдельно от SSH, private key только protected GitHub environment; VPS получает public trust key. Нельзя выполнить новую schema release старым неподписанным wrapper.

| Validation Plan / риск | Проверка, tool/working directory/environment | Этап / обязательность |
|---|---|---|
| Bundle authority | Root `pytest -q tests/test_studio_migration_release.py` и executable hostile/approved bundle cases, synthetic Git/keys/fake runner; syntax bash и workflow selection/contract tests | REQUIRED focused local где поддержано; Linux CI до merge |
| SMTP | Root focused security_email/job_notifications tests: verified SSLContext, failed handshake без AUTH/send, STARTTLS controls; fake SMTP only | REQUIRED local + CI |
| TOTP | Root account-security/API regressions, matched counter boundaries, replay across consumers, isolated PostgreSQL concurrency/migration; exact schema release rehearsal | REQUIRED local applicable; PG/rehearsal Linux CI |
| Realtime bridge | Root `pytest -q tests/test_realtime_static.py`: synthetic factory, missing/wrong capability, rebinding/foreign origin, valid local/proxy, fresh token; no provider/network external calls | REQUIRED local + CI |
| BYOK | Root stt-provider/API/Yandex focused tests: quota isolation, existing persisted429, genuine outage cooldown/recovery, all direct callers | REQUIRED local + CI |
| Local gates/review | Root `python scripts/ci_checks.py`, `git diff --check`, fresh read-only boundary investigation + one candidate bypass/regression review | REQUIRED до initial push |
| Delivery | Existing exact-main CI→protected backup/migration/API→drained worker; installed signature trust/wrapper checks, API/worker identity/schema0042/readiness/role/isolation, bounded no-paid smoke | REQUIRED после merge; live exploit/realtime/STT N/A, не нужны для safe delivery |

Checkpoint24Oct: реализация5/5 code READY, один PR340/head60db429, required CI40075895698 SUCCESS:2205 Python tests PASS, все6 POSIX hostile/approved signed-bundle tests PASS, PostgreSQL exactly-one TOTP/auth-route replay и two-owner quota isolation PASS; Studio build/container/browser и schema release-rehearsal PASS. Independent read-only candidate review не нашёл concrete bypass/regression. Focused affected local suite291 PASS/6 POSIX SKIP, Windows Python3.12/SQLite/synthetic data; старые shell release cases локально не стартовали из-за отсутствующего Git Bash binary, их Linux CI PASS. Lightweight checks/diff whitespace PASS. Fresh Contabo read-only: deployed source858f0a8 clean, old root wrapper hashf09296b7, OpenSSL3.0.13; все пять Compose services healthy, signing trust ещё отсутствует. Финальный docs status/Evidence commit не меняет исполняемый code; его current revision checks остаются REQUIRED/PENDING до merge. Wrapper/public trust bootstrap и backup/migration/API/worker CD ещё не выполнялись. Следующий шаг: дождаться final revision gates и merge PR340, установить reviewed wrapper+public key независимо от untrusted bundle, required environment approval и0041→0042/API/worker delivery. Providers/paid calls/user data mutations не выполнялись.

Scoped readiness пересчитана24Oct по проверенному origin/main858f0a8 и уточнённому PWASEC-13: **446/692 READY=64.45%; current personal441/459=96.08%**. Незамерженный PR340 candidate60db429 с CI40075895698 восстанавливает PWASEC-13: **447/692=64.60%, personal442/459=96.30%; Goal code5/5**. До merge эти значения не объявляются готовностью main. Один существующий AC был возвращён IN_PROGRESS и подтверждён исправлением, denominator неизменен:716 stable IDs минус24 ALIAS/SUPERSEDED; personal исключает224 commercial backlog и9 deferred SP-01..05/VID-01..04, сохраняя17 READY shared technical EVC. Старый WK checkpoint430/451 ошибочно исключал shared technical вместе со всем commercial-файлом и не отделял deferred voice; он не переносится как актуальная оценка. Остальные AC используют прежнее unchanged Evidence, это scoped пересчёт, не новый полный audit.

### WORKER-RELIABILITY-20261024 — DONE по первичным records

PR339 merged858f0a8, final CI40029247548/main40029848055 PASS; API40030448317, graceful drain40030653602 и worker40030822929 PASS. Fresh bounded runtime readback: exact858f0a8 API/worker, schema0041, role/isolation/readiness healthy, expired processing leases0. Ниже сохранён исторический pre-merge checkpoint; его ACTIVE/PENDING относятся к моменту записи, Goal не возобновляется.

Основание: владелец24Oct2026 выбрал WK-01..WK-06 единой узкой Goal, один PR и поставка на Contabo; Cloudflare исключён. Built-in Goal ACTIVE. Fresh base/main `8c25efa627b6eeebf13e87e26161e65a96975942`, clean branch `codex/worker-reliability-wk01-wk06-20261024`, existing worktree. GitHub: open PR0, main strict `ci-required`, admins enforced, approvals0; unrelated branch/materials сохраняются.

| Finding / приоритет | Критерий закрытия / AC | Статус / Evidence |
|---|---|---|
| WK-01 · FIX P1 · HIGH | JOBREL-04: bounded locked sweep expired processing leases реально вызывается worker; безопасное requeue либо completed/cancelled/attention required по durable evidence; uncertainty никогда не разрешает новый STT/Google create | READY candidate0d7e902 + reviewed stop-boundary diff; local real entry safe/uncertain/cancel/active PASS; PostgreSQL skip-locked/rollback/batch-limit PASS in CI40028316121/checks (aggregate failure below). Base defect: recovery available, worker claim absent, retry job_not_failed, cancel processing |
| WK-02 · FIX P1 · HIGH | Drain посылает SIGTERM, ожидает безопасный выход; истечение времени наблюдения не посылает SIGKILL, не разрешает deploy и оставляет явный incomplete статус | READY candidate0d7e902 + reviewed client hard-timeout diff; Linux fake Docker exit0/timeout/no-kill/abnormal PASS in CI40028316121; real waiting-client timeout regression added, final required CI PENDING; base TTL3600+60 vs FFmpeg7200 |
| WK-03 · FIX P2 · HIGH | Очистка/notifications/alerts имеют независимые bounded проходы во время основной обработки; work classes получают конечную очередь без постоянного приоритета audio | READY candidate fe5b822 + reviewed diff; independent serial housekeeping with own sessions, fairness rotation and active-boundary graceful join; deterministic thread tests PASS; base busy jobs3/background0 |
| WK-04 · FIX P2 · MEDIUM | Readiness не остаётся ready бесконечно при остановке main loop: heartbeat учитывает его activity и известные bounded operation deadlines; законные долгие этапы не считаются зависанием; никаких automatic paid retry/restart | READY candidate fe5b822; main-thread context/deadline gates runtime heartbeat, fake clock long FFmpeg/stall + independent thread tests PASS; no schema or automatic restart |
| WK-05 · FIX P2 · HIGH | До STT cancel/lease проверяется между chunks и при ожидании FFmpeg; дочерний процесс/streams очищаются, отмена никогда не начинает STT | READY candidate fe5b822; fresh authority checks rate-limited1s, cancellable250ms child wait/reap + stream closure; boundary cancel test asserts provider calls0; real synthetic decoder regressions PASS |
| WK-06 · FIX P2 · HIGH | Unknown failure сохраняет allowlisted exception type, stage и opaque correlation context; реальные handlers это сериализуют, не включая exception text/traceback/секреты/контент | READY candidate fe5b822; allowlisted JSON formatter emits exception class/stage/UUID; real handler test excludes secret payload and traceback PASS |

Scope: runtime worker, существующие processing/recovery/cancellation boundaries, operational drain, focused tests и canonical docs. Non-goals: Cloudflare/другие platforms, commercial/Yandex features, provider tuning, старые Google Docs, paid canary/scans, production fault injection, массовая переработка/очистка пользовательских данных, изменение required gates. Recovery — выбранное поведение существующих expired processing jobs с сохранением accounting и output authority; никаких прямых SQL resets.

DoD: шесть критериев READY по code и подходящим автоматическим checks; один PR/current required CI PASS/merge; applicable API/worker delivery exact main на pinned Contabo167.86.68.98, schema/role/isolation/health и bounded no-paid smoke. Планируется stateful class NONE/schema0041 unchanged; при необходимости schema/config owner decision не имитируется. Worker rollout status→graceful drain→manual deploy; blocked drain не обходится. Recovery rollout не выполняет платные canary или ручные reset production.

| Validation Plan | Tool / каталог / environment / ожидаемый результат | Этап |
|---|---|---|
| WK-01 | Root focused retry/runner/worker tests, isolated SQLite + required Linux PG/role suite; expired safe/uncertain/cancel/completed outputs, concurrency/fencing, no external dispatch | REQUIRED local до push и CI |
| WK-02 | Existing manage-worker/drain contracts + fake Docker Linux cases: normal exit0, timeout running/no kill, abnormal exit, unchanged image | REQUIRED Linux CI; local available Bash only, отсутствие не PASS |
| WK-03/04/06 | Worker/runtime/health/alerts/notifications tests с fake clocks/events и bounded threads; busy work не блокирует background, graceful join of active background boundary, overdue loop не обновляет runtime heartbeat, long bounded operation и redaction проходят | REQUIRED local + CI |
| WK-05 | Source materialization/media preparation/real synthetic FFmpeg/integrity/orchestration tests; cancel during read/process, cleanup and zero provider calls | REQUIRED focused local; Linux media profile CI |
| Docs/local gates | `python scripts/ci_checks.py`, `git diff --check`, source/self-review, specs/runbooks/findings/checkpoint | REQUIRED до initial push |
| Delivery | Existing CI→merge→API/worker CD; exact revision/schema0041, direct worker role, isolation и no-paid smoke через contabo-vps | REQUIRED после merge |

Checkpoint24Oct: implementation WK-01..06 complete in local commits922c0ce/b5a9f4e/fe5b822 plus reviewed tests/docs diff. Root combined focused suite343 PASS/1 SKIP (PostgreSQL locking unavailable locally), Windows Python3.12 with SQLite/synthetic data and available real FFmpeg. Earlier narrower regressions202 and164 PASS; they overlap and are not summed. Lightweight checks/diff whitespace PASS. PostgreSQL concurrency and Linux fake-Docker drain remain REQUIRED remote CI; current required CI/merge/API-worker CD PENDING. No paid calls, production reset/fault injection or Cloudflare changes. Next: one initial push/PR, required Linux CI, then merge, API CD, graceful drain and worker CD; verify exact revision/schema0041/role/isolation/health before closing. Self-review: expired leases revalidated under locks, unknown paid/output outcomes never dispatch; runtime progress only main context, existing long operation budgets preserved; stop prevents new claims and waits for current background boundary; cancellation applies only before STT/owned child; logging excludes content/secrets/tracebacks.

Readiness baseline24Oct/origin-main8c25efa: all716 stable IDs traced spec↔delivery,24 ALIAS/SUPERSEDED excluded; canonical recorded statuses447/692 READY(64.60%), personal without commercial430/451(95.34%). WK-01 exposes one overstated READY on base(JOBREL-04): independently corrected base446/692(64.45%), personal429/451(95.12%). Candidate restores that criterion only after applicable checks. This scoped recalculation reuses unchanged AC Evidence, not a new full audit; no new denominator from six findings. PR339 opened at0d7e902; CI40028316121: Studio build/container and browser E2E PASS, Python2181 PASS/4 FAIL. Failures isolated to updated fake-Docker argument arity and two old selector fixtures using object() instead of a session; fixtures corrected without weakening production checks. WK-01 PostgreSQL concurrency PASS. Grouped follow-up includes SIGTERM-between-classes guard, fallback analysis deadline, maintenance scan progress, bounded observer CLI kill and real controlled-media success regression. Local follow-up53 PASS plus real-media9 PASS; final aggregate CI PENDING. All six criteria code READY; delivery remains PENDING. Previous Goal DIARIZATION-WHOLE завершена PR338/main8c25efa: CI40014806617/main40015514630, API40015574555, drain40017761455, worker40017882902 PASS; production bounded smoke API/worker exact8c25efa, schema0041/health/role/isolation PASS, old documents untouched. Нижний pre-merge checkpoint сохранён как history.

### DIARIZATION-WHOLE-20261023 — DONE по первичным records

Основание: владелец23Oct2026 поручил узкую Goal одним PR: при диаризации отправлять запись целиком, где возможно, убрать мусор из начала новых документов; старые транскрипции не менять. Built-in Goal ACTIVE. Fresh base `0cf7f72ef8c30bb81467b77ba6ad8cc29078ed43`, clean branch `codex/diarization-whole-recording-20261023`, existing worktree. GitHub: canonical repository ID1212324255, open PR0, main strict `ci-required`, admins enforced, approvals0; unrelated материалы сохранены.

Scope: MC-06 / F68, PB-01, PD-09. Критерии Goal: D01 — новый ElevenLabs job с diarization обрабатывает целую выбранную запись/явный clip в одном запросе в пределах provider file<5GB/duration<=10h и действующих project/source/resource guards; без diarization прежнее разбиение сохраняется. D02 — при превышении whole-request limits безопасное разбиение и part-local labels сохраняются; durable multipart recovery не меняет оплаченный план и не повторяет завершённые части. D03 — новые документы начинают транскрипт с речи, без списка «Спикер N — часть M»; при fallback краткое ограничение остаётся после текста. Non-goals: voice identity/принудительное число участников, новые API/UI controls, изменение limits/resources/timeouts/стоимости, paid canary/retries, редактирование/пересоздание прежних документов, migrations/config/workflows.

DoD: D01..03 подтверждены focused regressions и source review; canonical contract/AC Evidence актуализированы; один PR, current required CI PASS, merge, applicable exact-revision API/worker CD и bounded health/readiness. Stateful class NONE, schema0041 unchanged. Worker только status → graceful drain → manual deploy → image/role/readiness; existing recovery procedure применяется при failed post-check без автоматического provider retry/rollback. Полный текст/идентификаторы пользовательских документов не сохраняются в repository.

| Validation Plan / риск | Проверка, tool / каталог / environment | Этап / применимость |
|---|---|---|
| D01: whole vs split, clip и hard guards | Root `pytest -q tests/test_studio_media_preparation.py tests/test_studio_media_clip.py tests/test_studio_long_media_preflight.py tests/test_studio_transcription_media_integrity.py`; synthetic media/fakes, decoder cases при available FFmpeg | REQUIRED local focused до push; Linux real-media REQUIRED CI |
| D02: routing / paid recovery | Root `pytest -q tests/test_studio_job_elevenlabs_transcription.py`; isolated SQLite/fake providers, durable plan/checkpoints/usage/cancellation | REQUIRED local и existing required CI |
| D03: document format | Root affected Google Docs / speaker assembly tests, no network; transcript starts with speech, note at end, no exhaustive legend, metadata/style retained | REQUIRED local и CI |
| Docs / gates | Root `python scripts/ci_checks.py`, `git diff --check`, self-review; current GitHub `ci-required` | REQUIRED before merge |
| Delivery | Existing Studio Platform CD / Worker Drain, pinned Contabo read-only status/revision/schema/health, manual worker component after drain | REQUIRED after merge; no deployment before gates |
| Paid / old docs | Real ElevenLabs/Google mutations, old transcript repair | N/A: explicitly outside scope |

Checkpoint23Oct: diagnosis of six recent owner documents + scoped read-only production attempts confirmed 5-part/23-label and 2-part/10-label assembly; same `scribe_v2`, ru, diarize=true. F68 reopened narrowly for unnecessary fragmentation and exhaustive prefix legend; no claim of acoustic speaker accuracy without audio comparison. Implementation D01..03 complete. Local validation below; next: initial push/one PR, current required CI, merge and API/worker CD. F68 candidate closure depends on actual gates; no old-document mutation.

Previous rebrand Goal completed: PR337/main0cf7f72; required CI39943830679 and main39950863307, web CD39950923150 SUCCESS; API/worker remain compatible f7f6087/schema0041. The pre-merge checkpoint below is historical, not an active Goal.

Local Evidence23Oct, dirty candidate over base0cf7f72: six focused suites208/208 PASS (SQLite/synthetic provider/Google + real synthetic FFmpeg decode); lightweight repository checks and diff whitespace PASS. Environment: Windows Python3.12, `STUDIO_DATABASE_URL=sqlite+pysqlite:///:memory:`, owned workspace TEMP/TMP and pytest basetemp; initial sandbox Temp permission failures were environmental and resolved with this isolated temp boundary. No production secrets/data/provider calls. Self-review: source validation/whole-source consent precedes whole preference; clip bounds preserved; disabled/Yandex policy unchanged; latest existing multipart plan retains old split, complete checkpoint restoration bypasses STT; no fallback retry after paid failure; only newly formatted output changes. Linux CI/required aggregate and delivery remain PENDING before initial push.

### VOICEOPS-REBRAND-20261023 — DONE по первичным records

Основание: владелец23Oct2026 согласовал единое название VoiceOps Studio и repository `Just9120/voiceops-studio`, затем поручил начать; ручные Google OAuth изменения выполняет параллельно. Built-in Goal ACTIVE. Fresh base/main `f7f608713e4b70484e48b6b1df0641dd3f0a50ec`, clean branch `codex/voiceops-studio-rebrand-20261023`, существующий worktree. GitHub repository ID1212324255, ownerJust9120/admin, open PR0; strict `ci-required`, admins enforced, approvals0, force/delete запрещены. CLI credentials доступны вне Windows sandbox; их значения не фиксируются. Base fetched23Oct; unrelated branch/stash/ignored материалы сохраняются.

Результат: единый бренд для repository/Colab/Studio/GCP display name, публичные информационные страницы для Google Branding и рабочие строгие CI/CD после rename. Один основной PR. Spec: BRAND-01..05, owner decision23Oct. Non-goals: commercial, новые provider calls/scopes в runtime, OAuth client/project IDs, смена домена, удаление архивов/секретов, перенос БД/buckets/volumes, переименование state-bearing VPS directories/Compose/images и исправление отдельного PWA cache finding. Реальные Google grants/Branding/scopes/Publish app меняет владелец; агент сверяет доступное readback и сообщает оставшиеся действия, не выдаёт их за выполненные.

| Критерий | Scope / DoD | Статус |
|---|---|---|
| BRAND-01 | VoiceOps Studio в активных product/repository metadata, документации и launcher labels; ElevenLabs остаётся provider name | READY |
| BRAND-02 | About/privacy/personal-use information доступны без login, содержат фактические Google/data flows и контакты, есть навигация и mobile layout; без invented legal/SLO promises | READY |
| BRAND-03 | CI/CD принимает exact canonical repository, foreign identity отвергается; remotes и installed forced-command wrappers синхронизированы без ослабления gates | IN_PROGRESS |
| BRAND-04 | Persistent/runtime identifiers и existing data сохраняются; Colab сохраняет immutable reviewed ref/hash verification | READY |
| BRAND-05 | GCP display name/actual GitHub identity проверены; one PR required checks/merge и applicable web CD/health/public pages подтверждены; manual OAuth итог отражён отдельно | IN_PROGRESS |

DoD: BRAND-01..05 реализованы, применимые local checks/self-review и exact-revision `ci-required` PASS, один PR merged, применимая поставка и bounded smoke подтверждены. Stateful class NONE, migrations не нужны. Host changes ограничены Git remote и exact reviewed repository-name substitutions в двух установленных root-owned wrappers после merge; target `/opt/elevenlabs-studio`, pinned Contabo167.86.68.98. До смены remote/wrappers — проверить текущие values/hashes, отсутствие active release и сохранить exact recovery copies; permissions/SSH commands/approvals/locks сохраняются. Recovery — вернуть exact прежние remote/wrappers при failed verification; rename/редиректы GitHub проверяются по неизменному ID. Installed wrappers не обновляются candidate/unreviewed source.

| Validation Plan / риск | Проверка, каталог/tool, environment | Этап / применимость |
|---|---|---|
| Trusted repository/Colab | Root: `pytest -q tests/test_ci_validation.py tests/test_colab_launcher_integrity.py tests/test_realtime_static.py`; affected deploy/preflight/wrapper tests используют Linux/bash и synthetic data | REQUIRED local Python focused до initial push; Linux shell REMOTE-ONLY REQUIRED CI, локальная отсутствующая Git Bash usr/bin часть не считается PASS |
| Public pages/no login side effects | Studio: affected Vitest, `npm run lint`, `npm run build`; isolated browser desktop/mobile direct URL/nav/back и отсутствие API/provider calls | REQUIRED local до initial push; existing Studio/E2E CI REQUIRED |
| Docs/metadata | Root: `python scripts/ci_checks.py`, `git diff --check`, active-vs-historical refs/ID/link/self-review | REQUIRED local до initial push |
| GitHub/host/cloud | CLI/plugin exact repository ID1212324255, protections/PR/runs; explicit GCP project read-update-read; pinned SSH wrapper hashes/remote/health | REQUIRED по соответствующему этапу; external writes только выбранного scope |
| Delivery | Exact merged main CI; existing Studio platform CD; web build identity/public pages/PWA/navigation и API/worker unchanged health | REQUIRED remote после merge; не повторять deployment без причины |
| Paid/production destructive tests | STT/Live/scans/restore/delete/runtime Google grants | N/A: вне scope; реальные пользовательские данные не fixtures |

Checkpoint23Oct: branch/base созданы до edits; discovery выявил hardcoded old repository в CI deploy-gate, component remote validation и двух privileged wrappers. GitHub rename выполняется после локальной подготовки и до PR validation; host remote сменяется перед merge/CD, installed wrappers — только exact reviewed main после merge с backup/readback. При ручном rename владельца сначала повторно прочитать repository по ID и сохранить его изменения. GCP target `braided-potion-499918-k4`, project number476316429029; display name на старте ElevenLabs API, ниже записан подтверждённый результат rename. OAuth Console Testing/empty declared scopes известны по owner screenshots; исправление owner-side, не скрытое расширение runtime permissions. Локальная implementation/validation завершена (Evidence ниже); следующий шаг — GitHub rename, initial push/один PR и required CI/merge/CD.

Candidate validation23Oct:39 CI/Colab integrity и62 realtime static Python cases PASS;11 Login/Sidebar/main component cases PASS; lint/build/lightweight/diff checks PASS. Isolated Chromium layout11/11 PASS на390×844/768×1024/1280×720, включая3 новых public direct URL/no API/keyboard/reload/back и существующие main navigation/fragments/history/menu/reset cases. Screenshots public390/1280 визуально просмотрены. Windows shell attempts не исполнили Bash fixtures: отсутствует Git `usr/bin/bash.exe`, WSL fallback недоступен; assertions не менялись, definitive affected shell tests — обязательный Linux CI. Initial sandbox Temp rename отказ Vitest устранён локальный TMP и запуском разрешённых checks вне sandbox, затем11/11 PASS. Логи/скриншоты ignored, не входят в PR.

GCP23Oct: exact project read-update-read подтвердил display name VoiceOps Studio, ID/number прежние. MCP command transport не сохранил пробел в --name и завершился до изменения; выполнен штатный локальный gcloud с тем же profile/explicit project, итог подтверждён. Runtime scopes/clients/billing/IAM не менялись. Colab runtime diff — только docstring/page titles; reviewed immutable ref023f2175cfe0631c6670588075e8329bc0672a14 и expected hashes в launchers проверены по Git object bytes. Self-review сверил no-script public pages/фактические data flows, immutable Colab pins, отсутствие credential/state/schema changes и exact repository guards. Sidebar secondary links сведены к одной ссылке «О приложении», чтобы не раздувать mobile header;9 affected component и3 existing layout cases после изменения PASS. GitHub23Oct read-update-read: repository ID1212324255 теперь Just9120/voiceops-studio; default main и strict ci-required/admin enforcement сохранены, local origin обновлён, fresh origin/mainf7f6087. Осталось: one PR/current checks, merge/host wrapper+remote sync/web CD и owner manual OAuth sync.

### PERSONAL-REVIEW-FIXES-20261018 — DONE по первичным records

PR336 merged/f7f6087; required CI39114120229 и main39114461322 SUCCESS; web/API39114493348, worker39115420877 SUCCESS. Fresh readback23Oct: source/web/API/worker exactf7f6087, health/readiness PASS, schema0041; backup timer active10h и scheduled snapshotc520d51f23Oct07:20MSK подтверждён. Нижний checkpoint сохранён как pre-merge history, не активная Goal.

Основание: владелец 18Oct2026 поручил исправить все проблемы последнего personal review единой Goal, одним PR, начиная с backup и фрагментов. Built-in Goal ACTIVE. Fresh base `b7f9d48136e07d6bcd92eba6f8fba9bd42871b1a`, clean branch `codex/studio-review-fixes-20261018`, один существующий worktree. GitHub readback18Oct: open PR0; main strict `ci-required`, admins enforced, approvals0. Unrelated branch/stash/ignored материалы сохранены. Baseline API/worker b7f9d48, web def1750 (source unchanged), schema0041; runtime healthy. Реальные задачи владельца не изменяются.

Результат: регулярный проверяемый backup с обнаружением просрочки; фрагменты по Q065/Q066; понятные состояния, подтверждение результатов и компактный доступный personal UI. Все14 критериев ниже входят в один основной PR. Non-goals: commercial/Яндекс/voice identity/personal email/cleaned experiment, платные STT/Live/scans, изменение OAuth permissions, production restore/fault injection и удаление пользовательских данных. Новые кебаб-меню не добавляются без подтверждённой пользы; primary/cancel/recovery остаются видимыми.

| Критерий | Finding / scope и критерий закрытия | Статус |
|---|---|---|
| G01 | F77 · P1 FIX · REC-02/04, OBSERV-18: действующий10h backup timer, актуальный подтверждённый snapshot, отсутствие запусков/просрочка12h дают безопасное предупреждение; recovery не запускается | READY |
| G02 | UXR26 · P1 FIX · PS-04/05: каждый фрагмент валиден независимо; пересечения, пропуски и произвольная последовательность разрешены, end-of-file доступен каждому; UI/API/tests согласованы | READY |
| G03 | UXR27 · P2 FIX · PS-03..05: известная длительность подготовленной версии проверяется до подтверждения; неизвестная не выдаётся за проверенную | READY |
| G04 | UXR23 · P2 FIX · PUX-14: восстановленный недоступный источник явно обозначен, не позволяет расчёт и имеет понятное исправление | READY |
| G05 | UXR25 · P2 FIX · AP/PUX-06: после успешного Drive export есть явный статус и прямое открытие; дополнительное меню не скрывает подтверждение | READY |
| G06 | UXR28 · P2 FIX · Q069: preflight показывает конечное название, фрагмент и целевую папку каждого документа | READY |
| G07 | UXR29 · P2 FIX · PUX-14: выбранная batch/Live/maintenance вкладка восстанавливается после reload и back/forward через URL | READY |
| G08 | UXR30 · P2 FIX · UX accessibility: ошибки фрагментов связаны с полями, invalid состояние и keyboard feedback согласованы | READY |
| G09 | UXR31 · P2 REFACTOR · PUX-19: компактная mobile навигация/settings без потери пунктов/focus, поля выше в390×844, нет overflow в390/768/desktop | READY |
| G10 | UXR24 · P2 FIX · PT-02: overview показывает полезную сводку транскрибаций/результатов вместо количества технических Project | READY |
| G11 | UXR11 · P2 FIX: понятные названия действующих audit events и очевидный переход из краткого account journal в полный owner-scoped журнал | READY |
| G12 | UXR10 · P2 REFACTOR: компактные fragment rows с видимыми границами/именем/папкой; дополнительные параметры раскрываются без лишней вложенности | READY |
| G13 | UXR32 · P3 FIX: Live readiness и disabled Start используют одинаковые условия и объяснение | READY |
| G14 | UXR19 · P3 FIX: единое округление кратких duration/reduction и доступные точные значения; ненулевой выигрыш не становится0 | READY |

Evidence findings: browser review18Oct/webdef1750/APIb7, synthetic15s audio→13.226208s, Drive upload/export bytes readback, reload/fragment/keyboard проверки; F77 — host timer LoadState=not-found, root/studio-deploy cron0 и проектные restic snapshots: latest pre-migration11Oct2026/a08b3847 (~160h), scheduled17Jul2026. UI мониторинг не сигнализирует отсутствие расписания; operational_alerts проверяет только последний failed outcome. UXR26 воспроизведён в UI и pure backend validator; Q065 явно допускает пересечения. Confidence фактов HIGH; предполагаемый выигрыш перекомпоновки UXR10/24/31 MEDIUM. Остальные рекомендации приняты владельцем в scope этой Goal, не являются новыми business features.

DoD: G01..G14 выполнены и подтверждены; локальные applicable checks/self-review; один PR, current-head required CI/review, merge, web/API и совместимый worker CD, узкая host backup установка/проверка по существующей процедуре. Секреты/retention/backup repository не заменяются. Никаких migrations без необходимости, обхода Environment gates или metadata-only follow-up PR. После applicable delivery — exact revision/health, bounded read-only UI smoke, safe branch cleanup. Ручная приёмка не gate.

| Validation Plan / риск | Проверка и каталог | Этап / применимость |
|---|---|---|
| Backup/monitoring | Root: affected backup/operational-alert tests; syntax/systemd verification; synthetic no/missing/stale/failure/success и recovery transitions | REQUIRED local до initial push; Linux shell в существующем CI REQUIRED |
| Фрагменты/длительность | Root: affected media_clip/schema/batch_preflight/processor tests; Studio: composer/App component regressions; никаких provider calls | REQUIRED local focused и существующий Linux CI |
| Draft/feedback/navigation/a11y/layout | Studio: affected Vitest, `npm run lint`, `npm run build`; isolated Playwright390×844/768×1024/desktop; menu/focus/reload/negative states | REQUIRED local до initial push; production safe smoke после CD |
| Repository | Root: `python scripts/ci_checks.py`, `git diff --check`, ID/link/diff/self-review | REQUIRED до initial push |
| GitHub/delivery | Existing required `ci-required` exact revision; platform/worker runbooks; backup timer/actual snapshot readback и health | REQUIRED remote; ручные Environment approvals только при фактическом applicable gate |
| Платные/production restore/real phone | STT/Live запрещены последним решением владельца; restore/fault injection вне scope; IAB resize/standalone недоступны | N/A для реализации этих исправлений; ограничения Evidence сохраняются |

Checkpoint18Oct, candidate `7e99510` плюс этот docs commit: G01..G14 по реализации14/14 READY; initial push/PR, required Linux CI и delivery PENDING. Это прогресс candidate, не завершённая поставка. Self-review сверил owner isolation, CSRF/идемпотентность, индивидуальную валидацию интервалов, API совместимость, safe URLs и отсутствие новых paid calls/migrations.

Evidence `V-REVIEW-FIXES-18` (18Oct2026, Windows/Python3.12 и isolated Chromium, synthetic configuration):48 focused Python PASS (media clip, batch projection, alerts, audit taxonomy);119 component/model/formatter cases PASS; App247/247 PASS, после anchor focus дополнительно affected settings/navigation/Live cases PASS; lint/typecheck/build и lightweight repository checks PASS. Playwright8/8 PASS:390×844,768×1024,1280×720, reload/back/main navigation,6 settings tabs, journal anchor раскрыт/focused, menus/Escape, fragment fields/folder disclosures и no document overflow. Высота collapsed fragment202/292/334px соответственно; исходное наблюдение около402px на mobile. Настоящее устройство/standalone/offline и provider calls не проверялись. PostgreSQL/API integration и Linux shell — REQUIRED в CI, локальная Windows проверка их не заменяет.

F77 host remediation18Oct выполнена существующей опубликованной процедурой verified main b7f9d48: root-owned units установлены, timer enabled/active10h, первый scheduled backup SUCCESS11:23MSK, snapshot `2e8f86c5` в прежнем Studio restic repository подтверждён по project tag (age0.01h). Настроен существующий единственный active admin как получатель backup outcome и нового monitor owner, без смены ключей/repository/retention. Root0600 config recovery copies сохранены в `/etc/elevenlabs-studio/review-fixes-20261018`; runtime freshness monitor включится после API/worker CD. Restore не выполнялся, пользовательские задачи/данные не менялись.

Оставшиеся gates: опубликовать один PR; current-head `ci-required` и применимый review; merge; дождаться exact-main web/API, штатно drain→stopped→deploy worker, подтвердить identities/readiness и безопасные UI/backup smoke. При failure исправлять этот PR до merge; approvals не обходить. Платные STT/Live/scans запрещены. Собственные production test objects в этой Goal не создавались; unrelated branch/stash/ignored материалы сохраняются.

### DOMAIN-STUDIO-20261017 — DONE по первичным records

PR335 merged/b7f9d48; main CI39064461850 SUCCESS; component CD39064494660/39065299870/39065490787 SUCCESS. Readback18Oct: API/workerb7f9d48, webdef1750 с новым origin, healthy; Google Picker/export/direct upload и обоих storage boundaries подтверждены безопасным synthetic review. Старый checkpoint ниже отражает подготовку, не незавершённую Goal.

Основание: владелец 17Oct2026 поручил перенос на `studio.cloud-nodes.net`; тот же VPS167.86.68.98 и Google-проект, DNS A уже подготовлен через Cloudflare proxy. Built-in Goal активирована. Fresh base/main `def1750df518dbe269fa20a532900bd63e2dac68`, clean branch `codex/studio-domain-20261017`, один основной PR; GitHub main требует `ci-required`, approvals0, открытых PR нет. Предыдущая UX Goal завершена PR332/333 и поставками: web/API38735693476, worker38736484985, edge38478332090; устаревший нижний checkpoint не означает незавершённую поставку.

Результат: новый canonical HTTPS origin с рабочими API/Google/хранилищем и безопасным переходом со старого адреса. Non-goals: смена VPS/Google-клиентов, перенос/удаление данных, изменение permissions/scopes, миграции БД, платные provider calls, коммерческие функции. Куки/локальные PWA данные между origin не переносятся; нужен новый вход и установка PWA.

| Критерий Goal | Результат / validation | Статус |
|---|---|---|
| D01 | Новый TLS/vhost изолирован от соседних проектов; exact host/headers/health/build identity | IN_PROGRESS |
| D02 | APP_PUBLIC_URL и оба OAuth callback на новом origin; старые Google grants сохраняются; Picker и CORS exact allowlists | BACKLOG |
| D03 | Canonical deployment defaults/examples/probes и эксплуатационная процедура отражают новый адрес | BACKLOG |
| D04 | Старый адрес безопасно направляет пользователя на новый без replay mutation/OAuth credential query; rollback сохраняется | BACKLOG |
| D05 | Applicable local/CI/review, merge, runtime identity/health и browser smoke; сохранены gates/данные/чужие изменения | BACKLOG |

Validation Plan: local `python scripts/ci_checks.py`, affected deployment/header tests и `git diff --check` REQUIRED; Linux shell/CI REQUIRED по impact. Remote: nginx syntax/TLS/headers, origin-only CORS preflight двух buckets, primary/maintenance callback/Picker settings readback, публичные health/build и безопасный browser вход/navigation REQUIRED. Никаких реальных STT/Live, удаления файлов или OAuth scope expansion. Перед переключением — backup exact vhost/runtime config, подтверждение external settings; при fail stop и восстановление прежней конфигурации, без blind retry. Защищённая snippet lane остаётся с Environment reviewer gate, её полномочия не расширяются на vhost. Смена host/origin — отдельно разрешённая операторская процедура этой Goal с точным target.

Checkpoint17Oct: новый адрес DNS/Cloudflare доступен; выделенный HTTP ACME vhost staged, прочие HTTP paths503, старый runtime/main def1750 не изменён и здоров. Выпущен независимый TLS certificate нового host с webroot renewal, expires15Jan2027. Linux nginx syntax обеих candidate-конфигураций и bash syntax release/wrapper PASS; lightweight checks PASS. Windows affected tests44 PASS/6 platform skips; один syntax case локально недоступен из-за отсутствующего Git usr/bin/bash.exe, реальный Linux syntax подтверждён отдельно; полный required CI PENDING. Никакие assertions/gates не ослаблены.

External gates: владелец получил точные project476316429029/client IDs и инструкции добавить новый origin/callback обоим Google clients, website Picker и root authorized domain. Автоматический доступ к Chrome отклонён; владелец выполняет изменения сам. Рабочие R2 credentials не имеют get/put CORS permission; scopes ключей не расширяются. Безопасные OPTIONS обоих buckets пока403/no Allow-Origin, пользователь получил инструкцию append origin без изменения других policy fields/backup bucket. Ни объектов, ни STT/Live вызовов не создавалось. Следующий шаг: source PR/required CI; после owner settings — повторный OPTIONS и staged TLS → проверка/worker drain → точная замена3 runtime settings → API/worker CD → проверка нового origin → старый redirect. До external evidence cutover не выполнять. Readiness baseline personal437/454/full442/687 на def1750, denominator не меняется: только deployment hostname/config этой Goal.

### UX-STUDIO-20261014 — DONE по первичным records

Основание: владелец 14Oct2026 поручил все правки итогового UX/UI-ревью как единую Goal. Built-in Goal активирована и проверена. Base/fresh origin/main `99f174ea4337570ef042bdd8764fbbd4ec4e7478`; отдельная ветка `codex/ux-studio-20261014`, один worktree, tracked state чистый до подготовки. GitHub: открытых PR нет, main требует `ci-required`, approvals0. Unrelated branch/stash/ignored материалы сохраняются.

Результат: рабочее прослушивание аудио, сохраняемые безопасные черновики, понятные ошибки/recovery, удобные списки и мобильные действия. Один основной PR; узкие изменения — локальные commits. Старые исправленные UXR01..13 не реализуются повторно; новые проявления UXR07/10/12 входят в текущий scope.

| Критерий Goal | Scope / результат | Статус |
|---|---|---|
| G01 | UXR20: HTML audio допускает same-origin и локальный blob, остальные CSP ограничения сохранены; реальная проверка плеера | READY |
| G02 | UXR14: owner-scoped audio/batch drafts восстанавливают параметры/строки после reload; File/blob, ключи/токены и секретные адреса не сохраняются; logout изолирует данные | READY |
| G03 | UXR15: удалённую незапущенную строку можно вернуть с параметрами и позицией; feedback соответствует действию | READY |
| G04 | UXR16/21: локальная и серверная ошибки видимы рядом с действием, доступный recovery; показаны известные исходники без private paths; при нескольких файлах точный виновник не выдумывается | READY |
| G05 | UXR07: pagination/filter переводят focus к новым результатам; видимые chips, счётчики и reset; выбранные завершённые задачи можно убрать в историю с учётом partial failures | READY |
| G06 | UXR17: точный переход к раскрытому maintenance-access, возврат к обслуживанию без автоматического OAuth grant | READY |
| G07 | UXR18: документ открывается прямо из обзора, задача — в своих деталях; URL validation/ownership сохраняются | READY |
| G08 | UXR10: компактная история, drawer деталей с Escape/focus return, отдельный mobile presentation; primary/cancel/recovery остаются видимыми | READY |
| G09 | UXR12/19: читаемая стоимость с exact disclosure, ненулевые доли секунды не показываются нулём | READY |
| G10 | Дополнительные правки: массовые действия только для поддерживаемых безопасных операций; inline title для незапущенных строк; sticky action bar без перекрытий; mobile sheet для вторичных действий; empty CTA файлов/словарей | IN_PROGRESS |

Non-goals: уже исправленные findings, commercial/Яндекс/voice identity/personal email/cleaned experiment, палитра команд, новые платные scans, установка PWA и speculative deployment. Сетевые/offline/standalone ограничения остаются Evidence gaps, не выдуманными дефектами. Destructive production tests не выполняются; synthetic проверки используют существующее изолированное окружение. Provider canary только в ранее согласованном бюджете и с точечным удалением собственных test bytes/docs, metadata/расход сохраняются.

DoD: G01..G10 выполнены; применимые local checks/self-review; current revision required CI/review; merge; web/API/worker/edge только по затронутым units, exact identity/health/прикладные smoke и required Environment approval; безопасная очистка своих веток. CSP edge поставка требует действующего reviewer gate, не bypass. Миграция без необходимости не добавляется.

Актуальный реестр UX findings (Evidence: production browser11–13Oct2026/web99f174e; synthetic UI/API tests14Oct в текущем dirty branch; без raw logs/данных):

| ID | Область / влияние | Приоритет / действие | Confidence / зависимость |
|---|---|---|---|
| UXR20 | AP-31: CSP запрещает исправный same-origin/blob audio; ложная подсказка повторной сборки | P1 FIX, G01 | HIGH: policy+runtime header+валидный WAV; protected edge delivery |
| UXR14 | Audio/batch ввод теряется при reload/PWA update | P2 FIX, PUX-14/G02 | HIGH: browser reload; safe draft whitelist |
| UXR15 | Нет Undo строки, stale добавление после удаления | P2 FIX, PUX-15/G03 | HIGH: browser; только незапущенная форма |
| UXR16 | Local decode error вне viewport | P2 FIX, PUX-06/G04 | HIGH: browser; focus только user-triggered errors |
| UXR21 | Audio failure не показывает известные исходники/следующее действие | P2 FIX, PUX-06/G04 | HIGH: invalid synthetic WAV; при нескольких файлах неизвестную точную причину не выдумывать |
| UXR07 (дополнение) | History page остаётся внизу нового набора | P2 FIX, PUX-16/G05 | HIGH: browser pagination; исходный search/autofill исправлен |
| UXR17 | Maintenance recovery не раскрывает нужную настройку | P2 FIX, PUX-17/G06 | HIGH: browser; existing Google authority/consent |
| UXR18 | Нет прямой ссылки на конкретный результат из overview | P2 FIX, PUX-18/G07 | HIGH: browser; validated DTO URLs/project ownership |
| UXR10 (дополнение) | Избыточная вложенность/около700px деталей | P2 REFACTOR, PUX-19/G08 | HIGH наблюдение; MEDIUM ожидаемая польза; измеримый mobile/desktop review |
| UXR12 (дополнение) | Восемь знаков стоимости затрудняют чтение | P3 FIX, G09 | HIGH: browser; exact scalar disclosure сохраняется |
| UXR19 | Ненулевая subsecond reduction показана0:00 | P3 FIX, AP-31/G09 | HIGH:3s→2.2s synthetic output; readable duration |

PUX-14..23 —10 новых AC по явному owner scope, не автоматическое превращение findings в требования. Baseline main99f174e, прежний snapshot427/444 personal и432/677 full относится к прежнему составу; незамерженные10 AC показываются отдельно. Новый main denominator и readiness пересчитываются после merge. Existing AP-31 имеет известное нарушение плеера на baseline; candidate fix требует обязательной проверки и поставки.

Validation Plan:

| Риск / критерий | Проверка / команда и каталог | Environment / этап / применимость |
|---|---|---|
| CSP/audio | Existing security-header contracts; реальный browser playback same-origin/blob | Root targeted Python и Studio browser; REQUIRED до merge/после edge |
| Draft isolation, Undo, errors, drawer, filters, links, costs | Affected Vitest из `apps/studio`; `npm run lint`, `npm run build`; `git diff --check` | Synthetic local REQUIRED до initial push |
| Mobile/keyboard/media | Existing `STUDIO_BROWSER_LAYOUT_ONLY=1 npm run test:e2e` + meaningful regression scenarios | Local isolated desktop1280x720/mobile390x844 REQUIRED; реальные permissions/standalone отдельно PARTIAL |
| API/source error DTO и compatibility | Affected Python tests; полная applicable suite в существующем CI | Synthetic PG/Redis/FFmpeg в Linux CI REQUIRED; Windows portable не заменяет CI |
| Repository conventions | `python scripts/ci_checks.py`, ID/link/diff/self-review | Local REQUIRED до initial push |
| Delivery | Existing platform/edge workflows и runbook, current main/artifact identity, readiness и bounded smoke | GitHub/VPS REQUIRED; remaining included minutes UNSET, speculative reruns запрещены |

Checkpoint14Oct: G01..G10 реализованы в candidate branch, local checks PASS; статус IN_PROGRESS до required CI/review, merge и applicable CD. Local commit58c3b41 — media/cost; следующий согласованный batch — drafts/Undo/recovery/navigation/drawer/bulk UX и scoped API preview. До initial push завершены self-review и локальные проверки, remote CI/merge/CD PENDING.

- Local Evidence14Oct2026: affected UI suite322 cases (nine files; финальные App/JobCard reruns после изменения текста), security-header/source-deletion Python57/57; реальные Chromium media+desktop1280×720/mobile390×844/reset-link4/4. Lint/typecheck/build, lightweight repository checks и diff PASS. PG API integration локально не подтверждена: Windows portable не заменяет Linux PostgreSQL/Redis CI; явный запуск service module прерван до результата, не PASS. Required remote suite остаётся gate.
- Self-review: sessionStorage содержит только bounded owner/project metadata, повторное платное bypass-confirmation сбрасывается; File/blob/keys/tokens/transcript bodies/transport URLs не сохраняются. Undo не создаёт job. Bulk source selection1..50 проверяется API; token связан с точным набором и fresh locked snapshot; CSRF/recent auth и занятые источники сохраняют existing gates. Unknown mutation не повторяется вслепую. Single/all deletion совместимы с прежним API. Drawer освобождает native inertness до возврата focus; mobile меню не скрывает primary/recovery.
- Delivery scope: web и API автоматически после main CI; source_deletion.py — shared worker dependency, требуется existing drain/worker manual lane и exact main identity. Schema0041 unchanged, migration N/A. Edge lane для одного CSP snippet, reviewer Environment gate обязателен; release-enable false до согласованного release window и возвращается false после поставки. Новые paid scans и provider calls не запускались.
- Осталось: initial push/один PR → required exact-revision CI/review → merge → web/API и совместимый worker → protected edge → bounded runtime/UI smoke → cleanup своих веток. Test objects на production в этой Goal не создавались.


Hotfix compatibility14Oct: основной PR332 MERGED/main206c579d77f282e9ada1135d49a2ee807593e51b. CI38477514519 SUCCESS: Python2135, Studio819, authenticated/layout browser17; exact main CI38478146748 SUCCESS с immutable full-PR validation reuse, без дублирования suite. Platform CD38478199729 web/API SUCCESS, worker38478822427 в работе; edge38478332090 фактически ждёт Just9120 approval. Schema0041 unchanged. G01..G09 READY по реализации/CI, delivery Goal ещё не DONE.

При проверке rollout найден UXR22: старый API игнорирует неизвестные query/body source_ids, поэтому web-before-API или rollback может показать global preview как выбранный набор. FIX/P1 в G10/PUX-20; HIGH: static contract и regression legacy/mismatched response. Hotfix делает explicit selection echo, fail-closed клиент до POST; extra поле только для selected preview, прежний all-files payload сохраняется. Миграция/API бизнес-правила удаления не меняются, новый AC не добавляется.

Branch `codex/ux-selected-cleanup-compat`, fresh base206c579, main чистый до начала; необходимый hotfix сверх одного основного PR разрешён владельцем. Local49 source-deletion tests и3 UI selected scenarios PASS, lint/typecheck/diff PASS. Required exact-head CI/review, merge и affected web/API/worker CD PENDING. Merge hotfix только после завершения первой применимой поставки, включая pending edge gate: current-main recheck старого edge run сохраняется. Source headers не меняются в hotfix; повторная edge поставка после него N/A при подтверждённой неизменности snippet.

Validation hotfix REQUIRED: legacy/mismatched preview даёт zero mutation, correct selection подтверждается; old global payload совместим; affected unit/contract/UI + lint/typecheck/build/diff/self-review; полный remote CI; exact-main component delivery/health и bounded safe browser smoke. PostgreSQL/Redis/Linux остаются remote-only, никаких paid/transcript calls, deletion или новых production test objects.

### FINDINGS-UX-20261011 — DONE по первичным records

PR329/330/331, main99f174e и поставка завершены11Oct; source evidence и ограничения ниже сохраняются как previous checkpoint. Старые PENDING строки относятся к моменту подготовки; итог восстановлен по primary records и `.tmp/findings-ux-release-checkpoint.md` вне canonical реестра. Новая Goal не возобновляет старую.

Основание: владелец поручил взять единой Goal все findings, кроме Яндекса, и все UX/UI правки браузерного ревью 11Oct2026. Последующие решения сохраняют F08/F09, F62 и personal email F66 отложенными. Встроенная Goal текущего чата создана и проверена инструментом; ранее BLOCKED на reviewer gate, теперь gate одобрен владельцем и работа продолжается. Инструмент не предоставляет resume; новую Goal не создаём.

- Scope: F48, F67..F76; UXR01..UXR13. UXR04/F74 и UXR06/F75 — одни проблемы, закрываются без дублей. F02/F04/F05 (Яндекс), F08/F09 (voice identity/commercial), F62 (аудит лекций/cleaned experiment) исключены. Решением владельца 11Oct2026 F66: почта для personal отложена; SMTP activation и отправка писем не входят в DoD. Закрытые findings не переоткрываются без нового нарушения.
- Branch `codex/findings-ux-20261011`, base/fresh origin/main `8f622994c65649c88857219481274b50aaf4cace`, 11Oct2026. Main/base совпадают на старте, один worktree; `codex/audio-upload-confirmation` и существующие ignored материалы сохранены. GitHub connector доступен, открытых PR нет. Прямой gh auth недействителен; существующий Git credential helper обеспечивает CLI без раскрытия секрета. Readback11Oct: main strict ci-required(app15368), admins enforced, force/delete disabled, required approvals0. Connector403 не используется как доказательство отсутствия protection. Перед merge повторить primary gates readback.
- Один основной PR: изменения взаимозависимы через source/job DTO, auth/cloud boundaries и общие UI компоненты. Узкие задачи — локальные commits; initial push только после готовности всего scope PR и применимой local validation. Возможные необходимые hotfix после merge входят в Goal.
- Non-goals: новые commercial/voice/Yandex функции, изменения общей safety policy, реальные STT/Live/LLM эксперименты, платные security scans, изменение пользовательских Google Docs, destructive production cleanup/restore. F48 теперь выбран владельцем: immutable reviewed Colab source без изменения стабильного batch/realtime назначения.
- DoD: подтверждены критерии ниже; актуальны связанные AC/findings/Evidence; self-review, required CI/review актуальной revision, merge; exact-revision web/API/worker delivery с действующими gates и safe smoke; безопасная синхронизация main/очистка только принадлежащих Goal веток. F66 отложен владельцем и не блокирует Goal; недоступное восстановление через email не предлагается на форме входа.

| Задача / критерии закрытия | Scope / зависимости | Required Evidence |
|---|---|---|
| G01: До STT проверены audio stream/container/codec/integrity; part-local speaker IDs не обещают общую identity; UI объясняет prepared timeline и перечисляет конкретные missing parts/ranges | F67/F68/F69/F73; MC-01/06/07, UXN-05; immutable part plan/owner DTO | Реальные synthetic FFmpeg negative/positive fixtures, assembly/plan/API/UI regressions; zero provider calls при invalid media |
| G02: Новые transcription inputs/preferences используют 3/7/30; existing expiry/legacy reads сохранены | F75/UXR06; STORAG-06; отдельная audio policy | Policy/API/preferences/expiry regressions, legacy readback |
| G03: DEFER — почта для personal отложена владельцем; собственный домен обязателен для будущих писем. Не предлагать недоступную email recovery на форме входа | F66; SECX-06; решение владельца 11Oct2026 | Existing inactive outbox/reset tests сохраняются; login regression подтверждает отсутствие недоступного действия; SMTP activation и реальные письма не выполняются |
| G04: Auth/cloud/document implementations заменяемы через bounded interfaces, существующие routes/ownership/transactions совместимы | F70; EVC-35/41/43/48 | Alternative fake adapters и contract/API isolation/regressions; imports/registry/self-review |
| G05: Tested compatible API/web/worker rollback после schema/config switch; реальные FFmpeg проверки обязательны в affected CI без дублей workflow | F71/F76; DBLP-08/RELEAS-02; isolated Docker/Linux | Synthetic isolated release rollback rehearsal с identity/health/schema/runtime-role readback, real codec cases FAIL при отсутствии binary в applicable CI, runner-time records |
| G06: Architecture соответствует действующему lifecycle; Colab launcher исполняет immutable reviewed revision | F72/F48 | Relative links/source routing, launcher/notebook identity regressions, документация совместимости и обновления |
| G07: Исправлены mobile layout, picker focus/labels, state-dependent copy, history/document navigation, menu grouping, composer density, audit labels/pagination, cost formatting, expired audio fallback | UXR01..05, UXR07..13/F74 | Component regressions и browser desktop/390x844: отсутствие перекрытий, keyboard/focus, безопасные empty/error/result states; основные CTA/recovery видимы |

#### Validation Plan

Canonical commands/сервисы — [validation](runbooks/validation.md); delivery — [operations](runbooks/studio-platform-ops.md). Synthetic config/data и fake external boundaries; production credentials/data не fixtures.

| AC/риск | Проверка / ожидаемый результат | Tool/каталог/environment | Этап / применимость |
|---|---|---|---|
| Diff/docs/identity | Без whitespace errors, broken relative links, расхождений ID/scope; bootstrap/source refs проверены | `git diff --check`, repository checks по runbook, root/Windows | Local pre-push REQUIRED |
| UI/DTO/menus | Typecheck/lint/build и affected component regressions; доступные имена, Escape/focus, disclosure/navigation, retention/timeline/partial states | npm/TypeScript/Vitest canonical commands, apps/studio, synthetic local | Local pre-push REQUIRED; полный прогон — CI |
| Media/mail/auth/cloud/rollback | Affected Python checks по поведению/границам; invalid source до STT, owner/CSRF, transaction/dedup/expiry, alternative adapters | Focused pytest по runbook, root/synthetic portable; FFmpeg при доступности | Local по риску REQUIRED; PG/Redis/Docker/Linux часть remote-only |
| Executable integration | Required `ci-required` и все applicable root/Studio/browser jobs на актуальном test merge revision; no unexpected skips | GitHub Actions synthetic PostgreSQL/Redis/Linux/FFmpeg | Pre-merge REQUIRED |
| Responsive/keyboard | Desktop и 390x844 safe браузерные сценарии в версии изменённого приложения | CUA/browser и существующий isolated browser E2E, без реальных provider calls | Pre-merge REQUIRED; production bounded smoke после CD |
| Delivery/recovery | Exact merge/artifact web/API/worker; migration/backup gates по фактическому diff; health/version и безопасный smoke | Existing CD/runbooks/VPS | Post-merge REQUIRED; real paid canary N/A без отдельного разрешения |

- Checkpoint11Oct: PR329, candidate c23fdc0a89b6f946e14020598ac74f941eaee62f; required CI38141034993 SUCCESS. G01/G02/G04/G06/G07 code/component/browser подтверждены; G05 isolated release rehearsal PASS: baseline8f622994 → candidate test-merge c1618886fbb798225c564286926277f9ecf1ae9e → baseline, schema0040→0041→0040, API/web/worker identity/readiness, credential revocation и сохранение source metadata. Длительность rehearsal205.66s; production rollback не запускался. Все unreleased schema изменения объединены в один direct additive0041 от0040; production safety gates сохранены.
- CI Evidence11Oct2026: Linux Python2128 PASS, PostgreSQL/Redis/real FFmpeg/migration checks; Studio component/typecheck/lint/build и authenticated browser/layout PASS; ci-required SUCCESS. Source head c23fdc0, проверяемая test-merge revision c1618886. Local Vitest810/810 PASS; browser desktop1280×720/mobile390×844/history/picker/menu/overflow/reset-link3/3 PASS. Windows portable diagnostic не является полной PASS suite: shell-dependent failures проверены отдельным Linux CI. Никаких платных scans/provider calls или production mutations. Included Actions minutes UNSET.
- G03/F66 DEFER: владелец 11Oct2026 явно отложил почту для personal. Код outbox/reset/security events и существующие regressions сохраняются, SMTP disabled; activation не входит в Goal. SECX-06 BACKLOG с сохранением source Q268/S257 и правила собственного домена для будущих писем.
- Delivery11Oct2026 PASS: PR329 MERGED, main5601f1a2567569a9578e8eeb01f079d518d8605b; final CI38141779639/main38142176982 SUCCESS. Web38142204757 exact revision PASS; protected backup/migration/API38142530996 SUCCESS после owner approval, snapshot a08b38474302, direct0040→0041. Worker38149008278 и bounded status38149134335 SUCCESS: identity_match=yes, health=healthy, isolation_match=yes; API health database/Redis reachable, schema0041 current. Миграционный selector возвращён false. No paid canary/provider calls/production test objects.
- Hotfix branch `codex/history-autofill-hotfix`, base5601f1a2567569a9578e8eeb01f079d518d8605b, main/remote/protections/open PR readback11Oct PASS. Production browser UXR07 regression: история автоматически заполнена сохранённым логином, search autocomplete/name отсутствуют и browser autofill=true. Scope hotfix: специализированное имя/отключение autocomplete у поиска; regression проверяет возврат на первую страницу после очистки фильтра; убрать недоступную personal email recovery из Login по решению F66. Reset link processing и inactive backend/schema сохраняются.
- Hotfix Validation Plan: local lint/build, Login/PasswordResetPanel components, existing isolated desktop390x844/history/picker/reset-link E2E и docs/ID/diff checks REQUIRED; актуальный required CI/review перед merge; web-only exact revision CD и production browser empty search/autofill readback REQUIRED. API/worker/schema не меняются — их повторная поставка N/A. No new external/mail/provider calls. Local11Oct2026 dirty hotfix diff PASS: npm lint/build, Vitest Login/PasswordResetPanel8/8, existing browser E2E3/3 (1280×720,390×844, reset-link), lightweight ci_checks, ID/registry reconciliation и git diff --check. Npm argument forwarding отклонён локальным CLI; тот же Vitest из installed node_modules выполнен напрямую. Browser tests не содержат saved credentials: реальное отсутствие autofill проверяется после web CD. Self-review: изменены только search semantics, Login CTA, существующие regressions и scope/evidence документы; backend/schema неизменны. Remote CI/merge/web CD PENDING.
- Осталось: hotfix local validation/self-review → push/PR → required current-head CI/review → merge → web CD → bounded browser readback → safe owned branches cleanup. Ни ожидаемые gates, ни browser autofill исправление пока не объявлены PASS.
- Hotfix330 MERGED/main622430328681e39f62a2a45a6c141d4e520387b8; CI38150165849/main38150503042 и web38150544078 PASS. Production browser readback FAIL для UXR07: autocomplete=off/name уже применены, но сохранённый логин по-прежнему вставлен. Причина подтверждена DOM: неактивная Live-панель оставляет два password-input для external endpoint в общем документе без form owner; в один из них также вставлен сохранённый пароль. Содержимое не выгружалось и не отправлялось; caption/webhook calls не запускались.
- Следующий hotfix `codex/live-endpoint-autofill-hotfix`, base622430328681e39f62a2a45a6c141d4e520387b8: монтировать external secret inputs только в активной раскрытой Live-панели, сохранить их значения в памяти панели при закрытии/смене вкладки; изолировать их в отдельной non-login форме с именами и new-password semantics. Маскирование сохраняется. Это regression UXR07; backend/API/storage не меняются. Также исправить старые агрегаты эпиков по актуальному AC registry, без добавления AC/scope.
- Validation нового hotfix: local lint/build, affected Live component (отсутствие скрытых secrets, сохранение ввода при переключении), existing desktop/mobile E2E, docs/registry/diff REQUIRED; current-head CI/review → merge → exact web CD → actual saved-login browser readback REQUIRED. Платные/внешние calls, изменение сохранённых паролей или settings не выполняются. Local11Oct dirty diff PASS: lint/build, Live component33/33 включая сохранение ввода/zero start, desktop/mobile/reset-link E2E3/3 включая отсутствие password inputs в batch, lightweight checks/relative paths/ID/epic aggregates/diff. Self-review PASS: secret values остаются React state, новые form submit preventDefault и masking не запускают transport; вкладки/recording lifecycle сохраняются. Remote CI/merge/web delivery и actual saved-login browser readback PENDING; предыдущее autocomplete=off readback FAIL не скрыто.

#### Finding Evidence — PR329/330 merge/delivery PASS; UXR07 root-cause hotfix PENDING

PR329 интегрирован и поставлен на main5601f1a; AC и findings сверены с CI и delivery records выше. UXR07 требует narrow browser autofill hotfix. Реестр сохраняет audit Evidence и стабильные ID.

| Findings / UX | Candidate implementation / Evidence11Oct2026 | Оставшиеся gates |
|---|---|---|
| F48 | Immutable reviewed Colab ref/SHA256 до исполнения, integrity/static regressions CI PASS | PR329 merge PASS; реальный Colab runtime не запускался |
| F66 | Transactional encrypted outbox, single-use15min reset, anti-enumeration, bounded retries/TLS/security events, SQLite/PG/fake SMTP/browser PASS. At-least-once transport, не exactly-once | DEFER по решению владельца; future activation вне Goal |
| F67/F68/F69/F73 | Real integrity до STT, part-local speaker namespace, prepared timeline и immutable missing-part intervals; Linux FFmpeg/PG/API/UI regressions PASS | PR329 merge/CD PASS; реальный STT не запускался |
| F70 | Bounded auth/cloud/document ports, alternative adapters, owner/CSRF/transaction compatibility; full Linux API/worker suite PASS | PR329 merge/CD PASS; central App не переписан целиком |
| F71/F76 | Full isolated API/web/worker upgrade/compatible rollback PASS205.66s; mandatory real FFmpeg в affected existing CI, no duplicate codec job | PR329 merge/CD PASS; production rollback не выполнялся |
| F72/F74/F75 | Canonical architecture lifecycle/copy; future inputs3/7/30, legacy expiry unchanged; migration/policy/API/UI PASS | PR329 merge/CD PASS |
| UXR01/02/03/05 | Mobile layout, picker focus, credential labels, favourite/credential/audio menus; primary/recovery CTA visible; component/browser PASS | PR329 merge/CD PASS; safe smoke без paid calls |
| UXR04/06 | Те же критерии F74/F75, без дублей | См. F74/F75 |
| UXR07/08/09/10 | History search/filter/page10, owner-safe primary document, explicit details, mobile picker, source-first composer; component/PG/full E2E PASS | PR329 merge/CD PASS; UXR07 browser autofill hotfix PENDING |
| UXR11/12/13 | Human audit labels/disclosure/pagination, rounded/exact cost, positive expired audio Drive-only fallback; component/browser PASS | PR329 merge/CD PASS; safe smoke без paid calls |


### AUDIT-20261010 — DONE по первичным records

Основание: владелец явно поручил выполнить полный аудит по согласованному плану. Scope — Colab, Studio, API/worker, integrations/data/security/operations/CI; requirements→code и code→current requirements. Разрешены только canonical spec/plan и индексируемые разделы, один docs PR→CI→merge. Код, workflows, настройки, deploy, удаления, provider calls и experiments не входят. Implementation Goal не активируется.

- Branch `codex/full-audit-20261010`, base/fresh origin/main `bc5150eb189b44867101ca45b9da201921a99227`, проверка10Oct2026. Main совпал с GitHub; tracked state до аудита чистый; открытых PR нет. Сохранены прежняя `codex/audio-upload-confirmation`, stash a2169cd и unknown/active ignored материалы. Один worktree. Built-in implementation Goal не возобновлялась.
- Product Google Doc ID из spec прочитан полностью:308 пунктов, modifiedTime27Sep2026 не изменился. Обновлённый аудит prompt ID `1GkDaXtI0uCHcL2mLjsJ9bUPRs7JkNZ4JEYu9_AjdMrc` определяет проверку, не copied repository policy. Discussion cleaned/no_verbatim не даёт согласованной feature.
- DoD audit: source/AC/code/finding reconciliation, readiness и quality review; scoped diff/links/IDs/local docs checks+self-review; один docs PR, актуальные applicable required checks, merge/readback и safe owned branch cleanup. CD N/A: нет runtime change. Непроверенные сценарии не объявлены PASS.
- Checkpoint восстановлен11Oct: PR328 MERGED10Oct08:58:55Z, merge8f622994c65649c88857219481274b50aaf4cace (GitHub primary readback). Docs delivery завершена; runtime/CD N/A. Findings и аудиторский baseline ниже сохранены, следующий scope выбран владельцем как FINDINGS-UX-20261011. Included Actions minutes UNSET; paid scans не запускались.

### Предыдущая implementation Goal DELIVERY-METADATA-CLEANUP-20261006 — DONE

Восстановлена по PR327: merged `bc5150eb189b44867101ca45b9da201921a99227`06Oct2026; G01..G08 выполнены. CI37500894207 и main37502013651 SUCCESS; protections readback10Oct PASS; web/API CD37502621690, worker37504355706 и read-only status37505410061 SUCCESS. API/worker/web current identity10Oct совпала с main. F06/F13/F61/F63 закрыты; F04 не входил в её scope. Новую поставку ради статуса не запускали.

PERSONAL-COMPLETION-20261004 — DONE по PR326/merge1937658:105/105 выбранных AC READY на момент closure; CI37430070244/37430070238, protected web/API/migration37430070252, worker37431465267 и status37432061023 SUCCESS. Старые pre-merge PENDING в реестрах заменены primary results; вновь выявленные независимые нарушения F74/F75 возвращают соответствующие AC в работу. Closure предыдущей Goal не доказывает отсутствие новых findings.



## Готовность — main25Oct2026 и personal integrations candidate

Проверенный `origin/main` `815b829e8d51dbea073d62e914887593d64895f6`, fetch25Oct2026; PR342 CI40091076292/API40091778574/worker40092000906 SUCCESS, primary readback25Oct. Это scoped пересчёт, не новый полный аудит: неизменённые AC используют прежнее Evidence с указанными в реестрах ограничениями.

Baseline registry хранит453/692 READY. Независимо учтены четыре переставших быть подтверждёнными Cloudkeep REC-01/03/04/06: актуальная оценка кода/процедур main **449/692=64.88%**, без изменения denominator. Новое расписание не доказывает retention/RPO/restore; F78 сохраняет gap. Historical recorded personal448/459=97.60% не переносится как current.

Candidate23e796f/f65c342 с текущим docs diff: **454/683=66.47%**. Девять критериев исключены явным решением: VID-01..05 и JOBNOT-01..04 SUPERSEDED; manual speaker names/roles остаются. Personal теперь включает все применимые technical EVC-33..48/50 и manual speaker AC, исключает224 commercial-only: **454/459=98.91%**. При том же действующем scope и известных recovery gaps baseline main до реализации даёт444/459=96.73%;10 YD/UXN/PM AC добавляют10 READY. Совпадающий исторический denominator459 имеет другой состав: cancelled notification/identity AC исключены, manual speaker AC сохранены. Изменения менее10п.п.; рост не выдаётся за live verification.

Current Goal:14 затронутых code AC (8 YD + UXN-04/PM-05 + JOBNOT-05/06 + SECX-01/OBSERV-18) candidate READY по source и synthetic checks. Required current Linux CI/review, merge, schema0043/API/worker/web delivery и scoped external setup/smoke PENDING; это не DONE. Personal остаются SECX-06(DEFER) и REC-01/03/04/06(IN_PROGRESS, F78). F62 — внешняя отложенная процедура, не AC приложения.

### Эпики / features

Незамерженный candidate показан отдельно; проценты эпиков не усредняются. Полные статусы и ограничения находятся в indexed registries. N/A означает, что весь эпик явно отменён, не неизвестный denominator.

| Эпик | main READY / active | Candidate READY / active | Остаток candidate |
|---|---|---|---|
| `COLAB-BATCH-01` | 24/24 | 24/24 | — |
| `COLAB-REALTIME-01` | 6/6 | 6/6 | — |
| `COLAB-LIFECYCLE-02` | 2/2 | 2/2 | — |
| `PWA-CORE-01` | 16/16 | 16/16 | — |
| `PWA-USER-EXPERIENCE-02` | 23/23 | 23/23 | — |
| `PWA-UX-POLISH-03` | 7/7 | 7/7 | — |
| `PWA-UX-CONTROLS-04` | 14/14 | 14/14 | — |
| `PWA-TRANSCRIPTIONS-UX-01` | 4/4 | 4/4 | — |
| `PWA-INGEST-01` | 11/11 | 11/11 | — |
| `PWA-GOOGLE-PICKER-UX-01` | 9/9 | 9/9 | — |
| `PWA-SEGMENTS-01` | 5/5 | 5/5 | — |
| `PWA-BATCH-01` | 11/11 | 11/11 | — |
| `PWA-AUDIO-PREPARATION-01` | 31/31 | 31/31 | — |
| `PWA-SPEAKER-IDENTITY-01` | 5/5 | 5/5 | — |
| `PWA-MANIFEST-01` | 6/7 | 7/7 | — |
| `PWA-STANDARDIZATION-01` | 14/14 | 14/14 | — |
| `PWA-TRANSCRIPT-MAINTENANCE-01` | 9/9 | 9/9 | — |
| `PWA-REALTIME-01` | 13/13 | 13/13 | — |
| `PWA-OPERABILITY-01` | 18/18 | 18/18 | — |
| `PWA-SECURITY-HARDENING-02` | 21/21 | 21/21 | — |
| `GOOGLE-DRIVE-RELIABILITY-02` | 6/6 | 6/6 | — |
| `STORAGE-LIFECYCLE-02` | 22/22 | 22/22 | — |
| `STT-PROVIDER-ABSTRACTION-01` | 14/14 | 14/14 | — |
| `YANDEX-STT-01` | 5/5 | 5/5 | — |
| `PWA-DICTIONARIES-01` | 1/1 | 1/1 | — |
| `PWA-WORKER-ISOLATION-02` | 3/3 | 3/3 | — |
| `PWA-DATABASE-LEAST-PRIVILEGE-03` | 8/8 | 8/8 | — |
| `JOB-RELIABILITY-02` | 17/17 | 17/17 | — |
| `JOB-NOTIFICATIONS-01` | 6/6 | 2/2 | — |
| `REALTIME-CONTINUITY-02` | 5/5 | 5/5 | — |
| `TRANSCRIPT-EXPORTS-02` | 3/3 | 3/3 | — |
| `USAGE-COST-ACCOUNTING-01` | 6/6 | 6/6 | — |
| `OBSERVABILITY-AUDIT-02` | 35/35 | 35/35 | — |
| `RELEASE-SAFETY-02` | 5/5 | 5/5 | — |
| `PERSONAL-TECHNICAL-01` | 5/5 | 5/5 | — |
| `BRAND-VOICEOPS-01` | 5/5 | 5/5 | — |
| `RESULTS-STUDIO-02` | 9/9 | 9/9 | — |
| `YANDEX-DISK-01` | 0/8 | 8/8 | — |
| `REALTIME-RECOVERY-03` | 6/6 | 6/6 | — |
| `PWA-REQUIREMENTS-05` | 5/6 | 6/6 | — |
| `MEDIA-CONTRACT-03` | 8/8 | 8/8 | — |
| `PERSONAL-VOICE-02` | 1/5 | 0/0 N/A | SUPERSEDED |
| `SECURITY-LIFECYCLE-03` | 5/6 | 5/6 | BACKLOG:1 |
| `RECOVERY-DATA-03` | 3/7 | 3/7 | IN_PROGRESS:4 |
| `ENVIRONMENT-CAPABILITIES-01` | 17/50 | 17/50 | BACKLOG:33 |
| `COMMERCIAL-INFRA-DATA-01` | 0/15 | 0/15 | BACKLOG:15 |
| `COMMERCIAL-IDENTITY-01` | 0/18 | 0/18 | BACKLOG:18 |
| `COMMERCIAL-DATA-GOVERNANCE-01` | 0/26 | 0/26 | BACKLOG:26 |
| `COMMERCIAL-CROSS-BORDER-01` | 0/14 | 0/14 | BACKLOG:14 |
| `COMMERCIAL-STT-QUOTA-01` | 0/16 | 0/16 | BACKLOG:16 |
| `COMMERCIAL-SPEAKER-PRIVACY-01` | 0/3 | 0/3 | BACKLOG:3 |
| `COMMERCIAL-QUEUE-FAIRNESS-01` | 0/6 | 0/6 | BACKLOG:6 |
| `COMMERCIAL-BILLING-01` | 0/27 | 0/27 | BACKLOG:27 |
| `COMMERCIAL-ECONOMICS-01` | 0/15 | 0/15 | BACKLOG:15 |
| `COMMERCIAL-SECURITY-01` | 0/19 | 0/19 | BACKLOG:19 |
| `COMMERCIAL-NOTIFICATIONS-01` | 0/8 | 0/8 | BACKLOG:8 |
| `COMMERCIAL-LEGAL-01` | 0/15 | 0/15 | BACKLOG:15 |
| `COMMERCIAL-COMPLETENESS-02` | 0/9 | 0/9 | BACKLOG:9 |



## Validation Plan и Evidence

Canonical команды — [validation](runbooks/validation.md); delivery targets/recovery — [operations](runbooks/studio-platform-ops.md). Fixtures синтетические; пользовательские тексты, credentials и raw logs не включены в audit artifacts/PR. Время10Oct2026, runtime browser08:32..08:45UTC; первичные GitHub records/readback до08:53UTC.

| Риск / AC | Проверка / environment / этап | Обязательность | Evidence / ограничения |
|---|---|---|---|
| Trace/ID/denominator |308 Q, unique701 spec↔registry, stable IDs, relative links и scoped diff; root | Local до push REQUIRED | PASS10Oct:308 Q,701 stable AC,677 active/444 personal,76 unique findings,73 existing relative links и self-review;297 docs/CI/static/helper tests PASS за1.88s, git diff --check PASS. Это не remote gate PASS |
| Notebook/entrypoints | `python scripts/ci_checks.py`, root Windows Python3.12 | Local REQUIRED | PASS7 guards10Oct; thin Colab entrypoints и generated protobuf callers сохранены |
| Yandex/media/restore risks | `pytest -q tests/test_studio_yandex_transcription.py tests/test_studio_media_preparation.py tests/test_studio_restore_rehearsal.py tests/test_studio_recovery_quarantine.py`, isolated SQLite/synthetic data; fresh owned basetemp | Targeted audit REQUIRED | PASS92/SKIP1,1.30s10Oct; isolated PostgreSQL restore integration skip локально, Linux primary evidence отдельно. Дополнительно4 реальных FFmpeg wave/flac/copy/stereo tests PASS10Oct за0.86s. First local attempt failed fixture temp permission, corrected workspace basetemp; assertions не менялись |
| Implementation main | Linux PG17/Redis, migration, Python, Vitest/TypeScript/lint/build/browser E2E | Existing exact-main CI Evidence REQUIRED | A20261010-CI: main37502013651 SUCCESS06Oct on `bc5150eb189b44867101ca45b9da201921a99227`; PR32737500894207/test-merge69b0311,2067Python/5FFmpeg skips,800UI/76files и13browser PASS. Provider/Google/S3 сетевые границы mocked; docs PR применимость ниже |
| Advisory/dependency graph | npm lock audit; isolated installed constrained Python graph, no install/mutation | Audit RECOMMENDED | A20261010-DEPS: npm audit10Oct0 vulnerabilities. Linux Node/Python audit37426076418 SUCCESS06Oct, unchanged locks/constraints to main подтверждены. Fresh local pip-audit не завершился за bounded diagnostic window и остановлен; today Python advisory coverage PARTIAL, не0/PASS |
| GitHub settings/CI cost | Read-only gh/api protection/environments/jobs | Audit REQUIRED | A20261010-GH: strict app-bound ci-required, admins/force/delete settings; единственный migration Environment/reviewer/main-only подтверждён10Oct. PR542runner-s/265elapsed vs main560/273, safe fallback; included minutes UNSET |
| Runtime/browser | Public identity/ready/unauth401 и authenticated navigation/forms/picker/settings/support; safe read-only production | Audit RECOMMENDED | A20261010-RUNTIME: web/API/worker build/commit `bc5150eb189b44867101ca45b9da201921a99227`, schema0040, backend/PG/queue/worker/storage ready; queue0/0, heartbeat свежий. Drive connected, folder dialog/list/sort input открываются; numeric '-' и dot→comma PASS. Maintenance extended grant revoked; Yandex disabled. Нет paid STT, export writes, upload, revoke, deletion или restart |
| PR / merge | Actual current-head test-merge ci-required + applicable reviews/self-review | Remote REQUIRED | PENDING до publication; old main PASS не заменяет gate PR. Runtime suites/CD N/A только при подтверждённом docs-only selection |

### Охват, технические выводы и ограничения

**A20261010-CODE.**547 tracked files; Colab entrypoints/notebooks, React/Vite PWA, FastAPI/API/worker/Alembic, provider/storage/Google/auth/recovery, scripts/Compose/CI и tests/config прослежены по ownership/callers. AST tracked обычных Python modules:0 parse errors; IPython entrypoints отдельно. All701 IDs сопоставлены с code/test cohorts; broad READY не означает отдельный test на каждый AC. Privacy/auth/owner/CSRF/TOTP/trusted-device, signed upload length, OAuth initiating session, body/WS budgets, log redaction и replay guards сохранены; предыдущие security closures проверены в current code/regression inventory. Нового доказанного exploitable security finding не установлено; это не guarantee отсутствия vulnerabilities.

PostgreSQL — authoritative state, fenced leases/short transactions и immutable options/usage; external I/O вне lock-held transactions. Bounded cleanup/reconciliation и composite indices PR326 есть. One-worker-per-process и central App/main ограничивают изменение/масштабирование (F70), но measured production bottleneck/универсальный SLO не выдуман. No production DB dump/EXPLAIN/load или SSH access использован; operational topology/schedules — config/records, не полная проверка host state.

Config Settings env→defaults, explicit database URL/secret-file boundaries, Compose injected env/mounts и isolated synthetic tests проверены; production `.env` не читался. Python transitive constraints/npm lock воспроизводят dependency resolution; они не доказывают bit-identical binaries, active runtime artifact identity сверяется отдельно. Generated protobuf имеет adjacent proto и relay consumer; notebooks реальные entrypoints, compatibility410/deprecated routes и googlePicker facade имеют consumers/контракт. Absence imports не использовано как основание удаления.

**UI coverage.** Authenticated dashboard/audio/batch/Live/maintenance/settings, representative loading/empty/success/configured/unavailable states, picker/modal/number fields; current1280×720, horizontal overflow в проверенных main states не выявлен. Critical executable suites покрывают synthetic auth/owner/storage/errors/exports/Live recovery; real happy-path STT/Google writes не выполнялись. Mobile390/modal, offline/PWA update/install и poor-network capture опираются на code/component/browser fixtures, не новый runtime proof. Реальные media/provider sessions, backup timer/freshness/RPO under outage, host nginx/S3 policy и restore всей topology10Oct не проверены. STT support status configured/unknown/not_run; это не provider PASS. Maintenance revoked grant — runtime precondition, не кодовый defect.



## Audit quality review

Повторно проверены308 требований и701 стабильный ID в обе стороны;677 active/444 personal, alias/deferred scope отделены. Previous source unchanged; требования хранения transcription inputs уточнены без нового AC. F06/F13/F63 закрыты primary records, F15 остаётся bounded closure, независимый F70 не маскируется им. READY PUX-08/STORAG-06 пересмотрены по наблюдаемым нарушениям; остальные остатки имеют конкретный finding, а не старую случайную ссылку F06/F07. Manual acceptance percentage/ожидание владельца отсутствуют.

Confidence HIGH для source/counts, F04 synthetic parser и F67 real synthetic media, current GitHub settings/revision/health и UI противоречий. MEDIUM для полного runtime/архитектурной заменяемости/полной rollback topology; внешние consumers, paid service outcome, host timers и today Python advisory coverage ограничены. Возможные false negatives: provider wire evolution, real long-file speaker seams, browser capture permissions/offline/install, object versions/S3 behavior и operational failure under load. Эти условия не выданы за PASS/отсутствие дефектов.

Проверенные false positives: Drive loading/disabled state оказался временным; AX disabled options не доказали неработоспособность sorting; native select найден по актуальному DOM. Maintenance revoked grant честно блокирует mutation, ordinary Drive доступен. Generated protobuf/notebooks/legacy adapters не мусор; отсутствие optional tooling не finding. Новые source checks/пояснения не означают voiceprint/cleaned feature. Полный исследовательский отчёт и raw logs остаются вне tracked repository.

PR337, head8f9d649 и run39942848202 — initial validation, не основание merge следующей revision. Post-push self-review23Oct: explicit hidden-path scan выявил3 оставшихся canonical arguments в manual status/drain/preflight workflows. Они обновлены в том же PR без изменения triggers/permissions/procedures; contract regression связывает передаваемую repository identity с deploy-gate. Local40 CI unit cases и5 static workflow contracts PASS;1 дополнительно выбранный remote-temp-path case не исполнил Bash из-за уже установленного Windows ограничения, окончательная проверка remote-only. Следующий grouped push после завершения текущего CI; merge/CD остаются pending. Устаревший candidate run39942848202 сохранён как record, merge требует checks следующей revision. VPS preflight23Oct10:59Z подтвердил baselinef7f6087/clean main, exact installed wrapper bytes и прежние modes755/500; все5 containers healthy. Pinned raw Colab files на новом GitHub host доступны и SHA-256 совпадают.

CI39942848202 FAIL разобран: primary-navigation tests имели неоднозначный unnamed selector после добавления отдельного именованного info landmark;4 selector уточнены именем основной навигации, действия/assertions сохраняются. Guard документации поймал случайное совпадение части английского слова, формулировка заменена без изменения guard. Транспортный preflight fixture исправлен обновлением3 workflow arguments выше. User23Oct сообщил, что Google приложение опубликовано; это owner report, независимый OAuth Console readback пока недоступен.

Grouped CI correction23Oct: local43 CI/Colab/doc-guard tests и256 App/Login/Sidebar tests PASS; lightweight/diff/self-review PASS. Все подтверждённые причины initial FAIL исправлены одним batch; следующий push требует новый exact-revision CI. Fresh GCP readback: project VoiceOps Studio ACTIVE; Picker key ограничен current host и Drive/Picker APIs, значения ключей не читались. CLI не раскрывает OAuth Audience/Data Access/client origins; owner report о публикации принят с этим ограничением.
