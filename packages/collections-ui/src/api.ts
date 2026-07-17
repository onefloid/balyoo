// The single boundary between the UI and the platform. Reads are identical in both
// deployments; only the live REST client can write. The UI still gates write UI on
// reported capabilities, so a static deployment never even offers a write.

import type { AppConfig } from "./config";
import type {
  CollectionInfo,
  Item,
  ItemQuery,
  JsonSchema,
  Page,
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly details?: string[],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ApiClient {
  readonly canWrite: boolean;
  listCollections(): Promise<CollectionInfo[]>;
  getCollection(collection: string): Promise<CollectionInfo>;
  getSchema(collection: string): Promise<JsonSchema>;
  listItems(collection: string, query?: ItemQuery): Promise<Page<Item>>;
  getItem(collection: string, id: string): Promise<Item>;
  createItem(collection: string, data: Record<string, unknown>): Promise<Item>;
  updateItem(
    collection: string,
    id: string,
    patch: Record<string, unknown>,
  ): Promise<Item>;
  deleteItem(collection: string, id: string): Promise<void>;
}

/** Fetch JSON, mapping a non-2xx response to an ApiError carrying server details. */
async function requestJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    let details: string[] | undefined;
    try {
      const body = await res.json();
      if (typeof body?.error === "string") message = body.error;
      if (Array.isArray(body?.details)) details = body.details as string[];
    } catch {
      /* non-JSON error body: keep the status text */
    }
    throw new ApiError(res.status, message, details);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const WRITES_UNSUPPORTED =
  "This is a static, read-only deployment; writes are not available.";

/** Read-only client for the exported static JSON mirror (paths suffixed `.json`). */
class StaticJsonClient implements ApiClient {
  readonly canWrite = false;
  private readonly root: URL;

  constructor(apiBase: string) {
    this.root = new URL(apiBase, document.baseURI);
  }

  private url(path: string): string {
    return new URL(`${path}.json`, this.root).toString();
  }

  listCollections() {
    return requestJSON<CollectionInfo[]>(this.url("collections"));
  }
  getCollection(collection: string) {
    return requestJSON<CollectionInfo>(this.url(`collections/${collection}`));
  }
  getSchema(collection: string) {
    return requestJSON<JsonSchema>(this.url(`collections/${collection}/schema`));
  }
  listItems(collection: string) {
    // The mirror's items file holds every item; search/sort happen client-side.
    return requestJSON<Page<Item>>(this.url(`collections/${collection}/items`));
  }
  getItem(collection: string, id: string) {
    return requestJSON<Item>(this.url(`collections/${collection}/items/${id}`));
  }
  createItem(): Promise<Item> {
    return Promise.reject(new ApiError(405, WRITES_UNSUPPORTED));
  }
  updateItem(): Promise<Item> {
    return Promise.reject(new ApiError(405, WRITES_UNSUPPORTED));
  }
  deleteItem(): Promise<void> {
    return Promise.reject(new ApiError(405, WRITES_UNSUPPORTED));
  }
}

const JSON_HEADERS = { "content-type": "application/json" };

/** Full CRUD client for a live `collections serve` REST API. */
class RestClient implements ApiClient {
  readonly canWrite = true;
  private readonly root: URL;

  constructor(apiBase: string) {
    this.root = new URL(apiBase, document.baseURI);
  }

  private url(path: string): string {
    return new URL(path, this.root).toString();
  }

  listCollections() {
    return requestJSON<CollectionInfo[]>(this.url("collections"));
  }
  getCollection(collection: string) {
    return requestJSON<CollectionInfo>(this.url(`collections/${collection}`));
  }
  getSchema(collection: string) {
    return requestJSON<JsonSchema>(this.url(`collections/${collection}/schema`));
  }
  listItems(collection: string, query: ItemQuery = {}) {
    const params = new URLSearchParams();
    // Default to a large page so the table has the full set to search/sort over,
    // matching the static mirror's single-file behaviour.
    params.set("limit", String(query.limit ?? 1000));
    if (query.offset) params.set("offset", String(query.offset));
    if (query.q) params.set("q", query.q);
    if (query.sort) params.set("sort", query.sort);
    if (query.order) params.set("order", query.order);
    return requestJSON<Page<Item>>(
      this.url(`collections/${collection}/items?${params}`),
    );
  }
  getItem(collection: string, id: string) {
    return requestJSON<Item>(this.url(`collections/${collection}/items/${id}`));
  }
  createItem(collection: string, data: Record<string, unknown>) {
    return requestJSON<Item>(this.url(`collections/${collection}/items`), {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(data),
    });
  }
  updateItem(collection: string, id: string, patch: Record<string, unknown>) {
    return requestJSON<Item>(this.url(`collections/${collection}/items/${id}`), {
      method: "PATCH",
      headers: JSON_HEADERS,
      body: JSON.stringify(patch),
    });
  }
  deleteItem(collection: string, id: string) {
    return requestJSON<void>(this.url(`collections/${collection}/items/${id}`), {
      method: "DELETE",
    });
  }
}

export function makeClient(config: AppConfig): ApiClient {
  return config.static
    ? new StaticJsonClient(config.apiBase)
    : new RestClient(config.apiBase);
}
