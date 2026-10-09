"""
Engine registry for the opt-in live integration suite.

Each :class:`Engine` knows how to

* locate its service (host/port/user/password/database from ``QB_IT_<ENGINE>_*``
  environment variables, defaulting to ``docker/docker-compose.integration.yml``),
* tell whether it can run here (service reachable, driver importable) and
  produce a precise skip reason when it cannot,
* open a NATIVE connection (the vendor driver, not the connector under test)
  to seed the standard dataset,
* build the kwargs for the real connector class under test,
* declare which conformance features it legitimately lacks (``skip`` table).

Nothing in this module imports a database driver at import time.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import socket
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests.integration import dataset

ALL_FEATURES = (
    "introspect_pk",
    "introspect_fk",
    "window",
    "right_join",
    "statement_timeout",
    "db_read_only",
    "case_sensitive_identifiers",
    "unicode_identifiers",
    "async",
)

HOST_DEFAULT = "127.0.0.1"
_SCRATCH = Path(tempfile.gettempdir()) / "qb_integration"


class EngineUnavailable(Exception):
    """The engine cannot run here; the message is the skip reason."""


@dataclass
class Engine:
    name: str  # also the QB_IT_<NAME> env prefix and pytest id
    connector: str  # registry name of the sync connector under test
    tier: str  # embedded | required | extended | cloud
    family: str  # key in dataset.FAMILIES ("" for non-SQL smoke engines)
    drivers: tuple[str, ...]  # any-of importable module names
    pip: str  # what to install when the driver is missing
    port: int = 0
    user: str = "qb"
    password: str = "qb_it_password"
    database: str = "qb_it"
    #: features this engine legitimately lacks -> reason (skip, never silent pass)
    unsupported: dict[str, str] = field(default_factory=dict)
    async_connector: str | None = None
    connector_factory: Callable[[Engine, dict[str, Any]], dict[str, Any]] | None = None
    native_factory: Callable[[Engine], Any] | None = None
    ro_native: Callable[[Engine, Any], None] | None = None  # create read-only login
    slow_sql: str = ""  # a statement that runs far longer than the timeout
    ddl_family_overrides: dict[str, str] = field(default_factory=dict)

    # ---- configuration -------------------------------------------------
    def env(self, key: str, default: Any) -> str:
        return os.environ.get(f"QB_IT_{self.name.upper()}_{key}", str(default))

    @property
    def host(self) -> str:
        return self.env("HOST", HOST_DEFAULT)

    @property
    def port_(self) -> int:
        return int(self.env("PORT", self.port))

    @property
    def user_(self) -> str:
        return self.env("USER", self.user)

    @property
    def password_(self) -> str:
        return self.env("PASSWORD", self.password)

    @property
    def database_(self) -> str:
        return self.env("DATABASE", self.database)

    @property
    def embedded(self) -> bool:
        return self.tier == "embedded"

    # ---- availability --------------------------------------------------
    def driver_module(self) -> str | None:
        for mod in self.drivers:
            with contextlib.suppress(ImportError):
                importlib.import_module(mod)
                return mod
        return None

    def check_available(self) -> None:
        if self.driver_module() is None:
            raise EngineUnavailable(
                f"driver not installed (need one of {', '.join(self.drivers)}; "
                f"pip install {self.pip})"
            )
        if self.embedded or self.tier == "cloud":
            return
        try:
            with socket.create_connection((self.host, self.port_), timeout=1.5):
                pass
        except OSError as exc:
            raise EngineUnavailable(
                f"{self.name} not reachable at {self.host}:{self.port_} ({exc}); "
                "start it with: docker compose -p qb-integration "
                "-f docker/docker-compose.integration.yml up -d --wait"
                + (" (add --profile extended)" if self.tier == "extended" else "")
            ) from exc

    # ---- connector under test -----------------------------------------
    def connector_kwargs(self, **overrides: Any) -> dict[str, Any]:
        assert self.connector_factory is not None
        return self.connector_factory(self, overrides)

    def make_connector(self, **overrides: Any) -> Any:
        from query_builder.connectors.registry import get_connector

        return get_connector(self.connector, **self.connector_kwargs(**overrides))

    def make_async_connector(self, **overrides: Any) -> Any:
        from query_builder.connectors.registry import get_connector

        assert self.async_connector
        return get_connector(self.async_connector, **self.connector_kwargs(**overrides))

    def connector_class_keys(self) -> list[str]:
        from query_builder.connectors.registry import ConnectorRegistry

        keys = []
        for reg_name in (self.connector, self.async_connector):
            if reg_name:
                cls = ConnectorRegistry._registry[reg_name]
                keys.append(f"{cls.__module__}.{cls.__qualname__}")
        return keys

    # ---- native seeding ------------------------------------------------
    def seed(self) -> None:
        assert self.native_factory is not None
        native = self.native_factory(self)
        try:
            for stmt in dataset.schema_statements(self.family):
                native.run(stmt)
            if self.ro_native is not None:
                self.ro_native(self, native)
        finally:
            native.close()

    def cleanup(self) -> None:
        if self.native_factory is None or not self.family:
            return
        native = self.native_factory(self)
        try:
            for stmt in dataset.drop_statements(self.family):
                with contextlib.suppress(Exception):
                    native.run(stmt)
        finally:
            native.close()


class Native:
    """Tiny uniform wrapper over a vendor DB-API connection or client."""

    def __init__(self, run: Callable[[str], Any], close: Callable[[], None]):
        self.run = run
        self.close = close


# --------------------------------------------------------------------------
# native adapters
# --------------------------------------------------------------------------
def _dbapi_native(conn: Any, commit: bool = True) -> Native:
    def run(sql: str) -> Any:
        cur = conn.cursor()
        try:
            cur.execute(sql)
            if cur.description:
                return cur.fetchall()
            return None
        finally:
            cur.close()
            if commit:
                conn.commit()

    return Native(run, conn.close)


def _pg_native(e: Engine, database: str | None = None) -> Native:
    import psycopg

    conn = psycopg.connect(
        host=e.host,
        port=e.port_,
        user=e.user_,
        password=e.password_,
        dbname=database or e.database_,
        autocommit=True,
    )
    return _dbapi_native(conn, commit=False)


def _mysql_native(e: Engine) -> Native:
    try:
        import MySQLdb as driver

        kw = {"passwd": e.password_, "db": e.database_}
    except ImportError:
        import pymysql as driver

        kw = {"password": e.password_, "database": e.database_}
    conn = driver.connect(host=e.host, port=e.port_, user=e.user_, **kw)
    conn.autocommit(True) if callable(conn.autocommit) else None
    return _dbapi_native(conn, commit=False)


def _mysql_root_run(e: Engine, statements: list[str]) -> None:
    try:
        import MySQLdb as driver

        kw = {"passwd": e.env("ROOT_PASSWORD", "qb_it_root_password")}
    except ImportError:
        import pymysql as driver

        kw = {"password": e.env("ROOT_PASSWORD", "qb_it_root_password")}
    conn = driver.connect(host=e.host, port=e.port_, user="root", **kw)
    try:
        cur = conn.cursor()
        for s in statements:
            cur.execute(s)
        conn.commit()
    finally:
        conn.close()


def _clickhouse_native(e: Engine) -> Native:
    import clickhouse_connect

    client = clickhouse_connect.get_client(
        host=e.host,
        port=e.port_,
        username=e.user_,
        password=e.password_,
        database=e.database_,
    )
    return Native(client.command, client.close)


def _clickhouse_native_http(e: Engine) -> Native:
    """Seed the native-protocol engine through the HTTP port of the same server."""
    import clickhouse_connect

    client = clickhouse_connect.get_client(
        host=e.host,
        port=int(os.environ.get("QB_IT_CLICKHOUSE_NATIVE_HTTP_PORT", 38123)),
        username=e.user_,
        password=e.password_,
        database=e.database_,
    )
    return Native(client.command, client.close)


def _sqlite_native(e: Engine) -> Native:
    import sqlite3

    conn = sqlite3.connect(embedded_path(e))
    return _dbapi_native(conn)


def _duckdb_native(e: Engine) -> Native:
    import duckdb

    conn = duckdb.connect(embedded_path(e))
    return Native(conn.execute, conn.close)


def embedded_path(e: Engine) -> str:
    _SCRATCH.mkdir(parents=True, exist_ok=True)
    ext = {"sqlite": "db", "duckdb": "duckdb"}[e.name]
    return str(_SCRATCH / f"qb_it.{ext}")


def _mssql_native(e: Engine, database: str | None = None) -> Native:
    import pymssql

    conn = pymssql.connect(
        server=e.host,
        port=str(e.port_),
        user=e.user_,
        password=e.password_,
        database=database or e.database_,
        autocommit=True,
    )
    return _dbapi_native(conn, commit=False)


def _trino_native(e: Engine) -> Native:
    import trino

    conn = trino.dbapi.connect(
        host=e.host, port=e.port_, user=e.user_, catalog="memory", schema="default"
    )

    def run(sql: str) -> Any:
        cur = conn.cursor()
        cur.execute(sql)
        return cur.fetchall()

    return Native(run, conn.close)


# --------------------------------------------------------------------------
# read-only logins (to prove DB-level enforcement behind the validator)
# --------------------------------------------------------------------------
RO_USER = "qb_ro"
RO_PASSWORD = "qb_ro_password"


def _pg_ro(e: Engine, native: Native) -> None:
    native.run(f"DROP ROLE IF EXISTS {RO_USER}")
    native.run(f"CREATE ROLE {RO_USER} LOGIN PASSWORD '{RO_PASSWORD}'")
    native.run(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {RO_USER}")


def _mysql_ro(e: Engine, native: Native) -> None:
    db = e.database_
    _mysql_root_run(
        e,
        [
            f"DROP USER IF EXISTS '{RO_USER}'@'%'",
            f"CREATE USER '{RO_USER}'@'%' IDENTIFIED BY '{RO_PASSWORD}'",
            f"GRANT SELECT ON `{db}`.* TO '{RO_USER}'@'%'",
        ],
    )


def _clickhouse_ro(e: Engine, native: Native) -> None:
    native.run(f"DROP USER IF EXISTS {RO_USER}")
    native.run(f"CREATE USER {RO_USER} IDENTIFIED BY '{RO_PASSWORD}'")
    native.run(f"GRANT SELECT ON {e.database_}.* TO {RO_USER}")


# --------------------------------------------------------------------------
# connector kwargs
# --------------------------------------------------------------------------
def _ro(overrides: dict[str, Any], e: Engine) -> tuple[str, str]:
    if overrides.get("readonly"):
        return RO_USER, RO_PASSWORD
    return e.user_, overrides.get("password") or e.password_


def _kw_postgres(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    user, pw = _ro(o, e)
    return {
        "host": e.host,
        "port": e.port_,
        "user": user,
        "password": pw,
        "dbname": e.database_,
        "connect_timeout": 5,
    }


def _kw_cockroach(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    kw = {
        "host": e.host,
        "port": e.port_,
        "user": e.user_,
        "dbname": e.database_,
        "sslmode": "disable",
        "connect_timeout": 5,
    }
    if o.get("password"):
        kw["password"] = o["password"]
    return kw


def _kw_mysql(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    user, pw = _ro(o, e)
    return {
        "database": e.database_,
        "host": e.host,
        "port": e.port_,
        "user": user,
        "password": pw,
        "connect_timeout": 5,
    }


def _kw_clickhouse(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    user, pw = _ro(o, e)
    return {
        "database": e.database_,
        "host": e.host,
        "port": e.port_,
        "username": user,
        "password": pw,
    }


def _kw_sqlite(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    if o.get("readonly"):
        return {
            "database": f"file:{embedded_path(e)}?mode=ro",
            "uri": True,
            "check_same_thread": False,
        }
    return {"database": embedded_path(e), "check_same_thread": False}


def _kw_duckdb(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    kw: dict[str, Any] = {"database": embedded_path(e)}
    if o.get("readonly"):
        kw["read_only"] = True
    return kw


def _kw_mssql(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {
        "server": e.host,
        "port": str(e.port_),
        "user": e.user_,
        "password": o.get("password") or e.password_,
        "database": e.database_,
        "login_timeout": 5,
    }


def _kw_trino(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {
        "catalog": "memory",
        "schema_name": "default",
        "host": e.host,
        "port": e.port_,
        "user": e.user_,
    }


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------
#: SLEEP() is not interrupted by MySQL's max_execution_time (it just returns 1), so
#: use a genuinely expensive read-only SELECT.
_MYSQL_SLOW = (
    "SELECT COUNT(*) FROM information_schema.columns a, "
    "information_schema.columns b, information_schema.columns c"
)

ENGINES: dict[str, Engine] = {}


def _register(e: Engine) -> Engine:
    ENGINES[e.name] = e
    return e


def _pg_database_bootstrap(e: Engine) -> Native:
    return _pg_native(e)


_register(
    Engine(
        name="sqlite",
        connector="sqlite",
        tier="embedded",
        family="sqlite",
        drivers=("sqlite3",),
        pip="(stdlib)",
        connector_factory=_kw_sqlite,
        native_factory=_sqlite_native,
        unsupported={
            "statement_timeout": "SQLite has no server-side statement timeout",
            "case_sensitive_identifiers": "SQLite identifiers are case-insensitive",
        },
        slow_sql="",
    )
)
_register(
    Engine(
        name="duckdb",
        connector="duckdb",
        tier="embedded",
        family="duckdb",
        drivers=("duckdb",),
        pip="duckdb",
        connector_factory=_kw_duckdb,
        native_factory=_duckdb_native,
        unsupported={
            "statement_timeout": "DuckDB has no statement timeout setting",
            "case_sensitive_identifiers": "DuckDB identifiers are case-insensitive",
        },
    )
)
_register(
    Engine(
        name="postgres",
        connector="postgres",
        tier="required",
        family="pg",
        drivers=("psycopg", "psycopg2"),
        pip="'psycopg[binary]'",
        port=35432,
        connector_factory=_kw_postgres,
        native_factory=_pg_native,
        ro_native=_pg_ro,
        slow_sql="SELECT pg_sleep(30)",
    )
)
_register(
    Engine(
        name="mysql",
        connector="mysql",
        tier="required",
        family="mysql",
        drivers=("MySQLdb", "pymysql"),
        pip="mysqlclient  # or pymysql",
        port=35306,
        connector_factory=_kw_mysql,
        native_factory=_mysql_native,
        ro_native=_mysql_ro,
        slow_sql=_MYSQL_SLOW,
        unsupported={
            "case_sensitive_identifiers": "MySQL table names follow the filesystem",
        },
    )
)
_register(
    Engine(
        name="mariadb",
        connector="mysql",
        tier="required",
        family="mysql",
        drivers=("MySQLdb", "pymysql"),
        pip="mysqlclient  # or pymysql",
        port=35307,
        connector_factory=_kw_mysql,
        native_factory=_mysql_native,
        ro_native=_mysql_ro,
        slow_sql=_MYSQL_SLOW,
        unsupported={
            "case_sensitive_identifiers": "MariaDB table names follow the filesystem",
        },
    )
)
_register(
    Engine(
        name="clickhouse",
        connector="clickhouse",
        tier="required",
        family="clickhouse",
        drivers=("clickhouse_connect",),
        pip="clickhouse-connect",
        port=38123,
        connector_factory=_kw_clickhouse,
        native_factory=_clickhouse_native,
        ro_native=_clickhouse_ro,
        slow_sql="SELECT sleepEachRow(3) FROM numbers(10)",
        unsupported={
            "introspect_fk": "ClickHouse has no foreign keys",
        },
    )
)


def _kw_clickhouse_native(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    user, pw = _ro(o, e)
    return {
        "database": e.database_,
        "host": e.host,
        "port": e.port_,
        "user": user,
        "password": pw,
    }


_register(
    Engine(
        name="clickhouse_native",
        connector="clickhouse_native",
        async_connector="async_clickhouse_native",
        tier="extended",
        family="clickhouse",
        drivers=("clickhouse_driver",),
        pip="clickhouse-driver",
        port=39000,
        connector_factory=_kw_clickhouse_native,
        native_factory=_clickhouse_native_http,
        ro_native=_clickhouse_ro,
        slow_sql="SELECT sleepEachRow(3) FROM numbers(10)",
        unsupported={"introspect_fk": "ClickHouse has no foreign keys"},
    )
)

_register(
    Engine(
        name="cockroach",
        connector="cockroachdb",
        tier="extended",
        family="pg",
        drivers=("psycopg", "psycopg2"),
        pip="'psycopg[binary]'",
        port=35257,
        user="root",
        password="",
        database="qb_it",
        connector_factory=_kw_cockroach,
        native_factory=lambda e: _cockroach_native(e),
        slow_sql="SELECT pg_sleep(30)",
    )
)
_register(
    Engine(
        name="timescale",
        connector="timescaledb",
        tier="extended",
        family="pg",
        drivers=("psycopg", "psycopg2"),
        pip="'psycopg[binary]'",
        port=35433,
        connector_factory=_kw_postgres,
        native_factory=_pg_native,
        ro_native=_pg_ro,
        slow_sql="SELECT pg_sleep(30)",
    )
)
_register(
    Engine(
        name="mssql",
        connector="mssql",
        tier="extended",
        family="mssql",
        drivers=("pymssql", "pyodbc"),
        pip="pymssql",
        port=35143,
        user="sa",
        password="Qb_it_Passw0rd!",
        connector_factory=_kw_mssql,
        native_factory=lambda e: _mssql_bootstrap(e),
        slow_sql="WAITFOR DELAY '00:00:30'",
    )
)
_register(
    Engine(
        name="trino",
        connector="trino",
        tier="extended",
        family="trino",
        drivers=("trino",),
        pip="trino",
        port=38080,
        user="qb",
        password="",
        connector_factory=_kw_trino,
        native_factory=_trino_native,
        unsupported={
            "introspect_pk": "Trino memory catalog has no primary keys",
            "introspect_fk": "Trino memory catalog has no foreign keys",
            "case_sensitive_identifiers": "Trino folds identifiers to lower case",
            "statement_timeout": "Trino timeouts are session properties, not applied",
            "db_read_only": "no read-only login in the memory catalog",
        },
    )
)


_register(
    Engine(
        name="questdb",
        connector="questdb",
        tier="extended",
        family="questdb",
        drivers=("psycopg", "psycopg2"),
        pip="'psycopg[binary]'",
        port=38812,
        user="admin",
        password="quest",
        database="qdb",
        connector_factory=_kw_postgres,
        native_factory=_pg_native,
        slow_sql="SELECT count() FROM long_sequence(100000000) a CROSS JOIN long_sequence(100000) b",
        unsupported={
            "having": "QuestDB has no HAVING clause",
            "in_subquery": "QuestDB cannot compare a column with a subquery result in IN",
            "sql_null_semantics": "QuestDB compares NULL as a regular value (NULL != 1 is true)",
            "introspect_not_null": "QuestDB has no NOT NULL constraints",
            "statement_timeout": "QuestDB has no per-session statement timeout",
            "introspect_pk": "QuestDB has no primary keys",
            "introspect_fk": "QuestDB has no foreign keys",
            "right_join": "QuestDB has no RIGHT JOIN",
            "case_sensitive_identifiers": "QuestDB table names are case-insensitive",
            "db_read_only": "QuestDB (OSS) has no read-only users",
        },
    )
)


def _kw_mongodb(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {"database": e.database_, "host": e.host, "port": e.port_}


def _kw_redis(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {"host": e.host, "port": e.port_}


def _kw_elasticsearch(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {"endpoint": f"http://{e.host}:{e.port_}"}


def _kw_opensearch(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {
        "hosts": [{"host": e.host, "port": e.port_}],
        "index_pattern": "qbit_*",
    }


def _kw_neo4j(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {
        "uri": f"bolt://{e.host}:{e.port_}",
        "auth": (e.user_, o.get("password") or e.password_),
    }


def _kw_cassandra(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {
        "contact_points": [e.host],
        "port": e.port_,
        "keyspace": e.database_,
    }


for _e in (
    Engine(
        name="mongodb",
        connector="mongodb",
        tier="extended",
        family="",
        drivers=("pymongosql", "pymongo"),
        pip="pymongosql",
        port=35017,
        password="",
        connector_factory=_kw_mongodb,
    ),
    Engine(
        name="redis",
        connector="redis",
        async_connector="async_redis",
        tier="extended",
        family="",
        drivers=("redis",),
        pip="redis",
        port=36379,
        password="",
        connector_factory=_kw_redis,
    ),
    Engine(
        name="elasticsearch",
        connector="elasticsearch",
        tier="extended",
        family="",
        drivers=("elasticsearch",),
        pip="'elasticsearch>=8,<9'",
        port=39200,
        password="",
        connector_factory=_kw_elasticsearch,
    ),
    Engine(
        name="opensearch",
        connector="opensearch",
        async_connector="async_opensearch",
        tier="extended",
        family="",
        drivers=("opensearchpy",),
        pip="opensearch-py",
        port=39201,
        password="",
        connector_factory=_kw_opensearch,
    ),
    Engine(
        name="neo4j",
        connector="neo4j",
        async_connector="async_neo4j",
        tier="extended",
        family="",
        drivers=("neo4j",),
        pip="neo4j",
        port=38687,
        user="neo4j",
        connector_factory=_kw_neo4j,
    ),
    Engine(
        name="cassandra",
        connector="apache_cassandra",
        async_connector="async_apache_cassandra",
        tier="extended",
        family="",
        drivers=("cassandra",),
        pip="cassandra-driver",
        port=39042,
        password="",
        connector_factory=_kw_cassandra,
    ),
):
    _register(_e)


def _cockroach_native(e: Engine) -> Native:
    """Cockroach insecure mode: create the database first, then connect to it."""
    import psycopg

    boot = psycopg.connect(
        host=e.host,
        port=e.port_,
        user=e.user_,
        dbname="defaultdb",
        sslmode="disable",
        autocommit=True,
    )
    with boot.cursor() as cur:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS {e.database_}")
    boot.close()
    conn = psycopg.connect(
        host=e.host,
        port=e.port_,
        user=e.user_,
        dbname=e.database_,
        sslmode="disable",
        autocommit=True,
    )
    return _dbapi_native(conn, commit=False)


def _mssql_bootstrap(e: Engine) -> Native:
    boot = _mssql_native(e, database="master")
    boot.run(f"IF DB_ID('{e.database_}') IS NULL CREATE DATABASE {e.database_}")
    boot.close()
    return _mssql_native(e)


def selected_engine_names() -> list[str]:
    """Engines to parametrize over, honouring QB_IT_ENGINES (comma separated)."""
    raw = os.environ.get("QB_IT_ENGINES", "").strip()
    if not raw:
        return list(ENGINES)
    wanted = [w.strip().lower() for w in raw.split(",") if w.strip()]
    unknown = [w for w in wanted if w not in ENGINES]
    if unknown:
        raise ValueError(
            f"QB_IT_ENGINES names unknown engine(s) {unknown}; known: {sorted(ENGINES)}"
        )
    return [n for n in ENGINES if n in wanted]
