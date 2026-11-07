import { useEffect, useRef, useState } from "react";
import { mutateWithCsrfRetry } from "./apiClient";
import { ActionMenu } from "./ActionMenu";
import { ConfirmClearDialog } from "./ConfirmClearDialog";
import { CompanionRelease } from "./CompanionRelease";
import { LocalDeviceEnrollment } from "./LocalDeviceEnrollment";
import { LocalModelCatalog } from "./LocalModelCatalog";
import { runBoundedRequest } from "./jobMutationRequest";
import { localDeviceStatus, localExecutionFailure, parseLocalDevice, useLocalExecutionDevices, type LocalExecutionDevice } from "./localExecutionContracts";

export function LocalExecutionPanel({ csrf, onCsrf }: { csrf: string; onCsrf: (value: string) => void }) {
  const enrollmentId = /^#local-enrollment=([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$/.exec(window.location.hash)?.[1];
  const devices = useLocalExecutionDevices();
  const [label, setLabel] = useState("");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [secret, setSecret] = useState<{ label: string; token: string } | null>(null);
  const [attempt, setAttempt] = useState<{ label: string; creation_key: string } | null>(null);
  const [confirm, setConfirm] = useState<{ row: LocalExecutionDevice; action: "rotate" | "revoke" } | null>(null);
  const [confirmError, setConfirmError] = useState("");
  const busy = useRef(false);
  const alive = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  async function apply(action: "pair" | "rotate" | "revoke", row?: LocalExecutionDevice) {
    if (busy.current) return;
    busy.current = true; setPending(true); setMessage(""); setConfirmError(""); setSecret(null);
    const pairing = action === "pair" ? attempt ?? { label: label.trim(), creation_key: crypto.randomUUID() } : null;
    if (pairing) setAttempt(pairing);
    try {
      const path = "/local-execution/devices" + (row ? `/${row.id}/${action}` : "");
      const body = pairing ?? { expected_revision: row!.credential_revision };
      const result = await runBoundedRequest(signal => mutateWithCsrfRetry<{
        device: unknown; pairing_token?: string | null;
      }>(path, csrf, onCsrf, { method: "POST", body: JSON.stringify(body), signal }));
      if (result.status !== "completed" || !parseLocalDevice(result.value.device)) throw new Error("local_mutation_unconfirmed");
      if (action !== "revoke" && result.value.pairing_token !== null &&
        (typeof result.value.pairing_token !== "string" || !/^vs-local\.[a-f0-9-]{36}\.[A-Za-z0-9_-]{43}$/.test(result.value.pairing_token))) throw new Error("invalid_pairing_token");
      if (!alive.current) return;
      setConfirm(null);
      if (pairing) { setAttempt(null); setLabel(""); }
      if (result.value.pairing_token) setSecret({ label: parseLocalDevice(result.value.device)!.label, token: result.value.pairing_token });
      setMessage(action === "revoke" ? "Доступ компьютера отозван. Файлы и готовые результаты сохранены."
        : result.value.pairing_token ? "Ключ создан. Введите его в обработчик на своём компьютере."
        : "Этот компьютер уже подключён. Ключ повторно не выдаётся: выберите «Заменить ключ», если первый ответ был потерян.");
      window.dispatchEvent(new Event("studio:local-devices-changed"));
      await devices.refresh();
    } catch (error) {
      if (alive.current) {
        const explanation = localExecutionFailure(error);
        setMessage(explanation); if (row) setConfirmError(explanation);
        await devices.refresh();
      }
    } finally {
      busy.current = false; if (alive.current) setPending(false);
    }
  }
  return <article className="card" aria-labelledby="local-execution-title">
    <h3 id="local-execution-title">Локальные модели на Windows</h3>
    {enrollmentId && <LocalDeviceEnrollment key={enrollmentId} requestId={enrollmentId} csrf={csrf} onCsrf={onCsrf} />}
    <CompanionRelease />
    <LocalModelCatalog devices={devices.items} csrf={csrf} onCsrf={onCsrf} />
    <p>Распознавание выполняется на выбранном Windows-компьютере. Обработчик должен быть запущен; Studio сохраняет результат и создаёт документ. Автоматического перехода на облачный сервис нет.</p>
    <p className="muted">Поддерживаются русский и английский языки. Nemotron обрабатывает записи или фрагменты до 60 минут, Parakeet — до 24 минут. Скорость зависит от компьютера.</p>
    <details><summary>Ручная настройка существующего обработчика</summary>
      <ol><li>Подготовьте локальную модель и обработчик по инструкции <code>docs/runbooks/local-worker.md</code> в проекте.</li>
        <li>Введите название компьютера ниже и создайте ключ.</li>
        <li>На компьютере запустите <code>python scripts/voiceops_local_worker.py pair</code>. Ключ вводится скрыто в запрос обработчика.</li>
        <li>Запустите <code>python scripts/voiceops_local_worker.py run</code> и дождитесь статуса «Готов к работе».</li></ol>
      <p>Ключ даёт обработчику доступ только к назначенным ему задачам. Не передавайте его другим людям.</p>
    </details>
    {devices.error && <p role="alert" className="notice">{devices.error}</p>}
    <div className="actions"><button type="button" disabled={devices.loading || pending} onClick={() => void devices.refresh()}>{devices.loading ? "Обновляем компьютеры…" : "Обновить компьютеры"}</button></div>
    {!devices.loading && !devices.error && devices.items.length === 0 && <p>Компьютеры ещё не подключены.</p>}
    <ul className="local-device-list">{devices.items.map(row => <li key={row.id} className="split">
      <div><strong>{row.label}</strong><p>{localDeviceStatus(row)}</p>{row.last_seen_at && <small className="muted">На связи: {new Date(row.last_seen_at).toLocaleString("ru-RU")}</small>}</div>
      <ActionMenu label={`Действия компьютера ${row.label}`} disabled={pending} items={[
        { id: "rotate", label: "Заменить ключ", onSelect: () => { setConfirmError(""); setConfirm({ row, action: "rotate" }); } },
        { id: "revoke", label: "Отозвать доступ", danger: true, onSelect: () => { setConfirmError(""); setConfirm({ row, action: "revoke" }); } },
      ]} />
    </li>)}</ul>
    <form onSubmit={event => { event.preventDefault(); if (label.trim() || attempt) void apply("pair"); }}>
      <label>Название компьютера<input value={attempt?.label ?? label} disabled={pending || !!attempt} maxLength={80} autoComplete="off" onChange={event => setLabel(event.target.value)} placeholder="Например, домашний ПК" /></label>
      <div className="actions"><button type="submit" disabled={pending || (!attempt && (!label.trim() || devices.items.length >= 8))} aria-busy={pending || undefined}>{pending ? "Подтверждаем…" : attempt ? "Повторить тот же запрос подключения" : "Подключить компьютер"}</button></div>
    </form>
    {message && <p role="status" className="notice">{message}</p>}
    {secret && <section className="notice" aria-label="Одноразовый ключ компьютера">
      <p>Ключ для «{secret.label}» показывается только сейчас. После закрытия его нельзя прочитать повторно.</p>
      <label>Ключ подключения<input type="password" readOnly value={secret.token} autoComplete="off" spellCheck={false} /></label>
      <div className="actions"><button type="button" onClick={() => {
        void (async () => {
          try { await navigator.clipboard.writeText(secret.token); if (alive.current) setMessage("Ключ скопирован. Вставьте его в скрытый запрос обработчика."); }
          catch { if (alive.current) setMessage("Не удалось скопировать ключ. Выделите значение поля и скопируйте вручную."); }
        })();
      }}>Скопировать ключ</button><button type="button" onClick={() => setSecret(null)}>Скрыть ключ</button></div>
    </section>}
    {confirm && <ConfirmClearDialog title={confirm.action === "revoke" ? `Отозвать доступ «${confirm.row.label}»?` : `Заменить ключ «${confirm.row.label}»?`}
      description="Старый ключ перестанет работать. Незавершённое распознавание этого компьютера будет остановлено; принятые результаты и документы сохранятся. Для продолжения потребуется новый ключ и явный повтор задачи."
      confirmLabel={confirm.action === "revoke" ? "Отозвать доступ" : "Заменить ключ"} cancelLabel="Отмена" pending={pending} error={confirmError}
      onConfirm={() => void apply(confirm.action, confirm.row)} onCancel={() => setConfirm(null)} />}
  </article>;
}
