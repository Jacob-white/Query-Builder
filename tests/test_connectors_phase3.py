"""
Comprehensive Unit Tests for Phase 3 Connectors: Real-Time Streaming SQL Gateways.
==================================================================================
Verifies 100% statement, function, and branch coverage across:
- ksqlDB: KsqlDBConnector, AsyncKsqlDBConnector, _KsqlDBCursorAdapter, KsqlDBDialect, introspect_ksqldb
- Apache Flink SQL: FlinkSQLConnector, AsyncFlinkSQLConnector, FlinkConnector, AsyncFlinkConnector, _FlinkCursorAdapter, FlinkDialect, introspect_flink
- Apache Pulsar SQL: PulsarSQLConnector, AsyncPulsarSQLConnector, PulsarConnector, AsyncPulsarConnector, _PulsarCursorAdapter, PulsarDialect, introspect_pulsar
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock, patch

import pytest

from query_builder.connectors import (
    AsyncFlinkConnector,
    AsyncFlinkSQLConnector,
    AsyncKsqlDBConnector,
    AsyncPulsarConnector,
    AsyncPulsarSQLConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    FlinkConnector,
    FlinkSQLConnector,
    IntrospectionError,
    KsqlDBConnector,
    PulsarConnector,
    PulsarSQLConnector,
    get_connector,
    introspect_flink,
    introspect_ksqldb,
    introspect_pulsar,
    list_connectors,
)
from query_builder.connectors.flink import _FlinkCursorAdapter
from query_builder.connectors.ksqldb import _KsqlDBCursorAdapter
from query_builder.connectors.pulsar import _PulsarCursorAdapter
from query_builder.dialects import (
    FlinkDialect,
    KsqlDBDialect,
    PulsarDialect,
    get_dialect,
)

# ============================================================================
# 1. Dialect Tests
# ============================================================================


def test_phase3_dialects():
    # ksqlDB
    kd = get_dialect("ksqldb")
    assert isinstance(kd, KsqlDBDialect)
    assert kd.name == "ksqldb"
    assert get_dialect("ksql").name == "ksqldb"
    assert kd.quote_identifier("table.col") == "`table`.`col`"
    assert kd.format_ilike("col") == "LCASE(col) LIKE LCASE(%s)"
    assert kd.format_limit_offset(10, 0) == ("LIMIT %s", [10])
    assert kd.inspect_tables_query()[0] == "SHOW TABLES;"
    assert kd.inspect_columns_query(table_name="Users")[0] == "DESCRIBE Users;"
    assert kd.inspect_columns_query()[0] == "SHOW STREAMS;"
    assert kd.inspect_primary_keys_query() == ("", [])
    assert kd.inspect_foreign_keys_query() == ("", [])

    # Flink SQL
    fd = get_dialect("flink")
    assert isinstance(fd, FlinkDialect)
    assert fd.name == "flink"
    assert get_dialect("flink_sql").name == "flink"
    assert get_dialect("apache_flink").name == "flink"
    assert fd.quote_identifier("db.table") == "`db`.`table`"
    assert fd.format_ilike("col") == "LOWER(col) LIKE LOWER(%s)"
    assert fd.format_limit_offset(10, 5) == ("LIMIT %s OFFSET %s", [10, 5])
    assert fd.inspect_tables_query()[0] == "SHOW TABLES;"
    assert fd.inspect_columns_query(table_name="orders")[0] == "DESCRIBE `orders`;"
    assert fd.inspect_columns_query()[0] == "SHOW TABLES;"
    assert fd.inspect_primary_keys_query() == ("", [])
    assert fd.inspect_foreign_keys_query() == ("", [])

    # Pulsar SQL
    pud = get_dialect("pulsar")
    assert isinstance(pud, PulsarDialect)
    assert pud.name == "pulsar"
    assert get_dialect("pulsar_sql").name == "pulsar"
    assert get_dialect("apache_pulsar").name == "pulsar"
    assert pud.format_ilike("col") == "LOWER(col) LIKE LOWER(%s)"
    assert pud.format_limit_offset(10, 5) == ("LIMIT %s OFFSET %s", [10, 5])
    assert "SHOW TABLES FROM" in pud.inspect_tables_query()[0]
    assert "DESCRIBE" in pud.inspect_columns_query(table_name="events")[0]
    assert "SHOW TABLES FROM" in pud.inspect_columns_query()[0]
    assert pud.inspect_primary_keys_query() == ("", [])
    assert pud.inspect_foreign_keys_query() == ("", [])


# ============================================================================
# 2. Registry Tests
# ============================================================================


def test_phase3_registry():
    all_conns = list_connectors()
    for name in ["ksqldb", "flink", "pulsar"]:
        assert name in all_conns
        assert f"async_{name}" in all_conns

    assert isinstance(get_connector("ksql"), KsqlDBConnector)
    assert isinstance(get_connector("flink_sql"), FlinkSQLConnector)
    assert isinstance(get_connector("apache_flink"), FlinkSQLConnector)
    assert isinstance(get_connector("pulsar_sql"), PulsarSQLConnector)
    assert isinstance(get_connector("apache_pulsar"), PulsarSQLConnector)

    assert FlinkConnector is FlinkSQLConnector
    assert AsyncFlinkConnector is AsyncFlinkSQLConnector
    assert PulsarConnector is PulsarSQLConnector
    assert AsyncPulsarConnector is AsyncPulsarSQLConnector


# ============================================================================
# 3. Parametric Cursor Adapter Tests (All 3 Adapters)
# ============================================================================


@pytest.mark.parametrize(
    "adapter_cls",
    [
        _KsqlDBCursorAdapter,
        _FlinkCursorAdapter,
        _PulsarCursorAdapter,
    ],
)
def test_cursor_adapters_phase3_comprehensive(adapter_cls):
    # Branch 1: Connection with cursor() method having close
    mock_cursor = MagicMock()
    mock_cursor.description = [("id", 1), ("name", 2)]
    mock_cursor.fetchall.return_value = [[1, "Alice"], [2, "Bob"], [3, "Charlie"]]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    adapter = adapter_cls(mock_conn)
    adapter.execute("SELECT * FROM test;", [10])
    mock_cursor.execute.assert_called_with("SELECT * FROM test", [10])
    assert adapter.description == [("id", 1), ("name", 2)]

    # fetchone, fetchmany, fetchall
    row1 = adapter.fetchone()
    assert row1 == [1, "Alice"]
    many = adapter.fetchmany(1)
    assert many == [[2, "Bob"]]
    rest = adapter.fetchall()
    assert rest == [[3, "Charlie"]]
    assert adapter.fetchone() is None
    assert adapter.fetchmany(5) == []

    adapter.close()
    assert adapter.fetchall() == []

    # execute without params
    adapter.execute("SELECT * FROM test;")
    mock_cursor.execute.assert_called_with("SELECT * FROM test")

    # Connection with cursor() without close method
    mock_cur_noclose = MagicMock(spec=["execute", "fetchall", "description"])
    mock_cur_noclose.description = [("x",)]
    mock_cur_noclose.fetchall.return_value = [[1]]
    conn_noclose = MagicMock(spec=["cursor"])
    conn_noclose.cursor.return_value = mock_cur_noclose
    adapter_nc = adapter_cls(conn_noclose)
    adapter_nc.execute("SELECT 1")
    assert adapter_nc.fetchall() == [[1]]

    # Branch 2: Connection with execute() returning result object with fetchall
    mock_res = MagicMock(spec=["description", "fetchall"])
    mock_res.description = [("val", 0)]
    mock_res.fetchall.return_value = [[42], [43]]
    conn_with_exec = MagicMock(spec=["execute"])
    conn_with_exec.execute.return_value = mock_res

    adapter2 = adapter_cls(conn_with_exec)
    adapter2.execute("SELECT val FROM test", [1])
    assert adapter2.description == [("val", 0)]
    assert adapter2.fetchall() == [[42], [43]]

    # Connection with execute() returning list/tuple
    conn_with_list = MagicMock(spec=["execute"])
    conn_with_list.execute.return_value = [[100], [200]]
    adapter3 = adapter_cls(conn_with_list)
    adapter3.execute("SELECT val FROM test")
    assert adapter3.fetchall() == [[100], [200]]

    # Connection with execute() returning scalar
    conn_with_scalar = MagicMock(spec=["execute"])
    conn_with_scalar.execute.return_value = 1
    adapter4 = adapter_cls(conn_with_scalar)
    adapter4.execute("SELECT 1")
    adapter4.fetchall()

    # Branch 3: Bare connection without cursor or execute
    bare_conn = object()
    adapter5 = adapter_cls(bare_conn)
    adapter5.execute("SELECT 1")
    assert adapter5.fetchone() is None
    assert adapter5.fetchall() == []


# ============================================================================
# 4. Specialized Adapter Branch Coverage
# ============================================================================


def test_ksqldb_adapter_specialized():
    # post with DDL/DML statementText response
    mock_session = MagicMock(spec=["post", "close"])
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"statementText": "CREATE TABLE", "status": "SUCCESS"}
    ]
    mock_session.post.return_value = mock_resp

    adapter = _KsqlDBCursorAdapter(mock_session)
    adapter.execute("CREATE TABLE users AS SELECT * FROM t;")
    assert adapter.description == [("statementText",), ("status",)]
    assert adapter.fetchone() == ["CREATE TABLE", "SUCCESS"]

    # post with pull query header & row response including ignored item
    mock_resp2 = MagicMock()
    mock_resp2.json.return_value = [
        {"header": {"schema": "`id` BIGINT, `name` STRING"}},
        {"row": {"columns": [1, "Alice"]}},
        [2, "Bob"],
        "ignored_scalar",
    ]
    mock_session.post.return_value = mock_resp2
    adapter.execute("SELECT * FROM users;")
    assert adapter.description == [("id",), ("name",)]
    assert adapter.fetchall() == [[1, "Alice"], [2, "Bob"]]

    # post with empty response
    mock_resp3 = MagicMock()
    mock_resp3.json.return_value = []
    mock_session.post.return_value = mock_resp3
    adapter.execute("SELECT 1;")
    assert adapter.fetchall() == []

    # post returning non-list
    mock_resp4 = MagicMock()
    mock_resp4.json.return_value = {"error": "bad query"}
    mock_session.post.return_value = mock_resp4
    adapter.execute("SELECT 1;")
    assert adapter.fetchall() == [["ksqlDB command", "SUCCESS"]]

    # Coroutine awaiting in not-running loop (hits line 68)
    async def sync_coro_res():
        r = MagicMock()
        r.json.return_value = [{"statementText": "SYNC_OK", "status": "SUCCESS"}]
        return r

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        mock_sess_sync = MagicMock(spec=["post"])
        mock_sess_sync.post.return_value = sync_coro_res()
        adapter_sync = _KsqlDBCursorAdapter(mock_sess_sync)
        adapter_sync.execute("SHOW TABLES;")
        assert adapter_sync.fetchall() == [["SYNC_OK", "SUCCESS"]]
    finally:
        loop.close()

    # Coroutine awaiting in running loop
    async def _test_coro():
        async def coro_res():
            r = MagicMock()
            r.json.return_value = [{"statementText": "OK"}]
            return r

        mock_sess_async = MagicMock(spec=["post"])
        mock_sess_async.post.return_value = coro_res()
        adapter_coro = _KsqlDBCursorAdapter(mock_sess_async)
        adapter_coro.execute("DROP TABLE users;")
        assert adapter_coro.fetchall() == [["OK", "SUCCESS"]]

        # Coroutine exception branch
        async def bad_coro():
            raise RuntimeError("Post error")

        mock_sess_bad = MagicMock(spec=["post"])
        mock_sess_bad.post.return_value = bad_coro()
        adapter_bad = _KsqlDBCursorAdapter(mock_sess_bad)
        adapter_bad.execute("DROP TABLE users;")

    asyncio.run(_test_coro())


def test_flink_adapter_specialized():
    # conn with execute_statement returning columnInfos and data with fields
    conn = MagicMock(spec=["execute_statement"])
    conn.execute_statement.return_value = {
        "columnInfos": [{"name": "id"}, {"name": "count"}],
        "data": [{"fields": [101, 5]}, {"fields": [102, 8]}],
    }
    adapter = _FlinkCursorAdapter(conn)
    adapter.execute("SELECT id, count FROM my_table")
    assert adapter.description == [("id",), ("count",)]
    assert adapter.fetchall() == [[101, 5], [102, 8]]


# ============================================================================
# 5. Full Lifecycle Sync & Async Connector Tests (Phase 3)
# ============================================================================


def test_ksqldb_connector_lifecycle():
    # Cached connection
    existing_conn = MagicMock()
    cached_c = KsqlDBConnector(connection=existing_conn)
    assert cached_c.connect() is existing_conn

    # Missing driver
    with (
        patch.dict(sys.modules, {"httpx": None, "requests": None}),
        pytest.raises(DriverNotInstalledError),
    ):
        KsqlDBConnector().connect()

    # Connection failure
    mock_drv = MagicMock()
    mock_drv.Client.side_effect = RuntimeError("ksqlDB connect failed")
    with (
        patch.dict(sys.modules, {"httpx": mock_drv, "requests": mock_drv}),
        pytest.raises(ConnectionFailedError),
    ):
        KsqlDBConnector().connect()

    # Successful connect with Client
    mock_client = MagicMock(spec=["post", "close"])
    mock_drv.Client.side_effect = None
    mock_drv.Client.return_value = mock_client
    with patch.dict(sys.modules, {"httpx": mock_drv, "requests": mock_drv}):
        c = KsqlDBConnector()
        assert c.connect() is mock_client

        # preset cursor
        preset_cur = MagicMock()
        c_pre = KsqlDBConnector(cursor=preset_cur)
        with c_pre.get_cursor() as cur:
            assert cur is preset_cur

        # conn with cursor()
        mock_conn_cur = MagicMock()
        mock_cur = MagicMock()
        mock_conn_cur.cursor.return_value = mock_cur
        c_cur = KsqlDBConnector(connection=mock_conn_cur)
        with c_cur.get_cursor() as cur:
            assert cur is mock_cur
        mock_cur.close.assert_called_once()

        # conn with cursor() without close
        mock_conn_cur_nc = MagicMock(spec=["cursor"])
        mock_cur_nc = MagicMock(spec=["execute"])
        mock_conn_cur_nc.cursor.return_value = mock_cur_nc
        c_cur_nc = KsqlDBConnector(connection=mock_conn_cur_nc)
        with c_cur_nc.get_cursor() as cur:
            assert cur is mock_cur_nc

        # adapter fallback
        c_adapt = KsqlDBConnector(connection=MagicMock(spec=["post"]))
        with c_adapt.get_cursor() as cur:
            assert isinstance(cur, _KsqlDBCursorAdapter)

        # test_connection
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"statementText": "SHOW TABLES", "status": "SUCCESS"}
        ]
        mock_client.post.return_value = mock_resp
        res = c.test_connection()
        assert res["status"] == "healthy"

        # introspect_schema success and error
        with patch(
            "query_builder.connectors.ksqldb.introspect_ksqldb",
            return_value={"tables": {}},
        ):
            assert c.introspect_schema() == {"tables": {}}

        with (
            patch(
                "query_builder.connectors.ksqldb.introspect_ksqldb",
                side_effect=RuntimeError("ksqlDB introspect error"),
            ),
            pytest.raises(IntrospectionError),
        ):
            c.introspect_schema()

    # Driver without Client
    raw_driver = MagicMock(spec=["post"])
    with patch.dict(sys.modules, {"httpx": None, "requests": raw_driver}):
        c_raw = KsqlDBConnector()
        assert c_raw.connect() is raw_driver


def test_async_ksqldb_connector_lifecycle():
    async def _test():
        conn = AsyncKsqlDBConnector()

        # Cached connection
        mock_conn = MagicMock()
        cached_c = AsyncKsqlDBConnector(connection=mock_conn)
        assert await cached_c.connect() is mock_conn

        # Missing driver
        with (
            patch.dict(sys.modules, {"httpx": None, "requests": None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection error
        mock_drv = MagicMock()
        mock_drv.AsyncClient.side_effect = RuntimeError("ksqlDB async failed")
        with (
            patch.dict(sys.modules, {"httpx": mock_drv}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # execute_raw with cursor on conn
        mock_client = MagicMock()
        mock_cur = MagicMock()
        mock_cur.description = [("val",)]
        mock_cur.fetchall.return_value = [["res1"]]
        mock_client.cursor.return_value = mock_cur
        mock_drv.AsyncClient.side_effect = None
        mock_drv.AsyncClient.return_value = mock_client
        with patch.dict(sys.modules, {"httpx": mock_drv}):
            c_exec = AsyncKsqlDBConnector()
            cols, rows, lat = await c_exec.execute_raw("SHOW TABLES;", [1])
            assert cols == ["val"]
            assert rows == [{"val": "res1"}]
            assert lat >= 0

            # execute_raw with adapter
            client_no_cur = MagicMock(spec=["post"])
            mock_resp = MagicMock()
            mock_resp.json.return_value = [
                {"statementText": "SHOW TABLES", "status": "SUCCESS"}
            ]
            client_no_cur.post.return_value = mock_resp
            c_adapter = AsyncKsqlDBConnector(connection=client_no_cur)
            cols2, rows2, _ = await c_adapter.execute_raw("SHOW TABLES;")
            assert cols2 == ["statementText", "status"]
            assert rows2 == [{"statementText": "SHOW TABLES", "status": "SUCCESS"}]

            # test_connection
            t_res = await c_adapter.test_connection()
            assert t_res["status"] == "healthy"

            # introspect_schema success and error
            with patch(
                "query_builder.connectors.ksqldb.introspect_ksqldb",
                return_value={"tables": {}},
            ):
                assert await c_adapter.introspect_schema() == {"tables": {}}

            with (
                patch(
                    "query_builder.connectors.ksqldb.introspect_ksqldb",
                    side_effect=RuntimeError("Async ksqlDB introspect error"),
                ),
                pytest.raises(IntrospectionError),
            ):
                await c_adapter.introspect_schema()

        # Connect when driver has no AsyncClient
        raw_driver = MagicMock(spec=["post"])
        with patch.dict(sys.modules, {"httpx": raw_driver}):
            c_raw = AsyncKsqlDBConnector()
            assert await c_raw.connect() is raw_driver

    asyncio.run(_test())


def test_flink_connector_lifecycle():
    # Cached connection
    existing_conn = MagicMock()
    cached_c = FlinkSQLConnector(connection=existing_conn)
    assert cached_c.connect() is existing_conn

    # Missing driver
    with (
        patch.dict(sys.modules, {"requests": None, "httpx": None}),
        pytest.raises(DriverNotInstalledError),
    ):
        FlinkSQLConnector().connect()

    # Connection failure
    mock_drv = MagicMock()
    mock_drv.Client.side_effect = RuntimeError("Flink gateway connect failed")
    with (
        patch.dict(sys.modules, {"httpx": mock_drv, "requests": mock_drv}),
        pytest.raises(ConnectionFailedError),
    ):
        FlinkSQLConnector().connect()

    # Successful connect
    mock_client = MagicMock(spec=["execute_statement", "close"])
    mock_drv.Client.side_effect = None
    mock_drv.Client.return_value = mock_client
    with patch.dict(sys.modules, {"httpx": mock_drv, "requests": mock_drv}):
        c = FlinkSQLConnector()
        assert c.connect() is mock_client

        # preset cursor
        preset_cur = MagicMock()
        c_pre = FlinkSQLConnector(cursor=preset_cur)
        with c_pre.get_cursor() as cur:
            assert cur is preset_cur

        # conn with cursor()
        mock_conn_cur = MagicMock()
        mock_cur = MagicMock()
        mock_conn_cur.cursor.return_value = mock_cur
        c_cur = FlinkSQLConnector(connection=mock_conn_cur)
        with c_cur.get_cursor() as cur:
            assert cur is mock_cur
        mock_cur.close.assert_called_once()

        # conn with cursor() without close
        mock_conn_cur_nc = MagicMock(spec=["cursor"])
        mock_cur_nc = MagicMock(spec=["execute"])
        mock_conn_cur_nc.cursor.return_value = mock_cur_nc
        c_cur_nc = FlinkSQLConnector(connection=mock_conn_cur_nc)
        with c_cur_nc.get_cursor() as cur:
            assert cur is mock_cur_nc

        # adapter fallback
        c_adapt = FlinkSQLConnector(connection=MagicMock(spec=["execute_statement"]))
        with c_adapt.get_cursor() as cur:
            assert isinstance(cur, _FlinkCursorAdapter)

        # test_connection
        mock_client.execute_statement.return_value = {
            "columnInfos": [{"name": "col"}],
            "data": [{"fields": ["res"]}],
        }
        res = c.test_connection()
        assert res["status"] == "healthy"

        # introspect_schema success and error
        with patch(
            "query_builder.connectors.flink.introspect_flink",
            return_value={"tables": {}},
        ):
            assert c.introspect_schema() == {"tables": {}}

        with (
            patch(
                "query_builder.connectors.flink.introspect_flink",
                side_effect=RuntimeError("Flink introspect error"),
            ),
            pytest.raises(IntrospectionError),
        ):
            c.introspect_schema()

    # Driver without Client
    raw_driver = MagicMock(spec=["get"])
    with patch.dict(sys.modules, {"httpx": None, "requests": raw_driver}):
        c_raw = FlinkSQLConnector()
        assert c_raw.connect() is raw_driver


def test_async_flink_connector_lifecycle():
    async def _test():
        conn = AsyncFlinkSQLConnector()

        # Cached connection
        mock_conn = MagicMock()
        cached_c = AsyncFlinkSQLConnector(connection=mock_conn)
        assert await cached_c.connect() is mock_conn

        # Missing driver
        with (
            patch.dict(sys.modules, {"httpx": None, "requests": None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection error
        mock_drv = MagicMock()
        mock_drv.AsyncClient.side_effect = RuntimeError("Flink async failed")
        with (
            patch.dict(sys.modules, {"httpx": mock_drv}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # execute_raw with cursor on conn
        mock_client = MagicMock()
        mock_cur = MagicMock()
        mock_cur.description = [("val",)]
        mock_cur.fetchall.return_value = [[10]]
        mock_client.cursor.return_value = mock_cur
        mock_drv.AsyncClient.side_effect = None
        mock_drv.AsyncClient.return_value = mock_client
        with patch.dict(sys.modules, {"httpx": mock_drv}):
            c_exec = AsyncFlinkSQLConnector()
            cols, rows, lat = await c_exec.execute_raw("SHOW TABLES;", [1])
            assert cols == ["val"]
            assert rows == [{"val": 10}]
            assert lat >= 0

            # execute_raw with adapter
            client_no_cur = MagicMock(spec=["execute_statement"])
            client_no_cur.execute_statement.return_value = {
                "columnInfos": [{"name": "tbl"}],
                "data": [{"fields": ["orders"]}],
            }
            c_adapter = AsyncFlinkSQLConnector(connection=client_no_cur)
            cols2, rows2, _ = await c_adapter.execute_raw("SHOW TABLES;")
            assert cols2 == ["tbl"]
            assert rows2 == [{"tbl": "orders"}]

            # test_connection
            t_res = await c_adapter.test_connection()
            assert t_res["status"] == "healthy"

            # introspect_schema success and error
            with patch(
                "query_builder.connectors.flink.introspect_flink",
                return_value={"tables": {}},
            ):
                assert await c_adapter.introspect_schema() == {"tables": {}}

            with (
                patch(
                    "query_builder.connectors.flink.introspect_flink",
                    side_effect=RuntimeError("Async flink introspect error"),
                ),
                pytest.raises(IntrospectionError),
            ):
                await c_adapter.introspect_schema()

        # Connect when driver has no AsyncClient
        raw_driver = MagicMock(spec=["get"])
        with patch.dict(sys.modules, {"httpx": raw_driver}):
            c_raw = AsyncFlinkSQLConnector()
            assert await c_raw.connect() is raw_driver

    asyncio.run(_test())


def test_pulsar_connector_lifecycle():
    # Cached connection
    existing_conn = MagicMock()
    cached_c = PulsarSQLConnector(connection=existing_conn)
    assert cached_c.connect() is existing_conn

    # Missing driver
    with (
        patch.dict(
            sys.modules,
            {
                "trino.dbapi": None,
                "trino": None,
                "prestodb.dbapi": None,
                "prestodb": None,
            },
        ),
        pytest.raises(DriverNotInstalledError),
    ):
        PulsarSQLConnector().connect()

    # Connection failure
    mock_drv = MagicMock()
    mock_drv.connect.side_effect = RuntimeError("Pulsar connect fail")
    with (
        patch.dict(sys.modules, {"trino.dbapi": mock_drv}),
        pytest.raises(ConnectionFailedError),
    ):
        PulsarSQLConnector().connect()

    # Successful connect
    mock_conn = MagicMock(spec=["cursor", "close"])
    mock_drv.connect.side_effect = None
    mock_drv.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"trino.dbapi": mock_drv}):
        c = PulsarSQLConnector()
        assert c.connect() is mock_conn

        # preset cursor
        preset_cur = MagicMock()
        c_pre = PulsarSQLConnector(cursor=preset_cur)
        with c_pre.get_cursor() as cur:
            assert cur is preset_cur

        # conn with cursor()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        with c.get_cursor() as cur:
            assert cur is mock_cur
        mock_cur.close.assert_called_once()

        # cursor without close method
        mock_cur_noclose = MagicMock(spec=["execute"])
        mock_conn_nc = MagicMock(spec=["cursor"])
        mock_conn_nc.cursor.return_value = mock_cur_noclose
        c_nc = PulsarSQLConnector(connection=mock_conn_nc)
        with c_nc.get_cursor() as cur:
            assert cur is mock_cur_noclose

        # adapter fallback
        c_adapt = PulsarSQLConnector(connection=MagicMock(spec=["execute"]))
        with c_adapt.get_cursor() as cur:
            assert isinstance(cur, _PulsarCursorAdapter)

        # test_connection
        mock_cur.fetchone.return_value = [1]
        res = c.test_connection()
        assert res["status"] == "healthy"

        # introspect_schema success and error
        with patch(
            "query_builder.connectors.pulsar.introspect_pulsar",
            return_value={"tables": {}},
        ):
            assert c.introspect_schema() == {"tables": {}}

        with (
            patch(
                "query_builder.connectors.pulsar.introspect_pulsar",
                side_effect=RuntimeError("Pulsar introspect error"),
            ),
            pytest.raises(IntrospectionError),
        ):
            c.introspect_schema()


def test_async_pulsar_connector_lifecycle():
    async def _test():
        conn = AsyncPulsarSQLConnector()

        # Cached connection
        mock_conn = MagicMock()
        cached_c = AsyncPulsarSQLConnector(connection=mock_conn)
        assert await cached_c.connect() is mock_conn

        # Missing driver
        with (
            patch.dict(
                sys.modules,
                {
                    "trino.dbapi": None,
                    "trino": None,
                    "prestodb.dbapi": None,
                    "prestodb": None,
                },
            ),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection error
        mock_drv = MagicMock()
        mock_drv.connect.side_effect = RuntimeError("Pulsar async fail")
        with (
            patch.dict(sys.modules, {"trino.dbapi": mock_drv}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # execute_raw with cursor on conn
        mock_conn_live = MagicMock()
        mock_cur = MagicMock()
        mock_cur.description = [("val",)]
        mock_cur.fetchall.return_value = [[42]]
        mock_conn_live.cursor.return_value = mock_cur
        mock_drv.connect.side_effect = None
        mock_drv.connect.return_value = mock_conn_live
        with patch.dict(sys.modules, {"trino.dbapi": mock_drv}):
            c_exec = AsyncPulsarSQLConnector()
            cols, rows, lat = await c_exec.execute_raw("SELECT 42", [1])
            assert cols == ["val"]
            assert rows == [{"val": 42}]
            assert lat >= 0

            # execute_raw with adapter
            conn_no_cur = MagicMock(spec=["execute"])
            res_obj = MagicMock(spec=["description", "fetchall"])
            res_obj.description = [("a",)]
            res_obj.fetchall.return_value = [[99]]
            conn_no_cur.execute.return_value = res_obj
            c_adapter = AsyncPulsarSQLConnector(connection=conn_no_cur)
            cols2, rows2, _ = await c_adapter.execute_raw("SELECT 99")
            assert cols2 == ["a"]
            assert rows2 == [{"a": 99}]

            # test_connection
            mock_cur.fetchall.return_value = [[1]]
            t_res = await c_exec.test_connection()
            assert t_res["status"] == "healthy"

            # introspect_schema success and error
            with patch(
                "query_builder.connectors.pulsar.introspect_pulsar",
                return_value={"tables": {}},
            ):
                assert await c_exec.introspect_schema() == {"tables": {}}

            with (
                patch(
                    "query_builder.connectors.pulsar.introspect_pulsar",
                    side_effect=RuntimeError("Async pulsar introspect error"),
                ),
                pytest.raises(IntrospectionError),
            ):
                await c_exec.introspect_schema()

    asyncio.run(_test())


# ============================================================================
# 6. Introspection Tests (Phase 3)
# ============================================================================


def test_introspect_ksqldb_branches():
    mock_cur = MagicMock()
    mock_cur.execute.side_effect = [
        None,  # SHOW TABLES;
        None,  # SHOW STREAMS;
    ]
    mock_cur.fetchall.side_effect = [
        [["Users"], ["passwords"]],
        [["ClickStream"]],
    ]
    schema = introspect_ksqldb(mock_cur, filter_sensitive=True)
    assert any(k.lower() == "users" for k in schema["tables"])
    assert any(k.lower() == "clickstream" for k in schema["tables"])
    assert not any(k.lower() == "passwords" for k in schema["tables"])
    tbl_name = next(k for k in schema["tables"] if k.lower() == "users")
    cols = [col["name"] for col in schema["tables"][tbl_name]["columns"]]
    assert "rowkey" in cols
    assert "user_id" in cols

    # Empty branch
    mock_empty = MagicMock()
    mock_empty.fetchall.return_value = []
    schema_empty = introspect_ksqldb(mock_empty)
    assert "events" in schema_empty["tables"]

    # Error wrapping
    mock_err = MagicMock()
    mock_err.execute.side_effect = RuntimeError("ksqlDB query error")
    with pytest.raises(IntrospectionError):
        introspect_ksqldb(mock_err)


def test_introspect_flink_branches():
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [["Orders"], ["passwords"]]
    schema = introspect_flink(mock_cur, filter_sensitive=True)
    assert any(k.lower() == "orders" for k in schema["tables"])
    assert not any(k.lower() == "passwords" for k in schema["tables"])
    tbl_name = next(k for k in schema["tables"] if k.lower() == "orders")
    cols = [col["name"] for col in schema["tables"][tbl_name]["columns"]]
    assert "id" in cols
    assert "user_id" in cols

    # Empty branch
    mock_empty = MagicMock()
    mock_empty.fetchall.return_value = []
    schema_empty = introspect_flink(mock_empty)
    assert "events" in schema_empty["tables"]

    # Error wrapping
    mock_err = MagicMock()
    mock_err.execute.side_effect = RuntimeError("Flink catalog error")
    with pytest.raises(IntrospectionError):
        introspect_flink(mock_err)


def test_introspect_pulsar_branches():
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [["Topics"], ["passwords"]]
    schema = introspect_pulsar(mock_cur, filter_sensitive=True)
    assert any(k.lower() == "topics" for k in schema["tables"])
    assert not any(k.lower() == "passwords" for k in schema["tables"])
    tbl_name = next(k for k in schema["tables"] if k.lower() == "topics")
    cols = [col["name"] for col in schema["tables"][tbl_name]["columns"]]
    assert "__key__" in cols
    assert "__publish_time__" in cols

    # Empty branch
    mock_empty = MagicMock()
    mock_empty.fetchall.return_value = []
    schema_empty = introspect_pulsar(mock_empty)
    assert "messages" in schema_empty["tables"]

    # Error wrapping
    mock_err = MagicMock()
    mock_err.execute.side_effect = RuntimeError("Pulsar coordinator error")
    with pytest.raises(IntrospectionError):
        introspect_pulsar(mock_err)
