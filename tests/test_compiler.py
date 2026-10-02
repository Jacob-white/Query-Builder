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
            }
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
        ]
    }


def test_basic_query_compilation(mock_schema):
    spec = {
        "table": "habbits",
        "columns": ["habbits.title", "habbits.is_active"],
        "limit": 10,
        "offset": 0,
    }
    compiler = QueryCompiler(spec, schema=mock_schema, user_id=1, force_user_filter=True)
    sql, params, _count_sql, count_params = compiler.compile()

    assert 'SELECT "t1"."title" AS "habbits.title", "t1"."is_active" AS "habbits.is_active"' in sql
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
                "on": [{"left": "habbits.id", "right": "habbit_logs.habbit_id"}]
            }
        ],
        "filters": [
            {"column": "habbits.is_active", "op": "eq", "value": True},
            {"column": "habbits.title", "op": "contains", "value": "Workout"}
        ],
        "filter_join": "AND",
        "order_by": [
            {"column": "habbits.title", "direction": "ASC"}
        ],
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
            {"column": "habbit_logs.id", "agg": "count", "alias": "log_count"}
        ],
        "joins": [
            {"table": "habbit_logs", "left_col": "id", "right_col": "habbit_id"}
        ],
        "having": [
            {"column": "habbit_logs.id", "agg": "count", "op": "gt", "value": 5}
        ]
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
