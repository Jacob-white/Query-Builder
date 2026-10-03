"""
CockroachDB Distributed SQL Connector.
======================================
Extends PostgreSQL connector with distributed cluster features and CockroachDB settings.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.postgres import PostgresConnector


class CockroachConnector(PostgresConnector):
    """Connector for CockroachDB distributed SQL clusters."""

    dialect_name = "cockroachdb"

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        cursor.execute(f"SET statement_timeout = '{int(timeout_ms)}ms';")
