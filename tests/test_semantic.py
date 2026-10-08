"""
Tests for Semantic Metrics & Modeling Layer Protocol.
====================================================
Covers MetricDefinition, DimensionDefinition, SemanticModel, SemanticRegistry,
YAML/JSON loading, SQL expansion across dialects, and QueryCompiler integration.
"""

import json
from pathlib import Path

import pytest

from query_builder.compiler import QueryCompiler
from query_builder.exceptions import ValidationError
from query_builder.semantic import (
    DimensionDefinition,
    MetricDefinition,
    MetricFilter,
    SemanticError,
    SemanticModel,
    SemanticRegistry,
    _format_filter_sql,
    expand_metric_sql,
    expand_time_grain_sql,
    get_global_semantic_registry,
    load_semantic_models_from_dict,
    load_semantic_models_from_yaml,
    parse_simple_yaml_or_json,
    reset_global_semantic_registry,
)


class TestMetricFilter:
    def test_filter_to_and_from_dict(self):
        f = MetricFilter(field="status", operator="eq", value="active")
        d = f.to_dict()
        assert d == {"field": "status", "operator": "eq", "value": "active"}

        f2 = MetricFilter.from_dict({"column": "state", "op": "NEQ", "value": "draft"})
        assert f2.field == "state"
        assert f2.operator == "neq"
        assert f2.value == "draft"

    def test_filter_requires_field(self):
        with pytest.raises(SemanticError, match="requires a 'field'"):
            MetricFilter.from_dict({"operator": "eq", "value": 10})


class TestMetricDefinition:
    def test_metric_definition_lifecycle(self):
        m = MetricDefinition(
            name="mrr",
            title="Monthly Recurring Revenue",
            sql_expression="amount_cents / 100.0",
            aggregation="sum",
            filters=[MetricFilter(field="status", operator="eq", value="active")],
            format="currency",
        )
        d = m.to_dict()
        assert d["name"] == "mrr"
        assert d["aggregation"] == "sum"
        assert len(d["filters"]) == 1

        m2 = MetricDefinition.from_dict(d)
        assert m2.name == "mrr"
        assert m2.title == "Monthly Recurring Revenue"
        assert m2.filters[0].field == "status"

    def test_metric_unsupported_aggregation(self):
        with pytest.raises(SemanticError, match="Unsupported metric aggregation"):
            MetricDefinition(
                name="bad",
                title="Bad",
                sql_expression="col",
                aggregation="exponential",
            )

    def test_metric_fallback_format_and_missing_fields(self):
        m = MetricDefinition(
            name="users", title="Users", sql_expression="id", format="custom_unknown"
        )
        assert m.format == "number"

        with pytest.raises(SemanticError, match="requires a 'name'"):
            MetricDefinition.from_dict({"sql": "id"})

        with pytest.raises(SemanticError, match="requires an 'sql_expression'"):
            MetricDefinition.from_dict({"name": "users"})


class TestDimensionDefinition:
    def test_dimension_lifecycle(self):
        d = DimensionDefinition(
            name="created_date",
            title="Created Date",
            sql_expression="created_at",
            data_type="timestamp",
            time_grains=["day", "month", "invalid_grain"],
        )
        assert d.time_grains == ["day", "month"]
        dict_data = d.to_dict()
        assert dict_data["name"] == "created_date"

        d2 = DimensionDefinition.from_dict(dict_data)
        assert d2.name == "created_date"
        assert d2.time_grains == ["day", "month"]

    def test_dimension_errors(self):
        with pytest.raises(SemanticError, match="requires a 'name'"):
            DimensionDefinition.from_dict({"sql": "col"})
        with pytest.raises(SemanticError, match="requires an 'sql_expression'"):
            DimensionDefinition.from_dict({"name": "col"})


class TestSemanticModel:
    def test_model_lifecycle(self):
        sm = SemanticModel(
            name="subscriptions",
            table_name="billing_subscriptions",
            dimensions=[
                DimensionDefinition(
                    name="plan", title="Plan", sql_expression="plan_name"
                )
            ],
            metrics=[
                MetricDefinition(
                    name="total_revenue",
                    title="Revenue",
                    sql_expression="amount",
                    aggregation="sum",
                )
            ],
        )
        assert sm.get_dimension("plan") is not None
        assert sm.get_dimension("nonexistent") is None
        assert sm.get_metric("total_revenue") is not None
        assert sm.get_metric("nonexistent") is None

        d = sm.to_dict()
        sm2 = SemanticModel.from_dict(d)
        assert sm2.name == "subscriptions"
        assert sm2.table_name == "billing_subscriptions"
        assert len(sm2.dimensions) == 1
        assert len(sm2.metrics) == 1

    def test_model_validation(self):
        with pytest.raises(SemanticError, match="requires a 'name'"):
            SemanticModel.from_dict({})


class TestSemanticRegistry:
    def setup_method(self):
        reset_global_semantic_registry()

    def test_registry_operations(self):
        reg = get_global_semantic_registry()
        assert len(reg.list_models()) == 0

        sm = SemanticModel(
            name="users",
            table_name="app_users",
            metrics=[
                MetricDefinition(
                    name="active_count",
                    title="Active",
                    sql_expression="id",
                    aggregation="count",
                )
            ],
        )
        reg.register_model(sm)

        assert reg.get_model("users") == sm
        assert reg.get_model("unknown") is None
        assert reg.get_metric("active_count") is not None
        assert reg.get_metric("active_count").table == "app_users"
        assert len(reg.list_metrics()) == 1

        reg.clear()
        assert len(reg.list_models()) == 0


class TestYamlAndJsonLoading:
    def test_parse_json(self):
        data = {
            "models": [
                {
                    "name": "orders",
                    "table_name": "shop_orders",
                    "metrics": [
                        {"name": "order_count", "sql": "id", "aggregation": "count"}
                    ],
                }
            ]
        }
        res = parse_simple_yaml_or_json(json.dumps(data))
        models = load_semantic_models_from_dict(res)
        assert len(models) == 1
        assert models[0].name == "orders"

    def test_parse_invalid_json(self):
        with pytest.raises(SemanticError, match="Invalid JSON"):
            parse_simple_yaml_or_json("{not_valid_json")

    def test_parse_simple_yaml_string(self):
        yaml_content = """
models:
  - name: revenue
    table: sales_records
    description: Revenue model
    metrics:
      - name: gross_sales
        sql: amount
        aggregation: sum
    dimensions:
      - name: region
        sql: sales_region
"""
        models = load_semantic_models_from_yaml(yaml_content)
        assert len(models) == 1
        assert models[0].name == "revenue"
        assert models[0].table_name == "sales_records"
        assert len(models[0].metrics) == 1
        assert len(models[0].dimensions) == 1

    def test_load_from_file_path(self, tmp_path: Path):
        file_path = tmp_path / "semantic_model.json"
        file_path.write_text(
            json.dumps(
                {
                    "name": "customers",
                    "table": "users",
                    "metrics": [{"name": "cnt", "sql": "id", "aggregation": "count"}],
                }
            )
        )
        models = load_semantic_models_from_yaml(file_path)
        assert len(models) == 1
        assert models[0].name == "customers"

    def test_load_missing_file_path(self, tmp_path: Path):
        missing = tmp_path / "does_not_exist.yaml"
        with pytest.raises(SemanticError, match="file not found"):
            load_semantic_models_from_yaml(missing)


class TestSqlExpansions:
    def test_format_filter_sql_all_operators(self):
        assert (
            _format_filter_sql(MetricFilter("status", "eq", "active"), "postgres")
            == "status = 'active'"
        )
        assert (
            _format_filter_sql(MetricFilter("status", "eq", None), "postgres")
            == "status IS NULL"
        )
        assert (
            _format_filter_sql(MetricFilter("status", "neq", "archived"), "postgres")
            == "status <> 'archived'"
        )
        assert (
            _format_filter_sql(MetricFilter("status", "neq", None), "postgres")
            == "status IS NOT NULL"
        )
        assert (
            _format_filter_sql(MetricFilter("amount", "gt", 100), "postgres")
            == "amount > 100"
        )
        assert (
            _format_filter_sql(MetricFilter("amount", "gte", 50), "postgres")
            == "amount >= 50"
        )
        assert (
            _format_filter_sql(MetricFilter("amount", "lt", 10), "postgres")
            == "amount < 10"
        )
        assert (
            _format_filter_sql(MetricFilter("amount", "lte", 5), "postgres")
            == "amount <= 5"
        )
        assert (
            _format_filter_sql(
                MetricFilter("tier", "in", ["gold", "platinum"]), "postgres"
            )
            == "tier IN ('gold', 'platinum')"
        )
        assert (
            _format_filter_sql(
                MetricFilter("tier", "not_in", ["free", "trial"]), "postgres"
            )
            == "tier NOT IN ('free', 'trial')"
        )
        assert (
            _format_filter_sql(MetricFilter("deleted_at", "is_null", None), "postgres")
            == "deleted_at IS NULL"
        )
        assert (
            _format_filter_sql(
                MetricFilter("deleted_at", "is_not_null", None), "postgres"
            )
            == "deleted_at IS NOT NULL"
        )
        assert (
            _format_filter_sql(MetricFilter("code", "other", 42), "postgres")
            == "code = 42"
        )

    def test_expand_metric_sql_unfiltered(self):
        m = MetricDefinition(
            name="sales", title="Sales", sql_expression="amount", aggregation="sum"
        )
        assert expand_metric_sql(m, "postgres") == "SUM(amount)"
        assert expand_metric_sql(m, "mysql") == "SUM(amount)"

    def test_expand_metric_sql_filtered_postgres_filter_clause(self):
        m = MetricDefinition(
            name="active_mrr",
            title="Active MRR",
            sql_expression="mrr",
            aggregation="sum",
            filters=[MetricFilter("status", "eq", "active")],
        )
        # Postgres supports FILTER (WHERE ...)
        sql = expand_metric_sql(m, "postgres")
        assert sql == "SUM(mrr) FILTER (WHERE status = 'active')"

        # DuckDB supports FILTER (WHERE ...)
        sql_duck = expand_metric_sql(m, "duckdb")
        assert sql_duck == "SUM(mrr) FILTER (WHERE status = 'active')"

    def test_expand_metric_sql_filtered_mysql_case_clause(self):
        m = MetricDefinition(
            name="active_mrr",
            title="Active MRR",
            sql_expression="mrr",
            aggregation="sum",
            filters=[MetricFilter("status", "eq", "active")],
        )
        sql = expand_metric_sql(m, "mysql")
        assert sql == "SUM(CASE WHEN status = 'active' THEN mrr ELSE NULL END)"

    def test_expand_count_distinct_metric(self):
        m = MetricDefinition(
            name="uniq_users",
            title="Unique Users",
            sql_expression="user_id",
            aggregation="count_distinct",
            filters=[MetricFilter("tier", "neq", "free")],
        )
        assert (
            expand_metric_sql(m, "postgres")
            == "COUNT(DISTINCT user_id) FILTER (WHERE tier <> 'free')"
        )
        assert (
            expand_metric_sql(m, "mysql")
            == "COUNT(DISTINCT CASE WHEN tier <> 'free' THEN user_id ELSE NULL END)"
        )

        # Unfiltered count distinct
        m_unfilt = MetricDefinition(
            name="uniq", title="Uniq", sql_expression="id", aggregation="count_distinct"
        )
        assert expand_metric_sql(m_unfilt, "postgres") == "COUNT(DISTINCT id)"

    def test_expand_custom_metric(self):
        m = MetricDefinition(
            name="custom_ratio",
            title="Ratio",
            sql_expression="SUM(a) / NULLIF(SUM(b), 0)",
            aggregation="custom",
            filters=[MetricFilter("x", "gt", 0)],
        )
        assert (
            expand_metric_sql(m, "postgres")
            == "CASE WHEN x > 0 THEN (SUM(a) / NULLIF(SUM(b), 0)) ELSE NULL END"
        )

        m_raw = MetricDefinition(
            name="raw", title="Raw", sql_expression="1 + 1", aggregation="custom"
        )
        assert expand_metric_sql(m_raw, "postgres") == "(1 + 1)"

    def test_expand_time_grain_sql_all_dialects(self):
        # Postgres / DuckDB / Snowflake
        assert (
            expand_time_grain_sql("created_at", "month", "postgres")
            == "DATE_TRUNC('month', created_at)"
        )
        assert (
            expand_time_grain_sql("created_at", "day", "duckdb")
            == "DATE_TRUNC('day', created_at)"
        )
        assert (
            expand_time_grain_sql("created_at", "year", "snowflake")
            == "DATE_TRUNC('year', created_at)"
        )

        # BigQuery
        assert (
            expand_time_grain_sql("ts", "quarter", "bigquery")
            == "DATE_TRUNC(ts, QUARTER)"
        )

        # SQLite
        assert "STRFTIME" in expand_time_grain_sql("ts", "month", "sqlite")
        assert "STRFTIME" in expand_time_grain_sql("ts", "day", "sqlite")

        # MySQL
        assert "DATE_FORMAT" in expand_time_grain_sql("ts", "month", "mysql")

        # MSSQL
        assert expand_time_grain_sql("ts", "month", "mssql") == "DATETRUNC(month, ts)"

        # Oracle
        assert expand_time_grain_sql("ts", "month", "oracle") == "TRUNC(ts, 'MM')"

        # Unsupported grain
        with pytest.raises(SemanticError, match="Unsupported time grain"):
            expand_time_grain_sql("ts", "millennium", "postgres")


class TestCompilerSemanticIntegration:
    def setup_method(self):
        reset_global_semantic_registry()

    def test_compile_metric_in_column_projection(self):
        spec = {
            "table": "subscriptions",
            "columns": [
                {"column": "plan_id"},
                {
                    "column": "revenue",
                    "metric": {
                        "name": "mrr",
                        "title": "MRR",
                        "sql": "amount_cents / 100.0",
                        "aggregation": "sum",
                        "filters": [
                            {"field": "status", "operator": "eq", "value": "active"}
                        ],
                    },
                    "alias": "active_mrr",
                },
            ],
        }
        compiler = QueryCompiler(spec, dialect="postgres")
        sql, params, _, _ = compiler.compile()
        assert "active_mrr" in sql
        assert "SUM(amount_cents / 100.0) FILTER (WHERE status = 'active')" in sql
        assert "GROUP BY" in sql

    def test_compile_time_grain_column(self):
        spec = {
            "table": "orders",
            "columns": [
                {"column": "created_at", "time_grain": "month", "alias": "order_month"},
                {"column": "total", "agg": "sum", "alias": "gross_sum"},
            ],
        }
        compiler = QueryCompiler(spec, dialect="postgres")
        sql, params, _, _ = compiler.compile()
        assert 'DATE_TRUNC(\'month\', "t1"."created_at") AS "order_month"' in sql
        assert 'GROUP BY DATE_TRUNC(\'month\', "t1"."created_at")' in sql

    def test_compile_with_semantic_model_and_top_level_metrics(self):
        semantic_model = SemanticModel(
            name="sales",
            table_name="sales_records",
            metrics=[
                MetricDefinition(
                    name="total_sales",
                    title="Total",
                    sql_expression="amount",
                    aggregation="sum",
                )
            ],
        )
        spec = {
            "table": "sales_records",
            "columns": ["region"],
            "metrics": ["total_sales"],
            "semantic_model": semantic_model.to_dict(),
        }
        compiler = QueryCompiler(spec, dialect="postgres")
        sql, params, _, _ = compiler.compile()
        assert 'SUM(amount) AS "total_sales"' in sql
        assert 'GROUP BY "t1"."region"' in sql

    def test_validate_time_grain_and_metrics_in_spec(self):
        spec_bad_grain = {
            "table": "users",
            "columns": [{"column": "created_at", "time_grain": "century"}],
        }
        with pytest.raises(ValidationError, match="Unsupported time grain"):
            QueryCompiler(spec_bad_grain)

        spec_bad_metrics = {
            "table": "users",
            "metrics": "not_a_list",
        }
        with pytest.raises(ValidationError, match="Field 'metrics' must be a list"):
            QueryCompiler(spec_bad_metrics)


class TestSemanticEdgeCasesAndCoverage:
    def test_load_semantic_models_from_empty_dict(self):
        models = load_semantic_models_from_dict({})
        assert models == []

        # non-dict in items
        models2 = load_semantic_models_from_dict({"models": ["not_a_dict"]})
        assert models2 == []

        # unattached lines and line without colon in fallback yaml
        content = "unattached_line\nmodels:\n  - name: x\n    line_without_colon\n"
        models3 = load_semantic_models_from_dict(parse_simple_yaml_or_json(content))
        assert len(models3) == 1

    def test_model_from_dict_non_dict_items(self):
        sm = SemanticModel.from_dict(
            {
                "name": "edge",
                "dimensions": ["not_a_dict"],
                "metrics": ["not_a_dict"],
            }
        )
        assert len(sm.dimensions) == 0
        assert len(sm.metrics) == 0

    def test_registry_metric_with_existing_table(self):
        reg = SemanticRegistry()
        m = MetricDefinition(
            name="custom_m", title="Custom", sql_expression="x", table="custom_table"
        )
        sm = SemanticModel(name="test_model", table_name="default_table", metrics=[m])
        reg.register_model(sm)
        assert reg.get_metric("custom_m").table == "custom_table"

    def test_fallback_yaml_parser_without_yaml_module(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "yaml":
                raise ImportError("No module named yaml")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        content = """
# Header comment
models:
  - name: fallback_revenue
    table: sales
    description: Fallback revenue
    metrics:
      - name: mrr
        sql: amount
        aggregation: sum
    dimensions:
      - name: date
        sql: created_at
"""
        res = parse_simple_yaml_or_json(content)
        models = load_semantic_models_from_dict(res)
        assert len(models) == 1
        assert models[0].name == "fallback_revenue"
        assert models[0].table_name == "sales"
        assert models[0].description == "Fallback revenue"
        assert len(models[0].metrics) == 1
        assert len(models[0].dimensions) == 1

    def test_yaml_returns_list_or_non_dict(self, monkeypatch):
        class FakeYaml:
            @staticmethod
            def safe_load(content):
                if content == "list_doc":
                    return [{"name": "from_list", "table": "tbl"}]
                elif content == "dict_doc":
                    return {"models": [{"name": "from_dict_yaml", "table": "tbl"}]}
                return 12345

        import sys

        sys.modules["yaml"] = FakeYaml()
        try:
            res_dict = parse_simple_yaml_or_json("dict_doc")
            assert "models" in res_dict
            assert res_dict["models"][0]["name"] == "from_dict_yaml"

            res1 = parse_simple_yaml_or_json("list_doc")
            assert "models" in res1
            assert res1["models"][0]["name"] == "from_list"

            res2 = parse_simple_yaml_or_json("scalar_doc")
            assert res2 == {}
        finally:
            del sys.modules["yaml"]

    def test_format_filter_sql_scalar_in_and_fallback_dialect(self):
        # scalar IN and NOT IN
        assert (
            _format_filter_sql(MetricFilter("id", "in", "SELECT id FROM v"), "postgres")
            == "id IN (SELECT id FROM v)"
        )
        assert (
            _format_filter_sql(
                MetricFilter("id", "not_in", "SELECT id FROM v"), "postgres"
            )
            == "id NOT IN (SELECT id FROM v)"
        )

        # Fallback dialect for time grain
        assert (
            expand_time_grain_sql("col", "day", "exotic_db") == "DATE_TRUNC('day', col)"
        )
