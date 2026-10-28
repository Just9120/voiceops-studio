import type { JobСтатус } from "./jobModel";
import { parseWorkProgress, type WorkProgress } from "./WorkProgress";

export const JOB_PROGRESS_STAGE_KEYS = [
  "preparation",
  "audio_extraction",
  "splitting",
  "provider_processing",
  "part_merge",
  "google_docs_output",
] as const;

export type JobProgressStageKey = (typeof JOB_PROGRESS_STAGE_KEYS)[number];
export type JobProgressStageStatus =
  | "pending"
  | "active"
  | "completed"
  | "failed"
  | "cancelled"
  | "not_applicable";
export type JobProgressStage = {
  key: JobProgressStageKey;
  status: JobProgressStageStatus;
  applicability: "required" | "conditional" | "not_applicable";
};
export type JobSourceProgress = {
  position: number;
  name: string;
  status:
    | "queued"
    | "processing"
    | "completed"
    | "failed"
    | "cancelled"
    | "skipped";
  provider_parts: {
    completed: number;
    total: number;
  } | null;
  stages: JobProgressStage[];
};
export type JobProgress = {
  work?: WorkProgress | null;
  job_id: string;
  job_status: JobСтатус;
  tracking_precision: "checkpoint";
  completed_source_count: number;
  total_source_count: number;
  active_source_position: number | null;
  current_stage: JobProgressStageKey | null;
  sources: JobSourceProgress[];
};
export type ProjectJobProgressResponse = {
  jobs: JobProgress[];
  truncated: boolean;
  limit: number;
};
export type JobProgressState = {
  loading: boolean;
  error: string;
  data: JobProgress | null;
};

const TERMINAL_JOB_STATUSES = new Set<JobСтатус>([
  "completed",
  "failed",
  "cancelled",
]);

export function confirmedProgressPercent(progress: JobProgress) {
  const applicableStages = progress.sources.flatMap((source) =>
    source.stages
      .filter((stage) => stage.status !== "not_applicable")
      .map((stage) => ({ source, stage })),
  );
  if (applicableStages.length === 0) {
    return progress.job_status === "completed" ? 100 : 0;
  }
  const confirmedStageUnits = applicableStages.reduce(
    (total, { source, stage }) => {
      if (stage.status === "completed") return total + 1;
      if (
        stage.key === "provider_processing" &&
        stage.status === "active" &&
        source.provider_parts
      ) {
        return (
          total +
          source.provider_parts.completed / source.provider_parts.total
        );
      }
      return total;
    },
    0,
  );
  return Math.floor((confirmedStageUnits / applicableStages.length) * 100);
}

export function terminalProgressState(
  state: JobProgressState | undefined,
  jobStatus: JobСтатус,
): JobProgressState | undefined {
  if (!state?.data || !TERMINAL_JOB_STATUSES.has(jobStatus)) return state;
  const terminalStageStatus =
    jobStatus === "failed" ? "failed" : jobStatus === "cancelled" ? "cancelled" : null;
  const sources = state.data.sources.map((source) => {
    if (source.status === "skipped") return source;
    if (jobStatus === "completed") {
      return {
        ...source,
        status: "completed" as const,
        stages: source.stages.map((stage) => ({
          ...stage,
          status:
            stage.status === "not_applicable"
              ? ("not_applicable" as const)
              : ("completed" as const),
        })),
      };
    }
    return {
      ...source,
      status:
        source.status === "processing"
          ? (jobStatus as "failed" | "cancelled")
          : source.status,
      stages: source.stages.map((stage) => ({
        ...stage,
        status:
          stage.status === "active" && terminalStageStatus
            ? terminalStageStatus
            : stage.status,
      })),
    };
  });
  return {
    ...state,
    loading: false,
    data: {
      ...state.data,
      job_status: jobStatus,
      completed_source_count:
        jobStatus === "completed"
          ? state.data.total_source_count
          : state.data.completed_source_count,
      current_stage: jobStatus === "completed" ? null : state.data.current_stage,
      sources,
    },
  };
}

export function updateRequestedProgressStates(
  current: Record<string, JobProgressState>,
  requestedIds: readonly string[],
  update: (jobId: string, previous: JobProgressState | undefined) => JobProgressState,
) {
  const next = { ...current };
  for (const jobId of requestedIds) next[jobId] = update(jobId, current[jobId]);
  return next;
}

const STAGE_STATUSES = new Set<JobProgressStageStatus>([
  "pending",
  "active",
  "completed",
  "failed",
  "cancelled",
  "not_applicable",
]);
const SOURCE_STATUSES = new Set<JobSourceProgress["status"]>([
  "queued",
  "processing",
  "completed",
  "failed",
  "cancelled",
  "skipped",
]);
const APPLICABILITY = new Set<JobProgressStage["applicability"]>([
  "required",
  "conditional",
  "not_applicable",
]);

export function parseProjectJobProgressResponse(
  value: unknown,
): ProjectJobProgressResponse | null {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["jobs", "limit", "truncated"]) ||
    !Array.isArray(value.jobs) ||
    typeof value.truncated !== "boolean" ||
    !Number.isSafeInteger(value.limit) ||
    (value.limit as number) < 0 ||
    (value.limit as number) > 100 ||
    value.jobs.length > (value.limit as number)
  )
    return null;
  const parsed: JobProgress[] = [];
  const jobIds = new Set<string>();
  for (const item of value.jobs) {
    const progress = parseJobProgress(item);
    if (!progress || jobIds.has(progress.job_id)) return null;
    jobIds.add(progress.job_id);
    parsed.push(progress);
  }
  return {
    jobs: parsed,
    truncated: value.truncated,
    limit: value.limit as number,
  };
}

function parseJobProgress(value: unknown): JobProgress | null {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "job_id",
      "job_status",
      "tracking_precision",
      "completed_source_count",
      "total_source_count",
      "active_source_position",
      "current_stage",
      "sources",
      ...(Object.hasOwn(value, "work") ? ["work"] : []),
    ]) ||
    typeof value.job_id !== "string" ||
    value.job_id.length === 0 ||
    !["queued", "processing"].includes(String(value.job_status)) ||
    value.tracking_precision !== "checkpoint" ||
    !isNonNegativeInteger(value.completed_source_count) ||
    !isNonNegativeInteger(value.total_source_count) ||
    value.completed_source_count > value.total_source_count ||
    !isNullableNonNegativeInteger(value.active_source_position) ||
    !isNullableStageKey(value.current_stage) ||
    !Array.isArray(value.sources)
  ) {
    return null;
  }
  const sources: JobSourceProgress[] = [];
  const positions = new Set<number>();
  for (const source of value.sources) {
    const parsed = parseSourceProgress(source);
    if (!parsed || positions.has(parsed.position)) return null;
    positions.add(parsed.position);
    sources.push(parsed);
  }
  if (
    value.active_source_position !== null &&
    !positions.has(value.active_source_position)
  )
    return null;
  if (
    value.total_source_count !==
    sources.filter((source) => source.status !== "skipped").length
  )
    return null;
  const activeStages = sources.flatMap((source) =>
    source.stages.filter((stage) =>
      ["active", "failed", "cancelled"].includes(stage.status),
    ),
  );
  if (
    (value.current_stage === null && activeStages.length > 0) ||
    (value.current_stage !== null &&
      (activeStages.length !== 1 || activeStages[0].key !== value.current_stage))
  )
    return null;
  if (value.work !== undefined && value.work !== null && !parseWorkProgress(value.work)) return null;
  return value as JobProgress;
}

function parseSourceProgress(value: unknown): JobSourceProgress | null {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "position",
      "name",
      "status",
      "provider_parts",
      "stages",
    ]) ||
    !isNonNegativeInteger(value.position) ||
    typeof value.name !== "string" ||
    value.name.length === 0 ||
    !SOURCE_STATUSES.has(value.status as JobSourceProgress["status"]) ||
    !isProviderParts(value.provider_parts) ||
    !Array.isArray(value.stages) ||
    value.stages.length !== JOB_PROGRESS_STAGE_KEYS.length
  )
    return null;
  const stages: JobProgressStage[] = [];
  for (const [index, stage] of value.stages.entries()) {
    if (
      !isRecord(stage) ||
      !hasExactKeys(stage, ["key", "status", "applicability"]) ||
      stage.key !== JOB_PROGRESS_STAGE_KEYS[index] ||
      !STAGE_STATUSES.has(stage.status as JobProgressStageStatus) ||
      !APPLICABILITY.has(
        stage.applicability as JobProgressStage["applicability"],
      ) ||
      (stage.applicability === "not_applicable") !==
        (stage.status === "not_applicable")
    )
      return null;
    stages.push(stage as JobProgressStage);
  }
  return { ...value, stages } as JobSourceProgress;
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

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isNullableNonNegativeInteger(value: unknown) {
  return value === null || isNonNegativeInteger(value);
}

function isProviderParts(
  value: unknown,
): value is JobSourceProgress["provider_parts"] {
  if (value === null) return true;
  return (
    isRecord(value) &&
    hasExactKeys(value, ["completed", "total"]) &&
    isNonNegativeInteger(value.completed) &&
    isNonNegativeInteger(value.total) &&
    value.total > 0 &&
    value.completed <= value.total
  );
}

function isNullableStageKey(value: unknown): value is JobProgressStageKey | null {
  return (
    value === null ||
    JOB_PROGRESS_STAGE_KEYS.includes(value as JobProgressStageKey)
  );
}
