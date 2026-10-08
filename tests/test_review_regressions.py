"""Regression tests for code-review findings on the AST validator and Django integration."""

import pytest

from query_builder.ast_validator import validate_sql_ast


def _denied(sql: str, tables: set[str]) -> bool:
    return not validate_sql_ast(sql, restricted_tables=tables)["valid"]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT applysession FROM t",
        "SELECT joinusers FROM t",
        "SELECT fromusers, applyusers, joinusers FROM t",
    ],
)
def test_keyword_prefixed_identifiers_are_not_table_references(sql):
    result = validate_sql_ast(
        sql,
        restricted_tables={
            "APPLYSESSION",
            "JOINUSERS",
            "USERS",
            "FROMUSERS",
            "APPLYUSERS",
        },
    )
    assert not any("Access Denied: Table" in v for v in result["violations"])


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM users",
        "SELECT * FROM(users)",
        'SELECT * FROM"users"',
        "SELECT * FROM a JOIN users ON a.id = users.id",
    ],
)
def test_real_table_references_still_blocked_without_whitespace(sql):
    assert _denied(sql, {"USERS"})


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT core.accounts.id FROM x",
        "SELECT * FROM core.accounts",
        "SELECT * FROM db.core.accounts",
        'SELECT "core"."accounts"."id" FROM x',
    ],
)
def test_schema_qualified_restricted_table_is_blocked_in_any_position(sql):
    assert _denied(sql, {"CORE.ACCOUNTS"})


def test_django_module_import_does_not_require_ninja_settings():
    from query_builder.integrations import django as d

    # Importing never touches ninja (which needs configured Django settings); the alias
    # stays available for type hints and the real classes load lazily.
    assert d.NinjaRouter is not None
    assert callable(d._get_ninja)


def _filter(column, value, combiner=None):
    flt = {"column": column, "op": "=", "value": value}
    if combiner:
        flt["combiner"] = combiner
    return flt


def _where(filters, filter_join):
    from query_builder.compiler import QueryCompiler

    spec = {
        "table": "users",
        "columns": ["a"],
        "filters": filters,
        "filter_join": filter_join,
    }
    sql = QueryCompiler(spec, dialect="sqlite").compile()[0]
    return " ".join(sql.split())


def test_explicit_combiners_preserve_mixed_and_or_precedence():
    """The React client sends a combiner on every filter once any OR exists."""
    sql = _where(
        [_filter("a", 1, "AND"), _filter("b", 2, "AND"), _filter("c", 3, "OR")], "OR"
    )
    assert '"t1"."a" = ? AND "t1"."b" = ? OR "t1"."c" = ?' in sql


def test_missing_combiners_fall_back_to_filter_join():
    """Documents why partial combiners are unsafe: the fallback applies to every gap."""
    sql = _where([_filter("a", 1), _filter("b", 2), _filter("c", 3, "OR")], "OR")
    assert '"t1"."a" = ? OR "t1"."b" = ? OR "t1"."c" = ?' in sql
