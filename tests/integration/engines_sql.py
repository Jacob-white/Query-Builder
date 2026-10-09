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

ds.FAMILIES["monetdb"] = ds.Ddl(int_t="INTEGER", str_t="VARCHAR(100)", nstr_t="VARCHAR(100)")
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
    emp_cols = ", ".join(q(c) for c in ("id", "name", "dept_id", "salary", "age", "email"))
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


class SqlEngine(Engine):
    """Engine seeded with quoted-identifier DDL; DROPs are best-effort (no IF EXISTS everywhere)."""

    def seed(self) -> None:
        assert self.native_factory is not None
        native = self.native_factory(self)
        try:
            for stmt in _statements(self.family):
                if stmt.startswith("DROP"):
                    with contextlib.suppress(Exception):
                        native.run(stmt)
                else:
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

    conn = connect(
        _firebird_dsn(e), user=e.user_, password=e.password_, charset="UTF8"
    )
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
    conn = connect(
        _firebird_dsn(e), user="SYSDBA", password=root, charset="UTF8"
    )
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
    )
)
