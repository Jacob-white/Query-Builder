"""
ClickHouse Real-Time Analytical Database Connector.
===================================================
Provides fast analytical query execution, execution timeout limits, and system catalog introspection.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterator
from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.introspection import introspect_clickhouse

_SET_RE = re.compile(r"^\s*SET\s+(\w+)\s*=\s*(.+?)\s*;?\s*$", re.IGNORECASE | re.DOTALL)
_ROW_RETURNING = ("select", "with", "show", "describe", "desc", "explain", "exists")


class ClickHouseCursor:
    """
    Minimal DB-API style cursor over a ``clickhouse-connect`` client.

    ``clickhouse_connect`` clients expose ``query()``/``command()`` rather than
    ``cursor()``/``execute()``, so the generic connector machinery (which drives
    DB-API cursors) needs this adapter. ``SET name = value`` statements are kept
    client-side and sent as per-query settings, which makes the statement timeout
    independent of HTTP session handling.
    """

    def __init__(self, client: Any) -> None:
        self._client = client
        # join_use_nulls: without it ClickHouse fills unmatched OUTER JOIN columns
        # with type defaults ('' / 0) instead of SQL NULL, silently corrupting
        # LEFT/RIGHT/FULL join results.
        self._settings: dict[str, Any] = {"join_use_nulls": 1}
        self._rows: list[Any] = []
        self._pos = 0
        self.description: list[tuple[Any, ...]] | None = None
        self.rowcount = -1

    def execute(self, sql: str, params: Any = None) -> ClickHouseCursor:
        self._rows, self._pos, self.description = [], 0, None
        match = _SET_RE.match(sql)
        if match:
            raw = match.group(2).strip("'\"")
            self._settings[match.group(1)] = int(raw) if raw.isdigit() else raw
            return self
        words = sql.lstrip().lstrip("(").split(None, 1)
        first = words[0].lower() if words else ""
        settings = dict(self._settings) or None
        if first in _ROW_RETURNING:
            result = self._client.query(
                sql, parameters=params or None, settings=settings
            )
            self.description = [(name, None) for name in result.column_names]
            self._rows = list(result.result_rows)
            self.rowcount = len(self._rows)
        else:
            self._client.command(sql, parameters=params or None, settings=settings)
        return self

    def fetchall(self) -> list[Any]:
        rows, self._pos = self._rows[self._pos :], len(self._rows)
        return rows

    def fetchone(self) -> Any:
        if self._pos >= len(self._rows):
            return None
        self._pos += 1
        return self._rows[self._pos - 1]

    def close(self) -> None:
        self._rows = []


class ClickHouseConnector(BaseConnector):
    """Connector for ClickHouse columnar database."""

    dialect_name = "clickhouse"
    read_only_support = "enforced"

    def apply_read_only(self, connection: Any) -> None:
        """``readonly = 2``: no writes/DDL, and the ``readonly`` setting itself cannot be
        changed, but per-query settings (the statement timeout) remain adjustable.
        ``readonly = 1`` would reject the connector's own ``SET max_execution_time``."""
        setter = getattr(connection, "set_client_setting", None)
        if setter is not None:
            setter("readonly", 2)
        else:
            connection.command("SET readonly = 2")

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

        try:
            import clickhouse_connect
        except ImportError as err:
            raise DriverNotInstalledError(
                "clickhouse-connect is not installed. "
                "Install with: pip install 'query-builder-engine[clickhouse]'"
            ) from err

        try:
            client = clickhouse_connect.get_client(
                database=self.database, **self.config
            )
            self._connection = client
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to ClickHouse: {exc}"
            ) from exc

    @contextlib.contextmanager
    def get_cursor(self) -> Iterator[Any]:
        """Yield a DB-API cursor; wraps clickhouse-connect clients (no cursor())."""
        if self._cursor is None:
            conn = self.connect()
            if not hasattr(conn, "cursor") and hasattr(conn, "query"):
                yield ClickHouseCursor(conn)
                return
        with super().get_cursor() as cur:
            yield cur

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        seconds = max(1, timeout_ms // 1000)
        cursor.execute(f"SET max_execution_time = {seconds};")

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        with self.get_cursor() as cur:
            cur.execute("SELECT version();")
            row = cur.fetchone()
            if row:
                info["engine_version"] = row[0]
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            return introspect_clickhouse(
                cur, database=self.database, filter_sensitive=filter_sensitive
            )
