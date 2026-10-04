import sqlite3

import pytest

from query_builder.compiler import QueryCompiler
from query_builder.executor import execute_compiled_spec, execute_cursor_query
from query_builder.schema import normalize_schema_snapshot


def test_normalize_schema_snapshot_filtering():
    raw = {
        "tables": {
            "users": {
                "columns": ["id", "username", "user_id"],
                "has_user_id": True,
            },
            "auth_user": {
                "columns": ["id", "password"],
            },
            "projects": {
                "columns": [
                    {"name": "id", "is_primary": True, "data_type": "integer"},
                    {"name": "title", "data_type": "varchar"},
                ]
            },
        },
        "foreign_keys": [
            {
                "table": "projects",
                "column": "user_id",
                "foreign_table": "users",
                "foreign_column": "id",
            }
        ],
        "relationships": [
            {
                "source_table": "projects",
                "source_column": "user_id",
                "target_table": "users",
                "target_column": "id",
            }
        ],
    }
    normalized = normalize_schema_snapshot(raw, filter_sensitive=True)
    assert "users" in normalized["tables"]
    assert "projects" in normalized["tables"]
    assert "auth_user" not in normalized["tables"]
    assert len(normalized["foreign_keys"]) == 1


def test_sqlite_execution_harness():
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT);")
    cur.execute(
        "INSERT INTO users (id, name, email) VALUES (1, 'Alice', 'alice@example.com');"
    )
    cur.execute(
        "INSERT INTO users (id, name, email) VALUES (2, 'Bob', 'bob@example.com');"
    )
    conn.commit()

    cols, rows, latency = execute_cursor_query(
        cur, "SELECT id, name FROM users ORDER BY id ASC;"
    )
    assert cols == ["id", "name"]
    assert len(rows) == 2
    assert rows[0]["name"] == "Alice"
    assert rows[1]["name"] == "Bob"
    assert latency >= 0

    spec = {
        "table": "users",
        "columns": ["users.id", "users.name"],
        "filters": [{"column": "users.name", "op": "eq", "value": "Alice"}],
        "limit": 10,
        "offset": 0,
    }
    res = execute_compiled_spec(cur, spec, dialect="sqlite")
    assert res["count"] == 1
    assert len(res["rows"]) == 1
    assert res["rows"][0]["users.name"] == "Alice"

    # Test query without filters (count_params empty branch)
    res_all = execute_compiled_spec(
        cur, {"table": "users", "columns": ["users.id"]}, dialect="sqlite"
    )
    assert res_all["count"] == 2

    # Test execute_compiled_spec with tenant_id
    cur.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, tenant_id TEXT);")
    cur.execute("INSERT INTO accounts (id, tenant_id) VALUES (1, 'tenant-123');")
    conn.commit()
    res_tenant = execute_compiled_spec(
        cur,
        {"table": "accounts", "columns": ["accounts.id"], "tenant_id": "tenant-456"},
        dialect="sqlite",
        tenant_id="tenant-123",
    )
    assert res_tenant["count"] == 1

    # Test execute_compiled_spec with QuerySpec dataclass instance
    from query_builder.models import QuerySpec

    res_dataclass = execute_compiled_spec(
        cur,
        QuerySpec(table="accounts", columns=["accounts.id"], tenant_id="tenant-123"),
        dialect="sqlite",
    )
    assert res_dataclass["count"] == 1
    assert res_dataclass["rows"] == [{"accounts.id": 1}]

    # Test AST validation failure in execute_compiled_spec
    with pytest.raises(Exception) as exc:
        bad_spec = {"table": "auth_user", "columns": ["*"]}
        execute_compiled_spec(cur, bad_spec, dialect="sqlite", validate_ast=True)
    assert "AST safety validation" in str(exc.value)

    conn.close()


def test_compiler_filters_and_projections():
    spec = {
        "table": "products",
        "columns": [
            "*",
        ],
        "filters": [
            {"column": "price", "op": "between", "value": [10, 50]},
            {"column": "category", "op": "in", "value": ["shoes", "hats"]},
            {"column": "description", "op": "is_not_null"},
            {"column": "archived_at", "op": "is_null"},
            {"column": "sku", "op": "starts_with", "value": "ABC"},
            {"column": "sku", "op": "ends_with", "value": "XYZ"},
        ],
        "filter_join": "OR",
        "order_by": [{"column": "price", "direction": "DESC"}],
        "distinct": True,
        "limit": 25,
        "offset": 5,
    }
    compiler = QueryCompiler(spec, dialect="postgres")
    sql, params, _count_sql, _ = compiler.compile()

    assert "SELECT DISTINCT" in sql
    assert '"t1".*' in sql
    assert "BETWEEN %s AND %s" in sql
    assert "IN (%s, %s)" in sql
    assert '"t1"."description" IS NOT NULL' in sql
    assert '"t1"."archived_at" IS NULL' in sql
    assert "OR" in sql
    assert 'ORDER BY "t1"."price" DESC' in sql
    assert 10 in params
    assert 50 in params
    assert "%s" in sql
