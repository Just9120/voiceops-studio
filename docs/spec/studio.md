# AC: Studio: существующие personal-подсистемы

Часть [canonical spec](../project-spec.md). Единственный владелец формулировок AC этой подсистемы. Статусы/Evidence находятся в [реестре](../delivery/studio.md).

### Эпик `PWA-CORE-01` — application shell, auth и integrations

| AC | Проверяемое требование |
|---|---|
| `PC-01` | Интерфейс адаптивен на desktop и narrow viewport без document-level overflow и недоступных controls. |
| `PC-02` | Sidebar содержит Dashboard. |
| `PC-03` | Primary navigation и page title используют пользовательскую сущность `Транскрибации`, а не технический `Project`. |
| `PC-04` | Sidebar содержит Settings. |
| `PC-05` | Admin входит по login/password и получает server session. |
| `PC-06` | Provider API keys добавляются и управляются в Settings. |
| `PC-07` | Google Drive подключается через owner-scoped OAuth flow. |
| `PC-08` | Local uploads хранятся в Cloudflare R2 через S3-compatible boundary. |
| `PC-09` | В Settings выбирается retention period local uploads. |
| `PC-10` | После expiry object удаляется из R2 идемпотентным cleanup. |
| `PC-11` | После expiry local source исчезает из active web UI. |
| `PC-12` | Доступны system, light и dark themes. |
| `PC-13` | Пользователь выбирает accent/interface color. |
| `PC-14` | Direct local upload в `Обработке аудио` и `Транскрибациях` показывает реальный progress текущего файла в bytes/percent и aggregate queue progress; timeout/network outcome проходит completion reconciliation без автоматического повторного PUT. |
| `PC-15` | Когда для открытой Studio PWA установлена новая версия service worker, интерфейс сообщает о доступном обновлении без самопроизвольной перезагрузки; при возвращении к открытой вкладке выполняется проверка версии, а отсутствие сети или ошибка проверки не прерывают текущую работу. Проверка: simulated registration/update, visibility и offline states. |
| `PC-16` | Уведомление о новой версии предлагает `Обновить сейчас` и `Позже`: второе действие оставляет незавершённый ввод и текущую страницу, первое применяет ожидающую версию и перезагружает страницу; повторное предложение возможно после возвращения к вкладке. Обновление в другой вкладке не вызывает принудительную перезагрузку текущей. Проверка: component и multi-tab/browser regression. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `PWA-USER-EXPERIENCE-02` — пользовательский язык и progressive disclosure

| AC | Проверяемое требование |
|---|---|
| `PUX-01` | Обзор приоритетно показывает пользовательские действия, текущую работу и доступные результаты; configuration counters не выступают главным содержанием страницы. |
| `PUX-02` | Основной flow `Подготовка аудио` описывает варианты выбора по пользовательскому результату; S3, server-side FFmpeg, MIME, bytes и иные implementation details не показываются без явного раскрытия технических деталей. |
| `PUX-03` | Composer и preflight транскрибации используют понятные русские действия и явную non-color-only индикацию важных опций; internal source/output type names и identifiers не входят в default presentation. |
| `PUX-04` | Одиночная job отображается как `Транскрибация`, а batch с несколькими jobs — как `Группа транскрибаций`; служебные labels `Мульти-транскрибация` и `Элемент N` отсутствуют в default presentation. |
| `PUX-05` | Terminal notice имеет семантически корректный visual/ARIA tone для success, failure и cancellation; failed/cancelled state не использует success styling. |
| `PUX-06` | Пользователь видит локализованную actionable ошибку; raw backend/provider error code не показывается по умолчанию и доступен только в явно раскрытых данных для поддержки. |
| `PUX-07` | Job/History cards не дублируют одинаковые timestamps и metadata; UUID, storage/source/output technical types и расширенные processing details находятся под явным disclosure. |
| `PUX-08` | Основной Live flow объясняет захват, временное восстановление и результат пользовательским русским языком; model/VAD/checkpoint/storage/reconnect implementation details находятся под disclosure `Технические детали`. |
| `PUX-09` | Transcript maintenance использует user-task terms (`проверка`, `применение`, `актуальный формат`) в основных controls/messages; `dry-run`, metadata, catalog и standard identifiers показываются только как secondary technical help. |
| `PUX-10` | Maintenance result сначала показывает summary и доступные действия, а длинные document lists имеют filter и bounded pagination/progressive disclosure без unbounded render всех строк. |
| `PUX-11` | В Settings обычные подключения и пользовательские storage preferences отделены от diagnostics, runtime identity, debug/export и maintenance access, которые явно обозначены как раздел для поддержки/расширенные настройки. |
| `PUX-12` | App-owned Google Drive dialog на viewport `390x844` не имеет horizontal overflow, сохраняет читаемые названия и доступные primary/close controls; modal scroll остаётся изолирован от страницы. |
| `PUX-13` | Running transcription отображается одним постоянно активным user-facing progress meter с текущим действием и активным файлом; owner-scoped automatic refresh обновляет state без ручного reload/tab switch, exact percentage отражает только подтверждённые checkpoints, а technical stages доступны под progressive disclosure. |
| `PUX-14` | После reload аудио/batch восстановлены owner/project-scoped параметры, названия, строки и интервалы. File/blob выбираются заново; credentials/capabilities/текст транскриптов не сохраняются, reprocess consent сбрасывается, logout очищает drafts. Проверка: reload/isolation/malformed-storage/logout regressions. |
| `PUX-15` | Удаление незапущенной строки сообщает текущий исход и позволяет Undo с прежними параметрами и позицией без создания задачи/API side effect. Проверка: component и keyboard/browser сценарий удаления/Undo. |
| `PUX-16` | История показывает активные фильтры, reset и количество среди загруженного среза; пагинация возвращает focus к началу новых результатов, не выдаёт частичный набор за полный. Проверка: desktop/mobile page/filter/reset. |
| `PUX-17` | Recovery обслуживания открывает нужный раскрытый Google-access раздел и позволяет вернуться в обслуживание; переход не запускает OAuth/consent автоматически. Проверка: точная navigation/focus и отсутствие grant calls. |
| `PUX-18` | Конкретный документ из обзора открывается прямой валидированной ссылкой; задача открывается в собственных деталях в batch. Неизвестный/небезопасный URL не становится внешней ссылкой. Проверка: overview links и owner-safe detail navigation. |
| `PUX-19` | Детали завершённой задачи открываются в доступной панели без разрастания списка: основной документ доступен внутри, Escape/close возвращают focus и scroll; mobile panel/menu помещаются в viewport. Проверка: native Chromium desktop/mobile и keyboard. |
| `PUX-20` | Массовые действия используют только выбранный текущий owner-scoped набор (до50): файлы удаляются после точного confirmation с existing authorization/readback, terminal задачи убираются в историю без нового STT; blocked/unknown outcomes показываются отдельно, оригиналы Drive и финансовые записи сохраняются. Проверка: subset/partial/duplicate/state regressions. |
| `PUX-21` | Основное действие длинной формы доступно в закреплённой панели без перекрытия существенных controls/errors и mobile keyboard viewport. Проверка: desktop/mobile layout/focus/scroll. |
| `PUX-22` | Название незапущенного документа редактируется в строке: Enter завершает ввод, Escape возвращает значение до текущего редактирования; существующий внешний документ не переименовывается. Проверка: inline input и отсутствие внешних mutation calls. |
| `PUX-23` | Пустые файлы/словарь предлагают прямой доступный следующий шаг; отсутствие интеграции/permissions не объявляется успехом. Проверка: empty CTA и fail-closed состояния. |

Основание PUX-14..23: owner decision14Oct2026 — все правки повторного UX/UI-ревью выбраны единой Goal. Исправления UXR20/21/12/19 уточняют existing AP/PUX/cost AC, сами findings denominator не увеличивают. Черновики хранятся только в текущей browser session; полного восстановления File после закрытия приложения не обещают.


Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `PWA-UX-POLISH-03` — содержательный dashboard и сворачиваемые support/maintenance details

| AC | Проверяемое требование |
|---|---|
| `UXPOL-01` | Owner dashboard показывает полезные незавершённые/последние транскрибации, последние документы, connection/system attention и быстрые действия; корректные loading/empty/error states не подменяются техническими counters. |
| `UXPOL-02` | **SUPERSEDED, вне denominator → PTM-01.** Сохранённая формулировка: Maintenance-вкладка называется `Подготовка документов` и объясняет проверку/стандартизацию текущего формата без двусмысленного обещания, что все документы уже готовы. |
| `UXPOL-03` | Завершённый scan/apply plan сначала показывает summary; document list сворачивается, а весь завершённый результат можно явно убрать/reset без удаления durable run/history или влияния на running operation. |
| `UXPOL-04` | System state в `Для поддержки` по умолчанию показывает понятный readiness summary, а component identities, commits, schema и technical probes находятся под доступным disclosure. |
| `UXPOL-05` | Diagnostic events отображаются bounded страницами; каждая строка имеет понятный human label/summary и раскрывает technical code/metadata только по запросу пользователя. |
| `UXPOL-06` | Diagnostic bundle UI предлагает `JSON — для анализа моделью` и `Markdown — для человека`, ясно объясняет выбор и не требует DOCX/YAML/TOML для обычного flow; backend compatibility может сохраняться. |
| `UXPOL-07` | Связанная операция/задача выбирается из недавних операций или ищется по понятному названию/ID case-insensitively; поле остаётся optional, объясняет назначение и не требует угадать exact register/internal identifier. |
| `UXPOL-08` | Eleven Labs account/cost panel объясняет план, использовано/осталось, overage и invoice простым русским языком; raw provider units/provenance находятся под optional disclosure. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `PWA-UX-CONTROLS-04` — честные controls, recovery и compact diagnostics

| AC | Проверяемое требование |
|---|---|
| `UXCTL-01` | Отдельный STT mode показывается только если effective provider capability реально отличается model, transport, features, speed или cost; эквивалентные modes объединяются. |
| `UXCTL-02` | Для каждого различающегося STT mode до dispatch доступно краткое понятное объяснение фактических отличий без неподтверждённых обещаний. |
| `UXCTL-03` | Fragmentation включается отдельным явным checkbox и в выключенном состоянии не создаёт segment-specific controls. |
| `UXCTL-04` | Общая output folder является default destination всех fragments. |
| `UXCTL-05` | Каждый fragment может переопределить output folder; composer/preflight показывает resolved destination каждого fragment до создания jobs. |
| `UXCTL-06` | Attention-required terminal job остаётся видимой до решения, но её подробности можно свернуть без изменения durable state. |
| `UXCTL-07` | Пользователь может повторно проверить uncertain result, связать job с подтверждённым более поздним результатом либо явно подтвердить отсутствие результата с предупреждением о возможном расходе; только resolved job переходит в обычный history lifecycle, audit сохраняется. |
| `UXCTL-08` | Eleven Labs account UI отдельно показывает base subscription plan и PAYG/prepaid balance и переводит raw provider values в понятные пользовательские labels. |
| `UXCTL-09` | Порядок расходования subscription credits и PAYG отображается только при наличии подтверждённых provider data и не выводится из предположений Studio. |
| `UXCTL-10` | Bulk cleanup preview показывает eligible/blocked Studio-owned files, aggregate bytes и явно сообщает, что Google Drive sources/documents не удаляются. |
| `UXCTL-11` | Bulk cleanup apply требует explicit confirmation, удаляет только eligible Studio-owned files, безопасно пропускает blocked files и возвращает bounded summary по причинам. |
| `UXCTL-12` | Diagnostic event сначала показывает human-readable problem/action summary; technical event code, request/trace IDs и расширенные metadata находятся под disclosure. |
| `UXCTL-13` | Diagnostic projection сохраняет safe blocker reason и source/object type, необходимые для понимания failed или blocked действия. |
| `UXCTL-14` | Весь diagnostic event log можно свернуть; errors/warnings приоритетны, informational events доступны по запросу, список остаётся bounded/paginated. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `PWA-TRANSCRIPTIONS-UX-01` — пользовательская модель транскрибаций

| AC | Проверяемое требование |
|---|---|
| `PT-01` | В `Транскрибациях` доступны отдельные вкладки обычной и Live-транскрибации. |
| `PT-02` | Для запуска новой транскрибации пользователь не создаёт, не редактирует и не архивирует технический Project вручную. |
| `PT-03` | Один массовый запуск отображается как одна группа транскрибаций с отдельными source/fragment items. |
| `PT-04` | Существующие active legacy workspaces, sources, jobs и outputs остаются доступны без destructive migration; archived production data не восстанавливается автоматически. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `PWA-INGEST-01` — target и source selection, multi-transcription

| AC | Проверяемое требование |
|---|---|
| `PI-01` | Выбирается target Google Drive folder. |
| `PI-02` | Target folder можно добавить в Favorites и выбрать повторно. |
| `PI-03` | С компьютера выбирается один файл. |
| `PI-04` | С компьютера выбираются несколько файлов. |
| `PI-05` | С компьютера выбирается целая папка с файлами. |
| `PI-06` | На Google Drive выбирается один source file. |
| `PI-07` | На Google Drive выбираются несколько source files. |
| `PI-08` | На Google Drive выбирается source folder. |
| `PI-09` | Один batch принимает одну target folder и несколько явно выбранных files. |
| `PI-10` | Один batch принимает одну target folder и source folder. |
| `PI-11` | Для каждой composer row можно независимо выбрать source и target folder. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `PWA-GOOGLE-PICKER-UX-01` — app-owned Drive selection, search и viewport

| AC | Проверяемое требование |
|---|---|
| `PG-01` | Во всех source-file/source-folder/output-folder Picker flows открытая Google Picker modal остаётся зафиксированной относительно viewport и не смещается вслед за document scroll. |
| `PG-02` | Пока Google Picker открыт, background document scroll заблокирован; после pick/cancel/error/timeout предыдущие scroll position и body styles восстанавливаются без page jump. |
| `PG-03` | В output-folder flow текущая открытая папка является допустимым default selection: кнопка `Выбрать` активна без выбора вложенной папки, включая папку без дочерних папок. |
| `PG-04` | App-owned output-folder dialog позволяет искать доступные папки по имени, открывать найденную папку и выбрать её как current target без обязательного выбора вложенной папки. |
| `PG-05` | Source-file flow использует app-owned интерфейс, визуально и поведенчески согласованный с output-folder dialog; native Google Picker для этого flow не используется. |
| `PG-06` | Source-file dialog позволяет искать поддерживаемые audio/video files по имени и выбрать до `50` файлов; navigation/search/pagination не теряют уже выбранные элементы и не создают duplicates. |
| `PG-07` | Source-folder flow использует app-owned интерфейс, визуально и поведенчески согласованный с output-folder dialog; текущая открытая папка является допустимым selection, включая empty folder. |
| `PG-08` | Source-folder dialog позволяет искать доступные папки по имени, открыть найденную папку и выбрать её как current source folder. |
| `PG-09` | По выбору пользователя папки сортируются по имени (А→Я/Я→А) или дате обновления (новые/старые); порядок действует на весь запрос Drive, navigation/search/pagination сохраняют выбор и не смешивают страницы разных порядков. Проверка: component tests с несколькими страницами и поздними ответами. Основание: UX-аннотация 2, 2026-09-07. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `PWA-SEGMENTS-01` — произвольные пользовательские фрагменты

| AC | Проверяемое требование |
|---|---|
| `PS-01` | Пользователь задаёт число фрагментов. |
| `PS-02` | Поддерживается произвольное число `N >= 1`, а не только две части. |
| `PS-03` | Для каждого фрагмента задаётся start time. |
| `PS-04` | Для каждого фрагмента независимо задаётся end time либо явный `Конец`, включая границы всей записи. До подтверждения видны интервалы и папки; пустые/обратные интервалы и выход за известную длительность выбранной версии обнаруживаются заранее. Неизвестная длительность явно требует проверки. Q065,Q066,Q069,Q070. |
| `PS-05` | Для каждого валидного фрагмента создаётся отдельный transcript document. Пересечения, пропуски и порядок фрагментов не ограничивают валидность отдельных интервалов; отдельные аудиофайлы не требуются. Q065,Q067. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `PWA-BATCH-01` — transcription options, progress и output

| AC | Проверяемое требование |
|---|---|
| `PB-01` | Доступно разделение на спикеров. |
| `PB-02` | Доступен явный русский язык. |
| `PB-03` | Доступен явный английский язык. |
| `PB-04` | Доступно auto-detection языка. |
| `PB-05` | Job progress отображается live в процентах из server checkpoints. |
| `PB-06` | При выбранном Google Drive обычная транскрибация завершается только после подтверждения полного оформленного Google Doc в выбранной папке; UI показывает статус и ссылку, постоянная внутренняя копия текста не нужна. Проверка: fake Google create/write/readback, пустой/частичный ответ не становится success. Q125,Q129,Q130. |
| `PB-07` | Transcript document разбит на читабельные абзацы. |
| `PB-08` | В начале документа только Provider/Model/Language; UUID, recipe JSON и boolean Speakers не выводятся. Дата из title не дублируется; clip, изменённая timeline и необходимые особенности обработки остаются кратким понятным текстом. Решение владельца24Oct2026. |
| `PB-09` | Если timestamp нужен в metadata при отсутствии даты в title, он имеет ISO 8601 format. |
| `PB-10` | Опциональный timestamp получен из подтверждённого creation time исходного media file; дата в title не становится authority для source matching. |
| `PB-11` | Composer и preflight явно текстом показывают `Разделение спикеров: включено` или `Разделение спикеров: выключено`; включённое состояние визуально заметно и не передаётся только цветом. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `PWA-AUDIO-PREPARATION-01` — самостоятельная обработка аудио

| AC | Проверяемое требование |
|---|---|
| `AP-01` | Sidebar содержит отдельный пункт `Подготовка аудио` непосредственно перед `Транскрипциями`, а hero той же страницы использует заголовок `Подготовка аудио`. |
| `AP-02` | Пользователь выбирает один или несколько доступных owner-scoped media sources и запускает обработку независимо от транскрибации. |
| `AP-03` | До обработки каждый input проверяется через bounded probe на container, codec, duration, audio-stream presence и media integrity; invalid input fail-closed. |
| `AP-04` | Несколько inputs по умолчанию упорядочиваются по authoritative creation time, а пользователь может явно изменить порядок до запуска. |
| `AP-05` | Совместимые inputs могут быть склеены без перекодирования и потери качества; несовместимый copy plan блокируется до явного выбора conversion path. |
| `AP-06` | Processed output можно явно преобразовать в `WAV` или `FLAC`. |
| `AP-07` | Для stereo input доступен явный mono mode: mixdown, left channel или right channel; недоступный channel mode отклоняется до processing. |
| `AP-08` | Silence processing позволяет задать threshold, минимальную длительность тишины и сколько тишины оставить; значения имеют bounded safe limits. |
| `AP-09` | До mutation пользователь получает preview общей исходной длительности и оценочной длительности после silence processing. |
| `AP-10` | Склейка, silence processing, conversion и переименование могут выполняться отдельно или в комбинации без обязательной последующей транскрибации. |
| `AP-11` | Пользователь может задать optional output name; если поле пусто, output наследует stem соответствующего исходного filename (для concat — первого source в подтверждённом порядке). User-visible Unicode/кириллическое имя сохраняется в Studio Source, Google Drive и download, а internal storage key формируется отдельно и не подменяет видимое имя. |
| `AP-12` | Доступны bounded presets для типовых сценариев `Лекция`, `Созвон` и `Только обработать аудио`, причём пользователь видит и может изменить итоговые параметры до запуска. |
| `AP-13` | Processing имеет durable owner-scoped queue state, server checkpoints, live progress, cancellation и безопасное восстановление после worker restart. |
| `AP-14` | Готовое подготовленное аудио скачивается или сохраняется в Google Drive без отдельной сохраняемой копии результата в S3. Повторное использование использует доступный результат без обещания внутреннего постоянного хранения. Проверка: local/server success, export failure/cancel и проверка отсутствия finished S3 object. Q169. |
| `AP-15` | Пользователь может загрузить successful output в явно выбранную Google Drive folder через owner grant с `drive.file`; persisted result содержит safe Drive link без token/object identity. |
| `AP-16` | Исходники с устройства для серверной подготовки аудио имеют выбранное хранение 3/7/30 дней; request-scoped FFmpeg и частичные результаты очищаются после success/failure/cancel, без раскрытия bytes/paths. Проверка: selected retention, active lease, cleanup retry и owner isolation. Q162,Q167,Q177,Q178. |
| `AP-17` | Пользователь может обработать device media browser-side без передачи source bytes в API/S3/provider; результат существует только в текущей вкладке и скачивается как WAV. |
| `AP-18` | Browser-local path имеет явные file-count/input-size/decoded-memory bounds и при неподдерживаемом codec/channel/resources выдаёт понятную ошибку с предложением server-side Studio path. |
| `AP-19` | Для нескольких inputs пользователь явно выбирает `Обработать каждый отдельно` (default, отдельный output на source) либо `Склеить в один файл` (один ordered output). |
| `AP-20` | До запуска UI показывает numbered result/concat plan, origin, size и authoritative creation metadata where available, позволяет manual reorder и не использует filename как creation/order authority. |
| `AP-21` | Default plan сохраняет исходный format/container; изменение каналов или пауз требует явного WAV/FLAC conversion path без скрытого перекодирования. |
| `AP-22` | Primary UI использует user-facing scenario/title controls, не показывает technical filename template, называет функцию `Уменьшить длинные паузы в аудио или видео`, использует default `-45 dB` и раскрывает остальные silence parameters только после включения функции.  При редактировании допустимы пустой текст и промежуточный минус; точка отображается запятой. До запуска обеих processing paths конечные значения проверяются по существующим bounds, некорректный ввод не отправляется. Проверка: regression UI tests. Основание: UX-аннотации 3/4, 2026-09-07. |
| `AP-23` | Download, optional save в явно выбранную Google Drive folder и handoff/reuse в транскрибацию или новую обработку представлены независимыми terminal actions, а не взаимоисключающим выбором результата. После завершения без auto-save доступно «Сохранить в Google Drive» с тем же выбором папки; повтор не создаёт дубликат, ошибка/отмена не лишает скачивания. По решению владельца2026-10-05 после reload download/export заново собирают результат из доступных исходников по сохранённым параметрам до окончания их срока хранения, без STT и без finished S3 copy; временные файлы очищаются после завершения передачи/ошибки/отмены. Во время первоначального auto-save используются готовые bytes текущей обработки. Исходники недоступны — понятное recovery state, без обещания постоянного внутреннего хранения. Это заменяет прежнее требование сохранять готовые bytes после reload (UX-аннотация2026-09-07) и сохраняет independent terminal actions. Проверка: component/API/worker regression tests с fake Drive. |
| `AP-24` | Server-side FLAC создаётся с явной 16-bit sample precision и исходной sample rate, UI раскрывает эти параметры, а FFmpeg filter graph не может неявно повысить output до избыточного 24-bit. |
| `AP-25` | Source actions оформлены как доступный tablist; mode `В Google Drive без обработки` принимает bounded multi-select только поддерживаемых audio/video с устройства и сохраняет исходные bytes, filename и MIME без преобразования. |
| `AP-26` | Для direct-upload mode целевая folder выбирается существующим app-owned output-folder dialog с search/navigation/shared drives и возможностью выбрать current folder, включая empty folder. |
| `AP-27` | Resumable transfer идёт напрямую browser → Google Drive и не отправляет source bytes в Studio API, S3, Studio Source, FFmpeg, transcription или provider; используются только существующие Google OAuth scopes без expansion. |
| `AP-28` | UI показывает current-file и aggregate progress в bytes и процентах, текущую стадию и cancellation; automatic retry/replay отсутствует. |
| `AP-29` | File count, per-file/aggregate size и MIME имеют явные bounds; partial failures изолированы, а manual retry использует устойчивый idempotency marker и не дублирует уже подтверждённые uploads. |
| `AP-31` | После анализа пауз пользователь видит waveform с отмеченными интервалами тишины/сокращения, может прослушать репрезентативный результат и сравнить исходную/итоговую длительность. Проверка: known silent intervals, no-silence/empty/error/loading и keyboard controls. Q060. |
| `AP-30` | API server-side проверяет owner destination и result metadata: file ID, parent, name, MIME, size и idempotency marker; UI показывает только safe Drive links, а token/resumable upload URL/private diagnostics не логируются и не сохраняются. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `PWA-SPEAKER-IDENTITY-01` — имена и роли спикеров

Q009,Q089..092: отложено до отдельного решения владельца; ручные имена/роли и samples сохраняются как существующая optional implementation, не обязательный current personal scope.

| AC | Проверяемое требование |
|---|---|
| `SP-01` | Есть owner-scoped база имён спикеров. |
| `SP-02` | Для speaker identity хранится роль. |
| `SP-03` | Пользователь может прослушать bounded voice fragment обнаруженного спикера. |
| `SP-04` | Пользователь явно связывает provider speaker label с выбранным именем. |
| `SP-05` | Подтверждённое имя/роль используется в transcript output и history metadata. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `PWA-MANIFEST-01` — duplicate protection и каталог

| AC | Проверяемое требование |
|---|---|
| `PM-01` | Accepted output evidence блокирует неявную повторную транскрибацию. |
| `PM-02` | Явный reprocess/bypass требует отдельного user confirmation. |
| `PM-03` | Пользователь может безопасно очистить owner-scoped manifest/catalog. |
| `PM-04` | Выбранная Google Drive folder tree регистрируется отдельным dry-run/apply flow. |
| `PM-05` | Для обычного исходника/фрагмента запись успешной транскрибации в манифесте появляется только после подтверждённого создания полного Google Doc или полного DOCX на Яндекс Диске. Старт задачи, вызов STT, пустой или частичный документ не считаются успехом. Временный STT text незавершённого экспорта используется для export-only recovery; постоянная полная копия обычной транскрипции в Studio не требуется. Проверка: contract/worker tests полного результата, export failure и повтора без нового STT. Уточнение согласованного источника revision 2994, 2026-09-27. |
| `PM-06` | Duplicate identity использует Drive file ID/Studio source identity и settings, не filename alone. |
| `PM-07` | При создании новой транскрибации прежняя завершившаяся ошибкой попытка распознавания до создания Google Docs не блокирует запуск; если создание документа началось, новая задача допускается после явного подтверждения владельцем отсутствия результата. Для терминальной неопределённой попытки preflight предоставляет действие подтверждения отсутствия документа без поиска старой задачи по страницам истории или проектам, только если не найден принятый связанный документ Studio или импортированного каталога; действие не запускает новую транскрибацию автоматически. Preflight, создание задачи и worker учитывают подтверждение одинаково. Активная обработка того же исходника и настроек и неопределённое создание Google Docs без подтверждения остаются заблокированными; принятый документ проверяется отдельно. Проверка: unit/API/worker и UI regression на эти состояния, включая скрытую из истории и другого проекта подтверждённую ошибку. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `PWA-STANDARDIZATION-01` — стандартизация Google Docs

| AC | Проверяемое требование |
|---|---|
| `PD-01` | Есть отдельная быстрая selected-folder dry-run/apply operation. |
| `PD-02` | Folder mode обходит все вложенные подпапки в bounded tree. |
| `PD-03` | Документ нормализуется в читабельные абзацы. |
| `PD-04` | Standard metadata header содержит Provider/Model/Language; standardization сохраняет существенные clip/concat/timeline/processing пояснения без технических IDs/JSON/boolean Speakers. Legacy полный header читается совместимо. Решение владельца24Oct2026. |
| `PD-05` | Опциональный timestamp нормализуется в ISO 8601; дата, уже указанная в title, не дублируется в metadata. |
| `PD-06` | Если timestamp нужен при отсутствии даты в title, он отражает подтверждённое creation time исходного media file, а не Google Doc/job time; отсутствие поля допустимо для компактного header. |
| `PD-07` | Canonical identifier текущего document standard — versionless `transcript_doc`; user-facing flow не предлагает выбор версии стандарта. |
| `PD-08` | Название документа в новых и стандартизированных transcripts оформлено Google Docs style `Heading 2`. |
| `PD-09` | Метка каждого блока спикера имеет русскую форму `Спикер N:`, bold и размер `14 pt`. |
| `PD-10` | Обычный текст транскрибации по умолчанию имеет размер `11 pt`. |
| `PD-11` | Пользовательские структурные labels документа русифицированы; устойчивые technical terms и metadata keys сохраняются на английском. |
| `PD-12` | Каждый новый Studio PWA transcript создаётся в текущем canonical формате `transcript_doc`. |
| `PD-13` | Existing eligible Google Docs приводятся к текущему `transcript_doc` через существующий explicit dry-run/apply standardization flow одной пользовательской операцией; historical version selection не требуется. |
| `PD-14` | Existing legacy Google Doc стандартируется без обязательной связи с исходным media file: валидный существующий `Created at` сохраняется при отсутствии даты в title, иначе не дублируется; отсутствующий/невалидный не заменяется `unknown` или догадкой, при известном source допустима его подтверждённая дата. Подтверждённый source-date conflict остаётся blocker. Compact header без Speakers/date принимается каталогом и при известной source date. Решение владельца24Oct2026 уточняет прежнее обязательное сохранение видимой даты. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `PWA-TRANSCRIPT-MAINTENANCE-01` — workspace и durable execution обслуживания

| AC | Проверяемое требование |
|---|---|
| `PTM-01` | Стандартизация Google Docs и манифест находятся в «Транскрибации → Обслуживание»; Settings содержит connection/consent controls и ссылку на workspace. |
| `PTM-02` | Выбор root folder и одного native Google Doc использует app-owned Google Drive dialog с навигацией, bounded search, выбором текущей папки и блокировкой фонового scroll. |
| `PTM-03` | Dry-run и apply выполняются как durable owner-scoped background runs и восстанавливают состояние после navigation/reload, worker restart или истечения lease; длительный Google traversal не удерживает browser HTTP request. |
| `PTM-04` | UI показывает persisted stage, bounded progress и terminal result; Drive/document IDs, OAuth tokens, document contents и raw Google errors не возвращаются в browser DTO и не попадают в operational logs. |
| `PTM-05` | Apply создаётся только из успешного owner-scoped preview, наследует его exact workflow/target, выполняет fresh server-side revalidation и остаётся explicit user-confirmed operation. |
| `PTM-06` | Повтор запроса idempotent, conflicting replay fail-closed, а один owner не может одновременно запустить два runs одного workflow. |
| `PTM-07` | Timeout, rate limit, auth/scope, selection, revision/write conflict и exhausted retry возвращаются как structured safe error codes с понятным русским действием без raw backend detail. |
| `PTM-08` | Worker обрабатывает maintenance runs только после normal audio-preparation/transcription work; lease generation и heartbeat не позволяют потерявшему lease worker перезаписать reclaimed run. |
| `PTM-09` | Пока owner-scoped maintenance run имеет status `queued` или `running`, открытый workspace автоматически запрашивает fresh `no-store` state и обновляет progress до terminal status без reload, remount или переключения вкладки. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `PWA-REALTIME-01` — realtime-транскрибация

| AC | Проверяемое требование |
|---|---|
| `PR-01` | В Windows/Chrome выбирается вкладка, окно или экран. |
| `PR-02` | Захватывается передаваемый browser/system audio track. |
| `PR-03` | Микрофон включается опционально и смешивается с display audio. |
| `PR-04` | Partial и committed transcript отображаются live. |
| `PR-05` | Подтверждённый transcript скачивается как `.txt`. |
| `PR-06` | Realtime microphone/display/mixed sessions работают стабильно в поддерживаемых браузерных сценариях. |
| `PR-07` | Каждый committed fragment немедленно сохраняется в owner/browser-scoped local draft. |
| `PR-08` | Последний partial fragment сохраняется с bounded debounce и явно остаётся неподтверждённым. |
| `PR-09` | Live draft синхронизируется в owner-scoped server storage с encryption at rest, bounded size и idempotent monotonic revision. |
| `PR-10` | После refresh, browser crash или перезапуска компьютера пользователь получает явное предложение восстановить незавершённый draft. |
| `PR-11` | Найденный draft можно восстановить, скачать как `.txt` или удалить явным действием. |
| `PR-12` | Live-текст после reload остаётся доступным до ручной очистки владельцем без автоматического срока удаления; начало следующей сессии не удаляет предыдущий текст. Проверка: local/server recovery спустя более 72 часов, restart/new session и explicit clear; чужой owner не имеет доступа. Q118,Q120. |
| `PR-13` | Live draft не сохраняет audio и не включает transcript body в logs, diagnostics, audit events или ordinary History/Analytics. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `PWA-OPERABILITY-01` — diagnostics, history и analytics

| AC | Проверяемое требование |
|---|---|
| `PO-01` | Собираются safe backend diagnostics. |
| `PO-02` | Собираются safe frontend/PWA diagnostics. |
| `PO-03` | Диагностический summary отражает safe configuration state. |
| `PO-04` | Diagnostics экспортируются в Markdown. |
| `PO-05` | Diagnostics экспортируются в JSON. |
| `PO-06` | Diagnostics экспортируются в YAML. |
| `PO-07` | Diagnostics экспортируются в TOML. |
| `PO-08` | History показывает safe transcription metadata. |
| `PO-09` | Успешная history entry содержит safe Google Docs link. |
| `PO-10` | History можно очистить owner-scoped action. |
| `PO-11` | Очистка History требует подтверждения Да/Нет. |
| `PO-12` | Analytics показывает количество транскрибаций. |
| `PO-13` | Analytics показывает execution/stage durations. |
| `PO-14` | Analytics показывает provider/model. |
| `PO-15` | Analytics явно показывает success percentage. |
| `PO-16` | Analytics показывает дополнительные safe outcome/options metadata. |
| `PO-17` | Analytics можно очистить owner-scoped action. |
| `PO-18` | Очистка Analytics требует подтверждения Да/Нет. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `PWA-SECURITY-HARDENING-02` — personal auth и security lifecycle

| AC | Проверяемое требование |
|---|---|
| `PWASEC-01` | Provider API keys шифруются at rest. |
| `PWASEC-02` | Google OAuth refresh tokens шифруются at rest. |
| `PWASEC-03` | Local passwords хранятся только как one-way password hash. |
| `PWASEC-04` | Upload policy ограничивает максимальный размер source file. |
| `PWASEC-05` | Batch/upload policy ограничивает максимальное число files. |
| `PWASEC-06` | Общая максимальная длительность одного исходника настраивается; значение по умолчанию — 12 часов (S051). |
| `PWASEC-07` | Пользователь может просмотреть active sessions. |
| `PWASEC-08` | Пользователь может отозвать одну выбранную active session. |
| `PWASEC-09` | Пользователь может отозвать все другие active sessions. |
| `PWASEC-10` | Critical actions требуют recent re-authentication; явно доверенный браузер может заменить повторное подтверждение только для разрешённых операций, но не для входа и изменения факторов защиты. Решение `D20260927-TRUSTED-DEVICE`. |
| `PWASEC-11` | Login защищён отдельным brute-force limit. |
| `PWASEC-12` | Password reset защищён отдельным brute-force limit. |
| `PWASEC-13` | TOTP verification защищена отдельным brute-force limit. Принятый time-step counter атомарно потребляется в БД вместе с auth-действием и не принимается повторно в login, reauth, enrollment confirmation и disable; следующий свежий code и одноразовый recovery сохраняют работоспособность. Уточнение безопасности по решению владельца24Oct2026: пять findings deep scan. Проверка — counter/window/rollback regression и конкурентные PostgreSQL/auth-route tests. |
| `PWASEC-14` | Personal TOTP остаётся optional, пока пользователь явно его не включил. |
| `PWASEC-15` | TOTP использует стандартный protocol и не привязан к одному authenticator app. |
| `PWASEC-16` | TOTP enrollment имеет проверяемую secret-confirmation boundary. |
| `PWASEC-17` | TOTP recovery определён и протестирован. |
| `PWASEC-18` | TOTP disable требует безопасной owner verification. |
| `PWASEC-19` | После успешного подтверждения паролем и, если 2FA включена, одноразовым кодом владелец может явно выбрать «Запомнить это устройство на 30 дней»; сервер выдаёт ограниченное этим браузером доверие без раскрытия секрета в Java Script. Вход и login 2FA не пропускаются. |
| `PWASEC-20` | Пока доверие не истекло и не отозвано, владелец в действующей сессии выполняет разрешённые sensitive actions после обычного 10-минутного окна без нового пароля; отсутствие, чужое, истёкшее или отозванное доверие требует обычной re-authentication. |
| `PWASEC-21` | Владелец видит срок доверия и может отозвать его для текущего или всех браузеров; сброс пароля и изменение 2FA отзывают доверие. Отзыв проверяется сервером на следующей защищённой операции. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `GOOGLE-DRIVE-RELIABILITY-02` — Drive upload/token/preflight reliability

| AC | Проверяемое требование |
|---|---|
| `GOOGLE-01` | Upload обработанного media в Google Drive поддерживает resumable protocol. |
| `GOOGLE-02` | Invalid/revoked Google grant создаёт явное состояние reconnect. |
| `GOOGLE-03` | Disconnect удаляет сохранённый Google token material. |
| `GOOGLE-04` | Disconnect пытается выполнить provider-side token revocation, когда это поддерживается. |
| `GOOGLE-05` | До provider spend повторно проверяется доступность source. |
| `GOOGLE-06` | До provider spend повторно проверяется возможность записи в target folder. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `STORAGE-LIFECYCLE-02` — полный storage lifecycle

| AC | Проверяемое требование |
|---|---|
| `STORAG-01` | Все большие S3-compatible uploads поддерживают resumable или multipart protocol. |
| `STORAG-02` | Abandoned upload sessions периодически очищаются. |
| `STORAG-03` | Failed/request-scoped FFmpeg temporary files очищаются. |
| `STORAG-04` | Orphaned storage objects периодически reconciliate и очищаются. |
| `STORAG-05` | Cleanup удаляет obsolete object versions при включённом storage versioning. |
| `STORAG-06` | Загруженные исходники транскрибаций имеют выбираемый срок 3/7/30 дней и видимую дату удаления. Проверка: настройка новых загрузок, readback expiry и сохранение сроков уже загруженных файлов; политика не применяется к Live. Q162..164,Q178. |
| `STORAG-07` | Готовое подготовленное аудио не сохраняется отдельным finished object в S3; скачивание/Google Drive и request-scoped cleanup сохраняют доступный пользователю результат. Q169. |
| `STORAG-08` | Исходники серверной подготовки аудио с устройства имеют отдельную выбираемую политику 3/7/30 дней и видимую дату удаления. Q162,Q163,Q177,Q178. |
| `STORAG-09` | Transcription reference files имеют отдельную явную retention policy. |
| `STORAG-10` | Правила для текста различаются: Live — до ручной очистки, временный обычный STT text — до успешного полного документа либо явной отмены, затем удаляется. Проверка: >72 h/>24 h, export retry/cancel/success и отсутствие тела в diagnostics. Q118,Q131,Q133,Q175. |
| `STORAG-11` | Temporary files имеют явную retention/TTL policy. |
| `STORAG-12` | History data имеет явную retention policy. |
| `STORAG-13` | Analytics data имеет явную retention policy. |
| `STORAG-14` | Diagnostic/log data имеет явную retention policy. |
| `STORAG-15` | Deletion считается завершённым только после подтверждения cleanup всеми internal stores. |
| `STORAG-16` | Audio-processing references и transcription references являются разными data classes. |
| `STORAG-17` | Audio-reference использует отдельный S3 bucket. |
| `STORAG-18` | Transcription-reference использует отдельный S3 bucket. |
| `STORAG-19` | Audio-reference bucket имеет независимые lifecycle rules. |
| `STORAG-20` | Transcription-reference bucket имеет независимые lifecycle rules. |
| `STORAG-22` | Загруженная копия исходника созвона автоматически удаляется после подтверждённого создания всех полных документов по нему; failed/partial/export-unresolved и active jobs не удаляют bytes, оригинал устройства не затрагивается. Проверка: multiple fragments/all-success/one-failure/retry/concurrency. Q168. |
| `STORAG-21` | Два reference buckets имеют независимо ограниченные access permissions. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `STT-PROVIDER-ABSTRACTION-01` — provider-neutral STT contract

| AC | Проверяемое требование |
|---|---|
| `STTPRO-01` | Batch STT выполняется через provider-neutral interface. |
| `STTPRO-02` | Realtime STT выполняется через provider-neutral interface. |
| `STTPRO-03` | Provider capability metadata фиксирует supported operating modes. |
| `STTPRO-04` | Provider capability metadata фиксирует supported languages. |
| `STTPRO-05` | Provider capability metadata фиксирует diarization support. |
| `STTPRO-06` | Provider capability metadata фиксирует dictionary support. |
| `STTPRO-07` | Provider capability metadata фиксирует file constraints. |
| `STTPRO-08` | User-facing economic mode маппится на configured provider capability. |
| `STTPRO-09` | User-facing standard mode маппится на configured provider capability. |
| `STTPRO-10` | User-facing premium mode маппится на configured provider capability. |
| `STTPRO-11` | User-facing realtime mode маппится на configured provider capability. |
| `STTPRO-12` | Provider/mode health может остановить новый dispatch после массовых failures. |
| `STTPRO-13` | Automatic cross-provider fallback не выполняется. |
| `STTPRO-14` | BYOK eligibility конфигурируется отдельно для каждого provider. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `YANDEX-STT-01` — Yandex Speech Kit provider

| AC | Проверяемое требование |
|---|---|
| `YANDEX-01` | Yandex Speech Kit поддерживает обычную batch transcription. |
| `YANDEX-02` | Yandex Speech Kit поддерживает deferred transcription. |
| `YANDEX-03` | Yandex Speech Kit поддерживает realtime transcription. |
| `YANDEX-04` | Deferred Yandex jobs сохраняют provider operation ID. |
| `YANDEX-05` | Deferred Yandex jobs poll и сохраняют terminal provider result. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `PWA-DICTIONARIES-01` — пользовательские словари

| AC | Проверяемое требование |
|---|---|
| `PWADIC-01` | Owner-scoped dictionaries поддерживают terms, surnames, names и abbreviations для улучшения STT. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `PWA-WORKER-ISOLATION-02` — worker resource и privilege boundary

| AC | Проверяемое требование |
|---|---|
| `PWAWOR-01` | Media/FFmpeg worker работает как component, отделённый от API process. |
| `PWAWOR-02` | Media/FFmpeg worker имеет явные CPU/memory/process resource bounds. |
| `PWAWOR-03` | Media/FFmpeg worker имеет минимально необходимые filesystem/network/database privileges. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `PWA-DATABASE-LEAST-PRIVILEGE-03` — отдельные PostgreSQL owner, migrator и runtime roles

| AC | Проверяемое требование |
|---|---|
| `DBLP-01` | Running API использует отдельную login role без `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `REPLICATION`, `BYPASSRLS`, schema ownership или DDL privileges. |
| `DBLP-02` | Protected migrations используют отдельную migrator login role, не доступную API/worker и ограниченную одной Studio database/schema ownership boundary. |
| `DBLP-03` | Schema/tables/sequences принадлежат отдельной `NOLOGIN` owner role; bootstrap/admin login не является ordinary runtime owner. |
| `DBLP-04` | API, worker, migrator и bootstrap credentials хранятся в разных root-owned secret files; bootstrap credential не монтируется в API/worker containers. |
| `DBLP-05` | Reviewed API/worker direct-grant manifests сначала revoke broad access/memberships, затем выдают минимальные table/sequence grants; public schema CREATE и implicit grants запрещены. |
| `DBLP-06` | Default privileges и protected migration flow fail closed re-apply/verify API/worker grants после additive schema change до component recreation. |
| `DBLP-07` | Clean initialization и upgrade проверяют positive/negative role matrix, schema ownership, Alembic current/head, API/worker readiness и отсутствие privilege escalation. |
| `DBLP-08` | Production switch имеет verified pre-change backup, staged credential/role preflight, bounded API smoke и explicit compatible rollback/recovery без возврата bootstrap/superuser credential в runtime. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `JOB-RELIABILITY-02` — durable batch execution contract

| AC | Проверяемое требование |
|---|---|
| `JOBREL-01` | Transcription jobs используют durable queue. |
| `JOBREL-02` | Каждая job сохраняет явное processing-stage state. |
| `JOBREL-03` | Каждая job сохраняет last safe checkpoint. |
| `JOBREL-04` | После worker restart перед claim выполняется bounded locked recovery истёкших processing leases: durable outputs → completed, cancel → cancelled, доказуемо retry-safe → queued; неизвестный/оплаченный неопределённый результат → attention state без нового STT/Google create. Live leases и stale owners защищены fencing. Проверка: lifecycle/real worker entry tests и PostgreSQL concurrency/rollback. WK-01, owner decision24Oct2026. |
| `JOBREL-05` | Автоматически повторяются только доказуемо безопасные transient failures. |
| `JOBREL-06` | Retry/recovery не дублирует provider operations. |
| `JOBREL-07` | Retry/recovery не дублирует Google Docs outputs. |
| `JOBREL-08` | Retry/recovery не дублирует storage files. |
| `JOBREL-09` | Retry/recovery не дублирует notifications. |
| `JOBREL-10` | Critical job/queue/service events имеют guaranteed-delivery mechanism. |
| `JOBREL-11` | Queued transcription можно отменить. |
| `JOBREL-12` | Для running transcription можно запросить cancel; она останавливается на safe boundaries. |
| `JOBREL-13` | Server job продолжается после закрытия PWA пользователем. |
| `JOBREL-14` | UI показывает текущую processing stage. |
| `JOBREL-15` | Source availability проверяется до provider dispatch. |
| `JOBREL-16` | Target write readiness проверяется до provider dispatch. |
| `JOBREL-17` | После immutable authoritative snapshot долгие source availability/materialization и media preparation операции не удерживают idle worker DB transaction; после I/O выполняется fresh fail-closed lifecycle/source/credential/output revalidation до любого provider call. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `JOB-NOTIFICATIONS-01` — уведомления о завершении/error

| AC | Проверяемое требование |
|---|---|
| `JOBNOT-01` | **SUPERSEDED: требование отменено владельцем25Oct2026, вне denominator.** Web Push об успехе не требуется; вместо него JOBNOT-05. |
| `JOBNOT-02` | **SUPERSEDED: требование отменено владельцем25Oct2026, вне denominator.** Web Push об ошибке не требуется; вместо него JOBNOT-06. |
| `JOBNOT-03` | **SUPERSEDED: требование отменено владельцем25Oct2026, вне denominator.** Email об успехе не требуется; вместо него JOBNOT-05. |
| `JOBNOT-04` | **SUPERSEDED: требование отменено владельцем25Oct2026, вне denominator.** Email об ошибке не требуется; вместо него JOBNOT-06. |
| `JOBNOT-05` | После явного opt-in настроенный Telegram-бот уведомляет об успешном завершении. Получатель привязан к конкретному owner; другой/disabled owner не может использовать этот chat. Повторные intent/claim не создают дублей; внешняя доставка at-least-once при потерянном ACK. Проверка: owner/opt-out, durable retry, positive message ACK, безопасный payload и разрешённая реальная доставка после настройки. |
| `JOBNOT-06` | Telegram уведомляет о terminal error; автоматический retry подавляет устаревшее сообщение предыдущей попытки. Ошибка Telegram не отменяет обработку и не скрывает готовый результат. Проверка: terminal/retry races, claim fences/backoff, malformed/negative ACK и ошибочный получатель без отправки. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `REALTIME-CONTINUITY-02` — expanded realtime consumers

| AC | Проверяемое требование |
|---|---|
| `REALTI-01` | Capture-source loss и STT-connection loss отображаются как разные user-visible errors. |
| `REALTI-02` | Realtime subtitles доступны через отдельный browser/OBS overlay. |
| `REALTI-03` | Realtime subtitles могут передаваться в You Tube Live. |
| `REALTI-04` | Realtime subtitles могут передаваться другому явно поддержанному external consumer. |
| `REALTI-05` | Failure одного external realtime consumer не останавливает primary session. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `TRANSCRIPT-EXPORTS-02` — дополнительные export formats

| AC | Проверяемое требование |
|---|---|
| `TRANSC-01` | Сохранённый Live-текст скачивается как Markdown без нового STT. Проверка: Unicode, paragraphs/speakers и escaping. Q134. |
| `TRANSC-02` | Live-текст с подтверждёнными временными данными скачивается как SRT с корректным порядком/диапазонами; без timing показано ограничение. Q135..137. |
| `TRANSC-03` | Live-текст с подтверждёнными временными данными скачивается как VTT с корректным порядком/диапазонами; без timing показано ограничение. Q135..137. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `USAGE-COST-ACCOUNTING-01` — personal usage/cost evidence

| AC | Проверяемое требование |
|---|---|
| `USAGEC-01` | Каждая transcription job хранит подтверждённую длительность audio, фактически отправленную provider; uncertain outcome не выдаётся за exact billed usage. |
| `USAGEC-02` | Каждая transcription job хранит nominal attributable cost как `confirmed duration × immutable public tariff snapshot`, currency и provenance; этот расчёт явно не выдаётся за invoice debit после подписки или квоты. |
| `USAGEC-03` | Для каждого активного Eleven Labs credential Studio server-side получает из official account API tier/status, period usage/limit, reset, usage-based billing entitlement/cap, current overage и open/next invoice без передачи API key в браузер. |
| `USAGEC-04` | Studio получает из official workspace analytics API credit usage по продуктам за применимый billing/rolling period, сохраняет нормализованный bounded snapshot и не преобразует credits в минуты без provider Evidence. |
| `USAGEC-05` | Owner UI раздельно показывает job-level nominal cost и provider account actuals, включая provider-reported remaining period units, overage и invoice amounts; unavailable или semantically incomparable данные не подменяются расчётной цифрой. |
| `USAGEC-06` | Account snapshot имеет видимые `fetched_at`, period/window provenance и current/stale/unavailable state; при открытом экране выполняется bounded refresh, ручное обновление доступно, а provider error сохраняет последний успешный snapshot только как stale. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `OBSERVABILITY-AUDIT-02` — health, tracing, alerts и protected audit

| AC | Проверяемое требование |
|---|---|
| `OBSERV-01` | `job_id` проходит через весь batch pipeline. |
| `OBSERV-02` | `request_id` проходит через request-to-job boundary. |
| `OBSERV-03` | `trace_id` проходит через весь cross-service pipeline. |
| `OBSERV-04` | Admin health показывает backend status. |
| `OBSERV-05` | Admin health показывает PostgreSQL status. |
| `OBSERV-06` | Admin health показывает queue status. |
| `OBSERV-07` | Admin health показывает worker status. |
| `OBSERV-08` | Admin health показывает S3 status. |
| `OBSERV-09` | Admin health показывает STT provider status. |
| `OBSERV-10` | Admin health показывает email status. |
| `OBSERV-11` | Backend предоставляет отдельный liveness probe. |
| `OBSERV-12` | Backend предоставляет отдельный readiness probe. |
| `OBSERV-13` | Worker предоставляет отдельный liveness probe. |
| `OBSERV-14` | Worker предоставляет отдельный readiness probe. |
| `OBSERV-15` | Critical-error alerts отправляются. |
| `OBSERV-16` | Stuck-queue alerts отправляются. |
| `OBSERV-17` | Provider-unavailability alerts отправляются. |
| `OBSERV-18` | Backup/cleanup failure alerts отправляются. |
| `OBSERV-19` | Alerts отправляются при приближении к storage/API limits. |
| `OBSERV-20` | Secrets исключены из logs и diagnostics. |
| `OBSERV-21` | User data по умолчанию минимизированы в logs и diagnostics. |
| `OBSERV-22` | Diagnostics показывают release version. |
| `OBSERV-23` | Diagnostics показывают environment. |
| `OBSERV-24` | Diagnostics показывают web build identity. |
| `OBSERV-25` | Diagnostics показывают API build identity. |
| `OBSERV-26` | Diagnostics показывают worker build identity. |
| `OBSERV-27` | Diagnostics показывают exact commit identity. |
| `OBSERV-28` | Diagnostics показывают exact DB schema revision. |
| `OBSERV-29` | Audit record идентифицирует actor. |
| `OBSERV-30` | Audit record идентифицирует время действия. |
| `OBSERV-31` | Audit record идентифицирует action. |
| `OBSERV-32` | Audit record идентифицирует operation outcome. |
| `OBSERV-33` | Ordinary application flows не могут изменять прошлые audit records. |
| `OBSERV-34` | Ordinary application flows не могут удалять audit records. |
| `OBSERV-35` | Очистка History/Analytics не удаляет audit records. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.

### Эпик `RELEASE-SAFETY-02` — personal release safety

| AC | Проверяемое требование |
|---|---|
| `RELEAS-01` | Все PostgreSQL schema changes используют versioned migrations. |
| `RELEAS-02` | Personal production имеет tested rollback procedure. |
| `RELEAS-03` | Deployment валидирует required environment configuration. |
| `RELEAS-04` | Deployment валидирует required secrets без раскрытия values. |
| `RELEAS-05` | Deployment fail-closed при отсутствии critical settings. |

Проверка AC этого эпика: Unit/component/contract проверки позитивного и негативного сценария, owner isolation и повторов; browser проверяет пользовательский результат; внешние side effects и recovery — отдельный разрешённый сценарий точной версии. Конкретные существующие suites и незакрытые gaps — в [delivery dashboard](../delivery-plan.md). Наличие suite не подтверждает её полноту.


### Эпик `PERSONAL-TECHNICAL-01` — проверяемые ограничения стека

| AC | Проверяемое требование |
|---|---|
| `TECH-01` | Frontend использует React/TypeScript/Vite и PWA manifest/service worker; сборка проходит typecheck и создаёт update-capable PWA. Q275. |
| `TECH-02` | API — Python/FastAPI, authoritative данные PostgreSQL через SQLAlchemy и versioned Alembic; миграция isolated DB до единственного head совместима с API/worker. Q276,Q277. |
| `TECH-03` | Redis обеспечивает shared service limits; недоступность Redis в защищённых capability/rate-limit paths не отключает соответствующую проверку незаметно. Q278. |
| `TECH-04` | Server preparation использует bounded FFmpeg; local processing использует browser capabilities, unsupported codec/resources сообщаются до обработки. Q279. |
| `TECH-05` | Внутренние файлы используют S3-compatible boundary, production units — Docker Compose/Nginx; configuration не смешивает внешние пользовательские диски и internal storage. Q280,Q282,Q286. |

Проверка: clean CI build/API/DB/Compose с synthetic configuration, positive/negative configuration и bounded media; реальные providers не вызываются. Эти AC восстанавливают явно заданные технические требования, не вводят новый stack.
