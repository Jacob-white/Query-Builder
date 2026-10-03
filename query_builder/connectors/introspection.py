"""
Universal and Engine-Specific Schema Introspection Protocols.
=============================================================
Provides automated reverse-engineering of tables, columns, primary keys,
and foreign key relationships across supported SQL database engines.
"""

from __future__ import annotations

import contextlib
from typing import Any

from query_builder.connectors.base import DriverNotInstalledError, IntrospectionError
from query_builder.schema import normalize_schema_snapshot


def introspect_sqlite(cursor: Any, filter_sensitive: bool = True) -> dict[str, Any]:
    """
    Introspects SQLite schema using sqlite_master, PRAGMA table_info,
    and PRAGMA foreign_key_list.
    """
    try:
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
        )
        table_rows = cursor.fetchall()
        table_names = [r[0] for r in table_rows if r and r[0]]

        tables: dict[str, dict[str, Any]] = {}
        foreign_keys: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []

        for tbl in table_names:
            # Table columns
            cursor.execute(f'PRAGMA table_info("{tbl}");')
            cols_meta = cursor.fetchall()
            cols: list[dict[str, Any]] = []
            has_user = False

            for c in cols_meta:
                # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
                col_name = str(c[1])
                data_type = str(c[2]) if c[2] else "text"
                is_nullable = not bool(c[3])
                is_pk = bool(c[5])
                if col_name == "user_id":
                    has_user = True

                cols.append(
                    {
                        "name": col_name,
                        "data_type": data_type,
                        "is_nullable": is_nullable,
                        "is_primary": is_pk,
                        "comment": None,
                    }
                )

            tables[tbl] = {
                "name": tbl,
                "columns": cols,
                "has_user_id": has_user,
                "user_col": "user_id",
                "comment": None,
            }

            # Foreign keys
            cursor.execute(f'PRAGMA foreign_key_list("{tbl}");')
            fk_rows = cursor.fetchall()
            for fk in fk_rows:
                # id, seq, table, from, to, on_update, on_delete, match
                target_table = str(fk[2])
                from_col = str(fk[3])
                to_col = str(fk[4]) if fk[4] else "id"

                foreign_keys.append(
                    {
                        "table": tbl,
                        "column": from_col,
                        "foreign_table": target_table,
                        "foreign_column": to_col,
                    }
                )
                relationships.append(
                    {
                        "source_table": tbl,
                        "source_column": from_col,
                        "target_table": target_table,
                        "target_column": to_col,
                    }
                )

        raw_snapshot = {
            "tables": tables,
            "foreign_keys": foreign_keys,
            "relationships": relationships,
        }
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(f"Failed to introspect SQLite schema: {exc}") from exc


def introspect_duckdb(
    connection_or_cursor: Any, filter_sensitive: bool = True
) -> dict[str, Any]:
    """
    Introspects DuckDB schema using information_schema and duckdb_constraints.
    """
    try:
        cur = (
            connection_or_cursor.cursor()
            if hasattr(connection_or_cursor, "cursor")
            else connection_or_cursor
        )

        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema IN ('main', 'public') AND table_type = 'BASE TABLE'
            ORDER BY table_name;
            """
        )
        table_rows = cur.fetchall()
        table_names = [r[0] for r in table_rows if r and r[0]]

        cur.execute(
            """
            SELECT table_name, column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema IN ('main', 'public')
            ORDER BY table_name, ordinal_position;
            """
        )
        col_rows = cur.fetchall()

        table_cols_map: dict[str, list[dict[str, Any]]] = {}
        for r in col_rows:
            t_name, c_name, d_type, is_null = str(r[0]), str(r[1]), str(r[2]), str(r[3])
            table_cols_map.setdefault(t_name, []).append(
                {
                    "name": c_name,
                    "data_type": d_type,
                    "is_nullable": is_null.upper() == "YES",
                    "is_primary": c_name == "id",
                    "comment": None,
                }
            )

        foreign_keys: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []

        with contextlib.suppress(Exception):
            cur.execute(
                """
                SELECT table_name, constraint_type, constraint_column_names, referenced_table, referenced_column_names
                FROM duckdb_constraints()
                WHERE constraint_type = 'FOREIGN KEY';
                """
            )
            for fk_row in cur.fetchall():
                tbl = str(fk_row[0])
                from_cols = fk_row[2]
                target_tbl = str(fk_row[3])
                to_cols = fk_row[4]
                if from_cols and target_tbl:
                    fc = (
                        from_cols[0]
                        if isinstance(from_cols, (list, tuple))
                        else str(from_cols)
                    )
                    tc = (
                        to_cols[0]
                        if (to_cols and isinstance(to_cols, (list, tuple)))
                        else "id"
                    )
                    foreign_keys.append(
                        {
                            "table": tbl,
                            "column": fc,
                            "foreign_table": target_tbl,
                            "foreign_column": tc,
                        }
                    )
                    relationships.append(
                        {
                            "source_table": tbl,
                            "source_column": fc,
                            "target_table": target_tbl,
                            "target_column": tc,
                        }
                    )

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            cols = table_cols_map.get(tbl, [])
            has_user = any(c["name"] == "user_id" for c in cols)
            tables[tbl] = {
                "name": tbl,
                "columns": cols,
                "has_user_id": has_user,
                "user_col": "user_id",
                "comment": None,
            }

        raw_snapshot = {
            "tables": tables,
            "foreign_keys": foreign_keys,
            "relationships": relationships,
        }
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(f"Failed to introspect DuckDB schema: {exc}") from exc


def introspect_information_schema(
    cursor: Any, schema_name: str = "public", filter_sensitive: bool = True
) -> dict[str, Any]:
    """
    Introspects standard ANSI/PostgreSQL/MySQL/MSSQL schemas via information_schema catalogs.
    """
    try:
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
            ORDER BY table_name;
            """,
            [schema_name],
        )
        table_rows = cursor.fetchall()
        table_names = [r[0] for r in table_rows if r and r[0]]

        cursor.execute(
            """
            SELECT table_name, column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position;
            """,
            [schema_name],
        )
        col_rows = cursor.fetchall()

        table_cols_map: dict[str, list[dict[str, Any]]] = {}
        for r in col_rows:
            t_name, c_name, d_type, is_null = str(r[0]), str(r[1]), str(r[2]), str(r[3])
            table_cols_map.setdefault(t_name, []).append(
                {
                    "name": c_name,
                    "data_type": d_type,
                    "is_nullable": is_null.upper() == "YES",
                    "is_primary": c_name == "id",
                    "comment": None,
                }
            )

        foreign_keys: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []

        with contextlib.suppress(Exception):
            cursor.execute(
                """
                SELECT
                    kcu.table_name AS src_table,
                    kcu.column_name AS src_column,
                    ccu.table_name AS tgt_table,
                    ccu.column_name AS tgt_column
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                    ON ccu.constraint_name = tc.constraint_name
                    AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = %s;
                """,
                [schema_name],
            )
            for fk_row in cursor.fetchall():
                src_tbl, src_col, tgt_tbl, tgt_col = (
                    str(fk_row[0]),
                    str(fk_row[1]),
                    str(fk_row[2]),
                    str(fk_row[3]),
                )
                foreign_keys.append(
                    {
                        "table": src_tbl,
                        "column": src_col,
                        "foreign_table": tgt_tbl,
                        "foreign_column": tgt_col,
                    }
                )
                relationships.append(
                    {
                        "source_table": src_tbl,
                        "source_column": src_col,
                        "target_table": tgt_tbl,
                        "target_column": tgt_col,
                    }
                )

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            cols = table_cols_map.get(tbl, [])
            has_user = any(c["name"] == "user_id" for c in cols)
            tables[tbl] = {
                "name": tbl,
                "columns": cols,
                "has_user_id": has_user,
                "user_col": "user_id",
                "comment": None,
            }

        raw_snapshot = {
            "tables": tables,
            "foreign_keys": foreign_keys,
            "relationships": relationships,
        }
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect information_schema for '{schema_name}': {exc}"
        ) from exc


def introspect_clickhouse(
    cursor: Any, database: str = "default", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects ClickHouse schema using system.tables and system.columns."""
    try:
        cursor.execute(
            "SELECT name FROM system.tables WHERE database = %s ORDER BY name;",
            [database],
        )
        table_rows = cursor.fetchall()
        table_names = [r[0] for r in table_rows if r and r[0]]

        cursor.execute(
            "SELECT table, name, type FROM system.columns WHERE database = %s ORDER BY table, position;",
            [database],
        )
        col_rows = cursor.fetchall()

        table_cols_map: dict[str, list[dict[str, Any]]] = {}
        for r in col_rows:
            t_name, c_name, d_type = str(r[0]), str(r[1]), str(r[2])
            table_cols_map.setdefault(t_name, []).append(
                {
                    "name": c_name,
                    "data_type": d_type,
                    "is_nullable": "Nullable" in d_type,
                    "is_primary": c_name == "id",
                    "comment": None,
                }
            )

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            cols = table_cols_map.get(tbl, [])
            has_user = any(c["name"] == "user_id" for c in cols)
            tables[tbl] = {
                "name": tbl,
                "columns": cols,
                "has_user_id": has_user,
                "user_col": "user_id",
                "comment": None,
            }

        raw_snapshot = {
            "tables": tables,
            "foreign_keys": [],
            "relationships": [],
        }
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect ClickHouse database '{database}': {exc}"
        ) from exc


def introspect_oracle(
    cursor: Any, owner: str | None = None, filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects Oracle schema using user_tables or all_tables."""
    try:
        if owner:
            cursor.execute(
                "SELECT table_name FROM all_tables WHERE owner = %s ORDER BY table_name",
                [owner.upper()],
            )
        else:
            cursor.execute("SELECT table_name FROM user_tables ORDER BY table_name")
        table_rows = cursor.fetchall()
        table_names = [r[0] for r in table_rows if r and r[0]]

        if owner:
            cursor.execute(
                """
                SELECT table_name, column_name, data_type, nullable
                FROM all_tab_columns
                WHERE owner = %s
                ORDER BY table_name, column_id
                """,
                [owner.upper()],
            )
        else:
            cursor.execute(
                """
                SELECT table_name, column_name, data_type, nullable
                FROM user_tab_columns
                ORDER BY table_name, column_id
                """
            )
        col_rows = cursor.fetchall()

        table_cols_map: dict[str, list[dict[str, Any]]] = {}
        for r in col_rows:
            t_name, c_name, d_type, nullable = (
                str(r[0]),
                str(r[1]),
                str(r[2]),
                str(r[3]),
            )
            table_cols_map.setdefault(t_name, []).append(
                {
                    "name": c_name.lower(),
                    "data_type": d_type.lower(),
                    "is_nullable": nullable == "Y",
                    "is_primary": c_name.lower() == "id",
                    "comment": None,
                }
            )

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            clean_tbl = tbl.lower()
            cols = table_cols_map.get(tbl, [])
            has_user = any(c["name"] == "user_id" for c in cols)
            tables[clean_tbl] = {
                "name": clean_tbl,
                "columns": cols,
                "has_user_id": has_user,
                "user_col": "user_id",
                "comment": None,
            }

        raw_snapshot = {
            "tables": tables,
            "foreign_keys": [],
            "relationships": [],
        }
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(f"Failed to introspect Oracle schema: {exc}") from exc


def introspect_via_sqlalchemy(
    engine_or_connection: Any, filter_sensitive: bool = True
) -> dict[str, Any]:
    """
    Universal schema introspection using SQLAlchemy's Inspector abstraction.
    Works across any SQLAlchemy-supported relational database.
    """
    try:
        from sqlalchemy import inspect
    except ImportError as err:
        raise DriverNotInstalledError(
            "SQLAlchemy is required for introspect_via_sqlalchemy. "
            "Install with: pip install 'query-builder-engine[sqlalchemy]'"
        ) from err

    try:
        inspector = inspect(engine_or_connection)
        table_names = inspector.get_table_names()

        tables: dict[str, dict[str, Any]] = {}
        foreign_keys: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []

        for tbl in table_names:
            cols: list[dict[str, Any]] = []
            has_user = False
            pk_info = inspector.get_pk_constraint(tbl) or {}
            pk_cols = set(pk_info.get("constrained_columns", []))

            for col in inspector.get_columns(tbl):
                c_name = col.get("name", "")
                d_type = str(col.get("type", "text"))
                is_nullable = bool(col.get("nullable", True))
                is_pk = c_name in pk_cols

                if c_name == "user_id":
                    has_user = True

                cols.append(
                    {
                        "name": c_name,
                        "data_type": d_type,
                        "is_nullable": is_nullable,
                        "is_primary": is_pk,
                        "comment": col.get("comment"),
                    }
                )

            tables[tbl] = {
                "name": tbl,
                "columns": cols,
                "has_user_id": has_user,
                "user_col": "user_id",
                "comment": None,
            }

            for fk in inspector.get_foreign_keys(tbl):
                referred_table = fk.get("referred_table")
                constrained_cols = fk.get("constrained_columns", [])
                referred_cols = fk.get("referred_columns", [])

                if referred_table and constrained_cols and referred_cols:
                    for src_c, tgt_c in zip(constrained_cols, referred_cols):
                        foreign_keys.append(
                            {
                                "table": tbl,
                                "column": src_c,
                                "foreign_table": referred_table,
                                "foreign_column": tgt_c,
                            }
                        )
                        relationships.append(
                            {
                                "source_table": tbl,
                                "source_column": src_c,
                                "target_table": referred_table,
                                "target_column": tgt_c,
                            }
                        )

        raw_snapshot = {
            "tables": tables,
            "foreign_keys": foreign_keys,
            "relationships": relationships,
        }
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect schema via SQLAlchemy: {exc}"
        ) from exc


def introspect_cratedb(
    cursor: Any, schema_name: str = "doc", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects CrateDB schema using information_schema.tables and columns."""
    try:
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
            ORDER BY table_name;
            """,
            [schema_name],
        )
        table_rows = cursor.fetchall()
        table_names = [r[0] for r in table_rows if r and r[0]]

        cursor.execute(
            """
            SELECT table_name, column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position;
            """,
            [schema_name],
        )
        col_rows = cursor.fetchall()

        table_cols_map: dict[str, list[dict[str, Any]]] = {}
        for r in col_rows:
            t_name, c_name, d_type, is_null = str(r[0]), str(r[1]), str(r[2]), str(r[3])
            table_cols_map.setdefault(t_name, []).append(
                {
                    "name": c_name,
                    "data_type": d_type,
                    "is_nullable": is_null.upper() == "YES",
                    "is_primary": c_name == "id",
                    "comment": None,
                }
            )

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            cols = table_cols_map.get(tbl, [])
            has_user = any(c["name"] == "user_id" for c in cols)
            tables[tbl] = {
                "name": tbl,
                "columns": cols,
                "has_user_id": has_user,
                "user_col": "user_id",
                "comment": None,
            }

        raw_snapshot = {
            "tables": tables,
            "foreign_keys": [],
            "relationships": [],
        }
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect CrateDB schema '{schema_name}': {exc}"
        ) from exc


def introspect_druid(
    cursor: Any, schema_name: str = "druid", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects Apache Druid schema using INFORMATION_SCHEMA."""
    try:
        cursor.execute(
            """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME;
            """,
            [schema_name],
        )
        table_rows = cursor.fetchall()
        table_names = [r[0] for r in table_rows if r and r[0]]

        cursor.execute(
            """
            SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME, ORDINAL_POSITION;
            """,
            [schema_name],
        )
        col_rows = cursor.fetchall()

        table_cols_map: dict[str, list[dict[str, Any]]] = {}
        for r in col_rows:
            t_name, c_name, d_type, is_null = str(r[0]), str(r[1]), str(r[2]), str(r[3])
            table_cols_map.setdefault(t_name, []).append(
                {
                    "name": c_name,
                    "data_type": d_type,
                    "is_nullable": is_null.upper() == "YES",
                    "is_primary": c_name == "__time" or c_name == "id",
                    "comment": None,
                }
            )

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            cols = table_cols_map.get(tbl, [])
            has_user = any(c["name"] == "user_id" for c in cols)
            tables[tbl] = {
                "name": tbl,
                "columns": cols,
                "has_user_id": has_user,
                "user_col": "user_id",
                "comment": None,
            }

        raw_snapshot = {
            "tables": tables,
            "foreign_keys": [],
            "relationships": [],
        }
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect Apache Druid schema '{schema_name}': {exc}"
        ) from exc


def introspect_saphana(
    cursor: Any, schema_name: str = "SYSTEM", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects SAP HANA schema using SYS.TABLES and SYS.TABLE_COLUMNS."""
    try:
        try:
            cursor.execute(
                """
                SELECT TABLE_NAME
                FROM SYS.TABLES
                WHERE SCHEMA_NAME = %s
                ORDER BY TABLE_NAME;
                """,
                [schema_name.upper()],
            )
            table_rows = cursor.fetchall()
            table_names = [r[0] for r in table_rows if r and r[0]]

            cursor.execute(
                """
                SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE_NAME, IS_NULLABLE
                FROM SYS.TABLE_COLUMNS
                WHERE SCHEMA_NAME = %s
                ORDER BY TABLE_NAME, POSITION;
                """,
                [schema_name.upper()],
            )
            col_rows = cursor.fetchall()
        except Exception:  # noqa: BLE001
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                ORDER BY table_name;
                """,
                [schema_name],
            )
            table_rows = cursor.fetchall()
            table_names = [r[0] for r in table_rows if r and r[0]]

            cursor.execute(
                """
                SELECT table_name, column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = %s
                ORDER BY table_name, ordinal_position;
                """,
                [schema_name],
            )
            col_rows = cursor.fetchall()

        table_cols_map: dict[str, list[dict[str, Any]]] = {}
        for r in col_rows:
            t_name, c_name, d_type, is_null = str(r[0]), str(r[1]), str(r[2]), str(r[3])
            table_cols_map.setdefault(t_name, []).append(
                {
                    "name": c_name.lower(),
                    "data_type": d_type.lower(),
                    "is_nullable": is_null.upper() in ("TRUE", "YES", "Y"),
                    "is_primary": c_name.lower() == "id",
                    "comment": None,
                }
            )

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            clean_tbl = tbl.lower()
            cols = table_cols_map.get(tbl, [])
            has_user = any(c["name"] == "user_id" for c in cols)
            tables[clean_tbl] = {
                "name": clean_tbl,
                "columns": cols,
                "has_user_id": has_user,
                "user_col": "user_id",
                "comment": None,
            }

        raw_snapshot = {
            "tables": tables,
            "foreign_keys": [],
            "relationships": [],
        }
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect SAP HANA schema '{schema_name}': {exc}"
        ) from exc


def introspect_scylladb(
    cursor_or_session: Any, keyspace: str = "system", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects ScyllaDB and Apache Cassandra schema using system_schema."""
    try:
        cur = (
            cursor_or_session.cursor()
            if hasattr(cursor_or_session, "cursor")
            else cursor_or_session
        )

        cur.execute(
            f"SELECT table_name FROM system_schema.tables WHERE keyspace_name = '{keyspace}';"
        )
        table_rows = cur.fetchall()
        table_names = [r[0] for r in table_rows if r and r[0]]

        cur.execute(
            f"SELECT table_name, column_name, type, kind FROM system_schema.columns WHERE keyspace_name = '{keyspace}';"
        )
        col_rows = cur.fetchall()

        table_cols_map: dict[str, list[dict[str, Any]]] = {}
        for r in col_rows:
            t_name, c_name, d_type, kind = str(r[0]), str(r[1]), str(r[2]), str(r[3])
            is_pk = kind in ("partition_key", "clustering")
            table_cols_map.setdefault(t_name, []).append(
                {
                    "name": c_name,
                    "data_type": d_type,
                    "is_nullable": not is_pk,
                    "is_primary": is_pk,
                    "comment": None,
                }
            )

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            cols = table_cols_map.get(tbl, [])
            has_user = any(c["name"] == "user_id" for c in cols)
            tables[tbl] = {
                "name": tbl,
                "columns": cols,
                "has_user_id": has_user,
                "user_col": "user_id",
                "comment": None,
            }

        raw_snapshot = {
            "tables": tables,
            "foreign_keys": [],
            "relationships": [],
        }
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect ScyllaDB keyspace '{keyspace}': {exc}"
        ) from exc


def introspect_sparksql(
    cursor_or_session: Any, schema_name: str = "default", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects Apache Spark SQL schema using SHOW TABLES or INFORMATION_SCHEMA."""
    try:
        cur = (
            cursor_or_session
            if hasattr(cursor_or_session, "execute")
            else (
                cursor_or_session.cursor()
                if hasattr(cursor_or_session, "cursor")
                else cursor_or_session
            )
        )
        try:
            cur.execute(f"SHOW TABLES IN `{schema_name}`;")
            table_rows = cur.fetchall()
            table_names = []
            for r in table_rows:
                if r:
                    t_name = str(r[1]) if len(r) > 1 else str(r[0])
                    table_names.append(t_name)
        except Exception:  # noqa: BLE001
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                ORDER BY table_name;
                """,
                [schema_name],
            )
            table_rows = cur.fetchall()
            table_names = [r[0] for r in table_rows if r and r[0]]

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            cols: list[dict[str, Any]] = []
            with contextlib.suppress(Exception):
                cur.execute(f"DESCRIBE TABLE `{schema_name}`.`{tbl}`;")
                col_rows = cur.fetchall()
                for cr in col_rows:
                    if cr and cr[0] and not str(cr[0]).startswith("#"):
                        c_name = str(cr[0]).strip()
                        d_type = str(cr[1]).strip() if len(cr) > 1 else "string"
                        cols.append(
                            {
                                "name": c_name,
                                "data_type": d_type,
                                "is_nullable": True,
                                "is_primary": c_name.lower() == "id",
                                "comment": None,
                            }
                        )

            has_user = any(c["name"] == "user_id" for c in cols)
            tables[tbl] = {
                "name": tbl,
                "columns": cols,
                "has_user_id": has_user,
                "user_col": "user_id",
                "comment": None,
            }

        raw_snapshot = {
            "tables": tables,
            "foreign_keys": [],
            "relationships": [],
        }
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect Spark SQL schema '{schema_name}': {exc}"
        ) from exc


def introspect_chdb(
    cursor_or_conn: Any, database: str = "default", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects chDB in-process ClickHouse schema using system.tables and system.columns."""
    try:
        cur = (
            cursor_or_conn
            if hasattr(cursor_or_conn, "execute")
            else (
                cursor_or_conn.cursor()
                if hasattr(cursor_or_conn, "cursor")
                else cursor_or_conn
            )
        )
        cur.execute(
            """
            SELECT name
            FROM system.tables
            WHERE database = %s
            ORDER BY name;
            """,
            [database],
        )
        table_rows = cur.fetchall()
        table_names = [r[0] for r in table_rows if r and r[0]]

        cur.execute(
            """
            SELECT table, name, type
            FROM system.columns
            WHERE database = %s
            ORDER BY table, position;
            """,
            [database],
        )
        col_rows = cur.fetchall()

        table_cols_map: dict[str, list[dict[str, Any]]] = {}
        for r in col_rows:
            t_name, c_name, d_type = str(r[0]), str(r[1]), str(r[2])
            is_pk = c_name.lower() == "id"
            table_cols_map.setdefault(t_name, []).append(
                {
                    "name": c_name,
                    "data_type": d_type,
                    "is_nullable": "Nullable" in d_type,
                    "is_primary": is_pk,
                    "comment": None,
                }
            )

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            cols = table_cols_map.get(tbl, [])
            has_user = any(c["name"] == "user_id" for c in cols)
            tables[tbl] = {
                "name": tbl,
                "columns": cols,
                "has_user_id": has_user,
                "user_col": "user_id",
                "comment": None,
            }

        raw_snapshot = {
            "tables": tables,
            "foreign_keys": [],
            "relationships": [],
        }
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect chDB database '{database}': {exc}"
        ) from exc


def introspect_greptimedb(
    cursor: Any, schema_name: str = "public", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects GreptimeDB time-series schema using INFORMATION_SCHEMA."""
    try:
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
            ORDER BY table_name;
            """,
            [schema_name],
        )
        table_rows = cursor.fetchall()
        table_names = [r[0] for r in table_rows if r and r[0]]

        cursor.execute(
            """
            SELECT table_name, column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position;
            """,
            [schema_name],
        )
        col_rows = cursor.fetchall()

        table_cols_map: dict[str, list[dict[str, Any]]] = {}
        for r in col_rows:
            t_name, c_name, d_type, is_null = (
                str(r[0]),
                str(r[1]),
                str(r[2]),
                str(r[3]),
            )
            is_pk = c_name in ("greptime_timestamp", "ts", "id")
            table_cols_map.setdefault(t_name, []).append(
                {
                    "name": c_name,
                    "data_type": d_type,
                    "is_nullable": is_null.upper() == "YES",
                    "is_primary": is_pk,
                    "comment": None,
                }
            )

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            cols = table_cols_map.get(tbl, [])
            has_user = any(c["name"] == "user_id" for c in cols)
            tables[tbl] = {
                "name": tbl,
                "columns": cols,
                "has_user_id": has_user,
                "user_col": "user_id",
                "comment": None,
            }

        raw_snapshot = {
            "tables": tables,
            "foreign_keys": [],
            "relationships": [],
        }
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect GreptimeDB schema '{schema_name}': {exc}"
        ) from exc


def introspect_tdengine(
    cursor: Any, database: str = "default", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects TDengine schema using SHOW TABLES and DESCRIBE."""
    try:
        try:
            cursor.execute(f"SHOW `{database}`.TABLES;")
        except Exception:  # noqa: BLE001
            cursor.execute("SHOW TABLES;")
        table_rows = cursor.fetchall()
        table_names = [r[0] for r in table_rows if r and r[0]]

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            cols: list[dict[str, Any]] = []
            with contextlib.suppress(Exception):
                cursor.execute(f"DESCRIBE `{tbl}`;")
                col_rows = cursor.fetchall()
                for idx, cr in enumerate(col_rows):
                    if cr:
                        c_name = str(cr[0])
                        d_type = str(cr[1]) if len(cr) > 1 else "VARCHAR"
                        is_pk = (idx == 0) or c_name.lower() == "ts"
                        cols.append(
                            {
                                "name": c_name,
                                "data_type": d_type,
                                "is_nullable": not is_pk,
                                "is_primary": is_pk,
                                "comment": None,
                            }
                        )

            has_user = any(c["name"] == "user_id" for c in cols)
            tables[tbl] = {
                "name": tbl,
                "columns": cols,
                "has_user_id": has_user,
                "user_col": "user_id",
                "comment": None,
            }

        raw_snapshot = {
            "tables": tables,
            "foreign_keys": [],
            "relationships": [],
        }
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect TDengine database '{database}': {exc}"
        ) from exc


def introspect_surrealdb(
    client_or_cursor: Any, database: str = "test", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects SurrealDB schema using INFO FOR DB and table metadata."""
    try:
        cur = (
            client_or_cursor
            if hasattr(client_or_cursor, "execute")
            or hasattr(client_or_cursor, "query")
            else (
                client_or_cursor.cursor()
                if hasattr(client_or_cursor, "cursor")
                else client_or_cursor
            )
        )
        table_names: list[str] = []
        if hasattr(cur, "execute"):
            cur.execute("INFO FOR DB;")
            res = cur.fetchone()
            if isinstance(res, dict) and "tables" in res:
                table_names = list(res["tables"].keys())
            elif isinstance(res, (list, tuple)) and res:
                first = res[0]
                if isinstance(first, dict) and "tables" in first:
                    table_names = list(first["tables"].keys())
                else:
                    table_names = [str(r[0]) for r in res if r and r[0]]
            elif isinstance(res, str):
                table_names = [res]
        elif hasattr(cur, "query"):
            res = cur.query("INFO FOR DB;")
            if isinstance(res, list) and res and isinstance(res[0], dict):
                table_names = list(res[0].get("result", {}).get("tables", {}).keys())

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            cols: list[dict[str, Any]] = [
                {
                    "name": "id",
                    "data_type": "record",
                    "is_nullable": False,
                    "is_primary": True,
                    "comment": None,
                }
            ]
            tables[tbl] = {
                "name": tbl,
                "columns": cols,
                "has_user_id": False,
                "user_col": "user_id",
                "comment": None,
            }

        raw_snapshot = {
            "tables": tables,
            "foreign_keys": [],
            "relationships": [],
        }
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect SurrealDB database '{database}': {exc}"
        ) from exc


def introspect_arangodb(
    db_or_cursor: Any, database: str = "_system", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects ArangoDB collections schema."""
    try:
        table_names: list[str] = []
        if hasattr(db_or_cursor, "execute"):
            db_or_cursor.execute("RETURN COLLECTIONS();")
            rows = db_or_cursor.fetchall()
            for r in rows:
                if r:
                    val = r[0] if isinstance(r, (list, tuple)) else r
                    if isinstance(val, list):
                        for item in val:
                            name = (
                                item.get("name")
                                if isinstance(item, dict)
                                else str(item)
                            )
                            if name and not name.startswith("_"):
                                table_names.append(name)
                    elif isinstance(val, dict):
                        name = val.get("name")
                        if name and not name.startswith("_"):
                            table_names.append(name)
                    else:
                        table_names.append(str(val))
        elif hasattr(db_or_cursor, "collections"):
            colls = db_or_cursor.collections()
            for c in colls:
                c_name = (
                    c["name"] if isinstance(c, dict) else getattr(c, "name", str(c))
                )
                if not str(c_name).startswith("_"):
                    table_names.append(str(c_name))

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            cols: list[dict[str, Any]] = [
                {
                    "name": "_key",
                    "data_type": "string",
                    "is_nullable": False,
                    "is_primary": True,
                    "comment": None,
                },
                {
                    "name": "_id",
                    "data_type": "string",
                    "is_nullable": False,
                    "is_primary": False,
                    "comment": None,
                },
            ]
            tables[tbl] = {
                "name": tbl,
                "columns": cols,
                "has_user_id": False,
                "user_col": "user_id",
                "comment": None,
            }

        raw_snapshot = {
            "tables": tables,
            "foreign_keys": [],
            "relationships": [],
        }
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect ArangoDB database '{database}': {exc}"
        ) from exc


def introspect_cassandra(
    cursor_or_session: Any, keyspace: str = "system", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects Apache Cassandra CQL schema using system_schema."""
    return introspect_scylladb(
        cursor_or_session, keyspace=keyspace, filter_sensitive=filter_sensitive
    )


def introspect_exasol(
    cursor: Any, schema_name: str = "PUBLIC", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects Exasol schema using EXA_ALL_TABLES and EXA_ALL_COLUMNS."""
    try:
        try:
            cursor.execute(
                """
                SELECT TABLE_NAME
                FROM EXA_ALL_TABLES
                WHERE TABLE_SCHEMA = ?
                ORDER BY TABLE_NAME;
                """,
                [schema_name.upper()],
            )
            table_rows = cursor.fetchall()
            table_names = [r[0] for r in table_rows if r and r[0]]

            cursor.execute(
                """
                SELECT COLUMN_TABLE, COLUMN_NAME, COLUMN_TYPE, COLUMN_IS_NULLABLE
                FROM EXA_ALL_COLUMNS
                WHERE COLUMN_SCHEMA = ?
                ORDER BY COLUMN_TABLE, COLUMN_ORDINAL_POSITION;
                """,
                [schema_name.upper()],
            )
            col_rows = cursor.fetchall()
        except Exception:  # noqa: BLE001
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                ORDER BY table_name;
                """,
                [schema_name],
            )
            table_rows = cursor.fetchall()
            table_names = [r[0] for r in table_rows if r and r[0]]

            cursor.execute(
                """
                SELECT table_name, column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = %s
                ORDER BY table_name, ordinal_position;
                """,
                [schema_name],
            )
            col_rows = cursor.fetchall()

        pk_cols_map: dict[str, set[str]] = {}
        with contextlib.suppress(Exception):
            cursor.execute(
                """
                SELECT CONSTRAINT_TABLE, COLUMN_NAME
                FROM EXA_ALL_CONSTRAINT_COLUMNS
                WHERE CONSTRAINT_SCHEMA = ? AND CONSTRAINT_TYPE = 'PRIMARY KEY';
                """,
                [schema_name.upper()],
            )
            for pkr in cursor.fetchall():
                pk_cols_map.setdefault(str(pkr[0]).lower(), set()).add(
                    str(pkr[1]).lower()
                )

        foreign_keys: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            cursor.execute(
                """
                SELECT CONSTRAINT_TABLE, COLUMN_NAME, REFERENCED_TABLE, REFERENCED_COLUMN
                FROM EXA_ALL_CONSTRAINT_COLUMNS
                WHERE CONSTRAINT_SCHEMA = ? AND CONSTRAINT_TYPE = 'FOREIGN KEY';
                """,
                [schema_name.upper()],
            )
            for fkr in cursor.fetchall():
                src_tbl, src_col, tgt_tbl, tgt_col = (
                    str(fkr[0]).lower(),
                    str(fkr[1]).lower(),
                    str(fkr[2]).lower(),
                    str(fkr[3]).lower(),
                )
                foreign_keys.append(
                    {
                        "table": src_tbl,
                        "column": src_col,
                        "foreign_table": tgt_tbl,
                        "foreign_column": tgt_col,
                    }
                )
                relationships.append(
                    {
                        "source_table": src_tbl,
                        "source_column": src_col,
                        "target_table": tgt_tbl,
                        "target_column": tgt_col,
                    }
                )

        table_cols_map: dict[str, list[dict[str, Any]]] = {}
        for r in col_rows:
            t_name, c_name, d_type, is_null = (
                str(r[0]),
                str(r[1]),
                str(r[2]),
                str(r[3]),
            )
            is_pk = c_name.lower() in pk_cols_map.get(t_name.lower(), set()) or (
                c_name.lower() == "id"
            )
            table_cols_map.setdefault(t_name, []).append(
                {
                    "name": c_name.lower(),
                    "data_type": d_type.lower(),
                    "is_nullable": is_null.upper() in ("TRUE", "YES", "Y"),
                    "is_primary": is_pk,
                    "comment": None,
                }
            )

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            clean_tbl = tbl.lower()
            cols = table_cols_map.get(tbl, []) or table_cols_map.get(clean_tbl, [])
            has_user = any(c["name"] == "user_id" for c in cols)
            tables[clean_tbl] = {
                "name": clean_tbl,
                "columns": cols,
                "has_user_id": has_user,
                "user_col": "user_id",
                "comment": None,
            }

        raw_snapshot = {
            "tables": tables,
            "foreign_keys": foreign_keys,
            "relationships": relationships,
        }
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect Exasol schema '{schema_name}': {exc}"
        ) from exc


def introspect_db2(
    cursor: Any, schema_name: str = "SYSCAT", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects IBM DB2 schema using SYSCAT tables."""
    try:
        try:
            cursor.execute(
                """
                SELECT TABNAME
                FROM SYSCAT.TABLES
                WHERE TABSCHEMA = ? AND TYPE = 'T'
                ORDER BY TABNAME;
                """,
                [schema_name.upper()],
            )
            table_rows = cursor.fetchall()
            table_names = [r[0] for r in table_rows if r and r[0]]

            cursor.execute(
                """
                SELECT TABNAME, COLNAME, TYPENAME, NULLS
                FROM SYSCAT.COLUMNS
                WHERE TABSCHEMA = ?
                ORDER BY TABNAME, COLNO;
                """,
                [schema_name.upper()],
            )
            col_rows = cursor.fetchall()
        except Exception:  # noqa: BLE001
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                ORDER BY table_name;
                """,
                [schema_name],
            )
            table_rows = cursor.fetchall()
            table_names = [r[0] for r in table_rows if r and r[0]]

            cursor.execute(
                """
                SELECT table_name, column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = %s
                ORDER BY table_name, ordinal_position;
                """,
                [schema_name],
            )
            col_rows = cursor.fetchall()

        pk_cols_map: dict[str, set[str]] = {}
        with contextlib.suppress(Exception):
            cursor.execute(
                """
                SELECT TABNAME, COLNAME
                FROM SYSCAT.KEYCOLUSE
                WHERE TABSCHEMA = ?;
                """,
                [schema_name.upper()],
            )
            for pkr in cursor.fetchall():
                pk_cols_map.setdefault(str(pkr[0]).lower(), set()).add(
                    str(pkr[1]).lower()
                )

        foreign_keys: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            cursor.execute(
                """
                SELECT TABNAME, FK_COLNAMES, REFTABNAME, PK_COLNAMES
                FROM SYSCAT.REFERENCES
                WHERE TABSCHEMA = ?;
                """,
                [schema_name.upper()],
            )
            for fkr in cursor.fetchall():
                src_tbl, src_col, tgt_tbl, tgt_col = (
                    str(fkr[0]).lower(),
                    str(fkr[1]).lower(),
                    str(fkr[2]).lower(),
                    str(fkr[3]).lower(),
                )
                foreign_keys.append(
                    {
                        "table": src_tbl,
                        "column": src_col,
                        "foreign_table": tgt_tbl,
                        "foreign_column": tgt_col,
                    }
                )
                relationships.append(
                    {
                        "source_table": src_tbl,
                        "source_column": src_col,
                        "target_table": tgt_tbl,
                        "target_column": tgt_col,
                    }
                )

        table_cols_map: dict[str, list[dict[str, Any]]] = {}
        for r in col_rows:
            t_name, c_name, d_type, is_null = (
                str(r[0]),
                str(r[1]),
                str(r[2]),
                str(r[3]),
            )
            is_pk = c_name.lower() in pk_cols_map.get(t_name.lower(), set()) or (
                c_name.lower() == "id"
            )
            table_cols_map.setdefault(t_name, []).append(
                {
                    "name": c_name.lower(),
                    "data_type": d_type.lower(),
                    "is_nullable": is_null.upper() in ("Y", "YES", "TRUE"),
                    "is_primary": is_pk,
                    "comment": None,
                }
            )

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            clean_tbl = tbl.lower()
            cols = table_cols_map.get(tbl, []) or table_cols_map.get(clean_tbl, [])
            has_user = any(c["name"] == "user_id" for c in cols)
            tables[clean_tbl] = {
                "name": clean_tbl,
                "columns": cols,
                "has_user_id": has_user,
                "user_col": "user_id",
                "comment": None,
            }

        raw_snapshot = {
            "tables": tables,
            "foreign_keys": foreign_keys,
            "relationships": relationships,
        }
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect IBM DB2 schema '{schema_name}': {exc}"
        ) from exc


def introspect_cosmosdb(
    client_or_container: Any, database: str = "default", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects Azure Cosmos DB container schemas."""
    try:
        target = getattr(client_or_container, "target", client_or_container)
        table_names: list[str] = []
        if hasattr(target, "get_database_client"):
            db_client = target.get_database_client(database)
            if hasattr(db_client, "list_containers"):
                for container in db_client.list_containers():
                    c_id = (
                        container.get("id")
                        if isinstance(container, dict)
                        else getattr(container, "id", None)
                    )
                    if c_id:
                        table_names.append(c_id)
        elif hasattr(target, "query_items"):
            items = list(target.query_items("SELECT VALUE c.id FROM c;"))
            table_names = [str(i) for i in items]
        elif hasattr(target, "execute"):
            target.execute("SELECT VALUE c.id FROM c;")
            rows = target.fetchall()
            for r in rows:
                if r:
                    table_names.append(str(r[0]))

        if not table_names:
            table_names = ["items"]

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            cols: list[dict[str, Any]] = [
                {
                    "name": "id",
                    "data_type": "string",
                    "is_nullable": False,
                    "is_primary": True,
                    "comment": None,
                },
                {
                    "name": "_rid",
                    "data_type": "string",
                    "is_nullable": False,
                    "is_primary": False,
                    "comment": None,
                },
                {
                    "name": "_ts",
                    "data_type": "number",
                    "is_nullable": False,
                    "is_primary": False,
                    "comment": None,
                },
            ]
            tables[tbl] = {
                "name": tbl,
                "columns": cols,
                "has_user_id": False,
                "user_col": "user_id",
                "comment": None,
            }

        raw_snapshot = {
            "tables": tables,
            "foreign_keys": [],
            "relationships": [],
        }
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect Cosmos DB database '{database}': {exc}"
        ) from exc
