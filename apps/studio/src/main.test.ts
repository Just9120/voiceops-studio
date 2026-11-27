import { afterEach, describe, expect, it, vi } from "vitest";

const registerSWMock = vi.hoisted(() => vi.fn());

vi.mock("virtual:pwa-register", () => ({
  registerSW: registerSWMock,
}));

afterEach(() => {
  vi.restoreAllMocks();
  registerSWMock.mockReset();
});

describe("service-worker diagnostics registration", () => {
  async function loadMainWithServiceWorker() {
    vi.resetModules();
    const diagnostics = await import("./pwaDiagnostics");
    const listeners: Record<string, EventListener> = {};
    Object.defineProperty(navigator, "serviceWorker", {
      value: { addEventListener: vi.fn((type: string, listener: EventListener) => { listeners[type] = listener; }) },
      configurable: true,
    });
    const emit = vi.spyOn(diagnostics, "emitPwaServiceWorkerError").mockImplementation(() => undefined);
    const mod = await import("./main");
    return { mod, listeners, emit };
  }

  it("registration failure emits one fixed safe event and successful registration emits none", async () => {
    const { mod, emit } = await loadMainWithServiceWorker();
    mod.initializePwaRuntime(true);
    mod.initializePwaRuntime(true);
    expect(registerSWMock).toHaveBeenCalledTimes(1);
    expect(emit).not.toHaveBeenCalled();
    const options = registerSWMock.mock.calls[0][0] as { onRegisterError: () => void };
    options.onRegisterError();
    expect(emit).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(registerSWMock.mock.calls)).not.toContain("synthetic-script-url");
    expect(options).toEqual(expect.objectContaining({
      immediate: true,
      onNeedRefresh: expect.any(Function),
      onNeedReload: expect.any(Function),
      onRegisteredSW: expect.any(Function),
    }));
  });

  it("messageerror emits without serializing message data and listener is not duplicated", async () => {
    const { mod, listeners, emit } = await loadMainWithServiceWorker();
    mod.initializePwaRuntime(true);
    mod.initializePwaRuntime(true);
    expect(Object.keys(listeners)).toEqual(["controllerchange", "messageerror"]);
    listeners.messageerror(new MessageEvent("messageerror", { data: { raw: "synthetic-message-data" } }));
    expect(emit).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(emit.mock.calls)).not.toContain("synthetic-message-data");
  });
});
