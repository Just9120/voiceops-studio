import { formatTime } from "./formatters";
import {
  isApprovedOutputUrl,
  jobErrorPresentation,
  jobMediaClipLabel,
  jobTitle,
  jobСтатусLabel,
  type TranscriptionJob,
} from "./jobModel";
import { ResourceExternalLink } from "./resourceLinks";

export function JobCardSummary({ job }: { job: TranscriptionJob }) {
  const mediaClipLabel = jobMediaClipLabel(job);
  const failure = job.status === "failed" ? jobErrorPresentation(job) : null;
  return (
    <>
      <b>{jobTitle(job)}</b>
      <span>Статус: {jobСтатусLabel(job.status)}</span>
      {job.local_execution && <span>Локально · {job.local_execution.device_name}{job.local_execution.result_accepted ? " · текст принят Studio" : ""}</span>}
      {job.source_count > 1 && <span>Файлов: {job.source_count}</span>}
      {mediaClipLabel && <span>Часть созвона: {mediaClipLabel}</span>}
      {(job.title?.trim() || job.source_names?.[0]?.trim()) && <span>Создана: {formatTime(job.created_at)}</span>}
      {job.output_folder && (
        <span>
          Папка результата: {job.output_folder.name || "Папка Google Drive"}
        </span>
      )}
      {job.output_folder?.web_view_url &&
        job.status !== "completed" &&
        isApprovedOutputUrl(job.output_folder.web_view_url) && (
          <ResourceExternalLink
            href={job.output_folder.web_view_url}
            label="Открыть папку результата"
            ariaLabel="Открыть папку результата в Google Drive в новой вкладке"
          />
        )}
      {job.status === "processing" && job.cancel_requested_at && (
        <span>Отмена запрошена: {formatTime(job.cancel_requested_at)}</span>
      )}
      {failure && <span className="error">{failure.message}</span>}
      {failure?.supportCode && (
        <details className="technical-details job-support-details">
          <summary>Данные для поддержки</summary>
          <span>Код ошибки: {failure.supportCode}</span>
        </details>
      )}
    </>
  );
}
