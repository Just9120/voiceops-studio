import { useSyncExternalStore } from "react";
import { pwaUpdates, type PwaUpdateController } from "./pwaUpdates";

function subscribeConnectivity(notify: () => void) {
  window.addEventListener("online", notify);
  window.addEventListener("offline", notify);
  return () => {
    window.removeEventListener("online", notify);
    window.removeEventListener("offline", notify);
  };
}

function browserOnline() {
  return navigator.onLine;
}

export function PwaConnectivityNotice() {
  const online = useSyncExternalStore(subscribeConnectivity, browserOnline);
  return <div className="pwa-connectivity" role="status" hidden={online}>
    <strong>Устройство без сети</strong>
    <span>Проверьте подключение перед запуском или повтором серверной операции.</span>
  </div>;
}

export function PwaUpdateNotice({ controller = pwaUpdates }: { controller?: PwaUpdateController }) {
  const { visible, applying, error } = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
  );
  if (!visible) return null;
  return (
    <aside className="pwa-update-notice card" role="status" aria-live="polite" aria-busy={applying}>
      <div className="pwa-update-details">
        <strong>Доступна новая версия Studio</strong>
        <p>Обновите страницу, когда закончите ввод: несохранённые данные формы могут пропасть.</p>
        {error && <p className="error">Не удалось применить обновление. Повторите попытку.</p>}
      </div>
      <div className="pwa-update-actions">
        <button type="button" className="primary" disabled={applying} onClick={() => { void controller.apply(); }}>
          {applying ? "Обновляем…" : "Обновить сейчас"}
        </button>
        <button type="button" className="secondary" disabled={applying} onClick={() => controller.defer()}>
          Позже
        </button>
      </div>
    </aside>
  );
}
