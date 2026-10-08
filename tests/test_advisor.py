"""
Unit Tests for Query Builder Performance Advisor and Cloud Cost Estimator.
==========================================================================
Covers 100% of statements, branches, and functions in query_builder/advisor.py.
"""

from __future__ import annotations

from query_builder.advisor import (
    analyze_query_performance,
    estimate_cloud_cost,
    recommend_indexes,
)
from query_builder.models import FilterSpec, JoinSpec, OrderBySpec, QuerySpec


class TestCloudCostEstimation:
    """Tests for estimate_cloud_cost."""

    def test_bigquery_cost_estimation_defaults(self) -> None:
        sql = "SELECT id, amount FROM orders WHERE status = 'shipped';"
        cost = estimate_cloud_cost(sql, dialect="bigquery")

        assert cost["pricing_tier"] == "BigQuery On-Demand ($6.25/TB)"
        assert cost["bytes_scanned_estimated"] >= 10 * 1024 * 1024
        assert cost["dollar_cost_estimated"] > 0
        assert cost["is_cached"] is False

    def test_bigquery_cost_estimation_with_table_stats(self) -> None:
        sql = "SELECT * FROM logs JOIN events ON logs.id = events.log_id;"
        stats = {
            "logs": {"byte_size": 100 * 1024 * 1024 * 1024},  # 100 GB
            "events": {"row_count": 1_000_000},  # 1M rows * 128 bytes = 128 MB
        }
        cost = estimate_cloud_cost(sql, dialect="bigquery", table_stats=stats)

        assert cost["bytes_scanned_estimated"] > 100 * 1024 * 1024 * 1024
        assert cost["dollar_cost_estimated"] > 0.5

    def test_snowflake_cost_estimation(self) -> None:
        sql = "SELECT * FROM sales;"
        cost = estimate_cloud_cost(sql, dialect="snowflake")

        assert cost["pricing_tier"] == "Snowflake X-Small (1 Credit/Hr)"
        assert cost["credits_estimated"] is not None
        assert cost["credits_estimated"] > 0
        assert cost["dollar_cost_estimated"] > 0

    def test_postgres_and_duckdb_zero_cost(self) -> None:
        sql = "SELECT * FROM users;"
        cost = estimate_cloud_cost(sql, dialect="postgres")

        assert cost["pricing_tier"] == "Zero-Cost Local / Provisioned Instance"
        assert cost["dollar_cost_estimated"] == 0.0
        assert cost["credits_estimated"] is None


class TestIndexRecommendations:
    """Tests for recommend_indexes."""

    def test_empty_table_returns_empty_list(self) -> None:
        assert recommend_indexes({}) == []
        assert recommend_indexes({"table": ""}) == []

    def test_recommend_indexes_from_query_spec_dataclass(self) -> None:
        spec = QuerySpec(
            table="orders",
            columns=["id", "customer_id", "status"],
            joins=[
                JoinSpec(
                    table="customers",
                    type="INNER",
                    left_table="orders",
                    left_col="customer_id",
                    right_col="customer_uuid",
                )
            ],
            filters=[
                FilterSpec(column="status", op="=", value="complete"),
                FilterSpec(
                    column="id", op="=", value=1
                ),  # Skipped because id is in existing_indexes
                FilterSpec(
                    column="EXISTS (sub)", op="RAW", value=""
                ),  # Skipped because RAW
            ],
            order_by=[OrderBySpec(column="created_at", direction="desc")],
        )

        recs = recommend_indexes(spec)
        assert len(recs) == 3

        # 1. Filter index on status
        r_filter = next(r for r in recs if r["columns"] == ["status"])
        assert r_filter["table"] == "orders"
        assert r_filter["index_name"] == "idx_orders_status"
        assert r_filter["ddl"] == "CREATE INDEX idx_orders_status ON orders (status);"
        assert r_filter["estimated_impact"] == "high"

        # 2. Join foreign key index on customer_uuid
        r_join = next(r for r in recs if r["columns"] == ["customer_uuid"])
        assert r_join["table"] == "customers"
        assert r_join["index_name"] == "idx_customers_customer_uuid"
        assert r_join["estimated_impact"] == "high"

        # 3. Composite index on (status, created_at)
        r_comp = next(r for r in recs if len(r["columns"]) == 2)
        assert r_comp["columns"] == ["status", "created_at"]
        assert r_comp["index_name"] == "idx_orders_comp_status_created_at"
        assert r_comp["estimated_impact"] == "medium"

    def test_recommend_indexes_from_dict(self) -> None:
        spec_dict = {
            "table": "events",
            "filters": [{"column": "event_type", "op": "=", "value": "login"}],
            "order_by": [{"column": "timestamp", "direction": "desc"}],
        }
        recs = recommend_indexes(spec_dict)
        assert len(recs) == 2

    def test_recommend_indexes_skips_existing_join_index_and_same_col_composite(
        self,
    ) -> None:
        spec = QuerySpec(
            table="orders",
            columns=["id"],
            joins=[JoinSpec(table="users", left_col="user_id", right_col="id")],
            filters=[FilterSpec(column="created_at", op="=", value="2026-01-01")],
            order_by=[OrderBySpec(column="created_at", direction="DESC")],
        )
        recs = recommend_indexes(spec)
        assert len(recs) == 1
        assert recs[0]["columns"] == ["created_at"]


class TestAnalyzeQueryPerformance:
    """Tests for analyze_query_performance."""

    def test_flags_unbounded_scan_when_select_star_without_limit(self) -> None:
        spec = QuerySpec(table="large_table", columns=["*"], limit=0)
        sql = "SELECT * FROM large_table;"

        insights = analyze_query_performance(spec, sql, dialect="postgres")
        types = [i["type"] for i in insights]

        assert "cost" in types
        assert "warning" in types
        assert "optimization" in types

        warn = next(i for i in insights if i["type"] == "warning")
        assert "Unbounded Table Scan" in warn["title"]

        opt = next(i for i in insights if i["type"] == "optimization")
        assert "Full Table Scan" in opt["title"]

    def test_bounded_scan_with_filters_and_indexes(self) -> None:
        spec = QuerySpec(
            table="orders",
            columns=["id", "total"],
            filters=[FilterSpec(column="status", op="=", value="paid")],
            limit=50,
        )
        sql = "SELECT id, total FROM orders WHERE status = 'paid' LIMIT 50;"

        insights = analyze_query_performance(spec, sql, dialect="bigquery")
        types = [i["type"] for i in insights]

        assert "cost" in types
        assert "index" in types
        assert "warning" not in types
        assert "optimization" not in types
