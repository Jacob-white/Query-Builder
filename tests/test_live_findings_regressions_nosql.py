"""
Regression tests for defects found by running the NoSQL / graph / document / wide-column
connectors against REAL engines (tests/integration, ``engines_nosql.py``).  Default suite:
mocks and fakes only, no services.  One block per bug, named after the symptom seen live.
"""

from __future__ import annotations

import asyncio
import datetime
import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from query_builder.connectors._native_readonly import (
    assert_read_only,
    find_mutation,
    strip_literals,
)
from query_builder.connectors._sql_subset import (
    UnsupportedQuery,
    parse_select_subset,
)
from query_builder.connectors.base import (
    ConnectionFailedError,
    IntrospectionError,
)
from query_builder.exceptions import SecurityError


def run(coro: Any) -> Any:
    return asyncio.run(coro)


# ============================================================================
# Native read-only guard (AQL REMOVE/REPLACE/UPSERT, Cypher SET/MERGE/REMOVE, SurrealQL
# RELATE/DEFINE, CQL BATCH/TRUNCATE, SQL++ MERGE were NOT caught by the SQL-shaped check)
# ============================================================================
@pytest.mark.parametrize(
    ("language", "statement"),
    [
        ("aql", "FOR p IN people REMOVE p IN people"),
        ("aql", "FOR p IN people REPLACE p WITH {a: 1} IN people"),
        ("aql", "UPSERT {a: 1} INSERT {a: 1} UPDATE {} IN people"),
        ("aql", "FOR p IN people RETURN 1; /* x */ FOR q IN t INSERT {} INTO t"),
        ("surrealql", "DELETE people"),
        ("surrealql", "UPDATE people SET age = 0"),
        ("surrealql", "RELATE a:1->knows->b:2"),
        ("surrealql", "DEFINE TABLE x"),
        ("surrealql", "SELECT * FROM people; REMOVE TABLE people"),
        ("surrealql", "RETURN http::get('http://x')"),
        ("cypher", "MATCH (p) SET p.age = 0"),
        ("cypher", "MERGE (n:X {id: 1})"),
        ("cypher", "MATCH (p) REMOVE p.age"),
        ("cypher", "MATCH (p) DETACH DELETE p"),
        ("cypher", "CALL mg.load_all()"),
        ("cypher", "DROP GRAPH"),
        ("cql", "BEGIN BATCH INSERT INTO t (a) VALUES (1) APPLY BATCH"),
        ("cql", "TRUNCATE t"),
        ("cql", "DELETE FROM t WHERE a = 1"),
        ("n1ql", "MERGE INTO t USING s ON KEY s.k WHEN MATCHED THEN DELETE"),
        ("n1ql", "UPSERT INTO t (KEY, VALUE) VALUES ('k', {})"),
        ("n1ql", "SELECT 1; DROP COLLECTION t"),
    ],
)
def test_native_read_only_guard_rejects_writes(language: str, statement: str) -> None:
    assert find_mutation(statement, language) is not None
    with pytest.raises(SecurityError, match="Read-only session violation"):
        assert_read_only(statement, language, "Engine")


@pytest.mark.parametrize(
    ("language", "statement"),
    [
        ("aql", "FOR p IN people SORT p.age RETURN {name: p.name, update: p.update}"),
        ("aql", "FOR p IN `remove` RETURN 'REMOVE' /* INSERT */"),
        ("aql", "RETURN COLLECTIONS()"),
        ("aql", ""),
        ("surrealql", "SELECT name, age FROM people ORDER BY age"),
        ("surrealql", "INFO FOR DB"),
        ("surrealql", "SELECT * FROM t WHERE x = 'DELETE'"),
        ("cypher", "MATCH (p:Person) RETURN p.name AS name, p.set AS s"),
        ("cypher", "SHOW VERSION"),
        ("cypher", "CALL schema.node_type_properties() YIELD *"),
        ("cypher", "CALL dbms.components() YIELD name"),
        ("cql", "SELECT name FROM system_schema.tables"),
        ("n1ql", "SELECT name FROM system:keyspaces"),
        ("n1ql", "INFER `b`.`_default`.`c`"),
    ],
)
def test_native_read_only_guard_allows_reads(language: str, statement: str) -> None:
    assert find_mutation(statement, language) is None
    assert_read_only(statement, language, "Engine")


def test_native_read_only_guard_helpers() -> None:
    assert strip_literals("a 'b' \"c\" `d` -- e\nf // g\n/* h */ i # j").split() == [
        "a",
        "f",
        "i",
    ]
    assert find_mutation("   ;  ", "cypher") is None  # blank
    assert find_mutation("12345", "cypher") is None  # no words at all
    assert "starts with" in (find_mutation("PURGE x", "aql") or "")


# ============================================================================
# SQL subset parser (Firestore / Bigtable have no SQL: unsupported statements must RAISE)
# ============================================================================
def test_subset_parser_full_statement() -> None:
    plan = parse_select_subset(
        'SELECT "t"."name" AS n, age FROM `people` AS t '
        "WHERE t.age >= %s AND name IN (%s, 'b') AND 3 < score AND x IS NOT NULL "
        "AND y IS NULL AND z NOT IN (1, 2) AND w LIKE 'ab%' AND v != -1 "
        "ORDER BY age DESC, name LIMIT %s OFFSET 2",
        [30, "a", 5],
    )
    assert plan.table == "people"
    assert plan.columns == ["name", "age"] and plan.out_names == ["n", "age"]
    ops = [(p.column, p.op, p.value) for p in plan.predicates]
    assert ops == [
        ("age", ">=", 30),
        ("name", "in", ["a", "b"]),
        ("score", ">", 3),
        ("x", "is-not-null", None),
        ("y", "is-null", None),
        ("z", "not-in", [1, 2]),
        ("w", "prefix", "ab"),
        ("v", "!=", -1),
    ]
    assert plan.order_by == [("age", True), ("name", False)]
    assert (plan.limit, plan.offset) == (5, 2)


def test_subset_parser_star_count_and_literals() -> None:
    assert parse_select_subset("SELECT * FROM c").columns is None
    assert parse_select_subset('SELECT "t".* FROM c AS t').columns is None
    plan = parse_select_subset("SELECT COUNT(*) AS n FROM c WHERE a = 1.5 AND b = true")
    assert plan.count_star and plan.count_alias == "n"
    assert [p.value for p in plan.predicates] == [1.5, True]
    plan = parse_select_subset("SELECT COUNT(*) FROM c WHERE a = NULL AND (b = 1)")
    assert plan.count_alias == "count" and plan.predicates[1].value == 1
    # a '?' inside a literal is not a placeholder; ? outside is
    plan = parse_select_subset("SELECT a FROM c WHERE b = 'x?' AND c = ?", [7])
    assert [p.value for p in plan.predicates] == ["x?", 7]


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM c",
        "SELECT a FROM c JOIN d ON c.x = d.x",
        "SELECT a FROM (SELECT a FROM c) AS t",
        "SELECT a FROM c GROUP BY a",
        "SELECT DISTINCT a FROM c",
        "SELECT a FROM c WHERE a = 1 OR b = 2",
        "SELECT a FROM c WHERE a IN (SELECT a FROM d)",
        "SELECT a FROM c WHERE a LIKE '%x'",
        "SELECT a FROM c WHERE a IS TRUE",
        "SELECT a FROM c WHERE NOT a = 1",
        "SELECT a FROM c WHERE a BETWEEN 1 AND 2",
        "SELECT lower(a) FROM c",
        "SELECT COUNT(*), a FROM c",
        "SELECT a FROM c WHERE a = b",
        "SELECT a FROM c WHERE a = :named",
        "SELECT a FROM c WHERE a = %s",
        "SELECT a FROM c WHERE a = (1 + 2)",
        "SELECT a FROM c WHERE 1 = 1",
        "SELECT a FROM c ORDER BY lower(a)",
        "SELEC a FROM",
        "SELECT 1",
    ],
)
def test_subset_parser_rejects_everything_outside_the_subset(sql: str) -> None:
    with pytest.raises(UnsupportedQuery):
        parse_select_subset(sql)


# ============================================================================
# Firestore: the connector ignored the query (returned the first 10 documents of whatever
# collection a regex found, "users" when none), invented collections/columns, and its
# async class never awaited the async client.
# ============================================================================
class FakeDoc:
    def __init__(self, doc_id: str, data: dict[str, Any]) -> None:
        self.id = doc_id
        self._data = data

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)


class FakeQuery:
    """Records the structured-query calls the connector makes."""

    def __init__(self, docs: list[FakeDoc], log: list[Any]) -> None:
        self.docs, self.log = docs, log

    def where(self, filter: Any) -> FakeQuery:  # noqa: A002 - mirrors the SDK keyword
        self.log.append(("where", filter.field_path, filter.op_string, filter.value))
        return self

    def order_by(self, field: str, direction: str) -> FakeQuery:
        self.log.append(("order_by", field, direction))
        return self

    def offset(self, n: int) -> FakeQuery:
        self.log.append(("offset", n))
        return self

    def limit(self, n: int) -> FakeQuery:
        self.log.append(("limit", n))
        return self

    def stream(self) -> list[FakeDoc]:
        return self.docs

    def count(self) -> Any:
        agg = MagicMock()
        agg.get.return_value = [[MagicMock(value=len(self.docs))]]
        return agg


class FakeFirestore:
    def __init__(self, collections: dict[str, list[FakeDoc]]) -> None:
        self.data = collections
        self.log: list[Any] = []

    def collection(self, name: str) -> FakeQuery:
        self.log.append(("collection", name))
        return FakeQuery(self.data[name], self.log)

    def collections(self) -> list[Any]:
        return [types.SimpleNamespace(id=n) for n in self.data]


class FakeFieldFilter:
    def __init__(self, field_path: str, op_string: str, value: Any) -> None:
        self.field_path, self.op_string, self.value = field_path, op_string, value


@pytest.fixture
def fake_firestore_filter() -> Any:
    mods = {
        "google.cloud.firestore_v1": types.ModuleType("google.cloud.firestore_v1"),
        "google.cloud.firestore_v1.base_query": types.ModuleType("base_query"),
    }
    mods["google.cloud.firestore_v1.base_query"].FieldFilter = FakeFieldFilter  # type: ignore[attr-defined]
    with patch.dict(sys.modules, mods):
        yield


PEOPLE_DOCS = [
    FakeDoc(
        "a",
        {"id": 1, "name": "alice", "age": 30, "ref": types.SimpleNamespace(path="x/y")},
    ),
    FakeDoc("b", {"name": "bob", "age": 45, "when": datetime.datetime(2020, 1, 1)}),
]


def test_firestore_adapter_runs_the_query_not_a_fixed_scan(
    fake_firestore_filter: Any,
) -> None:
    from query_builder.connectors.firestore import _FirestoreCursorAdapter

    client = FakeFirestore({"people": PEOPLE_DOCS})
    adapter = _FirestoreCursorAdapter(client)
    adapter.execute(
        'SELECT "t"."name" AS n FROM "people" AS "t" WHERE age >= %s AND name = %s '
        "AND score IN (1, 2) AND nick LIKE %s AND z IS NULL AND y IS NOT NULL "
        "ORDER BY age DESC, name LIMIT 5 OFFSET 1",
        [30, "alice", "al%"],
    )
    assert adapter.description == [("n",)]
    assert adapter.fetchall() == [["alice"], ["bob"]]
    assert client.log == [
        ("collection", "people"),
        ("where", "age", ">=", 30),
        ("where", "name", "==", "alice"),
        ("where", "score", "in", [1, 2]),
        ("where", "nick", ">=", "al"),
        ("where", "nick", "<=", "al"),
        ("where", "z", "==", None),
        ("where", "y", "!=", None),
        ("order_by", "age", "DESCENDING"),
        ("order_by", "name", "ASCENDING"),
        ("offset", 1),
        ("limit", 5),
    ]
    adapter.execute("SELECT * FROM people")  # union of fields; own `id` field wins
    names = [d[0] for d in adapter.description]
    assert names == ["id", "name", "age", "ref", "when"]
    rows = adapter.fetchall()
    assert rows[0][0] == 1 and rows[1][0] == "b"  # doc id only when no `id` field
    assert rows[0][3] == "x/y"  # DocumentReference -> its path
    adapter.execute("SELECT COUNT(*) AS n FROM people WHERE age > 1")
    assert (adapter.description, adapter.fetchall()) == ([("n",)], [[2]])
    adapter.execute("SELECT 1")
    assert adapter.fetchall() == [[1]]
    with pytest.raises(
        UnsupportedQuery
    ):  # never "the first documents" for what it cannot run
        adapter.execute("SELECT a FROM people GROUP BY a")


def test_firestore_introspection_has_no_invented_collections_or_columns() -> None:
    from query_builder.connectors.firestore import FirestoreConnector

    client = FakeFirestore({"people": PEOPLE_DOCS[:1], "empty": []})
    snapshot = FirestoreConnector(connection=client).introspect_schema(
        filter_sensitive=False
    )
    assert set(snapshot["tables"]) == {"people", "empty"}
    cols = {c["name"]: c for c in snapshot["tables"]["people"]["columns"]}
    assert {"id", "name", "age"} <= set(cols) and cols["id"]["is_primary"] is True
    assert cols["age"]["data_type"] == "number"
    assert "user_id" not in cols and "data" not in cols  # were fabricated
    assert [c["name"] for c in snapshot["tables"]["empty"]["columns"]] == ["id"]
    assert (
        FirestoreConnector(connection=FakeFirestore({})).introspect_schema()["tables"]
        == {}
    )  # was {"users": ...}


class AsyncFakeQuery(FakeQuery):
    async def _stream(self) -> Any:
        for d in self.docs:
            yield d

    def stream(self) -> Any:  # type: ignore[override]
        return self._stream()

    def count(self) -> Any:
        class Agg:
            async def get(inner) -> Any:  # noqa: N805
                return [[MagicMock(value=len(self.docs))]]

        return Agg()


class AsyncFakeFirestore(FakeFirestore):
    def collection(self, name: str) -> AsyncFakeQuery:  # type: ignore[override]
        return AsyncFakeQuery(self.data[name], self.log)

    async def _collections(self) -> Any:
        for n in self.data:
            yield types.SimpleNamespace(id=n)

    def collections(self) -> Any:  # type: ignore[override]
        return self._collections()


def test_async_firestore_awaits_the_async_client(fake_firestore_filter: Any) -> None:
    from query_builder.connectors.firestore import AsyncFirestoreConnector

    async def body() -> None:
        conn = AsyncFirestoreConnector(
            connection=AsyncFakeFirestore({"people": PEOPLE_DOCS})
        )
        cols, rows, _ = await conn.execute_raw(
            "SELECT name FROM people WHERE age > %s ORDER BY age", [10]
        )
        assert cols == ["name"] and rows == [{"name": "alice"}, {"name": "bob"}]
        _, counted, _ = await conn.execute_raw("SELECT COUNT(*) AS n FROM people")
        assert counted == [{"n": 2}]
        _, one, _ = await conn.execute_raw("SELECT 1")
        assert one == [{"val": 1}]
        info = await conn.test_connection()
        assert info["status"] == "healthy"
        snapshot = await conn.introspect_schema(filter_sensitive=False)
        assert {"id", "name", "age"} <= {
            c["name"] for c in snapshot["tables"]["people"]["columns"]
        }
        _, names, _ = await conn.execute_raw("collections")
        assert names == [{"collection_name": "people"}]

    run(body())


def test_async_firestore_connection_paths() -> None:
    from query_builder.connectors.firestore import AsyncFirestoreConnector

    async def body() -> None:
        # a DB-API style connection (has cursor()) and a bare execute() object
        cur = MagicMock()
        cur.description = [("v",)]
        cur.fetchall.return_value = [[1]]
        conn = MagicMock()
        conn.cursor.return_value = cur
        assert (await AsyncFirestoreConnector(connection=conn).execute_raw("x", [1]))[
            1
        ] == [{"v": 1}]
        assert (await AsyncFirestoreConnector(connection=conn).execute_raw("x"))[1] == [
            {"v": 1}
        ]
        bare = MagicMock(spec=["execute"])
        res = MagicMock(spec=["description", "fetchall"])
        res.description, res.fetchall.return_value = [("c",)], [[2]]
        bare.execute.return_value = res
        assert (await AsyncFirestoreConnector(connection=bare).execute_raw("x"))[1] == [
            {"c": 2}
        ]
        snap = await AsyncFirestoreConnector(connection=bare).introspect_schema()
        assert isinstance(snap["tables"], dict)
        conn_cur = AsyncFirestoreConnector(connection=conn)
        assert isinstance((await conn_cur.introspect_schema())["tables"], dict)
        cur.close.assert_called()

        # awaitable collections() (older async clients)
        async def aw() -> list[Any]:
            return []

        old = MagicMock(spec=["collections"])
        old.collections.return_value = aw()
        assert (await AsyncFirestoreConnector(connection=old).test_connection())[
            "status"
        ] == "healthy"
        # introspection failure is wrapped
        broken = AsyncFakeFirestore({"p": []})
        broken.collections = MagicMock(side_effect=RuntimeError("down"))  # type: ignore[method-assign]
        with pytest.raises(IntrospectionError):
            await AsyncFirestoreConnector(connection=broken).introspect_schema()

    run(body())


def test_firestore_sync_unsupported_statement_is_an_error_through_the_connector() -> (
    None
):
    from query_builder.connectors.firestore import FirestoreConnector

    conn = FirestoreConnector(connection=FakeFirestore({"people": PEOPLE_DOCS}))
    with pytest.raises(UnsupportedQuery):
        conn.execute(
            sql="SELECT a FROM people WHERE a = 1 OR b = 2", validate_ast=False
        )


# ============================================================================
# Bigtable: same family of bugs (fixed 3-column shape, fixed 10 rows, "metrics" table),
# plus the async class used a data client that has no table listing at all.
# ============================================================================
class Cell:
    def __init__(self, value: bytes) -> None:
        self.value = value


class BtRow:
    def __init__(self, key: bytes, cells: dict[str, dict[bytes, list[Cell]]]) -> None:
        self.row_key, self.cells = key, cells


class FakeBtTable:
    def __init__(self, rows: list[BtRow], log: list[Any]) -> None:
        self.rows, self.log = rows, log

    def read_rows(self, **kwargs: Any) -> list[BtRow]:
        self.log.append(kwargs)
        return self.rows


class FakeBtInstance:
    def __init__(self, tables: dict[str, list[BtRow]]) -> None:
        self.tables, self.log = tables, []

    def table(self, name: str) -> FakeBtTable:
        return FakeBtTable(self.tables[name], self.log)

    def list_tables(self) -> list[Any]:
        return [types.SimpleNamespace(table_id=n) for n in self.tables]


def _bt_rows() -> list[BtRow]:
    def row(key: str, name: str, age: str, bad: bytes | None = None) -> BtRow:
        cells = {
            "cf": {
                b"name": [Cell(name.encode()), Cell(b"old")],
                b"age": [Cell(age.encode())],
            }
        }
        if bad is not None:
            cells["cf"][b"bin"] = [Cell(bad)]
        cells["cf"][b"empty"] = []
        return BtRow(key.encode(), cells)

    return [
        row("k1", "alice", "30"),
        row("k2", "bob", "45", bad=b"\xff\x00"),
        row("k3", "carol", "28"),
    ]


def test_bigtable_adapter_reads_rows_and_applies_the_query() -> None:
    from query_builder.connectors.bigtable import _BigtableCursorAdapter

    inst = FakeBtInstance({"people": _bt_rows()})
    adapter = _BigtableCursorAdapter(inst)
    adapter.execute(
        'SELECT "cf.name" AS name, "cf.age" AS age FROM people '
        'WHERE "cf.age" >= %s AND row_key >= %s AND row_key <= %s '
        'ORDER BY "cf.age" LIMIT 2',
        [28, "k1", "k9"],
    )
    assert adapter.description == [("name",), ("age",)]
    assert adapter.fetchall() == [["carol", "28"], ["alice", "30"]]  # numeric order
    assert inst.log[-1]["start_key"] == b"k1" and inst.log[-1]["end_key"] == b"k9"
    assert inst.log[-1]["end_inclusive"] is True

    adapter.execute("SELECT * FROM people WHERE row_key = 'k2'")
    names = [d[0] for d in adapter.description]
    assert names == ["row_key", "cf.name", "cf.age", "cf.bin"]
    assert adapter.fetchall() == [["k2", "bob", "45", "0xff00"]]  # non-text -> hex

    adapter.execute("SELECT COUNT(*) AS n FROM people WHERE \"cf.name\" LIKE 'a%'")
    assert adapter.fetchall() == [[1]]
    adapter.execute("SELECT row_key FROM people ORDER BY row_key DESC LIMIT 1 OFFSET 1")
    assert adapter.fetchall() == [["k2"]]
    adapter.execute("SELECT row_key FROM people WHERE row_key LIKE 'k%' LIMIT 3")
    assert inst.log[-1]["start_key"] == b"k" and inst.log[-1]["end_key"] == b"l"
    adapter.execute(
        "SELECT row_key FROM people WHERE row_key > 'k1' AND row_key < 'k3'"
    )
    assert (
        inst.log[-1]["start_key"] == b"k1\x00"
        and inst.log[-1]["end_inclusive"] is False
    )
    adapter.execute("SELECT row_key FROM people LIMIT 2")
    assert inst.log[-1]["limit"] == 2  # pushed down when nothing needs client-side work
    adapter.execute(
        "SELECT row_key FROM people WHERE row_key IN ('k1','k3') "
        'AND "cf.age" IS NOT NULL AND "cf.nope" IS NULL AND "cf.age" != 1 '
        'AND "cf.name" NOT IN (\'zed\') AND "cf.age" < 100 AND "cf.age" > 1 '
        'AND "cf.age" <= 99'
    )
    assert adapter.fetchall() == [["k1"], ["k3"]]
    adapter.execute("SELECT * FROM people WHERE row_key = 'nothing'")
    assert adapter.description == [("row_key",)] or adapter.fetchall() == []
    adapter.execute("SELECT 1")
    assert adapter.fetchall() == [[1]]
    adapter.execute(
        "SELECT row_key FROM people WHERE row_key LIKE '%'"
    )  # whole-table prefix
    with pytest.raises(UnsupportedQuery):
        adapter.execute("DELETE FROM people")


def test_bigtable_prefix_ending_in_0xff_has_no_upper_bound() -> None:
    from query_builder.connectors._sql_subset import Predicate, SubsetPlan
    from query_builder.connectors.bigtable import _key_range

    plan = SubsetPlan(
        table="t", columns=None, predicates=[Predicate("row_key", "prefix", "\xff")]
    )
    assert _key_range(plan)["start_key"] == "\xff".encode()


def test_bigtable_introspection_lists_real_tables_and_cell_columns() -> None:
    from query_builder.connectors.bigtable import BigtableConnector

    conn = BigtableConnector(
        connection=FakeBtInstance({"people": _bt_rows(), "empty": []})
    )
    snapshot = conn.introspect_schema(filter_sensitive=False)
    assert set(snapshot["tables"]) == {"people", "empty"}  # was {"metrics"} when empty
    people = [c["name"] for c in snapshot["tables"]["people"]["columns"]]
    assert people == ["row_key", "cf.age", "cf.bin", "cf.name"] or set(people) >= {
        "row_key",
        "cf.name",
        "cf.age",
    }
    assert [c["name"] for c in snapshot["tables"]["empty"]["columns"]] == ["row_key"]
    assert (
        BigtableConnector(connection=FakeBtInstance({})).introspect_schema()["tables"]
        == {}
    )


def test_async_bigtable_runs_the_sync_client_in_a_thread() -> None:
    from query_builder.connectors.bigtable import AsyncBigtableConnector

    inst = FakeBtInstance({"people": _bt_rows()})

    async def body() -> None:
        conn = AsyncBigtableConnector(connection=inst)
        cols, rows, _ = await conn.execute_raw(
            'SELECT "cf.name" AS name FROM people ORDER BY "cf.age" LIMIT 1'
        )
        assert cols == ["name"] and rows == [{"name": "carol"}]
        assert (await conn.test_connection())["status"] == "healthy"
        snapshot = await conn.introspect_schema(filter_sensitive=False)
        assert "people" in snapshot["tables"]
        cur = MagicMock()
        cur.description, cur.fetchall.return_value = [("v",)], [[1]]
        dbapi = MagicMock()
        dbapi.cursor.return_value = cur
        c2 = AsyncBigtableConnector(connection=dbapi)
        assert (await c2.execute_raw("x", [1]))[1] == [{"v": 1}]
        assert (await c2.execute_raw("x"))[1] == [{"v": 1}]
        assert isinstance((await c2.introspect_schema())["tables"], dict)
        broken = MagicMock(spec=["list_tables"])
        broken.list_tables.side_effect = RuntimeError("down")
        with pytest.raises(IntrospectionError):
            await AsyncBigtableConnector(connection=broken).introspect_schema()

    run(body())


def test_bigtable_connect_uses_the_sync_admin_client() -> None:
    from query_builder.connectors.bigtable import (
        AsyncBigtableConnector,
        BigtableConnector,
    )

    drv = MagicMock()
    drv.Client.return_value.instance.return_value = "instance"
    with patch.dict(sys.modules, {"google.cloud.bigtable": drv}):
        c = BigtableConnector(project_id="p", instance_id="i", admin=True, k=1)
        assert c.connect() == "instance"
        drv.Client.assert_called_with(project="p", admin=True, k=1)
        assert (
            run(AsyncBigtableConnector(project_id="p", instance_id="i").connect())
            == "instance"
        )
        drv.Client.side_effect = RuntimeError("no")
        with pytest.raises(ConnectionFailedError):
            BigtableConnector().connect()
        with pytest.raises(ConnectionFailedError):
            run(AsyncBigtableConnector().connect())


# ============================================================================
# ArangoDB: introspection listed only _key/_id (documents' real fields were invisible), the
# async class returned an EMPTY schema and ran the blocking driver on the event loop, the
# engine version was the literal "ArangoDB", AQL writes passed the SQL-shaped check.
# ============================================================================
class FakeArangoDb:
    """python-arango StandardDatabase stand-in answering the AQL the connector sends."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.aql = types.SimpleNamespace(execute=self._execute)

    def _execute(self, query: str, bind_vars: dict[str, Any] | None = None) -> Any:
        self.statements.append(query)
        if query.startswith("RETURN COLLECTIONS"):
            return iter(
                [[{"name": "people"}, {"name": "_system_coll"}, {"name": "empty"}]]
            )
        if "`people`" in query:
            return iter([{"name": "a", "age": 3, "tags": ["x"], "ok": True, "n": None}])
        if "`empty`" in query:
            return iter([{}])
        return iter([1])

    def version(self) -> str:
        return "3.12.4"


def test_arango_introspection_reports_real_fields_and_engine_version() -> None:
    from query_builder.connectors.arangodb import ArangoDBConnector

    conn = ArangoDBConnector(connection=FakeArangoDb())
    snapshot = conn.introspect_schema(filter_sensitive=False)
    assert set(snapshot["tables"]) == {"people", "empty"}
    cols = {c["name"]: c["data_type"] for c in snapshot["tables"]["people"]["columns"]}
    assert cols == {
        "_key": "string",
        "_id": "string",
        "name": "string",
        "age": "number",
        "tags": "array",
        "ok": "boolean",
        "n": "null",
    }
    assert conn.test_connection()["engine_version"] == "ArangoDB 3.12.4"
    bad = FakeArangoDb()
    bad.version = MagicMock(side_effect=RuntimeError("401"))  # type: ignore[method-assign]
    assert (
        ArangoDBConnector(connection=bad).test_connection()["engine_version"]
        == "ArangoDB"
    )
    bad.version = MagicMock(return_value=None)  # type: ignore[method-assign]
    assert (
        ArangoDBConnector(connection=bad).test_connection()["engine_version"]
        == "ArangoDB"
    )


def test_arango_native_db_object_introspection_samples_documents() -> None:
    from query_builder.connectors.introspection import introspect_arangodb

    class Coll:
        def all(self, limit: int) -> list[Any]:
            return [{"_key": "1", "a": None}, {"a": 5, "b": "x"}, "not-a-doc"]

    db = MagicMock(spec=["collections", "collection"])
    db.collections.return_value = [{"name": "docs"}]
    db.collection.return_value = Coll()
    cols = {
        c["name"]: c["data_type"]
        for c in introspect_arangodb(db, filter_sensitive=False)["tables"]["docs"][
            "columns"
        ]
    }
    assert cols["a"] == "number" and cols["b"] == "string"
    failing = MagicMock(spec=["collections", "collection"])
    failing.collections.return_value = [{"name": "docs"}]
    failing.collection.side_effect = RuntimeError("denied")  # sampling is best effort
    cols = introspect_arangodb(failing, filter_sensitive=False)["tables"]["docs"][
        "columns"
    ]
    assert [c["name"] for c in cols] == ["_key", "_id"]


def test_arango_adapter_refuses_aql_writes_below_the_ast_validator() -> None:
    from query_builder.connectors.arangodb import (
        ArangoDBConnector,
        _ArangoCursorAdapter,
    )

    db = FakeArangoDb()
    adapter = _ArangoCursorAdapter(db)
    for statement in (
        "FOR p IN people REMOVE p IN people",
        "FOR p IN people REPLACE p WITH {} IN people",
        "UPSERT {a: 1} INSERT {a: 1} UPDATE {} IN people",
    ):
        with pytest.raises(SecurityError):
            adapter.execute(statement)
    assert db.statements == []  # never reached the engine
    _ArangoCursorAdapter(db, read_only=False).execute(
        "FOR p IN people REMOVE p IN people"
    )
    assert len(db.statements) == 1
    # through the connector, with the AST validator OFF
    conn = ArangoDBConnector(connection=FakeArangoDb())
    with pytest.raises(SecurityError):
        conn.execute(sql="FOR p IN people REMOVE p IN people", validate_ast=False)
    assert conn._read_only() is True
    # heterogeneous documents: the column set is the union, not the first document's keys
    db2 = types.SimpleNamespace(
        aql=types.SimpleNamespace(
            execute=lambda q, bind_vars=None: iter([{"a": 1}, {"a": 2, "b": 3}])
        )
    )
    a2 = _ArangoCursorAdapter(db2)
    a2.execute("FOR d IN c RETURN d")
    assert a2.description == [("a",), ("b",)] and a2.fetchall() == [[1, None], [2, 3]]


def test_async_arango_is_not_empty_and_runs_off_the_event_loop() -> None:
    from query_builder.connectors.arangodb import AsyncArangoDBConnector

    async def body() -> None:
        conn = AsyncArangoDBConnector(connection=FakeArangoDb())
        info = await conn.test_connection()
        assert (
            info["engine_version"] == "ArangoDB 3.12.4" and info["status"] == "healthy"
        )
        snapshot = await conn.introspect_schema(filter_sensitive=False)
        assert "people" in snapshot["tables"]  # was always {}
        cols, rows, _ = await conn.execute_raw("RETURN 1")
        assert rows == [{"value": 1}] and cols == ["value"]
        with pytest.raises(SecurityError):
            await conn.execute_raw("FOR p IN people REMOVE p IN people")
        broken = FakeArangoDb()
        broken.aql = types.SimpleNamespace(
            execute=MagicMock(side_effect=RuntimeError("down"))
        )
        with pytest.raises(IntrospectionError):
            await AsyncArangoDBConnector(connection=broken).introspect_schema()

    run(body())


# ============================================================================
# SurrealDB: the connector passed `namespace=`/`database=` into Surreal(url, ...) (TypeError
# with the real SDK), never signed in or selected a namespace/database, doubled `/rpc`,
# misread the SDK >= 1.0 result shape (rows silently EMPTY), left RecordIDs as SDK objects,
# introspected tables without columns, and the async class used the blocking client.
# ============================================================================
class FakeSurrealClient:
    def __init__(self, url: str, **kw: Any) -> None:
        self.url, self.kw, self.calls = url, kw, []
        self.answers: dict[str, Any] = {}

    def signin(self, creds: dict[str, str]) -> None:
        self.calls.append(("signin", creds))

    def use(self, ns: str, db: str) -> None:
        self.calls.append(("use", ns, db))

    def query(self, sql: str, vars: Any = None) -> Any:  # noqa: A002
        self.calls.append(("query", sql, vars))
        for prefix, value in self.answers.items():
            if sql.startswith(prefix):
                return value
        return []

    def version(self) -> str:
        return "surrealdb-2.3.7"

    def close(self) -> None:
        self.calls.append(("close",))


class FakeRecordId:
    def __str__(self) -> str:
        return "people:1"


def _surreal_driver(client: Any, name: str = "Surreal") -> Any:
    drv = types.SimpleNamespace()
    setattr(
        drv, name, lambda url, **kw: client(url, **kw) if callable(client) else client
    )
    return drv


def test_surreal_connect_signs_in_selects_namespace_and_fixes_url() -> None:
    from query_builder.connectors.surrealdb import SurrealDBConnector

    made: list[FakeSurrealClient] = []

    def factory(url: str, **kw: Any) -> FakeSurrealClient:
        made.append(FakeSurrealClient(url, **kw))
        return made[-1]

    with patch.dict(sys.modules, {"surrealdb": _surreal_driver(factory)}):
        conn = SurrealDBConnector(
            url="ws://h:8000/rpc",
            namespace="ns",
            database="db",
            username="root",
            password="pw",
        )
        client = conn.connect()
    assert (
        client.url == "ws://h:8000" and client.kw == {}
    )  # no ns/db kwargs, no /rpc twice
    assert client.calls == [
        ("signin", {"username": "root", "password": "pw"}),
        ("use", "ns", "db"),
    ]
    assert "pw" not in repr(conn) and "pw" not in str(conn)

    class Failing(FakeSurrealClient):
        def signin(self, creds: dict[str, str]) -> None:
            raise RuntimeError("authentication failed")

    failing = Failing("ws://h:8000")
    with patch.dict(sys.modules, {"surrealdb": _surreal_driver(failing)}):
        with pytest.raises(ConnectionFailedError):
            SurrealDBConnector(username="root", password="bad").connect()
    assert ("close",) in failing.calls  # the half-open client is released
    # no credentials: nothing to sign in with; ws url without /rpc is untouched
    anon = FakeSurrealClient("ws://h:8000")
    with patch.dict(sys.modules, {"surrealdb": _surreal_driver(anon)}):
        SurrealDBConnector(url="ws://h:8000").connect()
    assert [c[0] for c in anon.calls] == ["use"]


def test_surreal_adapter_reads_both_sdk_result_shapes_and_plain_values() -> None:
    from query_builder.connectors.surrealdb import _SurrealCursorAdapter

    client = FakeSurrealClient("u")
    adapter = _SurrealCursorAdapter(client)
    rec = {"id": FakeRecordId(), "name": "a", "nested": {"k": [FakeRecordId(), 1]}}
    client.answers["SELECT"] = [rec, {"name": "b", "extra": 2}]  # SDK >= 1.0
    adapter.execute("SELECT * FROM people WHERE a = ? AND b = ?", [1, 2])
    assert adapter.description == [("id",), ("name",), ("nested",), ("extra",)]
    row = adapter.fetchone()
    assert row[0] == "people:1" and row[2] == {"k": ["people:1", 1]}
    assert client.calls[-1][1] == "SELECT * FROM people WHERE a = $p0 AND b = $p1"
    assert client.calls[-1][2] == {"p0": 1, "p1": 2}
    client.answers["SELECT"] = [{"result": [{"x": 1}], "status": "OK", "time": "1ms"}]
    adapter.execute("SELECT x FROM t", {"named": 1})  # legacy shape + named binds
    assert adapter.fetchall() == [[1]] and client.calls[-1][2] == {"named": 1}
    client.answers["SELECT"] = [{"result": 5, "status": "OK"}]
    adapter.execute("SELECT 5")
    assert adapter.fetchall() == [[5]]
    client.answers["SELECT"] = [{"result": None, "status": "OK"}]
    adapter.execute("SELECT nothing")
    assert adapter.fetchall() == []
    client.answers["SELECT"] = None
    adapter.execute("SELECT 1")  # health check: SELECT 1 is not SurrealQL
    assert client.calls[-1][1] == "RETURN 1"
    for write in ("DELETE people", "UPDATE people SET a = 1", "REMOVE TABLE people"):
        with pytest.raises(SecurityError):
            adapter.execute(write)
    exec_only = MagicMock(spec=["execute", "description", "fetchall"])
    exec_only.description, exec_only.fetchall.return_value = [("c",)], [(1,)]
    a2 = _SurrealCursorAdapter(exec_only)
    a2.execute("SELECT 1 AS c", [1])
    a2.execute("SELECT 1 AS c")
    assert a2.fetchall() == [(1,)]
    a3 = _SurrealCursorAdapter(object())
    a3.execute("SELECT 1")
    assert a3.description == []
    assert a3.fetchone() is None


def test_surreal_introspection_uses_info_for_db_and_samples_fields() -> None:
    from query_builder.connectors.surrealdb import SurrealDBConnector

    client = FakeSurrealClient("u")
    client.answers["INFO FOR DB"] = {
        "tables": {"people": "DEFINE TABLE people", "t2": ""}
    }
    client.answers["INFO FOR TABLE `people`"] = {
        "fields": {
            "name": "DEFINE FIELD name ON people TYPE string",
            "untyped": "DEFINE FIELD untyped ON people",
        }
    }
    client.answers["SELECT * FROM `people`"] = [
        {"id": FakeRecordId(), "name": "a", "age": 3, "untyped": 1.5}
    ]
    conn = SurrealDBConnector(connection=client)
    snapshot = conn.introspect_schema(filter_sensitive=False)
    cols = {c["name"]: c["data_type"] for c in snapshot["tables"]["people"]["columns"]}
    assert cols == {
        "id": "record",
        "name": "string",
        "untyped": "number",
        "age": "number",
    }
    assert [c["name"] for c in snapshot["tables"]["t2"]["columns"]] == ["id"]
    assert conn.test_connection()["engine_version"] == "surrealdb-2.3.7"
    client.version = None  # type: ignore[assignment] - an SDK without a usable version()
    assert conn.test_connection()["engine_version"] == "SurrealDB"
    with pytest.raises(IntrospectionError):
        SurrealDBConnector(
            connection=MagicMock(
                spec=["query"], query=MagicMock(side_effect=RuntimeError("x"))
            )
        ).introspect_schema()


class AsyncFakeSurreal(FakeSurrealClient):
    async def connect(self) -> None:
        self.calls.append(("connect",))

    async def signin(self, creds: dict[str, str]) -> None:  # type: ignore[override]
        self.calls.append(("signin", creds))

    async def use(self, ns: str, db: str) -> None:  # type: ignore[override]
        self.calls.append(("use", ns, db))

    async def query(self, sql: str, vars: Any = None) -> Any:  # type: ignore[override]  # noqa: A002
        return FakeSurrealClient.query(self, sql, vars)

    async def version(self) -> str:  # type: ignore[override]
        return "surrealdb-2.3.7"

    async def close(self) -> None:  # type: ignore[override]
        self.calls.append(("close",))


def test_async_surreal_uses_the_async_sdk_and_awaits_it() -> None:
    from query_builder.connectors.surrealdb import AsyncSurrealDBConnector

    client = AsyncFakeSurreal("u")
    client.answers["SELECT"] = [{"name": "a"}]
    client.answers["INFO FOR DB"] = {"tables": {"people": ""}}
    client.answers["INFO FOR TABLE"] = {}

    async def body() -> None:
        drv = _surreal_driver(client, name="AsyncSurreal")
        with patch.dict(sys.modules, {"surrealdb": drv}):
            conn = AsyncSurrealDBConnector(
                url="ws://h:8000/rpc",
                namespace="n",
                database="d",
                username="u",
                password="p",
            )
            info = await conn.test_connection()
            assert (
                info["engine_version"] == "surrealdb-2.3.7" and info["namespace"] == "n"
            )
            assert [c[0] for c in client.calls[:3]] == ["connect", "signin", "use"]
            cols, rows, _ = await conn.execute_raw(
                "SELECT name FROM people WHERE a = ?", [1]
            )
            assert cols == ["name"] and rows == [{"name": "a"}]
            snapshot = await conn.introspect_schema(filter_sensitive=False)
            assert (
                "people" in snapshot["tables"]
            )  # was always {} (default async fallback)
            with pytest.raises(SecurityError):
                await conn.execute_raw("DELETE people")
            await conn.close()

        # failing sign-in releases the client and surfaces a connection error
        class Bad(AsyncFakeSurreal):
            async def signin(self, creds: dict[str, str]) -> None:  # type: ignore[override]
                raise RuntimeError("nope")

        bad = Bad("u")
        with patch.dict(
            sys.modules, {"surrealdb": _surreal_driver(bad, "AsyncSurreal")}
        ):
            with pytest.raises(ConnectionFailedError):
                await AsyncSurrealDBConnector(username="u", password="p").connect()
        assert ("close",) in bad.calls
        # blocking-only SDK object (no connect/signin): still works; no creds -> no signin
        sync = FakeSurrealClient("u")
        with patch.dict(sys.modules, {"surrealdb": _surreal_driver(sync, "Surreal")}):
            c = AsyncSurrealDBConnector()
            assert await c.connect() is sync
            assert await c.test_connection()
        # introspection failure is wrapped
        broken = FakeSurrealClient("u")
        broken.query = MagicMock(side_effect=RuntimeError("down"))  # type: ignore[method-assign]
        with pytest.raises(IntrospectionError):
            await AsyncSurrealDBConnector(connection=broken).introspect_schema()
        # fallback to driver.connect when the SDK has no Surreal class
        fb = types.SimpleNamespace(connect=lambda url: FakeSurrealClient(url))
        with patch.dict(sys.modules, {"surrealdb": fb}):
            assert isinstance(
                await AsyncSurrealDBConnector().connect(), FakeSurrealClient
            )
            assert isinstance(SurrealDBConnector().connect(), FakeSurrealClient)

    from query_builder.connectors.surrealdb import SurrealDBConnector

    run(body())


# ============================================================================
# Memgraph: introspection fabricated a "Node" label with id/name/user_id columns (and asked
# for mg.labels(), which does not exist); the async class never awaited its async driver;
# SET / MERGE / REMOVE passed the read-only check (Bolt access modes are ignored by Memgraph).
# ============================================================================
class FakeMgResult:
    def __init__(self, keys: list[str], rows: list[list[Any]]) -> None:
        self._keys, self._rows = keys, rows

    def keys(self) -> list[str]:
        return self._keys

    def __iter__(self) -> Any:
        return iter(self._rows)

    def values(self) -> list[list[Any]]:
        return self._rows


class FakeMgSession:
    def __init__(self, answers: dict[str, tuple[list[str], list[list[Any]]]]) -> None:
        self.answers, self.ran = answers, []

    def run(self, query: str, parameters: Any = None) -> FakeMgResult:
        self.ran.append(query)
        for prefix, (keys, rows) in self.answers.items():
            if query.startswith(prefix):
                return FakeMgResult(keys, rows)
        raise RuntimeError(f"unexpected query {query}")

    def close(self) -> None:
        pass


class FakeMgDriver:
    def __init__(self, answers: dict[str, tuple[list[str], list[list[Any]]]]) -> None:
        self.session_obj = FakeMgSession(answers)

    def session(self) -> FakeMgSession:
        return self.session_obj

    def close(self) -> None:
        pass


MG_SCHEMA = {
    "CALL schema.node_type_properties()": (
        ["nodeLabels", "propertyName", "propertyTypes"],
        [[["Person"], "name", ["String"]], [["Person"], "age", ["Integer"]]],
    ),
    "SHOW VERSION": (["version"], [["2.21.0"]]),
    "RETURN 1": (["val"], [[1]]),
}


def test_memgraph_introspection_is_not_fabricated() -> None:
    from query_builder.connectors.memgraph import MemgraphConnector

    drv = FakeMgDriver(MG_SCHEMA)
    conn = MemgraphConnector(connection=drv)
    snapshot = conn.introspect_schema(filter_sensitive=False)
    cols = {c["name"]: c["data_type"] for c in snapshot["tables"]["Person"]["columns"]}
    assert cols == {"name": "string", "age": "integer"}
    assert set(snapshot["tables"]) == {"Person"}  # no invented "Node" label
    assert conn.test_connection()["engine_version"] == "Memgraph 2.21.0"
    empty = MemgraphConnector(
        connection=FakeMgDriver(
            {"CALL schema.node_type_properties()": (["nodeLabels"], [])}
        )
    )
    assert empty.introspect_schema()["tables"] == {}


def test_memgraph_write_statements_are_refused_client_side() -> None:
    from query_builder.connectors.memgraph import MemgraphConnector

    drv = FakeMgDriver(MG_SCHEMA)
    conn = MemgraphConnector(connection=drv)
    for statement in (
        "MATCH (p:Person) SET p.age = 0",
        "MERGE (n:X {id: 1})",
        "MATCH (p:Person) REMOVE p.age",
        "CREATE (n:Hacked)",
        "MATCH (n) DETACH DELETE n",
        "CALL mg.load_all()",
    ):
        with pytest.raises(SecurityError):
            conn.execute(sql=statement, validate_ast=False)
    assert drv.session_obj.ran == []
    # SELECT 1 (the generic health probe) is mapped to a valid Cypher statement
    assert conn.execute(sql="SELECT 1", validate_ast=False)["rows"] == [{"val": 1}]


class AsyncFakeMgSession:
    def __init__(self, answers: dict[str, tuple[list[str], list[list[Any]]]]) -> None:
        self.answers = answers

    async def __aenter__(self) -> AsyncFakeMgSession:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def run(self, query: str, parameters: Any = None) -> Any:
        for prefix, (keys, rows) in self.answers.items():
            if query.startswith(prefix):
                return AsyncFakeMgResult(keys, rows)
        raise RuntimeError(f"unexpected query {query}")


class AsyncFakeMgResult:
    def __init__(self, keys: list[str], rows: list[list[Any]]) -> None:
        self._keys = keys
        self._rows = [types.SimpleNamespace(values=lambda r=r: r) for r in rows]

    def keys(self) -> list[str]:
        return self._keys

    def __aiter__(self) -> Any:
        async def gen() -> Any:
            for r in self._rows:
                yield r

        return gen()


class AsyncFakeMgDriver:
    def __init__(self, answers: dict[str, tuple[list[str], list[list[Any]]]]) -> None:
        self.answers = answers

    async def verify_connectivity(self) -> None:
        return None

    def session(self) -> AsyncFakeMgSession:
        return AsyncFakeMgSession(self.answers)

    async def close(self) -> None:
        return None


def test_async_memgraph_really_awaits_the_async_driver() -> None:
    from query_builder.connectors.memgraph import AsyncMemgraphConnector

    async def body() -> None:
        conn = AsyncMemgraphConnector(connection=AsyncFakeMgDriver(MG_SCHEMA))
        info = await conn.test_connection()
        assert info["engine_version"] == "Memgraph 2.21.0"
        cols, rows, _ = await conn.execute_raw("RETURN 1 AS val")
        assert cols == ["val"] and rows == [{"val": 1}]
        _, rows, _ = await conn.execute_raw("SELECT 1")
        assert rows == [{"val": 1}]
        snapshot = await conn.introspect_schema(filter_sensitive=False)
        assert set(snapshot["tables"]) == {"Person"}
        with pytest.raises(SecurityError):
            await conn.execute_raw("MATCH (n) SET n.x = 1")
        await conn.close()
        # fallback queries when the schema procedure is missing
        fb = AsyncMemgraphConnector(
            connection=AsyncFakeMgDriver(
                {
                    "MATCH (n) UNWIND": (["label"], [["Person"]]),
                    "MATCH (n:`Person`)": (["props"], [[{"name": "a"}]]),
                }
            )
        )
        snap = await fb.introspect_schema(filter_sensitive=False)
        assert [c["name"] for c in snap["tables"]["Person"]["columns"]] == ["name"]
        # a failing introspection query is wrapped
        broken = AsyncMemgraphConnector(connection=AsyncFakeMgDriver({}))
        with pytest.raises(IntrospectionError):
            await broken.introspect_schema()
        # the version probe failing keeps the plain name
        nover = AsyncMemgraphConnector(
            connection=AsyncFakeMgDriver({"RETURN 1": (["val"], [[1]])})
        )
        assert (await nover.test_connection())["engine_version"] == "Memgraph"
        # non-async connection objects keep the DB-API path
        cur = MagicMock()
        cur.description, cur.fetchall.return_value = [("v",)], [[1]]
        dbapi = MagicMock()
        dbapi.cursor.return_value = cur
        c2 = AsyncMemgraphConnector(connection=dbapi)
        assert (await c2.execute_raw("RETURN 1", [1]))[1] == [{"v": 1}]
        assert isinstance((await c2.introspect_schema())["tables"], dict)
        sess = FakeMgSession({"RETURN 1": (["val"], [[1]])})
        raw = AsyncMemgraphConnector(connection=sess)
        assert (await raw.execute_raw("RETURN 1"))[1] == [{"val": 1}]

    run(body())


# ============================================================================
# ScyllaDB: `SELECT 1` (the generic health probe) is not CQL; BATCH/APPLY/TRUNCATE were not
# covered by the SQL-shaped read-only check; the engine version was a literal.
# ============================================================================
class FakeCqlSession:
    def __init__(self) -> None:
        self.ran: list[str] = []

    def execute(self, query: str, params: Any = None) -> Any:
        self.ran.append(query)
        rs = types.SimpleNamespace(
            column_names=["release_version"], all=lambda: [("6.2.0",)]
        )
        return rs


def test_scylla_health_probe_is_valid_cql_and_reports_the_version() -> None:
    from query_builder.connectors.scylladb import ScyllaDBConnector

    session = FakeCqlSession()
    conn = ScyllaDBConnector(connection=session)
    info = conn.test_connection()
    assert info["engine_version"] == "Scylla/Cassandra 6.2.0"
    assert all(not q.upper().startswith("SELECT 1") for q in session.ran)
    assert "FROM system.local" in session.ran[0]


def test_scylla_blocks_cql_batches_and_truncates_below_the_validator() -> None:
    from query_builder.connectors.scylladb import (
        ScyllaDBConnector,
        _ScyllaCursorAdapter,
    )

    session = FakeCqlSession()
    conn = ScyllaDBConnector(connection=session)
    for statement in (
        "BEGIN BATCH INSERT INTO t (a) VALUES (1) APPLY BATCH",
        "TRUNCATE t",
        "DROP TABLE t",
    ):
        with pytest.raises(SecurityError):
            conn.execute(sql=statement, validate_ast=False)
    assert session.ran == []
    _ScyllaCursorAdapter(session, read_only=False).execute("TRUNCATE t")
    assert session.ran == ["TRUNCATE t"]
    assert conn._read_only() is True


# ============================================================================
# DynamoDB: introspection listed only the KEY attributes (AttributeDefinitions), ExecuteStatement
# pages (NextToken) were silently dropped, lists/maps/sets were mis-decoded.
# ============================================================================
class FakeDynamo:
    def __init__(self) -> None:
        self.statements: list[dict[str, Any]] = []

    def list_tables(self) -> dict[str, Any]:
        return {"TableNames": ["people"]}

    def describe_table(self, TableName: str) -> dict[str, Any]:  # noqa: N803
        return {
            "Table": {
                "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
                "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "N"}],
            }
        }

    def scan(self, TableName: str, Limit: int) -> dict[str, Any]:  # noqa: N803
        return {
            "Items": [
                {
                    "id": {"N": "1"},
                    "name": {"S": "a"},
                    "tags": {"SS": ["x"]},
                    "m": {"M": {"k": {"BOOL": True}}},
                    "user_id": {"S": "u"},
                    "weird": {},
                }
            ]
        }

    def execute_statement(self, **kw: Any) -> dict[str, Any]:
        self.statements.append(kw)
        if "NextToken" not in kw:
            return {"Items": [{"id": {"N": "1"}}], "NextToken": "t1"}
        return {"Items": [{"id": {"N": "2"}, "l": {"L": [{"N": "1.5"}, {"S": "z"}]}}]}


def test_dynamodb_introspection_includes_non_key_attributes() -> None:
    from query_builder.connectors.dynamodb import DynamoDBConnector

    snapshot = DynamoDBConnector(client=FakeDynamo()).introspect_schema(
        filter_sensitive=False
    )
    cols = {c["name"]: c for c in snapshot["tables"]["people"]["columns"]}
    assert {"id", "name", "tags", "m", "user_id", "weird"} <= set(cols)
    assert cols["id"]["is_primary"] is True and cols["id"]["data_type"] == "number"
    assert cols["name"]["data_type"] == "string" and cols["name"]["is_primary"] is False
    assert cols["tags"]["data_type"] == "string_set" and cols["m"]["data_type"] == "map"
    assert snapshot["tables"]["people"]["has_user_id"] is True
    client = FakeDynamo()
    client.scan = MagicMock(side_effect=RuntimeError("AccessDenied"))  # type: ignore[method-assign]
    only_keys = DynamoDBConnector(client=client).introspect_schema(
        filter_sensitive=False
    )
    assert [c["name"] for c in only_keys["tables"]["people"]["columns"]] == ["id"]


def test_dynamodb_follows_next_token_and_decodes_collections() -> None:
    from query_builder.connectors.dynamodb import DynamoDBConnector

    client = FakeDynamo()
    conn = DynamoDBConnector(client=client)
    result = conn.execute(sql='SELECT * FROM "people"', validate_ast=False)
    assert [r["id"] for r in result["rows"]] == [1, 2]  # was only page one
    assert result["rows"][1]["l"] == [1.5, "z"]
    assert result["columns"] == ["id", "l"]  # union of keys, not the first row's
    assert client.statements[1]["NextToken"] == "t1"
    assert DynamoDBConnector._unmarshal_item(
        {"ns": {"NS": ["1", "2.5"]}, "m": {"M": {"a": {"S": "x"}}}, "b": {"B": b"z"}}
    ) == {"ns": [1, 2.5], "m": {"a": "x"}, "b": b"z"}
    # paging stops once the row cap is exceeded (never an unbounded loop)
    endless = FakeDynamo()
    endless.execute_statement = MagicMock(  # type: ignore[method-assign]
        return_value={"Items": [{"x": {"N": "1"}}], "NextToken": "more"}
    )
    from query_builder.config import SecurityConfig

    capped_cfg = SecurityConfig()  # never mutate the shared global config
    capped_cfg.execution.max_rows_limit = 1
    capped = DynamoDBConnector(client=endless, security=capped_cfg)
    result = capped.execute(sql='SELECT x FROM "t"', validate_ast=False)
    assert len(result["rows"]) == 1 and result.get("truncated") is True
    assert endless.execute_statement.call_count == 2


# ============================================================================
# Spanner: connect() passed `instance=`/`database=` keywords the DB-API does not have
# (TypeError on every connect) and nothing made the session read-only.
# ============================================================================
def test_spanner_connect_uses_the_dbapi_positional_signature_and_read_only() -> None:
    from query_builder.connectors.spanner import SpannerConnector

    dbapi = types.ModuleType("google.cloud.spanner_dbapi")
    calls: list[Any] = []

    def connect(instance_id: str, database_id: str, **kw: Any) -> Any:
        calls.append((instance_id, database_id, kw))
        return types.SimpleNamespace(read_only=False)

    dbapi.connect = connect  # type: ignore[attr-defined]
    with patch.dict(sys.modules, {"google.cloud.spanner_dbapi": dbapi}):
        conn = SpannerConnector(instance_id="i", database_id="d", project="p")
        connection = conn.connect()
    assert calls == [("i", "d", {"project": "p"})]
    assert connection.read_only is True  # snapshot (read-only) transactions
    assert SpannerConnector.read_only_support == "enforced"


# ============================================================================
# Couchbase: bind parameters were DROPPED (queries with `?` were sent unbound), relative
# keyspaces (`FROM people`) had no bucket/scope context, introspection listed buckets
# instead of the bucket's collections, SQL++ writes (UPSERT/MERGE) passed the read-only check.
# ============================================================================
class FakeCbCluster:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.answers: dict[str, list[Any]] = {}

    def query(self, sql: str, *opts: Any) -> list[Any]:
        self.calls.append((sql, opts))
        for prefix, rows in self.answers.items():
            if sql.startswith(prefix):
                return rows
        return []

    def close(self) -> None:
        self.calls.append(("close", ()))


@pytest.fixture
def fake_cb_options() -> Any:
    mod = types.ModuleType("couchbase.options")

    class QueryOptions:
        def __init__(self, **kw: Any) -> None:
            self.kw = kw

    mod.QueryOptions = QueryOptions  # type: ignore[attr-defined]
    with patch.dict(
        sys.modules,
        {"couchbase": types.ModuleType("couchbase"), "couchbase.options": mod},
    ):
        yield


def test_couchbase_binds_parameters_and_sets_the_bucket_scope_context(
    fake_cb_options: Any,
) -> None:
    from query_builder.connectors.couchbase import CouchbaseConnector

    cluster = FakeCbCluster()
    cluster.answers["SELECT"] = [{"name": "alice", "age": 30}]
    conn = CouchbaseConnector(
        connection=types.SimpleNamespace(cursor=None), bucket_name="b", scope_name="s"
    )
    from query_builder.connectors.couchbase import _CouchbaseClient

    conn = CouchbaseConnector(
        connection=_CouchbaseClient(cluster, conn._query_context(), True),
        bucket_name="b",
        scope_name="s",
    )
    result = conn.execute(sql="SELECT name, age FROM people WHERE age > ?", params=[21])
    assert result["rows"] == [{"name": "alice", "age": 30}]
    sql, opts = cluster.calls[-1]
    assert sql == "SELECT name, age FROM people WHERE age > ?"
    assert opts[0].kw == {
        "query_context": "default:`b`.`s`",
        "positional_parameters": [21],  # was dropped: the query went out unbound
    }


def test_couchbase_refuses_sqlpp_writes_even_without_the_ast_validator() -> None:
    from query_builder.connectors.couchbase import CouchbaseConnector, _CouchbaseCursor

    cluster = FakeCbCluster()
    conn = CouchbaseConnector(
        connection=types.SimpleNamespace(cursor=lambda: _CouchbaseCursor(cluster))
    )
    for statement in (
        "UPSERT INTO people (KEY, VALUE) VALUES ('k', {})",
        "MERGE INTO people t USING [{'k': 'p1'}] s ON KEY s.k WHEN MATCHED THEN DELETE",
        "DELETE FROM people",
        "DROP COLLECTION people",
    ):
        with pytest.raises(SecurityError):
            conn.execute(sql=statement, validate_ast=False)
    assert cluster.calls == []
    _CouchbaseCursor(cluster, read_only=False).execute("DELETE FROM people")
    assert len(cluster.calls) == 1
    assert conn._read_only() is True


def test_couchbase_introspection_lists_the_buckets_collections_and_reports_version() -> (
    None
):
    from query_builder.connectors.couchbase import CouchbaseConnector, _CouchbaseClient

    cluster = FakeCbCluster()
    cluster.answers["SELECT name FROM system:keyspaces"] = [{"name": "people"}]
    cluster.answers["INFER `b`.`s`.`people`"] = [
        [
            {
                "properties": {
                    "id": {"type": "number"},
                    "name": {"type": ["string", "null"]},
                }
            }
        ]
    ]
    cluster.answers["SELECT version()"] = [{"v": "7.6.2-3721-community"}]
    conn = CouchbaseConnector(
        connection=_CouchbaseClient(cluster), bucket_name="b'x", scope_name="s"
    )
    # quotes in the bucket name cannot break out of the keyspace filter
    conn.introspect_schema()
    assert "`bucket` = 'b''x'" in cluster.calls[0][0]
    conn = CouchbaseConnector(
        connection=_CouchbaseClient(cluster), bucket_name="b", scope_name="s"
    )
    snapshot = conn.introspect_schema(filter_sensitive=False)
    cols = {c["name"]: c["data_type"] for c in snapshot["tables"]["people"]["columns"]}
    assert cols == {"id": "number", "name": "string|null"}
    assert conn.test_connection()["engine_version"] == "Couchbase 7.6.2-3721-community"


# ============================================================================
# Cosmos DB: the connector only ever held a CLIENT, which cannot run queries, so every query
# returned NO ROWS silently; introspection invented an "items" container and fixed
# id/_rid/_ts columns; the async class used the blocking client.
# ============================================================================
class FakeCosmosContainer:
    def __init__(self, docs: list[Any], log: list[Any]) -> None:
        self.docs, self.log = docs, log
        self.id = "people"

    def query_items(self, query: str, parameters: Any = None, **kw: Any) -> Any:
        self.log.append((query, parameters, kw))
        return iter(self.docs)


class FakeCosmosDatabase:
    def __init__(self, containers: dict[str, list[Any]], log: list[Any]) -> None:
        self.containers, self.log = containers, log

    def get_container_client(self, name: str) -> FakeCosmosContainer:
        self.log.append(("container", name))
        return FakeCosmosContainer(self.containers[name], self.log)

    def list_containers(self) -> list[dict[str, str]]:
        return [{"id": n} for n in self.containers]

    def read(self) -> dict[str, str]:
        self.log.append(("read_db",))
        return {"id": "db"}


class FakeCosmosClient:
    def __init__(self, containers: dict[str, list[Any]]) -> None:
        self.containers, self.log = containers, []

    def get_database_client(self, name: str) -> FakeCosmosDatabase:
        self.log.append(("database", name))
        return FakeCosmosDatabase(self.containers, self.log)


def test_cosmos_runs_the_query_against_the_container_named_in_from() -> None:
    from query_builder.connectors.cosmosdb import (
        CosmosDBConnector,
        _CosmosDBCursorAdapter,
        container_of,
    )

    docs = [
        {"id": "1", "name": "alice", "age": 30, "ref": object.__new__(FakeRecordId)},
        {"id": "2", "name": "bob", "extra": [1]},
    ]
    client = FakeCosmosClient({"people": docs})
    conn = CosmosDBConnector(connection=client, database="db")
    result = conn.execute(
        sql="SELECT * FROM people p WHERE p.age > @param",
        params=[21],
        validate_ast=False,
    )
    assert [r["name"] for r in result["rows"]] == ["alice", "bob"]
    assert result["rows"][0]["ref"] == "people:1"  # SDK objects -> plain values
    assert result["columns"] == ["id", "name", "age", "ref", "extra"]
    query, parameters, kw = client.log[-1]
    assert query == "SELECT * FROM people p WHERE p.age > @p0"
    assert parameters == [{"name": "@p0", "value": 21}]
    assert kw == {"enable_cross_partition_query": True}
    assert ("container", "people") in client.log and ("database", "db") in client.log
    # a statement that names no container cannot run: error, not "no rows"
    adapter = _CosmosDBCursorAdapter(client, database="db")
    from query_builder.connectors.base import QueryExecutionError

    with pytest.raises(QueryExecutionError, match="needs a container"):
        adapter.execute("SELECT VALUE 1")
    with pytest.raises(SecurityError):
        adapter.execute("DELETE FROM people")
    assert container_of('SELECT 1 FROM "my-coll" c') == "my-coll"
    assert container_of("SELECT 1 FROM `bt` c") == "bt"
    assert container_of("SELECT 1 FROM [x y] c") == "x y"
    assert container_of("SELECT 1") is None
    scalar = _CosmosDBCursorAdapter(FakeCosmosContainer([1, 2], []))
    scalar.execute("SELECT VALUE c.n FROM c")
    assert scalar.description == [("value",)] and scalar.fetchall() == [[1], [2]]
    empty = _CosmosDBCursorAdapter(FakeCosmosContainer([], []))
    empty.execute("SELECT * FROM c WHERE false")
    assert empty.description == []


def test_cosmos_health_check_needs_no_container() -> None:
    from query_builder.connectors.cosmosdb import CosmosDBConnector

    client = FakeCosmosClient({"people": []})
    info = CosmosDBConnector(connection=client, database="db").test_connection()
    assert info["status"] == "healthy" and ("read_db",) in client.log
    cur = MagicMock(spec=["execute", "fetchone", "close"])
    info = CosmosDBConnector(cursor=cur).test_connection()  # DB-API style delegate
    assert info["status"] == "healthy"
    cur.execute.assert_called_with("SELECT 1")
    dbapi = MagicMock(spec=["cursor"])
    dbapi.cursor.return_value = cur
    assert CosmosDBConnector(connection=dbapi).test_connection()["status"] == "healthy"


def test_cosmos_introspection_reports_containers_and_attributes_only() -> None:
    from query_builder.connectors.cosmosdb import CosmosDBConnector

    docs = [{"id": "1", "name": "a", "age": 3, "_rid": "x", "_ts": 1, "user_id": "u"}]
    client = FakeCosmosClient({"people": docs, "empty": []})
    snapshot = CosmosDBConnector(connection=client, database="db").introspect_schema(
        filter_sensitive=False
    )
    cols = {c["name"]: c["data_type"] for c in snapshot["tables"]["people"]["columns"]}
    assert cols == {
        "id": "string",
        "name": "string",
        "age": "number",
        "user_id": "string",
    }
    assert snapshot["tables"]["people"]["has_user_id"] is True
    assert [c["name"] for c in snapshot["tables"]["empty"]["columns"]] == ["id"]
    assert (
        CosmosDBConnector(
            connection=FakeCosmosClient({}), database="db"
        ).introspect_schema()["tables"]
        == {}
    )  # was {"items": ...}


class AsyncCosmosItems:
    def __init__(self, docs: list[Any]) -> None:
        self.docs = docs

    def __aiter__(self) -> Any:
        async def gen() -> Any:
            for d in self.docs:
                yield d

        return gen()


class AsyncCosmosContainer(FakeCosmosContainer):
    def query_items(self, query: str, parameters: Any = None, **kw: Any) -> Any:
        self.log.append((query, parameters, kw))
        return AsyncCosmosItems(self.docs)


class AsyncCosmosDatabase(FakeCosmosDatabase):
    def get_container_client(self, name: str) -> AsyncCosmosContainer:  # type: ignore[override]
        return AsyncCosmosContainer(self.containers[name], self.log)

    def list_containers(self) -> Any:  # type: ignore[override]
        return AsyncCosmosItems([{"id": n} for n in self.containers])

    async def read(self) -> dict[str, str]:  # type: ignore[override]
        self.log.append(("read_db",))
        return {"id": "db"}


class AsyncCosmosClient(FakeCosmosClient):
    def get_database_client(self, name: str) -> AsyncCosmosDatabase:  # type: ignore[override]
        return AsyncCosmosDatabase(self.containers, self.log)


def test_async_cosmos_awaits_the_aio_client() -> None:
    from query_builder.connectors.cosmosdb import AsyncCosmosDBConnector

    docs = [{"id": "1", "name": "alice"}]

    async def body() -> None:
        client = AsyncCosmosClient({"people": docs})
        conn = AsyncCosmosDBConnector(connection=client, database="db")
        cols, rows, _ = await conn.execute_raw(
            "SELECT c.name FROM people c WHERE c.age > @param", [3]
        )
        assert cols == ["id", "name"] and rows == [{"id": "1", "name": "alice"}]
        # the aio SDK has no enable_cross_partition_query argument
        assert client.log[-1] == (
            "SELECT c.name FROM people c WHERE c.age > @p0",
            [{"name": "@p0", "value": 3}],
            {},
        )
        assert (await conn.test_connection())["status"] == "healthy"
        assert ("read_db",) in client.log
        snapshot = await conn.introspect_schema(filter_sensitive=False)
        assert {"id", "name"} <= {
            c["name"] for c in snapshot["tables"]["people"]["columns"]
        }
        with pytest.raises(SecurityError):
            await conn.execute_raw("DELETE FROM people")
        # the blocking SDK object also works (plain iterators)
        sync_client = FakeCosmosClient({"people": docs})
        c2 = AsyncCosmosDBConnector(connection=sync_client, database="db")
        assert (await c2.execute_raw("SELECT * FROM people"))[1][0]["name"] == "alice"
        assert (await c2.test_connection())["status"] == "healthy"
        assert (
            "people" in (await c2.introspect_schema(filter_sensitive=False))["tables"]
        )
        # DB-API style delegate
        cur = MagicMock(spec=["execute", "description", "fetchall"])
        cur.description, cur.fetchall.return_value = [("v",)], [[1]]
        c3 = AsyncCosmosDBConnector(connection=cur)
        assert (await c3.execute_raw("SELECT 1"))[1] == [{"v": 1}]
        assert (await c3.test_connection())["status"] == "healthy"
        assert isinstance((await c3.introspect_schema())["tables"], dict)
        broken = FakeCosmosClient({})
        broken.get_database_client = MagicMock(side_effect=RuntimeError("down"))  # type: ignore[method-assign]
        with pytest.raises(IntrospectionError):
            await AsyncCosmosDBConnector(connection=broken).introspect_schema()
        # connection: prefers azure.cosmos.aio, reports failures
        aio = types.ModuleType("azure.cosmos.aio")
        aio.CosmosClient = lambda endpoint, credential, **kw: (
            "aio",
            endpoint,
            credential,
        )  # type: ignore[attr-defined]
        with patch.dict(sys.modules, {"azure.cosmos.aio": aio}):
            got = await AsyncCosmosDBConnector(endpoint="http://x", key="k").connect()
        assert got == ("aio", "http://x", "k")
        with patch.dict(
            sys.modules,
            {
                "azure.cosmos.aio": None,
                "azure.cosmos": None,
                "azure.cosmos.cosmos_client": None,
            },
        ):
            from query_builder.connectors.base import DriverNotInstalledError

            with pytest.raises(DriverNotInstalledError):
                await AsyncCosmosDBConnector().connect()

    run(body())


def test_spanner_primary_key_is_read_from_the_primary_key_index() -> None:
    from query_builder.connectors.spanner import SpannerConnector

    def snapshot() -> dict[str, Any]:
        return {
            "tables": {
                "t": {
                    "name": "t",
                    "columns": [
                        {"name": "id", "is_primary": True},  # the generic GUESS
                        {"name": "k", "is_primary": False},
                    ],
                }
            }
        }

    cur = MagicMock()
    cur.fetchall.return_value = [("t", "k")]
    conn = SpannerConnector(cursor=cur)
    with patch(
        "query_builder.connectors.spanner.introspect_information_schema",
        side_effect=lambda *a, **k: snapshot(),
    ):
        cols = conn.introspect_schema()["tables"]["t"]["columns"]
        assert [(c["name"], c["is_primary"]) for c in cols] == [
            ("id", False),
            ("k", True),
        ]
        cur.execute.side_effect = RuntimeError("no index_columns")
        cols = conn.introspect_schema()["tables"]["t"][
            "columns"
        ]  # keeps the generic answer
        assert cols[0]["is_primary"] is True
