"""
YugabyteDB Distributed Cloud-Native HTAP Database Connector.
============================================================
Provides YugabyteDB connectivity via PostgreSQL protocols (psycopg2 / psycopg / asyncpg),
dual sync and async execution protocols, statement isolation, and schema introspection.
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
from query_builder.connectors.introspection import introspect_yugabyte
from query_builder.connectors.registry import register_connector


@register_connector("yugabyte", aliases=["yugabytedb"])
class YugabyteDBConnector(BaseConnector):
    """Connector for YugabyteDB distributed cloud-native HTAP database."""

    dialect_name = "yugabyte"

    def __init__(
        self,
        schema_name: str = "public",
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
        for mod_name in ("psycopg2", "psycopg", "yugabytedb"):
            try:
                driver = __import__(mod_name)
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'psycopg2' or 'psycopg' is not installed. "
                "Install with: pip install 'query-builder-engine[yugabyte]'"
            )

        try:
            self._connection = driver.connect(**self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to YugabyteDB: {exc}"
            ) from exc

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        cursor.execute(f"SET statement_timeout = {timeout_ms};")

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        with self.get_cursor() as cur, contextlib.suppress(Exception):
            cur.execute("SELECT version();")
            row = cur.fetchone() if hasattr(cur, "fetchone") else None
            if row is not None:
                ver = (
                    row[0]
                    if isinstance(row, (tuple, list)) and len(row) > 0
                    else str(row)
                )
                info["engine_version"] = f"YugabyteDB {ver}".strip()
        info["schema_name"] = self.schema_name
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_yugabyte(
                    cur,
                    schema_name=self.schema_name,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect YugabyteDB schema '{self.schema_name}': {exc}"
                ) from exc


YugabyteConnector = YugabyteDBConnector


@register_connector("async_yugabyte", aliases=["async_yugabytedb"])
class AsyncYugabyteDBConnector(AsyncBaseConnector):
    """Asynchronous connector for YugabyteDB distributed HTAP database."""

    dialect_name = "yugabyte"

    def __init__(
        self,
        schema_name: str = "public",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.schema_name = schema_name

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("asyncpg", "psycopg", "psycopg2"):
            try:
                driver = __import__(mod_name)
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'asyncpg' or 'psycopg' is not installed. "
                "Install with: pip install 'query-builder-engine[yugabyte]'"
            )

        try:
            if hasattr(driver, "connect"):
                res = driver.connect(**self.config)
                self._connection = await res if hasattr(res, "__await__") else res
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to YugabyteDB: {exc}"
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
                with contextlib.suppress(Exception):
                    cur.close()
        elif hasattr(conn, "fetch"):
            # asyncpg
            records = await conn.fetch(sql, *(params or []))
            col_names = list(records[0].keys()) if records else []
            dict_rows = [dict(r) for r in records]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms
        elif hasattr(conn, "execute"):
            res = conn.execute(sql, *(params or [])) if params else conn.execute(sql)
            if hasattr(res, "__await__"):
                res = await res
            desc = (
                getattr(conn, "description", None)
                or getattr(res, "description", None)
                or []
            )
            col_names = [col[0] for col in desc]
            fetchall_fn = getattr(conn, "fetchall", None) or getattr(
                res, "fetchall", None
            )
            raw_rows = fetchall_fn() if fetchall_fn else []
            if hasattr(raw_rows, "__await__"):
                raw_rows = await raw_rows
            dict_rows = [
                dict(zip(col_names, r)) if not isinstance(r, dict) else r
                for r in (raw_rows or [])
            ]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms
        return None

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        try:
            if hasattr(conn, "cursor"):
                cur = conn.cursor()
                try:
                    return introspect_yugabyte(
                        cur,
                        schema_name=self.schema_name,
                        filter_sensitive=filter_sensitive,
                    )
                finally:
                    with contextlib.suppress(Exception):
                        cur.close()
            return introspect_yugabyte(
                conn,
                schema_name=self.schema_name,
                filter_sensitive=filter_sensitive,
            )
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect YugabyteDB schema '{self.schema_name}': {exc}"
            ) from exc


AsyncYugabyteConnector = AsyncYugabyteDBConnector
