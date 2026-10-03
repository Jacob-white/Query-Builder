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

    # PrestoDB
    pdb = get_dialect("prestodb")
    assert pdb.name == "presto"

    # Druid
    dr = get_dialect("druid")
    assert dr.name == "druid"
    assert dr.format_ilike('"c"') == 'LOWER("c") LIKE LOWER(%s)'
    assert get_dialect("apache_druid").name == "druid"

    # Pinot
    pi = get_dialect("pinot")
    assert pi.name == "pinot"
    assert pi.format_ilike('"c"') == 'LOWER("c") LIKE LOWER(%s)'
    assert get_dialect("apache_pinot").name == "pinot"

    # StarRocks
    sr = get_dialect("starrocks")
    assert sr.name == "starrocks"
    assert sr.quote_identifier("users") == "`users`"
    assert sr.quote_alias("my`alias") == "`my``alias`"
    assert sr.format_ilike("`c`") == "`c` ILIKE %s"

    # Materialize & RisingWave
    mz = get_dialect("materialize")
    assert mz.name == "materialize"
    assert get_dialect("mz").name == "materialize"
    assert mz.format_ilike('"c"') == '"c" ILIKE %s'

    rw = get_dialect("risingwave")
    assert rw.name == "risingwave"
    assert get_dialect("rw").name == "risingwave"
    assert rw.format_ilike('"c"') == '"c" ILIKE %s'

    # CrateDB & InfluxDB
    crate = get_dialect("cratedb")
    assert crate.name == "cratedb"
    assert get_dialect("crate").name == "cratedb"
    assert crate.format_ilike('"c"') == '"c" ILIKE %s'

    influx = get_dialect("influxdb")
    assert influx.name == "influxdb"
    assert get_dialect("iox").name == "influxdb"
    assert get_dialect("influx").name == "influxdb"
    assert influx.format_ilike('"c"') == '"c" ILIKE %s'

    # AlloyDB & Vertica
    alloy = get_dialect("alloydb")
    assert alloy.name == "alloydb"
    assert alloy.format_ilike('"c"') == '"c" ILIKE %s'

    vert = get_dialect("vertica")
    assert vert.name == "vertica"
    assert vert.format_ilike('"c"') == '"c" ILIKE %s'

    # SAP HANA, OceanBase, ScyllaDB
    hana = get_dialect("saphana")
    assert hana.name == "saphana"
    assert get_dialect("hana").name == "saphana"
    assert get_dialect("sap_hana").name == "saphana"
    assert hana.format_ilike('"c"') == 'LOWER("c") LIKE LOWER(%s)'

    ob = get_dialect("oceanbase")
    assert ob.name == "oceanbase"
    assert ob.quote_identifier("users") == "`users`"

    scylla = get_dialect("scylladb")
    assert scylla.name == "scylladb"
    assert get_dialect("scylla").name == "scylladb"
    assert get_dialect("cassandra").name == "scylladb"
    assert get_dialect("cql").name == "scylladb"
    assert scylla.format_ilike('"c"') == 'LOWER("c") LIKE LOWER(%s)'
    scylla_clause, scylla_params = scylla.format_limit_offset(10, 20)
    assert scylla_clause == "LIMIT %s"
    assert scylla_params == [10]

    # Cassandra
    cas = get_dialect("apache_cassandra")
    assert cas.name == "scylladb"

    # Spark SQL
    spk = get_dialect("sparksql")
    assert spk.name == "sparksql"
    assert get_dialect("pyspark").name == "sparksql"
    assert spk.quote_identifier("db.users") == "`db`.`users`"
    assert spk.quote_alias("my`alias") == "`my``alias`"
    assert spk.format_ilike("`c`") == "`c` ILIKE %s"
    t_sql, t_params = spk.inspect_tables_query("default")
    assert "information_schema.tables" in t_sql and t_params == ["default"]
    c_sql, c_params = spk.inspect_columns_query("default", "users")
    assert "information_schema.columns" in c_sql and c_params == ["default", "users"]
    c_all_sql, c_all_params = spk.inspect_columns_query("default")
    assert "information_schema.columns" in c_all_sql and c_all_params == ["default"]
    pk_sql, pk_params = spk.inspect_primary_keys_query("default", "users")
    assert pk_sql == "" and pk_params == []
    fk_sql, fk_params = spk.inspect_foreign_keys_query("default", "users")
    assert fk_sql == "" and fk_params == []

    # chDB
    ch = get_dialect("chdb")
    assert ch.name == "chdb"
    assert ch.format_ilike("`c`") == "`c` ILIKE %s"

    # GreptimeDB
    grep = get_dialect("greptimedb")
    assert grep.name == "greptimedb"
    assert get_dialect("greptime").name == "greptimedb"
    assert grep.format_ilike('"c"') == '"c" ILIKE %s'
    gt_sql, gt_params = grep.inspect_tables_query("public")
    assert "information_schema.tables" in gt_sql and gt_params == ["public"]
    gc_sql, gc_params = grep.inspect_columns_query("public", "metrics")
    assert "information_schema.columns" in gc_sql and gc_params == ["public", "metrics"]
    gc_all_sql, gc_all_params = grep.inspect_columns_query("public")
    assert "information_schema.columns" in gc_all_sql and gc_all_params == ["public"]

    # TDengine
    td = get_dialect("tdengine")
    assert td.name == "tdengine"
    assert get_dialect("taos").name == "tdengine"
    assert td.quote_identifier("db.meters") == "`db`.`meters`"
    assert td.quote_alias("alias`1") == "`alias``1`"
    assert td.format_ilike("`c`") == "LOWER(`c`) LIKE LOWER(?)"
    td_clause, td_params = td.format_limit_offset(10, 20)
    assert td_clause == "LIMIT ? OFFSET ?" and td_params == [10, 20]
    td_t_sql, td_t_params = td.inspect_tables_query("default")
    assert td_t_sql == "SHOW TABLES;" and td_t_params == []
    td_c_sql, td_c_params = td.inspect_columns_query("default", "meters")
    assert td_c_sql == "DESCRIBE `meters`;" and td_c_params == []
    td_c_all_sql, td_c_all_params = td.inspect_columns_query("default")
    assert td_c_all_sql == "SHOW TABLES;" and td_c_all_params == []

    # SurrealDB
    surr = get_dialect("surrealdb")
    assert surr.name == "surrealdb"
    assert get_dialect("surreal").name == "surrealdb"
    assert surr.quote_identifier("doc.user") == "`doc`.`user`"
    assert surr.quote_alias("al`ias") == "`al``ias`"
    assert (
        surr.format_ilike("`name`")
        == "string::lowercase(`name`) CONTAINS string::lowercase(?)"
    )
    surr_clause, surr_params = surr.format_limit_offset(5, 15)
    assert surr_clause == "LIMIT ? START ?" and surr_params == [5, 15]
    surr_t_sql, surr_t_params = surr.inspect_tables_query("test")
    assert surr_t_sql == "INFO FOR DB;" and surr_t_params == []
    surr_c_sql, surr_c_params = surr.inspect_columns_query("test", "user")
    assert surr_c_sql == "INFO FOR TABLE `user`;" and surr_c_params == []
    surr_c_all_sql, surr_c_all_params = surr.inspect_columns_query("test")
    assert surr_c_all_sql == "INFO FOR DB;" and surr_c_all_params == []

    # ArangoDB
    ar = get_dialect("arangodb")
    assert ar.name == "arangodb"
    assert get_dialect("arango").name == "arangodb"
    assert get_dialect("aql").name == "arangodb"
    assert ar.quote_identifier("c.prop") == "`c`.`prop`"
    assert ar.quote_alias("my`alias") == "`my``alias`"
    assert ar.format_ilike("`title`") == "CONTAINS(LOWER(`title`), LOWER(?))"
    ar_clause, ar_params = ar.format_limit_offset(10, 5)
    assert ar_clause == "LIMIT ?, ?" and ar_params == [5, 10]
    ar_t_sql, ar_t_params = ar.inspect_tables_query("_system")
    assert ar_t_sql == "RETURN COLLECTIONS();" and ar_t_params == []
    ar_c_sql, ar_c_params = ar.inspect_columns_query("_system", "colls")
    assert ar_c_sql == "RETURN COLLECTIONS();" and ar_c_params == []

    # Exasol
    exa = get_dialect("exasol")
    assert exa.name == "exasol"
    assert exa.format_ilike('"col"') == "REGEXP_LIKE(\"col\", ?, 'i')"
    exa_t_sql, exa_t_params = exa.inspect_tables_query("public")
    assert "EXA_ALL_TABLES" in exa_t_sql and exa_t_params == ["PUBLIC"]
    exa_c_sql, exa_c_params = exa.inspect_columns_query("public", "sales")
    assert "EXA_ALL_COLUMNS" in exa_c_sql and exa_c_params == ["PUBLIC", "SALES"]
    exa_c_all_sql, exa_c_all_params = exa.inspect_columns_query("public")
    assert "EXA_ALL_COLUMNS" in exa_c_all_sql and exa_c_all_params == ["PUBLIC"]
    exa_pk_sql, exa_pk_params = exa.inspect_primary_keys_query("public", "sales")
    assert "EXA_ALL_CONSTRAINT_COLUMNS" in exa_pk_sql and exa_pk_params == [
        "PUBLIC",
        "SALES",
    ]
    exa_pk_all_sql, exa_pk_all_params = exa.inspect_primary_keys_query("public")
    assert "EXA_ALL_CONSTRAINT_COLUMNS" in exa_pk_all_sql and exa_pk_all_params == [
        "PUBLIC"
    ]

    # DB2
    db2 = get_dialect("db2")
    assert db2.name == "db2"
    assert get_dialect("ibm_db2").name == "db2"
    assert db2.format_ilike('"name"') == 'LOWER("name") LIKE LOWER(?)'
    db2_clause, db2_params = db2.format_limit_offset(10, 20)
    assert db2_clause == "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY" and db2_params == [
        20,
        10,
    ]
    db2_t_sql, db2_t_params = db2.inspect_tables_query("syscat")
    assert "SYSCAT.TABLES" in db2_t_sql and db2_t_params == ["SYSCAT"]
    db2_c_sql, db2_c_params = db2.inspect_columns_query("syscat", "orders")
    assert "SYSCAT.COLUMNS" in db2_c_sql and db2_c_params == ["SYSCAT", "ORDERS"]
    db2_c_all_sql, db2_c_all_params = db2.inspect_columns_query("syscat")
    assert "SYSCAT.COLUMNS" in db2_c_all_sql and db2_c_all_params == ["SYSCAT"]
    db2_pk_sql, db2_pk_params = db2.inspect_primary_keys_query("syscat", "orders")
    assert "SYSCAT.KEYCOLUSE" in db2_pk_sql and db2_pk_params == ["SYSCAT", "ORDERS"]
    db2_pk_all_sql, db2_pk_all_params = db2.inspect_primary_keys_query("syscat")
    assert "SYSCAT.KEYCOLUSE" in db2_pk_all_sql and db2_pk_all_params == ["SYSCAT"]
    db2_fk_sql, db2_fk_params = db2.inspect_foreign_keys_query("syscat", "orders")
    assert "SYSCAT.REFERENCES" in db2_fk_sql and db2_fk_params == ["SYSCAT", "ORDERS"]
    db2_fk_all_sql, db2_fk_all_params = db2.inspect_foreign_keys_query("syscat")
    assert "SYSCAT.REFERENCES" in db2_fk_all_sql and db2_fk_all_params == ["SYSCAT"]

    # Cosmos DB
    cosmos = get_dialect("cosmosdb")
    assert cosmos.name == "cosmosdb"
    assert get_dialect("azure_cosmos").name == "cosmosdb"
    assert cosmos.format_ilike('"doc"') == 'CONTAINS(LOWER("doc"), LOWER(@param))'
    cos_clause, cos_params = cosmos.format_limit_offset(10, 30)
    assert cos_clause == "OFFSET @param LIMIT @param" and cos_params == [30, 10]
    cos_t_sql, cos_t_params = cosmos.inspect_tables_query("default")
    assert "SELECT VALUE c.id FROM c;" in cos_t_sql and cos_t_params == []
    cos_c_sql, cos_c_params = cosmos.inspect_columns_query("default", "items")
    assert "SELECT * FROM c OFFSET 0 LIMIT 1;" in cos_c_sql and cos_c_params == []

    # Aliases
    assert get_dialect("postgresql").name == "postgres"
    assert get_dialect("sqlserver").name == "mssql"
    assert get_dialect("unknown_engine").name == "postgres"
