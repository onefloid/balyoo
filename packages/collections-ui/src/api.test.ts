import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  FallbackClient,
  RestClient,
  StaticJsonClient,
  makeClient,
} from "./api";
import type { ApiClient } from "./api";
import type { CollectionInfo } from "./types";

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

describe("FallbackClient", () => {
  const collections: CollectionInfo[] = [
    {
      name: "books",
      capabilities: {
        supports_read: true,
        supports_write: false,
        supports_delete: false,
        supports_search: true,
        supports_transactions: true,
      },
      item_count: 2,
    },
  ];

  /** A minimal stub client whose reads resolve or reject as configured. */
  function stub(overrides: Partial<ApiClient>): ApiClient {
    const reject = () => Promise.reject(new Error("not stubbed"));
    return {
      canWrite: false,
      listCollections: reject,
      getCollection: reject,
      getSchema: reject,
      listItems: reject,
      getItem: reject,
      createItem: reject,
      updateItem: reject,
      deleteItem: reject,
      ...overrides,
    } as ApiClient;
  }

  it("passes primary results through and never calls onFallback on success", async () => {
    const onFallback = vi.fn();
    const primary = stub({ listCollections: () => Promise.resolve(collections) });
    const fallback = stub({});
    const client = new FallbackClient(primary, fallback, onFallback);

    expect(await client.listCollections()).toEqual(collections);
    expect(onFallback).not.toHaveBeenCalled();
  });

  it("falls back to the static client when the live client throws (network/CORS)", async () => {
    const onFallback = vi.fn();
    const primary = stub({
      listCollections: () => Promise.reject(new TypeError("Failed to fetch")),
    });
    const fallback = stub({ listCollections: () => Promise.resolve(collections) });
    const client = new FallbackClient(primary, fallback, onFallback);

    expect(await client.listCollections()).toEqual(collections);
    expect(onFallback).toHaveBeenCalledTimes(1);
  });

  it("falls back on a 5xx (cold-start/gateway) error", async () => {
    const onFallback = vi.fn();
    const primary = stub({
      listCollections: () => Promise.reject(new ApiError(503, "Service Unavailable")),
    });
    const fallback = stub({ listCollections: () => Promise.resolve(collections) });
    const client = new FallbackClient(primary, fallback, onFallback);

    expect(await client.listCollections()).toEqual(collections);
    expect(onFallback).toHaveBeenCalledTimes(1);
  });

  it("does NOT fall back on a 404 (a real answer from a reachable server)", async () => {
    const onFallback = vi.fn();
    const primary = stub({
      getItem: () => Promise.reject(new ApiError(404, "Not found")),
    });
    const fallback = stub({
      getItem: () => Promise.resolve({ id: "x", data: {} }),
    });
    const client = new FallbackClient(primary, fallback, onFallback);

    await expect(client.getItem("books", "missing")).rejects.toMatchObject({
      status: 404,
    });
    expect(onFallback).not.toHaveBeenCalled();
  });

  it("notifies onFallback only once across repeated failures", async () => {
    const onFallback = vi.fn();
    const primary = stub({
      listCollections: () => Promise.reject(new TypeError("down")),
      getSchema: () => Promise.reject(new TypeError("down")),
    });
    const fallback = stub({
      listCollections: () => Promise.resolve(collections),
      getSchema: () => Promise.resolve({}),
    });
    const client = new FallbackClient(primary, fallback, onFallback);

    await client.listCollections();
    await client.getSchema("books");
    expect(onFallback).toHaveBeenCalledTimes(1);
  });

  it("sends writes to the live client, not the static mirror", async () => {
    const created = { id: "x", data: { title: "T" } };
    const createItem = vi.fn(() => Promise.resolve(created));
    const primary = stub({ canWrite: true, createItem });
    const fallback = stub({});
    const client = new FallbackClient(primary, fallback, () => {});

    expect(client.canWrite).toBe(true);
    expect(await client.createItem("books", { title: "T" })).toEqual(created);
    expect(createItem).toHaveBeenCalledTimes(1);
  });
});

describe("exported client classes", () => {
  it("RestClient can write, StaticJsonClient cannot", () => {
    expect(new RestClient("").canWrite).toBe(true);
    expect(new StaticJsonClient("api/").canWrite).toBe(false);
  });
});
