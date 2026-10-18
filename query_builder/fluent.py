"""
Fluent Query Builder for Python.
================================
Provides a chainable, type-safe API for constructing declarative QuerySpec
definitions, compiling to SQL, and executing against connectors.
"""

from __future__ import annotations

from typing import Any

from query_builder.compiler import QueryCompiler
from query_builder.models import (
    CteSpec,
    FilterSpec,
    HavingSpec,
    JoinSpec,
    OrderBySpec,
    QuerySpec,
    WindowFunctionSpec,
)
from query_builder.spec_check import check_columns


class FluentQuery:
    """Chainable Python query builder."""

    def __init__(self, table: str) -> None:
        self._table = table
        self._columns: list[str | dict[str, Any]] = []
        self._metrics: list[str] = []
        self._joins: list[dict[str, Any]] = []
        self._filters: list[dict[str, Any]] = []
        self._filter_join = "AND"
        self._having: list[dict[str, Any]] = []
        self._order_by: list[dict[str, Any]] = []
        self._limit: int = 50
        self._offset: int = 0
        self._distinct: bool = False
        self._grouping_type: str | None = None
        self._grouping_sets: list[list[str]] = []
        self._ctes: list[CteSpec] = []
        self._window_functions: list[WindowFunctionSpec] = []
        self._tenant_id: Any = None

    def select(self, *columns: str | dict[str, Any] | list[Any]) -> FluentQuery:
        """Adds columns/projections to select."""
        for c in columns:
            if isinstance(c, list):
                self._columns.extend(c)
            else:
                self._columns.append(c)
        return self

    def columns(self, *columns: str | dict[str, Any] | list[Any]) -> FluentQuery:
        """Alias for select()."""
        return self.select(*columns)

    def metrics(self, *metric_names: str | list[str]) -> FluentQuery:
        """Adds semantic metrics to select."""
        for m in metric_names:
            if isinstance(m, list):
                self._metrics.extend(m)
            else:
                self._metrics.append(m)
        return self

    def where(
        self,
        column: str,
        op: str = "eq",
        value: Any = None,
        *,
        table_prefix: str | None = None,
    ) -> FluentQuery:
        """Adds a WHERE filter condition."""
        f: dict[str, Any] = {"column": column, "op": op, "value": value}
        if table_prefix:
            f["table_prefix"] = table_prefix
        self._filters.append(f)
        return self

    def filter(
        self,
        column: str,
        op: str = "eq",
        value: Any = None,
        *,
        table_prefix: str | None = None,
    ) -> FluentQuery:
        """Alias for where()."""
        return self.where(column, op, value, table_prefix=table_prefix)

    def or_where(
        self,
        column: str,
        op: str = "eq",
        value: Any = None,
        *,
        table_prefix: str | None = None,
    ) -> FluentQuery:
        """Switches filter_join to OR and adds a filter condition."""
        self._filter_join = "OR"
        return self.where(column, op, value, table_prefix=table_prefix)

    def join(
        self,
        table: str,
        on_left: str | None = None,
        on_right: str | None = None,
        join_type: str = "INNER JOIN",
        *,
        on: list[dict[str, Any]] | None = None,
    ) -> FluentQuery:
        """Adds a relational table join."""
        j: dict[str, Any] = {"table": table, "type": join_type}
        if on_left and on_right:
            j["left_col"] = on_left
            j["right_col"] = on_right
        if on:
            j["on"] = on
        self._joins.append(j)
        return self

    def left_join(
        self,
        table: str,
        on_left: str | None = None,
        on_right: str | None = None,
        *,
        on: list[dict[str, Any]] | None = None,
    ) -> FluentQuery:
        """Adds a LEFT JOIN."""
        return self.join(table, on_left, on_right, join_type="LEFT JOIN", on=on)

    def right_join(
        self,
        table: str,
        on_left: str | None = None,
        on_right: str | None = None,
        *,
        on: list[dict[str, Any]] | None = None,
    ) -> FluentQuery:
        """Adds a RIGHT JOIN."""
        return self.join(table, on_left, on_right, join_type="RIGHT JOIN", on=on)

    def full_join(
        self,
        table: str,
        on_left: str | None = None,
        on_right: str | None = None,
        *,
        on: list[dict[str, Any]] | None = None,
    ) -> FluentQuery:
        """Adds a FULL JOIN."""
        return self.join(table, on_left, on_right, join_type="FULL JOIN", on=on)

    def having(
        self,
        column: str,
        op: str = "eq",
        value: Any = None,
        *,
        agg: str | None = None,
    ) -> FluentQuery:
        """Adds a HAVING clause filter."""
        h: dict[str, Any] = {"column": column, "op": op, "value": value}
        if agg:
            h["agg"] = agg
        self._having.append(h)
        return self

    def order_by(
        self,
        column: str,
        direction: str = "ASC",
        *,
        table_prefix: str | None = None,
        nulls: str | None = None,
    ) -> FluentQuery:
        """Adds an ORDER BY sorting condition."""
        o: dict[str, Any] = {"column": column, "direction": direction}
        if table_prefix:
            o["table_prefix"] = table_prefix
        if nulls:
            o["nulls"] = nulls
        self._order_by.append(o)
        return self

    def rollup(self) -> FluentQuery:
        """Configures GROUP BY ROLLUP."""
        self._grouping_type = "rollup"
        return self

    def cube(self) -> FluentQuery:
        """Configures GROUP BY CUBE."""
        self._grouping_type = "cube"
        return self

    def grouping_sets(self, *sets: list[str]) -> FluentQuery:
        """Configures GROUP BY GROUPING SETS."""
        self._grouping_type = "grouping_sets"
        self._grouping_sets.extend(sets)
        return self

    def with_cte(
        self,
        name: str,
        cte_query: QuerySpec | dict[str, Any] | FluentQuery,
        *,
        recursive: bool = False,
        columns: list[str] | None = None,
        materialized: bool | None = None,
    ) -> FluentQuery:
        """Adds a Common Table Expression (WITH clause)."""
        q_spec: QuerySpec | dict[str, Any] = (
            cte_query.to_spec() if isinstance(cte_query, FluentQuery) else cte_query
        )
        self._ctes.append(
            CteSpec(
                name=name,
                query=q_spec,
                recursive=recursive,
                columns=columns or [],
                materialized=materialized,
            )
        )
        return self

    def window(
        self,
        function: str,
        *,
        alias: str | None = None,
        partition_by: list[str] | None = None,
        order_by: list[OrderBySpec | dict[str, Any]] | None = None,
        arguments: list[Any] | None = None,
    ) -> FluentQuery:
        """Adds a window function projection."""
        parsed_orders: list[dict[str, Any] | OrderBySpec] = [
            o if isinstance(o, OrderBySpec) else OrderBySpec(**o)
            for o in (order_by or [])
        ]
        self._window_functions.append(
            WindowFunctionSpec(
                function=function,
                arguments=arguments or [],
                partition_by=partition_by or [],
                order_by=parsed_orders,
                alias=alias,
            )
        )
        return self

    def limit(self, count: int) -> FluentQuery:
        """Sets result limit."""
        self._limit = count
        return self

    def offset(self, count: int) -> FluentQuery:
        """Sets pagination offset."""
        self._offset = count
        return self

    def distinct(self, enable: bool = True) -> FluentQuery:
        """Enables or disables SELECT DISTINCT."""
        self._distinct = enable
        return self

    def tenant(self, tenant_id: Any) -> FluentQuery:
        """Sets tenant ID for multi-tenant isolation."""
        self._tenant_id = tenant_id
        return self

    def to_spec(self) -> QuerySpec:
        """Builds a typed QuerySpec dataclass instance."""
        return QuerySpec(
            table=self._table,
            columns=list(self._columns) if self._columns else ["*"],
            metrics=list(self._metrics),
            joins=[JoinSpec(**j) for j in self._joins],
            filters=[FilterSpec(**f) for f in self._filters],
            filter_join=self._filter_join,
            having=[HavingSpec(**h) for h in self._having],
            order_by=[OrderBySpec(**o) for o in self._order_by],
            limit=self._limit,
            offset=self._offset,
            distinct=self._distinct,
            grouping_type=self._grouping_type,
            grouping_sets=[list(s) for s in self._grouping_sets],
            ctes=list(self._ctes),
            window_functions=list(self._window_functions),
            tenant_id=self._tenant_id,
        )

    def to_dict(self) -> dict[str, Any]:
        """Converts to a serializable QuerySpec dictionary."""
        return self.to_spec().to_dict()

    def _compiler(
        self,
        dialect: str = "postgres",
        schema: Any = None,
    ) -> QueryCompiler:
        schema_dict = (
            schema.to_dict()
            if schema is not None and hasattr(schema, "to_dict")
            else schema
        )
        return QueryCompiler(self.to_dict(), schema=schema_dict, dialect=dialect)

    def compile(
        self,
        dialect: str = "postgres",
        schema: Any = None,
    ) -> tuple[str, list[Any], str, list[Any]]:
        """Compiles this query into SQL and parameters."""
        return self._compiler(dialect=dialect, schema=schema).compile()

    def compile_runnable(
        self,
        dialect: str = "postgres",
        schema: Any = None,
        *,
        pretty: bool = True,
    ) -> str | None:
        """Compiles this query into a formatted, runnable SQL string with inlined parameters."""
        return self._compiler(dialect=dialect, schema=schema).compile_runnable(
            pretty=pretty
        )

    def compile_search(
        self,
        search_term: str,
        dialect: str = "postgres",
        schema: Any = None,
    ) -> tuple[str, list[Any], str, list[Any]]:
        """Compiles this query with an automatic full-table text search predicate."""
        return self._compiler(dialect=dialect, schema=schema).compile_search(
            search_term
        )

    def check_columns(self, schema: Any) -> FluentQuery:
        """Validates every referenced column against ``schema`` (raises ``SpecColumnError`` if invalid)."""
        check_columns(self.to_spec(), schema)
        return self

    def to_sql(
        self,
        dialect: str = "postgres",
        schema: Any = None,
    ) -> str:
        """Compiles this query directly to a SQL string."""
        return self.compile(dialect=dialect, schema=schema)[0]

    def execute(self, connector: Any, **kwargs: Any) -> Any:
        """Executes this query against a connector instance."""
        return connector.execute(spec=self.to_dict(), **kwargs)


def query(table: str) -> FluentQuery:
    """Helper creating a FluentQuery builder for the specified table."""
    return FluentQuery(table)
