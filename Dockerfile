# Container for the remote (HTTP) MCP server — see packages/collections-mcp.
# Build context is the repo root (a uv workspace).
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app
COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8080

# Collections data lives on a mounted volume (see fly.toml); OAuth settings come
# from COLLECTIONS_MCP_* env / secrets. The server is read-only until a token
# carries the write scope.
CMD ["uv", "run", "collections", "mcp", "--http", \
     "--host", "0.0.0.0", "--port", "8080", "--root", "/data/collections"]
