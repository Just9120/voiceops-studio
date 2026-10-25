import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { YandexDiskConnectionPanel } from "./YandexDiskConnectionPanel";

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { "content-type": "application/json" },
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState(null, "", "/"); });

describe("Disk connection", () => {
  it("reports operator configuration without offering an unusable OAuth action", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ configured: false, connected: false, status: "not_connected" })));
    render(<YandexDiskConnectionPanel csrf="csrf" onCsrf={() => {}} />);
    expect(await screen.findByText("Подключение ещё не настроено администратором.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Подключить Яндекс Диск" })).toBeDisabled();
  });

  it("does not believe a success query parameter before authoritative connection readback", async () => {
    window.history.replaceState(null, "", "/settings/connections?yandex_oauth=connected");
    vi.stubGlobal("fetch", vi.fn(async () => json({ configured: true, connected: false, status: "not_connected" })));
    render(<YandexDiskConnectionPanel csrf="csrf" onCsrf={() => {}} />);
    expect(await screen.findByText(/Не удалось завершить подключение/)).toBeInTheDocument();
    expect(window.location.search).toBe("");
  });

  it("reconciles a lost disconnect response without resending the mutation", async () => {
    let connected = true;
    let deletes = 0;
    vi.stubGlobal("fetch", vi.fn(async (_url: RequestInfo | URL, options?: RequestInit) => {
      if (options?.method === "DELETE") { connected = false; deletes += 1; throw new TypeError("lost response"); }
      return json({ configured: true, connected, status: connected ? "active" : "revoked" });
    }));
    render(<YandexDiskConnectionPanel csrf="csrf" onCsrf={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Отключить Яндекс Диск" }));
    fireEvent.click(screen.getByRole("button", { name: "Да" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText(/отключён в Studio/)).toBeInTheDocument();
    expect(deletes).toBe(1);
  });
});
