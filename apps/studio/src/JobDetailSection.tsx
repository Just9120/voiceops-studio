import { JobUsageCostSummary } from "./JobUsageCostSummary";
import { formatBytes, formatMediaTimestamp } from "./formatters";
import { longMediaEstimate } from "./longMediaPreflight";
import {
  jobSourceProcessingСтатусLabel,
  safeJobSources,
  transcriptionLanguageModeLabel,
  type JobOutputsResponse,
  type TranscriptionJob,
} from "./jobModel";
import {
  isFullProviderRestore,
  isPartialProviderResume,
  isPartialProviderRestart,
  providerFailureLabel,
  retryUnavailableLabel,
  type JobRetryState,
} from "./jobRecoveryModel";
import { isSafeDisplayUrl, ResourceExternalLink } from "./resourceLinks";

export function JobDetailSection({
  job,
  outputs,
  retry,
  onRetry,
}: {
  job: TranscriptionJob;
  outputs: JobOutputsResponse | null;
  retry: JobRetryState | undefined;
  onRetry: (jobId: string) => void | Promise<void>;
}) {
  const unavailable = retryUnavailableLabel(retry?.data?.reason);
  const partialResume = isPartialProviderResume(retry?.data);
  const fullRestore = isFullProviderRestore(retry?.data);
  const partialRestart = isPartialProviderRestart(retry?.data);
  const ordinaryProviderFailure =
    retry?.data?.available &&
    !partialResume &&
    !fullRestore &&
    !partialRestart &&
    retry.data.provider_failure_code
      ? providerFailureLabel(retry.data.provider_failure_code)
      : null;

  return (
    <section aria-label="Подробности транскрибации">
      <p>Язык: {transcriptionLanguageModeLabel(job.language_mode)}</p>
      <p>
        Разделение спикеров: {job.diarization_enabled ? "Включено" : "Выключено"}
      </p>
      <h5>Расход сервиса распознавания</h5>
      <JobUsageCostSummary usageCost={job.usage_cost} />
      <h5>Папка результата</h5>
      {job.output_folder ? (
        <p>
          {job.output_folder.name || "Папка результата"}{" "}
          {isSafeDisplayUrl(job.output_folder.web_view_url) && (
            <ResourceExternalLink
              href={job.output_folder.web_view_url ?? ""}
              label="Открыть папку результата"
              ariaLabel="Открыть папку результата в новой вкладке"
            />
          )}
        </p>
      ) : (
        <p className="notice">Папка результата не задана.</p>
      )}

      {job.status === "failed" && (
        <div
          className="resource-actions"
          role="region"
          aria-label="Действия после ошибки"
        >
          {job.error_code === "media_duration_confirmation_required" && <p className="notice">{retry?.data?.long_duration_preflight
            ? longMediaEstimate(retry.data.long_duration_preflight)
            : "Для старой задачи измеренная оценка не сохранена. Повтор сначала проверит длительность; для длинной записи потребуется отдельное подтверждение."}</p>}
          {retry?.data?.available ? (
            <>
              {ordinaryProviderFailure && (
                <span className="notice">
                  Причина остановки: {ordinaryProviderFailure}. После исправления причины
                  повтор будет безопасным и не продублирует подтверждённый результат.
                </span>
              )}
              {fullRestore && (
                <span className="notice">
                  Все части уже распознаны и сохранены. Studio соберёт результат
                  и сохранит документ без повторного вызова ElevenLabs.
                </span>
              )}
              {partialResume && (
                <span className="notice">
                  Сохранено частей: {retry.data.resumable_provider_part_count ?? 0} из{" "}
                  {retry.data.provider_total_part_count ?? 0}. Уже готовые части не будут
                  повторно отправлены в ElevenLabs. Причина остановки:{" "}
                  {providerFailureLabel(retry.data.provider_failure_code)}.
                </span>
              )}
              {partialRestart && (
                <span className="notice">
                  Сохранённые части больше недоступны. При продолжении весь файл
                  будет отправлен в ElevenLabs заново и может повторно списать
                  средства. Причина предыдущей остановки:{" "}
                  {providerFailureLabel(retry.data.provider_failure_code)}.
                </span>
              )}
              {partialResume && retry.data.missing_provider_parts?.length ? <section aria-label="Нераспознанные части">
                <strong>Осталось распознать:</strong>
                <ul>{retry.data.missing_provider_parts.map((part) => <li key={`${part.source_id}:${part.part_index}`}>
                  {job.sources?.find((source) => source.id === part.source_id)?.original_filename ?? "Исходник"}: часть {part.part_index + 1} · {formatMediaTimestamp(part.start_seconds)}–{formatMediaTimestamp(part.end_seconds)}
                </li>)}</ul>
              </section> : partialResume && <p className="muted">Точные интервалы старой задачи не сохранены. Продолжение использует подтверждённые готовые части.</p>}
              <button
                type="button"
                onClick={() => void onRetry(job.id)}
                disabled={retry.posting}
                aria-busy={retry.posting}
              >
                {fullRestore
                  ? "Собрать и сохранить результат"
                  : partialResume
                  ? "Продолжить оставшиеся части"
                  : partialRestart
                    ? "Начать транскрибацию заново"
                  : "Повторить безопасную обработку"}
              </button>
            </>
          ) : unavailable ? (
            <span className="notice">{unavailable}</span>
          ) : null}
          {retry?.message && <span>{retry.message}</span>}
          {retry?.error && <span className="error">{retry.error}</span>}
        </div>
      )}
      <h5>Файлы задачи</h5>
      {safeJobSources(job).map((source) => (
        <article className="source-card" key={`${job.id}-${source.id}`}>
          <b>
            {source.position + 1}. {source.original_filename}
          </b>
          <span>
            Статус обработки:{" "}
            {jobSourceProcessingСтатусLabel(job, source, outputs)}
          </span>
          <span>Размер: {formatBytes(source.size_bytes)}</span>
          {isSafeDisplayUrl(source.drive_file_url) && (
            <div className="resource-actions">
              <ResourceExternalLink
                href={source.drive_file_url ?? ""}
                label={source.source_type === "yandex_disk" ? "Открыть файл на Яндекс Диске" : "Открыть файл в Google Drive"}
                ariaLabel={source.source_type === "yandex_disk" ? "Открыть файл на Яндекс Диске в новой вкладке" : "Открыть файл в Google Drive в новой вкладке"}
              />
            </div>
          )}
        </article>
      ))}
      <details className="technical-details job-support-details">
        <summary>Данные для поддержки</summary>
        <p>Идентификатор задачи: {job.id}</p>
      </details>
    </section>
  );
}
