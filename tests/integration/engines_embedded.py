"""
Embedded / in-process engines and cloud-service emulators that need no server.

* ``datafusion`` / ``polars``: in-process SQL engines over in-memory tables. "Native seeding"
  means building the Arrow table / Polars DataFrame with the library's own API.
* ``generic_sqlite`` / ``generic_duckdb``: ``GenericDBAPIConnector`` over real DB-API connections.
* ``snowflake_fakesnow``: ``SnowflakeConnector`` against the ``fakesnow`` emulator (DuckDB-backed).
  EMULATED: it is not the Snowflake service, dialect fidelity is partial.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests.integration import dataset
from tests.integration.engines import Engine, Native, register

_SCRATCH = Path(tempfile.gettempdir()) / "qb_integration"

_NO_SQL_CONSTRAINTS = {
    "introspect_fk": "in-memory tables carry no foreign keys",
    "statement_timeout": "in-process engine: no statement timeout / cancellation",
    "db_read_only": "no separate read-only login on an in-process engine",
    "case_sensitive_identifiers": "identifiers are case-insensitive here",
}


# --------------------------------------------------------------------------- frames
def _columns() -> dict[str, tuple[list[str], list[list[Any]], dict[str, bool]]]:
    """table -> (column names, column values, nullable flags) built from dataset constants."""
    emp = dataset.EMPLOYEES
    res = dataset.RESERVED
    return {
        dataset.T_DEPT: (
            ["id", "name"],
            [[r[0] for r in dataset.DEPARTMENTS], [r[1] for r in dataset.DEPARTMENTS]],
            {"id": False, "name": False},
        ),
        dataset.T_EMP: (
            ["id", "name", "dept_id", "salary", "age", "email"],
            [[r[i] for r in emp] for i in range(6)],
            {
                "id": False,
                "name": False,
                "dept_id": True,
                "salary": False,
                "age": False,
                "email": True,
            },
        ),
        dataset.T_RES: (
            ["id", "select", "group", "order", "MixedCase", dataset.UNICODE_COL],
            [[r[i] for r in res] for i in range(6)],
            {"id": False},
        ),
        dataset.T_MIXED: (["id", "val"], [[1], ["mixed"]], {"id": False}),
    }


def _arrow_tables() -> dict[str, Any]:
    import pyarrow as pa
    import pyarrow.dataset as pyarrow_dataset

    out = {}
    for table, (names, cols, nullable) in _columns().items():
        fields, arrays = [], []
        for name, values in zip(names, cols, strict=True):
            typ = pa.int32() if all(isinstance(v, int | None) for v in values) else pa.string()
            fields.append(pa.field(name, typ, nullable=nullable.get(name, False)))
            arrays.append(pa.array(values, type=typ))
        out[table] = pyarrow_dataset.dataset(
            pa.Table.from_arrays(arrays, schema=pa.schema(fields))
        )
    return out


def _polars_frames() -> dict[str, Any]:
    import polars as pl

    out = {}
    for table, (names, cols, _n) in _columns().items():
        out[table] = pl.DataFrame(dict(zip(names, cols, strict=True)))
    return out


@dataclass
class _InMemoryEngine(Engine):
    """Engine whose "database" is a set of in-memory tables owned by the test process."""

    frames: Callable[[], dict[str, Any]] | None = None  # noqa: F821
    _tables: dict[str, Any] = field(default_factory=dict)

    def seed(self) -> None:
        assert self.frames is not None
        self._tables = self.frames()

    def cleanup(self) -> None:
        self._tables = {}


def _df_kwargs(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    assert isinstance(e, _InMemoryEngine)
    return {"tables": dict(e._tables)}


def _df_native(e: Engine) -> Native:  # pragma: no cover - unused, seed() is overridden
    return Native(lambda _s: None, lambda: None)


from collections.abc import Callable  # noqa: E402

_DF_UNSUPPORTED = {
    **_NO_SQL_CONSTRAINTS,
    "introspect_pk": "the connector marks a column named `id` as primary: heuristic, tables have no PK",
}

register(
    _InMemoryEngine(
        name="datafusion",
        connector="datafusion",
        tier="embedded",
        family="duckdb",
        drivers=("datafusion",),
        pip="datafusion",
        connector_factory=_df_kwargs,
        native_factory=_df_native,
        frames=_arrow_tables,
        unsupported=dict(_DF_UNSUPPORTED),
    )
)
register(
    _InMemoryEngine(
        name="polars",
        connector="polars",
        tier="embedded",
        family="duckdb",
        drivers=("polars",),
        pip="polars",
        connector_factory=_df_kwargs,
        native_factory=_df_native,
        frames=_polars_frames,
        unsupported={
            **_DF_UNSUPPORTED,
            "introspect_not_null": "Polars frames have no NOT NULL metadata",
        },
    )
)



# ------------------------------------------------------------- GenericDBAPIConnector
def _scratch_path(name: str, ext: str) -> str:
    _SCRATCH.mkdir(parents=True, exist_ok=True)
    return str(_SCRATCH / f"qb_it_{name}.{ext}")


def _generic_sqlite_native(e: Engine) -> Native:
    import sqlite3

    conn = sqlite3.connect(_scratch_path(e.name, "db"))

    def run(sql: str) -> Any:
        cur = conn.cursor()
        try:
            cur.execute(sql)
            return cur.fetchall() if cur.description else None
        finally:
            cur.close()
            conn.commit()

    return Native(run, conn.close)


def _kw_generic_sqlite(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    import sqlite3

    path = _scratch_path(e.name, "db")
    if o.get("readonly"):
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    else:
        conn = sqlite3.connect(path, check_same_thread=False)
    return {"connection": conn, "dialect": "sqlite"}


def _generic_duckdb_native(e: Engine) -> Native:
    import duckdb

    conn = duckdb.connect(_scratch_path(e.name, "duckdb"))
    return Native(conn.execute, conn.close)


def _kw_generic_duckdb(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    import duckdb

    kw: dict[str, Any] = {}
    if o.get("readonly"):
        kw["read_only"] = True
    return {
        "connection": duckdb.connect(_scratch_path(e.name, "duckdb"), **kw),
        "dialect": "duckdb",
    }


register(
    Engine(
        name="generic_sqlite",
        connector="generic",
        tier="embedded",
        family="sqlite",
        drivers=("sqlite3",),
        pip="(stdlib)",
        connector_factory=_kw_generic_sqlite,
        native_factory=_generic_sqlite_native,
        unsupported={
            "statement_timeout": "sqlite3 has no statement timeout",
            "case_sensitive_identifiers": "SQLite identifiers are case-insensitive",
        },
    )
)
register(
    Engine(
        name="generic_duckdb",
        connector="generic",
        tier="embedded",
        family="duckdb",
        drivers=("duckdb",),
        pip="duckdb",
        connector_factory=_kw_generic_duckdb,
        native_factory=_generic_duckdb_native,
        unsupported={
            "statement_timeout": "DuckDB has no statement timeout setting",
            "case_sensitive_identifiers": "DuckDB identifiers are case-insensitive",
        },
    )
)


def _generic_pg_native(e: Engine) -> Native:
    import psycopg

    conn = psycopg.connect(
        host=e.host,
        port=e.port_,
        user=e.user_,
        password=e.password_,
        dbname=e.database_,
        autocommit=True,
    )

    def run(sql: str) -> Any:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall() if cur.description else None

    return Native(run, conn.close)


def _kw_generic_psycopg(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    import psycopg

    def raw_connection() -> Any:
        return psycopg.connect(
            host=e.host,
            port=e.port_,
            user=e.user_,
            password=o.get("password") or e.password_,
            dbname=e.database_,
            connect_timeout=5,
        )

    if o.get("password"):  # the wrong-password test: the failure must surface in connect()

        from types import SimpleNamespace

        lazy = SimpleNamespace(raw_connection=raw_connection)
        return {"engine": lazy, "dialect": "postgres"}
    return {"connection": raw_connection(), "dialect": "postgres"}


register(
    Engine(
        name="generic_psycopg",
        connector="generic",
        tier="extended",
        family="pg",
        drivers=("psycopg",),
        pip="'psycopg[binary]'",
        port=45432,
        connector_factory=_kw_generic_psycopg,
        native_factory=_generic_pg_native,
        slow_sql="SELECT pg_sleep(30)",
        service="generic_pg",
        container_port=5432,
        unsupported={
            "statement_timeout": "GenericDBAPIConnector does not set a statement timeout (driver-agnostic)",
            "db_read_only": "no separate read-only login is provisioned for the generic class",
        },
    )
)


# ------------------------------------------------------ LanceDB / ChromaDB (smoke engines)
_DIRS: dict[str, str] = {}


def _fresh_dir(name: str) -> str:
    import shutil
    import uuid

    old = _DIRS.get(name)
    if old:
        shutil.rmtree(old, ignore_errors=True)
    _SCRATCH.mkdir(parents=True, exist_ok=True)
    path = str(_SCRATCH / f"qb_it_{name}_{uuid.uuid4().hex[:8]}")
    _DIRS[name] = path
    return path


def _seed_lancedb(e: Engine) -> None:
    import lancedb

    from tests.integration import smoke

    db = lancedb.connect(_fresh_dir("lancedb"))
    db.create_table(
        "qbit_people",
        data=[
            {"id": i, "name": n, "age": a, "vector": [float(i), 1.0]}
            for i, n, a in smoke.PEOPLE
        ],
    )


def _lancedb_count(e: Engine) -> list[dict[str, Any]]:
    import lancedb

    table = lancedb.connect(_DIRS["lancedb"]).open_table("qbit_people")
    return [{"count": table.count_rows()}]


def _seed_chroma(e: Engine) -> None:
    import chromadb

    from tests.integration import smoke

    client = chromadb.PersistentClient(path=_fresh_dir("chroma"))
    col = client.create_collection("qbit_people")
    col.add(
        ids=[str(i) for i, _, _ in smoke.PEOPLE],
        documents=[n for _, n, _ in smoke.PEOPLE],
        metadatas=[{"name": n, "age": a} for _, n, a in smoke.PEOPLE],
        embeddings=[[float(i), 1.0] for i, _, _ in smoke.PEOPLE],
    )


def _chroma_count(e: Engine) -> list[dict[str, Any]]:
    import chromadb

    client = chromadb.PersistentClient(path=_DIRS["chroma"])
    return [{"count": client.get_collection("qbit_people").count()}]


def _register_vector_smoke() -> None:
    from tests.integration import smoke

    smoke.SMOKE["lancedb"] = smoke.Smoke(
        seed=_seed_lancedb,
        table="qbit_people",
        columns={"id", "name", "age", "vector"},
        read="SELECT name, age FROM qbit_people ORDER BY age",
        expected=smoke.BY_AGE,
        writes=smoke.SQL_WRITES,
        check=_lancedb_count,
    )
    smoke.SMOKE["chroma"] = smoke.Smoke(
        seed=_seed_chroma,
        table="qbit_people",
        columns={"id", "document", "name", "age"},
        read="SELECT name, age FROM qbit_people WHERE age >= 28 ORDER BY age",
        expected=smoke.BY_AGE,
        writes=smoke.SQL_WRITES,
        check=_chroma_count,
    )


_register_vector_smoke()

register(
    Engine(
        name="lancedb",
        connector="lancedb",
        async_connector="async_lancedb",
        tier="embedded",
        family="",
        drivers=("lancedb",),
        pip="lancedb",
        connector_factory=lambda e, o: {"uri": _DIRS["lancedb"]},
        password="",
    )
)
register(
    Engine(
        name="chroma",
        connector="chroma",
        async_connector="async_chroma",
        tier="embedded",
        family="",
        drivers=("chromadb",),
        pip="chromadb",
        connector_factory=lambda e, o: {"path": _DIRS["chroma"]},
        password="",
    )
)


# ------------------------------------------------- Snowflake through the fakesnow emulator
_FAKESNOW: dict[str, Any] = {}


def _fakesnow_up() -> None:
    """Patch snowflake.connector.connect to the DuckDB-backed emulator, once per process."""
    if "ctx" in _FAKESNOW:
        return
    import atexit

    import fakesnow

    path = _fresh_dir("fakesnow")
    Path(path).mkdir(parents=True, exist_ok=True)
    ctx = fakesnow.patch(db_path=path)
    ctx.__enter__()
    _FAKESNOW["ctx"] = ctx
    atexit.register(lambda: ctx.__exit__(None, None, None))


class _SnowCursor:
    """fakesnow does not implement ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS (an
    emulator gap, the real service does): swallow exactly that statement, nothing else."""

    def __init__(self, cur: Any) -> None:
        self._cur = cur

    def execute(self, sql: str, *a: Any, **kw: Any) -> Any:
        if sql.strip().upper().startswith("ALTER SESSION SET STATEMENT_TIMEOUT"):
            return self
        self._cur.execute(sql, *a, **kw)
        return self

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cur, name)

    def __iter__(self) -> Any:
        return iter(self._cur)


class _SnowConn:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def cursor(self) -> _SnowCursor:
        return _SnowCursor(self._conn.cursor())

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def _snow_connect() -> Any:
    _fakesnow_up()
    import snowflake.connector

    return snowflake.connector.connect(database="QB_IT", schema="PUBLIC")


def _snow_statements() -> list[str]:
    """The standard dataset with EVERY identifier quoted (Snowflake folds unquoted names to
    upper case, while the compiler emits quoted lower-case names)."""
    d, e, r, m = dataset.T_DEPT, dataset.T_EMP, dataset.T_RES, dataset.T_MIXED

    def lit(v: Any) -> str:
        if v is None:
            return "NULL"
        return str(v) if isinstance(v, int) else "'" + str(v).replace("'", "''") + "'"

    stmts = [f'DROP TABLE IF EXISTS "{t}"' for t in (e, r, m, d)]
    stmts += [
        f'CREATE TABLE "{d}" ("id" INTEGER NOT NULL, "name" VARCHAR(100) NOT NULL, '
        'PRIMARY KEY ("id"))',
        f'CREATE TABLE "{e}" ("id" INTEGER NOT NULL, "name" VARCHAR(100) NOT NULL, '
        '"dept_id" INTEGER, "salary" INTEGER NOT NULL, "age" INTEGER NOT NULL, '
        '"email" VARCHAR(100), PRIMARY KEY ("id"), '
        f'FOREIGN KEY ("dept_id") REFERENCES "{d}" ("id"))',
        f'CREATE TABLE "{r}" ("id" INTEGER NOT NULL, "select" INTEGER NOT NULL, '
        '"group" VARCHAR(100) NOT NULL, "order" INTEGER NOT NULL, '
        '"MixedCase" VARCHAR(100) NOT NULL, '
        f'"{dataset.UNICODE_COL}" VARCHAR(100) NOT NULL, PRIMARY KEY ("id"))',
        f'CREATE TABLE "{m}" ("id" INTEGER NOT NULL, "val" VARCHAR(100) NOT NULL, '
        'PRIMARY KEY ("id"))',
    ]
    stmts += [
        f'INSERT INTO "{d}" ("id", "name") VALUES ({row[0]}, {lit(row[1])})'
        for row in dataset.DEPARTMENTS
    ]
    stmts += [
        f'INSERT INTO "{e}" ("id", "name", "dept_id", "salary", "age", "email") '
        f"VALUES ({', '.join(lit(v) for v in row)})"
        for row in dataset.EMPLOYEES
    ]
    cols = ", ".join(
        f'"{c}"' for c in ("id", "select", "group", "order", "MixedCase", dataset.UNICODE_COL)
    )
    stmts += [
        f'INSERT INTO "{r}" ({cols}) VALUES ({", ".join(lit(v) for v in row)})'
        for row in dataset.RESERVED
    ]
    stmts.append(f"INSERT INTO \"{m}\" (\"id\", \"val\") VALUES (1, 'mixed')")
    return stmts


@dataclass
class _SnowflakeEmulatedEngine(Engine):
    def seed(self) -> None:
        conn = _snow_connect()
        try:
            cur = conn.cursor()
            for stmt in _snow_statements():
                cur.execute(stmt)
        finally:
            conn.close()

    def cleanup(self) -> None:
        return None


register(
    _SnowflakeEmulatedEngine(
        name="snowflake_fakesnow",
        connector="snowflake",
        tier="embedded",
        family="pg",
        drivers=("fakesnow", "snowflake.connector"),
        pip="fakesnow snowflake-connector-python",
        password="",
        emulated=True,
        connector_factory=lambda e, o: {"connection": _SnowConn(_snow_connect())},
        native_factory=None,
        unsupported={
            "statement_timeout": "fakesnow does not implement STATEMENT_TIMEOUT or cancellation",
            "introspect_fk": (
                "fakesnow's SHOW IMPORTED KEYS returns the PRIMARY keys with swapped columns "
                "(emulator bug): the connector's FK path follows the Snowflake docs but "
                "is NOT live-verified"
            ),
            "db_read_only": "fakesnow has no roles/grants",
            "case_sensitive_identifiers": "DuckDB (fakesnow) folds identifier case",
        },
    )
)
