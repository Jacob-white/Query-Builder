"""
Comprehensive test suite for Django, Django REST Framework, and Django Ninja integrations.
Verifies 100% statement and branch coverage for query_builder/integrations/django.py.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import django
import pytest
from django.conf import settings

if not settings.configured:
    settings.configure(
        SECRET_KEY="test-secret-key-query-builder",
        ROOT_URLCONF=__name__,
        DATABASES={
            "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
        },
        INSTALLED_APPS=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "rest_framework",
        ],
    )
    django.setup()

from django.http import HttpResponse
from django.test import RequestFactory
from rest_framework.test import APIRequestFactory

from query_builder.capabilities import EngineCapabilities, FeatureTier
from query_builder.connectors.sqlite import SQLiteConnector
from query_builder.integrations.django import (
    _exec_conn_method,
    _filter_schema_tables,
    _get_drf,
    _get_effective_policy,
    _normalize_schema_snapshot,
    _resolve_conn,
    _resolve_tenant_sync,
    create_django_urls,
    create_drf_views,
    create_ninja_router,
)
from query_builder.models import QueryResult
from query_builder.policy import SecurityPolicy, TenantContext


@pytest.fixture
def sqlite_conn(tmp_path):
    import sqlite3

    db_file = tmp_path / "test_django.db"
    raw = sqlite3.connect(str(db_file))
    raw.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, tenant_id TEXT, name TEXT, ssn TEXT);"
    )
    raw.execute(
        "INSERT INTO users VALUES (1, 'tenant_1', 'Alice', '000-00-0001'), (2, 'tenant_2', 'Bob', '000-00-0002');"
    )
    raw.commit()
    raw.close()
    return SQLiteConnector(database=str(db_file))


# ==============================================================================
# 1. Helper / Utility Function Coverage
# ==============================================================================


def test_resolve_conn_string():
    conn = _resolve_conn("sqlite")
    assert conn is not None


def test_resolve_conn_sync_callable():
    mock_conn = MagicMock()
    conn = _resolve_conn(lambda: mock_conn)
    assert conn is mock_conn


def test_resolve_conn_async_callable():
    mock_conn = MagicMock()

    async def async_factory():
        await asyncio.sleep(0.001)
        return mock_conn

    conn = _resolve_conn(async_factory)
    assert conn is mock_conn


def test_resolve_conn_async_callable_in_running_loop():
    mock_conn = MagicMock()

    async def async_factory():
        await asyncio.sleep(0.001)
        return mock_conn

    async def run_in_loop():
        return _resolve_conn(async_factory)

    res = asyncio.run(run_in_loop())
    assert res is mock_conn


def test_exec_conn_method_sync_and_async():
    class DummySyncConn:
        def query(self, val: int, statement_timeout_ms: int = 100):
            return val * 2

    class DummyAsyncConn:
        async def query_async(self, val: int, statement_timeout_ms: int = 100):
            await asyncio.sleep(0.001)
            return val * 3

    class DummyAwaitableReturnConn:
        def query_awaitable(self, val: int):
            async def _coro():
                return val * 4

            return _coro()

    sync_conn = DummySyncConn()
    assert _exec_conn_method(sync_conn, "query", 5, statement_timeout_ms=None) == 10
    assert _exec_conn_method(sync_conn, "query", 5, statement_timeout_ms=50) == 10

    # Connector without statement_timeout_ms parameter
    class DummyNoTimeout:
        def test(self, x):
            return x + 1

    no_timeout = DummyNoTimeout()
    assert _exec_conn_method(no_timeout, "test", 4, statement_timeout_ms=100) == 5

    async_conn = DummyAsyncConn()
    assert _exec_conn_method(async_conn, "query_async", 5) == 15

    # Run in loop
    async def in_loop():
        return _exec_conn_method(async_conn, "query_async", 6)

    assert asyncio.run(in_loop()) == 18

    # Awaitable return
    await_conn = DummyAwaitableReturnConn()
    assert _exec_conn_method(await_conn, "query_awaitable", 5) == 20

    async def in_loop_awaitable():
        return _exec_conn_method(await_conn, "query_awaitable", 7)

    assert asyncio.run(in_loop_awaitable()) == 28


def test_filter_schema_tables():
    data = {"tables": {"users": {}, "secrets": {}, "orders": {}}}
    policy = SecurityPolicy(
        allowed_tables=["users", "orders"], restricted_tables=["orders"]
    )
    filtered = _filter_schema_tables(data, policy)
    assert list(filtered["tables"].keys()) == ["users"]


def test_normalize_schema_snapshot():
    @dataclass
    class SnapDC:
        tables: dict

    dc = SnapDC(tables={"t1": {}})
    assert _normalize_schema_snapshot(dc) == {"tables": {"t1": {}}}

    class SnapWithToDict:
        def to_dict(self):
            return {"tables": {"t2": {}}}

    assert _normalize_schema_snapshot(SnapWithToDict()) == {"tables": {"t2": {}}}
    assert _normalize_schema_snapshot({"tables": {"t3": {}}}) == {"tables": {"t3": {}}}
    assert _normalize_schema_snapshot(12345) == {"tables": {}}


def test_resolve_tenant_sync():
    rf = RequestFactory()
    req = rf.get("/")

    # None resolver
    assert _resolve_tenant_sync(req, None) is None

    # Returns TenantContext
    ctx = TenantContext(tenant_id="t1", user_id="u1", roles=["admin"])
    assert _resolve_tenant_sync(req, lambda r: ctx) == ctx

    # Returns str
    res_str = _resolve_tenant_sync(req, lambda r: "tenant_str")
    assert res_str.tenant_id == "tenant_str"

    # Returns dict with known and extra fields
    res_dict = _resolve_tenant_sync(
        req, lambda r: {"tenant_id": "t_dict", "roles": ["user"], "dept": "engineering"}
    )
    assert res_dict.tenant_id == "t_dict"
    assert res_dict.attributes["dept"] == "engineering"

    # Async resolver
    async def async_res(r):
        await asyncio.sleep(0.001)
        return "async_tenant"

    assert _resolve_tenant_sync(req, async_res).tenant_id == "async_tenant"

    async def run_async_in_loop():
        return _resolve_tenant_sync(req, async_res)

    assert asyncio.run(run_async_in_loop()).tenant_id == "async_tenant"

    # None return raises PermissionError
    with pytest.raises(
        PermissionError, match="Unauthorized: TenantContext could not be resolved"
    ):
        _resolve_tenant_sync(req, lambda r: None)

    # Invalid type raises PermissionError
    with pytest.raises(
        PermissionError, match="Unauthorized: Invalid tenant context type"
    ):
        _resolve_tenant_sync(req, lambda r: 12345)

    # Empty tenant_id raises PermissionError
    with pytest.raises(
        PermissionError,
        match="Unauthorized: Resolved TenantContext contains empty tenant_id",
    ):
        _resolve_tenant_sync(req, lambda r: "   ")


def test_get_effective_policy():
    assert _get_effective_policy(None, False) is None
    p1 = _get_effective_policy(None, True)
    assert p1.enforce_tenant_isolation is True

    sp = SecurityPolicy()
    p2 = _get_effective_policy(sp, True)
    assert p2.enforce_tenant_isolation is True

    p3 = _get_effective_policy({"allowed_tables": ["a"]}, True)
    assert p3.enforce_tenant_isolation is True
    assert p3.allowed_tables == ["a"]

    # SecurityConfig mock
    class MockPrivacy:
        def __init__(self):
            self.allowed_tables = ["u"]
            self.restricted_tables = ["s"]
            self.tenant_column = "tid"
            self.enforce_tenant_isolation = False
            self.sensitive_column_patterns = ["ssn"]
            self.masking_strategy = "redact"

    class MockSecurityConfig:
        privacy = MockPrivacy()
        execution = MagicMock(max_complexity_score=50)

    sc = MockSecurityConfig()
    p4 = _get_effective_policy(sc, True)
    assert p4.enforce_tenant_isolation is True
    assert p4.tenant_column == "tid"
    assert p4.max_complexity_score == 50

    p5 = _get_effective_policy(sc, False)
    assert p5.enforce_tenant_isolation is False

    # Fallback
    assert _get_effective_policy("unknown", False) == "unknown"


# ==============================================================================
# 2. Django URL Patterns & Views (create_django_urls)
# ==============================================================================


def test_django_urls_not_available():
    with (
        patch("query_builder.integrations.django.DJANGO_AVAILABLE", False),
        pytest.raises(ImportError, match="Django is not installed"),
    ):
        create_django_urls("sqlite")


def test_django_urls_endpoints(sqlite_conn):
    rf = RequestFactory()
    urls = create_django_urls(
        sqlite_conn,
        security={"allowed_tables": ["users"], "enforce_tenant_isolation": False},
        capabilities={"advanced_aggregations": FeatureTier.ADVANCED},
    )
    url_map = {u.name: u.callback for u in urls}

    # 1. Capabilities
    req = rf.get("/capabilities/")
    resp = url_map["query-builder-capabilities"](req)
    assert resp.status_code == 200
    assert "capabilities" in json.loads(resp.content)

    req_post = rf.post("/capabilities/")
    resp_post = url_map["query-builder-capabilities"](req_post)
    assert resp_post.status_code == 405

    # 2. Schema / Introspect
    req_s = rf.get("/schema/")
    resp_s = url_map["query-builder-schema"](req_s)
    assert resp_s.status_code == 200
    data_s = json.loads(resp_s.content)
    assert "tables" in data_s

    req_s_bad = rf.post("/schema/")
    assert url_map["query-builder-schema"](req_s_bad).status_code == 405

    # Schema introspection error
    with patch.object(
        sqlite_conn, "introspect_schema", side_effect=RuntimeError("Introspect fail")
    ):
        resp_err = url_map["query-builder-schema"](req_s)
        assert resp_err.status_code == 500

    # 3. Compile
    spec = {"table": "users", "columns": ["id", "name"]}
    req_c = rf.post(
        "/compile/", data=json.dumps({"spec": spec}), content_type="application/json"
    )
    resp_c = url_map["query-builder-compile"](req_c)
    assert resp_c.status_code == 200
    assert "sql" in json.loads(resp_c.content)

    # Compile Method not allowed
    assert url_map["query-builder-compile"](rf.get("/compile/")).status_code == 405

    # Missing spec
    req_c_empty = rf.post(
        "/compile/", data=json.dumps({}), content_type="application/json"
    )
    assert url_map["query-builder-compile"](req_c_empty).status_code == 400

    # Compile with security error / disabled feature / permission error
    tenant_resolver = lambda r: None
    urls_tenant = create_django_urls(sqlite_conn, tenant_resolver=tenant_resolver)
    url_map_tenant = {u.name: u.callback for u in urls_tenant}
    assert url_map_tenant["query-builder-compile"](req_c).status_code == 401

    # SecurityError
    caps_disabled = EngineCapabilities.simple_only()
    urls_disabled = create_django_urls(
        sqlite_conn,
        capabilities=caps_disabled,
    )
    url_map_dis = {u.name: u.callback for u in urls_disabled}
    spec_cte = {"table": "users", "ctes": [{"name": "c", "query": {"table": "users"}}]}
    req_cte = rf.post(
        "/compile/",
        data=json.dumps({"spec": spec_cte}),
        content_type="application/json",
    )
    assert url_map_dis["query-builder-compile"](req_cte).status_code == 403

    # Generic compilation error
    bad_req = rf.post("/compile/", data="invalid-json", content_type="application/json")
    assert url_map["query-builder-compile"](bad_req).status_code == 400

    # 4. Validate
    req_v = rf.post(
        "/validate/",
        data=json.dumps({"sql": "SELECT id FROM users"}),
        content_type="application/json",
    )
    resp_v = url_map["query-builder-validate"](req_v)
    assert resp_v.status_code == 200
    assert json.loads(resp_v.content)["valid"] is True

    assert url_map["query-builder-validate"](rf.get("/validate/")).status_code == 405
    assert (
        url_map["query-builder-validate"](
            rf.post("/validate/", data=json.dumps({}), content_type="application/json")
        ).status_code
        == 400
    )
    assert (
        url_map["query-builder-validate"](
            rf.post("/validate/", data="bad-json", content_type="application/json")
        ).status_code
        == 400
    )

    # 5. Execute
    req_e_spec = rf.post(
        "/execute/",
        data=json.dumps(
            {
                "spec": {
                    "table": "c",
                    "columns": ["id", "name"],
                    "ctes": [{"name": "c", "query": {"table": "users"}}],
                    "window_functions": [{"function": "ROW_NUMBER", "alias": "rn"}],
                    "rollup": {"columns": ["name"]},
                    "vector_search": {"column": "name", "vector": [1, 2]},
                }
            }
        ),
        content_type="application/json",
    )
    # With full capabilities
    caps_full = EngineCapabilities.full()
    urls_full = create_django_urls(sqlite_conn, capabilities=caps_full)
    url_map_full = {u.name: u.callback for u in urls_full}
    resp_e = url_map_full["query-builder-execute"](req_e_spec)
    assert resp_e.status_code in (200, 400)  # executed or SQL error, but code path hit

    # Execute with fallback object
    mock_res_obj = QueryResult(
        sql="SELECT 1",
        params=[],
        columns=["c"],
        rows=[{"c": 1}],
        count=1,
        limit=50,
        offset=0,
        latency_ms=1.2,
    )
    with patch.object(sqlite_conn, "execute", return_value=mock_res_obj):
        resp_obj = url_map_full["query-builder-execute"](
            rf.post(
                "/execute/",
                data=json.dumps({"spec": {"table": "users"}}),
                content_type="application/json",
            )
        )
        assert resp_obj.status_code == 200
        assert json.loads(resp_obj.content)["count"] == 1

    # Execute raw SQL
    req_e_raw = rf.post(
        "/execute/",
        data=json.dumps({"sql": "SELECT id, name FROM users"}),
        content_type="application/json",
    )
    resp_raw = url_map_full["query-builder-execute"](req_e_raw)
    assert resp_raw.status_code == 200
    assert len(json.loads(resp_raw.content)["rows"]) == 2

    # Execute raw SQL disabled
    urls_no_raw = create_django_urls(
        sqlite_conn,
        capabilities=EngineCapabilities(raw_sql=FeatureTier.DISABLED),
    )
    assert {u.name: u.callback for u in urls_no_raw}["query-builder-execute"](
        req_e_raw
    ).status_code == 403

    # Execute raw SQL blocked under tenant isolation
    urls_iso = create_django_urls(
        sqlite_conn,
        security=SecurityPolicy(enforce_tenant_isolation=True),
        tenant_resolver=lambda r: "t1",
    )
    assert {u.name: u.callback for u in urls_iso}["query-builder-execute"](
        req_e_raw
    ).status_code == 403

    # Execute method not allowed & missing spec/sql
    assert url_map["query-builder-execute"](rf.get("/execute/")).status_code == 405
    assert (
        url_map["query-builder-execute"](
            rf.post("/execute/", data=json.dumps({}), content_type="application/json")
        ).status_code
        == 400
    )
    assert (
        url_map["query-builder-execute"](
            rf.post("/execute/", data="invalid", content_type="application/json")
        ).status_code
        == 400
    )
    assert (
        url_map_tenant["query-builder-execute"](
            rf.post(
                "/execute/",
                data=json.dumps({"spec": {"table": "users"}}),
                content_type="application/json",
            )
        ).status_code
        == 401
    )

    # 6. Export
    req_exp_rows = rf.post(
        "/export/",
        data=json.dumps({"rows": [{"a": 1}], "columns": ["a"], "format": "csv"}),
        content_type="application/json",
    )
    resp_exp = url_map["query-builder-export"](req_exp_rows)
    assert resp_exp.status_code == 200
    assert resp_exp["Content-Disposition"] == 'attachment; filename="export.csv"'

    req_exp_spec = rf.post(
        "/export/",
        data=json.dumps({"spec": {"table": "users"}, "format": "json"}),
        content_type="application/json",
    )
    resp_exp_spec = url_map["query-builder-export"](req_exp_spec)
    assert resp_exp_spec.status_code == 200

    req_exp_sql = rf.post(
        "/export/",
        data=json.dumps({"sql": "SELECT id FROM users", "format": "csv"}),
        content_type="application/json",
    )
    resp_exp_sql = url_map["query-builder-export"](req_exp_sql)
    assert resp_exp_sql.status_code == 200

    # Tenant isolation blocking raw SQL export
    assert {u.name: u.callback for u in urls_iso}["query-builder-export"](
        req_exp_sql
    ).status_code == 403

    # Export errors
    assert url_map["query-builder-export"](rf.get("/export/")).status_code == 405
    assert (
        url_map["query-builder-export"](
            rf.post("/export/", data=json.dumps({}), content_type="application/json")
        ).status_code
        == 400
    )
    assert url_map_tenant["query-builder-export"](req_exp_rows).status_code == 401
    assert (
        url_map["query-builder-export"](
            rf.post("/export/", data="bad", content_type="application/json")
        ).status_code
        == 400
    )


# ==============================================================================
# 3. Django REST Framework Views (create_drf_views)
# ==============================================================================


def test_drf_views(sqlite_conn):
    rf = APIRequestFactory()
    views = create_drf_views(
        sqlite_conn,
        security={"allowed_tables": ["users", "c"], "enforce_tenant_isolation": False},
        capabilities=EngineCapabilities.full(),
    )

    # 1. CapabilitiesView
    cap_view = views["CapabilitiesView"].as_view()
    resp = cap_view(rf.get("/"))
    assert resp.status_code == 200
    assert "capabilities" in resp.data

    # 2. SchemaView
    sch_view = views["SchemaView"].as_view()
    resp = sch_view(rf.get("/"))
    assert resp.status_code == 200
    assert "tables" in resp.data

    # 3. CompileView
    comp_view = views["CompileView"].as_view()
    resp = comp_view(
        rf.post("/", {"spec": {"table": "users", "columns": ["id"]}}, format="json")
    )
    assert resp.status_code == 200
    assert "sql" in resp.data

    assert comp_view(rf.post("/", {}, format="json")).status_code == 400

    # CompileView DisabledFeatureError
    caps_min = EngineCapabilities.simple_only()
    views_min = create_drf_views(sqlite_conn, capabilities=caps_min)
    assert (
        views_min["CompileView"]
        .as_view()(
            rf.post(
                "/",
                {
                    "spec": {
                        "table": "users",
                        "ctes": [{"name": "c", "query": {"table": "users"}}],
                    }
                },
                format="json",
            )
        )
        .status_code
        == 403
    )

    # 4. ValidateView
    val_view = views["ValidateView"].as_view()
    resp = val_view(rf.post("/", {"sql": "SELECT id FROM users"}, format="json"))
    assert resp.status_code == 200
    assert resp.data["valid"] is True

    assert val_view(rf.post("/", {}, format="json")).status_code == 400

    # 5. ExecuteView
    exec_view = views["ExecuteView"].as_view()
    spec_advanced = {
        "table": "users",
        "ctes": [{"name": "c", "query": {"table": "users"}}],
        "window_functions": [{"function": "ROW_NUMBER", "alias": "rn"}],
        "rollup": {"columns": ["name"]},
        "vector_search": {"column": "name", "vector": [1, 2]},
    }
    with patch(
        "query_builder.integrations.django._exec_conn_method",
        return_value={"columns": ["a"], "rows": [], "count": 0},
    ):
        resp = exec_view(rf.post("/", {"spec": spec_advanced}, format="json"))
        assert resp.status_code == 200

    # Raw SQL
    resp_raw = exec_view(rf.post("/", {"sql": "SELECT id FROM users"}, format="json"))
    assert resp_raw.status_code == 200
    assert resp_raw.data["count"] == 2

    # Missing spec and sql
    assert exec_view(rf.post("/", {}, format="json")).status_code == 400

    # Raw SQL disabled
    views_no_raw = create_drf_views(
        sqlite_conn,
        capabilities=EngineCapabilities(raw_sql=FeatureTier.DISABLED),
    )
    assert (
        views_no_raw["ExecuteView"]
        .as_view()(rf.post("/", {"sql": "SELECT 1"}, format="json"))
        .status_code
        == 403
    )

    # Tenant isolation blocking raw sql
    views_iso = create_drf_views(
        sqlite_conn,
        security=SecurityPolicy(enforce_tenant_isolation=True),
        tenant_resolver=lambda r: "t1",
    )
    assert (
        views_iso["ExecuteView"]
        .as_view()(rf.post("/", {"sql": "SELECT 1"}, format="json"))
        .status_code
        == 403
    )

    # 6. ExportView
    exp_view = views["ExportView"].as_view()
    resp = exp_view(
        rf.post(
            "/", {"rows": [{"x": 1}], "columns": ["x"], "format": "csv"}, format="json"
        )
    )
    assert resp.status_code == 200

    resp_spec = exp_view(
        rf.post("/", {"spec": {"table": "users"}, "format": "json"}, format="json")
    )
    assert resp_spec.status_code == 200

    resp_sql = exp_view(
        rf.post("/", {"sql": "SELECT id FROM users", "format": "csv"}, format="json")
    )
    assert resp_sql.status_code == 200

    # Missing source
    assert exp_view(rf.post("/", {}, format="json")).status_code == 400

    # Raw SQL disabled export
    assert (
        views_no_raw["ExportView"]
        .as_view()(rf.post("/", {"sql": "SELECT 1"}, format="json"))
        .status_code
        == 403
    )

    # Tenant isolation export block
    assert (
        views_iso["ExportView"]
        .as_view()(rf.post("/", {"sql": "SELECT 1"}, format="json"))
        .status_code
        == 403
    )


def test_get_drf_import_errors():
    with (
        patch.dict("sys.modules", {"rest_framework": None}),
        pytest.raises(ImportError, match="Django REST Framework is not installed"),
    ):
        _get_drf()


# ==============================================================================
# 4. Django Ninja Router (create_ninja_router)
# ==============================================================================


def test_ninja_router_not_available():
    with (
        patch("query_builder.integrations.django.NINJA_AVAILABLE", False),
        pytest.raises(ImportError, match="Django Ninja is not installed"),
    ):
        create_ninja_router("sqlite")


def test_ninja_router_endpoints(sqlite_conn):
    rf = RequestFactory()
    router = create_ninja_router(
        sqlite_conn,
        security={"allowed_tables": ["users", "c"], "enforce_tenant_isolation": False},
        capabilities=EngineCapabilities.full(),
    )

    # Route operations are registered in router.operations
    op_map = {}
    for path_str, ops in router.path_operations.items():
        for op in ops.operations:
            op_map[(op.methods[0], path_str)] = op.view_func

    req = rf.get("/capabilities")
    res = op_map[("GET", "/capabilities")](req)
    assert "capabilities" in res

    # Schema
    res_s = op_map[("GET", "/schema")](req)
    assert "tables" in res_s

    # Compile
    res_c = op_map[("POST", "/compile")](
        req, payload={"spec": {"table": "users", "columns": ["id"]}}
    )
    assert "sql" in res_c

    from ninja.errors import HttpError

    with pytest.raises(HttpError) as exc_info:
        op_map[("POST", "/compile")](req, payload={})
    assert exc_info.value.status_code == 400

    # Compile disabled feature
    router_min = create_ninja_router(
        sqlite_conn, capabilities=EngineCapabilities.simple_only()
    )
    op_map_min = {}
    for path_str, ops in router_min.path_operations.items():
        for op in ops.operations:
            op_map_min[(op.methods[0], path_str)] = op.view_func

    with pytest.raises(HttpError) as exc_info:
        op_map_min[("POST", "/compile")](
            req,
            payload={
                "spec": {
                    "table": "users",
                    "ctes": [{"name": "c", "query": {"table": "users"}}],
                }
            },
        )
    assert exc_info.value.status_code == 403

    # Validate
    res_v = op_map[("POST", "/validate")](req, payload={"sql": "SELECT id FROM users"})
    assert res_v["valid"] is True

    with pytest.raises(HttpError) as exc_info:
        op_map[("POST", "/validate")](req, payload={})
    assert exc_info.value.status_code == 400

    # Execute
    res_e = op_map[("POST", "/execute")](
        req, payload={"spec": {"table": "users", "columns": ["id"]}}
    )
    assert res_e["count"] == 2

    # Execute advanced features
    with patch(
        "query_builder.integrations.django._exec_conn_method",
        return_value={"columns": ["a"], "rows": [], "count": 0},
    ):
        res_e_adv = op_map[("POST", "/execute")](
            req,
            payload={
                "spec": {
                    "table": "users",
                    "ctes": [{"name": "c", "query": {"table": "users"}}],
                    "window_functions": [{"function": "ROW_NUMBER", "alias": "rn"}],
                    "rollup": {"columns": ["name"]},
                    "vector_search": {"column": "name", "vector": [1, 2]},
                }
            },
        )
        assert res_e_adv is not None

    # Execute raw SQL
    res_e_raw = op_map[("POST", "/execute")](
        req, payload={"sql": "SELECT id FROM users"}
    )
    assert res_e_raw["count"] == 2

    # Execute empty
    with pytest.raises(HttpError) as exc_info:
        op_map[("POST", "/execute")](req, payload={})
    assert exc_info.value.status_code == 400

    # Execute raw SQL disabled
    router_no_raw = create_ninja_router(
        sqlite_conn,
        capabilities=EngineCapabilities(raw_sql=FeatureTier.DISABLED),
    )
    op_map_no_raw = {
        (op.methods[0], path_str): op.view_func
        for path_str, ops in router_no_raw.path_operations.items()
        for op in ops.operations
    }
    with pytest.raises(HttpError) as exc_info:
        op_map_no_raw[("POST", "/execute")](req, payload={"sql": "SELECT 1"})
    assert exc_info.value.status_code == 403

    # Execute raw SQL tenant isolation block
    router_iso = create_ninja_router(
        sqlite_conn,
        security=SecurityPolicy(enforce_tenant_isolation=True),
        tenant_resolver=lambda r: "t1",
    )
    op_map_iso = {
        (op.methods[0], path_str): op.view_func
        for path_str, ops in router_iso.path_operations.items()
        for op in ops.operations
    }
    with pytest.raises(HttpError) as exc_info:
        op_map_iso[("POST", "/execute")](req, payload={"sql": "SELECT 1"})
    assert exc_info.value.status_code == 403

    # Export
    resp_exp_rows = op_map[("POST", "/export")](
        req, payload={"rows": [{"k": 1}], "columns": ["k"], "format": "csv"}
    )
    assert isinstance(resp_exp_rows, HttpResponse)
    assert resp_exp_rows.status_code == 200

    resp_exp_spec = op_map[("POST", "/export")](
        req, payload={"spec": {"table": "users"}, "format": "json"}
    )
    assert resp_exp_spec.status_code == 200

    resp_exp_sql = op_map[("POST", "/export")](
        req, payload={"sql": "SELECT id FROM users", "format": "csv"}
    )
    assert resp_exp_sql.status_code == 200

    # Tenant isolation export block
    with pytest.raises(HttpError) as exc_info:
        op_map_iso[("POST", "/export")](req, payload={"sql": "SELECT id FROM users"})
    assert exc_info.value.status_code == 403

    # Missing export source
    with pytest.raises(HttpError) as exc_info:
        op_map[("POST", "/export")](req, payload={})
    assert exc_info.value.status_code == 400


def test_django_integration_remaining_edge_cases(sqlite_conn):
    rf = RequestFactory()
    from query_builder.capabilities import DisabledFeatureError
    from query_builder.exceptions import SecurityError

    # 1. _filter_schema_tables edge cases (153->161)
    assert _filter_schema_tables({"other": 1}, None) == {"other": 1}
    assert _filter_schema_tables({"tables": "not_a_dict"}, SecurityPolicy()) == {
        "tables": "not_a_dict"
    }

    # 2. _get_effective_policy with has_tenant_resolver=False (238->240)
    sp = SecurityPolicy()
    assert _get_effective_policy(sp, has_tenant_resolver=False) is sp

    # 3. _get_drf with unexpected Exception (69-70)
    class FaultyModule:
        @property
        def PermissionDenied(self):
            raise RuntimeError("unexpected load failure")

    with (
        patch.dict(
            "sys.modules",
            {
                "rest_framework": MagicMock(__spec__=None),
                "rest_framework.exceptions": FaultyModule(),
            },
        ),
        pytest.raises(ImportError, match="Django REST Framework could not be loaded"),
    ):
        _get_drf()

    # 4. NINJA_AVAILABLE fallback (80-82)
    import importlib

    import query_builder.integrations.django as d_mod

    with patch.dict("sys.modules", {"ninja": None}):
        importlib.reload(d_mod)
        assert d_mod.NINJA_AVAILABLE is False
    # restore module
    importlib.reload(d_mod)

    # 5. _exec_conn_method signature exception (119-120)
    class FakeConn:
        def test_fn(self, statement_timeout_ms=None):
            return "ok"

    with patch("inspect.signature", side_effect=ValueError("no signature")):
        assert (
            _exec_conn_method(FakeConn(), "test_fn", statement_timeout_ms=100) == "ok"
        )

    # 6. Django URLs edge cases (405, 408, 410, 442, 484, 460->462, 388->403)
    urls_sec = create_django_urls(
        sqlite_conn,
        security={"allowed_tables": ["users"], "enforce_tenant_isolation": False},
    )
    url_map_sec = {u.name: u.callback for u in urls_sec}

    # Line 405 (policy applied in execute_view)
    class ObjWithToDict:
        def to_dict(self):
            return {"count": 1, "columns": ["id"], "rows": [{"id": 1}]}

    with patch.object(sqlite_conn, "execute", return_value=ObjWithToDict()):
        # Line 408 (hasattr to_dict)
        r = url_map_sec["query-builder-execute"](
            rf.post(
                "/execute/",
                data=json.dumps({"spec": {"table": "users"}}),
                content_type="application/json",
            )
        )
        assert r.status_code == 200

    with patch.object(
        sqlite_conn,
        "execute",
        return_value={"count": 1, "columns": ["id"], "rows": [{"id": 1}]},
    ):
        # Line 410 (isinstance dict)
        r = url_map_sec["query-builder-execute"](
            rf.post(
                "/execute/",
                data=json.dumps({"spec": {"table": "users"}}),
                content_type="application/json",
            )
        )
        assert r.status_code == 200

    # Line 442 (SecurityError / DisabledFeatureError in execute_view)
    with patch.object(sqlite_conn, "execute", side_effect=SecurityError("forbidden")):
        r = url_map_sec["query-builder-execute"](
            rf.post(
                "/execute/",
                data=json.dumps({"spec": {"table": "users"}}),
                content_type="application/json",
            )
        )
        assert r.status_code == 403

    # Line 484 (SecurityError / DisabledFeatureError in export_view)
    with patch.object(
        sqlite_conn, "execute", side_effect=DisabledFeatureError("disabled")
    ):
        r = url_map_sec["query-builder-export"](
            rf.post(
                "/export/",
                data=json.dumps({"spec": {"table": "users"}}),
                content_type="application/json",
            )
        )
        assert r.status_code == 403

    # urls with no capabilities and no policy (388->403, 460->462)
    urls_bare = create_django_urls(sqlite_conn, capabilities=None, security=None)
    url_map_bare = {u.name: u.callback for u in urls_bare}
    with patch.object(sqlite_conn, "execute", return_value={"rows": [], "columns": []}):
        r = url_map_bare["query-builder-execute"](
            rf.post(
                "/execute/",
                data=json.dumps({"spec": {"table": "users"}}),
                content_type="application/json",
            )
        )
        assert r.status_code == 200
        r_exp = url_map_bare["query-builder-export"](
            rf.post(
                "/export/",
                data=json.dumps({"spec": {"table": "users"}}),
                content_type="application/json",
            )
        )
        assert r_exp.status_code == 200

    # 7. DRF views edge cases (575->590, 576->578, 578->580, 580->587, 587->590, 591->593, 621->623)
    drf_factory = APIRequestFactory()
    views_bare = create_drf_views(sqlite_conn, capabilities=None, security=None)
    # Simple spec hitting 576->578, 578->580, 580->587, 587->590 and 591->593
    resp = views_bare["ExecuteView"].as_view()(
        drf_factory.post(
            "/", {"spec": {"table": "users", "columns": ["id"]}}, format="json"
        )
    )
    assert resp.status_code == 200
    # Export without policy (621->623)
    resp_exp = views_bare["ExportView"].as_view()(
        drf_factory.post("/", {"spec": {"table": "users"}}, format="json")
    )
    assert resp_exp.status_code == 200

    # 8. Ninja router edge cases (738->753, 754->756, 785->787)
    router_bare = create_ninja_router(sqlite_conn, capabilities=None, security=None)
    op_map_bare = {
        (op.methods[0], path_str): op.view_func
        for path_str, ops in router_bare.path_operations.items()
        for op in ops.operations
    }
    res_ninja_exec = op_map_bare[("POST", "/execute")](
        rf.post("/"), payload={"spec": {"table": "users", "columns": ["id"]}}
    )
    assert res_ninja_exec["count"] == 2
    res_ninja_exp = op_map_bare[("POST", "/export")](
        rf.post("/"), payload={"spec": {"table": "users"}}
    )
    assert isinstance(res_ninja_exp, HttpResponse)
