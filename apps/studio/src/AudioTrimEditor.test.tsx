import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AudioTrimEditor } from "./AudioTrimEditor";

describe("audio trim boundaries", () => {
  it("requires explicit conversion and saves the exact original-time interval", async () => {
    const save = vi.fn().mockResolvedValue(undefined), dirty = vi.fn();
    render(<AudioTrimEditor duration={100} visual={null} options={{ output_format: "copy" }} disabled={false} onSave={save} onDirtyChange={dirty} />);
    await userEvent.clear(screen.getByLabelText("Начало"));
    await userEvent.type(screen.getByLabelText("Начало"), "12,5");
    expect(screen.getByRole("button", { name: "Применить границы" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("выберите WAV или FLAC");
    await userEvent.selectOptions(screen.getByLabelText("Формат результата"), "flac");
    await userEvent.click(screen.getByRole("button", { name: "Применить границы" }));
    expect(save).toHaveBeenCalledWith({ start_seconds: 12.5, end_seconds: null, output_format: "flac" });
    expect(dirty).toHaveBeenLastCalledWith(false);
  });
  it("accepts timecodes and preserves the exact fraction of a second", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(<AudioTrimEditor duration={7200} visual={null} options={{ output_format: "wav" }} disabled={false}
      onSave={save} onDirtyChange={vi.fn()} />);
    const start = screen.getByLabelText("Начало");
    const end = screen.getByLabelText("Конец");
    const apply = screen.getByRole("button", { name: "Применить границы" });
    await userEvent.clear(start);
    await userEvent.type(start, "00:10:15,25");
    await userEvent.clear(end);
    await userEvent.type(end, "01:71:00");
    expect(apply).toBeDisabled();
    await userEvent.clear(end);
    await userEvent.type(end, "01:30:00");
    await userEvent.click(apply);
    expect(save).toHaveBeenCalledWith({ start_seconds: 615.25, end_seconds: 5400, output_format: "wav" });
  });

  it("keeps invalid intermediate edits without allowing a render", async () => {
    const save = vi.fn(), dirty = vi.fn();
    render(<AudioTrimEditor duration={100} visual={null} options={{ output_format: "wav" }} disabled={false} onSave={save} onDirtyChange={dirty} />);
    await userEvent.clear(screen.getByLabelText("Конец"));
    expect(screen.getByRole("button", { name: "Применить границы" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Конец"), "101");
    expect(screen.getByRole("button", { name: "Применить границы" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Выделить всю запись" }));
    expect(screen.getByLabelText("Конец")).toHaveValue("00:01:40");
    expect(dirty).toHaveBeenLastCalledWith(false);
    expect(screen.getByRole("button", { name: "Применить границы" })).toBeDisabled();
    expect(save).not.toHaveBeenCalled();
  });
  it("keeps pending/failure edits and offers retry without false success", async () => {
    const save = vi.fn().mockRejectedValue(new Error("Источники недоступны"));
    render(<AudioTrimEditor duration={10} visual={null} options={{ output_format: "wav" }} disabled={false} onSave={save} onDirtyChange={vi.fn()} />);
    await userEvent.clear(screen.getByLabelText("Начало"));
    await userEvent.type(screen.getByLabelText("Начало"), "2");
    await userEvent.click(screen.getByRole("button", { name: "Применить границы" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Источники недоступны");
    expect(screen.getByLabelText("Начало")).toHaveValue("2");
  });
});
