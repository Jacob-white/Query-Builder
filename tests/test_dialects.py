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
    assert quote_alias("col]name", "mssql") == "[col]]name]"
    assert quote_alias("col`name", "mysql") == "`col``name`"


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
    assert pg.format_like('"t1"."name"') == '"t1"."name" LIKE %s'

    mssql = get_dialect("mssql")
    assert mssql.format_ilike("[t1].[name]") == "LOWER([t1].[name]) LIKE LOWER(%s)"

    sqlite = get_dialect("sqlite")
    assert sqlite.format_ilike('"t1"."name"') == '"t1"."name" LIKE ?'

    mysql = get_dialect("mysql")
    assert mysql.format_ilike("`t1`.`name`") == "LOWER(`t1`.`name`) LIKE LOWER(%s)"


def test_new_dialects_behavior():
    duck = get_dialect("duckdb")
    assert duck.name == "duckdb"
    assert duck.placeholder == "?"
    assert duck.quote_identifier("users") == '"users"'
    assert duck.format_ilike('"t1"."name"') == '"t1"."name" ILIKE ?'
    clause, params = duck.format_limit_offset(10, 20)
    assert clause == "LIMIT ? OFFSET ?"
    assert params == [10, 20]

    bq = get_dialect("bigquery")
    assert bq.name == "bigquery"
    assert bq.placeholder == "%s"
    assert bq.quote_identifier("project.dataset.table") == "`project`.`dataset`.`table`"
    assert bq.quote_alias("my`alias") == "`my``alias`"
    assert bq.format_ilike("`col`") == "LOWER(`col`) LIKE LOWER(%s)"

    ch = get_dialect("clickhouse")
    assert ch.name == "clickhouse"
    assert ch.placeholder == "%s"
    assert ch.quote_identifier("events") == "`events`"
    assert ch.quote_alias("ev`cnt") == "`ev``cnt`"
    assert ch.format_ilike("`col`") == "`col` ILIKE %s"

    ora = get_dialect("oracle")
    assert ora.name == "oracle"
    assert ora.placeholder == "%s"
    assert ora.quote_identifier("users") == '"users"'
    assert ora.format_ilike('"col"') == 'LOWER("col") LIKE LOWER(%s)'
    ora_clause, ora_params = ora.format_limit_offset(25, 50)
    assert ora_clause == "OFFSET %s ROWS FETCH NEXT %s ROWS ONLY"
    assert ora_params == [50, 25]

    rs = get_dialect("redshift")
    assert rs.name == "redshift"
    assert rs.placeholder == "%s"
    assert rs.format_ilike('"col"') == '"col" ILIKE %s'

    trino = get_dialect("trino")
    assert trino.name == "trino"
    assert trino.placeholder == "?"
    assert (
        trino.quote_identifier("catalog.schema.table") == '"catalog"."schema"."table"'
    )
    assert trino.format_ilike('"col"') == 'LOWER("col") LIKE LOWER(?)'
    trino_clause, trino_params = trino.format_limit_offset(25, 50)
    assert trino_clause == "OFFSET ? LIMIT ?"
    assert trino_params == [50, 25]

    presto = get_dialect("presto")
    assert presto.name == "presto"
    assert presto.placeholder == "?"

    # Aliases
    assert get_dialect("postgresql").name == "postgres"
    assert get_dialect("sqlserver").name == "mssql"
    assert get_dialect("unknown_engine").name == "postgres"
