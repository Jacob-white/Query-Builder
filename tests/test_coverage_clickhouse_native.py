"""Mock tests for ClickHouse native adapter helpers and the asynch connection paths."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

from query_builder.connectors import clickhouse_native as chn


def test_detached_cursor_delegates_to_adapter() -> None:
    adapter = MagicMock()
    adapter.description = [("a",)]
    adapter.fetchall.return_value = [[1]]
    adapter.fetchone.return_value = [1]
    cur = chn._DetachedCursor(adapter)
    assert cur.description == [("a",)]
    cur.execute("SELECT 1", [2])
    adapter.execute.assert_called_once_with("SELECT 1", [2])
    assert cur.fetchall() == [[1]] and cur.fetchone() == [1]
    cur.close()
    adapter.close.assert_called_once()
    assert not hasattr(cur, "target")  # deliberately detached from the raw client


class _AsynchCursor:
    def __init__(self, description: Any, rows: list[Any]) -> None:
        self.description = description
        self._rows = rows
        self.executed: list[tuple[str, Any]] = []

    async def __aenter__(self) -> _AsynchCursor:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql, params))

    async def fetchall(self) -> list[Any]:
        return self._rows


class _AsynchConn:
    def __init__(self, cursor: _AsynchCursor) -> None:
        self._cursor = cursor

    async def connect(self) -> None:
        return None

    def cursor(self) -> _AsynchCursor:
        return self._cursor


def test_asynch_connection_detection_and_query_binding() -> None:
    cur = _AsynchCursor([("n",), ("s",)], [(1, "a")])
    conn = _AsynchConn(cur)
    assert chn._is_asynch_connection(conn)
    assert not chn._is_asynch_connection(MagicMock())
    cols, rows = asyncio.run(
        chn._asynch_query(conn, "SELECT n, s FROM t WHERE a = %s;", [5])
    )
    assert (cols, rows) == (["n", "s"], [(1, "a")])
    assert cur.executed == [("SELECT n, s FROM t WHERE a = %(p0)s", {"p0": 5})]
    empty = _AsynchCursor(None, None)  # type: ignore[arg-type]
    assert asyncio.run(chn._asynch_query(_AsynchConn(empty), "SELECT 1", None)) == (
        [],
        [],
    )


def test_bind_positional_keeps_literal_percent_and_dict_params() -> None:
    assert chn._bind_positional("SELECT 1", None) == ("SELECT 1", None)
    assert chn._bind_positional("a LIKE '50%%' AND b = %s", [1]) == (
        "a LIKE '50%%' AND b = %(p0)s",
        {"p0": 1},
    )
    d = {"x": 1}
    assert chn._bind_positional("SELECT %(x)s", d) == ("SELECT %(x)s", d)


def test_async_test_connection_reads_version_from_asynch() -> None:
    cur = _AsynchCursor([("v",)], [("24.3.1",)])
    connector = chn.AsyncClickHouseNativeConnector(
        connection=_AsynchConn(cur), database="d"
    )
    info = asyncio.run(connector.test_connection())
    assert (
        info["engine_version"] == "ClickHouse Native 24.3.1" and info["database"] == "d"
    )
    assert ("SELECT version()", None) in cur.executed

    # a failing version probe is swallowed: the health check still succeeds
    class Failing(_AsynchCursor):
        async def execute(self, sql: str, params: Any = None) -> None:
            if "version" in sql:
                raise RuntimeError("denied")
            await super().execute(sql, params)

    failing = chn.AsyncClickHouseNativeConnector(
        connection=_AsynchConn(Failing([("1",)], [(1,)]))
    )
    info2 = asyncio.run(failing.test_connection())
    assert info2["status"] == "healthy" and "ClickHouse Native" not in str(
        info2.get("engine_version", "")
    )


def test_sync_introspection_detaches_real_client_adapters() -> None:
    class RawClient:  # not a Mock: execute() returns rows, no fetchall()
        def execute(self, sql: str, *a: Any, **k: Any) -> list[Any]:
            return []

    connector = chn.ClickHouseNativeConnector(connection=RawClient(), database="d")
    seen: dict[str, Any] = {}

    def fake_introspect(
        cur: Any, database: str, filter_sensitive: bool
    ) -> dict[str, Any]:
        seen.update(cur=cur, database=database, fs=filter_sensitive)
        return {"tables": {}}

    with patch.object(chn, "introspect_clickhouse_native", fake_introspect):
        assert connector.introspect_schema(filter_sensitive=False) == {"tables": {}}
    assert isinstance(seen["cur"], chn._DetachedCursor)
    assert seen["database"] == "d" and seen["fs"] is False
