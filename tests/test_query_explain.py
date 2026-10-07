"""
Tests for Universal Query Plan Explain and Optimization Advisory Engine.
========================================================================
Covers QueryPlanNode models, Postgres explain plan parsing, spec estimation,
rule-based optimization warnings, and server API endpoint integration.
"""

from __future__ import annotations

import json
import threading
import urllib.request

from query_builder.explain import (
    QueryPlanNode,
    estimate_plan_from_spec,
    normalize_explain_output,
)
from query_builder.models import QuerySpec
from query_builder.server import create_server


def test_query_plan_node_to_dict():
    child = QueryPlanNode(
        node_type="Seq Scan",
        table="users",
        cost_estimate=45.0,
        rows_estimated=150,
        filter_predicate="active = 1",
    )
    parent = QueryPlanNode(
        node_type="Limit",
        cost_estimate=50.0,
        rows_estimated=10,
        cost_percentage=100.0,
        warnings=["Bottleneck detected"],
        children=[child],
    )

    d = parent.to_dict()
    assert d["node_type"] == "Limit"
    assert d["cost_estimate"] == 50.0
    assert d["cost_percentage"] == 100.0
    assert len(d["warnings"]) == 1
    assert len(d["children"]) == 1
    assert d["children"][0]["node_type"] == "Seq Scan"
    assert d["children"][0]["table"] == "users"


def test_estimate_plan_from_spec_simple():
    spec = {
        "table": "documents",
        "columns": ["id", "title"],
        "filters": [["status", "eq", "published"]],
        "limit": 20,
    }
    node = estimate_plan_from_spec(spec)
    assert node.node_type == "Limit"
    assert node.rows_estimated == 20
    assert len(node.children) > 0
    sort_node = node.children[0]
    assert sort_node.node_type == "Sort"
    scan_node = sort_node.children[0]
    assert scan_node.node_type == "Seq Scan"
    assert scan_node.table == "documents"
    assert scan_node.filter_predicate == "status eq published"


def test_estimate_plan_from_spec_vector_unindexed_warning():
    spec = {
        "table": "embeddings",
        "columns": ["id", "text"],
        "vector_search": {
            "vector": [0.1, 0.2, 0.3],
            "column": "vec",
            "top_k": 5,
        },
    }
    node = estimate_plan_from_spec(spec)
    assert node.node_type == "Limit"
    sort_node = node.children[0]
    knn_node = sort_node.children[0]
    assert knn_node.node_type == "KNN Scan"
    # Rule 2: Unindexed vector search scan warning
    assert any("vector index" in w.lower() for w in knn_node.warnings)


def test_estimate_plan_from_spec_hybrid_search():
    spec = {
        "table": "articles",
        "columns": ["id", "title"],
        "hybrid_search": {
            "vector": [0.1, 0.2, 0.3],
            "vector_column": "embedding",
            "query_text": "distributed databases",
            "text_columns": ["title", "body"],
            "fusion": "rrf",
            "top_k": 10,
        },
    }
    node = estimate_plan_from_spec(spec)
    assert node.node_type == "Limit"
    sort_node = node.children[0]
    hybrid_node = sort_node.children[0]
    assert hybrid_node.node_type == "Hybrid Search Merge"
    assert len(hybrid_node.children) == 2
    child_types = [c.node_type for c in hybrid_node.children]
    assert "Vector KNN Scan" in child_types
    assert "Full-Text Scan" in child_types


def test_estimate_plan_with_joins():
    spec = {
        "table": "orders",
        "columns": ["id", "customer_name"],
        "joins": [
            {
                "table": "customers",
                "type": "INNER",
                "on": ["orders.customer_id", "customers.id"],
            },
            {
                "table": "shipments",
                "type": "LEFT",
                "on": ["orders.id", "shipments.order_id"],
            },
        ],
        "limit": 50,
    }
    node = estimate_plan_from_spec(spec)
    assert node.node_type == "Limit"
    sort_node = node.children[0]
    join_top = sort_node.children[0]
    assert "Join" in join_top.node_type
    assert len(join_top.children) == 2


def test_estimate_plan_filter_with_unstructured_item():
    spec = {
        "table": "users",
        "columns": ["id"],
        "filters": ["raw_expression", {"column": "age", "op": ">", "value": 18}],
    }
    node = estimate_plan_from_spec(spec)
    scan_node = node.children[0].children[0]
    assert scan_node.filter_predicate == "age > 18"


def test_parse_postgres_plan_json():
    pg_raw = [
        {
            "Plan": {
                "Node Type": "Seq Scan",
                "Relation Name": "large_log_table",
                "Total Cost": 45000.0,
                "Plan Rows": 500000,
                "Actual Total Time": 124.5,
                "Actual Rows": 499800,
                "Filter": "(created_at > '2026-01-01'::date)",
                "Plans": [
                    {
                        "Node Type": "Index Scan",
                        "Relation Name": "index_table",
                        "Index Name": "idx_created_at",
                        "Total Cost": 120.0,
                        "Plan Rows": 100,
                    }
                ],
            }
        }
    ]

    node = normalize_explain_output(pg_raw, dialect="postgres")
    assert node.node_type == "Seq Scan"
    assert node.table == "large_log_table"
    assert node.cost_estimate == 45000.0
    assert node.rows_estimated == 500000
    assert node.actual_time_ms == 124.5
    assert node.rows_actual == 499800
    assert node.filter_predicate == "(created_at > '2026-01-01'::date)"
    assert len(node.children) == 1
    assert node.children[0].node_type == "Index Scan"
    assert node.children[0].index_name == "idx_created_at"

    # Warnings verification: Seq Scan on >1000 rows
    assert any("Sequential table scan" in w for w in node.warnings)


def test_normalize_explain_output_dict_and_fallback():
    # 1. Single dict with "Plan"
    single_dict = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Total Cost": 50.0,
            "Plan Rows": 10,
        }
    }
    node = normalize_explain_output(single_dict, dialect="postgres")
    assert node.node_type == "Seq Scan"

    # 2. Generic fallback driver scan
    fallback_node = normalize_explain_output("SCAN TABLE users", dialect="sqlite")
    assert fallback_node.node_type == "Execution Plan"
    assert "Sqlite" in fallback_node.children[0].node_type


def test_estimate_plan_edge_cases():
    # Empty spec and string spec
    node_empty = estimate_plan_from_spec({})
    assert node_empty.node_type == "Limit"

    node_str = estimate_plan_from_spec("non_dict_spec")  # type: ignore
    assert node_str.node_type == "Limit"

    # Join without dict attributes and dict filters
    node_joins = estimate_plan_from_spec(
        {
            "table": "a",
            "joins": [{"table": "b"}],
            "filters": [{"column": "age", "op": ">", "value": 18}],
        }
    )
    assert len(node_joins.children[0].children[0].children) == 2

    # QuerySpec dataclass instance & object join
    class DummyJoin:
        def __init__(self):
            self.table = "dummy_table"
            self.type = "INNER"

    spec_obj = QuerySpec(
        table="orders",
        columns=["id"],
        joins=[DummyJoin()],  # type: ignore
    )
    node_obj = estimate_plan_from_spec(spec_obj)
    assert node_obj.node_type == "Limit"

    # Zero total cost
    from query_builder.explain import _analyze_and_tag_warnings

    zero_node = QueryPlanNode(node_type="Seq Scan", cost_estimate=0.0)
    _analyze_and_tag_warnings(zero_node, 0.0)
    assert zero_node.cost_percentage == 0.0


def test_server_explain_endpoint():
    server = create_server("127.0.0.1", 0)
    host, port = server.server_address
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    base_url = f"http://{host}:{port}"
    try:
        payload = json.dumps(
            {
                "spec": {
                    "table": "users",
                    "columns": ["id", "username", "email"],
                    "filters": [["status", "eq", "active"]],
                    "limit": 25,
                },
                "dialect": "postgres",
            }
        ).encode()

        req = urllib.request.Request(
            f"{base_url}/api/v1/explain",
            data=payload,
            headers={"Content-Type": "application/json", "Connection": "close"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            assert data["node_type"] == "Limit"
            assert data["rows_estimated"] == 25
            assert "cost_percentage" in data
            assert "children" in data
            assert len(data["children"]) > 0

    finally:
        server.shutdown()
        server.server_close()
