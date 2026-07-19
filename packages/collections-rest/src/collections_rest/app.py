"""FastAPI application factory.

``create_app(service)`` builds a fully generic REST API on top of a
:class:`~collections_core.service.CollectionsService`. The same routes work for
every collection and every backend; capabilities and validation are enforced by
the service, and domain errors are mapped to HTTP status codes here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from collections_core.errors import (
    CollectionNotFound,
    Conflict,
    InvalidIdentifier,
    ItemNotFound,
    NotSupported,
    SchemaValidationError,
)
from collections_core.models import Query
from collections_core.service import CollectionsService
from fastapi import FastAPI, Request
from fastapi import Query as QueryParam
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

_RESERVED_PARAMS = {"limit", "offset", "sort", "order", "q"}


def create_app(
    service: CollectionsService,
    *,
    ui_dir: str | Path | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Collections API",
        version="0.1.0",
        description="Generic, schema-driven REST API for arbitrary collections.",
    )
    # A public, cross-origin API (e.g. served next to the MCP server for browser
    # clients on other origins) needs CORS. Left off by default so a same-origin
    # deployment adds no headers; pass ["*"] to allow any origin.
    if cors_origins is not None:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["GET", "HEAD", "OPTIONS"],
            allow_headers=["*"],
        )
    _register_error_handlers(app)

    @app.get("/collections")
    def list_collections() -> list[dict[str, Any]]:
        return [info.model_dump() for info in service.list_collections()]

    @app.get("/collections/{collection}")
    def get_collection(collection: str) -> dict[str, Any]:
        return service.get_collection(collection).model_dump()

    @app.get("/collections/{collection}/schema")
    def get_schema(collection: str) -> dict[str, Any]:
        return service.get_schema(collection)

    @app.get("/collections/{collection}/items")
    def list_items(
        collection: str,
        request: Request,
        limit: int = QueryParam(50, ge=1, le=1000),
        offset: int = QueryParam(0, ge=0),
        sort: str | None = None,
        order: str = QueryParam("asc", pattern="^(asc|desc)$"),
        q: str | None = None,
    ) -> dict[str, Any]:
        filters = {
            key: value
            for key, value in request.query_params.items()
            if key not in _RESERVED_PARAMS
        }
        query = Query(
            filters=filters, q=q, sort=sort, order=order, limit=limit, offset=offset
        )
        return service.list_items(collection, query).model_dump()

    @app.get("/collections/{collection}/items/{item_id}")
    def get_item(collection: str, item_id: str) -> dict[str, Any]:
        return service.get_item(collection, item_id).model_dump()

    @app.post("/collections/{collection}/items", status_code=201)
    def create_item(collection: str, data: dict[str, Any]) -> dict[str, Any]:
        return service.create_item(collection, data).model_dump()

    @app.patch("/collections/{collection}/items/{item_id}")
    def update_item(
        collection: str, item_id: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        return service.update_item(collection, item_id, patch).model_dump()

    @app.delete("/collections/{collection}/items/{item_id}", status_code=204)
    def delete_item(collection: str, item_id: str) -> Response:
        service.delete_item(collection, item_id)
        return Response(status_code=204)

    # Optionally serve the built collections-ui bundle from the same origin, so a
    # read-write deployment needs no separate host and no CORS. The API routes above
    # are registered first and take precedence; this catch-all only serves the UI's
    # static files (index.html, assets, and its live-mode config.json).
    if ui_dir is not None:
        app.mount("/", StaticFiles(directory=str(ui_dir), html=True), name="ui")

    return app


def _register_error_handlers(app: FastAPI) -> None:
    def not_found(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": str(exc)})

    def bad_request(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    def not_supported(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=405, content={"error": str(exc)})

    def conflict(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=409, content={"error": str(exc)})

    def validation_failed(_: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, SchemaValidationError)
        return JSONResponse(
            status_code=422, content={"error": str(exc), "details": exc.errors}
        )

    app.add_exception_handler(CollectionNotFound, not_found)
    app.add_exception_handler(ItemNotFound, not_found)
    app.add_exception_handler(InvalidIdentifier, bad_request)
    app.add_exception_handler(NotSupported, not_supported)
    app.add_exception_handler(Conflict, conflict)
    app.add_exception_handler(SchemaValidationError, validation_failed)
