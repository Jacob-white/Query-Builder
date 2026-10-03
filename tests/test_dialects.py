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

    # Databricks
    dbx = get_dialect("databricks")
    assert dbx.name == "databricks"
    assert dbx.placeholder == "%s"
    assert dbx.quote_identifier("catalog.schema.table") == "`catalog`.`schema`.`table`"
    assert dbx.quote_alias("my`alias") == "`my``alias`"
    assert dbx.format_ilike("`c`") == "LOWER(`c`) LIKE LOWER(%s)"
    assert get_dialect("spark").name == "databricks"

    # Athena
    ath = get_dialect("athena")
    assert ath.name == "athena"
    assert ath.placeholder == "?"
    assert ath.format_ilike('"c"') == 'LOWER("c") LIKE LOWER(?)'

    # Polars
    pol = get_dialect("polars")
    assert pol.name == "polars"
    assert pol.placeholder == "?"
    assert pol.format_ilike('"c"') == '"c" ILIKE ?'

    # DataFusion
    df = get_dialect("datafusion")
    assert df.name == "datafusion"
    assert df.placeholder == "?"
    assert df.format_ilike('"c"') == 'LOWER("c") LIKE LOWER(?)'

    # Timescale & Cockroach
    assert get_dialect("timescaledb").name == "timescaledb"
    assert get_dialect("timescale").name == "timescaledb"
    assert get_dialect("cockroachdb").name == "cockroachdb"
    assert get_dialect("cockroach").name == "cockroachdb"

    # Spanner
    spn = get_dialect("spanner")
    assert spn.name == "spanner"
    assert spn.quote_identifier("users") == "`users`"
    assert spn.quote_alias("u`a") == "`u``a`"
    assert spn.format_ilike("`c`") == "LOWER(`c`) LIKE LOWER(%s)"

    # QuestDB
    qdb = get_dialect("questdb")
    assert qdb.name == "questdb"
    assert qdb.format_ilike('"c"') == '"c" ILIKE %s'

    # Elasticsearch
    es = get_dialect("elasticsearch")
    assert es.name == "elasticsearch"
    assert es.format_ilike('"c"') == 'LOWER("c") LIKE LOWER(%s)'
    assert get_dialect("opensearch").name == "elasticsearch"

    # DynamoDB
    ddb = get_dialect("dynamodb")
    assert ddb.name == "dynamodb"
    assert ddb.placeholder == "?"
    assert ddb.format_ilike('"c"') == 'LOWER("c") LIKE LOWER(?)'
    clause, params = ddb.format_limit_offset(10, 0)
    assert clause == "LIMIT ?"
    assert params == [10]
    assert get_dialect("partiql").name == "dynamodb"

    # Dremio
    dre = get_dialect("dremio")
    assert dre.name == "dremio"
    assert dre.placeholder == "?"
    assert dre.quote_identifier("users") == '"users"'
    assert dre.quote_alias("my_alias") == '"my_alias"'
    assert dre.format_like('"c"') == '"c" LIKE ?'
    assert dre.format_ilike('"c"') == '"c" ILIKE ?'
    dre_clause, dre_params = dre.format_limit_offset(10, 20)
    assert dre_clause == "LIMIT ? OFFSET ?"
    assert dre_params == [10, 20]

    # Firebolt
    fb = get_dialect("firebolt")
    assert fb.name == "firebolt"
    assert fb.placeholder == "?"
    assert fb.quote_identifier("users") == '"users"'
    assert fb.quote_alias("my_alias") == '"my_alias"'
    assert fb.format_like('"c"') == '"c" LIKE ?'
    assert fb.format_ilike('"c"') == '"c" ILIKE ?'
    fb_clause, fb_params = fb.format_limit_offset(15, 0)
    assert fb_clause == "LIMIT ? OFFSET ?"
    assert fb_params == [15, 0]

    # TiDB
    tidb = get_dialect("tidb")
    assert tidb.name == "tidb"
    assert tidb.placeholder == "%s"
    assert tidb.quote_identifier("users") == "`users`"
    assert tidb.quote_alias("my`alias") == "`my``alias`"
    assert tidb.format_like("`c`") == "`c` LIKE %s"
    assert tidb.format_ilike("`c`") == "LOWER(`c`) LIKE LOWER(%s)"
    tidb_clause, tidb_params = tidb.format_limit_offset(5, 10)
    assert tidb_clause == "LIMIT %s OFFSET %s"
    assert tidb_params == [5, 10]

    # SingleStore
    sstore = get_dialect("singlestore")
    assert sstore.name == "singlestore"
    assert sstore.placeholder == "%s"
    assert sstore.quote_identifier("users") == "`users`"
    assert sstore.quote_alias("my_alias") == "`my_alias`"
    assert sstore.format_like("`c`") == "`c` LIKE %s"
    assert sstore.format_ilike("`c`") == "LOWER(`c`) LIKE LOWER(%s)"
    assert get_dialect("memsql").name == "singlestore"

    # Teradata
    td = get_dialect("teradata")
    assert td.name == "teradata"
    assert td.placeholder == "?"
    assert td.quote_identifier("users") == '"users"'
    assert td.quote_alias('my"alias') == '"my""alias"'
    assert td.format_like('"c"') == '"c" LIKE ?'
    assert td.format_ilike('"c"') == 'LOWER("c") LIKE LOWER(?)'
    td_clause, td_params = td.format_limit_offset(25, 50)
    assert td_clause == "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
    assert td_params == [50, 25]

    # Couchbase
    cb = get_dialect("couchbase")
    assert cb.name == "couchbase"
    assert cb.placeholder == "?"
    assert cb.quote_identifier("travel.airline") == "`travel`.`airline`"
    assert cb.quote_alias("my`alias") == "`my``alias`"
    assert cb.format_like("`c`") == "`c` LIKE ?"
    assert cb.format_ilike("`c`") == "LOWER(`c`) LIKE LOWER(?)"
    cb_clause, cb_params = cb.format_limit_offset(10, 5)
    assert cb_clause == "LIMIT ? OFFSET ?"
    assert cb_params == [10, 5]
    assert get_dialect("n1ql").name == "couchbase"

    # Cloudflare D1
    d1 = get_dialect("d1")
    assert d1.name == "d1"
    assert d1.placeholder == "?"
    assert d1.quote_identifier("users") == '"users"'
    assert d1.quote_alias("my_alias") == '"my_alias"'
    assert d1.format_like('"c"') == '"c" LIKE ?'
    assert d1.format_ilike('"c"') == '"c" LIKE ?'
    assert get_dialect("cloudflare_d1").name == "d1"

    # MongoDB Atlas SQL
    mongo = get_dialect("mongodb")
    assert mongo.name == "mongodb"
    assert mongo.placeholder == "?"
    assert mongo.quote_identifier("users") == '"users"'
    assert mongo.quote_alias("my_alias") == '"my_alias"'
    assert mongo.format_like('"c"') == '"c" LIKE ?'
    assert mongo.format_ilike('"c"') == 'LOWER("c") LIKE LOWER(?)'
    mongo_clause, mongo_params = mongo.format_limit_offset(100, 200)
    assert mongo_clause == "LIMIT ? OFFSET ?"
    assert mongo_params == [100, 200]
    assert get_dialect("mongo").name == "mongodb"
    assert get_dialect("atlas_sql").name == "mongodb"

    # Neon & Supabase
    neon = get_dialect("neon")
    assert neon.name == "neon"
    assert neon.placeholder == "%s"
    assert neon.quote_identifier("users") == '"users"'
    assert neon.quote_alias("my_alias") == '"my_alias"'
    assert neon.format_like('"c"') == '"c" LIKE %s'
    assert neon.format_ilike('"c"') == '"c" ILIKE %s'
    neon_clause, neon_params = neon.format_limit_offset(20, 40)
    assert neon_clause == "LIMIT %s OFFSET %s"
    assert neon_params == [20, 40]

    supa = get_dialect("supabase")
    assert supa.name == "supabase"
    assert supa.placeholder == "%s"
    assert supa.quote_identifier("users") == '"users"'
    assert supa.quote_alias("my_alias") == '"my_alias"'
    assert supa.format_like('"c"') == '"c" LIKE %s'
    assert supa.format_ilike('"c"') == '"c" ILIKE %s'

    # Aliases
    assert get_dialect("postgresql").name == "postgres"
    assert get_dialect("sqlserver").name == "mssql"
    assert get_dialect("unknown_engine").name == "postgres"
