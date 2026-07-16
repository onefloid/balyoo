# Architecture

Collections is a generic, schema-driven platform for storing, validating,
searching and serving arbitrary structured objects. Nothing is tailored to a
specific use case (books, movies, …) — everything is driven by JSON Schema.

## Layers

```
        REST API        (later: MCP server, Web UI, …)
             │
        Collections Core            ← business logic only; knows only interfaces
             │
   StorageProvider · SchemaValidator · SearchProvider   (Protocols)
             │
        Filesystem provider   (later: SQLite, Postgres, S3, Git, …)
```

The dependency direction always points **inward** toward the core. The core never
imports FastAPI, `jsonschema`, or any concrete backend. Adapters depend on the
core, not the other way around.

## Packages (uv workspace)

| Package                    | Import root              | Responsibility |
|----------------------------|--------------------------|----------------|
| `collections-core`         | `collections_core`       | Models, capabilities, interfaces, errors, `CollectionsService`. Only depends on pydantic. |
| `collections-schema`       | `collections_schema`     | `JsonSchemaValidator` (implements `SchemaValidator`). |
| `collections-filesystem`   | `collections_filesystem` | `FilesystemStorageProvider` — full CRUD + in-memory query/search. |
| `collections-rest`         | `collections_rest`       | `create_app(service)` — fully generic FastAPI. |
| `collections-cli`          | `collections_cli`        | cyclopts CLI; composition layer that wires everything together. |

Planned (placeholder directories exist): `collections-mcp`, `collections-ui` (TS),
`collections-sqlite`, `collections-postgres`, `collections-search-lunr`,
`collections-auth-basic`.

## Key ideas

**Schema first.** Each collection has a JSON Schema that drives validation, API
docs (FastAPI's auto-generated OpenAPI), and later form generation and MCP tool
descriptions. The *dynamic* item content lives in `Item.data` as a `dict` and is
validated with `jsonschema`; pydantic models describe only the *fixed* structures
(`Query`, `Page`, `Item`, `CollectionInfo`, `Capabilities`).

**Capabilities.** Each provider advertises what it supports
(`supports_read/write/delete/search/transactions`). The `CollectionsService`
enforces them and can additionally run `read_only=True`, which masks
write/delete. This is how the *same* application serves both read-only (e.g.
static hosting) and read-write (e.g. a database) deployments with an identical
API and UI.

**Storage independence.** The service is written entirely against the
`StorageProvider` protocol. The test suite exercises the core against an
in-memory fake provider (`tests/conftest.py`) to prove this independence
structurally, not just by convention.

## REST API

Every route is generic — there are no collection-specific endpoints.

```
GET    /collections
GET    /collections/{c}
GET    /collections/{c}/schema
GET    /collections/{c}/items          ?limit&offset&sort&order&q&<field>=<value>
GET    /collections/{c}/items/{id}
POST   /collections/{c}/items
PATCH  /collections/{c}/items/{id}
DELETE /collections/{c}/items/{id}
```

Domain errors map to HTTP status codes in `collections_rest.app`:
`CollectionNotFound`/`ItemNotFound` → 404, `SchemaValidationError` → 422 (with a
`details` list), `NotSupported` → 405, `Conflict` → 409.

## Static-first data layout

```
collections/
  books/
    schema.json
    items/
      dune.json
      lotr.json
  movies/
    schema.json
    items/
      matrix.json
```

This is exactly what the filesystem provider reads and writes, and it is directly
deployable as static files for read-only hosting (GitHub/Cloudflare/Netlify/Vercel
Pages) without a server or database.
