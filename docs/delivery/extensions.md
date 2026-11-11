# Реестр AC: Studio: расширение согласованных сценариев

### `PERSONAL-LOCAL-NEMOTRON-01`

Source snapshot04Nov2026 paragraphs382..386 восстановлен в NEM-01..04 без перенумерации прежних AC. Ни прежний local feasibility probe, ни наличие модели на PC не доказывают интеграцию со Studio. Denominator/current main readiness пересчитывается в F42; неподтверждённая интеграция не включается в READY.

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
|---|---|---|---|---|---|
| `NEM-01` | READY | PASS | PASS | PASS | Exact 8ad83e3 и CI42366143439/42366616828. Owner PC/model, preflight/create и no cloud fallback проверены current local API tests. |
| `NEM-02` | READY | PASS | PASS | PASS | PR350/main `ddd2e97`, Linux job128519961671 подтвердил выдачу 51-й задачи в обоих вариантах, безопасную отмену и fences. Main CI42418052529 и API CD42418087978 PASS, runtime readback подтверждён. |
| `NEM-03` | READY | PASS | PASS | PASS | Verified source/result, immutable timeline и encrypted operation cache. Изолированный путь от локального STT до export подтверждён. |
| `NEM-04` | READY | PASS | PASS | PASS | Отрицательные API/UI fixtures: offline/missing runtime/reconnect сохраняют явный выбор без cloud fallback. |

### `PERSONAL-WINDOWS-STT-02`

Отдельный Windows-этап после поставки PR #349. Статусы квалифицированы на `8ad83e3`. Базовые NEM-01…04 учитываются выше; дефект очереди F91 затрагивает обе группы.

| AC | Состояние | Блок одного PR | Evidence / следующий шаг |
|---|---|---|---|
| `LSTT-01` | READY | Каталог | PR #352/main `7d02060`: поиск, курсор, фильтры ASR/gated и сортировка. Main CI42455581157 и readback запроса Parakeet на VPS PASS. |
| `LSTT-02` | READY | Инвентаризация ПК | CPU/RAM/GPU/VRAM/disk на Windows и synthetic unknown/scoped inventory tests. |
| `LSTT-03` | READY | Карточка модели | PR #352/main `7d02060`: точные weights URL, условия доступа, требования и неизвестные значения. Catalog/API и browser CI PASS. |
| `LSTT-04` | READY | Подбор | PR #352/main `7d02060`: признаки обнаружения, целостности и запуска раздельны. Missing/corrupt encoder, прежний inventory и запуск проверены. |
| `LSTT-05` | READY | Локальная проба | Измеряемая короткая локальная проба на Windows payload 0.1.2. |
| `LSTT-06` | READY | Импорт | Verified import fixtures и фактические закреплённые модельные файлы. |
| `LSTT-07` | IN_PROGRESS | Закрытый установщик | F96: 0.1.3 скачивается из Studio, 0.1.4 с `1d5f1d6` прошёл установку и новую привязку в Sandbox. На ПК владельца Nemotron → production Google Doc PASS. В Studio пока выдаётся 0.1.3. 12Nov Windows Sandbox: unsigned кандидат 0.1.5 из `f9eb6ad` с проверенным SHA-256 установился начисто. Setup скачал закреплённые FFmpeg и FFprobe, установленный self-test EXIT 0. Источник проверки — локальный артефакт. После согласованной поставки проверить скачивание и привязку 0.1.5 из итоговой ревизии. |
| `LSTT-08` | READY | Привязка | Proof-bound start/finish, replay/revoke/rotation fixtures и реальный Windows DPAPI self-test. |
| `LSTT-09` | READY | Управление загрузками | PR #352/main `7d02060`: два нарушения SHA-256 с последующим скачиванием исправных bytes. Portable 40 PASS, CI и 0.1.3 поставлены. |
| `LSTT-10` | READY | Управление версиями | PR #352/main `7d02060`: несколько ревизий сосуществуют, выбор явный, удаление занятой версии запрещено. Companion/API regression и CI PASS. |
| `LSTT-11` | READY | Фиксация версии | PR #352/main `7d02060`: сохранённая ревизия проходит claim и результат после обновления каталога. Mismatch отвергается. CI и схема 0046 PASS. |
| `LSTT-12` | READY | Статусы и действия | Exact payload, tray и worker state, start/stop/autostart code/fixtures. Startup пользователя не менялся. |
| `LSTT-13` | READY | Локальная задача | PR350/main `ddd2e97`: Linux job128519961671 подтвердил claim за неподходящей первой страницей и за просроченными исходниками. Synthetic workflow обеих локальных моделей идёт до экспорта без cloud STT. Main CI и API CD PASS. |
| `LSTT-14` | READY | Восстановление | Lease expiry, disconnect/revocation и explicit retry в API fixtures. Физический сон не симулировался. |
| `LSTT-15` | READY | Путь данных | Объяснение в UI и isolated loopback source/result transfer. |
| `LSTT-16` | READY | Разделение расхода | Provider resolver guard и реальный local inference без облачного STT. |

### `AUDIO-QUALITY-PROGRESS-TRIM-01`

Baseline28Oct2026 main4fb10e2: новые критерии0/14; unmerged candidate14/14 CODE READY по реализации и применимым локальным tests, обязательные CI/CD PENDING; существующие waveform/fragments/worker transport переиспользуются, но не доказывают новые условия.

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
|---|---|---|---|---|---|
| `AQP-01` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Catalog and worker fixture dispatch all five profiles through batch, including legacy ElevenLabs/Yandex defaults and provider/model-specific transport. |
| `AQP-02` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Encrypted owner-scoped credential lifecycle plus dedicated provider validation. Synthetic API/UI/adapter tests reject missing configuration or wrong provider before dispatch, without echoing credentials. |
| `AQP-03` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Catalog limits propagate to composer/preflight; validation rejects unsupported language, diarization/dictionary and duration combinations. Negative adapter tests confirm no silent provider fallback. |
| `AQP-04` | READY | PASS | PASS | PENDING | F100 · PR #357 candidate, local synthetic checks. Worker проверяет полный Google Doc до принятия результата, без повторного STT на недоступной проверке. |
| `AQP-05` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Worker stores provider/model and source settings in output/duplicate identity. Prepared output provenance, changed clock and unknown tariff checked without fabricated zero. |
| `AQP-06` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Worker/FFmpeg progress exposes bounded files/bytes/seconds counters; UI model renders current stage and timestamp. Current synthetic media and polling tests confirm real updates. |
| `AQP-07` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Provider wait has indeterminate percent and separate heartbeat/elapsed, durable reconnect/reload and stale response guards. Local progress tests cover polling failure/recovery and stop. |
| `AQP-08` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Native start/end ranges and exact fields, reset, apply and preview playback. Chromium job128519962151 verified original trim/reload and no overflow at 390/768/1280. |
| `AQP-09` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Component and API reject invalid/nonfinite/out-of-bounds ranges. Trim requires explicit WAV/FLAC rather than hidden copy conversion; real media tests preserve source bytes. |
| `AQP-10` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Original ordered clip precedes silence/mono. Real FFmpeg concat WAVE/FLAC and retained-frame tests confirm render and re-render without changing originals. |
| `AQP-11` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Waveform distinguishes amplitude, pause and speech. Native VAD tests verified silence and decoder cancellation in Linux job128519961671; local parser/component tests cover unavailable and bounded metadata. |
| `AQP-12` | READY | PASS | PASS | PENDING | F107 · PR #357 candidate, local synthetic checks. В браузере проверяется верхняя граница PCM до декодирования, неизвестный вход переводится в явный server path. Bounded waveform и zoom/pan сохранены. |
| `AQP-13` | READY | PASS | PASS | PENDING | Recorded source revision/content plus options/sample recipe regenerates after reload without finished S3 object or redetection. Current real PCM conversion/concat/re-edit/render and same-size changed-cloud-source regressions PASS; browser trim/reload PASS. 23bc718..ddbc172. Required current Linux CI/release and single PR/delivery remain PENDING. |
| `AQP-14` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Canonical extensions spec defines identical reference corpus, paired settings and evaluation of text/terms/speakers/completeness/speed/cost, plus explicit budget before provider requests. |


Часть [delivery dashboard](../delivery-plan.md). Полный аудит 2026-10-10 на проверенном `origin/main` `bc5150eb189b44867101ca45b9da201921a99227`; формулировки — [spec](../spec/extensions.md), источник — [trace](../spec/source-trace.md). Все действующие ID повторно оценены по реализации и подходящим проверкам A20261010-CODE/CI; runtime scope/ограничения — A20261010-RUNTIME в плане. CODE/TEST/CI — типы Evidence, а не три процента; ◐ ограничивает проверенные условия. ALIAS/SUPERSEDED исключены. READY не требует ручной приёмки и не доказывает commercial rollout.

### `BRAND-VOICEOPS-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
|---|---|---|---|---|---|
| `BRAND-01` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Fresh local tsc/Vite/PWA build passed. Built HTML, manifest, npm package and current README show VoiceOps Studio; GitHub PR and local origin confirm Just9120/voiceops-studio. Provider/compatible entrypoint names remain in their actual roles. |
| `BRAND-02` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Browser job128519962151: public about/privacy/terms на 390/768/1280, прямой URL/reload, клавиатура, навигация, без API. Production smoke из PR337; заново проверялся CI artifact, не production. |
| `BRAND-03` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. GitHub PR337 merged as 0cf7f72. Main CI39950863307 and web CD39950923150 passed exact-revision, trust and component gates. Linux job128519961671 passed legacy remote, wrong revision and wrong SSH identity negatives. VPS readback confirms canonical origin. Strict ci-required/admin protection from this Goal’s prior verified GitHub readback; fresh gh API returned 401. |
| `BRAND-04` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. PR337 diff and historical post-rename readback preserve GCP IDs and state identities. Current readback confirms unchanged deployment directory/Compose project, healthy PostgreSQL with schema 0045 and GCP project ID braided-potion-499918-k4. Exact Linux tests pass both Colab launcher integrity cases. F90 still tracks reviewed release ref and reproducibility. |
| `BRAND-05` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. GCP projects describe returned ACTIVE VoiceOps Studio on the existing ID. PR337 exact web deployment passed. VPS web build and public /build-meta.json match 8ad83e3, about/privacy/terms respond 200 and show the brand, API/worker healthy, schema 0045. OAuth client settings and publication were not changed or reverified in this check. |

### `RESULTS-STUDIO-02`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `RS-01` | READY | PASS | PASS | PENDING | Every saved Live session has its own selector/read/copy/export/clear path and lazy owner-scoped history; new capture does not hide previous text. Backend realtime tests, history/component tests, real Chromium IndexedDB migration/isolation and full web cohort PASS. a7145ca. Required current Linux CI/release and single PR/delivery remain PENDING. |
| `RS-02` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Unit test распаковывает DOCX и проверяет transcript_doc, metadata, стили речи/спикеров и XML escaping. Panel экспортирует сохранённый draft локально. |
| `RS-03` | READY | PASS | PASS | PENDING | One accessible continue/stop/cancel dialog; continue preserves capture while stream/timestamp cutoffs discard old refinements across reconnect. Current Live/ConfirmClearDialog and server tombstone regressions PASS; focus/history browser coverage PASS. dc301a8; no paid Live. Required current Linux CI/release and single PR/delivery remain PENDING. |
| `RS-04` | SUPERSEDED | — | — | — | A20261010-CODE/CI; Q125/Q128/Q129: cloud-free текст относится к Live, обычный результат — внешний документ; ID/связи сохранены, реализация отменённого поведения не требуется. |
| `RS-05` | READY | PASS | PASS | PENDING | F100 · PR #357 candidate, local synthetic checks. Readback разделяет экспорт и факт сохранения полного документа; восстановление проверяет существующий результат. |
| `RS-06` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Worker regression сохраняет зашифрованный STT checkpoint при export failure, восстанавливает через 30 дней без нового STT. Cleanup test сохраняет незавершённое через 90 дней и удаляет после отмены. |
| `RS-07` | ALIAS | — | — | — | Audit quality review: Live TXT/recovered download уже PR-05/11; не считать дважды. |
| `RS-08` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Google и Yandex synthetic worker regressions восстанавливают полный cache для export-only, не обращаются к provider повторно, не тарифицируют экспорт как новую попытку. Partial/corrupt cache не заменяется скрытым платным запуском. |
| `RS-09` | ALIAS | — | — | — | Audit quality review: Live TXT/recovered download уже PR-05/11; не считать дважды. |
| `RS-10` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Unit: real cue timestamps, раздельные clocks сессий, gap/refinement и запрет смешанных/выдуманных таймкодов. Panel сохраняет выбранный timed session. |
| `RS-11` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. SRT/VTT отключены для неполных/невалидных таймкодов, partial и смешанных сессий. Panel и exporter tests проверяют ограничение и понятное объяснение. |
| `RS-12` | SUPERSEDED | — | — | — | A20261010-CODE/CI; Q146/Q150: success только полный документ, без обещания восстановления утраченного внешнего документа; ID/связи сохранены, реализация отменённого поведения не требуется. |
| `RS-13` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Owner/CSRF/no-store route, cutoff и bounded snapshot без текста/секретов. Fake Drive подтверждает повтор без дубля и отсутствие записи при read-only folder. Component: cancel не вызывает export. |
| `RS-14` | SUPERSEDED | — | — | — | A20261010-CODE/CI; Q125/Q131: постоянная обычная копия в S3 исключена; Live и transient text отдельны; ID/связи сохранены, реализация отменённого поведения не требуется. |
| `RS-15` | SUPERSEDED | — | — | — | A20261010-CODE/CI; Q118/Q162: 3/7/30 относится к device source, Live без TTL; ID/связи сохранены, реализация отменённого поведения не требуется. |
| `RS-16` | SUPERSEDED | — | — | — | A20261010-CODE/CI; Q118/Q164: expiry источника не expiry Live; ID/связи сохранены, реализация отменённого поведения не требуется. |
| `RS-17` | SUPERSEDED | — | — | — | A20261010-CODE/CI; Q165/Q170/Q174: очистка текста/исходников разделена; ID/связи сохранены, реализация отменённого поведения не требуется. |

### `YANDEX-DISK-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `YD-01` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Separate owner/session-bound OAuth with PKCE, encrypted refresh and one-use callback. Linux job128519961671 confirms callback authority. Historical consent readback after PR343. |
| `YD-02` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Picker supports one/multiple files, ordered selection and owner-bound verified handles. Synthetic intake tests and post-PR344 bounded content download smoke (F79). |
| `YD-03` | READY | PASS | PASS | PENDING | All nested pages collected with explicit media/exclusion preview; empty folders valid, whole enumeration aborts on change, permission failure, cancellation or visible bounds. Pure recursive collector and picker/component tests PASS in full web cohort; all3 picker modes geometry/focus at390/768/1280 PASS. 9f02ce1; backend owner-bound selection contracts preserved. Required current Linux CI/release and single PR/delivery remain PENDING. |
| `YD-04` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Folder-only API mode, search/loading/empty/error and validation of current folder. Browser job128519962151 confirms picker geometry/focus at 390/768/1280. |
| `YD-05` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Synthetic DOCX tests verify complete text, paragraph/speaker styles, target and confirmed full upload. Linux job128519961671 checks persisted output kind. Historical F79 smoke verified exact bytes and cleanup. |
| `YD-06` | SUPERSEDED | — | — | — | A20261010-CODE/CI; Q169: готовое подготовленное аудио скачивается либо сохраняется в Google Drive; ID/связи сохранены, реализация отменённого поведения не требуется. |
| `YD-07` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Create-only transport verifies version and SHA/content when hash is missing. Edit or collision produces conflict without overwrite; lost ACK does not recreate the document. |
| `YD-08` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Disconnect attempts bounded provider revoke and clears local authority even on failure. Synthetic tests cover revoked/expired access, stale refresh, exact owner and grant lifecycle. |
| `YD-09` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Synthetic worker retains cache after quota/access/destination failure and retries only export. Receipts preserve identity; no new SpeechKit request or partial result success. |

### `REALTIME-RECOVERY-03`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `RTC-01` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Controller: session identity и абсолютные offsets сохраняются при смене transport. Component хранит единый draft, Yandex rotation сохраняет capture. |
| `RTC-02` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Controller автоматически берёт новый одноразовый capability и переподключается при timeout/socket failure. Проверены bounded retries. |
| `RTC-03` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Controller повторяет только непереданные frames и сохраняет очередность. Tests: send race/backpressure, replay и segment dedupe с абсолютным временем. |
| `RTC-04` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Overflow и неподтверждённый конец показываются отдельным gap с исходным интервалом. Controller тестирует unconfirmed tail, exporter сохраняет gap в тексте и не выдаёт ложные таймкоды. |
| `RTC-05` | SUPERSEDED | — | — | — | A20261010-CODE/CI; Q117: полная аудиозапись Live не требуется; ID/связи сохранены, реализация отменённого поведения не требуется. |
| `RTC-06` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Controller coalesces stop/final commit. Segment stream/Panel tests: поздние индексированные finals и corrections обновляют нужный фрагмент, сохраняя порядок и повторяющуюся речь. |
| `RTC-07` | SUPERSEDED | — | — | — | A20261010-CODE/CI; Q118/Q120: вместо выбранного TTL — до ручной очистки; ID/связи сохранены, реализация отменённого поведения не требуется. |
| `RTC-08` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Capability выдаётся после явного старта и разрешения на захват; открытие сохранённой сессии и clear/continue не запускают новую платную сессию. Проверено на synthetic controller. |

### `PWA-REQUIREMENTS-05`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `UXN-01` | SUPERSEDED | — | — | — | A20261010-CODE/CI; Q015: пользовательские Projects явно исключены; ID/связи сохранены, реализация отменённого поведения не требуется. |
| `UXN-02` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Naming tests cover known vs missing time, Unicode, concat order and optional title without technical templates. |
| `UXN-03` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Original-clock bounds and fully removed intervals are rejected before batch creation. API/worker tests cover long and prepared sources. |
| `UXN-04` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. App shows selected Google or verified Yandex destination in preflight/restored composer. Owner-scoped API tests reject read-only/foreign/missing targets. |
| `UXN-05` | READY | PASS | PASS | PENDING | User fragment bounds/document anchors refer to original ordered recording, distinct from prepared bytes; unavailable legacy map is explicit. Current timeline/render/word/context fixtures and three-width original trim/reload/fragment browser scenarios PASS. c95d934/35e64c0. Required current Linux CI/release and single PR/delivery remain PENDING. |
| `UXN-06` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Exact Google document tests confirm absent recording date is omitted; prepared output does not substitute export or job time. |
| `UXN-07` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Prepared provenance retains ordered filenames, clip/timeline/processing and verifies selected source version, scope and recipe before/after Google I/O. |
| `UXN-09` | ALIAS | — | — | — | Вне denominator; актуальные AC: UXPOL-07 |

### `MEDIA-CONTRACT-03`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `MC-01` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Required FFmpeg tests cover real codec/container probe, invalid audio, misleading file identity and no provider calls on failed media prep. |
| `MC-03` | READY | PASS | PASS | PENDING | Selected final duration>4h requires source/clip/clock-bound confirmation even with max>12h; preparation maps cost to actual selected bytes. New24h→10h/original15..21h regression quotes6h before STT; changed same-duration clock/context rejects consent.133 shared/native cases and165 media/provider cases PASS; unknown rates stay unavailable, never fake zero. 35e64c0. Required current Linux CI/release and single PR/delivery remain PENDING. |
| `MC-04` | READY | PASS | PASS | PENDING | Default12h/configured limit applies after selection/preparation/concat and before provider splitting, including long original with allowed short clip; video rejected or interval-extracted before whole encode. Current media/provider/clock tests PASS; no provider used for rejected ranges. 7ff827d/0d7699a. Required current Linux CI/release and single PR/delivery remain PENDING. |
| `MC-05` | READY | PASS | PASS | PENDING | F108 · PR #357 candidate, local synthetic checks. Склейка сохраняет слова, действительно повторённые вне overlap, и не полагается на совпадение текста для их удаления. |
| `MC-06` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Provider media tests verify whole diarized request under guards, clip and persisted multipart plan. Part-local labels and end-of-text note tested separately. |
| `MC-07` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Immutable provider plan and checkpoint tests preserve concrete missing ranges and reject incomplete result. UI retains pending/attention state. |
| `MC-08` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Linux Yandex fixtures cover int64 strings, finalRefinement, channel and malformed fields, plus terminal recovery without STT; original-clock projection preserves timestamps. |
| `MC-09` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Catalog selection and relay tests verify REAL_TIME wire without speakers and separate FULL_DATA batch, no deferred fallback. |

### `PERSONAL-VOICE-02`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `VID-01` | SUPERSEDED | — | — | — | Automatic voice identity отменена владельцем25Oct2026; diarization и ручные имена сохраняются. Вне denominator. |
| `VID-02` | SUPERSEDED | — | — | — | Automatic voice identity отменена владельцем25Oct2026; diarization и ручные имена сохраняются. Вне denominator. |
| `VID-03` | SUPERSEDED | — | — | — | Automatic voice identity отменена владельцем25Oct2026; diarization и ручные имена сохраняются. Вне denominator. |
| `VID-04` | SUPERSEDED | — | — | — | Automatic voice identity отменена владельцем25Oct2026; diarization и ручные имена сохраняются. Вне denominator. |
| `VID-05` | SUPERSEDED | — | — | — | Automatic voice identity отменена владельцем25Oct2026; diarization и ручные имена сохраняются. Вне denominator. |

### `SECURITY-LIFECYCLE-03`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `SECX-01` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Authorized CLI requires interactive TTY, existing active admin UUID/email and hidden password confirmation. Owner tests confirm atomic session/trust/reset revocation and preservation of TOTP unless explicitly reset. Negative paths and PostgreSQL CI passed. |
| `SECX-02` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. PostgreSQL auth lifecycle verifies enrollment by valid one-time TOTP, then returns recovery codes once; responses are no-store. |
| `SECX-03` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Recovery rotation calls strict `require_recent_auth` without trusted-browser bypass, requires active factor and replaces verifier set. Login/reauth and rotation regressions cover the shared gate and session lifecycle. |
| `SECX-04` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. PostgreSQL route tests confirm enrollment and rotation revoke other owner sessions, preserve current and foreign sessions. Trusted-device tests confirm disable also revokes browser trust. |
| `SECX-05` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Recovery code tests confirm deterministic one-way verifier after normalization and one-time consumption in login lifecycle. API stores hashes only. |
| `SECX-06` | BLOCKED | PASS | PASS | PASS | F66 · `067065b`. 08Nov loopback SMTP с реальным TLS подтвердил STARTTLS и implicit TLS, отказ до AUTH/MAIL при несовпадении сертификата, 451 → retry → sent, From и очистку outbox. Runtime activation и внешняя доставка требуют подтверждённых домена, SMTP configuration и разрешения на тестовое письмо. |

### `RECOVERY-DATA-03`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `REC-01` | READY | PASS | PASS | PENDING | Owner04Nov:3 latest verified copies per DB/destination, shared3day schedule unchanged. Connected Drive metadata: three archive generations, each16 entries/one Studio dump (872919/907558/907558bytes), bounded pages complete. Latest3 CloudKeep executions: Drive3 targets, S3/Yandex1 each; copy/verify/cleanup PASS. S3/Yandex physical listings not repeated; primary records are their Evidence. No config/backup deletion. |
| `REC-02` | READY | PASS | PASS | PENDING | Regular CloudKeep jobc5e2ee11-1fc9-49bc-8a0c-f5053f72dc0c remains enabled every3days; Studio10h timer disabled. Latest Drive/S3/Yandex target records04Nov pass copy/verify/cleanup. RPO4days/RTO4h and three-copy policy confirmed by owner04Nov; selected actual dump recovery and limitations in REC-01/03..06. No shared schedule change. |
| `REC-03` | READY | PASS | PASS | PENDING | Actual CloudKeep dump442bd085…3c179→isolated PostgreSQL17→candidate0045 migration/decrypt/quarantine/current deletion reconciliation→DB+Redis health/authenticated API PASS. Source revisionadd5563, cached Linux image/fresh source; run1ae757769aa64f36a65ec9f72e655146.423 source rows retained but current deletion respected; stale synthetic Live text cleared. All owned resources and local sensitive payloads cleaned, production healthy. Current Linux CI/release/CD PENDING. |
| `REC-04` | READY | PASS | PASS | PENDING | Owner RPO345600s; actual retained snapshot07:24:42Z age42020.742s at simulated incident, within4days. Current control inventory read separately in read-only snapshot and reconciled before access; synthetic missing-after-backup metadata/false-RPO bounds covered by restore suite.36 local PASS/1 local Docker SKIP, separately actual VPS drill PASS. Does not guarantee complete-disaster availability of deletion inventory. |
| `REC-05` | READY | PASS | PASS | PENDING | Isolated actual-backup application recovery PASS34.296s; full measured download/transfer/recovery/API/cleanup124.186s <14400s. Includes candidate schema, Redis health, current controls and authenticated project/source/Live access. Uses available backup/key/current inventory; real production failover and external grant reactivation not performed. Missing trusted deletion evidence keeps quarantine; target never permits resurrecting cleared text. |
| `REC-06` | READY | PASS | PASS | PENDING | Actual run1ae757769aa64f36a65ec9f72e655146: exact dump identity, snapshot/incident age42020.742s, current deletion reconciliation,0045/DB/Redis health and authenticated API PASS; end-to-end124.186s including copy retrieval/transfer/cleanup. Pure quarantine time not substituted for application readiness. Cached image graph is not current constrained CI/release proof; required CI/CD remain. |
| `REC-07` | READY | ✅ | ✅ | ✅ | Restore quarantine/old-session revocation/deletion inventory protections PR326, CI37428475481 PASS; Cloudkeep restore пока не запускался. Следует той же reviewed quarantine процедуре, не обычному прямому восстановлению production. |
