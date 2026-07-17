"""HTTP MCP server: JWT verification, scope->capability, and the guarded endpoint."""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import threading
import time

import collections_mcp.http as http_mod
import jwt
import pytest
import uvicorn
from collections_core.service import CollectionsService
from collections_filesystem.provider import FilesystemStorageProvider
from collections_mcp.http import (
    JwtTokenVerifier,
    OAuthConfig,
    build_asgi_app,
    make_service_resolver,
)
from collections_mcp.server import build_tools
from collections_schema.validator import JsonSchemaValidator
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.auth.provider import AccessToken, TokenVerifier
from starlette.testclient import TestClient

ISSUER = "https://idp.example.com"
RESOURCE = "https://mcp.example.com"
OAUTH = OAuthConfig(issuer_url=ISSUER, resource_url=RESOURCE)


def _service_factory(root):
    return lambda read_only, no_delete, subject: CollectionsService(
        FilesystemStorageProvider(root),
        JsonSchemaValidator(),
        read_only=read_only,
        deletable=not no_delete,
    )


# -- JWT verification --------------------------------------------------------
@pytest.fixture(scope="module")
def keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _verifier(keypair) -> JwtTokenVerifier:
    v = JwtTokenVerifier(
        jwks_url_provider=lambda: "https://unused", issuer=ISSUER, audience=RESOURCE
    )

    class _Key:
        key = keypair.public_key()

    class _Jwks:
        def get_signing_key_from_jwt(self, _token):
            return _Key()

    v._jwks = _Jwks()  # avoid the network; use the local public key
    return v


def _token(keypair, **claims) -> str:
    base = {"iss": ISSUER, "aud": RESOURCE, "sub": "user1", "exp": int(time.time()) + 3600}
    return jwt.encode({**base, **claims}, keypair, algorithm="RS256")


def _verify(verifier, token):
    return asyncio.run(verifier.verify_token(token))


def test_accepts_a_valid_token_and_extracts_scopes(keypair):
    token = _token(keypair, scope="openid collections:write")
    access = _verify(_verifier(keypair), token)
    assert access is not None
    assert access.subject == "user1"
    assert "collections:write" in access.scopes


def test_extracts_scopes_from_permissions_claim(keypair):
    access = _verify(_verifier(keypair), _token(keypair, permissions=["collections:write"]))
    assert "collections:write" in access.scopes


def test_rejects_expired_wrong_audience_and_bad_signature(keypair):
    verifier = _verifier(keypair)
    assert _verify(verifier, _token(keypair, exp=int(time.time()) - 10)) is None
    assert _verify(verifier, _token(keypair, aud="https://other")) is None

    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(
        {"iss": ISSUER, "aud": RESOURCE, "exp": int(time.time()) + 60}, other, algorithm="RS256"
    )
    assert _verify(verifier, forged) is None


# -- scope -> capability -----------------------------------------------------
def _resolve_tools(examples_copy, monkeypatch, scopes):
    resolve = make_service_resolver(_service_factory(examples_copy), OAUTH)
    token = AccessToken(token="x", client_id="c", scopes=scopes) if scopes is not None else None
    monkeypatch.setattr(http_mod, "get_access_token", lambda: token)
    return {t.name for t in build_tools(resolve())}


def test_no_token_is_read_only(examples_copy, monkeypatch):
    names = _resolve_tools(examples_copy, monkeypatch, None)
    assert not any(n.startswith(("create_", "update_")) for n in names)
    assert "delete_item" not in names


def test_write_scope_grants_writes_but_not_delete(examples_copy, monkeypatch):
    names = _resolve_tools(examples_copy, monkeypatch, ["collections:write"])
    assert "create_books" in names and "update_books" in names
    assert "delete_item" not in names  # delete needs its own scope


def test_delete_scope_grants_delete(examples_copy, monkeypatch):
    names = _resolve_tools(
        examples_copy, monkeypatch, ["collections:write", "collections:delete"]
    )
    assert "create_books" in names and "delete_item" in names


def test_resolver_passes_the_subject_for_per_user_isolation(monkeypatch):
    seen: dict[str, object] = {}

    def factory(read_only, no_delete, subject):
        seen["subject"] = subject
        return CollectionsService(FilesystemStorageProvider("/unused"))

    resolve = make_service_resolver(factory, OAUTH)
    monkeypatch.setattr(
        http_mod,
        "get_access_token",
        lambda: AccessToken(token="x", client_id="c", scopes=[], subject="user-42"),
    )
    resolve()
    assert seen["subject"] == "user-42"


# -- guarded HTTP endpoint (in-process TestClient) ---------------------------
class _FakeVerifier(TokenVerifier):
    async def verify_token(self, token):
        scopes = {
            "admin": ["collections:write", "collections:delete"],
            "write": ["collections:write"],
            "read": [],
        }.get(token)
        if scopes is None:
            return None
        return AccessToken(token=token, client_id="c", scopes=scopes)


def _client(root) -> TestClient:
    app = build_asgi_app(_service_factory(root), OAUTH, verifier=_FakeVerifier())
    return TestClient(app)


def test_health_endpoint_is_public(examples_copy):
    with _client(examples_copy) as client:
        res = client.get("/health")
        assert res.status_code == 200 and res.json() == {"status": "ok"}


def test_protected_resource_metadata_points_to_the_idp(examples_copy):
    with _client(examples_copy) as client:
        res = client.get("/.well-known/oauth-protected-resource")
        assert res.status_code == 200
        assert ISSUER in json.dumps(res.json())


def test_mcp_endpoint_requires_a_token(examples_copy):
    with _client(examples_copy) as client:
        res = client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert res.status_code == 401


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


async def _tool_names(url, token):
    async with streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"}) as (
        read,
        write,
        _,
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return {t.name for t in (await session.list_tools()).tools}


async def _create(url, token):
    async with streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"}) as (
        read,
        write,
        _,
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.call_tool("create_books", {"id": "http-it", "title": "T"})
            return json.loads(res.content[0].text)


def test_full_authenticated_tool_call_over_http(examples_copy):
    port = _free_port()
    app = build_asgi_app(_service_factory(examples_copy), OAUTH, verifier=_FakeVerifier())
    with _running(app, port):
        url = f"http://127.0.0.1:{port}/mcp"
        admin = asyncio.run(_tool_names(url, "admin"))
        assert {"create_books", "delete_item"} <= admin

        writer = asyncio.run(_tool_names(url, "write"))
        assert "create_books" in writer and "delete_item" not in writer

        reader = asyncio.run(_tool_names(url, "read"))
        assert "create_books" not in reader and "list_items" in reader

        created = asyncio.run(_create(url, "admin"))
        assert created["id"] == "http-it" and created["data"]["title"] == "T"
    assert (examples_copy / "books" / "items" / "http-it.json").exists()
