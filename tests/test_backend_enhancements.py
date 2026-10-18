"""
Unit tests for backend bug fixes, security hardening, and feature enhancements.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import query_builder as qb
from query_builder.adapters import ColumnSchema, ForeignKey, TableSchema
from query_builder.advisor import recommend_indexes
from query_builder.cli import main as cli_main
from query_builder.compiler import QueryCompiler
from query_builder.exceptions import SecurityError, SpecColumnError, ValidationError
from query_builder.executor import execute_compiled_spec
from query_builder.explain import estimate_plan_from_spec
from query_builder.fluent import query
from query_builder.join_solver import find_best_join_condition
from query_builder.mcp_server import McpServer
from query_builder.models import (
    ColumnMeta,
    ForeignKeyMeta,
    OrderBySpec,
    QuerySpec,
    SchemaSnapshot,
    TableMeta,
)
from query_builder.parser import parse_sql_to_spec
from query_builder.policy import SecurityPolicy, TenantContext, apply_security_policy
from query_builder.schema_audit import audit_schema
from query_builder.security import apply_column_masking, calculate_ast_complexity
from query_builder.spec_check import check_columns


def _sample_snapshot() -> SchemaSnapshot:
    return SchemaSnapshot(
        tables={
            "users": TableMeta(
                name="users",
                comment="User accounts",
                columns=[
                    ColumnMeta(
                        name="id",
                        data_type="integer",
                        is_primary=True,
                        comment="Primary key",
                    ),
                    ColumnMeta(
                        name="email",
                        data_type="text",
                        comment="Email address",
                    ),
                    ColumnMeta(
                        name="tenant_id",
                        data_type="text",
                        comment="Tenant identifier",
                    ),
                ],
                has_user_id=False,
            ),
            "orders": TableMeta(
                name="orders",
                comment="Customer orders",
                columns=[
                    ColumnMeta(
                        name="order_pk",
                        data_type="integer",
                        is_primary=True,
                        comment="Order primary key",
                    ),
                    ColumnMeta(
                        name="user_id",
                        data_type="integer",
                        comment="Owner user ID",
                    ),
                    ColumnMeta(
                        name="amount",
                        data_type="numeric",
                        comment="Order total",
                    ),
                    ColumnMeta(
                        name="status",
                        data_type="text",
                        comment="Order status",
                    ),
                ],
                has_user_id=True,
            ),
        },
        foreign_keys=[
            ForeignKeyMeta(
                table="orders",
                column="user_id",
                foreign_table="users",
                foreign_column="id",
            )
        ],
    )


def test_spec_check_accepts_dataclasses_and_skips_raw_and_metrics() -> None:
    snap = _sample_snapshot()
    spec = QuerySpec(
        table="orders",
        columns=[
            "orders.amount",
            {"raw_expression": "orders.amount * 1.1", "alias": "with_tax"},
            {"metric": "total_revenue", "alias": "rev"},
        ],
    )
    # Valid columns + raw_expression + metric should pass
    check_columns(spec, snap)

    # Unknown column on QuerySpec + SchemaSnapshot should raise SpecColumnError
    bad_spec = QuerySpec(table="orders", columns=["orders.non_existent"])
    with pytest.raises(SpecColumnError) as exc_info:
        check_columns(bad_spec, snap)
    assert exc_info.value.table == "orders"

    # Also test Adapter TableSchema / ColumnSchema dataclasses
    adapter_schema = {
        "users": TableSchema(
            name="users",
            columns=[ColumnSchema(name="id", data_type="integer", is_primary=True)],
        )
    }
    check_columns(QuerySpec(table="users", columns=["users.id"]), adapter_schema)


def test_schema_audit_accepts_schema_snapshot_and_adapter_dataclasses() -> None:
    snap = _sample_snapshot()
    report = audit_schema(snap)
    assert report.tables == 2
    assert report.columns == 7
    assert report.missing_links == []
    assert report.undescribed_tables == []

    adapter_schema = {
        "users": TableSchema(
            name="users",
            columns=[ColumnSchema(name="id", data_type="integer", is_primary=True)],
        ),
        "posts": TableSchema(
            name="posts",
            columns=[
                ColumnSchema(name="id", data_type="integer", is_primary=True),
                ColumnSchema(name="user_id", data_type="integer"),
            ],
            foreign_keys=[
                ForeignKey(
                    table="posts",
                    column="user_id",
                    foreign_table="users",
                    foreign_column="id",
                )
            ],
        ),
    }
    report2 = audit_schema(adapter_schema)
    assert report2.tables == 2
    assert report2.missing_links == []


def test_compiler_parameter_order_alignment_with_case_when_and_isolation() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INT, tenant_id TEXT, amount REAL, status TEXT);"
    )
    conn.execute("INSERT INTO orders VALUES (1, 42, 't_acme', 600.0, 'PAID');")
    conn.execute("INSERT INTO orders VALUES (2, 42, 't_acme', 100.0, 'PAID');")
    conn.execute("INSERT INTO orders VALUES (3, 99, 't_other', 900.0, 'PAID');")

    schema = {
        "tables": {
            "orders": {
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "user_id", "data_type": "integer"},
                    {"name": "tenant_id", "data_type": "text"},
                    {"name": "amount", "data_type": "real"},
                    {"name": "status", "data_type": "text"},
                ],
                "has_user_id": True,
            }
        }
    }
    spec = {
        "table": "orders",
        "columns": [
            {
                "case_when": {
                    "branches": [
                        {
                            "condition": {
                                "column": "orders.amount",
                                "op": "gte",
                                "value": 500.0,
                            },
                            "then_value": "VIP",
                        }
                    ],
                    "else_value": "Regular",
                },
                "alias": "tier",
            },
            {"column": "orders.id", "agg": "COUNT", "alias": "cnt"},
        ],
        "filters": [{"column": "orders.status", "op": "eq", "value": "PAID"}],
        "tenant_id": "t_acme",
    }

    compiler = QueryCompiler(
        spec,
        schema=schema,
        user_id=42,
        force_user_filter=True,
        dialect="sqlite",
    )
    main_sql, main_params, count_sql, count_params = compiler.compile()

    rows = conn.execute(main_sql, main_params).fetchall()
    assert sorted(rows) == [("Regular", 1), ("VIP", 1)]

    total_groups = conn.execute(count_sql, count_params).fetchone()[0]
    assert total_groups == 2
    conn.close()


def test_compiler_derived_table_subquery_and_nulls_ordering() -> None:
    spec = {
        "table": {
            "subquery": {
                "table": "orders",
                "columns": ["id", "amount"],
                "filters": [{"column": "status", "op": "eq", "value": "PAID"}],
            },
            "alias": "paid_orders",
        },
        "columns": ["paid_orders.id", "paid_orders.amount"],
        "order_by": [
            {"column": "paid_orders.amount", "direction": "DESC", "nulls": "LAST"}
        ],
        "limit": None,
    }
    compiler = QueryCompiler(spec, dialect="postgres")
    sql, params, count_sql, count_params = compiler.compile()
    assert 'FROM (SELECT "t1"."id" AS "id", "t1"."amount" AS "amount"' in sql
    assert 'AS "paid_orders"' in sql
    assert "DESC NULLS LAST" in sql
    assert params == ["PAID", 50, 0]
    assert count_params == ["PAID"]

    with pytest.raises(ValidationError):
        QueryCompiler(
            {
                "table": "orders",
                "columns": ["id"],
                "order_by": [{"column": "id", "direction": "ASC", "nulls": "INVALID"}],
            }
        )


def test_compiler_extended_aggregates_and_camelcase_keys() -> None:
    spec = {
        "table": "orders",
        "columns": [
            "orders.status",
            {"expression": "STRING_AGG(orders.item, ',')", "alias": "items_list"},
        ],
        "joins": [
            {
                "table": "users",
                "type": "LEFT",
                "leftTable": "orders",
                "leftCol": "user_id",
                "rightCol": "id",
            }
        ],
        "filters": [
            {
                "column": "orders.amount",
                "op": "gt",
                "value": 10,
                "paren_open": True,
                "paren_close": True,
            }
        ],
    }
    sql, params, _, _ = QueryCompiler(spec, dialect="postgres").compile()
    assert 'GROUP BY "t1"."status"' in sql
    assert 'LEFT JOIN "users" "t2" ON "t1"."user_id" = "t2"."id"' in sql
    assert params == [10, 50, 0]


def test_explain_and_executor_handle_none_limit_and_zero_user_id() -> None:
    plan = estimate_plan_from_spec({"table": "users", "columns": ["id"], "limit": None})
    assert plan is not None

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items (id INT, user_id INT, name TEXT);")
    conn.execute("INSERT INTO items VALUES (1, 0, 'ZeroOwner'), (2, 1, 'OneOwner');")

    schema = {
        "tables": {
            "items": {
                "columns": [
                    {"name": "id", "data_type": "int"},
                    {"name": "user_id", "data_type": "int"},
                    {"name": "name", "data_type": "text"},
                ],
                "has_user_id": True,
            }
        }
    }
    res = execute_compiled_spec(
        conn.cursor(),
        {"table": "items", "columns": ["name"], "limit": None, "offset": None},
        schema=schema,
        user_id=0,
        dialect="sqlite",
    )
    assert res["rows"] == [{"name": "ZeroOwner"}]
    conn.close()


def test_join_solver_habit_id_and_schema_snapshot_pk() -> None:
    snap = _sample_snapshot()
    cond = find_best_join_condition("users", "orders", snap)
    assert cond["left_col"] == "id"
    assert cond["right_col"] == "user_id"

    habit_schema = {
        "tables": {
            "logs": {"columns": [{"name": "id"}, {"name": "project_id"}]},
            "streaks": {"columns": [{"name": "id"}, {"name": "project_id"}]},
        }
    }
    cond_habit = find_best_join_condition("logs", "streaks", habit_schema)
    assert cond_habit["left_col"] == "project_id"
    assert cond_habit["right_col"] == "project_id"


def test_security_masking_complexity_and_policy_clac_wildcard() -> None:
    assert (
        apply_column_masking("alice@example.com", "partial_email")
        == "al***@example.com"
    )
    assert apply_column_masking("+1-555-867-5309", "partial_phone") == "***-***-5309"
    assert apply_column_masking("123-45-6789", "last4") == "****6789"

    from query_builder.dialects import get_dialect

    pg = get_dialect("postgres")
    assert "@***" in pg.format_masking_expression('"t1"."email"', "partial_email")
    assert "***-***-" in pg.format_masking_expression('"t1"."phone"', "partial_phone")
    assert "RIGHT(" in pg.format_masking_expression('"t1"."ssn"', "last4")

    # Complexity accounts for derived tables, CTEs, and window functions
    complex_spec = {
        "table": {"subquery": {"table": "orders", "columns": ["id"]}, "alias": "sub"},
        "columns": ["id"],
        "ctes": [{"name": "c1", "query": {"table": "users", "columns": ["id"]}}],
        "window_functions": [{"function": "ROW_NUMBER", "alias": "rn"}],
    }
    assert calculate_ast_complexity(complex_spec) > 10

    # Policy CLAC blocks wildcard when no schema is given, and expands when schema is given
    policy = SecurityPolicy(
        enforce_tenant_isolation=False,
        column_permissions={
            "users": {
                "allowed_roles": ["admin"],
                "restricted_columns": ["email"],
            }
        },
    )
    ctx = TenantContext(tenant_id="t1", roles=["viewer"])
    with pytest.raises(SecurityError):
        apply_security_policy(
            {"table": "users", "columns": ["*"]},
            context=ctx,
            policy=policy,
        )

    schema = {
        "tables": {
            "users": {"columns": [{"name": "id"}, {"name": "name"}, {"name": "email"}]}
        }
    }
    expanded_clac = apply_security_policy(
        {"table": "users", "columns": []},
        schema=schema,
        context=ctx,
        policy=policy,
    )
    assert expanded_clac["columns"] == ["id", "name"]

    mask_policy = SecurityPolicy(
        enforce_tenant_isolation=False,
        column_masking={"users": ["email"]},
        masking_strategy="partial_email",
    )
    expanded_mask = apply_security_policy(
        {"table": "users", "columns": ["*"]},
        schema=schema,
        context=ctx,
        policy=mask_policy,
    )
    assert len(expanded_mask["columns"]) == 3
    assert isinstance(expanded_mask["columns"][2], dict)
    assert expanded_mask["columns"][2]["alias"] == "email_masked"
    assert expanded_mask["columns"][2]["masking_strategy"] == "partial_email"


def test_advisor_resolves_aliases_and_deduplicates_indexes() -> None:
    snap = _sample_snapshot()
    spec = {
        "table": "orders",
        "columns": ["orders.order_pk", "orders.status"],
        "joins": [
            {
                "table": "users",
                "type": "INNER",
                "left_col": "orders.user_id",
                "right_col": "users.id",
            }
        ],
        "filters": [
            {"column": "t1.order_pk", "op": "eq", "value": 10},
            {"column": "t1.status", "op": "eq", "value": "PAID"},
            {"column": "orders.status", "op": "neq", "value": "CANCELLED"},
        ],
        "order_by": ["t1.amount DESC"],
    }
    recs = recommend_indexes(spec, schema_snapshot=snap)
    tables_for_recs = [r["table"] for r in recs]
    assert "t1" not in tables_for_recs
    # order_pk is primary key on orders in snap, so no single-column index for order_pk
    assert not any(r["columns"] == ["order_pk"] for r in recs)
    # status should only be recommended once as a single-column index
    status_recs = [r for r in recs if r["columns"] == ["status"]]
    assert len(status_recs) == 1


def test_parser_not_ilike_nulls_ordering_and_table_aliases() -> None:
    sql = """
        SELECT u.id, o.amount
        FROM users AS u
        INNER JOIN orders o ON u.id = o.user_id
        WHERE u.email NOT ILIKE '%@spam.com'
          AND o.status NOT LIKE 'TEST%'
        ORDER BY o.amount DESC NULLS LAST, u.id ASC NULLS FIRST
    """
    spec = parse_sql_to_spec(sql)
    assert spec is not None
    assert spec.table == "users"
    assert spec.columns == ["users.id", "orders.amount"]
    assert len(spec.joins) == 1
    assert spec.joins[0].table == "orders"
    assert spec.joins[0].left_table == "users"
    assert spec.joins[0].left_col == "id"
    assert spec.joins[0].right_col == "user_id"
    assert [(f.table_prefix, f.column, f.op) for f in spec.filters] == [
        ("users", "email", "NOT ILIKE"),
        ("orders", "status", "NOT LIKE"),
    ]
    assert spec.order_by == [
        OrderBySpec(
            column="amount",
            direction="desc",
            table_prefix="orders",
            nulls="LAST",
        ),
        OrderBySpec(
            column="id",
            direction="asc",
            table_prefix="users",
            nulls="FIRST",
        ),
    ]


def test_fluent_query_new_methods() -> None:
    schema = {
        "tables": {
            "orders": {
                "columns": [
                    {"name": "id", "data_type": "integer"},
                    {"name": "status", "data_type": "text"},
                    {"name": "amount", "data_type": "numeric"},
                ]
            }
        }
    }
    q = (
        query("orders")
        .select("orders.status")
        .where("orders.status", "eq", "PAID")
        .order_by("orders.status", "ASC", nulls="LAST")
        .rollup()
        .window("ROW_NUMBER", alias="rn", partition_by=["orders.status"])
        .with_cte("recent_orders", query("orders").select("orders.id"))
        .check_columns(schema)
    )
    runnable = q.compile_runnable(dialect="postgres", schema=schema)
    assert runnable is not None
    assert "'PAID'" in runnable
    assert "NULLS LAST" in runnable
    assert "ROLLUP" in runnable

    search_sql, search_params, _, _ = (
        query("orders")
        .select("orders.id", "orders.status")
        .compile_search("urgent", dialect="postgres", schema=schema)
    )
    assert "ILIKE" in search_sql
    assert "%urgent%" in search_params


def test_cli_parse_and_case_insensitive_schema_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(
        json.dumps(
            {
                "tables": {
                    "Customers": {
                        "name": "Customers",
                        "columns": [
                            {"name": "id", "data_type": "integer", "is_primary": True}
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    rc = cli_main(
        ["schema", "--schema", str(schema_file), "--table", "Customers", "--json"]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["name"] == "Customers"

    rc_parse = cli_main(
        [
            "parse",
            "SELECT id, email FROM users WHERE id = 7 ORDER BY id DESC NULLS LAST",
        ]
    )
    assert rc_parse == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["table"] == "users"
    assert parsed["order_by"][0]["nulls"] == "LAST"


def test_mcp_new_tools_and_public_exports() -> None:
    assert hasattr(qb, "egress_guard")
    assert hasattr(qb, "EgressPolicy")
    assert hasattr(qb, "ServerSecurity")
    assert hasattr(qb, "secure_request")

    server = McpServer()
    resp_parse = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "query_builder_parse_sql",
                "arguments": {"sql": "SELECT id FROM users WHERE id = 1"},
            },
        }
    )
    assert resp_parse is not None
    parsed_payload = json.loads(resp_parse["result"]["content"][0]["text"])
    assert parsed_payload["spec"]["table"] == "users"

    schema = {"tables": {"users": {"columns": [{"name": "id"}]}}}
    resp_check = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "query_builder_check_columns",
                "arguments": {
                    "spec": {"table": "users", "columns": ["users.missing_col"]},
                    "schema": schema,
                },
            },
        }
    )
    assert resp_check is not None
    check_payload = json.loads(resp_check["result"]["content"][0]["text"])
    assert check_payload["valid"] is False
    assert check_payload["table"] == "users"

    resp_audit = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "query_builder_audit_schema",
                "arguments": {"schema": schema},
            },
        }
    )
    assert resp_audit is not None
    audit_payload = json.loads(resp_audit["result"]["content"][0]["text"])
    assert audit_payload["tables"] == 1
