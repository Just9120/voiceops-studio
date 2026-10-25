import { type KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { ApiError, mutateWithCsrfRetry } from "./apiClient";
import { lockDocumentScroll } from "./documentScrollLock";

export type DiskResource = {
  path: string; name: string; is_folder: boolean; fingerprint: string;
  mime_type: string | null; size_bytes: number | null; modified: string | null;
};
export type DiskSelection = DiskResource & { id: string };
type Page = { folder: DiskResource; items: DiskResource[]; next_offset: number | null };
export type DiskPickerMode = "sources" | "source-folder" | "output-folder";
export type DiskPickerResult = { resources: DiskSelection[]; folder: DiskSelection | null } | null;
type Props = {
  mode: DiskPickerMode; csrf: string; onCsrf: (value: string) => void;
  onFinish: (result: DiskPickerResult) => void;
};

function parseResource(value: unknown): DiskResource | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  if (typeof row.path !== "string" || !row.path.startsWith("disk:/") || row.path.length > 4096 ||
      typeof row.name !== "string" || !row.name || row.name.length > 512 || typeof row.is_folder !== "boolean" ||
      typeof row.fingerprint !== "string" || !/^[a-f0-9]{64}$/.test(row.fingerprint) ||
      (row.mime_type !== null && typeof row.mime_type !== "string") ||
      (row.size_bytes !== null && (typeof row.size_bytes !== "number" || !Number.isSafeInteger(row.size_bytes) || row.size_bytes < 0)) ||
      (row.modified !== null && typeof row.modified !== "string")) return null;
  return row as DiskResource;
}

function parsePage(value: unknown): Page {
  if (!value || typeof value !== "object") throw new Error("invalid_disk_page");
  const raw = value as Record<string, unknown>;
  const folder = parseResource(raw.folder);
  if (!folder?.is_folder || !Array.isArray(raw.items) || raw.items.length > 100 ||
      (raw.next_offset !== null && (typeof raw.next_offset !== "number" || !Number.isInteger(raw.next_offset) || raw.next_offset < 1))) {
    throw new Error("invalid_disk_page");
  }
  const items = raw.items.map(parseResource);
  if (items.some((item) => !item) || new Set(items.map((item) => item!.path)).size !== items.length) throw new Error("invalid_disk_page");
  return { folder, items: items as DiskResource[], next_offset: raw.next_offset as number | null };
}

export function diskFailureMessage(error: unknown) {
  const detail = error instanceof ApiError && error.data && typeof error.data === "object"
    ? (error.data as { detail?: { reason?: string } }).detail : null;
  const reason = detail && typeof detail === "object" ? detail.reason : "";
  if (reason === "recent_reauthentication_required") return "Подтвердите личность в разделе «Аккаунт» и повторите действие.";
  if (reason === "yandex_disk_configuration_unavailable") return "Подключение Яндекс Диска ещё не настроено администратором.";
  if (reason === "yandex_disk_reauthorization_required" || reason === "yandex_disk_authentication_rejected") return "Восстановите подключение Яндекс Диска в настройках.";
  if (reason === "yandex_disk_resource_changed") return "Файл или папка изменились на Диске. Обновите список и выберите заново.";
  if (reason === "yandex_disk_permission_denied") return "Нет доступа к выбранному файлу или папке. Проверьте подключение Диска.";
  if (reason === "yandex_disk_quota_exceeded") return "На Яндекс Диске недостаточно места. Освободите место и повторите сохранение.";
  return "Не удалось выполнить действие с Яндекс Диском. Проверьте подключение и повторите попытку.";
}

function isMedia(row: DiskResource) {
  return !row.is_folder && Boolean(row.mime_type && (/^(audio|video)\//.test(row.mime_type) || row.mime_type === "application/ogg"));
}

export function YandexDiskPicker({ mode, csrf, onCsrf, onFinish }: Props) {
  const titleId = useId();
  const dialog = useRef<HTMLElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const currentRequest = useRef<AbortController | null>(null);
  const requestVersion = useRef(0);
  const alive = useRef(true);
  const [path, setPath] = useState("disk:/");
  const [sort, setSort] = useState("name");
  const [reload, setReload] = useState(0);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState<Page | null>(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [selection, setSelection] = useState(new Map<string, DiskResource>());
  const options = useRef({ csrf, onCsrf });
  options.current.onCsrf = onCsrf;
  useEffect(() => { options.current.csrf = csrf; }, [csrf]);

  useEffect(() => {
    alive.current = true;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const unlock = lockDocumentScroll();
    close.current?.focus();
    return () => {
      alive.current = false;
      currentRequest.current?.abort();
      unlock();
      if (previous?.isConnected) previous.focus();
    };
  }, []);

  async function post(url: string, payload: unknown, signal: AbortSignal) {
    return mutateWithCsrfRetry<unknown>(url, options.current.csrf, (value) => {
      options.current.csrf = value;
      options.current.onCsrf(value);
    },
      { method: "POST", body: JSON.stringify(payload), signal });
  }

  useEffect(() => {
    const controller = new AbortController();
    currentRequest.current?.abort();
    currentRequest.current = controller;
    const version = ++requestVersion.current;
    const timeout = setTimeout(() => controller.abort(), 20_000);
    setBusy(true); setPage(null); setError("");
    void post("/yandex/resources/list", { path, sort, folders_only: mode === "output-folder" }, controller.signal)
      .then(parsePage).then((result) => {
        if (alive.current && version === requestVersion.current) setPage(result);
      }).catch((err) => {
        if (alive.current && version === requestVersion.current) setError(diskFailureMessage(err));
      }).finally(() => {
        clearTimeout(timeout);
        if (alive.current && version === requestVersion.current) setBusy(false);
      });
    return () => { controller.abort(); clearTimeout(timeout); };
    // Credentials are kept in a ref so CSRF refresh does not restart navigation.
  }, [path, sort, mode, reload]);

  async function loadMore() {
    if (!page || page.next_offset === null || busy || pending) return;
    const controller = new AbortController();
    currentRequest.current = controller;
    const timeout = setTimeout(() => controller.abort(), 20_000);
    const version = requestVersion.current;
    const offset = page.next_offset;
    setBusy(true); setError("");
    try {
      const next = parsePage(await post("/yandex/resources/list", { path, sort, offset, folders_only: mode === "output-folder" }, controller.signal));
      if (next.folder.fingerprint !== page.folder.fingerprint || next.folder.modified !== page.folder.modified || (next.next_offset !== null && next.next_offset <= offset)) throw new Error("changed_disk_page");
      if (alive.current && version === requestVersion.current) setPage((previous) => previous ? {
        ...next, items: [...new Map([...previous.items, ...next.items].map((item) => [item.path, item])).values()],
      } : next);
    } catch (err) {
      if (alive.current && version === requestVersion.current) setError(diskFailureMessage(err));
    } finally {
      clearTimeout(timeout);
      if (alive.current && version === requestVersion.current) setBusy(false);
    }
  }

  async function confirm() {
    if (!page || pending || busy) return;
    const controller = new AbortController();
    currentRequest.current = controller;
    const timeout = setTimeout(() => controller.abort(), 60_000);
    setPending(true); setError("");
    try {
      let items = [...selection.values()];
      if (mode === "source-folder") {
        let slice = parsePage(await post("/yandex/resources/list", { path, sort }, controller.signal));
        const baseline = slice.folder;
        items = slice.items.filter(isMedia);
        while (slice.next_offset !== null) {
          const offset = slice.next_offset;
          if (items.length > 50) throw new Error("disk_folder_over_limit");
          slice = parsePage(await post("/yandex/resources/list", { path, sort, offset }, controller.signal));
          if (slice.folder.fingerprint !== baseline.fingerprint || slice.folder.modified !== baseline.modified || (slice.next_offset !== null && slice.next_offset <= offset)) throw new Error("changed_disk_page");
          items.push(...slice.items.filter(isMedia));
        }
        if (items.length > 50) throw new Error("disk_folder_over_limit");
        if (new Set(items.map((item) => item.path)).size !== items.length) throw new Error("changed_disk_page");
      }
      async function select(item: DiskResource): Promise<DiskSelection> {
        const raw = await post("/yandex/resources/select", { path: item.path, fingerprint: item.fingerprint, is_folder: item.is_folder }, controller.signal);
        const parsed = parseResource(raw);
        const id = raw && typeof raw === "object" ? (raw as { id?: unknown }).id : null;
        if (!parsed || parsed.path !== item.path || parsed.fingerprint !== item.fingerprint ||
            typeof id !== "string" || !/^[a-f0-9-]{36}$/.test(id)) throw new Error("invalid_disk_selection");
        return { ...parsed, id };
      }
      const folder = mode === "sources" ? null : await select(page.folder);
      const resources: DiskSelection[] = [];
      if (mode !== "output-folder") for (const item of items) resources.push(await select(item));
      if (alive.current) onFinish({ resources, folder });
    } catch (err) {
      if (alive.current) setError(err instanceof Error && err.message === "disk_folder_over_limit"
        ? "В папке больше 50 записей. Выберите нужные файлы отдельно; ничего не добавлено."
        : err instanceof Error && err.message === "changed_disk_page"
        ? "Содержимое папки изменилось. Обновите список и повторите выбор; ничего не добавлено." : diskFailureMessage(err));
    } finally {
      clearTimeout(timeout);
      if (alive.current) setPending(false);
    }
  }

  function keyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") { event.preventDefault(); currentRequest.current?.abort(); onFinish(null); return; }
    if (event.key !== "Tab") return;
    const controls = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), [href]') ?? []);
    const first = controls[0], last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }

  const shown = page?.items.filter((item) => (item.is_folder || isMedia(item)) && item.name.toLocaleLowerCase("ru").includes(search.toLocaleLowerCase("ru"))) ?? [];
  return <div className="confirm-clear-backdrop"><section ref={dialog} role="dialog" aria-modal="true" aria-labelledby={titleId}
    className="card google-drive-folder-picker-dialog" data-studio-scroll-lock-allow onKeyDown={keyDown}>
    <header className="actions"><h2 id={titleId}>{mode === "sources" ? "Выберите записи на Яндекс Диске" : "Выберите папку Яндекс Диска"}</h2>
      <button ref={close} type="button" onClick={() => { currentRequest.current?.abort(); onFinish(null); }}>Закрыть</button></header>
    <p className="muted">{mode === "source-folder" ? "Будут добавлены аудио и видео из текущей папки без вложенных папок. Пустую папку тоже можно выбрать." : mode === "output-folder" ? "Откройте нужную папку и подтвердите её. Результат сохранится как DOCX." : "Можно выбрать до 50 аудио и видео, в том числе из разных папок."}</p>
    <label>Сортировка<select value={sort} disabled={pending} onChange={(event) => setSort(event.target.value)}>
      <option value="name">По имени А–Я</option><option value="-name">По имени Я–А</option>
      <option value="-modified">Сначала недавно изменённые</option><option value="modified">Сначала давно изменённые</option></select></label>
    <label>Поиск в загруженных элементах текущей папки<input value={search} disabled={pending} onChange={(event) => setSearch(event.target.value)} /></label>
    <nav className="actions" aria-label="Путь на Яндекс Диске"><button type="button" disabled={pending || path === "disk:/"} onClick={() => { setPath("disk:/"); setSearch(""); }}>Мой диск</button>
      <button type="button" disabled={pending || path === "disk:/"} onClick={() => { const parent = path.slice(0, path.lastIndexOf("/")); setPath(parent === "disk:" ? "disk:/" : parent); setSearch(""); }}>На уровень выше</button>
      <span style={{ overflowWrap: "anywhere" }}>{path === "disk:/" ? "Мой диск" : path.slice(6)}</span></nav>
    {error && <div role="alert"><p className="error">{error}</p><button type="button" disabled={busy || pending} onClick={() => setReload((value) => value + 1)}>Обновить список</button></div>}
    {busy && <p role="status">Загружаем список…</p>}
    {page && <><ul className="google-drive-folder-list">{shown.map((item) => <li key={item.path}>
      {item.is_folder ? <button type="button" className="google-drive-folder-row" disabled={pending} onClick={() => { setPath(item.path); setSearch(""); }}><span aria-hidden="true">📁</span><span style={{ overflowWrap: "anywhere" }}>{item.name}</span><span>Открыть</span></button> : mode === "source-folder" ? <span className="google-drive-folder-row"><span aria-hidden="true">🎧</span><span style={{ overflowWrap: "anywhere" }}>{item.name}</span></span> : mode === "sources" && <button type="button" className="google-drive-folder-row" aria-pressed={selection.has(item.path)} disabled={pending || (!selection.has(item.path) && selection.size >= 50)}
        onClick={() => setSelection((previous) => { const next = new Map(previous); if (next.has(item.path)) next.delete(item.path); else next.set(item.path, item); return next; })}><span aria-hidden="true">🎧</span><span style={{ overflowWrap: "anywhere" }}>{item.name}</span>{mode === "sources" && <span>{selection.has(item.path) ? "Выбрано" : "Выбрать"}</span>}</button>}
    </li>)}</ul>
      {!shown.length && !busy && <p className="muted">{search ? "Совпадений среди загруженных элементов нет." : mode === "sources" ? "Подходящих аудио и видео на этой странице нет." : "Подходящих элементов на этой странице нет. Текущую папку можно выбрать."}</p>}
      {page.next_offset !== null && <button type="button" disabled={busy || pending} onClick={() => void loadMore()}>Показать ещё</button>}
      <footer className="actions"><button type="button" className="primary" disabled={busy || pending || (mode === "sources" && !selection.size)} aria-busy={pending || undefined} onClick={() => void confirm()}>{pending ? "Проверяем выбор…" : mode === "sources" ? `Выбрать файлы (${selection.size})` : "Выбрать эту папку"}</button></footer>
    </>}
  </section></div>;
}

export function openYandexDiskPicker(props: Omit<Props, "onFinish">, signal?: AbortSignal): Promise<DiskPickerResult> {
  if (signal?.aborted) return Promise.resolve(null);
  return new Promise((resolve) => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const node = document.createElement("div");
    document.body.append(node);
    const root = createRoot(node);
    let settled = false;
    const finish = (result: DiskPickerResult) => {
      if (settled) return;
      settled = true;
      signal?.removeEventListener("abort", cancel);
      queueMicrotask(() => { root.unmount(); node.remove(); resolve(result); requestAnimationFrame(() => { if (previous?.isConnected) previous.focus(); }); });
    };
    const cancel = () => finish(null);
    signal?.addEventListener("abort", cancel, { once: true });
    root.render(<YandexDiskPicker {...props} onFinish={finish} />);
  });
}
