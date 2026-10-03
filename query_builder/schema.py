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
