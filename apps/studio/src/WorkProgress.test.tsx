import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WorkProgressDetail, parseWorkProgress } from "./WorkProgress";

const value = { stage: "media_processing", completed: 30, total: 120, unit: "seconds",
  started_at: "2026-10-28T10:00:00Z", updated_at: "2026-10-28T10:00:05Z", sequence: 2, generation: 1 };
describe("measured work progress", () => {
  it("labels the measured stage instead of claiming a total job percentage", () => {
    render(<WorkProgressDetail value={value} />);
    expect(screen.getByText(/25% этапа/)).toBeVisible();
    expect(screen.getByText("0:30 из 2:00")).toBeVisible();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });
  it("does not manufacture provider percentages", () => {
    render(<WorkProgressDetail value={{ ...value, stage: "provider_wait", completed: null, total: null, unit: null }} />);
    expect(screen.getByText(/Сервис не сообщает процент/)).toBeVisible();
    expect(screen.queryByText(/% этапа/)).not.toBeInTheDocument();
  });
  it("rejects malformed and unsupported measurements", () => {
    expect(parseWorkProgress({ ...value, completed: Infinity })).toBeNull();
    expect(parseWorkProgress({ ...value, started_at: "invalid" })).toBeNull();
    expect(parseWorkProgress({ ...value, stage: "private/path" })).toBeNull();
    expect(parseWorkProgress({ ...value, sequence: -1 })).toBeNull();
  });
});
