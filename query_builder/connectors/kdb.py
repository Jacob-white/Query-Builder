"""
Kdb+ Ultra-High Performance Financial Vector and Time-Series Connector via PyKX.
=================================================================================
Provides Kdb+ connectivity via PyKX / qPython, dual sync and async execution protocols,
vector cursor adaptation, and q schema introspection.
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
from query_builder.connectors.introspection import introspect_kdb
from query_builder.connectors.registry import register_connector


def _has_attr(target: Any, attr: str) -> bool:
    if hasattr(target, "_mock_children"):
        if getattr(target, "_mock_methods", None) is not None:
            return hasattr(target, attr)
        return attr in target._mock_children
    return hasattr(target, attr)


class _KdbCursorAdapter:
    """Adapts a PyKX or q connection into a DB-API cursor interface."""

    def __init__(self, client_or_cursor: Any) -> None:
        self.target = client_or_cursor
        self.description: list[tuple[str]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean = sql.strip().rstrip(";").strip()
        if _has_attr(self.target, "sendSync"):
            # qpython
            clean_q = (
                "1"
                if clean.upper() in ("SELECT 1", "SELECT 1;", "SELECT 1 FROM DUAL")
                else clean
            )
            res = self.target.sendSync(clean_q)
            if hasattr(res, "meta"):
                self.description = [(str(c),) for c in res.meta.columns]
                self._rows = [list(r) for r in res]
            elif isinstance(res, (list, tuple)):
                self.description = [("val",)]
                self._rows = [[r] for r in res]
            else:
                self.description = [("val",)]
                self._rows = [[res]]
        elif _has_attr(self.target, "cursor") and not _has_attr(
            self.target, "fetchall"
        ):
            cur = self.target.cursor()
            try:
                if params:
                    cur.execute(clean, params)
                else:
                    cur.execute(clean)
                self.description = getattr(cur, "description", None)
                self._rows = list(cur.fetchall()) if hasattr(cur, "fetchall") else []
            finally:
                with contextlib.suppress(Exception):
                    cur.close()
        elif (
            _has_attr(self.target, "q") and getattr(self.target, "q", None) is not None
        ):
            # pykx.q.sql or pykx.q
            res = None
            if _has_attr(self.target.q, "sql"):
                with contextlib.suppress(Exception):
                    res = self.target.q.sql(clean)
            if res is None and callable(self.target.q):
                res = self.target.q(clean)
            if hasattr(res, "columns"):
                self.description = [(str(c),) for c in res.columns]
            elif hasattr(res, "keys"):
                self.description = [(str(k),) for k in res]
            else:
                self.description = [("val",)]
            if hasattr(res, "pd"):
                df = res.pd()
                self._rows = [list(row) for _, row in df.iterrows()]
            elif hasattr(res, "py"):
                val = res.py()
                self._rows = [list(val)] if isinstance(val, (list, tuple)) else [[val]]
            else:
                self._rows = []
        elif _has_attr(self.target, "execute") or _has_attr(self.target, "fetchall"):
            if params:
                self.target.execute(clean, params)
            else:
                self.target.execute(clean)
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


@register_connector("kdb", aliases=["kdb+", "pykx", "q"])
class KdbConnector(BaseConnector):
    """Connector for Kdb+ financial vector and time-series database."""

    dialect_name = "kdb"

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5001,
        database: str = "default",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.host = host
        self.port = port
        self.database = database
        self.config.setdefault("host", host)
        self.config.setdefault("port", port)
        self.config.setdefault("database", database)

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("pykx", "qpython.qconnection", "qpython"):
            try:
                driver = __import__(
                    mod_name, fromlist=["QConnection", "SyncQConnection"]
                )
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'pykx' or 'qpython' is not installed. "
                "Install with: pip install 'query-builder-engine[kdb]'"
            )

        try:
            cfg = {
                k: v
                for k, v in self.config.items()
                if k not in ("host", "port", "database")
            }
            if hasattr(driver, "QConnection"):
                conn = driver.QConnection(host=self.host, port=self.port, **cfg)
                if hasattr(conn, "open"):
                    conn.open()
                self._connection = conn
            elif hasattr(driver, "SyncQConnection"):
                conn = driver.SyncQConnection(self.host, self.port, **cfg)
                if hasattr(conn, "open"):
                    conn.open()
                self._connection = conn
            elif hasattr(driver, "q"):
                self._connection = driver
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(f"Failed to connect to Kdb+: {exc}") from exc

    @contextlib.contextmanager
    def get_cursor(self) -> Any:
        if self._cursor is not None:
            yield _KdbCursorAdapter(self._cursor)
            return

        conn = self.connect()
        yield _KdbCursorAdapter(conn)

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        pass

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        with self.get_cursor() as cur, contextlib.suppress(Exception):
            cur.execute(".z.K")
            rows = cur.fetchall() if hasattr(cur, "fetchall") else []
            if rows and len(rows) > 0 and len(rows[0]) > 0 and rows[0][0]:
                info["engine_version"] = f"kdb+ {rows[0][0]}".strip()
        info["database"] = self.database
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            conn = getattr(cur, "target", cur)
            try:
                return introspect_kdb(conn, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Kdb+ database '{self.database}': {exc}"
                ) from exc


PyKXConnector = KdbConnector


@register_connector("async_kdb", aliases=["async_kdb+", "async_pykx"])
class AsyncKdbConnector(AsyncBaseConnector):
    """Asynchronous connector for Kdb+ time-series database."""

    dialect_name = "kdb"

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5001,
        database: str = "default",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.host = host
        self.port = port
        self.database = database
        self.config.setdefault("host", host)
        self.config.setdefault("port", port)
        self.config.setdefault("database", database)

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("pykx", "qpython.qconnection", "qpython"):
            try:
                driver = __import__(
                    mod_name, fromlist=["QConnection", "SyncQConnection"]
                )
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'pykx' or 'qpython' is not installed. "
                "Install with: pip install 'query-builder-engine[kdb]'"
            )

        try:
            cfg = {
                k: v
                for k, v in self.config.items()
                if k not in ("host", "port", "database")
            }
            if hasattr(driver, "SyncQConnection"):
                conn = driver.SyncQConnection(self.host, self.port, **cfg)
                conn.open()
                self._connection = conn
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Kdb+: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        adapter = _KdbCursorAdapter(conn)
        try:
            adapter.execute(sql, params)
            desc = adapter.description or []
            col_names = [col[0] for col in desc]
            rows = adapter.fetchall() or []
            dict_rows = [dict(zip(col_names, r)) for r in rows]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms
        finally:
            adapter.close()

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        try:
            return introspect_kdb(conn, filter_sensitive=filter_sensitive)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Kdb+ database '{self.database}': {exc}"
            ) from exc


AsyncPyKXConnector = AsyncKdbConnector
