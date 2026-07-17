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
| `COLLECTIONS_MCP_WRITE_SCOPE` | scope granting create/update (default `collections:write`) |
| `COLLECTIONS_MCP_DELETE_SCOPE` | scope granting delete (default `collections:delete`) |
| `COLLECTIONS_MCP_AUDIENCE` | token audience (default = resource URL) |
| `COLLECTIONS_MCP_JWKS_URL` | JWKS URL (default: discovered from the issuer) |

You need an **OIDC identity provider** as the authorization server (Auth0 / WorkOS
AuthKit / Stytch / Keycloak, …). The server is IdP-agnostic — pick one that
supports **Dynamic Client Registration** for smooth client onboarding. Register the
`collections:write` (and, for deletes, `collections:delete`) scope/permission and
grant it to whoever may write. Pass `--per-user` to give each authenticated subject
its own isolated collections (under `<root>/<hashed-subject>`).

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
**SQLite** at `/data/collections.db` (a durable volume) with a `/health` check.

**The only values you must supply** are `COLLECTIONS_MCP_ISSUER` and
`COLLECTIONS_MCP_RESOURCE_URL` — there are no real secrets (the server only
*verifies* tokens; SQLite needs no credentials).

**Checklist:**

1. **Name the app** — set `app` in `fly.toml` (or `fly launch --no-deploy --copy-config`).
   Your public URL becomes `https://<app>.fly.dev`.
2. **Identity provider** — register a resource/API whose **audience equals that URL**
   and define the `collections:write` / `collections:delete` scopes. Enable Dynamic
   Client Registration so the LLM host can self-register. (If the IdP's `aud` can't
   be a URL, set `COLLECTIONS_MCP_AUDIENCE` to match its value.)
3. **Create the volume first** (same region), so Fly doesn't auto-create/duplicate it:
   ```bash
   fly volumes create collections_data --region <region> --size 1
   ```
4. **Set the config** (these are not secret; `[env]` in `fly.toml` also works):
   ```bash
   fly secrets set \
     COLLECTIONS_MCP_ISSUER=https://YOUR-IDP/ \
     COLLECTIONS_MCP_RESOURCE_URL=https://YOUR-APP.fly.dev
   ```
5. **Deploy:** `fly deploy`
6. **Seed the empty database once** (then it persists on the volume):
   ```bash
   fly ssh console -C "/app/.venv/bin/collections migrate \
     --root /app/examples/collections --db /data/collections.db"
   ```

The MCP endpoint is then `https://YOUR-APP.fly.dev/mcp`. Register that URL (with the
OAuth flow) in your LLM host — e.g. Anthropic's MCP connector or a Claude.ai custom
connector. An empty database simply serves no collections until seeded.

> **Common pitfalls.** Tokens rejected with 401 almost always mean the token's
> `aud` doesn't match `RESOURCE_URL`/`AUDIENCE`, or `ISSUER` doesn't exactly match
> the token's `iss` (mind trailing slashes). One volume ⇒ keep it to a single
> machine. A `503 "No server is available"` at the end of `fly deploy` is a
> transient Fly control-plane error (the build already succeeded) — just retry.

