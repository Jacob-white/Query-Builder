import pytest

from query_builder.dialects import (
    DialectError,
    get_dialect,
    quote_alias,
    quote_identifier,
)


def test_quote_identifier_postgres():
    assert quote_identifier("users") == '"users"'
    assert quote_identifier("public.users") == '"public"."users"'
    assert quote_identifier("t1.created_at") == '"t1"."created_at"'


def test_quote_identifier_mssql():
    dialect = get_dialect("mssql")
    assert dialect.quote_identifier("users") == "[users]"
    assert dialect.quote_identifier("dbo.users") == "[dbo].[users]"


def test_quote_identifier_mysql():
    dialect = get_dialect("mysql")
    assert dialect.quote_identifier("users") == "`users`"
    assert dialect.quote_identifier("mydb.users") == "`mydb`.`users`"


def test_quote_identifier_injection_rejection():
    for dialect_name in ["postgres", "mssql", "mysql", "sqlite"]:
        dialect = get_dialect(dialect_name)
        with pytest.raises(DialectError):
            dialect.quote_identifier("users; DROP TABLE users;")
        with pytest.raises(DialectError):
            dialect.quote_identifier("users--comment")
        with pytest.raises(DialectError):
            dialect.quote_identifier("123bad_identifier")


def test_quote_alias_escaping():
    assert quote_alias('user"name', "postgres") == '"user""name"'
    assert quote_alias('col]name', "mssql") == '[col]]name]'
    assert quote_alias('col`name', "mysql") == '`col``name`'


def test_limit_offset_formatting():
    pg = get_dialect("postgres")
    clause, params = pg.format_limit_offset(25, 50)
    assert clause == "LIMIT %s OFFSET %s"
    assert params == [25, 50]

    mssql = get_dialect("mssql")
    clause, params = mssql.format_limit_offset(25, 50)
    assert clause == "OFFSET %s ROWS FETCH NEXT %s ROWS ONLY"
    assert params == [50, 25]


def test_ilike_formatting():
    pg = get_dialect("postgres")
    assert pg.format_ilike('"t1"."name"') == '"t1"."name" ILIKE %s'

    mssql = get_dialect("mssql")
    assert mssql.format_ilike("[t1].[name]") == "LOWER([t1].[name]) LIKE LOWER(%s)"

    sqlite = get_dialect("sqlite")
    assert sqlite.format_ilike('"t1"."name"') == '"t1"."name" LIKE ?'
