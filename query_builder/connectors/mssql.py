"""
Microsoft SQL Server Database Connector.
========================================
Provides lock timeout controls and schema introspection for SQL Server.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.introspection import introspect_information_schema


class MSSQLConnector(BaseConnector):
    """Connector for Microsoft SQL Server databases."""

    dialect_name = "mssql"

    def __init__(
        self,
        connection: Any = None,
        cursor: Any = None,
        schema_name: str = "dbo",
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.schema_name = schema_name

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("pymssql", "pyodbc"):
            try:
                driver = __import__(mod_name)
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "Neither 'pymssql' nor 'pyodbc' is installed. "
                "Install with: pip install 'query-builder-engine[mssql]'"
            )

        try:
            self._connection = driver.connect(**self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(f"Failed to connect to MSSQL: {exc}") from exc

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        cursor.execute(f"SET LOCK_TIMEOUT {int(timeout_ms)};")

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        with self.get_cursor() as cur:
            cur.execute("SELECT @@VERSION;")
            row = cur.fetchone()
            if row:
                info["engine_version"] = row[0]
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            return introspect_information_schema(
                cur, schema_name=self.schema_name, filter_sensitive=filter_sensitive
            )
