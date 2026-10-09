"""
Comprehensive Unit Tests for Lakehouse, In-Process, Time-Series, Multi-Model, and Enterprise Connectors.
=======================================================================================================
Verifies 100% statement, function, and branch coverage for:
- Apache Spark SQL (PySpark / Thrift)
- chDB (In-process ClickHouse)
- GreptimeDB (Time-series)
- TDengine (IoT Big Data)
- SurrealDB (Multi-model SurrealQL)
- ArangoDB (AQL / Multi-model)
- Apache Cassandra (CQL)
- Exasol (In-memory analytics)
- IBM DB2 (Enterprise relational)
- Azure Cosmos DB (SQL API)
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
    AsyncAzureCosmosDBConnector,
    AsyncCassandraConnector,
    AsyncChDBConnector,
    AsyncCosmosDBConnector,
    AsyncDB2Connector,
    AsyncExasolConnector,
    AsyncGreptimeDBConnector,
    AsyncIBMDB2Connector,
    AsyncSparkConnector,
    AsyncSparkSQLConnector,
    AsyncSurrealDBConnector,
    AsyncTDengineConnector,
    AzureCosmosDBConnector,
    ChDBConnector,
    ConnectionFailedError,
    CosmosDBConnector,
    DB2Connector,
    DriverNotInstalledError,
    ExasolConnector,
    GreptimeDBConnector,
    IBMDB2Connector,
    IntrospectionError,
    SparkConnector,
    SparkSQLConnector,
    SurrealDBConnector,
    TDengineConnector,
    get_connector,
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
# 1. Apache Spark SQL Connector Tests
# ============================================================================


def test_spark_cursor_adapter():
    # 1. SparkSession mock
    mock_df = MagicMock()
    mock_df.columns = ["id", "val"]
    mock_row1 = MagicMock()
    mock_row1.id = "1"
    mock_row1.val = 100
    mock_row1.__getitem__ = lambda self, idx: [self.id, self.val][idx]
    mock_df.collect.return_value = [mock_row1]

    mock_session = MagicMock()
    mock_session.sql.return_value = mock_df

    adapter = _SparkCursorAdapter(mock_session)
    adapter.execute("SELECT * FROM t;")
    assert adapter.description == [("id",), ("val",)]
    assert adapter.fetchone() == ["1", 100]
    assert adapter.fetchall() == []
    adapter.close()

    # 1b. Collect returning scalar / non-getitem
    mock_df_scalar = MagicMock(spec=["collect"])
    mock_df_scalar.collect.return_value = [42]
    mock_session.sql.return_value = mock_df_scalar
    adapter.execute("SELECT 1;")
    assert adapter.fetchall() == [[42]]

    # 1c. df without collect
    mock_df_no_collect = MagicMock(spec=[])
    mock_session.sql.return_value = mock_df_no_collect
    adapter.execute("SELECT 1;")
    assert adapter.fetchall() == []

    # 2. execute mock
    mock_cur = MagicMock(spec=["execute", "description", "fetchall"])
    mock_cur.description = [("col",)]
    mock_cur.fetchall.return_value = [("a",), ("b",)]
    adapter2 = _SparkCursorAdapter(mock_cur)
    adapter2.execute("SELECT col FROM t WHERE x = %s;", ["val"])
    assert adapter2.description == [("col",)]
    assert adapter2.fetchall() == [("a",), ("b",)]

    # 2b. execute without fetchall
    mock_cur_no_fetch = MagicMock(spec=["execute", "description"])
    mock_cur_no_fetch.description = None
    adapter_no_fetch = _SparkCursorAdapter(mock_cur_no_fetch)
    adapter_no_fetch.execute("SELECT 1;")
    assert adapter_no_fetch.fetchall() == []

    # 3. None mock
    adapter3 = _SparkCursorAdapter(object())
    adapter3.execute("SELECT 1;")
    assert adapter3.description is None
    assert adapter3.fetchall() == []


def test_spark_sql_connector_sync_and_introspection():
    conn = SparkSQLConnector(schema_name="analytics")
    assert conn.dialect_name == "sparksql"
    assert conn.schema_name == "analytics"
    assert SparkConnector is SparkSQLConnector

    # Missing driver
    with (
        patch.dict(
            sys.modules,
            {"pyspark": None, "pyspark.sql": None, "pyhive.hive": None, "thrift": None},
        ),
        pytest.raises(DriverNotInstalledError, match="pyspark"),
    ):
        conn.connect()

    # Connection failure
    mock_driver = MagicMock()
    mock_driver.SparkSession.builder.appName.side_effect = RuntimeError(
        "Spark cluster unavailable"
    )
    with (
        patch.dict(sys.modules, {"pyspark.sql": mock_driver}),
        pytest.raises(
            ConnectionFailedError, match="Failed to connect to Apache Spark SQL"
        ),
    ):
        conn.connect()

    # Successful connect with SparkSession
    mock_spark = MagicMock()
    mock_builder = MagicMock()
    mock_builder.appName.return_value = mock_builder
    mock_builder.config.return_value = mock_builder
    mock_builder.getOrCreate.return_value = mock_spark
    mock_driver.SparkSession.builder = mock_builder

    conn_with_cfg = SparkSQLConnector(schema_name="analytics", master="local[*]")
    with patch.dict(sys.modules, {"pyspark.sql": mock_driver}):
        res_conn = conn_with_cfg.connect()
        assert res_conn is mock_spark

    # Successful connect with fallback driver.connect
    mock_driver2 = MagicMock(spec=["connect"])
    mock_conn = MagicMock()
    mock_driver2.connect.return_value = mock_conn
    conn_fallback = SparkSQLConnector(schema_name="analytics")
    with patch.dict(
        sys.modules,
        {"pyspark.sql": None, "pyhive.hive": mock_driver2},
    ):
        assert conn_fallback.connect() is mock_conn

    # get_cursor variants
    mock_cur = MagicMock()
    conn_with_cur = SparkSQLConnector(cursor=mock_cur)
    with conn_with_cur.get_cursor() as cur:
        assert cur is mock_cur

    mock_conn_with_cursor = MagicMock()
    mock_conn_with_cursor.cursor.return_value = mock_cur
    conn_cur_method = SparkSQLConnector(connection=mock_conn_with_cursor)
    with conn_cur_method.get_cursor() as cur:
        assert cur is mock_cur
    mock_cur.close.assert_called()

    # Statement timeout & test_connection
    conn_with_cur.apply_statement_timeout(mock_cur, 5000)
    info = conn_with_cur.test_connection()
    assert info["engine_version"] == "Apache Spark SQL"
    assert info["schema_name"] == "default"

    # Introspect schema
    mock_cur.execute.side_effect = [
        [("analytics", "users", False)],  # SHOW TABLES IN
        [
            ("id", "bigint", None),
            ("name", "string", None),
            ("user_id", "string", None),
        ],  # DESCRIBE
    ]
    mock_cur.fetchall.side_effect = [
        [("analytics", "users", False)],
        [("id", "bigint", None), ("name", "string", None), ("user_id", "string", None)],
    ]
    snap = conn_with_cur.introspect_schema()
    assert "users" in snap["tables"]
    with patch.object(conn_with_cur, "introspect_schema", return_value=snap):
        assert conn_with_cur.inspect_tables() == ["users"]
        assert len(conn_with_cur.inspect_columns("users")) == 3
        assert conn_with_cur.inspect_primary_keys("users") == ["id"]
        assert conn_with_cur.inspect_foreign_keys("users") == []

    # Introspect error
    mock_cur.execute.side_effect = RuntimeError("Introspection boom")
    with pytest.raises(IntrospectionError, match="Failed to introspect Spark SQL"):
        conn_with_cur.introspect_schema()


def test_spark_sql_connector_execution():
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = [1]
    mock_cur.description = [("id",), ("name",)]
    mock_cur.fetchall.return_value = [(1, "Alice")]

    conn = SparkSQLConnector(cursor=mock_cur)
    spec = {
        "table": "users",
        "columns": ["id", "name"],
        "limit": 10,
        "offset": 0,
    }
    res = conn.execute(spec)
    assert res["count"] == 1
    assert res["rows"] == [{"id": 1, "name": "Alice"}]


def test_spark_sql_async_connector():
    async def _test():
        conn = AsyncSparkSQLConnector(schema_name="lake")
        assert conn.dialect_name == "sparksql"
        assert AsyncSparkConnector is AsyncSparkSQLConnector

        # Driver missing
        with (
            patch.dict(
                sys.modules,
                {
                    "pyspark": None,
                    "pyspark.sql": None,
                    "pyhive.hive": None,
                    "thrift": None,
                },
            ),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection failure
        mock_driver = MagicMock()
        mock_driver.SparkSession.builder.appName.side_effect = RuntimeError(
            "Async fail"
        )
        with (
            patch.dict(sys.modules, {"pyspark.sql": mock_driver}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # Successful connect with SparkSession
        mock_spark = MagicMock()
        mock_builder = MagicMock()
        mock_builder.appName.return_value = mock_builder
        mock_builder.config.return_value = mock_builder
        mock_builder.getOrCreate.return_value = mock_spark
        mock_driver.SparkSession.builder = mock_builder

        conn_cfg = AsyncSparkSQLConnector(schema_name="lake", foo="bar")
        with patch.dict(sys.modules, {"pyspark.sql": mock_driver}):
            assert (await conn_cfg.connect()) is mock_spark

        # Successful fallback connect
        mock_driver2 = MagicMock(spec=["connect"])
        mock_conn = MagicMock()
        mock_driver2.connect.return_value = mock_conn
        conn_fallback = AsyncSparkSQLConnector()
        with patch.dict(
            sys.modules,
            {"pyspark.sql": None, "pyhive.hive": mock_driver2},
        ):
            assert (await conn_fallback.connect()) is mock_conn

        # execute_raw with cursor
        mock_cur = MagicMock()
        mock_cur.description = [("id",)]
        mock_cur.fetchall.return_value = [(10,)]
        mock_conn_cur = MagicMock(spec=["cursor"])
        mock_conn_cur.cursor.return_value = mock_cur
        conn_async = AsyncSparkSQLConnector(connection=mock_conn_cur)
        cols, rows, lat = await conn_async.execute_raw("SELECT 10;", [1])
        assert cols == ["id"]
        assert rows == [{"id": 10}]
        assert lat >= 0

        # execute_raw with adapter
        mock_df = MagicMock()
        mock_df.columns = ["val"]
        mock_row = MagicMock()
        mock_row.val = 99
        mock_df.collect.return_value = [mock_row]
        mock_spark.sql.return_value = mock_df
        del mock_spark.cursor
        conn_adapter = AsyncSparkSQLConnector(connection=mock_spark)
        cols, rows, lat = await conn_adapter.execute_raw("SELECT 99;")
        assert cols == ["val"]
        assert rows == [{"val": 99}]

        # async test_connection and close
        info = await conn_adapter.test_connection()
        assert info["status"] == "healthy"
        await conn_adapter.close()

    asyncio.run(_test())


def test_introspect_sparksql_branches():
    mock_cur = MagicMock()
    # SHOW TABLES fails, fallback to information_schema
    mock_cur.execute.side_effect = [
        RuntimeError("No SHOW TABLES"),
        [("tbl1",)],
        RuntimeError("No DESCRIBE"),
    ]
    mock_cur.fetchall.side_effect = [
        [("tbl1",)],
    ]
    snap = introspect_sparksql(mock_cur, schema_name="default")
    assert "tbl1" in snap["tables"]

    # Total failure
    mock_cur.execute.side_effect = RuntimeError("Fatal catalog error")
    with pytest.raises(IntrospectionError):
        introspect_sparksql(mock_cur)


# ============================================================================
# 2. chDB Connector Tests
# ============================================================================


def test_chdb_cursor_adapter():
    mock_chdb = MagicMock()
    mock_res = MagicMock()
    mock_res.bytes = b'{"id": 1, "name": "foo"}\n{"id": 2, "name": "bar"}\n'
    mock_chdb.query.return_value = mock_res

    adapter = _ChDBCursorAdapter(mock_chdb)
    adapter.execute("SELECT * FROM t WHERE id = %s;", [1])
    assert adapter.description == [("id",), ("name",)]
    assert adapter.fetchone() == [1, "foo"]
    assert adapter.fetchall() == [[2, "bar"]]
    adapter.close()

    # Empty query output
    mock_res_empty = MagicMock()
    mock_res_empty.bytes = b""
    mock_chdb.query.return_value = mock_res_empty
    adapter.execute("SELECT * FROM empty;")
    assert adapter.description == []
    assert adapter.fetchall() == []

    # Execute fallback
    mock_chdb2 = MagicMock(spec=["execute", "fetchall", "description"])
    mock_chdb2.description = [("cnt",)]
    mock_chdb2.fetchall.return_value = [(100,)]
    adapter2 = _ChDBCursorAdapter(mock_chdb2)
    adapter2.execute("SELECT 100;")
    assert adapter2.description == [("cnt",)]
    assert adapter2.fetchall() == [(100,)]

    # Query failure
    mock_chdb.query.side_effect = RuntimeError("Parse error")
    with pytest.raises(RuntimeError, match="chDB query execution failed"):
        adapter.execute("BAD SQL;")

    # Adapter with dummy object
    adapter_empty = _ChDBCursorAdapter(object())
    adapter_empty.execute("SELECT 1;")
    assert adapter_empty.description == []


def test_chdb_connector_sync_and_async():
    conn = ChDBConnector(database="analytics")
    assert conn.dialect_name == "chdb"
    assert conn.database == "analytics"

    # Driver missing
    with (
        patch.dict(sys.modules, {"chdb": None, "chdb.dbapi": None}),
        pytest.raises(DriverNotInstalledError, match="chdb"),
    ):
        conn.connect()

    # Connection failure
    mock_driver = MagicMock()
    mock_driver.connect.side_effect = RuntimeError("chdb init failed")
    with (
        patch.dict(sys.modules, {"chdb.dbapi": mock_driver}),
        pytest.raises(ConnectionFailedError),
    ):
        conn.connect()

    # Successful connect via dbapi
    mock_dbapi_conn = MagicMock()
    mock_driver.connect.side_effect = None
    mock_driver.connect.return_value = mock_dbapi_conn
    with patch.dict(sys.modules, {"chdb.dbapi": mock_driver}):
        assert conn.connect() is mock_dbapi_conn

    # Successful connect via raw chdb module
    conn2 = ChDBConnector()
    mock_raw_chdb = MagicMock(spec=["query"])
    with patch.dict(sys.modules, {"chdb.dbapi": None, "chdb": mock_raw_chdb}):
        assert conn2.connect() is mock_raw_chdb

    # get_cursor variants
    mock_cur = MagicMock()
    conn_cur = ChDBConnector(cursor=mock_cur)
    with conn_cur.get_cursor() as cur:
        assert cur is mock_cur

    conn_cur.apply_statement_timeout(mock_cur, 1000)
    info = conn_cur.test_connection()
    assert info["engine_version"].startswith("chDB")

    # Introspection
    mock_cur.fetchall.side_effect = [
        [("events",)],
        [("events", "id", "UInt64"), ("events", "tag", "Nullable(String)")],
    ]
    snap = conn_cur.introspect_schema()
    assert "events" in snap["tables"]
    cols = snap["tables"]["events"]["columns"]
    assert cols[0]["name"] == "id" and cols[0]["is_primary"] is True
    assert cols[1]["is_nullable"] is True

    # Introspection failure
    mock_cur.fetchall.side_effect = RuntimeError("Introspect error")
    with pytest.raises(IntrospectionError):
        conn_cur.introspect_schema()


def test_async_chdb_connector():
    async def _test():
        conn = AsyncChDBConnector(database="db")
        assert conn.dialect_name == "chdb"

        # Driver missing
        with (
            patch.dict(sys.modules, {"chdb": None, "chdb.dbapi": None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection failure
        mock_driver = MagicMock()
        mock_driver.connect.side_effect = RuntimeError("Init fail")
        with (
            patch.dict(sys.modules, {"chdb.dbapi": mock_driver}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # Success connect
        mock_driver.connect.side_effect = None
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.description = [("res",)]
        mock_cur.fetchall.return_value = [(42,)]
        mock_conn.cursor.return_value = mock_cur
        mock_driver.connect.return_value = mock_conn

        with patch.dict(sys.modules, {"chdb.dbapi": mock_driver}):
            assert (await conn.connect()) is mock_conn
            cols, rows, _lat = await conn.execute_raw("SELECT 42;")
            assert cols == ["res"]
            assert rows == [{"res": 42}]

            # execute_raw with params
            cols, rows, _lat = await conn.execute_raw("SELECT %s;", [42])
            assert cols == ["res"]

        # execute_raw with adapter
        mock_chdb = MagicMock(spec=["query"])
        mock_res = MagicMock()
        mock_res.bytes = b'{"x": 10}\n'
        mock_chdb.query.return_value = mock_res
        conn_adapter = AsyncChDBConnector(connection=mock_chdb)
        cols, rows, _lat = await conn_adapter.execute_raw("SELECT 10;")
        assert cols == ["x"]
        assert rows == [{"x": 10}]

    asyncio.run(_test())


# ============================================================================
# 3. GreptimeDB Connector Tests
# ============================================================================


def test_greptimedb_connector():
    conn = GreptimeDBConnector(schema_name="ts")
    assert conn.dialect_name == "greptimedb"
    assert conn.schema_name == "ts"

    # Missing driver
    with (
        patch.dict(
            sys.modules,
            {"greptimedb": None, "psycopg2": None, "psycopg": None, "pymysql": None},
        ),
        pytest.raises(DriverNotInstalledError, match="greptimedb"),
    ):
        conn.connect()

    # Connection failure
    mock_driver = MagicMock()
    mock_driver.connect.side_effect = RuntimeError("GreptimeDB unreachable")
    with (
        patch.dict(sys.modules, {"greptimedb": mock_driver}),
        pytest.raises(ConnectionFailedError),
    ):
        conn.connect()

    # Successful connect
    mock_conn = MagicMock()
    mock_driver.connect.side_effect = None
    mock_driver.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"greptimedb": mock_driver}):
        assert conn.connect() is mock_conn

    # test_connection & introspect
    mock_cur = MagicMock()
    conn_cur = GreptimeDBConnector(cursor=mock_cur, schema_name="ts")
    info = conn_cur.test_connection()
    assert info["engine_version"] == "GreptimeDB"
    assert info["schema_name"] == "ts"

    mock_cur.fetchall.side_effect = [
        [("cpu_metrics",)],
        [
            ("cpu_metrics", "greptime_timestamp", "Timestamp", "NO"),
            ("cpu_metrics", "usage", "Float64", "YES"),
        ],
    ]
    snap = conn_cur.introspect_schema()
    assert "cpu_metrics" in snap["tables"]
    cols = snap["tables"]["cpu_metrics"]["columns"]
    assert cols[0]["is_primary"] is True
    assert cols[1]["is_nullable"] is True

    # Introspect error
    mock_cur.fetchall.side_effect = RuntimeError("TS introspection error")
    with pytest.raises(IntrospectionError):
        conn_cur.introspect_schema()


def test_async_greptimedb_connector():
    async def _test():
        conn = AsyncGreptimeDBConnector(schema_name="public")
        assert conn.dialect_name == "greptimedb"

        # Missing driver
        with (
            patch.dict(
                sys.modules,
                {
                    "greptimedb": None,
                    "psycopg": None,
                    "asyncpg": None,
                    "pymysql": None,
                },
            ),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection failure
        mock_driver = MagicMock()
        mock_driver.connect.side_effect = RuntimeError("Async Greptime fail")
        with (
            patch.dict(sys.modules, {"greptimedb": mock_driver}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # Successful execute_raw
        mock_cur = MagicMock()
        mock_cur.description = [("val",)]
        mock_cur.fetchall.return_value = [(100,)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        conn_exec = AsyncGreptimeDBConnector(connection=mock_conn)

        cols, rows, _lat = await conn_exec.execute_raw("SELECT 100;", [1])
        assert cols == ["val"]
        assert rows == [{"val": 100}]

        cols2, _rows2, _ = await conn_exec.execute_raw("SELECT 100;")
        assert cols2 == ["val"]

    asyncio.run(_test())


# ============================================================================
# 4. TDengine Connector Tests
# ============================================================================


def test_tdengine_cursor_adapter():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.description = [("ts",), ("v",)]
    mock_cur.fetchall.return_value = [("2026-01-01", 220)]
    mock_conn.cursor.return_value = mock_cur

    adapter = _TDengineCursorAdapter(mock_conn)
    adapter.execute("SELECT * FROM m;", [1])
    assert adapter.description == [("ts",), ("v",)]
    assert adapter.fetchone() == ("2026-01-01", 220)
    assert adapter.fetchall() == []
    adapter.close()

    # Adapter with execute method directly
    mock_target = MagicMock(spec=["execute", "fetchall", "description"])
    mock_target.description = [("c",)]
    mock_target.fetchall.return_value = [(1,)]
    adapter2 = _TDengineCursorAdapter(mock_target)
    adapter2.execute("SELECT 1;", [1])
    assert adapter2.description == [("c",)]
    assert adapter2.fetchall() == [(1,)]

    # Adapter with empty object
    adapter_empty = _TDengineCursorAdapter(object())
    adapter_empty.execute("SELECT 1;")
    assert adapter_empty.description is None


def test_tdengine_connector_sync_and_async():
    conn = TDengineConnector(database="power")
    assert conn.dialect_name == "tdengine"
    assert conn.database == "power"

    # Missing driver
    with (
        patch.dict(sys.modules, {"taos": None, "taosrest": None, "taospy": None}),
        pytest.raises(DriverNotInstalledError, match="taos"),
    ):
        conn.connect()

    # Connection failure
    mock_driver = MagicMock()
    mock_driver.connect.side_effect = RuntimeError("TDengine host down")
    with (
        patch.dict(sys.modules, {"taos": mock_driver}),
        pytest.raises(ConnectionFailedError),
    ):
        conn.connect()

    # Successful connect
    mock_conn = MagicMock()
    mock_driver.connect.side_effect = None
    mock_driver.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"taos": mock_driver}):
        assert conn.connect() is mock_conn

    # get_cursor variants
    mock_cur = MagicMock()
    conn_cur = TDengineConnector(cursor=mock_cur)
    with conn_cur.get_cursor() as cur:
        assert cur is mock_cur

    info = conn_cur.test_connection()
    assert info["engine_version"] == "TDengine"
    assert info["database"] == "default"

    # Introspection
    mock_cur.fetchall.side_effect = [
        [("meters",)],
        [("ts", "TIMESTAMP"), ("current", "FLOAT")],
    ]
    snap = conn_cur.introspect_schema()
    assert "meters" in snap["tables"]
    cols = snap["tables"]["meters"]["columns"]
    assert cols[0]["name"] == "ts" and cols[0]["is_primary"] is True
    assert cols[1]["is_nullable"] is True

    # Introspection failure
    mock_cur.fetchall.side_effect = RuntimeError("Introspection fail")
    with pytest.raises(IntrospectionError):
        conn_cur.introspect_schema()


def test_async_tdengine_connector():
    async def _test():
        conn = AsyncTDengineConnector(database="iot")
        assert conn.dialect_name == "tdengine"

        # Missing driver
        with (
            patch.dict(sys.modules, {"taos": None, "taosrest": None, "taospy": None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection failure
        mock_driver = MagicMock()
        mock_driver.connect.side_effect = RuntimeError("Async connect fail")
        with (
            patch.dict(sys.modules, {"taos": mock_driver}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # Success execute_raw
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.description = [("val",)]
        mock_cur.fetchall.return_value = [(10,)]
        mock_conn.cursor.return_value = mock_cur
        conn_exec = AsyncTDengineConnector(connection=mock_conn)

        cols, rows, _lat = await conn_exec.execute_raw("SELECT 10;", [1])
        assert cols == ["val"]
        assert rows == [{"val": 10}]

    asyncio.run(_test())


def test_introspect_tdengine_fallback():
    mock_cur = MagicMock()
    # SHOW db.TABLES fails, falls back to SHOW TABLES
    mock_cur.execute.side_effect = [
        RuntimeError("DB syntax error"),
        [("sensor",)],
        [("ts", "TIMESTAMP")],
    ]
    mock_cur.fetchall.side_effect = [
        [("sensor",)],
        [("ts", "TIMESTAMP")],
    ]
    snap = introspect_tdengine(mock_cur, database="test")
    assert "sensor" in snap["tables"]


# ============================================================================
# 5. SurrealDB Connector Tests
# ============================================================================


def test_surrealdb_cursor_adapter():
    mock_client = MagicMock()
    # 1. query returning list of dicts with result list
    mock_client.query.return_value = [
        {"result": [{"id": "user:1", "name": "Alice"}, {"id": "user:2", "name": "Bob"}]}
    ]
    adapter = _SurrealCursorAdapter(mock_client)
    adapter.execute("SELECT * FROM user;", {"name": "Alice"})
    assert adapter.description == [("id",), ("name",)]
    assert adapter.fetchone() == ["user:1", "Alice"]
    assert adapter.fetchall() == [["user:2", "Bob"]]
    adapter.close()

    # 2. query returning scalar result items
    mock_client.query.return_value = [{"result": ["val1", "val2"]}]
    adapter.execute("SELECT 1;")
    assert adapter.description == [("value",)]
    assert adapter.fetchall() == [["val1"], ["val2"]]

    # 3. query returning empty result
    mock_client.query.return_value = [{"result": []}]
    adapter.execute("SELECT 1;")
    assert adapter.description == []
    assert adapter.fetchall() == []

    # 4. query returning dict
    mock_client.query.return_value = {"id": "1", "data": "abc"}
    adapter.execute("SELECT 1;")
    assert adapter.description == [("id",), ("data",)]
    assert adapter.fetchall() == [["1", "abc"]]

    # 5. query returning a bare scalar (SDK >= 1.0 returns the statement result directly)
    mock_client.query.return_value = 123
    adapter.execute("SELECT 1;")
    assert adapter.description == [("value",)]
    assert adapter.fetchall() == [[123]]

    # 6. execute fallback
    mock_client2 = MagicMock(spec=["execute", "description", "fetchall"])
    mock_client2.description = [("col",)]
    mock_client2.fetchall.return_value = [(99,)]
    adapter2 = _SurrealCursorAdapter(mock_client2)
    adapter2.execute("SELECT 99;", [1])
    assert adapter2.description == [("col",)]
    assert adapter2.fetchall() == [(99,)]

    # 7. empty object
    adapter_empty = _SurrealCursorAdapter(object())
    adapter_empty.execute("SELECT 1;")
    assert adapter_empty.description == []


def test_surrealdb_connector_sync_and_async():
    conn = SurrealDBConnector(database="testdb", namespace="testns")
    assert conn.dialect_name == "surrealdb"
    assert conn.database == "testdb"
    assert conn.namespace == "testns"

    # Missing driver
    with (
        patch.dict(sys.modules, {"surrealdb": None, "surrealdb.ws": None}),
        pytest.raises(DriverNotInstalledError, match="surrealdb"),
    ):
        conn.connect()

    # Connection failure
    mock_driver = MagicMock()
    mock_driver.Surreal.side_effect = RuntimeError("Surreal connection error")
    with (
        patch.dict(sys.modules, {"surrealdb": mock_driver}),
        pytest.raises(ConnectionFailedError),
    ):
        conn.connect()

    # Successful connect via Surreal cls
    mock_client = MagicMock()
    mock_driver.Surreal.side_effect = None
    mock_driver.Surreal.return_value = mock_client
    with patch.dict(sys.modules, {"surrealdb": mock_driver}):
        assert conn.connect() is mock_client

    # Successful connect via driver.connect fallback
    mock_driver2 = MagicMock(spec=["connect"])
    mock_driver2.connect.return_value = mock_client
    conn_fallback = SurrealDBConnector()
    with patch.dict(sys.modules, {"surrealdb": mock_driver2}):
        assert conn_fallback.connect() is mock_client

    # get_cursor variants
    mock_cur = MagicMock()
    conn_cur = SurrealDBConnector(cursor=mock_cur)
    with conn_cur.get_cursor() as cur:
        assert cur is mock_cur

    info = conn_cur.test_connection()
    assert info["engine_version"] == "SurrealDB"
    assert info["database"] == "test"

    # Introspection
    snap = _surreal_introspection(
        conn_cur, mock_cur, {"tables": {"users": "DEFINE TABLE users;"}}
    )
    assert "users" in snap["tables"]
    cols = snap["tables"]["users"]["columns"]
    assert cols[0]["name"] == "id" and cols[0]["is_primary"] is True

    # Introspection failure
    mock_cur.execute.side_effect = RuntimeError("Introspection error")
    with pytest.raises(IntrospectionError):
        conn_cur.introspect_schema()


def test_async_surrealdb_connector():
    async def _test():
        conn = AsyncSurrealDBConnector()
        assert conn.dialect_name == "surrealdb"

        # Missing driver
        with (
            patch.dict(sys.modules, {"surrealdb": None, "surrealdb.ws": None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection failure
        mock_driver = MagicMock()
        mock_driver.AsyncSurreal.side_effect = RuntimeError("Async fail")
        with (
            patch.dict(sys.modules, {"surrealdb": mock_driver}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # Successful execute_raw
        mock_client = MagicMock()
        mock_client.query.return_value = [{"result": [{"val": 100}]}]
        conn_exec = AsyncSurrealDBConnector(connection=mock_client)
        cols, rows, _lat = await conn_exec.execute_raw("SELECT 100;", [1])
        assert cols == ["val"]
        assert rows == [{"val": 100}]

    asyncio.run(_test())


def _surreal_introspection(conn, mock_cur, info):
    """Drive introspection of ``conn`` through ``mock_cur`` answering the INFO/SELECT queries."""
    answers = {"INFO FOR DB": info, "INFO FOR TABLE": {}, "SELECT": None}
    state = {"rows": []}

    def execute(sql, params=None):
        for prefix, value in answers.items():
            if sql.startswith(prefix):
                state["rows"] = [] if value is None else [list(value.values())]
                mock_cur.description = [(k,) for k in (value or {})]
                return

    mock_cur.execute.side_effect = execute
    mock_cur.fetchall.side_effect = lambda: state["rows"]
    return conn.introspect_schema()


def test_introspect_surrealdb_variants():
    # 1. INFO FOR DB lists the tables; undeclared tables are sampled (here: empty)
    mock_cur1 = MagicMock()
    snap1 = _surreal_introspection(
        SurrealDBConnector(cursor=mock_cur1),
        mock_cur1,
        {"tables": {"orders": "DEFINE TABLE orders;"}},
    )
    assert list(snap1["tables"]) == ["orders"]
    # nothing is invented: only the record id for an empty, schemaless table
    assert [c["name"] for c in snap1["tables"]["orders"]["columns"]] == ["id"]

    # 2. a raw SDK client (only .query) is wrapped; SDK >= 1.0 result shape
    answers = {
        "INFO FOR DB": {"tables": {"audit": ""}},
        "INFO FOR TABLE": {
            "fields": {"actor": "DEFINE FIELD actor ON audit TYPE string"}
        },
        "SELECT": [{"id": "audit:1", "actor": "x", "n": 3}],
    }
    mock_client = MagicMock(spec=["query"])
    mock_client.query.side_effect = lambda sql, vars=None: next(
        v for k, v in answers.items() if sql.startswith(k)
    )
    snap2 = introspect_surrealdb(mock_client)
    cols = {c["name"]: c["data_type"] for c in snap2["tables"]["audit"]["columns"]}
    assert cols == {"id": "record", "actor": "string", "n": "number"}


# ============================================================================
# 6. ArangoDB Connector Tests
# ============================================================================


def test_arango_cursor_adapter():
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__iter__.return_value = [
        {"_key": "k1", "val": 10},
        {"_key": "k2", "val": 20},
    ]
    mock_db.aql.execute.return_value = mock_cursor

    adapter = _ArangoCursorAdapter(mock_db)
    adapter.execute("FOR doc IN coll RETURN doc;", ["val"])
    assert adapter.description == [("_key",), ("val",)]
    assert adapter.fetchone() == ["k1", 10]
    assert adapter.fetchall() == [["k2", 20]]
    adapter.close()

    # Scalar docs
    mock_cursor2 = MagicMock()
    mock_cursor2.__iter__.return_value = ["res1", "res2"]
    mock_db.aql.execute.return_value = mock_cursor2
    adapter.execute("FOR d IN coll RETURN d._id;")
    assert adapter.description == [("value",)]
    assert adapter.fetchall() == [["res1"], ["res2"]]

    # Empty docs
    mock_cursor3 = MagicMock()
    mock_cursor3.__iter__.return_value = []
    mock_db.aql.execute.return_value = mock_cursor3
    adapter.execute("RETURN [];")
    assert adapter.description == []
    assert adapter.fetchall() == []

    # Execute fallback
    mock_db2 = MagicMock(spec=["execute", "description", "fetchall"])
    mock_db2.description = [("c",)]
    mock_db2.fetchall.return_value = [(10,)]
    adapter2 = _ArangoCursorAdapter(mock_db2)
    adapter2.execute("SELECT 10;", [1])
    assert adapter2.description == [("c",)]
    assert adapter2.fetchall() == [(10,)]

    # Empty object
    adapter_empty = _ArangoCursorAdapter(object())
    adapter_empty.execute("SELECT 1;")
    assert adapter_empty.description == []


def test_arangodb_connector_sync_and_async():
    conn = ArangoDBConnector(database="graph_db", username="admin")
    assert conn.dialect_name == "arangodb"
    assert conn.database == "graph_db"
    assert conn.username == "admin"

    # Missing driver
    with (
        patch.dict(sys.modules, {"arango": None, "arango.client": None}),
        pytest.raises(DriverNotInstalledError, match="python-arango"),
    ):
        conn.connect()

    # Connection failure
    mock_driver = MagicMock()
    mock_driver.ArangoClient.side_effect = RuntimeError("ArangoDB down")
    with (
        patch.dict(sys.modules, {"arango": mock_driver}),
        pytest.raises(ConnectionFailedError),
    ):
        conn.connect()

    # Successful connect
    mock_client = MagicMock()
    mock_db = MagicMock()
    mock_client.db.return_value = mock_db
    mock_driver.ArangoClient.side_effect = None
    mock_driver.ArangoClient.return_value = mock_client
    with patch.dict(sys.modules, {"arango": mock_driver}):
        assert conn.connect() is mock_db

    # get_cursor variants
    mock_cur = MagicMock()
    conn_cur = ArangoDBConnector(cursor=mock_cur)
    with conn_cur.get_cursor() as cur:
        assert cur is mock_cur

    info = conn_cur.test_connection()
    assert info["engine_version"] == "ArangoDB"
    assert info["database"] == "_system"

    # Introspection via collections()
    mock_db_introspection = MagicMock(spec=["collections"])
    mock_db_introspection.collections.return_value = [
        {"name": "nodes"},
        {"name": "_system_coll"},
    ]
    snap = introspect_arangodb(mock_db_introspection)
    assert "nodes" in snap["tables"]
    assert "_system_coll" not in snap["tables"]

    # Introspection via execute() returning dict items and list items
    mock_cur_ar = MagicMock(spec=["execute", "fetchall"])
    mock_cur_ar.fetchall.return_value = [
        [[{"name": "edges"}, {"name": "_internal"}]],
        [{"name": "extra"}],
        ["plain_table"],
    ]
    snap2 = introspect_arangodb(mock_cur_ar)
    assert "edges" in snap2["tables"]
    assert "extra" in snap2["tables"]
    assert "plain_table" in snap2["tables"]

    # Introspection error
    mock_db_introspection.collections.side_effect = RuntimeError("Introspect fail")
    with pytest.raises(IntrospectionError):
        introspect_arangodb(mock_db_introspection)


def test_async_arangodb_connector():
    async def _test():
        conn = AsyncArangoDBConnector()
        assert conn.dialect_name == "arangodb"

        # Driver missing
        with (
            patch.dict(sys.modules, {"arango": None, "arango.client": None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection failure
        mock_driver = MagicMock()
        mock_driver.ArangoClient.side_effect = RuntimeError("Async connect fail")
        with (
            patch.dict(sys.modules, {"arango": mock_driver}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # Successful execute_raw
        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__iter__.return_value = [{"cnt": 42}]
        mock_db.aql.execute.return_value = mock_cursor

        conn_exec = AsyncArangoDBConnector(connection=mock_db)
        cols, rows, _lat = await conn_exec.execute_raw("RETURN 42;", [1])
        assert cols == ["cnt"]
        assert rows == [{"cnt": 42}]

    asyncio.run(_test())


# ============================================================================
# 7. Apache Cassandra Connector Tests
# ============================================================================


def test_cassandra_cursor_adapter():
    mock_session = MagicMock()
    mock_res = MagicMock()
    mock_res.column_names = ["pk", "val"]
    mock_res.all.return_value = [{"pk": "p1", "val": 10}, {"pk": "p2", "val": 20}]
    mock_session.execute.return_value = mock_res

    adapter = _CassandraCursorAdapter(mock_session)
    adapter.execute("SELECT * FROM t WHERE pk = %s;", ["p1"])
    assert adapter.description == [("pk",), ("val",)]
    assert adapter.fetchone() == ["p1", 10]
    assert adapter.fetchall() == [["p2", 20]]
    adapter.close()

    # Description and fetchall
    mock_res2 = MagicMock(spec=["description", "fetchall"])
    mock_res2.description = [("id",)]
    mock_res2.fetchall.return_value = [(1,), (2,)]
    mock_session.execute.return_value = mock_res2
    adapter.execute("SELECT 1;")
    assert adapter.description == [("id",)]
    assert adapter.fetchall() == [[1], [2]]

    # None description & scalar list
    mock_session.execute.return_value = [5, 6]
    adapter.execute("SELECT 1;")
    assert adapter.fetchall() == [[5], [6]]

    # Cursor fallback
    mock_session_cur = MagicMock(spec=["cursor"])
    mock_cur = MagicMock()
    mock_cur.description = [("x",)]
    mock_cur.fetchall.return_value = [(10,)]
    mock_session_cur.cursor.return_value = mock_cur
    adapter2 = _CassandraCursorAdapter(mock_session_cur)
    adapter2.execute("SELECT 10;", [1])
    assert adapter2.description == [("x",)]
    assert adapter2.fetchall() == [(10,)]

    # Empty object
    adapter_empty = _CassandraCursorAdapter(object())
    adapter_empty.execute("SELECT 1;")
    assert adapter_empty.description is None


def test_cassandra_connector_sync_and_async():
    conn = ApacheCassandraConnector(keyspace="my_ks")
    assert conn.dialect_name == "cassandra"
    assert conn.keyspace == "my_ks"

    # Missing driver
    with (
        patch.dict(sys.modules, {"cassandra": None, "cassandra.cluster": None}),
        pytest.raises(DriverNotInstalledError, match="cassandra-driver"),
    ):
        conn.connect()

    # Connection failure
    mock_driver = MagicMock()
    mock_driver.Cluster.side_effect = RuntimeError("Cassandra node unavailable")
    with (
        patch.dict(sys.modules, {"cassandra.cluster": mock_driver}),
        pytest.raises(ConnectionFailedError),
    ):
        conn.connect()

    # Successful connect
    mock_cluster = MagicMock()
    mock_session = MagicMock()
    mock_cluster.connect.return_value = mock_session
    mock_driver.Cluster.side_effect = None
    mock_driver.Cluster.return_value = mock_cluster

    with patch.dict(sys.modules, {"cassandra.cluster": mock_driver}):
        assert conn.connect() is mock_session

    # get_cursor variants
    mock_cur = MagicMock(spec=["execute", "fetchall", "fetchone"])
    conn_cur = ApacheCassandraConnector(cursor=mock_cur)
    with conn_cur.get_cursor() as cur:
        assert cur is mock_cur

    info = conn_cur.test_connection()
    assert info["engine_version"] == "Apache Cassandra"
    assert info["keyspace"] == "system"

    # Introspection
    mock_cur.fetchall.side_effect = [
        [("users",)],
        [
            ("users", "id", "uuid", "partition_key"),
            ("users", "name", "text", "regular"),
        ],
    ]
    snap = conn_cur.introspect_schema()
    assert "users" in snap["tables"]
    cols = snap["tables"]["users"]["columns"]
    assert cols[0]["name"] == "id" and cols[0]["is_primary"] is True
    assert cols[1]["is_nullable"] is True

    # Introspection failure
    mock_cur.fetchall.side_effect = RuntimeError("Introspection fail")
    with pytest.raises(IntrospectionError):
        conn_cur.introspect_schema()


def test_async_cassandra_connector():
    async def _test():
        conn = AsyncCassandraConnector()
        assert conn.dialect_name == "cassandra"

        # Missing driver
        with (
            patch.dict(sys.modules, {"cassandra": None, "cassandra.cluster": None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection failure
        mock_driver = MagicMock()
        mock_driver.Cluster.side_effect = RuntimeError("Async connect fail")
        with (
            patch.dict(sys.modules, {"cassandra.cluster": mock_driver}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # Successful execute_raw
        mock_session = MagicMock()
        mock_res = MagicMock()
        mock_res.column_names = ["val"]
        mock_res.all.return_value = [(10,)]
        mock_session.execute.return_value = mock_res

        conn_exec = AsyncCassandraConnector(connection=mock_session)
        cols, rows, _lat = await conn_exec.execute_raw("SELECT 10;", [1])
        assert cols == ["val"]
        assert rows == [{"val": 10}]

    asyncio.run(_test())


# ============================================================================
# 8. Exasol Connector Tests
# ============================================================================


def test_exasol_cursor_adapter():
    mock_conn = MagicMock()
    mock_stmt = MagicMock(spec=["columns", "fetchall_dict"])
    mock_stmt.columns.return_value = {"id": {}, "name": {}}
    mock_stmt.fetchall_dict.return_value = [{"id": 1, "name": "foo"}]
    mock_conn.execute.return_value = mock_stmt

    adapter = _ExasolCursorAdapter(mock_conn)
    adapter.execute("SELECT * FROM t;", [1])
    assert adapter.description == [("id",), ("name",)]
    assert adapter.fetchone() == [1, "foo"]
    assert adapter.fetchall() == []
    adapter.close()

    # Empty dicts
    mock_stmt.fetchall_dict.return_value = []
    adapter.execute("SELECT 1;")
    assert adapter.fetchall() == []

    # Stmt with fetchall
    mock_stmt2 = MagicMock(spec=["description", "fetchall"])
    mock_stmt2.description = [("a",)]
    mock_stmt2.fetchall.return_value = [(10,)]
    mock_conn.execute.return_value = mock_stmt2
    adapter.execute("SELECT 1;")
    assert adapter.description == [("a",)]
    assert adapter.fetchall() == [(10,)]

    # Stmt as tuple
    mock_conn.execute.return_value = [(1,)]
    adapter.execute("SELECT 1;")
    assert adapter.fetchall() == [(1,)]

    # Conn having cursor()
    mock_conn_cur = MagicMock(spec=["cursor"])
    mock_cur = MagicMock()
    mock_cur.description = [("c",)]
    mock_cur.fetchall.return_value = [(5,)]
    mock_conn_cur.cursor.return_value = mock_cur
    adapter2 = _ExasolCursorAdapter(mock_conn_cur)
    adapter2.execute("SELECT 5;", [1])
    assert adapter2.description == [("c",)]
    assert adapter2.fetchall() == [(5,)]

    # Empty object
    adapter_empty = _ExasolCursorAdapter(object())
    adapter_empty.execute("SELECT 1;")
    assert adapter_empty.description is None


def test_exasol_connector_sync_and_async():
    conn = ExasolConnector(schema_name="RETAIL")
    assert conn.dialect_name == "exasol"
    assert conn.schema_name == "RETAIL"

    # Missing driver
    with (
        patch.dict(sys.modules, {"pyexasol": None, "turbodbc": None}),
        pytest.raises(DriverNotInstalledError, match="pyexasol"),
    ):
        conn.connect()

    # Connection failure
    mock_driver = MagicMock()
    mock_driver.connect.side_effect = RuntimeError("Exasol host unreachable")
    with (
        patch.dict(sys.modules, {"pyexasol": mock_driver}),
        pytest.raises(ConnectionFailedError),
    ):
        conn.connect()

    # Successful connect
    mock_conn = MagicMock()
    mock_driver.connect.side_effect = None
    mock_driver.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"pyexasol": mock_driver}):
        assert conn.connect() is mock_conn

    # get_cursor variants
    mock_cur = MagicMock()
    conn_cur = ExasolConnector(cursor=mock_cur)
    with conn_cur.get_cursor() as cur:
        assert cur is mock_cur

    info = conn_cur.test_connection()
    assert info["engine_version"] == "Exasol"

    # Introspection via EXA_ALL tables
    mock_cur.fetchall.side_effect = [
        [("sales",)],
        [("sales", "id", "DECIMAL", "N"), ("sales", "amt", "DOUBLE", "Y")],
        [("sales", "id")],
        [("sales", "id", "orders", "sales_id")],
    ]
    snap = conn_cur.introspect_schema()
    assert "sales" in snap["tables"]
    cols = snap["tables"]["sales"]["columns"]
    assert cols[0]["name"] == "id" and cols[0]["is_primary"] is True
    assert cols[1]["is_nullable"] is True
    assert len(snap["foreign_keys"]) == 1
    assert snap["foreign_keys"][0]["foreign_table"] == "orders"

    # Introspection via information_schema fallback
    mock_cur.fetchall.side_effect = [
        RuntimeError("EXA catalog unavailable"),
        [("orders",)],
        [("orders", "id", "integer", "NO")],
    ]
    snap2 = conn_cur.introspect_schema()
    assert "orders" in snap2["tables"]

    # Introspection error
    mock_cur.fetchall.side_effect = RuntimeError("Catalog error")
    with pytest.raises(IntrospectionError):
        conn_cur.introspect_schema()


def test_async_exasol_connector():
    async def _test():
        conn = AsyncExasolConnector()
        assert conn.dialect_name == "exasol"

        # Driver missing
        with (
            patch.dict(sys.modules, {"pyexasol": None, "turbodbc": None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection failure
        mock_driver = MagicMock()
        mock_driver.connect.side_effect = RuntimeError("Async connect fail")
        with (
            patch.dict(sys.modules, {"pyexasol": mock_driver}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # Success execute_raw
        mock_conn = MagicMock()
        mock_stmt = MagicMock(spec=["columns", "fetchall_dict"])
        mock_stmt.columns.return_value = {"val": {}}
        mock_stmt.fetchall_dict.return_value = [{"val": 100}]
        mock_conn.execute.return_value = mock_stmt

        conn_exec = AsyncExasolConnector(connection=mock_conn)
        cols, rows, _lat = await conn_exec.execute_raw("SELECT 100;", [1])
        assert cols == ["val"]
        assert rows == [{"val": 100}]

    asyncio.run(_test())


# ============================================================================
# 9. IBM DB2 Connector Tests
# ============================================================================


def test_db2_connector_sync_and_async():
    conn = DB2Connector(schema_name="MY_SCHEMA")
    assert conn.dialect_name == "db2"
    assert conn.schema_name == "MY_SCHEMA"
    assert IBMDB2Connector is DB2Connector

    # Missing driver
    with (
        patch.dict(sys.modules, {"ibm_db_dbi": None, "ibm_db": None}),
        pytest.raises(DriverNotInstalledError, match="ibm_db"),
    ):
        conn.connect()

    # Connection failure
    mock_driver = MagicMock()
    mock_driver.connect.side_effect = RuntimeError("DB2 connection error")
    with (
        patch.dict(sys.modules, {"ibm_db_dbi": mock_driver}),
        pytest.raises(ConnectionFailedError),
    ):
        conn.connect()

    # Successful connect
    mock_conn = MagicMock()
    mock_driver.connect.side_effect = None
    mock_driver.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"ibm_db_dbi": mock_driver}):
        assert conn.connect() is mock_conn

    # test_connection & introspect
    mock_cur = MagicMock()
    conn_cur = DB2Connector(cursor=mock_cur)
    info = conn_cur.test_connection()
    assert info["engine_version"] == "IBM DB2"
    mock_cur.execute.assert_called_with("SELECT 1 FROM SYSIBM.SYSDUMMY1")

    mock_cur.fetchall.side_effect = [
        [("CUSTOMERS",)],
        [("CUSTOMERS", "ID", "INTEGER", "N"), ("CUSTOMERS", "NAME", "VARCHAR", "Y")],
        [("CUSTOMERS", "ID")],
        [("ORDERS", "CUST_ID", "CUSTOMERS", "ID")],
    ]
    snap = conn_cur.introspect_schema()
    assert "customers" in snap["tables"]
    cols = snap["tables"]["customers"]["columns"]
    assert cols[0]["name"] == "id" and cols[0]["is_primary"] is True
    assert cols[1]["is_nullable"] is True
    assert len(snap["foreign_keys"]) == 1
    assert snap["foreign_keys"][0]["foreign_table"] == "customers"

    # Fallback to information_schema
    mock_cur.fetchall.side_effect = [
        RuntimeError("No SYSCAT"),
        [("ORDERS",)],
        [("ORDERS", "ID", "INTEGER", "NO")],
    ]
    snap2 = conn_cur.introspect_schema()
    assert "orders" in snap2["tables"]

    # Introspection failure
    mock_cur.fetchall.side_effect = RuntimeError("DB2 fatal error")
    with pytest.raises(IntrospectionError):
        conn_cur.introspect_schema()


def test_async_db2_connector():
    async def _test():
        conn = AsyncDB2Connector()
        assert conn.dialect_name == "db2"
        assert AsyncIBMDB2Connector is AsyncDB2Connector

        # Missing driver
        with (
            patch.dict(sys.modules, {"ibm_db_dbi": None, "ibm_db": None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection failure
        mock_driver = MagicMock()
        mock_driver.connect.side_effect = RuntimeError("Async connect fail")
        with (
            patch.dict(sys.modules, {"ibm_db_dbi": mock_driver}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # Success execute_raw
        mock_cur = MagicMock()
        mock_cur.description = [("res",)]
        mock_cur.fetchall.return_value = [(100,)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        conn_exec = AsyncDB2Connector(connection=mock_conn)
        cols, rows, _lat = await conn_exec.execute_raw("SELECT 100;", [1])
        assert cols == ["res"]
        assert rows == [{"res": 100}]

        cols2, _rows2, _ = await conn_exec.execute_raw("SELECT 100;")
        assert cols2 == ["res"]

    asyncio.run(_test())


# ============================================================================
# 10. Azure Cosmos DB Connector Tests
# ============================================================================


def test_cosmosdb_cursor_adapter():
    mock_container = MagicMock()
    mock_container.query_items.return_value = [
        {"id": "doc1", "value": 10},
        {"id": "doc2", "value": 20},
    ]

    adapter = _CosmosDBCursorAdapter(mock_container)
    adapter.execute("SELECT * FROM c WHERE c.id = @p0;", ["doc1"])
    assert adapter.description == [("id",), ("value",)]
    assert adapter.fetchone() == ["doc1", 10]
    assert adapter.fetchall() == [["doc2", 20]]
    adapter.close()

    # Scalar items
    mock_container.query_items.return_value = ["res1", "res2"]
    adapter.execute("SELECT 1;")
    assert adapter.description == [("value",)]
    assert adapter.fetchall() == [["res1"], ["res2"]]

    # Execute fallback
    mock_target = MagicMock(spec=["execute", "description", "fetchall"])
    mock_target.description = [("x",)]
    mock_target.fetchall.return_value = [(5,)]
    adapter2 = _CosmosDBCursorAdapter(mock_target)
    adapter2.execute("SELECT 5;", [1])
    assert adapter2.description == [("x",)]
    assert adapter2.fetchall() == [(5,)]

    # Empty object
    adapter_empty = _CosmosDBCursorAdapter(object())
    adapter_empty.execute("SELECT 1;")
    assert adapter_empty.description == []


def test_cosmosdb_connector_sync_and_async():
    conn = CosmosDBConnector(database="docs_db")
    assert conn.dialect_name == "cosmosdb"
    assert conn.database == "docs_db"
    assert AzureCosmosDBConnector is CosmosDBConnector

    # Missing driver
    with (
        patch.dict(
            sys.modules, {"azure.cosmos": None, "azure.cosmos.cosmos_client": None}
        ),
        pytest.raises(DriverNotInstalledError, match="azure-cosmos"),
    ):
        conn.connect()

    # Connection failure
    mock_driver = MagicMock()
    mock_driver.CosmosClient.side_effect = RuntimeError("Cosmos client fail")
    with (
        patch.dict(sys.modules, {"azure.cosmos": mock_driver}),
        pytest.raises(ConnectionFailedError),
    ):
        conn.connect()

    # Successful connect
    mock_client = MagicMock()
    mock_driver.CosmosClient.side_effect = None
    mock_driver.CosmosClient.return_value = mock_client
    with patch.dict(sys.modules, {"azure.cosmos": mock_driver}):
        assert conn.connect() is mock_client

    # get_cursor variants
    mock_cur = MagicMock()
    conn_cur = CosmosDBConnector(cursor=mock_cur)
    with conn_cur.get_cursor() as cur:
        assert cur is mock_cur

    info = conn_cur.test_connection()
    assert info["engine_version"] == "Azure Cosmos DB"

    # Introspection via list_containers
    mock_client_intro = MagicMock(spec=["get_database_client"])
    mock_db_client = MagicMock(spec=["list_containers", "get_container_client"])
    mock_db_client.list_containers.return_value = [{"id": "users"}, {"id": "orders"}]
    proxy = MagicMock(spec=["query_items"])
    proxy.query_items.return_value = [{"id": "1", "name": "a", "_ts": 5}]
    mock_db_client.get_container_client.return_value = proxy
    mock_client_intro.get_database_client.return_value = mock_db_client

    snap = introspect_cosmosdb(mock_client_intro)
    assert "users" in snap["tables"]
    assert "orders" in snap["tables"]
    # real attributes only: system properties (_ts) are not columns, nothing invented
    assert [c["name"] for c in snap["tables"]["users"]["columns"]] == ["id", "name"]

    # Introspection via execute fallback
    mock_cur_cosmos = MagicMock(spec=["execute", "fetchall"])
    mock_cur_cosmos.fetchall.return_value = [("items",)]
    snap2 = introspect_cosmosdb(mock_cur_cosmos)
    assert "items" in snap2["tables"]

    # Introspection via query_items
    mock_container = MagicMock(spec=["query_items", "id"])
    mock_container.id = "metrics"
    mock_container.query_items.return_value = [{"id": "m1", "v": 1.5}, "not-a-doc"]
    snap3 = introspect_cosmosdb(mock_container)
    assert [c["name"] for c in snap3["tables"]["metrics"]["columns"]] == ["id", "v"]

    # nothing to introspect: no tables (a table is never invented)
    snap_empty = introspect_cosmosdb(object())
    assert snap_empty["tables"] == {}

    # Introspection error
    mock_client_intro.get_database_client.side_effect = RuntimeError("Cosmos DB error")
    with pytest.raises(IntrospectionError):
        introspect_cosmosdb(mock_client_intro)


def test_async_cosmosdb_connector():
    async def _test():
        conn = AsyncCosmosDBConnector()
        assert conn.dialect_name == "cosmosdb"
        assert AsyncAzureCosmosDBConnector is AsyncCosmosDBConnector

        # Driver missing
        with (
            patch.dict(
                sys.modules, {"azure.cosmos": None, "azure.cosmos.cosmos_client": None}
            ),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection failure
        mock_driver = MagicMock()
        mock_driver.CosmosClient.side_effect = RuntimeError("Async connect fail")
        with (
            patch.dict(sys.modules, {"azure.cosmos": mock_driver}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # Successful execute_raw
        mock_container = MagicMock()
        mock_container.query_items.return_value = [{"res": 42}]
        conn_exec = AsyncCosmosDBConnector(connection=mock_container)

        cols, rows, _lat = await conn_exec.execute_raw("SELECT 42;", [1])
        assert cols == ["res"]
        assert rows == [{"res": 42}]

    asyncio.run(_test())


# ============================================================================
# 11. Registry Instantiation Integration Tests
# ============================================================================


def test_registry_resolution_for_new_connectors():
    # Verify every new connector resolves correctly via ConnectorRegistry.get()
    assert isinstance(get_connector("sparksql"), SparkSQLConnector)
    assert isinstance(get_connector("spark_sql"), SparkSQLConnector)
    assert isinstance(get_connector("pyspark"), SparkSQLConnector)
    assert isinstance(get_connector("async_sparksql"), AsyncSparkSQLConnector)
    assert isinstance(get_connector("async_spark_sql"), AsyncSparkSQLConnector)
    assert isinstance(get_connector("async_pyspark"), AsyncSparkSQLConnector)

    assert isinstance(get_connector("chdb"), ChDBConnector)
    assert isinstance(get_connector("async_chdb"), AsyncChDBConnector)

    assert isinstance(get_connector("greptimedb"), GreptimeDBConnector)
    assert isinstance(get_connector("greptime"), GreptimeDBConnector)
    assert isinstance(get_connector("async_greptimedb"), AsyncGreptimeDBConnector)
    assert isinstance(get_connector("async_greptime"), AsyncGreptimeDBConnector)

    assert isinstance(get_connector("tdengine"), TDengineConnector)
    assert isinstance(get_connector("taos"), TDengineConnector)
    assert isinstance(get_connector("async_tdengine"), AsyncTDengineConnector)
    assert isinstance(get_connector("async_taos"), AsyncTDengineConnector)

    assert isinstance(get_connector("surrealdb"), SurrealDBConnector)
    assert isinstance(get_connector("surreal"), SurrealDBConnector)
    assert isinstance(get_connector("async_surrealdb"), AsyncSurrealDBConnector)
    assert isinstance(get_connector("async_surreal"), AsyncSurrealDBConnector)

    assert isinstance(get_connector("arangodb"), ArangoDBConnector)
    assert isinstance(get_connector("arango"), ArangoDBConnector)
    assert isinstance(get_connector("aql"), ArangoDBConnector)
    assert isinstance(get_connector("async_arangodb"), AsyncArangoDBConnector)
    assert isinstance(get_connector("async_arango"), AsyncArangoDBConnector)
    assert isinstance(get_connector("async_aql"), AsyncArangoDBConnector)

    assert isinstance(get_connector("apache_cassandra"), ApacheCassandraConnector)
    assert isinstance(get_connector("apache-cassandra"), ApacheCassandraConnector)
    assert isinstance(
        get_connector("async_apache_cassandra"), AsyncApacheCassandraConnector
    )
    assert isinstance(
        get_connector("async_apache-cassandra"), AsyncApacheCassandraConnector
    )

    assert isinstance(get_connector("exasol"), ExasolConnector)
    assert isinstance(get_connector("async_exasol"), AsyncExasolConnector)

    assert isinstance(get_connector("db2"), DB2Connector)
    assert isinstance(get_connector("ibm_db2"), DB2Connector)
    assert isinstance(get_connector("async_db2"), AsyncDB2Connector)
    assert isinstance(get_connector("async_ibm_db2"), AsyncDB2Connector)

    assert isinstance(get_connector("cosmosdb"), CosmosDBConnector)
    assert isinstance(get_connector("azure_cosmos"), CosmosDBConnector)
    assert isinstance(get_connector("async_cosmosdb"), AsyncCosmosDBConnector)
    assert isinstance(get_connector("async_azure_cosmos"), AsyncCosmosDBConnector)
