"""
JSON Schema and OpenAPI Adapter for Query Builder.
==================================================
Parses JSON Schema (Draft 4/7/2020-12) and OpenAPI 3.x specifications
into Query-Builder TableSchema models.
"""

from __future__ import annotations

import json
from typing import Any

from query_builder.adapters.utils import normalize_type_name, read_source
from query_builder.models import ColumnSchema, ForeignKey, SchemaDict, TableSchema

JSON_SCHEMA_TYPE_MAP: dict[str, str] = {
    "string": "text",
    "integer": "integer",
    "number": "decimal",
    "boolean": "boolean",
    "object": "json",
    "array": "json",
    "null": "text",
}


def _parse_table_schema(
    table_name: str,
    schema_def: dict[str, Any],
) -> TableSchema:
    """Parses an individual JSON Schema object into a TableSchema."""
    properties = schema_def.get("properties", {})
    required_cols = set(schema_def.get("required", []))

    # Primary keys
    primary_keys: list[str] = []
    if "x-primary-keys" in schema_def and isinstance(
        schema_def["x-primary-keys"], list
    ):
        primary_keys.extend(schema_def["x-primary-keys"])
    elif "primary_keys" in schema_def and isinstance(schema_def["primary_keys"], list):
        primary_keys.extend(schema_def["primary_keys"])

    columns: list[ColumnSchema] = []
    foreign_keys: list[ForeignKey] = []

    for prop_name, prop_def in properties.items():
        if not isinstance(prop_def, dict):
            prop_def = {"type": str(prop_def)}

        # Handle $ref
        ref_fk: ForeignKey | None = None
        if "$ref" in prop_def:
            ref_path = prop_def["$ref"]
            ref_target = ref_path.rstrip("/").split("/")[-1]
            ref_fk = ForeignKey(
                table=table_name,
                column=prop_name,
                foreign_table=ref_target,
                foreign_column="id",
            )
            foreign_keys.append(ref_fk)

        # Type handling (support union types e.g. ["string", "null"])
        raw_type = prop_def.get("type", "string")
        has_null_type = False
        if isinstance(raw_type, list):
            has_null_type = "null" in raw_type
            non_null_types = [t for t in raw_type if t != "null"]
            raw_type = non_null_types[0] if non_null_types else "string"

        fmt = prop_def.get("format", "").lower()
        if fmt in ("date-time", "datetime"):
            data_type = "timestamp"
        elif fmt == "date":
            data_type = "date"
        elif fmt == "uuid":
            data_type = "uuid"
        elif fmt in ("int32", "int64"):
            data_type = "integer" if fmt == "int32" else "bigint"
        elif fmt in ("float", "double"):
            data_type = "float"
        else:
            data_type = JSON_SCHEMA_TYPE_MAP.get(
                str(raw_type).lower(), normalize_type_name(str(raw_type))
            )

        # Nullability:
        # In JSON Schema, fields not in `required` are optional/nullable.
        # If in required, is_nullable is False unless explicitly nullable: true or has "null" type.
        is_required = prop_name in required_cols
        is_nullable = (
            not is_required or has_null_type or bool(prop_def.get("nullable", False))
        )

        # Primary key check
        is_pk = (
            prop_name in primary_keys
            or bool(prop_def.get("x-primary-key", False))
            or bool(prop_def.get("primaryKey", False))
            or bool(prop_def.get("is_primary", False))
        )
        if is_pk and prop_name not in primary_keys:
            primary_keys.append(prop_name)

        # Enums
        col_enums: list[str] | None = None
        if "enum" in prop_def and isinstance(prop_def["enum"], list):
            col_enums = [str(e) for e in prop_def["enum"]]
            data_type = "string"

        # Explicit Foreign Key (x-foreign-key or x-references)
        fk: ForeignKey | None = ref_fk
        fk_raw = (
            prop_def.get("x-foreign-key")
            or prop_def.get("x-references")
            or prop_def.get("foreign_key")
        )
        if fk_raw:
            if isinstance(fk_raw, str) and "." in fk_raw:
                f_tbl, f_col = fk_raw.split(".", 1)
                fk = ForeignKey(
                    table=table_name,
                    column=prop_name,
                    foreign_table=f_tbl,
                    foreign_column=f_col,
                )
                foreign_keys.append(fk)
            elif isinstance(fk_raw, dict):
                fk = ForeignKey(
                    table=table_name,
                    column=prop_name,
                    foreign_table=fk_raw.get("table", ""),
                    foreign_column=fk_raw.get("column", "id"),
                )
                foreign_keys.append(fk)

        columns.append(
            ColumnSchema(
                name=prop_name,
                data_type=data_type,
                is_nullable=is_nullable,
                is_primary=is_pk,
                default=prop_def.get("default"),
                comment=prop_def.get("description"),
                enums=col_enums,
                foreign_key=fk,
            )
        )

    # Fallback to single 'id' primary key if none specified and 'id' exists
    if not primary_keys:
        for c in columns:
            if c.name == "id":
                c.is_primary = True
                primary_keys.append("id")
                break

    table_enums: dict[str, list[str]] = {}
    for c in columns:
        if c.enums:
            table_enums[c.name] = c.enums

    return TableSchema(
        name=table_name,
        columns=columns,
        primary_keys=primary_keys,
        foreign_keys=foreign_keys,
        enums=table_enums,
        comment=schema_def.get("description"),
    )


def from_json_schema(source: Any) -> SchemaDict:
    """
    Parses a JSON Schema or OpenAPI 3.x specification into TableSchema models.

    Args:
        source: JSON Schema / OpenAPI dictionary, JSON string, or file path.

    Returns:
        SchemaDict mapping table names to TableSchema instances.
    """
    import os
    from pathlib import Path

    if isinstance(source, (str, Path, os.PathLike)):
        text = read_source(source)
        try:
            raw_data = json.loads(text)
        except json.JSONDecodeError:
            raw_data = {"type": "object", "properties": {}}
    else:
        raw_data = source

    tables = SchemaDict()

    # 1. OpenAPI 3.x components/schemas
    if (
        isinstance(raw_data, dict)
        and "components" in raw_data
        and isinstance(raw_data["components"], dict)
        and "schemas" in raw_data["components"]
    ):
        schemas = raw_data["components"]["schemas"]
        for schema_name, schema_def in schemas.items():
            if isinstance(schema_def, dict):
                tbl = _parse_table_schema(schema_name, schema_def)
                tables[tbl.name] = tbl
        return tables

    # 2. JSON Schema definitions or $defs
    defs = None
    if isinstance(raw_data, dict):
        defs = raw_data.get("definitions") or raw_data.get("$defs")

    if isinstance(defs, dict):
        for schema_name, schema_def in defs.items():
            if isinstance(schema_def, dict):
                tbl = _parse_table_schema(schema_name, schema_def)
                tables[tbl.name] = tbl
        return tables

    # 3. Direct dictionary of tables: { "users": { ... }, "orders": { ... } }
    if (
        isinstance(raw_data, dict)
        and "properties" not in raw_data
        and "type" not in raw_data
    ):
        for tbl_name, tbl_def in raw_data.items():
            if isinstance(tbl_def, dict):
                tbl = _parse_table_schema(tbl_name, tbl_def)
                tables[tbl.name] = tbl
        return tables

    # 4. Single schema object
    if isinstance(raw_data, dict):
        name = raw_data.get("title") or raw_data.get("name") or "main"
        tbl = _parse_table_schema(name, raw_data)
        tables[tbl.name] = tbl

    return tables
