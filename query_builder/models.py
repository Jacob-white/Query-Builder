"""
Data Models and Type Specifications for Query Builder Engine.
============================================================
Defines standard dataclass specifications for declarative queries, filters,
joins, ordering, schema metadata, and validation results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ColumnMeta:
    """Metadata describing a table column."""

    name: str
    data_type: str = "text"
    is_nullable: bool = True
    is_primary: bool = False
    comment: str | None = None


@dataclass
class ForeignKeyMeta:
    """Metadata describing a database foreign key constraint."""

    table: str
    column: str
    foreign_table: str
    foreign_column: str


@dataclass
class TableMeta:
    """Metadata describing a database table."""

    name: str
    schema: str = "public"
    columns: list[ColumnMeta] = field(default_factory=list)
    comment: str | None = None
    has_user_id: bool = False
    user_col: str = "user_id"


@dataclass
class ForeignKey:
    """Specification of a foreign key relationship between columns."""

    table: str
    column: str
    foreign_table: str
    foreign_column: str
    constraint_name: str | None = None

    def to_foreign_key_meta(self) -> ForeignKeyMeta:
        return ForeignKeyMeta(
            table=self.table,
            column=self.column,
            foreign_table=self.foreign_table,
            foreign_column=self.foreign_column,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "table": self.table,
            "column": self.column,
            "foreign_table": self.foreign_table,
            "foreign_column": self.foreign_column,
        }
        if self.constraint_name is not None:
            result["constraint_name"] = self.constraint_name
        return result


@dataclass
class ColumnSchema:
    """Schema specification for a table column."""

    name: str
    data_type: str = "text"
    is_nullable: bool = True
    is_primary: bool = False
    default: Any = None
    comment: str | None = None
    enums: list[str] | None = None
    foreign_key: ForeignKey | None = None

    def to_column_meta(self) -> ColumnMeta:
        return ColumnMeta(
            name=self.name,
            data_type=self.data_type,
            is_nullable=self.is_nullable,
            is_primary=self.is_primary,
            comment=self.comment,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "data_type": self.data_type,
            "is_nullable": self.is_nullable,
            "is_primary": self.is_primary,
            "default": self.default,
            "comment": self.comment,
            "enums": self.enums,
        }
        if self.foreign_key is not None:
            result["foreign_key"] = self.foreign_key.to_dict()
        return result


@dataclass
class TableSchema:
    """Schema specification for a database table."""

    name: str
    columns: list[ColumnSchema] = field(default_factory=list)
    schema: str = "public"
    comment: str | None = None
    primary_keys: list[str] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    enums: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.primary_keys:
            self.primary_keys = [c.name for c in self.columns if c.is_primary]
        else:
            for c in self.columns:
                if c.name in self.primary_keys:
                    c.is_primary = True
        if not self.foreign_keys:
            self.foreign_keys = [
                c.foreign_key for c in self.columns if c.foreign_key is not None
            ]
        else:
            col_map = {c.name: c for c in self.columns}
            for fk in self.foreign_keys:
                if fk.column in col_map and col_map[fk.column].foreign_key is None:
                    col_map[fk.column].foreign_key = fk
        for c in self.columns:
            if c.enums and c.name not in self.enums:
                self.enums[c.name] = list(c.enums)

    def to_table_meta(self) -> TableMeta:
        return TableMeta(
            name=self.name,
            schema=self.schema,
            columns=[c.to_column_meta() for c in self.columns],
            comment=self.comment,
            has_user_id=any(c.name == "user_id" for c in self.columns),
            user_col="user_id",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "schema": self.schema,
            "columns": [c.to_dict() for c in self.columns],
            "primary_keys": list(self.primary_keys),
            "foreign_keys": [fk.to_dict() for fk in self.foreign_keys],
            "enums": dict(self.enums),
            "comment": self.comment,
        }

    def get_column(self, name: str) -> ColumnSchema | None:
        """Find a column by case-insensitive name."""
        target = name.lower()
        for col in self.columns:
            if col.name.lower() == target:
                return col
        return None

    def to_schema_snapshot(self) -> SchemaSnapshot:
        from query_builder.adapters.utils import to_schema_snapshot

        return to_schema_snapshot({self.name: self})


class SchemaDict(dict[str, TableSchema]):
    """Dictionary mapping table names to TableSchema with conversion helper methods."""

    def to_schema_snapshot(self) -> SchemaSnapshot:
        from query_builder.adapters.utils import to_schema_snapshot

        return to_schema_snapshot(self)

    def to_snapshot(self) -> SchemaSnapshot:
        return self.to_schema_snapshot()

    def to_dict(self) -> dict[str, Any]:
        return {name: table.to_dict() for name, table in self.items()}


@dataclass
class SchemaSnapshot:
    """Complete snapshot of database schema available to Query Builder."""

    tables: dict[str, dict[str, Any]] = field(default_factory=dict)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    foreign_keys: list[dict[str, Any]] = field(default_factory=list)
    categories: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class JoinCondition:
    """Explicit join condition between two column references."""

    left: str
    right: str


@dataclass
class JoinSpec:
    """Specification of a table join."""

    table: str
    type: str = "LEFT"  # INNER, LEFT, RIGHT, FULL
    on: list[dict[str, str] | JoinCondition] = field(default_factory=list)
    left_table: str | None = None
    left_col: str | None = None
    right_col: str | None = None


@dataclass
class FilterSpec:
    """Specification of a filter condition on a column."""

    column: str
    op: str = "eq"  # eq, neq, gt, gte, lt, lte, contains, starts_with, ends_with, in, between, is_null, is_not_null
    value: Any = None
    table_prefix: str | None = None


@dataclass
class HavingSpec:
    """Specification of a HAVING aggregate filter."""

    column: str
    agg: str = "count"  # count, sum, avg, min, max
    op: str = "gt"
    value: Any = None


@dataclass
class OrderBySpec:
    """Specification of column sort direction."""

    column: str
    direction: str = "asc"  # asc, desc
    table_prefix: str | None = None


@dataclass
class QuerySpec:
    """Declarative specification for building and compiling a SQL query."""

    table: str
    columns: list[str | dict[str, Any]] = field(default_factory=list)
    joins: list[dict[str, Any] | JoinSpec] = field(default_factory=list)
    filters: list[dict[str, Any] | FilterSpec] = field(default_factory=list)
    filter_join: str = "AND"  # AND, OR
    having: list[dict[str, Any] | HavingSpec] = field(default_factory=list)
    order_by: list[dict[str, Any] | OrderBySpec] = field(default_factory=list)
    limit: int = 50
    offset: int = 0
    distinct: bool = False
    tenant_id: Any = None


@dataclass
class ValidationResult:
    """Result of an AST SQL validation check."""

    valid: bool
    ast_validated: bool
    statement_type: str
    is_read_only: bool
    violations: list[str] = field(default_factory=list)
    injection_risk: str = "NONE"
    message: str = ""


@dataclass
class QueryResult:
    """Standardized result of query execution."""

    sql: str
    params: list[Any]
    columns: list[str]
    rows: list[dict[str, Any]]
    count: int
    limit: int
    offset: int
    latency_ms: float | None = None
