import {
  downsampleMono,
  floatToPcm16Base64,
  parseRealtimeCapability,
  parseRealtimeEvent,
  realtimeAudioMessage,
  type RealtimeCapability,
} from "./realtimeProtocol";
import type { RealtimeSegmentMetadata } from "./realtimeTranscript";
import { RealtimeSegmentStream } from "./realtimeSegmentStream";
import { newRealtimeClientSessionId } from "./realtimeDrafts";

export type RealtimeSourceOptions = {
  displayAudio: boolean;
  microphone: boolean;
  microphoneDeviceId?: string;
};

export type RealtimeSourceKind = "display" | "microphone";

export type RealtimeSessionStatus =
  | "ready"
  | "requesting_permission"
  | "connecting"
  | "reconnecting"
  | "connected"
  | "transcribing"
  | "stopping"
  | "stopped"
  | "closed";

type RealtimeSessionCallbacks = {
  onStatus: (status: RealtimeSessionStatus) => void;
  onPartial: (text: string) => void;
  onCommitted: (text: string, metadata?: RealtimeSegmentMetadata) => void;
  onError: (message: string) => void;
  onClearBoundaryPending?: (pending: boolean) => void;
  onInputLevel?: (level: number) => void;
  onSourceLevel?: (kind: RealtimeSourceKind, level: number) => void;
};

type AudioNodeLike = { disconnect: () => void };
type CapturedAudioSource = {
  kind: RealtimeSourceKind;
  stream: MediaStream;
};
type SourceMonitor = {
  kind: RealtimeSourceKind;
  analyser: AnalyserNode;
  samples: Float32Array;
  gain: GainNode;
};
type Attempt = {
  id: number;
  cancelled: boolean;
  cleanupDone: boolean;
  userStopRequested: boolean;
  mediaStreams: MediaStream[];
  audioContext: AudioContext | null;
  processor: ScriptProcessorNode | null;
  nodes: AudioNodeLike[];
  sourceMonitors: SourceMonitor[];
  displayDucked: boolean;
  websocket: WebSocket | null;
  capabilityAbort: AbortController | null;
  capabilityTimer: number | null;
  connectionTimer: number | null;
  sessionTimer: number | null;
  closeTimer: number | null;
  durationTimer: number | null;
  provider: "elevenlabs" | "yandex";
  stream: MediaStream | null;
  namespace: string;
  transport: number;
  reconnectTimer: number | null;
  reconnectAttempts: number;
  sessionReady: boolean;
  audioSeconds: number;
  replay: { audio: string; bytes: number; start: number; end: number }[];
  replayBytes: number;
  confirmedSeconds: number;
  lastSentSeconds: number;
  gapStart: number | null;
  gapSequence: number;
  clearBeforeSeconds: number | null;
  segmentStream: RealtimeSegmentStream | null;
};

type RealtimeSessionDependencies = {
  requestCapability: (signal: AbortSignal) => Promise<unknown>;
  mediaDevices?: Partial<
    Pick<MediaDevices, "getDisplayMedia" | "getUserMedia">
  >;
  createAudioContext?: () => AudioContext;
  createWebSocket?: (url: string) => WebSocket;
  setTimer?: (callback: () => void, milliseconds: number) => number;
  clearTimer?: (timer: number) => void;
};

type DisplayAudioCaptureOptions = DisplayMediaStreamOptions & {
  selfBrowserSurface?: "include" | "exclude";
  surfaceSwitching?: "include" | "exclude";
  systemAudio?: "include" | "exclude";
  windowAudio?: "exclude" | "window" | "system";
};

export const DISPLAY_AUDIO_CAPTURE_OPTIONS: DisplayAudioCaptureOptions = {
  video: true,
  audio: true,
  selfBrowserSurface: "exclude",
  surfaceSwitching: "include",
  systemAudio: "include",
  windowAudio: "system",
};

const PERMISSION_ERRORS = new Set([
  "NotAllowedError",
  "PermissionDeniedError",
  "AbortError",
]);
const CONNECTION_TIMEOUT_MS = 10_000;
const SESSION_START_TIMEOUT_MS = 10_000;
const CAPABILITY_TIMEOUT_MS = 25_000;
const FINAL_COMMIT_GRACE_MS = 2_000;
const YANDEX_SESSION_SAFE_DURATION_MS = 295_000;
const AUDIO_PROCESSOR_BUFFER_SIZE = 8_192;
const MAX_WEBSOCKET_BUFFERED_BYTES = 512 * 1024;
const MAX_REPLAY_BYTES = 16_000 * 2 * 10;
const RECONNECT_DELAYS_MS = [1000, 2000, 4000];
const MIXED_DISPLAY_GAIN = 0.35;
const MIXED_DISPLAY_DUCKED_GAIN = 0.08;
const MIXED_MICROPHONE_GAIN = 1;
const MICROPHONE_DUCKING_ACTIVATE_LEVEL = 0.05;
const MICROPHONE_DUCKING_RELEASE_LEVEL = 0.025;
const SOURCE_ANALYSER_FFT_SIZE = 2_048;
const DUCKING_TIME_CONSTANT_SECONDS = 0.05;

function stopStream(stream: MediaStream) {
  stream.getTracks().forEach((track) => track.stop());
}

function safeDisconnect(node: AudioNodeLike | null) {
  try {
    node?.disconnect();
  } catch {
    // Already disconnected.
  }
}

function normalizedInputLevel(input: Float32Array) {
  if (input.length === 0) return 0;
  let squareTotal = 0;
  for (const sample of input) squareTotal += sample * sample;
  const rms = Math.sqrt(squareTotal / input.length);
  return Math.min(1, rms * 4);
}

function microphoneConstraints(deviceId?: string): MediaTrackConstraints {
  return {
    ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
    channelCount: { ideal: 1 },
    echoCancellation: { ideal: true },
    noiseSuppression: { ideal: true },
    autoGainControl: { ideal: true },
  };
}

export function realtimeProviderErrorMessage(
  code: string,
  provider: "elevenlabs" | "yandex" = "elevenlabs",
) {
  const normalized = code.toLowerCase();
  const providerName = provider === "yandex" ? "Yandex SpeechKit" : "ElevenLabs";
  if (normalized.includes("session_time_limit")) {
    return "Достигнута максимальная длительность одной realtime-сессии. Сохраните текст и начните новую сессию.";
  }
  if (
    normalized.includes("rate_limited") ||
    normalized.includes("commit_throttled")
  ) {
    return `${providerName} временно ограничил частоту realtime-запросов. Повторите запуск позже.`;
  }
  if (
    normalized.includes("quota") ||
    normalized.includes("resource_exhausted")
  ) {
    return `Квота или доступный баланс ${providerName} исчерпаны.`;
  }
  if (
    normalized.includes("auth") ||
    normalized.includes("token") ||
    normalized.includes("unaccepted_terms")
  ) {
    return "Одноразовый realtime-доступ отклонён. Запустите новую сессию.";
  }
  if (normalized.includes("queue_overflow")) {
    return `Очередь ${providerName} переполнена. Проверьте сеть и начните новую сессию.`;
  }
  if (normalized.includes("insufficient_audio_activity")) {
    return `${providerName} не обнаружил достаточной речевой активности. Проверьте выбранный источник и уровень сигнала.`;
  }
  if (
    normalized.includes("audio") ||
    normalized.includes("chunk") ||
    normalized.includes("input_error")
  ) {
    return `${providerName} отклонил аудиопоток. Выберите источник и начните заново.`;
  }
  return "Realtime-сессия завершилась ошибкой. Начните новую сессию.";
}

export class RealtimeSessionController {
  private generation = 0;
  private current: Attempt | null = null;
  private readonly callbacks: RealtimeSessionCallbacks;
  private readonly deps: Required<RealtimeSessionDependencies>;

  constructor(
    callbacks: RealtimeSessionCallbacks,
    dependencies: RealtimeSessionDependencies,
  ) {
    this.callbacks = callbacks;
    this.deps = {
      requestCapability: dependencies.requestCapability,
      mediaDevices: dependencies.mediaDevices ?? navigator.mediaDevices,
      createAudioContext:
        dependencies.createAudioContext ?? (() => new AudioContext()),
      createWebSocket:
        dependencies.createWebSocket ?? ((url) => new WebSocket(url)),
      setTimer:
        dependencies.setTimer ??
        ((callback, milliseconds) =>
          window.setTimeout(callback, milliseconds)),
      clearTimer:
        dependencies.clearTimer ?? ((timer) => window.clearTimeout(timer)),
    };
  }

  get active() {
    return Boolean(this.current && !this.current.cleanupDone);
  }

  async start(options: RealtimeSourceOptions) {
    if (this.active) return;
    if (!options.displayAudio && !options.microphone) {
      this.callbacks.onError("Выберите хотя бы один источник аудио.");
      return;
    }
    const attempt: Attempt = {
      id: ++this.generation,
      cancelled: false,
      cleanupDone: false,
      userStopRequested: false,
      mediaStreams: [],
      audioContext: null,
      processor: null,
      nodes: [],
      sourceMonitors: [],
      displayDucked: false,
      websocket: null,
      capabilityAbort: null,
      capabilityTimer: null,
      connectionTimer: null,
      sessionTimer: null,
      closeTimer: null,
      durationTimer: null,
      provider: "elevenlabs",
      stream: null,
      namespace: newRealtimeClientSessionId(),
      transport: 0,
      reconnectTimer: null,
      reconnectAttempts: 0,
      sessionReady: false,
      audioSeconds: 0,
      replay: [],
      replayBytes: 0,
      confirmedSeconds: 0,
      lastSentSeconds: 0,
      gapStart: null,
      gapSequence: 0,
      clearBeforeSeconds: null,
      segmentStream: null,
    };
    this.current = attempt;
    this.callbacks.onError("");
    this.callbacks.onPartial("");
    this.callbacks.onStatus("requesting_permission");
    try {
      const stream = await this.capture(attempt, options);
      attempt.stream = stream;
      this.assertActive(attempt);
      if (!attempt.audioContext) {
        attempt.audioContext = this.deps.createAudioContext();
      }
      await attempt.audioContext.resume();
      this.assertActive(attempt);

      this.callbacks.onStatus("connecting");
      const capabilityAbort = new AbortController();
      attempt.capabilityAbort = capabilityAbort;
      let capabilityTimedOut = false;
      attempt.capabilityTimer = this.deps.setTimer(() => {
        attempt.capabilityTimer = null;
        if (!this.owns(attempt) || attempt.cancelled) return;
        capabilityTimedOut = true;
        capabilityAbort.abort();
      }, CAPABILITY_TIMEOUT_MS);
      let capabilityValue: unknown;
      try {
        capabilityValue = await this.deps.requestCapability(
          capabilityAbort.signal,
        );
      } catch (error) {
        if (capabilityTimedOut) {
          throw new Error(
            "Studio API не подготовил realtime-доступ за 25 секунд. Проверьте сеть и начните новую сессию.",
            { cause: error },
          );
        }
        throw error;
      } finally {
        this.clearCapabilityRequest(attempt, false);
      }
      const capability = parseRealtimeCapability(
        capabilityValue,
      );
      attempt.provider = capability.provider ?? "elevenlabs";
      this.assertActive(attempt);
      this.connect(attempt, capability, stream);
    } catch (error) {
      this.handleStartFailure(attempt, error);
    }
  }

  clearTranscript() {
    const attempt = this.current;
    if (!attempt || attempt.cleanupDone) return;
    attempt.clearBeforeSeconds = attempt.audioSeconds;
    attempt.segmentStream?.clearBefore(attempt.clearBeforeSeconds);
    this.callbacks.onClearBoundaryPending?.(attempt.segmentStream?.clearBoundaryPending ?? false);
    this.callbacks.onPartial("");
  }

  stop() {
    const attempt = this.current;
    if (!attempt || attempt.cleanupDone) {
      this.callbacks.onStatus("stopped");
      return;
    }
    if (attempt.userStopRequested) return;
    attempt.cancelled = true;
    attempt.userStopRequested = true;
    this.clearReconnectTimer(attempt);
    this.clearCapabilityRequest(attempt);
    this.callbacks.onStatus("stopping");
    this.releaseMedia(attempt);
    const websocket = attempt.websocket;
    if (websocket?.readyState === WebSocket.OPEN) {
      try {
        websocket.send(realtimeAudioMessage("", true));
      } catch {
        // Closing below is still deterministic.
      }
      attempt.closeTimer = this.deps.setTimer(() => {
        this.closeSocket(attempt);
        this.finish(attempt, "stopped");
      }, FINAL_COMMIT_GRACE_MS);
      return;
    }
    this.closeSocket(attempt);
    this.finish(attempt, "stopped");
  }

  dispose() {
    const attempt = this.current;
    if (!attempt) return;
    attempt.cancelled = true;
    attempt.userStopRequested = true;
    this.closeSocket(attempt);
    this.finish(attempt, "stopped", false);
  }

  private owns(attempt: Attempt) {
    return this.current?.id === attempt.id;
  }

  private assertActive(attempt: Attempt) {
    if (!this.owns(attempt) || attempt.cancelled || attempt.cleanupDone) {
      throw new Error("STALE_REALTIME_ATTEMPT");
    }
  }

  private async capture(
    attempt: Attempt,
    options: RealtimeSourceOptions,
  ) {
    const sources: CapturedAudioSource[] = [];
    const register = (
      kind: CapturedAudioSource["kind"],
      stream: MediaStream,
    ) => {
      if (!this.owns(attempt) || attempt.cancelled) {
        stopStream(stream);
        throw new Error("STALE_REALTIME_ATTEMPT");
      }
      sources.push({ kind, stream });
      attempt.mediaStreams.push(stream);
      stream.getAudioTracks().forEach((track) => {
        track.addEventListener(
          "ended",
          () => {
            if (!this.owns(attempt) || attempt.cancelled) return;
            this.callbacks.onError(
              "Источник аудио остановлен браузером или отключён.",
            );
            this.stop();
          },
          { once: true },
        );
      });
      return stream;
    };
    try {
      if (options.displayAudio) {
        const getDisplayMedia = this.deps.mediaDevices.getDisplayMedia;
        if (typeof getDisplayMedia !== "function") {
          throw new Error(
            "Этот браузер не поддерживает захват звука вкладки или экрана.",
          );
        }
        const display = register(
          "display",
          await getDisplayMedia.call(
            this.deps.mediaDevices,
            DISPLAY_AUDIO_CAPTURE_OPTIONS,
          ),
        );
        if (display.getAudioTracks().length === 0) {
          throw new Error(
            "Браузер не передал звук выбранной вкладки или экрана. Включите передачу аудио в окне выбора.",
          );
        }
      }
      if (options.microphone) {
        const getUserMedia = this.deps.mediaDevices.getUserMedia;
        if (typeof getUserMedia !== "function") {
          throw new Error(
            "Этот браузер не поддерживает захват микрофона или аудиовхода.",
          );
        }
        register(
          "microphone",
          await getUserMedia.call(this.deps.mediaDevices, {
            audio: microphoneConstraints(options.microphoneDeviceId),
          }),
        );
      }
      this.assertActive(attempt);
      if (sources.length === 1) return sources[0].stream;

      const context = this.deps.createAudioContext();
      attempt.audioContext = context;
      const destination = context.createMediaStreamDestination();
      attempt.nodes.push(destination);
      for (const { kind, stream } of sources) {
        const source = context.createMediaStreamSource(stream);
        const analyser = context.createAnalyser();
        analyser.fftSize = SOURCE_ANALYSER_FFT_SIZE;
        const gain = context.createGain();
        gain.gain.value =
          kind === "microphone"
            ? MIXED_MICROPHONE_GAIN
            : MIXED_DISPLAY_GAIN;
        source.connect(analyser);
        analyser.connect(gain);
        gain.connect(destination);
        attempt.nodes.push(source, analyser, gain);
        attempt.sourceMonitors.push({
          kind,
          analyser,
          samples: new Float32Array(analyser.fftSize),
          gain,
        });
      }
      return destination.stream;
    } catch (error) {
      sources.forEach(({ stream }) => stopStream(stream));
      throw error;
    }
  }

  private connect(
    attempt: Attempt,
    capability: RealtimeCapability,
    stream: MediaStream,
  ) {
    this.assertActive(attempt);
    const context = attempt.audioContext;
    if (!context) throw new Error("AudioContext не подготовлен.");
    if (!attempt.processor) {
    const source = context.createMediaStreamSource(stream);
    const processor = context.createScriptProcessor(
      AUDIO_PROCESSOR_BUFFER_SIZE,
      1,
      1,
    );
    const silentOutput = context.createGain();
    silentOutput.gain.value = 0;
    source.connect(processor);
    processor.connect(silentOutput);
    silentOutput.connect(context.destination);
    attempt.nodes.push(source, silentOutput);
    attempt.processor = processor;
    processor.onaudioprocess = (event) => {
      if (!this.owns(attempt) || attempt.cancelled) return;
      this.updateSourceLevels(attempt, context);
      const mono = event.inputBuffer.getChannelData(0);
      this.callbacks.onInputLevel?.(normalizedInputLevel(mono));
      const downsampled = downsampleMono(mono, context.sampleRate);
      const frame = { audio: floatToPcm16Base64(downsampled), bytes: downsampled.length * 2, start: attempt.audioSeconds, end: attempt.audioSeconds + downsampled.length / 16000 };
      attempt.audioSeconds = frame.end;
      attempt.replay.push(frame);
      attempt.replayBytes += frame.bytes;
      while (attempt.replayBytes > MAX_REPLAY_BYTES && attempt.replay.length) {
        const dropped = attempt.replay.shift()!;
        attempt.replayBytes -= dropped.bytes;
        attempt.gapStart ??= dropped.start;
        this.emitGap(attempt, attempt.gapStart, dropped.end, "Аудио не передано: обрыв превысил доступный буфер", `buffer.${attempt.transport}`);
      }
      this.flushReplay(attempt);
    };
    }

    const transport = ++attempt.transport;
    const offset = attempt.replay[0]?.start ?? attempt.audioSeconds;
    // Each provider clock starts at zero. Previous transport loss is already
    // reported; a failed new handshake must not report that same interval again.
    attempt.confirmedSeconds = offset;
    attempt.lastSentSeconds = offset;
    const segments = new RealtimeSegmentStream(`${attempt.namespace}.${transport}`, offset, attempt.namespace);
    if (attempt.clearBeforeSeconds !== null) segments.clearBefore(attempt.clearBeforeSeconds);
    attempt.segmentStream = segments;
    this.callbacks.onClearBoundaryPending?.(segments.clearBoundaryPending);
    attempt.sessionReady = false;
    let websocket: WebSocket;
    try {
      websocket = this.deps.createWebSocket(capability.websocket_url);
    } catch (error) {
      throw new Error(
        "Браузер не смог открыть защищённое realtime-соединение. Проверьте сетевые ограничения и начните новую сессию.",
        { cause: error },
      );
    }
    attempt.websocket = websocket;
    const ownsTransport = () => this.owns(attempt) && !attempt.cleanupDone && attempt.websocket === websocket && attempt.transport === transport;
    attempt.connectionTimer = this.deps.setTimer(() => {
      attempt.connectionTimer = null;
      if (
        !ownsTransport() ||
        attempt.cleanupDone ||
        websocket.readyState !== WebSocket.CONNECTING
      ) {
        return;
      }
      this.reconnect(attempt);
    }, CONNECTION_TIMEOUT_MS);
    websocket.onopen = () => {
      if (!ownsTransport() || attempt.cancelled) return;
      this.clearConnectionTimer(attempt);
      this.callbacks.onStatus("connected");
      attempt.sessionTimer = this.deps.setTimer(() => {
        attempt.sessionTimer = null;
        if (!ownsTransport()) return;
        this.reconnect(attempt);
      }, SESSION_START_TIMEOUT_MS);
    };
    websocket.onmessage = (message) => {
      if (!ownsTransport()) return;
      let parsed: unknown;
      try {
        parsed = JSON.parse(String(message.data));
      } catch {
        return;
      }
      const event = parseRealtimeEvent(parsed);
      if (event.kind === "session_started") {
        this.clearSessionTimer(attempt);
        this.startProviderDurationTimer(attempt);
        this.callbacks.onStatus("transcribing");
        attempt.sessionReady = true;
        attempt.reconnectAttempts = 0;
        attempt.gapStart = null;
        this.callbacks.onError("");
        this.flushReplay(attempt);
      } else if (event.kind === "partial") {
        this.clearSessionTimer(attempt);
        this.callbacks.onStatus("transcribing");
        this.callbacks.onPartial(segments.partial(event));
      } else if (event.kind === "committed") {
        this.clearSessionTimer(attempt);
        this.callbacks.onStatus("transcribing");
        const commit = segments.committed(event);
        this.callbacks.onClearBoundaryPending?.(segments.clearBoundaryPending);
        if (commit) {
          if (!commit.replaces && !event.timestampUpdate) this.callbacks.onPartial("");
          if (commit.metadata.end_seconds !== undefined) attempt.confirmedSeconds = Math.max(attempt.confirmedSeconds, commit.metadata.end_seconds);
          this.callbacks.onCommitted(commit.text, commit.metadata);
        }
      } else if (event.kind === "error") {
        if (attempt.userStopRequested) return;
        this.callbacks.onError(
          realtimeProviderErrorMessage(event.code, attempt.provider),
        );
        this.closeSocket(attempt, "Ошибка провайдера");
        this.finish(attempt, "closed");
      }
    };
    websocket.onerror = () => {
      if (!ownsTransport() || attempt.userStopRequested) return;
      this.reconnect(attempt);
    };
    websocket.onclose = () => {
      if (!ownsTransport()) return;
      if (attempt.userStopRequested) this.finish(attempt, "stopped");
      else this.reconnect(attempt);
    };
  }

  private emitGap(attempt: Attempt, start: number, end: number, reason: string, identity?: string) {
    if (attempt.clearBeforeSeconds !== null) start = Math.max(start, attempt.clearBeforeSeconds);
    if (end <= start) return;
    this.callbacks.onCommitted(`[Разрыв аудио ${start.toFixed(1)}–${end.toFixed(1)} сек: ${reason}]`, {
      id: `${attempt.namespace}.gap.${identity ?? attempt.gapSequence++}`, session_id: attempt.namespace, start_seconds: start, end_seconds: end, gap: true,
    });
  }

  private flushReplay(attempt: Attempt) {
    const socket = attempt.websocket;
    if (!socket || socket.readyState !== WebSocket.OPEN || !attempt.sessionReady || attempt.cancelled) return;
    while (attempt.replay.length) {
      if (socket.bufferedAmount > MAX_WEBSOCKET_BUFFERED_BYTES) { this.reconnect(attempt); return; }
      const frame = attempt.replay[0];
      try { socket.send(realtimeAudioMessage(frame.audio)); }
      catch { this.reconnect(attempt); return; }
      attempt.replay.shift();
      attempt.replayBytes -= frame.bytes;
      attempt.lastSentSeconds = frame.end;
    }
  }

  private reconnect(attempt: Attempt, planned = false) {
    if (!this.owns(attempt) || attempt.cancelled || attempt.cleanupDone || attempt.reconnectTimer !== null) return;
    if (attempt.lastSentSeconds > attempt.confirmedSeconds) {
      this.emitGap(attempt, attempt.confirmedSeconds, attempt.lastSentSeconds, "Переданное аудио не полностью подтверждено провайдером");
    }
    this.closeSocket(attempt, "Переподключение");
    this.callbacks.onStatus("reconnecting");
    const delay = planned ? 0 : RECONNECT_DELAYS_MS[attempt.reconnectAttempts++];
    if (delay === undefined) {
      if (attempt.replay.length) this.emitGap(attempt, attempt.replay[0].start, attempt.audioSeconds, "Соединение не восстановлено");
      this.callbacks.onError("Не удалось восстановить Live после трёх попыток. Текст сохранён; проверьте сеть и начните снова.");
      this.finish(attempt, "closed");
      return;
    }
    attempt.reconnectTimer = this.deps.setTimer(() => {
      attempt.reconnectTimer = null;
      void this.reconnectTransport(attempt);
    }, delay);
  }

  private async reconnectTransport(attempt: Attempt) {
    if (!this.owns(attempt) || attempt.cancelled || !attempt.stream) return;
    const abort = new AbortController();
    attempt.capabilityAbort = abort;
    attempt.capabilityTimer = this.deps.setTimer(() => abort.abort(), CAPABILITY_TIMEOUT_MS);
    try {
      const value = await this.deps.requestCapability(abort.signal);
      this.assertActive(attempt);
      const capability = parseRealtimeCapability(value);
      if ((capability.provider ?? "elevenlabs") !== attempt.provider) throw new Error("Провайдер Live изменился во время восстановления.");
      this.clearCapabilityRequest(attempt, false);
      this.connect(attempt, capability, attempt.stream);
    } catch (error) {
      this.clearCapabilityRequest(attempt);
      if (!this.owns(attempt) || attempt.cancelled) return;
      const cause = error instanceof Error ? error.cause : null;
      const status = cause && typeof cause === "object" && "status" in cause ? cause.status : null;
      if ([401, 403, 422, 429].includes(status as number)) {
        this.callbacks.onError(error instanceof Error ? error.message : "Live-доступ отклонён. Проверьте настройки.");
        this.finish(attempt, "closed");
      } else this.reconnect(attempt);
    }
  }

  private clearReconnectTimer(attempt: Attempt) {
    if (attempt.reconnectTimer !== null) this.deps.clearTimer(attempt.reconnectTimer);
    attempt.reconnectTimer = null;
  }

  private updateSourceLevels(attempt: Attempt, context: AudioContext) {
    if (attempt.sourceMonitors.length === 0) return;
    let microphoneLevel = 0;
    let displayMonitor: SourceMonitor | undefined;
    for (const monitor of attempt.sourceMonitors) {
      monitor.analyser.getFloatTimeDomainData(monitor.samples);
      const level = normalizedInputLevel(monitor.samples);
      this.callbacks.onSourceLevel?.(monitor.kind, level);
      if (monitor.kind === "microphone") microphoneLevel = level;
      else displayMonitor = monitor;
    }
    if (!displayMonitor) return;
    const shouldDuck = attempt.displayDucked
      ? microphoneLevel > MICROPHONE_DUCKING_RELEASE_LEVEL
      : microphoneLevel >= MICROPHONE_DUCKING_ACTIVATE_LEVEL;
    if (shouldDuck === attempt.displayDucked) return;
    attempt.displayDucked = shouldDuck;
    displayMonitor.gain.gain.setTargetAtTime(
      shouldDuck ? MIXED_DISPLAY_DUCKED_GAIN : MIXED_DISPLAY_GAIN,
      context.currentTime,
      DUCKING_TIME_CONSTANT_SECONDS,
    );
  }

  private handleStartFailure(attempt: Attempt, error: unknown) {
    if (!this.owns(attempt)) {
      this.releaseMedia(attempt);
      return;
    }
    const stale = error instanceof Error && error.message === "STALE_REALTIME_ATTEMPT";
    if (!stale) {
      const errorName = error instanceof DOMException ? error.name : "";
      this.callbacks.onError(
        PERMISSION_ERRORS.has(errorName)
          ? "Разрешение на захват аудио отменено или отклонено. Выберите источник и начните снова."
          : error instanceof Error
            ? error.message
            : "Не удалось запустить realtime-сессию.",
      );
    }
    this.finish(attempt, attempt.userStopRequested ? "stopped" : "ready");
  }

  private releaseMedia(attempt: Attempt) {
    this.callbacks.onInputLevel?.(0);
    this.callbacks.onSourceLevel?.("display", 0);
    this.callbacks.onSourceLevel?.("microphone", 0);
    if (attempt.processor) {
      attempt.processor.onaudioprocess = null;
      safeDisconnect(attempt.processor);
      attempt.processor = null;
    }
    attempt.nodes.forEach(safeDisconnect);
    attempt.nodes = [];
    attempt.sourceMonitors = [];
    attempt.displayDucked = false;
    attempt.mediaStreams.forEach(stopStream);
    attempt.mediaStreams = [];
    const context = attempt.audioContext;
    attempt.audioContext = null;
    if (context && context.state !== "closed") {
      void context.close().catch(() => undefined);
    }
  }

  private closeSocket(attempt: Attempt, reason = "Остановлено пользователем") {
    this.clearConnectionTimer(attempt);
    this.clearSessionTimer(attempt);
    if (attempt.closeTimer !== null) {
      this.deps.clearTimer(attempt.closeTimer);
      attempt.closeTimer = null;
    }
    if (attempt.durationTimer !== null) {
      this.deps.clearTimer(attempt.durationTimer);
      attempt.durationTimer = null;
    }
    const websocket = attempt.websocket;
    attempt.websocket = null;
    if (
      websocket &&
      (websocket.readyState === WebSocket.OPEN ||
        websocket.readyState === WebSocket.CONNECTING)
    ) {
      try {
        websocket.close(1000, reason);
      } catch {
        // Browser is already closing it.
      }
    }
  }

  private clearConnectionTimer(attempt: Attempt) {
    if (attempt.connectionTimer === null) return;
    this.deps.clearTimer(attempt.connectionTimer);
    attempt.connectionTimer = null;
  }

  private clearSessionTimer(attempt: Attempt) {
    if (attempt.sessionTimer === null) return;
    this.deps.clearTimer(attempt.sessionTimer);
    attempt.sessionTimer = null;
  }

  private startProviderDurationTimer(attempt: Attempt) {
    if (attempt.provider !== "yandex" || attempt.durationTimer !== null) return;
    attempt.durationTimer = this.deps.setTimer(() => {
      attempt.durationTimer = null;
      if (!this.owns(attempt) || attempt.cleanupDone) return;
      this.callbacks.onError(
        "Yandex SpeechKit ограничивает соединение пятью минутами. Продолжаем ту же Live-сессию через новый доступ.",
      );
      const socket = attempt.websocket;
      // Keep capturing into the bounded replay buffer while the old transport
      // commits its tail. Sending new frames after commit loses that tail on rotation.
      attempt.sessionReady = false;
      if (socket?.readyState === WebSocket.OPEN) {
        try { socket.send(realtimeAudioMessage("", true)); } catch { /* reconnect below */ }
      }
      attempt.closeTimer = this.deps.setTimer(() => { attempt.closeTimer = null; this.reconnect(attempt, true); }, FINAL_COMMIT_GRACE_MS);
    }, YANDEX_SESSION_SAFE_DURATION_MS);
  }

  private clearCapabilityRequest(attempt: Attempt, abort = true) {
    if (attempt.capabilityTimer !== null) {
      this.deps.clearTimer(attempt.capabilityTimer);
      attempt.capabilityTimer = null;
    }
    const controller = attempt.capabilityAbort;
    attempt.capabilityAbort = null;
    if (abort && controller && !controller.signal.aborted) {
      controller.abort();
    }
  }

  private finish(
    attempt: Attempt,
    status: RealtimeSessionStatus,
    reportStatus = true,
  ) {
    if (attempt.cleanupDone) return;
    attempt.cleanupDone = true;
    this.callbacks.onClearBoundaryPending?.(false);
    this.clearReconnectTimer(attempt);
    attempt.replay = [];
    attempt.replayBytes = 0;
    this.clearCapabilityRequest(attempt);
    this.releaseMedia(attempt);
    this.closeSocket(attempt);
    if (this.owns(attempt)) {
      this.current = null;
      if (reportStatus) this.callbacks.onStatus(status);
    }
  }
}
