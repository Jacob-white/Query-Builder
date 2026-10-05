"""
Adapter Utilities and Type Helpers.
===================================
Provides shared conversion, normalization, and snapshot synthesis utilities
for ORM and schema adapters.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from query_builder.models import SchemaSnapshot, TableSchema

PRIMITIVE_TYPE_MAP: dict[str, str] = {
    "int": "integer",
    "integer": "integer",
    "int2": "integer",
    "int4": "integer",
    "int8": "bigint",
    "bigint": "bigint",
    "smallint": "integer",
    "tinyint": "integer",
    "serial": "integer",
    "bigserial": "bigint",
    "smallserial": "integer",
    "string": "text",
    "str": "text",
    "text": "text",
    "varchar": "text",
    "char": "text",
    "character": "text",
    "nvarchar": "text",
    "bool": "boolean",
    "boolean": "boolean",
    "float": "float",
    "float4": "float",
    "float8": "float",
    "double": "float",
    "double precision": "float",
    "real": "float",
    "decimal": "decimal",
    "numeric": "decimal",
    "money": "decimal",
    "date": "date",
    "datetime": "timestamp",
    "timestamp": "timestamp",
    "timestamptz": "timestamp",
    "time": "time",
    "timetz": "time",
    "json": "json",
    "jsonb": "json",
    "uuid": "uuid",
    "bytes": "bytes",
    "binary": "bytes",
    "varbinary": "bytes",
    "bytea": "bytes",
    "blob": "bytes",
}


def normalize_type_name(raw_type: str) -> str:
    """Normalizes an arbitrary ORM or database column type name to a canonical string."""
    cleaned = raw_type.strip().lower()
    # Strip precision/length e.g. varchar(255), decimal(10, 2)
    if "(" in cleaned:
        cleaned = cleaned.split("(", 1)[0].strip()
    return PRIMITIVE_TYPE_MAP.get(cleaned, cleaned or "text")


def read_source(source: Any) -> str:
    """
    Reads schema text from a file path if the source points to an existing file,
    otherwise returns the string content directly.
    """
    if isinstance(source, (str, Path, os.PathLike)):
        try:
            path = Path(source)
            if path.is_file():
                return path.read_text(encoding="utf-8")
        except (OSError, ValueError):
            pass
    return str(source)


def to_schema_snapshot(
    tables: dict[str, TableSchema] | list[TableSchema] | TableSchema,
) -> SchemaSnapshot:
    """
    Synthesizes a full SchemaSnapshot dataclass from TableSchema instances,
    deduplicating foreign keys and generating bidirectional relationships.
    """
    from query_builder.models import SchemaSnapshot, TableSchema

    if isinstance(tables, TableSchema):
        table_list = [tables]
    elif isinstance(tables, dict):
        table_list = list(tables.values())
    elif isinstance(tables, (list, tuple)):
        table_list = list(tables)
    else:
        raise TypeError(
            f"Expected TableSchema, dict, or list, got {type(tables).__name__}"
        )

    snapshot_tables: dict[str, dict[str, Any]] = {}
    all_fks: list[dict[str, str]] = []
    all_rels: list[dict[str, str]] = []
    seen_fks: set[tuple[str, str, str, str]] = set()

    for table in table_list:
        snapshot_tables[table.name] = {
            "name": table.name,
            "schema": table.schema,
            "columns": [col.to_dict() for col in table.columns],
            "primary_keys": list(table.primary_keys),
            "foreign_keys": [fk.to_dict() for fk in table.foreign_keys],
            "enums": dict(table.enums),
            "comment": table.comment,
        }
        for fk in table.foreign_keys:
            key = (fk.table, fk.column, fk.foreign_table, fk.foreign_column)
            if key not in seen_fks and all(key):
                seen_fks.add(key)
                all_fks.append(fk.to_dict())
                all_rels.append(
                    {
                        "source_table": fk.table,
                        "source_column": fk.column,
                        "target_table": fk.foreign_table,
                        "target_column": fk.foreign_column,
                    }
                )

    return SchemaSnapshot(
        tables=snapshot_tables,
        foreign_keys=all_fks,
        relationships=all_rels,
        categories={},
    )
