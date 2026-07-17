"""Remote (HTTP) MCP server, protected by a static bearer token and/or a
self-hosted OAuth 2.1 Authorization Server.

For a cloud LLM the MCP server must be reachable at a URL over the Streamable HTTP
transport, and — since anyone could reach it — protected. The baseline is a single
shared secret: every request to ``/mcp`` must carry
``Authorization: Bearer <token>``, checked in constant time against the configured
``COLLECTIONS_MCP_TOKEN``. That's enough for curl, the Anthropic API MCP connector,
and bridges like ``mcp-remote``.

Some MCP hosts (ChatGPT, Claude.ai custom connectors) only accept a Client ID +
Client Secret and drive a real OAuth 2.1 Authorization Code flow with PKCE. Rather
than depending on an external identity provider, this module can make *this same
server* act as its own Authorization Server for exactly one pre-configured client
(``OAuthConfig``): ``/authorize`` auto-approves immediately — safe, because the
actual gate is the client secret required at ``/token``, and this is a
single-owner service, not a multi-tenant IdP. Authorization codes and issued
access/refresh tokens are HMAC-signed, self-describing strings rather than
anything stored server-side, so they survive Fly.io's scale-to-zero machine
restarts without a database. All the OAuth mechanics themselves (PKCE
verification, redirect_uri/state handling, RFC 8414/9728 metadata) are the
``mcp`` SDK's own — see :mod:`mcp.server.auth` — driven by the
``OAuthAuthorizationServerProvider`` protocol implemented here as
:class:`SingleClientOAuthProvider`.

Pass ``token=None`` to serve without authentication (the ``--allow-anonymous``
escape hatch, e.g. behind another gateway or for a purely read-only deployment) —
OAuth is not available in that mode.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import dataclasses
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import unquote

from collections_core.service import CollectionsService
from mcp.server.auth.handlers.authorize import AuthorizationHandler
from mcp.server.auth.handlers.metadata import MetadataHandler
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.middleware.client_auth import AuthenticationError
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    ProviderTokenVerifier,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.server.auth.routes import (
    build_metadata,
    build_resource_metadata_url,
    cors_middleware,
    create_protected_resource_routes,
)
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl, AnyUrl
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from collections_mcp.server import build_server

ACCESS_TOKEN_TTL = 3600  # 1 hour
REFRESH_TOKEN_TTL = 60 * 60 * 24 * 30  # 30 days
AUTH_CODE_TTL = 300  # 5 minutes, per RFC 6749 section 10.5


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _require_token(app: ASGIApp, token: str | None) -> ASGIApp:
    """Wrap an ASGI app so HTTP requests must present the bearer ``token``.

    With ``token is None`` the wrapper is a pass-through (anonymous access). The
    comparison is constant-time to avoid leaking the secret through timing.
    """
    if token is None:
        return app

    async def guarded(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await app(scope, receive, send)
            return
        header = dict(scope["headers"]).get(b"authorization", b"").decode()
        prefix = "bearer "
        provided = header[len(prefix) :] if header[: len(prefix)].lower() == prefix else ""
        if not hmac.compare_digest(provided, token):
            response = JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        await app(scope, receive, send)

    return guarded


@dataclasses.dataclass
class OAuthConfig:
    """A single, pre-configured OAuth client this server issues tokens for."""

    client_id: str
    client_secret: str
    redirect_uris: list[str]
    public_url: str  # this server's own https:// base URL; used as issuer + resource


class SingleClientOAuthProvider:
    """A minimal, self-hosted OAuth 2.1 Authorization Server for exactly one
    pre-configured client — no external IdP, no login page.

    ``/authorize`` auto-approves immediately; the client secret required at
    ``/token`` is what actually gates access. Authorization codes and issued
    access/refresh tokens are HMAC-signed JSON payloads, not stored anywhere, so
    they verify correctly even after this process restarts (Fly.io stops idle
    machines and rebuilds them fresh on the next request).
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uris: list[str],
        static_token: str | None,
    ) -> None:
        self._client = OAuthClientInformationFull(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uris=[AnyUrl(uri) for uri in redirect_uris],
            token_endpoint_auth_method="client_secret_post",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        )
        self._static_token = static_token
        self._key = client_secret.encode()

    def _sign(self, payload: dict[str, Any]) -> str:
        body = json.dumps(payload, separators=(",", ":")).encode()
        signature = hmac.new(self._key, body, hashlib.sha256).digest()
        return f"{_b64encode(body)}.{_b64encode(signature)}"

    def _verify(self, token: str, expected_kind: str) -> dict[str, Any] | None:
        try:
            body_b64, signature_b64 = token.split(".", 1)
            body = _b64decode(body_b64)
            signature = _b64decode(signature_b64)
        except (ValueError, binascii.Error):
            return None
        expected_signature = hmac.new(self._key, body, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected_signature):
            return None
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return None
        if payload.get("kind") != expected_kind or payload.get("exp", 0) < time.time():
            return None
        return payload

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._client if client_id == self._client.client_id else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        raise NotImplementedError  # dynamic client registration is disabled

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        code = self._sign(
            {
                "kind": "code",
                "client_id": client.client_id,
                "exp": time.time() + AUTH_CODE_TTL,
                "code_challenge": params.code_challenge,
                "redirect_uri": str(params.redirect_uri),
                "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
                "scopes": params.scopes or [],
            }
        )
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        payload = self._verify(authorization_code, "code")
        if payload is None or payload["client_id"] != client.client_id:
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=payload["scopes"],
            expires_at=payload["exp"],
            client_id=payload["client_id"],
            code_challenge=payload["code_challenge"],
            redirect_uri=AnyUrl(payload["redirect_uri"]),
            redirect_uri_provided_explicitly=payload["redirect_uri_provided_explicitly"],
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        return self._issue_token(client, authorization_code.scopes)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        payload = self._verify(refresh_token, "refresh")
        if payload is None or payload["client_id"] != client.client_id:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=payload["client_id"],
            scopes=payload["scopes"],
            expires_at=int(payload["exp"]),
        )

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        return self._issue_token(client, scopes or refresh_token.scopes)

    def _issue_token(self, client: OAuthClientInformationFull, scopes: list[str]) -> OAuthToken:
        access = self._sign(
            {
                "kind": "access",
                "client_id": client.client_id,
                "exp": time.time() + ACCESS_TOKEN_TTL,
                "scopes": scopes,
            }
        )
        refresh = self._sign(
            {
                "kind": "refresh",
                "client_id": client.client_id,
                "exp": time.time() + REFRESH_TOKEN_TTL,
                "scopes": scopes,
            }
        )
        return OAuthToken(
            access_token=access,
            expires_in=ACCESS_TOKEN_TTL,
            refresh_token=refresh,
            scope=" ".join(scopes) if scopes else None,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        if self._static_token is not None and hmac.compare_digest(token, self._static_token):
            return AccessToken(token=token, client_id="static", scopes=[])
        payload = self._verify(token, "access")
        if payload is None:
            return None
        return AccessToken(
            token=token,
            client_id=payload["client_id"],
            scopes=payload["scopes"],
            expires_at=int(payload["exp"]),
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        # Stateless tokens can't be individually blacklisted; rotating the client
        # secret (which is also the HMAC signing key) invalidates every previously
        # issued code/token at once. /revoke isn't mounted, so this never runs.
        pass


class _LenientClientAuthenticator:
    """Authenticates ``/token`` requests, accepting the client secret from either
    HTTP Basic auth or a ``client_secret`` form field.

    The SDK's own :class:`~mcp.server.auth.middleware.client_auth.ClientAuthenticator`
    strictly branches on the client's *declared* ``token_endpoint_auth_method``, but
    real-world OAuth clients aren't consistent about which one they use for a
    manually pasted-in client_id/secret — so this accepts either, rather than
    guessing which style a given connector uses.
    """

    def __init__(self, provider: SingleClientOAuthProvider) -> None:
        self._provider = provider

    async def authenticate_request(self, request: Request) -> OAuthClientInformationFull:
        form = await request.form()
        client_id = form.get("client_id")
        if not client_id:
            raise AuthenticationError("Missing client_id")
        client = await self._provider.get_client(str(client_id))
        if not client:
            raise AuthenticationError("Invalid client_id")

        raw_secret = form.get("client_secret")
        secret = raw_secret if isinstance(raw_secret, str) else None
        auth_header = request.headers.get("Authorization", "")
        if secret is None and auth_header.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                basic_client_id, secret = decoded.split(":", 1)
                if unquote(basic_client_id) != client_id:
                    raise AuthenticationError("Client ID mismatch in Basic auth")
                secret = unquote(secret)
            except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
                raise AuthenticationError("Invalid Basic authentication header") from exc

        if (
            not secret
            or not client.client_secret
            or not hmac.compare_digest(client.client_secret.encode(), secret.encode())
        ):
            raise AuthenticationError("Invalid client_secret")
        return client


def build_asgi_app(
    service: CollectionsService, *, token: str | None, oauth: OAuthConfig | None = None
) -> Starlette:
    """Build the Streamable HTTP MCP app (mounted at ``/mcp``).

    ``service`` is already configured with its effective capabilities (read-only,
    deletable); auth only gates access, it does not change what tools exist.
    ``token=None`` serves ``/mcp`` without authentication. When ``oauth`` is given,
    this server additionally becomes its own OAuth 2.1 Authorization Server for
    that one client (see :class:`SingleClientOAuthProvider`) — ``/mcp`` then
    accepts either the static ``token`` or a token issued through that flow.
    """
    manager = StreamableHTTPSessionManager(
        app=build_server(service),
        json_response=True,
        stateless=True,
    )

    async def handle_mcp(scope: Scope, receive: Receive, send: Send) -> None:
        await manager.handle_request(scope, receive, send)

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    routes: list[Route] = [Route("/health", health, methods=["GET"])]
    middleware: list[Middleware] = []

    if oauth is None:
        routes.append(Mount("/mcp", app=_require_token(handle_mcp, token)))
    else:
        provider = SingleClientOAuthProvider(
            client_id=oauth.client_id,
            client_secret=oauth.client_secret,
            redirect_uris=oauth.redirect_uris,
            static_token=token,
        )
        issuer_url = AnyHttpUrl(oauth.public_url)
        metadata = build_metadata(
            issuer_url, None, ClientRegistrationOptions(), RevocationOptions()
        )
        routes += [
            Route(
                "/.well-known/oauth-authorization-server",
                endpoint=cors_middleware(MetadataHandler(metadata).handle, ["GET", "OPTIONS"]),
                methods=["GET", "OPTIONS"],
            ),
            Route(
                "/authorize",
                endpoint=AuthorizationHandler(provider).handle,
                methods=["GET", "POST"],
            ),
            Route(
                "/token",
                endpoint=cors_middleware(
                    TokenHandler(provider, _LenientClientAuthenticator(provider)).handle,
                    ["POST", "OPTIONS"],
                ),
                methods=["POST", "OPTIONS"],
            ),
            *create_protected_resource_routes(
                resource_url=issuer_url,
                authorization_servers=[issuer_url],
                resource_name="Collections",
            ),
        ]
        guarded_mcp = RequireAuthMiddleware(
            handle_mcp,
            required_scopes=[],
            resource_metadata_url=build_resource_metadata_url(issuer_url),
        )
        routes.append(Mount("/mcp", app=guarded_mcp))
        middleware = [
            Middleware(
                AuthenticationMiddleware,
                backend=BearerAuthBackend(ProviderTokenVerifier(provider)),
            ),
            Middleware(AuthContextMiddleware),
        ]

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette):
        async with manager.run():
            yield

    return Starlette(routes=routes, middleware=middleware, lifespan=lifespan)
