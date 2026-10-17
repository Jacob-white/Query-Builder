"""Checks on a query spec that the compiler leaves to the database.

The compiler checks identifier shape and SQL safety, but not that a column exists, so a misspelt or invented column
reaches the database and comes back as a driver error. :func:`check_columns` refuses it first, with a message that names
the column and the table, suggests the likeliest real column and lists what exists. That message is also what a caller
needs to send back to a language model for a repair.

Pure: it reads the spec and a schema and does nothing else.
"""

from __future__ import annotations

import difflib
from collections.abc import Mapping
from typing import Any

from query_builder.exceptions import SpecColumnError

#: How many of a table's columns an error lists before it trails off.
MAX_COLUMNS_LISTED = 60

#: A name shorter than this is not suggested as "part of" a real column (too many accidental hits).
_MIN_PARTIAL_LENGTH = 3


def _tables_of(schema: Any) -> dict[str, list[str]]:
    """``{table: [column names]}`` from the shapes a schema comes in; empty when it is none of them."""
    tables: Any = getattr(schema, "tables", None)
    if tables is None and isinstance(schema, Mapping):
        tables = schema.get("tables", schema)
    if not isinstance(tables, Mapping):
        return {}
    out: dict[str, list[str]] = {}
    for name, meta in tables.items():
        if not isinstance(name, str) or not isinstance(meta, Mapping):
            continue
        columns = meta.get("columns", [])
        names: list[str] = []
        if isinstance(columns, Mapping):
            names = [str(c) for c in columns]
        elif isinstance(columns, list):
            for column in columns:
                if isinstance(column, Mapping) and isinstance(column.get("name"), str):
                    names.append(column["name"])
                elif isinstance(column, str):
                    names.append(column)
        out[name] = names
    return out


def _items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _suggestions(name: str, columns: list[str]) -> list[str]:
    """The columns a misspelt ``name`` probably meant: ones that contain it first, then ones that look like it."""
    inside = [
        c
        for c in columns
        if len(name) >= _MIN_PARTIAL_LENGTH and name.lower() in c.lower()
    ]
    close = [
        c
        for c in difflib.get_close_matches(name, columns, n=3, cutoff=0.6)
        if c not in inside
    ]
    return (inside + close)[:3]


def check_columns(spec: Any, schema: Any) -> None:
    """Raise :class:`SpecColumnError` when ``spec`` names a column that does not exist in a table of the query.

    Checked: the selected columns, the filters and the sort. A column is read as ``table.column``; a bare name is a
    column of the base table (or of the ``table`` / ``tablePrefix`` key beside it). ``schema`` may be a
    ``SchemaSnapshot``, ``{"tables": {...}}`` or a bare ``{table: {"columns": [...]}}`` mapping, with columns as
    ``{"name": ...}`` dicts, plain names or a name-to-type mapping.

    Left alone, because they are not a plain column of a listed table: expressions, CASE columns, ``*``, an alias used in
    a sort, a sub-query's columns (the schema does not list them), a filter on a sub-query, and any table the schema does
    not list. A spec or schema of an unexpected shape checks nothing: the compiler reports shape problems.
    """
    if not isinstance(spec, dict):
        return
    tables = _tables_of(schema)
    base = spec.get("table")
    if not isinstance(base, str) or base not in tables:
        return
    sub_queries = {
        c.get("name") for c in _items(spec.get("ctes")) if isinstance(c, dict)
    }
    in_query: dict[str, str] = {base: base}
    for join in _items(spec.get("joins")):
        if isinstance(join, dict) and isinstance(join.get("table"), str):
            in_query[join["table"]] = join["table"]
            if isinstance(join.get("alias"), str):
                in_query[join["alias"]] = join["table"]
    aliases = {
        c["alias"]
        for c in _items(spec.get("columns"))
        if isinstance(c, dict) and isinstance(c.get("alias"), str)
    }

    def check(ref: Any, prefix: Any = None) -> None:
        if not isinstance(ref, str) or not ref or ref == "*":
            return
        if "." in ref:
            owner, _, name = ref.rpartition(".")
        else:
            owner = prefix if isinstance(prefix, str) and prefix else base
            name = ref
        if owner in sub_queries:
            return
        real = in_query.get(owner)
        if real is None:
            if owner in tables:
                present = ", ".join(sorted(set(in_query.values())))
                raise SpecColumnError(
                    f"'{ref}' is a column of {owner}, which is not in this query. The query has: {present}. "
                    f"Join {owner} first.",
                    column=ref,
                    table=owner,
                )
            return
        if real in sub_queries or real not in tables or name in tables[real]:
            return
        columns = tables[real]
        close = _suggestions(name, columns)
        hint = f" Did you mean {', '.join(close)}?" if close else ""
        listed = ", ".join(columns[:MAX_COLUMNS_LISTED]) + (
            "..." if len(columns) > MAX_COLUMNS_LISTED else ""
        )
        raise SpecColumnError(
            f"'{ref}' is not a column of {real}.{hint} The columns of {real} are: {listed}.",
            column=ref,
            table=real,
            suggestions=close,
            available=columns,
        )

    for column in _items(spec.get("columns")):
        if isinstance(column, str):
            check(column)
        elif (
            isinstance(column, dict)
            and not column.get("expression")
            and not column.get("case_when")
        ):
            check(column.get("column") or column.get("name"), column.get("table"))
    for flt in _items(spec.get("filters")):
        if isinstance(flt, dict) and "subquery" not in flt:
            check(
                flt.get("column"),
                flt.get("tablePrefix") or flt.get("table_prefix") or flt.get("table"),
            )
    for item in _items(spec.get("order_by")):
        if isinstance(item, dict) and not (
            item.get("column") in aliases and "." not in str(item.get("column"))
        ):
            check(
                item.get("column"),
                item.get("tablePrefix")
                or item.get("table_prefix")
                or item.get("table"),
            )


__all__ = ["MAX_COLUMNS_LISTED", "SpecColumnError", "check_columns"]
