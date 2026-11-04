import { validSegmentMetadata, type RealtimeSegmentMetadata } from "./realtimeTranscript";

export type RealtimeCapability = {
  provider?: "elevenlabs" | "yandex";
  websocket_url: string;
  expires_in_seconds: number;
  model_id: string;
  audio_format: "pcm_16000";
  commit_strategy: "vad";
};

export type RealtimeWord = {text: string; start_seconds: number; end_seconds: number};
export type RealtimeTranscriptEvent =
  | { kind: "session_started" }
  | { kind: "partial"; text: string; words?: RealtimeWord[] }
  | { kind: "committed"; text: string; metadata?: RealtimeSegmentMetadata; words?: RealtimeWord[]; timestampUpdate?: boolean }
  | { kind: "error"; code: string }
  | { kind: "ignored" };

const REALTIME_HOST = "api.elevenlabs.io";
const REALTIME_PATH = "/v1/speech-to-text/realtime";
const REALTIME_QUERY_KEYS = new Set([
  "audio_format",
  "commit_strategy",
  "include_timestamps",
  "language_code",
  "model_id",
  "token",
]);
const REALTIME_ERROR_EVENTS = new Set([
  "auth_error",
  "chunk_size_exceeded",
  "commit_throttled",
  "error",
  "input_error",
  "insufficient_audio_activity",
  "queue_overflow",
  "quota_exceeded",
  "rate_limited",
  "resource_exhausted",
  "session_time_limit_exceeded",
  "transcriber_error",
  "unaccepted_terms",
]);

export function parseRealtimeCapability(value: unknown): RealtimeCapability {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Сервер вернул некорректную realtime-конфигурацию.");
  }
  const candidate = value as Record<string, unknown>;
  if (
    typeof candidate.model_id !== "string" ||
    !candidate.model_id ||
    candidate.model_id.length > 120 ||
    candidate.audio_format !== "pcm_16000" ||
    candidate.commit_strategy !== "vad" ||
    !Number.isInteger(candidate.expires_in_seconds) ||
    (candidate.expires_in_seconds as number) < 1 ||
    (candidate.expires_in_seconds as number) > 900 ||
    typeof candidate.websocket_url !== "string"
  ) {
    throw new Error("Сервер вернул некорректную realtime-конфигурацию.");
  }
  let url: URL;
  try {
    url = new URL(candidate.websocket_url);
  } catch {
    throw new Error("Сервер вернул небезопасный realtime-адрес.");
  }
  const provider = candidate.provider === "yandex" ? "yandex" : "elevenlabs";
  const isElevenLabs =
    provider === "elevenlabs" &&
    url.protocol === "wss:" &&
    url.hostname === REALTIME_HOST &&
    !url.port &&
    url.pathname === REALTIME_PATH;
  const expectedLocalProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const isYandexRelay =
    provider === "yandex" &&
    url.protocol === expectedLocalProtocol &&
    url.host === window.location.host &&
    url.pathname === "/api/realtime/yandex";
  if (
    (!isElevenLabs && !isYandexRelay) ||
    Boolean(url.username) ||
    Boolean(url.password) ||
    Boolean(url.hash)
  ) {
    throw new Error("Сервер вернул небезопасный realtime-адрес.");
  }
  const queryKeys = [...new Set(url.searchParams.keys())];
  if (isYandexRelay) {
    const capabilityValues = url.searchParams.getAll("capability");
    if (
      queryKeys.length !== 1 ||
      queryKeys[0] !== "capability" ||
      capabilityValues.length !== 1 ||
      !capabilityValues[0] ||
      capabilityValues[0].length > 1600 ||
      capabilityValues[0] !== capabilityValues[0].trim()
    ) {
      throw new Error("Сервер вернул небезопасный realtime-адрес.");
    }
    return { ...(candidate as Omit<RealtimeCapability, "provider">), provider };
  }
  const tokenValues = url.searchParams.getAll("token");
  const token = tokenValues[0] ?? "";
  const languageValues = url.searchParams.getAll("language_code");
  if (
    queryKeys.some((key) => !REALTIME_QUERY_KEYS.has(key)) ||
    tokenValues.length !== 1 ||
    !token ||
    token.length > 4096 ||
    token !== token.trim() ||
    [...token].some((character) => character.charCodeAt(0) < 33) ||
    url.searchParams.getAll("model_id").length !== 1 ||
    url.searchParams.get("model_id") !== candidate.model_id ||
    url.searchParams.getAll("audio_format").length !== 1 ||
    url.searchParams.get("audio_format") !== candidate.audio_format ||
    url.searchParams.getAll("commit_strategy").length !== 1 ||
    url.searchParams.get("commit_strategy") !== candidate.commit_strategy ||
    languageValues.length > 1 ||
    url.searchParams.getAll("include_timestamps").length > 1 ||
    (url.searchParams.has("include_timestamps") && url.searchParams.get("include_timestamps") !== "true") ||
    (languageValues.length === 1 &&
      !/^[a-z]{2,3}$/i.test(languageValues[0]))
  ) {
    throw new Error("Сервер вернул небезопасный realtime-адрес.");
  }
  return candidate as RealtimeCapability;
}

function scalarText(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

export function parseRealtimeEvent(value: unknown): RealtimeTranscriptEvent {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { kind: "ignored" };
  }
  const data = value as Record<string, unknown>;
  const eventType = scalarText(
    data.message_type ?? data.type ?? data.event ?? data.status,
  ).toLowerCase();
  if (eventType.includes("session_started")) {
    return { kind: "session_started" };
  }
  if (
    REALTIME_ERROR_EVENTS.has(eventType) ||
    eventType.includes("error") ||
    data.error ||
    data.error_code
  ) {
    return {
      kind: "error",
      code:
        scalarText(data.error_code ?? data.code ?? data.error) ||
        eventType ||
        "realtime_error",
    };
  }
  const text = scalarText(
    data.text ??
      data.transcript ??
      data.partial_transcript ??
      data.committed_transcript ??
      data.final_transcript,
  );
  if (!text) return { kind: "ignored" };
  const words = realtimeWords(data.words);
  const wordPayload = words ? {words} : {};
  const metadata = transcriptEventMetadata(data, words);
  if (eventType.includes("commit")) {
    return { kind: "committed", text, ...wordPayload, ...(metadata ? { metadata } : {}), ...(eventType === "committed_transcript_with_timestamps" ? { timestampUpdate: true } : {}) };
  }
  if (eventType === "final_transcript") {
    return { kind: "partial", text, ...wordPayload };
  }
  if (eventType.includes("partial") || data.is_final === false) {
    return { kind: "partial", text, ...wordPayload };
  }
  if (data.is_final === true) {
    return { kind: "committed", text, ...wordPayload, ...(metadata ? { metadata } : {}) };
  }
  return { kind: "partial", text, ...wordPayload };
}

function realtimeWords(value: unknown): RealtimeWord[] | undefined {
  if (!Array.isArray(value) || value.length === 0 || value.length > 20000) return undefined;
  const result: RealtimeWord[] = [];
  let length = 0;
  for (const candidate of value) {
    if (!candidate || typeof candidate !== "object") return undefined;
    if (candidate.type === "spacing") continue;
    const {text, start, end} = candidate;
    if (typeof text !== "string" || !text || text.length > 20000 || typeof start !== "number" || typeof end !== "number"
      || !Number.isFinite(start) || !Number.isFinite(end) || start < 0 || start > end || end > 604800
      || (result.length > 0 && start < result[result.length-1].start_seconds)) return undefined;
    length += text.length;
    if (length > 500000) return undefined;
    result.push({text,start_seconds:start,end_seconds:end});
  }
  return result.length ? result : undefined;
}

function transcriptEventMetadata(data: Record<string, unknown>, words?: RealtimeWord[]): RealtimeSegmentMetadata | undefined {
  const index = data.final_index;
  const identity = typeof data.segment_id === "string" ? data.segment_id : Number.isInteger(index) && (index as number) >= 0 ? `index.${index}` : "timed";
  const metadata: RealtimeSegmentMetadata = { id: identity };
  let start = data.start_seconds, end = data.end_seconds;
  if (words?.length) { start ??= words[0].start_seconds; end ??= words[words.length - 1].end_seconds; }
  if (typeof start === "number" && typeof end === "number") {
    metadata.start_seconds = start;
    metadata.end_seconds = end;
  }
  if (Number.isInteger(data.speaker) && (data.speaker as number) >= 1) metadata.speaker = data.speaker as number;
  if (!validSegmentMetadata(metadata)) return undefined;
  return identity !== "timed" || metadata.start_seconds !== undefined ? metadata : undefined;
}

export function downsampleMono(
  input: Float32Array,
  inputRate: number,
  outputRate = 16_000,
) {
  if (!Number.isFinite(inputRate) || inputRate < outputRate) {
    throw new Error("Частота аудио не поддерживается realtime-клиентом.");
  }
  if (inputRate === outputRate) return input;
  const ratio = inputRate / outputRate;
  const result = new Float32Array(Math.round(input.length / ratio));
  let inputOffset = 0;
  for (let outputOffset = 0; outputOffset < result.length; outputOffset += 1) {
    const nextInputOffset = Math.round((outputOffset + 1) * ratio);
    let total = 0;
    let count = 0;
    for (
      let index = inputOffset;
      index < nextInputOffset && index < input.length;
      index += 1
    ) {
      total += input[index];
      count += 1;
    }
    result[outputOffset] = count ? total / count : 0;
    inputOffset = nextInputOffset;
  }
  return result;
}

export function floatToPcm16Base64(input: Float32Array) {
  const buffer = new ArrayBuffer(input.length * 2);
  const view = new DataView(buffer);
  for (let index = 0; index < input.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, input[index]));
    view.setInt16(
      index * 2,
      sample < 0 ? sample * 0x8000 : sample * 0x7fff,
      true,
    );
  }
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}

export function realtimeAudioMessage(audioBase64: string, commit = false) {
  return JSON.stringify({
    message_type: "input_audio_chunk",
    audio_base_64: audioBase64,
    sample_rate: 16_000,
    ...(commit ? { commit: true } : {}),
  });
}
