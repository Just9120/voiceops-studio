import { useEffect, useState } from "react";
import { api, ApiError } from "./apiClient";

type Release = { version: string; sha256: string; bytes: number; signed: false };
type ReleaseState = { status: "loading" | "missing" | "invalid" | "error" | "timeout" }
  | { status: "ready"; release: Release };

const RELEASE_TIMEOUT_MS = 15_000;

function isRelease(value: unknown): value is Release {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<Release>;
  return candidate.signed === false && typeof candidate.sha256 === "string" && /^[a-f0-9]{64}$/.test(candidate.sha256)
    && typeof candidate.version === "string" && /^\d{1,6}\.\d{1,6}\.\d{1,6}$/.test(candidate.version)
    && typeof candidate.bytes === "number" && Number.isSafeInteger(candidate.bytes) && candidate.bytes > 0;
}

export function CompanionRelease() {
  const [state, setState] = useState<ReleaseState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      controller.abort();
      setState({ status: "timeout" });
    }, RELEASE_TIMEOUT_MS);
    void api<unknown>("/local-execution/companion-release", { signal: controller.signal }).then(value => {
      if (!controller.signal.aborted) {
        setState(isRelease(value) ? { status: "ready", release: value } : { status: "invalid" });
      }
    }).catch((failure: unknown) => {
      if (!controller.signal.aborted) {
        setState({ status: failure instanceof ApiError && failure.status === 404 ? "missing" : "error" });
      }
    }).finally(() => window.clearTimeout(timeout));
    return () => { window.clearTimeout(timeout); controller.abort(); };
  }, [attempt]);

  const messages = {
    loading: "Проверяем доступность установщика Windows…",
    missing: "Установщик Windows сейчас недоступен.",
    invalid: "Данные об установщике не прошли проверку. Скачивание недоступно.",
    error: "Не удалось проверить доступность установщика.",
    timeout: "Studio не дождалась ответа об установщике. Попробуйте ещё раз.",
  };
  const release = state.status === "ready" ? state.release : null;
  return <section className="notice" aria-labelledby="companion-release-title">
    <h4 id="companion-release-title">Подключить компьютер</h4>
    {state.status !== "ready" && <>
      <p role="status">{messages[state.status]}</p>
      {state.status !== "loading" && <button type="button" onClick={() => {
        setState({ status: "loading" });
        setAttempt(value => value + 1);
      }}>Проверить установщик снова</button>}
    </>}
    {release && <>
    <p>Закрытая тестовая сборка для Windows x64, версия {release.version}, {Math.ceil(release.bytes / 1048576)} МиБ.
      Установщик не подписан. Сверьте SHA‑256 скачанного файла перед запуском.</p>
    <p>SHA‑256 <code style={{ overflowWrap: "anywhere" }}>{release.sha256}</code></p>
    <p>Запустите установщик и подтвердите подключение в браузере. Модели устанавливаются отдельно.</p>
    <a className="button-like" href={`/api/local-execution/companion-release/${release.sha256}/download`}>Скачать установщик Windows</a>
    </>}
  </section>;
}
