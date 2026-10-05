"""
Amazon Web Services (AWS) Timestream SQL Time-Series Connector.
===============================================================
Provides AWS Timestream connectivity via boto3 timestream-query,
dual sync and async execution protocols, and Timestream measure introspection.
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
from query_builder.connectors.introspection import introspect_timestream
from query_builder.connectors.registry import register_connector


class _TimestreamCursorAdapter:
    """Adapts a boto3 timestream-query client into a standard DB-API cursor interface."""

    def __init__(self, connection: Any) -> None:
        self.conn = connection
        self.description: list[tuple[str, ...]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if hasattr(self.conn, "cursor"):
            cur = self.conn.cursor()
            try:
                if params:
                    cur.execute(clean_sql, params)
                else:
                    cur.execute(clean_sql)
                self.description = getattr(cur, "description", None)
                self._rows = list(cur.fetchall()) if hasattr(cur, "fetchall") else []
            finally:
                if hasattr(cur, "close"):
                    cur.close()
        elif hasattr(self.conn, "query"):
            res = self.conn.query(QueryString=clean_sql)
            col_info = res.get("ColumnInfo", [])
            self.description = [(c.get("Name", "col"),) for c in col_info]
            rows_data = res.get("Rows", [])
            self._rows = [
                [data.get("ScalarValue") for data in r.get("Data", [])]
                for r in rows_data
            ]
        elif hasattr(self.conn, "execute"):
            res = (
                self.conn.execute(clean_sql, params)
                if params
                else self.conn.execute(clean_sql)
            )
            self.description = getattr(res, "description", None)
            if hasattr(res, "fetchall"):
                self._rows = list(res.fetchall())
            elif isinstance(res, (list, tuple)):
                self._rows = list(res)
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

    def fetchmany(self, size: int = 1) -> list[list[Any]]:
        if not self._rows:
            return []
        res = self._rows[:size]
        self._rows = self._rows[size:]
        return res

    def close(self) -> None:
        self._rows = []


@register_connector("timestream", aliases=["aws_timestream"])
class TimestreamConnector(BaseConnector):
    """Connector for Amazon Timestream serverless time-series database."""

    dialect_name = "timestream"

    def __init__(
        self,
        database_name: str = "default",
        region_name: str = "us-east-1",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.database_name = database_name
        self.region_name = region_name

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            import boto3
        except ImportError as err:
            raise DriverNotInstalledError(
                "boto3 is not installed. Install with: pip install 'query-builder-engine[timestream]'"
            ) from err

        try:
            self._connection = boto3.client(
                "timestream-query", region_name=self.region_name, **self.config
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to AWS Timestream: {exc}"
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
        else:
            adapter = _TimestreamCursorAdapter(conn)
            try:
                yield adapter
            finally:
                adapter.close()

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        with self.get_cursor() as cur:
            cur.execute(f'SHOW TABLES FROM "{self.database_name}"')
            cur.fetchone()
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "AWS Timestream",
            "latency_ms": round(latency_ms, 2),
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_timestream(
                    cur,
                    database_name=self.database_name,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Timestream schema: {exc}"
                ) from exc


@register_connector("async_timestream", aliases=["async_aws_timestream"])
class AsyncTimestreamConnector(AsyncBaseConnector):
    """Asynchronous connector for Amazon Timestream time-series database."""

    dialect_name = "timestream"

    def __init__(
        self,
        database_name: str = "default",
        region_name: str = "us-east-1",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.database_name = database_name
        self.region_name = region_name

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            import boto3
        except ImportError as err:
            raise DriverNotInstalledError(
                "boto3 is not installed. Install with: pip install 'query-builder-engine[timestream]'"
            ) from err

        try:
            self._connection = boto3.client(
                "timestream-query", region_name=self.region_name, **self.config
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to AWS Timestream: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
        else:
            cur = _TimestreamCursorAdapter(conn)

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

    async def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        await self.execute_raw(f'SHOW TABLES FROM "{self.database_name}"')
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "AWS Timestream",
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        cur = (
            conn.cursor() if hasattr(conn, "cursor") else _TimestreamCursorAdapter(conn)
        )
        try:
            return introspect_timestream(
                cur,
                database_name=self.database_name,
                filter_sensitive=filter_sensitive,
            )
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Timestream schema: {exc}"
            ) from exc
        finally:
            if hasattr(cur, "close"):
                cur.close()
