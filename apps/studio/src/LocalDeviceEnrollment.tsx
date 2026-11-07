import { useEffect, useState } from "react";
import { ApiError, api, mutateWithCsrfRetry } from "./apiClient";
import { localExecutionFailure } from "./localExecutionContracts";

type Enrollment = { label: string; approved: boolean };

function enrollmentView(value: unknown): Enrollment {
  if (!value || typeof value !== "object" || !("label" in value) || typeof value.label !== "string"
    || !value.label || value.label.length > 80 || !("approved" in value) || typeof value.approved !== "boolean") {
    throw new Error("invalid_local_enrollment");
  }
  return { label: value.label, approved: value.approved };
}

function enrollmentError(error: unknown) {
  if (error instanceof ApiError && error.status === 410) {
    return "Запрос истёк. Начните подключение заново в приложении на компьютере.";
  }
  return localExecutionFailure(error);
}

export function LocalDeviceEnrollment({ requestId, csrf, onCsrf }: {
  requestId: string;
  csrf: string;
  onCsrf: (value: string) => void;
}) {
  const [view, setView] = useState<Enrollment | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const path = `/local-execution/enrollment/${requestId}`;

  useEffect(() => {
    const controller = new AbortController();
    void api<unknown>(path, { signal: controller.signal })
      .then((response) => {
        if (!controller.signal.aborted) setView(enrollmentView(response));
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) setError(enrollmentError(failure));
      });
    return () => controller.abort();
  }, [path]);

  async function approve() {
    if (!view || view.approved || busy) return;
    setBusy(true);
    setError("");
    try {
      const approved = enrollmentView(await mutateWithCsrfRetry<unknown>(
        path + "/approve", csrf, onCsrf, { method: "POST" },
      ));
      if (!approved.approved) throw new Error("local_enrollment_unconfirmed");
      setView(approved);
    } catch (failure) {
      setError(enrollmentError(failure));
    } finally {
      setBusy(false);
    }
  }

  return <section className="notice" aria-labelledby="local-enrollment-title">
    <h4 id="local-enrollment-title">Подключение компьютера</h4>
    {error && <p role="alert">{error}</p>}
    {!view && !error && <p role="status">Проверяем запрос…</p>}
    {view?.approved && <p role="status">Подключение «{view.label}» подтверждено. Вернитесь в приложение на компьютере.</p>}
    {view && !view.approved && <>
      <p>Подключить «{view.label}» к вашему аккаунту Studio? Подтвердите запрос, если вы запустили подключение на этом компьютере.</p>
      <button type="button" className="primary" disabled={busy} onClick={() => void approve()}>
        {busy ? "Подтверждаем…" : "Подтвердить подключение"}
      </button>
    </>}
  </section>;
}
