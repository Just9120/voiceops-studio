import type { Page } from "./platformRouting";
import { PublicInfoLinks } from "./PublicInfoLinks";

const platformNav: { id: Page; label: string; compactLabel?: string }[] = [
  { id: "dashboard", label: "Обзор" },
  { id: "audio", label: "Подготовка аудио", compactLabel: "Аудио" },
  { id: "projects", label: "Транскрибации" },
  { id: "settings", label: "Настройки" },
];

export function PlatformTopbar({ page }: { page: Page }) {
  return (
    <header className="app-topbar">
      <span>{platformNav.find(({ id }) => id === page)?.label}</span>
      <span className="app-personal-badge">Personal</span>
    </header>
  );
}

export function PlatformSidebar({
  page,
  onNavigate,
}: {
  page: Page;
  onNavigate: (page: Page) => void;
}) {
  return (
    <aside className="app-sidebar">
      <div className="app-brand">
        <img src="/icons/voiceops-brand.svg" width="32" height="32" alt="" />
        <span>VoiceOps Studio</span>
        <span className="app-personal-badge">Studio</span>
      </div>
      <nav className="app-nav" aria-label="Основная навигация">
        {platformNav.map(({ id, label, compactLabel }) => (
          <button
            type="button"
            className={page === id ? "active" : undefined}
            aria-current={page === id ? "page" : undefined}
            aria-label={label}
            onClick={() => onNavigate(id)}
            key={id}
          >
            <span className={compactLabel ? "app-nav-wide-label" : undefined}>{label}</span>
            {compactLabel && <span className="app-nav-compact-label">{compactLabel}</span>}
          </button>
        ))}
      </nav>
      <div className="app-sidebar-footer">
        <span>Личный аккаунт</span>
        <PublicInfoLinks compact />
      </div>
    </aside>
  );
}
