"""
Smoke battery for non-SQL engines (see ``smoke.py``): the same assertions for
every document / key-value / search / graph / wide-column engine, through the
real connector classes.

Each test is tagged with a NATIVE-core category (``tests/integration/categories.py``).
A category the engine cannot exercise must be declared in ``Smoke.limitations`` (with a
probe through the native driver where possible); a category with neither checks nor a
limitation is reported as UNTESTED and keeps the engine below the ``certified`` tier.
"""

from __future__ import annotations

import traceback
from typing import Any

import pytest

from query_builder.security import SecurityError
from tests.integration import categories, smoke
from tests.integration.engines import ENGINES, Engine

cat = pytest.mark.qb_category

WRONG_PASSWORD = "Wr0ng-S3cret-Pw!x"


@pytest.fixture
def spec(smoke_engine: Engine) -> smoke.Smoke:
    return smoke.SMOKE[smoke_engine.name]  # seeded once per session by conftest


@pytest.fixture
def sconn(smoke_engine: Engine) -> Any:
    connector = smoke_engine.make_connector()
    connector.connect()
    try:
        yield connector
    finally:
        connector.close()


def _norm(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return sorted(
        ({str(k): v for k, v in r.items()} for r in rows), key=lambda r: str(r.get(key))
    )


def _skip_unless_checks(
    engine: Engine, spec: smoke.Smoke, category: str
) -> list[smoke.Check]:
    """The checks for a category, or a skip: declared limitation vs UNTESTED."""
    checks = spec.checks.get(category)
    if checks:
        return checks
    lim = spec.limitations.get(category)
    if lim is not None:
        pytest.skip(categories.limitation_reason(engine.name, category, lim.reason))
    pytest.skip(
        f"{engine.name}: no {category} check defined in Smoke and no limitation "
        "declared (UNTESTED)"
    )


def _run_check(sconn: Any, check: smoke.Check) -> None:
    result = sconn.execute(sql=check.statement, validate_ast=check.validate_ast)
    rows = result["rows"]
    if check.expect_count is not None:
        assert len(rows) == check.expect_count, (check.statement, rows)
        return
    got = check.extract(rows)
    context = f"{check.statement}: got {got!r} from rows {rows!r}"
    if check.subset:
        missing = [v for v in check.expected if v not in got]
        assert not missing, f"{missing!r} not found; {context}"
    elif check.ordered:
        assert got == check.expected, context
    else:
        assert sorted(map(str, got)) == sorted(map(str, check.expected)), context


@cat("connect")
def test_connect_and_test_connection(
    smoke_engine: Engine, spec: smoke.Smoke, sconn: Any
) -> None:
    info = sconn.test_connection()
    assert info["status"] == "healthy"
    assert info["dialect"] == sconn.dialect_name
    assert info.get("engine_version"), info


@cat("introspect")
def test_introspection_sees_the_seeded_object(
    smoke_engine: Engine, spec: smoke.Smoke, sconn: Any
) -> None:
    tables = {k.lower(): v for k, v in sconn.introspect_schema()["tables"].items()}
    assert spec.table.lower() in tables, f"{spec.table} not in {sorted(tables)}"
    cols = {c["name"].lower() for c in tables[spec.table.lower()]["columns"]}
    assert spec.columns <= cols, f"missing {spec.columns - cols} in {sorted(cols)}"


@cat("read_basic")
def test_native_read_through_the_connector(
    smoke_engine: Engine, spec: smoke.Smoke, sconn: Any
) -> None:
    result = sconn.execute(sql=spec.read, validate_ast=False)
    rows = result["rows"]
    if smoke_engine.name == "redis":  # RediSearch replies are one nested payload
        flat = str(rows)
        assert all(name in flat for _, name, _ in smoke.PEOPLE), flat
        return
    wanted = [
        {k: v for k, v in r.items() if k in ("name", "age")} for r in spec.expected
    ]
    got = [{k: v for k, v in r.items() if k in ("name", "age")} for r in rows]
    assert _norm(got, "name") == _norm(wanted, "name"), result["sql"]


@cat("spec_compile")
def test_query_spec_compiled_and_executed(
    request: pytest.FixtureRequest,
    smoke_engine: Engine,
    spec: smoke.Smoke,
    sconn: Any,
) -> None:
    _apply_known_issue(request, smoke_engine, spec)
    if spec.spec is None:
        lim = spec.limitations.get("spec_compile")
        reason = lim.reason if lim else "no SQL compiler path (native query language)"
        if lim is None:
            pytest.skip(f"{smoke_engine.name}: {reason}")
        pytest.skip(
            categories.limitation_reason(smoke_engine.name, "spec_compile", reason)
        )
    rows = sconn.execute(spec=spec.spec)["rows"]
    assert [{"name": r["name"], "age": r["age"]} for r in rows] == spec.spec_expected


@cat("read_filtered")
def test_filtered_reads(smoke_engine: Engine, spec: smoke.Smoke, sconn: Any) -> None:
    for check in _skip_unless_checks(smoke_engine, spec, "read_filtered"):
        _run_check(sconn, check)


@cat("ordering")
def test_ordered_reads(smoke_engine: Engine, spec: smoke.Smoke, sconn: Any) -> None:
    for check in _skip_unless_checks(smoke_engine, spec, "ordering"):
        _run_check(sconn, check)


@cat("pagination")
def test_paginated_reads(smoke_engine: Engine, spec: smoke.Smoke, sconn: Any) -> None:
    for check in _skip_unless_checks(smoke_engine, spec, "pagination"):
        _run_check(sconn, check)


@cat("value_safety")
def test_special_values_round_trip_as_data(
    smoke_engine: Engine, spec: smoke.Smoke, sconn: Any
) -> None:
    """Quotes, backslashes, ``%``/``_``, regex/JSON-looking text, unicode and an
    injection-looking string come back byte for byte, and the stored data survives."""
    for check in _skip_unless_checks(smoke_engine, spec, "value_safety"):
        _run_check(sconn, check)
    assert spec.check is not None
    assert spec.check(smoke_engine) == [{"count": 3}], "data changed by a read"


@cat("error_mapping")
def test_bad_native_queries_map_to_the_connector_error_family(
    request: pytest.FixtureRequest,
    smoke_engine: Engine,
    spec: smoke.Smoke,
    sconn: Any,
) -> None:
    """An engine/driver error must surface as ConnectorError/QueryBuilderError, never as a
    raw driver exception, and the connection stays usable."""
    from query_builder.connectors.base import ConnectorError
    from query_builder.exceptions import QueryBuilderError

    _apply_known_issue(request, smoke_engine, spec)
    if not spec.bad_queries:
        lim = spec.limitations.get("error_mapping")
        if lim is not None:
            pytest.skip(
                categories.limitation_reason(
                    smoke_engine.name, "error_mapping", lim.reason
                )
            )
        pytest.skip(
            f"{smoke_engine.name}: no bad_queries defined in Smoke (UNTESTED error mapping)"
        )
    for statement in spec.bad_queries:
        with pytest.raises(Exception) as err:  # noqa: PT011
            sconn.execute(sql=statement, validate_ast=False)
        assert isinstance(err.value, (ConnectorError, QueryBuilderError)), (
            f"{statement!r}: raw driver exception leaked: "
            f"{type(err.value).__module__}.{type(err.value).__name__}: {err.value}"
        )
    sconn.execute(sql=spec.read, validate_ast=False)  # still usable


@cat("write_refused")
def test_writes_are_rejected_and_data_survives(
    smoke_engine: Engine, spec: smoke.Smoke, sconn: Any
) -> None:
    for statement in spec.writes:  # layer 1: the AST validator
        with pytest.raises(SecurityError):
            sconn.execute(sql=statement)
    assert spec.check is not None
    assert spec.check(smoke_engine) == [{"count": 3}]


@cat("write_refused")
def test_writes_rejected_by_read_only_session_without_ast(
    request: pytest.FixtureRequest,
    smoke_engine: Engine,
    spec: smoke.Smoke,
    sconn: Any,
) -> None:
    """Layer 2: with the AST validator off the read-only session check must hold."""
    _apply_known_issue(request, smoke_engine, spec)
    for statement in spec.writes:
        try:
            sconn.execute(sql=statement, validate_ast=False)
        except Exception:  # noqa: BLE001 - refused client-side or by the engine itself
            continue
        pytest.fail(f"{smoke_engine.name}: write was accepted: {statement!r}")
    assert spec.check is not None
    assert spec.check(smoke_engine) == [{"count": 3}], "data changed by a write"


def _apply_known_issue(
    request: pytest.FixtureRequest, engine: Engine, spec: smoke.Smoke
) -> None:
    reason = spec.known_issues.get(request.node.originalname)
    if reason:
        request.applymarker(
            pytest.mark.xfail(reason=f"known issue, reported: {reason}", strict=True)
        )


@cat("secrets")
def test_wrong_password_never_leaks(smoke_engine: Engine, spec: smoke.Smoke) -> None:
    if not smoke_engine.password_:
        pytest.skip(f"{smoke_engine.name}: container runs without authentication")
    bad = smoke_engine.make_connector(password=WRONG_PASSWORD)
    with pytest.raises(Exception) as err:  # noqa: PT011
        bad.connect()
        bad.test_connection()
    text = "".join(
        traceback.format_exception(type(err.value), err.value, err.value.__traceback__)
    )
    assert WRONG_PASSWORD not in text
    assert WRONG_PASSWORD not in repr(bad) + str(bad)
    bad.close()


@cat("registry")
def test_registry_lists_every_smoke_engine() -> None:
    assert set(smoke.SMOKE) <= set(ENGINES)
