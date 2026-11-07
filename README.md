# VoiceOps Studio

VoiceOps Studio — PWA для подготовки аудио, транскрибации и работы с результатами. Product scope включает изолированные personal и commercial контуры; отдельный Colab поддерживается в пределах существующих возможностей. Фактические исполняемые поверхности:

1. **Google Colab** — batch-транскрибации в Google Docs и realtime-транскрибация в окне браузера.
2. **VoiceOps Studio PWA** — web-приложение с отдельной подготовкой WAV/FLAC до транскрибации, batch и realtime, авторизацией, Google Drive, Cloudflare R2, worker processing, history, analytics и diagnostics.

Personal Studio PWA работает и развивается. Яндекс Диск входит в согласованные требования; его текущие gaps зафиксированы в delivery-plan. Полные готовые обычные транскрипции не хранятся отдельной постоянной копией в Studio. Live сохраняет текст до ручной очистки, а незавершённая обычная транскрибация — до полного документа, отмены или явного закрытия ошибки; это recovery state. Готовое аудио скачивается или экспортируется через временную сборку из доступных исходников. Colab не получает новые PWA/commercial возможности автоматически.

Единый бренд проекта и repository — **VoiceOps Studio**, canonical repository `Just9120/voiceops-studio`. ElevenLabs — provider, а не имя приложения. Файлы `elevenlabs_api.py` / `elevenlabs_realtime.py` сохраняют совместимые entrypoint names. Действующие database/volume/bucket names и deployment paths не меняются ради брендинга.

Публичная информация Studio доступна без входа и API-запросов: [описание приложения](apps/studio/public/about.html), [обработка данных](apps/studio/public/privacy.html), [правила personal использования](apps/studio/public/terms.html). В развернутом Studio это `/about.html`, `/privacy.html`, `/terms.html`; страница входа и основная навигация содержат ссылки на них. Google Branding использует существующий canonical host и эти страницы после подтверждённой поставки.

README не дублирует быстро устаревающие проценты и revision IDs. Полный scope, atomic AC, источники и метод расчёта находятся в [docs/project-spec.md](docs/project-spec.md). Все текущие статусы AC, Evidence, numerator/denominator, текущая и предыдущая оценки, findings, варианты Goal и checkpoint находятся только в [docs/delivery-plan.md](docs/delivery-plan.md).

Commercial production включён в durable product scope; его фактическое состояние и приоритеты отражены в delivery dashboard. Существующий personal code не считается commercial Evidence.

## Stack и карта кода

- Colab: `elevenlabs_api.py`, `elevenlabs_realtime.py`, thin launchers в `notebooks/`; generated protobuf сохраняет собственные entrypoints/upstream.
- Studio: React 18 / TypeScript 5.6 / Vite 6 в `apps/studio`; Python/FastAPI, SQLAlchemy/Alembic и worker в `apps/studio-api`; PostgreSQL, Redis, FFmpeg; deployment files в `deploy/studio`, операции в `scripts`.
- Пакеты: npm с `apps/studio/package-lock.json`; engines из `apps/studio/package.json`. Python CI 3.11, `requirements-dev.txt` + `constraints-dev.txt`, API requirements/constraints в `apps/studio-api`. Constraints фиксируют версии и не являются hash-integrity lock. Окружение и setup — [validation](docs/runbooks/validation.md).

## Быстрый старт и validation

Для платной batch-транскрибации Colab один раз создай отдельный пустой Google Doc за пределами папок исходников и результатов. Добавь его ID или ссылку в Colab Secret `COLAB_STT_RESERVATION_DOC_ID` и предоставь доступ к этому секрету во всех batch-ноутбуках, которые используют один манифест. Для всех таких сессий используй один и тот же документ. Журнал хранит технические ключи и состояния резервов. Не редактируй его вручную.

Если запуск прервался и исход распознавания неизвестен, при попытке повтора Colab покажет код резерва. В разделе «Восстановление после неизвестного результата» укажи этот код и ссылку на готовый Google Doc, если он есть. Если документа нет, сначала останови другие запуски этой записи и проверь папку результата, затем закрой резерв вручную. Закрытие не запускает распознавание. Следующий запуск при отсутствии документа может снова списать оплату.

```bash
# Lightweight repository checks
python scripts/ci_checks.py

# Python tests (PostgreSQL/Redis + bash нужны для полного CI-профиля)
pytest -q

# Ограниченный локальный профиль
pytest -q --portable

# VoiceOps Studio PWA
cd apps/studio
npm ci
npm run lint
npm run test -- --run
npm run build

# Локальный интерфейс Studio
npm run dev

# Проверка whitespace/diff
git diff --check
```

На Windows portable suite всё ещё включает shell-dependent проверки; ограничения и фактические результаты последнего аудита указаны в [delivery-plan](docs/delivery-plan.md) и [validation runbook](docs/runbooks/validation.md).

Для локального API нужны отдельные тестовые PostgreSQL/Redis, migrations и synthetic configuration. Подготовка окружения и запуск `uvicorn studio_api.main:app` описаны в [validation runbook](docs/runbooks/validation.md).

Colab batch запускается вручную через `notebooks/elevenlabs_api_colab.ipynb`. Оба thin launchers закрепляют проверенный полный commit SHA и проверяют SHA-256 скачанных runtime файлов до install/exec. Обновление launcher требует review новой revision и одновременной смены `GITHUB_REF` и expected hashes; скачивание с подвижной ветки не используется. Он поддерживает Drive/local file intake, bounded local-folder intake, `ru`/`en`/auto language modes, speaker diarization, Google Docs output и duplicate-protection manifest; destructive manifest clear вынесен в dry-run-first flow с backup и точным подтверждением. Realtime Colab проверяется по отдельному runbook. Обычные проверки и поставка выполняются по [AGENTS](AGENTS.md), [validation](docs/runbooks/validation.md) и [Studio operations](docs/runbooks/studio-platform-ops.md).

## Canonical и operational документы

| Документ | Назначение |
|---|---|
| [Источники требований](docs/project-spec.md#1-назначение-источники-и-область) | Согласованные источники, версии и трассировка; сами требования не разрешают implementation. |
| [AGENTS.md](AGENTS.md) | Goal-driven repository router, execution kernel, authority и scope. |
| [docs/project-spec.md](docs/project-spec.md) | Canonical product contract и индекс эпиков; формулировки AC — в docs/spec/*.md. |
| [docs/delivery-plan.md](docs/delivery-plan.md) | Живой dashboard, readiness, blockers и checkpoint; полные реестры AC — в docs/delivery/*.md. |
| [docs/delivery-plan-archive.md](docs/delivery-plan-archive.md) | Архив завершённой delivery history. |
| [docs/ci-cd-rules.md](docs/ci-cd-rules.md) | Настройка и исправление pipeline; не обязательное чтение для routine checks/merge/deploy. |
| [docs/architecture.md](docs/architecture.md) | Logical/runtime architecture, data flow и state ownership. |
| [docs/studio-processing-contract.md](docs/studio-processing-contract.md) | Детальные Studio processing invariants. |
| [SECURITY.md](SECURITY.md) | Security reporting, safe research boundaries и authority routing. |
| [docs/runbooks/validation.md](docs/runbooks/validation.md) | Repository и component validation commands. |
| [docs/runbooks/studio-platform-ops.md](docs/runbooks/studio-platform-ops.md) | Studio rollout и production operations. |
| [docs/runbooks/realtime-colab.md](docs/runbooks/realtime-colab.md) | Realtime Colab prototype, диагностика и ограничения runtime-проверок. |
| [docs/runbooks/local-worker.md](docs/runbooks/local-worker.md) | Personal Nemotron на компьютере владельца: pairing, запуск, ограничения и recovery. |

## Historical и supporting evidence

Dated audits фиксируют состояние на указанный revision/date. Они не являются current source of truth, readiness input или implementation authorization.

| Документ | Назначение |
|---|---|
| [docs/audits/repository-audit-2026-08-27.md](docs/audits/repository-audit-2026-08-27.md) | Evidence-based audit на pre-PR `#245` baseline; findings и gaps. |
| [docs/audits/repository-audit-2026-07-26.md](docs/audits/repository-audit-2026-07-26.md) | Исторический audit supporting evidence. |
| [docs/audits/repository-audit-2026-07-21.md](docs/audits/repository-audit-2026-07-21.md) | Более ранний historical audit, перенесённый из operational runbooks. |

Опциональные `docs/utility/context-bundle-builder.md` и `docs/ai-delivery-infrastructure-plan.md` в текущем repository отсутствуют; их содержание не предполагается.

## Границы статусов

- Source presence не равна production LIVE.
- CI success не равен deployment success.
- Готовность проекта — READY / все актуальные продуктовые и технические AC проверенного origin/main; READY подтверждают код и подходящие автоматические проверки. Результат поставки восстанавливается по первичным records.
- Постоянный режим — Ad-hoc: пользователь использует проект и сообщает о багах, агент выполняет доступные проверки и исправления в разрешённой задаче. Плановой программы ручных тестов и отчётов пользователя по функциям нет.
- Текущая готовность не копируется из archive — она пересчитывается по соответствию кода актуальным требованиям. Известный дефект возвращает затронутый AC в работу.
