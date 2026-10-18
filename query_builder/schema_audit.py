"""An audit of what a schema tells a query builder, or an AI helper, about the data.

Anything that joins only on *declared* links cannot follow an ``..._id`` column that has none (guessing a join from similar
names is how wrong joins are written), and a table or column with no description is a guess about meaning. :func:`audit_schema`
lists those gaps. It reads only what a schema already holds (table, column and link names, and descriptions), never row
data, so it is safe to run anywhere the schema is.

Pure: nothing is read from or written to a database.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

#: Id columns that are trace or correlation keys rather than links to a table.
DEFAULT_NOT_LINK_NAMES = frozenset(
    {"correlation_id", "request_id", "session_id", "trace_id"}
)


@dataclass
class SchemaAudit:
    """The gaps :func:`audit_schema` found."""

    #: ``(table, column, target_table)``: an id column named after a table that exists, with no declared link to it.
    missing_links: list[tuple[str, str, str]] = field(default_factory=list)
    #: ``(table, column)``: an id column that names no table, so a person must say where it points.
    unexplained_ids: list[tuple[str, str]] = field(default_factory=list)
    undescribed_tables: list[str] = field(default_factory=list)
    #: Per table, how many columns have no description (a table with none left out).
    undescribed_columns: dict[str, int] = field(default_factory=dict)
    #: How many tables and columns were audited (tables skipped by ``ignore_prefixes`` are not counted).
    tables: int = 0
    columns: int = 0

    @property
    def clean(self) -> bool:
        """True when the audit found nothing at all."""
        return not (
            self.missing_links
            or self.unexplained_ids
            or self.undescribed_tables
            or self.undescribed_columns
        )

    def to_dict(self) -> dict[str, Any]:
        """The report as plain data, for JSON."""
        return {
            "missing_links": [
                {"table": t, "column": c, "target": target}
                for t, c, target in self.missing_links
            ],
            "unexplained_ids": [
                {"table": t, "column": c} for t, c in self.unexplained_ids
            ],
            "undescribed_tables": list(self.undescribed_tables),
            "undescribed_columns": dict(self.undescribed_columns),
            "tables": self.tables,
            "columns": self.columns,
            "clean": self.clean,
        }


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _column_names(meta: Any) -> list[tuple[str, str]]:
    """``[(column name, description)]`` from the shapes a table's columns come in."""
    columns = (
        meta.get("columns", [])
        if isinstance(meta, Mapping)
        else getattr(meta, "columns", [])
    )
    out: list[tuple[str, str]] = []
    if isinstance(columns, Mapping):
        return [(str(name), "") for name in columns]
    if isinstance(columns, list):
        for column in columns:
            if isinstance(column, Mapping) and isinstance(column.get("name"), str):
                described = _text(column.get("description")) or _text(
                    column.get("comment")
                )
                out.append((column["name"], described))
            elif isinstance(column, str):
                out.append((column, ""))
            elif hasattr(column, "name") and isinstance(column.name, str):
                described = _text(getattr(column, "description", None)) or _text(
                    getattr(column, "comment", None)
                )
                out.append((column.name, described))
    return out


def _declared_links(
    schema_tables: Mapping[str, Any], schema: Any
) -> set[tuple[str, str]]:
    """Every ``(table, column)`` that holds a declared link: a per-table foreign key, a top-level one, or a relationship."""
    links: set[tuple[str, str]] = set()
    for name, meta in schema_tables.items():
        fks = (
            meta.get("foreign_keys", [])
            if isinstance(meta, Mapping)
            else getattr(meta, "foreign_keys", [])
        )
        for fk in fks or []:
            if isinstance(fk, Mapping) and isinstance(fk.get("column"), str):
                links.add((name, fk["column"]))
            elif hasattr(fk, "column") and isinstance(fk.column, str):
                links.add((name, fk.column))
    top: Iterable[Any] = getattr(schema, "foreign_keys", None) or (
        schema.get("foreign_keys", []) if isinstance(schema, Mapping) else []
    )
    for fk in top or []:
        if isinstance(fk, Mapping):
            links.add((str(fk.get("table", "")), str(fk.get("column", ""))))
        elif hasattr(fk, "table") and hasattr(fk, "column"):
            links.add((str(fk.table), str(fk.column)))
    relationships: Iterable[Any] = getattr(schema, "relationships", None) or (
        schema.get("relationships", []) if isinstance(schema, Mapping) else []
    )
    for rel in relationships or []:
        if isinstance(rel, Mapping):
            links.add(
                (str(rel.get("source_table", "")), str(rel.get("source_column", "")))
            )
        elif hasattr(rel, "source_table") and hasattr(rel, "source_column"):
            links.add((str(rel.source_table), str(rel.source_column)))
    return links


def _target(column: str, tables: Mapping[str, Any]) -> str:
    """The table an id column is named after, singular or plural.

    ``customer_id`` finds ``customer`` or ``customers``; ``parent_customer_id`` finds the longest tail of the name that is
    a table (``parent_customer``, then ``customer``).
    """
    parts = column[: -len("_id")].split("_")
    for start in range(len(parts)):
        stem = "_".join(parts[start:])
        candidates = [stem, stem + "s", stem + "es"]
        if stem.endswith("y"):
            candidates.append(stem[:-1] + "ies")
        for candidate in candidates:
            if candidate in tables:
                return candidate
    return ""


def audit_schema(
    schema: Any,
    *,
    known_not_links: Iterable[tuple[str, str]] = (),
    ignore_prefixes: Iterable[str] = (),
    not_link_prefixes: Iterable[str] = (),
    not_link_names: Iterable[str] = DEFAULT_NOT_LINK_NAMES,
) -> SchemaAudit:
    """Audit ``schema`` (a ``SchemaSnapshot`` or ``{"tables": {...}}``) for gaps in links and descriptions.

    A table is read as ``{"columns": [...], "foreign_keys": [...], "description": ...}``, or with ``comment`` for the
    description; links may be per table, top-level ``foreign_keys`` or ``relationships``, as in a ``SchemaSnapshot``.

    ``known_not_links`` is a set of ``(table, column)`` pairs that look like a link but are not one. ``ignore_prefixes``
    skips whole tables by name prefix (a host's own extension tables, say). ``not_link_prefixes`` and ``not_link_names``
    are id columns that are not expected to link (identifiers from another system, trace keys). A schema of an
    unexpected shape gives an empty report.
    """
    tables_raw: Any = getattr(schema, "tables", None)
    if tables_raw is None and isinstance(schema, Mapping):
        tables_raw = schema.get("tables")
        if tables_raw is None and any(
            isinstance(v, Mapping) or hasattr(v, "columns") for v in schema.values()
        ):
            tables_raw = schema
    if not isinstance(tables_raw, Mapping):
        return SchemaAudit()
    tables = {
        name: meta
        for name, meta in tables_raw.items()
        if isinstance(name, str)
        and (isinstance(meta, Mapping) or hasattr(meta, "columns"))
    }
    declared = _declared_links(tables, schema)
    skip_tables = tuple(ignore_prefixes)
    skip_columns = tuple(not_link_prefixes)
    skip_names = set(not_link_names)
    skip_pairs = set(known_not_links)
    report = SchemaAudit()
    for name in sorted(tables):
        if name.startswith(skip_tables) and skip_tables:
            continue
        meta = tables[name]
        columns = _column_names(meta)
        report.tables += 1
        report.columns += len(columns)
        for column, _ in columns:
            if (
                column.endswith("_id")
                and column != "id"
                and (name, column) not in declared
                and not (skip_columns and column.startswith(skip_columns))
                and column not in skip_names
                and (name, column) not in skip_pairs
            ):
                target = _target(column, tables)
                if target and target != name:
                    report.missing_links.append((name, column, target))
                else:
                    report.unexplained_ids.append((name, column))
        table_desc = (
            (_text(meta.get("description")) or _text(meta.get("comment")))
            if isinstance(meta, Mapping)
            else (
                _text(getattr(meta, "description", None))
                or _text(getattr(meta, "comment", None))
            )
        )
        if not table_desc:
            report.undescribed_tables.append(name)
        missing = sum(1 for _, described in columns if not described)
        if missing:
            report.undescribed_columns[name] = missing
    return report


__all__ = ["DEFAULT_NOT_LINK_NAMES", "SchemaAudit", "audit_schema"]
