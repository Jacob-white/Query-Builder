"""
DuckDB Embedded OLAP Connector.
===============================
Provides high-performance analytical query execution and Parquet/Iceberg exploration.
"""

from __future__ import annotations

import os
from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.introspection import introspect_duckdb


class DuckDBConnector(BaseConnector):
    """Connector for DuckDB embedded analytical databases."""

    dialect_name = "duckdb"
    # File databases are opened with read_only=True (enforced by the engine).  An
    # in-memory database or a caller-supplied connection cannot be flipped to read-only
    # after the fact, so for those the validator is the only barrier.
    read_only_support = "enforced"

    def apply_read_only(self, connection: Any) -> None:
        """No-op by design: DuckDB's access mode can only be chosen when the database is
        opened (``read_only=True`` in ``connect``) and cannot be changed on an open
        connection."""
        return None

    def __init__(
        self,
        database: str = ":memory:",
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
            import duckdb
        except ImportError as err:
            raise DriverNotInstalledError(
                "duckdb is not installed. Install with: pip install 'query-builder-engine[duckdb]'"
            ) from err

        try:
            kwargs = dict(self.config)
            if (
                self.security.execution.enforce_read_only_session
                and "read_only" not in kwargs
                and str(self.database) not in ("", ":memory:")
                and os.path.isfile(str(self.database))
            ):
                kwargs["read_only"] = True
            self._connection = duckdb.connect(self.database, **kwargs)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to DuckDB database '{self.database}': {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        with self.get_cursor() as cur:
            cur.execute("SELECT version();")
            ver_row = cur.fetchone()
            if ver_row:
                info["engine_version"] = ver_row[0]
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = self.connect()
        return introspect_duckdb(conn, filter_sensitive=filter_sensitive)
