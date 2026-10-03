"""
PostgreSQL Database Connector.
==============================
Provides transactional execution, statement timeout configuration, and schema introspection.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.introspection import introspect_information_schema


class PostgresConnector(BaseConnector):
    """Connector for PostgreSQL databases."""

    dialect_name = "postgres"

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
            self._connection = driver.connect(**self.config)
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
