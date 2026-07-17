"""MCP server for the Collections platform.

Exposes every collection over the Model Context Protocol so an AI assistant (Claude
Desktop and other MCP hosts) can browse, search and edit items natively. Built on
:class:`~collections_core.service.CollectionsService`, exactly like the REST layer,
so all validation and capability rules are reused.
"""

from collections_mcp.server import build_server, build_tools, dispatch, run_stdio

__all__ = ["build_server", "build_tools", "dispatch", "run_stdio"]
