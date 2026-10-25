import { isApprovedTranscriptUrl } from "./outputUrls";
import { formatTime } from "./formatters";
import type { Source } from "./sourceModel";

export type JobСтатус =
  | "queued"
  | "processing"
  | "cancelled"
  | "failed"
  | "completed";
export type JobSourceСтатус = "queued" | "skipped";
export type JobSourceProcessingСтатус = JobСтатус | "skipped";
export type JobSource = Source & {
  position: number;
  job_source_status: JobSourceСтатус;
};
export type JobOutput = {
  source_id?: string;
  source_position: number | null;
  source_name: string | null;
  source_type: string | null;
  output_kind: string | null;
  transcript_standard: string | null;
  web_view_url: string | null;
  link_available: boolean;
  document_character_count: number | null;
  document_created_at: string | null;
  persisted_at: string | null;
};
export type JobOutputsResponse = {
  job_id: string;
  job_status: JobСтатус;
  output_count: number;
  outputs: JobOutput[];
};
export type JobOutputsState = {
  loading: boolean;
  error: string;
  data: JobOutputsResponse | null;
};
export type JobDetailState = {
  loading: boolean;
  error: string;
  job: TranscriptionJob | null;
};
export type JobOutputFolder = { name: string; web_view_url: string | null };
export type TranscriptionLanguageMode = "ru" | "en" | "detect";
const TRANSCRIPTION_LANGUAGE_MODES: ReadonlySet<TranscriptionLanguageMode> =
  new Set(["ru", "en", "detect"]);

export function isTranscriptionLanguageMode(
  value: unknown,
): value is TranscriptionLanguageMode {
  return (
    typeof value === "string" &&
    TRANSCRIPTION_LANGUAGE_MODES.has(value as TranscriptionLanguageMode)
  );
}
export type JobMediaClip = {
  start_seconds: number | null;
  end_seconds: number | null;
};
export type JobBatchReference = {
  id: string;
  position: number;
};
export type JobUsageAccountingStatus =
  | "unavailable"
  | "not_started"
  | "confirmed_partial"
  | "complete"
  | "uncertain";
export type JobUsageRateSnapshot = {
  rate_per_hour: string;
  currency: "USD";
  effective_date: string;
  source: "elevenlabs_public_api_pricing" | "yandex_public_api_pricing";
};
export type JobUsageCost = {
  accounting_status: JobUsageAccountingStatus;
  confirmed_billed_duration_seconds: number | null;
  confirmed_provider_cost: string | null;
  currency: "USD" | null;
  cost_basis: "confirmed_audio_duration_x_rate_snapshot" | null;
  rate_snapshot: JobUsageRateSnapshot | null;
};
export type SpeakerProfileSummary = {
  id: string;
  display_name: string;
  role: string;
};
export type JobSpeakerIdentity = {
  id: string;
  label: string;
  sample_available: boolean;
  profile: SpeakerProfileSummary | null;
};
export type TranscriptionJob = {
  output_provider?: "google_drive" | "yandex_disk";
  id: string;
  project_id: string;
  status: JobСтатус;
  title: string | null;
  source_names?: string[];
  primary_output_url?: string;
  provider: string | null;
  language_mode?: TranscriptionLanguageMode | null;
  diarization_enabled?: boolean;
  media_clip?: JobMediaClip | null;
  batch?: JobBatchReference | null;
  terminal_dismissed_at?: string | null;
  history_attention_required?: boolean;
  history_attention_resolved_at?: string | null;
  history_attention_resolution?: "acknowledged_no_result" | "linked_later_result" | null;
  history_attention_linked_job_id?: string | null;
  source_count: number;
  sources?: JobSource[];
  created_at: string;
  updated_at: string;
  cancelled_at: string | null;
  cancel_requested_at: string | null;
  attempt_count: number;
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
  error_message: string | null;
  output_folder?: JobOutputFolder | null;
  speaker_identities?: JobSpeakerIdentity[];
  usage_cost?: JobUsageCost;
};
export type JobState = {
  loading: boolean;
  loadingMore: boolean;
  error: string;
  loaded: boolean;
  items: TranscriptionJob[];
  nextCursor: string | null;
};

export function jobTitle(job: Pick<TranscriptionJob, "title" | "created_at"> & Partial<Pick<TranscriptionJob, "source_names" | "source_count">>) {
  if (job.title?.trim()) return job.title.trim();
  const firstSource = job.source_names?.[0]?.trim();
  if (firstSource) return firstSource;
  return `Транскрибация от ${formatTime(job.created_at)}`;
}

export function jobMediaClipLabel(job: TranscriptionJob) {
  const clip = job.media_clip;
  if (!clip) return null;
  const format = (seconds: number) => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainder = seconds % 60;
    return hours > 0
      ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`
      : `${minutes}:${String(remainder).padStart(2, "0")}`;
  };
  if ((clip.start_seconds ?? 0) === 0 && clip.end_seconds !== null) {
    return `Начало — ${format(clip.end_seconds)}`;
  }
  if (clip.start_seconds !== null && clip.end_seconds === null) {
    return `${format(clip.start_seconds)} — конец`;
  }
  if (clip.start_seconds !== null && clip.end_seconds !== null) {
    return `${format(clip.start_seconds)} — ${format(clip.end_seconds)}`;
  }
  return null;
}

export function transcriptionLanguageModeLabel(value: string | null | undefined) {
  if (value === "ru") return "Русский";
  if (value === "en") return "Английский";
  if (!value || value === "detect") return "Автоопределение";
  return value;
}

export function safeJobSources(job: TranscriptionJob) {
  return [...(job.sources ?? [])].sort((a, b) => a.position - b.position);
}

export function isApprovedOutputUrl(value: string | null) {
  return isApprovedTranscriptUrl(value);
}

export function outputSourceLabel(output: JobOutput) {
  const position =
    output.source_position == null ? "—" : String(output.source_position + 1);
  return `${position}. ${output.source_name || "Файл без имени"}`;
}

export function jobSourceProcessingСтатус(
  job: TranscriptionJob,
  source: JobSource,
  outputs: JobOutputsResponse | null | undefined,
): JobSourceProcessingСтатус {
  if (source.job_source_status === "skipped") return "skipped";
  if (
    outputs?.job_id === job.id &&
    outputs.outputs.some((output) => output.source_id === source.id)
  ) {
    return "completed";
  }
  if (job.status === "completed") return "completed";
  return job.status;
}

export function jobSourceProcessingСтатусLabel(
  job: TranscriptionJob,
  source: JobSource,
  outputs: JobOutputsResponse | null | undefined,
) {
  const labels: Record<JobSourceProcessingСтатус, string> = {
    queued: "В очереди",
    processing: "Обрабатывается",
    cancelled: "Отменена",
    failed: "Ошибка",
    completed: "Завершена",
    skipped: "Пропущена",
  };
  return labels[jobSourceProcessingСтатус(job, source, outputs)];
}

export function jobСтатусLabel(status: JobСтатус) {
  const labels: Record<JobСтатус, string> = {
    queued: "В очереди",
    processing: "Обрабатывается",
    cancelled: "Отменена",
    failed: "Ошибка",
    completed: "Завершена",
  };
  return labels[status];
}

const JOB_ERROR_LABELS: Record<string, string> = {
  malformed_provider_response:
    "Сервис распознавания вернул неполный ответ. Откройте детали задачи и проверьте доступное безопасное продолжение.",
  provider_authentication_failed:
    "Сервис распознавания отклонил ключ. Проверьте подключение ElevenLabs в настройках.",
  provider_rate_limited:
    "Сервис распознавания временно ограничил запросы. Подождите и повторите доступное безопасное действие.",
  provider_unavailable:
    "Сервис распознавания временно недоступен. Попробуйте позже.",
  source_unavailable:
    "Исходный файл больше недоступен. Выберите файл заново.",
  output_reconciliation_required:
    "Создание результата не подтверждено. Запустите проверку результата в карточке задачи.",
};

function normalizedErrorCode(value: string | null | undefined) {
  const code = value?.trim().toLowerCase() ?? "";
  return /^[a-z0-9][a-z0-9_.-]{0,79}$/.test(code) ? code : null;
}

export function jobErrorPresentation(job: TranscriptionJob) {
  const message = job.error_message?.trim() ?? "";
  const messageCode = normalizedErrorCode(message);
  const supportCode = normalizedErrorCode(job.error_code) ?? messageCode;
  if (supportCode && JOB_ERROR_LABELS[supportCode]) {
    return { message: JOB_ERROR_LABELS[supportCode], supportCode };
  }
  return {
    message:
      "Не удалось завершить обработку. Откройте детали задачи и проверьте доступное безопасное продолжение.",
    supportCode,
  };
}
