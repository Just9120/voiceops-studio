import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  JobOutputsResponse,
  JobSource,
  JobUsageCost,
  TranscriptionJob,
} from "./jobModel";
import type { JobRetryState } from "./jobRecoveryModel";
import { JobDetailSection } from "./JobDetailSection";

function source(
  id: string,
  position: number,
  driveFileUrl: string | null,
): JobSource {
  return {
    id,
    project_id: "project-1",
    source_type: "local_upload",
    original_filename: `${id}.ogg`,
    mime_type: "audio/ogg",
    size_bytes: 1024,
    drive_file_url: driveFileUrl,
    upload_status: "uploaded",
    uploaded_at: "2026-07-22T09:00:00Z",
    expires_at: null,
    deleted_at: null,
    delete_reason: null,
    created_at: "2026-07-22T08:00:00Z",
    updated_at: "2026-07-22T09:00:00Z",
    position,
    job_source_status: "queued",
  };
}

const job: TranscriptionJob = {
  id: "job-1",
  project_id: "project-1",
  status: "failed",
  title: "Interview",
  provider: "elevenlabs",
  language_mode: "ru",
  diarization_enabled: true,
  source_count: 2,
  sources: [
    source("second", 1, "https://evil.example/file/token"),
    source("first", 0, "https://drive.example/file/safe"),
  ],
  created_at: "2026-07-22T10:00:00Z",
  updated_at: "2026-07-22T10:00:00Z",
  cancelled_at: null,
  cancel_requested_at: null,
  attempt_count: 1,
  started_at: null,
  finished_at: null,
  error_code: "provider_error",
  error_message: "Provider failed",
  output_folder: {
    name: "Results",
    web_view_url: "https://drive.example/folder/safe",
  },
};

const completeUsage: JobUsageCost = {
  accounting_status: "complete",
  confirmed_billed_duration_seconds: 12.612,
  confirmed_provider_cost: "0.00077073",
  currency: "USD",
  cost_basis: "confirmed_audio_duration_x_rate_snapshot",
  rate_snapshot: {
    rate_per_hour: "0.220000",
    currency: "USD",
    effective_date: "2026-08-30",
    source: "elevenlabs_public_api_pricing",
  },
};

function retry(overrides: Partial<JobRetryState> = {}): JobRetryState {
  return {
    loading: false,
    posting: false,
    error: "",
    message: "",
    data: {
      job_id: "job-1",
      job_status: "failed",
      available: true,
      reason: "available",
      attempt_count: 1,
      max_attempts: 3,
      missing_output_count: 1,
      retry_safe_source_count: 1,
    },
    ...overrides,
  };
}

describe("JobDetailSection", () => {
  it("renders sorted sources and only safe resource links", () => {
    render(
      <JobDetailSection
        job={job}
        outputs={null}
        retry={undefined}
        onRetry={vi.fn()}
      />,
    );

    const detail = screen.getByLabelText("Подробности транскрибации");
    expect(detail).toHaveTextContent("Язык: Русский");
    expect(detail).toHaveTextContent("Разделение спикеров: Включено");
    expect(detail).toHaveTextContent(
      "Для этой задачи нет подтверждённых данных о расходе.",
    );
    const text = detail.textContent ?? "";
    expect(text.indexOf("1. first.ogg")).toBeLessThan(
      text.indexOf("2. second.ogg"),
    );
    expect(
      within(detail).getByRole("link", {
        name: "Открыть папку результата в новой вкладке",
      }),
    ).toHaveAttribute("href", "https://drive.example/folder/safe");
    expect(
      within(detail).getByRole("link", {
        name: "Открыть файл в Google Drive в новой вкладке",
      }),
    ).toHaveAttribute("href", "https://drive.example/file/safe");
    expect(detail).not.toHaveTextContent("https://evil.example/file/token");
  });

  it("shows confirmed nominal job cost separately from account actuals", () => {
    render(
      <JobDetailSection
        job={{ ...job, usage_cost: completeUsage }}
        outputs={null}
        retry={undefined}
        onRetry={vi.fn()}
      />,
    );

    const usage = screen.getByLabelText("Расход сервиса распознавания по задаче");
    expect(usage).toHaveTextContent("Подтверждённая длительность: 12,612 с");
    expect(usage).toHaveTextContent("Номинальная стоимость: 0,00077073 USD");
    expect(within(usage).getByText("менее 0,01 USD")).toBeVisible();
    expect(usage).toHaveTextContent("а не фактическое списание");
    expect(usage).toHaveTextContent("Настройки → Подключения");
    expect(usage).toHaveTextContent("Тариф: 0,22 USD/ч");
    expect(usage).toHaveTextContent("официальные публичные тарифы ElevenLabs");
  });

  it("does not present an uncertain provider outcome as an exact total", () => {
    render(
      <JobDetailSection
        job={{
          ...job,
          usage_cost: { ...completeUsage, accounting_status: "uncertain" },
        }}
        outputs={null}
        retry={undefined}
        onRetry={vi.fn()}
      />,
    );

    const usage = screen.getByLabelText("Расход сервиса распознавания по задаче");
    expect(usage).toHaveTextContent("Показана только подтверждённая часть");
    expect(usage).toHaveTextContent("Итоговый расход неопределён");
    expect(usage).toHaveTextContent("0,00077073 USD");
  });

  it("shows a distinct state before provider usage is confirmed", () => {
    render(
      <JobDetailSection
        job={{
          ...job,
          usage_cost: {
            accounting_status: "not_started",
            confirmed_billed_duration_seconds: null,
            confirmed_provider_cost: null,
            currency: null,
            cost_basis: null,
            rate_snapshot: null,
          },
        }}
        outputs={null}
        retry={undefined}
        onRetry={vi.fn()}
      />,
    );

    expect(
      screen.getByText("Подтверждённый расход пока не зафиксирован."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/0,00 USD/)).not.toBeInTheDocument();
  });

  it("runs an available safe retry for the current job", async () => {
    const onRetry = vi.fn();
    render(
      <JobDetailSection
        job={job}
        outputs={null}
        retry={retry()}
        onRetry={onRetry}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Повторить безопасную обработку" }),
    );

    expect(onRetry).toHaveBeenCalledOnce();
    expect(onRetry).toHaveBeenCalledWith("job-1");
  });

  it("explains an ordinary safe provider rejection before retry", () => {
    render(
      <JobDetailSection
        job={job}
        outputs={null}
        retry={retry({
          data: {
            ...retry().data!,
            provider_failure_code: "provider_scope_rejected",
          },
        })}
        onRetry={vi.fn()}
      />,
    );

    const action = screen.getByRole("region", {
      name: "Действия после ошибки",
    });
    expect(action).toHaveTextContent(
      "ElevenLabs запретил Speech to Text для этого ключа, тарифа или IP",
    );
    expect(action).toHaveTextContent("повтор будет безопасным");
  });

  it("disables an available retry while its request is pending", async () => {
    const onRetry = vi.fn();
    render(
      <JobDetailSection
        job={job}
        outputs={null}
        retry={retry({ posting: true })}
        onRetry={onRetry}
      />,
    );

    const button = screen.getByRole("button", {
      name: "Повторить безопасную обработку",
    });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    await userEvent.click(button);
    expect(onRetry).not.toHaveBeenCalled();
  });
  it("offers cached assembly without a paid restart", async () => {
    const onRetry = vi.fn();
    render(<JobDetailSection job={job} outputs={null} retry={retry({ data: {
      ...retry().data!, reason: "full_provider_restore_available",
      resumable_provider_part_count: 3, provider_total_part_count: 3,
    } })} onRetry={onRetry} />);
    expect(screen.getByRole("region", { name: "Действия после ошибки" })).toHaveTextContent("без повторного вызова ElevenLabs");
    await userEvent.click(screen.getByRole("button", { name: "Собрать и сохранить результат" }));
    expect(onRetry).toHaveBeenCalledWith(job.id);
    expect(screen.queryByRole("button", { name: "Начать транскрибацию заново" })).not.toBeInTheDocument();
  });

  it("explains partial provider progress and resumes only remaining parts", async () => {
    const onRetry = vi.fn();
    render(
      <JobDetailSection
        job={job}
        outputs={null}
        retry={retry({
          data: {
            ...retry().data!,
            reason: "partial_provider_resume_available",
            resumable_provider_part_count: 1,
            provider_total_part_count: 2,
            provider_failure_code: "provider_rate_limited",
          },
        })}
        onRetry={onRetry}
      />,
    );

    const action = screen.getByRole("region", {
      name: "Действия после ошибки",
    });
    expect(action).toHaveTextContent("Сохранено частей: 1 из 2");
    expect(action).toHaveTextContent("ElevenLabs ограничил частоту запросов");
    expect(action).toHaveTextContent("не будут повторно отправлены");
    await userEvent.click(
      within(action).getByRole("button", {
        name: "Продолжить оставшиеся части",
      }),
    );
    expect(onRetry).toHaveBeenCalledWith("job-1");
  });

  it("distinguishes an expired-checkpoint full provider restart", () => {
    render(
      <JobDetailSection
        job={job}
        outputs={null}
        retry={retry({
          data: {
            ...retry().data!,
            reason: "partial_provider_restart_available",
            provider_total_part_count: 2,
            provider_failure_code: "provider_request_rejected",
          },
        })}
        onRetry={vi.fn()}
      />,
    );

    const action = screen.getByRole("region", {
      name: "Действия после ошибки",
    });
    expect(action).toHaveTextContent("весь файл");
    expect(action).toHaveTextContent("повторно списать средства");
    expect(action).toHaveTextContent("ElevenLabs отклонил эту часть файла");
    expect(
      within(action).getByRole("button", {
        name: "Начать транскрибацию заново",
      }),
    ).toBeInTheDocument();
  });

  it("shows unavailable, pending, message, and error retry states", () => {
    const unavailable = retry({
      posting: true,
      message: "Повтор запущен",
      error: "Повтор не выполнен",
      data: {
        ...retry().data!,
        available: false,
        reason: "attempt_limit_reached",
      },
    });
    render(
      <JobDetailSection
        job={job}
        outputs={null}
        retry={unavailable}
        onRetry={vi.fn()}
      />,
    );

    const action = screen.getByRole("region", {
      name: "Действия после ошибки",
    });
    expect(action).toHaveTextContent("Достигнут предел попыток");
    expect(action).toHaveTextContent("Повтор запущен");
    expect(action).toHaveTextContent("Повтор не выполнен");
    expect(within(action).queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders the missing output folder state", () => {
    render(
      <JobDetailSection
        job={{ ...job, status: "completed", output_folder: null }}
        outputs={null}
        retry={undefined}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByText("Папка результата не задана.")).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Действия после ошибки" }),
    ).not.toBeInTheDocument();
  });

  it("derives file processing status from persisted outputs instead of the relation queue flag", () => {
    const outputData: JobOutputsResponse = {
      job_id: job.id,
      job_status: "failed",
      output_count: 1,
      outputs: [
        {
          source_id: "first",
          source_position: 0,
          source_name: "first.ogg",
          source_type: "local_upload",
          output_kind: "google_docs_transcript",
          transcript_standard: "transcript_doc",
          web_view_url: null,
          link_available: false,
          document_character_count: 42,
          document_created_at: "2026-07-22T10:00:00Z",
          persisted_at: "2026-07-22T10:01:00Z",
        },
      ],
    };

    render(
      <JobDetailSection
        job={job}
        outputs={outputData}
        retry={undefined}
        onRetry={vi.fn()}
      />,
    );

    const detail = screen.getByLabelText("Подробности транскрибации");
    expect(
      within(detail).getByText("Статус обработки: Завершена"),
    ).toBeInTheDocument();
    expect(
      within(detail).getByText("Статус обработки: Ошибка"),
    ).toBeInTheDocument();
    expect(detail).not.toHaveTextContent("Статус файла: queued");
  });
});
