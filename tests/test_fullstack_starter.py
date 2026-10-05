"""
Integration Test Suite for Fullstack Starter Template.
======================================================
Tests database schema and seeder integrity, FastAPI backend endpoints (/health,
/api/schema, /api/compile, /api/execute), multi-table relational join execution,
AST safety security policy enforcement, and schema serialization.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure examples/fullstack_starter is importable
starter_root = Path(__file__).resolve().parent.parent / "examples" / "fullstack_starter"
if str(starter_root) not in sys.path:
    sys.path.insert(0, str(starter_root))

import pytest
from backend.main import app
from database import (
    DEFAULT_DB_PATH,
    get_starter_schema_snapshot,
    get_starter_tables,
    init_database,
    snapshot_to_dict,
)
from fastapi.testclient import TestClient

from query_builder import (
    SQLiteConnector,
    configure_query_builder,
    reset_query_builder_config,
    reset_security_config,
)


@pytest.fixture(autouse=True, scope="module")
def setup_and_teardown_starter_module():
    """Module-level setup and teardown for fullstack starter integration tests.

    Ensures clean state isolation before execution and deterministically resets
    global configuration after the test module finishes.
    """
    reset_query_builder_config()
    reset_security_config()
    configure_query_builder(
        profile="development",
        default_dialect="sqlite",
        default_limit=50,
    )
    init_database(DEFAULT_DB_PATH)
    try:
        yield
    finally:
        reset_query_builder_config()
        reset_security_config()


@pytest.fixture(autouse=True)
def setup_starter_test():
    """Function-level fixture ensuring starter environment is configured for each test."""
    configure_query_builder(
        profile="development",
        default_dialect="sqlite",
        default_limit=50,
    )
    try:
        yield
    finally:
        reset_query_builder_config()
        reset_security_config()


def test_database_initialization_and_seed_data(tmp_path: Path) -> None:
    """Verifies that init_database creates all 5 tables and populates seed rows."""
    db_file = tmp_path / "test_starter.db"
    conn = init_database(db_file, force_recreate=True)

    # 1. Check all tables exist
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
    )
    tables = [r[0] for r in cur.fetchall()]
    assert set(tables) == {"categories", "products", "users", "orders", "order_items"}

    # 2. Check seed row counts
    cur.execute("SELECT COUNT(*) FROM categories;")
    assert cur.fetchone()[0] == 4

    cur.execute("SELECT COUNT(*) FROM products;")
    assert cur.fetchone()[0] == 8

    cur.execute("SELECT COUNT(*) FROM users;")
    assert cur.fetchone()[0] == 5

    cur.execute("SELECT COUNT(*) FROM orders;")
    assert cur.fetchone()[0] == 5

    cur.execute("SELECT COUNT(*) FROM order_items;")
    assert cur.fetchone()[0] == 8

    # 3. Check foreign key cascade integrity
    conn.execute("PRAGMA foreign_keys = ON;")
    with conn:
        conn.execute("DELETE FROM orders WHERE id = 1;")
    cur.execute("SELECT COUNT(*) FROM order_items WHERE order_id = 1;")
    assert cur.fetchone()[0] == 0, "Order items should be deleted via ON DELETE CASCADE"


def test_schema_snapshot_serialization() -> None:
    """Verifies that starter schema tables and snapshot contain correct relations and types."""
    tables = get_starter_tables()
    assert len(tables) == 5
    assert "products" in tables
    assert "orders" in tables

    prod_table = tables["products"]
    assert "id" in prod_table.primary_keys
    category_id_col = next(
        (c for c in prod_table.columns if c.name == "category_id"), None
    )
    assert category_id_col is not None
    assert category_id_col.foreign_key is not None
    assert category_id_col.foreign_key.foreign_table == "categories"
    assert category_id_col.foreign_key.foreign_column == "id"

    snapshot = get_starter_schema_snapshot()
    assert "categories" in snapshot.tables
    assert "products" in snapshot.tables
    assert "users" in snapshot.tables
    assert "orders" in snapshot.tables
    assert "order_items" in snapshot.tables

    # Verify foreign keys are registered
    fk_pairs = [(fk["table"], fk["foreign_table"]) for fk in snapshot.foreign_keys]
    assert ("products", "categories") in fk_pairs
    assert ("orders", "users") in fk_pairs
    assert ("order_items", "orders") in fk_pairs
    assert ("order_items", "products") in fk_pairs

    # Verify dictionary serialization
    snapshot_dict = snapshot_to_dict(snapshot)
    assert isinstance(snapshot_dict, dict)
    assert "tables" in snapshot_dict
    assert "foreign_keys" in snapshot_dict
    assert "relationships" in snapshot_dict


def test_sqlite_connector_direct_execution(tmp_path: Path) -> None:
    """Verifies SQLiteConnector executes compiled queries with aggregation and joins."""
    db_file = tmp_path / "connector_test.db"
    init_database(db_file)

    connector = SQLiteConnector(database=str(db_file))
    conn_info = connector.test_connection()
    assert conn_info["status"] == "healthy"

    # Introspect schema
    schema = connector.introspect_schema()
    assert "products" in schema["tables"]

    # Query with join: Users and their completed orders
    spec = {
        "table": "orders",
        "columns": [
            "orders.id",
            "orders.total_amount",
            {"column": "users.email", "alias": "user_email"},
        ],
        "joins": [
            {
                "table": "users",
                "type": "INNER JOIN",
                "on": [{"left": "orders.user_id", "right": "users.id"}],
            }
        ],
        "filters": [{"column": "orders.status", "op": "eq", "value": "COMPLETED"}],
        "order_by": [{"column": "orders.id", "direction": "ASC"}],
        "limit": 10,
    }

    result = connector.execute(spec=spec)
    assert result["count"] > 0
    assert len(result["rows"]) > 0
    assert "orders.id" in result["columns"]
    assert "user_email" in result["columns"]
    assert result["dialect"] == "sqlite"
    assert result["latency_ms"] >= 0


def test_fastapi_health_endpoint() -> None:
    """Verifies GET /health returns service health and configuration details."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "query-builder-fullstack-starter"
    assert "sqlite" in data["dialects"]
    assert data["security_profile"] == "development"
    assert data["read_only_enforced"] is False


def test_fastapi_schema_endpoint() -> None:
    """Verifies GET /api/schema returns complete schema snapshot."""
    client = TestClient(app)
    response = client.get("/api/schema")
    assert response.status_code == 200

    data = response.json()
    assert "tables" in data
    assert "foreign_keys" in data
    assert "relationships" in data

    tables = data["tables"]
    assert "categories" in tables
    assert "products" in tables
    assert "users" in tables
    assert "orders" in tables
    assert "order_items" in tables


def test_fastapi_compile_endpoint() -> None:
    """Verifies POST /api/compile translates JSON query specs into SQL."""
    client = TestClient(app)

    # 1. Valid compilation
    payload = {
        "spec": {
            "table": "products",
            "columns": ["products.id", "products.name", "products.price"],
            "filters": [{"column": "products.price", "op": "gt", "value": 100}],
            "order_by": [{"column": "products.price", "direction": "DESC"}],
            "limit": 5,
            "offset": 0,
        },
        "dialect": "sqlite",
    }
    response = client.post("/api/compile", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert "sql" in data
    assert "params" in data
    assert "count_sql" in data
    assert "SELECT" in data["sql"]
    assert "products" in data["sql"]
    assert data["params"] == [100, 5, 0]

    # 2. Invalid spec: missing table parameter
    bad_payload = {"spec": {"columns": ["id"]}, "dialect": "sqlite"}
    bad_response = client.post("/api/compile", json=bad_payload)
    assert bad_response.status_code == 400


def test_fastapi_execute_endpoint_spec() -> None:
    """Verifies POST /api/execute runs queries and returns structured rows."""
    client = TestClient(app)

    payload = {
        "spec": {
            "table": "categories",
            "columns": ["categories.id", "categories.name", "categories.slug"],
            "limit": 10,
        }
    }
    response = client.post("/api/execute", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["count"] == 4
    assert len(data["rows"]) == 4
    assert "categories.id" in data["columns"]
    assert "categories.name" in data["columns"]
    assert data["dialect"] == "sqlite"
    assert data["latency_ms"] >= 0


def test_fastapi_execute_relational_join() -> None:
    """Verifies POST /api/execute handles multi-table relational queries."""
    client = TestClient(app)

    payload = {
        "spec": {
            "table": "order_items",
            "columns": [
                "order_items.id",
                "order_items.quantity",
                "order_items.unit_price",
                {"column": "products.name", "alias": "product_name"},
                {"column": "orders.status", "alias": "order_status"},
            ],
            "joins": [
                {
                    "table": "products",
                    "type": "INNER JOIN",
                    "on": [{"left": "order_items.product_id", "right": "products.id"}],
                },
                {
                    "table": "orders",
                    "type": "INNER JOIN",
                    "on": [{"left": "order_items.order_id", "right": "orders.id"}],
                },
            ],
            "limit": 10,
        }
    }
    response = client.post("/api/execute", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["count"] == 8
    assert len(data["rows"]) == 8
    assert "product_name" in data["columns"]
    assert "order_status" in data["columns"]


def test_fastapi_execute_security_policy_enforcement() -> None:
    """Verifies POST /api/execute rejects mutation SQL queries and multi-statement attacks."""
    client = TestClient(app)

    # 1. Mutation attempt: DROP TABLE
    drop_payload = {"sql": "DROP TABLE users;"}
    res_drop = client.post("/api/execute", json=drop_payload)
    assert res_drop.status_code == 403
    assert "Security violation" in res_drop.json()["detail"]

    # 2. Mutation attempt: DELETE
    delete_payload = {"sql": "DELETE FROM products WHERE id = 1;"}
    res_delete = client.post("/api/execute", json=delete_payload)
    assert res_delete.status_code == 403
    assert "Security violation" in res_delete.json()["detail"]

    # 3. Semicolon multi-statement query chaining
    multi_payload = {"sql": "SELECT 1; DROP TABLE orders;"}
    res_multi = client.post("/api/execute", json=multi_payload)
    assert res_multi.status_code == 403
    assert "Security violation" in res_multi.json()["detail"]

    # 4. Safe raw SELECT should pass
    safe_payload = {"sql": "SELECT id, name FROM categories LIMIT 2;"}
    res_safe = client.post("/api/execute", json=safe_payload)
    assert res_safe.status_code == 200
    assert len(res_safe.json()["rows"]) == 2
