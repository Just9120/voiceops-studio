import { isApprovedTranscriptUrl } from "./outputUrls";
import { api } from "./apiClient";
import {
  isTranscriptionLanguageMode,
  type JobMediaClip,
  type JobOutputFolder,
  type JobOutputsResponse,
  type JobSpeakerIdentity,
  type JobSource,
  type JobUsageCost,
  type TranscriptionJob,
} from "./jobModel";
import { LATEST_REQUEST_CANCEL_REASON } from "./latestRequest";
import { parsePreparedAudioContext, type Source } from "./sourceModel";

const JOB_STATUSES = new Set([
  "queued",
  "processing",
  "cancelled",
  "failed",
  "completed",
]);
const SOURCE_STATUSES = new Set([
  "pending",
  "uploaded",
  "deleted",
  "expired",
  "failed",
]);

export type CollectionPage<T> = {
  items: T[];
  nextCursor: string | null;
  pageSize: number;
};

const DEFAULT_COLLECTION_PAGE_SIZE = 50;
const MAX_COLLECTION_PAGE_SIZE = 100;
const SIGNED_CURSOR_RE = /^[A-Za-z0-9_-]+$/;

export function parseProjectSourceCollection(
  candidate: unknown,
  projectId: string,
): Source[] | null {
  if (!isRecord(candidate) || !Array.isArray(candidate.sources)) return null;
  const sources: Source[] = [];
  for (const rawSource of candidate.sources) {
    const source = parseSource(rawSource, projectId);
    if (!source) return null;
    sources.push(source);
  }
  return hasUniqueIds(sources) ? sources : null;
}

export function parseProjectSourcePage(
  candidate: unknown,
  projectId: string,
): CollectionPage<Source> | null {
  const items = parseProjectSourceCollection(candidate, projectId);
  return items ? parseCollectionPage(candidate, "sources", items) : null;
}

export function parseProjectJobCollection(
  candidate: unknown,
  projectId: string,
): TranscriptionJob[] | null {
  if (!isRecord(candidate) || !Array.isArray(candidate.jobs)) return null;
  const jobs: TranscriptionJob[] = [];
  const batchPositions = new Map<string, Set<number>>();
  for (const rawJob of candidate.jobs) {
    const job = parseJob(rawJob, projectId);
    if (!job) return null;
    if (job.batch) {
      const positions = batchPositions.get(job.batch.id) ?? new Set<number>();
      if (positions.has(job.batch.position)) return null;
      positions.add(job.batch.position);
      batchPositions.set(job.batch.id, positions);
    }
    jobs.push(job);
  }
  return hasUniqueIds(jobs) ? jobs : null;
}

export function parseProjectJobPage(
  candidate: unknown,
  projectId: string,
): CollectionPage<TranscriptionJob> | null {
  const items = parseProjectJobCollection(candidate, projectId);
  return items ? parseCollectionPage(candidate, "jobs", items) : null;
}

export function parseJobDetailResponse(
  candidate: unknown,
  projectId: string,
  jobId: string,
): TranscriptionJob | null {
  const job = parseJob(candidate, projectId);
  if (
    !job ||
    job.id !== jobId ||
    !isRecord(candidate) ||
    !Array.isArray(candidate.sources)
  ) {
    return null;
  }
  const sources: JobSource[] = [];
  for (const rawSource of candidate.sources) {
    const source = parseJobSource(rawSource, projectId);
    if (!source) return null;
    sources.push(source);
  }
  if (
    sources.length !== job.source_count ||
    !hasUniqueIds(sources) ||
    new Set(sources.map((source) => source.position)).size !== sources.length
  ) {
    return null;
  }
  return { ...job, sources };
}

export function parseJobSummaryResponse(
  candidate: unknown,
  projectId: string,
  jobId: string,
): TranscriptionJob | null {
  const job = parseJob(candidate, projectId);
  return job?.id === jobId ? job : null;
}

export function parseJobOutputsResponse(
  candidate: unknown,
  jobId: string,
): JobOutputsResponse | null {
  if (
    !isRecord(candidate) ||
    boundedString(candidate.job_id, 36) !== jobId ||
    !JOB_STATUSES.has(String(candidate.job_status)) ||
    !isNonNegativeInteger(candidate.output_count) ||
    !Array.isArray(candidate.outputs) ||
    candidate.output_count !== candidate.outputs.length
  ) {
    return null;
  }
  const outputs: JobOutputsResponse["outputs"] = [];
  for (const rawOutput of candidate.outputs) {
    const output = parseJobOutput(rawOutput);
    if (!output) return null;
    outputs.push(output);
  }
  if (
    new Set(outputs.map((output) => output.source_id)).size !== outputs.length ||
    new Set(outputs.map((output) => output.source_position)).size !==
      outputs.length
  ) {
    return null;
  }
  return {
    job_id: jobId,
    job_status: candidate.job_status as JobOutputsResponse["job_status"],
    output_count: candidate.output_count,
    outputs,
  };
}

export async function requestProjectSourceCollection(
  projectId: string,
  signal?: AbortSignal,
): Promise<Source[]> {
  const candidate = await api<unknown>(`/projects/${projectId}/sources`, {
    signal,
    ignoredAbortReason: LATEST_REQUEST_CANCEL_REASON,
  });
  const sources = parseProjectSourceCollection(candidate, projectId);
  if (!sources) throw new Error("invalid_project_source_collection");
  return sources;
}

export async function requestProjectSourcePage(
  projectId: string,
  cursor: string | null = null,
  signal?: AbortSignal,
): Promise<CollectionPage<Source>> {
  const candidate = await requestCollectionPage(
    `/projects/${projectId}/sources`,
    cursor,
    signal,
  );
  const page = parseProjectSourcePage(candidate, projectId);
  if (!page) throw new Error("invalid_project_source_page");
  return page;
}

export async function requestProjectJobCollection(
  projectId: string,
  signal?: AbortSignal,
): Promise<TranscriptionJob[]> {
  const candidate = await api<unknown>(`/projects/${projectId}/jobs`, {
    signal,
    ignoredAbortReason: LATEST_REQUEST_CANCEL_REASON,
  });
  const jobs = parseProjectJobCollection(candidate, projectId);
  if (!jobs) throw new Error("invalid_project_job_collection");
  return jobs;
}

export async function requestProjectJobPage(
  projectId: string,
  cursor: string | null = null,
  signal?: AbortSignal,
): Promise<CollectionPage<TranscriptionJob>> {
  const candidate = await requestCollectionPage(
    `/projects/${projectId}/jobs`,
    cursor,
    signal,
  );
  const page = parseProjectJobPage(candidate, projectId);
  if (!page) throw new Error("invalid_project_job_page");
  return page;
}

function requestCollectionPage(
  path: string,
  cursor: string | null,
  signal?: AbortSignal,
) {
  if (!cursor) {
    return api<unknown>(path, {
      signal,
      ignoredAbortReason: LATEST_REQUEST_CANCEL_REASON,
    });
  }
  const search = new URLSearchParams({
    page_size: String(DEFAULT_COLLECTION_PAGE_SIZE),
  });
  search.set("cursor", cursor);
  return api<unknown>(`${path}?${search.toString()}`, {
    signal,
    ignoredAbortReason: LATEST_REQUEST_CANCEL_REASON,
  });
}

function parseCollectionPage<T>(
  candidate: unknown,
  collectionKey: "sources" | "jobs",
  items: T[],
): CollectionPage<T> | null {
  if (!isRecord(candidate) || !Array.isArray(candidate[collectionKey])) {
    return null;
  }
  const rawPageSize = candidate.page_size;
  const pageSize =
    rawPageSize === undefined
      ? DEFAULT_COLLECTION_PAGE_SIZE
      : rawPageSize;
  if (
    !Number.isSafeInteger(pageSize) ||
    (pageSize as number) < 1 ||
    (pageSize as number) > MAX_COLLECTION_PAGE_SIZE ||
    items.length > (pageSize as number)
  ) {
    return null;
  }
  const rawCursor = candidate.next_cursor;
  const nextCursor = rawCursor === undefined ? null : rawCursor;
  if (
    nextCursor !== null &&
    (typeof nextCursor !== "string" ||
      nextCursor.length === 0 ||
      nextCursor.length > 1_200 ||
      !SIGNED_CURSOR_RE.test(nextCursor) ||
      items.length !== pageSize)
  ) {
    return null;
  }
  return { items, nextCursor, pageSize: pageSize as number };
}

export async function requestJobDetail(
  jobId: string,
  projectId: string,
  signal?: AbortSignal,
): Promise<TranscriptionJob> {
  const candidate = await requestJobRead(`/jobs/${jobId}`, signal);
  const job = parseJobDetailResponse(candidate, projectId, jobId);
  if (!job) throw new Error("invalid_job_detail_response");
  return job;
}

export async function requestJobOutputs(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobOutputsResponse> {
  const candidate = await requestJobRead(`/jobs/${jobId}/outputs`, signal);
  const outputs = parseJobOutputsResponse(candidate, jobId);
  if (!outputs) throw new Error("invalid_job_outputs_response");
  return outputs;
}

async function requestJobRead(path: string, signal?: AbortSignal) {
  return api<unknown>(path, {
    signal,
    ignoredAbortReason: LATEST_REQUEST_CANCEL_REASON,
  });
}

function parseSource(
  candidate: unknown,
  projectId: string,
  driveUrlRequired = true,
): Source | null {
  if (!isRecord(candidate)) return null;
  const id = boundedString(candidate.id, 36);
  const candidateProjectId = boundedString(candidate.project_id, 36);
  const originalFilename = boundedString(candidate.original_filename, 255);
  const mimeType = nullableBoundedString(candidate.mime_type, 255);
  const driveFileUrl = driveUrlRequired
    ? nullableBoundedString(candidate.drive_file_url, 2_000)
    : null;
  const deleteReason = nullableBoundedString(candidate.delete_reason, 80);
  const rawSourceCreatedAt =
    candidate.source_created_at === undefined
      ? null
      : candidate.source_created_at;
  const rawCreationProvenance =
    candidate.source_created_at_provenance === undefined
      ? null
      : candidate.source_created_at_provenance;
  const creationProvenance = nullableBoundedString(
    rawCreationProvenance,
    40,
  );
  const creationAuthorityIsValid =
    (rawSourceCreatedAt === null && creationProvenance === null) ||
    (isIsoDate(rawSourceCreatedAt) &&
      (creationProvenance === "google_drive_created_time" || creationProvenance === "yandex_disk_created_time" ||
        creationProvenance === "embedded_media_metadata"));
  if (
    !id ||
    candidateProjectId !== projectId ||
    !originalFilename ||
    (candidate.source_type !== "local_upload" &&
      candidate.source_type !== "google_drive" && candidate.source_type !== "yandex_disk") ||
    !SOURCE_STATUSES.has(String(candidate.upload_status)) ||
    mimeType === undefined ||
    driveFileUrl === undefined ||
    deleteReason === undefined ||
    creationProvenance === undefined ||
    !creationAuthorityIsValid ||
    !isNullableNonNegativeInteger(candidate.size_bytes) ||
    !isNullableIsoDate(candidate.uploaded_at) ||
    !isNullableIsoDate(candidate.expires_at) ||
    !isNullableIsoDate(candidate.deleted_at) ||
    !isIsoDate(candidate.created_at) ||
    !isIsoDate(candidate.updated_at)
  ) {
    return null;
  }
  return {
    id,
    project_id: candidateProjectId,
    source_type: candidate.source_type,
    ...(parsePreparedAudioContext(candidate.prepared_audio) ? { prepared_audio: parsePreparedAudioContext(candidate.prepared_audio)! } : {}),
    original_filename: originalFilename,
    mime_type: mimeType,
    size_bytes: candidate.size_bytes,
    drive_file_url: driveFileUrl,
    upload_status: candidate.upload_status as Source["upload_status"],
    uploaded_at: candidate.uploaded_at,
    source_created_at: rawSourceCreatedAt as string | null,
    source_created_at_provenance: creationProvenance,
    expires_at: candidate.expires_at,
    deleted_at: candidate.deleted_at,
    delete_reason: deleteReason,
    created_at: candidate.created_at,
    updated_at: candidate.updated_at,
  };
}

function parseJobSource(candidate: unknown, projectId: string): JobSource | null {
  const source = parseSource(candidate, projectId, false);
  if (
    !source ||
    !isRecord(candidate) ||
    !isNonNegativeInteger(candidate.position) ||
    (candidate.job_source_status !== "queued" &&
      candidate.job_source_status !== "skipped")
  ) {
    return null;
  }
  return {
    ...source,
    position: candidate.position,
    job_source_status: candidate.job_source_status,
  };
}

function parseJobOutput(
  candidate: unknown,
): JobOutputsResponse["outputs"][number] | null {
  if (!isRecord(candidate)) return null;
  const sourceId = boundedString(candidate.source_id, 36);
  const sourceName = nullableBoundedString(candidate.source_name, 255);
  const sourceType = nullableBoundedString(candidate.source_type, 40);
  const outputKind = nullableBoundedString(candidate.output_kind, 80);
  const transcriptStandard = nullableBoundedString(
    candidate.transcript_standard,
    80,
  );
  const webViewUrl = nullableBoundedString(candidate.web_view_url, 50_000);
  if (
    !sourceId ||
    !isNonNegativeInteger(candidate.source_position) ||
    sourceName === undefined ||
    sourceType === undefined ||
    outputKind === undefined ||
    transcriptStandard === undefined ||
    webViewUrl === undefined ||
    (webViewUrl !== null && !isApprovedTranscriptUrl(webViewUrl, outputKind)) ||
    typeof candidate.link_available !== "boolean" ||
    candidate.link_available !== (webViewUrl !== null) ||
    !isNullableNonNegativeInteger(candidate.document_character_count) ||
    !isNullableIsoDate(candidate.document_created_at) ||
    !isNullableIsoDate(candidate.persisted_at)
  ) {
    return null;
  }
  return {
    source_id: sourceId,
    source_position: candidate.source_position,
    source_name: sourceName,
    source_type: sourceType,
    output_kind: outputKind,
    transcript_standard: transcriptStandard,
    web_view_url: webViewUrl,
    link_available: candidate.link_available,
    document_character_count: candidate.document_character_count,
    document_created_at: candidate.document_created_at,
    persisted_at: candidate.persisted_at,
  };
}

function parseJob(
  candidate: unknown,
  projectId: string,
): TranscriptionJob | null {
  if (!isRecord(candidate)) return null;
  const id = boundedString(candidate.id, 36);
  const candidateProjectId = boundedString(candidate.project_id, 36);
  const title = nullableBoundedString(candidate.title, 160);
  const provider = nullableBoundedString(candidate.provider, 40);
  const outputProvider = candidate.output_provider;
  const errorCode = nullableBoundedString(candidate.error_code, 80);
  const errorMessage = nullableBoundedString(candidate.error_message, 512);
  const mediaClip = parseOptionalMediaClip(candidate.media_clip);
  const outputFolder = parseOptionalOutputFolder(candidate.output_folder);
  const primaryOutputUrl = candidate.primary_output_url === undefined ? undefined : boundedString(candidate.primary_output_url, 50_000);
  const batch = parseOptionalBatchReference(candidate.batch);
  const languageMode = candidate.language_mode;
  const diarizationEnabled = candidate.diarization_enabled;
  const terminalDismissedAt = candidate.terminal_dismissed_at;
  const historyAttentionRequired = candidate.history_attention_required;
  const historyAttentionResolvedAt = candidate.history_attention_resolved_at;
  const historyAttentionResolution = candidate.history_attention_resolution;
  const historyAttentionLinkedJobId = candidate.history_attention_linked_job_id;
  const sourceNames = candidate.source_names;
  const speakerIdentities = parseOptionalSpeakerIdentities(
    candidate.speaker_identities,
  );
  const usageCost = parseOptionalJobUsageCost(candidate.usage_cost);
  if (
    !id ||
    candidateProjectId !== projectId ||
    !JOB_STATUSES.has(String(candidate.status)) ||
    title === undefined ||
    provider === undefined ||
    (outputProvider !== undefined && outputProvider !== "google_drive" && outputProvider !== "yandex_disk") ||
    errorCode === undefined ||
    errorMessage === undefined ||
    mediaClip === false ||
    outputFolder === false ||
    (candidate.primary_output_url !== undefined && (!primaryOutputUrl || !isApprovedTranscriptUrl(primaryOutputUrl))) ||
    batch === false ||
    speakerIdentities === false ||
    usageCost === false ||
    (languageMode !== undefined &&
      languageMode !== null &&
      !isTranscriptionLanguageMode(languageMode)) ||
    (diarizationEnabled !== undefined &&
      typeof diarizationEnabled !== "boolean") ||
    (terminalDismissedAt !== undefined &&
      !isNullableIsoDate(terminalDismissedAt)) ||
    (historyAttentionRequired !== undefined &&
      typeof historyAttentionRequired !== "boolean") ||
    (historyAttentionResolvedAt !== undefined &&
      !isNullableIsoDate(historyAttentionResolvedAt)) ||
    (historyAttentionResolution !== undefined &&
      historyAttentionResolution !== null &&
      historyAttentionResolution !== "acknowledged_no_result" &&
      historyAttentionResolution !== "linked_later_result") ||
    (historyAttentionLinkedJobId !== undefined &&
      historyAttentionLinkedJobId !== null &&
      !boundedString(historyAttentionLinkedJobId, 36)) ||
    !isNonNegativeInteger(candidate.source_count) ||
    (sourceNames !== undefined &&
      (!Array.isArray(sourceNames) ||
        sourceNames.length > 3 ||
        sourceNames.some((name) => !boundedString(name, 512)))) ||
    !isIsoDate(candidate.created_at) ||
    !isIsoDate(candidate.updated_at) ||
    !isNullableIsoDate(candidate.cancelled_at) ||
    !isNullableIsoDate(candidate.cancel_requested_at) ||
    !isNonNegativeInteger(candidate.attempt_count) ||
    !isNullableIsoDate(candidate.started_at) ||
    !isNullableIsoDate(candidate.finished_at)
  ) {
    return null;
  }
  return {
    id,
    project_id: candidateProjectId,
    status: candidate.status as TranscriptionJob["status"],
    title,
    provider,
    ...(outputProvider !== undefined ? { output_provider: outputProvider as "google_drive" | "yandex_disk" } : {}),
    ...(primaryOutputUrl ? { primary_output_url: primaryOutputUrl } : {}),
    ...(languageMode !== undefined ? { language_mode: languageMode } : {}),
    ...(diarizationEnabled !== undefined
      ? { diarization_enabled: diarizationEnabled }
      : {}),
    ...(candidate.media_clip !== undefined ? { media_clip: mediaClip } : {}),
    ...(candidate.batch !== undefined ? { batch } : {}),
    ...(terminalDismissedAt !== undefined
      ? { terminal_dismissed_at: terminalDismissedAt }
      : {}),
    ...(historyAttentionRequired !== undefined
      ? { history_attention_required: historyAttentionRequired }
      : {}),
    ...(historyAttentionResolvedAt !== undefined
      ? { history_attention_resolved_at: historyAttentionResolvedAt }
      : {}),
    ...(historyAttentionResolution !== undefined
      ? { history_attention_resolution: historyAttentionResolution }
      : {}),
    ...(historyAttentionLinkedJobId !== undefined
      ? {
          history_attention_linked_job_id:
            historyAttentionLinkedJobId as string | null,
        }
      : {}),
    source_count: candidate.source_count,
    ...(sourceNames !== undefined ? { source_names: sourceNames as string[] } : {}),
    created_at: candidate.created_at,
    updated_at: candidate.updated_at,
    cancelled_at: candidate.cancelled_at,
    cancel_requested_at: candidate.cancel_requested_at,
    attempt_count: candidate.attempt_count,
    started_at: candidate.started_at,
    finished_at: candidate.finished_at,
    error_code: errorCode,
    error_message: errorMessage,
    ...(candidate.output_folder !== undefined
      ? { output_folder: outputFolder }
      : {}),
    ...(candidate.speaker_identities !== undefined
      ? { speaker_identities: speakerIdentities }
      : {}),
    ...(candidate.usage_cost !== undefined ? { usage_cost: usageCost } : {}),
  };
}

function parseOptionalJobUsageCost(
  candidate: unknown,
): JobUsageCost | false | undefined {
  if (candidate === undefined) return undefined;
  if (!isRecord(candidate)) return false;
  const status = candidate.accounting_status;
  if (
    status !== "unavailable" &&
    status !== "not_started" &&
    status !== "confirmed_partial" &&
    status !== "complete" &&
    status !== "uncertain"
  ) {
    return false;
  }
  if (status === "unavailable" || status === "not_started") {
    if (
      candidate.confirmed_billed_duration_seconds !== null ||
      candidate.confirmed_provider_cost !== null ||
      candidate.currency !== null ||
      candidate.cost_basis !== null ||
      candidate.rate_snapshot !== null
    ) {
      return false;
    }
    return {
      accounting_status: status,
      confirmed_billed_duration_seconds: null,
      confirmed_provider_cost: null,
      currency: null,
      cost_basis: null,
      rate_snapshot: null,
    };
  }

  const duration = candidate.confirmed_billed_duration_seconds;
  const cost = candidate.confirmed_provider_cost;
  const rateSnapshot = parseJobUsageRateSnapshot(candidate.rate_snapshot);
  if (
    typeof duration !== "number" ||
    !Number.isFinite(duration) ||
    duration < 0 ||
    typeof cost !== "string" ||
    !/^(0|[1-9][0-9]*)[.][0-9]{8}$/.test(cost) ||
    candidate.currency !== "USD" ||
    candidate.cost_basis !== "confirmed_audio_duration_x_rate_snapshot" ||
    rateSnapshot === false ||
    (rateSnapshot === null && (status !== "complete" || duration !== 0)) ||
    (duration === 0 && cost !== "0.00000000")
  ) {
    return false;
  }
  return {
    accounting_status: status,
    confirmed_billed_duration_seconds: duration,
    confirmed_provider_cost: cost,
    currency: "USD",
    cost_basis: "confirmed_audio_duration_x_rate_snapshot",
    rate_snapshot: rateSnapshot,
  };
}

function parseJobUsageRateSnapshot(
  candidate: unknown,
): JobUsageCost["rate_snapshot"] | false {
  if (candidate === null) return null;
  if (!isRecord(candidate)) return false;
  const rate = candidate.rate_per_hour;
  if (
    typeof rate !== "string" ||
    !/^(0|[1-9][0-9]*)[.][0-9]{6}$/.test(rate) ||
    Number(rate) <= 0 ||
    candidate.currency !== "USD" ||
    !isIsoCalendarDate(candidate.effective_date) ||
    (candidate.source !== "elevenlabs_public_api_pricing" && candidate.source !== "yandex_public_api_pricing")
  ) {
    return false;
  }
  return {
    rate_per_hour: rate,
    currency: "USD",
    effective_date: candidate.effective_date,
    source: candidate.source as "elevenlabs_public_api_pricing" | "yandex_public_api_pricing",
  };
}

function parseOptionalSpeakerIdentities(
  candidate: unknown,
): JobSpeakerIdentity[] | false | undefined {
  if (candidate === undefined) return undefined;
  if (!Array.isArray(candidate)) return false;
  const speakers: JobSpeakerIdentity[] = [];
  for (const raw of candidate) {
    if (!isRecord(raw)) return false;
    const id = boundedString(raw.id, 36);
    const label = boundedString(raw.label, 40);
    if (
      !id ||
      !label ||
      !/^Speaker [1-9][0-9]*$/.test(label) ||
      typeof raw.sample_available !== "boolean"
    ) {
      return false;
    }
    let profile: JobSpeakerIdentity["profile"] = null;
    if (raw.profile !== null) {
      if (!isRecord(raw.profile)) return false;
      const profileId = boundedString(raw.profile.id, 36);
      const displayName = boundedString(raw.profile.display_name, 160);
      const role = boundedString(raw.profile.role, 120);
      if (!profileId || !displayName || !role) return false;
      profile = { id: profileId, display_name: displayName, role };
    }
    speakers.push({
      id,
      label,
      sample_available: raw.sample_available,
      profile,
    });
  }
  return hasUniqueIds(speakers) ? speakers : false;
}

function parseOptionalBatchReference(
  candidate: unknown,
): TranscriptionJob["batch"] | false | undefined {
  if (candidate === undefined) return undefined;
  if (candidate === null) return null;
  if (!isRecord(candidate)) return false;
  const keys = Object.keys(candidate).sort();
  if (
    keys.length !== 2 ||
    keys[0] !== "id" ||
    keys[1] !== "position" ||
    typeof candidate.id !== "string" ||
    !/^multi_[0-9a-f]{32}$/.test(candidate.id) ||
    !isNonNegativeInteger(candidate.position) ||
    candidate.position > 49
  ) {
    return false;
  }
  return { id: candidate.id, position: candidate.position };
}

function parseOptionalMediaClip(
  candidate: unknown,
): JobMediaClip | null | false | undefined {
  if (candidate === undefined) return undefined;
  if (candidate === null) return null;
  if (!isRecord(candidate)) return false;
  const start = candidate.start_seconds;
  const end = candidate.end_seconds;
  if (
    !isNullableNonNegativeInteger(start) ||
    !isNullableNonNegativeInteger(end) ||
    (start !== null && start > 604_800) ||
    (end !== null && end > 604_800) ||
    (end !== null && end <= (start ?? 0)) ||
    (start === 0 && end === null) ||
    (start === null && end === null)
  ) {
    return false;
  }
  return { start_seconds: start, end_seconds: end };
}

function parseOptionalOutputFolder(
  candidate: unknown,
): JobOutputFolder | null | false | undefined {
  if (candidate === undefined) return undefined;
  if (candidate === null) return null;
  if (!isRecord(candidate)) return false;
  const name = boundedString(candidate.name, 512);
  const webViewUrl = nullableBoundedString(candidate.web_view_url, 50_000);
  if (!name || webViewUrl === undefined) return false;
  return { name, web_view_url: webViewUrl };
}

function boundedString(value: unknown, maxLength: number): string | null {
  return typeof value === "string" &&
    value.trim().length > 0 &&
    value.length <= maxLength
    ? value
    : null;
}

function nullableBoundedString(
  value: unknown,
  maxLength: number,
): string | null | undefined {
  if (value === null) return null;
  return typeof value === "string" && value.length <= maxLength
    ? value
    : undefined;
}

function isNonNegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}

function isNullableNonNegativeInteger(
  value: unknown,
): value is number | null {
  return value === null || isNonNegativeInteger(value);
}

function isIsoDate(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    value.length <= 64 &&
    Number.isFinite(Date.parse(value))
  );
}

function isNullableIsoDate(value: unknown): value is string | null {
  return value === null || isIsoDate(value);
}

function isIsoCalendarDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return false;
  }
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value;
}

function hasUniqueIds(items: Array<{ id: string }>) {
  return new Set(items.map((item) => item.id)).size === items.length;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
