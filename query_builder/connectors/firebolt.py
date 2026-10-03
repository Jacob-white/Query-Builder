"""
Firebolt Ultra-Low Latency Cloud Data Warehouse Connector.
==========================================================
Provides Firebolt DB-API connectivity, session management, and schema introspection.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_information_schema


class FireboltConnector(BaseConnector):
    """Connector for Firebolt ultra-low latency cloud data warehouse."""

    dialect_name = "firebolt"

    def __init__(
        self,
        database: str = "default_db",
        engine_name: str | None = None,
        account_name: str | None = None,
        schema_name: str = "public",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.database = database
        self.engine_name = engine_name
        self.account_name = account_name
        self.schema_name = schema_name

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            from firebolt import db as firebolt_db
        except ImportError as err:
            raise DriverNotInstalledError(
                "firebolt-sdk is not installed. "
                "Install with: pip install 'query-builder-engine[firebolt]'"
            ) from err

        try:
            self._connection = firebolt_db.connect(
                database=self.database,
                engine_name=self.engine_name,
                account_name=self.account_name,
                **self.config,
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Firebolt database '{self.database}': {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "Firebolt Cloud Data Warehouse"
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_information_schema(
                    cur,
                    schema_name=self.schema_name,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Firebolt schema '{self.schema_name}': {exc}"
                ) from exc
