import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  applyStudioAccentColor,
  applyStudioTheme,
  readStudioThemePreference,
  resolveStudioTheme,
  setStudioThemePreference,
  STUDIO_THEME_STORAGE_KEY,
} from "./theme";

describe("Studio theme preference", () => {
  beforeEach(() => {
    window.localStorage.clear();
    delete document.documentElement.dataset.theme;
    delete document.documentElement.dataset.themePreference;
    delete document.documentElement.dataset.accent;
    document.documentElement.style.colorScheme = "";
    let themeColor = document.querySelector<HTMLMetaElement>(
      'meta[name="theme-color"]',
    );
    if (!themeColor) {
      themeColor = document.createElement("meta");
      themeColor.name = "theme-color";
      document.head.append(themeColor);
    }
    themeColor.content = "#315efb";
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({
        matches: false,
        media: "(prefers-color-scheme: dark)",
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    );
  });

  it("defaults invalid or absent storage to the system preference", () => {
    expect(readStudioThemePreference()).toBe("system");
    window.localStorage.setItem(STUDIO_THEME_STORAGE_KEY, "unknown");
    expect(readStudioThemePreference()).toBe("system");
    expect(resolveStudioTheme("system", true)).toBe("dark");
    expect(resolveStudioTheme("system", false)).toBe("light");
  });

  it("persists and immediately applies an explicit dark theme", () => {
    expect(setStudioThemePreference("dark")).toBe("dark");
    expect(window.localStorage.getItem(STUDIO_THEME_STORAGE_KEY)).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.dataset.themePreference).toBe("dark");
    expect(document.documentElement.style.colorScheme).toBe("dark");
    expect(
      document.querySelector('meta[name="theme-color"]')?.getAttribute("content"),
    ).toBe("#151c29");
  });

  it("restores the OLED preference and uses dark browser controls", () => {
    expect(setStudioThemePreference("oled")).toBe("oled");
    expect(readStudioThemePreference()).toBe("oled");
    expect(document.documentElement.dataset.theme).toBe("oled");
    expect(document.documentElement.style.colorScheme).toBe("dark");
    expect(document.querySelector('meta[name="theme-color"]')?.getAttribute("content")).toBe("#000000");
  });

  it("resolves the system choice without persisting the resolved value", () => {
    expect(applyStudioTheme("system", true)).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.dataset.themePreference).toBe("system");
    expect(window.localStorage.getItem(STUDIO_THEME_STORAGE_KEY)).toBeNull();
  });

  it("survives a blocked localStorage getter during bootstrap and updates", () => {
    const getter = vi
      .spyOn(window, "localStorage", "get")
      .mockImplementation(() => {
        throw new DOMException("blocked", "SecurityError");
      });

    expect(readStudioThemePreference()).toBe("system");
    expect(() => setStudioThemePreference("dark")).not.toThrow();
    expect(document.documentElement.dataset.theme).toBe("dark");

    getter.mockRestore();
  });

  it("applies a supported owner accent without browser persistence", () => {
    expect(applyStudioAccentColor("teal")).toBe("teal");
    expect(document.documentElement.dataset.accent).toBe("teal");
    expect(window.localStorage.length).toBe(0);
  });
});
