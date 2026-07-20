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


def test_check_schema_accepts_a_well_formed_schema(book_schema):
    # Including the custom x- presentation keys, which draft 2020-12 tolerates.
    JsonSchemaValidator().check_schema(
        {**book_schema, "x-collection": {"icon": "📚"}}
    )


def test_check_schema_rejects_a_malformed_schema():
    with pytest.raises(SchemaValidationError) as excinfo:
        # ``type`` must be a string or array of strings, not an integer.
        JsonSchemaValidator().check_schema({"type": 123})
    assert excinfo.value.errors


def test_check_schema_allows_a_safe_pattern():
    JsonSchemaValidator().check_schema(
        {
            "type": "object",
            "properties": {"slug": {"type": "string", "pattern": "^[a-z][a-z0-9-]*$"}},
        }
    )


def test_check_schema_rejects_catastrophic_pattern():
    with pytest.raises(SchemaValidationError) as excinfo:
        JsonSchemaValidator().check_schema(
            {"type": "object", "properties": {"x": {"pattern": "(a+)+$"}}}
        )
    assert any("catastrophic" in m for m in excinfo.value.errors)


def test_check_schema_rejects_catastrophic_pattern_when_nested_deep():
    # The scan must reach patterns nested anywhere in the schema tree.
    schema = {
        "type": "object",
        "properties": {
            "items": {"type": "array", "items": {"pattern": "([a-z]+)*!"}},
        },
    }
    with pytest.raises(SchemaValidationError):
        JsonSchemaValidator().check_schema(schema)


def test_check_schema_rejects_catastrophic_pattern_properties_key():
    with pytest.raises(SchemaValidationError):
        JsonSchemaValidator().check_schema(
            {"type": "object", "patternProperties": {"(x*)*": {"type": "string"}}}
        )


def test_check_schema_rejects_invalid_regex():
    # An un-compilable pattern is rejected (by the metaschema's "regex" format
    # check, with our re.compile guard as a defence-in-depth backstop).
    with pytest.raises(SchemaValidationError) as excinfo:
        JsonSchemaValidator().check_schema(
            {"type": "object", "properties": {"x": {"pattern": "("}}}
        )
    assert excinfo.value.errors


def test_check_schema_rejects_overlong_pattern():
    with pytest.raises(SchemaValidationError) as excinfo:
        JsonSchemaValidator().check_schema(
            {"type": "object", "properties": {"x": {"pattern": "a" * 1001}}}
        )
    assert any("too long" in m for m in excinfo.value.errors)
