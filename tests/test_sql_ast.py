"""Unit tests for the sqlglot structural layer (``query_builder.sql_ast``) and its
integration into ``validate_sql_ast`` (union of layers, tagging, dialect keyword)."""

from __future__ import annotations

import pytest

from query_builder import sql_ast
from query_builder.ast_validator import AST_LAYER_TAG, validate_sql_ast
from query_builder.sql_ast import analyze_sql, resolve_dialects


def _tables(sql: str, dialect: str | None = None):
    return [
        (t.qualified, t.is_cte, t.is_function) for t in analyze_sql(sql, dialect).tables
    ]


def test_analysis_shape() -> None:
    a = analyze_sql(
        "WITH c AS (SELECT 1) SELECT x, count(*) FROM main.orders o JOIN c ON 1=1 GROUP BY x",
        "sqlite",
    )
    assert a.parsed and a.read_only
    assert a.statement_count == 1 and a.statement_types == ("SELECT",)
    assert ("main.orders", False, False) in _tables(
        "SELECT * FROM main.orders", "sqlite"
    )
    assert "COUNT" in a.functions
    assert a.cte_names == ("c",)
    assert a.dialects_parsed == ("sqlite",)


def test_cte_shadowing_is_scoped() -> None:
    # The inner reference is NOT the CTE (a non-recursive CTE cannot see itself).
    t = _tables("WITH auth_user AS (SELECT * FROM auth_user) SELECT * FROM auth_user")
    assert ("auth_user", False, False) in t and ("auth_user", True, False) in t
    # Recursive CTEs do see themselves.
    t = _tables(
        "WITH RECURSIVE r AS (SELECT 1 UNION ALL SELECT * FROM r) SELECT * FROM r"
    )
    assert all(is_cte for _n, is_cte, _f in t)
    # Earlier CTEs are visible to later ones, later ones are not visible to earlier ones.
    t = _tables("WITH a AS (SELECT * FROM b), b AS (SELECT 1) SELECT * FROM a")
    assert ("b", False, False) in t
    t = _tables("WITH a AS (SELECT 1), b AS (SELECT * FROM a) SELECT * FROM b")
    assert all(is_cte for _n, is_cte, _f in t)
    # A schema-qualified name is never a CTE reference.
    t = _tables("WITH a AS (SELECT 1) SELECT * FROM main.a")
    assert ("main.a", False, False) in t
    # Quoted vs unquoted names with different case do not shadow each other.
    t = _tables('WITH "Auth_User" AS (SELECT 1) SELECT * FROM auth_user')
    assert ("auth_user", False, False) in t


@pytest.mark.parametrize(
    "sql",
    [
        "WITH auth_user AS (SELECT * FROM auth_user) SELECT * FROM auth_user",
        "SELECT * FROM auth_user AS harmless",
        "SELECT * FROM harmless h JOIN auth_user u ON 1=1",
        "SELECT (SELECT password FROM auth_user)",
        "SELECT * FROM orders WHERE id IN (SELECT id FROM auth_user)",
        "SELECT * FROM 'auth_user'",
        "SELECT * FROM main.auth_user",
        "SELECT * FROM db..auth_user",
        "SELECT 1 UNION SELECT * FROM auth_user",
        "SELECT * FROM mysql.user",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM public.orders",
    ],
)
def test_restricted_tables_rejected_by_ast_layer(sql: str) -> None:
    res = validate_sql_ast(sql)
    assert not res["valid"]
    assert res["violation_layers"]["sqlglot_ast"], res


def test_cte_alias_does_not_hide_or_trigger() -> None:
    ok = validate_sql_ast("WITH auth_user AS (SELECT 1 AS id) SELECT * FROM auth_user")
    # The AST layer correctly treats the reference as the CTE (no AST violation); only the
    # conservative legacy layer still objects, and the result is the union.
    assert ok["violation_layers"]["sqlglot_ast"] == []
    assert not ok["valid"]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; SELECT 2",
        "SELECT 1; DROP TABLE x",
        "TABLE auth_user",
        "VALUES (1)",
        "DELETE FROM orders",
        "INSERT INTO orders VALUES (1)",
        "SELECT * INTO x FROM orders",
        "SELECT * FROM orders FOR UPDATE",
        "WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x",
        "EXPLAIN SELECT 1",
        "PRAGMA writable_schema=1",
        "SELECT FROM WHERE",
    ],
)
def test_non_read_only_rejected(sql: str) -> None:
    res = validate_sql_ast(sql)
    assert not res["valid"]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT * FROM read_csv('x.csv')",
        "SELECT * FROM 'data.csv'",
        "SELECT * FROM pragma_table_info('orders')",
        "SELECT load_extension('x')",
        "SELECT * FROM OPENROWSET('a', 'b', 'c')",
        "SELECT * FROM pg_catalog.pg_read_file('x')",
        "SELECT dbms_xmlgen.getxml('select 1') FROM dual",
    ],
)
def test_denied_functions_and_files_rejected(sql: str) -> None:
    res = validate_sql_ast(sql)
    assert not res["valid"]
    assert res["violation_layers"]["sqlglot_ast"], res


def test_fail_closed_on_unparsable_and_recursion() -> None:
    a = analyze_sql("SELECT FROM WHERE (((", "postgres")
    assert not a.parsed and a.errors
    res = validate_sql_ast("SELECT FROM WHERE (((")
    assert not res["valid"]
    assert any("failing closed" in v for v in res["violations"])
    deep = "SELECT " + "(" * 3000 + "1" + ")" * 3000
    validate_sql_ast(deep)  # must not raise (deep nesting fails closed or is accepted)
    assert not analyze_sql("SELECT " + "(" * 20000 + "1", "postgres").parsed


def test_layers_are_tagged_and_unioned() -> None:
    res = validate_sql_ast("SELECT * FROM auth_user")
    assert not res["valid"]
    assert res["violation_layers"]["legacy"]
    assert all(
        v.startswith(AST_LAYER_TAG) for v in res["violation_layers"]["sqlglot_ast"]
    )
    assert set(res["violations"]) >= set(res["violation_layers"]["legacy"])
    assert set(res["violations"]) >= set(res["violation_layers"]["sqlglot_ast"])


def test_dialect_selection() -> None:
    assert resolve_dialects("mysql") == ("mysql",)
    assert resolve_dialects("TiDB") == ("mysql",)
    assert resolve_dialects("duckdb") == ("duckdb",)
    assert resolve_dialects("snowflake") == ("snowflake",)
    assert resolve_dialects("doris") == ("doris",)
    assert resolve_dialects(None) == tuple(sql_ast.FALLBACK_DIALECTS)
    assert resolve_dialects("totally_unknown") == tuple(sql_ast.FALLBACK_DIALECTS)
    assert resolve_dialects("neo4j") == tuple(sql_ast.FALLBACK_DIALECTS)


def test_union_of_dialects_reports_any_unsafe_interpretation() -> None:
    # Parses under several dialects; the restricted table is visible in all of them.
    assert not validate_sql_ast("SELECT a FROM auth_user LIMIT 1")["valid"]
    # Backslash escapes differ (MySQL vs standard): both interpretations are analysed.
    q = "SELECT '\\' FROM auth_user -- '"
    assert not validate_sql_ast(q)["valid"]


def test_placeholders_are_parsed() -> None:
    for sql in (
        "SELECT * FROM t WHERE a = %s LIMIT %s",
        "SELECT * FROM t WHERE a = %(a)s",
        "SELECT * FROM t WHERE a = $1",
        "SELECT * FROM t WHERE a = $name",
        "SELECT * FROM t WHERE a = ? SKIP ? LIMIT ?",
        "SELECT '%s $1' FROM t WHERE a = $1",
    ):
        assert analyze_sql(sql, "mysql").parsed, sql
    # Placeholders inside literals/comments are left alone.
    assert (
        sql_ast._normalize_placeholders("SELECT '%s' -- %s\n, %s")
        == "SELECT '%s' -- %s\n, ?"
    )


def test_unavailable_sqlglot_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    a = sql_ast.SqlAnalysis(parsed=False, unavailable=True)
    out = sql_ast.evaluate_policy(
        a,
        restricted_tables=set(),
        schema_patterns=[],
        allowed_schemas_upper=set(),
        denied_functions=set(),
        denied_function_prefixes=("X_",),
        denied_keywords=set(),
    )
    assert out and "not installed" in out[0]


def test_cte_policy_flags() -> None:
    assert not validate_sql_ast(
        "WITH a AS (SELECT 1) SELECT * FROM a", allow_cte=False
    )["valid"]
    assert not validate_sql_ast("WITH RECURSIVE a AS (SELECT 1) SELECT * FROM a")[
        "valid"
    ]
    assert validate_sql_ast(
        "WITH RECURSIVE a AS (SELECT 1) SELECT * FROM a", allow_recursive_cte=True
    )["valid"]


def test_allowed_schemas_unblocks_public() -> None:
    assert not validate_sql_ast("SELECT * FROM public.orders")["valid"]
    assert validate_sql_ast("SELECT * FROM public.orders", allowed_schemas=["public"])[
        "valid"
    ]
