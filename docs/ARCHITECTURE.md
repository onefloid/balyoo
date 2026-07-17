# Architecture

Collections is a generic, schema-driven platform for storing, validating,
searching and serving arbitrary structured objects. Nothing is tailored to a
specific use case (books, movies, …) — everything is driven by JSON Schema.

## Layers

```
    REST API · Web UI · MCP server
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
| `collections-core`         | `collections_core`       | Models, capabilities, interfaces, errors, `CollectionsService`, shared query engine (`query.run_query`). Only depends on pydantic. |
| `collections-schema`       | `collections_schema`     | `JsonSchemaValidator` (implements `SchemaValidator`). |
| `collections-filesystem`   | `collections_filesystem` | `FilesystemStorageProvider` — full CRUD, ids stored as JSON files. |
| `collections-sqlite`       | `collections_sqlite`     | `SqliteStorageProvider` — durable, transactional CRUD in a SQLite database. |
| `collections-rest`         | `collections_rest`       | `create_app(service)` — fully generic FastAPI. |
| `collections-mcp`          | `collections_mcp`        | MCP server (stdio + token-secured HTTP) exposing every collection as tools, generated from schemas. |
| `collections-static`       | `collections_static`     | Static export: JSON API mirror + a `config.json` for the UI. |
| `collections-ui`           | `collections_ui` (TS)    | Generic React/Vite frontend: table, search, detail, schema-generated create/edit (RJSF). The one TypeScript package. |
| `collections-cli`          | `collections_cli`        | cyclopts CLI; composition layer that wires everything together. |

Both storage providers reuse `collections_core.query.run_query` for
filter/search/sort/paginate, so results are identical across backends. Switching a
deployment from the filesystem provider to SQLite needs no change to any adapter —
the REST API, UI and MCP server depend only on the core interfaces.

Planned (placeholder directories exist): `collections-postgres`,
`collections-search-lunr`, `collections-auth-basic`.

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

## MCP server

`collections-mcp` exposes the same platform to AI assistants over the Model Context
Protocol (stdio; launched by `collections mcp`). It is another adapter over
`CollectionsService` — no business logic is duplicated — and the tool set is
**generated from the platform**:

- Generic reads: `list_collections`, `get_schema`, `list_items` (`q`/sort/paginate),
  `get_item`.
- Per collection, `create_<c>` / `update_<c>` whose **input schema is the
  collection's JSON Schema** (presentation keywords `$schema`/`x-card`/`x-collection`
  stripped; update relaxes `required` to just `id`). This is what MCP adds over
  REST: the assistant gets typed, validated write tools instead of an opaque blob.
- `delete_item`.

The tool logic is transport-agnostic (`build_tools` / `dispatch` in
`collections_mcp.server`) and unit-tested without a live client. Writes are
advertised only when capabilities allow (`--read-only` ⇒ read tools only), the same
capability rule the REST API and UI follow. Domain errors become `isError` tool
results carrying the message (and a `SchemaValidationError`'s field list).

**Transports.** `collections mcp` serves **stdio** (local hosts like Claude
Desktop) by default. `--http` serves the remote **Streamable HTTP** transport for a
cloud LLM (`collections_mcp.http`), protected by a **static bearer token**: every
request to `/mcp` must carry `Authorization: Bearer <COLLECTIONS_MCP_TOKEN>`,
compared in constant time, or gets a `401` — no identity provider required. The
token only gates access; capabilities come from CLI flags (`--read-only`,
`--no-delete`), the same capability gating the REST API and UI follow. Pass
`--allow-anonymous` to serve without a token. A `Dockerfile` (non-root, uv-cached) +
`fly.toml` deploy it with a durable volume, and a public `/health` endpoint backs the
platform health check.

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

### Static export (`collections-static`)

`collections export` (→ `collections_static.export_site`) walks the service and
writes a static site under `dist/`:

- `dist/api/…` — a JSON mirror of the REST routes (`collections.json`,
  `collections/<c>.json`, `<c>/schema.json`, `<c>/items.json`,
  `<c>/items/<id>.json`). Index/manifest files let a client discover collections
  and item ids without a directory listing. The bodies are `model_dump()` of the
  same pydantic models the REST API returns, so the shape is identical.
- `dist/config.json` — `{"apiBase": "api/", "static": true}`, read at runtime by
  `collections-ui` so it targets the mirror in read-only mode. Export runs with
  `read_only=True`, so capabilities report no writes and the UI shows none.

The generator only calls existing `CollectionsService` methods — no business logic
is duplicated, and it never clobbers files already in the output directory (the
UI bundle is placed there first). `.github/workflows/deploy-pages.yml` builds the
UI, assembles it with the mirror, and deploys `dist/` to GitHub Pages.

## Web UI (`collections-ui`)

A single React/Vite/TypeScript app, fully generic: every view — collection list,
a **table** and a modern **card** view with client-side search/sort, item detail,
and **create/edit forms generated from JSON Schema** (via RJSF) — works for any
collection. It depends only on the generic API.

**Schema-driven cards.** The card (tile) layout and the collection's default view
are chosen by an optional `x-card` block in the collection's schema (`default` of
`"list"`/`"cards"`, plus `title` / `subtitle` / `image` / `badges` / `fields`, each
naming a property); when absent, `resolveCardConfig`
(`packages/collections-ui/src/card.ts`) derives one — title from `title`/`name`,
array fields as chips, remaining scalars as key/value rows, defaulting to the list
view. `x-card` is a custom keyword, ignored by JSON Schema validators, so it never
affects data validation (it is also stripped before the schema reaches RJSF). A
viewer's List/Cards choice is remembered per collection (`localStorage`) and
overrides the schema default.

**Collection avatar.** A collection's home-page symbol is set by an optional
`x-collection` block (`icon`, an emoji, and `color`, a hex accent) resolved by
`resolveCollectionMeta` (`packages/collections-ui/src/collection.ts`); without it a
coloured monogram is derived from the name. `color` is validated as a hex value
before it reaches an inline style, so an arbitrary string cannot inject CSS.

**One build, many deployments.** A runtime `config.json` selects the data source:
the live REST API (`{"apiBase": "", "static": false}`, full CRUD) or the static
JSON mirror (`{"apiBase": "api/", "static": true}`, GET-only, `.json`-suffixed).
An `ApiClient` abstraction (`StaticJsonClient` / `RestClient`) hides the
difference; reads are identical, and the app builds with a relative base so the
same bundle runs at a domain root or a project sub-path.

**Capability-adaptive.** Write controls (New / Edit / Delete) render only when the
collection's reported capabilities allow them. Because the static export advertises
no writes, the same UI is safely read-only there. The server remains the
authoritative validator; RJSF/AJV is a client-side convenience.

A read-write deployment can serve the built bundle from the API origin with
`collections serve --ui <dir>` (a `StaticFiles` mount registered after the API
routes), so no separate host or CORS setup is needed.
