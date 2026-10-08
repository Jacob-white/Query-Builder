"""Single-pass, dialect-aware lexing for ``validate_sql_ast`` (ISSUE 1).

The validator has no dialect parameter, so text is lexed under every interpretation that
dialects disagree on (backslash escapes, ``#`` comments, dollar quoting, brackets, nested
comments, MySQL ``--`` rule) and the union of violations is reported.
"""

from __future__ import annotations

import pytest

from query_builder.ast_validator import (
    strip_sql_comments_and_literals,
    validate_sql_ast,
)


def _invalid(sql: str) -> dict:
    res = validate_sql_ast(sql)
    assert res["valid"] is False, f"expected denial for: {sql!r} -> {res}"
    return res


def _valid(sql: str) -> dict:
    res = validate_sql_ast(sql)
    assert res["valid"] is True, f"expected valid for: {sql!r} -> {res['violations']}"
    return res


@pytest.mark.parametrize(
    "sql",
    [
        # `--` inside a string literal must not truncate the text the checks see
        "SELECT '--' AS x FROM auth_user",
        "SELECT '--' FROM sqlite_master",
        "SELECT '--' AS x FROM pg_catalog.pg_authid",
        "SELECT '--' AS x, password FROM auth_user",
        "SELECT '-- x' || a FROM credentials",
        # `--` inside quoted identifiers
        'SELECT "--" FROM auth_user',
        "SELECT `--` FROM auth_user",
        "SELECT [--] FROM auth_user",
        # `/*` inside a literal must not open a comment that hides code
        "SELECT '/*' AS x FROM auth_user WHERE a = '*/'",
        # `#` MySQL line comment hiding a newline-separated table
        "SELECT * FROM #x\nauth_user",
        # dollar quoting hiding a quote
        "SELECT $$ ' $$ FROM auth_user WHERE x = $$ ' $$",
        "SELECT $q$ ' $q$ FROM auth_user WHERE x = $q$ ' $q$",
        # nested block comments (PG) vs flat (everyone else)
        "SELECT 1 /* a /* b */ FROM auth_user */",
        # MySQL: `--` not followed by whitespace is not a comment
        "SELECT 1 --1 FROM auth_user",
    ],
)
def test_literal_and_comment_lexing_cannot_hide_restricted_tables(sql: str) -> None:
    _invalid(sql)


@pytest.mark.parametrize(
    "sql",
    [
        # Backslash is an ordinary character in SQLite / PG / DuckDB / SQL Server, so
        # `'\'` is a complete literal and the DROP is a separate statement there.
        "SELECT '\\'; DROP TABLE users; SELECT '' --'",
        "SELECT '\\'; SELECT 1 FROM auth_user; SELECT '",
        "SELECT '\\' ; DELETE FROM t WHERE a = '' --'",
    ],
)
def test_backslash_quote_ambiguity_is_fail_closed(sql: str) -> None:
    res = _invalid(sql)
    assert any(
        "Multiple statements" in v or "keyword" in v.lower() or "pattern" in v.lower()
        for v in res["violations"]
    )


def test_stacked_statement_hidden_by_dollar_quote_interpretation() -> None:
    # PG sees one dollar-quoted literal; other dialects see a second statement.
    res = _invalid("SELECT $$ x $$ ; SELECT 1")
    assert any("Multiple statements" in v for v in res["violations"])


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 'it''s' FROM t",
        "SELECT 'it\\'s' FROM t",
        "SELECT 'it\\'s a drop' AS note FROM t",
        "SELECT 'a\\\\' FROM t",
        "SELECT '--' AS x FROM t",
        "SELECT '/* not a comment' AS x FROM t",
        "SELECT a # b FROM t",  # PostgreSQL bitwise XOR operator
        "SELECT a #> '{x}' FROM t",  # PostgreSQL JSON path operator
        "SELECT $1, a FROM t WHERE b = $2",
        "SELECT price$ FROM t",
        "SELECT arr[1], arr[i + 1] FROM t",
        "SELECT a FROM t -- trailing comment ; DROP TABLE x",
        "SELECT a FROM t /* ; DROP TABLE x */",
        "SELECT ';' AS semi FROM t",
        'SELECT "a;b" FROM t',
        "SELECT [my col] FROM t",
        "SELECT [drop], [delete] FROM t",
        "SELECT a FROM t;",
        "SELECT 1 /* a /* b */ c */ FROM t",
        "SELECT 'x' AS note -- keep\nFROM t",
    ],
)
def test_ordinary_queries_stay_valid(sql: str) -> None:
    _valid(sql)


def test_strip_helper_is_single_pass() -> None:
    # `--` inside the literal must not eat the closing quote or the rest of the query
    stripped = strip_sql_comments_and_literals("SELECT '--' AS x FROM auth_user")
    assert stripped == "SELECT '' AS x FROM auth_user"
    assert (
        strip_sql_comments_and_literals("SELECT 'a''b' /* c */ FROM t -- d")
        == "SELECT ''   FROM t  "
    )
    # quoted identifiers are preserved verbatim
    assert '"--"' in strip_sql_comments_and_literals('SELECT "--" FROM t')


def test_unterminated_interpretation_does_not_cause_false_positive() -> None:
    # With "backslash is ordinary" this leaves a dangling quote (a syntax error on those
    # engines), so that interpretation must not turn the literal text into code.
    _valid("SELECT 'user\\'s delete action' AS note FROM users")
    _valid("SELECT 'x' AS a, 'it\\'s drop' AS b FROM users")
