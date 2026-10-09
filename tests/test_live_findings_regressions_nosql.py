"""
Regression tests for defects the live suite found in the search / document /
key-value / graph / native-protocol connectors (no services needed: the vendor
clients are replaced by small fakes that have the real clients' shape).
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from query_builder.compiler import QueryCompiler
from query_builder.connectors.base import IntrospectionError
from query_builder.connectors.clickhouse_native import (
    ClickHouseNativeConnector,
    _bind_positional,
    _ClickHouseNativeCursorAdapter,
    _DetachedCursor,
)
from query_builder.connectors.elasticsearch import (
    ElasticsearchConnector,
    ElasticsearchCursor,
)
from query_builder.connectors.introspection import (
    _redis_index_columns,
    introspect_redis_search,
)
from query_builder.connectors.mongodb import MongoDBAtlasSQLConnector
from query_builder.connectors.neo4j import Neo4jConnector
from query_builder.connectors.opensearch import (
    OpenSearchConnector,
    _typed_parameter,
)
from query_builder.connectors.redis_search import (
    READ_ONLY_COMMANDS,
    RedisSearchConnector,
)
from query_builder.dialects import get_dialect
from query_builder.exceptions import DialectError, SecurityError


# ---- Elasticsearch -----------------------------------------------------------
class _FakeSql:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []
        self.cleared = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        return self.pages.pop(0)

    def clear_cursor(self, cursor):
        self.cleared.append(cursor)


class _FakeEsClient:
    def __init__(self, pages, version="8.15.2"):
        self.sql = _FakeSql(pages)
        self._version = version

    def info(self):
        return {"version": {"number": self._version}}


def test_elasticsearch_cursor_binds_params_and_follows_cursor_pages():
    client = _FakeEsClient(
        [
            {"columns": [{"name": "a"}], "rows": [[1], [2]], "cursor": "c1"},
            {"rows": [[3]], "cursor": "c2"},
            {"rows": [[4]]},
        ]
    )
    cur = ElasticsearchCursor(client)
    assert cur.execute("SELECT a FROM t WHERE x = ? ;", [7]) is cur
    assert client.sql.calls[0] == {
        "query": "SELECT a FROM t WHERE x = ?",
        "format": "json",
        "params": [7],
    }
    assert client.sql.calls[1] == {"cursor": "c1", "format": "json"}
    assert cur.description == [("a", None)] and cur.rowcount == 4
    assert cur.fetchone() == [1]
    assert cur.fetchall() == [[2], [3], [4]]
    assert cur.fetchone() is None
    cur.close()
    assert cur.fetchall() == []


def test_elasticsearch_cursor_clears_a_runaway_cursor(monkeypatch):
    import query_builder.connectors.elasticsearch as es

    monkeypatch.setattr(es, "_MAX_PAGES", 2)
    client = _FakeEsClient(
        [{"columns": [], "rows": [], "cursor": "c"}] + [{"rows": [], "cursor": "c"}] * 5
    )
    ElasticsearchCursor(client).execute("SELECT 1")
    assert client.sql.cleared == ["c"]


def test_elasticsearch_connector_wraps_client_and_reports_version_and_tables():
    client = _FakeEsClient(
        [
            {"columns": [{"name": "x"}], "rows": [[1]]},  # SELECT 1 (health probe)
            {
                "rows": [
                    ["docker-cluster", "people", "TABLE", "INDEX"],
                    ["docker-cluster", ".hidden", "TABLE", "INDEX"],
                ]
            },
            {"rows": [["name", "VARCHAR", "text"], ["age", "BIGINT", "long"]]},
        ]
    )
    es = ElasticsearchConnector(connection=client)
    with es.get_cursor() as cur:
        assert isinstance(cur, ElasticsearchCursor)
    info = es.test_connection()
    assert info["engine_version"] == "Elasticsearch 8.15.2"
    tables = es.introspect_schema()["tables"]
    assert list(tables) == ["people"]  # the cluster name is NOT a table; hidden skipped
    assert [c["name"] for c in tables["people"]["columns"]] == ["name", "age"]

    es_mock = ElasticsearchConnector(
        connection=MagicMock()
    )  # DB-API style keeps working
    with es_mock.get_cursor():
        pass
    broken = _FakeEsClient([{"rows": []}])
    broken.info = lambda: (_ for _ in ()).throw(RuntimeError("down"))
    assert (
        ElasticsearchConnector(connection=broken).test_connection()["engine_version"]
        == "Elasticsearch SQL"
    )
    explicit = MagicMock()
    with ElasticsearchConnector(cursor=explicit).get_cursor() as cur2:
        assert cur2 is explicit


def test_elasticsearch_dialect_binds_qmark_and_refuses_offset():
    es = get_dialect("elasticsearch")
    assert es.placeholder == "?"
    assert es.format_limit_offset(25, 0) == ("LIMIT 25", [])
    with pytest.raises(DialectError, match="OFFSET"):
        es.format_limit_offset(25, 5)
    sql, params, _, _ = QueryCompiler(
        {
            "table": "t",
            "columns": ["a"],
            "filters": [{"column": "a", "op": "eq", "value": 1}],
        },
        dialect="elasticsearch",
    ).compile()
    assert sql.endswith("LIMIT 50") and params == [1]


# ---- OpenSearch -----------------------------------------------------------------
def test_opensearch_typed_parameters_and_limit():
    assert _typed_parameter(True) == {"type": "boolean", "value": True}
    assert _typed_parameter(5) == {"type": "long", "value": 5}
    assert _typed_parameter(1.5) == {"type": "double", "value": 1.5}
    assert _typed_parameter("x") == {"type": "string", "value": "x"}
    os_d = get_dialect("opensearch")
    assert os_d.format_limit_offset(10, 0) == ("LIMIT 10", [])
    assert os_d.format_limit_offset(10, 5) == ("LIMIT 10 OFFSET 5", [])

    sent = {}

    class Transport:
        def perform_request(self, method, path, body=None):
            if "version" in body["query"].lower():
                raise RuntimeError("the SQL plugin has no version()")
            sent.update(method=method, path=path, body=body)
            return {"schema": [{"name": "n"}], "datarows": [[1]]}

    class Client:
        transport = Transport()

        def info(self):
            return {"version": {"number": "2.17.0"}}

    c = OpenSearchConnector(connection=Client())
    cols, rows, _ = c.execute_raw("SELECT n FROM t WHERE a = ? AND b = ?", ["x", 2])
    assert rows == [{"n": 1}]
    assert sent["body"]["parameters"] == [
        {"type": "string", "value": "x"},
        {"type": "long", "value": 2},
    ]
    # the SQL plugin has no version(): ask the cluster
    assert c.test_connection()["engine_version"] == "OpenSearch 2.17.0"


# ---- MongoDB (pymongosql) ----------------------------------------------------
class _FakeCollection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query, limit=0):
        return iter(self.docs[:limit] if limit else self.docs)


class _FakeMongoDb:
    name = "qb_it"

    def __init__(self):
        self.collections = {
            "people": _FakeCollection(
                [{"_id": 1, "name": "a", "age": 3, "user_id": 9}]
            ),
            "system.views": _FakeCollection([]),
        }
        self.client = MagicMock()
        self.client.server_info.return_value = {"version": "7.0.14"}
        self.pinged = False

    def list_collection_names(self):
        return list(self.collections)

    def __getitem__(self, name):
        return self.collections[name]

    def command(self, name):
        self.pinged = name == "ping"


class _FakeMongoConnection:
    def __init__(self):
        self.database = _FakeMongoDb()


def test_mongodb_connector_pings_and_introspects_natively():
    conn = _FakeMongoConnection()
    mongo = MongoDBAtlasSQLConnector(connection=conn, database="qb_it")
    info = mongo.test_connection()  # `SELECT 1` is a syntax error in pymongosql
    assert conn.database.pinged and info["engine_version"] == "MongoDB 7.0.14"
    assert info["status"] == "healthy" and info["database"] == "qb_it"
    schema = mongo.introspect_schema()
    assert list(schema["tables"]) == ["people"]  # system.* collections are skipped
    cols = {c["name"]: c for c in schema["tables"]["people"]["columns"]}
    assert cols["_id"]["is_primary"] and cols["age"]["data_type"] == "int"
    assert schema["tables"]["people"]["has_user_id"] is True

    conn.database.client.server_info.side_effect = RuntimeError("no perms")
    assert mongo.test_connection()["engine_version"] == "MongoDB"

    conn.database.list_collection_names = lambda: (_ for _ in ()).throw(
        RuntimeError("x")
    )
    with pytest.raises(IntrospectionError, match="MongoDB database"):
        mongo.introspect_schema()


def test_mongodb_connector_keeps_the_sql_path_for_dbapi_style_connections():
    cur = MagicMock()
    cur.fetchall.side_effect = [[("t",)], [("t", "id", "int", "NO")], [], []]
    cur.fetchone.return_value = (1,)
    mongo = MongoDBAtlasSQLConnector(cursor=cur, database="db")
    assert mongo.test_connection()["engine_version"] == "MongoDB Atlas SQL"
    assert "t" in mongo.introspect_schema()["tables"]
    # a database object without list_collection_names() (a mock) falls back too
    mocked = MongoDBAtlasSQLConnector(connection=MagicMock(), database="db")
    assert mocked._native_db() is not None  # MagicMock has the attribute ...
    odd = MagicMock()
    odd.database.list_collection_names.return_value = "not-a-list"
    odd.cursor.return_value = cur
    cur.fetchall.side_effect = [[("t",)], [("t", "id", "int", "NO")], [], []]
    assert "t" in MongoDBAtlasSQLConnector(connection=odd).introspect_schema()["tables"]


def test_mongodb_dialect_inlines_limit_and_offset():
    sql, params, _, _ = QueryCompiler(
        {"table": "t", "columns": ["a"], "limit": 5, "offset": 2}, dialect="mongodb"
    ).compile()
    assert sql.endswith("LIMIT 5 OFFSET 2") and params == []


# ---- Redis ------------------------------------------------------------------------
def test_redis_index_columns_parse_resp2_resp3_and_garbage():
    resp2 = [
        b"index_name", b"idx", b"attributes",
        [
            [b"identifier", b"name", b"attribute", b"name", b"type", b"TEXT"],
            [b"identifier", b"$.age", b"attribute", b"age", b"type", b"NUMERIC"],
            "ignored-scalar",
        ],
        b"num_docs", b"3",
    ]  # fmt: skip
    client = MagicMock(spec=["execute_command"])
    client.execute_command.return_value = resp2
    cols = _redis_index_columns(client, "idx")
    assert [(c["name"], c["data_type"]) for c in cols] == [
        ("name", "text"),
        ("age", "numeric"),
    ]
    client.execute_command.return_value = {
        b"attributes": [{b"identifier": b"title", b"type": b"TAG"}]
    }
    assert _redis_index_columns(client, "idx")[0]["name"] == "title"
    client.execute_command.return_value = [b"index_name", b"idx"]  # no attributes
    assert _redis_index_columns(client, "idx") == []
    client.execute_command.return_value = {}
    assert _redis_index_columns(client, "idx") == []
    client.execute_command.side_effect = RuntimeError("unknown index")
    assert _redis_index_columns(client, "idx") == []
    assert _redis_index_columns(None, "idx") == []
    assert _redis_index_columns(MagicMock(spec=[]), "idx") == []


def test_redis_introspection_uses_real_index_columns_and_never_invents_indexes():
    client = MagicMock(spec=["execute_command"])
    client.execute_command.side_effect = [
        [b"people"],
        [
            b"attributes",
            [[b"identifier", b"name", b"attribute", b"name", b"type", b"TEXT"]],
        ],
    ]
    snap = introspect_redis_search(client)
    assert [c["name"] for c in snap["tables"]["people"]["columns"]] == ["name"]
    nothing = MagicMock(spec=["execute_command"])
    nothing.execute_command.return_value = []
    assert introspect_redis_search(nothing)["tables"] == {}


def test_redis_raw_path_is_read_only():
    assert {"FT.SEARCH", "GET", "PING"} <= READ_ONLY_COMMANDS
    assert not READ_ONLY_COMMANDS & {"FLUSHALL", "SET", "DEL", "FT.CREATE", "EVAL"}
    client = MagicMock(spec=["execute_command"])
    client.execute_command.return_value = b"OK"
    redis = RedisSearchConnector(connection=client)
    assert redis.execute_raw("ping")[1] == [{"result": "OK"}]  # case-insensitive
    for write in ("FLUSHALL", "SET k v", "FT.DROPINDEX idx", "EVAL 'x' 0"):
        with pytest.raises(SecurityError, match="Read-only session"):
            redis.execute_raw(write)
    assert client.execute_command.call_count == 1


# ---- Neo4j ------------------------------------------------------------------------
def test_neo4j_sessions_are_opened_in_read_access_mode():
    class Rec(dict):
        def keys(self):
            return list(super().keys())

    class Result(list):
        def keys(self):
            return ["n"]

    class Session:
        def run(self, query, parameters):
            return Result([Rec(n=1)])

        def close(self):
            pass

    class Driver:
        modes = []

        def session(self, **kwargs):
            Driver.modes.append(kwargs)
            return Session()

    cols, rows, _ = Neo4jConnector(connection=Driver()).execute_raw(
        "MATCH (n) RETURN n"
    )
    assert Driver.modes == [
        {"default_access_mode": "READ"}
    ]  # the server refuses writes
    assert rows == [{"n": 1}]


# ---- ClickHouse native protocol ----------------------------------------------------
def test_clickhouse_native_binds_named_parameters():
    assert _bind_positional("SELECT 1", None) == ("SELECT 1", None)
    assert _bind_positional("SELECT 1", []) == ("SELECT 1", None)
    assert _bind_positional("SELECT %s", {"p": 1}) == ("SELECT %s", {"p": 1})
    sql, params = _bind_positional("a = %s AND b = %s AND c LIKE '100%%'", [1, "x"])
    assert sql == "a = %(p0)s AND b = %(p1)s AND c LIKE '100%%'"
    assert params == {"p0": 1, "p1": "x"}


class _FakeNativeClient:
    """clickhouse_driver.Client: execute() returns rows, not a DB-API cursor."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []

    def execute(self, sql, params=None, with_column_types=False):
        self.calls.append((sql, params))
        if "system.tables" in sql:
            return [("people",)], [("name", "String")]
        if "system.columns" in sql:
            return (
                [("people", "id", "Int32", 1), ("people", "name", "String", 0)],
                [("t", "String")] * 4,
            )
        return [(1,)], [("x", "UInt8")]


def test_clickhouse_native_connector_with_a_real_shaped_client(monkeypatch):
    import sys
    import types

    fake_mod = types.ModuleType("clickhouse_driver")
    fake_mod.Client = _FakeNativeClient
    monkeypatch.setitem(sys.modules, "clickhouse_driver", fake_mod)
    monkeypatch.setitem(sys.modules, "clickhouse_driver.Client", fake_mod)
    ch = ClickHouseNativeConnector(database="d", host="h", settings={"x": 1})
    client = ch.connect()
    # unmatched OUTER JOIN columns must be NULL; caller settings still win
    assert client.kwargs["settings"] == {"join_use_nulls": 1, "x": 1}
    with ch.get_cursor() as cur:
        cur.execute("SELECT %s", [5])
        assert cur.fetchall() == [[1]]
    assert client.calls[-1] == ("SELECT %(p0)s", {"p0": 5})
    snap = ch.introspect_schema()  # needs a DB-API-shaped cursor, not the raw client
    cols = {c["name"]: c["is_primary"] for c in snap["tables"]["people"]["columns"]}
    assert cols == {"id": True, "name": False}

    adapter = _ClickHouseNativeCursorAdapter(client)
    detached = _DetachedCursor(adapter)
    assert not hasattr(detached, "target")
    detached.execute("SELECT 1")
    assert detached.description == [("x",)]
    assert detached.fetchone() == [1]
    assert detached.fetchall() == []
    detached.close()


def test_async_loops_are_untouched():
    # sanity: the module-level helpers above never leave a running loop behind
    assert asyncio.run(asyncio.sleep(0, "ok")) == "ok"
