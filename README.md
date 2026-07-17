# balyoo

**Schema-first collections for humans and AI.**

Collections is a generic platform for storing, validating, searching and serving
arbitrary structured objects — books, movies, employees, products, APIs, … You
describe a collection with a JSON Schema, pick a storage provider, and the
validation, CRUD, REST API and web UI (and, later, an MCP server) come for free.

> **Milestone 1 (this repo):** a working vertical slice in Python — core, schema
> validation, a filesystem storage provider with full CRUD, a fully generic REST
> API, and a CLI, with example collections. See
> [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design and the
> roadmap (MCP, SQLite/Postgres, pluggable search & auth). A generic React web UI
> (`collections-ui`) is now included.

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

# Serve the API *and* the web UI from one origin (build the UI first, see below)
uv run collections serve --ui packages/collections-ui/dist

# Export the JSON API mirror + UI runtime config for static hosting
uv run collections export --root examples/collections --out dist
```

## Web UI (`collections-ui`)

A single, fully generic React frontend — a **list** (table) and a modern **card**
view (toggle per collection, remembered across visits), item detail, and
schema-generated **create/edit** forms (via [RJSF](https://rjsf-team.github.io/react-jsonschema-form/)).
It talks only to the generic API and adapts to the reported capabilities: on a
read-only deployment it shows no write controls. **One build serves every
deployment**; a runtime `config.json` tells it whether it is talking to the live
REST API or the static JSON mirror.

Each card's contents — and which view a collection **opens in** — are
**schema-driven**: a collection may add an optional `x-card` block to its JSON
Schema to set the default view (`"list"` or `"cards"`) and choose the title,
subtitle, image, badge and field properties shown on the tile; without it a
sensible layout is derived from the schema, defaulting to the list view. `x-card`
is a custom keyword, ignored by JSON Schema validators. (A viewer's own List/Cards
choice is remembered per collection and overrides the schema default.)

```jsonc
// examples/collections/books/schema.json
"x-card": {
  "default": "cards",
  "title": "title", "subtitle": "author",
  "badges": ["tags"], "fields": ["year", "pages"]
}
```

```bash
cd packages/collections-ui
pnpm install          # Node ≥ 20 + pnpm
pnpm test             # vitest
pnpm build            # -> packages/collections-ui/dist

# Dev: UI on :5173 proxying to a live API on :8000
uv run collections serve            # in one terminal
pnpm dev                            # in another, then open http://localhost:5173/
```

For a read-write deployment, serve the built bundle from the same origin as the
API (no CORS): `uv run collections serve --ui packages/collections-ui/dist`.

## Static deployment (GitHub Pages)

For read-only static hosting there is no server and no database:

- `collections export` writes `dist/api/…` — JSON files whose layout mirrors the
  REST routes (`collections.json`, `<c>/schema.json`, `<c>/items.json`,
  `<c>/items/<id>.json`) — plus `dist/config.json`, which points the UI at that
  mirror in read-only mode (exported with `read_only=True`, so no write controls).
- The built `collections-ui` bundle is laid on top of that mirror.

Pushing to `main` runs [`.github/workflows/deploy-pages.yml`](.github/workflows/deploy-pages.yml),
which builds the UI, assembles it with the JSON mirror, and deploys to GitHub Pages.

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
    REST API / CLI / Web UI      (later: MCP server)
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

# Web UI (Node ≥ 20 + pnpm)
pnpm --dir packages/collections-ui install
pnpm --dir packages/collections-ui test
pnpm --dir packages/collections-ui lint
pnpm --dir packages/collections-ui build
```

## License

Apache-2.0
