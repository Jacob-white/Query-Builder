"""
Comprehensive Unit and Integration Tests for Expanded Connectors Ecosystem.
============================================================================
Covers PrestoDB, Druid, Pinot, StarRocks, Materialize, RisingWave, CrateDB,
InfluxDB, AlloyDB, Vertica, SAP HANA, OceanBase, and ScyllaDB connectors,
including async execution protocols, statement timeouts, schema introspection,
and error handling.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from query_builder.connectors import (
    AlloyDBConnector,
    AsyncCrateConnector,
    AsyncCrateDBConnector,
    AsyncMaterializeConnector,
    AsyncPrestoConnector,
    AsyncPrestoDBConnector,
    AsyncRisingWaveConnector,
    AsyncStarRocksConnector,
    CassandraConnector,
    ConnectionFailedError,
    CrateConnector,
    CrateDBConnector,
    DriverNotInstalledError,
    DruidConnector,
    HANAConnector,
    InfluxDBConnector,
    IntrospectionError,
    IOxConnector,
    MaterializeConnector,
    OceanBaseConnector,
    PinotConnector,
    PrestoConnector,
    PrestoDBConnector,
    RisingWaveConnector,
    SAPHANAConnector,
    ScyllaDBConnector,
    StarRocksConnector,
    VerticaConnector,
    introspect_cratedb,
    introspect_druid,
    introspect_saphana,
    introspect_scylladb,
)
from query_builder.connectors.influxdb import _InfluxCursorAdapter
from query_builder.connectors.scylladb import _ScyllaCursorAdapter
from query_builder.dialects import (
    BaseDialect,
    ClickHouseDialect,
    CrateDBDialect,
    DruidDialect,
    OracleDialect,
    SAPHANADialect,
    ScyllaDBDialect,
    SQLiteDialect,
)
from query_builder.executor import async_execute

# ============================================================================
# 1. PrestoDB Connector Tests (Sync & Async)
# ============================================================================


def test_prestodb_connector_sync_lifecycle_and_execution():
    conn = PrestoDBConnector(catalog="tpch", schema_name="sf1")
    assert conn.dialect_name == "presto"
    assert conn.catalog == "tpch"
    assert conn.schema_name == "sf1"
    assert PrestoConnector is PrestoDBConnector

    # Missing driver
    with (
        patch.dict(
            sys.modules,
            {
                "prestodb": None,
                "prestodb.dbapi": None,
                "trino": None,
                "trino.dbapi": None,
            },
        ),
        pytest.raises(DriverNotInstalledError, match="prestodb"),
    ):
        conn.connect()

    # Connection failure
    mock_driver = MagicMock()
    mock_driver.connect.side_effect = RuntimeError("Presto cluster unavailable")
    with (
        patch.dict(sys.modules, {"prestodb": mock_driver}),
        pytest.raises(ConnectionFailedError, match="Failed to connect to PrestoDB"),
    ):
        conn.connect()

    # Connection success and caching
    mock_conn = MagicMock()
    mock_driver.connect.side_effect = None
    mock_driver.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"prestodb": mock_driver}):
        assert conn.connect() is mock_conn
        assert conn.connect() is mock_conn

    # test_connection with and without version row
    mock_cur = MagicMock()
    conn._cursor = mock_cur
    mock_cur.fetchone.side_effect = [(1,), ("Presto 0.280",)]
    info = conn.test_connection()
    assert info["engine_version"] == "Presto 0.280"

    mock_cur.fetchone.side_effect = [(1,), None]
    info_no_row = conn.test_connection()
    assert "engine_version" not in info_no_row

    # introspect_schema success
    mock_cur.fetchall.side_effect = [
        [("lineitem",)],
        [("lineitem", "orderkey", "bigint", "NO")],
        [],
    ]
    schema = conn.introspect_schema()
    assert "lineitem" in schema["tables"]

    # introspect_schema failure
    mock_cur.execute.side_effect = RuntimeError("Introspection error")
    with pytest.raises(
        IntrospectionError, match="Failed to introspect PrestoDB schema"
    ):
        conn.introspect_schema()
    mock_cur.execute.side_effect = None


def test_prestodb_connector_async_lifecycle():
    async def _test():
        conn = AsyncPrestoDBConnector(catalog="hive", schema_name="analytics")
        assert conn.dialect_name == "presto"
        assert AsyncPrestoConnector is AsyncPrestoDBConnector

        # Missing driver
        with (
            patch.dict(
                sys.modules,
                {
                    "prestodb": None,
                    "prestodb.dbapi": None,
                    "trino": None,
                    "trino.dbapi": None,
                },
            ),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection failure
        mock_driver = MagicMock()
        mock_driver.connect.side_effect = RuntimeError("Cluster timeout")
        with (
            patch.dict(sys.modules, {"prestodb": mock_driver}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # Success and cached
        mock_conn = MagicMock()
        mock_driver.connect.side_effect = None
        mock_driver.connect.return_value = mock_conn
        with patch.dict(sys.modules, {"prestodb": mock_driver}):
            c = await conn.connect()
            assert c is mock_conn
            c2 = await conn.connect()
            assert c2 is mock_conn

            # execute_raw with and without params
            mock_cur = MagicMock()
            mock_conn.cursor.return_value = mock_cur
            mock_cur.description = [("id",), ("name",)]
            mock_cur.fetchall.return_value = [(1, "item1")]

            cols, rows, _latency = await conn.execute_raw(
                "SELECT * FROM items WHERE id = ?", [1]
            )
            assert cols == ["id", "name"]
            assert rows == [{"id": 1, "name": "item1"}]
            mock_cur.execute.assert_called_with("SELECT * FROM items WHERE id = ?", [1])

            cols, rows, _latency = await conn.execute_raw("SELECT * FROM items")
            assert cols == ["id", "name"]
            mock_cur.execute.assert_called_with("SELECT * FROM items")

            # async_execute harness
            res = await async_execute(conn, {"table": "items", "limit": 10})
            assert res["dialect"] == "presto"

    asyncio.run(_test())


# ============================================================================
# 2. Apache Druid Connector Tests
# ============================================================================


def test_druid_connector_lifecycle():
    conn = DruidConnector(
        host="druid-broker", port=8082, path="/druid/v2/sql", schema_name="druid"
    )
    assert conn.dialect_name == "druid"
    assert conn.host == "druid-broker"
    assert conn.port == 8082

    # Driver missing
    with (
        patch.dict(sys.modules, {"pydruid": None, "pydruid.db": None}),
        pytest.raises(DriverNotInstalledError, match="pydruid"),
    ):
        conn.connect()

    # Connection failure
    mock_pydruid = MagicMock()
    mock_pydruid.connect.side_effect = RuntimeError("Broker down")
    with (
        patch.dict(sys.modules, {"pydruid": mock_pydruid}),
        pytest.raises(ConnectionFailedError, match="Failed to connect to Apache Druid"),
    ):
        conn.connect()

    # Connection success and cached
    mock_conn = MagicMock()
    mock_pydruid.connect.side_effect = None
    mock_pydruid.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"pydruid": mock_pydruid}):
        assert conn.connect() is mock_conn
        assert conn.connect() is mock_conn

    # test_connection
    mock_cur = MagicMock()
    conn._cursor = mock_cur
    info = conn.test_connection()
    assert info["engine_version"] == "Apache Druid"

    # introspect_schema success
    mock_cur.fetchall.side_effect = [
        [("wikipedia",)],
        [("wikipedia", "__time", "TIMESTAMP", "NO")],
    ]
    schema = conn.introspect_schema()
    assert "wikipedia" in schema["tables"]
    assert schema["tables"]["wikipedia"]["columns"][0]["is_primary"] is True

    # introspect_schema error
    mock_cur.execute.side_effect = RuntimeError("Schema catalog error")
    with pytest.raises(
        IntrospectionError, match="Failed to introspect Apache Druid schema"
    ):
        conn.introspect_schema()


# ============================================================================
# 3. Apache Pinot Connector Tests
# ============================================================================


def test_pinot_connector_lifecycle():
    conn = PinotConnector(
        host="pinot-broker", port=8099, path="/query/sql", scheme="http"
    )
    assert conn.dialect_name == "pinot"
    assert conn.host == "pinot-broker"
    assert conn.port == 8099

    # Driver missing
    with (
        patch.dict(sys.modules, {"pinotdb": None}),
        pytest.raises(DriverNotInstalledError, match="pinotdb"),
    ):
        conn.connect()

    # Connection failure
    mock_pinotdb = MagicMock()
    mock_pinotdb.connect.side_effect = RuntimeError("Broker connection refused")
    with (
        patch.dict(sys.modules, {"pinotdb": mock_pinotdb}),
        pytest.raises(
            ConnectionFailedError, match="Failed to connect to Apache Pinot broker"
        ),
    ):
        conn.connect()

    # Connection success and cached
    mock_conn = MagicMock()
    mock_pinotdb.connect.side_effect = None
    mock_pinotdb.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"pinotdb": mock_pinotdb}):
        assert conn.connect() is mock_conn
        assert conn.connect() is mock_conn

    # test_connection
    mock_cur = MagicMock()
    conn._cursor = mock_cur
    info = conn.test_connection()
    assert info["engine_version"] == "Apache Pinot OLAP"

    # introspect_schema success
    mock_cur.fetchall.side_effect = [
        [("airlineStats",)],
        [("airlineStats", "FlightNum", "INT"), ("airlineStats", "user_id", "INT")],
    ]
    schema = conn.introspect_schema()
    assert "airlineStats" in schema["tables"]
    assert schema["tables"]["airlineStats"]["has_user_id"] is True

    # introspect_schema error
    mock_cur.execute.side_effect = RuntimeError("Pinot metadata error")
    with pytest.raises(
        IntrospectionError, match="Failed to introspect Apache Pinot schema"
    ):
        conn.introspect_schema()


# ============================================================================
# 4. StarRocks Connector Tests (Sync & Async)
# ============================================================================


def test_starrocks_connector_sync_lifecycle():
    conn = StarRocksConnector(
        host="starrocks-fe", port=9030, database="analytics", user="root"
    )
    assert conn.dialect_name == "starrocks"

    # Driver missing
    with (
        patch.dict(sys.modules, {"starrocks": None, "pymysql": None, "MySQLdb": None}),
        pytest.raises(DriverNotInstalledError, match="starrocks"),
    ):
        conn.connect()

    # Connection failure
    mock_driver = MagicMock()
    mock_driver.__name__ = "pymysql"
    mock_driver.connect.side_effect = RuntimeError("FE unreachable")
    with (
        patch.dict(sys.modules, {"pymysql": mock_driver}),
        pytest.raises(ConnectionFailedError, match="Failed to connect to StarRocks"),
    ):
        conn.connect()

    # Connection success (pymysql branch and non-pymysql branch)
    mock_conn = MagicMock()
    mock_driver.connect.side_effect = None
    mock_driver.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"pymysql": mock_driver}):
        assert conn.connect() is mock_conn
        assert conn.connect() is mock_conn

    # non-pymysql connect branch
    conn_alt = StarRocksConnector()
    mock_mysqldb = MagicMock()
    mock_mysqldb.__name__ = "MySQLdb"
    mock_mysqldb.connect.return_value = mock_conn
    with patch.dict(
        sys.modules, {"starrocks": None, "pymysql": None, "MySQLdb": mock_mysqldb}
    ):
        assert conn_alt.connect() is mock_conn

    # apply_statement_timeout
    mock_cur = MagicMock()
    conn.apply_statement_timeout(mock_cur, 5000)
    mock_cur.execute.assert_called_with("SET query_timeout = 5;")

    # test_connection
    conn._cursor = mock_cur
    info = conn.test_connection()
    assert info["engine_version"] == "StarRocks MPP Engine"

    # introspect_schema success and failure
    mock_cur.fetchall.side_effect = [
        [("events",)],
        [
            ("events", "event_id", "bigint", "NO"),
            ("events", "user_id", "bigint", "YES"),
        ],
        [],
    ]
    schema = conn.introspect_schema()
    assert "events" in schema["tables"]
    assert schema["tables"]["events"]["has_user_id"] is True

    mock_cur.execute.side_effect = RuntimeError("Introspection error")
    with pytest.raises(
        IntrospectionError, match="Failed to introspect StarRocks schema"
    ):
        conn.introspect_schema()


def test_starrocks_connector_async_lifecycle():
    async def _test():
        conn = AsyncStarRocksConnector(host="starrocks-fe", database="sales")
        assert conn.dialect_name == "starrocks"

        # Driver missing
        with (
            patch.dict(sys.modules, {"pymysql": None, "starrocks": None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection failure
        mock_driver = MagicMock()
        mock_driver.connect.side_effect = RuntimeError("Auth failed")
        with (
            patch.dict(sys.modules, {"pymysql": mock_driver}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # Success and raw query execution
        mock_conn = MagicMock()
        mock_driver.connect.side_effect = None
        mock_driver.connect.return_value = mock_conn
        with patch.dict(sys.modules, {"pymysql": mock_driver}):
            c = await conn.connect()
            assert c is mock_conn
            c2 = await conn.connect()
            assert c2 is mock_conn

            mock_cur = MagicMock()
            mock_conn.cursor.return_value = mock_cur
            mock_cur.description = [("total",)]
            mock_cur.fetchall.return_value = [(100,)]

            cols, rows, _latency = await conn.execute_raw(
                "SELECT count(*) as total FROM sales WHERE dt = %s", ["2026-10-01"]
            )
            assert cols == ["total"]
            assert rows == [{"total": 100}]

            cols, rows, _latency = await conn.execute_raw("SELECT 1")
            assert cols == ["total"]

    asyncio.run(_test())


# ============================================================================
# 5. Materialize Connector Tests (Sync & Async)
# ============================================================================


def test_materialize_connector_sync_lifecycle():
    conn = MaterializeConnector(cluster="analytics_cluster", schema_name="public")
    assert conn.dialect_name == "materialize"
    assert conn.cluster == "analytics_cluster"

    # Driver missing
    with (
        patch.dict(sys.modules, {"psycopg": None, "psycopg2": None}),
        pytest.raises(DriverNotInstalledError, match="materialize"),
    ):
        conn.connect()

    # Connection failure
    mock_driver = MagicMock()
    mock_driver.connect.side_effect = RuntimeError("Materialize mz_cluster inactive")
    with (
        patch.dict(sys.modules, {"psycopg": mock_driver}),
        pytest.raises(ConnectionFailedError, match="Failed to connect to Materialize"),
    ):
        conn.connect()

    # Connection success with cluster SET
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_driver.connect.side_effect = None
    mock_driver.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"psycopg": mock_driver}):
        assert conn.connect() is mock_conn
        mock_cur.execute.assert_called_with("SET cluster = analytics_cluster;")
        assert conn.connect() is mock_conn

    # Test without cluster
    conn_no_cluster = MaterializeConnector(cluster=None)
    with patch.dict(sys.modules, {"psycopg": mock_driver}):
        assert conn_no_cluster.connect() is mock_conn

    # apply_statement_timeout
    conn.apply_statement_timeout(mock_cur, 3000)
    mock_cur.execute.assert_called_with("SET statement_timeout = '3000ms';")

    # test_connection
    conn._cursor = mock_cur
    info = conn.test_connection()
    assert info["engine_version"] == "Materialize Streaming SQL"
    assert info["mz_cluster"] == "analytics_cluster"

    conn_no_cluster._cursor = mock_cur
    info_no_cluster = conn_no_cluster.test_connection()
    assert "mz_cluster" not in info_no_cluster

    # introspect_schema
    mock_cur.fetchall.side_effect = [
        [("mv_orders",)],
        [("mv_orders", "order_id", "text", "NO")],
        [],
    ]
    schema = conn.introspect_schema()
    assert "mv_orders" in schema["tables"]

    mock_cur.execute.side_effect = RuntimeError("Introspection error")
    with pytest.raises(
        IntrospectionError, match="Failed to introspect Materialize schema"
    ):
        conn.introspect_schema()


def test_materialize_connector_async_lifecycle():
    async def _test():
        conn = AsyncMaterializeConnector(cluster="stream_cluster")
        assert conn.dialect_name == "materialize"

        with (
            patch.dict(sys.modules, {"psycopg": None, "psycopg2": None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        mock_driver = MagicMock()
        mock_driver.connect.side_effect = RuntimeError("Conn error")
        with (
            patch.dict(sys.modules, {"psycopg": mock_driver}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        mock_conn = MagicMock()
        mock_driver.connect.side_effect = None
        mock_driver.connect.return_value = mock_conn
        with patch.dict(sys.modules, {"psycopg": mock_driver}):
            c = await conn.connect()
            assert c is mock_conn

            mock_cur = MagicMock()
            mock_conn.cursor.return_value = mock_cur
            mock_cur.description = [("val",)]
            mock_cur.fetchall.return_value = [("ok",)]

            _cols, rows, _latency = await conn.execute_raw(
                "SELECT val FROM stream WHERE id = %s", ["k1"]
            )
            assert rows == [{"val": "ok"}]
            _cols, rows, _latency = await conn.execute_raw("SELECT val FROM stream")
            assert rows == [{"val": "ok"}]

    asyncio.run(_test())


# ============================================================================
# 6. RisingWave Connector Tests (Sync & Async)
# ============================================================================


def test_risingwave_connector_sync_lifecycle():
    conn = RisingWaveConnector(database="rw_db", schema_name="public")
    assert conn.dialect_name == "risingwave"
    assert conn.database == "rw_db"

    # Driver missing
    with (
        patch.dict(sys.modules, {"psycopg": None, "psycopg2": None}),
        pytest.raises(DriverNotInstalledError, match="risingwave"),
    ):
        conn.connect()

    # Connection failure
    mock_driver = MagicMock()
    mock_driver.connect.side_effect = RuntimeError("Frontend compute node down")
    with (
        patch.dict(sys.modules, {"psycopg": mock_driver}),
        pytest.raises(ConnectionFailedError, match="Failed to connect to RisingWave"),
    ):
        conn.connect()

    # Connection success and cached
    mock_conn = MagicMock()
    mock_driver.connect.side_effect = None
    mock_driver.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"psycopg": mock_driver}):
        assert conn.connect() is mock_conn
        assert conn.connect() is mock_conn

    # apply_statement_timeout
    mock_cur = MagicMock()
    conn.apply_statement_timeout(mock_cur, 4000)
    mock_cur.execute.assert_called_with("SET statement_timeout = 4000;")

    # test_connection
    conn._cursor = mock_cur
    info = conn.test_connection()
    assert info["engine_version"] == "RisingWave Streaming Database"

    # introspect_schema
    mock_cur.fetchall.side_effect = [
        [("rw_mv",)],
        [("rw_mv", "sensor_id", "int", "NO")],
        [],
    ]
    schema = conn.introspect_schema()
    assert "rw_mv" in schema["tables"]

    mock_cur.execute.side_effect = RuntimeError("Introspection error")
    with pytest.raises(
        IntrospectionError, match="Failed to introspect RisingWave schema"
    ):
        conn.introspect_schema()


def test_risingwave_connector_async_lifecycle():
    async def _test():
        conn = AsyncRisingWaveConnector(database="stream_db")
        assert conn.dialect_name == "risingwave"

        with (
            patch.dict(sys.modules, {"psycopg": None, "psycopg2": None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        mock_driver = MagicMock()
        mock_driver.connect.side_effect = RuntimeError("Conn err")
        with (
            patch.dict(sys.modules, {"psycopg": mock_driver}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        mock_conn = MagicMock()
        mock_driver.connect.side_effect = None
        mock_driver.connect.return_value = mock_conn
        with patch.dict(sys.modules, {"psycopg": mock_driver}):
            c = await conn.connect()
            assert c is mock_conn

            mock_cur = MagicMock()
            mock_conn.cursor.return_value = mock_cur
            mock_cur.description = [("count",)]
            mock_cur.fetchall.return_value = [(42,)]

            _cols, rows, _latency = await conn.execute_raw(
                "SELECT count FROM metrics WHERE id = %s", [1]
            )
            assert rows == [{"count": 42}]
            _cols, rows, _latency = await conn.execute_raw("SELECT count FROM metrics")
            assert rows == [{"count": 42}]

    asyncio.run(_test())


# ============================================================================
# 7. CrateDB Connector Tests (Sync & Async)
# ============================================================================


def test_cratedb_connector_sync_lifecycle():
    conn = CrateDBConnector(
        schema_name="doc", servers=["crate-node1:4200", "crate-node2:4200"]
    )
    assert conn.dialect_name == "cratedb"
    assert conn.schema_name == "doc"
    assert CrateConnector is CrateDBConnector

    # Driver missing
    with (
        patch.dict(
            sys.modules,
            {"crate": None, "crate.client": None, "psycopg2": None, "psycopg": None},
        ),
        pytest.raises(DriverNotInstalledError, match="cratedb"),
    ):
        conn.connect()

    # Connection failure
    mock_driver = MagicMock()
    mock_driver.connect.side_effect = RuntimeError("Crate cluster down")
    with (
        patch.dict(sys.modules, {"crate.client": mock_driver}),
        pytest.raises(ConnectionFailedError, match="Failed to connect to CrateDB"),
    ):
        conn.connect()

    # Connection success and cached
    mock_conn = MagicMock()
    mock_driver.connect.side_effect = None
    mock_driver.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"crate.client": mock_driver}):
        assert conn.connect() is mock_conn
        assert conn.connect() is mock_conn
        conn_bare = CrateDBConnector(servers=None, schema_name="")
        assert conn_bare.connect() is mock_conn

    # apply_statement_timeout
    mock_cur = MagicMock()
    conn.apply_statement_timeout(mock_cur, 6000)
    mock_cur.execute.assert_called_with("SET statement_timeout = 6000;")

    # test_connection
    conn._cursor = mock_cur
    info = conn.test_connection()
    assert info["engine_version"] == "CrateDB Distributed Database"

    # introspect_schema
    mock_cur.fetchall.side_effect = [
        [("metrics",)],
        [("metrics", "host", "string", "NO")],
    ]
    schema = conn.introspect_schema()
    assert "metrics" in schema["tables"]

    mock_cur.execute.side_effect = RuntimeError("Introspection error")
    with pytest.raises(IntrospectionError, match="Failed to introspect CrateDB schema"):
        conn.introspect_schema()


def test_cratedb_connector_async_lifecycle():
    async def _test():
        conn = AsyncCrateDBConnector(schema_name="doc", servers=["node1"])
        assert conn.dialect_name == "cratedb"
        assert AsyncCrateConnector is AsyncCrateDBConnector

        with (
            patch.dict(
                sys.modules,
                {
                    "crate": None,
                    "crate.client": None,
                    "psycopg2": None,
                    "psycopg": None,
                },
            ),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        mock_driver = MagicMock()
        mock_driver.connect.side_effect = RuntimeError("Conn err")
        with (
            patch.dict(sys.modules, {"crate.client": mock_driver}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        mock_conn = MagicMock()
        mock_driver.connect.side_effect = None
        mock_driver.connect.return_value = mock_conn
        with patch.dict(sys.modules, {"crate.client": mock_driver}):
            c = await conn.connect()
            assert c is mock_conn
            conn_bare = AsyncCrateDBConnector(servers=None, schema_name="")
            assert await conn_bare.connect() is mock_conn

            mock_cur = MagicMock()
            mock_conn.cursor.return_value = mock_cur
            mock_cur.description = [("metric",)]
            mock_cur.fetchall.return_value = [("cpu",)]

            _cols, rows, _latency = await conn.execute_raw(
                "SELECT metric FROM logs WHERE id = %s", [1]
            )
            assert rows == [{"metric": "cpu"}]
            _cols, rows, _latency = await conn.execute_raw("SELECT metric FROM logs")
            assert rows == [{"metric": "cpu"}]

    asyncio.run(_test())


# ============================================================================
# 8. InfluxDB Connector Tests
# ============================================================================


def test_influxdb_connector_lifecycle():
    conn = InfluxDBConnector(
        host="influxdb.local", token="secret-token", database="iot"
    )
    assert conn.dialect_name == "influxdb"
    assert conn.database == "iot"
    assert IOxConnector is InfluxDBConnector

    # Driver missing
    with (
        patch.dict(
            sys.modules,
            {
                "influxdb3_python": None,
                "influxdb3_client": None,
                "flightsql": None,
                "pyarrow.flight": None,
            },
        ),
        pytest.raises(DriverNotInstalledError, match="influxdb"),
    ):
        conn.connect()

    # Connection failure
    mock_driver = MagicMock()
    mock_driver.connect.side_effect = RuntimeError("InfluxDB connection rejected")
    with (
        patch.dict(sys.modules, {"flightsql": mock_driver}),
        pytest.raises(ConnectionFailedError, match="Failed to connect to InfluxDB 3.0"),
    ):
        conn.connect()

    # Connection success via connect
    mock_conn = MagicMock()
    mock_driver.connect.side_effect = None
    mock_driver.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"flightsql": mock_driver}):
        assert conn.connect() is mock_conn
        assert conn.connect() is mock_conn

    # Alternative client instantiation branch (InfluxDBClient3)
    conn_client = InfluxDBConnector()
    mock_client_module = MagicMock(spec=["InfluxDBClient3"])
    mock_client_instance = MagicMock()
    mock_client_module.InfluxDBClient3.return_value = mock_client_instance
    with patch.dict(
        sys.modules, {"flightsql": None, "influxdb3_client": mock_client_module}
    ):
        assert conn_client.connect() is mock_client_instance

    # Fallback driver branch
    conn_fallback = InfluxDBConnector()
    mock_raw_driver = MagicMock(spec=[])
    with patch.dict(
        sys.modules,
        {
            "flightsql": None,
            "influxdb3_client": None,
            "pyarrow.flight": mock_raw_driver,
        },
    ):
        assert conn_fallback.connect() is mock_raw_driver

    # test_connection
    mock_cur = MagicMock()
    conn._cursor = mock_cur
    info = conn.test_connection()
    assert info["engine_version"] == "InfluxDB 3.0 / IOx SQL Engine"
    assert info["database"] == "iot"

    # introspect_schema
    mock_cur.fetchall.side_effect = [
        [("cpu_metrics",)],
        [("cpu_metrics", "usage", "float", "NO")],
        [],
    ]
    schema = conn.introspect_schema()
    assert "cpu_metrics" in schema["tables"]

    mock_cur.execute.side_effect = RuntimeError("Introspection error")
    with pytest.raises(
        IntrospectionError, match="Failed to introspect InfluxDB schema"
    ):
        conn.introspect_schema()


# ============================================================================
# 9. Google Cloud AlloyDB Connector Tests
# ============================================================================


def test_alloydb_connector_lifecycle():
    conn = AlloyDBConnector(
        project_id="my-gcp-proj",
        region="us-central1",
        cluster_id="alloydb-cluster",
        instance_id="primary-instance",
        enable_columnar_engine=True,
    )
    assert conn.dialect_name == "alloydb"
    assert conn.project_id == "my-gcp-proj"

    # Driver missing
    with (
        patch.dict(
            sys.modules,
            {"google.cloud.alloydb.connector": None, "psycopg": None, "psycopg2": None},
        ),
        pytest.raises(DriverNotInstalledError, match="alloydb"),
    ):
        conn.connect()

    # Connection failure
    mock_driver = MagicMock()
    mock_driver.connect.side_effect = RuntimeError("IAM permission denied")
    with (
        patch.dict(sys.modules, {"psycopg": mock_driver}),
        pytest.raises(
            ConnectionFailedError, match="Failed to connect to Google Cloud AlloyDB"
        ),
    ):
        conn.connect()

    # Connection success via driver.connect
    mock_conn = MagicMock()
    mock_driver.connect.side_effect = None
    mock_driver.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"psycopg": mock_driver}):
        assert conn.connect() is mock_conn
        assert conn.connect() is mock_conn

    # Connector abstraction branch (google.cloud.alloydb.connector.Connector)
    conn_gcp = AlloyDBConnector(
        project_id="p1", region="r1", cluster_id="c1", instance_id="i1"
    )
    mock_alloy_mod = MagicMock()
    mock_connector_cls = MagicMock()
    mock_alloy_mod.Connector = mock_connector_cls
    del mock_alloy_mod.connect
    mock_connector_inst = MagicMock()
    mock_connector_cls.return_value = mock_connector_inst
    mock_connector_inst.connect.return_value = mock_conn
    with patch.dict(
        sys.modules,
        {
            "google.cloud.alloydb.connector": mock_alloy_mod,
            "psycopg": None,
            "psycopg2": None,
        },
    ):
        assert conn_gcp.connect() is mock_conn

    # Unrecognized driver interface
    conn_bad = AlloyDBConnector()
    with (
        patch.dict(sys.modules, {"psycopg": object()}),
        pytest.raises(ConnectionFailedError, match="Unrecognized AlloyDB driver"),
    ):
        conn_bad.connect()

    # apply_statement_timeout
    mock_cur = MagicMock()
    conn.apply_statement_timeout(mock_cur, 3500)
    mock_cur.execute.assert_called_with("SET LOCAL statement_timeout = 3500;")

    # test_connection
    conn._cursor = mock_cur
    info = conn.test_connection()
    assert info["engine_version"] == "Google Cloud AlloyDB for PostgreSQL"
    assert info["alloydb_cluster"] == "alloydb-cluster"
    assert info["alloydb_instance"] == "primary-instance"
    assert info["columnar_engine"] is True

    # test_connection without cluster/instance
    conn_bare = AlloyDBConnector()
    conn_bare._cursor = mock_cur
    info_bare = conn_bare.test_connection()
    assert "alloydb_cluster" not in info_bare
    assert "alloydb_instance" not in info_bare


# ============================================================================
# 10. Vertica Connector Tests
# ============================================================================


def test_vertica_connector_lifecycle():
    conn = VerticaConnector(
        host="vertica.internal", port=5433, database="VMart", user="dbadmin"
    )
    assert conn.dialect_name == "vertica"
    assert conn.host == "vertica.internal"

    # Driver missing
    with (
        patch.dict(sys.modules, {"vertica_python": None}),
        pytest.raises(DriverNotInstalledError, match="vertica-python"),
    ):
        conn.connect()

    # Connection failure
    mock_vertica = MagicMock()
    mock_vertica.connect.side_effect = RuntimeError("SSL handshake failed")
    with (
        patch.dict(sys.modules, {"vertica_python": mock_vertica}),
        pytest.raises(ConnectionFailedError, match="Failed to connect to Vertica"),
    ):
        conn.connect()

    # Connection success and cached
    mock_conn = MagicMock()
    mock_vertica.connect.side_effect = None
    mock_vertica.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"vertica_python": mock_vertica}):
        assert conn.connect() is mock_conn
        assert conn.connect() is mock_conn

    # apply_statement_timeout
    mock_cur = MagicMock()
    conn.apply_statement_timeout(mock_cur, 4500)
    mock_cur.execute.assert_called_with("SET SESSION RUNTIMECAP = '4s';")

    # test_connection
    conn._cursor = mock_cur
    info = conn.test_connection()
    assert info["engine_version"] == "Vertica Columnar Analytical Database"

    # introspect_schema
    mock_cur.fetchall.side_effect = [
        [("sales_fact",)],
        [("sales_fact", "sale_id", "int", "NO")],
        [],
    ]
    schema = conn.introspect_schema()
    assert "sales_fact" in schema["tables"]

    mock_cur.execute.side_effect = RuntimeError("Introspection error")
    with pytest.raises(IntrospectionError, match="Failed to introspect Vertica schema"):
        conn.introspect_schema()


# ============================================================================
# 11. SAP HANA Connector Tests
# ============================================================================


def test_saphana_connector_lifecycle():
    conn = SAPHANAConnector(address="hana.corp", port=39015, schema_name="SYSTEM")
    assert conn.dialect_name == "saphana"
    assert conn.address == "hana.corp"
    assert HANAConnector is SAPHANAConnector

    # Driver missing
    with (
        patch.dict(sys.modules, {"hdbcli": None, "hdbcli.dbapi": None}),
        pytest.raises(DriverNotInstalledError, match="hdbcli"),
    ):
        conn.connect()

    # Connection failure
    mock_hdbcli = MagicMock()
    mock_hdbcli.connect.side_effect = RuntimeError("Authentication token expired")
    with (
        patch.dict(sys.modules, {"hdbcli": mock_hdbcli}),
        pytest.raises(ConnectionFailedError, match="Failed to connect to SAP HANA"),
    ):
        conn.connect()

    # Connection success and cached
    mock_conn = MagicMock()
    mock_hdbcli.connect.side_effect = None
    mock_hdbcli.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"hdbcli": mock_hdbcli}):
        assert conn.connect() is mock_conn
        assert conn.connect() is mock_conn

    # test_connection
    mock_cur = MagicMock()
    conn._cursor = mock_cur
    info = conn.test_connection()
    assert info["engine_version"] == "SAP HANA In-Memory Database"

    # introspect_schema
    mock_cur.fetchall.side_effect = [
        [("BKPF",)],
        [("BKPF", "BELNR", "NVARCHAR", "FALSE")],
    ]
    schema = conn.introspect_schema()
    assert "bkpf" in schema["tables"]

    mock_cur.execute.side_effect = RuntimeError("Introspection error")
    with pytest.raises(
        IntrospectionError, match="Failed to introspect SAP HANA schema"
    ):
        conn.introspect_schema()


# ============================================================================
# 12. OceanBase Connector Tests
# ============================================================================


def test_oceanbase_connector_lifecycle():
    conn = OceanBaseConnector(
        host="ob.cluster", port=2881, tenant="sys", user="root", database="test"
    )
    assert conn.dialect_name == "oceanbase"
    assert conn.tenant == "sys"

    # Driver missing
    with (
        patch.dict(
            sys.modules, {"pyoceanbase": None, "pymysql": None, "MySQLdb": None}
        ),
        pytest.raises(DriverNotInstalledError, match="pyoceanbase"),
    ):
        conn.connect()

    # Connection failure
    mock_driver = MagicMock()
    mock_driver.__name__ = "pymysql"
    mock_driver.connect.side_effect = RuntimeError("Tenant resource pool exhausted")
    with (
        patch.dict(sys.modules, {"pymysql": mock_driver}),
        pytest.raises(ConnectionFailedError, match="Failed to connect to OceanBase"),
    ):
        conn.connect()

    # Connection success and cached
    mock_conn = MagicMock()
    mock_driver.connect.side_effect = None
    mock_driver.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"pymysql": mock_driver}):
        assert conn.connect() is mock_conn
        assert conn.connect() is mock_conn

    # User already has @ in username branch & non-pymysql branch
    conn_at = OceanBaseConnector(user="root@sys", tenant="sys")
    mock_non_pymysql = MagicMock()
    mock_non_pymysql.__name__ = "MySQLdb"
    mock_non_pymysql.connect.return_value = mock_conn
    with patch.dict(
        sys.modules, {"pyoceanbase": None, "pymysql": None, "MySQLdb": mock_non_pymysql}
    ):
        assert conn_at.connect() is mock_conn

    # apply_statement_timeout
    mock_cur = MagicMock()
    conn.apply_statement_timeout(mock_cur, 2500)
    mock_cur.execute.assert_called_with("SET ob_query_timeout = 2500000;")

    # test_connection
    conn._cursor = mock_cur
    info = conn.test_connection()
    assert info["engine_version"] == "OceanBase Enterprise Distributed Database"
    assert info["tenant"] == "sys"

    # introspect_schema
    mock_cur.fetchall.side_effect = [
        [("accounts",)],
        [("accounts", "acc_id", "int", "NO"), ("accounts", "user_id", "int", "YES")],
        [],
    ]
    schema = conn.introspect_schema()
    assert "accounts" in schema["tables"]
    assert schema["tables"]["accounts"]["has_user_id"] is True

    mock_cur.execute.side_effect = RuntimeError("Introspection error")
    with pytest.raises(
        IntrospectionError, match="Failed to introspect OceanBase schema"
    ):
        conn.introspect_schema()


# ============================================================================
# 13. ScyllaDB & Apache Cassandra Connector Tests
# ============================================================================


def test_scylladb_connector_lifecycle():
    conn = ScyllaDBConnector(
        contact_points=["10.0.0.1", "10.0.0.2"], port=9042, keyspace="system_auth"
    )
    assert conn.dialect_name == "scylladb"
    assert conn.keyspace == "system_auth"
    assert conn.schema_name == "system_auth"
    assert CassandraConnector is ScyllaDBConnector

    # Driver missing
    with (
        patch.dict(sys.modules, {"cassandra": None, "cassandra.cluster": None}),
        pytest.raises(DriverNotInstalledError, match="cassandra-driver"),
    ):
        conn.connect()

    # Connection failure
    mock_driver = MagicMock()
    mock_cluster_cls = MagicMock()
    mock_driver.Cluster = mock_cluster_cls
    mock_cluster_cls.side_effect = RuntimeError("No hosts available")
    with (
        patch.dict(sys.modules, {"cassandra.cluster": mock_driver}),
        pytest.raises(
            ConnectionFailedError, match="Failed to connect to ScyllaDB cluster"
        ),
    ):
        conn.connect()

    # Connection success and cached
    mock_cluster_inst = MagicMock()
    mock_session = MagicMock()
    mock_cluster_cls.side_effect = None
    mock_cluster_cls.return_value = mock_cluster_inst
    mock_cluster_inst.connect.return_value = mock_session
    with patch.dict(sys.modules, {"cassandra.cluster": mock_driver}):
        assert conn.connect() is mock_session
        assert conn.connect() is mock_session

    # Alternative cluster lookup branch (cluster.Cluster)
    conn_alt = ScyllaDBConnector()
    mock_driver_alt = MagicMock(spec=["cluster"])
    mock_submodule = MagicMock()
    mock_driver_alt.cluster = mock_submodule
    mock_submodule.Cluster.return_value = mock_cluster_inst
    with patch.dict(sys.modules, {"cassandra.cluster": mock_driver_alt}):
        assert conn_alt.connect() is mock_session

    # test_connection
    mock_cur = MagicMock()
    conn._cursor = mock_cur
    info = conn.test_connection()
    assert info["engine_version"] == "ScyllaDB / Apache Cassandra"
    assert info["keyspace"] == "system_auth"

    # get_cursor with regular cursor and adapter
    conn._cursor = None
    # If session has cursor():
    mock_session.cursor = MagicMock(return_value=mock_cur)
    with conn.get_cursor() as cur:
        assert cur is mock_cur

    # If cursor does not have close():
    mock_cur_noclose = MagicMock()
    del mock_cur_noclose.close
    mock_session.cursor = MagicMock(return_value=mock_cur_noclose)
    with conn.get_cursor() as cur:
        assert cur is mock_cur_noclose

    # If session does not have cursor():
    del mock_session.cursor
    with conn.get_cursor() as cur:
        assert isinstance(cur, _ScyllaCursorAdapter)

    # introspect_schema
    mock_session.execute.side_effect = [
        [("roles",)],
        [("roles", "role", "text", "partition_key")],
    ]
    schema = conn.introspect_schema()
    assert "roles" in schema["tables"]
    assert schema["tables"]["roles"]["columns"][0]["is_primary"] is True

    mock_session.execute.side_effect = RuntimeError("CQL schema error")
    with pytest.raises(
        IntrospectionError, match="Failed to introspect ScyllaDB keyspace"
    ):
        conn.introspect_schema()


def test_scylla_cursor_adapter_execution():
    mock_session = MagicMock()
    adapter = _ScyllaCursorAdapter(mock_session)

    # Case 1: result_set with column_names and all() returning dict-like rows with .values()
    class MockRowDict:
        def __init__(self, d: dict[str, Any]):
            self._d = d

        def values(self):
            return self._d.values()

    mock_result_set = MagicMock()
    mock_result_set.column_names = ["col1", "col2"]
    del mock_result_set.description
    mock_result_set.all.return_value = [MockRowDict({"col1": "v1", "col2": "v2"})]
    mock_session.execute.return_value = mock_result_set

    adapter.execute("SELECT col1, col2 FROM tbl WHERE id = %s;", [10])
    assert adapter.description == [("col1",), ("col2",)]
    row = adapter.fetchone()
    assert row == ["v1", "v2"]
    assert adapter.fetchone() is None

    # Case 2: result_set with description and fetchall() returning standard tuples
    mock_result_set2 = MagicMock()
    del mock_result_set2.column_names
    del mock_result_set2.all
    mock_result_set2.description = [("a",), ("b",)]
    mock_result_set2.fetchall.return_value = [(1, 2), (3, 4)]
    mock_session.execute.return_value = mock_result_set2

    adapter.execute("SELECT * FROM tbl")
    all_rows = adapter.fetchall()
    assert all_rows == [[1, 2], [3, 4]]
    assert adapter.fetchall() == []

    # Case 3: result_set is None
    mock_session.execute.return_value = None
    adapter.execute("SELECT 1")
    assert adapter.description is None
    assert adapter.fetchall() == []

    # Case 4: result_set is a list or tuple directly
    mock_session.execute.return_value = [(5, 6)]
    adapter.execute("SELECT 5, 6")
    assert adapter.fetchall() == [[5, 6]]

    # Case 5: result_set is an iterator (hits else: rows = list(result_set) if result_set is not None else [])
    mock_session.execute.return_value = iter([(7, 8)])
    adapter.execute("SELECT 7, 8")
    assert adapter.fetchall() == [[7, 8]]

    # Case 6: session without execute
    no_exec_adapter = _ScyllaCursorAdapter(object())
    no_exec_adapter.execute("SELECT 1")
    assert no_exec_adapter.fetchall() == []

    adapter.close()


# ============================================================================
# 14. Standalone Introspection Protocols Tests
# ============================================================================


def test_introspect_cratedb_protocol():
    mock_cur = MagicMock()
    mock_cur.fetchall.side_effect = [
        [("t1",), ("t2",)],
        [
            ("t1", "id", "integer", "NO"),
            ("t1", "user_id", "integer", "YES"),
            ("t2", "name", "text", "YES"),
        ],
    ]
    res = introspect_cratedb(mock_cur, schema_name="doc")
    assert "t1" in res["tables"]
    assert "t2" in res["tables"]
    assert res["tables"]["t1"]["has_user_id"] is True
    assert res["tables"]["t2"]["has_user_id"] is False

    mock_cur.execute.side_effect = RuntimeError("Catalog error")
    with pytest.raises(IntrospectionError, match="Failed to introspect CrateDB schema"):
        introspect_cratedb(mock_cur)


def test_introspect_druid_protocol():
    mock_cur = MagicMock()
    mock_cur.fetchall.side_effect = [
        [("wiki",)],
        [
            ("wiki", "__time", "TIMESTAMP", "NO"),
            ("wiki", "user_id", "VARCHAR", "YES"),
        ],
    ]
    res = introspect_druid(mock_cur, schema_name="druid")
    assert "wiki" in res["tables"]
    assert res["tables"]["wiki"]["columns"][0]["is_primary"] is True
    assert res["tables"]["wiki"]["has_user_id"] is True

    mock_cur.execute.side_effect = RuntimeError("Druid error")
    with pytest.raises(
        IntrospectionError, match="Failed to introspect Apache Druid schema"
    ):
        introspect_druid(mock_cur)


def test_introspect_saphana_protocol():
    mock_cur = MagicMock()
    # Path 1: Primary SYS.TABLES succeeds
    mock_cur.fetchall.side_effect = [
        [("T_PRIMARY",)],
        [
            ("T_PRIMARY", "ID", "INTEGER", "FALSE"),
            ("T_PRIMARY", "USER_ID", "VARCHAR", "TRUE"),
        ],
    ]
    res = introspect_saphana(mock_cur, schema_name="SYSTEM")
    assert "t_primary" in res["tables"]
    assert res["tables"]["t_primary"]["has_user_id"] is True

    # Path 2: SYS.TABLES raises Exception, fallback to information_schema succeeds
    mock_cur.execute.side_effect = [
        RuntimeError("SYS catalog disabled"),
        None,
        None,
    ]
    mock_cur.fetchall.side_effect = [
        [("t_fallback",)],
        [("t_fallback", "code", "varchar", "YES")],
    ]
    res_fallback = introspect_saphana(mock_cur, schema_name="public")
    assert "t_fallback" in res_fallback["tables"]

    # Path 3: Total failure raises IntrospectionError
    mock_cur.execute.side_effect = RuntimeError("Fatal connection lost")
    with pytest.raises(
        IntrospectionError, match="Failed to introspect SAP HANA schema"
    ):
        introspect_saphana(mock_cur)


def test_introspect_scylladb_protocol():
    # Test with session having cursor()
    mock_session = MagicMock()
    mock_cur = MagicMock()
    mock_session.cursor.return_value = mock_cur
    mock_cur.fetchall.side_effect = [
        [("users",), ("keys",)],
        [
            ("users", "user_id", "uuid", "partition_key"),
            ("users", "email", "text", "regular"),
            ("keys", "id", "int", "clustering"),
        ],
    ]
    res = introspect_scylladb(mock_session, keyspace="my_ks")
    assert "users" in res["tables"]
    assert res["tables"]["users"]["columns"][0]["is_primary"] is True
    assert res["tables"]["users"]["has_user_id"] is True
    assert res["tables"]["keys"]["columns"][0]["is_primary"] is True

    # Test with direct cursor (without .cursor method)
    mock_direct_cur = MagicMock()
    del mock_direct_cur.cursor
    mock_direct_cur.fetchall.side_effect = [
        [("tbl2",)],
        [("tbl2", "val", "text", "regular")],
    ]
    res_direct = introspect_scylladb(mock_direct_cur, keyspace="my_ks")
    assert "tbl2" in res_direct["tables"]
    assert res_direct["tables"]["tbl2"]["columns"][0]["is_primary"] is False
    assert res_direct["tables"]["tbl2"]["has_user_id"] is False

    # Error path
    mock_direct_cur.execute.side_effect = RuntimeError("CQL query error")
    with pytest.raises(
        IntrospectionError, match="Failed to introspect ScyllaDB keyspace"
    ):
        introspect_scylladb(mock_direct_cur)


def test_influx_cursor_adapter():
    # 1. PyArrow table mock with column_names and to_pylist()
    mock_arrow_table = MagicMock()
    mock_arrow_table.column_names = ["time", "val"]
    mock_arrow_table.to_pylist.return_value = [{"time": "2026-01-01", "val": 42.5}]
    mock_client = MagicMock()
    mock_client.query.return_value = mock_arrow_table

    adapter = _InfluxCursorAdapter(mock_client)
    adapter.execute("SELECT * FROM m;")
    assert adapter.description == [("time",), ("val",)]
    row = adapter.fetchone()
    assert row == ["2026-01-01", 42.5]
    assert adapter.fetchone() is None
    assert adapter.fetchall() == []

    # 2. fetchall client result
    mock_res_cur = MagicMock()
    mock_res_cur.description = [("x",)]
    mock_res_cur.fetchall.return_value = [[1], [2]]
    del mock_res_cur.column_names
    del mock_res_cur.to_pylist
    mock_client.query.return_value = mock_res_cur

    adapter = _InfluxCursorAdapter(mock_client)
    adapter.execute("SELECT x FROM m;")
    assert adapter.fetchall() == [[1], [2]]

    # 3. list of dicts / tuples / scalar results
    mock_client.query.return_value = [{"a": 1}, (2, 3), 4]
    adapter = _InfluxCursorAdapter(mock_client)
    adapter.execute("SELECT * FROM m;")
    assert adapter.fetchall() == [[1], [2, 3], [4]]

    # 4. other query return type (e.g. object without columns)
    mock_client.query.return_value = object()
    adapter = _InfluxCursorAdapter(mock_client)
    adapter.execute("SELECT 1;")
    assert adapter.fetchall() == []

    # 5. Client with execute method
    mock_exec_client = MagicMock()
    del mock_exec_client.query
    mock_exec_client.description = [("id",)]
    mock_exec_client.fetchall.return_value = [[10]]
    adapter = _InfluxCursorAdapter(mock_exec_client)
    adapter.execute("SELECT id FROM m;", [1])
    mock_exec_client.execute.assert_called_with("SELECT id FROM m;", [1])
    assert adapter.fetchall() == [[10]]

    # execute without params
    adapter.execute("SELECT 1;")
    mock_exec_client.execute.assert_called_with("SELECT 1;")

    # execute without fetchall method on client
    mock_exec_no_fetchall = MagicMock()
    del mock_exec_no_fetchall.query
    del mock_exec_no_fetchall.fetchall
    mock_exec_no_fetchall.description = [("id",)]
    adapter_no_fetch = _InfluxCursorAdapter(mock_exec_no_fetchall)
    adapter_no_fetch.execute("INSERT INTO m VALUES (1);")
    assert adapter_no_fetch.fetchall() == []

    # Client with neither query nor execute
    adapter_empty = _InfluxCursorAdapter(object())
    adapter_empty.execute("SELECT 1;")
    assert adapter_empty.fetchall() == []

    adapter.close()

    # 6. Test InfluxDBConnector.get_cursor yields _InfluxCursorAdapter when conn has no .cursor
    mock_influx_client = MagicMock()
    del mock_influx_client.cursor
    conn = InfluxDBConnector(connection=mock_influx_client)
    with conn.get_cursor() as cur:
        assert isinstance(cur, _InfluxCursorAdapter)

    # 7. Test InfluxDBConnector.get_cursor when conn has .cursor with close()
    mock_conn_cur = MagicMock()
    mock_cur_inst = MagicMock()
    mock_conn_cur.cursor.return_value = mock_cur_inst
    conn_cur = InfluxDBConnector(connection=mock_conn_cur)
    with conn_cur.get_cursor() as cur:
        assert cur is mock_cur_inst
    mock_cur_inst.close.assert_called_once()

    # 8. Test InfluxDBConnector.get_cursor when conn has .cursor without close()
    mock_conn_cur2 = MagicMock()
    mock_cur_inst2 = MagicMock()
    del mock_cur_inst2.close
    mock_conn_cur2.cursor.return_value = mock_cur_inst2
    conn_cur2 = InfluxDBConnector(connection=mock_conn_cur2)
    with conn_cur2.get_cursor() as cur:
        assert cur is mock_cur_inst2


def test_scylla_cursor_adapter_edge_cases():
    mock_session = MagicMock()
    mock_result = MagicMock()
    del mock_result.column_names
    del mock_result.description
    del mock_result.all
    del mock_result.fetchall
    # scalar rows from query like SELECT count(*)
    mock_result.__iter__.return_value = [42, 99]
    mock_session.execute.return_value = mock_result

    adapter = _ScyllaCursorAdapter(mock_session)
    # Test query with trailing semicolon and newlines/spaces
    adapter.execute("SELECT count(*) FROM users;\n  ")
    # Verify semicolon and whitespace were stripped
    mock_session.execute.assert_called_with("SELECT count(*) FROM users")
    assert adapter.fetchall() == [[42], [99]]


def test_connector_inspect_methods_sync():
    conn = PrestoDBConnector()
    with patch.object(conn, "introspect_schema") as mock_intro:
        mock_intro.return_value = {
            "tables": {
                "users": {
                    "columns": [
                        {"name": "id", "is_primary": True},
                        {"name": "email", "is_primary": False},
                    ]
                },
                "orders": {
                    "columns": [
                        {"name": "order_id", "is_primary": True},
                        {"name": "user_id", "is_primary": False},
                    ]
                },
            },
            "foreign_keys": [
                {
                    "table": "orders",
                    "column": "user_id",
                    "foreign_table": "users",
                    "foreign_column": "id",
                }
            ],
        }

        # inspect_tables
        assert conn.inspect_tables() == ["orders", "users"]

        # inspect_columns
        cols = conn.inspect_columns("users")
        assert len(cols) == 2
        assert conn.inspect_columns("missing_table") == []

        # inspect_primary_keys
        assert conn.inspect_primary_keys("users") == ["id"]
        assert conn.inspect_primary_keys("orders") == ["order_id"]

        # inspect_foreign_keys
        fks_all = conn.inspect_foreign_keys()
        assert len(fks_all) == 1
        assert conn.inspect_foreign_keys("orders") == fks_all
        assert conn.inspect_foreign_keys("users") == []


def test_connector_inspect_methods_async():
    async def _test():
        conn = AsyncPrestoDBConnector()
        # Default fallback introspection
        snap = await conn.introspect_schema()
        assert snap["tables"] == {}

        # Mocked introspect_schema
        with patch.object(conn, "introspect_schema") as mock_intro:
            mock_intro.return_value = {
                "tables": {
                    "orders": {
                        "columns": [
                            {"name": "id", "is_primary": True},
                            {"name": "user_id", "is_primary": False},
                        ]
                    }
                },
                "foreign_keys": [
                    {
                        "table": "orders",
                        "column": "user_id",
                        "foreign_table": "users",
                        "foreign_column": "id",
                    }
                ],
            }

            tables = await conn.inspect_tables()
            assert tables == ["orders"]

            cols = await conn.inspect_columns("orders")
            assert len(cols) == 2
            assert await conn.inspect_columns("missing") == []
            assert await conn.inspect_primary_keys("orders") == ["id"]

            fks = await conn.inspect_foreign_keys("orders")
            assert len(fks) == 1
            assert await conn.inspect_foreign_keys() == fks
            assert await conn.inspect_foreign_keys("users") == []

    asyncio.run(_test())


def test_dialect_inspection_queries():
    base = BaseDialect()
    sql, params = base.inspect_tables_query("public")
    assert "information_schema.tables" in sql
    assert params == ["public"]

    sql_col, params_col = base.inspect_columns_query("public", "users")
    assert "information_schema.columns" in sql_col
    assert params_col == ["public", "users"]

    sql_col_all, params_col_all = base.inspect_columns_query("public")
    assert "information_schema.columns" in sql_col_all
    assert params_col_all == ["public"]

    sql_pk, params_pk = base.inspect_primary_keys_query("public", "users")
    assert "PRIMARY KEY" in sql_pk
    assert params_pk == ["public", "users"]

    sql_pk_all, params_pk_all = base.inspect_primary_keys_query("public")
    assert "PRIMARY KEY" in sql_pk_all
    assert params_pk_all == ["public"]

    sql_fk, params_fk = base.inspect_foreign_keys_query("public", "users")
    assert "FOREIGN KEY" in sql_fk
    assert params_fk == ["public", "users"]

    sql_fk_all, params_fk_all = base.inspect_foreign_keys_query("public")
    assert "FOREIGN KEY" in sql_fk_all
    assert params_fk_all == ["public"]

    # SQLite
    sqlite = SQLiteDialect()
    assert "sqlite_master" in sqlite.inspect_tables_query()[0]
    assert "PRAGMA table_info" in sqlite.inspect_columns_query("main", "users")[0]
    assert "PRAGMA table_info" in sqlite.inspect_primary_keys_query("main", "users")[0]
    assert (
        "PRAGMA foreign_key_list"
        in sqlite.inspect_foreign_keys_query("main", "users")[0]
    )

    # ClickHouse
    ch = ClickHouseDialect()
    assert "system.tables" in ch.inspect_tables_query("default")[0]
    assert "system.columns" in ch.inspect_columns_query("default", "events")[0]
    assert "system.columns" in ch.inspect_columns_query("default")[0]

    # Oracle
    ora = OracleDialect()
    assert "all_tables" in ora.inspect_tables_query("HR")[0]

    # Druid
    druid = DruidDialect()
    assert "INFORMATION_SCHEMA.TABLES" in druid.inspect_tables_query()[0]
    assert (
        "INFORMATION_SCHEMA.COLUMNS" in druid.inspect_columns_query("druid", "wiki")[0]
    )
    assert "INFORMATION_SCHEMA.COLUMNS" in druid.inspect_columns_query("druid")[0]

    # CrateDB
    crate = CrateDBDialect()
    assert "information_schema.tables" in crate.inspect_tables_query()[0]
    assert "information_schema.columns" in crate.inspect_columns_query("doc", "t1")[0]
    assert "information_schema.columns" in crate.inspect_columns_query("doc")[0]

    # SAP HANA
    hana = SAPHANADialect()
    assert "SYS.TABLES" in hana.inspect_tables_query("SYSTEM")[0]
    assert "SYS.TABLE_COLUMNS" in hana.inspect_columns_query("SYSTEM", "T1")[0]
    assert "SYS.TABLE_COLUMNS" in hana.inspect_columns_query("SYSTEM")[0]

    # ScyllaDB
    scylla = ScyllaDBDialect()
    assert "system_schema.tables" in scylla.inspect_tables_query("system")[0]
    assert "system_schema.columns" in scylla.inspect_columns_query("system", "users")[0]
    assert "system_schema.columns" in scylla.inspect_columns_query("system")[0]
    assert "partition_key" in scylla.inspect_primary_keys_query("system", "users")[0]
    assert "partition_key" in scylla.inspect_primary_keys_query("system")[0]
    assert scylla.inspect_foreign_keys_query("system", "users") == ("", [])
