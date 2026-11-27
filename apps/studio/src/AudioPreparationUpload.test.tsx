import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AudioPreparationPage } from "./AudioPreparationPage";
import * as transport from "./directUpload";

const partSize = 8 * 1024 * 1024;
const fileSize = 2 * partSize + 16;
const active = (uploaded_parts: number[]) => ({ status: "active", uploaded_parts });
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});

async function setup(statuses: unknown[] = [active([1]), active([1, 2]), active([1, 2, 3])]) {
  let uploaded = false;
  const issuedParts: number[] = [];
  const uploadedSource = {
    id: "audio-source", project_id: "project-id", source_type: "local_upload",
    reference_class: "audio_processing", original_filename: "reference.wav",
    mime_type: "audio/wav", size_bytes: fileSize, upload_status: "uploaded",
    expires_at: "2099-01-01T00:00:00Z", deleted_at: null,
  };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/api/transcriptions/workspace")) return json({ project: { id: "project-id", title: "Транскрибации" } });
    if (url.endsWith("/sources")) return json({ sources: uploaded ? [uploadedSource] : [] });
    if (url.endsWith("/audio-preparations")) return json({ jobs: [] });
    if (url.endsWith("/local-upload/initiate")) {
      expect(JSON.parse(String(init?.body))).toMatchObject({ reference_class: "audio_processing", size_bytes: fileSize, mime_type: "audio/wav" });
      return json({ source_id: "audio-source", upload: { mode: "multipart", part_size_bytes: partSize, part_count: 3, expires_in: 3600 } });
    }
    const match = url.match(/\/multipart\/parts\/(\d+)$/);
    if (match) {
      const part = Number(match[1]);
      issuedParts.push(part);
      return json({ part_number: part, upload: { url: "https://storage.example/private?signature=never-display", method: "PUT", headers: {}, expires_in: 300 } });
    }
    if (url.endsWith("/multipart/status")) {
      const state = statuses.shift();
      if (state instanceof Response) return state;
      if ((state as { status?: string })?.status === "completed") uploaded = true;
      return json(state ?? active([]));
    }
    if (url.endsWith("/multipart/complete")) { uploaded = true; return json(uploadedSource); }
    throw new Error(`Unexpected test request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  const put = vi.spyOn(transport, "uploadFileWithProgress").mockResolvedValue({ ok: true, status: 200 });
  render(<AudioPreparationPage csrf="csrf" onCsrf={vi.fn()} />);
  const add = await screen.findByRole("button", { name: "Добавить файлы", exact: true });
  await waitFor(() => expect(add).toBeEnabled());
  await userEvent.click(add);
  await userEvent.click(await screen.findByRole("tab", { name: "Загрузить в Studio" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Выбрать и загрузить в Studio" })).toBeEnabled());
  const upload = async () => {
    await userEvent.upload(screen.getByLabelText("Выбрать файлы для загрузки в Studio"), new File([new Uint8Array(fileSize)], "reference.wav", { type: "audio/wav" }));
    await waitFor(() => {
      const settled = screen.queryByRole("button", { name: "Выбрать и загрузить в Studio" }) ?? add;
      expect(settled).toBeEnabled();
    });
  };
  const completeCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/multipart/complete"));
  return { put, upload, fetchMock, issuedParts, completeCalls };
}

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("audio-reference multipart upload", () => {
  it("uses audio isolation, confirms every part and completes without processing or Drive writes", async () => {
    const run = await setup();
    await run.upload();
    expect(run.issuedParts).toEqual([1, 2, 3]);
    expect(run.put.mock.calls.map(([request]) => request.file.size)).toEqual([partSize, partSize, 16]);
    expect(run.completeCalls()).toHaveLength(1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Проверить файлы и рассчитать" })).toBeEnabled();
    expect(run.fetchMock.mock.calls.some(([url, init]) => /google|provider/.test(String(url)) || (String(url).endsWith("/audio-preparations") && init?.method === "POST"))).toBe(false);
  });

  it.each(["direct_upload_network_error", "direct_upload_timeout"])("reconciles a confirmed %s without replaying the part", async (reason) => {
    const run = await setup();
    run.put.mockRejectedValueOnce(new transport.DirectUploadAmbiguousError(reason));
    await run.upload();
    expect(run.issuedParts).toEqual([1, 2, 3]);
    expect(run.completeCalls()).toHaveLength(1);
  });

  it("retries only the same missing part and reports the audio-storage boundary and cause", async () => {
    const run = await setup([active([]), active([])]);
    run.put.mockRejectedValue(new transport.DirectUploadAmbiguousError("direct_upload_network_error"));
    await run.upload();
    expect(run.issuedParts).toEqual([1, 1]);
    expect(run.completeCalls()).toHaveLength(0);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("часть 1 из 3");
    expect(alert).toHaveTextContent("хранилище обработки аудио");
    expect(alert).toHaveTextContent("сетевой ошибке или блокировке");
    expect(alert).not.toHaveTextContent("multipart_part_unconfirmed");
    expect(alert).not.toHaveTextContent("never-display");
  });

  it("continues the original session after one confirmed same-part retry", async () => {
    const run = await setup([active([]), active([1]), active([1, 2]), active([1, 2, 3])]);
    run.put.mockRejectedValueOnce(new transport.DirectUploadAmbiguousError("direct_upload_network_error"));
    await run.upload();
    expect(run.issuedParts).toEqual([1, 1, 2, 3]);
    expect(run.completeCalls()).toHaveLength(1);
    expect(run.fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/local-upload/initiate"))).toHaveLength(1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([json({ detail: "unavailable" }, 503), active([1, 1])])("does not replay a PUT when confirmation is unavailable or malformed", async (status) => {
    const run = await setup([status]);
    run.put.mockRejectedValueOnce(new transport.DirectUploadAmbiguousError("direct_upload_timeout"));
    await run.upload();
    expect(run.issuedParts).toEqual([1]);
    expect(run.completeCalls()).toHaveLength(0);
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось проверить приём части 1 из 3");
    expect(screen.getByRole("alert")).toHaveTextContent("Истекло время ожидания");
  });

  it("accepts server-confirmed completion without re-uploading or submitting completion again", async () => {
    const run = await setup([{ status: "completed", uploaded_parts: [] }]);
    run.put.mockRejectedValueOnce(new transport.DirectUploadAmbiguousError("direct_upload_network_error"));
    await run.upload();
    expect(run.issuedParts).toEqual([1]);
    expect(run.completeCalls()).toHaveLength(0);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Проверить файлы и рассчитать" })).toBeEnabled();
  });

  it("reports an HTTP rejection without retry or leaking capability details", async () => {
    const run = await setup();
    run.put.mockResolvedValueOnce({ ok: false, status: 403 });
    await run.upload();
    expect(run.issuedParts).toEqual([1]);
    expect(screen.getByRole("alert")).toHaveTextContent("HTTP 403");
    expect(screen.getByRole("alert")).not.toHaveTextContent("never-display");
  });

  it("never displays unknown transport exception messages", async () => {
    const run = await setup([active([]), active([])]);
    run.put.mockRejectedValue(new transport.DirectUploadAmbiguousError("https://storage.example/secret?signature=private"));
    await run.upload();
    expect(screen.getByRole("alert")).toHaveTextContent("Браузер не получил однозначный ответ");
    expect(screen.getByRole("alert")).not.toHaveTextContent("signature");
  });
});
