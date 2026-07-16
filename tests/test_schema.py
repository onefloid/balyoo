"""JSON Schema validator adapter."""

from __future__ import annotations

import pytest
from collections_core.errors import SchemaValidationError
from collections_schema.validator import JsonSchemaValidator


def test_valid_item_passes(book_schema):
    JsonSchemaValidator().validate(book_schema, {"title": "OK", "year": 2020})


def test_missing_required_field_reports_error(book_schema):
    with pytest.raises(SchemaValidationError) as excinfo:
        JsonSchemaValidator().validate(book_schema, {"author": "nobody"})
    assert excinfo.value.errors  # non-empty list of messages


def test_wrong_type_reports_path(book_schema):
    with pytest.raises(SchemaValidationError) as excinfo:
        JsonSchemaValidator().validate(book_schema, {"title": "OK", "year": "soon"})
    assert any("year" in message for message in excinfo.value.errors)
