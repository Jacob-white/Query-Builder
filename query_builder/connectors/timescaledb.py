"""
TimescaleDB Time-Series Database Connector.
==========================================
Extends PostgreSQL connector with hypertable awareness and time-series optimizations.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.postgres import PostgresConnector


class TimescaleConnector(PostgresConnector):
    """Connector for TimescaleDB time-series databases."""

    dialect_name = "timescaledb"

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        with self.get_cursor() as cur:
            cur.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb';"
            )
            row = cur.fetchone()
            if row:
                info["timescale_version"] = row[0]
        return info
