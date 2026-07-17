"""HTTP MCP server: JWT verification, scope->capability, and the guarded endpoint."""

from __future__ import annotations

import asyncio
import json
import time

import collections_mcp.http as http_mod
import jwt
import pytest
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
from mcp.server.auth.provider import AccessToken, TokenVerifier
from starlette.testclient import TestClient

ISSUER = "https://idp.example.com"
RESOURCE = "https://mcp.example.com"
OAUTH = OAuthConfig(issuer_url=ISSUER, resource_url=RESOURCE, write_scope="collections:write")


def _service_factory(root):
    return lambda read_only: CollectionsService(
        FilesystemStorageProvider(root), JsonSchemaValidator(), read_only=read_only
    )


# -- JWT verification --------------------------------------------------------
@pytest.fixture(scope="module")
def keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _verifier(keypair) -> JwtTokenVerifier:
    v = JwtTokenVerifier(jwks_url="https://unused", issuer=ISSUER, audience=RESOURCE)

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
def test_scope_selects_read_vs_write_tools(examples_copy, monkeypatch):
    resolve = make_service_resolver(_service_factory(examples_copy), "collections:write")

    monkeypatch.setattr(http_mod, "get_access_token", lambda: None)
    read_tools = [t.name for t in build_tools(resolve())]
    assert not any(n.startswith(("create_", "update_")) for n in read_tools)

    monkeypatch.setattr(
        http_mod,
        "get_access_token",
        lambda: AccessToken(token="x", client_id="c", scopes=["collections:write"]),
    )
    write_tools = [t.name for t in build_tools(resolve())]
    assert "create_books" in write_tools


# -- guarded HTTP endpoint ---------------------------------------------------
class _FakeVerifier(TokenVerifier):
    async def verify_token(self, token):
        if token == "write":
            return AccessToken(token=token, client_id="c", scopes=["collections:write"])
        if token == "read":
            return AccessToken(token=token, client_id="c", scopes=[])
        return None


def _client(root) -> TestClient:
    app = build_asgi_app(_service_factory(root), OAUTH, verifier=_FakeVerifier())
    return TestClient(app)


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


def test_authenticated_initialize_succeeds(examples_copy):
    with _client(examples_copy) as client:
        res = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer write",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
        assert res.status_code == 200
        assert res.json()["result"]["serverInfo"]["name"] == "collections"
