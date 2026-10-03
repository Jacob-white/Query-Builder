"""
Base Database Connector Specification and Execution Protocol.
=============================================================
Defines the foundational connector contract for execution, transaction management,
statement timeout isolation, health checks, and schema introspection.
"""

from __future__ import annotations

import contextlib
import time
import types
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any, Self

from query_builder.ast_validator import validate_sql_ast
from query_builder.compiler import CompilationError, QueryCompiler
from query_builder.dialects import BaseDialect, get_dialect
from query_builder.executor import execute_cursor_query
from query_builder.middleware import LifecycleInterceptor, MiddlewarePipeline


class ConnectorError(Exception):
    """Base exception for all database connector failures."""


class DriverNotInstalledError(ConnectorError):
    """Raised when an optional third-party database driver is required but not installed."""


class ConnectionFailedError(ConnectorError):
    """Raised when establishing a connection to the target database fails."""


class IntrospectionError(ConnectorError):
    """Raised when schema introspection cannot complete successfully."""


class BaseConnector(ABC):
    """
    Abstract base database connector providing standardized query compilation,
    read-only transaction execution, statement timeout guards, and schema introspection.
    """

    dialect_name: str = "postgres"
    default_timeout_ms: int = 5000

    def __init__(
        self,
        connection: Any = None,
        cursor: Any = None,
        dialect: str | BaseDialect | None = None,
        middleware: MiddlewarePipeline | list[LifecycleInterceptor] | None = None,
        **config: Any,
    ) -> None:
        self._connection = connection
        self._cursor = cursor
        self.config = config
        self.middleware = MiddlewarePipeline.ensure(middleware)

        if dialect is not None:
            self.dialect = (
                dialect if isinstance(dialect, BaseDialect) else get_dialect(dialect)
            )
            self.dialect_name = self.dialect.name
        else:
            self.dialect = get_dialect(self.dialect_name)

    @abstractmethod
    def connect(self) -> Any:
        """Establishes or returns an active database connection."""

    def close(self) -> None:
        """Closes the active connection if managed by this connector."""
        if self._cursor is not None:
            with contextlib.suppress(Exception):
                self._cursor.close()
            self._cursor = None

        if self._connection is not None:
            with contextlib.suppress(Exception):
                self._connection.close()
            self._connection = None

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        self.close()

    @contextlib.contextmanager
    def get_cursor(self) -> Iterator[Any]:
        """Context manager yielding a DB-API 2.0 cursor."""
        if self._cursor is not None:
            yield self._cursor
            return

        conn = self.connect()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
            try:
                yield cur
            finally:
                with contextlib.suppress(Exception):
                    cur.close()
        else:
            yield conn

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        """Hook for dialect-specific statement timeout configuration."""
        # Base implementation is a no-op; subclasses override with dialect-specific SQL.

    def test_connection(self) -> dict[str, Any]:
        """Validates connection health and returns dialect and engine metadata."""
        start = time.perf_counter()
        with self.get_cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "latency_ms": round(latency_ms, 2),
        }

    def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        """Executes a raw SQL statement against a cursor and maps rows to dicts."""
        with self.get_cursor() as cur:
            return execute_cursor_query(cur, sql, params)

    def execute(
        self,
        spec: dict[str, Any],
        schema: dict[str, Any] | None = None,
        user_id: Any = None,
        statement_timeout_ms: int | None = None,
        validate_ast: bool = True,
        middleware: MiddlewarePipeline | list[LifecycleInterceptor] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Compiles a query specification into the connector's dialect, validates AST safety,
        applies statement timeouts, executes count and paginated data queries with middleware hooks.
        """
        if not isinstance(spec, dict) and not hasattr(spec, "__dict__"):
            raise CompilationError(
                "Specification must be a dictionary or dataclass instance."
            )

        timeout = (
            statement_timeout_ms
            if statement_timeout_ms is not None
            else self.default_timeout_ms
        )
        if timeout <= 0:
            raise ValueError("statement_timeout_ms must be positive.")

        ctx = context if context is not None else {}
        pipeline = (
            MiddlewarePipeline.ensure(middleware)
            if middleware is not None
            else self.middleware
        )

        try:
            spec_dict = (
                {k: v for k, v in spec.__dict__.items() if not k.startswith("_")}
                if hasattr(spec, "__dict__") and not isinstance(spec, dict)
                else spec
            )

            # Pre-compile hook
            compiled_spec = pipeline.run_pre_compile(spec_dict, ctx)

            compiler = QueryCompiler(
                spec=compiled_spec,
                schema=schema,
                user_id=user_id,
                force_user_filter=bool(user_id),
                dialect=self.dialect,
            )
            main_sql, main_params, count_sql, count_params = compiler.compile()

            # Post-compile hook
            compilation = {
                "main_sql": main_sql,
                "main_params": main_params,
                "count_sql": count_sql,
                "count_params": count_params,
            }
            compilation = pipeline.run_post_compile(compilation, ctx)
            main_sql = compilation["main_sql"]
            main_params = compilation["main_params"]
            count_sql = compilation["count_sql"]
            count_params = compilation["count_params"]

            if validate_ast:
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

            execution_plan = {
                "main_sql": main_sql,
                "main_params": main_params,
                "count_sql": count_sql,
                "count_params": count_params,
                "spec": compiled_spec,
            }

            # Pre-execute hook (short-circuit support)
            short_circuited, result_or_plan = pipeline.run_pre_execute(
                execution_plan, ctx
            )
            if short_circuited:
                return pipeline.run_post_execute(result_or_plan, ctx)

            with self.get_cursor() as cur:
                self.apply_statement_timeout(cur, timeout)

                # 1. Total Count query
                if count_params:
                    cur.execute(count_sql, count_params)
                else:
                    cur.execute(count_sql)
                count_row = cur.fetchone()
                total_count = count_row[0] if (count_row and len(count_row) > 0) else 0

                # 2. Main paginated query
                col_names, dict_rows, latency_ms = execute_cursor_query(
                    cur, main_sql, main_params
                )

            limit = int(compiled_spec.get("limit", 50))
            offset = int(compiled_spec.get("offset", 0))

            raw_result = {
                "sql": main_sql,
                "params": [str(p) for p in main_params],
                "columns": col_names,
                "rows": dict_rows,
                "count": total_count,
                "limit": limit,
                "offset": offset,
                "page": (offset // limit) + 1 if limit else 1,
                "latency_ms": round(latency_ms, 2),
                "dialect": self.dialect_name,
            }

            return pipeline.run_post_execute(raw_result, ctx)

        except Exception as exc:
            pipeline.run_error(exc, ctx)
            raise

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        """
        Automatically reverse-engineers tables, columns, primary keys, and relationships.

        Fallback implementation attempts dialect-specific inspection via cursor:
        1. SQLite introspection if dialect is sqlite or connection is sqlite3.
        2. ANSI information_schema catalog query if supported.
        3. Returns a normalized empty schema snapshot if catalogs are unavailable.
        """
        try:
            with self.get_cursor() as cur:
                if self.dialect_name in ("sqlite", "sqlite3") or hasattr(
                    self._connection, "backup"
                ):
                    from query_builder.connectors.introspection import introspect_sqlite

                    return introspect_sqlite(cur, filter_sensitive=filter_sensitive)

                schema_name = getattr(self, "schema_name", None) or self.config.get(
                    "schema_name", "public"
                )
                from query_builder.connectors.introspection import (
                    introspect_information_schema,
                )

                return introspect_information_schema(
                    cur, schema_name=schema_name, filter_sensitive=filter_sensitive
                )
        except Exception:  # noqa: BLE001
            from query_builder.schema import normalize_schema_snapshot

            return normalize_schema_snapshot(
                {"tables": {}, "foreign_keys": [], "relationships": []},
                filter_sensitive=filter_sensitive,
            )
