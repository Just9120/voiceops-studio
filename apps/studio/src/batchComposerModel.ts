import {
  isTranscriptionLanguageMode,
  type TranscriptionJob,
  type TranscriptionLanguageMode,
} from "./jobModel";

export const DEFAULT_TRANSCRIPTION_LANGUAGE_MODE: TranscriptionLanguageMode =
  "ru";
export const MAX_BATCH_ITEMS = 50;
export type SttProvider = "elevenlabs" | "yandex";
export type SttOperatingMode = "economic" | "standard" | "premium";

export type VerifiedOutputFolder = {
  folder_id: string;
  name: string;
  web_view_url: string | null;
  provider?: "google_drive" | "yandex_disk";
};
export type ComposerSegment = {
  id: string;
  start_boundary: string;
  end_boundary: string;
  ends_at_source_end: boolean;
  title: string;
  reprocess_existing: boolean;
  output_folder?: VerifiedOutputFolder | null;
};
export type ComposerRow = {
  id: string;
  source_id: string;
  output_folder: VerifiedOutputFolder | null;
  segmentation_enabled?: boolean;
  segments: ComposerSegment[];
};
export type BatchCreateResponse = {
  jobs: TranscriptionJob[];
  created_count: number;
  replayed: boolean;
};
export type BatchCreateRequest = {
  provider?: SttProvider;
  operating_mode?: SttOperatingMode;
  provider_credential_id: string | null;
  language: TranscriptionLanguageMode;
  options: { diarize: boolean; dictionary_ids?: string[] };
  items: {
    source_id: string;
    output_folder_id: string;
    output_provider?: "google_drive" | "yandex_disk";
    title: string | null;
    reprocess_existing: boolean;
    media_clip_start_seconds?: number | null;
    media_clip_end_seconds?: number | null;
  }[];
};
export type ExpandedComposerItem = {
  row_id: string;
  segment_id: string;
  segment_index: number;
  request_item: BatchCreateRequest["items"][number];
};
export type BatchPreflightItem = {
  position: number;
  title: string | null;
  media_clip: {
    start_seconds: number | null;
    end_seconds: number | null;
  } | null;
  source: {
    name: string;
    source_type: "local_upload" | "google_drive" | "yandex_disk" | "unknown";
    mime_type: string | null;
    size_bytes: number | null;
    duration_seconds: number | null;
  };
  output_destination: { name: string };
  existing_result_match: {
    status:
      | "accepted_match"
      | "standardization_required"
      | "indeterminate"
      | "no_match";
    accepted_output_count: number;
    resolution: "not_required" | "required" | "reprocess";
  };
  provider_attempt_authority: {
    status: "available" | "blocked";
    reason_code:
      | "equivalent_provider_work_in_flight"
      | "equivalent_provider_outcome_unresolved"
      | null;
    attention_job_id?: string | null;
  };
  planned_outcome: "process" | "skip" | "blocked";
};
export type BatchPreflightResponse = {
  provider: SttProvider;
  model: string;
  operating_mode: SttOperatingMode;
  dictionary_term_count: number;
  language_mode: TranscriptionLanguageMode;
  diarization_enabled: boolean;
  existing_result_authority: {
    status: "partial" | "available";
    reason_code: string | null;
  };
  items: BatchPreflightItem[];
  summary: {
    process_count: number;
    skip_count: number;
    blocked_count: number;
  };
  confirmation_required: true;
};

export function newComposerRow(): ComposerRow {
  return {
    id: crypto.randomUUID(),
    source_id: "",
    output_folder: null,
    segmentation_enabled: false,
    segments: [newComposerSegment(0, 1)],
  };
}

function newComposerSegment(position: number, count: number): ComposerSegment {
  return {
    id: crypto.randomUUID(),
    start_boundary: position === 0 ? "0:00" : "",
    end_boundary: "",
    ends_at_source_end: position === count - 1,
    title: "",
    reprocess_existing: false,
    output_folder: null,
  };
}

export function resizeComposerSegments(
  segments: ComposerSegment[],
  requestedCount: number,
): ComposerSegment[] {
  if (
    !Number.isInteger(requestedCount) ||
    requestedCount < 1 ||
    requestedCount > MAX_BATCH_ITEMS
  ) {
    throw new Error("Invalid segment count");
  }
  if (requestedCount === segments.length) return segments;
  const next = segments.slice(0, requestedCount).map((segment) => ({
    ...segment,
    reprocess_existing: false,
  }));
  while (next.length < requestedCount) {
    next.push(newComposerSegment(next.length, requestedCount));
  }
  if (requestedCount > segments.length) {
    next[next.length - 1] = {
      ...next[next.length - 1],
      end_boundary: "",
      ends_at_source_end: true,
    };
  }
  return next;
}

export function clearComposerReprocessDecisions(
  row: ComposerRow,
): ComposerRow {
  return {
    ...row,
    segments: row.segments.map((segment) => ({
      ...segment,
      reprocess_existing: false,
    })),
  };
}

export function composerSignature(
  rows: ComposerRow[],
  credentialId: string,
  languageMode: TranscriptionLanguageMode,
  diarizationEnabled: boolean,
  provider?: SttProvider,
  operatingMode?: SttOperatingMode,
  dictionaryIds?: string[],
) {
  try {
    return JSON.stringify(
      buildBatchCreateRequest(
        rows,
        credentialId,
        languageMode,
        diarizationEnabled,
        provider,
        operatingMode,
        dictionaryIds,
      ),
    );
  } catch {
    return JSON.stringify({
      credentialId,
      languageMode,
      diarizationEnabled,
      provider,
      operatingMode,
      dictionaryIds,
      invalid_rows: rows.map((row) => ({
        id: row.id,
        source_id: row.source_id,
        output_folder_id: row.output_folder?.folder_id ?? null,
        output_provider: row.output_folder?.provider ?? "google_drive",
        segmentation_enabled: row.segmentation_enabled === true,
        segments: row.segments.map((segment) => ({
          id: segment.id,
          start_boundary: segment.start_boundary,
          end_boundary: segment.end_boundary,
          ends_at_source_end: segment.ends_at_source_end,
          title: segment.title,
          reprocess_existing: segment.reprocess_existing,
          output_folder_id: segment.output_folder?.folder_id ?? null,
          output_provider: segment.output_folder?.provider ?? null,
        })),
      })),
    });
  }
}

export function parseSegmentBoundary(value: string): number | null {
  const text = value.trim();
  const parts = text.split(":");
  if (parts.length !== 2 && parts.length !== 3) return null;
  if (!parts.every((part) => /^\d+$/.test(part))) return null;
  const numbers = parts.map(Number);
  const [hours, minutes, seconds] =
    numbers.length === 3
      ? [numbers[0], numbers[1], numbers[2]]
      : [0, numbers[0], numbers[1]];
  if (seconds >= 60 || (parts.length === 3 && minutes >= 60)) return null;
  const total = hours * 3600 + minutes * 60 + seconds;
  return Number.isSafeInteger(total) && total >= 0 && total <= 604800
    ? total
    : null;
}

export function formatSegmentBoundary(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${minutes}:${String(seconds).padStart(2, "0")}`;
}

type ParsedComposerSegment = {
  start_seconds: number;
  end_seconds: number | null;
};

function inspectComposerSegmentPlan(segments: ComposerSegment[], durationSeconds: number | null = null): {
  issue: string | null;
  clips: ParsedComposerSegment[];
} {
  if (segments.length < 1 || segments.length > MAX_BATCH_ITEMS) {
    return {
      issue: `укажите от 1 до ${MAX_BATCH_ITEMS} фрагментов`,
      clips: [],
    };
  }
  const clips: ParsedComposerSegment[] = [];
  for (let index = 0; index < segments.length; index += 1) {
    const segment = segments[index];
    const number = index + 1;
    const start = parseSegmentBoundary(segment.start_boundary);
    if (start === null) {
      return {
        issue: `фрагмент ${number}: укажите начало в формате ММ:СС или ЧЧ:ММ:СС`,
        clips: [],
      };
    }
    const end = segment.ends_at_source_end
      ? null
      : parseSegmentBoundary(segment.end_boundary);
    if (!segment.ends_at_source_end && end === null) {
      return {
        issue: `фрагмент ${number}: укажите конец или выберите «До конца файла»`,
        clips: [],
      };
    }
    if (end !== null && end <= start) {
      return {
        issue: `фрагмент ${number}: конец должен быть позже начала`,
        clips: [],
      };
    }
    if (durationSeconds !== null && (start >= durationSeconds || (end !== null && end > durationSeconds))) {
      return {
        issue: `фрагмент ${number}: границы выходят за длительность выбранной записи (${durationSeconds.toLocaleString("ru-RU")} сек.)`,
        clips: [],
      };
    }
    clips.push({ start_seconds: start, end_seconds: end });
  }
  return { issue: null, clips };
}

export function composerSegmentPlanIssue(
  segments: ComposerSegment[],
  durationSeconds: number | null = null,
): string | null {
  return inspectComposerSegmentPlan(segments, durationSeconds).issue;
}

export function expandComposerRows(rows: ComposerRow[]): ExpandedComposerItem[] {
  return rows.flatMap<ExpandedComposerItem>((row) => {
    if (!row.segmentation_enabled) {
      const segment = row.segments[0] ?? newComposerSegment(0, 1);
      return [{
        row_id: row.id,
        segment_id: segment.id,
        segment_index: 0,
        request_item: {
          source_id: row.source_id,
          output_folder_id: row.output_folder?.folder_id ?? "",
          ...(row.output_folder?.provider === "yandex_disk" ? { output_provider: "yandex_disk" as const } : {}),
          title: segment.title.trim() || null,
          reprocess_existing: segment.reprocess_existing,
        },
      }];
    }
    const inspected = inspectComposerSegmentPlan(row.segments);
    if (inspected.issue) throw new Error(inspected.issue);
    return row.segments.map((segment, segmentIndex) => {
      const clip = inspected.clips[segmentIndex];
      const fullSource =
        clip.start_seconds === 0 &&
        clip.end_seconds === null;
      return {
        row_id: row.id,
        segment_id: segment.id,
        segment_index: segmentIndex,
        request_item: {
          source_id: row.source_id,
          output_folder_id:
            segment.output_folder?.folder_id ?? row.output_folder?.folder_id ?? "",
          ...((segment.output_folder ?? row.output_folder)?.provider === "yandex_disk"
            ? { output_provider: "yandex_disk" as const } : {}),
          title: segment.title.trim() || null,
          reprocess_existing: segment.reprocess_existing,
          ...(fullSource
            ? {}
            : {
                media_clip_start_seconds: clip.start_seconds,
                media_clip_end_seconds: clip.end_seconds,
              }),
        },
      };
    });
  });
}

export function buildBatchCreateRequest(
  rows: ComposerRow[],
  credentialId: string,
  languageMode: TranscriptionLanguageMode,
  diarizationEnabled: boolean,
  provider?: SttProvider,
  operatingMode?: SttOperatingMode,
  dictionaryIds?: string[],
): BatchCreateRequest {
  const items = expandComposerRows(rows).map((item) => item.request_item);
  if (items.length > MAX_BATCH_ITEMS) throw new Error("Batch item limit exceeded");
  const request: BatchCreateRequest = {
    provider_credential_id: credentialId || null,
    language: languageMode,
    options: { diarize: diarizationEnabled },
    items,
  };
  if (provider) request.provider = provider;
  if (operatingMode) request.operating_mode = operatingMode;
  if (dictionaryIds?.length) request.options.dictionary_ids = [...dictionaryIds];
  return request;
}

export function parseBatchPreflightResponse(
  value: unknown,
): BatchPreflightResponse | null {
  if (!isRecord(value)) return null;
  if (
    !hasExactKeys(value, [
      "provider",
      "model",
      "operating_mode",
      "dictionary_term_count",
      "language_mode",
      "diarization_enabled",
      "existing_result_authority",
      "items",
      "summary",
      "confirmation_required",
    ]) ||
    !["elevenlabs", "yandex"].includes(String(value.provider)) ||
    typeof value.model !== "string" ||
    value.model.length === 0 ||
    value.model.length > 120 ||
    !["economic", "standard", "premium"].includes(
      String(value.operating_mode),
    ) ||
    !isNonNegativeInteger(value.dictionary_term_count) ||
    !isTranscriptionLanguageMode(value.language_mode) ||
    typeof value.diarization_enabled !== "boolean" ||
    value.confirmation_required !== true ||
    !isRecord(value.existing_result_authority) ||
    !hasExactKeys(value.existing_result_authority, ["status", "reason_code"]) ||
    !["partial", "available"].includes(
      String(value.existing_result_authority.status),
    ) ||
    !isNullableString(value.existing_result_authority.reason_code) ||
    !Array.isArray(value.items) ||
    !isRecord(value.summary) ||
    !hasExactKeys(value.summary, [
      "process_count",
      "skip_count",
      "blocked_count",
    ])
  ) {
    return null;
  }
  if (
    (value.existing_result_authority.status === "partial" &&
      value.existing_result_authority.reason_code !==
        "unlinked_catalog_entries_excluded") ||
    (value.existing_result_authority.status === "available" &&
      value.existing_result_authority.reason_code !== null)
  ) {
    return null;
  }
  const items = value.items;
  if (!items.every((item, index) => isPreflightItem(item, index))) return null;
  const counts = [
    value.summary.process_count,
    value.summary.skip_count,
    value.summary.blocked_count,
  ];
  if (!counts.every(isNonNegativeInteger)) return null;
  const outcomes = items.map((item) =>
    isRecord(item) ? item.planned_outcome : null,
  );
  if (
    value.summary.process_count !==
      outcomes.filter((outcome) => outcome === "process").length ||
    value.summary.skip_count !==
      outcomes.filter((outcome) => outcome === "skip").length ||
    value.summary.blocked_count !==
      outcomes.filter((outcome) => outcome === "blocked").length
  ) {
    return null;
  }
  return value as BatchPreflightResponse;
}

function isPreflightItem(value: unknown, expectedPosition: number) {
  if (!isRecord(value) || !isRecord(value.source)) return false;
  if (
    !hasExactKeys(value, [
      "position",
      "title",
      "media_clip",
      "source",
      "output_destination",
      "existing_result_match",
      "provider_attempt_authority",
      "planned_outcome",
    ]) ||
    !hasExactKeys(value.source, [
      "name",
      "source_type",
      "mime_type",
      "size_bytes",
      "duration_seconds",
    ]) ||
    value.position !== expectedPosition ||
    !isNullableString(value.title) ||
    !isMediaClip(value.media_clip) ||
    typeof value.source.name !== "string" ||
    !["local_upload", "google_drive", "yandex_disk", "unknown"].includes(
      String(value.source.source_type),
    ) ||
    !isNullableString(value.source.mime_type) ||
    !isNullableNonNegativeNumber(value.source.size_bytes) ||
    !isNullableNonNegativeNumber(value.source.duration_seconds) ||
    !isRecord(value.output_destination) ||
    !hasExactKeys(value.output_destination, ["name"]) ||
    typeof value.output_destination.name !== "string" ||
    !isRecord(value.existing_result_match) ||
    !hasExactKeys(value.existing_result_match, [
      "status",
      "accepted_output_count",
      "resolution",
    ]) ||
    ![
      "accepted_match",
      "standardization_required",
      "indeterminate",
      "no_match",
    ].includes(
      String(value.existing_result_match.status),
    ) ||
    !isNonNegativeInteger(
      value.existing_result_match.accepted_output_count,
    ) ||
    !["not_required", "required", "reprocess"].includes(
      String(value.existing_result_match.resolution),
    ) ||
    !isRecord(value.provider_attempt_authority) ||
    !(hasExactKeys(value.provider_attempt_authority, [
      "status",
      "reason_code",
    ]) || hasExactKeys(value.provider_attempt_authority, [
      "status",
      "reason_code",
      "attention_job_id",
    ])) ||
    !["available", "blocked"].includes(
      String(value.provider_attempt_authority.status),
    ) ||
    !isNullableString(value.provider_attempt_authority.reason_code) ||
    !["process", "skip", "blocked"].includes(String(value.planned_outcome))
  ) {
    return false;
  }
  const status = String(value.existing_result_match.status);
  const resolution = String(value.existing_result_match.resolution);
  const outcome = String(value.planned_outcome);
  const acceptedOutputCount =
    value.existing_result_match.accepted_output_count;
  const providerAuthorityStatus = String(
    value.provider_attempt_authority.status,
  );
  const providerAuthorityReason =
    value.provider_attempt_authority.reason_code;
  const attentionJobId = value.provider_attempt_authority.attention_job_id ?? null;
  if (
    status !== "no_match" &&
    (!isNonNegativeInteger(acceptedOutputCount) || acceptedOutputCount < 1)
  ) {
    return false;
  }
  const coherentDecision =
    (status === "no_match" && resolution === "not_required") ||
    (status !== "no_match" &&
      ["required", "reprocess"].includes(resolution));
  const coherentProviderAuthority =
    (providerAuthorityStatus === "available" &&
      providerAuthorityReason === null && attentionJobId === null) ||
    (providerAuthorityStatus === "blocked" &&
      [
        "equivalent_provider_work_in_flight",
        "equivalent_provider_outcome_unresolved",
      ].includes(String(providerAuthorityReason)) &&
      (attentionJobId === null ||
        (providerAuthorityReason === "equivalent_provider_outcome_unresolved" &&
          typeof attentionJobId === "string" &&
          /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(attentionJobId))));
  const existingResultAllowsProcessing =
    status === "no_match" || resolution === "reprocess";
  const coherentOutcome =
    outcome ===
    (existingResultAllowsProcessing &&
    providerAuthorityStatus === "available"
      ? "process"
      : "blocked");
  return (
    coherentDecision &&
    coherentProviderAuthority &&
    coherentOutcome &&
    value.source.name.length > 0 &&
    value.output_destination.name.length > 0
  );
}

function isMediaClip(value: unknown) {
  if (value === null) return true;
  return (
    isRecord(value) &&
    hasExactKeys(value, ["start_seconds", "end_seconds"]) &&
    (value.start_seconds === null || isNonNegativeInteger(value.start_seconds)) &&
    (value.end_seconds === null || isNonNegativeInteger(value.end_seconds)) &&
    (value.start_seconds !== null || value.end_seconds !== null) &&
    (value.end_seconds === null ||
      value.start_seconds === null ||
      value.end_seconds > value.start_seconds)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: string[]) {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return (
    actual.length === expected.length &&
    actual.every((key, index) => key === expected[index])
  );
}

function isNullableString(value: unknown) {
  return value === null || typeof value === "string";
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isNullableNonNegativeNumber(value: unknown) {
  return (
    value === null ||
    (typeof value === "number" && Number.isFinite(value) && value >= 0)
  );
}

export function makeIdempotencyKey() {
  return `batch-${crypto.randomUUID()}`;
}

export function mergeJobsWithBatchOrder(
  jobs: TranscriptionJob[],
  batchJobs: TranscriptionJob[],
) {
  if (batchJobs.length === 0) return jobs;
  const freshById = new Map(jobs.map((job) => [job.id, job]));
  const batchIds = new Set(batchJobs.map((job) => job.id));
  return [
    ...batchJobs.map((job) => freshById.get(job.id) ?? job),
    ...jobs.filter((job) => !batchIds.has(job.id)),
  ];
}
