// Mirrors the *fixed* pydantic models the platform exposes (collections_core.models
// and .capabilities). The dynamic item content is an untyped object validated
// against the collection's JSON Schema, exactly as on the server.

export interface Capabilities {
  supports_read: boolean;
  supports_write: boolean;
  supports_delete: boolean;
  supports_search: boolean;
  supports_transactions: boolean;
}

export interface Item {
  id: string;
  data: Record<string, unknown>;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface CollectionInfo {
  name: string;
  capabilities: Capabilities;
  item_count: number;
}

/** A JSON Schema document (draft 2020-12). Kept loose here; RJSF narrows it. */
export type JsonSchema = Record<string, unknown>;

/** Optional constraints for listing items (honoured by the live REST client). */
export interface ItemQuery {
  q?: string;
  sort?: string;
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}
