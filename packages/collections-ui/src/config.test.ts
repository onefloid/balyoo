import { afterEach, describe, expect, it, vi } from "vitest";

import { loadConfig } from "./config";

afterEach(() => vi.unstubAllGlobals());

describe("loadConfig", () => {
  it("parses a valid live config", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({ apiBase: "", static: false }),
      })),
    );
    expect(await loadConfig()).toEqual({ apiBase: "", static: false });
  });

  it("falls back to the read-only static mirror when config.json is missing", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, json: async () => ({}) })));
    expect(await loadConfig()).toEqual({ apiBase: "api/", static: true });
  });

  it("falls back when the request throws", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("network down");
      }),
    );
    expect(await loadConfig()).toEqual({ apiBase: "api/", static: true });
  });
});
