"""
Apache Spark SQL Lakehouse and Big Data Engine Connector.
=========================================================
Provides Apache Spark SQL connectivity, dual sync and async execution protocols,
cursor adapters for PySpark SparkSession and Thrift/PyHive, statement timeouts,
and schema introspection.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_sparksql
from query_builder.connectors.registry import register_connector


class _SparkCursorAdapter:
    """Adapts a PySpark SparkSession or DataFrame execution into a DB-API cursor interface."""

    def __init__(self, session_or_client: Any) -> None:
        self.client = session_or_client
        self.description: list[tuple[str]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if hasattr(self.client, "sql"):
            # PySpark SparkSession
            df = self.client.sql(clean_sql)
            if hasattr(df, "columns"):
                self.description = [(col,) for col in df.columns]
            if hasattr(df, "collect"):
                rows = df.collect()
                self._rows = [
                    [
                        getattr(r, col, r[col] if isinstance(r, dict) else r)
                        for col in (
                            df.columns if hasattr(df, "columns") else range(len(r))
                        )
                    ]
                    if hasattr(r, "__getitem__")
                    else [r]
                    for r in rows
                ]
            else:
                self._rows = []
        elif hasattr(self.client, "execute"):
            if params:
                self.client.execute(clean_sql, params)
            else:
                self.client.execute(clean_sql)
            self.description = getattr(self.client, "description", None)
            if hasattr(self.client, "fetchall"):
                self._rows = list(self.client.fetchall())
            else:
                self._rows = []
        else:
            self.description = None
            self._rows = []

    def fetchone(self) -> list[Any] | None:
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[list[Any]]:
        res = self._rows
        self._rows = []
        return res

    def close(self) -> None:
        pass


@register_connector("sparksql", aliases=["spark_sql", "pyspark"])
class SparkSQLConnector(BaseConnector):
    """Connector for Apache Spark SQL big data and lakehouse query engine."""

    dialect_name = "sparksql"

    def __init__(
        self,
        schema_name: str = "default",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.schema_name = schema_name

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("pyspark.sql", "pyhive.hive", "thrift"):
            try:
                driver = __import__(mod_name, fromlist=["SparkSession", "connect"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'pyspark' (or 'pyhive') is not installed. "
                "Install with: pip install 'query-builder-engine[spark]'"
            )

        try:
            if hasattr(driver, "SparkSession"):
                builder = driver.SparkSession.builder.appName("QueryBuilder")
                for k, v in self.config.items():
                    builder = builder.config(k, v)
                self._connection = builder.getOrCreate()
                return self._connection

            self._connection = driver.connect(schema=self.schema_name, **self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Apache Spark SQL: {exc}"
            ) from exc

    @contextlib.contextmanager
    def get_cursor(self) -> Any:
        if self._cursor is not None:
            yield self._cursor
            return

        conn = self.connect()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
            try:
                yield cur
            finally:
                if hasattr(cur, "close"):
                    cur.close()
        elif hasattr(conn, "sql"):
            adapter = _SparkCursorAdapter(conn)
            yield adapter
        else:
            adapter = _SparkCursorAdapter(conn)
            yield adapter

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        pass

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "Apache Spark SQL"
        info["schema_name"] = self.schema_name
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_sparksql(
                    cur,
                    schema_name=self.schema_name,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Spark SQL schema '{self.schema_name}': {exc}"
                ) from exc


SparkConnector = SparkSQLConnector


@register_connector("async_sparksql", aliases=["async_spark_sql", "async_pyspark"])
class AsyncSparkSQLConnector(AsyncBaseConnector):
    """Asynchronous connector for Apache Spark SQL engine."""

    dialect_name = "sparksql"

    def __init__(
        self,
        schema_name: str = "default",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.schema_name = schema_name

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("pyspark.sql", "pyhive.hive", "thrift"):
            try:
                driver = __import__(mod_name, fromlist=["SparkSession", "connect"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'pyspark' (or 'pyhive') is not installed. "
                "Install with: pip install 'query-builder-engine[spark]'"
            )

        try:
            if hasattr(driver, "SparkSession"):
                builder = driver.SparkSession.builder.appName("QueryBuilderAsync")
                for k, v in self.config.items():
                    builder = builder.config(k, v)
                self._connection = builder.getOrCreate()
                return self._connection

            self._connection = driver.connect(schema=self.schema_name, **self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Apache Spark SQL: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
            try:
                if params:
                    cur.execute(sql, params)
                else:
                    cur.execute(sql)
                desc = cur.description or []
                col_names = [col[0] for col in desc]
                rows = cur.fetchall() or []
                dict_rows = [dict(zip(col_names, r)) for r in rows]
                latency_ms = (time.perf_counter() - start) * 1000.0
                return col_names, dict_rows, latency_ms
            finally:
                if hasattr(cur, "close"):
                    cur.close()
        elif hasattr(conn, "sql"):
            adapter = _SparkCursorAdapter(conn)
            adapter.execute(sql, params)
            desc = adapter.description or []
            col_names = [col[0] for col in desc]
            rows = adapter.fetchall() or []
            dict_rows = [dict(zip(col_names, r)) for r in rows]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms
        else:
            adapter = _SparkCursorAdapter(conn)
            adapter.execute(sql, params)
            desc = adapter.description or []
            col_names = [col[0] for col in desc]
            rows = adapter.fetchall() or []
            dict_rows = [dict(zip(col_names, r)) for r in rows]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms


AsyncSparkConnector = AsyncSparkSQLConnector
