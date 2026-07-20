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
from collections_core.errors import InvalidIdentifier, NotSupported, SchemaValidationError
from collections_core.interfaces import SchemaValidator, StorageProvider
from collections_core.models import CollectionInfo, Item, Page, Query

# Collection names that would collide with the MCP server's generic collection-
# management tools (``create_collection``, ``update_schema``) once turned into the
# per-collection ``create_<name>`` / ``update_<name>`` tool names.
_RESERVED_COLLECTION_NAMES = frozenset({"collection", "schema"})


class CollectionsService:
    def __init__(
        self,
        provider: StorageProvider,
        validator: SchemaValidator | None = None,
        *,
        read_only: bool = False,
        deletable: bool = True,
    ) -> None:
        self._provider = provider
        self._validator = validator
        self._read_only = read_only
        self._deletable = deletable

    @property
    def capabilities(self) -> Capabilities:
        """Effective capabilities = provider capabilities masked by policy.

        ``read_only`` masks both write and delete; ``deletable=False`` additionally
        masks delete alone, so a caller can be granted writes without the more
        destructive delete (e.g. a token with the write scope but not the delete
        scope).
        """
        caps = self._provider.capabilities
        update: dict[str, bool] = {}
        if self._read_only:
            update.update(supports_write=False, supports_delete=False)
        if not self._deletable:
            update["supports_delete"] = False
        return caps.model_copy(update=update) if update else caps

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

    def create_collection(self, collection: str, schema: dict[str, Any]) -> None:
        """Create a new collection from a (meta-validated) JSON Schema.

        The schema is checked for being a well-formed JSON Schema before it is
        persisted, so a malformed definition is rejected up front rather than
        surfacing later as confusing item-validation errors.
        """
        self._require("write")
        if collection in _RESERVED_COLLECTION_NAMES:
            raise InvalidIdentifier("collection name (reserved)", collection)
        self._check_schema(schema)
        self._provider.create_collection(collection, schema)

    def update_schema(self, collection: str, schema: dict[str, Any]) -> list[str]:
        """Replace a collection's schema; return ids of now-invalid items.

        Changing a schema can retroactively invalidate stored items. The update is
        not blocked (the caller may be tightening the schema deliberately), but the
        ids of items that no longer conform are returned so the caller can warn.
        """
        self._require("write")
        self._check_schema(schema)
        self._provider.update_schema(collection, schema)
        return self._invalid_items(collection, schema)

    def delete_collection(self, collection: str) -> None:
        self._require("delete")
        self._provider.delete_collection(collection)

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

    def _check_schema(self, schema: dict[str, Any]) -> None:
        if self._validator is None:
            return
        self._validator.check_schema(schema)

    def _invalid_items(self, collection: str, schema: dict[str, Any]) -> list[str]:
        """Ids of stored items that do not conform to ``schema`` (empty if none)."""
        if self._validator is None:
            return []
        invalid: list[str] = []
        offset = 0
        while True:
            page = self._provider.list_items(collection, Query(limit=1000, offset=offset))
            for item in page.items:
                try:
                    self._validator.validate(schema, item.data)
                except SchemaValidationError:
                    invalid.append(item.id)
            offset += len(page.items)
            if not page.items or offset >= page.total:
                break
        return invalid

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
