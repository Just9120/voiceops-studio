import {
  isUsableJobSource,
  parsePreparedAudioContext,
  reconcileOptimisticSources,
  sourceСтатусLabel,
  unusableJobSourceReason,
  type Source,
} from "./sourceModel";

const uploadedSource: Source = {
  id: "source-1",
  project_id: "project-1",
  source_type: "local_upload",
  original_filename: "recording.ogg",
  mime_type: "audio/ogg",
  size_bytes: 1024,
  drive_file_url: null,
  upload_status: "uploaded",
  uploaded_at: "2026-07-22T09:00:00Z",
  expires_at: null,
  deleted_at: null,
  delete_reason: null,
  created_at: "2026-07-22T08:00:00Z",
  updated_at: "2026-07-22T09:00:00Z",
};

describe("source model", () => {
  it("preserves an explicit original-timeline claim and keeps private receipts out of the projection", () => {
    const context = { job_id: "a".repeat(36), input_duration_ms: 15000, output_duration_ms: 10000,
      pauses_removed: true, original_timeline_available: true };
    expect(parsePreparedAudioContext({ ...context, content_sha256: "private", timeline_sha256: "private" })).toEqual(context);
    expect(parsePreparedAudioContext({ ...context, original_timeline_available: "true" })).toBeNull();
  });
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-22T10:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("retains a new optimistic source until the API confirms its ID", () => {
    const optimistic = { ...uploadedSource, id: "optimistic" };

    expect(reconcileOptimisticSources([optimistic], [])).toEqual([
      optimistic,
    ]);
  });

  it("retires an optimistic source after the API confirms its ID", () => {
    const optimistic = { ...uploadedSource, id: "confirmed" };
    const authoritative = {
      ...optimistic,
      updated_at: "2026-07-22T10:01:00Z",
    };

    expect(
      reconcileOptimisticSources([optimistic], [authoritative]),
    ).toEqual([]);
  });

  it.each([
    [uploadedSource, true],
    [{ ...uploadedSource, source_type: "google_drive" }, true],
    [{ ...uploadedSource, expires_at: "2026-07-22T11:00:00Z" }, true],
    [{ ...uploadedSource, upload_status: "pending" }, false],
    [{ ...uploadedSource, deleted_at: "2026-07-22T09:30:00Z" }, false],
    [{ ...uploadedSource, expires_at: "2026-07-22T10:00:00Z" }, false],
  ] as const)("evaluates job-source usability %#", (source, expected) => {
    expect(isUsableJobSource(source)).toBe(expected);
  });

  it("fails closed for an unexpected source type", () => {
    const source = {
      ...uploadedSource,
      source_type: "unexpected-provider",
    } as unknown as Source;

    expect(isUsableJobSource(source)).toBe(false);
    expect(unusableJobSourceReason(source)).toBe(
      "Тип файла не поддерживается для задачи",
    );
  });

  it.each([
    [
      {
        ...uploadedSource,
        deleted_at: "2026-07-22T09:30:00Z",
        expires_at: "2026-07-22T09:00:00Z",
      },
      "Убранный из Studio файл нельзя добавить в задачу",
    ],
    [
      { ...uploadedSource, expires_at: "2026-07-22T09:00:00Z" },
      "Срок хранения временной копии истёк",
    ],
    [
      { ...uploadedSource, upload_status: "failed" },
      "Файл ещё не готов для задачи",
    ],
  ] as const)("explains unusable sources %#", (source, expected) => {
    expect(unusableJobSourceReason(source)).toBe(expected);
  });

  it.each([
    ["pending", "Загружается"],
    ["uploaded", "Готов"],
    ["deleted", "Убран из Studio"],
    ["expired", "Срок истёк"],
    ["failed", "Ошибка"],
  ] as const)("labels %s status", (status, expected) => {
    expect(sourceСтатусLabel(status)).toBe(expected);
  });
});
