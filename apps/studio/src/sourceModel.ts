export type Source = {
  prepared_audio?: { job_id: string; input_duration_ms: number; output_duration_ms: number; pauses_removed: boolean };
  id: string;
  project_id: string;
  source_type: "local_upload" | "google_drive" | "yandex_disk";
  original_filename: string;
  mime_type: string | null;
  size_bytes: number | null;
  drive_file_url: string | null;
  upload_status: "pending" | "uploaded" | "deleted" | "expired" | "failed";
  uploaded_at: string | null;
  source_created_at: string | null;
  source_created_at_provenance:
    | "google_drive_created_time"
    | "yandex_disk_created_time"
    | "embedded_media_metadata"
    | null;
  expires_at: string | null;
  deleted_at: string | null;
  delete_reason: string | null;
  created_at: string;
  updated_at: string;
};

export function preparedAudioContext(source: Source) {
  return parsePreparedAudioContext(source.prepared_audio);
}

export function sourceLocationLabel(kind: string | null) {
  return kind === "google_drive" ? "Google Drive" : kind === "yandex_disk" ? "Яндекс Диск" : "Studio";
}

export function knownSourceDurationSeconds(source: Source | null | undefined): number | null {
  const context = source ? preparedAudioContext(source) : null;
  return context && context.output_duration_ms <= 604800000
    ? context.output_duration_ms / 1000 : null;
}

export function parsePreparedAudioContext(candidate: unknown): Source["prepared_audio"] | null {
  if (!candidate || typeof candidate !== "object") return null;
  const value = candidate as Record<string, unknown>;
  if (typeof value.job_id !== "string" || value.job_id.length !== 36 ||
      typeof value.input_duration_ms !== "number" || typeof value.output_duration_ms !== "number" ||
      !Number.isSafeInteger(value.input_duration_ms) || value.input_duration_ms <= 0 ||
      !Number.isSafeInteger(value.output_duration_ms) || value.output_duration_ms <= 0 ||
      typeof value.pauses_removed !== "boolean") return null;
  return { job_id: value.job_id, input_duration_ms: value.input_duration_ms,
    output_duration_ms: value.output_duration_ms, pauses_removed: value.pauses_removed };
}

export function reconcileOptimisticSources(
  optimisticSources: Source[],
  authoritativeSources: Source[],
) {
  const confirmedIds = new Set(authoritativeSources.map((source) => source.id));
  return optimisticSources.filter((source) => !confirmedIds.has(source.id));
}

export function isUsableJobSource(source: Source) {
  const expiresAt = source.expires_at
    ? new Date(source.expires_at).getTime()
    : null;
  return (
    source.upload_status === "uploaded" &&
    !source.deleted_at &&
    (expiresAt == null || expiresAt > Date.now()) &&
    (source.source_type === "google_drive" || source.source_type === "yandex_disk" ||
      source.source_type === "local_upload")
  );
}

export function unusableJobSourceReason(source: Source) {
  if (source.deleted_at)
    return "Убранный из Studio файл нельзя добавить в задачу";
  if (source.expires_at && new Date(source.expires_at).getTime() <= Date.now())
    return "Срок хранения временной копии истёк";
  if (source.upload_status !== "uploaded")
    return "Файл ещё не готов для задачи";
  return "Тип файла не поддерживается для задачи";
}

export function sourceСтатусLabel(status: Source["upload_status"]) {
  const labels: Record<Source["upload_status"], string> = {
    pending: "Загружается",
    uploaded: "Готов",
    deleted: "Убран из Studio",
    expired: "Срок истёк",
    failed: "Ошибка",
  };
  return labels[status];
}
