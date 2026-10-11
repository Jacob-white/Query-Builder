"""Regressions for defects found by live-engine testing (no services needed).

* RisingWave rejects ``SELECT DISTINCT ... ORDER BY <qualified column>`` and silently drops
  the rows whose partition key is NULL for an aggregate window without ORDER BY.
* pymongosql ignores the ``''`` quote escape and silently returns no rows.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from query_builder.compiler import QueryCompiler
from query_builder.connectors.mongodb import (
    MongoDBAtlasSQLConnector,
    bind_escaped_quote_literals,
)
from query_builder.dialects.registry import get_dialect

SCHEMA = {
    "tables": {
        "emp": {
            "columns": [
                {"name": "id", "is_primary": True},
                {"name": "dept_id"},
                {"name": "salary"},
            ],
            "has_user_id": False,
        }
    },
    "foreign_keys": [],
    "relationships": [],
}


def _sql(spec: dict[str, Any], dialect: str) -> str:
    return QueryCompiler(spec, schema=SCHEMA, dialect=get_dialect(dialect)).compile()[0]


DISTINCT = {
    "table": "emp",
    "columns": ["dept_id"],
    "distinct": True,
    "order_by": [{"column": "dept_id", "direction": "asc"}],
}


def test_risingwave_distinct_orders_by_select_alias() -> None:
    sql = _sql(DISTINCT, "risingwave")
    assert 'SELECT DISTINCT "t1"."dept_id" AS "dept_id"' in sql
    assert 'ORDER BY "dept_id" ASC' in sql


def test_risingwave_non_distinct_order_by_keeps_qualified_column() -> None:
    sql = _sql({**DISTINCT, "distinct": False}, "risingwave")
    assert 'ORDER BY "t1"."dept_id" ASC' in sql


def test_risingwave_distinct_order_by_unselected_column_is_untouched() -> None:
    spec = {**DISTINCT, "order_by": [{"column": "salary"}]}
    assert 'ORDER BY "t1"."salary" ASC' in _sql(spec, "risingwave")


def test_other_dialects_distinct_output_is_unchanged() -> None:
    assert 'ORDER BY "t1"."dept_id" ASC' in _sql(DISTINCT, "postgres")
    assert 'ORDER BY "t1"."dept_id" ASC' in _sql(DISTINCT, "cockroachdb")


def _window(wf: dict[str, Any]) -> dict[str, Any]:
    return {"table": "emp", "columns": ["id"], "window_functions": [wf]}


SUM_WINDOW = {
    "function": "SUM",
    "arguments": ["salary"],
    "partition_by": ["dept_id"],
    "alias": "t",
}
FULL = (
    'OVER (PARTITION BY "t1"."dept_id" ORDER BY "t1"."dept_id" '
    "ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)"
)


def test_risingwave_partition_aggregate_window_keeps_null_partition_rows() -> None:
    assert FULL in _sql(_window(SUM_WINDOW), "risingwave")


@pytest.mark.parametrize(
    "wf",
    [
        {**SUM_WINDOW, "order_by": [{"column": "salary"}]},
        {**SUM_WINDOW, "frame": {"frame_type": "ROWS", "start": "UNBOUNDED PRECEDING"}},
        {**SUM_WINDOW, "partition_by": []},
        {
            "function": "ROW_NUMBER",
            "partition_by": ["dept_id"],
            "order_by": [{"column": "salary"}],
            "alias": "t",
        },
    ],
)
def test_risingwave_window_rewrite_only_for_bare_partition_aggregates(
    wf: dict[str, Any],
) -> None:
    assert FULL not in _sql(_window(wf), "risingwave")


def test_other_dialects_window_output_is_unchanged() -> None:
    sql = _sql(_window(SUM_WINDOW), "postgres")
    assert 'OVER (PARTITION BY "t1"."dept_id")' in sql


# ------------------------------------------------------------------ pymongosql quotes


@pytest.mark.parametrize(
    ("sql", "params", "want_sql", "want_params"),
    [
        (
            "SELECT name FROM c WHERE name = 'O''Brien'",
            None,
            "SELECT name FROM c WHERE name = ?",
            ["O'Brien"],
        ),
        (
            "SELECT a FROM c WHERE x = ? AND name = 'it''s' AND y = ?",
            [1, 2],
            "SELECT a FROM c WHERE x = ? AND name = ? AND y = ?",
            [1, "it's", 2],
        ),
        (
            "SELECT a FROM c WHERE n = 'a''b' OR m = 'c''''d'",
            [],
            "SELECT a FROM c WHERE n = ? OR m = ?",
            ["a'b", "c''d"],
        ),
        (  # only the quote-escaped literal is bound; plain literals stay literal
            "SELECT a FROM c WHERE n = 'plain' AND m = 'x''y'",
            None,
            "SELECT a FROM c WHERE n = 'plain' AND m = ?",
            ["x'y"],
        ),
        (  # a `?` or quote inside a double-quoted identifier is not a placeholder
            "SELECT \"we?ird\" FROM c WHERE m = 'x''y'",
            None,
            'SELECT "we?ird" FROM c WHERE m = ?',
            ["x'y"],
        ),
    ],
)
def test_escaped_quote_literals_become_bound_parameters(
    sql: str, params: Any, want_sql: str, want_params: list[Any]
) -> None:
    assert bind_escaped_quote_literals(sql, params) == (want_sql, want_params)


@pytest.mark.parametrize(
    ("sql", "params"),
    [
        ("SELECT a FROM c WHERE n = 'plain'", None),  # no escape: untouched
        ("SELECT a FROM c WHERE n = 'x''y'", {"k": 1}),  # named params: untouched
        ("SELECT a FROM c WHERE n = 'x''y", None),  # unterminated: driver reports it
        ("SELECT \"a FROM c WHERE n = 'x''y'", None),  # unterminated identifier
    ],
)
def test_bind_escaped_quote_literals_leaves_other_sql_alone(
    sql: str, params: Any
) -> None:
    assert bind_escaped_quote_literals(sql, params) == (sql, params)


def test_mongodb_connector_executes_escaped_quote_query_with_bound_value() -> None:
    cur = MagicMock()
    cur.description = [("name",)]
    cur.fetchall.return_value = [("O'Brien",)]
    conn = MongoDBAtlasSQLConnector(database="d", cursor=cur)
    result = conn.execute(sql="SELECT name FROM people WHERE name = 'O''Brien'")
    cur.execute.assert_called_once_with(
        "SELECT name FROM people WHERE name = ?", ["O'Brien"]
    )
    assert result["rows"] == [{"name": "O'Brien"}]
