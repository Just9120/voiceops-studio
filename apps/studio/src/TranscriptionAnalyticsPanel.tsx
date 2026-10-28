import { useEffect, useRef, useState } from "react";
import { api, mutateWithCsrfRetry } from "./apiClient";
import { ConfirmClearDialog } from "./ConfirmClearDialog";
import {
  cancelLatestRequests,
  LATEST_REQUEST_CANCEL_REASON,
  settleLatestRequest,
} from "./latestRequest";
import {
  parseTranscriptionAnalytics,
  type AnalyticsDurationSummary,
  type TranscriptionAnalytics,
} from "./transcriptionAnalyticsModel";

type AnalyticsState = {
  status: "idle" | "loading" | "ready" | "error";
  data: TranscriptionAnalytics | null;
};

type AnalyticsLoader = (
  projectId: string,
  signal?: AbortSignal,
) => Promise<unknown>;

const EMPTY_STATE: AnalyticsState = { status: "idle", data: null };
const ANALYTICS_REQUEST_TIMEOUT_MS = 15_000;

function requestTranscriptionAnalytics(
  projectId: string,
  signal?: AbortSignal,
) {
  return api<unknown>(`/projects/${projectId}/transcription-analytics`, {
    signal,
    ignoredAbortReason: LATEST_REQUEST_CANCEL_REASON,
  });
}

const OUTCOME_LABELS: Array<
  [keyof TranscriptionAnalytics["outcomes"], string]
> = [
  ["queued", "В очереди"],
  ["processing", "В обработке"],
  ["completed", "Готово"],
  ["failed", "Ошибки"],
  ["cancelled", "Отменено"],
];

const DURATION_LABELS: Array<
  [keyof TranscriptionAnalytics["durations"], string]
> = [
  ["queue", "Ожидание в очереди"],
  ["processing", "Обработка задачи"],
  ["provider_processing", "Распознавание речи"],
  ["post_provider_output", "После распознавания до результата"],
];

function formatDuration(value: number | null) {
  if (value === null) return "Нет данных";
  const seconds = Math.round(value);
  if (seconds < 60) return `${seconds} с`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (minutes < 60)
    return remainingSeconds > 0
      ? `${minutes} мин ${remainingSeconds} с`
      : `${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes > 0
    ? `${hours} ч ${remainingMinutes} мин`
    : `${hours} ч`;
}

function formatSuccessPercentage(value: number | null) {
  return value === null
    ? "Нет завершённых исходов"
    : `${value.toLocaleString("ru-RU", {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      })}%`;
}

function formatProviderCost(value: string) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "Нет данных";
  if (numeric > 0 && numeric < 0.01) return "< 0,01 USD";
  return `${numeric.toLocaleString("ru-RU", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} USD`;
}

function DurationCard({
  label,
  summary,
}: {
  label: string;
  summary: AnalyticsDurationSummary;
}) {
  return (
    <article className="analytics-metric">
      <span className="muted">{label}</span>
      <strong>Среднее: {formatDuration(summary.average_seconds)}</strong>
      {summary.sample_count > 0 ? (
        <small>
          Медиана {formatDuration(summary.p50_seconds)} · p95{" "}
          {formatDuration(summary.p95_seconds)} · замеров {summary.sample_count}
        </small>
      ) : (
        <small>Появится после завершённых этапов обработки.</small>
      )}
    </article>
  );
}

export function TranscriptionAnalyticsPanel({
  projectId,
  csrf = "",
  onCsrf = () => undefined,
  loadAnalytics = requestTranscriptionAnalytics,
}: {
  projectId: string;
  csrf?: string;
  onCsrf?: (csrf: string) => void;
  loadAnalytics?: AnalyticsLoader;
}) {
  const [state, setState] = useState<AnalyticsState>(EMPTY_STATE);
  const requestEpochsRef = useRef(new Map<string, number>());
  const requestControllersRef = useRef(new Map<string, AbortController>());
  const [clearOpen, setClearOpen] = useState(false);
  const [clearPending, setClearPending] = useState(false);
  const [clearMessage, setClearMessage] = useState("");
  const clearPendingRef = useRef(false);

  useEffect(() => {
    cancelLatestRequests(
      requestEpochsRef.current,
      requestControllersRef.current,
    );
    setState(EMPTY_STATE);
    return () => {
      cancelLatestRequests(
        requestEpochsRef.current,
        requestControllersRef.current,
      );
    };
  }, [projectId]);

  async function load() {
    setState((current) => ({
      status: "loading",
      data: current.data,
    }));
    await settleLatestRequest(
      requestEpochsRef.current,
      "transcription-analytics",
      async (signal) => {
        const parsed = parseTranscriptionAnalytics(
          await loadAnalytics(projectId, signal),
        );
        if (!parsed) {
          throw new Error("invalid_transcription_analytics_response");
        }
        return parsed;
      },
      (parsed) => setState({ status: "ready", data: parsed }),
      () =>
        setState((current) => ({ status: "error", data: current.data })),
      {
        controllers: requestControllersRef.current,
        timeoutMs: ANALYTICS_REQUEST_TIMEOUT_MS,
      },
    );
  }

  async function clearAnalytics() {
    if (clearPendingRef.current) return;
    clearPendingRef.current = true;
    setClearPending(true);
    setClearMessage("");
    try {
      const result = await mutateWithCsrfRetry<unknown>(
        `/projects/${projectId}/transcription-analytics/clear`,
        csrf,
        onCsrf,
        {
          method: "POST",
          body: JSON.stringify({ confirm_clear: true }),
        },
      );
      if (!isClearResponse(result)) throw new Error("invalid_clear_response");
      setClearOpen(false);
      setState(EMPTY_STATE);
      setClearMessage("Аналитика очищена. Новые метрики считаются с этого момента.");
      await load();
    } catch {
      setClearMessage("Не удалось очистить аналитику. Повторите попытку.");
    } finally {
      clearPendingRef.current = false;
      setClearPending(false);
    }
  }

  const analytics = state.data;
  return (
    <details
      className="transcription-analytics"
      onToggle={(event) => {
        if (event.currentTarget.open && state.status === "idle") void load();
      }}
    >
      <summary>Аналитика транскрибаций</summary>
      <div className="analytics-content">
        <div className="split analytics-heading">
          <p className="muted">
            {analytics?.scope === "project_since_reset"
              ? "Агрегаты с момента последней очистки"
              : "Агрегаты за всё время проекта"}{" "}
            без текстов транскриптов и приватных идентификаторов.
          </p>
          <button
            className="secondary"
            disabled={state.status === "loading"}
            onClick={() => void load()}
            type="button"
          >
            {state.status === "loading" ? "Обновляем…" : "Обновить"}
          </button>
          <button
            className="danger"
            disabled={clearPending}
            onClick={() => setClearOpen(true)}
            type="button"
          >
            Очистить аналитику
          </button>
        </div>
        {clearMessage && <p role="status" className="notice">{clearMessage}</p>}
        {state.status === "loading" && !analytics && (
          <p role="status">Загрузка аналитики…</p>
        )}
        {state.status === "error" && !analytics && (
          <p className="notice">
            Аналитика временно недоступна. Попробуйте обновить позднее.
          </p>
        )}
        {analytics && (
          <>
            <div className="analytics-total-grid">
              <article>
                <span>Задачи</span>
                <strong>{analytics.totals.jobs}</strong>
              </article>
              <article>
                <span>Источники</span>
                <strong>{analytics.totals.sources}</strong>
              </article>
              <article>
                <span>Результаты</span>
                <strong>{analytics.totals.outputs}</strong>
              </article>
            </div>

            <section aria-label="Исходы транскрибаций">
              <h3>Исходы</h3>
              <article
                className="analytics-success"
                aria-label="Успешность транскрибаций"
              >
                <strong>
                  Успешность: {formatSuccessPercentage(analytics.success.percentage)}
                </strong>
                {analytics.success.terminal_jobs > 0 && (
                  <small>
                    Успешно {analytics.success.successful_jobs} из{" "}
                    {analytics.success.terminal_jobs} завершённых исходов.
                  </small>
                )}
              </article>
              <div className="analytics-outcomes">
                {OUTCOME_LABELS.map(([key, label]) => (
                  <span key={key}>
                    {label} <b>{analytics.outcomes[key]}</b>
                  </span>
                ))}
              </div>
            </section>

            <section aria-label="Выбранные настройки транскрибаций">
              <h3>Настройки</h3>
              <div className="analytics-config-grid">
                <article>
                  <b>Провайдер и модель</b>
                  <span>
                    ElevenLabs · scribe_v2{" "}
                    {analytics.configuration.provider_model.elevenlabs_scribe_v2}
                  </span>
                  {(analytics.configuration.provider_model.yandex_general ?? 0) > 0 && <span>Yandex SpeechKit · general {analytics.configuration.provider_model.yandex_general}</span>}
                  {(analytics.configuration.provider_model.yandex_deferred_general ?? 0) > 0 && <span>Yandex SpeechKit · deferred-general {analytics.configuration.provider_model.yandex_deferred_general}</span>}
                  {([['mistral_voxtral_small_transcribe_3', 'Mistral · Voxtral Small Transcribe 3'], ['gemini_35_transcribe', 'Google · Gemini 3.5 Transcribe'], ['tbank_default', 'Т-Банк · VoiceKit']] as const).map(([key, label]) => (analytics.configuration.provider_model[key] ?? 0) > 0 && <span key={key}>{label} {analytics.configuration.provider_model[key]}</span>)}
                  {analytics.configuration.provider_model.unknown > 0 && (
                    <small>
                      Не определено:{" "}
                      {analytics.configuration.provider_model.unknown}
                    </small>
                  )}
                </article>
                <article>
                  <b>Язык</b>
                  <span>
                    Русский {analytics.configuration.language_mode.ru} ·
                    английский {analytics.configuration.language_mode.en} ·
                    автоопределение{" "}
                    {analytics.configuration.language_mode.detect}
                  </span>
                  {analytics.configuration.language_mode.other > 0 && (
                    <small>
                      Другой режим:{" "}
                      {analytics.configuration.language_mode.other}
                    </small>
                  )}
                </article>
                <article>
                  <b>Спикеры</b>
                  <span>
                    Разделение включено{" "}
                    {analytics.configuration.diarization.enabled} · выключено{" "}
                    {analytics.configuration.diarization.disabled}
                  </span>
                </article>
              </div>
            </section>

            <section aria-label="Длительности этапов транскрибаций">
              <h3>Длительность этапов</h3>
              <div className="analytics-duration-grid">
                {DURATION_LABELS.map(([key, label]) => (
                  <DurationCard
                    key={key}
                    label={label}
                    summary={analytics.durations[key]}
                  />
                ))}
              </div>
              <p className="muted analytics-footnote">
                Последний интервал объединяет слияние частей и создание
                результата в Google Docs. Незавершённые этапы в статистику не
                входят.
              </p>
              <details className="analytics-glossary">
                <summary>Как читать метрики длительности</summary>
                <dl>
                  <div>
                    <dt>Среднее</dt>
                    <dd>
                      Сумма длительностей, разделённая на число замеров. Долгие
                      задачи могут заметно увеличить значение.
                    </dd>
                  </div>
                  <div>
                    <dt>Медиана</dt>
                    <dd>
                      Половина замеров короче этого значения, половина —
                      длиннее.
                    </dd>
                  </div>
                  <div>
                    <dt>p95</dt>
                    <dd>
                      95% замеров завершились не дольше этого времени. Это не
                      максимальная длительность.
                    </dd>
                  </div>
                  <div>
                    <dt>Замеры</dt>
                    <dd>
                      Количество завершённых интервалов конкретного этапа,
                      вошедших в расчёт.
                    </dd>
                  </div>
                </dl>
              </details>
            </section>

            <section aria-label="Расход ElevenLabs">
              <h3>Расход ElevenLabs</h3>
              <div className="analytics-total-grid">
                <article>
                  <span>Подтверждённо отправлено</span>
                  <strong>
                    {formatDuration(
                      analytics.usage_cost.confirmed_billed_duration_seconds,
                    )}
                  </strong>
                </article>
                <article>
                  <span>Стоимость по тарифу</span>
                  <strong>
                    {formatProviderCost(
                      analytics.usage_cost.confirmed_provider_cost,
                    )}
                  </strong>
                  <details><summary>Точное значение стоимости</summary>{analytics.usage_cost.confirmed_provider_cost} USD</details>
                </article>
                <article>
                  <span>Полный учёт</span>
                  <strong>{analytics.usage_cost.complete_jobs}</strong>
                </article>
              </div>
              <p className="muted analytics-footnote">
                Сумма рассчитана по подтверждённой длительности, реально
                отправленной в ElevenLabs, и сохранённому тарифу. Это расчётная
                стоимость, а не счёт после подписки или квоты; фактические расходы
                сверх лимита и счета показаны в Настройки → Подключения.
              </p>
              {(analytics.usage_cost.uncertain_jobs > 0 ||
                analytics.usage_cost.unavailable_jobs > 0) && (
                <p className="notice" role="status">
                  Неподтверждённый исход: {analytics.usage_cost.uncertain_jobs} ·
                  исторические задачи без учёта: {analytics.usage_cost.unavailable_jobs}.
                  Неподтверждённая часть не добавлена к сумме; уже подтверждённые
                  части таких задач учтены.
                </p>
              )}
            </section>
          </>
        )}
        {state.status === "error" && analytics && (
          <p className="notice">
            Не удалось обновить данные; показана последняя подтверждённая
            версия.
          </p>
        )}
      </div>
      {clearOpen && (
        <ConfirmClearDialog
          title="Очистить аналитику?"
          description="Существующие транскрипции, результаты и документы не удаляются. Сводка начнёт считаться заново с момента очистки."
          pending={clearPending}
          onConfirm={() => void clearAnalytics()}
          onCancel={() => setClearOpen(false)}
        />
      )}
    </details>
  );
}

function isClearResponse(value: unknown): value is {
  ok: true;
  reset_at: string;
  hidden_job_count: number;
} {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (
    candidate.ok === true &&
    typeof candidate.reset_at === "string" &&
    Number.isFinite(Date.parse(candidate.reset_at)) &&
    typeof candidate.hidden_job_count === "number" &&
    Number.isInteger(candidate.hidden_job_count) &&
    candidate.hidden_job_count >= 0
  );
}
