"""Mock tests for the asyncio DB-API helpers (query_builder.connectors._async_dbapi)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from query_builder.connectors import _async_dbapi as ad


def _native_class(module: str, name: str = "Connection") -> type:
    return type(name, (), {"__module__": module})


class _AsyncCursor:
    def __init__(self, description: Any, rows: list[Any]) -> None:
        self.description = description
        self._rows = rows
        self.executed: list[tuple[Any, ...]] = []

    async def __aenter__(self) -> _AsyncCursor:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql,) if params is None else (sql, params))

    async def fetchall(self) -> list[Any]:
        return self._rows


class _AsyncConn:
    __module__ = "aiomysql.connection"

    def __init__(self, cursor: _AsyncCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _AsyncCursor:
        return self._cursor


def test_is_native_async_classifies_by_class() -> None:
    assert ad.is_native_async(
        _native_class("psycopg.connection_async", "AsyncConnection")()
    )
    assert not ad.is_native_async(_native_class("psycopg.connection", "Connection")())
    assert ad.is_native_async(_native_class("aiomysql.connection")())
    assert ad.is_native_async(_native_class("asyncmy.connection")())
    assert not ad.is_native_async(MagicMock())  # a Mock is always blocking
    assert not ad.is_native_async(object())


def test_open_psycopg_async_only_for_coroutine_connect() -> None:
    seen: dict[str, Any] = {}

    class AsyncConnection:
        @staticmethod
        async def connect(**kw: Any) -> str:
            seen.update(kw)
            return "conn"

    driver = MagicMock()
    driver.AsyncConnection = AsyncConnection
    assert asyncio.run(ad.open_psycopg_async(driver, {"host": "h"})) == "conn"
    assert seen == {"autocommit": True, "host": "h"}
    # psycopg2 / mocks: sync connect -> caller falls back to the blocking path
    assert asyncio.run(ad.open_psycopg_async(MagicMock(), {})) is None
    assert asyncio.run(ad.open_psycopg_async(object(), {})) is None


def test_open_aiomysql_only_for_named_drivers() -> None:
    calls: list[dict[str, Any]] = []

    async def connect(**kw: Any) -> str:
        calls.append(kw)
        return "aconn"

    drv = type("m", (), {})()
    drv.__name__ = "aiomysql"  # type: ignore[attr-defined]
    drv.connect = connect  # type: ignore[attr-defined]
    assert asyncio.run(ad.open_aiomysql(drv, {"db": "x"})) == "aconn"
    assert calls == [{"autocommit": True, "db": "x"}]
    other = type("m", (), {})()
    other.__name__ = "pymysql"  # type: ignore[attr-defined]
    other.connect = connect  # type: ignore[attr-defined]
    assert asyncio.run(ad.open_aiomysql(other, {})) is None
    assert len(calls) == 1


def test_open_blocking_sets_autocommit_and_tolerates_failure() -> None:
    conn = MagicMock()
    got = asyncio.run(ad.open_blocking(lambda **kw: conn, host="h"))
    assert got is conn and conn.autocommit is True

    class Frozen:
        def __setattr__(self, k: str, v: Any) -> None:
            raise AttributeError(k)

    frozen = Frozen()
    assert asyncio.run(ad.open_blocking(lambda **kw: frozen)) is frozen


def test_blocking_query_params_description_and_rollback() -> None:
    conn = MagicMock()
    cur = conn.cursor.return_value
    cur.description = [("a",), ("b",)]
    cur.fetchall.return_value = [(1, 2)]
    assert ad._blocking_query(conn, "SELECT", [1]) == (["a", "b"], [(1, 2)])
    cur.execute.assert_called_once_with("SELECT", [1])
    cur.close.assert_called_once()
    cur.execute.reset_mock()
    cur.description = None
    cur.fetchall.return_value = None
    assert ad._blocking_query(conn, "SELECT 1", None) == ([], [])
    cur.execute.assert_called_once_with("SELECT 1")

    cur.execute.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        ad._blocking_query(conn, "X", None)
    conn.rollback.assert_called_once()
    # rollback itself failing, or absent, never masks the original error
    conn.rollback.side_effect = RuntimeError("rb")
    with pytest.raises(RuntimeError, match="boom"):
        ad._blocking_query(conn, "X", None)
    plain = MagicMock(spec=["cursor"])
    plain.cursor.return_value.execute.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        ad._blocking_query(plain, "X", None)


def test_run_query_blocking_and_native_paths() -> None:
    conn = MagicMock()
    conn.cursor.return_value.description = [("id",)]
    conn.cursor.return_value.fetchall.return_value = [(7,)]
    names, rows, ms = asyncio.run(ad.run_query(conn, "SELECT id"))
    assert names == ["id"] and rows == [{"id": 7}] and ms >= 0

    acur = _AsyncCursor([("id",), ("n",)], [(1, "a")])
    names, rows, _ = asyncio.run(ad.run_query(_AsyncConn(acur), "SELECT", [5]))
    assert rows == [{"id": 1, "n": "a"}]
    assert acur.executed == [("SELECT", [5])]
    acur2 = _AsyncCursor(None, [])
    names, rows, _ = asyncio.run(ad.run_query(_AsyncConn(acur2), "DELETE"))
    assert (names, rows) == ([], []) and acur2.executed == [("DELETE",)]


def test_loop_cursor_and_introspect_with_native_async() -> None:
    acur = _AsyncCursor([("t",)], [("a",), ("b",)])
    conn = _AsyncConn(acur)

    def introspect(cur: Any) -> list[Any]:
        cur.execute("SELECT t", ["p"])
        first = cur.fetchone()
        rest = cur.fetchall()
        assert cur.fetchone() is None and cur.fetchall() == []
        cur.execute("SELECT t")
        cur.close()
        assert cur.fetchall() == []
        return [first, rest, cur.description]

    out = asyncio.run(ad.introspect_with(conn, introspect))
    assert out == [("a",), [("b",)], [("t",)]]
    assert acur.executed == [("SELECT t", ["p"]), ("SELECT t",)]


def test_loop_cursor_without_description_has_no_rows() -> None:
    acur = _AsyncCursor(None, [("ignored",)])

    def introspect(cur: Any) -> list[Any]:
        cur.execute("SET x")
        return cur.fetchall()

    assert asyncio.run(ad.introspect_with(_AsyncConn(acur), introspect)) == []


def test_introspect_with_blocking_connection() -> None:
    conn = MagicMock()
    assert asyncio.run(ad.introspect_with(conn, lambda cur: cur)) is conn.cursor()
    conn.cursor.return_value.close.assert_called_once()

    # a bare cursor (no .cursor attribute) is used directly and not closed
    bare = MagicMock(spec=["execute"])
    assert asyncio.run(ad.introspect_with(bare, lambda cur: cur)) is bare

    def boom(cur: Any) -> None:
        raise ValueError("bad")

    with pytest.raises(ValueError, match="bad"):
        asyncio.run(ad.introspect_with(conn, boom))
    conn.rollback.assert_called_once()
    conn.rollback.side_effect = RuntimeError("rb")
    with pytest.raises(ValueError, match="bad"):
        asyncio.run(ad.introspect_with(conn, boom))
    nocursor = MagicMock(spec=["cursor"])
    with pytest.raises(ValueError, match="bad"):
        asyncio.run(ad.introspect_with(nocursor, boom))
