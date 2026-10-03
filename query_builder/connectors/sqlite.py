"""
SQLite Database Connector.
==========================
Built-in connector using Python's standard library sqlite3 module.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from query_builder.connectors.base import BaseConnector, ConnectionFailedError
from query_builder.connectors.introspection import introspect_sqlite


class SQLiteConnector(BaseConnector):
    """Connector for SQLite databases using standard library sqlite3."""

    dialect_name = "sqlite"

    def __init__(
        self,
        database: str = ":memory:",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.database = database

    def connect(self) -> sqlite3.Connection:
        if self._connection is not None:
            return self._connection
        try:
            self._connection = sqlite3.connect(self.database, **self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to SQLite database '{self.database}': {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = sqlite3.sqlite_version
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            return introspect_sqlite(cur, filter_sensitive=filter_sensitive)
