# collections-chat

Owner-only in-app chat: lets the operator create/edit collection items by
chatting from the website, instead of setting up an external MCP client. Wraps
`collections_mcp.server.build_tools()`/`dispatch()` in an Anthropic tool-use
loop (`agent.py`), streamed over SSE (`http.py`), gated by a single owner
bearer token (`auth.py`) and backed by SQLite-persisted rate limits
(`quota.py`).

Not multi-user: `ChatAuthenticator` is a small protocol so a real per-user
authorizer can replace `StaticOwnerAuthenticator` later without touching the
rest of this package.

## Enabling it

```
COLLECTIONS_CHAT_LLM_API_KEY=sk-ant-...   # your own Anthropic key
COLLECTIONS_CHAT_OWNER_TOKEN=...          # bearer token gating /chat
COLLECTIONS_CHAT_MODEL=claude-sonnet-5    # optional, this is the default
collections mcp --http --chat --db /data/collections.db
```

`/chat/stream` then accepts `POST {"message": str, "history": [...], "active_collections": [...]}`
with `Authorization: Bearer <COLLECTIONS_CHAT_OWNER_TOKEN>` and streams
Server-Sent Events (`token` / `tool_call` / `tool_result` / `done` / `error`).
