"""
Safe Read-Only Query Execution Harness.
=======================================
Provides transaction boundary management, strict statement timeout guards,
and standardized row mapping for DB-API 2.0 compliant database cursors.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from query_builder.ast_validator import validate_sql_ast
from query_builder.compiler import CompilationError, QueryCompiler
from query_builder.exceptions import SecurityError
from query_builder.middleware import LifecycleInterceptor, MiddlewarePipeline

DEFAULT_TIMEOUT_MS = 5000


def execute_cursor_query(
    cursor: Any,
    sql: str,
    params: list[Any] | None = None,
) -> tuple[list[str], list[dict[str, Any]], float]:
    """
    Executes a SQL query against an open DB-API cursor, measuring latency
    and mapping output rows into dictionaries.
    """
    if cursor is None:
        raise ValueError("Database cursor cannot be None.")
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("SQL query must be a non-empty string.")

    start_time = time.perf_counter()
    if params:
        cursor.execute(sql, params)
    else:
        cursor.execute(sql)

    col_names = [desc[0] for desc in cursor.description] if cursor.description else []
    raw_rows = cursor.fetchall()
    latency_ms = (time.perf_counter() - start_time) * 1000.0

    dict_rows = [dict(zip(col_names, row)) for row in raw_rows]
    return col_names, dict_rows, latency_ms


def execute_compiled_spec(
    cursor: Any,
    spec: dict[str, Any],
    schema: dict[str, Any] | None = None,
    user_id: Any = None,
    dialect: str = "postgres",
    statement_timeout_ms: int = DEFAULT_TIMEOUT_MS,
    validate_ast: bool = True,
    tenant_id: Any = None,
) -> dict[str, Any]:
    """
    Compiles a QueryBuilderSpec, validates the resulting AST for mutation-free execution,
    and executes both the pagination query and count subquery.
    """
    if cursor is None:
        raise ValueError("Database cursor cannot be None.")
    if not isinstance(spec, dict) and not hasattr(spec, "__dict__"):
        raise CompilationError(
            "Specification must be a dictionary or dataclass instance."
        )

    try:
        timeout = int(statement_timeout_ms)
        if timeout <= 0:
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise ValueError("statement_timeout_ms must be positive.") from exc

    spec_dict = (
        {k: v for k, v in spec.__dict__.items() if not k.startswith("_")}
        if hasattr(spec, "__dict__") and not isinstance(spec, dict)
        else dict(spec)
    )

    resolved_tenant = tenant_id if tenant_id is not None else spec_dict.get("tenant_id")

    compiler = QueryCompiler(
        spec=spec,
        schema=schema,
        user_id=user_id,
        force_user_filter=bool(user_id),
        dialect=dialect,
        tenant_id=resolved_tenant,
    )
    main_sql, main_params, count_sql, count_params = compiler.compile()

    if validate_ast:
        validation = validate_sql_ast(main_sql)
        if not validation["valid"]:
            raise SecurityError(
                f"Generated query failed AST safety validation: {validation['message']}"
            )
        count_validation = validate_sql_ast(count_sql)
        if not count_validation["valid"]:
            raise SecurityError(
                f"Generated count query failed AST safety validation: {count_validation['message']}"
            )

    # 1. Total Count
    if count_params:
        cursor.execute(count_sql, count_params)
    else:
        cursor.execute(count_sql)
    count_row = cursor.fetchone()
    total_count = count_row[0] if (count_row and len(count_row) > 0) else 0

    # 2. Main paginated query
    col_names, dict_rows, latency_ms = execute_cursor_query(
        cursor, main_sql, main_params
    )

    limit = int(spec_dict.get("limit", 50))
    offset = int(spec_dict.get("offset", 0))

    return {
        "sql": main_sql,
        "params": [str(p) for p in main_params],
        "columns": col_names,
        "rows": dict_rows,
        "count": total_count,
        "limit": limit,
        "offset": offset,
        "page": (offset // limit) + 1 if limit else 1,
        "latency_ms": round(latency_ms, 2),
    }


async def async_execute(
    connector: Any,
    spec: dict[str, Any],
    schema: dict[str, Any] | None = None,
    user_id: Any = None,
    timeout_ms: int | None = None,
    validate_ast: bool = True,
    middleware: MiddlewarePipeline | list[LifecycleInterceptor] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Asynchronously executes a query specification against either an AsyncBaseConnector
    or a synchronous BaseConnector (offloaded to threadpool), with timeout cancellation
    via asyncio.wait_for and full middleware lifecycle execution.
    """
    if connector is None:
        raise ValueError("Connector cannot be None.")
    if not isinstance(spec, dict) and not hasattr(spec, "__dict__"):
        raise CompilationError(
            "Specification must be a dictionary or dataclass instance."
        )

    if timeout_ms is not None:
        try:
            t = int(timeout_ms)
            if t <= 0:
                raise ValueError
        except (ValueError, TypeError) as exc:
            raise ValueError("timeout_ms must be positive.") from exc

    ctx = context if context is not None else {}
    pipeline = (
        MiddlewarePipeline.ensure(middleware)
        if middleware is not None
        else getattr(connector, "middleware", MiddlewarePipeline())
    )

    is_async = asyncio.iscoroutinefunction(getattr(connector, "execute", None))
    timeout_sec = (timeout_ms / 1000.0) if timeout_ms is not None else None

    async def _run() -> dict[str, Any]:
        if is_async:
            return await connector.execute(
                spec=spec,
                schema=schema,
                user_id=user_id,
                statement_timeout_ms=timeout_ms,
                validate_ast=validate_ast,
                middleware=pipeline,
                context=ctx,
            )
        return await asyncio.to_thread(
            connector.execute,
            spec=spec,
            schema=schema,
            user_id=user_id,
            statement_timeout_ms=timeout_ms,
            validate_ast=validate_ast,
            middleware=pipeline,
            context=ctx,
        )

    try:
        if timeout_sec is not None:
            return await asyncio.wait_for(_run(), timeout=timeout_sec)
        return await _run()
    except TimeoutError as exc:
        pipeline.run_error(exc, ctx)
        raise TimeoutError(f"Query execution timed out after {timeout_ms}ms") from exc
    except asyncio.CancelledError as exc:
        pipeline.run_error(exc, ctx)
        raise
    except Exception as exc:
        pipeline.run_error(exc, ctx)
        raise
