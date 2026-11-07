import { useEffect, useState } from "react";
import { api, ApiError } from "./apiClient";

type Release = { version: string; sha256: string; bytes: number; signed: false };

export function CompanionRelease() {
  const [release, setRelease] = useState<Release | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void api<Release>("/local-execution/companion-release", { signal: controller.signal }).then(value => {
      if (!controller.signal.aborted && value.signed === false && /^[a-f0-9]{64}$/.test(value.sha256)
        && /^\d{1,6}\.\d{1,6}\.\d{1,6}$/.test(value.version) && Number.isSafeInteger(value.bytes) && value.bytes > 0) {
        setRelease(value);
      }
    }).catch((failure: unknown) => {
      if (!controller.signal.aborted && !(failure instanceof ApiError && failure.status === 404)) setError(true);
    });
    return () => controller.abort();
  }, []);
  if (error) return <p role="status">Не удалось проверить доступность установщика.</p>;
  if (!release) return null;
  return <section className="notice" aria-labelledby="companion-release-title">
    <h4 id="companion-release-title">Подключить компьютер</h4>
    <p>Закрытая тестовая сборка для Windows x64, версия {release.version}, {Math.ceil(release.bytes / 1048576)} МиБ.
      Установщик не подписан. Сверьте SHA‑256 скачанного файла перед запуском.</p>
    <p>SHA‑256 <code style={{ overflowWrap: "anywhere" }}>{release.sha256}</code></p>
    <p>Запустите установщик и подтвердите подключение в браузере. Модели устанавливаются отдельно.</p>
    <a className="button-like" href={`/api/local-execution/companion-release/${release.sha256}/download`}>Скачать установщик Windows</a>
  </section>;
}
