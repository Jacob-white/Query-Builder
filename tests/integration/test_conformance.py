"""
Shared live conformance battery.

One parametrized suite, run against every available SQL engine through the REAL
connector class (no mocks). The engine is seeded through its native driver;
every assertion goes through ``query_builder``. Features an engine legitimately
lacks are declared in ``engines.Engine.unsupported`` and SKIPPED with the
reason, never silently passed.
"""

from __future__ import annotations

import time
import traceback
from typing import Any

import pytest

from query_builder.security import SecurityError
from tests.integration import cases as cs
from tests.integration import categories
from tests.integration import dataset as ds
from tests.integration.engines import Engine

cat = pytest.mark.qb_category

WRONG_PASSWORD = "Wr0ng-S3cret-Pw!x"


def need(engine: Engine, *features: str) -> None:
    """Skip (naming the declared limitation) when the engine declares it cannot do a feature.

    The skip message carries the feature so the report can classify it as
    ``verified_limitation`` (probe confirmed) or ``declared_unverified`` (no probe).
    """
    for feat in features:
        lim = engine.limitation(feat)
        if lim is not None:
            pytest.skip(categories.limitation_reason(engine.name, feat, lim.reason))


def _sorted(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: repr(sorted(r.items(), key=lambda kv: kv[0])))


def _count(conn: Any) -> int:
    res = conn.execute(
        spec={
            "table": ds.T_EMP,
            "columns": [{"column": "id", "agg": "count", "alias": "n"}],
            "limit": 5,
        }
    )
    return int(cs.norm(res["rows"][0]["n"]))


# ------------------------------------------------------------------ connectivity
@cat("connect")
def test_connect_and_test_connection(conn: Any, engine: Engine) -> None:
    info = conn.test_connection()
    assert info["status"] == "healthy"
    assert info["dialect"] == conn.dialect_name
    assert info.get("engine_version"), f"no engine_version reported: {info}"
    assert info["latency_ms"] >= 0


# ------------------------------------------------------------------ introspection
def _tables(schema: dict[str, Any]) -> dict[str, Any]:
    return {k.lower(): v for k, v in schema["tables"].items()}


@cat("introspect_tables")
def test_introspection_finds_seeded_tables(conn: Any, engine: Engine) -> None:
    tables = _tables(conn.introspect_schema(filter_sensitive=False))
    for t in (ds.T_DEPT, ds.T_EMP, ds.T_RES, ds.T_MIXED):
        assert t.lower() in tables, f"{t} missing from {sorted(tables)}"


@cat("introspect_columns")
def test_introspection_finds_seeded_columns(conn: Any, engine: Engine) -> None:
    tables = _tables(conn.introspect_schema(filter_sensitive=False))
    cols = {c["name"].lower() for c in tables[ds.T_EMP.lower()]["columns"]}
    assert cols == {"id", "name", "dept_id", "salary", "age", "email"}
    res_cols = {c["name"].lower() for c in tables[ds.T_RES.lower()]["columns"]}
    assert {"select", "group", "order", "mixedcase", ds.UNICODE_COL} <= res_cols
    nullable = {
        c["name"].lower(): c["is_nullable"] for c in tables[ds.T_EMP.lower()]["columns"]
    }
    assert nullable["email"] is True
    if "introspect_not_null" not in engine.unsupported:
        assert nullable["id"] is False, "NOT NULL column reported nullable"


@cat("introspect_pk_fk")
def test_introspection_primary_keys(conn: Any, engine: Engine) -> None:
    need(engine, "introspect_pk")
    tables = _tables(conn.introspect_schema(filter_sensitive=False))
    for t in (ds.T_DEPT, ds.T_EMP, ds.T_MIXED):
        primary = {c["name"] for c in tables[t.lower()]["columns"] if c["is_primary"]}
        assert primary == {"id"}, f"{t}: primary key columns {primary}"


@cat("introspect_pk_fk")
def test_introspection_foreign_keys(conn: Any, engine: Engine) -> None:
    need(engine, "introspect_fk")
    schema = conn.introspect_schema(filter_sensitive=False)
    fks = [
        (
            f["table"].lower(),
            f["column"],
            f["foreign_table"].lower(),
            f["foreign_column"],
        )
        for f in schema["foreign_keys"]
    ]
    assert (ds.T_EMP, "dept_id", ds.T_DEPT, "id") in fks, fks


# ------------------------------------------------------------------ query cases
@pytest.mark.parametrize("case", cs.CASES, ids=lambda c: c.id)
def test_compile_and_execute(conn: Any, engine: Engine, case: cs.Case) -> None:
    need(engine, *case.requires)
    result = conn.execute(spec=case.spec)
    got = cs.norm_rows(result["rows"])
    want = cs.norm_rows(case.expected)
    if not case.ordered:
        got, want = _sorted(got), _sorted(want)
    assert got == want, f"\nSQL: {result['sql']}\nparams: {result['params']}"
    if case.expected_count is not None:
        assert int(result["count"]) == case.expected_count, result["sql"]


@cat("identifier_quoting")
def test_non_ascii_identifiers_are_rejected_before_reaching_the_database(
    conn: Any, engine: Engine
) -> None:
    """Identifiers are ASCII-only by design (IDENTIFIER_REGEX): reject, never guess."""
    from query_builder.exceptions import ValidationError

    with pytest.raises(ValidationError):
        conn.execute(spec={"table": ds.T_RES, "columns": [ds.UNICODE_COL], "limit": 5})


# ------------------------------------------------------------------ parameter binding
EVIL_VALUES = [
    "'; DROP TABLE qbit_employees; --",
    "x' OR '1'='1",
    "x' UNION SELECT name FROM qbit_departments --",
    "\\'; DELETE FROM qbit_employees; --",
    "1; DELETE FROM qbit_employees",
]


@cat("parameter_safety")
@pytest.mark.parametrize("value", EVIL_VALUES)
def test_injection_looking_values_are_data(
    conn: Any, engine: Engine, value: str
) -> None:
    for op in ("eq", "neq", "contains", "starts_with", "like"):
        spec = {
            "table": ds.T_EMP,
            "columns": ["id"],
            "filters": [{"column": "name", "op": op, "value": value}],
            "limit": 50,
        }
        rows = conn.execute(spec=spec)["rows"]
        if op == "neq":
            assert len(rows) == 8  # every real name differs from the payload
        else:
            assert rows == [], f"{op} returned rows for {value!r}"
    assert _count(conn) == 8, "data changed after injection-looking values"


@cat("parameter_safety")
def test_raw_sql_parameter_binding(conn: Any, engine: Engine) -> None:
    ph = conn.dialect.placeholder
    sql = f"SELECT id FROM {ds.T_EMP} WHERE name = {ph} ORDER BY id"
    assert cs.norm_rows(conn.execute(sql=sql, params=["Alice"])["rows"]) == [{"id": 1}]
    for value in EVIL_VALUES:
        assert conn.execute(sql=sql, params=[value])["rows"] == []
    assert _count(conn) == 8


# ------------------------------------------------------------------ read-only
WRITES = [
    f"DELETE FROM {ds.T_EMP}",
    f"UPDATE {ds.T_EMP} SET salary = 1",
    f"INSERT INTO {ds.T_DEPT} (id, name) VALUES (99, 'x')",
    f"DROP TABLE {ds.T_EMP}",
    f"TRUNCATE TABLE {ds.T_EMP}",
    "CREATE TABLE qbit_should_not_exist (id INTEGER)",
    f"ALTER TABLE {ds.T_EMP} ADD COLUMN x INTEGER",
    f"SELECT 1; DROP TABLE {ds.T_EMP}",
    f"WITH x AS (SELECT 1) DELETE FROM {ds.T_EMP}",
]


@cat("write_refused")
@pytest.mark.parametrize("sql", WRITES)
def test_writes_rejected_by_validator(conn: Any, engine: Engine, sql: str) -> None:
    with pytest.raises(SecurityError):
        conn.execute(sql=sql)
    assert _count(conn) == 8


@cat("write_refused")
@pytest.mark.parametrize("sql", WRITES[:3])
def test_writes_rejected_by_read_only_session_even_without_ast(
    conn: Any, engine: Engine, sql: str
) -> None:
    with pytest.raises(SecurityError):
        conn.execute(sql=sql, validate_ast=False)
    assert _count(conn) == 8


@cat("write_refused")
def test_database_enforces_read_only_behind_the_validator(
    engine: Engine,
) -> None:
    need(engine, "db_read_only")
    ro = engine.make_connector(readonly=True)
    try:
        ro.connect()
        res = ro.execute(sql=f"SELECT COUNT(*) AS n FROM {ds.T_EMP}")
        assert cs.norm_rows(res["rows"])[0]["n"] == 8  # folds alias case
        # bypass every client-side check: the database itself must refuse
        with pytest.raises(Exception) as err:  # noqa: PT011
            ro.execute_raw(f"DELETE FROM {ds.T_EMP}")
        assert not isinstance(err.value, SecurityError)
    finally:
        ro.close()
    check = engine.make_connector()
    try:
        check.connect()
        assert _count(check) == 8
    finally:
        check.close()


# ------------------------------------------------------------------ timeout
@cat("statement_timeout")
def test_statement_timeout_cancels_slow_query(conn: Any, engine: Engine) -> None:
    need(engine, "statement_timeout")
    assert engine.slow_sql
    started = time.perf_counter()
    with pytest.raises(Exception):  # noqa: B017, PT011
        conn.execute(sql=engine.slow_sql, timeout_ms=1000, validate_ast=False)
    elapsed = time.perf_counter() - started
    assert elapsed < 15, (
        f"query was not cancelled by the statement timeout ({elapsed:.1f}s)"
    )
    # the connection/pool must still be usable afterwards
    fresh = engine.make_connector()
    try:
        fresh.connect()
        assert _count(fresh) == 8
    finally:
        fresh.close()


# ------------------------------------------------------------------ secrets
@cat("secrets")
def test_wrong_password_error_never_leaks_the_password(engine: Engine) -> None:
    if engine.embedded or not engine.password_:
        pytest.skip(f"{engine.name}: no password-based authentication")
    bad = engine.make_connector(password=WRONG_PASSWORD)
    with pytest.raises(Exception) as err:  # noqa: PT011
        bad.connect()
        bad.test_connection()
    rendered = "".join(
        traceback.format_exception(type(err.value), err.value, err.value.__traceback__)
    )
    chain = []
    cur: BaseException | None = err.value
    while cur is not None and len(chain) < 10:
        chain.append(f"{type(cur).__name__}: {cur}")
        cur = cur.__cause__ or cur.__context__
    assert WRONG_PASSWORD not in rendered
    assert all(WRONG_PASSWORD not in c for c in chain), chain
    assert WRONG_PASSWORD not in repr(bad)
    assert WRONG_PASSWORD not in str(bad)
    bad.close()


#: Defects found by the error_mapping battery and REPORTED, not fixed here: the connector lets
#: the vendor driver's exception escape instead of wrapping it in the ConnectorError family.
#: They run as strict xfails (flip to failures once fixed; never count towards `certified`).
#: Engines not listed run the checks for real and fail if they leak.
RAW_ERROR_LEAKS: dict[str, str] = {
    "postgres": "psycopg.errors.* escape PostgresConnector.execute unwrapped",
    "sqlite": "sqlite3.OperationalError escapes SQLiteConnector.execute unwrapped",
    "duckdb": "duckdb.BinderException/ParserException escape DuckDBConnector.execute unwrapped",
}


def _known_raw_leak(request: pytest.FixtureRequest, engine: Engine) -> None:
    reason = RAW_ERROR_LEAKS.get(engine.name)
    if reason:
        request.applymarker(
            pytest.mark.xfail(reason=f"known issue, reported: {reason}", strict=True)
        )


@cat("error_mapping")
def test_unknown_table_fails_cleanly(
    request: pytest.FixtureRequest, conn: Any, engine: Engine
) -> None:
    _known_raw_leak(request, engine)
    with pytest.raises(Exception) as err:  # noqa: PT011
        conn.execute(
            spec={"table": "qbit_no_such_table", "columns": ["id"], "limit": 5}
        )
    assert not isinstance(err.value, SecurityError)
    assert_mapped_error(err.value)
    assert _count(conn) == 8  # connection still usable


BAD_SQL = [
    "SELEC id FROM qbit_employees",  # syntax error
    "SELECT nosuchcolumn FROM qbit_employees",  # unknown column
]


@cat("error_mapping")
@pytest.mark.parametrize("sql", BAD_SQL)
def test_bad_native_sql_maps_to_the_connector_error_family(
    request: pytest.FixtureRequest, conn: Any, engine: Engine, sql: str
) -> None:
    """A database error must surface as the library's error family, never a raw driver
    exception (``psycopg.Error``, ``sqlite3.OperationalError``, ...)."""
    _known_raw_leak(request, engine)
    with pytest.raises(Exception) as err:  # noqa: PT011
        conn.execute(sql=sql, validate_ast=False)
    assert_mapped_error(err.value)
    assert _count(conn) == 8  # connection still usable afterwards


def assert_mapped_error(exc: BaseException) -> None:
    from query_builder.connectors.base import ConnectorError
    from query_builder.exceptions import QueryBuilderError

    assert isinstance(exc, (ConnectorError, QueryBuilderError)), (
        f"raw driver exception leaked: {type(exc).__module__}.{type(exc).__name__}: {exc}"
    )
