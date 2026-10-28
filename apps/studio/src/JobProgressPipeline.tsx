import type {
  JobProgressStage,
  JobProgressStageKey,
  JobProgressState,
} from "./jobProgressModel";
import { confirmedProgressPercent } from "./jobProgressModel";
import { WorkProgressDetail } from "./WorkProgress";

const STAGE_LABELS: Record<JobProgressStageKey, string> = {
  preparation: "Подготовка источника",
  audio_extraction: "Извлечение аудио",
  splitting: "Разбиение на части (при необходимости)",
  provider_processing: "Распознавание речи",
  part_merge: "Слияние частей (при необходимости)",
  google_docs_output: "Сохранение документа",
};

const ACTIVE_STAGE_LABELS: Record<JobProgressStageKey, string> = {
  preparation: "Подготавливаем файл",
  audio_extraction: "Извлекаем аудио из видео",
  splitting: "Проверяем размер и делим длинную запись",
  provider_processing: "Транскрибируем запись",
  part_merge: "Объединяем части транскрипта",
  google_docs_output: "Сохраняем документ",
};

function statusLabel(stage: JobProgressStage) {
  if (stage.status === "pending") return "Ожидает";
  if (stage.status === "active") return "Выполняется";
  if (stage.status === "failed") return "Ошибка";
  if (stage.status === "cancelled") return "Отменено";
  if (stage.status === "not_applicable") return "Не требуется";
  return stage.applicability === "conditional" ? "Проверено" : "Готово";
}

export function JobProgressPipeline({
  jobId,
  state,
}: {
  jobId: string;
  state: JobProgressState | undefined;
}) {
  if (!state) return null;
  if (state.loading && !state.data)
    return <p role="status">Загрузка прогресса…</p>;
  if (!state.data)
    return (
      <p className="notice">
        Прогресс временно недоступен. Обновите страницу позднее.
      </p>
    );

  const progress = state.data;
  const percent = confirmedProgressPercent(progress);
  const activeSource = progress.sources.find(
    (source) => source.position === progress.active_source_position,
  );
  const isActive =
    progress.job_status === "queued" || progress.job_status === "processing";
  let currentAction =
    progress.job_status === "queued"
      ? "Ждёт начала обработки"
      : progress.job_status === "completed"
        ? "Транскрибация завершена"
        : progress.job_status === "failed"
          ? "Не удалось завершить транскрибацию"
          : progress.job_status === "cancelled"
            ? "Транскрибация отменена"
            : "Обрабатываем запись";
  if (isActive && progress.current_stage) {
    currentAction = ACTIVE_STAGE_LABELS[progress.current_stage];
  }
  if (
    isActive &&
    progress.current_stage === "provider_processing" &&
    activeSource?.provider_parts
  ) {
    const { completed, total } = activeSource.provider_parts;
    currentAction =
      completed < total
        ? `Транскрибируем часть ${completed + 1} из ${total}`
        : "Завершаем транскрибацию частей";
  }
  return (
    <section
      className="job-progress"
      aria-label={`Прогресс задачи ${jobId}`}
      aria-live="polite"
      aria-busy={isActive}
    >
      <div className="job-progress-header">
        <strong>{currentAction}</strong>
        <strong>Подтверждено {percent}%</strong>
      </div>
      {isActive && <WorkProgressDetail value={progress.work} />}
      <div
        className={`job-progress-meter${isActive ? " is-active" : ""}`}
        role="progressbar"
        aria-label="Общий прогресс транскрибации"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-valuetext={`${percent}% подтверждено. ${currentAction}`}
      >
        <span
          className="job-progress-meter-fill"
          style={{ width: `${percent}%` }}
        />
      </div>
      <div className="job-progress-summary">
        <span>
          Готово файлов: {progress.completed_source_count} из{" "}
          {progress.total_source_count}
        </span>
        {activeSource && <span>Сейчас: {activeSource.name}</span>}
      </div>
      <p className="muted job-progress-explanation">
        Статус обновляется автоматически. Анимация показывает, что обработка
        продолжается; процент меняется только по подтверждённым этапам.
      </p>
      <details className="job-progress-details">
        <summary>Подробности по этапам</summary>
        {progress.sources.map((source) => (
          <div className="job-progress-source" key={source.position}>
            <b>
              {source.position + 1}. {source.name}
            </b>
            {source.provider_parts && (
              <span className="muted">
                Части ElevenLabs: {source.provider_parts.completed} из{" "}
                {source.provider_parts.total}
              </span>
            )}
            <ol className="job-progress-steps">
              {source.stages.map((stage) => (
                <li
                  className={`job-progress-step progress-${stage.status}`}
                  key={stage.key}
                >
                  <span aria-hidden="true" className="job-progress-marker" />
                  <span>{STAGE_LABELS[stage.key]}</span>
                  <small>{statusLabel(stage)}</small>
                </li>
              ))}
            </ol>
          </div>
        ))}
      </details>
      {state.error && (
        <p className="notice">
          Не удалось обновить прогресс; показан последний подтверждённый статус.
        </p>
      )}
    </section>
  );
}
