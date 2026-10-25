# Спецификация проекта VoiceOps Studio

## 1. Назначение, источники и область

VoiceOps Studio — PWA подготовки аудио, обычной транскрибации файлов/фрагментов и Live-текста. Текущий этап — personal для владельца. Полный будущий commercial scope сохранён отдельно и не блокирует готовность personal. Colab — самостоятельный стабильный personal вариант с ограниченной поддержкой существующего назначения.

Решение владельца23Oct2026 `OWNER-REBRAND-20261023`: единый бренд всего проекта — VoiceOps Studio, canonical repository `Just9120/voiceops-studio`; ElevenLabs остаётся названием provider. Отображаемое имя существующего Google Cloud project меняется без смены project/client IDs. Публичные страницы описания и обработки данных отражают personal реализацию и доступны до входа. Stateful deployment identifiers и existing data сохраняются; compatibility/strict CI/CD — часть переименования, а не поручение миграции данных. Проверяемые критерии BRAND-01..05 — в [расширениях](spec/extensions.md#эпик-brand-voiceops-01--единый-бренд-и-публичная-информация).

Решение владельца25Oct2026 `OWNER-PERSONAL-INTEGRATIONS-20261025`: automatic voice identity исключена окончательно; обычная diarization и ручные имена сохраняются. Task notifications — только Telegram, Web Push/email исключены. Personal access/security mail F66 остаётся DEFER, восстановление — через защищённую VPS-процедуру и TOTP recovery codes. Регулярные backups и freshness/target monitoring принадлежат Cloudkeep; Studio сохраняет фактические protected pre-migration backup outcomes. Выбран полный personal Яндекс Диск; commercial и F62 остаются вне этой Goal.

Canonical требования и атомарные AC — здесь и в индексируемых spec; состояния, Evidence, findings и checkpoint — только [delivery-plan](delivery-plan.md). Workflow/полномочия — [AGENTS](../AGENTS.md). Запись requirement/finding не разрешает исполнение.

## Источники и решения

Согласованный Google Doc ID `1uaYvnqpbns_iyHTtQDZYjNYygT4ikUhmhuhRDWySrzI` повторно прочитан полностью 2026-10-10; содержание и 308 пунктов не изменились с аудита 2026-10-04, modifiedTime `2026-09-27T19:48:44.099Z`, 308 пунктов Q001..Q308. [Source trace](spec/source-trace.md) сохраняет все пункты, актуальные AC/constraints и исторические S-ID. Прежняя revision 2026-09-05 содержала 289 пунктов; перенос её процентов без сверки недопустим. Неповторённые старые AC сохранены, явно изменённые — обновлены либо SUPERSEDED со связями. Последующие решения PWA update prompt, document-based retry и trusted device30 days остаются обязательными.

Решения25Oct2026 синхронизированы scoped native Google Doc edits с requiredRevisionId/readback: voice identity исключена, task notifications только Telegram, personal recovery через authorized VPS console, регулярные backups через Cloudkeep; RPO новой цепочки UNSET, RTO4h сохранён. System mail F66 и lecture/cleaned procedure F62 отложены. Stable IDs/отменённые критерии не удаляются.

## Бизнес-правила и интерфейсы/данные

1. Навигация: обзор, подготовка аудио, транскрибации, настройки. Отдельной пользовательской сущности Project нет; технический legacy Project ID не создаёт продуктового обязательства.
2. Обычная транскрибация успешна только после подтверждённого полного внешнего документа: Google Doc либо DOCX на Яндекс Диске при выборе подключения. Начатый STT/пустой/частичный документ не success. Постоянная обычная Studio-копия не нужна; после успеха transient text очищается, внешний документ не синхронизируется.
3. При export failure готовый STT text хранится до полного документа либо явной отмены; export-only retry использует его без нового STT и отдельного подтверждения расхода. Активная задача, подтверждённый документ и неопределённое создание документа — разные состояния. Неудачный STT до документа не делает исходник обработанным; отсутствие документа подтверждается в доступном preflight действии.
4. Live-текст читается/скачивается/очищается в Studio независимо от облака. До ручной очистки сохраняется после reload без автоматического TTL; новая сессия сама текст не удаляет. Не требуются полная аудиозапись, редактирование текста и имён в PWA. DOCX/TXT/Markdown, SRT/VTT при подтверждённом timing; исправления провайдера заменяют соответствующий сегмент.
5. В S3 — device inputs серверной обработки, с раздельными buckets/политиками аудио и транскрибаций, выбором 3/7/30 дней и видимым expiry. Drive source не становится постоянной S3-копией. Готовое подготовленное аудио скачивается либо сохраняется в Google Drive без отдельного finished S3 object. Device-копия созвона удаляется после всех полных документов; cleanup не ломает active processing/recovery и не удаляет облачный оригинал/экспорт.
6. Manifest duplicate identity учитывает источник, fragments и настройки; filename alone недостаточен. Success только полный документ. Просмотр/очистка/сохранение манифеста и явный bypass; утраченному внешнему документу не соответствует автоматический платный повтор.
7. Единый transcript_doc: Heading2 title,11pt body, bold14pt «Спикер N:»; header Provider/Model/Language. Решение24Oct2026: дата из title не дублируется; опциональная ISO8601 дата при необходимости только из подтверждённого исходника, без mtime/job/currenttime. Fragments/concat/обработка сохраняют существенные пояснения без UUID/recipe JSON/boolean Speakers; полная provenance остаётся в Studio. Legacy valid date сохраняется без даты в title; конфликт с известным source блокирует mutation. Старый и компактный headers совместимы с каталогом.
8. Общий source limit12 h проверяется до fragmentation;4–12 h имеют до запуска оценку расхода и подтверждение. Provider-specific limits не обходятся скрытым fallback. Подготовка пауз показывает waveform/интервалы, прослушивание и duration comparison. Naming templates используют известные дату/время/название, не выдумывают metadata.
9. Google Drive — personal внешняя интеграция, Яндекс Диск — отдельная optional настройка personal и будущий commercial destination. Primary Google scope exact identity+drive.file+drive.readonly; расширенный maintenance access отдельно контролируется. Cloud failure не считается готовым обычным transcript document.
10. Production body/privatebytes/credentials не входят в logs, diagnostics, audit или Evidence. Owner-scoped content response не является diagnostics. STT/provider/Google side effects и чужие данные изолированы; TOTP/trusted-device не отменяют login2FA. Technical AC равноправны продуктовым.

## Индекс эпиков и AC

| Формулировки | Состояния/Evidence |
|---|---|
| [Colab](spec/colab.md) | [Реестр](delivery/colab.md) |
| [Personal Studio и технические требования](spec/studio.md) | [Реестр](delivery/studio.md) |
| [Live/exports, Yandex Disk, media/recovery](spec/extensions.md) | [Реестр](delivery/extensions.md) |
| [Будущая commercial реализация и общие interfaces](spec/commercial.md) | [Реестр](delivery/commercial.md) |

READY = исполняемый код и подходящие автоматические проверки; ручной acceptance процент не используется. Current personal включает Colab/Studio/extensions и общие technical EVC-33..48/50. SP-01..05 и VID-01..04 отложены Q009 и исключены только из current personal; commercial — будущий scope. ALIAS/SUPERSEDED исключены из всех denominators, ID сохранены. Полный roadmap дополнительно включает будущие commercial/voice AC. Числа находятся в плане; новая Goal scope не сокращает spec.

## NFR, архитектура и зависимости

Стек Q275..292: React/TypeScript/Vite PWA, Python/FastAPI, PostgreSQL/SQLAlchemy/Alembic, Redis для shared limits, FFmpeg/browser processing, S3-compatible storage, Docker Compose/Nginx. Проверяемые TECH-01..05 восстановлены отдельными атомарными AC. Least privilege/resource boundaries — DBLP/PWAWOR/PWASEC; backup/RPO/RTO/deletion restore — REC/RELEAS/STORAG. Конкретные commands/versions/config владельцы — [README](../README.md), [validation](runbooks/validation.md), [operations](runbooks/studio-platform-ops.md), [processing contract](studio-processing-contract.md), [architecture](architecture.md); найденный drift этих документов — findings, не новые политики.

Решение владельца17Oct2026: canonical Studio hostname меняется с `studio.librechat.online` на `studio.cloud-nodes.net`, VPS и Google-проект сохраняются. Это смена deployment configuration, без миграции пользовательских данных/новых продуктовых AC. Cookie sessions, доверие браузеру, локальные drafts и installed PWA между origins автоматически не переносятся. Процедура, external preconditions и recovery — [domain cutover](runbooks/studio-platform-ops.md#studio-domain-cutover-domain-studio-20261017); фактическое выполнение — в плане/первичных delivery records.

Яндекс Disk использует отдельное owner-scoped OAuth подключение и DOCX export с persisted receipt; timed Live exports — от сегментной модели и provider corrections. Изменение retention требует совместимой миграции existing drafts/checkpoints и recovery, а не очистки пользовательского текста. Утверждения runtime требуют primary deployment records и versioned smoke.

## Owner-triggered процедуры и открытые вопросы

- CONSTRAINT-LECTURE-AUDIT (Q301..306): по команде владельца через существующий Google Drive connector и модель по подписке сопоставить лекции с полными документами по source/result evidence (имени недостаточно), проверить качество/пропуски/термины и при доступном инструменте аудио, выдать ссылки, охват проверки и действия. Изменение документов и платный повтор согласуются отдельно. Это внешняя процедура, не автоматически запускаемый код Studio/LLM API/MCP feature; без поручения аудит лекций не выполняется и в code readiness denominator не входит.
- CONSTRAINT-CLEANED-EXPERIMENT (Q307..308): сравнение обычного/очищенного Eleven Labs на одинаковых коротких lecture/call fragments со смыслом/терминами/отрицаниями/повторами; выбор feature только после результатов и решения владельца. Default normal unchanged, никакого paid experiment в текущем AUDIT. Не включать будущую feature до решения.
- Automatic voice identity исключена владельцем25Oct2026: Q009/Q089..092 и VID сохраняются как историческая трассировка SUPERSEDED. Обычная пронумерованная diarization и manual names/roles сохраняются; matcher/voiceprints не требуются.
- Cloudflare Zero Trust — optional дополнительный слой, без обязательного deliverable. Commercial tariff/legal/provider решения не выдумываются; открытые поля UNSET в соответствующем spec.
- Требования содержат action/observable result/validation в соответствующих AC. Числовые SLO/coverage target не заданы. Отсутствующий runtime доступ/faithful fixture — Evidence gap, а не отмена требования.

## SPEC gap внешних процедур

`SPEC-GAP-OPS-01` относится к Q301..308: это действия владельца и внешней модели, а не функция, которую источник поручает встроить в Studio. Для отдельной Goal аудита лекций нужны выбранная папка/материалы и доступный способ аудио-сверки; для cleaned experiment — одинаковые согласованные короткие фрагменты и разрешённый provider scope. Критерии результата: подтверждённые source/result связи, отчёт с охватом и ограничениями, сохранность смысла/терминов/отрицаний, отсутствие несогласованных edits/paid calls. Измерение выполнения этих операций по коду Studio неприменимо. До отдельного поручения они остаются внешним процедурным scope и не расширяют denominator приложения; наличие connector не выдаётся за проведённый анализ.

## Durable technical и safety constraints

### Colab

- Provider failures показывают только safe scalar diagnostics: provider, status, endpoint без query и `detail`, `message`, `code`, `type`, `error.message`, `error.type`, `error.code`.
- Temporary cleanup ограничен TTL и prefix `elevenlabs_api_`; произвольные пользовательские файлы не удаляются.
- Parallel notebooks or tabs не являются поддерживаемой concurrency model manifest.
- Launcher исполняет repository code из `GITHUB_REF`; для production предпочтителен reviewed commit SHA.
- Existing-doc normalization остаётся selected-folder workflow that defaults to dry-run и разделяет selected-folder scan counters от apply-impact counters.
- `standard_check` хранит только target/detected standard, status, checked-at и checker version.
- Timestamped backups старого manifest содержат sensitive operational metadata и защищаются как active manifest.
- Visible metadata не публикует source filename/source mode.

### PWA ownership и processing

- Все projects, sources, jobs, credentials, connections, diagnostics, outputs, history и analytics owner-scoped.
- User-facing segment/project labels уникальны case-insensitively в своём owner/project scope.
- BYOK credentials encrypted at rest, расшифровываются server-side только для авторизованной операции и не возвращаются browser.
- Google tokens хранятся encrypted server-side; Picker access capability bounded, `no-store`, CSRF-protected и перепроверяется API.
- R2 object keys, presigned URLs, lease authority, transcript bodies и external payloads не входят в metadata DTO/logs/diagnostics; явный owner-scoped Live content endpoint для RS-01 является отдельным authenticated no-store boundary.
- Batch creation сохраняет immutable per-job output-folder snapshot. Изменение project default не перенаправляет существующую job.
- Claim/lease/cancellation checks выполняются на stage boundaries. Uncertain provider/output side effect не запускает automatic retry и переводится в explicit reconciliation.
- Exactly-once Google document creation не заявляется; успешное завершение требует persisted output evidence для каждого non-skipped source/fragment.
- Video audio extraction и automatic long-media split/merge остаются server-side, bounded и deterministic.
- Existing-document standardization мутирует только подходящие Google Docs; manifest import мутирует только PostgreSQL catalog metadata.
- Service worker не runtime-cache-ит API responses или upload requests.
- Обычные проверки, merge, deployment и recovery регулируют [AGENTS](../AGENTS.md), [validation](runbooks/validation.md) и [operations](runbooks/studio-platform-ops.md); настройку CI/CD и исправления pipeline — [CI/CD rules](ci-cd-rules.md).
