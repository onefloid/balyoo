"""Abstract interfaces the core depends on.

The core is written entirely against these Protocols. Concrete storage, search
and validation backends live in separate packages and are injected at the edges
(e.g. by the CLI). This keeps the core independent of any particular backend.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from collections_core.capabilities import Capabilities
from collections_core.models import Item, Page, Query


@runtime_checkable
class StorageProvider(Protocol):
    """Persists collections and their items. Implemented per backend."""

    @property
    def capabilities(self) -> Capabilities: ...

    def list_collections(self) -> list[str]: ...

    def get_schema(self, collection: str) -> dict[str, Any]: ...

    def list_items(self, collection: str, query: Query) -> Page[Item]: ...

    def get_item(self, collection: str, item_id: str) -> Item: ...

    def create_item(self, collection: str, data: dict[str, Any]) -> Item: ...

    def update_item(self, collection: str, item_id: str, patch: dict[str, Any]) -> Item: ...

    def delete_item(self, collection: str, item_id: str) -> None: ...


@runtime_checkable
class SchemaValidator(Protocol):
    """Validates item data against a JSON Schema.

    Implementations must raise
    :class:`collections_core.errors.SchemaValidationError` on failure.
    """

    def validate(self, schema: dict[str, Any], data: dict[str, Any]) -> None: ...


@runtime_checkable
class SearchProvider(Protocol):
    """Optional pluggable search. When absent, providers may search in-memory."""

    def search(self, collection: str, items: list[Item], query: Query) -> list[Item]: ...
