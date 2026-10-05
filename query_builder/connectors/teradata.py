"""
Teradata Enterprise Analytical Data Warehouse Connector.
========================================================
Provides Teradata SQL connectivity, statement execution, and schema introspection.
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


class TeradataConnector(BaseConnector):
    """Connector for Teradata enterprise analytical data warehouse."""

    dialect_name = "teradata"

    def __init__(
        self,
        host: str = "localhost",
        user: str = "dbc",
        password: str = "",
        database: str = "dbc",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.host = host
        self.user = user
        self.password = password
        self.database = database
        self.config.setdefault("host", host)
        self.config.setdefault("user", user)
        self.config.setdefault("password", password)
        self.config.setdefault("database", database)

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            import teradatasql
        except ImportError as err:
            raise DriverNotInstalledError(
                "teradatasql is not installed. "
                "Install with: pip install 'query-builder-engine[teradata]'"
            ) from err

        try:
            cfg = {
                k: v
                for k, v in self.config.items()
                if k not in ("host", "user", "password", "database")
            }
            self._connection = teradatasql.connect(
                host=self.host,
                user=self.user,
                password=self.password,
                database=self.database,
                **cfg,
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Teradata host '{self.host}': {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "Teradata"
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_information_schema(
                    cur,
                    schema_name=self.database,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Teradata schema '{self.database}': {exc}"
                ) from exc
