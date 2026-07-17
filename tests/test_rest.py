"""Generic REST API, including capability enforcement and error mapping."""

from __future__ import annotations

import pytest
from collections_core.service import CollectionsService
from collections_filesystem.provider import FilesystemStorageProvider
from collections_rest.app import create_app
from collections_schema.validator import JsonSchemaValidator
from fastapi.testclient import TestClient


def _client(root, *, read_only=False) -> TestClient:
    service = CollectionsService(
        FilesystemStorageProvider(root), JsonSchemaValidator(), read_only=read_only
    )
    return TestClient(create_app(service))


def test_list_collections(examples_copy):
    client = _client(examples_copy)
    response = client.get("/collections")
    assert response.status_code == 200
    names = {c["name"] for c in response.json()}
    assert names == {"books", "movies"}


def test_get_schema(examples_copy):
    client = _client(examples_copy)
    response = client.get("/collections/books/schema")
    assert response.status_code == 200
    assert response.json()["title"] == "Book"


def test_list_items_with_search(examples_copy):
    client = _client(examples_copy)
    response = client.get("/collections/books/items", params={"q": "dune"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == "dune"


def test_create_then_get_then_delete(examples_copy):
    client = _client(examples_copy)

    created = client.post(
        "/collections/books/items", json={"id": "hobbit", "title": "The Hobbit"}
    )
    assert created.status_code == 201

    fetched = client.get("/collections/books/items/hobbit")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["title"] == "The Hobbit"

    patched = client.patch("/collections/books/items/hobbit", json={"year": 1937})
    assert patched.status_code == 200
    assert patched.json()["data"]["year"] == 1937

    deleted = client.delete("/collections/books/items/hobbit")
    assert deleted.status_code == 204


def test_unknown_collection_returns_404(examples_copy):
    client = _client(examples_copy)
    assert client.get("/collections/nope/items").status_code == 404


def test_unknown_item_returns_404(examples_copy):
    client = _client(examples_copy)
    assert client.get("/collections/books/items/ghost").status_code == 404


def test_invalid_item_returns_422(examples_copy):
    client = _client(examples_copy)
    response = client.post("/collections/books/items", json={"author": "no title"})
    assert response.status_code == 422
    assert "details" in response.json()


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 99999}, {"offset": -1}, {"order": "sideways"}],
)
def test_out_of_range_query_params_return_422(examples_copy, params):
    client = _client(examples_copy)
    response = client.get("/collections/books/items", params=params)
    assert response.status_code == 422


def test_path_traversal_id_in_body_returns_400(examples_copy):
    client = _client(examples_copy)
    response = client.post(
        "/collections/books/items",
        json={"id": "../../../../tmp/evil", "title": "x"},
    )
    assert response.status_code == 400
    # Nothing was written outside the collection.
    assert not (examples_copy.parent.parent / "tmp" / "evil.json").exists()


def test_duplicate_item_returns_409(examples_copy):
    client = _client(examples_copy)
    response = client.post(
        "/collections/books/items", json={"id": "dune", "title": "Dune again"}
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    "method,url,body",
    [
        ("post", "/collections/books/items", {"title": "x"}),
        ("patch", "/collections/books/items/dune", {"year": 2000}),
        ("delete", "/collections/books/items/dune", None),
    ],
)
def test_read_only_blocks_writes_with_405(examples_copy, method, url, body):
    client = _client(examples_copy, read_only=True)
    response = client.request(method, url, json=body)
    assert response.status_code == 405

    # Reads on the very same API still work.
    assert client.get("/collections/books/items/dune").status_code == 200


def test_serves_ui_bundle_alongside_api(examples_copy, tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<!doctype html><title>UI</title>", encoding="utf-8")
    (ui / "config.json").write_text('{"apiBase": "", "static": false}', encoding="utf-8")

    service = CollectionsService(
        FilesystemStorageProvider(examples_copy), JsonSchemaValidator()
    )
    client = TestClient(create_app(service, ui_dir=ui))

    # UI served from the same origin as the API...
    assert client.get("/").text.startswith("<!doctype html>")
    assert client.get("/config.json").json() == {"apiBase": "", "static": False}
    # ...without shadowing the API routes.
    assert client.get("/collections/books/items/dune").status_code == 200
