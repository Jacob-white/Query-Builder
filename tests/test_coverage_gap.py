import pytest

from query_builder.cli import main
from query_builder.compiler import CompilationError, QueryCompiler
from query_builder.join_solver import find_best_join_condition


def test_clean_table_name_with_dot():
    cond = find_best_join_condition(
        "production.users",
        "public.orders",
        {
            "tables": {
                "users": {"columns": [{"name": "id"}]},
                "orders": {"columns": [{"name": "id"}, {"name": "user_id"}]},
            }
        },
    )
    assert cond["left_table"] == "users"
    assert cond["right_table"] == "orders"


def test_security_error_during_base_table_compilation():
    schema = {
        "tables": {
            "secret_vault": {
                "columns": [{"name": "id"}],
                "has_user_id": False,
            }
        }
    }
    spec = {"table": "secret_vault"}
    with pytest.raises(CompilationError) as exc:
        QueryCompiler(spec, schema=schema, user_id=1, force_user_filter=True).compile()
    assert "refusing to query it without tenant isolation" in str(exc.value)


def test_security_error_during_join_table_compilation():
    schema = {
        "tables": {
            "users": {
                "columns": [{"name": "id"}, {"name": "user_id"}],
                "has_user_id": True,
            },
            "orphan_child": {
                "columns": [{"name": "id"}, {"name": "data"}],
                "has_user_id": False,
            },
        }
    }
    spec = {
        "table": "users",
        "joins": [
            {
                "table": "orphan_child",
                "left_col": "id",
                "right_col": "id",
            }
        ],
    }
    with pytest.raises(CompilationError) as exc:
        QueryCompiler(spec, schema=schema, user_id=1, force_user_filter=True).compile()
    assert "refusing to query it without tenant isolation" in str(exc.value)


def test_compiler_join_auto_resolution_via_schema_condition():
    schema = {
        "tables": {
            "firms": {"columns": [{"name": "id"}]},
            "branches": {"columns": [{"name": "id"}, {"name": "firm_id"}]},
        }
    }
    spec = {"table": "firms", "joins": [{"table": "branches"}]}
    compiler = QueryCompiler(spec, schema=schema)
    sql, _, _, _ = compiler.compile()
    assert '"firms" "t1"' in sql
    assert '"branches" "t2"' in sql


def test_compiler_default_columns_from_schema():
    schema = {"tables": {"metrics": {"columns": [{"name": "val1"}, {"name": "val2"}]}}}
    compiler = QueryCompiler({"table": "metrics"}, schema=schema)
    sql, _, _, _ = compiler.compile()
    assert '"t1"."val1"' in sql
    assert '"t1"."val2"' in sql


def test_compiler_skipped_empty_items_and_formatting():
    spec = {
        "table": "items",
        "columns": [
            {},  # empty dict skipped
            {"name": "col_alias", "alias": "my_alias"},
        ],
        "filters": [
            {},  # empty filter skipped
            {"column": "status", "op": "in", "value": 42},  # scalar for in
            {"column": "date", "op": "between", "value": "2026-01-01 AND 2026-12-31"},
        ],
        "order_by": [
            {},  # empty order by skipped
        ],
    }
    compiler = QueryCompiler(spec)
    sql, params, _, _ = compiler.compile()
    assert '"t1"."col_alias" AS "my_alias"' in sql
    assert '"t1"."status" IN (%s)' in sql
    assert 42 in params
    assert "2026-01-01" in params
    assert "2026-12-31" in params


def test_compiler_join_fallback_and_dataclass_on():
    from query_builder.models import JoinCondition

    schema = {
        "tables": {
            "users": {
                "columns": [{"name": "id"}, {"name": "user_id"}],
                "has_user_id": True,
            },
            "orders": {
                "columns": [{"name": "id"}, {"name": "user_id"}],
                "has_user_id": True,
            },
        }
    }
    spec = {
        "table": "users",
        "joins": [
            {
                "table": "orders",
                "type": "CUSTOM_TYPE",  # triggers fallback to LEFT JOIN
                "on": [JoinCondition(left="users.id", right="orders.user_id")],
            }
        ],
    }
    compiler = QueryCompiler(spec, schema=schema, user_id=10, force_user_filter=True)
    sql, params, _, _ = compiler.compile()
    assert 'LEFT JOIN "orders" "t2"' in sql
    assert '"t1"."user_id" = %s' in sql
    assert '"t2"."user_id" = %s' in sql
    assert params == [10, 10, 50, 0]


def test_compiler_fallbacks_and_ilike():
    spec = {
        "table": "users",
        "filter_join": "INVALID_COMBINER",  # line 303
        "filters": [
            {
                "column": "email",
                "op": "ilike",
                "value": "%@example.com",
            },  # lines 341-342
        ],
        "order_by": [
            {"column": "created_at", "direction": "INVALID_DIR"},  # line 406
        ],
    }
    compiler = QueryCompiler(spec)
    sql, params, _, _ = compiler.compile()
    assert "ILIKE %s" in sql
    assert 'ORDER BY "t1"."created_at" ASC' in sql
    assert "%@example.com" in params


def test_cli_subcommand_dispatch():
    with pytest.raises(SystemExit):
        main([])
