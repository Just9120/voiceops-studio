import { StrictMode } from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App, { __appDiagnosticsTest } from "./App";
import * as googlePicker from "./googlePicker";
import { computeGooglePickerSize } from "./googlePicker";
import {
  clearPwaDiagnosticsSession,
  configurePwaDiagnosticsSession,
  emitPwaDiagnostic,
} from "./pwaDiagnostics";

const originalLocation = window.location;
const openGooglePickerImplementation = googlePicker.openGooglePicker;
const json = (body: unknown, ok = true, status = 200) =>
  Promise.resolve({
    ok,
    status,
    json: () => Promise.resolve(body),
    clone: () => ({ json: () => Promise.resolve(body) }),
    text: () => Promise.resolve(JSON.stringify(body)),
    blob: () =>
      Promise.resolve(
        body instanceof Blob
          ? body
          : new Blob([JSON.stringify(body)], { type: "application/json" }),
      ),
  } as Response);
type TestDiagnosticsReportFormat = "md" | "json" | "yaml" | "toml";
const testReportMetadata = {
  md: { mediaType: "text/markdown", body: "# Studio diagnostics report\n" },
  json: { mediaType: "application/json", body: '{"schema_version":"v1"}\n' },
  yaml: { mediaType: "application/yaml", body: '"schema_version": "v1"\n' },
  toml: { mediaType: "application/toml", body: 'schema_version = "v1"\n' },
} as const;
const diagnosticsReport = (
  format: TestDiagnosticsReportFormat,
  body = testReportMetadata[format].body,
  status = 200,
  headers: Record<string, string> = {},
) =>
  Promise.resolve(
    new Response(body, {
      status,
      headers: {
        "cache-control": "no-store",
        "content-disposition":
          `attachment; filename="studio-diagnostics-report.${format}"`,
        "content-type": `${testReportMetadata[format].mediaType}; charset=utf-8`,
        ...headers,
      },
    }),
  );
const markdownReport = (
  body = testReportMetadata.md.body,
  status = 200,
  headers: Record<string, string> = {},
) => diagnosticsReport("md", body, status, headers);
function googleConnectionFixture(overrides: Record<string, unknown> = {}) {
  return {
    connected: false,
    status: null,
    google_email: null,
    scopes: null,
    connected_at: null,
    revoked_at: null,
    picker_configured: false,
    picker_scope_ready: false,
    picker_ready: false,
    reconnect_required: false,
    ...overrides,
  };
}
function googleOauthStartFixture(overrides: Record<string, unknown> = {}) {
  return {
    authorization_url:
      "https://accounts.google.com/o/oauth2/v2/auth?client_id=test-client.apps.googleusercontent.com&redirect_uri=https%3A%2F%2Fstudio.test%2Fapi%2Fgoogle%2Foauth%2Fcallback&response_type=code&scope=openid+email+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fdrive.file+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fdrive.readonly&state=secret-state&access_type=offline&prompt=consent",
    expires_at: "2026-08-13T12:00:00Z",
    ...overrides,
  };
}
function projectFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: "project-fixture",
    title: "Fixture project",
    description: null,
    created_at: "2026-08-13T10:00:00Z",
    updated_at: "2026-08-13T11:00:00Z",
    archived_at: null,
    output_drive_folder_id: null,
    output_drive_folder_url: null,
    output_drive_folder_name: null,
    ...overrides,
  };
}
function credentialFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: "credential-fixture",
    provider: "elevenlabs",
    label: "Fixture credential",
    status: "active",
    masked_value: "••••safe",
    active_version: 1,
    ...overrides,
  };
}
function sttProviderCatalogFixture() {
  const health = {
    available: true,
    consecutive_failures: 0,
    retry_after_seconds: null,
  };
  const constraints = {
    max_bytes: 26_214_400,
    max_duration_seconds: 14_400,
    audio_channels: [1, 2],
  };
  return {
    providers: [
      {
        provider: "elevenlabs",
        display_name: "ElevenLabs",
        byok_enabled: true,
        modes: [
          {
            mode: "economic",
            model: "scribe_v2",
            transport: "batch",
            languages: ["ru", "en", "detect"],
            diarization: true,
            dictionaries: true,
            file_constraints: constraints,
            health,
          },
          {
            mode: "standard",
            model: "scribe_v2",
            transport: "batch",
            languages: ["ru", "en", "detect"],
            diarization: true,
            dictionaries: true,
            file_constraints: constraints,
            health,
          },
          {
            mode: "premium",
            model: "scribe_v2",
            transport: "batch",
            languages: ["ru", "en", "detect"],
            diarization: true,
            dictionaries: true,
            file_constraints: constraints,
            health,
          },
          {
            mode: "realtime",
            model: "scribe_v2_realtime",
            transport: "websocket",
            languages: ["ru", "en", "detect"],
            diarization: false,
            dictionaries: false,
            file_constraints: {
              max_bytes: null,
              max_duration_seconds: 1_800,
              audio_channels: [1],
            },
            health,
          },
        ],
      },
      {
        provider: "yandex",
        display_name: "Yandex SpeechKit",
        byok_enabled: false,
        modes: [
          {
            mode: "economic",
            model: "general:rc",
            transport: "deferred",
            languages: ["ru", "en", "detect"],
            diarization: false,
            dictionaries: false,
            file_constraints: {
              max_bytes: 62_914_560,
              max_duration_seconds: 14_400,
              audio_channels: [1],
            },
            health,
          },
          {
            mode: "standard",
            model: "general",
            transport: "batch",
            languages: ["ru", "en", "detect"],
            diarization: true,
            dictionaries: false,
            file_constraints: {
              max_bytes: 62_914_560,
              max_duration_seconds: 14_400,
              audio_channels: [1],
            },
            health,
          },
          {
            mode: "premium",
            model: "general:rc",
            transport: "batch",
            languages: ["ru", "en", "detect"],
            diarization: true,
            dictionaries: false,
            file_constraints: {
              max_bytes: 62_914_560,
              max_duration_seconds: 14_400,
              audio_channels: [1],
            },
            health,
          },
          {
            mode: "realtime",
            model: "general",
            transport: "grpc_relay",
            languages: ["ru", "en", "detect"],
            diarization: true,
            dictionaries: false,
            file_constraints: {
              max_bytes: 10_485_760,
              max_duration_seconds: 300,
              audio_channels: [1],
            },
            health,
          },
        ],
      },
    ],
  };
}
function batchPreflightJson(init?: RequestInit) {
  const request = JSON.parse(String(init?.body ?? "{}")) as {
    provider?: "elevenlabs" | "yandex";
    operating_mode?: "economic" | "standard" | "premium";
    language?: "ru" | "en" | "detect";
    options?: { diarize?: boolean; dictionary_ids?: string[] };
    items?: {
      title?: string | null;
      reprocess_existing?: boolean;
      media_clip_start_seconds?: number | null;
      media_clip_end_seconds?: number | null;
    }[];
  };
  const items = request.items ?? [];
  return json({
    provider: request.provider ?? "elevenlabs",
    model: "scribe_v2",
    operating_mode: request.operating_mode ?? "standard",
    dictionary_term_count: request.options?.dictionary_ids?.length ?? 0,
    language_mode: request.language ?? "ru",
    diarization_enabled: request.options?.diarize === true,
    existing_result_authority: {
      status: "partial",
      reason_code: "unlinked_catalog_entries_excluded",
    },
    items: items.map((item, position) => ({
      position,
      title: item.title ?? null,
      media_clip:
        item.media_clip_start_seconds != null ||
        item.media_clip_end_seconds != null
          ? {
              start_seconds: item.media_clip_start_seconds ?? null,
              end_seconds: item.media_clip_end_seconds ?? null,
            }
          : null,
      source: {
        name: `Safe source ${position + 1}`,
        source_type: position % 2 === 0 ? "google_drive" : "local_upload",
        mime_type: position % 2 === 0 ? "video/mp4" : "audio/ogg",
        size_bytes: 2048 * (position + 1),
        duration_seconds: null,
      },
      output_destination: { name: `Safe folder ${position + 1}` },
      existing_result_match: {
        status: "no_match",
        accepted_output_count: 0,
        resolution: "not_required",
      },
      provider_attempt_authority: {
        status: "available",
        reason_code: null,
        attention_job_id: null,
      },
      planned_outcome: "process",
    })),
    summary: {
      process_count: items.length,
      skip_count: 0,
      blocked_count: 0,
    },
    confirmation_required: true,
  });
}

function isBatchPreflightRequest(url: string, init?: RequestInit) {
  return url.endsWith("/jobs/batch/preflight") && init?.method === "POST";
}
function requestPath(url: string) {
  return new URL(url, "http://localhost").pathname;
}
function progressStages(
  current:
    | "preparation"
    | "provider_processing"
    | "part_merge"
    | "google_docs_output"
    | null,
  video = true,
) {
  const keys = [
    "preparation",
    "audio_extraction",
    "splitting",
    "provider_processing",
    "part_merge",
    "google_docs_output",
  ];
  const currentIndex = current ? keys.indexOf(current) : -1;
  return keys.map((key, index) => {
    const notApplicable = key === "audio_extraction" && !video;
    return {
      key,
      status: notApplicable
        ? "not_applicable"
        : currentIndex < 0
          ? "pending"
          : index < currentIndex
            ? "completed"
            : index === currentIndex
              ? "active"
              : "pending",
      applicability: notApplicable
        ? "not_applicable"
        : key === "splitting" || key === "part_merge"
          ? "conditional"
          : "required",
    };
  });
}
function expectOnlySafeFormDrafts() {
  for (const key of Object.keys(sessionStorage)) {
    expect(key.startsWith("studio-form-draft:v1:")).toBe(true);
    const value=sessionStorage.getItem(key) ?? "";
    expect(value).not.toMatch(/"(?:password|secret|csrf|access_token|refresh_token|presigned_url)"\s*:/);
    expect(value).not.toContain("https://upload.example/leak");
    expect(value).not.toContain("secret-key");
  }
}
function renderApp() {
  render(<App />);
}
function postedPwaEventsFrom(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls
    .filter(([url]) => String(url).endsWith("/api/diagnostics/pwa-events"))
    .flatMap(
      ([, init]) => JSON.parse(String((init as RequestInit).body)).events,
    );
}

function installFakeGooglePicker() {
  googlePicker.resetGooglePickerLoaderForTests();
  let callback: ((data: unknown) => void) | null = null;
  let appOwnedPickerCallback: ((data: unknown) => void) | null = null;
  let outputFolderOpenCount = 0;
  const viewIds: string[] = [];
  const viewModes: string[] = [];
  const viewParents: string[] = [];
  const includeFolders: boolean[] = [];
  const selectFolderEnabled: boolean[] = [];
  const builderCalls: { method: string; args: unknown[] }[] = [];
  const setVisible = vi.fn();
  class FakeView {
    constructor(viewId: string) {
      viewIds.push(viewId);
    }
    setIncludeFolders(value: boolean) {
      includeFolders.push(value);
      return this;
    }
    setSelectFolderEnabled(value: boolean) {
      selectFolderEnabled.push(value);
      return this;
    }
    setMode(mode: string) {
      viewModes.push(mode);
      return this;
    }
    setParent(parentId: string) {
      viewParents.push(parentId);
      return this;
    }
  }
  class FakeBuilder {
    addView() {
      builderCalls.push({ method: "addView", args: [] });
      return this;
    }
    enableFeature(feature: string) {
      builderCalls.push({ method: "enableFeature", args: [feature] });
      return this;
    }
    setOAuthToken() {
      return this;
    }
    setDeveloperKey() {
      return this;
    }
    setAppId() {
      return this;
    }
    setLocale(locale: string) {
      builderCalls.push({ method: "setLocale", args: [locale] });
      return this;
    }
    setSize(width: number, height: number) {
      builderCalls.push({ method: "setSize", args: [width, height] });
      return this;
    }
    setTitle(title: string) {
      builderCalls.push({ method: "setTitle", args: [title] });
      return this;
    }
    setOrigin(origin: string) {
      builderCalls.push({ method: "setOrigin", args: [origin] });
      return this;
    }
    setMaxItems(maxItems: number) {
      builderCalls.push({ method: "setMaxItems", args: [maxItems] });
      return this;
    }
    setCallback(cb: (data: unknown) => void) {
      builderCalls.push({ method: "setCallback", args: [cb] });
      callback = cb;
      return this;
    }
    build() {
      return { setVisible };
    }
  }
  window.gapi = { load: vi.fn((_name: string, cb: () => void) => cb()) };
  window.google = {
    picker: {
      Action: { PICKED: "picked", CANCEL: "cancel", ERROR: "error" },
      DocsView: FakeView,
      PickerBuilder: FakeBuilder,
      ViewId: { DOCS: "docs", FOLDERS: "folders" },
      DocsViewMode: { LIST: "list" },
      Feature: { MULTISELECT_ENABLED: "multi" },
    },
  };
  vi.spyOn(googlePicker, "openGooglePicker").mockImplementation(
    (mode, session) => {
      if (
        mode !== "sources" &&
        mode !== "source-folder" &&
        mode !== "output-folder"
      ) {
        return openGooglePickerImplementation(mode, session);
      }
      if (mode === "output-folder") outputFolderOpenCount += 1;
      session.access_token = "";
      return new Promise((resolve) => {
        let completed = false;
        const finish = (
          result: Awaited<ReturnType<typeof googlePicker.openGooglePicker>>,
        ) => {
          if (completed) return;
          completed = true;
          window.clearTimeout(timeout);
          resolve(result);
        };
        appOwnedPickerCallback = (data: unknown) => {
          if (completed) return;
          const payload = data as { action?: unknown; docs?: unknown[] };
          if (payload.action === "picked") {
            const docs = Array.isArray(payload.docs)
              ? payload.docs
                  .map(
                    (doc) =>
                      doc as {
                        id?: unknown;
                        name?: unknown;
                        mimeType?: unknown;
                      },
                  )
                  .filter(
                    (doc) => typeof doc.id === "string" && doc.id.trim(),
                  )
                  .map((doc) => ({
                    id: String(doc.id),
                    name:
                      typeof doc.name === "string" ? doc.name : undefined,
                    mimeType:
                      typeof doc.mimeType === "string"
                        ? doc.mimeType
                        : undefined,
                  }))
              : [];
            finish({ action: "picked", docs });
          } else if (payload.action === "cancel") {
            finish({ action: "cancel" });
          } else if (payload.action === "error") {
            finish({
              action: "error",
              message:
                "Не удалось загрузить Google Drive. Переподключите Drive или повторите попытку.",
            });
          }
        };
        const timeout = window.setTimeout(
          () =>
            finish({
              action: "error",
              message:
                "Время выбора в Google Drive истекло. Повторите попытку.",
            }),
          300_000,
        );
      });
    },
  );
  return {
    loadScript: async () => {
      let script: HTMLScriptElement | null = null;
      await waitFor(() => {
        script = document.head.querySelector<HTMLScriptElement>(
          'script[data-studio-google-picker="true"]',
        );
        expect(appOwnedPickerCallback !== null || script !== null).toBe(true);
      });
      script?.onload?.(new Event("load"));
    },
    trigger: (data: unknown) => {
      const activeCallback = appOwnedPickerCallback ?? callback;
      if (!activeCallback) {
        throw new Error("Picker callback was not registered");
      }
      activeCallback(data);
    },
    waitForCallback: () =>
      waitFor(() =>
        expect(appOwnedPickerCallback ?? callback).not.toBeNull(),
      ),
    setVisible,
    viewIds,
    viewModes,
    viewParents,
    includeFolders,
    selectFolderEnabled,
    builderCalls,
    get outputFolderOpenCount() {
      return outputFolderOpenCount;
    },
  };
}

type OutputFixtureOptions = {
  jobStatus?: "queued" | "processing" | "completed" | "failed" | "cancelled";
  languageMode?: "ru" | "en" | "detect";
  outputCount?: number;
  outputs?: unknown[];
  detailOk?: boolean;
  outputsOk?: boolean;
  detailErrorBody?: unknown;
  outputsErrorBody?: unknown;
  retryResponse?: unknown;
  reconciliationResponse?: unknown;
  terminalDismissedAt?: string | null;
  historyAttentionRequired?: boolean;
  includeSecondProject?: boolean;
  errorCode?: string | null;
};

const focusedJobDetailSource = {
  id: "source-detail-id-not-output-id",
  project_id: "p1",
  position: 0,
  job_source_status: "queued",
  source_type: "google_drive",
  original_filename: "focused-source.mp3",
  mime_type: "audio/mpeg",
  size_bytes: 1234,
  drive_file_id: null,
  drive_file_url: null,
  upload_status: "uploaded",
  uploaded_at: "2026-07-01T00:01:00Z",
  expires_at: null,
  deleted_at: null,
  delete_reason: null,
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-07-01T00:00:00Z",
};

function installFocusedOutputFixture(options: OutputFixtureOptions = {}) {
  const jobStatus = options.jobStatus ?? "processing";
  const outputCount = options.outputCount ?? options.outputs?.length ?? 1;
  const outputs = options.outputs ?? [
    {
      source_id: "source-id-not-rendered",
      source_position: 0,
      source_name: `${jobStatus}-source`,
      source_type: "google_drive",
      output_kind: "transcript",
      transcript_standard: "transcript_doc",
      web_view_url: "https://docs.google.com/document/d/focused-safe/edit",
      link_available: true,
      document_character_count: 456,
      document_created_at: "2026-07-02T00:10:00Z",
      persisted_at: "2026-07-02T00:11:00Z",
    },
  ];
  (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    (url: string, init?: RequestInit) => {
      if (url.endsWith("/api/auth/session"))
        return json({
          authenticated: true,
          user: { email: "user@example.com", role: "admin" },
        });
      if (url.endsWith("/api/auth/csrf"))
        return json({ csrf_token: "csrf-after-refresh" });
      if (url.endsWith("/api/stt/providers"))
        return json(sttProviderCatalogFixture());
      if (url.endsWith("/api/stt/dictionaries"))
        return json({ dictionaries: [] });
      if (url.endsWith("/api/projects"))
        return json({
          projects: [
            {
              id: "p1",
              title: "Research calls",
              description: null,
              created_at: "2026-07-01T00:00:00",
              updated_at: "2026-07-01T00:00:00",
              archived_at: null,
              output_drive_folder_id: null,
              output_drive_folder_url: null,
              output_drive_folder_name: null,
            },
            ...(options.includeSecondProject
              ? [
                  {
                    id: "p2",
                    title: "Project Two",
                    description: null,
                    created_at: "2026-07-02T00:00:00",
                    updated_at: "2026-07-02T00:00:00",
                    archived_at: null,
                    output_drive_folder_id: null,
                    output_drive_folder_url: null,
                    output_drive_folder_name: null,
                  },
                ]
              : []),
          ],
        });
      if (url.endsWith("/api/credentials"))
        return json({
          credentials: [
            {
              id: "cred-active",
              provider: "elevenlabs",
              label: "Primary STT",
              status: "active",
              masked_value: "••••1234",
              active_version: 2,
            },
          ],
        });
      if (url.endsWith("/api/projects/p2/sources") && !init?.method)
        return json({ sources: [] });
      if (url.endsWith("/api/projects/p2/jobs") && !init?.method)
        return json({ jobs: [] });
      if (url.endsWith("/api/projects/p1/sources") && !init?.method)
        return json({
          sources: [
            {
              id: "source-focused",
              project_id: "p1",
              source_type: "google_drive",
              original_filename: "focused-source.mp3",
              mime_type: "audio/mpeg",
              size_bytes: 1234,
              drive_file_id: null,
              drive_file_url: null,
              upload_status: "uploaded",
              uploaded_at: "2026-07-01T00:01:00Z",
              expires_at: null,
              deleted_at: null,
              delete_reason: null,
              created_at: "2026-07-01T00:00:00Z",
              updated_at: "2026-07-01T00:00:00Z",
            },
          ],
        });
      if (url.endsWith("/api/projects/p1/jobs") && !init?.method)
        return json({
          jobs: [
            {
              id: "job-focused",
              project_id: "p1",
              status: jobStatus,
              title: "Focused output job",
              provider: null,
              language_mode: options.languageMode ?? "ru",
              provider_credential_id: "cred-active",
              terminal_dismissed_at: options.terminalDismissedAt ?? null,
              history_attention_required:
                options.historyAttentionRequired ?? false,
              source_count: 1,
              created_at: "2026-07-02T00:00:00Z",
              updated_at: "2026-07-02T00:01:00Z",
              cancelled_at:
                jobStatus === "cancelled" ? "2026-07-02T00:02:00Z" : null,
              cancel_requested_at: null,
              attempt_count: 1,
              started_at: "2026-07-02T00:00:30Z",
              finished_at: ["completed", "failed", "cancelled"].includes(
                jobStatus,
              )
                ? "2026-07-02T00:03:00Z"
                : null,
              error_code:
                jobStatus === "failed"
                  ? (options.errorCode ?? "SAFE_FAILED")
                  : null,
              error_message: jobStatus === "failed" ? "Safe failure" : null,
            },
          ],
        });
      if (
        options.reconciliationResponse !== undefined &&
        url.endsWith("/api/jobs/job-focused/output-reconciliation") &&
        !init?.method
      )
        return json(options.reconciliationResponse);
      if (
        options.retryResponse !== undefined &&
        url.endsWith("/api/jobs/job-focused/retry") &&
        !init?.method
      )
        return json(options.retryResponse);
      if (url.endsWith("/api/jobs/job-focused/outputs"))
        return options.outputsOk === false
          ? json(
              options.outputsErrorBody ?? { detail: "raw sql traceback token" },
              false,
              500,
            )
          : json({
              job_id: "job-focused",
              job_status: jobStatus,
              output_count: outputCount,
              outputs,
            });
      if (url.endsWith("/api/jobs/job-focused"))
        return options.detailOk === false
          ? json(
              options.detailErrorBody ?? {
                detail: "raw detail traceback token",
              },
              false,
              500,
            )
          : json({
              id: "job-focused",
              project_id: "p1",
              status: jobStatus,
              title: "Focused output job",
              provider: null,
              language_mode: options.languageMode ?? "ru",
              provider_credential_id: "cred-active",
              terminal_dismissed_at: options.terminalDismissedAt ?? null,
              history_attention_required:
                options.historyAttentionRequired ?? false,
              source_count: 1,
              created_at: "2026-07-02T00:00:00Z",
              updated_at: "2026-07-02T00:01:00Z",
              cancelled_at:
                jobStatus === "cancelled" ? "2026-07-02T00:02:00Z" : null,
              cancel_requested_at: null,
              attempt_count: 1,
              started_at: "2026-07-02T00:00:30Z",
              finished_at: ["completed", "failed", "cancelled"].includes(
                jobStatus,
              )
                ? "2026-07-02T00:03:00Z"
                : null,
              error_code:
                jobStatus === "failed"
                  ? (options.errorCode ?? "SAFE_FAILED")
                  : null,
              error_message: jobStatus === "failed" ? "Safe failure" : null,
              sources: [focusedJobDetailSource],
            });
      return json({ credentials: [], events: [] });
    },
  );
}

async function waitForPlatformOverview() {
  expect(
    await screen.findByRole("heading", { name: "VoiceOps Studio" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Обзор", current: "page" }),
  ).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByLabelText("Последние результаты")).not.toHaveTextContent(
      "Загрузка…",
    ),
  );
}

async function openPlatformNavPage(
  name: "Обзор" | "Транскрибации" | "Настройки",
) {
  await waitFor(() =>
    expect(
      within(screen.getByRole("navigation", { name: "Основная навигация" })).getByRole("button", {
        name: "Обзор",
      }),
    ).toBeInTheDocument(),
  );
  await userEvent.click(
    within(screen.getByRole("navigation", { name: "Основная навигация" })).getByRole("button", { name }),
  );
}

async function openProjectsPage() {
  await openPlatformNavPage("Транскрибации");
  expect(
    await screen.findByRole("heading", { name: "Транскрибации" }),
  ).toBeInTheDocument();
}

async function openSelectedProjectJobs() {
  await openProjectsPage();
  await screen.findByRole("form", { name: "Композитор пакетных задач" });
}

async function chooseExistingSource(rowNumber: number, sourceName: string) {
  const select = await screen.findByLabelText(
    `Существующий файл для задачи ${rowNumber}`,
  );
  const option = within(select).getByRole("option", {
    name: new RegExp(sourceName),
  });
  await userEvent.selectOptions(select, option);
}

async function chooseResultFolder(
  rowNumber = 1,
  folderId = "folder-123",
  expectedDisplayName?: string,
) {
  vi.spyOn(googlePicker, "openGooglePicker").mockResolvedValueOnce({
    action: "picked",
    docs: [{ id: folderId }],
  } as Awaited<ReturnType<typeof googlePicker.openGooglePicker>>);
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  const previousFetch = fetchMock.getMockImplementation();
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (
      url.endsWith("/api/google/picker/session") &&
      init?.method === "POST"
    ) {
      return json({
        access_token: "ya29.test-access-token",
        api_key: "public-picker-key",
        app_id: "123456789",
        scope_ready: true,
      });
    }
    if (
      url.includes("/api/projects/") &&
      url.endsWith("/output-folders/google-picker/verify") &&
      init?.method === "POST"
    ) {
      if (!expectedDisplayName) {
        const previousResponse = await previousFetch?.(url, init);
        if (previousResponse) {
          const candidate = (await previousResponse
            .clone()
            .json()
            .catch(() => null)) as {
            name?: unknown;
            web_view_url?: unknown;
          } | null;
          if (
            candidate &&
            typeof candidate.name === "string" &&
            candidate.name.trim() &&
            (candidate.web_view_url === null ||
              typeof candidate.web_view_url === "string")
          ) {
            return previousResponse;
          }
        }
      }
      return json({
        name: expectedDisplayName ?? "Папка Google Drive",
        web_view_url: `https://drive.google.com/drive/folders/${folderId}`,
      });
    }
    return previousFetch?.(url, init) ?? json({ ok: true });
  });
  await userEvent.click(
    await screen.findByRole("button", {
      name: `Выбрать папку результата для задачи ${rowNumber}`,
    }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", {
        name: `Выбрать папку результата для задачи ${rowNumber}`,
      }),
    ).toHaveTextContent("Изменить"),
  );
  if (expectedDisplayName) {
    expect(screen.getAllByText(expectedDisplayName).length).toBeGreaterThan(0);
  }
}

async function chooseSegmentResultFolder(
  rowNumber: number,
  segmentNumber: number,
  folderId: string,
  expectedDisplayName: string,
) {
  vi.spyOn(googlePicker, "openGooglePicker").mockResolvedValueOnce({
    action: "picked",
    docs: [{ id: folderId }],
  } as Awaited<ReturnType<typeof googlePicker.openGooglePicker>>);
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  const previousFetch = fetchMock.getMockImplementation();
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (
      url.endsWith("/api/google/picker/session") &&
      init?.method === "POST"
    ) {
      return json({
        access_token: "ya29.test-access-token",
        api_key: "public-picker-key",
        app_id: "123456789",
        scope_ready: true,
      });
    }
    if (
      url.includes("/api/projects/") &&
      url.endsWith("/output-folders/google-picker/verify") &&
      init?.method === "POST" &&
      JSON.parse(String(init.body)).folder_id === folderId
    ) {
      return json({
        name: expectedDisplayName,
        web_view_url: `https://drive.google.com/drive/folders/${folderId}`,
      });
    }
    return previousFetch?.(url, init) ?? json({ ok: true });
  });
  await userEvent.click(
    screen.getByRole("button", {
      name: `Выбрать папку фрагмента ${segmentNumber} задачи ${rowNumber}`,
    }),
  );
  await waitFor(() =>
    expect(screen.getByText(expectedDisplayName)).toBeInTheDocument(),
  );
}

async function reviewAndConfirmBatch() {
  await userEvent.click(
    screen.getByRole("button", { name: /\u041fроверить задачи \(\d+\)/ }),
  );
  await screen.findByLabelText("Проверка перед созданием задач");
  await userEvent.click(
    screen.getByRole("button", {
      name: /\u041fодтвердить и создать \(\d+\)/,
    }),
  );
}

async function openSettingsPage() {
  await openPlatformNavPage("Настройки");
  expect(
    await screen.findByRole("heading", { name: "Аккаунт" }),
  ).toBeInTheDocument();
}

async function openSettingsSection(
  name:
    | "Аккаунт"
    | "Подключения"
    | "Файлы и хранилище"
    | "Оформление"
    | "Для поддержки",
) {
  await openSettingsPage();
  if (name !== "Аккаунт") {
    await userEvent.click(screen.getByRole("tab", { name }));
  }
  expect(
    await screen.findByRole("heading", { name }),
  ).toBeInTheDocument();
}

async function openFocusedJobsList() {
  renderApp();
  await openSelectedProjectJobs();
  expect(await screen.findByText("Focused output job")).toBeInTheDocument();
}
describe("Studio PWA", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        addEventListener: vi.fn(),
        enumerateDevices: vi.fn().mockResolvedValue([]),
        getDisplayMedia: vi.fn(),
        getUserMedia: vi.fn(),
        removeEventListener: vi.fn(),
      },
    });
    Object.defineProperty(window, "location", {
      value: originalLocation,
      writable: true,
      configurable: true,
    });
    window.history.replaceState({}, "", "/");
    vi.spyOn(window, "confirm").mockReturnValue(true);
    googlePicker.resetGooglePickerLoaderForTests();
    delete window.gapi;
    delete window.google;
    document.head
      .querySelectorAll('script[data-studio-google-picker="true"]')
      .forEach((node) => node.remove());
    localStorage.clear();
    sessionStorage.clear();
    delete document.documentElement.dataset.theme;
    delete document.documentElement.dataset.themePreference;
    document.documentElement.style.colorScheme = "";
    let localUploadIndex = 0;
    const localUploadMetadata = new Map<
      string,
      { mime_type: string; size_bytes: number }
    >();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (isBatchPreflightRequest(url, init))
          return batchPreflightJson(init);
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
          });
        if (url.endsWith("/api/auth/csrf"))
          return json({
            csrf_token: "csrf-after-refresh",
            user: { email: "user@example.com", role: "admin" },
          });
        if (url.endsWith("/api/auth/sessions") && !init?.method)
          return json({
            sessions: [
              {
                id: "00000000-0000-0000-0000-000000000001",
                is_current: true,
                created_at: "2026-08-27T10:00:00Z",
                last_seen_at: "2026-08-27T10:05:00Z",
                expires_at: "2026-09-10T10:00:00Z",
              },
            ],
            truncated: false,
            limit: 100,
          });
        if (
          url.endsWith("/api/account/preferences") &&
          init?.method === "PATCH"
        ) {
          const payload = JSON.parse(String(init.body));
          return json({
            source_retention_ttl_seconds:
              payload.source_retention_ttl_seconds ?? 259200,
            allowed_source_retention_ttl_seconds: [
              259200, 604800, 2592000,
            ],
            accent_color: payload.accent_color ?? "blue",
            allowed_accent_colors: ["blue", "violet", "teal", "rose"],
          });
        }
        if (url.endsWith("/api/account/preferences"))
          return json({
            source_retention_ttl_seconds: 259200,
            allowed_source_retention_ttl_seconds: [
              259200, 604800, 2592000,
            ],
            accent_color: "blue",
            allowed_accent_colors: ["blue", "violet", "teal", "rose"],
          });
        if (url.endsWith("/api/sources/upload-policy"))
          return json({
            local_upload_enabled: true,
            max_upload_bytes: 536870912,
            multipart_threshold_bytes: 16777216,
            multipart_part_size_bytes: 8388608,
            supported_mime_prefixes: ["audio/", "video/"],
            supported_mime_types: ["application/ogg"],
          });
        if (url.endsWith("/api/stt/providers"))
          return json(sttProviderCatalogFixture());
        if (url.endsWith("/api/stt/dictionaries"))
          return json({ dictionaries: [] });
        if (url.endsWith("/api/auth/bootstrap-status"))
          return json({ bootstrap_required: false });
        if (url.endsWith("/api/auth/login-context"))
          return json({ login_csrf_token: "login-csrf" });
        if (url.endsWith("/api/auth/login"))
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
            csrf_token: "csrf",
          });
        if (url.endsWith("/api/auth/logout")) return json({ ok: true });
        if (url.endsWith("/api/projects") && init?.method === "POST")
          return json({
            id: "p2",
            title: "Created project",
            description: "",
            created_at: "2026-07-01T00:00:00",
            updated_at: "2026-07-01T00:00:00",
            archived_at: null,
            output_drive_folder_id: null,
            output_drive_folder_url: null,
            output_drive_folder_name: null,
          });
        if (url.includes("/api/projects/") && init?.method === "PATCH")
          return json({
            id: "p1",
            title: "Renamed project",
            description: "",
            created_at: "2026-07-01T00:00:00",
            updated_at: "2026-07-01T00:00:00",
            archived_at: null,
            output_drive_folder_id: null,
            output_drive_folder_url: null,
            output_drive_folder_name: null,
          });
        if (url.endsWith("/archive") && init?.method === "POST")
          return json({ ok: true });
        if (url.endsWith("/api/projects"))
          return json({
            projects: [
              {
                id: "p1",
                title: "Research calls",
                description: "Customer interview notes",
                created_at: "2026-07-01T00:00:00",
                updated_at: "2026-07-01T00:00:00",
                archived_at: null,
                output_drive_folder_id: "folder-123",
                output_drive_folder_url:
                  "https://drive.example/folders/folder-123",
                output_drive_folder_name: "Transcripts",
              },
            ],
          });
        if (url.endsWith("/api/google/drive/files/drive-file-2/metadata"))
          return json({
            id: "drive-file-2",
            name: "verified-drive-call.mov",
            mime_type: "video/quicktime",
            size_bytes: 1234,
            web_view_link: "https://drive.example/file/2",
            created_time: "2026-07-01T00:00:00Z",
            modified_time: "2026-07-02T00:00:00Z",
            is_folder: false,
          });
        if (url.endsWith("/api/google/drive/folders/folder-children/children"))
          return json({
            folder_id: "folder-children",
            items: [
              {
                id: "child-file-1",
                name: "child-call.mp3",
                mime_type: "audio/mpeg",
                size_bytes: 4096,
                web_view_link: "https://drive.example/file/child-1",
                created_time: "2026-07-03T00:00:00Z",
                modified_time: "2026-07-04T00:00:00Z",
                is_folder: false,
              },
              {
                id: "child-folder-1",
                name: "Nested folder",
                mime_type: "application/vnd.google-apps.folder",
                size_bytes: null,
                web_view_link: "https://drive.example/folder/nested",
                created_time: "2026-07-05T00:00:00Z",
                modified_time: "2026-07-06T00:00:00Z",
                is_folder: true,
              },
            ],
            next_page_token: "next-token",
          });
        if (
          url.endsWith(
            "/api/google/drive/folders/folder-children/children?page_token=next-token",
          )
        )
          return json({
            folder_id: "folder-children",
            items: [
              {
                id: "child-file-2",
                name: "second-child.wav",
                mime_type: "audio/wav",
                size_bytes: null,
                web_view_link: null,
                created_time: null,
                modified_time: "2026-07-07T00:00:00Z",
                is_folder: false,
              },
            ],
            next_page_token: null,
          });
        if (url.endsWith("/api/credentials") && !init?.method)
          return json({
            credentials: [
              {
                id: "cred-active",
                provider: "elevenlabs",
                label: "Primary STT",
                status: "active",
                masked_value: "••••1234",
                active_version: 2,
              },
            ],
          });
        if (url.endsWith("/api/projects/p1/jobs") && !init?.method)
          return json({ jobs: [] });
        if (url.endsWith("/api/projects/p1/sources") && !init?.method)
          return json({
            sources: [
              {
                id: "s1",
                project_id: "p1",
                source_type: "google_drive",
                original_filename:
                  "Лекция 1. Личность как психологическое явление.flac",
                mime_type: "video/mp4",
                size_bytes: 2048,
                drive_file_id: "drive-file-1",
                drive_file_url: "https://drive.example/file/1",
                upload_status: "uploaded",
                uploaded_at: "2026-07-01T00:01:00",
                expires_at: null,
                deleted_at: null,
                delete_reason: null,
                created_at: "2026-07-01T00:00:00",
                updated_at: "2026-07-01T00:00:00",
              },
              {
                id: "s-local",
                project_id: "p1",
                source_type: "local_upload",
                original_filename: "local-temp.ogg",
                mime_type: "audio/ogg",
                size_bytes: 1024,
                drive_file_id: null,
                drive_file_url: null,
                upload_status: "uploaded",
                uploaded_at: "2026-07-01T00:02:00",
                expires_at: "2099-01-02T00:02:00Z",
                deleted_at: null,
                delete_reason: null,
                created_at: "2026-07-01T00:00:00",
                updated_at: "2026-07-01T00:00:00",
              },
            ],
          });
        if (
          url.endsWith("/api/google/picker/session") &&
          init?.method === "POST"
        )
          return json({
            access_token: "ya29.test-access-token",
            api_key: "public-picker-key",
            app_id: "123456789",
            scope_ready: true,
          });
        if (
          url.endsWith("/api/projects/p1/sources/google-picker") &&
          init?.method === "POST"
        )
          return json({
            sources: [
              {
                id: "s-picker-1",
                project_id: "p1",
                source_type: "google_drive",
                original_filename: "picked-first.mp4",
                mime_type: "video/mp4",
                size_bytes: 10,
                drive_file_url: "https://drive.example/file-1",
                upload_status: "uploaded",
                uploaded_at: "2026-07-01T00:00:00Z",
                expires_at: null,
                deleted_at: null,
                delete_reason: null,
                created_at: "2026-07-01T00:00:00Z",
                updated_at: "2026-07-01T00:00:00Z",
              },
              {
                id: "s-picker-2",
                project_id: "p1",
                source_type: "google_drive",
                original_filename: "picked-second.mp4",
                mime_type: "video/mp4",
                size_bytes: 20,
                drive_file_url: "https://drive.example/file-2",
                upload_status: "uploaded",
                uploaded_at: "2026-07-01T00:00:00Z",
                expires_at: null,
                deleted_at: null,
                delete_reason: null,
                created_at: "2026-07-01T00:00:00Z",
                updated_at: "2026-07-01T00:00:00Z",
              },
            ],
          });
        if (
          url.endsWith(
            "/api/projects/p1/output-folders/google-picker/verify",
          ) &&
          init?.method === "POST"
        )
          return json({
            name: "Default folder",
            web_view_url: "https://drive.example/folders/folder-123",
          });
        if (
          url.endsWith("/api/projects/p1/sources/google-drive") &&
          init?.method === "POST"
        )
          return json({ id: "s2" });
        if (
          url.endsWith("/api/projects/p1/sources/local-upload/initiate") &&
          init?.method === "POST"
        ) {
          localUploadIndex += 1;
          const sourceId = `local-source-${localUploadIndex}`;
          const request = JSON.parse(String(init.body)) as {
            mime_type: string;
            size_bytes: number;
          };
          localUploadMetadata.set(sourceId, request);
          return json({
            source_id: sourceId,
            upload: {
              method: "PUT",
              url: `https://upload.example/presigned-${localUploadIndex}`,
              headers: { "Content-Type": request.mime_type },
              expires_in: 900,
            },
          });
        }
        if (url.startsWith("https://upload.example/presigned"))
          return json({}, true, 200);
        if (
          url.includes("/api/sources/local-source-") &&
          url.endsWith("/local-upload/complete") &&
          init?.method === "POST"
        ) {
          const sourceId =
            url.match(/local-source-\d+/)?.[0] ?? "local-source-1";
          const metadata = localUploadMetadata.get(sourceId) ?? {
            mime_type: "audio/ogg",
            size_bytes: 11,
          };
          return json({
            id: sourceId,
            project_id: "p1",
            source_type: "local_upload",
            original_filename: `${sourceId}.ogg`,
            mime_type: metadata.mime_type,
            size_bytes: metadata.size_bytes,
            drive_file_id: null,
            drive_file_url: null,
            upload_status: "uploaded",
            uploaded_at: "2099-01-01T00:00:00Z",
            expires_at: "2099-01-02T00:00:00Z",
            deleted_at: null,
            delete_reason: null,
            created_at: "2026-07-01T00:00:00Z",
            updated_at: "2026-07-01T00:00:00Z",
          });
        }
        if (url.endsWith("/api/sources/s1") && init?.method === "DELETE")
          return json({
            ok: true,
            source_state: "deleted",
            storage_cleanup: "not_applicable",
          });
        if (
          url.endsWith("/api/sources/s-local") &&
          init?.method === "DELETE"
        )
          return json({
            ok: true,
            source_state: "deleted",
            storage_cleanup: "pending",
          });
        if (url.endsWith("/api/credentials") && init?.method === "POST") {
          const request = JSON.parse(String(init.body)) as {
            provider: "elevenlabs" | "openai";
            label: string;
          };
          return json({
            id: "c1",
            provider: request.provider,
            label: request.label,
            status: "active",
            masked_value: "••••safe",
          });
        }
        if (url.endsWith("/replace"))
          return json({
            ok: true,
            active_version: 2,
            masked_value: "••••safe",
          });
        if (url.endsWith("/api/credentials"))
          return json({
            credentials: [
              {
                id: "c1",
                provider: "elevenlabs",
                label: "main",
                status: "active",
                masked_value: "••••1234",
                active_version: 1,
              },
            ],
          });
        if (url.endsWith("/api/audit-events"))
          return json({
            events: [
              {
                id: "e1",
                type: "credential.created",
                created_at: new Date().toISOString(),
              },
            ],
          });
        if (
          url.endsWith("/api/diagnostics/incidents/incident-1/acknowledge") &&
          init?.method === "POST"
        )
          return json({
            id: "incident-1",
            kind: "provider_unavailable",
            severity: "warning",
            status: "acknowledged",
            summary_code: "provider_unavailable",
            occurrence_count: 4,
            evidence_count: 4,
            first_detected_at: "2026-07-16T08:00:00Z",
            last_detected_at: "2026-07-16T10:00:00Z",
            last_transition_at: "2026-07-16T10:01:00Z",
            delivery: {
              channel: "telegram",
              state: "suppressed",
              attempt_count: 0,
              notification_kind: "firing",
            },
          });
        if (url.endsWith("/api/diagnostics/system"))
          return json({
            environment: "production",
            build: { web: "web-safe", api: "api-safe", worker: "worker-safe" },
            google_drive: { connected: true, scope_ready: true },
            provider_credentials: { active_count: 1, ready: true },
            diagnostics: {
              recording_enabled: true,
              debug_recording: "inactive",
              retention_days: 14,
              debug_retention_hours: 24,
            },
            report_limits: { max_days: 7, max_timeline_events: 5000 },
          });
        if (url.includes("/api/diagnostics/events"))
          return json({
            events: [],
            next_cursor: null,
            period: {
              start: "2026-07-15T00:00:00",
              end: "2026-07-16T00:00:00",
            },
          });
        if (
          url.endsWith("/api/diagnostics/report.md") &&
          init?.method === "POST"
        )
          return markdownReport("# Safe report\n");
        if (url.endsWith("/api/google/connection") && init?.method === "DELETE")
          return json(
            googleConnectionFixture({
              status: "revoked",
              google_email: "safe.user@example.com",
              scopes: "https://www.googleapis.com/auth/drive.file",
              connected_at: "2026-07-01T00:00:00",
              revoked_at: "2026-07-02T00:00:00",
            }),
          );
        if (url.endsWith("/api/google/maintenance/connection"))
          return json({
            connected: true,
            status: "active",
            google_email: "safe.user@example.com",
            scopes:
              "openid email https://www.googleapis.com/auth/drive.metadata.readonly https://www.googleapis.com/auth/documents",
            connected_at: "2026-07-28T00:00:00Z",
            revoked_at: null,
            configured: true,
            account_match: true,
            scope_ready: true,
            ready: true,
            reconnect_required: false,
          });
        if (url.endsWith("/api/google/connection"))
          return json({
            connected: true,
            status: "active",
            google_email: "safe.user@example.com",
            scopes: "openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly",
            connected_at: "2026-07-01T00:00:00",
            revoked_at: null,
            picker_configured: true,
            picker_scope_ready: true,
            picker_ready: true,
            reconnect_required: false,
          });
        if (url.endsWith("/api/google/oauth/start") && init?.method === "POST")
          return json(googleOauthStartFixture());
        if (
          url.endsWith("/api/projects/p1/jobs/batch") &&
          init?.method === "POST"
        )
          return json({ jobs: [], created_count: 0, replayed: false });
        return json({ ok: true });
      }),
    );
  });
  it("uses the authenticated platform shell as the default app entrypoint", async () => {
    render(<App />);
    await waitForPlatformOverview();
    expect(fetch).toHaveBeenCalledWith(
      "/api/auth/session",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("keeps a verified Yandex destination in preflight and restored composer drafts", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const original = baseFetch.getMockImplementation();
    const folder = { path: "disk:/", name: "Мой диск", is_folder: true, fingerprint: "f".repeat(64), mime_type: null, size_bytes: null, modified: null };
    const handle = "6f5d76f9-1ced-44a4-abf5-9ff96092687e";
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/yandex/resources/list") return json({ folder, items: [], next_offset: null });
      if (url === "/api/yandex/resources/select") return json({ ...folder, id: handle });
      if (url === "/api/projects/p1/output-folders/yandex-disk/verify") return json({ name: "Мой диск", web_view_url: "https://disk.yandex.ru/client/disk/", provider: "yandex_disk" });
      return original?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    await openSelectedProjectJobs();
    await chooseExistingSource(1, "Лекция 1");
    await userEvent.click(screen.getByRole("button", { name: "Выбрать папку Яндекс Диска для задачи 1" }));
    await userEvent.click(await screen.findByRole("button", { name: "Выбрать эту папку" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText(/Яндекс Диск · DOCX/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Проверить задачи \(1\)/ }));
    await screen.findByLabelText("Проверка перед созданием задач");
    const call = baseFetch.mock.calls.find(([url]) => String(url).endsWith("/jobs/batch/preflight"));
    expect(JSON.parse(String(call?.[1]?.body)).items[0]).toMatchObject({ source_id: "s1", output_folder_id: handle, output_provider: "yandex_disk" });
    expect(Object.values(sessionStorage).some((raw) => String(raw).includes('"provider":"yandex_disk"'))).toBe(true);
    expect(baseFetch.mock.calls.some(([url]) => String(url).endsWith("/jobs/batch"))).toBe(false);
  });

  it("undo restores an unstarted row, its title and position without creating jobs", async () => {
    renderApp();
    await openSelectedProjectJobs();
    await userEvent.type(screen.getByLabelText("Название документа задачи 1"), "Synthetic title");
    await userEvent.click(screen.getByRole("button", {name:"Добавить задачу",exact:true}));
    await userEvent.click(screen.getByRole("button", {name:"Удалить задачу 1",exact:true}));
    expect(screen.getByLabelText("Название документа задачи 1")).toHaveValue("");
    await userEvent.click(screen.getByRole("button", {name:"Отменить удаление задачи",exact:true}));
    expect(screen.getByLabelText("Название документа задачи 1")).toHaveValue("Synthetic title");
    expect(screen.getByLabelText("Название документа задачи 2")).toHaveValue("");
    const calls=(fetch as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls.filter(([url,init]) => String(url).endsWith("/jobs/batch") && init?.method === "POST")).toHaveLength(0);
  });

  it("selected cleanup keeps preview/confirmation gates and blocked selections", async () => {
    const mock=fetch as ReturnType<typeof vi.fn>;
    const original=mock.getMockImplementation();
    let removed=false;
    mock.mockImplementation((url:string,init?:RequestInit) => {
      if(url.includes("/sources/bulk-deletion/preview?")) {
        expect(new URL(url,"https://synthetic.test").searchParams.getAll("source_ids")).toEqual(["s1","s-local"]);
        return json({selection_ids:["s-local","s1"],preview_token:"a".repeat(64),eligible_count:1,blocked_count:1,listed_count:2,hidden_expired_count:0,eligible_bytes:1024,blocked_bytes:1024,eligible_unknown_size_count:0,blocked_unknown_size_count:0,blocked_reasons:{processing_job_uses_source:1},google_drive_files_deleted:0});
      }
      if(url.endsWith("/sources/bulk-deletion") && init?.method === "POST") {
        expect(JSON.parse(String(init.body))).toEqual({confirm_delete:true,expected_preview_token:"a".repeat(64),expected_eligible_count:1,expected_blocked_count:1,source_ids:["s1","s-local"]});
        removed=true;
        return json({ok:true,deleted_count:1,blocked_count:1,blocked_reasons:{processing_job_uses_source:1},cleanup_counts:{not_applicable:1},google_drive_files_deleted:0});
      }
      if(removed && url.endsWith("/projects/p1/sources") && !init?.method) return Promise.resolve(original?.(url,init)).then(async response => {const value=await response.json(); return json({...value,sources:value.sources.filter((source:{id:string}) => source.id !== "s1")});});
      return original?.(url,init) ?? json({ok:true});
    });
    renderApp();
    await openSettingsSection("Файлы и хранилище");
    await userEvent.click(await screen.findByRole("button",{name:"Выбрать загруженные файлы (до 50)",exact:true}));
    await userEvent.click(screen.getByRole("button",{name:"Убрать выбранные (2)",exact:true}));
    await screen.findByText("План очистки выбранных файлов");
    expect(mock.mock.calls.filter(([url,init]) => String(url).endsWith("/sources/bulk-deletion") && init?.method === "POST")).toHaveLength(0);
    await userEvent.click(screen.getByRole("button",{name:"Подтвердить очистку (1)",exact:true}));
    expect(await screen.findByText(/Из Studio убрано файлов: 1\. Пропущено: 1/)).toBeVisible();
    expect(screen.getByRole("checkbox",{name:"Выбрать файл: local-temp.ogg",exact:true})).toBeChecked();
    expect(mock.mock.calls.filter(([,init]) => init?.method === "DELETE")).toHaveLength(0);
  });

  it.each([undefined, ["other-source"]])("selected cleanup fails closed for legacy or mismatched API selection %s", async (selection) => {
    const mock=fetch as ReturnType<typeof vi.fn>;
    const original=mock.getMockImplementation();
    mock.mockImplementation((url:string,init?:RequestInit) => {
      if(url.includes("/sources/bulk-deletion/preview?")) return json({selection_ids:selection,preview_token:"a".repeat(64),eligible_count:1,blocked_count:1,listed_count:2,hidden_expired_count:0,eligible_bytes:1024,blocked_bytes:1024,eligible_unknown_size_count:0,blocked_unknown_size_count:0,blocked_reasons:{processing_job_uses_source:1},google_drive_files_deleted:0});
      return original?.(url,init) ?? json({});
    });
    renderApp();
    await openSettingsSection("Файлы и хранилище");
    await userEvent.click(await screen.findByRole("button",{name:"Выбрать загруженные файлы (до 50)",exact:true}));
    await userEvent.click(screen.getByRole("button",{name:"Убрать выбранные (2)",exact:true}));
    expect(await screen.findByText(/Studio не подтвердила выбранные файлы/)).toBeVisible();
    expect(screen.queryByRole("button",{name:/Подтвердить очистку/})).not.toBeInTheDocument();
    expect(mock.mock.calls.filter(([,init]) => init?.method === "DELETE" || (init?.method === "POST" && String(init.body).includes("confirm_delete")))).toHaveLength(0);
  });

  it("selected terminal dismissal confirms readback without starting transcription", async () => {
    installFocusedOutputFixture({jobStatus:"completed"});
    const mock=fetch as ReturnType<typeof vi.fn>;
    const original=mock.getMockImplementation();
    let dismissed=false;
    mock.mockImplementation((url:string,init?:RequestInit) => {
      if(url.endsWith("/jobs/job-focused/dismiss") && init?.method === "POST") {
        dismissed=true;
        return Promise.resolve(original?.("/api/jobs/job-focused")).then(async response => json({...await response.json(),terminal_dismissed_at:"2026-10-14T00:00:00Z"}));
      }
      if(dismissed && url.endsWith("/jobs/job-focused") && !init?.method) return Promise.resolve(original?.(url,init)).then(async response => json({...await response.json(),terminal_dismissed_at:"2026-10-14T00:00:00Z"}));
      return original?.(url,init) ?? json({});
    });
    await openFocusedJobsList();
    await userEvent.click(screen.getByRole("button",{name:"Выбрать завершённые (до 50)",exact:true}));
    await userEvent.click(screen.getByRole("button",{name:"Убрать выбранные в историю (1)",exact:true}));
    expect(await screen.findByText("Убрано в историю: 1 из 1. Не подтверждено: 0. Документы и расход сохранены.")).toBeVisible();
    expect(mock.mock.calls.filter(([url,init]) => String(url).endsWith("/dismiss") && init?.method === "POST")).toHaveLength(1);
    expect(mock.mock.calls.filter(([url,init]) => String(url).endsWith("/jobs/batch") && init?.method === "POST")).toHaveLength(0);
  });

  it("maintenance recovery reveals exact settings without granting OAuth", async () => {
    const mock=fetch as ReturnType<typeof vi.fn>;
    const original=mock.getMockImplementation();
    mock.mockImplementation((url:string,init?:RequestInit) => {
      if(url.endsWith("/google/maintenance/connection")) return json({connected:false,configured:true,status:"disconnected",google_email:null,scopes:null,connected_at:null,revoked_at:null,ready:false,scope_ready:false,account_match:false,reconnect_required:false});
      if(url.includes("/transcript-maintenance/runs?")) return json({run:null});
      return original?.(url,init) ?? json({});
    });
    renderApp();
    await openSelectedProjectJobs();
    await userEvent.click(screen.getByRole("tab",{name:"Обслуживание",exact:true}));
    await userEvent.click(await screen.findByRole("button",{name:"Настроить доступ Google",exact:true}));
    const panel=document.getElementById("google-maintenance-access") as HTMLDetailsElement;
    await waitFor(() => expect(panel.open).toBe(true));
    await waitFor(() => expect(within(panel).getByText("Расширенный доступ к готовым Google Docs")).toHaveFocus());
    const calls=(fetch as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls.filter(([url,init]) => String(url).includes("oauth/start") && init?.method === "POST")).toHaveLength(0);
  });

  it("keeps batch transcription intact and opens Live inside the selected project", async () => {
    renderApp();
    await openProjectsPage();
    expect(
      await screen.findByRole("form", { name: "Композитор пакетных задач" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: "Обычная транскрибация" }),
    ).toHaveAttribute("aria-selected", "true");

    const ordinaryTab = screen.getByRole("tab", {
      name: "Обычная транскрибация",
    });
    ordinaryTab.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(
      screen.getByRole("tab", { name: "Live-транскрибация" }),
    ).toHaveFocus();
    expect(
      screen.getByRole("tab", { name: "Live-транскрибация" }),
    ).toHaveAttribute("aria-selected", "true");
    const livePanel = await screen.findByRole("region", {
      name: "Live-транскрибация",
    });
    expect(livePanel).toBeInTheDocument();
    expect(
      screen.queryByRole("form", { name: "Композитор пакетных задач" }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Микрофон или аудиовход")).not.toBeChecked();
    expect(screen.getByLabelText("Звук вкладки или экрана")).toBeChecked();
    expect(screen.getByRole("button", { name: "Начать" })).toBeEnabled();
    expect(
      screen.getByText(/до ручной очистки; звук не сохраняется/i),
    ).toBeInTheDocument();

    const navigation = screen.getByRole("navigation", {
      name: "Основная навигация",
    });
    await userEvent.click(within(navigation).getByRole("button", { name: "Обзор" }));
    await waitFor(() =>
      expect(
        within(navigation).getByRole("button", { name: "Обзор" }),
      ).toHaveAttribute("aria-current", "page"),
    );
    expect(
      screen.getByRole("region", {
        name: "Live-транскрибация",
        hidden: true,
      }),
    ).toBe(livePanel);

    await userEvent.click(
      within(navigation).getByRole("button", { name: "Транскрибации" }),
    );
    expect(
      await screen.findByRole("region", { name: "Live-транскрибация" }),
    ).toBe(livePanel);

    await userEvent.click(
      screen.getByRole("tab", { name: "Обычная транскрибация" }),
    );
    expect(
      await screen.findByRole("form", { name: "Композитор пакетных задач" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", {
        name: "Live-транскрибация",
        hidden: true,
      }),
    ).toBe(livePanel);
    expect(livePanel.closest('[role="tabpanel"]')).toHaveAttribute("hidden");
  });

  it("exposes clear provider limits and keyboard-operable settings tabs", async () => {
    renderApp();
    await openSettingsSection("Подключения");

    expect(
      screen.getByRole("heading", { name: "Настройки", level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(6);
    await userEvent.click(screen.getByRole("tab", { name: "Подключения" }));
    expect(
      screen.getByText(/профили ElevenLabs и Yandex SpeechKit/i),
    ).toBeInTheDocument();

    const accountTab = screen.getByRole("tab", { name: "Аккаунт" });
    accountTab.focus();
    await userEvent.keyboard("{End}");
    const diagnosticsTab = screen.getByRole("tab", { name: "Для поддержки" });
    expect(diagnosticsTab).toHaveFocus();
    expect(diagnosticsTab).toHaveAttribute("aria-selected", "true");
    expect(
      await screen.findByRole("heading", { name: "Для поддержки" }),
    ).toBeInTheDocument();

    await userEvent.keyboard("{Home}");
    expect(accountTab).toHaveFocus();
    expect(accountTab).toHaveAttribute("aria-selected", "true");
  });

  it("opens approved Drive resource links in new tabs with compact action labels", async () => {
    renderApp();
    await openSettingsSection("Файлы и хранилище");

    expect(screen.queryByText("Папка по умолчанию")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", {
        name: "Открыть папку в Google Drive в новой вкладке",
      }),
    ).not.toBeInTheDocument();

    const sourceLink = await screen.findByRole("link", {
      name: "Открыть файл в Google Drive в новой вкладке",
    });
    expect(sourceLink).toHaveAttribute("href", "https://drive.example/file/1");
    expect(sourceLink).toHaveAttribute("target", "_blank");
    expect(sourceLink).toHaveAttribute("rel", "noopener noreferrer");
    expect(sourceLink).toHaveClass("button-like", "secondary", "resource-link");
    expect(sourceLink.closest(".resource-actions")).not.toBeNull();
    expect(sourceLink).toHaveTextContent("↗");
    expect(
      screen
        .getByRole("button", {
          name: "Убрать из Studio: Лекция 1. Личность как психологическое явление.flac",
        })
        .closest(".resource-actions"),
    ).not.toBeNull();
    expect(screen.getAllByText("Убрать из Studio")).toHaveLength(2);
    expect(
      screen.queryByRole("button", { name: "Удалить" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("Файл останется на Google Drive."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Временную копию удалит фоновая очистка Studio."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Убрать из Studio: local-temp.ogg" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Хранится до:/)).toBeInTheDocument();
    expect(
      screen.getByText("Лекция 1. Личность как психологическое явление.flac"),
    ).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("______");
  });

  it("previews and confirms a Studio-only bulk file cleanup", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = fetchMock.getMockImplementation();
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url === "/api/projects/p1/sources/bulk-deletion/preview" &&
        !init?.method
      ) {
        return json({
          preview_token: "a".repeat(64),
          eligible_count: 2,
          listed_count: 3,
          hidden_expired_count: 0,
          eligible_bytes: 3_072,
          eligible_unknown_size_count: 0,
          blocked_count: 1,
          blocked_bytes: 4_096,
          blocked_unknown_size_count: 0,
          blocked_reasons: { processing_job_uses_source: 1 },
          google_drive_files_deleted: 0,
        });
      }
      if (
        url === "/api/projects/p1/sources/bulk-deletion" &&
        init?.method === "POST"
      ) {
        return json({
          ok: true,
          deleted_count: 2,
          blocked_count: 1,
          blocked_reasons: { processing_job_uses_source: 1 },
          cleanup_counts: { not_applicable: 1, pending: 1 },
          google_drive_files_deleted: 0,
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openSettingsSection("Файлы и хранилище");
    await userEvent.click(
      screen.getByRole("button", { name: "Очистить все файлы" }),
    );

    const plan = await screen.findByRole("region", {
      name: "План очистки файлов Studio",
    });
    expect(plan).toHaveTextContent("Сейчас в списке файлов: 3");
    expect(plan).toHaveTextContent(
      "К окончательной очистке готовы записи Studio: 2",
    );
    expect(plan).toHaveTextContent("Будут пропущены: 1");
    expect(plan).toHaveTextContent("используются текущей обработкой: 1");
    expect(plan).toHaveTextContent(
      "Исходные файлы Google Drive останутся на месте",
    );

    await userEvent.click(
      within(plan).getByRole("button", { name: "Подтвердить очистку (2)" }),
    );
    expect(
      await screen.findByText(
        "Из Studio убрано файлов: 2. Пропущено: 1. Файлы Google Drive не удалялись.",
      ),
    ).toBeInTheDocument();

    const mutation = fetchMock.mock.calls.find(
      ([url, init]) =>
        url === "/api/projects/p1/sources/bulk-deletion" &&
        init?.method === "POST",
    );
    expect(mutation).toBeDefined();
    expect(JSON.parse(String(mutation?.[1]?.body))).toEqual({
      confirm_delete: true,
      expected_preview_token: "a".repeat(64),
      expected_eligible_count: 2,
      expected_blocked_count: 1,
    });
  });

  it("explains expired cleanup records that are hidden from the current file list", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = fetchMock.getMockImplementation();
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url === "/api/projects/p1/sources/bulk-deletion/preview" &&
        !init?.method
      ) {
        return json({
          preview_token: "b".repeat(64),
          eligible_count: 7,
          listed_count: 0,
          hidden_expired_count: 7,
          eligible_bytes: 508_110_000,
          eligible_unknown_size_count: 0,
          blocked_count: 0,
          blocked_bytes: 0,
          blocked_unknown_size_count: 0,
          blocked_reasons: {},
          google_drive_files_deleted: 0,
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openSettingsSection("Файлы и хранилище");
    await userEvent.click(
      screen.getByRole("button", { name: "Очистить все файлы" }),
    );

    const plan = await screen.findByRole("region", {
      name: "План очистки файлов Studio",
    });
    expect(plan).toHaveTextContent("Сейчас в списке файлов: 0");
    expect(plan).toHaveTextContent(
      "Истёкших записей, скрытых после окончания срока хранения: 7",
    );
    expect(plan).toHaveTextContent(
      "К окончательной очистке готовы записи Studio: 7",
    );
  });

  it("explains when bulk cleanup needs recent reauthentication", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = fetchMock.getMockImplementation();
    let reauthenticated = false;
    let cleanupPosts = 0;
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/auth/reauth" && init?.method === "POST") {
        reauthenticated = true;
        return json({ ok: true });
      }
      if (
        url === "/api/projects/p1/sources/bulk-deletion/preview" &&
        !init?.method
      ) {
        return json({
          preview_token: "c".repeat(64),
          eligible_count: 1,
          listed_count: 1,
          hidden_expired_count: 0,
          eligible_bytes: 1024,
          eligible_unknown_size_count: 0,
          blocked_count: 0,
          blocked_bytes: 0,
          blocked_unknown_size_count: 0,
          blocked_reasons: {},
          google_drive_files_deleted: 0,
        });
      }
      if (
        url === "/api/projects/p1/sources/bulk-deletion" &&
        init?.method === "POST"
      ) {
        cleanupPosts += 1;
        if (reauthenticated) return json({ ok: true, deleted_count: 1, blocked_count: 0, blocked_reasons: {}, cleanup_counts: { pending: 1 }, google_drive_files_deleted: 0 });
        return json(
          { detail: { reason: "recent_reauthentication_required" } },
          false,
          409,
        );
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openSettingsSection("Файлы и хранилище");
    await userEvent.click(
      screen.getByRole("button", { name: "Очистить все файлы" }),
    );
    const plan = await screen.findByRole("region", {
      name: "План очистки файлов Studio",
    });
    await userEvent.click(
      within(plan).getByRole("button", { name: "Подтвердить очистку (1)" }),
    );

    expect(
      await screen.findByText(
        "Сначала подтвердите личность в разделе «Аккаунт», затем повторите очистку.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Подтвердить очистку (1)" }),
    ).toBeInTheDocument();
    expect(cleanupPosts).toBe(1);
    await userEvent.click(screen.getByRole("tab", { name: "Аккаунт" }));
    const security = screen.getByRole("region", { name: "Защита аккаунта" });
    await userEvent.type(within(security).getByLabelText("Пароль"), "synthetic-test-password");
    await userEvent.click(within(security).getByRole("button", { name: "Подтвердить личность" }));
    await waitFor(() => expect(reauthenticated).toBe(true));
    await userEvent.click(screen.getByRole("tab", { name: "Файлы и хранилище" }));
    await userEvent.click(screen.getByRole("button", { name: "Подтвердить очистку (1)" }));
    expect(await screen.findByText("Из Studio убрано файлов: 1. Пропущено: 0. Файлы Google Drive не удалялись.")).toBeVisible();
    expect(cleanupPosts).toBe(2);
    expect(screen.queryByRole("region", { name: "План очистки файлов Studio" })).not.toBeInTheDocument();
  });

  it("removes a Drive source only from the active project list", async () => {
    let sourceLoads = 0;
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string, init?: RequestInit) => {
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
          });
        if (url.endsWith("/api/auth/csrf")) return json({ csrf_token: "csrf" });
        if (url.endsWith("/api/projects"))
          return json({
            projects: [
              {
                id: "p1",
                title: "Research calls",
                description: null,
                created_at: "2026-07-01T00:00:00",
                updated_at: "2026-07-01T00:00:00",
                archived_at: null,
                output_drive_folder_id: "folder-default",
                output_drive_folder_url:
                  "https://drive.google.com/drive/folders/folder-default",
                output_drive_folder_name: "Default folder",
              },
            ],
          });
        if (url.endsWith("/api/projects/p1/jobs") && !init?.method)
          return json({ jobs: [] });
        if (url.endsWith("/api/projects/p1/sources") && !init?.method) {
          sourceLoads += 1;
          return json({
            sources:
              sourceLoads === 1
                ? [
                    {
                      id: "s1",
                      project_id: "p1",
                      source_type: "google_drive",
                      original_filename:
                        "Лекция 1. Личность как психологическое явление.flac",
                      mime_type: "audio/flac",
                      size_bytes: 2048,
                      drive_file_id: "drive-file-1",
                      drive_file_url:
                        "https://drive.google.com/file/d/drive-file-1/view",
                      upload_status: "uploaded",
                      uploaded_at: "2026-07-01T00:01:00",
                      expires_at: null,
                      deleted_at: null,
                      delete_reason: null,
                      created_at: "2026-07-01T00:00:00",
                      updated_at: "2026-07-01T00:00:00",
                    },
                  ]
                : [],
          });
        }
        if (url.endsWith("/api/sources/s1") && init?.method === "DELETE")
          return json({
            ok: true,
            source_state: "deleted",
            storage_cleanup: "not_applicable",
          });
        if (url.endsWith("/api/google/connection"))
          return json({
            connected: true,
            status: "active",
            google_email: "safe.user@example.com",
            scopes: "openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly",
            connected_at: "2026-07-01T00:00:00",
            revoked_at: null,
            picker_configured: true,
            picker_scope_ready: true,
            picker_ready: true,
            reconnect_required: false,
          });
        if (url.endsWith("/api/credentials"))
          return json({
            credentials: [
              {
                id: "cred-active",
                provider: "elevenlabs",
                label: "Primary STT",
                status: "active",
                masked_value: "••••1234",
                active_version: 2,
              },
            ],
          });
        if (url.endsWith("/api/audit-events")) return json({ events: [] });
        return json({ ok: true });
      },
    );
    renderApp();
    await openSettingsSection("Файлы и хранилище");
    const removeButton = await screen.findByRole("button", {
      name: "Убрать из Studio: Лекция 1. Личность как психологическое явление.flac",
    });
    await userEvent.click(removeButton);
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/sources/s1",
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(
        ([url, init]) =>
          String(url).includes("google") &&
          ["DELETE", "PATCH", "PUT", "POST"].includes(String(init?.method)),
      ),
    ).toBe(false);
    expect(
      await screen.findByText("Источники пока не добавлены."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Лекция 1. Личность как психологическое явление.flac"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", {
        name: "Открыть файл в Google Drive в новой вкладке",
      }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/Лекция 1\. Личность/)).not.toBeInTheDocument();
  });

  it("refreshes the transcription source picker after a file is removed in Settings", async () => {
    let sourceAvailable = true;
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/projects/p1/sources" && !init?.method) {
        return json({
          sources: sourceAvailable
            ? [
                {
                  id: "s1",
                  project_id: "p1",
                  source_type: "google_drive",
                  original_filename:
                    "Лекция 1. Личность как психологическое явление.flac",
                  mime_type: "audio/flac",
                  size_bytes: 2048,
                  drive_file_url:
                    "https://drive.google.com/file/d/drive-file-1/view",
                  upload_status: "uploaded",
                  uploaded_at: "2026-07-01T00:01:00Z",
                  source_created_at: "2026-07-01T00:00:00Z",
                  source_created_at_provenance: "google_drive_created_time",
                  expires_at: null,
                  deleted_at: null,
                  delete_reason: null,
                  created_at: "2026-07-01T00:00:00Z",
                  updated_at: "2026-07-01T00:00:00Z",
                },
              ]
            : [],
        });
      }
      if (url === "/api/sources/s1" && init?.method === "DELETE") {
        sourceAvailable = false;
        return json({
          ok: true,
          source_state: "deleted",
          storage_cleanup: "not_applicable",
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();
    const sourceSelect = await screen.findByLabelText(
      "Существующий файл для задачи 1",
    );
    expect(
      within(sourceSelect).getByRole("option", {
        name: /Лекция 1\. Личность как психологическое явление\.flac/,
      }),
    ).toBeInTheDocument();

    await openSettingsSection("Файлы и хранилище");
    await userEvent.click(
      await screen.findByRole("button", {
        name: "Убрать из Studio: Лекция 1. Личность как психологическое явление.flac",
      }),
    );
    expect(
      await screen.findByText("Источники пока не добавлены."),
    ).toBeInTheDocument();

    await openProjectsPage();
    const refreshedSelect = await screen.findByLabelText(
      "Существующий файл для задачи 1",
    );
    await waitFor(() =>
      expect(
        within(refreshedSelect).queryByRole("option", {
          name: /Лекция 1\. Личность как психологическое явление\.flac/,
        }),
      ).not.toBeInTheDocument(),
    );
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          url === "/api/projects/p1/sources" && !init?.method,
      ).length,
    ).toBeGreaterThanOrEqual(3);
  });



  it("fails source removal closed when confirmation throws", async () => {
    vi.spyOn(window, "confirm").mockImplementation(() => {
      throw new Error("confirm unavailable");
    });
    renderApp();
    await openSettingsSection("Файлы и хранилище");
    await userEvent.click(
      screen.getByRole("button", { name: "Убрать из Studio: local-temp.ogg" }),
    );
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(
        ([url, init]) => String(url).endsWith("/api/sources/s-local") && init?.method === "DELETE",
      ),
    ).toBe(false);
  });

  it("confirms source removal text and sends at most one DELETE", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderApp();
    await openSettingsSection("Файлы и хранилище");
    await userEvent.click(
      screen.getByRole("button", {
        name: "Убрать из Studio: Лекция 1. Личность как психологическое явление.flac",
      }),
    );
    expect(confirm).toHaveBeenCalledWith(
      "Источник будет убран только из Studio. Файл останется на Google Drive. Старые неудачные задачи сохранятся в истории, но повтор с этим источником станет недоступен.",
    );
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(
        ([url, init]) => String(url).endsWith("/api/sources/s1") && init?.method === "DELETE",
      ),
    ).toBe(false);

    confirm.mockReturnValue(true);
    await userEvent.click(
      screen.getByRole("button", { name: "Убрать из Studio: local-temp.ogg" }),
    );
    expect(confirm).toHaveBeenLastCalledWith(
      "Источник будет убран из Studio. Временная копия будет удалена из хранилища после безопасной проверки связанных задач. Старые неудачные задачи сохранятся в истории, но повтор с этим источником станет недоступен.",
    );
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.filter(
        ([url, init]) => String(url).endsWith("/api/sources/s-local") && init?.method === "DELETE",
      ),
    ).toHaveLength(1);
  });

  it("bounds and deduplicates stalled source deletion before reconciling absence", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const requestSignals: AbortSignal[] = [];
    let deleteStarted = false;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/sources/s1" && !init?.method && deleteStarted)
        return json({}, false, 404);
      if (url === "/api/sources/s1" && init?.method === "DELETE") {
        deleteStarted = true;
        const signal = init.signal;
        if (!signal) throw new Error("source deletion signal is missing");
        requestSignals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openSettingsSection("Файлы и хранилище");
    const removeButton = screen.getByRole("button", {
      name: "Убрать из Studio: Лекция 1. Личность как психологическое явление.flac",
    });

    vi.useFakeTimers();
    try {
      fireEvent.click(removeButton);
      fireEvent.click(removeButton);
      await act(async () => {
        await Promise.resolve();
      });

      expect(requestSignals).toHaveLength(1);
      expect(removeButton).toBeDisabled();
      expect(removeButton).toHaveAttribute("aria-busy", "true");

      await act(async () => {
        await vi.advanceTimersByTimeAsync(20_000);
      });

      expect(requestSignals[0]?.aborted).toBe(true);
      expect(
        baseFetch.mock.calls.some(
          ([url, init]) =>
            url === "/api/sources/s1" &&
            init?.cache === "no-store",
        ),
      ).toBe(true);
      expect(
        baseFetch.mock.calls.filter(
          ([url, init]) =>
            url === "/api/sources/s1" && init?.method === "DELETE",
        ),
      ).toHaveLength(1);
      expect(screen.getByText("Файл убран из Studio.")).toBeInTheDocument();
      expect(
        screen.queryByText("Лекция 1. Личность как психологическое явление.flac"),
      ).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
  it("keeps a source visible when an ambiguous deletion is not reconciled", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/sources/s1" && init?.method === "DELETE") {
        return Promise.reject(new TypeError("raw transport detail"));
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openSettingsSection("Файлы и хранилище");
    const removeButton = screen.getByRole("button", {
      name: "Убрать из Studio: Лекция 1. Личность как психологическое явление.flac",
    });
    await userEvent.click(removeButton);

    expect(
      await screen.findByText(
        "Studio не подтвердила удаление файла. Список обновлён; подождите и повторите при необходимости.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Лекция 1. Личность как психологическое явление.flac"),
    ).toBeInTheDocument();
    await waitFor(() => expect(removeButton).toBeEnabled());
    expect(removeButton).toHaveAttribute("aria-busy", "false");
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          url === "/api/sources/s1" && init?.method === "DELETE",
      ),
    ).toHaveLength(1);
    expect(document.body).not.toHaveTextContent("raw transport detail");
  });
  it("reports queued background cleanup after removing an uploaded local source", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url.endsWith("/api/sources/s-local") &&
        init?.method === "DELETE"
      )
        return json({
          ok: true,
          source_state: "deleted",
          storage_cleanup: "pending",
        });
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    await openSettingsSection("Файлы и хранилище");
    await userEvent.click(
      screen.getByRole("button", { name: "Убрать из Studio: local-temp.ogg" }),
    );
    expect(
      await screen.findByText(
        "Файл убран из Studio. Временная копия поставлена в очередь фонового удаления; выбранный срок хранения ждать не нужно.",
      ),
    ).toBeInTheDocument();
  });

  it("keeps a source visible when an inconsistent delete reload fails", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let failSourceReload = false;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        failSourceReload &&
        url.endsWith("/api/projects/p1/sources") &&
        !init?.method
      )
        return json({ detail: "raw source reload failure" }, false, 500);
      if (
        url.endsWith("/api/sources/s-local") &&
        init?.method === "DELETE"
      )
        return json({
          ok: false,
          source_state: "uploaded",
          storage_cleanup: "not_applicable",
        });
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    await openSettingsSection("Файлы и хранилище");
    expect(await screen.findByText("local-temp.ogg")).toBeInTheDocument();
    failSourceReload = true;
    await userEvent.click(
      screen.getByRole("button", { name: "Убрать из Studio: local-temp.ogg" }),
    );

    expect(
      await screen.findByText(
        "Studio вернула несогласованное подтверждение удаления. Список файлов обновлён.",
      ),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Не удалось загрузить сохранённые файлы Studio."),
    ).toBeInTheDocument();
    expect(screen.getByText("local-temp.ogg")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("raw source reload failure");
    expect(
      screen.queryByText(/Временная копия поставлена в очередь/),
    ).not.toBeInTheDocument();
  });

  it.each([
    ["queued_job_uses_source", "Сначала отмените ожидающие задачи, использующие этот файл."],
    ["processing_job_uses_source", "Дождитесь завершения или отмены текущей обработки."],
    ["retryable_failed_job_uses_source", "Источник нужен для доступного безопасного повтора задачи."],
    ["audio_preparation_uses_source", "Сначала завершите или отмените подготовку аудио, использующую этот файл."],
  ])("shows safe blocked-removal message for %s", async (reason, message) => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/sources/s-local") && init?.method === "DELETE")
        return json({ detail: { reason } }, false, 409);
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    await openSettingsSection("Файлы и хранилище");
    await userEvent.click(
      screen.getByRole("button", { name: "Убрать из Studio: local-temp.ogg" }),
    );
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("job_");
    expect(document.body.textContent).not.toContain("cleanup_owner");
    expect(document.body.textContent).not.toContain("retry_stage");
  });

  it("shows only the latest source deletion notice", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = fetchMock.getMockImplementation();
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/sources/s-local") && init?.method === "DELETE") {
        return json(
          { detail: { reason: "audio_preparation_uses_source" } },
          false,
          409,
        );
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openSettingsSection("Файлы и хранилище");
    await userEvent.click(
      screen.getByRole("button", {
        name: "Убрать из Studio: Лекция 1. Личность как психологическое явление.flac",
      }),
    );
    expect(await screen.findByText("Файл убран из Studio.")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Убрать из Studio: local-temp.ogg" }),
    );
    expect(
      await screen.findByText(
        "Сначала завершите или отмените подготовку аудио, использующую этот файл.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Файл убран из Studio.")).not.toBeInTheDocument();
  });

  it("keeps the source card and shows a safe ambiguous outcome after a 5xx removal", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string, init?: RequestInit) => {
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
          });
        if (url.endsWith("/api/auth/csrf")) return json({ csrf_token: "csrf" });
        if (url.endsWith("/api/projects"))
          return json({
            projects: [
              {
                id: "p1",
                title: "Research calls",
                description: null,
                created_at: "2026-07-01T00:00:00",
                updated_at: "2026-07-01T00:00:00",
                archived_at: null,
                output_drive_folder_id: null,
                output_drive_folder_url: null,
                output_drive_folder_name: null,
              },
            ],
          });
        if (url.endsWith("/api/projects/p1/jobs") && !init?.method)
          return json({ jobs: [] });
        if (url.endsWith("/api/projects/p1/sources") && !init?.method)
          return json({
            sources: [
              {
                id: "s1",
                project_id: "p1",
                source_type: "google_drive",
                original_filename: "safe-drive.mp4",
                mime_type: "video/mp4",
                size_bytes: 2048,
                drive_file_id: "drive-file-1",
                drive_file_url:
                  "https://drive.google.com/file/d/drive-file-1/view",
                upload_status: "uploaded",
                uploaded_at: "2026-07-01T00:01:00",
                expires_at: null,
                deleted_at: null,
                delete_reason: null,
                created_at: "2026-07-01T00:00:00",
                updated_at: "2026-07-01T00:00:00",
              },
            ],
          });
        if (url.endsWith("/api/sources/s1") && init?.method === "DELETE")
          return json({}, false, 500);
        if (url.endsWith("/api/google/connection"))
          return json({
            connected: true,
            status: "active",
            google_email: "safe.user@example.com",
            scopes: "openid email",
            connected_at: "2026-07-01T00:00:00",
            revoked_at: null,
            picker_configured: false,
            picker_scope_ready: false,
            picker_ready: false,
            reconnect_required: false,
          });
        if (url.endsWith("/api/credentials"))
          return json({
            credentials: [
              {
                id: "cred-active",
                provider: "elevenlabs",
                label: "Primary STT",
                status: "active",
                masked_value: "••••1234",
                active_version: 2,
              },
            ],
          });
        if (url.endsWith("/api/audit-events")) return json({ events: [] });
        return json({ ok: true });
      },
    );
    renderApp();
    await openSettingsSection("Файлы и хранилище");
    await userEvent.click(
      await screen.findByRole("button", {
        name: "Убрать из Studio: safe-drive.mp4",
      }),
    );
    expect(
      await screen.findByText(
        "Studio не подтвердила удаление файла. Список обновлён; подождите и повторите при необходимости.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("safe-drive.mp4")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("удален с Google Drive");
  });

  it("renders actionable dashboard summaries without exposing project lifecycle", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/projects") && !init?.method)
        return json({
          projects: [
            {
              id: "older",
              title: "Older",
              description: null,
              created_at: "2026-07-01T00:00:00Z",
              updated_at: "2026-07-01T00:00:00Z",
              archived_at: null,
              output_drive_folder_id: null,
              output_drive_folder_url: null,
              output_drive_folder_name: null,
            },
            {
              id: "newer",
              title: "Newer",
              description: "Latest notes",
              created_at: "2026-07-02T00:00:00Z",
              updated_at: "2026-07-03T00:00:00Z",
              archived_at: null,
              output_drive_folder_id: "folder-new",
              output_drive_folder_url: "https://drive.example/folders/new",
              output_drive_folder_name: "Ready folder",
            },
          ],
        });
      if (url.endsWith("/api/google/connection"))
        return json({
          connected: true,
          status: "active",
          google_email: "user@example.com",
          scopes: "openid email",
          connected_at: "2026-07-01T00:00:00Z",
          revoked_at: null,
          picker_ready: true,
          picker_configured: true,
          picker_scope_ready: true,
          reconnect_required: false,
        });
      if (url.endsWith("/api/credentials"))
        return json({
          credentials: [
            {
              id: "c1",
              provider: "elevenlabs",
              label: "main",
              status: "active",
              masked_value: "••••1234",
              active_version: 1,
            },
          ],
        });
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    await waitForPlatformOverview();
    expect(screen.getByLabelText("Последние результаты")).toHaveTextContent(
      "Недоступно",
    );
    expect(screen.getByLabelText("Google Drive")).toHaveTextContent(
      "Подключён",
    );
    expect(screen.getByLabelText("Готовность к работе")).toHaveTextContent(
      "Можно начинать",
    );
    expect(
      screen.getByRole("heading", { name: "Последние документы" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Newer")).not.toBeInTheDocument();
    expect(screen.queryByText("Older")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Новый проект/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Требует внимания")).not.toBeInTheDocument();
  });

  it("explains automatic workspace creation from the empty dashboard", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/projects") && !init?.method)
        return json({ projects: [] });
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    await waitForPlatformOverview();
    expect(await screen.findByText("Начать работу")).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: "Создать транскрибацию" }).length,
    ).toBeGreaterThan(0);
    expect(screen.getByLabelText("Последние результаты")).toHaveTextContent(
      "Начните с первой записи",
    );
  });

  it("keeps successful dashboard data when one dashboard request fails without raw errors", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/google/connection"))
        return json({ detail: "Traceback raw stack" }, false, 500);
      if (url.endsWith("/api/credentials"))
        return json({
          credentials: [
            {
              id: "c1",
              provider: "elevenlabs",
              label: "main",
              status: "active",
              masked_value: "••••1234",
              active_version: 1,
            },
          ],
        });
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    await waitForPlatformOverview();
    expect(screen.getByLabelText("Последние результаты")).toHaveTextContent(
      "Последних задач: 0",
    );
    expect(screen.getByLabelText("Google Drive")).toHaveTextContent(
      "Недоступно",
    );
    expect(screen.getByLabelText("Готовность к работе")).toHaveTextContent(
      "Недоступно",
    );
    expect(screen.getByText(/Часть данных панели/)).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Подключите или обновите Google Drive для выбора файлов и папок.",
      ),
    ).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("Traceback raw stack");
  });

  it("bounds the dashboard Google connection read and retries explicitly", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const connectionSignals: AbortSignal[] = [];
    let connectionReads = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/google/connection" && !init?.method) {
        connectionReads += 1;
        if (connectionReads > 1) {
          return json(
            googleConnectionFixture({
              connected: true,
              status: "active",
              google_email: "safe.user@example.com",
              scopes: "openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly",
              connected_at: "2026-08-13T12:00:00Z",
              picker_configured: true,
              picker_scope_ready: true,
              picker_ready: true,
            }),
          );
        }
        const signal = init.signal;
        if (!signal) throw new Error("Google connection signal is missing");
        connectionSignals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 15_000 ? 1 : (delay as number),
          ...args,
        )) as typeof setTimeout);

    try {
      renderApp();
      await waitForPlatformOverview();
      const card = screen.getByLabelText("Google Drive");
      await waitFor(() => expect(card).toHaveTextContent("Недоступно"));
      expect(connectionSignals).toHaveLength(1);
      expect(connectionSignals[0]?.aborted).toBe(true);
      await userEvent.click(
        within(card).getByRole("button", { name: "Повторить" }),
      );
      await waitFor(() => expect(card).toHaveTextContent("Подключён"));
      expect(connectionReads).toBe(2);
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("fails Projects Google connection closed on malformed data and retries", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let connectionReads = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/google/connection" && !init?.method) {
        connectionReads += 1;
        if (connectionReads === 2) {
          return json(
            googleConnectionFixture({
              connected: true,
              status: null,
              raw_refresh_token: "raw-projects-google-secret",
            }),
          );
        }
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    expect(
      await screen.findByText("Не удалось проверить подключение Google Drive."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Выбрать файлы Google Drive" }),
    ).toBeDisabled();
    expect(document.body.textContent).not.toContain("raw-projects-google-secret");
    expect(document.body.textContent).not.toContain("Google Drive не подключён.");

    await userEvent.click(
      screen.getByRole("button", {
        name: "Повторить проверку Google Drive",
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Выбрать файлы Google Drive" }),
      ).toBeEnabled(),
    );
    expect(connectionReads).toBe(3);
  });

  it("keeps the latest Projects Google state after a late pre-remount read", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let connectionReads = 0;
    let resolveFirstProjectsRead: ((response: Response) => void) | undefined;
    const connected = googleConnectionFixture({
      connected: true,
      status: "active",
      google_email: "safe.user@example.com",
      scopes: "openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly",
      connected_at: "2026-08-13T12:00:00Z",
      picker_configured: true,
      picker_scope_ready: true,
      picker_ready: true,
    });
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/google/connection" && !init?.method) {
        connectionReads += 1;
        if (connectionReads === 1) return json(connected);
        if (connectionReads === 2) {
          return new Promise<Response>((resolve) => {
            resolveFirstProjectsRead = resolve;
          });
        }
        return json(googleConnectionFixture());
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();
    await waitFor(() => expect(resolveFirstProjectsRead).toBeDefined());
    await openSettingsSection("Подключения");
    await screen.findByText("Google Drive не подключён");
    await openProjectsPage();
    expect(
      await screen.findByText("Google Drive не подключён."),
    ).toBeInTheDocument();
    const driveButton = screen.getByRole("button", { name: "Выбрать файлы Google Drive" });
    expect(driveButton).toBeDisabled();

    await act(async () => resolveFirstProjectsRead?.(await json(connected)));
    expect(screen.getByText("Google Drive не подключён.")).toBeInTheDocument();
    expect(driveButton).toBeDisabled();
    expect(connectionReads).toBe(4);
  });

  it("bounds dashboard project and credential reads with independent retries", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const projectSignals: AbortSignal[] = [];
    const credentialSignals: AbortSignal[] = [];
    let projectReads = 0;
    let credentialReads = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/projects" && !init?.method) {
        projectReads += 1;
        if (projectReads > 1) return defaultFetch?.(url, init) ?? json({ projects: [] });
        const signal = init.signal;
        if (!signal) throw new Error("Project signal is missing");
        projectSignals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      }
      if (url === "/api/credentials" && !init?.method) {
        credentialReads += 1;
        if (credentialReads > 1)
          return defaultFetch?.(url, init) ?? json({ credentials: [] });
        const signal = init.signal;
        if (!signal) throw new Error("Credential signal is missing");
        credentialSignals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 15_000 ? 1 : (delay as number),
          ...args,
        )) as typeof setTimeout);

    try {
      renderApp();
      await waitForPlatformOverview();
      const projectsCard = screen.getByLabelText("Последние результаты");
      const credentialsCard = screen.getByLabelText("Готовность к работе");
      await waitFor(() => expect(projectsCard).toHaveTextContent("Недоступно"));
      await waitFor(() => expect(credentialsCard).toHaveTextContent("Недоступно"));
      expect(screen.getByLabelText("Google Drive")).toHaveTextContent("Подключён");
      expect(projectSignals[0]?.aborted).toBe(true);
      expect(credentialSignals[0]?.aborted).toBe(true);

      await userEvent.click(
        within(projectsCard).getByRole("button", { name: "Повторить" }),
      );
      await userEvent.click(
        within(credentialsCard).getByRole("button", { name: "Повторить" }),
      );
      await waitFor(() => expect(projectsCard).toHaveTextContent("Последних задач: 0"));
      await waitFor(() => expect(credentialsCard).toHaveTextContent("Можно начинать"));
      expect(projectReads).toBe(2);
      expect(credentialReads).toBe(2);
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("rejects duplicate dashboard collections without rendering raw fields", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let projectReads = 0;
    let credentialReads = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/projects" && !init?.method) {
        projectReads += 1;
        if (projectReads === 1) {
          return json({
            projects: [
              projectFixture({ id: "duplicate", title: "raw-project-value" }),
              projectFixture({ id: "duplicate", title: "other duplicate" }),
            ],
          });
        }
      }
      if (url === "/api/credentials" && !init?.method) {
        credentialReads += 1;
        if (credentialReads === 1) {
          return json({
            credentials: [
              credentialFixture({
                id: "duplicate",
                masked_value: "raw-credential-value",
              }),
              credentialFixture({ id: "duplicate", label: "duplicate label" }),
            ],
          });
        }
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await waitForPlatformOverview();
    const projectsCard = screen.getByLabelText("Последние результаты");
    const credentialsCard = screen.getByLabelText("Готовность к работе");
    await waitFor(() => expect(projectsCard).toHaveTextContent("Недоступно"));
    await waitFor(() => expect(credentialsCard).toHaveTextContent("Недоступно"));
    expect(document.body.textContent).not.toContain("raw-project-value");
    expect(document.body.textContent).not.toContain("raw-credential-value");

    await userEvent.click(
      within(projectsCard).getByRole("button", { name: "Повторить" }),
    );
    await userEvent.click(
      within(credentialsCard).getByRole("button", { name: "Повторить" }),
    );
    await waitFor(() => expect(projectsCard).toHaveTextContent("Последних задач: 0"));
    await waitFor(() => expect(credentialsCard).toHaveTextContent("Можно начинать"));
  });

  it("ignores a late dashboard project retry after Overview remount", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let projectReads = 0;
    let olderRetrySignal: AbortSignal | undefined;
    let resolveOlderRetry: ((response: Response) => void) | undefined;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/projects" && !init?.method) {
        projectReads += 1;
        if (projectReads === 1)
          return json({ detail: "raw-project-failure" }, false, 503);
        if (projectReads === 2) {
          olderRetrySignal = init.signal;
          return new Promise<Response>((resolve) => {
            resolveOlderRetry = resolve;
          });
        }
        if (projectReads === 4) {
          return json({
            projects: [
              projectFixture({ id: "new-1", title: "Newest one" }),
              projectFixture({ id: "new-2", title: "Newest two" }),
            ],
          });
        }
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await waitForPlatformOverview();
    const initialProjectsCard = screen.getByLabelText("Последние результаты");
    await waitFor(() =>
      expect(initialProjectsCard).toHaveTextContent("Недоступно"),
    );
    await userEvent.click(
      within(initialProjectsCard).getByRole("button", { name: "Повторить" }),
    );
    await waitFor(() => expect(resolveOlderRetry).toBeDefined());

    await openProjectsPage();
    expect(olderRetrySignal?.aborted).toBe(true);
    await openPlatformNavPage("Обзор");
    await waitForPlatformOverview();
    const currentProjectsCard = screen.getByLabelText("Последние результаты");
    await waitFor(() =>
      expect(currentProjectsCard).toHaveTextContent("Недоступно"),
    );
    expect(screen.queryByText("Newest one")).not.toBeInTheDocument();
    expect(projectReads).toBe(4);

    await act(async () =>
      resolveOlderRetry?.(
        await json({
          projects: [projectFixture({ id: "old", title: "Late older result" })],
        }),
      ),
    );
    expect(currentProjectsCard).toHaveTextContent("Недоступно");
    expect(screen.queryByText("Late older result")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("raw-project-failure");
  });

  it("opens transcriptions from the dashboard without manual project CRUD", async () => {
    renderApp();
    await waitForPlatformOverview();

    await userEvent.click(
      within(await screen.findByRole("banner")).getByRole("button", {
        name: "Создать транскрибацию",
      }),
    );

    expect(
      await screen.findByRole("heading", { name: "Транскрибации" }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe("/transcriptions");
    expect(
      screen.getByRole("tab", { name: "Обычная транскрибация" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: "Live-транскрибация" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Новый проект" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Архивировать" }),
    ).not.toBeInTheDocument();
  });

  it("opens audio preparation from the dashboard", async () => {
    renderApp();
    await waitForPlatformOverview();

    await userEvent.click(
      within(await screen.findByRole("banner")).getByRole("button", {
        name: "Подготовить аудио",
      }),
    );

    expect(
      await screen.findByRole("heading", { name: "Подготовка аудио" }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe("/audio");
  });

  it("keeps a finished browser-only WAV available across section navigation and opens the new section at its heading", async () => {
    class FakeAudioContext {
      async decodeAudioData() {
        const channel = Float32Array.from([0.2, -0.2]);
        return { length: 2, numberOfChannels: 1, sampleRate: 48_000, getChannelData: () => channel } as AudioBuffer;
      }
      async close() { return undefined; }
    }
    vi.stubGlobal("AudioContext", FakeAudioContext);
    const createUrl = vi.fn(() => "blob:ux-audit-result");
    const revokeUrl = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createUrl });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeUrl });
    const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    Object.defineProperty(window, "scrollY", { configurable: true, value: 490 });
    try {
      renderApp();
      await waitForPlatformOverview();
      const navigation = screen.getByRole("navigation", { name: "Основная навигация" });
      await userEvent.click(within(navigation).getByRole("button", { name: "Подготовка аудио" }));
      const heading = await screen.findByRole("heading", { name: "Подготовка аудио" });
      expect(heading).toHaveFocus();
      expect(scrollTo).toHaveBeenCalledWith(0, 0);
      await userEvent.click(screen.getByRole("tab", { name: "Обработать на устройстве" }));
      const file = new File(["encoded"], "safe.wav", { type: "audio/wav" });
      Object.defineProperty(file, "arrayBuffer", { value: async () => new TextEncoder().encode("encoded").buffer });
      await userEvent.upload(screen.getByLabelText("Выбрать файлы для обработки на устройстве"), file);
      await userEvent.click(screen.getByRole("button", { name: "Обработать на устройстве" }));
      const download = await screen.findByRole("link", { name: "Скачать файл" });
      expect(download).toHaveAttribute("href", "blob:ux-audit-result");
      expect(createUrl).toHaveBeenCalledOnce();

      await userEvent.click(within(navigation).getByRole("button", { name: "Обзор" }));
      expect(screen.queryByRole("link", { name: "Скачать файл" })).not.toBeInTheDocument();
      expect(revokeUrl).not.toHaveBeenCalled();
      await userEvent.click(within(navigation).getByRole("button", { name: "Подготовка аудио" }));
      expect(screen.getByRole("link", { name: "Скачать файл" })).toHaveAttribute("href", "blob:ux-audit-result");
      expect(revokeUrl).not.toHaveBeenCalled();
    } finally {
      cleanup();
      Object.defineProperty(window, "scrollY", { configurable: true, value: 0 });
      Reflect.deleteProperty(URL, "createObjectURL");
      Reflect.deleteProperty(URL, "revokeObjectURL");
    }
  });

  it("renders one batch as one ordered multi-transcription with item controls", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const batchId = "multi_0123456789abcdef0123456789abcdef";
    const batchJob = (id: string, title: string, position: number) => ({
      id,
      project_id: "p1",
      status: "queued",
      title,
      provider: "elevenlabs",
      language_mode: "ru",
      diarization_enabled: false,
      media_clip: null,
      batch: { id: batchId, position },
      terminal_dismissed_at: null,
      source_count: 1,
      created_at: "2026-08-22T10:00:00Z",
      updated_at: "2026-08-22T10:00:00Z",
      cancelled_at: null,
      cancel_requested_at: null,
      attempt_count: 0,
      started_at: null,
      finished_at: null,
      error_code: null,
      error_message: null,
      output_folder: null,
    });
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/projects/p1/jobs") && !init?.method) {
        return json({
          jobs: [
            batchJob("job-batch-second", "Вторая запись", 1),
            batchJob("job-batch-first", "Первая запись", 0),
          ],
        });
      }
      return defaultFetch?.(url, init) ?? json({});
    });

    renderApp();
    await openProjectsPage();
    const multi = await screen.findByRole("article", {
      name: "Группа транскрибаций · 2",
    });
    expect(within(multi).getByText("Транскрибация 1 из 2")).toBeInTheDocument();
    expect(within(multi).getByText("Транскрибация 2 из 2")).toBeInTheDocument();
    expect(within(multi).getAllByText("Первая запись")).toHaveLength(1);
    expect(within(multi).getAllByText("Вторая запись")).toHaveLength(1);
    expect(
      within(multi)
        .getAllByText(/^(Первая запись|Вторая запись)$/)
        .map((element) => element.textContent),
    ).toEqual(["Первая запись", "Вторая запись"]);
    expect(within(multi).getByText("Завершено: 0 из 2"))
      .toBeInTheDocument();
    expect(within(multi).getAllByRole("button", { name: "Открыть" }))
      .toHaveLength(2);
    expect(within(multi).getAllByText("Статус: В очереди")).toHaveLength(2);
  });

  it("keeps multiple legacy workspaces accessible without lifecycle controls", async () => {
    installFocusedOutputFixture({ includeSecondProject: true });
    renderApp();
    await openProjectsPage();

    const switcher = await screen.findByText(
      "Прежние рабочие области · 2",
    );
    const details = switcher.closest("details");
    if (!details) throw new Error("legacy workspace switcher is missing");
    expect(
      within(details).getByRole("button", { name: /Research calls/ }),
    ).toBeInTheDocument();
    expect(
      within(details).getAllByRole("button"),
    ).toHaveLength(2);
    expect(
      screen.queryByRole("button", { name: "Редактировать" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Архивировать" }),
    ).not.toBeInTheDocument();
  });

  it("Google Picker loader deduplicates success and retries after load failure", async () => {
    googlePicker.resetGooglePickerLoaderForTests();
    window.gapi = { load: vi.fn((_name: string, cb: () => void) => cb()) };
    const first = googlePicker.loadGooglePicker();
    const second = googlePicker.loadGooglePicker();
    expect(first).toBe(second);
    const script = document.head.querySelector<HTMLScriptElement>(
      'script[data-studio-google-picker="true"]',
    );
    expect(script).not.toBeNull();
    script?.onload?.(new Event("load"));
    await expect(first).resolves.toBeUndefined();
    expect(
      document.head.querySelectorAll(
        'script[data-studio-google-picker="true"]',
      ),
    ).toHaveLength(1);

    googlePicker.resetGooglePickerLoaderForTests();
    delete window.gapi;
    document.head
      .querySelectorAll('script[data-studio-google-picker="true"]')
      .forEach((node) => node.remove());
    const failed = googlePicker.loadGooglePicker();
    const failedScript = document.head.querySelector<HTMLScriptElement>(
      'script[data-studio-google-picker="true"]',
    );
    failedScript?.onerror?.(new Event("error"));
    await expect(failed).rejects.toThrow("Google Picker не загрузился");
    expect(
      document.head.querySelector('script[data-studio-google-picker="true"]'),
    ).toBeNull();

    window.gapi = { load: vi.fn((_name: string, cb: () => void) => cb()) };
    const retried = googlePicker.loadGooglePicker();
    document.head
      .querySelector<HTMLScriptElement>(
        'script[data-studio-google-picker="true"]',
      )
      ?.onload?.(new Event("load"));
    await expect(retried).resolves.toBeUndefined();
  });

  it("native catalog Google Picker callback normalizes picked/cancel/error and is idempotent without token persistence", async () => {
    googlePicker.resetGooglePickerLoaderForTests();
    window.gapi = { load: vi.fn((_name: string, cb: () => void) => cb()) };
    let callback: ((data: unknown) => void) | null = null;
    class FakeView {
      setIncludeFolders() {
        return this;
      }
      setSelectFolderEnabled() {
        return this;
      }
      setMode() {
        return this;
      }
      setParent() {
        return this;
      }
    }
    class FakeBuilder {
      addView() {
        return this;
      }
      enableFeature() {
        return this;
      }
      setOAuthToken() {
        return this;
      }
      setDeveloperKey() {
        return this;
      }
      setAppId() {
        return this;
      }
      setLocale() {
        return this;
      }
      setSize() {
        return this;
      }
      setTitle() {
        return this;
      }
      setOrigin() {
        return this;
      }
      setMaxItems() {
        return this;
      }
      setCallback(cb: (data: unknown) => void) {
        callback = cb;
        return this;
      }
      build() {
        return { setVisible: vi.fn() };
      }
    }
    window.google = {
      picker: {
        Action: { PICKED: "picked", CANCEL: "cancel", ERROR: "error" },
        DocsView: FakeView,
        PickerBuilder: FakeBuilder,
        ViewId: { DOCS: "docs", FOLDERS: "folders" },
        DocsViewMode: { LIST: "list" },
        Feature: { MULTISELECT_ENABLED: "multi" },
      },
    };
    const pickerSession = {
      access_token: "ya29.secret",
      api_key: "public",
      app_id: "app",
      scope_ready: true,
    };
    const pickedPromise = googlePicker.openGooglePicker(
      "catalog-folder",
      pickerSession,
    );
    expect(pickerSession.access_token).toBe("");
    document.head
      .querySelector<HTMLScriptElement>(
        'script[data-studio-google-picker="true"]',
      )
      ?.onload?.(new Event("load"));
    await waitFor(() => expect(callback).not.toBeNull());
    expect(document.documentElement.style.overflow).toBe("hidden");
    expect(document.body.style.overflow).toBe("hidden");
    callback?.({
      action: "picked",
      docs: [
        {
          id: "document-1",
          name: "Name",
          mimeType: "application/vnd.google-apps.folder",
        },
      ],
    });
    callback?.({ action: "error", raw: "raw-google-payload" });
    await expect(pickedPromise).resolves.toEqual({
      action: "picked",
      docs: [
        {
          id: "document-1",
          name: "Name",
          mimeType: "application/vnd.google-apps.folder",
        },
      ],
    });
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.overflow).toBe("");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.body.textContent).not.toContain("ya29.secret");

    callback = null;
    const cancelPromise = googlePicker.openGooglePicker("catalog-folder", {
      access_token: "ya29.cancel",
      api_key: "public",
      app_id: "app",
      scope_ready: true,
    });
    await waitFor(() => expect(callback).not.toBeNull());
    expect(document.body.style.overflow).toBe("hidden");
    callback?.({ action: "cancel" });
    await expect(cancelPromise).resolves.toEqual({ action: "cancel" });
    expect(document.body.style.overflow).toBe("");

    callback = null;
    const errorPromise = googlePicker.openGooglePicker("catalog-folder", {
      access_token: "ya29.error",
      api_key: "public",
      app_id: "app",
      scope_ready: true,
    });
    await waitFor(() => expect(callback).not.toBeNull());
    expect(document.body.style.overflow).toBe("hidden");
    callback?.({ action: "error", raw: "raw-google-payload" });
    await expect(errorPromise).resolves.toEqual({
      action: "error",
      message: "Google Picker вернул ошибку. Повторите попытку.",
    });
    expect(document.body.style.overflow).toBe("");
    expect(document.body.textContent).not.toContain("raw-google-payload");
  });

  it("computes deterministic Google Picker sizes within viewport and minimum constraints", () => {
    expect(computeGooglePickerSize(1920, 1080)).toEqual({
      width: 1051,
      height: 650,
    });
    expect(computeGooglePickerSize(1366, 768)).toEqual({
      width: 1051,
      height: 650,
    });
    expect(computeGooglePickerSize(800, 600)).toEqual({
      width: 752,
      height: 552,
    });
    expect(computeGooglePickerSize(480, 320)).toEqual({
      width: 566,
      height: 350,
    });
    const computed = computeGooglePickerSize(1024.8, 700.2);
    expect(Number.isInteger(computed.width)).toBe(true);
    expect(Number.isInteger(computed.height)).toBe(true);
  });

  it("keeps only the catalog compatibility mode on the native Google Picker", async () => {
    googlePicker.resetGooglePickerLoaderForTests();
    const originalInnerWidth = window.innerWidth;
    const originalInnerHeight = window.innerHeight;
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1366,
    });
    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      value: 768,
    });
    let callback: ((data: unknown) => void) | null = null;
    const viewIds: string[] = [];
    const viewModes: string[] = [];
    const viewParents: string[] = [];
    const includeFolders: boolean[] = [];
    const viewMimeTypes: string[] = [];
    const selectFolderEnabled: boolean[] = [];
    const builderCalls: { method: string; args: unknown[] }[] = [];
    class FakeView {
      constructor(viewId: string) {
        viewIds.push(viewId);
      }
      setIncludeFolders(value: boolean) {
        includeFolders.push(value);
        return this;
      }
      setMimeTypes(mimeTypes: string) {
        viewMimeTypes.push(mimeTypes);
        return this;
      }
      setSelectFolderEnabled(value: boolean) {
        selectFolderEnabled.push(value);
        return this;
      }
      setMode(mode: string) {
        viewModes.push(mode);
        return this;
      }
      setParent(parentId: string) {
        viewParents.push(parentId);
        return this;
      }
    }
    class FakeBuilder {
      addView() {
        return this;
      }
      enableFeature(feature: string) {
        builderCalls.push({ method: "enableFeature", args: [feature] });
        return this;
      }
      setOAuthToken(token: string) {
        builderCalls.push({ method: "setOAuthToken", args: [token] });
        return this;
      }
      setDeveloperKey(key: string) {
        builderCalls.push({ method: "setDeveloperKey", args: [key] });
        return this;
      }
      setAppId(appId: string) {
        builderCalls.push({ method: "setAppId", args: [appId] });
        return this;
      }
      setLocale(locale: string) {
        builderCalls.push({ method: "setLocale", args: [locale] });
        return this;
      }
      setSize(width: number, height: number) {
        builderCalls.push({ method: "setSize", args: [width, height] });
        return this;
      }
      setTitle(title: string) {
        builderCalls.push({ method: "setTitle", args: [title] });
        return this;
      }
      setOrigin(origin: string) {
        builderCalls.push({ method: "setOrigin", args: [origin] });
        return this;
      }
      setMaxItems(maxItems: number) {
        builderCalls.push({ method: "setMaxItems", args: [maxItems] });
        return this;
      }
      setSelectableMimeTypes(mimeTypes: string) {
        builderCalls.push({
          method: "setSelectableMimeTypes",
          args: [mimeTypes],
        });
        return this;
      }
      setCallback(cb: (data: unknown) => void) {
        builderCalls.push({ method: "setCallback", args: [cb] });
        callback = cb;
        return this;
      }
      build() {
        return { setVisible: vi.fn() };
      }
    }
    window.gapi = { load: vi.fn((_name: string, cb: () => void) => cb()) };
    window.google = {
      picker: {
        Action: { PICKED: "picked", CANCEL: "cancel", ERROR: "error" },
        DocsView: FakeView,
        PickerBuilder: FakeBuilder,
        ViewId: { DOCS: "docs", FOLDERS: "folders" },
        DocsViewMode: { LIST: "list" },
        Feature: { MULTISELECT_ENABLED: "multi" },
      },
    };

    const catalogFolderPromise = googlePicker.openGooglePicker(
      "catalog-folder",
      {
        access_token: "ya29.catalog",
        api_key: "public",
        app_id: "app",
        scope_ready: true,
      },
    );
    document.head
      .querySelector<HTMLScriptElement>(
        'script[data-studio-google-picker="true"]',
      )
      ?.onload?.(new Event("load"));
    await waitFor(() => expect(callback).not.toBeNull());
    callback?.({ action: "cancel" });
    await expect(catalogFolderPromise).resolves.toEqual({ action: "cancel" });

    expect(viewIds).toEqual(["folders"]);
    expect(viewModes).toEqual(["list"]);
    expect(viewParents).toEqual(["root"]);
    expect(includeFolders).toEqual([true]);
    expect(viewMimeTypes).toEqual([]);
    expect(selectFolderEnabled).toEqual([true]);
    expect(builderCalls).toContainEqual({ method: "setLocale", args: ["ru"] });
    expect(builderCalls).toContainEqual({
      method: "setTitle",
      args: ["Выберите папку каталога транскриптов"],
    });
    expect(builderCalls).toContainEqual({
      method: "setSize",
      args: [1051, 650],
    });
    expect(builderCalls).toContainEqual({
      method: "setOrigin",
      args: [window.location.origin],
    });
    expect(builderCalls).toContainEqual({
      method: "setOAuthToken",
      args: ["ya29.catalog"],
    });
    expect(builderCalls).toContainEqual({
      method: "setDeveloperKey",
      args: ["public"],
    });
    expect(builderCalls).toContainEqual({ method: "setAppId", args: ["app"] });
    expect(builderCalls).toContainEqual({ method: "setMaxItems", args: [1] });
    expect(
      builderCalls.filter((call) => call.method === "enableFeature"),
    ).toEqual([]);
    expect(
      builderCalls.filter((call) => call.method === "setCallback"),
    ).toHaveLength(1);
    expect(
      builderCalls.some((call) => call.args.includes("support_drives")),
    ).toBe(false);
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: originalInnerWidth,
    });
    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      value: originalInnerHeight,
    });
  });

  it("refreshes in-memory CSRF and renders settings without browser storage secrets", async () => {
    renderApp();
    await waitForPlatformOverview();
    expect(fetch).toHaveBeenCalledWith(
      "/api/auth/csrf",
      expect.objectContaining({ method: "POST" }),
    );
    await openSettingsSection("Подключения");
    await screen.findByText(/Ключи провайдеров/);
    expect(
      screen.getByRole("heading", {
        name: "Работа с готовыми Google Docs",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", {
        name: "Привести документы к текущему формату",
      }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/Транскрибации → Обслуживание/)).toBeInTheDocument();
    expect(screen.getByText(/••••1234/)).toBeInTheDocument();
    expect(window.localStorage.length).toBe(0);
    expectOnlySafeFormDrafts();
  });

  it("opens transcript maintenance as a dedicated Transcriptions workspace", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = fetchMock.getMockImplementation();
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes("/api/transcript-maintenance/runs?workflow=")) {
        return json({ run: null });
      }
      return defaultFetch!(url, init);
    });
    renderApp();
    await openProjectsPage();

    await userEvent.click(
      screen.getByRole("tab", { name: "Обслуживание" }),
    );

    expect(
      await screen.findByRole("heading", {
        name: "Проверка и обновление Google Docs",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Привести документы к текущему формату" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Учесть готовые документы в Studio" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: "Обслуживание" }),
    ).toHaveAttribute("aria-selected", "true");
  });

  it("persists the local-source retention choice through account settings", async () => {
    renderApp();
    await openSettingsSection("Файлы и хранилище");

    const retention = await screen.findByRole("combobox", {
      name: "Срок хранения локальных файлов",
    });
    expect(
      screen.getByText(/временной приватной копии в Studio/),
    ).toHaveTextContent(
      "Ссылки на Google Drive и результаты Google Docs не затрагиваются.",
    );
    expect(retention).toHaveValue("259200");
    expect(
      within(retention).queryByRole("option", { name: "1 час" }),
    ).not.toBeInTheDocument();
    expect(within(retention).getAllByRole("option")).toHaveLength(3);
    expect(
      within(retention).getByRole("option", { name: "30 дней" }),
    ).toBeInTheDocument();

    await userEvent.selectOptions(retention, "604800");
    await userEvent.click(
      screen.getByRole("button", { name: "Сохранить срок" }),
    );

    await screen.findByText("Срок хранения сохранён.");
    expect(fetch).toHaveBeenCalledWith(
      "/api/account/preferences",
      expect.objectContaining({
        method: "PATCH",
        headers: expect.objectContaining({
          "x-csrf-token": "csrf-after-refresh",
        }),
        body: JSON.stringify({ source_retention_ttl_seconds: 604800 }),
      }),
    );
    expect(retention).toHaveValue("604800");
    expect(window.localStorage.length).toBe(0);
    expectOnlySafeFormDrafts();
  });

  it("bounds a stalled retention read and fails closed with retry", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const retentionSignals: AbortSignal[] = [];
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/account/preferences" && !init?.method) {
        const signal = init.signal;
        if (!signal) throw new Error("retention-read signal is missing");
        retentionSignals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 15_000 ? 1 : (delay as number),
          ...args,
        )) as typeof setTimeout);

    try {
      renderApp();
      await openSettingsSection("Файлы и хранилище");
      const retentionError = await screen.findByText(
        "Не удалось загрузить настройку хранения. Повторите попытку.",
      );
      expect(retentionError).toBeInTheDocument();
      expect(retentionSignals).toHaveLength(1);
      expect(retentionSignals[0]?.aborted).toBe(true);
      const retentionPanel = retentionError.closest(".retention-preferences");
      expect(retentionPanel).not.toBeNull();
      expect(
        within(retentionPanel as HTMLElement).getByRole("button", {
          name: "Повторить",
        }),
      ).toBeEnabled();
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("rejects a malformed retention response before rendering choices", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) =>
      url === "/api/account/preferences" && !init?.method
        ? json({
            source_retention_ttl_seconds: 259200,
            allowed_source_retention_ttl_seconds: [86400],
          })
        : (defaultFetch?.(url, init) ?? json({ ok: true })),
    );

    renderApp();
    await openSettingsSection("Файлы и хранилище");
    expect(
      await screen.findByText(
        "Не удалось загрузить настройку хранения. Повторите попытку.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", {
        name: "Срок хранения локальных файлов",
      }),
    ).not.toBeInTheDocument();
  });

  it("bounds and deduplicates retention save with authoritative confirmation", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const mutationSignals: AbortSignal[] = [];
    let serverTtl = 259200;
    let preferenceReads = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/account/preferences" && !init?.method) {
        preferenceReads += 1;
        return json({
          source_retention_ttl_seconds: serverTtl,
          allowed_source_retention_ttl_seconds: [
            259200, 604800, 2592000,
          ],
          accent_color: "blue",
          allowed_accent_colors: ["blue", "violet", "teal", "rose"],
        });
      }
      if (url === "/api/account/preferences" && init?.method === "PATCH") {
        serverTtl = JSON.parse(String(init.body)).source_retention_ttl_seconds;
        const signal = init.signal;
        if (!signal) throw new Error("retention-save signal is missing");
        mutationSignals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openSettingsSection("Файлы и хранилище");
    const retention = await screen.findByRole("combobox", {
      name: "Срок хранения локальных файлов",
    });
    await userEvent.selectOptions(retention, "604800");
    const form = retention.closest("form");
    if (!form) throw new Error("retention form is missing");
    const readsBeforeMutation = preferenceReads;

    vi.useFakeTimers();
    try {
      fireEvent.submit(form);
      fireEvent.submit(form);
      await act(async () => {
        await Promise.resolve();
      });
      expect(mutationSignals).toHaveLength(1);
      expect(screen.getByRole("button", { name: "Сохраняем…" })).toBeDisabled();
      expect(form).toHaveAttribute("aria-busy", "true");

      await act(async () => {
        await vi.advanceTimersByTimeAsync(20_000);
      });
      vi.useRealTimers();
      expect(
        await screen.findByText(
          "Сохранение срока подтверждено по актуальной настройке аккаунта.",
        ),
      ).toBeInTheDocument();
      expect(mutationSignals[0]?.aborted).toBe(true);
      expect(preferenceReads).toBe(readsBeforeMutation + 1);
      expect(retention).toHaveValue("604800");
      expect(screen.getByRole("button", { name: "Сохранить срок" })).toBeEnabled();
      expect(
        baseFetch.mock.calls.filter(
          ([url, init]) =>
            url === "/api/account/preferences" && init?.method === "PATCH",
        ),
      ).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps retention mutation ownership and result across Settings remount", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let serverTtl = 259200;
    let preferenceReads = 0;
    let resolvePatch: ((response: Response) => void) | undefined;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/account/preferences" && !init?.method) {
        preferenceReads += 1;
        return json({
          source_retention_ttl_seconds: serverTtl,
          allowed_source_retention_ttl_seconds: [
            259200, 604800, 2592000,
          ],
          accent_color: "blue",
          allowed_accent_colors: ["blue", "violet", "teal", "rose"],
        });
      }
      if (url === "/api/account/preferences" && init?.method === "PATCH") {
        return new Promise<Response>((resolve) => {
          resolvePatch = resolve;
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openSettingsSection("Файлы и хранилище");
    const retention = await screen.findByRole("combobox", {
      name: "Срок хранения локальных файлов",
    });
    await userEvent.selectOptions(retention, "604800");
    const form = retention.closest("form");
    if (!form) throw new Error("retention form is missing");
    fireEvent.submit(form);
    fireEvent.submit(form);
    await waitFor(() => expect(resolvePatch).toBeDefined());
    expect(screen.getByRole("button", { name: "Сохраняем…" })).toBeDisabled();

    await openProjectsPage();
    await openSettingsSection("Файлы и хранилище");
    expect(
      await screen.findByRole("button", { name: "Сохраняем…" }),
    ).toBeDisabled();
    serverTtl = 604800;
    const failedResponse = await json(
      { detail: "raw-retention-failure-must-not-render" },
      false,
      503,
    );
    await act(async () => resolvePatch?.(failedResponse));
    expect(
      await screen.findByText(
        "Сохранение срока подтверждено по актуальной настройке аккаунта.",
      ),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", {
          name: "Срок хранения локальных файлов",
        }),
      ).toHaveValue("604800"),
    );
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          url === "/api/account/preferences" && init?.method === "PATCH",
      ),
    ).toHaveLength(1);
    expect(document.body.textContent).not.toContain(
      "raw-retention-failure-must-not-render",
    );

    const readsBeforeFinalReopen = preferenceReads;
    await openProjectsPage();
    await openSettingsSection("Файлы и хранилище");
    await screen.findByRole("combobox", {
      name: "Срок хранения локальных файлов",
    });
    expect(preferenceReads).toBe(readsBeforeFinalReopen + 1);
  });

  it("restores a different authoritative retention value after ambiguity", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let preferenceReads = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/account/preferences" && !init?.method) {
        preferenceReads += 1;
        return json({
          source_retention_ttl_seconds:
            preferenceReads === 1 ? 2592000 : 259200,
          allowed_source_retention_ttl_seconds: [
            259200, 604800, 2592000,
          ],
          accent_color: "blue",
          allowed_accent_colors: ["blue", "violet", "teal", "rose"],
        });
      }
      if (url === "/api/account/preferences" && init?.method === "PATCH")
        return json({ detail: "raw-ambiguous-retention" }, false, 503);
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openSettingsSection("Файлы и хранилище");
    const retention = await screen.findByRole("combobox", {
      name: "Срок хранения локальных файлов",
    });
    await userEvent.selectOptions(retention, "604800");
    await userEvent.click(screen.getByRole("button", { name: "Сохранить срок" }));
    expect(
      await screen.findByText(
        "Studio не подтвердила сохранение. Показано актуальное значение; проверьте его перед повторной попыткой.",
      ),
    ).toBeInTheDocument();
    expect(retention).toHaveValue("259200");
    expect(document.body.textContent).not.toContain("raw-ambiguous-retention");
  });
  it("restores the last confirmed retention value when reconciliation fails", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let preferenceReads = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/account/preferences" && !init?.method) {
        preferenceReads += 1;
        return preferenceReads === 1
          ? json({
              source_retention_ttl_seconds: 259200,
              allowed_source_retention_ttl_seconds: [
                259200, 604800, 2592000,
              ],
              accent_color: "blue",
              allowed_accent_colors: ["blue", "violet", "teal", "rose"],
            })
          : json({ detail: "raw-retention-read-failure" }, false, 500);
      }
      if (url === "/api/account/preferences" && init?.method === "PATCH")
        return json({ detail: "raw-retention-write-failure" }, false, 503);
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openSettingsSection("Файлы и хранилище");
    const retention = await screen.findByRole("combobox", {
      name: "Срок хранения локальных файлов",
    });
    await userEvent.selectOptions(retention, "604800");
    await userEvent.click(screen.getByRole("button", { name: "Сохранить срок" }));
    expect(
      await screen.findByText(
        "Studio не подтвердила сохранение, а обновить настройку не удалось. Сохранено последнее подтверждённое значение; обновите страницу перед повторной попыткой.",
      ),
    ).toBeInTheDocument();
    expect(retention).toHaveValue("259200");
    expect(document.body.textContent).not.toContain("raw-retention-read-failure");
    expect(document.body.textContent).not.toContain("raw-retention-write-failure");
  });
  it("renders disconnected Google Drive state", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/google/connection"))
        return json(googleConnectionFixture());
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    await openSettingsSection("Подключения");
    expect(
      await screen.findByText("Google Drive не подключён"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Подключите Google Drive, чтобы выбирать файлы и папку результатов.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Подключить Google Drive" }),
    ).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      "/api/google/connection",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("renders connected Google Drive safe metadata without raw tokens", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string) => {
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
          });
        if (url.endsWith("/api/auth/csrf"))
          return json({ csrf_token: "csrf-after-refresh" });
        if (url.endsWith("/api/credentials"))
          return json({
            credentials: [
              {
                id: "cred-active",
                provider: "elevenlabs",
                label: "Primary STT",
                status: "active",
                masked_value: "••••1234",
                active_version: 2,
              },
            ],
          });
        if (url.endsWith("/api/audit-events")) return json({ events: [] });
        if (url.endsWith("/api/google/connection"))
          return json(
            googleConnectionFixture({
              connected: true,
              status: "active",
              google_email: "safe.user@example.com",
              scopes: "https://www.googleapis.com/auth/drive.file",
              connected_at: "2026-07-01T00:00:00",
              picker_configured: true,
              picker_scope_ready: true,
              picker_ready: true,
              refresh_token: "raw-refresh-token-never-render",
            }),
          );
        return json({ ok: true });
      },
    );
    renderApp();
    await openSettingsSection("Подключения");
    expect(
      await screen.findByText("Google Drive подключён"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Подключите Google Drive, чтобы выбирать файлы и папку результатов.",
      ),
    ).not.toBeInTheDocument();
    expect(screen.getByText("safe.user@example.com")).toBeInTheDocument();
    expect(screen.getByText("active")).toBeInTheDocument();
    expect(
      screen.getByText("https://www.googleapis.com/auth/drive.file"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("raw-refresh-token-never-render"),
    ).not.toBeInTheDocument();
    expect(window.localStorage.length).toBe(0);
    expectOnlySafeFormDrafts();
  });

  it("starts Google OAuth with CSRF and navigates without storing OAuth data", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/google/connection"))
        return json(googleConnectionFixture());
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const assign = vi.fn();
    Object.defineProperty(window, "location", {
      value: { ...window.location, assign },
      writable: true,
    });
    renderApp();
    await openSettingsSection("Подключения");
    await userEvent.click(
      await screen.findByRole("button", { name: "Подключить Google Drive" }),
    );
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/google/oauth/start",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    const startCall = (
      fetch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.find(([url]) => url === "/api/google/oauth/start");
    expect(startCall?.[1]?.headers).toMatchObject({
      "x-csrf-token": "csrf-after-refresh",
    });
    expect(assign).toHaveBeenCalledWith(
      String(googleOauthStartFixture().authorization_url),
    );
    expect(document.body).not.toHaveTextContent("secret-state");
    expect(window.localStorage.length).toBe(0);
    expectOnlySafeFormDrafts();
  });

  it("disconnects Google Drive with CSRF", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string, init?: RequestInit) => {
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
          });
        if (url.endsWith("/api/auth/csrf"))
          return json({ csrf_token: "csrf-after-refresh" });
        if (url.endsWith("/api/credentials"))
          return json({
            credentials: [
              {
                id: "cred-active",
                provider: "elevenlabs",
                label: "Primary STT",
                status: "active",
                masked_value: "••••1234",
                active_version: 2,
              },
            ],
          });
        if (url.endsWith("/api/audit-events")) return json({ events: [] });
        if (url.endsWith("/api/diagnostics/system"))
          return json({
            environment: "production",
            build: { web: "web-safe", api: "api-safe", worker: "worker-safe" },
            google_drive: { connected: true, scope_ready: true },
            provider_credentials: { active_count: 1, ready: true },
            diagnostics: {
              recording_enabled: true,
              debug_recording: "inactive",
              retention_days: 14,
              debug_retention_hours: 24,
            },
            report_limits: { max_days: 7, max_timeline_events: 5000 },
          });
        if (url.includes("/api/diagnostics/events"))
          return json({
            events: [],
            next_cursor: null,
            period: {
              start: "2026-07-15T00:00:00",
              end: "2026-07-16T00:00:00",
            },
          });
        if (
          url.endsWith("/api/diagnostics/report.md") &&
          init?.method === "POST"
        )
          return markdownReport("# Safe report\n");
        if (url.endsWith("/api/google/connection") && init?.method === "DELETE")
          return json(
            googleConnectionFixture({
              status: "revoked",
              google_email: "safe.user@example.com",
              scopes: "https://www.googleapis.com/auth/drive.file",
              connected_at: "2026-07-01T00:00:00",
              revoked_at: "2026-07-02T00:00:00",
            }),
          );
        if (url.endsWith("/api/google/connection"))
          return json(
            googleConnectionFixture({
              connected: true,
              status: "active",
              google_email: "safe.user@example.com",
              scopes: "https://www.googleapis.com/auth/drive.file",
              connected_at: "2026-07-01T00:00:00",
              picker_configured: true,
              picker_scope_ready: true,
              picker_ready: true,
            }),
          );
        return json({ ok: true });
      },
    );
    renderApp();
    await openSettingsSection("Подключения");
    await userEvent.click(
      await screen.findByRole("button", { name: "Отключить Google Drive" }),
    );
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/google/connection",
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
    const deleteCall = (
      fetch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.find(
      ([url, init]) =>
        url === "/api/google/connection" && init?.method === "DELETE",
    );
    expect(deleteCall?.[1]?.headers).toMatchObject({
      "x-csrf-token": "csrf-after-refresh",
    });
    expect(await screen.findByText(/Статус: revoked/)).toBeInTheDocument();
  });

  it.each(["connect", "disconnect"])("guides Google %s through recent authentication and requires an explicit retry", async (operation) => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = fetchMock.getMockImplementation();
    let reauthenticated = false;
    let connected = true;
    let mutationCount = 0;
    const endpoint = operation === "connect" ? "/api/google/oauth/start" : "/api/google/connection";
    const method = operation === "connect" ? "POST" : "DELETE";
    const connection = () => googleConnectionFixture({ connected, status: connected ? "active" : "revoked", picker_configured: true, picker_scope_ready: connected, picker_ready: connected, reconnect_required: false });
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/google/connection" && !init?.method) return json(connection());
      if (url === "/api/auth/security") return json({ totp_enabled: false, totp_enrollment_pending: false, recent_auth_expires_at: reauthenticated ? "2099-01-01T00:00:00Z" : null, password_reset_delivery: "disabled" });
      if (url === "/api/auth/reauth" && init?.method === "POST") { reauthenticated = true; return json({ ok: true }); }
      if (url === endpoint && init?.method === method) {
        mutationCount += 1;
        if (!reauthenticated) return json({ detail: { reason: "recent_reauthentication_required" } }, false, 409);
        if (operation === "connect") return json(googleOauthStartFixture({}));
        connected = false;
        return json(connection());
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const assign = vi.fn();
    Object.defineProperty(window, "location", { value: { ...originalLocation, assign }, configurable: true });
    renderApp();
    await openSettingsSection("Подключения");
    const action = operation === "connect" ? "Переподключить Google Drive" : "Отключить Google Drive";
    await userEvent.click(await screen.findByRole("button", { name: action, exact: true }));
    expect(await screen.findByText("Сначала подтвердите личность в разделе «Аккаунт», затем вернитесь в «Подключения» и повторите действие с Google Drive.")).toHaveAttribute("role", "alert");
    expect(mutationCount).toBe(1);
    expect(assign).not.toHaveBeenCalled();
    expect(screen.queryByText("recent_reauthentication_required")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Подтвердить личность для Google Drive" }));
    const security = screen.getByRole("region", { name: "Защита аккаунта" });
    await userEvent.type(within(security).getByLabelText("Пароль"), "synthetic-test-password");
    await userEvent.click(within(security).getByRole("button", { name: "Подтвердить личность", exact: true }));
    await waitFor(() => expect(reauthenticated).toBe(true));
    await openSettingsSection("Подключения");
    expect(mutationCount).toBe(1);
    await userEvent.click(await screen.findByRole("button", { name: action, exact: true }));
    await waitFor(() => expect(mutationCount).toBe(2));
    if (operation === "connect") expect(assign).toHaveBeenCalledTimes(1);
    else expect(await screen.findByText("Google Drive отключён.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Подтвердить личность для Google Drive" })).not.toBeInTheDocument();
  });

  it("bounds stalled Google connection reads and exposes an explicit retry", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const connectionSignals: AbortSignal[] = [];
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/google/connection" && !init?.method) {
        const signal = init.signal;
        if (!signal) throw new Error("Google connection signal is missing");
        connectionSignals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 15_000 ? 1 : (delay as number),
          ...args,
        )) as typeof setTimeout);

    try {
      renderApp();
      await openSettingsSection("Подключения");
      expect(
        await screen.findByText(
          "Не удалось загрузить статус Google Drive. Повторите попытку.",
        ),
      ).toBeInTheDocument();
      expect(connectionSignals).toHaveLength(2);
      expect(connectionSignals.every((signal) => signal.aborted)).toBe(true);
      const retry = screen.getByRole("button", {
        name: "Повторить проверку Google Drive",
      });
      await userEvent.click(retry);
      await waitFor(() => expect(connectionSignals).toHaveLength(3));
      await waitFor(() => expect(connectionSignals[2]?.aborted).toBe(true));
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("rejects malformed Google connection state without rendering raw fields", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) =>
      url === "/api/google/connection" && !init?.method
        ? json(
            googleConnectionFixture({
              connected: true,
              status: null,
              raw_refresh_token: "raw-google-connection-secret",
            }),
          )
        : (defaultFetch?.(url, init) ?? json({ ok: true })),
    );

    renderApp();
    await openSettingsSection("Подключения");
    expect(
      await screen.findByText(
        "Не удалось загрузить статус Google Drive. Повторите попытку.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Подключить Google Drive" }),
    ).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain(
      "raw-google-connection-secret",
    );
  });

  it("bounds and deduplicates OAuth start without replay after ambiguity", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const mutationSignals: AbortSignal[] = [];
    let connectionReads = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/google/connection" && !init?.method) {
        connectionReads += 1;
        return json(googleConnectionFixture());
      }
      if (url === "/api/google/oauth/start" && init?.method === "POST") {
        const signal = init.signal;
        if (!signal) throw new Error("Google OAuth start signal is missing");
        mutationSignals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const assign = vi.fn();
    Object.defineProperty(window, "location", {
      value: { ...window.location, assign },
      writable: true,
    });

    renderApp();
    await openSettingsSection("Подключения");
    const connect = await screen.findByRole("button", {
      name: "Подключить Google Drive",
    });
    const readsBeforeMutation = connectionReads;
    vi.useFakeTimers();
    try {
      fireEvent.click(connect);
      fireEvent.click(connect);
      await act(async () => Promise.resolve());
      expect(mutationSignals).toHaveLength(1);
      expect(connect).toBeDisabled();
      expect(connect).toHaveAttribute("aria-busy", "true");
      await act(async () => {
        await vi.advanceTimersByTimeAsync(20_000);
      });
      vi.useRealTimers();
      expect(
        await screen.findByText(
          "Studio не подтвердила начало подключения. Статус Google Drive обновлён; не повторяйте запрос, пока не проверите состояние подключения.",
        ),
      ).toBeInTheDocument();
      expect(mutationSignals[0]?.aborted).toBe(true);
      expect(connectionReads).toBe(readsBeforeMutation + 1);
      expect(assign).not.toHaveBeenCalled();
      expect(
        baseFetch.mock.calls.filter(
          ([url, init]) =>
            url === "/api/google/oauth/start" && init?.method === "POST",
        ),
      ).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("rejects an untrusted OAuth URL and performs one safe reconciliation", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let connectionReads = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/google/connection" && !init?.method) {
        connectionReads += 1;
        return json(googleConnectionFixture());
      }
      if (url === "/api/google/oauth/start" && init?.method === "POST")
        return json(
          googleOauthStartFixture({
            authorization_url:
              "https://evil.example/oauth?state=raw-google-oauth-secret",
          }),
        );
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const assign = vi.fn();
    Object.defineProperty(window, "location", {
      value: { ...window.location, assign },
      writable: true,
    });

    renderApp();
    await openSettingsSection("Подключения");
    const readsBeforeMutation = connectionReads;
    await userEvent.click(
      await screen.findByRole("button", { name: "Подключить Google Drive" }),
    );
    expect(
      await screen.findByText(
        "Studio не подтвердила начало подключения. Статус Google Drive обновлён; не повторяйте запрос, пока не проверите состояние подключения.",
      ),
    ).toBeInTheDocument();
    expect(connectionReads).toBe(readsBeforeMutation + 1);
    expect(assign).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toContain("raw-google-oauth-secret");
  });

  it("keeps disconnect ownership and outcome across a Settings remount", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let connectionReads = 0;
    let serverDisconnected = false;
    let resolveDelete: ((response: Response) => void) | undefined;
    const activeConnection = () =>
      googleConnectionFixture({
        connected: true,
        status: "active",
        google_email: "safe.user@example.com",
        scopes: "openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly",
        connected_at: "2026-07-01T00:00:00Z",
        picker_configured: true,
        picker_scope_ready: true,
        picker_ready: true,
      });
    const revokedConnection = () =>
      googleConnectionFixture({
        status: "revoked",
        google_email: "safe.user@example.com",
        scopes: "openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly",
        connected_at: "2026-07-01T00:00:00Z",
        revoked_at: "2026-08-13T12:00:00Z",
      });
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/google/connection" && !init?.method) {
        connectionReads += 1;
        return json(serverDisconnected ? revokedConnection() : activeConnection());
      }
      if (url === "/api/google/connection" && init?.method === "DELETE")
        return new Promise<Response>((resolve) => {
          resolveDelete = resolve;
        });
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openSettingsSection("Подключения");
    const disconnect = await screen.findByRole("button", {
      name: "Отключить Google Drive",
    });
    fireEvent.click(disconnect);
    fireEvent.click(disconnect);
    await waitFor(() => expect(resolveDelete).toBeDefined());
    await openProjectsPage();
    await openSettingsSection("Подключения");
    expect(
      await screen.findByRole("button", { name: "Отключить Google Drive" }),
    ).toBeDisabled();

    serverDisconnected = true;
    const failedResponse = await json(
      { detail: "raw-google-disconnect-failure" },
      false,
      503,
    );
    await act(async () => resolveDelete?.(failedResponse));
    expect(
      await screen.findByText(
        "Отключение Google Drive подтверждено по актуальному состоянию.",
      ),
    ).toBeInTheDocument();
    expect(await screen.findByText("Google Drive не подключён")).toBeInTheDocument();
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          url === "/api/google/connection" && init?.method === "DELETE",
      ),
    ).toHaveLength(1);
    expect(document.body.textContent).not.toContain(
      "raw-google-disconnect-failure",
    );

    const readsBeforeFinalReopen = connectionReads;
    await openProjectsPage();
    await openSettingsSection("Подключения");
    await screen.findByText("Google Drive не подключён");
    expect(connectionReads).toBe(readsBeforeFinalReopen + 2);
  });

  it("keeps the authoritative connected state after an ambiguous disconnect", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let connectionReads = 0;
    const activeConnection = googleConnectionFixture({
      connected: true,
      status: "active",
      google_email: "safe.user@example.com",
      scopes: "openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly",
      connected_at: "2026-07-01T00:00:00Z",
      picker_configured: true,
      picker_scope_ready: true,
      picker_ready: true,
    });
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/google/connection" && !init?.method) {
        connectionReads += 1;
        return json(activeConnection);
      }
      if (url === "/api/google/connection" && init?.method === "DELETE")
        return json({ detail: "raw-google-still-connected" }, false, 503);
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openSettingsSection("Подключения");
    const readsBeforeMutation = connectionReads;
    await userEvent.click(
      await screen.findByRole("button", { name: "Отключить Google Drive" }),
    );
    expect(
      await screen.findByText(
        "Studio не подтвердила отключение. Показан актуальный статус; проверьте его перед повторной попыткой.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Google Drive подключён")).toBeInTheDocument();
    expect(connectionReads).toBe(readsBeforeMutation + 1);
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          url === "/api/google/connection" && init?.method === "DELETE",
      ),
    ).toHaveLength(1);
    expect(document.body.textContent).not.toContain(
      "raw-google-still-connected",
    );
  });
  it("invalidates a late OAuth start response after logout", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let resolveStart: ((response: Response) => void) | undefined;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/google/connection" && !init?.method)
        return json(googleConnectionFixture());
      if (url === "/api/google/oauth/start" && init?.method === "POST")
        return new Promise<Response>((resolve) => {
          resolveStart = resolve;
        });
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const assign = vi.fn();
    Object.defineProperty(window, "location", {
      value: { ...window.location, assign },
      writable: true,
    });

    renderApp();
    await openSettingsSection("Подключения");
    await userEvent.click(
      await screen.findByRole("button", { name: "Подключить Google Drive" }),
    );
    await waitFor(() => expect(resolveStart).toBeDefined());
    await userEvent.click(screen.getByRole("tab", { name: "Аккаунт" }));
    await userEvent.click(screen.getByRole("button", { name: "Выйти" }));
    expect(
      await screen.findByRole("heading", { name: "Вход" }),
    ).toBeInTheDocument();

    const successfulResponse = await json(googleOauthStartFixture());
    await act(async () => resolveStart?.(successfulResponse));
    expect(assign).not.toHaveBeenCalled();
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          url === "/api/google/oauth/start" && init?.method === "POST",
      ),
    ).toHaveLength(1);
    expect(document.body.textContent).not.toContain("secret-state");
  });
  it("supports credential replacement without rendering raw key", async () => {
    renderApp();
    await openSettingsSection("Подключения");
    await userEvent.click(
      await screen.findByRole("button", { name: "Заменить" }),
    );
    await userEvent.type(
      screen.getByPlaceholderText("Новый ключ для замены"),
      "raw-secret-never-render",
    );
    await userEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(
      screen.queryByText("raw-secret-never-render"),
    ).not.toBeInTheDocument();
  });

  it("explains and confirms credential disable and permanent deletion", async () => {
    const confirm = vi.mocked(window.confirm);
    confirm.mockReturnValue(false);
    renderApp();
    await openSettingsSection("Подключения");

    expect(
      await screen.findByText(/Отключение запрещает использовать ключ/),
    ).toBeInTheDocument();
    await clickCredentialAction("Отключить");
    expect(confirm).toHaveBeenLastCalledWith(
      "Отключить ключ «Primary STT»? Он станет недоступен для новых и выполняющихся задач, но история версий сохранится.",
    );
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(
        ([url]) => url === "/api/credentials/cred-active/revoke",
      ),
    ).toBe(false);

    confirm.mockReturnValue(true);
    await clickCredentialAction("Отключить");
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/credentials/cred-active/revoke",
        expect.objectContaining({ method: "POST" }),
      ),
    );

    confirm.mockReturnValue(false);
    await clickCredentialAction("Удалить навсегда");
    expect(confirm).toHaveBeenLastCalledWith(
      "Удалить ключ «Primary STT» навсегда? Все сохранённые значения будут стёрты без возможности восстановления.",
    );
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(
        ([url, init]) =>
          url === "/api/credentials/cred-active" && init?.method === "DELETE",
      ),
    ).toBe(false);

    confirm.mockReturnValue(true);
    await clickCredentialAction("Удалить навсегда");
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/credentials/cred-active",
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
  });

  it.each(["tbank", "mistral", "gemini"])("prepares a separate %s key without retaining secret inputs", async (provider) => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const stored: Record<string, unknown>[] = [];
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/credentials" && !init?.method) return json({ credentials: stored });
      if (url === "/api/credentials" && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        const row = { id: "synthetic-new", provider: body.provider, label: body.label, status: "active", masked_value: "••••synthetic", active_version: 1, folder_id: null };
        stored.push(row);
        return json(row);
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    await openSettingsSection("Подключения");
    await userEvent.click(await screen.findByRole("button", { name: "Добавить ключ" }));
    await userEvent.selectOptions(screen.getByLabelText("Провайдер"), provider);
    await userEvent.type(screen.getByPlaceholderText("Метка"), "Synthetic new provider");
    const secret = "synthetic-sensitive-value";
    if (provider === "tbank") await userEvent.type(screen.getByLabelText("API_KEY VoiceKit"), "synthetic-public-id");
    await userEvent.type(screen.getByPlaceholderText("Новый ключ"), secret);
    await userEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => expect(stored).toHaveLength(1));
    const call = baseFetch.mock.calls.find(([url, init]) => url === "/api/credentials" && init?.method === "POST");
    const body = JSON.parse(String(call?.[1]?.body));
    expect(body.provider).toBe(provider);
    if (provider === "tbank") expect(JSON.parse(body.raw_value)).toEqual({ api_key: "synthetic-public-id", secret_key: secret });
    else expect(body.raw_value).toBe(secret);
    expect(screen.queryByDisplayValue(secret)).not.toBeInTheDocument();
    expect(JSON.stringify({ ...sessionStorage, ...localStorage })).not.toContain(secret);
  });

  it("creates credentials with raw_value while using credential-specific field names", async () => {
    renderApp();
    await openSettingsSection("Подключения");
    await userEvent.click(
      await screen.findByRole("button", { name: "Добавить ключ" }),
    );
    await userEvent.type(
      await screen.findByPlaceholderText("Метка"),
      "primary-provider",
    );
    await userEvent.type(
      screen.getByPlaceholderText("Новый ключ"),
      "fake-provider-token",
    );
    await userEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/credentials",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    const createCall = (
      fetch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.find(
      ([url, init]) => url === "/api/credentials" && init?.method === "POST",
    );
    expect(JSON.parse(String(createCall?.[1]?.body))).toMatchObject({
      label: "primary-provider",
      raw_value: "fake-provider-token",
    });
  });

  it("bounds a stalled credential-list read and exposes a safe retry", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const credentialSignals: AbortSignal[] = [];
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/credentials" && !init?.method) {
        const signal = init?.signal;
        if (!signal) throw new Error("credential-list signal is missing");
        credentialSignals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 15_000 ? 1 : (delay as number),
          ...args,
        )) as typeof setTimeout);

    try {
      renderApp();
      await openSettingsSection("Подключения");
      expect(
        await screen.findByText(
          "Не удалось загрузить ключи провайдеров. Повторите попытку.",
        ),
      ).toBeInTheDocument();
      expect(credentialSignals).toHaveLength(2);
      expect(credentialSignals[0]?.aborted).toBe(true);
      expect(credentialSignals[1]?.aborted).toBe(true);
      expect(
        screen.getByRole("button", { name: "Добавить ключ" }),
      ).toBeDisabled();
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("rejects a malformed credential collection before rendering actions", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) =>
      url === "/api/credentials" && !init?.method
        ? json({ credentials: [{ id: "unsafe-incomplete-record" }] })
        : (defaultFetch?.(url, init) ?? json({ ok: true })),
    );

    renderApp();
    await openSettingsSection("Подключения");
    expect(
      await screen.findByText(
        "Не удалось загрузить ключи провайдеров. Повторите попытку.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("unsafe-incomplete-record")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Заменить" })).not.toBeInTheDocument();
  });

  it("bounds and deduplicates credential creation while clearing the raw value", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const createSignals: AbortSignal[] = [];
    let credentialReads = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/credentials" && !init?.method) credentialReads += 1;
      if (url === "/api/credentials" && init?.method === "POST") {
        const signal = init.signal;
        if (!signal) throw new Error("credential-create signal is missing");
        createSignals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openSettingsSection("Подключения");
    await userEvent.click(
      await screen.findByRole("button", { name: "Добавить ключ" }),
    );
    const label = await screen.findByPlaceholderText("Метка");
    const rawValue = screen.getByPlaceholderText("Новый ключ");
    await userEvent.type(label, "deadline-safe");
    await userEvent.type(rawValue, "raw-secret-cleared-immediately");
    const form = label.closest("form");
    if (!form) throw new Error("credential-create form is missing");
    const readsBeforeCreate = credentialReads;

    vi.useFakeTimers();
    try {
      fireEvent.submit(form);
      fireEvent.submit(form);
      await act(async () => {
        await Promise.resolve();
      });
      expect(createSignals).toHaveLength(1);
      expect(rawValue).toHaveValue("");
      expect(label).toHaveValue("deadline-safe");
      expect(
        screen.getByRole("button", { name: "Создаём…" }),
      ).toBeDisabled();
      expect(
        screen.getByRole("button", { name: "Создаём ключ…" }),
      ).toHaveAttribute("aria-busy", "true");

      await act(async () => {
        await vi.advanceTimersByTimeAsync(20_000);
      });
      vi.useRealTimers();
      expect(
        await screen.findByText(
          "Studio не подтвердила создание ключа. Список обновлён; проверьте его перед повторной попыткой. Значение ключа нужно ввести заново.",
        ),
      ).toBeInTheDocument();
      expect(createSignals[0]?.aborted).toBe(true);
      expect(credentialReads).toBe(readsBeforeCreate + 1);
      expect(rawValue).toHaveValue("");
      expect(label).toHaveValue("deadline-safe");
      expect(screen.getByRole("button", { name: "Создать" })).toBeEnabled();
      expect(
        baseFetch.mock.calls.filter(
          ([url, init]) =>
            url === "/api/credentials" && init?.method === "POST",
        ),
      ).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps an ambiguous credential replacement owned across navigation", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let resolveReplace: ((response: Response) => void) | undefined;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url === "/api/credentials/cred-active/replace" &&
        init?.method === "POST"
      ) {
        return new Promise<Response>((resolve) => {
          resolveReplace = resolve;
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openSettingsSection("Подключения");
    await userEvent.click(
      await screen.findByRole("button", { name: "Заменить" }),
    );
    const rawValue = screen.getByPlaceholderText("Новый ключ для замены");
    await userEvent.type(rawValue, "raw-navigation-secret");
    const form = rawValue.closest("form");
    if (!form) throw new Error("credential-replace form is missing");
    fireEvent.submit(form);
    fireEvent.submit(form);
    await waitFor(() => expect(resolveReplace).toBeDefined());
    expect(rawValue).toHaveValue("");
    expect(
      screen.getByRole("button", { name: "Сохраняем…" }),
    ).toBeDisabled();
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          url === "/api/credentials/cred-active/replace" &&
          init?.method === "POST",
      ),
    ).toHaveLength(1);

    await openProjectsPage();
    const failedResponse = await json(
      { detail: "raw-provider-failure-must-not-render" },
      false,
      503,
    );
    await act(async () => resolveReplace?.(failedResponse));
    await openSettingsSection("Подключения");
    expect(
      await screen.findByText(
        "Studio не подтвердила замену ключа. Список обновлён; проверьте версию перед повторной попыткой. Значение ключа нужно ввести заново.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Заменить" })).toBeEnabled();
    expect(document.body.textContent).not.toContain("raw-navigation-secret");
    expect(document.body.textContent).not.toContain(
      "raw-provider-failure-must-not-render",
    );
  });

  it("confirms an ambiguous revoke only from the credential list", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let revoked = false;
    let revokeCalls = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/credentials" && !init?.method) {
        return json({
          credentials: [
            {
              id: "cred-active",
              provider: "elevenlabs",
              label: "Primary STT",
              status: revoked ? "revoked" : "active",
              masked_value: "••••1234",
              active_version: 2,
            },
          ],
        });
      }
      if (
        url === "/api/credentials/cred-active/revoke" &&
        init?.method === "POST"
      ) {
        revokeCalls += 1;
        revoked = true;
        return json({ detail: "ambiguous-after-revoke" }, false, 503);
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openSettingsSection("Подключения");
    await clickCredentialAction("Отключить");
    expect(
      await screen.findByText(
        "Отключение ключа подтверждено по актуальному списку.",
      ),
    ).toBeInTheDocument();
    expect(revokeCalls).toBe(1);
    expect(screen.getByText(/revoked · v2/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("ambiguous-after-revoke");
  });
  it("confirms an ambiguous permanent deletion only from the credential list", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let deleted = false;
    let deleteCalls = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/credentials" && !init?.method) {
        return json({
          credentials: deleted
            ? []
            : [
                {
                  id: "cred-active",
                  provider: "elevenlabs",
                  label: "Primary STT",
                  status: "active",
                  masked_value: "••••1234",
                  active_version: 2,
                },
              ],
        });
      }
      if (
        url === "/api/credentials/cred-active" &&
        init?.method === "DELETE"
      ) {
        deleteCalls += 1;
        deleted = true;
        return json({ detail: "ambiguous-after-delete" }, false, 503);
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openSettingsSection("Подключения");
    await clickCredentialAction("Удалить навсегда");
    expect(
      await screen.findByText(
        "Удаление ключа подтверждено по актуальному списку.",
      ),
    ).toBeInTheDocument();
    expect(deleteCalls).toBe(1);
    expect(
      screen.queryByRole("heading", { name: "Primary STT" }),
    ).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("ambiguous-after-delete");
  });
  it("loads the transcription workspace and renders both modes", async () => {
    renderApp();
    await openProjectsPage();

    expect(
      await screen.findByRole("tab", { name: "Обычная транскрибация" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: "Live-транскрибация" }),
    ).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      "/api/projects",
      expect.objectContaining({ credentials: "same-origin" }),
    );
    expect(
      screen.queryByRole("button", { name: "Новый проект" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Архивировать" }),
    ).not.toBeInTheDocument();
  });

  it("opens transcriptions with the exact prepared audio source", async () => {
    renderApp();
    await waitForPlatformOverview();

    act(() => {
      window.dispatchEvent(
        new CustomEvent("studio:transcribe-source", {
          detail: { sourceId: "s1" },
        }),
      );
    });

    expect(
      await screen.findByRole("heading", { name: "Транскрибации" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByLabelText("Существующий файл для задачи 1"),
    ).toHaveValue("s1");
    expect(
      screen.getByText(
        "Результат обработки добавлен в новую задачу транскрибации.",
      ),
    ).toBeInTheDocument();
  });

  it("creates one internal transcription workspace when no active project exists", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const workspace = projectFixture({
      id: "transcription-workspace",
      title: "Транскрибации",
    });
    let workspaceCalls = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/projects" && !init?.method) {
        return json({ projects: [] });
      }
      if (
        url === "/api/transcriptions/workspace" &&
        init?.method === "POST"
      ) {
        workspaceCalls += 1;
        return json({ project: workspace, created: true });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();

    expect(
      await screen.findByRole("tab", { name: "Обычная транскрибация" }),
    ).toBeInTheDocument();
    expect(workspaceCalls).toBe(1);
    expect(
      baseFetch.mock.calls.some(
        ([url, init]) =>
          url === "/api/projects/transcription-workspace/archive" &&
          init?.method === "POST",
      ),
    ).toBe(false);
  });

  it("shows a retryable error when the transcription workspace list fails", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/projects" && !init?.method) {
        return json({ detail: "broken" }, false, 500);
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();

    expect(
      await screen.findByText(/Операция не выполнена/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Повторить" })).toBeEnabled();
  });

  it("bounds a stalled transcription-workspace read and exposes a safe retry", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const projectSignals: AbortSignal[] = [];
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/projects" && !init?.method) {
        const signal = init.signal;
        if (!signal) throw new Error("project-list signal is missing");
        projectSignals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 15_000 ? 1 : (delay as number),
          ...args,
        )) as typeof setTimeout);

    try {
      renderApp();
      await openProjectsPage();
      expect(
        await screen.findByText("Не удалось загрузить транскрибации."),
      ).toBeInTheDocument();
      expect(projectSignals).toHaveLength(2);
      expect(projectSignals[0]?.aborted).toBe(true);
      expect(projectSignals[1]?.aborted).toBe(true);
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("reconciles an ambiguous automatic workspace creation without a duplicate POST", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const workspace = projectFixture({
      id: "reconciled-workspace",
      title: "Транскрибации",
    });
    const createSignals: AbortSignal[] = [];
    let projectReads = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/projects" && !init?.method) {
        projectReads += 1;
        return json({
          projects: projectReads >= 3 ? [workspace] : [],
        });
      }
      if (
        url === "/api/transcriptions/workspace" &&
        init?.method === "POST"
      ) {
        const signal = init.signal;
        if (!signal) throw new Error("workspace-create signal is missing");
        createSignals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 20_000 ? 1 : (delay as number),
          ...args,
        )) as typeof setTimeout);

    try {
      renderApp();
      await openProjectsPage();
      expect(
        await screen.findByRole("tab", { name: "Обычная транскрибация" }),
      ).toBeInTheDocument();
      expect(createSignals).toHaveLength(1);
      expect(createSignals[0]?.aborted).toBe(true);
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("shows compact preparation readiness status", async () => {
    renderApp();
    await openProjectsPage();
    await screen.findByRole("heading", { name: "Подготовка задач" });
    const status = await screen.findByLabelText("Готовность задач подготовки");
    expect(status).toHaveTextContent("Готово: 0 из 1");
    expect(status).toHaveTextContent("Задача 1: выберите источник");
    expect(screen.getByText("Название документа")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Необязательно. Если оставить пустым, Google Docs получит имя исходного файла.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Готовность" }),
    ).not.toBeInTheDocument();
  });

  it("derives readiness, blockers, and submit state from row readiness", async () => {
    renderApp();
    await openProjectsPage();

    const readiness = await screen.findByLabelText(
      "Готовность задач подготовки",
    );
    expect(readiness).toHaveTextContent("Готово: 0 из 1");
    expect(readiness).toHaveTextContent("Задача 1: выберите источник");
    expect(
      screen.queryByRole("button", { name: "Поднять задачу 1" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Удалить задачу 1" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Проверить задачи (1)" }),
    ).toBeDisabled();

    await chooseExistingSource(1, "Лекция 1");
    expect(readiness).toHaveTextContent("Готово: 0 из 1");
    expect(readiness).toHaveTextContent("Задача 1: выберите папку результата");
    await chooseResultFolder(1);
    expect(readiness).toHaveTextContent("Готово: 1 из 1");
    expect(
      screen.getByRole("button", { name: "Проверить задачи (1)" }),
    ).toBeEnabled();

    await userEvent.click(
      screen.getByRole("button", { name: "Добавить задачу" }),
    );
    expect(
      screen.getByRole("status", { name: "Результат добавления задачи" }),
    ).toHaveTextContent("Добавлена задача 2. Выберите источник.");
    await waitFor(() =>
      expect(
        screen.getByLabelText("Существующий файл для задачи 2"),
      ).toHaveFocus(),
    );
    await chooseExistingSource(2, "Лекция 1");
    await chooseResultFolder(2);
    expect(readiness).toHaveTextContent("Готово: 0 из 2");
    expect(readiness).toHaveTextContent(
      "Задача 1: такой источник, папка и диапазон уже добавлены",
    );
    expect(
      screen.getAllByText("Такой источник, папка и диапазон уже добавлены.")
        .length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByRole("button", { name: "Проверить задачи (2)" }),
    ).toBeDisabled();

    await chooseExistingSource(2, "local-temp");
    expect(readiness).toHaveTextContent("Готово: 2 из 2");
    expect(readiness).toHaveTextContent("Все задачи готовы");
    expect(
      screen.getByRole("button", { name: "Проверить задачи (2)" }),
    ).toBeEnabled();
  });

  it("shows server-authoritative batch preflight and invalidates it after edits", async () => {
    renderApp();
    await openProjectsPage();
    await chooseExistingSource(1, "Лекция 1");
    await chooseResultFolder(1);
    await userEvent.selectOptions(
      screen.getByLabelText("Язык транскрибации"),
      "detect",
    );
    const diarizationToggle = screen.getByLabelText("Разделять на спикеров");
    expect(
      screen.getByText("Разделение спикеров: выключено"),
    ).toBeInTheDocument();
    await userEvent.click(diarizationToggle);
    expect(
      screen.getByText("Разделение спикеров: включено"),
    ).toBeInTheDocument();
    expect(diarizationToggle.closest("label")).toHaveClass("is-enabled");

    await userEvent.click(
      screen.getByRole("button", { name: "Проверить задачи (1)" }),
    );

    const preview = await screen.findByLabelText(
      "Проверка перед созданием задач",
    );
    expect(preview).toHaveTextContent("ElevenLabs scribe_v2");
    expect(preview).toHaveTextContent("Автоопределение");
    expect(preview).toHaveTextContent("Разделение спикеров: включено");
    expect(preview).toHaveTextContent("Safe source 1");
    expect(preview).toHaveTextContent("Safe folder 1");
    expect(preview).toHaveTextContent("План: обработать");
    expect(preview).toHaveTextContent(
      "Совпадений с теми же настройками среди результатов Studio и точно связанных записей каталога не найдено.",
    );
    expect(preview).toHaveTextContent(
      "Проверены принятые результаты Studio и записи импортированного каталога",
    );
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(
        ([url, init]) =>
          url === "/api/projects/p1/jobs/batch/preflight" &&
          init?.method === "POST",
      ),
    ).toBe(true);
    const preflightCall = (
      fetch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.find(
      ([url, init]) =>
        url === "/api/projects/p1/jobs/batch/preflight" &&
        init?.method === "POST",
    );
    expect(preflightCall?.[1]?.headers).not.toHaveProperty("Idempotency-Key");
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(
        ([url, init]) =>
          url === "/api/projects/p1/jobs/batch" && init?.method === "POST",
      ),
    ).toBe(false);

    await userEvent.type(
      screen.getByLabelText("Название документа задачи 1"),
      " Уточнение",
    );
    await waitFor(() =>
      expect(
        screen.queryByLabelText("Проверка перед созданием задач"),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: "Проверить задачи (1)" }),
    ).toBeEnabled();
  });

  it("shows the disabled speaker-separation state explicitly in composer and preflight", async () => {
    renderApp();
    await openProjectsPage();
    await chooseExistingSource(1, "Лекция 1");
    await chooseResultFolder(1);

    const diarizationToggle = screen.getByLabelText("Разделять на спикеров");
    expect(diarizationToggle).not.toBeChecked();
    expect(diarizationToggle.closest("label")).not.toHaveClass("is-enabled");
    expect(
      screen.getByText("Разделение спикеров: выключено"),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Проверить задачи (1)" }),
    );
    const preview = await screen.findByLabelText(
      "Проверка перед созданием задач",
    );
    expect(preview).toHaveTextContent("Разделение спикеров: выключено");
    expect(
      within(preview).getByText("Разделение спикеров: выключено"),
    ).not.toHaveClass("is-enabled");
  });

  it("shows only materially distinct provider modes and explains the effective choice", async () => {
    renderApp();
    await openProjectsPage();

    expect(
      screen.queryByLabelText("Режим транскрибации"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/Других реально отличающихся режимов провайдер сейчас не предлагает/),
    ).toBeInTheDocument();
    expect(screen.getByText(/scribe_v2 · обработка: обычная/)).toBeInTheDocument();
    expect(
      screen.getByText(/Стоимость здесь не сравнивается/),
    ).toBeInTheDocument();
  });

  it("offers and persists system, light, and dark appearance choices", async () => {
    renderApp();
    await openSettingsSection("Оформление");
    const selector = screen.getByLabelText("Тема интерфейса");
    expect(selector).toHaveValue("system");
    await userEvent.selectOptions(selector, "dark");
    expect(localStorage.getItem("studio-theme-preference")).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    await userEvent.selectOptions(selector, "light");
    expect(localStorage.getItem("studio-theme-preference")).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("persists and applies the owner accent color without browser storage", async () => {
    renderApp();
    await openSettingsSection("Оформление");
    const selector = await screen.findByLabelText("Цвет интерфейса");
    expect(selector).toHaveValue("blue");

    await userEvent.selectOptions(selector, "violet");

    expect(
      await screen.findByText("Цвет интерфейса сохранён."),
    ).toBeInTheDocument();
    expect(document.documentElement.dataset.accent).toBe("violet");
    expect(fetch).toHaveBeenCalledWith(
      "/api/account/preferences",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ accent_color: "violet" }),
      }),
    );
    expect(localStorage.getItem("studio-accent-preference")).toBeNull();
  });

  it("builds arbitrary ordered segment jobs from one source", async () => {
    renderApp();
    await openProjectsPage();
    await chooseExistingSource(1, "Лекция 1");
    await chooseResultFolder(1, "folder-segments");

    const fragmentationToggle = screen.getByRole("checkbox", {
      name: /Разделить файл на фрагменты/,
    });
    expect(fragmentationToggle).not.toBeChecked();
    await userEvent.click(fragmentationToggle);
    expect(fragmentationToggle).toBeChecked();

    const count = screen.getByLabelText("Количество фрагментов задачи 1");
    fireEvent.change(count, { target: { value: "3" } });
    expect(
      screen.getByRole("button", { name: "Проверить задачи (3)" }),
    ).toBeDisabled();
    await userEvent.click(screen.getAllByRole("checkbox", {name:"До конца файла"})[0]);
    await userEvent.type(
      screen.getByLabelText("Конец фрагмента 1 задачи 1"),
      "10:10",
    );
    await userEvent.type(
      screen.getByLabelText("Начало фрагмента 2 задачи 1"),
      "10:10",
    );
    await userEvent.type(
      screen.getByLabelText("Конец фрагмента 2 задачи 1"),
      "15:15",
    );
    await userEvent.type(
      screen.getByLabelText("Начало фрагмента 3 задачи 1"),
      "15:20",
    );
    await userEvent.type(
      screen.getByLabelText("Название фрагмента 1 задачи 1"),
      "Часть один",
    );
    await userEvent.type(
      screen.getByLabelText("Название фрагмента 2 задачи 1"),
      "Часть два",
    );
    await userEvent.type(
      screen.getByLabelText("Название фрагмента 3 задачи 1"),
      "Часть три",
    );
    await chooseSegmentResultFolder(
      1,
      2,
      "folder-second-segment",
      "Папка второго фрагмента",
    );
    expect(screen.getByText("Собственная папка этого фрагмента.")).toBeInTheDocument();
    await userEvent.click(fragmentationToggle);
    expect(fragmentationToggle).not.toBeChecked();
    await userEvent.click(fragmentationToggle);
    expect(screen.getByLabelText("Количество фрагментов задачи 1")).toHaveValue(3);
    expect(
      screen.getByLabelText("Название фрагмента 2 задачи 1"),
    ).toHaveValue("Часть два");

    const endField=screen.getByLabelText("Конец фрагмента 1 задачи 1");
    fireEvent.change(endField,{target:{value:"0:00"}});
    expect(endField).toHaveAttribute("aria-invalid","true");
    const errorId=endField.getAttribute("aria-describedby");
    expect(errorId && document.getElementById(errorId)).toHaveTextContent("конец должен быть позже начала");
    fireEvent.change(endField,{target:{value:"10:10"}});
    expect(endField).not.toHaveAttribute("aria-invalid");
    await userEvent.click(
      screen.getByRole("button", { name: "Проверить задачи (3)" }),
    );
    const preview = await screen.findByLabelText(
      "Проверка перед созданием задач",
    );
    expect(preview).toHaveTextContent("Часть файла: Начало — 10:10");
    expect(preview).toHaveTextContent("Документ: Часть один");
    expect(preview).toHaveTextContent("Папка: Safe folder 2");
    expect(preview).toHaveTextContent("План требует проверки длительности");
    expect(preview).toHaveTextContent("Часть файла: 10:10 — 15:15");
    expect(preview).toHaveTextContent("Часть файла: 15:20 — конец");
    const preflightCall = (
      fetch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.find(
      ([url, init]) =>
        url === "/api/projects/p1/jobs/batch/preflight" &&
        init?.method === "POST",
    );
    const body = JSON.parse(String(preflightCall?.[1]?.body));
    expect(body.items).toEqual([
      expect.objectContaining({
        source_id: "s1",
        output_folder_id: "folder-segments",
        title: "Часть один",
        media_clip_start_seconds: 0,
        media_clip_end_seconds: 610,
      }),
      expect.objectContaining({
        source_id: "s1",
        output_folder_id: "folder-second-segment",
        title: "Часть два",
        media_clip_start_seconds: 610,
        media_clip_end_seconds: 915,
      }),
      expect.objectContaining({
        source_id: "s1",
        output_folder_id: "folder-segments",
        title: "Часть три",
        media_clip_start_seconds: 920,
        media_clip_end_seconds: null,
      }),
    ]);
  });

  it("blocks an existing result until the user explicitly accepts paid reprocessing", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (isBatchPreflightRequest(url, init)) {
        const request = JSON.parse(String(init?.body ?? "{}")) as {
          language?: "ru" | "en" | "detect";
          options?: { diarize?: boolean };
          items?: {
            title?: string | null;
            reprocess_existing?: boolean;
          }[];
        };
        const reprocess = request.items?.[0]?.reprocess_existing === true;
        return json({
          provider: "elevenlabs",
          model: "scribe_v2",
          operating_mode: "standard",
          dictionary_term_count: 0,
          language_mode: request.language ?? "ru",
          diarization_enabled: request.options?.diarize === true,
          existing_result_authority: {
            status: "partial",
            reason_code: "unlinked_catalog_entries_excluded",
          },
          items: [
            {
              position: 0,
              title: request.items?.[0]?.title ?? null,
              media_clip: null,
              source: {
                name: "Safe source 1",
                source_type: "google_drive",
                mime_type: "audio/mpeg",
                size_bytes: 2048,
                duration_seconds: null,
              },
              output_destination: { name: "Safe folder 1" },
              existing_result_match: {
                status: "accepted_match",
                accepted_output_count: 1,
                resolution: reprocess ? "reprocess" : "required",
              },
              provider_attempt_authority: {
                status: "available",
                reason_code: null,
                attention_job_id: null,
              },
              planned_outcome: reprocess ? "process" : "blocked",
            },
          ],
          summary: {
            process_count: reprocess ? 1 : 0,
            skip_count: 0,
            blocked_count: reprocess ? 0 : 1,
          },
          confirmation_required: true,
        });
      }
      if (
        url === "/api/projects/p1/jobs/batch" &&
        init?.method === "POST"
      ) {
        return json({ jobs: [], created_count: 1, replayed: false });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();
    await chooseExistingSource(1, "Лекция 1");
    await chooseResultFolder(1);
    await userEvent.click(
      screen.getByRole("button", { name: "Проверить задачи (1)" }),
    );

    const blocked = await screen.findByLabelText(
      "Проверка перед созданием задач",
    );
    expect(blocked).toHaveTextContent("План требует решения");
    expect(blocked).toHaveTextContent(
      "Есть готовый результат с теми же настройками.",
    );
    expect(blocked).toHaveTextContent("План: заблокировано");
    expect(
      screen.getByRole("button", {
        name: "Подтвердить и создать (1)",
      }),
    ).toBeDisabled();
    expect(
      baseFetch.mock.calls.some(
        ([url, init]) =>
          url === "/api/projects/p1/jobs/batch" && init?.method === "POST",
      ),
    ).toBe(false);

    await userEvent.click(
      screen.getByLabelText("Транскрибировать заново задачу 1"),
    );
    await waitFor(() =>
      expect(
        screen.queryByLabelText("Проверка перед созданием задач"),
      ).not.toBeInTheDocument(),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Проверить задачи (1)" }),
    );

    const approved = await screen.findByLabelText(
      "Проверка перед созданием задач",
    );
    expect(approved).toHaveTextContent("План: транскрибировать заново");
    expect(
      screen.getByRole("button", {
        name: "Подтвердить и создать (1)",
      }),
    ).toBeEnabled();
    await userEvent.click(
      screen.getByRole("button", {
        name: "Подтвердить и создать (1)",
      }),
    );
    await waitFor(() =>
      expect(
        baseFetch.mock.calls.some(
          ([url, init]) =>
            url === "/api/projects/p1/jobs/batch" && init?.method === "POST",
        ),
      ).toBe(true),
    );
    const createCall = baseFetch.mock.calls.find(
      ([url, init]) =>
        url === "/api/projects/p1/jobs/batch" && init?.method === "POST",
    );
    expect(JSON.parse(String(createCall?.[1]?.body))).toEqual(
      expect.objectContaining({
        items: [
          expect.objectContaining({
            reprocess_existing: true,
          }),
        ],
      }),
    );
  });

  it.each([
    [
      "equivalent_provider_work_in_flight",
      "Для этого источника уже выполняется транскрибация. Дождитесь её завершения и повторите проверку.",
    ],
    [
      "equivalent_provider_outcome_unresolved",
      "Предыдущая транскрибация имеет неопределённый результат. Дождитесь завершения проверки результата или обратитесь к сохранённой задаче.",
    ],
  ] as const)(
    "keeps provider authority %s blocked even when accepted-output reprocessing is available",
    async (reasonCode, expectedCopy) => {
      const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
      const defaultFetch = baseFetch.getMockImplementation();
      baseFetch.mockImplementation((url: string, init?: RequestInit) => {
        if (isBatchPreflightRequest(url, init)) {
          return json({
            provider: "elevenlabs",
            model: "scribe_v2",
            operating_mode: "standard",
            dictionary_term_count: 0,
            language_mode: "ru",
            diarization_enabled: false,
            existing_result_authority: {
              status: "partial",
              reason_code: "unlinked_catalog_entries_excluded",
            },
            items: [
              {
                position: 0,
                title: null,
                media_clip: null,
                source: {
                  name: "Safe source 1",
                  source_type: "google_drive",
                  mime_type: "audio/mpeg",
                  size_bytes: 2048,
                  duration_seconds: null,
                },
                output_destination: { name: "Safe folder 1" },
                existing_result_match: {
                  status: "accepted_match",
                  accepted_output_count: 1,
                  resolution: "required",
                },
                provider_attempt_authority: {
                  status: "blocked",
                  reason_code: reasonCode,
                  attention_job_id: reasonCode === "equivalent_provider_outcome_unresolved"
                    ? "11111111-1111-4111-8111-111111111111"
                    : null,
                },
                planned_outcome: "blocked",
              },
            ],
            summary: {
              process_count: 0,
              skip_count: 0,
              blocked_count: 1,
            },
            confirmation_required: true,
          });
        }
        return defaultFetch?.(url, init) ?? json({ ok: true });
      });

      renderApp();
      await openProjectsPage();
      await chooseExistingSource(1, "Лекция 1");
      await chooseResultFolder(1);
      await userEvent.click(
        screen.getByRole("button", { name: "Проверить задачи (1)" }),
      );

      const blocked = await screen.findByLabelText(
        "Проверка перед созданием задач",
      );
      expect(blocked).toHaveTextContent("План временно заблокирован");
      expect(blocked).toHaveTextContent(expectedCopy);
      expect(screen.queryByRole("button", { name: "Подтвердить отсутствие документа" })).not.toBeInTheDocument();
      expect(
        screen.getByRole("link", { name: "Посмотреть текущие транскрибации" }),
      ).toHaveAttribute("href", "#current-transcriptions");
      expect(
        screen.getByText(
          "Найдена активная или неразрешённая предыдущая транскрибация. Если доступно действие в плане, проверьте Google Drive и подтвердите отсутствие документа.",
        ),
      ).toBeInTheDocument();
      expect(
        screen.queryByText(
          "Найдены ранее созданные результаты. Выберите явное решение для каждой заблокированной задачи.",
        ),
      ).not.toBeInTheDocument();
      expect(
        screen.getByText(
          "Предыдущая транскрибация ещё выполняется или требует проверки",
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByLabelText("Транскрибировать заново задачу 1"),
      ).toBeDisabled();
      expect(
        screen.getByRole("button", {
          name: "Подтвердить и создать (1)",
        }),
      ).toBeDisabled();
      expect(
        baseFetch.mock.calls.some(
          ([url, init]) =>
            url === "/api/projects/p1/jobs/batch" &&
            init?.method === "POST",
        ),
      ).toBe(false);
    },
  );

  it("resolves an older hidden attempt from the blocked plan without starting STT", async () => {
    const oldJobId = "11111111-1111-4111-8111-111111111111";
    let acknowledged = false;
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (isBatchPreflightRequest(url, init)) {
        return json({
          provider: "elevenlabs", model: "scribe_v2", operating_mode: "standard",
          dictionary_term_count: 0, language_mode: "ru", diarization_enabled: false,
          existing_result_authority: { status: "partial", reason_code: "unlinked_catalog_entries_excluded" },
          items: [{
            position: 0, title: null, media_clip: null,
            source: { name: "Практика №44.flac", source_type: "google_drive", mime_type: "audio/flac", size_bytes: 123, duration_seconds: null },
            output_destination: { name: "Results" },
            existing_result_match: { status: "no_match", accepted_output_count: 0, resolution: "not_required" },
            provider_attempt_authority: acknowledged
              ? { status: "available", reason_code: null, attention_job_id: null }
              : { status: "blocked", reason_code: "equivalent_provider_outcome_unresolved", attention_job_id: oldJobId },
            planned_outcome: acknowledged ? "process" : "blocked",
          }],
          summary: { process_count: acknowledged ? 1 : 0, skip_count: 0, blocked_count: acknowledged ? 0 : 1 },
          confirmation_required: true,
        });
      }
      if (url === `/api/jobs/${oldJobId}/attention-resolution` && init?.method === "POST") {
        acknowledged = true;
        return json({ history_attention_resolution: "acknowledged_no_result", history_attention_resolved_at: "2026-09-27T00:00:00Z" });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();
    await chooseExistingSource(1, "Лекция 1");
    await chooseResultFolder(1);
    await userEvent.click(screen.getByRole("button", { name: "Проверить задачи (1)" }));
    expect(await screen.findByRole("button", { name: "Подтвердить отсутствие документа" })).toBeEnabled();
    expect(screen.queryByRole("link", { name: "Посмотреть текущие транскрибации" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Подтвердить отсутствие документа" }));
    await waitFor(() => expect(screen.queryByLabelText("Проверка перед созданием задач")).not.toBeInTheDocument());
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("проверили папку результата в Google Drive"));
    const resolveCall = baseFetch.mock.calls.find(([url]) => url === `/api/jobs/${oldJobId}/attention-resolution`);
    expect(JSON.parse(String(resolveCall?.[1]?.body))).toEqual({
      resolution: "acknowledged_no_result", linked_job_id: null, confirm_possible_spend: true,
    });
    expect(baseFetch.mock.calls.some(([url, init]) => url === "/api/projects/p1/jobs/batch" && init?.method === "POST")).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Проверить задачи (1)" }));
    expect(await screen.findByText("План: обработать")).toBeInTheDocument();
  });

  it("invalidates a stale plan after a create-time provider authority race", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (isBatchPreflightRequest(url, init)) {
        return batchPreflightJson(init);
      }
      if (
        url === "/api/projects/p1/jobs/batch" &&
        init?.method === "POST"
      ) {
        return json(
          { detail: { reason: "provider_authority_conflict" } },
          false,
          409,
        );
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();
    await chooseExistingSource(1, "Лекция 1");
    await chooseResultFolder(1);
    await userEvent.click(
      screen.getByRole("button", { name: "Проверить задачи (1)" }),
    );
    await screen.findByLabelText("Проверка перед созданием задач");

    await userEvent.click(
      screen.getByRole("button", {
        name: "Подтвердить и создать (1)",
      }),
    );

    expect(
      await screen.findByText(
        "Появилась активная или неразрешённая предыдущая транскрибация. Задачи не созданы; проверьте план заново после разрешения её статуса.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Проверка перед созданием задач"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Проверить задачи (1)" }),
    ).toBeEnabled();
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          url === "/api/projects/p1/jobs/batch" &&
          init?.method === "POST",
      ),
    ).toHaveLength(1);
  });

  it("keeps rows incomplete when a selected source has no row result folder", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/projects") && !init?.method)
        return json({
          projects: [
            {
              id: "p1",
              title: "Research calls",
              description: "Customer interview notes",
              created_at: "2026-07-01T00:00:00",
              updated_at: "2026-07-01T00:00:00",
              archived_at: null,
              output_drive_folder_id: null,
              output_drive_folder_url: null,
              output_drive_folder_name: null,
            },
          ],
        });
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();
    await chooseExistingSource(1, "Лекция 1");

    const readiness = screen.getByLabelText("Готовность задач подготовки");
    expect(readiness).toHaveTextContent("Готово: 0 из 1");
    expect(readiness).toHaveTextContent("Задача 1: выберите папку результата");
    expect(
      screen.getByRole("button", { name: "Проверить задачи (1)" }),
    ).toBeDisabled();
  });

  it("exposes submitting progress as the submit button accessible name", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let resolveBatch: ((value: Response) => void) | null = null;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url.endsWith("/api/projects/p1/jobs/batch") &&
        init?.method === "POST"
      ) {
        return new Promise<Response>((resolve) => {
          resolveBatch = resolve;
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();
    await chooseExistingSource(1, "Лекция 1");
    await chooseResultFolder(1);
    await userEvent.click(
      screen.getByRole("button", { name: "Проверить задачи (1)" }),
    );
    await screen.findByLabelText("Проверка перед созданием задач");
    await userEvent.click(
      screen.getByRole("button", { name: "Подтвердить и создать (1)" }),
    );

    expect(
      await screen.findByRole("button", { name: "Создание задач…" }),
    ).toBeDisabled();
    await act(async () => {
      resolveBatch?.({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({ jobs: [], created_count: 1, replayed: false }),
        text: () => Promise.resolve("{}"),
      } as Response);
    });
    resolveBatch?.({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({ jobs: [], created_count: 1, replayed: false }),
      text: () => Promise.resolve("{}"),
    } as Response);
  });

  it("bounds stalled batch preflight without creating jobs", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const requestSignals: AbortSignal[] = [];
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (isBatchPreflightRequest(url, init)) {
        const signal = init?.signal;
        if (!signal) throw new Error("batch preflight signal is missing");
        requestSignals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();
    await chooseExistingSource(1, "Лекция 1");
    await chooseResultFolder(1);

    vi.useFakeTimers();
    try {
      fireEvent.click(
        screen.getByRole("button", { name: "Проверить задачи (1)" }),
      );
      await act(async () => {
        await Promise.resolve();
      });
      expect(requestSignals).toHaveLength(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(20_000);
      });

      expect(requestSignals[0]?.aborted).toBe(true);
      expect(
        screen.getByText(
          "Проверка плана заняла слишком много времени. Задачи не создавались; повторите проверку.",
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Проверить задачи (1)" }),
      ).toBeEnabled();
      expect(
        baseFetch.mock.calls.some(
          ([url, init]) =>
            url === "/api/projects/p1/jobs/batch" &&
            init?.method === "POST",
        ),
      ).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });
  it("bounds stalled batch creation without an automatic duplicate POST", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const requestSignals: AbortSignal[] = [];
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url === "/api/projects/p1/jobs/batch" &&
        init?.method === "POST"
      ) {
        const signal = init.signal;
        if (!signal) throw new Error("batch create signal is missing");
        requestSignals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();
    await chooseExistingSource(1, "Лекция 1");
    await chooseResultFolder(1);
    await userEvent.click(
      screen.getByRole("button", { name: "Проверить задачи (1)" }),
    );
    await screen.findByLabelText("Проверка перед созданием задач");

    vi.useFakeTimers();
    try {
      fireEvent.click(
        screen.getByRole("button", {
          name: "Подтвердить и создать (1)",
        }),
      );
      await act(async () => {
        await Promise.resolve();
      });
      expect(requestSignals).toHaveLength(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(20_000);
      });

      expect(requestSignals[0]?.aborted).toBe(true);
      expect(
        screen.getByLabelText("Неопределённый исход создания пакета"),
      ).toHaveTextContent("Новая отправка заблокирована");
      expect(
        screen.getByRole("button", {
          name: "Повторить подтверждение пакета",
        }),
      ).toBeEnabled();
      expect(
        baseFetch.mock.calls.filter(
          ([url, init]) =>
            url === "/api/projects/p1/jobs/batch" &&
            init?.method === "POST",
        ),
      ).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("creates, lists, details, and cancels project jobs safely with CSRF", async () => {
    const secretLike =
      "sk-live-raw-token refresh_token encrypted_ciphertext s3://secret-key https://upload.example/leak";
    const jobSources = [
      {
        id: "s2",
        project_id: "p1",
        position: 1,
        job_source_status: "queued",
        source_type: "local_upload",
        original_filename: "ready-local.ogg",
        mime_type: "audio/ogg",
        size_bytes: 4096,
        drive_file_id: null,
        drive_file_url: secretLike,
        upload_status: "uploaded",
        uploaded_at: "2026-07-01T00:02:00",
        expires_at: null,
        deleted_at: null,
        delete_reason: null,
        created_at: "2026-07-01T00:00:00",
        updated_at: "2026-07-01T00:00:00",
      },
      {
        id: "s1",
        project_id: "p1",
        position: 0,
        job_source_status: "queued",
        source_type: "google_drive",
        original_filename: "ready-drive.mp4",
        mime_type: "video/mp4",
        size_bytes: 2048,
        drive_file_id: "drive-file-1",
        drive_file_url: "https://drive.example/file/job-source",
        upload_status: "uploaded",
        uploaded_at: "2026-07-01T00:01:00",
        expires_at: null,
        deleted_at: null,
        delete_reason: null,
        created_at: "2026-07-01T00:00:00",
        updated_at: "2026-07-01T00:00:00",
      },
    ];
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string, init?: RequestInit) => {
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
          });
        if (url.endsWith("/api/auth/csrf"))
          return json({ csrf_token: "csrf-after-refresh" });
        if (url.endsWith("/api/stt/providers"))
          return json(sttProviderCatalogFixture());
        if (url.endsWith("/api/stt/dictionaries"))
          return json({ dictionaries: [] });
        if (url.endsWith("/api/google/connection"))
          return json({
            connected: true,
            status: "active",
            google_email: "safe.user@example.com",
            scopes: "openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly",
            connected_at: "2026-07-01T00:00:00",
            revoked_at: null,
            picker_configured: true,
            picker_scope_ready: true,
            picker_ready: true,
            reconnect_required: false,
          });
        if (url.endsWith("/api/credentials"))
          return json({
            credentials: [
              {
                id: "cred-active",
                provider: "elevenlabs",
                label: "Primary STT",
                status: "active",
                masked_value: "••••1234",
                active_version: 2,
                raw_value: secretLike,
                ciphertext: secretLike,
                nonce: secretLike,
              },
              {
                id: "cred-revoked",
                provider: "elevenlabs",
                label: "Revoked STT",
                status: "revoked",
                masked_value: "••••9999",
                active_version: 1,
              },
            ],
          });
        if (url.endsWith("/api/projects"))
          return json({
            projects: [
              {
                id: "p1",
                title: "Research calls",
                description: null,
                created_at: "2026-07-01T00:00:00",
                updated_at: "2026-07-01T00:00:00",
                archived_at: null,
                output_drive_folder_id: "folder-default",
                output_drive_folder_url:
                  "https://drive.google.com/drive/folders/folder-default",
                output_drive_folder_name: "Default folder",
              },
            ],
          });
        if (url.endsWith("/api/projects/p1/sources") && !init?.method)
          return json({
            sources: [
              {
                id: "s1",
                project_id: "p1",
                source_type: "google_drive",
                original_filename: "ready-drive.mp4",
                mime_type: "video/mp4",
                size_bytes: 2048,
                drive_file_id: "drive-file-1",
                drive_file_url: "https://drive.example/file/1",
                upload_status: "uploaded",
                uploaded_at: "2026-07-01T00:01:00",
                expires_at: null,
                deleted_at: null,
                delete_reason: null,
                created_at: "2026-07-01T00:00:00",
                updated_at: "2026-07-01T00:00:00",
              },
              {
                id: "s2",
                project_id: "p1",
                source_type: "local_upload",
                original_filename: "ready-local.ogg",
                mime_type: "audio/ogg",
                size_bytes: 4096,
                drive_file_id: null,
                drive_file_url: null,
                upload_status: "uploaded",
                uploaded_at: "2026-07-01T00:02:00",
                expires_at: null,
                deleted_at: null,
                delete_reason: null,
                created_at: "2026-07-01T00:00:00",
                updated_at: "2026-07-01T00:00:00",
              },
              {
                id: "s3",
                project_id: "p1",
                source_type: "local_upload",
                original_filename: "pending-local.ogg",
                mime_type: "audio/ogg",
                size_bytes: 1024,
                drive_file_id: null,
                drive_file_url: null,
                upload_status: "pending",
                uploaded_at: null,
                expires_at: null,
                deleted_at: null,
                delete_reason: null,
                created_at: "2026-07-01T00:00:00",
                updated_at: "2026-07-01T00:00:00",
              },
              {
                id: "s4",
                project_id: "p1",
                source_type: "google_drive",
                original_filename: "deleted-drive.mp4",
                mime_type: "video/mp4",
                size_bytes: null,
                drive_file_id: "drive-file-4",
                drive_file_url: secretLike,
                upload_status: "uploaded",
                uploaded_at: "2026-07-01T00:03:00",
                expires_at: null,
                deleted_at: "2026-07-01T00:04:00",
                delete_reason: "user",
                created_at: "2026-07-01T00:00:00",
                updated_at: "2026-07-01T00:00:00",
              },
            ],
          });
        if (url.endsWith("/api/credentials"))
          return json({
            credentials: [
              {
                id: "cred-active",
                provider: "elevenlabs",
                label: "Primary STT",
                status: "active",
                masked_value: "••••1234",
                active_version: 2,
              },
            ],
          });
        if (url.endsWith("/api/projects/p1/jobs") && !init?.method)
          return json({
            jobs: [
              {
                id: "job-1",
                project_id: "p1",
                status: "queued",
                title: "Queued review",
                provider: null,
                provider_credential_id: "cred-safe-id-not-rendered",
                source_count: 2,
                created_at: "2026-07-02T00:00:00Z",
                updated_at: "2026-07-02T00:01:00Z",
                cancelled_at: null,
                cancel_requested_at: null,
                attempt_count: 0,
                started_at: null,
                finished_at: null,
                error_code: null,
                error_message: null,
              },
              {
                id: "job-processing",
                project_id: "p1",
                status: "processing",
                title: "Processing review",
                provider: null,
                provider_credential_id: "cred-active",
                source_count: 1,
                created_at: "2026-07-02T00:00:00Z",
                updated_at: "2026-07-02T00:03:00Z",
                cancelled_at: null,
                cancel_requested_at: "2026-07-02T00:03:00Z",
                attempt_count: 2,
                started_at: "2026-07-02T00:01:00Z",
                finished_at: null,
                error_code: null,
                error_message: null,
              },
              {
                id: "job-2",
                project_id: "p1",
                status: "failed",
                title: null,
                provider: null,
                provider_credential_id: "cred-active",
                source_count: 1,
                source_names: ["Лекция 1.mp4"],
                created_at: "2026-07-03T00:00:00Z",
                updated_at: "2026-07-03T00:01:00Z",
                cancelled_at: null,
                cancel_requested_at: null,
                attempt_count: 0,
                started_at: null,
                finished_at: null,
                error_code: "SAFE_CODE",
                error_message: "Safe visible error",
              },
            ],
          });
        if (requestPath(url) === "/api/projects/p1/jobs/progress")
          return json({
            jobs: [
              {
                job_id: "job-1",
                job_status: "queued",
                tracking_precision: "checkpoint",
                completed_source_count: 0,
                total_source_count: 2,
                active_source_position: null,
                current_stage: null,
                sources: [
                  {
                    position: 0,
                    name: "ready-drive.mp4",
                    status: "queued",
                    provider_parts: null,
                    stages: progressStages(null),
                  },
                  {
                    position: 1,
                    name: "ready-local.ogg",
                    status: "queued",
                    provider_parts: null,
                    stages: progressStages(null, false),
                  },
                ],
              },
              {
                job_id: "job-processing",
                job_status: "processing",
                tracking_precision: "checkpoint",
                completed_source_count: 0,
                total_source_count: 1,
                active_source_position: 0,
                current_stage: "provider_processing",
                sources: [
                  {
                    position: 0,
                    name: "processing.mp4",
                    status: "processing",
                    provider_parts: null,
                    stages: progressStages("provider_processing"),
                  },
                ],
              },
            ],
            truncated: false,
            limit: 2,
          });
        if (isBatchPreflightRequest(url, init))
          return batchPreflightJson(init);
        if (
          url.endsWith("/api/projects/p1/jobs/batch") &&
          init?.method === "POST"
        )
          return json({
            jobs: [
              {
                id: "job-created",
                project_id: "p1",
                status: "queued",
                title: "Created from UI",
                provider: null,
                provider_credential_id: "cred-active",
                source_count: 1,
                sources: [],
                output_folder: {
                  name: "Default folder",
                  web_view_url:
                    "https://drive.google.com/drive/folders/folder-default",
                },
                created_at: "2026-07-04T00:00:00Z",
                updated_at: "2026-07-04T00:00:00Z",
                cancelled_at: null,
                cancel_requested_at: null,
                attempt_count: 0,
                started_at: null,
                finished_at: null,
                error_code: null,
                error_message: null,
              },
            ],
            created_count: 1,
            replayed: false,
          });
        if (url.endsWith("/api/jobs/job-1/outputs"))
          return json({
            job_id: "job-1",
            job_status: "processing",
            output_count: 3,
            outputs: [
              {
                source_id: "internal-source-id",
                source_position: 1,
                source_name: "second-output",
                source_type: "local_upload",
                output_kind: "transcript",
                transcript_standard: "plain",
                web_view_url:
                  "https://docs.google.com/document/d/doc-safe/edit",
                link_available: true,
                document_character_count: 222,
                document_created_at: "2026-07-02T00:10:00Z",
                persisted_at: "2026-07-02T00:11:00Z",
              },
              {
                source_id: "hidden-source-id",
                source_position: 0,
                source_name: "first-output",
                source_type: "google_drive",
                output_kind: "transcript",
                transcript_standard: "plain",
                web_view_url: null,
                link_available: false,
                document_character_count: 111,
                document_created_at: "2026-07-02T00:08:00Z",
                persisted_at: "2026-07-02T00:09:00Z",
              },
              {
                source_id: "unsafe-source-id",
                source_position: 2,
                source_name: "unsafe-output",
                source_type: "google_drive",
                output_kind: "transcript",
                transcript_standard: "plain",
                web_view_url: null,
                link_available: false,
                document_character_count: 333,
                document_created_at: "2026-07-02T00:12:00Z",
                persisted_at: "2026-07-02T00:13:00Z",
                transcript_text: "secret transcript body",
                credential_token: "credential-token",
                storage_key: "storage/private/key",
              },
            ],
          });
        if (url.endsWith("/api/jobs/job-1"))
          return json({
            id: "job-1",
            project_id: "p1",
            status: "queued",
            title: "Queued review",
            provider: null,
            provider_credential_id: "cred-active",
            source_count: 2,
            created_at: "2026-07-02T00:00:00Z",
            updated_at: "2026-07-02T00:01:00Z",
            cancelled_at: null,
            cancel_requested_at: null,
            attempt_count: 0,
            started_at: null,
            finished_at: null,
            error_code: null,
            error_message: null,
            sources: jobSources,
          });
        if (url.endsWith("/api/jobs/job-1/cancel") && init?.method === "POST")
          return json({
            id: "job-1",
            project_id: "p1",
            status: "cancelled",
            title: "Queued review",
            provider: null,
            provider_credential_id: "cred-active",
            source_count: 2,
            sources: jobSources,
            created_at: "2026-07-02T00:00:00Z",
            updated_at: "2026-07-02T00:02:00Z",
            cancelled_at: "2026-07-02T00:02:00Z",
            cancel_requested_at: null,
            attempt_count: 0,
            started_at: null,
            finished_at: null,
            error_code: null,
            error_message: null,
          });
        return json({});
      },
    );
    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/projects/p1/jobs",
        expect.objectContaining({ credentials: "same-origin" }),
      ),
    );
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/credentials",
        expect.objectContaining({ credentials: "same-origin" }),
      ),
    );
    expect(await screen.findByText("Queued review")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Подготовка задач" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Создайте задачу из готовых файлов проекта."),
    ).not.toBeInTheDocument();
    expect(
      screen.getByLabelText("Готовность задач подготовки"),
    ).toHaveTextContent("Готово: 0 из 1");
    expect(screen.getByText("Будет создано транскрибаций: 1")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("worker/provider");
    expect(screen.getByText("Лекция 1.mp4")).toBeInTheDocument();
    expect(screen.getByText("Статус: В очереди")).toBeInTheDocument();
    expect(screen.getByText("Статус: Ошибка")).toBeInTheDocument();
    expect(screen.getByText("Статус: Обрабатывается")).toBeInTheDocument();
    expect(screen.getByText(/Отмена запрошена:/)).toBeInTheDocument();
    expect(screen.getByText("Отмена запрошена")).toBeInTheDocument();
    expect(screen.getByText("Файлов: 2")).toBeInTheDocument();
    const processingProgress = await screen.findByLabelText(
      "Прогресс задачи job-processing",
    );
    expect(processingProgress).toHaveTextContent("Транскрибируем запись");
    expect(
      within(processingProgress).getByRole("progressbar", {
        name: "Общий прогресс транскрибации",
      }),
    ).toHaveClass("is-active");
    expect(processingProgress).toHaveTextContent(
      "Статус обновляется автоматически",
    );
    expect(processingProgress).toHaveTextContent("Подготовка источника");
    expect(processingProgress).toHaveTextContent("Извлечение аудио");
    expect(processingProgress).toHaveTextContent(
      "Разбиение на части (при необходимости)",
    );
    expect(processingProgress).toHaveTextContent("Распознавание речи");
    expect(processingProgress).toHaveTextContent(
      "Слияние частей (при необходимости)",
    );
    expect(processingProgress).toHaveTextContent("Сохранение документа");
    expect(
      within(processingProgress).getByText("Распознавание речи")
        .parentElement,
    ).toHaveTextContent("Выполняется");
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.filter(
        ([url]) => requestPath(String(url)) === "/api/projects/p1/jobs/progress",
      ),
    ).toHaveLength(1);
    expect(screen.queryByText("Error code: SAFE_CODE")).not.toBeInTheDocument();
    expect(screen.getByText(/Не удалось завершить обработку/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("Safe visible error");

    expect((await screen.findAllByText(/ready-drive/))[0]).toBeInTheDocument();
    expect(
      screen.getByLabelText("Готовность задач подготовки"),
    ).toHaveTextContent("Готово:");
    expect(
      within(screen.getByLabelText("Существующий файл для задачи 1")).getByRole(
        "option",
        { name: /pending-local\.ogg/ },
      ),
    ).toBeDisabled();
    expect(
      within(screen.getByLabelText("Существующий файл для задачи 1")).getByRole(
        "option",
        { name: /deleted-drive\.mp4/ },
      ),
    ).toBeDisabled();
    await chooseExistingSource(1, "ready-drive.mp4");
    await chooseResultFolder(1);
    await userEvent.click(
      screen.getByRole("button", { name: "Добавить задачу" }),
    );
    await chooseExistingSource(2, "ready-local.ogg");
    await chooseResultFolder(2);
    await userEvent.type(
      screen.getByLabelText("Название документа задачи 1"),
      "Created from UI",
    );
    const profileSelect = screen.queryByLabelText("Профиль подключения");
    if (profileSelect) {
      await userEvent.selectOptions(profileSelect, "cred-active");
    }
    const languageSelect = screen.getByLabelText("Язык транскрибации");
    expect(languageSelect).toHaveValue("ru");
    await userEvent.selectOptions(languageSelect, "en");
    const diarizationToggle = screen.getByLabelText("Разделять на спикеров");
    expect(diarizationToggle).not.toBeChecked();
    await userEvent.click(diarizationToggle);
    await reviewAndConfirmBatch();
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/projects/p1/jobs/batch",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    const createCall = (
      fetch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.find(
      ([url, init]) =>
        url === "/api/projects/p1/jobs/batch" && init?.method === "POST",
    );
    expect(createCall?.[1]?.headers).toMatchObject({
      "x-csrf-token": "csrf-after-refresh",
    });
    expect(JSON.parse(String(createCall?.[1]?.body))).toEqual({
      provider: "elevenlabs",
      operating_mode: "standard",
      provider_credential_id: "cred-active",
      language: "en",
      options: { diarize: true },
      items: [
        {
          source_id: "s1",
          output_folder_id: "folder-123",
          title: "Created from UI",
          reprocess_existing: false,
        },
        {
          source_id: "s2",
          output_folder_id: "folder-123",
          title: null,
          reprocess_existing: false,
        },
      ],
    });

    const queuedJobCard = screen.getByText("Queued review").closest("article");
    expect(queuedJobCard).not.toBeNull();
    await userEvent.click(
      within(queuedJobCard as HTMLElement).getByRole("button", {
        name: "Открыть",
      }),
    );
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/jobs/job-1",
        expect.objectContaining({ credentials: "same-origin" }),
      ),
    );
    const detail = await screen.findByLabelText("Подробности транскрибации");
    expect(within(detail).getByText("1. ready-drive.mp4")).toBeInTheDocument();
    expect(within(detail).getByText("2. ready-local.ogg")).toBeInTheDocument();
    expect(
      within(detail).getAllByText("Статус обработки: В очереди"),
    ).toHaveLength(2);
    expect(
      within(detail).queryByRole("link", {
        name: "Открыть файл в Google Drive в новой вкладке",
      }),
    ).not.toBeInTheDocument();
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/jobs/job-1/outputs",
        expect.objectContaining({ credentials: "same-origin" }),
      ),
    );
    const outputCall = (
      fetch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.find(([url]) => url === "/api/jobs/job-1/outputs");
    expect(outputCall?.[1]?.headers).not.toHaveProperty("x-csrf-token");
    const outputs = await screen.findByLabelText("Результаты транскрибации");
    expect(outputs).toHaveTextContent("2. second-output");
    expect(outputs).toHaveTextContent("1. first-output");
    expect(outputs.textContent?.indexOf("2. second-output")).toBeLessThan(
      outputs.textContent?.indexOf("1. first-output") ?? 0,
    );
    const outputLink = within(outputs).getByRole("link", {
      name: "Открыть документ",
    });
    expect(outputLink).toHaveAttribute(
      "href",
      "https://docs.google.com/document/d/doc-safe/edit",
    );
    expect(outputLink).toHaveAttribute("target", "_blank");
    expect(outputLink).toHaveAttribute("rel", "noopener noreferrer");
    expect(outputs).toHaveTextContent("Ссылка недоступна");
    expect(
      within(outputs).queryByText("https://evil.example/doc-token-storage"),
    ).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("secret transcript body");
    expect(document.body.textContent).not.toContain("credential-token");
    expect(document.body.textContent).not.toContain("storage/private/key");
    expect(document.body.textContent).not.toContain("internal-source-id");

    await userEvent.click(
      within(queuedJobCard as HTMLElement).getByRole("button", {
        name: "Отменить",
      }),
    );
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/jobs/job-1/cancel",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    const cancelCall = (
      fetch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.find(([url]) => url === "/api/jobs/job-1/cancel");
    expect(cancelCall?.[1]?.headers).toMatchObject({
      "x-csrf-token": "csrf-after-refresh",
    });
    expect(
      await screen.findByText(
        "Запрос отмены отправлен. Уже созданные результаты останутся доступны.",
      ),
    ).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("raw-token");
    expect(document.body.textContent).not.toContain("refresh_token");
    expect(document.body.textContent).not.toContain("encrypted_ciphertext");
    expect(document.body.textContent).not.toContain(
      "https://upload.example/leak",
    );
    expect(document.body.textContent).not.toContain("cred-active");
    expect(document.body.textContent).not.toContain("cred-revoked");
    expect(window.localStorage.length).toBe(0);
    expectOnlySafeFormDrafts();
  });

  it("uses Google Picker actions instead of manual Drive ID forms in platform projects", async () => {
    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    expect(
      screen.getByRole("button", { name: "Выбрать файлы Google Drive" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByPlaceholderText("Drive file/folder ID"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByPlaceholderText("Drive folder ID"),
    ).not.toBeInTheDocument();
    expect(window.localStorage.length).toBe(0);
    expectOnlySafeFormDrafts();
  });

  it("Google multiselect seeds one shared target and preserves independent folder overrides", async () => {
    const picker = installFakeGooglePicker();
    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    await userEvent.click(
      screen.getByRole("button", { name: "Выбрать файлы Google Drive" }),
    );
    await picker.loadScript();
    await picker.waitForCallback();
    expect(picker.viewIds).not.toContain("docs");
    expect(googlePicker.openGooglePicker).toHaveBeenCalledWith(
      "sources",
      expect.objectContaining({ scope_ready: true }),
      {
        returnFocusTo: expect.any(HTMLButtonElement),
        sourceMimePolicy: {
          supported_mime_prefixes: ["audio/", "video/"],
          supported_mime_types: ["application/ogg"],
        },
      },
    );
    const sessionCalls = (
      fetch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.filter(([url]) => url === "/api/google/picker/session");
    expect(sessionCalls).toHaveLength(1);
    expect(sessionCalls[0]?.[1]?.headers).toMatchObject({
      "x-csrf-token": "csrf-after-refresh",
    });
    picker.trigger({
      action: "picked",
      docs: [
        {
          id: "file-1",
          name: "leaky-name",
          mimeType: "video/mp4",
          url: "https://drive.example/leaky",
        },
        { id: "file-2", token: "ya29.leaky" },
      ],
    });
    const mutationCall = await waitFor(() => {
      const call = (
        fetch as unknown as ReturnType<typeof vi.fn>
      ).mock.calls.find(
        ([url, init]) =>
          url === "/api/projects/p1/sources/google-picker" &&
          init?.method === "POST",
      );
      expect(call).toBeTruthy();
      return call;
    });
    expect(JSON.parse(String(mutationCall?.[1]?.body))).toEqual({
      file_ids: ["file-1", "file-2"],
    });
    expect(String(mutationCall?.[1]?.body)).not.toContain("leaky-name");
    expect(String(mutationCall?.[1]?.body)).not.toContain("video/mp4");
    expect(String(mutationCall?.[1]?.body)).not.toContain("drive.example");
    expect(String(mutationCall?.[1]?.body)).not.toContain("ya29");
    await waitFor(() =>
      expect(screen.getAllByText("picked-first.mp4").length).toBeGreaterThan(0),
    );
    expect(screen.getAllByText("picked-second.mp4").length).toBeGreaterThan(0);
    expect(document.body.textContent?.indexOf("picked-first.mp4")).toBeLessThan(
      document.body.textContent?.indexOf("picked-second.mp4") ?? 0,
    );
    expect(screen.getByLabelText("Источник задачи 1")).toHaveTextContent(
      "picked-first.mp4",
    );
    expect(screen.getByLabelText("Источник задачи 2")).toHaveTextContent(
      "picked-second.mp4",
    );
    expect(
      screen.getByRole("button", {
        name: "Выбрать папку результата для задачи 1",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Выбрать папку результата для задачи 2",
      }),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", {
        name: "Выбрать папку результата для задачи 1",
      }),
    );
    await picker.waitForCallback();
    picker.trigger({ action: "picked", docs: [{ id: "folder-1" }] });
    await waitFor(() =>
      expect(screen.getAllByText("Default folder")).toHaveLength(2),
    );
    await userEvent.click(
      screen.getByRole("button", {
        name: "Выбрать папку результата для задачи 2",
      }),
    );
    await picker.waitForCallback();
    picker.trigger({ action: "picked", docs: [{ id: "folder-2" }] });
    await waitFor(() =>
      expect(screen.getAllByText("Default folder").length).toBeGreaterThan(1),
    );
    await reviewAndConfirmBatch();
    const batchCall = await waitFor(() => {
      const call = (
        fetch as unknown as ReturnType<typeof vi.fn>
      ).mock.calls.find(
        ([url, init]) =>
          url === "/api/projects/p1/jobs/batch" && init?.method === "POST",
      );
      expect(call).toBeTruthy();
      return call;
    });
    expect(JSON.parse(String(batchCall?.[1]?.body)).items).toMatchObject([
      { source_id: "s-picker-1", output_folder_id: "folder-1" },
      { source_id: "s-picker-2", output_folder_id: "folder-2" },
    ]);
    expect(window.localStorage.length).toBe(0);
    expectOnlySafeFormDrafts();
    expect(document.body.textContent).not.toContain("ya29.test-access-token");
  });

  it("fails Google multiselect closed when the API response cannot cover every picked file", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url.endsWith("/api/projects/p1/sources/google-picker") &&
        init?.method === "POST"
      ) {
        return json({
          sources: [
            {
              id: "s-picker-only",
              project_id: "p1",
              source_type: "google_drive",
              original_filename: "picked-only.mp4",
              mime_type: "video/mp4",
              size_bytes: 10,
              drive_file_url: "https://drive.example/file-only",
              upload_status: "uploaded",
              uploaded_at: "2026-07-01T00:00:00Z",
              expires_at: null,
              deleted_at: null,
              delete_reason: null,
              created_at: "2026-07-01T00:00:00Z",
              updated_at: "2026-07-01T00:00:00Z",
            },
          ],
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    vi.spyOn(googlePicker, "openGooglePicker").mockResolvedValueOnce({
      action: "picked",
      docs: [{ id: "file-1" }, { id: "file-2" }],
    });

    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    await userEvent.click(
      screen.getByRole("button", { name: "Выбрать файлы Google Drive" }),
    );

    expect(
      await screen.findByText(
        "Studio добавила не все выбранные файлы. Список обновлён; проверьте его перед повторным выбором.",
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("listitem").filter((item) =>
      item.classList.contains("composer-row"),
    )).toHaveLength(1);
    expect(screen.getByLabelText("Источник задачи 1")).not.toHaveTextContent(
      "picked-only.mp4",
    );
    await waitFor(() =>
      expect(
        baseFetch.mock.calls.filter(
          ([url, init]) =>
            url === "/api/projects/p1/sources" && !init?.method,
        ),
      ).toHaveLength(2),
    );
  });

  it("renders refreshed authoritative job data for returned batch IDs before existing history", async () => {
    let jobListCalls = 0;
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string, init?: RequestInit) => {
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
          });
        if (url.endsWith("/api/auth/csrf"))
          return json({ csrf_token: "csrf-after-refresh" });
        if (url.endsWith("/api/stt/providers"))
          return json(sttProviderCatalogFixture());
        if (url.endsWith("/api/stt/dictionaries"))
          return json({ dictionaries: [] });
        if (url.endsWith("/api/google/connection"))
          return json({
            connected: true,
            status: "active",
            google_email: "safe.user@example.com",
            scopes: "drive.file",
            connected_at: "2026-07-01T00:00:00Z",
            revoked_at: null,
            picker_configured: true,
            picker_scope_ready: true,
            picker_ready: true,
            reconnect_required: false,
          });
        if (url.endsWith("/api/credentials"))
          return json({
            credentials: [
              {
                id: "cred-active",
                provider: "elevenlabs",
                label: "Primary STT",
                status: "active",
                masked_value: "••••1234",
                active_version: 2,
              },
            ],
          });
        if (url.endsWith("/api/projects"))
          return json({
            projects: [
              {
                id: "p1",
                title: "Research calls",
                description: null,
                created_at: "2026-07-01T00:00:00Z",
                updated_at: "2026-07-01T00:00:00Z",
                archived_at: null,
                output_drive_folder_id: "folder-default",
                output_drive_folder_url:
                  "https://drive.google.com/drive/folders/folder-default",
                output_drive_folder_name: "Default folder",
              },
            ],
          });
        if (url.endsWith("/api/projects/p1/sources") && !init?.method)
          return json({
            sources: [
              {
                id: "s1",
                project_id: "p1",
                source_type: "local_upload",
                original_filename: "ready-local.ogg",
                mime_type: "audio/ogg",
                size_bytes: 10,
                drive_file_id: null,
                drive_file_url: null,
                upload_status: "uploaded",
                uploaded_at: "2026-07-01T00:00:00Z",
                expires_at: null,
                deleted_at: null,
                delete_reason: null,
                created_at: "2026-07-01T00:00:00Z",
                updated_at: "2026-07-01T00:00:00Z",
              },
            ],
          });
        if (url.endsWith("/api/projects/p1/jobs") && !init?.method) {
          jobListCalls += 1;
          return json({
            jobs:
              jobListCalls < 2
                ? [
                    {
                      id: "job-existing",
                      project_id: "p1",
                      status: "failed",
                      title: "Existing history",
                      provider: null,
                      provider_credential_id: "cred-active",
                      source_count: 1,
                      created_at: "2026-07-01T00:00:00Z",
                      updated_at: "2026-07-01T00:01:00Z",
                      cancelled_at: null,
                      cancel_requested_at: null,
                      attempt_count: 0,
                      started_at: null,
                      finished_at: null,
                      error_code: "SAFE",
                      error_message: "Still visible",
                    },
                  ]
                : [
                    {
                      id: "job-created",
                      project_id: "p1",
                      status: "completed",
                      title: "Fresh authoritative",
                      provider: null,
                      provider_credential_id: "cred-active",
                      source_count: 1,
                      output_folder: {
                        name: "Fresh folder",
                        web_view_url:
                          "https://drive.google.com/drive/folders/fresh",
                      },
                      created_at: "2026-07-02T00:00:00Z",
                      updated_at: "2026-07-02T00:05:00Z",
                      cancelled_at: null,
                      cancel_requested_at: null,
                      attempt_count: 1,
                      started_at: "2026-07-02T00:01:00Z",
                      finished_at: "2026-07-02T00:04:00Z",
                      error_code: null,
                      error_message: null,
                    },
                    {
                      id: "job-existing",
                      project_id: "p1",
                      status: "failed",
                      title: "Existing history",
                      provider: null,
                      provider_credential_id: "cred-active",
                      source_count: 1,
                      created_at: "2026-07-01T00:00:00Z",
                      updated_at: "2026-07-01T00:01:00Z",
                      cancelled_at: null,
                      cancel_requested_at: null,
                      attempt_count: 0,
                      started_at: null,
                      finished_at: null,
                      error_code: "SAFE",
                      error_message: "Still visible",
                    },
                  ],
          });
        }
        if (isBatchPreflightRequest(url, init))
          return batchPreflightJson(init);
        if (
          url.endsWith("/api/projects/p1/jobs/batch") &&
          init?.method === "POST"
        )
          return json({
            jobs: [
              {
                id: "job-created",
                project_id: "p1",
                status: "queued",
                title: "Stale create",
                provider: null,
                provider_credential_id: "cred-active",
                source_count: 1,
                output_folder: { name: "Stale folder", web_view_url: null },
                created_at: "2026-07-02T00:00:00Z",
                updated_at: "2026-07-02T00:00:00Z",
                cancelled_at: null,
                cancel_requested_at: null,
                attempt_count: 0,
                started_at: null,
                finished_at: null,
                error_code: null,
                error_message: null,
              },
            ],
            created_count: 1,
            replayed: true,
          });
        if (url.endsWith("/api/jobs/job-created/outputs"))
          return json({
            job_id: "job-created",
            job_status: "completed",
            output_count: 0,
            outputs: [],
          });
        return json({ ok: true });
      },
    );
    renderApp();
    await openSelectedProjectJobs();
    await chooseExistingSource(1, "ready-local.ogg");
    await chooseResultFolder(1);
    await reviewAndConfirmBatch();
    expect(await screen.findByText("Fresh authoritative")).toBeInTheDocument();
    expect(screen.getByText("Статус: Завершена")).toBeInTheDocument();
    expect(
      screen.getByText("Папка результата: Fresh folder"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Stale create")).not.toBeInTheDocument();
    expect(screen.getByText("Existing history")).toBeInTheDocument();
    expect(
      document.body.textContent?.indexOf("Fresh authoritative"),
    ).toBeLessThan(document.body.textContent?.indexOf("Existing history") ?? 0);
  });

  it("moves saved-file management out of transcriptions and into Settings", async () => {
    renderApp();
    await openSelectedProjectJobs();

    expect(screen.queryByText("Файлы проекта")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Убрать из Studio:/ }),
    ).not.toBeInTheDocument();

    await openSettingsSection("Файлы и хранилище");
    expect(
      await screen.findByRole("heading", { name: "Сохранённые файлы Studio" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Убрать из Studio: local-temp.ogg" }),
    ).toBeInTheDocument();
  });
  it("row folder verification retries only CSRF rejections and never ordinary failures", async () => {
    const scenarios: Array<{
      name: string;
      response: "422" | "500" | "502" | "network";
    }> = [
      { name: "422", response: "422" },
      { name: "500", response: "500" },
      { name: "502", response: "502" },
      { name: "network", response: "network" },
    ];
    for (const scenario of scenarios) {
      cleanup();
    sessionStorage.clear();
      googlePicker.resetGooglePickerLoaderForTests();
      vi.restoreAllMocks();
      let verifyCalls = 0;
      vi.spyOn(googlePicker, "openGooglePicker").mockResolvedValue({
        action: "picked",
        docs: [{ id: `folder-${scenario.name}` }],
      } as Awaited<ReturnType<typeof googlePicker.openGooglePicker>>);
      (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
        (url: string, init?: RequestInit) => {
          if (url.endsWith("/api/auth/session"))
            return json({
              authenticated: true,
              user: { email: "user@example.com", role: "admin" },
            });
          if (url.endsWith("/api/auth/csrf"))
            return json({ csrf_token: "csrf-after-refresh" });
          if (url.endsWith("/api/google/connection"))
            return json({
              connected: true,
              status: "active",
              google_email: "safe.user@example.com",
              scopes: "drive.file",
              connected_at: "2026-07-01T00:00:00Z",
              revoked_at: null,
              picker_configured: true,
              picker_scope_ready: true,
              picker_ready: true,
              reconnect_required: false,
            });
          if (url.endsWith("/api/google/picker/session"))
            return json({
              access_token: "picker-token",
              api_key: "public",
              app_id: "app",
              scope_ready: true,
            });
          if (url.endsWith("/api/credentials"))
            return json({ credentials: [] });
          if (url.endsWith("/api/projects"))
            return json({
              projects: [
                {
                  id: "p1",
                  title: "Research calls",
                  description: null,
                  created_at: "2026-07-01T00:00:00Z",
                  updated_at: "2026-07-01T00:00:00Z",
                  archived_at: null,
                  output_drive_folder_id: null,
                  output_drive_folder_url: null,
                  output_drive_folder_name: null,
                },
              ],
            });
          if (url.endsWith("/api/projects/p1/jobs") && !init?.method)
            return json({ jobs: [] });
          if (url.endsWith("/api/projects/p1/sources") && !init?.method)
            return json({
              sources: [
                {
                  id: "s1",
                  project_id: "p1",
                  source_type: "local_upload",
                  original_filename: "ready-local.ogg",
                  mime_type: "audio/ogg",
                  size_bytes: 10,
                  drive_file_id: null,
                  drive_file_url: null,
                  upload_status: "uploaded",
                  uploaded_at: "2026-07-01T00:00:00Z",
                  expires_at: null,
                  deleted_at: null,
                  delete_reason: null,
                  created_at: "2026-07-01T00:00:00Z",
                  updated_at: "2026-07-01T00:00:00Z",
                },
              ],
            });
          if (
            url.endsWith(
              "/api/projects/p1/output-folders/google-picker/verify",
            ) &&
            init?.method === "POST"
          ) {
            verifyCalls += 1;
            if (scenario.response === "network")
              return Promise.reject(new Error("network down"));
            return json(
              { detail: "safe failure" },
              false,
              Number(scenario.response),
            );
          }
          return json({ ok: true });
        },
      );
      renderApp();
      await openSelectedProjectJobs();
      await userEvent.click(
        await screen.findByRole("button", { name: "Добавить задачу" }),
      );
      await userEvent.click(
        screen.getByRole("button", {
          name: "Выбрать папку результата для задачи 1",
        }),
      );
      await waitFor(() => expect(verifyCalls).toBe(1));
      expect(screen.getAllByText("Папка не выбрана")[0]).toBeInTheDocument();
    }

    cleanup();
    sessionStorage.clear();
    googlePicker.resetGooglePickerLoaderForTests();
    vi.restoreAllMocks();
    let verifyCalls = 0;
    const verifyBodies: string[] = [];
    vi.spyOn(googlePicker, "openGooglePicker").mockResolvedValue({
      action: "picked",
      docs: [{ id: "folder-csrf" }],
    } as Awaited<ReturnType<typeof googlePicker.openGooglePicker>>);
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string, init?: RequestInit) => {
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
          });
        if (url.endsWith("/api/auth/csrf"))
          return json({
            csrf_token: verifyCalls > 0 ? "csrf-refreshed" : "csrf-initial",
          });
        if (url.endsWith("/api/google/connection"))
          return json({
            connected: true,
            status: "active",
            google_email: "safe.user@example.com",
            scopes: "drive.file",
            connected_at: "2026-07-01T00:00:00Z",
            revoked_at: null,
            picker_configured: true,
            picker_scope_ready: true,
            picker_ready: true,
            reconnect_required: false,
          });
        if (url.endsWith("/api/google/picker/session"))
          return json({
            access_token: "picker-token",
            api_key: "public",
            app_id: "app",
            scope_ready: true,
          });
        if (url.endsWith("/api/credentials"))
          return json({
            credentials: [
              {
                id: "cred-active",
                provider: "elevenlabs",
                label: "Primary STT",
                status: "active",
                masked_value: "••••1234",
                active_version: 2,
              },
            ],
          });
        if (url.endsWith("/api/projects"))
          return json({
            projects: [
              {
                id: "p1",
                title: "Research calls",
                description: null,
                created_at: "2026-07-01T00:00:00Z",
                updated_at: "2026-07-01T00:00:00Z",
                archived_at: null,
                output_drive_folder_id: null,
                output_drive_folder_url: null,
                output_drive_folder_name: null,
              },
            ],
          });
        if (url.endsWith("/api/projects/p1/jobs") && !init?.method)
          return json({ jobs: [] });
        if (url.endsWith("/api/projects/p1/sources") && !init?.method)
          return json({
            sources: [
              {
                id: "s1",
                project_id: "p1",
                source_type: "local_upload",
                original_filename: "ready-local.ogg",
                mime_type: "audio/ogg",
                size_bytes: 10,
                drive_file_id: null,
                drive_file_url: null,
                upload_status: "uploaded",
                uploaded_at: "2026-07-01T00:00:00Z",
                expires_at: null,
                deleted_at: null,
                delete_reason: null,
                created_at: "2026-07-01T00:00:00Z",
                updated_at: "2026-07-01T00:00:00Z",
              },
            ],
          });
        if (
          url.endsWith(
            "/api/projects/p1/output-folders/google-picker/verify",
          ) &&
          init?.method === "POST"
        ) {
          verifyCalls += 1;
          verifyBodies.push(String(init.body));
          return verifyCalls === 1
            ? json({ detail: { reason: "csrf_token_invalid" } }, false, 403)
            : json({
                name: "Verified folder",
                web_view_url:
                  "https://drive.google.com/drive/folders/folder-csrf",
              });
        }
        return json({ ok: true });
      },
    );
    renderApp();
    await openSelectedProjectJobs();
    await userEvent.click(
      await screen.findByRole("button", { name: "Добавить задачу" }),
    );
    await userEvent.click(
      screen.getByRole("button", {
        name: "Выбрать папку результата для задачи 1",
      }),
    );
    expect(await screen.findAllByText("Verified folder")).toHaveLength(2);
    expect(verifyCalls).toBe(2);
    expect(verifyBodies).toEqual([
      JSON.stringify({ folder_id: "folder-csrf" }),
      JSON.stringify({ folder_id: "folder-csrf" }),
    ]);
  });

  it("preserves the preparation composer draft across project tab switches", async () => {
    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });

    await chooseExistingSource(1, "Лекция 1");
    await chooseResultFolder(1, "folder-one");
    await userEvent.type(
      screen.getByLabelText("Название документа задачи 1"),
      "First draft title",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Добавить задачу" }),
    );
    await chooseExistingSource(2, "local-temp.ogg");
    await chooseResultFolder(2, "folder-two");
    await userEvent.type(
      screen.getByLabelText("Название документа задачи 2"),
      "Second draft title",
    );

    await openPlatformNavPage("Обзор");
    await openPlatformNavPage("Транскрибации");
    await screen.findByRole("form", { name: "Композитор пакетных задач" });

    const rows = screen
      .getAllByRole("listitem")
      .filter((item) => item.classList.contains("composer-row"));
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent(
      "Лекция 1. Личность как психологическое явление.flac",
    );
    expect(rows[0]).toHaveTextContent("Default folder");
    expect(
      within(rows[0]).getByLabelText("Название документа задачи 1"),
    ).toHaveValue("First draft title");
    expect(rows[1]).toHaveTextContent("local-temp.ogg");
    expect(rows[1]).toHaveTextContent("Default folder");
    expect(
      within(rows[1]).getByLabelText("Название документа задачи 2"),
    ).toHaveValue("Second draft title");
    expect(window.localStorage.length).toBe(0);
    expectOnlySafeFormDrafts();
  });

  it("isolates composer state and preserves ambiguous batch recovery across project switches", async () => {
    let projectACreateCalls = 0;
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string, init?: RequestInit) => {
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
          });
        if (url.endsWith("/api/auth/csrf"))
          return json({ csrf_token: "csrf-after-refresh" });
        if (url.endsWith("/api/stt/providers"))
          return json(sttProviderCatalogFixture());
        if (url.endsWith("/api/stt/dictionaries"))
          return json({ dictionaries: [] });
        if (url.endsWith("/api/google/connection"))
          return json({
            connected: true,
            status: "active",
            google_email: "safe.user@example.com",
            scopes: "drive.file",
            connected_at: "2026-07-01T00:00:00Z",
            revoked_at: null,
            picker_configured: true,
            picker_scope_ready: true,
            picker_ready: true,
            reconnect_required: false,
          });
        if (url.endsWith("/api/credentials"))
          return json({
            credentials: [
              {
                id: "cred-active",
                provider: "elevenlabs",
                label: "Primary STT",
                status: "active",
                masked_value: "••••1234",
                active_version: 2,
              },
            ],
          });
        if (url.endsWith("/api/projects"))
          return json({
            projects: [
              {
                id: "pA",
                title: "Project A",
                description: null,
                created_at: "2026-07-01T00:00:00Z",
                updated_at: "2026-07-01T00:00:00Z",
                archived_at: null,
                output_drive_folder_id: "folder-a",
                output_drive_folder_url:
                  "https://drive.google.com/drive/folders/folder-a",
                output_drive_folder_name: "A default",
              },
              {
                id: "pB",
                title: "Project B",
                description: null,
                created_at: "2026-07-02T00:00:00Z",
                updated_at: "2026-07-02T00:00:00Z",
                archived_at: null,
                output_drive_folder_id: "folder-b",
                output_drive_folder_url:
                  "https://drive.google.com/drive/folders/folder-b",
                output_drive_folder_name: "B default",
              },
            ],
          });
        if (url.endsWith("/api/projects/pA/sources") && !init?.method)
          return json({
            sources: [
              {
                id: "source-a",
                project_id: "pA",
                source_type: "local_upload",
                original_filename: "project-a-source.ogg",
                mime_type: "audio/ogg",
                size_bytes: 10,
                drive_file_id: null,
                drive_file_url: null,
                upload_status: "uploaded",
                uploaded_at: "2026-07-01T00:00:00Z",
                expires_at: null,
                deleted_at: null,
                delete_reason: null,
                created_at: "2026-07-01T00:00:00Z",
                updated_at: "2026-07-01T00:00:00Z",
              },
            ],
          });
        if (url.endsWith("/api/projects/pB/sources") && !init?.method)
          return json({
            sources: [
              {
                id: "source-b",
                project_id: "pB",
                source_type: "local_upload",
                original_filename: "project-b-source.ogg",
                mime_type: "audio/ogg",
                size_bytes: 20,
                drive_file_id: null,
                drive_file_url: null,
                upload_status: "uploaded",
                uploaded_at: "2026-07-02T00:00:00Z",
                expires_at: null,
                deleted_at: null,
                delete_reason: null,
                created_at: "2026-07-02T00:00:00Z",
                updated_at: "2026-07-02T00:00:00Z",
              },
            ],
          });
        if (url.endsWith("/api/projects/pA/jobs") && !init?.method)
          return json({
            jobs: [
              {
                id: "job-a",
                project_id: "pA",
                status: "completed",
                title: "A completed job",
                provider: null,
                provider_credential_id: "cred-active",
                source_count: 1,
                output_folder: {
                  name: "A result folder",
                  web_view_url:
                    "https://drive.google.com/drive/folders/a-result",
                },
                created_at: "2026-07-01T01:00:00Z",
                updated_at: "2026-07-01T01:05:00Z",
                cancelled_at: null,
                cancel_requested_at: null,
                attempt_count: 1,
                started_at: "2026-07-01T01:01:00Z",
                finished_at: "2026-07-01T01:04:00Z",
                error_code: null,
                error_message: null,
              },
            ],
          });
        if (url.endsWith("/api/projects/pB/jobs") && !init?.method)
          return json({ jobs: [] });
        if (url.endsWith("/api/jobs/job-a"))
          return json({
            id: "job-a",
            project_id: "pA",
            status: "completed",
            title: "A completed job",
            provider: null,
            provider_credential_id: "cred-active",
            source_count: 1,
            created_at: "2026-07-01T01:00:00Z",
            updated_at: "2026-07-01T01:05:00Z",
            cancelled_at: null,
            cancel_requested_at: null,
            attempt_count: 1,
            started_at: "2026-07-01T01:01:00Z",
            finished_at: "2026-07-01T01:04:00Z",
            error_code: null,
            error_message: null,
            sources: [
              {
                id: "source-a",
                project_id: "pA",
                position: 0,
                job_source_status: "queued",
                source_type: "local_upload",
                original_filename: "project-a-source.ogg",
                mime_type: "audio/ogg",
                size_bytes: 10,
                drive_file_id: null,
                drive_file_url: null,
                upload_status: "uploaded",
                uploaded_at: "2026-07-01T00:00:00Z",
                expires_at: null,
                deleted_at: null,
                delete_reason: null,
                created_at: "2026-07-01T00:00:00Z",
                updated_at: "2026-07-01T00:00:00Z",
              },
            ],
          });
        if (url.endsWith("/api/jobs/job-a/outputs"))
          return json({
            job_id: "job-a",
            job_status: "completed",
            output_count: 1,
            outputs: [
              {
                source_id: "source-a",
                source_position: 0,
                source_name: "project-a-output",
                source_type: "local_upload",
                output_kind: "transcript",
                transcript_standard: "plain",
                web_view_url: null,
                link_available: false,
                document_character_count: 10,
                document_created_at: "2026-07-01T01:03:00Z",
                persisted_at: "2026-07-01T01:04:00Z",
              },
            ],
          });
        if (isBatchPreflightRequest(url, init))
          return batchPreflightJson(init);
        if (
          url.endsWith("/api/projects/pA/jobs/batch") &&
          init?.method === "POST"
        ) {
          projectACreateCalls += 1;
          if (projectACreateCalls === 1) {
            return Promise.reject(new Error("temporary batch outage"));
          }
          return json({
            jobs: [],
            created_count: 1,
            replayed: true,
          });
        }
        if (
          url.endsWith("/api/projects/pB/jobs/batch") &&
          init?.method === "POST"
        )
          return json({
            jobs: [
              {
                id: "job-b-created",
                project_id: "pB",
                status: "queued",
                title: "B clean submit",
                provider: null,
                provider_credential_id: "cred-active",
                source_count: 1,
                created_at: "2026-07-02T01:00:00Z",
                updated_at: "2026-07-02T01:00:00Z",
                cancelled_at: null,
                cancel_requested_at: null,
                attempt_count: 0,
                started_at: null,
                finished_at: null,
                error_code: null,
                error_message: null,
              },
            ],
            created_count: 1,
            replayed: false,
          });
        return json({ ok: true });
      },
    );

    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    await chooseExistingSource(1, "project-a-source.ogg");
    await chooseResultFolder(1, "folder-a");
    await userEvent.type(
      screen.getByLabelText("Название документа задачи 1"),
      "Project A row title",
    );
    await userEvent.click(
      within(
        screen.getByText("A completed job").closest("article") as HTMLElement,
      ).getByRole("button", { name: /^(Открыть|Показать результаты и детали)$/ }),
    );
    expect(
      await screen.findByLabelText("Подробности транскрибации"),
    ).toBeInTheDocument();
    expect(await screen.findByLabelText("Результаты транскрибации")).toHaveTextContent(
      "project-a-output",
    );
    await reviewAndConfirmBatch();
    expect(
      await screen.findByLabelText("Неопределённый исход создания пакета"),
    ).toHaveTextContent("Новая отправка заблокирована");

    await userEvent.click(
      screen.getByRole("button", { name: /Project B .*02\.07\.2026/ }),
    );
    await screen.findByRole("form", { name: "Композитор пакетных задач" });

    expect(
      screen.queryByDisplayValue("Project A row title"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("A default")).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Неопределённый исход создания пакета"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("A completed job")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Подробности транскрибации")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Результаты транскрибации")).not.toBeInTheDocument();
    expect(screen.queryByText("project-a-output")).not.toBeInTheDocument();
    expect(screen.getAllByText("Папка не выбрана").length).toBeGreaterThan(0);
    await chooseExistingSource(1, "project-b-source.ogg");
    await chooseResultFolder(1, "folder-b");
    await userEvent.type(
      screen.getByLabelText("Название документа задачи 1"),
      "B clean submit",
    );
    await reviewAndConfirmBatch();
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/projects/pB/jobs/batch",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    const bCreateCall = (
      fetch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.find(
      ([url, init]) =>
        url === "/api/projects/pB/jobs/batch" && init?.method === "POST",
    );
    expect(JSON.parse(String(bCreateCall?.[1]?.body))).toEqual({
      provider: "elevenlabs",
      operating_mode: "standard",
      provider_credential_id: "cred-active",
      language: "ru",
      options: { diarize: false },
      items: [
        {
          source_id: "source-b",
          output_folder_id: "folder-b",
          title: "B clean submit",
          reprocess_existing: false,
        },
      ],
    });
    const firstACreateCall = (
      fetch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.find(
      ([url, init]) =>
        url === "/api/projects/pA/jobs/batch" && init?.method === "POST",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Project A .*01\.07\.2026/ }),
    );
    expect(
      await screen.findByLabelText("Неопределённый исход создания пакета"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Проверить задачи (1)" }),
    ).toBeDisabled();

    await userEvent.click(
      screen.getByRole("button", {
        name: "Повторить подтверждение пакета",
      }),
    );
    expect(
      await screen.findByText(
        "Повторный запрос подтверждён: транскрибация уже создана.",
      ),
    ).toBeInTheDocument();
    const aCreateCalls = (
      fetch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.filter(
      ([url, init]) =>
        url === "/api/projects/pA/jobs/batch" && init?.method === "POST",
    );
    expect(aCreateCalls).toHaveLength(2);
    expect(aCreateCalls[1]?.[1]?.headers).toMatchObject({
      "Idempotency-Key": (
        firstACreateCall?.[1]?.headers as Record<string, string>
      )["Idempotency-Key"],
    });
    expect(aCreateCalls[1]?.[1]?.body).toBe(firstACreateCall?.[1]?.body);
    expect(window.localStorage.length).toBe(0);
    expectOnlySafeFormDrafts();
  });

  it("source Picker cancel/error and duplicate clicks do not create source mutations", async () => {
    let picker = installFakeGooglePicker();
    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    const button = screen.getByRole("button", {
      name: "Выбрать файлы Google Drive",
    });
    fireEvent.click(button);
    fireEvent.click(button);
    await picker.loadScript();
    await picker.waitForCallback();
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.filter(
        ([url]) => url === "/api/google/picker/session",
      ),
    ).toHaveLength(1);
    picker.trigger({ action: "cancel" });
    await screen.findByText("Выбор файлов отменён.");
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(
        ([url]) => url === "/api/projects/p1/sources/google-picker",
      ),
    ).toBe(false);

    cleanup();
    vi.clearAllMocks();
    picker = installFakeGooglePicker();
    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    await userEvent.click(
      screen.getByRole("button", { name: "Выбрать файлы Google Drive" }),
    );
    await picker.loadScript();
    await picker.waitForCallback();
    picker.trigger({ action: "error", raw: "raw-google-payload" });
    expect(
      await screen.findByText(
        "Не удалось загрузить Google Drive. Переподключите Drive или повторите попытку.",
      ),
    ).toBeInTheDocument();
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(
        ([url]) => url === "/api/projects/p1/sources/google-picker",
      ),
    ).toBe(false);
    expect(document.body.textContent).not.toContain("raw-google-payload");
  });

  it("bounds stalled Google Picker sessions without replay and releases the source action", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const sessionSignals: AbortSignal[] = [];
    let sessionCalls = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url.endsWith("/api/google/picker/session") &&
        init?.method === "POST"
      ) {
        sessionCalls += 1;
        const signal = init.signal;
        if (!signal) throw new Error("Picker session signal is missing");
        sessionSignals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 20_000 ? 1 : (delay as number),
          ...args,
        )) as typeof setTimeout);

    try {
      renderApp();
      await openProjectsPage();
      const button = await screen.findByRole("button", {
        name: "Выбрать файлы Google Drive",
      });
      await userEvent.click(button);

      expect(
        await screen.findByText(
          "Google Picker не ответил вовремя. Повторите попытку.",
        ),
      ).toBeInTheDocument();
      expect(sessionCalls).toBe(1);
      expect(sessionSignals).toHaveLength(1);
      expect(sessionSignals[0]?.aborted).toBe(true);
      expect(button).toBeEnabled();
      expect(
        document.head.querySelector(
          'script[data-studio-google-picker="true"]',
        ),
      ).toBeNull();
      expect(
        baseFetch.mock.calls.some(
          ([url]) => url === "/api/projects/p1/sources/google-picker",
        ),
      ).toBe(false);

      await userEvent.click(button);
      await waitFor(() => expect(sessionCalls).toBe(2));
      await waitFor(() => expect(sessionSignals[1]?.aborted).toBe(true));
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("fails closed on a malformed Google Picker session without exposing its payload", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url.endsWith("/api/google/picker/session") &&
        init?.method === "POST"
      ) {
        return json({
          access_token: "raw-private-google-token",
          api_key: " ",
          app_id: "app",
          scope_ready: true,
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();
    const button = await screen.findByRole("button", {
      name: "Выбрать файлы Google Drive",
    });
    await userEvent.click(button);

    expect(
      await screen.findByText(
        "Studio не смогла открыть Google Drive. Повторите попытку позже.",
      ),
    ).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(
      "raw-private-google-token",
    );
    expect(button).toBeEnabled();
    expect(
      document.head.querySelector(
        'script[data-studio-google-picker="true"]',
      ),
    ).toBeNull();
    expect(
      baseFetch.mock.calls.some(
        ([url]) => url === "/api/projects/p1/sources/google-picker",
      ),
    ).toBe(false);
  });

  it("closes an unresponsive app-owned Drive picker and ignores a late selection", async () => {
    const picker = installFakeGooglePicker();
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 300_000 ? 1 : (delay as number),
          ...args,
        )) as typeof setTimeout);

    try {
      renderApp();
      await openProjectsPage();
      const button = await screen.findByRole("button", {
        name: "Выбрать файлы Google Drive",
      });
      await userEvent.click(button);
      await picker.loadScript();
      await picker.waitForCallback();

      expect(
        await screen.findByText(
          "Время выбора в Google Drive истекло. Повторите попытку.",
        ),
      ).toBeInTheDocument();
      expect(picker.setVisible).not.toHaveBeenCalled();
      expect(document.body.style.overflow).toBe("");
      expect(button).toBeEnabled();

      picker.trigger({ action: "picked", docs: [{ id: "late-file" }] });
      await act(async () => {
        await Promise.resolve();
      });
      expect(
        (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(
          ([url]) => url === "/api/projects/p1/sources/google-picker",
        ),
      ).toBe(false);
    } finally {
      timeoutSpy.mockRestore();
    }
  });
  it("bounds ambiguous Google source creation without replay and refreshes sources", async () => {
    const picker = installFakeGooglePicker();
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const mutationSignals: AbortSignal[] = [];
    let mutationCalls = 0;
    let sourceReadsAfterMutation = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url === "/api/projects/p1/sources" &&
        !init?.method &&
        mutationCalls > 0
      ) {
        sourceReadsAfterMutation += 1;
      }
      if (
        url === "/api/projects/p1/sources/google-picker" &&
        init?.method === "POST"
      ) {
        mutationCalls += 1;
        const signal = init.signal;
        if (!signal) throw new Error("Google source signal is missing");
        mutationSignals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 20_000 ? 1 : (delay as number),
          ...args,
        )) as typeof setTimeout);

    try {
      renderApp();
      await openProjectsPage();
      const button = await screen.findByRole("button", {
        name: "Выбрать файлы Google Drive",
      });
      await userEvent.click(button);
      await picker.loadScript();
      await picker.waitForCallback();
      picker.trigger({ action: "picked", docs: [{ id: "file-timeout" }] });

      expect(
        await screen.findByText(
          "Studio не подтвердила добавление файлов Google Drive. Список файлов обновлён; проверьте его перед повторным выбором.",
        ),
      ).toBeInTheDocument();
      expect(mutationCalls).toBe(1);
      expect(mutationSignals).toHaveLength(1);
      expect(mutationSignals[0]?.aborted).toBe(true);
      await waitFor(() => expect(sourceReadsAfterMutation).toBeGreaterThan(0));
      expect(button).toBeEnabled();
      expect(
        screen.getByLabelText("Источник задачи 1"),
      ).not.toHaveTextContent("file-timeout");
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("treats a Google source 5xx as ambiguous without exposing or replaying it", async () => {
    const picker = installFakeGooglePicker();
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let mutationCalls = 0;
    let sourceReadsAfterMutation = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url === "/api/projects/p1/sources" &&
        !init?.method &&
        mutationCalls > 0
      ) {
        sourceReadsAfterMutation += 1;
      }
      if (
        url === "/api/projects/p1/sources/google-picker" &&
        init?.method === "POST"
      ) {
        mutationCalls += 1;
        return json(
          { detail: "raw-private-google-source-failure" },
          false,
          503,
        );
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();
    const button = await screen.findByRole("button", {
      name: "Выбрать файлы Google Drive",
    });
    await userEvent.click(button);
    await picker.loadScript();
    await picker.waitForCallback();
    picker.trigger({ action: "picked", docs: [{ id: "file-503" }] });

    expect(
      await screen.findByText(
        "Studio не подтвердила добавление файлов Google Drive. Список файлов обновлён; проверьте его перед повторным выбором.",
      ),
    ).toBeInTheDocument();
    expect(mutationCalls).toBe(1);
    await waitFor(() => expect(sourceReadsAfterMutation).toBeGreaterThan(0));
    expect(button).toBeEnabled();
    expect(document.body.textContent).not.toContain(
      "raw-private-google-source-failure",
    );
  });

  it("bounds stalled Google folder verification and releases all Picker actions", async () => {
    vi.spyOn(googlePicker, "openGooglePicker").mockResolvedValueOnce({
      action: "picked",
      docs: [{ id: "folder-timeout" }],
    } as Awaited<ReturnType<typeof googlePicker.openGooglePicker>>);
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const verifySignals: AbortSignal[] = [];
    let verifyCalls = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url === "/api/projects/p1/output-folders/google-picker/verify" &&
        init?.method === "POST"
      ) {
        verifyCalls += 1;
        const signal = init.signal;
        if (!signal) throw new Error("Folder verify signal is missing");
        verifySignals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 20_000 ? 1 : (delay as number),
          ...args,
        )) as typeof setTimeout);

    try {
      renderApp();
      await openProjectsPage();
      const folderButton = await screen.findByRole("button", {
        name: "Выбрать папку результата для задачи 1",
      });
      await userEvent.click(folderButton);

      expect(
        await screen.findByText(
          "Проверка папки результата заняла слишком много времени. Повторите выбор.",
        ),
      ).toBeInTheDocument();
      expect(verifyCalls).toBe(1);
      expect(verifySignals).toHaveLength(1);
      expect(verifySignals[0]?.aborted).toBe(true);
      expect(folderButton).toBeEnabled();
      expect(folderButton).toHaveTextContent("Выбрать");
      expect(
        screen.getByRole("button", { name: "Выбрать файлы Google Drive" }),
      ).toBeEnabled();
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("rejects malformed Google folder verification without using its values", async () => {
    vi.spyOn(googlePicker, "openGooglePicker").mockResolvedValueOnce({
      action: "picked",
      docs: [{ id: "folder-malformed" }],
    } as Awaited<ReturnType<typeof googlePicker.openGooglePicker>>);
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url === "/api/projects/p1/output-folders/google-picker/verify" &&
        init?.method === "POST"
      ) {
        return json({
          name: " ",
          web_view_url: "https://drive.example/raw-private-folder",
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();
    const folderButton = await screen.findByRole("button", {
      name: "Выбрать папку результата для задачи 1",
    });
    await userEvent.click(folderButton);

    expect(
      await screen.findByText(
        "Studio не смогла подтвердить папку результата. Повторите выбор позже.",
      ),
    ).toBeInTheDocument();
    expect(folderButton).toBeEnabled();
    expect(folderButton).toHaveTextContent("Выбрать");
    expect(document.body.textContent).not.toContain("raw-private-folder");
  });

  it("keeps Google Picker ownership and safe outcomes across project switches", async () => {
    const picker = installFakeGooglePicker();
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const sourceResolvers: Array<(response: Response) => void> = [];
    const folderResolvers: Array<(response: Response) => void> = [];
    let sourceMutationCalls = 0;
    let folderVerificationCalls = 0;
    let sourceReadsAfterMutation = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/projects" && !init?.method) {
        return json({
          projects: [
            {
              id: "p1",
              title: "Research calls",
              description: "Customer interview notes",
              created_at: "2026-07-01T00:00:00",
              updated_at: "2026-07-01T00:00:00",
              archived_at: null,
              output_drive_folder_id: null,
              output_drive_folder_url: null,
              output_drive_folder_name: null,
            },
            {
              id: "p2",
              title: "Project Two",
              description: null,
              created_at: "2026-07-02T00:00:00",
              updated_at: "2026-07-02T00:00:00",
              archived_at: null,
              output_drive_folder_id: null,
              output_drive_folder_url: null,
              output_drive_folder_name: null,
            },
          ],
        });
      }
      if (url === "/api/projects/p2/sources" && !init?.method)
        return json({ sources: [] });
      if (url === "/api/projects/p2/jobs" && !init?.method)
        return json({ jobs: [] });
      if (
        url === "/api/projects/p1/sources" &&
        !init?.method &&
        sourceMutationCalls > 0
      ) {
        sourceReadsAfterMutation += 1;
      }
      if (
        url === "/api/projects/p1/sources/google-picker" &&
        init?.method === "POST"
      ) {
        sourceMutationCalls += 1;
        return new Promise<Response>((resolve) => {
          sourceResolvers.push(resolve);
        });
      }
      if (
        url === "/api/projects/p1/output-folders/google-picker/verify" &&
        init?.method === "POST"
      ) {
        folderVerificationCalls += 1;
        return new Promise<Response>((resolve) => {
          folderResolvers.push(resolve);
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();
    const sourceButton = await screen.findByRole("button", {
      name: "Выбрать файлы Google Drive",
    });
    await userEvent.click(sourceButton);
    await picker.loadScript();
    await picker.waitForCallback();
    picker.trigger({ action: "picked", docs: [{ id: "file-remount" }] });
    await waitFor(() => expect(sourceMutationCalls).toBe(1));

    await userEvent.click(
      screen.getByRole("button", { name: /Project Two/ }),
    );
    expect(
      await screen.findByText(
        "Google Picker занят операцией в другом проекте. Дождитесь её завершения.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Выбрать файлы Google Drive" }),
    ).toBeDisabled();
    expect(
      screen.queryByText(/Файлы Google Drive добавлены в проект/),
    ).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /Research calls/ }),
    );
    expect(
      await screen.findByText(
        "Выбор в Google Drive для этого проекта ещё выполняется. Дождитесь завершения перед новой попыткой.",
      ),
    ).toBeInTheDocument();
    const restoredSourceButton = screen.getByRole("button", {
      name: "Выбрать файлы Google Drive",
    });
    expect(restoredSourceButton).toBeDisabled();
    restoredSourceButton.click();
    expect(sourceMutationCalls).toBe(1);

    await userEvent.click(
      screen.getByRole("button", { name: /Project Two/ }),
    );
    await act(async () => {
      sourceResolvers[0]?.(
        await json({
          sources: [
            {
              id: "source-remount",
              project_id: "p1",
              source_type: "google_drive",
              original_filename: "remount-source.mp4",
              mime_type: "video/mp4",
              size_bytes: 10,
              drive_file_url: "https://drive.example/file-remount",
              upload_status: "uploaded",
              uploaded_at: "2026-07-01T00:00:00Z",
              expires_at: null,
              deleted_at: null,
              delete_reason: null,
              created_at: "2026-07-01T00:00:00Z",
              updated_at: "2026-07-01T00:00:00Z",
            },
          ],
        }),
      );
    });
    await waitFor(() => expect(sourceReadsAfterMutation).toBeGreaterThan(0));
    expect(
      screen.queryByText(
        "Файлы Google Drive добавлены в Studio. Выберите их в нужных задачах заново.",
      ),
    ).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /Research calls/ }),
    );
    expect(
      await screen.findByText(
        "Файлы Google Drive добавлены в Studio. Выберите их в нужных задачах заново.",
      ),
    ).toBeInTheDocument();
    const folderButton = screen.getByRole("button", {
      name: "Выбрать папку результата для задачи 1",
    });
    await userEvent.click(folderButton);
    await waitFor(() => expect(picker.outputFolderOpenCount).toBe(1));
    expect(
      picker.builderCalls.filter((call) => call.method === "setCallback"),
    ).toHaveLength(0);
    expect(
      screen.queryByText(
        "Файлы Google Drive добавлены в Studio. Выберите их в нужных задачах заново.",
      ),
    ).not.toBeInTheDocument();
    picker.trigger({ action: "picked", docs: [{ id: "folder-remount" }] });
    await waitFor(() => expect(folderVerificationCalls).toBe(1));

    await userEvent.click(
      screen.getByRole("button", { name: /Project Two/ }),
    );
    expect(
      await screen.findByText(
        "Google Picker занят операцией в другом проекте. Дождитесь её завершения.",
      ),
    ).toBeInTheDocument();
    await act(async () => {
      folderResolvers[0]?.(
        await json({
          name: "Verified remount folder",
          web_view_url: "https://drive.example/folder-remount",
        }),
      );
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Выбрать файлы Google Drive" }),
      ).toBeEnabled(),
    );
    expect(
      screen.queryByText(/Папка Google Drive проверена/),
    ).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /Research calls/ }),
    );
    expect(
      await screen.findByText(
        "Папка Google Drive проверена, но прежняя задача больше не открыта. Выберите папку для задачи повторно.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Выбрать папку результата для задачи 1",
      }),
    ).toBeEnabled();
    expect(sourceMutationCalls).toBe(1);
    expect(folderVerificationCalls).toBe(1);
  });
  it("shows an actionable safe message when Picker session requires reconnect", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url.endsWith("/api/google/picker/session") &&
        init?.method === "POST"
      )
        return json(
          {
            detail: "google_reauthorization_required",
            raw: "private-google-response",
          },
          false,
          409,
        );
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();
    await userEvent.click(
      await screen.findByRole("button", {
        name: "Выбрать файлы Google Drive",
      }),
    );

    expect(
      await screen.findByText(
        "Переподключите Google Drive в настройках и повторите выбор.",
      ),
    ).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("private-google-response");
  });

  it("disables row folder selection while Google Drive is disconnected without requesting Picker session", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/google/connection"))
        return json({
          connected: false,
          status: "missing",
          google_email: null,
          scopes: "",
          connected_at: null,
          revoked_at: null,
          picker_configured: false,
          picker_scope_ready: false,
          picker_ready: false,
          reconnect_required: false,
        });
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();
    const button = await screen.findByRole("button", {
      name: "Выбрать папку результата для задачи 1",
    });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(
        ([url]) => url === "/api/google/picker/session",
      ),
    ).toBe(false);
  });

  it("keeps row folder selection unavailable for reconnect or Picker readiness problems", async () => {
    const scenarios = [
      {
        reconnect_required: true,
        picker_scope_ready: true,
        picker_configured: true,
      },
      {
        reconnect_required: false,
        picker_scope_ready: false,
        picker_configured: true,
      },
      {
        reconnect_required: false,
        picker_scope_ready: true,
        picker_configured: false,
      },
    ];
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();

    for (const scenario of scenarios) {
      cleanup();
      vi.clearAllMocks();
      baseFetch.mockImplementation((url: string, init?: RequestInit) => {
        if (url.endsWith("/api/google/connection"))
          return json({
            connected: true,
            status: "active",
            google_email: "safe.user@example.com",
            scopes: "openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly",
            connected_at: "2026-07-01T00:00:00",
            revoked_at: null,
            picker_configured: scenario.picker_configured,
            picker_scope_ready: scenario.picker_scope_ready,
            picker_ready: false,
            reconnect_required: scenario.reconnect_required,
          });
        return defaultFetch?.(url, init) ?? json({ ok: true });
      });

      renderApp();
      await openProjectsPage();
      const button = await screen.findByRole("button", {
        name: "Выбрать папку результата для задачи 1",
      });
      expect(button).toBeDisabled();
      await userEvent.click(button);
      expect(
        (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(
          ([url]) => url === "/api/google/picker/session",
        ),
      ).toBe(false);
    }
  });

  it("row output-folder Picker verifies only folder ID and guards duplicate opens", async () => {
    const picker = installFakeGooglePicker();
    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    const button = screen.getByRole("button", {
      name: "Выбрать папку результата для задачи 1",
    });
    fireEvent.click(button);
    fireEvent.click(button);
    await picker.loadScript();
    await picker.waitForCallback();
    expect(picker.viewIds).toEqual([]);
    expect(picker.builderCalls).toEqual([]);
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.filter(
        ([url]) => url === "/api/google/picker/session",
      ),
    ).toHaveLength(1);
    picker.trigger({
      action: "picked",
      docs: [
        {
          id: "folder-picked",
          name: "Folder Name",
          mimeType: "application/vnd.google-apps.folder",
          token: "ya29.leaky",
        },
      ],
    });
    const folderCall = await waitFor(() => {
      const call = (
        fetch as unknown as ReturnType<typeof vi.fn>
      ).mock.calls.find(
        ([url, init]) =>
          url === "/api/projects/p1/output-folders/google-picker/verify" &&
          init?.method === "POST",
      );
      expect(call).toBeTruthy();
      return call;
    });
    expect(JSON.parse(String(folderCall?.[1]?.body))).toEqual({
      folder_id: "folder-picked",
    });
    expect(folderCall?.[1]?.headers).toEqual(
      expect.objectContaining({ "x-csrf-token": "csrf-after-refresh" }),
    );
    expect(String(folderCall?.[1]?.body)).not.toContain("Folder Name");
    expect(String(folderCall?.[1]?.body)).not.toContain(
      "application/vnd.google-apps.folder",
    );
    expect(String(folderCall?.[1]?.body)).not.toContain("raw-google-payload");
    expect(String(folderCall?.[1]?.body)).not.toContain("ya29");
    expect(document.body.textContent).not.toContain("Folder Name");
    expect(document.body.textContent).not.toContain("ya29");
    expect(document.body.textContent).not.toContain("raw-google-payload");
  });

  it("saves, revalidates, reuses, and removes an owner folder favorite", async () => {
    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    await chooseResultFolder(1, "favorite-folder", "Favorite Folder");

    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const previousFetch = fetchMock.getMockImplementation();
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (
        url === "/api/output-folder-favorites/google-picker" &&
        init?.method === "POST"
      ) {
        expect(JSON.parse(String(init.body))).toEqual({
          folder_id: "favorite-folder",
        });
        return json({
          id: "favorite-1",
          drive_folder_id: "favorite-folder",
          name: "Favorite Folder",
          web_view_url:
            "https://drive.google.com/drive/folders/favorite-folder",
          created_at: "2026-08-20T10:00:00Z",
          updated_at: "2026-08-20T10:00:00Z",
        });
      }
      if (
        url === "/api/output-folder-favorites/favorite-1" &&
        init?.method === "DELETE"
      ) {
        return json({ ok: true });
      }
      return previousFetch?.(url, init) ?? json({ ok: true });
    });

    await userEvent.click(
      screen.getByRole("button", { name: "Добавить в избранное" }),
    );
    expect(
      await screen.findByRole("button", { name: "Обновить в избранном" }),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Добавить задачу" }));
    const secondRow = await screen.findByRole("listitem", { name: "Задача 2" });
    await userEvent.click(within(secondRow).getByText("Избранные папки"));
    await userEvent.click(
      within(secondRow).getByRole("button", {
        name: "Выбрать: Favorite Folder",
      }),
    );
    await waitFor(() =>
      expect(within(secondRow).getByText("Favorite Folder")).toBeInTheDocument(),
    );
    const verificationCalls = fetchMock.mock.calls.filter(
      ([url, init]) =>
        url === "/api/projects/p1/output-folders/google-picker/verify" &&
        init?.method === "POST" &&
        JSON.parse(String(init.body)).folder_id === "favorite-folder",
    );
    expect(verificationCalls.length).toBeGreaterThanOrEqual(2);

    await userEvent.click(
      within(secondRow).getByRole("button", { name: "Действия с избранной папкой Favorite Folder" }),
    );
    await userEvent.click(within(secondRow).getByRole("menuitem", { name: "Убрать из избранного" }));
    await waitFor(() =>
      expect(
        within(secondRow).queryByRole("button", {
          name: "Выбрать: Favorite Folder",
        }),
      ).not.toBeInTheDocument(),
    );
    expect(
      fetchMock.mock.calls.filter(
        ([url, init]) =>
          url === "/api/output-folder-favorites/favorite-1" &&
          init?.method === "DELETE",
      ),
    ).toHaveLength(1);
  });

  it("revalidates a favorite for only the selected fragment and preserves default inheritance", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const previousFetch = fetchMock.getMockImplementation();
    let favoriteWritable = true;
    const favorite = {
      id: "favorite-1",
      drive_folder_id: "favorite-folder",
      name: "Избранная папка",
      web_view_url: "https://drive.google.com/drive/folders/favorite-folder",
      created_at: "2026-08-20T10:00:00Z",
      updated_at: "2026-08-20T10:00:00Z",
    };
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/output-folder-favorites") {
        return json({ favorites: [favorite] });
      }
      if (
        url === "/api/projects/p1/output-folders/google-picker/verify" &&
        init?.method === "POST" &&
        JSON.parse(String(init.body)).folder_id === favorite.drive_folder_id
      ) {
        return favoriteWritable
          ? json({ name: "Проверенная папка", web_view_url: favorite.web_view_url })
          : json({ detail: "folder_not_writable" }, false, 403);
      }
      return previousFetch?.(url, init) ?? json({ ok: true });
    });

    const favoritesFetch = fetchMock.getMockImplementation();
    renderApp();
    await openProjectsPage();
    await chooseExistingSource(1, "Лекция 1");
    await userEvent.click(screen.getByRole("checkbox", {
      name: /Разделить файл на фрагменты/,
    }));
    fireEvent.change(screen.getByLabelText("Количество фрагментов задачи 1"), {
      target: { value: "2" },
    });
    fireEvent.change(screen.getByLabelText("Конец фрагмента 1 задачи 1"), {
      target: { value: "10:00" },
    });
    fireEvent.change(screen.getByLabelText("Начало фрагмента 2 задачи 1"), {
      target: { value: "10:00" },
    });
    const firstFragment = screen.getByText("Фрагмент 1").closest("li")!;
    const secondFragment = screen.getByText("Фрагмент 2").closest("li")!;
    const favorites = screen.getByLabelText("Избранные папки фрагмента 1 задачи 1");
    await userEvent.click(within(favorites).getByText("Избранные папки"));
    await userEvent.click(await within(favorites).findByRole("button", {
      name: "Выбрать: Избранная папка",
    }));
    expect(await within(firstFragment).findByText("Проверенная папка")).toBeInTheDocument();
    expect(within(secondFragment).getByText("Папка не выбрана")).toBeInTheDocument();
    expect(screen.getByRole("button", {
      name: "Выбрать папку результата для задачи 1",
    })).toHaveTextContent("Выбрать");

    await chooseResultFolder(1, "default-folder", "Общая папка");
    fetchMock.mockImplementation(favoritesFetch!);
    expect(within(firstFragment).getByText("Проверенная папка")).toBeInTheDocument();
    expect(within(secondFragment).getByText("Общая папка")).toBeInTheDocument();
    await userEvent.click(within(firstFragment).getByRole("button", {
      name: "Наследовать общую папку для фрагмента 1 задачи 1",
    }));
    expect(within(firstFragment).getByText("Общая папка")).toBeInTheDocument();

    favoriteWritable = false;
    await userEvent.click(within(favorites).getByRole("button", {
      name: "Выбрать: Избранная папка",
    }));
    expect(await within(favorites).findByText(
      "Избранная папка больше не подтверждена для записи. Выберите другую или удалите её из списка.",
    )).toBeInTheDocument();
    expect(within(firstFragment).getByText("Общая папка")).toBeInTheDocument();
    expect(within(firstFragment).queryByText("Собственная папка этого фрагмента.")).not.toBeInTheDocument();

    favoriteWritable = true;
    await userEvent.click(within(favorites).getByRole("button", {
      name: "Выбрать: Избранная папка",
    }));
    expect(await within(firstFragment).findByText("Проверенная папка")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Проверить задачи (2)" }));
    await screen.findByLabelText("Проверка перед созданием задач");
    const preflightCall = fetchMock.mock.calls.find(
      ([url, init]) => isBatchPreflightRequest(url, init),
    );
    expect(JSON.parse(String(preflightCall?.[1]?.body)).items).toEqual([
      expect.objectContaining({ output_folder_id: "favorite-folder" }),
      expect.objectContaining({ output_folder_id: "default-folder" }),
    ]);
  });

  it("row output-folder Picker cancel/error does not mutate project folder and source/folder cannot open simultaneously", async () => {
    let picker = installFakeGooglePicker();
    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    await userEvent.click(
      screen.getByRole("button", { name: "Выбрать файлы Google Drive" }),
    );
    expect(
      screen.getByRole("button", { name: "Выбрать файлы Google Drive" }),
    ).toBeDisabled();
    await picker.loadScript();
    await picker.waitForCallback();
    picker.trigger({ action: "cancel" });
    await screen.findByText("Выбор файлов отменён.");
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(
        ([url]) =>
          url === "/api/projects/p1/output-folders/google-picker/verify",
      ),
    ).toBe(false);

    cleanup();
    vi.clearAllMocks();
    picker = installFakeGooglePicker();
    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    await userEvent.click(
      screen.getByRole("button", {
        name: "Выбрать папку результата для задачи 1",
      }),
    );
    await picker.loadScript();
    await picker.waitForCallback();
    picker.trigger({ action: "error", raw: "raw-google-payload" });
    expect(
      await screen.findByText(
        "Не удалось загрузить Google Drive. Переподключите Drive или повторите попытку.",
      ),
    ).toBeInTheDocument();
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(
        ([url]) =>
          url === "/api/projects/p1/output-folders/google-picker/verify",
      ),
    ).toBe(false);
    expect(document.body.textContent).not.toContain("raw-google-payload");

    cleanup();
    vi.clearAllMocks();
    picker = installFakeGooglePicker();
    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    await userEvent.click(
      screen.getByRole("button", {
        name: "Выбрать папку результата для задачи 1",
      }),
    );
    await picker.loadScript();
    await picker.waitForCallback();
    picker.trigger({ action: "picked", docs: [] });
    expect(
      await screen.findByText("Выберите одну папку Google Drive."),
    ).toBeInTheDocument();
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(
        ([url]) =>
          url === "/api/projects/p1/output-folders/google-picker/verify",
      ),
    ).toBe(false);
  });

  it("reconnect-required state provides a Settings recovery action", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string, init?: RequestInit) => {
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
          });
        if (url.endsWith("/api/auth/csrf"))
          return json({ csrf_token: "csrf-after-refresh" });
        if (url.endsWith("/api/projects"))
          return json({
            projects: [
              {
                id: "p1",
                title: "Research calls",
                description: null,
                created_at: "2026-07-01T00:00:00",
                updated_at: "2026-07-01T00:00:00",
                archived_at: null,
                output_drive_folder_id: null,
                output_drive_folder_url: null,
                output_drive_folder_name: null,
              },
            ],
          });
        if (url.endsWith("/api/projects/p1/sources") && !init?.method)
          return json({ sources: [] });
        if (url.endsWith("/api/google/connection"))
          return json({
            connected: true,
            status: "active",
            google_email: "safe.user@example.com",
            scopes: "openid email",
            connected_at: "2026-07-01T00:00:00",
            revoked_at: null,
            picker_configured: true,
            picker_scope_ready: false,
            picker_ready: false,
            reconnect_required: true,
          });
        if (url.endsWith("/api/google/oauth/start") && init?.method === "POST")
          return json(googleOauthStartFixture({}));
        return json({ credentials: [], events: [] });
      },
    );
    const assign = vi.fn();
    Object.defineProperty(window, "location", {
      value: { ...originalLocation, assign },
      configurable: true,
    });
    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    await waitFor(() =>
      expect(document.body.textContent).toContain(
        "Переподключите Google Drive",
      ),
    );
    expect(
      screen.getByRole("button", { name: "Выбрать файлы Google Drive" }),
    ).toBeDisabled();
    await openSettingsSection("Подключения");
    await userEvent.click(
      await screen.findByRole("button", {
        name: "Переподключить Google Drive",
      }),
    );
    expect(fetch).toHaveBeenCalledWith(
      "/api/google/oauth/start",
      expect.objectContaining({ method: "POST" }),
    );
    expect(assign).toHaveBeenCalledWith(
      String(googleOauthStartFixture().authorization_url),
    );
  });

  it("allows creating a job without credential when credential loading fails", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string, init?: RequestInit) => {
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
          });
        if (url.endsWith("/api/auth/csrf"))
          return json({ csrf_token: "csrf-after-refresh" });
        if (url.endsWith("/api/google/connection"))
          return json({
            connected: true,
            status: "active",
            google_email: "safe.user@example.com",
            scopes: "openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly",
            connected_at: "2026-07-01T00:00:00",
            revoked_at: null,
            picker_configured: true,
            picker_scope_ready: true,
            picker_ready: true,
            reconnect_required: false,
          });
        if (url.endsWith("/api/credentials"))
          return json({ detail: "raw backend detail ignored" }, false, 503);
        if (url.endsWith("/api/projects"))
          return json({
            projects: [
              {
                id: "p1",
                title: "Research calls",
                description: null,
                created_at: "2026-07-01T00:00:00",
                updated_at: "2026-07-01T00:00:00",
                archived_at: null,
                output_drive_folder_id: "folder-default",
                output_drive_folder_url:
                  "https://drive.google.com/drive/folders/folder-default",
                output_drive_folder_name: "Default folder",
              },
            ],
          });
        if (url.endsWith("/api/projects/p1/jobs") && !init?.method)
          return json({ jobs: [] });
        if (url.endsWith("/api/projects/p1/sources") && !init?.method)
          return json({
            sources: [
              {
                id: "s1",
                project_id: "p1",
                source_type: "local_upload",
                original_filename: "ready-local.ogg",
                mime_type: "audio/ogg",
                size_bytes: 4096,
                drive_file_id: null,
                drive_file_url: null,
                upload_status: "uploaded",
                uploaded_at: "2026-07-01T00:02:00",
                expires_at: null,
                deleted_at: null,
                delete_reason: null,
                created_at: "2026-07-01T00:00:00",
                updated_at: "2026-07-01T00:00:00",
              },
            ],
          });
        if (
          url.endsWith("/api/projects/p1/jobs/batch") &&
          init?.method === "POST"
        )
          return json({
            jobs: [
              {
                id: "job-created",
                project_id: "p1",
                status: "queued",
                title: null,
                provider: null,
                provider_credential_id: "cred-active",
                source_count: 1,
                sources: [],
                output_folder: {
                  name: "Default folder",
                  web_view_url:
                    "https://drive.google.com/drive/folders/folder-default",
                },
                created_at: "2026-07-04T00:00:00Z",
                updated_at: "2026-07-04T00:00:00Z",
                cancelled_at: null,
                cancel_requested_at: null,
                attempt_count: 0,
                started_at: null,
                finished_at: null,
                error_code: null,
                error_message: null,
              },
            ],
            created_count: 1,
            replayed: false,
          });
        return json({});
      },
    );
    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /Проверить задачи \(\d+\)/ }),
      ).toBeDisabled(),
    );
    expect(
      screen.queryByText("raw backend detail ignored"),
    ).not.toBeInTheDocument();

    await chooseExistingSource(1, "ready-local.ogg");
    await chooseResultFolder(1);
    expect(
      screen.getByRole("button", { name: /Проверить задачи \(\d+\)/ }),
    ).toBeDisabled();
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(
        ([url, init]) =>
          url === "/api/projects/p1/jobs/batch" && init?.method === "POST",
      ),
    ).toBe(false);
    expect(window.localStorage.length).toBe(0);
    expectOnlySafeFormDrafts();
  });

  it("bounds stalled project source and job collection reads", async () => {
    installFocusedOutputFixture({ jobStatus: "completed" });
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const stalledPaths = new Set([
      "/api/projects/p1/sources",
      "/api/projects/p1/jobs",
    ]);
    const requestSignals: AbortSignal[] = [];
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (stalledPaths.has(String(url)) && !init?.method) {
        const signal = init?.signal;
        if (!signal) throw new Error("project collection signal is missing");
        requestSignals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      }
      return defaultFetch?.(url, init) ?? json({});
    });
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 15_000 ? 0 : delay,
          ...args,
        )) as typeof setTimeout);

    try {
      renderApp();
      await openProjectsPage();
      await screen.findByRole("form", {
        name: "Композитор пакетных задач",
      });

      expect(
        await screen.findByText(
          "Не удалось загрузить сохранённые файлы Studio.",
        ),
      ).toBeInTheDocument();
      expect(
        await screen.findByText("Не удалось загрузить задачи проекта."),
      ).toBeInTheDocument();
      // Overview loads recent jobs once; the transcription workspace then
      // loads its own source and job collections. Every stalled read remains
      // bounded and is aborted by the shared request timeout.
      expect(requestSignals).toHaveLength(3);
      expect(requestSignals.every((signal) => signal.aborted)).toBe(true);
      expect(screen.queryByText("Загрузка файлов…")).not.toBeInTheDocument();
      expect(screen.queryByText("Загрузка задач…")).not.toBeInTheDocument();
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("rejects malformed or cross-project source and job collections", async () => {
    installFocusedOutputFixture();
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/projects/p1/sources") && !init?.method) {
        return json({
          sources: [
            {
              id: "source-unsafe",
              project_id: "project-other",
              source_type: "google_drive",
              original_filename: "raw-private-source.mp3",
              mime_type: "audio/mpeg",
              size_bytes: 1234,
              drive_file_url: null,
              upload_status: "uploaded",
              uploaded_at: "2026-08-14T10:00:00Z",
              expires_at: null,
              deleted_at: null,
              delete_reason: null,
              created_at: "2026-08-14T09:00:00Z",
              updated_at: "2026-08-14T10:00:00Z",
              s3_object_key: "raw-private-storage-key",
            },
          ],
        });
      }
      if (url.endsWith("/api/projects/p1/jobs") && !init?.method) {
        return json({
          jobs: [
            {
              id: "job-unsafe",
              project_id: "p1",
              status: "private-status",
              title: "raw-private-job",
              provider: null,
              source_count: 0,
              created_at: "2026-08-14T09:00:00Z",
              updated_at: "2026-08-14T10:00:00Z",
              cancelled_at: null,
              cancel_requested_at: null,
              attempt_count: 0,
              started_at: null,
              finished_at: null,
              error_code: null,
              error_message: null,
              lease_owner_id: "raw-private-worker",
            },
          ],
        });
      }
      return defaultFetch?.(url, init) ?? json({});
    });

    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });

    expect(
      await screen.findByText(
        "Не удалось загрузить сохранённые файлы Studio.",
      ),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Не удалось загрузить задачи проекта."),
    ).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("raw-private");
  });

  it("does not request job outputs until explicit job detail opening", async () => {
    installFocusedOutputFixture();
    renderApp();
    await waitForPlatformOverview();
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(([url]) =>
        String(url).endsWith("/api/jobs/job-focused/outputs"),
      ),
    ).toBe(false);

    await userEvent.click(
      screen.getByRole("button", { name: /Транскрибации/ }),
    );
    await screen.findByRole("tab", { name: "Обычная транскрибация" });
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(([url]) =>
        String(url).endsWith("/api/jobs/job-focused/outputs"),
      ),
    ).toBe(false);

    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    expect(await screen.findByText("Focused output job")).toBeInTheDocument();
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(([url]) =>
        String(url).endsWith("/api/jobs/job-focused/outputs"),
      ),
    ).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Открыть" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/jobs/job-focused/outputs",
        expect.objectContaining({ credentials: "same-origin" }),
      ),
    );
    const outputCalls = (
      fetch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.filter(([url]) => url === "/api/jobs/job-focused/outputs");
    expect(outputCalls).toHaveLength(1);
    expect(outputCalls[0]?.[1]?.method).toBeUndefined();
    expect(outputCalls[0]?.[1]?.headers).not.toHaveProperty("x-csrf-token");
  });

  it("renders a completed English job consistently across list, detail, progress, and outputs", async () => {
    installFocusedOutputFixture({
      jobStatus: "completed",
      languageMode: "en",
    });

    await openFocusedJobsList();
    await userEvent.click(screen.getByRole("button", { name: "Показать результаты и детали" }));

    expect(
      await screen.findByText(
        "Задача завершена — документ доступен по кнопке результата.",
      ),
    ).toBeInTheDocument();
    expect(await screen.findByText("Язык: Английский")).toBeInTheDocument();
    expect(
      await screen.findByText("Статус: Завершена"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Открыть документ" }),
    ).toHaveAttribute(
      "href",
      "https://docs.google.com/document/d/focused-safe/edit",
    );
    expect(
      screen.queryByText("Не удалось загрузить задачи проекта."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Не удалось загрузить детали задачи."),
    ).not.toBeInTheDocument();
  });

  it("bounds stalled job detail reads and leaves safe retryable UI", async () => {
    installFocusedOutputFixture({ jobStatus: "processing" });
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const stalledPaths = new Set([
      "/api/jobs/job-focused",
      "/api/jobs/job-focused/retry",
      "/api/jobs/job-focused/output-reconciliation",
      "/api/jobs/job-focused/outputs",
    ]);
    const requestSignals: AbortSignal[] = [];
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (stalledPaths.has(String(url)) && !init?.method) {
        const signal = init?.signal;
        if (!signal) throw new Error("job detail request signal is missing");
        requestSignals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      }
      return defaultFetch?.(url, init) ?? json({});
    });

    await openFocusedJobsList();
    vi.useFakeTimers();
    try {
      fireEvent.click(screen.getByRole("button", { name: "Открыть" }));
      expect(screen.getByText("Загрузка деталей задачи…")).toBeInTheDocument();
      expect(screen.getByText("Загрузка результатов…")).toBeInTheDocument();
      expect(requestSignals).toHaveLength(4);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000);
      });

      expect(requestSignals.every((signal) => signal.aborted)).toBe(true);
      expect(
        screen.getByText("Не удалось загрузить детали задачи."),
      ).toBeInTheDocument();
      expect(
        screen.getByText("Не удалось загрузить результаты."),
      ).toBeInTheDocument();
      expect(
        screen.queryByText("Загрузка деталей задачи…"),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByText("Загрузка результатов…"),
      ).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("rejects malformed job detail and output DTOs without raw rendering", async () => {
    installFocusedOutputFixture();
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/jobs/job-focused" && !init?.method) {
        return json({
          id: "job-other",
          project_id: "p1",
          status: "processing",
          title: "raw-private-detail",
          provider: null,
          source_count: 0,
          sources: [],
          created_at: "2026-08-14T09:00:00Z",
          updated_at: "2026-08-14T10:00:00Z",
          cancelled_at: null,
          cancel_requested_at: null,
          attempt_count: 1,
          started_at: null,
          finished_at: null,
          error_code: null,
          error_message: null,
          lease_owner_id: "raw-private-detail-owner",
        });
      }
      if (url === "/api/jobs/job-focused/outputs" && !init?.method) {
        return json({
          job_id: "job-focused",
          job_status: "completed",
          output_count: 1,
          outputs: [
            {
              source_id: "source-focused",
              source_position: 0,
              source_name: "raw-private-output",
              source_type: "google_drive",
              output_kind: "google_doc",
              transcript_standard: "transcript_doc",
              web_view_url: "https://evil.example/raw-private-link",
              link_available: true,
              document_character_count: 10,
              document_created_at: "2026-08-14T10:00:00Z",
              persisted_at: "2026-08-14T10:01:00Z",
              document_id: "raw-private-document-id",
            },
          ],
        });
      }
      return defaultFetch?.(url, init) ?? json({});
    });

    await openFocusedJobsList();
    await userEvent.click(screen.getByRole("button", { name: "Открыть" }));

    expect(
      await screen.findByText("Не удалось загрузить детали задачи."),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Не удалось загрузить результаты."),
    ).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("raw-private");
  });

  it("rejects inconsistent retry and reconciliation authority DTOs", async () => {
    installFocusedOutputFixture({ jobStatus: "failed" });
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/jobs/job-focused/retry" && !init?.method) {
        return json({
          job_id: "job-focused",
          job_status: "failed",
          available: true,
          reason: "non_retryable",
          attempt_count: 1,
          max_attempts: 3,
          missing_output_count: 1,
          retry_safe_source_count: 0,
          raw_checkpoint: "raw-private-checkpoint",
        });
      }
      if (
        url === "/api/jobs/job-focused/output-reconciliation" &&
        !init?.method
      ) {
        return json({
          job_id: "job-focused",
          job_status: "failed",
          available: true,
          counts: {
            prepared: 0,
            creation_returned: 0,
            reconciliation_required: 0,
            resolved: 0,
            conflict: 0,
          },
          cases: [],
          raw_google_token: "raw-private-google-token",
        });
      }
      return defaultFetch?.(url, init) ?? json({});
    });

    await openFocusedJobsList();
    await userEvent.click(screen.getByRole("button", { name: "Открыть" }));
    expect(
      await screen.findByLabelText("Подробности транскрибации"),
    ).toBeInTheDocument();

    expect(
      screen.queryByRole("button", { name: "Повторить безопасную обработку" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Проверить созданный документ в Google Drive",
      }),
    ).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("raw-private");
  });

  it("keeps only the latest repeated job detail refresh", async () => {
    installFocusedOutputFixture();
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let detailCalls = 0;
    let outputCalls = 0;
    let resolveStaleDetail: ((response: Response) => void) | undefined;
    let resolveStaleOutputs: ((response: Response) => void) | undefined;
    const staleDetail = new Promise<Response>((resolve) => {
      resolveStaleDetail = resolve;
    });
    const staleOutputs = new Promise<Response>((resolve) => {
      resolveStaleOutputs = resolve;
    });
    const detailBody = (sourceName: string) => ({
      id: "job-focused",
      project_id: "p1",
      status: "processing",
      title: "Focused output job",
      provider: null,
      provider_credential_id: "cred-active",
      source_count: 1,
      created_at: "2026-07-02T00:00:00Z",
      updated_at: "2026-07-02T00:01:00Z",
      cancelled_at: null,
      cancel_requested_at: null,
      attempt_count: 1,
      started_at: "2026-07-02T00:00:30Z",
      finished_at: null,
      error_code: null,
      error_message: null,
      sources: [
        {
          id: "source-detail-id-not-output-id",
          project_id: "p1",
          position: 0,
          job_source_status: "queued",
          source_type: "google_drive",
          original_filename: sourceName,
          mime_type: "audio/mpeg",
          size_bytes: 1234,
          drive_file_id: null,
          drive_file_url: null,
          upload_status: "uploaded",
          uploaded_at: "2026-07-01T00:01:00Z",
          expires_at: null,
          deleted_at: null,
          delete_reason: null,
          created_at: "2026-07-01T00:00:00Z",
          updated_at: "2026-07-01T00:00:00Z",
        },
      ],
    });
    const outputsBody = (sourceName: string) => ({
      job_id: "job-focused",
      job_status: "processing",
      output_count: 1,
      outputs: [
        {
          source_id: "source-id-not-rendered",
          source_position: 0,
          source_name: sourceName,
          source_type: "google_drive",
          output_kind: "transcript",
          transcript_standard: "transcript_doc",
          web_view_url:
            "https://docs.google.com/document/d/focused-safe/edit",
          link_available: true,
          document_character_count: 456,
          document_created_at: "2026-07-02T00:10:00Z",
          persisted_at: "2026-07-02T00:11:00Z",
        },
      ],
    });

    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      const requestUrl = String(url);
      if (requestUrl.endsWith("/api/jobs/job-focused") && !init?.method) {
        detailCalls += 1;
        return detailCalls === 1
          ? staleDetail
          : json(detailBody("fresh-detail.mp3"));
      }
      if (
        requestUrl.endsWith("/api/jobs/job-focused/outputs") &&
        !init?.method
      ) {
        outputCalls += 1;
        return outputCalls === 1
          ? staleOutputs
          : json(outputsBody("fresh-output"));
      }
      return defaultFetch?.(url, init) ?? json({});
    });

    await openFocusedJobsList();
    await userEvent.click(screen.getByRole("button", { name: "Открыть" }));
    await waitFor(() => {
      expect(detailCalls).toBe(1);
      expect(outputCalls).toBe(1);
    });
    await userEvent.click(screen.getByRole("button", { name: "Открыть" }));
    await waitFor(() => {
      expect(detailCalls).toBe(2);
      expect(outputCalls).toBe(2);
    });

    expect(
      await screen.findByLabelText("Подробности транскрибации"),
    ).toHaveTextContent("fresh-detail.mp3");
    expect(
      await screen.findByLabelText("Результаты транскрибации"),
    ).toHaveTextContent("fresh-output");

    await act(async () => {
      resolveStaleDetail?.(await json(detailBody("stale-detail.mp3")));
      resolveStaleOutputs?.(await json(outputsBody("stale-output")));
    });

    expect(screen.getByLabelText("Подробности транскрибации")).toHaveTextContent(
      "fresh-detail.mp3",
    );
    expect(screen.getByLabelText("Результаты транскрибации")).toHaveTextContent(
      "fresh-output",
    );
    expect(document.body.textContent).not.toContain("stale-detail.mp3");
    expect(document.body.textContent).not.toContain("stale-output");
  });

  it("deduplicates terminal dismissal and unlocks after failure", async () => {
    installFocusedOutputFixture({ jobStatus: "completed" });
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const dismissResolvers: Array<(response: Response) => void> = [];
    let dismissCalls = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        String(url).endsWith("/api/jobs/job-focused/dismiss") &&
        init?.method === "POST"
      ) {
        dismissCalls += 1;
        return new Promise<Response>((resolve) => {
          dismissResolvers.push(resolve);
        });
      }
      return defaultFetch?.(url, init) ?? json({});
    });

    await openFocusedJobsList();
    const dismissButton = screen.getByRole("button", {
      name: "Убрать в историю",
    });
    act(() => {
      dismissButton.click();
      dismissButton.click();
    });

    await waitFor(() => expect(dismissCalls).toBe(1));
    expect(dismissButton).toBeDisabled();
    expect(dismissButton).toHaveAttribute("aria-busy", "true");

    await act(async () => {
      dismissResolvers[0]?.(
        await json({ detail: "raw dismissal failure" }, false, 500),
      );
    });
    expect(
      await screen.findByText(
        "Не удалось убрать задачу в историю. Повторите позже.",
      ),
    ).toBeInTheDocument();
    const unlockedButton = screen.getByRole("button", {
      name: "Убрать в историю",
    });
    await waitFor(() => expect(unlockedButton).toBeEnabled());

    await userEvent.click(unlockedButton);
    await waitFor(() => expect(dismissCalls).toBe(2));
    dismissResolvers[1]?.(
      await json({
        id: "job-focused",
        project_id: "p1",
        status: "completed",
        title: "Focused output job",
        provider: null,
        provider_credential_id: "cred-active",
        terminal_dismissed_at: "2026-07-02T00:04:00Z",
        source_count: 1,
        sources: [],
        created_at: "2026-07-02T00:00:00Z",
        updated_at: "2026-07-02T00:04:00Z",
        cancelled_at: null,
        cancel_requested_at: null,
        attempt_count: 1,
        started_at: "2026-07-02T00:00:30Z",
        finished_at: "2026-07-02T00:03:00Z",
        error_code: null,
        error_message: null,
      }),
    );
    await waitFor(() =>
      expect(
        (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.filter(
          ([url]) => url === "/api/projects/p1/jobs",
        ).length,
      ).toBeGreaterThan(1),
    );

    expect(dismissCalls).toBe(2);
    expect(document.body.textContent).not.toContain("raw dismissal failure");
  });

  it("deduplicates in-flight cancellation and unlocks after failure", async () => {
    installFocusedOutputFixture({ jobStatus: "queued" });
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const cancelResolvers: Array<(response: Response) => void> = [];
    let cancelCalls = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        String(url).endsWith("/api/jobs/job-focused/cancel") &&
        init?.method === "POST"
      ) {
        cancelCalls += 1;
        return new Promise<Response>((resolve) => {
          cancelResolvers.push(resolve);
        });
      }
      return defaultFetch?.(url, init) ?? json({});
    });

    await openFocusedJobsList();
    const cancelButton = screen.getByRole("button", { name: "Отменить" });
    act(() => {
      cancelButton.click();
      cancelButton.click();
    });

    await waitFor(() => expect(cancelCalls).toBe(1));
    expect(cancelButton).toBeDisabled();
    expect(cancelButton).toHaveAttribute("aria-busy", "true");

    await act(async () => {
      cancelResolvers[0]?.(
        await json({ detail: "raw cancellation failure" }, false, 500),
      );
    });
    expect(
      await screen.findByText("Не удалось отменить задачу. Повторите позже."),
    ).toBeInTheDocument();
    const retryButton = screen.getByRole("button", { name: "Отменить" });
    await waitFor(() => expect(retryButton).toBeEnabled());

    await userEvent.click(retryButton);
    await waitFor(() => expect(cancelCalls).toBe(2));
    cancelResolvers[1]?.(
      await json({
        id: "job-focused",
        project_id: "p1",
        status: "cancelled",
        title: "Focused output job",
        provider: null,
        provider_credential_id: "cred-active",
        source_count: 1,
        sources: [focusedJobDetailSource],
        created_at: "2026-07-02T00:00:00Z",
        updated_at: "2026-07-02T00:02:00Z",
        cancelled_at: "2026-07-02T00:02:00Z",
        cancel_requested_at: null,
        attempt_count: 0,
        started_at: null,
        finished_at: "2026-07-02T00:02:00Z",
        error_code: null,
        error_message: null,
      }),
    );

    expect(
      await screen.findByText(
        "Запрос отмены отправлен. Уже созданные результаты останутся доступны.",
      ),
    ).toBeInTheDocument();
    expect(cancelCalls).toBe(2);
    expect(document.body.textContent).not.toContain("raw cancellation failure");
  });

  it("rejects malformed direct cancellation authority without raw rendering", async () => {
    installFocusedOutputFixture({ jobStatus: "queued" });
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        String(url).endsWith("/api/jobs/job-focused/cancel") &&
        init?.method === "POST"
      ) {
        return json({
          id: "job-other",
          project_id: "p1",
          status: "cancelled",
          raw_worker_lease: "raw-private-cancel-lease",
        });
      }
      return defaultFetch?.(url, init) ?? json({});
    });

    await openFocusedJobsList();
    await userEvent.click(screen.getByRole("button", { name: "Отменить" }));

    expect(
      await screen.findByText("Не удалось отменить задачу. Повторите позже."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Отменить" })).toBeEnabled();
    expect(document.body.textContent).not.toContain("raw-private");
  });

  it("rejects malformed direct dismissal authority without raw rendering", async () => {
    installFocusedOutputFixture({ jobStatus: "completed" });
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        String(url).endsWith("/api/jobs/job-focused/dismiss") &&
        init?.method === "POST"
      ) {
        return json({
          id: "job-focused",
          project_id: "p1",
          status: "completed",
          terminal_dismissed_at: null,
          raw_storage_key: "raw-private-dismiss-storage",
        });
      }
      return defaultFetch?.(url, init) ?? json({});
    });

    await openFocusedJobsList();
    await userEvent.click(
      screen.getByRole("button", { name: "Убрать в историю" }),
    );

    expect(
      await screen.findByText(
        "Не удалось убрать задачу в историю. Повторите позже.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Убрать в историю" }),
    ).toBeEnabled();
    expect(document.body.textContent).not.toContain("raw-private");
  });

  it("clears history only after Да while preserving the durable job", async () => {
    installFocusedOutputFixture({
      jobStatus: "completed",
      terminalDismissedAt: "2026-07-02T00:04:00Z",
    });
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const clearCalls: Array<RequestInit | undefined> = [];
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        String(url).endsWith("/api/projects/p1/history/clear") &&
        init?.method === "POST"
      ) {
        clearCalls.push(init);
        return json({
          ok: true,
          reset_at: "2026-08-21T12:00:00Z",
          hidden_job_count: 1,
          preserved_job_count: 0,
        });
      }
      return defaultFetch?.(url, init) ?? json({});
    });

    await openFocusedJobsList();
    await userEvent.click(screen.getByText(/Недавние транскрибации/));
    await userEvent.click(
      screen.getByRole("button", { name: "Очистить историю" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Нет" }));
    expect(clearCalls).toHaveLength(0);

    await userEvent.click(
      screen.getByRole("button", { name: "Очистить историю" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Да" }));
    expect(
      await screen.findByText(
        "История очищена. Незавершённые задачи и задачи, требующие решения, сохранены.",
      ),
    ).toBeInTheDocument();
    expect(clearCalls).toHaveLength(1);
    expect(clearCalls[0]).toEqual(
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ confirm_clear: true }),
      }),
    );
  });

  it("keeps a dismissed recovery task visible after history clear", async () => {
    installFocusedOutputFixture({
      jobStatus: "failed",
      terminalDismissedAt: "2026-07-02T00:04:00Z",
      historyAttentionRequired: true,
    });

    await openFocusedJobsList();

    const current = screen.getByLabelText("Текущие транскрибации");
    expect(current).toHaveTextContent("Focused output job");
    expect(current).toHaveTextContent(
      "Эта задача требует решения и сохранена после очистки истории.",
    );
    expect(
      screen.queryByRole("button", { name: "Убрать в историю" }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByText(/Недавние транскрибации/));
    expect(
      screen.queryByRole("button", { name: "Очистить историю" }),
    ).not.toBeInTheDocument();
  });

  it("keeps source deletion ownership across Settings section switches", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let resolveDelete: (response: Response) => void = () => undefined;
    let deleteCalls = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/sources/s1" && init?.method === "DELETE") {
        deleteCalls += 1;
        return new Promise<Response>((resolve) => {
          resolveDelete = resolve;
        });
      }
      return defaultFetch?.(url, init) ?? json({});
    });

    renderApp();
    await openSettingsSection("Файлы и хранилище");
    const removeButton = await screen.findByRole("button", {
      name: "Убрать из Studio: Лекция 1. Личность как психологическое явление.flac",
    });
    await userEvent.click(removeButton);
    await waitFor(() => expect(deleteCalls).toBe(1));

    await userEvent.click(screen.getByRole("tab", { name: "Аккаунт" }));
    await userEvent.click(
      screen.getByRole("tab", { name: "Файлы и хранилище" }),
    );
    const restoredButton = await screen.findByRole("button", {
      name: "Убрать из Studio: Лекция 1. Личность как психологическое явление.flac",
    });
    expect(restoredButton).toBeDisabled();
    restoredButton.click();
    expect(deleteCalls).toBe(1);

    await act(async () => {
      resolveDelete(
        await json({
          ok: true,
          source_state: "deleted",
          storage_cleanup: "not_applicable",
        }),
      );
    });
    expect(await screen.findByText("Файл убран из Studio.")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Убрать из Studio: Лекция 1. Личность как психологическое явление.flac",
      }),
    ).not.toBeInTheDocument();
  });
  it("keeps local upload ownership and safe outcomes across project switches", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const putResolvers: Array<(response: Response) => void> = [];
    let completionCalls = 0;
    let uploadSucceeded = false;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/projects" && !init?.method) {
        return json({
          projects: [
            {
              id: "p1",
              title: "Research calls",
              description: "Customer interview notes",
              created_at: "2026-07-01T00:00:00",
              updated_at: "2026-07-01T00:00:00",
              archived_at: null,
              output_drive_folder_id: "folder-123",
              output_drive_folder_url:
                "https://drive.example/folders/folder-123",
              output_drive_folder_name: "Transcripts",
            },
            {
              id: "p2",
              title: "Project Two",
              description: null,
              created_at: "2026-07-02T00:00:00",
              updated_at: "2026-07-02T00:00:00",
              archived_at: null,
              output_drive_folder_id: null,
              output_drive_folder_url: null,
              output_drive_folder_name: null,
            },
          ],
        });
      }
      if (url === "/api/projects/p2/sources" && !init?.method) {
        return json({ sources: [] });
      }
      if (url === "/api/projects/p2/jobs" && !init?.method) {
        return json({ jobs: [] });
      }
      if (
        url === "/api/projects/p1/sources" &&
        !init?.method &&
        uploadSucceeded
      ) {
        return json({
          sources: [
            {
              id: "local-source-2",
              project_id: "p1",
              source_type: "local_upload",
              original_filename: "local-source-2.ogg",
              mime_type: "audio/ogg",
              size_bytes: 7,
              drive_file_id: null,
              drive_file_url: null,
              upload_status: "uploaded",
              uploaded_at: "2099-01-01T00:00:00Z",
              expires_at: "2099-01-02T00:00:00Z",
              deleted_at: null,
              delete_reason: null,
              created_at: "2026-07-01T00:00:00Z",
              updated_at: "2026-07-01T00:00:00Z",
            },
          ],
        });
      }
      if (
        String(url).startsWith("https://upload.example/presigned") &&
        init?.method === "PUT"
      ) {
        return new Promise<Response>((resolve) => {
          putResolvers.push(resolve);
        });
      }
      if (
        String(url).endsWith("/local-upload/complete") &&
        init?.method === "POST"
      ) {
        completionCalls += 1;
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();
    const firstRow = await screen.findByLabelText("Источник задачи 1");
    const firstInput = within(firstRow).getByLabelText(
      "Выбрать файлы с устройства для задачи 1",
    ) as HTMLInputElement;
    await userEvent.upload(
      firstInput,
      new File(["failed"], "first-off-panel.ogg", { type: "audio/ogg" }),
    );
    await waitFor(() => expect(putResolvers).toHaveLength(1));
    const firstInitiation = baseFetch.mock.calls.find(
      ([url, init]) =>
        url === "/api/projects/p1/sources/local-upload/initiate" &&
        init?.method === "POST",
    );
    expect(JSON.parse(String(firstInitiation?.[1]?.body))).toMatchObject({
      reference_class: "transcription",
    });
    expect(firstInput).toBeDisabled();
    expect(firstInput).toHaveAttribute("aria-busy", "true");

    await userEvent.click(
      screen.getByRole("button", { name: /Project Two/ }),
    );
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    expect(
      screen.queryByText(
        "Загрузка файлов для этого проекта ещё выполняется. Дождитесь завершения перед новым выбором.",
      ),
    ).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /Research calls/ }),
    );
    expect(
      await screen.findByText(
        "Загрузка файлов для этого проекта ещё выполняется. Дождитесь завершения перед новым выбором.",
      ),
    ).toBeInTheDocument();
    const restoredInput = screen.getByLabelText(
      "Выбрать файлы с устройства для задачи 1",
    ) as HTMLInputElement;
    expect(restoredInput).toBeDisabled();
    expect(restoredInput).toHaveAttribute("aria-busy", "true");
    fireEvent.change(restoredInput, {
      target: {
        files: [
          new File(["duplicate"], "duplicate.ogg", { type: "audio/ogg" }),
        ],
      },
    });
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          url === "/api/projects/p1/sources/local-upload/initiate" &&
          init?.method === "POST",
      ),
    ).toHaveLength(1);

    await userEvent.click(
      screen.getByRole("button", { name: /Project Two/ }),
    );
    await act(async () => {
      putResolvers[0]?.(
        await json({ detail: "raw off-panel storage failure" }, false, 500),
      );
    });
    expect(
      screen.queryByText(
        "Локальная загрузка не завершена. Проверьте список файлов проекта перед повторной попыткой.",
      ),
    ).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /Research calls/ }),
    );
    expect(
      await screen.findByText(
        "Локальная загрузка не завершена. Проверьте список файлов проекта перед повторной попыткой.",
      ),
    ).toBeInTheDocument();
    const retryInput = screen.getByLabelText(
      "Выбрать файлы с устройства для задачи 1",
    ) as HTMLInputElement;
    await waitFor(() => expect(retryInput).toBeEnabled());
    expect(document.body).not.toHaveTextContent(
      "raw off-panel storage failure",
    );

    await userEvent.upload(
      retryInput,
      new File(["success"], "second-off-panel.ogg", { type: "audio/ogg" }),
    );
    await waitFor(() => expect(putResolvers).toHaveLength(2));
    expect(
      screen.queryByText(
        "Локальная загрузка не завершена. Проверьте список файлов проекта перед повторной попыткой.",
      ),
    ).not.toBeInTheDocument();
    uploadSucceeded = true;
    await act(async () => {
      putResolvers[1]?.(await json({ ok: true }));
    });
    await within(screen.getByLabelText("Источник задачи 1")).findByText(
      "Загружено файлов: 1.",
    );
    expect(completionCalls).toBe(1);

    await userEvent.click(
      screen.getByRole("button", { name: /Project Two/ }),
    );
    expect(
      screen.queryByText(
        "Локальная загрузка завершена. Обновлённый список файлов доступен в проекте.",
      ),
    ).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: /Research calls/ }),
    );
    expect(
      await screen.findByText(
        "Локальная загрузка завершена. Обновлённый список файлов доступен в проекте.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: /local-source-2\.ogg/ }),
    ).toBeInTheDocument();
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          url === "/api/projects/p1/sources/local-upload/initiate" &&
          init?.method === "POST",
      ),
    ).toHaveLength(2);
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          String(url).startsWith("https://upload.example/presigned") &&
          init?.method === "PUT",
      ),
    ).toHaveLength(2);
  });

  it("keeps cancellation ownership and safe outcomes across project switches", async () => {
    installFocusedOutputFixture({
      jobStatus: "queued",
      includeSecondProject: true,
    });
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const cancelResolvers: Array<(response: Response) => void> = [];
    let cancelCalls = 0;
    const failureMessage =
      "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0442\u043c\u0435\u043d\u0438\u0442\u044c \u0437\u0430\u0434\u0430\u0447\u0443. \u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0435 \u043f\u043e\u0437\u0436\u0435.";
    const successMessage =
      "\u0417\u0430\u043f\u0440\u043e\u0441 \u043e\u0442\u043c\u0435\u043d\u044b \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d. \u0423\u0436\u0435 \u0441\u043e\u0437\u0434\u0430\u043d\u043d\u044b\u0435 \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u044b \u043e\u0441\u0442\u0430\u043d\u0443\u0442\u0441\u044f \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u044b.";
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        String(url).endsWith("/api/jobs/job-focused/cancel") &&
        init?.method === "POST"
      ) {
        cancelCalls += 1;
        return new Promise<Response>((resolve) => {
          cancelResolvers.push(resolve);
        });
      }
      return defaultFetch?.(url, init) ?? json({});
    });

    await openFocusedJobsList();
    const cancelButton = screen.getByRole("button", {
      name: "\u041e\u0442\u043c\u0435\u043d\u0438\u0442\u044c",
    });
    await userEvent.click(cancelButton);
    await waitFor(() => expect(cancelCalls).toBe(1));

    await userEvent.click(
      screen.getByRole("button", { name: /Project Two/ }),
    );
    await screen.findByRole("form", {
      name: "\u041a\u043e\u043c\u043f\u043e\u0437\u0438\u0442\u043e\u0440 \u043f\u0430\u043a\u0435\u0442\u043d\u044b\u0445 \u0437\u0430\u0434\u0430\u0447",
    });
    await userEvent.click(
      screen.getByRole("button", { name: /Research calls/ }),
    );

    const restoredCancelButton = await screen.findByRole("button", {
      name: "\u041e\u0442\u043c\u0435\u043d\u0438\u0442\u044c",
    });
    expect(restoredCancelButton).toBeDisabled();
    expect(restoredCancelButton).toHaveAttribute("aria-busy", "true");
    restoredCancelButton.click();
    expect(cancelCalls).toBe(1);

    await act(async () => {
      cancelResolvers[0]?.(
        await json({ detail: "raw cancellation failure" }, false, 500),
      );
    });
    await waitFor(() => expect(restoredCancelButton).toBeEnabled());
    expect(await screen.findByText(failureMessage)).toBeInTheDocument();

    await userEvent.click(restoredCancelButton);
    await waitFor(() => expect(cancelCalls).toBe(2));
    expect(screen.queryByText(failureMessage)).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: /Project Two/ }),
    );
    await act(async () => {
      cancelResolvers[1]?.(
        await json({
          id: "job-focused",
          project_id: "p1",
          status: "cancelled",
          title: "Focused output job",
          provider: null,
          provider_credential_id: "cred-active",
          terminal_dismissed_at: null,
          source_count: 1,
          sources: [focusedJobDetailSource],
          created_at: "2026-07-02T00:00:00Z",
          updated_at: "2026-07-02T00:02:00Z",
          cancelled_at: "2026-07-02T00:02:00Z",
          cancel_requested_at: null,
          attempt_count: 1,
          started_at: "2026-07-02T00:00:30Z",
          finished_at: "2026-07-02T00:02:00Z",
          error_code: null,
          error_message: null,
        }),
      );
    });
    expect(screen.queryByText(successMessage)).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: /Research calls/ }),
    );
    expect(await screen.findByText(successMessage)).toBeInTheDocument();
    expect(cancelCalls).toBe(2);
    expect(document.body.textContent).not.toContain("raw cancellation failure");
  });
  it("deduplicates output reconciliation and unlocks after failure", async () => {
    const reconciliationResponse = {
      job_id: "job-focused",
      job_status: "failed",
      available: true,
      counts: {
        prepared: 0,
        creation_returned: 0,
        reconciliation_required: 1,
        resolved: 0,
        conflict: 0,
      },
      cases: [
        {
          job_source_id: "source-focused",
          status: "reconciliation_required",
          reason: "provider_outcome_uncertain",
          prepared_at: "2026-07-02T00:02:00Z",
          last_checked_at: null,
          resolved: false,
          resolved_at: null,
        },
      ],
    };
    installFocusedOutputFixture({
      jobStatus: "failed",
      reconciliationResponse,
    });
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const reconciliationResolvers: Array<(response: Response) => void> = [];
    let reconciliationCalls = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        String(url).endsWith(
          "/api/jobs/job-focused/output-reconciliation/check",
        ) && init?.method === "POST"
      ) {
        reconciliationCalls += 1;
        return new Promise<Response>((resolve) => {
          reconciliationResolvers.push(resolve);
        });
      }
      return defaultFetch?.(url, init) ?? json({});
    });

    await openFocusedJobsList();
    await userEvent.click(screen.getByRole("button", { name: "Открыть" }));
    const reconciliationButton = await screen.findByRole("button", {
      name: "Проверить созданный документ в Google Drive",
    });
    act(() => {
      reconciliationButton.click();
      reconciliationButton.click();
    });

    await waitFor(() => expect(reconciliationCalls).toBe(1));
    expect(reconciliationButton).toBeDisabled();
    expect(reconciliationButton).toHaveAttribute("aria-busy", "true");

    await act(async () => {
      reconciliationResolvers[0]?.(
        await json({ detail: "raw reconciliation failure" }, false, 500),
      );
    });
    expect(
      await screen.findByText("Не удалось проверить папку результата."),
    ).toBeInTheDocument();
    const unlockedButton = screen.getByRole("button", {
      name: "Проверить созданный документ в Google Drive",
    });
    await waitFor(() => expect(unlockedButton).toBeEnabled());

    await userEvent.click(unlockedButton);
    await waitFor(() => expect(reconciliationCalls).toBe(2));
    reconciliationResolvers[1]?.(
      await json({
        job_id: "job-focused",
        checked: 1,
        resolved: 1,
        unresolved: 0,
        conflicts: 0,
      }),
    );
    await waitFor(() =>
      expect(
        (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.filter(
          ([url]) => url === "/api/projects/p1/jobs",
        ).length,
      ).toBeGreaterThan(1),
    );

    const reconciliationPosts = (
      fetch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.filter(
      ([url, init]) =>
        url === "/api/jobs/job-focused/output-reconciliation/check" &&
        init?.method === "POST",
    );
    expect(reconciliationPosts).toHaveLength(2);
    expect(document.body.textContent).not.toContain(
      "raw reconciliation failure",
    );
  });

  it("submits cached assembly without provider-cost confirmation", async () => {
    installFocusedOutputFixture({ jobStatus: "failed", retryResponse: {
      job_id: "job-focused", job_status: "failed", available: true,
      reason: "full_provider_restore_available", attempt_count: 1, max_attempts: 3,
      missing_output_count: 1, retry_safe_source_count: 1,
      resumable_provider_part_count: 3, provider_total_part_count: 3,
    } });
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const posts: RequestInit[] = [];
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (String(url).endsWith("/api/jobs/job-focused/retry") && init?.method === "POST") {
        posts.push(init);
        return json({ detail: "synthetic restore rejected" }, false, 409);
      }
      return defaultFetch?.(url, init) ?? json({});
    });
    await openFocusedJobsList();
    await userEvent.click(screen.getByRole("button", { name: "Открыть" }));
    await userEvent.click(await screen.findByRole("button", { name: "Собрать и сохранить результат" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0].body).toBeUndefined();
  });

  it("deduplicates provider-cost retry and unlocks after failure", async () => {
    const retryResponse = {
      job_id: "job-focused",
      job_status: "failed",
      available: true,
      reason: "partial_provider_resume_available",
      attempt_count: 1,
      max_attempts: 3,
      missing_output_count: 1,
      retry_safe_source_count: 1,
      resumable_provider_part_count: 1,
      provider_total_part_count: 2,
      provider_failure_code: "provider_rate_limited",
    };
    installFocusedOutputFixture({ jobStatus: "failed", retryResponse });
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const retryResolvers: Array<(response: Response) => void> = [];
    let retryCalls = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        String(url).endsWith("/api/jobs/job-focused/retry") &&
        init?.method === "POST"
      ) {
        retryCalls += 1;
        return new Promise<Response>((resolve) => {
          retryResolvers.push(resolve);
        });
      }
      return defaultFetch?.(url, init) ?? json({});
    });

    await openFocusedJobsList();
    await userEvent.click(screen.getByRole("button", { name: "Открыть" }));
    const retryButton = await screen.findByRole("button", {
      name: "Продолжить оставшиеся части",
    });
    act(() => {
      retryButton.click();
      retryButton.click();
    });

    await waitFor(() => expect(retryCalls).toBe(1));
    expect(retryButton).toBeDisabled();
    expect(retryButton).toHaveAttribute("aria-busy", "true");

    await act(async () => {
      retryResolvers[0]?.(
        await json({ detail: "raw provider retry failure" }, false, 500),
      );
    });
    expect(
      await screen.findByText("Повтор сейчас недоступен."),
    ).toBeInTheDocument();
    const unlockedButton = screen.getByRole("button", {
      name: "Продолжить оставшиеся части",
    });
    await waitFor(() => expect(unlockedButton).toBeEnabled());

    await userEvent.click(unlockedButton);
    await waitFor(() => expect(retryCalls).toBe(2));
    retryResolvers[1]?.(
      await json({
        ...retryResponse,
        job_status: "queued",
        available: true,
        reason: "available",
        missing_output_count: 0,
        retry_safe_source_count: 0,
        resumable_provider_part_count: 0,
        provider_total_part_count: 0,
        provider_failure_code: null,
      }),
    );
    await waitFor(() =>
      expect(
        (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.filter(
          ([url]) => url === "/api/projects/p1/jobs",
        ).length,
      ).toBeGreaterThan(1),
    );

    const retryPosts = (
      fetch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.filter(
      ([url, init]) =>
        url === "/api/jobs/job-focused/retry" && init?.method === "POST",
    );
    expect(retryPosts).toHaveLength(2);
    expect(
      retryPosts.map(([, init]) => JSON.parse(String(init?.body))),
    ).toEqual([
      {
        confirm_remaining_provider_cost: true,
        confirm_long_duration_cost: false,
      },
      {
        confirm_remaining_provider_cost: true,
        confirm_long_duration_cost: false,
      },
    ]);
    expect(document.body.textContent).not.toContain(
      "raw provider retry failure",
    );
  });

  it("uses the server duration policy for the long-recording confirmation", async () => {
    const retryResponse = {
      job_id: "job-focused",
      job_status: "failed",
      available: true,
      reason: "available",
      attempt_count: 1,
      max_attempts: 3,
      missing_output_count: 1,
      retry_safe_source_count: 1,
      resumable_provider_part_count: 0,
      provider_total_part_count: 0,
      provider_failure_code: null, long_duration_preflight: { source_duration_seconds: 18000, selected_duration_seconds: 18000, nominal_cost: "1.10000000", currency: "USD", rate_per_hour: "0.220000", effective_date: "2026-10-06", source: "elevenlabs_public_api_pricing", provider: "elevenlabs", additional_source_count: 0, maximum_seconds_per_source: 21600, basis: "measured_duration_x_immutable_public_tariff", invoice_debit: false, confirmation_token: "a".repeat(64) },
    };
    installFocusedOutputFixture({
      jobStatus: "failed",
      errorCode: "media_duration_confirmation_required",
      retryResponse,
    });
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (String(url).endsWith("/api/sources/upload-policy") && !init?.method)
        return json({
          local_upload_enabled: true,
          max_upload_bytes: 536870912,
          multipart_threshold_bytes: 16777216,
          multipart_part_size_bytes: 8388608,
          media_duration_warning_seconds: 7200,
          media_max_duration_seconds: 21600,
          supported_mime_prefixes: ["audio/", "video/"],
          supported_mime_types: ["application/ogg"],
        });
      if (
        String(url).endsWith("/api/jobs/job-focused/retry") &&
        init?.method === "POST"
      )
        return json({ ...retryResponse, job_status: "queued" });
      return defaultFetch?.(url, init) ?? json({});
    });

    await openFocusedJobsList();
    await userEvent.click(screen.getByRole("button", { name: "Открыть" }));
    await userEvent.click(
      await screen.findByRole("button", {
        name: "Повторить безопасную обработку",
      }),
    );

    expect(window.confirm).toHaveBeenCalledWith(
      expect.stringContaining("Номинальная оценка: 1,1 USD"),
    );
    await waitFor(() =>
      expect(
        baseFetch.mock.calls.some(
          ([url, init]) =>
            url === "/api/jobs/job-focused/retry" &&
            init?.method === "POST" &&
            JSON.parse(String(init.body)).confirm_long_duration_cost === true && JSON.parse(String(init.body)).long_duration_confirmation_token === "a".repeat(64),
        ),
      ).toBe(true),
    );
  });
  it("confirms timed-out cancellation with an authoritative job read and no second POST", async () => {
    installFocusedOutputFixture({ jobStatus: "queued" });
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let cancelPosts = 0;
    let authoritativeReads = 0;
    let mutationSignal: AbortSignal | undefined;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      const requestUrl = String(url);
      if (
        requestUrl.endsWith("/api/jobs/job-focused/cancel") &&
        init?.method === "POST"
      ) {
        cancelPosts += 1;
        mutationSignal = init.signal;
        return new Promise<Response>((_resolve, reject) =>
          init.signal?.addEventListener("abort", () => reject(init.signal?.reason)),
        );
      }
      if (requestUrl.endsWith("/api/jobs/job-focused") && !init?.method) {
        authoritativeReads += 1;
        return json({
          id: "job-focused",
          project_id: "p1",
          status: "cancelled",
          title: "Focused output job",
          provider: null,
          terminal_dismissed_at: null,
          source_count: 1,
          sources: [focusedJobDetailSource],
          created_at: "2026-07-02T00:00:00Z",
          updated_at: "2026-07-02T00:02:00Z",
          cancelled_at: "2026-07-02T00:02:00Z",
          cancel_requested_at: null,
          attempt_count: 1,
          started_at: null,
          finished_at: "2026-07-02T00:02:00Z",
          error_code: null,
          error_message: null,
        });
      }
      return defaultFetch?.(url, init) ?? json({});
    });
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 20_000 ? 0 : delay,
          ...args,
        )) as typeof setTimeout);

    try {
      await openFocusedJobsList();
      await userEvent.click(
        screen.getByRole("button", { name: "Отменить" }),
      );

      expect(
        await screen.findByText(
          "Studio не ответила вовремя, но отмена подтверждена по актуальному состоянию задачи.",
        ),
      ).toBeInTheDocument();
      expect(cancelPosts).toBe(1);
      expect(authoritativeReads).toBe(1);
      expect(mutationSignal?.aborted).toBe(true);
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("reports an unconfirmed timed-out dismissal without repeating the POST", async () => {
    installFocusedOutputFixture({ jobStatus: "completed" });
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let dismissPosts = 0;
    let authoritativeReads = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      const requestUrl = String(url);
      if (
        requestUrl.endsWith("/api/jobs/job-focused/dismiss") &&
        init?.method === "POST"
      ) {
        dismissPosts += 1;
        return new Promise<Response>((_resolve, reject) =>
          init.signal?.addEventListener("abort", () => reject(init.signal?.reason)),
        );
      }
      if (requestUrl.endsWith("/api/jobs/job-focused") && !init?.method) {
        authoritativeReads += 1;
        return defaultFetch?.(url, init) ?? json({});
      }
      return defaultFetch?.(url, init) ?? json({});
    });
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 20_000 ? 0 : delay,
          ...args,
        )) as typeof setTimeout);

    try {
      await openFocusedJobsList();
      const readsBeforeDismiss = authoritativeReads;
      await userEvent.click(
        screen.getByRole("button", { name: "Убрать в историю" }),
      );

      expect(
        await screen.findByText(
          "Studio не ответила вовремя. Перенос в историю не подтверждён; обновите состояние перед повтором.",
        ),
      ).toBeInTheDocument();
      expect(dismissPosts).toBe(1);
      expect(authoritativeReads).toBeGreaterThan(readsBeforeDismiss);
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("confirms a timed-out provider-cost retry from readiness without repeating the POST", async () => {
    const beforeRetry = {
      job_id: "job-focused",
      job_status: "failed",
      available: true,
      reason: "partial_provider_resume_available",
      attempt_count: 1,
      max_attempts: 3,
      missing_output_count: 1,
      retry_safe_source_count: 1,
      resumable_provider_part_count: 1,
      provider_total_part_count: 2,
      provider_failure_code: "provider_rate_limited",
    };
    installFocusedOutputFixture({
      jobStatus: "failed",
      retryResponse: beforeRetry,
    });
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let retryPosts = 0;
    let readinessReads = 0;
    let retryTimedOut = false;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      const requestUrl = String(url);
      if (
        requestUrl.endsWith("/api/jobs/job-focused/retry") &&
        init?.method === "POST"
      ) {
        retryPosts += 1;
        return new Promise<Response>((_resolve, reject) =>
          init.signal?.addEventListener("abort", () => {
            retryTimedOut = true;
            reject(init.signal?.reason);
          }),
        );
      }
      if (
        requestUrl.endsWith("/api/jobs/job-focused/retry") &&
        !init?.method
      ) {
        readinessReads += 1;
        return json(
          retryTimedOut
            ? {
                ...beforeRetry,
                job_status: "queued",
                available: true,
                reason: "available",
                missing_output_count: 0,
                retry_safe_source_count: 0,
                resumable_provider_part_count: 0,
                provider_total_part_count: 0,
                provider_failure_code: null,
              }
            : beforeRetry,
        );
      }
      return defaultFetch?.(url, init) ?? json({});
    });
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 20_000 ? 0 : delay,
          ...args,
        )) as typeof setTimeout);

    try {
      await openFocusedJobsList();
      await userEvent.click(screen.getByRole("button", { name: "Открыть" }));
      const readsBeforeRetry = readinessReads;
      await userEvent.click(
        await screen.findByRole("button", {
          name: "Продолжить оставшиеся части",
        }),
      );

      expect(
        await screen.findByText(
          "Studio не ответила вовремя, но повтор подтверждён по актуальному состоянию задачи.",
        ),
      ).toBeInTheDocument();
      expect(retryPosts).toBe(1);
      expect(readinessReads).toBeGreaterThan(readsBeforeRetry);
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("reports an unchanged reconciliation state after timeout without repeating the Google check", async () => {
    const reconciliationState = {
      job_id: "job-focused",
      job_status: "failed",
      available: true,
      counts: {
        prepared: 0,
        creation_returned: 0,
        reconciliation_required: 1,
        resolved: 0,
        conflict: 0,
      },
      cases: [
        {
          job_source_id: "source-1",
          status: "reconciliation_required",
          reason: "provider_outcome_uncertain",
          prepared_at: "2026-07-02T00:02:00Z",
          resolved: false,
          last_checked_at: null,
          resolved_at: null,
        },
      ],
    };
    installFocusedOutputFixture({
      jobStatus: "failed",
      reconciliationResponse: reconciliationState,
    });
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let reconciliationPosts = 0;
    let reconciliationReads = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      const requestUrl = String(url);
      if (
        requestUrl.endsWith(
          "/api/jobs/job-focused/output-reconciliation/check",
        ) &&
        init?.method === "POST"
      ) {
        reconciliationPosts += 1;
        return new Promise<Response>((_resolve, reject) =>
          init.signal?.addEventListener("abort", () => reject(init.signal?.reason)),
        );
      }
      if (
        requestUrl.endsWith("/api/jobs/job-focused/output-reconciliation") &&
        !init?.method
      ) {
        reconciliationReads += 1;
        return json(reconciliationState);
      }
      return defaultFetch?.(url, init) ?? json({});
    });
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 20_000 ? 0 : delay,
          ...args,
        )) as typeof setTimeout);

    try {
      await openFocusedJobsList();
      await userEvent.click(screen.getByRole("button", { name: "Открыть" }));
      const readsBeforeCheck = reconciliationReads;
      await userEvent.click(
        await screen.findByRole("button", {
          name: "Проверить созданный документ в Google Drive",
        }),
      );

      expect(
        await screen.findByText(
          "Studio не ответила вовремя. Результат проверки не подтверждён; обновите состояние перед повтором.",
        ),
      ).toBeInTheDocument();
      expect(reconciliationPosts).toBe(1);
      expect(reconciliationReads).toBeGreaterThan(readsBeforeCheck);
    } finally {
      timeoutSpy.mockRestore();
    }
  });
  it.each(["success", "timeout-confirmed", "timeout-unknown", "reauth", "reauth-401"] as const)(
    "resolves an uncertain error with bounded readback: %s",
    async (mode) => {
      installFocusedOutputFixture({ jobStatus: "failed", historyAttentionRequired: true });
      vi.spyOn(window, "confirm").mockReturnValue(true);
      const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
      const defaultFetch = baseFetch.getMockImplementation()!;
      let posts = 0;
      let readbacks = 0;
      const resolvedFields = {
        history_attention_required: false,
        history_attention_resolved_at: "2026-09-06T10:00:00Z",
        history_attention_resolution: "acknowledged_no_result",
        history_attention_linked_job_id: null,
        terminal_dismissed_at: "2026-09-06T10:00:00Z",
      };
      baseFetch.mockImplementation(async (url: string, init?: RequestInit) => {
        if (String(url).endsWith("/api/jobs/job-focused/attention-resolution") && init?.method === "POST") {
          posts += 1;
          expect(JSON.parse(String(init.body))).toEqual({ resolution: "acknowledged_no_result", linked_job_id: null, confirm_possible_spend: true });
          if (mode === "reauth-401") return json({ detail: "session_expired" }, false, 401);
          if (mode === "reauth" && posts === 1) return json({ detail: { reason: "recent_reauthentication_required" } }, false, 409);
          if (mode.startsWith("timeout")) return new Promise<Response>((_resolve, reject) => init.signal?.addEventListener("abort", () => reject(init.signal?.reason)));
          const response = await defaultFetch("/api/jobs/job-focused");
          return json({ ...await response.json(), ...resolvedFields });
        }
        const response = await defaultFetch(url, init);
        if (posts && String(url).endsWith("/api/jobs/job-focused") && !init?.method) {
          readbacks += 1;
          if (mode === "timeout-confirmed") return json({ ...await response.json(), ...resolvedFields });
        }
        return response;
      });
      const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
      const timeoutSpy = vi.spyOn(globalThis, "setTimeout").mockImplementation(((callback, delay, ...args) => nativeSetTimeout(callback, delay === 20_000 ? 0 : delay, ...args)) as typeof setTimeout);
      try {
        await openFocusedJobsList();
        await userEvent.click(await screen.findByRole("button", { name: "Закрыть ошибку и убрать в историю" }));
        const message = mode === "reauth-401"
          ? "Для решения войдите в аккаунт заново."
          : mode === "reauth"
          ? "Сначала подтвердите личность в разделе «Аккаунт», затем повторите закрытие ошибки."
          : mode === "timeout-unknown"
            ? "Studio не ответила вовремя. Закрытие ошибки не подтверждено; обновите состояние перед повтором."
            : "Отмечено, что подтверждённого результата нет. Задача убрана в историю, решение сохранено в журнале.";
        expect(await screen.findByText(message)).toBeVisible();
        expect(posts).toBe(1);
        if (mode.startsWith("timeout")) expect(readbacks).toBeGreaterThan(0);
        if (mode === "reauth") {
          await userEvent.click(screen.getByRole("button", { name: "Закрыть ошибку и убрать в историю" }));
          expect(await screen.findByText("Отмечено, что подтверждённого результата нет. Задача убрана в историю, решение сохранено в журнале.")).toBeVisible();
          expect(posts).toBe(2);
        }
      } finally {
        timeoutSpy.mockRestore();
      }
    },
  );

  it("renders the explicit empty job outputs state without output links", async () => {
    installFocusedOutputFixture({
      jobStatus: "queued",
      outputCount: 0,
      outputs: [],
    });
    await openFocusedJobsList();
    await userEvent.click(screen.getByRole("button", { name: "Открыть" }));
    const outputs = await screen.findByLabelText("Результаты транскрибации");
    expect(outputs).toHaveTextContent("Результаты пока не созданы.");
    expect(
      within(outputs).queryByRole("link", { name: "Открыть документ" }),
    ).not.toBeInTheDocument();
  });

  it.each(["failed", "cancelled"] as const)(
    "renders partial outputs for %s jobs without completed-status gating",
    async (jobStatus) => {
      installFocusedOutputFixture({ jobStatus });
      await openFocusedJobsList();
      await userEvent.click(screen.getByRole("button", { name: "Открыть" }));
      const outputs = await screen.findByLabelText("Результаты транскрибации");
      expect(outputs).toHaveTextContent(`${jobStatus}-source`);
      expect(
        within(outputs).getByRole("link", { name: "Открыть документ" }),
      ).toHaveAttribute(
        "href",
        "https://docs.google.com/document/d/focused-safe/edit",
      );
    },
  );

  it("keeps loaded job details visible when outputs request fails generically", async () => {
    installFocusedOutputFixture({
      outputsOk: false,
      outputsErrorBody: { detail: "raw database traceback token" },
    });
    await openFocusedJobsList();
    await userEvent.click(screen.getByRole("button", { name: "Открыть" }));
    const detail = await screen.findByLabelText("Подробности транскрибации");
    expect(
      within(detail).getByText("1. focused-source.mp3"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Не удалось загрузить результаты."),
    ).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(
      "raw database traceback token",
    );
  });

  it("keeps successful outputs visible when job detail request fails generically", async () => {
    installFocusedOutputFixture({
      detailOk: false,
      detailErrorBody: { detail: "raw detail traceback token" },
    });
    await openFocusedJobsList();
    await userEvent.click(screen.getByRole("button", { name: "Открыть" }));
    expect(
      await screen.findByText("Не удалось загрузить детали задачи."),
    ).toBeInTheDocument();
    const outputs = await screen.findByLabelText("Результаты транскрибации");
    expect(outputs).toHaveTextContent("processing-source");
    expect(
      within(outputs).getByRole("link", { name: "Открыть документ" }),
    ).toHaveAttribute(
      "href",
      "https://docs.google.com/document/d/focused-safe/edit",
    );
    expect(document.body.textContent).not.toContain(
      "raw detail traceback token",
    );
  });

  it("keeps login out of the DOM while session bootstrap is pending", async () => {
    let resolveSession: (value: Response) => void = () => undefined;
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string) => {
        if (url.endsWith("/api/auth/session"))
          return new Promise((resolve) => {
            resolveSession = resolve;
          });
        return json({ csrf_token: "csrf-after-refresh" });
      },
    );
    renderApp();
    expect(screen.getByRole("status")).toHaveTextContent("Проверяем сессию…");
    expect(
      screen.queryByRole("heading", { name: "Вход" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Пароль")).not.toBeInTheDocument();
    resolveSession(
      await json({
        authenticated: true,
        user: { email: "user@example.com", role: "admin" },
      }),
    );
    await waitForPlatformOverview();
  });

  it("renders login only for confirmed anonymous session and keeps manual login/logout transitions", async () => {
    const mockFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    window.history.replaceState({}, "", "/settings/diagnostics");
    mockFetch.mockImplementation((url: string) => {
      if (url.endsWith("/api/auth/session")) return json({}, false, 401);
      if (url.endsWith("/api/auth/bootstrap-status"))
        return json({ bootstrap_required: false });
      if (url.endsWith("/api/auth/login-context"))
        return json({ login_csrf_token: "login-csrf" });
      if (url.endsWith("/api/auth/login"))
        return json({
          authenticated: true,
          user: { email: "user@example.com", role: "admin" },
          csrf_token: "csrf-login",
        });
      if (url.endsWith("/api/auth/logout")) return json({ ok: true });
      if (url.endsWith("/api/credentials"))
        return json({
          credentials: [
            {
              id: "cred-active",
              provider: "elevenlabs",
              label: "Primary STT",
              status: "active",
              masked_value: "••••1234",
              active_version: 2,
            },
          ],
        });
      if (url.endsWith("/api/audit-events")) return json({ events: [] });
      if (url.endsWith("/api/google/connection"))
        return json(googleConnectionFixture());
      return json({ csrf_token: "csrf-after-refresh" });
    });
    renderApp();
    await screen.findByRole("heading", { name: "Вход" });
    await userEvent.type(screen.getByLabelText("Email"), "user@example.com");
    await userEvent.type(screen.getByLabelText("Пароль"), "password-long");
    await userEvent.click(screen.getByRole("button", { name: "Войти" }));
    await waitForPlatformOverview();
    expect(window.location.pathname).toBe("/");
    await openSettingsPage();
    await userEvent.click(await screen.findByRole("button", { name: "Выйти" }));
    expect(
      await screen.findByRole("heading", { name: "Вход" }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe("/");

    await userEvent.type(screen.getByLabelText("Email"), "user@example.com");
    await userEvent.type(screen.getByLabelText("Пароль"), "password-long");
    await userEvent.click(screen.getByRole("button", { name: "Войти" }));
    await waitForPlatformOverview();
  });

  it("shows retry instead of login after transient session failure", async () => {
    let sessionCalls = 0;
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string) => {
        if (url.endsWith("/api/auth/session")) {
          sessionCalls += 1;
          return sessionCalls === 1
            ? json({ detail: "service unavailable" }, false, 503)
            : json({
                authenticated: true,
                user: { email: "user@example.com", role: "admin" },
              });
        }
        return json({ csrf_token: "csrf-after-refresh" });
      },
    );
    renderApp();
    expect(
      await screen.findByText(
        "Не удалось проверить сессию. Повторите попытку.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Вход" }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Повторить" }));
    await waitForPlatformOverview();
  });

  it("bounds and retries both authenticated bootstrap stages", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const sessionSignals: AbortSignal[] = [];
    const csrfSignals: AbortSignal[] = [];
    let secondAttemptSessionSignal: AbortSignal | undefined;
    let sessionReads = 0;
    let csrfReads = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/auth/session")) {
        sessionReads += 1;
        const signal = init?.signal;
        if (!signal) throw new Error("Session bootstrap signal is missing");
        if (sessionReads === 1) {
          sessionSignals.push(signal);
          return new Promise<Response>((_resolve, reject) => {
            signal.addEventListener("abort", () => reject(signal.reason));
          });
        }
        if (sessionReads === 2) secondAttemptSessionSignal = signal;
        return json({
          authenticated: true,
          user: { email: "current@example.com", role: "admin" },
        });
      }
      if (url.endsWith("/api/auth/csrf") && init?.method === "POST") {
        csrfReads += 1;
        const signal = init.signal;
        if (!signal) throw new Error("CSRF bootstrap signal is missing");
        if (csrfReads === 1) {
          csrfSignals.push(signal);
          return new Promise<Response>((_resolve, reject) => {
            signal.addEventListener("abort", () => reject(signal.reason));
          });
        }
        return json({
          csrf_token: "csrf-current",
          user: { email: "current@example.com", role: "admin" },
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 15_000 ? 1 : (delay as number),
          ...args,
        )) as typeof setTimeout);

    try {
      renderApp();
      expect(
        await screen.findByText(
          "Не удалось проверить сессию. Повторите попытку.",
        ),
      ).toBeInTheDocument();
      expect(sessionSignals).toHaveLength(1);
      expect(sessionSignals[0]?.aborted).toBe(true);
      expect(
        screen.queryByRole("heading", { name: "Вход" }),
      ).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole("button", { name: "Повторить" }));
      await waitFor(() => expect(csrfSignals).toHaveLength(1));
      expect(csrfSignals[0]).toBe(secondAttemptSessionSignal);
      expect(csrfSignals[0]?.aborted).toBe(true);
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Не удалось проверить сессию",
      );

      await userEvent.click(screen.getByRole("button", { name: "Повторить" }));
      await waitForPlatformOverview();
      expect(sessionReads).toBe(3);
      expect(csrfReads).toBe(2);
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("rejects malformed bootstrap responses without rendering raw fields", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let sessionReads = 0;
    let csrfReads = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/auth/session")) {
        sessionReads += 1;
        if (sessionReads === 1) {
          return json({
            authenticated: true,
            user: { email: "safe@example.com", role: "raw-session-role" },
            raw_session_field: "raw-session-secret",
          });
        }
        return json({
          authenticated: true,
          user: { email: "safe@example.com", role: "user" },
        });
      }
      if (url.endsWith("/api/auth/csrf") && init?.method === "POST") {
        csrfReads += 1;
        if (csrfReads === 1) {
          return json({
            csrf_token: "raw-csrf-token",
            user: { email: "other@example.com", role: "user" },
            raw_csrf_field: "raw-csrf-secret",
          });
        }
        return json({
          csrf_token: "csrf-safe",
          user: { email: "safe@example.com", role: "user" },
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Не удалось проверить сессию",
    );
    expect(document.body.textContent).not.toContain("raw-session-role");
    expect(document.body.textContent).not.toContain("raw-session-secret");
    expect(
      screen.queryByRole("heading", { name: "Вход" }),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Повторить" }));
    await waitFor(() => expect(csrfReads).toBe(1));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Не удалось проверить сессию",
    );
    expect(document.body.textContent).not.toContain("raw-csrf-token");
    expect(document.body.textContent).not.toContain("raw-csrf-secret");
    expect(document.body.textContent).not.toContain("other@example.com");

    await userEvent.click(screen.getByRole("button", { name: "Повторить" }));
    await waitForPlatformOverview();
    expect(sessionReads).toBe(3);
    expect(csrfReads).toBe(2);
  });

  it("aborts and ignores an older StrictMode bootstrap across session generations", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let sessionReads = 0;
    let csrfReads = 0;
    let olderSignal: AbortSignal | undefined;
    let resolveOlderSession: ((response: Response) => void) | undefined;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/auth/session")) {
        sessionReads += 1;
        if (sessionReads === 1) {
          olderSignal = init?.signal;
          return new Promise<Response>((resolve) => {
            resolveOlderSession = resolve;
          });
        }
        return json({
          authenticated: true,
          user: { email: "current@example.com", role: "admin" },
        });
      }
      if (url.endsWith("/api/auth/csrf") && init?.method === "POST") {
        csrfReads += 1;
        const lateOlderAttempt = csrfReads > 1;
        return json({
          csrf_token: lateOlderAttempt ? "csrf-older" : "csrf-current",
          user: lateOlderAttempt
            ? { email: "older@example.com", role: "user" }
            : { email: "current@example.com", role: "admin" },
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
    await waitForPlatformOverview();
    expect(sessionReads).toBeGreaterThanOrEqual(2);
    expect(olderSignal?.aborted).toBe(true);
    expect(resolveOlderSession).toBeDefined();

    await act(async () => {
      resolveOlderSession?.(
        await json({
          authenticated: true,
          user: { email: "older@example.com", role: "user" },
          raw_session_field: "late-raw-session-field",
        }),
      );
    });
    await waitFor(() => expect(csrfReads).toBeGreaterThanOrEqual(2));
    await openSettingsPage();
    expect(await screen.findByText("current@example.com")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("older@example.com");
    expect(document.body.textContent).not.toContain("late-raw-session-field");

    await userEvent.click(screen.getByRole("button", { name: "Выйти" }));
    expect(
      await screen.findByRole("heading", { name: "Вход" }),
    ).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("older@example.com");
  });

  it("reconciles an ambiguous logout without replaying the mutation", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let sessionReads = 0;
    let csrfReads = 0;
    let logoutCalls = 0;
    let timedOutLogoutSignal: AbortSignal | undefined;
    const logoutTokens: string[] = [];
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/auth/session")) {
        sessionReads += 1;
        return json({
          authenticated: true,
          user: { email: "logout@example.com", role: "admin" },
        });
      }
      if (url.endsWith("/api/auth/csrf") && init?.method === "POST") {
        csrfReads += 1;
        return json({
          csrf_token: csrfReads === 1 ? "csrf-initial" : "csrf-reconciled",
          user: { email: "logout@example.com", role: "admin" },
        });
      }
      if (url.endsWith("/api/auth/logout") && init?.method === "POST") {
        logoutCalls += 1;
        logoutTokens.push(String(new Headers(init.headers).get("x-csrf-token")));
        if (logoutCalls === 1) {
          timedOutLogoutSignal = init.signal;
          if (!timedOutLogoutSignal) {
            throw new Error("Logout signal is missing");
          }
          return new Promise<Response>((_resolve, reject) => {
            timedOutLogoutSignal?.addEventListener("abort", () =>
              reject(timedOutLogoutSignal?.reason),
            );
          });
        }
        return json({ ok: true });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 20_000 ? 1 : (delay as number),
          ...args,
        )) as typeof setTimeout);

    try {
      renderApp();
      await openSettingsPage();
      const logoutButton = screen.getByRole("button", { name: "Выйти" });
      fireEvent.click(logoutButton);
      fireEvent.click(logoutButton);

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Не удалось подтвердить выход",
      );
      expect(screen.getByText("logout@example.com")).toBeInTheDocument();
      expect(timedOutLogoutSignal?.aborted).toBe(true);
      expect(logoutCalls).toBe(1);
      expect(sessionReads).toBe(2);
      expect(csrfReads).toBe(2);

      await userEvent.click(screen.getByRole("button", { name: "Выйти" }));
      expect(
        await screen.findByRole("heading", { name: "Вход" }),
      ).toBeInTheDocument();
      expect(logoutCalls).toBe(2);
      expect(logoutTokens).toEqual(["csrf-initial", "csrf-reconciled"]);
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("accepts an authoritative anonymous reconciliation after malformed logout success", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let sessionReads = 0;
    let logoutCalls = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/auth/session")) {
        sessionReads += 1;
        if (sessionReads > 1) {
          return json({ detail: "raw-session-ended" }, false, 401);
        }
        return json({
          authenticated: true,
          user: { email: "logout@example.com", role: "user" },
        });
      }
      if (url.endsWith("/api/auth/csrf") && init?.method === "POST") {
        return json({
          csrf_token: "csrf-initial",
          user: { email: "logout@example.com", role: "user" },
        });
      }
      if (url.endsWith("/api/auth/logout") && init?.method === "POST") {
        logoutCalls += 1;
        return json({ ok: "raw-ok", raw_logout_field: "raw-logout-secret" });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openSettingsPage();
    await userEvent.click(screen.getByRole("button", { name: "Выйти" }));

    expect(
      await screen.findByRole("heading", { name: "Вход" }),
    ).toBeInTheDocument();
    expect(logoutCalls).toBe(1);
    expect(sessionReads).toBe(2);
    expect(document.body.textContent).not.toContain("raw-ok");
    expect(document.body.textContent).not.toContain("raw-logout-secret");
    expect(document.body.textContent).not.toContain("raw-session-ended");
  });

  it("aborts logout ownership on root-shell teardown and ignores late success", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let logoutSignal: AbortSignal | undefined;
    let resolveLogout: ((response: Response) => void) | undefined;
    let sessionReads = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/auth/session")) sessionReads += 1;
      if (url.endsWith("/api/auth/logout") && init?.method === "POST") {
        logoutSignal = init.signal;
        return new Promise<Response>((resolve) => {
          resolveLogout = resolve;
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    const rendered = render(<App />);
    await openSettingsPage();
    await userEvent.click(screen.getByRole("button", { name: "Выйти" }));
    await waitFor(() => expect(resolveLogout).toBeDefined());

    rendered.unmount();
    expect(logoutSignal?.aborted).toBe(true);
    await act(async () => resolveLogout?.(await json({ ok: true })));
    expect(sessionReads).toBe(1);
  });

  it("waits for confirmed Google connection before showing OAuth success", async () => {
    window.history.pushState(
      {},
      "",
      "/studio?keep=1&google_oauth=connected#safe",
    );
    const replaceSpy = vi.spyOn(window.history, "replaceState");
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let resolveConnection: (value: Response) => void = () => undefined;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/google/connection"))
        return new Promise((resolve) => {
          resolveConnection = resolve;
        });
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    expect(
      await screen.findByRole("heading", { name: "Подключения" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Google Drive подключён. Статус подключения обновлён.",
      ),
    ).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      "/api/google/connection",
      expect.objectContaining({ credentials: "same-origin" }),
    );
    expect(replaceSpy).toHaveBeenCalledWith(
      expect.anything(),
      "",
      "/studio?keep=1#safe",
    );
    expect(window.location.search).toBe("?keep=1");
    resolveConnection(
      await json({
        connected: true,
        status: "active",
        google_email: "safe.user@example.com",
        scopes: "openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly",
        connected_at: "2026-07-01T00:00:00",
        revoked_at: null,
        picker_configured: true,
        picker_scope_ready: true,
        picker_ready: true,
        reconnect_required: false,
      }),
    );
    expect(
      await screen.findByText(
        "Google Drive подключён. Статус подключения обновлён.",
      ),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("safe.user@example.com"),
    ).toBeInTheDocument();
    cleanup();
    renderApp();
    await waitForPlatformOverview();
    expect(
      screen.queryByText(
        "Google Drive подключён. Статус подключения обновлён.",
      ),
    ).not.toBeInTheDocument();
  });

  it("routes a safe maintenance OAuth callback to confirmed settings", async () => {
    window.history.pushState(
      {},
      "",
      "/?google_maintenance_oauth=connected&keep=1#safe",
    );

    renderApp();

    expect(
      await screen.findByRole("heading", { name: "Подключения" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(
        "Расширенный доступ для обслуживания подключён и проверен.",
      ),
    ).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      "/api/google/maintenance/connection",
      expect.objectContaining({ credentials: "same-origin" }),
    );
    expect(window.location.search).toBe("?keep=1");
    expect(window.location.hash).toBe("#safe");
  });

  it("does not show OAuth success when refreshed Google connection is disconnected", async () => {
    window.history.pushState({}, "", "/?google_oauth=connected");
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/google/connection"))
        return json(googleConnectionFixture());
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    expect(
      await screen.findByText("Google Drive не подключён"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Google Drive подключён. Статус подключения обновлён.",
      ),
    ).not.toBeInTheDocument();
  });

  it("does not show OAuth success when refreshed Google connection fails", async () => {
    window.history.pushState({}, "", "/?google_oauth=connected");
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/google/connection"))
        return json({ detail: "raw backend token detail" }, false, 500);
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    expect(
      await screen.findByText(
        "Не удалось загрузить статус Google Drive. Повторите попытку.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Google Drive подключён. Статус подключения обновлён.",
      ),
    ).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("raw backend token detail");
  });

  it.each([
    ["cancelled", "Подключение Google Drive отменено."],
    [
      "invalid_state",
      "Не удалось завершить подключение Google Drive. Запустите подключение ещё раз.",
    ],
    [
      "invalid_callback",
      "Не удалось завершить подключение Google Drive. Запустите подключение ещё раз.",
    ],
    [
      "exchange_failed",
      "Google Drive не подключён. Повторите авторизацию и подтвердите запрошенный доступ.",
    ],
    [
      "offline_access_missing",
      "Google Drive не подключён. Повторите авторизацию и подтвердите запрошенный доступ.",
    ],
  ])(
    "maps Google OAuth result %s to a safe message",
    async (result, message) => {
      window.history.pushState(
        {},
        "",
        `/?google_oauth=${result}&error_description=raw-secret-value`,
      );
      renderApp();
      expect(await screen.findByText(message)).toBeInTheDocument();
      expect(document.body.textContent).not.toContain("raw-secret-value");
    },
  );

  it("ignores unknown Google OAuth results safely", async () => {
    window.history.pushState(
      {},
      "",
      "/?google_oauth=raw-secret-value&keep=1#hash",
    );
    renderApp();
    await waitForPlatformOverview();
    expect(document.body.textContent).not.toContain("raw-secret-value");
    expect(window.location.search).toBe("?keep=1");
    expect(window.location.hash).toBe("#hash");
  });

  it("marks login fields with explicit browser autocomplete semantics", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string) =>
        url.endsWith("/api/auth/session")
          ? json({}, false, 401)
          : json({ bootstrap_required: false }),
    );
    renderApp();
    const email = await screen.findByLabelText("Email");
    const password = screen.getByLabelText("Пароль");
    expect(email).toHaveAttribute("autocomplete", "username");
    expect(password).toHaveAttribute("autocomplete", "current-password");
  });
  it("marks BYOK credential forms to avoid saved login autofill", async () => {
    renderApp();
    await openSettingsSection("Подключения");
    await screen.findByText(/Ключи провайдеров/);
    await userEvent.click(
      screen.getByRole("button", { name: "Добавить ключ" }),
    );
    await userEvent.click(
      screen.getAllByRole("button", { name: "Заменить" })[0],
    );
    const createKey = screen.getByPlaceholderText("Новый ключ");
    const replaceKey = screen.getByPlaceholderText("Новый ключ для замены");
    expect(createKey.closest("form")).toHaveAttribute("autocomplete", "off");
    expect(replaceKey.closest("form")).toHaveAttribute("autocomplete", "off");
    const label = screen.getByPlaceholderText("Метка");
    expect(label).toHaveAccessibleName("Метка ключа");
    expect(createKey).toHaveAccessibleName("Новый ключ");
    expect(label).toHaveAttribute("name", "credential_label");
    expect(label).toHaveAttribute("autocomplete", "off");
    expect(createKey).toHaveAttribute("name", "credential_raw_value");
    expect(replaceKey).toHaveAttribute(
      "name",
      "replacement_credential_raw_value",
    );
    expect(createKey).toHaveAttribute("autocomplete", "new-password");
    expect(replaceKey).toHaveAttribute("autocomplete", "new-password");
    expect(createKey).toHaveAttribute("type", "password");
    expect(replaceKey).toHaveAttribute("type", "password");
    expect(createKey).toHaveAttribute("spellcheck", "false");
    expect(replaceKey).toHaveAttribute("spellcheck", "false");
    expect(createKey).toHaveAttribute("data-1p-ignore", "true");
    expect(createKey).toHaveAttribute("data-lpignore", "true");
    expect(createKey).toHaveAttribute("data-bwignore", "true");
    expect(replaceKey).toHaveAttribute("data-1p-ignore", "true");
    expect(replaceKey).toHaveAttribute("data-lpignore", "true");
    expect(replaceKey).toHaveAttribute("data-bwignore", "true");
  });
  it("renders polished overview summary cards with separated labels and values", async () => {
    renderApp();
    const projectsCard = await screen.findByLabelText("Последние результаты");
    expect(within(projectsCard).getByText("Транскрибации и результаты")).toHaveClass(
      "summary-label",
    );
    await waitFor(() =>
      expect(within(projectsCard).getByText("Последних задач: 0")).toHaveClass(
        "summary-value",
      ),
    );
    const driveCard = screen.getByLabelText("Google Drive");
    expect(within(driveCard).getByText("Google Drive")).toHaveClass(
      "summary-label",
    );
    expect(within(driveCard).getByText("Подключён")).toHaveClass(
      "summary-value",
    );
    expect(screen.queryByText("ПРОЕКТЫ1")).not.toBeInTheDocument();
    expect(screen.queryByText("GOOGLE DRIVEПодключён")).not.toBeInTheDocument();
  });

  it("does not expose the internal project selector or lifecycle for one workspace", async () => {
    renderApp();
    await openProjectsPage();
    await screen.findByRole("tab", { name: "Обычная транскрибация" });
    expect(screen.queryByLabelText("Список проектов")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Редактировать" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Архивировать" }),
    ).not.toBeInTheDocument();
  });

  it("preserves multi-row associations while moving and deleting composer rows", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const folderNames: Record<string, string> = {
      "folder-alpha": "Folder Alpha",
      "folder-bravo": "Folder Bravo",
      "folder-charlie": "Folder Charlie",
    };
    const folderIds = ["folder-alpha", "folder-bravo", "folder-charlie"];
    vi.spyOn(googlePicker, "openGooglePicker").mockImplementation(
      async (kind) => {
        expect(kind).toBe("output-folder");
        const folderId = folderIds.shift() ?? "folder-fallback";
        return {
          action: "picked",
          docs: [{ id: folderId }],
        } as Awaited<ReturnType<typeof googlePicker.openGooglePicker>>;
      },
    );
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url.endsWith("/api/projects/p1/output-folders/google-picker/verify") &&
        init?.method === "POST"
      ) {
        const body = JSON.parse(String(init.body)) as { folder_id?: string };
        const folderId = body.folder_id ?? "folder-fallback";
        const name = folderNames[folderId] ?? "Folder Fallback";
        return json({
          id: folderId,
          name,
          web_view_url: `https://drive.example/folders/${folderId}`,
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const getComposerRows = () =>
      screen
        .getAllByRole("listitem")
        .filter((item) => item.classList.contains("composer-row"));
    const expectRow = async (
      position: number,
      sourceText: string,
      folderText: string,
      title: string,
    ) => {
      const row = getComposerRows()[position - 1];
      expect(row).toHaveAccessibleName(`Задача ${position}`);
      expect(within(row).getByText(`Задача ${position}`)).toBeInTheDocument();
      expect(row).toHaveTextContent(sourceText);
      expect(row).toHaveTextContent(folderText);
      await waitFor(() =>
        expect(
          within(row).getByLabelText(
            `Название документа задачи ${position}`,
          ),
        ).toHaveValue(title),
      );
    };

    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });

    await chooseExistingSource(1, "Лекция 1");
    await chooseResultFolder(1, "folder-one");
    await userEvent.type(
      screen.getByLabelText("Название документа задачи 1"),
      "Alpha title",
    );
    await userEvent.click(
      screen.getByRole("button", {
        name: "Выбрать папку результата для задачи 1",
      }),
    );
    await screen.findByText("Folder Alpha");

    await userEvent.click(
      screen.getByRole("button", { name: "Добавить задачу" }),
    );
    await chooseExistingSource(2, "local-temp");
    await userEvent.type(
      screen.getByLabelText("Название документа задачи 2"),
      "Bravo title",
    );
    await userEvent.click(
      screen.getByRole("button", {
        name: /папку результата для задачи 2/,
      }),
    );
    await screen.findByText("Folder Bravo");

    await userEvent.click(
      screen.getByRole("button", { name: "Добавить задачу" }),
    );
    const row3 = await screen.findByLabelText("Источник задачи 3");
    await userEvent.upload(
      within(row3).getByLabelText(
        "Выбрать файлы с устройства для задачи 3",
      ) as HTMLInputElement,
      new File(["charlie"], "charlie.ogg", { type: "audio/ogg" }),
    );
    await screen.findByText("Загружено файлов: 1.");
    await userEvent.type(
      screen.getByLabelText("Название документа задачи 3"),
      "Charlie title",
    );
    await userEvent.click(
      screen.getByRole("button", {
        name: /папку результата для задачи 3/,
      }),
    );
    await screen.findByText("Folder Charlie");

    await expectRow(1, "Лекция 1", "Folder Alpha", "Alpha title");
    await expectRow(2, "local-temp.ogg", "Folder Bravo", "Bravo title");
    await expectRow(3, "local-source-1.ogg", "Folder Charlie", "Charlie title");

    await userEvent.click(
      screen.getByRole("button", { name: "Поднять задачу 3" }),
    );

    await expectRow(1, "Лекция 1", "Folder Alpha", "Alpha title");
    await expectRow(2, "local-source-1.ogg", "Folder Charlie", "Charlie title");
    await expectRow(3, "local-temp.ogg", "Folder Bravo", "Bravo title");
    expect(
      screen.getByRole("button", { name: "Поднять задачу 1" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Поднять задачу 2" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Опустить задачу 2" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Удалить задачу 2" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Опустить задачу 3" }),
    ).toBeDisabled();

    await userEvent.click(
      screen.getByRole("button", { name: "Удалить задачу 2" }),
    );

    expect(getComposerRows()).toHaveLength(2);
    const rowTextAfterDelete = getComposerRows()
      .map((row) => row.textContent ?? "")
      .join(" ");
    expect(rowTextAfterDelete).not.toContain("Folder Charlie");
    expect(screen.queryByDisplayValue("Charlie title")).not.toBeInTheDocument();
    await expectRow(1, "Лекция 1", "Folder Alpha", "Alpha title");
    await expectRow(2, "local-temp.ogg", "Folder Bravo", "Bravo title");

    await userEvent.click(
      screen.getByRole("button", { name: "Удалить задачу 2" }),
    );

    expect(getComposerRows()).toHaveLength(1);
    await expectRow(1, "Лекция 1", "Folder Alpha", "Alpha title");
    expect(
      screen.queryByRole("button", { name: /Поднять задачу/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Опустить задачу/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Удалить задачу/ }),
    ).not.toBeInTheDocument();
    expect(
      baseFetch.mock.calls.some(
        ([url, init]) =>
          String(url).startsWith("/api/sources/") && init?.method === "DELETE",
      ),
    ).toBe(false);
  });

  it("keeps the final composer row and does not remove its project source", async () => {
    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    await chooseExistingSource(1, "Лекция 1");
    expect(
      screen.queryByRole("button", { name: "Удалить задачу 1" }),
    ).not.toBeInTheDocument();
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(
        ([url, init]) =>
          String(url).startsWith("/api/sources/") && init?.method === "DELETE",
      ),
    ).toBe(false);
    expect(screen.getAllByText(/Лекция 1/).length).toBeGreaterThan(0);
  });

  it("renders balanced Drive and device source cards with an accessible hidden file input", async () => {
    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    const row = await screen.findByLabelText("Источник задачи 1");
    expect(
      within(row).getByRole("button", { name: "Выбрать файлы Google Drive" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Добавить задачу для/ }),
    ).not.toBeInTheDocument();
    const input = within(row).getByLabelText(
      "Выбрать файлы с устройства для задачи 1",
    ) as HTMLInputElement;
    expect(input.tagName.toLowerCase()).toBe("input");
    expect(input).toHaveAttribute("type", "file");
    expect(input).toHaveAttribute("multiple");
    await waitFor(() => expect(input).toBeEnabled());
    expect(input).toHaveClass("visually-hidden");
    expect(input.closest(".file-picker-control")).not.toBeNull();
    expect(
      input.closest(".file-picker-control")?.querySelector("label"),
    ).toHaveTextContent("С устройства");
    expect(input).toHaveAttribute(
      "accept",
      "audio/*,video/*,application/ogg",
    );
    expect(document.body).not.toHaveTextContent(
      "https://upload.example/presigned",
    );
    const folderInput = within(row).getByLabelText(
      "Выбрать папку с устройства для задачи 1",
    ) as HTMLInputElement;
    expect(folderInput).toHaveAttribute("type", "file");
    expect(folderInput).toHaveAttribute("multiple");
    expect(folderInput).toHaveAttribute("webkitdirectory");
    expect(folderInput).toHaveAttribute("directory");
    expect(folderInput).toHaveClass("visually-hidden");
  });

  it("previews a local folder before upload and carries the shared target to appended rows", async () => {
    const folderFile = (path: string, type: string) => {
      const file = new File([path], path.split("/").at(-1) ?? "file", {
        type,
      });
      Object.defineProperty(file, "webkitRelativePath", {
        configurable: true,
        value: path,
      });
      return file;
    };

    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    await chooseResultFolder(1, "folder-shared");
    const row = await screen.findByLabelText("Источник задачи 1");
    const folderInput = within(row).getByLabelText(
      "Выбрать папку с устройства для задачи 1",
    ) as HTMLInputElement;

    await userEvent.upload(
      folderInput,
      [
        folderFile("Calls/one.ogg", "audio/ogg"),
        folderFile("Calls/nested/two.ogg", "audio/ogg"),
        folderFile("Calls/readme.txt", "text/plain"),
      ],
      { applyAccept: false },
    );

    const dialog = await screen.findByRole("dialog", {
      name: "Импортировать папку «Calls»?",
    });
    expect(dialog).toHaveTextContent("Всего найдено3");
    expect(dialog).toHaveTextContent("Будет загружено2");
    expect(dialog).toHaveTextContent("Будет пропущено1");
    expect(dialog).toHaveTextContent("Default folder");
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(
        ([url, init]) =>
          url === "/api/projects/p1/sources/local-upload/initiate" &&
          init?.method === "POST",
      ),
    ).toBe(false);

    await userEvent.click(
      within(dialog).getByRole("button", { name: "Импортировать 2" }),
    );
    await screen.findByText("Загружено файлов: 2.");
    expect(screen.getByLabelText("Источник задачи 1")).toHaveTextContent(
      "local-source-1.ogg",
    );
    expect(screen.getByLabelText("Источник задачи 2")).toHaveTextContent(
      "local-source-2.ogg",
    );
    expect(screen.getByLabelText("Задача 1")).toHaveTextContent(
      "Default folder",
    );
    expect(screen.getByLabelText("Задача 2")).toHaveTextContent(
      "Default folder",
    );
  });

  it("previews and explicitly applies a Google Drive source folder without trusting Picker metadata", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const previousFetch = fetchMock.getMockImplementation();
    const source = (id: string, name: string) => ({
      id,
      project_id: "p1",
      source_type: "google_drive",
      original_filename: name,
      mime_type: "audio/mpeg",
      size_bytes: 10,
      drive_file_url: `https://drive.google.com/file/d/${id}/view`,
      upload_status: "uploaded",
      uploaded_at: "2026-08-23T10:00:00Z",
      source_created_at: "2026-08-20T10:00:00Z",
      source_created_at_provenance: "google_drive_created_time",
      expires_at: null,
      deleted_at: null,
      delete_reason: null,
      created_at: "2026-08-23T10:00:00Z",
      updated_at: "2026-08-23T10:00:00Z",
    });
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url === "/api/projects/p1/sources/google-folder/preview" &&
        init?.method === "POST"
      ) {
        expect(JSON.parse(String(init.body))).toEqual({
          folder_id: "folder-source",
        });
        expect(String(init.body)).not.toContain("Picker Folder Name");
        expect(String(init.body)).not.toContain("ya29");
        return json({
          folder: { id: "folder-source", name: "Verified Calls" },
          total_file_count: 3,
          folder_count: 2,
          supported_count: 2,
          skipped_count: 1,
          accepted: [
            {
              id: "drive-folder-a",
              name: "a.mp3",
              mime_type: "audio/mpeg",
              size_bytes: 10,
              created_time: "2026-08-20T10:00:00Z",
              relative_path: "Verified Calls/a.mp3",
            },
            {
              id: "drive-folder-b",
              name: "b.mp3",
              mime_type: "audio/mpeg",
              size_bytes: 10,
              created_time: "2026-08-20T10:00:00Z",
              relative_path: "Verified Calls/Nested/b.mp3",
            },
          ],
          skipped: [
            {
              relative_path: "Verified Calls/readme.txt",
              reason: "unsupported",
            },
          ],
          blocker: null,
          complete: true,
          preview_token: "a".repeat(64),
        });
      }
      if (
        url === "/api/projects/p1/sources/google-folder/apply" &&
        init?.method === "POST"
      ) {
        expect(JSON.parse(String(init.body))).toEqual({
          folder_id: "folder-source",
          preview_token: "a".repeat(64),
        });
        return json({
          sources: [
            source("drive-folder-source-a", "a.mp3"),
            source("drive-folder-source-b", "b.mp3"),
          ],
        });
      }
      return previousFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    const picker = installFakeGooglePicker();
    await userEvent.click(
      screen.getByRole("button", {
        name: "Выбрать папку-источник Google Drive для задачи 1",
      }),
    );
    await picker.loadScript();
    await picker.waitForCallback();
    expect(picker.viewIds).toEqual([]);
    expect(picker.selectFolderEnabled).toEqual([]);
    expect(picker.builderCalls).toEqual([]);
    picker.trigger({
      action: "picked",
      docs: [
        {
          id: "folder-source",
          name: "Picker Folder Name",
          mimeType: "application/vnd.google-apps.folder",
          token: "ya29.raw-picker-token",
        },
      ],
    });

    const dialog = await screen.findByRole("dialog", {
      name: "Импортировать папку «Verified Calls»?",
    });
    expect(dialog).toHaveTextContent("Будет загружено2");
    expect(dialog).toHaveTextContent("Будет пропущено1");
    expect(dialog).toHaveTextContent("не выбрана");
    expect(dialog).not.toHaveTextContent("Picker Folder Name");
    expect(
      fetchMock.mock.calls.filter(
        ([url]) => url === "/api/projects/p1/sources/google-folder/apply",
      ),
    ).toHaveLength(0);

    await userEvent.click(
      within(dialog).getByRole("button", { name: "Импортировать 2" }),
    );
    await screen.findByText("Добавлено файлов из папки: 2.");
    expect(screen.getByLabelText("Задача 1")).toHaveTextContent("a.mp3");
    expect(screen.getByLabelText("Задача 2")).toHaveTextContent("b.mp3");
    const fragmentationToggles = screen.getAllByRole("checkbox", {
      name: /Разделить файл на фрагменты/,
    });
    expect(fragmentationToggles).toHaveLength(2);
    for (const checkbox of fragmentationToggles) {
      expect(checkbox).not.toBeChecked();
    }
    expect(
      screen.queryByRole("checkbox", { name: "До конца файла" }),
    ).not.toBeInTheDocument();

    await chooseResultFolder(1, "folder-shared", "Shared results");
    expect(screen.getByLabelText("Задача 1")).toHaveTextContent(
      "Shared results",
    );
    expect(screen.getByLabelText("Задача 2")).toHaveTextContent(
      "Shared results",
    );

    await chooseResultFolder(2, "folder-override", "Override results");
    expect(screen.getByLabelText("Задача 1")).toHaveTextContent(
      "Shared results",
    );
    expect(screen.getByLabelText("Задача 1")).not.toHaveTextContent(
      "Override results",
    );
    expect(screen.getByLabelText("Задача 2")).toHaveTextContent(
      "Override results",
    );
    expect(
      fetchMock.mock.calls.filter(
        ([url]) => url === "/api/projects/p1/sources/google-folder/apply",
      ),
    ).toHaveLength(1);
    expect(document.body.textContent).not.toContain("ya29.raw-picker-token");
  });

  it("does not replay an ambiguous Google Drive folder apply", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const previousFetch = fetchMock.getMockImplementation();
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url === "/api/projects/p1/sources/google-folder/preview" &&
        init?.method === "POST"
      ) {
        return json({
          folder: { id: "folder-source", name: "Calls" },
          total_file_count: 1,
          folder_count: 1,
          supported_count: 1,
          skipped_count: 0,
          accepted: [
            {
              id: "drive-folder-a",
              name: "a.mp3",
              mime_type: "audio/mpeg",
              size_bytes: 10,
              created_time: "2026-08-20T10:00:00Z",
              relative_path: "Calls/a.mp3",
            },
          ],
          skipped: [],
          blocker: null,
          complete: true,
          preview_token: "b".repeat(64),
        });
      }
      if (
        url === "/api/projects/p1/sources/google-folder/apply" &&
        init?.method === "POST"
      ) {
        return json({ detail: "raw-provider-body" }, false, 502);
      }
      return previousFetch?.(url, init) ?? json({ ok: true });
    });

    const picker = installFakeGooglePicker();
    renderApp();
    await openProjectsPage();
    await userEvent.click(
      screen.getByRole("button", {
        name: "Выбрать папку-источник Google Drive для задачи 1",
      }),
    );
    await picker.loadScript();
    await picker.waitForCallback();
    picker.trigger({ action: "picked", docs: [{ id: "folder-source" }] });
    const dialog = await screen.findByRole("dialog", {
      name: "Импортировать папку «Calls»?",
    });
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Импортировать 1" }),
    );

    expect(
      await screen.findByText(
        "Studio не подтвердила добавление файлов. Список обновлён; проверьте его и только затем выберите папку снова.",
      ),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(
        ([url]) => url === "/api/projects/p1/sources/google-folder/apply",
      ),
    ).toHaveLength(1);
    expect(document.body.textContent).not.toContain("raw-provider-body");
  });

  it("shows an actionable read-only preview when Drive folder descendants are not visible", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const previousFetch = fetchMock.getMockImplementation();
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url === "/api/projects/p1/sources/google-folder/preview" &&
        init?.method === "POST"
      ) {
        return json({
          folder: { id: "folder-source", name: "Calls" },
          total_file_count: 0,
          folder_count: 1,
          supported_count: 0,
          skipped_count: 0,
          accepted: [],
          skipped: [],
          blocker: "empty",
          complete: true,
          preview_token: null,
        });
      }
      return previousFetch?.(url, init) ?? json({ ok: true });
    });

    const picker = installFakeGooglePicker();
    renderApp();
    await openProjectsPage();
    await userEvent.click(
      screen.getByRole("button", {
        name: "Выбрать папку-источник Google Drive для задачи 1",
      }),
    );
    await picker.loadScript();
    await picker.waitForCallback();
    picker.trigger({ action: "picked", docs: [{ id: "folder-source" }] });

    const dialog = await screen.findByRole("dialog", {
      name: "Папка «Calls» не готова к импорту",
    });
    expect(dialog).toHaveTextContent("Всего найдено0");
    expect(dialog).toHaveTextContent("Будет загружено0");
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "текущий узкий доступ Google Drive",
    );
    expect(
      within(dialog).getByRole("button", { name: "Импортировать 0" }),
    ).toBeDisabled();
    expect(
      fetchMock.mock.calls.filter(
        ([url]) => url === "/api/projects/p1/sources/google-folder/apply",
      ),
    ).toHaveLength(0);
  });

  it("local multi-file selection preserves successful rows through ordered batch creation", async () => {
    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    const row = await screen.findByLabelText("Источник задачи 1");
    const input = within(row).getByLabelText(
      "Выбрать файлы с устройства для задачи 1",
    ) as HTMLInputElement;

    await userEvent.upload(
      input,
      [
        new File(["one"], "one.ogg", { type: "audio/ogg" }),
        new File(["bad"], "bad.exe", { type: "application/x-msdownload" }),
        new File(["two"], "two.ogg", { type: "audio/ogg" }),
      ],
      { applyAccept: false },
    );

    await screen.findByText("Загружено файлов: 2.");
    expect(screen.getByLabelText("Источник задачи 1")).toHaveTextContent(
      "local-source-1.ogg",
    );
    expect(screen.getByLabelText("Источник задачи 1")).toHaveTextContent(
      "Временная копия хранится до:",
    );
    expect(screen.getByLabelText("Источник задачи 2")).toHaveTextContent(
      "local-source-2.ogg",
    );
    expect(
      screen.getByText(
        /bad\.exe: тип файла не поддерживается текущими правилами\./,
      ),
    ).toBeInTheDocument();
    const uploadPuts = (
      fetch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.filter(
      ([url, init]) =>
        String(url).startsWith("https://upload.example/presigned") &&
        init?.method === "PUT",
    );
    expect(uploadPuts).toHaveLength(2);
    for (const [, init] of uploadPuts) {
      expect(init).toEqual(
        expect.objectContaining({
          credentials: "omit",
          headers: { "Content-Type": "audio/ogg" },
          body: expect.any(File),
        }),
      );
      expect(init).not.toHaveProperty("duplex");
    }
    expect(
      screen.getByRole("button", {
        name: "Выбрать папку результата для задачи 1",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Выбрать папку результата для задачи 2",
      }),
    ).toBeInTheDocument();
    await chooseResultFolder(1, "folder-local-1");
    await chooseResultFolder(2, "folder-local-2");
    await reviewAndConfirmBatch();
    const batchCall = await waitFor(() => {
      const call = (
        fetch as unknown as ReturnType<typeof vi.fn>
      ).mock.calls.find(
        ([url, init]) =>
          url === "/api/projects/p1/jobs/batch" && init?.method === "POST",
      );
      expect(call).toBeTruthy();
      return call;
    });
    expect(JSON.parse(String(batchCall?.[1]?.body)).items).toMatchObject([
      {
        source_id: "local-source-1",
        output_folder_id: "folder-local-1",
      },
      {
        source_id: "local-source-2",
        output_folder_id: "folder-local-2",
      },
    ]);
  });

  it("bounds ambiguous local upload initiation without replaying the POST", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const initiationSignals: AbortSignal[] = [];
    let initiationCalls = 0;
    let sourceReadsAfterInitiation = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url === "/api/projects/p1/sources" &&
        !init?.method &&
        initiationCalls > 0
      ) {
        sourceReadsAfterInitiation += 1;
      }
      if (
        url === "/api/projects/p1/sources/local-upload/initiate" &&
        init?.method === "POST"
      ) {
        initiationCalls += 1;
        const signal = init.signal;
        if (!signal) throw new Error("upload initiation signal is missing");
        initiationSignals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 20_000 ? 1 : (delay as number),
          ...args,
        )) as typeof setTimeout);
    try {
      renderApp();
      await openProjectsPage();
      const row = await screen.findByLabelText("Источник задачи 1");
      const input = within(row).getByLabelText(
        "Выбрать файлы с устройства для задачи 1",
      ) as HTMLInputElement;

      await userEvent.upload(
        input,
        new File(["stalled"], "initiation-timeout.ogg", {
          type: "audio/ogg",
        }),
      );

      expect(
        await within(row).findByText(
          /Studio не подтвердила подготовку загрузки\. Список файлов обновлён/,
        ),
      ).toBeInTheDocument();
      expect(initiationSignals).toHaveLength(1);
      expect(initiationSignals[0]?.aborted).toBe(true);
      expect(initiationCalls).toBe(1);
      await waitFor(() => expect(sourceReadsAfterInitiation).toBeGreaterThan(0));
      expect(input).toBeEnabled();
      expect(
        baseFetch.mock.calls.filter(
          ([url, init]) =>
            String(url).startsWith("https://upload.example/presigned") &&
            init?.method === "PUT",
        ),
      ).toHaveLength(0);
      expect(
        baseFetch.mock.calls.filter(
          ([url, init]) =>
            String(url).endsWith("/local-upload/complete") &&
            init?.method === "POST",
        ),
      ).toHaveLength(0);
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("fails closed after an ambiguous initiation response without replay", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let initiationCalls = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url === "/api/projects/p1/sources/local-upload/initiate" &&
        init?.method === "POST"
      ) {
        initiationCalls += 1;
        expect(init.signal).toBeInstanceOf(AbortSignal);
        return json({ detail: "raw private initiation failure" }, false, 500);
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    await openProjectsPage();
    const row = await screen.findByLabelText("Источник задачи 1");
    const input = within(row).getByLabelText(
      "Выбрать файлы с устройства для задачи 1",
    ) as HTMLInputElement;

    await userEvent.upload(
      input,
      new File(["ambiguous"], "initiation-500.ogg", { type: "audio/ogg" }),
    );

    expect(
      await within(row).findByText(
        /Studio не подтвердила подготовку загрузки\. Список файлов обновлён/,
      ),
    ).toBeInTheDocument();
    expect(initiationCalls).toBe(1);
    expect(input).toBeEnabled();
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          String(url).startsWith("https://upload.example/presigned") &&
          init?.method === "PUT",
      ),
    ).toHaveLength(0);
    expect(document.body).not.toHaveTextContent(
      "raw private initiation failure",
    );
  });
  it("bounds a stalled local PUT and recovers without repeating object upload", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const putSignals: AbortSignal[] = [];
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        String(url).startsWith("https://upload.example/presigned") &&
        init?.method === "PUT"
      ) {
        const signal = init.signal;
        if (!signal) throw new Error("upload PUT signal is missing");
        putSignals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason));
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 600_000 ? 1 : (delay as number),
          ...args,
        )) as typeof setTimeout);
    try {
      renderApp();
      await openProjectsPage();
      const row = await screen.findByLabelText("Источник задачи 1");
      const input = within(row).getByLabelText(
        "Выбрать файлы с устройства для задачи 1",
      ) as HTMLInputElement;

      await userEvent.upload(
        input,
        new File(["stalled"], "put-timeout.ogg", { type: "audio/ogg" }),
      );

      await within(row).findByText("Загружено файлов: 1.");
      expect(putSignals).toHaveLength(1);
      expect(putSignals[0]?.aborted).toBe(true);
      expect(
        baseFetch.mock.calls.filter(
          ([url, init]) =>
            url ===
              "/api/projects/p1/sources/local-upload/initiate" &&
            init?.method === "POST",
        ),
      ).toHaveLength(1);
      expect(
        baseFetch.mock.calls.filter(
          ([url, init]) =>
            String(url).startsWith("https://upload.example/presigned") &&
            init?.method === "PUT",
        ),
      ).toHaveLength(1);
      expect(
        baseFetch.mock.calls.filter(
          ([url, init]) =>
            String(url).endsWith("/local-upload/complete") &&
            init?.method === "POST",
        ),
      ).toHaveLength(1);
      expect(row).toHaveTextContent("local-source-1.ogg");
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("recovers an ambiguous local PUT through completion without creating a second source", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let rejectedPut = false;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        String(url).startsWith("https://upload.example/presigned") &&
        init?.method === "PUT" &&
        !rejectedPut
      ) {
        rejectedPut = true;
        return Promise.reject(new TypeError("synthetic ambiguous PUT"));
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    await openProjectsPage();
    const row = await screen.findByLabelText("Источник задачи 1");
    const input = within(row).getByLabelText(
      "Выбрать файлы с устройства для задачи 1",
    ) as HTMLInputElement;

    await userEvent.upload(
      input,
      new File(["recover"], "recover.ogg", { type: "audio/ogg" }),
    );

    await within(row).findByText("Загружено файлов: 1.");
    expect(row).toHaveTextContent("local-source-1.ogg");
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          String(url).endsWith(
            "/api/projects/p1/sources/local-upload/initiate",
          ) && init?.method === "POST",
      ),
    ).toHaveLength(1);
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          String(url).startsWith("https://upload.example/presigned") &&
          init?.method === "PUT",
      ),
    ).toHaveLength(1);
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          String(url).endsWith("/local-upload/complete") &&
          init?.method === "POST",
      ),
    ).toHaveLength(1);
  });

  it("accepts an authoritative uploaded source without replaying completion", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let completionCalls = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url === "/api/sources/local-source-1" &&
        !init?.method &&
        completionCalls === 1
      ) {
        return json(
            {
              id: "local-source-1",
              project_id: "p1",
              source_type: "local_upload",
              original_filename: "local-source-1.ogg",
              mime_type: "audio/ogg",
              size_bytes: 7,
              drive_file_id: null,
              drive_file_url: null,
              upload_status: "uploaded",
              uploaded_at: "2099-01-01T00:00:00Z",
              expires_at: "2099-01-02T00:00:00Z",
              deleted_at: null,
              delete_reason: null,
              created_at: "2026-07-01T00:00:00Z",
              updated_at: "2026-07-01T00:00:00Z",
            },
        );
      }
      if (
        String(url).endsWith("/local-upload/complete") &&
        init?.method === "POST"
      ) {
        completionCalls += 1;
        return Promise.reject(new TypeError("synthetic lost response"));
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();
    const row = await screen.findByLabelText("Источник задачи 1");
    const input = within(row).getByLabelText(
      "Выбрать файлы с устройства для задачи 1",
    ) as HTMLInputElement;
    await userEvent.upload(
      input,
      new File(["recover"], "completed-reconcile.ogg", {
        type: "audio/ogg",
      }),
    );

    await within(row).findByText("Загружено файлов: 1.");
    expect(completionCalls).toBe(1);
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          String(url).endsWith(
            "/api/projects/p1/sources/local-upload/initiate",
          ) && init?.method === "POST",
      ),
    ).toHaveLength(1);
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          String(url).startsWith("https://upload.example/presigned") &&
          init?.method === "PUT",
      ),
    ).toHaveLength(1);
    expect(document.body).not.toHaveTextContent("synthetic lost response");
  });
  it("retries local upload completion without repeating initiation or PUT", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let rejectedCompletion = false;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url === "/api/sources/local-source-1" &&
        !init?.method &&
        rejectedCompletion
      ) {
        return json(
            {
              id: "local-source-1",
              project_id: "p1",
              source_type: "local_upload",
              upload_status: "pending",
              mime_type: "audio/ogg",
              size_bytes: 7,
              deleted_at: null,
            },
        );
      }      if (
        String(url).endsWith("/local-upload/complete") &&
        init?.method === "POST" &&
        !rejectedCompletion
      ) {
        rejectedCompletion = true;
        return Promise.reject(new TypeError("synthetic lost completion"));
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    await openProjectsPage();
    const row = await screen.findByLabelText("Источник задачи 1");
    const input = within(row).getByLabelText(
      "Выбрать файлы с устройства для задачи 1",
    ) as HTMLInputElement;

    await userEvent.upload(
      input,
      new File(["recover"], "complete-retry.ogg", { type: "audio/ogg" }),
    );

    await within(row).findByText("Загружено файлов: 1.");
    expect(
      baseFetch.mock.calls.some(
        ([url, init]) =>
          url === "/api/sources/local-source-1" &&
          init?.cache === "no-store",
      ),
    ).toBe(true);
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          String(url).endsWith(
            "/api/projects/p1/sources/local-upload/initiate",
          ) && init?.method === "POST",
      ),
    ).toHaveLength(1);
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          String(url).startsWith("https://upload.example/presigned") &&
          init?.method === "PUT",
      ),
    ).toHaveLength(1);
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          String(url).endsWith("/local-upload/complete") &&
          init?.method === "POST",
      ),
    ).toHaveLength(2);
  });

  it("bounds stalled upload completion and replays only after pending reconciliation", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const completionSignals: AbortSignal[] = [];
    let completionCalls = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        url === "/api/sources/local-source-1" &&
        !init?.method &&
        completionCalls === 1
      ) {
        return json(
            {
              id: "local-source-1",
              project_id: "p1",
              source_type: "local_upload",
              upload_status: "pending",
              mime_type: "audio/ogg",
              size_bytes: 7,
              deleted_at: null,
            },
        );
      }
      if (
        String(url).endsWith("/local-upload/complete") &&
        init?.method === "POST"
      ) {
        completionCalls += 1;
        if (completionCalls === 1) {
          const signal = init.signal;
          if (!signal) throw new Error("upload completion signal is missing");
          completionSignals.push(signal);
          return new Promise<Response>((_resolve, reject) => {
            signal.addEventListener("abort", () => reject(signal.reason));
          });
        }
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 20_000 ? 1 : (delay as number),
          ...args,
        )) as typeof setTimeout);
    try {
      renderApp();
      await openProjectsPage();
      const row = await screen.findByLabelText("Источник задачи 1");
      const input = within(row).getByLabelText(
        "Выбрать файлы с устройства для задачи 1",
      ) as HTMLInputElement;

      await userEvent.upload(
        input,
        new File(["recover"], "complete-timeout.ogg", { type: "audio/ogg" }),
      );

      await within(row).findByText("Загружено файлов: 1.");
      expect(completionSignals).toHaveLength(1);
      expect(completionSignals[0]?.aborted).toBe(true);
      expect(completionCalls).toBe(2);
      expect(
        baseFetch.mock.calls.filter(
          ([url, init]) =>
            String(url).endsWith(
              "/api/projects/p1/sources/local-upload/initiate",
            ) && init?.method === "POST",
        ),
      ).toHaveLength(1);
      expect(
        baseFetch.mock.calls.filter(
          ([url, init]) =>
            String(url).startsWith("https://upload.example/presigned") &&
            init?.method === "PUT",
        ),
      ).toHaveLength(1);
      expect(
        baseFetch.mock.calls.some(
          ([url, init]) =>
            url === "/api/sources/local-source-1" &&
            init?.cache === "no-store",
        ),
      ).toBe(true);
    } finally {
      timeoutSpy.mockRestore();
    }
  });
  it("blocks a second local selection while the row upload is still running", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let releasePut: (() => void) | undefined;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        String(url).startsWith("https://upload.example/presigned") &&
        init?.method === "PUT"
      )
        return new Promise<Response>((resolve) => {
          releasePut = () => resolve(new Response(null, { status: 200 }));
        });
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    await openProjectsPage();
    const row = await screen.findByLabelText("Источник задачи 1");
    const input = within(row).getByLabelText(
      "Выбрать файлы с устройства для задачи 1",
    ) as HTMLInputElement;

    await userEvent.upload(
      input,
      new File(["first"], "first.ogg", { type: "audio/ogg" }),
    );
    await waitFor(() => expect(input).toBeDisabled());
    fireEvent.change(input, {
      target: {
        files: [new File(["second"], "second.ogg", { type: "audio/ogg" })],
      },
    });
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          String(url).endsWith(
            "/api/projects/p1/sources/local-upload/initiate",
          ) && init?.method === "POST",
      ),
    ).toHaveLength(1);

    act(() => releasePut?.());
    await within(row).findByText("Загружено файлов: 1.");
    await waitFor(() => expect(input).toBeEnabled());
    expect(row).toHaveTextContent("local-source-1.ogg");
    expect(row).not.toHaveTextContent("local-source-2.ogg");
  });

  it("reports an explicit storage PUT rejection without leaking upload identity", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        String(url).startsWith("https://upload.example/presigned") &&
        init?.method === "PUT"
      )
        return json({ private: "raw-storage-body" }, false, 400);
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    await openProjectsPage();
    const row = await screen.findByLabelText("Источник задачи 1");
    const input = within(row).getByLabelText(
      "Выбрать файлы с устройства для задачи 1",
    ) as HTMLInputElement;

    await userEvent.upload(
      input,
      new File(["rejected"], "private-filename.ogg", { type: "audio/ogg" }),
    );

    expect(
      await within(row).findByText(
        /Хранилище отклонило загрузку\. Обновите страницу и повторите/,
      ),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        baseFetch.mock.calls.some(([url]) =>
          String(url).endsWith("/api/diagnostics/pwa-events"),
        ),
      ).toBe(true),
    );
    const event = postedPwaEventsFrom(baseFetch).find(
      (candidate) => candidate.event_code === "PWA_API_REQUEST_FAILED",
    );
    expect(event).toMatchObject({
      event_code: "PWA_API_REQUEST_FAILED",
      metadata: {
        boundary: "api_request",
        error_code: "api_request_failed",
        endpoint_group: "sources",
        http_status_category: "4xx",
        retryable: false,
      },
    });
    expect(JSON.stringify(event)).not.toContain("private-filename.ogg");
    expect(JSON.stringify(event)).not.toContain("presigned");
    expect(JSON.stringify(event)).not.toContain("raw-storage-body");
    expect(
      baseFetch.mock.calls.some(
        ([url, init]) =>
          String(url).endsWith("/local-upload/complete") &&
          init?.method === "POST",
      ),
    ).toBe(false);
  });

  it("refuses an unsafe upload capability before contacting its origin", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        String(url).endsWith(
          "/api/projects/p1/sources/local-upload/initiate",
        ) &&
        init?.method === "POST"
      )
        return json({
          source_id: "unsafe-source",
          upload: {
            method: "POST",
            url: "http://unsafe-upload.example/private",
            headers: {
              "Content-Type": "audio/ogg",
              Authorization: "private",
            },
            expires_in: 3600,
          },
        });
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    await openProjectsPage();
    const row = await screen.findByLabelText("Источник задачи 1");
    const input = within(row).getByLabelText(
      "Выбрать файлы с устройства для задачи 1",
    ) as HTMLInputElement;

    await userEvent.upload(
      input,
      new File(["unsafe"], "unsafe.ogg", { type: "audio/ogg" }),
    );

    expect(
      await within(row).findByText(
        /Studio не смогла безопасно подтвердить загрузку/,
      ),
    ).toBeInTheDocument();
    expect(
      baseFetch.mock.calls.some(([url]) =>
        String(url).startsWith("http://unsafe-upload.example"),
      ),
    ).toBe(false);
    expect(
      baseFetch.mock.calls.some(
        ([url, init]) =>
          String(url).endsWith("/local-upload/complete") &&
          init?.method === "POST",
      ),
    ).toBe(false);
    expect(document.body.textContent).not.toContain("Authorization");
    expect(document.body.textContent).not.toContain("private");
  });

  it("refuses a mismatched upload completion before adding it to a task row", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (
        String(url).endsWith("/local-upload/complete") &&
        init?.method === "POST"
      )
        return json({
          id: "different-source",
          project_id: "p1",
          source_type: "local_upload",
          original_filename: "different.ogg",
          mime_type: "audio/ogg",
          size_bytes: 8,
          drive_file_url: null,
          upload_status: "uploaded",
          uploaded_at: "2099-01-01T00:00:00Z",
          expires_at: "2099-01-02T00:00:00Z",
          deleted_at: null,
          delete_reason: null,
          created_at: "2026-07-01T00:00:00Z",
          updated_at: "2026-07-01T00:00:00Z",
        });
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    await openProjectsPage();
    const row = await screen.findByLabelText("Источник задачи 1");
    const input = within(row).getByLabelText(
      "Выбрать файлы с устройства для задачи 1",
    ) as HTMLInputElement;

    await userEvent.upload(
      input,
      new File(["mismatch"], "mismatch.ogg", { type: "audio/ogg" }),
    );

    expect(
      await within(row).findByText(
        /Studio вернула несогласованное подтверждение загрузки/,
      ),
    ).toBeInTheDocument();
    expect(row).not.toHaveTextContent("different.ogg");
    expect(
      baseFetch.mock.calls.filter(
        ([url, init]) =>
          String(url).endsWith("/local-upload/complete") &&
          init?.method === "POST",
      ),
    ).toHaveLength(1);
  });

  it("bounds and retries Preparation prerequisite reads independently", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    const credentialSignals: AbortSignal[] = [];
    const policySignals: AbortSignal[] = [];
    let credentialReads = 0;
    let policyReads = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/credentials") && !init?.method) {
        credentialReads += 1;
        if (credentialReads === 2) {
          const signal = init.signal;
          if (!signal) throw new Error("Preparation credential signal is missing");
          credentialSignals.push(signal);
          return new Promise<Response>((_resolve, reject) => {
            signal.addEventListener("abort", () => reject(signal.reason));
          });
        }
      }
      if (url.endsWith("/api/sources/upload-policy") && !init?.method) {
        policyReads += 1;
        if (policyReads === 1) {
          const signal = init.signal;
          if (!signal) throw new Error("Upload-policy signal is missing");
          policySignals.push(signal);
          return new Promise<Response>((_resolve, reject) => {
            signal.addEventListener("abort", () => reject(signal.reason));
          });
        }
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 15_000 ? 1 : (delay as number),
          ...args,
        )) as typeof setTimeout);

    try {
      renderApp();
      await openProjectsPage();
      await screen.findByRole("form", { name: "Композитор пакетных задач" });
      expect(
        await screen.findByRole("button", {
          name: "Повторить загрузку профилей",
        }),
      ).toBeInTheDocument();
      expect(
        await screen.findByText(/Не удалось загрузить правила локальной загрузки/),
      ).toBeInTheDocument();
      expect(credentialSignals).toHaveLength(1);
      expect(policySignals).toHaveLength(1);
      expect(credentialSignals[0]?.aborted).toBe(true);
      expect(policySignals[0]?.aborted).toBe(true);
      const credentialReadsBeforeRetry = credentialReads;
      const policyReadsBeforeRetry = policyReads;

      await userEvent.click(
        screen.getByRole("button", {
          name: "Повторить загрузку профилей",
        }),
      );
      await userEvent.click(
        screen.getByRole("button", { name: "Проверить ещё раз" }),
      );

      expect(await screen.findByText("Профиль подключения выбран")).toBeInTheDocument();
      const row = await screen.findByLabelText("Источник задачи 1");
      await waitFor(() =>
        expect(
          within(row).getByLabelText(
            "Выбрать файлы с устройства для задачи 1",
          ),
        ).toBeEnabled(),
      );
      expect(credentialReads).toBe(credentialReadsBeforeRetry + 1);
      expect(policyReads).toBe(policyReadsBeforeRetry + 1);
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("rejects malformed Preparation prerequisite responses without raw fields", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let credentialReads = 0;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/credentials") && !init?.method) {
        credentialReads += 1;
        if (credentialReads === 2) {
          return json({
            credentials: [
              credentialFixture({
                id: "duplicate-preparation",
                label: "raw-credential-field",
              }),
              credentialFixture({ id: "duplicate-preparation" }),
            ],
          });
        }
      }
      if (url.endsWith("/api/sources/upload-policy") && !init?.method) {
        return json({
          local_upload_enabled: true,
          max_upload_bytes: "raw-policy-field",
          supported_mime_prefixes: ["audio/"],
          supported_mime_types: [],
        });
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    expect(
      await screen.findByRole("button", {
        name: "Повторить загрузку профилей",
      }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/Не удалось загрузить правила локальной загрузки/),
    ).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("raw-credential-field");
    expect(document.body.textContent).not.toContain("raw-policy-field");
    const row = await screen.findByLabelText("Источник задачи 1");
    expect(
      within(row).getByLabelText(
        "Выбрать файлы с устройства для задачи 1",
      ),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /Проверить задачи/ }),
    ).toBeDisabled();
  });

  it("aborts and ignores late Preparation prerequisites across project remounts", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    let credentialReads = 0;
    let policyReads = 0;
    let olderCredentialSignal: AbortSignal | undefined;
    let olderPolicySignal: AbortSignal | undefined;
    let resolveOlderCredentials: ((response: Response) => void) | undefined;
    let resolveOlderPolicy: ((response: Response) => void) | undefined;
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/projects") && !init?.method) {
        return json({
          projects: [
            projectFixture({
              id: "p1",
              title: "Research calls",
              created_at: "2026-07-01T00:00:00Z",
              updated_at: "2026-07-01T00:00:00Z",
            }),
            projectFixture({
              id: "p2",
              title: "Project Two",
              created_at: "2026-07-02T00:00:00Z",
              updated_at: "2026-07-02T00:00:00Z",
            }),
          ],
        });
      }
      if (
        (url.endsWith("/api/projects/p2/sources") ||
          url.endsWith("/api/projects/p2/jobs")) &&
        !init?.method
      ) {
        return json(url.endsWith("/sources") ? { sources: [] } : { jobs: [] });
      }
      if (url.endsWith("/api/credentials") && !init?.method) {
        credentialReads += 1;
        if (credentialReads === 2) {
          olderCredentialSignal = init.signal;
          return new Promise<Response>((resolve) => {
            resolveOlderCredentials = resolve;
          });
        }
        if (credentialReads > 2) {
          return json({
            credentials: [
              credentialFixture({
                id: `current-${credentialReads}`,
                label: `Current ${credentialReads}`,
              }),
            ],
          });
        }
      }
      if (url.endsWith("/api/sources/upload-policy") && !init?.method) {
        policyReads += 1;
        if (policyReads === 1) {
          olderPolicySignal = init.signal;
          return new Promise<Response>((resolve) => {
            resolveOlderPolicy = resolve;
          });
        }
      }
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });

    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    await waitFor(() => expect(resolveOlderCredentials).toBeDefined());
    await waitFor(() => expect(resolveOlderPolicy).toBeDefined());

    await userEvent.click(
      screen.getByRole("button", { name: /Project Two .*02\.07\.2026/ }),
    );
    expect(olderCredentialSignal?.aborted).toBe(true);
    expect(olderPolicySignal?.aborted).toBe(true);
    expect(await screen.findByText("Профиль подключения выбран")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /Research calls .*01\.07\.2026/ }),
    );
    expect(await screen.findByText("Профиль подключения выбран")).toBeInTheDocument();
    const row = await screen.findByLabelText("Источник задачи 1");
    await waitFor(() =>
      expect(
        within(row).getByLabelText(
          "Выбрать файлы с устройства для задачи 1",
        ),
      ).toBeEnabled(),
    );

    const credentialReadsBeforeLate = credentialReads;
    const policyReadsBeforeLate = policyReads;
    await act(async () => {
      resolveOlderCredentials?.(
        await json({
          credentials: [
            credentialFixture({ id: "old-1", label: "Late old profile one" }),
            credentialFixture({ id: "old-2", label: "Late old profile two" }),
          ],
        }),
      );
      resolveOlderPolicy?.(
        await json({
          local_upload_enabled: false,
          max_upload_bytes: 1,
          multipart_threshold_bytes: 16777216,
          multipart_part_size_bytes: 8388608,
          supported_mime_prefixes: ["audio/"],
          supported_mime_types: [],
        }),
      );
    });

    expect(screen.queryByText("Late old profile one")).not.toBeInTheDocument();
    expect(screen.queryByText("Late old profile two")).not.toBeInTheDocument();
    expect(
      within(row).getByLabelText(
        "Выбрать файлы с устройства для задачи 1",
      ),
    ).toBeEnabled();
    expect(credentialReadsBeforeLate).toBeGreaterThanOrEqual(4);
    expect(policyReadsBeforeLate).toBeGreaterThanOrEqual(3);
    expect(credentialReads).toBe(credentialReadsBeforeLate);
    expect(policyReads).toBe(policyReadsBeforeLate);
  });

  it("uses the server upload-size policy before initiating a local upload", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/sources/upload-policy"))
        return json({
          local_upload_enabled: true,
          max_upload_bytes: 3,
          multipart_threshold_bytes: 16777216,
          multipart_part_size_bytes: 8388608,
          supported_mime_prefixes: ["audio/", "video/"],
          supported_mime_types: ["application/ogg"],
        });
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    await openProjectsPage();
    const row = await screen.findByLabelText("Источник задачи 1");
    const input = within(row).getByLabelText(
      "Выбрать файлы с устройства для задачи 1",
    ) as HTMLInputElement;
    await waitFor(() => expect(input).toBeEnabled());

    await userEvent.upload(
      input,
      new File(["four"], "too-large.ogg", { type: "audio/ogg" }),
    );

    expect(
      await screen.findByText(/too-large\.ogg: файл больше 3 байт\./),
    ).toBeInTheDocument();
    expect(
      baseFetch.mock.calls.some(
        ([url, init]) =>
          String(url).endsWith(
            "/api/projects/p1/sources/local-upload/initiate",
          ) && init?.method === "POST",
      ),
    ).toBe(false);
  });

  it("fails closed when the server upload policy is unavailable", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/sources/upload-policy"))
        return json({ detail: "unavailable" }, false, 503);
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    await openProjectsPage();
    expect(
      await screen.findByText(
        /Не удалось загрузить правила локальной загрузки/,
      ),
    ).toBeInTheDocument();
    const row = await screen.findByLabelText("Источник задачи 1");
    expect(
      within(row).getByLabelText(
        "Выбрать файлы с устройства для задачи 1",
      ),
    ).toBeDisabled();
  });

  it("clears stale local upload status before rejecting a new invalid file", async () => {
    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    const deviceCard = await screen.findByLabelText("Источник задачи 1");
    const input = within(deviceCard).getByLabelText(
      "Выбрать файлы с устройства для задачи 1",
    ) as HTMLInputElement;
    const validFile = new File(["valid audio"], "valid.ogg", {
      type: "audio/ogg",
    });

    await userEvent.upload(input, validFile);

    await within(deviceCard).findByText("Загружено файлов: 1.");
    const uploadInitiationsBeforeInvalid = (
      fetch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.filter(
      ([url, init]) =>
        String(url).endsWith(
          "/api/projects/p1/sources/local-upload/initiate",
        ) && init?.method === "POST",
    );
    expect(uploadInitiationsBeforeInvalid).toHaveLength(1);

    const unsupportedFile = new File(["not media"], "unsupported.exe", {
      type: "application/x-msdownload",
    });
    await userEvent.upload(input, unsupportedFile, { applyAccept: false });

    await screen.findByText(
      /unsupported\.exe: тип файла не поддерживается текущими правилами\./,
    );
    expect(
      within(deviceCard).queryByText(/valid\.ogg/),
    ).not.toBeInTheDocument();
    expect(
      within(deviceCard).queryByText(/Загружено файлов: 1\./),
    ).not.toBeInTheDocument();
    const uploadInitiationsAfterInvalid = (
      fetch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.filter(
      ([url, init]) =>
        String(url).endsWith(
          "/api/projects/p1/sources/local-upload/initiate",
        ) && init?.method === "POST",
    );
    expect(uploadInitiationsAfterInvalid).toHaveLength(1);
  });

  it("shows the no-ready-source recovery state and switches back to sources", async () => {
    const baseFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = baseFetch.getMockImplementation();
    baseFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/projects/p1/sources") && !init?.method)
        return json({ sources: [] });
      return defaultFetch?.(url, init) ?? json({ ok: true });
    });
    renderApp();
    await openProjectsPage();
    await screen.findByRole("form", { name: "Композитор пакетных задач" });
    expect(
      await screen.findByText(/Сначала добавьте хотя бы один готовый файл/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Перейти к источникам" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("tab", { name: "Подготовка" }),
    ).not.toBeInTheDocument();
  });

  it("places Google Drive technical values in a closed details block and repairs security summary markup", async () => {
    renderApp();
    await openSettingsSection("Подключения");
    const googleCard = screen
      .getByRole("heading", { name: "Google Drive подключён" })
      .closest("article");
    expect(googleCard).not.toBeNull();
    const technical = within(googleCard as HTMLElement).getByText(
      "Технические сведения",
    );
    const details = technical.closest("details");
    expect(details).not.toHaveAttribute("open");
    expect(
      within(details as HTMLElement).getByText("active"),
    ).toBeInTheDocument();
    expect(
      within(details as HTMLElement).getByText(/drive.file/),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Аккаунт" }));
    const securitySummary = screen
      .getByText("Журнал безопасности")
      .closest("summary");
    expect(securitySummary).toHaveAccessibleName("Журнал безопасности");
    expect(securitySummary?.querySelector("h1,h2,h3,h4,h5,h6")).toBeNull();
    expect(securitySummary?.closest("details")).not.toHaveAttribute("open");
  });

  it("keeps Studio CSS scoped to one token block without broad sidebar aside rules", () => {
    const css = readFileSync(join(process.cwd(), "src/styles.css"), "utf8");
    expect(css.match(/:root\s*\{/g)).toHaveLength(1);
    expect(css).toContain(".app-sidebar");
    expect(css).not.toContain("button:not(.primary):not(.danger)");
    expect(css).toMatch(
      /button:where\(\s*:not\(\.primary\):not\(\.danger\)\s*\)/,
    );
    expect(css).toContain(':root[data-theme="dark"]');
    expect(css).toMatch(
      /:root\[data-theme="dark"\]\s*\{[^}]*--studio-on-primary:\s*#08111f/s,
    );
    expect(css).toMatch(/\.shell > main\s*\{[^}]*width:\s*100%/s);
    expect(css).not.toContain("width: min(100%, 1360px)");
    expect(css).not.toContain("!important");
    expect(css).toContain(".app-nav button");
    expect(css).toContain(".tabs button");
    expect(css).toContain(".legacy-workspace-list button");
    expect(css).toContain(".legacy-workspace-list button.active");
    expect(css).toContain(".file-picker-control:focus-within .button-like");
    expect(css).toMatch(
      /\.file-picker-control:focus-within \.button-like\s*\{[^}]*outline:/s,
    );
    expect(css).not.toMatch(/(^|\n)aside\s*\{/);
    expect(css).not.toMatch(/aside\s*\{[^}]*height:\s*100vh/s);
    expect(css).not.toMatch(/(^|\n)input\[type=["']file["']\]\s*\{/);
    expect(css).toMatch(/button,\s*\.button-like\s*\{[^}]*min-height:\s*44px/s);
    expect(css).toMatch(/summary\s*\{[^}]*min-height:\s*44px/s);
    expect(css).toMatch(
      /\.meta\s*\{[^}]*grid-template-columns:\s*minmax\(8rem, 0\.35fr\) minmax\(0, 1fr\)/s,
    );
    expect(css).toMatch(
      /@media \(max-width: 900px\)[\s\S]*?\.app-nav\s*\{[^}]*grid-template-columns:\s*repeat\(4, minmax\(0, 1fr\)\)/,
    );
    expect(css).toMatch(
      /@media \(max-width: 620px\)[\s\S]*?\.meta\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/,
    );
  });

  it("shows bootstrap-required operator instruction", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string) =>
        url.endsWith("/api/auth/session")
          ? json({}, false, 401)
          : json({ bootstrap_required: true }),
    );
    renderApp();
    expect(await screen.findByText(/bootstrap-admin/)).toBeInTheDocument();
  });
});

describe("settings diagnostics", () => {
  beforeEach(() => {
    cleanup();
    vi.restoreAllMocks();
    clearPwaDiagnosticsSession();
    window.history.replaceState({}, "", "/");
    localStorage.clear();
    sessionStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => json({ ok: true })),
    );
  });

  async function openDiagnosticsSettings() {
    await openSettingsSection("Подключения");
    await userEvent.click(screen.getByRole("tab", { name: "Для поддержки" }));
    await screen.findByRole("heading", { name: "Для поддержки" });
  }

  function installBasicPlatformSettingsFixture() {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string) => {
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
          });
        if (url.endsWith("/api/auth/csrf"))
          return json({ csrf_token: "csrf-after-refresh" });
        if (url.endsWith("/api/credentials"))
          return json({
            credentials: [
              {
                id: "cred-active",
                provider: "elevenlabs",
                label: "Primary STT",
                status: "active",
                masked_value: "••••1234",
                active_version: 2,
              },
            ],
          });
        if (url.endsWith("/api/google/connection"))
          return json({
            connected: false,
            status: null,
            google_email: null,
            scopes: null,
            connected_at: null,
            revoked_at: null,
          });
        if (url.endsWith("/api/audit-events")) return json({ events: [] });
        if (url.endsWith("/api/diagnostics/system"))
          return json({
            build: {},
            diagnostics: {},
            google_drive: {},
            provider_credentials: {},
            report_limits: {},
          });
        if (url.includes("/api/diagnostics/events"))
          return json({
            events: [],
            next_cursor: null,
            period: {
              start: "2026-07-15T00:00:00Z",
              end: "2026-07-16T00:00:00Z",
            },
          });
        if (url.endsWith("/api/projects")) return json({ projects: [] });
        return json({ ok: true });
      },
    );
  }

  it("bounds, validates, and safely retries the settings audit collection", async () => {
    installBasicPlatformSettingsFixture();
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = fetchMock.getMockImplementation();
    let auditGets = 0;
    let auditSignal: AbortSignal | undefined;
    fetchMock.mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/audit-events")) {
          auditGets += 1;
          auditSignal = init?.signal;
          if (auditGets === 1) {
            return json({
              events: [
                {
                  id: "audit-malformed",
                  type: "auth.login",
                  created_at: "not-a-date",
                  metadata: { raw: "raw-audit-metadata" },
                },
              ],
              raw_response: "raw-audit-response",
            });
          }
          return json({
            events: [
              {
                id: "audit-safe",
                type: "auth.login",
                created_at: "2026-08-14T08:00:00Z",
                metadata: { raw: "raw-audit-retry-metadata" },
                raw_event: "raw-audit-event",
              },
            ],
            raw_response: "raw-audit-retry-response",
          });
        }
        return defaultFetch?.(input, init) ?? json({});
      },
    );
    const timeoutSpy = vi.spyOn(globalThis, "setTimeout");

    try {
      renderApp();
      await openDiagnosticsSettings();
      expect(
        await screen.findByText(
          "Не удалось загрузить аудит безопасности. Повторите попытку.",
        ),
      ).toBeInTheDocument();
      expect(auditSignal).toBeInstanceOf(AbortSignal);
      expect(timeoutSpy).toHaveBeenCalledWith(expect.any(Function), 15_000);
      expect(document.body.textContent).not.toContain("raw-audit");
      expect(
        screen.queryByText("Событий аудита нет."),
      ).not.toBeInTheDocument();

      await userEvent.click(
        screen.getByRole("button", { name: "Повторить загрузку аудита" }),
      );
      expect(await screen.findByText(/Вход выполнен/)).toBeInTheDocument();
      expect(auditGets).toBe(2);
      expect(document.body.textContent).not.toContain("raw-audit");
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("replaces audit cursor pages without accumulating previously viewed rows", async () => {
    installBasicPlatformSettingsFixture();
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = fetchMock.getMockImplementation();
    const auditUrls: string[] = [];
    fetchMock.mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/api/audit-events")) {
          auditUrls.push(url);
          if (auditUrls.length === 1) {
            return json({
              events: Array.from({ length: 50 }, (_, index) => ({
                id: `audit-${index}`,
                type: "auth.login",
                created_at: `2026-08-14T08:00:${String(index).padStart(2, "0")}Z`,
              })),
              next_cursor: "audit-next-page",
              page_size: 50,
            });
          }
          return json({
            events: [
              {
                id: "audit-49",
                type: "auth.login",
                created_at: "2026-08-14T08:00:49Z",
              },
              {
                id: "audit-next",
                type: "credential.revoked",
                created_at: "2026-08-14T07:59:59Z",
              },
            ],
            next_cursor: null,
            page_size: 50,
          });
        }
        return defaultFetch?.(input, init) ?? json({});
      },
    );

    renderApp();
    await openDiagnosticsSettings();
    const auditRegion = screen.getByRole("region", {
      name: "Аудит безопасности",
    });
    await userEvent.click(within(auditRegion).getByText("Аудит безопасности"));
    await waitFor(() =>
      expect(within(auditRegion).getAllByRole("listitem")).toHaveLength(50),
    );

    await userEvent.click(
      within(auditRegion).getByRole("button", {
        name: "Следующая страница аудита",
      }),
    );

    expect(
      await within(auditRegion).findByText(/Ключ отозван/),
    ).toBeInTheDocument();
    expect(within(auditRegion).getAllByRole("listitem")).toHaveLength(2);
    expect(within(auditRegion).getByRole("button", { name: "Предыдущая страница аудита" })).toBeEnabled();
    expect(auditUrls).toHaveLength(2);
    expect(auditUrls[1]).toContain("page_size=50");
    expect(auditUrls[1]).toContain("cursor=audit-next-page");
    expect(document.body.textContent).not.toContain("audit-next-page");
  });

  it("keeps a mutation-triggered audit refresh latest-wins", async () => {
    installBasicPlatformSettingsFixture();
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = fetchMock.getMockImplementation();
    let auditGets = 0;
    let staleSignal: AbortSignal | undefined;
    let resolveStale: ((response: Response) => void) | undefined;
    fetchMock.mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/audit-events")) {
          auditGets += 1;
          if (auditGets === 1) {
            staleSignal = init?.signal;
            return new Promise<Response>((resolve) => {
              resolveStale = resolve;
            });
          }
          return json({
            events: [
              {
                id: "audit-new",
                type: "credential.revoked",
                created_at: "2026-08-14T08:01:00Z",
              },
            ],
          });
        }
        return defaultFetch?.(input, init) ?? json({});
      },
    );
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    renderApp();
    await openSettingsSection("Подключения");
    await waitFor(() => expect(resolveStale).toBeDefined());
    await clickCredentialAction("Отключить");
    await waitFor(() => expect(auditGets).toBe(2));
    expect(staleSignal?.aborted).toBe(true);
    await act(async () =>
      resolveStale?.(
        await json({
          events: [
            {
              id: "audit-stale",
              type: "auth.login",
              created_at: "2026-08-14T07:59:00Z",
            },
          ],
        }),
      ),
    );

    await userEvent.click(screen.getByRole("tab", { name: "Для поддержки" }));
    expect(await screen.findByText(/Ключ отозван/)).toBeInTheDocument();
    expect(screen.queryByText(/Вход выполнен/)).not.toBeInTheDocument();
    confirmSpy.mockRestore();
  });

  it("aborts audit ownership on settings teardown and ignores late success", async () => {
    installBasicPlatformSettingsFixture();
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = fetchMock.getMockImplementation();
    let auditGets = 0;
    let auditSignal: AbortSignal | undefined;
    let resolveAudit: ((response: Response) => void) | undefined;
    fetchMock.mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/audit-events")) {
          auditGets += 1;
          if (auditGets === 1) {
            auditSignal = init?.signal;
            return new Promise<Response>((resolve) => {
              resolveAudit = resolve;
            });
          }
          return json({
            events: [
              {
                id: "audit-remount",
                type: "auth.sessions_revoked",
                created_at: "2026-08-14T08:02:00Z",
              },
            ],
          });
        }
        return defaultFetch?.(input, init) ?? json({});
      },
    );

    renderApp();
    await openSettingsPage();
    await waitFor(() => expect(resolveAudit).toBeDefined());
    await userEvent.click(
      within(screen.getByRole("navigation", { name: "Основная навигация" })).getByRole("button", {
        name: "Обзор",
      }),
    );
    expect(auditSignal?.aborted).toBe(true);
    await act(async () =>
      resolveAudit?.(
        await json({
          events: [
            {
              id: "audit-late",
              type: "auth.login",
              created_at: "2026-08-14T07:58:00Z",
            },
          ],
        }),
      ),
    );

    await openSettingsPage();
    await userEvent.click(screen.getByRole("tab", { name: "Для поддержки" }));
    expect(await screen.findByText(/Другие сеансы завершены/)).toBeInTheDocument();
    expect(screen.queryByText(/Вход выполнен/)).not.toBeInTheDocument();
  });

  it("exports every diagnostics format through the common safe report flow", async () => {
    const originalURL = URL;
    const createObjectURL = vi.fn(() => "blob:diagnostics-report");
    const revokeObjectURL = vi.fn();
    originalURL.createObjectURL = createObjectURL;
    originalURL.revokeObjectURL = revokeObjectURL;
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    const calledUrls: string[] = [];
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string, init?: RequestInit) => {
        calledUrls.push(url);
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
          });
        if (url.endsWith("/api/auth/csrf"))
          return json({ csrf_token: "csrf-after-refresh" });
        if (url.endsWith("/api/credentials"))
          return json({
            credentials: [
              {
                id: "cred-active",
                provider: "elevenlabs",
                label: "Primary STT",
                status: "active",
                masked_value: "••••1234",
                active_version: 2,
              },
            ],
          });
        if (url.endsWith("/api/google/connection"))
          return json({
            connected: false,
            status: null,
            google_email: null,
            scopes: null,
            connected_at: null,
            revoked_at: null,
          });
        if (url.endsWith("/api/audit-events")) return json({ events: [] });
        if (url.endsWith("/api/diagnostics/system"))
          return json({
            build: {},
            diagnostics: {},
            google_drive: {},
            provider_credentials: {},
            report_limits: {},
          });
        if (url.includes("/api/diagnostics/events"))
          return json({
            events: [],
            next_cursor: null,
            period: {
              start: "2026-07-15T00:00:00Z",
              end: "2026-07-16T00:00:00Z",
            },
          });
        const reportMatch = url.match(
          /\/api\/diagnostics\/report\.(md|json|yaml|toml)$/,
        );
        if (reportMatch && init?.method === "POST") {
          const format = reportMatch[1] as TestDiagnosticsReportFormat;
          return diagnosticsReport(format);
        }
        return json({ ok: true });
      },
    );

    renderApp();
    await openDiagnosticsSettings();
    expect(
      screen.getByRole("heading", { name: "События диагностики" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Диагностический пакет для анализа",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/безопасный пакет/)).toBeInTheDocument();
    expect(screen.getByText(/Не вводите пароли/)).toBeInTheDocument();
    expect(screen.getByText(/Аудит безопасности в пакет не входит/)).toBeInTheDocument();

    await userEvent.type(
      screen.getByLabelText("Что произошло"),
      "Тестовый сбой при создании задачи",
    );
    await userEvent.type(
      screen.getByLabelText(/Какая операция связана с проблемой/),
      "Задача 42",
    );
    await userEvent.selectOptions(screen.getByLabelText("Период"), "7");
    await userEvent.click(
      screen.getByText("Расширенные технические фильтры"),
    );
    await userEvent.selectOptions(screen.getByLabelText("Уровень"), "INFO");
    await userEvent.selectOptions(screen.getByLabelText("Компонент"), "api");
    await userEvent.type(
      screen.getByLabelText("Код события"),
      "api.request_failed",
    );
    for (const [label, format] of [
      ["JSON", "json"],
      ["Markdown", "md"],
    ]) {
      await userEvent.selectOptions(
        screen.getByLabelText("Формат пакета"),
        format,
      );
      await userEvent.click(
        screen.getByRole("button", {
          name: "Скачать диагностический пакет",
        }),
      );
      expect(await screen.findByText(`${label}-отчёт скачан.`)).toBeInTheDocument();
    }
    const reportCalls = (
      fetch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.filter(([url]) =>
      /\/api\/diagnostics\/report\.(md|json|yaml|toml)$/.test(String(url)),
    );
    expect(reportCalls).toHaveLength(2);
    expect(reportCalls.map(([url]) => String(url).split(".").at(-1))).toEqual([
      "json",
      "md",
    ]);
    for (const [, init] of reportCalls) {
      expect(init?.body).toContain('"level":"INFO"');
      expect(init?.body).toContain('"component":"api"');
      expect(init?.body).toContain('"event_code":"api.request_failed"');
      expect(init?.body).toContain(
        '"problem_description":"Тестовый сбой при создании задачи"',
      );
      expect(init?.body).toContain('"operation_reference":"Задача 42"');
    }
    expect(
      calledUrls.some(
        (url) =>
          url.includes("/api/diagnostics/pwa") &&
          !url.endsWith("/api/diagnostics/pwa-events"),
      ),
    ).toBe(false);
    expect(
      clickSpy.mock.instances.map((instance) => instance.download.split(".").at(-1)),
    ).toEqual(["json", "md"]);
    expect(createObjectURL).toHaveBeenCalledTimes(2);
    expect(revokeObjectURL).toHaveBeenCalledTimes(2);
    clickSpy.mockRestore();
    cleanup();
    window.history.replaceState({}, "", "/");
  });

  it("bounds and deduplicates stalled diagnostics report export before retry", async () => {
    installBasicPlatformSettingsFixture();
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = fetchMock.getMockImplementation();
    let reportCalls = 0;
    let reportSignal: AbortSignal | undefined;
    fetchMock.mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (
          url.endsWith("/api/diagnostics/report.md") &&
          init?.method === "POST"
        ) {
          reportCalls += 1;
          reportSignal = init.signal;
          if (reportCalls === 1) {
            if (!reportSignal) throw new Error("report signal is missing");
            return new Promise<Response>((_resolve, reject) => {
              reportSignal?.addEventListener("abort", () =>
                reject(new Error("raw-report-timeout")),
              );
            });
          }
          return markdownReport();
        }
        return defaultFetch?.(input, init) ?? json({});
      },
    );
    const createObjectURL = vi.fn(() => "blob:bounded-report");
    const revokeObjectURL = vi.fn();
    URL.createObjectURL = createObjectURL;
    URL.revokeObjectURL = revokeObjectURL;
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    renderApp();
    await openDiagnosticsSettings();
    await screen.findByText("За выбранный период событий нет.");
    await userEvent.selectOptions(screen.getByLabelText("Формат пакета"), "md");
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 20_000 ? 1 : (delay as number),
          ...args,
        )) as typeof setTimeout);

    try {
      const exportButton = screen.getByRole("button", {
        name: "Скачать диагностический пакет",
      });
      fireEvent.click(exportButton);
      fireEvent.click(exportButton);
      expect(
        await screen.findByText(
          "Не удалось скачать Markdown-отчёт. Повторите попытку.",
        ),
      ).toBeInTheDocument();
      expect(reportSignal?.aborted).toBe(true);
      expect(reportCalls).toBe(1);
      expect(document.body.textContent).not.toContain("raw-report-timeout");

      await userEvent.click(exportButton);
      expect(
        await screen.findByText("Markdown-отчёт скачан."),
      ).toBeInTheDocument();
      expect(reportCalls).toBe(2);
      expect(createObjectURL).toHaveBeenCalledTimes(1);
      expect(clickSpy).toHaveBeenCalledTimes(1);
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:bounded-report");
    } finally {
      timeoutSpy.mockRestore();
      clickSpy.mockRestore();
    }
  });

  it("retries report export only after exact CSRF rejection and validates Markdown", async () => {
    installBasicPlatformSettingsFixture();
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = fetchMock.getMockImplementation();
    const reportTokens: string[] = [];
    let reportCalls = 0;
    let csrfRequests = 0;
    fetchMock.mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (
          url.endsWith("/api/auth/csrf") &&
          init?.method === "POST"
        ) {
          csrfRequests += 1;
          return json({
            csrf_token:
              csrfRequests === 1 ? "csrf-after-refresh" : "csrf-export-new",
          });
        }
        if (
          url.endsWith("/api/diagnostics/report.md") &&
          init?.method === "POST"
        ) {
          reportCalls += 1;
          reportTokens.push(
            String((init.headers as Record<string, string>)["x-csrf-token"]),
          );
          if (reportCalls === 1) {
            return json(
              { detail: { reason: "origin_not_allowed", raw: "raw-origin" } },
              false,
              403,
            );
          }
          if (reportCalls === 2) {
            return json(
              { detail: { reason: "csrf_token_invalid" } },
              false,
              403,
            );
          }
          if (reportCalls === 3) {
            return markdownReport("raw-invalid-report", 200, {
              "content-type": "application/json",
            });
          }
          return markdownReport();
        }
        return defaultFetch?.(input, init) ?? json({});
      },
    );
    const createObjectURL = vi.fn(() => "blob:validated-report");
    const revokeObjectURL = vi.fn();
    URL.createObjectURL = createObjectURL;
    URL.revokeObjectURL = revokeObjectURL;
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    renderApp();
    await openDiagnosticsSettings();
    await userEvent.selectOptions(screen.getByLabelText("Формат пакета"), "md");
    const exportButton = screen.getByRole("button", {
      name: "Скачать диагностический пакет",
    });
    await userEvent.click(exportButton);
    await waitFor(() => expect(reportCalls).toBe(1));
    expect(csrfRequests).toBe(1);
    expect(createObjectURL).not.toHaveBeenCalled();

    await userEvent.click(exportButton);
    await waitFor(() => expect(reportCalls).toBe(3));
    expect(csrfRequests).toBe(2);
    expect(reportTokens).toEqual([
      "csrf-after-refresh",
      "csrf-after-refresh",
      "csrf-export-new",
    ]);
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toContain("raw-origin");
    expect(document.body.textContent).not.toContain("raw-invalid-report");

    await userEvent.click(exportButton);
    expect(
      await screen.findByText("Markdown-отчёт скачан."),
    ).toBeInTheDocument();
    expect(reportCalls).toBe(4);
    expect(reportTokens.at(-1)).toBe("csrf-export-new");
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:validated-report");
    clickSpy.mockRestore();
  });

  it("aborts report export ownership on diagnostics teardown", async () => {
    installBasicPlatformSettingsFixture();
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = fetchMock.getMockImplementation();
    let reportSignal: AbortSignal | undefined;
    let resolveReport: ((response: Response) => void) | undefined;
    fetchMock.mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (
          url.endsWith("/api/diagnostics/report.md") &&
          init?.method === "POST"
        ) {
          reportSignal = init.signal;
          return new Promise<Response>((resolve) => {
            resolveReport = resolve;
          });
        }
        return defaultFetch?.(input, init) ?? json({});
      },
    );
    const createObjectURL = vi.fn(() => "blob:late-report");
    URL.createObjectURL = createObjectURL;

    renderApp();
    await openDiagnosticsSettings();
    await userEvent.selectOptions(screen.getByLabelText("Формат пакета"), "md");
    await userEvent.click(
      screen.getByRole("button", {
        name: "Скачать диагностический пакет",
      }),
    );
    await waitFor(() => expect(resolveReport).toBeDefined());
    await userEvent.click(screen.getByRole("tab", { name: "Аккаунт" }));
    expect(reportSignal?.aborted).toBe(true);

    await act(async () => resolveReport?.(await markdownReport()));
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(
      screen.queryByText("Markdown-отчёт скачан."),
    ).not.toBeInTheDocument();
  });

  it("restores URL-backed navigation without browser-stored navigation state", async () => {
    const addSpy = vi.spyOn(window, "addEventListener");
    const removeSpy = vi.spyOn(window, "removeEventListener");
    const localGet = vi.spyOn(Storage.prototype, "getItem");
    const localSet = vi.spyOn(Storage.prototype, "setItem");
    installBasicPlatformSettingsFixture();
    window.history.replaceState({}, "", "/");

    renderApp();
    await waitForPlatformOverview();
    expect(window.location.pathname).toBe("/");
    await userEvent.click(
      screen.getByRole("button", { name: "Транскрибации" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Транскрибации" }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe("/transcriptions");
    await userEvent.click(screen.getByRole("button", { name: "Настройки" }));
    expect(
      await screen.findByRole("heading", { name: "Аккаунт" }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe("/settings");
    await userEvent.click(screen.getByRole("tab", { name: "Для поддержки" }));
    expect(
      await screen.findByRole("heading", { name: "Для поддержки" }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe("/settings/diagnostics");
    await userEvent.click(screen.getByRole("tab", { name: "Аккаунт" }));
    expect(
      await screen.findByRole("heading", { name: "Аккаунт" }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe("/settings");
    cleanup();
    expect(
      removeSpy.mock.calls.filter(([type]) => type === "popstate"),
    ).toHaveLength(2);

    window.history.replaceState({}, "", "/settings/diagnostics");
    renderApp();
    expect(
      await screen.findByRole("heading", { name: "Для поддержки" }),
    ).toBeInTheDocument();
    window.history.pushState({}, "", "/settings");
    fireEvent.popState(window);
    expect(
      await screen.findByRole("heading", { name: "Аккаунт" }),
    ).toBeInTheDocument();
    cleanup();

    window.history.replaceState({}, "", "/unknown");
    renderApp();
    await waitForPlatformOverview();
    cleanup();

    window.history.replaceState({}, "", "/projects");
    renderApp();
    expect(
      await screen.findByRole("heading", { name: "Транскрибации" }),
    ).toBeInTheDocument();
    cleanup();

    window.history.replaceState({}, "", "/settings");
    renderApp();
    expect(
      await screen.findByRole("heading", { name: "Аккаунт" }),
    ).toBeInTheDocument();
    expect(
      addSpy.mock.calls.filter(([type]) => type === "popstate"),
    ).toHaveLength(7);
    expect(
      localGet.mock.calls.every(([key]) => key === "studio-theme-preference"),
    ).toBe(true);
    expect(localSet).not.toHaveBeenCalled();
    cleanup();
    window.history.replaceState({}, "", "/");
  });

  it("direct settings OAuth cleanup preserves the intended settings route", async () => {
    installBasicPlatformSettingsFixture();
    const replaceSpy = vi.spyOn(window.history, "replaceState");
    window.history.replaceState(
      {},
      "",
      "/settings/diagnostics?google_oauth=connected&keep=1",
    );
    renderApp();
    expect(
      await screen.findByRole("heading", { name: "Для поддержки" }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe("/settings/diagnostics");
    expect(window.location.search).toBe("?keep=1");
    expect(replaceSpy).toHaveBeenCalledWith(
      expect.anything(),
      "",
      "/settings/diagnostics?keep=1",
    );
    cleanup();
    window.history.replaceState({}, "", "/");
  });

  it("opens platform Settings diagnostics and renders safe system, timeline, PWA, and separate audit sections", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string, init?: RequestInit) => {
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
          });
        if (url.endsWith("/api/auth/csrf"))
          return json({ csrf_token: "csrf-after-refresh" });
        if (url.endsWith("/api/credentials"))
          return json({
            credentials: [
              {
                id: "cred-active",
                provider: "elevenlabs",
                label: "Primary STT",
                status: "active",
                masked_value: "••••1234",
                active_version: 2,
              },
            ],
          });
        if (url.endsWith("/api/google/connection"))
          return json({
            connected: false,
            status: null,
            google_email: null,
            scopes: null,
            connected_at: null,
            revoked_at: null,
          });
        if (url.endsWith("/api/audit-events"))
          return json({
            events: [
              {
                id: "audit-1",
                type: "auth.login",
                trace_id: "trace_6666666666666666",
                created_at: "2026-07-16T10:00:00Z",
              },
            ],
          });
        if (
          url.endsWith("/api/diagnostics/incidents/incident-1/acknowledge") &&
          init?.method === "POST"
        )
          return json({
            id: "incident-1",
            kind: "provider_unavailable",
            severity: "warning",
            status: "acknowledged",
            summary_code: "provider_unavailable",
            occurrence_count: 4,
            evidence_count: 4,
            first_detected_at: "2026-07-16T08:00:00Z",
            last_detected_at: "2026-07-16T10:00:00Z",
            last_transition_at: "2026-07-16T10:01:00Z",
            delivery: {
              channel: "telegram",
              state: "suppressed",
              attempt_count: 0,
              notification_kind: "firing",
            },
          });
        if (url.endsWith("/api/diagnostics/system"))
          return json({
            environment: "production",
            build: {
              web: "web-build",
              api: "api-build",
              worker: "worker-build",
            },
            release_version: "0.1.0",
            schema_revision: "0026_runtime_component_status",
            components: {
              web: { status: "available", commit_sha: "a".repeat(40) },
              api: { status: "available", commit_sha: "a".repeat(40) },
              worker: { status: "ready", commit_sha: "a".repeat(40), heartbeat_age_seconds: 5 },
            },
            health: {
              backend: "ready",
              database: "reachable",
              queue: { status: "ready", queued: 1, processing: 0, oldest_queued_age_seconds: 12 },
              worker: { status: "ready" },
              object_storage: { status: "ready", probe: "read_only_head" },
              stt_provider: { status: "configured", availability: "unknown", probe: "not_run", configured_credentials: 2 },
              email: { status: "not_configured" },
            },
            google_drive: { connected: true, scope_ready: false },
            provider_credentials: { active_count: 2, ready: true },
            diagnostics: {
              recording_enabled: true,
              debug_recording: "inactive",
              retention_days: 14,
              debug_retention_hours: 24,
            },
            report_limits: { max_days: 7, max_timeline_events: 5000 },
            alerts: {
              incident_monitoring: "enabled",
              telegram: "not_configured",
              email: "not_configured",
              storage_limit: "not_configured",
              api_limit: "configured",
              incidents: [
                {
                  id: "incident-1",
                  kind: "provider_unavailable",
                  severity: "warning",
                  status: "firing",
                  summary_code: "provider_unavailable",
                  occurrence_count: 4,
                  evidence_count: 4,
                  first_detected_at: "2026-07-16T08:00:00Z",
                  last_detected_at: "2026-07-16T10:00:00Z",
                  last_transition_at: "2026-07-16T10:00:00Z",
                  delivery: {
                    channel: "telegram",
                    state: "pending",
                    attempt_count: 0,
                    notification_kind: "firing",
                  },
                },
                {
                  id: "incident-canary",
                  kind: "operator_canary",
                  severity: "warning",
                  status: "resolved",
                  summary_code: "operator_canary_ok",
                  occurrence_count: 2,
                  evidence_count: 0,
                  first_detected_at: "2026-07-16T09:00:00Z",
                  last_detected_at: "2026-07-16T09:00:01Z",
                  last_transition_at: "2026-07-16T09:00:02Z",
                  trace_id: "trace_7777777777777777",
                  delivery: {
                    channel: "telegram",
                    state: "suppressed",
                    attempt_count: 0,
                    notification_kind: "recovery",
                  },
                },
              ],
            },
            secret_path: "/secret/path/forbidden",
          });
        if (url.includes("/api/diagnostics/events"))
          return json({
            events: [
              {
                id: "evt-1",
                occurred_at: "2026-07-16T09:00:00Z",
                level: "ERROR",
                component: "api",
                event_code: "JOB_FAILED",
                correlation_id: "corr_should_not_render",
                request_id: "req_should_not_render",
                metadata: {
                  boundary: "provider_transport",
                  error_code: "provider_timeout",
                  provider_error_code: "service_unavailable",
                  retryable: true,
                  http_status_category: "5xx",
                  filename: "forbidden.mp3",
                  transcript: "forbidden transcript",
                  safe_count: 3,
                },
                occurrence_count: 2,
              },
            ],
            next_cursor: "cursor-secret",
            period: {
              start: "2026-07-15T00:00:00Z",
              end: "2026-07-16T00:00:00Z",
            },
          });
        if (
          url.endsWith("/api/diagnostics/report.md") &&
          init?.method === "POST"
        )
          return markdownReport("# report\n");
        return json({ ok: true });
      },
    );

    renderApp();
    await openDiagnosticsSettings();

    expect(screen.getByRole("tab", { name: "Для поддержки" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(await screen.findByText("web-build")).toBeInTheDocument();
    expect(screen.getByText("api-build")).toBeInTheDocument();
    expect(screen.getByText("worker-build")).toBeInTheDocument();
    expect(screen.getByText("0.1.0")).toBeInTheDocument();
    expect(screen.getByText("0026_runtime_component_status")).toBeInTheDocument();
    expect(screen.getAllByText("a".repeat(40))).toHaveLength(3);
    expect(screen.getByText(/read_only_head/)).toBeInTheDocument();
    expect(screen.getByText(/probe not_run/)).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Системные предупреждения" }),
    ).toBeInTheDocument();
    expect(screen.getByText("STT provider временно недоступен")).toBeInTheDocument();
    expect(screen.getByText("работает")).toBeInTheDocument();
    expect(screen.getByText("данные доступны")).toBeInTheDocument();
    expect(screen.getByText(/уведомление: ожидает отправки/)).toBeInTheDocument();
    await userEvent.click(screen.getByText("Недавние восстановления"));
    expect(screen.getByText(/Проверка контура предупреждений завершена/)).toBeInTheDocument();
    expect(screen.getByText("trace_7777777777777777")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Просмотрено" }));
    expect(
      await screen.findByText("Предупреждение отмечено как просмотренное."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Разрешение Google Drive получено"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Google Drive готов")).not.toBeInTheDocument();
    expect(screen.getByText("JOB_FAILED")).toBeInTheDocument();
    expect(screen.getAllByText("Ошибка").length).toBeGreaterThan(0);
    expect(screen.getAllByText("API").length).toBeGreaterThan(0);
    expect(screen.getByText("неактивна")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("JOB_FAILEDERROR");
    expect(screen.getByText("boundary")).toBeInTheDocument();
    expect(screen.getByText("error_code")).toBeInTheDocument();
    expect(screen.getByText("provider_error_code")).toBeInTheDocument();
    expect(screen.getByText("retryable")).toBeInTheDocument();
    expect(screen.getByText("http_status_category")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Диагностика PWA" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/пока не включён/)).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Аудит безопасности" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Вход выполнен/)).toBeInTheDocument();
    expect(screen.getByText("trace_6666666666666666")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("corr_should_not_render");
    expect(document.body.textContent).not.toContain("req_should_not_render");
    expect(document.body.textContent).not.toContain("cursor-secret");
    expect(document.body.textContent).not.toContain("/secret/path/forbidden");
    expect(document.body.textContent).not.toContain("forbidden.mp3");
    expect(document.body.textContent).not.toContain("forbidden transcript");
    expect(document.body.textContent).not.toContain("safe_count");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("sends selected filters on the first diagnostics request and cursor only for the second page", async () => {
    const originalURL = URL;
    const createObjectURL = vi.fn(() => "blob:diagnostics-report");
    const revokeObjectURL = vi.fn();
    originalURL.createObjectURL = createObjectURL;
    originalURL.revokeObjectURL = revokeObjectURL;
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    const diagnosticsEventUrls: string[] = [];
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string, init?: RequestInit) => {
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
          });
        if (url.endsWith("/api/auth/csrf"))
          return json({ csrf_token: "csrf-after-refresh" });
        if (url.endsWith("/api/credentials"))
          return json({
            credentials: [
              {
                id: "cred-active",
                provider: "elevenlabs",
                label: "Primary STT",
                status: "active",
                masked_value: "••••1234",
                active_version: 2,
              },
            ],
          });
        if (url.endsWith("/api/google/connection"))
          return json({
            connected: false,
            status: null,
            google_email: null,
            scopes: null,
            connected_at: null,
            revoked_at: null,
          });
        if (url.endsWith("/api/audit-events")) return json({ events: [] });
        if (url.endsWith("/api/diagnostics/system"))
          return json({
            build: {},
            diagnostics: {},
            google_drive: {},
            provider_credentials: {},
            report_limits: {},
          });
        if (url.includes("/api/diagnostics/events")) {
          diagnosticsEventUrls.push(url);
          const query = new URL(url, "http://localhost").searchParams;
          const isCursorRequest = query.has("cursor");
          return json({
            events: [
              {
                id: isCursorRequest ? "evt-second-page" : "evt-first-page",
                occurred_at: isCursorRequest
                  ? "2026-07-16T09:05:00Z"
                  : "2026-07-16T09:00:00Z",
                level: "INFO",
                component: "worker",
                event_code: isCursorRequest ? "JOB_COMPLETED" : "JOB_CREATED",
                metadata: isCursorRequest
                  ? { output_count: 1, final_job_status: "completed" }
                  : {
                      source_count: 2,
                      batch_position: 1,
                      credential_selected: true,
                    },
                occurrence_count: 1,
              },
            ],
            next_cursor: isCursorRequest ? null : "opaque-cursor",
            period: {
              start: "2026-07-15T00:00:00Z",
              end: "2026-07-16T00:00:00Z",
            },
          });
        }
        if (
          url.endsWith("/api/diagnostics/report.md") &&
          init?.method === "POST"
        )
          return markdownReport("# Markdown\n");
        return json({ ok: true });
      },
    );

    renderApp();
    await openDiagnosticsSettings();
    await screen.findByText("Задача транскрибации создана");
    expect(screen.getAllByText("Информация").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Фоновая обработка").length).toBeGreaterThan(0);
    expect(document.body.textContent).not.toContain("JOB_CREATEDINFO");
    const operationSearch = screen.getByLabelText(
      /Какая операция связана с проблемой/,
    );
    await userEvent.type(operationSearch, "job_cre");
    const matchingOperation = within(
      screen.getByRole("group", { name: "Подходящие недавние операции" }),
    ).getByRole("button", { name: /Задача транскрибации создана/ });
    await userEvent.click(matchingOperation);
    expect((operationSearch as HTMLInputElement).value).toMatch(/Задача транскрибации создана/);
    diagnosticsEventUrls.length = 0;

    await userEvent.selectOptions(screen.getByLabelText("Период"), "7");
    await userEvent.click(
      screen.getByText("Расширенные технические фильтры"),
    );
    await userEvent.selectOptions(screen.getByLabelText("Уровень"), "INFO");
    await userEvent.selectOptions(screen.getByLabelText("Компонент"), "worker");
    await userEvent.type(screen.getByLabelText("Код события"), "JOB_CREATED");
    await userEvent.click(
      screen.getByRole("button", { name: "Обновить события" }),
    );
    await waitFor(() => expect(diagnosticsEventUrls).toHaveLength(1));
    const firstParams = new URL(diagnosticsEventUrls[0], "http://localhost")
      .searchParams;
    expect(firstParams.get("page_size")).toBe("25");
    expect(firstParams.get("start")).toBeTruthy();
    expect(firstParams.get("end")).toBeTruthy();
    expect(firstParams.get("level")).toBe("INFO");
    expect(firstParams.get("component")).toBe("worker");
    expect(firstParams.get("event_code")).toBe("JOB_CREATED");
    expect(firstParams.has("cursor")).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Показать ещё" }));
    await waitFor(() => expect(diagnosticsEventUrls).toHaveLength(2));
    const secondParams = new URL(diagnosticsEventUrls[1], "http://localhost")
      .searchParams;
    expect([...secondParams.keys()].sort()).toEqual(["cursor", "page_size"]);
    expect(secondParams.get("page_size")).toBe("25");
    expect(secondParams.get("cursor")).toBe("opaque-cursor");
    expect(secondParams.has("start")).toBe(false);
    expect(secondParams.has("end")).toBe(false);
    expect(secondParams.has("level")).toBe(false);
    expect(secondParams.has("component")).toBe(false);
    expect(secondParams.has("event_code")).toBe(false);
    expect(secondParams.has("project_id")).toBe(false);
    expect(secondParams.has("job_id")).toBe(false);
    expect(screen.getByText("JOB_CREATED")).toBeInTheDocument();
    expect(screen.getByText("JOB_COMPLETED")).toBeInTheDocument();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);

    await userEvent.selectOptions(screen.getByLabelText("Формат пакета"), "md");
    await userEvent.click(
      screen.getByRole("button", {
        name: "Скачать диагностический пакет",
      }),
    );
    const reportCall = (
      fetch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.find(([url]) =>
      String(url).endsWith("/api/diagnostics/report.md"),
    );
    expect(reportCall?.[1]?.headers).toMatchObject({
      "x-csrf-token": "csrf-after-refresh",
    });
    expect(reportCall?.[1]?.body).toContain('"level":"INFO"');
    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1));
    const [downloadedBlob] = createObjectURL.mock.calls[0] as unknown as [Blob];
    expect(downloadedBlob).toMatchObject({
      size: 11,
      type: "text/markdown;charset=utf-8",
    });
    expect(clickSpy).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:diagnostics-report");
    expect(document.body.innerHTML).not.toContain(".txt");
    expect(document.body.innerHTML).not.toContain("text/html");
    expect(document.body.innerHTML).not.toContain("application/json");
    expect(document.body.innerHTML).not.toContain("https://");
    clickSpy.mockRestore();
  });

  it("renders backend-registered diagnostic metadata keys and rejects arbitrary sensitive metadata", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string, init?: RequestInit) => {
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
          });
        if (url.endsWith("/api/auth/csrf"))
          return json({ csrf_token: "csrf-after-refresh" });
        if (url.endsWith("/api/credentials"))
          return json({
            credentials: [
              {
                id: "cred-active",
                provider: "elevenlabs",
                label: "Primary STT",
                status: "active",
                masked_value: "••••1234",
                active_version: 2,
              },
            ],
          });
        if (url.endsWith("/api/google/connection"))
          return json({
            connected: false,
            status: null,
            google_email: null,
            scopes: null,
            connected_at: null,
            revoked_at: null,
          });
        if (url.endsWith("/api/audit-events")) return json({ events: [] });
        if (url.endsWith("/api/diagnostics/system"))
          return json({
            build: {},
            diagnostics: {},
            google_drive: {},
            provider_credentials: {},
            report_limits: {},
          });
        if (url.includes("/api/diagnostics/events"))
          return json({
            events: [
              {
                id: "created",
                occurred_at: "2026-07-16T09:00:00Z",
                level: "INFO",
                component: "api",
                event_code: "JOB_CREATED",
                metadata: {
                  source_count: 2,
                  batch_position: 0,
                  credential_selected: true,
                  filename: "forbidden-source.mp3",
                  url: "https://forbidden.example/report",
                  attempt: 99,
                },
                occurrence_count: 1,
              },
              {
                id: "provider-failed",
                occurred_at: "2026-07-16T09:01:00Z",
                level: "ERROR",
                component: "worker",
                event_code: "PROVIDER_REQUEST_FAILED",
                metadata: {
                  attempt_number: 3,
                  boundary: "provider_transport",
                  duration_ms: 1200,
                  error_code: "provider_timeout",
                  provider_error_code: "service_unavailable",
                  retryable: true,
                  http_status_category: "5xx",
                  transcript: "forbidden transcript",
                  secret: "forbidden-secret",
                  duration_seconds: 2,
                },
                occurrence_count: 1,
              },
              {
                id: "completed",
                occurred_at: "2026-07-16T09:02:00Z",
                level: "INFO",
                component: "worker",
                event_code: "JOB_COMPLETED",
                metadata: {
                  output_count: 1,
                  final_job_status: "completed",
                  attempt_number: 3,
                  request_id: "req_should_not_render",
                },
                occurrence_count: 1,
              },
              {
                id: "cancelled",
                occurred_at: "2026-07-16T09:03:00Z",
                level: "INFO",
                component: "api",
                event_code: "JOB_CANCELLED",
                metadata: {
                  final_job_status: "cancelled",
                  correlation_id: "corr_should_not_render",
                },
                occurrence_count: 1,
              },
              {
                id: "api-failure",
                occurred_at: "2026-07-16T09:04:00Z",
                level: "WARNING",
                component: "api",
                event_code: "API_REQUEST_FAILED",
                metadata: {
                  endpoint_group: "jobs",
                  http_status_category: "4xx",
                  arbitrary: "forbidden arbitrary value",
                  status_category: "4xx",
                  safe_count: 12,
                },
                occurrence_count: 1,
              },
            ],
            next_cursor: null,
            period: {
              start: "2026-07-15T00:00:00Z",
              end: "2026-07-16T00:00:00Z",
            },
          });
        if (
          url.endsWith("/api/diagnostics/report.md") &&
          init?.method === "POST"
        )
          return markdownReport("# Markdown\n");
        return json({ ok: true });
      },
    );

    renderApp();
    await openDiagnosticsSettings();
    await screen.findByText("JOB_CREATED");
    const headers = Array.from(
      document.querySelectorAll<HTMLElement>(".diagnostics-event-header"),
    );
    const createdHeader = headers.find((header) =>
      header.textContent?.includes("Задача транскрибации создана"),
    );
    const cancelledHeader = headers.find((header) =>
      header.textContent?.includes("Транскрибация отменена"),
    );
    expect(createdHeader?.textContent).toContain(
      "Задача транскрибации создана·Информация",
    );
    expect(cancelledHeader?.textContent).toContain(
      "Транскрибация отменена·Информация",
    );
    expect(createdHeader?.textContent).not.toContain("JOB_CREATED");
    expect(cancelledHeader?.textContent).not.toContain("JOB_CANCELLED");
    for (const separator of document.querySelectorAll(
      ".diagnostics-event-header span",
    )) {
      if (separator.textContent === "·")
        expect(separator).not.toHaveAttribute("aria-hidden");
    }
    for (const text of [
      "PROVIDER_REQUEST_FAILED",
      "JOB_COMPLETED",
      "JOB_CANCELLED",
      "API_REQUEST_FAILED",
      "source_count",
      "batch_position",
      "credential_selected",
      "attempt_number",
      "boundary",
      "duration_ms",
      "error_code",
      "provider_error_code",
      "retryable",
      "http_status_category",
      "output_count",
      "final_job_status",
      "endpoint_group",
    ]) {
      expect(screen.queryAllByText(text).length).toBeGreaterThan(0);
    }
    for (const forbidden of [
      "forbidden-source.mp3",
      "https://forbidden.example/report",
      "forbidden transcript",
      "forbidden-secret",
      "req_should_not_render",
      "corr_should_not_render",
      "forbidden arbitrary value",
      "filename",
      "transcript",
      "secret",
      "request_id",
      "correlation_id",
      "arbitrary",
    ]) {
      expect(document.body.textContent).not.toContain(forbidden);
    }
    for (const unsupportedKey of [
      "attempt",
      "duration_seconds",
      "status_category",
      "safe_count",
    ]) {
      expect(screen.queryByText(unsupportedKey, { exact: true })).toBeNull();
    }
  });

  it("localizes unconfigured build identities and inactive DEBUG display state", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string) => {
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
          });
        if (url.endsWith("/api/auth/csrf"))
          return json({ csrf_token: "csrf-after-refresh" });
        if (url.endsWith("/api/credentials"))
          return json({
            credentials: [
              {
                id: "cred-active",
                provider: "elevenlabs",
                label: "Primary STT",
                status: "active",
                masked_value: "••••1234",
                active_version: 2,
              },
            ],
          });
        if (url.endsWith("/api/google/connection"))
          return json({ connected: false, status: null });
        if (url.endsWith("/api/audit-events")) return json({ events: [] });
        if (url.endsWith("/api/diagnostics/system"))
          return json({
            build: { web: "unknown", api: "", worker: undefined },
            diagnostics: { debug_recording: "inactive" },
            google_drive: {},
            provider_credentials: {},
            report_limits: {},
          });
        if (url.includes("/api/diagnostics/events"))
          return json({
            events: [],
            next_cursor: null,
            period: {
              start: "2026-07-16T00:00:00Z",
              end: "2026-07-17T00:00:00Z",
            },
          });
        return json({ ok: true });
      },
    );

    renderApp();
    await openDiagnosticsSettings();

    expect(await screen.findAllByText("не настроено")).toHaveLength(3);
    expect(screen.getByText("неактивна")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("unknown");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("uses Russian labels for known audit events and safe fallback for unknown events", async () => {
    const knownTypes = [
      "admin.bootstrap_created",
      "auth.login_failed",
      "auth.sessions_revoked",
      "credential.created",
      "credential.replaced",
      "credential.revoked",
      "credential.deleted",
      "google.connected",
      "google.disconnected",
      "google.oauth_started",
      "google.oauth_failed",
      "project.created",
      "project.updated",
      "project.archived",
      "project.output_folder.google_picker_set",
      "source.google_drive.created",
      "source.google_picker.created",
      "job.cancelled",
      "job.cancel_requested",
      "unknown.private_event",
    ];
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string) => {
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
          });
        if (url.endsWith("/api/auth/csrf"))
          return json({ csrf_token: "csrf-after-refresh" });
        if (url.endsWith("/api/credentials"))
          return json({
            credentials: [
              {
                id: "cred-active",
                provider: "elevenlabs",
                label: "Primary STT",
                status: "active",
                masked_value: "••••1234",
                active_version: 2,
              },
            ],
          });
        if (url.endsWith("/api/google/connection"))
          return json({ connected: false, status: null });
        if (url.endsWith("/api/audit-events"))
          return json({
            events: knownTypes.map((type, index) => ({
              id: `audit-${index}`,
              type,
              created_at: "2026-07-16T10:00:00Z",
            })),
          });
        if (url.endsWith("/api/diagnostics/system"))
          return json({
            build: {},
            diagnostics: {},
            google_drive: {},
            provider_credentials: {},
            report_limits: {},
          });
        if (url.includes("/api/diagnostics/events"))
          return json({
            events: [],
            next_cursor: null,
            period: {
              start: "2026-07-16T00:00:00Z",
              end: "2026-07-17T00:00:00Z",
            },
          });
        return json({ ok: true });
      },
    );

    renderApp();
    await openDiagnosticsSettings();

    for (const label of [
      "Администратор создан",
      "Неудачная попытка входа",
      "Другие сеансы завершены",
      "Ключ создан",
      "Ключ заменён",
      "Ключ отозван",
      "Ключ удалён",
      "Google Drive подключён",
      "Google Drive отключён",
      "Начато подключение Google Drive",
      "Подключение Google Drive не удалось",
      "Проект создан",
      "Проект обновлён",
      "Проект архивирован",
      "Папка проекта выбрана через Google Drive",
      "Источник Google Drive добавлен",
      "Источники выбраны через Google Drive",
      "Задача отменена",
      "Запрошена отмена задачи",
    ]) {
      expect(screen.getAllByText(new RegExp(label)).length).toBeGreaterThan(0);
    }
    expect(screen.getByText(/Действие Studio/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("unknown.private_event");
    expect(document.body.textContent).not.toContain("job.cancelled");
    expect(document.body.textContent).not.toContain("job.cancel_requested");
  });

  it("shows loading, empty, error, and retry states", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (url: string) => {
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
          });
        if (url.endsWith("/api/auth/csrf"))
          return json({ csrf_token: "csrf-after-refresh" });
        if (url.endsWith("/api/credentials"))
          return json({
            credentials: [
              {
                id: "cred-active",
                provider: "elevenlabs",
                label: "Primary STT",
                status: "active",
                masked_value: "••••1234",
                active_version: 2,
              },
            ],
          });
        if (url.endsWith("/api/google/connection"))
          return json({
            connected: false,
            status: null,
            google_email: null,
            scopes: null,
            connected_at: null,
            revoked_at: null,
          });
        if (url.endsWith("/api/audit-events")) return json({ events: [] });
        if (url.endsWith("/api/diagnostics/system"))
          return json({}, false, 500);
        if (url.includes("/api/diagnostics/events"))
          return json({}, false, 500);
        return json({ ok: true });
      },
    );
    renderApp();
    await openDiagnosticsSettings();
    expect(
      screen.getByText(/Не удалось загрузить состояние/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Повторить загрузку состояния" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Повторить загрузку событий" }),
    ).toBeInTheDocument();
  });

  it("bounds and validates system status before explicit retry", async () => {
    installBasicPlatformSettingsFixture();
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = fetchMock.getMockImplementation();
    const systemSignals: AbortSignal[] = [];
    let systemGets = 0;
    fetchMock.mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/diagnostics/system")) {
          systemGets += 1;
          const signal = init?.signal;
          if (!signal) throw new Error("system status signal is missing");
          systemSignals.push(signal);
          if (systemGets === 1) {
            return json({
              build: { web: { raw: "raw-build-secret" } },
              diagnostics: {},
              google_drive: {},
              provider_credentials: {},
              report_limits: {},
            });
          }
          return json({
            environment: "production",
            build: { web: "web-safe", api: "api-safe", worker: "worker-safe" },
            diagnostics: {},
            google_drive: {},
            provider_credentials: {},
            report_limits: {},
            raw_system_field: "raw-system-secret",
          });
        }
        return defaultFetch?.(input, init) ?? json({});
      },
    );
    const timeoutSpy = vi.spyOn(globalThis, "setTimeout");

    try {
      renderApp();
      await openDiagnosticsSettings();
      expect(
        await screen.findByText("Не удалось загрузить состояние."),
      ).toBeInTheDocument();
      expect(systemSignals[0]?.aborted).toBe(false);
      expect(timeoutSpy).toHaveBeenCalledWith(expect.any(Function), 15_000);
      expect(document.body.textContent).not.toContain("raw-build-secret");

      await userEvent.click(
        screen.getByRole("button", { name: "Повторить загрузку состояния" }),
      );
      expect(await screen.findByText("web-safe")).toBeInTheDocument();
      expect(document.body.textContent).not.toContain("raw-system-secret");
      expect(systemGets).toBe(2);
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("keeps filtered events latest-wins and paginates single-flight", async () => {
    installBasicPlatformSettingsFixture();
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = fetchMock.getMockImplementation();
    let eventGets = 0;
    let staleSignal: AbortSignal | undefined;
    let resolveStale: ((response: Response) => void) | undefined;
    let resolvePage: ((response: Response) => void) | undefined;
    const period = {
      start: "2026-07-16T00:00:00Z",
      end: "2026-07-17T00:00:00Z",
    };
    const event = (id: string, level: "ERROR" | "WARNING" | "INFO") => ({
      id,
      occurred_at: "2026-07-16T09:00:00Z",
      level,
      component: "api",
      event_code: id,
      occurrence_count: 1,
    });
    fetchMock.mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/api/diagnostics/events")) {
          eventGets += 1;
          if (eventGets === 1) {
            return json({
              events: [event("INITIAL_EVENT", "INFO")],
              next_cursor: null,
              period,
            });
          }
          if (eventGets === 2) {
            staleSignal = init?.signal;
            return new Promise<Response>((resolve) => {
              resolveStale = resolve;
            });
          }
          if (eventGets === 3) {
            return json({
              events: [{ ...event("MALFORMED_EVENT", "WARNING"), level: "RAW" }],
              next_cursor: null,
              period,
              raw_events_field: "raw-events-secret",
            });
          }
          if (eventGets === 4) {
            return json({
              events: [
                {
                  ...event("LATEST_EVENT", "WARNING"),
                  metadata: {
                    retryable: true,
                    transcript: "raw-transcript-secret",
                  },
                  raw_event_field: "raw-event-secret",
                },
              ],
              next_cursor: "safe-cursor",
              period,
            });
          }
          return new Promise<Response>((resolve) => {
            resolvePage = resolve;
          });
        }
        return defaultFetch?.(input, init) ?? json({});
      },
    );

    renderApp();
    await openDiagnosticsSettings();
    expect(await screen.findByText("INITIAL_EVENT")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Уровень"), "ERROR");
    await userEvent.click(
      screen.getByRole("button", { name: "Обновить события" }),
    );
    await waitFor(() => expect(resolveStale).toBeDefined());
    await userEvent.selectOptions(screen.getByLabelText("Уровень"), "WARNING");
    await userEvent.click(
      screen.getByRole("button", { name: "Обновить события" }),
    );
    expect(
      await screen.findByText("Не удалось загрузить события."),
    ).toBeInTheDocument();
    expect(staleSignal?.aborted).toBe(true);
    expect(screen.queryByText("MALFORMED_EVENT")).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Повторить загрузку событий" }),
    );
    expect(await screen.findByText("LATEST_EVENT")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("raw-events-secret");
    expect(document.body.textContent).not.toContain("raw-event-secret");
    expect(document.body.textContent).not.toContain("raw-transcript-secret");

    const more = screen.getByRole("button", { name: "Показать ещё" });
    fireEvent.click(more);
    fireEvent.click(more);
    expect(eventGets).toBe(5);
    await act(async () =>
      resolvePage?.(
        await json({
          events: [
            event("LATEST_EVENT", "WARNING"),
            event("PAGE_EVENT", "INFO"),
          ],
          next_cursor: null,
          period,
        }),
      ),
    );
    expect(await screen.findByText("PAGE_EVENT")).toBeInTheDocument();
    expect(screen.getAllByText("LATEST_EVENT")).toHaveLength(1);

    await act(async () =>
      resolveStale?.(
        await json({
          events: [event("STALE_EVENT", "ERROR")],
          next_cursor: null,
          period,
        }),
      ),
    );
    expect(screen.queryByText("STALE_EVENT")).not.toBeInTheDocument();
  });

  it("aborts system and event read ownership on diagnostics teardown", async () => {
    installBasicPlatformSettingsFixture();
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const defaultFetch = fetchMock.getMockImplementation();
    let systemSignal: AbortSignal | undefined;
    let eventsSignal: AbortSignal | undefined;
    let resolveSystem: ((response: Response) => void) | undefined;
    let resolveEvents: ((response: Response) => void) | undefined;
    fetchMock.mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/diagnostics/system")) {
          systemSignal = init?.signal;
          return new Promise<Response>((resolve) => {
            resolveSystem = resolve;
          });
        }
        if (url.includes("/api/diagnostics/events")) {
          eventsSignal = init?.signal;
          return new Promise<Response>((resolve) => {
            resolveEvents = resolve;
          });
        }
        return defaultFetch?.(input, init) ?? json({});
      },
    );

    renderApp();
    await openDiagnosticsSettings();
    await waitFor(() => {
      expect(resolveSystem).toBeDefined();
      expect(resolveEvents).toBeDefined();
    });
    await userEvent.click(screen.getByRole("tab", { name: "Аккаунт" }));
    expect(systemSignal?.aborted).toBe(true);
    expect(eventsSignal?.aborted).toBe(true);

    await act(async () => {
      resolveSystem?.(
        await json({
          environment: "late-system",
          build: {},
          diagnostics: {},
          google_drive: {},
          provider_credentials: {},
          report_limits: {},
        }),
      );
      resolveEvents?.(
        await json({
          events: [
            {
              id: "LATE_EVENT",
              occurred_at: "2026-07-16T09:00:00Z",
              level: "INFO",
              component: "api",
              event_code: "LATE_EVENT",
            },
          ],
          next_cursor: null,
          period: {
            start: "2026-07-16T00:00:00Z",
            end: "2026-07-17T00:00:00Z",
          },
        }),
      );
    });
    expect(screen.queryByText("late-system")).not.toBeInTheDocument();
    expect(screen.queryByText("LATE_EVENT")).not.toBeInTheDocument();
  });
});

describe("PWA API diagnostics instrumentation", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    clearPwaDiagnosticsSession();
    configurePwaDiagnosticsSession({ csrf: "csrf-safe", debugActive: false });
  });

  function postedPwaEvents(fetchMock: ReturnType<typeof vi.fn>) {
    return fetchMock.mock.calls
      .filter(([url]) => String(url).endsWith("/api/diagnostics/pwa-events"))
      .flatMap(
        ([, init]) => JSON.parse(String((init as RequestInit).body)).events,
      );
  }

  it("emits no event for successful requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await __appDiagnosticsTest.api("/projects");
    expect(postedPwaEvents(fetchMock)).toHaveLength(0);
  });

  it("emits one safe event for direct network failure and omits raw path", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error("synthetic-network-detail"))
      .mockResolvedValue(json({ accepted: true }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(
      __appDiagnosticsTest.api("/jobs/synthetic-id"),
    ).rejects.toThrow();
    await waitFor(() => expect(postedPwaEvents(fetchMock)).toHaveLength(1));
    const payload = JSON.stringify(postedPwaEvents(fetchMock));
    expect(payload).toContain("jobs");
    expect(payload).not.toContain("synthetic-id");
    expect(payload).not.toContain("synthetic-network-detail");
  });

  it("emits one safe event for direct 5xx", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ ok: false }, false, 503))
      .mockResolvedValue(json({ accepted: true }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(
      __appDiagnosticsTest.api("/sources/synthetic-id"),
    ).rejects.toThrow();
    await waitFor(() => expect(postedPwaEvents(fetchMock)).toHaveLength(1));
    expect(postedPwaEvents(fetchMock)[0].metadata).toMatchObject({
      endpoint_group: "sources",
      http_status_category: "5xx",
      retryable: true,
    });
  });

  it("emits nothing for recovered CSRF retry", async () => {
    const onCsrf = vi.fn();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        json({ detail: { reason: "csrf_token_invalid" } }, false, 403),
      )
      .mockResolvedValueOnce(json({ csrf_token: "csrf-new" }))
      .mockResolvedValueOnce(json({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await __appDiagnosticsTest.csrfMutate("/projects", "csrf-old", onCsrf, {
      method: "POST",
      body: "{}",
    });
    expect(onCsrf).toHaveBeenCalledWith("csrf-new");
    expect(postedPwaEvents(fetchMock)).toHaveLength(0);
  });

  it("emits exactly one for final failed CSRF retry and does not retry non-CSRF failures", async () => {
    const onCsrf = vi.fn();
    let fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        json({ detail: { reason: "csrf_token_invalid" } }, false, 403),
      )
      .mockResolvedValueOnce(json({ csrf_token: "csrf-new" }))
      .mockResolvedValueOnce(json({ ok: false }, false, 500))
      .mockResolvedValue(json({ accepted: true }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(
      __appDiagnosticsTest.csrfMutate("/credentials", "csrf-old", onCsrf, {
        method: "POST",
        body: "{}",
      }),
    ).rejects.toThrow();
    await waitFor(() => expect(postedPwaEvents(fetchMock)).toHaveLength(1));

    fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ ok: false }, false, 400))
      .mockResolvedValue(json({ accepted: true }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(
      __appDiagnosticsTest.csrfMutate("/projects", "csrf-old", onCsrf, {
        method: "POST",
        body: "{}",
      }),
    ).rejects.toThrow();
    await waitFor(() => expect(postedPwaEvents(fetchMock)).toHaveLength(1));
    expect(
      fetchMock.mock.calls
        .map(([url]) => String(url))
        .filter((url) => url.endsWith("/api/auth/csrf")),
    ).toHaveLength(0);
  });

  it("emits one original-operation event when CSRF refresh fails", async () => {
    for (const refreshFailure of [
      {
        response: Promise.reject(new Error("synthetic-refresh-network")),
        category: "unknown",
      },
      { response: json({ ok: false }, false, 503), category: "5xx" },
    ]) {
      clearPwaDiagnosticsSession();
      configurePwaDiagnosticsSession({ csrf: "csrf-safe", debugActive: false });
      const onCsrf = vi.fn();
      const fetchMock = vi
        .fn()
        .mockResolvedValueOnce(
          json({ detail: { reason: "csrf_token_invalid" } }, false, 403),
        )
        .mockImplementationOnce(() => refreshFailure.response)
        .mockResolvedValue(json({ accepted: true }));
      vi.stubGlobal("fetch", fetchMock);

      await expect(
        __appDiagnosticsTest.csrfMutate("/projects", "csrf-old", onCsrf, {
          method: "POST",
          body: "{}",
        }),
      ).rejects.toThrow();
      await waitFor(() => expect(postedPwaEvents(fetchMock)).toHaveLength(1));
      expect(postedPwaEvents(fetchMock)[0].metadata).toMatchObject({
        endpoint_group: "projects",
        http_status_category: refreshFailure.category,
      });
      expect(JSON.stringify(postedPwaEvents(fetchMock))).not.toContain("auth");
      expect(JSON.stringify(postedPwaEvents(fetchMock))).not.toContain(
        "synthetic-refresh-network",
      );
      expect(onCsrf).not.toHaveBeenCalled();
    }
  });

  it("does not recursively emit when diagnostics ingestion fails", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ ok: false }, false, 500))
      .mockRejectedValueOnce(new Error("synthetic-ingestion-failure"));
    vi.stubGlobal("fetch", fetchMock);
    await expect(
      __appDiagnosticsTest.api("/diagnostics/events"),
    ).rejects.toThrow();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(
      fetchMock.mock.calls.filter(([url]) =>
        String(url).endsWith("/api/diagnostics/pwa-events"),
      ),
    ).toHaveLength(1);
  });
});

describe("Settings DEBUG session controls", () => {
  beforeEach(() => {
    cleanup();
    vi.restoreAllMocks();
    clearPwaDiagnosticsSession();
    window.history.replaceState({}, "", "/");
  });

  function installSettingsFetch(
    debugResponses: Array<
      | {
          active: boolean;
          started_at?: string | null;
          expires_at?: string | null;
        }
      | Response
    >,
  ) {
    const debugGets: string[] = [];
    const posts: unknown[] = [];
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "safe@example.test", role: "user" },
          });
        if (url.endsWith("/api/auth/csrf"))
          return json({ csrf_token: "csrf-safe" });
        if (url.endsWith("/api/audit-events")) return json({ events: [] });
        if (url.endsWith("/api/credentials"))
          return json({
            credentials: [
              {
                id: "cred-active",
                provider: "elevenlabs",
                label: "Primary STT",
                status: "active",
                masked_value: "••••1234",
                active_version: 2,
              },
            ],
          });
        if (url.endsWith("/api/google/connection"))
          return json({ connected: false });
        if (url.endsWith("/api/diagnostics/system"))
          return json({
            build: {},
            diagnostics: {},
            google_drive: {},
            provider_credentials: {},
            report_limits: {},
          });
        if (url.includes("/api/diagnostics/events"))
          return json({
            events: [],
            next_cursor: null,
            period: {
              start: "2026-07-16T00:00:00Z",
              end: "2026-07-17T00:00:00Z",
            },
          });
        if (
          url.endsWith("/api/diagnostics/debug-session") &&
          (!init?.method || init.method === "GET")
        ) {
          debugGets.push(url);
          const next = debugResponses.shift() ?? {
            active: false,
            started_at: null,
            expires_at: null,
          };
          return next instanceof Response ? next : json(next);
        }
        if (
          url.endsWith("/api/diagnostics/debug-session") &&
          init?.method === "POST"
        ) {
          posts.push(JSON.parse(String(init.body)));
          return json({
            active: true,
            started_at: new Date(Date.now()).toISOString(),
            expires_at: new Date(Date.now() + 600000).toISOString(),
          });
        }
        if (
          url.endsWith("/api/diagnostics/debug-session") &&
          init?.method === "DELETE"
        )
          return json({ active: false, started_at: null, expires_at: null });
        if (url.endsWith("/api/diagnostics/pwa-events"))
          return json({ accepted: true });
        return json({});
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    return { fetchMock, debugGets, posts };
  }

  async function openDiagnostics() {
    renderApp();
    await screen.findByText("Настройки");
    await userEvent.click(
      screen.getAllByRole("button", { name: "Настройки" })[0],
    );
    await userEvent.click(screen.getByRole("tab", { name: "Для поддержки" }));
  }

  it("renders loading, inactive defaults, active status, start and stop flows without browser storage", async () => {
    const storageSpy = vi.spyOn(Storage.prototype, "setItem");
    const { posts } = installSettingsFetch([
      { active: false, started_at: null, expires_at: null },
      { active: false, started_at: null, expires_at: null },
    ]);
    await openDiagnostics();
    expect(await screen.findByText("DEBUG не активна")).toBeInTheDocument();
    const duration = screen.getByLabelText(
      "Длительность DEBUG",
    ) as HTMLSelectElement;
    expect(duration.value).toBe("10");
    expect(
      within(duration).getByRole("option", { name: "5 минут" }),
    ).toBeInTheDocument();
    expect(
      within(duration).getByRole("option", { name: "30 минут" }),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Включить DEBUG" }),
    );
    expect(await screen.findByText("DEBUG активна")).toBeInTheDocument();
    expect(posts).toEqual([{ duration_minutes: 10 }]);
    await userEvent.click(
      screen.getByRole("button", { name: "Остановить DEBUG" }),
    );
    expect(await screen.findByText("DEBUG не активна")).toBeInTheDocument();
    expect(storageSpy).not.toHaveBeenCalled();
  });

  it("refreshes on 409 conflict without issuing a second POST", async () => {
    const debugGets: string[] = [];
    let postCount = 0;
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "safe@example.test", role: "user" },
          });
        if (url.endsWith("/api/auth/csrf"))
          return json({ csrf_token: "csrf-safe" });
        if (url.endsWith("/api/audit-events")) return json({ events: [] });
        if (url.endsWith("/api/credentials"))
          return json({
            credentials: [
              {
                id: "cred-active",
                provider: "elevenlabs",
                label: "Primary STT",
                status: "active",
                masked_value: "••••1234",
                active_version: 2,
              },
            ],
          });
        if (url.endsWith("/api/google/connection"))
          return json({ connected: false });
        if (url.endsWith("/api/diagnostics/system"))
          return json({
            build: {},
            diagnostics: {},
            google_drive: {},
            provider_credentials: {},
            report_limits: {},
          });
        if (url.includes("/api/diagnostics/events"))
          return json({
            events: [],
            next_cursor: null,
            period: {
              start: "2026-07-16T00:00:00Z",
              end: "2026-07-17T00:00:00Z",
            },
          });
        if (
          url.endsWith("/api/diagnostics/debug-session") &&
          (!init?.method || init.method === "GET")
        ) {
          debugGets.push(url);
          return debugGets.length === 1
            ? json({ active: false, started_at: null, expires_at: null })
            : json({
                active: true,
                started_at: new Date(Date.now()).toISOString(),
                expires_at: new Date(Date.now() + 600000).toISOString(),
              });
        }
        if (
          url.endsWith("/api/diagnostics/debug-session") &&
          init?.method === "POST"
        ) {
          postCount += 1;
          return json({ detail: "conflict" }, false, 409);
        }
        if (url.endsWith("/api/diagnostics/pwa-events"))
          return json({ accepted: true });
        return json({});
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    await openDiagnostics();
    await userEvent.click(
      await screen.findByRole("button", { name: "Включить DEBUG" }),
    );
    await screen.findByText(
      "DEBUG уже активна в другой вкладке. Статус обновлён.",
    );
    expect(postCount).toBe(1);
    expect(debugGets).toHaveLength(2);
  });

  it("uses refreshed CSRF for ingestion after DEBUG start retry", async () => {
    const oldToken = "csrf-old-safe";
    const newToken = "csrf-new-safe";
    const expiresAt = new Date(Date.now() + 600000).toISOString();
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/auth/session"))
          return json({
            authenticated: true,
            user: { email: "safe@example.test", role: "user" },
          });
        if (url.endsWith("/api/auth/csrf") && init?.method === "POST")
          return json({ csrf_token: newToken });
        if (url.endsWith("/api/auth/csrf"))
          return json({ csrf_token: oldToken });
        if (url.endsWith("/api/audit-events")) return json({ events: [] });
        if (url.endsWith("/api/credentials"))
          return json({
            credentials: [
              {
                id: "cred-active",
                provider: "elevenlabs",
                label: "Primary STT",
                status: "active",
                masked_value: "••••1234",
                active_version: 2,
              },
            ],
          });
        if (url.endsWith("/api/google/connection"))
          return json({ connected: false });
        if (url.endsWith("/api/diagnostics/system"))
          return json({
            build: {},
            diagnostics: {},
            google_drive: {},
            provider_credentials: {},
            report_limits: {},
          });
        if (url.includes("/api/diagnostics/events"))
          return json({
            events: [],
            next_cursor: null,
            period: {
              start: "2026-07-16T00:00:00Z",
              end: "2026-07-17T00:00:00Z",
            },
          });
        if (
          url.endsWith("/api/diagnostics/debug-session") &&
          (!init?.method || init.method === "GET")
        )
          return json({ active: false, started_at: null, expires_at: null });
        if (
          url.endsWith("/api/diagnostics/debug-session") &&
          init?.method === "POST" &&
          (init.headers as Record<string, string>)["x-csrf-token"] === oldToken
        )
          return json(
            { detail: { reason: "csrf_token_invalid" } },
            false,
            403,
          );
        if (
          url.endsWith("/api/diagnostics/debug-session") &&
          init?.method === "POST"
        )
          return json({
            active: true,
            started_at: new Date(Date.now()).toISOString(),
            expires_at: expiresAt,
          });
        if (url.endsWith("/api/diagnostics/pwa-events"))
          return json({ accepted: true });
        return json({});
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    await openDiagnostics();
    await userEvent.click(
      await screen.findByRole("button", { name: "Включить DEBUG" }),
    );
    expect(await screen.findByText("DEBUG активна")).toBeInTheDocument();

    emitPwaDiagnostic(
      "PWA_API_REQUEST_FAILED",
      {
        boundary: "api_request",
        error_code: "api_request_failed",
        retryable: true,
      },
      { dedupe: false },
    );
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([url]) =>
          String(url).endsWith("/api/diagnostics/pwa-events"),
        ),
      ).toBe(true),
    );
    const ingestion = fetchMock.mock.calls.find(([url]) =>
      String(url).endsWith("/api/diagnostics/pwa-events"),
    )?.[1] as RequestInit;
    expect(ingestion.headers).toMatchObject({ "x-csrf-token": newToken });
    expect(JSON.stringify(ingestion)).not.toContain(oldToken);
  });

  it("CSRF refresh during another mutation preserves DEBUG until inactive server status clears it", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        json({ detail: { reason: "csrf_token_invalid" } }, false, 403),
      )
      .mockResolvedValueOnce(json({ csrf_token: "csrf-rotated" }))
      .mockResolvedValueOnce(json({ ok: true }))
      .mockResolvedValue(json({ accepted: true }));
    vi.stubGlobal("fetch", fetchMock);
    clearPwaDiagnosticsSession();
    configurePwaDiagnosticsSession({
      csrf: "csrf-old",
      debugActive: true,
      expiresAt: new Date(Date.now() + 60000).toISOString(),
    });
    await __appDiagnosticsTest.csrfMutate(
      "/projects",
      "csrf-old",
      (token) => configurePwaDiagnosticsSession({ csrf: token }),
      { method: "POST", body: "{}" },
    );
    emitPwaDiagnostic(
      "PWA_API_REQUEST_FAILED",
      {
        boundary: "api_request",
        error_code: "api_request_failed",
        retryable: true,
      },
      { dedupe: false },
    );
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([url]) =>
          String(url).endsWith("/api/diagnostics/pwa-events"),
        ),
      ).toBe(true),
    );
    expect(postedPwaEventsFrom(fetchMock).at(-1)?.level).toBe("DEBUG");

    configurePwaDiagnosticsSession({
      csrf: "csrf-rotated",
      debugActive: false,
    });
    emitPwaDiagnostic(
      "PWA_API_REQUEST_FAILED",
      {
        boundary: "api_request",
        error_code: "api_request_failed",
        retryable: true,
      },
      { dedupe: false },
    );
    await waitFor(() => expect(postedPwaEventsFrom(fetchMock)).toHaveLength(2));
    expect(postedPwaEventsFrom(fetchMock).at(-1)?.level).toBeUndefined();
  });

  it("bounds and validates DEBUG status reads before explicit retry", async () => {
    const { fetchMock } = installSettingsFetch([]);
    const defaultFetch = fetchMock.getMockImplementation();
    const debugSignals: AbortSignal[] = [];
    let debugGets = 0;
    fetchMock.mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (
          url.endsWith("/api/diagnostics/debug-session") &&
          (!init?.method || init.method === "GET")
        ) {
          debugGets += 1;
          if (debugGets === 1) {
            const signal = init?.signal;
            if (!signal) throw new Error("DEBUG status signal is missing");
            debugSignals.push(signal);
            return new Promise<Response>((_resolve, reject) => {
              signal.addEventListener("abort", () => reject(signal.reason));
            });
          }
          if (debugGets === 2) {
            return json({
              active: "raw-active",
              raw_debug_field: "raw-debug-secret",
            });
          }
          return json({ active: false, raw_ignored_field: "raw-ignored" });
        }
        return defaultFetch?.(input, init) ?? json({});
      },
    );
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 15_000 ? 1 : (delay as number),
          ...args,
        )) as typeof setTimeout);

    try {
      await openDiagnostics();
      expect(
        await screen.findByText("Не удалось загрузить статус DEBUG."),
      ).toBeInTheDocument();
      expect(debugSignals[0]?.aborted).toBe(true);

      await userEvent.click(
        screen.getByRole("button", { name: "Повторить проверку DEBUG" }),
      );
      expect(
        await screen.findByText("Не удалось загрузить статус DEBUG."),
      ).toBeInTheDocument();
      expect(document.body.textContent).not.toContain("raw-active");
      expect(document.body.textContent).not.toContain("raw-debug-secret");

      await userEvent.click(
        screen.getByRole("button", { name: "Повторить проверку DEBUG" }),
      );
      expect(await screen.findByText("DEBUG не активна")).toBeInTheDocument();
      expect(document.body.textContent).not.toContain("raw-ignored");
      expect(debugGets).toBe(3);
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("reconciles bounded DEBUG start and stop without mutation replay", async () => {
    const { fetchMock } = installSettingsFetch([]);
    const defaultFetch = fetchMock.getMockImplementation();
    let debugGets = 0;
    let startCalls = 0;
    let stopCalls = 0;
    let startSignal: AbortSignal | undefined;
    const startedAt = new Date(Date.now()).toISOString();
    const expiresAt = new Date(Date.now() + 600000).toISOString();
    fetchMock.mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (
          url.endsWith("/api/diagnostics/debug-session") &&
          (!init?.method || init.method === "GET")
        ) {
          debugGets += 1;
          return debugGets === 2
            ? json({ active: true, started_at: startedAt, expires_at: expiresAt })
            : json({ active: false });
        }
        if (
          url.endsWith("/api/diagnostics/debug-session") &&
          init?.method === "POST"
        ) {
          startCalls += 1;
          startSignal = init.signal;
          if (!startSignal) throw new Error("DEBUG start signal is missing");
          return new Promise<Response>((_resolve, reject) => {
            startSignal?.addEventListener("abort", () =>
              reject(startSignal?.reason),
            );
          });
        }
        if (
          url.endsWith("/api/diagnostics/debug-session") &&
          init?.method === "DELETE"
        ) {
          stopCalls += 1;
          return json({
            active: "raw-stopped",
            raw_stop_field: "raw-stop-secret",
          });
        }
        return defaultFetch?.(input, init) ?? json({});
      },
    );
    const nativeSetTimeout = globalThis.setTimeout.bind(globalThis);
    const timeoutSpy = vi
      .spyOn(globalThis, "setTimeout")
      .mockImplementation(((callback, delay, ...args) =>
        nativeSetTimeout(
          callback,
          delay === 20_000 ? 1 : (delay as number),
          ...args,
        )) as typeof setTimeout);

    try {
      await openDiagnostics();
      const start = await screen.findByRole("button", {
        name: "Включить DEBUG",
      });
      fireEvent.click(start);
      fireEvent.click(start);
      expect(
        await screen.findByText("DEBUG включена. Статус подтверждён."),
      ).toBeInTheDocument();
      expect(startSignal?.aborted).toBe(true);
      expect(startCalls).toBe(1);
      expect(debugGets).toBe(2);

      const stop = screen.getByRole("button", { name: "Остановить DEBUG" });
      fireEvent.click(stop);
      fireEvent.click(stop);
      expect(
        await screen.findByText("DEBUG остановлена. Статус подтверждён."),
      ).toBeInTheDocument();
      expect(stopCalls).toBe(1);
      expect(debugGets).toBe(3);
      expect(document.body.textContent).not.toContain("raw-stopped");
      expect(document.body.textContent).not.toContain("raw-stop-secret");
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("aborts DEBUG mutation ownership on diagnostics teardown", async () => {
    const { fetchMock } = installSettingsFetch([
      { active: false, started_at: null, expires_at: null },
    ]);
    const defaultFetch = fetchMock.getMockImplementation();
    let startSignal: AbortSignal | undefined;
    let resolveStart: ((response: Response) => void) | undefined;
    let startCalls = 0;
    fetchMock.mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (
          url.endsWith("/api/diagnostics/debug-session") &&
          init?.method === "POST"
        ) {
          startCalls += 1;
          startSignal = init.signal;
          return new Promise<Response>((resolve) => {
            resolveStart = resolve;
          });
        }
        return defaultFetch?.(input, init) ?? json({});
      },
    );

    await openDiagnostics();
    await userEvent.click(
      await screen.findByRole("button", { name: "Включить DEBUG" }),
    );
    await waitFor(() => expect(resolveStart).toBeDefined());
    await userEvent.click(screen.getByRole("tab", { name: "Аккаунт" }));

    expect(startSignal?.aborted).toBe(true);
    await act(async () =>
      resolveStart?.(
        await json({
          active: true,
          started_at: new Date(Date.now()).toISOString(),
          expires_at: new Date(Date.now() + 600000).toISOString(),
        }),
      ),
    );
    expect(startCalls).toBe(1);
    expect(
      screen.queryByText("DEBUG включена."),
    ).not.toBeInTheDocument();
  });

  it("expires local DEBUG once and failed refresh does not poll every second", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const expiresAt = new Date(Date.now() + 1000).toISOString();
    const { debugGets } = installSettingsFetch([
      {
        active: true,
        started_at: new Date(Date.now()).toISOString(),
        expires_at: expiresAt,
      },
      new Response("{}", { status: 500 }),
    ]);
    await openDiagnostics();
    expect(await screen.findByText("DEBUG активна")).toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    expect(
      await screen.findByText("Не удалось загрузить статус DEBUG."),
    ).toBeInTheDocument();
    const afterExpiryGets = debugGets.length;
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    expect(debugGets).toHaveLength(afterExpiryGets);
    vi.useRealTimers();
  });
});

async function clickCredentialAction(label: string) {
  await userEvent.click(await screen.findByRole("button", { name: "Другие действия с ключом Primary STT" }));
  await userEvent.click(screen.getByRole("menuitem", { name: label }));
}
