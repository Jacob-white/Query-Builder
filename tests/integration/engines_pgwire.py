"""
Postgres-/MySQL-wire engine family for the live suite: YugabyteDB, CrateDB, RisingWave,
Materialize, GreptimeDB, StarRocks, Doris, TiDB, Supabase, AlloyDB Omni, OceanBase.

Containers: ``docker/compose.pgwire.yml`` (profile ``pgwire``).  Run one engine per batch::

    python scripts/it_batch.py --label cratedb --engines cratedb \
        --compose docker/compose.pgwire.yml --profile pgwire --services cratedb

Neon (serverless Postgres, no local image) and Redshift (cloud only) are intentionally
NOT registered here: a plain PostgreSQL container is not evidence for their connector
classes.  Redshift is covered by the cloud stub (``tests/integration/cloud.py``); see
``docs/TESTING_LIVE.md``.
"""

from __future__ import annotations

from typing import Any

from tests.integration import dataset, smoke
from tests.integration.engines import (
    RO_PASSWORD,
    RO_USER,
    Engine,
    Native,
    _dbapi_native,
    _kw_postgres,
    _pg_native,
    _pg_ro,
    _ro,
    register,
)

_PG_SLEEP = "SELECT pg_sleep(30)"
#: two big generated relations: far longer than any test timeout, no side effects
_GEN_SLOW = (
    "SELECT count(*) FROM generate_series(1, 100000000) a "
    "CROSS JOIN generate_series(1, 100000) b"
)


def _pg_wire_native(e: Engine, flush: str | None = None) -> Native:
    """psycopg autocommit connection; optionally run ``flush`` after every INSERT."""
    native = _pg_native(e)
    if flush is None:
        return native
    inner = native.run

    def run(sql: str) -> Any:
        out = inner(sql)
        if sql.lstrip().upper().startswith("INSERT"):
            inner(flush)
        return out

    return Native(run, native.close)


# --------------------------------------------------------------------------
# YugabyteDB (YSQL, PostgreSQL fork)
# --------------------------------------------------------------------------
register(
    Engine(
        name="yugabyte",
        connector="yugabyte",
        async_connector="async_yugabyte",
        tier="extended",
        family="pg",
        drivers=("psycopg2", "psycopg"),
        pip="psycopg2-binary",
        port=40100,
        user="yugabyte",
        password="yugabyte",
        database="yugabyte",
        connector_factory=_kw_postgres,
        native_factory=_pg_native,
        ro_native=_pg_ro,
        slow_sql=_PG_SLEEP,
        service="yugabyte",
        container_port=5433,
    )
)

# --------------------------------------------------------------------------
# Supabase (supabase/postgres image) and AlloyDB Omni: genuine PostgreSQL builds of
# the vendors' own images.  The connector classes are thin Postgres subclasses.
# --------------------------------------------------------------------------
register(
    Engine(
        name="supabase",
        connector="supabase",
        tier="extended",
        family="pg",
        drivers=("psycopg", "psycopg2"),
        pip="'psycopg[binary]'",
        port=40900,
        user="postgres",
        connector_factory=_kw_postgres,
        native_factory=_pg_native,
        ro_native=_pg_ro,
        slow_sql=_PG_SLEEP,
        service="supabase",
        container_port=5432,
    )
)
register(
    Engine(
        name="alloydb",
        connector="alloydb",
        tier="extended",
        family="pg",
        drivers=("psycopg", "psycopg2"),
        pip="'psycopg[binary]'",
        port=40950,
        user="postgres",
        connector_factory=_kw_postgres,
        native_factory=_pg_native,
        ro_native=_pg_ro,
        slow_sql=_PG_SLEEP,
        service="alloydb",
        container_port=5432,
    )
)

# --------------------------------------------------------------------------
# CrateDB (HTTP endpoint through the `crate` client; no foreign keys)
# --------------------------------------------------------------------------
dataset.FAMILIES["cratedb"] = dataset.Ddl(
    int_t="INTEGER",
    nint_t="INTEGER",
    str_t="TEXT",
    nstr_t="TEXT",
    fk=False,
    table_suffix=" CLUSTERED INTO 1 SHARDS WITH (number_of_replicas = 0)",
)


def _crate_native(e: Engine) -> Native:
    from crate import client

    conn = client.connect(f"http://{e.host}:{e.port_}")
    cur = conn.cursor()
    touched: set[str] = set()

    def run(sql: str) -> Any:
        cur.execute(sql)
        head = sql.lstrip().upper()
        if head.startswith("INSERT"):
            touched.add(sql.split("(", 1)[0].split()[-1])
            for table in touched:  # CrateDB is eventually consistent until REFRESH
                cur.execute(f"REFRESH TABLE {table}")
        return cur.fetchall() if cur.description else None

    return Native(run, conn.close)


def _crate_ro(e: Engine, native: Native) -> None:
    for stmt in (
        f"DROP USER IF EXISTS {RO_USER}",
        f"CREATE USER {RO_USER} WITH (password = '{RO_PASSWORD}')",
        f"GRANT DQL ON SCHEMA doc TO {RO_USER}",
    ):
        native.run(stmt)


def _kw_crate(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    kw: dict[str, Any] = {
        "servers": [f"http://{e.host}:{e.port_}"],
        "schema_name": "doc",
    }
    if o.get("readonly"):
        kw["username"] = RO_USER
        kw["password"] = RO_PASSWORD
    return kw


register(
    Engine(
        name="cratedb",
        connector="cratedb",
        async_connector="async_cratedb",
        tier="extended",
        family="cratedb",
        drivers=("crate",),
        pip="crate",
        port=40200,
        user="crate",
        password="",
        database="doc",
        connector_factory=_kw_crate,
        native_factory=_crate_native,
        ro_native=_crate_ro,
        slow_sql=_GEN_SLOW,
        unsupported={"introspect_fk": "CrateDB has no foreign keys"},
        service="cratedb",
        container_port=4200,
    )
)

# --------------------------------------------------------------------------
# RisingWave (PostgreSQL wire, streaming): no foreign keys
# --------------------------------------------------------------------------
dataset.FAMILIES["risingwave"] = dataset.Ddl(
    int_t="INT", nint_t="INT", str_t="VARCHAR", nstr_t="VARCHAR", fk=False
)


def _kw_risingwave(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {
        "host": e.host,
        "port": e.port_,
        "user": e.user_,
        "database": e.database_,
        "connect_timeout": 5,
    }


register(
    Engine(
        name="risingwave",
        connector="risingwave",
        async_connector="async_risingwave",
        tier="extended",
        family="risingwave",
        drivers=("psycopg", "psycopg2"),
        pip="'psycopg[binary]'",
        port=40300,
        user="root",
        password="",
        database="dev",
        connector_factory=_kw_risingwave,
        native_factory=lambda e: _pg_wire_native(e, flush="FLUSH"),
        slow_sql=_GEN_SLOW,
        unsupported={
            "introspect_fk": "RisingWave has no foreign keys",
            "db_read_only": "no read-only role is provisioned for this engine in the harness",
        },
        service="risingwave",
        container_port=4566,
    )
)

# --------------------------------------------------------------------------
# Materialize (PostgreSQL wire, streaming): tables have no PK/FK constraints
# --------------------------------------------------------------------------
dataset.FAMILIES["materialize"] = dataset.Ddl(
    int_t="INTEGER", str_t="TEXT", nstr_t="TEXT", pk=False, fk=False
)


def _kw_materialize(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {
        "host": e.host,
        "port": e.port_,
        "user": e.user_,
        "dbname": e.database_,
        "connect_timeout": 5,
    }


register(
    Engine(
        name="materialize",
        connector="materialize",
        async_connector="async_materialize",
        tier="extended",
        family="materialize",
        drivers=("psycopg", "psycopg2"),
        pip="'psycopg[binary]'",
        port=40400,
        user="materialize",
        password="",
        database="materialize",
        connector_factory=_kw_materialize,
        native_factory=_pg_native,
        slow_sql=_GEN_SLOW,
        unsupported={
            "introspect_pk": "Materialize tables have no primary keys",
            "introspect_fk": "Materialize has no foreign keys",
            "db_read_only": "no read-only role is provisioned for this engine in the harness",
        },
        service="materialize",
        container_port=6875,
    )
)

# --------------------------------------------------------------------------
# GreptimeDB (PostgreSQL wire): every table needs a TIME INDEX column, which the
# standard dataset has no room for, so the smoke battery runs instead.
# --------------------------------------------------------------------------
_GREPT_PASSWORD = "qb_it_password"


def _seed_greptime(e: Engine) -> None:
    native = _pg_native(e)
    try:
        native.run("DROP TABLE IF EXISTS qbit_people")
        native.run(
            "CREATE TABLE qbit_people (id INT, name STRING, age INT, "
            "ts TIMESTAMP TIME INDEX, PRIMARY KEY (id))"
        )
        for pid, name, age in smoke.PEOPLE:
            native.run(
                "INSERT INTO qbit_people (id, name, age, ts) VALUES "
                f"({pid}, '{name}', {age}, {pid})"
            )
    finally:
        native.close()


def _greptime_count(e: Engine) -> list[dict[str, Any]]:
    native = _pg_native(e)
    try:
        rows = native.run("SELECT count(*) FROM qbit_people")
        return [{"count": rows[0][0]}]
    finally:
        native.close()


def _kw_greptime(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {
        "host": e.host,
        "port": e.port_,
        "user": e.user_,
        "password": o.get("password") or e.password_,
        "dbname": e.database_,
        "connect_timeout": 5,
    }


register(
    Engine(
        name="greptimedb",
        connector="greptimedb",
        async_connector="async_greptimedb",
        tier="extended",
        family="",
        drivers=("psycopg2", "psycopg"),
        pip="psycopg2-binary",
        port=40500,
        user="qb",
        password=_GREPT_PASSWORD,
        database="public",
        connector_factory=_kw_greptime,
        native_factory=_pg_native,
        service="greptimedb",
        container_port=4003,
    )
)
smoke.SMOKE["greptimedb"] = smoke.Smoke(
    seed=_seed_greptime,
    table="qbit_people",
    columns={"id", "name", "age"},
    read="SELECT name, age FROM qbit_people ORDER BY age",
    expected=smoke.BY_AGE,
    writes=smoke.SQL_WRITES,
    spec=smoke.SPEC_PEOPLE,
    check=_greptime_count,
)


# --------------------------------------------------------------------------
# MySQL-wire engines: TiDB, StarRocks, Doris, OceanBase
# --------------------------------------------------------------------------
def _mysql_admin_run(
    e: Engine, user: str, statements: tuple[str, ...] | list[str]
) -> None:
    import pymysql

    admin = pymysql.connect(
        host=e.host, port=e.port_, user=user, password="", autocommit=True
    )
    try:
        with admin.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
    finally:
        admin.close()


def _mysql_wire_native(
    e: Engine, *, admin_user: str = "root", bootstrap: tuple[str, ...] = ()
) -> Native:
    """Run ``bootstrap`` as the admin login (idempotent), then connect as the test user."""
    import pymysql

    _mysql_admin_run(e, admin_user, bootstrap)
    login = e.user_ if e.name != "oceanbase" else f"{e.user_}@{_OB_TENANT}"
    conn = pymysql.connect(
        host=e.host,
        port=e.port_,
        user=login,
        password=e.password_,
        database=e.database_,
        autocommit=True,
    )
    return _dbapi_native(conn, commit=False)


def _bootstrap_stmts(e: Engine, grant: str) -> tuple[str, ...]:
    return (
        f"CREATE DATABASE IF NOT EXISTS {e.database_}",
        f"CREATE USER IF NOT EXISTS '{e.user_}'@'%' IDENTIFIED BY '{e.password_}'",
        grant.format(db=e.database_, user=e.user_),
    )


def _ro_stmts(e: Engine, grant: str) -> list[str]:
    return [
        f"DROP USER IF EXISTS '{RO_USER}'@'%'",
        f"CREATE USER '{RO_USER}'@'%' IDENTIFIED BY '{RO_PASSWORD}'",
        grant.format(db=e.database_, ro=RO_USER),
    ]


def _kw_mysqlwire(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    user, pw = _ro(o, e)
    return {
        "database": e.database_,
        "host": e.host,
        "port": e.port_,
        "user": user,
        "password": pw,
        "connect_timeout": 5,
    }


_MYSQL_SLOW = (
    "SELECT COUNT(*) FROM information_schema.columns a, "
    "information_schema.columns b, information_schema.columns c, "
    "information_schema.columns d"
)

# ---- TiDB (tidb-server with the in-memory unistore engine)
register(
    Engine(
        name="tidb",
        connector="tidb",
        tier="extended",
        family="mysql",
        drivers=("pymysql", "MySQLdb"),
        pip="pymysql",
        port=40800,
        connector_factory=_kw_mysqlwire,
        native_factory=lambda e: _mysql_wire_native(
            e, bootstrap=_bootstrap_stmts(e, "GRANT ALL ON {db}.* TO '{user}'@'%'")
        ),
        ro_native=lambda e, n: _mysql_admin_run(
            e, "root", _ro_stmts(e, "GRANT SELECT ON {db}.* TO '{ro}'@'%'")
        ),
        slow_sql=_MYSQL_SLOW,
        unsupported={
            "case_sensitive_identifiers": "TiDB table names follow lower_case_table_names",
        },
        service="tidb",
        container_port=4000,
    )
)

# ---- StarRocks (allin1) and Doris (all-in-one): key-model tables, no foreign keys
_OLAP_SUFFIX = (
    " {model} KEY (id) DISTRIBUTED BY HASH(id) BUCKETS 1 "
    "PROPERTIES ('replication_num' = '1')"
)
dataset.FAMILIES["starrocks"] = dataset.Ddl(
    quote="`", pk=False, fk=False, table_suffix=_OLAP_SUFFIX.format(model="PRIMARY")
)
dataset.FAMILIES["doris"] = dataset.Ddl(
    quote="`", pk=False, fk=False, table_suffix=_OLAP_SUFFIX.format(model="UNIQUE")
)

register(
    Engine(
        name="starrocks",
        connector="starrocks",
        async_connector="async_starrocks",
        tier="extended",
        family="starrocks",
        drivers=("pymysql", "MySQLdb"),
        pip="pymysql",
        port=40600,
        connector_factory=_kw_mysqlwire,
        native_factory=lambda e: _mysql_wire_native(
            e,
            bootstrap=_bootstrap_stmts(e, "GRANT user_admin TO USER '{user}'@'%'")
            + (
                f"GRANT ALL ON ALL TABLES IN DATABASE {e.database_} TO USER '{e.user_}'@'%'",
                f"GRANT CREATE TABLE, DROP, ALTER ON DATABASE {e.database_} TO USER '{e.user_}'@'%'",
            ),
        ),
        ro_native=lambda e, n: _mysql_admin_run(
            e,
            "root",
            _ro_stmts(
                e, "GRANT SELECT ON ALL TABLES IN DATABASE {db} TO USER '{ro}'@'%'"
            ),
        ),
        slow_sql=(
            "SELECT count(*) FROM TABLE(generate_series(1, 100000000)) a "
            "CROSS JOIN TABLE(generate_series(1, 100000)) b"
        ),
        unsupported={"introspect_fk": "StarRocks has no foreign keys"},
        service="starrocks",
        container_port=9030,
    )
)
register(
    Engine(
        name="doris",
        connector="doris",
        async_connector="async_doris",
        tier="extended",
        family="doris",
        drivers=("pymysql",),
        pip="pymysql",
        port=40700,
        connector_factory=_kw_mysqlwire,
        native_factory=lambda e: _mysql_wire_native(
            e, bootstrap=_bootstrap_stmts(e, "GRANT ALL ON *.*.* TO '{user}'@'%'")
        ),
        ro_native=lambda e, n: _mysql_admin_run(
            e,
            "root",
            _ro_stmts(e, "GRANT SELECT_PRIV ON internal.{db}.* TO '{ro}'@'%'"),
        ),
        slow_sql=(
            "SELECT count(*) FROM numbers('number' = '100000000') a "
            "CROSS JOIN numbers('number' = '100000') b"
        ),
        unsupported={"introspect_fk": "Doris has no foreign keys"},
        service="doris",
        container_port=9030,
    )
)

# ---- OceanBase (MySQL-mode tenant `test` of oceanbase-ce, mini mode)
_OB_TENANT = "test"


def _kw_oceanbase(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    kw = _kw_mysqlwire(e, o)
    kw["tenant"] = _OB_TENANT
    return kw


register(
    Engine(
        name="oceanbase",
        connector="oceanbase",
        tier="extended",
        family="mysql",
        drivers=("pymysql",),
        pip="pymysql",
        port=40960,
        connector_factory=_kw_oceanbase,
        native_factory=lambda e: _mysql_wire_native(
            e,
            admin_user=f"root@{_OB_TENANT}",
            bootstrap=_bootstrap_stmts(e, "GRANT ALL ON {db}.* TO '{user}'@'%'"),
        ),
        ro_native=lambda e, n: _mysql_admin_run(
            e,
            f"root@{_OB_TENANT}",
            _ro_stmts(e, "GRANT SELECT ON {db}.* TO '{ro}'@'%'"),
        ),
        slow_sql=_MYSQL_SLOW,
        unsupported={
            "case_sensitive_identifiers": "OceanBase (MySQL mode) table names follow lower_case_table_names",
        },
        service="oceanbase",
        container_port=2881,
    )
)
