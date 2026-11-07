import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { api } from "./apiClient";
import type { LocalExecutionDevice } from "./localExecutionContracts";
import { LocalModelCatalog } from "./LocalModelCatalog";

vi.mock("./apiClient", () => ({ api: vi.fn(), mutateWithCsrfRetry: vi.fn() }));

const device: LocalExecutionDevice = {
  id: "test-device", label: "Тестовый ПК", credential_revision: 1, online: true, ready: false,
  runtime_status: "unknown", runtime_version: null, model: null, last_seen_at: null, revoked_at: null,
};

it.each([false, true])("labels an installation according to complete file evidence (%s)", async (verified) => {
  const model = "synthetic";
  vi.mocked(api).mockImplementation(async (path) => path.endsWith("/inventory") ? {
    inventory: {
      cpu: "Synthetic CPU", cpu_threads: 8, ram_bytes: null, disk_free_bytes: null, gpus: [],
      execution: ["cpu"], installed: [model], verified_installations: verified ? [model] : undefined,
      probes: [{ model, audio_seconds: 2, elapsed_seconds: 1 }],
    },
  } : {
    items: [{
      id: model, source_url: "https://huggingface.co/test/synthetic", hub_revision: null, access: "gated",
      license: null, languages: [], downloads: null, likes: null,
      studio: { name: "Synthetic model", model, revision: "a".repeat(40), languages: [],
        diarization: true, word_timestamps: true, download_bytes: 100, platform: "Windows x64",
        execution: "CPU", min_ram_bytes: null, max_audio_seconds: 1440,
        weights_url: "https://huggingface.co/test/weights/tree/" + "a".repeat(40) },
    }],
    next_cursor: null,
  });
  render(<LocalModelCatalog devices={[device]} csrf="synthetic" onCsrf={vi.fn()} />);
  fireEvent.click(screen.getByText("Каталог локальных речевых моделей"));
  fireEvent.change(screen.getByLabelText("Компьютер для подбора"), { target: { value: device.id } });
  fireEvent.click(screen.getByRole("button", { name: "Найти модели" }));

  if (verified) {
    expect(await screen.findByText(/файлы проверены/)).toBeInTheDocument();
    expect(screen.getByText(/Проба с холодным запуском/)).toBeInTheDocument();
  } else {
    expect(await screen.findByText(/файлы обнаружены, проверка не подтверждена/)).toBeInTheDocument();
    expect(screen.queryByText(/Проба с холодным запуском/)).not.toBeInTheDocument();
  }
  expect(screen.getByText(/Доступ на Hugging Face: по запросу/)).toBeInTheDocument();
  expect(screen.getByText(/RAM нет данных · предел записи 24 мин/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Файлы закреплённой ревизии/ })).toHaveAttribute(
    "href", "https://huggingface.co/test/weights/tree/" + "a".repeat(40),
  );
});

it("keeps the cursor bound to the applied search until the draft is submitted", async () => {
  const request = vi.mocked(api);
  request.mockReset();
  request.mockResolvedValue({ items: [], next_cursor: "opaque=" });
  render(<LocalModelCatalog devices={[]} csrf="synthetic" onCsrf={vi.fn()} />);
  fireEvent.click(screen.getByText("Каталог локальных речевых моделей"));
  const search = screen.getByLabelText("Название модели");
  fireEvent.change(search, { target: { value: "first" } });
  fireEvent.click(screen.getByRole("button", { name: "Найти модели" }));
  const next = await screen.findByRole("button", { name: "Показать ещё модели" });
  expect(next).toBeEnabled();

  fireEvent.change(search, { target: { value: "second" } });
  expect(next).toBeDisabled();
  expect(screen.getByText(/Показаны результаты предыдущего поиска/)).toBeInTheDocument();
  fireEvent.click(next);
  expect(request).toHaveBeenCalledTimes(1);

  fireEvent.click(screen.getByRole("button", { name: "Найти модели" }));
  await screen.findByText(/На этой странице нет моделей/);
  fireEvent.click(screen.getByRole("button", { name: "Показать ещё модели" }));
  const urls = request.mock.calls.map(([path]) => new URL(path, "https://studio.example.test").searchParams);
  expect(urls.map(query => [query.get("search"), query.get("cursor")])).toEqual([
    ["first", null], ["second", null], ["second", "opaque="],
  ]);
});
