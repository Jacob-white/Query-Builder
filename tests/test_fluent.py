"""
Tests for FluentQuery Builder.
==============================
"""

from __future__ import annotations

from unittest.mock import MagicMock

from query_builder.fluent import FluentQuery, query
from query_builder.models import QuerySpec


def test_fluent_query_basic():
    q = query("users").select("id", "name").where("active", "eq", True).limit(25)
    spec = q.to_spec()
    assert isinstance(spec, QuerySpec)
    assert spec.table == "users"
    assert spec.columns == ["id", "name"]
    assert len(spec.filters) == 1
    assert spec.filters[0].column == "active"
    assert spec.filters[0].value is True
    assert spec.limit == 25

    # Test QuerySpec.builder()
    b = QuerySpec.builder("users").select("id").limit(5)
    assert b.to_spec().table == "users"
    assert b.to_spec().limit == 5


def test_fluent_query_aliases_and_extensions():
    q = (
        FluentQuery("orders")
        .columns(["id", "total"])
        .columns("status")
        .filter("total", "gte", 100, table_prefix="o")
        .or_where("status", "eq", "pending")
        .having("total", "gt", 50, agg="SUM")
        .order_by("id", "DESC", table_prefix="o")
        .limit(10)
        .offset(5)
        .distinct(True)
        .tenant("tenant-42")
    )
    d = q.to_dict()
    assert d["table"] == "orders"
    assert d["columns"] == ["id", "total", "status"]
    assert len(d["filters"]) == 2
    assert d["filters"][0]["table_prefix"] == "o"
    assert d["filter_join"] == "OR"
    assert len(d["having"]) == 1
    assert d["having"][0]["agg"] == "SUM"
    assert d["order_by"][0]["table_prefix"] == "o"
    assert d["distinct"] is True
    assert d["tenant_id"] == "tenant-42"
    assert d["limit"] == 10
    assert d["offset"] == 5


def test_fluent_query_joins():
    q = (
        query("users")
        .select("users.id", "profiles.bio", "orders.amount", "logs.msg")
        .left_join("profiles", on_left="users.id", on_right="profiles.user_id")
        .right_join("orders", on_left="users.id", on_right="orders.user_id")
        .full_join(
            "logs", on=[{"left": "users.id", "right": "logs.user_id", "op": "eq"}]
        )
    )
    spec = q.to_spec()
    assert len(spec.joins) == 3
    assert spec.joins[0].table == "profiles"
    assert spec.joins[0].type == "LEFT JOIN"
    assert spec.joins[1].table == "orders"
    assert spec.joins[1].type == "RIGHT JOIN"
    assert spec.joins[2].table == "logs"
    assert spec.joins[2].type == "FULL JOIN"


def test_fluent_query_compile_and_sql():
    q = query("products").select("name", "price").where("price", "lt", 50)
    sql, params, count_sql, count_params = q.compile(dialect="postgres")
    assert "SELECT" in sql
    assert '"products"' in sql
    assert 50 in params

    raw_sql = q.to_sql(dialect="postgres")
    assert raw_sql == sql


def test_fluent_query_execute():
    connector = MagicMock()
    connector.execute.return_value = {"rows": [{"id": 1}], "columns": ["id"]}
    q = query("items").select("id").where("id", "eq", 1)
    res = q.execute(connector, limit=1)
    assert res == {"rows": [{"id": 1}], "columns": ["id"]}
    connector.execute.assert_called_once()


def test_lazy_imports_and_dir():
    import pytest

    import query_builder

    fq = query_builder.FluentQuery
    assert fq is FluentQuery
    assert "FluentQuery" in dir(query_builder)

    with pytest.raises(AttributeError, match="has no attribute 'non_existent_symbol'"):
        _ = query_builder.non_existent_symbol
