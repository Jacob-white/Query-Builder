"""
Snowflake Cloud Data Warehouse Connector.
=========================================
Provides session-level query timeouts and metadata introspection.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.introspection import introspect_information_schema


class SnowflakeConnector(BaseConnector):
    """Connector for Snowflake Data Warehouse."""

    dialect_name = "snowflake"

    def __init__(
        self,
        connection: Any = None,
        cursor: Any = None,
        schema_name: str = "PUBLIC",
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.schema_name = schema_name

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            import snowflake.connector
        except ImportError as err:
            raise DriverNotInstalledError(
                "snowflake-connector-python is not installed. "
                "Install with: pip install 'query-builder-engine[snowflake]'"
            ) from err

        try:
            self._connection = snowflake.connector.connect(**self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Snowflake: {exc}"
            ) from exc

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        seconds = max(1, timeout_ms // 1000)
        cursor.execute(f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {seconds};")

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        with self.get_cursor() as cur:
            cur.execute("SELECT CURRENT_VERSION();")
            row = cur.fetchone()
            if row:
                info["engine_version"] = row[0]
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            snapshot = introspect_information_schema(
                cur, schema_name=self.schema_name, filter_sensitive=filter_sensitive
            )
            # Snowflake's INFORMATION_SCHEMA has no KEY_COLUMN_USAGE / CONSTRAINT_COLUMN_USAGE,
            # so key columns only come from the SHOW commands (the ANSI query cannot see them).
            self._overlay_keys(cur, snapshot)
            return snapshot

    def _show(self, cur: Any, statement: str) -> list[dict[str, Any]] | None:
        try:
            cur.execute(statement)
            names = [str(d[0]).lower() for d in (cur.description or [])]
            rows = cur.fetchall() or []
        except Exception:  # noqa: BLE001 - no privilege / unsupported: keep the ANSI result
            return None
        # duplicate names (e.g. two pk_column_name) keep the FIRST occurrence
        out = []
        for row in rows:
            rec: dict[str, Any] = {}
            for name, val in zip(names, row, strict=False):
                rec.setdefault(name, val)
            out.append(rec)
        return out

    def _overlay_keys(self, cur: Any, snapshot: dict[str, Any]) -> None:
        schema = str(self.schema_name).replace('"', "")
        tables = {t.lower(): t for t in snapshot.get("tables", {})}
        pks = self._show(cur, f'SHOW PRIMARY KEYS IN SCHEMA "{schema}"')
        if pks is not None:
            pk_cols = {
                (str(r["table_name"]).lower(), str(r["column_name"]).lower())
                for r in pks
                if "table_name" in r and "column_name" in r
            }
            for key, tname in tables.items():
                for col in snapshot["tables"][tname]["columns"]:
                    col["is_primary"] = (key, str(col["name"]).lower()) in pk_cols
        fks = self._show(cur, f'SHOW IMPORTED KEYS IN SCHEMA "{schema}"')
        if fks:
            snapshot["foreign_keys"] = []
            snapshot["relationships"] = []
            for r in fks:
                try:
                    src_t, src_c = str(r["fk_table_name"]), str(r["fk_column_name"])
                    tgt_t, tgt_c = str(r["pk_table_name"]), str(r["pk_column_name"])
                except KeyError:
                    continue
                snapshot["foreign_keys"].append(
                    {
                        "table": tables.get(src_t.lower(), src_t),
                        "column": src_c,
                        "foreign_table": tables.get(tgt_t.lower(), tgt_t),
                        "foreign_column": tgt_c,
                    }
                )
                snapshot["relationships"].append(
                    {
                        "source_table": tables.get(src_t.lower(), src_t),
                        "source_column": src_c,
                        "target_table": tables.get(tgt_t.lower(), tgt_t),
                        "target_column": tgt_c,
                    }
                )
