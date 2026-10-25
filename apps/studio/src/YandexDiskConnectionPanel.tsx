import { useEffect, useRef, useState } from "react";
import { api, mutateWithCsrfRetry } from "./apiClient";
import { ConfirmClearDialog } from "./ConfirmClearDialog";
import { runBoundedRequest } from "./jobMutationRequest";
import { diskFailureMessage } from "./YandexDiskPicker";

type Connection = { configured: boolean; connected: boolean; status: string };
function connectionPayload(raw: unknown): Connection {
  if (!raw || typeof raw !== "object") throw new Error("invalid_disk_connection");
  const row = raw as Partial<Connection>;
  if (typeof row.configured !== "boolean" || typeof row.connected !== "boolean" ||
      !["active", "revoked", "error", "not_connected"].includes(row.status || "")) throw new Error("invalid_disk_connection");
  return row as Connection;
}

export function YandexDiskConnectionPanel({ csrf, onCsrf }: { csrf: string; onCsrf: (value: string) => void }) {
  const [connection, setConnection] = useState<Connection | null>(null);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [confirm, setConfirm] = useState(false);
  const alive = useRef(true);
  const readVersion = useRef(0);
  const callback = useRef<string | null>(null);
  useEffect(() => {
    alive.current = true;
    const url = new URL(window.location.href);
    callback.current = url.searchParams.get("yandex_oauth");
    if (callback.current !== null) {
      url.searchParams.delete("yandex_oauth");
      window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
    }
    void load();
    return () => { alive.current = false; readVersion.current += 1; };
  }, []);

  async function load() {
    const version = ++readVersion.current;
    if (alive.current) setLoading(true);
    try {
      const result = await runBoundedRequest((signal) => api<unknown>("/yandex/connection", { signal }));
      if (result.status !== "completed") throw new Error("timeout");
      const row = connectionPayload(result.value);
      if (!alive.current || version !== readVersion.current) return null;
      setConnection(row);
      if (callback.current) {
        setMessage(callback.current === "connected" && row.connected ? "Яндекс Диск подключён."
          : callback.current === "cancelled" ? "Подключение Яндекс Диска отменено."
          : "Не удалось завершить подключение Яндекс Диска. Запустите подключение ещё раз.");
        callback.current = null;
      }
      return row;
    } catch {
      if (alive.current && version === readVersion.current) setMessage("Не удалось проверить подключение Яндекс Диска. Повторите проверку.");
      return null;
    } finally { if (alive.current && version === readVersion.current) setLoading(false); }
  }

  async function connect() {
    if (pending) return;
    setPending(true); setMessage("");
    try {
      const result = await runBoundedRequest((signal) => mutateWithCsrfRetry<{ authorization_url: string }>(
        "/yandex/oauth/start", csrf, onCsrf, { method: "POST", signal }));
      if (result.status !== "completed") throw new Error("timeout");
      const url = new URL(result.value.authorization_url);
      if (url.origin !== "https://oauth.yandex.ru" || url.pathname !== "/authorize" || url.username || url.password) throw new Error("invalid_oauth_url");
      if (alive.current) window.location.assign(url.href);
    } catch (error) { if (alive.current) setMessage(diskFailureMessage(error)); }
    finally { if (alive.current) setPending(false); }
  }

  async function disconnect() {
    if (pending) return;
    setPending(true); setMessage("");
    try {
      const result = await runBoundedRequest((signal) => mutateWithCsrfRetry<{ disconnected: boolean; remote_revocation_confirmed: boolean }>(
        "/yandex/connection", csrf, onCsrf, { method: "DELETE", signal }));
      const state = await load();
      if (!alive.current) return;
      if (!state || state.connected) throw new Error("disconnect_unconfirmed");
      setMessage(result.status === "completed" && result.value.remote_revocation_confirmed
        ? "Яндекс Диск отключён. Доступ отозван."
        : "Подключение удалено из Studio. Отзыв доступа на стороне Яндекса не подтверждён; при необходимости отзовите его в настройках Яндекс ID.");
      setConfirm(false);
    } catch (error) {
      const observed = await load();
      if (alive.current) {
        if (observed && !observed.connected) {
          setMessage("Яндекс Диск отключён в Studio. Отзыв доступа на стороне Яндекса не подтверждён.");
          setConfirm(false);
        } else setMessage(diskFailureMessage(error));
      }
    }
    finally { if (alive.current) setPending(false); }
  }

  return <article className="card" aria-labelledby="yandex-disk-connection-title">
    <h3 id="yandex-disk-connection-title">Яндекс Диск</h3>
    <p>Отдельное подключение для чтения записей и сохранения транскрипций как DOCX.</p>
    <p role="status">{loading ? "Проверяем подключение…" : connection === null ? "Состояние подключения не подтверждено." : connection.connected ? "Яндекс Диск подключён." : "Яндекс Диск не подключён."}</p>
    {connection && !connection.configured && <p className="notice">Подключение ещё не настроено администратором.</p>}
    {message && <p className="notice" role="status">{message}</p>}
    <div className="actions"><button type="button" className="primary" disabled={loading || pending || !connection?.configured} aria-busy={pending || undefined} onClick={() => void connect()}>{connection?.connected ? "Переподключить Яндекс Диск" : "Подключить Яндекс Диск"}</button>
      {connection?.connected && <button type="button" disabled={loading || pending} onClick={() => setConfirm(true)}>Отключить Яндекс Диск</button>}
      <button type="button" disabled={loading || pending} onClick={() => void load()}>Обновить статус</button></div>
    <p className="muted">Переподключение не требует предварительного отключения. Файлы на Диске не удаляются.</p>
    {confirm && <ConfirmClearDialog title="Отключить Яндекс Диск?" description="Studio удалит токены подключения и попробует отозвать доступ у Яндекса. Исходные файлы и документы сохранятся." pending={pending} onConfirm={() => void disconnect()} onCancel={() => setConfirm(false)} />}
  </article>;
}
