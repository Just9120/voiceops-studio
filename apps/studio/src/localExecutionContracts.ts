import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./apiClient";

export const LOCAL_MODEL = "NVIDIA-Nemotron-3.5-Transcribe-30B-A4B";
export const PARAKEET_MODEL = "parakeet-tdt-0.6b-v3.q8_0";
export type LocalModelSelection = { model: string; revision: string };
export function localModelName(model: string | null) {
  if (model === LOCAL_MODEL) return "Nemotron 3.5 Transcribe";
  if (model === PARAKEET_MODEL) return "Parakeet TDT 0.6B v3";
  return "Модель не подтверждена";
}
export type LocalExecutionDevice = {
  id: string; label: string; credential_revision: number; online: boolean; ready: boolean;
  runtime_status: "unknown" | "loading_model" | "ready" | "model_missing" | "runtime_missing" | "runtime_error";
  runtime_version: string | null; model: string | null; last_seen_at: string | null; revoked_at: string | null;
  model_revision?: string | null;
};
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const statuses = ["unknown", "loading_model", "ready", "model_missing", "runtime_missing", "runtime_error"];
function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}
export function parseLocalDevice(raw: unknown): LocalExecutionDevice | null {
  if (!record(raw) || typeof raw.id !== "string" || !uuid.test(raw.id)
    || typeof raw.label !== "string" || !raw.label.trim() || raw.label.length > 80
    || !Number.isSafeInteger(raw.credential_revision) || Number(raw.credential_revision) < 1
    || typeof raw.online !== "boolean" || typeof raw.ready !== "boolean" || !statuses.includes(String(raw.runtime_status))
    || ![raw.runtime_version, raw.model].every(value => value === null || typeof value === "string")
    || ![raw.last_seen_at, raw.revoked_at].every(value => value === null || typeof value === "string" && Number.isFinite(Date.parse(value)))) return null;
  if (raw.model_revision != null && (typeof raw.model_revision !== "string" || !/^[a-f0-9]{40}$/.test(raw.model_revision))) return null;
  if (raw.ready && (!raw.online || raw.runtime_status !== "ready" || raw.last_seen_at === null || raw.revoked_at !== null ||
    (raw.model !== LOCAL_MODEL && (raw.model !== PARAKEET_MODEL || !raw.model_revision)))) return null;
  return raw as LocalExecutionDevice;
}
export function parseLocalDevices(raw: unknown): LocalExecutionDevice[] {
  if (!record(raw) || !Array.isArray(raw.devices) || raw.devices.length > 8) throw new Error("invalid_local_devices");
  const rows = raw.devices.map(parseLocalDevice);
  if (rows.some(row => !row || row.revoked_at !== null) || new Set(rows.map(row => row?.id)).size !== rows.length) throw new Error("invalid_local_devices");
  return rows as LocalExecutionDevice[];
}
export function localDeviceReady(row: LocalExecutionDevice, now = Date.now()) {
  const seen = row.last_seen_at === null ? NaN : Date.parse(row.last_seen_at);
  // A stale last successful response cannot keep an offline PC selectable.
  return row.ready && row.revoked_at === null && now - seen >= 0 && now - seen <= 90_000;
}
export function localDeviceStatus(row: LocalExecutionDevice, now = Date.now()) {
  if (row.revoked_at) return "Доступ отозван";
  if (!row.online || row.last_seen_at === null || now - Date.parse(row.last_seen_at) > 90_000) return "Компьютер не на связи";
  if (localDeviceReady(row, now)) return "Готов к работе";
  const labels = { unknown: "Состояние модели ещё не подтверждено", loading_model: "Загружается модель",
    ready: "Нужная модель не подтверждена", model_missing: "Файлы модели не найдены",
    runtime_missing: "Обработчик не найден", runtime_error: "Ошибка локального обработчика" };
  return labels[row.runtime_status];
}
export function localExecutionFailure(error: unknown) {
  const data = error instanceof ApiError && record(error.data) ? error.data : null;
  const detail = data && record(data.detail) ? data.detail : data;
  const reason = detail?.reason;
  if (reason === "recent_reauthentication_required") return "Подтвердите пароль и 2FA в разделе «Аккаунт», затем повторите действие.";
  if (reason === "local_device_limit") return "Можно подключить до 8 компьютеров. Отзовите доступ ненужного компьютера.";
  if (reason === "local_device_changed") return "Состояние компьютера изменилось. Обновите список и повторите действие с актуальным состоянием.";
  if (reason === "local_device_not_ready") return "Выбранный компьютер не готов. Запустите его обработчик и дождитесь статуса «Готов к работе».";
  if (reason === "local_device_model_changed") return "Компьютер сейчас использует другую версию модели. Запустите назначенную версию и обновите список.";
  return "Не удалось подтвердить действие. Обновите список; при повторе подключения Studio проверит тот же запрос без создания дубля.";
}

export function useLocalExecutionDevices(enabled = true) {
  const [items, setItems] = useState<LocalExecutionDevice[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [checkedAt, setCheckedAt] = useState(0);
  const epoch = useRef(0);
  const request = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    const version = ++epoch.current;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 20_000);
    setLoading(true);
    try {
      const rows = parseLocalDevices(await api<unknown>("/local-execution/devices", { signal: controller.signal }));
      if (epoch.current !== version) return null;
      setItems(rows); setError(""); setCheckedAt(Date.now());
      return rows;
    } catch {
      if (epoch.current === version) setError("Не удалось обновить список компьютеров. Проверьте соединение и повторите.");
      return null;
    } finally {
      window.clearTimeout(timeout);
      if (epoch.current === version) { request.current = null; setLoading(false); }
    }
  }, []);
  useEffect(() => {
    if (!enabled) return;
    void refresh();
    const update = () => { if (document.visibilityState !== "hidden" && !request.current) void refresh(); };
    const timer = window.setInterval(update, 15_000);
    document.addEventListener("visibilitychange", update);
    window.addEventListener("focus", update);
    window.addEventListener("studio:local-devices-changed", update);
    return () => {
      ++epoch.current; request.current?.abort(); request.current = null;
      window.clearInterval(timer); document.removeEventListener("visibilitychange", update);
      window.removeEventListener("focus", update); window.removeEventListener("studio:local-devices-changed", update);
    };
  }, [enabled, refresh]);
  return { items, loading, error, checkedAt, refresh };
}
