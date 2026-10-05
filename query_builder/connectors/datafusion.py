"""
Apache Arrow DataFusion In-Memory Analytical Connector.
======================================================
Provides extensible, vectorized Arrow execution via DataFusion SessionContext.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

from query_builder.ast_validator import validate_sql_ast
from query_builder.compiler import (
    CompilationError,
    QueryCompiler,
)
from query_builder.config import SecurityConfig
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.middleware import (
    LifecycleInterceptor,
    MiddlewarePipeline,
)
from query_builder.models import QuerySpec
from query_builder.schema import normalize_schema_snapshot


def _format_literal(val: Any) -> str:
    """Safely escapes and formats a python value into a SQL literal."""
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float)):
        return str(val)
    s = str(val).replace("'", "''")
    return f"'{s}'"


def _substitute_params(sql: str, params: list[Any] | None) -> str:
    """Substitutes positional ? placeholders without corrupting string literals."""
    if not params:
        return sql
    formatted = [_format_literal(p) for p in params]
    param_idx = 0
    num_params = len(formatted)
    out: list[str] = []
    in_quote = False
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            if in_quote and i + 1 < n and sql[i + 1] == "'":
                out.append("''")
                i += 2
                continue
            in_quote = not in_quote
            out.append("'")
            i += 1
        elif ch == "?" and not in_quote and param_idx < num_params:
            out.append(formatted[param_idx])
            param_idx += 1
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


class _DataFusionCursorAdapter:
    """DB-API compliant cursor adapter for Apache Arrow DataFusion SessionContext."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.description: list[tuple[str, ...]] | None = None
        self._rows: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        sub_sql = _substitute_params(sql, params)
        batches = self.ctx.sql(sub_sql).collect()
        if batches:
            first_batch = batches[0]
            if isinstance(first_batch, list):
                val = first_batch[0][0] if first_batch and first_batch[0] else 0
                cnt = int(val.as_py()) if hasattr(val, "as_py") else int(val)
                self.description = [("count",)]
                self._rows = [(cnt,)]
            else:
                col_names = [str(c) for c in getattr(first_batch.schema, "names", [])]
                self.description = [(c,) for c in col_names]
                all_rows = []
                for b in batches:
                    dicts = b.to_pylist()
                    for d in dicts:
                        all_rows.append(tuple(d.get(c) for c in col_names))
                self._rows = all_rows
        else:
            self.description = []
            self._rows = []

    def fetchone(self) -> tuple[Any, ...] | None:
        if self._rows:
            return self._rows.pop(0)
        return None

    def fetchall(self) -> list[tuple[Any, ...]]:
        rows = self._rows
        self._rows = []
        return rows

    def close(self) -> None:
        self._rows = []


class DataFusionConnector(BaseConnector):
    """Connector for Apache Arrow DataFusion SessionContext."""

    dialect_name = "datafusion"

    def __init__(
        self,
        context: Any = None,
        tables: dict[str, Any] | None = None,
        **config: Any,
    ) -> None:
        super().__init__(**config)
        self._context = context
        self._tables = tables or {}

    def close(self) -> None:
        """Releases registered tables and execution context resources."""
        self._tables.clear()
        self._context = None
        super().close()

    def connect(self) -> Any:
        if self._context is not None:
            return self._context

        try:
            from datafusion import SessionContext
        except ImportError as err:
            raise DriverNotInstalledError(
                "datafusion is not installed. Install with: pip install 'query-builder-engine[datafusion]'"
            ) from err

        try:
            self._context = SessionContext()
            for name, df in self._tables.items():
                self._context.register_table(name, df)
            return self._context
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to initialize DataFusion SessionContext: {exc}"
            ) from exc

    def register_table(self, name: str, table_provider: Any) -> None:
        ctx = self.connect()
        ctx.register_table(name, table_provider)
        self._tables[name] = table_provider

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        ctx = self.connect()
        ctx.sql("SELECT 1").collect()
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "latency_ms": round(latency_ms, 2),
            "engine_version": "Apache Arrow DataFusion",
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        ctx = self.connect()
        try:
            tables_map: dict[str, dict[str, Any]] = {}
            for tbl in self._tables:
                df = ctx.table(tbl)
                cols: list[dict[str, Any]] = []
                has_user = False
                for field in df.schema():
                    f_name = str(field.name)
                    if f_name == "user_id":
                        has_user = True
                    cols.append(
                        {
                            "name": f_name,
                            "data_type": str(field.type).lower(),
                            "is_nullable": bool(field.nullable),
                            "is_primary": f_name == "id",
                            "comment": None,
                        }
                    )
                tables_map[tbl] = {
                    "name": tbl,
                    "columns": cols,
                    "has_user_id": has_user,
                    "user_col": "user_id",
                    "comment": None,
                }

            return normalize_schema_snapshot(
                {"tables": tables_map, "foreign_keys": [], "relationships": []},
                filter_sensitive=filter_sensitive,
            )
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect DataFusion schema: {exc}"
            ) from exc

    @contextlib.contextmanager
    def get_cursor(self) -> Any:
        if self._cursor is not None:
            yield self._cursor
            return
        ctx = self.connect()
        adapter = _DataFusionCursorAdapter(ctx)
        try:
            yield adapter
        finally:
            adapter.close()

    def execute(
        self,
        spec: dict[str, Any] | QuerySpec | None = None,
        schema: dict[str, Any] | None = None,
        user_id: Any = None,
        statement_timeout_ms: int | None = None,
        validate_ast: bool = True,
        middleware: MiddlewarePipeline | list[LifecycleInterceptor] | None = None,
        context: dict[str, Any] | None = None,
        *,
        sql: str | None = None,
        params: list[Any] | None = None,
        timeout_ms: int | None = None,
        security: SecurityConfig | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if (
            spec is not None
            and not isinstance(spec, dict)
            and not hasattr(spec, "__dict__")
        ):
            raise CompilationError(
                "Specification must be a dictionary or dataclass instance."
            )
        if validate_ast and spec is not None:
            compiler = QueryCompiler(
                spec=spec if isinstance(spec, dict) else {},
                schema=schema,
                user_id=user_id,
                force_user_filter=bool(user_id),
                dialect=self.dialect,
            )
            main_sql, _, count_sql, _ = compiler.compile()
            v_main = validate_sql_ast(main_sql)
            if not v_main["valid"]:
                raise CompilationError(
                    f"Generated query failed AST safety validation: {v_main['message']}"
                )
            v_count = validate_sql_ast(count_sql)
            if not v_count["valid"]:
                raise CompilationError(
                    f"Generated count query failed AST safety validation: {v_count['message']}"
                )
        return super().execute(
            spec=spec,
            schema=schema,
            user_id=user_id,
            statement_timeout_ms=statement_timeout_ms,
            validate_ast=validate_ast,
            middleware=middleware,
            context=context,
            sql=sql,
            params=params,
            timeout_ms=timeout_ms,
            security=security,
            **kwargs,
        )
