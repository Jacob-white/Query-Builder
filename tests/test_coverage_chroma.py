"""Mock tests for the ChromaDB SQL-subset translation onto Collection.get/query."""

from __future__ import annotations

from typing import Any

import pytest
import sqlglot

from query_builder.connectors import chroma as ch
from query_builder.connectors.chroma import UnsupportedChromaQuery, _ChromaCursorAdapter


class _Collection:
    def __init__(
        self, get_res: dict[str, Any], query_res: dict[str, Any] | None = None
    ):
        self.get_res = get_res
        self.query_res = query_res or {}
        self.get_calls: list[dict[str, Any]] = []
        self.query_calls: list[dict[str, Any]] = []

    def get(self, **kw: Any) -> dict[str, Any]:
        self.get_calls.append(kw)
        return self.get_res

    def query(self, **kw: Any) -> dict[str, Any]:
        self.query_calls.append(kw)
        return self.query_res


class _Client:
    """A chromadb client: get_collection() only (no cursor/query/execute)."""

    def __init__(self, coll: _Collection) -> None:
        self.coll = coll
        self.requested: list[str] = []

    def get_collection(self, name: str) -> _Collection:
        self.requested.append(name)
        return self.coll


DOCS = {
    "ids": ["a", "b", "c"],
    "documents": ["da", "db", None],
    "metadatas": [{"n": 3, "tag": "x"}, {"n": 1}, None],
}


def _run(sql: str, params: list[Any] | None = None, res: dict[str, Any] | None = None):
    coll = _Collection(res or DOCS)
    cur = _ChromaCursorAdapter(_Client(coll))
    cur.execute(sql, params)
    return cur, coll


def _where(sql: str) -> Any:
    node = sqlglot.parse_one(sql, read="postgres").args["where"].this
    return ch._chroma_where(node)


def test_literals_and_where_translation() -> None:
    assert _where("SELECT * FROM t WHERE n > -5") == (None, {"n": {"$gt": -5}})
    assert _where("SELECT * FROM t WHERE n <= 2.5") == (None, {"n": {"$lte": 2.5}})
    assert _where("SELECT * FROM t WHERE n < 1e3") == (None, {"n": {"$lt": 1000.0}})
    assert _where("SELECT * FROM t WHERE ok = TRUE") == (None, {"ok": {"$eq": True}})
    assert _where("SELECT * FROM t WHERE tag <> 'x'") == (None, {"tag": {"$ne": "x"}})
    assert _where("SELECT * FROM t WHERE n >= 1 AND (a = 'q' OR b IN (1, 2))") == (
        None,
        {
            "$and": [
                {"n": {"$gte": 1}},
                {"$or": [{"a": {"$eq": "q"}}, {"b": {"$in": [1, 2]}}]},
            ]
        },
    )
    # id filters become a ids= lookup, not a metadata where
    assert _where("SELECT * FROM t WHERE id = 'a'") == (["a"], None)
    assert _where("SELECT * FROM t WHERE id IN ('a', 'b')") == (["a", "b"], None)
    assert _where("SELECT * FROM t WHERE id = 7") == (["7"], None)


@pytest.mark.parametrize(
    "where",
    [
        "n = other",  # column vs column: not a literal
        "n LIKE 'x%'",  # unsupported operator
        "NOT n = 1",
        "n = 1 + 2",
    ],
)
def test_unsupported_where_raises_instead_of_returning_unfiltered_rows(
    where: str,
) -> None:
    with pytest.raises(UnsupportedChromaQuery):
        _where(f"SELECT * FROM t WHERE {where}")


def test_select_star_with_filter_order_limit_offset() -> None:
    cur, coll = _run(
        "SELECT * FROM docs WHERE n >= 1 ORDER BY n DESC LIMIT 1 OFFSET 1;"
    )
    assert coll.get_calls == [
        {
            "ids": None,
            "where": {"n": {"$gte": 1}},
            "include": ["documents", "metadatas"],
        }
    ]
    # DESC puts NULLs first (c, a, b); OFFSET 1 LIMIT 1 keeps "a"
    assert [d[0] for d in cur.description] == ["id", "document", "n", "tag"]
    assert cur.fetchall() == [["a", "da", 3, "x"]]


def test_projection_aliases_and_ordering_with_nulls_last() -> None:
    cur, coll = _run("SELECT id AS key, tag FROM docs ORDER BY tag, id DESC")
    assert [d[0] for d in cur.description] == ["key", "tag"]
    # tag ascending, None last; ties keep id-descending order applied first
    assert cur.fetchall() == [["a", "x"], ["c", None], ["b", None]]


def test_select_star_with_no_rows_names_default_columns() -> None:
    cur, _ = _run(
        "SELECT * FROM docs", res={"ids": [], "documents": [], "metadatas": []}
    )
    assert [d[0] for d in cur.description] == ["id", "document"]
    assert cur.fetchall() == []


def test_id_filter_goes_to_get_ids() -> None:
    cur, coll = _run("SELECT id FROM docs WHERE id IN ('a', 'c')")
    assert coll.get_calls[0]["ids"] == ["a", "c"] and coll.get_calls[0]["where"] is None
    assert cur.fetchone() == ["a"]
    assert cur.fetchone() == [
        "b"
    ]  # the fake does not filter; adapter returns what get gave
    assert cur.fetchmany(5) == [["c"]]


def test_parameters_are_inlined_with_escaping_before_translation() -> None:
    cur, coll = _run("SELECT id FROM docs WHERE tag = %s", ["x'y"])
    assert coll.get_calls[0]["where"] == {"tag": {"$eq": "x'y"}}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a.id FROM docs a JOIN other b ON a.id = b.id",
        "SELECT tag, COUNT(*) FROM docs GROUP BY tag",
        "SELECT DISTINCT tag FROM docs",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "SELECT * FROM (SELECT 1) s",
        "SELECT 1",
        "SELECT id FROM docs ORDER BY LOWER(tag)",
        "SELECT LOWER(tag) FROM docs",
        "INSERT INTO docs VALUES (1)",
    ],
)
def test_unsupported_select_shapes_are_refused(sql: str) -> None:
    coll = _Collection(DOCS)
    cur = _ChromaCursorAdapter(_Client(coll))
    with pytest.raises(UnsupportedChromaQuery):
        cur.execute(sql)


def test_vector_query_maps_to_collection_query() -> None:
    res = {
        "ids": [["a", "b"]],
        "documents": [["da", "db"]],
        "metadatas": [[{"n": 1}, None]],
        "distances": [[0.1, 0.2]],
    }
    coll = _Collection(DOCS, res)
    cur = _ChromaCursorAdapter(_Client(coll))
    cur.execute("SELECT id, distance FROM docs ORDER BY distance LIMIT 2", [[1, 2]])
    assert coll.query_calls == [
        {
            "query_embeddings": [[1, 2]],
            "n_results": 2,
            "include": ["documents", "metadatas", "distances"],
        }
    ]
    assert [d[0] for d in cur.description] == ["id", "document", "n", "distance"]
    assert cur.fetchall() == [["a", "da", 1, 0.1], ["b", "db", None, 0.2]]
    # JSON string vector, default n_results, quoted collection, empty result
    coll2 = _Collection(DOCS, {"ids": [[]], "distances": [[]]})
    cur2 = _ChromaCursorAdapter(_Client(coll2))
    cur2.execute('SELECT * FROM "docs" WHERE vector = %s', ["[0.5, 0.25]"])
    assert coll2.query_calls[0]["query_embeddings"] == [[0.5, 0.25]]
    assert coll2.query_calls[0]["n_results"] == 10
    assert [d[0] for d in cur2.description] == ["id", "document", "distance"]
    assert cur2.fetchall() == []


def test_vector_query_rejects_malformed_requests() -> None:
    client = _Client(_Collection(DOCS))
    cur = _ChromaCursorAdapter(client)
    with pytest.raises(UnsupportedChromaQuery, match="FROM"):
        cur._vector_query("SELECT distance", [[1.0]])
    with pytest.raises(UnsupportedChromaQuery, match="vector"):
        cur._vector_query("SELECT distance FROM docs", [5])


def test_chroma_records_handles_ragged_results() -> None:
    assert ch._chroma_records({}) == []
    recs = ch._chroma_records(
        {"ids": ["a", "b"], "documents": ["x"], "metadatas": [{"k": 1}]}
    )
    assert recs == [{"id": "a", "document": "x", "k": 1}, {"id": "b", "document": None}]
    assert ch._chroma_version().startswith("ChromaDB")
