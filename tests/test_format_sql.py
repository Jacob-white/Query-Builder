"""Laying a statement out for a person to read: ``format_sql`` and ``compile_runnable(pretty=True)``.

The layout is cosmetic, so the one rule is that it must never change what the statement says. ``format_sql`` therefore
compares the formatter's output with the input, ignoring only whitespace and the case of unquoted words, and returns
the input untouched when anything else differs. Quoted text (string literals and quoted identifiers) is compared
exactly, so a value is never altered. The result is also run on SQLite and must return the rows the original does.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

import pytest
import sqlparse

from query_builder import QueryCompiler, format_sql
from query_builder.runnable import _fingerprint

LONG = (
    'SELECT "orders"."id", "customers"."region" FROM "orders" '
    'INNER JOIN "customers" ON "orders"."customer_id" = "customers"."id" '
    'WHERE ("customers"."region" = \'east\' AND "orders"."id" IN (1, 2)) '
    'ORDER BY "orders"."id" LIMIT 20 OFFSET 0'
)


def test_a_statement_is_laid_out_one_clause_per_line_with_keywords_in_capitals() -> (
    None
):
    out = format_sql(
        LONG.replace("SELECT", "select")
        .replace("INNER JOIN", "inner join")
        .replace("WHERE", "where")
    )
    assert out is not None
    lines = out.splitlines()
    assert lines[0].startswith("SELECT ")
    for clause in ("INNER JOIN ", "WHERE ", "ORDER BY ", "LIMIT "):
        assert any(line.startswith(clause) for line in lines), clause


def test_laying_out_never_changes_what_the_statement_says() -> None:
    out = format_sql(LONG)
    assert out is not None and out != LONG
    assert _fingerprint(out) == _fingerprint(LONG)


def test_a_string_value_keeps_its_exact_text_including_spaces_and_keywords() -> None:
    sql = "SELECT a FROM t WHERE n = 'select   from  where --  x' AND m = 'it''s'"
    out = format_sql(sql)
    assert out is not None
    assert "'select   from  where --  x'" in out and "'it''s'" in out


def test_a_quoted_name_is_not_changed() -> None:
    out = format_sql('SELECT "select", "Mixed Case", `back tick` FROM "from"')
    assert out is not None
    for name in ('"select"', '"Mixed Case"', "`back tick`", '"from"'):
        assert name in out


def test_a_value_that_looks_like_sql_stays_a_value() -> None:
    sql = "SELECT 1 FROM t WHERE n = 'x''; DROP TABLE t; --'"
    out = format_sql(sql)
    assert out is not None and "'x''; DROP TABLE t; --'" in out
    assert (
        out.replace("'x''; DROP TABLE t; --'", "").count(";") == 0
    )  # none outside the value


@pytest.mark.parametrize("empty", [None, ""])
def test_nothing_in_gives_nothing_out(empty: str | None) -> None:
    assert format_sql(empty) == empty


def test_the_input_is_returned_when_the_formatter_would_change_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The control for the guard: with a formatter that damages the text, the original must come back.
    monkeypatch.setattr(sqlparse, "format", lambda sql, **_: sql.replace("1", "2"))
    assert format_sql("SELECT 1") == "SELECT 1"


def test_the_input_is_returned_when_the_formatter_changes_a_value_but_only_in_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Case may differ for words, never inside quotes: a formatter that upper-cases a literal must be refused.
    monkeypatch.setattr(
        sqlparse, "format", lambda sql, **_: sql.replace("'east'", "'EAST'")
    )
    assert format_sql("SELECT 1 WHERE r = 'east'") == "SELECT 1 WHERE r = 'east'"


def test_the_input_is_returned_when_the_formatter_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(sql: str, **_: Any) -> str:
        raise RuntimeError("formatter failed")

    monkeypatch.setattr(sqlparse, "format", boom)
    assert format_sql("SELECT 1") == "SELECT 1"


def test_formatting_is_idempotent() -> None:
    once = format_sql(LONG)
    assert once is not None and format_sql(once) == once


def test_a_large_statement_is_formatted_in_reasonable_time() -> None:
    sql = "SELECT a FROM t WHERE " + " AND ".join(f"c{i} = {i}" for i in range(2000))
    started = time.perf_counter()
    out = format_sql(sql)
    assert out is not None and time.perf_counter() - started < 10


def test_the_fingerprint_ignores_whitespace_and_word_case_but_not_quoted_text() -> None:
    assert _fingerprint("select  a\n from t") == _fingerprint("SELECT a FROM t")
    assert _fingerprint("x = 'a b'") != _fingerprint("x = 'a  b'")
    assert _fingerprint("x = 'a'") != _fingerprint("x = 'A'")
    assert _fingerprint('"a b"') != _fingerprint('"a  b"')
    assert _fingerprint("-- one\nSELECT 1") != _fingerprint("-- two\nSELECT 1")


# --- compile_runnable(pretty=True) --------------------------------------------------------------------------------------

SCHEMA = {
    "tables": {
        "orders": {
            "name": "orders",
            "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "status", "type": "TEXT"},
                {"name": "total", "type": "REAL"},
            ],
        }
    }
}


@pytest.fixture
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE orders (id INTEGER, status TEXT, total REAL)")
    connection.executemany(
        "INSERT INTO orders VALUES (?, ?, ?)",
        [(1, "open", 5.5), (2, "closed", 7.0), (3, "open", 1.25)],
    )
    return connection


def spec() -> dict[str, Any]:
    return {
        "table": "orders",
        "columns": ["orders.id", "orders.status", "orders.total"],
        "filters": [
            {"column": "orders.status", "op": "eq", "value": "open"},
            {"column": "orders.total", "op": "gt", "value": 1},
        ],
        "order_by": [{"column": "id", "tablePrefix": "orders", "direction": "ASC"}],
        "limit": 10,
    }


def test_pretty_gives_the_same_statement_laid_out_and_it_returns_the_same_rows(
    conn: sqlite3.Connection,
) -> None:
    compiler = QueryCompiler(spec(), schema=SCHEMA, dialect="sqlite")
    plain = compiler.compile_runnable()
    pretty = QueryCompiler(spec(), schema=SCHEMA, dialect="sqlite").compile_runnable(
        pretty=True
    )
    assert plain is not None and pretty is not None
    assert _fingerprint(pretty) == _fingerprint(plain)
    assert (
        conn.execute(pretty).fetchall()
        == conn.execute(plain).fetchall()
        == [(1, "open", 5.5), (3, "open", 1.25)]
    )


def test_pretty_is_off_by_default() -> None:
    plain = QueryCompiler(spec(), schema=SCHEMA, dialect="sqlite").compile_runnable()
    assert plain == QueryCompiler(
        spec(), schema=SCHEMA, dialect="sqlite"
    ).compile_runnable(pretty=False)


def test_pretty_keeps_a_value_with_sql_in_it_as_a_value(
    conn: sqlite3.Connection,
) -> None:
    hostile = spec()
    hostile["filters"] = [
        {"column": "orders.status", "op": "eq", "value": "x'; DROP TABLE orders; --"}
    ]
    pretty = QueryCompiler(hostile, schema=SCHEMA, dialect="sqlite").compile_runnable(
        pretty=True
    )
    assert pretty is not None and "'x''; DROP TABLE orders; --'" in pretty
    assert conn.execute(pretty).fetchall() == []
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone() == (3,)


def test_a_dialect_that_cannot_be_rendered_is_still_none_with_pretty() -> None:
    assert (
        QueryCompiler(spec(), schema=SCHEMA, dialect="cosmosdb").compile_runnable(
            pretty=True
        )
        is None
    )


# --- comments are compared exactly -------------------------------------------------------------------------------------


def test_a_block_comment_is_kept_as_written_and_the_fingerprint_notices_a_change_inside_it() -> (
    None
):
    assert _fingerprint("SELECT /* keep  this */ 1") != _fingerprint(
        "SELECT /* keep this */ 1"
    )
    assert _fingerprint("select /* keep this */ 1") == _fingerprint(
        "SELECT  /* keep this */\n1"
    )
    out = format_sql("SELECT /* keep   this */ 1 FROM t")
    assert out is not None and "/* keep   this */" in out


def test_an_unterminated_comment_runs_to_the_end_and_does_not_hang_or_crash() -> None:
    assert _fingerprint("SELECT 1 /* never closed  ") == "select1/* never closed  "
    assert _fingerprint("SELECT 1 -- no newline  ") == "select1-- no newline  "
    assert format_sql("SELECT 1 /* never closed") is not None
