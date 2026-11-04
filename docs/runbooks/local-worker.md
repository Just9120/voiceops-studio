# Локальная Nemotron: personal обработчик

Требования — [NEM-01..04](../spec/extensions.md#эпик-personal-local-nemotron-01--распознавание-на-компьютере-владельца), состояние реализации/поставки — [delivery dashboard](../delivery-plan.md). Этот runbook не подтверждает завершённую поставку или доступность модели на конкретном компьютере.

## Устройство и границы

Владелец явно назначает задачу своему компьютеру. Companion делает исходящие HTTPS-запросы к Studio; API отдаёт только исходник назначенной owner/device/job задачи и принимает полный результат. Cloud credentials, database access и storage URLs компьютеру не передаются. Native API слушает только `127.0.0.1` с отдельным случайным ключом; CORS и playground выключены. Открывать входящие порты ПК не требуется.

Поддерживаемая комбинация: Windows, Python3.11+, установленный FFmpeg/FFprobe, NeMo-Speech.cpp `0.2.0+nightly.66d50d9` CPU, Nemotron3.5 Transcribe30B-A4B IQ4_NL и F16 encoder. Native source revision `66d50d91b75a406becd95fbaf39d2c9c13e95d7c`, weights snapshot `dbd06c5cad7a2f33c8e06be2fb3ef814dbd9aa59`. Точные sizes/SHA-256 — в [native adapter](../../scripts/local_worker/native.py). Обработчик не устанавливает и не скачивает модели автоматически.

Это распознавание полной выбранной записи, до60минут; можно выбрать допустимый фрагмент более длинного исходника. Язык задаётся явно `ru`/`en`: SALM не определяет его автоматически. Доступны word timestamps и диаризация; отсутствие надёжного alignment не выдаётся за готовые таймкоды. Live и словари этого локального adapter не поддерживаются. Текст не переводится и не очищается от fillers автоматически.

Модель занимает значительную RAM; её фактическое потребление и возможность запуска проверяются на целевом компьютере. Произвольного порога обязательной свободной RAM в обработчике нет. Загрузка не объявляется READY заранее; реальный отказ native process переводится в error state. На HDD первая проверка файлов и холодная загрузка могут занимать несколько минут. Точное время зависит от свободной памяти и диска.

## Первичная привязка

Рабочий каталог команд — корень этого repository, актуальная версия после поставки. Требуется обычный Python с библиотекой стандартного состава; API/DB/provider packages для companion не устанавливаются.

1. В Studio создайте привязку компьютера в подключениях. Действие требует штатного recent authentication. Ключ показывается один раз; не отправляйте его в чат, issue, command line или файл открытым текстом.
2. На этом компьютере выполните:

   ```powershell
   python scripts/voiceops_local_worker.py pair
   ```

3. Укажите пути к уже установленным runtime, decoder и encoder. FFmpeg/FFprobe обнаруживаются в `PATH`; при отсутствии запрашиваются пути. Можно передать не секретные paths флагами `--runtime`, `--decoder`, `--encoder`, `--ffmpeg`, `--ffprobe`.
4. После проверки файлов вставьте ключ в скрытый prompt. Профиль сохраняется в `LocalAppData/VoiceOpsStudio/local-worker/profile.json`, целиком защищён current-user Windows DPAPI: origin, key, paths и proof проверенных файлов связаны вместе.
5. Запустите:

   ```powershell
   python scripts/voiceops_local_worker.py run
   ```

При запуске загружается локальная модель; после readiness обработчик ожидает выбранные в Studio задачи. Остановка — `Ctrl+C`. Установка автозапуска не выполняется. `--profile` перед подкомандой позволяет явно выбрать отдельный profile path. Для замены существующей привязки нужен `pair --replace`; чужой или неизвестный файл не перезаписывается.

Большие weights проверяются полностью при pairing. Последующие запуски используют DPAPI-sealed proof только при неизменных file ID/size/timestamps; маленький runtime executable хешируется каждый раз. Замена/изменение файла требует повторной проверки. Это integrity guard установленного комплекта, не защита от malware с правами того же пользователя/администратора.

## Выполнение и recovery

Claim возвращает одну назначенную задачу и generation. Source SHA-256 проверяется до FFmpeg; фактическая длительность возвращается API для фиксации исходной шкалы и разрешённого интервала до inference. Подготовка WAV16kHz mono выполняется только во временном каталоге PC. Первичный исходник не изменяется.

Native Chat API должен вернуть `finish_reason=stop`, согласованный полный текст и ожидаемую модель/длительность/язык. CLI compact JSON не является достаточным доказательством завершения decoder: в нём нет finish reason. Duration-derived output budget устанавливает pinned recognizer; короткий512-token budget старого feasibility probe не применяется.

Результат передаётся bounded gzip, сохраняется общим encrypted checkpoint и передаёт задачу VPS для export-only продолжения. Обрыв ответа после commit разрешается повтором **того же полного тела**, а не новым inference. Потеря checkpoint не разрешает cloud fallback. История, вывод документов, source lifecycle и accounting подчиняются общим [processing contract](../studio-processing-contract.md) и [operations](studio-platform-ops.md).

Heartbeat продлевает lease, но сам по себе не увеличивает измеряемый progress. Для native inference процент неизвестен. Отмена, revoked key, истечение authority или длительная потеря соединения завершают только созданный companion native process; в Windows используется kill-on-close Job Object. Offline lease становится явной recoverable ошибкой. После аварийного перезапуска обработчик не повторяет старую активную inference молча: задача отмечается как прерванная, владелец выбирает повтор в Studio.

После success/error/cancel/штатной остановки owned temporary bytes/logs удаляются. Следующий запуск очищает только распознанные временные run trees с неживым owner PID; активные, неизвестные, изменённые или содержащие дополнительные файлы каталоги сохраняются. Model files и профиль не входят в очистку. Native raw diagnostics/paths/transcript bodies не печатаются в console или API errors.

## Безопасная проверка

Из корня, synthetic configuration по [validation](validation.md):

```powershell
python -m pytest -q --portable tests/test_voiceops_local_worker.py tests/test_studio_local_execution_devices.py tests/test_studio_nemotron_local_result.py
```

CI/Linux проверяет portable protocol/process/cleanup и серверную часть; real DPAPI case применим к Windows. Настоящий native canary использует только короткий synthetic WAV, отдельный owned scratch, loopback native server и подтверждённую очистку/child exit. Проверка реальных пользовательских записей и любые платные STT calls этим runbook не разрешаются.
