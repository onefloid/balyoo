"""Remote (HTTP) MCP server, secured as an OAuth 2.1 resource server.

For a cloud LLM the MCP server must be reachable at a URL over the Streamable HTTP
transport, and — since anyone could reach it — protected. Following the MCP
Authorization spec, this server is a *resource server*: an external OIDC identity
provider issues the tokens, and here we only verify the presented bearer JWT and
map its scopes onto capabilities:

- a valid token → read tools;
- the write scope → create/update tools;
- the delete scope → delete tool.

That reuses the exact capability gating in :func:`build_tools`; nothing about the
tool set is special-cased for HTTP.
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
from collections.abc import Callable

import anyio
import httpx
import jwt
from collections_core.service import CollectionsService
from mcp.server.auth.middleware.auth_context import (
    AuthContextMiddleware,
    get_access_token,
)
from mcp.server.auth.middleware.bearer_auth import (
    BearerAuthBackend,
    RequireAuthMiddleware,
)
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.routes import create_protected_resource_routes
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from collections_mcp.server import build_server

logger = logging.getLogger("collections_mcp")

# Produce a service for the current request given the granted capabilities
# (read_only, no_delete) and the authenticated subject (for optional per-user data
# isolation). Supplied by the composition layer (the CLI) so this package stays
# provider-agnostic.
ServiceFactory = Callable[[bool, bool, "str | None"], CollectionsService]


@dataclasses.dataclass
class OAuthConfig:
    """OIDC/OAuth settings for the resource server."""

    issuer_url: str  # the identity provider (authorization server)
    resource_url: str  # public URL of THIS MCP server (the protected resource)
    write_scope: str = "collections:write"
    delete_scope: str = "collections:delete"
    audience: str | None = None  # defaults to resource_url
    jwks_url: str | None = None  # defaults to the issuer's OIDC-discovered JWKS

    def resolved_audience(self) -> str:
        return self.audience or self.resource_url

    def resolved_jwks_url(self) -> str:
        if self.jwks_url:
            return self.jwks_url
        discovery = self.issuer_url.rstrip("/") + "/.well-known/openid-configuration"
        meta = httpx.get(discovery, timeout=10).raise_for_status().json()
        return meta["jwks_uri"]

    @property
    def scopes_supported(self) -> list[str]:
        return [self.write_scope, self.delete_scope]


def _scopes(claims: dict) -> list[str]:
    """Collect scopes from the common JWT shapes (OAuth `scope`, `scp`, Auth0
    `permissions`)."""
    found: list[str] = []
    scope = claims.get("scope")
    if isinstance(scope, str):
        found += scope.split()
    for key in ("scp", "permissions"):
        value = claims.get(key)
        if isinstance(value, list):
            found += [s for s in value if isinstance(s, str)]
    return found


class JwtTokenVerifier(TokenVerifier):
    """Verify a bearer JWT against the identity provider's JWKS.

    The JWKS client is created lazily on first use so the server boots even if the
    identity provider is briefly unreachable (a transient IdP outage yields 401s
    rather than a crash-loop, and recovers on its own).
    """

    def __init__(
        self, *, jwks_url_provider: Callable[[], str], issuer: str, audience: str
    ) -> None:
        self._jwks_url_provider = jwks_url_provider
        self._issuer = issuer
        self._audience = audience
        self._jwks: jwt.PyJWKClient | None = None

    def _decode(self, token: str) -> dict:
        if self._jwks is None:
            self._jwks = jwt.PyJWKClient(self._jwks_url_provider())
        key = self._jwks.get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            key,
            algorithms=["RS256", "RS384", "RS512", "ES256"],
            audience=self._audience,
            issuer=self._issuer,
            options={"require": ["exp"]},
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = await anyio.to_thread.run_sync(self._decode, token)
        except Exception as exc:  # invalid signature / audience / issuer / expiry
            # Never log the token itself; the exception type is enough to debug.
            logger.warning("MCP token verification failed: %s", type(exc).__name__)
            return None
        return AccessToken(
            token=token,
            client_id=str(claims.get("azp") or claims.get("client_id") or ""),
            scopes=_scopes(claims),
            expires_at=claims.get("exp"),
            subject=str(claims.get("sub")) if claims.get("sub") else None,
            claims=claims,
        )


def make_service_resolver(service_factory: ServiceFactory, oauth: OAuthConfig):
    """A resolver that reads the authenticated token and maps its scopes to
    capabilities, so the token decides what the assistant may do."""

    def resolve() -> CollectionsService:
        token = get_access_token()
        scopes = token.scopes if token else []
        can_write = oauth.write_scope in scopes
        can_delete = oauth.delete_scope in scopes
        subject = token.subject if token else None
        return service_factory(not can_write, not can_delete, subject)

    return resolve


def build_asgi_app(
    service_factory: ServiceFactory,
    oauth: OAuthConfig,
    *,
    verifier: TokenVerifier | None = None,
) -> Starlette:
    """Build the OAuth-protected Streamable HTTP MCP app (mounted at ``/mcp``).

    ``verifier`` can be injected for testing; by default a :class:`JwtTokenVerifier`
    is built from ``oauth`` (with lazy JWKS discovery).
    """
    if verifier is None:
        verifier = JwtTokenVerifier(
            jwks_url_provider=oauth.resolved_jwks_url,
            issuer=oauth.issuer_url,
            audience=oauth.resolved_audience(),
        )
    manager = StreamableHTTPSessionManager(
        app=build_server(make_service_resolver(service_factory, oauth)),
        json_response=True,
        stateless=True,
    )

    async def handle_mcp(scope, receive, send) -> None:
        await manager.handle_request(scope, receive, send)

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    resource_metadata_url = AnyHttpUrl(
        oauth.resource_url.rstrip("/") + "/.well-known/oauth-protected-resource"
    )
    # A valid token is required to reach the MCP endpoint; the specific write/delete
    # scopes are enforced per-tool by the capability gating, not here.
    guarded_mcp = RequireAuthMiddleware(
        handle_mcp, required_scopes=[], resource_metadata_url=resource_metadata_url
    )

    routes = [
        Route("/health", health, methods=["GET"]),
        Mount("/mcp", app=guarded_mcp),
        *create_protected_resource_routes(
            resource_url=AnyHttpUrl(oauth.resource_url),
            authorization_servers=[AnyHttpUrl(oauth.issuer_url)],
            scopes_supported=oauth.scopes_supported,
            resource_name="Collections",
        ),
    ]
    middleware = [
        Middleware(AuthenticationMiddleware, backend=BearerAuthBackend(verifier)),
        Middleware(AuthContextMiddleware),
    ]

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette):
        async with manager.run():
            yield

    return Starlette(routes=routes, middleware=middleware, lifespan=lifespan)
