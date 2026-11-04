import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import type { RealtimeSegmentMetadata } from "./realtimeTranscript";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type MockCallbacks = {
  onStatus: (value: string) => void;
  onInputLevel: (value: number) => void;
  onSourceLevel: (kind: "display" | "microphone", value: number) => void;
  onPartial: (value: string) => void;
  onCommitted: (value: string, metadata?: RealtimeSegmentMetadata) => void;
};

const controllerState = vi.hoisted(() => ({
  instances: [] as Array<{
    active: boolean;
    callbacks: MockCallbacks;
    dependencies: { requestCapability: () => Promise<unknown> };
    start: ReturnType<typeof vi.fn>;
    stop: ReturnType<typeof vi.fn>;
    dispose: ReturnType<typeof vi.fn>;
    clearTranscript: ReturnType<typeof vi.fn>;
  }>,
}));

vi.mock("./realtimeSession", () => ({
  RealtimeSessionController: class {
    active = false;
    callbacks: MockCallbacks;
    dependencies: { requestCapability: () => Promise<unknown> };
    start = vi.fn(async () => {
      this.active = true;
      this.callbacks.onStatus("requesting_permission");
      await this.dependencies.requestCapability();
      this.callbacks.onStatus("connected");
      this.callbacks.onInputLevel(0.42);
    });
    stop = vi.fn(() => {
      this.active = false;
      this.callbacks.onStatus("stopped");
    });
    dispose = vi.fn();
    clearTranscript = vi.fn();
    constructor(
      callbacks: MockCallbacks,
      dependencies: { requestCapability: () => Promise<unknown> },
    ) {
      this.callbacks = callbacks;
      this.dependencies = dependencies;
      controllerState.instances.push(this);
    }
  },
}));

import { LiveTranscriptionPanel as ProductionLiveTranscriptionPanel } from "./LiveTranscriptionPanel";
import * as realtimeDrafts from "./realtimeDrafts";

function LiveTranscriptionPanel(
  props: Omit<ComponentProps<typeof ProductionLiveTranscriptionPanel>, "ownerUserId">,
) {
  return <ProductionLiveTranscriptionPanel ownerUserId="owner-safe" {...props} />;
}

const response = (body: unknown, ok = true, status = 200) =>
  Promise.resolve({
    ok,
    status,
    json: () => Promise.resolve(body),
    clone: () => ({ json: () => Promise.resolve(body) }),
  } as Response);

async function confirmStoppedClear() {
  await userEvent.click(screen.getByRole("button", { name: "Очистить" }));
  await userEvent.click(within(screen.getByRole("dialog",{name:"Очистить текст Live-сессии?"})).getByRole("button",{name:"Очистить",exact:true}));
}

describe("LiveTranscriptionPanel", () => {
  it("uses one three-action dialog to clear an active capture, continue and stop without another paid start", async () => {
    const confirm = vi.spyOn(window,"confirm").mockReturnValue(true);
    confirm.mockClear();
    render(<LiveTranscriptionPanel projectId="project-safe" csrf="csrf" onCsrf={vi.fn()} active />);
    const start = await screen.findByRole("button",{name:"Начать"});
    await waitFor(() => expect(start).toBeEnabled());
    await userEvent.click(start);
    const controller = controllerState.instances[0];
    act(() => controller.callbacks.onCommitted("до очистки"));
    const clear = screen.getByRole("button",{name:"Очистить",exact:true});
    expect(clear).toBeEnabled();
    await userEvent.click(clear);
    const dialog = screen.getByRole("dialog",{name:"Очистить текст Live-сессии?"});
    expect(within(dialog).getAllByRole("button")).toHaveLength(3);
    expect(within(dialog).getByRole("button",{name:"Отмена"})).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(clear).toHaveFocus();
    expect(controller.clearTranscript).not.toHaveBeenCalled();
    await userEvent.click(clear);
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button",{name:"Очистить и продолжить"}));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(controller.clearTranscript).toHaveBeenCalledOnce();
    expect(controller.stop).not.toHaveBeenCalled();
    expect(controller.start).toHaveBeenCalledOnce();
    expect(screen.queryByText("до очистки")).not.toBeInTheDocument();
    expect(screen.getByRole("button",{name:"Остановить",exact:true})).toHaveFocus();
    act(() => controller.callbacks.onCommitted("после очистки"));
    await waitFor(() => {
      const writes = vi.mocked(fetch).mock.calls.filter(([url,init]) => String(url).includes("/realtime/drafts/") && init?.method === "PUT");
      expect(new Set(writes.map(([url]) => String(url).split("/").at(-1))).size).toBe(2);
    });
    await userEvent.click(screen.getByRole("button",{name:"Очистить",exact:true}));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button",{name:"Остановить и очистить"}));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(controller.stop).toHaveBeenCalledOnce();
    expect(controller.dispose).toHaveBeenCalledOnce();
    expect(start).toHaveFocus();
    act(() => controller.callbacks.onCommitted("поздний текст остановленной записи"));
    expect(screen.queryByText("поздний текст остановленной записи")).not.toBeInTheDocument();
    expect(confirm).not.toHaveBeenCalled();
    expect(controllerState.instances).toHaveLength(1);
  });
  it("does not announce readiness when no audio source is selected", async () => {
    render(<LiveTranscriptionPanel projectId="project" csrf="csrf" onCsrf={vi.fn()} active />);
    await waitFor(() => expect(screen.getByRole("button",{name:"Начать",exact:true})).toBeEnabled());
    await userEvent.click(screen.getByLabelText("Звук вкладки или экрана"));
    expect(screen.getByRole("button",{name:"Начать",exact:true})).toBeDisabled();
    expect(screen.getByText("Выберите источник звука")).toBeInTheDocument();
    expect(screen.queryByText("Готово к запуску")).not.toBeInTheDocument();
  });

  beforeEach(() => {
    controllerState.instances.length = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith("/api/stt/providers?include_local=true")) {
          return response({
            providers: [
              {
                provider: "elevenlabs",
                display_name: "ElevenLabs",
                byok_enabled: true,
                modes: [
                  {
                    mode: "realtime",
                    model: "scribe_v2_realtime",
                    transport: "websocket",
                    languages: ["ru", "en", "detect"],
                    diarization: false,
                    dictionaries: false,
                    file_constraints: {
                      max_bytes: null,
                      max_duration_seconds: 1800,
                      audio_channels: [1],
                    },
                    health: {
                      available: true,
                      consecutive_failures: 0,
                      retry_after_seconds: null,
                    },
                  },
                ],
              },
              {
                provider: "yandex",
                display_name: "Yandex SpeechKit",
                byok_enabled: false,
                modes: [
                  {
                    mode: "realtime",
                    model: "general",
                    transport: "grpc_relay",
                    languages: ["ru", "en", "detect"],
                    diarization: true,
                    dictionaries: false,
                    file_constraints: {
                      max_bytes: 10485760,
                      max_duration_seconds: 300,
                      audio_channels: [1],
                    },
                    health: {
                      available: true,
                      consecutive_failures: 0,
                      retry_after_seconds: null,
                    },
                  },
                ],
              },
            ],
          });
        }
        if (url.endsWith("/api/credentials")) {
          return response({
            credentials: [
              {
                id: "credential-safe",
                provider: "elevenlabs",
                label: "Realtime",
                status: "active",
                active_version: 4,
                masked_value: "••••safe",
              },
            ],
          });
        }
        if (url.endsWith("/realtime/drafts/latest") && !init?.method) {
          return response({ draft: null });
        }
        if (url.includes("/realtime/drafts/") && init?.method === "PUT") {
          const body = JSON.parse(String(init.body));
          return response({
            draft: {
              client_session_id: String(url).split("/").at(-1),
              revision: body.revision,
              updated_at: "2026-08-22T12:00:00Z",
              expires_at: "2026-08-25T12:00:00Z",
            },
          });
        }
        if (url.includes("/realtime/drafts/") && init?.method === "DELETE") {
          return response({ ok: true, deleted: true });
        }
        if (
          url.endsWith("/api/projects/project-safe/realtime/capability") &&
          init?.method === "POST"
        ) {
          return response({
            websocket_url:
              "wss://api.elevenlabs.io/v1/speech-to-text/realtime?model_id=scribe_v2_realtime&token=sutkn_browser_secret&audio_format=pcm_16000&commit_strategy=vad&language_code=ru",
            expires_in_seconds: 900,
            model_id: "scribe_v2_realtime",
            audio_format: "pcm_16000",
            commit_strategy: "vad",
          });
        }
        return response({ ok: true });
      }),
    );
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        enumerateDevices: vi.fn().mockResolvedValue([]),
        getUserMedia: vi.fn(),
        getDisplayMedia: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      },
    });
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn().mockReturnValue("blob:live-transcript"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
  });

  afterEach(() => cleanup());

  it("prioritizes tab or system audio and keeps microphone opt-in", async () => {
    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        active
      />,
    );

    expect(await screen.findByText("Realtime · v4")).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "Звук вкладки или экрана" }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Микрофон или аудиовход" }),
    ).not.toBeChecked();
    expect(screen.queryByLabelText("Устройство ввода")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Начать" })).toBeEnabled();
  });

  it("keeps external secrets out of inactive panels and preserves deliberate endpoint input", async () => {
    const props = { projectId: "project-safe", csrf: "csrf-safe", onCsrf: vi.fn() };
    const { rerender, container } = render(<LiveTranscriptionPanel {...props} active={false} />);
    expect(container.querySelector('input[type="password"]')).toBeNull();

    rerender(<LiveTranscriptionPanel {...props} active />);
    await userEvent.click(screen.getByText("Субтитры и внешние получатели"));
    const endpoint = await screen.findByLabelText(/YouTube Live closed-caption ingestion URL/);
    await userEvent.type(endpoint, "https://example.test/synthetic-caption");
    await userEvent.click(screen.getByText("Субтитры и внешние получатели"));
    await waitFor(() => expect(container.querySelector('input[type="password"]')).toBeNull());
    await userEvent.click(screen.getByText("Субтитры и внешние получатели"));
    expect(await screen.findByLabelText(/YouTube Live closed-caption ingestion URL/)).toHaveValue("https://example.test/synthetic-caption");

    rerender(<LiveTranscriptionPanel {...props} active={false} />);
    expect(container.querySelector('input[type="password"]')).toBeNull();
    rerender(<LiveTranscriptionPanel {...props} active />);
    expect(await screen.findByLabelText(/YouTube Live closed-caption ingestion URL/)).toHaveValue("https://example.test/synthetic-caption");
    for (const controller of controllerState.instances) expect(controller.start).not.toHaveBeenCalled();
  });

  it("uses provider capability metadata to hide disabled Live BYOK choices", async () => {
    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        active
      />,
    );

    expect(
      await screen.findByRole("option", {
        name: "Yandex SpeechKit — не включён",
      }),
    ).toBeDisabled();
    expect(
      screen.getByRole("option", { name: "ElevenLabs" }),
    ).toBeEnabled();
  });

  it("blocks Live start while the selected provider circuit is open", async () => {
    const defaultFetch = vi.mocked(fetch).getMockImplementation();
    vi.mocked(fetch).mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/stt/providers?include_local=true")) {
        return response({
          providers: [
            {
              provider: "elevenlabs",
              display_name: "ElevenLabs",
              byok_enabled: true,
              modes: [
                {
                  mode: "realtime",
                  model: "scribe_v2_realtime",
                  transport: "websocket",
                  languages: ["ru", "en", "detect"],
                  diarization: false,
                  dictionaries: false,
                  file_constraints: {
                    max_bytes: null,
                    max_duration_seconds: 1800,
                    audio_channels: [1],
                  },
                  health: {
                    available: false,
                    consecutive_failures: 3,
                    retry_after_seconds: 300,
                  },
                },
              ],
            },
          ],
        });
      }
      return defaultFetch?.(url, init) as Promise<Response>;
    });

    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        active
      />,
    );

    expect(
      await screen.findByText(
        "ElevenLabs временно недоступен в Live-режиме",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Начать" })).toBeDisabled();
  });

  it("shows isolated source levels and explains automatic ducking", async () => {
    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        active
      />,
    );

    await userEvent.click(
      screen.getByRole("checkbox", { name: "Микрофон или аудиовход" }),
    );

    expect(
      screen.getByText(/Studio показывает уровни каждого источника/),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Уровни источников смешанного аудио"),
    ).toBeInTheDocument();

    const start = screen.getByRole("button", { name: "Начать" });
    await waitFor(() => expect(start).toBeEnabled());
    await userEvent.click(start);
    act(() => {
      controllerState.instances[0].callbacks.onSourceLevel("display", 0.64);
      controllerState.instances[0].callbacks.onSourceLevel("microphone", 0.18);
    });

    expect(screen.getByText("Звук вкладки · 64%")).toBeInTheDocument();
    expect(screen.getByText("Микрофон · 18%")).toBeInTheDocument();
    expect(screen.getByLabelText("Уровень звука вкладки")).toHaveAttribute(
      "value",
      "64",
    );
    expect(screen.getByLabelText("Уровень микрофона")).toHaveAttribute(
      "value",
      "18",
    );
  });

  it("requests a project-scoped one-use capability without rendering it", async () => {
    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        active
      />,
    );
    const start = await screen.findByRole("button", { name: "Начать" });
    await waitFor(() => expect(start).toBeEnabled());
    await userEvent.selectOptions(screen.getByLabelText("Язык"), "en");
    await userEvent.click(start);

    await screen.findByText("Соединение установлено");
    expect(screen.getByText("Сигнал есть · 42%")).toBeInTheDocument();
    expect(screen.getByLabelText("Статистика live-сессии")).toHaveTextContent(
      "Сессия: 00:00 · Фрагментов: 0 · Символов: 0",
    );
    const capabilityCall = vi.mocked(fetch).mock.calls.find(
      ([url]) =>
        String(url).endsWith(
          "/api/projects/project-safe/realtime/capability",
        ),
    );
    expect(capabilityCall).toBeDefined();
    expect(capabilityCall?.[1]).toMatchObject({
      method: "POST",
      credentials: "same-origin",
      headers: expect.objectContaining({ "x-csrf-token": "csrf-safe" }),
    });
    expect(JSON.parse(String(capabilityCall?.[1]?.body))).toEqual({
      provider: "elevenlabs",
      provider_credential_id: "credential-safe",
      language: "en",
    });
    expect(document.body.textContent).not.toContain("sutkn_browser_secret");
    expect(document.body.textContent).not.toContain("websocket_url");
    await waitFor(() =>
      expect(navigator.mediaDevices.enumerateDevices).toHaveBeenCalledOnce(),
    );

    await userEvent.click(screen.getByRole("button", { name: "Остановить" }));
    expect(controllerState.instances[0].stop).toHaveBeenCalledOnce();
    expect(screen.getByText("Остановлено")).toBeInTheDocument();
  });

  it("keeps long live output observable with stats and opt-out follow", async () => {
    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        active
      />,
    );
    const start = await screen.findByRole("button", { name: "Начать" });
    await waitFor(() => expect(start).toBeEnabled());
    await userEvent.click(start);

    const committed = screen.getByLabelText("Подтверждённая транскрипция");
    Object.defineProperty(committed, "scrollHeight", {
      configurable: true,
      value: 480,
    });
    act(() => {
      controllerState.instances[0].callbacks.onCommitted("Готовый фрагмент");
    });

    expect(await screen.findByText("Готовый фрагмент")).toBeInTheDocument();
    expect(screen.getByLabelText("Статистика live-сессии")).toHaveTextContent(
      "Фрагментов: 1 · Символов: 16",
    );
    await waitFor(() => expect(committed.scrollTop).toBe(480));

    const follow = screen.getByRole("button", {
      name: "Автопрокрутка: вкл",
    });
    await userEvent.click(follow);
    expect(
      screen.getByRole("button", { name: "Автопрокрутка: выкл" }),
    ).toHaveAttribute("aria-pressed", "false");
  });

  it("confirms copy and downloads a timestamped browser-only transcript", async () => {
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        active
      />,
    );
    const start = await screen.findByRole("button", { name: "Начать" });
    await waitFor(() => expect(start).toBeEnabled());
    await userEvent.click(start);
    act(() => {
      controllerState.instances[0].callbacks.onCommitted("Итоговый текст");
    });

    await userEvent.click(screen.getByRole("button", { name: "Копировать" }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("Итоговый текст");
    expect(
      await screen.findByText("Текст скопирован в буфер обмена."),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Скачать .txt" }));
    expect(URL.createObjectURL).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    const anchor = click.mock.instances[0];
    expect(anchor.download).toMatch(
      /^studio-live-transcript-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}Z\.txt$/,
    );
    expect(anchor.href).toBe("blob:live-transcript");
    expect(await screen.findByText("Текст сохранён в файл .txt.")).toBeInTheDocument();
    await waitFor(() =>
      expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:live-transcript"),
    );
  });

  it("starts independent captures and opens prior timed sessions without another paid capture", async () => {
    const stored = new Map<string, {client_session_id:string;revision:number;updated_at:string;expires_at:null;committed_segments:string[];partial:string;segment_metadata?:unknown[]}>();
    const fetchMock = vi.mocked(fetch);
    const defaultFetch = fetchMock.getMockImplementation();
    fetchMock.mockImplementation((url, init) => {
      const path = String(url);
      if (path.includes("/realtime/drafts/") && init?.method === "PUT") {
        const id = path.split("/").at(-1)!;
        const saved = { ...JSON.parse(String(init.body)), client_session_id:id,
          updated_at:stored.get(id)?.updated_at ?? `2026-08-22T12:00:0${stored.size}Z`, expires_at:null };
        stored.set(id, saved);
        return response({draft:{client_session_id:id,revision:saved.revision,updated_at:saved.updated_at,expires_at:null}});
      }
      if (path.includes("/realtime/drafts?page_size=")) return response({sessions:[...stored.values()].map(row => ({
        client_session_id:row.client_session_id,revision:row.revision,updated_at:row.updated_at,
        committed_segment_count:row.committed_segments.length,committed_character_count:row.committed_segments.join("").length,partial_character_count:row.partial.length,
      })),next_cursor:null,page_size:50});
      if (path.includes("/realtime/drafts/") && !path.endsWith("/latest") && !init?.method) {
        return response({draft:stored.get(path.split("/").at(-1)!) ?? null,cleared:false});
      }
      return defaultFetch?.(url, init) ?? response({ok:true});
    });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    click.mockClear();
    render(<LiveTranscriptionPanel projectId="project-safe" csrf="csrf-safe" onCsrf={vi.fn()} active />);
    const start = await screen.findByRole("button", { name: "Начать" });
    await waitFor(() => expect(start).toBeEnabled());
    await userEvent.click(start);
    act(() => controllerState.instances[0].callbacks.onCommitted("первая сессия", {
      id:"first.0", session_id:"capture_first_123456", start_seconds:10, end_seconds:12,
    }));
    await userEvent.click(screen.getByRole("button", {name:"Остановить"}));
    await userEvent.click(start);
    await waitFor(() => expect(controllerState.instances).toHaveLength(2));
    expect(screen.queryByText("первая сессия")).not.toBeInTheDocument();
    expect(screen.getByRole("button",{name:"Скачать .txt"})).toBeDisabled();
    act(() => {
      controllerState.instances[0].callbacks.onCommitted("поздняя старая реплика");
      controllerState.instances[1].callbacks.onCommitted("вторая сессия", {
        id:"second.0",session_id:"capture_second_123456",start_seconds:1,end_seconds:2,
      });
    });
    expect(screen.queryByText("поздняя старая реплика")).not.toBeInTheDocument();
    expect(screen.getByText("вторая сессия")).toBeInTheDocument();
    expect(screen.getByRole("option",{name:"SRT"})).toBeEnabled();
    await userEvent.selectOptions(screen.getByLabelText("Формат скачивания Live"), "srt");
    await userEvent.click(screen.getByRole("button",{name:"Скачать .srt"}));
    expect(click).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole("button",{name:"Остановить"}));
    await userEvent.click(screen.getByText("Сохранённые Live-сессии"));
    const buttons = await screen.findAllByRole("button",{name:"Открыть сессию"});
    expect(buttons).toHaveLength(2);
    await userEvent.click(buttons.at(-1)!);
    expect(await screen.findByText("первая сессия")).toBeInTheDocument();
    expect(screen.queryByText("вторая сессия")).not.toBeInTheDocument();
    expect(controllerState.instances).toHaveLength(2);
    expect(controllerState.instances[1].start).toHaveBeenCalledOnce();
  });

  it("replaces indexed corrections, preserves the next partial and gates timed downloads", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    click.mockClear();
    render(<LiveTranscriptionPanel projectId="project-safe" csrf="csrf-safe" onCsrf={vi.fn()} active />);
    const start = await screen.findByRole("button", { name: "Начать" });
    await waitFor(() => expect(start).toBeEnabled());
    await userEvent.click(start);
    const callbacks = controllerState.instances[0].callbacks;
    act(() => callbacks.onCommitted("сырой текст", { id: "session.1.index.0" }));
    expect(screen.getByRole("option", { name: "SRT" })).toBeDisabled();
    act(() => {
      callbacks.onPartial("следующая реплика");
      callbacks.onCommitted("Исправленный текст.", { id: "session.1.index.0", start_seconds: 1, end_seconds: 2 });
    });
    expect(screen.queryByText("сырой текст")).not.toBeInTheDocument();
    expect(screen.getByText("Исправленный текст.")).toBeInTheDocument();
    expect(screen.getByText("следующая реплика")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "SRT" })).toBeDisabled();
    act(() => callbacks.onCommitted("следующая реплика", { id: "session.1.index.1", start_seconds: 2, end_seconds: 3 }));
    expect(screen.getByRole("option", { name: "SRT" })).toBeEnabled();
    await userEvent.selectOptions(screen.getByLabelText("Формат скачивания Live"), "docx");
    await userEvent.click(screen.getByRole("button", { name: "Скачать .docx" }));
    expect(click).toHaveBeenCalledOnce();
    expect(click.mock.instances[0].download).toMatch(/\.docx$/);
    expect(controllerState.instances[0].start).toHaveBeenCalledOnce();
  });

  it("stops hidden capture and keeps the transcript mounted across mode switches", async () => {
    const props = {
      projectId: "project-safe",
      csrf: "csrf-safe",
      onCsrf: vi.fn(),
    };
    const { rerender } = render(
      <LiveTranscriptionPanel {...props} active />,
    );
    const start = await screen.findByRole("button", { name: "Начать" });
    await waitFor(() => expect(start).toBeEnabled());
    await userEvent.click(start);
    act(() => {
      controllerState.instances[0].callbacks.onCommitted("Сохранённый текст");
    });

    rerender(<LiveTranscriptionPanel {...props} active={false} />);

    expect(controllerState.instances[0].stop).toHaveBeenCalledOnce();
    expect(screen.getByText("Сохранённый текст")).toBeInTheDocument();
    expect(
      screen.getByText(/Live-сессия остановлена при переходе/),
    ).toBeInTheDocument();

    rerender(<LiveTranscriptionPanel {...props} active />);
    expect(screen.getByText("Сохранённый текст")).toBeInTheDocument();
  });

  it("warns before browser navigation while live text can be lost", async () => {
    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        active
      />,
    );
    const untouched = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(untouched);
    expect(untouched.defaultPrevented).toBe(false);

    const start = await screen.findByRole("button", { name: "Начать" });
    await waitFor(() => expect(start).toBeEnabled());
    await userEvent.click(start);
    const runningNavigation = new Event("beforeunload", {
      cancelable: true,
    });
    window.dispatchEvent(runningNavigation);
    expect(runningNavigation.defaultPrevented).toBe(true);
  });

  it("restores only committed text supplied from current React memory", async () => {
    const onSegmentsChange = vi.fn();
    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        active
        initialSegments={["Первый проектный фрагмент", "Второй фрагмент"]}
        onSegmentsChange={onSegmentsChange}
      />,
    );

    expect(await screen.findByText("Realtime · v4")).toBeInTheDocument();
    expect(screen.getByText("Первый проектный фрагмент")).toBeInTheDocument();
    expect(screen.getByText("Второй фрагмент")).toBeInTheDocument();
    expect(screen.getByLabelText("Статистика live-сессии")).toHaveTextContent(
      "Фрагментов: 2",
    );
    expect(onSegmentsChange).not.toHaveBeenCalled();
  });

  it("verifies a local recovery candidate before offering text cleared by another browser", async () => {
    const local = realtimeDrafts.makeRealtimeDraft({ownerUserId:"owner-safe", projectId:"project-safe",
      clientSessionId:"session_retired_123456", revision:4, committedSegments:["retired local text"],partial:""});
    const load = vi.spyOn(realtimeDrafts,"loadLocalRealtimeDraft").mockResolvedValue(local);
    const remove = vi.spyOn(realtimeDrafts,"deleteLocalRealtimeDraft").mockResolvedValue(undefined);
    const fallback = vi.mocked(fetch).getMockImplementation();
    let resolveRead: ((value:Response) => void) | undefined;
    vi.mocked(fetch).mockImplementation((url, init) => {
      if (String(url).endsWith(`/realtime/drafts/${local.client_session_id}`) && !init?.method) {
        return new Promise<Response>(resolve => { resolveRead=resolve; });
      }
      return fallback?.(url,init) ?? response({ok:true});
    });
    render(<LiveTranscriptionPanel projectId="project-safe" csrf="csrf" onCsrf={vi.fn()} active />);
    await waitFor(() => expect(resolveRead).toBeDefined());
    expect(screen.getByRole("button",{name:"Начать"})).toBeDisabled();
    expect(screen.queryByRole("button",{name:"Восстановить"})).not.toBeInTheDocument();
    await act(async () => { resolveRead?.(await response({draft:null,cleared:true})); });
    await waitFor(() => expect(screen.getByRole("button",{name:"Начать"})).toBeEnabled());
    expect(remove).toHaveBeenCalledWith("owner-safe","project-safe",local.client_session_id);
    expect(screen.queryByText("retired local text")).not.toBeInTheDocument();
    load.mockRestore(); remove.mockRestore();
  });

  it("offers an owner-scoped server draft after reload and restores partial as unconfirmed", async () => {
    const defaultFetch = vi.mocked(fetch).getMockImplementation();
    const updatedAt = new Date().toISOString();
    const expiresAt = new Date(Date.now() + 72 * 60 * 60 * 1000).toISOString();
    vi.mocked(fetch).mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/realtime/drafts/latest") && !init?.method) {
        return response({
          draft: {
            client_session_id: "session_recovery_123",
            revision: 7,
            committed_segments: ["Восстановленный фрагмент"],
            partial: "неподтверждённое продолжение",
            updated_at: updatedAt,
            expires_at: expiresAt,
          },
        });
      }
      return defaultFetch?.(url, init) as Promise<Response>;
    });
    const onSegmentsChange = vi.fn();

    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        onSegmentsChange={onSegmentsChange}
        active
      />,
    );

    expect(
      await screen.findByRole("region", { name: "Восстановление Live-черновика" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Начать" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Восстановить" }));
    expect(screen.getByText("Восстановленный фрагмент")).toBeInTheDocument();
    expect(screen.getByText("неподтверждённое продолжение")).toBeInTheDocument();
    expect(onSegmentsChange).toHaveBeenCalledWith(["Восстановленный фрагмент"]);
    expect(screen.getByRole("button", { name: "Начать" })).toBeEnabled();
    await waitFor(() =>
      expect(
        vi.mocked(fetch).mock.calls.some(
          ([url, init]) =>
            String(url).includes("/realtime/drafts/session_recovery_123") &&
            init?.method === "PUT" &&
            JSON.parse(String(init.body)).revision === 7,
        ),
      ).toBe(true),
    );
  });

  it("keeps Clear disabled until recovery lookup settles", async () => {
    const defaultFetch = vi.mocked(fetch).getMockImplementation();
    let resolveRecovery: ((value: Response) => void) | undefined;
    vi.mocked(fetch).mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/realtime/drafts/latest") && !init?.method) {
        return new Promise<Response>((resolve) => {
          resolveRecovery = resolve;
        });
      }
      return defaultFetch?.(url, init) as Promise<Response>;
    });

    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        initialSegments={["Retained text"]}
        active
      />,
    );

    expect(screen.getByRole("button", { name: "Очистить" })).toBeDisabled();
    await act(async () => resolveRecovery?.(await response({ draft: null })));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Очистить" })).toBeEnabled(),
    );
  });

  it("reconciles retained newer segments without restoring an older draft", async () => {
    const defaultFetch = vi.mocked(fetch).getMockImplementation();
    const putBodies: Array<{
      revision: number;
      committed_segments: string[];
    }> = [];
    vi.mocked(fetch).mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/realtime/drafts/latest") && !init?.method) {
        return response({
          draft: {
            client_session_id: "session_older_recovery",
            revision: 8,
            committed_segments: ["Старый checkpoint"],
            partial: "",
            updated_at: new Date().toISOString(),
            expires_at: new Date(
              Date.now() + 72 * 60 * 60 * 1000,
            ).toISOString(),
          },
        });
      }
      if (url.includes("/realtime/drafts/") && init?.method === "PUT") {
        const body = JSON.parse(String(init.body)) as {
          revision: number;
          committed_segments: string[];
        };
        putBodies.push(body);
        return response({
          draft: {
            client_session_id: "session_older_recovery",
            revision: body.revision,
          },
        });
      }
      return defaultFetch?.(url, init) as Promise<Response>;
    });
    const retained = ["Старый checkpoint", "Новый фрагмент из памяти"];

    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        initialSegments={retained}
        active
      />,
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Восстановить" }),
    );

    expect(screen.getByText("Новый фрагмент из памяти")).toBeInTheDocument();
    await waitFor(() => expect(putBodies).toHaveLength(1));
    expect(putBodies[0]).toMatchObject({
      revision: 9,
      committed_segments: retained,
    });
    expect(
      screen.queryByRole("region", { name: "Восстановление Live-черновика" }),
    ).not.toBeInTheDocument();
  });

  it("blocks automatic restore when retained and recovered text diverge", async () => {
    const defaultFetch = vi.mocked(fetch).getMockImplementation();
    vi.mocked(fetch).mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/realtime/drafts/latest") && !init?.method) {
        return response({
          draft: {
            client_session_id: "session_divergent_recovery",
            revision: 5,
            committed_segments: ["Другой server text"],
            partial: "",
            updated_at: new Date().toISOString(),
            expires_at: new Date(
              Date.now() + 72 * 60 * 60 * 1000,
            ).toISOString(),
          },
        });
      }
      return defaultFetch?.(url, init) as Promise<Response>;
    });

    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        initialSegments={["Текст из памяти вкладки"]}
        active
      />,
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Восстановить" }),
    );

    expect(screen.getByText("Текст из памяти вкладки")).toBeInTheDocument();
    expect(screen.queryByText("Другой server text")).not.toBeInTheDocument();
    expect(
      screen.getByText(/автоматическая замена заблокирована/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Восстановление Live-черновика" }),
    ).toBeInTheDocument();
    expect(
      vi.mocked(fetch).mock.calls.some(
        ([url, init]) =>
          String(url).includes("/realtime/drafts/") && init?.method === "PUT",
      ),
    ).toBe(false);
  });

  it("degrades safely when the server recovery read stalls", async () => {
    const defaultFetch = vi.mocked(fetch).getMockImplementation();
    let recoverySignal: AbortSignal | undefined;
    vi.mocked(fetch).mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/realtime/drafts/latest") && !init?.method) {
        recoverySignal = init.signal;
        return new Promise<Response>((_resolve, reject) => {
          recoverySignal?.addEventListener("abort", () =>
            reject(new Error("raw-stalled-recovery")),
          );
        });
      }
      return defaultFetch?.(url, init) as Promise<Response>;
    });
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
      render(
        <LiveTranscriptionPanel
          projectId="project-safe"
          csrf="csrf-safe"
          onCsrf={vi.fn()}
          active
        />,
      );

      expect(
        await screen.findByText(/Восстановление из Studio сейчас недоступно/),
      ).toBeInTheDocument();
      expect(recoverySignal?.aborted).toBe(true);
      expect(screen.getByRole("button", { name: "Начать" })).toBeEnabled();
      expect(document.body.textContent).not.toContain("raw-stalled-recovery");
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("keeps a restored partial-only draft downloadable and removable", async () => {
    const defaultFetch = vi.mocked(fetch).getMockImplementation();
    vi.mocked(fetch).mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/realtime/drafts/latest") && !init?.method) {
        return response({
          draft: {
            client_session_id: "session_partial_only",
            revision: 3,
            committed_segments: [],
            partial: "только неподтверждённый текст",
            updated_at: new Date().toISOString(),
            expires_at: new Date(
              Date.now() + 72 * 60 * 60 * 1000,
            ).toISOString(),
          },
        });
      }
      return defaultFetch?.(url, init) as Promise<Response>;
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        active
      />,
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Восстановить" }),
    );

    expect(screen.getByText("только неподтверждённый текст")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Копировать" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Скачать .txt" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Очистить" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Копировать" }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "[Неподтверждённый фрагмент]\nтолько неподтверждённый текст",
    );

    await confirmStoppedClear();
    await waitFor(() =>
      expect(
        vi.mocked(fetch).mock.calls.some(
          ([url, init]) =>
            String(url).includes("/realtime/drafts/session_partial_only") &&
            init?.method === "DELETE",
        ),
      ).toBe(true),
    );
    expect(
      screen.getByText("Речь появится здесь до подтверждения фрагмента."),
    ).toBeInTheDocument();
  });

  it("clears visible text without deleting a different unresolved saved session", async () => {
    const defaultFetch = vi.mocked(fetch).getMockImplementation();
    vi.mocked(fetch).mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/realtime/drafts/latest") && !init?.method) {
        return response({
          draft: {
            client_session_id: "session_unresolved_clear",
            revision: 4,
            committed_segments: ["Retained server text"],
            partial: "",
            updated_at: new Date().toISOString(),
            expires_at: new Date(
              Date.now() + 72 * 60 * 60 * 1000,
            ).toISOString(),
          },
        });
      }
      return defaultFetch?.(url, init) as Promise<Response>;
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        initialSegments={["Retained React text"]}
        active
      />,
    );
    expect(
      await screen.findByRole("region", { name: "Восстановление Live-черновика" }),
    ).toBeInTheDocument();
    await confirmStoppedClear();

    expect(vi.mocked(fetch).mock.calls.some(([url, init]) =>
      String(url).includes("/realtime/drafts/session_unresolved_clear") && init?.method === "DELETE")).toBe(false);
    expect(
      screen.queryByRole("region", { name: "Восстановление Live-черновика" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("Подтверждённых фрагментов пока нет."),
    ).toBeInTheDocument();
  });

  it("makes deletion the final server mutation after queued checkpoints", async () => {
    const defaultFetch = vi.mocked(fetch).getMockImplementation();
    const order: string[] = [];
    let resolveFirstPut: ((value: Response) => void) | undefined;
    let firstPutSessionId = "";
    vi.mocked(fetch).mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes("/realtime/drafts/") && init?.method === "PUT") {
        const body = JSON.parse(String(init.body));
        order.push(`PUT:${body.revision}`);
        if (!resolveFirstPut) {
          firstPutSessionId = String(url).split("/").at(-1) ?? "";
          return new Promise<Response>((resolve) => {
            resolveFirstPut = resolve;
          });
        }
      }
      if (url.includes("/realtime/drafts/") && init?.method === "DELETE") {
        order.push("DELETE");
      }
      return defaultFetch?.(url, init) as Promise<Response>;
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        active
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Начать" }));
    act(() => {
      controllerState.instances[0].callbacks.onCommitted("Первый checkpoint");
      controllerState.instances[0].callbacks.onCommitted("Второй checkpoint");
    });
    await waitFor(() => expect(resolveFirstPut).toBeDefined());
    await userEvent.click(screen.getByRole("button", { name: "Остановить" }));
    await confirmStoppedClear();
    expect(order).toEqual(["PUT:1"]);

    await act(async () => {
      resolveFirstPut?.(
        await response({
          draft: {
            client_session_id: firstPutSessionId,
            revision: 1,
          },
        }),
      );
    });
    await waitFor(() => expect(order.at(-1)).toBe("DELETE"));
    expect(order.filter((item) => item.startsWith("PUT"))).toEqual(["PUT:1"]);
    expect(
      screen.getByText("Подтверждённых фрагментов пока нет."),
    ).toBeInTheDocument();
  });

  it("makes deletion the final local mutation after a pending checkpoint", async () => {
    const order: string[] = [];
    let resolveLocalSave: (() => void) | undefined;
    vi.spyOn(realtimeDrafts, "saveLocalRealtimeDraft").mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          order.push("LOCAL_SAVE");
          resolveLocalSave = resolve;
        }),
    );
    vi.spyOn(realtimeDrafts, "deleteLocalRealtimeDraft").mockImplementation(
      async () => {
        order.push("LOCAL_DELETE");
      },
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        active
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Начать" }));
    act(() => {
      controllerState.instances[0].callbacks.onCommitted("Local checkpoint");
    });
    await waitFor(() => expect(resolveLocalSave).toBeDefined());
    await userEvent.click(screen.getByRole("button", { name: "Остановить" }));
    await confirmStoppedClear();
    expect(order).toEqual(["LOCAL_SAVE"]);

    act(() => resolveLocalSave?.());
    await waitFor(() => expect(order).toEqual(["LOCAL_SAVE", "LOCAL_DELETE"]));
    expect(
      screen.getByText("Подтверждённых фрагментов пока нет."),
    ).toBeInTheDocument();
  });

  it("flushes the latest debounced partial before workspace unmount", async () => {
    const defaultFetch = vi.mocked(fetch).getMockImplementation();
    const oldProjectWrites: Array<{ partial: string }> = [];
    vi.mocked(fetch).mockImplementation((url: string, init?: RequestInit) => {
      if (
        url.includes("/api/projects/project-safe/realtime/drafts/") &&
        init?.method === "PUT"
      ) {
        const body = JSON.parse(String(init.body)) as { partial: string };
        oldProjectWrites.push(body);
        return response({
          draft: {
            client_session_id: String(url).split("/").at(-1),
            revision: 1,
          },
        });
      }
      return defaultFetch?.(url, init) as Promise<Response>;
    });
    const props = { csrf: "csrf-safe", onCsrf: vi.fn(), active: true };
    const { rerender } = render(
      <LiveTranscriptionPanel {...props} projectId="project-safe" />,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Начать" }));
    act(() => {
      controllerState.instances[0].callbacks.onPartial("Последний partial");
    });

    rerender(
      <LiveTranscriptionPanel
        key="project-next"
        {...props}
        projectId="project-next"
      />,
    );

    await waitFor(() => expect(oldProjectWrites).toHaveLength(1));
    expect(oldProjectWrites[0].partial).toBe("Последний partial");
  });

  it("bounds a stalled server checkpoint and reports degraded recovery", async () => {
    const defaultFetch = vi.mocked(fetch).getMockImplementation();
    let checkpointSignal: AbortSignal | undefined;
    vi.mocked(fetch).mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes("/realtime/drafts/") && init?.method === "PUT") {
        checkpointSignal = init.signal;
        return new Promise<Response>((_resolve, reject) => {
          checkpointSignal?.addEventListener("abort", () =>
            reject(new Error("raw-stalled-checkpoint")),
          );
        });
      }
      return defaultFetch?.(url, init) as Promise<Response>;
    });
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
      render(
        <LiveTranscriptionPanel
          projectId="project-safe"
          csrf="csrf-safe"
          onCsrf={vi.fn()}
          active
        />,
      );
      await userEvent.click(
        await screen.findByRole("button", { name: "Начать" }),
      );
      act(() => {
        controllerState.instances[0].callbacks.onCommitted("Timeout checkpoint");
      });
      expect(
        await screen.findByText(
          "Не все копии Live-черновика подтверждены. Не закрывайте вкладку и скачайте текст при первой возможности.",
        ),
      ).toBeInTheDocument();
      expect(checkpointSignal?.aborted).toBe(true);
      expect(document.body.textContent).not.toContain("raw-stalled-checkpoint");
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("checkpoints each committed fragment to the encrypted server draft API", async () => {
    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        active
      />,
    );
    const start = await screen.findByRole("button", { name: "Начать" });
    await waitFor(() => expect(start).toBeEnabled());
    await userEvent.click(start);

    act(() => {
      controllerState.instances[0].callbacks.onCommitted("Надёжный checkpoint");
    });
    await waitFor(() =>
      expect(
        vi.mocked(fetch).mock.calls.some(
          ([url, init]) =>
            String(url).includes("/realtime/drafts/") && init?.method === "PUT",
        ),
      ).toBe(true),
    );
    const checkpointCall = vi.mocked(fetch).mock.calls.find(
      ([url, init]) =>
        String(url).includes("/realtime/drafts/") && init?.method === "PUT",
    );
    expect(JSON.parse(String(checkpointCall?.[1]?.body))).toEqual({
      revision: 1,
      committed_segments: ["Надёжный checkpoint"],
      segment_metadata: [null],
      partial: "",
    });
    expect(String(checkpointCall?.[1]?.body)).not.toContain("audio");
  });

  it("checkpoints the latest partial only after the bounded debounce", async () => {
    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        active
      />,
    );
    const start = await screen.findByRole("button", { name: "Начать" });
    await waitFor(() => expect(start).toBeEnabled());
    await userEvent.click(start);
    act(() => {
      controllerState.instances[0].callbacks.onPartial("Последний partial");
    });
    expect(
      vi.mocked(fetch).mock.calls.some(
        ([url, init]) =>
          String(url).includes("/realtime/drafts/") && init?.method === "PUT",
      ),
    ).toBe(false);

    await waitFor(
      () =>
        expect(
          vi.mocked(fetch).mock.calls.some(
            ([url, init]) =>
              String(url).includes("/realtime/drafts/") && init?.method === "PUT",
          ),
        ).toBe(true),
      { timeout: 2_000 },
    );
    const checkpointCall = vi.mocked(fetch).mock.calls.find(
      ([url, init]) =>
        String(url).includes("/realtime/drafts/") && init?.method === "PUT",
    );
    expect(JSON.parse(String(checkpointCall?.[1]?.body))).toMatchObject({
      revision: 1,
      committed_segments: [],
      partial: "Последний partial",
    });
  });

  it("requires an active ElevenLabs profile", async () => {
    vi.mocked(fetch).mockImplementation((url: string) =>
      url.endsWith("/api/credentials")
        ? response({ credentials: [] })
        : response({ ok: true }),
    );
    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        active
      />,
    );
    expect(await screen.findByText("Активный профиль не найден")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Начать" })).toBeDisabled();
  });

  it("bounds a stalled profile read and exposes a safe explicit retry", async () => {
    let credentialGets = 0;
    let credentialSignal: AbortSignal | undefined;
    vi.mocked(fetch).mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/credentials")) {
        credentialGets += 1;
        credentialSignal = init?.signal;
        if (credentialGets === 1) {
          return new Promise<Response>((_resolve, reject) => {
            credentialSignal?.addEventListener("abort", () =>
              reject(new Error("raw-live-credential-timeout")),
            );
          });
        }
        return response({
          credentials: [
            {
              id: "credential-safe",
              provider: "elevenlabs",
              label: "Realtime",
              status: "active",
              active_version: 4,
              masked_value: "••••safe",
            },
          ],
        });
      }
      return response({ ok: true });
    });
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
      render(
        <LiveTranscriptionPanel
          projectId="project-safe"
          csrf="csrf-safe"
          onCsrf={vi.fn()}
          active
        />,
      );
      expect(
        await screen.findByText(
          "Не удалось загрузить профили STT. Повторите попытку.",
        ),
      ).toBeInTheDocument();
      expect(credentialSignal?.aborted).toBe(true);
      expect(credentialGets).toBe(1);
      expect(document.body.textContent).not.toContain(
        "raw-live-credential-timeout",
      );
      expect(screen.getByRole("button", { name: "Начать" })).toBeDisabled();

      await userEvent.click(
        screen.getByRole("button", {
          name: "Повторить загрузку профилей",
        }),
      );
      expect(await screen.findByText("Realtime · v4")).toBeInTheDocument();
      expect(credentialGets).toBe(2);
      expect(screen.getByRole("button", { name: "Начать" })).toBeEnabled();
    } finally {
      timeoutSpy.mockRestore();
    }
  });

  it("rejects malformed profile rows without retaining raw fields", async () => {
    vi.mocked(fetch).mockImplementation((url: string) =>
      url.endsWith("/api/credentials")
        ? response({
            credentials: [
              {
                id: "credential-unsafe",
                provider: "elevenlabs",
                label: "Realtime",
                status: "active",
                active_version: 4,
                masked_value: { raw: "raw-live-mask" },
                raw_credential: "raw-live-credential",
              },
            ],
            raw_collection: "raw-live-collection",
          })
        : response({ ok: true }),
    );

    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        active
      />,
    );
    expect(
      await screen.findByText(
        "Не удалось загрузить профили STT. Повторите попытку.",
      ),
    ).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("raw-live");
    expect(screen.getByRole("button", { name: "Начать" })).toBeDisabled();
  });

  it("keeps project-switch profile ownership latest-wins and teardown-safe", async () => {
    let credentialGets = 0;
    let staleSignal: AbortSignal | undefined;
    let resolveStale: ((response: Response) => void) | undefined;
    vi.mocked(fetch).mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/credentials")) {
        credentialGets += 1;
        if (credentialGets === 1) {
          staleSignal = init?.signal;
          return new Promise<Response>((resolve) => {
            resolveStale = resolve;
          });
        }
        return response({
          credentials: [
            {
              id: "credential-current",
              provider: "elevenlabs",
              label: "Current project profile",
              status: "active",
              active_version: 2,
              masked_value: "••••safe",
            },
          ],
        });
      }
      return response({ ok: true });
    });
    const props = { csrf: "csrf-safe", onCsrf: vi.fn(), active: true };
    const { rerender } = render(
      <LiveTranscriptionPanel {...props} projectId="project-a" />,
    );
    await waitFor(() => expect(resolveStale).toBeDefined());

    rerender(<LiveTranscriptionPanel {...props} projectId="project-b" />);
    expect(staleSignal?.aborted).toBe(true);
    expect(
      await screen.findByText("Current project profile · v2"),
    ).toBeInTheDocument();
    await act(async () =>
      resolveStale?.(
        await response({
          credentials: [
            {
              id: "credential-stale",
              provider: "elevenlabs",
              label: "Stale project profile",
              status: "active",
              active_version: 1,
              masked_value: "••••stale",
            },
          ],
        }),
      ),
    );
    expect(screen.queryByText(/Stale project profile/)).not.toBeInTheDocument();
    expect(credentialGets).toBe(2);
  });

  it("fails closed when browser audio capture is unavailable", async () => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        enumerateDevices: vi.fn().mockResolvedValue([]),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      },
    });

    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        active
      />,
    );

    expect(
      await screen.findByText("Этот браузер не поддерживает захват микрофона."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Этот браузер не поддерживает захват звука вкладки или экрана.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Начать" })).toBeDisabled();
    expect(
      screen.getByRole("checkbox", { name: "Микрофон или аудиовход" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("checkbox", { name: "Микрофон или аудиовход" }),
    ).not.toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Звук вкладки или экрана" }),
    ).toBeDisabled();
  });

  it("disposes capture when the browser page is hidden", async () => {
    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        active
      />,
    );
    const start = await screen.findByRole("button", { name: "Начать" });
    await waitFor(() => expect(start).toBeEnabled());
    await userEvent.click(start);
    await screen.findByText("Соединение установлено");

    window.dispatchEvent(new Event("pagehide"));

    expect(controllerState.instances[0].dispose).toHaveBeenCalledOnce();
  });

  it("keeps capture active when the document becomes hidden", async () => {
    render(
      <LiveTranscriptionPanel
        projectId="project-safe"
        csrf="csrf-safe"
        onCsrf={vi.fn()}
        active
      />,
    );
    const start = await screen.findByRole("button", { name: "Начать" });
    await waitFor(() => expect(start).toBeEnabled());
    await userEvent.click(start);
    await screen.findByText("Соединение установлено");
    const visibilityState = vi
      .spyOn(document, "visibilityState", "get")
      .mockReturnValue("hidden");

    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    expect(controllerState.instances[0].stop).not.toHaveBeenCalled();
    expect(screen.queryByText(/вкладка стала скрытой/)).not.toBeInTheDocument();
    visibilityState.mockRestore();
  });
});
