"""In-memory query engine shared by storage providers.

Providers that hold their items in memory (or can load a collection's items) reuse
:func:`run_query` so filtering, full-text search, sorting and pagination behave
identically across backends.
"""

from __future__ import annotations

import json
from typing import Any

from collections_core.models import Item, Page, Query


def run_query(items: list[Item], query: Query) -> Page[Item]:
    """Filter, search, sort and paginate ``items`` per ``query``."""
    filtered = _filter(items, query)
    total = len(filtered)
    ordered = _sort(filtered, query)
    window = ordered[query.offset : query.offset + query.limit]
    return Page[Item](items=window, total=total, limit=query.limit, offset=query.offset)


def _filter(items: list[Item], query: Query) -> list[Item]:
    result = items
    if query.filters:
        result = [
            item
            for item in result
            if all(str(item.data.get(k)) == v for k, v in query.filters.items())
        ]
    if query.q:
        needle = query.q.lower()
        result = [item for item in result if _contains(item.data, needle)]
    return result


def _sort(items: list[Item], query: Query) -> list[Item]:
    if not query.sort:
        return items
    field = query.sort
    return sorted(
        items,
        key=lambda item: _sort_key(item.data.get(field)),
        reverse=query.order == "desc",
    )


def _sort_key(value: Any) -> tuple[int, Any]:
    """A total, type-safe sort key so heterogeneous field values never crash.

    Values are bucketed by type rank first, so different types are never compared
    against each other; within a bucket the natural value orders as expected.
    Unorderable values (lists, dicts) fall back to a stable JSON string, and
    missing/None values sort last on ascending.
    """
    if value is None:
        return (4, "")
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, (int, float)):
        return (1, value)
    if isinstance(value, str):
        return (2, value)
    return (3, json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))


def _contains(data: dict[str, Any], needle: str) -> bool:
    """True if any string value (top-level or nested in lists) contains needle."""
    for value in data.values():
        if isinstance(value, str) and needle in value.lower():
            return True
        if isinstance(value, list) and any(
            isinstance(v, str) and needle in v.lower() for v in value
        ):
            return True
    return False
