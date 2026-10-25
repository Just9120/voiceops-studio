import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { YandexDiskPicker } from "./YandexDiskPicker";

const folder = { path: "disk:/", name: "Мой диск", is_folder: true, fingerprint: "f".repeat(64),
  mime_type: null, size_bytes: null, modified: null };
const file = (name: string) => ({ ...folder, path: `disk:/${name}`, name, is_folder: false,
  mime_type: "audio/flac", size_bytes: 4 });
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { "content-type": "application/json" },
});
beforeEach(() => { vi.spyOn(window, "scrollTo").mockImplementation(() => {}); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("Disk picker", () => {
  it("selects the current empty output folder and validates the server handle", async () => {
    const selected = vi.fn();
    const fetch = vi.fn(async (url: RequestInfo | URL, options?: RequestInit) => {
      expect(options?.method).toBe("POST");
      return String(url).endsWith("/select")
        ? json({ ...folder, id: "6f5d76f9-1ced-44a4-abf5-9ff96092687e" })
        : json({ folder, items: [], next_offset: null });
    });
    vi.stubGlobal("fetch", fetch);
    render(<YandexDiskPicker mode="output-folder" csrf="csrf" onCsrf={() => {}} onFinish={selected} />);
    const choose = await screen.findByRole("button", { name: "Выбрать эту папку" });
    await waitFor(() => expect(choose).toBeEnabled());
    fireEvent.click(choose);
    await waitFor(() => expect(selected).toHaveBeenCalledWith({ resources: [], folder: expect.objectContaining({ id: expect.any(String) }) }));
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toMatchObject({ path: "disk:/", folders_only: true });
  });

  it("can confirm an empty source folder without creating a fake source", async () => {
    const selected = vi.fn();
    vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => String(url).endsWith("/select")
      ? json({ ...folder, id: "6f5d76f9-1ced-44a4-abf5-9ff96092687e" })
      : json({ folder, items: [], next_offset: null })));
    render(<YandexDiskPicker mode="source-folder" csrf="csrf" onCsrf={() => {}} onFinish={selected} />);
    const choose = screen.getByRole("button", { name: "Выбрать эту папку" });
    await waitFor(() => expect(choose).toBeEnabled());
    fireEvent.click(choose);
    await waitFor(() => expect(selected).toHaveBeenCalledWith({ resources: [], folder: expect.objectContaining({ is_folder: true }) }));
  });

  it("preserves file selection order and loads all required source-folder pages", async () => {
    const selected = vi.fn();
    const seen: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, options?: RequestInit) => {
      const body = JSON.parse(String(options?.body || "{}"));
      if (String(url).endsWith("/select")) {
        seen.push(body.path);
        const item = body.is_folder ? folder : file(body.path.split("/").at(-1));
        return json({ ...item, id: body.path.endsWith("one.flac") ? "6f5d76f9-1ced-44a4-abf5-9ff96092687e" : "6f5d76f9-1ced-44a4-abf5-9ff96092687f" });
      }
      return json({ folder, items: [file(body.offset ? "two.flac" : "one.flac")], next_offset: body.offset ? null : 1 });
    }));
    render(<YandexDiskPicker mode="source-folder" csrf="csrf" onCsrf={() => {}} onFinish={selected} />);
    const choose = screen.getByRole("button", { name: "Выбрать эту папку" });
    await waitFor(() => expect(choose).toBeEnabled());
    fireEvent.click(choose);
    await waitFor(() => expect(selected).toHaveBeenCalled());
    expect(selected.mock.calls[0][0].resources.map((item: { name: string }) => item.name)).toEqual(["one.flac", "two.flac"]);
    expect(seen).toEqual(["disk:/", "disk:/one.flac", "disk:/two.flac"]);
  });

  it("does not confirm a stale file or expose raw external errors", async () => {
    const selected = vi.fn();
    vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => String(url).endsWith("/select")
      ? json({ detail: { reason: "yandex_disk_resource_changed", raw: "private-data" } }, 409)
      : json({ folder, items: [file("one.flac")], next_offset: null })));
    render(<YandexDiskPicker mode="sources" csrf="csrf" onCsrf={() => {}} onFinish={selected} />);
    fireEvent.click(await screen.findByRole("button", { name: /one.flac/ }));
    fireEvent.click(screen.getByRole("button", { name: "Выбрать файлы (1)" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("изменились");
    expect(selected).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toContain("private-data");
  });

  it("permits Escape while listing is still pending", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    const selected = vi.fn();
    render(<YandexDiskPicker mode="sources" csrf="csrf" onCsrf={() => {}} onFinish={selected} />);
    expect(screen.getByRole("button", { name: "Выбрать файлы (0)" })).toBeDisabled();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(selected).toHaveBeenCalledWith(null);
  });
});
