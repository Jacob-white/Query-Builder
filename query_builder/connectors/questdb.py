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

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "QuestDB"
        return info
