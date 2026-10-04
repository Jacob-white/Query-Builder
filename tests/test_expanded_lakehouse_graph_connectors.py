"""
Unit Tests for Expanded Lakehouse, Distributed HTAP, Search, Graph, and Time-Series Connectors.
==============================================================================================
Validates:
- Doris (Apache Doris)
- Impala (Apache Impala)
- Hive (Apache Hive)
- Kyuubi (Apache Kyuubi)
- Drill (Apache Drill)
- YugabyteDB (YugabyteDB)
- OpenSearch (OpenSearch SQL)
- Neo4j (Cypher Graph)
- Kdb+ (PyKX Time-Series)
- ClickHouse Native (Binary TCP)
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock, patch

import pytest

from query_builder.connectors import (
    ApacheDorisConnector,
    ApacheDrillConnector,
    ApacheHiveConnector,
    ApacheImpalaConnector,
    ApacheKyuubiConnector,
    AsyncApacheDorisConnector,
    AsyncApacheDrillConnector,
    AsyncApacheHiveConnector,
    AsyncApacheImpalaConnector,
    AsyncApacheKyuubiConnector,
    AsyncClickHouseNativeConnector,
    AsyncDorisConnector,
    AsyncDrillConnector,
    AsyncHiveConnector,
    AsyncImpalaConnector,
    AsyncKdbConnector,
    AsyncKyuubiConnector,
    AsyncNeo4jConnector,
    AsyncOpenSearchConnector,
    AsyncPyKXConnector,
    AsyncYugabyteConnector,
    AsyncYugabyteDBConnector,
    ClickHouseNativeConnector,
    ConnectionFailedError,
    ConnectorRegistry,
    DorisConnector,
    DrillConnector,
    DriverNotInstalledError,
    HiveConnector,
    ImpalaConnector,
    IntrospectionError,
    KdbConnector,
    KyuubiConnector,
    Neo4jConnector,
    OpenSearchConnector,
    PyKXConnector,
    YugabyteConnector,
    YugabyteDBConnector,
    get_connector,
)
from query_builder.connectors.clickhouse_native import _ClickHouseNativeCursorAdapter
from query_builder.connectors.doris import _DorisCursorAdapter
from query_builder.connectors.drill import _DrillCursorAdapter
from query_builder.connectors.hive import _HiveCursorAdapter
from query_builder.connectors.impala import _ImpalaCursorAdapter
from query_builder.connectors.kdb import _KdbCursorAdapter
from query_builder.connectors.kyuubi import _KyuubiCursorAdapter
from query_builder.connectors.neo4j import _Neo4jCursorAdapter
from query_builder.connectors.opensearch import _OpenSearchCursorAdapter

# ============================================================================
# 1. Doris Connector Tests
# ============================================================================


def test_doris_cursor_adapter():
    # Target with cursor()
    mock_target = MagicMock()
    mock_cur = MagicMock()
    mock_cur.description = [("id",), ("name",)]
    mock_cur.fetchall.return_value = [("1", "alpha"), ("2", "beta")]
    mock_target.cursor.return_value = mock_cur

    adapter = _DorisCursorAdapter(mock_target)
    adapter.execute("SELECT * FROM t WHERE id = %s", ["1"])
    assert adapter.description == [("id",), ("name",)]
    assert adapter.fetchone() == ("1", "alpha")
    assert adapter.fetchall() == [("2", "beta")]
    assert adapter.fetchone() is None
    adapter.close()

    # Target with direct execute
    mock_direct = MagicMock(spec=["execute", "fetchall", "description"])
    mock_direct.description = [("cnt",)]
    mock_direct.fetchall.return_value = [(42,)]
    adapter2 = _DorisCursorAdapter(mock_direct)
    adapter2.execute("SELECT count(*) FROM t")
    assert adapter2.fetchall() == [(42,)]

    # Target without execute/cursor
    adapter3 = _DorisCursorAdapter(object())
    adapter3.execute("SELECT 1")
    assert adapter3.description is None
    assert adapter3.fetchall() == []


def test_doris_connector_lifecycle():
    # Missing driver
    with patch.dict(
        sys.modules, {"pydoris": None, "pymysql": None, "mysql.connector": None}
    ):
        conn = DorisConnector()
        with pytest.raises(DriverNotInstalledError):
            conn.connect()

    # Driver connect failure
    mock_driver = MagicMock()
    mock_driver.connect.side_effect = RuntimeError("Doris connection refused")
    with patch.dict(sys.modules, {"pydoris": mock_driver}):
        conn = DorisConnector()
        with pytest.raises(ConnectionFailedError):
            conn.connect()

    # Driver connect success and caching
    mock_db_conn = MagicMock()
    mock_driver.connect.side_effect = None
    mock_driver.connect.return_value = mock_db_conn
    with patch.dict(sys.modules, {"pydoris": mock_driver}):
        conn = DorisConnector(database="test_db")
        c1 = conn.connect()
        assert c1 is mock_db_conn
        assert conn.connect() is mock_db_conn  # cached

    # Pre-set cursor and connection
    mock_cur = MagicMock()
    mock_cur.description = [("v",)]
    mock_cur.fetchall.return_value = [("doris 2.0",)]
    conn_preset = DorisConnector(cursor=mock_cur)
    with conn_preset.get_cursor() as cur:
        cur.execute("SELECT version();")
        assert cur.fetchall() == [("doris 2.0",)]

    # Timeout
    conn_preset.apply_statement_timeout(mock_cur, 5000)
    mock_cur.execute.assert_called_with("SET query_timeout = 5;")

    # Test connection
    mock_cur.fetchall.return_value = [("2.0.3",)]
    info = conn_preset.test_connection()
    assert info["status"] == "healthy"
    assert "Doris" in info["engine_version"]
    assert info["database"] == "information_schema"

    # Introspect schema
    with patch("query_builder.connectors.doris.introspect_doris") as mock_intro:
        mock_intro.return_value = {"tables": {}}
        res = conn_preset.introspect_schema()
        assert res == {"tables": {}}

        mock_intro.side_effect = Exception("Introspection error")
        with pytest.raises(IntrospectionError):
            conn_preset.introspect_schema()

    # Alias check
    assert ApacheDorisConnector is DorisConnector


def test_async_doris_connector():
    # Missing driver
    with patch.dict(sys.modules, {"aiomysql": None, "pymysql": None, "pydoris": None}):
        aconn = AsyncDorisConnector()
        with pytest.raises(DriverNotInstalledError):
            asyncio.run(aconn.connect())

    # Driver connect failure
    mock_driver = MagicMock()
    mock_driver.connect.side_effect = RuntimeError("Async connect failed")
    with patch.dict(sys.modules, {"aiomysql": mock_driver}):
        aconn = AsyncDorisConnector()
        with pytest.raises(ConnectionFailedError):
            asyncio.run(aconn.connect())

    # Async connect success
    mock_conn = MagicMock()
    mock_driver.connect.side_effect = None
    mock_driver.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"aiomysql": mock_driver}):
        aconn = AsyncDorisConnector(database="test_db")

        async def _test():
            c = await aconn.connect()
            assert c is mock_conn
            assert await aconn.connect() is mock_conn  # cached

        asyncio.run(_test())

    # Async execute_raw and introspect_schema
    mock_cur = MagicMock()
    mock_cur.description = [("id",), ("val",)]
    mock_cur.fetchall.return_value = [("1", 100)]
    mock_conn.cursor.return_value = mock_cur
    aconn = AsyncDorisConnector(connection=mock_conn)

    async def _test_exec():
        cols, rows, latency = await aconn.execute_raw("SELECT * FROM tbl")
        assert cols == ["id", "val"]
        assert rows == [{"id": "1", "val": 100}]
        assert latency >= 0

        with patch("query_builder.connectors.doris.introspect_doris") as mock_intro:
            mock_intro.return_value = {"tables": {"t": {}}}
            schema = await aconn.introspect_schema()
            assert "tables" in schema

            mock_intro.side_effect = Exception("Async introspect error")
            with pytest.raises(IntrospectionError):
                await aconn.introspect_schema()

    asyncio.run(_test_exec())
    assert AsyncApacheDorisConnector is AsyncDorisConnector


# ============================================================================
# 2. Impala Connector Tests
# ============================================================================


def test_impala_cursor_adapter():
    mock_target = MagicMock()
    mock_cur = MagicMock()
    mock_cur.description = [("x",)]
    mock_cur.fetchall.return_value = [(10,)]
    mock_target.cursor.return_value = mock_cur

    adapter = _ImpalaCursorAdapter(mock_target)
    adapter.execute("SELECT 10")
    assert adapter.fetchall() == [(10,)]
    adapter.close()

    mock_direct = MagicMock(spec=["execute", "fetchall", "description"])
    mock_direct.description = [("y",)]
    mock_direct.fetchall.return_value = [(20,)]
    adapter2 = _ImpalaCursorAdapter(mock_direct)
    adapter2.execute("SELECT 20 WHERE 1 = %s", [1])
    assert adapter2.fetchall() == [(20,)]


def test_impala_connector_lifecycle():
    # Missing driver
    with patch.dict(sys.modules, {"impala.dbapi": None}):
        conn = ImpalaConnector()
        with pytest.raises(DriverNotInstalledError):
            conn.connect()

    # Driver connect failure
    mock_driver = MagicMock()
    mock_driver.connect.side_effect = RuntimeError("Impala unavailable")
    with patch.dict(sys.modules, {"impala.dbapi": mock_driver}):
        conn = ImpalaConnector()
        with pytest.raises(ConnectionFailedError):
            conn.connect()

    # Driver connect success and caching
    mock_impala_conn = MagicMock()
    mock_driver.connect.side_effect = None
    mock_driver.connect.return_value = mock_impala_conn
    with patch.dict(sys.modules, {"impala.dbapi": mock_driver}):
        conn = ImpalaConnector(host="localhost", database="analytics")
        assert conn.connect() is mock_impala_conn
        assert conn.connect() is mock_impala_conn

    # Preset cursor
    mock_cur = MagicMock()
    mock_cur.description = [("version",)]
    mock_cur.fetchall.return_value = [("impalad 4.2",)]
    conn_preset = ImpalaConnector(cursor=mock_cur)
    conn_preset.apply_statement_timeout(mock_cur, 3000)
    mock_cur.execute.assert_called_with("SET QUERY_TIMEOUT_S = 3;")

    info = conn_preset.test_connection()
    assert info["status"] == "healthy"
    assert "Impala" in info["engine_version"]

    with patch("query_builder.connectors.impala.introspect_impala") as mock_intro:
        mock_intro.return_value = {"tables": {}}
        assert conn_preset.introspect_schema() == {"tables": {}}
        mock_intro.side_effect = Exception("Impala introspection failed")
        with pytest.raises(IntrospectionError):
            conn_preset.introspect_schema()

    assert ApacheImpalaConnector is ImpalaConnector


def test_async_impala_connector():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.description = [("val",)]
    mock_cur.fetchall.return_value = [(99,)]
    mock_conn.cursor.return_value = mock_cur

    aconn = AsyncImpalaConnector(connection=mock_conn)

    async def _test():
        c = await aconn.connect()
        assert c is mock_conn
        cols, rows, _ = await aconn.execute_raw("SELECT 99")
        assert cols == ["val"]
        assert rows == [{"val": 99}]

        with patch("query_builder.connectors.impala.introspect_impala") as mock_intro:
            mock_intro.return_value = {"tables": {"logs": {}}}
            schema = await aconn.introspect_schema()
            assert "tables" in schema

            mock_intro.side_effect = Exception("Async error")
            with pytest.raises(IntrospectionError):
                await aconn.introspect_schema()

    asyncio.run(_test())
    assert AsyncApacheImpalaConnector is AsyncImpalaConnector


# ============================================================================
# 3. Hive Connector Tests
# ============================================================================


def test_hive_cursor_adapter():
    mock_target = MagicMock()
    mock_cur = MagicMock()
    mock_cur.description = [("k",)]
    mock_cur.fetchall.return_value = [("v",)]
    mock_target.cursor.return_value = mock_cur

    adapter = _HiveCursorAdapter(mock_target)
    adapter.execute("SELECT 'v'")
    assert adapter.fetchall() == [("v",)]
    adapter.close()


def test_hive_connector_lifecycle():
    # Missing driver
    with patch.dict(sys.modules, {"pyhive.hive": None}):
        conn = HiveConnector()
        with pytest.raises(DriverNotInstalledError):
            conn.connect()

    # Driver connect failure
    mock_driver = MagicMock()
    mock_driver.connect.side_effect = RuntimeError("HiveServer2 unreachable")
    with patch.dict(sys.modules, {"pyhive.hive": mock_driver}):
        conn = HiveConnector()
        with pytest.raises(ConnectionFailedError):
            conn.connect()

    # Connect success and caching
    mock_hive_conn = MagicMock()
    mock_driver.connect.side_effect = None
    mock_driver.connect.return_value = mock_hive_conn
    with patch.dict(sys.modules, {"pyhive.hive": mock_driver}):
        conn = HiveConnector(database="lakehouse")
        assert conn.connect() is mock_hive_conn
        assert conn.connect() is mock_hive_conn

    # Preset cursor
    mock_cur = MagicMock()
    mock_cur.description = [("version",)]
    mock_cur.fetchall.return_value = [("3.1.3",)]
    conn_preset = HiveConnector(cursor=mock_cur)
    conn_preset.apply_statement_timeout(mock_cur, 4000)
    mock_cur.execute.assert_called_with("SET hive.query.timeout.seconds = 4;")

    info = conn_preset.test_connection()
    assert info["status"] == "healthy"
    assert "Hive" in info["engine_version"]

    with patch("query_builder.connectors.hive.introspect_hive") as mock_intro:
        mock_intro.return_value = {"tables": {}}
        assert conn_preset.introspect_schema() == {"tables": {}}
        mock_intro.side_effect = Exception("Hive introspection failed")
        with pytest.raises(IntrospectionError):
            conn_preset.introspect_schema()

    assert ApacheHiveConnector is HiveConnector


def test_async_hive_connector():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.description = [("cnt",)]
    mock_cur.fetchall.return_value = [(5,)]
    mock_conn.cursor.return_value = mock_cur

    aconn = AsyncHiveConnector(connection=mock_conn)

    async def _test():
        c = await aconn.connect()
        assert c is mock_conn
        cols, rows, _ = await aconn.execute_raw("SELECT count(*) FROM hdfs_tbl")
        assert cols == ["cnt"]
        assert rows == [{"cnt": 5}]

        with patch("query_builder.connectors.hive.introspect_hive") as mock_intro:
            mock_intro.return_value = {"tables": {}}
            schema = await aconn.introspect_schema()
            assert "tables" in schema

            mock_intro.side_effect = Exception("Async error")
            with pytest.raises(IntrospectionError):
                await aconn.introspect_schema()

    asyncio.run(_test())
    assert AsyncApacheHiveConnector is AsyncHiveConnector


# ============================================================================
# 4. Kyuubi Connector Tests
# ============================================================================


def test_kyuubi_cursor_adapter():
    mock_target = MagicMock()
    mock_cur = MagicMock()
    mock_cur.description = [("status",)]
    mock_cur.fetchall.return_value = [("OK",)]
    mock_target.cursor.return_value = mock_cur

    adapter = _KyuubiCursorAdapter(mock_target)
    adapter.execute("SELECT 'OK'")
    assert adapter.fetchall() == [("OK",)]
    adapter.close()


def test_kyuubi_connector_lifecycle():
    # Missing driver
    with patch.dict(sys.modules, {"pyhive.hive": None}):
        conn = KyuubiConnector()
        with pytest.raises(DriverNotInstalledError):
            conn.connect()

    # Driver connect failure
    mock_driver = MagicMock()
    mock_driver.connect.side_effect = RuntimeError("Kyuubi gateway error")
    with patch.dict(sys.modules, {"pyhive.hive": mock_driver}):
        conn = KyuubiConnector()
        with pytest.raises(ConnectionFailedError):
            conn.connect()

    # Connect success and caching
    mock_kyuubi_conn = MagicMock()
    mock_driver.connect.side_effect = None
    mock_driver.connect.return_value = mock_kyuubi_conn
    with patch.dict(sys.modules, {"pyhive.hive": mock_driver}):
        conn = KyuubiConnector(database="gateway")
        assert conn.connect() is mock_kyuubi_conn
        assert conn.connect() is mock_kyuubi_conn

    # Preset cursor
    mock_cur = MagicMock()
    mock_cur.description = [("version",)]
    mock_cur.fetchall.return_value = [("kyuubi 1.8.0",)]
    conn_preset = KyuubiConnector(cursor=mock_cur)
    conn_preset.apply_statement_timeout(mock_cur, 6000)
    mock_cur.execute.assert_called_with("SET kyuubi.operation.timeout = 6000;")

    info = conn_preset.test_connection()
    assert info["status"] == "healthy"
    assert "Kyuubi" in info["engine_version"]

    with patch("query_builder.connectors.kyuubi.introspect_kyuubi") as mock_intro:
        mock_intro.return_value = {"tables": {}}
        assert conn_preset.introspect_schema() == {"tables": {}}
        mock_intro.side_effect = Exception("Kyuubi introspection failed")
        with pytest.raises(IntrospectionError):
            conn_preset.introspect_schema()

    assert ApacheKyuubiConnector is KyuubiConnector


def test_async_kyuubi_connector():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.description = [("res",)]
    mock_cur.fetchall.return_value = [(1,)]
    mock_conn.cursor.return_value = mock_cur

    aconn = AsyncKyuubiConnector(connection=mock_conn)

    async def _test():
        c = await aconn.connect()
        assert c is mock_conn
        cols, rows, _ = await aconn.execute_raw("SELECT 1")
        assert cols == ["res"]
        assert rows == [{"res": 1}]

        with patch("query_builder.connectors.kyuubi.introspect_kyuubi") as mock_intro:
            mock_intro.return_value = {"tables": {}}
            schema = await aconn.introspect_schema()
            assert "tables" in schema

            mock_intro.side_effect = Exception("Async error")
            with pytest.raises(IntrospectionError):
                await aconn.introspect_schema()

    asyncio.run(_test())
    assert AsyncApacheKyuubiConnector is AsyncKyuubiConnector


# ============================================================================
# 5. Drill Connector Tests
# ============================================================================


def test_drill_cursor_adapter():
    mock_target = MagicMock()
    # Mock PyDrill response
    mock_drill_res = MagicMock()
    mock_drill_res.columns = ["name", "age"]
    mock_drill_res.rows = [{"name": "alice", "age": 30}]
    mock_target.query.return_value = mock_drill_res

    adapter = _DrillCursorAdapter(mock_target)
    adapter.execute("SELECT * FROM dfs.users")
    assert adapter.description == [("name",), ("age",)]
    assert adapter.fetchall() == [["alice", 30]]
    adapter.close()


def test_drill_connector_lifecycle():
    # Missing driver
    with patch.dict(sys.modules, {"pydrill.client": None}):
        conn = DrillConnector()
        with pytest.raises(DriverNotInstalledError):
            conn.connect()

    # Driver connect failure
    mock_driver = MagicMock()
    mock_driver.PyDrill.side_effect = RuntimeError("Drill cluster offline")
    with patch.dict(sys.modules, {"pydrill.client": mock_driver}):
        conn = DrillConnector()
        with pytest.raises(ConnectionFailedError):
            conn.connect()

    # Connect success and caching
    mock_drill_client = MagicMock()
    mock_driver.PyDrill.side_effect = None
    mock_driver.PyDrill.return_value = mock_drill_client
    with patch.dict(sys.modules, {"pydrill.client": mock_driver}):
        conn = DrillConnector(host="drill.local", port=8047)
        assert conn.connect() is mock_drill_client
        assert conn.connect() is mock_drill_client

    # Preset cursor
    mock_cur = MagicMock()
    mock_drill_res = MagicMock()
    mock_drill_res.columns = ["version"]
    mock_drill_res.rows = [{"version": "1.21.1"}]
    mock_cur.query.return_value = mock_drill_res
    conn_preset = DrillConnector(cursor=mock_cur)
    conn_preset.apply_statement_timeout(mock_cur, 5000)
    mock_cur.execute.assert_called_with(
        "ALTER SESSION SET `exec.query.max__idle__seconds` = 5;"
    )

    info = conn_preset.test_connection()
    assert info["status"] == "healthy"
    assert "Drill" in info["engine_version"]

    with patch("query_builder.connectors.drill.introspect_drill") as mock_intro:
        mock_intro.return_value = {"tables": {}}
        assert conn_preset.introspect_schema() == {"tables": {}}
        mock_intro.side_effect = Exception("Drill introspection failed")
        with pytest.raises(IntrospectionError):
            conn_preset.introspect_schema()

    assert ApacheDrillConnector is DrillConnector


def test_async_drill_connector():
    mock_client = MagicMock()
    mock_drill_res = MagicMock()
    mock_drill_res.columns = ["count"]
    mock_drill_res.rows = [{"count": 100}]
    mock_client.query.return_value = mock_drill_res

    aconn = AsyncDrillConnector(connection=mock_client)

    async def _test():
        c = await aconn.connect()
        assert c is mock_client
        cols, rows, _ = await aconn.execute_raw(
            "SELECT count(*) FROM cp.`employee.json`"
        )
        assert cols == ["count"]
        assert rows == [{"count": 100}]

        with patch("query_builder.connectors.drill.introspect_drill") as mock_intro:
            mock_intro.return_value = {"tables": {}}
            schema = await aconn.introspect_schema()
            assert "tables" in schema

            mock_intro.side_effect = Exception("Async error")
            with pytest.raises(IntrospectionError):
                await aconn.introspect_schema()

    asyncio.run(_test())
    assert AsyncApacheDrillConnector is AsyncDrillConnector


# ============================================================================
# 6. YugabyteDB Connector Tests
# ============================================================================


def test_yugabyte_connector_lifecycle():
    # Missing driver
    with patch.dict(sys.modules, {"psycopg": None}):
        conn = YugabyteDBConnector()
        with pytest.raises(DriverNotInstalledError):
            conn.connect()

    # Driver connect failure
    mock_driver = MagicMock()
    mock_driver.connect.side_effect = RuntimeError("YugabyteDB connection refused")
    with patch.dict(sys.modules, {"psycopg": mock_driver}):
        conn = YugabyteDBConnector()
        with pytest.raises(ConnectionFailedError):
            conn.connect()

    # Connect success and caching
    mock_yb_conn = MagicMock()
    mock_driver.connect.side_effect = None
    mock_driver.connect.return_value = mock_yb_conn
    with patch.dict(sys.modules, {"psycopg": mock_driver}):
        conn = YugabyteDBConnector(dbname="yugabyte")
        assert conn.connect() is mock_yb_conn
        assert conn.connect() is mock_yb_conn

    # Preset cursor
    mock_cur = MagicMock()
    mock_cur.description = [("version",)]
    mock_cur.fetchone.return_value = ["PostgreSQL 15.2-YB-2.19.0.0"]
    conn_preset = YugabyteDBConnector(cursor=mock_cur)
    conn_preset.apply_statement_timeout(mock_cur, 5000)
    mock_cur.execute.assert_called_with("SET statement_timeout = 5000;")

    info = conn_preset.test_connection()
    assert info["status"] == "healthy"
    assert "Yugabyte" in info["engine_version"]

    with patch("query_builder.connectors.yugabyte.introspect_yugabyte") as mock_intro:
        mock_intro.return_value = {"tables": {}}
        assert conn_preset.introspect_schema() == {"tables": {}}
        mock_intro.side_effect = Exception("YugabyteDB introspection failed")
        with pytest.raises(IntrospectionError):
            conn_preset.introspect_schema()

    assert YugabyteConnector is YugabyteDBConnector


def test_async_yugabyte_connector():
    # Missing driver
    with patch.dict(sys.modules, {"psycopg": None}):
        aconn = AsyncYugabyteDBConnector()
        with pytest.raises(DriverNotInstalledError):
            asyncio.run(aconn.connect())

    mock_driver = MagicMock()
    mock_yb_conn = MagicMock()
    mock_driver.connect = MagicMock(return_value=mock_yb_conn)

    with patch.dict(sys.modules, {"psycopg": mock_driver}):
        aconn = AsyncYugabyteDBConnector(dbname="yugabyte")

        async def _test():
            c = await aconn.connect()
            assert c is mock_yb_conn
            assert await aconn.connect() is mock_yb_conn

        asyncio.run(_test())

    # Raw execution and introspection
    mock_cur = MagicMock()
    mock_cur.description = [("id",)]
    mock_cur.fetchall.return_value = [(101,)]
    mock_yb_conn.cursor.return_value = mock_cur
    aconn = AsyncYugabyteDBConnector(connection=mock_yb_conn)

    async def _test_exec():
        cols, rows, _ = await aconn.execute_raw("SELECT 101 AS id")
        assert cols == ["id"]
        assert rows == [{"id": 101}]

        with patch(
            "query_builder.connectors.yugabyte.introspect_yugabyte"
        ) as mock_intro:
            mock_intro.return_value = {"tables": {}}
            schema = await aconn.introspect_schema()
            assert "tables" in schema

            mock_intro.side_effect = Exception("Async error")
            with pytest.raises(IntrospectionError):
                await aconn.introspect_schema()

    asyncio.run(_test_exec())
    assert AsyncYugabyteConnector is AsyncYugabyteDBConnector


# ============================================================================
# 7. OpenSearch Connector Tests
# ============================================================================


def test_opensearch_cursor_adapter():
    # Test client transport branch
    mock_client = MagicMock()
    mock_client.transport.perform_request.return_value = {
        "schema": [
            {"name": "id", "type": "keyword"},
            {"name": "val", "type": "integer"},
        ],
        "datarows": [["a1", 10], ["a2", 20]],
    }
    adapter = _OpenSearchCursorAdapter(mock_client)
    adapter.execute("SELECT id, val FROM logs;", ["param"])
    assert adapter.description == [("id",), ("val",)]
    assert adapter.fetchone() == ["a1", 10]
    assert adapter.fetchall() == [["a2", 20]]
    adapter.close()


def test_opensearch_connector_lifecycle():
    # Missing driver
    with patch.dict(sys.modules, {"opensearchpy": None}):
        conn = OpenSearchConnector()
        with pytest.raises(DriverNotInstalledError):
            conn.connect()

    # Driver connect failure
    mock_driver = MagicMock()
    mock_driver.OpenSearch.side_effect = RuntimeError("OpenSearch cluster down")
    with patch.dict(sys.modules, {"opensearchpy": mock_driver}):
        conn = OpenSearchConnector()
        with pytest.raises(ConnectionFailedError):
            conn.connect()

    # Connect success and caching
    mock_os_client = MagicMock()
    mock_driver.OpenSearch.side_effect = None
    mock_driver.OpenSearch.return_value = mock_os_client
    with patch.dict(sys.modules, {"opensearchpy": mock_driver}):
        conn = OpenSearchConnector(hosts=["https://localhost:9200"])
        assert conn.connect() is mock_os_client
        assert conn.connect() is mock_os_client

    # Preset cursor
    mock_cur = MagicMock()
    mock_cur.transport.perform_request.return_value = {
        "schema": [{"name": "version"}],
        "datarows": [["2.11.0"]],
    }
    conn_preset = OpenSearchConnector(cursor=mock_cur)
    conn_preset.apply_statement_timeout(mock_cur, 5000)

    info = conn_preset.test_connection()
    assert info["status"] == "healthy"
    assert "OpenSearch" in info["engine_version"]

    with patch(
        "query_builder.connectors.opensearch.introspect_opensearch"
    ) as mock_intro:
        mock_intro.return_value = {"tables": {}}
        assert conn_preset.introspect_schema() == {"tables": {}}
        mock_intro.side_effect = Exception("OpenSearch introspection failed")
        with pytest.raises(IntrospectionError):
            conn_preset.introspect_schema()


def test_async_opensearch_connector():
    mock_client = MagicMock()
    mock_client.transport.perform_request.return_value = {
        "schema": [{"name": "cnt"}],
        "datarows": [[123]],
    }
    aconn = AsyncOpenSearchConnector(connection=mock_client)

    async def _test():
        c = await aconn.connect()
        assert c is mock_client
        cols, rows, _ = await aconn.execute_raw("SELECT count(*) FROM indices")
        assert cols == ["cnt"]
        assert rows == [{"cnt": 123}]

        with patch(
            "query_builder.connectors.opensearch.introspect_opensearch"
        ) as mock_intro:
            mock_intro.return_value = {"tables": {}}
            schema = await aconn.introspect_schema()
            assert "tables" in schema

            mock_intro.side_effect = Exception("Async error")
            with pytest.raises(IntrospectionError):
                await aconn.introspect_schema()

    asyncio.run(_test())


# ============================================================================
# 8. Neo4j Connector Tests
# ============================================================================


def test_neo4j_cursor_adapter():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value = mock_session

    mock_rec1 = MagicMock()
    mock_rec1.values.return_value = ["Alice", 30]
    mock_rec2 = MagicMock()
    mock_rec2.values.return_value = ["Bob", 40]
    mock_result = MagicMock()
    mock_result.keys.return_value = ["name", "age"]
    mock_result.__iter__.return_value = [mock_rec1, mock_rec2]
    mock_session.run.return_value = mock_result

    adapter = _Neo4jCursorAdapter(mock_driver)
    adapter.execute("SELECT 1")  # Translates to RETURN 1 AS val
    mock_session.run.assert_called_with("RETURN 1 AS val", {})
    assert adapter.description == [("name",), ("age",)]
    assert adapter.fetchone() == ["Alice", 30]
    assert adapter.fetchall() == [["Bob", 40]]
    adapter.close()


def test_neo4j_connector_lifecycle():
    # Missing driver
    with patch.dict(sys.modules, {"neo4j": None}):
        conn = Neo4jConnector()
        with pytest.raises(DriverNotInstalledError):
            conn.connect()

    # Driver connect failure
    mock_driver_mod = MagicMock()
    mock_driver_mod.GraphDatabase.driver.side_effect = RuntimeError(
        "Bolt protocol offline"
    )
    with patch.dict(sys.modules, {"neo4j": mock_driver_mod}):
        conn = Neo4jConnector()
        with pytest.raises(ConnectionFailedError):
            conn.connect()

    # Connect success and caching
    mock_driver = MagicMock()
    mock_driver_mod.GraphDatabase.driver.side_effect = None
    mock_driver_mod.GraphDatabase.driver.return_value = mock_driver
    with patch.dict(sys.modules, {"neo4j": mock_driver_mod}):
        conn = Neo4jConnector(uri="bolt://localhost:7687", auth=("neo4j", "pass"))
        assert conn.connect() is mock_driver
        assert conn.connect() is mock_driver

    # Preset cursor
    mock_session = MagicMock()
    mock_rec = MagicMock()
    mock_rec.values.return_value = ["5.15.0"]
    mock_res = MagicMock()
    mock_res.keys.return_value = ["version"]
    mock_res.__iter__.return_value = [mock_rec]
    mock_session.run.return_value = mock_res
    conn_preset = Neo4jConnector(cursor=mock_session)
    conn_preset.apply_statement_timeout(mock_session, 5000)

    info = conn_preset.test_connection()
    assert info["status"] == "healthy"
    assert "Neo4j" in info["engine_version"]

    with patch("query_builder.connectors.neo4j.introspect_neo4j") as mock_intro:
        mock_intro.return_value = {"tables": {}}
        assert conn_preset.introspect_schema() == {"tables": {}}
        mock_intro.side_effect = Exception("Neo4j introspection failed")
        with pytest.raises(IntrospectionError):
            conn_preset.introspect_schema()


def test_async_neo4j_connector():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value = mock_session
    mock_rec = MagicMock()
    mock_rec.values.return_value = [7]
    mock_res = MagicMock()
    mock_res.keys.return_value = ["val"]
    mock_res.__iter__.return_value = [mock_rec]
    mock_session.run.return_value = mock_res

    aconn = AsyncNeo4jConnector(connection=mock_driver)

    async def _test():
        c = await aconn.connect()
        assert c is mock_driver
        cols, rows, _ = await aconn.execute_raw("RETURN 7 AS val")
        assert cols == ["val"]
        assert rows == [{"val": 7}]

        with patch("query_builder.connectors.neo4j.introspect_neo4j") as mock_intro:
            mock_intro.return_value = {"tables": {}}
            schema = await aconn.introspect_schema()
            assert "tables" in schema

            mock_intro.side_effect = Exception("Async error")
            with pytest.raises(IntrospectionError):
                await aconn.introspect_schema()

    asyncio.run(_test())


# ============================================================================
# 9. Kdb+ Connector Tests
# ============================================================================


def test_kdb_cursor_adapter():
    # pykx target
    mock_client = MagicMock()
    mock_res = MagicMock()
    mock_res.columns = ["sym", "price"]
    mock_df = MagicMock()
    mock_df.iterrows.return_value = [(0, ["AAPL", 180.5])]
    mock_res.pd.return_value = mock_df
    mock_client.q.sql.return_value = mock_res

    adapter = _KdbCursorAdapter(mock_client)
    adapter.execute("SELECT sym, price FROM trade")
    assert adapter.description == [("sym",), ("price",)]
    assert adapter.fetchall() == [["AAPL", 180.5]]
    adapter.close()


def test_kdb_connector_lifecycle():
    # Missing driver
    with patch.dict(sys.modules, {"pykx": None, "qpython": None}):
        conn = KdbConnector()
        with pytest.raises(DriverNotInstalledError):
            conn.connect()

    # Driver connect failure
    mock_driver = MagicMock()
    mock_driver.SyncQConnection.side_effect = RuntimeError("q service unavailable")
    mock_driver.QConnection.side_effect = RuntimeError("q service unavailable")
    with patch.dict(sys.modules, {"pykx": mock_driver}):
        conn = KdbConnector()
        with pytest.raises(ConnectionFailedError):
            conn.connect()

    # Connect success and caching
    mock_q_conn = MagicMock()
    mock_driver.QConnection.side_effect = None
    mock_driver.QConnection.return_value = mock_q_conn
    with patch.dict(sys.modules, {"pykx": mock_driver}):
        conn = KdbConnector(host="localhost", port=5000)
        assert conn.connect() is mock_q_conn
        assert conn.connect() is mock_q_conn

    # Preset cursor
    mock_cur = MagicMock()
    mock_res = MagicMock()
    mock_res.columns = ["version"]
    mock_df = MagicMock()
    mock_df.iterrows.return_value = [(0, ["KDB+ 4.0"])]
    mock_res.pd.return_value = mock_df
    mock_cur.q.sql.return_value = mock_res
    conn_preset = KdbConnector(cursor=mock_cur)
    conn_preset.apply_statement_timeout(mock_cur, 5000)

    info = conn_preset.test_connection()
    assert info["status"] == "healthy"
    assert "kdb" in info["engine_version"].lower()

    with patch("query_builder.connectors.kdb.introspect_kdb") as mock_intro:
        mock_intro.return_value = {"tables": {}}
        assert conn_preset.introspect_schema() == {"tables": {}}
        mock_intro.side_effect = Exception("Kdb introspection failed")
        with pytest.raises(IntrospectionError):
            conn_preset.introspect_schema()

    assert PyKXConnector is KdbConnector


def test_async_kdb_connector():
    mock_client = MagicMock()
    mock_res = MagicMock()
    mock_res.columns = ["count"]
    mock_df = MagicMock()
    mock_df.iterrows.return_value = [(0, [500])]
    mock_res.pd.return_value = mock_df
    mock_client.q.sql.return_value = mock_res

    aconn = AsyncKdbConnector(connection=mock_client)

    async def _test():
        c = await aconn.connect()
        assert c is mock_client
        cols, rows, _ = await aconn.execute_raw("count trade")
        assert cols == ["count"]
        assert rows == [{"count": 500}]

        with patch("query_builder.connectors.kdb.introspect_kdb") as mock_intro:
            mock_intro.return_value = {"tables": {}}
            schema = await aconn.introspect_schema()
            assert "tables" in schema

            mock_intro.side_effect = Exception("Async error")
            with pytest.raises(IntrospectionError):
                await aconn.introspect_schema()

    asyncio.run(_test())
    assert AsyncPyKXConnector is AsyncKdbConnector


# ============================================================================
# 10. ClickHouse Native Connector Tests
# ============================================================================


def test_clickhouse_native_cursor_adapter():
    mock_client = MagicMock()
    mock_client.execute.return_value = (
        [(1, "foo"), (2, "bar")],
        [("id", "UInt32"), ("name", "String")],
    )

    adapter = _ClickHouseNativeCursorAdapter(mock_client)
    adapter.execute("SELECT id, name FROM default.hits", [1])
    assert adapter.description == [("id",), ("name",)]
    assert adapter.fetchone() == [1, "foo"]
    assert adapter.fetchall() == [[2, "bar"]]
    adapter.close()


def test_clickhouse_native_connector_lifecycle():
    # Missing driver
    with patch.dict(sys.modules, {"clickhouse_driver": None}):
        conn = ClickHouseNativeConnector()
        with pytest.raises(DriverNotInstalledError):
            conn.connect()

    # Driver connect failure
    mock_driver = MagicMock()
    mock_driver.Client.side_effect = RuntimeError("ClickHouse TCP connection failed")
    with patch.dict(sys.modules, {"clickhouse_driver": mock_driver}):
        conn = ClickHouseNativeConnector()
        with pytest.raises(ConnectionFailedError):
            conn.connect()

    # Connect success and caching
    mock_ch_client = MagicMock()
    mock_driver.Client.side_effect = None
    mock_driver.Client.return_value = mock_ch_client
    with patch.dict(sys.modules, {"clickhouse_driver": mock_driver}):
        conn = ClickHouseNativeConnector(host="ch.local", port=9000)
        assert conn.connect() is mock_ch_client
        assert conn.connect() is mock_ch_client

    # Preset cursor
    mock_cur = MagicMock()
    mock_cur.execute.return_value = ([("23.8.1.1",)], [("version()", "String")])
    conn_preset = ClickHouseNativeConnector(cursor=mock_cur)
    conn_preset.apply_statement_timeout(mock_cur, 5000)
    mock_cur.execute.assert_called_with("SET max_execution_time = 5;")

    info = conn_preset.test_connection()
    assert info["status"] == "healthy"
    assert "ClickHouse" in info["engine_version"]

    with patch(
        "query_builder.connectors.clickhouse_native.introspect_clickhouse_native"
    ) as mock_intro:
        mock_intro.return_value = {"tables": {}}
        assert conn_preset.introspect_schema() == {"tables": {}}
        mock_intro.side_effect = Exception("ClickHouse native introspection failed")
        with pytest.raises(IntrospectionError):
            conn_preset.introspect_schema()


def test_async_clickhouse_native_connector():
    mock_client = MagicMock()
    mock_client.execute.return_value = ([(10,)], [("cnt", "UInt64")])

    aconn = AsyncClickHouseNativeConnector(connection=mock_client)

    async def _test():
        c = await aconn.connect()
        assert c is mock_client
        cols, rows, _ = await aconn.execute_raw("SELECT count() FROM default.hits")
        assert cols == ["cnt"]
        assert rows == [{"cnt": 10}]

        with patch(
            "query_builder.connectors.clickhouse_native.introspect_clickhouse_native"
        ) as mock_intro:
            mock_intro.return_value = {"tables": {}}
            schema = await aconn.introspect_schema()
            assert "tables" in schema

            mock_intro.side_effect = Exception("Async error")
            with pytest.raises(IntrospectionError):
                await aconn.introspect_schema()

    asyncio.run(_test())


# ============================================================================
# 11. Registry Verification
# ============================================================================


def test_expanded_connectors_registry_lookups():
    # Sync connectors & aliases
    assert isinstance(ConnectorRegistry.get("doris"), DorisConnector) and isinstance(
        get_connector("doris"), DorisConnector
    )
    assert isinstance(ConnectorRegistry.get("apache_doris"), DorisConnector)
    assert isinstance(ConnectorRegistry.get("pydoris"), DorisConnector)

    assert isinstance(ConnectorRegistry.get("impala"), ImpalaConnector) and isinstance(
        get_connector("impala"), ImpalaConnector
    )
    assert isinstance(ConnectorRegistry.get("apache_impala"), ImpalaConnector)
    assert isinstance(ConnectorRegistry.get("impyla"), ImpalaConnector)

    assert isinstance(ConnectorRegistry.get("hive"), HiveConnector) and isinstance(
        get_connector("hive"), HiveConnector
    )
    assert isinstance(ConnectorRegistry.get("apache_hive"), HiveConnector)
    assert isinstance(ConnectorRegistry.get("pyhive"), HiveConnector)

    assert isinstance(ConnectorRegistry.get("kyuubi"), KyuubiConnector) and isinstance(
        get_connector("kyuubi"), KyuubiConnector
    )
    assert isinstance(ConnectorRegistry.get("apache_kyuubi"), KyuubiConnector)

    assert isinstance(ConnectorRegistry.get("drill"), DrillConnector) and isinstance(
        get_connector("drill"), DrillConnector
    )
    assert isinstance(ConnectorRegistry.get("apache_drill"), DrillConnector)
    assert isinstance(ConnectorRegistry.get("pydrill"), DrillConnector)

    assert isinstance(
        ConnectorRegistry.get("yugabyte"), YugabyteDBConnector
    ) and isinstance(get_connector("yugabyte"), YugabyteDBConnector)
    assert isinstance(ConnectorRegistry.get("yugabytedb"), YugabyteDBConnector)

    assert isinstance(
        ConnectorRegistry.get("opensearch"), OpenSearchConnector
    ) and isinstance(get_connector("opensearch"), OpenSearchConnector)
    assert isinstance(ConnectorRegistry.get("opensearch_sql"), OpenSearchConnector)

    assert isinstance(ConnectorRegistry.get("neo4j"), Neo4jConnector) and isinstance(
        get_connector("neo4j"), Neo4jConnector
    )
    assert isinstance(ConnectorRegistry.get("cypher"), Neo4jConnector)
    assert isinstance(ConnectorRegistry.get("neo4j_sql"), Neo4jConnector)

    assert isinstance(ConnectorRegistry.get("kdb"), KdbConnector) and isinstance(
        get_connector("kdb"), KdbConnector
    )
    assert isinstance(ConnectorRegistry.get("kdb+"), KdbConnector)
    assert isinstance(ConnectorRegistry.get("pykx"), KdbConnector)
    assert isinstance(ConnectorRegistry.get("q"), KdbConnector)

    assert isinstance(
        ConnectorRegistry.get("clickhouse_native"), ClickHouseNativeConnector
    ) and isinstance(get_connector("clickhouse_native"), ClickHouseNativeConnector)
    assert isinstance(ConnectorRegistry.get("ch_native"), ClickHouseNativeConnector)
    assert isinstance(
        ConnectorRegistry.get("clickhouse_tcp"), ClickHouseNativeConnector
    )

    # Async connectors & aliases
    assert isinstance(ConnectorRegistry.get("async_doris"), AsyncDorisConnector)
    assert isinstance(ConnectorRegistry.get("async_apache_doris"), AsyncDorisConnector)

    assert isinstance(ConnectorRegistry.get("async_impala"), AsyncImpalaConnector)
    assert isinstance(
        ConnectorRegistry.get("async_apache_impala"), AsyncImpalaConnector
    )

    assert isinstance(ConnectorRegistry.get("async_hive"), AsyncHiveConnector)
    assert isinstance(ConnectorRegistry.get("async_apache_hive"), AsyncHiveConnector)

    assert isinstance(ConnectorRegistry.get("async_kyuubi"), AsyncKyuubiConnector)
    assert isinstance(
        ConnectorRegistry.get("async_apache_kyuubi"), AsyncKyuubiConnector
    )

    assert isinstance(ConnectorRegistry.get("async_drill"), AsyncDrillConnector)
    assert isinstance(ConnectorRegistry.get("async_apache_drill"), AsyncDrillConnector)

    assert isinstance(ConnectorRegistry.get("async_yugabyte"), AsyncYugabyteDBConnector)
    assert isinstance(
        ConnectorRegistry.get("async_yugabytedb"), AsyncYugabyteDBConnector
    )

    assert isinstance(
        ConnectorRegistry.get("async_opensearch"), AsyncOpenSearchConnector
    )
    assert isinstance(
        ConnectorRegistry.get("async_opensearch_sql"), AsyncOpenSearchConnector
    )

    assert isinstance(ConnectorRegistry.get("async_neo4j"), AsyncNeo4jConnector)
    assert isinstance(ConnectorRegistry.get("async_cypher"), AsyncNeo4jConnector)

    assert isinstance(ConnectorRegistry.get("async_kdb"), AsyncKdbConnector)
    assert isinstance(ConnectorRegistry.get("async_kdb+"), AsyncKdbConnector)
    assert isinstance(ConnectorRegistry.get("async_pykx"), AsyncKdbConnector)

    assert isinstance(
        ConnectorRegistry.get("async_clickhouse_native"),
        AsyncClickHouseNativeConnector,
    )
    assert isinstance(
        ConnectorRegistry.get("async_ch_native"), AsyncClickHouseNativeConnector
    )
