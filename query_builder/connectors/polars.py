"""
Polars Vectorized In-Memory Analytical Connector.
================================================
Provides lightning-fast in-memory SQL execution against Polars DataFrames and LazyFrames.
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


class PolarsConnector(BaseConnector):
    """Connector for Polars in-memory SQLContext."""

    dialect_name = "polars"

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
            import polars as pl
        except ImportError as err:
            raise DriverNotInstalledError(
                "polars is not installed. Install with: pip install 'query-builder-engine[polars]'"
            ) from err

        try:
            self._context = pl.SQLContext()
            for name, df in self._tables.items():
                self._context.register(name, df)
            return self._context
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to initialize Polars SQLContext: {exc}"
            ) from exc

    def register_table(self, name: str, data: Any) -> None:
        """Registers a DataFrame or LazyFrame in the SQLContext."""
        ctx = self.connect()
        ctx.register(name, data)
        self._tables[name] = data

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        ctx = self.connect()
        ctx.execute("SELECT 1").collect()
        latency_ms = (time.perf_counter() - start) * 1000.0
        info: dict[str, Any] = {
            "status": "healthy",
            "dialect": self.dialect_name,
            "latency_ms": round(latency_ms, 2),
        }
        try:
            import polars as pl

            info["engine_version"] = f"Polars {pl.__version__}"
        except ImportError:
            pass
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        ctx = self.connect()
        try:
            table_names = ctx.tables()
            tables_map: dict[str, dict[str, Any]] = {}

            for tbl in table_names:
                df = self._tables.get(tbl)
                cols: list[dict[str, Any]] = []
                has_user = False

                if df is not None and hasattr(df, "schema"):
                    for c_name, c_type in df.schema.items():
                        c_str = str(c_name)
                        if c_str == "user_id":
                            has_user = True
                        cols.append(
                            {
                                "name": c_str,
                                "data_type": str(c_type).lower(),
                                "is_nullable": True,
                                "is_primary": c_str == "id",
                                "comment": None,
                            }
                        )
                else:
                    # Discover columns by querying 0 rows
                    sampled = ctx.execute(f'SELECT * FROM "{tbl}" LIMIT 0').collect()
                    for c_name, c_type in sampled.schema.items():
                        c_str = str(c_name)
                        if c_str == "user_id":
                            has_user = True
                        cols.append(
                            {
                                "name": c_str,
                                "data_type": str(c_type).lower(),
                                "is_nullable": True,
                                "is_primary": c_str == "id",
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
                f"Failed to introspect Polars tables: {exc}"
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

        # 1. Total Count
        count_query = count_sql
        if count_params:
            for p in count_params:
                val = f"'{p}'" if isinstance(p, str) else str(p)
                count_query = count_query.replace("?", val, 1)

        count_df = ctx.execute(count_query).collect()
        total_count = int(count_df[0, 0]) if count_df.height > 0 else 0

        # 2. Main Query
        query_sql = main_sql
        for p in main_params:
            val = f"'{p}'" if isinstance(p, str) else str(p)
            query_sql = query_sql.replace("?", val, 1)

        start = time.perf_counter()
        result_df = ctx.execute(query_sql).collect()
        latency_ms = (time.perf_counter() - start) * 1000.0

        limit = int(spec.get("limit", 50))
        offset = int(spec.get("offset", 0))

        return {
            "sql": main_sql,
            "params": [str(p) for p in main_params],
            "columns": result_df.columns,
            "rows": result_df.to_dicts(),
            "count": total_count,
            "limit": limit,
            "offset": offset,
            "page": (offset // limit) + 1 if limit else 1,
            "latency_ms": round(latency_ms, 2),
            "dialect": self.dialect_name,
        }
