import { useEffect, useState } from "react";
import type { SettingsSection } from "./platformRouting";
import type { CollectionPage } from "./projectCollectionContracts";
import { readStudioThemePreference } from "./theme";
import { TranscriptionAnalyticsPanel } from "./TranscriptionAnalyticsPanel";

const themeNames = { system: "Системная", light: "Светлая", dark: "Тёмная", oled: "OLED" } as const;

const settingsGroups = [
  {
    title: "Основное",
    items: [
      { section: "appearance", name: "Оформление", detail: "" },
      { section: "account", name: "Аккаунт и безопасность", detail: "Пароль, 2FA и сессии" },
      { section: "connections", name: "Подключения", detail: "Облачные диски и провайдеры распознавания" },
      { section: "notifications", name: "Уведомления", detail: "Доставка в Telegram" },
    ],
  },
  {
    title: "Управление",
    items: [
      { section: "files", name: "Хранилище", detail: "Сроки хранения и очистка" },
      { section: "analytics", name: "Аналитика и расход", detail: "Задания и расчётная стоимость" },
      { section: "diagnostics", name: "Поддержка", detail: "Диагностика и состояние системы" },
      { section: "devices", name: "Windows Companion", detail: "Связанные компьютеры и модели" },
    ],
  },
] as const;

export function SettingsLanding({
  onSelect,
  onBack,
}: {
  onSelect: (section: SettingsSection) => void;
  onBack: () => void;
}) {
  const theme = readStudioThemePreference();
  return (
    <section className="settings-landing">
      <header className="workspace-heading">
        <h1 className="page-title">Настройки</h1>
        <p>Управляйте подключениями, внешним видом и данными.</p>
      </header>
      <div className="settings-landing-grid">
        {settingsGroups.map(({ title, items }) => (
          <section className="card settings-landing-panel" key={title} aria-label={title}>
            <h2>{title}</h2>
            {items.map(({ section, name, detail }) => (
              <button className="settings-landing-entry" type="button" key={section}
                aria-label={name} onClick={() => onSelect(section)}>
                <strong>{name}</strong>
                <small>{detail || themeNames[theme]}</small>
              </button>
            ))}
          </section>
        ))}
      </div>
      <footer className="workspace-action-bar">
        <button type="button" onClick={onBack}>К обзору</button>
      </footer>
    </section>
  );
}

type WorkspaceListItem = { id: string; archived_at: string | null };

export function SettingsAnalytics({
  csrf,
  requestProjects,
  onCsrf,
}: {
  csrf: string;
  onCsrf: (csrf: string) => void;
  requestProjects: (signal: AbortSignal, cursor: string | null) => Promise<CollectionPage<WorkspaceListItem>>;
}) {
  const [attempt, setAttempt] = useState(0);
  const [workspace, setWorkspace] = useState<string | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    const request = new AbortController();
    const timeout = window.setTimeout(() => request.abort(), 15_000);
    let disposed = false;
    const findWorkspace = async () => {
      let cursor: string | null = null;
      do {
        const page = await requestProjects(request.signal, cursor);
        const active = page.items.find((item) => item.archived_at === null);
        if (active) return active.id;
        cursor = page.nextCursor;
      } while (cursor !== null);
      return null;
    };
    void findWorkspace()
      .then((workspaceId) => {
        if (disposed) return;
        setWorkspace(workspaceId);
        setStatus("ready");
      })
      .catch(() => {
        if (!disposed) setStatus("error");
      })
      .finally(() => window.clearTimeout(timeout));
    return () => {
      disposed = true;
      window.clearTimeout(timeout);
      request.abort();
    };
  }, [attempt, requestProjects]);

  if (status === "loading") return <p role="status">Загружаем аналитику…</p>;
  if (status === "error") return (
    <div className="notice" role="status">
      <p>Не удалось открыть аналитику.</p>
      <button type="button" onClick={() => { setStatus("loading"); setAttempt((value) => value + 1); }}>Повторить</button>
    </div>
  );
  if (!workspace) return <p className="notice">Аналитика появится после создания рабочей области.</p>;
  return <TranscriptionAnalyticsPanel projectId={workspace} csrf={csrf} onCsrf={onCsrf} />;
}
