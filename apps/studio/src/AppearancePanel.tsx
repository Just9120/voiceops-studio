import { useEffect, useState } from "react";
import {
  STUDIO_THEME_MEDIA_QUERY,
  type StudioAccentColor,
  type StudioThemePreference,
} from "./theme";

const themes = [
  { value: "light", label: "Светлая" },
  { value: "dark", label: "Тёмная" },
  { value: "system", label: "Системная" },
  { value: "oled", label: "OLED" },
] as const;
const accents = [
  { value: "blue", label: "Синий" },
  { value: "teal", label: "Бирюзовый" },
  { value: "violet", label: "Фиолетовый" },
  { value: "rose", label: "Розовый" },
] as const;
const descriptions: Record<StudioThemePreference, string> = {
  light: "Светлая тема интерфейса.",
  dark: "Тёмная тема интерфейса.",
  system: "По умолчанию Studio следует настройке ОС.",
  oled: "Тема OLED · Чёрный фон.",
};

type Props = {
  theme: StudioThemePreference;
  accent: StudioAccentColor;
  accentDisabled: boolean;
  message: string;
  onThemeChange: (theme: StudioThemePreference) => void;
  onAccentChange: (color: StudioAccentColor) => void;
};

export function AppearancePanel({
  theme,
  accent,
  accentDisabled,
  message,
  onThemeChange,
  onAccentChange,
}: Props) {
  const [osDark, setOsDark] = useState(
    () => window.matchMedia?.(STUDIO_THEME_MEDIA_QUERY).matches ?? false,
  );

  useEffect(() => {
    const media = window.matchMedia?.(STUDIO_THEME_MEDIA_QUERY);
    if (!media) return;
    const update = () => setOsDark(media.matches);
    update();
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, []);

  return (
    <section className="studio-appearance" aria-labelledby="appearance-settings-title">
      <h2 id="appearance-settings-title">Оформление</h2>
      <p className="muted">{descriptions[theme]}</p>
      <div className="card studio-appearance-card">
        <h3>Тема</h3>
        <div className="studio-appearance-options" role="group" aria-label="Тема интерфейса">
          {themes.map(({ label, value }) => (
            <button
              key={value}
              type="button"
              className="studio-appearance-option"
              aria-label={label}
              aria-pressed={theme === value}
              onClick={() => onThemeChange(value)}
            >
              <span>{label}</span>
              <span className="muted">{theme === value ? "Выбрана" : "Применить тему"}</span>
            </button>
          ))}
        </div>
        {theme === "oled" ? (
          <div className="studio-appearance-options" role="group" aria-label="Акцент OLED">
            {accents.map(({ label, value }) => (
              <button
                key={value}
                type="button"
                className="studio-appearance-option"
                aria-label={label}
                aria-pressed={accent === value}
                disabled={accentDisabled}
                onClick={() => onAccentChange(value)}
              >
                <span>{label}</span>
                <span className="muted">{accent === value ? "Выбран" : "Применить акцент OLED"}</span>
              </button>
            ))}
          </div>
        ) : (
          <>
            <dl className="studio-appearance-details">
              {theme === "system" && (
                <div>
                  <dt>Тема ОС</dt>
                  <dd>{osDark ? "Тёмная" : "Светлая"}</dd>
                </div>
              )}
              <div>
                <dt>Акцент</dt>
                <dd>Синий</dd>
              </div>
            </dl>
            <div className="studio-appearance-hint">
              <strong>Дополнительные акценты в OLED</strong>
              <span>Выберите OLED для бирюзового, фиолетового или розового.</span>
            </div>
          </>
        )}
        {message && <p className="notice" role="status">{message}</p>}
      </div>
    </section>
  );
}
