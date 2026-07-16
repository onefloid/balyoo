"""Fixed data models shared across the platform.

These pydantic models describe the *fixed* structures of the platform (queries,
pages, item envelopes). The *dynamic* content of an item lives in ``Item.data``
as a plain ``dict`` and is validated against the collection's JSON Schema by a
:class:`~collections_core.interfaces.SchemaValidator` -- not by pydantic.
"""

from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

from collections_core.capabilities import Capabilities

T = TypeVar("T")


class Item(BaseModel):
    """A single stored object. ``id`` identifies it, ``data`` is schema-driven."""

    id: str
    data: dict[str, Any]


class Query(BaseModel):
    """A backend-agnostic query over a collection's items."""

    filters: dict[str, str] = Field(default_factory=dict)
    q: str | None = None
    sort: str | None = None
    order: Literal["asc", "desc"] = "asc"
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class Page(BaseModel, Generic[T]):
    """A paginated slice of results."""

    items: list[T]
    total: int
    limit: int
    offset: int


class CollectionInfo(BaseModel):
    """Metadata describing a collection and what can be done with it."""

    name: str
    capabilities: Capabilities
    item_count: int
