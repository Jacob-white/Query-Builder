"""
Asynchronous Database Connector Specification and Execution Protocol.
======================================================================
Defines the abstract base class for asynchronous database connectors, supporting
async/await transaction boundaries, statement timeouts, schema introspection fallbacks,
and lifecycle middleware pipeline execution.
"""

from __future__ import annotations

import asyncio
import time
import types
from abc import ABC, abstractmethod
from typing import Any, Self

from query_builder.ast_validator import validate_sql_ast
from query_builder.compiler import CompilationError, QueryCompiler
from query_builder.dialects import BaseDialect, get_dialect
from query_builder.middleware import LifecycleInterceptor, MiddlewarePipeline


class AsyncBaseConnector(ABC):
    """
    Abstract base asynchronous database connector providing standardized query compilation,
    async transaction execution, statement timeout guards, and schema introspection.
    """

    dialect_name: str = "postgres"
    default_timeout_ms: int = 5000

    def __init__(
        self,
        connection: Any = None,
        dialect: str | BaseDialect | None = None,
        middleware: MiddlewarePipeline | list[LifecycleInterceptor] | None = None,
        **config: Any,
    ) -> None:
        self._connection = connection
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
    async def connect(self) -> Any:
        """Establishes or returns an active database connection asynchronously."""

    async def close(self) -> None:
        """Closes the active connection if managed by this connector."""
        if self._connection is not None:
            if hasattr(self._connection, "close"):
                res = self._connection.close()
                if asyncio.iscoroutine(res):
                    await res
            self._connection = None

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        await self.close()

    async def test_connection(self) -> dict[str, Any]:
        """Validates connection health and returns dialect and engine metadata."""
        start = time.perf_counter()
        await self.execute_raw("SELECT 1")
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        """Default async schema introspection fallback returning normalized snapshot."""
        from query_builder.schema import normalize_schema_snapshot

        return normalize_schema_snapshot(
            {"tables": {}, "foreign_keys": [], "relationships": []},
            filter_sensitive=filter_sensitive,
        )

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        """Executes a raw SQL statement asynchronously against the database."""
        raise NotImplementedError("Subclasses must implement execute_raw()")

    async def execute(
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
        and executes count and paginated data queries asynchronously with middleware hooks.
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

            # Compile query
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

            # 1. Total Count query
            _count_cols, count_rows, _ = await self.execute_raw(count_sql, count_params)
            total_count = 0
            if count_rows:
                first_row = count_rows[0]
                if isinstance(first_row, dict):
                    total_count = next(iter(first_row.values())) if first_row else 0
                else:
                    total_count = first_row[0] if len(first_row) > 0 else 0

            # 2. Main paginated query
            col_names, dict_rows, latency_ms = await self.execute_raw(
                main_sql, main_params
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
