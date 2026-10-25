import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as googlePicker from "./googlePicker";
import { AudioPreparationPage } from "./AudioPreparationPage";
beforeEach(() => sessionStorage.clear());

function json(value: unknown) {
  return new Response(JSON.stringify(value), { status: 200, headers: { "content-type": "application/json" } });
}

function source(id: string, filename: string, createdAt: string | null) {
  return {
    id,
    project_id: "project-id",
    source_type: "local_upload",
    original_filename: filename,
    mime_type: "audio/wav",
    size_bytes: 100,
    drive_file_url: null,
    upload_status: "uploaded",
    uploaded_at: "2026-08-24T20:00:00Z",
    source_created_at: createdAt,
    source_created_at_provenance: createdAt ? "embedded_media_metadata" : null,
    expires_at: "2027-08-25T20:00:00Z",
    deleted_at: null,
    delete_reason: null,
    created_at: "2026-08-24T20:00:00Z",
    updated_at: "2026-08-24T20:00:00Z",
  };
}

function previewJob(id: string, title: string, sourceIds: string[]) {
  return {
    id,
    status: "preview_queued",
    title,
    options: { output_format: "copy" },
    input_count: sourceIds.length,
    inputs: sourceIds.map((sourceId, position) => ({ position, filename: sourceId, source_type: "local_upload", ephemeral_reference: false })),
    preview: null,
    progress: { percent: 0, stage: "preview_queued" },
    output: null,
    error_code: null,
  };
}

describe("AudioPreparationPage", () => {
  it("blocks a restored removed source and lets the user clear only unavailable selections", async () => {
    sessionStorage.setItem("studio-form-draft:v1:audio:project-id", JSON.stringify({sourceMode:"studio",selected:["removed-source"]}));
    const fetchMock = vi.fn(async(input: RequestInfo | URL, init?: RequestInit) => {
      const url=String(input);
      if(url.endsWith("/workspace")) return json({project:{id:"project-id",title:"Studio"}});
      if(url.endsWith("/sources")) return json({sources:[]});
      if(url.endsWith("/audio-preparations") && (init?.method ?? "GET") === "GET") return json({jobs:[]});
      throw new Error("Unexpected request");
    });
    vi.stubGlobal("fetch",fetchMock);
    render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()}/>);
    const clear = await screen.findByRole("button",{name:"Убрать недоступные файлы из плана"});
    expect(screen.getByRole("button",{name:"Проверить файлы и рассчитать"})).toBeDisabled();
    expect(screen.getByText("Недоступный файл")).toBeInTheDocument();
    await userEvent.click(clear);
    expect(screen.queryByText("Недоступный файл")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([,init])=>(init as RequestInit|undefined)?.method==="POST" && String((init as RequestInit)?.body).includes("removed-source"))).toBe(false);
  });
  afterEach(() => vi.unstubAllGlobals());

  it.each(["source", "folder", "result"])("offers Google recovery after rejected authorization in the %s flow", async (flow) => {
    const ready = { ...previewJob("ready", "Готовое аудио", []), status: "completed", progress: { percent: 100, stage: "completed" }, output: { download_ready: true, source_id: "out", google_drive_url: null } };
    const picker = vi.spyOn(googlePicker, "openGooglePicker").mockResolvedValue({ action: "cancel" });
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/workspace")) return json({ project: { id: "project-id", title: "Studio" } });
      if (url.endsWith("/sources")) return json({ sources: [] });
      if (url.endsWith("/audio-preparations")) return json({ jobs: [ready] });
      if (url.endsWith("/picker/session")) return new Response(JSON.stringify({ detail: "google_reauthorization_required" }), { status: 409 });
      throw new Error(`Unexpected mutation: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()} />);
    await screen.findByRole("heading", { name: "Готовое аудио" });
    if (flow === "folder") await userEvent.click(screen.getByRole("checkbox", { name: "Автоматически сохранить копию в Google Drive" }));
    const label = flow === "source" ? "Выбрать файлы в Google Drive" : flow === "folder" ? "Выбрать папку" : "Сохранить в Google Drive";
    await userEvent.click(screen.getByRole("button", { name: label, exact: true }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Переподключите Google Drive в настройках и повторите выбор.");
    expect(screen.queryByText("google_reauthorization_required")).not.toBeInTheDocument();
    expect(picker).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: label, exact: true })).toBeEnabled();
    expect(screen.getByRole("link", { name: "Скачать файл" })).toBeVisible();
    const navigate = vi.fn();
    window.addEventListener("studio:navigate-settings", navigate);
    await userEvent.click(screen.getByRole("button", { name: "Открыть настройки Google Drive" }));
    expect(navigate.mock.calls[0][0].detail).toEqual({ section: "connections" });
    window.removeEventListener("studio:navigate-settings", navigate);
    await userEvent.click(screen.getByRole("checkbox", { name: "Автоматически сохранить копию в Google Drive" }));
    if (flow !== "folder") await userEvent.click(screen.getByRole("checkbox", { name: "Автоматически сохранить копию в Google Drive" }));
    expect(screen.getByRole("checkbox", { name: "Автоматически сохранить копию в Google Drive" })).not.toBeChecked();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/picker/session"))).toHaveLength(1);
  });

  it("reports dialog failure, keeps cancellation quiet and allows a later successful folder selection", async () => {
    vi.spyOn(googlePicker, "openGooglePicker")
      .mockResolvedValueOnce({ action: "error", message: "Не удалось загрузить Google Drive. Повторите попытку." })
      .mockResolvedValueOnce({ action: "cancel" })
      .mockResolvedValueOnce({ action: "picked", docs: [{ id: "folder", name: "Выбранная папка" }] });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/workspace")) return json({ project: { id: "project-id", title: "Studio" } });
      if (url.endsWith("/sources")) return json({ sources: [] });
      if (url.endsWith("/audio-preparations")) return json({ jobs: [] });
      if (url.endsWith("/picker/session")) return json({ access_token: "synthetic", scope_ready: true });
      throw new Error(url);
    }));
    render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Автоматически сохранить копию в Google Drive" }));
    const choose = screen.getByRole("button", { name: "Выбрать папку", exact: true });
    await waitFor(() => expect(choose).toBeEnabled());
    await userEvent.click(choose);
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить Google Drive. Повторите попытку.");
    await userEvent.click(choose);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await userEvent.click(choose);
    expect(await screen.findByText("Выбранная папка")).toBeVisible();
  });

  it("restores older pending previews and allows cancelling them to release their sources", async () => {
    const pending = { ...previewJob("older-preview", "Подготовка исходного файла", ["source-id"]), status: "preview_ready", progress: { percent: 100, stage: "preview_ready" } };
    const latest = { ...previewJob("latest-result", "Последний результат", []), status: "completed", progress: { percent: 100, stage: "completed" } };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/transcriptions/workspace")) return json({ project: { id: "project-id", title: "Транскрибации" } });
      if (url.endsWith("/sources")) return json({ sources: [] });
      if (url.endsWith("/audio-preparations")) return json({ jobs: [latest, pending] });
      if (url.endsWith("/older-preview/cancel") && init?.method === "POST") return json({ ...pending, status: "cancelled", progress: { percent: 100, stage: "cancelled" } });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()} />);

    const heading = await screen.findByRole("heading", { name: /Подготовка исходного файла/ });
    const card = heading.closest("article")!;
    await userEvent.click(within(card).getByRole("button", { name: "Отменить" }));
    expect(await within(card).findByText("Отменено")).toBeVisible();
    expect(within(card).queryByRole("button", { name: "Отменить" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith("/older-preview/cancel") && init?.method === "POST")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Отменить" })).not.toBeInTheDocument();
  });

  it("loads the owner workspace, displays the actual source deadline and enables preview after selection", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/transcriptions/workspace")) return json({ project: { id: "project-id", title: "Транскрибации" }, created: false });
      if (url.endsWith("/api/projects/project-id/sources")) return json({ sources: [{ id: "source-id", project_id: "project-id", source_type: "local_upload", original_filename: "meeting.wav", mime_type: "audio/wav", size_bytes: 100, drive_file_url: null, upload_status: "uploaded", uploaded_at: "2026-08-24T20:00:00Z", source_created_at: "2026-08-24T19:00:00Z", source_created_at_provenance: "embedded_media_metadata", expires_at: "2027-08-25T20:00:00Z", deleted_at: null, delete_reason: null, created_at: "2026-08-24T20:00:00Z", updated_at: "2026-08-24T20:00:00Z" }] });
      if (url.endsWith("/api/projects/project-id/audio-preparations")) return json({ jobs: [] });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "Подготовка аудио" })).toBeInTheDocument();
    const savedSources = screen
      .getByText("Выбрать из сохранённых файлов Studio")
      .closest("details");
    expect(savedSources).not.toHaveAttribute("open");
    await userEvent.click(
      screen.getByText("Выбрать из сохранённых файлов Studio"),
    );
    const source = await screen.findByRole("checkbox", { name: /meeting\.wav/i });
    expect(screen.getByText(/хранится до.*2027/i)).toBeInTheDocument();
    expect(screen.queryByText(/максимум через 24 часа/i)).not.toBeInTheDocument();
    const preview = screen.getByRole("button", { name: "Проверить файлы и рассчитать" });
    expect(screen.getByRole("textbox", { name: /Название результата/ })).toHaveValue("");
    expect(screen.getByPlaceholderText("Имя исходного файла")).toBeInTheDocument();
    expect(screen.getByText(/если оставить поле пустым, используется имя исходного файла/i)).toBeInTheDocument();
    expect(preview).toBeDisabled();
    await userEvent.click(source);
    await waitFor(() => expect(preview).toBeEnabled());
  });

  it("defaults to preserving the source and exposes conversion controls explicitly", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/transcriptions/workspace")) return json({ project: { id: "project-id", title: "Транскрибации" }, created: false });
      if (url.endsWith("/sources")) return json({ sources: [] });
      return json({ jobs: [] });
    }));
    render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()} />);
    const user = userEvent.setup();
    expect(await screen.findByLabelText("Формат результата")).toHaveValue("copy");
    expect(screen.queryByLabelText("Шаблон файла")).not.toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    const preset = screen.getByLabelText("Сценарий");
    await user.selectOptions(preset, "lecture");
    expect(screen.getByLabelText("Формат результата")).toHaveValue("flac");
    expect(screen.getByLabelText("Звуковые каналы")).toHaveValue("mixdown");
    expect(screen.getByRole("checkbox", { name: "Уменьшить длинные паузы в аудио или видео" })).toBeChecked();
    await user.click(screen.getByText("Дополнительные настройки пауз"));
    expect(screen.getByLabelText(/Что считать тишиной/)).toHaveValue("-45");
    await user.selectOptions(screen.getByLabelText("Формат результата"), "copy");
    expect(screen.getByLabelText("Звуковые каналы")).toHaveValue("preserve");
    expect(screen.getByRole("checkbox", { name: "Уменьшить длинные паузы в аудио или видео" })).not.toBeChecked();
  });

  it("submits a friendly naming choice using known creation metadata without exposing template syntax", async () => {
    const calls: Record<string, unknown>[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/workspace")) return json({ project: { id: "project-id", title: "Studio" } });
      if (url.endsWith("/sources")) return json({ sources: [source("lecture", "Лекция 1. Предмет.flac", "2026-10-06T12:34:56Z")] });
      if (url.endsWith("/audio-preparations") && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        calls.push(body);
        return json(previewJob("queued", body.title, body.source_ids));
      }
      if (url.endsWith("/audio-preparations")) return json({ jobs: [] });
      throw new Error(url);
    }));
    render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()} />);
    await userEvent.click(screen.getByText("Выбрать из сохранённых файлов Studio"));
    await userEvent.click(await screen.findByRole("checkbox", { name: /Лекция 1\. Предмет/ }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Как назвать файл" }), "dateTime");
    expect(screen.getByText(/Пример имени: 2026-10-06_12-34-56Z_Лекция 1\. Предмет/)).toBeVisible();
    expect(screen.queryByText("{date}_{time}_{title}")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Проверить файлы и рассчитать" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].options).toMatchObject({ output_name_template: "{date}_{time}_{title}" });
  });

  it("renders consistent terminal actions and hands the exact output source to transcriptions", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/transcriptions/workspace")) return json({ project: { id: "project-id", title: "Транскрибации" }, created: false });
      if (url.endsWith("/sources")) return json({ sources: [] });
      if (url.endsWith("/audio-preparations")) return json({ jobs: [{
        id: "audio-job-id",
        status: "completed",
        title: "Готовый файл",
        input_count: 1,
        inputs: [],
        preview: { input_duration_seconds: 10, estimated_output_duration_seconds: 8, copy_compatible: true },
        progress: { percent: 100, stage: "completed" },
        output: { download_ready: true, source_id: "prepared-source-id", google_drive_url: "https://drive.google.com/file/d/safe/view", duration_seconds: 8 },
        error_code: null,
      }] });
      throw new Error(`unexpected request: ${url}`);
    }));
    const listener = vi.fn();
    window.addEventListener("studio:transcribe-source", listener);

    render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()} />);

    const download = await screen.findByRole("link", { name: "Скачать файл" });
    expect(download).toHaveClass("button-like", "primary");
    await userEvent.click(
      screen.getByRole("button", { name: "Использовать для транскрибации" }),
    );
    expect(listener).toHaveBeenCalledTimes(1);
    expect((listener.mock.calls[0][0] as CustomEvent).detail).toEqual({
      sourceId: "prepared-source-id",
    });
    await userEvent.click(screen.getByRole("button", { name: "Другие действия: Готовый файл" }));
    expect(screen.getByRole("menuitem", { name: "Использовать в новой обработке" })).toBeInTheDocument();
    window.removeEventListener("studio:transcribe-source", listener);
  });

  it("creates independent jobs by default for multiple selected files", async () => {
    const created: Record<string, unknown>[] = [];
    const rows = [
      source("source-a", "anything-a.wav", "2026-08-24T20:00:00Z"),
      source("source-b", "Лекция 1. Предмет, задачи и методы социальной психологии.mp4", "2026-08-24T18:00:00Z"),
      source("source-c", "anything-c.wav", "2026-08-24T19:00:00Z"),
    ];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/transcriptions/workspace")) return json({ project: { id: "project-id", title: "Транскрибации" }, created: false });
      if (url.endsWith("/sources")) return json({ sources: rows });
      if (url.endsWith("/audio-preparations") && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        created.push(body);
        return json(previewJob(`job-${created.length}`, String(body.title), body.source_ids as string[]));
      }
      if (url.endsWith("/audio-preparations")) return json({ jobs: [] });
      throw new Error(`unexpected request: ${url}`);
    }));
    render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()} />);
    await userEvent.click(await screen.findByText("Выбрать из сохранённых файлов Studio"));
    for (const row of rows) await userEvent.click(screen.getByRole("checkbox", { name: new RegExp(row.original_filename, "i") }));

    expect(screen.getByRole("radio", { name: "Обработать каждый отдельно" })).toBeChecked();
    expect(screen.getByText("Будет создано результатов: 3.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Проверить файлы и рассчитать" }));

    await waitFor(() => expect(created).toHaveLength(3));
    expect(created.map((body) => body.source_ids)).toEqual([["source-b"], ["source-c"], ["source-a"]]);
    expect(created.map((body) => body.title)).toEqual(["Лекция 1. Предмет, задачи и методы социальной психологии", "anything-c", "anything-a"]);
  });

  it("shows and submits an explicit metadata-ordered concatenation plan", async () => {
    let created: Record<string, unknown> | null = null;
    const rows = [
      source("source-a", "arbitrary-z.wav", "2026-08-24T20:00:00Z"),
      source("source-b", "arbitrary-x.wav", "2026-08-24T18:00:00Z"),
      source("source-c", "arbitrary-y.wav", "2026-08-24T19:00:00Z"),
    ];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/transcriptions/workspace")) return json({ project: { id: "project-id", title: "Транскрибации" }, created: false });
      if (url.endsWith("/sources")) return json({ sources: rows });
      if (url.endsWith("/audio-preparations") && init?.method === "POST") {
        created = JSON.parse(String(init.body));
        return json(previewJob("concat-job", "Обработанное аудио", (created as Record<string, unknown>).source_ids as string[]));
      }
      if (url.endsWith("/audio-preparations")) return json({ jobs: [] });
      throw new Error(`unexpected request: ${url}`);
    }));
    render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()} />);
    await userEvent.click(await screen.findByText("Выбрать из сохранённых файлов Studio"));
    for (const row of rows) await userEvent.click(screen.getByRole("checkbox", { name: new RegExp(row.original_filename, "i") }));
    await userEvent.click(screen.getByRole("radio", { name: "Склеить в один файл" }));

    const plan = screen.getByRole("heading", { name: "Порядок склейки" }).parentElement as HTMLElement;
    const items = within(plan).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("arbitrary-x.wav");
    expect(items[1]).toHaveTextContent("arbitrary-y.wav");
    expect(items[2]).toHaveTextContent("arbitrary-z.wav");
    await userEvent.click(within(plan).getByRole("button", { name: "Переместить файл 1 ниже" }));
    await userEvent.click(screen.getByRole("button", { name: "Проверить файлы и рассчитать" }));

    await waitFor(() => expect(created).not.toBeNull());
    expect(created).toMatchObject({ title: "arbitrary-y", source_ids: ["source-c", "source-b", "source-a"], manual_order: true });
  });

  it("explains an aggregate server size rejection without starting processing", async () => {
    const row = source("source-a", "large.wav", "2026-08-24T20:00:00Z");
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/transcriptions/workspace")) return json({ project: { id: "project-id", title: "Транскрибации" }, created: false });
      if (url.endsWith("/sources")) return json({ sources: [row] });
      if (url.endsWith("/audio-preparations") && init?.method === "POST") return new Response(JSON.stringify({ detail: { reason: "input_too_large" } }), { status: 422, headers: { "content-type": "application/json" } });
      if (url.endsWith("/audio-preparations")) return json({ jobs: [] });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()} />);
    await userEvent.click(await screen.findByText("Выбрать из сохранённых файлов Studio"));
    await userEvent.click(screen.getByRole("checkbox", { name: /large.wav/i }));
    await userEvent.click(screen.getByRole("button", { name: "Проверить файлы и рассчитать" }));
    expect(await screen.findByText("Суммарный размер файлов превышает доступное место для обработки. Выберите меньше файлов.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Запустить обработку" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/execute"))).toBe(false);
  });

  it("keeps device files browser-local until the user explicitly chooses Studio upload", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/transcriptions/workspace")) return json({ project: { id: "project-id", title: "Транскрибации" }, created: false });
      if (url.endsWith("/sources")) return json({ sources: [] });
      if (url.endsWith("/audio-preparations")) return json({ jobs: [] });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()} />);
    await screen.findByRole("heading", { name: "Подготовка аудио" });
    await userEvent.click(screen.getByRole("tab", { name: "Обработать на устройстве" }));

    await userEvent.upload(
      screen.getByLabelText("Выбрать файлы для обработки на устройстве"),
      new File(["local bytes"], "private-recording.wav", { type: "audio/wav" }),
    );

    expect(screen.getByText(/Выбрано файлов: 1 · обработка на устройстве/i)).toBeInTheDocument();
    expect(
      screen.getByText(/исходные файлы не отправляются в Studio/i),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Формат результата")).toHaveValue("wav");
    expect(screen.getByLabelText("Формат результата")).toBeDisabled();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("local-upload/initiate"))).toBe(false);
  });

  it("discloses the bounded FLAC output precision", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/transcriptions/workspace")) return json({ project: { id: "project-id", title: "Транскрибации" }, created: false });
      if (url.endsWith("/sources")) return json({ sources: [] });
      if (url.endsWith("/audio-preparations")) return json({ jobs: [] });
      throw new Error(`unexpected request: ${url}`);
    }));
    render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()} />);
    await screen.findByRole("heading", { name: "Подготовка аудио" });

    await userEvent.selectOptions(screen.getByLabelText("Формат результата"), "flac");

    expect(
      screen.getByText(/FLAC создаётся в 16-bit PCM без lossy-сжатия/i),
    ).toBeInTheDocument();
  });

  it("sends separately selected audio retention and retains it after an upload admission error", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void init;
      const url = String(input);
      if (url.endsWith("/api/transcriptions/workspace")) return json({ project: { id: "project-id", title: "Транскрибации" }, created: false });
      if (url.endsWith("/sources")) return json({ sources: [] });
      if (url.endsWith("/audio-preparations")) return json({ jobs: [] });
      if (url.endsWith("/local-upload/initiate")) return new Response(JSON.stringify({ detail: "Хранилище временно недоступно" }), { status: 503, headers: { "content-type": "application/json" } });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()} />);
    await screen.findByRole("heading", { name: "Подготовка аудио" });
    await userEvent.click(screen.getByRole("tab", { name: "Загрузить в Studio" }));
    const retention = screen.getByRole("combobox", { name: "Хранить исходники аудио" });
    expect(retention).toHaveValue("7");
    expect(within(retention).getAllByRole("option").map((option) => (option as HTMLOptionElement).value)).toEqual(["3", "7", "30"]);
    await userEvent.selectOptions(retention, "30");
    await userEvent.upload(screen.getByLabelText("Выбрать файлы для загрузки в Studio"), new File(["synthetic"], "safe.wav", { type: "audio/wav" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Не удалось загрузить файлы: safe.wav:/);
    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/local-upload/initiate"));
    expect(JSON.parse((call?.[1] as RequestInit).body as string)).toMatchObject({ reference_class: "audio_processing", audio_retention_days: 30 });
    expect(retention).toHaveValue("30");
  });

  it("exposes keyboard-accessible source tabs and isolates direct Drive upload from processing controls", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/transcriptions/workspace")) return json({ project: { id: "project-id", title: "Транскрибации" }, created: false });
      if (url.endsWith("/sources")) return json({ sources: [] });
      if (url.endsWith("/audio-preparations")) return json({ jobs: [] });
      throw new Error(`unexpected request: ${url}`);
    }));
    render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()} />);
    await screen.findByRole("heading", { name: "Подготовка аудио" });

    const tablist = screen.getByRole("tablist", { name: "Способ получения исходных файлов" });
    expect(within(tablist).getAllByRole("tab")).toHaveLength(5);
    await userEvent.click(within(tablist).getByRole("tab", { name: "Из Яндекс Диска" }));
    expect(screen.getByRole("button", { name: "Выбрать файлы на Яндекс Диске" })).toBeEnabled();
    const direct = within(tablist).getByRole("tab", { name: "В Google Drive без обработки" });
    await userEvent.click(direct);
    expect(direct).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: "Загрузить исходные файлы без обработки" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "2. Параметры" })).not.toBeInTheDocument();

    direct.focus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(within(tablist).getByRole("tab", { name: "Загрузить в Studio" }))
      .toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: "2. Параметры" })).toBeInTheDocument();
  });
});


describe("audio UX regression", () => {
  it("recovers persisted legacy audio without creating another processing job", async () => {
    const stuck = { ...previewJob("stuck", "Практика №48", []), status: "processing", progress: { stage: "google_drive_upload", percent: 92 }, recoverable_output: true };
    const recovered = { ...stuck, status: "completed", recoverable_output: false, output: { download_ready: true, source_id: "ready-source", google_drive_url: null } };
    const posts: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/workspace")) return json({ project: { id: "project-id", title: "Studio" } });
      if (url.endsWith("/sources")) return json({ sources: [] });
      if (url.endsWith("/audio-preparations")) return json({ jobs: [stuck] });
      if (url.endsWith("/recover-output") && init?.method === "POST") { posts.push(url); return json(recovered); }
      throw new Error(url);
    }));
    render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Восстановить готовый файл" }));
    expect(await screen.findByRole("link", { name: "Скачать файл" })).toHaveAttribute("href", "/api/audio-preparations/stuck/download");
    expect(screen.getByRole("button", { name: "Использовать для транскрибации" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Восстановить готовый файл" })).not.toBeInTheDocument();
    expect(posts).toEqual(["/api/audio-preparations/stuck/recover-output"]);
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("keeps empty/minus drafts and sends comma/point decimals as numbers only after validation", async () => {
    const requests: Record<string, unknown>[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/workspace")) return json({ project: { id: "project-id", title: "Studio" } });
      if (url.endsWith("/sources")) return json({ sources: [source("s", "Лекция.wav", null)] });
      if (url.endsWith("/audio-preparations") && init?.method === "POST") {
        const body = JSON.parse(String(init.body)); requests.push(body);
        return json(previewJob("job", "Лекция", ["s"]));
      }
      if (url.endsWith("/audio-preparations")) return json({ jobs: [] });
      throw new Error(url);
    }));
    const user = userEvent.setup();
    render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()} />);
    await user.click(screen.getByText("Выбрать из сохранённых файлов Studio"));
    await user.click(await screen.findByRole("checkbox", { name: /Лекция.wav/ }));
    await user.click(screen.getByRole("checkbox", { name: "Уменьшить длинные паузы в аудио или видео" }));
    await user.click(screen.getByText("Дополнительные настройки пауз"));
    const threshold = screen.getByLabelText(/Что считать тишиной/);
    const minimum = screen.getByLabelText("Минимальная пауза, сек");
    const keep = screen.getByLabelText("Сколько паузы оставить, сек");
    const submit = screen.getByRole("button", { name: "Проверить файлы и рассчитать" });
    await user.clear(threshold);
    expect(threshold).toHaveValue("");
    await user.type(threshold, "-");
    expect(threshold).toHaveValue("-");
    await user.click(screen.getByText("Дополнительные настройки пауз"));
    expect(threshold.closest("details")).not.toHaveAttribute("open");
    await user.click(submit);
    expect(requests).toHaveLength(0);
    expect(threshold.closest("details")).toHaveAttribute("open");
    expect(screen.getByText(/введите число от −60 до −10/)).toBeVisible();
    expect(threshold).toHaveFocus();
    expect(threshold).toHaveAttribute("aria-invalid", "true");
    expect(threshold).toHaveAttribute("aria-describedby", "audio-threshold-error");
    expect(screen.getByRole("alert")).toHaveTextContent(/введите число от −60 до −10/);
    await user.type(threshold, "40.5");
    expect(threshold).toHaveValue("-40,5");
    expect(threshold).toHaveAttribute("aria-invalid", "false");
    await user.clear(minimum); await user.type(minimum, "1,2");
    await user.clear(keep); await user.type(keep, "0.35");
    expect(keep).toHaveValue("0,35");
    await user.click(submit);
    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0].options).toMatchObject({ silence_threshold_db: -40.5, silence_min_duration_seconds: 1.2, silence_keep_duration_seconds: 0.35 });
  });

  it("saves a completed download through the same folder picker, keeps download and polls the durable export", async () => {
    const picker = vi.spyOn(googlePicker, "openGooglePicker").mockResolvedValue({ action: "picked", docs: [{ id: "chosen-folder", name: "Результаты" }] });
    const saved = { ...previewJob("ready", "Готовое аудио", []), status: "completed", progress: { percent: 100, stage: "completed" }, output: { download_ready: true, source_id: "ready-source", google_drive_url: null } };
    const posts: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/workspace")) return json({ project: { id: "project-id", title: "Studio" } });
      if (url.endsWith("/sources")) return json({ sources: [] });
      if (url.endsWith("/audio-preparations")) return json({ jobs: [saved] });
      if (url.endsWith("/picker/session")) return json({ access_token: "synthetic", scope_ready: true });
      if (url.endsWith("/ready/save-to-drive")) {
        posts.push(JSON.parse(String(init?.body)));
        return json({ ...saved, progress: { percent: 0, stage: "google_drive_export_queued" } });
      }
      if (url.endsWith("/ready")) return json({ ...saved, output: { ...saved.output, google_drive_url: "https://drive.google.com/file/d/result/view" } });
      throw new Error(url);
    }));
    render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Сохранить в Google Drive" }));
    expect(picker.mock.calls[0][0]).toBe("output-folder");
    expect(posts).toEqual([{ folder_id: "chosen-folder" }]);
    expect(screen.getByRole("link", { name: "Скачать файл" })).toHaveAttribute("href", "/api/audio-preparations/ready/download");
    expect(screen.getByRole("button", { name: "Сохраняем в Google Drive…" })).toBeDisabled();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Сохраняем в Google Drive…" })).not.toBeInTheDocument(), { timeout: 3000 });
    expect(screen.getByRole("link", { name: "Открыть копию в Google Drive" })).toHaveAttribute("href", "https://drive.google.com/file/d/result/view");
    await userEvent.click(screen.getByRole("button", { name: "Другие действия: Готовое аудио" }));
    expect(screen.getByRole("menuitem", { name: "Открыть в Google Drive" })).toHaveAttribute("href", "https://drive.google.com/file/d/result/view");
  });

  it("picker cancellation makes no export and an unconfirmed export retries its original destination", async () => {
    const picker = vi.spyOn(googlePicker, "openGooglePicker").mockResolvedValue({ action: "cancel" });
    const ready = { ...previewJob("ready", "Аудио", []), status: "completed", progress: { percent: 100, stage: "completed" }, output: { download_ready: true, source_id: "out", google_drive_url: null } };
    const posts: unknown[] = [];
    let failed = false;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/workspace")) return json({ project: { id: "project-id", title: "Studio" } });
      if (url.endsWith("/sources")) return json({ sources: [] });
      if (url.endsWith("/audio-preparations")) return json({ jobs: [{ ...ready, ...(failed ? { progress: { percent: 100, stage: "google_drive_export_failed" }, output_folder: { id: "original", name: "Папка" } } : {}) }] });
      if (url.endsWith("/picker/session")) return json({ access_token: "synthetic", scope_ready: true });
      if (url.endsWith("/save-to-drive")) { posts.push(JSON.parse(String(init?.body))); return json(ready); }
      throw new Error(url);
    }));
    const view = render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Сохранить в Google Drive" }));
    expect(posts).toHaveLength(0);
    view.unmount(); failed = true;
    render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Повторить сохранение в Google Drive" }));
    expect(posts).toEqual([{ folder_id: "original" }]);
    expect(picker).toHaveBeenCalledTimes(1);
  });
  it("hands a regenerated result through a confirmed Drive copy without an S3 output Source", async () => {
    const ready = { ...previewJob("ready", "Готовая лекция", []), status: "completed", progress: { percent: 100, stage: "completed" },
      output: { download_ready: true, export_ready: true, regeneration_required: true, source_id: null, google_drive_url: null } };
    const queued = { ...ready, progress: { percent: 0, stage: "google_drive_export_queued" }, output_folder: { id: "folder", name: "Материалы" } };
    const saved = { ...queued, progress: { percent: 100, stage: "completed" }, output: { ...ready.output, google_drive_url: "https://drive.google.com/file/d/prepared/view" } };
    vi.spyOn(googlePicker, "openGooglePicker").mockResolvedValue({ action: "picked", docs: [{ id: "folder", name: "Материалы", mimeType: "application/vnd.google-apps.folder" }] });
    const posts: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/workspace")) return json({ project: { id: "project-id", title: "Studio" } });
      if (url.endsWith("/sources")) return json({ sources: [] });
      if (url.endsWith("/audio-preparations")) return json({ jobs: [ready] });
      if (url.endsWith("/picker/session")) return json({ access_token: "synthetic", api_key: "test", app_id: "test", scope_ready: true });
      if (url.endsWith("/save-to-drive")) { posts.push(url); return json(queued); }
      if (url.endsWith("/reuse-source")) { posts.push(url); return json(source("drive-input", "Готовая лекция.flac", null)); }
      if (url.endsWith("/audio-preparations/ready")) return json(saved);
      throw new Error(`Unexpected call: ${url}`);
    }));
    const handoff = vi.fn();
    window.addEventListener("studio:transcribe-source", handoff);
    try {
      render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()} />);
      await userEvent.click(await screen.findByRole("button", { name: "Использовать для транскрибации" }));
      expect(screen.getByRole("status")).toHaveTextContent("Сохраняем копию в Google Drive для передачи");
      await waitFor(() => expect(handoff).toHaveBeenCalledTimes(1), { timeout: 3000 });
      expect(handoff.mock.calls[0][0].detail).toEqual({ sourceId: "drive-input" });
      expect(posts).toEqual(["/api/audio-preparations/ready/save-to-drive", "/api/audio-preparations/ready/reuse-source"]);
      expect(screen.getByRole("button", { name: "Подготовить файл для скачивания" })).toBeEnabled();
    } finally { window.removeEventListener("studio:transcribe-source", handoff); }
  });

});
