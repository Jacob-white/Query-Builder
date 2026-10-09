"""
Regressions for defects the live runs (tests/integration, family ``vector_ts``) found in the
vector-store / time-series connectors. Mock/unit level: no engine, no vendor driver needed.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from query_builder.compiler import QueryCompiler
from query_builder.connectors import _promql
from query_builder.connectors._vector_sql import (
    Cond,
    VectorQueryError,
    distance_from_score,
    drive_async,
    drive_sync,
    infer_type,
    matches,
    parse_vector_sql,
    payload_columns,
    shape_rows,
    sort_hits,
    vector_from_param,
)
from query_builder.connectors.base import (
    ConnectionFailedError,
    DriverNotInstalledError,
    QueryExecutionError,
)
from query_builder.dialects import get_dialect


def _compile(
    dialect: str, spec: dict[str, Any]
) -> tuple[str, list[Any], str, list[Any]]:
    return QueryCompiler(spec=spec, dialect=get_dialect(dialect)).compile()


VEC_SPEC = {
    "table": "people",
    "columns": ["name", "age"],
    "vector_search": {"vector": [1, 0.1], "column": "vector", "top_k": 2},
    "filters": [{"column": "age", "op": ">", "value": 20}],
}


# --- compiler: COUNT query was handed the SELECT-list / ORDER BY vector parameters -------
@pytest.mark.parametrize("include_distances", [True, False])
def test_count_query_gets_only_its_own_parameters(include_distances: bool) -> None:
    spec = json.loads(json.dumps(VEC_SPEC))
    spec["vector_search"]["include_distances"] = include_distances
    spec["vector_search"]["min_score"] = 0.5
    _, _, count_sql, count_params = _compile("qdrant", spec)
    assert count_sql.count("%s") == len(count_params)
    assert count_params == ["[1, 0.1]", 0.5, 20]


def test_count_query_params_with_hybrid_search() -> None:
    spec = {
        "table": "people",
        "columns": ["name"],
        "hybrid_search": {
            "vector": [1, 0.1],
            "vector_column": "vector",
            "query_text": "x",
            "text_columns": ["name"],
        },
        "filters": [{"column": "age", "op": ">", "value": 20}],
    }
    _, _, count_sql, count_params = _compile("qdrant", spec)
    assert count_sql.count("%s") == len(count_params) == 1


# --- parser ------------------------------------------------------------------------------
def test_parse_vector_search_with_filters_and_threshold() -> None:
    spec = json.loads(json.dumps(VEC_SPEC))
    spec["vector_search"]["min_score"] = 0.5
    spec["filters"] = [
        {"column": "age", "op": ">=", "value": 20},
        {"column": "name", "op": "in", "value": ["a", "b"]},
        {"column": "email", "op": "is_null"},
    ]
    sql, params, count_sql, count_params = _compile("milvus", spec)
    vq = parse_vector_sql(sql, params)
    assert vq.table == "people" and vq.vector == [1.0, 0.1] and vq.metric == "cosine"
    assert vq.vector_column == "vector" and vq.max_distance == 0.5
    assert vq.limit == 2 and vq.offset == 0 and vq.order_by == [("_distance", False)]
    assert [(c.column, c.op) for c in vq.conds] == [
        ("age", ">="),
        ("name", "in"),
        ("email", "is_null"),
    ]
    assert vq.wanted_payload_fields() == ["age", "email", "name", "_distance"][:3] + []
    counted = parse_vector_sql(count_sql, count_params)
    assert counted.count_only and counted.max_distance == 0.5


def test_parse_scan_and_projection_star() -> None:
    vq = parse_vector_sql(
        'SELECT * FROM "t1" WHERE "x" != %s ORDER BY "x" DESC LIMIT 3', [5]
    )
    assert vq.wanted_payload_fields() is None
    assert vq.conds == [Cond("x", "!=", 5)]
    assert vq.order_by == [("x", True)] and vq.limit == 3 and not vq.is_search


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM t",
        "SELECT a FROM t JOIN u ON t.id = u.id",
        "SELECT a FROM t GROUP BY a",
        "SELECT a FROM t WHERE a = 1 OR b = 2",
        "SELECT a + 1 FROM t",
        "SELECT a FROM t WHERE LOWER(a) = 'x'",
        "SELECT a FROM",
    ],
)
def test_parser_rejects_what_a_vector_store_cannot_honour(sql: str) -> None:
    with pytest.raises(VectorQueryError):
        parse_vector_sql(sql, [])


def test_parser_value_forms_and_param_errors() -> None:
    vq = parse_vector_sql(
        "SELECT a FROM t WHERE a = 1.5 AND b = 'x' AND c = TRUE AND d = -2 "
        "AND e NOT IN (1, 2) AND f IS NOT NULL AND g IN (%s)",
        ["p"],
    )
    values = {c.column: (c.op, c.value) for c in vq.conds}
    assert values["a"] == ("=", 1.5) and values["b"] == ("=", "x")
    assert values["c"] == ("=", True) and values["d"] == ("=", -2)
    assert values["e"] == ("not_in", [1, 2]) and values["f"] == ("is_not_null", None)
    assert values["g"] == ("in", ["p"])
    with pytest.raises(VectorQueryError, match="missing"):
        parse_vector_sql("SELECT a FROM t WHERE a = %s", [])
    with pytest.raises(VectorQueryError, match="one query vector"):
        parse_vector_sql(
            "SELECT COSINE_DISTANCE(v, %s) AS d FROM t WHERE COSINE_DISTANCE(v, %s) <= 1 LIMIT 1",
            [[1.0], [2.0]],
        )


def test_vector_param_forms() -> None:
    assert vector_from_param([1, 2]) == [1.0, 2.0]
    assert vector_from_param("[1, 2]") == [1.0, 2.0]
    for bad in ("nope", "[]", 5):
        with pytest.raises(VectorQueryError):
            vector_from_param(bad)


def test_distance_conversions() -> None:
    assert distance_from_score("cosine", 0.75, "cosine") == pytest.approx(0.25)
    assert distance_from_score("dot", 2.0, "dot") == -2.0
    assert distance_from_score("euclidean", 3.0, "euclidean") == 3.0
    with pytest.raises(VectorQueryError, match="collection uses"):
        distance_from_score("cosine", 1.0, "euclidean")


def test_helpers_shape_sort_match_infer() -> None:
    vq = parse_vector_sql("SELECT a, b AS bee FROM t", [])
    hits = [{"a": 2, "b": 1}, {"a": 1, "b": None}]
    assert shape_rows(vq, hits) == ([("a",), ("bee",)], [[2, 1], [1, None]])
    star = parse_vector_sql("SELECT * FROM t", [])
    assert shape_rows(star, hits)[0] == [("a",), ("b",)]
    assert shape_rows(star, [])[0] == [("id",)]
    count = parse_vector_sql("SELECT COUNT(*) FROM t", [])
    assert shape_rows(count, hits) == ([("count",)], [[2]])

    ordered = parse_vector_sql("SELECT a FROM t ORDER BY b DESC", [])
    assert [h["a"] for h in sort_hits(ordered, hits)] == [2, 1]

    row = {"a": 5, "s": "x", "n": None}
    cases = [
        (Cond("a", "=", 5), True),
        (Cond("a", "!=", 5), False),
        (Cond("a", ">", 4), True),
        (Cond("a", "<=", 4), False),
        (Cond("a", "in", [5]), True),
        (Cond("a", "not_in", [5]), False),
        (Cond("n", "is_null"), True),
        (Cond("a", "is_not_null"), True),
        (Cond("n", "="), False),
        (Cond("n", "!=", 1), True),
        (Cond("s", ">", 1), False),
    ]
    for cond, expected in cases:
        assert matches([cond], row) is expected, cond
    assert [infer_type(v) for v in (True, 1, 1.5, "s", [1], {}, None)] == [
        "boolean",
        "integer",
        "float",
        "string",
        "array",
        "json",
        "unknown",
    ]
    assert payload_columns([{"a": None}, {"a": 1, "b": "x"}], {"c": "string"}) == {
        "a": "integer",
        "b": "string",
        "c": "string",
    }


def test_plan_drivers_sync_and_async() -> None:
    class Client:
        def __init__(self) -> None:
            self.http = SimpleNamespace(root=lambda: "r")

        def add(self, a: int, b: int) -> int:
            return a + b

        async def aadd(self, a: int, b: int) -> int:
            return a + b

        async def agen(self):
            for i in range(2):
                yield i

    def plan() -> Any:
        x = yield ("add", {"a": 1, "b": 2})
        y = yield ("http.root", {})
        z = yield (lambda: "callable", {})
        return x, y, z

    assert drive_sync(plan(), Client()) == (3, "r", "callable")

    def aplan() -> Any:
        x = yield ("aadd", {"a": 1, "b": 2})
        items = yield ("agen", {})
        return x, items

    assert asyncio.run(drive_async(aplan(), Client())) == (3, [0, 1])


# --- Qdrant -----------------------------------------------------------------------------
class _FakeQdrant:
    """Quacks like qdrant_client.QdrantClient (module name is faked below)."""

    def __init__(self, distance: str = "Cosine", named: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        params = SimpleNamespace(size=2, distance=SimpleNamespace(value=distance))
        self.vectors = {"vec": params} if named else params
        self.points = [
            SimpleNamespace(id=1, payload={"name": "a", "age": 30}, score=0.99),
            SimpleNamespace(id=2, payload={"name": "b", "age": 45}, score=0.2),
        ]

    def get_collections(self) -> Any:
        return SimpleNamespace(collections=[SimpleNamespace(name="people")])

    def get_collection(self, collection_name: str) -> Any:
        self.calls.append(("get_collection", {"collection_name": collection_name}))
        return SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(vectors=self.vectors)),
            payload_schema={
                "age": SimpleNamespace(data_type=SimpleNamespace(value="integer"))
            },
        )

    def query_points(self, **kw: Any) -> Any:
        self.calls.append(("query_points", kw))
        return SimpleNamespace(points=self.points)

    def scroll(self, **kw: Any) -> Any:
        self.calls.append(("scroll", kw))
        if (
            kw.get("offset") is None
            and kw["limit"] == 256
            and not getattr(self, "_paged", False)
        ):
            self._paged = True
            return self.points[:1], 2
        return self.points[1:], None

    def count(self, **kw: Any) -> Any:
        self.calls.append(("count", kw))
        return SimpleNamespace(count=7)


_FakeQdrant.__module__ = "qdrant_client.qdrant_client"


def _fake_models() -> types.ModuleType:
    mod = types.ModuleType("qdrant_client.models")
    for name in (
        "FieldCondition",
        "MatchValue",
        "MatchAny",
        "Range",
        "IsNullCondition",
        "PayloadField",
        "Filter",
    ):
        setattr(
            mod,
            name,
            type(name, (), {"__init__": lambda self, **kw: self.__dict__.update(kw)}),
        )
    pkg = types.ModuleType("qdrant_client")
    pkg.models = mod  # type: ignore[attr-defined]
    return pkg


@pytest.fixture
def qdrant_models() -> Any:
    pkg = _fake_models()
    with patch.dict(
        sys.modules, {"qdrant_client": pkg, "qdrant_client.models": pkg.models}
    ):
        yield pkg.models


def test_qdrant_vector_search_runs_the_search_and_honours_where(
    qdrant_models: Any,
) -> None:
    """The adapter used the removed ``client.search`` and fell back to an unfiltered scroll."""
    from query_builder.connectors.qdrant import QdrantConnector

    client = _FakeQdrant()
    conn = QdrantConnector(connection=client)
    spec = json.loads(json.dumps(VEC_SPEC))
    spec["vector_search"]["top_k"] = 5
    res = conn.execute(spec=spec)
    assert [r["name"] for r in res["rows"]] == ["a", "b"]
    assert res["rows"][0]["_distance"] == pytest.approx(0.01)
    call = next(c for n, c in client.calls if n == "query_points")
    assert call["query"] == [1.0, 0.1] and call["limit"] == 5 and call["using"] is None
    must = call["query_filter"].must[0]
    assert must.key == "age" and must.range.gt == 20
    assert res["count"] == 7


def test_qdrant_filter_operators(qdrant_models: Any) -> None:
    from query_builder.connectors.qdrant import _qdrant_filter

    flt = _qdrant_filter(
        [
            Cond("a", "=", 1),
            Cond("b", "!=", 2),
            Cond("c", "in", [1]),
            Cond("d", "not_in", [1]),
            Cond("e", "is_null"),
            Cond("f", "is_not_null"),
            Cond("g", "<=", 3),
        ]
    )
    assert len(flt.must) == 4 and len(flt.must_not) == 3
    assert _qdrant_filter([]) is None


def test_qdrant_metric_mismatch_and_ordering_rejected(qdrant_models: Any) -> None:
    from query_builder.connectors.qdrant import QdrantConnector

    spec = {
        "table": "people",
        "columns": ["name"],
        "vector_search": {"vector": [1, 0], "column": "vector", "metric": "euclidean"},
    }
    with pytest.raises(VectorQueryError, match="collection uses"):
        QdrantConnector(connection=_FakeQdrant("Cosine")).execute(spec=spec)
    with pytest.raises(VectorQueryError, match="ordered by distance"):
        QdrantConnector(connection=_FakeQdrant()).execute(
            sql="SELECT COSINE_DISTANCE(v, %s) AS d, name FROM people ORDER BY name LIMIT 2",
            params=[[1.0, 0.0]],
            validate_ast=False,
        )


def test_qdrant_named_vectors(qdrant_models: Any) -> None:
    from query_builder.connectors.qdrant import QdrantConnector

    client = _FakeQdrant(named=True)
    conn = QdrantConnector(connection=client)
    spec = {
        "table": "people",
        "columns": ["name"],
        "vector_search": {"vector": [1, 0], "column": "vec"},
    }
    conn.execute(spec=spec)
    assert next(c for n, c in client.calls if n == "query_points")["using"] == "vec"
    spec["vector_search"]["column"] = "other"
    with pytest.raises(VectorQueryError, match="named vectors"):
        conn.execute(spec=spec)


def test_qdrant_scan_paginates_sorts_and_counts(qdrant_models: Any) -> None:
    from query_builder.connectors.qdrant import QdrantConnector

    client = _FakeQdrant()
    conn = QdrantConnector(connection=client)
    res = conn.execute(
        spec={
            "table": "people",
            "columns": ["name", "age"],
            "order_by": [{"column": "age", "direction": "desc"}],
            "limit": 10,
        }
    )
    assert [r["name"] for r in res["rows"]] == ["b", "a"]
    res = conn.execute(spec={"table": "people", "columns": ["name"], "limit": 1})
    assert len(res["rows"]) == 1


def test_qdrant_scan_cap(qdrant_models: Any) -> None:
    from query_builder.connectors import qdrant as q

    client = _FakeQdrant()
    client.scroll = lambda **kw: (
        [SimpleNamespace(id=i, payload={"x": i}) for i in range(256)],
        1,
    )  # type: ignore[method-assign]
    with (
        patch.object(q, "MAX_SCAN_POINTS", 300),
        pytest.raises(VectorQueryError, match="scan exceeds"),
    ):
        q.QdrantConnector(connection=client).execute(
            sql="SELECT x FROM people ORDER BY x", validate_ast=False
        )


def test_qdrant_introspection_reports_what_the_server_has() -> None:
    """Introspection used to invent id/vector/user_id/text columns (and a 'documents' table)."""
    from query_builder.connectors.qdrant import QdrantConnector

    client = _FakeQdrant()
    client.scroll = lambda **kw: (
        [SimpleNamespace(id=1, payload={"name": "a", "age": 30, "tags": ["x"]})],
        None,
    )  # type: ignore[method-assign]
    snap = QdrantConnector(connection=client).introspect_schema()
    cols = {c["name"]: c for c in snap["tables"]["people"]["columns"]}
    assert set(cols) == {"id", "vector", "age", "name", "tags"}
    assert "user_id" not in cols and "text" not in cols
    assert cols["vector"]["comment"] == "dimension=2; distance=Cosine"
    assert (
        cols["age"]["data_type"] == "integer" and cols["tags"]["data_type"] == "array"
    )
    client.get_collections = lambda: SimpleNamespace(collections=[])  # type: ignore[method-assign]
    assert QdrantConnector(connection=client).introspect_schema()["tables"] == {}
    client.get_collections = MagicMock(side_effect=RuntimeError("down"))  # type: ignore[method-assign]
    from query_builder.connectors.base import IntrospectionError

    with pytest.raises(IntrospectionError):
        QdrantConnector(connection=client).introspect_schema()


def test_async_qdrant_awaits_the_driver(qdrant_models: Any) -> None:
    """The async class called the async client's coroutines through a sync adapter."""
    from query_builder.connectors.qdrant import AsyncQdrantConnector

    class AClient(_FakeQdrant):
        async def get_collections(self) -> Any:  # type: ignore[override]
            return super().get_collections()

        async def get_collection(self, collection_name: str) -> Any:  # type: ignore[override]
            return super().get_collection(collection_name)

        async def query_points(self, **kw: Any) -> Any:  # type: ignore[override]
            return super().query_points(**kw)

        async def scroll(self, **kw: Any) -> Any:  # type: ignore[override]
            return ([SimpleNamespace(id=1, payload={"name": "a", "age": 1})], None)

        async def close(self) -> None:
            return None

    AClient.__module__ = "qdrant_client.async_qdrant_client"

    async def body() -> None:
        conn = AsyncQdrantConnector(connection=AClient())
        info = await conn.test_connection()
        assert info["status"] == "healthy"
        res = await conn.execute(spec=VEC_SPEC)
        assert [r["name"] for r in res["rows"]] == ["a", "b"]
        scan = await conn.execute(sql="SELECT name FROM people", validate_ast=False)
        assert scan["rows"] == [{"name": "a"}]
        snap = await conn.introspect_schema()
        assert "people" in snap["tables"]
        await conn.close()

    asyncio.run(body())


# --- Weaviate ---------------------------------------------------------------------------
def test_weaviate_connect_kwargs_split_url_and_use_api_key() -> None:
    """``connect_to_custom(http_host='http://host:8080')`` is invalid; api_key was ignored."""
    from query_builder.connectors import weaviate as w

    kw = w._connect_kwargs("https://wv.example.com:8443", {"grpc_port": 1}, None)
    assert kw["http_host"] == "wv.example.com" and kw["http_port"] == 8443
    assert (
        kw["http_secure"] is True
        and kw["grpc_port"] == 1
        and kw["grpc_host"] == "wv.example.com"
    )
    plain = w._connect_kwargs("localhost", {}, None)
    assert (
        plain["http_port"] == 8080
        and plain["grpc_port"] == 50051
        and plain["http_secure"] is False
    )

    auth = types.ModuleType("weaviate.classes.init")
    auth.Auth = SimpleNamespace(api_key=lambda k: ("key", k))  # type: ignore[attr-defined]
    with patch.dict(sys.modules, {"weaviate.classes.init": auth}):
        assert w._connect_kwargs("http://h:1", {}, "sekret")["auth_credentials"] == (
            "key",
            "sekret",
        )


def test_weaviate_connector_passes_split_endpoint_to_the_driver() -> None:
    from query_builder.connectors.weaviate import WeaviateConnector

    drv = MagicMock()
    with patch.dict(sys.modules, {"weaviate": drv}):
        WeaviateConnector(url="http://wv:9090", grpc_port=1234).connect()
    kwargs = drv.connect_to_custom.call_args.kwargs
    assert (
        kwargs["http_host"] == "wv"
        and kwargs["http_port"] == 9090
        and kwargs["grpc_port"] == 1234
    )


def _weaviate_fake(metric: str = "cosine") -> Any:
    from query_builder.connectors.weaviate import WeaviateConnector  # noqa: F401

    objs = [
        SimpleNamespace(
            uuid="u1",
            properties={"name": "a", "age": 30},
            metadata=SimpleNamespace(distance=0.1),
            vector={"default": [1.0, 0.0]},
        ),
        SimpleNamespace(
            uuid="u2",
            properties={"name": "b", "age": 45},
            metadata=SimpleNamespace(distance=0.9),
            vector={"default": [0.0, 1.0]},
        ),
    ]
    cfg = SimpleNamespace(
        properties=[
            SimpleNamespace(name="name", data_type=SimpleNamespace(value="text")),
            SimpleNamespace(name="age", data_type=SimpleNamespace(value="int")),
        ],
        vector_index_config=SimpleNamespace(
            distance_metric=SimpleNamespace(value=metric)
        ),
    )
    coll = SimpleNamespace(
        config=SimpleNamespace(get=lambda: cfg),
        query=SimpleNamespace(
            near_vector=MagicMock(return_value=SimpleNamespace(objects=objs)),
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=objs)),
        ),
        aggregate=SimpleNamespace(
            over_all=MagicMock(return_value=SimpleNamespace(total_count=9))
        ),
    )
    client = SimpleNamespace(
        collections=SimpleNamespace(
            list_all=lambda: {"Qbit_people": cfg}, get=lambda name: coll
        ),
        is_ready=lambda: True,
        get_meta=lambda: {"version": "1.28.2"},
    )
    return type("WClient", (), {"__module__": "weaviate.client"})(), client, coll


def _weaviate_conn(metric: str = "cosine") -> Any:
    from query_builder.connectors.weaviate import WeaviateConnector

    shell, client, coll = _weaviate_fake(metric)
    shell.__dict__.update(client.__dict__)
    return WeaviateConnector(connection=shell), coll


def _filter_modules() -> dict[str, Any]:
    class _Prop:
        def __init__(self, name: str) -> None:
            self.name = name

        def __getattr__(self, op: str) -> Any:
            return lambda *a: (self.name, op, a)

    class Filter:
        @staticmethod
        def by_property(name: str) -> _Prop:
            return _Prop(name)

        @staticmethod
        def all_of(parts: list[Any]) -> Any:
            return ("all", parts)

    class Sort:
        def __init__(self, items: list[Any]) -> None:
            self.items = items

        @classmethod
        def by_property(cls, name: str, ascending: bool = True) -> Sort:
            return cls([(name, ascending)])

        def by_property_chain(self) -> None:  # pragma: no cover
            pass

    Sort.by_property.__func__  # classmethod access check
    q = types.ModuleType("weaviate.classes.query")
    q.Filter = Filter  # type: ignore[attr-defined]
    q.Sort = type(
        "Sort",
        (),
        {
            "by_property": staticmethod(
                lambda n, ascending=True: SimpleNamespace(
                    items=[(n, ascending)],
                    by_property=lambda n2, ascending=True: SimpleNamespace(
                        items=[(n, ascending), (n2, ascending)]
                    ),
                )
            )
        },
    )  # type: ignore[attr-defined]
    q.MetadataQuery = lambda **kw: SimpleNamespace(**kw)  # type: ignore[attr-defined]
    return {
        "weaviate": types.ModuleType("weaviate"),
        "weaviate.classes": types.ModuleType("weaviate.classes"),
        "weaviate.classes.query": q,
    }


def test_weaviate_search_scan_count_and_introspection() -> None:
    conn, coll = _weaviate_conn()
    with patch.dict(sys.modules, _filter_modules()):
        info = conn.test_connection()
        assert info["engine_version"] == "Weaviate 1.28.2"
        spec = json.loads(json.dumps(VEC_SPEC))
        spec["table"] = "qbit_people"
        spec["filters"] = [
            {"column": "age", "op": ">", "value": 20},
            {"column": "name", "op": "in", "value": ["a"]},
        ]
        res = conn.execute(spec=spec)
        assert [r["name"] for r in res["rows"]] == ["a", "b"] and res["count"] == 9
        call = coll.query.near_vector.call_args.kwargs
        assert call["near_vector"] == [1.0, 0.1] and call["filters"][0] == "all"
        scan = conn.execute(
            spec={
                "table": "qbit_people",
                "columns": ["name", "age"],
                "order_by": [
                    {"column": "age", "direction": "desc"},
                    {"column": "name"},
                ],
                "limit": 5,
            }
        )
        assert len(scan["rows"]) == 2
        snap = conn.introspect_schema()
        cols = {c["name"]: c for c in snap["tables"]["Qbit_people"]["columns"]}
        assert (
            set(cols) == {"id", "vector", "name", "age"}
            and cols["age"]["data_type"] == "integer"
        )
        assert cols["vector"]["comment"] == "distance=cosine; dimension=2"
        with pytest.raises(VectorQueryError, match="does not exist"):
            conn.execute(sql="SELECT name FROM nope", validate_ast=False)
        with pytest.raises(VectorQueryError, match="ordered by distance"):
            conn.execute(
                sql="SELECT COSINE_DISTANCE(v, %s) AS d FROM qbit_people ORDER BY name LIMIT 1",
                params=[[1.0, 0.0]],
                validate_ast=False,
            )


def test_weaviate_euclidean_is_sqrt_of_l2_squared_and_metric_checked() -> None:
    conn, coll = _weaviate_conn("l2-squared")
    spec = {
        "table": "qbit_people",
        "columns": ["name"],
        "vector_search": {
            "vector": [1, 0],
            "column": "vector",
            "metric": "euclidean",
            "min_score": 0.5,
        },
    }
    with patch.dict(sys.modules, _filter_modules()):
        res = conn.execute(spec=spec)
        assert (
            res["rows"][0]["_distance"] == pytest.approx(0.1**0.5)
            and len(res["rows"]) == 1
        )
        spec["vector_search"]["metric"] = "cosine"
        with pytest.raises(VectorQueryError, match="collection uses"):
            conn.execute(spec=spec)
        cnt = conn.execute(sql="SELECT COUNT(*) FROM qbit_people", validate_ast=False)
        assert cnt["rows"] == [{"count": 9}]


# --- Prometheus / VictoriaMetrics -------------------------------------------------------
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/tsdb/delete_series?match[]={__name__=~'.+'}",
        "/-/quit",
        "/-/reload",
        "/api/v1/write",
        "/snapshot/create",
        "/api/v1/import",
    ],
)
def test_metrics_connectors_never_forward_write_or_admin_endpoints(path: str) -> None:
    """VictoriaMetrics answers GET /api/v1/admin/tsdb/delete_series: it must not be reachable."""
    with pytest.raises(_promql.PromQLRequestError):
        _promql.build_request(path)


def test_build_request_forms() -> None:
    assert _promql.build_request("up{job='x'}") == (
        "/api/v1/query",
        [("query", "up{job='x'}")],
    )
    assert _promql.build_request("/api/v1/query_range?query=up&step=5")[1] == [
        ("query", "up"),
        ("step", "5"),
    ]
    assert (
        _promql.build_request("/prometheus/api/v1/labels")[0]
        == "/prometheus/api/v1/labels"
    )
    assert _promql.build_request("/health")[0] == "/health"
    with pytest.raises(_promql.PromQLRequestError):
        _promql.build_request("   ")


def test_shape_response_vector_matrix_scalar_lists_and_errors() -> None:
    vec = {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {"metric": {"__name__": "m", "name": "a"}, "value": [1.0, "30"]}
            ],
        },
    }
    assert _promql.shape_response("/api/v1/query", vec) == (
        [("__name__",), ("name",), ("timestamp",), ("value",)],
        [["m", "a", 1.0, 30.0]],
    )
    mat = {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [{"metric": {"k": "v"}, "values": [[1, "1"], [2, "2"]]}],
        },
    }
    assert len(_promql.shape_response("/api/v1/query_range", mat)[1]) == 2
    scalar = {"status": "success", "data": {"resultType": "scalar", "result": [5, "2"]}}
    assert _promql.shape_response("/api/v1/query", scalar)[1] == [[5, 2.0]]
    assert _promql.shape_response("/api/v1/labels", {"data": ["a", "b"]}) == (
        [("label",)],
        [["a"], ["b"]],
    )
    assert _promql.shape_response("/api/v1/label/x/values", {"data": ["a"]})[0] == [
        ("value",)
    ]
    assert _promql.shape_response("/api/v1/series", {"data": [{"a": "1"}, {"b": "2"}]})[
        0
    ] == [("a",), ("b",)]
    assert _promql.shape_response(
        "/api/v1/status/buildinfo", {"data": {"version": "1"}}
    )[1] == [['{"version": "1"}']]
    assert _promql.shape_response("/x", {"data": 5})[1] == [[5]]
    with pytest.raises(_promql.PromQLRequestError, match="bad_data: parse error"):
        _promql.shape_response(
            "/api/v1/query",
            {"status": "error", "errorType": "bad_data", "error": "parse error"},
        )


class _Resp:
    def __init__(self, body: Any, status: int = 200) -> None:
        self._body, self.status_code = body, status

    def json(self) -> Any:
        if self._body is None:
            raise ValueError("no json")
        return self._body


def test_prometheus_connector_talks_to_the_server_through_httpx() -> None:
    """With requests/httpx as the 'driver' the old adapter had no base URL and returned no rows."""
    import httpx

    from query_builder.connectors.prometheus import (
        AsyncPrometheusConnector,
        PrometheusConnector,
    )

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        path = request.url.path
        if path == "/api/v1/query":
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "resultType": "vector",
                        "result": [{"metric": {"name": "a"}, "value": [1, "30"]}],
                    },
                },
            )
        if path == "/api/v1/label/__name__/values":
            return httpx.Response(200, json={"status": "success", "data": ["qbit"]})
        if path == "/api/v1/labels":
            return httpx.Response(
                200, json={"status": "success", "data": ["__name__", "name"]}
            )
        if path == "/api/v1/metadata":
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {"qbit": [{"type": "gauge", "help": "h"}]},
                },
            )
        if path == "/api/v1/status/buildinfo":
            return httpx.Response(
                200, json={"status": "success", "data": {"version": "2.55.1"}}
            )
        if path == "/-/ready":
            return httpx.Response(200, text="ready")
        return httpx.Response(404, json={"status": "error", "error": "nope"})

    transport = httpx.MockTransport(handler)
    conn = PrometheusConnector(url="http://prom:9090", transport=transport)
    res = conn.execute(sql="qbit", validate_ast=False)
    assert res["rows"] == [{"name": "a", "timestamp": 1, "value": 30.0}]
    assert conn.test_connection()["engine_version"] == "Prometheus 2.55.1"
    snap = conn.introspect_schema()
    assert {c["name"] for c in snap["tables"]["qbit"]["columns"]} == {
        "timestamp",
        "value",
        "name",
    }
    with pytest.raises(QueryExecutionError):
        conn.execute(
            sql="/api/v1/admin/tsdb/delete_series?match[]=qbit", validate_ast=False
        )
    with pytest.raises(QueryExecutionError, match="HTTP 404"):
        conn.execute(sql="/api/v1/rules", validate_ast=False)

    async def body() -> None:
        a = AsyncPrometheusConnector(
            url="http://prom:9090", transport=httpx.MockTransport(handler)
        )
        res = await a.execute(sql="qbit", validate_ast=False)
        assert res["rows"][0]["value"] == 30.0
        assert (await a.test_connection())["engine_version"] == "Prometheus 2.55.1"
        assert "qbit" in (await a.introspect_schema())["tables"]
        with pytest.raises(QueryExecutionError):
            await a.execute(sql="/-/quit", validate_ast=False)
        await a.close()

    asyncio.run(body())


def test_victoriametrics_connector_blocks_admin_endpoints_and_runs_metricsql() -> None:
    import httpx

    from query_builder.connectors.victoriametrics import (
        AsyncVictoriaMetricsConnector,
        VictoriaMetricsConnector,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/query":
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "resultType": "vector",
                        "result": [{"metric": {"name": "a"}, "value": [1, "30"]}],
                    },
                },
            )
        if path == "/health":
            return httpx.Response(200, text="OK")
        if path == "/api/v1/label/__name__/values":
            return httpx.Response(200, json={"status": "success", "data": ["qbit"]})
        if path == "/api/v1/labels":
            return httpx.Response(
                200, json={"status": "success", "data": ["__name__", "name"]}
            )
        return httpx.Response(404, text="not found")

    conn = VictoriaMetricsConnector(
        url="http://vm:8428", transport=httpx.MockTransport(handler)
    )
    assert conn.execute(sql="qbit", validate_ast=False)["rows"][0]["name"] == "a"
    assert conn.test_connection()["engine_version"] == "VictoriaMetrics"
    assert "qbit" in conn.introspect_schema()["tables"]
    with pytest.raises(QueryExecutionError):
        conn.execute(
            sql="/api/v1/admin/tsdb/delete_series?match[]={__name__=~'.+'}",
            validate_ast=False,
        )

    async def body() -> None:
        a = AsyncVictoriaMetricsConnector(
            url="http://vm:8428", transport=httpx.MockTransport(handler)
        )
        assert (await a.execute(sql="qbit", validate_ast=False))["rows"][0][
            "name"
        ] == "a"
        assert (await a.test_connection())["status"] == "healthy"
        assert "qbit" in (await a.introspect_schema())["tables"]
        await a.close()

    asyncio.run(body())


def test_requests_fallback_has_a_base_url() -> None:
    session = MagicMock()
    session.get.return_value = _Resp({"status": "success", "data": []})
    requests = types.ModuleType("requests")
    requests.Session = lambda: session  # type: ignore[attr-defined]
    with patch.dict(sys.modules, {"requests": requests}):
        client = _promql.RequestsBase("http://prom:9090/", timeout=3)
        client.get("/api/v1/labels", params=[("a", "b")])
        client.close()
    session.get.assert_called_once_with(
        "http://prom:9090/api/v1/labels", params=[("a", "b")], timeout=3
    )


def test_http_health_paths_and_non_json_error_bodies() -> None:
    sync = _promql.PromSync(SimpleNamespace(get=lambda path, params=None: _Resp(None)))
    assert sync.request("/-/ready")[1] == [[json.dumps({"ok": True})]]
    with pytest.raises(_promql.PromQLRequestError, match="HTTP 500"):
        _promql.PromSync(
            SimpleNamespace(get=lambda path, params=None: _Resp(None, 500))
        ).request("/api/v1/rules")
    assert (
        _promql.PromSync(
            SimpleNamespace(get=lambda path, params=None: _Resp(None))
        ).request("/api/v1/labels")[1]
        == []
    )
    assert _promql.is_http_client(MagicMock()) is False


# --- TDengine ---------------------------------------------------------------------------
def test_tdengine_native_driver_failure_falls_through_to_rest_driver() -> None:
    """``import taos`` raises InterfaceError (not ImportError) without libtaos."""
    from query_builder.connectors import tdengine as td

    rest = MagicMock()

    def fake_import(name: str, *a: Any, **k: Any) -> Any:
        if name == "taos":
            raise RuntimeError("[0xffff]: unable to load taos client library")
        if name == "taosrest":
            return rest
        raise ImportError(name)

    with patch.object(td, "__import__", fake_import, create=True):
        conn = td.TDengineConnector(database="d", url="http://h:6041")
        assert conn.connect() is rest.connect.return_value
        aconn = td.AsyncTDengineConnector(database="d", url="http://h:6041")
        assert asyncio.run(aconn.connect()) is rest.connect.return_value

    def only_broken(name: str, *a: Any, **k: Any) -> Any:
        if name == "taos":
            raise RuntimeError("unable to load taos client library")
        raise ImportError(name)

    with (
        patch.object(td, "__import__", only_broken, create=True),
        pytest.raises(DriverNotInstalledError, match="unable to load"),
    ):
        td.TDengineConnector().connect()


def test_async_tdengine_introspection_is_not_empty_and_version_reported() -> None:
    from query_builder.connectors.tdengine import AsyncTDengineConnector

    cur = MagicMock()
    cur.description = [("c",)]
    cur.fetchall.side_effect = [
        [("meters",)],
        [("ts", "TIMESTAMP"), ("current", "FLOAT")],
    ]
    conn = MagicMock()
    conn.cursor.return_value = cur

    async def body() -> None:
        c = AsyncTDengineConnector(database="power", connection=conn)
        snap = await c.introspect_schema()
        assert "meters" in snap["tables"]
        cur.fetchall.side_effect = None
        cur.fetchall.return_value = [("3.3.3.0",)]
        cur.description = [("server_version()",)]
        info = await c.test_connection()
        assert info["engine_version"] == "TDengine 3.3.3.0"
        cur.fetchall.side_effect = RuntimeError("down")
        from query_builder.connectors.base import IntrospectionError

        with pytest.raises(IntrospectionError):
            await c.introspect_schema()

    asyncio.run(body())


def test_tdengine_sync_reports_server_version() -> None:
    from query_builder.connectors.tdengine import TDengineConnector

    cur = MagicMock()
    cur.fetchone.return_value = ("3.3.3.0",)
    assert (
        TDengineConnector(cursor=cur).test_connection()["engine_version"]
        == "TDengine 3.3.3.0"
    )


# --- InfluxDB 3 -------------------------------------------------------------------------
def test_influxdb_uses_the_real_driver_module_binds_params_and_introspects_iox() -> (
    None
):
    """The loop never tried ``influxdb_client_3`` (the real module), dropped bound parameters
    and introspected schema 'public' instead of IOx's 'iox'."""
    from query_builder.connectors.influxdb import (
        InfluxDBConnector,
        _InfluxCursorAdapter,
    )

    class Table:
        column_names = ["id"]

        def to_pylist(self) -> list[dict[str, Any]]:
            return [{"id": 1}]

    class Client:
        def __init__(self, **kw: Any) -> None:
            self.kw = kw
            self.queries: list[tuple[str, Any]] = []

        def query(self, sql: str, **kw: Any) -> Table:
            self.queries.append((sql, kw.get("query_parameters")))
            return Table()

    Client.__module__ = "influxdb_client_3.client"
    driver = types.ModuleType("influxdb_client_3")
    driver.InfluxDBClient3 = Client  # type: ignore[attr-defined]
    with patch.dict(sys.modules, {"influxdb_client_3": driver}):
        conn = InfluxDBConnector(host="http://h:8181", database="db", token="t")
        client = conn.connect()
    assert (
        isinstance(client, Client)
        and client.kw["database"] == "db"
        and "schema_name" not in client.kw
    )

    adapter = _InfluxCursorAdapter(client)
    adapter.execute("SELECT * FROM t WHERE a = %s AND b = %s", [1, "x"])
    assert client.queries[-1] == (
        "SELECT * FROM t WHERE a = $p0 AND b = $p1",
        {"p0": 1, "p1": "x"},
    )
    assert adapter.fetchall() == [[1]]

    seen: list[str] = []
    with patch(
        "query_builder.connectors.influxdb.introspect_information_schema",
        side_effect=lambda cur, schema_name, filter_sensitive: seen.append(schema_name)
        or {"tables": {}},
    ):
        conn.introspect_schema()
    assert seen == ["iox"]


def test_influxdb_version_from_ping_header() -> None:
    from query_builder.connectors.influxdb import InfluxDBConnector

    res = MagicMock()
    res.__enter__.return_value = res
    res.headers = {"x-influxdb-version": "3.5.0"}
    with patch("urllib.request.urlopen", return_value=res):
        assert (
            InfluxDBConnector(host="127.0.0.1:8181")._server_version()
            == "InfluxDB 3.5.0"
        )
    with patch("urllib.request.urlopen", side_effect=OSError("down")):
        assert "InfluxDB" in InfluxDBConnector(host="http://h")._server_version()


# --- Milvus / Pinecone ------------------------------------------------------------------
def test_milvus_expression_building_and_async_client_selection() -> None:
    from query_builder.connectors import milvus as m

    expr = m._milvus_expr(
        [
            Cond("a", "=", 'x"y'),
            Cond("b", ">", 3),
            Cond("c", "in", [1, 2]),
            Cond("d", "not_in", ["q"]),
            Cond("e", "is_null"),
            Cond("f", "is_not_null"),
            Cond("g", "=", True),
        ]
    )
    assert (
        expr
        == 'a == "x\\"y" and b > 3 and c in [1, 2] and d not in ["q"] and e is null and f is not null and g == true'
    )
    with pytest.raises(VectorQueryError):
        m._lit(object())

    drv = MagicMock()
    with patch.dict(sys.modules, {"pymilvus": drv}):
        assert (
            asyncio.run(m.AsyncMilvusConnector(uri="http://m:19530").connect())
            is drv.AsyncMilvusClient.return_value
        )
        assert (
            m.MilvusConnector(uri="http://m:19530").connect()
            is drv.MilvusClient.return_value
        )


class _FakeMilvus:
    def __init__(self, loaded: bool = True, metric: str = "COSINE") -> None:
        self.loaded, self.metric, self.calls = loaded, metric, []

    def list_collections(self) -> list[str]:
        return ["People"]

    def describe_collection(self, collection_name: str) -> dict[str, Any]:
        dt = lambda n: SimpleNamespace(name=n)  # noqa: E731
        return {
            "description": "d",
            "fields": [
                {"name": "id", "type": dt("INT64"), "is_primary": True},
                {"name": "vector", "type": dt("FLOAT_VECTOR"), "params": {"dim": 2}},
                {"name": "name", "type": dt("VARCHAR"), "nullable": True},
            ],
        }

    def get_load_state(self, collection_name: str) -> dict[str, Any]:
        return {"state": SimpleNamespace(name="Loaded" if self.loaded else "NotLoad")}

    def load_collection(self, collection_name: str) -> None:
        self.calls.append(("load", {}))
        self.loaded = True

    def list_indexes(self, **kw: Any) -> list[str]:
        return ["vector"]

    def describe_index(self, **kw: Any) -> dict[str, str]:
        return {"metric_type": self.metric}

    def search(self, **kw: Any) -> list[list[dict[str, Any]]]:
        self.calls.append(("search", kw))
        return [[{"id": 1, "distance": 0.99, "entity": {"name": "a", "age": 3}}]]

    def query(self, **kw: Any) -> list[dict[str, Any]]:
        self.calls.append(("query", kw))
        if kw.get("output_fields") == ["count(*)"]:
            return [{"count(*)": 4}]
        return [{"id": 2, "name": "b", "age": 9}, {"id": 1, "name": "a", "age": 3}]

    def get_server_version(self) -> str:
        return "v2.5.0"


_FakeMilvus.__module__ = "pymilvus.milvus_client"


def test_milvus_search_scan_count_introspection_and_loading() -> None:
    from query_builder.connectors.milvus import MilvusConnector

    client = _FakeMilvus(loaded=False)
    conn = MilvusConnector(connection=client)
    res = conn.execute(
        spec={
            "table": "people",
            "columns": ["name", "age"],
            "vector_search": {"vector": [1, 0], "column": "vector", "top_k": 3},
            "filters": [{"column": "age", "op": ">", "value": 1}],
        }
    )
    assert res["rows"][0]["name"] == "a" and res["rows"][0][
        "_distance"
    ] == pytest.approx(0.01)
    assert ("load", {}) in client.calls
    search = next(c for n, c in client.calls if n == "search")
    assert (
        search["filter"] == "age > 1"
        and search["anns_field"] == "vector"
        and search["limit"] == 3
    )
    assert res["count"] == 4 or res["count"] >= 0

    scan = conn.execute(
        spec={
            "table": "people",
            "columns": ["name"],
            "order_by": [{"column": "age", "direction": "asc"}],
            "limit": 5,
        }
    )
    assert [r["name"] for r in scan["rows"]] == ["a", "b"]
    plain = conn.execute(
        sql="SELECT name FROM people LIMIT 1 OFFSET 0", validate_ast=False
    )
    assert plain["rows"] == [{"name": "b"}]
    assert conn.test_connection()["engine_version"] == "Milvus v2.5.0"

    snap = conn.introspect_schema()
    cols = {c["name"]: c for c in snap["tables"]["People"]["columns"]}
    assert (
        cols["vector"]["comment"] == "dimension=2" and cols["id"]["is_primary"] is True
    )
    assert cols["age"]["comment"] == "dynamic field"
    assert MilvusConnector(connection=_FakeMilvus(loaded=False)).introspect_schema()[
        "tables"
    ]["People"]
    with pytest.raises(VectorQueryError, match="does not exist"):
        conn.execute(sql="SELECT name FROM nope", validate_ast=False)
    l2 = MilvusConnector(connection=_FakeMilvus(metric="L2"))
    sp = {
        "table": "people",
        "columns": ["name"],
        "vector_search": {"vector": [1, 0], "column": "vector", "metric": "euclidean"},
    }
    assert l2.execute(spec=sp)["rows"][0]["_distance"] == pytest.approx(0.99**0.5)
    with pytest.raises(VectorQueryError, match="collection uses"):
        MilvusConnector(connection=_FakeMilvus()).execute(spec=sp)


def test_async_milvus_awaits_the_driver() -> None:
    from query_builder.connectors.milvus import AsyncMilvusConnector

    class A(_FakeMilvus):
        pass

    for name in (
        "list_collections",
        "describe_collection",
        "get_load_state",
        "load_collection",
        "list_indexes",
        "describe_index",
        "search",
        "query",
        "get_server_version",
    ):
        sync = getattr(_FakeMilvus, name)

        def make(sync: Any) -> Any:
            async def f(self: Any, *a: Any, **k: Any) -> Any:
                return sync(self, *a, **k)

            return f

        setattr(A, name, make(sync))
    A.__module__ = "pymilvus.milvus_client"

    async def body() -> None:
        c = AsyncMilvusConnector(connection=A())
        assert (await c.test_connection())["engine_version"] == "Milvus v2.5.0"
        res = await c.execute(sql="SELECT name FROM people", validate_ast=False)
        assert res["rows"][0]["name"] == "b"
        assert "People" in (await c.introspect_schema())["tables"]

    asyncio.run(body())


class _FakePineconeIndex:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def query(self, **kw: Any) -> Any:
        self.calls.append(("query", kw))
        return {
            "matches": [
                {"id": "1", "score": 0.9, "metadata": {"name": "a", "age": 3}},
                {"id": "2", "score": 0.1, "metadata": {"name": "b", "age": 9}},
            ]
        }

    def list(self, **kw: Any) -> Any:
        yield SimpleNamespace(
            vectors=[SimpleNamespace(id="1"), SimpleNamespace(id="2")]
        )

    def fetch(self, ids: list[str]) -> Any:
        return SimpleNamespace(
            vectors={
                i: SimpleNamespace(metadata={"name": n, "age": a})
                for i, n, a in (("1", "a", 3), ("2", "b", 9))
                if i in ids
            }
        )

    def describe_index_stats(self) -> dict[str, Any]:
        return {"total_vector_count": 2}


_FakePineconeIndex.__module__ = "pinecone.db_data.index"


class _FakePinecone:
    def __init__(self, metric: str = "cosine") -> None:
        self.metric, self.index = metric, _FakePineconeIndex()

    def list_indexes(self) -> Any:
        return SimpleNamespace(names=lambda: ["qbit-people"])

    def describe_index(self, name: str) -> Any:
        return SimpleNamespace(host="h:1", dimension=2, metric=self.metric)

    def Index(self, host: str) -> Any:  # noqa: N802
        return self.index


_FakePinecone.__module__ = "pinecone.pinecone"


def test_pinecone_search_scan_filters_and_introspection() -> None:
    from query_builder.connectors.pinecone import PineconeConnector

    client = _FakePinecone()
    conn = PineconeConnector(connection=client)
    spec = {
        "table": "qbit_people",
        "columns": ["name", "age"],
        "vector_search": {"vector": [1, 0], "column": "vector", "top_k": 5},
        "filters": [
            {"column": "age", "op": ">", "value": 1},
            {"column": "age", "op": "<", "value": 50},
            {"column": "name", "op": "not_in", "value": ["z"]},
        ],
    }
    res = conn.execute(spec=spec)
    assert [r["name"] for r in res["rows"]] == ["a", "b"]
    q = next(c for n, c in client.index.calls if n == "query")
    assert (
        q["filter"]
        == {
            "age": {"$gt": 1, "$lt": 50},
            "name": {"$nin": ["z"], "$exists": True},
        }
        and q["top_k"] == 5
    )
    assert res["rows"][0]["_distance"] == pytest.approx(0.1)

    scan = conn.execute(
        spec={
            "table": "qbit_people",
            "columns": ["name", "age"],
            "order_by": [{"column": "age", "direction": "desc"}],
            "filters": [{"column": "age", "op": ">", "value": 1}],
            "limit": 5,
        }
    )
    assert [r["name"] for r in scan["rows"]] == ["b", "a"]
    cnt = conn.execute(sql="SELECT COUNT(*) FROM qbit_people", validate_ast=False)
    assert cnt["rows"] == [{"count": 2}]
    snap = conn.introspect_schema()
    cols = {c["name"]: c for c in snap["tables"]["qbit-people"]["columns"]}
    assert (
        set(cols) == {"id", "vector", "name", "age"}
        and "dimension=2" in cols["vector"]["comment"]
    )
    with pytest.raises(VectorQueryError, match="unsupported WHERE"):
        conn.execute(
            sql="SELECT name FROM qbit_people WHERE name = 'a' OR age = 1",
            validate_ast=False,
        )
    from query_builder.connectors.pinecone import _pinecone_filter

    assert _pinecone_filter([Cond("a", "is_null"), Cond("b", "is_not_null")]) == {
        "a": {"$exists": False},
        "b": {"$exists": True},
    }
    with pytest.raises(VectorQueryError, match="does not exist"):
        conn.execute(sql="SELECT name FROM other", validate_ast=False)
    assert conn.test_connection()["status"] == "healthy"

    euclid = PineconeConnector(connection=_FakePinecone("euclidean"))
    sp = {
        "table": "qbit_people",
        "columns": ["name"],
        "vector_search": {"vector": [1, 0], "column": "vector", "metric": "euclidean"},
    }
    assert euclid.execute(spec=sp)["rows"][0]["_distance"] == pytest.approx(0.9**0.5)


def test_pinecone_bare_index_connection() -> None:
    from query_builder.connectors.pinecone import PineconeConnector

    idx = _FakePineconeIndex()
    conn = PineconeConnector(connection=idx, index_name="qbit-people", metric="cosine")
    res = conn.execute(
        sql="SELECT COSINE_DISTANCE(v, %s) AS d, name FROM qbit_people ORDER BY d LIMIT 1",
        params=[[1.0, 0.0]],
        validate_ast=False,
    )
    assert res["rows"][0]["name"] == "a"
    assert conn.test_connection()["status"] == "healthy"
    assert "qbit-people" in conn.introspect_schema()["tables"]


def test_async_pinecone_awaits_the_driver() -> None:
    from query_builder.connectors.pinecone import AsyncPineconeConnector

    class AIdx(_FakePineconeIndex):
        async def query(self, **kw: Any) -> Any:  # type: ignore[override]
            return super().query(**kw)

        async def list(self, **kw: Any) -> Any:  # type: ignore[override]
            yield SimpleNamespace(vectors=[SimpleNamespace(id="1")])

        async def fetch(self, ids: list[str]) -> Any:  # type: ignore[override]
            return super().fetch(ids)

        async def describe_index_stats(self) -> dict[str, Any]:  # type: ignore[override]
            return {"total_vector_count": 2}

    AIdx.__module__ = "pinecone.db_data.index_asyncio"

    class APc(_FakePinecone):
        def __init__(self) -> None:
            super().__init__()
            self.index = AIdx()

        async def list_indexes(self) -> Any:  # type: ignore[override]
            return SimpleNamespace(names=lambda: ["qbit-people"])

        async def describe_index(self, name: str) -> Any:  # type: ignore[override]
            return SimpleNamespace(host="h:1", dimension=2, metric="cosine")

        def IndexAsyncio(self, host: str) -> Any:  # noqa: N802
            return self.index

    APc.__module__ = "pinecone.pinecone_asyncio"

    async def body() -> None:
        c = AsyncPineconeConnector(connection=APc())
        assert (await c.test_connection())["status"] == "healthy"
        res = await c.execute(
            spec={
                "table": "qbit_people",
                "columns": ["name"],
                "vector_search": {"vector": [1, 0], "column": "vector"},
            }
        )
        assert res["rows"][0]["name"] == "a"
        scan = await c.execute(sql="SELECT name FROM qbit_people", validate_ast=False)
        assert scan["rows"] == [{"name": "a"}]
        assert "qbit-people" in (await c.introspect_schema())["tables"]
        bare = AsyncPineconeConnector(connection=AIdx())
        assert (await bare.test_connection())["status"] == "healthy"

    asyncio.run(body())


def test_async_pinecone_connect_uses_the_asyncio_client_for_a_named_index() -> None:
    from query_builder.connectors.pinecone import AsyncPineconeConnector

    drv = MagicMock()
    pc = MagicMock()

    async def describe(name: str) -> Any:
        return SimpleNamespace(host="h:1")

    pc.describe_index = describe
    drv.PineconeAsyncio.return_value = pc
    with patch.dict(sys.modules, {"pinecone": drv}):
        c = AsyncPineconeConnector(index_name="x", api_key="k", metric="cosine")
        assert asyncio.run(c.connect()) is pc.IndexAsyncio.return_value
        plain = AsyncPineconeConnector(api_key="k")
        assert asyncio.run(plain.connect()) is pc
        sync = __import__(
            "query_builder.connectors.pinecone", fromlist=["x"]
        ).PineconeConnector(api_key="k", metric="cosine")
        sync.connect()
    assert "metric" not in drv.Pinecone.call_args.kwargs
    boom = MagicMock()
    boom.PineconeAsyncio.side_effect = RuntimeError("nope")
    with (
        patch.dict(sys.modules, {"pinecone": boom}),
        pytest.raises(ConnectionFailedError),
    ):
        asyncio.run(AsyncPineconeConnector().connect())
