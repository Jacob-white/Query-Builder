"""Mock tests for the remaining Pinecone / Qdrant / Milvus plan branches (no live engines)."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from query_builder.connectors import pinecone as pc
from query_builder.connectors._vector_sql import VectorQueryError
from query_builder.connectors.base import IntrospectionError
from query_builder.connectors.milvus import AsyncMilvusConnector, MilvusConnector
from query_builder.connectors.qdrant import AsyncQdrantConnector, QdrantConnector
from tests.test_live_findings_regressions_vector_ts import (
    _FakeMilvus,
    _FakePinecone,
    _FakePineconeIndex,
    _FakeQdrant,
    qdrant_models,  # noqa: F401 - pytest fixture
)

VEC_SQL = "SELECT name, COSINE_DISTANCE(v, %s) AS d FROM {table} {tail}"


def _sql(table: str, tail: str = "") -> str:
    return VEC_SQL.format(table=table, tail=tail)


# ---------------------------------------------------------------------- Pinecone


def test_pinecone_vector_search_rejects_non_distance_ordering() -> None:
    conn = pc.PineconeConnector(connection=_FakePinecone())
    with pytest.raises(VectorQueryError, match="ordered by distance"):
        conn.execute(
            sql=_sql("qbit_people", "ORDER BY name LIMIT 1"),
            params=[[1.0, 0.0]],
            validate_ast=False,
        )


def test_pinecone_distance_threshold_and_count_over_search() -> None:
    conn = pc.PineconeConnector(connection=_FakePinecone())
    near = conn.execute(
        sql=(
            "SELECT name FROM qbit_people WHERE COSINE_DISTANCE(v, %s) < 0.5 "
            "ORDER BY COSINE_DISTANCE(v, %s) LIMIT 5"
        ),
        params=[[1.0, 0.0], [1.0, 0.0]],
        validate_ast=False,
    )
    # scores 0.9 / 0.1 -> distances 0.1 / 0.9: only the first is within the threshold
    assert [r["name"] for r in near["rows"]] == ["a"]
    counted = conn.execute(
        sql="SELECT COUNT(*) FROM qbit_people WHERE COSINE_DISTANCE(v, %s) < 0.5",
        params=[[1.0, 0.0]],
        validate_ast=False,
    )
    assert counted["rows"] == [{"count": 1}]


def test_pinecone_scan_cap_and_introspection_sampling() -> None:
    class Greedy(_FakePineconeIndex):
        def list(self, **kw: Any) -> Any:
            yield SimpleNamespace(
                vectors=[SimpleNamespace(id=str(i)) for i in range(30)]
            )

    client = _FakePinecone()
    client.index = Greedy()
    with (
        patch.object(pc, "MAX_SCAN_VECTORS", 10),
        pytest.raises(VectorQueryError, match="scan exceeds"),
    ):
        pc.PineconeConnector(connection=client).execute(
            sql="SELECT name FROM qbit_people", validate_ast=False
        )
    # introspection stops listing after 20 ids and samples only those
    fetched: list[list[str]] = []

    def fetch(ids: list[str]) -> Any:
        fetched.append(ids)
        return SimpleNamespace(vectors={})

    client.index.fetch = fetch  # type: ignore[method-assign]
    snap = pc.PineconeConnector(connection=client).introspect_schema()
    assert len(fetched[0]) == 20
    assert [c["name"] for c in snap["tables"]["qbit-people"]["columns"]] == [
        "id",
        "vector",
    ]

    # an empty index is not fetched at all
    class Empty(_FakePineconeIndex):
        def list(self, **kw: Any) -> Any:
            yield SimpleNamespace(vectors=[])

    client.index = Empty()
    client.index.fetch = lambda ids: pytest.fail("must not fetch an empty index")  # type: ignore[method-assign]
    assert (
        "qbit-people"
        in pc.PineconeConnector(connection=client).introspect_schema()["tables"]
    )


def test_pinecone_introspection_failures_are_wrapped() -> None:
    client = _FakePinecone()
    client.list_indexes = MagicMock(side_effect=RuntimeError("401"))  # type: ignore[method-assign]
    with pytest.raises(IntrospectionError, match="401"):
        pc.PineconeConnector(connection=client).introspect_schema()

    async def body() -> None:
        class AClient(_FakePinecone):
            async def list_indexes(self) -> Any:  # type: ignore[override]
                raise RuntimeError("403")

        AClient.__module__ = "pinecone.pinecone_asyncio"
        with pytest.raises(IntrospectionError, match="403"):
            await pc.AsyncPineconeConnector(connection=AClient()).introspect_schema()

    asyncio.run(body())


def test_async_pinecone_test_connection_variants() -> None:
    async def body() -> None:
        class Idx(_FakePineconeIndex):
            def describe_index_stats(self) -> dict[str, int]:  # sync: not awaited
                return {"n": 1}

        Idx.__module__ = "pinecone.db_data.index"
        info = await pc.AsyncPineconeConnector(connection=Idx()).test_connection()
        assert info["status"] == "healthy"
        plain = MagicMock(spec=[])  # neither control plane nor index
        assert (await pc.AsyncPineconeConnector(connection=plain).test_connection())[
            "engine_version"
        ] == "Pinecone"

    asyncio.run(body())


# ----------------------------------------------------------------------- Qdrant


def test_qdrant_threshold_count_over_search_and_version(qdrant_models: Any) -> None:  # noqa: F811
    client = _FakeQdrant()
    conn = QdrantConnector(connection=client)
    near = conn.execute(
        sql="SELECT name FROM people WHERE COSINE_DISTANCE(v, %s) < 0.1 ORDER BY COSINE_DISTANCE(v, %s)",
        params=[[1.0, 0.0], [1.0, 0.0]],
        validate_ast=False,
    )
    # scores 0.99 / 0.2 -> distances 0.01 / 0.8
    assert [r["name"] for r in near["rows"]] == ["a"]
    counted = conn.execute(
        sql="SELECT COUNT(*) FROM people WHERE COSINE_DISTANCE(v, %s) < 0.1",
        params=[[1.0, 0.0]],
        validate_ast=False,
    )
    assert counted["rows"] == [{"count": 1}]

    client.http = SimpleNamespace(
        service_api=SimpleNamespace(root=lambda: SimpleNamespace(version="1.12.0"))
    )
    assert QdrantConnector(connection=client).test_connection()["engine_version"] == (
        "Qdrant 1.12.0"
    )
    assert (
        QdrantConnector(connection=_FakeQdrant()).test_connection()["engine_version"]
        == "Qdrant"
    )
    from query_builder.connectors import qdrant as q

    assert q._server_version(SimpleNamespace(version=None)) == "Qdrant"


def test_async_qdrant_introspection_failure_is_wrapped() -> None:
    class Broken(_FakeQdrant):
        async def get_collections(self) -> Any:  # type: ignore[override]
            raise RuntimeError("unauthorized")

    Broken.__module__ = "qdrant_client.async_qdrant_client"

    with pytest.raises(IntrospectionError, match="unauthorized"):
        asyncio.run(AsyncQdrantConnector(connection=Broken()).introspect_schema())


# ----------------------------------------------------------------------- Milvus


def test_milvus_search_guards_thresholds_and_count() -> None:
    conn = MilvusConnector(connection=_FakeMilvus())
    with pytest.raises(VectorQueryError, match="ordered by distance"):
        conn.execute(
            sql=_sql("people", "ORDER BY name LIMIT 1"),
            params=[[1.0, 0.0]],
            validate_ast=False,
        )
    near = conn.execute(
        sql=(
            "SELECT name FROM people WHERE COSINE_DISTANCE(v, %s) < 0.001 "
            "ORDER BY COSINE_DISTANCE(v, %s)"
        ),
        params=[[1.0, 0.0], [1.0, 0.0]],
        validate_ast=False,
    )
    assert near["rows"] == []  # distance 0.01 is outside the 0.001 threshold
    counted = conn.execute(
        sql="SELECT COUNT(*) FROM people WHERE COSINE_DISTANCE(v, %s) < 0.5",
        params=[[1.0, 0.0]],
        validate_ast=False,
    )
    assert counted["rows"] == [{"count": 1}]


def test_milvus_requires_an_index_and_selecting_the_primary_key() -> None:
    class NoIndex(_FakeMilvus):
        def list_indexes(self, **kw: Any) -> list[str]:
            return []

    NoIndex.__module__ = "pymilvus.milvus_client"
    with pytest.raises(VectorQueryError, match="no index on vector"):
        MilvusConnector(connection=NoIndex()).execute(
            sql=_sql("people", "LIMIT 1"), params=[[1.0, 0.0]], validate_ast=False
        )
    client = _FakeMilvus()
    res = MilvusConnector(connection=client).execute(
        sql="SELECT id FROM people", validate_ast=False
    )
    assert [r["id"] for r in res["rows"]] == [2, 1]
    query = next(c for n, c in client.calls if n == "query")
    assert query["output_fields"] == ["id"]  # pk requested once, not duplicated


def test_milvus_introspection_failures_are_wrapped() -> None:
    class Broken(_FakeMilvus):
        def list_collections(self) -> list[str]:
            raise RuntimeError("rpc error")

    Broken.__module__ = "pymilvus.milvus_client"
    with pytest.raises(IntrospectionError, match="rpc error"):
        MilvusConnector(connection=Broken()).introspect_schema()

    class ABroken(_FakeMilvus):
        async def list_collections(self) -> list[str]:  # type: ignore[override]
            raise RuntimeError("rpc async")

    ABroken.__module__ = "pymilvus.milvus_client"
    with pytest.raises(IntrospectionError, match="rpc async"):
        asyncio.run(AsyncMilvusConnector(connection=ABroken()).introspect_schema())


def test_async_milvus_connect_falls_back_to_sync_client_class() -> None:
    driver = SimpleNamespace(MilvusClient=MagicMock(return_value="client"))
    with patch.dict(sys.modules, {"pymilvus": driver}):
        got = asyncio.run(
            AsyncMilvusConnector(uri="http://m:19530", token="t", db_name="d").connect()
        )
    assert got == "client"
    driver.MilvusClient.assert_called_once_with(
        uri="http://m:19530", token="t", db_name="d"
    )
