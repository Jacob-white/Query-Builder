"""
QuestDB High-Performance Time-Series Database Connector.
=======================================================
Provides PostgreSQL wire protocol compatibility and time-series query execution.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.postgres import PostgresConnector


class QuestDBConnector(PostgresConnector):
    """Connector for QuestDB time-series database."""

    dialect_name = "questdb"
    # No documented session-level read-only mode for this engine: rely on a read-only role.
    read_only_support = "none"

    def apply_read_only(self, connection: Any) -> None:
        return None

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "QuestDB"
        return info
