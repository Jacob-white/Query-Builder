"""
Vector-store contract (family ``vector_ts``): similarity search, filters, distance
semantics, thresholds, counts, introspection of a real collection and async parity, through
the real connector classes. The seeded collection is the standard "people" dataset with
orthogonal 4-d vectors (see ``engines_vector_ts.py``), so the expected order is exact.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tests.integration import engines as eng
from tests.integration.conftest import _live_or_skip
from tests.integration.engines_vector_ts import QUERY_VECTOR

VECTOR_ENGINES = [
    n
    for n in ("qdrant", "weaviate", "milvus", "pinecone")
    if n in eng.selected_engine_names()
]
#: engines whose collections were built with the COSINE metric by the seeder
COSINE_DISTANCE_ALICE = (
    1 - 1 / (1 + 0.1**2) ** 0.5
)  # cos distance of [1,.1,0,0] vs [1,0,0,0]

TABLE = "qbit_people"


def _params() -> list[Any]:
    return [
        pytest.param(n, id=n, marks=pytest.mark.qb_engine(n)) for n in VECTOR_ENGINES
    ]


@pytest.fixture
def vengine(request: Any) -> eng.Engine:
    return _live_or_skip(request.param).engine


@pytest.fixture
def vconn(vengine: eng.Engine) -> Any:
    connector = vengine.make_connector()
    connector.connect()
    try:
        yield connector
    finally:
        connector.close()


def _search(extra: dict[str, Any] | None = None, **vs: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "table": TABLE,
        "columns": ["name", "age"],
        "vector_search": {
            "vector": QUERY_VECTOR,
            "column": "vector",
            "top_k": 3,
            **vs,
        },
    }
    spec.update(extra or {})
    return spec


pytestmark = [pytest.mark.parametrize("vengine", _params(), indirect=True)]


def test_similarity_search_orders_by_distance(vengine: eng.Engine, vconn: Any) -> None:
    res = vconn.execute(spec=_search())
    assert [r["name"] for r in res["rows"]] == ["alice", "bob", "carol"], res["rows"]
    distances = [r["_distance"] for r in res["rows"]]
    assert distances == sorted(distances)
    assert distances[0] == pytest.approx(COSINE_DISTANCE_ALICE, abs=1e-3)
    assert distances[1] == pytest.approx(1 - 0.1 / (1 + 0.1**2) ** 0.5, abs=1e-3)
    assert res["rows"][0]["age"] == 30


def test_top_k_and_offset(vengine: eng.Engine, vconn: Any) -> None:
    res = vconn.execute(spec=_search(top_k=1))
    assert [r["name"] for r in res["rows"]] == ["alice"]
    paged = vconn.execute(spec=_search(extra={"offset": 1, "limit": 1}))
    assert [r["name"] for r in paged["rows"]] == ["bob"], paged["rows"]


def test_where_clause_filters_the_search(vengine: eng.Engine, vconn: Any) -> None:
    """Filters used to be silently dropped by every vector adapter."""
    res = vconn.execute(
        spec=_search(extra={"filters": [{"column": "age", "op": ">", "value": 29}]})
    )
    assert [r["name"] for r in res["rows"]] == ["alice", "bob"], res["rows"]
    res = vconn.execute(
        spec=_search(
            extra={"filters": [{"column": "name", "op": "=", "value": "carol"}]}
        )
    )
    assert [r["name"] for r in res["rows"]] == ["carol"]
    res = vconn.execute(
        spec=_search(
            extra={
                "filters": [{"column": "name", "op": "in", "value": ["bob", "carol"]}]
            }
        )
    )
    assert [r["name"] for r in res["rows"]] == ["bob", "carol"]
    res = vconn.execute(
        spec=_search(extra={"filters": [{"column": "age", "op": "<=", "value": 30}]})
    )
    assert [r["name"] for r in res["rows"]] == ["alice", "carol"]


def test_min_score_threshold(vengine: eng.Engine, vconn: Any) -> None:
    res = vconn.execute(spec=_search(min_score=0.5))
    assert [r["name"] for r in res["rows"]] == ["alice"], res["rows"]


def test_count_reflects_the_filter(vengine: eng.Engine, vconn: Any) -> None:
    res = vconn.execute(
        spec=_search(
            top_k=1, extra={"filters": [{"column": "age", "op": ">", "value": 29}]}
        )
    )
    assert res["count"] == 2, res["count"]
    plain = vconn.execute(
        spec={"table": TABLE, "columns": ["name"], "limit": 10},
    )
    assert plain["count"] == 3


def test_scan_with_filter_and_order(vengine: eng.Engine, vconn: Any) -> None:
    res = vconn.execute(
        spec={
            "table": TABLE,
            "columns": ["name", "age"],
            "filters": [{"column": "age", "op": ">=", "value": 30}],
            "order_by": [{"column": "age", "direction": "desc"}],
            "limit": 10,
        }
    )
    assert [(r["name"], r["age"]) for r in res["rows"]] == [("bob", 45), ("alice", 30)]


def test_introspection_describes_the_real_collection(
    vengine: eng.Engine, vconn: Any
) -> None:
    tables = {
        k.lower().replace("-", "_"): v
        for k, v in vconn.introspect_schema()["tables"].items()
    }
    table = tables[TABLE]
    cols = {c["name"]: c for c in table["columns"]}
    assert {"id", "vector", "name", "age"} <= set(cols), sorted(cols)
    assert not {"user_id", "text"} & set(cols), "invented columns"
    assert cols["vector"]["data_type"] == "vector"
    assert "4" in (cols["vector"]["comment"] or "")  # the dimension is reported
    assert cols["age"]["data_type"] in ("integer", "int", "int64", "number", "float")
    assert cols["name"]["data_type"] in ("string", "text", "varchar")


def test_metric_mismatch_is_an_error_not_wrong_data(
    vengine: eng.Engine, vconn: Any
) -> None:
    with pytest.raises(Exception, match="(?i)cosine|metric|distance"):
        vconn.execute(spec=_search(metric="euclidean"))


def test_unknown_collection_is_an_error(vengine: eng.Engine, vconn: Any) -> None:
    with pytest.raises(Exception, match="(?i)not exist|not found|unknown|no such"):
        vconn.execute(spec={"table": "qbit_nope", "columns": ["name"], "limit": 1})


def test_async_search_matches_sync(vengine: eng.Engine, vconn: Any) -> None:
    if not vengine.async_connector:
        pytest.skip(f"{vengine.name}: no async connector class")
    sync_rows = vconn.execute(
        spec=_search(extra={"filters": [{"column": "age", "op": ">", "value": 29}]})
    )["rows"]

    async def body() -> list[dict[str, Any]]:
        conn = vengine.make_async_connector()
        try:
            await conn.connect()
            res = await conn.execute(
                spec=_search(
                    extra={"filters": [{"column": "age", "op": ">", "value": 29}]}
                )
            )
            return res["rows"]
        finally:
            closer = conn.close()
            if asyncio.iscoroutine(closer):
                await closer

    got = asyncio.run(body())
    assert [r["name"] for r in got] == [r["name"] for r in sync_rows]
    for a, b in zip(got, sync_rows, strict=True):
        assert a["_distance"] == pytest.approx(b["_distance"], abs=1e-6)
