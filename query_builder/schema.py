"""
Database Schema Snapshot & Metadata Indexing Protocol.
======================================================
Provides structure definition, normalization, and validation for database
schemas consumed by Query Builder and Visual SQL Explorers.
"""

from typing import Any

DEFAULT_SENSITIVE_TABLES: set[str] = {
    "auth_user",
    "auth_group",
    "auth_permission",
    "auth_user_groups",
    "auth_user_user_permissions",
    "authtoken_token",
    "django_session",
    "django_admin_log",
    "django_content_type",
    "django_migrations",
    "pg_shadow",
    "pg_authid",
    "pg_user",
    "pg_database",
    "pg_tables",
    "pg_stat_activity",
    "pg_roles",
    "pg_settings",
    "pg_config",
    "passwords",
    "credentials",
    "crm_connection",
    "crm_field_mapping",
    "django_cache_table",
    "api_auditlog",
    "user_profile",
    "sqlite_master",
    "sqlite_schema",
    "sqlite_temp_master",
    "sqlite_temp_schema",
    "sqlite_sequence",
    "sqlite_stat1",
    "mysql.user",
    "mysql.db",
    "sys.objects",
    "sys.tables",
    "sys.sql_logins",
}


def normalize_schema_snapshot(
    raw_data: dict[str, Any], filter_sensitive: bool = True
) -> dict[str, Any]:
    """
    Normalizes a dictionary into a validated schema snapshot mapping
    with sanitized table lists, relationships, and foreign keys.
    """
    tables: dict[str, dict[str, Any]] = {}
    raw_tables = raw_data.get("tables", {})

    for tbl_name, tbl_info in raw_tables.items():
        clean_tbl = tbl_name.lower().strip()
        if filter_sensitive and clean_tbl in DEFAULT_SENSITIVE_TABLES:
            continue

        cols: list[dict[str, Any]] = []
        for col in tbl_info.get("columns", []):
            if isinstance(col, dict):
                cols.append(
                    {
                        "name": col.get("name", ""),
                        "data_type": col.get("data_type", "text"),
                        "is_nullable": bool(col.get("is_nullable", True)),
                        "is_primary": bool(col.get("is_primary", False)),
                        "comment": col.get("comment"),
                    }
                )
            elif isinstance(col, str):
                cols.append(
                    {
                        "name": col,
                        "data_type": "text",
                        "is_nullable": True,
                        "is_primary": col == "id",
                        "comment": None,
                    }
                )

        has_user = tbl_info.get("has_user_id", False) or any(
            c["name"] == "user_id" for c in cols
        )
        tables[tbl_name] = {
            "name": tbl_name,
            "columns": cols,
            "has_user_id": has_user,
            "user_col": tbl_info.get("user_col", "user_id"),
            "comment": tbl_info.get("comment"),
        }

    foreign_keys: list[dict[str, Any]] = []
    for fk in raw_data.get("foreign_keys", []):
        foreign_keys.append(
            {
                "table": fk.get("table", ""),
                "column": fk.get("column", ""),
                "foreign_table": fk.get("foreign_table", ""),
                "foreign_column": fk.get("foreign_column", ""),
            }
        )

    relationships: list[dict[str, Any]] = []
    for rel in raw_data.get("relationships", []):
        relationships.append(
            {
                "source_table": rel.get("source_table", ""),
                "source_column": rel.get("source_column", ""),
                "target_table": rel.get("target_table", ""),
                "target_column": rel.get("target_column", ""),
            }
        )

    return {
        "tables": tables,
        "foreign_keys": foreign_keys,
        "relationships": relationships,
        "categories": raw_data.get("categories", {}),
    }


def explore_schema(
    raw_data: dict[str, Any], filter_sensitive: bool = True
) -> dict[str, Any]:
    """
    Analyzes and summarizes a database schema snapshot with structural graph metrics,
    foreign key degree distribution, hub tables, and column type distributions.
    """
    snapshot = normalize_schema_snapshot(raw_data, filter_sensitive=filter_sensitive)
    tables = snapshot["tables"]
    fks = snapshot["foreign_keys"]
    rels = snapshot["relationships"]

    total_columns = sum(len(t.get("columns", [])) for t in tables.values())
    total_pks = sum(
        sum(1 for c in t.get("columns", []) if c.get("is_primary"))
        for t in tables.values()
    )
    user_isolated_count = sum(1 for t in tables.values() if t.get("has_user_id"))

    outgoing_degrees: dict[str, int] = {t: 0 for t in tables}
    incoming_degrees: dict[str, int] = {t: 0 for t in tables}

    for fk in fks:
        src = fk.get("table")
        dst = fk.get("foreign_table")
        if src in outgoing_degrees:
            outgoing_degrees[src] += 1
        if dst in incoming_degrees:
            incoming_degrees[dst] += 1

    hubs = [
        t
        for t, deg in incoming_degrees.items()
        if deg >= 2 or (outgoing_degrees.get(t, 0) + deg) >= 3
    ]
    isolated = [
        t
        for t in tables
        if outgoing_degrees.get(t, 0) == 0 and incoming_degrees.get(t, 0) == 0
    ]

    type_counts: dict[str, int] = {}
    for t in tables.values():
        for c in t.get("columns", []):
            dtype = (c.get("data_type") or "unknown").lower()
            type_counts[dtype] = type_counts.get(dtype, 0) + 1

    table_summaries: dict[str, Any] = {}
    for tbl_name, t in tables.items():
        table_summaries[tbl_name] = {
            "name": tbl_name,
            "column_count": len(t.get("columns", [])),
            "columns": t.get("columns", []),
            "has_user_id": t.get("has_user_id", False),
            "user_col": t.get("user_col", "user_id"),
            "comment": t.get("comment"),
            "primary_keys": [
                c["name"] for c in t.get("columns", []) if c.get("is_primary")
            ],
            "outgoing_fks": [fk for fk in fks if fk.get("table") == tbl_name],
            "incoming_fks": [fk for fk in fks if fk.get("foreign_table") == tbl_name],
        }

    return {
        "table_count": len(tables),
        "column_count": total_columns,
        "primary_key_count": total_pks,
        "foreign_key_count": len(fks),
        "relationship_count": len(rels),
        "user_isolated_count": user_isolated_count,
        "categories": snapshot.get("categories", {}),
        "hubs": sorted(hubs),
        "isolated_tables": sorted(isolated),
        "data_types": type_counts,
        "tables": table_summaries,
    }


def format_schema_tree(
    raw_data: dict[str, Any], filter_sensitive: bool = True, max_columns: int = 5
) -> str:
    """
    Renders an ASCII tree visualization of the schema hierarchy, tables, columns, and foreign keys.
    """
    explored = explore_schema(raw_data, filter_sensitive=filter_sensitive)
    lines: list[str] = [
        f"Database Schema ({explored['table_count']} tables, {explored['column_count']} columns, {explored['foreign_key_count']} FKs):"
    ]

    tables = explored["tables"]
    sorted_tables = sorted(tables.keys())
    for i, tbl_name in enumerate(sorted_tables):
        is_last_tbl = i == len(sorted_tables) - 1
        tbl_prefix = "└── " if is_last_tbl else "├── "
        child_indent = "    " if is_last_tbl else "│   "

        tbl_info = tables[tbl_name]
        user_tag = " [user-isolated]" if tbl_info.get("has_user_id") else ""
        lines.append(
            f"{tbl_prefix}{tbl_name} ({tbl_info['column_count']} cols){user_tag}"
        )

        cols = tbl_info.get("columns", [])
        visible_cols = cols[:max_columns]
        for col in visible_cols:
            pk_tag = " [PK]" if col.get("is_primary") else ""
            lines.append(
                f"{child_indent}├── {col['name']}: {col.get('data_type', 'text')}{pk_tag}"
            )
        if len(cols) > max_columns:
            lines.append(
                f"{child_indent}├── ... ({len(cols) - max_columns} more columns)"
            )

        fks = tbl_info.get("outgoing_fks", [])
        for fk in fks:
            lines.append(
                f"{child_indent}└── FK: {fk['column']} -> {fk['foreign_table']}.{fk['foreign_column']}"
            )

    return "\n".join(lines)
