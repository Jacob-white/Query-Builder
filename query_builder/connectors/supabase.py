"""
Supabase Managed PostgreSQL Database Connector.
===============================================
Extends PostgreSQL connector with Supabase project URL and key configuration.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.postgres import PostgresConnector


class SupabaseConnector(PostgresConnector):
    """Connector for Supabase Managed PostgreSQL."""

    dialect_name = "supabase"

    def __init__(
        self,
        connection: Any = None,
        cursor: Any = None,
        schema_name: str = "public",
        supabase_url: str | None = None,
        supabase_key: str | None = None,
        **config: Any,
    ) -> None:
        super().__init__(
            connection=connection,
            cursor=cursor,
            schema_name=schema_name,
            **config,
        )
        self.supabase_url = supabase_url
        self.supabase_key = supabase_key

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
                "Install with: pip install 'query-builder-engine[supabase]'"
            )

        try:
            self._connection = driver.connect(**self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Supabase PostgreSQL: {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "Supabase Managed PostgreSQL"
        if self.supabase_url:
            info["supabase_url"] = self.supabase_url
        return info

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        cursor.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)};")
