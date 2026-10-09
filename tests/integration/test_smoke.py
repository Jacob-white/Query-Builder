"""
Smoke battery for non-SQL engines (see ``smoke.py``): the same assertions for
every document / key-value / search / graph / wide-column engine, through the
real connector classes.
"""

from __future__ import annotations

import traceback
from typing import Any

import pytest

from query_builder.security import SecurityError
from tests.integration import smoke
from tests.integration.engines import ENGINES, Engine

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


def test_connect_and_test_connection(
    smoke_engine: Engine, spec: smoke.Smoke, sconn: Any
) -> None:
    info = sconn.test_connection()
    assert info["status"] == "healthy"
    assert info["dialect"] == sconn.dialect_name
    assert info.get("engine_version"), info


def test_introspection_sees_the_seeded_object(
    smoke_engine: Engine, spec: smoke.Smoke, sconn: Any
) -> None:
    tables = {k.lower(): v for k, v in sconn.introspect_schema()["tables"].items()}
    assert spec.table.lower() in tables, f"{spec.table} not in {sorted(tables)}"
    cols = {c["name"].lower() for c in tables[spec.table.lower()]["columns"]}
    assert spec.columns <= cols, f"missing {spec.columns - cols} in {sorted(cols)}"


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


def test_query_spec_compiled_and_executed(
    request: pytest.FixtureRequest,
    smoke_engine: Engine,
    spec: smoke.Smoke,
    sconn: Any,
) -> None:
    _apply_known_issue(request, smoke_engine, spec)
    if spec.spec is None:
        pytest.skip(
            f"{smoke_engine.name}: no SQL compiler path (native query language)"
        )
    rows = sconn.execute(spec=spec.spec)["rows"]
    assert [{"name": r["name"], "age": r["age"]} for r in rows] == spec.spec_expected


def test_writes_are_rejected_and_data_survives(
    smoke_engine: Engine, spec: smoke.Smoke, sconn: Any
) -> None:
    for statement in spec.writes:  # layer 1: the AST validator
        with pytest.raises(SecurityError):
            sconn.execute(sql=statement)
    assert spec.check is not None
    assert spec.check(smoke_engine) == [{"count": 3}]


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


def test_registry_lists_every_smoke_engine() -> None:
    assert set(smoke.SMOKE) <= set(ENGINES)
