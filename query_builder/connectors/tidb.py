"""
TiDB Distributed HTAP Database Connector.
=========================================
Extends MySQL connector with TiDB distributed HTAP cluster awareness and version telemetry.
"""

from __future__ import annotations

import contextlib
from typing import Any

from query_builder.connectors.base import (
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.mysql import MySQLConnector


class TiDBConnector(MySQLConnector):
    """Connector for TiDB distributed HTAP MySQL-compatible database."""

    dialect_name = "tidb"

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("pymysql", "MySQLdb"):
            try:
                driver = __import__(mod_name)
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "Neither 'pymysql' nor 'mysqlclient' (MySQLdb) is installed. "
                "Install with: pip install 'query-builder-engine[tidb]'"
            )

        try:
            self._connection = driver.connect(db=self.database, **self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to TiDB database '{self.database}': {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "TiDB HTAP"
        with contextlib.suppress(Exception), self.get_cursor() as cur:
            cur.execute("SELECT tidb_version();")
            row = cur.fetchone()
            if row and row[0]:
                info["tidb_version"] = row[0]
        return info
