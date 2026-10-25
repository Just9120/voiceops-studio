# Studio processing contract

## Уточнение согласованного scope 2026-09-30

Согласованный источник revision2994: успешный обычный результат — полный внешний Google Doc либо DOCX на выбранном Яндекс Диске, Studio хранит status/link. Временный STT text сохраняется для незавершённого export-only recovery без нового STT, затем очищается после полного документа либо явной terminal cancellation; история и расход сохраняются. Manifest success устанавливается только после полного документа. PostgreSQL владеет workflow metadata. Готовое подготовленное аудио не получает отдельную постоянную S3-копию: скачивание/экспорт собирает его из доступных исходников по сохранённым параметрам. Источник продуктового scope — [project spec](project-spec.md), Evidence и ограничения — [delivery dashboard](delivery-plan.md).


This is the current Studio processing contract. It is not a delivery plan, PR history, deployment runbook, or proof of production-live processing. Product scope lives in `docs/project-spec.md`; architecture lives in `docs/architecture.md`; rollout procedure lives in `docs/runbooks/studio-platform-ops.md`.

## Yandex Disk destination boundary

`output_provider` distinguishes Google Drive and Yandex Disk independently of the STT
provider. Legacy folder/document field names remain API-compatible; Disk IDs are opaque
owner/account/version handles, not Google file IDs. Source materialization and output
creation recheck account, source, destination, project and lease authority around I/O.

Disk creates a deterministic full DOCX with canonical provider/model/language and
conditional provenance. A committed receipt pins path, SHA256, MD5 and size before
create-only upload; exact strong readback is required before accepted output. A lost
response can recover the same file, while an edited file is never silently replaced.
Confirmed absence permits explicit cache-only export retry; permission/network failures
do not establish absence. Numbered diarization and manual speaker names remain available;
automatic voice identification is not part of this contract.

## Authority

- PostgreSQL is the durable authority for jobs, job-source relations, leases, lifecycle state, output destinations, output rows, and completion decisions.
- Redis is not the processing queue, lease authority, retry authority, scheduler, notification authority, or heartbeat authority.
- Browser clients do not start internal processing directly and must not receive internal lease/claim metadata.
- A worker process handles no more than one primary job at a time. A separate serial housekeeping thread uses its own sessions for cleanup, notifications and alerts while primary work is busy; it never dispatches STT. Primary claim priority rotates across audio, transcription and transcript maintenance. SIGTERM prevents new passes/claims and waits for active boundaries to finish; an operator observation timeout does not kill them.
- Source-level code does not prove production-live processing; controlled rollout evidence is required.

## Runtime progress and preparation cancellation

Runtime heartbeat is conditional on main-thread progress. Idle/claim work has a 120-second operation deadline (error backoff retains its configured allowance); media probes/analysis/processing and provider requests use their existing bounded timeouts plus 30 seconds. A valid 7200-second FFmpeg operation is allowed. Background and lease-heartbeat threads cannot renew main-thread progress. An overdue main loop stops publishing runtime heartbeat, so the existing freshness readiness gate becomes unavailable; this does not restart the process or authorize any provider retry.

Before STT, source streaming checks cancellation and exact lease/source authority between chunks, rate-limited to once per second, using fresh reads closed before further I/O. Media copies check between chunks; owned FFmpeg/ffprobe waits poll every 250ms with the same authority check. Cancellation/lease loss terminates and reaps only the owned media child, closes streams and removes temporary work; no provider request starts. A network read remains bounded by its existing transport timeout. Already-started STT retains the existing uncertainty/accounting/reconciliation rules.

Worker diagnostics serialize only allowlisted event/type/stage/count/status and opaque job/run/iteration IDs. Exception text, traceback, arbitrary extras, file names, provider payloads and credentials are never serialized.

## Claim and lease

- Claim is atomic and must establish exact owner and generation fencing before processing begins.
- Active processing requires an active unexpired lease owned by the exact owner/generation.
- Stale owners, stale generations, expired leases, terminal jobs, cancellation conflicts, or ownership ambiguity fail closed.
- Lease owner, generation, claim timestamp, and lease expiration are internal server-side metadata.
- Lease timestamps are normalized to timezone-aware UTC before comparison.
- A naive datetime value is interpreted as UTC.
- A lease is active only when `lease_expires_at > now`.
- `lease_expires_at == now` means the lease is expired.
- A bounded PostgreSQL-backed heartbeat may run only around one documented long external stage: source materialization/provider work or Google output authorization/metadata/create flow.
- Each heartbeat renewal uses its own database session, applies transaction-local PostgreSQL statement/lock timeouts before the fenced renewal, renews only `lease_expires_at` through exact owner/generation fencing, commits only if stop has not already been requested, and closes; the main orchestration session is never shared across threads.
- Heartbeat is stage-scoped and stops with a strictly bounded two-phase join after the external call; a production heartbeat thread is daemon as a final shutdown safety net, and failure or stop timeout has priority over any simultaneous provider/Google exception, fails closed with normalized `lease_heartbeat_*` reasons, and does not retry provider or Google work.
- `lease_expires_at` is mutable heartbeat state and must not be treated as immutable source/output snapshot identity; lease owner, generation, status, cancellation, project/source/output identity, and active-lease checks remain authoritative. Lease renewal may happen only at documented safe checkpoints or through this bounded PostgreSQL heartbeat, never as Redis, implicit lease recovery, or an unbounded background loop.

## Deterministic processing

- Job-source relations are processed in deterministic order by `position` and then a stable database tie-breaker.
- Skipped relations are ignored for required output coverage.
- An existing persisted output for a relation is authoritative.
- A relation with persisted output must not repeat provider transcription or Google Docs creation.
- Existing output coverage is considered before deciding whether more external work is required.
- A materialized source with a server-validated `video/*` MIME type is converted server-side to AAC/M4A before ElevenLabs submission. The browser does not choose or perform this conversion.
- An optional manual two-project split is represented as two independent single-source jobs with immutable complementary clip ranges and different persisted output-folder snapshots. The first range owns `[0, boundary)` and the second owns `[boundary, source end]`; the boundary is an integer second greater than zero. Configuration cannot change after job creation.
- Manual clip bounds are validated against the duration-probed prepared source before the first provider request. An invalid or out-of-duration range fails closed without a provider call. Each valid clip is created as a temporary server-side AAC/M4A input before the ordinary long-media split policy is evaluated; no clipped media or transcript body is persisted in Studio.
- Video preparation invokes `ffmpeg` without a shell, selects the first audio stream, has a 1,800-second timeout, refuses an empty or deployment-limit-exceeding output, and keeps input/output artifacts inside one temporary directory that is closed after the provider boundary.
- Video-preparation failures are normalized before the provider request-start marker. Lifecycle, lease, cancellation, source, credential, and output identity are revalidated after preparation and immediately before provider submission.
- Every prepared ElevenLabs input is duration-probed server-side. It is split before the first provider request when it exceeds either 25 MiB or 1,320 seconds; parts target 20 MiB and at most 1,320 seconds, are mono AAC at 96 kbit/s, overlap by two seconds, are capped at 256 deterministic ordered parts, and may not exceed the deployment source-size limit in aggregate.
- Part creation is shell-free, timeout-bounded, size-validated, and temporary. Merge assigns the overlap interval to the earlier part, removes an exact repeated word prefix when present, shifts retained word timestamps onto the source timeline, and fails closed if a multi-part response cannot provide the word timing needed for deterministic ownership.
- A part with blank text and no words is valid silence and does not prevent assembly of the other parts. Text without required words/timing is not silently discarded. An empty overall transcript does not authorize Google export or successful completion. Assembly failures emit a fixed safe `transcript_assembly` diagnostic code, never transcript text or provider payloads.
- Provider calls run in part order with lifecycle revalidation between calls. The provider timeout is 1,800 seconds per part and Google Docs upload timeout is 120 seconds. Once any part has returned successfully, a later provider failure is classified as an uncertain partial result and the whole source is not automatically retried.
- Source creation authority is either normalized Google Drive `createdTime` or embedded media `creation_time` persisted with explicit provenance. A missing value remains unknown; browser modification time, upload time, job time and Google Docs creation time are prohibited fallbacks. The Google Docs formatter receives the persisted source value rather than the output clock.
- The current attempt may persist only bounded integer provider-part progress: one prepared total greater than zero and a monotonically increasing completed count no greater than that total. The provider-start checkpoint and total commit before the first call; each successful part count commits only after post-call lifecycle/lease revalidation. A lost or invalid progress commit after provider work fails closed as a partial-provider-result boundary.

## Transaction and commit ownership

- Row locks must not be held across source storage, Drive, provider, or Google Docs external I/O.
- Output authorization and Google Docs creation use the persisted per-job output-folder snapshot.
- The mutable project default output folder must not replace the destination of an existing job.
- Changing a job output-folder snapshot after creation is prohibited except through a separately designed migration/reconciliation operation; no such operation exists now.
- Output persistence is a dedicated transaction boundary.
- The worker commits after each per-source output persistence boundary.
- A commit failure after Google Docs creation is a reconciliation risk.
- When Google creation outcome is uncertain, automatic second Google creation is prohibited.
- Provider calls and Google side effects must not be retried automatically inside the same attempt after an uncertain side effect.

## Output authority

- At most one output row may exist for each non-skipped job-source relation.
- The current schema enforces unique `job_source_id` and unique Google `document_id` for persisted Studio outputs.
- Completion is allowed only after persisted output coverage exists for every non-skipped relation.
- Partial outputs may exist for jobs that are still `processing` or that later become `failed` or `cancelled`.
- Exactly-once Google document creation is not claimed; the database can enforce persisted-row uniqueness but cannot prove external side-effect uniqueness by itself.

## Cancellation and side-effect checkpoints

Processing must re-check lifecycle, lease, ownership, and cancellation at safe boundaries:

1. before source access;
2. before provider submission;
3. after provider completion and before exposing transcript text to the next stage;
4. before Google Docs creation;
5. after Google creation and before output persistence, including heartbeat result validation;
6. after output persistence and before the next source;
7. before final completion.

If cancellation, lease loss, owner/generation mismatch, project/source mutation, credential mutation, output-folder mutation, or terminal transition is observed at a checkpoint, processing must fail closed and preserve only safe normalized evidence.

## Worker loop

- Each processing iteration uses a fresh database session.
- The worker must not keep a database session open during idle sleep.
- SIGTERM/SIGINT requests graceful stop.
- After stop is requested, the worker must not claim another job.
- The worker must not automatically retry the same attempt after provider, Google, persistence, or lifecycle failure.
- Logs and diagnostics must use normalized safe reason codes and must not include secrets, transcript text, source bytes, raw provider payloads, raw Google responses, document IDs/URLs, folder IDs, object keys, presigned URLs, or lease metadata in browser-visible surfaces.

## Browser-safe output

- Output read access is explicit, authenticated, and owner-scoped.
- Partial outputs may be returned for an owned job; job status remains the lifecycle authority.
- Browser payloads may include only validated safe Google or selected Yandex Disk web URL metadata and aggregate output metadata. Output provider is pinned per job and folder handle; the STT provider is independent.
- Browser payloads must not include transcript body, Google document ID, folder ID, lease metadata, provider payloads, Google payloads, source bytes, object keys, private paths, or secret values.
- Browser progress may expose only the safe source display name, fixed stage states, and bounded completed/total provider-part counters. Percentage must derive only from confirmed checkpoints; time-based simulated movement is prohibited.

## Known limitations

- Output reconciliation is source-level and explicit owner-driven; runtime rollout still requires operator migration/deployment evidence.
- Safe stage-specific retry/recovery is source-level and explicit owner-driven; runtime rollout evidence remains pending.
- No generic retry/recovery scheduler for failed long external calls.
- No OpenAI Studio processing path.
- New ElevenLabs diarization prefers one request for the complete selected recording or explicit clip, below the standard provider 5GB file limit and at most 10 hours. Existing source/resource/whole-source duration and cost-confirmation guards apply before this preference; non-diarized splitting is unchanged. A prior durable multipart plan retains its deterministic split on recovery, preventing checkpoint/usage reinterpretation or repeated completed parts. Oversized/longer eligible media retains bounded splitting. Part-local speaker IDs are never equated across independent requests; fallback documents disclose this in one note after the transcript, without an exhaustive speaker-to-part legend before speech. Whole-recording diarization reduces artificial label multiplication but does not guarantee acoustic accuracy or identify named people. Existing Google Docs are not rewritten by this policy.
- **Манифест Studio** may mutate only owner-scoped eligible current-document catalog metadata in PostgreSQL through its explicit dry-run/apply contract; it does not change Google Docs, source bytes, transcript bodies, or provider state.
- No multi-worker production validation.
- No production-live processing claim without controlled rollout validation.

## Output reconciliation

Studio output reconciliation is an explicit owner action for uncertain Google Docs side effects. Processing must prepare and commit a durable reconciliation case before Google Docs creation, then pass an opaque random token to Drive `appProperties`. When Google creation response, lifecycle, heartbeat state, context close, or output persistence is uncertain, the job records `output_reconciliation_required` where lifecycle permits and does not retry provider work or create a second Google Doc.

The reconciliation path performs exact Drive lookup using the opaque appProperty token and the job output-folder snapshot. It does not read transcript text, Google document body, raw provider responses, or raw Google responses. Zero matches remain unresolved; multiple matches become conflict; exactly one verified match may persist one missing output row. Reconciliation does not require an active worker lease, live source bytes, uploaded source status, object-storage availability, or source restoration, and it does not mutate lease owner, lease generation, attempt count, source bytes, or job output-folder snapshot.

An existing unresolved reconciliation case permanently blocks a new Google Docs create for that relation because Drive appProperties are correlation metadata, not an idempotency key. A `prepared` case by itself is internal evidence and does not make owner reconciliation available until it becomes `creation_returned`, `reconciliation_required`, or `conflict`. Pre-create reconciliation-case persistence failure is a safe processing failure, not output uncertainty and not an existing-output race. A `conflict` case is a stable fail-closed state: repeated owner checks report the conflict without selecting a candidate, creating/deleting Google Docs, or reading document body.

## Preflight provider-attempt authority

Batch preflight projects the final provider-call guard into an owner-scoped, per-source browser outcome. For the selected effective provider/model/language/diarization settings, a competing attempt is `in_flight` while its job is processing. A terminal provider failure before any Google Docs creation is not a document and does not block a newly created job, even when the old job itself cannot be retried safely. A failed attempt with started document creation or unresolved output reconciliation remains `unresolved` until the owner explicitly records `acknowledged_no_result`; this history resolution does not retry the old job, erase its accounting, or bypass a separately accepted output. Without that acknowledgement, unknown document creation stays blocked. An inconsistent completed state without persisted output remains `unresolved`. Unknown settings remain conflicting while work or document creation may still be active; attempts with confirmed different settings do not. Google Drive identity may span multiple Studio source rows owned by the same user.

The browser receives `available` or `blocked` plus one allowlisted reason: equivalent provider work is in flight, or an equivalent provider outcome remains unresolved. New clients opt in with `x-studio-preflight-recovery: 1`; only then can preflight also return an owner-scoped terminal job ID whose attention can be resolved. Legacy clients continue to receive the original two-field authority object during the web/API rollout. The owner can confirm the absence of a Google Docs result without finding the job in paginated history or another project. The existing recent-auth attention-resolution endpoint rechecks ownership and eligibility before storing this confirmation; preflight itself remains read-only and never creates a new job. No action ID is returned for in-flight work, persisted accepted output, or an accepted linked catalog result. The browser does not receive private source identity, Drive file ID, provider payload, transcript, credential, lease, or failure detail. An accepted-output reprocessing decision applies only to accepted-output authority and cannot override provider-attempt authority.

Preflight is read-only and can become stale. Batch creation therefore locks the relevant catalog source identities and repeats both accepted-output and provider-attempt checks before creating job or job-source rows. A provider-authority conflict returns a stable browser-safe 409 reason and creates no batch rows. The worker still repeats the same guard immediately before the paid provider boundary; the earlier checks improve UX but never replace the final race-safe authority.

## Safe stage-specific retry and expired-lease recovery

Studio keeps a durable PostgreSQL per-source attempt ledger for retry/recovery decisions. A missing non-skipped job-source must have an attempt row committed before source/provider external work starts. The provider request-start marker is committed immediately before transport; a valid provider response is marked before Google/output work with `provider_result_lost` until output persistence completes.

Same-job retry is available only by explicit owner action and only when durable evidence proves the provider request did not start, or the provider definitively rejected the request before any successful transcription (`provider_authentication_rejected`, `provider_request_rejected`, or `provider_rate_limited`). Timeout, unavailable/connection interruption after request start, malformed response, unknown transport error, lifecycle/lease/heartbeat loss after request start, and a returned provider result without persisted output all block retry. Conservative blocking is preferred over another paid provider call.

Google uncertainty remains governed by output reconciliation. A provider-returned attempt entering Google handoff cannot be retried by calling the provider again; unresolved reconciliation evidence blocks a new Google Docs create. Existing persisted outputs remain authoritative, are skipped by retry/recovery, and partial outputs are preserved.

A full, unexpired encrypted multipart checkpoint set permits explicit owner-only `full_provider_restore_available`: assemble and export already recognized parts without provider calls or new usage accounting. This is distinct from continuation of unfinished parts, which retains its explicit cost confirmation. Owner/project/job/source identity, key/HMAC, part order, count and deterministic media timing must match. A durable fully completed earlier attempt requires the full set at execution as well as enqueue: expiry, cleanup, corruption or mismatch fails closed and cannot fall back to STT. Unresolved Google reconciliation, cancellation, lease/lifecycle gates and the attempt limit remain authoritative. Cached restore is not automatic expired-lease recovery.

Expired processing lease recovery is stage-aware and database-only. It may requeue only when every missing required relation is retry-safe and the job has not reached the retry limit. Unknown/legacy execution state, provider uncertainty, provider-result-lost state, Google handoff/uncertainty, unresolved reconciliation, non-retryable evidence, or three job attempts fail closed. Before each primary claim, the worker scans at most 10 expired processing jobs under PostgreSQL SKIP LOCKED row locks and invokes this database-only lifecycle. Each recovery clears the old owner/lease; the next claim increments generation. A live lease is never recovered. Only durable retry-safe evidence permits requeue. There is no speculative provider retry, Google retry, transcript persistence, or replacement-job creation.

The maximum processing attempts per job is three: the initial attempt plus at most two explicit/safe recovered attempts. Existing failed jobs without source-attempt evidence are treated as legacy/unknown and are not retryable.

### Studio source deletion, retention, and cleanup

Studio source removal is logical, owner-scoped, and durable in PostgreSQL. Source rows are never hard-deleted by the source lifecycle; display metadata, job-source relations, historical jobs, persisted outputs, attempt evidence, and reconciliation cases remain available for history. Google Drive source removal only removes the Studio reference: Studio must not delete, trash, update, or otherwise mutate the external Drive file, and Google Docs outputs are not removed by this flow.

Local-upload bytes use an asynchronous, idempotent cleanup lifecycle stored on `sources`. S3/R2 delete is allowed only after durable logical deletion or retention expiry state exists. A missing object is treated as successful physical cleanup; storage failures do not roll back logical deletion and are retried through durable cleanup state. Object storage identity is cleared only after successful cleanup finalization; browser payloads must not expose bucket/object keys, cleanup owners, cleanup generations, cleanup leases, cleanup attempt counts, cleanup errors, or internal job references.

Pending local uploads expire one hour after initiation by default. Verified completion resets `expires_at` from the authenticated owner's PostgreSQL-backed account preference: one hour, 24 hours (default), three days, seven days, or 30 days for ordinary references. Audio-processing references use the separately persisted per-job selection of three, seven (default), or30 days; success/failure/cancellation does not shorten this choice. One-shot new device transcription uploads are logically retired only after every linked job completes and every full document is accepted, with active audio uses still protected. Legacy uploads do not enroll automatically. Preference changes are owner-scoped, CSRF-protected, allowlisted server-side, and apply only to future verified completions; browser-local state is not retention authority. The browser presign remains a separate capability with a maximum lifetime of 15 minutes. Completed local-source payloads expose the exact expiry so the PWA can show it, while Google Drive inputs and Google Docs outputs are outside this retention rule.

Maximum source bytes and supported MIME rules are server policy. The authenticated PWA may read only those safe values plus a local-upload availability boolean through the `no-store` source-upload policy DTO so it can reject unsupported local selections early; unavailable storage or malformed/unavailable policy disables direct local upload. This browser check never replaces server validation at initiation, exact stored-object metadata verification, source availability, or materialization.

Local sources expire when `expires_at <= now`. Expiry blocks new jobs, claims, explicit retries, expired-lease recovery, upload completion, and processing-time source access. Retention expiry may mark a local source `expired` with `delete_reason=retention_expired` without setting `deleted_at`; the active project source collection omits both elapsed and status-expired local rows while durable metadata and historical job relations remain available through history-specific reads. A referencing `processing` job defers physical cleanup until terminal/recovered state; cleanup never calls the provider, Google Drive, Google Docs, output reconciliation, or attempt-ledger mutation. Explicit owner deletion abandons retries of terminal failed jobs while preserving their history and external originals. Queued/processing transcription jobs and active audio input/output use still block deletion. Automated ephemeral cleanup retains the conservative retryable-failure guard; bulk preview/apply follows the explicit owner policy and rechecks active references.

## Сохранение готового аудио в Drive

По AP-23 готовый output можно сохранить отдельно от обработки. `POST /api/audio-preparations/{job_id}/save-to-drive` проверяет owner, CSRF/origin и выбранную папку. `status=completed` сохраняется; `current_stage=google_drive_export_queued/google_drive_upload` представляет активный export и продолжает polling. Старый worker игнорирует completed row, поэтому rolling update не запускает FFmpeg повторно. Новый worker использует существующие lease/generation/heartbeat, читает только готовый output из его storage class и применяет существующий Drive idempotency marker job ID. Истёкший/удалённый source не восстанавливается.

Error/cancel оставляют download и source доступными по действующей retention policy. Пока export активен, явная очистка не удаляет output. Повтор проверяет ту же папку; новый target после неопределённого результата не подменяется. Если Drive уже завершил передачу до обработки отмены, сохраняется подтверждённая ссылка: отмена не удаляет созданный remote файл. Schema и OAuth scopes не расширяются; поставка затрагивает web, API и worker.

Auto-save использует те же export состояния: completed/output_source_id фиксируются до Google I/O, входные ephemeral references больше не удерживаются готовой обработкой. Resumable upload отправляет отдельные 8 MiB chunks с Content-Range, использует подтверждённый Range, проверяет состояние той же upload session после потерянного ответа и ограничивает retries/no-progress. Между запросами проверяются cancellation/lease; timeout каждого запроса 60 секунд. Подтверждённый конечный ответ и reconciliation требуют совпадения размера готового файла. Stage progress отражает подтверждённую передачу, а не неизменные 92%.

Для legacy unlinked output доступен owner/CSRF/origin `POST /api/audio-preparations/{job_id}/recover-output`. Восстановление разрешено только для persisted uploaded output с детерминированным job ID, точным project/owner key, audio storage class и действующей retention. Оно не запускает FFmpeg/STT/Google, не забирает активную lease и не превращает неизвестный внешний export в подтверждённый. Истёкшая legacy processing lease восстанавливается через тот же output при следующем claim; failed/cancelled result восстанавливается только явно. Download/export проверяют storage identity и наличие bytes отдельно.


## Durable document identity и provenance

Новые batch jobs сохраняют выбранную модель в internal options `_stt_model`; transport и accepted-result identity используют этот snapshot вместо позднее изменённых defaults. Документ берёт provider из job, model из snapshot/owned immutable provider operation или part checkpoints; конфликтующая identity отображается unknown, а не другим провайдером. Historical jobs без нового snapshot сохраняют старый контракт, без чтения новых defaults в analytics.

Header содержит Provider/Model/Language. По решению владельца24Oct2026 Source/Preparation IDs, Speakers boolean, Recording date provenance и recipe JSON остаются в Studio и не выводятся в документ. Реальная календарная дата в title — только display hint для пропуска дублирующего Created at, не источник authority/сортировки. Без даты в title известная дата записи может выводиться в ISO8601; неизвестная пропускается, job/document/modified timestamps не заменяют её. Catalog принимает compact header без Speakers/Created at и старые полные headers; существующий видимый конфликт с подтверждённой source date проверяется как прежде. Standardization не возвращает технический шум.

Prepared/clip provenance выводится только в полезном для чтения виде: ordered Original source filenames для подготовленного/объединённого аудио, Timeline, Clip/Segment time range и одна строка Audio processing с сокращением пауз/изменением каналов/форматом. При сокращении пауз явно указано отличие timeline от исходной записи. Полный immutable snapshot с IDs/recipe/dates остаётся внутренним и сравнивается до/после Google side effect; изменение даже скрытого recipe по-прежнему блокирует подтверждение вывода. Export creation date не считается recording date; при partially known concat общая дата пропускается. Только exact owned preparation linkage допустим; filename match и foreign inputs не дают authority. Speaker uncertainty notes и речь сохраняются.
