import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  RealtimeSessionController,
  realtimeProviderErrorMessage,
  type RealtimeSessionStatus,
} from "./realtimeSession";

const capability = {
  websocket_url:
    "wss://api.elevenlabs.io/v1/speech-to-text/realtime?model_id=scribe_v2_realtime&token=sutkn_test&audio_format=pcm_16000&commit_strategy=vad",
  expires_in_seconds: 900,
  model_id: "scribe_v2_realtime",
  audio_format: "pcm_16000",
  commit_strategy: "vad",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function mediaFixture({ includeVideo = false } = {}) {
  const stop = vi.fn();
  const track = { kind: "audio", stop, addEventListener: vi.fn() };
  const videoStop = vi.fn();
  const videoTrack = {
    kind: "video",
    stop: videoStop,
    addEventListener: vi.fn(),
  };
  const stream = {
    getTracks: () => (includeVideo ? [videoTrack, track] : [track]),
    getAudioTracks: () => [track],
  } as unknown as MediaStream;
  return { stream, stop, track, videoStop, videoTrack };
}

function audioFixture() {
  const processor = {
    onaudioprocess: null as ((event: AudioProcessingEvent) => void) | null,
    connect: vi.fn(),
    disconnect: vi.fn(),
  } as unknown as ScriptProcessorNode;
  const sources: Array<{
    connect: ReturnType<typeof vi.fn>;
    disconnect: ReturnType<typeof vi.fn>;
  }> = [];
  const gains: Array<{
    gain: {
      value: number;
      setTargetAtTime: ReturnType<typeof vi.fn>;
    };
    connect: ReturnType<typeof vi.fn>;
    disconnect: ReturnType<typeof vi.fn>;
  }> = [];
  const analysers: Array<{
    fftSize: number;
    connect: ReturnType<typeof vi.fn>;
    disconnect: ReturnType<typeof vi.fn>;
    getFloatTimeDomainData: ReturnType<typeof vi.fn>;
  }> = [];
  const analyserInputs: Float32Array[] = [];
  const destination = { disconnect: vi.fn(), stream: mediaFixture().stream };
  const context = {
    state: "running",
    sampleRate: 48_000,
    currentTime: 12,
    destination: {},
    resume: vi.fn().mockResolvedValue(undefined),
    close: vi.fn().mockResolvedValue(undefined),
    createMediaStreamSource: vi.fn(() => {
      const source = { connect: vi.fn(), disconnect: vi.fn() };
      sources.push(source);
      return source;
    }),
    createScriptProcessor: vi.fn(() => processor),
    createAnalyser: vi.fn(() => {
      const input = new Float32Array(2_048);
      const analyser = {
        fftSize: 2_048,
        connect: vi.fn(),
        disconnect: vi.fn(),
        getFloatTimeDomainData: vi.fn((target: Float32Array) => {
          target.set(input);
        }),
      };
      analysers.push(analyser);
      analyserInputs.push(input);
      return analyser;
    }),
    createGain: vi.fn(() => {
      const gain = {
        gain: { value: 1, setTargetAtTime: vi.fn() },
        connect: vi.fn(),
        disconnect: vi.fn(),
      };
      gains.push(gain);
      return gain;
    }),
    createMediaStreamDestination: vi.fn(() => destination),
  } as unknown as AudioContext;
  return {
    context,
    processor,
    sources,
    gains,
    analysers,
    analyserInputs,
    destination,
  };
}

function websocketFixture() {
  const socket = {
    readyState: 0,
    bufferedAmount: 0,
    send: vi.fn(),
    close: vi.fn(),
    onopen: null as (() => void) | null,
    onmessage: null as ((message: MessageEvent) => void) | null,
    onerror: null as (() => void) | null,
    onclose: null as (() => void) | null,
  } as unknown as WebSocket;
  return socket;
}

describe("RealtimeSessionController", () => {
  it("clears at captured audio time without restarting capture, the socket or a paid capability", async () => {
    vi.useFakeTimers();
    const microphone = mediaFixture(), audio = audioFixture(), socket = websocketFixture();
    const committed = vi.fn(), partial = vi.fn(), pending = vi.fn(), requestCapability = vi.fn().mockResolvedValue(capability);
    const controller = new RealtimeSessionController({onStatus:vi.fn(),onPartial:partial,onCommitted:committed,onError:vi.fn(),onClearBoundaryPending:pending},
      {requestCapability,mediaDevices:{getUserMedia:vi.fn().mockResolvedValue(microphone.stream)},
        createAudioContext:() => audio.context,createWebSocket:() => socket});
    try {
      await controller.start({displayAudio:false,microphone:true});
      (socket as unknown as {readyState:number}).readyState = 1;
      socket.onopen?.(new Event("open"));
      const emit = (value:unknown) => socket.onmessage?.(new MessageEvent("message",{data:JSON.stringify(value)}));
      emit({message_type:"session_started"});
      audio.processor.onaudioprocess?.({inputBuffer:{getChannelData:() => new Float32Array(48000)}} as unknown as AudioProcessingEvent);
      emit({message_type:"committed_transcript",text:"до",start_seconds:0,end_seconds:0.5,final_index:0});
      controller.clearTranscript();
      expect(pending).toHaveBeenLastCalledWith(true);
      emit({message_type:"committed_transcript",text:"позднее до",start_seconds:0,end_seconds:0.5,final_index:0});
      emit({message_type:"partial_transcript",text:"до после"});
      expect(partial).toHaveBeenLastCalledWith("");
      emit({message_type:"committed_transcript_with_timestamps",text:"до после",words:[
        {text:"до",start:0,end:0.5,type:"word"},{text:" ",type:"spacing"},{text:"после",start:1.1,end:1.5,type:"word"}]});
      expect(committed).toHaveBeenCalledTimes(2);
      expect(committed.mock.calls[1]).toEqual(["после",expect.objectContaining({start_seconds:1.1,end_seconds:1.5})]);
      expect(pending).toHaveBeenLastCalledWith(false);
      expect(requestCapability).toHaveBeenCalledOnce();
      expect(microphone.stop).not.toHaveBeenCalled();
      expect(socket.close).not.toHaveBeenCalled();
      expect(controller.active).toBe(true);
    } finally { controller.dispose(); vi.useRealTimers(); }
  });
  beforeEach(() => {
    vi.stubGlobal("WebSocket", { CONNECTING: 0, OPEN: 1 });
  });

  it("uses a fresh capability, replays only unsent audio and keeps absolute timing across transports", async () => {
    vi.useFakeTimers();
    const microphone = mediaFixture(), audio = audioFixture();
    const sockets = [websocketFixture(), websocketFixture(), websocketFixture()];
    const requestCapability = vi.fn().mockResolvedValue(capability);
    const commits = vi.fn();
    let connection = 0;
    const controller = new RealtimeSessionController(
      { onStatus: vi.fn(), onPartial: vi.fn(), onCommitted: commits, onError: vi.fn() },
      { requestCapability, mediaDevices: { getUserMedia: vi.fn().mockResolvedValue(microphone.stream) }, createAudioContext: () => audio.context, createWebSocket: () => sockets[connection++] },
    );
    const open = (socket: WebSocket) => {
      (socket as unknown as { readyState: number }).readyState = 1;
      socket.onopen?.(new Event("open"));
      socket.onmessage?.(new MessageEvent("message", { data: JSON.stringify({ message_type: "session_started" }) }));
    };
    const frame = () => audio.processor.onaudioprocess?.({ inputBuffer: { getChannelData: () => new Float32Array(48000) } } as AudioProcessingEvent);
    try {
      await controller.start({ displayAudio: false, microphone: true });
      open(sockets[0]);
      frame(); frame();
      sockets[0].onmessage?.(new MessageEvent("message", { data: JSON.stringify({ message_type: "committed_transcript_with_timestamps", text: "до обрыва", start_seconds: 0, end_seconds: 1 }) }));
      sockets[0].onerror?.(new Event("error"));
      frame();
      await vi.advanceTimersByTimeAsync(1000);
      expect(requestCapability).toHaveBeenCalledTimes(2);
      expect(sockets[1].send).not.toHaveBeenCalled();
      open(sockets[1]);
      expect(sockets[1].send).toHaveBeenCalledTimes(1);
      sockets[1].onmessage?.(new MessageEvent("message", { data: JSON.stringify({ message_type: "committed_transcript_with_timestamps", text: "после обрыва", start_seconds: 0, end_seconds: 1 }) }));
      expect(commits).toHaveBeenCalledWith("после обрыва", expect.objectContaining({ start_seconds: 2, end_seconds: 3 }));
      frame();
      sockets[1].onerror?.(new Event("error"));
      const gaps = commits.mock.calls.filter(([, metadata]) => metadata.gap);
      expect(gaps.map(([, metadata]) => [metadata.start_seconds, metadata.end_seconds])).toEqual([[1, 2], [3, 4]]);
      expect(gaps[0][1].id).not.toBe(gaps[1][1].id);
      expect(microphone.stop).not.toHaveBeenCalled();
      controller.dispose();
      await vi.advanceTimersByTimeAsync(5000);
      expect(requestCapability).toHaveBeenCalledTimes(2);
      expect(microphone.stop).toHaveBeenCalledOnce();
    } finally { controller.dispose(); vi.useRealTimers(); }
  });

  it("buffers capture during planned rotation and reports an unconfirmed tail instead of silently losing it", async () => {
    vi.useFakeTimers();
    const microphone = mediaFixture(), audio = audioFixture();
    const sockets = [websocketFixture(), websocketFixture()];
    let connection = 0;
    const commits = vi.fn(), requestCapability = vi.fn().mockResolvedValue({ ...capability, provider: "yandex", websocket_url: "ws://localhost:3000/api/realtime/yandex?capability=header.signature", model_id: "general" });
    const controller = new RealtimeSessionController(
      { onStatus: vi.fn(), onPartial: vi.fn(), onCommitted: commits, onError: vi.fn() },
      { requestCapability, mediaDevices: { getUserMedia: vi.fn().mockResolvedValue(microphone.stream) }, createAudioContext: () => audio.context, createWebSocket: () => sockets[connection++] },
    );
    const open = (socket: WebSocket) => {
      (socket as unknown as { readyState: number }).readyState = 1;
      socket.onopen?.(new Event("open"));
      socket.onmessage?.(new MessageEvent("message", { data: JSON.stringify({ message_type: "session_started" }) }));
    };
    const frame = () => audio.processor.onaudioprocess?.({ inputBuffer: { getChannelData: () => new Float32Array(48000) } } as AudioProcessingEvent);
    try {
      await controller.start({ displayAudio: false, microphone: true });
      open(sockets[0]); frame();
      await vi.advanceTimersByTimeAsync(295000);
      expect(sockets[0].send).toHaveBeenCalledTimes(2); // audio, then commit
      frame();
      expect(sockets[0].send).toHaveBeenCalledTimes(2);
      await vi.advanceTimersByTimeAsync(2001);
      expect(requestCapability).toHaveBeenCalledTimes(2);
      open(sockets[1]);
      expect(sockets[1].send).toHaveBeenCalledTimes(1);
      expect(commits).toHaveBeenCalledWith(expect.stringContaining("не полностью подтверждено"), expect.objectContaining({ start_seconds: 0, end_seconds: 1, gap: true }));
      expect(microphone.stop).not.toHaveBeenCalled();
    } finally { controller.dispose(); vi.useRealTimers(); }
  });

  it("maps safe provider codes to distinct operator actions", () => {
    expect(realtimeProviderErrorMessage("session_time_limit_exceeded")).toContain(
      "максимальная длительность",
    );
    expect(realtimeProviderErrorMessage("rate_limited")).toContain(
      "частоту realtime-запросов",
    );
    expect(realtimeProviderErrorMessage("quota_exceeded")).toContain(
      "баланс ElevenLabs",
    );
    expect(realtimeProviderErrorMessage("queue_overflow")).toContain(
      "Очередь ElevenLabs",
    );
    expect(realtimeProviderErrorMessage("input_error")).toContain(
      "аудиопоток",
    );
    expect(
      realtimeProviderErrorMessage("insufficient_audio_activity"),
    ).toContain("речевой активности");
    expect(realtimeProviderErrorMessage("quota_exceeded", "yandex")).toContain(
      "Yandex SpeechKit",
    );
  });

  it("commits and rotates Yandex transport before the limit without releasing capture", async () => {
    const microphone = mediaFixture();
    const audio = audioFixture();
    const socket = websocketFixture();
    const timers = new Map<number, { callback: () => void; milliseconds: number }>();
    let timerId = 0;
    const errors: string[] = [];
    const statuses: RealtimeSessionStatus[] = [];
    const controller = new RealtimeSessionController(
      {
        onStatus: (status) => statuses.push(status),
        onPartial: vi.fn(),
        onCommitted: vi.fn(),
        onError: (message) => errors.push(message),
      },
      {
        requestCapability: vi.fn().mockResolvedValue({
          provider: "yandex",
          websocket_url:
            "ws://localhost:3000/api/realtime/yandex?capability=header.signature",
          expires_in_seconds: 300,
          model_id: "general",
          audio_format: "pcm_16000",
          commit_strategy: "vad",
        }),
        mediaDevices: {
          getUserMedia: vi.fn().mockResolvedValue(microphone.stream),
        },
        createAudioContext: () => audio.context,
        createWebSocket: () => socket,
        setTimer: (callback, milliseconds) => {
          const id = ++timerId;
          timers.set(id, { callback, milliseconds });
          return id;
        },
        clearTimer: (id) => {
          timers.delete(id);
        },
      },
    );

    await controller.start({ displayAudio: false, microphone: true });
    (socket as unknown as { readyState: number }).readyState = WebSocket.OPEN;
    socket.onopen?.(new Event("open"));
    socket.onmessage?.(
      new MessageEvent("message", {
        data: JSON.stringify({ message_type: "session_started" }),
      }),
    );
    const duration = [...timers.values()].find(
      (timer) => timer.milliseconds === 295_000,
    );
    expect(duration).toBeDefined();

    duration?.callback();

    expect(errors.at(-1)).toContain("пятью минутами");
    expect(statuses.at(-1)).toBe("transcribing");
    expect(JSON.parse(String(vi.mocked(socket.send).mock.calls.at(-1)?.[0]))).toMatchObject({
      commit: true,
    });
    expect(microphone.stop).not.toHaveBeenCalled();
    [...timers.values()].find((timer) => timer.milliseconds === 2000)?.callback();
    expect(statuses.at(-1)).toBe("reconnecting");
    expect(microphone.stop).not.toHaveBeenCalled();
    controller.dispose();
  });

  it("requests browser permission before consuming a capability", async () => {
    const display = mediaFixture();
    const permission = deferred<MediaStream>();
    const requestCapability = vi.fn().mockResolvedValue(capability);
    const statuses: RealtimeSessionStatus[] = [];
    const controller = new RealtimeSessionController(
      {
        onStatus: (status) => statuses.push(status),
        onPartial: vi.fn(),
        onCommitted: vi.fn(),
        onError: vi.fn(),
      },
      {
        requestCapability,
        mediaDevices: {
          getDisplayMedia: vi.fn(() => permission.promise),
          getUserMedia: vi.fn(),
        },
        createAudioContext: () => audioFixture().context,
        createWebSocket: () => websocketFixture(),
        setTimer: vi.fn(),
        clearTimer: vi.fn(),
      },
    );

    const starting = controller.start({
      displayAudio: true,
      microphone: false,
    });
    expect(statuses).toEqual(["requesting_permission"]);
    expect(requestCapability).not.toHaveBeenCalled();

    controller.stop();
    permission.resolve(display.stream);
    await starting;
    expect(display.stop).toHaveBeenCalled();
    expect(requestCapability).not.toHaveBeenCalled();
    expect(statuses.at(-1)).toBe("stopped");
  });

  it("does not consume a capability when browser permission is rejected", async () => {
    const requestCapability = vi.fn().mockResolvedValue(capability);
    const statuses: RealtimeSessionStatus[] = [];
    const errors: string[] = [];
    const controller = new RealtimeSessionController(
      {
        onStatus: (status) => statuses.push(status),
        onPartial: vi.fn(),
        onCommitted: vi.fn(),
        onError: (message) => errors.push(message),
      },
      {
        requestCapability,
        mediaDevices: {
          getUserMedia: vi
            .fn()
            .mockRejectedValue(new DOMException("Denied", "NotAllowedError")),
        },
      },
    );

    await controller.start({ displayAudio: false, microphone: true });

    expect(requestCapability).not.toHaveBeenCalled();
    expect(errors.at(-1)).toContain("отменено или отклонено");
    expect(statuses).toEqual(["requesting_permission", "ready"]);
    expect(controller.active).toBe(false);
  });

  it("rejects display capture without an audio track before issuing a capability", async () => {
    const stop = vi.fn();
    const display = {
      getTracks: () => [{ stop, addEventListener: vi.fn() }],
      getAudioTracks: () => [],
    } as unknown as MediaStream;
    const requestCapability = vi.fn().mockResolvedValue(capability);
    const errors: string[] = [];
    const controller = new RealtimeSessionController(
      {
        onStatus: vi.fn(),
        onPartial: vi.fn(),
        onCommitted: vi.fn(),
        onError: (message) => errors.push(message),
      },
      {
        requestCapability,
        mediaDevices: {
          getDisplayMedia: vi.fn().mockResolvedValue(display),
        },
      },
    );

    await controller.start({ displayAudio: true, microphone: false });

    expect(requestCapability).not.toHaveBeenCalled();
    expect(stop).toHaveBeenCalled();
    expect(errors.at(-1)).toContain("не передал звук");
    expect(controller.active).toBe(false);
  });

  it("stops cleanly when the user cancels a pending capability request", async () => {
    const microphone = mediaFixture();
    const requestEntered = deferred<void>();
    const statuses: RealtimeSessionStatus[] = [];
    let capabilitySignal: AbortSignal | undefined;
    const controller = new RealtimeSessionController(
      {
        onStatus: (status) => statuses.push(status),
        onPartial: vi.fn(),
        onCommitted: vi.fn(),
        onError: vi.fn(),
      },
      {
        requestCapability: (signal) => {
          capabilitySignal = signal;
          requestEntered.resolve(undefined);
          return new Promise((_resolve, reject) => {
            signal.addEventListener(
              "abort",
              () => reject(new DOMException("Aborted", "AbortError")),
              { once: true },
            );
          });
        },
        mediaDevices: {
          getUserMedia: vi.fn().mockResolvedValue(microphone.stream),
        },
        createAudioContext: () => audioFixture().context,
        setTimer: vi.fn(() => 17),
        clearTimer: vi.fn(),
      },
    );

    const starting = controller.start({ displayAudio: false, microphone: true });
    await requestEntered.promise;
    controller.stop();
    await starting;

    expect(capabilitySignal?.aborted).toBe(true);
    expect(microphone.stop).toHaveBeenCalled();
    expect(statuses.at(-1)).toBe("stopped");
    expect(controller.active).toBe(false);
  });

  it("stops the session when a captured source ends", async () => {
    const microphone = mediaFixture();
    const audio = audioFixture();
    const errors: string[] = [];
    const statuses: RealtimeSessionStatus[] = [];
    const controller = new RealtimeSessionController(
      {
        onStatus: (status) => statuses.push(status),
        onPartial: vi.fn(),
        onCommitted: vi.fn(),
        onError: (message) => errors.push(message),
      },
      {
        requestCapability: vi.fn().mockResolvedValue(capability),
        mediaDevices: {
          getUserMedia: vi.fn().mockResolvedValue(microphone.stream),
        },
        createAudioContext: () => audio.context,
        createWebSocket: () => websocketFixture(),
        setTimer: vi.fn(() => 19),
        clearTimer: vi.fn(),
      },
    );

    await controller.start({ displayAudio: false, microphone: true });
    const ended = microphone.track.addEventListener.mock.calls.find(
      ([event]) => event === "ended",
    )?.[1] as EventListener | undefined;
    ended?.(new Event("ended"));

    expect(errors.at(-1)).toContain("Источник аудио остановлен");
    expect(microphone.stop).toHaveBeenCalled();
    expect(statuses.at(-1)).toBe("stopped");
    expect(controller.active).toBe(false);
  });

  it("does not subscribe to the auxiliary display video track ending", async () => {
    const display = mediaFixture({ includeVideo: true });
    const audio = audioFixture();
    const errors: string[] = [];
    const controller = new RealtimeSessionController(
      {
        onStatus: vi.fn(),
        onPartial: vi.fn(),
        onCommitted: vi.fn(),
        onError: (message) => errors.push(message),
      },
      {
        requestCapability: vi.fn().mockResolvedValue(capability),
        mediaDevices: {
          getDisplayMedia: vi.fn().mockResolvedValue(display.stream),
        },
        createAudioContext: () => audio.context,
        createWebSocket: () => websocketFixture(),
        setTimer: vi.fn(() => 29),
        clearTimer: vi.fn(),
      },
    );

    await controller.start({ displayAudio: true, microphone: false });

    expect(display.videoTrack.addEventListener).not.toHaveBeenCalled();
    expect(display.track.addEventListener).toHaveBeenCalledWith(
      "ended",
      expect.any(Function),
      { once: true },
    );
    expect(errors.filter(Boolean)).toEqual([]);
    expect(controller.active).toBe(true);

    controller.dispose();
    expect(display.videoStop).toHaveBeenCalledOnce();
    expect(display.stop).toHaveBeenCalledOnce();
  });

  it("streams PCM, presents partial and committed text, and stops cleanly", async () => {
    const microphone = mediaFixture();
    const audio = audioFixture();
    const socket = websocketFixture();
    const statuses: RealtimeSessionStatus[] = [];
    const partials: string[] = [];
    const committed: string[] = [];
    const errors: string[] = [];
    const inputLevels: number[] = [];
    const timerCallbacks: Array<() => void> = [];
    const timerDelays: number[] = [];
    const controller = new RealtimeSessionController(
      {
        onStatus: (status) => statuses.push(status),
        onPartial: (text) => partials.push(text),
        onCommitted: (text) => committed.push(text),
        onError: (message) => errors.push(message),
        onInputLevel: (level) => inputLevels.push(level),
      },
      {
        requestCapability: vi.fn().mockResolvedValue(capability),
        mediaDevices: {
          getDisplayMedia: vi.fn(),
          getUserMedia: vi.fn().mockResolvedValue(microphone.stream),
        },
        createAudioContext: () => audio.context,
        createWebSocket: () => socket,
        setTimer: (callback, milliseconds) => {
          timerCallbacks.push(callback);
          timerDelays.push(milliseconds);
          return timerCallbacks.length;
        },
        clearTimer: vi.fn(),
      },
    );

    await controller.start({ displayAudio: false, microphone: true });
    expect(statuses).toEqual([
      "requesting_permission",
      "connecting",
    ]);
    (socket as unknown as { readyState: number }).readyState = 1;
    socket.onopen?.(new Event("open"));
    socket.onmessage?.(
      new MessageEvent("message", {
        data: JSON.stringify({ message_type: "session_started" }),
      }),
    );
    socket.onmessage?.(
      new MessageEvent("message", {
        data: JSON.stringify({
          message_type: "partial_transcript",
          text: "черновик",
        }),
      }),
    );
    socket.onmessage?.(
      new MessageEvent("message", {
        data: JSON.stringify({
          message_type: "final_transcript",
          text: "уточнённый черновик",
        }),
      }),
    );
    socket.onmessage?.(
      new MessageEvent("message", {
        data: JSON.stringify({
          message_type: "committed_transcript",
          text: "готовый фрагмент",
        }),
      }),
    );
    expect(statuses.at(-1)).toBe("transcribing");
    expect(partials).toEqual([
      "",
      "черновик",
      "уточнённый черновик",
      "",
    ]);
    expect(committed).toEqual(["готовый фрагмент"]);
    expect(errors.every((message) => message === "")).toBe(true);

    audio.processor.onaudioprocess?.({
      inputBuffer: {
        getChannelData: () => new Float32Array(48).fill(0.25),
      },
    } as AudioProcessingEvent);
    expect(socket.send).toHaveBeenCalledTimes(1);
    expect(inputLevels.at(-1)).toBeCloseTo(1);
    expect(JSON.parse(String(vi.mocked(socket.send).mock.calls[0][0]))).toMatchObject({
      message_type: "input_audio_chunk",
      sample_rate: 16_000,
    });

    controller.stop();
    expect(timerDelays).toEqual([25_000, 10_000, 10_000, 2_000]);
    expect(microphone.stop).toHaveBeenCalled();
    expect(inputLevels.at(-1)).toBe(0);
    expect(JSON.parse(String(vi.mocked(socket.send).mock.calls[1][0]))).toEqual({
      message_type: "input_audio_chunk",
      audio_base_64: "",
      sample_rate: 16_000,
      commit: true,
    });
    timerCallbacks.at(-1)?.();
    expect(socket.close).toHaveBeenCalledWith(1000, "Остановлено пользователем");
    expect(statuses.at(-1)).toBe("stopped");
    expect(controller.active).toBe(false);
  });

  it("coalesces repeated stop requests while the final commit is pending", async () => {
    const microphone = mediaFixture();
    const audio = audioFixture();
    const socket = websocketFixture();
    const statuses: RealtimeSessionStatus[] = [];
    const partials: string[] = [];
    const timerCallbacks: Array<() => void> = [];
    const timerDelays: number[] = [];
    const controller = new RealtimeSessionController(
      {
        onStatus: (status) => statuses.push(status),
        onPartial: (text) => partials.push(text),
        onCommitted: vi.fn(),
        onError: vi.fn(),
      },
      {
        requestCapability: vi.fn().mockResolvedValue(capability),
        mediaDevices: {
          getUserMedia: vi.fn().mockResolvedValue(microphone.stream),
        },
        createAudioContext: () => audio.context,
        createWebSocket: () => socket,
        setTimer: (callback, milliseconds) => {
          timerCallbacks.push(callback);
          timerDelays.push(milliseconds);
          return timerCallbacks.length;
        },
        clearTimer: vi.fn(),
      },
    );

    await controller.start({ displayAudio: false, microphone: true });
    (socket as unknown as { readyState: number }).readyState = 1;
    socket.onopen?.(new Event("open"));
    socket.onmessage?.(
      new MessageEvent("message", {
        data: JSON.stringify({
          message_type: "partial_transcript",
          text: "последний неподтверждённый фрагмент",
        }),
      }),
    );

    controller.stop();
    controller.stop();

    expect(timerDelays.filter((delay) => delay === 2_000)).toHaveLength(1);
    expect(socket.send).toHaveBeenCalledTimes(1);
    expect(microphone.stop).toHaveBeenCalledOnce();
    expect(audio.context.close).toHaveBeenCalledOnce();
    expect(statuses.filter((status) => status === "stopping")).toHaveLength(1);
    expect(partials.at(-1)).toBe("последний неподтверждённый фрагмент");

    timerCallbacks.at(-1)?.();
    expect(socket.close).toHaveBeenCalledOnce();
    expect(statuses.filter((status) => status === "stopped")).toHaveLength(1);
    expect(controller.active).toBe(false);
  });

  it("starts a fresh owned session after a completed stop cycle", async () => {
    const microphones = [mediaFixture(), mediaFixture()];
    const audio = [audioFixture(), audioFixture()];
    const sockets = [websocketFixture(), websocketFixture()];
    const statuses: RealtimeSessionStatus[] = [];
    const timerCallbacks: Array<() => void> = [];
    const getUserMedia = vi
      .fn()
      .mockResolvedValueOnce(microphones[0].stream)
      .mockResolvedValueOnce(microphones[1].stream);
    const createAudioContext = vi
      .fn()
      .mockReturnValueOnce(audio[0].context)
      .mockReturnValueOnce(audio[1].context);
    const createWebSocket = vi
      .fn()
      .mockReturnValueOnce(sockets[0])
      .mockReturnValueOnce(sockets[1]);
    const controller = new RealtimeSessionController(
      {
        onStatus: (status) => statuses.push(status),
        onPartial: vi.fn(),
        onCommitted: vi.fn(),
        onError: vi.fn(),
      },
      {
        requestCapability: vi.fn().mockResolvedValue(capability),
        mediaDevices: { getUserMedia },
        createAudioContext,
        createWebSocket,
        setTimer: (callback) => {
          timerCallbacks.push(callback);
          return timerCallbacks.length;
        },
        clearTimer: vi.fn(),
      },
    );

    for (let index = 0; index < 2; index += 1) {
      await controller.start({ displayAudio: false, microphone: true });
      (sockets[index] as unknown as { readyState: number }).readyState = 1;
      sockets[index].onopen?.(new Event("open"));
      sockets[index].onmessage?.(
        new MessageEvent("message", {
          data: JSON.stringify({ message_type: "session_started" }),
        }),
      );
      expect(controller.active).toBe(true);
      expect(statuses.at(-1)).toBe("transcribing");

      controller.stop();
      timerCallbacks.at(-1)?.();

      expect(controller.active).toBe(false);
      expect(statuses.at(-1)).toBe("stopped");
      expect(microphones[index].stop).toHaveBeenCalledOnce();
      expect(audio[index].context.close).toHaveBeenCalledOnce();
      expect(sockets[index].close).toHaveBeenCalledOnce();
    }

    expect(getUserMedia).toHaveBeenCalledTimes(2);
    expect(createAudioContext).toHaveBeenCalledTimes(2);
    expect(createWebSocket).toHaveBeenCalledTimes(2);
    expect(statuses.filter((status) => status === "transcribing")).toHaveLength(2);
    expect(statuses.filter((status) => status === "stopped")).toHaveLength(2);
  });

  it("keeps capture while retrying a socket connection timeout", async () => {
    const microphone = mediaFixture();
    const audio = audioFixture();
    const socket = websocketFixture();
    const statuses: RealtimeSessionStatus[] = [];
    const errors: string[] = [];
    let connectTimeout: (() => void) | undefined;
    const controller = new RealtimeSessionController(
      {
        onStatus: (status) => statuses.push(status),
        onPartial: vi.fn(),
        onCommitted: vi.fn(),
        onError: (message) => errors.push(message),
      },
      {
        requestCapability: vi.fn().mockResolvedValue(capability),
        mediaDevices: {
          getDisplayMedia: vi.fn(),
          getUserMedia: vi.fn().mockResolvedValue(microphone.stream),
        },
        createAudioContext: () => audio.context,
        createWebSocket: () => socket,
        setTimer: (callback, milliseconds) => {
          if (milliseconds === 10_000) connectTimeout = callback;
          return 23;
        },
        clearTimer: vi.fn(),
      },
    );

    await controller.start({ displayAudio: false, microphone: true });
    expect(statuses.at(-1)).toBe("connecting");
    connectTimeout?.();

    expect(socket.close).toHaveBeenCalledWith(1000, "Переподключение");
    expect(microphone.stop).not.toHaveBeenCalled();
    expect(statuses.at(-1)).toBe("reconnecting");
    expect(controller.active).toBe(true);
    controller.dispose();
    expect(microphone.stop).toHaveBeenCalledOnce();
  });

  it("keeps capture while retrying a provider session handshake timeout", async () => {
    const microphone = mediaFixture();
    const audio = audioFixture();
    const socket = websocketFixture();
    const statuses: RealtimeSessionStatus[] = [];
    const errors: string[] = [];
    const tenSecondTimers: Array<() => void> = [];
    const controller = new RealtimeSessionController(
      {
        onStatus: (status) => statuses.push(status),
        onPartial: vi.fn(),
        onCommitted: vi.fn(),
        onError: (message) => errors.push(message),
      },
      {
        requestCapability: vi.fn().mockResolvedValue(capability),
        mediaDevices: {
          getUserMedia: vi.fn().mockResolvedValue(microphone.stream),
        },
        createAudioContext: () => audio.context,
        createWebSocket: () => socket,
        setTimer: (callback, milliseconds) => {
          if (milliseconds === 10_000) tenSecondTimers.push(callback);
          return tenSecondTimers.length + 50;
        },
        clearTimer: vi.fn(),
      },
    );

    await controller.start({ displayAudio: false, microphone: true });
    (socket as unknown as { readyState: number }).readyState = 1;
    socket.onopen?.(new Event("open"));
    expect(statuses.at(-1)).toBe("connected");
    expect(tenSecondTimers).toHaveLength(2);

    tenSecondTimers[1]();

    expect(socket.close).toHaveBeenCalledWith(1000, "Переподключение");
    expect(microphone.stop).not.toHaveBeenCalled();
    expect(statuses.at(-1)).toBe("reconnecting");
    expect(controller.active).toBe(true);
    controller.dispose();
  });

  it("never exposes a capability URL from a WebSocket constructor failure", async () => {
    const microphone = mediaFixture();
    const audio = audioFixture();
    const errors: string[] = [];
    const controller = new RealtimeSessionController(
      {
        onStatus: vi.fn(),
        onPartial: vi.fn(),
        onCommitted: vi.fn(),
        onError: (message) => errors.push(message),
      },
      {
        requestCapability: vi.fn().mockResolvedValue(capability),
        mediaDevices: {
          getUserMedia: vi.fn().mockResolvedValue(microphone.stream),
        },
        createAudioContext: () => audio.context,
        createWebSocket: (url) => {
          throw new Error(`CSP rejected ${url}`);
        },
        setTimer: vi.fn(() => 37),
        clearTimer: vi.fn(),
      },
    );

    await controller.start({ displayAudio: false, microphone: true });

    expect(errors.at(-1)).toContain("защищённое realtime-соединение");
    expect(errors.join(" ")).not.toContain("sutkn_test");
    expect(errors.join(" ")).not.toContain("wss://");
    expect(microphone.stop).toHaveBeenCalledOnce();
    expect(controller.active).toBe(false);
  });

  it("aborts a stalled capability request and releases capture", async () => {
    const microphone = mediaFixture();
    const audio = audioFixture();
    const requestEntered = deferred<void>();
    const errors: string[] = [];
    const statuses: RealtimeSessionStatus[] = [];
    let capabilitySignal: AbortSignal | undefined;
    let capabilityTimeout: (() => void) | undefined;
    const controller = new RealtimeSessionController(
      {
        onStatus: (status) => statuses.push(status),
        onPartial: vi.fn(),
        onCommitted: vi.fn(),
        onError: (message) => errors.push(message),
      },
      {
        requestCapability: (signal) => {
          capabilitySignal = signal;
          requestEntered.resolve(undefined);
          return new Promise((_resolve, reject) => {
            signal.addEventListener(
              "abort",
              () => reject(new DOMException("Aborted", "AbortError")),
              { once: true },
            );
          });
        },
        mediaDevices: {
          getUserMedia: vi.fn().mockResolvedValue(microphone.stream),
        },
        createAudioContext: () => audio.context,
        createWebSocket: vi.fn(),
        setTimer: (callback, milliseconds) => {
          if (milliseconds === 25_000) capabilityTimeout = callback;
          return 41;
        },
        clearTimer: vi.fn(),
      },
    );

    const starting = controller.start({
      displayAudio: false,
      microphone: true,
    });
    await requestEntered.promise;
    capabilityTimeout?.();
    await starting;

    expect(capabilitySignal?.aborted).toBe(true);
    expect(microphone.stop).toHaveBeenCalled();
    expect(errors.at(-1)).toContain("25 секунд");
    expect(statuses.at(-1)).toBe("ready");
    expect(controller.active).toBe(false);
  });

  it("reconnects with a bounded replay queue when websocket backpressure becomes unsafe", async () => {
    const microphone = mediaFixture();
    const audio = audioFixture();
    const socket = websocketFixture();
    const errors: string[] = [];
    const statuses: RealtimeSessionStatus[] = [];
    const controller = new RealtimeSessionController(
      {
        onStatus: (status) => statuses.push(status),
        onPartial: vi.fn(),
        onCommitted: vi.fn(),
        onError: (message) => errors.push(message),
      },
      {
        requestCapability: vi.fn().mockResolvedValue(capability),
        mediaDevices: {
          getUserMedia: vi.fn().mockResolvedValue(microphone.stream),
        },
        createAudioContext: () => audio.context,
        createWebSocket: () => socket,
        setTimer: vi.fn(() => 31),
        clearTimer: vi.fn(),
      },
    );

    await controller.start({ displayAudio: false, microphone: true });
    (socket as unknown as { readyState: number; bufferedAmount: number }).readyState = 1;
    (socket as unknown as { bufferedAmount: number }).bufferedAmount = 600_000;
    socket.onopen?.(new Event("open"));
    socket.onmessage?.(new MessageEvent("message", { data: JSON.stringify({ message_type: "session_started" }) }));
    audio.processor.onaudioprocess?.({
      inputBuffer: {
        getChannelData: () => new Float32Array(48).fill(0.2),
      },
    } as AudioProcessingEvent);

    expect(socket.send).not.toHaveBeenCalled();
    expect(socket.close).toHaveBeenCalledWith(1000, "Переподключение");
    expect(statuses.at(-1)).toBe("reconnecting");
    expect(microphone.stop).not.toHaveBeenCalled();
    expect(controller.active).toBe(true);
    controller.dispose();
  });

  it("retains an unsent frame when websocket send races with a closed connection", async () => {
    const microphone = mediaFixture();
    const audio = audioFixture();
    const socket = websocketFixture();
    const errors: string[] = [];
    const statuses: RealtimeSessionStatus[] = [];
    const controller = new RealtimeSessionController(
      {
        onStatus: (status) => statuses.push(status),
        onPartial: vi.fn(),
        onCommitted: vi.fn(),
        onError: (message) => errors.push(message),
      },
      {
        requestCapability: vi.fn().mockResolvedValue(capability),
        mediaDevices: {
          getUserMedia: vi.fn().mockResolvedValue(microphone.stream),
        },
        createAudioContext: () => audio.context,
        createWebSocket: () => socket,
        setTimer: vi.fn(() => 37),
        clearTimer: vi.fn(),
      },
    );

    await controller.start({ displayAudio: false, microphone: true });
    (socket as unknown as { readyState: number }).readyState = 1;
    socket.onopen?.(new Event("open"));
    socket.onmessage?.(new MessageEvent("message", { data: JSON.stringify({ message_type: "session_started" }) }));
    vi.mocked(socket.send).mockImplementationOnce(() => {
      throw new DOMException("Socket already closed", "InvalidStateError");
    });

    expect(() =>
      audio.processor.onaudioprocess?.({
        inputBuffer: {
          getChannelData: () => new Float32Array(48).fill(0.2),
        },
      } as AudioProcessingEvent),
    ).not.toThrow();

    expect(socket.close).toHaveBeenCalledWith(1000, "Переподключение");
    expect(statuses.at(-1)).toBe("reconnecting");
    expect(microphone.stop).not.toHaveBeenCalled();
    controller.dispose();
    expect(microphone.stop).toHaveBeenCalledOnce();
    expect(audio.context.close).toHaveBeenCalledOnce();
    expect(controller.active).toBe(false);
  });

  it("mixes display audio and microphone in one AudioContext", async () => {
    const display = mediaFixture();
    const microphone = mediaFixture();
    const audio = audioFixture();
    const socket = websocketFixture();
    const sourceLevels: Array<{ kind: string; level: number }> = [];
    const getDisplayMedia = vi.fn().mockResolvedValue(display.stream);
    const getUserMedia = vi.fn().mockResolvedValue(microphone.stream);
    const controller = new RealtimeSessionController(
      {
        onStatus: vi.fn(),
        onPartial: vi.fn(),
        onCommitted: vi.fn(),
        onError: vi.fn(),
        onSourceLevel: (kind, level) => sourceLevels.push({ kind, level }),
      },
      {
        requestCapability: vi.fn().mockResolvedValue(capability),
        mediaDevices: {
          getDisplayMedia,
          getUserMedia,
        },
        createAudioContext: () => audio.context,
        createWebSocket: () => socket,
        setTimer: vi.fn(),
        clearTimer: vi.fn(),
      },
    );

    await controller.start({ displayAudio: true, microphone: true });
    expect(getDisplayMedia).toHaveBeenCalledWith({
      video: true,
      audio: true,
      selfBrowserSurface: "exclude",
      surfaceSwitching: "include",
      systemAudio: "include",
      windowAudio: "system",
    });
    expect(getUserMedia).toHaveBeenCalledWith({
      audio: {
        channelCount: { ideal: 1 },
        echoCancellation: { ideal: true },
        noiseSuppression: { ideal: true },
        autoGainControl: { ideal: true },
      },
    });
    expect(audio.context.createMediaStreamDestination).toHaveBeenCalledTimes(1);
    expect(audio.context.createMediaStreamSource).toHaveBeenCalledTimes(3);
    expect(audio.context.createAnalyser).toHaveBeenCalledTimes(2);
    expect(audio.context.createGain).toHaveBeenCalledTimes(3);
    expect(audio.gains[0].gain.value).toBe(0.35);
    expect(audio.gains[1].gain.value).toBe(1);
    expect(audio.sources[0].connect).toHaveBeenCalledWith(audio.analysers[0]);
    expect(audio.sources[1].connect).toHaveBeenCalledWith(audio.analysers[1]);
    expect(audio.analysers[0].connect).toHaveBeenCalledWith(audio.gains[0]);
    expect(audio.analysers[1].connect).toHaveBeenCalledWith(audio.gains[1]);
    expect(audio.gains[0].connect).toHaveBeenCalledWith(audio.destination);
    expect(audio.gains[1].connect).toHaveBeenCalledWith(audio.destination);

    audio.analyserInputs[0].fill(0.2);
    audio.analyserInputs[1].fill(0.02);
    audio.processor.onaudioprocess?.({
      inputBuffer: {
        getChannelData: () => new Float32Array(48),
      },
    } as AudioProcessingEvent);
    expect(sourceLevels).toEqual([
      { kind: "display", level: expect.closeTo(0.8) },
      { kind: "microphone", level: expect.closeTo(0.08) },
    ]);
    expect(audio.gains[0].gain.setTargetAtTime).toHaveBeenLastCalledWith(
      0.08,
      12,
      0.05,
    );

    audio.analyserInputs[1].fill(0.004);
    audio.processor.onaudioprocess?.({
      inputBuffer: {
        getChannelData: () => new Float32Array(48),
      },
    } as AudioProcessingEvent);
    expect(audio.gains[0].gain.setTargetAtTime).toHaveBeenLastCalledWith(
      0.35,
      12,
      0.05,
    );

    controller.dispose();
    expect(sourceLevels.slice(-2)).toEqual([
      { kind: "display", level: 0 },
      { kind: "microphone", level: 0 },
    ]);
    expect(display.stop).toHaveBeenCalled();
    expect(microphone.stop).toHaveBeenCalled();
  });

  it("reports unsupported browser capture before issuing a capability", async () => {
    const requestCapability = vi.fn().mockResolvedValue(capability);
    const errors: string[] = [];
    const statuses: RealtimeSessionStatus[] = [];
    const controller = new RealtimeSessionController(
      {
        onStatus: (status) => statuses.push(status),
        onPartial: vi.fn(),
        onCommitted: vi.fn(),
        onError: (message) => errors.push(message),
      },
      {
        requestCapability,
        mediaDevices: {},
      },
    );

    await controller.start({ displayAudio: true, microphone: false });

    expect(requestCapability).not.toHaveBeenCalled();
    expect(errors.at(-1)).toBe(
      "Этот браузер не поддерживает захват звука вкладки или экрана.",
    );
    expect(statuses.at(-1)).toBe("ready");
    expect(controller.active).toBe(false);
  });
});
