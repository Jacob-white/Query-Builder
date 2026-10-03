"""
Comprehensive Edge-Case and Branch-Exhaustion Tests for Next-Tier Connectors.
=============================================================================
Guarantees 100% statement, function, and branch coverage for:
- DB2 (IBM DB2)
- GreptimeDB
- TDengine
- ArangoDB
- Apache Cassandra
- chDB
- Azure Cosmos DB
- Exasol
- SurrealDB
- Apache Spark SQL
- and Introspection functions
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock, patch

import pytest

from query_builder.connectors import (
    ApacheCassandraConnector,
    ArangoDBConnector,
    AsyncApacheCassandraConnector,
    AsyncArangoDBConnector,
    AsyncChDBConnector,
    AsyncCosmosDBConnector,
    AsyncDB2Connector,
    AsyncExasolConnector,
    AsyncGreptimeDBConnector,
    AsyncSparkSQLConnector,
    AsyncSurrealDBConnector,
    AsyncTDengineConnector,
    ChDBConnector,
    CosmosDBConnector,
    DB2Connector,
    ExasolConnector,
    GreptimeDBConnector,
    IntrospectionError,
    SparkSQLConnector,
    SurrealDBConnector,
    TDengineConnector,
    introspect_arangodb,
    introspect_cosmosdb,
    introspect_sparksql,
    introspect_surrealdb,
    introspect_tdengine,
)
from query_builder.connectors.arangodb import _ArangoCursorAdapter
from query_builder.connectors.cassandra import _CassandraCursorAdapter
from query_builder.connectors.chdb import _ChDBCursorAdapter
from query_builder.connectors.cosmosdb import _CosmosDBCursorAdapter
from query_builder.connectors.exasol import _ExasolCursorAdapter
from query_builder.connectors.spark import _SparkCursorAdapter
from query_builder.connectors.surrealdb import _SurrealCursorAdapter
from query_builder.connectors.tdengine import _TDengineCursorAdapter

# ============================================================================
# 1. IBM DB2 Edge Cases
# ============================================================================


def test_db2_cached_and_async_connect():
    conn = DB2Connector(connection="mock_conn")
    assert conn.connect() == "mock_conn"

    mock_driver = MagicMock()
    mock_db2_conn = MagicMock()
    mock_driver.connect.return_value = mock_db2_conn
    with patch.dict(sys.modules, {"ibm_db_dbi": mock_driver}):
        async_conn = AsyncDB2Connector()

        async def _test():
            c1 = await async_conn.connect()
            assert c1 is mock_db2_conn
            c2 = await async_conn.connect()  # Cached branch
            assert c2 is mock_db2_conn

        asyncio.run(_test())


# ============================================================================
# 2. GreptimeDB Edge Cases
# ============================================================================


def test_greptimedb_cached_and_async_connect():
    conn = GreptimeDBConnector(connection="mock_conn")
    assert conn.connect() == "mock_conn"

    mock_driver = MagicMock()
    mock_greptime_conn = MagicMock()
    mock_driver.connect.return_value = mock_greptime_conn
    with patch.dict(sys.modules, {"greptimedb": mock_driver}):
        async_conn = AsyncGreptimeDBConnector()

        async def _test():
            c1 = await async_conn.connect()
            assert c1 is mock_greptime_conn
            c2 = await async_conn.connect()  # Cached branch
            assert c2 is mock_greptime_conn

        asyncio.run(_test())


# ============================================================================
# 3. TDengine Edge Cases
# ============================================================================


def test_tdengine_adapter_and_lifecycle_branches():
    # Adapter with target having cursor and no params
    mock_target_cur = MagicMock()
    mock_cur = MagicMock()
    mock_cur.description = [("val",)]
    mock_cur.fetchall.return_value = [[1]]
    mock_target_cur.cursor.return_value = mock_cur
    adapter1 = _TDengineCursorAdapter(mock_target_cur)
    adapter1.execute("SELECT 1")
    assert adapter1.description == [("val",)]
    assert adapter1.fetchall() == [[1]]

    # Adapter with target having execute directly and no params
    mock_target_exec = MagicMock(spec=["execute", "description", "fetchall"])
    mock_target_exec.description = [("cnt",)]
    mock_target_exec.fetchall.return_value = [[42]]
    adapter2 = _TDengineCursorAdapter(mock_target_exec)
    adapter2.execute("SELECT 42")
    assert adapter2.description == [("cnt",)]
    assert adapter2.fetchall() == [[42]]

    # Cached connect
    conn = TDengineConnector(connection="mock_taos_conn")
    assert conn.connect() == "mock_taos_conn"

    # get_cursor with conn having cursor() (with and without close)
    mock_conn1 = MagicMock()
    mock_c1 = MagicMock()
    mock_conn1.cursor.return_value = mock_c1
    conn_cur1 = TDengineConnector(connection=mock_conn1)
    with conn_cur1.get_cursor() as c:
        assert c is mock_c1
    mock_c1.close.assert_called_once()

    # get_cursor with conn having no cursor() -> adapter
    conn_cur2 = TDengineConnector(connection=object())
    with conn_cur2.get_cursor() as c:
        assert isinstance(c, _TDengineCursorAdapter)

    # Async connect success and cache
    mock_driver = MagicMock()
    mock_conn_async = MagicMock()
    mock_driver.connect.return_value = mock_conn_async
    with patch.dict(sys.modules, {"taos": mock_driver}):
        async_conn = AsyncTDengineConnector()

        async def _test():
            c1 = await async_conn.connect()
            assert c1 is mock_conn_async
            c2 = await async_conn.connect()
            assert c2 is mock_conn_async

        asyncio.run(_test())


# ============================================================================
# 4. ArangoDB Edge Cases
# ============================================================================


def test_arangodb_adapter_and_lifecycle_branches():
    # Adapter with db having execute directly and no params
    mock_db_exec = MagicMock(spec=["execute", "description", "fetchall"])
    mock_db_exec.description = [("aql_res",)]
    mock_db_exec.fetchall.return_value = [["doc"]]
    adapter1 = _ArangoCursorAdapter(mock_db_exec)
    adapter1.execute("RETURN 1")
    assert adapter1.description == [("aql_res",)]
    assert adapter1.fetchall() == [["doc"]]

    # Cached connect
    conn = ArangoDBConnector(connection="mock_arango_db")
    assert conn.connect() == "mock_arango_db"

    # get_cursor with conn having cursor()
    mock_conn = MagicMock()
    mock_c = MagicMock()
    mock_conn.cursor.return_value = mock_c
    conn_cur = ArangoDBConnector(connection=mock_conn)
    with conn_cur.get_cursor() as c:
        assert c is mock_c
    mock_c.close.assert_called_once()

    # get_cursor with conn having no cursor() -> adapter
    conn_cur2 = ArangoDBConnector(connection=object())
    with conn_cur2.get_cursor() as c:
        assert isinstance(c, _ArangoCursorAdapter)

    # introspect_schema through connector
    mock_cur = MagicMock(spec=["execute", "fetchall"])
    mock_cur.fetchall.return_value = [[{"name": "vertices"}]]
    conn_schema = ArangoDBConnector(cursor=mock_cur)
    snap = conn_schema.introspect_schema()
    assert "vertices" in snap["tables"]

    # introspect_schema error handling
    mock_cur.fetchall.side_effect = RuntimeError("Introspection fail")
    with pytest.raises(IntrospectionError):
        conn_schema.introspect_schema()

    # Async connect success and cache
    mock_driver = MagicMock()
    mock_client = MagicMock()
    mock_db = MagicMock()
    mock_client.db.return_value = mock_db
    mock_driver.ArangoClient.return_value = mock_client
    with patch.dict(sys.modules, {"arango": mock_driver}):
        async_conn = AsyncArangoDBConnector()

        async def _test():
            c1 = await async_conn.connect()
            assert c1 is mock_db
            c2 = await async_conn.connect()
            assert c2 is mock_db

        asyncio.run(_test())


# ============================================================================
# 5. Apache Cassandra Edge Cases
# ============================================================================


def test_cassandra_adapter_and_lifecycle_branches():
    # Adapter execute where result_set is custom iterable (neither all, fetchall, nor list)
    class CustomResultSet:
        def __iter__(self):
            return iter([{"col": "val"}])

    mock_session = MagicMock()
    mock_session.execute.return_value = CustomResultSet()
    adapter1 = _CassandraCursorAdapter(mock_session)
    adapter1.execute("SELECT * FROM t;")
    assert adapter1.fetchall() == [["val"]]

    # Adapter execute with cursor and no params
    mock_session_cur = MagicMock(spec=["cursor"])
    mock_cur = MagicMock()
    mock_cur.description = [("x",)]
    mock_cur.fetchall.return_value = [(100,)]
    mock_session_cur.cursor.return_value = mock_cur
    adapter2 = _CassandraCursorAdapter(mock_session_cur)
    adapter2.execute("SELECT 100")
    assert adapter2.description == [("x",)]
    assert adapter2.fetchall() == [(100,)]

    # Cached connect
    conn = ApacheCassandraConnector(connection="mock_session")
    assert conn.connect() == "mock_session"

    # get_cursor with conn having cursor() (with close)
    mock_conn = MagicMock()
    mock_c = MagicMock()
    mock_conn.cursor.return_value = mock_c
    conn_cur = ApacheCassandraConnector(connection=mock_conn)
    with conn_cur.get_cursor() as c:
        assert c is mock_c
    mock_c.close.assert_called_once()

    # get_cursor with conn having no cursor() -> adapter
    conn_cur2 = ApacheCassandraConnector(connection=object())
    with conn_cur2.get_cursor() as c:
        assert isinstance(c, _CassandraCursorAdapter)

    # Async connect success and cache
    mock_driver = MagicMock()
    mock_cluster = MagicMock()
    mock_sess = MagicMock()
    mock_cluster.connect.return_value = mock_sess
    mock_driver.Cluster.return_value = mock_cluster
    with patch.dict(sys.modules, {"cassandra.cluster": mock_driver}):
        async_conn = AsyncApacheCassandraConnector()

        async def _test():
            c1 = await async_conn.connect()
            assert c1 is mock_sess
            c2 = await async_conn.connect()
            assert c2 is mock_sess

        asyncio.run(_test())


# ============================================================================
# 6. chDB Edge Cases
# ============================================================================


def test_chdb_adapter_and_lifecycle_branches():
    # Adapter with res.data
    mock_chdb_data = MagicMock()
    mock_res_data = MagicMock(spec=["data"])
    mock_res_data.data = b'{"n": 1}\n{"n": 2}'
    mock_chdb_data.query.return_value = mock_res_data
    adapter1 = _ChDBCursorAdapter(mock_chdb_data)
    adapter1.execute("SELECT 1")
    assert adapter1.description == [("n",)]
    assert adapter1.fetchall() == [[1], [2]]

    # Adapter with raw string res
    mock_chdb_str = MagicMock()
    mock_chdb_str.query.return_value = '{"s": "hello"}'
    adapter2 = _ChDBCursorAdapter(mock_chdb_str)
    adapter2.execute("SELECT 1")
    assert adapter2.description == [("s",)]
    assert adapter2.fetchall() == [["hello"]]

    # Adapter with empty json lines
    mock_chdb_empty = MagicMock()
    mock_chdb_empty.query.return_value = b"\n   \n"
    adapter3 = _ChDBCursorAdapter(mock_chdb_empty)
    adapter3.execute("SELECT 1")
    assert adapter3.fetchall() == []

    # Adapter execute exception handling
    mock_chdb_err = MagicMock()
    mock_chdb_err.query.side_effect = RuntimeError("chdb query error")
    adapter_err = _ChDBCursorAdapter(mock_chdb_err)
    with pytest.raises(RuntimeError):
        adapter_err.execute("SELECT 1")

    # Cached connect
    conn = ChDBConnector(connection="mock_chdb")
    assert conn.connect() == "mock_chdb"

    # connect where driver has no connect method
    mock_driver_no_connect = object()
    with patch.dict(sys.modules, {"chdb": mock_driver_no_connect}):
        conn_no_connect = ChDBConnector()
        assert conn_no_connect.connect() is mock_driver_no_connect

    # get_cursor with conn having cursor()
    mock_conn = MagicMock()
    mock_c = MagicMock()
    mock_conn.cursor.return_value = mock_c
    conn_cur = ChDBConnector(connection=mock_conn)
    with conn_cur.get_cursor() as c:
        assert c is mock_c
    mock_c.close.assert_called_once()

    # get_cursor with conn having no cursor() -> adapter
    conn_cur2 = ChDBConnector(connection=object())
    with conn_cur2.get_cursor() as c:
        assert isinstance(c, _ChDBCursorAdapter)

    # Async connect driver branches
    mock_driver_connect = MagicMock(spec=["connect"])
    mock_chdb_session = MagicMock()
    mock_driver_connect.connect.return_value = mock_chdb_session
    with patch.dict(sys.modules, {"chdb": mock_driver_connect}):
        async_conn = AsyncChDBConnector()

        async def _test():
            c1 = await async_conn.connect()
            assert c1 is mock_chdb_session
            c2 = await async_conn.connect()
            assert c2 is mock_chdb_session

        asyncio.run(_test())

    # Async execute_raw with conn having cursor()
    mock_cur_raw = MagicMock()
    mock_cur_raw.description = [("x",)]
    mock_cur_raw.fetchall.return_value = [(10,)]
    mock_conn_raw = MagicMock()
    mock_conn_raw.cursor.return_value = mock_cur_raw
    async_conn_cur = AsyncChDBConnector(connection=mock_conn_raw)

    async def _test_exec():
        cols1, rows1, _ = await async_conn_cur.execute_raw("SELECT 10;", [1])
        assert cols1 == ["x"] and rows1 == [{"x": 10}]
        cols2, rows2, _ = await async_conn_cur.execute_raw("SELECT 10;")
        assert cols2 == ["x"] and rows2 == [{"x": 10}]

    asyncio.run(_test_exec())


# ============================================================================
# 7. Azure Cosmos DB Edge Cases
# ============================================================================


def test_cosmosdb_adapter_and_lifecycle_branches():
    # Adapter with target having execute directly and no params
    mock_target_exec = MagicMock(spec=["execute", "description", "fetchall"])
    mock_target_exec.description = [("c_res",)]
    mock_target_exec.fetchall.return_value = [["doc1"]]
    adapter1 = _CosmosDBCursorAdapter(mock_target_exec)
    adapter1.execute("SELECT 1")
    assert adapter1.description == [("c_res",)]
    assert adapter1.fetchall() == [["doc1"]]

    # Cached connect
    conn = CosmosDBConnector(connection="mock_client")
    assert conn.connect() == "mock_client"

    # get_cursor with conn having cursor()
    mock_conn = MagicMock()
    mock_c = MagicMock()
    mock_conn.cursor.return_value = mock_c
    conn_cur = CosmosDBConnector(connection=mock_conn)
    with conn_cur.get_cursor() as c:
        assert c is mock_c
    mock_c.close.assert_called_once()

    # get_cursor with conn having no cursor() -> adapter
    conn_cur2 = CosmosDBConnector(connection=object())
    with conn_cur2.get_cursor() as c:
        assert isinstance(c, _CosmosDBCursorAdapter)

    # introspect_schema through connector
    mock_client = MagicMock(spec=["get_database_client"])
    mock_db = MagicMock(spec=["list_containers"])
    mock_db.list_containers.return_value = [{"id": "coll1"}]
    mock_client.get_database_client.return_value = mock_db
    conn_schema = CosmosDBConnector(connection=mock_client)
    snap = conn_schema.introspect_schema()
    assert "coll1" in snap["tables"]

    # introspect_schema error handling
    mock_client.get_database_client.side_effect = RuntimeError("Introspection fail")
    with pytest.raises(IntrospectionError):
        conn_schema.introspect_schema()

    # Async connect success and cache
    mock_driver = MagicMock()
    mock_cosmos_client = MagicMock()
    mock_driver.CosmosClient.return_value = mock_cosmos_client
    with patch.dict(sys.modules, {"azure.cosmos": mock_driver}):
        async_conn = AsyncCosmosDBConnector()

        async def _test():
            c1 = await async_conn.connect()
            assert c1 is mock_cosmos_client
            c2 = await async_conn.connect()
            assert c2 is mock_cosmos_client

        asyncio.run(_test())


# ============================================================================
# 8. Exasol Edge Cases
# ============================================================================


def test_exasol_adapter_and_lifecycle_branches():
    # Adapter with stmt having no fetchall or fetchall_dict and not list/tuple
    mock_conn = MagicMock()
    mock_stmt = object()
    mock_conn.execute.return_value = mock_stmt
    adapter1 = _ExasolCursorAdapter(mock_conn)
    adapter1.execute("SELECT 1;")
    assert adapter1.fetchall() == []

    # Adapter with conn having cursor() and no params
    mock_conn_cur = MagicMock(spec=["cursor"])
    mock_cur = MagicMock()
    mock_cur.description = [("res",)]
    mock_cur.fetchall.return_value = [(42,)]
    mock_conn_cur.cursor.return_value = mock_cur
    adapter2 = _ExasolCursorAdapter(mock_conn_cur)
    adapter2.execute("SELECT 42")
    assert adapter2.description == [("res",)]
    assert adapter2.fetchall() == [(42,)]

    # Cached connect
    conn = ExasolConnector(connection="mock_exa_conn")
    assert conn.connect() == "mock_exa_conn"

    # get_cursor with conn having cursor()
    mock_conn_gc = MagicMock()
    mock_c = MagicMock()
    mock_conn_gc.cursor.return_value = mock_c
    conn_cur = ExasolConnector(connection=mock_conn_gc)
    with conn_cur.get_cursor() as c:
        assert c is mock_c
    mock_c.close.assert_called_once()

    # get_cursor with conn having no cursor() -> adapter
    conn_cur2 = ExasolConnector(connection=object())
    with conn_cur2.get_cursor() as c:
        assert isinstance(c, _ExasolCursorAdapter)

    # Async connect success and cache
    mock_driver = MagicMock()
    mock_exasol_conn = MagicMock()
    mock_driver.connect.return_value = mock_exasol_conn
    with patch.dict(sys.modules, {"pyexasol": mock_driver}):
        async_conn = AsyncExasolConnector()

        async def _test():
            c1 = await async_conn.connect()
            assert c1 is mock_exasol_conn
            c2 = await async_conn.connect()
            assert c2 is mock_exasol_conn

        asyncio.run(_test())


# ============================================================================
# 9. SurrealDB Edge Cases
# ============================================================================


def test_surrealdb_adapter_and_lifecycle_branches():
    # Adapter with res being a dictionary
    mock_client_dict = MagicMock()
    mock_client_dict.query.return_value = {"res_key": "res_val"}
    adapter1 = _SurrealCursorAdapter(mock_client_dict)
    adapter1.execute("SELECT 1")
    assert adapter1.description == [("res_key",)]
    assert adapter1.fetchall() == [["res_val"]]

    # Adapter with res being None
    mock_client_none = MagicMock()
    mock_client_none.query.return_value = None
    adapter2 = _SurrealCursorAdapter(mock_client_none)
    adapter2.execute("SELECT 1")
    assert adapter2.description == []
    assert adapter2.fetchall() == []

    # Adapter with client having execute directly and no params
    mock_client_exec = MagicMock(spec=["execute", "description", "fetchall"])
    mock_client_exec.description = [("val",)]
    mock_client_exec.fetchall.return_value = [[99]]
    adapter3 = _SurrealCursorAdapter(mock_client_exec)
    adapter3.execute("SELECT 99")
    assert adapter3.description == [("val",)]
    assert adapter3.fetchall() == [[99]]

    # Cached connect
    conn = SurrealDBConnector(connection="mock_surreal")
    assert conn.connect() == "mock_surreal"

    # get_cursor with conn having cursor()
    mock_conn = MagicMock()
    mock_c = MagicMock()
    mock_conn.cursor.return_value = mock_c
    conn_cur = SurrealDBConnector(connection=mock_conn)
    with conn_cur.get_cursor() as c:
        assert c is mock_c
    mock_c.close.assert_called_once()

    # get_cursor with conn having no cursor() -> adapter
    conn_cur2 = SurrealDBConnector(connection=object())
    with conn_cur2.get_cursor() as c:
        assert isinstance(c, _SurrealCursorAdapter)

    # Async connect with driver having connect function instead of Surreal class
    mock_driver_connect = MagicMock(spec=["connect"])
    mock_client_async = MagicMock()
    mock_driver_connect.connect.return_value = mock_client_async
    with patch.dict(sys.modules, {"surrealdb": mock_driver_connect}):
        async_conn = AsyncSurrealDBConnector()

        async def _test():
            c1 = await async_conn.connect()
            assert c1 is mock_client_async
            c2 = await async_conn.connect()
            assert c2 is mock_client_async

        asyncio.run(_test())


# ============================================================================
# 10. Apache Spark SQL Edge Cases
# ============================================================================


def test_spark_adapter_and_lifecycle_branches():
    # Adapter with neither sql nor execute
    adapter_empty = _SparkCursorAdapter(object())
    adapter_empty.execute("SELECT 1")
    assert adapter_empty.description is None
    assert adapter_empty.fetchall() == []

    # Cached connect
    conn = SparkSQLConnector(connection="mock_spark")
    assert conn.connect() == "mock_spark"

    # get_cursor with conn having cursor()
    mock_conn_cur = MagicMock()
    mock_c = MagicMock()
    mock_conn_cur.cursor.return_value = mock_c
    conn_cur = SparkSQLConnector(connection=mock_conn_cur)
    with conn_cur.get_cursor() as c:
        assert c is mock_c
    mock_c.close.assert_called_once()

    # get_cursor with conn having sql()
    mock_conn_sql = MagicMock(spec=["sql"])
    conn_sql = SparkSQLConnector(connection=mock_conn_sql)
    with conn_sql.get_cursor() as c:
        assert isinstance(c, _SparkCursorAdapter)

    # get_cursor with conn having neither cursor nor sql
    conn_none = SparkSQLConnector(connection=object())
    with conn_none.get_cursor() as c:
        assert isinstance(c, _SparkCursorAdapter)

    # Async execute_raw with conn having cursor() and no params
    mock_cur = MagicMock()
    mock_cur.description = [("a",)]
    mock_cur.fetchall.return_value = [(1,)]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    async_conn = AsyncSparkSQLConnector(connection=mock_conn)

    async def _test():
        c1 = await async_conn.connect()
        assert c1 is mock_conn
        cols, rows, _ = await async_conn.execute_raw("SELECT 1")
        assert cols == ["a"] and rows == [{"a": 1}]

    asyncio.run(_test())

    # Async execute_raw with conn having sql()
    mock_spark_session = MagicMock(spec=["sql"])
    mock_df = MagicMock()
    mock_df.columns = ["val"]
    mock_row = MagicMock()
    mock_row.val = 100
    mock_df.collect.return_value = [mock_row]
    mock_spark_session.sql.return_value = mock_df

    async_conn_sql = AsyncSparkSQLConnector(connection=mock_spark_session)

    async def _test_sql():
        cols, rows, _ = await async_conn_sql.execute_raw("SELECT 100", [1])
        assert cols == ["val"] and rows == [{"val": 100}]

    asyncio.run(_test_sql())

    # Async execute_raw with conn having neither cursor nor sql
    async_conn_empty = AsyncSparkSQLConnector(connection=object())

    async def _test_empty():
        cols, rows, _ = await async_conn_empty.execute_raw("SELECT 1", [1])
        assert cols == [] and rows == []

    asyncio.run(_test_empty())


# ============================================================================
# 11. Introspection Branch Edge Cases
# ============================================================================


def test_introspection_missing_branches():
    # 1. Spark SQL: empty/falsy row and comment row
    mock_spark_cur = MagicMock(spec=["execute", "fetchall"])
    mock_spark_cur.fetchall.side_effect = [
        [(), ("main", "tbl1")],  # first is empty tuple
        [None, ("# Comment",), ("id", "bigint")],  # comment and None
    ]
    snap_spark = introspect_sparksql(mock_spark_cur, schema_name="main")
    assert "tbl1" in snap_spark["tables"]
    assert snap_spark["tables"]["tbl1"]["columns"][0]["name"] == "id"

    # 2. TDengine: empty row and column named 'ts'
    mock_taos_cur = MagicMock(spec=["execute", "fetchall"])
    mock_taos_cur.fetchall.side_effect = [
        [("metrics",)],
        [None, ("ts", "TIMESTAMP"), ("val", "DOUBLE")],
    ]
    snap_taos = introspect_tdengine(mock_taos_cur, database="test")
    assert "metrics" in snap_taos["tables"]
    cols_taos = snap_taos["tables"]["metrics"]["columns"]
    assert cols_taos[0]["name"] == "ts" and cols_taos[0]["is_primary"] is True

    # 3. SurrealDB: cur.fetchone() returning None
    mock_surreal_empty = MagicMock(spec=["execute", "fetchone"])
    mock_surreal_empty.fetchone.return_value = None
    snap_surreal_empty = introspect_surrealdb(mock_surreal_empty)
    assert snap_surreal_empty["tables"] == {}

    # SurrealDB: cur.query() returning empty list or non-dict
    mock_surreal_query_empty = MagicMock(spec=["query"])
    mock_surreal_query_empty.query.return_value = []
    snap_surreal_q = introspect_surrealdb(mock_surreal_query_empty)
    assert snap_surreal_q["tables"] == {}

    # 4. ArangoDB: rows with empty tuple or names starting with '_'
    mock_arango_cur = MagicMock(spec=["execute", "fetchall"])
    mock_arango_cur.fetchall.return_value = [
        (),
        [{"name": "_system"}],
        {"name": "_internal"},
        {"name": "valid_coll"},
    ]
    snap_arango = introspect_arangodb(mock_arango_cur)
    assert "valid_coll" in snap_arango["tables"]
    assert "_system" not in snap_arango["tables"]

    # ArangoDB: collections list with item starting with '_'
    mock_arango_db = MagicMock(spec=["collections"])
    mock_arango_db.collections.return_value = [{"name": "_hidden"}, {"name": "visible"}]
    snap_arango_colls = introspect_arangodb(mock_arango_db)
    assert "visible" in snap_arango_colls["tables"]
    assert "_hidden" not in snap_arango_colls["tables"]

    # 5. Cosmos DB: empty row in execute and container with no id
    mock_cosmos_cur = MagicMock(spec=["execute", "fetchall"])
    mock_cosmos_cur.fetchall.return_value = [(), ("container1",)]
    snap_cosmos = introspect_cosmosdb(mock_cosmos_cur)
    assert "container1" in snap_cosmos["tables"]

    mock_cosmos_client = MagicMock(spec=["get_database_client"])
    mock_cosmos_db = MagicMock(spec=["list_containers"])
    mock_cosmos_db.list_containers.return_value = [{}, {"id": "c2"}]
    mock_cosmos_client.get_database_client.return_value = mock_cosmos_db
    snap_cosmos_db = introspect_cosmosdb(mock_cosmos_client)
    assert "c2" in snap_cosmos_db["tables"]


def test_cursor_close_and_introspection_final_branches():
    # Test get_cursor when cursor has no close method (covers if hasattr(cur, "close") False branch)
    mock_cur_noclose = object()
    mock_conn = MagicMock(spec=["cursor"])
    mock_conn.cursor.return_value = mock_cur_noclose

    for conn_cls in [
        TDengineConnector,
        ArangoDBConnector,
        ApacheCassandraConnector,
        ChDBConnector,
        CosmosDBConnector,
        ExasolConnector,
        SparkSQLConnector,
        SurrealDBConnector,
    ]:
        conn = conn_cls(connection=mock_conn)
        with conn.get_cursor() as c:
            assert c is mock_cur_noclose

    # AsyncChDBConnector with driver having no connect method
    mock_driver_no_connect = object()
    with patch.dict(sys.modules, {"chdb": mock_driver_no_connect}):
        async_conn = AsyncChDBConnector()
        assert asyncio.run(async_conn.connect()) is mock_driver_no_connect

    # Introspection empty objects
    assert introspect_surrealdb(object())["tables"] == {}
    assert introspect_arangodb(object())["tables"] == {}

    mock_cur_empty = MagicMock(spec=["execute", "fetchall"])
    mock_cur_empty.fetchall.return_value = []
    snap_empty = introspect_cosmosdb(mock_cur_empty)
    assert "items" in snap_empty["tables"]

    mock_client_no_list = MagicMock(spec=["get_database_client"])
    mock_client_no_list.get_database_client.return_value = object()
    assert "items" in introspect_cosmosdb(mock_client_no_list)["tables"]
