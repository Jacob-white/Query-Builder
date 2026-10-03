"""
SingleStore / MemSQL Distributed SQL Database Connector.
========================================================
Provides distributed in-memory and disk database connectivity,
session timeout isolation, and schema introspection.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.mysql import MySQLConnector


class SingleStoreConnector(MySQLConnector):
    """Connector for SingleStore / MemSQL distributed SQL database."""

    dialect_name = "singlestore"

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("singlestoredb", "MySQLdb", "pymysql"):
            try:
                driver = __import__(mod_name)
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "Neither 'singlestoredb' nor 'mysqlclient'/'pymysql' is installed. "
                "Install with: pip install 'query-builder-engine[singlestore]'"
            )

        try:
            if "singlestoredb" in getattr(driver, "__name__", ""):
                self._connection = driver.connect(database=self.database, **self.config)
            else:
                self._connection = driver.connect(db=self.database, **self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to SingleStore database '{self.database}': {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "SingleStore"
        return info


MemSQLConnector = SingleStoreConnector
