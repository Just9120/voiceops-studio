export const STUDIO_THEME_STORAGE_KEY = "studio-theme-preference";
export const STUDIO_THEME_MEDIA_QUERY = "(prefers-color-scheme: dark)";

export type StudioThemePreference = "system" | ResolvedStudioTheme;
export type ResolvedStudioTheme = "light" | "dark" | "oled";
export const STUDIO_ACCENT_COLORS = ["blue", "violet", "teal", "rose"] as const;
export type StudioAccentColor = (typeof STUDIO_ACCENT_COLORS)[number];

const THEME_COLORS: Record<ResolvedStudioTheme, string> = {
  light: "#eff2f7",
  dark: "#151c29",
  oled: "#000000",
};

function isStudioThemePreference(value: unknown): value is StudioThemePreference {
  return value === "system" || value === "light" || value === "dark" || value === "oled";
}

export function isStudioAccentColor(value: unknown): value is StudioAccentColor {
  return STUDIO_ACCENT_COLORS.some((color) => color === value);
}

export function applyStudioAccentColor(
  color: StudioAccentColor,
  documentRef: Document = document,
) {
  documentRef.documentElement.dataset.accent = color;
  return color;
}

export function readStudioThemePreference(
  storage?: Pick<Storage, "getItem">,
): StudioThemePreference {
  try {
    const stored = (storage ?? window.localStorage).getItem(
      STUDIO_THEME_STORAGE_KEY,
    );
    return isStudioThemePreference(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

export function resolveStudioTheme(
  preference: StudioThemePreference,
  systemPrefersDark: boolean,
): ResolvedStudioTheme {
  if (preference === "system") return systemPrefersDark ? "dark" : "light";
  return preference;
}

function currentSystemPrefersDark() {
  return window.matchMedia?.(STUDIO_THEME_MEDIA_QUERY).matches ?? false;
}

export function applyStudioTheme(
  preference: StudioThemePreference,
  systemPrefersDark = currentSystemPrefersDark(),
  documentRef: Document = document,
) {
  const resolved = resolveStudioTheme(preference, systemPrefersDark);
  documentRef.documentElement.dataset.theme = resolved;
  documentRef.documentElement.dataset.themePreference = preference;
  documentRef.documentElement.style.colorScheme = resolved === "light" ? "light" : "dark";
  documentRef
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", THEME_COLORS[resolved]);
  return resolved;
}

export function setStudioThemePreference(
  preference: StudioThemePreference,
  storage?: Pick<Storage, "setItem">,
) {
  try {
    (storage ?? window.localStorage).setItem(
      STUDIO_THEME_STORAGE_KEY,
      preference,
    );
  } catch {
    // A blocked storage API must not prevent applying a non-sensitive UI choice.
  }
  return applyStudioTheme(preference);
}

let systemListenerInstalled = false;

export function initializeStudioTheme() {
  const preference = readStudioThemePreference();
  const media = window.matchMedia?.(STUDIO_THEME_MEDIA_QUERY);
  applyStudioTheme(preference, media?.matches ?? false);
  if (!systemListenerInstalled && media?.addEventListener) {
    systemListenerInstalled = true;
    media.addEventListener("change", (event) => {
      const applied = document.documentElement.dataset.themePreference;
      const current = isStudioThemePreference(applied)
        ? applied
        : readStudioThemePreference();
      if (current === "system") applyStudioTheme(current, event.matches);
    });
  }
  return preference;
}
