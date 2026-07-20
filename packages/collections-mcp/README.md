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
- **Collection management:** `create_collection` (define a new collection from a JSON
  Schema — its description doubles as authoring guidance, and the schema is
  meta-validated before it is stored), `update_schema` (replace a collection's schema;
  returns the ids of any existing items that no longer conform), and
  `delete_collection`. A newly created collection's typed `create_<name>` /
  `update_<name>` tools then appear automatically.
- **`delete_item`.**

Write tools (including `create_collection` / `update_schema`) appear only when the
service's capabilities allow them; a read-only server (`--read-only`) is read-only to
the assistant too. `delete_collection` requires the delete capability, like
`delete_item`.

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
| `--rest` | also serve the read-only REST API at `/collections` (public) |

`--rest` (only valid with `--http`) additionally exposes the generic REST API
under `/collections` in the *same* process and against the *same* backend —
read-only and **without** the `/mcp` bearer token, with open CORS so browsers on
other origins can read it. SQLite lives on a single Fly volume that only one
machine can mount, so co-hosting REST here avoids a second container and volume;
switch to a separate app only when you move to a networked database.

Configure via environment:

| Variable | Meaning |
|---|---|
| `COLLECTIONS_MCP_TOKEN` | the bearer secret required on every `/mcp` request |

Generate a strong token with e.g. `openssl rand -hex 32`. Without either
`COLLECTIONS_MCP_TOKEN` or `--allow-anonymous`, `--http` refuses to start.

### Connecting a client

- **Anthropic API MCP connector:** pass the token as `authorization_token`.
- **Any client that lets you set headers:** send `Authorization: Bearer <token>`.
- **ChatGPT / claude.ai custom connectors:** their setup screens only accept a
  Client ID + Client Secret and drive a real OAuth flow, not a bare bearer token —
  see [OAuth for ChatGPT / Claude.ai](#oauth-for-chatgpt--claudeai-custom-connectors)
  below.

### OAuth for ChatGPT / Claude.ai custom connectors

ChatGPT's and Claude.ai's custom-connector setup screens only accept a
**Client ID + Client Secret** and then run a standard OAuth 2.1 Authorization Code
flow (with PKCE): redirect the browser to `/authorize`, expect a redirect back to
*their* callback URL with a `code`, then `POST /token` to exchange it. A bare
bearer token can't satisfy that UI.

Rather than depending on an external identity provider, setting four more env vars
makes this same server act as its own OAuth 2.1 Authorization Server for exactly
one pre-configured client:

| Variable | Meaning |
|---|---|
| `COLLECTIONS_MCP_OAUTH_CLIENT_ID` | any identifier you choose, e.g. `collections` |
| `COLLECTIONS_MCP_OAUTH_CLIENT_SECRET` | a strong secret, e.g. `openssl rand -hex 32` |
| `COLLECTIONS_MCP_OAUTH_REDIRECT_URIS` | comma-separated allowed callback URL(s) |
| `COLLECTIONS_MCP_PUBLIC_URL` | this server's own `https://` base URL |

All four must be set together (or none at all — `COLLECTIONS_MCP_TOKEN` alone keeps
working exactly as above; OAuth is additive, never a replacement). `/mcp` then
accepts *either* the static token or a token issued through the OAuth flow.

There's no login page: `/authorize` auto-approves immediately, because the actual
gate is the client secret required at the `/token` exchange — appropriate for a
single-owner service, not a multi-tenant one. Authorization codes and issued
access/refresh tokens are signed, self-verifying strings rather than anything
stored server-side, so they survive this process restarting (e.g. Fly.io stopping
an idle machine and rebuilding it fresh on the next request). To revoke every
issued token at once, rotate `COLLECTIONS_MCP_OAUTH_CLIENT_SECRET`.

**Redirect URIs to register:**

- **Claude.ai:** fixed — `https://claude.ai/api/mcp/auth_callback`.
- **ChatGPT:** *not* fixed — its connector setup screen shows a callback URL
  specific to that connector instance; copy it character-for-character into
  `COLLECTIONS_MCP_OAUTH_REDIRECT_URIS`.

Comma-separate both if you're registering the same server with both apps:

```bash
fly secrets set \
  COLLECTIONS_MCP_OAUTH_CLIENT_ID=collections \
  COLLECTIONS_MCP_OAUTH_CLIENT_SECRET=$(openssl rand -hex 32) \
  COLLECTIONS_MCP_OAUTH_REDIRECT_URIS="https://claude.ai/api/mcp/auth_callback,https://chatgpt.com/connector/oauth/YOUR-CALLBACK-ID" \
  COLLECTIONS_MCP_PUBLIC_URL=https://YOUR-APP.fly.dev
```

Then, in the app's connector setup screen, paste in the Client ID and Client
Secret you just set. If the setup screen also asks for a "scope" (e.g. a default
or base scope) it doesn't matter what you enter, or whether you leave it blank —
capabilities here are controlled by the `--read-only`/`--no-delete` flags above,
not by OAuth scopes, and this server accepts any scope a connector sends.

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
fly launch --no-deploy --copy-config      # rename the app in fly.toml if you fork this
fly volumes create collections_data --size 1
fly secrets set COLLECTIONS_MCP_TOKEN=$(openssl rand -hex 32)
fly deploy

# seed the (empty) database once, then it persists on the volume
fly ssh console -C "/app/.venv/bin/collections migrate --root /app/examples/collections --db /data/collections.db"
```

### Continuous deployment

`.github/workflows/ci.yml` deploys automatically on every push to `main`, after
the Python lint/test job passes — no manual `fly deploy` needed for routine
changes. It needs a `FLY_API_TOKEN` repository secret:

```bash
fly tokens create deploy -x 999999h   # a long-lived deploy token
```

Add the output as a secret named `FLY_API_TOKEN` under **Settings → Secrets and
variables → Actions** in the GitHub repo. Without it, the `deploy` job fails
(tests/lint on `pull_request`s are unaffected — deploy only runs on `push` to
`main`). A manual `fly deploy` from your machine (as above) still works too, e.g.
for a one-off redeploy without pushing a commit.

The MCP endpoint is then `https://YOUR-APP.fly.dev/mcp`. Register that URL in your LLM
host along with the bearer token (see [Connecting a client](#connecting-a-client)
above). An empty database simply serves no collections until seeded.

