# collections-mcp

An **MCP server** that exposes every collection over the Model Context Protocol, so
an AI assistant (Claude Desktop and other MCP hosts) can browse, search and edit
items natively — no repo checkout, no JSON copy-paste.

Built on `CollectionsService`, exactly like `collections-rest`, so validation and
capabilities are reused. The tool set is generated from the platform:

- **Generic reads:** `list_collections`, `get_schema`, `list_items` (full-text `q`,
  sort, paginate), `get_item`.
- **Schema-typed writes, per collection:** `create_<collection>` and
  `update_<collection>`, whose input schema is the collection's own JSON Schema — so
  the assistant gets typed, validated fields instead of an opaque blob.
- **`delete_item`.**

Write tools appear only when the service's capabilities allow them; a read-only
server (`--read-only`) is read-only to the assistant too.

## Run

```bash
# stdio transport (what an MCP host launches)
uv run collections mcp --root examples/collections            # read-write
uv run collections mcp --root examples/collections --read-only
```

## Configure Claude Desktop

Add to `claude_desktop_config.json`:

```jsonc
{
  "mcpServers": {
    "collections": {
      "command": "uv",
      "args": ["run", "collections", "mcp", "--root", "/abs/path/to/collections"]
    }
  }
}
```

## Remote (HTTP + bearer token) — for cloud LLMs

A cloud LLM can't launch a local process; it connects to a **URL** over the
Streamable HTTP transport. `collections mcp --http` serves that, protected by a
**static bearer token** — no identity provider to set up. Set `COLLECTIONS_MCP_TOKEN`
to a shared secret and every request to `/mcp` must carry
`Authorization: Bearer <token>`; anything else gets a `401`. The MCP endpoint is at
`/mcp`, and a public `/health` endpoint backs the platform health check.

The token only gates access; **what** an authenticated caller may do comes from
flags, not the token:

| Flag | Effect |
|---|---|
| _(none)_ | read + create/update + delete |
| `--read-only` | read tools only |
| `--no-delete` | read + create/update, but no `delete_item` |
| `--allow-anonymous` | serve `/mcp` without a token (no authentication) |

Configure via environment:

| Variable | Meaning |
|---|---|
| `COLLECTIONS_MCP_TOKEN` | the bearer secret required on every `/mcp` request |

Generate a strong token with e.g. `openssl rand -hex 32`. Without either
`COLLECTIONS_MCP_TOKEN` or `--allow-anonymous`, `--http` refuses to start.

### Connecting a client

- **Anthropic API MCP connector:** pass the token as `authorization_token`.
- **Any client that lets you set headers:** send `Authorization: Bearer <token>`.
- **claude.ai custom connector (web UI):** its connector flow is built around OAuth
  or unauthenticated servers, so a static header may not be enterable there — for
  that case deploy with `--allow-anonymous` (optionally `--read-only`) and rely on an
  unguessable URL, or put the server behind your own gateway.

### Storage backends

Both the REST server and the MCP server take `--db <path>` to use the durable,
transactional **SQLite** backend instead of a filesystem root. Seed a SQLite
database from an existing filesystem layout with `collections migrate`:

```bash
collections migrate --root examples/collections --db collections.db   # idempotent
collections mcp --http --db collections.db ...
```

### Deploy to Fly.io

The repo ships a `Dockerfile` and `fly.toml`; the container runs the MCP server on
**SQLite** at `/data/collections.db` (a durable volume):

```bash
fly launch --no-deploy --copy-config      # rename the app in fly.toml
fly volumes create collections_data --size 1
fly secrets set COLLECTIONS_MCP_TOKEN=$(openssl rand -hex 32)
fly deploy

# seed the (empty) database once, then it persists on the volume
fly ssh console -C "/app/.venv/bin/collections migrate --root /app/examples/collections --db /data/collections.db"
```

The MCP endpoint is then `https://YOUR-APP.fly.dev/mcp`. Register that URL in your LLM
host along with the bearer token (see [Connecting a client](#connecting-a-client)
above). An empty database simply serves no collections until seeded.

