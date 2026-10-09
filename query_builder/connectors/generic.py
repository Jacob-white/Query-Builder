"""
Generic DB-API 2.0 Database Connector.
======================================
Universal connector accepting any active DB-API 2.0 connection or cursor
and configurable with any registered SQL dialect.
"""

from __future__ import annotations

import contextlib
import sys
from typing import Any

from query_builder.connectors.base import BaseConnector, ConnectionFailedError
from query_builder.connectors.introspection import (
    introspect_duckdb,
    introspect_information_schema,
    introspect_sqlite,
    introspect_via_sqlalchemy,
)
from query_builder.dialects import BaseDialect


class GenericDBAPIConnector(BaseConnector):
    """Universal connector for any DB-API 2.0 cursor or connection."""

    def __init__(
        self,
        connection: Any = None,
        cursor: Any = None,
        dialect: str | BaseDialect = "postgres",
        engine: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(
            connection=connection, cursor=cursor, dialect=dialect, **config
        )
        self.engine = engine

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection
        if self._cursor is not None:
            return self._cursor
        if self.engine is not None:
            try:
                self._connection = self.engine.raw_connection()
                return self._connection
            except Exception as exc:
                raise ConnectionFailedError(
                    f"Failed to obtain raw connection from engine: {exc}"
                ) from exc

        raise ConnectionFailedError(
            "GenericDBAPIConnector requires an explicit connection, cursor, or engine."
        )

    @contextlib.contextmanager
    def get_cursor(self) -> Any:
        """Cursor that rolls back after a failed statement.

        DB-API connections are non-autocommit by default; on PostgreSQL-style engines one
        failed statement otherwise leaves the transaction aborted and EVERY later query on
        the connection fails ("current transaction is aborted").
        """
        try:
            with super().get_cursor() as cur:
                yield cur
        except Exception:
            conn = self._connection
            if conn is not None and hasattr(conn, "rollback"):
                with contextlib.suppress(Exception):
                    conn.rollback()
            raise

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        version = self._probe_engine_version()
        if version:
            info["engine_version"] = version
        return info

    def _probe_engine_version(self) -> str | None:
        """Best-effort engine version; never raises and never leaves a failed transaction."""
        probe = (
            "SELECT sqlite_version()"
            if self.dialect_name in ("sqlite", "sqlite3", "d1")
            else "SELECT version()"
        )
        with contextlib.suppress(Exception), self.get_cursor() as cur:
            try:
                cur.execute(probe)
                row = cur.fetchone()
                if row and row[0]:
                    return str(row[0])
            except Exception:  # noqa: BLE001 - engine has no such function
                conn = self._connection
                if conn is not None and hasattr(conn, "rollback"):
                    with contextlib.suppress(Exception):
                        conn.rollback()
        # fall back to the DB-API driver module's own version
        root = type(self._connection).__module__.split(".")[0] if self._connection else ""
        ver = getattr(sys.modules.get(root), "__version__", None)
        return f"{root} {ver}" if root and isinstance(ver, str) else (root or None)

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        if self.engine is not None:
            return introspect_via_sqlalchemy(
                self.engine, filter_sensitive=filter_sensitive
            )

        # information_schema SQL uses the server-style ``%s`` marker, which embedded DB-API
        # drivers (sqlite3, duckdb) reject: use the catalog readers made for those engines.
        if self.dialect_name in ("sqlite", "sqlite3", "d1"):
            with self.get_cursor() as cur:
                return introspect_sqlite(cur, filter_sensitive=filter_sensitive)
        if self.dialect_name == "duckdb":
            return introspect_duckdb(self.connect(), filter_sensitive=filter_sensitive)

        schema_name = self.config.get("schema_name") or "public"
        with self.get_cursor() as cur:
            return introspect_information_schema(
                cur,
                schema_name=schema_name,
                filter_sensitive=filter_sensitive,
                placeholder=self.dialect.placeholder,
            )
