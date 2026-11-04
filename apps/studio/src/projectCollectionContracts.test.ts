import { describe, expect, it } from "vitest";
import {
  parseJobDetailResponse,
  parseJobOutputsResponse,
  parseJobSummaryResponse,
  parseProjectJobCollection,
  parseProjectJobPage,
  parseProjectSourceCollection,
  parseProjectSourcePage,
} from "./projectCollectionContracts";

const source = {
  id: "source-safe",
  project_id: "project-safe",
  source_type: "google_drive",
  original_filename: "safe.mp3",
  mime_type: "audio/mpeg",
  size_bytes: 1234,
  drive_file_url: "https://drive.google.com/file/d/safe/view",
  upload_status: "uploaded",
  uploaded_at: "2026-08-14T10:00:00Z",
  source_created_at: null,
  source_created_at_provenance: null,
  expires_at: null,
  deleted_at: null,
  delete_reason: null,
  created_at: "2026-08-14T09:00:00Z",
  updated_at: "2026-08-14T10:00:00Z",
};

const job = {
  id: "job-safe",
  project_id: "project-safe",
  status: "processing",
  title: "Safe job",
  provider: "elevenlabs",
  language_mode: "ru",
  diarization_enabled: true,
  media_clip: null,
  terminal_dismissed_at: null,
  source_count: 1,
  created_at: "2026-08-14T09:00:00Z",
  updated_at: "2026-08-14T10:00:00Z",
  cancelled_at: null,
  cancel_requested_at: null,
  attempt_count: 1,
  started_at: "2026-08-14T09:01:00Z",
  finished_at: null,
  error_code: null,
  error_message: null,
  output_folder: {
    name: "Safe folder",
    web_view_url: "https://drive.google.com/drive/folders/safe",
  },
};

const usageCost = {
  accounting_status: "complete",
  confirmed_billed_duration_seconds: 12.612,
  confirmed_provider_cost: "0.00077073",
  currency: "USD",
  cost_basis: "confirmed_audio_duration_x_rate_snapshot",
  rate_snapshot: {
    rate_per_hour: "0.220000",
    currency: "USD",
    effective_date: "2026-08-30",
    source: "elevenlabs_public_api_pricing",
  },
} as const;

it("preserves a local job target across collection and detail parsing", () => {
  const local_execution = { device_id: "00000000-0000-4000-8000-000000000001", device_name: "Домашний ПК", result_accepted: true };
  expect(parseJobSummaryResponse({ ...job, provider: "nemotron", local_execution }, "project-safe", "job-safe"))
    .toMatchObject({ provider: "nemotron", local_execution });
  expect(parseProjectJobCollection({ jobs: [{ ...job, provider: "nemotron", local_execution: { ...local_execution, device_name: {} } }] }, "project-safe"))
    .toBeNull();
});

describe("project collection contracts", () => {
  it("validates bounded signed page envelopes", () => {
    const cursor = "signed_cursor-1";
    expect(
      parseProjectSourcePage(
        { sources: [source], next_cursor: cursor, page_size: 1 },
        "project-safe",
      ),
    ).toEqual({ items: [source], nextCursor: cursor, pageSize: 1 });
    expect(
      parseProjectJobPage(
        { jobs: [job], next_cursor: null, page_size: 50 },
        "project-safe",
      ),
    ).toEqual({ items: [job], nextCursor: null, pageSize: 50 });
    expect(
      parseProjectSourcePage(
        { sources: [source], next_cursor: "unsafe cursor", page_size: 1 },
        "project-safe",
      ),
    ).toBeNull();
    expect(
      parseProjectSourcePage(
        { sources: [source], next_cursor: cursor, page_size: 2 },
        "project-safe",
      ),
    ).toBeNull();
    expect(
      parseProjectJobPage(
        { jobs: [job], next_cursor: null, page_size: 101 },
        "project-safe",
      ),
    ).toBeNull();
  });

  it("reconstructs safe source fields and discards private extras", () => {
    const parsed = parseProjectSourceCollection(
      {
        sources: [
          {
            ...source,
            drive_file_id: "private-drive-id",
            s3_object_key: "private-storage-key",
          },
        ],
        raw_page: "private-page",
      },
      "project-safe",
    );

    expect(parsed).toEqual([source]);
    expect(parsed?.[0]).not.toHaveProperty("drive_file_id");
    expect(parsed?.[0]).not.toHaveProperty("s3_object_key");
  });

  it("rejects cross-project, duplicate, and malformed source rows", () => {
    expect(
      parseProjectSourceCollection(
        { sources: [{ ...source, project_id: "project-other" }] },
        "project-safe",
      ),
    ).toBeNull();
    expect(
      parseProjectSourceCollection({ sources: [source, source] }, "project-safe"),
    ).toBeNull();
    expect(
      parseProjectSourceCollection(
        { sources: [{ ...source, upload_status: "private" }] },
        "project-safe",
      ),
    ).toBeNull();
    expect(
      parseProjectSourceCollection(
        {
          sources: [
            {
              ...source,
              source_created_at: "2025-12-03T12:22:32Z",
              source_created_at_provenance: null,
            },
          ],
        },
        "project-safe",
      ),
    ).toBeNull();
  });

  it("accepts only paired authoritative source creation metadata", () => {
    const parsed = parseProjectSourceCollection(
      {
        sources: [
          {
            ...source,
            source_created_at: "2025-12-03T12:22:32Z",
            source_created_at_provenance: "google_drive_created_time",
          },
        ],
      },
      "project-safe",
    );

    expect(parsed?.[0].source_created_at).toBe("2025-12-03T12:22:32Z");
    expect(parsed?.[0].source_created_at_provenance).toBe(
      "google_drive_created_time",
    );
  });

  it("reconstructs safe job fields and discards private extras", () => {
    const parsed = parseProjectJobCollection(
      {
        jobs: [
          {
            ...job,
            provider_credential_id: "private-credential-id",
            lease_owner_id: "private-worker",
            sources: [{ transcript_body: "private-transcript" }],
          },
        ],
      },
      "project-safe",
    );

    expect(parsed).toEqual([job]);
    expect(parsed?.[0]).not.toHaveProperty("provider_credential_id");
    expect(parsed?.[0]).not.toHaveProperty("lease_owner_id");
    expect(parsed?.[0]).not.toHaveProperty("sources");
  });

  it("preserves bounded source names for history titles and rejects malformed names", () => {
    const named = { ...job, title: null, source_names: ["Лекция 1.mp4"] };
    expect(parseProjectJobCollection({ jobs: [named] }, "project-safe")?.[0].source_names)
      .toEqual(["Лекция 1.mp4"]);
    expect(parseProjectJobCollection({ jobs: [{ ...named, source_names: [" "] }] }, "project-safe"))
      .toBeNull();
    expect(parseProjectJobCollection({ jobs: [{ ...named, source_names: ["x".repeat(513)] }] }, "project-safe"))
      .toBeNull();
  });

  it("accepts only a boolean history-attention marker", () => {
    expect(
      parseProjectJobCollection(
        { jobs: [{ ...job, history_attention_required: true }] },
        "project-safe",
      )?.[0].history_attention_required,
    ).toBe(true);
    expect(
      parseProjectJobCollection(
        { jobs: [{ ...job, history_attention_required: "private-state" }] },
        "project-safe",
      ),
    ).toBeNull();
  });

  it("accepts a bounded job usage projection and discards private extras", () => {
    const parsed = parseProjectJobCollection(
      {
        jobs: [
          {
            ...job,
            usage_cost: {
              ...usageCost,
              provider_request_id: "private-request-id",
              rate_snapshot: {
                ...usageCost.rate_snapshot,
                raw_provider_payload: "private-payload",
              },
            },
          },
        ],
      },
      "project-safe",
    );

    expect(parsed?.[0].usage_cost).toEqual(usageCost);
    expect(parsed?.[0].usage_cost).not.toHaveProperty("provider_request_id");
    expect(parsed?.[0].usage_cost?.rate_snapshot).not.toHaveProperty(
      "raw_provider_payload",
    );
  });

  it("rejects malformed or internally inconsistent job usage projections", () => {
    const invalidUsageCosts = [
      { ...usageCost, rate_snapshot: { ...usageCost.rate_snapshot, source: ["yandex_public_api_pricing"] } },
      { ...usageCost, accounting_status: "provider-private-state" },
      { ...usageCost, currency: "EUR" },
      {
        ...usageCost,
        rate_snapshot: {
          ...usageCost.rate_snapshot,
          source: "private-provider-request-id",
        },
      },
      {
        ...usageCost,
        confirmed_billed_duration_seconds: 0,
        confirmed_provider_cost: "0.00000001",
      },
      {
        accounting_status: "not_started",
        confirmed_billed_duration_seconds: 0,
        confirmed_provider_cost: "0.00000000",
        currency: "USD",
        cost_basis: "confirmed_audio_duration_x_rate_snapshot",
        rate_snapshot: null,
      },
    ];

    for (const invalid of invalidUsageCosts) {
      expect(
        parseProjectJobCollection(
          { jobs: [{ ...job, usage_cost: invalid }] },
          "project-safe",
        ),
      ).toBeNull();
    }
  });

  it("preserves the public Yandex tariff provenance", () => {
    const yandexCost = { ...usageCost, rate_snapshot: { ...usageCost.rate_snapshot, source: "yandex_public_api_pricing" } };
    const parsed = parseProjectJobCollection({ jobs: [{ ...job, provider: "yandex", usage_cost: yandexCost }] }, "project-safe");
    expect(parsed?.[0].usage_cost?.rate_snapshot?.source).toBe("yandex_public_api_pricing");
  });

  it("accepts only safe speaker identity history metadata", () => {
    const withSpeakers = {
      ...job,
      speaker_identities: [
        {
          id: "speaker-safe",
          label: "Speaker 1",
          sample_available: true,
          profile: {
            id: "profile-safe",
            display_name: "Анна",
            role: "Автор",
            provider_label: "private-provider-label",
          },
          sample_start_ms: 1000,
          document_id: "private-document-id",
        },
      ],
    };
    const parsed = parseProjectJobCollection(
      { jobs: [withSpeakers] },
      "project-safe",
    );

    expect(parsed?.[0].speaker_identities).toEqual([
      {
        id: "speaker-safe",
        label: "Speaker 1",
        sample_available: true,
        profile: {
          id: "profile-safe",
          display_name: "Анна",
          role: "Автор",
        },
      },
    ]);
    expect(parsed?.[0].speaker_identities?.[0]).not.toHaveProperty(
      "sample_start_ms",
    );
    expect(parsed?.[0].speaker_identities?.[0]).not.toHaveProperty(
      "document_id",
    );

    expect(
      parseProjectJobCollection(
        {
          jobs: [
            {
              ...job,
              speaker_identities: [
                {
                  id: "speaker-safe",
                  label: "provider-private-label",
                  sample_available: true,
                  profile: null,
                },
              ],
            },
          ],
        },
        "project-safe",
      ),
    ).toBeNull();
  });

  it("accepts every canonical job language mode across list, detail, and summary", () => {
    for (const languageMode of ["ru", "en", "detect"] as const) {
      const localizedJob = { ...job, language_mode: languageMode };
      expect(
        parseProjectJobCollection({ jobs: [localizedJob] }, "project-safe"),
      ).toEqual([localizedJob]);
      expect(
        parseJobDetailResponse(
          {
            ...localizedJob,
            source_count: 0,
            sources: [],
          },
          "project-safe",
          "job-safe",
        )?.language_mode,
      ).toBe(languageMode);
      expect(
        parseJobSummaryResponse(localizedJob, "project-safe", "job-safe")
          ?.language_mode,
      ).toBe(languageMode);
    }

    expect(
      parseProjectJobCollection(
        { jobs: [{ ...job, language_mode: "private-mode" }] },
        "project-safe",
      ),
    ).toBeNull();
  });

  it("accepts only safe batch presentation references with unique positions", () => {
    const batchId = "multi_0123456789abcdef0123456789abcdef";
    const first = {
      ...job,
      batch: { id: batchId, position: 0 },
    };
    const second = {
      ...job,
      id: "job-safe-2",
      batch: { id: batchId, position: 1 },
    };

    expect(
      parseProjectJobCollection({ jobs: [second, first] }, "project-safe"),
    ).toEqual([second, first]);
    expect(
      parseProjectJobCollection(
        {
          jobs: [first, { ...second, batch: { id: batchId, position: 0 } }],
        },
        "project-safe",
      ),
    ).toBeNull();
    expect(
      parseProjectJobCollection(
        {
          jobs: [
            {
              ...first,
              batch: { id: "batch-key-must-not-be-exposed", position: 0 },
            },
          ],
        },
        "project-safe",
      ),
    ).toBeNull();
  });

  it("rejects cross-project, duplicate, and malformed job rows", () => {
    expect(
      parseProjectJobCollection(
        { jobs: [{ ...job, project_id: "project-other" }] },
        "project-safe",
      ),
    ).toBeNull();
    expect(
      parseProjectJobCollection({ jobs: [job, job] }, "project-safe"),
    ).toBeNull();
    expect(
      parseProjectJobCollection(
        {
          jobs: [
            {
              ...job,
              media_clip: { start_seconds: 10, end_seconds: 5 },
            },
          ],
        },
        "project-safe",
      ),
    ).toBeNull();
  });

  it("validates and sanitizes the ordered job detail projection", () => {
    const parsed = parseJobDetailResponse(
      {
        ...job,
        sources: [
          {
            ...source,
            drive_file_url: undefined,
            position: 0,
            job_source_status: "queued",
            drive_file_id: "private-drive-id",
            transcript_body: "private-transcript",
          },
        ],
        provider_credential_id: "private-credential-id",
      },
      "project-safe",
      "job-safe",
    );

    expect(parsed?.sources).toEqual([
      {
        ...source,
        drive_file_url: null,
        position: 0,
        job_source_status: "queued",
      },
    ]);
    expect(parsed).not.toHaveProperty("provider_credential_id");
    expect(parsed?.sources?.[0]).not.toHaveProperty("drive_file_id");
    expect(parsed?.sources?.[0]).not.toHaveProperty("transcript_body");
    expect(
      parseJobDetailResponse(
        { ...job, source_count: 2, sources: [] },
        "project-safe",
        "job-safe",
      ),
    ).toBeNull();
  });

  it("validates one exact job summary and discards mutation extras", () => {
    const parsed = parseJobSummaryResponse(
      {
        ...job,
        status: "completed",
        terminal_dismissed_at: "2026-08-14T10:01:00Z",
        finished_at: "2026-08-14T10:00:00Z",
        provider_credential_id: "private-credential-id",
        sources: [{ transcript_body: "private-transcript" }],
      },
      "project-safe",
      "job-safe",
    );

    expect(parsed).toEqual({
      ...job,
      status: "completed",
      terminal_dismissed_at: "2026-08-14T10:01:00Z",
      finished_at: "2026-08-14T10:00:00Z",
    });
    expect(parsed).not.toHaveProperty("provider_credential_id");
    expect(parsed).not.toHaveProperty("sources");
    expect(
      parseJobSummaryResponse(job, "project-safe", "job-other"),
    ).toBeNull();
  });

  it("validates outputs, approved links, counts, and uniqueness", () => {
    const output = {
      source_id: "source-safe",
      source_position: 0,
      source_name: "safe.mp3",
      source_type: "google_drive",
      output_kind: "google_doc",
      transcript_standard: "transcript_doc",
      web_view_url: "https://docs.google.com/document/d/safe/edit",
      link_available: true,
      document_character_count: 123,
      document_created_at: "2026-08-14T10:00:00Z",
      persisted_at: "2026-08-14T10:01:00Z",
    };
    const parsed = parseJobOutputsResponse(
      {
        job_id: "job-safe",
        job_status: "completed",
        output_count: 1,
        outputs: [{ ...output, document_id: "private-document-id" }],
        raw_storage: "private-storage",
      },
      "job-safe",
    );

    expect(parsed).toEqual({
      job_id: "job-safe",
      job_status: "completed",
      output_count: 1,
      outputs: [output],
    });
    expect(parsed?.outputs[0]).not.toHaveProperty("document_id");
    expect(
      parseJobOutputsResponse(
        {
          job_id: "job-safe",
          job_status: "completed",
          output_count: 1,
          outputs: [
            {
              ...output,
              web_view_url: "https://evil.example/private",
            },
          ],
        },
        "job-safe",
      ),
    ).toBeNull();
    expect(
      parseJobOutputsResponse(
        {
          job_id: "job-safe",
          job_status: "completed",
          output_count: 2,
          outputs: [output],
        },
        "job-safe",
      ),
    ).toBeNull();
  });
});


it("projects only safe prepared timeline fields and rejects unsafe primary output links", () => {
  const prepared_audio = { job_id: "123e4567-e89b-42d3-a456-426614174000", input_duration_ms: 12000, output_duration_ms: 8000, pauses_removed: true, secret: "private" };
  const parsed = parseProjectSourceCollection({ sources: [{ ...source, prepared_audio }] }, "project-safe");
  expect(parsed?.[0].prepared_audio).toEqual({ job_id: prepared_audio.job_id, input_duration_ms: 12000, output_duration_ms: 8000, pauses_removed: true });
  const url = "https://docs.google.com/document/d/synthetic/edit";
  expect(parseJobSummaryResponse({ ...job, primary_output_url: url }, "project-safe", "job-safe")?.primary_output_url).toBe(url);
  for (const primary_output_url of ["javascript:alert(1)", "https://attacker.example.test/", "https://docs.google.com@attacker.example.test/"]) {
    expect(parseJobSummaryResponse({ ...job, primary_output_url }, "project-safe", "job-safe")).toBeNull();
  }
});
