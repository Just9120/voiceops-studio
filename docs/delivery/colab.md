# Реестр AC: Colab

Часть [delivery dashboard](../delivery-plan.md). Полный аудит 2026-10-10 на проверенном `origin/main` `bc5150eb189b44867101ca45b9da201921a99227`; формулировки — [spec](../spec/colab.md), источник — [trace](../spec/source-trace.md). Все действующие ID повторно оценены по реализации и подходящим проверкам A20261010-CODE/CI; runtime scope/ограничения — A20261010-RUNTIME в плане. CODE/TEST/CI — типы Evidence, а не три процента; ◐ ограничивает проверенные условия. ALIAS/SUPERSEDED исключены. READY не требует ручной приёмки и не доказывает commercial rollout.

### `COLAB-BATCH-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `CB-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CB-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CB-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CB-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CB-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CB-06` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CB-07` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CB-08` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CB-09` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CB-10` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CB-11` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CB-12` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CB-13` | READY | PASS | PASS | PASS | PR351/main `067065b`, exact CI42419498462: atomic guard, concurrent dispatch, lost acknowledgment and explicit recovery. Published launcher pin/hash PASS. Shared guard setup required before a paid run. |
| `CB-14` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CB-15` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CB-16` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CB-17` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CB-18` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CB-19` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CB-20` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CB-21` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CB-22` | READY | PASS | PASS | PASS | PR351/main `067065b`, exact CI confirms known date retained and unknown omitted. Published launcher pin/hash PASS. |
| `CB-23` | READY | PASS | PASS | PASS | PR351/main `067065b`, exact CI verifies folder preview, stale revision and atomic rejection. Published launcher pin/hash PASS. |
| `CB-24` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |

### `COLAB-REALTIME-01`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `CR-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CR-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CR-03` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CR-04` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CR-05` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `CR-06` | IN_PROGRESS | PASS | PARTIAL | PASS | 08Nov, Windows Chrome 157 и runtime `067065b`: 6/6 loopback cycles с synthetic MediaStream и committed response. Denial и Stop при pending capture проверены с подменой media APIs. Матрица с реальными разрешениями/источниками, Colab proxy и ElevenLabs остаётся открыта. |

### `COLAB-LIFECYCLE-02`

| AC | Состояние | CODE | TEST | CI | Остаток / Evidence |
| --- | --- | --- | --- | --- | --- |
| `COLABL-01` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
| `COLABL-02` | READY | ✅ | ◐ | ✅ | Код реализован; subsystem checks есть, полный сценарий LIVE отдельно не проверен |
