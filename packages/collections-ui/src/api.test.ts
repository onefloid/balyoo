import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, makeClient } from "./api";

function mockFetch(response: {
  ok?: boolean;
  status?: number;
  statusText?: string;
  body?: unknown;
}) {
  const fn = vi.fn(async (_url: string, _init?: RequestInit) => ({
    ok: response.ok ?? true,
    status: response.status ?? 200,
    statusText: response.statusText ?? "OK",
    json: async () => response.body ?? {},
  }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("client selection", () => {
  it("uses the read-only static client when config.static is true", () => {
    const client = makeClient({ apiBase: "api/", static: true });
    expect(client.canWrite).toBe(false);
  });

  it("uses the read-write REST client when config.static is false", () => {
    const client = makeClient({ apiBase: "", static: false });
    expect(client.canWrite).toBe(true);
  });
});

describe("static JSON client suffixes paths with .json", () => {
  const client = makeClient({ apiBase: "api/", static: true });

  it("lists collections from collections.json", async () => {
    const fetchMock = mockFetch({ body: [] });
    await client.listCollections();
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/collections\.json$/);
  });

  it("reads an item from its .json file under items/", async () => {
    const fetchMock = mockFetch({ body: { id: "dune", data: {} } });
    await client.getItem("books", "dune");
    expect(fetchMock.mock.calls[0][0]).toMatch(
      /\/api\/collections\/books\/items\/dune\.json$/,
    );
  });

  it("rejects writes with a 405 ApiError", async () => {
    mockFetch({ body: {} });
    await expect(client.createItem("books", { title: "x" })).rejects.toBeInstanceOf(
      ApiError,
    );
  });
});

describe("REST client hits routes without .json", () => {
  const client = makeClient({ apiBase: "", static: false });

  it("lists items with a query string and no suffix", async () => {
    const fetchMock = mockFetch({ body: { items: [], total: 0 } });
    await client.listItems("books", { q: "dune" });
    const url = fetchMock.mock.calls[0][0];
    expect(url).toContain("/collections/books/items?");
    expect(url).not.toContain(".json");
    expect(url).toContain("q=dune");
  });

  it("creates an item with a POST body", async () => {
    const fetchMock = mockFetch({ status: 201, body: { id: "x", data: {} } });
    await client.createItem("books", { title: "The Hobbit" });
    const [, init] = fetchMock.mock.calls[0];
    expect(init).toMatchObject({ method: "POST" });
    expect(JSON.parse(init!.body as string)).toEqual({
      title: "The Hobbit",
    });
  });
});

describe("error mapping", () => {
  it("surfaces the server's 422 details on the ApiError", async () => {
    mockFetch({
      ok: false,
      status: 422,
      statusText: "Unprocessable Entity",
      body: { error: "Schema validation failed", details: ["title: required"] },
    });
    const client = makeClient({ apiBase: "", static: false });
    await expect(client.createItem("books", {})).rejects.toMatchObject({
      status: 422,
      message: "Schema validation failed",
      details: ["title: required"],
    });
  });
});
