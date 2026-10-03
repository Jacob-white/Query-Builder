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
    AthenaConnector,
    BaseConnector,
    BigQueryConnector,
    ClickHouseConnector,
    CockroachConnector,
    ConnectionFailedError,
    ConnectorError,
    ConnectorRegistry,
    DatabricksConnector,
    DataFusionConnector,
    DriverNotInstalledError,
    DuckDBConnector,
    DynamoDBConnector,
    ElasticsearchConnector,
    GenericDBAPIConnector,
    IntrospectionError,
    MSSQLConnector,
    MySQLConnector,
    OracleConnector,
    PolarsConnector,
    PostgresConnector,
    QuestDBConnector,
    RedshiftConnector,
    SnowflakeConnector,
    SpannerConnector,
    SQLiteConnector,
    TimescaleConnector,
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
    import importlib

    import query_builder.connectors

    importlib.reload(query_builder.connectors)
    assert "sqlite" in list_connectors()
    assert "polars" in list_connectors()
    assert "databricks" in list_connectors()
    assert "spark" in list_connectors()
    assert "athena" in list_connectors()
    assert "datafusion" in list_connectors()
    assert "timescaledb" in list_connectors()
    assert "cockroachdb" in list_connectors()
    assert "spanner" in list_connectors()
    assert "questdb" in list_connectors()
    assert "elasticsearch" in list_connectors()
    assert "dynamodb" in list_connectors()


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


# ============================================================================
# 8. Expanded Connectors Suite
# ============================================================================


def test_polars_connector_full():
    import polars as pl

    df = pl.DataFrame(
        {
            "id": [1, 2, 3],
            "name": ["Alice", "Bob", "Charlie"],
            "user_id": [10, 10, 20],
        }
    )
    conn = PolarsConnector(tables={"users": df})
    # connect caching
    ctx = conn.connect()
    assert conn.connect() is ctx

    # test_connection
    info = conn.test_connection()
    assert info["status"] == "healthy"
    assert "Polars" in info["engine_version"]

    # introspect_schema (with schema on table df)
    schema = conn.introspect_schema()
    assert "users" in schema["tables"]
    users_tbl = schema["tables"]["users"]
    assert users_tbl["has_user_id"] is True
    assert users_tbl["columns"][0]["is_primary"] is True

    # introspect_schema (fallback discovery when table not in _tables)
    conn_fallback = PolarsConnector()
    fallback_ctx = conn_fallback.connect()
    fallback_ctx.register(
        "orders", pl.DataFrame({"id": [101], "user_id": [10], "amount": [99.5]})
    )
    schema_fb = conn_fallback.introspect_schema()
    assert "orders" in schema_fb["tables"]
    assert schema_fb["tables"]["orders"]["has_user_id"] is True

    # introspect_schema error branch
    with (
        patch.object(ctx, "tables", side_effect=RuntimeError("tables fail")),
        pytest.raises(IntrospectionError, match="Failed to introspect Polars"),
    ):
        conn.introspect_schema()

    # execute normal with limit/offset
    res = conn.execute({"table": "users", "limit": 2, "offset": 0})
    assert res["count"] == 3
    assert len(res["rows"]) == 2
    assert res["page"] == 1
    assert res["dialect"] == "polars"

    # execute with limit=0
    res0 = conn.execute({"table": "users", "limit": 0})
    assert res0["count"] == 3
    assert res0["page"] == 1

    # execute with filter (string & int params)
    res_f = conn.execute(
        {
            "table": "users",
            "filters": [
                {"column": "name", "op": "eq", "value": "Alice"},
                {"column": "id", "op": "eq", "value": 1},
            ],
        }
    )
    assert res_f["count"] == 1
    assert res_f["rows"][0]["name"] == "Alice"

    # execute with empty count_df height=0
    mock_empty_count = pl.DataFrame()
    with patch.object(ctx, "execute") as mock_exec:
        mock_exec.return_value.collect.side_effect = [
            mock_empty_count,
            pl.DataFrame({"id": [1]}),
        ]
        res_empty = conn.execute({"table": "users"})
        assert res_empty["count"] == 0

    # execute spec validation error
    with pytest.raises(CompilationError, match="Specification must be a dictionary"):
        conn.execute("invalid")  # type: ignore

    # AST validation failure on main query
    with (
        patch(
            "query_builder.connectors.polars.validate_sql_ast",
            return_value={"valid": False, "message": "Disallowed query"},
        ),
        pytest.raises(CompilationError, match="safety validation"),
    ):
        conn.execute({"table": "users"})

    # AST validation failure on count query
    with (
        patch(
            "query_builder.connectors.polars.validate_sql_ast",
            side_effect=[
                {"valid": True, "message": "OK"},
                {"valid": False, "message": "Bad count query"},
            ],
        ),
        pytest.raises(CompilationError, match="Generated count query failed"),
    ):
        conn.execute({"table": "users"})

    # register_table
    conn.register_table("items", pl.DataFrame({"id": [100]}))
    assert "items" in conn._tables

    # execute with validate_ast=False
    res_no_ast = conn.execute({"table": "users"}, validate_ast=False)
    assert res_no_ast["count"] == 3

    # driver missing
    orig_import = builtins.__import__

    def mock_no_polars(name, *args, **kwargs):
        if name == "polars" or name.startswith("polars"):
            raise ImportError("No polars")
        return orig_import(name, *args, **kwargs)

    with (
        patch("builtins.__import__", side_effect=mock_no_polars),
        pytest.raises(DriverNotInstalledError, match="polars is not installed"),
    ):
        PolarsConnector().connect()

    # test_connection with driver missing
    mock_ctx_dummy = MagicMock()
    with patch("builtins.__import__", side_effect=mock_no_polars):
        info_no_polars = PolarsConnector(context=mock_ctx_dummy).test_connection()
        assert "engine_version" not in info_no_polars

    # connection failed
    with (
        patch("polars.SQLContext", side_effect=RuntimeError("SQLContext init failed")),
        pytest.raises(ConnectionFailedError, match="Failed to initialize Polars"),
    ):
        PolarsConnector().connect()


def test_datafusion_connector_full():
    mock_field_id = MagicMock()
    mock_field_id.name = "id"
    mock_field_id.type = "Int64"
    mock_field_id.nullable = False

    mock_field_user = MagicMock()
    mock_field_user.name = "user_id"
    mock_field_user.type = "Int64"
    mock_field_user.nullable = False

    mock_table = MagicMock()
    mock_table.schema.return_value = [mock_field_id, mock_field_user]

    mock_batch = MagicMock()
    mock_batch.schema.names = ["id", "user_id"]
    mock_batch.to_pylist.return_value = [{"id": 1, "user_id": 10}]

    mock_ctx = MagicMock()
    mock_ctx.table.return_value = mock_table

    mock_scalar = MagicMock()
    mock_scalar.as_py.return_value = 5
    mock_count_batch = [[mock_scalar]]

    mock_ctx.sql.return_value.collect.side_effect = [
        [mock_count_batch],
        [mock_batch],
    ]

    conn = DataFusionConnector(context=mock_ctx, tables={"users": mock_table})
    assert conn.connect() is mock_ctx

    info = conn.test_connection()
    assert info["status"] == "healthy"
    assert info["engine_version"] == "Apache Arrow DataFusion"

    # introspect_schema
    schema = conn.introspect_schema()
    assert "users" in schema["tables"]
    assert schema["tables"]["users"]["has_user_id"] is True

    # introspect_schema error branch
    mock_ctx.table.side_effect = RuntimeError("DF table exploded")
    with pytest.raises(IntrospectionError, match="Failed to introspect DataFusion"):
        conn.introspect_schema()
    mock_ctx.table.side_effect = None

    # register_table
    conn.register_table("items", MagicMock())
    assert "items" in conn._tables

    # execute normal
    mock_ctx.sql.return_value.collect.side_effect = [
        [mock_count_batch],
        [mock_batch],
    ]
    res = conn.execute(
        {
            "table": "users",
            "filters": [
                {"column": "user_id", "op": "eq", "value": 10},
                {"column": "name", "op": "eq", "value": "Alice"},
            ],
            "limit": 10,
            "offset": 0,
        }
    )
    assert res["count"] == 5
    assert len(res["rows"]) == 1
    assert res["columns"] == ["id", "user_id"]
    assert res["dialect"] == "datafusion"

    # execute with limit=0 and empty batches
    mock_ctx.sql.return_value.collect.side_effect = [[], []]
    res0 = conn.execute({"table": "users", "limit": 0})
    assert res0["count"] == 0
    assert res0["page"] == 1
    assert res0["rows"] == []

    # execute with validate_ast=False
    mock_ctx.sql.return_value.collect.side_effect = [[mock_count_batch], [mock_batch]]
    res_no_ast = conn.execute({"table": "users"}, validate_ast=False)
    assert res_no_ast["count"] == 5

    # execute spec validation error
    with pytest.raises(CompilationError, match="Specification must be a dictionary"):
        conn.execute("invalid")  # type: ignore

    # AST validation failure on main query
    with (
        patch(
            "query_builder.connectors.datafusion.validate_sql_ast",
            return_value={"valid": False, "message": "Disallowed DF query"},
        ),
        pytest.raises(CompilationError, match="safety validation"),
    ):
        conn.execute({"table": "users"})

    # AST validation failure on count query
    with (
        patch(
            "query_builder.connectors.datafusion.validate_sql_ast",
            side_effect=[
                {"valid": True, "message": "OK"},
                {"valid": False, "message": "Bad DF count query"},
            ],
        ),
        pytest.raises(CompilationError, match="Generated count query failed"),
    ):
        conn.execute({"table": "users"})

    # missing driver
    orig_import = builtins.__import__

    def mock_no_df(name, *args, **kwargs):
        if name == "datafusion" or name.startswith("datafusion"):
            raise ImportError("No datafusion")
        return orig_import(name, *args, **kwargs)

    with (
        patch("builtins.__import__", side_effect=mock_no_df),
        pytest.raises(DriverNotInstalledError, match="datafusion is not installed"),
    ):
        DataFusionConnector().connect()

    # connection failed
    mock_df_mod = MagicMock()
    mock_df_mod.SessionContext.side_effect = RuntimeError("SessionContext failed")
    with (
        patch.dict(sys.modules, {"datafusion": mock_df_mod}),
        pytest.raises(ConnectionFailedError, match="Failed to initialize DataFusion"),
    ):
        DataFusionConnector().connect()

    # SessionContext init success with tables registration
    mock_df_mod_ok = MagicMock()
    mock_ctx_inst = MagicMock()
    mock_df_mod_ok.SessionContext.return_value = mock_ctx_inst
    with patch.dict(sys.modules, {"datafusion": mock_df_mod_ok}):
        df_conn = DataFusionConnector(tables={"users": MagicMock()})
        assert df_conn.connect() is mock_ctx_inst
        mock_ctx_inst.register_table.assert_called_once()


def test_databricks_connector_full():
    mock_conn = MagicMock()
    conn = DatabricksConnector(catalog="lakehouse", schema_name="silver")
    conn._connection = mock_conn
    assert conn.connect() is mock_conn
    conn._connection = None

    # Missing driver
    orig_import = builtins.__import__

    def mock_no_db(name, *args, **kwargs):
        if name == "databricks" or name.startswith("databricks"):
            raise ImportError("No databricks")
        return orig_import(name, *args, **kwargs)

    with (
        patch("builtins.__import__", side_effect=mock_no_db),
        pytest.raises(
            DriverNotInstalledError, match="databricks-sql-connector is not installed"
        ),
    ):
        conn.connect()

    # Connection failure
    mock_sql = MagicMock()
    mock_sql.connect.side_effect = RuntimeError("Databricks auth fail")
    mock_db_pkg = MagicMock(sql=mock_sql)
    with (
        patch.dict(
            sys.modules, {"databricks": mock_db_pkg, "databricks.sql": mock_sql}
        ),
        pytest.raises(ConnectionFailedError, match="Failed to connect to Databricks"),
    ):
        conn.connect()

    # Connection success
    mock_sql.connect.side_effect = None
    mock_sql.connect.return_value = mock_conn
    with patch.dict(
        sys.modules, {"databricks": mock_db_pkg, "databricks.sql": mock_sql}
    ):
        assert conn.connect() is mock_conn

    # test_connection
    info = conn.test_connection()
    assert info["engine_version"] == "Databricks Spark SQL"

    # introspect_schema
    with patch(
        "query_builder.connectors.databricks.introspect_information_schema"
    ) as mock_intro:
        mock_intro.return_value = {"tables": {}, "foreign_keys": []}
        res = conn.introspect_schema()
        assert "tables" in res


def test_athena_connector_full():
    mock_conn = MagicMock()
    conn = AthenaConnector(s3_staging_dir="s3://lake/staging", schema_name="analytics")
    conn._connection = mock_conn
    assert conn.connect() is mock_conn
    conn._connection = None

    # Missing driver
    orig_import = builtins.__import__

    def mock_no_athena(name, *args, **kwargs):
        if name == "pyathena" or name.startswith("pyathena"):
            raise ImportError("No pyathena")
        return orig_import(name, *args, **kwargs)

    with (
        patch("builtins.__import__", side_effect=mock_no_athena),
        pytest.raises(DriverNotInstalledError, match="pyathena is not installed"),
    ):
        conn.connect()

    # Connection failure
    mock_pyathena = MagicMock()
    mock_pyathena.connect.side_effect = RuntimeError("S3 permission denied")
    with (
        patch.dict(sys.modules, {"pyathena": mock_pyathena}),
        pytest.raises(ConnectionFailedError, match="Failed to connect to AWS Athena"),
    ):
        conn.connect()

    # Connection success
    mock_pyathena.connect.side_effect = None
    mock_pyathena.connect.return_value = mock_conn
    with patch.dict(sys.modules, {"pyathena": mock_pyathena}):
        assert conn.connect() is mock_conn

    # test_connection
    info = conn.test_connection()
    assert info["engine_version"] == "AWS Athena Presto/Trino Engine"

    # introspect_schema
    with patch(
        "query_builder.connectors.athena.introspect_information_schema"
    ) as mock_intro:
        mock_intro.return_value = {"tables": {}, "foreign_keys": []}
        res = conn.introspect_schema()
        assert "tables" in res


def test_timescale_connector_full():
    mock_cur = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    # Timescale extension exists
    mock_cur.fetchone.return_value = ("2.14.0",)
    conn = TimescaleConnector(connection=mock_conn, cursor=mock_cur)
    info = conn.test_connection()
    assert info["timescale_version"] == "2.14.0"

    # Timescale extension does not exist
    mock_cur.fetchone.return_value = None
    info_none = conn.test_connection()
    assert "timescale_version" not in info_none


def test_cockroach_connector_full():
    mock_cur = MagicMock()
    conn = CockroachConnector(cursor=mock_cur)
    conn.apply_statement_timeout(mock_cur, 4500)
    mock_cur.execute.assert_called_with("SET statement_timeout = '4500ms';")


def test_spanner_connector_full():
    mock_conn = MagicMock()
    conn = SpannerConnector(instance_id="prod", database_id="orders")
    conn._connection = mock_conn
    assert conn.connect() is mock_conn
    conn._connection = None

    # Missing driver
    orig_import = builtins.__import__

    def mock_no_spanner(name, *args, **kwargs):
        if "spanner" in name:
            raise ImportError("No spanner")
        return orig_import(name, *args, **kwargs)

    with (
        patch("builtins.__import__", side_effect=mock_no_spanner),
        pytest.raises(
            DriverNotInstalledError, match="google-cloud-spanner is not installed"
        ),
    ):
        conn.connect()

    # Connection failure
    mock_spanner_dbapi = MagicMock()
    mock_spanner_dbapi.connect.side_effect = RuntimeError("GCP quota exceeded")
    with (
        patch.dict(
            sys.modules,
            {
                "google.cloud.spanner_dbapi": mock_spanner_dbapi,
            },
        ),
        pytest.raises(
            ConnectionFailedError, match="Failed to connect to Google Cloud Spanner"
        ),
    ):
        conn.connect()

    # Connection success
    mock_spanner_dbapi.connect.side_effect = None
    mock_spanner_dbapi.connect.return_value = mock_conn
    with patch.dict(
        sys.modules,
        {
            "google.cloud.spanner_dbapi": mock_spanner_dbapi,
        },
    ):
        assert conn.connect() is mock_conn

    # test_connection
    info = conn.test_connection()
    assert info["engine_version"] == "Google Cloud Spanner GoogleSQL"

    # introspect_schema
    with patch(
        "query_builder.connectors.spanner.introspect_information_schema"
    ) as mock_intro:
        mock_intro.return_value = {"tables": {}, "foreign_keys": []}
        res = conn.introspect_schema()
        assert "tables" in res


def test_questdb_connector_full():
    mock_cur = MagicMock()
    conn = QuestDBConnector(cursor=mock_cur)
    info = conn.test_connection()
    assert info["engine_version"] == "QuestDB"


def test_elasticsearch_connector_full():
    mock_conn = MagicMock()
    conn = ElasticsearchConnector(endpoint="http://localhost:9200")
    conn._connection = mock_conn
    assert conn.connect() is mock_conn
    conn._connection = None

    # Missing driver
    orig_import = builtins.__import__

    def mock_no_es(name, *args, **kwargs):
        if name == "elasticsearch" or name.startswith("elasticsearch"):
            raise ImportError("No elasticsearch")
        return orig_import(name, *args, **kwargs)

    with (
        patch("builtins.__import__", side_effect=mock_no_es),
        pytest.raises(DriverNotInstalledError, match="elasticsearch is not installed"),
    ):
        conn.connect()

    # Connection failure
    mock_es_cls = MagicMock(side_effect=RuntimeError("ES connection timeout"))
    mock_es_mod = MagicMock(Elasticsearch=mock_es_cls)
    with (
        patch.dict(sys.modules, {"elasticsearch": mock_es_mod}),
        pytest.raises(
            ConnectionFailedError, match="Failed to connect to Elasticsearch"
        ),
    ):
        conn.connect()

    # Connection success
    mock_es_cls.side_effect = None
    mock_es_cls.return_value = mock_conn
    with patch.dict(sys.modules, {"elasticsearch": mock_es_mod}):
        assert conn.connect() is mock_conn

    # test_connection
    info = conn.test_connection()
    assert info["engine_version"] == "Elasticsearch SQL"

    # introspect_schema
    mock_cur = MagicMock()
    mock_cur.fetchall.side_effect = [
        [("metrics",)],
        [("id", "keyword"), ("user_id", "keyword"), ("cpu", "float")],
    ]
    conn_intro = ElasticsearchConnector(cursor=mock_cur)
    schema = conn_intro.introspect_schema()
    assert "metrics" in schema["tables"]
    assert schema["tables"]["metrics"]["has_user_id"] is True
    assert schema["tables"]["metrics"]["columns"][0]["is_primary"] is True

    # introspect_schema error branch
    mock_cur_bad = MagicMock()
    mock_cur_bad.execute.side_effect = RuntimeError("Bad ES query")
    conn_bad = ElasticsearchConnector(cursor=mock_cur_bad)
    with pytest.raises(
        IntrospectionError, match="Failed to introspect Elasticsearch indices"
    ):
        conn_bad.introspect_schema()


def test_dynamodb_connector_full():
    mock_client = MagicMock()
    conn = DynamoDBConnector(region_name="us-west-2")
    conn._client = mock_client
    assert conn.connect() is mock_client
    conn._client = None

    # Missing driver
    orig_import = builtins.__import__

    def mock_no_boto(name, *args, **kwargs):
        if name == "boto3" or name.startswith("boto3"):
            raise ImportError("No boto3")
        return orig_import(name, *args, **kwargs)

    with (
        patch("builtins.__import__", side_effect=mock_no_boto),
        pytest.raises(DriverNotInstalledError, match="boto3 is not installed"),
    ):
        conn.connect()

    # Connection failure
    mock_boto = MagicMock()
    mock_boto.client.side_effect = RuntimeError("AWS credentials missing")
    with (
        patch.dict(sys.modules, {"boto3": mock_boto}),
        pytest.raises(
            ConnectionFailedError, match="Failed to connect to Amazon DynamoDB"
        ),
    ):
        conn.connect()

    # Connection success
    mock_boto.client.side_effect = None
    mock_boto.client.return_value = mock_client
    with patch.dict(sys.modules, {"boto3": mock_boto}):
        assert conn.connect() is mock_client

    # test_connection
    info = conn.test_connection()
    assert info["engine_version"] == "Amazon DynamoDB PartiQL"

    # introspect_schema
    mock_client.list_tables.return_value = {"TableNames": ["users"]}
    mock_client.describe_table.return_value = {
        "Table": {
            "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
            "AttributeDefinitions": [
                {"AttributeName": "id", "AttributeType": "N"},
                {"AttributeName": "user_id", "AttributeType": "N"},
                {"AttributeName": "status", "AttributeType": "S"},
            ],
        }
    }
    schema = conn.introspect_schema()
    assert "users" in schema["tables"]
    assert schema["tables"]["users"]["has_user_id"] is True
    assert schema["tables"]["users"]["columns"][0]["is_primary"] is True

    # introspect_schema error branch
    mock_client.list_tables.side_effect = RuntimeError("DynamoDB throttling")
    with pytest.raises(
        IntrospectionError, match="Failed to introspect DynamoDB tables"
    ):
        conn.introspect_schema()
    mock_client.list_tables.side_effect = None

    # _to_dynamo_param
    assert DynamoDBConnector._to_dynamo_param(True) == {"BOOL": True}
    assert DynamoDBConnector._to_dynamo_param(42) == {"N": "42"}
    assert DynamoDBConnector._to_dynamo_param(3.14) == {"N": "3.14"}
    assert DynamoDBConnector._to_dynamo_param(None) == {"NULL": True}
    assert DynamoDBConnector._to_dynamo_param("abc") == {"S": "abc"}

    # _unmarshal_item
    assert DynamoDBConnector._unmarshal_item(
        {
            "s": {"S": "text"},
            "n_int": {"N": "10"},
            "n_float": {"N": "10.5"},
            "b": {"BOOL": True},
            "nil": {"NULL": True},
            "custom": {"L": ["val"]},
            "empty": {},
        }
    ) == {
        "s": "text",
        "n_int": 10,
        "n_float": 10.5,
        "b": True,
        "nil": None,
        "custom": ["val"],
        "empty": None,
    }

    # execute normal
    mock_client.execute_statement.side_effect = [
        {"Items": [{"cnt": {"N": "10"}}]},
        {
            "Items": [
                {
                    "id": {"N": "1"},
                    "user_id": {"N": "100"},
                    "status": {"S": "active"},
                }
            ]
        },
    ]
    res = conn.execute(
        {
            "table": "users",
            "filters": [{"column": "id", "op": "eq", "value": 1}],
            "limit": 10,
            "offset": 0,
        }
    )
    assert res["count"] == 10
    assert len(res["rows"]) == 1
    assert res["rows"][0]["status"] == "active"
    assert res["columns"] == ["id", "user_id", "status"]
    assert res["dialect"] == "dynamodb"

    # execute with limit=0 and empty items
    mock_client.execute_statement.side_effect = [{"Items": []}, {"Items": []}]
    res0 = conn.execute({"table": "users", "limit": 0})
    assert res0["count"] == 0
    assert res0["page"] == 1
    assert res0["rows"] == []
    assert res0["columns"] == []

    # execute count query error branch
    mock_client.execute_statement.side_effect = [
        RuntimeError("Count query error"),
        {"Items": [{"id": {"N": "2"}}]},
    ]
    res_cnt_err = conn.execute({"table": "users"})
    assert res_cnt_err["count"] == 0
    assert len(res_cnt_err["rows"]) == 1

    # execute with validate_ast=False
    mock_client.execute_statement.side_effect = [
        {"Items": [{"cnt": {"N": "3"}}]},
        {"Items": []},
    ]
    res_no_ast = conn.execute({"table": "users"}, validate_ast=False)
    assert res_no_ast["count"] == 3

    # execute with non-numeric count item
    mock_client.execute_statement.side_effect = [
        {"Items": [{"cnt": {"S": "invalid"}}]},
        {"Items": []},
    ]
    res_nan = conn.execute({"table": "users"})
    assert res_nan["count"] == 0

    # execute with empty main_params and count_params
    with patch(
        "query_builder.connectors.dynamodb.QueryCompiler.compile",
        return_value=("SELECT * FROM users", [], "SELECT COUNT(*) FROM users", []),
    ):
        mock_client.execute_statement.side_effect = [
            {"Items": [{"cnt": {"N": "1"}}]},
            {"Items": []},
        ]
        res_no_p = conn.execute({"table": "users"})
        assert res_no_p["count"] == 1

    # execute spec validation error
    with pytest.raises(CompilationError, match="Specification must be a dictionary"):
        conn.execute("invalid")  # type: ignore

    # AST validation failure on main query
    with (
        patch(
            "query_builder.connectors.dynamodb.validate_sql_ast",
            return_value={"valid": False, "message": "Disallowed Dynamo query"},
        ),
        pytest.raises(CompilationError, match="safety validation"),
    ):
        conn.execute({"table": "users"})

    # AST validation failure on count query
    with (
        patch(
            "query_builder.connectors.dynamodb.validate_sql_ast",
            side_effect=[
                {"valid": True, "message": "OK"},
                {"valid": False, "message": "Bad Dynamo count query"},
            ],
        ),
        pytest.raises(CompilationError, match="Generated count query failed"),
    ):
        conn.execute({"table": "users"})
