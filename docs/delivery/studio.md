# Реестр AC: Studio: существующие personal-подсистемы

Часть [delivery dashboard](../delivery-plan.md). Полный аудит 2026-10-10 на проверенном `origin/main` `bc5150eb189b44867101ca45b9da201921a99227`; формулировки — [spec](../spec/studio.md), источник — [trace](../spec/source-trace.md). Все действующие ID повторно оценены по реализации и подходящим проверкам A20261010-CODE/CI; runtime scope/ограничения — A20261010-RUNTIME в плане. CODE/TEST/CI — типы Evidence, а не три процента; ◐ ограничивает проверенные условия. ALIAS/SUPERSEDED исключены. READY не требует ручной приёмки и не доказывает commercial rollout.

### `PWA-CORE-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PC-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PC-02` | READY | ✅ | ✅ | ✅ | V26-BROWSER + V26-CD + V26-CI; полный узкий AC подтверждён |
| `PC-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PC-04` | READY | ✅ | ✅ | ✅ | V26-BROWSER + V26-CD + V26-CI; полный узкий AC подтверждён |
| `PC-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PC-06` | READY | ✅ | ✅ | ✅ | 07Nov, main 8ad83e3: Settings и App.test.tsx проверены на создание, замену, отключение и удаление ключей. Сценарии Vitest используют synthetic API. |
| `PC-07` | READY | ✅ | ✅ | ✅ | 07Nov, код OAuth одинаков на main 8ad83e3 и PR350. В Linux/PostgreSQL job128519961671 прошли изоляция владельцев и пять сценариев отклонения callback вне исходной сессии. Локальная PostgreSQL fixture не подготовилась, свежие provider calls не выполнялись. F46 закрыт ранее в #320. |
| `PC-08` | READY | ✅ | ✅ | ✅ | 07Nov, main 8ad83e3: production R2 boundary сверена при аудите. test_studio_reference_storage.py проверяет выбор точного bucket и S3 multipart. В этой перепроверке новый объект в R2 не создавался. |
| `PC-09` | READY | ✅ | ✅ | ✅ | 07Nov, main 8ad83e3: в Settings проверены выбор retention, сохранение и чтение подтверждённого значения. App.test.tsx и test_studio_retention_admission.py, synthetic. |
| `PC-10` | READY | ✅ | ✅ | ✅ | 07Nov, main 8ad83e3: test_studio_source_deletion.py проверяет expiry, retry и lease fencing. test_studio_reference_storage.py проверяет повторяемое удаление, exact-key scope и подтверждение отсутствия объекта через synthetic S3. |
| `PC-11` | READY | ✅ | ✅ | ✅ | 07Nov, main 8ad83e3: browser visibility predicate скрывает просроченные источники без действующей отсрочки. test_studio_source_deletion.py проверяет скрытые записи и исключение активной обработки. |
| `PC-12` | READY | ✅ | ✅ | ✅ | 07Nov, main 8ad83e3: Appearance предлагает system, light и dark. theme.test.ts проверяет определение системной темы, применение явного выбора и безопасное сохранение. |
| `PC-13` | READY | ✅ | ✅ | ✅ | 07Nov, main 8ad83e3: Appearance и App.test.tsx проверяют выбор, сохранение через настройки аккаунта и применение цвета интерфейса. |
| `PC-14` | READY | ✅ | ✅ | ✅ | 07Nov, main 8ad83e3: обе формы вычисляют общий процент по фактическим байтам XHR. directUpload.test.ts, AudioPreparationUpload.test.tsx и App.test.tsx проверяют прогресс и подтверждение результата после сбоя без повторного PUT. |
| `PC-15` | READY | ✅ | ✅ | ✅ | Восстановлено по code и primary records 2026-09-30: PR #312/e01bc91, CI 35970014222/35970014302, web CD 35970355470 SUCCESS. |
| `PC-16` | READY | ✅ | ✅ | ✅ | Восстановлено по code и primary records 2026-09-30: PR #312/e01bc91, CI 35970014222/35970014302, web CD 35970355470 SUCCESS. |

### `PWA-USER-EXPERIENCE-02`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PUX-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PUX-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PUX-03` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. App: русские действия, доступный текст состояния диаризации и понятные source/destination. Contract preflight возвращает браузеру безопасное представление без технических идентификаторов в default UI. |
| `PUX-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PUX-05` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. JobCard назначает failed alert/assertive и отдельный danger tone, cancelled status/polite и нейтральный tone. Browser CI подтверждает success-карточку, локальная App выборка — terminal recovery и отмену. |
| `PUX-06` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. JobCardSummary synthetic: известная ошибка локализована, неизвестное сообщение провайдера скрыто, raw код под support disclosure. App synthetic подтверждает локализованную actionable recovery. |
| `PUX-07` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. JobCardSummary tests assert one creation timestamp and safe fallback title. JobDetailSection and JobOutputsSection put job UUID and source/output type codes in details; history uses the same summary/card renderer. |
| `PUX-08` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Live panel puts provider/VAD and reconnect buffer behavior in closed technical disclosures. Main controls and recovery messages explain user actions and text restoration. Synthetic component tests cover stalled checkpoint, recovery and draft clearing. |
| `PUX-09` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Основные действия используют «Проверить», «Применить» и актуальный формат. Technical details отделены; browser CI проверил русские controls в закрытой Google ветке. |
| `PUX-10` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Summary и действия предшествуют списку. Component подтверждает фильтр и ограниченную выдачу длинного списка. |
| `PUX-11` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PUX-12` | READY | ✅ | ✅ | ✅ | 07Nov, код Studio совпадает с main 8ad83e3. Browser job128519962151 проверил Drive picker на 390×844, границы диалога, доступность элементов и блокировку прокрутки страницы. Тесты picker и scroll lock прошли локально. |
| `PUX-13` | READY | ✅ | ✅ | ✅ | 07Nov, main 8ad83e3: один активный индикатор, текущее действие и исходник проверены в JobProgressPipeline.test.tsx, подтверждённые проценты в jobProgressModel.test.ts, автоматическое обновление и recovery в jobProgressPolling.test.ts. |
| `PUX-14` | READY | ✅ | ✅ | ✅ | 07Nov, main 8ad83e3: formDrafts.test.tsx проверяет восстановление метаданных, изоляцию проектов, повреждённое хранилище, сброс согласия на платный обход и очистку при logout. Применимая история PR332/main206c579 сохранена. |
| `PUX-15` | READY | ✅ | ✅ | ✅ | 07Nov, main 8ad83e3: App.test.tsx проверяет Undo с исходным названием и позицией без POST создания задач. Browser job128519962151 подтвердил восстановление двух строк и сохранение после reload на 390/768/1280. |
| `PUX-16` | READY | ✅ | ✅ | ✅ | 07Nov, main 8ad83e3: App.tsx показывает число среди загруженных задач. Browser job128519962151 проверил 10→2 результата при переходе, возврат фокуса и прокрутку, поиск и сброс на 390/768/1280. |
| `PUX-17` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. App synthetic подтверждает exact Settings disclosure, focus и отсутствие OAuth POST. Route push/popstate сохраняет обычный возврат в обслуживание. |
| `PUX-18` | READY | ✅ | ✅ | ✅ | 07Nov, main 8ad83e3: ссылки обзора проходят isApprovedOutputUrl и ResourceExternalLink. resourceLinks.test.tsx проверяет отказ от unsafe URL. Browser job128519962151 проверил прямой href и открытие деталей нужной записи. |
| `PUX-19` | READY | ✅ | ✅ | ✅ | 07Nov, main 8ad83e3: DetailDrawer использует native dialog и восстанавливает фокус и прокрутку. Browser job128519962151 подтвердил ссылку, размеры и Escape с возвратом фокуса на 390/768/1280. documentScrollLock.test.ts подтвердил восстановление позиции. |
| `PUX-20` | READY | ✅ | ✅ | ✅ | 07Nov, main 8ad83e3: App.test.tsx проверяет подтверждение, readback и сохранение заблокированного выбора, отправку dismiss без нового STT. Linux job128519961671 подтвердил точный subset, owner isolation, отказ повтору и сохранность Drive. |
| `PUX-21` | BLOCKED | PARTIAL | PASS | PENDING | F42 · `8ad83e3`. Composer footer uses sticky and safe area. Exact browser CI exercised desktop/mobile-size layout, not a real screen keyboard. Need a mobile keyboard open on the long composer with errors plus scroll/focus to verify CTA and controls remain reachable. |
| `PUX-22` | IN_PROGRESS | PARTIAL | PASS | PENDING | F42/F114 · `8ad83e3`. Single-document input handles Enter/Escape via draft state, segment title input only handles onChange. External document mutation is not involved. |
| `PUX-23` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Composer empty dictionary CTA routes to the exact settings anchor. Empty source UI offers intake and storage actions. Synthetic App tests verify empty source recovery, permission-denied read-only preview and explicit Google maintenance setup without auto-grant. |

Основание PUX-14..23: owner decision14Oct2026 — все правки повторного UX/UI-ревью выбраны единой Goal. Исправления UXR20/21/12/19 уточняют existing AP/PUX/cost AC, сами findings denominator не увеличивают. Черновики хранятся только в текущей browser session; полного восстановления File после закрытия приложения не обещают.


### `PWA-UX-POLISH-03`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `UXPOL-01` | READY | ✅ | ✅ | ✅ | 07Nov, main 8ad83e3: App.test.tsx проверяет задачи и доступные действия в обзоре, empty workspace, раздельные ошибки и retry. Browser job128519962151 проверил быстрые действия и ссылки на готовые документы. |
| `UXPOL-02` | SUPERSEDED | — | — | — | Вне denominator; актуальные AC: PTM-01 |
| `UXPOL-03` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. DryRunResult/ApplyResult сворачиваются. «Закрыть результат» сбрасывает только локальные state и доступно лишь после завершения. List tests подтверждают прогрессивный показ. |
| `UXPOL-04` | READY | ✅ | ✅ | ✅ | 07Nov, main 8ad83e3: App.tsx показывает системные предупреждения отдельно от раскрываемых версий, схемы и проб. App.test.tsx подтвердил эти разделы, состояния и фильтрацию технических данных. |
| `UXPOL-05` | READY | ✅ | ✅ | ✅ | 07Nov, main 8ad83e3: диагностический список запрашивает страницы по курсору. App.test.tsx проверяет фильтры до первой страницы, cursor для следующей, локализованные события и allowlist раскрываемых метаданных. |
| `UXPOL-06` | READY | ✅ | ✅ | ✅ | 07Nov, main 8ad83e3: App.tsx показывает отдельные подписи и объяснение для JSON и Markdown. App.test.tsx проверяет оба формата и отсутствие запросов к остальным форматам в штатном сценарии. |
| `UXPOL-07` | IN_PROGRESS | PARTIAL | PASS | PENDING | F42/F109 · `8ad83e3`. App synthetic подтверждает case-insensitive поиск по коду события и выбор. UUID операции/задачи присутствуют в ответе, но UI не ищет по ним. |
| `UXPOL-08` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. ElevenLabsAccountPanel synthetic покрывает plan/remaining/overage/invoice, PAYG и недостаточные scopes. В коде raw units/provenance вынесены в отдельный details. Без запроса к ElevenLabs. |

### `PWA-UX-CONTROLS-04`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `UXCTL-01` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Provider mode capability фильтрует эквивалентные варианты. App: ElevenLabs показывает один эффективный scribe_v2 без лишнего selector. |
| `UXCTL-02` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. App: до отправки показываются модель, способ обработки и границы сравнения стоимости. Тест подтверждает объяснение effective mode. |
| `UXCTL-03` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. App: checkbox открывает controls фрагментации, отключённый checkbox не показывает границы. Редактирование числа фрагментов имеет validation. |
| `UXCTL-04` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. App: общая папка наследуется строками и фрагментами, preflight request подтверждает default при отсутствии override. |
| `UXCTL-05` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. App: favorite перепроверяется отдельно для фрагмента, preflight получает разные resolved destination IDs. PostgreSQL CI: произвольные сегменты и раздельные назначения. |
| `UXCTL-06` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. App synthetic сохраняет dismissed attention job в текущем списке после очистки. JobCard использует нативный details без вызова API при раскрытии, кнопка закрытия недоступна без recovery. |
| `UXCTL-07` | IN_PROGRESS | PARTIAL | PASS | PENDING | F42/F100 · `8ad83e3`. Exact Linux CI confirms owner/replay/audit and UI gives the cost warning. Linking treats a completed job with an output row as confirmed, including Google outputs accepted without content readback. |
| `UXCTL-08` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. ElevenLabs transport/parser keeps subscription and PAYG separate. Panel tests distinguish billing mode from plan name and leave missing values explicitly unknown. |
| `UXCTL-09` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Panel explicitly says provider has not reported order of spending subscription versus PAYG. Transport keeps unit distinctions and UI never derives a priority from counters. |
| `UXCTL-10` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Preview показывает eligible/blocked count, bytes и причины; SQLite tests проверяют скрытые expired rows и исключение Drive, App проверяет текст и выбор. |
| `UXCTL-11` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. App требует подтверждения и показывает итог, PostgreSQL job128519961671 подтверждает точный subset, отказ replay/foreign scope и отсутствие удаления Drive. |
| `UXCTL-12` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. App показывает безопасное описание и действие; расширенные детали/коды остаются под disclosure. Backend строит human summary и нормализует event metadata. |
| `UXCTL-13` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Allowlist diagnostics принимает bounded blocker/source/object type и отбрасывает произвольные поля. UI читает только зарегистрированные метаданные. |
| `UXCTL-14` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Diagnostics показывает свёрнутый журнал, warning/error перед вложенным info. App synthetic подтверждает page_size=25, передачу filters и cursor только на следующей странице. |

### `PWA-TRANSCRIPTIONS-UX-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PT-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PT-02` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. App synthetic подтверждает отсутствие ручного lifecycle, автоматическое создание одного workspace и восстановление неоднозначного ответа без повторного POST. |
| `PT-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PT-04` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. App synthetic сохраняет доступ к двум legacy workspace без ручного lifecycle. Active API list ограничен владельцем и archived_at IS NULL; пересоздание выполняется только при отсутствии active workspace. |

### `PWA-INGEST-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PI-01` | READY | ✅ | ◐ | ✅ | F42 · `8ad83e3`. App: выбор общей и построчной папки, проверка ID и защита от повторного открытия. |
| `PI-02` | READY | ✅ | ◐ | ✅ | F42 · `8ad83e3`. App: сохранение, повторная проверка, выбор и удаление папки из Favorites. |
| `PI-03` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. App: выбор одного OGG с устройства запускает штатную загрузку для нужной строки. |
| `PI-04` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. App: выбор нескольких файлов через обычный input, успешные строки сохраняются при частичном отказе, порядок batch не теряется. |
| `PI-05` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. App: directory input, preview вложенных файлов, фильтрация и создание строк после подтверждения. |
| `PI-06` | READY | ✅ | ◐ | ✅ | F42 · `8ad83e3`. Drive picker: выбирает один файл и возвращает подтверждённый ID через общий source flow. |
| `PI-07` | READY | ✅ | ◐ | ✅ | F42 · `8ad83e3`. Drive picker: несколько файлов, дедупликация между поиском и страницами. App: создание нескольких строк из результата. |
| `PI-08` | READY | ✅ | ◐ | ✅ | F42 · `8ad83e3`. App: preview и явное применение source folder, данные папки проверяются API. |
| `PI-09` | READY | ✅ | ◐ | ✅ | F42 · `8ad83e3`. App: Google multiselect создаёт строки с одной общей папкой, независимые переопределения сохраняются. |
| `PI-10` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. App: Drive folder preview и apply создают строки из проверенных API файлов. Выбор общей папки результата распространяется на обе строки. |
| `PI-11` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. App: source и destination привязаны к строкам при reorder/delete и override. PostgreSQL CI: две one-source задачи, один исходник допустим с разными папками. |

### `PWA-GOOGLE-PICKER-UX-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PG-01` | READY | ✅ | ✅ | ◐ | F42 · `8ad83e3`. Общий фиксированный overlay для всех трёх режимов. Browser job128519962151: границы и прокрутка на 390×844. |
| `PG-02` | READY | ✅ | ◐ | ✅ | F42 · `8ad83e3`. Scroll lock: точные стили и координаты. Общий cleanup диалога при выборе, Escape, ошибке и timeout. |
| `PG-03` | READY | ✅ | ◐ | ✅ | F42 · `8ad83e3`. Drive picker: пустая открытая папка доступна для выбора без вложенной папки. |
| `PG-04` | READY | ✅ | ◐ | ✅ | F42 · `8ad83e3`. Drive picker: общий поиск по имени, открытие результата и подтверждение текущей папки. Output mode отдельно проверен на пустой папке. |
| `PG-05` | READY | ✅ | ◐ | ✅ | F42 · `8ad83e3`. App: только legacy catalog использует native Picker. Source file и output folder идут через общий диалог Studio. |
| `PG-06` | READY | ✅ | ◐ | ✅ | F42 · `8ad83e3`. Drive picker: поиск и пагинация, сохранение и дедупликация выбора, предел 50 файлов. |
| `PG-07` | READY | ✅ | ◐ | ✅ | F42 · `8ad83e3`. Drive picker: общий с output mode диалог. Тест выбирает текущую найденную source folder без дочерних папок. |
| `PG-08` | READY | ✅ | ◐ | ✅ | F42 · `8ad83e3`. Drive picker: поиск по префиксу имени с экранированием, открытие найденной source folder и подтверждение. |
| `PG-09` | READY | ✅ | ◐ | ✅ | F42 · `8ad83e3`. Четыре варианта orderBy. Drive picker: порядок передаётся на сервер, проверены пагинация, смена порядка, сохранение контекста и поздний ответ. |

### `PWA-SEGMENTS-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PS-01` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. App: число фрагментов задаётся вручную, поддерживает промежуточный пустой ввод, отклоняет неполное и недопустимое значение до preflight. |
| `PS-02` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Composer model tests cover adding and preserving three fragments and invalid counts; App and batch API model iterate a variable list within the agreed batch limit. |
| `PS-03` | READY | PASS | PASS | PENDING | audio_timeline/transcript_timeline persist exact clip→original maps through trim/silence/ordered concat/re-edit. Real PCM8k/44.1k/48k, repeat rendering and provider/cache-only projection PASS in current523-test cohort; browser original trim/reload PASS. c95d934..35e64c0. Required current Linux CI/release and single PR/delivery remain PENDING. |
| `PS-04` | READY | PASS | PASS | PENDING | Composer keeps empty count drafts; original start/end/EOF, reverse/out-of-bounds/fully removed intervals rejected before STT. App/clip/API fixtures and current timeline cohort PASS; three-width fragment/reload layout PASS. b1c3875/c95d934. Required current Linux CI/release and single PR/delivery remain PENDING. |
| `PS-05` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Linux job128519961671 verifies independent overlap, gap, open end and out-of-order preflight plus separate jobs for the same source. Worker/output tests verify a document per job and clip projection without creating a permanent source copy. STT and Drive use synthetic fixtures. |

### `PWA-BATCH-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PB-01` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. App: доступное управление diarization. ElevenLabs adapter передаёт `diarize=true`, тесты определяют безопасный ответ без speaker labels. |
| `PB-02` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. App: доступен явный русский. Adapter test подтверждает `language_code=ru` в запросе, PostgreSQL preflight test возвращает `ru`. |
| `PB-03` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. App: доступен явный английский. Adapter test подтверждает `language_code=en`, PostgreSQL batch сохраняет `en` на обеих задачах. |
| `PB-04` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. App: явное автоопределение для поддерживаемого провайдера. ElevenLabs test подтверждает отсутствие language_code при detect. |
| `PB-05` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Server projection использует checkpoint и ограничивает progress. Polling/model/pipeline tests подтверждают обновления, отказ и возобновление; App показывает серверный прогресс. |
| `PB-06` | IN_PROGRESS | PARTIAL | FAIL | PENDING | F100 · `8ad83e3`. Fake Google вернул корректные create/style acknowledgements для пустого Docs. Transport сообщил success, проверка содержимого отсутствует. Happy path и отказ на HTTP ошибке форматирования подтверждены. |
| `PB-07` | IN_PROGRESS | PARTIAL | FAIL | PENDING | F101 · `8ad83e3`. Formatter сохранил неразмеченный текст из 200 синтетических предложений одним абзацем (7691 символ). Исходные переносы и блоки диаризации поддерживаются. |
| `PB-08` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Точное сравнение body подтверждает Provider/Model/Language, отсутствие служебных полей и дублирующей даты. Worker tests сохраняют clip и значимую provenance. |
| `PB-09` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Formatter выводит `Created at` через UTC ISO 8601 только при отсутствии даты в title. Тесты compact metadata и worker provenance. |
| `PB-10` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Worker берёт дату из проверенной source provenance, не из title или даты экспорта. Тесты на unknown date и prepared input. Title date остаётся display hint. |
| `PB-11` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. App: composer и preflight показывают оба текстовых состояния, включение дополнительно выделено классом `is-enabled`. |

### `PWA-AUDIO-PREPARATION-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `AP-01` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. App navigation and browser layout tests show standalone audio section and its title; sidebar order verified in current source. |
| `AP-02` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. AudioPreparationPage: выбор и независимая подготовка одного или нескольких файлов. Service: owner/project isolation и переход preview → start. |
| `AP-03` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Probe/analysis: bounded metadata и FFmpeg с `-xerror`, отсутствие audio stream и повреждённый вход отклоняются. Processor: подготовка требует успешного preview. |
| `AP-04` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. App + service: сортировка по source creation time и сохранение manual order. Проверены имена, не совпадающие с хронологией. |
| `AP-05` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Command/preview: `-c:a copy`, проверка совместимости, отклонение mismatch. Реальный FFmpeg: два WAV, точное совпадение PCM frames в заданном порядке. |
| `AP-06` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Компонент показывает WAV/FLAC. Реальный FFmpeg: обе конверсии дали читаемый выход, длительность проверена через ffprobe. |
| `AP-07` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. FFmpeg graph: mixdown/left/right, неподдерживаемый канал отклоняется. Browser-local: PCM WAV mono и отказ при отсутствии правого канала. |
| `AP-08` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Общий UI ввод трёх параметров и границы normalize/preview. Тесты silence analysis и browser-local подтверждают применение порога длительности. |
| `AP-09` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Preview считает исходную и оценочную длительность до start, тесты known silence и server-side preview. Service отклоняет start до готового preview. |
| `AP-10` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Обработка и название не требуют batch. Component/processor: отдельные задачи, concat и render; FFmpeg graph объединяет conversion/channel/silence. |
| `AP-11` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Audio naming tests подтверждают title/stem, Unicode и точки. Fake Drive upload получил `Лекция 1. Предмет.flac`; download payload и legacy Studio Source используют тот же filename, storage key вычисляется отдельно. Ранее: V27 / PR #302: full dotted Unicode title, processor/API и actual local download; web/API/worker 84ae25f. Новый Drive side effect не выполнялся в проверках агента; это ограничение Evidence |
| `AP-12` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Общие preset controls для трёх сценариев. Component/normalize: эффективные параметры и явное переопределение. |
| `AP-13` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. SQLite/processor: durable preview и claim, checkpoints, live processing progress, cancellation и reclaim истёкшей lease. Реальная остановка production worker не воспроизводилась. |
| `AP-14` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Download и Drive export регенерируют результат из исходников после reload. Проверены failure/cancel, reuse и cleanup scratch; тесты success/failure проверяют нулевые S3 PUT и отсутствие отдельного output Source. Ранее: PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). metadata-only output, worker regeneration из retained originals без STT/S3; independent download/Drive/handoff, selected retention и512-point waveform/sample. Audio/API/lease/cleanup/component regressions PASS; real synthetic FFmpeg local PASS,5 Linux FFmpeg skips без binary. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |
| `AP-15` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Папка подтверждается для владельца. Export проверен для foreign owner, exact destination, повторного запуска и отмены. Сохраняемая ссылка Drive проверяется отдельно от токена и внутренних storage IDs. Ранее: F41 исправлен #318/8d9f45d: output сохранён до initial Drive export, cancellation/recovery; CI 36701312137/36701312154 PASS, current main CI 37155276745/37155276751 PASS. |
| `AP-16` | READY | PASS | PASS | PENDING | Current-lease source admission survives TTL only for admitted running work; idle preview/queue/failed/lost lease does not defer forever. Current source_deletion/retention_admission/audio service/processor/download tests in523 cohort PASS, UI deferral guidance in full web checks. 0f387bb/36e2425. Required current Linux CI/release and single PR/delivery remain PENDING. |
| `AP-17` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Component: исходник остаётся в браузере до явной загрузки в Studio. Browser-local orchestration: декодирование и WAV, decoder context закрывается. |
| `AP-18` | IN_PROGRESS | PARTIAL | FAIL | PENDING | F107 · `8ad83e3`. File count and compressed-byte guards run before decode; decoded-sample guard runs after whole-file allocation, so it cannot enforce the required upfront memory bound. |
| `AP-19` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Component: несколько отдельных задач по умолчанию либо один concat в заданном порядке после выбора режима. |
| `AP-20` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Component: numbered concat plan и ручная перестановка. Код использует origin/size и creation metadata, а не имя; service подтверждает порядок. |
| `AP-21` | READY | PARTIAL | PARTIAL | PENDING | F42 · `8ad83e3`. Подтверждены copy по умолчанию и отдельный WAV/FLAC path. Каналы и паузы автоматически переключают copy на видимый FLAC, UI показывает предупреждение перед запуском. Достаточность предупреждения для явного выбора в этих двух ветках ещё не квалифицирована. |
| `AP-22` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. UI: дружелюбные названия и скрытые параметры, −45 dB, пустой/минус/запятая. Обе ветки используют `silenceValues`; component подтверждает отсутствие POST на invalid input. |
| `AP-23` | READY | PASS | PASS | PENDING | Independent download/Drive/reuse preserved. Verified source versions, recorded re-render recipe and atomic exported-byte/map receipts reject same-size replacement or missing evidence without creating a Source. Current real FFmpeg/download/export/actual reuse-handler fixtures in523 cohort and browser audio/reload PASS; external Drive fake. 4efbdd6..ddbc172. Required current Linux CI/release and single PR/delivery remain PENDING. |
| `AP-24` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Component показывает точность; real FFmpeg/ffprobe: 24-bit stereo → FLAC mono 16-bit при исходных 44 100 Hz. Filter graph закрепляет `s16`. |
| `AP-25` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Keyboard tablist; direct mode принимает bounded media multiselect. Transfer tests подтверждают сохранение MIME, имени и отправку исходного File. |
| `AP-26` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Direct panel открывает общий output-folder picker и сохраняет launcher. Общий picker подтверждает поиск, shared drives и выбор пустой папки. |
| `AP-27` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Direct transfer отправляет File в resumable Google endpoint. API принимает метаданные, не media bytes. Component проверяет отсутствие Studio Source запроса. |
| `AP-28` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Component/transfer: bytes и проценты текущего файла и итога, отмена активного PUT, следующее действие требует ручного выбора. |
| `AP-29` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Browser/API: bounds count/file/total/MIME. Изолированный partial failure и ручной повтор с тем же marker; подтверждённый upload не повторяется. |
| `AP-31` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Waveform/FFmpeg tests show duration and detected silence/retained intervals, including unavailable/error state. Preview uses current sample; Chromium verified same-origin/blob WAV playback. |
| `AP-30` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. API проверяет owner/project/folder и точные id/name/MIME/size/marker. PostgreSQL job128519961671 подтверждает CSRF и отсутствие token/capability в completion DTO. Direct transfer URL и raw ошибки не входят в durable state или diagnostics. |

### `PWA-SPEAKER-IDENTITY-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `SP-01` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Speaker profile API CRUD + Alembic: имена и уникальность в границах владельца, чужие профили недоступны, deactivate сохраняет существующие привязки. |
| `SP-02` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Speaker profile API и схема сохраняют нормализованную роль. Synthetic fixture подтверждает валидацию и deterministic rendering. |
| `SP-03` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Synthetic API подтверждает owner-scoped bounded voice sample и отсутствие сохранения сэмпла. UI запрашивает его только после явного действия. |
| `SP-04` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Synthetic API проверяет явное сопоставление label с owner profile, точное изменение целевого документа и отказ без ожидаемого заголовка. |
| `SP-05` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Synthetic export/assignment покрывает имя и роль в заголовке документа и обновление history snapshot с сохранением provider label. Нет автоматического распознавания личности. |

### `PWA-MANIFEST-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PM-01` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. PostgreSQL CI: preflight и create блокируют повтор при accepted linked output. Worker adapter сохраняет duplicate guard перед dispatch. |
| `PM-02` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. App требует отдельного подтверждения платной повторной обработки. PostgreSQL CI: create повторно валидирует explicit reprocess, worker adapter проверяет authority. |
| `PM-03` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Owner reset подтверждается отдельным «Да». PostgreSQL CI проверил cutoff: старое evidence скрыто, исходные записи не удаляются. Snapshot тестирует owner scope. |
| `PM-04` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Каталог имеет отдельные owner-scoped preview/apply. Folder tree, ограниченный обход и применяемый snapshot подтверждены scan/route/component tests. |
| `PM-05` | IN_PROGRESS | PARTIAL | FAIL | PENDING | F100 · `8ad83e3`. Google success и reconciliation могут записать принятый результат без независимого подтверждения полного документа. Yandex DOCX проверяется отдельно через receipt/readback, этот дефект его не дисквалифицирует. |
| `PM-06` | READY | PASS | PASS | PENDING | Versioned source identity separates selected revision/SHA-only/legacy MD5 and unversioned historical IDs in Python/SQL/catalog paths; changed same-ID content cannot inherit prepared provenance. Current drive_content_versions/materialization/reuse tests PASS; PostgreSQL grouping expression regression checks bind consistency. ddbc172. Required current Linux CI/release and single PR/delivery remain PENDING. |
| `PM-07` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. App подтверждает отсутствие документа в blocked plan для скрытой задачи без нового POST batch. PostgreSQL API tests проверили retry-safe attempt, acknowledged hidden failure, активный/неопределённый и linked result. Worker guard проверяет ту же authority. |

### `PWA-STANDARDIZATION-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PD-01` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Компонент выполняет отдельный folder preview и явный apply, run API привязывает их к выбранной операции и folder snapshot. |
| `PD-02` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Catalog scan проверяет вложенные папки, pagination, cycles и общий лимит. Неполная выдача отклоняется без частичного apply. |
| `PD-03` | IN_PROGRESS | PARTIAL | FAIL | PENDING | F101 · `8ad83e3`. Legacy standardizer умеет сегментировать речь. Синтетический новый документ с 200 предложениями в одном абзаце классифицирован как current, поэтому тот же UI skip не исправляет его. |
| `PD-04` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Legacy compact standardization сохраняет речь, clip/concat/timeline/processing и убирает legacy IDs, recipe JSON и Speakers. |
| `PD-05` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Legacy standardization нормализует валидную дату, исключает дублирование даты из title. Тесты новой и legacy metadata. |
| `PD-06` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. При известном source timestamp standardizer использует проверенное creation time. Classifier отклоняет конфликт, отсутствие optional даты допускается. |
| `PD-07` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Canonical type `transcript_doc` проверяется classifier. UI предлагает проверку и применение актуального формата без переключателя исторических версий. |
| `PD-08` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Google Docs create и in-place standardization формируют запрос стиля `HEADING_2` для title, включая правильные индексы исходного документа. |
| `PD-09` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. In-place test проверяет локализацию `Спикер N:`, bold и 14 pt. Общий style builder используется при создании нового Docs. |
| `PD-10` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Google create и in-place standardization проверяют style body 11 pt, отдельно от меток спикеров. |
| `PD-11` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Metadata keys остаются `Provider/Model/Language`; builder и standardizer используют русские заголовки и метки спикеров. Прежние английские labels читаются. |
| `PD-12` | IN_PROGRESS | PARTIAL | FAIL | PENDING | F101 · `8ad83e3`. Новый Google Doc имеет canonical header, но при непрерывном тексте пропускает требуемые стандартом читаемые абзацы. Тест воспроизвёл это на 200 предложениях. |
| `PD-13` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Eligible legacy Google Doc приводится в текущий формат на месте после preview и confirm; fresh snapshot до записи, revision guards и idempotent current document проверены fake Docs. Отдельный false-current случай учитывается в PD-03/F101. |
| `PD-14` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Standardizer/scan tests: валидная legacy дата сохраняется без связи с source, неверная пропускается, конфликт с подтверждённым source не применяется. Compact header не требует даты и Speakers. |

### `PWA-TRANSCRIPT-MAINTENANCE-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PTM-01` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. App: отдельный workspace обслуживания в транскрипциях, Settings ведёт в него и показывает состояние OAuth. Chromium CI проверяет fail-closed сценарий без Google authority. |
| `PTM-02` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Оба режима используют общий app-owned picker. Picker tests покрывают поиск, root/current folder, выбор одного Google Doc, блокировку и восстановление scroll. |
| `PTM-03` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. API создаёт durable run и возвращает без выполнения traversal. SQLite worker tests проверяют lease/reclaim и прогресс; component восстанавливает run после нового mount. |
| `PTM-04` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Safe progress DTO и normalized error: route/component tests не возвращают document IDs, токены, тело Docs и необработанные ошибки. Worker пишет только безопасные stage/reason. |
| `PTM-05` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Apply принимает успешный owner-scoped preview той же операции и цели. Route/worker tests покрывают невалидную ссылку на preview, свежее состояние и отказ при изменённом документе. |
| `PTM-06` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Повтор идентичного запроса возвращает run, conflicting replay и второй активный run отклоняются. Owner scope и workflow isolation проверены в run tests. |
| `PTM-07` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Scan/apply/run tests нормализуют timeout, auth, rate limit и revision conflict. Component сопоставляет safe reason с русским действием и требует свежей проверки после ошибки. |
| `PTM-08` | IN_PROGRESS | PARTIAL | FAIL | PENDING | F103 · `8ad83e3`. Stale lease fencing PASS, но production loop периодически ставит maintenance первым. Worker reliability test подтверждает это при backlog, тогда как AC требует strict priority. |
| `PTM-09` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Component polling test проходит queued → running → terminal без remount. API отдаёт owner-scoped exact/latest run с `no-store`. |

### `PWA-REALTIME-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PR-01` | BLOCKED | PARTIAL | PASS | PENDING | F42 · `8ad83e3`. Realtime controller tests assert getDisplayMedia parameters and no-audio rejection; internal browser had no Studio tab in this pass. Need native Windows/Chrome chooser evidence for tab/window/screen. No media capture or STT was triggered. |
| `PR-02` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Controller tests передают PCM из выбранного display stream и отклоняют stream без audio track до выдачи capability. Browser CI использует синтетический аудиоисточник. |
| `PR-03` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Две дорожки микшируются в одном AudioContext, микрофон opt-in. Controller и UI проверяют isolated levels, mixing и cleanup. |
| `PR-04` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Controller/Panel: partial отдельно от committed, итоговый фрагмент появляется в UI, indexed correction не создаёт дубликат. Chromium CI с fake transport. |
| `PR-05` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Panel проверяет скачивание TXT и состав browser-only текста. Browser CI подтверждает скачивание после синтетического capture. |
| `PR-06` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Realtime controller tests cover microphone, display and mixed audio, permission rejection without provider capability, missing display audio, source loss and reconnect. Native chooser matrix on physical Windows not repeated. |
| `PR-07` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Panel checkpoint вызывается при committed event, локальные записи IndexedDB привязаны к owner/project/session. Тесты fencing и browser reload подтверждают доступ к сохранённому тексту. |
| `PR-08` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Panel fake timers подтверждают один checkpoint последнего partial после bounded debounce и flush при unmount. Recovered partial помечается неподтверждённым. |
| `PR-09` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. SQLite: encrypted payload, owner scope, bounds и monotonic revision. PostgreSQL job128519961671: private/no-store routes, monotonic save и race первого insert. |
| `PR-10` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Panel восстанавливает owner-scoped candidate из сохранённых данных после нового mount. Browser job128519962151 подтверждает reload; физический reboot не воспроизводился. |
| `PR-11` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Recovery panel предлагает restore, TXT и явное delete, включая partial-only draft. Тесты подтверждают разделение действий и отсутствие мутации другой сессии. |
| `PR-12` | READY | PASS | PASS | PENDING | Independent owner/project/client-session local and server drafts, no TTL, clear tombstone/late-save fencing. Current backend realtime/local storage tests and real Chromium IndexedDB legacy migration/two-session isolation/clear PASS; common web Live regressions PASS. 247e59a/a7145ca/dc301a8. Required current Linux CI/release and single PR/delivery remain PENDING. |
| `PR-13` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Draft schema хранит только текст/metadata, шифрование подтверждено. PostgreSQL job128519961671: редактирование validation response, отсутствие audit payload и private/no-store API. Ordinary history/analytics используют отдельные DTO. |

### `PWA-OPERABILITY-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PO-01` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. SQLite diagnostics tests проверяют owner scope, redaction, deduplication, ограничение retention и безопасные aggregate events API/worker. |
| `PO-02` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. PWA failures используют allowlisted keys; App и backend tests проверяют безопасную correlation и отсутствие рекурсивной отправки при ошибке ingestion. |
| `PO-03` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Safe system report тестирует конфигурацию и состояние компонентов без приватных URL/IDs. App показывает system/Timeline/PWA/audit отдельными секциями. |
| `PO-04` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. App экспортирует Markdown через общий отчёт. Backend проверяет совместимость Markdown и отказ при неизвестном формате. |
| `PO-05` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. JSON round-trip проверяет общий безопасный report payload. App использует тот же flow для запроса и скачивания. |
| `PO-06` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. YAML round-trip подтверждает тот же payload, App проверяет экспорт в YAML через общий flow. |
| `PO-07` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. TOML round-trip подтверждает тот же payload, App проверяет экспорт в TOML через общий flow. |
| `PO-08` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. App history fixture показывает safe provider/language/progress. API list tests подтверждают owner scope, safe DTO и cursor isolation. |
| `PO-09` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Chromium CI history links и resource link tests подтверждают URL Google Docs и отклонение небезопасных ссылок. |
| `PO-10` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. PostgreSQL job128519961671: очистка owner-scoped, старые строки скрываются, durable jobs и attention tasks сохраняются. |
| `PO-11` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. App: до явного «Да» не отправляется очистка, отмена сохраняет историю. |
| `PO-12` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. SQLite aggregate и component tests сверяют totals jobs/sources/outputs. PostgreSQL API отдаёт только owner-scoped агрегаты. |
| `PO-13` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Aggregate fixture сверяет execution и stage intervals и не подставляет duration без выборки. Component показывает подписи фаз. |
| `PO-14` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Backend читает исторический provider/model из durable job options независимо от rotation. Panel проверяет ElevenLabs, Yandex и расширенный model DTO. |
| `PO-15` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Panel явно показывает success percentage; когда terminal denominator отсутствует, выводит объяснение вместо нулевого процента. |
| `PO-16` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Safe aggregate DTO включает outcome, language, speaker flags и длительности; parser отклоняет приватные поля и несогласованные totals. |
| `PO-17` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. PostgreSQL owner-scoped reset сохраняет durable jobs. App перечитывает агрегат после смены cutoff. |
| `PO-18` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Component подтверждает отсутствие мутации до «Да», а отказ сохраняет прежний срез. |

### `PWA-SECURITY-HARDENING-02`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PWASEC-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PWASEC-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PWASEC-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PWASEC-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PWASEC-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PWASEC-06` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PWASEC-07` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PWASEC-08` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PWASEC-09` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PWASEC-10` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PWASEC-11` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PWASEC-12` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PWASEC-13` | READY | ✅ | ✅ | ✅ | SECURITY-FIVE-20261024 / PR340 candidate60db429: persisted conditional counter/secret-nonce consume во всех auth consumers, additive0042; unit rollback/window/secret PASS, PostgreSQL exactly-one concurrency и cross-route replay/fresh/recovery controls PASS в CI40075895698 (2205 tests), release-rehearsal PASS. Code READY; final revision gates/merge/protected delivery остаются обязательными, production ещё0041. |
| `PWASEC-14` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PWASEC-15` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PWASEC-16` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PWASEC-17` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PWASEC-18` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PWASEC-19` | READY | ✅ | ✅ | ✅ | Восстановлено по code и primary records 2026-09-30: PR #317/5dcd3e6, migration/CD 36299859149, worker CD 36300397903 и status 36300716206 SUCCESS. |
| `PWASEC-20` | READY | ✅ | ✅ | ✅ | Восстановлено по code и primary records 2026-09-30: PR #317/5dcd3e6, migration/CD 36299859149, worker CD 36300397903 и status 36300716206 SUCCESS. |
| `PWASEC-21` | READY | ✅ | ✅ | ✅ | Восстановлено по code и primary records 2026-09-30: PR #317/5dcd3e6, migration/CD 36299859149, worker CD 36300397903 и status 36300716206 SUCCESS. |

### `GOOGLE-DRIVE-RELIABILITY-02`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `GOOGLE-01` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Worker использует resumable transport. Synthetic tests покрывают диапазоны частей, возобновление с подтверждённого offset, lost ACK, bounded progress и checksum/readback. |
| `GOOGLE-02` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Token refresh отличает invalid grant от transient failure, API отдаёт безопасную причину для reconnect. PostgreSQL и App tests подтверждают revoked state и недоступность Picker. |
| `GOOGLE-03` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Disconnect стирает ciphertext/nonce/key ID обоих grants и идемпотентен. PostgreSQL job128519961671 подтвердил безопасный payload и удаление локального материала. |
| `GOOGLE-04` | IN_PROGRESS | PARTIAL | FAIL | PENDING | F104 · `8ad83e3`. Disconnect удаляет локальные токены и возвращает revoked; provider-side revoke call отсутствует. Реальный grant не отзывался. |
| `GOOGLE-05` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Source availability/materialization проверяют Google metadata, exact revision/checksum и scope перед provider dispatch. Неподтверждённый source fail-closed. |
| `GOOGLE-06` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Google pre-dispatch verifier получает актуальную metadata папки, требует `canAddChildren` и перечитывает lease/target после I/O. Tests покрывают read-only folder и недоступный grant. |

### `STORAGE-LIFECYCLE-02`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `STORAG-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STORAG-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STORAG-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STORAG-04` | READY | PASS | PASS | PASS | F99, PR #354/main `dc0eb90`, CD42468294371: ограниченная периодическая сверка с проверкой DB references включена. 11Nov readback running worker: флаг true. Scheduler и непустой synthetic S3 покрыты тестами; production контрольный проход 08Nov был пустым. |
| `STORAG-05` | READY | ✅ | ✅ | ✅ | PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). Selected originals3/7/30, отсутствие finished S3 writer, fenced leases/all-full-docs retirement, bounded version cleanup/readback и page membership; storage/API/PG/lifecycle checks PASS. External production deletion не выполнялась. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |
| `STORAG-06` | READY | PASS | PASS | PENDING | New uploads retain selected3/7/30 with legacy expiry preserved; admission-before-expiry plus active lease controls deferral/cleanup, UI exposes reason. Current retention/deletion/source/media/download cohort523 PASS. Existing PG/concurrency suite remains mandatory CI, no production source changed. 0f387bb/36e2425/b3ecfc7. Required current Linux CI/release and single PR/delivery remain PENDING. |
| `STORAG-07` | READY | ✅ | ✅ | ✅ | PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). Selected originals3/7/30, отсутствие finished S3 writer, fenced leases/all-full-docs retirement, bounded version cleanup/readback и page membership; storage/API/PG/lifecycle checks PASS. External production deletion не выполнялась. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |
| `STORAG-08` | READY | ✅ | ✅ | ✅ | PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). Selected originals3/7/30, отсутствие finished S3 writer, fenced leases/all-full-docs retirement, bounded version cleanup/readback и page membership; storage/API/PG/lifecycle checks PASS. External production deletion не выполнялась. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |
| `STORAG-09` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STORAG-10` | IN_PROGRESS | PARTIAL | FAIL | PENDING | F100 · `8ad83e3`. Live manual-clear и retention при известной ошибке экспорта подтверждены. Google worker очищает checkpoint после неподтверждённого success, поскольку не перечитывает содержимое Docs. |
| `STORAG-11` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STORAG-12` | READY | ✅ | ✅ | ✅ | PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). History/analytics metadata без automatic TTL; owner reset скрывает прежний view, operational rows сохраняются для integrity. Retention policy и reset regressions PASS. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |
| `STORAG-13` | READY | ✅ | ✅ | ✅ | PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). History/analytics metadata без automatic TTL; owner reset скрывает прежний view, operational rows сохраняются для integrity. Retention policy и reset regressions PASS. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |
| `STORAG-14` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STORAG-15` | READY | ✅ | ✅ | ✅ | PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). Selected originals3/7/30, отсутствие finished S3 writer, fenced leases/all-full-docs retirement, bounded version cleanup/readback и page membership; storage/API/PG/lifecycle checks PASS. External production deletion не выполнялась. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |
| `STORAG-16` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STORAG-17` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STORAG-18` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STORAG-19` | READY | ✅ | ✅ | ✅ | PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). Selected originals3/7/30, отсутствие finished S3 writer, fenced leases/all-full-docs retirement, bounded version cleanup/readback и page membership; storage/API/PG/lifecycle checks PASS. External production deletion не выполнялась. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |
| `STORAG-20` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STORAG-22` | IN_PROGRESS | PARTIAL | FAIL | PENDING | F100 · `8ad83e3`. В isolated SQLite синтетический пустой Google Doc принят и persisted как completed. Enrolled source затем получает `all_transcripts_exported` и pending physical cleanup. Реальных удалений не выполнялось. |
| `STORAG-21` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

### `STT-PROVIDER-ABSTRACTION-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `STTPRO-01` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Provider-neutral execution selects configured adapters. Synthetic worker tests dispatch T-Bank/Mistral/Gemini without entering ElevenLabs transport; ElevenLabs and Yandex paths also covered. |
| `STTPRO-02` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Live capability route selects transport by provider; shared realtime controller/protocol handles ElevenLabs websocket and Yandex relay. Local capability/UI tests use fake transport. |
| `STTPRO-03` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Catalog tests verify effective modes per provider and hide unsupported Live for batch-only adapters. |
| `STTPRO-04` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Catalog exposes validated language modes. Adapter tests cover explicit `ru`/`en` and omission for detect; unsupported combinations fail before dispatch. |
| `STTPRO-05` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Catalog and validation tests distinguish Yandex realtime without diarization from capable batch. ElevenLabs and configured adapters expose tested model-specific limits. |
| `STTPRO-06` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Catalog metadata gates dictionaries per mode. Validation rejects unsupported Yandex dictionary options before provider dispatch. |
| `STTPRO-07` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Provider metadata publishes file size/duration/channel limits. Selection tests reject oversized duration and unsupported Gemini combinations before dispatch. |
| `STTPRO-08` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Catalog and adapter tests map economic to configured effective model and Yandex deferred transport. Equivalent mode is intentionally merged in UI. |
| `STTPRO-09` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Catalog and adapter tests map standard to configured model/transport, preserving the selected provider in preflight and execution. |
| `STTPRO-10` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Selection tests map premium to configured model and enforce provider features. UI merges equivalent settings when there is no meaningful difference. |
| `STTPRO-11` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Capability validation resolves realtime-specific model and transport. Tests distinguish Yandex relay and ElevenLabs websocket; batch-only adapters cannot request Live. |
| `STTPRO-12` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Health tests count provider-scoped failures and open the provider/mode circuit. Existing App Live test blocks new start with open circuit. BYOK quota is not shared failure. |
| `STTPRO-13` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Selection tests fail closed on disabled/unsupported providers. Synthetic dispatch confirms provider identity does not fall back to ElevenLabs. |
| `STTPRO-14` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Each provider has its own explicit BYOK enablement. Catalog/selection tests reject disabled provider and maintain independent realtime eligibility. |

### `YANDEX-STT-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `YANDEX-01` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Synthetic worker sends selected `standard/general` to SpeechKit, persists operation and normalizes terminal text, timing and optional speaker data. Linux job128519961671 covers the standard path. |
| `YANDEX-02` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Selected `economic/deferred-general` uses deferred transport. Linux job128519961671 confirms durable submit, polling and resume without a new submit. |
| `YANDEX-03` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Synthetic gRPC relay streams audio and committed/refined text. Controller tests confirm capture survives rotation and single-use capability is enforced. Paid live was not run. |
| `YANDEX-04` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. SQLite worker test sees persisted encrypted operation identity before the first poll, then resumes the same operation after interruption. |
| `YANDEX-05` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Synthetic terminal result and cache survive worker reload. Restored execution reads saved text/timing without new submit; terminal provider error does not fabricate success. |

### `PWA-DICTIONARIES-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PWADIC-01` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. API фильтрует CRUD и выбор для STT по владельцу. Synthetic normalization покрывает четыре вида записей, дубли и ограниченный snapshot terms. |

### `PWA-WORKER-ISOLATION-02`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PWAWOR-01` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Compose задаёт API и worker отдельными сервисами с разными commands/health gates. Synthetic compose contract проверяет границу процесса и отдельный DB login. |
| `PWAWOR-02` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Compose и contract tests подтверждают CPU, hard memory и pids limits, init и ограниченный временный каталог. Текущие runtime cgroup значения заново не снимались. |
| `PWAWOR-03` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Compose tests подтверждают read-only FS, cap_drop, disjoint networks, отдельный DB login. Role manifest tests проверяют allowlist, запрет DDL/изменения audit и fail-closed новые таблицы. Grants на VPS заново не снимались. |

### `PWA-DATABASE-LEAST-PRIVILEGE-03`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `DBLP-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `DBLP-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `DBLP-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `DBLP-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `DBLP-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `DBLP-06` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `DBLP-07` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `DBLP-08` | READY | ✅ | ✅ | ✅ | PR329 candidate c23fdc0, CI38141034993 SUCCESS11Oct2026 (test merge c1618886); ещё не main. F71: existing protected backup/role gates сохранены; isolated full API/web/worker schema/credential switch и compatible rollback PASS205.66s; no bootstrap credentials in runtime. Production switch данного PR ещё PENDING. |

### `JOB-RELIABILITY-02`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `JOBREL-01` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. PostgreSQL API tests сохраняют batch как durable задачи. Worker retry tests подтверждают восстановление очереди после потерянной lease. |
| `JOBREL-02` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Orchestrator обновляет durable processing status. Progress projection различает preparation, provider, Google export, failure и retry. |
| `JOBREL-03` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Retry tests сохраняют immutable план и monotonic bounded provider-part checkpoints. Recovery продолжает с последнего безопасного сохранённого состояния. |
| `JOBREL-04` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Real worker entry tests: safe/uncertain/cancelled/active. Linux job128519961671: bounded sweep с SKIP LOCKED и transactional rollback. |
| `JOBREL-05` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Retry tests различают pre-transport retry-safe и неопределённый outcome. Worker entry восстанавливает очереди только при доказанной безопасности. |
| `JOBREL-06` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Retry/worker tests проверяют отсутствие повторной отправки для неопределённой и уже подтверждённой операции, а также resume Yandex operation без нового submit. |
| `JOBREL-07` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Existing output и reconciliation case останавливают повторный create. Тесты покрывают race, output commit, retry и запрет повтора после неопределённого ответа. |
| `JOBREL-08` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Synthetic retry tests verify reuse of the same Google upload session after lost acknowledgment, create-only Yandex receipt/reconciliation, and retained-source render without a second stored audio result. |
| `JOBREL-09` | IN_PROGRESS | PARTIAL | FAIL | PENDING | F106 · `8ad83e3`. Durable intent dedupe подтверждён. Возобновившийся старый claim отправляет сообщение после replacement delivery; нет pre-dispatch claim fence. |
| `JOBREL-10` | IN_PROGRESS | PARTIAL | FAIL | PENDING | F42/F110 · `8ad83e3`. Synthetic SQLite: потеря JOB_CLAIMED после commit lease при сбое диагностической записи. Состояние задачи и специализированные outbox сохраняются, но этот event не восстанавливается. |
| `JOBREL-11` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Linux API test: cancel переводит queued, сохраняет terminal. App обновляет состояние и блокирует дублирующие запросы. |
| `JOBREL-12` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Worker/orchestrator: cancel до первого источника и между STT и Docs, прерывание собственного subprocess. App показывает pending и снимает блокировку при ошибке. |
| `JOBREL-13` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `JOBREL-14` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Server stage projection и UI pipeline tests подтверждают текущую стадию без вывода внутренних идентификаторов. |
| `JOBREL-15` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Preflight отклоняет deleted/unuploaded/missing identity. Materialization и adapter повторно проверяют owner/source revision, checksum и готовность до обращения к STT. |
| `JOBREL-16` | IN_PROGRESS | PARTIAL | FAIL | PENDING | F42/F111 · `8ad83e3`. Google rejects missing can_add_children. Yandex checks folder identity, but mock read-only destination passes readiness and the actual client gets permission_denied on upload-authority request. |
| `JOBREL-17` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Real/synthetic tests подтверждают отсутствие idle DB transaction в source download и media preparation. После I/O provider boundary повторно проверяет жизненный цикл и authority. |

### `JOB-NOTIFICATIONS-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `JOBNOT-01` | SUPERSEDED | — | — | — | Требование отменено владельцем25Oct2026; task notifications только Telegram JOBNOT-05/06. ID/история сохранены, вне denominator. |
| `JOBNOT-02` | SUPERSEDED | — | — | — | Требование отменено владельцем25Oct2026; task notifications только Telegram JOBNOT-05/06. ID/история сохранены, вне denominator. |
| `JOBNOT-03` | SUPERSEDED | — | — | — | Требование отменено владельцем25Oct2026; task notifications только Telegram JOBNOT-05/06. ID/история сохранены, вне denominator. |
| `JOBNOT-04` | SUPERSEDED | — | — | — | Требование отменено владельцем25Oct2026; task notifications только Telegram JOBNOT-05/06. ID/история сохранены, вне denominator. |
| `JOBNOT-05` | IN_PROGRESS | PARTIAL | FAIL | PENDING | F106 · `8ad83e3`. Owner/opt-in and positive Telegram ACK подтверждены, есть исторический approved private test. Synthetic expired claim отправляется даже после успешной доставки replacement, без потери ACK. |
| `JOBNOT-06` | IN_PROGRESS | PARTIAL | FAIL | PENDING | F106 · `8ad83e3`. Worker может отправить устаревшую ошибку после committed automatic retry и подавления claimed intent. Completion fence останавливает только запись результата. |

### `REALTIME-CONTINUITY-02`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `REALTI-01` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Controller отдельно сообщает остановленный audio source и сетевой/provider timeout. Tests: `ended` завершает capture, socket/handshake timeout оставляет capture и запускает retry. |
| `REALTI-02` | IN_PROGRESS | PARTIAL | PENDING | PENDING | F102 · `8ad83e3`. Browser overlay имеет same-profile BroadcastChannel. OBS Browser Source в собственном браузере не получает этот канал. Native OBS / Window Capture не прогонялись. |
| `REALTI-03` | READY | PARTIAL | PARTIAL | PENDING | F42 · `8ad83e3`. UI и mocked HTTP POST ingestion подтверждены. Совместимость payload и получение caption в реальной YouTube трансляции отдельно не подтверждены. |
| `REALTI-04` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Панель отправляет captions на явно указанный HTTPS webhook, API применяет owner/CSRF, allowlist и проверку публичного адреса. Fake transport подтверждает JSON payload и отказ на ошибке. Runtime allowlist не менялся. |
| `REALTI-05` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Отправка каждому получателю имеет собственный обработчик ошибки. Тесты подтверждают независимость helper и безопасное отклонение backend; код не останавливает capture при отказе доставки. |

### `TRANSCRIPT-EXPORTS-02`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `TRANSC-01` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Live exporter writes Markdown locally, preserves Unicode and paragraphs/speaker labels, escapes markup; no provider call. |
| `TRANSC-02` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Exporter tests exact SRT order and timestamp formatting, preserves independent session clocks and rejects unsafe timing. |
| `TRANSC-03` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Exporter tests WEBVTT and real cue times; panel disables timed export for untimed/partial sessions. |

### `USAGE-COST-ACCOUNTING-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `USAGEC-01` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Usage accounting сохраняет подтверждённые части один раз и отдельно отмечает неподтверждённый outcome. В projection неизвестное значение не становится нулём. |
| `USAGEC-02` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Nominal amount вычисляется из confirmed duration и immutable tariff snapshot; test проверяет precision, currency и provenance. UI отличает nominal от account actuals. |
| `USAGEC-03` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Server transport запрашивает subscription по credential, нормализует tier/status, overage и invoice, браузеру возвращает только DTO. Synthetic tests охватывают отсутствующие значения и invalid provider response. |
| `USAGEC-04` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Workspace usage normalizes bounded window и credit units, распознаёт именованные колонки. Ambiguous or malformed units не превращаются в оценку минут. |
| `USAGEC-05` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Panel разделяет nominal job cost и provider actuals, явно показывает неизвестные invoice/period units и не округляет малый положительный расход в ноль. |
| `USAGEC-06` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Credential/version scoped snapshot: current/stale/unavailable и timestamp/window. Explicit/bounded refresh и старый snapshot при ошибке проверены backend и UI. |

### `OBSERVABILITY-AUDIT-02`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `OBSERV-01` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Job ID связывает API job, worker lifecycle, provider diagnostic events и output. Synthetic orchestration и PostgreSQL diagnostics подтвердили цепочку. |
| `OBSERV-02` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Middleware создаёт request ID и возвращает заголовок; `JOB_CREATED` связывает его с job. Worker использует durable job correlation вместо подстановки request ID. |
| `OBSERV-03` | READY | PASS | PASS | PASS | F115, PR #352/main `7d02060`. Один сохранённый job trace проходит claim и операции локального обработчика. Регрессии покрывают replay, recovery, старый клиент и чужой lease. CI и поставка 0.1.3 подтверждены. |
| `OBSERV-04` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. System summary различает backend ready/degraded по runtime identity, App показывает health. Отдельная readiness проверяет DB/Redis. |
| `OBSERV-05` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Authenticated system summary показывает успешную проверку DB boundary; PostgreSQL CI подтверждает schema readiness и 503 при неподготовленной схеме. |
| `OBSERV-06` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Runtime observability и system summary показывают bounded очередь и её состояние без отправки задач. |
| `OBSERV-07` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Worker health основан на текущем heartbeat; missing/stale и wrong revision отклоняются в runtime/worker-health tests. |
| `OBSERV-08` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Runtime health делает read-only storage probe и возвращает safe status без bucket identity. Fake probes и system summary проверены. |
| `OBSERV-09` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Provider health отражает safe availability и состояние circuit. Tests проверяют неизвестное состояние без реального provider call. |
| `OBSERV-10` | IN_PROGRESS | PARTIAL | FAIL | PENDING | F105 · `8ad83e3`. System health возвращает `not_configured` даже при валидной synthetic security SMTP configuration. Отправка письма не выполнялась. |
| `OBSERV-11` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Отдельный `/api/livez` не зависит от DB/Redis. Linux integration проверяет response. |
| `OBSERV-12` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. Отдельный `/api/readyz` проверяет schema и Redis. PostgreSQL integration проверяет ready и non-200 при pending migrations. |
| `OBSERV-13` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Worker liveness отдельно проверяет процесс без чтения конфигурации и зависимостей. |
| `OBSERV-14` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Worker readiness проверяет expected PID, DB доступ и свежую identity; stale/revision mismatch fail-closed. |
| `OBSERV-15` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Operational rules создают owner-scoped critical incident. Durable delivery tests подтверждают bounded transport и отсутствие дубля при повторном наблюдении. |
| `OBSERV-16` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Stuck queue detection проверен на превышении порога; incident переходит в outbox с повтором и cooldown. |
| `OBSERV-17` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Rule tests подтверждают provider-unavailable signal и ограничение owner scope. Доставка проверена fake transport. |
| `OBSERV-18` | BLOCKED | PARTIAL | PASS | PENDING | F42 · `8ad83e3`. Synthetic tests cover reported protected-backup failure, cleanup events, incident and delivery worker. Scheduled backups belong to CloudKeep per F77. Need a CloudKeep record linking failed backup/target to delivery in its monitoring contour; successful archive records do not prove alert delivery. |
| `OBSERV-19` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Rule tests проверяют storage/API limit signals и отсутствие алерта без необходимых данных. Доставка проверена fake transport. |
| `OBSERV-20` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Nginx rules и actual uvicorn formatters закрывают OAuth/WS query logging. Diagnostics и provider/Telegram error tests проверяют redaction секретов. |
| `OBSERV-21` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Diagnostics DTO, audit metadata и reports ограничены allowlist; payload текста, IDs/URLs вне контракта и arbitrary raw errors отклоняются. |
| `OBSERV-22` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. System report возвращает coherent release version; mixed/invalid identities fail closed. |
| `OBSERV-23` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. System report и frontend показывают проверенное environment label без raw configuration. |
| `OBSERV-24` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Web metadata извлекается из build artifact и проходит strict component validation. System report test проверяет web build. |
| `OBSERV-25` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. API runtime identity из pinned build metadata, API component отражается в system report. |
| `OBSERV-26` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Worker build identity читается из свежего heartbeat. Component scoped identity проверена deployment и runtime contracts. |
| `OBSERV-27` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. System route integration проверяет exact full commit по компонентам; malformed identity не принимается. |
| `OBSERV-28` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. System summary выдаёт schema revision из DB, а readiness integration сверяет actual migration head. |
| `OBSERV-29` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Audit writer и owner action tests проверяют привязку actor для пользовательских операций; системные операции сохраняют свою отдельную attribution. |
| `OBSERV-30` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Audit model сохраняет timestamp, маршруты возвращают его в bounded page; order/cursor tests подтверждают устойчивый порядок. |
| `OBSERV-31` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Audit writer хранит event type; static labels и route tests проверяют отображаемое действие. |
| `OBSERV-32` | READY | PASS | PASS | PENDING | F42 · `8ad83e3`. Audit writer принимает ограниченный outcome, regression читает сохранённые rejected/failed вместе с trace. |
| `OBSERV-33` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. PostgreSQL job128519961671 проверяет DB запрет UPDATE для старой audit row. |
| `OBSERV-34` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. PostgreSQL job128519961671 проверяет DB запрет DELETE для audit rows. |
| `OBSERV-35` | READY | PASS | PASS | PASS | F42 · `8ad83e3`. PostgreSQL history/analytics reset тест подтверждает сохранение audit trail и запись новых events, durable jobs не удаляются. |

### `RELEASE-SAFETY-02`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `RELEAS-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `RELEAS-02` | READY | ✅ | ✅ | ✅ | PR329 candidate c23fdc0, CI38141034993 SUCCESS11Oct2026 (test merge c1618886); ещё не main. F71: tested full application compatible rollback procedure PASS на isolated synthetic Docker topology; production rollback не запускался. |
| `RELEAS-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `RELEAS-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `RELEAS-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |


### `PERSONAL-TECHNICAL-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `TECH-01` | READY | ✅ | ✅ | ✅ | A20261010-CODE/CI; package.json, vite.config.ts, pwaUpdate.ts; Studio build/component/browser CI; runtime claims только A20261010-RUNTIME. |
| `TECH-02` | READY | ✅ | ✅ | ✅ | A20261010-CODE/CI; API requirements/models, migrations0040; CI PostgreSQL/migration tests; runtime claims только A20261010-RUNTIME. |
| `TECH-03` | READY | ✅ | ✅ | ✅ | A20261010-CODE/CI; rate_limit.py, realtime replay guard; API/security/Redis CI; runtime claims только A20261010-RUNTIME. |
| `TECH-04` | READY | ✅ | ✅ | ✅ | A20261010-CODE/CI; audio processor/browserAudioProcessing; preparation/security/resource/component tests; runtime claims только A20261010-RUNTIME. |
| `TECH-05` | READY | ✅ | ✅ | ✅ | A20261010-CODE/CI; source_storage.py, deploy/studio, API/Compose/edge tests; Yandex Disk feature отдельно YD; runtime claims только A20261010-RUNTIME. |
