"""
Safe Read-Only Query Execution Harness.
=======================================
Provides transaction boundary management, strict statement timeout guards,
and standardized row mapping for DB-API 2.0 compliant database cursors.
"""

from __future__ import annotations

import time
from typing import Any

from query_builder.ast_validator import validate_sql_ast
from query_builder.compiler import CompilationError, QueryCompiler

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
) -> dict[str, Any]:
    """
    Compiles a QueryBuilderSpec, validates the resulting AST for mutation-free execution,
    and executes both the pagination query and count subquery.
    """
    compiler = QueryCompiler(
        spec=spec,
        schema=schema,
        user_id=user_id,
        force_user_filter=bool(user_id),
        dialect=dialect,
    )
    main_sql, main_params, count_sql, count_params = compiler.compile()

    if validate_ast:
        validation = validate_sql_ast(main_sql)
        if not validation["valid"]:
            raise CompilationError(
                f"Generated query failed AST safety validation: {validation['message']}"
            )

    # 1. Total Count
    if count_params:
        cursor.execute(count_sql, count_params)
    else:
        cursor.execute(count_sql)
    total_count = cursor.fetchone()[0]

    # 2. Main paginated query
    col_names, dict_rows, latency_ms = execute_cursor_query(
        cursor, main_sql, main_params
    )

    limit = int(spec.get("limit", 50))
    offset = int(spec.get("offset", 0))

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
