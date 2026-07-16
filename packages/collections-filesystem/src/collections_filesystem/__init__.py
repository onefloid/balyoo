"""Filesystem storage provider.

Collections live on disk as::

    <root>/<collection>/schema.json
    <root>/<collection>/items/<id>.json

This layout is directly deployable as static files (read-only) or used with full
CRUD (read-write).
"""

from collections_filesystem.provider import FilesystemStorageProvider

__all__ = ["FilesystemStorageProvider"]
