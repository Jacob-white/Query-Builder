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
class VectorSearchSpec:
    """Specification for vector similarity / nearest neighbor search."""

    vector: list[float]
    column: str = "embedding"
    top_k: int = 10
    metric: str = "cosine"  # cosine, euclidean, l2, dot_product, inner_product
    include_distances: bool = True
    min_score: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.vector, (list, tuple)):
            raise TypeError("VectorSearchSpec 'vector' must be a list or tuple of numbers.")
        if len(self.vector) == 0:
            raise ValueError("VectorSearchSpec 'vector' cannot be empty.")
        self.vector = [float(v) for v in self.vector]
        if self.top_k <= 0:
            raise ValueError("VectorSearchSpec 'top_k' must be greater than 0.")
        valid_metrics = {"cosine", "euclidean", "l2", "dot_product", "inner_product"}
        if self.metric.lower() not in valid_metrics:
            raise ValueError(
                f"Invalid VectorSearchSpec 'metric': '{self.metric}'. Must be one of {sorted(valid_metrics)}."
            )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "vector": list(self.vector),
            "column": self.column,
            "top_k": self.top_k,
            "metric": self.metric,
            "include_distances": self.include_distances,
        }
        if self.min_score is not None:
            result["min_score"] = self.min_score
        return result


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
    vector_search: VectorSearchSpec | dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.vector_search, dict):
            self.vector_search = VectorSearchSpec(**self.vector_search)

    def to_dict(self) -> dict[str, Any]:
        res: dict[str, Any] = {
            "table": self.table,
            "columns": list(self.columns),
            "joins": [
                j.to_dict() if hasattr(j, "to_dict") else (j.__dict__ if hasattr(j, "__dict__") else j)
                for j in self.joins
            ],
            "filters": [
                f.to_dict() if hasattr(f, "to_dict") else (f.__dict__ if hasattr(f, "__dict__") else f)
                for f in self.filters
            ],
            "filter_join": self.filter_join,
            "having": [
                h.to_dict() if hasattr(h, "to_dict") else (h.__dict__ if hasattr(h, "__dict__") else h)
                for h in self.having
            ],
            "order_by": [
                o.to_dict() if hasattr(o, "to_dict") else (o.__dict__ if hasattr(o, "__dict__") else o)
                for o in self.order_by
            ],
            "limit": self.limit,
            "offset": self.offset,
            "distinct": self.distinct,
        }
        if self.tenant_id is not None:
            res["tenant_id"] = self.tenant_id
        if self.vector_search is not None:
            res["vector_search"] = (
                self.vector_search.to_dict()
                if hasattr(self.vector_search, "to_dict")
                else self.vector_search
            )
        return res


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
