import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Login } from "./Login";

const json = (body: unknown, ok = true, status = 200) =>
  Promise.resolve({
    ok,
    status,
    json: () => Promise.resolve(body),
    clone: () => ({ json: () => Promise.resolve(body) }),
  } as Response);

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Login auth boundary", () => {
  it("bounds and validates bootstrap status before exposing the form", async () => {
    const bootstrapSignals: AbortSignal[] = [];
    let bootstrapReads = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (!url.endsWith("/api/auth/bootstrap-status")) {
          throw new Error(`Unexpected request: ${url}`);
        }
        bootstrapReads += 1;
        if (bootstrapReads === 1) {
          const signal = init?.signal;
          if (!signal) throw new Error("Bootstrap signal is missing");
          bootstrapSignals.push(signal);
          return new Promise<Response>((_resolve, reject) => {
            signal.addEventListener("abort", () => reject(signal.reason));
          });
        }
        if (bootstrapReads === 2) {
          return json({
            bootstrap_required: "raw-bootstrap-value",
            raw_bootstrap_field: "raw-bootstrap-secret",
          });
        }
        return json({ bootstrap_required: false });
      }),
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
      render(<Login onLogin={vi.fn()} />);
      expect(screen.getByRole("status")).toHaveTextContent(
        "Проверяем готовность входа",
      );
      expect(
        screen.queryByRole("heading", { name: "Вход" }),
      ).not.toBeInTheDocument();

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Не удалось проверить готовность входа",
      );
      expect(bootstrapSignals).toHaveLength(1);
      expect(bootstrapSignals[0]?.aborted).toBe(true);

      await userEvent.click(screen.getByRole("button", { name: "Повторить" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Не удалось проверить готовность входа",
      );
      expect(document.body.textContent).not.toContain("raw-bootstrap-value");
      expect(document.body.textContent).not.toContain("raw-bootstrap-secret");

      await userEvent.click(screen.getByRole("button", { name: "Повторить" }));
      expect(
        await screen.findByRole("heading", { name: "Вход" }),
      ).toBeInTheDocument();
      expect(bootstrapReads).toBe(3);
      expect(screen.queryByRole("button", { name: "Забыли пароль?" })).not.toBeInTheDocument();
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("renders the operator-only bootstrap state from a valid decision", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => json({ bootstrap_required: true })),
    );

    render(<Login onLogin={vi.fn()} />);

    expect(
      await screen.findByRole("heading", {
        name: "Требуется первичная настройка",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
  });

  it("keeps both login stages bounded, single-flight, and explicitly retryable", async () => {
    const contextSignals: AbortSignal[] = [];
    const loginSignals: AbortSignal[] = [];
    let secondContextSignal: AbortSignal | undefined;
    let contextReads = 0;
    let loginReads = 0;
    const onLogin = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith("/api/auth/bootstrap-status")) {
          return json({ bootstrap_required: false });
        }
        if (url.endsWith("/api/auth/login-context")) {
          contextReads += 1;
          const signal = init?.signal;
          if (!signal) throw new Error("Login-context signal is missing");
          if (contextReads === 1) {
            contextSignals.push(signal);
            return new Promise<Response>((_resolve, reject) => {
              signal.addEventListener("abort", () => reject(signal.reason));
            });
          }
          if (contextReads === 2) secondContextSignal = signal;
          return json({ login_csrf_token: `login-csrf-${contextReads}` });
        }
        if (url.endsWith("/api/auth/login")) {
          loginReads += 1;
          const signal = init?.signal;
          if (!signal) throw new Error("Login signal is missing");
          if (loginReads === 1) {
            loginSignals.push(signal);
            return new Promise<Response>((_resolve, reject) => {
              signal.addEventListener("abort", () => reject(signal.reason));
            });
          }
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
            csrf_token: "csrf-authenticated",
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
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
      const { container } = render(<Login onLogin={onLogin} />);
      await screen.findByRole("heading", { name: "Вход" });
      await userEvent.type(screen.getByLabelText("Email"), "user@example.com");
      await userEvent.type(screen.getByLabelText("Пароль"), "password-long");
      const form = container.querySelector("form");
      if (!form) throw new Error("Login form is missing");

      fireEvent.submit(form);
      fireEvent.submit(form);
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Не удалось войти",
      );
      expect(contextReads).toBe(1);
      expect(loginReads).toBe(0);
      expect(contextSignals[0]?.aborted).toBe(true);

      fireEvent.submit(form);
      fireEvent.submit(form);
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Не удалось войти",
      );
      expect(contextReads).toBe(2);
      expect(loginReads).toBe(1);
      expect(loginSignals[0]).toBe(secondContextSignal);
      expect(loginSignals[0]?.aborted).toBe(true);

      fireEvent.submit(form);
      await waitFor(() =>
        expect(onLogin).toHaveBeenCalledWith(
          { email: "user@example.com", role: "admin", accent_color: "blue" },
          "csrf-authenticated",
        ),
      );
      expect(contextReads).toBe(3);
      expect(loginReads).toBe(2);
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("rejects malformed login DTOs without rendering raw fields", async () => {
    let contextReads = 0;
    let loginReads = 0;
    const onLogin = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url.endsWith("/api/auth/bootstrap-status")) {
          return json({ bootstrap_required: false });
        }
        if (url.endsWith("/api/auth/login-context")) {
          contextReads += 1;
          if (contextReads === 1) {
            return json({
              login_csrf_token: " raw-login-context ",
              raw_context_field: "raw-context-secret",
            });
          }
          return json({ login_csrf_token: `context-${contextReads}` });
        }
        if (url.endsWith("/api/auth/login")) {
          loginReads += 1;
          if (loginReads === 1) {
            return json({
              authenticated: true,
              user: { email: "user@example.com", role: "raw-role" },
              csrf_token: "raw-login-token",
              raw_login_field: "raw-login-secret",
            });
          }
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "user" },
            csrf_token: "csrf-safe",
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );

    const { container } = render(<Login onLogin={onLogin} />);
    await screen.findByRole("heading", { name: "Вход" });
    await userEvent.type(screen.getByLabelText("Email"), "user@example.com");
    await userEvent.type(screen.getByLabelText("Пароль"), "password-long");
    const form = container.querySelector("form");
    if (!form) throw new Error("Login form is missing");

    fireEvent.submit(form);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Не удалось войти",
    );
    expect(document.body.textContent).not.toContain("raw-login-context");
    expect(document.body.textContent).not.toContain("raw-context-secret");

    fireEvent.submit(form);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Не удалось войти",
    );
    expect(document.body.textContent).not.toContain("raw-role");
    expect(document.body.textContent).not.toContain("raw-login-token");
    expect(document.body.textContent).not.toContain("raw-login-secret");

    fireEvent.submit(form);
    await waitFor(() =>
      expect(onLogin).toHaveBeenCalledWith(
        { email: "user@example.com", role: "user", accent_color: "blue" },
        "csrf-safe",
      ),
    );
    expect(contextReads).toBe(3);
    expect(loginReads).toBe(2);
  });

  it("aborts login ownership on teardown and ignores a late success", async () => {
    let loginSignal: AbortSignal | undefined;
    let resolveLogin: ((response: Response) => void) | undefined;
    const onLogin = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith("/api/auth/bootstrap-status")) {
          return json({ bootstrap_required: false });
        }
        if (url.endsWith("/api/auth/login-context")) {
          return json({ login_csrf_token: "login-context" });
        }
        if (url.endsWith("/api/auth/login")) {
          loginSignal = init?.signal;
          return new Promise<Response>((resolve) => {
            resolveLogin = resolve;
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );

    const { unmount } = render(<Login onLogin={onLogin} />);
    await screen.findByRole("heading", { name: "Вход" });
    await userEvent.type(screen.getByLabelText("Email"), "user@example.com");
    await userEvent.type(screen.getByLabelText("Пароль"), "password-long");
    await userEvent.click(screen.getByRole("button", { name: "Войти" }));
    await waitFor(() => expect(resolveLogin).toBeDefined());

    unmount();
    expect(loginSignal?.aborted).toBe(true);
    resolveLogin?.(
      await json({
        authenticated: true,
        user: { email: "late@example.com", role: "admin" },
        csrf_token: "late-csrf",
      }),
    );
    await Promise.resolve();
    expect(onLogin).not.toHaveBeenCalled();
  });

  it("requests optional second-factor material only after the server requires it", async () => {
    const loginBodies: Array<Record<string, unknown>> = [];
    let loginAttempts = 0;
    const onLogin = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith("/api/auth/bootstrap-status")) {
          return json({ bootstrap_required: false });
        }
        if (url.endsWith("/api/auth/login-context")) {
          return json({ login_csrf_token: `context-${loginAttempts + 1}` });
        }
        if (url.endsWith("/api/auth/login")) {
          loginAttempts += 1;
          loginBodies.push(JSON.parse(String(init?.body)));
          if (loginAttempts === 1) {
            return json(
              { detail: { reason: "second_factor_required" } },
              false,
              409,
            );
          }
          if (loginAttempts === 2) {
            return json({ detail: "Неверная почта или пароль" }, false, 401);
          }
          if (loginAttempts === 3) {
            return json({ detail: { reason: "second_factor_invalid" } }, false, 401);
          }
          return json({
            authenticated: true,
            user: { email: "user@example.com", role: "admin" },
            csrf_token: "csrf-authenticated",
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );

    render(<Login onLogin={onLogin} />);
    await screen.findByRole("heading", { name: "Вход" });
    await userEvent.type(screen.getByLabelText("Email"), "user@example.com");
    await userEvent.type(screen.getByLabelText("Пароль"), "password-long");
    await userEvent.click(screen.getByRole("button", { name: "Войти" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Введите код из приложения-аутентификатора или резервный код",
    );
    expect(screen.getByLabelText("Одноразовый код")).toHaveAttribute(
      "autocomplete",
      "one-time-code",
    );
    await userEvent.type(screen.getByLabelText("Одноразовый код"), "000000");
    await userEvent.click(screen.getByRole("button", { name: "Войти" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Неверная почта или пароль");
    await userEvent.click(screen.getByRole("button", { name: "Войти" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Неверный одноразовый или резервный код",
    );

    await userEvent.clear(screen.getByLabelText("Одноразовый код"));
    await userEvent.type(screen.getByLabelText("Одноразовый код"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Войти" }));
    await waitFor(() =>
      expect(onLogin).toHaveBeenCalledWith(
        { email: "user@example.com", role: "admin", accent_color: "blue" },
        "csrf-authenticated",
      ),
    );
    expect(loginBodies).toEqual([
      {
        email: "user@example.com",
        password: "password-long",
        login_csrf_token: "context-1",
      },
      {
        email: "user@example.com",
        password: "password-long",
        login_csrf_token: "context-2",
        verification_code: "000000",
      },
      {
        email: "user@example.com",
        password: "password-long",
        login_csrf_token: "context-3",
        verification_code: "000000",
      },
      {
        email: "user@example.com",
        password: "password-long",
        login_csrf_token: "context-4",
        verification_code: "123456",
      },
    ]);
  });
});
