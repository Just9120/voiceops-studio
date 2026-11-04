import { useEffect, useRef, useState } from "react";
import { ApiError, api, mutateWithCsrfRetry } from "./apiClient";

type DownloadState = { state: "idle" | "preparing" | "ready" | "failed"; percent: number; reason?: string | null };
type Props = { jobId: string; csrf: string; onCsrf: (value: string) => void; preview?: boolean; initialActive?: boolean; onActiveChange?: (jobId: string, active: boolean) => void };

function parseDownload(value: unknown): DownloadState {
  const status = value as DownloadState | null;
  if (!status || !["preparing", "ready", "failed"].includes(status.state)
    || !Number.isFinite(status.percent) || status.percent < 0 || status.percent > 100) {
    throw new Error("invalid_download_status");
  }
  return status;
}

function failureReason(error: unknown) {
  if (error instanceof ApiError && error.data && typeof error.data === "object") {
    const detail = (error.data as { detail?: { reason?: string } }).detail;
    if (typeof detail?.reason === "string") return detail.reason;
  }
  return "download_failed";
}

function message(reason?: string | null) {
  return ({
    download_busy: "Сейчас готовится другой файл. Повторите скачивание после его завершения.",
    download_expired: "Временный файл уже очищен. Подготовьте его заново, пока исходники доступны.",
    source_unavailable: "Исходники больше недоступны. Откройте сохранённую копию в Google Drive или добавьте исходники заново.",
    source_version_unavailable: "Прежняя версия исходника Google Drive не зафиксирована. Откройте сохранённую копию результата или добавьте исходники заново.",
    timeline_unavailable: "Не удалось подтвердить сохранённую карту обработки. Откройте копию результата на диске или создайте новую обработку из доступных исходников.",
    no_retained_audio: "После удаления пауз не осталось звука. Измените настройки пауз или выберите другой диапазон.",
    output_copy_changed: "Копия на Google Drive изменена и не была перезаписана. Можно скачать результат из Studio, пока доступны исходники, или создать новую обработку.",
    cancellation_requested: "Подготовка скачивания отменена. Параметры обработки сохранены.",
    lease_unavailable: "Файл сейчас используется другой операцией. Дождитесь её завершения и повторите.",
  } as Record<string, string>)[reason ?? ""] ?? "Не удалось подготовить скачивание. Параметры сохранены; повторите позже.";
}

export function AudioResultDownload({ jobId, csrf, onCsrf, preview = false, initialActive = false, onActiveChange }: Props) {
  const [download, setDownload] = useState<DownloadState>({ state: initialActive ? "preparing" : "idle", percent: 0 });
  const [cancelling, setCancelling] = useState(false);
  const [playbackFailed, setPlaybackFailed] = useState(false);
  const reportedActive = useRef(false);

  useEffect(() => {
    const active = download.state === "preparing" || download.state === "ready";
    if (reportedActive.current === active) return;
    reportedActive.current = active;
    onActiveChange?.(jobId, active);
  }, [download.state, jobId, onActiveChange]);

  useEffect(() => {
    if (download.state !== "preparing") return;
    const controller = new AbortController();
    let polling = false;
    const timer = window.setInterval(() => {
      if (polling) return;
      polling = true;
      void api<unknown>(`/audio-preparations/${jobId}/download/status`, { cache: "no-store", signal: controller.signal })
        .then((value) => { if (!controller.signal.aborted) setDownload(parseDownload(value)); })
        .catch((error) => { if (!controller.signal.aborted) setDownload({ state: "failed", percent: 0, reason: failureReason(error) }); })
        .finally(() => { polling = false; });
    }, 2000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [download.state, jobId]);

  async function prepare() {
    setPlaybackFailed(false);
    setCancelling(false);
    setDownload({ state: "preparing", percent: 0 });
    try {
      setDownload(parseDownload(await mutateWithCsrfRetry(`/audio-preparations/${jobId}/${preview ? "preview-audio" : "download"}`, csrf, onCsrf, { method: "POST" })));
    } catch (error) {
      setDownload({ state: "failed", percent: 0, reason: failureReason(error) });
    }
  }

  async function cancel() {
    setCancelling(true);
    try {
      const value = await mutateWithCsrfRetry<unknown>(`/audio-preparations/${jobId}/download/cancel`, csrf, onCsrf, { method: "POST" });
      const result = value as { state?: string };
      if (result.state === "failed") setDownload(parseDownload(value));
    } catch (error) {
      setCancelling(false);
      setDownload({ state: "failed", percent: 0, reason: failureReason(error) });
    }
  }

  return <div className="audio-download-action">
    {download.state === "ready" && !preview
      ? <a className="button-like primary" href={`/api/audio-preparations/${jobId}/download`}
          onClick={() => setDownload({ state: "idle", percent: 0 })}>Скачать файл</a>
      : download.state !== "ready" && <button className="primary" type="button" disabled={download.state === "preparing"} onClick={() => void prepare()}>
          {download.state === "preparing" ? preview ? "Готовим фрагмент…" : "Готовим скачивание…" : preview ? "Прослушать пример обработки" : "Подготовить файл для скачивания"}
        </button>}
    {download.state === "preparing" && <>
      <p role="status">{cancelling ? "Отменяем подготовку…" : `Собираем файл из исходников · ${download.percent}%`}</p>
      <progress aria-label={preview ? "Подготовка примера" : "Подготовка скачивания"} max="100" value={download.percent} />
      <button type="button" disabled={cancelling} onClick={() => void cancel()}>{preview ? "Отменить подготовку примера" : "Отменить скачивание"}</button>
    </>}
    {download.state === "ready" && <button type="button" disabled={cancelling} onClick={() => void cancel()}>{preview ? "Закрыть пример" : "Закрыть скачивание"}</button>}
    {download.state === "ready" && <div>
      <audio controls preload="none" aria-label={preview ? "Прослушать пример обработки" : "Прослушать обработанный результат"} src={`/api/audio-preparations/${jobId}/listen`} onError={() => setPlaybackFailed(true)} />
      <p className="muted">{preview ? "Фрагмент до 30 секунд с выбранными настройками: участок возле первой найденной паузы или начало записи. Это пример, не готовый полный файл. Закройте пример перед запуском полной обработки." : "Можно прослушать результат перед скачиванием."} Временный файл доступен 15 минут; затем его можно собрать заново.</p>
      {playbackFailed && <p role="alert" className="error">Не удалось воспроизвести {preview ? "пример" : "файл"} в браузере. Причиной может быть формат, сетевой сбой или ограничение браузера. {preview ? "Закройте пример и повторите позже." : "Скачайте файл для внешнего плеера. Повторная подготовка нужна, только если срок доступа к файлу истёк."}</p>}
    </div>}
    {download.state === "failed" && <p role="alert" className="error">{message(download.reason)}</p>}
  </div>;
}
