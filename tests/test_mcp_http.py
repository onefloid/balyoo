"""HTTP MCP server: static bearer-token guard, flag-driven capabilities, endpoints."""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import threading
import time

import uvicorn
from collections_core.service import CollectionsService
from collections_filesystem.provider import FilesystemStorageProvider
from collections_mcp.http import build_asgi_app
from collections_schema.validator import JsonSchemaValidator
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from starlette.testclient import TestClient

TOKEN = "s3cret-token"


def _service(root, *, read_only=False, deletable=True) -> CollectionsService:
    return CollectionsService(
        FilesystemStorageProvider(root),
        JsonSchemaValidator(),
        read_only=read_only,
        deletable=deletable,
    )


def _initialize(headers=None):
    return {
        "headers": {"Accept": "application/json, text/event-stream", **(headers or {})},
        "json": {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    }


# -- token guard (in-process TestClient) -------------------------------------
def _client(root, *, token=TOKEN, **caps) -> TestClient:
    return TestClient(build_asgi_app(_service(root, **caps), token=token))


def test_health_endpoint_is_public(examples_copy):
    with _client(examples_copy) as client:
        res = client.get("/health")
        assert res.status_code == 200 and res.json() == {"status": "ok"}


def test_mcp_rejects_missing_or_wrong_token(examples_copy):
    with _client(examples_copy) as client:
        assert client.post("/mcp", **_initialize()).status_code == 401
        wrong = _initialize({"Authorization": "Bearer nope"})
        assert client.post("/mcp", **wrong).status_code == 401


def test_mcp_accepts_the_configured_token(examples_copy):
    with _client(examples_copy) as client:
        ok = _initialize({"Authorization": f"Bearer {TOKEN}"})
        assert client.post("/mcp", **ok).status_code == 200


def test_anonymous_mode_needs_no_token(examples_copy):
    with _client(examples_copy, token=None) as client:
        assert client.post("/mcp", **_initialize()).status_code == 200


# -- flag-driven capabilities ------------------------------------------------
def _tool_names(root, **caps) -> set[str]:
    from collections_mcp.server import build_tools

    return {t.name for t in build_tools(_service(root, **caps))}


def test_full_capabilities_expose_writes_and_delete(examples_copy):
    names = _tool_names(examples_copy)
    assert {"create_books", "update_books", "delete_item"} <= names


def test_read_only_hides_all_writes(examples_copy):
    names = _tool_names(examples_copy, read_only=True)
    assert not any(n.startswith(("create_", "update_")) for n in names)
    assert "delete_item" not in names


def test_no_delete_keeps_writes_but_hides_delete(examples_copy):
    names = _tool_names(examples_copy, deletable=False)
    assert "create_books" in names and "delete_item" not in names


# -- full tool call over real HTTP (threaded uvicorn + MCP client) -----------
def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@contextlib.contextmanager
def _running(app, port):
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        yield
    finally:
        server.should_exit = True
        thread.join(timeout=5)


async def _create(url):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.call_tool("create_books", {"id": "http-it", "title": "T"})
            return json.loads(res.content[0].text)


def test_full_authenticated_tool_call_over_http(examples_copy):
    port = _free_port()
    app = build_asgi_app(_service(examples_copy), token=TOKEN)
    with _running(app, port):
        created = asyncio.run(_create(f"http://127.0.0.1:{port}/mcp"))
        assert created["id"] == "http-it" and created["data"]["title"] == "T"
    assert (examples_copy / "books" / "items" / "http-it.json").exists()
