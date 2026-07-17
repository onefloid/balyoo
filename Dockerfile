# Container for the remote (HTTP) MCP server — see packages/collections-mcp.
# Build context is the repo root (a uv workspace).
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

# gosu lets the entrypoint drop from root to an unprivileged user after fixing the
# mounted volume's ownership; `app` is that unprivileged runtime user.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app

WORKDIR /app
COPY . .
# Cache uv's downloads across builds so dependency changes rebuild quickly.
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

EXPOSE 8080

COPY docker-entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Data is the durable SQLite database on the mounted volume (see fly.toml); OAuth
# settings come from COLLECTIONS_MCP_* env / secrets. The server is read-only until
# a token carries the write (and, for delete, delete) scope. Run the venv binary
# directly so no uv re-sync is attempted as the unprivileged user. Seed the empty
# database with `collections migrate` (see packages/collections-mcp/README.md).
CMD ["/app/.venv/bin/collections", "mcp", "--http", \
     "--host", "0.0.0.0", "--port", "8080", "--db", "/data/collections.db"]
