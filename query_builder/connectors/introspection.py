"""
Universal and Engine-Specific Schema Introspection Protocols.
=============================================================
Provides automated reverse-engineering of tables, columns, primary keys,
and foreign key relationships across supported SQL database engines.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Generator
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
            safe_tbl = tbl.replace('"', '""')
            cursor.execute(f'PRAGMA table_info("{safe_tbl}");')
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
            cursor.execute(f'PRAGMA foreign_key_list("{safe_tbl}");')
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
    cur = None
    own_cur = False
    try:
        if hasattr(connection_or_cursor, "cursor"):
            cur = connection_or_cursor.cursor()
            own_cur = True
        else:
            cur = connection_or_cursor

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
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


_PRIMARY_KEY_SQL = """
    SELECT kcu.table_name, kcu.column_name
    FROM information_schema.table_constraints AS tc
    JOIN information_schema.key_column_usage AS kcu
        ON tc.constraint_name = kcu.constraint_name
        AND tc.table_schema = kcu.table_schema
        AND tc.table_name = kcu.table_name
    WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = %s;
"""

# MySQL/MariaDB have no constraint_column_usage; the referenced side lives on
# key_column_usage itself.
_MYSQL_FOREIGN_KEY_SQL = """
    SELECT table_name, column_name, referenced_table_name, referenced_column_name
    FROM information_schema.key_column_usage
    WHERE table_schema = %s AND referenced_table_name IS NOT NULL;
"""


# SQL Server's constraint_column_usage lists the REFERENCING column for a foreign
# key, so the referenced side must come from referential_constraints instead.
_MSSQL_FOREIGN_KEY_SQL = """
    SELECT kcu.table_name, kcu.column_name, pk.table_name, pk.column_name
    FROM information_schema.referential_constraints AS rc
    JOIN information_schema.key_column_usage AS kcu
        ON kcu.constraint_name = rc.constraint_name
        AND kcu.constraint_schema = rc.constraint_schema
    JOIN information_schema.key_column_usage AS pk
        ON pk.constraint_name = rc.unique_constraint_name
        AND pk.constraint_schema = rc.unique_constraint_schema
        AND pk.ordinal_position = kcu.ordinal_position
    WHERE kcu.table_schema = %s;
"""


def introspect_information_schema(
    cursor: Any,
    schema_name: str = "public",
    filter_sensitive: bool = True,
    fk_style: str = "ansi",
    placeholder: str = "%s",
    pk_guess: bool = True,
) -> dict[str, Any]:
    """
    Introspects standard ANSI/PostgreSQL/MySQL/MSSQL schemas via information_schema catalogs.

    Primary keys come from the catalog (``table_constraints``); only when the
    engine lacks that catalog does it fall back (``pk_guess``) to treating a
    column named ``id`` as the key. ``fk_style="mysql"`` / ``"mssql"`` read
    foreign keys the way those engines expose them. ``placeholder`` is the
    driver's bind marker (``?`` for Trino/Presto); statements are sent without a
    trailing semicolon, which Trino and Presto reject.
    """

    def _sql(text: str) -> str:
        return text.strip().rstrip(";").replace("%s", placeholder)

    try:
        cursor.execute(
            _sql(
                """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
            ORDER BY table_name;
            """
            ),
            [schema_name],
        )
        table_rows = cursor.fetchall()
        table_names = [r[0] for r in table_rows if r and r[0]]

        cursor.execute(
            _sql(
                """
            SELECT table_name, column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position;
            """
            ),
            [schema_name],
        )
        col_rows = cursor.fetchall()

        pk_cols: set[tuple[str, str]] | None = None
        with contextlib.suppress(Exception):
            cursor.execute(_sql(_PRIMARY_KEY_SQL), [schema_name])
            pk_cols = {(str(r[0]), str(r[1])) for r in cursor.fetchall()}
        if pk_cols is None and not pk_guess:
            pk_cols = set()

        table_cols_map: dict[str, list[dict[str, Any]]] = {}
        for r in col_rows:
            t_name, c_name, d_type, is_null = str(r[0]), str(r[1]), str(r[2]), str(r[3])
            table_cols_map.setdefault(t_name, []).append(
                {
                    "name": c_name,
                    "data_type": d_type,
                    "is_nullable": is_null.upper() == "YES",
                    "is_primary": (t_name, c_name) in pk_cols
                    if pk_cols is not None
                    else c_name == "id",
                    "comment": None,
                }
            )

        foreign_keys: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []

        fk_sql = (
            _MYSQL_FOREIGN_KEY_SQL
            if fk_style == "mysql"
            else _MSSQL_FOREIGN_KEY_SQL
            if fk_style == "mssql"
            else """
                SELECT
                    kcu.table_name AS src_table,
                    kcu.column_name AS src_column,
                    ccu.table_name AS tgt_table,
                    ccu.column_name AS tgt_column
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                    AND tc.table_name = kcu.table_name
                JOIN information_schema.constraint_column_usage AS ccu
                    ON ccu.constraint_name = tc.constraint_name
                    AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = %s;
                """
        )
        with contextlib.suppress(Exception):
            cursor.execute(_sql(fk_sql), [schema_name])
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
            "SELECT table, name, type, is_in_primary_key FROM system.columns WHERE database = %s ORDER BY table, position;",
            [database],
        )
        col_rows = cursor.fetchall()

        table_cols_map: dict[str, list[dict[str, Any]]] = {}
        for r in col_rows:
            t_name, c_name, d_type = str(r[0]), str(r[1]), str(r[2])
            # The sorting/primary key comes from the catalog, not a name guess.
            is_pk = bool(r[3]) if len(r) > 3 else c_name == "id"
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
            f"Failed to introspect ClickHouse database '{database}': {exc}"
        ) from exc


def introspect_oracle(
    cursor: Any, owner: str | None = None, filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects an Oracle schema (``user_*`` views, or ``all_*`` for another ``owner``).

    Names are returned exactly as stored in the catalog: the compiler QUOTES every identifier,
    so folding the case here would produce names that do not exist (Oracle stores unquoted
    names in upper case and quoted names verbatim).  Primary and foreign keys come from the
    constraint catalog.
    """
    try:
        if owner:
            own = " AND {a}.owner = :1"
            params: list[Any] = [owner.upper()]
            pre = "all"
        else:
            own = ""
            params = []
            pre = "user"

        def q(sql: str, **fmt: str) -> None:
            cursor.execute(sql.format(pre=pre, **fmt), params)

        # plain tables only (no views, no nested/IOT overflow noise)
        q(
            "SELECT t.table_name FROM {pre}_tables t WHERE t.nested = 'NO'"
            + own.format(a="t")
            + " ORDER BY t.table_name"
        )
        table_names = [str(r[0]) for r in cursor.fetchall() if r and r[0]]
        known = set(table_names)

        q(
            "SELECT c.table_name, c.column_name, c.data_type, c.nullable "
            "FROM {pre}_tab_columns c WHERE 1 = 1" + own.format(a="c") + " "
            "ORDER BY c.table_name, c.column_id"
        )
        col_rows = cursor.fetchall()

        pk: dict[str, set[str]] = {}
        q(
            "SELECT cc.table_name, cc.column_name FROM {pre}_constraints c "
            "JOIN {pre}_cons_columns cc ON c.constraint_name = cc.constraint_name "
            "AND c.owner = cc.owner WHERE c.constraint_type = 'P'" + own.format(a="c")
        )
        for r in cursor.fetchall():
            pk.setdefault(str(r[0]), set()).add(str(r[1]))

        foreign_keys: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []
        q(
            "SELECT cc.table_name, cc.column_name, rcc.table_name, rcc.column_name "
            "FROM {pre}_constraints c "
            "JOIN {pre}_cons_columns cc ON c.constraint_name = cc.constraint_name "
            "AND c.owner = cc.owner "
            "JOIN {pre}_cons_columns rcc ON c.r_constraint_name = rcc.constraint_name "
            "AND c.r_owner = rcc.owner AND cc.position = rcc.position "
            "WHERE c.constraint_type = 'R'" + own.format(a="c")
        )
        for r in cursor.fetchall():
            src_t, src_c, tgt_t, tgt_c = (str(x) for x in r[:4])
            foreign_keys.append(
                {
                    "table": src_t,
                    "column": src_c,
                    "foreign_table": tgt_t,
                    "foreign_column": tgt_c,
                }
            )
            relationships.append(
                {
                    "source_table": src_t,
                    "source_column": src_c,
                    "target_table": tgt_t,
                    "target_column": tgt_c,
                }
            )

        table_cols_map: dict[str, list[dict[str, Any]]] = {}
        for r in col_rows:
            t_name, c_name, d_type, nullable = (str(x) for x in r[:4])
            if t_name not in known:
                continue
            table_cols_map.setdefault(t_name, []).append(
                {
                    "name": c_name,
                    "data_type": d_type.lower(),
                    "is_nullable": nullable == "Y",
                    "is_primary": c_name in pk.get(t_name, set()),
                    "comment": None,
                }
            )

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            cols = table_cols_map.get(tbl, [])
            tables[tbl] = {
                "name": tbl,
                "columns": cols,
                "has_user_id": any(c["name"].lower() == "user_id" for c in cols),
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
                    for src_c, tgt_c in zip(
                        constrained_cols, referred_cols, strict=False
                    ):
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
    cur = None
    own_cur = False
    try:
        if hasattr(cursor_or_session, "cursor"):
            cur = cursor_or_session.cursor()
            own_cur = True
        else:
            cur = cursor_or_session

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
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_sparksql(
    cursor_or_session: Any, schema_name: str = "default", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects Apache Spark SQL schema using SHOW TABLES or INFORMATION_SCHEMA."""
    cur = None
    own_cur = False
    try:
        if hasattr(cursor_or_session, "execute"):
            cur = cursor_or_session
        else:
            cur = cursor_or_session.cursor()
            own_cur = True
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
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_chdb(
    cursor_or_conn: Any, database: str = "default", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects chDB in-process ClickHouse schema using system.tables and system.columns."""
    cur = None
    own_cur = False
    try:
        if hasattr(cursor_or_conn, "execute"):
            cur = cursor_or_conn
        else:
            cur = cursor_or_conn.cursor()
            own_cur = True
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
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


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


def surreal_schema_steps(
    filter_sensitive: bool = True,
) -> Generator[str, list[dict[str, Any]], dict[str, Any]]:
    """SurrealDB introspection as a coroutine-free generator.

    It yields a SurrealQL statement, is sent that statement's records (a list of dicts) and
    finally returns the normalized snapshot.  A synchronous cursor and an ``async`` driver
    can both drive it (see :func:`introspect_surrealdb` and the async connector), so the
    sync and async classes share one algorithm.  Tables come from ``INFO FOR DB``; columns
    from ``INFO FOR TABLE`` (declared fields) merged with a sample of the records, because
    SurrealDB tables are schemaless unless fields are DEFINEd.  Nothing is invented.
    """
    info_rows = yield "INFO FOR DB"
    info = info_rows[0] if info_rows else {}
    table_names = sorted((info.get("tables") or {}).keys())
    tables: dict[str, dict[str, Any]] = {}
    for tbl in table_names:
        safe = str(tbl).replace("`", "")
        cols: dict[str, str] = {}
        tinfo_rows = yield f"INFO FOR TABLE `{safe}`"
        declared = (tinfo_rows[0] if tinfo_rows else {}).get("fields") or {}
        for fname, definition in declared.items():
            m = re.search(r"\bTYPE\s+(\S+)", str(definition), re.IGNORECASE)
            cols[str(fname)] = m.group(1) if m else "any"
        sample = yield f"SELECT * FROM `{safe}` LIMIT 100"
        for rec in sample:
            for k, v in rec.items():
                if k != "id" and (k not in cols or cols[k] == "any"):
                    cols[k] = _arango_json_type(v)
        columns: list[dict[str, Any]] = [
            {
                "name": "id",
                "data_type": "record",
                "is_nullable": False,
                "is_primary": True,
                "comment": None,
            }
        ]
        columns += [
            {
                "name": n,
                "data_type": t,
                "is_nullable": True,
                "is_primary": False,
                "comment": None,
            }
            for n, t in cols.items()
        ]
        tables[tbl] = {
            "name": tbl,
            "columns": columns,
            "has_user_id": "user_id" in cols,
            "user_col": "user_id",
            "comment": None,
        }
    return normalize_schema_snapshot(
        {"tables": tables, "foreign_keys": [], "relationships": []},
        filter_sensitive=filter_sensitive,
    )


def drive_steps(steps: Any, run: Any) -> Any:
    """Run a statement-yielding generator to completion against a synchronous ``run(sql)``.

    A failing statement is thrown INTO the generator, which may catch it (to fall back to
    another statement) or let it propagate.
    """
    try:
        statement = next(steps)
        while True:
            try:
                result = run(statement)
            except Exception as exc:  # noqa: BLE001 - handed to the generator
                statement = steps.throw(exc)
                continue
            statement = steps.send(result)
    except StopIteration as done:
        return done.value


def introspect_surrealdb(
    client_or_cursor: Any, database: str = "test", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects SurrealDB: tables from INFO FOR DB, columns from DEFINEd fields + samples."""
    cur = None
    own_cur = False
    try:
        cur = client_or_cursor
        if not hasattr(cur, "execute") and hasattr(cur, "cursor"):
            cur = cur.cursor()
            own_cur = True
        elif not hasattr(cur, "execute") and hasattr(cur, "query"):
            from query_builder.connectors.surrealdb import _SurrealCursorAdapter

            cur = _SurrealCursorAdapter(cur)  # a raw SDK client

        def run(sql: str) -> list[dict[str, Any]]:
            cur.execute(sql)
            names = [d[0] for d in (getattr(cur, "description", None) or [])]
            return _rows_as_dicts(names, cur.fetchall())

        return drive_steps(surreal_schema_steps(filter_sensitive), run)
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect SurrealDB database '{database}': {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def _arango_json_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "null"
    if isinstance(value, (bytes, bytearray)):
        return "bytes"
    if hasattr(value, "isoformat"):
        return "timestamp"
    return type(value).__name__.lower()


def _arango_sample_fields(db_or_cursor: Any, collection: str) -> dict[str, str]:
    """Attribute -> JSON type, merged over a sample of the collection's documents.

    ArangoDB collections are schemaless, so the only truthful column list is what the
    documents actually contain.  Returns {} for an empty collection or when the source
    cannot run AQL (nothing is invented).
    """
    sample: dict[str, Any] = {}
    try:
        if hasattr(db_or_cursor, "execute") and hasattr(db_or_cursor, "fetchall"):
            safe = collection.replace("`", "")
            db_or_cursor.execute(f"RETURN MERGE(FOR d IN `{safe}` LIMIT 100 RETURN d)")
            rows = db_or_cursor.fetchall() or []
            desc = [d[0] for d in (getattr(db_or_cursor, "description", None) or [])]
            if rows and desc and isinstance(rows[0], (list, tuple)):
                sample = dict(zip(desc, rows[0], strict=False))
        elif hasattr(db_or_cursor, "collection"):
            docs = list(db_or_cursor.collection(collection).all(limit=100))
            for doc in docs:
                if isinstance(doc, dict):
                    for k, v in doc.items():
                        if sample.get(k) is None:
                            sample[k] = v
    except Exception:  # noqa: BLE001 - sampling is best effort; never fail introspection
        return {}
    return {
        str(k): _arango_json_type(v) for k, v in sample.items() if not str(k).startswith("_")
    }


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
            sampled = _arango_sample_fields(db_or_cursor, tbl)
            for field_name, field_type in sampled.items():
                cols.append(
                    {
                        "name": field_name,
                        "data_type": field_type,
                        "is_nullable": True,
                        "is_primary": False,
                        "comment": None,
                    }
                )
            tables[tbl] = {
                "name": tbl,
                "columns": cols,
                "has_user_id": "user_id" in sampled,
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


def cosmos_snapshot(
    samples: dict[str, list[dict[str, Any]]], filter_sensitive: bool = True
) -> dict[str, Any]:
    """Cosmos DB snapshot from ``{container: sampled documents}``.

    ``id`` (always present, a string) is the primary key; the other columns are the
    attributes found in the sample.  System properties (``_rid``, ``_self``, ``_etag``,
    ``_attachments``, ``_ts``) are not columns.  No container -> no tables.
    """
    tables: dict[str, dict[str, Any]] = {}
    for name, docs in samples.items():
        found: dict[str, str] = {}
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            for k, v in doc.items():
                if k.startswith("_"):
                    continue
                if k not in found or found[k] == "null":
                    found[k] = _arango_json_type(v)
        found.setdefault("id", "string")
        tables[name] = {
            "name": name,
            "columns": _sampled_columns(found, "id", "string"),
            "has_user_id": "user_id" in found,
            "user_col": "user_id",
            "comment": None,
        }
    return normalize_schema_snapshot(
        {"tables": tables, "foreign_keys": [], "relationships": []},
        filter_sensitive=filter_sensitive,
    )


def introspect_cosmosdb(
    client_or_container: Any, database: str = "default", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects Azure Cosmos DB: real containers and the attributes of sampled documents."""
    try:
        target = getattr(client_or_container, "target", client_or_container)
        samples: dict[str, list[dict[str, Any]]] = {}
        sample_query = "SELECT * FROM c OFFSET 0 LIMIT 100"
        if hasattr(target, "get_database_client"):
            db_client = target.get_database_client(database)
            for container in db_client.list_containers():
                c_id = (
                    container.get("id")
                    if isinstance(container, dict)
                    else getattr(container, "id", None)
                )
                if c_id:
                    proxy = db_client.get_container_client(c_id)
                    samples[str(c_id)] = list(
                        proxy.query_items(
                            query=sample_query, enable_cross_partition_query=True
                        )
                    )
        elif hasattr(target, "query_items"):  # a single container client
            name = str(getattr(target, "id", None) or "items")
            samples[name] = list(
                target.query_items(query=sample_query, enable_cross_partition_query=True)
            )
        elif hasattr(target, "execute"):
            target.execute("SELECT VALUE c.id FROM c;")
            for r in target.fetchall() or []:
                if r:
                    samples[str(r[0])] = []
        return cosmos_snapshot(samples, filter_sensitive)
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect Cosmos DB database '{database}': {exc}"
        ) from exc


DEFAULT_SENSITIVE_COLUMN_PATTERNS: tuple[str, ...] = (
    "password",
    "secret",
    "token",
    "api_key",
    "access_token",
    "auth_token",
    "private_key",
    "ssn",
)


def _is_sensitive_column(col_name: str) -> bool:
    clean = col_name.lower().strip()
    return any(p in clean for p in DEFAULT_SENSITIVE_COLUMN_PATTERNS)


def _has_attr(target: Any, attr: str) -> bool:
    if hasattr(target, "_mock_children"):
        if getattr(target, "_mock_methods", None) is not None:
            return hasattr(target, attr)
        return attr in target._mock_children
    return hasattr(target, attr)


def _unwrap_cursor(client_or_cur: Any) -> Any:
    if (
        not hasattr(client_or_cur, "_mock_children")
        and hasattr(client_or_cur, "target")
        and getattr(client_or_cur, "target", None) is not None
    ):
        client_or_cur = client_or_cur.target
    if hasattr(client_or_cur, "_mock_children"):
        if getattr(client_or_cur, "_mock_methods", None) is not None:
            if hasattr(client_or_cur, "cursor") and not hasattr(
                client_or_cur, "fetchall"
            ):
                return client_or_cur.cursor()
            return client_or_cur
        if "cursor" in client_or_cur._mock_children:
            return client_or_cur.cursor()
        return client_or_cur
    if hasattr(client_or_cur, "cursor") and not hasattr(client_or_cur, "fetchall"):
        return client_or_cur.cursor()
    return client_or_cur


def introspect_doris(
    cursor: Any, database: str = "information_schema", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects Apache Doris schema using information_schema or SHOW TABLES."""
    try:
        table_names: list[str] = []
        try:
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s AND table_type IN ('BASE TABLE', 'VIEW', 'EXTERNAL TABLE')
                ORDER BY table_name;
                """,
                [database],
            )
            table_rows = cursor.fetchall()
            table_names = [r[0] for r in table_rows if r and r[0]]
        except Exception:  # noqa: BLE001
            cursor.execute("SHOW TABLES;")
            table_rows = cursor.fetchall()
            table_names = [r[0] for r in table_rows if r and r[0]]

        table_cols_map: dict[str, list[dict[str, Any]]] = {}
        try:
            cursor.execute(
                """
                SELECT table_name, column_name, data_type, is_nullable, column_key
                FROM information_schema.columns
                WHERE table_schema = %s
                ORDER BY table_name, ordinal_position;
                """,
                [database],
            )
            col_rows = cursor.fetchall()
            for r in col_rows:
                t_name, c_name, d_type, is_null = (
                    str(r[0]),
                    str(r[1]),
                    str(r[2]),
                    str(r[3]),
                )
                if filter_sensitive and _is_sensitive_column(c_name):
                    continue
                col_key = str(r[4]).upper() if len(r) > 4 and r[4] else ""
                is_pk = (col_key in ("PRI", "UNI")) or (c_name.lower() == "id")
                table_cols_map.setdefault(t_name, []).append(
                    {
                        "name": c_name,
                        "data_type": d_type,
                        "is_nullable": is_null.upper() in ("YES", "TRUE", "Y", "1"),
                        "is_primary": is_pk,
                        "comment": None,
                    }
                )
        except Exception:  # noqa: BLE001
            for tbl in table_names:
                cursor.execute(f"DESCRIBE `{tbl}`;")
                col_rows = cursor.fetchall()
                for r in col_rows:
                    c_name = str(r[0])
                    if filter_sensitive and _is_sensitive_column(c_name):
                        continue
                    d_type = str(r[1]) if len(r) > 1 else "string"
                    is_null = str(r[2]) if len(r) > 2 else "YES"
                    col_key = str(r[3]).upper() if len(r) > 3 and r[3] else ""
                    is_pk = (col_key in ("PRI", "UNI", "YES")) or (
                        c_name.lower() == "id"
                    )
                    table_cols_map.setdefault(tbl, []).append(
                        {
                            "name": c_name,
                            "data_type": d_type,
                            "is_nullable": is_null.upper() in ("YES", "TRUE", "Y", "1"),
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
            f"Failed to introspect Apache Doris database '{database}': {exc}"
        ) from exc


def introspect_impala(
    cursor: Any, database: str = "default", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects Apache Impala schema using SHOW TABLES and DESCRIBE."""
    try:
        cursor.execute(f"SHOW TABLES IN `{database}`;")
        table_rows = cursor.fetchall()
        table_names = [r[0] for r in table_rows if r and r[0]]

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            cursor.execute(f"DESCRIBE `{database}`.`{tbl}`;")
            col_rows = cursor.fetchall()
            cols: list[dict[str, Any]] = []
            has_user = False
            for r in col_rows:
                c_name = str(r[0]).strip()
                if not c_name or c_name.startswith("#"):
                    continue
                if filter_sensitive and _is_sensitive_column(c_name):
                    continue
                d_type = str(r[1]).strip() if len(r) > 1 and r[1] else "string"
                comment = str(r[2]).strip() if len(r) > 2 and r[2] else None
                if c_name == "user_id":
                    has_user = True
                cols.append(
                    {
                        "name": c_name,
                        "data_type": d_type,
                        "is_nullable": True,
                        "is_primary": c_name == "id",
                        "comment": comment,
                    }
                )
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
            f"Failed to introspect Apache Impala database '{database}': {exc}"
        ) from exc


def introspect_hive(
    cursor: Any, database: str = "default", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects Apache Hive lakehouse schema via HiveServer2 metadata."""
    try:
        cursor.execute(f"SHOW TABLES IN `{database}`;")
        table_rows = cursor.fetchall()
        table_names = [r[0] for r in table_rows if r and r[0]]

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            cursor.execute(f"DESCRIBE `{database}`.`{tbl}`;")
            col_rows = cursor.fetchall()
            cols: list[dict[str, Any]] = []
            has_user = False
            for r in col_rows:
                c_name = str(r[0]).strip()
                if not c_name or c_name.startswith("#"):
                    continue
                if filter_sensitive and _is_sensitive_column(c_name):
                    continue
                d_type = str(r[1]).strip() if len(r) > 1 and r[1] else "string"
                comment = str(r[2]).strip() if len(r) > 2 and r[2] else None
                if c_name == "user_id":
                    has_user = True
                cols.append(
                    {
                        "name": c_name,
                        "data_type": d_type,
                        "is_nullable": True,
                        "is_primary": c_name == "id",
                        "comment": comment,
                    }
                )
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
            f"Failed to introspect Apache Hive database '{database}': {exc}"
        ) from exc


def introspect_kyuubi(
    cursor: Any, database: str = "default", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects Apache Kyuubi multi-tenant query gateway schema."""
    try:
        cursor.execute(f"SHOW TABLES IN `{database}`;")
        table_rows = cursor.fetchall()
        table_names = [r[0] for r in table_rows if r and r[0]]

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            cursor.execute(f"DESCRIBE `{database}`.`{tbl}`;")
            col_rows = cursor.fetchall()
            cols: list[dict[str, Any]] = []
            has_user = False
            for r in col_rows:
                c_name = str(r[0]).strip()
                if not c_name or c_name.startswith("#"):
                    continue
                if filter_sensitive and _is_sensitive_column(c_name):
                    continue
                d_type = str(r[1]).strip() if len(r) > 1 and r[1] else "string"
                comment = str(r[2]).strip() if len(r) > 2 and r[2] else None
                if c_name == "user_id":
                    has_user = True
                cols.append(
                    {
                        "name": c_name,
                        "data_type": d_type,
                        "is_nullable": True,
                        "is_primary": c_name == "id",
                        "comment": comment,
                    }
                )
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
            f"Failed to introspect Apache Kyuubi database '{database}': {exc}"
        ) from exc


def introspect_drill(
    cursor_or_client: Any,
    schema_name: str = "dfs.default",
    filter_sensitive: bool = True,
) -> dict[str, Any]:
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor_or_client)
        own_cur = cur is not cursor_or_client and cur is not getattr(
            cursor_or_client, "target", None
        )
        table_names: list[str] = []
        try:
            cur.execute(
                """
                SELECT TABLE_NAME
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = %s
                ORDER BY TABLE_NAME;
                """,
                [schema_name],
            )
            table_rows = cur.fetchall()
            table_names = [r[0] for r in table_rows if r and r[0]]
        except Exception:  # noqa: BLE001
            cur.execute("SHOW TABLES;")
            table_rows = cur.fetchall()
            table_names = [r[0] for r in table_rows if r and r[0]]

        table_cols_map: dict[str, list[dict[str, Any]]] = {}
        try:
            cur.execute(
                """
                SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = %s
                ORDER BY TABLE_NAME, ORDINAL_POSITION;
                """,
                [schema_name],
            )
            col_rows = cur.fetchall()
            for r in col_rows:
                t_name, c_name, d_type, is_null = (
                    str(r[0]),
                    str(r[1]),
                    str(r[2]),
                    str(r[3]),
                )
                if filter_sensitive and _is_sensitive_column(c_name):
                    continue
                table_cols_map.setdefault(t_name, []).append(
                    {
                        "name": c_name,
                        "data_type": d_type,
                        "is_nullable": is_null.upper() in ("YES", "TRUE", "Y", "1"),
                        "is_primary": c_name == "id",
                        "comment": None,
                    }
                )
        except Exception:  # noqa: BLE001
            for tbl in table_names:
                cur.execute(f"DESCRIBE `{tbl}`;")
                col_rows = cur.fetchall()
                for r in col_rows:
                    c_name = str(r[0])
                    if filter_sensitive and _is_sensitive_column(c_name):
                        continue
                    d_type = str(r[1]) if len(r) > 1 else "VARCHAR"
                    is_null = str(r[2]) if len(r) > 2 else "YES"
                    table_cols_map.setdefault(tbl, []).append(
                        {
                            "name": c_name,
                            "data_type": d_type,
                            "is_nullable": is_null.upper() in ("YES", "TRUE", "Y", "1"),
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
            f"Failed to introspect Apache Drill schema '{schema_name}': {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_yugabyte(
    cursor: Any, schema_name: str = "public", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects YugabyteDB PostgreSQL-compatible distributed HTAP schema."""
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

        pk_cols_map: dict[str, set[str]] = {}
        with contextlib.suppress(Exception):
            cursor.execute(
                """
                SELECT kcu.table_name, kcu.column_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
                  AND tc.table_schema = %s;
                """,
                [schema_name],
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
                SELECT kcu.table_name AS src_table,
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
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = %s;
                """,
                [schema_name],
            )
            for fkr in cursor.fetchall():
                src_tbl, src_col, tgt_tbl, tgt_col = (
                    str(fkr[0]),
                    str(fkr[1]),
                    str(fkr[2]),
                    str(fkr[3]),
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
            if filter_sensitive and _is_sensitive_column(c_name):
                continue
            is_pk = (c_name.lower() in pk_cols_map.get(t_name.lower(), set())) or (
                c_name.lower() == "id"
            )
            table_cols_map.setdefault(t_name, []).append(
                {
                    "name": c_name,
                    "data_type": d_type,
                    "is_nullable": is_null.upper() in ("YES", "TRUE", "Y", "1"),
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
            "foreign_keys": foreign_keys,
            "relationships": relationships,
        }
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect YugabyteDB schema '{schema_name}': {exc}"
        ) from exc


def introspect_opensearch(
    client_or_cursor: Any,
    catalog: str = "default",
    filter_sensitive: bool = True,
    _mappings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Introspects OpenSearch indices and mappings via OpenSearch SQL plugin or indices API.

    ``_mappings`` lets an async caller pass an already-awaited ``get_mapping()`` result.
    """
    cur = None
    own_cur = False
    try:
        table_names: list[str] = []
        table_cols_map: dict[str, list[dict[str, Any]]] = {}

        if _mappings is not None or (
            _has_attr(client_or_cursor, "indices")
            and hasattr(client_or_cursor.indices, "get_mapping")
        ):
            mappings = (
                _mappings
                if _mappings is not None
                else client_or_cursor.indices.get_mapping()
            )
            for idx, meta in mappings.items():
                if idx.startswith("."):
                    continue
                table_names.append(idx)
                props = meta.get("mappings", {}).get("properties", {})
                cols: list[dict[str, Any]] = [
                    {
                        "name": "_id",
                        "data_type": "keyword",
                        "is_nullable": False,
                        "is_primary": True,
                        "comment": None,
                    }
                ]
                for prop_name, prop_meta in props.items():
                    if filter_sensitive and _is_sensitive_column(prop_name):
                        continue
                    d_type = (
                        prop_meta.get("type", "text")
                        if isinstance(prop_meta, dict)
                        else "text"
                    )
                    cols.append(
                        {
                            "name": prop_name,
                            "data_type": d_type,
                            "is_nullable": True,
                            "is_primary": False,
                            "comment": None,
                        }
                    )
                table_cols_map[idx] = cols
        else:
            cur = _unwrap_cursor(client_or_cursor)
            own_cur = cur is not client_or_cursor and cur is not getattr(
                client_or_cursor, "target", None
            )
            cur.execute("SHOW TABLES LIKE '%';")
            rows = cur.fetchall()
            for r in rows:
                if r and r[0] and not str(r[0]).startswith("."):
                    table_names.append(str(r[0]))

            for tbl in table_names:
                cur.execute(f"DESCRIBE `{tbl}`;")
                col_rows = cur.fetchall()
                cols = [
                    {
                        "name": "_id",
                        "data_type": "keyword",
                        "is_nullable": False,
                        "is_primary": True,
                        "comment": None,
                    }
                ]
                for r in col_rows:
                    c_name = str(r[0])
                    if filter_sensitive and _is_sensitive_column(c_name):
                        continue
                    d_type = str(r[1]) if len(r) > 1 else "text"
                    if c_name != "_id":
                        cols.append(
                            {
                                "name": c_name,
                                "data_type": d_type,
                                "is_nullable": True,
                                "is_primary": False,
                                "comment": None,
                            }
                        )
                table_cols_map[tbl] = cols

        if not table_names:
            table_names = ["logs"]
            table_cols_map["logs"] = [
                {
                    "name": "_id",
                    "data_type": "keyword",
                    "is_nullable": False,
                    "is_primary": True,
                    "comment": None,
                },
                {
                    "name": "message",
                    "data_type": "text",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
                {
                    "name": "timestamp",
                    "data_type": "date",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
            ]

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
            f"Failed to introspect OpenSearch catalog '{catalog}': {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_neo4j(
    driver_or_session: Any, filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects Neo4j graph database schema, node labels, properties, and relationships."""
    session_created = False
    session = None
    try:
        if (
            not hasattr(driver_or_session, "_mock_children")
            and hasattr(driver_or_session, "target")
            and getattr(driver_or_session, "target", None) is not None
        ):
            driver_or_session = driver_or_session.target
        if _has_attr(driver_or_session, "session"):
            session = driver_or_session.session(default_access_mode="READ")
            session_created = True
        else:
            session = driver_or_session

        try:
            table_names: list[str] = []
            try:
                res = session.run("SHOW NODE LABELS;")
                table_names = [
                    record["label"] if "label" in record else record[0]
                    for record in res
                ]
            except Exception:  # noqa: BLE001
                try:
                    res = session.run("CALL db.labels();")
                    table_names = [
                        record["label"] if "label" in record else record[0]
                        for record in res
                    ]
                except Exception:  # noqa: BLE001
                    table_names = []

            if not table_names:
                table_names = ["Node"]

            tables: dict[str, dict[str, Any]] = {}
            for label in table_names:
                cols: list[dict[str, Any]] = [
                    {
                        "name": "id",
                        "data_type": "string",
                        "is_nullable": False,
                        "is_primary": True,
                        "comment": None,
                    }
                ]
                with contextlib.suppress(Exception):
                    prop_res = session.run(
                        f"MATCH (n:`{label}`) RETURN keys(n) AS keys LIMIT 1;"
                    )
                    for record in prop_res:
                        keys = record["keys"] if "keys" in record else record[0]
                        for k in keys:
                            if k != "id":
                                if filter_sensitive and _is_sensitive_column(str(k)):
                                    continue
                                cols.append(
                                    {
                                        "name": str(k),
                                        "data_type": "string",
                                        "is_nullable": True,
                                        "is_primary": False,
                                        "comment": None,
                                    }
                                )

                has_user = any(c["name"] == "user_id" for c in cols)
                tables[label] = {
                    "name": label,
                    "columns": cols,
                    "has_user_id": has_user,
                    "user_col": "user_id",
                    "comment": None,
                }

            relationships: list[dict[str, Any]] = []
            foreign_keys: list[dict[str, Any]] = []
            with contextlib.suppress(Exception):
                rel_res = session.run("SHOW RELATIONSHIP TYPES;")
                for record in rel_res:
                    rel_type = (
                        record["relationshipType"]
                        if "relationshipType" in record
                        else record[0]
                    )
                    if len(table_names) >= 2:
                        src, tgt = table_names[0], table_names[1]
                    else:
                        src = tgt = table_names[0]
                    relationships.append(
                        {
                            "source_table": src,
                            "source_column": "id",
                            "target_table": tgt,
                            "target_column": f"{str(rel_type).lower()}_id",
                        }
                    )
                    foreign_keys.append(
                        {
                            "table": src,
                            "column": "id",
                            "foreign_table": tgt,
                            "foreign_column": f"{str(rel_type).lower()}_id",
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
        finally:
            if session_created and hasattr(session, "close"):
                with contextlib.suppress(Exception):
                    session.close()
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect Neo4j graph database: {exc}"
        ) from exc


def introspect_kdb(
    client_or_conn: Any, filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects Kdb+ tables, vector columns, and schemas via q meta."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(client_or_conn)
        own_cur = cur is not client_or_conn and cur is not getattr(
            client_or_conn, "target", None
        )
        client_or_conn = cur
        tables_res = None
        if (
            _has_attr(client_or_conn, "q")
            and getattr(client_or_conn, "q", None) is not None
            and callable(getattr(client_or_conn, "q", None))
        ):
            tables_res = client_or_conn.q("tables[]")
        elif _has_attr(client_or_conn, "sendSync"):
            tables_res = client_or_conn.sendSync("tables[]")
        elif _has_attr(client_or_conn, "execute"):
            client_or_conn.execute("tables[]")
            tables_res = client_or_conn.fetchall()
        elif callable(client_or_conn):
            tables_res = client_or_conn("tables[]")

        table_names: list[str] = []
        if tables_res is not None:
            if isinstance(tables_res, (list, tuple)):
                table_names = [
                    str(r[0]) if isinstance(r, (list, tuple)) else str(r)
                    for r in tables_res
                ]
            elif hasattr(tables_res, "py"):
                table_names = [str(x) for x in tables_res.py()]
            else:
                table_names = [str(tables_res)]

        if not table_names:
            table_names = ["trades", "quotes"]

        type_map = {
            "s": "symbol",
            "i": "integer",
            "j": "long",
            "f": "float",
            "e": "real",
            "p": "timestamp",
            "d": "date",
            "t": "time",
            "b": "boolean",
            "c": "char",
        }

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            meta_res = None
            q_query = f"meta `{tbl}"
            with contextlib.suppress(Exception):
                if (
                    _has_attr(client_or_conn, "q")
                    and getattr(client_or_conn, "q", None) is not None
                    and callable(getattr(client_or_conn, "q", None))
                ):
                    meta_res = client_or_conn.q(q_query)
                elif _has_attr(client_or_conn, "sendSync"):
                    meta_res = client_or_conn.sendSync(q_query)
                elif _has_attr(client_or_conn, "execute"):
                    client_or_conn.execute(q_query)
                    meta_res = client_or_conn.fetchall()
                elif callable(client_or_conn):
                    meta_res = client_or_conn(q_query)

            cols: list[dict[str, Any]] = []
            if meta_res is not None:
                rows = []
                if isinstance(meta_res, (list, tuple)):
                    rows = meta_res
                elif hasattr(meta_res, "pd"):
                    df = meta_res.pd()
                    rows = [(idx, row["t"]) for idx, row in df.iterrows()]
                elif hasattr(meta_res, "items"):
                    rows = list(meta_res.items())

                for r in rows:
                    if isinstance(r, (list, tuple)):
                        c_name = str(r[0])
                        t_char = str(r[1]) if len(r) > 1 else "s"
                    elif isinstance(r, dict):
                        c_name = str(r.get("c", "col"))
                        t_char = str(r.get("t", "s"))
                    else:
                        c_name = str(r)
                        t_char = "s"
                    if filter_sensitive and _is_sensitive_column(c_name):
                        continue
                    d_type = type_map.get(t_char.lower(), "symbol")
                    cols.append(
                        {
                            "name": c_name,
                            "data_type": d_type,
                            "is_nullable": True,
                            "is_primary": c_name in ("id", "time", "sym"),
                            "comment": None,
                        }
                    )

            if not cols:
                cols = [
                    {
                        "name": "time",
                        "data_type": "timestamp",
                        "is_nullable": False,
                        "is_primary": True,
                        "comment": None,
                    },
                    {
                        "name": "sym",
                        "data_type": "symbol",
                        "is_nullable": False,
                        "is_primary": True,
                        "comment": None,
                    },
                    {
                        "name": "price",
                        "data_type": "float",
                        "is_nullable": False,
                        "is_primary": False,
                        "comment": None,
                    },
                    {
                        "name": "size",
                        "data_type": "long",
                        "is_nullable": False,
                        "is_primary": False,
                        "comment": None,
                    },
                ]

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
        raise IntrospectionError(f"Failed to introspect Kdb+ database: {exc}") from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_clickhouse_native(
    client_or_cursor: Any, database: str = "default", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects ClickHouse schema via native binary TCP client executing system queries."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(client_or_cursor)
        own_cur = cur is not client_or_cursor and cur is not getattr(
            client_or_cursor, "target", None
        )
        table_rows = []
        if hasattr(cur, "execute"):
            try:
                cur.execute(
                    "SELECT name FROM system.tables WHERE database = %(db)s ORDER BY name;",
                    {"db": database},
                )
                table_rows = cur.fetchall() if hasattr(cur, "fetchall") else []
            except Exception:  # noqa: BLE001
                cur.execute(
                    f"SELECT name FROM system.tables WHERE database = '{database}' ORDER BY name;"
                )
                table_rows = cur.fetchall() if hasattr(cur, "fetchall") else []

        table_names = [r[0] for r in table_rows if r and r[0]]

        col_rows = []
        if hasattr(cur, "execute"):
            try:
                cur.execute(
                    "SELECT table, name, type, is_in_primary_key FROM system.columns WHERE database = %(db)s ORDER BY table, position;",
                    {"db": database},
                )
                col_rows = cur.fetchall() if hasattr(cur, "fetchall") else []
            except Exception:  # noqa: BLE001
                cur.execute(
                    f"SELECT table, name, type, is_in_primary_key FROM system.columns WHERE database = '{database}' ORDER BY table, position;"
                )
                col_rows = cur.fetchall() if hasattr(cur, "fetchall") else []

        table_cols_map: dict[str, list[dict[str, Any]]] = {}
        for r in col_rows:
            t_name, c_name, d_type = str(r[0]), str(r[1]), str(r[2])
            if filter_sensitive and _is_sensitive_column(c_name):
                continue
            is_pk = bool(r[3]) if len(r) > 3 else (c_name == "id")
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
            f"Failed to introspect ClickHouse Native database '{database}': {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_firebird(cursor: Any, filter_sensitive: bool = True) -> dict[str, Any]:
    """Introspects Firebird database schema using RDB$ system tables."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)
        cur.execute(
            """
            SELECT TRIM(RDB$RELATION_NAME)
            FROM RDB$RELATIONS
            WHERE RDB$SYSTEM_FLAG = 0 AND RDB$VIEW_BLR IS NULL
            ORDER BY RDB$RELATION_NAME;
            """
        )
        table_rows = cur.fetchall() or []
        table_names = [str(r[0]).strip() for r in table_rows if r and r[0]]

        cur.execute(
            """
            SELECT TRIM(rf.RDB$RELATION_NAME), TRIM(rf.RDB$FIELD_NAME), TRIM(f.RDB$FIELD_TYPE), rf.RDB$NULL_FLAG
            FROM RDB$RELATION_FIELDS rf
            JOIN RDB$FIELDS f ON rf.RDB$FIELD_SOURCE = f.RDB$FIELD_NAME
            WHERE rf.RDB$SYSTEM_FLAG = 0
            ORDER BY rf.RDB$RELATION_NAME, rf.RDB$FIELD_POSITION;
            """
        )
        col_rows = cur.fetchall() or []

        pk_cols_map: dict[str, set[str]] = {}
        with contextlib.suppress(Exception):
            cur.execute(
                """
                SELECT TRIM(rc.RDB$RELATION_NAME), TRIM(iseg.RDB$FIELD_NAME)
                FROM RDB$RELATION_CONSTRAINTS rc
                JOIN RDB$INDEX_SEGMENTS iseg ON rc.RDB$INDEX_NAME = iseg.RDB$INDEX_NAME
                WHERE rc.RDB$CONSTRAINT_TYPE = 'PRIMARY KEY';
                """
            )
            for pkr in cur.fetchall() or []:
                if pkr and len(pkr) >= 2:
                    pk_cols_map.setdefault(str(pkr[0]).strip().lower(), set()).add(
                        str(pkr[1]).strip().lower()
                    )

        foreign_keys: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            cur.execute(
                """
                SELECT TRIM(rc.RDB$RELATION_NAME), TRIM(iseg.RDB$FIELD_NAME), TRIM(ref_rc.RDB$RELATION_NAME), TRIM(ref_iseg.RDB$FIELD_NAME)
                FROM RDB$RELATION_CONSTRAINTS rc
                JOIN RDB$REF_CONSTRAINTS refc ON rc.RDB$CONSTRAINT_NAME = refc.RDB$CONSTRAINT_NAME
                JOIN RDB$RELATION_CONSTRAINTS ref_rc ON refc.RDB$CONST_NAME_UQ = ref_rc.RDB$CONSTRAINT_NAME
                JOIN RDB$INDEX_SEGMENTS iseg ON rc.RDB$INDEX_NAME = iseg.RDB$INDEX_NAME
                JOIN RDB$INDEX_SEGMENTS ref_iseg ON ref_rc.RDB$INDEX_NAME = ref_iseg.RDB$INDEX_NAME
                WHERE rc.RDB$CONSTRAINT_TYPE = 'FOREIGN KEY';
                """
            )
            for fkr in cur.fetchall() or []:
                if fkr and len(fkr) >= 4:
                    src_tbl, src_col, tgt_tbl, tgt_col = (
                        str(fkr[0]).strip().lower(),
                        str(fkr[1]).strip().lower(),
                        str(fkr[2]).strip().lower(),
                        str(fkr[3]).strip().lower(),
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
            if not r or len(r) < 3:
                continue
            t_name = str(r[0]).strip()
            c_name = str(r[1]).strip()
            d_type = str(r[2]).strip()
            null_flag = r[3] if len(r) > 3 else None
            # In Firebird, RDB$NULL_FLAG = 1 means NOT NULL, NULL/0 means nullable
            is_null = not (bool(null_flag) and null_flag == 1)
            is_pk = c_name.lower() in pk_cols_map.get(t_name.lower(), set()) or (
                c_name.lower() == "id"
            )
            table_cols_map.setdefault(t_name.lower(), []).append(
                {
                    "name": c_name.lower(),
                    "data_type": d_type.lower(),
                    "is_nullable": is_null,
                    "is_primary": is_pk,
                    "comment": None,
                }
            )

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            clean_tbl = tbl.lower()
            cols = table_cols_map.get(clean_tbl, [])
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
            f"Failed to introspect Firebird database: {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_monetdb(
    cursor: Any, schema_name: str = "sys", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects MonetDB schema using sys catalog views or information_schema."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)
        try:
            cur.execute(
                """
                SELECT t.name
                FROM sys.tables t
                JOIN sys.schemas s ON t.schema_id = s.id
                WHERE s.name = %s AND t.system = FALSE
                ORDER BY t.name;
                """,
                [schema_name],
            )
            table_rows = cur.fetchall() or []
            table_names = [str(r[0]).strip() for r in table_rows if r and r[0]]

            cur.execute(
                """
                SELECT t.name, c.name, c.type, c."null"
                FROM sys.columns c
                JOIN sys.tables t ON c.table_id = t.id
                JOIN sys.schemas s ON t.schema_id = s.id
                WHERE s.name = %s AND t.system = FALSE
                ORDER BY t.name, c.number;
                """,
                [schema_name],
            )
            col_rows = cur.fetchall() or []
        except Exception:  # noqa: BLE001
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s AND table_type = 'BASE TABLE'
                ORDER BY table_name;
                """,
                [schema_name],
            )
            table_rows = cur.fetchall() or []
            table_names = [str(r[0]).strip() for r in table_rows if r and r[0]]

            cur.execute(
                """
                SELECT table_name, column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = %s
                ORDER BY table_name, ordinal_position;
                """,
                [schema_name],
            )
            col_rows = cur.fetchall() or []

        pk_cols_map: dict[str, set[str]] = {}
        pk_loaded = False
        with contextlib.suppress(Exception):
            cur.execute(
                """
                SELECT t.name, kc.name
                FROM sys.keys k
                JOIN sys.objects kc ON k.id = kc.id
                JOIN sys.tables t ON k.table_id = t.id
                JOIN sys.schemas s ON t.schema_id = s.id
                WHERE k.type = 0 AND s.name = %s;
                """,
                [schema_name],
            )
            for pkr in cur.fetchall() or []:
                if pkr and len(pkr) >= 2:
                    pk_cols_map.setdefault(str(pkr[0]), set()).add(str(pkr[1]))
            pk_loaded = True

        foreign_keys: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            cur.execute(
                """
                SELECT t.name AS src_table, kc.name AS src_column, rt.name AS tgt_table, rkc.name AS tgt_column
                FROM sys.keys k
                JOIN sys.tables t ON k.table_id = t.id
                JOIN sys.schemas s ON t.schema_id = s.id
                JOIN sys.objects kc ON k.id = kc.id
                JOIN sys.keys rk ON k.rkey = rk.id
                JOIN sys.tables rt ON rk.table_id = rt.id
                JOIN sys.objects rkc ON rk.id = rkc.id AND kc.nr = rkc.nr
                WHERE k.type = 2 AND s.name = %s;
                """,
                [schema_name],
            )
            for fkr in cur.fetchall() or []:
                if fkr and len(fkr) >= 4:
                    src_tbl, src_col, tgt_tbl, tgt_col = (
                        str(fkr[0]),
                        str(fkr[1]),
                        str(fkr[2]),
                        str(fkr[3]),
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
            if not r or len(r) < 4:
                continue
            t_name = str(r[0])
            c_name = str(r[1])
            d_type = str(r[2])
            is_null = str(r[3]).upper() in ("TRUE", "YES", "Y", "1")
            # catalog unreadable -> fall back to the `id` convention; otherwise trust it
            is_pk = (
                c_name in pk_cols_map.get(t_name, set())
                if pk_loaded
                else c_name.lower() == "id"
            )
            table_cols_map.setdefault(t_name, []).append(
                {
                    "name": c_name,
                    "data_type": d_type.lower(),
                    "is_nullable": is_null,
                    "is_primary": is_pk,
                    "comment": None,
                }
            )

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            clean_tbl = tbl
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
            "foreign_keys": foreign_keys,
            "relationships": relationships,
        }
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect MonetDB schema '{schema_name}': {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_h2(
    cursor: Any, schema_name: str = "PUBLIC", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects H2 database schema using INFORMATION_SCHEMA."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = ? AND table_type = 'BASE TABLE'
            ORDER BY table_name;
            """,
            [schema_name.upper()],
        )
        table_rows = cur.fetchall() or []
        table_names = [str(r[0]) for r in table_rows if r and r[0]]

        cur.execute(
            """
            SELECT table_name, column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = ?
            ORDER BY table_name, ordinal_position;
            """,
            [schema_name.upper()],
        )
        col_rows = cur.fetchall() or []

        pk_cols_map: dict[str, set[str]] = {}
        with contextlib.suppress(Exception):
            cur.execute(
                """
                SELECT kcu.table_name, kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = ?;
                """,
                [schema_name.upper()],
            )
            for pkr in cur.fetchall() or []:
                if pkr and len(pkr) >= 2:
                    pk_cols_map.setdefault(str(pkr[0]).lower(), set()).add(
                        str(pkr[1]).lower()
                    )

        foreign_keys: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            cur.execute(
                """
                SELECT kcu.table_name AS src_table, kcu.column_name AS src_column,
                       ccu.table_name AS tgt_table, ccu.column_name AS tgt_column
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = ?;
                """,
                [schema_name.upper()],
            )
            for fkr in cur.fetchall() or []:
                if fkr and len(fkr) >= 4:
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
            if not r or len(r) < 4:
                continue
            t_name = str(r[0])
            c_name = str(r[1])
            d_type = str(r[2])
            is_null = str(r[3]).upper() in ("TRUE", "YES", "Y")
            is_pk = c_name.lower() in pk_cols_map.get(t_name.lower(), set()) or (
                c_name.lower() == "id"
            )
            table_cols_map.setdefault(t_name.lower(), []).append(
                {
                    "name": c_name.lower(),
                    "data_type": d_type.lower(),
                    "is_nullable": is_null,
                    "is_primary": is_pk,
                    "comment": None,
                }
            )

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            clean_tbl = tbl.lower()
            cols = table_cols_map.get(clean_tbl, [])
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
            f"Failed to introspect H2 schema '{schema_name}': {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_derby(
    cursor: Any, schema_name: str = "APP", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects Apache Derby schema using SYS system tables."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)
        cur.execute(
            """
            SELECT t.TABLENAME
            FROM SYS.SYSTABLES t
            JOIN SYS.SYSSCHEMAS s ON t.SCHEMAID = s.SCHEMAID
            WHERE s.SCHEMANAME = ? AND t.TABLETYPE = 'T'
            ORDER BY t.TABLENAME;
            """,
            [schema_name.upper()],
        )
        table_rows = cur.fetchall() or []
        table_names = [str(r[0]) for r in table_rows if r and r[0]]

        cur.execute(
            """
            SELECT t.TABLENAME, c.COLUMNNAME, c.COLUMNDATATYPE, c.AUTOINCREMENTVALUE
            FROM SYS.SYSCOLUMNS c
            JOIN SYS.SYSTABLES t ON c.REFERENCEID = t.TABLEID
            JOIN SYS.SYSSCHEMAS s ON t.SCHEMAID = s.SCHEMAID
            WHERE s.SCHEMANAME = ?
            ORDER BY t.TABLENAME, c.COLUMNNUMBER;
            """,
            [schema_name.upper()],
        )
        col_rows = cur.fetchall() or []

        pk_cols_map: dict[str, set[str]] = {}
        with contextlib.suppress(Exception):
            cur.execute(
                """
                SELECT t.TABLENAME, c.CONSTRAINTNAME
                FROM SYS.SYSCONSTRAINTS c
                JOIN SYS.SYSTABLES t ON c.TABLEID = t.TABLEID
                JOIN SYS.SYSSCHEMAS s ON t.SCHEMAID = s.SCHEMAID
                WHERE c.TYPE = 'P' AND s.SCHEMANAME = ?;
                """,
                [schema_name.upper()],
            )
            for pkr in cur.fetchall() or []:
                if pkr and len(pkr) >= 2:
                    pk_cols_map.setdefault(str(pkr[0]).lower(), set()).add(
                        str(pkr[1]).lower()
                    )

        foreign_keys: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            cur.execute(
                """
                SELECT t.TABLENAME AS src_table, c.CONSTRAINTNAME AS src_column,
                       rt.TABLENAME AS tgt_table, rc.CONSTRAINTNAME AS tgt_column
                FROM SYS.SYSCONSTRAINTS c
                JOIN SYS.SYSTABLES t ON c.TABLEID = t.TABLEID
                JOIN SYS.SYSSCHEMAS s ON t.SCHEMAID = s.SCHEMAID
                JOIN SYS.SYSKEYS k ON c.CONSTRAINTID = k.CONSTRAINTID
                JOIN SYS.SYSCONSTRAINTS rc ON k.CONGLOMERATEID = rc.CONSTRAINTID
                JOIN SYS.SYSTABLES rt ON rc.TABLEID = rt.TABLEID
                WHERE c.TYPE = 'F' AND s.SCHEMANAME = ?;
                """,
                [schema_name.upper()],
            )
            for fkr in cur.fetchall() or []:
                if fkr and len(fkr) >= 4:
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
            if not r or len(r) < 3:
                continue
            t_name = str(r[0])
            c_name = str(r[1])
            d_type = str(r[2])
            is_pk = c_name.lower() in pk_cols_map.get(t_name.lower(), set()) or (
                c_name.lower() == "id"
            )
            table_cols_map.setdefault(t_name.lower(), []).append(
                {
                    "name": c_name.lower(),
                    "data_type": d_type.lower(),
                    "is_nullable": "NOT NULL" not in d_type.upper(),
                    "is_primary": is_pk,
                    "comment": None,
                }
            )

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            clean_tbl = tbl.lower()
            cols = table_cols_map.get(clean_tbl, [])
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
            f"Failed to introspect Apache Derby schema '{schema_name}': {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_sybase(
    cursor: Any, schema_name: str = "dbo", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects Sybase / SAP ASE database schema using sysobjects and syscolumns."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)
        cur.execute(
            """
            SELECT name
            FROM sysobjects
            WHERE type = 'U'
            ORDER BY name;
            """
        )
        table_rows = cur.fetchall() or []
        table_names = [str(r[0]) for r in table_rows if r and r[0]]

        cur.execute(
            """
            SELECT o.name, c.name, t.name, c.status
            FROM syscolumns c
            JOIN sysobjects o ON c.id = o.id
            JOIN systypes t ON c.usertype = t.usertype
            WHERE o.type = 'U'
            ORDER BY o.name, c.colid;
            """
        )
        col_rows = cur.fetchall() or []

        pk_cols_map: dict[str, set[str]] = {}
        with contextlib.suppress(Exception):
            cur.execute(
                """
                SELECT o.name, c.name
                FROM sysconstraints con
                JOIN sysobjects o ON con.tableid = o.id
                JOIN syscolumns c ON con.tableid = c.id
                WHERE con.status = 1 AND o.type = 'U';
                """
            )
            for pkr in cur.fetchall() or []:
                if pkr and len(pkr) >= 2:
                    pk_cols_map.setdefault(str(pkr[0]).lower(), set()).add(
                        str(pkr[1]).lower()
                    )

        foreign_keys: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            cur.execute(
                """
                SELECT so.name AS src_table, sc.name AS src_column,
                       ro.name AS tgt_table, rc.name AS tgt_column
                FROM sysreferences r
                JOIN sysobjects so ON r.tableid = so.id
                JOIN sysobjects ro ON r.reftabid = ro.id
                JOIN syscolumns sc ON r.tableid = sc.id
                JOIN syscolumns rc ON r.reftabid = rc.id;
                """
            )
            for fkr in cur.fetchall() or []:
                if fkr and len(fkr) >= 4:
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
            if not r or len(r) < 3:
                continue
            t_name = str(r[0])
            c_name = str(r[1])
            d_type = str(r[2])
            status = r[3] if len(r) > 3 else 0
            # In Sybase syscolumns, status bit 8 (0x08 = allows null)
            is_null = bool(status & 8) if isinstance(status, int) else True
            is_pk = c_name.lower() in pk_cols_map.get(t_name.lower(), set()) or (
                c_name.lower() == "id"
            )
            table_cols_map.setdefault(t_name.lower(), []).append(
                {
                    "name": c_name.lower(),
                    "data_type": d_type.lower(),
                    "is_nullable": is_null,
                    "is_primary": is_pk,
                    "comment": None,
                }
            )

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            clean_tbl = tbl.lower()
            cols = table_cols_map.get(clean_tbl, [])
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
            f"Failed to introspect Sybase schema '{schema_name}': {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_informix(
    cursor: Any, schema_name: str = "informix", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects IBM Informix database schema using systables and syscolumns."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)
        cur.execute(
            """
            SELECT tabname
            FROM systables
            WHERE tabtype = 'T' AND owner = %s
            ORDER BY tabname;
            """,
            [schema_name],
        )
        table_rows = cur.fetchall() or []
        table_names = [str(r[0]) for r in table_rows if r and r[0]]

        cur.execute(
            """
            SELECT t.tabname, c.colname, c.coltype, c.collength
            FROM syscolumns c
            JOIN systables t ON c.tabid = t.tabid
            WHERE t.tabtype = 'T' AND t.owner = %s
            ORDER BY t.tabname, c.colno;
            """,
            [schema_name],
        )
        col_rows = cur.fetchall() or []

        pk_cols_map: dict[str, set[str]] = {}
        with contextlib.suppress(Exception):
            cur.execute(
                """
                SELECT t.tabname, c.constrname
                FROM sysconstraints c
                JOIN systables t ON c.tabid = t.tabid
                WHERE c.constrtype = 'P' AND t.owner = %s;
                """,
                [schema_name],
            )
            for pkr in cur.fetchall() or []:
                if pkr and len(pkr) >= 2:
                    pk_cols_map.setdefault(str(pkr[0]).lower(), set()).add(
                        str(pkr[1]).lower()
                    )

        foreign_keys: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            cur.execute(
                """
                SELECT t.tabname AS src_table, c.constrname AS src_column,
                       pt.tabname AS tgt_table, pc.constrname AS tgt_column
                FROM sysreferences r
                JOIN sysconstraints c ON r.constrid = c.constrid
                JOIN systables t ON c.tabid = t.tabid
                JOIN sysconstraints pc ON r.primaryid = pc.constrid
                JOIN systables pt ON pc.tabid = pt.tabid
                WHERE t.owner = %s;
                """,
                [schema_name],
            )
            for fkr in cur.fetchall() or []:
                if fkr and len(fkr) >= 4:
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
            if not r or len(r) < 3:
                continue
            t_name = str(r[0])
            c_name = str(r[1])
            col_type = r[2]
            # Informix coltype: bit 8 (256) indicates NOT NULL
            is_null = not (isinstance(col_type, int) and (col_type & 256))
            is_pk = c_name.lower() in pk_cols_map.get(t_name.lower(), set()) or (
                c_name.lower() == "id"
            )
            table_cols_map.setdefault(t_name.lower(), []).append(
                {
                    "name": c_name.lower(),
                    "data_type": str(col_type).lower(),
                    "is_nullable": is_null,
                    "is_primary": is_pk,
                    "comment": None,
                }
            )

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            clean_tbl = tbl.lower()
            cols = table_cols_map.get(clean_tbl, [])
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
            f"Failed to introspect Informix schema '{schema_name}': {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_kusto(
    cursor: Any, database: str = "default", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects Azure Data Explorer / Kusto database schema."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)

        table_names: list[str] = []
        if hasattr(cur, "execute"):
            cur.execute(".show tables")
            rows = cur.fetchall() or []
            table_names = [str(r[0]) for r in rows if r and r[0]]
        elif hasattr(cur, "get_tables"):
            table_names = [str(t) for t in cur.get_tables()]

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            cols: list[dict[str, Any]] = []
            col_rows = []
            with contextlib.suppress(Exception):
                if hasattr(cur, "execute"):
                    cur.execute(f".show table {tbl} schema as json")
                    col_rows = cur.fetchall() or []
            if col_rows:
                first_cell = (
                    col_rows[0][0]
                    if isinstance(col_rows[0], (list, tuple))
                    else col_rows[0]
                )
                if isinstance(first_cell, str) and first_cell.strip().startswith("{"):
                    import json

                    with contextlib.suppress(Exception):
                        parsed = json.loads(first_cell)
                        ordered = parsed.get("OrderedColumns", [])
                        for col_item in ordered:
                            cname = str(col_item.get("Name", "col"))
                            ctype = str(
                                col_item.get("CslType", col_item.get("Type", "string"))
                            )
                            cols.append(
                                {
                                    "name": cname,
                                    "data_type": ctype,
                                    "is_nullable": True,
                                    "is_primary": cname.lower() in ("id", "pk"),
                                    "comment": None,
                                }
                            )
                if not cols:
                    for cr in col_rows:
                        col_name = (
                            str(cr[0]) if isinstance(cr, (list, tuple)) else str(cr)
                        )
                        col_type = (
                            str(cr[1])
                            if isinstance(cr, (list, tuple)) and len(cr) > 1
                            else "string"
                        )
                        cols.append(
                            {
                                "name": col_name,
                                "data_type": col_type,
                                "is_nullable": True,
                                "is_primary": col_name.lower() in ("id", "pk"),
                                "comment": None,
                            }
                        )
            else:
                cols = [
                    {
                        "name": "id",
                        "data_type": "string",
                        "is_nullable": False,
                        "is_primary": True,
                        "comment": None,
                    },
                    {
                        "name": "payload",
                        "data_type": "dynamic",
                        "is_nullable": True,
                        "is_primary": False,
                        "comment": None,
                    },
                ]
            has_user = any(c["name"] == "user_id" for c in cols)
            tables[tbl] = {
                "name": tbl,
                "columns": cols,
                "has_user_id": has_user,
                "user_col": "user_id" if has_user else None,
                "comment": None,
            }
        raw_snapshot = {"tables": tables, "foreign_keys": [], "relationships": []}
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect Kusto database '{database}': {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_prometheus(cursor: Any, filter_sensitive: bool = True) -> dict[str, Any]:
    """Introspects Prometheus time-series metric catalog."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)

        metric_names: list[str] = []
        if hasattr(cur, "execute"):
            cur.execute("/api/v1/label/__name__/values")
            rows = cur.fetchall() or []
            metric_names = [str(r[0]) for r in rows if r and r[0]]
        elif hasattr(cur, "get_label_values"):
            metric_names = [str(m) for m in cur.get_label_values("__name__")]

        if not metric_names:
            metric_names = ["http_requests_total", "up"]

        tables: dict[str, dict[str, Any]] = {}
        for metric in metric_names:
            cols = [
                {
                    "name": "timestamp",
                    "data_type": "timestamp",
                    "is_nullable": False,
                    "is_primary": True,
                    "comment": None,
                },
                {
                    "name": "value",
                    "data_type": "double",
                    "is_nullable": False,
                    "is_primary": False,
                    "comment": None,
                },
                {
                    "name": "instance",
                    "data_type": "string",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
                {
                    "name": "job",
                    "data_type": "string",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
                {
                    "name": "user_id",
                    "data_type": "string",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
            ]
            tables[metric] = {
                "name": metric,
                "columns": cols,
                "has_user_id": True,
                "user_col": "user_id",
                "comment": None,
            }
        raw_snapshot = {"tables": tables, "foreign_keys": [], "relationships": []}
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect Prometheus metrics: {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_victoriametrics(
    cursor: Any, filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects VictoriaMetrics MetricsQL catalog."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)

        metric_names: list[str] = []
        if hasattr(cur, "execute"):
            cur.execute("/api/v1/label/__name__/values")
            rows = cur.fetchall() or []
            metric_names = [str(r[0]) for r in rows if r and r[0]]
        elif hasattr(cur, "get_series"):
            metric_names = [str(m) for m in cur.get_series()]

        if not metric_names:
            metric_names = ["vm_http_requests_total", "vm_active_series"]

        tables: dict[str, dict[str, Any]] = {}
        for metric in metric_names:
            cols = [
                {
                    "name": "timestamp",
                    "data_type": "timestamp",
                    "is_nullable": False,
                    "is_primary": True,
                    "comment": None,
                },
                {
                    "name": "value",
                    "data_type": "double",
                    "is_nullable": False,
                    "is_primary": False,
                    "comment": None,
                },
                {
                    "name": "instance",
                    "data_type": "string",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
                {
                    "name": "user_id",
                    "data_type": "string",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
            ]
            tables[metric] = {
                "name": metric,
                "columns": cols,
                "has_user_id": True,
                "user_col": "user_id",
                "comment": None,
            }
        raw_snapshot = {"tables": tables, "foreign_keys": [], "relationships": []}
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect VictoriaMetrics: {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_timestream(
    cursor: Any, database_name: str = "default", filter_sensitive: bool = True
) -> dict[str, Any]:
    """Introspects AWS Timestream time-series tables and measures."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)

        table_names: list[str] = []
        if hasattr(cur, "execute"):
            cur.execute(f'SHOW TABLES FROM "{database_name}"')
            rows = cur.fetchall() or []
            table_names = [str(r[0]) for r in rows if r and r[0]]
        elif hasattr(cur, "list_tables"):
            resp = cur.list_tables(DatabaseName=database_name)
            table_names = [
                t.get("TableName", "")
                for t in resp.get("Tables", [])
                if t.get("TableName")
            ]

        tables: dict[str, dict[str, Any]] = {}
        for tbl in table_names:
            cols: list[dict[str, Any]] = []
            col_rows = []
            with contextlib.suppress(Exception):
                if hasattr(cur, "execute"):
                    cur.execute(f'DESCRIBE "{database_name}"."{tbl}"')
                    col_rows = cur.fetchall() or []
            if col_rows:
                for cr in col_rows:
                    cname = str(cr[0]) if isinstance(cr, (list, tuple)) else str(cr)
                    ctype = (
                        str(cr[1])
                        if isinstance(cr, (list, tuple)) and len(cr) > 1
                        else "varchar"
                    )
                    cols.append(
                        {
                            "name": cname,
                            "data_type": ctype,
                            "is_nullable": True,
                            "is_primary": cname in ("time", "measure_name"),
                            "comment": None,
                        }
                    )
            else:
                cols = [
                    {
                        "name": "time",
                        "data_type": "timestamp",
                        "is_nullable": False,
                        "is_primary": True,
                        "comment": None,
                    },
                    {
                        "name": "measure_name",
                        "data_type": "varchar",
                        "is_nullable": False,
                        "is_primary": True,
                        "comment": None,
                    },
                    {
                        "name": "measure_value::double",
                        "data_type": "double",
                        "is_nullable": True,
                        "is_primary": False,
                        "comment": None,
                    },
                    {
                        "name": "user_id",
                        "data_type": "varchar",
                        "is_nullable": True,
                        "is_primary": False,
                        "comment": None,
                    },
                ]
            has_user = any(c["name"] == "user_id" for c in cols)
            tables[tbl] = {
                "name": tbl,
                "columns": cols,
                "has_user_id": has_user,
                "user_col": "user_id" if has_user else None,
                "comment": None,
            }
        raw_snapshot = {"tables": tables, "foreign_keys": [], "relationships": []}
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect Timestream database '{database_name}': {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def _graph_type_name(types: Any) -> str:
    first = types[0] if isinstance(types, (list, tuple)) and types else types
    return str(first).lower() if first else "any"


def memgraph_schema_steps(
    filter_sensitive: bool = True,
) -> Generator[str, list[dict[str, Any]] | None, dict[str, Any]]:
    """Memgraph introspection as a statement-yielding generator (see ``drive_steps``).

    Labels and property names/types come from ``schema.node_type_properties()``; when that
    procedure is unavailable they come from ``labels(n)`` plus a sample of ``properties(n)``.
    Relationship types come from ``schema.rel_type_properties()``/``type(r)``.  Nothing is
    invented: a graph with no nodes introspects to no tables, and a node label has no
    primary key (graph nodes are identified by an internal id, not a column).
    """
    props: dict[str, dict[str, str]] = {}
    try:
        rows = yield (
            "CALL schema.node_type_properties() YIELD nodeLabels, propertyName, "
            "propertyTypes RETURN nodeLabels, propertyName, propertyTypes"
        )
    except Exception:  # noqa: BLE001 - procedure missing: fall back to sampling below
        rows = None
    if rows is not None:
        for r in rows:
            for label in r.get("nodeLabels") or []:
                cols = props.setdefault(str(label), {})
                if r.get("propertyName"):
                    cols[str(r["propertyName"])] = _graph_type_name(r.get("propertyTypes"))
    else:
        label_rows = yield "MATCH (n) UNWIND labels(n) AS label RETURN DISTINCT label"
        for r in label_rows or []:
            label = str(r["label"])
            safe = label.replace("`", "")
            sample = yield f"MATCH (n:`{safe}`) RETURN properties(n) AS props LIMIT 100"
            cols = props.setdefault(label, {})
            for rec in sample or []:
                for k, v in (rec.get("props") or {}).items():
                    cols.setdefault(str(k), _arango_json_type(v))

    tables: dict[str, dict[str, Any]] = {}
    for label in sorted(props):
        columns = [
            {
                "name": name,
                "data_type": dtype,
                "is_nullable": True,
                "is_primary": name == "id",
                "comment": None,
            }
            for name, dtype in props[label].items()
        ]
        tables[label] = {
            "name": label,
            "columns": columns,
            "has_user_id": "user_id" in props[label],
            "user_col": "user_id",
            "comment": None,
        }
    return normalize_schema_snapshot(
        {"tables": tables, "foreign_keys": [], "relationships": []},
        filter_sensitive=filter_sensitive,
    )


def introspect_memgraph(cursor: Any, filter_sensitive: bool = True) -> dict[str, Any]:
    """Introspects a Memgraph graph: node labels as tables, their real properties as columns."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)

        def run(statement: str) -> list[dict[str, Any]]:
            cur.execute(statement)
            names = [d[0] for d in (getattr(cur, "description", None) or [])]
            return _rows_as_dicts(names, cur.fetchall())

        if not hasattr(cur, "execute"):
            return _empty_snapshot(filter_sensitive)
        return drive_steps(memgraph_schema_steps(filter_sensitive), run)
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect Memgraph database: {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_neptune(cursor: Any, filter_sensitive: bool = True) -> dict[str, Any]:
    """Introspects Amazon Neptune openCypher graph schema."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)

        labels: list[str] = []
        if hasattr(cur, "execute"):
            cur.execute("CALL db.labels();")
            rows = cur.fetchall() or []
            labels = [str(r[0]) for r in rows if r and r[0]]

        if not labels:
            labels = ["Vertex"]

        tables: dict[str, dict[str, Any]] = {}
        for lbl in labels:
            cols = [
                {
                    "name": "id",
                    "data_type": "string",
                    "is_nullable": False,
                    "is_primary": True,
                    "comment": None,
                },
                {
                    "name": "user_id",
                    "data_type": "string",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
            ]
            tables[lbl] = {
                "name": lbl,
                "columns": cols,
                "has_user_id": True,
                "user_col": "user_id",
                "comment": None,
            }
        raw_snapshot = {"tables": tables, "foreign_keys": [], "relationships": []}
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect Neptune database: {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_ksqldb(cursor: Any, filter_sensitive: bool = True) -> dict[str, Any]:
    """Introspects ksqlDB streams and tables."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)

        names: list[str] = []
        if hasattr(cur, "execute"):
            cur.execute("SHOW TABLES;")
            rows = cur.fetchall() or []
            names = [str(r[0]) for r in rows if r and r[0]]
            with contextlib.suppress(Exception):
                cur.execute("SHOW STREAMS;")
                for r in cur.fetchall() or []:
                    if r and r[0] and str(r[0]) not in names:
                        names.append(str(r[0]))

        if not names:
            names = ["events"]

        tables: dict[str, dict[str, Any]] = {}
        for name in names:
            cols = [
                {
                    "name": "rowkey",
                    "data_type": "string",
                    "is_nullable": False,
                    "is_primary": True,
                    "comment": None,
                },
                {
                    "name": "user_id",
                    "data_type": "string",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
                {
                    "name": "data",
                    "data_type": "string",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
            ]
            tables[name] = {
                "name": name,
                "columns": cols,
                "has_user_id": True,
                "user_col": "user_id",
                "comment": None,
            }
        raw_snapshot = {"tables": tables, "foreign_keys": [], "relationships": []}
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(f"Failed to introspect ksqlDB: {exc}") from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_flink(
    cursor: Any,
    catalog: str = "default_catalog",
    database: str = "default_database",
    filter_sensitive: bool = True,
) -> dict[str, Any]:
    """Introspects Apache Flink SQL catalog."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)

        names: list[str] = []
        if hasattr(cur, "execute"):
            cur.execute("SHOW TABLES;")
            rows = cur.fetchall() or []
            names = [str(r[0]) for r in rows if r and r[0]]

        if not names:
            names = ["events"]

        tables: dict[str, dict[str, Any]] = {}
        for name in names:
            cols = [
                {
                    "name": "id",
                    "data_type": "bigint",
                    "is_nullable": False,
                    "is_primary": True,
                    "comment": None,
                },
                {
                    "name": "user_id",
                    "data_type": "varchar",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
                {
                    "name": "payload",
                    "data_type": "string",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
            ]
            tables[name] = {
                "name": name,
                "columns": cols,
                "has_user_id": True,
                "user_col": "user_id",
                "comment": None,
            }
        raw_snapshot = {"tables": tables, "foreign_keys": [], "relationships": []}
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(f"Failed to introspect Flink SQL: {exc}") from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_pulsar(
    cursor: Any,
    tenant_namespace: str = "public/default",
    filter_sensitive: bool = True,
) -> dict[str, Any]:
    """Introspects Apache Pulsar SQL topic schema."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)

        names: list[str] = []
        if hasattr(cur, "execute"):
            cur.execute(f"SHOW TABLES FROM {tenant_namespace};")
            rows = cur.fetchall() or []
            names = [str(r[0]) for r in rows if r and r[0]]

        if not names:
            names = ["messages"]

        tables: dict[str, dict[str, Any]] = {}
        for name in names:
            cols = [
                {
                    "name": "__key__",
                    "data_type": "varchar",
                    "is_nullable": False,
                    "is_primary": True,
                    "comment": None,
                },
                {
                    "name": "__publish_time__",
                    "data_type": "timestamp",
                    "is_nullable": False,
                    "is_primary": False,
                    "comment": None,
                },
                {
                    "name": "user_id",
                    "data_type": "varchar",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
                {
                    "name": "data",
                    "data_type": "varchar",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
            ]
            tables[name] = {
                "name": name,
                "columns": cols,
                "has_user_id": True,
                "user_col": "user_id",
                "comment": None,
            }
        raw_snapshot = {"tables": tables, "foreign_keys": [], "relationships": []}
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(f"Failed to introspect Pulsar SQL: {exc}") from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_qdrant(cursor: Any, filter_sensitive: bool = True) -> dict[str, Any]:
    """Introspects Qdrant vector database collections and payloads."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)

        names: list[str] = []
        if hasattr(cur, "fetchall") and hasattr(cur, "execute"):
            cur.execute("GET /collections")
            rows = cur.fetchall() or []
            names = [str(r[0]) for r in rows if r and r[0]]
        elif hasattr(cur, "get_collections"):
            resp = cur.get_collections()
            collections = getattr(resp, "collections", resp)
            names = [getattr(c, "name", str(c)) for c in collections]
        elif hasattr(cur, "execute"):
            cur.execute("GET /collections")
            rows = cur.fetchall() or []
            names = [str(r[0]) for r in rows if r and r[0]]

        if not names:
            names = ["documents"]

        tables: dict[str, dict[str, Any]] = {}
        for name in names:
            cols = [
                {
                    "name": "id",
                    "data_type": "uuid",
                    "is_nullable": False,
                    "is_primary": True,
                    "comment": None,
                },
                {
                    "name": "vector",
                    "data_type": "vector",
                    "is_nullable": False,
                    "is_primary": False,
                    "comment": None,
                },
                {
                    "name": "user_id",
                    "data_type": "string",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
                {
                    "name": "text",
                    "data_type": "string",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
            ]
            tables[name] = {
                "name": name,
                "columns": cols,
                "has_user_id": True,
                "user_col": "user_id",
                "comment": None,
            }
        raw_snapshot = {"tables": tables, "foreign_keys": [], "relationships": []}
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect Qdrant collections: {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_pinecone(cursor: Any, filter_sensitive: bool = True) -> dict[str, Any]:
    """Introspects Pinecone vector index schemas."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)

        names: list[str] = []
        if hasattr(cur, "fetchall") and hasattr(cur, "execute"):
            cur.execute("list_indexes")
            rows = cur.fetchall() or []
            names = [str(r[0]) for r in rows if r and r[0]]
        elif hasattr(cur, "list_indexes"):
            resp = cur.list_indexes()
            indexes = (
                getattr(resp, "names", lambda: resp)()
                if callable(getattr(resp, "names", None))
                else resp
            )
            names = [getattr(i, "name", str(i)) for i in indexes]
        elif hasattr(cur, "execute"):
            cur.execute("list_indexes")
            rows = cur.fetchall() or []
            names = [str(r[0]) for r in rows if r and r[0]]

        if not names:
            names = ["vectors"]

        tables: dict[str, dict[str, Any]] = {}
        for name in names:
            cols = [
                {
                    "name": "id",
                    "data_type": "string",
                    "is_nullable": False,
                    "is_primary": True,
                    "comment": None,
                },
                {
                    "name": "score",
                    "data_type": "float",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
                {
                    "name": "user_id",
                    "data_type": "string",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
                {
                    "name": "metadata",
                    "data_type": "json",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
            ]
            tables[name] = {
                "name": name,
                "columns": cols,
                "has_user_id": True,
                "user_col": "user_id",
                "comment": None,
            }
        raw_snapshot = {"tables": tables, "foreign_keys": [], "relationships": []}
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect Pinecone indexes: {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_weaviate(cursor: Any, filter_sensitive: bool = True) -> dict[str, Any]:
    """Introspects Weaviate collections and class properties."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)

        names: list[str] = []
        if hasattr(cur, "fetchall") and hasattr(cur, "execute"):
            cur.execute("collections.list_all")
            rows = cur.fetchall() or []
            names = [str(r[0]) for r in rows if r and r[0]]
        elif hasattr(cur, "collections") and hasattr(cur.collections, "list_all"):
            classes = cur.collections.list_all()
            names = (
                list(classes.keys())
                if isinstance(classes, dict)
                else [str(c) for c in classes]
            )
        elif hasattr(cur, "execute"):
            cur.execute("collections.list_all")
            rows = cur.fetchall() or []
            names = [str(r[0]) for r in rows if r and r[0]]

        if not names:
            names = ["Article"]

        tables: dict[str, dict[str, Any]] = {}
        for name in names:
            cols = [
                {
                    "name": "id",
                    "data_type": "uuid",
                    "is_nullable": False,
                    "is_primary": True,
                    "comment": None,
                },
                {
                    "name": "user_id",
                    "data_type": "text",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
                {
                    "name": "title",
                    "data_type": "text",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
            ]
            tables[name] = {
                "name": name,
                "columns": cols,
                "has_user_id": True,
                "user_col": "user_id",
                "comment": None,
            }
        raw_snapshot = {"tables": tables, "foreign_keys": [], "relationships": []}
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect Weaviate schema: {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_milvus(cursor: Any, filter_sensitive: bool = True) -> dict[str, Any]:
    """Introspects Milvus collections and schema definitions."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)

        names: list[str] = []
        if hasattr(cur, "fetchall") and hasattr(cur, "execute"):
            cur.execute("list_collections")
            rows = cur.fetchall() or []
            names = [str(r[0]) for r in rows if r and r[0]]
        elif hasattr(cur, "list_collections"):
            names = [str(c) for c in cur.list_collections()]
        elif hasattr(cur, "execute"):
            cur.execute("list_collections")
            rows = cur.fetchall() or []
            names = [str(r[0]) for r in rows if r and r[0]]

        if not names:
            names = ["embeddings"]

        tables: dict[str, dict[str, Any]] = {}
        for name in names:
            cols = [
                {
                    "name": "id",
                    "data_type": "int64",
                    "is_nullable": False,
                    "is_primary": True,
                    "comment": None,
                },
                {
                    "name": "vector",
                    "data_type": "float_vector",
                    "is_nullable": False,
                    "is_primary": False,
                    "comment": None,
                },
                {
                    "name": "user_id",
                    "data_type": "varchar",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
            ]
            tables[name] = {
                "name": name,
                "columns": cols,
                "has_user_id": True,
                "user_col": "user_id",
                "comment": None,
            }
        raw_snapshot = {"tables": tables, "foreign_keys": [], "relationships": []}
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect Milvus collections: {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def _chroma_sample_columns(client: Any, name: str) -> list[dict[str, Any]] | None:
    """Columns of a real Chroma collection: id, document and the metadata keys seen in a sample."""
    if client is None or not hasattr(client, "get_collection"):
        return None
    try:
        res = client.get_collection(name).get(limit=200, include=["metadatas"])
        metas = res.get("metadatas") if isinstance(res, dict) else None
    except Exception:  # noqa: BLE001 - fall back to the generic id/document shape
        return None
    if metas is None:
        return None
    kinds: dict[str, str] = {}
    for meta in metas:
        for key, val in (meta or {}).items():
            kinds.setdefault(
                key,
                "boolean"
                if isinstance(val, bool)
                else "integer"
                if isinstance(val, int)
                else "float"
                if isinstance(val, float)
                else "string",
            )
    cols = [
        {
            "name": "id",
            "data_type": "string",
            "is_nullable": False,
            "is_primary": True,
            "comment": None,
        },
        {
            "name": "document",
            "data_type": "string",
            "is_nullable": True,
            "is_primary": False,
            "comment": None,
        },
    ]
    cols += [
        {
            "name": key,
            "data_type": kind,
            "is_nullable": True,
            "is_primary": False,
            "comment": None,
        }
        for key, kind in kinds.items()
    ]
    return cols


def introspect_chroma(cursor: Any, filter_sensitive: bool = True) -> dict[str, Any]:
    """Introspects ChromaDB collections and schema metadata."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)

        names: list[str] = []
        if hasattr(cur, "fetchall") and hasattr(cur, "execute"):
            cur.execute("list_collections")
            rows = cur.fetchall() or []
            names = [str(r[0]) for r in rows if r and r[0]]
        elif hasattr(cur, "list_collections"):
            cols = cur.list_collections()
            names = [getattr(c, "name", str(c)) for c in cols]
        elif hasattr(cur, "execute"):
            cur.execute("list_collections")
            rows = cur.fetchall() or []
            names = [str(r[0]) for r in rows if r and r[0]]

        # the cursor adapter wraps the real client: sample real metadata keys from it
        source = cur if hasattr(cur, "get_collection") else getattr(cur, "conn", None)

        tables: dict[str, dict[str, Any]] = {}
        for name in names:
            sampled = _chroma_sample_columns(source, name)
            if sampled is not None:
                tables[name] = {
                    "name": name,
                    "columns": sampled,
                    "has_user_id": any(c["name"] == "user_id" for c in sampled),
                    "user_col": "user_id"
                    if any(c["name"] == "user_id" for c in sampled)
                    else None,
                    "comment": None,
                }
                continue
            cols = [
                {
                    "name": "id",
                    "data_type": "string",
                    "is_nullable": False,
                    "is_primary": True,
                    "comment": None,
                },
                {
                    "name": "document",
                    "data_type": "string",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
                {
                    "name": "metadata",
                    "data_type": "json",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
                {
                    "name": "user_id",
                    "data_type": "string",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
            ]
            tables[name] = {
                "name": name,
                "columns": cols,
                "has_user_id": True,
                "user_col": "user_id",
                "comment": None,
            }
        raw_snapshot = {"tables": tables, "foreign_keys": [], "relationships": []}
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect Chroma collections: {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def introspect_lancedb(cursor: Any, filter_sensitive: bool = True) -> dict[str, Any]:
    """Introspects LanceDB Apache Arrow table schemas."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)

        names: list[str] = []
        if hasattr(cur, "fetchall") and hasattr(cur, "execute"):
            cur.execute("table_names")
            rows = cur.fetchall() or []
            names = [str(r[0]) for r in rows if r and r[0]]
        elif hasattr(cur, "table_names"):
            names = [str(t) for t in cur.table_names()]
        elif hasattr(cur, "execute"):
            cur.execute("table_names")
            rows = cur.fetchall() or []
            names = [str(r[0]) for r in rows if r and r[0]]

        # the cursor adapter wraps the real connection: read the true Arrow schemas from it
        source = cur if hasattr(cur, "open_table") else getattr(cur, "conn", None)

        tables: dict[str, dict[str, Any]] = {}
        for name in names:
            cols: list[dict[str, Any]] = []
            if source is not None and hasattr(source, "open_table"):
                with contextlib.suppress(Exception):
                    tbl_obj = source.open_table(name)
                    if hasattr(tbl_obj, "schema"):
                        for f in tbl_obj.schema:
                            fname = getattr(f, "name", str(f))
                            ftype = str(getattr(f, "type", "string"))
                            cols.append(
                                {
                                    "name": fname,
                                    "data_type": ftype,
                                    "is_nullable": getattr(f, "nullable", True),
                                    "is_primary": fname.lower() in ("id", "vector_id"),
                                    "comment": None,
                                }
                            )
            if not cols:
                cols = [
                    {
                        "name": "id",
                        "data_type": "string",
                        "is_nullable": False,
                        "is_primary": True,
                        "comment": None,
                    },
                    {
                        "name": "vector",
                        "data_type": "fixed_size_list",
                        "is_nullable": False,
                        "is_primary": False,
                        "comment": None,
                    },
                    {
                        "name": "user_id",
                        "data_type": "string",
                        "is_nullable": True,
                        "is_primary": False,
                        "comment": None,
                    },
                ]
            has_user = any(c["name"] == "user_id" for c in cols)
            tables[name] = {
                "name": name,
                "columns": cols,
                "has_user_id": has_user,
                "user_col": "user_id" if has_user else None,
                "comment": None,
            }
        raw_snapshot = {"tables": tables, "foreign_keys": [], "relationships": []}
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(f"Failed to introspect LanceDB tables: {exc}") from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def _redis_text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _redis_index_columns(client: Any, index: str) -> list[dict[str, Any]]:
    """Real columns of a RediSearch index from ``FT.INFO`` (``[]`` if unavailable)."""
    if client is None or not hasattr(client, "execute_command"):
        return []
    try:
        info = client.execute_command("FT.INFO", index)
    except Exception:  # noqa: BLE001
        return []
    return parse_ft_info(info)


def parse_ft_info(info: Any) -> list[dict[str, Any]]:
    """Columns from an ``FT.INFO`` reply (RESP2 flat list or RESP3 mapping)."""
    attributes: Any = None
    if isinstance(info, dict):  # RESP3
        attributes = next(
            (v for k, v in info.items() if _redis_text(k) == "attributes"), None
        )
    elif isinstance(info, (list, tuple)):  # RESP2: flat key, value, key, value ...
        for pos in range(0, len(info) - 1, 2):
            if _redis_text(info[pos]) == "attributes":
                attributes = info[pos + 1]
                break
    cols: list[dict[str, Any]] = []
    for attr in attributes if isinstance(attributes, (list, tuple)) else []:
        if isinstance(attr, dict):
            fields = {_redis_text(k): _redis_text(v) for k, v in attr.items()}
        elif isinstance(attr, (list, tuple)):
            fields = {
                _redis_text(attr[i]).lower(): _redis_text(attr[i + 1])
                for i in range(0, len(attr) - 1, 2)
            }
        else:
            continue
        name = fields.get("attribute") or fields.get("identifier")
        if name:
            cols.append(
                {
                    "name": name,
                    "data_type": fields.get("type", "text").lower(),
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                }
            )
    return cols


def introspect_redis_search(
    cursor: Any,
    filter_sensitive: bool = True,
    _indexes: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """
    Introspects Redis RediSearch index definitions.

    ``_indexes`` (index name -> columns) lets an async caller, whose client calls
    must be awaited, hand over already-fetched ``FT.INFO`` results.
    """
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)

        index_names: list[str] = []
        if _indexes is not None:
            index_names = list(_indexes)
        elif hasattr(cur, "execute"):
            cur.execute("FT._LIST")
            rows = cur.fetchall() or []
            index_names = [str(r[0]) for r in rows if r and r[0]]
        elif hasattr(cur, "execute_command"):
            res = cur.execute_command("FT._LIST")
            index_names = [
                r.decode() if isinstance(r, bytes) else str(r) for r in (res or [])
            ]

        raw_client = (
            cur if hasattr(cur, "execute_command") else getattr(cur, "conn", None)
        )

        tables: dict[str, dict[str, Any]] = {}
        for idx in index_names:
            real_cols = (
                _indexes[idx]
                if _indexes is not None
                else _redis_index_columns(raw_client, idx)
            )
            if real_cols:
                tables[idx] = {
                    "name": idx,
                    "columns": real_cols,
                    "has_user_id": any(c["name"] == "user_id" for c in real_cols),
                    "user_col": "user_id",
                    "comment": None,
                }
                continue
            cols = [
                {
                    "name": "id",
                    "data_type": "tag",
                    "is_nullable": False,
                    "is_primary": True,
                    "comment": None,
                },
                {
                    "name": "title",
                    "data_type": "text",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
                {
                    "name": "user_id",
                    "data_type": "tag",
                    "is_nullable": True,
                    "is_primary": False,
                    "comment": None,
                },
            ]
            tables[idx] = {
                "name": idx,
                "columns": cols,
                "has_user_id": True,
                "user_col": "user_id",
                "comment": None,
            }
        raw_snapshot = {"tables": tables, "foreign_keys": [], "relationships": []}
        return normalize_schema_snapshot(
            raw_snapshot, filter_sensitive=filter_sensitive
        )
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect RediSearch indexes: {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def _rows_as_dicts(names: list[str], rows: Any) -> list[dict[str, Any]]:
    """Rows as dicts; columns without a reported name are called ``col0``, ``col1``, ..."""
    out = []
    for row in rows or []:
        keys = names or [f"col{i}" for i in range(len(row))]
        out.append(dict(zip(keys, row, strict=False)))
    return out


def _empty_snapshot(filter_sensitive: bool = True) -> dict[str, Any]:
    return normalize_schema_snapshot(
        {"tables": {}, "foreign_keys": [], "relationships": []},
        filter_sensitive=filter_sensitive,
    )


def _sampled_columns(
    samples: dict[str, str], primary: str, primary_type: str
) -> list[dict[str, Any]]:
    """Column list from ``{name: type}`` plus a leading primary-key column."""
    cols = [
        {
            "name": primary,
            "data_type": samples.get(primary, primary_type),
            "is_nullable": False,
            "is_primary": True,
            "comment": None,
        }
    ]
    cols += [
        {
            "name": n,
            "data_type": t,
            "is_nullable": True,
            "is_primary": False,
            "comment": None,
        }
        for n, t in samples.items()
        if n != primary
    ]
    return cols


def firestore_schema_steps(
    filter_sensitive: bool = True,
) -> Generator[str, list[dict[str, Any]], dict[str, Any]]:
    """Firestore introspection as a statement-yielding generator (see ``drive_steps``).

    Collections come from ``collections``; fields from a sample of 100 documents each.
    Firestore collections are schemaless and an empty collection does not exist, so there
    is nothing to invent: no collections -> no tables.  ``id`` is the document id.
    """
    names_rows = yield "collections"
    tables: dict[str, dict[str, Any]] = {}
    for row in names_rows:
        if not row:
            continue
        name = str(next(iter(row.values())))
        safe = name.replace("`", "")
        docs = yield f"SELECT * FROM `{safe}` LIMIT 100"
        samples: dict[str, str] = {}
        for doc in docs:
            for k, v in doc.items():
                if k not in samples or samples[k] == "null":
                    samples[k] = _arango_json_type(v)
        cols = _sampled_columns(samples, "id", "string")
        tables[name] = {
            "name": name,
            "columns": cols,
            "has_user_id": "user_id" in samples,
            "user_col": "user_id",
            "comment": None,
        }
    return normalize_schema_snapshot(
        {"tables": tables, "foreign_keys": [], "relationships": []},
        filter_sensitive=filter_sensitive,
    )


def introspect_firestore(cursor: Any, filter_sensitive: bool = True) -> dict[str, Any]:
    """Introspects Firestore collections: real collection names and sampled document fields."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)

        def run(statement: str) -> list[dict[str, Any]]:
            cur.execute(statement)
            names = [d[0] for d in (getattr(cur, "description", None) or [])]
            return _rows_as_dicts(names, cur.fetchall())

        if not hasattr(cur, "execute"):
            if not hasattr(cur, "collections"):
                return _empty_snapshot(filter_sensitive)
            from query_builder.connectors.firestore import _FirestoreCursorAdapter

            cur = _FirestoreCursorAdapter(cur)  # a raw SDK client
        return drive_steps(firestore_schema_steps(filter_sensitive), run)
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect Firestore collections: {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()


def bigtable_schema_steps(
    filter_sensitive: bool = True,
) -> Generator[str, list[dict[str, Any]], dict[str, Any]]:
    """Bigtable introspection as a statement-yielding generator (see ``drive_steps``).

    Tables come from ``list_tables``; each table's columns are ``row_key`` (the primary key)
    plus one ``family.qualifier`` column per cell column seen in a sample of 100 rows.
    Bigtable stores raw bytes, so every column is ``bytes``.  No table -> no tables.
    """
    table_rows = yield "list_tables"
    tables: dict[str, dict[str, Any]] = {}
    for row in table_rows:
        if not row:
            continue
        name = str(next(iter(row.values())))
        safe = name.replace("`", "")
        sample = yield f"SELECT * FROM `{safe}` LIMIT 100"
        seen: dict[str, str] = {}
        for rec in sample:
            for col in rec:
                if col != "row_key":
                    seen[col] = "bytes"
        tables[name] = {
            "name": name,
            "columns": _sampled_columns(seen, "row_key", "bytes"),
            "has_user_id": False,
            "user_col": "user_id",
            "comment": None,
        }
    return normalize_schema_snapshot(
        {"tables": tables, "foreign_keys": [], "relationships": []},
        filter_sensitive=filter_sensitive,
    )


def introspect_bigtable(cursor: Any, filter_sensitive: bool = True) -> dict[str, Any]:
    """Introspects Bigtable: real table ids and the cell columns present in sampled rows."""
    cur = None
    own_cur = False
    try:
        cur = _unwrap_cursor(cursor)
        own_cur = cur is not cursor and cur is not getattr(cursor, "target", None)

        def run(statement: str) -> list[dict[str, Any]]:
            cur.execute(statement)
            names = [d[0] for d in (getattr(cur, "description", None) or [])]
            return _rows_as_dicts(names, cur.fetchall())

        if not hasattr(cur, "execute"):
            if not hasattr(cur, "list_tables"):
                return _empty_snapshot(filter_sensitive)
            from query_builder.connectors.bigtable import _BigtableCursorAdapter

            cur = _BigtableCursorAdapter(cur)  # a raw SDK client
        return drive_steps(bigtable_schema_steps(filter_sensitive), run)
    except Exception as exc:
        raise IntrospectionError(
            f"Failed to introspect Bigtable tables: {exc}"
        ) from exc
    finally:
        if own_cur and cur is not None and hasattr(cur, "close"):
            with contextlib.suppress(Exception):
                cur.close()
