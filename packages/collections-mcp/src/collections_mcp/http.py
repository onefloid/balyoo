"""Remote (HTTP) MCP server, protected by a static bearer token.

For a cloud LLM the MCP server must be reachable at a URL over the Streamable HTTP
transport, and — since anyone could reach it — protected. Rather than a full OAuth
2.1 / OIDC setup (which needs an external identity provider), this server uses a
single shared secret: every request to ``/mcp`` must carry
``Authorization: Bearer <token>``, checked in constant time against the configured
``COLLECTIONS_MCP_TOKEN``. A valid token grants full access; what that access
_includes_ (read-only, no-delete) is decided when the service is built, from CLI
flags — not per request.

Pass ``token=None`` to serve without authentication (the ``--allow-anonymous``
escape hatch, e.g. behind another gateway or for a purely read-only deployment).
"""

from __future__ import annotations

import contextlib
import hmac

from collections_core.service import CollectionsService
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from collections_mcp.server import build_server


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


def build_asgi_app(service: CollectionsService, *, token: str | None) -> Starlette:
    """Build the token-protected Streamable HTTP MCP app (mounted at ``/mcp``).

    ``service`` is already configured with its effective capabilities (read-only,
    deletable); the token only gates access, it does not change what tools exist.
    Pass ``token=None`` to serve ``/mcp`` without authentication.
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

    routes = [
        Route("/health", health, methods=["GET"]),
        Mount("/mcp", app=_require_token(handle_mcp, token)),
    ]

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette):
        async with manager.run():
            yield

    return Starlette(routes=routes, lifespan=lifespan)
