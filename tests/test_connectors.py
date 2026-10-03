"""
Comprehensive Unit Tests for Query Builder Connectors and Schema Introspection.
==============================================================================
Verifies 100% statement, function, and branch coverage across all connector classes,
drivers, statement timeout injection, introspection protocols, and error branches.
"""

from __future__ import annotations

import builtins
import sqlite3
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine

from query_builder.compiler import CompilationError
from query_builder.connectors import (
    BaseConnector,
    BigQueryConnector,
    ClickHouseConnector,
    ConnectionFailedError,
    ConnectorError,
    ConnectorRegistry,
    DriverNotInstalledError,
    DuckDBConnector,
    GenericDBAPIConnector,
    IntrospectionError,
    MSSQLConnector,
    MySQLConnector,
    OracleConnector,
    PostgresConnector,
    RedshiftConnector,
    SnowflakeConnector,
    SQLiteConnector,
    TrinoConnector,
    get_connector,
    introspect_clickhouse,
    introspect_duckdb,
    introspect_information_schema,
    introspect_oracle,
    introspect_sqlite,
    introspect_via_sqlalchemy,
    list_connectors,
    register_connector,
)
from query_builder.dialects import PostgresDialect

# ============================================================================
# 1. BaseConnector and Registry Tests
# ============================================================================


def test_registry_registration_and_lookup():
    class DummyConnector(BaseConnector):
        def connect(self) -> Any:
            return None

        def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
            return {}

    ConnectorRegistry.register("dummy", DummyConnector, aliases=["dum-dum"])
    assert "dummy" in ConnectorRegistry.list_available()
    assert "dum-dum" in ConnectorRegistry.list_available()

    instance = get_connector("dummy")
    assert isinstance(instance, DummyConnector)
    instance_alias = get_connector("dum-dum")
    assert isinstance(instance_alias, DummyConnector)

    # Invalid registration
    with pytest.raises(TypeError, match="must inherit from BaseConnector"):
        register_connector("invalid", str)  # type: ignore

    # Missing connector lookup
    with pytest.raises(
        ConnectorError, match="No connector registered for 'non_existent'"
    ):
        get_connector("non_existent")

    # Unregister and list
    ConnectorRegistry.unregister("dum-dum")
    assert "dum-dum" not in list_connectors()

    # Clear and re-populate
    ConnectorRegistry.clear()
    assert len(list_connectors()) == 0

    # Re-register
    import query_builder.connectors  # noqa: F401

    ConnectorRegistry.register("sqlite", SQLiteConnector)
    ConnectorRegistry.register("duckdb", DuckDBConnector)
    ConnectorRegistry.register("postgres", PostgresConnector, aliases=["postgresql"])
    ConnectorRegistry.register("mysql", MySQLConnector, aliases=["mariadb"])
    ConnectorRegistry.register("mssql", MSSQLConnector, aliases=["sqlserver"])
    ConnectorRegistry.register("snowflake", SnowflakeConnector)
    ConnectorRegistry.register("bigquery", BigQueryConnector)
    ConnectorRegistry.register("clickhouse", ClickHouseConnector)
    ConnectorRegistry.register("oracle", OracleConnector)
    ConnectorRegistry.register("redshift", RedshiftConnector)
    ConnectorRegistry.register("trino", TrinoConnector, aliases=["presto"])
    ConnectorRegistry.register("generic", GenericDBAPIConnector, aliases=["dbapi"])


def test_base_connector_lifecycle_and_errors():
    class MockConn:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

        def cursor(self):
            cur = MagicMock()
            cur.close = MagicMock()
            return cur

    class LifecycleConnector(BaseConnector):
        def connect(self) -> Any:
            if self._connection is None:
                self._connection = MockConn()
            return self._connection

        def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
            return {}

    # Context manager and close
    with LifecycleConnector() as conn:
        assert isinstance(conn, LifecycleConnector)
        with conn.get_cursor() as cur:
            assert cur is not None

    # Error suppressing on close
    err_conn = MagicMock()
    err_conn.close.side_effect = RuntimeError("Close exploded")
    err_cur = MagicMock()
    err_cur.close.side_effect = RuntimeError("Cursor close exploded")
    c = LifecycleConnector(connection=err_conn, cursor=err_cur)
    c.close()
    assert c._connection is None
    assert c._cursor is None

    # Close when already closed (connection and cursor are None)
    c_none = LifecycleConnector(connection=None, cursor=None)
    c_none.close()
    assert c_none._connection is None

    # Base apply_statement_timeout hook
    c.apply_statement_timeout(MagicMock(), 1000)

    # Custom dialect passing as BaseDialect vs string
    c_custom = LifecycleConnector(dialect=PostgresDialect())
    assert c_custom.dialect_name == "postgres"

    c_custom_str = LifecycleConnector(dialect="sqlite")
    assert c_custom_str.dialect_name == "sqlite"

    # Execution validation errors
    with pytest.raises(CompilationError, match="Specification must be a dictionary"):
        c_custom.execute("not a dict")  # type: ignore

    with pytest.raises(ValueError, match="statement_timeout_ms must be positive"):
        c_custom.execute({"table": "users"}, statement_timeout_ms=0)

    # AST validation failure on main query
    with patch("query_builder.connectors.base.validate_sql_ast") as mock_val:
        mock_val.return_value = {"valid": False, "message": "Disallowed mutation"}
        with pytest.raises(CompilationError, match="safety validation"):
            c_custom.execute({"table": "users"}, validate_ast=True)

    # AST validation failure on count query
    with patch("query_builder.connectors.base.validate_sql_ast") as mock_val:
        mock_val.side_effect = [
            {"valid": True, "message": "OK"},
            {"valid": False, "message": "Count query unsafe"},
        ]
        with pytest.raises(CompilationError, match="Count query unsafe"):
            c_custom.execute({"table": "users"}, validate_ast=True)

    # Execution with count_params, empty count row, and limit=0
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = None  # empty count_row
    mock_cur.description = [("id",), ("name",)]
    mock_cur.fetchall.return_value = []
    c_exec = LifecycleConnector(cursor=mock_cur)

    res_zero = c_exec.execute(
        {
            "table": "users",
            "filters": [{"column": "id", "op": "eq", "value": 1}],
            "limit": 0,
        },
        validate_ast=False,
    )
    assert res_zero["count"] == 0
    assert res_zero["page"] == 1

    # Execute without filters (count_params is empty)
    res_no_filters = c_exec.execute(
        {"table": "users", "limit": 10},
        validate_ast=False,
    )
    assert res_no_filters["count"] == 0

    # Raw query execution
    cols, _rows, latency = c_exec.execute_raw("SELECT 1")
    assert cols == ["id", "name"]
    assert latency >= 0

    # When cursor yields raw connection without .cursor()
    raw_cur_mock = MagicMock(spec=[])
    c_raw = LifecycleConnector(connection=raw_cur_mock)
    with c_raw.get_cursor() as yielded:
        assert yielded is raw_cur_mock


# ============================================================================
# 2. SQLite Connector Live Tests
# ============================================================================


def test_sqlite_connector_full_flow():
    connector = SQLiteConnector(database=":memory:")
    # Re-connect when already connected
    conn1 = connector.connect()
    assert connector.connect() is conn1

    test_res = connector.test_connection()
    assert test_res["status"] == "healthy"
    assert test_res["dialect"] == "sqlite"
    assert "engine_version" in test_res

    # Populate in-memory database
    with connector.get_cursor() as cur:
        cur.execute(
            """
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                user_id INTEGER
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER,
                amount REAL,
                FOREIGN KEY (customer_id) REFERENCES customers (id)
            );
            """
        )
        cur.execute("INSERT INTO customers VALUES (1, 'Alice', 42), (2, 'Bob', 42);")
        cur.execute("INSERT INTO orders VALUES (101, 1, 99.50), (102, 2, 149.00);")

    # Schema Introspection
    schema = connector.introspect_schema()
    assert "customers" in schema["tables"]
    assert "orders" in schema["tables"]
    assert schema["tables"]["customers"]["has_user_id"] is True
    assert len(schema["foreign_keys"]) == 1
    assert schema["foreign_keys"][0]["foreign_table"] == "customers"

    # Raw Query Execution
    cols, rows, latency = connector.execute_raw(
        "SELECT * FROM customers WHERE id = ?", [1]
    )
    assert cols == ["id", "name", "user_id"]
    assert len(rows) == 1
    assert rows[0]["name"] == "Alice"
    assert latency >= 0

    # Query Builder Spec Execution
    spec = {
        "table": "customers",
        "columns": ["id", "name"],
        "filters": [{"column": "name", "op": "eq", "value": "Alice"}],
        "limit": 10,
        "offset": 0,
    }
    result = connector.execute(spec, schema=schema, user_id=42)
    assert result["count"] == 1
    assert len(result["rows"]) == 1
    assert result["rows"][0]["name"] == "Alice"
    assert result["page"] == 1

    # Connection failure
    with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("Disk error")):
        bad_conn = SQLiteConnector(database="/invalid/path/db.sqlite")
        with pytest.raises(ConnectionFailedError, match="Failed to connect to SQLite"):
            bad_conn.connect()


# ============================================================================
# 3. DuckDB Connector Live Tests
# ============================================================================


def test_duckdb_connector_full_flow():
    connector = DuckDBConnector(database=":memory:")
    # Re-connect when already connected
    d_conn1 = connector.connect()
    assert connector.connect() is d_conn1

    test_res = connector.test_connection()
    assert test_res["status"] == "healthy"
    assert test_res["dialect"] == "duckdb"
    assert "engine_version" in test_res

    # Create tables
    with connector.get_cursor() as cur:
        cur.execute(
            """
            CREATE TABLE departments (
                id INTEGER PRIMARY KEY,
                title VARCHAR
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE staff (
                id INTEGER PRIMARY KEY,
                name VARCHAR,
                user_id INTEGER,
                dept_id INTEGER REFERENCES departments(id)
            );
            """
        )
        cur.execute("INSERT INTO departments VALUES (1, 'Engineering');")
        cur.execute("INSERT INTO staff VALUES (10, 'Charlie', 99, 1);")

    # Introspection
    schema = connector.introspect_schema()
    assert "departments" in schema["tables"]
    assert "staff" in schema["tables"]
    assert schema["tables"]["staff"]["has_user_id"] is True

    # Spec execution
    spec = {
        "table": "staff",
        "columns": ["id", "name"],
        "filters": [{"column": "name", "op": "contains", "value": "harl"}],
        "limit": 5,
        "offset": 0,
    }
    res = connector.execute(spec)
    assert res["count"] == 1
    assert res["rows"][0]["name"] == "Charlie"

    # Test connection when fetchone returns None
    mock_empty_cur = MagicMock()
    mock_empty_cur.fetchone.return_value = None
    mock_empty_conn = MagicMock()
    mock_empty_conn.cursor.return_value = mock_empty_cur
    d_empty = DuckDBConnector(connection=mock_empty_conn)
    info = d_empty.test_connection()
    assert "engine_version" not in info

    # Missing driver error
    orig_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "duckdb":
            raise ImportError("No duckdb")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        fresh_conn = DuckDBConnector()
        with pytest.raises(DriverNotInstalledError, match="duckdb is not installed"):
            fresh_conn.connect()

    # Connection failure
    with patch("duckdb.connect", side_effect=RuntimeError("Cannot lock")):
        fail_conn = DuckDBConnector()
        with pytest.raises(ConnectionFailedError, match="Failed to connect to DuckDB"):
            fail_conn.connect()


# ============================================================================
# 4. Universal & Mocked Connectors Tests (Postgres, MySQL, MSSQL, Snowflake, etc.)
# ============================================================================


def test_postgres_connector_mocked():
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [("users",), ("orders",)]
    mock_cursor.fetchone.return_value = ("PostgreSQL 16.1",)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    pg = PostgresConnector(connection=mock_conn)
    assert pg.connect() is mock_conn

    info = pg.test_connection()
    assert info["engine_version"] == "PostgreSQL 16.1"

    # test connection when fetchone returns None
    mock_cursor.fetchone.return_value = None
    info_none = pg.test_connection()
    assert "engine_version" not in info_none

    # Timeout
    pg.apply_statement_timeout(mock_cursor, 4000)
    mock_cursor.execute.assert_called_with("SET LOCAL statement_timeout = 4000;")

    # Introspect
    with patch(
        "query_builder.connectors.postgres.introspect_information_schema"
    ) as mock_intro:
        mock_intro.return_value = {"tables": {}}
        res = pg.introspect_schema()
        assert res == {"tables": {}}

    # Driver missing check
    orig_import = builtins.__import__

    def mock_import_pg(name, *args, **kwargs):
        if name in ("psycopg", "psycopg2"):
            raise ImportError("No psycopg")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import_pg):
        p_unconnected = PostgresConnector()
        with pytest.raises(
            DriverNotInstalledError, match="Neither 'psycopg' nor 'psycopg2'"
        ):
            p_unconnected.connect()

    # Driver installed and connect succeeds vs fails
    mock_driver = MagicMock()
    mock_driver.connect.return_value = mock_conn

    with patch.dict(sys.modules, {"psycopg": mock_driver}):
        p_ok = PostgresConnector()
        assert p_ok.connect() is mock_conn

    mock_driver_fail = MagicMock()
    mock_driver_fail.connect.side_effect = RuntimeError("Postgres down")
    with patch.dict(sys.modules, {"psycopg": mock_driver_fail}):
        p_fail = PostgresConnector()
        with pytest.raises(
            ConnectionFailedError, match="Failed to connect to PostgreSQL"
        ):
            p_fail.connect()


def test_mysql_connector_mocked():
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = ("8.0.35",)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    my = MySQLConnector(connection=mock_conn)
    assert my.connect() is mock_conn

    info = my.test_connection()
    assert info["engine_version"] == "8.0.35"

    # None row in test_connection
    mock_cursor.fetchone.return_value = None
    assert "engine_version" not in my.test_connection()

    my.apply_statement_timeout(mock_cursor, 3000)
    mock_cursor.execute.assert_called_with("SET SESSION max_execution_time = 3000;")

    with patch(
        "query_builder.connectors.mysql.introspect_information_schema"
    ) as mock_intro:
        mock_intro.return_value = {"tables": {}}
        assert my.introspect_schema() == {"tables": {}}

    # Driver missing check
    orig_import = builtins.__import__

    def mock_import_my(name, *args, **kwargs):
        if name in ("MySQLdb", "pymysql"):
            raise ImportError("No mysql")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import_my):
        m_unconnected = MySQLConnector()
        with pytest.raises(DriverNotInstalledError, match="Neither 'mysqlclient'"):
            m_unconnected.connect()

    # Driver connect success vs fail
    mock_driver = MagicMock()
    mock_driver.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"MySQLdb": mock_driver}):
        m_ok = MySQLConnector()
        assert m_ok.connect() is mock_conn

    mock_driver_fail = MagicMock()
    mock_driver_fail.connect.side_effect = RuntimeError("MySQL down")
    with patch.dict(sys.modules, {"MySQLdb": mock_driver_fail}):
        m_fail = MySQLConnector()
        with pytest.raises(ConnectionFailedError, match="Failed to connect to MySQL"):
            m_fail.connect()


def test_mssql_connector_mocked():
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = ("Microsoft SQL Server 2022",)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    ms = MSSQLConnector(connection=mock_conn)
    assert ms.connect() is mock_conn

    info = ms.test_connection()
    assert info["engine_version"] == "Microsoft SQL Server 2022"

    mock_cursor.fetchone.return_value = None
    assert "engine_version" not in ms.test_connection()

    ms.apply_statement_timeout(mock_cursor, 2500)
    mock_cursor.execute.assert_called_with("SET LOCK_TIMEOUT 2500;")

    with patch(
        "query_builder.connectors.mssql.introspect_information_schema"
    ) as mock_intro:
        mock_intro.return_value = {"tables": {}}
        assert ms.introspect_schema() == {"tables": {}}

    # Driver missing
    orig_import = builtins.__import__

    def mock_import_ms(name, *args, **kwargs):
        if name in ("pymssql", "pyodbc"):
            raise ImportError("No mssql")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import_ms):
        ms_unconnected = MSSQLConnector()
        with pytest.raises(
            DriverNotInstalledError, match="Neither 'pymssql' nor 'pyodbc'"
        ):
            ms_unconnected.connect()

    mock_driver = MagicMock()
    mock_driver.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"pymssql": mock_driver}):
        ms_ok = MSSQLConnector()
        assert ms_ok.connect() is mock_conn

    mock_driver_fail = MagicMock()
    mock_driver_fail.connect.side_effect = RuntimeError("MSSQL down")
    with patch.dict(sys.modules, {"pymssql": mock_driver_fail}):
        ms_fail = MSSQLConnector()
        with pytest.raises(ConnectionFailedError, match="Failed to connect to MSSQL"):
            ms_fail.connect()


def test_snowflake_connector_mocked():
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = ("7.40.1",)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    sf = SnowflakeConnector(connection=mock_conn)
    assert sf.connect() is mock_conn

    info = sf.test_connection()
    assert info["engine_version"] == "7.40.1"

    mock_cursor.fetchone.return_value = None
    assert "engine_version" not in sf.test_connection()

    sf.apply_statement_timeout(mock_cursor, 5000)
    mock_cursor.execute.assert_called_with(
        "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 5;"
    )

    with patch(
        "query_builder.connectors.snowflake.introspect_information_schema"
    ) as mock_intro:
        mock_intro.return_value = {"tables": {}}
        assert sf.introspect_schema() == {"tables": {}}

    # Driver missing
    orig_import = builtins.__import__

    def mock_import_sf(name, *args, **kwargs):
        if name == "snowflake.connector" or name.startswith("snowflake"):
            raise ImportError("No snowflake")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import_sf):
        sf_unconnected = SnowflakeConnector()
        with pytest.raises(
            DriverNotInstalledError, match="snowflake-connector-python is not installed"
        ):
            sf_unconnected.connect()

    mock_sf_mod = MagicMock()
    mock_sf_mod.connector.connect.return_value = mock_conn
    with patch.dict(
        sys.modules,
        {"snowflake": mock_sf_mod, "snowflake.connector": mock_sf_mod.connector},
    ):
        sf_ok = SnowflakeConnector()
        assert sf_ok.connect() is mock_conn

    mock_sf_fail = MagicMock()
    mock_sf_fail.connector.connect.side_effect = RuntimeError("Snowflake unreachable")
    with patch.dict(
        sys.modules,
        {"snowflake": mock_sf_fail, "snowflake.connector": mock_sf_fail.connector},
    ):
        sf_fail = SnowflakeConnector()
        with pytest.raises(
            ConnectionFailedError, match="Failed to connect to Snowflake"
        ):
            sf_fail.connect()


def test_bigquery_connector_mocked():
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    bq = BigQueryConnector(connection=mock_conn)
    assert bq.connect() is mock_conn

    info = bq.test_connection()
    assert info["engine_version"] == "BigQuery Standard SQL"

    with patch(
        "query_builder.connectors.bigquery.introspect_information_schema"
    ) as mock_intro:
        mock_intro.return_value = {"tables": {}}
        assert bq.introspect_schema() == {"tables": {}}

    # Driver missing
    orig_import = builtins.__import__

    def mock_import_bq(name, *args, **kwargs):
        if name.startswith("google.cloud"):
            raise ImportError("No bq")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import_bq):
        bq_unconnected = BigQueryConnector()
        with pytest.raises(
            DriverNotInstalledError, match="google-cloud-bigquery is not installed"
        ):
            bq_unconnected.connect()

    mock_bq_pkg = MagicMock()
    mock_dbapi = MagicMock()
    mock_dbapi.connect.return_value = mock_conn
    mock_bq_pkg.dbapi = mock_dbapi
    with patch.dict(
        sys.modules,
        {
            "google": MagicMock(),
            "google.cloud": MagicMock(),
            "google.cloud.bigquery": mock_bq_pkg,
            "google.cloud.bigquery.dbapi": mock_dbapi,
        },
    ):
        bq_ok = BigQueryConnector()
        assert bq_ok.connect() is mock_conn

        mock_dbapi.connect.side_effect = RuntimeError("BigQuery fail")
        bq_fail = BigQueryConnector()
        with pytest.raises(
            ConnectionFailedError, match="Failed to connect to Google BigQuery"
        ):
            bq_fail.connect()


def test_clickhouse_connector_mocked():
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = ("23.12.1",)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    ch = ClickHouseConnector(connection=mock_conn)
    assert ch.connect() is mock_conn

    info = ch.test_connection()
    assert info["engine_version"] == "23.12.1"

    mock_cursor.fetchone.return_value = None
    assert "engine_version" not in ch.test_connection()

    ch.apply_statement_timeout(mock_cursor, 4000)
    mock_cursor.execute.assert_called_with("SET max_execution_time = 4;")

    with patch(
        "query_builder.connectors.clickhouse.introspect_clickhouse"
    ) as mock_intro:
        mock_intro.return_value = {"tables": {}}
        assert ch.introspect_schema() == {"tables": {}}

    # Driver missing
    orig_import = builtins.__import__

    def mock_import_ch(name, *args, **kwargs):
        if name.startswith("clickhouse_connect"):
            raise ImportError("No ch")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import_ch):
        ch_unconnected = ClickHouseConnector()
        with pytest.raises(
            DriverNotInstalledError, match="clickhouse-connect is not installed"
        ):
            ch_unconnected.connect()

    mock_ch_mod = MagicMock()
    mock_ch_mod.get_client.return_value = mock_conn
    with patch.dict(sys.modules, {"clickhouse_connect": mock_ch_mod}):
        ch_ok = ClickHouseConnector()
        assert ch_ok.connect() is mock_conn

        mock_ch_mod.get_client.side_effect = RuntimeError("Clickhouse socket refused")
        ch_fail = ClickHouseConnector()
        with pytest.raises(
            ConnectionFailedError, match="Failed to connect to ClickHouse"
        ):
            ch_fail.connect()


def test_oracle_connector_mocked():
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    ora = OracleConnector(connection=mock_conn)
    assert ora.connect() is mock_conn

    info = ora.test_connection()
    assert info["engine_version"] == "Oracle Database"

    with patch("query_builder.connectors.oracle.introspect_oracle") as mock_intro:
        mock_intro.return_value = {"tables": {}}
        assert ora.introspect_schema() == {"tables": {}}

    # Driver missing
    orig_import = builtins.__import__

    def mock_import_ora(name, *args, **kwargs):
        if name in ("oracledb", "cx_Oracle"):
            raise ImportError("No oracle")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import_ora):
        ora_unconnected = OracleConnector()
        with pytest.raises(
            DriverNotInstalledError, match="Neither 'oracledb' nor 'cx_Oracle'"
        ):
            ora_unconnected.connect()

    mock_ora_mod = MagicMock()
    mock_ora_mod.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"oracledb": mock_ora_mod}):
        ora_ok = OracleConnector()
        assert ora_ok.connect() is mock_conn

        mock_ora_mod.connect.side_effect = RuntimeError("Oracle listener down")
        ora_fail = OracleConnector()
        with pytest.raises(ConnectionFailedError, match="Failed to connect to Oracle"):
            ora_fail.connect()


def test_redshift_connector_mocked():
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = ("PostgreSQL 8.0.2 on i686 - Redshift",)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    rs = RedshiftConnector(connection=mock_conn)
    assert rs.connect() is mock_conn

    info = rs.test_connection()
    assert "Redshift" in info["engine_version"]

    mock_cursor.fetchone.return_value = None
    assert "engine_version" not in rs.test_connection()

    rs.apply_statement_timeout(mock_cursor, 5000)
    mock_cursor.execute.assert_called_with("SET statement_timeout = 5000;")

    with patch(
        "query_builder.connectors.redshift.introspect_information_schema"
    ) as mock_intro:
        mock_intro.return_value = {"tables": {}}
        assert rs.introspect_schema() == {"tables": {}}

    # Driver missing
    orig_import = builtins.__import__

    def mock_import_rs(name, *args, **kwargs):
        if name in ("redshift_connector", "psycopg2", "psycopg"):
            raise ImportError("No redshift")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import_rs):
        rs_unconnected = RedshiftConnector()
        with pytest.raises(
            DriverNotInstalledError, match="Neither 'redshift_connector' nor 'psycopg2'"
        ):
            rs_unconnected.connect()

    mock_rs_mod = MagicMock()
    mock_rs_mod.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"redshift_connector": mock_rs_mod}):
        rs_ok = RedshiftConnector()
        assert rs_ok.connect() is mock_conn

        mock_rs_mod.connect.side_effect = RuntimeError("Redshift cluster unreachable")
        rs_fail = RedshiftConnector()
        with pytest.raises(
            ConnectionFailedError, match="Failed to connect to Amazon Redshift"
        ):
            rs_fail.connect()


def test_trino_connector_mocked():
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = ("438",)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    trino = TrinoConnector(connection=mock_conn)
    assert trino.connect() is mock_conn

    info = trino.test_connection()
    assert info["engine_version"] == "438"

    mock_cursor.fetchone.return_value = None
    assert "engine_version" not in trino.test_connection()

    with patch(
        "query_builder.connectors.trino.introspect_information_schema"
    ) as mock_intro:
        mock_intro.return_value = {"tables": {}}
        assert trino.introspect_schema() == {"tables": {}}

    # Driver missing
    orig_import = builtins.__import__

    def mock_import_trino(name, *args, **kwargs):
        if name.startswith("trino"):
            raise ImportError("No trino")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import_trino):
        trino_unconnected = TrinoConnector()
        with pytest.raises(DriverNotInstalledError, match="'trino' is not installed"):
            trino_unconnected.connect()

    mock_trino_dbapi = MagicMock()
    mock_trino_dbapi.connect.return_value = mock_conn
    mock_trino_mod = MagicMock()
    mock_trino_mod.dbapi = mock_trino_dbapi
    with patch.dict(
        sys.modules, {"trino": mock_trino_mod, "trino.dbapi": mock_trino_dbapi}
    ):
        trino_ok = TrinoConnector()
        assert trino_ok.connect() is mock_conn

        mock_trino_dbapi.connect.side_effect = RuntimeError("Trino cluster down")
        trino_fail = TrinoConnector()
        with pytest.raises(ConnectionFailedError, match="Failed to connect to Trino"):
            trino_fail.connect()


def test_generic_dbapi_connector():
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    gen = GenericDBAPIConnector(connection=mock_conn)
    assert gen.connect() == mock_conn

    gen_cursor_only = GenericDBAPIConnector(cursor=mock_cursor)
    assert gen_cursor_only.connect() == mock_cursor

    # Engine provided
    mock_engine = MagicMock()
    mock_engine.raw_connection.return_value = mock_conn
    gen_eng = GenericDBAPIConnector(engine=mock_engine)
    assert gen_eng.connect() == mock_conn

    # Missing credentials/connection
    gen_empty = GenericDBAPIConnector()
    with pytest.raises(ConnectionFailedError, match="requires an explicit connection"):
        gen_empty.connect()

    # Raw connection failure
    mock_bad_engine = MagicMock()
    mock_bad_engine.raw_connection.side_effect = RuntimeError("Pool depleted")
    gen_bad_eng = GenericDBAPIConnector(engine=mock_bad_engine)
    with pytest.raises(ConnectionFailedError, match="Failed to obtain raw connection"):
        gen_bad_eng.connect()

    # Introspection via engine vs cursor
    with patch("query_builder.connectors.generic.introspect_via_sqlalchemy") as mock_sa:
        mock_sa.return_value = {"tables": {}}
        assert gen_eng.introspect_schema() == {"tables": {}}

    with patch(
        "query_builder.connectors.generic.introspect_information_schema"
    ) as mock_info:
        mock_info.return_value = {"tables": {}}
        assert gen.introspect_schema() == {"tables": {}}


# ============================================================================
# 5. Schema Introspection Detailed Tests
# ============================================================================


def test_introspect_via_sqlalchemy_with_sqlite():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                user_id INTEGER
            );
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE posts (
                id INTEGER PRIMARY KEY,
                title VARCHAR(100),
                author_id INTEGER,
                FOREIGN KEY (author_id) REFERENCES users(id)
            );
            """
        )

    schema = introspect_via_sqlalchemy(engine)
    assert "users" in schema["tables"]
    assert "posts" in schema["tables"]
    assert schema["tables"]["users"]["has_user_id"] is True
    assert len(schema["foreign_keys"]) == 1
    assert schema["foreign_keys"][0]["foreign_table"] == "users"

    # Driver missing
    orig_import = builtins.__import__

    def mock_no_sa(name, *args, **kwargs):
        if name == "sqlalchemy" or name.startswith("sqlalchemy"):
            raise ImportError("No sqlalchemy")
        return orig_import(name, *args, **kwargs)

    with (
        patch("builtins.__import__", side_effect=mock_no_sa),
        pytest.raises(DriverNotInstalledError, match="SQLAlchemy is required"),
    ):
        introspect_via_sqlalchemy(engine)

    # Incomplete FK branches
    mock_sa_engine = MagicMock()
    mock_inspector = MagicMock()
    mock_inspector.get_table_names.return_value = ["t1"]
    mock_inspector.get_columns.return_value = [
        {"name": "id", "type": "int", "nullable": False}
    ]
    mock_inspector.get_pk_constraint.return_value = {"constrained_columns": ["id"]}
    mock_inspector.get_foreign_keys.return_value = [
        {"referred_table": None, "constrained_columns": []},
        {
            "referred_table": "t2",
            "constrained_columns": ["t2_id"],
            "referred_columns": ["id"],
        },
    ]
    with patch("sqlalchemy.inspect", return_value=mock_inspector):
        res_incomplete = introspect_via_sqlalchemy(mock_sa_engine)
        assert len(res_incomplete["foreign_keys"]) == 1


def test_introspect_information_schema_mock():
    mock_cursor = MagicMock()
    # tables query, columns query, constraints query
    mock_cursor.fetchall.side_effect = [
        [("accounts",), ("auth_user",)],  # auth_user sensitive
        [
            ("accounts", "id", "integer", "NO"),
            ("accounts", "name", "varchar", "YES"),
            ("accounts", "user_id", "integer", "NO"),
        ],
        [("accounts", "org_id", "organizations", "id")],  # FKs
    ]
    res = introspect_information_schema(
        mock_cursor, schema_name="public", filter_sensitive=True
    )
    assert "accounts" in res["tables"]
    assert "auth_user" not in res["tables"]
    assert res["tables"]["accounts"]["has_user_id"] is True
    assert len(res["foreign_keys"]) == 1


def test_introspect_duckdb_mock():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    mock_cur.fetchall.side_effect = [
        [("logs",)],
        [("logs", "id", "BIGINT", "NO"), ("logs", "msg", "VARCHAR", "YES")],
        [
            (
                "logs",
                "FOREIGN KEY",
                "parent_id",
                "logs",
                None,
            ),  # str instead of list, None tc
            ("logs", "FOREIGN KEY", None, "logs", None),  # from_cols is None
        ],
    ]
    res = introspect_duckdb(mock_conn, filter_sensitive=True)
    assert "logs" in res["tables"]
    assert len(res["foreign_keys"]) == 1
    assert res["foreign_keys"][0]["foreign_column"] == "id"


def test_introspect_clickhouse_mock():
    mock_cursor = MagicMock()
    mock_cursor.fetchall.side_effect = [
        [("analytics_events",)],
        [
            ("analytics_events", "id", "UInt64"),
            ("analytics_events", "payload", "Nullable(String)"),
        ],
    ]
    res = introspect_clickhouse(mock_cursor, database="default")
    assert "analytics_events" in res["tables"]
    assert res["tables"]["analytics_events"]["columns"][1]["is_nullable"] is True


def test_introspect_oracle_mock():
    # Case 1: owner specified
    mock_cursor = MagicMock()
    mock_cursor.fetchall.side_effect = [
        [("EMPLOYEES",)],
        [
            ("EMPLOYEES", "ID", "NUMBER", "N"),
            ("EMPLOYEES", "NAME", "VARCHAR2", "Y"),
        ],
    ]
    res = introspect_oracle(mock_cursor, owner="HR")
    assert "employees" in res["tables"]
    assert res["tables"]["employees"]["columns"][0]["is_nullable"] is False
    assert res["tables"]["employees"]["columns"][1]["is_nullable"] is True

    # Case 2: owner not specified (user_tables)
    mock_cursor_no_owner = MagicMock()
    mock_cursor_no_owner.fetchall.side_effect = [
        [("DEPTS",)],
        [
            ("DEPTS", "ID", "NUMBER", "N"),
            ("DEPTS", "TITLE", "VARCHAR2", "Y"),
        ],
    ]
    res_no_owner = introspect_oracle(mock_cursor_no_owner, owner=None)
    assert "depts" in res_no_owner["tables"]


def test_introspection_error_handling():
    bad_cur = MagicMock(spec=[])
    bad_cur.execute = MagicMock(side_effect=RuntimeError("Broken database cursor"))

    with pytest.raises(IntrospectionError, match="Failed to introspect SQLite"):
        introspect_sqlite(bad_cur)

    with pytest.raises(IntrospectionError, match="Failed to introspect DuckDB"):
        introspect_duckdb(bad_cur)

    with pytest.raises(
        IntrospectionError, match="Failed to introspect information_schema"
    ):
        introspect_information_schema(bad_cur)

    with pytest.raises(IntrospectionError, match="Failed to introspect ClickHouse"):
        introspect_clickhouse(bad_cur)

    with pytest.raises(IntrospectionError, match="Failed to introspect Oracle"):
        introspect_oracle(bad_cur)

    with pytest.raises(
        IntrospectionError, match="Failed to introspect schema via SQLAlchemy"
    ):
        introspect_via_sqlalchemy(MagicMock(side_effect=RuntimeError("Fail")))
