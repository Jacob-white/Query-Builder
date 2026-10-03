"""
TiDB Distributed HTAP Database Connector.
=========================================
Extends MySQL connector with TiDB distributed HTAP cluster awareness and version telemetry.
"""

from __future__ import annotations

import contextlib
from typing import Any

from query_builder.connectors.mysql import MySQLConnector


class TiDBConnector(MySQLConnector):
    """Connector for TiDB distributed HTAP MySQL-compatible database."""

    dialect_name = "tidb"

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "TiDB HTAP"
        with contextlib.suppress(Exception), self.get_cursor() as cur:
            cur.execute("SELECT tidb_version();")
            row = cur.fetchone()
            if row and row[0]:
                info["tidb_version"] = row[0]
        return info
