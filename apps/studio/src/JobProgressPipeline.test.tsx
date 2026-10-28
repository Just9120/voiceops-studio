import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { JobProgressPipeline } from "./JobProgressPipeline";
import type { JobProgressState } from "./jobProgressModel";

const state: JobProgressState = {
  loading: false,
  error: "",
  data: {
    job_id: "job-1",
    job_status: "processing",
    tracking_precision: "checkpoint",
    completed_source_count: 0,
    total_source_count: 1,
    active_source_position: 0,
    current_stage: "provider_processing",
    sources: [
      {
        position: 0,
        name: "Interview.mp4",
        status: "processing",
        provider_parts: { completed: 1, total: 4 },
        stages: [
          { key: "preparation", status: "completed", applicability: "required" },
          {
            key: "audio_extraction",
            status: "completed",
            applicability: "required",
          },
          { key: "splitting", status: "completed", applicability: "conditional" },
          {
            key: "provider_processing",
            status: "active",
            applicability: "required",
          },
          { key: "part_merge", status: "pending", applicability: "conditional" },
          {
            key: "google_docs_output",
            status: "pending",
            applicability: "required",
          },
        ],
      },
    ],
  },
};

describe("JobProgressPipeline", () => {
  it("renders one live meter with the current user-facing action", () => {
    render(<JobProgressPipeline jobId="job-1" state={state} />);
    const pipeline = screen.getByLabelText("Прогресс задачи job-1");
    expect(pipeline).toHaveAttribute("aria-busy", "true");
    expect(pipeline).toHaveTextContent("Транскрибируем часть 2 из 4");
    expect(pipeline).toHaveTextContent("Подтверждено 54%");
    expect(pipeline).toHaveTextContent("Сейчас: Interview.mp4");
    const meter = within(pipeline).getByRole("progressbar", {
      name: "Общий прогресс транскрибации",
    });
    expect(meter).toHaveAttribute("aria-valuenow", "54");
    expect(meter).toHaveAttribute(
      "aria-valuetext",
      "54% подтверждено. Транскрибируем часть 2 из 4",
    );
    expect(meter).toHaveClass("is-active");

    expect(
      within(pipeline).getByText("Подробности по этапам"),
    ).toBeInTheDocument();
    const steps = within(pipeline).getAllByRole("listitem");
    expect(steps).toHaveLength(6);
    expect(steps[0]).toHaveTextContent("Подготовка источника");
    expect(steps[2]).toHaveTextContent("Разбиение на части (при необходимости)");
    expect(steps[2]).toHaveTextContent("Проверено");
    expect(steps[3]).toHaveTextContent("Распознавание речи");
    expect(steps[3]).toHaveTextContent("Выполняется");
    expect(steps[5]).toHaveTextContent("Сохранение документа");
    expect(pipeline).toHaveTextContent("Части ElevenLabs: 1 из 4");
  });

  it("keeps terminal progress still and announces the outcome", () => {
    render(
      <JobProgressPipeline
        jobId="job-1"
        state={{
          ...state,
          data: {
            ...state.data!,
            job_status: "completed",
            completed_source_count: 1,
            current_stage: null,
          },
        }}
      />,
    );

    const pipeline = screen.getByLabelText("Прогресс задачи job-1");
    expect(pipeline).toHaveAttribute("aria-busy", "false");
    expect(pipeline).toHaveTextContent("Транскрибация завершена");
    expect(
      within(pipeline).getByRole("progressbar", {
        name: "Общий прогресс транскрибации",
      }),
    ).not.toHaveClass("is-active");

    render(
      <JobProgressPipeline
        jobId="job-failed"
        state={{
          ...state,
          data: {
            ...state.data!,
            job_id: "job-failed",
            job_status: "failed",
            current_stage: "provider_processing",
          },
        }}
      />,
    );
    const failed = screen.getByLabelText("Прогресс задачи job-failed");
    expect(failed).toHaveTextContent("Не удалось завершить транскрибацию");
    expect(failed).not.toHaveTextContent("Транскрибируем часть 2 из 4");
  });

  it("keeps the last confirmed state visible after a refresh failure", () => {
    render(
      <JobProgressPipeline
        jobId="job-1"
        state={{ ...state, error: "refresh_failed" }}
      />,
    );
    expect(screen.getByLabelText("Прогресс задачи job-1")).toHaveTextContent(
      "показан последний подтверждённый статус",
    );
  });
});
