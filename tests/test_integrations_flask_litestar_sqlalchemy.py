"""
Tests for Flask, Litestar, and SQLAlchemy 2.0 integrations, plus MySQL/SQLite
explain plan parsers, schema-aware explain estimation, and Django Ninja parity.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from query_builder import (
    DisabledFeatureError,
    EngineCapabilities,
    SecurityError,
    SecurityPolicy,
    SQLAlchemyIntegration,
    SQLiteConnector,
    TenantContext,
    analyze_query_performance,
    compile_to_sqlalchemy,
    create_flask_blueprint,
    create_litestar_router,
    create_ninja_router,
    create_sqlalchemy_integration,
    estimate_plan_from_spec,
    normalize_explain_output,
    parse_mysql_plan,
    parse_sqlite_plan,
)
from query_builder.integrations.flask import _get_flask
from query_builder.integrations.litestar import _get_litestar
from query_builder.integrations.sqlalchemy import (
    _coerce_policy as sa_coerce_policy,
)
from query_builder.integrations.sqlalchemy import (
    _get_sqlalchemy,
    _normalize_tenant_context,
    _to_named_parameters,
)


@pytest.fixture
def sqlite_conn(tmp_path: Any) -> SQLiteConnector:
    db_file = tmp_path / "test_integ.db"
    raw = sqlite3.connect(str(db_file))
    raw.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT, user_id INTEGER, tenant_id TEXT)"
    )
    raw.execute(
        "CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, total REAL, tenant_id TEXT, FOREIGN KEY(user_id) REFERENCES users(id))"
    )
    raw.execute(
        "INSERT INTO users (id, name, email, user_id, tenant_id) VALUES (1, 'Alice', 'alice@example.com', 1, 't1'), (2, 'Bob', 'bob@example.com', 2, 't2')"
    )
    raw.execute(
        "INSERT INTO orders (id, user_id, total, tenant_id) VALUES (10, 1, 99.5, 't1'), (20, 2, 45.0, 't2')"
    )
    raw.commit()
    raw.close()
    return SQLiteConnector(database=str(db_file))


# ==============================================================================
# 1. Explain Plan Parsers (MySQL & SQLite) & Schema-Aware Estimation
# ==============================================================================


def test_parse_mysql_plan_variants() -> None:
    json_str = json.dumps(
        {
            "query_block": {
                "select_id": 1,
                "cost_info": {"query_cost": "14.50"},
                "table": {
                    "table_name": "users",
                    "access_type": "ref",
                    "key": "idx_users_email",
                    "rows_examined_per_scan": 3,
                    "cost_info": {"read_cost": "2.50"},
                    "attached_condition": "users.email = 'alice@example.com'",
                },
            }
        }
    )
    node = parse_mysql_plan(json_str)
    assert node.node_type == "Index Scan"
    assert node.table == "users"
    assert node.index_name == "idx_users_email"
    assert node.rows_estimated == 3

    fallback_str = parse_mysql_plan("raw text explain")
    assert fallback_str.node_type == "Seq Scan"
    assert fallback_str.filter_predicate == "raw text explain"

    single_row = parse_mysql_plan(
        [{"table": "users", "type": "ALL", "rows": 2500, "Extra": "Using where"}]
    )
    assert single_row.node_type == "Seq Scan"
    assert single_row.table == "users"

    multi_rows = parse_mysql_plan(
        [
            "not_a_dict",
            {"table": "users", "type": "ALL", "rows": 100},
            {"table": "orders", "type": "eq_ref", "key": "PRIMARY", "rows": 1},
        ]
    )
    assert multi_rows.node_type == "Nested Loop"
    assert len(multi_rows.children) == 2
    assert multi_rows.children[1].node_type == "Index Scan"

    wrapped_qb = parse_mysql_plan(
        [
            {
                "query_block": {
                    "table": {
                        "table_name": "users",
                        "access_type": "ALL",
                        "cost": "bad",
                    }
                }
            }
        ]
    )
    assert wrapped_qb.node_type == "Seq Scan"

    complex_qb = {
        "query_block": {
            "cost_info": {"query_cost": "invalid"},
            "ordering_operation": {
                "using_filesort": True,
            },
            "grouping_operation": {
                "table": {
                    "table_name": "orders",
                    "access_type": "index_merge",
                    "rows": 50,
                }
            },
            "nested_loop": [
                {"table": {"table_name": "users", "access_type": "ALL", "rows": 100}},
                {
                    "table_name": "orders",
                    "access_type": "ref",
                    "key": "idx_user",
                    "rows": 5,
                },
            ],
        }
    }
    cnode = parse_mysql_plan(complex_qb)
    assert cnode.node_type == "Sort"
    assert cnode.children[0].node_type == "Group Aggregate"

    single_nl = parse_mysql_plan(
        {
            "query_block": {
                "cost_info": {"query_cost": 55.0},
                "nested_loop": [
                    {"table": {"table_name": "users", "access_type": "const"}}
                ],
            }
        }
    )
    assert single_nl.node_type == "Index Scan"

    empty_qb = parse_mysql_plan({"query_block": {}})
    assert empty_qb.node_type == "Execution Plan"
    bad_qb = parse_mysql_plan({"query_block": "invalid"})
    assert bad_qb.node_type == "Execution Plan"


def test_parse_sqlite_plan_variants() -> None:
    rows = [
        {"detail": "SCAN TABLE users"},
        {"detail": "SEARCH orders USING INDEX idx_orders_user (user_id=?)"},
        {"detail": "USE TEMP B-TREE FOR GROUP BY"},
        {"detail": "USE TEMP B-TREE FOR ORDER BY"},
    ]
    node = parse_sqlite_plan(rows)
    assert node.node_type == "Sort"
    assert node.children[0].node_type == "Group Aggregate"
    loop = node.children[0].children[0]
    assert loop.node_type == "Nested Loop"
    assert loop.children[0].node_type == "Seq Scan"
    assert loop.children[0].table == "users"
    assert loop.children[1].node_type == "Index Scan"
    assert loop.children[1].index_name == "idx_orders_user"

    tuple_rows = [(0, 0, 0, "SEARCH users USING INTEGER PRIMARY KEY (rowid=?)")]
    pk_node = parse_sqlite_plan(tuple_rows)
    assert pk_node.node_type == "Index Scan"
    assert pk_node.index_name == "sqlite_autoindex_pk"

    dict_node = parse_sqlite_plan({"detail": "SCAN users"})
    assert dict_node.node_type == "Seq Scan"
    str_node = parse_sqlite_plan("SEARCH users USING COVERING INDEX idx_cov")
    assert str_node.node_type == "Index Scan"
    list_str_node = parse_sqlite_plan(["SCAN orders"])
    assert list_str_node.node_type == "Seq Scan"
    empty_node = parse_sqlite_plan([])
    assert empty_node.node_type == "Execution Plan"


def test_normalize_explain_output_dispatch_and_schema_aware_estimate() -> None:
    mysql_out = normalize_explain_output(
        {
            "query_block": {
                "table": {"table_name": "users", "access_type": "ALL", "rows": 2000}
            }
        },
        dialect="mysql",
    )
    assert mysql_out.node_type == "Seq Scan"
    assert any("Sequential table scan" in w for w in mysql_out.warnings)

    mysql_tab = normalize_explain_output(
        [{"table": "users", "select_type": "SIMPLE", "type": "ALL", "rows": 1500}],
        dialect="mysql",
    )
    assert mysql_tab.node_type == "Seq Scan"

    sqlite_out = normalize_explain_output(
        [{"detail": "SEARCH users USING INDEX idx_u (id=?)"}],
        dialect="sqlite_eqp",
    )
    assert sqlite_out.node_type == "Index Scan"

    schema_dict_cols = {
        "tables": {
            "users": {"columns": {"id": {"type": "INTEGER", "primary_key": True}}},
            "orders": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "primary_key": True},
                    {"name": "user_id", "type": "INTEGER"},
                ]
            },
        }
    }
    plan_pk = estimate_plan_from_spec(
        {
            "table": "users",
            "filters": [["users.id", "=", 1]],
            "joins": [
                {"table": "orders", "type": "INNER", "on": ["users.id", "orders.id"]}
            ],
        },
        schema=schema_dict_cols,
    )
    join_node = plan_pk.children[0].children[0]
    assert join_node.children[0].node_type == "Index Scan"
    assert join_node.children[0].index_name == "pk_users_id"
    assert join_node.children[1].node_type == "Index Scan"
    assert join_node.children[1].index_name == "pk_orders_id"

    plan_dict_filter = estimate_plan_from_spec(
        {"table": "users", "filters": [{"column": "id", "op": "=", "value": 1}]},
        schema=schema_dict_cols,
    )
    assert plan_dict_filter.children[0].children[0].node_type == "Index Scan"

    perf = analyze_query_performance(
        {
            "table": "users",
            "columns": ["id"],
            "filters": [{"column": "id", "op": "=", "value": 1}],
            "limit": 10,
        },
        sql="SELECT id FROM users WHERE id = 1 LIMIT 10",
        schema_snapshot=schema_dict_cols,
    )
    assert all(p["type"] != "index" for p in perf)


# ==============================================================================
# 2. SQLAlchemy 2.0 Integration Tests
# ==============================================================================


def test_sqlalchemy_integration_full(sqlite_conn: SQLiteConnector) -> None:
    import sqlalchemy as sa
    from sqlalchemy.orm import Session, sessionmaker

    db_url = f"sqlite:///{sqlite_conn.database}"
    engine = sa.create_engine(db_url)

    assert _to_named_parameters("SELECT 1", []) == ("SELECT 1", {})
    sql_named, params_named = _to_named_parameters(
        "SELECT * FROM users WHERE name = ? AND id = $2",
        ["Alice", 1],
    )
    assert sql_named == "SELECT * FROM users WHERE name = :p0 AND id = :p1"
    assert params_named == {"p0": "Alice", "p1": 1}

    assert _normalize_tenant_context(None) is None
    tctx = TenantContext(tenant_id="t1")
    assert _normalize_tenant_context(tctx) is tctx
    assert _normalize_tenant_context("t1").tenant_id == "t1"
    assert (
        _normalize_tenant_context({"tenant_id": "t1", "org": "acme"}).tenant_id == "t1"
    )
    with pytest.raises(PermissionError):
        _normalize_tenant_context(TenantContext(tenant_id=""))
    with pytest.raises(PermissionError):
        _normalize_tenant_context("   ")
    with pytest.raises(PermissionError):
        _normalize_tenant_context({"user_id": "u1"})
    with pytest.raises(PermissionError):
        _normalize_tenant_context(12345)  # type: ignore[arg-type]

    assert sa_coerce_policy(None, False) is None
    assert sa_coerce_policy(None, True).enforce_tenant_isolation is True
    pol = SecurityPolicy(allowed_tables=["users"], enforce_tenant_isolation=False)
    assert sa_coerce_policy(pol, False) is pol
    assert sa_coerce_policy(pol, True).enforce_tenant_isolation is True
    assert (
        sa_coerce_policy({"allowed_tables": ["users"]}, True).enforce_tenant_isolation
        is True
    )
    assert SQLAlchemyIntegration(object()).dialect_name == "postgres"

    integ_url = create_sqlalchemy_integration(db_url)
    assert integ_url.dialect_name == "sqlite"
    schema = integ_url.introspect_schema()
    assert "users" in schema["tables"]
    assert "orders" in schema["tables"]

    integ = SQLAlchemyIntegration(engine)
    stmt, params, raw_sql = compile_to_sqlalchemy(
        {
            "table": "users",
            "columns": ["id", "name"],
            "filters": [{"column": "name", "op": "=", "value": "Alice"}],
        },
        dialect="sqlite",
    )
    assert ":p0" in str(stmt)
    assert params["p0"] == "Alice"
    assert "SELECT" in raw_sql

    clause, bparams, csql = integ.compile({"table": "users", "columns": ["id", "name"]})
    assert "SELECT" in csql and bparams == {"p0": 50, "p1": 0}

    exec_res = integ.execute(
        {
            "table": "users",
            "columns": ["id", "name"],
            "filters": [{"column": "name", "op": "=", "value": "Alice"}],
        }
    )
    assert exec_res["count"] == 1
    assert exec_res["rows"][0]["name"] == "Alice"

    with engine.connect() as conn:
        integ_conn = SQLAlchemyIntegration(conn)
        assert integ_conn.execute({"table": "users"})["count"] == 2
        cols, rows, _ = integ_conn.execute_raw(
            "SELECT id, name FROM users WHERE id = :id", {"id": 1}
        )
        assert len(rows) == 1 and rows[0]["name"] == "Alice"
        cols2, rows2, _ = integ_conn.execute_raw(
            "SELECT id, name FROM users WHERE id = ?", [2]
        )
        assert len(rows2) == 1 and rows2[0]["name"] == "Bob"
        cols3, rows3, _ = integ_conn.execute_raw("SELECT id, name FROM users")
        assert len(rows3) == 2

    SessionLocal = sessionmaker(bind=engine)
    integ_sm = SQLAlchemyIntegration(SessionLocal)
    assert integ_sm.introspect_schema()["tables"]
    assert integ_sm.execute({"table": "users"})["count"] == 2

    with Session(engine) as session:
        integ_sess = SQLAlchemyIntegration(session)
        assert integ_sess.introspect_schema()["tables"]
        assert integ_sess.execute({"table": "users"})["count"] == 2

    meta = sa.MetaData()
    meta.reflect(bind=engine)
    integ_meta = SQLAlchemyIntegration(engine, metadata=meta)
    assert "users" in integ_meta.introspect_schema()["tables"]

    integ_sec = SQLAlchemyIntegration(
        engine,
        security={"allowed_tables": ["users"], "restricted_tables": ["orders"]},
        capabilities={
            "raw_sql": False,
            "ctes": False,
            "window_functions": False,
            "analytical_grouping": False,
            "vector_search": False,
        },
    )
    filtered_schema = integ_sec.introspect_schema()
    assert "users" in filtered_schema["tables"]
    assert "orders" not in filtered_schema["tables"]

    res_t1 = integ_sec.execute({"table": "users"}, context="t1")
    assert res_t1["count"] == 1
    assert res_t1["rows"][0]["name"] == "Alice"

    with pytest.raises(SecurityError):
        integ_sec.execute_raw("SELECT * FROM users")
    with pytest.raises(DisabledFeatureError):
        integ_sec.execute(
            {"table": "users", "ctes": [{"name": "c", "query": {"table": "users"}}]}
        )
    with pytest.raises(DisabledFeatureError):
        integ_sec.execute(
            {
                "table": "users",
                "window_functions": [{"function": "ROW_NUMBER", "alias": "rn"}],
            }
        )
    with pytest.raises(DisabledFeatureError):
        integ_sec.execute({"table": "users", "rollup": ["name"]})
    with pytest.raises(DisabledFeatureError):
        integ_sec.execute(
            {"table": "users", "vector_search": {"column": "emb", "vector": [0.1]}}
        )

    integ_tenant_raw = SQLAlchemyIntegration(
        engine,
        security={"enforce_tenant_isolation": True},
    )
    with pytest.raises(SecurityError, match="Raw SQL execution is restricted"):
        integ_tenant_raw.execute_raw("SELECT * FROM users")
    with pytest.raises(SecurityError):
        integ.execute_raw("DROP TABLE users")

    with patch("importlib.import_module", side_effect=ImportError("No sqlalchemy")):
        with pytest.raises(ImportError, match="SQLAlchemy is not installed"):
            _get_sqlalchemy()
    with patch("importlib.import_module", return_value=None):
        with pytest.raises(ImportError, match="SQLAlchemy is not installed"):
            _get_sqlalchemy()


# ==============================================================================
# 3. Flask Blueprint Integration Tests (via Lightweight Test Harness)
# ==============================================================================


class _FakeFlaskResponse:
    def __init__(
        self,
        body: Any = b"",
        status: int = 200,
        mimetype: str = "application/json",
        headers: dict[str, str] | None = None,
    ) -> None:
        if hasattr(body, "__iter__") and not isinstance(body, (bytes, str, dict, list)):
            chunks = [c.encode("utf-8") if isinstance(c, str) else c for c in body]
            self.data = b"".join(chunks)
        elif isinstance(body, str):
            self.data = body.encode("utf-8")
        elif isinstance(body, bytes):
            self.data = body
        else:
            self.data = json.dumps(body).encode("utf-8")
        self.status_code = status
        self.mimetype = mimetype
        self.headers = headers or {}

    def get_json(self) -> Any:
        return json.loads(self.data.decode("utf-8"))


class _FakeFlaskRequest:
    def __init__(self) -> None:
        self.args: dict[str, str] = {}
        self._json: Any = None
        self.data: bytes = b""

    def get_json(self, silent: bool = True) -> Any:
        _ = silent
        return self._json


class _FakeFlaskBlueprint:
    def __init__(
        self, name: str, import_name: str, url_prefix: str | None = None
    ) -> None:
        self.name = name
        self.import_name = import_name
        self.url_prefix = url_prefix
        self.routes: dict[str, Any] = {}

    def add_url_rule(
        self,
        rule: str,
        endpoint: str,
        view_func: Any,
        methods: list[str] | None = None,
    ) -> None:
        _ = endpoint, methods
        self.routes[rule] = view_func


def test_flask_blueprint_endpoints(
    sqlite_conn: SQLiteConnector, monkeypatch: pytest.MonkeyPatch
) -> None:
    with patch("importlib.import_module", side_effect=ImportError("No flask")):
        with pytest.raises(ImportError, match="Flask is not installed"):
            _get_flask()
    with patch("importlib.import_module", return_value=None):
        with pytest.raises(ImportError, match="Flask is not installed"):
            _get_flask()

    fake_req = _FakeFlaskRequest()
    fake_flask = ModuleType("flask")
    fake_flask.Blueprint = _FakeFlaskBlueprint  # type: ignore[attr-defined]
    fake_flask.Response = _FakeFlaskResponse  # type: ignore[attr-defined]
    fake_flask.request = fake_req  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "flask", fake_flask)

    bp = create_flask_blueprint(
        connector=sqlite_conn,
        url_prefix="/qb",
        ai_provider=MagicMock(),
    )

    def _call(
        path: str, json_body: Any = None, args: dict[str, str] | None = None
    ) -> _FakeFlaskResponse:
        fake_req._json = json_body
        fake_req.data = b""
        fake_req.args = args or {}
        return bp.routes[path]()

    # 1. GET /capabilities
    r = _call("/capabilities")
    assert r.status_code == 200
    assert "capabilities" in r.get_json()

    # 2. GET /schema (plus cache hit and refresh)
    r = _call("/schema")
    assert r.status_code == 200
    assert "users" in r.get_json()["tables"]
    assert _call("/schema").status_code == 200
    assert _call("/schema", args={"refresh": "1"}).status_code == 200

    # Raw bytes body fallback in _get_body
    fake_req._json = None
    fake_req.data = json.dumps({"spec": {"table": "users", "columns": ["id"]}}).encode(
        "utf-8"
    )
    assert bp.routes["/compile"]().status_code == 200

    # 3. POST /compile
    r = _call("/compile", {"spec": {"table": "users", "columns": ["id", "name"]}})
    assert r.status_code == 200
    assert "SELECT" in r.get_json()["sql"]
    assert _call("/compile", {}).status_code == 400

    # 4. POST /validate
    r = _call("/validate", {"sql": "SELECT id FROM users"})
    assert r.status_code == 200
    assert r.get_json()["valid"] is True
    assert _call("/validate", {}).status_code == 400

    # 5. POST /execute
    r = _call("/execute", {"spec": {"table": "users"}, "timeout_ms": 1000})
    assert r.status_code == 200
    assert r.get_json()["count"] == 2

    r = _call(
        "/execute", {"sql": "SELECT id, name FROM users WHERE id = ?", "params": [1]}
    )
    assert r.status_code == 200
    assert r.get_json()["count"] == 1

    assert _call("/execute", {}).status_code == 400
    assert _call("/execute", {"spec": {"columns": ["id"]}}).status_code == 400
    assert _call("/execute", {"sql": 123}).status_code == 403
    assert _call("/execute", {"sql": "DROP TABLE users"}).status_code == 403

    # 6. POST /export and /export/stream
    r = _call("/export", {"spec": {"table": "users"}, "format": "csv"})
    assert r.status_code == 200
    assert b"Alice" in r.data

    r = _call(
        "/export",
        {
            "rows": [{"id": 1, "name": "Alice"}],
            "columns": ["id", "name"],
            "format": "json",
        },
    )
    assert r.status_code == 200

    r = _call("/export", {"sql": "SELECT id, name FROM users", "format": "csv"})
    assert r.status_code == 200

    r = _call(
        "/export",
        {
            "rows": [{"id": 1, "name": "Alice"}],
            "columns": ["id", "name"],
            "format": "csv",
            "stream": True,
        },
    )
    assert r.status_code == 200

    r = _call("/export/stream", {"spec": {"table": "users"}, "format": "csv"})
    assert r.status_code == 200
    r = _call("/export/stream", {"sql": "SELECT id, name FROM users", "format": "csv"})
    assert r.status_code == 200

    assert _call("/export", {}).status_code == 400
    assert _call("/export/stream", {}).status_code == 400
    assert _call("/export", {"sql": "DROP TABLE users"}).status_code == 403
    assert _call("/export/stream", {"sql": "DROP TABLE users"}).status_code == 403

    # 7. POST /explain
    r = _call(
        "/explain",
        {
            "spec": {
                "table": "users",
                "filters": [{"column": "id", "op": "=", "value": 1}],
            },
            "schema_snapshot": sqlite_conn.introspect_schema(),
        },
    )
    assert r.status_code == 200
    assert r.get_json()["plan"]["node_type"] == "Limit"
    assert _call("/explain", {}).status_code == 400

    # 8. POST /join-path
    r = _call("/join-path", {"active_tables": ["users"], "target_table": "orders"})
    assert r.status_code == 200
    assert r.get_json()["connected"] is True
    assert _call("/join-path", {}).status_code == 400

    # 9. POST /nlq, /nlq/explain, GET /nlq/providers
    r = _call("/nlq/providers")
    assert r.status_code == 200
    assert "providers" in r.get_json()

    assert _call("/nlq", {"prompt": ""}).status_code == 400
    assert _call("/nlq/explain", {}).status_code == 400
    assert _call("/nlq/explain", {"spec": {"table": "users"}}).status_code == 200

    with patch("query_builder.ai.client.ask_ai") as mock_ask:
        mock_ask.return_value = SimpleNamespace(
            spec={"table": "users", "columns": ["id", "name"]},
            explanation="Selects users",
            confidence=0.95,
            warnings=[],
        )
        r = _call("/nlq", {"prompt": "show all users"})
        assert r.status_code == 200
        assert "SELECT" in r.get_json()["sql"]

    # Custom nlq_service & security / capabilities path
    mock_nlq_svc = MagicMock()
    mock_nlq_svc.translate.return_value = SimpleNamespace(
        spec={"table": "users", "columns": ["id"]},
        explanation="Translated",
        confidence=0.9,
        warnings=[],
    )
    mock_nlq_svc.explain.return_value = SimpleNamespace(
        explanation="Explains query",
        provider="mock",
        complexity="low",
        to_dict=lambda: {
            "explanation": "Explains query",
            "provider": "mock",
            "complexity": "low",
        },
    )
    bp2 = create_flask_blueprint(
        sqlite_conn,
        nlq_service=mock_nlq_svc,
        security={"allowed_tables": ["users"], "enforce_tenant_isolation": True},
        tenant_resolver=lambda _req: "t1",
        capabilities={
            "raw_sql": False,
            "ctes": False,
            "window_functions": False,
            "analytical_grouping": False,
            "vector_search": False,
        },
        max_rows=1,
        statement_timeout_ms=500,
    )

    def _call2(path: str, json_body: Any = None) -> _FakeFlaskResponse:
        fake_req._json = json_body
        fake_req.data = b""
        fake_req.args = {}
        return bp2.routes[path]()

    assert _call2("/nlq", {"prompt": "users"}).status_code == 200
    assert _call2("/nlq/explain", {"spec": {"table": "users"}}).status_code == 200
    assert _call2("/execute", {"spec": {"table": "users"}}).status_code == 200
    assert _call2("/execute", {"sql": "SELECT 1"}).status_code == 403
    assert _call2("/export", {"sql": "SELECT 1"}).status_code == 403
    assert _call2("/export/stream", {"sql": "SELECT 1"}).status_code == 403
    assert _call2("/execute", {"spec": {"table": "orders"}}).status_code == 403
    assert (
        _call2(
            "/execute",
            {
                "spec": {
                    "table": "users",
                    "ctes": [{"name": "c", "query": {"table": "users"}}],
                }
            },
        ).status_code
        == 403
    )
    assert (
        _call2(
            "/execute",
            {
                "spec": {
                    "table": "users",
                    "window_functions": [{"function": "ROW_NUMBER", "alias": "rn"}],
                }
            },
        ).status_code
        == 403
    )
    assert (
        _call2("/execute", {"spec": {"table": "users", "rollup": ["name"]}}).status_code
        == 403
    )
    assert (
        _call2(
            "/execute",
            {
                "spec": {
                    "table": "users",
                    "vector_search": {"column": "emb", "vector": [0.1]},
                }
            },
        ).status_code
        == 403
    )


# ==============================================================================
# 4. Litestar Router Integration Tests (via Lightweight Test Harness)
# ==============================================================================


class _FakeLitestarResponse:
    def __init__(
        self,
        content: Any = b"",
        status_code: int = 200,
        media_type: str = "application/json",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.content = content
        self.status_code = status_code
        self.media_type = media_type
        self.headers = headers or {}

    def json(self) -> Any:
        if isinstance(self.content, (dict, list)):
            return self.content
        if isinstance(self.content, bytes):
            return json.loads(self.content.decode("utf-8"))
        return json.loads(str(self.content))


class _FakeLitestarStream:
    def __init__(
        self,
        iterator: Any,
        media_type: str = "text/csv",
        headers: dict[str, str] | None = None,
    ) -> None:
        chunks = [c.encode("utf-8") if isinstance(c, str) else c for c in iterator]
        self.content = b"".join(chunks)
        self.status_code = 200
        self.media_type = media_type
        self.headers = headers or {}


class _FakeLitestarRouter:
    def __init__(
        self, path: str, route_handlers: list[Any], tags: list[str] | None = None
    ) -> None:
        self.path = path
        self.route_handlers = route_handlers
        self.tags = tags
        self.routes: dict[str, Any] = {}
        for h in route_handlers:
            for p in getattr(h, "_paths", []):
                self.routes[p] = h


def _fake_route_decorator(path: list[str] | str) -> Any:
    paths = [path] if isinstance(path, str) else list(path)

    def _wrap(fn: Any) -> Any:
        fn._paths = paths
        return fn

    return _wrap


def test_litestar_router_endpoints(
    sqlite_conn: SQLiteConnector, monkeypatch: pytest.MonkeyPatch
) -> None:
    with patch("importlib.import_module", side_effect=ImportError("No litestar")):
        with pytest.raises(ImportError, match="Litestar is not installed"):
            _get_litestar()
    with patch("importlib.import_module", return_value=None):
        with pytest.raises(ImportError, match="Litestar is not installed"):
            _get_litestar()

    fake_ls = ModuleType("litestar")
    fake_ls.Router = _FakeLitestarRouter  # type: ignore[attr-defined]
    fake_ls.Response = _FakeLitestarResponse  # type: ignore[attr-defined]
    fake_ls.Stream = _FakeLitestarStream  # type: ignore[attr-defined]
    fake_ls.get = _fake_route_decorator  # type: ignore[attr-defined]
    fake_ls.post = _fake_route_decorator  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litestar", fake_ls)

    router = create_litestar_router(connector=sqlite_conn, path="/qb")

    def _run(coro: Any) -> Any:
        return asyncio.run(coro)

    assert _run(router.routes["/capabilities"]()).status_code == 200
    r = _run(router.routes["/schema"](refresh=False))
    assert r.status_code == 200
    assert "users" in r.json()["tables"]
    assert _run(router.routes["/schema"](refresh=False)).status_code == 200
    assert _run(router.routes["/schema"](refresh=True)).status_code == 200

    r = _run(
        router.routes["/compile"](data={"spec": {"table": "users", "columns": ["id"]}})
    )
    assert r.status_code == 200
    assert "SELECT" in r.json()["sql"]
    assert _run(router.routes["/compile"](data={})).status_code == 400

    r = _run(router.routes["/validate"](data={"sql": "SELECT id FROM users"}))
    assert r.status_code == 200
    assert r.json()["valid"] is True
    assert _run(router.routes["/validate"](data={})).status_code == 400

    r = _run(
        router.routes["/execute"](data={"spec": {"table": "users"}, "timeout_ms": 1000})
    )
    assert r.status_code == 200
    assert r.json()["count"] == 2

    r = _run(
        router.routes["/execute"](
            data={"sql": "SELECT id FROM users WHERE id = ?", "params": [1]}
        )
    )
    assert r.status_code == 200
    assert r.json()["count"] == 1

    assert _run(router.routes["/execute"](data={})).status_code == 400
    assert (
        _run(router.routes["/execute"](data={"spec": {"columns": ["id"]}})).status_code
        == 400
    )
    assert _run(router.routes["/execute"](data={"sql": 123})).status_code == 403
    assert (
        _run(router.routes["/execute"](data={"sql": "DROP TABLE users"})).status_code
        == 403
    )

    r = _run(
        router.routes["/export"](data={"spec": {"table": "users"}, "format": "csv"})
    )
    assert r.status_code == 200
    assert b"Alice" in r.content

    r = _run(
        router.routes["/export"](
            data={
                "rows": [{"id": 1, "name": "Alice"}],
                "columns": ["id", "name"],
                "format": "json",
            }
        )
    )
    assert r.status_code == 200

    r = _run(
        router.routes["/export"](
            data={"sql": "SELECT id, name FROM users", "format": "csv"}
        )
    )
    assert r.status_code == 200

    r = _run(
        router.routes["/export"](
            data={
                "rows": [{"id": 1, "name": "Alice"}],
                "columns": ["id", "name"],
                "format": "csv",
                "stream": True,
            }
        )
    )
    assert r.status_code == 200

    r = _run(
        router.routes["/export/stream"](
            data={
                "rows": [{"id": 1, "name": "Alice"}],
                "columns": ["id", "name"],
                "format": "csv",
            }
        )
    )
    assert r.status_code == 200
    assert b"Alice" in r.content

    r = _run(
        router.routes["/export/stream"](
            data={"spec": {"table": "users"}, "format": "csv"}
        )
    )
    assert r.status_code == 200
    r = _run(
        router.routes["/export/stream"](
            data={"sql": "SELECT id, name FROM users", "format": "csv"}
        )
    )
    assert r.status_code == 200

    assert _run(router.routes["/export"](data={})).status_code == 400
    assert _run(router.routes["/export/stream"](data={})).status_code == 400
    assert (
        _run(router.routes["/export"](data={"sql": "DROP TABLE users"})).status_code
        == 403
    )
    assert (
        _run(
            router.routes["/export/stream"](data={"sql": "DROP TABLE users"})
        ).status_code
        == 403
    )

    r = _run(
        router.routes["/explain"](
            data={
                "spec": {
                    "table": "users",
                    "filters": [{"column": "id", "op": "=", "value": 1}],
                },
                "schema_snapshot": sqlite_conn.introspect_schema(),
            }
        )
    )
    assert r.status_code == 200
    assert "plan" in r.json()
    assert _run(router.routes["/explain"](data={})).status_code == 400

    r = _run(
        router.routes["/join-path"](
            data={"active_tables": ["users"], "target_table": "orders"}
        )
    )
    assert r.status_code == 200
    assert r.json()["connected"] is True
    assert _run(router.routes["/join-path"](data={})).status_code == 400

    r = _run(router.routes["/nlq/providers"]())
    assert r.status_code == 200
    assert _run(router.routes["/nlq"](data={"prompt": ""})).status_code == 400
    assert _run(router.routes["/nlq/explain"](data={})).status_code == 400
    assert (
        _run(
            router.routes["/nlq/explain"](data={"spec": {"table": "users"}})
        ).status_code
        == 200
    )

    with patch("query_builder.ai.client.ask_ai") as mock_ask:
        mock_ask.return_value = SimpleNamespace(
            spec={"table": "users", "columns": ["id"]},
            explanation="Selects users",
            confidence=0.9,
            warnings=[],
        )
        r = _run(router.routes["/nlq"](data={"prompt": "list users"}))
        assert r.status_code == 200
        assert "SELECT" in r.json()["sql"]

    mock_nlq_svc = MagicMock()
    mock_nlq_svc.translate.return_value = SimpleNamespace(
        spec={"table": "users", "columns": ["id"]},
        explanation="Translated",
        confidence=0.9,
        warnings=[],
    )
    mock_nlq_svc.explain.return_value = SimpleNamespace(
        explanation="Explains query",
        provider="mock",
        complexity="low",
        to_dict=lambda: {
            "explanation": "Explains query",
            "provider": "mock",
            "complexity": "low",
        },
    )
    router2 = create_litestar_router(
        sqlite_conn,
        path="/qb2",
        nlq_service=mock_nlq_svc,
        security={"allowed_tables": ["users"], "enforce_tenant_isolation": True},
        tenant_resolver=lambda _req: "t1",
        capabilities={
            "raw_sql": False,
            "ctes": False,
            "window_functions": False,
            "analytical_grouping": False,
            "vector_search": False,
        },
        max_rows=1,
        statement_timeout_ms=500,
    )
    assert _run(router2.routes["/nlq"](data={"prompt": "users"})).status_code == 200
    assert (
        _run(
            router2.routes["/nlq/explain"](data={"spec": {"table": "users"}})
        ).status_code
        == 200
    )
    assert (
        _run(router2.routes["/execute"](data={"spec": {"table": "users"}})).status_code
        == 200
    )
    assert _run(router2.routes["/execute"](data={"sql": "SELECT 1"})).status_code == 403
    assert _run(router2.routes["/export"](data={"sql": "SELECT 1"})).status_code == 403
    assert (
        _run(router2.routes["/export/stream"](data={"sql": "SELECT 1"})).status_code
        == 403
    )
    assert (
        _run(router2.routes["/execute"](data={"spec": {"table": "orders"}})).status_code
        == 403
    )
    assert (
        _run(
            router2.routes["/execute"](
                data={
                    "spec": {
                        "table": "users",
                        "ctes": [{"name": "c", "query": {"table": "users"}}],
                    }
                }
            )
        ).status_code
        == 403
    )
    assert (
        _run(
            router2.routes["/execute"](
                data={
                    "spec": {
                        "table": "users",
                        "window_functions": [{"function": "ROW_NUMBER", "alias": "rn"}],
                    }
                }
            )
        ).status_code
        == 403
    )
    assert (
        _run(
            router2.routes["/execute"](
                data={"spec": {"table": "users", "rollup": ["name"]}}
            )
        ).status_code
        == 403
    )
    assert (
        _run(
            router2.routes["/execute"](
                data={
                    "spec": {
                        "table": "users",
                        "vector_search": {"column": "emb", "vector": [0.1]},
                    }
                }
            )
        ).status_code
        == 403
    )


# ==============================================================================
# 5. Django Ninja Router Parity Tests (/explain, /join-path, /nlq)
# ==============================================================================


def test_django_ninja_explain_join_path_nlq(sqlite_conn: SQLiteConnector) -> None:
    from ninja.errors import HttpError

    # Non-PK join with schema in estimate_plan_from_spec
    plan_non_pk_join = estimate_plan_from_spec(
        {
            "table": "users",
            "joins": [
                {
                    "table": "orders",
                    "type": "LEFT",
                    "on": ["users.name", "orders.total"],
                }
            ],
        },
        schema={"tables": {"orders": {"columns": {"id": {"primary_key": True}}}}},
    )
    assert plan_non_pk_join.children[0].children[0].children[1].node_type == "Seq Scan"

    router = create_ninja_router(
        connector=sqlite_conn,
        security=SecurityPolicy(enforce_tenant_isolation=True),
        tenant_resolver=lambda _req: "t1",
    )
    endpoints = {}
    for path_str, path_view in router.path_operations.items():
        for op in path_view.operations:
            endpoints[path_str] = op.view_func

    assert "/explain" in endpoints
    assert "/join-path" in endpoints
    assert "/nlq" in endpoints

    req = MagicMock()
    explain_res = endpoints["/explain"](
        req,
        {
            "spec": {
                "table": "users",
                "filters": [{"column": "id", "op": "=", "value": 1}],
            },
            "schema": sqlite_conn.introspect_schema(),
        },
    )
    assert "plan" in explain_res and "performance" in explain_res

    with pytest.raises(HttpError):
        endpoints["/explain"](req, {})

    jp_res = endpoints["/join-path"](
        req, {"active_tables": ["users"], "target_table": "orders"}
    )
    assert jp_res["connected"] is True
    jp_res_schema = endpoints["/join-path"](
        req,
        {
            "active_tables": ["users"],
            "target_table": "orders",
            "schema": sqlite_conn.introspect_schema(),
        },
    )
    assert jp_res_schema["connected"] is True

    with pytest.raises(HttpError):
        endpoints["/join-path"](req, {})

    with pytest.raises(HttpError):
        endpoints["/nlq"](req, {"prompt": "   "})

    with patch("query_builder.ai.client.ask_ai") as mock_ask:
        mock_ask.return_value = SimpleNamespace(
            spec={"table": "users", "columns": ["id", "name"]},
            explanation="Selects users",
            confidence=0.95,
            warnings=[],
        )
        nlq_res = endpoints["/nlq"](req, {"prompt": "get all users"})
        assert "SELECT" in nlq_res["sql"]
        assert nlq_res["confidence"] == 0.95
        nlq_res_schema = endpoints["/nlq"](
            req,
            {"prompt": "get all users", "schema": sqlite_conn.introspect_schema()},
        )
        assert "SELECT" in nlq_res_schema["sql"]

    with patch(
        "query_builder.integrations.django.QueryCompiler",
        side_effect=PermissionError("no"),
    ):
        with pytest.raises(HttpError):
            endpoints["/explain"](req, {"spec": {"table": "users"}})
        with patch("query_builder.ai.client.ask_ai") as mock_ask:
            mock_ask.return_value = SimpleNamespace(
                spec={"table": "users", "columns": ["id"]},
                explanation="ok",
                confidence=0.9,
                warnings=[],
            )
            with pytest.raises(HttpError):
                endpoints["/nlq"](req, {"prompt": "users"})

    with patch(
        "query_builder.integrations.django.QueryCompiler",
        side_effect=SecurityError("sec"),
    ):
        with pytest.raises(HttpError):
            endpoints["/explain"](req, {"spec": {"table": "users"}})
        with patch("query_builder.ai.client.ask_ai") as mock_ask:
            mock_ask.return_value = SimpleNamespace(
                spec={"table": "users", "columns": ["id"]},
                explanation="ok",
                confidence=0.9,
                warnings=[],
            )
            with pytest.raises(HttpError):
                endpoints["/nlq"](req, {"prompt": "users"})


def test_error_branches_and_edge_cases(
    sqlite_conn: SQLiteConnector, monkeypatch: pytest.MonkeyPatch
) -> None:
    from query_builder.advisor import recommend_indexes
    from query_builder.explain import _extract_table_primary_keys

    # Explain edge cases
    assert _extract_table_primary_keys({"tables": "bad"}, "users") == []
    assert _extract_table_primary_keys({"tables": {"users": "bad"}}, "users") == []
    assert (
        _extract_table_primary_keys(
            {"tables": {"users": {"columns": {"email": {"primary_key": False}}}}},
            "users",
        )
        == []
    )
    assert (
        _extract_table_primary_keys({"tables": {"users": {"columns": "bad"}}}, "users")
        == []
    )
    assert estimate_plan_from_spec(12345).node_type == "Limit"  # type: ignore[arg-type]
    assert parse_mysql_plan("123").node_type == "Seq Scan"
    assert (
        parse_mysql_plan({"query_block": {"nested_loop": ["bad"]}}).node_type
        == "Execution Plan"
    )
    assert parse_sqlite_plan({}).node_type == "Execution Plan"
    assert parse_sqlite_plan(123).node_type == "Execution Plan"  # type: ignore[arg-type]
    assert (
        parse_sqlite_plan(
            [{}, 123, "OTHER OP", "SCAN TABLE", "SEARCH t USING INDEX"]
        ).node_type
        == "Nested Loop"
    )
    assert (
        estimate_plan_from_spec(
            {
                "table": "users",
                "joins": [{"table": "orders", "right_col": "orders.id"}],
            },
            schema={"tables": {"orders": {"columns": {"id": {"primary_key": True}}}}},
        ).node_type
        == "Limit"
    )

    # Advisor edge cases
    class _ObjWithToDict:
        def __init__(self, d: dict[str, Any]) -> None:
            self._d = d

        def to_dict(self) -> dict[str, Any]:
            return self._d

    recs = recommend_indexes(
        {
            "table": "users",
            "alias": "u",
            "joins": [
                {"table": ""},
                {"table": "orders", "alias": "o", "on": ["u.id", "o.user_id"]},
            ],
            "filters": [
                ("u.email", "=", "a@b.c"),
                _ObjWithToDict({"column": "u.name", "op": "="}),
                None,
            ],
            "order_by": ["u.created_at DESC"],
        },
        schema_snapshot={
            "tables": {
                "users": {
                    "columns": {
                        "id": {"primary_key": True},
                        "email": {"primary_key": False},
                    }
                },
                "orders": {"columns": "invalid"},
            }
        },
    )
    assert any(r["index_name"] == "idx_orders_user_id" for r in recs)
    assert any("comp" in r["index_name"] for r in recs)

    recs_obj_order = recommend_indexes(
        {
            "table": "users",
            "filters": [_ObjWithToDict({"column": "email", "op": "="})],
            "order_by": [_ObjWithToDict({"column": "name"})],
        },
        schema_snapshot={"tables": "invalid"},
    )
    assert len(recs_obj_order) >= 2

    recs_bad_order = recommend_indexes(
        {
            "table": "users",
            "filters": ["not_a_tuple"],
            "order_by": [12345],
        }
    )
    assert recs_bad_order == []

    # SQLAlchemy AST safety failure in compile_to_sqlalchemy
    with patch(
        "query_builder.integrations.sqlalchemy.validate_sql_ast",
        return_value={"valid": False, "is_read_only": False, "violations": ["bad"]},
    ):
        with pytest.raises(SecurityError, match="Security violation"):
            compile_to_sqlalchemy({"table": "users"})

    # Flask error branches (PermissionError, DisabledFeatureError, SecurityError, generic Exception)
    fake_req = _FakeFlaskRequest()
    fake_flask = ModuleType("flask")
    fake_flask.Blueprint = _FakeFlaskBlueprint  # type: ignore[attr-defined]
    fake_flask.Response = _FakeFlaskResponse  # type: ignore[attr-defined]
    fake_flask.request = fake_req  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "flask", fake_flask)

    bp_err = create_flask_blueprint(
        sqlite_conn,
        security=SecurityPolicy(enforce_tenant_isolation=True),
        capabilities=EngineCapabilities.default(),
        tenant_resolver=lambda _req: (_ for _ in ()).throw(PermissionError("no auth")),
    )

    def _call_err(path: str, body: Any) -> _FakeFlaskResponse:
        fake_req._json = body
        return bp_err.routes[path]()

    assert _call_err("/compile", {"spec": {"table": "users"}}).status_code == 401
    assert _call_err("/execute", {"spec": {"table": "users"}}).status_code == 401
    assert _call_err("/export", {"spec": {"table": "users"}}).status_code == 401
    assert _call_err("/export/stream", {"spec": {"table": "users"}}).status_code == 401
    assert _call_err("/explain", {"spec": {"table": "users"}}).status_code == 401
    assert _call_err("/nlq", {"prompt": "hi"}).status_code == 401

    bp_norm = create_flask_blueprint(sqlite_conn)

    def _call_norm(path: str, body: Any = None) -> _FakeFlaskResponse:
        fake_req._json = body
        return bp_norm.routes[path]()

    with patch(
        "query_builder.integrations.flask._exec_conn_method",
        side_effect=RuntimeError("db fail"),
    ):
        assert _call_norm("/schema").status_code == 500
        assert _call_norm("/execute", {"spec": {"table": "users"}}).status_code == 400
    with patch(
        "query_builder.integrations.flask.validate_sql_ast",
        return_value={"valid": False, "is_read_only": False},
    ):
        assert _call_norm("/compile", {"spec": {"table": "users"}}).status_code == 403
    with patch(
        "query_builder.integrations.flask.QueryCompiler",
        side_effect=DisabledFeatureError("ctes"),
    ):
        assert _call_norm("/compile", {"spec": {"table": "users"}}).status_code == 403
    with patch(
        "query_builder.integrations.flask.QueryCompiler",
        side_effect=SecurityError("sec"),
    ):
        assert _call_norm("/compile", {"spec": {"table": "users"}}).status_code == 403
        assert _call_norm("/explain", {"spec": {"table": "users"}}).status_code == 403
        assert _call_norm("/nlq", {"prompt": "users"}).status_code == 403
    with patch(
        "query_builder.integrations.flask.QueryCompiler",
        side_effect=RuntimeError("comp"),
    ):
        assert _call_norm("/compile", {"spec": {"table": "users"}}).status_code == 400
        assert _call_norm("/explain", {"spec": {"table": "users"}}).status_code == 400
        assert _call_norm("/nlq", {"prompt": "users"}).status_code == 400
    with patch(
        "query_builder.integrations.flask.validate_sql_ast",
        side_effect=RuntimeError("val"),
    ):
        assert _call_norm("/validate", {"sql": "SELECT 1"}).status_code == 400
    with patch(
        "query_builder.integrations.flask.find_join_path",
        side_effect=RuntimeError("jp"),
    ):
        assert (
            _call_norm(
                "/join-path", {"active_tables": ["a"], "target_table": "b"}
            ).status_code
            == 400
        )
    with patch("query_builder.nlq.NlqService.explain", side_effect=RuntimeError("exp")):
        assert (
            _call_norm("/nlq/explain", {"spec": {"table": "users"}}).status_code == 400
        )

    # Policy/tenant/max_rows/schema branches on Flask
    bp_tenant = create_flask_blueprint(
        sqlite_conn,
        security=SecurityPolicy(enforce_tenant_isolation=True),
        tenant_resolver=lambda _req: "t1",
        schema_cache_ttl=0.0,
    )
    fake_req._json = {"spec": {"table": "users", "limit": 1}}
    assert bp_tenant.routes["/compile"]().status_code == 200
    assert bp_tenant.routes["/export"]().status_code == 200
    assert bp_tenant.routes["/explain"]().status_code == 200
    fake_req._json = {"sql": "SELECT 1"}
    assert bp_tenant.routes["/execute"]().status_code == 403
    assert bp_tenant.routes["/export"]().status_code == 403

    bp_max = create_flask_blueprint(sqlite_conn, max_rows=1, schema_cache_ttl=0.0)
    fake_req._json = None
    fake_req.data = b""
    assert bp_max.routes["/schema"]().status_code == 200
    assert bp_max.routes["/compile"]().status_code == 400
    fake_req._json = {"sql": "SELECT id, name FROM users"}
    assert bp_max.routes["/execute"]().get_json()["count"] == 1
    fake_req._json = {
        "active_tables": ["users"],
        "target_table": "orders",
        "schema": sqlite_conn.introspect_schema(),
    }
    assert bp_max.routes["/join-path"]().status_code == 200
    with patch("query_builder.ai.client.ask_ai") as mock_ask:
        mock_ask.return_value = SimpleNamespace(
            spec={"table": "users", "columns": ["id"]},
            explanation="ok",
            confidence=0.9,
            warnings=[],
        )
        fake_req._json = {
            "prompt": "users",
            "schema": sqlite_conn.introspect_schema(),
        }
        assert bp_max.routes["/nlq"]().status_code == 200

    # Litestar error branches
    fake_ls = ModuleType("litestar")
    fake_ls.Router = _FakeLitestarRouter  # type: ignore[attr-defined]
    fake_ls.Response = _FakeLitestarResponse  # type: ignore[attr-defined]
    fake_ls.Stream = _FakeLitestarStream  # type: ignore[attr-defined]
    fake_ls.get = _fake_route_decorator  # type: ignore[attr-defined]
    fake_ls.post = _fake_route_decorator  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litestar", fake_ls)

    ls_err = create_litestar_router(
        sqlite_conn,
        security=SecurityPolicy(enforce_tenant_isolation=True),
        capabilities=EngineCapabilities.default(),
        tenant_resolver=lambda _req: (_ for _ in ()).throw(PermissionError("no auth")),
    )

    def _run(coro: Any) -> Any:
        return asyncio.run(coro)

    assert (
        _run(ls_err.routes["/compile"](data={"spec": {"table": "users"}})).status_code
        == 401
    )
    assert (
        _run(ls_err.routes["/execute"](data={"spec": {"table": "users"}})).status_code
        == 401
    )
    assert (
        _run(ls_err.routes["/export"](data={"spec": {"table": "users"}})).status_code
        == 401
    )
    assert (
        _run(
            ls_err.routes["/export/stream"](data={"spec": {"table": "users"}})
        ).status_code
        == 401
    )
    assert (
        _run(ls_err.routes["/explain"](data={"spec": {"table": "users"}})).status_code
        == 401
    )
    assert _run(ls_err.routes["/nlq"](data={"prompt": "hi"})).status_code == 401

    ls_norm = create_litestar_router(sqlite_conn)
    with patch(
        "query_builder.integrations.litestar._exec_conn_method",
        side_effect=RuntimeError("db fail"),
    ):
        assert _run(ls_norm.routes["/schema"](refresh=True)).status_code == 500
        assert (
            _run(
                ls_norm.routes["/execute"](data={"spec": {"table": "users"}})
            ).status_code
            == 400
        )
    with patch(
        "query_builder.integrations.litestar.validate_sql_ast",
        return_value={"valid": False, "is_read_only": False},
    ):
        assert (
            _run(
                ls_norm.routes["/compile"](data={"spec": {"table": "users"}})
            ).status_code
            == 403
        )
    with patch(
        "query_builder.integrations.litestar.QueryCompiler",
        side_effect=DisabledFeatureError("ctes"),
    ):
        assert (
            _run(
                ls_norm.routes["/compile"](data={"spec": {"table": "users"}})
            ).status_code
            == 403
        )
    with patch(
        "query_builder.integrations.litestar.QueryCompiler",
        side_effect=SecurityError("sec"),
    ):
        assert (
            _run(
                ls_norm.routes["/compile"](data={"spec": {"table": "users"}})
            ).status_code
            == 403
        )
        assert (
            _run(
                ls_norm.routes["/explain"](data={"spec": {"table": "users"}})
            ).status_code
            == 403
        )
        assert _run(ls_norm.routes["/nlq"](data={"prompt": "users"})).status_code == 403
    with patch(
        "query_builder.integrations.litestar.QueryCompiler",
        side_effect=RuntimeError("comp"),
    ):
        assert (
            _run(
                ls_norm.routes["/compile"](data={"spec": {"table": "users"}})
            ).status_code
            == 400
        )
        assert (
            _run(
                ls_norm.routes["/explain"](data={"spec": {"table": "users"}})
            ).status_code
            == 400
        )
        assert _run(ls_norm.routes["/nlq"](data={"prompt": "users"})).status_code == 400
    with patch(
        "query_builder.integrations.litestar.validate_sql_ast",
        side_effect=RuntimeError("val"),
    ):
        assert (
            _run(ls_norm.routes["/validate"](data={"sql": "SELECT 1"})).status_code
            == 400
        )
    with patch(
        "query_builder.integrations.litestar.find_join_path",
        side_effect=RuntimeError("jp"),
    ):
        assert (
            _run(
                ls_norm.routes["/join-path"](
                    data={"active_tables": ["a"], "target_table": "b"}
                )
            ).status_code
            == 400
        )
    with patch("query_builder.nlq.NlqService.explain", side_effect=RuntimeError("exp")):
        assert (
            _run(
                ls_norm.routes["/nlq/explain"](data={"spec": {"table": "users"}})
            ).status_code
            == 400
        )

    ls_tenant = create_litestar_router(
        sqlite_conn,
        security=SecurityPolicy(enforce_tenant_isolation=True),
        tenant_resolver=lambda _req: "t1",
        schema_cache_ttl=0.0,
    )
    assert (
        _run(
            ls_tenant.routes["/compile"](data={"spec": {"table": "users", "limit": 1}})
        ).status_code
        == 200
    )
    assert (
        _run(
            ls_tenant.routes["/export"](data={"spec": {"table": "users", "limit": 1}})
        ).status_code
        == 200
    )
    assert (
        _run(
            ls_tenant.routes["/explain"](data={"spec": {"table": "users", "limit": 1}})
        ).status_code
        == 200
    )
    assert (
        _run(ls_tenant.routes["/execute"](data={"sql": "SELECT 1"})).status_code == 403
    )
    assert (
        _run(ls_tenant.routes["/export"](data={"sql": "SELECT 1"})).status_code == 403
    )

    ls_max = create_litestar_router(sqlite_conn, max_rows=1, schema_cache_ttl=0.0)
    assert (
        _run(
            ls_max.routes["/schema"](
                request=SimpleNamespace(query_params={"refresh": "1"}), refresh=False
            )
        ).status_code
        == 200
    )
    assert (
        _run(
            ls_max.routes["/execute"](data={"sql": "SELECT id, name FROM users"})
        ).json()["count"]
        == 1
    )
    assert (
        _run(
            ls_max.routes["/join-path"](
                data={
                    "active_tables": ["users"],
                    "target_table": "orders",
                    "schema": sqlite_conn.introspect_schema(),
                }
            )
        ).status_code
        == 200
    )
    with patch("query_builder.ai.client.ask_ai") as mock_ask:
        mock_ask.return_value = SimpleNamespace(
            spec={"table": "users", "columns": ["id"]},
            explanation="ok",
            confidence=0.9,
            warnings=[],
        )
        assert (
            _run(
                ls_max.routes["/nlq"](
                    data={"prompt": "users", "schema": sqlite_conn.introspect_schema()}
                )
            ).status_code
            == 200
        )


def test_mysql_explain_advanced_operations_and_driver_wrappers() -> None:
    # 1. duplicates_removal, buffer_result, materialized_from_subquery, and union_result
    dup_plan = parse_mysql_plan(
        {
            "query_block": {
                "duplicates_removal": {
                    "buffer_result": {
                        "table": {
                            "table_name": "users",
                            "access_type": "ALL",
                            "rows_examined_per_scan": 1500,
                            "materialized_from_subquery": {
                                "query_block": {
                                    "table": {
                                        "table_name": "raw_users",
                                        "access_type": "index",
                                        "key": "idx_raw",
                                        "rows": 200,
                                    }
                                }
                            },
                        }
                    }
                }
            }
        }
    )
    assert dup_plan.node_type == "Unique"
    assert dup_plan.children[0].node_type == "Buffer Result"
    scan_child = dup_plan.children[0].children[0]
    assert scan_child.node_type == "Seq Scan"
    assert scan_child.table == "users"
    assert scan_child.children[0].table == "raw_users"
    assert scan_child.children[0].node_type == "Index Scan"

    union_plan = parse_mysql_plan(
        {
            "query_block": {
                "union_result": {
                    "table_name": "<union1,2>",
                    "query_specifications": [
                        {
                            "query_block": {
                                "table": {
                                    "table_name": "u1",
                                    "access_type": "ALL",
                                    "rows": 100,
                                }
                            }
                        },
                        {
                            "query_block": {
                                "table": {
                                    "table_name": "u2",
                                    "access_type": "ref",
                                    "key": "idx_u2",
                                    "rows": 20,
                                }
                            }
                        },
                    ],
                }
            }
        }
    )
    assert union_plan.node_type == "Union"
    assert len(union_plan.children) == 2

    # 2. Sibling table + grouping_operation + ordering_operation
    sibling_plan = parse_mysql_plan(
        {
            "query_block": {
                "table": {
                    "table_name": "orders",
                    "access_type": "ALL",
                    "rows": 2000,
                },
                "grouping_operation": {"using_temporary_table": True},
                "ordering_operation": {"using_filesort": True},
            }
        }
    )
    assert sibling_plan.node_type == "Sort"
    assert sibling_plan.children[0].node_type == "Group Aggregate"
    assert sibling_plan.children[0].children[0].table == "orders"

    # 3. Driver wrapper dicts in normalize_explain_output
    pg_wrapped = normalize_explain_output(
        [
            {
                "QUERY PLAN": json.dumps(
                    [
                        {
                            "Plan": {
                                "Node Type": "Index Scan",
                                "Relation Name": "users",
                                "Total Cost": 12.5,
                                "Plan Rows": 5,
                            }
                        }
                    ]
                )
            }
        ],
        dialect="postgres",
    )
    assert pg_wrapped.node_type == "Index Scan"
    assert pg_wrapped.table == "users"

    mysql_wrapped = normalize_explain_output(
        [
            {
                "EXPLAIN": json.dumps(
                    {
                        "query_block": {
                            "table": {
                                "table_name": "orders",
                                "access_type": "ALL",
                                "rows": 500,
                            }
                        }
                    }
                )
            }
        ],
        dialect="mysql",
    )
    assert mysql_wrapped.node_type == "Seq Scan"
    assert mysql_wrapped.table == "orders"

    sqlite_tuples = normalize_explain_output(
        [(0, 0, 0, "SEARCH users USING INDEX idx_users_email (email=?)")],
        dialect="sqlite",
    )
    assert sqlite_tuples.node_type == "Index Scan"
    assert sqlite_tuples.index_name == "idx_users_email"


def test_composite_pk_and_cross_table_composite_index_advisor(
    sqlite_conn: SQLiteConnector, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib

    from ninja.errors import HttpError

    import query_builder
    from query_builder.advisor import recommend_indexes
    from query_builder.integrations.sqlalchemy import _to_named_parameters

    importlib.reload(query_builder)

    # SQLAlchemy _to_named_parameters preserves single-quoted literals and double-quoted identifiers
    named_sql, bind_params = _to_named_parameters(
        "SELECT \"col?name\" FROM users WHERE note = 'What? $1 %s' AND id = ? AND status = $2",
        [42, "active"],
    )
    assert "'What? $1 %s'" in named_sql
    assert '"col?name"' in named_sql
    assert "id = :p0" in named_sql
    assert "status = :p1" in named_sql
    assert bind_params == {"p0": 42, "p1": "active"}

    composite_schema = {
        "tables": {
            "order_items": {
                "primary_keys": ["order_id", "item_id"],
                "columns": [
                    {"name": "order_id", "is_primary": True},
                    {"name": "item_id", "is_primary": True},
                    {"name": "quantity", "is_primary": False},
                ],
            },
            "orders": {
                "columns": {
                    "order_uuid": {"is_primary": True},
                    "id": {"is_primary": False},
                }
            },
            "customers": {
                "columns": [
                    {"name": "cust_id", "is_primary": True},
                    {"name": "region", "is_primary": False},
                    {"name": "created_at", "is_primary": False},
                ]
            },
        }
    }

    # Non-leading composite PK column filtered alone -> Seq Scan & index recommended
    plan_non_leading = estimate_plan_from_spec(
        {
            "table": "order_items",
            "filters": [{"column": "item_id", "op": "=", "value": 5}],
        },
        schema=composite_schema,
    )
    assert plan_non_leading.children[0].children[0].node_type == "Seq Scan"
    recs_non_leading = recommend_indexes(
        {
            "table": "order_items",
            "filters": [{"column": "item_id", "op": "=", "value": 5}],
        },
        schema_snapshot=composite_schema,
    )
    assert any(r["index_name"] == "idx_order_items_item_id" for r in recs_non_leading)

    # Leading + second composite PK columns filtered together -> Index Scan & no index recommended
    plan_both = estimate_plan_from_spec(
        {
            "table": "order_items",
            "filters": [
                {"column": "order_id", "op": "=", "value": 10},
                {"column": "item_id", "op": "=", "value": 5},
            ],
        },
        schema=composite_schema,
    )
    assert plan_both.children[0].children[0].node_type == "Index Scan"
    assert (
        plan_both.children[0].children[0].index_name
        == "pk_order_items_order_id_item_id"
    )
    recs_both = recommend_indexes(
        {
            "table": "order_items",
            "filters": [
                {"column": "order_id", "op": "=", "value": 10},
                {"column": "item_id", "op": "=", "value": 5},
            ],
        },
        schema_snapshot=composite_schema,
    )
    assert recs_both == []

    # Explicit non-PK 'id' column when table has PK 'order_uuid' -> recommends idx_orders_id
    recs_non_pk_id = recommend_indexes(
        {"table": "orders", "filters": [{"column": "id", "op": "=", "value": 99}]},
        schema_snapshot=composite_schema,
    )
    assert any(r["index_name"] == "idx_orders_id" for r in recs_non_pk_id)

    # Cross-table filter (c.region) + sort (orders.id) -> does NOT emit invalid single-table composite index
    recs_cross = recommend_indexes(
        {
            "table": "orders",
            "joins": [
                {
                    "table": "customers",
                    "alias": "c",
                    "left_col": "cust_id",
                    "right_col": "c.cust_id",
                }
            ],
            "filters": [{"column": "c.region", "op": "=", "value": "US"}],
            "order_by": [{"column": "orders.id", "direction": "DESC"}],
        },
        schema_snapshot=composite_schema,
    )
    assert not any(len(r["columns"]) == 2 for r in recs_cross)

    # Same-table aliased filter (c.region) + sort (c.created_at) -> emits composite index on customers
    recs_same_alias = recommend_indexes(
        {
            "table": "orders",
            "joins": [
                {
                    "table": "customers",
                    "alias": "c",
                    "left_col": "cust_id",
                    "right_col": "c.cust_id",
                }
            ],
            "filters": [{"column": "c.region", "op": "=", "value": "US"}],
            "order_by": [{"column": "c.created_at", "direction": "DESC"}],
        },
        schema_snapshot=composite_schema,
    )
    comp_rec = next(r for r in recs_same_alias if len(r["columns"]) == 2)
    assert comp_rec["table"] == "customers"
    assert comp_rec["index_name"] == "idx_customers_comp_region_created_at"

    # Flask malformed JSON body & export capability / max_rows enforcement
    fake_req = _FakeFlaskRequest()
    fake_flask = ModuleType("flask")
    fake_flask.Blueprint = _FakeFlaskBlueprint  # type: ignore[attr-defined]
    fake_flask.Response = _FakeFlaskResponse  # type: ignore[attr-defined]
    fake_flask.request = fake_req  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "flask", fake_flask)
    bp = create_flask_blueprint(
        sqlite_conn,
        max_rows=1,
        capabilities={
            "ctes": False,
            "window_functions": False,
            "analytical_grouping": False,
            "vector_search": False,
        },
    )
    fake_req._json = None
    fake_req.data = b"{bad json"
    assert bp.routes["/compile"]().status_code == 400

    for disabled_spec in (
        {"table": "users", "ctes": [{"name": "c", "query": {"table": "users"}}]},
        {
            "table": "users",
            "window_functions": [{"function": "ROW_NUMBER", "alias": "rn"}],
        },
        {"table": "users", "rollup": ["name"]},
        {"table": "users", "vector_search": {"column": "v", "vector": [0.1]}},
    ):
        fake_req._json = {"spec": disabled_spec}
        fake_req.data = b""
        assert bp.routes["/export"]().status_code == 403
        assert bp.routes["/export/stream"]().status_code == 403
    fake_req._json = {
        "spec": {"table": "users", "ctes": [{"name": "c", "query": {"table": "users"}}]}
    }
    assert bp.routes["/explain"]().status_code == 403

    fake_req._json = {"rows": [{"id": 1}, {"id": 2}, {"id": 3}], "columns": ["id"]}
    assert bp.routes["/export"]().status_code == 200
    fake_req._json = {"spec": {"table": "users", "columns": ["id"]}}
    assert bp.routes["/export"]().status_code == 200
    fake_req._json = {"sql": "SELECT id FROM users"}
    assert bp.routes["/export"]().status_code == 200

    # Litestar export capability / max_rows enforcement
    fake_ls = ModuleType("litestar")
    fake_ls.Router = _FakeLitestarRouter  # type: ignore[attr-defined]
    fake_ls.Response = _FakeLitestarResponse  # type: ignore[attr-defined]
    fake_ls.Stream = _FakeLitestarStream  # type: ignore[attr-defined]
    fake_ls.get = _fake_route_decorator  # type: ignore[attr-defined]
    fake_ls.post = _fake_route_decorator  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litestar", fake_ls)
    ls_router = create_litestar_router(
        sqlite_conn,
        max_rows=1,
        capabilities={
            "ctes": False,
            "window_functions": False,
            "analytical_grouping": False,
            "vector_search": False,
        },
    )

    def _run(coro: Any) -> Any:
        return asyncio.run(coro)

    for disabled_spec in (
        {"table": "users", "ctes": [{"name": "c", "query": {"table": "users"}}]},
        {
            "table": "users",
            "window_functions": [{"function": "ROW_NUMBER", "alias": "rn"}],
        },
        {"table": "users", "rollup": ["name"]},
        {"table": "users", "vector_search": {"column": "v", "vector": [0.1]}},
    ):
        assert (
            _run(ls_router.routes["/export"](data={"spec": disabled_spec})).status_code
            == 403
        )
        assert (
            _run(
                ls_router.routes["/export/stream"](data={"spec": disabled_spec})
            ).status_code
            == 403
        )
    assert (
        _run(
            ls_router.routes["/explain"](
                data={
                    "spec": {
                        "table": "users",
                        "ctes": [{"name": "c", "query": {"table": "users"}}],
                    }
                }
            )
        ).status_code
        == 403
    )

    assert (
        _run(
            ls_router.routes["/export"](
                data={"rows": [{"id": 1}, {"id": 2}], "columns": ["id"]}
            )
        ).status_code
        == 200
    )
    assert (
        _run(
            ls_router.routes["/export"](
                data={"spec": {"table": "users", "columns": ["id"]}}
            )
        ).status_code
        == 200
    )
    assert (
        _run(
            ls_router.routes["/export"](data={"sql": "SELECT id FROM users"})
        ).status_code
        == 200
    )

    # Django Ninja DisabledFeatureError on /explain and /nlq
    ninja_router = create_ninja_router(
        connector=sqlite_conn,
        security={"restricted_tables": ["secret"], "enforce_tenant_isolation": False},
        capabilities={"ctes": False},
    )
    ninja_eps = {}
    for path_str, path_view in ninja_router.path_operations.items():
        for op in path_view.operations:
            ninja_eps[path_str] = op.view_func

    for ep_path in ("/compile", "/execute", "/export", "/explain"):
        with pytest.raises(HttpError) as exc_sec:
            ninja_eps[ep_path](SimpleNamespace(), {"spec": {"table": "secret"}})
        assert exc_sec.value.status_code == 403
        with pytest.raises(HttpError) as exc_cap:
            ninja_eps[ep_path](
                SimpleNamespace(),
                {
                    "spec": {
                        "table": "users",
                        "ctes": [{"name": "c", "query": {"table": "users"}}],
                    }
                },
            )
        assert exc_cap.value.status_code == 403

    ninja_perm_router = create_ninja_router(
        connector=sqlite_conn,
        tenant_resolver=lambda _req: (_ for _ in ()).throw(PermissionError("denied")),
    )
    ninja_perm_eps = {}
    for path_str, path_view in ninja_perm_router.path_operations.items():
        for op in path_view.operations:
            ninja_perm_eps[path_str] = op.view_func
    for ep_path in ("/compile", "/execute", "/export"):
        with pytest.raises(HttpError) as exc_perm:
            ninja_perm_eps[ep_path](SimpleNamespace(), {"spec": {"table": "users"}})
        assert exc_perm.value.status_code == 401

    with patch("query_builder.ai.client.ask_ai") as mock_ask:
        mock_ask.return_value = SimpleNamespace(
            spec={
                "table": "users",
                "ctes": [{"name": "c", "query": {"table": "users"}}],
            },
            explanation="ok",
            confidence=0.9,
            warnings=[],
        )
        fake_req._json = {"prompt": "cte query"}
        assert bp.routes["/nlq"]().status_code == 403
        assert (
            _run(ls_router.routes["/nlq"](data={"prompt": "cte query"})).status_code
            == 403
        )
        with pytest.raises(HttpError) as exc_nlq:
            ninja_eps["/nlq"](SimpleNamespace(), {"prompt": "cte query"})
        assert exc_nlq.value.status_code == 403

    # Additional explain.py & advisor.py edge branches
    from query_builder.explain import (
        _extract_table_primary_keys,
        _match_pk_prefix,
        _resolve_mysql_op_child,
    )

    assert _resolve_mysql_op_child({}, None).node_type == "Execution Plan"
    assert _match_pk_prefix(["a", "b"], {"a"}) == "a"
    assert _extract_table_primary_keys(
        {
            "tables": {
                "t": {
                    "primary_keys": ["", "id", "id"],
                    "columns": {"id": {"is_primary": True}},
                }
            }
        },
        "t",
    ) == ["id"]

    plan_filter_edges = estimate_plan_from_spec(
        {
            "table": "users",
            "filters": [
                ["other.id", "=", 1],
                ["", "=", 1],
                {"column": "users.id", "op": "=", "value": 1},
                {"column": "other.id", "op": "=", "value": 1},
                {"column": "id", "table": "other", "op": "=", "value": 1},
            ],
            "joins": [{"table": "orders", "on": "invalid", "right_col": "id"}],
        },
        schema={
            "tables": {
                "users": {"primary_keys": ["id"]},
                "orders": {"primary_keys": ["id"]},
            }
        },
    )
    assert plan_filter_edges.node_type == "Limit"

    assert (
        normalize_explain_output(
            {"QUERY PLAN": {"Plan": {"Node Type": "Seq Scan"}}}, dialect="postgres"
        ).node_type
        == "Seq Scan"
    )
    assert (
        normalize_explain_output(
            {"EXPLAIN": "not valid json"}, dialect="postgres"
        ).node_type
        == "Execution Plan"
    )
    assert (
        normalize_explain_output(
            [{"detail": "SEARCH users USING INDEX idx_u (id=?)"}], dialect="sqlite"
        ).node_type
        == "Index Scan"
    )

    recs_edge = recommend_indexes(
        {
            "table": "t",
            "filters": [{"column": "c1", "op": "=", "value": 1}],
            "order_by": [{"column": "c2"}],
        },
        schema_snapshot={
            "tables": {
                "bad": "not_a_dict",
                "t": {
                    "primary_keys": ["", "pk1", "pk1"],
                    "columns": {
                        "pk1": {"is_primary": True},
                        "id": {"is_primary": False},
                        "other": {"is_primary": False},
                    },
                },
                "t2": {
                    "columns": [
                        {"name": "pk2", "is_primary": True},
                        {"name": "pk2", "is_primary": True},
                        {"name": "id", "is_primary": False},
                        {"name": "other", "is_primary": False},
                    ]
                },
            }
        },
    )
    assert len(recs_edge) == 2

    # Django URLs, DRF viewset, and Ninja router edge branches
    from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied

    from query_builder.integrations.django import (
        _is_tenant_isolation_active,
        _require_spec_capabilities,
        create_django_urls,
        create_drf_views,
    )

    assert _is_tenant_isolation_active(None, TenantContext(tenant_id="t1"), {}) is True
    assert _is_tenant_isolation_active(None, None, "not_a_dict") is False
    _require_spec_capabilities("not_a_dict", EngineCapabilities.default())

    dj_urls = create_django_urls(
        sqlite_conn,
        security={"restricted_tables": ["secret"], "enforce_tenant_isolation": False},
        capabilities={"ctes": False, "raw_sql": False},
    )
    dj_map = {p.name: p.callback for p in dj_urls}

    def _dj_post(cb: Any, body_dict: dict[str, Any]) -> Any:
        req = SimpleNamespace(
            method="POST",
            body=json.dumps(body_dict).encode("utf-8"),
            GET={},
            META={},
        )
        return cb(req)

    assert (
        _dj_post(
            dj_map["query-builder-compile"], {"spec": {"table": "secret"}}
        ).status_code
        == 403
    )
    assert (
        _dj_post(dj_map["query-builder-export"], {"sql": "SELECT 1"}).status_code == 403
    )
    assert (
        _dj_post(
            dj_map["query-builder-export"], {"spec": {"table": "secret"}}
        ).status_code
        == 403
    )
    assert (
        _dj_post(
            dj_map["query-builder-explain"],
            {
                "spec": {
                    "table": "users",
                    "ctes": [{"name": "c", "query": {"table": "users"}}],
                }
            },
        ).status_code
        == 403
    )
    with patch("query_builder.ai.client.ask_ai") as mock_ask:
        mock_ask.return_value = SimpleNamespace(
            spec={"table": "secret"},
            explanation="ok",
            confidence=0.9,
            warnings=[],
        )
        assert (
            _dj_post(dj_map["query-builder-nlq"], {"prompt": "secret"}).status_code
            == 403
        )
        mock_ask.return_value = SimpleNamespace(
            spec={
                "table": "users",
                "ctes": [{"name": "c", "query": {"table": "users"}}],
            },
            explanation="ok",
            confidence=0.9,
            warnings=[],
        )
        assert (
            _dj_post(dj_map["query-builder-nlq"], {"prompt": "cte"}).status_code == 403
        )

    drf_views = create_drf_views(
        sqlite_conn,
        security={"restricted_tables": ["secret"], "enforce_tenant_isolation": False},
        capabilities={"ctes": False},
    )
    assert (
        drf_views["ExportStreamView"]()
        .post(SimpleNamespace(data={"spec": {"table": "users", "columns": ["id"]}}))
        .status_code
        == 200
    )
    with pytest.raises(DRFPermissionDenied):
        drf_views["ExplainView"]().post(
            SimpleNamespace(
                data={
                    "spec": {
                        "table": "users",
                        "ctes": [{"name": "c", "query": {"table": "users"}}],
                    }
                }
            )
        )
    with pytest.raises(DRFPermissionDenied):
        drf_views["ExplainView"]().post(
            SimpleNamespace(data={"spec": {"table": "secret"}})
        )
    jp_resp = drf_views["JoinPathView"]().post(
        SimpleNamespace(data={"active_tables": ["users"], "target_table": "orders"})
    )
    assert jp_resp.data["connected"] is True

    with patch("query_builder.ai.client.ask_ai") as mock_ask:
        mock_ask.return_value = SimpleNamespace(
            spec={"table": "secret"},
            explanation="ok",
            confidence=0.9,
            warnings=[],
        )
        with pytest.raises(DRFPermissionDenied):
            drf_views["NlqView"]().post(SimpleNamespace(data={"prompt": "secret"}))
        mock_ask.return_value = SimpleNamespace(
            spec={
                "table": "users",
                "ctes": [{"name": "c", "query": {"table": "users"}}],
            },
            explanation="ok",
            confidence=0.9,
            warnings=[],
        )
        with pytest.raises(DRFPermissionDenied):
            drf_views["NlqView"]().post(SimpleNamespace(data={"prompt": "cte"}))


def test_explain_advisor_django_fastapi_join_solver_branch_coverage(
    sqlite_conn: SQLiteConnector,
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from query_builder.advisor import recommend_indexes
    from query_builder.explain import _extract_table_primary_keys, _match_pk_prefix
    from query_builder.integrations.django import (
        _is_tenant_isolation_active,
        _require_spec_capabilities,
        create_django_urls,
        create_drf_views,
    )
    from query_builder.integrations.fastapi import create_query_builder_router
    from query_builder.join_solver import find_best_join_condition, find_join_path
    from query_builder.mcp_server import McpServer

    # 1. explain.py branch coverage
    assert (
        parse_mysql_plan({"query_block": {"grouping_operation": {}}})
        .children[0]
        .node_type
        == "Execution Plan"
    )
    assert _extract_table_primary_keys(
        {
            "tables": {
                "t": {
                    "primary_keys": ["id", "id", ""],
                    "columns": {"id": {"is_primary": True}, "b": {"is_primary": True}},
                }
            }
        },
        "t",
    ) == ["id", "b"]
    assert _match_pk_prefix(["a", "b", "c"], {"a", "c"}) == "a"

    plan_branches = estimate_plan_from_spec(
        {
            "table": "order_items",
            "filters": [
                ("other.col", "=", 1),
                ("", "=", 1),
                {"column": "order_items.order_id", "op": "=", "value": 1},
                {"column": "other.order_id", "op": "=", "value": 1},
                {"column": "order_id", "table": "other", "op": "=", "value": 1},
            ],
            "joins": [
                {
                    "table": "orders",
                    "on": "not_a_list",
                    "right_col": "id",
                }
            ],
        },
        schema={
            "tables": {
                "order_items": {"primary_keys": ["order_id"]},
                "orders": {"primary_keys": ["id"]},
            }
        },
    )
    assert plan_branches.node_type == "Limit"

    assert (
        normalize_explain_output(
            {"QUERY PLAN": {"Plan": {"Node Type": "Seq Scan"}}}, dialect="postgres"
        ).node_type
        == "Seq Scan"
    )
    assert (
        normalize_explain_output(
            {"EXPLAIN": {"query_block": {"table": {"table_name": "u"}}}},
            dialect="mysql",
        ).table
        == "u"
    )
    assert (
        normalize_explain_output("not valid json", dialect="postgres").node_type
        == "Execution Plan"
    )

    # 2. advisor.py branch coverage
    recs = recommend_indexes(
        {"table": "orders", "filters": [{"column": "id", "op": "=", "value": 1}]},
        schema_snapshot={
            "tables": {
                "bad": 123,
                "orders": {
                    "primary_keys": ["uuid", "uuid", ""],
                    "columns": [
                        {"name": "id", "is_primary": False},
                        {"name": "uuid", "is_primary": True},
                    ],
                },
                "users": {
                    "primary_keys": ["id"],
                    "columns": {
                        "id": {"is_primary": True},
                        "other": {"is_primary": False},
                    },
                },
            }
        },
    )
    assert any(r["index_name"] == "idx_orders_id" for r in recs)

    # 3. django.py helper and capability branches
    assert (
        _is_tenant_isolation_active(None, TenantContext(tenant_id="t1"), "not_a_dict")
        is True
    )
    assert _is_tenant_isolation_active(None, None, "not_a_dict") is False
    _require_spec_capabilities("not_a_dict", EngineCapabilities.simple_only())
    for cap_spec in (
        {"ctes": [{"name": "c", "query": {"table": "users"}}]},
        {"window_functions": [{"function": "ROW_NUMBER", "alias": "rn"}]},
        {"rollup": ["name"]},
        {"vector_search": {"column": "v", "vector": [0.1]}},
    ):
        with pytest.raises(DisabledFeatureError):
            _require_spec_capabilities(cap_spec, EngineCapabilities.simple_only())

    urls = create_django_urls(
        sqlite_conn,
        capabilities=EngineCapabilities.simple_only(),
    )
    url_map = {u.name: u.callback for u in urls}

    class _DummyDjangoReq:
        def __init__(self, body_dict: dict[str, Any]) -> None:
            self.method = "POST"
            self.body = json.dumps(body_dict).encode("utf-8")
            self.GET: dict[str, str] = {}
            self.META: dict[str, str] = {}

    for ep_name in (
        "query-builder-export",
        "query-builder-export-stream",
        "query-builder-explain",
    ):
        resp = url_map[ep_name](
            _DummyDjangoReq(
                {"spec": {"table": "users", "rollup": ["name"]}, "format": "csv"}
            )
        )
        assert resp.status_code == 403

    assert (
        url_map["query-builder-export"](
            _DummyDjangoReq({"sql": "SELECT id FROM users", "format": "csv"})
        ).status_code
        == 403
    )
    assert (
        url_map["query-builder-export-stream"](
            _DummyDjangoReq({"sql": "SELECT id FROM users", "format": "csv"})
        ).status_code
        == 403
    )

    from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied

    drf_views = create_drf_views(
        sqlite_conn,
        capabilities=EngineCapabilities.simple_only(),
    )
    for view_key in ("ExportView", "ExportStreamView", "ExplainView"):
        with pytest.raises((DRFPermissionDenied, DisabledFeatureError)):
            drf_views[view_key]().post(
                SimpleNamespace(
                    data={
                        "spec": {"table": "users", "rollup": ["name"]},
                        "format": "csv",
                    }
                )
            )

    # 4. fastapi.py export/explain disabled capability branches
    app = FastAPI()
    app.include_router(
        create_query_builder_router(
            sqlite_conn,
            capabilities=EngineCapabilities.simple_only(),
            security={"allowed_tables": ["users"], "enforce_tenant_isolation": False},
        )
    )
    client = TestClient(app)
    for disabled_spec in (
        {"table": "users", "ctes": [{"name": "c", "query": {"table": "users"}}]},
        {
            "table": "users",
            "window_functions": [{"function": "ROW_NUMBER", "alias": "rn"}],
        },
        {"table": "users", "rollup": ["name"]},
        {"table": "users", "vector_search": {"column": "v", "vector": [0.1]}},
    ):
        assert client.post("/export", json={"spec": disabled_spec}).status_code == 403
        assert (
            client.post("/export/stream", json={"spec": disabled_spec}).status_code
            == 403
        )
        assert client.post("/explain", json={"spec": disabled_spec}).status_code == 403

    assert (
        client.post("/export", json={"sql": "SELECT id FROM users"}).status_code == 403
    )
    assert client.post("/explain", json={"spec": {}}).status_code == 400
    assert (
        client.post(
            "/explain", json={"spec": {"table": "users", "columns": ["id"]}}
        ).status_code
        == 200
    )

    # 5. join_solver.py branch coverage
    rel_obj = SimpleNamespace(
        source_table="orders",
        target_table="users",
        source_column="user_id",
        target_column="id",
    )
    cond = find_best_join_condition(
        "users",
        "orders",
        {
            "tables": {
                "users": {"columns": [{"name": "id"}]},
                "orders": {"columns": [{"name": "user_id"}]},
            },
            "relationships": [123, rel_obj],
        },
    )
    assert cond["is_fk"] is True

    cond_ies = find_best_join_condition(
        "categories",
        "items",
        {
            "tables": {
                "categories": {"columns": [{"name": "id"}]},
                "items": {"columns": [{"name": "category_id"}]},
            },
            "relationships": "not_a_list",
        },
    )
    assert cond_ies["right_col"] == "category_id"

    cond_es = find_best_join_condition(
        "boxes",
        "items",
        {
            "tables": {
                "boxes": {"columns": [{"name": "id"}]},
                "items": {"columns": [{"name": "box_id"}]},
            },
        },
    )
    assert cond_es["right_col"] == "box_id"

    path_rel = find_join_path(
        ["users"],
        "orders",
        {
            "tables": {"users": {}, "orders": {}},
            "relationships": [123, rel_obj],
        },
    )
    assert len(path_rel) == 1

    # 6. mcp_server.py locked connection resource & tool branches
    mcp = McpServer(
        connector=sqlite_conn,
        lock_connection=True,
        security_policy=SecurityPolicy(
            allowed_tables=["users"], enforce_tenant_isolation=False
        ),
    )
    tools = mcp.get_tools()
    assert any(t["name"] == "query_builder_execute" for t in tools)
    res_cat = mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": {"uri": "query-builder://schema/catalog"},
        }
    )
    assert res_cat is not None and "result" in res_cat
    res_comp = mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "query_builder_compile",
                "arguments": {
                    "spec": json.dumps({"table": "users", "columns": ["id"]})
                },
            },
        }
    )
    assert res_comp is not None and res_comp["result"]["isError"] is False

    import socket
    from dataclasses import dataclass

    from query_builder import egress_guard

    @dataclass
    class _SnapDC:
        tables: dict[str, Any]

    class _ToDictConn:
        def introspect_schema(self, filter_sensitive: bool = True) -> Any:
            return SimpleNamespace(to_dict=lambda: {"tables": {"users": {}}})

    class _DCConn:
        def introspect_schema(self, filter_sensitive: bool = True) -> Any:
            return _SnapDC(tables={"users": {}})

    class _RawConn:
        def introspect_schema(self, filter_sensitive: bool = True) -> Any:
            return "not_a_dict"

    for dummy_c in (_ToDictConn(), _DCConn(), _RawConn()):
        mcp_dummy = McpServer(connector=dummy_c, lock_connection=True)
        assert "tables" in mcp_dummy._read_resource("query-builder://schema/catalog")

    with egress_guard.egress_guard(
        SimpleNamespace(
            connect_time_guard=True,
            allow_private_networks=True,
            allowed_hostnames=[],
        )
    ):
        dummy_sock = SimpleNamespace(family=socket.AF_INET, type=socket.SOCK_STREAM)
        assert (
            egress_guard._check_socket_address(dummy_sock, "not_tuple") == "not_tuple"  # type: ignore[arg-type]
        )
        assert egress_guard._check_socket_address(dummy_sock, (123, 80)) == (123, 80)  # type: ignore[arg-type]
        with patch("socket.getaddrinfo", return_value=[]):
            assert egress_guard._check_socket_address(
                dummy_sock,  # type: ignore[arg-type]
                ("example.invalid", 80),
            ) == ("example.invalid", 80)
