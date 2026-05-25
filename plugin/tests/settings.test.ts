import { DEFAULT_SETTINGS } from "../src/settings";

describe("DEFAULT_SETTINGS", () => {
  test("has output folder under _todo/ideas", () => {
    expect(DEFAULT_SETTINGS.outputFolder).toBe("_todo/ideas/vibe-coding");
  });

  test("server url defaults to mrbear929 tools path", () => {
    expect(DEFAULT_SETTINGS.serverUrl).toMatch(/mrbear929\.com\/pitch$/);
  });

  test("poll defaults are sane", () => {
    expect(DEFAULT_SETTINGS.pollIntervalMs).toBeGreaterThanOrEqual(1000);
    expect(DEFAULT_SETTINGS.pollTimeoutMs).toBeGreaterThanOrEqual(5 * 60_000);
  });
});
