"""Static site generator.

Exports a collection service to a directory of flat JSON files whose layout
mirrors the REST API, plus a minimal read-only web UI that reads them. The result
is deployable to any static host (GitHub Pages, Cloudflare Pages, …) with no
server and no database.
"""

from collections_static.exporter import export_site

__all__ = ["export_site"]
