"""
MySQL / MariaDB Database Connector.
===================================
Provides session timeout management and information_schema introspection.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.introspection import introspect_information_schema


class MySQLConnector(BaseConnector):
    """Connector for MySQL and MariaDB databases."""

    dialect_name = "mysql"

    def __init__(
        self,
        connection: Any = None,
        cursor: Any = None,
        database: str = "mysql",
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.database = database

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("MySQLdb", "pymysql"):
            try:
                driver = __import__(mod_name)
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "Neither 'mysqlclient' (MySQLdb) nor 'pymysql' is installed. "
                "Install with: pip install 'query-builder-engine[mysql]'"
            )

        try:
            self._connection = driver.connect(db=self.database, **self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to MySQL database '{self.database}': {exc}"
            ) from exc

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        cursor.execute(f"SET SESSION max_execution_time = {int(timeout_ms)};")

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        with self.get_cursor() as cur:
            cur.execute("SELECT VERSION();")
            row = cur.fetchone()
            if row:
                info["engine_version"] = row[0]
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            return introspect_information_schema(
                cur, schema_name=self.database, filter_sensitive=filter_sensitive
            )
