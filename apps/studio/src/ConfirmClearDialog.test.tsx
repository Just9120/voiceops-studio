import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConfirmClearDialog } from "./ConfirmClearDialog";

describe("ConfirmClearDialog", () => {
  it("supports three explicit Live actions and restores focus to an available control", async () => {
    const trigger = document.createElement("button"), fallback = document.createElement("button");
    document.body.append(trigger,fallback); trigger.focus();
    const stop = vi.fn(), cancel = vi.fn();
    const view = render(<ConfirmClearDialog title="Очистить Live?" description="Другие сессии сохранятся."
      pending={false} confirmLabel="Очистить и продолжить" cancelLabel="Отмена"
      secondaryConfirm={{label:"Остановить и очистить",onClick:stop}} onConfirm={vi.fn()} onCancel={cancel}
      fallbackFocus={() => fallback.focus()} />);
    expect(screen.getByRole("button",{name:"Отмена"})).toHaveFocus();
    await userEvent.click(screen.getByRole("button",{name:"Остановить и очистить"}));
    expect(stop).toHaveBeenCalledOnce(); expect(cancel).not.toHaveBeenCalled();
    trigger.disabled = true; view.unmount(); expect(fallback).toHaveFocus();
    trigger.remove(); fallback.remove();
  });
  it("requires an explicit Да and keeps Нет as a separate safe action", async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmClearDialog
        title="Очистить историю?"
        description="Данные не удаляются."
        pending={false}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    expect(screen.getByRole("dialog", { name: "Очистить историю?" }))
      .toHaveAttribute("aria-modal", "true");
    await userEvent.click(screen.getByRole("button", { name: "Нет" }));
    expect(onCancel).toHaveBeenCalledOnce();
    expect(onConfirm).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Да" }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("blocks both actions while the clear request is pending", () => {
    render(
      <ConfirmClearDialog
        title="Очистить?"
        description="Подтверждение"
        pending
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Очищаем…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Нет" })).toBeDisabled();
  });

  it("focuses the safe action, traps Tab, closes on Escape, and returns focus", async () => {
    const onCancel = vi.fn();
    const trigger = document.createElement("button");
    trigger.textContent = "Открыть";
    document.body.append(trigger);
    trigger.focus();
    const view = render(
      <ConfirmClearDialog
        title="Очистить?"
        description="Подтверждение"
        pending={false}
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );

    const no = screen.getByRole("button", { name: "Нет" });
    const yes = screen.getByRole("button", { name: "Да" });
    expect(no).toHaveFocus();
    await userEvent.tab();
    expect(yes).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(no).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledOnce();

    view.unmount();
    expect(trigger).toHaveFocus();
    trigger.remove();
  });
});
