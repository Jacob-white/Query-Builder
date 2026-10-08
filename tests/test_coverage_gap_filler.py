"""
Comprehensive tests to eliminate all remaining coverage gaps in:
- query_builder/integrations/fastapi.py
- query_builder/mcp_server.py
- query_builder/models.py
- query_builder/policy.py
- query_builder/security.py
"""

from __future__ import annotations

import asyncio
import io
import json
import sqlite3
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from query_builder.capabilities import EngineCapabilities, FeatureTier
from query_builder.compiler import CompilationError
from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.sqlite import SQLiteConnector
from query_builder.exceptions import SecurityError
from query_builder.integrations.fastapi import (
    _exec_conn_method,
    _resolve_conn,
    create_query_builder_router,
)
from query_builder.mcp_server import McpServer, _run_coroutine_safely
from query_builder.models import (
    CaseWhenBranch,
    CaseWhenSpec,
    CubeSpec,
    FilterSpec,
    GroupingSetsSpec,
    PivotSpec,
    QueryResult,
    QuerySpec,
    RollupSpec,
    SetOperationSpec,
)
from query_builder.policy import (
    ColumnPolicy,
    RowPolicy,
    SecurityPolicy,
    TablePolicy,
    TenantContext,
    apply_security_policy,
)
from query_builder.security import calculate_ast_complexity


@pytest.fixture
def sqlite_test_db(tmp_path):
    db_file = tmp_path / "gap_test.db"
    raw_conn = sqlite3.connect(str(db_file))
    raw_conn.execute(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, tenant_id TEXT, name TEXT, ssn TEXT);"
    )
    raw_conn.execute(
        "INSERT INTO items VALUES (1, 't1', 'Widget', '111'), (2, 't2', 'Gadget', '222');"
    )
    raw_conn.commit()
    raw_conn.close()
    # TestClient serves requests from its own thread, so the connection must not be thread-bound.
    return SQLiteConnector(database=str(db_file), check_same_thread=False)


# ==============================================================================
# 1. FastAPI Integration Coverage Gaps
# ==============================================================================


def test_fastapi_resolve_conn_async_factory(sqlite_test_db):
    async def async_factory():
        await asyncio.sleep(0.001)
        return sqlite_test_db

    app = FastAPI()
    router = create_query_builder_router(connector=async_factory)
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/capabilities")
    assert resp.status_code == 200


def test_fastapi_exec_conn_method_awaitable():
    class DummyAwaitableConn:
        def test_method(self, x):
            async def _coro():
                return x * 10

            return _coro()

    conn = DummyAwaitableConn()
    res = asyncio.run(_exec_conn_method(conn, "test_method", 3))
    assert res == 30


def test_fastapi_not_available():
    with (
        patch("query_builder.integrations.fastapi.FASTAPI_AVAILABLE", False),
        pytest.raises(ImportError, match="FastAPI is not installed"),
    ):
        create_query_builder_router("sqlite")


def test_fastapi_invalid_tenant_context_type(sqlite_test_db):
    app = FastAPI()
    router = create_query_builder_router(
        connector=sqlite_test_db,
        tenant_resolver=lambda r: (
            12345
        ),  # Invalid type (not TenantContext, str, or dict)
    )
    app.include_router(router)
    client = TestClient(app)
    resp = client.post("/compile", json={"spec": {"table": "items", "columns": ["id"]}})
    assert resp.status_code == 401
    assert "Invalid tenant context type" in resp.json()["detail"]


def test_fastapi_effective_policy_variants(sqlite_test_db):
    # SecurityPolicy instance with tenant_resolver
    sp = SecurityPolicy(enforce_tenant_isolation=False)
    app1 = FastAPI()
    app1.include_router(
        create_query_builder_router(
            sqlite_test_db, security=sp, tenant_resolver=lambda r: "t1"
        )
    )
    client1 = TestClient(app1)
    client1.get("/schema")
    assert sp.enforce_tenant_isolation is True

    # dict with tenant_resolver
    app2 = FastAPI()
    app2.include_router(
        create_query_builder_router(
            sqlite_test_db,
            security={"allowed_tables": ["items"]},
            tenant_resolver=lambda r: "t1",
        )
    )
    client2 = TestClient(app2)
    client2.get("/schema")

    # custom object fallback
    app3 = FastAPI()
    app3.include_router(
        create_query_builder_router(sqlite_test_db, security="custom_fallback")
    )
    client3 = TestClient(app3)
    client3.get("/schema")


def test_fastapi_schema_introspection_fallbacks_and_errors(sqlite_test_db):
    # Snapshot with to_dict
    class SnapshotToDict:
        def to_dict(self):
            return {"tables": {"items": {}}}

    with patch.object(
        sqlite_test_db, "introspect_schema", return_value=SnapshotToDict()
    ):
        app = FastAPI()
        app.include_router(create_query_builder_router(sqlite_test_db))
        client = TestClient(app)
        resp = client.get("/schema")
        assert resp.status_code == 200

    # Snapshot fallback when not to_dict, not dict, but dict() fails
    with patch.object(sqlite_test_db, "introspect_schema", return_value=object()):
        app = FastAPI()
        app.include_router(create_query_builder_router(sqlite_test_db))
        client = TestClient(app)
        resp = client.get("/schema")
        assert resp.status_code == 200
        assert resp.json()["tables"] == {}

    # Introspection failure -> 500
    with patch.object(
        sqlite_test_db, "introspect_schema", side_effect=RuntimeError("DB exploded")
    ):
        app = FastAPI()
        app.include_router(create_query_builder_router(sqlite_test_db))
        client = TestClient(app)
        resp = client.get("/schema")
        assert resp.status_code == 500


def test_fastapi_compile_exception_paths(sqlite_test_db):
    app = FastAPI()
    app.include_router(create_query_builder_router(sqlite_test_db))
    client = TestClient(app)

    # CompilationError / generic exception -> 400
    with patch(
        "query_builder.integrations.fastapi.QueryCompiler.compile",
        side_effect=CompilationError("Syntax boom"),
    ):
        resp = client.post(
            "/compile", json={"spec": {"table": "items", "columns": ["id"]}}
        )
        assert resp.status_code == 400
        assert "Compilation error" in resp.json()["detail"]


def test_fastapi_validate_exception_path(sqlite_test_db):
    app = FastAPI()
    app.include_router(create_query_builder_router(sqlite_test_db))
    client = TestClient(app)

    with patch(
        "query_builder.integrations.fastapi.validate_sql_ast",
        side_effect=RuntimeError("AST boom"),
    ):
        resp = client.post("/validate", json={"sql": "SELECT 1"})
        assert resp.status_code == 400
        assert "Validation error" in resp.json()["detail"]


def test_fastapi_execute_features_and_fallbacks(sqlite_test_db):
    app = FastAPI()
    caps = EngineCapabilities.full()
    app.include_router(create_query_builder_router(sqlite_test_db, capabilities=caps))
    client = TestClient(app)

    # Missing table in target_spec -> 400
    resp_bad = client.post("/execute", json={"spec": {"columns": ["id"]}})
    assert resp_bad.status_code == 400

    # Advanced features in spec + timeout_ms
    spec_adv = {
        "table": "items",
        "ctes": [{"name": "c", "query": {"table": "items"}}],
        "window_functions": [{"function": "ROW_NUMBER", "alias": "rn"}],
        "rollup": {"columns": ["name"]},
        "vector_search": {"column": "name", "vector": [0.1, 0.2]},
    }
    resp_adv = client.post("/execute", json={"spec": spec_adv, "timeout_ms": 1000})
    assert resp_adv.status_code in (200, 400)

    # Connector returns object with to_dict
    class ResultWithToDict:
        def to_dict(self):
            return {"rows": [{"id": 1}], "columns": ["id"], "count": 1}

    with patch.object(sqlite_test_db, "execute", return_value=ResultWithToDict()):
        resp = client.post("/execute", json={"spec": {"table": "items"}})
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    # Connector returns QueryResult dataclass
    qr = QueryResult(
        sql="SELECT 1",
        params=[],
        columns=["c"],
        rows=[{"c": 42}],
        count=1,
        limit=50,
        offset=0,
        latency_ms=1.5,
    )
    with patch.object(sqlite_test_db, "execute", return_value=qr):
        resp_qr = client.post("/execute", json={"spec": {"table": "items"}})
        assert resp_qr.status_code == 200
        assert resp_qr.json()["count"] == 1

    # SecurityError / DisabledFeatureError / generic Exception in execute
    with patch.object(
        sqlite_test_db, "execute", side_effect=SecurityError("Blocked by policy")
    ):
        resp_sec = client.post("/execute", json={"spec": {"table": "items"}})
        assert resp_sec.status_code == 403

    with patch.object(
        sqlite_test_db, "execute", side_effect=RuntimeError("Execute crash")
    ):
        resp_crash = client.post("/execute", json={"spec": {"table": "items"}})
        assert resp_crash.status_code == 400


def test_fastapi_export_edge_cases(sqlite_test_db):
    app = FastAPI()
    app.include_router(create_query_builder_router(sqlite_test_db))
    client = TestClient(app)

    # Spec missing table -> 400
    resp_no_tbl = client.post("/export", json={"spec": {"columns": ["id"]}})
    assert resp_no_tbl.status_code == 400

    # Spec without policy or tenant_ctx (line 522)
    resp_spec = client.post(
        "/export", json={"spec": {"table": "items"}, "format": "json"}
    )
    assert resp_spec.status_code == 200

    # Connector returns QueryResult object (not dict) (line 531)
    qr = QueryResult(
        sql="SELECT 1",
        params=[],
        columns=["c"],
        rows=[{"c": 99}],
        count=1,
        limit=50,
        offset=0,
    )
    with patch.object(sqlite_test_db, "execute", return_value=qr):
        resp_qr = client.post(
            "/export", json={"spec": {"table": "items"}, "format": "json"}
        )
        assert resp_qr.status_code == 200

    # Raw SQL export failing AST safety (line 544)
    resp_unsafe_sql = client.post(
        "/export", json={"sql": "DROP TABLE items;", "format": "csv"}
    )
    assert resp_unsafe_sql.status_code == 403

    # Raw SQL export success (lines 548-551)
    resp_safe_sql = client.post(
        "/export", json={"sql": "SELECT id, name FROM items", "format": "csv"}
    )
    assert resp_safe_sql.status_code == 200

    # Neither rows, spec, nor sql provided (line 553)
    resp_empty = client.post("/export", json={"format": "csv"})
    assert resp_empty.status_code == 400

    # SecurityError (line 570)
    with patch.object(
        sqlite_test_db, "execute", side_effect=SecurityError("Export security fail")
    ):
        resp_sec = client.post(
            "/export", json={"spec": {"table": "items"}, "format": "json"}
        )
        assert resp_sec.status_code == 403

    # Generic exception (line 572)
    with patch.object(
        sqlite_test_db, "execute", side_effect=RuntimeError("Export disk crash")
    ):
        resp_err = client.post(
            "/export", json={"spec": {"table": "items"}, "format": "json"}
        )
        assert resp_err.status_code == 400


# ==============================================================================
# 2. MCP Server Coverage Gaps
# ==============================================================================


def test_mcp_run_coroutine_safely():
    async def sample():
        await asyncio.sleep(0.001)
        return "done"

    # Not running in loop
    assert _run_coroutine_safely(sample()) == "done"

    # Running inside an active loop
    async def nested():
        return _run_coroutine_safely(sample())

    assert asyncio.run(nested()) == "done"


def test_mcp_server_notifications_and_dispatch_types():
    server = McpServer()

    # notifications/initialized returns None
    assert (
        server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
        is None
    )

    # query_builder_compile with spec as JSON string
    res_comp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "query_builder_compile",
                "arguments": {
                    "spec": json.dumps({"table": "items", "columns": ["id"]})
                },
            },
        }
    )
    assert res_comp["result"]["isError"] is False

    # query_builder_validate with spec as JSON string and no sql
    res_val_spec = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "query_builder_validate",
                "arguments": {
                    "spec": json.dumps({"table": "items", "columns": ["id"]})
                },
            },
        }
    )
    assert res_val_spec["result"]["isError"] is False

    # query_builder_validate where validate_sql_ast returns an object (line 327)
    class ValidationObj:
        def __init__(self):
            self.valid = True
            self.is_read_only = True
            self.statement_type = "SELECT"
            self.injection_risk = "NONE"
            self.violations = []
            self.message = "ok"

    with patch(
        "query_builder.mcp_server.validate_sql_ast", return_value=ValidationObj()
    ):
        res_val_obj = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "query_builder_validate",
                    "arguments": {"sql": "SELECT 1"},
                },
            }
        )
        assert res_val_obj["result"]["isError"] is False

    # query_builder_explain_and_advise with spec as JSON string (line 339)
    res_exp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "query_builder_explain_and_advise",
                "arguments": {"spec": json.dumps({"table": "items"})},
            },
        }
    )
    assert res_exp["result"]["isError"] is False

    # query_builder_get_complexity with spec as JSON string (line 356)
    res_comp_score = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "query_builder_get_complexity",
                "arguments": {"spec": json.dumps({"table": "items"})},
            },
        }
    )
    assert res_comp_score["result"]["isError"] is False

    # query_builder_introspect with config as JSON string (line 367)
    # and with AsyncBaseConnector (line 376)
    class FakeAsyncConnector(AsyncBaseConnector):
        def __init__(self, **kwargs):
            pass

        async def connect(self):
            return self

        async def introspect_schema(self, filter_sensitive=True):
            return {"tables": {"async_table": {}}}

        async def execute(self, **kwargs):
            return {"rows": [{"id": i} for i in range(100)], "columns": ["id"]}

    with patch(
        "query_builder.connectors.ConnectorRegistry.get",
        return_value=FakeAsyncConnector(),
    ):
        res_intro_async = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "query_builder_introspect",
                    "arguments": {
                        "connector": "fake",
                        "config": json.dumps({"db": "test"}),
                    },
                },
            }
        )
        assert res_intro_async["result"]["isError"] is False

    # query_builder_introspect snapshots: dataclass, to_dict, fallback
    @dataclass
    class SnapDC:
        tables: dict

    class SnapToDict:
        def to_dict(self):
            return {"tables": {"to_dict_table": {}}}

    mock_sync_conn = MagicMock()
    mock_sync_conn.introspect_schema.return_value = SnapDC(tables={"dc_tbl": {}})
    with patch(
        "query_builder.connectors.ConnectorRegistry.get", return_value=mock_sync_conn
    ):
        assert (
            server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tools/call",
                    "params": {"name": "query_builder_introspect", "arguments": {}},
                }
            )["result"]["isError"]
            is False
        )

    mock_sync_conn.introspect_schema.return_value = SnapToDict()
    with patch(
        "query_builder.connectors.ConnectorRegistry.get", return_value=mock_sync_conn
    ):
        assert (
            server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 8,
                    "method": "tools/call",
                    "params": {"name": "query_builder_introspect", "arguments": {}},
                }
            )["result"]["isError"]
            is False
        )

    mock_sync_conn.introspect_schema.return_value = 12345  # fallback
    with patch(
        "query_builder.connectors.ConnectorRegistry.get", return_value=mock_sync_conn
    ):
        assert (
            server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 9,
                    "method": "tools/call",
                    "params": {"name": "query_builder_introspect", "arguments": {}},
                }
            )["result"]["isError"]
            is False
        )


def test_mcp_execute_and_join_path_edge_cases():
    server = McpServer()

    # Missing spec and sql (line 408)
    res_no_query = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": "query_builder_execute", "arguments": {}},
        }
    )
    assert res_no_query["result"]["isError"] is True

    # Complexity > 100 (line 425)
    with patch("query_builder.mcp_server.calculate_ast_complexity", return_value=150):
        res_complex = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {
                    "name": "query_builder_execute",
                    "arguments": {"spec": {"table": "items"}},
                },
            }
        )
        assert res_complex["result"]["isError"] is True
        assert (
            "exceeds maximum safe threshold"
            in res_complex["result"]["content"][0]["text"]
        )

    # Execute with AsyncBaseConnector and row truncation (lines 436, 455-456)
    class FakeAsyncExecConnector(AsyncBaseConnector):
        def __init__(self, **kwargs):
            pass

        async def connect(self):
            return self

        async def execute(self, **kwargs):
            return {"rows": [{"id": i} for i in range(100)], "columns": ["id"]}

    with patch(
        "query_builder.connectors.ConnectorRegistry.get",
        return_value=FakeAsyncExecConnector(),
    ):
        res_trunc = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {
                    "name": "query_builder_execute",
                    "arguments": {"spec": {"table": "items"}, "max_rows": 10},
                },
            }
        )
        assert res_trunc["result"]["isError"] is False
        parsed = json.loads(res_trunc["result"]["content"][0]["text"])
        assert len(parsed["rows"]) == 10
        assert parsed["truncated"] is True

    # Execute with object having to_dict or fallback attributes (lines 443, 447)
    class ResultObjToDict:
        def to_dict(self):
            return {"rows": [{"id": 1}], "columns": ["id"]}

    class ResultObjFallback:
        def __init__(self):
            self.columns = ["a"]
            self.rows = [{"a": 1}]
            self.count = 1

    mock_conn = MagicMock()
    mock_conn.execute.return_value = ResultObjToDict()
    with patch(
        "query_builder.connectors.ConnectorRegistry.get", return_value=mock_conn
    ):
        assert (
            server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 13,
                    "method": "tools/call",
                    "params": {
                        "name": "query_builder_execute",
                        "arguments": {"spec": {"table": "items"}},
                    },
                }
            )["result"]["isError"]
            is False
        )

    mock_conn.execute.return_value = ResultObjFallback()
    with patch(
        "query_builder.connectors.ConnectorRegistry.get", return_value=mock_conn
    ):
        assert (
            server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 14,
                    "method": "tools/call",
                    "params": {
                        "name": "query_builder_execute",
                        "arguments": {"spec": {"table": "items"}},
                    },
                }
            )["result"]["isError"]
            is False
        )

    # join_path with schema JSON string and active_tables string (lines 467, 469)
    res_join = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 15,
            "method": "tools/call",
            "params": {
                "name": "query_builder_join_path",
                "arguments": {
                    "active_tables": "users, orders",
                    "target_table": "products",
                    "schema": json.dumps(
                        {"tables": {"users": {}, "orders": {}, "products": {}}}
                    ),
                },
            },
        }
    )
    assert res_join["result"]["isError"] is False

    # join_path missing active_tables or target_table (line 472)
    res_join_err = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 16,
            "method": "tools/call",
            "params": {"name": "query_builder_join_path", "arguments": {}},
        }
    )
    assert res_join_err["result"]["isError"] is True

    # Unknown tool name (line 488)
    res_unk = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 17,
            "method": "tools/call",
            "params": {"name": "non_existent_tool", "arguments": {}},
        }
    )
    assert res_unk["result"]["isError"] is True


def test_mcp_run_stdio():
    input_data = (
        "\n"  # empty line (line 495)
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        + "\n"  # returns None (line 499)
        + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        + "\n"  # valid request
        + "not valid json\n"  # parse error (lines 502-509)
    )
    stdin = io.StringIO(input_data)
    stdout = io.StringIO()
    server = McpServer(stdin=stdin, stdout=stdout)
    server.run_stdio()

    out_lines = stdout.getvalue().strip().split("\n")
    assert len(out_lines) == 2
    resp1 = json.loads(out_lines[0])
    assert resp1["id"] == 1
    resp2 = json.loads(out_lines[1])
    assert resp2["error"]["code"] == -32700


# ==============================================================================
# 3. Models Coverage Gaps
# ==============================================================================


def test_models_to_dict_and_init_variants():
    # RollupSpec
    r = RollupSpec(columns=["a", "b"])
    assert r.to_dict() == {"grouping_type": "rollup", "columns": ["a", "b"]}

    # CubeSpec
    c = CubeSpec(columns=["x", "y"])
    assert c.to_dict() == {"grouping_type": "cube", "columns": ["x", "y"]}

    # GroupingSetsSpec
    g = GroupingSetsSpec(sets=[["a"], ["b", "c"]])
    assert g.to_dict() == {
        "grouping_type": "grouping_sets",
        "grouping_sets": [["a"], ["b", "c"]],
    }

    # PivotSpec with and without alias
    p1 = PivotSpec(aggregate="sum", column="val", values=[1, 2], alias="piv")
    assert p1.to_dict() == {
        "aggregate": "sum",
        "column": "val",
        "values": [1, 2],
        "alias": "piv",
    }

    p2 = PivotSpec(aggregate="avg", column="val", values=[3])
    assert p2.to_dict() == {"aggregate": "avg", "column": "val", "values": [3]}

    # CaseWhenBranch with dict condition and column
    cwb = CaseWhenBranch(
        condition={"field": "score", "operator": ">=", "value": 50},
        then_value="Pass",
        then_column="grade_col",
    )
    d_cwb = cwb.to_dict()
    assert d_cwb["then_value"] == "Pass"
    assert d_cwb["then_column"] == "grade_col"

    # CaseWhenSpec to_dict with branches, else_value, else_column, alias
    cws = CaseWhenSpec(
        branches=[cwb],
        else_value="Fail",
        else_column="fallback_col",
        alias="status_col",
    )
    d_cws = cws.to_dict()
    assert d_cws["else_value"] == "Fail"
    assert d_cws["else_column"] == "fallback_col"
    assert d_cws["alias"] == "status_col"

    # SetOperationSpec invalid operation raises ValueError
    with pytest.raises(ValueError, match="Invalid SetOperationSpec operation"):
        SetOperationSpec(operation="INVALID_SET_OP")

    # SetOperationSpec valid to_dict
    sos = SetOperationSpec(operation="union all", query={"table": "t2"})
    assert sos.operation == "UNION ALL"
    assert sos.to_dict()["operation"] == "UNION ALL"

    # QuerySpec with set_operations, rollup, cube, grouping_sets, pivot, grouping_type
    qs = QuerySpec(
        table="items",
        set_operations=[{"operation": "UNION", "query": {"table": "items2"}}],
        rollup=r,
        cube=c,
        grouping_sets=g,
        pivot={"aggregate": "sum", "column": "amt", "values": [10]},
        grouping_type="ROLLUP",
    )
    assert qs.grouping_type == "grouping_sets"
    d_qs = qs.to_dict()
    assert len(d_qs["set_operations"]) == 1
    assert d_qs["rollup"]["grouping_type"] == "rollup"
    assert d_qs["cube"]["grouping_type"] == "cube"
    assert d_qs["grouping_sets"] == [["a"], ["b", "c"]]
    assert d_qs["pivot"]["aggregate"] == "sum"
    assert d_qs["grouping_type"] == "grouping_sets"


# ==============================================================================
# 4. Policy Coverage Gaps
# ==============================================================================


def test_policy_table_column_row_subpolicies():
    tp = TablePolicy(allowed_tables=["t1"], restricted_tables=["t2"])
    cp = ColumnPolicy(allowed_roles=["admin"], restricted_columns=["secret"])
    rp = RowPolicy(filters=[FilterSpec("active", "=", True)])

    sp = SecurityPolicy(
        table_policy=tp,
        column_policies={"t1": cp, "t2": {"allowed_roles": ["user"]}},
        row_policies={"t1": rp, "t2": [{"field": "id", "operator": ">", "value": 0}]},
    )
    assert sp.allowed_tables == ["t1"]
    assert sp.restricted_tables == ["t2"]
    assert "t1" in sp.column_permissions
    assert "t2" in sp.column_permissions
    assert "t1" in sp.row_level_filters
    assert "t2" in sp.row_level_filters

    # Edge cases: None allowed_tables (74->76), empty restricted_tables (76->78),
    # non-policy/non-dict column_policy (85->79), non-policy/non-list row_policy (94->88)
    tp_empty = TablePolicy(allowed_tables=None, restricted_tables=[])
    sp_empty = SecurityPolicy(
        table_policy=tp_empty,
        column_policies={"t3": "not_dict_or_policy"},
        row_policies={"t3": "not_list_or_policy"},
    )
    assert sp_empty.allowed_tables is None
    assert sp_empty.restricted_tables == []


def test_policy_privacy_config_duck_typing():
    # Object with sensitive_column_patterns and tenant_column (line 156)
    class FakePrivacyConfig:
        def __init__(self):
            self.sensitive_column_patterns = ["ssn", "secret"]
            self.tenant_column = "tid"
            self.enforce_tenant_isolation = False

    spec = {"table": "items", "columns": ["id", "ssn"]}
    transformed = apply_security_policy(spec, policy=FakePrivacyConfig())
    # ssn should be redacted
    assert transformed["columns"] == [
        "id",
        {"column": "ssn", "alias": "ssn_masked", "masked": True},
    ]


def test_policy_column_access_control_dict_columns():
    # Column-level access control with dict columns and role checks (lines 395-407)
    policy = SecurityPolicy(
        column_permissions={
            "items": {"allowed_roles": ["admin"], "restricted_columns": ["ssn"]},
            "other": {
                "allowed_roles": ["admin"],
                "restricted_columns": [],
            },  # covers branch 399->388
        }
    )

    # 1. Unconfigured table covers branch 395->388
    spec_unconf = {"table": "unconfigured_table", "columns": ["col1"]}
    res_unconf = apply_security_policy(
        spec_unconf, context=TenantContext(tenant_id="t1"), policy=policy
    )
    assert res_unconf is not None

    # 2. Table with empty restricted_columns covers branch 399->388
    spec_other = {"table": "other", "columns": ["col1"]}
    res_other = apply_security_policy(
        spec_other, context=TenantContext(tenant_id="t1"), policy=policy
    )
    assert res_other is not None

    # 3. Non-str/non-dict object BEFORE restricted column covers line 407 (continue)
    ctx_user = TenantContext(tenant_id="t1", roles=["analyst"])
    spec_dict_col = {
        "table": "items",
        "columns": [12345, {"column": "ssn", "table": "items"}],
    }
    with pytest.raises(
        SecurityError,
        match="Access to restricted column 'ssn' on table 'items' requires roles",
    ):
        apply_security_policy(spec_dict_col, context=ctx_user, policy=policy)

    # 4. String columns: allowed column (covers 401-402 with no dot, 408->399), dotted restricted column (covers 401-402 with dot)
    spec_str_cols = {
        "table": "items",
        "columns": ["id", "items.ssn"],
    }
    with pytest.raises(
        SecurityError,
        match="Access to restricted column 'ssn' on table 'items' requires roles",
    ):
        apply_security_policy(spec_str_cols, context=ctx_user, policy=policy)

    # 5. String columns: only allowed columns so loop finishes (covers 399->388)
    spec_str_safe = {
        "table": "items",
        "columns": ["id", "items.name"],
    }
    res_safe = apply_security_policy(spec_str_safe, context=ctx_user, policy=policy)
    assert res_safe is not None

    # Authorized role -> success
    ctx_admin = TenantContext(tenant_id="t1", roles=["admin"])
    res = apply_security_policy(spec_dict_col, context=ctx_admin, policy=policy)
    assert res is not None


# ==============================================================================
# 5. Security AST Complexity Coverage Gaps
# ==============================================================================


def test_security_ast_complexity_gaps():
    # 1. set_operations containing dict where query is None / non-dict (line 724->720)
    spec_so_none = {
        "table": "items",
        "set_operations": [{"operation": "UNION", "query": None}],
    }
    score1 = calculate_ast_complexity(spec_so_none)
    assert score1 >= 10

    # 2. set_operations containing dict where query is a string (branch 725->719)
    spec_so_str = {
        "table": "items",
        "set_operations": [{"operation": "UNION", "query": "SELECT 1"}],
    }
    assert calculate_ast_complexity(spec_so_str) >= 10

    # 3. set_operations containing SetOperationSpec object with QuerySpec (lines 726-729)
    so_spec = SetOperationSpec(operation="UNION", query=QuerySpec(table="items2"))
    spec_so_obj = {
        "table": "items",
        "set_operations": [so_spec],
    }
    score2 = calculate_ast_complexity(spec_so_obj)
    assert score2 >= 10

    # 4. set_operations containing SetOperationSpec object with str query (branch 727->719)
    so_spec_str = SetOperationSpec(operation="UNION", query="SELECT 1")
    spec_so_obj_str = {
        "table": "items",
        "set_operations": [so_spec_str],
    }
    assert calculate_ast_complexity(spec_so_obj_str) >= 10

    # 5. grouping_type is set (line 741)
    spec_gt = {
        "table": "items",
        "grouping_type": "rollup",
    }
    score3 = calculate_ast_complexity(spec_gt)
    assert score3 >= 4


# ==============================================================================
# 6. Models CaseWhen Remaining Branches
# ==============================================================================


def test_models_casewhen_empty_and_defaults():
    # Branches 537->539, 539->541, 547->549, 549->551
    # Condition already has column and op (not field/operator), then_value and then_column are None
    cwb = CaseWhenBranch(condition={"column": "status", "op": "=", "value": 1})
    d_cwb = cwb.to_dict()
    assert d_cwb == {"condition": {"column": "status", "op": "=", "value": 1}}
    assert "then_value" not in d_cwb
    assert "then_column" not in d_cwb

    # Branches 564->exit, 577->579, 579->581, 581->583
    # CaseWhenSpec with empty branches, else_value=None, else_column=None, alias=None
    cws = CaseWhenSpec(branches=[])
    d_cws = cws.to_dict()
    assert d_cws == {"branches": []}
    assert "else_value" not in d_cws
    assert "else_column" not in d_cws
    assert "alias" not in d_cws


# ==============================================================================
# 7. FastAPI Remaining Coverage Gaps (146, 272->274, 369)
# ==============================================================================


def test_fastapi_async_factory_and_http_exception(sqlite_test_db):
    # 1. Async connector factory (line 146)
    async def async_connector_factory():
        return sqlite_test_db

    resolved = asyncio.run(_resolve_conn(async_connector_factory))
    assert resolved is sqlite_test_db

    # 2. _normalize_security dict with tenant_resolver=None (branch 272->274)
    app = FastAPI()
    router_sec_dict = create_query_builder_router(
        sqlite_test_db,
        security={"allowed_tables": ["items"]},
        tenant_resolver=None,
    )
    app.include_router(router_sec_dict)
    client = TestClient(app)
    res = client.get("/schema")
    assert res.status_code == 200

    # 3. /compile raising HTTPException re-raised (line 369)
    with patch(
        "query_builder.integrations.fastapi.apply_security_policy",
        side_effect=HTTPException(status_code=400, detail="custom HTTP error"),
    ):
        app_err = FastAPI()
        app_err.include_router(
            create_query_builder_router(sqlite_test_db, security=SecurityPolicy())
        )
        client_err = TestClient(app_err)
        res_err = client_err.post("/compile", json={"spec": {"table": "items"}})
        assert res_err.status_code == 400
        assert "custom HTTP error" in res_err.json()["detail"]

    # 4. /compile raising SecurityError (line 371)
    with patch(
        "query_builder.integrations.fastapi.apply_security_policy",
        side_effect=SecurityError("unauthorized"),
    ):
        app_sec = FastAPI()
        app_sec.include_router(
            create_query_builder_router(sqlite_test_db, security=SecurityPolicy())
        )
        client_sec = TestClient(app_sec)
        res_sec = client_sec.post("/compile", json={"spec": {"table": "items"}})
        assert res_sec.status_code == 403
        assert "unauthorized" in res_sec.json()["detail"]

    # 5. /execute raw SQL disabled (line 455)
    app_no_raw = FastAPI()
    app_no_raw.include_router(
        create_query_builder_router(
            sqlite_test_db,
            capabilities=EngineCapabilities(raw_sql=FeatureTier.DISABLED),
        )
    )
    client_no_raw = TestClient(app_no_raw)
    res_no_raw = client_no_raw.post("/execute", json={"sql": "SELECT 1"})
    assert res_no_raw.status_code == 403
    assert "Feature 'raw_sql' is disabled" in res_no_raw.json()["detail"]

    # 6. /execute raw SQL AST violation (lines 469-470)
    app_ast = FastAPI()
    app_ast.include_router(
        create_query_builder_router(
            sqlite_test_db, security=SecurityPolicy(enforce_tenant_isolation=False)
        )
    )
    client_ast = TestClient(app_ast)
    res_ast = client_ast.post("/execute", json={"sql": "DROP TABLE items"})
    assert res_ast.status_code == 403
    assert "Security violation" in res_ast.json()["detail"]


def test_security_branch_coverage_gaps():
    from query_builder.security import calculate_ast_complexity

    # line 726->720: set_operations items that do not have query attribute or dict
    score = calculate_ast_complexity(
        {
            "table": "items",
            "set_operations": ["invalid_item", 123],
        }
    )
    assert score >= 20


def test_capabilities_full_coverage():
    from query_builder.capabilities import EngineCapabilities, FeatureTier

    # 1. custom_overrides get_tier (line 63)
    caps = EngineCapabilities(custom_overrides={"special": FeatureTier.ADVANCED})
    assert caps.get_tier("special") == FeatureTier.ADVANCED
    assert caps.is_enabled("special") is True
    assert caps.is_advanced("special") is True

    # 2. from_dict parse_tier branches (lines 113, 119-121, 132)
    caps2 = EngineCapabilities.from_dict(
        {
            "projections": True,
            "filters": False,
            "sorts": "disabled",
            "joins": "off",
            "ctes": "none",
            "raw_sql": "unknown_value",
            "custom_overrides": {},
            "extra_custom": "adv",
        }
    )
    assert caps2.projections == FeatureTier.STANDARD
    assert caps2.filters == FeatureTier.DISABLED
    assert caps2.sorts == FeatureTier.DISABLED
    assert caps2.joins == FeatureTier.DISABLED
    assert caps2.ctes == FeatureTier.DISABLED
    assert caps2.raw_sql == FeatureTier.STANDARD
    assert caps2.get_tier("extra_custom") == FeatureTier.ADVANCED

    # 3. power_user (line 161)
    power = EngineCapabilities.power_user()
    assert isinstance(power, EngineCapabilities)


def test_cli_coverage_gaps(tmp_path):
    from query_builder import cli

    # 1. _run_coroutine_safely with already running loop (lines 35-36)
    async def _test_async():
        async def sample_coro():
            return 42

        return cli._run_coroutine_safely(sample_coro())

    res = asyncio.run(_test_async())
    assert res == 42

    # 2. mcp command (lines 838-842)
    with patch("query_builder.mcp_server.McpServer.run_stdio", return_value=0):
        assert cli.main(["mcp"]) == 0

    # 3. init command with mysql dialect (lines 921-923)
    target = tmp_path / "mysql_starter"
    assert cli.main(["init", str(target), "--dialect", "mysql"]) == 0
    assert (target / "main.py").exists()

    # 4. init command skipped files without --force (line 1039)
    assert cli.main(["init", str(target), "--dialect", "mysql"]) == 0

    # 5. init command exception handling (lines 1045-1050)
    with patch("os.makedirs", side_effect=OSError("permission denied")):
        assert cli.main(["init", str(tmp_path / "err_dir"), "--json"]) == 1
        assert cli.main(["init", str(tmp_path / "err_dir")]) == 1

    # 6. doctor command branches (lines 1097, 1121-1125, 1133, 1192, 1197)
    # config file
    cfg_file = tmp_path / "conn.json"
    cfg_file.write_text(json.dumps({"database": ":memory:"}))
    assert cli.main(["doctor", "--connector", "sqlite", "--config", str(cfg_file)]) == 0
    # config json string
    assert (
        cli.main(
            ["doctor", "--connector", "sqlite", "--config", '{"database": ":memory:"}']
        )
        == 0
    )
    # async connector
    mock_async_conn = MagicMock(spec=AsyncBaseConnector)

    async def _async_healthy():
        return {"status": "healthy", "latency_ms": 1, "success": True}

    mock_async_conn.test_connection = _async_healthy
    with patch(
        "query_builder.connectors.registry.ConnectorRegistry.get",
        return_value=mock_async_conn,
    ):
        assert cli.main(["doctor", "--connector", "mock_async"]) == 0

    # module with no __version__ and no sqlite_version (line 1097)
    fake_mod = type("FakeMod", (), {})()
    import importlib

    orig_import = importlib.import_module

    def custom_import(name, *args, **kwargs):
        if name == "sqlite3":
            return fake_mod
        return orig_import(name, *args, **kwargs)

    with (
        patch("importlib.import_module", side_effect=custom_import),
        patch("query_builder.connectors.registry.ConnectorRegistry.get") as mock_get,
    ):
        mock_inst = MagicMock()
        mock_inst.test_connection.return_value = {
            "status": "unhealthy",
            "success": False,
        }
        mock_get.return_value = mock_inst
        assert cli.main(["doctor"]) == 1

    # doctor exception with json (line 1197)
    with patch("platform.system", side_effect=RuntimeError("doctor failed")):
        assert cli.main(["doctor", "--json"]) == 1
        assert cli.main(["doctor"]) == 1


@pytest.mark.anyio
async def test_async_pool_coverage_gaps(sqlite_test_db):
    from query_builder.async_pool import (
        AsyncCancellationToken,
        AsyncConnectionPool,
        AsyncStreamingExecutor,
        PoolTimeoutError,
        QueryCancelledError,
        get_async_connection_pool_manager,
        reset_async_connection_pool_manager,
    )

    # 1. AsyncCancellationToken branches (lines 48, 57-59, 64-69, 75->exit)
    token = AsyncCancellationToken()

    async def async_cb_error():
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            pass

    def sync_cb_error():
        raise RuntimeError("boom")

    token.register_callback(async_cb_error)
    token.register_callback(sync_cb_error)
    await token.cancel()
    # cancel again (line 48 early return)
    await token.cancel()

    # register callback when already cancelled (lines 64-69)
    token.register_callback(async_cb_error)
    token.register_callback(sync_cb_error)
    token.register_callback(
        lambda: "sync_return_value"
    )  # 66->exit: sync result not awaitable

    # throw_if_cancelled
    with pytest.raises(QueryCancelledError):
        token.throw_if_cancelled()

    # 2. AsyncConnectionPool init variants & validation (lines 100-116)
    # connector instance
    conn_inst = sqlite_test_db
    pool_inst = AsyncConnectionPool(connector=conn_inst)
    assert pool_inst.factory is not None

    # connector_name sqlite
    pool_sqlite = AsyncConnectionPool(connector_name="sqlite", database=":memory:")
    assert pool_sqlite.factory is not None

    # connector_name other
    pool_duck = AsyncConnectionPool(connector_name="duckdb", database=":memory:")
    assert pool_duck.factory is not None

    # no factory/connector/name raises ValueError
    with pytest.raises(ValueError, match="AsyncConnectionPool requires"):
        AsyncConnectionPool()

    # 3. Connection lifecycle, health check, recycling (lines 142->exit, 146-147, 151, 155->157, 158-172, 178, 194, 211->216, 236->239, 240-241)
    class BrokenConn:
        def execute(self, sql):
            raise RuntimeError("broken")

        def close(self):
            raise RuntimeError("close error")

    broken_pool = AsyncConnectionPool(factory=BrokenConn, health_check_sql="SELECT 1")
    # check_health exception handling (lines 171-172)
    assert await broken_pool._check_health(BrokenConn()) is False
    # _close_connection exception handling (lines 146-147)
    await broken_pool._close_connection(BrokenConn())
    # _close_connection without close attribute (line 142->exit)
    await broken_pool._close_connection(object())

    # health check with empty health_check_sql (line 151)
    no_check_pool = AsyncConnectionPool(
        factory=lambda: sqlite3.connect(":memory:"), health_check_sql=""
    )
    assert await no_check_pool._check_health(sqlite3.connect(":memory:")) is True

    # health check with async cursor (lines 158-170)
    class AsyncCursorConn:
        async def cursor(self):
            class Cur:
                async def execute(self, sql):
                    return True

                async def close(self):
                    return True

            return Cur()

    assert (
        await AsyncConnectionPool(factory=AsyncCursorConn)._check_health(
            AsyncCursorConn()
        )
        is True
    )

    # health check with sync cursor, no close (lines 160->162, 163->165, 165->169)
    class SyncCursorNoCloseConn:
        def cursor(self):
            class Cur:
                def execute(self, sql):
                    return True

            return Cur()

    assert (
        await AsyncConnectionPool(factory=SyncCursorNoCloseConn)._check_health(
            SyncCursorNoCloseConn()
        )
        is True
    )

    # health check with sync cursor, sync close (line 167->169)
    class SyncCursorSyncCloseConn:
        def cursor(self):
            class Cur:
                def execute(self, sql):
                    return True

                def close(self):
                    return None

            return Cur()

    assert (
        await AsyncConnectionPool(factory=SyncCursorSyncCloseConn)._check_health(
            SyncCursorSyncCloseConn()
        )
        is True
    )

    # health check with object having neither execute nor cursor (line 170)
    class BareConn:
        pass

    assert await AsyncConnectionPool(factory=BareConn)._check_health(BareConn()) is True

    # Pre-warming / initialize when already initialized (line 178)
    pool = AsyncConnectionPool(
        factory=lambda: sqlite3.connect(":memory:"), min_size=1, max_size=2
    )
    await pool.initialize()
    await pool.initialize()  # idempotent early return

    # acquire with cancelled token inside loop (line 194)
    cancel_tok = AsyncCancellationToken()
    asyncio.get_event_loop().call_soon(lambda: asyncio.create_task(cancel_tok.cancel()))
    # fill pool
    c1 = await pool.acquire()
    c2 = await pool.acquire()
    # now pool is full, next acquire waits and observes cancel
    with pytest.raises(QueryCancelledError):
        await pool.acquire(token=cancel_tok)
    await pool.release(c1)
    await pool.release(c2)

    # timeout waiting for connection (line 227)
    timeout_pool = AsyncConnectionPool(
        factory=lambda: sqlite3.connect(":memory:"), max_size=1, timeout=0.05
    )
    _hold = await timeout_pool.acquire()
    with pytest.raises(PoolTimeoutError):
        await timeout_pool.acquire()
    await timeout_pool.release(_hold)

    # recycling stale / expired connection (lines 208, 215-217)
    c_reuse = await pool.acquire()
    await pool.release(c_reuse)
    # fake last_time to exceed max_idle_seconds
    conn_tuple = pool._available.pop()
    pool._available.append((conn_tuple[0], 0.0, 0.0))
    reacquired = await pool.acquire()
    await pool.release(reacquired)

    # unhealthy connection that is NOT idle and NOT expired (line 211->216)
    class ToggleHealthyConn:
        def __init__(self):
            self.healthy = True

        def execute(self, sql):
            if not self.healthy:
                raise RuntimeError("unhealthy")
            return 1

        def close(self):
            pass

    toggle_conn = ToggleHealthyConn()
    unhealthy_pool = AsyncConnectionPool(
        factory=lambda: toggle_conn,
        health_check_sql="SELECT 1",
        max_size=2,
    )
    conn_u = await unhealthy_pool.acquire()
    await unhealthy_pool.release(conn_u)
    # connection is now available and fresh (not idle, not expired). Make it unhealthy:
    toggle_conn.healthy = False
    conn_u2 = (
        await unhealthy_pool.acquire()
    )  # fails health check, closes it, creates new one
    assert conn_u2 is not None
    await unhealthy_pool.close()

    # release when pool is closed (lines 240-241)
    close_test_pool = AsyncConnectionPool(
        factory=lambda: sqlite3.connect(":memory:"), max_size=2
    )
    conn_to_release = await close_test_pool.acquire()
    await close_test_pool.close()
    await close_test_pool.release(conn_to_release)

    # context manager (lines 247-250)
    async with pool.connection() as conn:
        assert conn is not None

    await pool.close()

    # 4. AsyncConnectionPoolManager & reset (lines 300->304, 326->328, 331-337)
    mgr = get_async_connection_pool_manager()
    mgr_same = get_async_connection_pool_manager()  # line 326->328
    assert mgr_same is mgr
    p_created = await mgr.get_or_create(
        "test_pool", factory=lambda: sqlite3.connect(":memory:")
    )
    p_existing = await mgr.get_or_create(
        "test_pool", factory=lambda: sqlite3.connect(":memory:")
    )  # line 300->304
    assert p_existing is p_created
    assert mgr.get_pool("test_pool") is p_created
    await reset_async_connection_pool_manager()

    # 5. AsyncStreamingExecutor (lines 346, 355-358, 368-371)
    executor = AsyncStreamingExecutor()
    conn_exec = sqlite_test_db
    stream_res = await executor.execute_stream(conn_exec, {"table": "items"})
    assert stream_res is not None
    chunks = list(
        await executor.export_stream(conn_exec, {"table": "items"}, format="csv")
    )
    assert len(chunks) > 0


def test_compiler_coverage_gaps():
    from query_builder.capabilities import (
        DisabledFeatureError,
        EngineCapabilities,
        FeatureTier,
    )
    from query_builder.compiler import (
        CompilationError,
        QueryCompiler,
        ValidationError,
        validate_query_spec,
    )
    from query_builder.semantic import (
        MetricDefinition,
        SemanticModel,
        get_global_semantic_registry,
        reset_global_semantic_registry,
    )

    # 1. validate_query_spec case_when validations (lines 298, 301, 308)
    with pytest.raises(ValidationError, match="must be a dictionary or CaseWhenSpec"):
        validate_query_spec({"table": "items", "columns": [{"case_when": "invalid"}]})

    with pytest.raises(
        ValidationError, match="must contain a non-empty list of 'branches'"
    ):
        validate_query_spec(
            {"table": "items", "columns": [{"case_when": {"branches": []}}]}
        )

    with pytest.raises(ValidationError, match="must be a dict or CaseWhenBranch"):
        validate_query_spec(
            {"table": "items", "columns": [{"case_when": {"branches": ["invalid"]}}]}
        )

    # 2. validate_query_spec set_operations & grouping validations (lines 745, 752, 759, 762->746, 768, 775, 780, 785, 789->exit, 790)
    with pytest.raises(ValidationError, match="Field 'set_operations' must be a list"):
        validate_query_spec({"table": "items", "set_operations": "invalid"})

    with pytest.raises(ValidationError, match="must be a dict or SetOperationSpec"):
        validate_query_spec({"table": "items", "set_operations": ["invalid"]})

    with pytest.raises(ValidationError, match="Invalid set operation"):
        validate_query_spec(
            {
                "table": "items",
                "set_operations": [
                    {"operation": "INVALID", "query": {"table": "items"}}
                ],
            }
        )

    with pytest.raises(ValidationError, match="must include a 'query'"):
        validate_query_spec(
            {"table": "items", "set_operations": [{"operation": "UNION"}]}
        )

    # set operation query is not dict and has no __dict__ (line 762->746)
    validate_query_spec(
        {
            "table": "items",
            "set_operations": [{"operation": "UNION", "query": 123}],
        },
        allow_unknown_keys=True,
    )

    with pytest.raises(ValidationError, match="Invalid 'grouping_type'"):
        validate_query_spec({"table": "items", "grouping_type": "invalid_grouping"})

    with pytest.raises(ValidationError, match="Field 'grouping_sets' must be a list"):
        validate_query_spec({"table": "items", "grouping_sets": 123})

    with pytest.raises(
        ValidationError, match="Field 'rollup' must be a RollupSpec or dict"
    ):
        validate_query_spec({"table": "items", "rollup": 123})

    with pytest.raises(
        ValidationError, match="Field 'cube' must be a CubeSpec or dict"
    ):
        validate_query_spec({"table": "items", "cube": 123})

    with pytest.raises(
        ValidationError, match="Field 'pivot' must be a PivotSpec or dict"
    ):
        validate_query_spec({"table": "items", "pivot": 123})

    # pivot valid dict (line 789->exit)
    validate_query_spec({"table": "items", "pivot": {"column": "cat", "values": ["a"]}})

    # 3. QueryCompiler init with capabilities dict/unsupported (lines 821-824)
    qc_dict_caps = QueryCompiler(
        {"table": "items"}, capabilities={"raw_sql": "advanced"}
    )
    assert qc_dict_caps.capabilities is not None
    qc_none_caps = QueryCompiler({"table": "items"}, capabilities="unsupported_type")
    assert qc_none_caps.capabilities is None

    # 4. QueryCompiler semantic_models variants (lines 888-903, 894->890, 898->905, 902->899, 912->919, 914->913)
    sm1 = SemanticModel(
        name="sm_items",
        table_name="items",
        dimensions=[],
        metrics=[
            MetricDefinition(
                name="metric_count", title="Count", sql_expression="COUNT(*)"
            )
        ],
    )
    qc_sm = QueryCompiler(
        {"table": "items"},
        semantic_models=[
            sm1,
            {"name": "sm_dict", "table_name": "items", "dimensions": [], "metrics": []},
            object(),  # line 894->890: not SemanticModel or dict
        ],
    )
    assert "sm_items" in qc_sm.semantic_models
    assert "sm_dict" in qc_sm.semantic_models

    qc_sm_str = QueryCompiler(
        {"table": "items"},
        semantic_models="not_list_or_dict",  # line 898->905
    )
    assert qc_sm_str.semantic_models == {}

    qc_sm_dict = QueryCompiler(
        {"table": "items"},
        semantic_models={
            "sm_k": sm1,
            "sm_k2": {"name": "sm2", "table_name": "items"},
            "sm_invalid": object(),  # line 902->899: not SemanticModel or dict
        },
    )
    assert "sm_k" in qc_sm_dict.semantic_models

    qc_spec_sm = QueryCompiler(
        {
            "table": "items",
            "semantic_models": [
                {"name": "spec_sm", "table_name": "items"},
                123,  # line 914->913: not dict in list
            ],
        }
    )
    assert "spec_sm" in qc_spec_sm.semantic_models

    qc_spec_sm_str = QueryCompiler(
        {"table": "items", "semantic_models": "not_list_or_dict"}  # line 912->919
    )
    assert "not_list_or_dict" not in qc_spec_sm_str.semantic_models

    # 5. _validate_capabilities branches (lines 936, 952, 962->960, 965-966)
    qc_no_caps = QueryCompiler({"table": "items"}, capabilities=None)
    qc_no_caps._validate_capabilities()  # returns early (line 936)

    # plain column with capabilities enabled (line 962->960)
    qc_caps_plain_col = QueryCompiler(
        {"table": "items", "columns": [{"name": "id"}]},
        capabilities=EngineCapabilities(),
    )
    assert qc_caps_plain_col is not None

    # joins require feature
    with pytest.raises(DisabledFeatureError):
        QueryCompiler(
            {
                "table": "items",
                "joins": [
                    {
                        "table": "users",
                        "on": [{"left": "items.user_id", "right": "users.id"}],
                    }
                ],
            },
            capabilities=EngineCapabilities(joins=FeatureTier.DISABLED),
        )

    # column object with expression or case_when (lines 965-966)
    col_obj = type("ColObj", (), {"expression": "col + 1", "case_when": None})()
    with pytest.raises(DisabledFeatureError):
        QueryCompiler(
            {"table": "items", "columns": [col_obj]},
            validate_spec=False,
            capabilities=EngineCapabilities(calculated_fields=FeatureTier.DISABLED),
        )

    # column object with None expression/case_when (line 965->960)
    col_obj_empty = type("ColObjEmpty", (), {"expression": None, "case_when": None})()
    qc_caps_col_obj_empty = QueryCompiler(
        {"table": "items", "columns": [col_obj_empty]},
        validate_spec=False,
        capabilities=EngineCapabilities(),
    )
    assert qc_caps_col_obj_empty is not None

    # 6. _compile_case_when branches (lines 1072, 1082, 1087, 1096, 1098, 1110, 1118-1119, 1140)
    qc = QueryCompiler({"table": "items"})
    with pytest.raises(CompilationError, match="Invalid case_when specification type"):
        qc._compile_case_when("not_a_dict_or_obj", "items")

    # branch not dict (1082), cond not dict (1087), is_null (1096), is_not_null (1098), between scalar (1110), default op = (1118-1119), else NULL (1140)
    cw_complex = {
        "branches": [
            "invalid_branch_string",
            {"condition": "invalid_cond_string"},
            {
                "condition": {"column": "status", "operator": "is_null"},
                "then_value": "unknown",
            },
            {
                "condition": {"column": "status", "operator": "is_not_null"},
                "then_value": "known",
            },
            {
                "condition": {"column": "price", "operator": "between", "value": 10},
                "then_value": "cheap",
            },
            {
                "condition": {
                    "column": "category",
                    "operator": "custom_unmapped",
                    "value": "tech",
                },
                "then_value": "gadget",
            },
        ]
    }
    sql_cw = qc._compile_case_when(cw_complex, "items")
    assert "IS NULL" in sql_cw
    assert "IS NOT NULL" in sql_cw
    assert "BETWEEN" in sql_cw
    assert "ELSE NULL END" in sql_cw

    # 7. Metric lookups and top-level metrics (lines 1474->1476, 1477-1481, 1484->1494, 1519-1525, 1527->1536, 1528->1533, 1531->1528, 1536->1514)
    reg_model = SemanticModel(
        name="sm_global",
        table_name="items",
        dimensions=[],
        metrics=[
            MetricDefinition(
                name="global_metric", title="Global", sql_expression="SUM(sales)"
            )
        ],
    )
    get_global_semantic_registry().register_model(reg_model)
    try:
        # col_item metric resolved from local semantic_models (lines 1477-1481)
        sql_local_metric, *_ = QueryCompiler(
            {
                "table": "items",
                "columns": [
                    {"name": "id"},
                    {"name": "global_metric", "metric": "global_metric"},
                ],
            },
            semantic_models={"local_sm": reg_model},
        ).compile()
        assert "SUM(sales)" in sql_local_metric

        # col_item metric resolved from global registry
        sql_metric, *_ = QueryCompiler(
            {
                "table": "items",
                "columns": [
                    {"name": "id"},
                    {"name": "global_metric", "metric": "global_metric"},
                ],
            }
        ).compile()
        assert "SUM(sales)" in sql_metric

        # col_item metric not found anywhere -> falls through to standard column processing (line 1484->1494)
        sql_not_found_metric, *_ = QueryCompiler(
            {
                "table": "items",
                "columns": [
                    {"name": "unregistered_metric", "metric": "unregistered_metric"}
                ],
            }
        ).compile()
        assert "unregistered_metric" in sql_not_found_metric

        # top_metrics with sql_expression or sql (lines 1523-1525)
        sql_top_with_sql, *_ = QueryCompiler(
            {
                "table": "items",
                "columns": [{"name": "id"}],
                "metrics": [{"name": "custom_metric", "sql": "AVG(price)"}],
            }
        ).compile()
        assert "AVG(price)" in sql_top_with_sql

        # top_metrics with non-dict non-str entry (line 1525 continue)
        sql_top_non_dict, *_ = QueryCompiler(
            {
                "table": "items",
                "columns": [{"name": "id"}],
                "metrics": [12345],
            },
            validate_spec=False,
        ).compile()
        assert sql_top_non_dict is not None

        # top_metrics with falsy name (line 1527->1536)
        sql_top_no_name, *_ = QueryCompiler(
            {
                "table": "items",
                "columns": [{"name": "id"}],
                "metrics": [{"name": ""}],
            }
        ).compile()
        # col_item metric in semantic_models loop:
        # sm without get_metric (1478->1477), sm without matching metric (1480->1477), loop finishes without break (1477->1482)
        qc_loop_sm = QueryCompiler(
            {
                "table": "items",
                "columns": [
                    {"name": "id"},
                    {"name": "other_metric", "metric": "other_metric"},
                ],
            }
        )
        qc_loop_sm.semantic_models = {
            "bad": object(),
            "no_match": SemanticModel(
                name="sm_empty", table_name="items", dimensions=[], metrics=[]
            ),
        }
        sql_loop_sm, *_ = qc_loop_sm.compile()
        assert "other_metric" in sql_loop_sm

        # top_metrics loop:
        # sm without get_metric (1529->1528), sm without matching metric (1531->1528)
        qc_top_loop = QueryCompiler(
            {
                "table": "items",
                "columns": [{"name": "id"}],
                "metrics": ["unmatched_metric"],
            }
        )
        qc_top_loop.semantic_models = {
            "bad": object(),
            "no_match": SemanticModel(
                name="sm_empty", table_name="items", dimensions=[], metrics=[]
            ),
            "match": reg_model,
        }
        sql_top_loop, *_ = qc_top_loop.compile()
        assert sql_top_loop is not None

        # top_metrics as dict without sql, resolved from global registry
        sql_top_metric, *_ = QueryCompiler(
            {
                "table": "items",
                "columns": [{"name": "id"}],
                "metrics": [{"name": "global_metric", "alias": "gm_alias"}],
            }
        ).compile()
        assert "SUM(sales)" in sql_top_metric

        # top_metrics not found in semantic models or global (line 1536->1514)
        sql_top_missing, *_ = QueryCompiler(
            {
                "table": "items",
                "columns": [{"name": "id"}],
                "metrics": [{"name": "completely_missing_metric"}],
            }
        ).compile()
        assert "completely_missing_metric" not in sql_top_missing
    finally:
        reset_global_semantic_registry()

    # 8. GROUP BY ROLLUP / CUBE / GROUPING SETS without explicit columns (lines 2089, 2095, 2097-2098, 2099, 2104, 2111-2112)
    sql_rollup, *_ = QueryCompiler(
        {
            "table": "items",
            "columns": [
                {"name": "category"},
                {"name": "status"},
                {"name": "price", "agg": "sum"},
            ],
            "grouping_type": "rollup",
        }
    ).compile()
    assert "GROUP BY ROLLUP(" in sql_rollup

    # rollup without group_by_items (line 2089->2116)
    sql_r_no_cols, *_ = QueryCompiler(
        {
            "table": "items",
            "columns": [{"name": "price", "agg": "sum"}],
            "grouping_type": "rollup",
            "rollup": {"columns": []},
        }
    ).compile()
    assert "ROLLUP" not in sql_r_no_cols

    # cube with explicit columns and fallback to group_by_items
    sql_cube_explicit, *_ = QueryCompiler(
        {
            "table": "items",
            "columns": [
                {"name": "category"},
                {"name": "status"},
                {"name": "price", "agg": "sum"},
            ],
            "grouping_type": "cube",
            "cube": CubeSpec(columns=["category"]),
        }
    ).compile()
    assert "GROUP BY CUBE(" in sql_cube_explicit

    sql_cube_fallback, *_ = QueryCompiler(
        {
            "table": "items",
            "columns": [
                {"name": "category"},
                {"name": "status"},
                {"name": "price", "agg": "sum"},
            ],
            "grouping_type": "cube",
            "cube": {"columns": None},
        }
    ).compile()
    assert "GROUP BY CUBE(" in sql_cube_fallback

    # cube without group_by_items (line 2099->2116)
    sql_c_no_cols, *_ = QueryCompiler(
        {
            "table": "items",
            "columns": [{"name": "price", "agg": "sum"}],
            "grouping_type": "cube",
            "cube": {"columns": []},
        }
    ).compile()
    assert "CUBE" not in sql_c_no_cols

    # grouping_sets with GroupingSetsSpec fallback
    sql_gs, *_ = QueryCompiler(
        {
            "table": "items",
            "columns": [
                {"name": "category"},
                {"name": "status"},
                {"name": "price", "agg": "sum"},
            ],
            "grouping_type": "grouping_sets",
            "grouping_sets": GroupingSetsSpec(sets=[]),
        }
    ).compile()
    assert "GROUP BY" in sql_gs

    # grouping_sets without group_by_items (line 2111->2116)
    sql_gs_no_cols, *_ = QueryCompiler(
        {
            "table": "items",
            "columns": [{"name": "price", "agg": "sum"}],
            "grouping_type": "grouping_sets",
            "grouping_sets": [],
        }
    ).compile()
    assert "GROUPING SETS" not in sql_gs_no_cols

    # standard grouping without group_by_items (line 2113->2116)
    sql_std_no_cols, *_ = QueryCompiler(
        {
            "table": "items",
            "columns": [{"name": "price", "agg": "sum"}],
            "grouping_type": "standard",
        }
    ).compile()
    assert "GROUP BY" not in sql_std_no_cols

    # 9. compile with invalid set op type or missing query (lines 2281, 2285)
    qc_count_err1 = QueryCompiler(
        {"table": "items", "set_operations": ["invalid"]}, validate_spec=False
    )
    with pytest.raises(CompilationError, match="Invalid set operation item type"):
        qc_count_err1.compile()

    qc_count_err2 = QueryCompiler(
        {
            "table": "items",
            "set_operations": [{"operation": "UNION"}],
        },
        validate_spec=False,
    )
    with pytest.raises(CompilationError, match="is missing 'query'"):
        qc_count_err2.compile()
