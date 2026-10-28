import { useEffect, useState } from "react";
import { formatAudioDuration } from "./formatters";

const labels = {
  source_download: "Получаем исходник", source_copy: "Подготавливаем рабочую копию",
  media_probe: "Проверяем запись", media_processing: "Преобразуем аудио",
  media_analysis: "Анализируем запись", audio_processing: "Обрабатываем выбранное аудио",
  provider_upload: "Передаём запись для распознавания", provider_wait: "Ожидаем ответ сервиса распознавания",
  part_merge: "Собираем текст", document_output: "Сохраняем документ",
} as const;
export type WorkProgress = {
  stage: keyof typeof labels; completed: number | null; total: number | null;
  unit: "bytes" | "seconds" | "files" | "parts" | null;
  started_at: string; updated_at: string; sequence: number; generation: number;
};
export function parseWorkProgress(value: unknown): WorkProgress | null {
  if (!value || typeof value !== "object") return null;
  const work = value as WorkProgress;
  if (!Object.hasOwn(labels, work.stage) || ![null, "bytes", "seconds", "files", "parts"].includes(work.unit)
    || ![work.completed, work.total].every((n) => n === null || typeof n === "number" && Number.isFinite(n) && n >= 0)
    || ![work.started_at, work.updated_at].every((s) => typeof s === "string" && Number.isFinite(Date.parse(s)))
    || ![work.sequence, work.generation].every((n) => Number.isSafeInteger(n) && n >= 0)) return null;
  return work;
}
function amount(value: number, unit: WorkProgress["unit"]) {
  if (unit === "seconds") return formatAudioDuration(value);
  if (unit === "bytes") return `${(value / 1024 / 1024).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} МБ`;
  return `${value.toLocaleString("ru-RU")} ${unit === "files" ? "файлов" : "частей"}`;
}
export function WorkProgressDetail({ value }: { value: unknown }) {
  const work = parseWorkProgress(value);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!work) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [!!work]); // Elapsed time changes; the measured percentage never advances on a timer.
  if (!work) return null;
  const known = work.completed !== null && work.total !== null && work.total > 0;
  const percent = known ? Math.min(100, Math.floor(work.completed! / work.total! * 100)) : null;
  return <section className="work-progress-detail" aria-label="Текущий этап обработки">
    <p><strong>{labels[work.stage]}</strong>{percent !== null ? ` · ${percent}% этапа` : ""}</p>
    {work.completed !== null && <p>{amount(work.completed, work.unit)}{work.total !== null ? ` из ${amount(work.total, work.unit)}` : " обработано"}</p>}
    {work.stage === "provider_wait" && <p className="muted">Сервис не сообщает процент распознавания. Ожидание ответа не означает зависание.</p>}
    <p className="muted">На этапе: {formatAudioDuration(Math.max(0, (now - Date.parse(work.started_at)) / 1000))} · подтверждено в {new Date(work.updated_at).toLocaleTimeString("ru-RU")}</p>
  </section>;
}
