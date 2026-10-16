"""
Tests for FastAPI Router Integration (Milestone 4).
===================================================
Verifies:
- /schema, /compile, /validate, /execute, /export endpoints
- Turnkey router creation with SQLiteConnector
- Fail-closed multi-tenant row-level isolation via tenant_resolver
- Anti-tampering: unauthenticated tenant_id in client body is strictly ignored
- Restriction of direct raw SQL execution under multi-tenant isolation
- Async and sync tenant resolvers
- Route prefixing and custom tags
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from query_builder.connectors.sqlite import SQLiteConnector
from query_builder.integrations.fastapi import create_query_builder_router
from query_builder.policy import SecurityPolicy, TenantContext


@pytest.fixture
def sqlite_test_db():
    """Initializes an in-memory SQLite connector with tenant-partitioned sample data."""
    raw_conn = sqlite3.connect(":memory:", check_same_thread=False)
    cur = raw_conn.cursor()

    cur.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            name TEXT NOT NULL,
            email TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            amount NUMERIC NOT NULL
        )
    """)

    # Populate tenant-1 and tenant-2 rows
    cur.executemany(
        "INSERT INTO users (id, tenant_id, name, email) VALUES (?, ?, ?, ?)",
        [
            (1, "tenant-1", "Alice Alpha", "alice@alpha.com"),
            (2, "tenant-1", "Bob Alpha", "bob@alpha.com"),
            (3, "tenant-2", "Charlie Beta", "charlie@beta.com"),
        ],
    )

    cur.executemany(
        "INSERT INTO orders (id, tenant_id, user_id, amount) VALUES (?, ?, ?, ?)",
        [
            (101, "tenant-1", 1, 99.50),
            (102, "tenant-1", 2, 149.00),
            (103, "tenant-2", 3, 500.00),
        ],
    )

    raw_conn.commit()

    connector = SQLiteConnector(connection=raw_conn)
    return connector


def test_fastapi_endpoints_open_mode(sqlite_test_db):
    """Verifies schema, compile, validate, execute, export in single-tenant / open mode."""
    router = create_query_builder_router(
        connector=sqlite_test_db,
        security=SecurityPolicy(enforce_tenant_isolation=False),
        prefix="/qb",
    )

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # 1. GET /qb/schema
    schema_res = client.get("/qb/schema")
    assert schema_res.status_code == 200
    schema_data = schema_res.json()
    assert "tables" in schema_data
    assert "users" in schema_data["tables"]
    assert "orders" in schema_data["tables"]

    # Alias /qb/introspect
    alias_res = client.get("/qb/introspect")
    assert alias_res.status_code == 200

    # 2. POST /qb/compile
    compile_res = client.post(
        "/qb/compile",
        json={
            "spec": {
                "table": "users",
                "columns": ["users.id", "users.name"],
                "limit": 10,
            },
            "dialect": "sqlite",
        },
    )
    assert compile_res.status_code == 200
    comp_data = compile_res.json()
    assert "sql" in comp_data
    assert "SELECT" in comp_data["sql"]
    assert 'FROM "users"' in comp_data["sql"]

    # 3. POST /qb/validate
    valid_res = client.post(
        "/qb/validate",
        json={"sql": "SELECT id, name FROM users WHERE id = 1"},
    )
    assert valid_res.status_code == 200
    assert valid_res.json().get("valid") is True

    # 4. POST /qb/execute (spec)
    exec_res = client.post(
        "/qb/execute",
        json={
            "spec": {
                "table": "users",
                "columns": ["users.id", "users.name"],
                "limit": 10,
            }
        },
    )
    assert exec_res.status_code == 200
    exec_data = exec_res.json()
    assert exec_data["count"] == 3
    assert len(exec_data["rows"]) == 3
    assert "users.id" in exec_data["columns"] or "id" in exec_data["columns"]

    # 5. POST /qb/execute (raw sql in open mode)
    raw_exec_res = client.post(
        "/qb/execute",
        json={"sql": "SELECT COUNT(*) as total FROM users"},
    )
    assert raw_exec_res.status_code == 200
    assert raw_exec_res.json()["rows"][0]["total"] == 3

    # 6. POST /qb/export (CSV)
    export_res = client.post(
        "/qb/export",
        json={
            "format": "csv",
            "spec": {
                "table": "users",
                "columns": ["users.name", "users.email"],
            },
        },
    )
    assert export_res.status_code == 200
    assert "text/csv" in export_res.headers.get("content-type", "")
    assert "attachment; filename=" in export_res.headers.get("content-disposition", "")
    csv_text = export_res.text
    assert "Alice Alpha" in csv_text
    assert "charlie@beta.com" in csv_text

    # 7. POST /qb/export (JSON format)
    export_json_res = client.post(
        "/qb/export",
        json={
            "format": "json",
            "rows": [{"name": "Alice", "score": 100}, {"name": "Bob", "score": 90}],
            "columns": ["name", "score"],
        },
    )
    assert export_json_res.status_code == 200
    assert "application/json" in export_json_res.headers.get("content-type", "")
    assert len(export_json_res.json()) == 2


def test_fastapi_multi_tenant_isolation_sync(sqlite_test_db):
    """Verifies fail-closed multi-tenant RLS isolation with synchronous tenant_resolver."""

    def sync_tenant_resolver(request: Request) -> TenantContext | None:
        tenant_id = request.headers.get("X-Tenant-ID")
        if not tenant_id:
            return None
        return TenantContext(tenant_id=tenant_id)

    router = create_query_builder_router(
        connector=sqlite_test_db,
        tenant_resolver=sync_tenant_resolver,
    )

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # 1. Execute query as tenant-1 -> only sees tenant-1 rows
    res_t1 = client.post(
        "/execute",
        headers={"X-Tenant-ID": "tenant-1"},
        json={
            "spec": {
                "table": "users",
                "columns": ["users.id", "users.name", "users.tenant_id"],
            }
        },
    )
    assert res_t1.status_code == 200
    t1_data = res_t1.json()
    assert t1_data["count"] == 2
    for row in t1_data["rows"]:
        assert (
            row.get("tenant_id") == "tenant-1"
            or row.get("users.tenant_id") == "tenant-1"
        )

    # 2. Execute query as tenant-2 -> only sees tenant-2 rows
    res_t2 = client.post(
        "/execute",
        headers={"X-Tenant-ID": "tenant-2"},
        json={
            "spec": {
                "table": "users",
                "columns": ["users.id", "users.name", "users.tenant_id"],
            }
        },
    )
    assert res_t2.status_code == 200
    t2_data = res_t2.json()
    assert t2_data["count"] == 1
    row_t2 = t2_data["rows"][0]
    assert (
        row_t2.get("name") == "Charlie Beta"
        or row_t2.get("users.name") == "Charlie Beta"
    )

    # 3. Security Anti-Tampering: Client attempts to forge tenant_id in body
    # Header: tenant-1, Body: "tenant_id": "tenant-2"
    res_forge = client.post(
        "/execute",
        headers={"X-Tenant-ID": "tenant-1"},
        json={
            "spec": {
                "table": "users",
                "columns": ["users.id", "users.name"],
            },
            "tenant_id": "tenant-2",  # Malicious forgery attempt in request body
        },
    )
    assert res_forge.status_code == 200
    forge_data = res_forge.json()
    # Must still only return tenant-1's 2 rows!
    assert forge_data["count"] == 2
    for r in forge_data["rows"]:
        assert "Charlie Beta" not in str(r)

    # 4. Fail-closed: Missing tenant header -> 401 Unauthorized
    res_unauth = client.post(
        "/execute",
        json={
            "spec": {
                "table": "users",
                "columns": ["users.id"],
            }
        },
    )
    assert res_unauth.status_code == 401
    assert "TenantContext could not be resolved" in res_unauth.json()["detail"]

    # 5. Fail-closed: Empty tenant header -> 401 Unauthorized
    res_empty_tenant = client.post(
        "/execute",
        headers={"X-Tenant-ID": "   "},
        json={
            "spec": {
                "table": "users",
                "columns": ["users.id"],
            }
        },
    )
    assert res_empty_tenant.status_code == 401

    # 6. Raw SQL execution blocked under multi-tenant isolation
    res_raw_sql = client.post(
        "/execute",
        headers={"X-Tenant-ID": "tenant-1"},
        json={"sql": "SELECT * FROM users"},
    )
    assert res_raw_sql.status_code == 403
    assert "Raw SQL execution is restricted" in res_raw_sql.json()["detail"]


def test_fastapi_async_tenant_resolver(sqlite_test_db):
    """Verifies that an asynchronous coroutine tenant_resolver works seamlessly."""

    async def async_tenant_resolver(request: Request) -> TenantContext | None:
        auth_header = request.headers.get("Authorization")
        if auth_header == "Bearer token-tenant-1":
            return TenantContext(tenant_id="tenant-1", user_id="u1")
        if auth_header == "Bearer token-tenant-2":
            return TenantContext(tenant_id="tenant-2", user_id="u2")
        return None

    router = create_query_builder_router(
        connector=sqlite_test_db,
        tenant_resolver=async_tenant_resolver,
    )

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # Authorized request with Bearer token
    res = client.post(
        "/execute",
        headers={"Authorization": "Bearer token-tenant-1"},
        json={
            "spec": {
                "table": "orders",
                "columns": ["orders.id", "orders.amount"],
            }
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 2
    # Verify tenant-2 order (500.0) is not included
    amounts = [r.get("amount") or r.get("orders.amount") for r in data["rows"]]
    assert 500.0 not in amounts

    # Invalid token -> 401 Unauthorized
    bad_res = client.post(
        "/execute",
        headers={"Authorization": "Bearer invalid-token"},
        json={"spec": {"table": "orders", "columns": ["orders.id"]}},
    )
    assert bad_res.status_code == 401


def test_fastapi_compile_with_tenant_isolation(sqlite_test_db):
    """Verifies /compile injects tenant isolation filter into generated SQL."""

    def resolver(request: Request) -> str | None:
        return request.headers.get("X-Tenant")

    router = create_query_builder_router(
        connector=sqlite_test_db,
        tenant_resolver=resolver,
    )

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    res = client.post(
        "/compile",
        headers={"X-Tenant": "tenant-99"},
        json={
            "spec": {
                "table": "users",
                "columns": ["users.id", "users.name"],
            },
            "dialect": "sqlite",
        },
    )
    assert res.status_code == 200
    compiled = res.json()
    # Verified: compiled SQL must contain tenant filter
    assert "WHERE" in compiled["sql"]
    assert "tenant_id" in compiled["sql"]
    assert "tenant-99" in str(compiled["sql"]) or "tenant-99" in str(compiled["params"])


def test_fastapi_validation_error_paths(sqlite_test_db):
    """Verifies 400 Bad Request error paths for empty/missing request bodies."""
    router = create_query_builder_router(
        connector=sqlite_test_db,
        security=SecurityPolicy(enforce_tenant_isolation=False),
    )

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # Empty body to /execute
    res_empty_exec = client.post("/execute", json={})
    assert res_empty_exec.status_code == 400

    # Malformed spec to /compile
    res_bad_compile = client.post("/compile", json={"spec": {}})
    assert res_bad_compile.status_code == 400


def test_fastapi_resolver_exception_fails_closed(sqlite_test_db):
    """Verifies that an unhandled exception in tenant_resolver fails closed with 401."""

    def buggy_resolver(request: Request):
        raise RuntimeError("Auth service connection timeout")

    router = create_query_builder_router(
        connector=sqlite_test_db,
        tenant_resolver=buggy_resolver,
    )

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    res = client.post(
        "/execute",
        json={"spec": {"table": "users", "columns": ["users.id"]}},
    )
    assert res.status_code == 401
    assert "Tenant authentication failed" in res.json()["detail"]


def test_fastapi_connector_string_and_factory(sqlite_test_db):
    """Verifies connector resolution from string name and factory callable."""
    # From string
    router_str = create_query_builder_router(
        "sqlite", security=SecurityPolicy(enforce_tenant_isolation=False)
    )
    app_str = FastAPI()
    app_str.include_router(router_str)
    client_str = TestClient(app_str)
    res_str = client_str.get("/schema")
    assert res_str.status_code == 200

    # From factory callable
    router_factory = create_query_builder_router(
        lambda: sqlite_test_db, security=SecurityPolicy(enforce_tenant_isolation=False)
    )
    app_factory = FastAPI()
    app_factory.include_router(router_factory)
    client_factory = TestClient(app_factory)
    res_factory = client_factory.get("/schema")
    assert res_factory.status_code == 200


def test_django_integration_guards_without_django():
    """Verifies that Django integration functions raise clear ImportErrors when dependencies are missing."""
    from unittest.mock import patch

    from query_builder.integrations import django as django_mod

    with (
        patch.object(django_mod, "DJANGO_AVAILABLE", False),
        pytest.raises(ImportError, match="Django is not installed"),
    ):
        django_mod.create_django_urls("sqlite")

    with (
        patch.object(
            django_mod,
            "_get_drf",
            side_effect=ImportError("Django REST Framework is not installed"),
        ),
        pytest.raises(ImportError, match="Django REST Framework is not installed"),
    ):
        django_mod.create_drf_views("sqlite")

    with (
        patch.object(django_mod, "NINJA_AVAILABLE", False),
        pytest.raises(ImportError, match="Django Ninja is not installed"),
    ):
        django_mod.create_ninja_router("sqlite")


def test_fastapi_security_profile_production_enforces_isolation(sqlite_test_db):
    """Verifies SecurityProfile.production() normalization and strict raw SQL rejection under tenant isolation."""
    from query_builder.security import SecurityProfile

    def resolve_tenant(request: Request):
        return TenantContext(tenant_id="tenant-1")

    # Pass SecurityConfig via SecurityProfile.production()
    router = create_query_builder_router(
        connector=sqlite_test_db,
        security=SecurityProfile.production(),
        tenant_resolver=resolve_tenant,
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # 1. Spec query should execute and be isolated to tenant-1
    res = client.post(
        "/execute",
        json={"spec": {"table": "users", "columns": ["users.id", "users.name"]}},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 2
    for row in data["rows"]:
        assert "Alpha" in row.get("name", "") or "Alpha" in str(row)

    # 2. Raw SQL must be rejected with 403 Forbidden
    res_raw = client.post(
        "/execute",
        json={"sql": "SELECT * FROM users"},
    )
    assert res_raw.status_code == 403
    assert "restricted when tenant isolation is enforced" in res_raw.json()["detail"]

    # 3. Raw SQL export must also be rejected with 403 Forbidden
    res_export = client.post(
        "/export",
        json={"sql": "SELECT * FROM users", "format": "csv"},
    )
    assert res_export.status_code == 403
    assert "restricted when tenant isolation is enforced" in res_export.json()["detail"]


def test_fastapi_tenant_resolver_extra_jwt_claims(sqlite_test_db):
    """Verifies tenant_resolver returning a dictionary with extra JWT claims is accepted and attributes preserved."""

    def jwt_resolver(request: Request):
        return {
            "tenant_id": "tenant-2",
            "user_id": "user-charlie",
            "roles": ["member"],
            "iss": "https://auth.example.com",
            "sub": "auth0|987654",
            "department": "Engineering",
        }

    router = create_query_builder_router(
        connector=sqlite_test_db,
        tenant_resolver=jwt_resolver,
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    res = client.post(
        "/execute",
        json={"spec": {"table": "users", "columns": ["users.id", "users.name"]}},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 1
    assert (
        data["rows"][0].get("name") == "Charlie Beta"
        or data["rows"][0].get("users.name") == "Charlie Beta"
    )


def test_fastapi_schema_filtering_by_policy(sqlite_test_db):
    """Verifies that allowed_tables and restricted_tables on security policy filter introspected schema."""
    policy = SecurityPolicy(
        allowed_tables=["users"],
        restricted_tables=["orders"],
        enforce_tenant_isolation=False,
    )
    router = create_query_builder_router(
        connector=sqlite_test_db,
        security=policy,
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    res = client.get("/schema")
    assert res.status_code == 200
    tables = res.json()["tables"]
    assert "users" in tables
    assert "orders" not in tables


def test_fastapi_async_connector_methods():
    """Verifies that async connector methods (introspect_schema, execute, execute_raw) are cleanly awaited."""
    from unittest.mock import AsyncMock, MagicMock

    from query_builder.models import ColumnMeta, SchemaSnapshot, TableMeta

    fake_schema = SchemaSnapshot(
        tables={
            "items": TableMeta(
                name="items", columns=[ColumnMeta(name="id", data_type="INTEGER")]
            )
        }
    )

    async_conn = MagicMock()
    async_conn.dialect_name = "postgres"
    async_conn.introspect_schema = AsyncMock(return_value=fake_schema)
    async_conn.execute = AsyncMock(
        return_value={
            "columns": ["id"],
            "rows": [{"id": 1}],
            "count": 1,
            "sql": "SELECT 1",
        }
    )
    async_conn.execute_raw = AsyncMock(return_value=(["id"], [{"id": 1}], 1.5))

    router = create_query_builder_router(
        connector=async_conn,
        security=SecurityPolicy(enforce_tenant_isolation=False),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # 1. /schema
    schema_res = client.get("/schema")
    assert schema_res.status_code == 200
    assert "items" in schema_res.json()["tables"]

    # 2. /execute spec
    exec_res = client.post(
        "/execute", json={"spec": {"table": "items", "columns": ["items.id"]}}
    )
    assert exec_res.status_code == 200
    assert exec_res.json()["rows"] == [{"id": 1}]

    # 3. /execute raw sql
    raw_res = client.post("/execute", json={"sql": "SELECT * FROM items"})
    assert raw_res.status_code == 200
    assert raw_res.json()["rows"] == [{"id": 1}]

    # 4. /execute raw sql with tenant_id in payload is rejected (403)
    raw_tenant_res = client.post(
        "/execute", json={"sql": "SELECT * FROM items", "tenant_id": "tenant-abc"}
    )
    assert raw_tenant_res.status_code == 403
    assert (
        "Raw SQL execution is restricted when tenant isolation is enforced"
        in raw_tenant_res.json()["detail"]
    )

    # 5. /export raw sql with tenant_id in payload is rejected (403)
    export_tenant_res = client.post(
        "/export", json={"sql": "SELECT * FROM items", "tenant_id": "tenant-abc"}
    )
    assert export_tenant_res.status_code == 403
    assert (
        "Raw SQL export is restricted when tenant isolation is enforced"
        in export_tenant_res.json()["detail"]
    )


def test_django_helpers_simulation(sqlite_test_db):
    """Simulates internal Django integration helper functions without needing live Django installed."""
    from query_builder.config import PrivacySecurityConfig, SecurityConfig
    from query_builder.integrations.django import (
        _exec_conn_method,
        _filter_schema_tables,
        _get_effective_policy,
        _resolve_tenant_sync,
    )

    # 1. Policy normalization
    sec_cfg = SecurityConfig(
        privacy=PrivacySecurityConfig(
            tenant_column="tenant_id", enforce_tenant_isolation=False
        )
    )
    norm_policy = _get_effective_policy(sec_cfg, has_tenant_resolver=True)
    assert norm_policy.enforce_tenant_isolation is True
    assert norm_policy.tenant_column == "tenant_id"

    # 2. Tenant resolver sync and async
    ctx_sync = _resolve_tenant_sync(
        None, lambda r: {"tenant_id": "t1", "user_id": "u1", "extra_claim": "val"}
    )
    assert ctx_sync.tenant_id == "t1"
    assert ctx_sync.attributes.get("extra_claim") == "val"

    async def async_resolver(r):
        return TenantContext(tenant_id="t2")

    ctx_async = _resolve_tenant_sync(None, async_resolver)
    assert ctx_async.tenant_id == "t2"

    # Fails closed on None or empty string
    with pytest.raises(PermissionError, match="Unauthorized"):
        _resolve_tenant_sync(None, lambda r: None)

    with pytest.raises(PermissionError, match="empty tenant_id"):
        _resolve_tenant_sync(None, lambda r: "")

    # 3. _exec_conn_method with sync and async callables
    class MockConn:
        def sync_m(self, x: int) -> int:
            return x * 2

        async def async_m(self, x: int) -> int:
            return x + 10

        def no_timeout(self, q: str) -> str:
            return q

    mock_conn = MockConn()
    assert _exec_conn_method(mock_conn, "sync_m", 5) == 10
    assert _exec_conn_method(mock_conn, "async_m", 5) == 15
    # Statement timeout stripped safely if parameter not in signature
    assert (
        _exec_conn_method(mock_conn, "no_timeout", "ok", statement_timeout_ms=1000)
        == "ok"
    )

    # 4. _filter_schema_tables
    raw_tables = {"users": {}, "internal_secrets": {}, "orders": {}}
    filtered = _filter_schema_tables(
        {"tables": dict(raw_tables)},
        SecurityPolicy(
            allowed_tables=["users", "orders"], restricted_tables=["orders"]
        ),
    )
    assert "users" in filtered["tables"]
    assert "internal_secrets" not in filtered["tables"]
    assert "orders" not in filtered["tables"]


def test_fastapi_schema_cache_ttl(sqlite_test_db):
    app = FastAPI()
    router = create_query_builder_router(
        connector=sqlite_test_db, schema_cache_ttl=60.0
    )
    app.include_router(router)
    client = TestClient(app)

    # First fetch populates cache
    resp1 = client.get("/schema")
    assert resp1.status_code == 200
    assert "tables" in resp1.json()

    # Second fetch served from cache
    resp2 = client.get("/schema")
    assert resp2.status_code == 200

    # Refresh bypasses cache
    resp3 = client.get("/schema?refresh=true")
    assert resp3.status_code == 200


def test_fastapi_export_stream(sqlite_test_db):
    app = FastAPI()
    router = create_query_builder_router(connector=sqlite_test_db)
    app.include_router(router)
    client = TestClient(app)

    # CSV stream
    resp_csv = client.post(
        "/export/stream",
        json={
            "spec": {"table": "users", "columns": ["id", "name"]},
            "format": "csv",
        },
    )
    assert resp_csv.status_code == 200
    assert "text/csv" in resp_csv.headers["content-type"]
    assert "id,name" in resp_csv.text

    # JSON stream
    resp_json = client.post(
        "/export/stream",
        json={
            "spec": {"table": "users", "columns": ["id", "name"]},
            "format": "json",
        },
    )
    assert resp_json.status_code == 200
    assert "application/json" in resp_json.headers["content-type"]
    assert "Alice Alpha" in resp_json.text


def test_fastapi_explain(sqlite_test_db):
    app = FastAPI()
    router = create_query_builder_router(connector=sqlite_test_db)
    app.include_router(router)
    client = TestClient(app)

    resp = client.post(
        "/explain",
        json={
            "spec": {"table": "users", "columns": ["id", "name"]},
            "dialect": "sqlite",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "SELECT" in data["sql"]
    assert "plan" in data
    assert "performance" in data


def test_fastapi_join_path(sqlite_test_db):
    app = FastAPI()
    router = create_query_builder_router(connector=sqlite_test_db)
    app.include_router(router)
    client = TestClient(app)

    resp = client.post(
        "/join-path",
        json={
            "active_tables": ["users"],
            "target_table": "orders",
            "schema_snapshot": {
                "tables": {
                    "users": {
                        "columns": [{"name": "id", "data_type": "INTEGER"}],
                        "foreign_keys": [],
                    },
                    "orders": {
                        "columns": [{"name": "id"}, {"name": "user_id"}],
                        "foreign_keys": [
                            {
                                "table": "orders",
                                "column": "user_id",
                                "foreign_table": "users",
                                "foreign_column": "id",
                            }
                        ],
                    },
                }
            },
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is True
    assert len(data["path"]) == 1


def test_fastapi_nlq(sqlite_test_db):
    app = FastAPI()
    router = create_query_builder_router(connector=sqlite_test_db)
    app.include_router(router)
    client = TestClient(app)

    resp = client.post(
        "/nlq",
        json={
            "prompt": "Show all users",
            "dialect": "sqlite",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["spec"]["table"] == "users"
    assert "SELECT" in data["sql"]


def test_fastapi_edge_branches(sqlite_test_db):
    from unittest.mock import patch

    from query_builder.exceptions import SecurityError

    app = FastAPI()
    router = create_query_builder_router(connector=sqlite_test_db)
    app.include_router(router)
    client = TestClient(app)

    # 1. /export with stream=True
    resp_stream = client.post(
        "/export",
        json={"spec": {"table": "users"}, "stream": True, "format": "csv"},
    )
    assert resp_stream.status_code == 200

    # 2. /export/stream exceptions
    with patch(
        "query_builder.integrations.fastapi.stream_export_dataset",
        side_effect=SecurityError("threat"),
    ):
        assert (
            client.post("/export/stream", json={"spec": {"table": "users"}}).status_code
            == 403
        )
    with patch(
        "query_builder.integrations.fastapi.stream_export_dataset",
        side_effect=RuntimeError("glitch"),
    ):
        assert (
            client.post("/export/stream", json={"spec": {"table": "users"}}).status_code
            == 400
        )

    # 3. /explain exceptions
    with patch(
        "query_builder.integrations.fastapi.estimate_plan_from_spec",
        side_effect=SecurityError("threat"),
    ):
        assert (
            client.post("/explain", json={"spec": {"table": "users"}}).status_code
            == 403
        )
    with patch(
        "query_builder.integrations.fastapi.estimate_plan_from_spec",
        side_effect=RuntimeError("glitch"),
    ):
        assert (
            client.post("/explain", json={"spec": {"table": "users"}}).status_code
            == 400
        )

    # 4. /join-path with schema_snapshot=None and exceptions
    resp_jp = client.post(
        "/join-path",
        json={"active_tables": ["users"], "target_table": "orders"},
    )
    assert resp_jp.status_code == 200
    with patch(
        "query_builder.integrations.fastapi.find_join_path",
        side_effect=RuntimeError("glitch"),
    ):
        assert (
            client.post(
                "/join-path",
                json={"active_tables": ["users"], "target_table": "orders"},
            ).status_code
            == 400
        )

    # 5. /nlq empty prompt and exceptions
    assert client.post("/nlq", json={"prompt": ""}).status_code == 400
    with patch("query_builder.ai.client.ask_ai", side_effect=SecurityError("threat")):
        assert client.post("/nlq", json={"prompt": "users"}).status_code == 403
    with patch("query_builder.ai.client.ask_ai", side_effect=RuntimeError("glitch")):
        assert client.post("/nlq", json={"prompt": "users"}).status_code == 400


def test_fastapi_http_exception_and_nlq_tenant_policy(sqlite_test_db):
    from fastapi import HTTPException

    def bad_tenant(r):
        raise HTTPException(status_code=401, detail="Unauthorized tenant")

    app = FastAPI()
    router = create_query_builder_router(
        connector=sqlite_test_db,
        tenant_resolver=bad_tenant,
        security=SecurityPolicy(enforce_tenant_isolation=True),
    )
    app.include_router(router)
    client = TestClient(app)

    assert (
        client.post("/export/stream", json={"spec": {"table": "users"}}).status_code
        == 401
    )
    assert client.post("/nlq", json={"prompt": "users"}).status_code == 401

    # NLQ with valid tenant isolation
    app2 = FastAPI()
    router2 = create_query_builder_router(
        connector=sqlite_test_db,
        tenant_resolver=lambda r: "tenant-1",
        security=SecurityPolicy(enforce_tenant_isolation=True),
    )
    app2.include_router(router2)
    client2 = TestClient(app2)
    resp2 = client2.post("/nlq", json={"prompt": "Show users", "dialect": "sqlite"})
    assert resp2.status_code == 200
    assert "tenant_id" in resp2.json()["sql"]


def test_fastapi_compile_validates_sql_ast(sqlite_test_db):
    """Verifies that /compile validates SQL AST safety and rejects non-read-only compiled SQL."""
    from unittest.mock import patch

    app = FastAPI()
    router = create_query_builder_router(connector=sqlite_test_db)
    app.include_router(router)
    client = TestClient(app)

    # Control: valid select compiles with 200
    res_ok = client.post(
        "/compile", json={"spec": {"table": "users", "columns": ["id"]}}
    )
    assert res_ok.status_code == 200

    # Adversarial: compiled SQL containing non-read-only statement fails closed with 403
    with patch(
        "query_builder.compiler.QueryCompiler.compile",
        return_value=("DROP TABLE users;", [], None, None),
    ):
        res_bad = client.post(
            "/compile", json={"spec": {"table": "users", "columns": ["id"]}}
        )
        assert res_bad.status_code == 403
        assert "Security violation" in res_bad.json()["detail"]


def test_fastapi_policy_immutability_and_join_path_table_filter(sqlite_test_db):
    """Verifies that get_effective_policy does not mutate caller's SecurityPolicy and join-path filters tables."""
    orig_policy = SecurityPolicy(
        enforce_tenant_isolation=False,
        restricted_tables=["orders"],
    )
    app = FastAPI()
    router = create_query_builder_router(
        connector=sqlite_test_db,
        security=orig_policy,
        tenant_resolver=lambda r: "t1",
    )
    app.include_router(router)
    client = TestClient(app)

    # Immutability check: caller's policy was not mutated
    assert orig_policy.enforce_tenant_isolation is False

    # Join path table filtering
    res = client.post(
        "/join-path",
        json={"active_tables": ["users"], "target_table": "orders"},
    )
    # Since orders is in restricted_tables, it's filtered out of the schema snapshot
    assert res.status_code == 200
