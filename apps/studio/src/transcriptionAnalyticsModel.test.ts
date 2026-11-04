import { describe, expect, it } from "vitest";
import { parseTranscriptionAnalytics } from "./transcriptionAnalyticsModel";

it("accepts legacy and actual Yandex model counts but rejects ambiguous partial extensions", () => {
  expect(parseTranscriptionAnalytics(valid)).not.toBeNull();
  const updated = structuredClone(valid);
  const provider_model = { elevenlabs_scribe_v2: 1, yandex_general: 1, yandex_deferred_general: 1, unknown: 0 };
  expect(parseTranscriptionAnalytics({ ...updated, configuration: { ...updated.configuration, provider_model } })).not.toBeNull();
  expect(parseTranscriptionAnalytics({ ...updated, configuration: { ...updated.configuration, provider_model: { ...valid.configuration.provider_model, yandex_general: 0 } } })).toBeNull();
  expect(parseTranscriptionAnalytics({ ...updated, configuration: { ...updated.configuration, provider_model: { ...provider_model, yandex_general: -1 } } })).toBeNull();
});

const valid = {
  scope: "project_all_time",
  totals: { jobs: 3, sources: 4, outputs: 1 },
  outcomes: {
    queued: 1,
    processing: 0,
    completed: 1,
    failed: 1,
    cancelled: 0,
  },
  success: {
    successful_jobs: 1,
    terminal_jobs: 2,
    percentage: 50,
  },
  configuration: {
    provider_model: { elevenlabs_scribe_v2: 2, unknown: 1 },
    language_mode: { ru: 1, en: 1, detect: 1, other: 0 },
    diarization: { enabled: 1, disabled: 2 },
  },
  usage_cost: {
    confirmed_billed_duration_seconds: 3600,
    confirmed_provider_cost: "0.22000000",
    currency: "USD",
    cost_basis: "confirmed_audio_duration_x_rate_snapshot",
    complete_jobs: 1,
    uncertain_jobs: 1,
    unavailable_jobs: 1,
    in_progress_jobs: 0,
  },
  durations: {
    queue: {
      sample_count: 2,
      average_seconds: 15,
      p50_seconds: 10,
      p95_seconds: 20,
    },
    processing: {
      sample_count: 2,
      average_seconds: 75,
      p50_seconds: 60,
      p95_seconds: 90,
    },
    provider_processing: {
      sample_count: 2,
      average_seconds: 25,
      p50_seconds: 20,
      p95_seconds: 30,
    },
    post_provider_output: {
      sample_count: 0,
      average_seconds: null,
      p50_seconds: null,
      p95_seconds: null,
    },
  },
};

it("accepts explicit local model counts and rejects a negative count", () => {
  const provider_model = { elevenlabs_scribe_v2: 0, yandex_general: 0, yandex_deferred_general: 0,
    mistral_voxtral_small_transcribe_3: 0, gemini_35_transcribe: 0, tbank_default: 0, nemotron_35_transcribe_local: 3, unknown: 0 };
  const value = { ...valid, configuration: { ...valid.configuration, provider_model } };
  expect(parseTranscriptionAnalytics(value)?.configuration.provider_model.nemotron_35_transcribe_local).toBe(3);
  expect(parseTranscriptionAnalytics({ ...value, configuration: { ...value.configuration, provider_model: { ...provider_model, nemotron_35_transcribe_local: -1 } } })).toBeNull();
});

describe("transcription analytics parser", () => {
  it("accepts the exact aggregate contract", () => {
    expect(parseTranscriptionAnalytics(valid)).toEqual(valid);
    const sinceReset = { ...valid, scope: "project_since_reset" };
    expect(parseTranscriptionAnalytics(sinceReset)).toEqual(sinceReset);
  });

  it("fails closed on private extras and inconsistent counts", () => {
    expect(
      parseTranscriptionAnalytics({ ...valid, project_id: "private-project" }),
    ).toBeNull();
    expect(
      parseTranscriptionAnalytics({ ...valid, scope: "owner_all_time" }),
    ).toBeNull();
    expect(
      parseTranscriptionAnalytics({
        ...valid,
        totals: { ...valid.totals, jobs: 4 },
      }),
    ).toBeNull();
    expect(
      parseTranscriptionAnalytics({
        ...valid,
        success: { ...valid.success, percentage: 100 },
      }),
    ).toBeNull();
    expect(
      parseTranscriptionAnalytics({
        ...valid,
        success: { ...valid.success, terminal_jobs: 3 },
      }),
    ).toBeNull();
    expect(
      parseTranscriptionAnalytics({
        ...valid,
        durations: {
          ...valid.durations,
          queue: {
            ...valid.durations.queue,
            provider_request_started_at: "private-timestamp",
          },
        },
      }),
    ).toBeNull();
  });

  it("rejects incomplete or invalid duration summaries", () => {
    expect(
      parseTranscriptionAnalytics({
        ...valid,
        durations: {
          ...valid.durations,
          queue: {
            sample_count: 0,
            average_seconds: 1,
            p50_seconds: null,
            p95_seconds: null,
          },
        },
      }),
    ).toBeNull();
    expect(
      parseTranscriptionAnalytics({
        ...valid,
        durations: {
          ...valid.durations,
          queue: {
            ...valid.durations.queue,
            p95_seconds: -1,
          },
        },
      }),
    ).toBeNull();
  });

  it("rejects fabricated or malformed provider accounting", () => {
    expect(
      parseTranscriptionAnalytics({
        ...valid,
        usage_cost: {
          ...valid.usage_cost,
          confirmed_provider_cost: "about 0.22",
        },
      }),
    ).toBeNull();
    expect(
      parseTranscriptionAnalytics({
        ...valid,
        usage_cost: {
          ...valid.usage_cost,
          complete_jobs: 3,
        },
      }),
    ).toBeNull();
  });
});
