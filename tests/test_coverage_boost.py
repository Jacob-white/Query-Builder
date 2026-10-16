"""
Comprehensive coverage boost tests covering branches and edge cases across:
- query_builder.__init__ (PEP 562 lazy loading, __dir__, __getattr__)
- query_builder.nlq.prompt (serialize_schema_for_prompt semantic models and metrics)
- query_builder.models (QuerySpec, JoinSpec, FilterSpec, OrderBySpec, json_schema strict)
- query_builder.mcp_server (locked connection, resources/read, error branches)
- query_builder.integrations.django (_is_tenant_isolation_active, validation errors)
- query_builder.integrations.fastapi (_is_tenant_isolation_active payload structures)
- query_builder.policy (sensitive_column_patterns in expressions, CLAC expressions, CTEs)
- query_builder.semantic (expand_metrics_and_dimensions across dimensions, metrics, filters, having, order_by)
- query_builder.nlq.validator (DISTINCT_COUNT, expressions, time_grain, paren grouping)
- query_builder.ai.self_healing (fuzzy join tables/cols, order_by prefixes, window partitions)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

import query_builder
from query_builder.exceptions import SecurityError
from query_builder.models import (
    FilterSpec,
    JoinSpec,
    OrderBySpec,
    QuerySpec,
)
from query_builder.policy import SecurityPolicy, TenantContext, apply_security_policy
from query_builder.semantic import (
    DimensionDefinition,
    MetricDefinition,
    SemanticModel,
    SemanticRegistry,
    expand_metrics_and_dimensions,
)


def test_init_getattr_and_dir() -> None:
    # Test __getattr__ for dialects
    sqlite_dialect = query_builder.__getattr__("SQLiteDialect")
    assert sqlite_dialect is not None

    # Test __getattr__ for connectors
    sqlite_conn = query_builder.__getattr__("SQLiteConnector")
    assert sqlite_conn is not None

    # Test __getattr__ for introspect helpers
    introspect_fn = query_builder.__getattr__("introspect_sqlite")
    assert callable(introspect_fn)

    # Test __getattr__ for unknown attributes
    with pytest.raises(AttributeError):
        query_builder.__getattr__("NonExistentAttributeXYZ")

    # Test __dir__
    all_symbols = dir(query_builder)
    assert "FluentQuery" in all_symbols
    assert "query" in all_symbols
    assert "QueryCompiler" in all_symbols


def test_nlq_prompt_semantic_serialization() -> None:
    from query_builder.nlq.prompt import serialize_schema_for_prompt

    # Empty registry
    empty_reg = SemanticRegistry()
    assert "\nSemantic Metrics & Dimensions:" not in serialize_schema_for_prompt(
        {"tables": {}}, semantic=empty_reg
    )

    # Populated registry with model and standalone metrics
    reg = SemanticRegistry()
    model = SemanticModel(
        name="sales",
        table_name="orders",
        metrics=[
            MetricDefinition(
                name="total_revenue",
                title="Total Revenue",
                sql_expression="amount",
                aggregation="SUM",
                description="Sum of completed sales revenue",
            ),
            MetricDefinition(
                name="order_count",
                title="Order Count",
                sql_expression="id",
                aggregation="COUNT",
            ),
        ],
        dimensions=[
            DimensionDefinition(
                name="region",
                title="Sales Region",
                sql_expression="region_code",
                data_type="string",
                description="Geographic region",
            ),
            DimensionDefinition(
                name="year",
                title="Order Year",
                sql_expression="EXTRACT(YEAR FROM created_at)",
                data_type="integer",
            ),
        ],
    )
    reg.register_model(model)
    reg._metrics_by_name["standalone_users"] = MetricDefinition(
        name="standalone_users",
        title="Active Users",
        sql_expression="id",
        aggregation="COUNT",
        table="users",
        description="Active user count",
    )

    out = serialize_schema_for_prompt({"tables": {}}, semantic=reg)
    assert "Semantic Metrics & Dimensions:" in out
    assert "Model `sales` (Table: `orders`):" in out
    assert (
        "Metric `total_revenue`: Total Revenue [sum over `amount`] - Sum of completed sales revenue"
        in out
    )
    assert "Metric `order_count`: Order Count [count over `id`]" in out
    assert (
        "Dimension `region`: Sales Region [`region_code` (string)] - Geographic region"
        in out
    )
    assert (
        "Dimension `year`: Order Year [`EXTRACT(YEAR FROM created_at)` (integer)]"
        in out
    )
    assert (
        "Metric `standalone_users`: Active Users [count over `id` on `users`] - Active user count"
        in out
    )


def test_models_dataclasses_and_schema() -> None:
    # QuerySpec builder
    builder = QuerySpec.builder("customers")
    assert builder is not None

    # QuerySpec json_schema strict
    schema_strict = QuerySpec.json_schema(strict=True)
    assert schema_strict.get("additionalProperties") is False

    schema_loose = QuerySpec.json_schema(strict=False)
    assert "additionalProperties" not in schema_loose

    # JoinSpec camelCase and to_dict
    join = JoinSpec(
        table="orders",
        type="INNER",
        leftTable="customers",
        leftCol="id",
        rightCol="customer_id",
        alias="o",
        id="j1",
    )
    assert join.left_table == "customers"
    assert join.left_col == "id"
    assert join.right_col == "customer_id"
    d_join = join.to_dict()
    assert d_join["left_table"] == "customers"
    assert d_join["alias"] == "o"
    assert d_join["id"] == "j1"

    # FilterSpec camelCase, combiners, parenOpen/parenClose, subquery, id
    flt = FilterSpec(
        column="status",
        op="eq",
        value="active",
        tablePrefix="o",
        paren_open=True,
        paren_close=True,
        combiner="or",
        id="f1",
        table="orders",
        subquery={"table": "archive", "columns": ["id"]},
    )
    assert flt.table_prefix == "o"
    assert flt.parenOpen is True
    assert flt.parenClose is True
    assert flt.combiner == "OR"
    d_flt = flt.to_dict()
    assert d_flt["table_prefix"] == "o"
    assert d_flt["combiner"] == "OR"
    assert d_flt["id"] == "f1"
    assert d_flt["table"] == "orders"
    assert d_flt["parenOpen"] is True
    assert d_flt["parenClose"] is True
    assert d_flt["subquery"] == {"table": "archive", "columns": ["id"]}

    # OrderBySpec camelCase tablePrefix
    ob = OrderBySpec(column="amount", direction="desc", tablePrefix="o")
    assert ob.table_prefix == "o"
    assert ob.to_dict()["table_prefix"] == "o"

    # QuerySpec with metrics and semantic models
    qs = QuerySpec(
        table="customers",
        columns=["id", "name"],
        metrics=["total_revenue"],
        semantic_model={"name": "cust_model"},
        semantic_models=[{"name": "orders_model"}],
    )
    qs_dict = qs.to_dict()
    assert qs_dict["metrics"] == ["total_revenue"]
    assert qs_dict["semantic_model"] == {"name": "cust_model"}
    assert qs_dict["semantic_models"] == [{"name": "orders_model"}]


def test_mcp_server_branches() -> None:
    from query_builder.mcp_server import McpServer

    # 1. Test lock_connection mode
    server = McpServer(
        lock_connection=True,
        connector="sqlite",
        connector_config={"database": ":memory:"},
    )
    tools = server.get_tools()
    for t in tools:
        if t["name"] in ("query_builder_introspect", "query_builder_execute"):
            props = t["inputSchema"].get("properties", {})
            assert "connector" not in props
            assert "config" not in props

    # Trying to specify connector or config in locked mode raises SecurityError
    with pytest.raises(SecurityError):
        server._dispatch_tool(
            "query_builder_execute",
            {"spec": {"table": "users"}, "connector": "postgres"},
        )

    with pytest.raises(SecurityError):
        server._dispatch_tool(
            "query_builder_introspect",
            {"config": {"host": "localhost"}},
        )

    # 2. Test raw SQL forbidden with tenant context in MCP execute
    sec_server = McpServer(
        tenant_context=TenantContext(tenant_id="tenant_123"),
    )
    with pytest.raises(SecurityError):
        sec_server._dispatch_tool(
            "query_builder_execute",
            {"sql": "SELECT * FROM users"},
        )

    # 3. Test resources/read semantic metrics
    reg = SemanticRegistry()
    reg._metrics_by_name["m1"] = MetricDefinition(
        name="m1", title="M1", sql_expression="col", aggregation="SUM"
    )
    sem_server = McpServer(semantic_registry=reg)
    res = sem_server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": {"uri": "query-builder://semantic/metrics"},
        }
    )
    assert res is not None
    assert "m1" in res["result"]["contents"][0]["text"]

    # 4. Unknown resource
    err_res = sem_server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "resources/read",
            "params": {"uri": "query-builder://unknown/res"},
        }
    )
    assert err_res is not None
    assert "error" in err_res


def test_fastapi_tenant_isolation_active_variants() -> None:
    from query_builder.integrations.fastapi import _is_tenant_isolation_active

    # 1. Payload with tenant_id
    assert _is_tenant_isolation_active(None, None, {"tenant_id": "t1"}) is True

    # 2. Payload with context dict containing tenant_id
    assert (
        _is_tenant_isolation_active(None, None, {"context": {"tenant_id": "t1"}})
        is True
    )

    # 3. Payload with policy dict containing enforce_tenant_isolation
    assert (
        _is_tenant_isolation_active(
            None, None, {"policy": {"enforce_tenant_isolation": True}}
        )
        is True
    )

    # 4. Object payload with model_extra
    class MockModelExtra:
        def __init__(self, extra: dict[str, Any]) -> None:
            self.model_extra = extra

    assert (
        _is_tenant_isolation_active(None, None, MockModelExtra({"tenant_id": "t2"}))
        is True
    )
    assert (
        _is_tenant_isolation_active(
            None, None, MockModelExtra({"context": {"tenant_id": "t3"}})
        )
        is True
    )
    assert (
        _is_tenant_isolation_active(
            None, None, MockModelExtra({"policy": {"enforce_tenant_isolation": True}})
        )
        is True
    )

    # 5. Clean payload without tenant isolation
    assert _is_tenant_isolation_active(None, None, {}) is False


def test_django_tenant_isolation_active_variants() -> None:
    from query_builder.integrations.django import _is_tenant_isolation_active

    # 1. Payload with tenant_id
    assert _is_tenant_isolation_active(None, None, {"tenant_id": "t1"}) is True

    # 2. Payload with context dict containing tenant_id
    assert (
        _is_tenant_isolation_active(None, None, {"context": {"tenant_id": "t1"}})
        is True
    )

    # 3. Payload with policy dict containing enforce_tenant_isolation
    assert (
        _is_tenant_isolation_active(
            None, None, {"policy": {"enforce_tenant_isolation": True}}
        )
        is True
    )

    # 4. Clean payload
    assert _is_tenant_isolation_active(None, None, {}) is False


def test_policy_sensitive_column_patterns_in_expression() -> None:
    # Expression referencing column matching pattern should raise SecurityError
    policy = SecurityPolicy(
        sensitive_column_patterns=[r"^ssn_", r"_secret$"],
        column_masking={"users": ["api_key"]},
    )
    context = TenantContext(tenant_id="t1", roles=["analyst"])

    spec = {
        "table": "users",
        "columns": [
            {
                "expression": "UPPER(ssn_number)",
                "alias": "upper_ssn",
            }
        ],
    }
    with pytest.raises(SecurityError) as exc:
        apply_security_policy(spec, context=context, policy=policy)
    assert "Access to masked column 'ssn_number' in expression is forbidden." in str(
        exc.value
    )

    # CLAC check on expression
    clac_policy = SecurityPolicy(
        column_permissions={
            "users": {
                "allowed_roles": ["admin"],
                "restricted_columns": ["salary"],
            }
        }
    )
    clac_spec = {
        "table": "users",
        "columns": [
            {
                "expression": "salary * 1.1",
                "alias": "raised_salary",
            }
        ],
    }
    with pytest.raises(SecurityError) as exc:
        apply_security_policy(clac_spec, context=context, policy=clac_policy)
    assert "Access to restricted column 'salary'" in str(exc.value)


def test_semantic_expand_metrics_and_dimensions_coverage() -> None:
    reg = SemanticRegistry()
    model = SemanticModel(
        name="sales",
        table_name="orders",
        metrics=[
            MetricDefinition(
                name="rev",
                title="Revenue",
                sql_expression="amount",
                aggregation="SUM",
            )
        ],
        dimensions=[
            DimensionDefinition(
                name="reg",
                title="Region",
                sql_expression="region_code",
                data_type="string",
            )
        ],
    )
    reg.register_model(model)
    reg._metrics_by_name["total_orders"] = MetricDefinition(
        name="total_orders",
        title="Total Orders",
        sql_expression="id",
        aggregation="COUNT",
        table="orders",
    )

    # None registry returns spec dict copy
    assert expand_metrics_and_dimensions({"table": "orders"}, None) == {
        "table": "orders"
    }

    # Projections with string dimension, dict metric, dict dimension
    spec = {
        "table": "orders",
        "columns": [
            "reg",
            {"metric": "total_orders", "alias": "order_cnt"},
            {"column": "reg", "alias": "r"},
            "other_col",
            123,  # non-str non-dict
        ],
        "filters": [
            {"column": "reg", "op": "eq", "value": "NA"},
            "non_dict_filter",
        ],
        "having": [
            {"column": "rev", "op": "gt", "value": 1000},
            "non_dict_having",
        ],
        "order_by": [
            {"column": "reg", "direction": "asc"},
            "non_dict_order",
        ],
    }
    expanded = expand_metrics_and_dimensions(spec, reg)

    # Check columns
    cols = expanded["columns"]
    assert cols[0] == {
        "raw_expression": "region_code",
        "alias": "reg",
        "dimension": "reg",
    }
    assert cols[1] == {
        "raw_expression": "COUNT(id)",
        "alias": "order_cnt",
        "metric": "total_orders",
    }
    assert cols[2] == {
        "raw_expression": "region_code",
        "alias": "r",
        "dimension": "reg",
    }
    assert cols[3] == "other_col"
    assert cols[4] == 123

    # Check filters
    assert expanded["filters"][0]["column"] == "region_code"
    assert expanded["filters"][1] == "non_dict_filter"

    # Check having
    assert expanded["having"][0]["column"] == "amount"
    assert expanded["having"][0]["agg"] == "sum"
    assert expanded["having"][1] == "non_dict_having"

    # Check order_by
    assert expanded["order_by"][0]["column"] == "region_code"
    assert expanded["order_by"][1] == "non_dict_order"


def test_nlq_validator_branches() -> None:
    from query_builder.nlq.validator import NlqAstValidator

    validator = NlqAstValidator({"tables": {"users": {"columns": ["id", "name"]}}})

    raw_ast = {
        "table": "users",
        "columns": [
            {
                "column": "id",
                "agg": "DISTINCT_COUNT",
                "dimension": "dim_id",
                "time_grain": "day",
                "grain": "daily",
                "table": "users",
                "tablePrefix": "u",
                "distinct": True,
            }
        ],
        "filters": [
            {
                "column": "name",
                "op": "=",
                "value": "Alice",
                "table": "users",
                "tablePrefix": "u",
                "parenOpen": True,
                "parenClose": True,
                "subquery": {"table": "banned", "columns": ["name"]},
                "id": "f_1",
            }
        ],
        "order_by": [
            {
                "column": "id",
                "direction": "DESC",
                "tablePrefix": "u",
            }
        ],
        "metrics": ["m1"],
        "ctes": [{"name": "cte1", "query": {"table": "t1"}}],
    }

    res, warnings = validator.validate(raw_ast)
    assert res["table"] == "users"
    col = res["columns"][0]
    assert col["agg"] == "count_distinct"
    assert col["dimension"] == "dim_id"
    assert col["time_grain"] == "day"
    assert col["grain"] == "daily"
    assert col["table"] == "users"
    assert col["tablePrefix"] == "u"
    assert col["distinct"] is True

    flt = res["filters"][0]
    assert flt["table"] == "users"
    assert flt["tablePrefix"] == "u"
    assert flt["parenOpen"] is True
    assert flt["parenClose"] is True
    assert flt["id"] == "f_1"
    assert flt["subquery"] == {"table": "banned", "columns": ["name"]}

    assert res["order_by"][0]["tablePrefix"] == "u"
    assert res["metrics"] == ["m1"]
    assert len(res["ctes"]) == 1


def test_self_healing_advanced_branches() -> None:
    from query_builder.ai.self_healing import SelfHealingQueryEngine

    schema = {
        "tables": {
            "customers": {"columns": ["id", "name", "city"]},
            "orders": {"columns": ["id", "customer_id", "amount", "created_at"]},
        }
    }
    engine = SelfHealingQueryEngine(schema)

    raw_spec = {
        "table": "customerz",  # typo
        "columns": [
            {"column": "nam"},  # typo in customers.name
            "amount",  # cross-table resolution to orders.amount
            123,  # non-dict non-str
        ],
        "filters": [
            {
                "tablePrefix": "orderz",  # typo
                "column": "orderz.amount",
                "op": "equals",  # synonym
                "value": 100,
            },
            "non_dict_filter",
        ],
        "having": [
            {"column": "amount", "op": "greater_than", "value": 50},  # synonym
            "non_dict_having",
        ],
        "order_by": [
            {
                "tablePrefix": "orderz",  # typo
                "column": "amount",
                "direction": "desc",
            }
        ],
        "joins": [
            {
                "table": "orderz",  # typo
                "left_table": "customerz",  # typo
                "left_col": "idx",  # typo for id
                "right_col": "cust_id",  # typo for customer_id
            }
        ],
        "window_functions": [
            {
                "function": "ROW_NUMBER",
                "partition_by": ["customerz.nam"],  # typo in partition col
            }
        ],
    }

    healed, notes = engine.auto_heal(raw_spec)
    assert healed["table"] == "customers"
    assert any("nam" in n for n in notes)
    assert any("orderz" in n for n in notes)


def test_ast_validator_split_from_and_token_ceiling() -> None:
    from query_builder.ast_validator import _split_from_items, validate_sql_ast

    items = _split_from_items('"orders", `customers`, [archive], (SELECT 1) AS sub')
    assert len(items) == 4
    assert items[0] == '"orders"'
    assert items[1] == "`customers`"
    assert items[2] == "[archive]"

    # Token ceiling test
    res = validate_sql_ast("SELECT a, b, c, d FROM orders", max_ast_tokens=3)
    assert not res["valid"]
    assert any("exceeds safety threshold" in v for v in res["violations"])


def test_validate_cte_dag_and_window_specs() -> None:
    from query_builder.ast_validator import (
        validate_cte_dag,
        validate_window_function_spec,
    )

    # Empty CTE list
    assert validate_cte_dag([])["valid"] is True

    # Invalid CTE name, duplicate name, missing name
    invalid_ctes = [
        {"name": "valid_cte", "query": {"table": "users"}},
        {"name": "invalid-cte-name", "query": {"table": "orders"}},
        {"name": "valid_cte", "query": {"table": "customers"}},  # duplicate
        {"name": "", "query": {"table": "logs"}},  # empty
    ]
    res_ctes = validate_cte_dag(invalid_ctes)
    assert not res_ctes["valid"]

    # Circular CTE dependency and self-reference without recursive
    circular_ctes = [
        {"name": "cte_a", "query": {"table": "cte_b"}},
        {"name": "cte_b", "query": {"table": "cte_a"}},
        {"name": "self_cte", "query": {"table": "self_cte"}, "recursive": False},
    ]
    circ_res = validate_cte_dag(circular_ctes)
    assert not circ_res["valid"]
    assert any("Circular dependency" in v for v in circ_res["violations"])
    assert any("must be marked as recursive" in v for v in circ_res["violations"])

    # Window function validator checks
    assert not validate_window_function_spec({})["valid"]
    assert not validate_window_function_spec({"function": "NON_EXISTENT_WINDOW_FN"})[
        "valid"
    ]
    assert not validate_window_function_spec(
        {"function": "ROW_NUMBER", "frame": {"frame_type": "INVALID_FRAME"}}
    )["valid"]
    assert not validate_window_function_spec(
        {
            "function": "ROW_NUMBER",
            "frame": {"start": "UNBOUNDED FOLLOWING", "frame_type": "ROWS"},
        }
    )["valid"]
    assert not validate_window_function_spec(
        {
            "function": "ROW_NUMBER",
            "frame": {"start": "CURRENT ROW", "end": "UNBOUNDED PRECEDING"},
        }
    )["valid"]
    assert not validate_window_function_spec(
        {
            "function": "ROW_NUMBER",
            "frame": {"start": "1 FOLLOWING", "end": "1 PRECEDING"},
        }
    )["valid"]
    assert not validate_window_function_spec(
        {
            "function": "ROW_NUMBER",
            "frame": {"start": "CURRENT ROW", "end": "1 PRECEDING"},
        }
    )["valid"]


def test_django_new_views_validation_and_errors() -> None:
    from django.http import HttpRequest

    from query_builder.integrations.django import create_django_urls

    mock_conn = MagicMock()
    mock_conn.dialect_name = "sqlite"
    mock_conn.introspect_schema.return_value = {
        "tables": {"users": {"columns": ["id", "name"]}}
    }

    views = create_django_urls(mock_conn)
    # views: schema_view, introspect_view, capabilities_view, compile_view, validate_view,
    # execute_view, export_view, export_stream_view, explain_view, join_path_view, nlq_view
    view_map = {p.name: p.callback for p in views}

    # 1. explain_view method check & missing table
    req_get = HttpRequest()
    req_get.method = "GET"
    assert view_map["query-builder-explain"](req_get).status_code == 405

    req_post_empty = HttpRequest()
    req_post_empty.method = "POST"
    req_post_empty._body = b'{"spec": {}}'
    assert view_map["query-builder-explain"](req_post_empty).status_code == 400

    # 2. join_path_view method check & missing args
    assert view_map["query-builder-join-path"](req_get).status_code == 405
    req_join_empty = HttpRequest()
    req_join_empty.method = "POST"
    req_join_empty._body = b"{}"
    assert view_map["query-builder-join-path"](req_join_empty).status_code == 400

    # 3. nlq_view method check & empty prompt
    assert view_map["query-builder-nlq"](req_get).status_code == 405
    req_nlq_empty = HttpRequest()
    req_nlq_empty.method = "POST"
    req_nlq_empty._body = b'{"prompt": ""}'
    assert view_map["query-builder-nlq"](req_nlq_empty).status_code == 400

    # 4. export_stream_view method check & missing source
    assert view_map["query-builder-export-stream"](req_get).status_code == 405
    req_exp_empty = HttpRequest()
    req_exp_empty.method = "POST"
    req_exp_empty._body = b"{}"
    assert view_map["query-builder-export-stream"](req_exp_empty).status_code == 400


def test_django_tenant_isolation_active_extra_branches() -> None:
    from query_builder.integrations.django import _is_tenant_isolation_active

    class MockContext:
        tenant_id = "t_obj"

    class MockPolicy:
        enforce_tenant_isolation = True

    assert _is_tenant_isolation_active(None, None, {"context": MockContext()}) is True
    assert _is_tenant_isolation_active(None, None, {"policy": MockPolicy()}) is True


def test_django_views_raw_sql_security_and_validation() -> None:
    from django.http import HttpRequest

    from query_builder.integrations.django import create_django_urls

    mock_conn = MagicMock()
    mock_conn.dialect_name = "sqlite"
    views = create_django_urls(mock_conn)
    view_map = {p.name: p.callback for p in views}

    # execute_view non-string sql
    req_bad_sql = HttpRequest()
    req_bad_sql.method = "POST"
    req_bad_sql._body = b'{"sql": 123}'
    res = view_map["query-builder-execute"](req_bad_sql)
    assert res.status_code == 400

    # execute_view invalid AST sql
    req_unsafe_sql = HttpRequest()
    req_unsafe_sql.method = "POST"
    req_unsafe_sql._body = b'{"sql": "DROP TABLE users;"}'
    res = view_map["query-builder-execute"](req_unsafe_sql)
    assert res.status_code == 403

    # export_view invalid AST sql
    req_unsafe_exp = HttpRequest()
    req_unsafe_exp.method = "POST"
    req_unsafe_exp._body = b'{"sql": "DROP TABLE users;"}'
    res = view_map["query-builder-export"](req_unsafe_exp)
    assert res.status_code == 403

    # export_stream_view with spec and tenant context
    req_stream = HttpRequest()
    req_stream.method = "POST"
    req_stream._body = b'{"spec": {"table": "users", "columns": ["id"]}}'
    mock_conn.execute.return_value = {"rows": [{"id": 1}], "columns": ["id"]}
    urls_with_tenant = create_django_urls(
        mock_conn,
        tenant_resolver=lambda r: TenantContext(tenant_id="tenant_123"),
    )
    stream_map = {p.name: p.callback for p in urls_with_tenant}
    res_stream = stream_map["query-builder-export-stream"](req_stream)
    assert res_stream.status_code == 200


def test_drf_views_security_and_validation() -> None:
    import rest_framework.exceptions

    from query_builder.integrations.django import create_drf_views

    mock_conn = MagicMock()
    mock_conn.dialect_name = "sqlite"
    views = create_drf_views(mock_conn)

    req = MagicMock()
    req.data = {"sql": "DROP TABLE users;"}
    with pytest.raises(rest_framework.exceptions.PermissionDenied):
        views["ExecuteView"]().post(req)

    with pytest.raises(rest_framework.exceptions.PermissionDenied):
        views["ExportView"]().post(req)

    # ExportView with stream
    req_stream = MagicMock()
    req_stream.data = {"rows": [{"a": 1}], "columns": ["a"], "stream": True}
    res = views["ExportView"]().post(req_stream)
    assert res.status_code == 200

    # ExplainView missing table
    req_exp = MagicMock()
    req_exp.data = {"spec": {}}
    with pytest.raises(rest_framework.exceptions.ValidationError):
        views["ExplainView"]().post(req_exp)

    # JoinPathView missing active_tables
    req_join = MagicMock()
    req_join.data = {}
    with pytest.raises(rest_framework.exceptions.ValidationError):
        views["JoinPathView"]().post(req_join)

    # NlqView empty prompt
    req_nlq = MagicMock()
    req_nlq.data = {"prompt": "  "}
    with pytest.raises(rest_framework.exceptions.ValidationError):
        views["NlqView"]().post(req_nlq)


def test_ninja_router_validation_types() -> None:
    from ninja.errors import HttpError

    from query_builder.integrations.django import create_ninja_router

    mock_conn = MagicMock()
    mock_conn.dialect_name = "sqlite"
    router = create_ninja_router(mock_conn)

    op_map = {
        (op.methods[0], path_str): op.view_func
        for path_str, ops in router.path_operations.items()
        for op in ops.operations
    }
    req = MagicMock()

    with pytest.raises(HttpError) as exc_info:
        op_map[("POST", "/execute")](req, payload={"sql": 123})
    assert exc_info.value.status_code == 400

    with pytest.raises(HttpError) as exc_info:
        op_map[("POST", "/export")](req, payload={"sql": 123})
    assert exc_info.value.status_code == 400


def test_policy_expression_parse_error_and_ctes_spec_objects() -> None:
    from query_builder.models import CteSpec, FilterSpec, SetOperationSpec
    from query_builder.policy import (
        _extract_columns_from_expression,
        apply_security_policy,
    )

    ctx = TenantContext(tenant_id="t1")

    # 1. Unparseable expression returns empty list (lines 159-160)
    assert _extract_columns_from_expression("SELECT (((", "users") == []

    # 2. CteSpec and SetOperationSpec objects in apply_security_policy (lines 265-266, 285-286)
    cte_obj = CteSpec(name="my_cte", query={"table": "orders", "columns": ["id"]})
    so_obj = SetOperationSpec(
        operation="union", query={"table": "archive", "columns": ["id"]}
    )
    spec = {
        "table": "users",
        "columns": ["id"],
        "ctes": [cte_obj],
        "set_operations": [so_obj],
    }
    res = apply_security_policy(
        spec,
        policy=SecurityPolicy(allowed_tables=["users", "orders", "archive"]),
        context=ctx,
    )
    assert res["ctes"][0].query["table"] == "orders"
    assert res["set_operations"][0].query["table"] == "archive"

    # 3. FilterSpec object with _enforced attribute cleaned (lines 388-394)
    flt_obj = FilterSpec(column="status", op="eq", value="active")
    flt_obj._enforced = True
    spec_flt = {
        "table": "users",
        "columns": ["id"],
        "filters": [flt_obj],
    }
    res_flt = apply_security_policy(
        spec_flt, policy=SecurityPolicy(allowed_tables=["users"]), context=ctx
    )
    assert not hasattr(res_flt["filters"][0], "_enforced")

    # 4. row_level_filters skips CTE tables (line 468)
    rls_spec = {
        "table": "my_cte",
        "columns": ["id"],
        "ctes": [{"name": "my_cte", "query": {"table": "users"}}],
    }
    rls_pol = SecurityPolicy(
        allowed_tables=["users", "my_cte"],
        row_level_filters={"my_cte": [{"column": "x", "op": "eq", "value": 1}]},
    )
    res_rls = apply_security_policy(rls_spec, policy=rls_pol, context=ctx)
    assert res_rls is not None

    # 5. Dict column projection without column or name key (line 567)
    no_col_spec = {
        "table": "users",
        "columns": [{"alias": "my_alias"}],
    }
    no_col_pol = SecurityPolicy(
        allowed_tables=["users"],
        column_permissions={
            "users": {"allowed_roles": ["admin"], "restricted_columns": ["salary"]}
        },
    )
    res_no_col = apply_security_policy(no_col_spec, policy=no_col_pol, context=ctx)
    assert res_no_col is not None


def test_pool_factory_error_and_closed_during_factory() -> None:
    import sqlite3

    from query_builder.pool import ConnectionPool, PoolClosedError

    # 1. Failing factory discards slot placeholder
    def failing_factory() -> Any:
        raise RuntimeError("db connection failed")

    pool = ConnectionPool(factory=failing_factory, max_size=2)
    with pytest.raises(RuntimeError):
        pool.acquire()
    assert pool.in_use_count == 0

    # 2. Pool closed during factory
    pool2 = ConnectionPool(factory=lambda: sqlite3.connect(":memory:"), max_size=2)

    def closing_factory() -> Any:
        pool2._closed = True
        return sqlite3.connect(":memory:")

    pool2.factory = closing_factory
    with pytest.raises(PoolClosedError):
        pool2.acquire()
    assert pool2.in_use_count == 0


@pytest.mark.asyncio
async def test_async_pool_factory_error_and_closed_during_factory() -> None:
    from query_builder.async_pool import AsyncConnectionPool, PoolClosedError

    # 1. Failing async factory discards slot placeholder
    async def failing_factory() -> Any:
        raise RuntimeError("async db connection failed")

    pool = AsyncConnectionPool(factory=failing_factory, max_size=2)
    with pytest.raises(RuntimeError):
        await pool.acquire()
    assert pool.in_use_count == 0

    # 2. Pool closed during async factory
    mock_conn = MagicMock()
    mock_conn.close = MagicMock()

    async def closing_factory() -> Any:
        pool2._closed = True
        return mock_conn

    pool2 = AsyncConnectionPool(factory=closing_factory, max_size=2)
    with pytest.raises(PoolClosedError):
        await pool2.acquire()
    assert pool2.in_use_count == 0
