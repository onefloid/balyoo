"""Generic REST API. Every route is derived from collections and schemas -- there
are no collection-specific endpoints."""

from collections_rest.app import create_app

__all__ = ["create_app"]
