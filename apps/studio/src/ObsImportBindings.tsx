import { useEffect, useState } from "react";
import { api, mutateWithCsrfRetry } from "./apiClient";
import { ConfirmClearDialog } from "./ConfirmClearDialog";
import { LocalDeviceEnrollment } from "./LocalDeviceEnrollment";
import { localExecutionFailure } from "./localExecutionContracts";
import { runBoundedRequest } from "./jobMutationRequest";

type Binding = { id: string; label: string; created_at: string };

export function ObsImportBindings({ csrf, onCsrf }: { csrf: string; onCsrf: (token: string) => void }) {
  const requestId = /^#obs-enrollment=([a-f0-9-]{36})$/.exec(window.location.hash)?.[1];
  const [open, setOpen] = useState(Boolean(requestId));
  const [bindings, setBindings] = useState<Binding[] | null>(null);
  const [selected, setSelected] = useState<Binding | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [pending, setPending] = useState(false);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setError("");
    void api<{ bindings: Binding[] }>("/obs-import/bindings", { signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) setBindings(result.bindings);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError("Не удалось загрузить привязки OBS.");
      });
    return () => controller.abort();
  }, [open, refresh]);

  async function revoke() {
    if (!selected || pending) return;
    setPending(true);
    setError("");
    setStatus("");
    try {
      const response = await runBoundedRequest((signal) => mutateWithCsrfRetry<{ ok: boolean }>(
        `/obs-import/bindings/${selected.id}`, csrf, onCsrf, { method: "DELETE", signal },
      ));
      if (response.status !== "completed" || response.value.ok !== true) throw new Error("obs_revoke_unconfirmed");
      setBindings((current) => current?.filter((row) => row.id !== selected.id) ?? null);
      setSelected(null);
      setStatus("Привязка OBS отозвана.");
    } catch (failure) {
      setError(localExecutionFailure(failure));
    } finally {
      setPending(false);
    }
  }

  return <details className="card" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>Импорт аудио из OBS</summary>
    {requestId && <LocalDeviceEnrollment key={requestId} requestId={requestId} csrf={csrf} onCsrf={onCsrf} obs />}
    <p>Выберите импорт OBS при установке Companion. Затем откройте «VoiceOps Studio — импорт OBS» в меню «Пуск».</p>
    <button type="button" onClick={() => setRefresh((value) => value + 1)}>Обновить привязки OBS</button>
    {error && !selected && <p role="alert" className="error">{error}</p>}
    {status && <p role="status">{status}</p>}
    {bindings?.length === 0 && <p>Импорт OBS ещё не привязан.</p>}
    {!!bindings?.length && <ul className="local-device-list">
      {bindings.map((row) => <li key={row.id} className="split">
        <div><strong>{row.label}</strong><p>Привязка от {new Date(row.created_at).toLocaleString("ru-RU")}</p></div>
        <button type="button" onClick={() => { setError(""); setSelected(row); }}>Отозвать доступ OBS</button>
      </li>)}
    </ul>}
    {selected && <ConfirmClearDialog title={`Отозвать доступ «${selected.label}»?`}
      description="Импортёр перестанет добавлять аудио в Studio. Существующие черновики и записи OBS сохранятся."
      confirmLabel="Отозвать" cancelLabel="Отмена" pending={pending} error={error}
      onConfirm={() => void revoke()} onCancel={() => { setSelected(null); setError(""); }} />}
  </details>;
}
