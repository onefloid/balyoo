"""Domain errors raised by the core. Adapters map these to their own protocols.

For example the REST layer maps :class:`ItemNotFound` to HTTP 404 and
:class:`NotSupported` to HTTP 405 -- but the core itself knows nothing about HTTP.
"""

from __future__ import annotations


class CollectionsError(Exception):
    """Base class for all domain errors."""


class CollectionNotFound(CollectionsError):
    def __init__(self, collection: str) -> None:
        self.collection = collection
        super().__init__(f"Collection not found: {collection!r}")


class CollectionExists(CollectionsError):
    """Raised when creating a collection whose name is already taken."""

    def __init__(self, collection: str) -> None:
        self.collection = collection
        super().__init__(f"Collection already exists: {collection!r}")


class ItemNotFound(CollectionsError):
    def __init__(self, collection: str, item_id: str) -> None:
        self.collection = collection
        self.item_id = item_id
        super().__init__(f"Item not found: {collection!r}/{item_id!r}")


class SchemaValidationError(CollectionsError):
    """Raised when item data does not conform to its collection's JSON Schema."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("Schema validation failed: " + "; ".join(errors))


class NotSupported(CollectionsError):
    """Raised when an operation is not supported by the active capabilities."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(f"Operation not supported: {operation!r}")


class InvalidIdentifier(CollectionsError):
    """Raised when a collection or item id is not a safe, single path segment.

    Guards against path traversal (``..``, ``/``) and empty/reserved names when
    an id is used to address stored data.
    """

    def __init__(self, kind: str, value: str) -> None:
        self.kind = kind
        self.value = value
        super().__init__(f"Invalid {kind}: {value!r}")


class Conflict(CollectionsError):
    """Raised when a write conflicts with existing state (e.g. duplicate id)."""
