"""SQLite-backed storage provider.

A durable, transactional :class:`~collections_core.interfaces.StorageProvider`.
Because the REST API, UI and MCP server depend only on the core interfaces and
capabilities, switching from the filesystem provider to SQLite requires no changes
to any adapter.
"""

from collections_sqlite.provider import SqliteStorageProvider

__all__ = ["SqliteStorageProvider"]
