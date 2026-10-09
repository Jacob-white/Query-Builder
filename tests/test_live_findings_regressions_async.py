"""
Regression tests for the async connectors, which the live suite showed did not
work against real clients (coroutines were never awaited, introspection fell back
to nothing). The vendor async clients are replaced by fakes with their real shape.
"""

from __future__ import annotations

import asyncio
import sys
import types

import pytest

from query_builder.connectors.base import IntrospectionError
from query_builder.connectors.cassandra import AsyncApacheCassandraConnector
from query_builder.connectors.clickhouse_native import (
    AsyncClickHouseNativeConnector,
    _asynch_query,
    _PrefetchedCatalog,
)
from query_builder.connectors.neo4j import (
    AsyncNeo4jConnector,
    _prefetch_schema_queries,
    _ReplaySession,
    _translate_to_cypher,
)
from query_builder.connectors.opensearch import AsyncOpenSearchConnector
from query_builder.connectors.redis_search import AsyncRedisSearchConnector
from query_builder.exceptions import SecurityError


def run(coro):
    return asyncio.run(coro)


# ---- OpenSearch -----------------------------------------------------------------
class _AsyncTransport:
    async def perform_request(self, method, path, body=None):
        self.last = (method, path, body)
        if "version" in body["query"].lower():
            raise RuntimeError("no version() in the SQL plugin")
        return {"schema": [{"name": "n"}], "datarows": [[7]]}


class _AsyncIndices:
    def get_mapping(self):  # like opensearch-py: a plain function returning a coroutine
        async def inner():
            return {
                "people": {"mappings": {"properties": {"name": {"type": "text"}}}},
                ".kibana": {"mappings": {"properties": {}}},
            }

        return inner()


class _AsyncOpenSearchClient:
    transport = _AsyncTransport()
    indices = _AsyncIndices()

    def info(self):
        return {"version": {"number": "2.17.0"}}


def test_async_opensearch_awaits_the_real_client():
    conn = AsyncOpenSearchConnector(connection=_AsyncOpenSearchClient())
    cols, rows, _ = run(conn.execute_raw("SELECT n FROM t WHERE a = ?;", ["x"]))
    assert cols == ["n"] and rows == [{"n": 7}]
    assert conn._connection.transport.last[2]["parameters"] == [
        {"type": "string", "value": "x"}
    ]
    snap = run(conn.introspect_schema())
    assert list(snap["tables"]) == ["people"]  # hidden index skipped
    assert "name" in {c["name"] for c in snap["tables"]["people"]["columns"]}


# ---- Redis ----------------------------------------------------------------------
class _AsyncRedis:
    def __init__(self):
        self.calls = []

    async def execute_command(self, *args):
        self.calls.append(args)
        if args[0] == "FT._LIST":
            return [b"people", b"gone"]
        if args == ("FT.INFO", "gone"):
            raise RuntimeError("Unknown index name")
        if args[0] == "FT.INFO":
            return [
                b"attributes",
                [[b"identifier", b"name", b"attribute", b"name", b"type", b"TEXT"]],
            ]
        return b"OK"

    async def ping(self):
        return True


def test_async_redis_introspects_real_indexes_and_stays_read_only():
    client = _AsyncRedis()
    redis = AsyncRedisSearchConnector(connection=client)
    snap = run(redis.introspect_schema())
    cols = {c["name"] for c in snap["tables"]["people"]["columns"]}
    assert "name" in cols  # from FT.INFO, not invented
    assert "gone" in snap["tables"]  # fell back to the neutral columns, not an error

    assert run(redis.execute_raw("GET key"))[1] == [{"result": "OK"}]
    for write in ("FLUSHALL", "SET k v", "FT.DROPINDEX people"):
        with pytest.raises(SecurityError, match="Read-only session"):
            run(redis.execute_raw(write))
    assert not any(c[0] in ("FLUSHALL", "SET") for c in client.calls)

    broken = _AsyncRedis()

    async def boom(*args):
        raise RuntimeError("down")

    broken.execute_command = boom
    with pytest.raises(IntrospectionError, match="RediSearch"):
        run(AsyncRedisSearchConnector(connection=broken).introspect_schema())


# ---- Neo4j ----------------------------------------------------------------------
class _Record(dict):
    pass


class _AsyncResult:
    def __init__(self, keys, rows):
        self._keys, self._rows = keys, rows

    def keys(self):
        return self._keys

    def __aiter__(self):
        async def gen():
            for row in self._rows:
                yield _Record(zip(self._keys, row, strict=True))

        return gen()


class _AsyncSession:
    def __init__(self, driver):
        self.driver = driver

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def run(self, query, parameters=None):
        self.driver.queries.append((query, parameters))
        if "SHOW NODE LABELS" in query:
            return _AsyncResult(["label"], [["Person"]])
        if "keys(n)" in query:
            return _AsyncResult(["keys"], [[["id", "name"]]])
        if "SHOW RELATIONSHIP TYPES" in query:
            return _AsyncResult(["relationshipType"], [])
        if "dbms.components" in query:
            return _AsyncResult(["version"], [["5.24.1"]])
        if "boom" in query:
            raise RuntimeError("bad cypher")
        return _AsyncResult(["name"], [["alice"], ["bob"]])


class _AsyncDriver:
    def __init__(self):
        self.queries = []
        self.modes = []

    async def verify_connectivity(self):
        return None

    def session(self, **kwargs):
        self.modes.append(kwargs)
        return _AsyncSession(self)


def test_async_neo4j_runs_cypher_in_read_mode_and_introspects():
    driver = _AsyncDriver()
    neo = AsyncNeo4jConnector(connection=driver, database="neo4j")
    cols, rows, _ = run(neo.execute_raw("MATCH (p:Person) RETURN p.name AS name"))
    assert cols == ["name"] and rows == [{"name": "alice"}, {"name": "bob"}]
    assert {"default_access_mode": "READ"} in driver.modes
    # SQL is translated to Cypher exactly like the sync adapter does
    run(neo.execute_raw("SELECT name FROM Person WHERE age > ? LIMIT 2", [3]))
    assert driver.queries[-1][0].startswith("MATCH (`Person`:`Person`)")
    assert driver.queries[-1][1] == {"p0": 3}

    info = run(neo.test_connection())
    assert info["engine_version"] == "Neo4j 5.24.1" and info["database"] == "neo4j"
    snap = run(neo.introspect_schema())
    assert [c["name"] for c in snap["tables"]["Person"]["columns"]] == ["id", "name"]

    class NoVersion(_AsyncDriver):
        def session(self, **kwargs):
            session = super().session(**kwargs)
            original = session.run

            async def run_(query, parameters=None):
                if "dbms.components" in query:
                    raise RuntimeError("no procedure access")
                return await original(query, parameters)

            session.run = run_
            return session

    # the version probe is informational: a refusal never breaks the health check
    degraded = run(AsyncNeo4jConnector(connection=NoVersion()).test_connection())
    assert degraded["status"] == "healthy" and "engine_version" not in degraded


def test_neo4j_translation_helpers_and_replay():
    cypher, params = _translate_to_cypher("SELECT 1", None)
    assert cypher == "RETURN 1 AS val" and params == {}
    replay = _ReplaySession({"A": [{"x": 1}], "B": RuntimeError("nope")})
    assert replay.run("A;") == [{"x": 1}]
    with pytest.raises(RuntimeError, match="nope"):
        replay.run("B")
    with pytest.raises(KeyError):
        replay.run("missing")

    class Failing(_AsyncDriver):
        def session(self, **kwargs):
            session = super().session(**kwargs)
            original = session.run

            async def run_(query, parameters=None):
                if query == "SHOW NODE LABELS":
                    raise RuntimeError("old server")
                if query == "CALL db.labels()":
                    return _AsyncResult(["label"], [["Legacy"]])
                return await original(query, parameters)

            session.run = run_
            return session

    results = run(_prefetch_schema_queries(Failing()))
    assert isinstance(results["SHOW NODE LABELS"], RuntimeError)
    assert results["CALL db.labels()"] == [{"label": "Legacy"}]
    assert "MATCH (n:`Legacy`) RETURN keys(n) AS keys LIMIT 1" in results


# ---- ClickHouse native (asynch) -------------------------------------------------
class _AsynchCursor:
    def __init__(self, conn):
        self.conn, self.description, self._rows = conn, None, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, args=None):
        self.conn.executed.append((sql, args))
        if "system.tables" in sql:
            self.description, self._rows = [("name",)], [("people",)]
        elif "system.columns" in sql:
            self.description = [("table",), ("name",), ("type",), ("pk",)]
            self._rows = [("people", "id", "Int32", 1)]
        elif sql.startswith("SET"):
            self.description, self._rows = None, []
        elif "version" in sql:
            self.description, self._rows = [("v",)], [("24.8",)]
        else:
            self.description, self._rows = [("a",)], [(1,)]

    async def fetchall(self):
        return self._rows


class _AsynchConnection:
    def __init__(self):
        self.opened = False
        self.executed = []

    async def connect(self):  # asynch.connect() returns the connection UNOPENED
        self.opened = True

    def cursor(self):
        return _AsynchCursor(self)


def test_async_clickhouse_native_opens_the_asynch_connection_and_awaits_queries(
    monkeypatch,
):
    fake = types.ModuleType("asynch")
    holder = {}

    def connect(**kwargs):
        holder["conn"] = _AsynchConnection()
        holder["kwargs"] = kwargs
        return holder["conn"]

    fake.connect = connect
    monkeypatch.setitem(sys.modules, "asynch", fake)
    ch = AsyncClickHouseNativeConnector(database="d", host="h")
    run(ch.connect())
    conn = holder["conn"]
    assert conn.opened and holder["kwargs"]["host"] == "h"
    assert (
        "SET join_use_nulls = 1",
        None,
    ) in conn.executed  # OUTER JOIN misses are NULL

    cols, rows, _ = run(ch.execute_raw("SELECT a FROM t WHERE x = %s;", [5]))
    assert (cols, rows) == (["a"], [{"a": 1}])
    assert conn.executed[-1] == ("SELECT a FROM t WHERE x = %(p0)s", {"p0": 5})
    assert run(ch.test_connection())["engine_version"] == "ClickHouse Native 24.8"
    snap = run(ch.introspect_schema())
    assert snap["tables"]["people"]["columns"][0]["is_primary"] is True

    run(_asynch_query(conn, "SELECT 1", None))
    catalog = _PrefetchedCatalog({"system.tables": [("t",)]})
    catalog.execute("SELECT x FROM system.tables")
    assert catalog.fetchone() == ("t",) and catalog.fetchone() is None
    catalog.execute("SELECT x FROM system.tables")
    assert catalog.fetchall() == [("t",)] and catalog.fetchall() == []
    with pytest.raises(ValueError, match="no prefetched result"):
        catalog.execute("SELECT 1")
    catalog.close()


def test_async_clickhouse_native_introspection_failure_is_wrapped():
    conn = _AsynchConnection()

    async def failing_execute(sql, args=None):
        raise RuntimeError("catalog down")

    cursor_cls = _AsynchCursor
    cursor_cls_execute = cursor_cls.execute
    cursor_cls.execute = lambda self, sql, args=None: failing_execute(sql, args)
    try:
        with pytest.raises(RuntimeError, match="catalog down"):
            run(AsyncClickHouseNativeConnector(connection=conn).introspect_schema())
    finally:
        cursor_cls.execute = cursor_cls_execute
    bad = _AsynchConnection()
    ch = AsyncClickHouseNativeConnector(connection=bad)
    # introspect_clickhouse_native raising inside the prefetched path -> IntrospectionError
    import query_builder.connectors.clickhouse_native as mod

    original = mod.introspect_clickhouse_native
    mod.introspect_clickhouse_native = lambda *a, **k: (_ for _ in ()).throw(
        ValueError("x")
    )
    try:
        with pytest.raises(IntrospectionError, match="ClickHouse Native"):
            run(ch.introspect_schema())
    finally:
        mod.introspect_clickhouse_native = original


# ---- Cassandra --------------------------------------------------------------------
class _CassandraResult(list):
    column_names = ["id", "name"]

    def all(self):
        return list(self)


class _CassandraSession:
    def __init__(self):
        self.queries = []

    def execute(self, sql, params=None):
        self.queries.append(sql)
        if "system_schema.tables" in sql:
            res = _CassandraResult([("people",)])
            res.column_names = ["table_name"]
            return res
        if "system_schema.columns" in sql:
            res = _CassandraResult(
                [
                    ("people", "id", "int", "partition_key"),
                    ("people", "name", "text", "regular"),
                ]
            )
            res.column_names = ["table_name", "column_name", "type", "kind"]
            return res
        return _CassandraResult([(1, "a")])


def test_async_cassandra_introspects_and_runs_off_the_event_loop():
    session = _CassandraSession()
    cass = AsyncApacheCassandraConnector(connection=session, keyspace="ks")
    cols, rows, _ = run(cass.execute_raw("SELECT id, name FROM people"))
    assert cols == ["id", "name"] and rows == [{"id": 1, "name": "a"}]
    info = run(cass.test_connection())
    assert info["engine_version"] == "Apache Cassandra" and info["keyspace"] == "ks"
    snap = run(cass.introspect_schema())
    assert "people" in snap["tables"]

    class Broken(_CassandraSession):
        def execute(self, sql, params=None):
            raise RuntimeError("no keyspace")

    with pytest.raises(IntrospectionError, match="Cassandra"):
        run(AsyncApacheCassandraConnector(connection=Broken()).introspect_schema())
