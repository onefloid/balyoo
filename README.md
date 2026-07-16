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

# Export a static, server-less site (JSON API mirror + minimal read-only UI)
uv run collections export --root examples/collections --out dist
python -m http.server -d dist 8080   # then open http://localhost:8080/
```

## Static deployment (GitHub Pages)

`collections export` produces a fully static site — no server, no database:

- `dist/api/…` — JSON files whose layout mirrors the REST routes
  (`collections.json`, `<c>/schema.json`, `<c>/items.json`, `<c>/items/<id>.json`),
  so the same client works against a live server or a static host.
- `dist/index.html` — a minimal, schema-driven, read-only browser (collection
  list, table, client-side search, detail view). Exported with `read_only=True`,
  so it advertises no write capabilities.

Pushing to `main` runs [`.github/workflows/deploy-pages.yml`](.github/workflows/deploy-pages.yml),
which builds the site and deploys it to GitHub Pages.

> **One-time setup:** in the repo, go to **Settings → Pages → Build and
> deployment → Source** and select **GitHub Actions**. The site is then published
> at `https://onefloid.github.io/balyoo/` (also triggerable via the workflow's
> *Run workflow* button).

## AI ingestion (talk to Claude, publish an item)

Describe an experience in natural language — even from the Claude mobile app at the
bar — and have it turned into a valid item that goes live on the site:

> *"I'm at a cozy little bar in Berlin, great cocktails, 5/5."* → Claude structures
> it against the collection's schema, beautifies the text, previews it for you, and
> on your confirmation commits + pushes → Pages redeploys → live.

**Claude is the ingestion agent** — no OpenAI key and no server are needed for this
flow. The repo ships a Claude skill (`.claude/skills/ingest-experience/`) that
encodes the workflow, and a deterministic command that is the code-enforced safety
gate:

```bash
# Create or update an item from JSON, validated against the schema (preview + confirm)
uv run collections ingest books --data '{"title":"The Hobbit","author":"Tolkien","year":1937}'
```

`collections ingest` decides create vs. update by id, **validates against the JSON
Schema** (invalid items are never written), and prints a preview — a field diff for
updates — before asking to proceed. Claude produces the structured JSON; this
command is the deterministic write gate.

**Security & privacy.** The Pages site is public, so publishing is always a
confirmed step (updates shown as a diff). Validation happens in code, not on trust.
Beautified text is stored and rendered as plain text (no HTML/Markdown injection).
No secrets go into items or the repo, and — because the static site can't safely
hold an API key — the LLM step runs in Claude, never in the public browser. A
provider-agnostic, OpenAI-compatible engine for *unattended* ingestion (without
Claude in the loop) is planned but deliberately deferred.

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
