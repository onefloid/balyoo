"""Collections core: backend-agnostic business logic and interfaces.

The core knows nothing about REST, MCP, databases or the filesystem. It only
depends on the abstract interfaces defined in :mod:`collections_core.interfaces`
and orchestrates them through :class:`collections_core.service.CollectionsService`.
"""

from collections_core.capabilities import Capabilities
from collections_core.errors import (
    CollectionNotFound,
    CollectionsError,
    Conflict,
    ItemNotFound,
    NotSupported,
    SchemaValidationError,
)
from collections_core.interfaces import SchemaValidator, SearchProvider, StorageProvider
from collections_core.models import CollectionInfo, Item, Page, Query
from collections_core.service import CollectionsService

__all__ = [
    "Capabilities",
    "CollectionInfo",
    "CollectionNotFound",
    "CollectionsError",
    "CollectionsService",
    "Conflict",
    "Item",
    "ItemNotFound",
    "NotSupported",
    "Page",
    "Query",
    "SchemaValidationError",
    "SchemaValidator",
    "SearchProvider",
    "StorageProvider",
]
