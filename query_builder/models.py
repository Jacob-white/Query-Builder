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
