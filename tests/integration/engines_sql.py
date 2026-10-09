"""
Live engines: "other relational / analytical SQL" family.

Oracle, Vertica, MonetDB, Firebird, IBM Db2, IBM Informix, Exasol.  Containers live in
``docker/compose.sql.yml`` (compose profile ``sql``).  Teradata, SAP HANA, SAP ASE (Sybase)
and Kdb+ have no locally runnable image (licence / no container) and are not registered.

These engines fold unquoted identifiers (Oracle, Db2, Firebird, Exasol -> UPPER; Informix ->
lower) while the compiler always emits QUOTED identifiers, so the dataset must be created with
every identifier quoted: this module therefore builds its own DDL (``_statements``) instead of
using ``dataset.schema_statements``, which leaves the column names bare.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any

from tests.integration import dataset as ds
from tests.integration.engines import (
    RO_PASSWORD,
    RO_USER,
    Engine,
    Native,
    _dbapi_native,
    register,
)

# --------------------------------------------------------------------------- DDL families
_UTF = " CHARACTER SET UTF8"

ds.FAMILIES["monetdb"] = ds.Ddl(
    int_t="INTEGER", str_t="VARCHAR(100)", nstr_t="VARCHAR(100)"
)
ds.FAMILIES["firebird"] = ds.Ddl(
    str_t=f"VARCHAR(100){_UTF}",
    nstr_t=f"VARCHAR(100){_UTF}",
    drop="DROP TABLE {t}",
)


def _statements(family: str) -> list[str]:
    """DROP/CREATE/INSERT for the standard dataset with EVERY identifier quoted."""
    d = ds.FAMILIES[family]
    q = lambda n: ds._q(n, d)  # noqa: E731
    pk = (lambda c: f",\n  PRIMARY KEY ({q(c)})") if d.pk else (lambda c: "")
    out = [d.drop.format(t=q(t)) for t in (ds.T_EMP, ds.T_RES, ds.T_MIXED, ds.T_DEPT)]
    out.append(
        f"CREATE TABLE {q(ds.T_DEPT)} (\n  {q('id')} {d.int_t}{d.not_null},\n"
        f"  {q('name')} {d.str_t}{d.not_null}{pk('id')}\n){d.table_suffix}"
    )
    fk = (
        f",\n  FOREIGN KEY ({q('dept_id')}) REFERENCES {q(ds.T_DEPT)} ({q('id')})"
        if d.fk and d.pk
        else ""
    )
    out.append(
        f"CREATE TABLE {q(ds.T_EMP)} (\n  {q('id')} {d.int_t}{d.not_null},\n"
        f"  {q('name')} {d.str_t}{d.not_null},\n  {q('dept_id')} {d.nint_t},\n"
        f"  {q('salary')} {d.int_t}{d.not_null},\n  {q('age')} {d.int_t}{d.not_null},\n"
        f"  {q('email')} {d.nstr_t}{pk('id')}{fk}\n){d.table_suffix}"
    )
    out.append(
        f"CREATE TABLE {q(ds.T_RES)} (\n  {q('id')} {d.int_t}{d.not_null},\n"
        f"  {q('select')} {d.int_t}{d.not_null},\n"
        f"  {q('group')} {d.str_t}{d.not_null},\n"
        f"  {q('order')} {d.int_t}{d.not_null},\n"
        f"  {q('MixedCase')} {d.str_t}{d.not_null},\n"
        f"  {q(ds.UNICODE_COL)} {d.str_t}{d.not_null}{pk('id')}\n){d.table_suffix}"
    )
    out.append(
        f"CREATE TABLE {q(ds.T_MIXED)} (\n  {q('id')} {d.int_t}{d.not_null},\n"
        f"  {q('val')} {d.str_t}{d.not_null}{pk('id')}\n){d.table_suffix}"
    )
    for row in ds.DEPARTMENTS:
        out.append(
            f"INSERT INTO {q(ds.T_DEPT)} ({q('id')}, {q('name')}) VALUES "
            f"({ds._lit(row[0], d)}, {ds._lit(row[1], d)})"
        )
    emp_cols = ", ".join(
        q(c) for c in ("id", "name", "dept_id", "salary", "age", "email")
    )
    for row in ds.EMPLOYEES:
        vals = ", ".join(ds._lit(v, d) for v in row)
        out.append(f"INSERT INTO {q(ds.T_EMP)} ({emp_cols}) VALUES ({vals})")
    cols = ", ".join(
        q(c) for c in ("id", "select", "group", "order", "MixedCase", ds.UNICODE_COL)
    )
    for row in ds.RESERVED:
        vals = ", ".join(ds._lit(v, d) for v in row)
        out.append(f"INSERT INTO {q(ds.T_RES)} ({cols}) VALUES ({vals})")
    out.append(
        f"INSERT INTO {q(ds.T_MIXED)} ({q('id')}, {q('val')}) VALUES (1, {ds._lit('mixed', d)})"
    )
    return out


#: Tables that get an upper-case alias view on identifier-folding engines (see SqlEngine).
ALIASED = {
    ds.T_DEPT: ("id", "name"),
    ds.T_EMP: ("id", "name", "dept_id", "salary", "age", "email"),
}


@dataclass
class SqlEngine(Engine):
    """Engine seeded with quoted-identifier DDL; DROPs are best-effort (no IF EXISTS everywhere).

    ``fold_alias``: engines that fold UNQUOTED identifiers to upper case (Oracle, Db2, Firebird,
    Exasol) cannot resolve the harness's hand-written raw SQL (``SELECT id FROM qbit_employees``)
    against tables that the compiler needs created QUOTED in lower case.  Each aliased table
    therefore gets a same-named upper-case view, which is what an unquoted raw statement resolves
    to; writes through it would still hit the table, so the write-rejection tests stay honest.
    """

    fold_alias: bool = False

    def _alias_views(self) -> list[str]:
        return [t.upper() for t in ALIASED]

    def seed(self) -> None:
        assert self.native_factory is not None
        native = self.native_factory(self)
        try:
            if self.fold_alias:
                for v in self._alias_views():
                    with contextlib.suppress(Exception):
                        native.run(f"DROP VIEW {v}")
            for stmt in _statements(self.family):
                if stmt.startswith("DROP"):
                    with contextlib.suppress(Exception):
                        native.run(stmt)
                else:
                    native.run(stmt)
            if self.fold_alias:
                for t, cols in ALIASED.items():
                    sel = ", ".join(f'"{c}" AS {c.upper()}' for c in cols)
                    native.run(f'CREATE VIEW {t.upper()} AS SELECT {sel} FROM "{t}"')
            if self.ro_native is not None:
                self.ro_native(self, native)
        finally:
            native.close()

    def cleanup(self) -> None:
        if self.native_factory is None or not self.family:
            return
        native = self.native_factory(self)
        try:
            if self.fold_alias:
                for v in self._alias_views():
                    with contextlib.suppress(Exception):
                        native.run(f"DROP VIEW {v}")
            for stmt in ds.drop_statements(self.family):
                with contextlib.suppress(Exception):
                    native.run(stmt)
        finally:
            native.close()


def _ro_creds(o: dict[str, Any], e: Engine) -> tuple[str, str]:
    if o.get("readonly"):
        return RO_USER, RO_PASSWORD
    return e.user_, o.get("password") or e.password_


# --------------------------------------------------------------------------- MonetDB
def _monetdb_native(e: Engine) -> Native:
    import pymonetdb

    conn = pymonetdb.connect(
        hostname=e.host,
        port=e.port_,
        username=e.user_,
        password=e.password_,
        database=e.database_,
        autocommit=True,
    )
    return _dbapi_native(conn, commit=False)


def _monetdb_ro(e: Engine, native: Native) -> None:
    with contextlib.suppress(Exception):
        native.run(f"DROP USER {RO_USER}")
    native.run(
        f"CREATE USER {RO_USER} WITH PASSWORD '{RO_PASSWORD}' NAME 'qb read only' "
        'SCHEMA "sys"'
    )
    for t in (ds.T_DEPT, ds.T_EMP, ds.T_RES, ds.T_MIXED):
        native.run(f'GRANT SELECT ON "sys"."{t}" TO {RO_USER}')


def _kw_monetdb(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    user, pw = _ro_creds(o, e)
    return {
        "hostname": e.host,
        "port": e.port_,
        "username": user,
        "password": pw,
        "database": e.database_,
        "autocommit": True,
    }


register(
    SqlEngine(
        name="monetdb",
        connector="monetdb",
        async_connector="async_monetdb",
        tier="extended",
        family="monetdb",
        drivers=("pymonetdb",),
        pip="pymonetdb",
        port=41050,
        user="monetdb",
        password="qb_it_password",
        connector_factory=_kw_monetdb,
        native_factory=_monetdb_native,
        ro_native=_monetdb_ro,
        slow_sql=(
            "SELECT COUNT(*) FROM sys.columns a, sys.columns b, sys.columns c, sys.columns d"
        ),
        service="monetdb",
        container_port=50000,
    )
)


# --------------------------------------------------------------------------- Firebird
FIREBIRD_DB = "/var/lib/firebird/data/qb_it.fdb"


def _firebird_dsn(e: Engine) -> str:
    return f"{e.host}/{e.port_}:{e.env('DBPATH', FIREBIRD_DB)}"


def _firebird_native(e: Engine) -> Native:
    from firebird.driver import connect

    conn = connect(_firebird_dsn(e), user=e.user_, password=e.password_, charset="UTF8")
    return _dbapi_native(conn, commit=True)


def _kw_firebird(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    user, pw = _ro_creds(o, e)
    return {
        "database": _firebird_dsn(e),
        "user": user,
        "password": pw,
        "charset": "UTF8",
    }


def _firebird_ro(e: Engine, native: Native) -> None:
    root = e.env("ROOT_PASSWORD", "qb_it_root_password")
    from firebird.driver import connect

    # CREATE USER needs SYSDBA; the image sets SYSDBA's password from FIREBIRD_ROOT_PASSWORD
    conn = connect(_firebird_dsn(e), user="SYSDBA", password=root, charset="UTF8")
    try:
        cur = conn.cursor()
        try:
            cur.execute(f"DROP USER {RO_USER}")
            conn.commit()
        except Exception:  # noqa: BLE001 - first run: the user does not exist yet
            conn.rollback()
        cur.execute(f"CREATE USER {RO_USER} PASSWORD '{RO_PASSWORD}'")
        conn.commit()
        for t in (ds.T_DEPT, ds.T_EMP, ds.T_RES, ds.T_MIXED):
            cur.execute(f'GRANT SELECT ON "{t}" TO {RO_USER}')
        for v in (t.upper() for t in ALIASED):
            cur.execute(f"GRANT SELECT ON {v} TO {RO_USER}")
        conn.commit()
    finally:
        conn.close()


register(
    SqlEngine(
        name="firebird",
        connector="firebird",
        async_connector="async_firebird",
        tier="extended",
        family="firebird",
        drivers=("firebird.driver", "fdb"),
        pip="firebird-driver  # needs the fbclient shared library; use --linux",
        port=41051,
        user="qb",
        connector_factory=_kw_firebird,
        native_factory=_firebird_native,
        ro_native=_firebird_ro,
        slow_sql=(
            "SELECT COUNT(*) FROM rdb$fields a, rdb$fields b, rdb$fields c, rdb$fields d"
        ),
        service="firebird",
        container_port=3050,
        fold_alias=True,
    )
)


# --------------------------------------------------------------------------- Oracle
ds.FAMILIES["oracle"] = ds.Ddl(
    str_t="VARCHAR2(100)",
    nstr_t="VARCHAR2(100)",
    drop="DROP TABLE {t} CASCADE CONSTRAINTS PURGE",
)
ORACLE_SERVICE = "FREEPDB1"


def _oracle_connect(e: Engine, user: str, password: str) -> Any:
    import oracledb

    return oracledb.connect(
        user=user,
        password=password,
        host=e.host,
        port=e.port_,
        service_name=e.env("SERVICE", ORACLE_SERVICE),
    )


def _oracle_native(e: Engine) -> Native:
    conn = _oracle_connect(e, e.user_, e.password_)
    return _dbapi_native(conn, commit=True)


def _oracle_ro(e: Engine, native: Native) -> None:
    """Read-only login: SYSTEM creates it; a logon trigger points it at the data schema."""
    sysconn = _oracle_connect(e, "system", e.env("SYS_PASSWORD", "qb_it_sys_password"))
    try:
        cur = sysconn.cursor()
        with contextlib.suppress(Exception):
            cur.execute(f"DROP USER {RO_USER} CASCADE")
        cur.execute(f'CREATE USER {RO_USER} IDENTIFIED BY "{RO_PASSWORD}"')
        cur.execute(f"GRANT CREATE SESSION TO {RO_USER}")
        owner = e.user_.upper()
        names = [f'"{t}"' for t in (ds.T_DEPT, ds.T_EMP, ds.T_RES, ds.T_MIXED)]
        names += [t.upper() for t in ALIASED]
        for n in names:
            cur.execute(f"GRANT SELECT ON {owner}.{n} TO {RO_USER}")
        cur.execute(
            f"CREATE OR REPLACE TRIGGER {owner}.qb_ro_logon AFTER LOGON ON "
            f"{RO_USER.upper()}.SCHEMA BEGIN EXECUTE IMMEDIATE "
            f"'ALTER SESSION SET CURRENT_SCHEMA={owner}'; END;"
        )
    finally:
        sysconn.close()


def _kw_oracle(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    user, pw = _ro_creds(o, e)
    return {
        "user": user,
        "password": pw,
        "host": e.host,
        "port": e.port_,
        "service_name": e.env("SERVICE", ORACLE_SERVICE),
    }


register(
    SqlEngine(
        name="oracle",
        connector="oracle",
        tier="extended",
        family="oracle",
        drivers=("oracledb",),
        pip="oracledb  # thin mode, pure python",
        port=41052,
        connector_factory=_kw_oracle,
        native_factory=_oracle_native,
        ro_native=_oracle_ro,
        slow_sql="SELECT COUNT(*) FROM all_objects a, all_objects b, all_objects c",
        service="oracle",
        container_port=1521,
        fold_alias=True,
    )
)


# --------------------------------------------------------------------------- Vertica
ds.FAMILIES["vertica"] = ds.Ddl(drop="DROP TABLE IF EXISTS {t} CASCADE")


def _vertica_connect(e: Engine, user: str, password: str) -> Any:
    import vertica_python

    return vertica_python.connect(
        host=e.host,
        port=e.port_,
        user=user,
        password=password,
        database=e.database_,
        autocommit=True,
        connection_timeout=10,
    )


def _vertica_native(e: Engine) -> Native:
    return _dbapi_native(_vertica_connect(e, e.user_, e.password_), commit=False)


def _vertica_ro(e: Engine, native: Native) -> None:
    with contextlib.suppress(Exception):
        native.run(f"DROP USER {RO_USER}")
    native.run(f"CREATE USER {RO_USER} IDENTIFIED BY '{RO_PASSWORD}'")
    for t in (ds.T_DEPT, ds.T_EMP, ds.T_RES, ds.T_MIXED):
        native.run(f'GRANT SELECT ON "{t}" TO {RO_USER}')


def _kw_vertica(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    user, pw = _ro_creds(o, e)
    return {
        "host": e.host,
        "port": e.port_,
        "user": user,
        "password": pw,
        "database": e.database_,
        "connection_timeout": 10,
    }


register(
    SqlEngine(
        name="vertica",
        connector="vertica",
        tier="extended",
        family="vertica",
        drivers=("vertica_python",),
        pip="vertica-python",
        port=41053,
        user="dbadmin",
        password="",
        database="qb_it",
        connector_factory=_kw_vertica,
        native_factory=_vertica_native,
        ro_native=_vertica_ro,
        slow_sql=(
            "SELECT COUNT(*) FROM v_catalog.columns a CROSS JOIN v_catalog.columns b "
            "CROSS JOIN v_catalog.columns c"
        ),
        service="vertica",
        container_port=5433,
    )
)


# --------------------------------------------------------------------------- IBM (ibm_db)
def _ibm_dsn(
    e: Engine, user: str, password: str, database: str, extra: str = ""
) -> str:
    return (
        f"DATABASE={database};HOSTNAME={e.host};PORT={e.port_};PROTOCOL=TCPIP;"
        f"UID={user};PWD={password};{extra}"
    )


def _ibm_native(e: Engine, database: str) -> Native:
    import ibm_db_dbi

    conn = ibm_db_dbi.connect(_ibm_dsn(e, e.user_, e.password_, database), "", "")
    conn.set_autocommit(True)
    return _dbapi_native(conn, commit=False)


# ---- Db2 LUW
ds.FAMILIES["db2"] = ds.Ddl(drop="DROP TABLE {t}")


def _db2_native(e: Engine) -> Native:
    return _ibm_native(e, e.database_)


def _kw_db2(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {
        "dsn": _ibm_dsn(e, e.user_, o.get("password") or e.password_, e.database_),
        "schema_name": e.user_.upper(),
    }


register(
    SqlEngine(
        name="db2",
        connector="db2",
        async_connector="async_db2",
        tier="extended",
        family="db2",
        drivers=("ibm_db_dbi", "ibm_db"),
        pip="ibm_db",
        port=41054,
        user="db2inst1",
        password="qb_it_password",
        database="qbit",
        connector_factory=_kw_db2,
        native_factory=_db2_native,
        slow_sql=(
            "SELECT COUNT(*) FROM syscat.columns a, syscat.columns b, syscat.columns c"
        ),
        service="db2",
        container_port=50000,
        fold_alias=True,
        unsupported={
            "db_read_only": (
                "Db2 authenticates operating-system users; a restricted login would have to "
                "be created inside the container's OS, which the harness cannot do"
            ),
        },
    )
)


# ---- Informix (DRDA port of the developer image)
ds.FAMILIES["informix"] = ds.Ddl(drop="DROP TABLE IF EXISTS {t}")


def _informix_native(e: Engine) -> Native:
    return _ibm_native(e, e.database_)


def _kw_informix(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {
        "dsn": _ibm_dsn(e, e.user_, o.get("password") or e.password_, e.database_),
        "schema_name": e.user_,
    }


register(
    SqlEngine(
        name="informix",
        connector="informix",
        async_connector="async_informix",
        tier="extended",
        family="informix",
        drivers=("ibm_db_dbi", "ibm_db"),
        pip="ibm_db",
        port=41056,
        user="informix",
        password="in4mix",
        database="sysmaster",
        connector_factory=_kw_informix,
        native_factory=_informix_native,
        slow_sql=(
            "SELECT COUNT(*) FROM syscolumns a, syscolumns b, syscolumns c, syscolumns d"
        ),
        service="informix",
        container_port=9089,
    )
)
