"""
MySQL / MariaDB Database Connector.
===================================
Provides session timeout management and information_schema introspection.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors._txn import RollbackOnErrorMixin
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.introspection import introspect_information_schema


class MySQLConnector(RollbackOnErrorMixin, BaseConnector):
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
        # MySQL: max_execution_time (ms, SELECT only). MariaDB has no such variable
        # ("Unknown system variable", error 1193) and uses max_statement_time
        # (seconds, all statements) instead.
        if not getattr(self, "_is_mariadb", False):
            try:
                cursor.execute(f"SET SESSION max_execution_time = {int(timeout_ms)};")
                return
            except Exception as exc:
                if "max_execution_time" not in str(exc):
                    raise
                self._is_mariadb = True
        cursor.execute(f"SET SESSION max_statement_time = {int(timeout_ms) / 1000};")

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
                cur,
                schema_name=self.database,
                filter_sensitive=filter_sensitive,
                fk_style="mysql",
            )
