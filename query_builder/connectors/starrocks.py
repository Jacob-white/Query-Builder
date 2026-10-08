"""
StarRocks High-Performance Distributed MPP Analytical Database Connector.
========================================================================
Provides StarRocks vectorized query execution, query timeouts,
dual sync and async execution protocols, and schema introspection.
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
from query_builder.connectors.introspection import introspect_information_schema
from query_builder.connectors.registry import register_connector


@register_connector("starrocks")
class StarRocksConnector(BaseConnector):
    """Connector for StarRocks distributed MPP analytical database."""

    dialect_name = "starrocks"

    def __init__(
        self,
        host: str = "localhost",
        port: int = 9030,
        database: str = "default",
        user: str = "root",
        password: str = "",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.host = host
        self.port = port
        self.database = database
        self.schema_name = database
        self.user = user
        self.password = password
        self.config.setdefault("host", host)
        self.config.setdefault("port", port)
        self.config.setdefault("database", database)
        self.config.setdefault("user", user)
        self.config.setdefault("password", password)

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("starrocks", "pymysql", "MySQLdb"):
            try:
                driver = __import__(mod_name)
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "Neither 'starrocks' nor 'pymysql' is installed. "
                "Install with: pip install 'query-builder-engine[starrocks]'"
            )

        try:
            connect_kwargs = {
                "host": self.host,
                "port": self.port,
                "user": self.user,
                "password": self.password,
            }
            if "pymysql" in getattr(driver, "__name__", ""):
                connect_kwargs["database"] = self.database
            else:
                connect_kwargs["db"] = self.database
            cfg = {
                k: v
                for k, v in self.config.items()
                if k not in ("host", "port", "user", "password", "database", "db")
            }
            connect_kwargs.update(cfg)
            self._connection = driver.connect(**connect_kwargs)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to StarRocks at {self.host}:{self.port}: {exc}"
            ) from exc

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        timeout_sec = max(int(timeout_ms // 1000), 1)
        cursor.execute(f"SET query_timeout = {timeout_sec};")

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "StarRocks MPP Engine"
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_information_schema(
                    cur,
                    schema_name=self.database,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect StarRocks schema '{self.database}': {exc}"
                ) from exc


@register_connector("async_starrocks")
class AsyncStarRocksConnector(AsyncBaseConnector):
    """Asynchronous connector for StarRocks analytical database."""

    dialect_name = "starrocks"

    def __init__(
        self,
        host: str = "localhost",
        port: int = 9030,
        database: str = "default",
        user: str = "root",
        password: str = "",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.host = host
        self.port = port
        self.database = database
        self.schema_name = database
        self.user = user
        self.password = password
        self.config.setdefault("host", host)
        self.config.setdefault("port", port)
        self.config.setdefault("database", database)
        self.config.setdefault("user", user)
        self.config.setdefault("password", password)

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("pymysql", "starrocks"):
            try:
                driver = __import__(mod_name)
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "Neither 'starrocks' nor 'pymysql' is installed. "
                "Install with: pip install 'query-builder-engine[starrocks]'"
            )

        try:
            cfg = {
                k: v
                for k, v in self.config.items()
                if k not in ("host", "port", "user", "password", "database")
            }
            self._connection = driver.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                **cfg,
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to StarRocks: {exc}"
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
            col_names = [c[0] for c in desc]
            rows = cur.fetchall() or []
            dict_rows = [dict(zip(col_names, r, strict=False)) for r in rows]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms
        finally:
            cur.close()
