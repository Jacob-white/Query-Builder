"""Mock tests for the Weaviate connector: filters, named vectors, async paths, failures."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from query_builder.connectors import weaviate as wv
from query_builder.connectors._vector_sql import Cond
from query_builder.connectors.base import (
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from tests.test_live_findings_regressions_vector_ts import (
    _filter_modules,
    _weaviate_fake,
)


def _real_shell(**overrides: Any) -> Any:
    shell, client, coll = _weaviate_fake()
    shell.__dict__.update(client.__dict__)
    shell.__dict__.update(overrides)
    return shell, coll


def test_weaviate_filter_translates_every_operator() -> None:
    assert wv._weaviate_filter([]) is None
    conds = [
        Cond("a", "=", 1),
        Cond("b", "!=", 2),
        Cond("c", ">", 3),
        Cond("d", ">=", 4),
        Cond("e", "<", 5),
        Cond("f", "<=", 6),
        Cond("g", "in", (7, 8)),
        Cond("h", "not_in", [9, 10]),
        Cond("i", "is_null"),
        Cond("j", "is_not_null"),
    ]
    with patch.dict(sys.modules, _filter_modules()):
        kind, parts = wv._weaviate_filter(conds)
        assert kind == "all"
        assert parts == [
            ("a", "equal", (1,)),
            ("b", "not_equal", (2,)),
            ("c", "greater_than", (3,)),
            ("d", "greater_or_equal", (4,)),
            ("e", "less_than", (5,)),
            ("f", "less_or_equal", (6,)),
            ("g", "contains_any", ([7, 8],)),
            ("h", "not_equal", (9,)),  # NOT IN expands to AND-ed inequalities
            ("h", "not_equal", (10,)),
            ("i", "is_none", (True,)),
            ("j", "is_none", (False,)),
        ]
        assert wv._weaviate_filter([Cond("a", "=", 1)]) == ("a", "equal", (1,))


def test_vector_config_and_metric_from_named_vectors() -> None:
    legacy = SimpleNamespace(
        vector_index_config=SimpleNamespace(distance_metric=SimpleNamespace(value="dot"))
    )
    assert wv._metric_of(legacy) == "dot"
    named = SimpleNamespace(
        vector_index_config=None,
        vector_config={
            "title": SimpleNamespace(
                vector_index_config=SimpleNamespace(distance_metric="l2-squared")
            )
        },
    )
    assert wv._metric_of(named) == "l2-squared"
    assert wv._vector_config(SimpleNamespace(vector_index_config=None, vector_config={})) is None
    assert wv._metric_of(SimpleNamespace()) == "cosine"


def test_introspection_plan_without_vectors_or_samples() -> None:
    cfg = SimpleNamespace(
        properties=[SimpleNamespace(name="user_id", data_type="uuid")],
        vector_index_config=None,
    )
    empty = SimpleNamespace(objects=[])
    coll = SimpleNamespace(
        config=SimpleNamespace(get=lambda: cfg),
        query=SimpleNamespace(fetch_objects=lambda **kw: empty),
    )
    client = SimpleNamespace(
        collections=SimpleNamespace(list_all=lambda: ["T"], get=lambda name: coll)
    )
    raw = wv.drive_sync(wv.weaviate_introspect_plan(), client)
    table = raw["tables"]["T"]
    assert table["has_user_id"] is True and table["user_col"] == "user_id"
    vec_col = next(c for c in table["columns"] if c["name"] == "vector")
    assert vec_col["comment"] == "distance=cosine"  # no sample, so no dimension
    # a sample whose vector is not a named-vector dict gives no dimension either
    odd = SimpleNamespace(objects=[SimpleNamespace(vector=[1.0, 2.0])])
    coll.query.fetch_objects = lambda **kw: odd
    raw2 = wv.drive_sync(wv.weaviate_introspect_plan(), client)
    assert "dimension" not in raw2["tables"]["T"]["columns"][1]["comment"]


def test_server_version_formats() -> None:
    assert wv._server_version({"version": "1.2"}) == "Weaviate 1.2"
    assert wv._server_version({}) == "Weaviate"
    assert wv._server_version("junk") == "Weaviate"


def test_sync_test_connection_variants() -> None:
    not_ready, _ = _real_shell(is_ready=lambda: False)
    with pytest.raises(ConnectionFailedError, match="not ready"):
        wv.WeaviateConnector(connection=not_ready).test_connection()
    # no is_ready: fall back to listing collections
    shell, _ = _real_shell()
    del shell.__dict__["is_ready"]
    listed = MagicMock(return_value={})
    shell.collections = SimpleNamespace(list_all=listed)
    info = wv.WeaviateConnector(connection=shell).test_connection()
    listed.assert_called()
    assert info["status"] == "healthy" and info["engine_version"] == "Weaviate 1.28.2"
    # version lookup failing keeps the plain name
    broken, _ = _real_shell(get_meta=MagicMock(side_effect=RuntimeError("x")))
    assert (
        wv.WeaviateConnector(connection=broken).test_connection()["engine_version"]
        == "Weaviate"
    )


def test_sync_introspection_failure_is_wrapped() -> None:
    shell, _ = _real_shell(
        collections=SimpleNamespace(
            list_all=MagicMock(side_effect=RuntimeError("grpc down"))
        )
    )
    with pytest.raises(IntrospectionError, match="grpc down"):
        wv.WeaviateConnector(connection=shell).introspect_schema()


# ----------------------------------------------------------------------- async


def _async_client(ready: Any = True) -> tuple[Any, Any]:
    shell, coll = _real_shell()

    async def is_ready() -> Any:
        return ready

    async def get_meta() -> dict[str, str]:
        return {"version": "1.30.0"}

    shell.is_ready = is_ready
    shell.get_meta = get_meta
    return shell, coll


def test_async_connect_driver_variants() -> None:
    conn = wv.AsyncWeaviateConnector(url="http://wv:8081", api_key=None)
    assert asyncio.run(wv.AsyncWeaviateConnector(connection="x").connect()) == "x"
    with patch.dict(sys.modules, {"weaviate": None, "weaviate.client": None}):
        with pytest.raises(DriverNotInstalledError):
            asyncio.run(conn.connect())

    class AsyncDriver:
        def __init__(self) -> None:
            self.connected = False

        def use_async_with_custom(self, **kw: Any) -> Any:
            outer = self

            class C:
                async def connect(self) -> None:
                    outer.connected = True

            self.kwargs = kw
            return C()

    drv = AsyncDriver()
    with patch.dict(sys.modules, {"weaviate": drv}):
        got = asyncio.run(wv.AsyncWeaviateConnector(url="http://wv:8081").connect())
    assert drv.connected and drv.kwargs["http_host"] == "wv" and drv.kwargs["http_port"] == 8081
    assert got is not None

    sync_only = SimpleNamespace(connect_to_custom=MagicMock(return_value="sync-client"))
    with patch.dict(sys.modules, {"weaviate": sync_only}):
        assert asyncio.run(wv.AsyncWeaviateConnector().connect()) == "sync-client"
    legacy = SimpleNamespace(Client=MagicMock(return_value="legacy"))
    with patch.dict(sys.modules, {"weaviate": legacy}):
        assert asyncio.run(wv.AsyncWeaviateConnector(timeout=3).connect()) == "legacy"
        legacy.Client.assert_called_once_with(url="http://localhost:8080", timeout=3)
    bare = SimpleNamespace()
    with patch.dict(sys.modules, {"weaviate": bare}):
        assert asyncio.run(wv.AsyncWeaviateConnector().connect()) is bare
    boom = SimpleNamespace(connect_to_custom=MagicMock(side_effect=RuntimeError("no")))
    with patch.dict(sys.modules, {"weaviate": boom}), pytest.raises(ConnectionFailedError):
        asyncio.run(wv.AsyncWeaviateConnector().connect())


def test_async_execute_raw_real_client_and_cursor_fallback() -> None:
    shell, coll = _async_client()
    connector = wv.AsyncWeaviateConnector(connection=shell)
    with patch.dict(sys.modules, _filter_modules()):
        names, rows, ms = asyncio.run(
            connector.execute_raw("SELECT name, age FROM Qbit_people WHERE age > %s", [20])
        )
    assert names == ["name", "age"]
    assert rows == [{"name": "a", "age": 30}, {"name": "b", "age": 45}]
    assert ms >= 0
    # a DB-API style connection goes through its own cursor
    cur = MagicMock()
    cur.description = [("x",)]
    cur.fetchall.return_value = [(1,)]
    dbapi = MagicMock()
    dbapi.cursor.return_value = cur
    got = asyncio.run(wv.AsyncWeaviateConnector(connection=dbapi).execute_raw("Q", [1]))
    assert got[:2] == (["x"], [{"x": 1}])
    cur.execute.assert_called_once_with("Q", [1])
    cur.close.assert_called_once()
    cur.execute.reset_mock()
    asyncio.run(wv.AsyncWeaviateConnector(connection=dbapi).execute_raw("Q"))
    cur.execute.assert_called_once_with("Q")
    # a bare non-weaviate client is wrapped in the cursor adapter
    adapter_target = MagicMock(spec=["execute"])
    adapter_target.execute.return_value = None
    names, rows, _ = asyncio.run(
        wv.AsyncWeaviateConnector(connection=adapter_target).execute_raw("Q")
    )
    assert names == [] and rows == []


def test_async_test_connection_readiness_and_version() -> None:
    shell, _ = _async_client()
    info = asyncio.run(wv.AsyncWeaviateConnector(connection=shell).test_connection())
    assert info["engine_version"] == "Weaviate 1.30.0" and info["status"] == "healthy"
    not_ready, _ = _async_client(ready=False)
    with pytest.raises(ConnectionFailedError, match="not ready"):
        asyncio.run(wv.AsyncWeaviateConnector(connection=not_ready).test_connection())
    sync_ready, _ = _real_shell(get_meta=MagicMock(side_effect=RuntimeError("x")))
    info2 = asyncio.run(wv.AsyncWeaviateConnector(connection=sync_ready).test_connection())
    assert info2["engine_version"] == "Weaviate"
    plain = MagicMock(spec=[])
    info3 = asyncio.run(wv.AsyncWeaviateConnector(connection=plain).test_connection())
    assert info3["engine_version"] == "Weaviate"


def test_async_introspect_real_client_and_errors() -> None:
    shell, _ = _async_client()
    snap = asyncio.run(wv.AsyncWeaviateConnector(connection=shell).introspect_schema())
    assert "Qbit_people" in snap["tables"]
    bad, _ = _real_shell(
        collections=SimpleNamespace(list_all=MagicMock(side_effect=RuntimeError("down")))
    )
    with pytest.raises(IntrospectionError, match="down"):
        asyncio.run(wv.AsyncWeaviateConnector(connection=bad).introspect_schema())
    # DB-API style connection uses introspect_weaviate on its cursor
    cur = MagicMock()
    dbapi = MagicMock()
    dbapi.cursor.return_value = cur
    with patch.object(wv, "introspect_weaviate", return_value={"tables": {}}) as intro:
        out = asyncio.run(
            wv.AsyncWeaviateConnector(connection=dbapi).introspect_schema(
                filter_sensitive=False
            )
        )
    assert out == {"tables": {}}
    intro.assert_called_once_with(cur, filter_sensitive=False)
    cur.close.assert_called_once()
    with patch.object(wv, "introspect_weaviate", side_effect=RuntimeError("bad")):
        with pytest.raises(IntrospectionError, match="bad"):
            asyncio.run(wv.AsyncWeaviateConnector(connection=dbapi).introspect_schema())
