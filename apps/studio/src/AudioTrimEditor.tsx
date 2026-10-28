import { useState } from "react";
import { AudioWaveform } from "./AudioWaveform";
import { formatAudioDuration } from "./formatters";

export type AudioTrim = { trim_start_seconds?: number; trim_end_seconds?: number | null; output_format?: string };

export function AudioTrimEditor({ duration, visual, options, disabled, onSave, onDirtyChange, local = false }: {
  duration: number; visual: unknown; options: AudioTrim; disabled: boolean;
  onSave: (value: { start_seconds: number; end_seconds: number | null; output_format: string }) => Promise<void>;
  onDirtyChange: (dirty: boolean) => void;
  local?: boolean;
}) {
  const initialStart = options.trim_start_seconds ?? 0;
  const initialEnd = options.trim_end_seconds ?? duration;
  const [start, setStart] = useState(String(initialStart));
  const [end, setEnd] = useState(String(initialEnd));
  const [format, setFormat] = useState(options.output_format ?? "wav");
  const [zoom, setZoom] = useState(1);
  const [error, setError] = useState("");
  const a = Number(start.replace(",", ".")), b = Number(end.replace(",", "."));
  const valid = start.trim() !== "" && end.trim() !== "" && Number.isFinite(a) && Number.isFinite(b) && a >= 0 && b <= duration && b > a;
  const trimmed = a !== 0 || b !== duration;
  const dirty = a !== initialStart || b !== initialEnd || format !== options.output_format || !valid;
  const change = (boundary: "start" | "end", value: string) => {
    (boundary === "start" ? setStart : setEnd)(value);
    onDirtyChange(true); setError("");
  };
  async function save() {
    if (!valid || (trimmed && format === "copy")) return;
    setError("");
    try { await onSave({ start_seconds: a, end_seconds: b === duration ? null : b, output_format: format }); onDirtyChange(false); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Не удалось сохранить границы. Повторите попытку."); }
  }
  return <fieldset className="audio-trim-editor" disabled={disabled}>
    <legend>Обрезка аудио</legend>
    <p className="muted">Оставьте один участок на исходной шкале, до сокращения пауз. Исходники сохранятся. {local ? "Примените границы: плеер ниже будет воспроизводить новый результат. Локальный формат — WAV." : "После изменения примените границы; затем можно прослушать первые 30 секунд выбранного результата."}</p>
    <label>Масштаб шкалы <select value={zoom} onChange={(e) => setZoom(Number(e.target.value))}>
      {[1, 2, 4, 8, 16].map((value) => <option key={value} value={value}>{value}×</option>)}
    </select></label>
    <div className="audio-trim-scroll" tabIndex={0} role="region" aria-label="Шкала обрезки, прокрутка по времени">
      <div style={{ width: `${zoom * 100}%` }}>
        <AudioWaveform visual={visual} before={duration} after={valid ? b - a : duration} selection={valid ? [a, b] : undefined} />
        <label>Начало выделения<input type="range" min="0" max={duration} step="0.01" value={Number.isFinite(a) ? a : 0} aria-valuetext={formatAudioDuration(a)} onChange={(e) => change("start", e.target.value)} /></label>
        <label>Конец выделения<input type="range" min="0" max={duration} step="0.01" value={Number.isFinite(b) ? b : duration} aria-valuetext={formatAudioDuration(b)} onChange={(e) => change("end", e.target.value)} /></label>
      </div>
    </div>
    <div className="audio-settings-grid">
      <label>Начало, секунд<input inputMode="decimal" value={start} onChange={(e) => change("start", e.target.value)} aria-invalid={!valid} /></label>
      <label>Конец, секунд<input inputMode="decimal" value={end} onChange={(e) => change("end", e.target.value)} aria-invalid={!valid} /></label>
      <label>Формат результата<select value={format} onChange={(e) => { setFormat(e.target.value); onDirtyChange(true); }}>
        <option value="wav">WAV</option>{!local && <option value="flac">FLAC</option>}
        {!local && options.output_format === "copy" && <option value="copy">Исходный формат, без обрезки</option>}
      </select></label>
    </div>
    <p aria-live="polite">{valid ? `Выбрано: ${formatAudioDuration(a)}–${formatAudioDuration(b)} · ${formatAudioDuration(b - a)}` : "Укажите начало и конец внутри записи. Конец должен быть позже начала."}</p>
    {trimmed && format === "copy" && <p role="alert">Для точных границ выберите WAV или FLAC. Формат не изменится автоматически.</p>}
    {error && <p role="alert">{error}</p>}
    <div className="actions"><button type="button" disabled={!dirty || !valid || (trimmed && format === "copy")} onClick={() => void save()}>Применить границы</button>
      <button type="button" onClick={() => { setStart("0"); setEnd(String(duration)); onDirtyChange(true); }}>Выделить всю запись</button></div>
    {dirty && <p className="muted">Изменения ещё не применены. Запуск обработки станет доступен после сохранения границ.</p>}
  </fieldset>;
}
