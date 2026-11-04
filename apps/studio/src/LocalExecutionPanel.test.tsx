import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LocalExecutionPanel } from "./LocalExecutionPanel";
import { LOCAL_MODEL } from "./localExecutionContracts";

const device = (extra = {}) => ({ id: "00000000-0000-4000-8000-000000000001", label: "Домашний ПК", credential_revision: 1,
  online: true, ready: true, runtime_status: "ready", runtime_version: "0.2.0", model: LOCAL_MODEL,
  last_seen_at: new Date().toISOString(), revoked_at: null, ...extra });
const token = `vs-local.${device().id}.${"a".repeat(43)}`;
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); localStorage.clear(); sessionStorage.clear(); });

describe("local computer pairing", () => {
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
    fireEvent.change(screen.getByLabelText("Название компьютера"), { target: { value: "Домашний ПК" } });
    fireEvent.click(screen.getByRole("button", { name: "Подключить компьютер" }));
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
    fireEvent.change(screen.getByLabelText("Название компьютера"), { target: { value: "Домашний ПК" } });
    fireEvent.click(screen.getByRole("button", { name: "Подключить компьютер" }));
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
    fireEvent.change(screen.getByLabelText("Название компьютера"), { target: { value: "Домашний ПК" } });
    fireEvent.click(screen.getByRole("button", { name: "Подключить компьютер" }));
    expect(await screen.findByText(/Подтвердите пароль и 2FA/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Ключ подключения")).not.toBeInTheDocument();
  });
});
