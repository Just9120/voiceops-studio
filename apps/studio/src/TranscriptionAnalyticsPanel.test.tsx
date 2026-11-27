import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TranscriptionAnalyticsPanel } from "./TranscriptionAnalyticsPanel";

const analytics = {
  scope: "project_all_time",
  totals: { jobs: 3, sources: 4, outputs: 1 },
  outcomes: {
    queued: 1,
    processing: 0,
    completed: 1,
    failed: 1,
    cancelled: 0,
  },
  success: {
    successful_jobs: 1,
    terminal_jobs: 2,
    percentage: 50,
  },
  configuration: {
    provider_model: { elevenlabs_scribe_v2: 2, unknown: 1 },
    language_mode: { ru: 1, en: 1, detect: 1, other: 0 },
    diarization: { enabled: 1, disabled: 2 },
  },
  usage_cost: {
    confirmed_billed_duration_seconds: 3600,
    confirmed_provider_cost: "0.22000000",
    currency: "USD",
    cost_basis: "confirmed_audio_duration_x_rate_snapshot",
    complete_jobs: 1,
    uncertain_jobs: 1,
    unavailable_jobs: 1,
    in_progress_jobs: 0,
  },
  durations: {
    queue: {
      sample_count: 2,
      average_seconds: 15,
      p50_seconds: 10,
      p95_seconds: 20,
    },
    processing: {
      sample_count: 2,
      average_seconds: 75,
      p50_seconds: 60,
      p95_seconds: 90,
    },
    provider_processing: {
      sample_count: 1,
      average_seconds: 3600,
      p50_seconds: 3600,
      p95_seconds: 3600,
    },
    post_provider_output: {
      sample_count: 0,
      average_seconds: null,
      p50_seconds: null,
      p95_seconds: null,
    },
  },
};

describe("TranscriptionAnalyticsPanel", () => {
  it("never rounds a positive tiny cost to zero and keeps exact precision in details", async () => {
    render(<TranscriptionAnalyticsPanel projectId="fixture-project" loadAnalytics={vi.fn().mockResolvedValue({ ...analytics, usage_cost: { ...analytics.usage_cost, confirmed_provider_cost: "0.00077073" } })} />);
    await userEvent.click(screen.getByText("Аналитика транскрибаций"));
    expect(await screen.findByText(/< 0,01 USD/)).toBeInTheDocument();
    await userEvent.click(screen.getByText("Расход по всем STT-провайдерам", { exact: true }));
    await userEvent.click(screen.getByText("Точное значение стоимости"));
    expect(screen.getByText(/0.00077073 USD/)).toBeVisible();
  });
  it("shows Yandex models alongside historical ElevenLabs counts", async () => {
    const result = structuredClone(analytics);
    const provider_model = { elevenlabs_scribe_v2: 1, yandex_general: 1, yandex_deferred_general: 1, unknown: 0 };
    render(<TranscriptionAnalyticsPanel projectId="fixture-project" loadAnalytics={vi.fn().mockResolvedValue({ ...result, configuration: { ...result.configuration, provider_model } })} />);
    await userEvent.click(screen.getByText("Аналитика транскрибаций"));
    expect(await screen.findByText("Yandex SpeechKit · general 1")).toBeInTheDocument();
    expect(screen.getByText("Yandex SpeechKit · deferred-general 1")).toBeInTheDocument();
    expect(screen.getByText("ElevenLabs · scribe_v2 1")).toBeInTheDocument();
    expect(screen.queryByText(/Не определено:/)).not.toBeInTheDocument();
  });
  it("loads on demand and renders safe aggregate evidence", async () => {
    const loadAnalytics = vi.fn().mockResolvedValue(analytics);
    render(
      <TranscriptionAnalyticsPanel
        projectId="project-private-id"
        loadAnalytics={loadAnalytics}
      />,
    );

    expect(loadAnalytics).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getByText("Аналитика транскрибаций"),
    );
    await waitFor(() =>
      expect(loadAnalytics).toHaveBeenCalledWith(
        "project-private-id",
        expect.any(AbortSignal),
      ),
    );

    expect(await screen.findByText("ElevenLabs · scribe_v2 2")).toBeInTheDocument();
    expect(screen.getByLabelText("Успешность транскрибаций")).toHaveTextContent(
      "Успешность: 50,0%",
    );
    expect(screen.getByText("Успешно 1 из 2 завершённых исходов.")).toBeInTheDocument();
    expect(screen.getByText(/английский 1/)).toBeInTheDocument();
    expect(screen.getByText("Среднее: 1 ч")).toBeInTheDocument();
    expect(screen.getByText("0,22 USD")).toBeInTheDocument();
    expect(screen.getByText("Подтверждённо отправлено")).toBeInTheDocument();
    expect(screen.getByText(/Фактические списания после подписки или квоты/)).toBeInTheDocument();
    const outcomes = screen.getByRole("region", {
      name: "Исходы транскрибаций",
    });
    expect(within(outcomes).getByText("Готово", { exact: false })).toHaveTextContent(
      "Готово 1",
    );
    expect(screen.queryByText("project-private-id")).not.toBeInTheDocument();
    const glossary = screen
      .getByText("Как читать метрики длительности")
      .closest("details");
    expect(glossary).not.toHaveAttribute("open");
    expect(
      within(glossary as HTMLElement).getByText("Медиана"),
    ).toBeInTheDocument();
    expect(
      within(glossary as HTMLElement).getByText("p95"),
    ).toBeInTheDocument();
    expect(
      within(glossary as HTMLElement).getByText("Замеры"),
    ).toBeInTheDocument();
  });

  it("fails closed when the aggregate DTO is malformed", async () => {
    render(
      <TranscriptionAnalyticsPanel
        projectId="p1"
        loadAnalytics={() =>
          Promise.resolve({ ...analytics, transcript_body: "private text" })
        }
      />,
    );

    await userEvent.click(screen.getByText("Аналитика транскрибаций"));
    expect(
      await screen.findByText(/Аналитика временно недоступна/),
    ).toBeInTheDocument();
    expect(screen.queryByText("private text")).not.toBeInTheDocument();
  });

  it("states honestly when success percentage has no terminal denominator", async () => {
    const emptyAnalytics = {
      ...analytics,
      totals: { jobs: 1, sources: 1, outputs: 0 },
      outcomes: {
        queued: 1,
        processing: 0,
        completed: 0,
        failed: 0,
        cancelled: 0,
      },
      success: {
        successful_jobs: 0,
        terminal_jobs: 0,
        percentage: null,
      },
      configuration: {
        provider_model: { elevenlabs_scribe_v2: 1, unknown: 0 },
        language_mode: { ru: 1, en: 0, detect: 0, other: 0 },
        diarization: { enabled: 0, disabled: 1 },
      },
      usage_cost: {
        ...analytics.usage_cost,
        confirmed_billed_duration_seconds: 0,
        confirmed_provider_cost: "0.00000000",
        complete_jobs: 0,
        uncertain_jobs: 0,
        unavailable_jobs: 0,
        in_progress_jobs: 1,
      },
    };
    render(
      <TranscriptionAnalyticsPanel
        projectId="p1"
        loadAnalytics={() => Promise.resolve(emptyAnalytics)}
      />,
    );

    await userEvent.click(screen.getByText("Аналитика транскрибаций"));
    expect(
      await screen.findByText("Успешность: Нет завершённых исходов"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Успешно 0 из 0/)).not.toBeInTheDocument();
  });

  it("bounds a stalled read and retries without exposing raw failures", async () => {
    let requests = 0;
    let stalledSignal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        requests += 1;
        if (requests === 1) {
          stalledSignal = init?.signal;
          return new Promise<Response>((_resolve, reject) => {
            stalledSignal?.addEventListener("abort", () =>
              reject(new Error("raw-analytics-timeout")),
            );
          });
        }
        return Promise.resolve(
          new Response(JSON.stringify(analytics), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
        );
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
      render(<TranscriptionAnalyticsPanel projectId="p1" />);
      await userEvent.click(screen.getByText("Аналитика транскрибаций"));
      expect(
        await screen.findByText(/Аналитика временно недоступна/),
      ).toBeInTheDocument();
      expect(stalledSignal?.aborted).toBe(true);
      expect(requests).toBe(1);
      expect(document.body.textContent).not.toContain("raw-analytics-timeout");

      await userEvent.click(screen.getByRole("button", { name: "Обновить" }));
      expect(await screen.findByText("Задачи")).toBeInTheDocument();
      expect(requests).toBe(2);
    } finally {
      timeoutSpy.mockRestore();
      vi.unstubAllGlobals();
    }
  });

  it("aborts project teardown and ignores a late stale success", async () => {
    let staleSignal: AbortSignal | undefined;
    let resolveStale: ((value: unknown) => void) | undefined;
    const currentAnalytics = {
      ...analytics,
      durations: {
        ...analytics.durations,
        queue: {
          sample_count: 2,
          average_seconds: 99,
          p50_seconds: 90,
          p95_seconds: 120,
        },
      },
    };
    const loadAnalytics = vi.fn((projectId: string, signal?: AbortSignal) => {
      if (projectId === "p1") {
        staleSignal = signal;
        return new Promise((resolve) => {
          resolveStale = resolve;
        });
      }
      return Promise.resolve(currentAnalytics);
    });
    const { rerender } = render(
      <TranscriptionAnalyticsPanel
        key="p1"
        projectId="p1"
        loadAnalytics={loadAnalytics}
      />,
    );
    await userEvent.click(screen.getByText("Аналитика транскрибаций"));
    await waitFor(() => expect(resolveStale).toBeDefined());

    rerender(
      <TranscriptionAnalyticsPanel
        key="p2"
        projectId="p2"
        loadAnalytics={loadAnalytics}
      />,
    );
    expect(staleSignal?.aborted).toBe(true);
    await userEvent.click(screen.getByText("Аналитика транскрибаций"));
    expect(await screen.findByText("Среднее: 1 мин 39 с")).toBeInTheDocument();

    await act(async () => resolveStale?.(analytics));
    expect(screen.getByText("Среднее: 1 мин 39 с")).toBeInTheDocument();
    expect(screen.queryByText("Среднее: 15 с")).not.toBeInTheDocument();
  });

  it("preserves confirmed aggregates when an explicit refresh fails", async () => {
    const loadAnalytics = vi
      .fn()
      .mockResolvedValueOnce(analytics)
      .mockRejectedValueOnce(new Error("raw-analytics-refresh-failure"));
    render(
      <TranscriptionAnalyticsPanel
        projectId="p1"
        loadAnalytics={loadAnalytics}
      />,
    );
    await userEvent.click(screen.getByText("Аналитика транскрибаций"));
    expect(await screen.findByText("ElevenLabs · scribe_v2 2")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Обновить" }));
    expect(
      await screen.findByText(/показана последняя подтверждённая версия/),
    ).toBeInTheDocument();
    expect(screen.getByText("ElevenLabs · scribe_v2 2")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(
      "raw-analytics-refresh-failure",
    );
    expect(loadAnalytics).toHaveBeenCalledTimes(2);
  });

  it("clears only after Да and reloads the reset aggregate scope", async () => {
    const resetAnalytics = {
      ...analytics,
      scope: "project_since_reset",
      totals: { jobs: 0, sources: 0, outputs: 0 },
      outcomes: {
        queued: 0,
        processing: 0,
        completed: 0,
        failed: 0,
        cancelled: 0,
      },
      success: {
        successful_jobs: 0,
        terminal_jobs: 0,
        percentage: null,
      },
      configuration: {
        provider_model: { elevenlabs_scribe_v2: 0, unknown: 0 },
        language_mode: { ru: 0, en: 0, detect: 0, other: 0 },
        diarization: { enabled: 0, disabled: 0 },
      },
      usage_cost: {
        ...analytics.usage_cost,
        confirmed_billed_duration_seconds: 0,
        confirmed_provider_cost: "0.00000000",
        complete_jobs: 0,
        uncertain_jobs: 0,
        unavailable_jobs: 0,
        in_progress_jobs: 0,
      },
      durations: Object.fromEntries(
        Object.keys(analytics.durations).map((key) => [
          key,
          {
            sample_count: 0,
            average_seconds: null,
            p50_seconds: null,
            p95_seconds: null,
          },
        ]),
      ),
    };
    const loadAnalytics = vi
      .fn()
      .mockResolvedValueOnce(analytics)
      .mockResolvedValueOnce(resetAnalytics);
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: true,
          reset_at: "2026-08-21T12:00:00Z",
          hidden_job_count: 3,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    try {
      render(
        <TranscriptionAnalyticsPanel
          projectId="p1"
          csrf="csrf-safe"
          onCsrf={vi.fn()}
          loadAnalytics={loadAnalytics}
        />,
      );
      await userEvent.click(screen.getByText("Аналитика транскрибаций"));
      expect(await screen.findByText("ElevenLabs · scribe_v2 2"))
        .toBeInTheDocument();

      await userEvent.click(screen.getByRole("button", { name: "Действия аналитики" }));
      await userEvent.click(screen.getByRole("menuitem", { name: "Очистить аналитику" }));
      expect(screen.getByRole("button", { name: "Да" })).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "Нет" }));
      expect(fetchMock).not.toHaveBeenCalled();

      await userEvent.click(screen.getByRole("button", { name: "Действия аналитики" }));
      await userEvent.click(screen.getByRole("menuitem", { name: "Очистить аналитику" }));
      await userEvent.click(screen.getByRole("button", { name: "Да" }));
      await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/projects/p1/transcription-analytics/clear",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ confirm_clear: true }),
        }),
      );
      expect(
        await screen.findByText(
          "Аналитика очищена. Новые метрики считаются с этого момента.",
        ),
      ).toBeInTheDocument();
      expect(screen.getByText(/Агрегаты с момента последней очистки/))
        .toBeInTheDocument();
      expect(loadAnalytics).toHaveBeenCalledTimes(2);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
