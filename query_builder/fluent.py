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
    FilterSpec,
    HavingSpec,
    JoinSpec,
    OrderBySpec,
    QuerySpec,
)


class FluentQuery:
    """Chainable Python query builder."""

    def __init__(self, table: str) -> None:
        self._table = table
        self._columns: list[str | dict[str, Any]] = []
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
    ) -> FluentQuery:
        """Adds an ORDER BY sorting condition."""
        o: dict[str, Any] = {"column": column, "direction": direction}
        if table_prefix:
            o["table_prefix"] = table_prefix
        self._order_by.append(o)
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
            joins=[JoinSpec(**j) for j in self._joins],
            filters=[FilterSpec(**f) for f in self._filters],
            filter_join=self._filter_join,
            having=[HavingSpec(**h) for h in self._having],
            order_by=[OrderBySpec(**o) for o in self._order_by],
            limit=self._limit,
            offset=self._offset,
            distinct=self._distinct,
            tenant_id=self._tenant_id,
        )

    def to_dict(self) -> dict[str, Any]:
        """Converts to a serializable QuerySpec dictionary."""
        return self.to_spec().to_dict()

    def compile(
        self,
        dialect: str = "postgres",
        schema: dict[str, Any] | None = None,
    ) -> tuple[str, list[Any], str, list[Any]]:
        """Compiles this query into SQL and parameters."""
        compiler = QueryCompiler(self.to_dict(), schema=schema, dialect=dialect)
        return compiler.compile()

    def to_sql(
        self,
        dialect: str = "postgres",
        schema: dict[str, Any] | None = None,
    ) -> str:
        """Compiles this query directly to a SQL string."""
        return self.compile(dialect=dialect, schema=schema)[0]

    def execute(self, connector: Any, **kwargs: Any) -> Any:
        """Executes this query against a connector instance."""
        return connector.execute(spec=self.to_dict(), **kwargs)


def query(table: str) -> FluentQuery:
    """Helper creating a FluentQuery builder for the specified table."""
    return FluentQuery(table)
