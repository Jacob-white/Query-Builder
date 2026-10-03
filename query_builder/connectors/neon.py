"""
Neon Serverless Postgres Connector.
===================================
Extends PostgreSQL connector with branch, endpoint, and serverless compute awareness.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.postgres import PostgresConnector


class NeonConnector(PostgresConnector):
    """Connector for Neon Serverless PostgreSQL with branch and endpoint awareness."""

    dialect_name = "neon"

    def __init__(
        self,
        connection: Any = None,
        cursor: Any = None,
        schema_name: str = "public",
        branch_id: str | None = None,
        endpoint_id: str | None = None,
        **config: Any,
    ) -> None:
        super().__init__(
            connection=connection,
            cursor=cursor,
            schema_name=schema_name,
            **config,
        )
        self.branch_id = branch_id
        self.endpoint_id = endpoint_id

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "Neon Serverless Postgres"
        if self.branch_id:
            info["neon_branch"] = self.branch_id
        if self.endpoint_id:
            info["neon_endpoint"] = self.endpoint_id
        return info

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        cursor.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)};")
