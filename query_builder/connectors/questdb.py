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
                names = sorted(
                    [str(r[0]) for r in cur.fetchall() if r and r[0] and not str(r[0]).startswith("telemetry")]
                )
                tables: dict[str, dict[str, Any]] = {}

                # Pre-initialize dictionary to preserve the exact alphabetical order and handle empty tables
                for name in names:
                    tables[name] = {
                        "name": name,
                        "columns": [],
                        "has_user_id": False,
                        "user_col": "user_id",
                        "comment": None,
                    }

                # Fetch columns in batches using UNION ALL to reduce roundtrips (N+1 query issue)
                batch_size = 50
                for i in range(0, len(names), batch_size):
                    batch_names = names[i : i + batch_size]

                    union_queries = []
                    for name in batch_names:
                        literal = name.replace("'", "''")
                        # Need to inject the original unescaped name as a literal to avoid double unescaping issues
                        # But wait, QuestDB returns exactly what we ask it to return in the SELECT.
                        # To be completely safe with single quotes in table names being unescaped correctly,
                        # let's just use the `literal` for the actual query, and let python keep track of the table name.
                        union_queries.append(
                            f"SELECT '{literal}' as table_name, \"column\", \"type\" FROM table_columns('{literal}')"
                        )

                    if union_queries:
                        batch_query = " UNION ALL ".join(union_queries)
                        cur.execute(batch_query)

                        for row in cur.fetchall():
                            # Re-evaluating how string literal works in QuestDB, the DB evaluates `'it''s'` and returns `it's`.
                            # Thus, row[0] is already unescaped. So we don't need `.replace("''", "'")`.
                            table_name = str(row[0])
                            col_name = str(row[1])
                            col_type = str(row[2])

                            tables[table_name]["columns"].append(
                                {
                                    "name": col_name,
                                    "data_type": col_type,
                                    "is_nullable": True,
                                    "is_primary": False,
                                    "comment": None,
                                }
                            )
                            if col_name == "user_id":
                                tables[table_name]["has_user_id"] = True

        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect QuestDB schema: {exc}"
            ) from exc
        return normalize_schema_snapshot(
            {"tables": tables, "foreign_keys": [], "relationships": []},
            filter_sensitive=filter_sensitive,
        )
