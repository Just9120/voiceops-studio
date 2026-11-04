# Architecture

## Personal local execution

Nemotron companion — отдельный Windows process владельца, не замена VPS worker. Dedicated owner/device token и outbound Studio protocol ограничивают его назначенными local jobs; browser sessions, provider keys, storage credentials и database access не используются как machine credentials. API выдаёт проверенные source bytes/SHA и фиксирует clock receipt, PC выполняет FFmpeg и pinned CPU SALM, API принимает полный encrypted result с generation/idempotency fences, VPS продолжает общий export-only pipeline. Offline/cancel/revoke не вызывают cloud STT. Native model API остаётся loopback-only с отдельным ephemeral key; секретный профиль защищён current-user DPAPI. Устройство, команды и recovery — [local worker runbook](runbooks/local-worker.md), AC/статус — [extensions](spec/extensions.md) и [план](delivery-plan.md).

## Владение данными и границы scope

PostgreSQL владеет workflow metadata и зашифрованным recovery text. Live text сохраняется до явной очистки; незавершённый batch text — до полного документа, отмены или явного закрытия ошибки. Принятый обычный batch transcript остаётся внешним Google Docs output; отдельный standalone artifact Studio не создаётся. S3/R2 хранит только исходники с назначенным lifecycle, не новые finished audio results. Download/export аудио заново собирается worker из доступных исходников по сохранённым параметрам. Scope и статусы — [project spec](project-spec.md) и [delivery dashboard](delivery-plan.md); карта реализации не доказывает поставку.

Authorization, cloud-file access и document creation отделены bounded protocols в `integration_ports.py`, с конкретными local/Google modules и server-controlled factories. HTTP не выбирает implementation. Session/CSRF/owner checks остаются в API, lease/transaction authority — в worker; alternative adapters не обходят эти gates. Media part plan сохраняется до provider call и проецирует только номера/интервалы; prepared source context обозначает шкалу после фактического изменения длительности.

Access/security email — отдельный encrypted transactional outbox. Reset challenge одноразовый, 15 минут, response не раскрывает наличие аккаунта; ссылка содержит token во fragment, форма удаляет его из URL. Idle worker имеет только SELECT/UPDATE outbox, не создаёт challenges. Claims fenced, SMTP вне transaction, максимум3 попытки; SMTP acceptance при crash может повториться (stable Message-ID помогает dedup, не обещает exactly-once). Включение требует explicit own sender domain и TLS transport; job notifications opt-in независим. Процедуры — [operations](runbooks/studio-platform-ops.md), synthetic rollback Evidence — [validation](runbooks/validation.md).


This document is an architecture map, not a delivery plan, runbook, or production-readiness claim. It distinguishes source-level architecture from production deployment status.

## Contours

### Google Colab batch contour

The stable Colab contour runs through notebooks/scripts and remains the operational baseline for batch transcription and Google Docs delivery. It is independent from Studio PWA runtime services and must remain available as the fallback contour.

High-level Colab flow:

1. Operator launches the approved Colab notebook/script. Thin launchers pin a full reviewed commit and verify downloaded runtime SHA-256 before install/exec; updates change both revision and hashes after review.
2. Runtime reads secrets from approved Colab/runtime secret sources without printing values.
3. Source media is processed through provider transcription logic.
4. Transcript output is delivered to Google Docs in the versionless `transcript_doc` contract. The standalone Colab runtime builds Russian structural labels, preserves English metadata keys, writes bounded text chunks, and then applies one idempotent rich-text batch: title `HEADING_2`, ordinary transcript body `11 pt`, and `Спикер N:` bold `14 pt`. Google Docs ranges use UTF-16 code units.
5. Evidence must avoid secrets, transcript bodies, source bytes, document IDs/URLs, and raw external payloads.

Local-folder intake uses a Colab-rendered browser `<input webkitdirectory>` and the same `eval_js` iterator pattern as the upstream Colab file bridge. The browser emits only supported files as bounded base64 chunks with validated relative paths; absolute paths and `File.lastModified` are not accepted as source authority. Python reassembles bytes in memory under explicit file/count/total limits and then reuses the existing sequential local-file processing boundary. New transcript metadata prefers embedded media `creation_time`, falls back only to Drive `createdTime`, and otherwise records `unknown`. Duplicate-protection manifest sources are persisted only after a valid Google Doc ID is returned. Manifest clear is a separate dry-run-first operation with exact typed confirmation, backup-before-write ordering, and no source/Google Docs deletion. Realtime Colab owns attempt-scoped media/WebSocket resources: source-track end, session/WebSocket timeout and outbound backpressure all close the attempt and release every track. It never reconnects with a consumed single-use token; a retry is a new user Start and a new token.

Realtime Colab is an experimental standalone/proxy validation path described in `docs/runbooks/realtime-colab.md`.

### Studio PWA contour

Studio PWA is a web platform contour in development. Source-level architecture includes the web frontend, API, PostgreSQL, Redis, object storage, worker entrypoint, provider adapter path, Google Drive/Docs integration, diagnostics, independent transcript-maintenance operations with recursive-folder and single-document targets, and migrations. The bounded single-worker/small-source processing path has controlled production evidence, while broader selected capabilities and every newer schema/API revision still require their own rollout evidence.

The primary information architecture exposes `/transcriptions` with ordinary, Live and `Обслуживание` tabs. The third tab owns Google Docs standardization and `Манифест Studio`; Settings Connections owns only primary/maintenance grants and a navigation link to that workspace. `Project` remains an owner-scoped persistence boundary and a compatibility partition for existing sources/jobs/outputs, but its manual create/edit/archive lifecycle is not part of the product UI. On an empty active collection, a CSRF-protected idempotent endpoint locks the owner row, reuses the newest active workspace when one exists, or creates one internal `Транскрибации` workspace. It never unarchives archived rows. If several active legacy workspaces exist, a secondary compatibility selector keeps their data reachable without destructive migration.

The owner-facing Settings information architecture is URL-backed and split into `Аккаунт`, `Подключения`, `Файлы и хранилище`, `Оформление`, and `Для поддержки`. Provider credentials and Google grants live under Connections; the reusable owner Source catalog, retention controls and bounded temporary-storage control live under Files & Storage. The control exposes effective per-class policy and a dry-run-first orphan summary; it never exposes bucket/object/session identity. Apply requires a fresh signed owner/session plan plus an explicit same-origin confirmation. Runtime identity, diagnostics, debug and report export remain explicitly support-only rather than ordinary configuration. Transcriptions keeps only per-task source selection and does not render a second general catalog. The Files & Storage catalog is loaded only after that section is opened, while an in-flight deletion remains owned across section changes. An authoritative delete response removes the local card without an immediate stale collection reload; ambiguous outcomes still use server reconciliation.

One confirmed batch is presented as one multi-transcription with ordered item cards. Existing job-level lifecycle, progress, output and recovery APIs remain authoritative for each item. The API never exposes the stored idempotency key or request hash: it projects only a deterministic owner/project/key-scoped `multi_*` digest plus the bounded item position. The frontend validates that reference, rejects duplicate positions and groups items without adding a second durable batch state machine.

`/audio` — самостоятельная подготовка записи перед транскрибацией. Browser-local обработка декодирует выбранные bytes в Web Audio, применяет ограниченные преобразования и выдаёт WAV/object URL до закрытия вкладки. Server path сохраняет упорядоченные `AudioPreparationJobInput`, параметры и metadata результата в PostgreSQL. Отдельный worker выполняет FFprobe/FFmpeg в request-scoped каталоге; API не выполняет FFmpeg. Finished audio больше не создаёт S3 object или local-upload Source. Initial auto-save передаёт готовые bytes в подтверждённую папку Google Drive; post-reload download/export заново собирает результат из доступных исходников без STT. Загруженные исходники подготовки аудио сохраняют выбранный срок3/7/30 дней, Google sources остаются внешними ссылками. Недоступный/удалённый исходник даёт recovery state вместо обещания постоянного хранения результата.

Скачивание — явная worker-задача с одним unique DB slot на сервис и deadline3h. API/worker разделяют отдельный volatile tmpfs transfer volume2GiB. Каждая lease generation пишет в собственный каталог; публикация сверяет owner/generation/request/deadline под row lock. Готовый файл доступен15минут, передача также ограничена15минутами; завершение, disconnect, ошибка, отмена и bounded janitor очищают marked каталоги. Незнакомые файлы не удаляются. Active work защищает исходники от очистки. Параметры сохраняются для нового скачивания после очистки bytes. Для reuse/transcription используется подтверждённая копия Google Drive: при отсутствии копии владелец явно выбирает папку, затем API проверяет metadata и импортирует owner-scoped Google Source без S3 bytes. Старые S3 output Sources читаются по compatibility path до своего прежнего срока хранения; rollout не удаляет их массово.

Анализ полного исходника одновременно проверяет декодирование, измеряет огибающую громкости и интервалы тишины. PostgreSQL хранит максимум512 точек/интервалов на job; общий расчёт сокращения учитывает все найденные паузы. Это визуальная огибающая и оценка, не копия PCM. До full processing пользователь может явно подготовить WAV-пример до30s:60s окно возле первой паузы либо начала записи с выбранными параметрами. Пример использует тот же bounded download slot и TTL, сохраняет preview_ready и не публикуется как full result/Source. Native playback поддерживает byte ranges и не продлевает срок хранения. Пример закрывается перед запуском полного файла; повторное прослушивание готового результата использует явную регенерацию из исходников.

Прямая загрузка в Google Drive без обработки передаёт исходный `File` через browser resumable upload с owner/project/scope/folder проверками, signed descriptor и fresh parent/name/MIME/size/idempotency readback. Она не создаёт Studio Source, storage object, processing job или provider call.

The Audio workspace keeps its reusable Source catalog behind an explicit disclosure. Multiple inputs default to independent jobs/outputs; concat is an explicit alternate mode with a numbered metadata-backed plan and manual reorder. Filename is never creation/order authority. A completed Studio output may be downloaded, optionally opened in Drive, reused as a new Audio input, or handed to Transcriptions by exact owned Source ID. The receiving composer accepts the ID only after its authoritative owner Source collection has loaded and the Source still satisfies the normal usability boundary; it never duplicates the upload or bypasses Source validation. A browser-local output becomes a normal Studio Source only after the owner explicitly invokes its upload action.

Manual speaker identity is an owner-scoped post-processing contour for accepted diarized outputs. The worker derives one technical `Speaker N` observation and an at-most-eight-second source-relative time range per provider label in encounter order, persists no transcript text/audio/voiceprint/embedding, and commits observations in the same accepted-output transaction. The authenticated browser lazily loads active name/role profiles and may request one `no-store` sample; the API revalidates job/source ownership and current source availability, downloads the private R2/Drive source server-side, extracts a mono MP3 into a request-scoped temporary directory, returns only the bounded bytes, and deletes temporary files on exit. Explicit assignment locks the observation, resolves an active owner profile and exact accepted output, reads the Google Doc with the primary owner grant, replaces only exact speaker heading lines under Google revision control, and persists a name/role snapshot only after the document mutation succeeds or its idempotent outcome is observed. Browser history receives only observation ID, technical `Speaker N`, sample availability and assigned profile snapshot; provider labels, time bounds, source/storage identity, document ID and document content remain server-only. Profile edits do not silently rewrite historical documents; the owner must explicitly reapply an assignment.

## Components

| Component | Source location | Responsibility | Production status note |
| --- | --- | --- | --- |
| Studio frontend | `apps/studio/` | Browser UI for sessions, standalone audio preparation, bounded direct-to-Drive media upload, ordinary/Live/maintenance `Транскрибации`, app-owned searchable Drive dialogs, internal legacy workspaces, sources, provider-specific credentials, provider/mode selection, owner STT dictionaries, primary Google connection, separate maintenance consent, grouped multi-transcriptions with item-level jobs/outputs, owner opt-in Web Push/email/Telegram notification preferences and bounded delivery history, manual speaker profile/listen/assign flow, provider-account subscription/usage freshness, diagnostics, standardization, `Манифест Studio`, and Live workspace with IndexedDB/server draft recovery, a project-isolated browser/OBS overlay and explicit ephemeral external-caption targets; `src/apiClient.ts` owns same-origin JSON/CSRF retry transport and its safe diagnostic emission. | Current merge/CI/deployment evidence belongs in `docs/delivery-plan.md`; source presence is not deployment, live provider/account, Google, recovery or Live-capture evidence. |
| Studio API | `apps/studio-api/studio_api/` | FastAPI app, password/session/recent-auth and optional TOTP/recovery boundaries, owner-scoped APIs, audio-preparation/job/source/credential/output/diagnostic/catalog services, preview-bound bulk removal of Studio source records, explicit resolution of uncertain terminal transcription outcomes, provider-neutral STT capability validation and dispatch, Yandex asynchronous operation persistence/polling, short-lived signed Yandex realtime relay, bounded external caption delivery, owner dictionary CRUD, bounded official ElevenLabs subscription/workspace-usage reads, descriptor-bound direct-Drive upload issuance and result verification, encrypted owner-cleared Live drafts, separate maintenance OAuth/token refresh, durable maintenance run enqueue/read authority, exact-document revalidation, bounded recursive folder traversal, and redacted single-use ElevenLabs realtime capability issuance. | Current merge/CI/deployment evidence belongs in `docs/delivery-plan.md`; newer schema/config requires a separately verified API rollout. |
| Database | PostgreSQL via Studio deployment | Durable users/preferences/projects/sources/credentials/transcription and audio-preparation jobs/outputs/diagnostics/catalog state, encrypted optional TOTP factor state and hashed one-time recovery codes, session-scoped recent-auth timestamps, persisted Source reference class and exact bucket identity, durable single-PUT/multipart upload authority, owner-scoped output-folder Favorites, authoritative optional source-creation metadata, separately encrypted maintenance grant fields, owner-scoped transcript-maintenance run/progress/lease/result state, bounded provider-part progress counters, confirmed provider usage/cost with an immutable per-job tariff snapshot, bounded owner/credential-version-scoped ElevenLabs account snapshots, provider operating mode/config metadata, owner STT dictionaries, encrypted terminal Yandex results with opaque operation authority, per-provider/mode health circuit state, immutable optional media-clip bounds and long-duration confirmation, durable explicit resolution/linkage for uncertain terminal outcomes, safe underlying provider failure categories, bounded automatic-retry schedule/reason, encrypted Web Push subscriptions, owner notification preferences and deduplicated terminal-delivery outbox, encrypted unfinished-part recovery checkpoints and owner-cleared encrypted Live transcript drafts, trace-linked append-only audit records, owner-scoped operational incidents/deliveries, and the single authoritative worker-runtime heartbeat row. | Schema head is read with `alembic heads` from the checked-out revision; exact production revision evidence is tracked separately in `docs/delivery-plan.md` and must never be inferred from repository source. |
| Alembic migrations | `apps/studio-api/alembic/versions/` | Schema authority for Studio persistence. | Use the actual checked-out Alembic head and its direct predecessor; ordinary component CD does not apply it. The separately enabled protected release lane may apply only one reviewed direct additive successor per approval. |
| Redis | Studio deployment | Platform support service; not a processing queue/lock/retry authority unless separately designed. | Production health is operator evidence, not source evidence. |
| Object storage | Two S3/R2-compatible reference boundaries | Private temporary/local-upload source bytes. `transcription` and `audio_processing` select separate configured buckets, credential files and lifecycle identifiers; Sources persist class, exact bucket and upload protocol/session authority. Small files receive one bounded PUT capability. Large files use owner-scoped multipart part capabilities; the server alone retains upload ID, object key and ETags, validates exact part count/sizes and confirms the completed object. | Missing/equal boundaries or a persisted bucket mismatch fail closed without cross-bucket fallback. Existing objects keep the migration-default `transcription` class and are not moved. Object keys/source bytes/session IDs remain server-only. Abandoned multipart sessions enter durable cleanup and provider lifecycle is a second bounded safety net. Provider-side permissions/lifecycle require external Evidence. |
| Worker | `apps/studio-api/studio_api/worker.py` and related runner/orchestrator modules | Poll/claim/process bounded work according to lease and lifecycle rules. Provider-neutral transcription dispatch preserves the existing lease/retry/output lifecycle; ElevenLabs retains part checkpoints and tariff accounting, while Yandex normalizes one bounded OGG/Opus input and persists its asynchronous operation before polling. Provider/mode circuit state is updated only for allowlisted mass-failure categories. Audio preparation and normal transcription claims precede transcript maintenance; maintenance has its own fenced generation and shared stage heartbeat. Only allowlisted durable transient failures can return a failed transcription to the queue under a bounded backoff. During idle work the worker claims at most one owner terminal-notification delivery, commits the claim before network I/O, then records the bounded outcome in a fresh transaction. The runtime has explicit CPU/memory/PID limits, a read-only root filesystem, bounded tmpfs, a dedicated outbound/DB network pair and a direct-grant `studio_worker` PostgreSQL login without DDL/role/auth-session authority. | Worker deployment is manual-only. Current running/stopped identity, effective isolation and canary evidence belong in `docs/delivery-plan.md`; multi-worker behavior remains unproven. |
| Provider path | Provider-neutral catalog/dispatch plus ElevenLabs and Yandex modules under `apps/studio-api/studio_api/` | Owner-scoped BYOK batch/realtime execution with explicit provider/mode capability checks and no automatic cross-provider fallback. ElevenLabs additionally owns read-only subscription and workspace product-credit reconciliation. Yandex owns deferred operation polling and the API-side gRPC realtime relay; browser audio and long-lived provider secrets are not persisted. | One bounded ElevenLabs transcription canary completed. Yandex stays disabled until operator configuration and has no paid LIVE claim; current rollout evidence belongs in `docs/delivery-plan.md`. OpenAI Studio processing is deferred. |
| Google integration | Google OAuth/Drive/Docs modules under `apps/studio-api/studio_api/` | Primary identity + `drive.file + drive.readonly` capability, app-owned Picker, direct browser resumable upload with server verification, separately encrypted server-only maintenance grant, safe exact-document validation or bounded Drive traversal, Google Docs reads/writes, and output creation. | Primary `drive.readonly` can read every Drive file accessible to the account; full `drive` and unrelated scopes remain rejected. Primary Picker/output evidence does not prove the separate maintenance grant or either maintenance target mode. |
| Transcript maintenance | `transcript_catalog*.py`, `transcript_maintenance*.py`, migrations `0016`/`0017`/`0028`, worker integration and frontend maintenance panel/model modules | Two owner-scoped operations with independent `folder_tree` or `single_document` targets: in-place standardization or PostgreSQL-only `Манифест Studio` import. POST only enqueues a durable run; owner-scoped reads restore safe progress/result, and apply derives authority from a successful preview before fresh Google revalidation. | Source and targeted-test state is tracked in `docs/delivery-plan.md`; migration/config/deployment/live dry-run/apply evidence remains separate. |
| Diagnostics and runtime observability | API/frontend diagnostic modules, `runtime_observability.py`, `diagnostic_reports.py` and migrations `0010`/`0011`/`0026` | Safe diagnostic event/debug-session foundation and one allowlisted report model serialized as Markdown, JSON, YAML or TOML. The PWA presents human summaries/actions first, keeps technical codes/IDs/metadata behind disclosure, prioritizes warning/error events and bounds expansion through server pagination. Component-baked web/API identities plus the worker's process-incarnation heartbeat expose separate fail-closed release/build/commit identities, exact schema revision and bounded queue/storage/provider health. Frontend failure correlation persists only allowlisted status/request/category metadata. | Every format reuses the same owner filters, redaction boundary and `no-store` download contract. Storage probing performs bounded read-only `HEAD` checks against both selected buckets and returns only per-class status; provider status is configuration-only and performs no paid call. Runtime evidence remains separate from source or target revision claims. |
| Deployment | `deploy/studio/`, `.github/workflows/` | Ordinary component deployment plus a distinct approval-gated stateful release boundary. | Ordinary CD must not deploy workers or run migrations. The migration lane is disabled by default and requires a protected environment, a dedicated root forced command, exact-main identity, a new verified backup, one additive migration, exact API image deployment, and health evidence. |

## Runtime boundaries

- Browser is untrusted for durable secrets and raw server-side content. It normally receives only safe normalized owner-scoped metadata; explicit OAuth-start, Picker, and direct-upload capabilities are bounded exceptions governed by the product contract.
- API owns authentication, authorization, encryption/decryption, Drive/provider calls, separate maintenance token refresh/traversal, source storage access, and lifecycle checks.
- Realtime Yandex audio crosses only the exact same-origin `/api/realtime/yandex` WebSocket route under a five-minute signed capability, a ten-megabyte relay budget and a five-minute provider deadline. Nginx excludes the capability-bearing query from access logs and proxies WebSocket Upgrade explicitly.
- Browser/OBS overlay state stays in the same browser profile through a project-filtered `BroadcastChannel`. YouTube closed-caption and generic HTTPS webhook destinations are explicit per-tab inputs, never durable Studio state; generic webhook hosts require an operator allowlist and any consumer failure is isolated from capture/STT.
- Worker uses the API codebase/internal services but must be deployed and validated as a distinct runtime component.
- Web publishes only `127.0.0.1:8181:8080` for host nginx. A web-exclusive,
  non-internal `studio-web-ingress` bridge enables Docker host-port publication;
  its separate `studio-web-api` network stays internal. API, worker, PostgreSQL
  and Redis do not join the ingress bridge. An internal-only web container can
  be healthy internally while Docker leaves the host port unpublished.
- API/worker Compose services use a bounded root bootstrap only to copy allowlisted
  host-owned file-backed secrets into root-owned tmpfs runtime storage as `0400` files
  for UID/GID `10001`; the entrypoint then clears supplementary groups, drops to
  `10001`, and execs every ordinary API, worker, health, or Alembic command.
- Worker shares no Compose network with web, API or Redis. Its only internal service
  path is the dedicated PostgreSQL network; a separate non-internal network provides
  outbound provider/Google/object-storage access. API and worker use different
  PostgreSQL credentials, and worker readiness verifies the effective role attributes
  and required/prohibited grants.
- PostgreSQL is the durable authority for Studio persisted state.
- PostgreSQL separates `studio_owner` (`NOLOGIN` schema owner), protected
  `studio_migrator`, direct-grant `studio_api`, and direct-grant
  `studio_worker`. The bootstrap `studio` credential stays on the PostgreSQL
  service/explicit operator path and is not mounted into ordinary API or worker
  runtime. Every migration re-applies and verifies the reviewed direct grants.
- Redis is not the durable job queue authority for current processing semantics.
- Object storage is private server-side source-byte storage.
- External providers and Google APIs are side-effect boundaries requiring pre/post lifecycle checks.

### Bounded data-access contracts

- Growing owner browser collections — projects, project sources, transcription jobs and audit events — use signed session-bound keyset pages ordered by the deterministic pair `(timestamp DESC, id DESC)`. Cursor context binds the owner, surface and project scope; invalid, expired-session or cross-surface reuse fails closed. The browser fetches the next page only by explicit action, deduplicates by ID and discards stale cursors on authoritative reload.
- Progress polling sends at most 50 current job IDs from the visible browser collection. The compatibility project read has its own hard maximum and explicit truncation signal; neither path performs per-job follow-up queries.
- All-time transcription analytics remains exact. PostgreSQL performs grouped counts and percentile/duration aggregates; the API does not load all jobs, attempts or a cardinality-sized ID list, and query count is constant relative to history size.
- Transcript duplicate/catalog and competing-provider authority aggregate equivalent evidence in SQL under explicit row-group budgets. Budget exhaustion is an indeterminate conflict, never absence of evidence, so it cannot authorize another paid provider call.
- Provider-part retirement drains bounded deterministic `(created_at, id)` batches only after all outputs are accepted, cancellation or explicit terminal resolution. Old expiry timestamps do not retire unfinished text. Live drafts are removed only by explicit owner clear; the compatibility expiry-cleanup hook is a no-op.
- Before each paid ElevenLabs part, the worker durably records its part index,
  prepared audio duration and the configured public USD tariff snapshot. A returned
  provider result confirms that part exactly once before checkpoint progression; a
  transport or persistence ambiguity remains `uncertain` and is never converted to
  zero usage. Owner analytics sums confirmed duration/cost only. The amount is
  attributable provider usage (`confirmed duration × tariff snapshot`), not invoice
  reconciliation after subscription credits or a user-billing contour.
- Account reconciliation is an API-only read path: the server decrypts the active
  owner credential, validates bounded official subscription and workspace-usage
  responses, and persists only normalized account values for that credential version.
  PostgreSQL advisory locking serializes refresh for one owner/credential pair. A
  successful or failed attempt is cached for five minutes; the visible UI polls once
  per minute, supports an explicit force refresh, and labels the last success as
  `current`, `stale`, or `unavailable`. The browser receives no API key, provider user
  identifier or raw response, and the worker role has no access to this table.
- Subscription period usage is provider-reported `characters`; workspace analytics is
  provider-reported `credits`. Studio does not convert either unit into Scribe minutes
  or allocate account invoices/overage to jobs without a direct provider contract.
  Current overage and open/next invoices are account actuals. Per-job USD cost remains
  the separately versioned public-tariff snapshot because ElevenLabs exposes no
  structured price-catalog endpoint suitable for automatic tariff mutation.

### Browser-bound integration capabilities

The Studio frontend keeps the direct-browser Google Picker and local-upload architecture. Google Picker requires an access token from the exact primary identity + `drive.file + drive.readonly` connection. `drive.readonly` supplies read authority for arbitrary selected source descendants; `drive.file` remains the write boundary for objects created or explicitly opened by the app. Local upload uses a short-lived S3/R2 presigned PUT so source bytes do not transit the API process. One shared `XMLHttpRequest` transport sends the raw `File` body with browser credentials disabled and reports native per-file byte/percentage plus aggregate queue progress in Audio and Transcriptions. It uses a bounded capability-lifetime timeout, refuses a redirected terminal response, reconciles completion after an ambiguous network outcome and never retries the PUT automatically. The public edge `Referrer-Policy: origin` limits the request referrer to the Studio origin without path/query data; the presigned capability URL is never used as referrer or persisted. OAuth-start authorization URLs, primary Picker access tokens, and upload URLs are therefore capability responses rather than ordinary metadata. Local folder intake is browser-recursive through relative paths and reuses the existing per-file upload boundary only after a bounded preview. A Picker-selected Drive source folder is recursively enumerated by the API under explicit file/page/depth bounds; preview has no Source side effects, apply repeats traversal and compares an owner/project/folder/content-bound snapshot digest before one atomic Source transaction. Cycles, duplicate IDs, repeated page tokens, malformed/incomplete listings, drift, unsupported creation authority and more than 50 supported files fail closed.

Direct-to-Drive upload reuses the exact primary scope and app-owned output-folder picker, but not Source/S3 issuance. The CSRF-protected API revalidates owner/project/folder and returns one `no-store` in-memory access token plus a session-bound signed capability for every normalized operation descriptor. The browser first searches the exact target folder for the stable appProperty marker; zero matches permits one resumable upload, one match is reused, and ambiguity fails closed. It never automatically retries the media PUT. Completion sends only the selected file ID and signed descriptor back to the API; the API refreshes the owner grant, revalidates the folder, reads exact Drive metadata and accepts only the expected parent, filename, MIME, byte size, marker and safe `drive.google.com/file/d/...` web link. Access tokens and resumable session URLs remain function-local, are not persisted or rendered, and are excluded from audit/diagnostic payloads.

These responses require authenticated same-origin CSRF-protected issuance, `Cache-Control: no-store`, no service-worker runtime caching, no browser persistence/diagnostic logging, and server-side revalidation of every selected Drive ID or completed object. Picker/direct-Drive issuance requires the exact identity + `drive.file + drive.readonly` boundary and exact Picker origin; because this browser capability carries broad read authority, reconnect/consent is explicit and any extra scope fails closed. S3 upload issuance uses an opaque server-owned object key, exact content type, PUT-only operation and at most 900 seconds; the cross-origin PUT omits browser credentials, exposes at most the public Studio origin as referrer under the edge policy, and does not accept a redirected terminal response. Direct Drive upload uses a descriptor-bound one-hour capability, explicit manual retry, exact marker lookup and server-side result verification. Refresh tokens, ID tokens, object keys, source bytes, provider secrets, resumable session URLs, and maintenance access/refresh tokens never cross the server boundary or persist in browser state; the explicitly issued primary access token is held only in memory for the current Picker/direct-upload action.

Live transcription adds one more bounded browser capability. Only after microphone/display permission succeeds, the authenticated owner submits an active ElevenLabs credential reference to a project-scoped CSRF-protected endpoint. The API decrypts the main BYOK key only server-side, requests a provider single-use `realtime_scribe` token, validates the exact ElevenLabs WSS origin/model/audio/commit contract, and returns a `no-store` capability that expires within 15 minutes and is consumed on connection. The PWA never renders, persists, logs, or reuses that URL/token. A new attempt always requests a new capability.

Live transcript recovery is a separate content boundary, not a provider capability or batch/history record. Every committed fragment starts an owner/browser-scoped IndexedDB checkpoint; the latest partial uses a bounded debounce and remains explicitly unconfirmed. Serial server writes use monotonic owner/project/client-session revisions. PostgreSQL stores AES-GCM ciphertext, nonce, key ID, integrity HMAC, bounded counts, correction identities, timing and gaps until explicit owner clear; responses are `no-store`. Recovery returns text only to its authenticated owner. Audio is never persisted. Autosaves do not create audit/diagnostic/history/analytics rows. Legacy TTL values do not expire retained Live text; old rows remain readable after migration.

Transcript maintenance starts through a second OAuth consent but remains a server-only integration after the authorization redirect. The API stores its encrypted refresh token in separate columns, requires the same Google subject as the primary connection, and accepts only identity plus `drive.metadata.readonly` and `documents`. API and worker receive the separate maintenance OAuth client configuration; web and browser never receive its secret or refresh/access token. The browser receives only safe maintenance connection state and run DTOs. For each operation an app-owned dialog uses the in-memory primary Drive capability to search/navigate either one root folder or one native Google Doc, then sends `selection_mode` plus exactly one matching ID on enqueue; it never supplies a document list or saved candidate set. PostgreSQL owns queued/running/terminal state, bounded progress, result/error, attempts and fenced lease generation. Apply accepts only the successful owner preview ID and derives the private target server-side before fresh Google revalidation.

Before enabling local file selection, the frontend reads an authenticated `no-store` source-upload policy DTO containing only an availability boolean, the deployment-configured maximum byte count, multipart threshold/part size, and supported MIME rules. The frontend validates the DTO at runtime and fails closed for direct local uploads when storage is unavailable or the policy is unavailable or malformed. This read-only metadata is not an upload capability and does not replace API initiation, object-storage metadata verification, or processing-time source checks. Multipart upload uses sequential bounded parts and server status after every ambiguous PUT; reissuing a capability for the same part is safe because completion consumes only the provider-listed exact part set.

The public host nginx is the authoritative browser-header boundary for both the PWA and `/api`; the loopback-only web-container nginx does not maintain a competing policy. CSP limits executable script to Studio plus the Google API loader hosts, limits frames to Google Picker hosts, explicitly permits only the ElevenLabs realtime WSS endpoint for Live, and blocks external framing, objects, and unsafe evaluation. `connect-src https:` remains intentionally broader than the other directives only because the S3/R2-compatible upload origin is selected at runtime. Microphone and display capture are allowed only for the same origin; camera, geolocation, payment, USB, and unrelated browser capabilities remain denied.

## Studio data flow

1. User authenticates and opens `Транскрибации`; the UI resolves an owner-scoped internal workspace automatically.
2. User adds sources from safe single/multi-file or folder intake. A local folder is filtered in the browser before any PUT; files below the configured threshold use a single short-lived PUT, while larger files use a durable multipart session with short-lived per-part capabilities and server-confirmed status/completion. A Google Drive folder is selected in Picker but its IDs, metadata and descendants are authoritative only after server traversal. Both folder modes show a bounded preview and expand confirmed files into individual Source/composer rows with one inherited target folder and later per-row override.
3. User configures owner-scoped BYOK credentials and Google output destination.
4. Before job creation, the frontend requests a non-mutating server preflight. One composer row expands into one or more ordered jobs for the selected source: each user-defined fragment has immutable optional clip bounds, its own verified output folder and optional title. The API revalidates the active ElevenLabs credential, ordered fragment groups, non-overlapping clip bounds and writable output folders, evaluates owner-scoped accepted Studio output evidence per clip, then returns only safe source/display metadata, selected options, destination names, clip bounds, match categories, counts and planned outcomes. The preflight DTO does not echo source/folder identifiers or URLs and never returns storage paths, tokens, document references or raw external payloads.
5. A row with an accepted exact match, matching-settings legacy standard, or indeterminate accepted evidence is blocked until the user explicitly chooses paid reprocessing. Editing the source or effective transcription settings clears that choice and invalidates the preview. Batch creation remains the canonical authority: after external target validation it deterministically locks all owner source rows that share the selected catalog identities, reloads source lifecycle state, repeats the accepted-output query, and refuses unresolved conflicts before persisting new jobs. The affirmative decision is persisted on that single job as a reserved server-owned option, is not returned to the browser, and cannot be supplied through the deprecated arbitrary-options endpoint. An unchanged idempotent replay remains a replay rather than a new decision.
6. Worker claims one eligible queued job using fenced lease metadata.
7. Processing re-checks lifecycle, lease, cancellation, source availability, credentials, and output destination.
8. Source materialization provides an ephemeral server-side handle.
9. The worker duration-probes every prepared source. Google Drive `createdTime` is normalized and persisted during source intake. For a local source without creation authority, the worker also reads embedded media `creation_time` before the provider boundary and persists it with provenance when present; browser `File.lastModified`, upload time, job time and Google Docs creation time are not fallbacks. When immutable clip bounds exist, the worker rejects an invalid or out-of-duration interval before any provider request and creates one temporary AAC/M4A clip. Video preparation and the optional manual clip remain server-side; afterward any resulting media above the explicit size/duration policy becomes an ordered bounded set of overlapping mono AAC parts before the first provider request.
10. Immediately before the first paid provider call, a job locks its catalog source identity, rechecks accepted output evidence, and checks whether another equivalent job has durably crossed `provider_request_started`. The lock is held until the current job's own provider-start checkpoint commits, so only the first equivalent worker can cross the boundary. Processing attempts and terminal attempts without a retry-safe outcome remain conflicts; accepted outputs are evaluated separately, and a completed attempt missing its required output evidence fails closed as an inconsistency. A durable explicit-reprocess decision bypasses only an accepted-output conflict, never an in-flight or unresolved provider attempt. A losing job is classified non-retryable before any provider call. ElevenLabs then processes parts in order under the source/provider heartbeat. The attempt stores the prepared total and monotonically completed part count. For multi-part sources, each successful normalized provider result is encrypted and committed with exact scoped metadata before its completed counter advances. A later provider failure preserves both aggregate `partial_provider_result` and the fixed safe underlying category. The worker revalidates lifecycle authority between calls and merges successful part words onto one deterministic source timeline.
11. Google Docs output first creates one reconciliation-marked document reference for the active output target, then applies the versionless `transcript_doc` rich-text contract through Google Docs. A formatting failure is not accepted as output success: the prepared reconciliation marker remains authoritative and prevents a silent duplicate create on retry.
12. API persists safe output metadata and completes the job only when every non-skipped relation has output evidence.
13. While queued or processing jobs exist, the frontend polls one owner-scoped project progress endpoint and retains the last safe state for a newly terminal job until explicit dismissal. The API projects only browser-safe filenames, bounded part counters, and a fixed preparation, video-audio extraction, conditional split, provider, conditional merge, and Google Docs pipeline from current durable attempt checkpoints plus persisted-output evidence. Percentage uses confirmed checkpoints and completed prepared parts only. The DTO omits source IDs/URLs, storage identity, credentials, failure detail, transcript/provider content, and lease/claim authority.
14. Frontend reads browser-safe job/output metadata, groups jobs sharing the validated safe batch reference into one multi-transcription and preserves each item's progress, output and recovery controls; transcript/document bodies remain server-private and are not returned.
15. A terminal success/failure creates deduplicated owner notification intents in the same database transaction only for channels already opted in. The idle worker sends one claimed Web Push, email or optional Telegram delivery outside the database transaction and records only a bounded safe outcome. A retry-safe transient failure instead suppresses obsolete pending intents and returns the job to the queue after its server-enforced backoff; provider/Google/output uncertainty never follows that automatic path.

## Studio Live data flow

1. The authenticated owner opens the Live tab in `Транскрибации`; the resolved internal workspace supplies ownership scope. Batch composer/jobs remain mounted behind their separate tab and are not mutated.
2. The browser obtains explicit microphone, display/tab-audio, or both permissions. A mixed session combines sources locally with voice-priority gain staging: the microphone remains at unity gain while display audio is attenuated before the combined PCM path. Browser-only analysers expose independent bounded source levels to the active UI and never persist samples. Microphone activity uses hysteresis to duck display gain further and restore it after speech, reducing loud-source masking without mutating the original tracks. The microphone requests standard browser echo cancellation, noise suppression, automatic gain control and mono capture as ideal constraints; headphones remain the recommended acoustic boundary. No captured bytes transit Studio API, PostgreSQL, Redis, object storage, diagnostics or the worker.
3. Only after capture succeeds, the PWA requests one project-scoped capability for an active owner ElevenLabs credential. The API applies same-origin CSRF, ownership, credential-state, safe diagnostic, and issuance-rate-limit checks.
4. The browser opens the exact ElevenLabs WSS URL and streams downsampled mono PCM16 chunks while enforcing a bounded outgoing WebSocket buffer. `scribe_v2_realtime` with VAD yields partial and committed transcript events.
5. Partial text replaces the current unconfirmed preview; committed text appends in order. A committed event starts an immediate local checkpoint and queued encrypted server sync; partial changes checkpoint after a bounded debounce. Copy/download/clear are explicit. After refresh, crash or restart, the authenticated owner must explicitly restore, download or delete the retained draft before a new Live session starts. Live text has no fixed TTL and is removed only by explicit owner clearing.
6. Stop sends one final commit signal, allows a bounded final-event grace period, then closes capture/socket/audio resources. Hiding the Live workspace stops active capture while retaining confirmed text. Unsupported capture APIs, permission rejection, source-ended, capability timeout/abort, socket/provider error, backpressure overflow, a 10-second connection timeout, page hide, and unmount also clean up deterministically.
7. Bounded automatic reconnect obtains a fresh single-use capability, keeps the capture attempt and replays only bounded unsent audio. Exhausted recovery releases resources and marks the gap; a new manual Start remains explicit. Used capabilities are never reused. There is no cross-tab audio continuation or batch/source/Google Docs/catalog side effect. Live text is retained until explicit clearing; the worker does not expire it by TTL.

The current catalog authority defines one canonical settings tuple (`elevenlabs`, `scribe_v2`, `ru|detect`, diarization boolean), reuses versionless `transcript_doc` and the accepted Google Docs output kind as shared constants, and classifies persisted Studio output evidence plus explicitly source-linked imported catalog metadata as an accepted exact match, standardization-required, indeterminate, or no match. Legacy `transcript_doc_v1.2`/English structural labels are outdated, not a selectable current version. Classification is owner-scoped across projects: a Google source uses its private Drive file ID so reselecting the same file can retain identity, while a local upload uses its existing Studio source row because no content fingerprint is currently persisted. Duplicate Google document IDs are counted once when the same accepted document exists in both Studio output evidence and the imported catalog. These identities and output records remain server-only.

Transcript maintenance is not part of job creation. Standardization and `Манифест Studio` each own a separate target mode, selected target, preview, confirmation, and result. For dry-run and again for apply, the API revalidates the exact selected native Google Doc or traverses the selected root and descendants under explicit page/item/folder bounds. Recursive traversal rejects cycles, malformed listings, duplicate identities, repeated page tokens, incomplete search, or exceeded limits. Standardization skips current documents and may rewrite only eligible non-current documents in place under exact Google revision control; the same bounded batch replaces localized text and applies `HEADING_2`/`11 pt`/bold `14 pt` styles. `Манифест Studio` skips already-target entries and may persist only eligible current-document metadata. Per-document unsafe/inaccessible outcomes do not abort safe siblings in folder mode; connection-wide auth, rate-limit, availability, timeout, or global scan failures abort.

Manifest membership authority is the owner-scoped reconciliation of two durable
PostgreSQL evidence sources: historical `TranscriptionJobOutput` rows and
`TranscriptCatalogEntry` rows written by manifest apply. A catalog row alone is
sufficient to classify that document as already imported on every later
dry-run, including a new database session. Historical output evidence may add
exact effective settings; incompatible exact settings, malformed authority, or
ambiguous evidence fails closed as a conflict. This maintenance-membership
lookup is distinct from the source-linked accepted-output matching used by paid
transcription preflight.

The account-level `users.manifest_reset_at` boundary provides non-destructive
manifest clear semantics. Accepted output and imported catalog evidence at or
before that instant no longer participates in later duplicate decisions, while
the underlying jobs, outputs, Google Docs, sources, catalog rows, and audit
events remain durable. Provider-attempt authority is evaluated independently:
a `completed` disposition becomes available only when the same job-source has a
persisted accepted Google Docs output; completed-without-output, in-flight, and
uncertain attempts continue to fail closed. The reset therefore cannot bypass
an unresolved paid-call outcome.

Preflight exposes this authority as `partial` with reason `unlinked_catalog_entries_excluded`. It can block accidental repeated paid transcription against current accepted Studio output evidence and exact source-linked catalog evidence, and create repeats the decision under PostgreSQL source locks so a concurrent output-persistence transaction cannot pass unnoticed. The worker repeats the accepted-evidence comparison at the final provider boundary and treats an equivalent in-flight or unresolved provider attempt with a durable provider-start checkpoint as a conflict; only an attempt explicitly classified retry-safe is exempt. The same identity lock serializes that comparison with the current attempt's own provider-start commit, covering two jobs that were both queued before either had an accepted output and preventing a new job from bypassing an uncertain failed attempt. A losing job cannot be retried from its stale decision; the user must run a fresh preflight after the winning job's outcome is known. The deprecated multi-source create route uses the same catalog comparison but can only create when no accepted evidence exists; callers must use batch preflight/create for an explicit paid reprocess decision. The browser receives only the category, accepted-output count, and required/reprocess resolution. The explicit reprocess flag participates in the canonical request and idempotency hash; there is no implicit overwrite, provider retry, skip, or reuse.

The authority remains partial by design: the separately initiated maintenance operations can standardize and import approved legacy evidence, but a document without explicit source identity cannot participate in duplicate matching and indeterminate settings require an explicit reprocess decision. The authority does not infer linkage from a document name, detect a separately uploaded copy of the same local file, treat queued/processing jobs as accepted outputs, or turn a bounded maintenance operation into continuous Drive synchronization. Reuse/skip needs an explicit accepted-output linkage design and is not inferred from a match.

Progress tracking is deliberately checkpoint-based. Migration `0018_job_part_progress` adds only bounded integer `provider_total_parts` and `provider_completed_parts` to the current source attempt. The existing `prepared` checkpoint still covers source materialization plus media preparation, so audio extraction and split evaluation become confirmed when the provider checkpoint is reached rather than exposing fabricated sub-step timing. Split and merge are displayed as conditional checks: completion means the gate was evaluated and applied when required, not that every source was split. The PWA continues polling HTTP; WebSocket is not required for durable batch part progress. Within one synchronous provider request and within ffmpeg work there is no fabricated percentage. The separate Live contour uses a direct browser-to-ElevenLabs WebSocket and has no durable batch progress or job state.

Migration `0020_provider_part_checkpoints` introduced encrypted completed-part recovery. The current lifecycle keeps unfinished text without a fixed expiry and validates a contiguous leading checkpoint set. Explicit retry restores a complete cached result without source bytes or STT, or continues only safe missing parts. A completed provider attempt with missing/corrupt text never silently authorizes another paid full-file call. Full accepted output, cancellation or explicit terminal resolution retires checkpoints; browser projections omit ciphertext and cryptographic authority.

## High-level job state transitions

```text
queued
  -> processing (after atomic claim/lease and lifecycle checks)
  -> completed (only after persisted output evidence for all required relations)
  -> failed (normalized safe failure)
  -> queued (only from allowlisted retry-safe failure after bounded backoff)
  -> cancelled (safe terminal cancellation where allowed)
```

Lease loss, cancellation uncertainty, provider/Google errors, output-side-effect uncertainty, or post-create persistence failures must fail closed and preserve safe evidence for reconciliation. The system must not automatically duplicate provider calls or Google document creation when side effects are uncertain.

## Trust and safety boundaries

- Durable credentials, refresh/ID tokens, and provider secrets are server-only and encrypted at rest where persisted.
- OAuth codes, raw payloads, owners/permissions, source bytes, ordinary transcript/document bodies, object keys, private paths, and stack traces are not browser payloads. The bounded capability responses above and the authenticated owner-scoped temporary Live recovery DTO are the only explicit content/integration exceptions.
- Diagnostics and validation evidence must be allowlisted and redacted.
- Output links shown to the browser must be validated safe Google web-view metadata and owner-scoped.
- Production evidence must not record secret values, document IDs/URLs, transcript bodies, private account data, source bytes, raw provider responses, or raw Google responses.

## Deployment shape

The repository contains Studio deployment and workflow files, but architecture does not authorize deployment behavior. Routine delivery/recovery follows [AGENTS](../AGENTS.md) and [Studio operations](runbooks/studio-platform-ops.md); [CI/CD rules](ci-cd-rules.md) apply when configuring or repairing the pipeline.

Current important distinction: web/API deployment, migration application,
maintenance OAuth runtime configuration, worker-running, bounded core processing
evidence, and transcript-maintenance rollout are separate states. Ordinary
component CD must not silently run migrations, start workers, populate secrets,
or claim maintenance/processing readiness. The protected migration lane is a
separate stateful release path: an environment-bound job can expose the
exact-SHA forced-command release only after the externally configured
protection rules allow it to proceed, while the VPS runner owns candidate-image
identity, new tagged backup and isolated dump verification, exactly one
additive migration, API-only recreation, and health checks. Workflow binding or
success alone does not prove a reviewer pause; the separate no-op environment
probe validates that external control without checkout, secrets, or VPS access.
The release lane never owns worker, provider, Google, nginx, restore, downgrade,
retry, or rollback actions. Current factual revisions, run IDs, component
outcomes, and blockers belong in
`docs/delivery-plan.md`; current processing invariants are in
`docs/studio-processing-contract.md`.

Host browser-header delivery has its own non-stateful protected edge path. The
repository owns one canonical six-header snippet, while the active host site
only includes the fixed runtime snippet path. A manual exact-main workflow may
reach a dedicated root forced command after environment approval; the VPS
release program can back up and replace only that snippet, syntax-check/reload
nginx, verify exact local/public headers and API health, and restore the backup
on post-mutation failure. This path owns no site rewrite, container, database,
worker, secret, Google, or provider operation and is distinct from both ordinary
component CD and the protected migration lane.

## Observability, audit and operational-alert authority

The browser creates one opaque bounded `trace_id` for each API request. The API
accepts only the canonical shape or replaces it, echoes the effective value in
`X-Trace-ID`, keeps it in request-local context and snapshots the job-creation
trace on transcription and audio-preparation jobs. Worker diagnostics recover
that trace only through the exact owner/job relation. Diagnostic and audit
projections may expose the opaque identifier for support correlation, but never
derive it from or attach transcript content, storage identity, provider payload
or credentials. External providers do not receive Studio trace headers; the
allowlisted local result/error event is the external-boundary correlation point.

Every newly written audit row has one bounded operation outcome. Null remains
reserved for legacy rows and is projected honestly as `legacy_unknown`. An
additive PostgreSQL trigger rejects update/delete of historical audit rows even
for ordinary application credentials; worker grants likewise exclude those
operations. Maintenance/migration ownership remains explicit and separate from
History/Analytics clear behavior.

Operational alerts are PostgreSQL-owned state, not log scraping and not a second
queue. One `OperationalIncident` per owner/kind carries a lifecycle generation,
aggregate evidence and safe summary. `OperationalAlertDelivery` owns the unique
generation/kind/channel attempt, short claim, bounded retry and terminal outcome.
The idle worker evaluates bounded database/diagnostic/account signals, commits a
delivery claim before releasing the transaction, performs optional Telegram I/O
without a database transaction, then commits only a safe result code. It sends no
user job notification and performs no remediation, restart, retry or deletion.

The owner-facing Support settings API reads only owner-scoped incidents and the
latest delivery state. It exposes explicit `ready`, `not_configured`, `pending`,
`firing`, `acknowledged`, `resolved`, `delivered`, `failed` or `suppressed`
states without trace IDs or raw evidence. Email remains an honest
`not_configured` health dimension. Telegram credentials are optional separate
file-backed runtime secrets mounted only into API/worker; message text is a fixed
allowlisted Russian summary. Backup automation can append a success/failure
audit outcome through the running API for one explicitly configured personal
owner, but alert-recording failure never changes the authoritative backup exit
code.

## Worker operational boundary

The `studio-worker` is a distinct manual-only runtime component that uses the Studio API source build context but has its own operational image namespace (`elevenlabs-studio-worker:*`), process command, and Docker healthcheck. Process-only liveness validates PID 1 shape without touching configuration or dependencies. Docker readiness additionally requires valid component-baked identity, PostgreSQL access, exact current schema, and a fresh authoritative heartbeat from the same container-process incarnation and commit. It is not a job-progress authority, provider/Google readiness check, lease-correctness proof, canary result, or production-live processing claim.

Worker image identity is verified separately from mutable local tags by comparing the intended commit-specific worker image identity with the running container image ID. Its runtime heartbeat contains only opaque process identity, release/build/commit identity and timestamps; it is distinct from job lease heartbeats and never claims work. Pause means a gracefully drained/stopped container, not a frozen process. The worker remains one-job-per-process and PostgreSQL remains the processing authority; Redis is not introduced as a queue, lease, retry, or job-heartbeat authority. Long source/provider and Google output stages use a bounded stage-scoped heartbeat thread that creates a fresh PostgreSQL session for each exact owner/generation lease renewal and stops before the worker iteration can continue.

## Studio output reconciliation component

Source-level Studio architecture now includes `TranscriptionOutputReconciliation` PostgreSQL rows, an internal Drive appProperty token on Google Docs creates, a reconciliation Drive lookup helper, a dedicated `job_output_reconciliation` service, owner-scoped API endpoints, safe diagnostics, and a minimal PWA action. The component bridges uncertain external Google Docs side effects back to PostgreSQL output evidence without provider calls, Google Docs create/delete, document-body reads, manual document-ID attachment, or title-only matching.

The API remains the trust boundary: browsers see only aggregate reconciliation status and safe counts. Tokens, document IDs, folder IDs, raw URLs before output persistence, appProperties, raw Google payloads, transcript text, document body, and lease metadata remain server-only.

## Studio history and transcription analytics component

History and analytics use project-scoped non-destructive reset boundaries. Setting
`projects.history_reset_at` hides terminal jobs finished at or before the reset,
but active queued/processing jobs remain visible and may reappear as new terminal
history after they finish. Setting `projects.analytics_reset_at` makes aggregate
queries include only jobs created after the reset and consistently restricts
job-source, output, and attempt counts to those jobs. Neither operation deletes
jobs, attempts, outputs, sources, documents, or audit events, and both require an
explicit owner confirmation recorded by a safe audit event.

The project-scoped transcription analytics read path aggregates existing PostgreSQL job, job-source, output, credential-provider, and source-attempt authority without adding a separate analytics table or browser-visible raw events. The API reports safe all-time or since-reset totals, outcome/configuration counts, and duration summaries with sample coverage. Its explicit success percentage is `completed / (completed + failed + cancelled)`; queued and processing jobs do not enter that denominator, and an empty terminal denominator remains `null` rather than a fabricated zero. Queue and whole-job processing use complete job lifecycle intervals; provider and combined post-provider-output timing use complete source-attempt intervals. Missing, unfinished, or negative intervals are excluded rather than estimated.

The PWA requests analytics only when the user opens the project analytics panel and validates an exact aggregate DTO before rendering it. Project/job/source/output identifiers, filenames, titles, credentials, storage metadata, Google identifiers/URLs, raw timestamps, failure detail, provider payloads, and transcript/document content remain server-only. The combined post-provider interval may include part merging and Google Docs persistence and must not be presented as a Google-only measurement.

The account preference `users.accent_color` is an allowlisted owner-scoped value
(`blue`, `violet`, `teal`, or `rose`). Session/login DTOs carry only that safe
preference, and the browser applies the matching CSS token palette immediately;
theme mode and accent color remain independent settings.

## Studio source lifecycle component map

| Component | Responsibility | Boundary |
|---|---|---|
| Source deletion API | Owner-scoped logical deletion, safe blocker reasons, audit/diagnostics. | Commits durable PostgreSQL state before any local object cleanup attempt; never mutates Google Drive files. |
| Source expiry authority | Stores the pending-upload deadline at initiation and replaces it after exact object metadata verification using the effective owner preference (3/7/30 days for new transcription uploads; legacy short preferences map to3 days without rewriting existing expiries). Audio inputs use their separate selected3/7/30-day policy. | PostgreSQL user preference plus `sources.expires_at` are authoritative; the PWA changes the allowlisted preference through the API and displays the exact source deadline. |
| Active source read boundary | Returns only sources eligible to remain in current intake; expired local rows are omitted. | Filtering does not delete durable source metadata, job relations, outputs, history or audit evidence. |
| Source creation authority | Persists timezone-aware Google Drive `createdTime` or embedded media `creation_time` with explicit provenance. | Unknown remains null; modification/upload/job/output clocks are not substituted. The immutable processing snapshot supplies this value to new transcript metadata. |
| Output-folder Favorites | Stores owner-scoped verified Google Drive folder identity and safe link metadata. | Saving and every composer reuse perform server-side Drive verification; stored identity alone is not current write authorization. |
| Source cleanup service | PostgreSQL-backed cleanup claim, lease/generation fencing, idempotent local object delete, retention-expiry marking. | Holds row locks only for claim/finalization transactions, not during S3/R2 I/O; does not call providers, Google Drive, Google Docs, or output reconciliation. |
| Studio worker idle maintenance | Retires only explicitly cleared/cancelled/completed recovery text, then processes at most one source cleanup candidate only when no processing job is claimed. Retained Live/unfinished text has no fixed TTL. | No cleanup thread, Redis queue, production rollout, migration execution, transcript-body logging or canary is implied by source-level code. |

## Domain ownership и compatibility inventory

- Audio UI owns parameters and explicit actions; audioOutputNaming, AudioWaveform, AudioResultDownload and localAudioProcessing own naming, visual projection, transfer state and bounded local PCM. API owns owner/CSRF/lease authority; audio_analysis, audio_result_rendering and audio_downloads own decode, rendering and transient delivery. Worker alone executes FFmpeg. JobUsageCostSummary owns the nominal-cost presentation; long_media_preflight and provider_usage_accounting share immutable tariff authority.
- Live capture/session/stream protocol owns media resources and bounded unsent replay. Draft persistence stores encrypted text/metadata independently; network recovery does not consume a used capability or create a second durable session. Transcript maintenance has its own router, durable runs and worker, distinct from batch jobs.
- POST /api/projects/{project_id}/sources/google-drive is deprecated, but retains owner/CSRF and fresh metadata checks plus Deprecation/Link headers. Its successor is sources/google-picker. POST /api/projects/{project_id}/jobs is an ElevenLabs-only compatibility entrypoint with the same scope/duplicate guards; its successor is jobs/batch + preflight. Existing API tests cover both routes. PWA intake/enqueue callers use the successor paths.
- /api/transcript-catalog/migration/dry-run and /apply deliberately return410/transcript_maintenance_split_required without external mutations. Successors are the separate standardization and manifest workflows in transcript-maintenance; removing the410 contract would hide the migration instruction from older clients.
- googlePicker.ts remains the PWA facade for all current picker callers. Its catalog-folder/native bridge has only checked-in test callers; current product modes use GoogleDriveFolderPickerDialog. No sunset is set without evidence about older cached frontend callers. This is compatibility code, not a second canonical UX.
- Thin notebooks execute elevenlabs_api.py / elevenlabs_realtime.py and remain real entrypoints. Yandex relay imports checked-in generated protobuf; its source is the adjacent proto and its generator/wire regression are documented in the Live implementation. No generated output or notebook is removed as dead code.

External clients and old cached PWA assets are not observable from repository imports alone. Operator review may count legacy requests in existing redacted access records by path (never query/token/body) and source.google_drive.created audit events; absence from a bounded sample is not proof of no consumer. A future removal requires an explicit sunset, caller migration and current-version checks. Existing auth/CSRF and deprecation regressions remain required; there is no removal permission for unknown clients.
