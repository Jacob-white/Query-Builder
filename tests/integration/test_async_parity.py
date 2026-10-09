"""
Async connector parity battery. For every engine with an async connector class the
async class must connect, report health, introspect, read, and refuse writes with
the same results as the sync class on the same live data.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any, TypeVar

import pytest

from query_builder.security import SecurityError
from tests.integration import cases as cs
from tests.integration import smoke
from tests.integration.engines import Engine

T = TypeVar("T")


def run(coro: Awaitable[T]) -> T:
    return asyncio.run(coro)  # type: ignore[arg-type]


async def _with_connector(engine: Engine, fn: Any) -> Any:
    conn = engine.make_async_connector()
    try:
        await conn.connect()
        return await fn(conn)
    finally:
        closer = conn.close()
        if asyncio.iscoroutine(closer):
            await closer


def _need_cassandra_reactor(engine: Engine) -> None:
    pass


def test_async_connect_and_test_connection(async_engine: Engine) -> None:
    async def body(conn: Any) -> dict[str, Any]:
        return await conn.test_connection()

    info = run(_with_connector(async_engine, body))
    assert info["status"] == "healthy"
    assert info["dialect"] == async_engine.make_async_connector().dialect_name


def _table_columns(snapshot: dict[str, Any]) -> dict[str, set[str]]:
    return {
        name.lower(): {c["name"].lower() for c in t["columns"]}
        for name, t in snapshot["tables"].items()
    }


def test_async_introspection_matches_sync(async_engine: Engine) -> None:
    sync = async_engine.make_connector()
    sync.connect()
    try:
        expected = _table_columns(sync.introspect_schema(filter_sensitive=False))
    finally:
        sync.close()
    assert expected, "sync introspection found nothing to compare with"

    async def body(conn: Any) -> dict[str, Any]:
        return await conn.introspect_schema(filter_sensitive=False)

    got = _table_columns(run(_with_connector(async_engine, body)))
    interesting = {t for t in expected if t.startswith("qbit_") or t == "person"}
    assert interesting, expected
    for table in interesting:
        assert got.get(table) == expected[table], (table, got.get(table))


def test_async_reads_match_sync(async_engine: Engine) -> None:
    if async_engine.name in smoke.SMOKE:
        spec = smoke.SMOKE[async_engine.name]

        async def body(conn: Any) -> list[dict[str, Any]]:
            return (await conn.execute(sql=spec.read, validate_ast=False))["rows"]

        rows = run(_with_connector(async_engine, body))
        sync = async_engine.make_connector()
        sync.connect()
        try:
            want = sync.execute(sql=spec.read, validate_ast=False)["rows"]
        finally:
            sync.close()
        assert sorted(map(str, rows)) == sorted(map(str, want))
        return

    chosen = [
        c
        for c in cs.CASES
        if c.id
        in {
            "select-projection",
            "filter-gt",
            "filter-in",
            "filter-is-null",
            "join-inner",
            "join-left",
            "group-by-count-sum",
            "order-desc-limit-offset",
            "cte",
            "binding-eq-drop-table",
        }
        and not set(c.requires) & set(async_engine.unsupported)
    ]
    assert chosen

    async def body_sql(conn: Any) -> dict[str, list[dict[str, Any]]]:
        out = {}
        for case in chosen:
            out[case.id] = (await conn.execute(spec=case.spec))["rows"]
        return out

    results = run(_with_connector(async_engine, body_sql))
    for case in chosen:
        got = cs.norm_rows(results[case.id])
        want = cs.norm_rows(case.expected)
        if not case.ordered:
            got, want = (sorted(map(str, x)) for x in (got, want))
        assert got == want, case.id


def test_async_writes_are_rejected(async_engine: Engine) -> None:
    writes = (
        smoke.SMOKE[async_engine.name].writes
        if async_engine.name in smoke.SMOKE
        else ["DELETE FROM qbit_employees", "DROP TABLE qbit_employees"]
    )

    async def body(conn: Any) -> None:
        for statement in writes:  # layer 1: AST validator
            with pytest.raises(SecurityError):
                await conn.execute(sql=statement)
        for statement in writes:  # layer 2 (+ engine): must never be accepted
            try:
                await conn.execute(sql=statement, validate_ast=False)
            except Exception:  # noqa: BLE001
                continue
            pytest.fail(f"async write accepted: {statement!r}")

    run(_with_connector(async_engine, body))
    if async_engine.name in smoke.SMOKE:
        check = smoke.SMOKE[async_engine.name].check
        assert check is not None and check(async_engine) == [{"count": 3}]
    else:
        sync = async_engine.make_connector()
        sync.connect()
        try:
            res = sync.execute(
                spec={
                    "table": "qbit_employees",
                    "columns": [{"column": "id", "agg": "count", "alias": "n"}],
                    "limit": 5,
                }
            )
            assert cs.norm(res["rows"][0]["n"]) == 8
        finally:
            sync.close()
