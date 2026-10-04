"""
Comprehensive Unit Tests for Phase 1 Missing Enterprise Relational Connectors.
=============================================================================
Verifies 100% statement, function, and branch coverage across:
- Firebird Connector, AsyncFirebirdConnector, _FirebirdCursorAdapter, FirebirdDialect, introspect_firebird
- MonetDB Connector, AsyncMonetDBConnector, _MonetDBCursorAdapter, MonetDBDialect, introspect_monetdb
- H2 Connector, AsyncH2Connector, _H2CursorAdapter, H2Dialect, introspect_h2
- Derby Connector, AsyncDerbyConnector, _DerbyCursorAdapter, DerbyDialect, introspect_derby
- Sybase Connector / SAP ASE, AsyncSybaseConnector, _SybaseCursorAdapter, SybaseDialect, introspect_sybase
- Informix Connector / IBM Informix, AsyncInformixConnector, _InformixCursorAdapter, InformixDialect, introspect_informix
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock, patch

import pytest

from query_builder.connectors import (
    AsyncDerbyConnector,
    AsyncFirebirdConnector,
    AsyncH2Connector,
    AsyncIBMInformixConnector,
    AsyncInformixConnector,
    AsyncMonetDBConnector,
    AsyncSAPASEConnector,
    AsyncSybaseConnector,
    ConnectionFailedError,
    DerbyConnector,
    DriverNotInstalledError,
    FirebirdConnector,
    H2Connector,
    IBMInformixConnector,
    InformixConnector,
    IntrospectionError,
    MonetDBConnector,
    SAPASEConnector,
    SybaseConnector,
    get_connector,
    introspect_derby,
    introspect_firebird,
    introspect_h2,
    introspect_informix,
    introspect_monetdb,
    introspect_sybase,
    list_connectors,
)
from query_builder.connectors.derby import _DerbyCursorAdapter
from query_builder.connectors.firebird import _FirebirdCursorAdapter
from query_builder.connectors.h2 import _H2CursorAdapter
from query_builder.connectors.informix import _InformixCursorAdapter
from query_builder.connectors.monetdb import _MonetDBCursorAdapter
from query_builder.connectors.sybase import _SybaseCursorAdapter
from query_builder.dialects import (
    DerbyDialect,
    FirebirdDialect,
    H2Dialect,
    InformixDialect,
    MonetDBDialect,
    SybaseDialect,
    get_dialect,
)

# ============================================================================
# 1. Dialect Tests
# ============================================================================


def test_firebird_dialect():
    d = get_dialect("firebird")
    assert isinstance(d, FirebirdDialect)
    assert d.name == "firebird"
    assert d.placeholder == "?"
    assert get_dialect("firebirdsql").name == "firebird"

    assert d.format_ilike('"name"') == 'LOWER("name") LIKE LOWER(?)'
    assert d.quote_identifier("users") == '"users"'

    # format_limit_offset branches
    c, p = d.format_limit_offset(10, 20)
    assert c == "ROWS ? TO ?" and p == [21, 30]
    c, p = d.format_limit_offset(10, 0)
    assert c == "ROWS ?" and p == [10]

    # inspect queries
    q, p = d.inspect_tables_query("public")
    assert "RDB$RELATIONS" in q and p == []
    q, p = d.inspect_tables_query()
    assert "RDB$RELATIONS" in q and p == []

    q, p = d.inspect_columns_query("public", "users")
    assert "RDB$RELATION_FIELDS" in q and p == ["USERS"]
    q, p = d.inspect_columns_query("public")
    assert "RDB$RELATION_FIELDS" in q and p == []

    q, p = d.inspect_primary_keys_query("public", "users")
    assert "RDB$RELATION_CONSTRAINTS" in q and p == ["USERS"]
    q, p = d.inspect_primary_keys_query()
    assert "RDB$RELATION_CONSTRAINTS" in q and p == []

    q, p = d.inspect_foreign_keys_query("public", "users")
    assert "RDB$REF_CONSTRAINTS" in q and p == ["USERS"]
    q, p = d.inspect_foreign_keys_query()
    assert "RDB$REF_CONSTRAINTS" in q and p == []


def test_monetdb_dialect():
    d = get_dialect("monetdb")
    assert isinstance(d, MonetDBDialect)
    assert d.name == "monetdb"
    assert d.placeholder == "?"
    assert get_dialect("monet").name == "monetdb"

    assert d.format_ilike('"name"') == '"name" ILIKE ?'
    assert d.quote_identifier("users") == '"users"'

    c, p = d.format_limit_offset(10, 20)
    assert c == "LIMIT ? OFFSET ?" and p == [10, 20]

    q, p = d.inspect_tables_query("sys")
    assert "sys.tables" in q and p == ["sys"]
    q, p = d.inspect_columns_query("sys", "users")
    assert "sys.columns" in q and p == ["sys", "users"]
    q, p = d.inspect_columns_query("sys")
    assert "sys.columns" in q and p == ["sys"]

    q, p = d.inspect_primary_keys_query("sys", "users")
    assert "sys.keys" in q and p == ["sys", "users"]
    q, p = d.inspect_primary_keys_query("sys")
    assert "sys.keys" in q and p == ["sys"]

    q, p = d.inspect_foreign_keys_query("sys", "users")
    assert "sys.fkeys" in q and p == ["sys", "users"]
    q, p = d.inspect_foreign_keys_query("sys")
    assert "sys.fkeys" in q and p == ["sys"]


def test_h2_dialect():
    d = get_dialect("h2")
    assert isinstance(d, H2Dialect)
    assert d.name == "h2"
    assert d.placeholder == "?"
    assert get_dialect("h2db").name == "h2"

    assert d.format_ilike('"name"') == '"name" ILIKE ?'
    assert d.quote_identifier("users") == '"users"'

    c, p = d.format_limit_offset(10, 20)
    assert c == "LIMIT ? OFFSET ?" and p == [10, 20]

    q, p = d.inspect_tables_query("PUBLIC")
    assert "information_schema.tables" in q and p == ["PUBLIC"]
    q, p = d.inspect_columns_query("PUBLIC", "users")
    assert "information_schema.columns" in q and p == ["PUBLIC", "USERS"]
    q, p = d.inspect_columns_query("PUBLIC")
    assert "information_schema.columns" in q and p == ["PUBLIC"]

    q, p = d.inspect_primary_keys_query("PUBLIC", "users")
    assert "information_schema.table_constraints" in q and p == ["PUBLIC", "USERS"]
    q, p = d.inspect_primary_keys_query("PUBLIC")
    assert "information_schema.table_constraints" in q and p == ["PUBLIC"]

    q, p = d.inspect_foreign_keys_query("PUBLIC", "users")
    assert "information_schema.table_constraints" in q and p == ["PUBLIC", "USERS"]
    q, p = d.inspect_foreign_keys_query("PUBLIC")
    assert "information_schema.table_constraints" in q and p == ["PUBLIC"]


def test_derby_dialect():
    d = get_dialect("derby")
    assert isinstance(d, DerbyDialect)
    assert d.name == "derby"
    assert d.placeholder == "?"
    assert get_dialect("apache_derby").name == "derby"

    assert d.format_ilike('"name"') == 'LOWER("name") LIKE LOWER(?)'
    assert d.quote_identifier("users") == '"users"'

    c, p = d.format_limit_offset(10, 20)
    assert c == "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY" and p == [20, 10]
    c, p = d.format_limit_offset(10, 0)
    assert c == "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY" and p == [0, 10]

    q, p = d.inspect_tables_query("APP")
    assert "SYS.SYSTABLES" in q and p == ["APP"]
    q, p = d.inspect_columns_query("APP", "users")
    assert "SYS.SYSCOLUMNS" in q and p == ["APP", "USERS"]
    q, p = d.inspect_columns_query("APP")
    assert "SYS.SYSCOLUMNS" in q and p == ["APP"]

    q, p = d.inspect_primary_keys_query("APP", "users")
    assert "SYS.SYSCONSTRAINTS" in q and p == ["APP", "USERS"]
    q, p = d.inspect_primary_keys_query("APP")
    assert "SYS.SYSCONSTRAINTS" in q and p == ["APP"]

    q, p = d.inspect_foreign_keys_query("APP", "users")
    assert "SYS.SYSCONSTRAINTS" in q and p == ["APP", "USERS"]
    q, p = d.inspect_foreign_keys_query("APP")
    assert "SYS.SYSCONSTRAINTS" in q and p == ["APP"]


def test_sybase_dialect():
    d = get_dialect("sybase")
    assert isinstance(d, SybaseDialect)
    assert d.name == "sybase"
    assert d.placeholder == "?"
    assert get_dialect("sap_ase").name == "sybase"
    assert get_dialect("ase").name == "sybase"

    assert d.quote_identifier("col") == "[col]"
    assert d.quote_identifier("dbo.col") == "[dbo].[col]"
    assert d.format_ilike("[name]") == "LOWER([name]) LIKE LOWER(?)"

    c, p = d.format_limit_offset(10, 20)
    assert c == "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY" and p == [20, 10]

    q, p = d.inspect_tables_query("dbo")
    assert "sysobjects" in q and p == []
    q, p = d.inspect_columns_query("dbo", "users")
    assert "syscolumns" in q and p == ["users"]
    q, p = d.inspect_columns_query("dbo")
    assert "syscolumns" in q and p == []

    q, p = d.inspect_primary_keys_query("dbo", "users")
    assert "sysconstraints" in q and p == ["users"]
    q, p = d.inspect_primary_keys_query("dbo")
    assert "sysconstraints" in q and p == []

    q, p = d.inspect_foreign_keys_query("dbo", "users")
    assert "sysreferences" in q and p == ["users"]
    q, p = d.inspect_foreign_keys_query("dbo")
    assert "sysreferences" in q and p == []


def test_informix_dialect():
    d = get_dialect("informix")
    assert isinstance(d, InformixDialect)
    assert d.name == "informix"
    assert d.placeholder == "%s"
    assert get_dialect("ibm_informix").name == "informix"

    assert d.format_ilike('"name"') == 'LOWER("name") LIKE LOWER(%s)'
    assert d.quote_identifier("users") == '"users"'

    c, p = d.format_limit_offset(10, 20)
    assert c == "SKIP %s FIRST %s" and p == [20, 10]
    c, p = d.format_limit_offset(10, 0)
    assert c == "SKIP %s FIRST %s" and p == [0, 10]

    q, p = d.inspect_tables_query("informix")
    assert "systables" in q and p == ["informix"]
    q, p = d.inspect_columns_query("informix", "users")
    assert "syscolumns" in q and p == ["informix", "users"]
    q, p = d.inspect_columns_query("informix")
    assert "syscolumns" in q and p == ["informix"]

    q, p = d.inspect_primary_keys_query("informix", "users")
    assert "sysconstraints" in q and p == ["informix", "users"]
    q, p = d.inspect_primary_keys_query("informix")
    assert "sysconstraints" in q and p == ["informix"]

    q, p = d.inspect_foreign_keys_query("informix", "users")
    assert "sysreferences" in q and p == ["informix", "users"]
    q, p = d.inspect_foreign_keys_query("informix")
    assert "sysreferences" in q and p == ["informix"]


# ============================================================================
# 2. Cursor Adapter Tests (All 6 Adapters)
# ============================================================================


@pytest.mark.parametrize(
    "adapter_cls",
    [
        _FirebirdCursorAdapter,
        _MonetDBCursorAdapter,
        _H2CursorAdapter,
        _DerbyCursorAdapter,
        _SybaseCursorAdapter,
        _InformixCursorAdapter,
    ],
)
def test_cursor_adapters_comprehensive(adapter_cls):
    # Branch 1: Connection with cursor() method
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

    # Branch 2: Connection with execute() returning result object with fetchall
    mock_res = MagicMock()
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
    assert adapter3.description is None
    assert adapter3.fetchall() == [[100], [200]]

    # Connection with execute() returning scalar
    conn_with_scalar = MagicMock(spec=["execute"])
    conn_with_scalar.execute.return_value = 1
    adapter4 = adapter_cls(conn_with_scalar)
    adapter4.execute("SELECT 1")
    assert adapter4.fetchall() == []

    # Branch 3: Connection without cursor or execute
    bare_conn = object()
    adapter5 = adapter_cls(bare_conn)
    adapter5.execute("SELECT 1")
    assert adapter5.description is None
    assert adapter5.fetchall() == []


# ============================================================================
# 3. Firebird Connector & AsyncFirebirdConnector Tests
# ============================================================================


def test_firebird_connector_registry_and_sync():
    assert "firebird" in list_connectors()
    assert "firebirdsql" in list_connectors()
    assert isinstance(get_connector("firebird"), FirebirdConnector)
    assert isinstance(get_connector("firebirdsql"), FirebirdConnector)

    conn = FirebirdConnector()
    assert conn.dialect_name == "firebird"

    # Cached connection
    existing_conn = MagicMock()
    cached_c = FirebirdConnector(connection=existing_conn)
    assert cached_c.connect() is existing_conn

    # Missing driver
    with (
        patch.dict(
            sys.modules, {"firebird.driver": None, "firebird": None, "fdb": None}
        ),
        pytest.raises(DriverNotInstalledError, match="firebird-driver"),
    ):
        conn.connect()

    # Connection failure
    mock_drv = MagicMock()
    mock_drv.connect.side_effect = RuntimeError("Firebird connection refused")
    with (
        patch.dict(sys.modules, {"firebird.driver": mock_drv}),
        pytest.raises(ConnectionFailedError),
    ):
        conn.connect()

    # Successful connect
    mock_drv.connect.side_effect = None
    mock_drv.connect.return_value = existing_conn
    with patch.dict(sys.modules, {"firebird.driver": mock_drv}):
        c2 = FirebirdConnector()
        assert c2.connect() is existing_conn

    # get_cursor with cursor provided
    mock_cur = MagicMock()
    c_cur = FirebirdConnector(cursor=mock_cur)
    with c_cur.get_cursor() as cur:
        assert cur is mock_cur

    # get_cursor with conn having cursor()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    c_conn = FirebirdConnector(connection=mock_conn)
    with c_conn.get_cursor() as cur:
        assert cur is mock_cur
    mock_cur.close.assert_called_once()

    # get_cursor with conn having execute only (adapter fallback)
    conn_no_cur = MagicMock(spec=["execute"])
    c_adapter = FirebirdConnector(connection=conn_no_cur)
    with c_adapter.get_cursor() as cur:
        assert isinstance(cur, _FirebirdCursorAdapter)

    # test_connection
    mock_cur.fetchone.return_value = [1]
    res = c_conn.test_connection()
    assert res["status"] == "healthy"
    assert res["engine_version"] == "Firebird"

    # introspect_schema success and failure
    with (
        patch(
            "query_builder.connectors.firebird.introspect_firebird",
            return_value={"tables": {}},
        ),
    ):
        assert c_conn.introspect_schema() == {"tables": {}}

    with (
        patch(
            "query_builder.connectors.firebird.introspect_firebird",
            side_effect=RuntimeError("Introspect failed"),
        ),
        pytest.raises(IntrospectionError),
    ):
        c_conn.introspect_schema()


def test_async_firebird_connector():
    async def _test():
        assert "async_firebird" in list_connectors()
        assert "async_firebirdsql" in list_connectors()
        assert isinstance(get_connector("async_firebird"), AsyncFirebirdConnector)

        conn = AsyncFirebirdConnector()
        assert conn.dialect_name == "firebird"

        # Cached connection
        mock_conn = MagicMock()
        cached_c = AsyncFirebirdConnector(connection=mock_conn)
        assert await cached_c.connect() is mock_conn

        # Missing driver
        with (
            patch.dict(
                sys.modules, {"firebird.driver": None, "firebird": None, "fdb": None}
            ),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection error
        mock_drv = MagicMock()
        mock_drv.connect.side_effect = RuntimeError("Firebird async fail")
        with (
            patch.dict(sys.modules, {"firebird.driver": mock_drv}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # execute_raw with cursor
        mock_cur = MagicMock()
        mock_cur.description = [("val", 0)]
        mock_cur.fetchall.return_value = [[99]]
        mock_conn.cursor.return_value = mock_cur

        c_exec = AsyncFirebirdConnector(connection=mock_conn)
        cols, rows, lat = await c_exec.execute_raw("SELECT 99;", [1])
        assert cols == ["val"]
        assert rows == [{"val": 99}]
        assert lat >= 0

        # execute_raw without params and with adapter
        conn_no_cur = MagicMock(spec=["execute"])
        mock_res = MagicMock()
        mock_res.description = [("a", 0)]
        mock_res.fetchall.return_value = [[123]]
        conn_no_cur.execute.return_value = mock_res
        c_adapter = AsyncFirebirdConnector(connection=conn_no_cur)
        cols2, rows2, _ = await c_adapter.execute_raw("SELECT 123;")
        assert cols2 == ["a"]
        assert rows2 == [{"a": 123}]

        # test_connection
        t_res = await c_exec.test_connection()
        assert t_res["status"] == "healthy"
        assert t_res["engine_version"] == "Firebird"

        # introspect_schema success and error
        with patch(
            "query_builder.connectors.firebird.introspect_firebird",
            return_value={"tables": {}},
        ):
            snap = await c_exec.introspect_schema()
            assert snap == {"tables": {}}

        # introspect with adapter
        with patch(
            "query_builder.connectors.firebird.introspect_firebird",
            return_value={"tables": {"x": {}}},
        ):
            snap2 = await c_adapter.introspect_schema()
            assert "x" in snap2["tables"]

        with (
            patch(
                "query_builder.connectors.firebird.introspect_firebird",
                side_effect=RuntimeError("Async introspect err"),
            ),
            pytest.raises(IntrospectionError),
        ):
            await c_exec.introspect_schema()

        # async context manager
        async with c_exec as c_ctx:
            assert c_ctx is c_exec

    asyncio.run(_test())


# ============================================================================
# 4. MonetDB Connector & AsyncMonetDBConnector Tests
# ============================================================================


def test_monetdb_connector_registry_and_sync():
    assert "monetdb" in list_connectors()
    assert "monet" in list_connectors()
    assert isinstance(get_connector("monetdb"), MonetDBConnector)
    assert isinstance(get_connector("monet"), MonetDBConnector)

    conn = MonetDBConnector()
    assert conn.dialect_name == "monetdb"

    # Cached connection
    existing_conn = MagicMock()
    cached_c = MonetDBConnector(connection=existing_conn)
    assert cached_c.connect() is existing_conn

    # Missing driver
    with (
        patch.dict(sys.modules, {"pymonetdb": None}),
        pytest.raises(DriverNotInstalledError, match="pymonetdb"),
    ):
        conn.connect()

    # Connection failure
    mock_drv = MagicMock()
    mock_drv.connect.side_effect = RuntimeError("MonetDB connect refused")
    with (
        patch.dict(sys.modules, {"pymonetdb": mock_drv}),
        pytest.raises(ConnectionFailedError),
    ):
        conn.connect()

    # Successful connect
    mock_drv.connect.side_effect = None
    mock_drv.connect.return_value = existing_conn
    with patch.dict(sys.modules, {"pymonetdb": mock_drv}):
        c2 = MonetDBConnector()
        assert c2.connect() is existing_conn

    # get_cursor with cursor provided
    mock_cur = MagicMock()
    c_cur = MonetDBConnector(cursor=mock_cur)
    with c_cur.get_cursor() as cur:
        assert cur is mock_cur

    # get_cursor with conn having cursor()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    c_conn = MonetDBConnector(connection=mock_conn)
    with c_conn.get_cursor() as cur:
        assert cur is mock_cur
    mock_cur.close.assert_called_once()

    # get_cursor with adapter fallback
    conn_no_cur = MagicMock(spec=["execute"])
    c_adapter = MonetDBConnector(connection=conn_no_cur)
    with c_adapter.get_cursor() as cur:
        assert isinstance(cur, _MonetDBCursorAdapter)

    # test_connection
    mock_cur.fetchone.return_value = [1]
    res = c_conn.test_connection()
    assert res["status"] == "healthy"
    assert res["engine_version"] == "MonetDB"

    # introspect_schema success and failure
    with patch(
        "query_builder.connectors.monetdb.introspect_monetdb",
        return_value={"tables": {}},
    ):
        assert c_conn.introspect_schema() == {"tables": {}}

    with (
        patch(
            "query_builder.connectors.monetdb.introspect_monetdb",
            side_effect=RuntimeError("Introspect failed"),
        ),
        pytest.raises(IntrospectionError),
    ):
        c_conn.introspect_schema()


def test_async_monetdb_connector():
    async def _test():
        assert "async_monetdb" in list_connectors()
        assert "async_monet" in list_connectors()
        assert isinstance(get_connector("async_monetdb"), AsyncMonetDBConnector)

        conn = AsyncMonetDBConnector()
        assert conn.dialect_name == "monetdb"

        # Cached connection
        mock_conn = MagicMock()
        cached_c = AsyncMonetDBConnector(connection=mock_conn)
        assert await cached_c.connect() is mock_conn

        # Missing driver
        with (
            patch.dict(sys.modules, {"pymonetdb": None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection error
        mock_drv = MagicMock()
        mock_drv.connect.side_effect = RuntimeError("MonetDB async fail")
        with (
            patch.dict(sys.modules, {"pymonetdb": mock_drv}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # execute_raw with cursor
        mock_cur = MagicMock()
        mock_cur.description = [("val", 0)]
        mock_cur.fetchall.return_value = [[99]]
        mock_conn.cursor.return_value = mock_cur

        c_exec = AsyncMonetDBConnector(connection=mock_conn)
        cols, rows, lat = await c_exec.execute_raw("SELECT 99;", [1])
        assert cols == ["val"]
        assert rows == [{"val": 99}]
        assert lat >= 0

        # execute_raw without params and with adapter
        conn_no_cur = MagicMock(spec=["execute"])
        mock_res = MagicMock()
        mock_res.description = [("a", 0)]
        mock_res.fetchall.return_value = [[123]]
        conn_no_cur.execute.return_value = mock_res
        c_adapter = AsyncMonetDBConnector(connection=conn_no_cur)
        cols2, rows2, _ = await c_adapter.execute_raw("SELECT 123;")
        assert cols2 == ["a"]
        assert rows2 == [{"a": 123}]

        # test_connection
        t_res = await c_exec.test_connection()
        assert t_res["status"] == "healthy"
        assert t_res["engine_version"] == "MonetDB"

        # introspect_schema success and error
        with patch(
            "query_builder.connectors.monetdb.introspect_monetdb",
            return_value={"tables": {}},
        ):
            snap = await c_exec.introspect_schema()
            assert snap == {"tables": {}}

        # introspect with adapter
        with patch(
            "query_builder.connectors.monetdb.introspect_monetdb",
            return_value={"tables": {"x": {}}},
        ):
            snap2 = await c_adapter.introspect_schema()
            assert "x" in snap2["tables"]

        with (
            patch(
                "query_builder.connectors.monetdb.introspect_monetdb",
                side_effect=RuntimeError("Async introspect err"),
            ),
            pytest.raises(IntrospectionError),
        ):
            await c_exec.introspect_schema()

        # async context manager
        async with c_exec as c_ctx:
            assert c_ctx is c_exec

    asyncio.run(_test())


# ============================================================================
# 5. H2 Connector & AsyncH2Connector Tests
# ============================================================================


def test_h2_connector_registry_and_sync():
    assert "h2" in list_connectors()
    assert "h2db" in list_connectors()
    assert isinstance(get_connector("h2"), H2Connector)
    assert isinstance(get_connector("h2db"), H2Connector)

    conn = H2Connector()
    assert conn.dialect_name == "h2"

    # Cached connection
    existing_conn = MagicMock()
    cached_c = H2Connector(connection=existing_conn)
    assert cached_c.connect() is existing_conn

    # Missing driver
    with (
        patch.dict(sys.modules, {"jaydebeapi": None, "h2": None, "pypyodbc": None}),
        pytest.raises(DriverNotInstalledError, match="jaydebeapi"),
    ):
        conn.connect()

    # Connection failure
    mock_drv = MagicMock()
    mock_drv.connect.side_effect = RuntimeError("H2 connect refused")
    with (
        patch.dict(sys.modules, {"jaydebeapi": mock_drv}),
        pytest.raises(ConnectionFailedError),
    ):
        conn.connect()

    # Successful connect
    mock_drv.connect.side_effect = None
    mock_drv.connect.return_value = existing_conn
    with patch.dict(sys.modules, {"jaydebeapi": mock_drv}):
        c2 = H2Connector()
        assert c2.connect() is existing_conn

    # get_cursor with cursor provided
    mock_cur = MagicMock()
    c_cur = H2Connector(cursor=mock_cur)
    with c_cur.get_cursor() as cur:
        assert cur is mock_cur

    # get_cursor with conn having cursor()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    c_conn = H2Connector(connection=mock_conn)
    with c_conn.get_cursor() as cur:
        assert cur is mock_cur
    mock_cur.close.assert_called_once()

    # get_cursor with adapter fallback
    conn_no_cur = MagicMock(spec=["execute"])
    c_adapter = H2Connector(connection=conn_no_cur)
    with c_adapter.get_cursor() as cur:
        assert isinstance(cur, _H2CursorAdapter)

    # test_connection
    mock_cur.fetchone.return_value = [1]
    res = c_conn.test_connection()
    assert res["status"] == "healthy"
    assert res["engine_version"] == "H2 Database"

    # introspect_schema success and failure
    with patch(
        "query_builder.connectors.h2.introspect_h2",
        return_value={"tables": {}},
    ):
        assert c_conn.introspect_schema() == {"tables": {}}

    with (
        patch(
            "query_builder.connectors.h2.introspect_h2",
            side_effect=RuntimeError("Introspect failed"),
        ),
        pytest.raises(IntrospectionError),
    ):
        c_conn.introspect_schema()


def test_async_h2_connector():
    async def _test():
        assert "async_h2" in list_connectors()
        assert "async_h2db" in list_connectors()
        assert isinstance(get_connector("async_h2"), AsyncH2Connector)

        conn = AsyncH2Connector()
        assert conn.dialect_name == "h2"

        # Cached connection
        mock_conn = MagicMock()
        cached_c = AsyncH2Connector(connection=mock_conn)
        assert await cached_c.connect() is mock_conn

        # Missing driver
        with (
            patch.dict(sys.modules, {"jaydebeapi": None, "h2": None, "pypyodbc": None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection error
        mock_drv = MagicMock()
        mock_drv.connect.side_effect = RuntimeError("H2 async fail")
        with (
            patch.dict(sys.modules, {"jaydebeapi": mock_drv}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # execute_raw with cursor
        mock_cur = MagicMock()
        mock_cur.description = [("val", 0)]
        mock_cur.fetchall.return_value = [[99]]
        mock_conn.cursor.return_value = mock_cur

        c_exec = AsyncH2Connector(connection=mock_conn)
        cols, rows, lat = await c_exec.execute_raw("SELECT 99;", [1])
        assert cols == ["val"]
        assert rows == [{"val": 99}]
        assert lat >= 0

        # execute_raw without params and with adapter
        conn_no_cur = MagicMock(spec=["execute"])
        mock_res = MagicMock()
        mock_res.description = [("a", 0)]
        mock_res.fetchall.return_value = [[123]]
        conn_no_cur.execute.return_value = mock_res
        c_adapter = AsyncH2Connector(connection=conn_no_cur)
        cols2, rows2, _ = await c_adapter.execute_raw("SELECT 123;")
        assert cols2 == ["a"]
        assert rows2 == [{"a": 123}]

        # test_connection
        t_res = await c_exec.test_connection()
        assert t_res["status"] == "healthy"
        assert t_res["engine_version"] == "H2 Database"

        # introspect_schema success and error
        with patch(
            "query_builder.connectors.h2.introspect_h2",
            return_value={"tables": {}},
        ):
            snap = await c_exec.introspect_schema()
            assert snap == {"tables": {}}

        # introspect with adapter
        with patch(
            "query_builder.connectors.h2.introspect_h2",
            return_value={"tables": {"x": {}}},
        ):
            snap2 = await c_adapter.introspect_schema()
            assert "x" in snap2["tables"]

        with (
            patch(
                "query_builder.connectors.h2.introspect_h2",
                side_effect=RuntimeError("Async introspect err"),
            ),
            pytest.raises(IntrospectionError),
        ):
            await c_exec.introspect_schema()

        # async context manager
        async with c_exec as c_ctx:
            assert c_ctx is c_exec

    asyncio.run(_test())


# ============================================================================
# 6. Derby Connector & AsyncDerbyConnector Tests
# ============================================================================


def test_derby_connector_registry_and_sync():
    assert "derby" in list_connectors()
    assert "apache_derby" in list_connectors()
    assert isinstance(get_connector("derby"), DerbyConnector)
    assert isinstance(get_connector("apache_derby"), DerbyConnector)

    conn = DerbyConnector()
    assert conn.dialect_name == "derby"

    # Cached connection
    existing_conn = MagicMock()
    cached_c = DerbyConnector(connection=existing_conn)
    assert cached_c.connect() is existing_conn

    # Missing driver
    with (
        patch.dict(sys.modules, {"jaydebeapi": None, "drda": None}),
        pytest.raises(DriverNotInstalledError, match="jaydebeapi"),
    ):
        conn.connect()

    # Connection failure
    mock_drv = MagicMock()
    mock_drv.connect.side_effect = RuntimeError("Derby connect refused")
    with (
        patch.dict(sys.modules, {"jaydebeapi": mock_drv}),
        pytest.raises(ConnectionFailedError),
    ):
        conn.connect()

    # Successful connect
    mock_drv.connect.side_effect = None
    mock_drv.connect.return_value = existing_conn
    with patch.dict(sys.modules, {"jaydebeapi": mock_drv}):
        c2 = DerbyConnector()
        assert c2.connect() is existing_conn

    # get_cursor with cursor provided
    mock_cur = MagicMock()
    c_cur = DerbyConnector(cursor=mock_cur)
    with c_cur.get_cursor() as cur:
        assert cur is mock_cur

    # get_cursor with conn having cursor()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    c_conn = DerbyConnector(connection=mock_conn)
    with c_conn.get_cursor() as cur:
        assert cur is mock_cur
    mock_cur.close.assert_called_once()

    # get_cursor with adapter fallback
    conn_no_cur = MagicMock(spec=["execute"])
    c_adapter = DerbyConnector(connection=conn_no_cur)
    with c_adapter.get_cursor() as cur:
        assert isinstance(cur, _DerbyCursorAdapter)

    # test_connection
    mock_cur.fetchone.return_value = [1]
    res = c_conn.test_connection()
    assert res["status"] == "healthy"
    assert res["engine_version"] == "Apache Derby"

    # introspect_schema success and failure
    with patch(
        "query_builder.connectors.derby.introspect_derby",
        return_value={"tables": {}},
    ):
        assert c_conn.introspect_schema() == {"tables": {}}

    with (
        patch(
            "query_builder.connectors.derby.introspect_derby",
            side_effect=RuntimeError("Introspect failed"),
        ),
        pytest.raises(IntrospectionError),
    ):
        c_conn.introspect_schema()


def test_async_derby_connector():
    async def _test():
        assert "async_derby" in list_connectors()
        assert "async_apache_derby" in list_connectors()
        assert isinstance(get_connector("async_derby"), AsyncDerbyConnector)

        conn = AsyncDerbyConnector()
        assert conn.dialect_name == "derby"

        # Cached connection
        mock_conn = MagicMock()
        cached_c = AsyncDerbyConnector(connection=mock_conn)
        assert await cached_c.connect() is mock_conn

        # Missing driver
        with (
            patch.dict(sys.modules, {"jaydebeapi": None, "drda": None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection error
        mock_drv = MagicMock()
        mock_drv.connect.side_effect = RuntimeError("Derby async fail")
        with (
            patch.dict(sys.modules, {"jaydebeapi": mock_drv}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # execute_raw with cursor
        mock_cur = MagicMock()
        mock_cur.description = [("val", 0)]
        mock_cur.fetchall.return_value = [[99]]
        mock_conn.cursor.return_value = mock_cur

        c_exec = AsyncDerbyConnector(connection=mock_conn)
        cols, rows, lat = await c_exec.execute_raw("SELECT 99;", [1])
        assert cols == ["val"]
        assert rows == [{"val": 99}]
        assert lat >= 0

        # execute_raw without params and with adapter
        conn_no_cur = MagicMock(spec=["execute"])
        mock_res = MagicMock()
        mock_res.description = [("a", 0)]
        mock_res.fetchall.return_value = [[123]]
        conn_no_cur.execute.return_value = mock_res
        c_adapter = AsyncDerbyConnector(connection=conn_no_cur)
        cols2, rows2, _ = await c_adapter.execute_raw("SELECT 123;")
        assert cols2 == ["a"]
        assert rows2 == [{"a": 123}]

        # test_connection
        t_res = await c_exec.test_connection()
        assert t_res["status"] == "healthy"
        assert t_res["engine_version"] == "Apache Derby"

        # introspect_schema success and error
        with patch(
            "query_builder.connectors.derby.introspect_derby",
            return_value={"tables": {}},
        ):
            snap = await c_exec.introspect_schema()
            assert snap == {"tables": {}}

        # introspect with adapter
        with patch(
            "query_builder.connectors.derby.introspect_derby",
            return_value={"tables": {"x": {}}},
        ):
            snap2 = await c_adapter.introspect_schema()
            assert "x" in snap2["tables"]

        with (
            patch(
                "query_builder.connectors.derby.introspect_derby",
                side_effect=RuntimeError("Async introspect err"),
            ),
            pytest.raises(IntrospectionError),
        ):
            await c_exec.introspect_schema()

        # async context manager
        async with c_exec as c_ctx:
            assert c_ctx is c_exec

    asyncio.run(_test())


# ============================================================================
# 7. Sybase / SAP ASE Connector Tests
# ============================================================================


def test_sybase_connector_registry_and_sync():
    assert "sybase" in list_connectors()
    assert "sap_ase" in list_connectors()
    assert "ase" in list_connectors()
    assert SybaseConnector is SAPASEConnector
    assert isinstance(get_connector("sybase"), SybaseConnector)
    assert isinstance(get_connector("sap_ase"), SybaseConnector)
    assert isinstance(get_connector("ase"), SybaseConnector)

    conn = SybaseConnector()
    assert conn.dialect_name == "sybase"

    # Cached connection
    existing_conn = MagicMock()
    cached_c = SybaseConnector(connection=existing_conn)
    assert cached_c.connect() is existing_conn

    # Missing driver
    with (
        patch.dict(sys.modules, {"pyodbc": None, "freetds": None}),
        pytest.raises(DriverNotInstalledError, match="pyodbc"),
    ):
        conn.connect()

    # Connection failure
    mock_drv = MagicMock()
    mock_drv.connect.side_effect = RuntimeError("Sybase connect refused")
    with (
        patch.dict(sys.modules, {"pyodbc": mock_drv}),
        pytest.raises(ConnectionFailedError),
    ):
        conn.connect()

    # Successful connect
    mock_drv.connect.side_effect = None
    mock_drv.connect.return_value = existing_conn
    with patch.dict(sys.modules, {"pyodbc": mock_drv}):
        c2 = SybaseConnector()
        assert c2.connect() is existing_conn

    # get_cursor with cursor provided
    mock_cur = MagicMock()
    c_cur = SybaseConnector(cursor=mock_cur)
    with c_cur.get_cursor() as cur:
        assert cur is mock_cur

    # get_cursor with conn having cursor()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    c_conn = SybaseConnector(connection=mock_conn)
    with c_conn.get_cursor() as cur:
        assert cur is mock_cur
    mock_cur.close.assert_called_once()

    # get_cursor with adapter fallback
    conn_no_cur = MagicMock(spec=["execute"])
    c_adapter = SybaseConnector(connection=conn_no_cur)
    with c_adapter.get_cursor() as cur:
        assert isinstance(cur, _SybaseCursorAdapter)

    # test_connection
    mock_cur.fetchone.return_value = [1]
    res = c_conn.test_connection()
    assert res["status"] == "healthy"
    assert res["engine_version"] == "Sybase / SAP ASE"

    # introspect_schema success and failure
    with patch(
        "query_builder.connectors.sybase.introspect_sybase",
        return_value={"tables": {}},
    ):
        assert c_conn.introspect_schema() == {"tables": {}}

    with (
        patch(
            "query_builder.connectors.sybase.introspect_sybase",
            side_effect=RuntimeError("Introspect failed"),
        ),
        pytest.raises(IntrospectionError),
    ):
        c_conn.introspect_schema()


def test_async_sybase_connector():
    async def _test():
        assert "async_sybase" in list_connectors()
        assert "async_sap_ase" in list_connectors()
        assert "async_ase" in list_connectors()
        assert AsyncSybaseConnector is AsyncSAPASEConnector
        assert isinstance(get_connector("async_sybase"), AsyncSybaseConnector)

        conn = AsyncSybaseConnector()
        assert conn.dialect_name == "sybase"

        # Cached connection
        mock_conn = MagicMock()
        cached_c = AsyncSybaseConnector(connection=mock_conn)
        assert await cached_c.connect() is mock_conn

        # Missing driver
        with (
            patch.dict(sys.modules, {"pyodbc": None, "freetds": None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection error
        mock_drv = MagicMock()
        mock_drv.connect.side_effect = RuntimeError("Sybase async fail")
        with (
            patch.dict(sys.modules, {"pyodbc": mock_drv}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # execute_raw with cursor
        mock_cur = MagicMock()
        mock_cur.description = [("val", 0)]
        mock_cur.fetchall.return_value = [[99]]
        mock_conn.cursor.return_value = mock_cur

        c_exec = AsyncSybaseConnector(connection=mock_conn)
        cols, rows, lat = await c_exec.execute_raw("SELECT 99;", [1])
        assert cols == ["val"]
        assert rows == [{"val": 99}]
        assert lat >= 0

        # execute_raw without params and with adapter
        conn_no_cur = MagicMock(spec=["execute"])
        mock_res = MagicMock()
        mock_res.description = [("a", 0)]
        mock_res.fetchall.return_value = [[123]]
        conn_no_cur.execute.return_value = mock_res
        c_adapter = AsyncSybaseConnector(connection=conn_no_cur)
        cols2, rows2, _ = await c_adapter.execute_raw("SELECT 123;")
        assert cols2 == ["a"]
        assert rows2 == [{"a": 123}]

        # test_connection
        t_res = await c_exec.test_connection()
        assert t_res["status"] == "healthy"
        assert t_res["engine_version"] == "Sybase / SAP ASE"

        # introspect_schema success and error
        with patch(
            "query_builder.connectors.sybase.introspect_sybase",
            return_value={"tables": {}},
        ):
            snap = await c_exec.introspect_schema()
            assert snap == {"tables": {}}

        # introspect with adapter
        with patch(
            "query_builder.connectors.sybase.introspect_sybase",
            return_value={"tables": {"x": {}}},
        ):
            snap2 = await c_adapter.introspect_schema()
            assert "x" in snap2["tables"]

        with (
            patch(
                "query_builder.connectors.sybase.introspect_sybase",
                side_effect=RuntimeError("Async introspect err"),
            ),
            pytest.raises(IntrospectionError),
        ):
            await c_exec.introspect_schema()

        # async context manager
        async with c_exec as c_ctx:
            assert c_ctx is c_exec

    asyncio.run(_test())


# ============================================================================
# 8. IBM Informix Connector Tests
# ============================================================================


def test_informix_connector_registry_and_sync():
    assert "informix" in list_connectors()
    assert "ibm_informix" in list_connectors()
    assert InformixConnector is IBMInformixConnector
    assert isinstance(get_connector("informix"), InformixConnector)
    assert isinstance(get_connector("ibm_informix"), InformixConnector)

    conn = InformixConnector()
    assert conn.dialect_name == "informix"

    # Cached connection
    existing_conn = MagicMock()
    cached_c = InformixConnector(connection=existing_conn)
    assert cached_c.connect() is existing_conn

    # Missing driver
    with (
        patch.dict(sys.modules, {"ibm_db_dbi": None, "ibm_db": None}),
        pytest.raises(DriverNotInstalledError, match="ibm_db"),
    ):
        conn.connect()

    # Connection failure
    mock_drv = MagicMock()
    mock_drv.connect.side_effect = RuntimeError("Informix connect refused")
    with (
        patch.dict(sys.modules, {"ibm_db_dbi": mock_drv}),
        pytest.raises(ConnectionFailedError),
    ):
        conn.connect()

    # Successful connect
    mock_drv.connect.side_effect = None
    mock_drv.connect.return_value = existing_conn
    with patch.dict(sys.modules, {"ibm_db_dbi": mock_drv}):
        c2 = InformixConnector()
        assert c2.connect() is existing_conn

    # get_cursor with cursor provided
    mock_cur = MagicMock()
    c_cur = InformixConnector(cursor=mock_cur)
    with c_cur.get_cursor() as cur:
        assert cur is mock_cur

    # get_cursor with conn having cursor()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    c_conn = InformixConnector(connection=mock_conn)
    with c_conn.get_cursor() as cur:
        assert cur is mock_cur
    mock_cur.close.assert_called_once()

    # get_cursor with adapter fallback
    conn_no_cur = MagicMock(spec=["execute"])
    c_adapter = InformixConnector(connection=conn_no_cur)
    with c_adapter.get_cursor() as cur:
        assert isinstance(cur, _InformixCursorAdapter)

    # test_connection
    mock_cur.fetchone.return_value = [1]
    res = c_conn.test_connection()
    assert res["status"] == "healthy"
    assert res["engine_version"] == "IBM Informix"

    # introspect_schema success and failure
    with patch(
        "query_builder.connectors.informix.introspect_informix",
        return_value={"tables": {}},
    ):
        assert c_conn.introspect_schema() == {"tables": {}}

    with (
        patch(
            "query_builder.connectors.informix.introspect_informix",
            side_effect=RuntimeError("Introspect failed"),
        ),
        pytest.raises(IntrospectionError),
    ):
        c_conn.introspect_schema()


def test_async_informix_connector():
    async def _test():
        assert "async_informix" in list_connectors()
        assert "async_ibm_informix" in list_connectors()
        assert AsyncInformixConnector is AsyncIBMInformixConnector
        assert isinstance(get_connector("async_informix"), AsyncInformixConnector)

        conn = AsyncInformixConnector()
        assert conn.dialect_name == "informix"

        # Cached connection
        mock_conn = MagicMock()
        cached_c = AsyncInformixConnector(connection=mock_conn)
        assert await cached_c.connect() is mock_conn

        # Missing driver
        with (
            patch.dict(sys.modules, {"ibm_db_dbi": None, "ibm_db": None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection error
        mock_drv = MagicMock()
        mock_drv.connect.side_effect = RuntimeError("Informix async fail")
        with (
            patch.dict(sys.modules, {"ibm_db_dbi": mock_drv}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # execute_raw with cursor
        mock_cur = MagicMock()
        mock_cur.description = [("val", 0)]
        mock_cur.fetchall.return_value = [[99]]
        mock_conn.cursor.return_value = mock_cur

        c_exec = AsyncInformixConnector(connection=mock_conn)
        cols, rows, lat = await c_exec.execute_raw("SELECT 99;", [1])
        assert cols == ["val"]
        assert rows == [{"val": 99}]
        assert lat >= 0

        # execute_raw without params and with adapter
        conn_no_cur = MagicMock(spec=["execute"])
        mock_res = MagicMock()
        mock_res.description = [("a", 0)]
        mock_res.fetchall.return_value = [[123]]
        conn_no_cur.execute.return_value = mock_res
        c_adapter = AsyncInformixConnector(connection=conn_no_cur)
        cols2, rows2, _ = await c_adapter.execute_raw("SELECT 123;")
        assert cols2 == ["a"]
        assert rows2 == [{"a": 123}]

        # test_connection
        t_res = await c_exec.test_connection()
        assert t_res["status"] == "healthy"
        assert t_res["engine_version"] == "IBM Informix"

        # introspect_schema success and error
        with patch(
            "query_builder.connectors.informix.introspect_informix",
            return_value={"tables": {}},
        ):
            snap = await c_exec.introspect_schema()
            assert snap == {"tables": {}}

        # introspect with adapter
        with patch(
            "query_builder.connectors.informix.introspect_informix",
            return_value={"tables": {"x": {}}},
        ):
            snap2 = await c_adapter.introspect_schema()
            assert "x" in snap2["tables"]

        with (
            patch(
                "query_builder.connectors.informix.introspect_informix",
                side_effect=RuntimeError("Async introspect err"),
            ),
            pytest.raises(IntrospectionError),
        ):
            await c_exec.introspect_schema()

        # async context manager
        async with c_exec as c_ctx:
            assert c_ctx is c_exec

    asyncio.run(_test())


# ============================================================================
# 9. Introspection Functions In-Depth Unit Tests
# ============================================================================


def test_introspect_firebird_deep():
    cur = MagicMock()
    # 1. tables
    # 2. columns
    # 3. primary keys
    # 4. foreign keys
    cur.fetchall.side_effect = [
        [("CUSTOMERS",), ("ORDERS",), ("PASSWORDS",), (None,)],  # tables
        [
            ("CUSTOMERS", "ID", "INTEGER", 1),  # not null
            ("CUSTOMERS", "NAME", "VARCHAR", 0),  # nullable
            ("ORDERS", "ID", "INTEGER", 1),
            ("ORDERS", "CUST_ID", "INTEGER", 0),
            ("ORDERS", "USER_ID", "INTEGER", 0),  # has user_id
            ("PASSWORDS", "ID", "INTEGER", 1),
            (None, None),  # invalid row to skip
        ],
        [
            ("CUSTOMERS", "ID"),
            ("ORDERS", "ID"),
            (None,),  # malformed pkr
        ],
        [
            ("ORDERS", "CUST_ID", "CUSTOMERS", "ID"),
            (None,),  # malformed fkr
        ],
    ]

    snap = introspect_firebird(cur, filter_sensitive=True)
    assert "customers" in snap["tables"]
    assert "orders" in snap["tables"]
    assert "passwords" not in snap["tables"]

    cust_cols = snap["tables"]["customers"]["columns"]
    assert any(c["name"] == "id" and c["is_primary"] is True for c in cust_cols)
    assert any(c["name"] == "name" and c["is_nullable"] is True for c in cust_cols)

    orders_tbl = snap["tables"]["orders"]
    assert orders_tbl["has_user_id"] is True
    assert len(snap["foreign_keys"]) == 1
    assert snap["foreign_keys"][0]["table"] == "orders"
    assert snap["foreign_keys"][0]["foreign_table"] == "customers"

    # Introspect without filter_sensitive
    cur2 = MagicMock()
    cur2.fetchall.side_effect = [
        [("PASSWORDS",)],
        [("PASSWORDS", "ID", "INTEGER", 1)],
        [],
        [],
    ]
    snap2 = introspect_firebird(cur2, filter_sensitive=False)
    assert "passwords" in snap2["tables"]

    # Suppressed exception branches in PK and FK queries
    cur3 = MagicMock()
    cur3.fetchall.side_effect = [
        [("SIMPLE",)],
        [("SIMPLE", "ID", "INT", 1)],
        RuntimeError("PK query failed"),
        RuntimeError("FK query failed"),
    ]
    snap3 = introspect_firebird(cur3)
    assert "simple" in snap3["tables"]

    # Fatal error raises IntrospectionError
    cur_err = MagicMock()
    cur_err.execute.side_effect = RuntimeError("Fatal DB error")
    with pytest.raises(IntrospectionError, match="Firebird"):
        introspect_firebird(cur_err)


def test_introspect_monetdb_deep():
    cur = MagicMock()
    # 1. tables from sys.tables
    # 2. columns from sys.columns
    # 3. primary keys
    # 4. foreign keys
    cur.fetchall.side_effect = [
        [("USERS",), ("PASSWORDS",), (None,)],  # tables
        [
            ("USERS", "ID", "INTEGER", False),  # not null
            ("USERS", "NAME", "VARCHAR", True),  # nullable
            ("USERS", "USER_ID", "INTEGER", True),
            ("PASSWORDS", "ID", "INTEGER", False),
            (None, None, None),  # invalid row
        ],
        [
            ("USERS", "ID"),
            (None,),  # malformed pkr
        ],
        [
            ("USERS", "ID", "USERS", "ID"),
            (None,),  # malformed fkr
        ],
    ]

    snap = introspect_monetdb(cur, schema_name="sys", filter_sensitive=True)
    assert "users" in snap["tables"]
    assert "passwords" not in snap["tables"]
    assert snap["tables"]["users"]["has_user_id"] is True

    # Without filter_sensitive
    cur_s = MagicMock()
    cur_s.fetchall.side_effect = [
        [("PASSWORDS",)],
        [("PASSWORDS", "ID", "INTEGER", False)],
        [],
        [],
    ]
    snap_s = introspect_monetdb(cur_s, schema_name="sys", filter_sensitive=False)
    assert "passwords" in snap_s["tables"]

    # Fallback branch to information_schema when sys.tables fails
    cur_fb = MagicMock()
    cur_fb.fetchall.side_effect = [
        RuntimeError("sys.tables does not exist"),  # will trigger except block
        [("ITEMS",)],  # info_schema tables
        [("ITEMS", "ID", "INTEGER", "NO"), ("ITEMS", "TITLE", "VARCHAR", "YES")],
        [],  # PKs
        [],  # FKs
    ]
    snap_fb = introspect_monetdb(cur_fb, schema_name="sys", filter_sensitive=False)
    assert "items" in snap_fb["tables"]
    item_cols = snap_fb["tables"]["items"]["columns"]
    assert any(c["name"] == "id" and c["is_nullable"] is False for c in item_cols)
    assert any(c["name"] == "title" and c["is_nullable"] is True for c in item_cols)

    # Suppressed PK/FK exceptions
    cur_suppress = MagicMock()
    cur_suppress.fetchall.side_effect = [
        [("T1",)],
        [("T1", "ID", "INT", False)],
        RuntimeError("PK query failed"),
        RuntimeError("FK query failed"),
    ]
    snap_supp = introspect_monetdb(cur_suppress)
    assert "t1" in snap_supp["tables"]

    # Fatal error raises IntrospectionError
    cur_err = MagicMock()
    cur_err.execute.side_effect = RuntimeError("MonetDB fatal error")
    with pytest.raises(IntrospectionError, match="MonetDB"):
        introspect_monetdb(cur_err)


def test_introspect_h2_deep():
    cur = MagicMock()
    # 1. tables
    # 2. columns
    # 3. primary keys
    # 4. foreign keys
    cur.fetchall.side_effect = [
        [("EMPLOYEES",), ("PASSWORDS",), (None,)],
        [
            ("EMPLOYEES", "ID", "BIGINT", "NO"),
            ("EMPLOYEES", "EMAIL", "VARCHAR", "YES"),
            ("EMPLOYEES", "USER_ID", "BIGINT", "YES"),
            ("PASSWORDS", "ID", "BIGINT", "NO"),
            (None,),  # malformed
        ],
        [
            ("EMPLOYEES", "ID"),
            (None,),  # malformed pkr
        ],
        [
            ("EMPLOYEES", "USER_ID", "USERS", "ID"),
            (None,),  # malformed fkr
        ],
    ]

    snap = introspect_h2(cur, schema_name="PUBLIC", filter_sensitive=True)
    assert "employees" in snap["tables"]
    assert "passwords" not in snap["tables"]
    emp = snap["tables"]["employees"]
    assert emp["has_user_id"] is True
    assert len(snap["foreign_keys"]) == 1

    # Without filter_sensitive
    cur2 = MagicMock()
    cur2.fetchall.side_effect = [
        [("PASSWORDS",)],
        [("PASSWORDS", "ID", "BIGINT", "NO")],
        [],
        [],
    ]
    snap2 = introspect_h2(cur2, filter_sensitive=False)
    assert "passwords" in snap2["tables"]

    # Suppressed exceptions
    cur3 = MagicMock()
    cur3.fetchall.side_effect = [
        [("TEST",)],
        [("TEST", "ID", "INT", "NO")],
        RuntimeError("PK failed"),
        RuntimeError("FK failed"),
    ]
    snap3 = introspect_h2(cur3)
    assert "test" in snap3["tables"]

    # Fatal error raises IntrospectionError
    cur_err = MagicMock()
    cur_err.execute.side_effect = RuntimeError("H2 fatal")
    with pytest.raises(IntrospectionError, match="H2"):
        introspect_h2(cur_err)


def test_introspect_derby_deep():
    cur = MagicMock()
    # 1. tables
    # 2. columns
    # 3. primary keys
    # 4. foreign keys
    cur.fetchall.side_effect = [
        [("PROJECTS",), ("PASSWORDS",), (None,)],
        [
            ("PROJECTS", "ID", "INTEGER NOT NULL", None),
            ("PROJECTS", "NAME", "VARCHAR(100)", None),
            ("PROJECTS", "USER_ID", "INTEGER", None),
            ("PASSWORDS", "ID", "INTEGER NOT NULL", None),
            (None,),  # malformed
        ],
        [
            ("PROJECTS", "ID"),
            (None,),  # malformed pkr
        ],
        [
            ("PROJECTS", "USER_ID", "USERS", "ID"),
            (None,),  # malformed fkr
        ],
    ]

    snap = introspect_derby(cur, schema_name="APP", filter_sensitive=True)
    assert "projects" in snap["tables"]
    assert "passwords" not in snap["tables"]
    proj = snap["tables"]["projects"]
    assert proj["has_user_id"] is True
    assert len(snap["foreign_keys"]) == 1

    # Without filter_sensitive
    cur2 = MagicMock()
    cur2.fetchall.side_effect = [
        [("PASSWORDS",)],
        [("PASSWORDS", "ID", "INTEGER NOT NULL", None)],
        [],
        [],
    ]
    snap2 = introspect_derby(cur2, filter_sensitive=False)
    assert "passwords" in snap2["tables"]

    # Suppressed exceptions
    cur3 = MagicMock()
    cur3.fetchall.side_effect = [
        [("TEST",)],
        [("TEST", "ID", "INT NOT NULL", None)],
        RuntimeError("PK failed"),
        RuntimeError("FK failed"),
    ]
    snap3 = introspect_derby(cur3)
    assert "test" in snap3["tables"]

    # Fatal error raises IntrospectionError
    cur_err = MagicMock()
    cur_err.execute.side_effect = RuntimeError("Derby fatal")
    with pytest.raises(IntrospectionError, match="Derby"):
        introspect_derby(cur_err)


def test_introspect_sybase_deep():
    cur = MagicMock()
    # 1. tables
    # 2. columns
    # 3. primary keys
    # 4. foreign keys
    cur.fetchall.side_effect = [
        [("INVOICES",), ("PASSWORDS",), (None,)],
        [
            ("INVOICES", "ID", "int", 0),  # not null (bit 8 not set)
            ("INVOICES", "AMOUNT", "numeric", 8),  # nullable (status & 8 != 0)
            ("INVOICES", "USER_ID", "int", 8),
            ("PASSWORDS", "ID", "int", 0),
            (None,),  # malformed
        ],
        [
            ("INVOICES", "ID"),
            (None,),  # malformed pkr
        ],
        [
            ("INVOICES", "USER_ID", "USERS", "ID"),
            (None,),  # malformed fkr
        ],
    ]

    snap = introspect_sybase(cur, schema_name="dbo", filter_sensitive=True)
    assert "invoices" in snap["tables"]
    assert "passwords" not in snap["tables"]
    inv = snap["tables"]["invoices"]
    assert inv["has_user_id"] is True
    assert len(snap["foreign_keys"]) == 1

    # Without filter_sensitive
    cur2 = MagicMock()
    cur2.fetchall.side_effect = [
        [("PASSWORDS",)],
        [("PASSWORDS", "ID", "int", 0)],
        [],
        [],
    ]
    snap2 = introspect_sybase(cur2, filter_sensitive=False)
    assert "passwords" in snap2["tables"]

    # Suppressed exceptions
    cur3 = MagicMock()
    cur3.fetchall.side_effect = [
        [("TEST",)],
        [("TEST", "ID", "int", 0)],
        RuntimeError("PK failed"),
        RuntimeError("FK failed"),
    ]
    snap3 = introspect_sybase(cur3)
    assert "test" in snap3["tables"]

    # Fatal error raises IntrospectionError
    cur_err = MagicMock()
    cur_err.execute.side_effect = RuntimeError("Sybase fatal")
    with pytest.raises(IntrospectionError, match="Sybase"):
        introspect_sybase(cur_err)


def test_introspect_informix_deep():
    cur = MagicMock()
    # 1. tables
    # 2. columns
    # 3. primary keys
    # 4. foreign keys
    cur.fetchall.side_effect = [
        [("LOGS",), ("PASSWORDS",), (None,)],
        [
            ("LOGS", "ID", 258, 4),  # 258 & 256 != 0 -> NOT NULL
            ("LOGS", "MSG", 13, 255),  # 13 & 256 == 0 -> nullable
            ("LOGS", "USER_ID", 2, 4),
            ("PASSWORDS", "ID", 258, 4),
            (None,),  # malformed
        ],
        [
            ("LOGS", "ID"),
            (None,),  # malformed pkr
        ],
        [
            ("LOGS", "USER_ID", "USERS", "ID"),
            (None,),  # malformed fkr
        ],
    ]

    snap = introspect_informix(cur, schema_name="informix", filter_sensitive=True)
    assert "logs" in snap["tables"]
    assert "passwords" not in snap["tables"]
    logs_tbl = snap["tables"]["logs"]
    assert logs_tbl["has_user_id"] is True
    assert len(snap["foreign_keys"]) == 1

    # Without filter_sensitive
    cur2 = MagicMock()
    cur2.fetchall.side_effect = [
        [("PASSWORDS",)],
        [("PASSWORDS", "ID", 258, 4)],
        [],
        [],
    ]
    snap2 = introspect_informix(cur2, filter_sensitive=False)
    assert "passwords" in snap2["tables"]

    # Suppressed exceptions
    cur3 = MagicMock()
    cur3.fetchall.side_effect = [
        [("TEST",)],
        [("TEST", "ID", 258, 4)],
        RuntimeError("PK failed"),
        RuntimeError("FK failed"),
    ]
    snap3 = introspect_informix(cur3)
    assert "test" in snap3["tables"]

    # Fatal error raises IntrospectionError
    cur_err = MagicMock()
    cur_err.execute.side_effect = RuntimeError("Informix fatal")
    with pytest.raises(IntrospectionError, match="Informix"):
        introspect_informix(cur_err)


def test_sybase_dialect_quote_alias():
    d = get_dialect("sybase")
    assert d.quote_alias("my_alias]") == "[my_alias]]]"
    assert d.quote_alias("alias") == "[alias]"


@pytest.mark.parametrize(
    "adapter_cls",
    [
        _FirebirdCursorAdapter,
        _MonetDBCursorAdapter,
        _H2CursorAdapter,
        _DerbyCursorAdapter,
        _SybaseCursorAdapter,
        _InformixCursorAdapter,
    ],
)
def test_adapters_cursor_without_close_or_fetchall(adapter_cls):
    mock_cur = MagicMock(spec=["execute", "description"])
    mock_cur.description = None
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    adapter = adapter_cls(mock_conn)
    adapter.execute("SELECT 1;")
    assert adapter.description is None
    assert adapter.fetchall() == []


@pytest.mark.parametrize(
    "conn_cls",
    [
        FirebirdConnector,
        MonetDBConnector,
        H2Connector,
        DerbyConnector,
        SybaseConnector,
        InformixConnector,
    ],
)
def test_sync_connectors_cursor_without_close(conn_cls):
    mock_cur = MagicMock(spec=["execute"])
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    c = conn_cls(connection=mock_conn)
    with c.get_cursor() as cur:
        assert cur is mock_cur


def test_async_connectors_connect_success():
    async def _test():
        mock_conn = MagicMock()
        mock_driver = MagicMock()
        mock_driver.connect.return_value = mock_conn

        # Firebird
        with patch.dict(sys.modules, {"firebird.driver": mock_driver}):
            c = AsyncFirebirdConnector()
            assert await c.connect() is mock_conn

        # MonetDB
        with patch.dict(sys.modules, {"pymonetdb": mock_driver}):
            c = AsyncMonetDBConnector()
            assert await c.connect() is mock_conn

        # H2
        with patch.dict(sys.modules, {"jaydebeapi": mock_driver}):
            c = AsyncH2Connector()
            assert await c.connect() is mock_conn

        # Derby
        with patch.dict(sys.modules, {"jaydebeapi": mock_driver}):
            c = AsyncDerbyConnector()
            assert await c.connect() is mock_conn

        # Sybase
        with patch.dict(sys.modules, {"pyodbc": mock_driver}):
            c = AsyncSybaseConnector()
            assert await c.connect() is mock_conn

        # Informix
        with patch.dict(sys.modules, {"ibm_db_dbi": mock_driver}):
            c = AsyncInformixConnector()
            assert await c.connect() is mock_conn

    asyncio.run(_test())


def test_async_connectors_cursor_without_close():
    async def _test():
        for async_cls, mod_name, fn_name in [
            (AsyncFirebirdConnector, "firebird", "introspect_firebird"),
            (AsyncMonetDBConnector, "monetdb", "introspect_monetdb"),
            (AsyncH2Connector, "h2", "introspect_h2"),
            (AsyncDerbyConnector, "derby", "introspect_derby"),
            (AsyncSybaseConnector, "sybase", "introspect_sybase"),
            (AsyncInformixConnector, "informix", "introspect_informix"),
        ]:
            mock_cur = MagicMock(spec=["execute", "description", "fetchall"])
            mock_cur.description = [("x", 0)]
            mock_cur.fetchall.return_value = [[1]]
            mock_conn = MagicMock()
            mock_conn.cursor.return_value = mock_cur

            c = async_cls(connection=mock_conn)
            cols, _rows, _ = await c.execute_raw("SELECT 1;")
            assert cols == ["x"]

            with patch(
                f"query_builder.connectors.{mod_name}.{fn_name}",
                return_value={"tables": {}},
            ):
                snap = await c.introspect_schema()
                assert snap == {"tables": {}}

    asyncio.run(_test())
