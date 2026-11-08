import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LocalExecutionPanel } from "./LocalExecutionPanel";
import { LOCAL_MODEL } from "./localExecutionContracts";

const device = (extra = {}) => ({ id: "00000000-0000-4000-8000-000000000001", label: "Домашний ПК", credential_revision: 1,
  online: true, ready: true, runtime_status: "ready", runtime_version: "0.2.0", model: LOCAL_MODEL,
  last_seen_at: new Date().toISOString(), revoked_at: null, ...extra });
const token = `vs-local.${device().id}.${"a".repeat(43)}`;
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); localStorage.clear(); sessionStorage.clear(); });

function requestManualPairing() {
  fireEvent.click(screen.getByText("Ручная настройка существующего обработчика"));
  fireEvent.change(screen.getByLabelText("Название компьютера"), { target: { value: "Домашний ПК" } });
  fireEvent.click(screen.getByRole("button", { name: "Создать ключ для ручного подключения" }));
}

describe("local computer pairing", () => {
  it("shows the checksum and a same-origin download for the approved closed release", async () => {
    const sha256 = "1".repeat(64);
    vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/companion-release")
      ? json({ version: "0.1.0", sha256, bytes: 137883537, signed: false }) : json({ devices: [] })));
    render(<LocalExecutionPanel csrf="csrf" onCsrf={() => {}} />);
    expect(await screen.findByRole("link", { name: "Скачать установщик Windows" }))
      .toHaveAttribute("href", `/api/local-execution/companion-release/${sha256}/download`);
    expect(screen.getByText(sha256)).toBeVisible();
    expect(screen.getByText(/Установщик не подписан/)).toBeVisible();
  });

  it.each([
    [404, "Установщик Windows сейчас недоступен."],
    [200, "Данные об установщике не прошли проверку. Скачивание недоступно."],
  ])("shows a safe retry when release metadata is unavailable (%s)", async (status, message) => {
    let releaseReads = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (!url.endsWith("/companion-release")) return json({ devices: [] });
      return ++releaseReads === 1 ? json({}, status)
        : json({ version: "0.1.0", sha256: "a".repeat(64), bytes: 100, signed: false });
    }));
    render(<LocalExecutionPanel csrf="csrf" onCsrf={() => {}} />);
    expect(screen.getByText("Проверяем доступность установщика Windows…")).toBeVisible();
    expect(await screen.findByText(message)).toBeVisible();
    expect(screen.queryByRole("link", { name: "Скачать установщик Windows" })).not.toBeInTheDocument();
    const manualSetup = screen.getByText("Ручная настройка существующего обработчика").closest("details");
    expect(manualSetup).not.toHaveAttribute("open");
    expect(manualSetup).toHaveTextContent("Создать ключ для ручного подключения");
    fireEvent.click(screen.getByRole("button", { name: "Проверить установщик снова" }));
    expect(await screen.findByRole("link", { name: "Скачать установщик Windows" })).toBeVisible();
  });

  it("times out the installer read and ignores its late response", async () => {
    vi.useFakeTimers();
    let finish: ((value: Response) => void) | undefined;
    let releaseSignal: AbortSignal | null | undefined;
    vi.stubGlobal("fetch", vi.fn((url: string, options?: RequestInit) => {
      if (!url.endsWith("/companion-release")) return Promise.resolve(json({ devices: [] }));
      releaseSignal = options?.signal;
      return new Promise<Response>(resolve => { finish = resolve; });
    }));
    render(<LocalExecutionPanel csrf="csrf" onCsrf={() => {}} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(releaseSignal?.aborted).toBe(true);
    expect(screen.getByText(/Studio не дождалась ответа об установщике/)).toBeVisible();
    await act(async () => {
      finish?.(json({ version: "0.1.0", sha256: "a".repeat(64), bytes: 100, signed: false }));
    });
    expect(screen.queryByRole("link", { name: "Скачать установщик Windows" })).not.toBeInTheDocument();
  });

  it("confirms a Windows enrollment without displaying or storing a device secret", async () => {
    const previous = window.location.href;
    const requestId = device().id;
    const approvalCalls: RequestInit[] = [];
    window.history.replaceState(null, "", `/settings/connections#local-enrollment=${requestId}`);
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/approve")) {
        approvalCalls.push(init ?? {});
        return json({ label: "Windows PC", approved: true });
      }
      if (url.endsWith(requestId)) return json({ label: "Windows PC", approved: false });
      return json({ devices: [] });
    }));
    try {
      render(<LocalExecutionPanel csrf="csrf" onCsrf={() => {}} />);
      const button = await screen.findByRole("button", { name: "Подтвердить подключение" });
      expect(approvalCalls).toHaveLength(0);
      fireEvent.click(button);
      expect(await screen.findByText(/Подключение «Windows PC» подтверждено/)).toBeVisible();
      expect(approvalCalls).toHaveLength(1);
      expect(new Headers(approvalCalls[0].headers).get("x-csrf-token")).toBe("csrf");
      expect(screen.queryByLabelText("Ключ подключения")).not.toBeInTheDocument();
      expect(JSON.stringify([localStorage, sessionStorage])).not.toContain("vs-local.");
    } finally {
      window.history.replaceState(null, "", previous);
    }
  });

  it("shows missing-model feedback and keeps revoke behind confirmation", async () => {
    let rows = [device({ ready: false, runtime_status: "model_missing" })];
    const mutations: RequestInit[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: unknown, init?: RequestInit) => {
      if (init?.method === "POST") { mutations.push(init); rows = []; return json({ device: device({ online: false, ready: false, revoked_at: new Date().toISOString() }) }); }
      return json({ devices: rows });
    }));
    render(<LocalExecutionPanel csrf="csrf" onCsrf={() => {}} />);
    expect(await screen.findByText("Файлы модели не найдены")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Действия компьютера Домашний ПК" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Отозвать доступ" }));
    expect(mutations).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Отозвать доступ" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(JSON.parse(String(mutations[0].body))).toEqual({ expected_revision: 1 });
    expect(await screen.findByText(/Доступ компьютера отозван/)).toBeInTheDocument();
  });
  it("replays one ambiguous pairing without duplicates and never stores the secret", async () => {
    const pairs: Record<string, unknown>[] = [];
    let rows: ReturnType<typeof device>[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: unknown, init?: RequestInit) => {
      if (init?.method === "POST") {
        pairs.push(JSON.parse(String(init.body))); rows = [device()];
        if (pairs.length === 1) throw new TypeError("lost response");
        return json({ device: device(), pairing_token: null, token_available_once: false });
      }
      return json({ devices: rows });
    }));
    render(<LocalExecutionPanel csrf="csrf" onCsrf={() => {}} />);
    await screen.findByText("Компьютеры ещё не подключены.");
    requestManualPairing();
    const retry = await screen.findByRole("button", { name: "Повторить тот же запрос подключения" });
    fireEvent.click(retry);
    expect(await screen.findByText(/Этот компьютер уже подключён/)).toBeInTheDocument();
    expect(pairs).toHaveLength(2); expect(pairs[1]).toEqual(pairs[0]);
    expect(screen.queryByLabelText("Ключ подключения")).not.toBeInTheDocument();
    expect(JSON.stringify([localStorage, sessionStorage])).not.toContain("vs-local.");
  });
  it("exposes a secret only once in a masked field and clears it on explicit hide", async () => {
    let rows: ReturnType<typeof device>[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: unknown, init?: RequestInit) => {
      if (init?.method === "POST") { rows = [device()]; return json({ device: device(), pairing_token: token, token_available_once: true }); }
      return json({ devices: rows });
    }));
    render(<LocalExecutionPanel csrf="csrf" onCsrf={() => {}} />);
    await screen.findByText("Компьютеры ещё не подключены.");
    requestManualPairing();
    const secret = await screen.findByLabelText("Ключ подключения");
    expect(secret).toHaveAttribute("type", "password"); expect(secret).toHaveValue(token);
    expect(JSON.stringify([localStorage, sessionStorage])).not.toContain(token);
    fireEvent.click(screen.getByRole("button", { name: "Скрыть ключ" }));
    expect(screen.queryByLabelText("Ключ подключения")).not.toBeInTheDocument();
  });
  it("explains recent-auth failure and does not pretend the PC was paired", async () => {
    vi.stubGlobal("fetch", vi.fn(async (_url: unknown, init?: RequestInit) => init?.method === "POST"
      ? json({ detail: { reason: "recent_reauthentication_required" } }, 403) : json({ devices: [] })));
    render(<LocalExecutionPanel csrf="csrf" onCsrf={() => {}} />);
    await screen.findByText("Компьютеры ещё не подключены.");
    requestManualPairing();
    expect(await screen.findByText(/Подтвердите пароль и 2FA/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Ключ подключения")).not.toBeInTheDocument();
  });
});
