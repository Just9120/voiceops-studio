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
| `PC-06` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PC-07` | READY | ✅ | ✅ | ✅ | F46 исправлен #320/a666df1: exact initiating-session binding, чужая/отозванная/истёкшая session fail-closed; Linux CI 37154958672 и main CI 37155276745 PASS. |
| `PC-08` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PC-09` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PC-10` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PC-11` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PC-12` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PC-13` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PC-14` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PC-15` | READY | ✅ | ✅ | ✅ | Восстановлено по code и primary records 2026-09-30: PR #312/e01bc91, CI 35970014222/35970014302, web CD 35970355470 SUCCESS. |
| `PC-16` | READY | ✅ | ✅ | ✅ | Восстановлено по code и primary records 2026-09-30: PR #312/e01bc91, CI 35970014222/35970014302, web CD 35970355470 SUCCESS. |

### `PWA-USER-EXPERIENCE-02`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PUX-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PUX-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PUX-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PUX-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PUX-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PUX-06` | READY | ✅ | ✅ | ✅ | PR #309 merge 0d41180: local audio validation раскрывает настройки, фокусирует неверное поле и показывает inline/ARIA error; Vitest 751/751, Studio CI и browser-e2e PASS, web/API CD 35962179284 PASS. |
| `PUX-07` | READY | ✅ | ✅ | ✅ | PR #310 доставил `source_names`, PR #311 убрал второе отображение имени внутри группы; targeted/full Vitest 239/752 PASS, PR CI 35967620882/35967621016 и main CI 35967953699/35967953526 PASS. Web CD 35967953684, live web `02fc21d`: имя ровно один раз, номер элемента сохранён. |
| `PUX-08` | READY | ✅ | ✅ | ✅ | PR329 candidate c23fdc0, CI38141034993 SUCCESS11Oct2026 (test merge c1618886); ещё не main. F74/UXR04: Live reconnect и diarization copy соответствуют состоянию; component/browser PASS. |
| `PUX-09` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PUX-10` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PUX-11` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PUX-12` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PUX-13` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PUX-14` | READY | ✅ | ✅ | ✅ | PR332/main206c579; CI38477514519 (Python2135, UI819, browser17) и exact-main CI38478146748 SUCCESS14Oct. Delivery Goal отдельно pending; production UI проверки ограниченные. |
| `PUX-15` | READY | ✅ | ✅ | ✅ | PR332/main206c579; CI38477514519 (Python2135, UI819, browser17) и exact-main CI38478146748 SUCCESS14Oct. Delivery Goal отдельно pending; production UI проверки ограниченные. |
| `PUX-16` | READY | ✅ | ✅ | ✅ | PR332/main206c579; CI38477514519 (Python2135, UI819, browser17) и exact-main CI38478146748 SUCCESS14Oct. Delivery Goal отдельно pending; production UI проверки ограниченные. |
| `PUX-17` | READY | ✅ | ✅ | ✅ | PR332/main206c579; CI38477514519 (Python2135, UI819, browser17) и exact-main CI38478146748 SUCCESS14Oct. Delivery Goal отдельно pending; production UI проверки ограниченные. |
| `PUX-18` | READY | ✅ | ✅ | ✅ | PR332/main206c579; CI38477514519 (Python2135, UI819, browser17) и exact-main CI38478146748 SUCCESS14Oct. Delivery Goal отдельно pending; production UI проверки ограниченные. |
| `PUX-19` | READY | ✅ | ✅ | ✅ | PR332/main206c579; CI38477514519 (Python2135, UI819, browser17) и exact-main CI38478146748 SUCCESS14Oct. Delivery Goal отдельно pending; production UI проверки ограниченные. |
| `PUX-20` | READY | ✅ | ✅ | ✅ | Восстановлено18Oct по primary records PR333/def1750: current-head CI38735119529, platform38735693476 и worker38736484985 SUCCESS. Selected preview compatibility fail-closed исправлен; прежний pre-merge checkpoint устарел. |
| `PUX-21` | READY | ✅ | ✅ | ✅ | PR332/main206c579; CI38477514519 (Python2135, UI819, browser17) и exact-main CI38478146748 SUCCESS14Oct. Delivery Goal отдельно pending; production UI проверки ограниченные. |
| `PUX-22` | READY | ✅ | ✅ | ✅ | PR332/main206c579; CI38477514519 (Python2135, UI819, browser17) и exact-main CI38478146748 SUCCESS14Oct. Delivery Goal отдельно pending; production UI проверки ограниченные. |
| `PUX-23` | READY | ✅ | ✅ | ✅ | PR332/main206c579; CI38477514519 (Python2135, UI819, browser17) и exact-main CI38478146748 SUCCESS14Oct. Delivery Goal отдельно pending; production UI проверки ограниченные. |

Основание PUX-14..23: owner decision14Oct2026 — все правки повторного UX/UI-ревью выбраны единой Goal. Исправления UXR20/21/12/19 уточняют existing AP/PUX/cost AC, сами findings denominator не увеличивают. Черновики хранятся только в текущей browser session; полного восстановления File после закрытия приложения не обещают.


### `PWA-UX-POLISH-03`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `UXPOL-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `UXPOL-02` | SUPERSEDED | — | — | — | Вне denominator; актуальные AC: PTM-01 |
| `UXPOL-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `UXPOL-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `UXPOL-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `UXPOL-06` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `UXPOL-07` | READY | ✅ | ◐ | ✅ | Поиск/выбор уже реализован, App.tsx:9437–9454; V26-WEB PASS; historical browser scenario не подтверждён этим record, current representative UI scope A20261010-RUNTIME |
| `UXPOL-08` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

### `PWA-UX-CONTROLS-04`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `UXCTL-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `UXCTL-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `UXCTL-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `UXCTL-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `UXCTL-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `UXCTL-06` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `UXCTL-07` | READY | ✅ | ✅ | ✅ | V28-DELIVERY / PR #303 / web 3e65322: F22–F24 закрыты; PR/main CI PASS. Read-only LIVE подтверждает доступность интерфейса; destructive production scenario не выполнялся. Regression поведение проверено synthetic tests. |
| `UXCTL-08` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `UXCTL-09` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `UXCTL-10` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `UXCTL-11` | READY | ✅ | ◐ | ✅ | V28-DELIVERY / PR #303 / web 3e65322: F22–F24 закрыты; PR/main CI PASS. Read-only LIVE подтверждает доступность интерфейса; destructive production scenario не выполнялся. Regression поведение проверено synthetic tests. |
| `UXCTL-12` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `UXCTL-13` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `UXCTL-14` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

### `PWA-TRANSCRIPTIONS-UX-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PT-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PT-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PT-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PT-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

### `PWA-INGEST-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PI-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PI-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PI-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PI-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PI-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PI-06` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PI-07` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PI-08` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PI-09` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PI-10` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PI-11` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

### `PWA-GOOGLE-PICKER-UX-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PG-01` | READY | ✅ | ✅ | ◐ | V30-LAYOUT-LOCAL: исправлена grid regression после #305; geometry PASS desktop/mobile, поправка merged; current CI37502013651/production identity PASS10Oct, geometry этого конкретного сценария runtime отдельно не повторялась |
| `PG-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PG-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PG-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PG-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PG-06` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PG-07` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PG-08` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PG-09` | READY | ✅ | ✅ | ⏳ | V30-DELIVERY: #305/a56afb8, required CI и web/API/worker CD PASS; real numeric/sorting smoke PASS, Google writes покрыты fakes |

### `PWA-SEGMENTS-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PS-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PS-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PS-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PS-04` | READY | ✅ | ✅ | PENDING | V-REVIEW-FIXES-18 candidate: независимый EOF каждого фрагмента, per-field errors, known prepared duration до подтверждения; unknown duration явно pending до probe. Local focused tests PASS; REQUIRED API/DB Linux CI до merge. На baseline b7f9d48 — IN_PROGRESS по UXR26/27. |
| `PS-05` | READY | ✅ | ✅ | PENDING | V-REVIEW-FIXES-18 candidate: removed cross-fragment ordering/overlap/EOF restriction, preserved individual range/owner/idempotency constraints. Model/unit PASS; API persistence/negative tests REQUIRED Linux CI. На baseline b7f9d48 — IN_PROGRESS по UXR26. |

### `PWA-BATCH-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PB-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PB-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PB-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PB-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PB-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PB-06` | READY | ✅ | ✅ | ✅ | A20261010-CODE/CI; job_processing_orchestrator.py, job_google_docs_output.py; тесты Google output/orchestration. Яндекс Диск учитывается отдельно YD-05; не реализован. |
| `PB-07` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PB-08` | READY | ✅ | ◐ | ✅ | CONCISE-METADATA-20261024/code586c32d: compact provider/model/language, optional nonduplicated date, meaningful clip/prepared provenance; old headers/catalog compatible. Local188 focused synthetic tests PASS; Linux required CI и exact API/worker delivery PENDING до PR/merge,16 native Docs edits tracked in Current Goal. |
| `PB-09` | READY | ✅ | ◐ | ✅ | CONCISE-METADATA-20261024/code586c32d: compact provider/model/language, optional nonduplicated date, meaningful clip/prepared provenance; old headers/catalog compatible. Local188 focused synthetic tests PASS; Linux required CI и exact API/worker delivery PENDING до PR/merge,16 native Docs edits tracked in Current Goal. |
| `PB-10` | READY | ✅ | ✅ | ✅ | CONCISE-METADATA-20261024/code586c32d: compact provider/model/language, optional nonduplicated date, meaningful clip/prepared provenance; old headers/catalog compatible. Local188 focused synthetic tests PASS; Linux required CI и exact API/worker delivery PENDING до PR/merge,16 native Docs edits tracked in Current Goal. |
| `PB-11` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

### `PWA-AUDIO-PREPARATION-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `AP-01` | READY | ✅ | ✅ | ✅ | V26-BROWSER + V26-CD + V26-CI; полный узкий AC подтверждён |
| `AP-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `AP-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `AP-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `AP-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `AP-06` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `AP-07` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `AP-08` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `AP-09` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `AP-10` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `AP-11` | READY | ✅ | ✅ | ✅ | V27 / PR #302: full dotted Unicode title, processor/API и actual local download; web/API/worker 84ae25f. Новый Drive side effect не выполнялся в проверках агента; это ограничение Evidence |
| `AP-12` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `AP-13` | READY | ✅ | ✅ | ✅ | F41 исправлен #318/8d9f45d: output сохранён до initial Drive export, cancellation/recovery; CI 36701312137/36701312154 PASS, current main CI 37155276745/37155276751 PASS. |
| `AP-14` | READY | ✅ | ✅ | ✅ | PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). metadata-only output, worker regeneration из retained originals без STT/S3; independent download/Drive/handoff, selected retention и512-point waveform/sample. Audio/API/lease/cleanup/component regressions PASS; real synthetic FFmpeg local PASS,5 Linux FFmpeg skips без binary. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |
| `AP-15` | READY | ✅ | ✅ | ✅ | F41 исправлен #318/8d9f45d: output сохранён до initial Drive export, cancellation/recovery; CI 36701312137/36701312154 PASS, current main CI 37155276745/37155276751 PASS. |
| `AP-16` | READY | ✅ | ✅ | ✅ | PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). metadata-only output, worker regeneration из retained originals без STT/S3; independent download/Drive/handoff, selected retention и512-point waveform/sample. Audio/API/lease/cleanup/component regressions PASS; real synthetic FFmpeg local PASS,5 Linux FFmpeg skips без binary. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |
| `AP-17` | READY | ✅ | ✅ | ✅ | PR #309 merge 0d41180: локальный результат остаётся доступным при переходе между разделами той же вкладки; regression App component и 751/751 Vitest PASS, Studio CI/browser-e2e и web CD 35962179284 PASS. Обновление/закрытие вкладки не обещает durable storage. |
| `AP-18` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `AP-19` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `AP-20` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `AP-21` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `AP-22` | READY | ✅ | ✅ | ⏳ | V30-DELIVERY: #305/a56afb8, required CI и web/API/worker CD PASS; real numeric/sorting smoke PASS, Google writes покрыты fakes |
| `AP-23` | READY | ✅ | ✅ | ✅ | PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). metadata-only output, worker regeneration из retained originals без STT/S3; independent download/Drive/handoff, selected retention и512-point waveform/sample. Audio/API/lease/cleanup/component regressions PASS; real synthetic FFmpeg local PASS,5 Linux FFmpeg skips без binary. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |
| `AP-24` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `AP-25` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `AP-26` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `AP-27` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `AP-28` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `AP-29` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `AP-31` | READY | ✅ | ✅ | ✅ | PR332/main206c579: media-src self/blob, security-header contracts и реальный Chromium WAV playback PASS; CI38477514519/exact main38478146748 SUCCESS14Oct. Прежнее processing Evidence сохраняется. Edge38478332090 ждёт owner gate; production playback ещё не подтверждён. |
| `AP-30` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

### `PWA-SPEAKER-IDENTITY-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `SP-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `SP-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `SP-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `SP-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `SP-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

### `PWA-MANIFEST-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PM-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PM-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PM-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PM-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PM-05` | IN_PROGRESS | ◐ | ◐ | ✅ | A20261010-CODE/CI; full Google Doc и failed-export guards реализованы; unfinished text до документа/cancel подтверждён PR326. Optional DOCX destination на Яндекс Диске отсутствует (F02); прежний TTL finding F01 закрыт. |
| `PM-06` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PM-07` | READY | ✅ | ✅ | ✅ | PR #313–#316 поставлены; последний merge `3902b2a`, main CI 36285760379/36285760427 и web/API CD 36285760435 PASS. Принятый связанный catalog-result блокирует подтверждение отсутствия; private replay исходного файла не проверен. |

### `PWA-STANDARDIZATION-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PD-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PD-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PD-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PD-04` | READY | ✅ | ◐ | ✅ | CONCISE-METADATA-20261024/code586c32d: compact provider/model/language, optional nonduplicated date, meaningful clip/prepared provenance; old headers/catalog compatible. Local188 focused synthetic tests PASS; Linux required CI и exact API/worker delivery PENDING до PR/merge,16 native Docs edits tracked in Current Goal. |
| `PD-05` | READY | ✅ | ◐ | ✅ | CONCISE-METADATA-20261024/code586c32d: compact provider/model/language, optional nonduplicated date, meaningful clip/prepared provenance; old headers/catalog compatible. Local188 focused synthetic tests PASS; Linux required CI и exact API/worker delivery PENDING до PR/merge,16 native Docs edits tracked in Current Goal. |
| `PD-06` | READY | ✅ | ◐ | ✅ | CONCISE-METADATA-20261024/code586c32d: compact provider/model/language, optional nonduplicated date, meaningful clip/prepared provenance; old headers/catalog compatible. Local188 focused synthetic tests PASS; Linux required CI и exact API/worker delivery PENDING до PR/merge,16 native Docs edits tracked in Current Goal. |
| `PD-07` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PD-08` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PD-09` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PD-10` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PD-11` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PD-12` | READY | ✅ | ◐ | ✅ | CONCISE-METADATA-20261024/code586c32d: compact provider/model/language, optional nonduplicated date, meaningful clip/prepared provenance; old headers/catalog compatible. Local188 focused synthetic tests PASS; Linux required CI и exact API/worker delivery PENDING до PR/merge,16 native Docs edits tracked in Current Goal. |
| `PD-13` | READY | ✅ | ◐ | ✅ | CONCISE-METADATA-20261024/code586c32d: compact provider/model/language, optional nonduplicated date, meaningful clip/prepared provenance; old headers/catalog compatible. Local188 focused synthetic tests PASS; Linux required CI и exact API/worker delivery PENDING до PR/merge,16 native Docs edits tracked in Current Goal. |
| `PD-14` | READY | ✅ | ◐ | ✅ | CONCISE-METADATA-20261024/code586c32d: compact provider/model/language, optional nonduplicated date, meaningful clip/prepared provenance; old headers/catalog compatible. Local188 focused synthetic tests PASS; Linux required CI и exact API/worker delivery PENDING до PR/merge,16 native Docs edits tracked in Current Goal. |

### `PWA-TRANSCRIPT-MAINTENANCE-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PTM-01` | READY | ✅ | ✅ | ✅ | PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). Обслуживание в транскрибациях, settings link и metadata naming; maintenance/component/browser checks PASS, provider/Google boundaries fake. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |
| `PTM-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PTM-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PTM-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PTM-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PTM-06` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PTM-07` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PTM-08` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PTM-09` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

### `PWA-REALTIME-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PR-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PR-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PR-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PR-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PR-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PR-06` | READY | ✅ | ◐ | ✅ | CODE 84ae25f: realtimeSession.ts:340–439 — capture ownership, source loss, mix и cleanup; realtimeSession.test.ts:222–402 — permission/source cases. Full production capture matrix не запускалась |
| `PR-07` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PR-08` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PR-09` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PR-10` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PR-11` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PR-12` | READY | ✅ | ✅ | ✅ | PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). Encrypted Live manual-clear lifecycle, new capture сохраняет старый текст; >72h/restart/owner/clear concurrency tests PASS. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |
| `PR-13` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

### `PWA-OPERABILITY-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PO-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PO-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PO-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PO-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PO-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PO-06` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PO-07` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PO-08` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PO-09` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PO-10` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PO-11` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PO-12` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PO-13` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PO-14` | READY | ✅ | ✅ | ✅ | PR327: durable provider/model snapshot, ElevenLabs/Yandex standard/economic/unknown buckets, legacy payload/cost compatibility; Python и UI regressions PASS. PR327 mergedbc5150e; exact-main CI37502013651 и web/API CD37502621690/worker37504355706 SUCCESS06Oct; runtime identity/health10Oct PASS (A20261010-RUNTIME). |
| `PO-15` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PO-16` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PO-17` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PO-18` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

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
| `GOOGLE-01` | READY | ✅ | ✅ | ✅ | F41 исправлен #318/8d9f45d: output сохранён до initial Drive export, cancellation/recovery; CI 36701312137/36701312154 PASS, current main CI 37155276745/37155276751 PASS. |
| `GOOGLE-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `GOOGLE-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `GOOGLE-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `GOOGLE-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `GOOGLE-06` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

### `STORAGE-LIFECYCLE-02`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `STORAG-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STORAG-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STORAG-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STORAG-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STORAG-05` | READY | ✅ | ✅ | ✅ | PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). Selected originals3/7/30, отсутствие finished S3 writer, fenced leases/all-full-docs retirement, bounded version cleanup/readback и page membership; storage/API/PG/lifecycle checks PASS. External production deletion не выполнялась. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |
| `STORAG-06` | READY | ✅ | ✅ | ✅ | PR329 candidate c23fdc0, CI38141034993 SUCCESS11Oct2026 (test merge c1618886); ещё не main. F75/UXR06: future uploads/preferences3/7/30; legacy reads/expiry сохранены; migration/API/policy/UI PASS. |
| `STORAG-07` | READY | ✅ | ✅ | ✅ | PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). Selected originals3/7/30, отсутствие finished S3 writer, fenced leases/all-full-docs retirement, bounded version cleanup/readback и page membership; storage/API/PG/lifecycle checks PASS. External production deletion не выполнялась. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |
| `STORAG-08` | READY | ✅ | ✅ | ✅ | PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). Selected originals3/7/30, отсутствие finished S3 writer, fenced leases/all-full-docs retirement, bounded version cleanup/readback и page membership; storage/API/PG/lifecycle checks PASS. External production deletion не выполнялась. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |
| `STORAG-09` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STORAG-10` | READY | ✅ | ✅ | ✅ | PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). Selected originals3/7/30, отсутствие finished S3 writer, fenced leases/all-full-docs retirement, bounded version cleanup/readback и page membership; storage/API/PG/lifecycle checks PASS. External production deletion не выполнялась. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |
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
| `STORAG-22` | READY | ✅ | ✅ | ✅ | PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). Selected originals3/7/30, отсутствие finished S3 writer, fenced leases/all-full-docs retirement, bounded version cleanup/readback и page membership; storage/API/PG/lifecycle checks PASS. External production deletion не выполнялась. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |
| `STORAG-21` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

### `STT-PROVIDER-ABSTRACTION-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `STTPRO-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STTPRO-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STTPRO-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STTPRO-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STTPRO-05` | READY | ✅ | ✅ | PENDING | F05 code7151628: truthful Yandex REAL_TIME catalog/selection, existing wire labeling disabled; batch/ElevenLabs unchanged. Local193 focused checks PASS24Oct; required API/CI and delivery PENDING, no paid provider call. |
| `STTPRO-06` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STTPRO-07` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STTPRO-08` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STTPRO-09` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STTPRO-10` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STTPRO-11` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STTPRO-12` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STTPRO-13` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `STTPRO-14` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

### `YANDEX-STT-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `YANDEX-01` | READY | ✅ | ✅ | PENDING | F04 code854c0d7: standard/deferred official-shape REST timing/channel/probability, durable operation and encrypted completed-result reload without resubmit; malformed bounds normalized. Local193 focused checks PASS24Oct; required Linux/API CI and delivery PENDING. No real Yandex call. |
| `YANDEX-02` | READY | ✅ | ✅ | PENDING | F04 code854c0d7: standard/deferred official-shape REST timing/channel/probability, durable operation and encrypted completed-result reload without resubmit; malformed bounds normalized. Local193 focused checks PASS24Oct; required Linux/API CI and delivery PENDING. No real Yandex call. |
| `YANDEX-03` | READY | ✅ | ✅ | ✅ | REAL_TIME relay с отключённым speaker labeling, single-use capability, indexed finals/refinements и bounded reconnect/replay реализованы; tests/test_studio_yandex_transcription.py и exact-main CI37502013651 PASS. F05 сохраняется для неверного capability diarization, не для самой realtime transcription. Реальный Yandex runtime disabled, paid canary не выполнялся. |
| `YANDEX-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `YANDEX-05` | READY | ✅ | ✅ | PENDING | F04 code854c0d7: standard/deferred official-shape REST timing/channel/probability, durable operation and encrypted completed-result reload without resubmit; malformed bounds normalized. Local193 focused checks PASS24Oct; required Linux/API CI and delivery PENDING. No real Yandex call. |

### `PWA-DICTIONARIES-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PWADIC-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

### `PWA-WORKER-ISOLATION-02`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `PWAWOR-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PWAWOR-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `PWAWOR-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

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
| `JOBREL-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `JOBREL-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `JOBREL-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `JOBREL-04` | READY | ✅ | ✅ | ◐ | WK-01 candidate0d7e902 + reviewed diff: real worker entry safe/uncertain/cancel/active local PASS; PostgreSQL skip-locked/concurrency/rollback PASS in CI40028316121. Main8c25efa had no runtime recovery caller; candidate restores criterion. Aggregate CI/merge/CD PENDING; no paid live/fault injection. |
| `JOBREL-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `JOBREL-06` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `JOBREL-07` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `JOBREL-08` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `JOBREL-09` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `JOBREL-10` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `JOBREL-11` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `JOBREL-12` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `JOBREL-13` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `JOBREL-14` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `JOBREL-15` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `JOBREL-16` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `JOBREL-17` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

### `JOB-NOTIFICATIONS-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `JOBNOT-01` | SUPERSEDED | — | — | — | Требование отменено владельцем25Oct2026; task notifications только Telegram JOBNOT-05/06. ID/история сохранены, вне denominator. |
| `JOBNOT-02` | SUPERSEDED | — | — | — | Требование отменено владельцем25Oct2026; task notifications только Telegram JOBNOT-05/06. ID/история сохранены, вне denominator. |
| `JOBNOT-03` | SUPERSEDED | — | — | — | Требование отменено владельцем25Oct2026; task notifications только Telegram JOBNOT-05/06. ID/история сохранены, вне denominator. |
| `JOBNOT-04` | SUPERSEDED | — | — | — | Требование отменено владельцем25Oct2026; task notifications только Telegram JOBNOT-05/06. ID/история сохранены, вне denominator. |
| `JOBNOT-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `JOBNOT-06` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

### `REALTIME-CONTINUITY-02`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `REALTI-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `REALTI-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `REALTI-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `REALTI-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `REALTI-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

### `TRANSCRIPT-EXPORTS-02`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `TRANSC-01` | READY | ✅ | ✅ | ✅ | PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). Live MD/SRT/VTT, order/corrections/session clocks; без timing экспорт ограничен явно. Python/client/component checks PASS; без нового STT. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |
| `TRANSC-02` | READY | ✅ | ✅ | ✅ | PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). Live MD/SRT/VTT, order/corrections/session clocks; без timing экспорт ограничен явно. Python/client/component checks PASS; без нового STT. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |
| `TRANSC-03` | READY | ✅ | ✅ | ✅ | PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). Live MD/SRT/VTT, order/corrections/session clocks; без timing экспорт ограничен явно. Python/client/component checks PASS; без нового STT. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |

### `USAGE-COST-ACCOUNTING-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `USAGEC-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `USAGEC-02` | READY | ✅ | ✅ | ✅ | PR326 code f20ce3e; Linux CI37428475481, Studio/E2E37428475455 PASS06Oct (test-merge6b9e752). Immutable provider-specific nominal public USD snapshot/confirmed duration/rounding; unknown Yandex price не ноль и не ElevenLabs. Accounting tests PASS; runtime Yandex tariff UNSET, invoice debit не заявляется. PR326 merged1937658; current main bc5150eb189b44867101ca45b9da201921a99227, web/API CD37502621690 и worker37504355706 SUCCESS06Oct; A20261010-CODE/CI/RUNTIME. Непроверенные реальные provider/storage/restore условия остаются ограничением Evidence. |
| `USAGEC-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `USAGEC-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `USAGEC-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `USAGEC-06` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

### `OBSERVABILITY-AUDIT-02`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `OBSERV-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-06` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-07` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-08` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-09` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-10` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-11` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-12` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-13` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-14` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-15` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-16` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-17` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-18` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-19` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-20` | READY | ✅ | ✅ | ✅ | F47 code READY #320/a666df1: HTTP/WS query redaction и exact nginx access_log off; main CI 37155276745 PASS, API CD 37155276752 PASS. Protected nginx delivery не завершён: run 37156564109 host verification FAIL; см. F55. |
| `OBSERV-21` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-22` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-23` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-24` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-25` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-26` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-27` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-28` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-29` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-30` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-31` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-32` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-33` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-34` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `OBSERV-35` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

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
