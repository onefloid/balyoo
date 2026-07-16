"""Deterministic, schema-validated upsert logic for ``collections ingest``.

This is the safe write gate. A caller (a human, or Claude acting as the ingestion
agent) supplies an already-structured item as JSON; this module decides create vs.
update, validates the result against the collection's JSON Schema, and describes
the change so it can be previewed before anything is written or published.

The natural-language -> structured-item step is intentionally *not* here: that is
the LLM's job. Everything in this module is deterministic and testable.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from collections_core.errors import ItemNotFound
from collections_core.models import Item
from collections_core.service import CollectionsService
from collections_schema.validator import JsonSchemaValidator

_SLUG_FIELDS = ("name", "title", "id")
_validator = JsonSchemaValidator()


@dataclass
class UpsertPlan:
    """A previewable description of an upsert, before it is applied."""

    action: str  # "create" or "update"
    collection: str
    slug: str
    target: dict[str, Any]  # the full item data after the upsert
    changes: list[str] = field(default_factory=list)  # human-readable diff (updates)


def slugify(value: str) -> str:
    """Turn a label into a filesystem/URL-safe id, e.g. 'Cool Bar!' -> 'cool-bar'."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or uuid.uuid4().hex


def resolve_slug(data: dict[str, Any], explicit_id: str | None = None) -> str:
    """Pick the item id: explicit --id, else an id/name/title field, else a uuid."""
    if explicit_id:
        return slugify(explicit_id)
    for field_name in _SLUG_FIELDS:
        value = data.get(field_name)
        if isinstance(value, str) and value.strip():
            return slugify(value)
    return uuid.uuid4().hex


def plan_upsert(
    service: CollectionsService, collection: str, slug: str, data: dict[str, Any]
) -> UpsertPlan:
    """Validate the intended write and describe it, without applying it.

    Raises ``CollectionNotFound`` if the collection is unknown and
    ``SchemaValidationError`` if the resulting item would be invalid.
    """
    schema = service.get_schema(collection)  # raises CollectionNotFound

    try:
        existing: Item | None = service.get_item(collection, slug)
    except ItemNotFound:
        existing = None

    # ``id`` is metadata (the filename), not part of the stored item data.
    incoming = {k: v for k, v in data.items() if k != "id"}

    if existing is None:
        target = incoming
        changes: list[str] = []
        action = "create"
    else:
        target = {**existing.data, **incoming}
        changes = _diff(existing.data, incoming)
        action = "update"

    _validator.validate(schema, target)
    return UpsertPlan(action=action, collection=collection, slug=slug,
                      target=target, changes=changes)


def _diff(old: dict[str, Any], patch: dict[str, Any]) -> list[str]:
    """Field-level, human-readable diff of a patch against existing data."""
    lines: list[str] = []
    for key, value in patch.items():
        if key not in old:
            lines.append(f"+ {key}: {value!r}")
        elif old[key] != value:
            lines.append(f"~ {key}: {old[key]!r} -> {value!r}")
    return lines
