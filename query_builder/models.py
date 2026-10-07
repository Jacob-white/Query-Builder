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

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "column": self.column,
            "op": self.op,
            "value": self.value,
        }
        if self.table_prefix is not None:
            d["table_prefix"] = self.table_prefix
        return d


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

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "column": self.column,
            "direction": self.direction,
        }
        if self.table_prefix is not None:
            d["table_prefix"] = self.table_prefix
        return d


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
            raise TypeError(
                "VectorSearchSpec 'vector' must be a list or tuple of numbers."
            )
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
class HybridSearchSpec:
    """Specification for hybrid search combining dense vector KNN and sparse/full-text keyword search."""

    vector: list[float]
    vector_column: str = "embedding"
    query_text: str = ""
    text_columns: list[str] = field(default_factory=list)
    alpha: float = 0.5  # 1.0 = pure vector, 0.0 = pure text, 0.5 = balanced hybrid
    fusion: str = "rrf"  # "rrf" or "linear"
    rrf_k: int = 60
    top_k: int = 10
    metric: str = "cosine"  # cosine, euclidean, l2, dot_product, inner_product
    include_scores: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.vector, (list, tuple)):
            raise TypeError(
                "HybridSearchSpec 'vector' must be a list or tuple of numbers."
            )
        if len(self.vector) == 0:
            raise ValueError("HybridSearchSpec 'vector' cannot be empty.")
        self.vector = [float(v) for v in self.vector]

        if not isinstance(self.query_text, str):
            raise TypeError("HybridSearchSpec 'query_text' must be a string.")

        if not isinstance(self.text_columns, (list, tuple)):
            raise TypeError(
                "HybridSearchSpec 'text_columns' must be a list of column names."
            )
        self.text_columns = list(self.text_columns)

        if not (0.0 <= self.alpha <= 1.0):
            raise ValueError(
                f"HybridSearchSpec 'alpha' must be between 0.0 and 1.0, got {self.alpha}."
            )

        valid_fusions = {"rrf", "linear"}
        if self.fusion.lower() not in valid_fusions:
            raise ValueError(
                f"Invalid HybridSearchSpec 'fusion': '{self.fusion}'. Must be one of {sorted(valid_fusions)}."
            )
        self.fusion = self.fusion.lower()

        if self.rrf_k <= 0:
            raise ValueError("HybridSearchSpec 'rrf_k' must be greater than 0.")

        if self.top_k <= 0:
            raise ValueError("HybridSearchSpec 'top_k' must be greater than 0.")

        valid_metrics = {"cosine", "euclidean", "l2", "dot_product", "inner_product"}
        if self.metric.lower() not in valid_metrics:
            raise ValueError(
                f"Invalid HybridSearchSpec 'metric': '{self.metric}'. Must be one of {sorted(valid_metrics)}."
            )
        self.metric = self.metric.lower()

    def to_dict(self) -> dict[str, Any]:
        return {
            "vector": list(self.vector),
            "vector_column": self.vector_column,
            "query_text": self.query_text,
            "text_columns": list(self.text_columns),
            "alpha": self.alpha,
            "fusion": self.fusion,
            "rrf_k": self.rrf_k,
            "top_k": self.top_k,
            "metric": self.metric,
            "include_scores": self.include_scores,
        }


@dataclass
class WindowFrameSpec:
    """Specification of window function frame bounds (ROWS, RANGE, GROUPS)."""

    frame_type: str = "ROWS"  # ROWS, RANGE, GROUPS
    start: str = "UNBOUNDED PRECEDING"
    end: str | None = None
    exclusion: str | None = None

    def __post_init__(self) -> None:
        self.frame_type = (self.frame_type or "ROWS").upper().strip()
        if self.frame_type not in {"ROWS", "RANGE", "GROUPS"}:
            raise ValueError(
                f"Invalid frame_type: '{self.frame_type}'. Must be ROWS, RANGE, or GROUPS."
            )
        self.start = (self.start or "UNBOUNDED PRECEDING").upper().strip()
        if self.end is not None:
            self.end = self.end.upper().strip()
        if self.exclusion is not None:
            self.exclusion = self.exclusion.upper().strip()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "frame_type": self.frame_type,
            "start": self.start,
        }
        if self.end is not None:
            d["end"] = self.end
        if self.exclusion is not None:
            d["exclusion"] = self.exclusion
        return d


@dataclass
class WindowFunctionSpec:
    """Specification of an advanced window function with partition, order, and framing."""

    function: str
    arguments: list[Any] = field(default_factory=list)
    partition_by: list[str] = field(default_factory=list)
    order_by: list[dict[str, Any] | OrderBySpec] = field(default_factory=list)
    frame: WindowFrameSpec | dict[str, Any] | None = None
    alias: str | None = None

    def __post_init__(self) -> None:
        if not self.function:
            raise ValueError("WindowFunctionSpec 'function' cannot be empty.")
        self.function = self.function.upper().strip()
        if isinstance(self.frame, dict):
            self.frame = WindowFrameSpec(**self.frame)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "function": self.function,
            "arguments": list(self.arguments),
            "partition_by": list(self.partition_by),
            "order_by": [
                o.to_dict()
                if hasattr(o, "to_dict")
                else (o.__dict__ if hasattr(o, "__dict__") else o)
                for o in self.order_by
            ],
        }
        if self.frame is not None:
            d["frame"] = (
                self.frame.to_dict() if hasattr(self.frame, "to_dict") else self.frame
            )
        if self.alias is not None:
            d["alias"] = self.alias
        return d


WindowSpec = WindowFunctionSpec


@dataclass
class RollupSpec:
    """Analytical specification for GROUP BY ROLLUP hierarchical aggregation."""

    columns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"grouping_type": "rollup", "columns": list(self.columns)}


@dataclass
class CubeSpec:
    """Analytical specification for GROUP BY CUBE multi-dimensional aggregation."""

    columns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"grouping_type": "cube", "columns": list(self.columns)}


@dataclass
class GroupingSetsSpec:
    """Analytical specification for explicit GROUP BY GROUPING SETS aggregation."""

    sets: list[list[str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "grouping_type": "grouping_sets",
            "grouping_sets": [list(s) for s in self.sets],
        }


@dataclass
class PivotSpec:
    """Analytical specification for table pivoting / cross-tabulation."""

    aggregate: str
    column: str
    values: list[Any] = field(default_factory=list)
    alias: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "aggregate": self.aggregate,
            "column": self.column,
            "values": list(self.values),
        }
        if self.alias:
            d["alias"] = self.alias
        return d


@dataclass
class CteSpec:
    """Specification of a Common Table Expression (WITH stage) in a DAG pipeline."""

    name: str
    query: QuerySpec | dict[str, Any]
    columns: list[str] = field(default_factory=list)
    recursive: bool = False
    materialized: bool | None = None

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise ValueError("CteSpec 'name' must be a non-empty string identifier.")
        if isinstance(self.query, dict):
            self.query = QuerySpec(**self.query)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "query": self.query.to_dict()
            if hasattr(self.query, "to_dict")
            else self.query,
            "columns": list(self.columns),
            "recursive": self.recursive,
        }
        if self.materialized is not None:
            d["materialized"] = self.materialized
        return d


@dataclass
class CaseWhenBranch:
    """A single conditional branch (WHEN <condition> THEN <value | column>) in a CASE expression."""

    condition: dict[str, Any] | FilterSpec
    then_value: Any = None
    then_column: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.condition, dict):
            c_dict = dict(self.condition)
            if "field" in c_dict and "column" not in c_dict:
                c_dict["column"] = c_dict.pop("field")
            if "operator" in c_dict and "op" not in c_dict:
                c_dict["op"] = c_dict.pop("operator")
            self.condition = FilterSpec(**c_dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "condition": self.condition.to_dict()
            if hasattr(self.condition, "to_dict")
            else self.condition,
        }
        if self.then_value is not None:
            d["then_value"] = self.then_value
        if self.then_column is not None:
            d["then_column"] = self.then_column
        return d


@dataclass
class CaseWhenSpec:
    """Declarative specification for a SQL CASE WHEN conditional projection."""

    branches: list[CaseWhenBranch | dict[str, Any]] = field(default_factory=list)
    else_value: Any = None
    else_column: str | None = None
    alias: str | None = None

    def __post_init__(self) -> None:
        if self.branches:
            self.branches = [
                CaseWhenBranch(**b) if isinstance(b, dict) else b for b in self.branches
            ]

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "branches": [
                b.to_dict()
                if hasattr(b, "to_dict")
                else (b.__dict__ if hasattr(b, "__dict__") else b)
                for b in self.branches
            ],
        }
        if self.else_value is not None:
            d["else_value"] = self.else_value
        if self.else_column is not None:
            d["else_column"] = self.else_column
        if self.alias is not None:
            d["alias"] = self.alias
        return d


@dataclass
class SetOperationSpec:
    """Specification for a SQL set operation (UNION, UNION ALL, INTERSECT, EXCEPT/MINUS)."""

    operation: str = "UNION"  # UNION, UNION ALL, INTERSECT, EXCEPT, MINUS
    query: QuerySpec | dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.operation = (self.operation or "UNION").upper().strip()
        valid_ops = {"UNION", "UNION ALL", "INTERSECT", "EXCEPT", "MINUS"}
        if self.operation not in valid_ops:
            raise ValueError(
                f"Invalid SetOperationSpec operation: '{self.operation}'. Must be one of {sorted(valid_ops)}."
            )
        if isinstance(self.query, dict):
            self.query = QuerySpec(**self.query)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "query": self.query.to_dict()
            if hasattr(self.query, "to_dict")
            else self.query,
        }


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
    hybrid_search: HybridSearchSpec | dict[str, Any] | None = None
    ctes: list[CteSpec | dict[str, Any]] = field(default_factory=list)
    window_functions: list[WindowFunctionSpec | dict[str, Any]] = field(
        default_factory=list
    )
    set_operations: list[SetOperationSpec | dict[str, Any]] = field(
        default_factory=list
    )
    grouping_type: str | None = None  # standard, rollup, cube, grouping_sets
    grouping_sets: list[list[str]] | GroupingSetsSpec = field(default_factory=list)
    rollup: RollupSpec | None = None
    cube: CubeSpec | None = None
    pivot: PivotSpec | dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.vector_search, dict):
            self.vector_search = VectorSearchSpec(**self.vector_search)
        if isinstance(self.hybrid_search, dict):
            self.hybrid_search = HybridSearchSpec(**self.hybrid_search)
        if self.ctes:
            self.ctes = [CteSpec(**c) if isinstance(c, dict) else c for c in self.ctes]
        if self.window_functions:
            self.window_functions = [
                WindowFunctionSpec(**w) if isinstance(w, dict) else w
                for w in self.window_functions
            ]
        if self.set_operations:
            self.set_operations = [
                SetOperationSpec(**s) if isinstance(s, dict) else s
                for s in self.set_operations
            ]
        if self.rollup is not None:
            self.grouping_type = "rollup"
        if self.cube is not None:
            self.grouping_type = "cube"
        if isinstance(self.grouping_sets, GroupingSetsSpec):
            self.grouping_type = "grouping_sets"
            self.grouping_sets = list(self.grouping_sets.sets)
        if isinstance(self.pivot, dict):
            self.pivot = PivotSpec(**self.pivot)
        if self.grouping_type is not None:
            self.grouping_type = self.grouping_type.lower().strip()

    def to_dict(self) -> dict[str, Any]:
        res: dict[str, Any] = {
            "table": self.table,
            "columns": list(self.columns),
            "joins": [
                j.to_dict()
                if hasattr(j, "to_dict")
                else (j.__dict__ if hasattr(j, "__dict__") else j)
                for j in self.joins
            ],
            "filters": [
                f.to_dict()
                if hasattr(f, "to_dict")
                else (f.__dict__ if hasattr(f, "__dict__") else f)
                for f in self.filters
            ],
            "filter_join": self.filter_join,
            "having": [
                h.to_dict()
                if hasattr(h, "to_dict")
                else (h.__dict__ if hasattr(h, "__dict__") else h)
                for h in self.having
            ],
            "order_by": [
                o.to_dict()
                if hasattr(o, "to_dict")
                else (o.__dict__ if hasattr(o, "__dict__") else o)
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
        if self.hybrid_search is not None:
            res["hybrid_search"] = (
                self.hybrid_search.to_dict()
                if hasattr(self.hybrid_search, "to_dict")
                else self.hybrid_search
            )
        if self.ctes:
            res["ctes"] = [
                c.to_dict()
                if hasattr(c, "to_dict")
                else (c.__dict__ if hasattr(c, "__dict__") else c)
                for c in self.ctes
            ]
        if self.window_functions:
            res["window_functions"] = [
                w.to_dict()
                if hasattr(w, "to_dict")
                else (w.__dict__ if hasattr(w, "__dict__") else w)
                for w in self.window_functions
            ]
        if self.set_operations:
            res["set_operations"] = [
                s.to_dict()
                if hasattr(s, "to_dict")
                else (s.__dict__ if hasattr(s, "__dict__") else s)
                for s in self.set_operations
            ]
        if self.grouping_type is not None:
            res["grouping_type"] = self.grouping_type
        if self.grouping_sets:
            res["grouping_sets"] = [list(gs) for gs in self.grouping_sets]
        if self.rollup is not None:
            res["rollup"] = self.rollup.to_dict()
        if self.cube is not None:
            res["cube"] = self.cube.to_dict()
        if self.pivot is not None:
            res["pivot"] = (
                self.pivot.to_dict()
                if hasattr(self.pivot, "to_dict")
                else dict(self.pivot)
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
