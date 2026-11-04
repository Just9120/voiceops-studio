import { useEffect, useRef, useState } from "react";
import { api } from "./apiClient";
import { runBoundedRequest } from "./jobMutationRequest";
import { parseCollectionPage } from "./projectCollectionContracts";
import { deleteLocalRealtimeDraft, listLocalRealtimeDrafts, loadLocalRealtimeDraft,
  newestRealtimeDraft, parseLatestRealtimeDraftResponse, type RealtimeDraft } from "./realtimeDrafts";

type Summary = { client_session_id: string; revision: number; updated_at: string;
  committed_segment_count: number; committed_character_count: number; partial_character_count: number };

function summarize(draft: RealtimeDraft): Summary {
  return { client_session_id: draft.client_session_id, revision: draft.revision, updated_at: draft.updated_at,
    committed_segment_count: draft.committed_segments.length,
    committed_character_count: draft.committed_segments.reduce((sum, text) => sum + text.length, 0), partial_character_count: draft.partial.length };
}

export function parseRealtimeSessionPage(candidate: unknown) {
  if (!candidate || typeof candidate !== "object" || !Array.isArray((candidate as {sessions?:unknown}).sessions)) return null;
  const items: Summary[] = [];
  for (const value of (candidate as {sessions:unknown[]}).sessions) {
    if (!value || typeof value !== "object") return null;
    const row = value as Summary;
    if (typeof row.client_session_id !== "string" || !/^[A-Za-z0-9_-]{16,64}$/.test(row.client_session_id)
      || !Number.isSafeInteger(row.revision) || row.revision < 1 || row.revision > 2147483647
      || typeof row.updated_at !== "string" || !Number.isFinite(Date.parse(row.updated_at))
      || !Number.isSafeInteger(row.committed_segment_count) || row.committed_segment_count < 0 || row.committed_segment_count > 5000
      || !Number.isSafeInteger(row.committed_character_count) || row.committed_character_count < 0 || row.committed_character_count > 500000
      || !Number.isSafeInteger(row.partial_character_count) || row.partial_character_count < 0 || row.partial_character_count > 20000) return null;
    items.push({client_session_id:row.client_session_id, revision:row.revision, updated_at:row.updated_at,
      committed_segment_count:row.committed_segment_count, committed_character_count:row.committed_character_count,
      partial_character_count:row.partial_character_count});
  }
  if (new Set(items.map(item => item.client_session_id)).size !== items.length) return null;
  return parseCollectionPage(candidate, "sessions", items);
}

function merge(...groups: Summary[][]): Summary[] {
  const rows = new Map<string, Summary>();
  for (const group of groups) for (const row of group) {
    const previous = rows.get(row.client_session_id);
    if (!previous || row.revision >= previous.revision) rows.set(row.client_session_id, row);
  }
  return [...rows.values()].sort((a,b) => Date.parse(b.updated_at) - Date.parse(a.updated_at) || a.client_session_id.localeCompare(b.client_session_id));
}

export function RealtimeSessionHistory({ ownerUserId, projectId, disabled, currentDraft, refreshKey, onOpen }: {
  ownerUserId: string; projectId: string; disabled: boolean; currentDraft: RealtimeDraft | null;
  refreshKey: number; onOpen: (draft: RealtimeDraft) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Summary[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [opening, setOpening] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [reload, setReload] = useState(0);
  const epoch = useRef(0);
  const disabledRef = useRef(disabled);
  disabledRef.current = disabled;

  useEffect(() => {
    const generation = ++epoch.current;
    setItems([]); setNextCursor(null); setNotice(""); setOpening(null); setLoading(false);
    if (!open) return;
    setLoading(true);
    void Promise.all([
      listLocalRealtimeDrafts(ownerUserId, projectId).catch(() => []),
      runBoundedRequest(signal => api<unknown>(`/projects/${projectId}/realtime/drafts?page_size=50`, {signal, cache:"no-store"}), 10000)
        .then(result => result.status === "completed" ? parseRealtimeSessionPage(result.value) : null).catch(() => null),
    ]).then(([local, server]) => {
      if (epoch.current !== generation) return;
      setItems(merge(local.map(summarize), server?.items ?? []));
      setNextCursor(server?.nextCursor ?? null);
      if (!server) setNotice("Список Studio не подтверждён. Доступные локальные копии сохранены; повторите обновление.");
      setLoading(false);
    });
    return () => { epoch.current += 1; };
  }, [open, ownerUserId, projectId, refreshKey, reload]);

  useEffect(() => {
    if (currentDraft?.owner_user_id === ownerUserId && currentDraft.project_id === projectId) {
      setItems(previous => merge(previous, [summarize(currentDraft)]));
    }
  }, [currentDraft, ownerUserId, projectId]);

  async function loadMore() {
    if (!nextCursor || loading) return;
    const generation = epoch.current;
    setLoading(true);
    try {
      const response = await runBoundedRequest(signal => api<unknown>(`/projects/${projectId}/realtime/drafts?page_size=50&cursor=${encodeURIComponent(nextCursor)}`, {signal, cache:"no-store"}), 10000);
      if (generation !== epoch.current) return;
      const page = response.status === "completed" ? parseRealtimeSessionPage(response.value) : null;
      if (!page || page.nextCursor === nextCursor) throw new Error("invalid_live_sessions_page");
      setItems(previous => merge(previous, page.items)); setNextCursor(page.nextCursor); setNotice("");
    } catch {
      if (generation === epoch.current) setNotice("Не удалось загрузить следующую страницу. Уже загруженные сессии сохранены.");
    } finally { if (generation === epoch.current) setLoading(false); }
  }

  async function openSession(id: string) {
    if (disabledRef.current || opening) return;
    const generation = epoch.current;
    setOpening(id); setNotice("");
    try {
      const local = await loadLocalRealtimeDraft(ownerUserId, projectId, new Date(), id);
      const result = await runBoundedRequest(signal => api<unknown>(`/projects/${projectId}/realtime/drafts/${encodeURIComponent(id)}`, {signal, cache:"no-store"}), 10000).catch(() => null);
      if (generation !== epoch.current || disabledRef.current) return;
      if (result?.status === "completed" && result.value && typeof result.value === "object" && (result.value as {cleared?:unknown}).cleared === true) {
        if ((result.value as {draft?:unknown}).draft !== null) throw new Error("invalid_retired_session_response");
        await deleteLocalRealtimeDraft(ownerUserId, projectId, id);
        if (generation !== epoch.current) return;
        setItems(previous => previous.filter(row => row.client_session_id !== id));
        setNotice("Эта сессия уже очищена в Studio. Старая локальная копия удалена.");
        return;
      }
      const server = result?.status === "completed" ? parseLatestRealtimeDraftResponse(result.value, ownerUserId, projectId) : undefined;
      const selected = newestRealtimeDraft(local, server ?? null);
      if (!selected || selected.client_session_id !== id) throw new Error("live_session_unavailable");
      if (server === undefined) setNotice("Открыта локальная копия. Состояние копии Studio сейчас не подтверждено.");
      await onOpen(selected);
    } catch {
      if (generation === epoch.current) setNotice("Не удалось открыть эту сессию. Текущий текст сохранён; повторите позже.");
    } finally { if (generation === epoch.current) setOpening(null); }
  }

  return <details className="live-session-history" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Сохранённые Live-сессии</summary>
    {open && <div>
      <p className="muted">Каждая запись хранится отдельно до вашей очистки. Откройте сессию, чтобы скопировать, скачать или очистить её текст.</p>
      <button type="button" className="secondary" disabled={loading || Boolean(opening)} onClick={() => setReload(value => value + 1)}>Обновить список сессий</button>
      {loading && <p role="status">Загружаем Live-сессии…</p>}
      {notice && <p className="notice" role="status">{notice}</p>}
      {!loading && items.length === 0 && <p>Сохранённых Live-сессий пока нет.</p>}
      {disabled && <p className="muted">Другая сессия откроется после остановки текущей записи.</p>}
      <ul>{items.map(row => <li key={row.client_session_id}>
        <span>Сохранено {new Date(row.updated_at).toLocaleString("ru-RU")} · Фрагментов: {row.committed_segment_count} · Символов: {row.committed_character_count + row.partial_character_count}</span>{" "}
        <button type="button" disabled={disabled || Boolean(opening)} onClick={() => void openSession(row.client_session_id)}>
          {opening === row.client_session_id ? "Открываем…" : "Открыть сессию"}
        </button>
      </li>)}</ul>
      {nextCursor && <button type="button" className="secondary" disabled={loading || Boolean(opening)} onClick={() => void loadMore()}>Загрузить ещё сессии</button>}
    </div>}
  </details>;
}
