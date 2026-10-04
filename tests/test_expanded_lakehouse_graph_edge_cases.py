"""
Deep Edge Cases and Branch-Exhaustion Tests for Expanded Connectors and Introspection.
=====================================================================================
Covers 100% statement, function, and branch coverage for:
- Introspection: doris, impala, hive, kyuubi, drill, yugabyte, opensearch, neo4j, kdb, clickhouse_native
- Edge cases in cursor adapters, fallback queries, and driver mocking
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from query_builder.connectors import (
    AsyncClickHouseNativeConnector,
    AsyncDorisConnector,
    AsyncDrillConnector,
    AsyncHiveConnector,
    AsyncImpalaConnector,
    AsyncKdbConnector,
    AsyncKyuubiConnector,
    AsyncNeo4jConnector,
    AsyncOpenSearchConnector,
    AsyncYugabyteDBConnector,
    ClickHouseNativeConnector,
    ConnectionFailedError,
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
    YugabyteDBConnector,
    introspect_clickhouse_native,
    introspect_doris,
    introspect_drill,
    introspect_hive,
    introspect_impala,
    introspect_kdb,
    introspect_kyuubi,
    introspect_neo4j,
    introspect_opensearch,
    introspect_yugabyte,
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
# 1. Doris Introspection & Edge Cases
# ============================================================================


def test_introspect_doris_happy_and_fallback():
    # 1. Happy path via information_schema
    mock_cursor = MagicMock()
    mock_cursor.fetchall.side_effect = [
        # tables
        [("users",), ("orders",)],
        # columns
        [
            ("users", "id", "BIGINT", "NO", "PRI"),
            ("users", "password_hash", "VARCHAR(255)", "YES", ""),
            ("users", "user_id", "INT", "NO", ""),
            ("orders", "id", "BIGINT", "NO", "UNI"),
            ("orders", "amount", "DECIMAL(10,2)", "YES", ""),
        ],
    ]
    res = introspect_doris(mock_cursor, database="mydb", filter_sensitive=True)
    assert "users" in res["tables"]
    assert "orders" in res["tables"]
    assert res["tables"]["users"]["has_user_id"] is True
    # password_hash filtered
    user_col_names = [c["name"] for c in res["tables"]["users"]["columns"]]
    assert "password_hash" not in user_col_names
    assert "id" in user_col_names

    # 1b. Filter sensitive is False
    mock_cursor.fetchall.side_effect = [
        [("users",)],
        [("users", "password_hash", "VARCHAR(255)", "YES", "")],
    ]
    res_unfiltered = introspect_doris(
        mock_cursor, database="mydb", filter_sensitive=False
    )
    col_names = [c["name"] for c in res_unfiltered["tables"]["users"]["columns"]]
    assert "password_hash" in col_names

    # 2. Fallback path when information_schema raises
    mock_cursor2 = MagicMock()

    def _exec_side_effect(sql, *args, **kwargs):
        if "information_schema" in sql:
            raise RuntimeError("Access denied to information_schema")

    mock_cursor2.execute.side_effect = _exec_side_effect
    mock_cursor2.fetchall.side_effect = [
        # SHOW TABLES
        [("customers",)],
        # DESCRIBE `customers`
        [
            ("id", "BIGINT", "NO", "PRI"),
            ("name", "VARCHAR(100)", "YES", ""),
        ],
    ]
    res_fb = introspect_doris(mock_cursor2, database="mydb")
    assert "customers" in res_fb["tables"]
    assert len(res_fb["tables"]["customers"]["columns"]) == 2

    # 3. Error path
    mock_bad = MagicMock()
    mock_bad.execute.side_effect = RuntimeError("Fatal connection drop")
    with pytest.raises(IntrospectionError):
        introspect_doris(mock_bad)


def test_doris_connector_cursor_lifecycle():
    # Connection with cursor and close method raising
    mock_cur = MagicMock()
    mock_cur.close.side_effect = RuntimeError("Failed to close cursor")
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    conn = DorisConnector(connection=mock_conn)
    with conn.get_cursor() as cur:
        assert isinstance(cur, _DorisCursorAdapter)

    # Connection lacking cursor() method
    conn2 = DorisConnector(connection=object())
    with conn2.get_cursor() as cur:
        assert isinstance(cur, _DorisCursorAdapter)

    # test_connection with fetchone returning None
    mock_cur_none = MagicMock()
    mock_cur_none.fetchone.return_value = None
    conn_none = DorisConnector(cursor=mock_cur_none)
    info = conn_none.test_connection()
    assert info["status"] == "healthy"
    assert "engine_version" not in info


# ============================================================================
# 2. Impala Introspection & Edge Cases
# ============================================================================


def test_introspect_impala_edge_cases():
    mock_cur = MagicMock()
    mock_cur.fetchall.side_effect = [
        # SHOW TABLES
        [("logs",), ("",), (None,)],
        # DESCRIBE logs
        [
            ("# Partition Information", "", ""),  # comment line
            ("", "", ""),  # empty line
            ("id", "bigint", "primary key"),
            ("user_id", "int", "user reference"),
            ("api_key", "string", "secret"),
        ],
    ]
    res = introspect_impala(mock_cur, database="default", filter_sensitive=True)
    assert "logs" in res["tables"]
    assert res["tables"]["logs"]["has_user_id"] is True
    cols = [c["name"] for c in res["tables"]["logs"]["columns"]]
    assert "id" in cols
    assert "user_id" in cols
    assert "api_key" not in cols  # filtered

    # Error path
    mock_bad = MagicMock()
    mock_bad.execute.side_effect = RuntimeError("Impala query timeout")
    with pytest.raises(IntrospectionError):
        introspect_impala(mock_bad)


def test_impala_connector_cursor_lifecycle():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.close.side_effect = RuntimeError("close err")
    mock_conn.cursor.return_value = mock_cur
    conn = ImpalaConnector(connection=mock_conn)
    with conn.get_cursor() as cur:
        assert isinstance(cur, _ImpalaCursorAdapter)

    conn2 = ImpalaConnector(connection=object())
    with conn2.get_cursor() as cur:
        assert isinstance(cur, _ImpalaCursorAdapter)

    mock_cur_none = MagicMock()
    mock_cur_none.fetchone.return_value = None
    conn_none = ImpalaConnector(cursor=mock_cur_none)
    info = conn_none.test_connection()
    assert info["status"] == "healthy"
    assert "engine_version" not in info


# ============================================================================
# 3. Hive Introspection & Edge Cases
# ============================================================================


def test_introspect_hive_edge_cases():
    mock_cur = MagicMock()
    mock_cur.fetchall.side_effect = [
        # SHOW TABLES
        [("events",)],
        # DESCRIBE events
        [
            ("# col_name", "data_type", "comment"),
            ("id", "string", "id col"),
            ("user_id", "string", "user col"),
            ("token", "string", "auth token"),
        ],
    ]
    res = introspect_hive(mock_cur, database="warehouse", filter_sensitive=True)
    assert "events" in res["tables"]
    assert res["tables"]["events"]["has_user_id"] is True
    cols = [c["name"] for c in res["tables"]["events"]["columns"]]
    assert "token" not in cols
    assert "id" in cols

    # Error path
    mock_bad = MagicMock()
    mock_bad.execute.side_effect = RuntimeError("Thrift transport error")
    with pytest.raises(IntrospectionError):
        introspect_hive(mock_bad)


def test_hive_connector_cursor_lifecycle():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.close.side_effect = RuntimeError("close err")
    mock_conn.cursor.return_value = mock_cur
    conn = HiveConnector(connection=mock_conn)
    with conn.get_cursor() as cur:
        assert isinstance(cur, _HiveCursorAdapter)

    conn2 = HiveConnector(connection=object())
    with conn2.get_cursor() as cur:
        assert isinstance(cur, _HiveCursorAdapter)

    mock_cur_none = MagicMock()
    mock_cur_none.fetchone.return_value = None
    conn_none = HiveConnector(cursor=mock_cur_none)
    info = conn_none.test_connection()
    assert info["status"] == "healthy"
    assert "engine_version" not in info


# ============================================================================
# 4. Kyuubi Introspection & Edge Cases
# ============================================================================


def test_introspect_kyuubi_edge_cases():
    mock_cur = MagicMock()
    mock_cur.fetchall.side_effect = [
        [("jobs",)],
        [
            ("# header", "type", ""),
            ("id", "int", ""),
            ("secret_key", "string", "sensitive"),
        ],
    ]
    res = introspect_kyuubi(mock_cur, database="spark_db", filter_sensitive=True)
    assert "jobs" in res["tables"]
    cols = [c["name"] for c in res["tables"]["jobs"]["columns"]]
    assert "secret_key" not in cols

    # Error path
    mock_bad = MagicMock()
    mock_bad.execute.side_effect = RuntimeError("Kyuubi session expired")
    with pytest.raises(IntrospectionError):
        introspect_kyuubi(mock_bad)


def test_kyuubi_connector_cursor_lifecycle():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.close.side_effect = RuntimeError("close err")
    mock_conn.cursor.return_value = mock_cur
    conn = KyuubiConnector(connection=mock_conn)
    with conn.get_cursor() as cur:
        assert isinstance(cur, _KyuubiCursorAdapter)

    conn2 = KyuubiConnector(connection=object())
    with conn2.get_cursor() as cur:
        assert isinstance(cur, _KyuubiCursorAdapter)

    mock_cur_none = MagicMock()
    mock_cur_none.fetchone.return_value = None
    conn_none = KyuubiConnector(cursor=mock_cur_none)
    info = conn_none.test_connection()
    assert info["status"] == "healthy"
    assert "engine_version" not in info


# ============================================================================
# 5. Drill Introspection & Edge Cases
# ============================================================================


def test_introspect_drill_happy_and_fallback():
    # 1. Happy path via INFORMATION_SCHEMA
    mock_cur = MagicMock()
    mock_cur.fetchall.side_effect = [
        [("employees",)],
        [
            ("employees", "id", "INTEGER", "NO"),
            ("employees", "user_id", "INTEGER", "YES"),
            ("employees", "ssn", "VARCHAR", "YES"),
        ],
    ]
    res = introspect_drill(mock_cur, schema_name="dfs.default", filter_sensitive=True)
    assert "employees" in res["tables"]
    assert res["tables"]["employees"]["has_user_id"] is True
    cols = [c["name"] for c in res["tables"]["employees"]["columns"]]
    assert "ssn" not in cols
    assert "id" in cols

    # 2. Fallback path via SHOW TABLES and DESCRIBE
    mock_cur2 = MagicMock()

    def _exec_side_effect(sql, *args, **kwargs):
        if "INFORMATION_SCHEMA" in sql:
            raise RuntimeError("INFORMATION_SCHEMA disabled")

    mock_cur2.execute.side_effect = _exec_side_effect
    mock_cur2.fetchall.side_effect = [
        [("products",)],
        [("id", "INT", "NO"), ("name", "VARCHAR", "YES")],
    ]
    res_fb = introspect_drill(mock_cur2, schema_name="dfs.default")
    assert "products" in res_fb["tables"]
    assert len(res_fb["tables"]["products"]["columns"]) == 2

    # 3. Target with .cursor()
    mock_client = MagicMock()
    mock_client.cursor.return_value = mock_cur
    mock_cur.fetchall.side_effect = [[("t",)], [("t", "id", "INT", "NO")]]
    res_client = introspect_drill(mock_client)
    assert "t" in res_client["tables"]

    # 4. Error path
    mock_bad = MagicMock()
    mock_bad.execute.side_effect = RuntimeError("Drill query error")
    with pytest.raises(IntrospectionError):
        introspect_drill(mock_bad)


def test_drill_connector_cursor_lifecycle():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.close.side_effect = RuntimeError("close err")
    mock_conn.cursor.return_value = mock_cur
    conn = DrillConnector(connection=mock_conn)
    with conn.get_cursor() as cur:
        assert isinstance(cur, _DrillCursorAdapter)

    conn2 = DrillConnector(connection=object())
    with conn2.get_cursor() as cur:
        assert isinstance(cur, _DrillCursorAdapter)

    mock_cur_none = MagicMock()
    mock_drill_res = MagicMock()
    mock_drill_res.columns = []
    mock_drill_res.rows = []
    mock_cur_none.query.return_value = mock_drill_res
    conn_none = DrillConnector(cursor=mock_cur_none)
    info = conn_none.test_connection()
    assert info["status"] == "healthy"
    assert "engine_version" not in info


# ============================================================================
# 6. YugabyteDB Introspection & Edge Cases
# ============================================================================


def test_introspect_yugabyte_edge_cases():
    mock_cur = MagicMock()
    mock_cur.fetchall.side_effect = [
        # tables
        [("users",), ("orders",)],
        # columns
        [
            ("users", "id", "bigint", "NO"),
            ("users", "password", "text", "YES"),
            ("users", "user_id", "integer", "NO"),
            ("orders", "id", "bigint", "NO"),
            ("orders", "user_id", "integer", "NO"),
        ],
        # primary keys
        [("users", "id"), ("orders", "id")],
        # foreign keys
        [("orders", "user_id", "users", "id")],
    ]
    res = introspect_yugabyte(mock_cur, schema_name="public", filter_sensitive=True)
    assert "users" in res["tables"]
    assert "orders" in res["tables"]
    assert len(res["foreign_keys"]) == 1
    assert res["foreign_keys"][0]["table"] == "orders"
    assert res["foreign_keys"][0]["foreign_table"] == "users"

    # Error path
    mock_bad = MagicMock()
    mock_bad.execute.side_effect = RuntimeError("Yugabyte connection reset")
    with pytest.raises(IntrospectionError):
        introspect_yugabyte(mock_bad)


def test_yugabyte_connector_cursor_lifecycle():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.close.side_effect = RuntimeError("close err")
    mock_conn.cursor.return_value = mock_cur
    conn = YugabyteDBConnector(connection=mock_conn)
    with conn.get_cursor() as cur:
        assert cur is mock_cur

    mock_cur_none = MagicMock()
    mock_cur_none.fetchone.return_value = None
    conn_none = YugabyteDBConnector(cursor=mock_cur_none)
    info = conn_none.test_connection()
    assert info["status"] == "healthy"
    assert "engine_version" not in info


# ============================================================================
# 7. OpenSearch Introspection & Edge Cases
# ============================================================================


def test_introspect_opensearch_edge_cases():
    # 1. OpenSearch client with indices.get_mapping
    mock_client = MagicMock()
    mock_client.indices.get_mapping.return_value = {
        ".kibana": {"mappings": {}},  # skipped because of dot
        "products": {
            "mappings": {
                "properties": {
                    "name": {"type": "text"},
                    "price": {"type": "float"},
                    "auth_token": {"type": "keyword"},
                }
            }
        },
    }
    res = introspect_opensearch(mock_client, filter_sensitive=True)
    assert "products" in res["tables"]
    assert ".kibana" not in res["tables"]
    cols = [c["name"] for c in res["tables"]["products"]["columns"]]
    assert "auth_token" not in cols
    assert "name" in cols
    assert "_id" in cols

    # 2. SQL cursor branch
    mock_cur = MagicMock()
    mock_cur.fetchall.side_effect = [
        # SHOW TABLES LIKE '%'
        [("metrics",), (".opendistro_security",)],
        # DESCRIBE metrics
        [
            ("metric_name", "keyword"),
            ("user_id", "keyword"),
            ("value", "double"),
        ],
    ]
    res_sql = introspect_opensearch(mock_cur, filter_sensitive=True)
    assert "metrics" in res_sql["tables"]
    assert ".opendistro_security" not in res_sql["tables"]
    assert res_sql["tables"]["metrics"]["has_user_id"] is True

    # 3. Empty tables fallback
    mock_cur_empty = MagicMock()
    mock_cur_empty.fetchall.return_value = []
    res_empty = introspect_opensearch(mock_cur_empty)
    assert "logs" in res_empty["tables"]

    # 4. Error path
    mock_bad = MagicMock()
    mock_bad.execute.side_effect = RuntimeError("OpenSearch error")
    with pytest.raises(IntrospectionError):
        introspect_opensearch(mock_bad)


def test_opensearch_cursor_adapter_edge_cases():
    # Target with cursor()
    mock_target = MagicMock()
    mock_cur = MagicMock()
    mock_cur.description = [("status",)]
    mock_cur.fetchall.return_value = [("green",)]
    mock_target.cursor.return_value = mock_cur
    adapter = _OpenSearchCursorAdapter(mock_target)
    adapter.execute("SELECT status")
    assert adapter.fetchall() == [("green",)]

    # Target with direct execute
    mock_direct = MagicMock(spec=["execute", "fetchall", "description"])
    mock_direct.description = [("x",)]
    mock_direct.fetchall.return_value = [(1,)]
    adapter2 = _OpenSearchCursorAdapter(mock_direct)
    adapter2.execute("SELECT 1")
    assert adapter2.fetchall() == [(1,)]

    # Target without execute/cursor
    adapter3 = _OpenSearchCursorAdapter(object())
    adapter3.execute("SELECT 1")
    assert adapter3.fetchall() == []

    # test_connection with empty datarows
    mock_cur_empty = MagicMock()
    mock_cur_empty.transport.perform_request.return_value = {
        "schema": [],
        "datarows": [],
    }
    conn = OpenSearchConnector(cursor=mock_cur_empty)
    info = conn.test_connection()
    assert info["status"] == "healthy"
    assert "engine_version" not in info


# ============================================================================
# 8. Neo4j Introspection & Edge Cases
# ============================================================================


def test_introspect_neo4j_edge_cases():
    # 1. Driver with session()
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value = mock_session

    mock_rec_label1 = {"label": "User"}
    mock_rec_label2 = {"label": "Post"}
    mock_res_labels = [mock_rec_label1, mock_rec_label2]

    mock_rec_user_keys = {"keys": ["id", "user_id", "email", "password"]}
    mock_rec_post_keys = {"keys": ["id", "title"]}

    mock_rec_rel = {"relationshipType": "AUTHORED"}

    mock_session.run.side_effect = [
        mock_res_labels,  # SHOW NODE LABELS
        [mock_rec_user_keys],  # MATCH User keys
        [mock_rec_post_keys],  # MATCH Post keys
        [mock_rec_rel],  # SHOW RELATIONSHIP TYPES
    ]

    res = introspect_neo4j(mock_driver, filter_sensitive=True)
    assert "User" in res["tables"]
    assert "Post" in res["tables"]
    assert res["tables"]["User"]["has_user_id"] is True
    user_cols = [c["name"] for c in res["tables"]["User"]["columns"]]
    assert "password" not in user_cols
    assert "email" in user_cols
    assert len(res["relationships"]) == 1
    assert res["relationships"][0]["source_table"] == "User"
    assert res["relationships"][0]["target_table"] == "Post"

    # 2. Fallback to CALL db.labels()
    mock_session2 = MagicMock()

    def _run_side_effect(cypher):
        if "SHOW NODE LABELS" in cypher:
            raise RuntimeError("SHOW NODE LABELS syntax error")
        if "CALL db.labels()" in cypher:
            return [{"label": "Entity"}]
        return []

    mock_session2.run.side_effect = _run_side_effect
    res2 = introspect_neo4j(mock_session2)
    assert "Entity" in res2["tables"]

    # 3. Fallback to default "Node" label when labels query fails
    mock_session3 = MagicMock()
    mock_session3.run.side_effect = RuntimeError("Labels query disabled")
    res3 = introspect_neo4j(mock_session3)
    assert "Node" in res3["tables"]

    # 4. Error path
    mock_bad = MagicMock()
    mock_bad.session.side_effect = RuntimeError("Neo4j driver pool closed")
    with pytest.raises(IntrospectionError):
        introspect_neo4j(mock_bad)


def test_neo4j_cursor_adapter_edge_cases():
    mock_session = MagicMock()
    # Records without values() method (dict records)
    mock_session.run.return_value = [{"a": 1, "b": 2}]
    adapter = _Neo4jCursorAdapter(mock_session)
    adapter.execute("MATCH (n) RETURN n.a AS a, n.b AS b", {"param": 1})
    assert adapter.fetchall() == [[1, 2]]

    # Records with list / scalar
    mock_session.run.return_value = [("x", "y"), 42]
    adapter2 = _Neo4jCursorAdapter(mock_session)
    adapter2.execute("RETURN 1", [10, 20])
    assert adapter2.fetchall() == [["x", "y"], [42]]

    # Target with cursor()
    mock_target = MagicMock()
    mock_cur = MagicMock()
    mock_cur.description = [("val",)]
    mock_cur.fetchall.return_value = [(100,)]
    mock_target.cursor.return_value = mock_cur
    adapter3 = _Neo4jCursorAdapter(mock_target)
    adapter3.execute("SELECT 100")
    assert adapter3.fetchall() == [(100,)]

    # Target with direct execute
    mock_direct = MagicMock(spec=["execute", "fetchall", "description"])
    mock_direct.fetchall.return_value = [(200,)]
    adapter4 = _Neo4jCursorAdapter(mock_direct)
    adapter4.execute("SELECT 200")
    assert adapter4.fetchall() == [(200,)]

    # Target without execute/run
    adapter5 = _Neo4jCursorAdapter(object())
    adapter5.execute("SELECT 1")
    assert adapter5.fetchall() == []

    # test_connection with empty result
    mock_session_empty = MagicMock()
    mock_session_empty.run.return_value = []
    conn = Neo4jConnector(cursor=mock_session_empty)
    info = conn.test_connection()
    assert info["status"] == "healthy"
    assert "engine_version" not in info


# ============================================================================
# 9. Kdb+ Introspection & Edge Cases
# ============================================================================


def test_introspect_kdb_edge_cases():
    # 1. client with callable client("tables[]")
    mock_client = MagicMock()
    mock_client.q = None  # Force callable
    mock_client.return_value = ("trades", "quotes")

    # Meta response as dictionary / items
    mock_client.side_effect = [
        ("trades", "quotes"),
        {"time": "p", "sym": "s", "price": "f", "secret_token": "s"},
        {"sym": "s", "bid": "f", "ask": "f"},
    ]

    res = introspect_kdb(mock_client, filter_sensitive=True)
    assert "trades" in res["tables"]
    assert "quotes" in res["tables"]
    trade_cols = [c["name"] for c in res["tables"]["trades"]["columns"]]
    assert "secret_token" not in trade_cols
    assert "time" in trade_cols

    # 2. client with sendSync
    mock_sync = MagicMock(spec=["sendSync"])
    mock_sync.sendSync.side_effect = [
        ["orders"],
        [("id", "i"), ("amount", "f")],
    ]
    res_sync = introspect_kdb(mock_sync)
    assert "orders" in res_sync["tables"]
    assert len(res_sync["tables"]["orders"]["columns"]) == 2

    # 3. client with execute
    mock_exec = MagicMock(spec=["execute", "fetchall"])
    mock_exec.fetchall.side_effect = [
        [("ticks",)],
        [("sym", "s"), ("px", "f")],
    ]
    res_exec = introspect_kdb(mock_exec)
    assert "ticks" in res_exec["tables"]

    # 4. Fallback default tables and columns
    mock_empty = MagicMock(spec=["sendSync"])
    mock_empty.sendSync.return_value = None
    res_def = introspect_kdb(mock_empty)
    assert "trades" in res_def["tables"]
    assert "quotes" in res_def["tables"]

    # 5. Error path
    mock_bad = MagicMock(side_effect=RuntimeError("PyKX fatal memory error"))
    with pytest.raises(IntrospectionError):
        introspect_kdb(mock_bad)


def test_kdb_cursor_adapter_edge_cases():
    # Target with sendSync
    mock_sync = MagicMock(spec=["sendSync"])
    mock_res_meta = MagicMock()
    mock_res_meta.meta.columns = ["a", "b"]
    mock_res_meta.__iter__.return_value = [[1, 2]]
    mock_sync.sendSync.return_value = mock_res_meta
    adapter1 = _KdbCursorAdapter(mock_sync)
    adapter1.execute("select from t")
    assert adapter1.description == [("a",), ("b",)]
    assert adapter1.fetchall() == [[1, 2]]

    # Target with sendSync returning list of primitives
    mock_sync.sendSync.return_value = [10, 20]
    adapter2 = _KdbCursorAdapter(mock_sync)
    adapter2.execute("10 20")
    assert adapter2.fetchall() == [[10], [20]]

    # Target with sendSync returning single scalar
    mock_sync.sendSync.return_value = 99
    adapter2b = _KdbCursorAdapter(mock_sync)
    adapter2b.execute("99")
    assert adapter2b.fetchall() == [[99]]

    # Target with cursor()
    mock_target = MagicMock()
    mock_cur = MagicMock()
    mock_cur.description = [("col",)]
    mock_cur.fetchall.return_value = [(42,)]
    mock_target.cursor.return_value = mock_cur
    adapter3 = _KdbCursorAdapter(mock_target)
    adapter3.execute("select 42")
    assert adapter3.fetchall() == [(42,)]

    # Target with direct execute
    mock_direct = MagicMock(spec=["execute", "fetchall", "description"])
    mock_direct.fetchall.return_value = [(84,)]
    adapter4 = _KdbCursorAdapter(mock_direct)
    adapter4.execute("select 84")
    assert adapter4.fetchall() == [(84,)]

    # Target without execute/sendSync/q
    adapter5 = _KdbCursorAdapter(object())
    adapter5.execute("select 1")
    assert adapter5.fetchall() == []

    # test_connection with empty rows
    mock_cur_empty = MagicMock()
    mock_res_empty = MagicMock()
    mock_res_empty.columns = []
    mock_df_empty = MagicMock()
    mock_df_empty.iterrows.return_value = []
    mock_res_empty.pd.return_value = mock_df_empty
    mock_cur_empty.q.sql.return_value = mock_res_empty
    conn = KdbConnector(cursor=mock_cur_empty)
    info = conn.test_connection()
    assert info["status"] == "healthy"
    assert "engine_version" not in info


# ============================================================================
# 10. ClickHouse Native Introspection & Edge Cases
# ============================================================================


def test_introspect_clickhouse_native_edge_cases():
    # 1. Happy path parameterized
    mock_cur = MagicMock()
    mock_cur.fetchall.side_effect = [
        # tables
        [("hits",), ("visits",)],
        # columns
        [
            ("hits", "id", "UInt64", 1),
            ("hits", "api_key", "String", 0),
            ("hits", "user_id", "UInt32", 0),
            ("visits", "visit_id", "UInt64", 1),
        ],
    ]
    res = introspect_clickhouse_native(
        mock_cur, database="analytics", filter_sensitive=True
    )
    assert "hits" in res["tables"]
    assert "visits" in res["tables"]
    assert res["tables"]["hits"]["has_user_id"] is True
    cols = [c["name"] for c in res["tables"]["hits"]["columns"]]
    assert "api_key" not in cols
    assert "id" in cols

    # 2. Fallback unparameterized when parameterized query raises
    mock_cur2 = MagicMock()

    def _exec_side_effect(sql, *args, **kwargs):
        if "%(db)s" in sql:
            raise TypeError("Parameterized formatting unsupported")

    mock_cur2.execute.side_effect = _exec_side_effect
    mock_cur2.fetchall.side_effect = [
        [("events",)],
        [("events", "id", "UInt32", 1)],
    ]
    res_fb = introspect_clickhouse_native(mock_cur2, database="default")
    assert "events" in res_fb["tables"]
    assert len(res_fb["tables"]["events"]["columns"]) == 1

    # 3. Client with .cursor()
    mock_client = MagicMock()
    mock_client.cursor.return_value = mock_cur
    mock_cur.fetchall.side_effect = [[("t",)], [("t", "id", "UInt32", 1)]]
    res_client = introspect_clickhouse_native(mock_client)
    assert "t" in res_client["tables"]

    # 4. Error path
    mock_bad = MagicMock()
    mock_bad.execute.side_effect = RuntimeError("ClickHouse TCP socket closed")
    with pytest.raises(IntrospectionError):
        introspect_clickhouse_native(mock_bad)


def test_clickhouse_native_cursor_adapter_edge_cases():
    # Client with TypeError on with_column_types
    mock_client = MagicMock()
    mock_client.execute_iter = MagicMock()

    def _exec_side_effect(sql, params, **kwargs):
        if "with_column_types" in kwargs:
            raise TypeError("unexpected keyword argument 'with_column_types'")
        return [(100,), (200,)]

    mock_client.execute.side_effect = _exec_side_effect
    adapter = _ClickHouseNativeCursorAdapter(mock_client)
    adapter.execute("SELECT number FROM system.numbers LIMIT 2")
    assert adapter.description == [("val",)]
    assert adapter.fetchall() == [[100], [200]]

    # Target with cursor()
    mock_target = MagicMock()
    mock_cur = MagicMock()
    mock_cur.description = [("x",)]
    mock_cur.fetchall.return_value = [(1,)]
    mock_target.cursor.return_value = mock_cur
    adapter2 = _ClickHouseNativeCursorAdapter(mock_target)
    adapter2.execute("SELECT 1")
    assert adapter2.fetchall() == [(1,)]

    # Target with direct execute
    mock_direct = MagicMock(spec=["execute", "fetchall", "description"])
    mock_direct.fetchall.return_value = [(2,)]
    adapter3 = _ClickHouseNativeCursorAdapter(mock_direct)
    adapter3.execute("SELECT 2")
    assert adapter3.fetchall() == [(2,)]

    # Target without execute
    adapter4 = _ClickHouseNativeCursorAdapter(object())
    adapter4.execute("SELECT 1")
    assert adapter4.fetchall() == []

    # test_connection with empty rows
    mock_cur_empty = MagicMock()
    mock_cur_empty.execute.return_value = ([], [])
    conn = ClickHouseNativeConnector(cursor=mock_cur_empty)
    info = conn.test_connection()
    assert info["status"] == "healthy"
    assert "engine_version" not in info


# ============================================================================
# 11. Branch Exhaustion & Edge Cases for 100% Coverage
# ============================================================================


def test_doris_branch_exhaustion():
    # 1. _DorisCursorAdapter.execute with target having execute and params
    mock_target = MagicMock(spec=["execute", "fetchall", "description"])
    mock_target.fetchall.return_value = [(10,)]
    adapter = _DorisCursorAdapter(mock_target)
    adapter.execute("SELECT %s", [1])
    mock_target.execute.assert_called_with("SELECT %s", [1])
    assert adapter.fetchall() == [(10,)]

    # 2. DorisConnector.connect() when driver has no connect attr
    with patch("builtins.__import__", return_value=object()):
        conn = DorisConnector()
        res = conn.connect()
        assert res is not None

    # 3. DorisConnector.get_cursor() where cursor has no close method
    mock_conn = MagicMock(spec=["cursor"])
    mock_cur = MagicMock(spec=["execute", "fetchall", "description"])
    mock_conn.cursor.return_value = mock_cur
    conn2 = DorisConnector(connection=mock_conn)
    with conn2.get_cursor() as cur:
        assert cur is not None

    # 4. AsyncDorisConnector.connect() when driver has no connect attr
    async def _test_async():
        with patch("builtins.__import__", return_value=object()):
            aconn = AsyncDorisConnector()
            res_async = await aconn.connect()
            assert res_async is not None

    asyncio.run(_test_async())


def test_impala_branch_exhaustion():
    # 1. _has_attr on non-mock object
    from query_builder.connectors.impala import _has_attr

    assert _has_attr(object(), "nonexistent") is False
    assert _has_attr("hello", "upper") is True

    # 2. _ImpalaCursorAdapter.execute with cursor + params
    mock_target = MagicMock()
    mock_cur = MagicMock()
    mock_target.cursor.return_value = mock_cur
    adapter = _ImpalaCursorAdapter(mock_target)
    adapter.execute("SELECT %s", [42])
    mock_cur.execute.assert_called_with("SELECT %s", [42])

    # 3. Target without cursor or execute
    adapter_empty = _ImpalaCursorAdapter(object())
    adapter_empty.execute("SELECT 1")
    assert adapter_empty.fetchall() == []
    assert adapter_empty.description is None

    # 4. ImpalaConnector.get_cursor() where cur has no close
    mock_conn = MagicMock(spec=["cursor"])
    mock_cur = MagicMock(spec=["execute", "fetchall", "description"])
    mock_conn.cursor.return_value = mock_cur
    conn = ImpalaConnector(connection=mock_conn)
    with conn.get_cursor() as cur:
        assert cur is not None

    # 5. AsyncImpalaConnector.connect() missing driver
    async def _test_async():
        with patch("builtins.__import__", side_effect=ImportError("No impala")):
            aconn = AsyncImpalaConnector()
            with pytest.raises(DriverNotInstalledError):
                await aconn.connect()

        # 6. AsyncImpalaConnector.connect() connection failed
        mock_driver = MagicMock()
        mock_driver.connect.side_effect = RuntimeError("Failed to connect")
        with patch("builtins.__import__", return_value=mock_driver):
            aconn = AsyncImpalaConnector()
            with pytest.raises(ConnectionFailedError):
                await aconn.connect()

        # 7. AsyncImpalaConnector.connect() successful connect
        mock_driver.connect.side_effect = None
        mock_driver.connect.return_value = "impala_conn"
        with patch("builtins.__import__", return_value=mock_driver):
            aconn = AsyncImpalaConnector()
            res = await aconn.connect()
            assert res == "impala_conn"

    asyncio.run(_test_async())


def test_hive_branch_exhaustion():
    # 1. _has_attr on non-mock object
    from query_builder.connectors.hive import _has_attr

    assert _has_attr(object(), "foo") is False
    assert _has_attr("str", "strip") is True

    # 2. _HiveCursorAdapter.execute with cursor + params
    mock_target = MagicMock()
    mock_cur = MagicMock()
    mock_target.cursor.return_value = mock_cur
    adapter = _HiveCursorAdapter(mock_target)
    adapter.execute("SELECT %s", [10])
    mock_cur.execute.assert_called_with("SELECT %s", [10])

    # 3. _HiveCursorAdapter.execute with execute + params
    mock_target_exec = MagicMock(spec=["execute", "fetchall", "description"])
    adapter_exec = _HiveCursorAdapter(mock_target_exec)
    adapter_exec.execute("SELECT %s", [10])
    mock_target_exec.execute.assert_called_with("SELECT %s", [10])

    # 4. Target without cursor or execute
    adapter_obj = _HiveCursorAdapter(object())
    adapter_obj.execute("SELECT 1")
    assert adapter_obj.fetchall() == []

    # 5. HiveConnector.get_cursor() where cur has no close
    mock_conn = MagicMock(spec=["cursor"])
    mock_cur = MagicMock(spec=["execute", "fetchall", "description"])
    mock_conn.cursor.return_value = mock_cur
    conn = HiveConnector(connection=mock_conn)
    with conn.get_cursor() as cur:
        assert cur is not None

    async def _test_async():
        # 6. AsyncHiveConnector.connect() missing driver
        with patch("builtins.__import__", side_effect=ImportError("No hive")):
            aconn = AsyncHiveConnector()
            with pytest.raises(DriverNotInstalledError):
                await aconn.connect()

        # 7. AsyncHiveConnector.connect() connect failed
        mock_driver = MagicMock()
        mock_driver.connect.side_effect = RuntimeError("Failed to connect hive")
        with patch("builtins.__import__", return_value=mock_driver):
            aconn = AsyncHiveConnector()
            with pytest.raises(ConnectionFailedError):
                await aconn.connect()

        # 8. AsyncHiveConnector.connect() successful connect
        mock_driver.connect.side_effect = None
        mock_driver.connect.return_value = "hive_conn"
        with patch("builtins.__import__", return_value=mock_driver):
            aconn = AsyncHiveConnector()
            res = await aconn.connect()
            assert res == "hive_conn"

    asyncio.run(_test_async())


def test_kyuubi_branch_exhaustion():
    # 1. _has_attr on non-mock object
    from query_builder.connectors.kyuubi import _has_attr

    assert _has_attr(object(), "bar") is False
    assert _has_attr("str", "strip") is True

    # 2. _KyuubiCursorAdapter.execute with cursor + params
    mock_target = MagicMock()
    mock_cur = MagicMock()
    mock_target.cursor.return_value = mock_cur
    adapter = _KyuubiCursorAdapter(mock_target)
    adapter.execute("SELECT %s", [20])
    mock_cur.execute.assert_called_with("SELECT %s", [20])

    # 3. _KyuubiCursorAdapter.execute with execute + params
    mock_target_exec = MagicMock(spec=["execute", "fetchall", "description"])
    adapter_exec = _KyuubiCursorAdapter(mock_target_exec)
    adapter_exec.execute("SELECT %s", [20])
    mock_target_exec.execute.assert_called_with("SELECT %s", [20])

    # 4. Target without cursor or execute
    adapter_obj = _KyuubiCursorAdapter(object())
    adapter_obj.execute("SELECT 1")
    assert adapter_obj.fetchall() == []

    # 5. KyuubiConnector.get_cursor() where cur has no close
    mock_conn = MagicMock(spec=["cursor"])
    mock_cur = MagicMock(spec=["execute", "fetchall", "description"])
    mock_conn.cursor.return_value = mock_cur
    conn = KyuubiConnector(connection=mock_conn)
    with conn.get_cursor() as cur:
        assert cur is not None

    async def _test_async():
        # 6. AsyncKyuubiConnector.connect() missing driver
        with patch("builtins.__import__", side_effect=ImportError("No kyuubi")):
            aconn = AsyncKyuubiConnector()
            with pytest.raises(DriverNotInstalledError):
                await aconn.connect()

        # 7. AsyncKyuubiConnector.connect() connect failed
        mock_driver = MagicMock()
        mock_driver.connect.side_effect = RuntimeError("Failed to connect kyuubi")
        with patch("builtins.__import__", return_value=mock_driver):
            aconn = AsyncKyuubiConnector()
            with pytest.raises(ConnectionFailedError):
                await aconn.connect()

        # 8. AsyncKyuubiConnector.connect() successful connect
        mock_driver.connect.side_effect = None
        mock_driver.connect.return_value = "kyuubi_conn"
        with patch("builtins.__import__", return_value=mock_driver):
            aconn = AsyncKyuubiConnector()
            res = await aconn.connect()
            assert res == "kyuubi_conn"

    asyncio.run(_test_async())


def test_drill_branch_exhaustion():
    # 1. _has_attr on non-mock object
    from query_builder.connectors.drill import _has_attr

    assert _has_attr(object(), "test") is False
    assert _has_attr("abc", "lower") is True

    # 2. _DrillCursorAdapter.execute with target having cursor: with and without params
    mock_target = MagicMock()
    mock_cur = MagicMock()
    mock_cur.description = [("a",)]
    mock_cur.fetchall.return_value = [(1,)]
    mock_target.cursor.return_value = mock_cur
    adapter = _DrillCursorAdapter(mock_target)
    adapter.execute("SELECT %s", [1])
    assert adapter.description == [("a",)]
    assert adapter.fetchall() == [(1,)]

    adapter.execute("SELECT 1")
    assert adapter.description == [("a",)]

    # 3. _DrillCursorAdapter.execute with target having execute: with and without params
    mock_target_exec = MagicMock(spec=["execute", "fetchall", "description"])
    mock_target_exec.description = [("b",)]
    mock_target_exec.fetchall.return_value = [(2,)]
    adapter_exec = _DrillCursorAdapter(mock_target_exec)
    adapter_exec.execute("SELECT %s", [2])
    assert adapter_exec.fetchall() == [(2,)]

    adapter_exec.execute("SELECT 2")
    assert adapter_exec.description == [("b",)]

    # 4. Target without cursor, query, or execute
    adapter_obj = _DrillCursorAdapter(object())
    adapter_obj.execute("SELECT 1")
    assert adapter_obj.description is None
    assert adapter_obj.fetchall() == []

    # 5. DrillConnector.connect() when driver has no PyDrill/Drill attr
    with patch("builtins.__import__", return_value=object()):
        conn = DrillConnector()
        res = conn.connect()
        assert res is not None

    # 6. DrillConnector.get_cursor() where cur has no close
    mock_conn = MagicMock(spec=["cursor"])
    mock_cur2 = MagicMock(spec=["execute", "fetchall", "description"])
    mock_conn.cursor.return_value = mock_cur2
    conn2 = DrillConnector(connection=mock_conn)
    with conn2.get_cursor() as cur:
        assert cur is not None

    # 7. DrillConnector.test_connection() when ver is empty
    mock_cur_empty = MagicMock(spec=["execute", "fetchall"])
    mock_cur_empty.fetchall.return_value = [("",)]
    conn_tc = DrillConnector(cursor=mock_cur_empty)
    info = conn_tc.test_connection()
    assert "engine_version" not in info

    async def _test_async():
        # 8. AsyncDrillConnector.connect() missing driver
        with patch("builtins.__import__", side_effect=ImportError("No drill")):
            aconn = AsyncDrillConnector()
            with pytest.raises(DriverNotInstalledError):
                await aconn.connect()

        # 9. AsyncDrillConnector.connect() with Drill class
        mock_mod = MagicMock()
        mock_mod.Drill.return_value = "drill_inst"
        with patch("builtins.__import__", return_value=mock_mod):
            aconn = AsyncDrillConnector()
            res = await aconn.connect()
            assert res == "drill_inst"

        # 10. AsyncDrillConnector.connect() without Drill class
        mock_mod_no_cls = MagicMock(spec=[])
        with patch("builtins.__import__", return_value=mock_mod_no_cls):
            aconn = AsyncDrillConnector()
            res = await aconn.connect()
            assert res == mock_mod_no_cls

        # 11. AsyncDrillConnector.connect() connect error
        mock_mod_err = MagicMock()
        mock_mod_err.Drill.side_effect = RuntimeError("Drill connect failed")
        with patch("builtins.__import__", return_value=mock_mod_err):
            aconn = AsyncDrillConnector()
            with pytest.raises(ConnectionFailedError):
                await aconn.connect()

    asyncio.run(_test_async())


def test_yugabyte_branch_exhaustion():
    async def _test_async():
        # 1. AsyncYugabyteDBConnector.connect() driver without connect
        with patch("builtins.__import__", return_value=object()):
            aconn = AsyncYugabyteDBConnector()
            res = await aconn.connect()
            assert res is not None

        # 2. AsyncYugabyteDBConnector.connect() connect error
        mock_driver = MagicMock()
        mock_driver.connect.side_effect = RuntimeError("Yugabyte connect error")
        with patch("builtins.__import__", return_value=mock_driver):
            aconn = AsyncYugabyteDBConnector()
            with pytest.raises(ConnectionFailedError):
                await aconn.connect()

        # 3. AsyncYugabyteDBConnector.execute_raw() with cursor and params
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.description = [("col1",)]
        mock_cur.fetchall.return_value = [(100,)]
        mock_conn.cursor.return_value = mock_cur
        aconn2 = AsyncYugabyteDBConnector(connection=mock_conn)
        cols, rows, _lat = await aconn2.execute_raw("SELECT $1", [100])
        assert cols == ["col1"]
        assert rows == [{"col1": 100}]
        mock_cur.execute.assert_called_with("SELECT $1", [100])

        # 4. AsyncYugabyteDBConnector.execute_raw() with asyncpg conn.fetch
        mock_asyncpg_conn = MagicMock(spec=["fetch"])

        async def _mock_fetch(sql, *args):
            return [{"x": 1, "y": 2}]

        mock_asyncpg_conn.fetch = _mock_fetch
        aconn3 = AsyncYugabyteDBConnector(connection=mock_asyncpg_conn)
        cols, rows, _lat = await aconn3.execute_raw("SELECT 1, 2", [1])
        assert cols == ["x", "y"]
        assert rows == [{"x": 1, "y": 2}]

        # Empty records fetch
        async def _mock_empty_fetch(sql, *args):
            return []

        mock_asyncpg_conn.fetch = _mock_empty_fetch
        cols2, rows2, _lat2 = await aconn3.execute_raw("SELECT 1")
        assert cols2 == []
        assert rows2 == []

        # 5. AsyncYugabyteDBConnector.introspect_schema() without cursor on conn
        mock_conn_nocursor = MagicMock(spec=["fetch"])
        with patch(
            "query_builder.connectors.yugabyte.introspect_yugabyte",
            return_value={"tables": {"users": {}}},
        ):
            aconn4 = AsyncYugabyteDBConnector(connection=mock_conn_nocursor)
            res = await aconn4.introspect_schema()
            assert "users" in res["tables"]

        # 6. AsyncYugabyteDBConnector.execute_raw() on object without cursor or fetch
        aconn_obj = AsyncYugabyteDBConnector(connection=object())
        assert await aconn_obj.execute_raw("SELECT 1") is None

    asyncio.run(_test_async())


def test_opensearch_branch_exhaustion():
    # 1. _OpenSearchCursorAdapter.execute with cursor + params
    mock_target = MagicMock()
    mock_cur = MagicMock()
    mock_target.cursor.return_value = mock_cur
    adapter = _OpenSearchCursorAdapter(mock_target)
    adapter.execute("SELECT %s", [1])
    mock_cur.execute.assert_called_with("SELECT %s", [1])

    # 2. _OpenSearchCursorAdapter.execute with execute + params
    mock_target_exec = MagicMock(spec=["execute", "fetchall", "description"])
    adapter_exec = _OpenSearchCursorAdapter(mock_target_exec)
    adapter_exec.execute("SELECT %s", [1])
    mock_target_exec.execute.assert_called_with("SELECT %s", [1])

    # 3. OpenSearchConnector.connect() driver without OpenSearch or Elasticsearch
    with patch("builtins.__import__", return_value=object()):
        conn = OpenSearchConnector()
        assert conn.connect() is not None

    # 4. OpenSearchConnector.get_cursor() where conn has cursor with and without close
    mock_conn = MagicMock(spec=["cursor"])
    mock_cur2 = MagicMock(spec=["execute", "fetchall", "description", "close"])
    mock_conn.cursor.return_value = mock_cur2
    conn2 = OpenSearchConnector(connection=mock_conn)
    with conn2.get_cursor() as cur:
        assert cur is not None
    mock_cur2.close.assert_called_once()

    mock_conn_no_cur = MagicMock(spec=["transport"])
    conn3 = OpenSearchConnector(connection=mock_conn_no_cur)
    with conn3.get_cursor() as cur:
        assert cur is not None

    # cursor without close method
    mock_conn_noclose = MagicMock(spec=["cursor"])
    mock_cur_noclose = MagicMock(spec=["execute", "fetchall", "description"])
    mock_conn_noclose.cursor.return_value = mock_cur_noclose
    conn_noclose = OpenSearchConnector(connection=mock_conn_noclose)
    with conn_noclose.get_cursor() as cur:
        assert cur is not None

    async def _test_async():
        # 5. AsyncOpenSearchConnector.connect() missing driver
        with patch("builtins.__import__", side_effect=ImportError("No opensearch")):
            aconn = AsyncOpenSearchConnector()
            with pytest.raises(DriverNotInstalledError):
                await aconn.connect()

        # 6. AsyncOpenSearchConnector.connect() with AsyncOpenSearch
        mock_mod = MagicMock()
        mock_mod.AsyncOpenSearch.return_value = "async_os_inst"
        with patch("builtins.__import__", return_value=mock_mod):
            aconn = AsyncOpenSearchConnector()
            res = await aconn.connect()
            assert res == "async_os_inst"

        # 7. AsyncOpenSearchConnector.connect() without client class
        mock_mod_no_cls = MagicMock(spec=[])
        with patch("builtins.__import__", return_value=mock_mod_no_cls):
            aconn = AsyncOpenSearchConnector()
            res = await aconn.connect()
            assert res == mock_mod_no_cls

        # 8. AsyncOpenSearchConnector.connect() connect error
        mock_mod_err = MagicMock()
        mock_mod_err.AsyncOpenSearch.side_effect = RuntimeError(
            "OpenSearch connect error"
        )
        with patch("builtins.__import__", return_value=mock_mod_err):
            aconn = AsyncOpenSearchConnector()
            with pytest.raises(ConnectionFailedError):
                await aconn.connect()

    asyncio.run(_test_async())


def test_neo4j_branch_exhaustion():
    # 1. _Neo4jCursorAdapter.execute with cursor + params
    mock_target = MagicMock()
    mock_cur = MagicMock()
    mock_target.cursor.return_value = mock_cur
    adapter = _Neo4jCursorAdapter(mock_target)
    adapter.execute("MATCH (n) RETURN n", [1])
    mock_cur.execute.assert_called_with("MATCH (n) RETURN n", [1])

    # 2. _Neo4jCursorAdapter.execute with execute + params
    mock_target_exec = MagicMock(spec=["execute", "fetchall", "description"])
    adapter_exec = _Neo4jCursorAdapter(mock_target_exec)
    adapter_exec.execute("MATCH (n) RETURN n", [1])
    mock_target_exec.execute.assert_called_with("MATCH (n) RETURN n", [1])

    # 3. Neo4jConnector.connect() when driver has GraphDatabase but no driver method
    mock_mod = MagicMock()
    mock_mod.GraphDatabase = object()
    with patch("builtins.__import__", return_value=mock_mod):
        conn = Neo4jConnector()
        assert conn.connect() is not None

    # 4. Neo4jConnector.get_cursor() when _cursor is None
    mock_driver = MagicMock()
    conn2 = Neo4jConnector(connection=mock_driver)
    with conn2.get_cursor() as cur:
        assert cur is not None

    async def _test_async():
        # 5. AsyncNeo4jConnector.connect() missing driver
        with patch("builtins.__import__", side_effect=ImportError("No neo4j")):
            aconn = AsyncNeo4jConnector()
            with pytest.raises(DriverNotInstalledError):
                await aconn.connect()

        # 6. AsyncNeo4jConnector.connect() target_cls with driver method
        mock_mod2 = MagicMock()
        mock_mod2.AsyncGraphDatabase.driver.return_value = "async_neo4j_inst"
        with patch("builtins.__import__", return_value=mock_mod2):
            aconn = AsyncNeo4jConnector()
            res = await aconn.connect()
            assert res == "async_neo4j_inst"

        # 7. AsyncNeo4jConnector.connect() target_cls without driver method
        mock_mod2.AsyncGraphDatabase = object()
        mock_mod2.GraphDatabase = object()
        with patch("builtins.__import__", return_value=mock_mod2):
            aconn = AsyncNeo4jConnector()
            res = await aconn.connect()
            assert res is not None

        # 8. AsyncNeo4jConnector.connect() connect error
        mock_mod3 = MagicMock()
        mock_mod3.AsyncGraphDatabase.driver.side_effect = RuntimeError("Neo4j error")
        with patch("builtins.__import__", return_value=mock_mod3):
            aconn = AsyncNeo4jConnector()
            with pytest.raises(ConnectionFailedError):
                await aconn.connect()

    asyncio.run(_test_async())


def test_kdb_branch_exhaustion():
    # 1. _KdbCursorAdapter.execute with cursor + params
    mock_target = MagicMock()
    mock_cur = MagicMock()
    mock_target.cursor.return_value = mock_cur
    adapter = _KdbCursorAdapter(mock_target)
    adapter.execute("select %s", [1])
    mock_cur.execute.assert_called_with("select %s", [1])

    # 2. _KdbCursorAdapter.execute pykx.q.sql with keys
    class MockKeysRes:
        def keys(self):
            return ["k1", "k2"]

        def __iter__(self):
            return iter(["k1", "k2"])

        def py(self):
            return [10, 20]

    mock_target_keys = MagicMock()
    mock_target_keys.q.sql.return_value = MockKeysRes()
    adapter_keys = _KdbCursorAdapter(mock_target_keys)
    adapter_keys.execute("select * from t")
    assert adapter_keys.description == [("k1",), ("k2",)]
    assert adapter_keys.fetchall() == [[10, 20]]

    # 3. _KdbCursorAdapter.execute pykx.q.sql scalar
    class MockScalarRes:
        def py(self):
            return 42

    mock_target_scalar = MagicMock()
    mock_target_scalar.q.sql.return_value = MockScalarRes()
    adapter_scalar = _KdbCursorAdapter(mock_target_scalar)
    adapter_scalar.execute("select 42")
    assert adapter_scalar.description == [("val",)]
    assert adapter_scalar.fetchall() == [[42]]

    # 4. _KdbCursorAdapter.execute pykx.q.sql no pd or py
    mock_target_raw = MagicMock()
    mock_target_raw.q.sql.return_value = object()
    adapter_raw = _KdbCursorAdapter(mock_target_raw)
    adapter_raw.execute("select 1")
    assert adapter_raw.fetchall() == []

    # 5. _KdbCursorAdapter.execute with execute + params
    mock_target_exec = MagicMock(spec=["execute", "fetchall", "description"])
    adapter_exec = _KdbCursorAdapter(mock_target_exec)
    adapter_exec.execute("select %s", [5])
    mock_target_exec.execute.assert_called_with("select %s", [5])

    # 6. KdbConnector.connect() QConnection without open
    mock_mod = MagicMock()
    mock_mod.QConnection.return_value = object()
    with patch("builtins.__import__", return_value=mock_mod):
        conn = KdbConnector()
        assert conn.connect() is not None

    # 7. KdbConnector.connect() SyncQConnection with open
    mock_mod2 = MagicMock(spec=["SyncQConnection"])
    mock_sync_conn = MagicMock()
    mock_mod2.SyncQConnection.return_value = mock_sync_conn
    with patch("builtins.__import__", return_value=mock_mod2):
        conn = KdbConnector()
        assert conn.connect() is mock_sync_conn
        mock_sync_conn.open.assert_called_once()

    # 8. KdbConnector.connect() SyncQConnection without open
    mock_mod3 = MagicMock(spec=["SyncQConnection"])
    mock_mod3.SyncQConnection.return_value = object()
    with patch("builtins.__import__", return_value=mock_mod3):
        conn = KdbConnector()
        assert conn.connect() is not None

    # 9. KdbConnector.connect() driver with q
    mock_mod4 = MagicMock(spec=["q"])
    with patch("builtins.__import__", return_value=mock_mod4):
        conn = KdbConnector()
        assert conn.connect() is mock_mod4

    # 10. KdbConnector.connect() driver without any of them
    mock_mod5 = MagicMock(spec=[])
    with patch("builtins.__import__", return_value=mock_mod5):
        conn = KdbConnector()
        assert conn.connect() is mock_mod5

    # 11. KdbConnector.get_cursor() when _cursor is None
    conn_cur = KdbConnector(connection=MagicMock())
    with conn_cur.get_cursor() as cur:
        assert cur is not None

    async def _test_async():
        # 12. AsyncKdbConnector.connect() missing driver
        with patch("builtins.__import__", side_effect=ImportError("No kdb")):
            aconn = AsyncKdbConnector()
            with pytest.raises(DriverNotInstalledError):
                await aconn.connect()

        # 13. AsyncKdbConnector.connect() with SyncQConnection
        mock_mod_async = MagicMock()
        mock_sync = MagicMock()
        mock_mod_async.SyncQConnection.return_value = mock_sync
        with patch("builtins.__import__", return_value=mock_mod_async):
            aconn = AsyncKdbConnector()
            res = await aconn.connect()
            assert res == mock_sync
            mock_sync.open.assert_called_once()

        # 14. AsyncKdbConnector.connect() without SyncQConnection
        mock_mod_async_nosync = MagicMock(spec=[])
        with patch("builtins.__import__", return_value=mock_mod_async_nosync):
            aconn = AsyncKdbConnector()
            res = await aconn.connect()
            assert res == mock_mod_async_nosync

        # 15. AsyncKdbConnector.connect() connect error
        mock_mod_err = MagicMock()
        mock_mod_err.SyncQConnection.side_effect = RuntimeError("Kdb connect error")
        with patch("builtins.__import__", return_value=mock_mod_err):
            aconn = AsyncKdbConnector()
            with pytest.raises(ConnectionFailedError):
                await aconn.connect()

    asyncio.run(_test_async())


def test_clickhouse_native_branch_exhaustion():
    # 1. _ClickHouseNativeCursorAdapter.execute with cursor + params
    mock_target = MagicMock()
    mock_cur = MagicMock()
    mock_target.cursor.return_value = mock_cur
    adapter = _ClickHouseNativeCursorAdapter(mock_target)
    adapter.execute("SELECT %s", [1])
    mock_cur.execute.assert_called_with("SELECT %s", [1])

    # 2. _ClickHouseNativeCursorAdapter.execute with execute + fetchall and params
    mock_target_exec = MagicMock(spec=["execute", "fetchall", "description"])
    adapter_exec = _ClickHouseNativeCursorAdapter(mock_target_exec)
    adapter_exec.execute("SELECT %s", [1])
    mock_target_exec.execute.assert_called_with("SELECT %s", [1])

    # 3. _ClickHouseNativeCursorAdapter.execute non-tuple output
    mock_target_nontuple = MagicMock(spec=["execute"])
    mock_target_nontuple.execute.return_value = [100, 200]
    adapter_nontuple = _ClickHouseNativeCursorAdapter(mock_target_nontuple)
    adapter_nontuple.execute("SELECT 1")
    assert adapter_nontuple.description == [("val",)]
    assert adapter_nontuple.fetchall() == [[100], [200]]

    # 4. ClickHouseNativeConnector.connect() driver without Client
    with patch("builtins.__import__", return_value=object()):
        conn = ClickHouseNativeConnector()
        assert conn.connect() is not None

    # 5. ClickHouseNativeConnector.get_cursor() when _cursor is None
    mock_conn = MagicMock(spec=["cursor"])
    mock_cur2 = MagicMock(spec=["execute", "fetchall", "description", "close"])
    mock_conn.cursor.return_value = mock_cur2
    conn2 = ClickHouseNativeConnector(connection=mock_conn)
    with conn2.get_cursor() as cur:
        assert cur is not None
    mock_cur2.close.assert_called_once()

    # cur without close
    mock_cur_noclose = MagicMock(spec=["execute", "fetchall", "description"])
    mock_conn.cursor.return_value = mock_cur_noclose
    with conn2.get_cursor() as cur:
        assert cur is not None

    # conn without cursor
    conn_nocursor = ClickHouseNativeConnector(connection=object())
    with conn_nocursor.get_cursor() as cur:
        assert cur is not None

    async def _test_async():
        # 6. AsyncClickHouseNativeConnector.connect() missing driver
        with patch("builtins.__import__", side_effect=ImportError("No clickhouse")):
            aconn = AsyncClickHouseNativeConnector()
            with pytest.raises(DriverNotInstalledError):
                await aconn.connect()

        # 7. AsyncClickHouseNativeConnector.connect() with connect (async)
        mock_mod = MagicMock()

        async def _async_connect(**kwargs):
            return "async_ch_conn"

        mock_mod.connect = _async_connect
        with patch("builtins.__import__", return_value=mock_mod):
            aconn = AsyncClickHouseNativeConnector()
            res = await aconn.connect()
            assert res == "async_ch_conn"

        # 8. AsyncClickHouseNativeConnector.connect() with Client
        mock_mod2 = MagicMock(spec=["Client"])
        mock_mod2.Client.return_value = "ch_client_conn"
        with patch("builtins.__import__", return_value=mock_mod2):
            aconn = AsyncClickHouseNativeConnector()
            res = await aconn.connect()
            assert res == "ch_client_conn"

        # 9. AsyncClickHouseNativeConnector.connect() with neither
        mock_mod3 = MagicMock(spec=[])
        with patch("builtins.__import__", return_value=mock_mod3):
            aconn = AsyncClickHouseNativeConnector()
            res = await aconn.connect()
            assert res == mock_mod3

        # 10. AsyncClickHouseNativeConnector.connect() connect error
        mock_mod4 = MagicMock()
        mock_mod4.connect.side_effect = RuntimeError("ClickHouse connect error")
        with patch("builtins.__import__", return_value=mock_mod4):
            aconn = AsyncClickHouseNativeConnector()
            with pytest.raises(ConnectionFailedError):
                await aconn.connect()

    asyncio.run(_test_async())


def test_introspection_branch_exhaustion():
    # 1. _has_attr on non-mock object
    from query_builder.connectors.introspection import _has_attr

    assert _has_attr(object(), "abc") is False
    assert _has_attr("hello", "startswith") is True

    # 2. _unwrap_cursor on real objects and mocks
    from query_builder.connectors.introspection import _unwrap_cursor

    obj1 = object()
    assert _unwrap_cursor(obj1) is obj1

    class RealConn:
        def cursor(self):
            return "unwrapped_cur"

    assert _unwrap_cursor(RealConn()) == "unwrapped_cur"

    class RealCur:
        def cursor(self):
            return self

        def fetchall(self):
            return []

    rc = RealCur()
    assert _unwrap_cursor(rc) is rc

    mock_spec_conn = MagicMock(spec=["cursor"])
    mock_spec_conn.cursor.return_value = "cur_val"
    assert _unwrap_cursor(mock_spec_conn) == "cur_val"

    mock_spec_cur = MagicMock(spec=["cursor", "fetchall"])
    assert _unwrap_cursor(mock_spec_cur) is mock_spec_cur

    # 3. introspect_doris fallback with sensitive column
    mock_cur_doris = MagicMock()

    def _exec_doris(sql, *args, **kwargs):
        if "information_schema" in sql:
            raise RuntimeError("no info schema")

    mock_cur_doris.execute.side_effect = _exec_doris
    mock_cur_doris.fetchall.side_effect = [
        [("users",)],
        [("secret_token", "VARCHAR(255)", "YES", "")],
    ]
    res_doris = introspect_doris(mock_cur_doris, database="db", filter_sensitive=True)
    assert len(res_doris["tables"]["users"]["columns"]) == 0

    # 4. introspect_kyuubi with user_id column
    mock_cur_kyuubi = MagicMock()
    mock_cur_kyuubi.fetchall.side_effect = [
        [("accounts",)],
        [("user_id", "INT", "account owner")],
    ]
    res_kyuubi = introspect_kyuubi(mock_cur_kyuubi, database="default")
    assert res_kyuubi["tables"]["accounts"]["has_user_id"] is True

    # 5. introspect_drill fallback with sensitive column
    mock_cur_drill = MagicMock()

    def _exec_drill(sql, *args, **kwargs):
        if "INFORMATION_SCHEMA" in sql:
            raise RuntimeError("no info schema")

    mock_cur_drill.execute.side_effect = _exec_drill
    mock_cur_drill.fetchall.side_effect = [
        [("logs",)],
        [("password_hash", "VARCHAR", "YES")],
    ]
    res_drill = introspect_drill(
        mock_cur_drill, schema_name="dfs.default", filter_sensitive=True
    )
    assert len(res_drill["tables"]["logs"]["columns"]) == 0

    # 6. introspect_opensearch with sensitive column in DESCRIBE and with _id in DESCRIBE
    mock_cur_os = MagicMock()
    mock_cur_os.fetchall.side_effect = [
        [("events",)],
        [("_id", "keyword"), ("api_key", "keyword"), ("message", "text")],
    ]
    res_os = introspect_opensearch(mock_cur_os, filter_sensitive=True)
    col_names = [c["name"] for c in res_os["tables"]["events"]["columns"]]
    assert "_id" in col_names
    assert "api_key" not in col_names
    assert "message" in col_names
    assert col_names.count("_id") == 1

    # 7. introspect_neo4j with single table and relationships
    mock_driver_neo = MagicMock()
    mock_session_neo = MagicMock()
    mock_driver_neo.session.return_value = mock_session_neo
    mock_session_neo.run.side_effect = [
        [{"label": "Person"}],
        [
            {
                "nodeType": ":`Person`",
                "propertyName": "id",
                "propertyTypes": ["Long"],
            }
        ],
        [{"relationshipType": "FRIEND_OF"}],
    ]
    res_neo = introspect_neo4j(mock_driver_neo)
    assert len(res_neo["relationships"]) == 1
    assert res_neo["relationships"][0]["source_table"] == "Person"
    assert res_neo["relationships"][0]["target_table"] == "Person"

    # 8. introspect_kdb variations
    # 8a. q callable
    class QClient:
        def q(self, query):
            if "tables[]" in query:
                return ["trades"]
            return [("price", "f"), ("secret_key", "s")]

    res_kdb_q = introspect_kdb(QClient(), filter_sensitive=True)
    assert "trades" in res_kdb_q["tables"]
    kdb_cols = [c["name"] for c in res_kdb_q["tables"]["trades"]["columns"]]
    assert "price" in kdb_cols
    assert "secret_key" not in kdb_cols

    # 8b. direct callable
    def q_call(query):
        if "tables[]" in query:
            return ["quotes"]
        return [("bid", "f")]

    res_kdb_call = introspect_kdb(q_call)
    assert "quotes" in res_kdb_call["tables"]

    # 8c. tables_res with py()
    class PykxTables:
        def py(self):
            return ["portfolio"]

    class PykxClient:
        def sendSync(self, query):
            if "tables[]" in query:
                return PykxTables()
            return [("asset", "s")]

    res_kdb_py = introspect_kdb(PykxClient())
    assert "portfolio" in res_kdb_py["tables"]

    # 8d. tables_res scalar
    class ScalarClient:
        def sendSync(self, query):
            if "tables[]" in query:
                return "mytable"
            return [("val", "i")]

    res_kdb_scalar = introspect_kdb(ScalarClient())
    assert "mytable" in res_kdb_scalar["tables"]

    # 8e. meta_res with pd()
    class MockDf:
        def iterrows(self):
            return [("price", {"t": "f"})]

    class DfMeta:
        def pd(self):
            return MockDf()

    class DfClient:
        def sendSync(self, query):
            if "tables[]" in query:
                return ["market"]
            return DfMeta()

    res_kdb_df = introspect_kdb(DfClient())
    assert "market" in res_kdb_df["tables"]
    assert res_kdb_df["tables"]["market"]["columns"][0]["name"] == "price"

    # 8f. meta_res row as dict or raw
    class DictMetaClient:
        def sendSync(self, query):
            if "tables[]" in query:
                return ["records"]
            return [{"c": "score", "t": "i"}, "raw_col"]

    res_kdb_dict = introspect_kdb(DictMetaClient())
    dict_cols = [c["name"] for c in res_kdb_dict["tables"]["records"]["columns"]]
    assert "score" in dict_cols
    assert "raw_col" in dict_cols

    # 8g. introspect_kdb with object without q, sendSync, execute, or callable
    res_kdb_obj = introspect_kdb(object())
    assert "trades" in res_kdb_obj["tables"]

    # 8h. introspect_kdb with meta_res having no pd, no items, and not list/tuple
    class NoItemsMetaClient:
        def sendSync(self, query):
            if "tables[]" in query:
                return ["custom_tbl"]
            return 12345

    res_kdb_noitems = introspect_kdb(NoItemsMetaClient())
    assert "custom_tbl" in res_kdb_noitems["tables"]
    assert len(res_kdb_noitems["tables"]["custom_tbl"]["columns"]) == 4

    # 9. introspect_clickhouse_native with non-cursor/non-execute object
    res_ch_no_exec = introspect_clickhouse_native(object())
    assert res_ch_no_exec["tables"] == {}
