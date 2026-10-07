"""
Tests for EngineCapabilities, FeatureTier, DisabledFeatureError, and compiler integration.
"""

import pytest
from query_builder import (
    EngineCapabilities,
    FeatureTier,
    DisabledFeatureError,
    QueryCompiler,
)
from query_builder.models import QuerySpec, WindowFunctionSpec, RollupSpec


def test_capabilities_default_and_serialization():
    caps = EngineCapabilities.default()
    assert caps.projections == FeatureTier.STANDARD
    assert caps.filters == FeatureTier.STANDARD
    assert caps.joins == FeatureTier.STANDARD
    assert caps.ctes == FeatureTier.ADVANCED
    assert caps.window_functions == FeatureTier.ADVANCED
    assert caps.is_enabled("ctes")
    assert caps.is_advanced("ctes")

    d = caps.to_dict()
    assert d["projections"] == "standard"
    assert d["ctes"] == "advanced"
    assert d["window_functions"] == "advanced"

    restored = EngineCapabilities.from_dict(d)
    assert restored.ctes == FeatureTier.ADVANCED
    assert restored.projections == FeatureTier.STANDARD


def test_capabilities_simple_only_preset():
    simple = EngineCapabilities.simple_only()
    assert not simple.is_enabled("ctes")
    assert not simple.is_enabled("window_functions")
    assert not simple.is_enabled("analytical_grouping")
    assert not simple.is_enabled("vector_search")
    assert simple.is_enabled("projections")
    assert simple.is_enabled("filters")


def test_compiler_allows_standard_query_on_simple_capabilities():
    simple = EngineCapabilities.simple_only()
    spec = {
        "table": "users",
        "columns": ["id", "name"],
        "filters": [{"column": "age", "op": "gt", "value": 21}],
        "order_by": [{"column": "name", "direction": "asc"}],
        "limit": 10,
    }
    compiler = QueryCompiler(spec, capabilities=simple)
    sql, params, _, _ = compiler.compile()
    assert "users" in sql
    assert "WHERE" in sql
    assert "ORDER BY" in sql


def test_compiler_blocks_ctes_when_disabled():
    caps = EngineCapabilities(ctes=FeatureTier.DISABLED)
    spec = {
        "table": "users",
        "columns": ["id"],
        "ctes": [{"name": "active_users", "query": {"table": "users", "columns": ["id"]}}],
    }
    with pytest.raises(DisabledFeatureError) as exc_info:
        QueryCompiler(spec, capabilities=caps)
    assert "Feature 'ctes' is disabled" in str(exc_info.value)


def test_compiler_blocks_window_functions_when_disabled():
    caps = EngineCapabilities(window_functions=FeatureTier.DISABLED)
    spec = {
        "table": "orders",
        "columns": ["id", "amount"],
        "window_functions": [
            {
                "function": "sum",
                "column": "amount",
                "partition_by": ["user_id"],
                "order_by": ["id"],
                "alias": "running_total",
            }
        ],
    }
    with pytest.raises(DisabledFeatureError) as exc_info:
        QueryCompiler(spec, capabilities=caps)
    assert "Feature 'window_functions' is disabled" in str(exc_info.value)


def test_compiler_blocks_analytical_grouping_when_disabled():
    caps = EngineCapabilities(analytical_grouping=FeatureTier.DISABLED)
    spec = {
        "table": "sales",
        "columns": ["region", "year"],
        "rollup": {"columns": ["region", "year"]},
    }
    with pytest.raises(DisabledFeatureError) as exc_info:
        QueryCompiler(spec, capabilities=caps)
    assert "Feature 'analytical_grouping' is disabled" in str(exc_info.value)


def test_compiler_blocks_vector_search_when_disabled():
    caps = EngineCapabilities(vector_search=FeatureTier.DISABLED)
    spec = {
        "table": "documents",
        "columns": ["id", "content"],
        "vector_search": {
            "column": "embedding",
            "vector": [0.1, 0.2, 0.3],
            "metric": "cosine",
            "top_k": 5,
        },
    }
    with pytest.raises(DisabledFeatureError) as exc_info:
        QueryCompiler(spec, capabilities=caps)
    assert "Feature 'vector_search' is disabled" in str(exc_info.value)


def test_compiler_blocks_calculated_fields_when_disabled():
    caps = EngineCapabilities(calculated_fields=FeatureTier.DISABLED)
    spec = {
        "table": "orders",
        "columns": [
            "id",
            {"alias": "total_with_tax", "expression": "amount * 1.1"},
        ],
    }
    with pytest.raises(DisabledFeatureError) as exc_info:
        QueryCompiler(spec, capabilities=caps)
    assert "Feature 'calculated_fields' is disabled" in str(exc_info.value)


def test_fastapi_capabilities_integration():
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from query_builder.integrations.fastapi import create_query_builder_router
        from query_builder.connectors.sqlite import SQLiteConnector
        import sqlite3
    except ImportError:
        pytest.skip("FastAPI not installed")

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO users VALUES (1, 'Alice')")
    conn.commit()
    connector = SQLiteConnector(connection=conn)

    simple_caps = EngineCapabilities.simple_only()
    router = create_query_builder_router(
        connector=connector,
        capabilities=simple_caps,
        prefix="/qb",
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # 1. GET /qb/capabilities
    cap_res = client.get("/qb/capabilities")
    assert cap_res.status_code == 200
    caps_data = cap_res.json()["capabilities"]
    assert caps_data["ctes"] == "disabled"
    assert caps_data["projections"] == "standard"

    # 2. GET /qb/schema contains capabilities
    schema_res = client.get("/qb/schema")
    assert schema_res.status_code == 200
    assert "capabilities" in schema_res.json()
    assert schema_res.json()["capabilities"]["raw_sql"] == "disabled"

    # 3. POST /qb/compile simple succeeds
    compile_ok = client.post(
        "/qb/compile",
        json={"spec": {"table": "users", "columns": ["id", "name"]}},
    )
    assert compile_ok.status_code == 200

    # 4. POST /qb/compile with disabled CTE returns 403
    compile_cte = client.post(
        "/qb/compile",
        json={
            "spec": {
                "table": "users",
                "columns": ["id"],
                "ctes": [{"name": "u", "query": {"table": "users", "columns": ["id"]}}],
            }
        },
    )
    assert compile_cte.status_code == 403
    assert "disabled" in compile_cte.json()["detail"].lower()

    # 5. POST /qb/execute with raw SQL when raw_sql is disabled returns 403
    exec_raw = client.post(
        "/qb/execute",
        json={"sql": "SELECT 1"},
    )
    assert exec_raw.status_code == 403
    assert "raw_sql" in exec_raw.json()["detail"].lower()

