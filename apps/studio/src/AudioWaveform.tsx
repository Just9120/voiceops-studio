import { formatAudioDuration } from "./formatters";
import { useId } from "react";

export type AudioVisual = { sources: { position: number; duration_seconds: number; bin_duration_seconds?: number; peaks: number[];
  silences: { start: number; end: number; removed_seconds: number }[]; silence_count: number; intervals_truncated: boolean }[];
  removed_seconds: number };

export function parseAudioVisual(value: unknown): AudioVisual | null {
  if (!value || typeof value !== "object") return null;
  const visual = value as AudioVisual;
  if (!Array.isArray(visual.sources) || visual.sources.length < 1 || visual.sources.length > 50
    || !Number.isFinite(visual.removed_seconds) || visual.removed_seconds < 0) return null;
  let points = 0, intervals = 0;
  for (const [index, source] of visual.sources.entries()) {
    if (!source || typeof source !== "object" || source.position !== index || !Number.isFinite(source.duration_seconds) || source.duration_seconds <= 0
      || !Array.isArray(source.peaks) || !Array.isArray(source.silences)
      || !Number.isInteger(source.silence_count) || source.silence_count < 0) return null;
    if (source.bin_duration_seconds !== undefined && (!Number.isFinite(source.bin_duration_seconds) || source.bin_duration_seconds <= 0)) return null;
    points += source.peaks.length; intervals += source.silences.length;
    if (points > 512 || intervals > 512 || source.peaks.some((peak) => !Number.isFinite(peak) || peak < 0 || peak > 1)) return null;
    if (source.silences.some((part) => !part || typeof part !== "object" || !Number.isFinite(part.start) || !Number.isFinite(part.end)
      || !Number.isFinite(part.removed_seconds) || part.start < 0 || part.end <= part.start
      || part.end > source.duration_seconds || part.removed_seconds < 0 || part.removed_seconds > part.end - part.start + 0.002)) return null;
  }
  return visual;
}

const timestamp = formatAudioDuration;
const reductionLabel = (seconds: number) => seconds > 0 && seconds < 1
  ? seconds < 0.01 ? "менее 0,01 с" : `${seconds.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} с`
  : timestamp(seconds);

export function AudioWaveform({ visual: value, before, after, selection }: { visual: unknown; before: number; after: number; selection?: [number, number] }) {
  const pattern = useId().replaceAll(":", "");
  const visual = parseAudioVisual(value);
  if (!visual) return <p className="muted">Визуальная шкала недоступна для этой проверки.</p>;
  const total = visual.sources.reduce((sum, source) => sum + source.duration_seconds, 0);
  let offset = 0;
  const sections = visual.sources.map((source) => { const start = offset; offset += source.duration_seconds; return { source, start }; });
  const intervals = sections.flatMap(({ source, start }) => source.silences.map((part) => ({ ...part, start: part.start + start, end: part.end + start })));
  const count = visual.sources.reduce((sum, source) => sum + source.silence_count, 0);
  const truncated = visual.sources.some((source) => source.intervals_truncated);
  const hasWaveform = visual.sources.some((source) => source.peaks.length > 0);
  return <section className="audio-waveform" aria-label="Анализ звука и пауз">
    {!selection && <p>До: {timestamp(before)} · после сокращения: {timestamp(after)} · сокращение: {reductionLabel(Math.max(0, before - after))}</p>}
    {hasWaveform ? <svg viewBox="0 0 1000 100" preserveAspectRatio="none" role="img" aria-label={`Звуковая огибающая. Найдено пауз: ${count}. Штриховкой отмечены сокращаемые участки.`}>
      <defs><pattern id={pattern} width="8" height="8" patternUnits="userSpaceOnUse"><path d="M0 8L8 0" stroke="currentColor" strokeWidth="2" /></pattern></defs>
      {selection && <g><rect x="0" y="0" width={selection[0] / total * 1000} height="100" fill="currentColor" opacity="0.3" /><rect x={selection[1] / total * 1000} y="0" width={(total - selection[1]) / total * 1000} height="100" fill="currentColor" opacity="0.3" />{selection.map((bound, index) => <line key={index} x1={bound / total * 1000} x2={bound / total * 1000} y1="0" y2="100" stroke="currentColor" strokeWidth="3" />)}</g>}
      {intervals.map((part, index) => <g key={index}>
        <rect x={part.start / total * 1000} y="0" width={(part.end - part.start) / total * 1000} height="100" fill="currentColor" opacity="0.15" />
        {part.removed_seconds > 0 && <rect x={(part.start + (part.end - part.start - part.removed_seconds) / 2) / total * 1000} y="0" width={part.removed_seconds / total * 1000} height="100" fill={`url(#${pattern})`} />}
      </g>)}
      {sections.flatMap(({ source, start }) => source.peaks.map((peak, index) => {
        const bin = source.bin_duration_seconds ?? source.duration_seconds / source.peaks.length;
        const width = Math.max(0, Math.min(bin, source.duration_seconds - index * bin)) / total * 1000;
        const height = Math.max(1, peak * 90);
        return <rect key={`${source.position}-${index}`} x={(start + index * bin) / total * 1000} y={(100 - height) / 2} width={width * 0.7} height={height} fill="currentColor" />;
      }))}
    </svg> : <p className="muted">Звуковая огибающая недоступна; оценка длительности и найденные паузы сохранены.</p>}
    <p className="muted">Паузы выделены фоном, сокращаемые участки — штриховкой. Шкала показывает огибающую громкости; длительность результата до обработки — оценка.</p>
    {count === 0 ? <p>Пауз для сокращения не найдено.</p> : <details><summary>Найденные паузы: {count}</summary>
      <ul>{intervals.slice(0, 20).map((part, index) => <li key={index}>{timestamp(part.start)}–{timestamp(part.end)} · сокращение {part.removed_seconds.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} сек</li>)}</ul>
      {(truncated || intervals.length > 20) && <p className="muted">Показана часть интервалов. Оценка сокращения учитывает все найденные паузы.</p>}
    </details>}
  </section>;
}
