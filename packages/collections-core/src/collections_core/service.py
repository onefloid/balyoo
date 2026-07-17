"""The single place where business policy lives.

``CollectionsService`` orchestrates a storage provider and an optional schema
validator. It enforces capabilities (raising :class:`NotSupported` when an
operation is not allowed) and validates item data before writes. A service can
be configured ``read_only`` to mask a writable provider's write/delete
capabilities -- this is how the *same* application serves both read-only and
read-write deployments without any API or UI changes.
"""

from __future__ import annotations

from typing import Any

from collections_core.capabilities import Capabilities
from collections_core.errors import NotSupported
from collections_core.interfaces import SchemaValidator, StorageProvider
from collections_core.models import CollectionInfo, Item, Page, Query


class CollectionsService:
    def __init__(
        self,
        provider: StorageProvider,
        validator: SchemaValidator | None = None,
        *,
        read_only: bool = False,
    ) -> None:
        self._provider = provider
        self._validator = validator
        self._read_only = read_only

    @property
    def capabilities(self) -> Capabilities:
        """Effective capabilities = provider capabilities masked by read_only."""
        caps = self._provider.capabilities
        if self._read_only:
            return caps.model_copy(update={"supports_write": False, "supports_delete": False})
        return caps

    # -- collections -----------------------------------------------------
    def list_collections(self) -> list[CollectionInfo]:
        caps = self.capabilities
        return [
            CollectionInfo(name=name, capabilities=caps, item_count=self._count(name))
            for name in self._provider.list_collections()
        ]

    def get_collection(self, collection: str) -> CollectionInfo:
        # get_schema raises CollectionNotFound if the collection does not exist.
        self._provider.get_schema(collection)
        return CollectionInfo(
            name=collection,
            capabilities=self.capabilities,
            item_count=self._count(collection),
        )

    def get_schema(self, collection: str) -> dict[str, Any]:
        return self._provider.get_schema(collection)

    # -- items -----------------------------------------------------------
    def list_items(self, collection: str, query: Query) -> Page[Item]:
        self._require("read")
        # A query that filters or full-text searches needs the search capability;
        # a plain listing only needs read.
        if query.q or query.filters:
            self._require("search")
        return self._provider.list_items(collection, query)

    def get_item(self, collection: str, item_id: str) -> Item:
        self._require("read")
        return self._provider.get_item(collection, item_id)

    def create_item(self, collection: str, data: dict[str, Any]) -> Item:
        self._require("write")
        # ``id`` is a filename/metadata hint the provider consumes to address the
        # item; it is not stored content, so it must not be schema-validated
        # (otherwise a strict ``additionalProperties: false`` schema would reject
        # a create that a preview -- which never sees ``id`` -- reported as valid).
        self._validate(collection, {k: v for k, v in data.items() if k != "id"})
        return self._provider.create_item(collection, data)

    def update_item(self, collection: str, item_id: str, patch: dict[str, Any]) -> Item:
        self._require("write")
        current = self._provider.get_item(collection, item_id)
        self._validate(collection, {**current.data, **patch})
        return self._provider.update_item(collection, item_id, patch)

    def delete_item(self, collection: str, item_id: str) -> None:
        self._require("delete")
        self._provider.delete_item(collection, item_id)

    # -- internals -------------------------------------------------------
    def _count(self, collection: str) -> int:
        return self._provider.list_items(collection, Query(limit=1)).total

    def _validate(self, collection: str, data: dict[str, Any]) -> None:
        if self._validator is None:
            return
        schema = self._provider.get_schema(collection)
        self._validator.validate(schema, data)

    def _require(self, operation: str) -> None:
        caps = self.capabilities
        allowed = {
            "read": caps.supports_read,
            "write": caps.supports_write,
            "delete": caps.supports_delete,
            "search": caps.supports_search,
        }
        if not allowed.get(operation, False):
            raise NotSupported(operation)
