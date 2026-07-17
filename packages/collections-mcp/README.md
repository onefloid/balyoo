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

## Remote (HTTP + OAuth 2.1) — for cloud LLMs

A cloud LLM can't launch a local process; it connects to a **URL** over the
Streamable HTTP transport. `collections mcp --http` serves that, secured as an
**OAuth 2.1 resource server**: an external OIDC identity provider issues tokens,
this server only verifies the bearer JWT and maps its scopes to capabilities —
**a valid token grants reads; the write scope grants writes** (reusing the same
capability gating). The MCP endpoint is at `/mcp`; `/.well-known/oauth-protected-resource`
advertises your identity provider so MCP clients can run the OAuth flow.

Configure via environment:

| Variable | Meaning |
|---|---|
| `COLLECTIONS_MCP_ISSUER` | OIDC issuer URL (your identity provider) |
| `COLLECTIONS_MCP_RESOURCE_URL` | public URL of this server (the resource / audience) |
| `COLLECTIONS_MCP_WRITE_SCOPE` | scope granting writes (default `collections:write`) |
| `COLLECTIONS_MCP_AUDIENCE` | token audience (default = resource URL) |
| `COLLECTIONS_MCP_JWKS_URL` | JWKS URL (default: discovered from the issuer) |

You need an **OIDC identity provider** as the authorization server (Auth0 / WorkOS
AuthKit / Stytch / Keycloak, …). The server is IdP-agnostic — pick one that
supports **Dynamic Client Registration** for smooth client onboarding. Register a
`collections:write` scope/permission and grant it to whoever may write.

### Deploy to Fly.io

The repo ships a `Dockerfile` and `fly.toml` (durable volume for the data):

```bash
fly launch --no-deploy --copy-config      # rename the app in fly.toml
fly volumes create collections_data --size 1
fly secrets set \
  COLLECTIONS_MCP_ISSUER=https://YOUR-IDP/ \
  COLLECTIONS_MCP_RESOURCE_URL=https://YOUR-APP.fly.dev
fly deploy
```

The MCP endpoint is then `https://YOUR-APP.fly.dev/mcp`. Register that URL (with
the OAuth flow) in your LLM host — e.g. Anthropic's MCP connector or a Claude.ai
custom connector. Seed the volume with your collections (`fly ssh console`, or copy
your `schema.json`/`items` layout) — an empty data root simply serves no collections.

