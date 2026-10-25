import type { JobСтатус } from "./jobModel";
import { parseLongMediaPreflight, type LongMediaPreflight } from "./longMediaPreflight";

export type JobAttentionCandidate = { id: string; title: string | null; created_at: string };

export type OutputReconciliationResponse = {
  job_id: string;
  job_status: JobСтатус;
  available: boolean;
  counts: Record<string, number>;
  attention_candidates?: JobAttentionCandidate[];
  cases: {
    job_source_id: string;
    status: string;
    reason?: string | null;
    resolved: boolean;
    last_checked_at?: string | null;
  }[];
};

export type JobRetryResponse = {
  missing_provider_parts?: { source_id: string; part_index: number; start_seconds: number; end_seconds: number }[];
  long_duration_preflight?: LongMediaPreflight | null;
  job_id: string;
  job_status: JobСтатус;
  available: boolean;
  reason: string;
  attempt_count: number;
  max_attempts: number;
  missing_output_count: number;
  retry_safe_source_count: number;
  resumable_provider_part_count?: number;
  provider_total_part_count?: number;
  provider_failure_code?: string | null;
};

export type JobRetryState = {
  loading: boolean;
  posting: boolean;
  error: string;
  message: string;
  data: JobRetryResponse | null;
};

export type OutputReconciliationCheckResponse = {
  job_id: string;
  checked: number;
  resolved: number;
  unresolved: number;
  conflicts: number;
  unavailable?: number;
};

export type OutputReconciliationState = {
  loading: boolean;
  checking: boolean;
  error: string;
  message: string;
  data: OutputReconciliationResponse | null;
};

const JOB_STATUSES = new Set([
  "queued",
  "processing",
  "cancelled",
  "failed",
  "completed",
]);
const RETRY_REASONS = new Set([
  "full_provider_restore_available",
  "available",
  "partial_provider_resume_available",
  "partial_provider_restart_available",
  "job_not_failed",
  "cancelled",
  "completed",
  "attempt_limit_reached",
  "provider_outcome_uncertain",
  "provider_result_lost",
  "output_reconciliation_required",
  "legacy_or_unknown_execution_state",
  "prerequisites_unavailable",
  "non_retryable",
]);
const AVAILABLE_RETRY_REASONS = new Set([
  "full_provider_restore_available",
  "available",
  "partial_provider_resume_available",
  "partial_provider_restart_available",
]);
const RECONCILIATION_STATUSES = [
  "prepared",
  "creation_returned",
  "reconciliation_required",
  "resolved",
  "conflict",
] as const;

export function parseJobRetryResponse(
  candidate: unknown,
  jobId: string,
): JobRetryResponse | null {
  if (!isRecord(candidate)) return null;
  const missingParts = candidate.missing_provider_parts;
  if (missingParts !== undefined && (!Array.isArray(missingParts) || missingParts.length > 12800 || missingParts.some((part) =>
    !isRecord(part) || typeof part.source_id !== "string" || !part.source_id.trim() || part.source_id.length > 36 ||
    !Number.isInteger(part.part_index) || Number(part.part_index) < 0 || Number(part.part_index) >= 256 ||
    typeof part.start_seconds !== "number" || typeof part.end_seconds !== "number" ||
    !Number.isFinite(part.start_seconds) || !Number.isFinite(part.end_seconds) || !(0 <= part.start_seconds && part.start_seconds < part.end_seconds)
  ))) return null;
  if (Array.isArray(missingParts) && new Set(missingParts.map(part => `${part.source_id}:${part.part_index}`)).size !== missingParts.length) return null;
  const durationPreflight = parseLongMediaPreflight(candidate.long_duration_preflight);
  if (candidate.long_duration_preflight !== undefined && candidate.long_duration_preflight !== null && !durationPreflight) return null;
  const reason = candidate.reason;
  const resumableParts = optionalNonNegativeInteger(
    candidate.resumable_provider_part_count,
  );
  const totalParts = optionalNonNegativeInteger(
    candidate.provider_total_part_count,
  );
  const providerFailureCode = optionalNullableBoundedString(
    candidate.provider_failure_code,
    80,
  );
  const status = candidate.job_status;
  const missingOutputCount = candidate.missing_output_count;
  const retrySafeSourceCount = candidate.retry_safe_source_count;
  const noRecoveryWork =
    missingOutputCount === 0 &&
    retrySafeSourceCount === 0 &&
    (resumableParts ?? 0) === 0 &&
    (totalParts ?? 0) === 0 &&
    (providerFailureCode === undefined || providerFailureCode === null);
  if (
    boundedString(candidate.job_id, 36) !== jobId ||
    !JOB_STATUSES.has(String(status)) ||
    typeof candidate.available !== "boolean" ||
    !RETRY_REASONS.has(String(reason)) ||
    candidate.available !== AVAILABLE_RETRY_REASONS.has(String(reason)) ||
    !isNonNegativeInteger(candidate.attempt_count) ||
    !isPositiveInteger(candidate.max_attempts) ||
    candidate.attempt_count > candidate.max_attempts ||
    !isNonNegativeInteger(missingOutputCount) ||
    !isNonNegativeInteger(retrySafeSourceCount) ||
    retrySafeSourceCount > missingOutputCount ||
    resumableParts === null ||
    totalParts === null ||
    providerFailureCode === false ||
    (resumableParts ?? 0) > (totalParts ?? 0) ||
    !retryStatusReasonIsConsistent(String(status), String(reason)) ||
    (status !== "failed" && !noRecoveryWork) ||
    ((reason === "cancelled" || reason === "completed") && !noRecoveryWork) ||
    (candidate.available &&
      status === "failed" &&
      (missingOutputCount === 0 || retrySafeSourceCount !== missingOutputCount)) ||
    (reason === "available" &&
      status === "failed" &&
      ((resumableParts ?? 0) !== 0 ||
        (totalParts ?? 0) !== 0)) ||
    (reason === "full_provider_restore_available" &&
      (!(totalParts && totalParts > 1) || resumableParts !== totalParts)) ||
    (reason === "partial_provider_resume_available" &&
      (!(resumableParts && totalParts) || resumableParts > totalParts)) ||
    (reason === "partial_provider_restart_available" &&
      ((resumableParts ?? 0) !== 0 || !(totalParts && totalParts > 0)))
  ) {
    return null;
  }
  return {
    ...(candidate.long_duration_preflight !== undefined ? { long_duration_preflight: durationPreflight } : {}),
    job_id: jobId,
    ...(Array.isArray(missingParts) ? { missing_provider_parts: missingParts.map(part => ({source_id: part.source_id as string, part_index: part.part_index as number, start_seconds: part.start_seconds as number, end_seconds: part.end_seconds as number})) } : {}),
    job_status: candidate.job_status as JobRetryResponse["job_status"],
    available: candidate.available,
    reason: reason as string,
    attempt_count: candidate.attempt_count,
    max_attempts: candidate.max_attempts,
    missing_output_count: missingOutputCount,
    retry_safe_source_count: retrySafeSourceCount,
    ...(resumableParts !== undefined
      ? { resumable_provider_part_count: resumableParts }
      : {}),
    ...(totalParts !== undefined
      ? { provider_total_part_count: totalParts }
      : {}),
    ...(providerFailureCode !== undefined
      ? { provider_failure_code: providerFailureCode }
      : {}),
  };
}

export function parseOutputReconciliationResponse(
  candidate: unknown,
  jobId: string,
): OutputReconciliationResponse | null {
  if (!isRecord(candidate)) return null;
  const rawCounts = candidate.counts;
  if (
    boundedString(candidate.job_id, 36) !== jobId ||
    !JOB_STATUSES.has(String(candidate.job_status)) ||
    typeof candidate.available !== "boolean" ||
    !isRecord(rawCounts) ||
    Object.keys(rawCounts).length !== RECONCILIATION_STATUSES.length ||
    !RECONCILIATION_STATUSES.every(
      (status) => isNonNegativeInteger(rawCounts[status]),
    ) ||
    !Array.isArray(candidate.cases)
  ) {
    return null;
  }
  const cases: OutputReconciliationResponse["cases"] = [];
  for (const rawCase of candidate.cases) {
    if (!isRecord(rawCase)) return null;
    const jobSourceId = boundedString(rawCase.job_source_id, 36);
    const status = rawCase.status;
    const reason = optionalNullableBoundedString(rawCase.reason, 80);
    const preparedAt = optionalNullableIsoDate(rawCase.prepared_at);
    const lastCheckedAt = optionalNullableIsoDate(rawCase.last_checked_at);
    const resolvedAt = optionalNullableIsoDate(rawCase.resolved_at);
    if (
      !jobSourceId ||
      !RECONCILIATION_STATUSES.includes(
        status as (typeof RECONCILIATION_STATUSES)[number],
      ) ||
      reason === false ||
      typeof preparedAt !== "string" ||
      lastCheckedAt === false ||
      resolvedAt === false ||
      typeof rawCase.resolved !== "boolean" ||
      rawCase.resolved !== (status === "resolved") ||
      (status === "resolved") !== (typeof resolvedAt === "string")
    ) {
      return null;
    }
    cases.push({
      job_source_id: jobSourceId,
      status: status as string,
      ...(reason !== undefined ? { reason } : {}),
      resolved: rawCase.resolved,
      ...(lastCheckedAt !== undefined ? { last_checked_at: lastCheckedAt } : {}),
    });
  }
  const counts: Record<string, number> = {};
  for (const status of RECONCILIATION_STATUSES) {
    counts[status] = rawCounts[status] as number;
  }
  if (
    new Set(cases.map((item) => item.job_source_id)).size !== cases.length ||
    Object.values(counts).reduce((total, value) => total + value, 0) !==
      cases.length ||
    RECONCILIATION_STATUSES.some(
      (status) =>
        counts[status] !== cases.filter((item) => item.status === status).length,
    ) ||
    candidate.available !==
      ((candidate.job_status === "failed" ||
        candidate.job_status === "cancelled") &&
        cases.some((item) =>
          [
            "reconciliation_required",
            "creation_returned",
            "conflict",
          ].includes(item.status),
        ))
  ) {
    return null;
  }
  const attentionCandidates: JobAttentionCandidate[] = [];
  if (candidate.attention_candidates !== undefined) {
    if (!Array.isArray(candidate.attention_candidates) || candidate.attention_candidates.length > 50) return null;
    for (const item of candidate.attention_candidates) {
      if (!isRecord(item)) return null;
      const id = boundedString(item.id, 36);
      const title = optionalNullableBoundedString(item.title, 300);
      const createdAt = optionalNullableIsoDate(item.created_at);
      if (!id || id === jobId || title === false || title === undefined || typeof createdAt !== "string") return null;
      attentionCandidates.push({ id, title, created_at: createdAt });
    }
    if (new Set(attentionCandidates.map((item) => item.id)).size !== attentionCandidates.length) return null;
  }
  return {
    job_id: jobId,
    job_status:
      candidate.job_status as OutputReconciliationResponse["job_status"],
    available: candidate.available,
    counts,
    cases,
    ...(candidate.attention_candidates !== undefined ? { attention_candidates: attentionCandidates } : {}),
  };
}

export function parseOutputReconciliationCheckResponse(
  candidate: unknown,
  jobId: string,
): OutputReconciliationCheckResponse | null {
  if (
    !isRecord(candidate) ||
    boundedString(candidate.job_id, 36) !== jobId ||
    !isNonNegativeInteger(candidate.checked) ||
    !isNonNegativeInteger(candidate.resolved) ||
    !isNonNegativeInteger(candidate.unresolved) ||
    !isNonNegativeInteger(candidate.conflicts) ||
    (candidate.unavailable !== undefined && !isNonNegativeInteger(candidate.unavailable)) ||
    candidate.checked !==
      candidate.resolved + candidate.unresolved + candidate.conflicts + (typeof candidate.unavailable === "number" ? candidate.unavailable : 0)
  ) {
    return null;
  }
  return {
    job_id: jobId,
    checked: candidate.checked,
    resolved: candidate.resolved,
    unresolved: candidate.unresolved,
    conflicts: candidate.conflicts,
    ...(typeof candidate.unavailable === "number" ? { unavailable: candidate.unavailable } : {}),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function boundedString(value: unknown, maxLength: number): string | null {
  return typeof value === "string" &&
    value.trim().length > 0 &&
    value.length <= maxLength
    ? value
    : null;
}

function isNonNegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) > 0;
}

function optionalNonNegativeInteger(value: unknown): number | null | undefined {
  if (value === undefined) return undefined;
  return isNonNegativeInteger(value) ? value : null;
}

function optionalNullableBoundedString(
  value: unknown,
  maxLength: number,
): string | null | false | undefined {
  if (value === undefined) return undefined;
  if (value === null) return null;
  return typeof value === "string" &&
    value.trim().length > 0 &&
    value.length <= maxLength
    ? value
    : false;
}

function optionalNullableIsoDate(
  value: unknown,
): string | null | false | undefined {
  if (value === undefined) return undefined;
  if (value === null) return null;
  return typeof value === "string" &&
    value.length > 0 &&
    value.length <= 64 &&
    Number.isFinite(Date.parse(value))
    ? value
    : false;
}

function retryStatusReasonIsConsistent(status: string, reason: string) {
  if (status === "queued") return reason === "available";
  if (status === "processing") {
    return reason === "job_not_failed" || reason === "cancelled";
  }
  if (status === "cancelled") return reason === "cancelled";
  if (status === "completed") return reason === "completed";
  return status === "failed" && reason !== "job_not_failed";
}

export function retryUnavailableLabel(reason: string | undefined) {
  if (reason === "full_provider_restore_available") return "";
  if (reason === "provider_outcome_uncertain") {
    return "Повтор недоступен: результат внешнего вызова не определён";
  }
  if (reason === "output_reconciliation_required") {
    return "Требуется проверка созданного документа";
  }
  if (reason === "attempt_limit_reached") {
    return "Достигнут предел попыток";
  }
  if (reason && reason !== "available") return "Повтор недоступен";
  return "";
}

export function isPartialProviderResume(data: JobRetryResponse | null | undefined) {
  return data?.reason === "partial_provider_resume_available";
}

export function isFullProviderRestore(data: JobRetryResponse | null | undefined) {
  return data?.reason === "full_provider_restore_available";
}

export function isPartialProviderRestart(data: JobRetryResponse | null | undefined) {
  return data?.reason === "partial_provider_restart_available";
}

export function providerFailureLabel(code: string | null | undefined) {
  const labels: Record<string, string> = {
    provider_authentication_rejected: "ElevenLabs отклонил API-ключ",
    provider_payment_required:
      "ElevenLabs требует доступного API-баланса или оплаты",
    provider_scope_rejected:
      "ElevenLabs запретил Speech to Text для этого ключа, тарифа или IP",
    provider_request_rejected: "ElevenLabs отклонил эту часть файла",
    provider_rate_limited: "ElevenLabs ограничил частоту запросов",
    provider_timeout: "ElevenLabs не ответил вовремя",
    provider_unavailable: "ElevenLabs временно недоступен",
    malformed_provider_response: "ElevenLabs вернул некорректный ответ",
  };
  return code ? labels[code] ?? "Не удалось обработать следующую часть" : "Не удалось обработать следующую часть";
}
