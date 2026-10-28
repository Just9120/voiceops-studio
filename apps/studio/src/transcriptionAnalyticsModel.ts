export type AnalyticsDurationSummary = {
  sample_count: number;
  average_seconds: number | null;
  p50_seconds: number | null;
  p95_seconds: number | null;
};

export type TranscriptionAnalytics = {
  scope: "project_all_time" | "project_since_reset";
  totals: {
    jobs: number;
    sources: number;
    outputs: number;
  };
  outcomes: {
    queued: number;
    processing: number;
    completed: number;
    failed: number;
    cancelled: number;
  };
  success: {
    successful_jobs: number;
    terminal_jobs: number;
    percentage: number | null;
  };
  configuration: {
    provider_model: {
      elevenlabs_scribe_v2: number;
      yandex_general?: number;
      mistral_voxtral_small_transcribe_3?: number;
      gemini_35_transcribe?: number;
      tbank_default?: number;
      yandex_deferred_general?: number;
      unknown: number;
    };
    language_mode: {
      ru: number;
      en: number;
      detect: number;
      other: number;
    };
    diarization: {
      enabled: number;
      disabled: number;
    };
  };
  usage_cost: {
    confirmed_billed_duration_seconds: number;
    confirmed_provider_cost: string;
    currency: "USD";
    cost_basis: "confirmed_audio_duration_x_rate_snapshot";
    complete_jobs: number;
    uncertain_jobs: number;
    unavailable_jobs: number;
    in_progress_jobs: number;
  };
  durations: {
    queue: AnalyticsDurationSummary;
    processing: AnalyticsDurationSummary;
    provider_processing: AnalyticsDurationSummary;
    post_provider_output: AnalyticsDurationSummary;
  };
};

const EXACT_KEYS = {
  root: [
    "scope",
    "totals",
    "outcomes",
    "success",
    "configuration",
    "usage_cost",
    "durations",
  ],
  totals: ["jobs", "sources", "outputs"],
  outcomes: ["queued", "processing", "completed", "failed", "cancelled"],
  success: ["successful_jobs", "terminal_jobs", "percentage"],
  configuration: ["provider_model", "language_mode", "diarization"],
  providerModel: ["elevenlabs_scribe_v2", "unknown"],
  providerModelExtended: ["elevenlabs_scribe_v2", "yandex_general", "yandex_deferred_general", "unknown"],
  providerModelExpanded: ["elevenlabs_scribe_v2", "yandex_general", "yandex_deferred_general", "mistral_voxtral_small_transcribe_3", "gemini_35_transcribe", "tbank_default", "unknown"],
  languageMode: ["ru", "en", "detect", "other"],
  diarization: ["enabled", "disabled"],
  usageCost: [
    "confirmed_billed_duration_seconds",
    "confirmed_provider_cost",
    "currency",
    "cost_basis",
    "complete_jobs",
    "uncertain_jobs",
    "unavailable_jobs",
    "in_progress_jobs",
  ],
  durations: [
    "queue",
    "processing",
    "provider_processing",
    "post_provider_output",
  ],
  durationSummary: [
    "sample_count",
    "average_seconds",
    "p50_seconds",
    "p95_seconds",
  ],
} as const;

export function parseTranscriptionAnalytics(
  value: unknown,
): TranscriptionAnalytics | null {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, EXACT_KEYS.root) ||
    (value.scope !== "project_all_time" &&
      value.scope !== "project_since_reset") ||
    !isCountRecord(value.totals, EXACT_KEYS.totals) ||
    !isCountRecord(value.outcomes, EXACT_KEYS.outcomes) ||
    !isRecord(value.success) ||
    !hasExactKeys(value.success, EXACT_KEYS.success) ||
    !isNonNegativeInteger(value.success.successful_jobs) ||
    !isNonNegativeInteger(value.success.terminal_jobs) ||
    !isPercentageOrNull(value.success.percentage) ||
    !isRecord(value.configuration) ||
    !hasExactKeys(value.configuration, EXACT_KEYS.configuration) ||
    !(isCountRecord(value.configuration.provider_model, EXACT_KEYS.providerModel) ||
      isCountRecord(value.configuration.provider_model, EXACT_KEYS.providerModelExtended) || isCountRecord(value.configuration.provider_model, EXACT_KEYS.providerModelExpanded)) ||
    !isCountRecord(
      value.configuration.language_mode,
      EXACT_KEYS.languageMode,
    ) ||
    !isCountRecord(
      value.configuration.diarization,
      EXACT_KEYS.diarization,
    ) ||
    !isRecord(value.usage_cost) ||
    !hasExactKeys(value.usage_cost, EXACT_KEYS.usageCost) ||
    !isNonNegativeFiniteNumber(
      value.usage_cost.confirmed_billed_duration_seconds,
    ) ||
    typeof value.usage_cost.confirmed_provider_cost !== "string" ||
    !/^(0|[1-9][0-9]*)[.][0-9]{8}$/.test(
      value.usage_cost.confirmed_provider_cost,
    ) ||
    value.usage_cost.currency !== "USD" ||
    value.usage_cost.cost_basis !==
      "confirmed_audio_duration_x_rate_snapshot" ||
    !isNonNegativeInteger(value.usage_cost.complete_jobs) ||
    !isNonNegativeInteger(value.usage_cost.uncertain_jobs) ||
    !isNonNegativeInteger(value.usage_cost.unavailable_jobs) ||
    !isNonNegativeInteger(value.usage_cost.in_progress_jobs) ||
    !isRecord(value.durations) ||
    !hasExactKeys(value.durations, EXACT_KEYS.durations)
  ) {
    return null;
  }
  for (const key of EXACT_KEYS.durations) {
    if (!isDurationSummary(value.durations[key])) return null;
  }
  if (
    sumRecord(value.outcomes) !== value.totals.jobs ||
    sumRecord(value.configuration.provider_model) !== value.totals.jobs ||
    sumRecord(value.configuration.language_mode) !== value.totals.jobs ||
    sumRecord(value.configuration.diarization) !== value.totals.jobs ||
    value.usage_cost.complete_jobs +
      value.usage_cost.uncertain_jobs +
      value.usage_cost.unavailable_jobs +
      value.usage_cost.in_progress_jobs !==
      value.totals.jobs
  ) {
    return null;
  }
  const terminalJobs =
    value.outcomes.completed +
    value.outcomes.failed +
    value.outcomes.cancelled;
  const expectedPercentage =
    terminalJobs > 0
      ? Math.round((value.outcomes.completed / terminalJobs) * 1000) / 10
      : null;
  if (
    value.success.successful_jobs !== value.outcomes.completed ||
    value.success.terminal_jobs !== terminalJobs ||
    value.success.percentage !== expectedPercentage
  ) {
    return null;
  }
  return value as TranscriptionAnalytics;
}

function isDurationSummary(value: unknown): value is AnalyticsDurationSummary {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, EXACT_KEYS.durationSummary) ||
    !isNonNegativeInteger(value.sample_count)
  ) {
    return false;
  }
  const values = [
    value.average_seconds,
    value.p50_seconds,
    value.p95_seconds,
  ];
  if (value.sample_count === 0) return values.every((item) => item === null);
  return values.every(isNonNegativeFiniteNumber);
}

function isCountRecord(
  value: unknown,
  keys: readonly string[],
): value is Record<string, number> {
  return (
    isRecord(value) &&
    hasExactKeys(value, keys) &&
    keys.every((key) => isNonNegativeInteger(value[key]))
  );
}

function sumRecord(value: Record<string, unknown>) {
  return Object.values(value).reduce<number>(
    (total, item) => total + (typeof item === "number" ? item : 0),
    0,
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
) {
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

function isNonNegativeFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function isPercentageOrNull(value: unknown): value is number | null {
  return (
    value === null ||
    (isNonNegativeFiniteNumber(value) && value <= 100)
  );
}
