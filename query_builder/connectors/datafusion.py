"""
Apache Arrow DataFusion In-Memory Analytical Connector.
======================================================
Provides extensible, vectorized Arrow execution via DataFusion SessionContext.
"""

from __future__ import annotations

import time
from typing import Any

from query_builder.ast_validator import validate_sql_ast
from query_builder.compiler import CompilationError, QueryCompiler
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.schema import normalize_schema_snapshot


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

    def execute(
        self,
        spec: dict[str, Any],
        schema: dict[str, Any] | None = None,
        user_id: Any = None,
        statement_timeout_ms: int | None = None,
        validate_ast: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(spec, dict) and not hasattr(spec, "__dict__"):
            raise CompilationError(
                "Specification must be a dictionary or dataclass instance."
            )

        ctx = self.connect()
        compiler = QueryCompiler(
            spec=spec,
            schema=schema,
            user_id=user_id,
            force_user_filter=bool(user_id),
            dialect=self.dialect,
        )
        main_sql, main_params, count_sql, count_params = compiler.compile()

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

        count_query = count_sql
        if count_params:
            for p in count_params:
                val = f"'{p}'" if isinstance(p, str) else str(p)
                count_query = count_query.replace("?", val, 1)

        count_df = ctx.sql(count_query).collect()
        total_count = int(count_df[0][0][0].as_py()) if len(count_df) > 0 else 0

        query_sql = main_sql
        for p in main_params:
            val = f"'{p}'" if isinstance(p, str) else str(p)
            query_sql = query_sql.replace("?", val, 1)

        start = time.perf_counter()
        batches = ctx.sql(query_sql).collect()
        latency_ms = (time.perf_counter() - start) * 1000.0

        rows: list[dict[str, Any]] = []
        col_names: list[str] = []
        if len(batches) > 0:
            col_names = batches[0].schema.names
            for batch in batches:
                rows.extend(batch.to_pylist())

        limit = int(spec.get("limit", 50))
        offset = int(spec.get("offset", 0))

        return {
            "sql": main_sql,
            "params": [str(p) for p in main_params],
            "columns": col_names,
            "rows": rows,
            "count": total_count,
            "limit": limit,
            "offset": offset,
            "page": (offset // limit) + 1 if limit else 1,
            "latency_ms": round(latency_ms, 2),
            "dialect": self.dialect_name,
        }
