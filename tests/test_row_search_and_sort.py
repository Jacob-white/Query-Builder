"""Searching every row of a result, and sorting by a count or total.

Both were found by running a real application on top of the library: a grouped query sorted by its count compiled
but the database refused it, and a result paged by the database could only be searched a page at a time. The tests run
the SQL on a real SQLite database rather than comparing strings alone, and the search has adversarial terms (SQL, LIKE
wildcards) with controls.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from query_builder import QueryCompiler, validate_sql_ast
from query_builder.exceptions import CompilationError

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

ROWS = [
    (1, "alpha", "a"),
    (2, "ALPHABET", "a"),
    (3, "beta", "b"),
    (4, "100% sure", "b"),
    (5, "plain", "c"),
    (6, "o'brien", "c"),
    (7, "gamma", "c"),
]


@pytest.fixture
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE account (id INTEGER, name TEXT, kind TEXT)")
    connection.executemany("INSERT INTO account VALUES (?, ?, ?)", ROWS)
    return connection


def _compiler(spec: dict[str, Any], dialect: str = "sqlite") -> QueryCompiler:
    return QueryCompiler(spec, schema=SCHEMA, dialect=dialect)


def _plain(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    return {
        "table": "account",
        "columns": ["account.id", "account.name"],
        "order_by": [{"column": "id", "tablePrefix": "account", "direction": "ASC"}],
        "limit": limit,
        "offset": offset,
    }


def _search(
    conn: sqlite3.Connection, spec: dict[str, Any], term: str
) -> tuple[list[Any], int]:
    sql, params, count_sql, count_params = _compiler(spec).compile_search(term)
    return conn.execute(sql, params).fetchall(), conn.execute(
        count_sql, count_params
    ).fetchone()[0]


# --------------------------------------------------------------------------
# Sorting by a count or total
# --------------------------------------------------------------------------

GROUPED = {
    "table": "account",
    "columns": ["account.kind", {"column": "account.id", "agg": "count", "alias": "n"}],
    "limit": 10,
}


def test_a_grouped_query_sorts_by_its_count_and_the_database_accepts_it(
    conn: sqlite3.Connection,
) -> None:
    spec = {**GROUPED, "order_by": [{"column": "n", "direction": "DESC"}]}
    sql, params, _, _ = _compiler(spec).compile()
    assert 'ORDER BY "n" DESC' in sql
    rows = conn.execute(sql, params).fetchall()
    assert rows[0] == ("c", 3)
    assert [n for _, n in rows] == sorted((n for _, n in rows), reverse=True)


def test_a_default_named_aggregate_can_be_sorted_by_name(
    conn: sqlite3.Connection,
) -> None:
    spec = {
        "table": "account",
        "columns": ["account.kind", {"column": "account.id", "agg": "sum"}],
        "order_by": [{"column": "sum_account_id", "direction": "ASC"}],
    }
    sql, params, _, _ = _compiler(spec).compile()
    assert 'ORDER BY "sum_account_id" ASC' in sql
    assert conn.execute(sql, params).fetchall()


def test_sorting_by_a_grouping_column_is_unchanged() -> None:
    spec = {
        **GROUPED,
        "order_by": [{"column": "kind", "tablePrefix": "account", "direction": "ASC"}],
    }
    sql = _compiler(spec).compile()[0]
    assert 'ORDER BY "t1"."kind" ASC' in sql


def test_a_name_with_a_table_prefix_is_a_column_not_an_aggregate_label() -> None:
    # Control: the same name, but pointed at a table, still means that table's column.
    spec = {
        **GROUPED,
        "order_by": [{"column": "n", "tablePrefix": "account", "direction": "DESC"}],
    }
    assert 'ORDER BY "t1"."n" DESC' in _compiler(spec).compile()[0]


def test_a_plain_column_that_shares_a_label_is_not_treated_as_an_aggregate() -> None:
    spec = {
        "table": "account",
        "columns": [{"column": "account.name", "alias": "kind"}],
        "order_by": [{"column": "kind", "direction": "ASC"}],
    }
    assert 'ORDER BY "t1"."kind" ASC' in _compiler(spec).compile()[0]


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------


def test_a_search_keeps_the_rows_where_any_column_contains_the_text_case_insensitively(
    conn: sqlite3.Connection,
) -> None:
    rows, total = _search(conn, _plain(), "alpha")
    assert rows == [(1, "alpha"), (2, "ALPHABET")]
    assert total == 2


def test_a_search_matches_non_text_columns_too(conn: sqlite3.Connection) -> None:
    rows, total = _search(conn, _plain(), "4")
    assert rows == [(4, "100% sure")]
    assert total == 1


def test_the_spec_limit_and_offset_page_the_matches_not_the_whole_result(
    conn: sqlite3.Connection,
) -> None:
    first, total = _search(conn, _plain(limit=1, offset=0), "a")
    second, _ = _search(conn, _plain(limit=1, offset=1), "a")
    everything, _ = _search(conn, _plain(limit=50), "a")
    assert total == len(everything) >= 3
    assert [first[0], second[0]] == everything[:2]  # no gap, no repeat
    past_end, _ = _search(conn, _plain(limit=5, offset=500), "a")
    assert past_end == []


def test_the_search_is_not_cut_off_by_a_page_cap_on_the_inner_query(
    conn: sqlite3.Connection,
) -> None:
    # The inner query is compiled with no LIMIT of its own, so a match beyond the first page of the unsearched result is found.
    spec = _plain(limit=2)
    unsearched, _, _, _ = _compiler(spec).compile()
    assert "LIMIT" in unsearched
    rows, total = _search(conn, spec, "gamma")
    assert rows == [(7, "gamma")]
    assert total == 1


def test_percent_and_underscore_in_the_term_match_themselves(
    conn: sqlite3.Connection,
) -> None:
    assert _search(conn, _plain(), "100%")[0] == [(4, "100% sure")]
    assert _search(conn, _plain(), "%")[0] == [
        (4, "100% sure")
    ]  # control: % does not mean "anything"
    assert _search(conn, _plain(), "pl_in")[0] == []  # "_" is not "any one character"
    assert (
        _search(conn, _plain(), "!")[1] == 0
    )  # the escape character itself is literal too


def test_a_term_that_looks_like_sql_is_only_text(conn: sqlite3.Connection) -> None:
    sql, params, count_sql, count_params = _compiler(_plain()).compile_search(
        "x'); DROP TABLE account; --"
    )
    assert "DROP" not in sql
    assert conn.execute(sql, params).fetchall() == []
    assert conn.execute(count_sql, count_params).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM account").fetchone()[0] == len(
        ROWS
    )  # the table is intact


def test_a_quote_in_the_term_is_searched_for_literally(
    conn: sqlite3.Connection,
) -> None:
    assert _search(
        conn, {**_plain(), "columns": ["account.id", "account.name"]}, "o'b"
    )[0] == [(6, "o'brien")]


def test_a_grouped_query_is_searched_on_its_grouped_output(
    conn: sqlite3.Connection,
) -> None:
    rows, total = _search(
        conn, {**GROUPED, "order_by": [{"column": "n", "direction": "DESC"}]}, "b"
    )
    assert rows == [("b", 2)]
    assert total == 1


def test_the_wrapped_sql_passes_the_safety_validator() -> None:
    sql = _compiler(_plain()).compile_search("alpha")[0]
    assert validate_sql_ast(sql, dialect="sqlite")["valid"] is True


def test_the_count_query_counts_the_matches_and_ignores_paging(
    conn: sqlite3.Connection,
) -> None:
    _, _, count_sql, count_params = _compiler(_plain(limit=1)).compile_search("a")
    assert "LIMIT" not in count_sql.upper()
    assert conn.execute(count_sql, count_params).fetchone()[0] >= 3


def test_postgres_uses_ilike_and_mysql_casts_to_char() -> None:
    pg = _compiler(_plain(), "postgres").compile_search("a")[0]
    assert "ILIKE" in pg and "AS TEXT" in pg and "ESCAPE '!'" in pg
    my = _compiler(_plain(), "mysql").compile_search("a")[0]
    assert "AS CHAR" in my and "ESCAPE '!'" in my


def test_parameters_are_in_the_order_the_placeholders_appear() -> None:
    sql, params, count_sql, count_params = _compiler(
        {
            **_plain(limit=7, offset=3),
            "filters": [
                {"column": "kind", "tablePrefix": "account", "op": "=", "value": "k"}
            ],
        },
        "postgres",
    ).compile_search("zz")
    assert sql.count("%s") == len(params)
    assert params[0] == "k" and params[-2:] == [7, 3]
    assert count_sql.count("%s") == len(count_params)
    assert params[1:3] == ["%zz%", "%zz%"] == count_params[1:3]


def test_a_search_is_one_extra_compile_not_a_change_to_the_plain_one() -> None:
    compiler = _compiler(_plain(limit=5))
    plain = compiler.compile()[0]
    assert "LIMIT" in plain
    again = _compiler(_plain(limit=5)).compile()[0]
    assert plain == again


@pytest.mark.parametrize("term", ["", "   "])
def test_an_empty_term_is_refused(term: str) -> None:
    with pytest.raises(CompilationError, match="must not be empty"):
        _compiler(_plain()).compile_search(term)


def test_an_over_long_term_is_refused_and_the_limit_itself_is_allowed() -> None:
    with pytest.raises(CompilationError, match="at most 200"):
        _compiler(_plain()).compile_search("x" * 201)
    assert _compiler(_plain()).compile_search("x" * 200)[0]


def test_a_dialect_without_a_text_cast_is_refused() -> None:
    with pytest.raises(
        CompilationError, match="not supported for the 'cosmosdb' dialect"
    ):
        _compiler(_plain(), "cosmosdb").compile_search("a")


def test_a_query_that_selects_star_has_no_named_columns_to_search() -> None:
    with pytest.raises(CompilationError, match="needs named columns"):
        _compiler({"table": "account", "columns": ["*"]}).compile_search("a")
