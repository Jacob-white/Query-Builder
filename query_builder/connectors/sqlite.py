"""
SQLite Database Connector.
==========================
Built-in connector using Python's standard library sqlite3 module.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from query_builder.connectors.base import BaseConnector, ConnectionFailedError
from query_builder.connectors.introspection import introspect_sqlite


class SQLiteConnector(BaseConnector):
    """Connector for SQLite databases using standard library sqlite3."""

    dialect_name = "sqlite"
    read_only_support = "enforced"

    def apply_read_only(self, connection: Any) -> None:
        """``PRAGMA query_only = ON``: the connection refuses every write and DDL."""
        connection.execute("PRAGMA query_only = ON")

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
            target, kwargs = self.database, dict(self.config)
            ro_uri = self._read_only_uri_applicable(kwargs)
            if ro_uri:
                # Open the file read-only at the VFS level as well (no creation, no write).
                target = Path(self.database).resolve().as_uri() + "?mode=ro"
                kwargs["uri"] = True
            try:
                self._connection = sqlite3.connect(target, **kwargs)
                if ro_uri:
                    self._connection.execute("PRAGMA query_only = ON")
                    self._connection.execute(
                        "SELECT 1 FROM sqlite_master LIMIT 1"
                    ).fetchall()
            except sqlite3.OperationalError:
                if self._connection is not None:
                    self._connection.close()
                    self._connection = None
                if ro_uri:
                    # Fallback for WAL-mode databases on read-only filesystem mounts without -shm
                    self._connection = sqlite3.connect(
                        f"{target}&immutable=1", **kwargs
                    )
                    self._connection.execute("PRAGMA query_only = ON")
                else:
                    raise
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to SQLite database '{self.database}': {exc}"
            ) from exc

    def _read_only_uri_applicable(self, kwargs: dict[str, Any]) -> bool:
        db = str(self.database)
        return bool(
            self.security.execution.enforce_read_only_session
            and not kwargs.get("uri")
            and db not in ("", ":memory:")
            and not db.startswith("file:")
            and os.path.isfile(db)
        )

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = sqlite3.sqlite_version
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            return introspect_sqlite(cur, filter_sensitive=filter_sensitive)
