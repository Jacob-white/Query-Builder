"""
Apache Kyuubi Multi-Tenant Enterprise Query Gateway Connector.
=============================================================
Provides Apache Kyuubi connectivity via HiveServer2 protocols (pyhive / kyuubi / thrift),
dual sync and async execution protocols, statement isolation, and catalog introspection.
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
from query_builder.connectors.introspection import introspect_kyuubi
from query_builder.connectors.registry import register_connector


def _has_attr(target: Any, attr: str) -> bool:
    if hasattr(target, "_mock_children"):
        if getattr(target, "_mock_methods", None) is not None:
            return hasattr(target, attr)
        return attr in target._mock_children
    return hasattr(target, attr)


class _KyuubiCursorAdapter:
    """Adapts a Kyuubi connection or cursor into a DB-API cursor interface."""

    def __init__(self, client_or_cursor: Any) -> None:
        self.target = client_or_cursor
        self.description: list[tuple[str]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip()
        if _has_attr(self.target, "cursor") and not _has_attr(self.target, "fetchall"):
            cur = self.target.cursor()
            try:
                if params:
                    cur.execute(clean_sql, params)
                else:
                    cur.execute(clean_sql)
                self.description = getattr(cur, "description", None)
                self._rows = list(cur.fetchall()) if hasattr(cur, "fetchall") else []
            finally:
                with contextlib.suppress(Exception):
                    cur.close()
        elif hasattr(self.target, "execute"):
            if params:
                self.target.execute(clean_sql, params)
            else:
                self.target.execute(clean_sql)
            self.description = getattr(self.target, "description", None)
            self._rows = (
                list(self.target.fetchall()) if hasattr(self.target, "fetchall") else []
            )
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


@register_connector("kyuubi", aliases=["apache_kyuubi"])
class KyuubiConnector(BaseConnector):
    """Connector for Apache Kyuubi enterprise multi-tenant query gateway."""

    dialect_name = "kyuubi"

    def __init__(
        self,
        database: str = "default",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.database = database

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("kyuubi", "pyhive.hive", "impala.dbapi"):
            try:
                driver = __import__(mod_name, fromlist=["connect"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'kyuubi' or 'pyhive' is not installed. "
                "Install with: pip install 'query-builder-engine[kyuubi]'"
            )

        try:
            self._connection = driver.connect(database=self.database, **self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Apache Kyuubi Gateway: {exc}"
            ) from exc

    @contextlib.contextmanager
    def get_cursor(self) -> Any:
        if self._cursor is not None:
            yield _KyuubiCursorAdapter(self._cursor)
            return

        conn = self.connect()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
            try:
                yield _KyuubiCursorAdapter(cur)
            finally:
                if hasattr(cur, "close"):
                    with contextlib.suppress(Exception):
                        cur.close()
        else:
            yield _KyuubiCursorAdapter(conn)

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        with contextlib.suppress(Exception):
            cursor.execute(f"SET kyuubi.operation.timeout = {timeout_ms};")

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
                info["engine_version"] = f"Apache Kyuubi {ver}".strip()
        info["database"] = self.database
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_kyuubi(
                    cur,
                    database=self.database,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Apache Kyuubi database '{self.database}': {exc}"
                ) from exc


ApacheKyuubiConnector = KyuubiConnector


@register_connector("async_kyuubi", aliases=["async_apache_kyuubi"])
class AsyncKyuubiConnector(AsyncBaseConnector):
    """Asynchronous connector for Apache Kyuubi query gateway."""

    dialect_name = "kyuubi"

    def __init__(
        self,
        database: str = "default",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.database = database

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("kyuubi", "pyhive.hive", "impala.dbapi"):
            try:
                driver = __import__(mod_name, fromlist=["connect"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'kyuubi' or 'pyhive' is not installed. "
                "Install with: pip install 'query-builder-engine[kyuubi]'"
            )

        try:
            self._connection = driver.connect(database=self.database, **self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Apache Kyuubi: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        adapter = _KyuubiCursorAdapter(conn)
        adapter.execute(sql, params)
        desc = adapter.description or []
        col_names = [col[0] for col in desc]
        rows = adapter.fetchall() or []
        dict_rows = [dict(zip(col_names, r)) for r in rows]
        latency_ms = (time.perf_counter() - start) * 1000.0
        return col_names, dict_rows, latency_ms

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        adapter = _KyuubiCursorAdapter(conn)
        try:
            return introspect_kyuubi(
                adapter, database=self.database, filter_sensitive=filter_sensitive
            )
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Apache Kyuubi database '{self.database}': {exc}"
            ) from exc


AsyncApacheKyuubiConnector = AsyncKyuubiConnector
