import { api } from "./apiClient";
import type { SttOperatingMode, SttProvider } from "./batchComposerModel";

export type SttModeCapability = {
  notes?: string[];
  mode: SttOperatingMode | "realtime";
  model: string;
  transport: "batch" | "deferred" | "websocket" | "grpc_relay";
  languages: ("ru" | "en" | "detect")[];
  diarization: boolean;
  dictionaries: boolean;
  file_constraints: {
    max_bytes: number | null;
    max_duration_seconds: number;
    audio_channels: number[];
  };
  health: {
    available: boolean;
    consecutive_failures: number;
    retry_after_seconds: number | null;
  };
};

export type SttProviderCapability = {
  provider: SttProvider;
  display_name: string;
  byok_enabled: boolean;
  modes: SttModeCapability[];
};

export type SttDictionaryEntryKind =
  | "term"
  | "surname"
  | "name"
  | "abbreviation";

export type SttDictionary = {
  id: string;
  name: string;
  active: true;
  entries: { kind: SttDictionaryEntryKind; value: string }[];
  updated_at: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function finiteNonNegative(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

export function parseSttProviderCatalog(value: unknown): SttProviderCapability[] | null {
  if (!isRecord(value) || !Array.isArray(value.providers)) return null;
  const result: SttProviderCapability[] = [];
  for (const rawProvider of value.providers) {
    if (!isRecord(rawProvider)) return null;
    const provider = rawProvider.provider;
    if (
      (provider !== "elevenlabs" && provider !== "yandex" && provider !== "tbank" && provider !== "mistral" && provider !== "gemini") ||
      typeof rawProvider.display_name !== "string" ||
      !rawProvider.display_name.trim() ||
      typeof rawProvider.byok_enabled !== "boolean" ||
      !Array.isArray(rawProvider.modes)
    ) {
      return null;
    }
    const modes: SttModeCapability[] = [];
    for (const rawMode of rawProvider.modes) {
      if (!isRecord(rawMode) || !isRecord(rawMode.file_constraints) || !isRecord(rawMode.health)) {
        return null;
      }
      const mode = rawMode.mode;
      const transport = rawMode.transport;
      const maxBytes = rawMode.file_constraints.max_bytes;
      const retryAfter = rawMode.health.retry_after_seconds;
      if (
        !["economic", "standard", "premium", "realtime"].includes(String(mode)) ||
        !["batch", "deferred", "websocket", "grpc_relay"].includes(String(transport)) ||
        typeof rawMode.model !== "string" ||
        !rawMode.model ||
        !Array.isArray(rawMode.languages) ||
        rawMode.languages.some((language) => !["ru", "en", "detect"].includes(String(language))) ||
        typeof rawMode.diarization !== "boolean" ||
        typeof rawMode.dictionaries !== "boolean" ||
        (rawMode.notes !== undefined && (!Array.isArray(rawMode.notes) || rawMode.notes.length > 10 || rawMode.notes.some((note) => typeof note !== "string" || note.length > 2000))) ||
        (maxBytes !== null && !finiteNonNegative(maxBytes)) ||
        !finiteNonNegative(rawMode.file_constraints.max_duration_seconds) ||
        !Array.isArray(rawMode.file_constraints.audio_channels) ||
        rawMode.file_constraints.audio_channels.some((channel) => !Number.isInteger(channel) || (channel as number) < 1) ||
        typeof rawMode.health.available !== "boolean" ||
        !Number.isInteger(rawMode.health.consecutive_failures) ||
        (rawMode.health.consecutive_failures as number) < 0 ||
        (retryAfter !== null && !finiteNonNegative(retryAfter))
      ) {
        return null;
      }
      modes.push({
        mode: mode as SttModeCapability["mode"],
        model: rawMode.model,
        transport: transport as SttModeCapability["transport"],
        languages: rawMode.languages as SttModeCapability["languages"],
        diarization: rawMode.diarization,
        dictionaries: rawMode.dictionaries,
        ...(rawMode.notes !== undefined ? { notes: rawMode.notes as string[] } : {}),
        file_constraints: {
          max_bytes: maxBytes as number | null,
          max_duration_seconds: rawMode.file_constraints.max_duration_seconds as number,
          audio_channels: rawMode.file_constraints.audio_channels as number[],
        },
        health: {
          available: rawMode.health.available,
          consecutive_failures: rawMode.health.consecutive_failures as number,
          retry_after_seconds: retryAfter as number | null,
        },
      });
    }
    if (
      modes.length === 0 ||
      new Set(modes.map((mode) => mode.mode)).size !== modes.length
    ) {
      return null;
    }
    result.push({
      provider,
      display_name: rawProvider.display_name,
      byok_enabled: rawProvider.byok_enabled,
      modes,
    });
  }
  if (
    result.length === 0 ||
    new Set(result.map((provider) => provider.provider)).size !== result.length
  ) {
    return null;
  }
  return result;
}

export async function requestSttProviderCatalog(signal?: AbortSignal) {
  const providers = parseSttProviderCatalog(await api<unknown>("/stt/providers", { signal }));
  if (!providers) throw new Error("invalid_stt_provider_catalog");
  return providers;
}

export function parseSttDictionaryCollection(value: unknown): SttDictionary[] | null {
  if (!isRecord(value) || !Array.isArray(value.dictionaries)) return null;
  const result: SttDictionary[] = [];
  for (const rawDictionary of value.dictionaries) {
    if (
      !isRecord(rawDictionary) ||
      typeof rawDictionary.id !== "string" ||
      !rawDictionary.id ||
      typeof rawDictionary.name !== "string" ||
      !rawDictionary.name.trim() ||
      rawDictionary.active !== true ||
      typeof rawDictionary.updated_at !== "string" ||
      !Array.isArray(rawDictionary.entries)
    ) {
      return null;
    }
    const entries: SttDictionary["entries"] = [];
    for (const rawEntry of rawDictionary.entries) {
      if (
        !isRecord(rawEntry) ||
        !["term", "surname", "name", "abbreviation"].includes(String(rawEntry.kind)) ||
        typeof rawEntry.value !== "string" ||
        !rawEntry.value.trim()
      ) {
        return null;
      }
      entries.push({
        kind: rawEntry.kind as SttDictionaryEntryKind,
        value: rawEntry.value,
      });
    }
    result.push({
      id: rawDictionary.id,
      name: rawDictionary.name,
      active: true,
      entries,
      updated_at: rawDictionary.updated_at,
    });
  }
  return result;
}

export async function requestSttDictionaries(signal?: AbortSignal) {
  const dictionaries = parseSttDictionaryCollection(
    await api<unknown>("/stt/dictionaries", { signal }),
  );
  if (!dictionaries) throw new Error("invalid_stt_dictionary_collection");
  return dictionaries;
}

export function sttModeLabel(mode: SttModeCapability["mode"]) {
  return {
    economic: "Экономичный",
    standard: "Стандартный",
    premium: "Премиальный",
    realtime: "Live",
  }[mode];
}

function effectiveModeSignature(mode: SttModeCapability) {
  return JSON.stringify({
    model: mode.model,
    transport: mode.transport,
    languages: [...mode.languages].sort(),
    diarization: mode.diarization,
    dictionaries: mode.dictionaries,
    max_bytes: mode.file_constraints.max_bytes,
    max_duration_seconds: mode.file_constraints.max_duration_seconds,
    audio_channels: [...mode.file_constraints.audio_channels].sort((a, b) => a - b),
  });
}

export function distinctBatchModes(modes: SttModeCapability[]) {
  const rank = { standard: 0, economic: 1, premium: 2 } as const;
  const representatives = new Map<string, SttModeCapability>();
  for (const mode of modes.filter((item) => item.mode !== "realtime")) {
    const signature = effectiveModeSignature(mode);
    const current = representatives.get(signature);
    if (
      !current ||
      (mode.health.available && !current.health.available) ||
      (mode.health.available === current.health.available &&
        rank[mode.mode as keyof typeof rank] <
          rank[current.mode as keyof typeof rank])
    ) {
      representatives.set(signature, mode);
    }
  }
  return [...representatives.values()].sort(
    (left, right) =>
      rank[left.mode as keyof typeof rank] - rank[right.mode as keyof typeof rank],
  );
}

export function sttModeExplanation(mode: SttModeCapability) {
  const durationMinutes = Math.floor(
    mode.file_constraints.max_duration_seconds / 60,
  );
  const features = [
    mode.diarization ? "разделение спикеров" : null,
    mode.dictionaries ? "пользовательские словари" : null,
  ].filter(Boolean);
  return `${mode.model} · обработка: ${
    mode.transport === "deferred" ? "в очереди провайдера" : "обычная"
  } · до ${durationMinutes} мин.${
    features.length ? ` · поддерживает ${features.join(" и ")}` : ""
  }`;
}
