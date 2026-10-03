"""
IBM DB2 Enterprise Relational Database Connector.
=================================================
Provides IBM DB2 connectivity via ibm_db_dbi / ibm_db, dual sync and async
execution protocols, query statement isolation, and SYSCAT schema introspection.
"""

from __future__ import annotations

import time
from typing import Any

from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_db2
from query_builder.connectors.registry import register_connector


@register_connector("db2", aliases=["ibm_db2"])
class DB2Connector(BaseConnector):
    """Connector for IBM DB2 enterprise relational database."""

    dialect_name = "db2"

    def __init__(
        self,
        schema_name: str = "SYSCAT",
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
        for mod_name in ("ibm_db_dbi", "ibm_db"):
            try:
                driver = __import__(mod_name)
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'ibm_db' or 'ibm_db_dbi' is not installed. "
                "Install with: pip install 'query-builder-engine[db2]'"
            )

        try:
            self._connection = driver.connect(**self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(f"Failed to connect to IBM DB2: {exc}") from exc

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        with self.get_cursor() as cur:
            cur.execute("SELECT 1 FROM SYSIBM.SYSDUMMY1")
            cur.fetchone()
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "IBM DB2",
            "schema_name": self.schema_name,
            "latency_ms": round(latency_ms, 2),
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_db2(
                    cur,
                    schema_name=self.schema_name,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect IBM DB2 schema '{self.schema_name}': {exc}"
                ) from exc


IBMDB2Connector = DB2Connector


@register_connector("async_db2", aliases=["async_ibm_db2"])
class AsyncDB2Connector(AsyncBaseConnector):
    """Asynchronous connector for IBM DB2 enterprise database."""

    dialect_name = "db2"

    def __init__(
        self,
        schema_name: str = "SYSCAT",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.schema_name = schema_name

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("ibm_db_dbi", "ibm_db"):
            try:
                driver = __import__(mod_name)
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'ibm_db' or 'ibm_db_dbi' is not installed. "
                "Install with: pip install 'query-builder-engine[db2]'"
            )

        try:
            self._connection = driver.connect(**self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to IBM DB2: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
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
            cur.close()


AsyncIBMDB2Connector = AsyncDB2Connector
