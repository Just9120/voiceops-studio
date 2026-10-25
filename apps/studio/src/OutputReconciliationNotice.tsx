import type { OutputReconciliationState } from "./jobRecoveryModel";

export function OutputReconciliationNotice({
  jobId,
  state,
  onCheck,
  outputProvider = "google_drive",
}: {
  jobId: string;
  state: OutputReconciliationState;
  onCheck: (jobId: string) => void | Promise<void>;
  outputProvider?: "google_drive" | "yandex_disk";
}) {
  const location = outputProvider === "yandex_disk" ? "на Яндекс Диске" : "в Google Drive";
  return (
    <section className="notice" aria-label={`Проверка результата ${location}`}>
      <b>Требуется проверка {outputProvider === "yandex_disk" ? "документа DOCX" : "результата Google Docs"}</b>
      <p>
        Studio проверит, появился ли документ {location}, и не будет
        создавать его повторно.
      </p>
      <button
        type="button"
        disabled={state.checking}
        aria-busy={state.checking}
        onClick={() => void onCheck(jobId)}
      >
        {state.checking
          ? `Проверяем ${outputProvider === "yandex_disk" ? "Яндекс Диск" : "Google Drive"}…`
          : `Проверить созданный документ ${location}`}
      </button>
      {state.message && <p role="status">{state.message}</p>}
      {state.error && <p className="error">{state.error}</p>}
    </section>
  );
}
