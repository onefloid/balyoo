"""Chat feature: tool filtering, owner auth, quota, and the SSE endpoint."""

from __future__ import annotations

import time
from typing import Any

import anyio
import pytest
from collections_chat.agent import MAX_ACTIVE_COLLECTIONS, active_tools, run_turn
from collections_chat.auth import Actor, StaticOwnerAuthenticator
from collections_chat.http import build_chat_asgi_app
from collections_chat.quota import QuotaExceeded, QuotaLimits, QuotaStore
from collections_core.service import CollectionsService
from collections_mcp.http import build_asgi_app
from conftest import InMemoryProvider
from starlette.requests import Request
from starlette.testclient import TestClient

TOKEN = "owner-secret"


@pytest.fixture
def service(book_schema) -> CollectionsService:
    movie_schema = {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    }
    provider = InMemoryProvider({"books": book_schema, "movies": movie_schema})
    return CollectionsService(provider)


# -- active_tools() filtering --------------------------------------------
def test_active_tools_always_includes_generic_tools(service):
    names = {t["name"] for t in active_tools(service, active_collections=set())}
    assert {"list_collections", "get_schema", "list_items", "get_item"} <= names
    assert "create_books" not in names
    assert "update_movies" not in names


def test_active_tools_includes_only_requested_collections(service):
    names = {t["name"] for t in active_tools(service, active_collections={"books"})}
    assert "create_books" in names
    assert "update_books" in names
    assert "create_movies" not in names
    assert "update_movies" not in names


def test_active_tools_input_schema_is_anthropic_shaped(service):
    tools = {t["name"]: t for t in active_tools(service, active_collections={"books"})}
    create = tools["create_books"]
    assert set(create) == {"name", "description", "input_schema"}
    assert "title" in create["input_schema"]["properties"]


# -- StaticOwnerAuthenticator ---------------------------------------------
def _request(headers: dict[str, str]) -> Request:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw_headers, "method": "POST", "path": "/stream"})


def test_owner_authenticator_rejects_missing_token():
    auth = StaticOwnerAuthenticator(TOKEN)
    assert auth.authenticate(_request({})) is None


def test_owner_authenticator_rejects_wrong_token():
    auth = StaticOwnerAuthenticator(TOKEN)
    assert auth.authenticate(_request({"Authorization": "Bearer nope"})) is None


def test_owner_authenticator_accepts_the_configured_token():
    auth = StaticOwnerAuthenticator(TOKEN)
    actor = auth.authenticate(_request({"Authorization": f"Bearer {TOKEN}"}))
    assert actor == Actor(id="owner", can_write=True)


def test_owner_authenticator_rejects_empty_token_at_construction():
    # An empty configured token would make hmac.compare_digest("", "") true for
    # a request with no Authorization header at all -- must fail fast instead.
    with pytest.raises(ValueError):
        StaticOwnerAuthenticator("")


# -- QuotaStore ------------------------------------------------------------
def test_quota_enforces_per_minute_limit(tmp_path):
    store = QuotaStore(tmp_path / "quota.db", QuotaLimits(requests_per_minute=2))
    now = time.time()
    store.check_and_consume_request("owner", now=now)
    store.check_and_consume_request("owner", now=now)
    with pytest.raises(QuotaExceeded):
        store.check_and_consume_request("owner", now=now)


def test_quota_per_minute_window_resets(tmp_path):
    store = QuotaStore(tmp_path / "quota.db", QuotaLimits(requests_per_minute=1))
    now = time.time()
    store.check_and_consume_request("owner", now=now)
    store.check_and_consume_request("owner", now=now + 61)  # next minute window


def test_quota_token_budget_blocks_once_exhausted(tmp_path):
    store = QuotaStore(tmp_path / "quota.db", QuotaLimits(daily_token_budget=100))
    store.record_usage(150)
    with pytest.raises(QuotaExceeded):
        store.check_token_budget()


def test_quota_persists_across_reopen(tmp_path):
    db = tmp_path / "quota.db"
    limits = QuotaLimits(requests_per_minute=1)
    now = time.time()
    QuotaStore(db, limits).check_and_consume_request("owner", now=now)
    # A fresh QuotaStore instance (simulating a process restart after scale-to-
    # zero) must see the same counter, not reset to zero.
    reopened = QuotaStore(db, limits)
    with pytest.raises(QuotaExceeded):
        reopened.check_and_consume_request("owner", now=now)


# -- SSE endpoint ------------------------------------------------------------
class _FakeStream:
    def __init__(self, text: str) -> None:
        self._text = text

    async def __aenter__(self) -> _FakeStream:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    @property
    async def text_stream(self):
        yield self._text

    async def get_final_message(self):
        class _Usage:
            input_tokens = 42
            output_tokens = 7

        class _Message:
            content: list[Any] = []
            stop_reason = "end_turn"
            usage = _Usage()

        return _Message()


class _FakeMessages:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def stream(self, **kwargs: Any) -> _FakeStream:
        self.calls.append(kwargs)
        return _FakeStream("Hello from the assistant.")


class _FakeAnthropicClient:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


def test_run_turn_caps_client_supplied_active_collections_seed(book_schema):
    # Five collections, all requested up front by the client -- more than
    # MAX_ACTIVE_COLLECTIONS. Without the cap, every one of their full schemas
    # would be sent to the LLM on every call, defeating the point of filtering.
    schemas = {f"c{i}": book_schema for i in range(5)}
    many_collections_service = CollectionsService(InMemoryProvider(schemas))
    client = _FakeAnthropicClient()

    async def scenario() -> None:
        async for _ in run_turn(
            many_collections_service,
            client,
            "claude-sonnet-5",
            [],
            "hi",
            active_collections=set(schemas),
        ):
            pass

    anyio.run(scenario)

    assert len(client.messages.calls) == 1
    tool_names = {t["name"] for t in client.messages.calls[0]["tools"]}
    requested_collections = {
        n[len("create_") :]
        for n in tool_names
        if n.startswith("create_") and n != "create_collection"
    }
    assert len(requested_collections) <= MAX_ACTIVE_COLLECTIONS


def _chat_client(service, *, limits: QuotaLimits | None = None, tmp_path) -> TestClient:
    app = build_chat_asgi_app(
        service,
        _FakeAnthropicClient(),
        "claude-sonnet-5",
        StaticOwnerAuthenticator(TOKEN),
        QuotaStore(tmp_path / "quota.db", limits or QuotaLimits()),
    )
    return TestClient(app)


def test_chat_stream_requires_auth(service, tmp_path):
    with _chat_client(service, tmp_path=tmp_path) as client:
        res = client.post("/stream", json={"message": "hi"})
        assert res.status_code == 401


def test_chat_stream_streams_events_when_authenticated(service, tmp_path):
    with _chat_client(service, tmp_path=tmp_path) as client:
        res = client.post(
            "/stream",
            json={"message": "hi"},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert res.status_code == 200
        assert "event: token" in res.text
        assert "event: done" in res.text


def test_chat_stream_body_too_large_is_rejected_before_full_read(service, tmp_path):
    limits = QuotaLimits(max_body_bytes=16)
    with _chat_client(service, limits=limits, tmp_path=tmp_path) as client:
        big_message = "x" * 1000
        res = client.post(
            "/stream",
            json={"message": big_message},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert res.status_code == 413


def test_chat_stream_enforces_quota(service, tmp_path):
    limits = QuotaLimits(requests_per_minute=1)
    with _chat_client(service, limits=limits, tmp_path=tmp_path) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        first = client.post("/stream", json={"message": "hi"}, headers=headers)
        assert first.status_code == 200
        second = client.post("/stream", json={"message": "hi"}, headers=headers)
        assert second.status_code == 429


# -- mount into the combined MCP/REST/chat ASGI app --------------------------
def test_chat_app_mounted_at_chat_prefix_strips_path(service, tmp_path):
    seen_paths: list[str] = []

    async def recording_chat_app(scope, receive, send):
        seen_paths.append(scope["path"])
        response_started = {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/plain")],
        }
        await send(response_started)
        await send({"type": "http.response.body", "body": b"ok"})

    combined = build_asgi_app(service, token="mcp-token", chat_app=recording_chat_app)
    with TestClient(combined) as client:
        res = client.post("/chat/stream", json={})
        assert res.status_code == 200
        assert seen_paths == ["/stream"]
