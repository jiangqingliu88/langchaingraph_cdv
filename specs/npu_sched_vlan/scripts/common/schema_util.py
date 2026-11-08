"""Tiny JSON Schema validator (subset).

Supports: type (object/array/string/integer/number/boolean), required,
properties, additionalProperties:false, enum, pattern, items, minItems,
minimum. Enough for the demo schemas without third-party packages.
"""
from __future__ import annotations

import re


def validate(instance, schema, path="$"):
    errors = []
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(instance, dict):
            return [f"{path}: expected object"]
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required field '{key}'")
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in props:
                    errors.append(f"{path}: unexpected field '{key}'")
        for key, value in instance.items():
            if key in props:
                errors.extend(validate(value, props[key], f"{path}.{key}"))
    elif expected == "array":
        if not isinstance(instance, list):
            return [f"{path}: expected array"]
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: expected at least {schema['minItems']} items")
        item_schema = schema.get("items")
        if item_schema:
            for idx, item in enumerate(instance):
                errors.extend(validate(item, item_schema, f"{path}[{idx}]"))
    elif expected == "string":
        if not isinstance(instance, str):
            errors.append(f"{path}: expected string")
        elif "enum" in schema and instance not in schema["enum"]:
            errors.append(f"{path}: {instance!r} not in {schema['enum']}")
        elif "pattern" in schema and not re.match(schema["pattern"], instance):
            errors.append(f"{path}: {instance!r} does not match {schema['pattern']}")
    elif expected == "integer":
        if not isinstance(instance, int) or isinstance(instance, bool):
            errors.append(f"{path}: expected integer")
        elif "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: must be >= {schema['minimum']}")
    elif expected == "number":
        if not isinstance(instance, (int, float)) or isinstance(instance, bool):
            errors.append(f"{path}: expected number")
    elif expected == "boolean":
        if not isinstance(instance, bool):
            errors.append(f"{path}: expected boolean")
    return errors
