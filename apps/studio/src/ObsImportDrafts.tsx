import { useEffect, useState } from "react";
import { api } from "./apiClient";
import { parseProjectSourcePage } from "./projectCollectionContracts";
import type { Source } from "./sourceModel";

export function ObsImportDrafts({ projectId, selectedIds, onAdd }: {
  projectId: string;
  selectedIds: string[];
  onAdd: (source: Source) => void;
}) {
  const [open, setOpen] = useState(false);
  const [drafts, setDrafts] = useState<Source[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [request, setRequest] = useState<{ cursor: string | null }>({ cursor: null });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const search = request.cursor ? `?cursor=${encodeURIComponent(request.cursor)}` : "";
    setBusy(true);
    setError("");
    void api<unknown>(`/projects/${projectId}/obs-drafts${search}`, { signal: controller.signal })
      .then((raw) => {
        if (controller.signal.aborted) return;
        const page = parseProjectSourcePage(raw, projectId);
        if (!page) throw new Error("invalid_obs_drafts");
        setDrafts((current) => request.cursor
          ? [...current, ...page.items.filter((source) => !current.some((item) => item.id === source.id))]
          : page.items);
        setNext(page.nextCursor);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError("Не удалось загрузить черновики OBS.");
      })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [open, projectId, request]);

  return <details className="card" onToggle={(event) => {
    const expanded = event.currentTarget.open;
    setOpen(expanded);
    if (expanded) setRequest({ cursor: null });
  }}>
    <summary>Черновики OBS</summary>
    {open && <>
      <button type="button" disabled={busy} onClick={() => setRequest({ cursor: null })}>Обновить черновики</button>
      {busy && <p role="status">Обновляем черновики…</p>}
      {error && <p role="alert">{error}</p>}
      {!busy && !error && drafts.length === 0 && <p>В этой рабочей области пока нет черновиков OBS.</p>}
      {drafts.length > 0 && <ul className="local-device-list">
        {drafts.map((source) => <li key={source.id} className="split">
          <strong>{source.original_filename}</strong>
          <button type="button" disabled={selectedIds.includes(source.id)} onClick={() => onAdd(source)}>
            {selectedIds.includes(source.id) ? "В текущей задаче" : "Добавить в Batch"}
          </button>
        </li>)}
      </ul>}
      {next && <button type="button" disabled={busy} onClick={() => setRequest({ cursor: next })}>Загрузить ещё</button>}
    </>}
  </details>;
}
