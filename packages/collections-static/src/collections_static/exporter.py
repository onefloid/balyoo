"""Generate a static site from a :class:`CollectionsService`.

The JSON layout mirrors the REST routes so the *same* client works against a live
server or a static host::

    api/collections.json                     -> GET /collections
    api/collections/<c>.json                 -> GET /collections/<c>
    api/collections/<c>/schema.json          -> GET /collections/<c>/schema
    api/collections/<c>/items.json           -> GET /collections/<c>/items
    api/collections/<c>/items/<id>.json      -> GET /collections/<c>/items/<id>

Content is produced via ``model_dump()`` of the existing pydantic models, so it is
byte-for-byte the shape the REST API returns. Nothing here re-implements business
logic -- it only calls the service.

The UI itself is the built ``collections-ui`` bundle, laid down separately (by the
Pages workflow); this exporter only produces the JSON mirror plus a ``config.json``
that points the UI at ``api/`` in read-only static mode. Existing files in the
output directory (e.g. a UI build already placed there) are left untouched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from collections_core.models import Item, Query
from collections_core.service import CollectionsService

_PAGE_SIZE = 1000  # Query.limit is capped at 1000; paginate for larger collections.

# Consumed by collections-ui at runtime: read the mirror under api/ with GET-only,
# `.json`-suffixed requests. One build of the UI serves both this static deployment
# and a live read-write server (which ships its own config.json).
_STATIC_CONFIG = {"apiBase": "api/", "static": True}


def export_site(service: CollectionsService, out_dir: str | Path) -> None:
    """Write the static API mirror and the UI runtime config into ``out_dir``."""
    out = Path(out_dir)
    api = out / "api"

    infos = service.list_collections()
    _write_json(api / "collections.json", [info.model_dump() for info in infos])

    for info in infos:
        name = info.name
        base = api / "collections"
        _write_json(base / f"{name}.json", service.get_collection(name).model_dump())
        _write_json(base / name / "schema.json", service.get_schema(name))

        items = _all_items(service, name)
        _write_json(
            base / name / "items.json",
            {"items": [i.model_dump() for i in items], "total": len(items),
             "limit": len(items), "offset": 0},
        )
        for item in items:
            _write_json(base / name / "items" / f"{item.id}.json", item.model_dump())

    _write_json(out / "config.json", _STATIC_CONFIG)


def _all_items(service: CollectionsService, collection: str) -> list[Item]:
    """Collect every item, paging through the service so large collections work."""
    items: list[Item] = []
    offset = 0
    while True:
        page = service.list_items(collection, Query(limit=_PAGE_SIZE, offset=offset))
        items.extend(page.items)
        offset += len(page.items)
        if not page.items or offset >= page.total:
            return items


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
