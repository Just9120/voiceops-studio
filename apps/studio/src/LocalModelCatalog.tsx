import { useEffect, useRef, useState } from "react";
import { api, mutateWithCsrfRetry } from "./apiClient";
import type { LocalExecutionDevice } from "./localExecutionContracts";

type CatalogItem = {
  id: string; source_url: string; hub_revision: string | null; license: string | null;
  languages: string[]; downloads: number | null; likes: number | null;
  studio: { name: string; model: string; revision: string; languages: string[]; diarization: boolean;
    word_timestamps: boolean; download_bytes: number } | null;
};
type CatalogPage = { items: CatalogItem[]; next_cursor: string | null };

type Inventory = {
  cpu: string; cpu_threads: number | null; ram_bytes: number | null; disk_free_bytes: number | null;
  gpus: { name: string; vram_bytes: number | null }[]; installed: string[]; execution: string[];
  probes: { model: string; audio_seconds: number; elapsed_seconds: number }[];
};

function gib(bytes: number | null) {
  return bytes == null ? "нет данных" : `${(bytes / 1073741824).toFixed(1)} ГиБ`;
}

function suitability(item: CatalogItem, inventory: Inventory | null) {
  if (!item.studio) return "Недостаточно данных";
  if (!inventory) return "Недостаточно данных";
  if (inventory.probes.some(probe => probe.model === item.studio?.model)) return "Подходит по короткой пробе";
  if (inventory.installed.includes(item.studio.model)) return "С ограничениями · скорость не измерена";
  if (inventory.disk_free_bytes !== null && inventory.disk_free_bytes < item.studio.download_bytes) return "Не подходит · недостаточно места";
  return "Недостаточно данных · требуется проба на ПК";
}

export function LocalModelCatalog({ devices, csrf, onCsrf }: {
  devices: LocalExecutionDevice[]; csrf: string; onCsrf: (value: string) => void;
}) {
  const [items, setItems] = useState<CatalogItem[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [language, setLanguage] = useState("");
  const [sort, setSort] = useState("downloads");
  const [supported, setSupported] = useState(false);
  const [speakers, setSpeakers] = useState(false);
  const [timestamps, setTimestamps] = useState(false);
  const [compatible, setCompatible] = useState(false);
  const [device, setDevice] = useState("");
  const [inventory, setInventory] = useState<Inventory | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [installPending, setInstallPending] = useState(false);
  const [installStatus, setInstallStatus] = useState("");
  const lastQuery = useRef("");
  const busy = useRef(false);
  async function requestInstall(profile: NonNullable<CatalogItem["studio"]>) {
    if (!device || installPending) return;
    setInstallPending(true); setInstallStatus("");
    try {
      await mutateWithCsrfRetry(`/local-execution/devices/${device}/model-install`, csrf, onCsrf, {
        method: "POST", body: JSON.stringify({ model: profile.model, revision: profile.revision }),
      });
      setInstallStatus("Запрос передан. Откройте локальное приложение на выбранном ПК, подтвердите установку и укажите диск.");
    } catch {
      setInstallStatus("Установка не запрошена. Проверьте подключение компьютера и повторите.");
    } finally {
      setInstallPending(false);
    }
  }
  useEffect(() => {
    if (!device) return;
    const controller = new AbortController();
    let timer: number;
    async function refresh() {
      try {
        const reply = await api<{ inventory: Inventory | null }>(`/local-execution/devices/${device}/inventory`, { signal: controller.signal });
        if (!controller.signal.aborted) setInventory(reply.inventory);
      } catch {
        if (!controller.signal.aborted) setInventory(null);
      }
      if (!controller.signal.aborted) timer = window.setTimeout(() => void refresh(), 45_000);
    }
    void refresh();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [device]);

  async function load(cursor?: string) {
    if (busy.current) return;
    busy.current = true; setPending(true); setError("");
    const query = cursor ? new URLSearchParams(lastQuery.current)
      : new URLSearchParams({ search: search.trim(), language, sort, supported: String(supported || speakers || timestamps || compatible) });
    if (cursor) query.set("cursor", cursor);
    try {
      const page = await api<CatalogPage>(`/local-execution/catalog?${query}`);
      if (!cursor) lastQuery.current = query.toString();
      setItems(previous => cursor ? [...(previous ?? []), ...page.items.filter(item => !previous?.some(row => row.id === item.id))] : page.items);
      setNext(page.next_cursor);
    } catch {
      setError("Не удалось загрузить каталог Hugging Face. Повторите запрос позже.");
    } finally {
      busy.current = false; setPending(false);
    }
  }
  const visible = items?.filter(item => (!supported || item.studio)
    && (!speakers || item.studio?.diarization) && (!timestamps || item.studio?.word_timestamps)
    && (!compatible || suitability(item, inventory).startsWith("Подходит")));
  return <details>
    <summary>Каталог локальных речевых моделей</summary>
    <p>Поиск по всем моделям распознавания речи Hugging Face. Запуск в Studio доступен для поддерживаемых профилей.</p>
    <label>Компьютер для подбора<select value={device} onChange={event => { setDevice(event.target.value); setInventory(null); }}>
      <option value="">Без подбора под ПК</option>
      {devices.map(row => <option key={row.id} value={row.id}>{row.label}</option>)}
    </select></label>
    {device && (inventory ? <p>CPU {inventory.cpu} · RAM {gib(inventory.ram_bytes)} · На выбранном диске {gib(inventory.disk_free_bytes)}.
      GPU {inventory.gpus.map(gpu => `${gpu.name} (${gib(gpu.vram_bytes)})`).join(", ") || "нет данных"}. Пакет Studio использует CPU.</p>
      : <p>Недостаточно данных о ПК. Откройте локальный обработчик и дождитесь обновления.</p>)}
    <form onSubmit={event => { event.preventDefault(); void load(); }}>
      <label>Название модели<input type="search" maxLength={120} value={search} onChange={event => setSearch(event.target.value)} /></label>
      <label>Язык<select value={language} onChange={event => setLanguage(event.target.value)}>
        <option value="">Любой</option><option value="ru">Русский</option><option value="en">Английский</option>
      </select></label>
      <label><input type="checkbox" checked={supported} onChange={event => setSupported(event.target.checked)} /> Профили Studio</label>
      <label><input type="checkbox" checked={speakers} onChange={event => setSpeakers(event.target.checked)} /> Разделение спикеров</label>
      <label><input type="checkbox" checked={timestamps} onChange={event => setTimestamps(event.target.checked)} /> Таймкоды слов</label>
      <label><input type="checkbox" checked={compatible} onChange={event => setCompatible(event.target.checked)} /> Подтверждены пробой на этом ПК</label>
      <label>Сортировка<select value={sort} onChange={event => setSort(event.target.value)}>
        <option value="downloads">По загрузкам</option><option value="likes">По отметкам «Нравится»</option>
      </select></label>
      <button disabled={pending} type="submit">Найти модели</button>
    </form>
    {pending && <p role="status">Загружаем каталог…</p>}
    {error && <p role="alert">{error}</p>}
    {installStatus && <p role="status">{installStatus}</p>}
    {!pending && visible?.length === 0 && <p>На этой странице нет моделей по заданным фильтрам.</p>}
    {visible && <ul className="local-device-list">{visible.map(item => {
      const probe = inventory?.probes.find(value => value.model === item.studio?.model);
      return <li key={item.id}>
      <p><a href={item.source_url} target="_blank" rel="noreferrer">{item.studio?.name ?? item.id}</a></p>
      <p>{item.studio ? "Есть профиль Studio" : "Запуск в Studio пока не поддерживается"}</p>
      {item.studio && <p>Совместимость: {suitability(item, inventory)}. Установка: {inventory
        ? (inventory.installed.includes(item.studio.model) ? "файлы проверены" : "не подтверждена") : "нет данных"}.</p>}
      {item.studio && <p className="muted">Профиль использует CPU. {item.studio.diarization
        ? "Nemotron требует больше ресурсов и поддерживает разделение спикеров."
        : "Parakeet занимает меньше места. Этот профиль без разделения спикеров."}</p>}
      {probe && <p>Проба с холодным запуском: {probe.audio_seconds.toFixed(1)} с записи за {probe.elapsed_seconds.toFixed(1)} с.</p>}
      {item.studio && device && !inventory?.installed.includes(item.studio.model) && <button type="button"
        disabled={installPending} onClick={() => { if (item.studio) void requestInstall(item.studio); }}>Установить на выбранном ПК</button>}
      <p>Языки {((item.studio?.languages ?? item.languages).join(", ")) || "не указаны"} · Лицензия {item.license ?? "не указана"}</p>
      <p>Таймкоды {item.studio ? (item.studio.word_timestamps ? "есть" : "нет") : "не проверены"} · Разделение спикеров {item.studio ? (item.studio.diarization ? "есть" : "нет") : "не проверено"}</p>
      <p>Размер загрузки {item.studio ? `${(item.studio.download_bytes / 1073741824).toFixed(2)} ГиБ` : "не указан"} · Версия {(item.studio?.revision ?? item.hub_revision)?.slice(0, 12) ?? "не указана"}</p>
    </li>;
    })}</ul>}
    {next && <button type="button" disabled={pending} onClick={() => void load(next)}>Показать ещё модели</button>}
  </details>;
}
