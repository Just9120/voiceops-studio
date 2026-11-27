import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { openGooglePicker, resetGooglePickerLoaderForTests } from "./googlePicker";

const FOLDER_MIME_TYPE = "application/vnd.google-apps.folder";

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function pickerSession(token = "ya29.test-drive-token") {
  return {
    access_token: token,
    api_key: "public",
    app_id: "app",
    scope_ready: true,
  };
}

function rootPayload() {
  return {
    id: "root-id",
    name: "Мой диск",
    mimeType: FOLDER_MIME_TYPE,
  };
}

function requestUrl(input: string | URL | Request): URL {
  return new URL(String(input));
}

async function startPicker(...args: Parameters<typeof openGooglePicker>) {
  let resultPromise!: ReturnType<typeof openGooglePicker>;
  await act(async () => {
    resultPromise = openGooglePicker(...args);
    await Promise.resolve();
  });
  return { resultPromise };
}

describe("app-owned Google Drive picker", () => {
  beforeEach(() => {
    resetGooglePickerLoaderForTests();
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
    document
      .querySelectorAll('[data-studio-google-drive-folder-picker="true"]')
      .forEach((node) => node.remove());
    document.documentElement.removeAttribute("style");
    document.body.removeAttribute("style");
    localStorage.clear();
    sessionStorage.clear();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("returns keyboard focus to the launcher after choosing a folder", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.pathname.endsWith("/files/root")) return json(rootPayload());
      if (url.pathname.endsWith("/drives")) return json({ drives: [] });
      return json({ files: [] });
    }));
    const launcher = document.createElement("button");
    launcher.textContent = "Выбрать папку";
    document.body.appendChild(launcher);
    launcher.focus();
    try {
      const { resultPromise } = await startPicker("output-folder", pickerSession(), { returnFocusTo: launcher });
      await userEvent.click(await screen.findByRole("button", { name: "Выбрать эту папку" }));
      expect((await resultPromise).action).toBe("picked");
      await waitFor(() => expect(launcher).toHaveFocus());
    } finally {
      launcher.remove();
    }
  });

  it("returns focus after Escape when the caller reenables its launcher on cancellation", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.pathname.endsWith("/files/root")) return json(rootPayload());
      if (url.pathname.endsWith("/drives")) return json({ drives: [] });
      return json({ files: [] });
    }));
    const launcher = document.createElement("button");
    document.body.appendChild(launcher);
    launcher.focus();
    launcher.disabled = true;
    try {
      const { resultPromise } = await startPicker("output-folder", pickerSession(), { returnFocusTo: launcher });
      await screen.findByRole("button", { name: "Выбрать эту папку" });
      await userEvent.keyboard("{Escape}");
      expect((await resultPromise).action).toBe("cancel");
      launcher.disabled = false;
      await waitFor(() => expect(launcher).toHaveFocus());
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    } finally {
      launcher.remove();
    }
  });

  it("sorts all pages through Drive and preserves folder/search context while discarding old tokens", async () => {
    const requests: URL[] = [];
    const folder = (id: string, name: string) => ({ id, name, mimeType: FOLDER_MIME_TYPE });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.pathname.endsWith("/files/root")) return json(rootPayload());
      if (url.pathname.endsWith("/drives")) return json({ drives: [] });
      requests.push(url);
      const q = url.searchParams.get("q") || "";
      if (q.includes("sharedWithMe")) return json({ files: [] });
      if (q.includes("'nested' in parents")) return json({ files: [] });
      const sort = url.searchParams.get("orderBy");
      if (sort === "name_natural") return json({ files: [folder("old", "Старый порядок")], nextPageToken: "old-token" });
      if (url.searchParams.get("pageToken")) return json({ files: [folder("nested", "Новая папка")] });
      return json({ files: [folder("fresh", "Обновлённая папка")], nextPageToken: "sorted-token" });
    }));
    const { resultPromise } = await startPicker("output-folder", pickerSession());
    await screen.findByText("Старый порядок");
    await userEvent.selectOptions(screen.getByLabelText("Сортировка папок и файлов"), "modifiedTime desc,name_natural");
    await screen.findByText("Обновлённая папка");
    expect(screen.queryByText("Старый порядок")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Загрузить ещё" }));
    await screen.findByText("Новая папка");
    const paged = requests.find((url) => url.searchParams.has("pageToken"));
    expect(paged?.searchParams.get("pageToken")).toBe("sorted-token");
    expect(paged?.searchParams.get("orderBy")).toBe("modifiedTime desc,name_natural");
    await userEvent.click(screen.getByRole("button", { name: /Новая папка/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Выбрать эту папку" })).toBeEnabled());
    await userEvent.type(screen.getByLabelText("Поиск папок по началу названия"), "Архив");
    await userEvent.click(screen.getByRole("button", { name: "Найти" }));
    await screen.findByText("Обновлённая папка");
    await userEvent.selectOptions(screen.getByLabelText("Сортировка папок и файлов"), "name_natural desc");
    await waitFor(() => expect(requests.some((url) => url.searchParams.get("orderBy") === "name_natural desc" && url.searchParams.get("q")?.includes("name contains 'Архив'"))).toBe(true));
    expect(requests.some((url) => url.searchParams.get("orderBy") === "name_natural desc" && url.searchParams.get("q")?.includes("'nested' in parents"))).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "Сбросить" }));
    await userEvent.click(screen.getByRole("button", { name: "Выбрать эту папку" }));
    expect(await resultPromise).toEqual({ action: "picked", docs: [{ id: "nested", name: "Новая папка", mimeType: FOLDER_MIME_TYPE }] });
  });

  it("ignores a late sort response after another order is chosen", async () => {
    let resolveOld!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.pathname.endsWith("/files/root")) return json(rootPayload());
      if (url.pathname.endsWith("/drives")) return json({ drives: [] });
      if (url.searchParams.get("q")?.includes("sharedWithMe")) return json({ files: [] });
      if (url.searchParams.get("orderBy") === "modifiedTime,name_natural") return new Promise<Response>((resolve) => { resolveOld = resolve; });
      return json({ files: [{ id: "valid", name: "Актуальная папка", mimeType: FOLDER_MIME_TYPE }] });
    }));
    const { resultPromise } = await startPicker("output-folder", pickerSession());
    await screen.findByText("Актуальная папка");
    const sort = screen.getByLabelText("Сортировка папок и файлов");
    await userEvent.selectOptions(sort, "modifiedTime,name_natural");
    await userEvent.selectOptions(sort, "name_natural desc");
    await screen.findByText("Актуальная папка");
    await act(async () => resolveOld(json({ files: [{ id: "stale", name: "Устаревший ответ", mimeType: FOLDER_MIME_TYPE }] })));
    expect(screen.queryByText("Устаревший ответ")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(await resultPromise).toEqual({ action: "cancel" });
  });

  it("keeps the current empty output folder selectable and restores scroll", async () => {
    let sharedFolderQuery = "";
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL | Request, init?: RequestInit) => {
        const url = requestUrl(input);
        expect(init?.headers).toEqual({
          Authorization: "Bearer ya29.test-drive-token",
        });
        if (url.pathname.endsWith("/files/root")) {
          return Promise.resolve(json(rootPayload()));
        }
        if (url.pathname.endsWith("/drives")) {
          return Promise.resolve(json({ drives: [] }));
        }
        const query = url.searchParams.get("q") ?? "";
        if (query.includes("sharedWithMe")) {
          sharedFolderQuery = query;
          return Promise.resolve(json({ files: [] }));
        }
        if (query.includes("'root-id' in parents")) {
          return Promise.resolve(
            json({
              files: [
                {
                  id: "empty-folder-id",
                  name: "Пустая папка",
                  mimeType: FOLDER_MIME_TYPE,
                },
              ],
            }),
          );
        }
        if (query.includes("'empty-folder-id' in parents")) {
          return Promise.resolve(json({ files: [] }));
        }
        return Promise.resolve(json({}, 404));
      }),
    );
    const session = pickerSession();
    let resultPromise!: ReturnType<typeof openGooglePicker>;
    await act(async () => {
      resultPromise = openGooglePicker("output-folder", session);
      await Promise.resolve();
    });

    expect(session.access_token).toBe("");
    expect(document.documentElement.style.overflow).toBe("hidden");
    expect(document.body.style.overflow).toBe("hidden");
    expect(
      await screen.findByRole("dialog", {
        name: "Выберите папку для результатов",
      }),
    ).toHaveAttribute("aria-modal", "true");

    const selectCurrent = screen.getByRole("button", {
      name: "Выбрать эту папку",
    });
    await waitFor(() => expect(selectCurrent).toBeEnabled());
    await waitFor(() =>
      expect(sharedFolderQuery).toBe(
        `sharedWithMe and trashed = false and mimeType = '${FOLDER_MIME_TYPE}'`,
      ),
    );
    await userEvent.click(
      await screen.findByRole("button", {
        name: "Открыть папку «Пустая папка»",
      }),
    );

    expect(
      await screen.findByText(
        "Внутри нет папок. Текущую папку можно выбрать.",
      ),
    ).toBeInTheDocument();
    expect(selectCurrent).toBeEnabled();
    expect(screen.getByText("Текущая папка: Пустая папка")).toBeInTheDocument();
    await userEvent.click(selectCurrent);

    await expect(resultPromise).resolves.toEqual({
      action: "picked",
      docs: [
        {
          id: "empty-folder-id",
          name: "Пустая папка",
          mimeType: FOLDER_MIME_TYPE,
        },
      ],
    });
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.overflow).toBe("");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.body.textContent).not.toContain("ya29.test-drive-token");
  });

  it("escapes a folder search, opens the result, and selects it", async () => {
    const observedQueries: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL | Request) => {
        const url = requestUrl(input);
        if (url.pathname.endsWith("/files/root")) {
          return Promise.resolve(json(rootPayload()));
        }
        if (url.pathname.endsWith("/drives")) {
          return Promise.resolve(json({ drives: [] }));
        }
        const query = url.searchParams.get("q") ?? "";
        observedQueries.push(query);
        if (query.includes("sharedWithMe")) {
          return Promise.resolve(json({ files: [] }));
        }
        if (query.includes("name contains")) {
          return Promise.resolve(
            json({
              files: [
                {
                  id: "searched-folder-id",
                  name: "Архив интервью",
                  mimeType: FOLDER_MIME_TYPE,
                },
              ],
            }),
          );
        }
        return Promise.resolve(json({ files: [] }));
      }),
    );
    const { resultPromise } = await startPicker(
      "source-folder",
      pickerSession(),
    );
    const search = await screen.findByLabelText(
      "Поиск папок по началу названия",
    );
    await userEvent.type(search, "O'Brien\\Archive");
    await userEvent.click(screen.getByRole("button", { name: "Найти" }));

    await userEvent.click(
      await screen.findByRole("button", {
        name: "Открыть папку «Архив интервью»",
      }),
    );
    expect(
      observedQueries.some((query) =>
        query.includes("name contains 'O\\'Brien\\\\Archive'"),
      ),
    ).toBe(true);
    expect(
      await screen.findByText("Текущая папка: Архив интервью"),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Выбрать эту папку" }),
    );
    await expect(resultPromise).resolves.toMatchObject({
      action: "picked",
      docs: [{ id: "searched-folder-id", name: "Архив интервью" }],
    });
  });

  it("uses the app-owned searchable picker for a transcript folder", async () => {
    const observedQueries: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL | Request) => {
        const url = requestUrl(input);
        if (url.pathname.endsWith("/files/root")) {
          return Promise.resolve(json(rootPayload()));
        }
        if (url.pathname.endsWith("/drives")) {
          return Promise.resolve(json({ drives: [] }));
        }
        const query = url.searchParams.get("q") ?? "";
        if (query.includes("sharedWithMe")) {
          return Promise.resolve(json({ files: [] }));
        }
        observedQueries.push(query);
        if (query.includes("name contains")) {
          return Promise.resolve(
            json({
              files: [
                {
                  id: "transcript-folder-id",
                  name: "Созвоны команды",
                  mimeType: FOLDER_MIME_TYPE,
                },
              ],
            }),
          );
        }
        return Promise.resolve(json({ files: [] }));
      }),
    );

    const { resultPromise } = await startPicker(
      "transcript-folder",
      pickerSession(),
    );
    expect(
      await screen.findByRole("dialog", {
        name: "Выберите папку с транскриптами",
      }),
    ).toBeInTheDocument();
    const search = screen.getByLabelText(
      "Поиск папок с транскриптами по началу названия",
    );
    await userEvent.type(search, "Созвоны");
    await userEvent.click(screen.getByRole("button", { name: "Найти" }));
    await userEvent.click(
      await screen.findByRole("button", {
        name: "Открыть папку «Созвоны команды»",
      }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Выбрать эту папку" }),
    );

    await expect(resultPromise).resolves.toMatchObject({
      action: "picked",
      docs: [{ id: "transcript-folder-id", name: "Созвоны команды" }],
    });
    expect(
      observedQueries.some((query) => query.includes("name contains 'Созвоны'")),
    ).toBe(true);
  });

  it("searches and selects one Google Doc in the app-owned transcript picker", async () => {
    const googleDoc = {
      id: "google-doc-id",
      name: "Синк с разработкой",
      mimeType: "application/vnd.google-apps.document",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL | Request) => {
        const url = requestUrl(input);
        if (url.pathname.endsWith("/files/root")) {
          return Promise.resolve(json(rootPayload()));
        }
        if (url.pathname.endsWith("/drives")) {
          return Promise.resolve(json({ drives: [] }));
        }
        const query = url.searchParams.get("q") ?? "";
        if (query.includes("sharedWithMe")) {
          return Promise.resolve(json({ files: [] }));
        }
        return Promise.resolve(
          json({
            files: query.includes("name contains")
              ? [
                  googleDoc,
                  {
                    id: "pdf-id",
                    name: "Синк.pdf",
                    mimeType: "application/pdf",
                  },
                ]
              : [],
          }),
        );
      }),
    );

    const { resultPromise } = await startPicker(
      "transcript-document",
      pickerSession(),
    );
    expect(
      await screen.findByRole("dialog", {
        name: "Выберите Google Doc с транскриптом",
      }),
    ).toBeInTheDocument();
    const search = screen.getByLabelText(
      "Поиск Google Docs по началу названия",
    );
    await userEvent.type(search, "Синк");
    await userEvent.click(screen.getByRole("button", { name: "Найти" }));
    await userEvent.click(
      await screen.findByRole("button", {
        name: "Выбрать файл «Синк с разработкой»",
      }),
    );
    expect(screen.queryByText("Синк.pdf")).not.toBeInTheDocument();
    expect(screen.getByText("Выбран один Google Doc")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Выбрать Google Doc" }),
    );
    await expect(resultPromise).resolves.toEqual({
      action: "picked",
      docs: [googleDoc],
    });
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.overflow).toBe("");
  });

  it("paginates source files explicitly and preserves deduplicated selections across search", async () => {
    const fileOne = {
      id: "file-1",
      name: "Clip One.mp3",
      mimeType: "audio/mpeg",
    };
    const fileTwo = {
      id: "file-2",
      name: "Clip Two.mp4",
      mimeType: "video/mp4",
    };
    const fileThree = {
      id: "file-3",
      name: "Clip Three.ogg",
      mimeType: "application/ogg",
    };
    const listRequests: URL[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL | Request) => {
        const url = requestUrl(input);
        if (url.pathname.endsWith("/files/root")) {
          return Promise.resolve(json(rootPayload()));
        }
        if (url.pathname.endsWith("/drives")) {
          return Promise.resolve(json({ drives: [] }));
        }
        const query = url.searchParams.get("q") ?? "";
        if (query.includes("sharedWithMe")) {
          return Promise.resolve(json({ files: [] }));
        }
        listRequests.push(url);
        if (query.includes("name contains")) {
          return Promise.resolve(json({ files: [fileThree] }));
        }
        if (url.searchParams.get("pageToken") === "page-2") {
          return Promise.resolve(json({ files: [fileOne, fileTwo] }));
        }
        return Promise.resolve(
          json({
            files: [
              fileOne,
              {
                id: "unsupported-doc",
                name: "Not media.pdf",
                mimeType: "application/pdf",
              },
            ],
            nextPageToken: "page-2",
          }),
        );
      }),
    );
    const { resultPromise } = await startPicker("sources", pickerSession(), {
      sourceMimePolicy: {
        supported_mime_prefixes: ["audio/", "video/"],
        supported_mime_types: ["application/ogg"],
      },
    });

    expect(
      await screen.findByRole("dialog", { name: "Выберите аудио или видео" }),
    ).toBeInTheDocument();
    await userEvent.click(
      await screen.findByRole("button", { name: "Выбрать файл «Clip One.mp3»" }),
    );
    expect(screen.queryByText("Not media.pdf")).not.toBeInTheDocument();
    expect(listRequests).toHaveLength(1);
    expect(listRequests[0]?.searchParams.get("pageSize")).toBe("100");

    await userEvent.click(
      screen.getByRole("button", { name: "Загрузить ещё" }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Выбрать файл «Clip Two.mp4»" }),
    );
    expect(screen.getByText("Выбрано: 2 из 50")).toBeInTheDocument();

    const search = screen.getByLabelText("Поиск файлов по началу названия");
    await userEvent.type(search, "Clip");
    await userEvent.click(screen.getByRole("button", { name: "Найти" }));
    await userEvent.click(
      await screen.findByRole("button", {
        name: "Выбрать файл «Clip Three.ogg»",
      }),
    );
    expect(screen.getByText("Выбрано: 3 из 50")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Сбросить" }));
    expect(
      screen.getAllByRole("button", { name: "Убрать файл «Clip One.mp3»" }),
    ).toHaveLength(2);

    await userEvent.click(
      screen.getByRole("button", { name: "Добавить выбранные файлы (3)" }),
    );
    await expect(resultPromise).resolves.toEqual({
      action: "picked",
      docs: [fileOne, fileTwo, fileThree],
    });
    expect(
      listRequests.filter(
        (url) => !url.searchParams.get("q")?.includes("name contains"),
      ),
    ).toHaveLength(2);
  });

  it("enforces the 50-file selection maximum", async () => {
    const files = Array.from({ length: 51 }, (_, index) => ({
      id: `file-${index + 1}`,
      name: `Audio ${String(index + 1).padStart(2, "0")}.mp3`,
      mimeType: "audio/mpeg",
    }));
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL | Request) => {
        const url = requestUrl(input);
        if (url.pathname.endsWith("/files/root")) {
          return Promise.resolve(json(rootPayload()));
        }
        if (url.pathname.endsWith("/drives")) {
          return Promise.resolve(json({ drives: [] }));
        }
        const query = url.searchParams.get("q") ?? "";
        if (query.includes("sharedWithMe")) {
          return Promise.resolve(json({ files: [] }));
        }
        return Promise.resolve(json({ files }));
      }),
    );
    const { resultPromise } = await startPicker("sources", pickerSession());
    await screen.findByText("Audio 51.mp3");
    const selectionButtons = screen.getAllByRole("button", {
      name: /^Выбрать файл «Audio/,
    });
    selectionButtons.slice(0, 50).forEach((button) => fireEvent.click(button));
    expect(await screen.findByText("Выбрано: 50 из 50")).toBeInTheDocument();
    expect(selectionButtons[50]).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Отмена" }));
    await expect(resultPromise).resolves.toEqual({ action: "cancel" });
  });

  it("opens a shared drive with drive-scoped list parameters", async () => {
    const driveRequests: URL[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL | Request) => {
        const url = requestUrl(input);
        if (url.pathname.endsWith("/files/root")) {
          return Promise.resolve(json(rootPayload()));
        }
        if (url.pathname.endsWith("/drives")) {
          return Promise.resolve(
            json({ drives: [{ id: "drive-1", name: "Командный диск" }] }),
          );
        }
        const query = url.searchParams.get("q") ?? "";
        if (query.includes("sharedWithMe")) {
          return Promise.resolve(json({ files: [] }));
        }
        if (query.includes("'drive-1' in parents")) {
          driveRequests.push(url);
        }
        return Promise.resolve(json({ files: [] }));
      }),
    );
    const { resultPromise } = await startPicker(
      "source-folder",
      pickerSession(),
    );
    await userEvent.click(
      await screen.findByRole("button", {
        name: "Открыть папку «Командный диск»",
      }),
    );
    await screen.findByText("Текущая папка: Командный диск");
    expect(driveRequests).toHaveLength(1);
    expect(driveRequests[0]?.searchParams.get("corpora")).toBe("drive");
    expect(driveRequests[0]?.searchParams.get("driveId")).toBe("drive-1");
    await userEvent.click(
      screen.getByRole("button", { name: "Выбрать эту папку" }),
    );
    await expect(resultPromise).resolves.toMatchObject({
      action: "picked",
      docs: [{ id: "drive-1", name: "Командный диск" }],
    });
  });

  it("aborts a stale search and renders only the latest result", async () => {
    let firstSearchSignal: AbortSignal | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL | Request, init?: RequestInit) => {
        const url = requestUrl(input);
        if (url.pathname.endsWith("/files/root")) {
          return Promise.resolve(json(rootPayload()));
        }
        if (url.pathname.endsWith("/drives")) {
          return Promise.resolve(json({ drives: [] }));
        }
        const query = url.searchParams.get("q") ?? "";
        if (query.includes("sharedWithMe")) {
          return Promise.resolve(json({ files: [] }));
        }
        if (query.includes("name contains 'Первый'")) {
          firstSearchSignal = init?.signal ?? null;
          return new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () =>
              reject(new DOMException("Aborted", "AbortError")),
            );
          });
        }
        if (query.includes("name contains 'Второй'")) {
          return Promise.resolve(
            json({
              files: [
                {
                  id: "second-folder",
                  name: "Второй результат",
                  mimeType: FOLDER_MIME_TYPE,
                },
              ],
            }),
          );
        }
        return Promise.resolve(json({ files: [] }));
      }),
    );
    const { resultPromise } = await startPicker(
      "output-folder",
      pickerSession(),
    );
    const search = await screen.findByLabelText(
      "Поиск папок по началу названия",
    );
    await userEvent.type(search, "Первый");
    await userEvent.click(screen.getByRole("button", { name: "Найти" }));
    await screen.findByText("Ищем в Google Drive…");
    await userEvent.clear(search);
    await userEvent.type(search, "Второй");
    await userEvent.click(screen.getByRole("button", { name: "Найти" }));

    expect(
      await screen.findByRole("button", {
        name: "Открыть папку «Второй результат»",
      }),
    ).toBeInTheDocument();
    expect(firstSearchSignal?.aborted).toBe(true);
    await userEvent.click(
      screen.getByRole("button", { name: "Отмена" }),
    );
    await expect(resultPromise).resolves.toEqual({ action: "cancel" });
  });

  it("returns a safe error and restores scroll when Drive rejects the root", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(json({}, 401))));
    const { resultPromise } = await startPicker(
      "output-folder",
      pickerSession(),
    );

    let result: Awaited<typeof resultPromise> | undefined;
    await act(async () => {
      result = await resultPromise;
    });
    expect(result).toEqual({
      action: "error",
      message:
        "Не удалось загрузить Google Drive. Переподключите Drive или повторите попытку.",
    });
    expect(document.body.style.overflow).toBe("");
    expect(
      document.querySelector('[data-studio-google-drive-folder-picker="true"]'),
    ).toBeNull();
  });

  it("times out safely and restores scroll when Drive never responds", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));
    let resultPromise!: ReturnType<typeof openGooglePicker>;
    act(() => {
      resultPromise = openGooglePicker("sources", pickerSession());
    });
    expect(document.body.style.overflow).toBe("hidden");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300_000);
    });
    await expect(resultPromise).resolves.toEqual({
      action: "error",
      message: "Время выбора в Google Drive истекло. Повторите попытку.",
    });
    expect(document.body.style.overflow).toBe("");
  });
});
