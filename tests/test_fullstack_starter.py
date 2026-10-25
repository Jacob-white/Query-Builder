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
    import contextlib

    reset_query_builder_config()
    reset_security_config()
    configure_query_builder(
        profile="development",
        default_dialect="sqlite",
        default_limit=50,
    )
    with contextlib.closing(init_database(DEFAULT_DB_PATH)):
        pass
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
    import contextlib

    db_file = tmp_path / "test_starter.db"
    with contextlib.closing(init_database(db_file, force_recreate=True)) as conn:
        # 1. Check all tables exist
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
        )
        tables = [r[0] for r in cur.fetchall()]
        assert set(tables) == {
            "categories",
            "products",
            "users",
            "orders",
            "order_items",
        }

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
        assert cur.fetchone()[0] == 0, (
            "Order items should be deleted via ON DELETE CASCADE"
        )


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
    import contextlib

    db_file = tmp_path / "connector_test.db"
    with contextlib.closing(init_database(db_file)):
        pass

    connector = SQLiteConnector(database=str(db_file))
    try:
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
    finally:
        connector.close()


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


def test_custom_database_test_connect_query_and_disconnect(tmp_path: Path) -> None:
    """Verifies testing, connecting, querying, and disconnecting a custom database via UI endpoints."""
    import contextlib
    import sqlite3

    from backend.main import _parse_backend_connection_uri, clear_custom_databases

    clear_custom_databases()
    try:
        custom_db_file = tmp_path / "external_crm.sqlite"
        with contextlib.closing(sqlite3.connect(str(custom_db_file))) as sconn:
            sconn.execute(
                "CREATE TABLE accounts (id INTEGER PRIMARY KEY, company TEXT, arr REAL);"
            )
            sconn.execute(
                "INSERT INTO accounts VALUES (1, 'Acme Corp', 120000.0), (2, 'Globex', 85000.0);"
            )
            sconn.commit()

        # Verify Windows drive-letter, UNC, and query-param URI normalization for sqlite/duckdb URIs
        assert (
            _parse_backend_connection_uri(r"sqlite:////C:\Users\demo\crm.sqlite")[
                "file_path"
            ]
            == r"C:\Users\demo\crm.sqlite"
        )
        assert (
            _parse_backend_connection_uri(
                r"sqlite:///C:/Users/demo/crm.sqlite?mode=ro"
            )["file_path"]
            == "C:/Users/demo/crm.sqlite"
        )
        assert (
            _parse_backend_connection_uri(r"sqlite:////\\server\share\crm.sqlite")[
                "file_path"
            ]
            == r"\\server\share\crm.sqlite"
        )
        assert (
            _parse_backend_connection_uri("sqlite://///server/share/crm.sqlite")[
                "file_path"
            ]
            == "//server/share/crm.sqlite"
        )
        assert (
            _parse_backend_connection_uri(r"duckdb:////C:\Users\demo\wh.duckdb")[
                "file_path"
            ]
            == r"C:\Users\demo\wh.duckdb"
        )
        assert (
            _parse_backend_connection_uri(
                r"duckdb:///C:/Users/demo/wh.duckdb?access_mode=read_only"
            )["file_path"]
            == "C:/Users/demo/wh.duckdb"
        )
        assert (
            _parse_backend_connection_uri(r"duckdb:////\\server\share\wh.duckdb")[
                "file_path"
            ]
            == r"\\server\share\wh.duckdb"
        )

        client = TestClient(app)

        # 1. Test connection before connecting
        test_res = client.post(
            "/api/databases/test",
            json={
                "name": "External CRM",
                "dialect": "sqlite",
                "file_path": str(custom_db_file),
            },
        )
        assert test_res.status_code == 200
        test_body = test_res.json()
        assert test_body["ok"] is True
        assert test_body["table_count"] == 1
        assert "accounts" in test_body["sample_tables"]

        # 2. Test connection with sqlite:/// URI including ?mode=ro query parameter
        uri_res = client.post(
            "/api/databases/test",
            json={
                "name": "External CRM URI",
                "connection_uri": f"sqlite:////{str(custom_db_file).lstrip('/')}?mode=ro",
            },
        )
        assert uri_res.status_code == 200
        assert uri_res.json()["ok"] is True

        # 3. Connect and register the custom database
        conn_res = client.post(
            "/api/databases/connect",
            json={
                "name": "External CRM",
                "dialect": "sqlite",
                "file_path": str(custom_db_file),
            },
        )
        assert conn_res.status_code == 200
        conn_body = conn_res.json()
        assert conn_body["ok"] is True
        custom_id = conn_body["database"]["id"]
        assert custom_id == "custom_external_crm"
        assert conn_body["database"]["is_custom"] is True
        assert "accounts" in conn_body["schema"]["tables"]

        # 4. Verify it appears in GET /api/databases
        list_res = client.get("/api/databases")
        assert list_res.status_code == 200
        db_ids = [d["id"] for d in list_res.json()["databases"]]
        assert custom_id in db_ids

        # 5. Execute a query against the newly connected database
        exec_res = client.post(
            f"/api/execute?db={custom_id}",
            json={
                "db": custom_id,
                "spec": {
                    "table": "accounts",
                    "columns": ["accounts.company", "accounts.arr"],
                    "order_by": [{"column": "accounts.arr", "direction": "DESC"}],
                    "limit": 10,
                },
            },
        )
        assert exec_res.status_code == 200
        exec_data = exec_res.json()
        assert exec_data["count"] == 2
        assert exec_data["rows"][0]["accounts.company"] == "Acme Corp"

        # 6. Built-in databases cannot be deleted
        builtin_del = client.delete("/api/databases/starter_demo")
        assert builtin_del.status_code == 400

        # 7. Disconnect custom database
        del_res = client.delete(f"/api/databases/{custom_id}")
        assert del_res.status_code == 200
        assert del_res.json()["deleted_id"] == custom_id
    finally:
        clear_custom_databases()


def test_upload_csv_and_json_as_custom_database() -> None:
    """Verifies POST /api/databases/upload converts CSV and JSON files into queryable databases."""
    import base64
    import json

    from backend.main import clear_custom_databases

    clear_custom_databases()
    try:
        client = TestClient(app)

        # 1. Upload CSV file
        csv_bytes = (
            b"region,deals,revenue\nNorth America,14,420000.5\nEurope,9,275000.0\n"
        )
        csv_res = client.post(
            "/api/databases/upload",
            json={
                "name": "Regional Sales CSV",
                "filename": "regional_sales.csv",
                "content_base64": base64.b64encode(csv_bytes).decode("ascii"),
            },
        )
        assert csv_res.status_code == 200
        csv_body = csv_res.json()
        assert csv_body["ok"] is True
        csv_db_id = csv_body["database"]["id"]
        assert "regional_sales" in csv_body["schema"]["tables"]

        exec_csv = client.post(
            f"/api/execute?db={csv_db_id}",
            json={
                "db": csv_db_id,
                "spec": {
                    "table": "regional_sales",
                    "columns": ["regional_sales.region", "regional_sales.revenue"],
                    "limit": 10,
                },
            },
        )
        assert exec_csv.status_code == 200
        assert exec_csv.json()["count"] == 2

        # 2. Upload JSON file
        json_bytes = json.dumps(
            [
                {"ticket_id": 101, "priority": "HIGH", "open_days": 3},
                {"ticket_id": 102, "priority": "LOW", "open_days": 1},
            ]
        ).encode("utf-8")
        json_res = client.post(
            "/api/databases/upload",
            json={
                "name": "Support Tickets JSON",
                "filename": "tickets.json",
                "content_base64": base64.b64encode(json_bytes).decode("ascii"),
            },
        )
        assert json_res.status_code == 200
        json_db_id = json_res.json()["database"]["id"]
        assert "tickets" in json_res.json()["schema"]["tables"]

        exec_json = client.post(
            f"/api/execute?db={json_db_id}",
            json={
                "db": json_db_id,
                "spec": {
                    "table": "tickets",
                    "columns": ["tickets.ticket_id", "tickets.priority"],
                    "limit": 10,
                },
            },
        )
        assert exec_json.status_code == 200
        assert exec_json.json()["count"] == 2

        # 3. Upload TSV file
        tsv_bytes = b"metric\tvalue\nlatency_ms\t12.4\nthroughput\t950\n"
        tsv_res = client.post(
            "/api/databases/upload",
            json={
                "name": "Metrics TSV",
                "filename": "metrics.tsv",
                "content_base64": base64.b64encode(tsv_bytes).decode("ascii"),
            },
        )
        assert tsv_res.status_code == 200
        tsv_db_id = tsv_res.json()["database"]["id"]
        assert tsv_db_id == "custom_metrics_tsv"
        assert "metrics" in tsv_res.json()["schema"]["tables"]

        # 4. Upload JSONL file
        jsonl_bytes = b'{"id": 1, "event": "signup"}\n{"id": 2, "event": "purchase"}\n'
        jsonl_res = client.post(
            "/api/databases/upload",
            json={
                "name": "Event Stream JSONL",
                "filename": "events.jsonl",
                "content_base64": base64.b64encode(jsonl_bytes).decode("ascii"),
            },
        )
        assert jsonl_res.status_code == 200
        assert "events" in jsonl_res.json()["schema"]["tables"]

        # 5. Upload multi-table JSON dictionary and verify automatic FK inference
        multi_json_bytes = json.dumps(
            {
                "customers": [
                    {"id": 1, "name": "Alice"},
                    {"id": 2, "name": "Bob"},
                ],
                "invoices": [
                    {"id": 100, "customer_id": 1, "amount": 250.0},
                    {"id": 101, "customer_id": 2, "amount": 175.5},
                ],
            }
        ).encode("utf-8")
        multi_res = client.post(
            "/api/databases/upload",
            json={
                "name": "Billing Multi Table JSON",
                "filename": "billing.json",
                "content_base64": base64.b64encode(multi_json_bytes).decode("ascii"),
            },
        )
        assert multi_res.status_code == 200
        multi_schema = multi_res.json()["schema"]
        assert "customers" in multi_schema["tables"]
        assert "invoices" in multi_schema["tables"]
        fks = multi_schema.get("foreign_keys", [])
        assert any(
            fk["table"] == "invoices"
            and fk["column"] == "customer_id"
            and fk["foreign_table"] == "customers"
            for fk in fks
        )
    finally:
        clear_custom_databases()


def test_memory_scratchpad_and_persistence(tmp_path: Path) -> None:
    """Verifies :memory: SQLite/DuckDB scratchpad seeding, 3-slash URI resolution, and disk persistence."""
    import contextlib
    import sqlite3

    from backend.main import _CUSTOM_DATABASES, clear_custom_databases

    clear_custom_databases()
    try:
        client = TestClient(app)

        # 1. SQLite :memory: connection should have seeded starter tables
        mem_res = client.post(
            "/api/databases/connect",
            json={
                "name": "In-Memory Scratchpad",
                "dialect": "sqlite",
                "file_path": ":memory:",
            },
        )
        assert mem_res.status_code == 200
        mem_body = mem_res.json()
        mem_id = mem_body["database"]["id"]
        assert "products" in mem_body["schema"]["tables"]
        assert "categories" in mem_body["schema"]["tables"]
        assert mem_body["database"]["default_table"] != ""

        exec_mem = client.post(
            f"/api/execute?db={mem_id}",
            json={
                "db": mem_id,
                "spec": {
                    "table": "products",
                    "columns": ["products.name", "products.price"],
                    "limit": 5,
                },
            },
        )
        assert exec_mem.status_code == 200
        assert len(exec_mem.json()["rows"]) == 5
        assert exec_mem.json()["count"] == 8

        # 2. 3-slash sqlite:/// URI resolution for an absolute path
        db_file = tmp_path / "three_slash.sqlite"
        with contextlib.closing(sqlite3.connect(str(db_file))) as sconn:
            sconn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, label TEXT);")
            sconn.execute("INSERT INTO items VALUES (1, 'Widget');")
            sconn.commit()

        three_slash_uri = f"sqlite:///{str(db_file).lstrip('/')}"
        uri_test = client.post(
            "/api/databases/test",
            json={"name": "Three Slash URI", "connection_uri": three_slash_uri},
        )
        assert uri_test.status_code == 200
        assert uri_test.json()["table_count"] == 1

        # 3. Persistence reload when in-memory dict is cleared (simulating process restart)
        _CUSTOM_DATABASES.clear()
        list_res = client.get("/api/databases")
        assert list_res.status_code == 200
        persisted_ids = [d["id"] for d in list_res.json()["databases"]]
        assert mem_id in persisted_ids

        # 4. Federated hub can query a :memory: custom SQLite database via materialization fallback
        fed_exec = client.post(
            "/api/execute?db=federated_hub",
            json={
                "db": "federated_hub",
                "spec": {
                    "table": f"{mem_id}__products",
                    "columns": [f"{mem_id}__products.name"],
                    "limit": 3,
                },
            },
        )
        assert fed_exec.status_code == 200
        assert len(fed_exec.json()["rows"]) == 3
    finally:
        clear_custom_databases()


def test_upload_edge_cases_beyond_200_rows_and_overflow() -> None:
    """Verifies JSONL/JSON uploads with keys/type shifts after row 200, uint64 IDs, empty dicts, and 'items' table keys."""
    import base64
    import json

    from backend.main import clear_custom_databases

    clear_custom_databases()
    try:
        client = TestClient(app)

        # 1. JSONL introducing a new key at row 205 and a string id after 200 integer ids
        rows = [{"id": i, "amount": i * 5} for i in range(1, 205)]
        rows.append(
            {"id": "ext-205", "amount": "pending", "late_note": "added_after_200"}
        )
        jsonl_bytes = "\n".join(json.dumps(r) for r in rows).encode("utf-8")
        res_late = client.post(
            "/api/databases/upload",
            json={
                "name": "Late Schema Shift",
                "filename": "late_shift.jsonl",
                "content_base64": base64.b64encode(jsonl_bytes).decode("ascii"),
            },
        )
        assert res_late.status_code == 200
        late_cols = [
            c["name"]
            for c in res_late.json()["schema"]["tables"]["late_shift"]["columns"]
        ]
        assert "late_note" in late_cols

        # 2. 64-bit unsigned integer (> 2**63 - 1) should fall back to TEXT without OverflowError
        snowflake_bytes = json.dumps(
            [{"id": 18446744073709551615, "label": "uint64_max"}]
        ).encode("utf-8")
        res_sf = client.post(
            "/api/databases/upload",
            json={
                "name": "Snowflake IDs",
                "filename": "snowflakes.json",
                "content_base64": base64.b64encode(snowflake_bytes).decode("ascii"),
            },
        )
        assert res_sf.status_code == 200

        # 3. Empty JSON object [{}] should return 400 Bad Request, not 500 OperationalError
        res_empty = client.post(
            "/api/databases/upload",
            json={
                "name": "Empty Object",
                "filename": "empty.json",
                "content_base64": base64.b64encode(b"[{}]").decode("ascii"),
            },
        )
        assert res_empty.status_code == 400

        # 4. Multi-table JSON containing an 'items' table alongside 'orders' preserves both tables and FKs
        store_bytes = json.dumps(
            {
                "orders": [{"id": 1, "total": 99.5}],
                "items": [{"id": 10, "order_id": 1, "sku": "SKU-1"}],
            }
        ).encode("utf-8")
        res_store = client.post(
            "/api/databases/upload",
            json={
                "name": "Store Multi Table",
                "filename": "store.json",
                "content_base64": base64.b64encode(store_bytes).decode("ascii"),
            },
        )
        assert res_store.status_code == 200
        store_tables = res_store.json()["schema"]["tables"]
        assert "orders" in store_tables
        assert "items" in store_tables
        assert any(
            fk["table"] == "items" and fk["foreign_table"] == "orders"
            for fk in res_store.json()["schema"]["foreign_keys"]
        )

        # 5. Upload a .sql script file that creates tables with foreign keys and inserts rows
        sql_script = (
            b"CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT);\n"
            b"CREATE TABLE employees (id INTEGER PRIMARY KEY, dept_id INTEGER REFERENCES departments(id), full_name TEXT);\n"
            b"INSERT INTO departments VALUES (1, 'Engineering'), (2, 'Design');\n"
            b"INSERT INTO employees VALUES (10, 1, 'Ada Lovelace'), (11, 2, 'Grace Hopper');\n"
        )
        res_sql = client.post(
            "/api/databases/upload",
            json={
                "name": "Company SQL Dump",
                "filename": "company_dump.sql",
                "content_base64": base64.b64encode(sql_script).decode("ascii"),
            },
        )
        assert res_sql.status_code == 200
        sql_schema = res_sql.json()["schema"]
        assert "departments" in sql_schema["tables"]
        assert "employees" in sql_schema["tables"]
        assert any(
            fk["table"] == "employees" and fk["foreign_table"] == "departments"
            for fk in sql_schema["foreign_keys"]
        )

        # 6. Reject .sql script containing restricted statements (ATTACH/PRAGMA)
        bad_sql = b"ATTACH DATABASE '/etc/passwd' AS pwn; CREATE TABLE t (id INT);"
        res_bad_sql = client.post(
            "/api/databases/upload",
            json={
                "name": "Bad SQL Dump",
                "filename": "bad.sql",
                "content_base64": base64.b64encode(bad_sql).decode("ascii"),
            },
        )
        assert res_bad_sql.status_code == 400
        assert "restricted" in res_bad_sql.json()["detail"].lower()

        # 7. Reject .sql script that creates no tables
        empty_sql = b"-- comment only\nSELECT 1;"
        res_empty_sql = client.post(
            "/api/databases/upload",
            json={
                "name": "No Tables SQL",
                "filename": "empty.sql",
                "content_base64": base64.b64encode(empty_sql).decode("ascii"),
            },
        )
        assert res_empty_sql.status_code == 400

        # 8. Accept .sql dump with safe PRAGMA foreign_keys, comments with PRAGMA/ATTACH,
        # string literals containing 'attach'/'pragma', and SERIAL/AUTO_INCREMENT DDL
        real_world_sql = (
            b"-- sqlite3 dump header with PRAGMA and ATTACH mentioned in comments\n"
            b"PRAGMA foreign_keys=OFF;\n"
            b"CREATE TABLE tickets (\n"
            b"  id SERIAL PRIMARY KEY,\n"
            b"  notes TEXT\n"
            b") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;\n"
            b"INSERT INTO tickets (notes) VALUES ('Please attach the pragma report to detach issue');\n"
        )
        res_real_sql = client.post(
            "/api/databases/upload",
            json={
                "name": "Real World SQL Dump",
                "filename": "real_world.sql",
                "content_base64": base64.b64encode(real_world_sql).decode("ascii"),
            },
        )
        assert res_real_sql.status_code == 200
        assert "tickets" in res_real_sql.json()["schema"]["tables"]

        # 9. Reject unsafe PRAGMA writable_schema in .sql upload
        unsafe_pragma_sql = b"PRAGMA writable_schema=ON;\nCREATE TABLE t (id INT);"
        res_unsafe_pragma = client.post(
            "/api/databases/upload",
            json={
                "name": "Unsafe Pragma SQL",
                "filename": "unsafe_pragma.sql",
                "content_base64": base64.b64encode(unsafe_pragma_sql).decode("ascii"),
            },
        )
        assert res_unsafe_pragma.status_code == 400

        # 10. Built-in ID collision protection when payload.id is uppercase or hyphenated ("STARTER_DEMO")
        collision_res = client.post(
            "/api/databases/connect",
            json={
                "id": "STARTER_DEMO",
                "name": "Attempted Collision",
                "engine": "sqlite",
                "database": ":memory:",
            },
        )
        assert collision_res.status_code == 200
        assert collision_res.json()["database"]["id"] == "custom_attempted_collision"
        db_list = client.get("/api/databases").json()["databases"]
        builtin_demo = next(d for d in db_list if d["id"] == "starter_demo")
        assert builtin_demo["is_custom"] is False
        assert builtin_demo["name"] != "Attempted Collision"
    finally:
        clear_custom_databases()


def test_builtin_database_registry_contains_only_public_starter_databases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies that the default registry exposes only public starter databases with no local machine paths."""
    from backend.main import clear_custom_databases, get_builtin_database_ids

    monkeypatch.delenv("QB_DEFAULT_DB", raising=False)
    clear_custom_databases()
    try:
        builtin_ids = get_builtin_database_ids()
        assert builtin_ids == {"starter_demo", "federated_hub"}

        client = TestClient(app)
        res = client.get("/api/databases")
        assert res.status_code == 200
        payload = res.json()
        assert payload["default_database"] == "starter_demo"
        assert payload["count"] == 2
        returned_ids = {d["id"] for d in payload["databases"]}
        assert returned_ids == {"starter_demo", "federated_hub"}
    finally:
        clear_custom_databases()


def test_federated_hub_infers_cross_db_foreign_keys_and_failed_upload_cleans_files() -> (
    None
):
    """Verifies dynamic cross-DB FK inference in federated_hub and no leaked .sqlite files on failed upload."""
    import base64

    from backend.main import _UPLOAD_DIR, clear_custom_databases

    clear_custom_databases()
    client = TestClient(app)
    try:
        # 1. Failed upload of empty JSON object rows must not leave an orphaned .sqlite file
        before_files = (
            set(_UPLOAD_DIR.glob("*.sqlite")) if _UPLOAD_DIR.exists() else set()
        )
        bad_json = b"[{}]"
        bad_res = client.post(
            "/api/databases/upload",
            json={
                "name": "Empty Object Upload",
                "filename": "empty_obj.json",
                "content_base64": base64.b64encode(bad_json).decode("ascii"),
            },
        )
        assert bad_res.status_code == 400
        after_files = (
            set(_UPLOAD_DIR.glob("*.sqlite")) if _UPLOAD_DIR.exists() else set()
        )
        assert after_files == before_files

        # 2. Upload a secondary dataset with product_id and user_id columns
        reviews_json = b'[{"id": 1, "product_id": 1, "user_id": 1, "rating": 5}]'
        up_res = client.post(
            "/api/databases/upload",
            json={
                "id": "custom_reviews",
                "name": "Product Reviews",
                "filename": "reviews.json",
                "content_base64": base64.b64encode(reviews_json).decode("ascii"),
            },
        )
        assert up_res.status_code == 200
        uploaded_db_id = up_res.json()["database"]["id"]

        # 3. Introspect federated_hub and confirm cross-database FKs are dynamically inferred
        fed_res = client.get("/api/schema?db=federated_hub")
        assert fed_res.status_code == 200
        fed_schema = fed_res.json()
        fks = fed_schema.get("foreign_keys", [])
        cross_fk_pairs = {
            (fk["table"], fk["column"], fk["foreign_table"], fk["foreign_column"])
            for fk in fks
        }
        assert (
            f"{uploaded_db_id}__reviews",
            "product_id",
            "starter_demo__products",
            "id",
        ) in cross_fk_pairs
        assert (
            f"{uploaded_db_id}__reviews",
            "user_id",
            "starter_demo__users",
            "id",
        ) in cross_fk_pairs
    finally:
        clear_custom_databases()


def test_columns_distinct_endpoint_and_timegrain_execution() -> None:
    """Verifies GET /api/columns/distinct and camelCase timeGrain compilation in POST /api/execute."""
    client = TestClient(app)

    # 1. Distinct values for orders.status
    res = client.get("/api/columns/distinct?db=starter_demo&table=orders&column=status")
    assert res.status_code == 200
    body = res.json()
    assert body["table"] == "orders"
    assert body["column"] == "status"
    assert "COMPLETED" in body["values"]

    # 2. Reject invalid identifier on /api/columns/distinct
    bad_res = client.get(
        "/api/columns/distinct?db=starter_demo&table=orders;DROP&column=status"
    )
    assert bad_res.status_code == 400

    # 3. Execute spec with camelCase timeGrain on date column + aggregate
    exec_res = client.post(
        "/api/execute?db=starter_demo",
        json={
            "db": "starter_demo",
            "spec": {
                "table": "orders",
                "columns": [
                    {
                        "column": "orders.created_at",
                        "timeGrain": "month",
                        "alias": "order_month",
                    },
                    {
                        "column": "orders.total_amount",
                        "agg": "SUM",
                        "alias": "monthly_revenue",
                    },
                ],
                "limit": 10,
            },
        },
    )
    assert exec_res.status_code == 200
    exec_data = exec_res.json()
    assert "STRFTIME('%Y-%m-01'" in exec_data["sql"]
    assert "GROUP BY" in exec_data["sql"]
    assert len(exec_data["rows"]) >= 1
