import { audioSourceTitle } from "./audioOutputNaming";
import type { AudioVisual } from "./AudioWaveform";

export const LOCAL_AUDIO_MAX_FILES = 20;
export const LOCAL_AUDIO_MAX_INPUT_BYTES = 256 * 1024 * 1024;
export const LOCAL_AUDIO_MAX_DECODED_SAMPLES = 50_000_000;

export type LocalAudioOperationMode = "separate" | "concat";
export type LocalAudioChannelMode = "preserve" | "mixdown" | "left" | "right";

export type PcmAudio = {
  sampleRate: number;
  channels: Float32Array[];
};

export type LocalAudioOptions = {
  trimStartSeconds?: number;
  trimEndSeconds?: number | null;
  operationMode: LocalAudioOperationMode;
  channelMode: LocalAudioChannelMode;
  silenceEnabled: boolean;
  silenceThresholdDb: number;
  silenceMinimumSeconds: number;
  silenceKeepSeconds: number;
  title: string;
};

export type LocalAudioProgress = {
  stage: "reading" | "decoding" | "processing" | "encoding" | "completed";
  percent: number;
  filename: string | null;
};

export type LocalAudioResult = {
  blob: Blob;
  filename: string;
  inputDurationSeconds: number;
  outputDurationSeconds: number;
  visual?: AudioVisual;
};

function ensureActive(signal?: AbortSignal) {
  if (signal?.aborted) throw new DOMException("local_audio_aborted", "AbortError");
}

function safeTitle(value: string) {
  const sanitized = Array.from(value.trim(), (character) =>
    character.charCodeAt(0) <= 31 || '<>:"/\\|?*'.includes(character) ? "_" : character,
  ).join("");
  return sanitized
    .replace(/[. ]+$/g, "")
    .slice(0, 180);
}

function stem(name: string) {
  return safeTitle(audioSourceTitle(name)) || "Обработанное аудио";
}

function copyChannels(audio: PcmAudio, mode: LocalAudioChannelMode): Float32Array[] {
  if (audio.channels.length === 0 || audio.channels.some((channel) => channel.length !== audio.channels[0].length)) {
    throw new Error("local_audio_invalid_channels");
  }
  if (mode === "left") return [audio.channels[0].slice()];
  if (mode === "right") {
    if (audio.channels.length < 2) throw new Error("local_audio_right_channel_unavailable");
    return [audio.channels[1].slice()];
  }
  if (mode === "mixdown") {
    const output = new Float32Array(audio.channels[0].length);
    for (const channel of audio.channels) {
      for (let index = 0; index < output.length; index += 1) output[index] += channel[index] / audio.channels.length;
    }
    return [output];
  }
  return audio.channels.slice(0, 2).map((channel) => channel.slice());
}

function visitSilences(
  channels: Float32Array[],
  sampleRate: number,
  thresholdDb: number,
  minimumSeconds: number,
  visit: (start: number, end: number) => void,
) {
  const threshold = 10 ** (thresholdDb / 20);
  const minimumFrames = Math.max(1, Math.round(minimumSeconds * sampleRate));
  const length = channels[0]?.length ?? 0;
  let silentStart = -1;
  for (let frame = 0; frame <= length; frame += 1) {
    const silent = frame < length && channels.every((channel) => Math.abs(channel[frame]) < threshold);
    if (silent && silentStart < 0) silentStart = frame;
    if (!silent && silentStart >= 0) {
      const silentEnd = frame;
      const silentLength = silentEnd - silentStart;
      if (silentLength >= minimumFrames) visit(silentStart, silentEnd);
      silentStart = -1;
    }
  }
}

function retainedRanges(channels: Float32Array[], sampleRate: number, thresholdDb: number, minimumSeconds: number, keepSeconds: number) {
  const keepFrames = Math.max(0, Math.round(keepSeconds * sampleRate));
  const length = channels[0]?.length ?? 0;
  const ranges: [number, number][] = [];
  let cursor = 0;
  const push = (start: number, end: number) => { if (end > start) ranges.push([start, end]); };
  visitSilences(channels, sampleRate, thresholdDb, minimumSeconds, (start, end) => {
    if (end - start <= keepFrames) return;
    push(cursor, start + Math.ceil(keepFrames / 2));
    cursor = end - Math.floor(keepFrames / 2);
  });
  push(cursor, length);
  return ranges;
}

export function buildLocalAudioVisual(inputs: PcmAudio[], options: LocalAudioOptions): AudioVisual {
  const totalDuration = inputs.reduce((sum, input) => sum + input.channels[0].length / input.sampleRate, 0);
  let remaining = 512, removedTotal = 0, remainingPoints = 512, remainingDuration = totalDuration;
  const sources = inputs.map((input, position) => {
    const channels = copyChannels(input, options.channelMode);
    const duration = channels[0].length / input.sampleRate;
    const pointCount = Math.max(1, Math.min(channels[0].length, remainingPoints - (inputs.length - position - 1), Math.floor(remainingPoints * duration / remainingDuration)));
    remainingPoints -= pointCount; remainingDuration = Math.max(0.000001, remainingDuration - duration);
    const peaks = Array.from({ length: pointCount }, (_, point) => {
      let peak = 0;
      const start = Math.floor(point * channels[0].length / pointCount), end = Math.floor((point + 1) * channels[0].length / pointCount);
      for (let frame = start; frame < end; frame += 1) for (const channel of channels) peak = Math.max(peak, Math.abs(channel[frame]));
      return Math.min(1, peak);
    });
    const silences: AudioVisual["sources"][number]["silences"] = [];
    let count = 0;
    if (options.silenceEnabled) visitSilences(channels, input.sampleRate, options.silenceThresholdDb, options.silenceMinimumSeconds, (start, end) => {
      count += 1;
      const removed = Math.max(0, end - start - Math.round(options.silenceKeepSeconds * input.sampleRate)) / input.sampleRate;
      removedTotal += removed;
      if (remaining > 0) { silences.push({ start: start / input.sampleRate, end: end / input.sampleRate, removed_seconds: removed }); remaining -= 1; }
    });
    return { position, duration_seconds: duration, peaks, silences, silence_count: count, intervals_truncated: count > silences.length };
  });
  return { sources, removed_seconds: removedTotal };
}

function applySilence(
  channels: Float32Array[],
  sampleRate: number,
  options: LocalAudioOptions,
) {
  if (!options.silenceEnabled) return channels;
  const ranges = retainedRanges(
    channels,
    sampleRate,
    options.silenceThresholdDb,
    options.silenceMinimumSeconds,
    options.silenceKeepSeconds,
  );
  const length = ranges.reduce((total, [start, end]) => total + end - start, 0);
  return channels.map((channel) => {
    const output = new Float32Array(length);
    let offset = 0;
    for (const [start, end] of ranges) {
      output.set(channel.subarray(start, end), offset);
      offset += end - start;
    }
    return output;
  });
}

function concatenate(inputs: PcmAudio[], options: LocalAudioOptions): PcmAudio {
  if (inputs.length === 0) throw new Error("local_audio_no_inputs");
  const sampleRate = inputs[0].sampleRate;
  if (inputs.some((input) => input.sampleRate !== sampleRate)) throw new Error("local_audio_sample_rate_mismatch");
  const duration = inputs.reduce((sum, input) => sum + input.channels[0].length / sampleRate, 0);
  const start = options.trimStartSeconds ?? 0, end = options.trimEndSeconds ?? duration;
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end > duration || end <= start) throw new Error("local_audio_invalid_trim");
  let timelineOffset = 0;
  const selected = inputs.flatMap((input) => {
    const inputDuration = input.channels[0].length / sampleRate;
    const from = Math.max(0, Math.round((start - timelineOffset) * sampleRate));
    const to = Math.min(input.channels[0].length, Math.round((end - timelineOffset) * sampleRate));
    timelineOffset += inputDuration;
    return to > from ? [{ ...input, channels: input.channels.map((channel) => channel.subarray(from, to)) }] : [];
  });
  const processed = selected.map((input) => applySilence(copyChannels(input, options.channelMode), sampleRate, options));
  const channelCount = Math.max(...processed.map((channels) => channels.length));
  const normalized = processed.map((channels) => channelCount === 2 && channels.length === 1 ? [channels[0], channels[0]] : channels);
  if (normalized.some((channels) => channels.length !== channelCount)) throw new Error("local_audio_channel_mismatch");
  const length = normalized.reduce((total, channels) => total + channels[0].length, 0);
  const channels = Array.from({ length: channelCount }, () => new Float32Array(length));
  let offset = 0;
  for (const input of normalized) {
    for (let channel = 0; channel < channelCount; channel += 1) channels[channel].set(input[channel], offset);
    offset += input[0].length;
  }
  return { sampleRate, channels };
}

export function encodeWav(audio: PcmAudio) {
  const channelCount = audio.channels.length;
  const frameCount = audio.channels[0]?.length ?? 0;
  if (channelCount < 1 || channelCount > 2 || frameCount < 1) throw new Error("local_audio_invalid_output");
  const bytesPerSample = 2;
  const buffer = new ArrayBuffer(44 + frameCount * channelCount * bytesPerSample);
  const view = new DataView(buffer);
  const text = (offset: number, value: string) => {
    for (let index = 0; index < value.length; index += 1) view.setUint8(offset + index, value.charCodeAt(index));
  };
  text(0, "RIFF");
  view.setUint32(4, buffer.byteLength - 8, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channelCount, true);
  view.setUint32(24, audio.sampleRate, true);
  view.setUint32(28, audio.sampleRate * channelCount * bytesPerSample, true);
  view.setUint16(32, channelCount * bytesPerSample, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, frameCount * channelCount * bytesPerSample, true);
  let offset = 44;
  for (let frame = 0; frame < frameCount; frame += 1) {
    for (let channel = 0; channel < channelCount; channel += 1) {
      const sample = Math.max(-1, Math.min(1, audio.channels[channel][frame]));
      view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
      offset += 2;
    }
  }
  return new Blob([buffer], { type: "audio/wav" });
}

export function processDecodedPcm(inputs: PcmAudio[], options: LocalAudioOptions) {
  return options.operationMode === "concat"
    ? [concatenate(inputs, options)]
    : inputs.map((input) => concatenate([input], options));
}

export async function processLocalAudioFiles(
  files: File[],
  options: LocalAudioOptions,
  onProgress?: (progress: LocalAudioProgress) => void,
  signal?: AbortSignal,
): Promise<LocalAudioResult[]> {
  if (files.length < 1 || files.length > LOCAL_AUDIO_MAX_FILES) throw new Error("local_audio_file_count");
  const totalBytes = files.reduce((total, file) => total + file.size, 0);
  if (totalBytes <= 0 || totalBytes > LOCAL_AUDIO_MAX_INPUT_BYTES) throw new Error("local_audio_size_limit");
  const AudioContextClass = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AudioContextClass) throw new Error("local_audio_unsupported");
  const context = new AudioContextClass();
  const decoded: PcmAudio[] = [];
  let decodedSamples = 0;
  try {
    for (const [index, file] of files.entries()) {
      ensureActive(signal);
      onProgress?.({ stage: "reading", percent: Math.round((index / files.length) * 40), filename: file.name });
      const bytes = await file.arrayBuffer();
      ensureActive(signal);
      onProgress?.({ stage: "decoding", percent: Math.round(((index + 0.5) / files.length) * 40), filename: file.name });
      let buffer: AudioBuffer;
      try {
        buffer = await context.decodeAudioData(bytes.slice(0));
      } catch (error) {
        throw new Error(`local_audio_decode_failed:${safeTitle(file.name)}`, { cause: error });
      }
      decodedSamples += buffer.length * buffer.numberOfChannels;
      if (decodedSamples > LOCAL_AUDIO_MAX_DECODED_SAMPLES) throw new Error("local_audio_memory_limit");
      decoded.push({
        sampleRate: buffer.sampleRate,
        channels: Array.from({ length: buffer.numberOfChannels }, (_, channel) => buffer.getChannelData(channel).slice()),
      });
    }
    ensureActive(signal);
    onProgress?.({ stage: "processing", percent: 55, filename: null });
    const output = processDecodedPcm(decoded, options);
    const inputGroups = options.operationMode === "concat" ? [decoded] : decoded.map((item) => [item]);
    const results: LocalAudioResult[] = [];
    for (const [index, audio] of output.entries()) {
      ensureActive(signal);
      onProgress?.({ stage: "encoding", percent: 60 + Math.round(((index + 1) / output.length) * 35), filename: null });
      const requestedTitle = safeTitle(options.title);
      const sourceTitle = stem(files[index].name);
      const outputTitle = requestedTitle || sourceTitle;
      const suffix = output.length > 1 && requestedTitle ? ` — ${sourceTitle}` : "";
      results.push({
        blob: encodeWav(audio),
        filename: `${outputTitle}${suffix}.wav`,
        inputDurationSeconds: inputGroups[index].reduce((total, item) => total + item.channels[0].length / item.sampleRate, 0),
        outputDurationSeconds: audio.channels[0].length / audio.sampleRate,
        visual: buildLocalAudioVisual(inputGroups[index], options),
      });
    }
    onProgress?.({ stage: "completed", percent: 100, filename: null });
    return results;
  } finally {
    await context.close().catch(() => undefined);
  }
}
