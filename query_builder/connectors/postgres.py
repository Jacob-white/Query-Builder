"""
PostgreSQL Database Connector.
==============================
Provides transactional execution, statement timeout configuration, and schema introspection.
"""

from __future__ import annotations

import contextlib
from typing import Any

from query_builder.connectors._txn import RollbackOnErrorMixin
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.introspection import introspect_information_schema


def _pg_read_only(connection: Any) -> None:
    """``SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`` + commit.

    The SET itself opens a (read-write) transaction under non-autocommit drivers, and a
    session default only applies to the NEXT transaction, so it is committed immediately.
    """
    cur = connection.cursor()
    try:
        cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
    finally:
        close = getattr(cur, "close", None)
        if close is not None:
            # a failing close must not skip the commit below (it would leave the
            # session-default SET inside an open read-write transaction)
            with contextlib.suppress(Exception):
                close()
    commit = getattr(connection, "commit", None)
    if commit is not None:
        commit()


class PostgresConnector(RollbackOnErrorMixin, BaseConnector):
    """Connector for PostgreSQL databases."""

    dialect_name = "postgres"
    read_only_support = "enforced"

    def apply_read_only(self, connection: Any) -> None:
        """Session default READ ONLY: every later transaction refuses writes/DDL."""
        _pg_read_only(connection)

    def __init__(
        self,
        connection: Any = None,
        cursor: Any = None,
        schema_name: str = "public",
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.schema_name = schema_name

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("psycopg", "psycopg2"):
            try:
                driver = __import__(mod_name)
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "Neither 'psycopg' nor 'psycopg2' is installed. "
                "Install with: pip install 'query-builder-engine[postgres]'"
            )

        try:
            # `hostaddr` pins the already-validated address (no DNS at connect time);
            # `host` stays the name for TLS verification.
            self._connection = driver.connect(**self.pinned_connect_config())
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to PostgreSQL: {exc}"
            ) from exc

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        cursor.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)};")

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
            return introspect_information_schema(
                cur, schema_name=self.schema_name, filter_sensitive=filter_sensitive
            )
