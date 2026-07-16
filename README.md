# balyoo

**Schema-first collections for humans and AI.**

Collections is a generic platform for storing, validating, searching and serving
arbitrary structured objects — books, movies, employees, products, APIs, … You
describe a collection with a JSON Schema, pick a storage provider, and the
validation, CRUD, REST API (and, later, MCP server and web UI) come for free.

> **Milestone 1 (this repo):** a working vertical slice in Python — core, schema
> validation, a filesystem storage provider with full CRUD, a fully generic REST
> API, and a CLI, with example collections. See
> [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design and the
> roadmap (MCP, UI, SQLite/Postgres, pluggable search & auth).

## Quick start

```bash
uv sync

# CLI (defaults to ./examples/collections)
uv run collections list
uv run collections schema books
uv run collections items list books --q dune
uv run collections items get books dune

# REST API (auto-generated OpenAPI docs at /docs)
uv run collections serve
#   GET  http://127.0.0.1:8000/collections
#   POST http://127.0.0.1:8000/collections/books/items   {"title": "..."}

# Same API, read-only — writes return HTTP 405, reads still work
uv run collections serve --read-only
```

## How it fits together

```
        REST API / CLI          (later: MCP server, Web UI)
             │
        Collections Core        ← business logic; depends only on interfaces
             │
   StorageProvider · SchemaValidator · SearchProvider
             │
        Filesystem provider     (later: SQLite, Postgres, S3, Git, …)
```

The core knows nothing about REST, MCP or any database. Storage, search and auth
are pluggable; a read-only static deployment and a read-write database deployment
share the exact same API and UI. Details in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Development

```bash
uv sync
uv run ruff check .
uv run pytest
```

## License

Apache-2.0
