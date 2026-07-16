"""Capability descriptors for storage providers.

Not every backend supports every operation. Each provider advertises what it can
do via a :class:`Capabilities` instance so that the REST API, MCP server and UI
can adapt automatically (e.g. hide write actions for a read-only deployment).
"""

from __future__ import annotations

from pydantic import BaseModel


class Capabilities(BaseModel):
    """What a storage provider (or a service configuration) is able to do."""

    supports_read: bool = False
    supports_write: bool = False
    supports_delete: bool = False
    supports_search: bool = False
    supports_transactions: bool = False
