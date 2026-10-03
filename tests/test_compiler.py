import pytest

from query_builder.compiler import CompilationError, QueryCompiler


@pytest.fixture
def mock_schema():
    return {
        "tables": {
            "habbits": {
                "columns": [
                    {"name": "id", "is_primary": True},
                    {"name": "user_id"},
                    {"name": "title"},
                    {"name": "is_active"},
                    {"name": "streak_count"},
                ],
                "has_user_id": True,
                "user_col": "user_id",
            },
            "habbit_logs": {
                "columns": [
                    {"name": "id", "is_primary": True},
                    {"name": "habbit_id"},
                    {"name": "completed_at"},
                    {"name": "score"},
                ],
                "has_user_id": False,
            },
        },
        "foreign_keys": [
            {
                "table": "habbit_logs",
                "column": "habbit_id",
                "foreign_table": "habbits",
                "foreign_column": "id",
            }
        ],
        "relationships": [
            {
                "source_table": "habbit_logs",
                "source_column": "habbit_id",
                "target_table": "habbits",
                "target_column": "id",
            }
        ],
    }


def test_basic_query_compilation(mock_schema):
    spec = {
        "table": "habbits",
        "columns": ["habbits.title", "habbits.is_active"],
        "limit": 10,
        "offset": 0,
    }
    compiler = QueryCompiler(
        spec, schema=mock_schema, user_id=1, force_user_filter=True
    )
    sql, params, _count_sql, count_params = compiler.compile()

    assert (
        'SELECT "t1"."title" AS "habbits.title", "t1"."is_active" AS "habbits.is_active"'
        in sql
    )
    assert 'FROM "habbits" "t1"' in sql
    assert 'WHERE "t1"."user_id" = %s' in sql
    assert params == [1, 10, 0]
    assert count_params == [1]


def test_joins_and_filters_compilation(mock_schema):
    spec = {
        "table": "habbits",
        "columns": ["habbits.title", "habbit_logs.completed_at"],
        "joins": [
            {
                "table": "habbit_logs",
                "type": "LEFT JOIN",
                "on": [{"left": "habbits.id", "right": "habbit_logs.habbit_id"}],
            }
        ],
        "filters": [
            {"column": "habbits.is_active", "op": "eq", "value": True},
            {"column": "habbits.title", "op": "contains", "value": "Workout"},
        ],
        "filter_join": "AND",
        "order_by": [{"column": "habbits.title", "direction": "ASC"}],
        "limit": 20,
    }
    compiler = QueryCompiler(spec, schema=mock_schema)
    sql, params, _count_sql, _ = compiler.compile()

    assert 'LEFT JOIN "habbit_logs" "t2" ON "t1"."id" = "t2"."habbit_id"' in sql
    assert '"t1"."is_active" = %s AND "t1"."title" ILIKE %s' in sql
    assert True in params
    assert "%Workout%" in params
    assert 'ORDER BY "t1"."title" ASC' in sql


def test_aggregations_and_group_by(mock_schema):
    spec = {
        "table": "habbits",
        "columns": [
            "habbits.title",
            {"column": "habbit_logs.score", "agg": "avg", "alias": "average_score"},
            {"column": "habbit_logs.id", "agg": "count", "alias": "log_count"},
        ],
        "joins": [{"table": "habbit_logs", "left_col": "id", "right_col": "habbit_id"}],
        "having": [
            {"column": "habbit_logs.id", "agg": "count", "op": "gt", "value": 5}
        ],
    }
    compiler = QueryCompiler(spec, schema=mock_schema)
    sql, params, count_sql, _ = compiler.compile()

    assert 'AVG("t2"."score") AS "average_score"' in sql
    assert 'COUNT("t2"."id") AS "log_count"' in sql
    assert 'GROUP BY "t1"."title"' in sql
    assert 'HAVING COUNT("t2"."id") > %s' in sql
    assert 5 in params
    assert "AS count_subquery" in count_sql


def test_multi_dialect_mssql(mock_schema):
    spec = {
        "table": "habbits",
        "columns": ["habbits.title"],
        "limit": 15,
        "offset": 30,
    }
    compiler = QueryCompiler(spec, schema=mock_schema, dialect="mssql")
    sql, params, _count_sql, _ = compiler.compile()

    assert "[habbits] [t1]" in sql
    assert "OFFSET %s ROWS FETCH NEXT %s ROWS ONLY" in sql
    assert params == [30, 15]


def test_missing_table_raises_error():
    spec = {"table": "nonexistent"}
    compiler = QueryCompiler(spec, schema={"tables": {"habbits": {}}})
    with pytest.raises(CompilationError):
        compiler.compile()


def test_missing_table_key_raises_error():
    with pytest.raises(CompilationError):
        QueryCompiler({}).compile()


def test_invalid_spec_type_raises_error():
    with pytest.raises(CompilationError):
        QueryCompiler(12345)


def test_compiler_with_dataclasses():
    from query_builder.models import (
        FilterSpec,
        HavingSpec,
        JoinSpec,
        OrderBySpec,
        QuerySpec,
    )

    spec = QuerySpec(
        table="projects",
        columns=[
            "projects.id",
            {"column": "projects.title", "agg": "count", "alias": "p_count"},
        ],
        joins=[
            JoinSpec(
                table="tasks",
                type="LEFT",
                on=[{"left": "projects.id", "right": "tasks.project_id"}],
            )
        ],
        filters=[FilterSpec(column="projects.id", op="gt", value=10)],
        having=[HavingSpec(column="projects.title", agg="count", op="gt", value=2)],
        order_by=[OrderBySpec(column="projects.id", direction="desc")],
        limit=5,
        offset=0,
    )
    schema = {
        "tables": {
            "projects": {"columns": [{"name": "id"}, {"name": "title"}]},
            "tasks": {"columns": [{"name": "id"}, {"name": "project_id"}]},
        }
    }
    compiler = QueryCompiler(spec, schema=schema)
    sql, params, _count_sql, _ = compiler.compile()
    assert 'COUNT("t1"."title") AS "p_count"' in sql
    assert 'LEFT JOIN "tasks" "t2"' in sql
    assert 'GROUP BY "t1"."id"' in sql
    assert 'ORDER BY "t1"."id" DESC' in sql
    assert 10 in params
    assert 2 in params


def test_compiler_tenant_id_isolation():
    schema = {
        "tables": {
            "organizations": {
                "columns": [{"name": "id"}, {"name": "client_id"}, {"name": "name"}],
            }
        }
    }
    spec = {"table": "organizations", "columns": ["organizations.name"]}
    compiler = QueryCompiler(spec, schema=schema, tenant_id="tenant-99")
    sql, params, _, _ = compiler.compile()
    assert '"client_id" = %s' in sql
    assert "tenant-99" in params


def test_compiler_join_errors():
    schema = {"tables": {"users": {"columns": [{"name": "id"}]}}}

    # Missing target table in join dict
    with pytest.raises(CompilationError) as exc1:
        QueryCompiler({"table": "users", "joins": [{}]}, schema=schema).compile()
    assert "Missing join target" in str(exc1.value)

    # Join table not in schema
    with pytest.raises(CompilationError) as exc2:
        QueryCompiler(
            {"table": "users", "joins": [{"table": "not_in_schema"}]}, schema=schema
        ).compile()
    assert "Invalid join table" in str(exc2.value)

    # No join condition and no FK relationship found
    with pytest.raises(CompilationError) as exc3:
        QueryCompiler(
            {"table": "users", "joins": [{"table": "logs"}]}, schema=None
        ).compile()
    assert "No join condition specified" in str(exc3.value)


def test_compiler_join_auto_resolution_via_relationships():
    schema = {
        "tables": {
            "orders": {"columns": [{"name": "id"}, {"name": "user_id"}]},
            "users": {"columns": [{"name": "id"}, {"name": "name"}]},
        },
        "relationships": [
            {
                "source_table": "orders",
                "source_column": "user_id",
                "target_table": "users",
                "target_column": "id",
            }
        ],
    }
    spec = {
        "table": "orders",
        "columns": ["orders.id", "users.name"],
        "joins": [{"table": "users"}],
    }
    compiler = QueryCompiler(spec, schema=schema)
    sql, _, _, _ = compiler.compile()
    assert '"orders" "t1"' in sql
    assert '"users" "t2"' in sql
    assert '"t1"."user_id" = "t2"."id"' in sql


def test_compiler_filter_operators_and_validation():
    spec = {
        "table": "items",
        "filters": [
            {"column": "items.price", "op": "between", "value": "10, 20"},
            {"column": "items.tag", "op": "in", "value": "tech, hardware"},
            {"column": "items.code", "op": "like", "value": "PRD%"},
        ],
    }
    compiler = QueryCompiler(spec)
    sql, params, _, _ = compiler.compile()
    assert "BETWEEN %s AND %s" in sql
    assert "IN (%s, %s)" in sql
    assert "LIKE %s" in sql
    assert "10" in params
    assert "20" in params
    assert "tech" in params
    assert "hardware" in params

    # Invalid between bounds
    bad_between = {
        "table": "items",
        "filters": [{"column": "price", "op": "between", "value": "invalid"}],
    }
    with pytest.raises(CompilationError):
        QueryCompiler(bad_between).compile()

    # Unsupported operator
    bad_op = {
        "table": "items",
        "filters": [{"column": "price", "op": "unsupported_op", "value": 1}],
    }
    with pytest.raises(CompilationError):
        QueryCompiler(bad_op).compile()
