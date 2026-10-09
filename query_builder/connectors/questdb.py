"""
QuestDB High-Performance Time-Series Database Connector.
=======================================================
Provides PostgreSQL wire protocol compatibility and time-series query execution.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import IntrospectionError
from query_builder.connectors.postgres import PostgresConnector
from query_builder.schema import normalize_schema_snapshot


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

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        """
        QuestDB's pg-wire ``information_schema`` is incomplete (no ``is_nullable``),
        so tables and columns come from its own ``tables()`` / ``table_columns()``
        catalog functions. QuestDB has no primary or foreign keys.
        """
        try:
            with self.get_cursor() as cur:
                cur.execute("SELECT table_name FROM tables()")
                names = [str(r[0]) for r in cur.fetchall() if r and r[0]]
                tables: dict[str, dict[str, Any]] = {}
                for name in sorted(names):
                    if name.startswith("telemetry"):  # QuestDB internal tables
                        continue
                    literal = name.replace("'", "''")
                    cur.execute(
                        f'SELECT "column", "type" FROM table_columns(\'{literal}\')'
                    )
                    cols = [
                        {
                            "name": str(c[0]),
                            "data_type": str(c[1]),
                            "is_nullable": True,
                            "is_primary": False,
                            "comment": None,
                        }
                        for c in cur.fetchall()
                    ]
                    tables[name] = {
                        "name": name,
                        "columns": cols,
                        "has_user_id": any(c["name"] == "user_id" for c in cols),
                        "user_col": "user_id",
                        "comment": None,
                    }
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect QuestDB schema: {exc}"
            ) from exc
        return normalize_schema_snapshot(
            {"tables": tables, "foreign_keys": [], "relationships": []},
            filter_sensitive=filter_sensitive,
        )
