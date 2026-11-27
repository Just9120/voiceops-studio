import {
  parsePlatformRoute,
  platformPathFor,
  pushPlatformRoute,
} from "./platformRouting";

describe("platform routing", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.history.replaceState({}, "", "/");
  });

  it.each([
    ["/", { page: "dashboard", settingsSection: "account" }],
    ["/audio", { page: "audio", settingsSection: "account" }],
    ["/transcriptions", { page: "projects", settingsSection: "account" }],
    ["/projects", { page: "projects", settingsSection: "account" }],
    ["/settings", { page: "settings", settingsSection: "overview" }],
    ["/settings/account", { page: "settings", settingsSection: "account" }],
    ["/settings/devices", { page: "settings", settingsSection: "devices" }],
    ["/settings/analytics", { page: "settings", settingsSection: "analytics" }],
    [
      "/settings/connections",
      { page: "settings", settingsSection: "connections" },
    ],
    [
      "/settings/notifications",
      { page: "settings", settingsSection: "notifications" },
    ],
    ["/settings/files", { page: "settings", settingsSection: "files" }],
    [
      "/settings/appearance",
      { page: "settings", settingsSection: "appearance" },
    ],
    [
      "/settings/diagnostics",
      { page: "settings", settingsSection: "diagnostics" },
    ],
    ["/unknown", { page: "dashboard", settingsSection: "account" }],
  ])("parses %s", (pathname, expected) => {
    expect(parsePlatformRoute(pathname)).toEqual(expected);
  });

  it("reads the browser pathname when no path is provided", () => {
    window.history.replaceState({}, "", "/transcriptions");

    expect(parsePlatformRoute()).toEqual({
      page: "projects",
      settingsSection: "account",
    });
  });

  it.each([
    ["dashboard", "account", "/"],
    ["audio", "account", "/audio"],
    ["projects", "account", "/transcriptions"],
    ["settings", "overview", "/settings"],
    ["settings", "account", "/settings/account"],
    ["settings", "devices", "/settings/devices"],
    ["settings", "analytics", "/settings/analytics"],
    ["settings", "connections", "/settings/connections"],
    ["settings", "notifications", "/settings/notifications"],
    ["settings", "files", "/settings/files"],
    ["settings", "appearance", "/settings/appearance"],
    ["settings", "diagnostics", "/settings/diagnostics"],
  ] as const)("builds the %s/%s path", (page, section, expected) => {
    expect(platformPathFor(page, section)).toBe(expected);
  });

  it("pushes a changed route while preserving history state", () => {
    const state = { source: "routing-test" };
    window.history.replaceState(state, "", "/");
    const pushState = vi.spyOn(window.history, "pushState");

    pushPlatformRoute("settings", "diagnostics");

    expect(pushState).toHaveBeenCalledWith(
      state,
      "",
      "/settings/diagnostics",
    );
    expect(window.location.pathname).toBe("/settings/diagnostics");
  });

  it("does not add a duplicate history entry", () => {
    window.history.replaceState({}, "", "/transcriptions");
    const pushState = vi.spyOn(window.history, "pushState");

    pushPlatformRoute("projects");

    expect(pushState).not.toHaveBeenCalled();
  });
});
