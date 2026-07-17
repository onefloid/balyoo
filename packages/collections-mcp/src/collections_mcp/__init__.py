"""MCP server for the Collections platform.

Exposes every collection over the Model Context Protocol so an AI assistant (Claude
Desktop and other MCP hosts) can browse, search and edit items natively. Built on
:class:`~collections_core.service.CollectionsService`, exactly like the REST layer,
so all validation and capability rules are reused.
"""

from collections_mcp.server import build_server, build_tools, dispatch, run_stdio

__all__ = [
    "build_server",
    "build_tools",
    "dispatch",
    "run_stdio",
    "build_asgi_app",
]


def __getattr__(name: str):
    # Lazily expose the HTTP server so importing the package (e.g. for the stdio
    # server) doesn't require the HTTP transport dependencies to be present.
    if name == "build_asgi_app":
        from collections_mcp import http

        return http.build_asgi_app
    raise AttributeError(name)
