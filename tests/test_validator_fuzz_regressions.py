"""Permanent minimal repros for false negatives found by the differential fuzzers."""

from __future__ import annotations

import pytest

from query_builder.ast_validator import validate_sql_ast


def test_unterminated_block_comment_is_a_comment_not_a_syntax_error() -> None:
    """Found by the SQLite oracle.

    SQLite (unlike PostgreSQL/MySQL) accepts an unterminated ``/*`` comment running to the
    end of input, and treats ``$$`` as a bind-parameter name.  The legacy lexer used to
    classify the SQLite interpretation as a syntax error (dangling comment) and discard
    it, validating only the PostgreSQL dollar-quote reading in which ``FROM auth_user`` is
    inside a string -- so a query that SQLite executes against ``auth_user`` was accepted.
    """
    sql = "SELECT $$ FROM auth_user/* $$"
    for dialect in (None, "sqlite"):
        assert not validate_sql_ast(sql, dialect=dialect)["valid"]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT $$ FROM auth_user/* $$",
        "SELECT $$ FROM auth_user /* $a$",
        "SELECT 1 FROM auth_user /* never closed",
        "SELECT 1 /* x */ FROM auth_user /*",
    ],
)
def test_unterminated_block_comment_does_not_hide_code_before_it(sql: str) -> None:
    assert not validate_sql_ast(sql)["valid"]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM pragma_table_info('auth_user')",
        "SELECT * FROM pragma_database_list",
        "SELECT name FROM pragma_function_list()",
        "SELECT * FROM PRAGMA_table_xinfo('orders')",
    ],
)
def test_pragma_table_valued_functions_are_denied(sql: str) -> None:
    """Found by the SQLite oracle: ``pragma_*`` table functions expose schema/metadata of
    restricted tables (the authorizer reports a PRAGMA action)."""
    for dialect in (None, "sqlite"):
        assert not validate_sql_ast(sql, dialect=dialect)["valid"]
