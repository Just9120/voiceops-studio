import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PwaConnectivityNotice, PwaUpdateNotice } from "./PwaUpdateNotice";
import { installPwaReturnChecks, PwaUpdateController } from "./pwaUpdates";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function registration(update = vi.fn(async () => undefined)) {
  return { waiting: null, update } as unknown as ServiceWorkerRegistration;
}

it("announces loss of network and clears the notice after reconnection", () => {
  const connected = vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(true);
  render(<><input aria-label="Черновик" defaultValue="Тестовый черновик" /><PwaConnectivityNotice /></>);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  connected.mockReturnValue(false);
  act(() => window.dispatchEvent(new Event("offline")));
  expect(screen.getByRole("status")).toHaveTextContent("Устройство без сети");
  connected.mockReturnValue(true);
  act(() => window.dispatchEvent(new Event("online")));
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "Черновик" })).toHaveValue("Тестовый черновик");
});

describe("PWA update choice", () => {
  it("keeps an unfinished form after Later and offers the waiting update on return", async () => {
    const reload = vi.fn();
    const controller = new PwaUpdateController(reload);
    controller.setRegistration(registration());
    controller.setUpdateWorker(vi.fn(async () => undefined));
    const user = userEvent.setup();
    render(<><input aria-label="Черновик" /><PwaUpdateNotice controller={controller} /></>);

    await user.type(screen.getByRole("textbox", { name: "Черновик" }), "несохранённый текст");
    act(() => controller.announceAvailable());
    expect(screen.getByRole("status")).toHaveTextContent("Доступна новая версия Studio");
    await user.click(screen.getByRole("button", { name: "Позже" }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Черновик" })).toHaveValue("несохранённый текст");
    expect(reload).not.toHaveBeenCalled();

    await act(async () => { await controller.checkOnReturn(); });
    expect(screen.getByRole("button", { name: "Обновить сейчас" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Черновик" })).toHaveValue("несохранённый текст");
    expect(reload).not.toHaveBeenCalled();
  });

  it("reloads only the tab that explicitly applies the update", async () => {
    const firstReload = vi.fn();
    const secondReload = vi.fn();
    const activate = vi.fn(async () => undefined);
    const first = new PwaUpdateController(firstReload);
    const second = new PwaUpdateController(secondReload);
    first.setUpdateWorker(activate);
    second.setUpdateWorker(vi.fn(async () => undefined));
    first.announceAvailable();
    second.announceAvailable();
    second.defer();

    await first.apply();
    expect(activate).toHaveBeenCalledTimes(1);
    expect(firstReload).not.toHaveBeenCalled();
    first.onControllerChange();
    second.onControllerChange();
    expect(firstReload).toHaveBeenCalledTimes(1);
    expect(secondReload).not.toHaveBeenCalled();
    expect(second.getSnapshot().visible).toBe(false);

    await second.checkOnReturn();
    expect(second.getSnapshot().visible).toBe(true);
    await second.apply();
    expect(secondReload).toHaveBeenCalledTimes(1);
  });

  it("checks on return without duplicate requests and leaves offline/failing sessions usable", async () => {
    const reportError = vi.fn();
    const update = vi.fn(async () => undefined);
    const controller = new PwaUpdateController(vi.fn(), reportError);
    controller.setRegistration(registration(update));
    const uninstall = installPwaReturnChecks(controller);
    try {
      vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
      await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
      expect(update).not.toHaveBeenCalled();
      vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
      vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
      await act(async () => { window.dispatchEvent(new Event("focus")); });
      expect(update).not.toHaveBeenCalled();

      vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
      await act(async () => { window.dispatchEvent(new Event("online")); });
      await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
      expect(update).toHaveBeenCalledTimes(1);
      expect(controller.getSnapshot().visible).toBe(false);

      update.mockRejectedValueOnce(new Error("synthetic network failure"));
      vi.spyOn(Date, "now").mockReturnValue(Date.now() + 61_000);
      await act(async () => { window.dispatchEvent(new Event("focus")); });
      expect(update).toHaveBeenCalledTimes(2);
      expect(reportError).toHaveBeenCalledTimes(1);
      expect(controller.getSnapshot().visible).toBe(false);
    } finally {
      uninstall();
    }
  });

  it("recovers the update action when activation stalls or rejects", async () => {
    vi.useFakeTimers();
    const reportError = vi.fn();
    const controller = new PwaUpdateController(vi.fn(), reportError);
    controller.announceAvailable();
    controller.setUpdateWorker(vi.fn(async () => undefined));
    await controller.apply();
    expect(controller.getSnapshot().applying).toBe(true);
    await vi.advanceTimersByTimeAsync(15_000);
    expect(controller.getSnapshot()).toEqual({ visible: true, applying: false, error: true });

    controller.setUpdateWorker(vi.fn(async () => { throw new Error("synthetic activation failure"); }));
    await controller.apply();
    expect(controller.getSnapshot()).toEqual({ visible: true, applying: false, error: true });
    expect(reportError).toHaveBeenCalledTimes(1);
  });

  it("does not offer an update for an ordinary first registration", () => {
    const controller = new PwaUpdateController(vi.fn());
    controller.setRegistration(registration());
    controller.onControllerChange(false);
    expect(controller.getSnapshot()).toEqual({ visible: false, applying: false, error: false });
  });

  it("reloads after an explicitly requested activation even if the page had no controller", async () => {
    const reload = vi.fn();
    const controller = new PwaUpdateController(reload);
    controller.setUpdateWorker(vi.fn(async () => undefined));
    controller.announceAvailable();

    await controller.apply();
    controller.onControllerChange(false);
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
