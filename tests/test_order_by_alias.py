"""``order_by`` naming the alias of a selected column that is not an aggregate.

Sorting by an aggregate's label already compiles to ``ORDER BY "label"``. The alias of an ordinary selected column was
still qualified with the table alias, ``ORDER BY "t1"."is_open"``, a column that does not exist, so the query passed
validation and failed in the database. An ``order_by`` item with no table prefix whose column is an output alias of the
spec now sorts by that alias. A name that is a real column of a table in the query keeps meaning that column, and a
table prefix always means a column, so nothing that worked changes. Each case runs on SQLite as well as comparing SQL.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from query_builder import QueryCompiler

SCHEMA = {
    "tables": {
        "orders": {
            "name": "orders",
            "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "status", "type": "TEXT"},
                {"name": "customer_id", "type": "INTEGER"},
            ],
        },
        "customers": {
            "name": "customers",
            "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "region", "type": "TEXT"},
            ],
        },
    }
}

ORDERS = [
    (1, "open", 1),
    (2, "open", 1),
    (3, "closed", 2),
    (4, "open", 2),
    (5, "closed", 1),
    (6, "pending", 2),
]


@pytest.fixture
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE orders (id INTEGER, status TEXT, customer_id INTEGER)"
    )
    connection.executemany("INSERT INTO orders VALUES (?, ?, ?)", ORDERS)
    connection.execute("CREATE TABLE customers (id INTEGER, region TEXT)")
    connection.executemany(
        "INSERT INTO customers VALUES (?, ?)", [(1, "east"), (2, "west")]
    )
    return connection


def compile_spec(spec: dict[str, Any], schema: Any = SCHEMA) -> tuple[str, list[Any]]:
    sql, params, _, _ = QueryCompiler(spec, schema=schema, dialect="sqlite").compile()
    return sql, params


def run(
    conn: sqlite3.Connection, spec: dict[str, Any], schema: Any = SCHEMA
) -> list[tuple[Any, ...]]:
    sql, params = compile_spec(spec, schema)
    return conn.execute(sql, params).fetchall()


GROUPED = {
    "table": "orders",
    "columns": [
        {"column": "orders.status", "alias": "is_open"},
        {"column": "orders.id", "agg": "count", "alias": "n"},
    ],
}


def test_the_alias_of_a_grouping_column_and_of_a_count_are_both_written_as_labels(
    conn: sqlite3.Connection,
) -> None:
    spec = {
        **GROUPED,
        "order_by": [
            {"column": "is_open", "direction": "ASC"},
            {"column": "n", "direction": "DESC"},
        ],
    }
    sql, _ = compile_spec(spec)
    assert 'ORDER BY "is_open" ASC, "n" DESC' in sql
    assert '"t1"."is_open"' not in sql
    assert run(conn, spec) == [("closed", 2), ("open", 3), ("pending", 1)]


def test_descending_by_the_alias_runs_and_orders_the_rows(
    conn: sqlite3.Connection,
) -> None:
    spec = {**GROUPED, "order_by": [{"column": "is_open", "direction": "DESC"}]}
    assert [row[0] for row in run(conn, spec)] == ["pending", "open", "closed"]


def test_an_alias_on_a_query_with_no_grouping_works_too(
    conn: sqlite3.Connection,
) -> None:
    spec = {
        "table": "orders",
        "columns": [{"column": "orders.status", "alias": "state"}, "orders.id"],
        "order_by": [
            {"column": "state", "direction": "ASC"},
            {"column": "id", "tablePrefix": "orders", "direction": "DESC"},
        ],
    }
    sql, _ = compile_spec(spec)
    assert 'ORDER BY "state" ASC, "t1"."id" DESC' in sql
    assert [row[1] for row in run(conn, spec)] == [5, 3, 4, 2, 1, 6]


def test_an_expression_column_can_be_sorted_by_its_alias(
    conn: sqlite3.Connection,
) -> None:
    spec = {
        "table": "orders",
        "columns": [{"expression": "id * 2", "alias": "double_id"}],
        "order_by": [{"column": "double_id", "direction": "DESC"}],
    }
    sql, _ = compile_spec(spec)
    assert 'ORDER BY "double_id" DESC' in sql
    assert [row[0] for row in run(conn, spec)] == [12, 10, 8, 6, 4, 2]


def test_distinct_with_an_alias_runs(conn: sqlite3.Connection) -> None:
    spec = {
        "table": "orders",
        "columns": [{"column": "orders.status", "alias": "state"}],
        "distinct": True,
        "order_by": [{"column": "state", "direction": "ASC"}],
    }
    assert [row[0] for row in run(conn, spec)] == ["closed", "open", "pending"]


def test_the_alias_of_a_column_of_a_joined_table_is_sorted_by_label(
    conn: sqlite3.Connection,
) -> None:
    spec = {
        "table": "orders",
        "columns": [
            {"column": "customers.region", "alias": "area"},
            {"column": "orders.id", "agg": "count", "alias": "n"},
        ],
        "joins": [
            {
                "table": "customers",
                "type": "INNER",
                "left_table": "orders",
                "left_col": "customer_id",
                "right_col": "id",
            }
        ],
        "order_by": [{"column": "area", "direction": "DESC"}],
    }
    assert [row[0] for row in run(conn, spec)] == ["west", "east"]


# --- controls: what must not change -----------------------------------------------------------------------------------


def test_a_table_prefix_still_means_the_column_even_when_an_alias_has_the_same_name(
    conn: sqlite3.Connection,
) -> None:
    spec = {
        "table": "orders",
        "columns": [{"column": "orders.id", "alias": "status"}, "orders.status"],
        "order_by": [
            {"column": "status", "tablePrefix": "orders", "direction": "ASC"},
            {"column": "id", "tablePrefix": "orders"},
        ],
    }
    sql, _ = compile_spec(spec)
    assert 'ORDER BY "t1"."status" ASC, "t1"."id" ASC' in sql
    assert [row[1] for row in run(conn, spec)][:2] == ["closed", "closed"]


def test_a_real_column_of_the_base_table_keeps_meaning_that_column_even_if_an_alias_has_its_name(
    conn: sqlite3.Connection,
) -> None:
    spec = {
        "table": "orders",
        "columns": [{"column": "orders.id", "alias": "status"}],
        "order_by": [{"column": "status", "direction": "ASC"}],
    }
    assert 'ORDER BY "t1"."status" ASC' in compile_spec(spec)[0]


def test_a_name_only_a_joined_table_has_is_the_alias_because_an_unprefixed_name_means_the_base_table(
    conn: sqlite3.Connection,
) -> None:
    # An unprefixed name is read against the base table. "region" is not a column of orders (it belongs to customers),
    # so it used to compile to "t1"."region", a column that does not exist; as an output alias it now runs.
    spec = {
        "table": "orders",
        "columns": [{"column": "orders.id", "alias": "region"}],
        "joins": [
            {
                "table": "customers",
                "type": "INNER",
                "left_table": "orders",
                "left_col": "customer_id",
                "right_col": "id",
            }
        ],
        "order_by": [{"column": "region", "direction": "DESC"}],
    }
    assert 'ORDER BY "region" DESC' in compile_spec(spec)[0]
    assert [row[0] for row in run(conn, spec)] == [6, 5, 4, 3, 2, 1]


def test_a_column_with_no_alias_is_ordered_exactly_as_before(
    conn: sqlite3.Connection,
) -> None:
    spec = {
        "table": "orders",
        "columns": ["orders.status", "orders.id"],
        "order_by": [
            {"column": "orders.status"},
            {"column": "id", "tablePrefix": "orders", "direction": "DESC"},
        ],
    }
    sql, _ = compile_spec(spec)
    assert 'ORDER BY "t1"."status" ASC, "t1"."id" DESC' in sql


def test_a_name_that_is_no_alias_is_still_read_as_a_column() -> None:
    spec = {**GROUPED, "order_by": [{"column": "ghost", "direction": "ASC"}]}
    assert 'ORDER BY "t1"."ghost" ASC' in compile_spec(spec)[0]


def test_an_aggregate_label_is_unchanged(conn: sqlite3.Connection) -> None:
    spec = {**GROUPED, "order_by": [{"column": "n", "direction": "DESC"}]}
    assert 'ORDER BY "n" DESC' in compile_spec(spec)[0]


def test_without_a_schema_an_alias_is_still_sorted_by_label(
    conn: sqlite3.Connection,
) -> None:
    spec = {**GROUPED, "order_by": [{"column": "is_open", "direction": "ASC"}]}
    sql, params = compile_spec(spec, schema=None)
    assert 'ORDER BY "is_open" ASC' in sql
    assert [row[0] for row in conn.execute(sql, params).fetchall()] == [
        "closed",
        "open",
        "pending",
    ]
