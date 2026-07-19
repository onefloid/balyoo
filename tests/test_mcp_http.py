"""HTTP MCP server: static bearer-token guard, flag-driven capabilities, endpoints."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import secrets
import socket
import threading
import time
from urllib.parse import parse_qs, urlparse

import uvicorn
from collections_core.service import CollectionsService
from collections_filesystem.provider import FilesystemStorageProvider
from collections_mcp.http import OAuthConfig, SingleClientOAuthProvider, build_asgi_app
from collections_schema.validator import JsonSchemaValidator
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from starlette.testclient import TestClient

TOKEN = "s3cret-token"
OAUTH_CLIENT_ID = "test-client"
OAUTH_CLIENT_SECRET = "test-client-secret"
OAUTH_REDIRECT_URI = "https://example.com/callback"
OAUTH_PUBLIC_URL = "https://mcp.example.com"


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


def test_mcp_does_not_redirect_for_the_bare_path(examples_copy):
    """A bare `POST /mcp` (no trailing slash) — what real MCP clients send — must
    be handled directly, not 307-redirected to `/mcp/`: streaming MCP clients
    generally don't follow redirects for a POST body, so a redirect here silently
    breaks the connection. Regression test with `follow_redirects=False`, since
    TestClient follows redirects by default and would otherwise mask this."""
    with _client(examples_copy) as client:
        ok = _initialize({"Authorization": f"Bearer {TOKEN}"})
        res = client.post("/mcp", follow_redirects=False, **ok)
        assert res.status_code == 200


def test_anonymous_mode_needs_no_token(examples_copy):
    with _client(examples_copy, token=None) as client:
        assert client.post("/mcp", **_initialize()).status_code == 200


# -- co-hosted public REST API (--rest) --------------------------------------
def _rest_client(root, *, token=TOKEN) -> TestClient:
    return TestClient(
        build_asgi_app(_service(root), token=token, rest_service=_service(root, read_only=True))
    )


def test_rest_api_is_public(examples_copy):
    """The co-hosted REST API is reachable without the /mcp bearer token."""
    with _rest_client(examples_copy) as client:
        res = client.get("/collections")
        assert res.status_code == 200
        assert any(c["name"] == "books" for c in res.json())


def test_rest_api_is_read_only(examples_copy):
    with _rest_client(examples_copy) as client:
        res = client.post("/collections/books/items", json={"id": "x", "title": "T"})
        assert res.status_code == 405


def test_rest_api_sends_cors_headers(examples_copy):
    with _rest_client(examples_copy) as client:
        res = client.get("/collections", headers={"Origin": "https://example.com"})
        assert res.headers.get("access-control-allow-origin") == "*"


def test_mcp_still_requires_token_when_rest_is_enabled(examples_copy):
    with _rest_client(examples_copy) as client:
        assert client.post("/mcp", **_initialize()).status_code == 401
        ok = _initialize({"Authorization": f"Bearer {TOKEN}"})
        assert client.post("/mcp", **ok).status_code == 200


def test_rest_api_absent_without_rest_service(examples_copy):
    with _client(examples_copy) as client:
        assert client.get("/collections").status_code == 404


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


# -- self-hosted OAuth 2.1 flow (for ChatGPT/Claude.ai custom connectors) ----
def _oauth_config() -> OAuthConfig:
    return OAuthConfig(
        client_id=OAUTH_CLIENT_ID,
        client_secret=OAUTH_CLIENT_SECRET,
        redirect_uris=[OAUTH_REDIRECT_URI],
        public_url=OAUTH_PUBLIC_URL,
    )


def _oauth_client(root, *, token=TOKEN, **caps) -> TestClient:
    return TestClient(build_asgi_app(_service(root, **caps), token=token, oauth=_oauth_config()))


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def _authorize(client, *, code_challenge, redirect_uri=OAUTH_REDIRECT_URI, state="xyz", scope=None):
    params = {
        "response_type": "code",
        "client_id": OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    if scope is not None:
        params["scope"] = scope
    return client.get("/authorize", params=params, follow_redirects=False)


def _extract_code(res) -> tuple[str, str | None]:
    query = parse_qs(urlparse(res.headers["location"]).query)
    return query["code"][0], query.get("state", [None])[0]


def _token_form(
    code, verifier, *, client_secret=OAUTH_CLIENT_SECRET, redirect_uri=OAUTH_REDIRECT_URI
):
    return {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": OAUTH_CLIENT_ID,
        "client_secret": client_secret,
        "code_verifier": verifier,
    }


def test_full_oauth_authorization_code_flow(examples_copy):
    with _oauth_client(examples_copy) as client:
        verifier, challenge = _pkce_pair()

        authorize_res = _authorize(client, code_challenge=challenge)
        assert authorize_res.status_code == 302
        code, state = _extract_code(authorize_res)
        assert state == "xyz"

        token_res = client.post("/token", data=_token_form(code, verifier))
        assert token_res.status_code == 200
        access_token = token_res.json()["access_token"]

        mcp_res = client.post("/mcp", **_initialize({"Authorization": f"Bearer {access_token}"}))
        assert mcp_res.status_code == 200


def test_authorize_accepts_any_client_supplied_scope(examples_copy):
    """Connector setup screens often force you to fill in a "default"/"base"
    scope; this server ignores it entirely — capabilities come from CLI flags,
    not scopes — and must not reject the handshake over it."""
    with _oauth_client(examples_copy) as client:
        verifier, challenge = _pkce_pair()

        authorize_res = _authorize(client, code_challenge=challenge, scope="anything here")
        assert authorize_res.status_code == 302
        code, _ = _extract_code(authorize_res)

        token_res = client.post("/token", data=_token_form(code, verifier))
        assert token_res.status_code == 200


def test_static_token_still_works_when_oauth_enabled(examples_copy):
    with _oauth_client(examples_copy) as client:
        ok = _initialize({"Authorization": f"Bearer {TOKEN}"})
        assert client.post("/mcp", **ok).status_code == 200


def test_mcp_does_not_redirect_for_the_bare_path_with_oauth_enabled(examples_copy):
    with _oauth_client(examples_copy) as client:
        ok = _initialize({"Authorization": f"Bearer {TOKEN}"})
        res = client.post("/mcp", follow_redirects=False, **ok)
        assert res.status_code == 200


def test_token_accepts_client_secret_via_http_basic(examples_copy):
    with _oauth_client(examples_copy) as client:
        verifier, challenge = _pkce_pair()
        code, _ = _extract_code(_authorize(client, code_challenge=challenge))

        form = _token_form(code, verifier)
        del form["client_secret"]
        basic = base64.b64encode(f"{OAUTH_CLIENT_ID}:{OAUTH_CLIENT_SECRET}".encode()).decode()

        res = client.post("/token", data=form, headers={"Authorization": f"Basic {basic}"})
        assert res.status_code == 200
        assert "access_token" in res.json()


def test_token_rejects_wrong_client_secret(examples_copy):
    with _oauth_client(examples_copy) as client:
        verifier, challenge = _pkce_pair()
        code, _ = _extract_code(_authorize(client, code_challenge=challenge))

        res = client.post("/token", data=_token_form(code, verifier, client_secret="wrong"))
        assert res.status_code == 401


def test_token_rejects_wrong_code_verifier(examples_copy):
    with _oauth_client(examples_copy) as client:
        verifier, challenge = _pkce_pair()
        code, _ = _extract_code(_authorize(client, code_challenge=challenge))

        res = client.post("/token", data=_token_form(code, "wrong-verifier"))
        assert res.status_code == 400
        assert res.json()["error"] == "invalid_grant"


def test_authorize_rejects_unregistered_redirect_uri(examples_copy):
    with _oauth_client(examples_copy) as client:
        _, challenge = _pkce_pair()

        res = _authorize(
            client, code_challenge=challenge, redirect_uri="https://evil.example.com/cb"
        )
        assert res.status_code == 400


def test_mcp_rejects_a_tampered_access_token(examples_copy):
    with _oauth_client(examples_copy) as client:
        verifier, challenge = _pkce_pair()
        code, _ = _extract_code(_authorize(client, code_challenge=challenge))
        token_res = client.post("/token", data=_token_form(code, verifier))
        access_token = token_res.json()["access_token"]

        tampered = access_token[:-1] + ("A" if access_token[-1] != "A" else "B")
        res = client.post("/mcp", **_initialize({"Authorization": f"Bearer {tampered}"}))
        assert res.status_code == 401


def test_mcp_rejects_an_expired_access_token(examples_copy):
    provider = SingleClientOAuthProvider(
        client_id=OAUTH_CLIENT_ID,
        client_secret=OAUTH_CLIENT_SECRET,
        redirect_uris=[OAUTH_REDIRECT_URI],
        static_token=TOKEN,
    )
    expired = provider._sign(
        {"kind": "access", "client_id": OAUTH_CLIENT_ID, "exp": time.time() - 10, "scopes": []}
    )
    with _oauth_client(examples_copy) as client:
        res = client.post("/mcp", **_initialize({"Authorization": f"Bearer {expired}"}))
        assert res.status_code == 401


def test_tokens_survive_a_simulated_machine_restart(examples_copy):
    """Codes/tokens are stateless (HMAC-signed), so a token issued by one provider
    instance verifies against a freshly constructed one with the same client secret
    — simulating Fly.io tearing down and rebuilding an idle machine."""
    kwargs = dict(
        client_id=OAUTH_CLIENT_ID,
        client_secret=OAUTH_CLIENT_SECRET,
        redirect_uris=[OAUTH_REDIRECT_URI],
        static_token=TOKEN,
    )
    provider_a = SingleClientOAuthProvider(**kwargs)
    token = provider_a._sign(
        {"kind": "access", "client_id": OAUTH_CLIENT_ID, "exp": time.time() + 60, "scopes": []}
    )

    provider_b = SingleClientOAuthProvider(**kwargs)  # a fresh, unrelated instance
    access = asyncio.run(provider_b.load_access_token(token))
    assert access is not None and access.client_id == OAUTH_CLIENT_ID


def test_oauth_metadata_endpoints_are_reachable(examples_copy):
    with _oauth_client(examples_copy) as client:
        auth_meta = client.get("/.well-known/oauth-authorization-server")
        assert auth_meta.status_code == 200
        assert auth_meta.json()["issuer"].rstrip("/") == OAUTH_PUBLIC_URL

        resource_meta = client.get("/.well-known/oauth-protected-resource")
        assert resource_meta.status_code == 200
        assert OAUTH_PUBLIC_URL in json.dumps(resource_meta.json())
