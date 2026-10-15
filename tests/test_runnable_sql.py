"""Runnable SQL: a compiled query with its values written in, for a person to paste into a SQL window.

The bound form is what runs; this is only the copy for people, so it is tested for being right (it really runs and
returns the same rows) and for never being wrong (anything that does not line up gives None, never a guess).
"""

from __future__ import annotations

import datetime
import decimal
import sqlite3

import pytest

from query_builder import QueryCompiler
from query_builder.runnable import (
    BACKSLASH_ESCAPE_DIALECTS,
    inline_params,
    sql_literal,
)

SCHEMA = {
    "tables": {
        "account": {
            "name": "account",
            "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "name", "type": "TEXT"},
                {"name": "kind", "type": "TEXT"},
            ],
        }
    }
}


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (None, "NULL"),
        (True, "TRUE"),
        (False, "FALSE"),
        (5, "5"),
        (-2, "-2"),
        (2.5, "2.5"),
        (decimal.Decimal("1.50"), "1.50"),
        ("abc", "'abc'"),
        ("O'Brien", "'O''Brien'"),
        ("a\\b", "'a\\b'"),
        ("nul\x00byte", "'nulbyte'"),
        (datetime.date(2024, 1, 2), "'2024-01-02'"),
        (datetime.datetime(2024, 1, 2, 3, 4, 5), "'2024-01-02T03:04:05'"),
        (float("nan"), "NULL"),
        (float("inf"), "NULL"),
    ],
)
def test_each_kind_of_value_is_a_sql_literal(value: object, text: str) -> None:
    assert sql_literal(value) == text


def test_a_backslash_is_doubled_only_where_the_dialect_treats_it_as_an_escape() -> None:
    assert sql_literal("a\\b", backslash_escapes=True) == "'a\\\\b'"
    assert sql_literal("a\\b", backslash_escapes=False) == "'a\\b'"
    assert "mysql" in BACKSLASH_ESCAPE_DIALECTS
    assert "postgres" not in BACKSLASH_ESCAPE_DIALECTS


def test_placeholders_are_replaced_in_order() -> None:
    sql = "SELECT a FROM t WHERE x = %s AND y ILIKE %s LIMIT %s OFFSET %s"
    assert (
        inline_params(sql, [1, "%ab%", 50, 0])
        == "SELECT a FROM t WHERE x = 1 AND y ILIKE '%ab%' LIMIT 50 OFFSET 0"
    )
    assert (
        inline_params("SELECT 1 WHERE x = ?", ["z"], placeholder="?")
        == "SELECT 1 WHERE x = 'z'"
    )


def test_a_value_that_looks_like_sql_stays_one_string_literal() -> None:
    out = inline_params("SELECT 1 FROM t WHERE n = %s", ["x'; DROP TABLE t; --"])
    assert out == "SELECT 1 FROM t WHERE n = 'x''; DROP TABLE t; --'"


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ('SELECT "a%sb" FROM t WHERE x = %s', 'SELECT "a%sb" FROM t WHERE x = 7'),
        ("SELECT `a%sb` FROM t WHERE x = %s", "SELECT `a%sb` FROM t WHERE x = 7"),
        (
            "SELECT 'it''s %s' FROM t WHERE x = %s",
            "SELECT 'it''s %s' FROM t WHERE x = 7",
        ),
        ("SELECT 1 -- note %s\nWHERE x = %s", "SELECT 1 -- note %s\nWHERE x = 7"),
        ("SELECT 1 /* %s */ WHERE x = %s", "SELECT 1 /* %s */ WHERE x = 7"),
        ("SELECT 1 -- trailing %s", None),
        ("SELECT 'unterminated %s", None),
    ],
)
def test_a_marker_inside_quotes_or_a_comment_is_left_alone(
    sql: str, expected: str | None
) -> None:
    assert inline_params(sql, [7]) == expected


def test_an_unterminated_comment_is_copied_whole() -> None:
    assert inline_params("SELECT 1 /* open %s", []) == "SELECT 1 /* open %s"
    assert inline_params("SELECT 1 -- open %s", []) == "SELECT 1 -- open %s"


def test_a_marker_inside_a_value_is_not_substituted_again() -> None:
    assert inline_params("SELECT %s, %s", ["%s", 2]) == "SELECT '%s', 2"


def test_an_escaped_percent_sign_is_one_percent_sign() -> None:
    assert inline_params("SELECT 100 %% 7, %s", [1]) == "SELECT 100 % 7, 1"
    # With "?" markers a doubled percent is just two characters.
    assert inline_params("SELECT '%%' , ?", [1], placeholder="?") == "SELECT '%%' , 1"


def test_mismatched_counts_give_nothing_rather_than_a_wrong_statement() -> None:
    assert inline_params("SELECT %s", []) is None
    assert inline_params("SELECT %s", [1, 2]) is None


@pytest.mark.parametrize("placeholder", ["$param", "@param", ":1"])
def test_a_placeholder_that_is_not_positional_gives_nothing(placeholder: str) -> None:
    assert inline_params("SELECT 1", [], placeholder=placeholder) is None


SPEC = {
    "table": "account",
    "columns": ["account.id", "account.name"],
    "filters": [
        {"column": "name", "tablePrefix": "account", "op": "CONTAINS", "value": "o'b"}
    ],
    "limit": 5,
}


def test_the_compiler_returns_the_statement_with_its_values_written_in() -> None:
    runnable = QueryCompiler(SPEC, schema=SCHEMA, dialect="postgres").compile_runnable()
    assert runnable is not None
    assert "%s" not in runnable
    assert "ILIKE '%o''b%'" in runnable
    assert runnable.rstrip().endswith("LIMIT 5 OFFSET 0")


def test_what_actually_runs_is_still_bound() -> None:
    sql, params, _, _ = QueryCompiler(SPEC, schema=SCHEMA, dialect="postgres").compile()
    assert "%s" in sql
    assert params[0] == "%o'b%"


def test_a_dialect_with_named_placeholders_has_no_runnable_form() -> None:
    assert (
        QueryCompiler(SPEC, schema=SCHEMA, dialect="cosmosdb").compile_runnable()
        is None
    )


def test_a_mysql_backslash_in_a_value_is_doubled() -> None:
    spec = {
        **SPEC,
        "filters": [
            {"column": "name", "tablePrefix": "account", "op": "=", "value": "a\\b"}
        ],
    }
    mysql = QueryCompiler(spec, schema=SCHEMA, dialect="mysql").compile_runnable()
    postgres = QueryCompiler(spec, schema=SCHEMA, dialect="postgres").compile_runnable()
    assert mysql is not None and "'a\\\\b'" in mysql
    assert postgres is not None and "'a\\b'" in postgres


def test_the_runnable_statement_really_runs_and_returns_what_the_bound_one_does() -> (
    None
):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE account (id INTEGER, name TEXT, kind TEXT)")
    conn.executemany(
        "INSERT INTO account VALUES (?, ?, ?)",
        [(1, "O'Neil", "a"), (2, "plain", "b"), (3, "100% sure", "a")],
    )
    spec = {
        "table": "account",
        "columns": ["account.id", "account.name"],
        "filters": [
            {
                "column": "name",
                "tablePrefix": "account",
                "op": "CONTAINS",
                "value": "O'Neil",
            }
        ],
        "order_by": [{"column": "id", "tablePrefix": "account", "direction": "ASC"}],
        "limit": 10,
    }
    compiler = QueryCompiler(spec, schema=SCHEMA, dialect="sqlite")
    sql, params, _, _ = compiler.compile()
    bound = conn.execute(sql, params).fetchall()
    runnable = QueryCompiler(spec, schema=SCHEMA, dialect="sqlite").compile_runnable()
    assert runnable is not None
    assert conn.execute(runnable).fetchall() == bound == [(1, "O'Neil")]
