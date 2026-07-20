"""A :class:`~collections_core.interfaces.SchemaValidator` backed by ``jsonschema``."""

from __future__ import annotations

from typing import Any

from collections_core.errors import SchemaValidationError
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError


class JsonSchemaValidator:
    """Validates item data against a JSON Schema (draft 2020-12)."""

    def validate(self, schema: dict[str, Any], data: dict[str, Any]) -> None:
        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
        if errors:
            raise SchemaValidationError([self._format(e) for e in errors])

    def check_schema(self, schema: dict[str, Any]) -> None:
        """Validate that ``schema`` is itself a well-formed JSON Schema.

        Used before a collection's schema is persisted, so a malformed schema is
        rejected up front rather than surfacing later as opaque validation errors.
        The custom ``x-`` extension keys (``x-collection``, ``x-card``) are ignored
        here, as draft 2020-12 permits unknown keywords.
        """
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as error:
            path = ".".join(str(part) for part in error.absolute_path)
            message = f"{path}: {error.message}" if path else error.message
            raise SchemaValidationError([message]) from error

    @staticmethod
    def _format(error: JsonSchemaValidationError) -> str:
        path = ".".join(str(part) for part in error.absolute_path)
        return f"{path}: {error.message}" if path else error.message
