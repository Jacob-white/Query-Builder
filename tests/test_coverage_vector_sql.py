"""Unit tests for the shared vector-store SQL interpreter (connectors/_vector_sql.py)."""

from __future__ import annotations

import asyncio

import pytest

from query_builder.connectors import _vector_sql as vs
from query_builder.connectors._vector_sql import VectorQueryError, parse_vector_sql


def test_vector_from_param_accepts_lists_and_json() -> None:
    assert vs.vector_from_param([1, 2.5]) == [1.0, 2.5]
    assert vs.vector_from_param((3,)) == [3.0]
    assert vs.vector_from_param("[0.1, 0.2]") == [0.1, 0.2]
    for bad in ("not json", "[]", "{}", 5, None):
        with pytest.raises(VectorQueryError):
            vs.vector_from_param(bad)


def test_distance_from_score_per_metric() -> None:
    assert vs.distance_from_score("cosine", 0.75, "cosine") == 0.25
    assert vs.distance_from_score("dot", 2, "dot") == -2.0
    assert vs.distance_from_score("euclidean", 3, "euclidean") == 3.0
    with pytest.raises(VectorQueryError, match="cosine.*euclidean"):
        vs.distance_from_score("cosine", 1, "euclidean")


def test_parse_search_query_with_filters_order_and_paging() -> None:
    q = parse_vector_sql(
        "SELECT id, title AS t, COSINE_DISTANCE(emb, %s) AS d FROM docs "
        "WHERE (tag = %s AND n >= 2) AND ok = TRUE AND price > -1.5 "
        "ORDER BY d ASC, n DESC LIMIT 5 OFFSET 10;",
        ["[1, 0]", "x"],
    )
    assert q.table == "docs" and q.is_search
    assert q.vector == [1.0, 0.0] and q.metric == "cosine" and q.vector_column == "emb"
    assert q.columns == [("id", "id"), ("t", "title"), ("d", "_distance")]
    assert [(c.column, c.op, c.value) for c in q.conds] == [
        ("tag", "=", "x"),
        ("n", ">=", 2),
        ("ok", "=", True),
        ("price", ">", -1.5),
    ]
    assert q.order_by == [("_distance", False), ("n", True)]
    assert (q.limit, q.offset) == (5, 10)
    assert q.wanted_payload_fields() == sorted({"id", "title", "tag", "n", "ok", "price"})


def test_parse_distance_threshold_and_order_by_function() -> None:
    q = parse_vector_sql(
        "SELECT * FROM c WHERE L2_DISTANCE(v, %s) < 0.5 ORDER BY L2_DISTANCE(v, %s) LIMIT 3",
        ["[1, 2]", [1, 2]],
    )
    assert q.metric == "euclidean" and q.max_distance == 0.5
    assert q.order_by == [("_distance", False)]
    assert q.wanted_payload_fields() is None  # "*" fetches everything
    le = parse_vector_sql("SELECT * FROM c WHERE INNER_PRODUCT(v, %s) <= 1", ["[1]"])
    assert le.metric == "dot" and le.max_distance == 1.0
    # two different query vectors in one statement cannot be honoured
    with pytest.raises(VectorQueryError, match="one query vector"):
        parse_vector_sql(
            "SELECT COSINE_DISTANCE(v, %s) FROM c ORDER BY COSINE_DISTANCE(v, %s)",
            ["[1]", "[2]"],
        )


def test_parse_count_scan_and_null_conditions() -> None:
    q = parse_vector_sql("SELECT COUNT(*) FROM c WHERE a IS NULL AND b IS NOT NULL")
    assert q.count_only
    assert [(c.column, c.op) for c in q.conds] == [("a", "is_null"), ("b", "is_not_null")]
    q2 = parse_vector_sql(
        "SELECT id FROM c WHERE a IN (1, 'x', NULL) AND b NOT IN (2, 3) "
        "AND NOT (c IS NULL) AND d != 4 AND e < 5 AND f <= 6 AND g > 7"
    )
    ops = {c.column: (c.op, c.value) for c in q2.conds}
    assert ops["a"] == ("in", [1, "x", None])
    assert ops["b"] == ("not_in", [2, 3])
    assert ops["c"] == ("is_not_null", None)
    assert ops["d"] == ("!=", 4)
    assert (ops["e"][0], ops["f"][0], ops["g"][0]) == ("<", "<=", ">")
    nested = parse_vector_sql("SELECT id FROM c WHERE ((a = 1 AND b = 2))")
    assert [c.column for c in nested.conds] == ["a", "b"]
    q3 = parse_vector_sql("SELECT `id` FROM `c` WHERE x = 1.5 AND y = 'it''s'")
    assert [c.value for c in q3.conds] == [1.5, "it's"]
    assert parse_vector_sql("SELECT id FROM c ORDER BY id DESC").order_by == [("id", True)]


@pytest.mark.parametrize(
    ("sql", "match"),
    [
        ("SELEC nonsense (", "cannot parse"),
        ("DELETE FROM c", "only SELECT"),
        ("SELECT * FROM a JOIN b ON a.id = b.id", "JOINS"),
        ("SELECT t FROM c GROUP BY t", "GROUP"),
        ("SELECT t FROM c GROUP BY t HAVING COUNT(*) > 1", "GROUP"),
        ("WITH x AS (SELECT 1) SELECT * FROM x", "WITH"),
        ("SELECT DISTINCT t FROM c", "DISTINCT"),
        ("SELECT 1", "single collection"),
        ("SELECT * FROM (SELECT 1) s", "single collection"),
        ("SELECT LOWER(t) FROM c", "unsupported projection"),
        ("SELECT id FROM c WHERE LOWER(t) = 'x'", "unsupported column"),
        ("SELECT id FROM c WHERE t LIKE 'x%'", "unsupported WHERE"),
        ("SELECT id FROM c WHERE a = 1 OR b = 2", "unsupported WHERE"),
        ("SELECT id FROM c WHERE a = b + 1", "unsupported value"),
        ("SELECT id FROM c ORDER BY LOWER(t)", "unsupported ORDER BY"),
        ("SELECT id FROM c WHERE a = %s", "missing query parameter"),
        ("SELECT id FROM c WHERE NOT a = 1", "unsupported WHERE"),
    ],
)
def test_parse_rejects_what_a_vector_store_cannot_do_faithfully(sql: str, match: str) -> None:
    with pytest.raises(VectorQueryError, match=match):
        parse_vector_sql(sql)


def test_shape_rows_projection_star_and_count() -> None:
    hits = [{"id": 1, "t": "a", "_distance": 0.1}, {"id": 2, "extra": 5}]
    q = parse_vector_sql("SELECT id, t AS title, COSINE_DISTANCE(v, %s) AS d FROM c", ["[1]"])
    desc, rows = vs.shape_rows(q, hits)
    assert desc == [("id",), ("title",), ("d",)]
    assert rows == [[1, "a", 0.1], [2, None, None]]
    star = parse_vector_sql("SELECT * FROM c")
    desc, rows = vs.shape_rows(star, hits)
    assert desc == [("id",), ("t",), ("_distance",), ("extra",)]
    assert rows[1] == [2, None, None, 5]
    assert vs.shape_rows(star, []) == ([("id",)], [])
    assert vs.shape_rows(parse_vector_sql("SELECT COUNT(*) FROM c"), hits) == (
        [("count",)],
        [[2]],
    )


def test_sort_hits_puts_missing_values_last_both_directions() -> None:
    hits = [{"id": 1, "n": 2}, {"id": 2}, {"id": 3, "n": 9}, {"id": 4, "n": 2, "s": "b"}]
    asc = vs.sort_hits(parse_vector_sql("SELECT * FROM c ORDER BY n"), hits)
    assert [h["id"] for h in asc] == [1, 4, 3, 2]
    desc = vs.sort_hits(parse_vector_sql("SELECT * FROM c ORDER BY n DESC"), hits)
    assert [h["id"] for h in desc] == [3, 1, 4, 2]
    assert vs.sort_hits(parse_vector_sql("SELECT * FROM c"), hits) == hits


def test_matches_client_side_filter_semantics() -> None:
    def m(sql: str, hit: dict[str, object]) -> bool:
        return vs.matches(parse_vector_sql(f"SELECT * FROM c WHERE {sql}").conds, hit)

    assert m("a = 1", {"a": 1}) and not m("a = 1", {"a": 2})
    assert not m("a = 1", {})  # NULL never equals
    assert m("a != 1", {}) and m("a != 1", {"a": 2}) and not m("a != 1", {"a": 1})
    assert m("a IN (1, 2)", {"a": 2}) and not m("a IN (1, 2)", {"a": 3})
    assert m("a NOT IN (1, 2)", {"a": 3}) and not m("a NOT IN (1, 2)", {"a": 1})
    assert m("a IS NULL", {}) and not m("a IS NULL", {"a": 0})
    assert m("a IS NOT NULL", {"a": 0}) and not m("a IS NOT NULL", {})
    assert m("a > 1", {"a": 2}) and not m("a > 1", {"a": 1})
    assert m("a >= 1", {"a": 1}) and not m("a >= 2", {"a": 1})
    assert m("a < 2", {"a": 1}) and not m("a < 1", {"a": 1})
    assert m("a <= 1", {"a": 1}) and not m("a <= 0", {"a": 1})
    assert not m("a > 1", {"a": "text"})  # incomparable types never match
    assert m("a = 1 AND b = 2", {"a": 1, "b": 2}) and not m("a = 1 AND b = 2", {"a": 1})


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.sub = type("Sub", (), {"fetch": lambda _s, **kw: ("sub", kw)})()

    def search(self, **kw: object) -> str:
        self.calls.append(("search", kw))
        return "found"

    def boom(self, **kw: object) -> None:
        raise RuntimeError("engine said no")


def test_drive_sync_resolves_dotted_names_and_throws_errors_into_plan() -> None:
    client = _Client()

    def plan():
        first = yield ("search", {"q": 1})
        second = yield ("sub.fetch", {"k": 2})
        try:
            yield ("boom", {})
        except RuntimeError as exc:
            return [first, second, str(exc)]

    assert vs.drive_sync(plan(), client) == [
        "found",
        ("sub", {"k": 2}),
        "engine said no",
    ]
    assert client.calls == [("search", {"q": 1})]

    def with_callable():
        out = yield (lambda **kw: ("direct", kw), {"z": 1})
        return out

    assert vs.drive_sync(with_callable(), client) == ("direct", {"z": 1})


def test_drive_async_awaits_coroutines_and_throws_errors_into_plan() -> None:
    class AClient:
        async def search(self, **kw: object) -> str:
            return f"async {kw}"

        def plain(self, **kw: object) -> str:
            return "plain"

        async def boom(self, **kw: object) -> None:
            raise RuntimeError("nope")

    def plan():
        a = yield ("search", {"q": 1})
        b = yield ("plain", {})
        try:
            yield ("boom", {})
        except RuntimeError as exc:
            return [a, b, str(exc)]

    out = asyncio.run(vs.drive_async(plan(), AClient()))
    assert out == ["async {'q': 1}", "plain", "nope"]


def test_drive_async_collects_async_generators() -> None:
    class AClient:
        async def stream(self, **kw: object):
            for i in range(3):
                yield i

    def plan():
        items = yield ("stream", {})
        return items

    assert asyncio.run(vs.drive_async(plan(), AClient())) == [0, 1, 2]


def test_infer_type_and_payload_columns() -> None:
    kinds = [vs.infer_type(v) for v in (True, 1, 1.5, "s", [1], (1,), {"a": 1}, None)]
    assert kinds == [
        "boolean",
        "integer",
        "float",
        "string",
        "array",
        "array",
        "json",
        "unknown",
    ]
    cols = vs.payload_columns(
        [{"a": None, "b": 1}, {"a": "x", "b": "late", "c": None}, {"c": 2.5}],
        declared={"b": "text"},
    )
    assert cols == {"b": "text", "a": "string", "c": "float"}
