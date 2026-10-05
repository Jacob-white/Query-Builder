"""
Comprehensive Unit Tests for Phase 2 Connectors: Observability, Cloud Log, Time-Series & Graph.
=============================================================================================
Verifies 100% statement, function, and branch coverage across:
- Kusto (Azure Data Explorer / KQL): KustoConnector, AsyncKustoConnector, _KustoCursorAdapter, KustoDialect, introspect_kusto
- Prometheus: PrometheusConnector, AsyncPrometheusConnector, _PrometheusCursorAdapter, PrometheusDialect, introspect_prometheus
- VictoriaMetrics: VictoriaMetricsConnector, AsyncVictoriaMetricsConnector, _VictoriaMetricsCursorAdapter, VictoriaMetricsDialect, introspect_victoriametrics
- AWS Timestream: TimestreamConnector, AsyncTimestreamConnector, _TimestreamCursorAdapter, TimestreamDialect, introspect_timestream
- Memgraph: MemgraphConnector, AsyncMemgraphConnector, _MemgraphCursorAdapter, MemgraphDialect, introspect_memgraph
- Amazon Neptune: NeptuneConnector, AsyncNeptuneConnector, _NeptuneCursorAdapter, NeptuneDialect, introspect_neptune
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock, patch

import pytest

from query_builder.connectors import (
    ADXConnector,
    AsyncADXConnector,
    AsyncKustoConnector,
    AsyncMemgraphConnector,
    AsyncNeptuneConnector,
    AsyncPrometheusConnector,
    AsyncTimestreamConnector,
    AsyncVictoriaMetricsConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
    KustoConnector,
    MemgraphConnector,
    NeptuneConnector,
    PrometheusConnector,
    TimestreamConnector,
    VictoriaMetricsConnector,
    get_connector,
    introspect_kusto,
    introspect_memgraph,
    introspect_neptune,
    introspect_prometheus,
    introspect_timestream,
    introspect_victoriametrics,
    list_connectors,
)
from query_builder.connectors.kusto import _KustoCursorAdapter
from query_builder.connectors.memgraph import _MemgraphCursorAdapter
from query_builder.connectors.neptune import _NeptuneCursorAdapter
from query_builder.connectors.prometheus import _PrometheusCursorAdapter
from query_builder.connectors.timestream import _TimestreamCursorAdapter
from query_builder.connectors.victoriametrics import _VictoriaMetricsCursorAdapter
from query_builder.dialects import (
    KustoDialect,
    MemgraphDialect,
    NeptuneDialect,
    PrometheusDialect,
    TimestreamDialect,
    VictoriaMetricsDialect,
    get_dialect,
)

# ============================================================================
# 1. Dialect Tests
# ============================================================================


def test_phase2_dialects():
    # Kusto
    kd = get_dialect("kusto")
    assert isinstance(kd, KustoDialect)
    assert kd.name == "kusto"
    assert get_dialect("adx").name == "kusto"
    assert get_dialect("kql").name == "kusto"
    assert kd.format_ilike("col") == "col =~ %s"
    assert kd.format_limit_offset(10, 5) == ("LIMIT %s OFFSET %s", [10, 5])
    assert kd.inspect_tables_query()[0] == ".show tables"
    assert (
        kd.inspect_columns_query(table_name="events")[0]
        == ".show table events schema as json"
    )
    assert kd.inspect_columns_query()[0] == ".show database schema as json"
    assert kd.inspect_primary_keys_query() == ("", [])
    assert kd.inspect_foreign_keys_query() == ("", [])

    # Prometheus
    pd = get_dialect("prometheus")
    assert isinstance(pd, PrometheusDialect)
    assert pd.name == "prometheus"
    assert get_dialect("promql").name == "prometheus"
    assert pd.format_ilike("val") == 'val=~"(?i)%s"'
    assert pd.format_limit_offset(10, 0) == ("LIMIT %s OFFSET %s", [10, 0])
    assert pd.inspect_tables_query()[0] == "/api/v1/label/__name__/values"
    assert pd.inspect_columns_query()[0] == "/api/v1/labels"
    assert pd.inspect_primary_keys_query() == ("", [])
    assert pd.inspect_foreign_keys_query() == ("", [])

    # VictoriaMetrics
    vd = get_dialect("victoriametrics")
    assert isinstance(vd, VictoriaMetricsDialect)
    assert vd.name == "victoriametrics"
    assert get_dialect("vm").name == "victoriametrics"
    assert vd.format_ilike("val") == 'val=~"(?i)%s"'
    assert vd.format_limit_offset(10, 5) == ("LIMIT %s OFFSET %s", [10, 5])
    assert vd.inspect_tables_query()[0] == "/api/v1/label/__name__/values"
    assert vd.inspect_columns_query()[0] == "/api/v1/labels"
    assert vd.inspect_primary_keys_query() == ("", [])
    assert vd.inspect_foreign_keys_query() == ("", [])

    # Timestream
    td = get_dialect("timestream")
    assert isinstance(td, TimestreamDialect)
    assert td.name == "timestream"
    assert get_dialect("aws_timestream").name == "timestream"
    assert td.format_ilike("col") == "LOWER(col) LIKE LOWER(%s)"
    assert td.format_limit_offset(10, 5) == ("LIMIT %s", [10])
    assert td.inspect_tables_query("mydb")[0] == 'SHOW TABLES FROM "mydb"'
    assert td.inspect_columns_query("mydb", "mytbl")[0] == 'DESCRIBE "mydb"."mytbl"'
    assert td.inspect_columns_query("mydb")[0] == 'SHOW TABLES FROM "mydb"'
    assert td.inspect_primary_keys_query() == ("", [])
    assert td.inspect_foreign_keys_query() == ("", [])

    # Memgraph
    md = get_dialect("memgraph")
    assert isinstance(md, MemgraphDialect)
    assert md.name == "memgraph"
    assert md.quote_identifier("node.prop") == "`node`.`prop`"
    assert md.format_ilike("col") == "toLower(col) CONTAINS toLower(%s)"
    assert md.format_limit_offset(10, 5) == ("SKIP %s LIMIT %s", [5, 10])
    assert md.inspect_tables_query()[0] == "CALL mg.labels() YIELD label RETURN label;"
    assert md.inspect_columns_query()[0] == "SHOW CONSTRAINT INFO;"
    assert md.inspect_primary_keys_query() == ("", [])
    assert (
        md.inspect_foreign_keys_query()[0]
        == "CALL mg.relationship_types() YIELD relationship_type RETURN relationship_type;"
    )

    # Neptune
    nd = get_dialect("neptune")
    assert isinstance(nd, NeptuneDialect)
    assert nd.name == "neptune"
    assert get_dialect("aws_neptune").name == "neptune"
    assert nd.quote_identifier("n.p") == "`n`.`p`"
    assert nd.format_ilike("col") == "toLower(col) CONTAINS toLower(%s)"
    assert nd.format_limit_offset(10, 5) == ("SKIP %s LIMIT %s", [5, 10])
    assert nd.inspect_tables_query()[0] == "CALL db.labels();"
    assert nd.inspect_columns_query()[0] == "CALL db.propertyKeys();"
    assert nd.inspect_primary_keys_query() == ("", [])
    assert nd.inspect_foreign_keys_query()[0] == "CALL db.relationshipTypes();"


# ============================================================================
# 2. Registry Tests
# ============================================================================


def test_phase2_registry():
    all_conns = list_connectors()
    for name in [
        "kusto",
        "prometheus",
        "victoriametrics",
        "timestream",
        "memgraph",
        "neptune",
    ]:
        assert name in all_conns
        assert f"async_{name}" in all_conns

    assert isinstance(get_connector("adx"), KustoConnector)
    assert isinstance(get_connector("kql"), KustoConnector)
    assert isinstance(get_connector("async_kql"), AsyncKustoConnector)
    assert isinstance(get_connector("promql"), PrometheusConnector)
    assert isinstance(get_connector("vm"), VictoriaMetricsConnector)
    assert isinstance(get_connector("aws_timestream"), TimestreamConnector)
    assert isinstance(get_connector("memgraph_cypher"), MemgraphConnector)
    assert isinstance(get_connector("aws_neptune"), NeptuneConnector)
    assert ADXConnector is KustoConnector
    assert AsyncADXConnector is AsyncKustoConnector


# ============================================================================
# 3. Parametric Cursor Adapter Tests (All 6 Adapters)
# ============================================================================


@pytest.mark.parametrize(
    "adapter_cls",
    [
        _KustoCursorAdapter,
        _PrometheusCursorAdapter,
        _VictoriaMetricsCursorAdapter,
        _TimestreamCursorAdapter,
        _MemgraphCursorAdapter,
        _NeptuneCursorAdapter,
    ],
)
def test_cursor_adapters_phase2_comprehensive(adapter_cls):
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

    # Connection with cursor() without close method (exercises hasattr(cur, 'close') False branch)
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


def test_kusto_adapter_specialized():
    # execute_query returning primary_results with columns and as_dict
    client = MagicMock(spec=["execute_query"])
    res = MagicMock(spec=["primary_results"])
    col1 = MagicMock(column_name="metric")
    tbl = MagicMock()
    tbl.columns = [col1]
    row_obj = MagicMock()
    row_obj.as_dict.return_value = {"metric": "cpu"}
    tbl.__iter__.return_value = [row_obj]
    res.primary_results = [tbl]
    client.execute_query.return_value = res

    adapter = _KustoCursorAdapter(client, database="kusto_db")
    adapter.execute(".show tables")
    assert adapter.description == [("metric",)]
    assert adapter.fetchall() == [["cpu"]]

    # primary_results with row having values()
    row_val = MagicMock(spec=["values"])
    row_val.values.return_value = ["mem"]
    tbl2 = MagicMock()
    tbl2.columns = None
    tbl2.__len__ = lambda self: 1
    tbl2.__getitem__ = lambda self, idx: {"key": "val"}
    tbl2.__iter__.return_value = [row_val]
    res2 = MagicMock(spec=["primary_results"])
    res2.primary_results = [tbl2]
    client.execute_query.return_value = res2
    adapter.execute(".show tables")
    assert adapter.fetchall() == [["mem"]]

    # primary_results with row as tuple/list
    tbl3 = MagicMock()
    tbl3.columns = None
    tbl3.__len__ = lambda self: 1
    tbl3.__getitem__ = lambda self, idx: ["disk"]
    tbl3.__iter__.return_value = [("disk",)]
    res3 = MagicMock(spec=["primary_results"])
    res3.primary_results = [tbl3]
    client.execute_query.return_value = res3
    adapter.execute(".show tables")
    assert adapter.fetchall() == [["disk"]]

    # primary_results with scalar row
    tbl4 = MagicMock()
    tbl4.columns = None
    tbl4.__len__ = lambda self: 0
    tbl4.__iter__.return_value = [123]
    res4 = MagicMock(spec=["primary_results"])
    res4.primary_results = [tbl4]
    client.execute_query.return_value = res4
    adapter.execute(".show tables")
    assert adapter.fetchall() == [[123]]

    # primary_results where tbl[0] has as_dict
    tbl_as_dict = MagicMock()
    tbl_as_dict.columns = None
    sample_row = MagicMock()
    sample_row.as_dict.return_value = {"field_a": 1}
    tbl_as_dict.__len__ = lambda self: 1
    tbl_as_dict.__getitem__ = lambda self, idx: sample_row
    tbl_as_dict.__iter__.return_value = [sample_row]
    res_dict = MagicMock(spec=["primary_results"])
    res_dict.primary_results = [tbl_as_dict]
    client.execute_query.return_value = res_dict
    adapter.execute(".show tables")
    assert adapter.description == [("field_a",)]

    # primary_results where tbl[0] has keys
    tbl_keys = MagicMock()
    tbl_keys.columns = None
    sample_key_row = {"k1": 2}
    tbl_keys.__len__ = lambda self: 1
    tbl_keys.__getitem__ = lambda self, idx: sample_key_row
    tbl_keys.__iter__.return_value = [[2]]
    res_keys = MagicMock(spec=["primary_results"])
    res_keys.primary_results = [tbl_keys]
    client.execute_query.return_value = res_keys
    adapter.execute(".show tables")
    assert adapter.description == [("k1",)]

    # empty primary_results
    res_empty = MagicMock(spec=["primary_results"])
    res_empty.primary_results = []
    client.execute_query.return_value = res_empty
    adapter.execute(".show tables")
    assert adapter.description is None
    assert adapter.fetchall() == []

    # execute fallback when execute_query raises TypeError on 2 args
    client2 = MagicMock(spec=["execute_query"])
    res5 = MagicMock(spec=["description", "fetchall"])
    res5.description = [("a",)]
    res5.fetchall.return_value = [[99]]
    client2.execute_query.side_effect = [TypeError("wrong args"), res5]
    adapter2 = _KustoCursorAdapter(client2)
    adapter2.execute("SELECT 99", [1])
    assert adapter2.description == [("a",)]
    assert adapter2.fetchall() == [[99]]


def test_prometheus_adapter_specialized():
    # label values query
    client = MagicMock(spec=["all_metrics"])
    client.all_metrics.return_value = ["up", "node_cpu"]
    adapter = _PrometheusCursorAdapter(client)
    adapter.execute("/api/v1/label/__name__/values")
    assert adapter.description == [("metric_name",)]
    assert adapter.fetchall() == [["up"], ["node_cpu"]]

    # custom_query returning list of dicts with metric and value
    client2 = MagicMock(spec=["custom_query"])
    client2.custom_query.return_value = [
        {"metric": {"job": "api"}, "value": [123456, "1.0"]}
    ]
    adapter2 = _PrometheusCursorAdapter(client2)
    adapter2.execute("up{job='api'}")
    assert adapter2.description == [("timestamp",), ("value",), ("metric",)]
    assert adapter2.fetchall() == [[123456, "1.0", "{'job': 'api'}"]]

    # custom_query returning non-list
    client2.custom_query.return_value = "invalid"
    adapter2.execute("up{job='api'}")
    assert adapter2.fetchall() == []


def test_victoriametrics_adapter_specialized():
    # conn with get returning json dict with data list
    http_conn = MagicMock(spec=["get"])
    resp = MagicMock()
    resp.json.return_value = {"data": ["vm_metric1", "vm_metric2"]}
    http_conn.get.return_value = resp

    adapter = _VictoriaMetricsCursorAdapter(http_conn)
    adapter.execute("/api/v1/label/__name__/values")
    assert adapter.description == [("metric_name",)]
    assert adapter.fetchall() == [["vm_metric1"], ["vm_metric2"]]

    # conn with post returning json dict with result list
    http_conn2 = MagicMock(spec=["post"])
    resp2 = MagicMock()
    resp2.json.return_value = {
        "data": {"result": [{"metric": {"env": "prod"}, "value": [1700000000, "99.5"]}]}
    }
    http_conn2.post.return_value = resp2
    adapter2 = _VictoriaMetricsCursorAdapter(http_conn2)
    adapter2.execute("vm_metric1")
    assert adapter2.description == [("timestamp",), ("value",), ("metric",)]
    assert adapter2.fetchall() == [[1700000000, "99.5", "{'env': 'prod'}"]]

    # conn returning data as scalar and data as list
    resp3 = MagicMock()
    resp3.json.return_value = {"data": "scalar_res"}
    http_conn.get.return_value = resp3
    adapter.execute("/api/v1/status")
    assert adapter.fetchall() == [["scalar_res"]]

    resp4 = MagicMock()
    resp4.json.return_value = ["raw1", "raw2"]
    http_conn.get.return_value = resp4
    adapter.execute("/api/v1/raw")
    assert adapter.fetchall() == [["raw1"], ["raw2"]]

    # conn returning json dict without data key
    resp5 = MagicMock()
    resp5.json.return_value = {"status": "ok"}
    http_conn.get.return_value = resp5
    adapter.execute("/api/v1/health")
    assert adapter.description == [("status",)]
    assert adapter.fetchall() == [["ok"]]

    # Coroutine response handling
    async def async_resp():
        return resp

    http_async = MagicMock(spec=["get"])
    http_async.get.return_value = async_resp()
    adapter_coro = _VictoriaMetricsCursorAdapter(http_async)
    adapter_coro.execute("/api/v1/label/__name__/values")
    assert adapter_coro.fetchall() == [["vm_metric1"], ["vm_metric2"]]


def test_timestream_adapter_specialized():
    client = MagicMock(spec=["query"])
    client.query.return_value = {
        "ColumnInfo": [{"Name": "host"}, {"Name": "cpu"}],
        "Rows": [{"Data": [{"ScalarValue": "server-1"}, {"ScalarValue": "0.45"}]}],
    }
    adapter = _TimestreamCursorAdapter(client)
    adapter.execute("SELECT host, cpu FROM telemetry")
    assert adapter.description == [("host",), ("cpu",)]
    assert adapter.fetchall() == [["server-1", "0.45"]]


def test_memgraph_adapter_specialized():
    # conn with execute_query
    conn = MagicMock(spec=["execute_query"])
    res = MagicMock()
    res.keys = ["id", "name"]
    row = MagicMock()
    row.values.return_value = [1, "Memgraph"]
    res.records = [row]
    conn.execute_query.return_value = res
    adapter = _MemgraphCursorAdapter(conn)
    adapter.execute("MATCH (n) RETURN n.id, n.name")
    assert adapter.description == [("id",), ("name",)]
    assert adapter.fetchall() == [[1, "Memgraph"]]

    # conn with run
    conn2 = MagicMock(spec=["run"])
    res2 = MagicMock()
    res2.keys.return_value = ["val"]
    res2.values.return_value = [[42]]
    conn2.run.return_value = res2
    adapter2 = _MemgraphCursorAdapter(conn2)
    adapter2.execute("RETURN 42")
    assert adapter2.description == [("val",)]
    assert adapter2.fetchall() == [[42]]


def test_neptune_adapter_specialized():
    # conn with execute_open_cypher_query returning list of dicts
    conn = MagicMock(spec=["execute_open_cypher_query"])
    conn.execute_open_cypher_query.return_value = {
        "results": [{"name": "Neptune", "version": "1.2"}]
    }
    adapter = _NeptuneCursorAdapter(conn)
    adapter.execute("MATCH (n) RETURN n")
    assert adapter.description == [("name",), ("version",)]
    assert adapter.fetchall() == [["Neptune", "1.2"]]

    # results returning list of non-dicts
    conn.execute_open_cypher_query.return_value = {"results": [100, 200]}
    adapter.execute("MATCH (n) RETURN count(n)")
    assert adapter.description == [("val",)]
    assert adapter.fetchall() == [[100], [200]]

    # conn with run
    conn2 = MagicMock(spec=["run"])
    res2 = MagicMock()
    res2.keys.return_value = ["cnt"]
    res2.values.return_value = [[5]]
    conn2.run.return_value = res2
    adapter2 = _NeptuneCursorAdapter(conn2)
    adapter2.execute("RETURN 5")
    assert adapter2.description == [("cnt",)]
    assert adapter2.fetchall() == [[5]]


# ============================================================================
# 5. Full Lifecycle Sync & Async Connector Tests (Phase 2)
# ============================================================================


def test_kusto_connector_lifecycle():
    # Cached connection
    existing_conn = MagicMock()
    cached_c = KustoConnector(connection=existing_conn)
    assert cached_c.connect() is existing_conn

    # Missing driver
    with (
        patch.dict(
            sys.modules,
            {"azure.kusto.data": None, "azure.kusto.data.client": None},
        ),
        pytest.raises(DriverNotInstalledError),
    ):
        KustoConnector().connect()

    # Connection failure
    mock_drv = MagicMock()
    mock_drv.KustoClient.side_effect = RuntimeError("ADX connection failed")
    with (
        patch.dict(sys.modules, {"azure.kusto.data": mock_drv}),
        pytest.raises(ConnectionFailedError),
    ):
        KustoConnector().connect()

    # Successful connect
    mock_client = MagicMock(spec=["execute_query", "close"])
    mock_drv.KustoClient.side_effect = None
    mock_drv.KustoClient.return_value = mock_client
    with patch.dict(sys.modules, {"azure.kusto.data": mock_drv}):
        c = KustoConnector(database="test_db")
        assert c.connect() is mock_client

        # get_cursor with preset cursor
        preset_cur = MagicMock()
        c_pre = KustoConnector(cursor=preset_cur)
        with c_pre.get_cursor() as cur:
            assert cur is preset_cur

        # get_cursor with conn having cursor()
        mock_conn_cur = MagicMock()
        mock_cur = MagicMock()
        mock_conn_cur.cursor.return_value = mock_cur
        c_cur = KustoConnector(connection=mock_conn_cur)
        with c_cur.get_cursor() as cur:
            assert cur is mock_cur
        mock_cur.close.assert_called_once()

        # cursor without close method
        mock_cur_noclose = MagicMock(spec=["execute"])
        mock_conn_nc = MagicMock(spec=["cursor"])
        mock_conn_nc.cursor.return_value = mock_cur_noclose
        c_nc = KustoConnector(connection=mock_conn_nc)
        with c_nc.get_cursor() as cur:
            assert cur is mock_cur_noclose

        # get_cursor with adapter fallback
        with c.get_cursor() as cur:
            assert isinstance(cur, _KustoCursorAdapter)

        # test_connection
        mock_res = MagicMock(spec=["primary_results"])
        mock_tbl = MagicMock()
        mock_tbl.columns = [MagicMock(column_name="TableName")]
        mock_tbl.__iter__.return_value = [
            MagicMock(as_dict=lambda: {"TableName": "Metrics"})
        ]
        mock_res.primary_results = [mock_tbl]
        mock_client.execute_query.return_value = mock_res
        res = c.test_connection()
        assert res["status"] == "healthy"

        # introspect_schema success and error
        with patch(
            "query_builder.connectors.kusto.introspect_kusto",
            return_value={"tables": {}},
        ):
            assert c.introspect_schema() == {"tables": {}}

        with (
            patch(
                "query_builder.connectors.kusto.introspect_kusto",
                side_effect=RuntimeError("Kusto introspect error"),
            ),
            pytest.raises(IntrospectionError),
        ):
            c.introspect_schema()


def test_async_kusto_connector_lifecycle():
    async def _test():
        conn = AsyncKustoConnector(database="test_db")

        # Cached connection
        mock_conn = MagicMock()
        cached_c = AsyncKustoConnector(connection=mock_conn)
        assert await cached_c.connect() is mock_conn

        # Missing driver
        with (
            patch.dict(
                sys.modules,
                {"azure.kusto.data": None, "azure.kusto.data.client": None},
            ),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection error
        mock_drv = MagicMock()
        mock_drv.KustoClient.side_effect = RuntimeError("ADX async failed")
        with (
            patch.dict(sys.modules, {"azure.kusto.data": mock_drv}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # execute_raw with cursor on connection
        mock_client = MagicMock()
        mock_cur = MagicMock()
        mock_cur.description = [("val",)]
        mock_cur.fetchall.return_value = [[123]]
        mock_client.cursor.return_value = mock_cur
        mock_drv.KustoClient.side_effect = None
        mock_drv.KustoClient.return_value = mock_client
        with patch.dict(sys.modules, {"azure.kusto.data": mock_drv}):
            c_exec = AsyncKustoConnector()
            cols, rows, lat = await c_exec.execute_raw(".show tables", [1])
            assert cols == ["val"]
            assert rows == [{"val": 123}]
            assert lat >= 0

            # execute_raw with adapter (no cursor on conn)
            client_no_cur = MagicMock(spec=["execute_query", "close"])
            mock_res = MagicMock(spec=["primary_results"])
            mock_tbl = MagicMock()
            mock_tbl.columns = [MagicMock(column_name="tbl")]
            mock_tbl.__iter__.return_value = [
                MagicMock(as_dict=lambda: {"tbl": "Logs"})
            ]
            mock_res.primary_results = [mock_tbl]
            client_no_cur.execute_query.return_value = mock_res
            c_adapter = AsyncKustoConnector(connection=client_no_cur)
            cols2, rows2, _ = await c_adapter.execute_raw(".show tables")
            assert cols2 == ["tbl"]
            assert rows2 == [{"tbl": "Logs"}]

            # test_connection
            t_res = await c_adapter.test_connection()
            assert t_res["status"] == "healthy"

            # introspect_schema success and error
            with patch(
                "query_builder.connectors.kusto.introspect_kusto",
                return_value={"tables": {}},
            ):
                assert await c_adapter.introspect_schema() == {"tables": {}}

            with (
                patch(
                    "query_builder.connectors.kusto.introspect_kusto",
                    side_effect=RuntimeError("Async introspect error"),
                ),
                pytest.raises(IntrospectionError),
            ):
                await c_adapter.introspect_schema()

    asyncio.run(_test())


def test_prometheus_connector_lifecycle():
    # Cached connection
    existing_conn = MagicMock()
    cached_c = PrometheusConnector(connection=existing_conn)
    assert cached_c.connect() is existing_conn

    # Missing driver
    with (
        patch.dict(
            sys.modules,
            {"prometheus_api_client": None, "requests": None, "httpx": None},
        ),
        pytest.raises(DriverNotInstalledError),
    ):
        PrometheusConnector().connect()

    # Connection failure
    mock_drv = MagicMock()
    mock_drv.PrometheusConnect.side_effect = RuntimeError("Prometheus refused")
    with (
        patch.dict(sys.modules, {"prometheus_api_client": mock_drv}),
        pytest.raises(ConnectionFailedError),
    ):
        PrometheusConnector().connect()

    # Successful connect
    mock_client = MagicMock(spec=["all_metrics", "custom_query"])
    mock_client.all_metrics.return_value = ["cpu"]
    mock_drv.PrometheusConnect.side_effect = None
    mock_drv.PrometheusConnect.return_value = mock_client
    with patch.dict(sys.modules, {"prometheus_api_client": mock_drv}):
        c = PrometheusConnector()
        assert c.connect() is mock_client

        # preset cursor
        preset_cur = MagicMock()
        c_pre = PrometheusConnector(cursor=preset_cur)
        with c_pre.get_cursor() as cur:
            assert cur is preset_cur

        # conn with cursor()
        mock_conn_cur = MagicMock()
        mock_cur = MagicMock()
        mock_conn_cur.cursor.return_value = mock_cur
        c_cur = PrometheusConnector(connection=mock_conn_cur)
        with c_cur.get_cursor() as cur:
            assert cur is mock_cur
        mock_cur.close.assert_called_once()

        # cursor without close method
        mock_cur_noclose = MagicMock(spec=["execute"])
        mock_conn_nc = MagicMock(spec=["cursor"])
        mock_conn_nc.cursor.return_value = mock_cur_noclose
        c_nc = PrometheusConnector(connection=mock_conn_nc)
        with c_nc.get_cursor() as cur:
            assert cur is mock_cur_noclose

        # adapter fallback
        with c.get_cursor() as cur:
            assert isinstance(cur, _PrometheusCursorAdapter)

        # test_connection
        res = c.test_connection()
        assert res["status"] == "healthy"

        # introspect_schema success and error
        with patch(
            "query_builder.connectors.prometheus.introspect_prometheus",
            return_value={"tables": {}},
        ):
            assert c.introspect_schema() == {"tables": {}}

        with (
            patch(
                "query_builder.connectors.prometheus.introspect_prometheus",
                side_effect=RuntimeError("Prometheus introspect error"),
            ),
            pytest.raises(IntrospectionError),
        ):
            c.introspect_schema()

    # Connect when driver does not have PrometheusConnect
    raw_driver = MagicMock(spec=["get"])
    with patch.dict(sys.modules, {"prometheus_api_client": raw_driver}):
        c_raw = PrometheusConnector()
        assert c_raw.connect() is raw_driver


def test_async_prometheus_connector_lifecycle():
    async def _test():
        conn = AsyncPrometheusConnector()

        # Cached connection
        mock_conn = MagicMock()
        cached_c = AsyncPrometheusConnector(connection=mock_conn)
        assert await cached_c.connect() is mock_conn

        # Missing driver
        with (
            patch.dict(
                sys.modules,
                {"prometheus_api_client": None, "requests": None, "httpx": None},
            ),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection error
        mock_drv = MagicMock()
        mock_drv.PrometheusConnect.side_effect = RuntimeError("Prom async fail")
        with (
            patch.dict(sys.modules, {"prometheus_api_client": mock_drv}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # execute_raw with cursor on conn
        mock_client = MagicMock()
        mock_cur = MagicMock()
        mock_cur.description = [("metric",)]
        mock_cur.fetchall.return_value = [["up"]]
        mock_client.cursor.return_value = mock_cur
        mock_drv.PrometheusConnect.side_effect = None
        mock_drv.PrometheusConnect.return_value = mock_client
        with patch.dict(sys.modules, {"prometheus_api_client": mock_drv}):
            c_exec = AsyncPrometheusConnector()
            cols, rows, lat = await c_exec.execute_raw("up", [1])
            assert cols == ["metric"]
            assert rows == [{"metric": "up"}]
            assert lat >= 0

            # execute_raw with adapter
            client_no_cur = MagicMock(spec=["all_metrics", "custom_query"])
            client_no_cur.all_metrics.return_value = ["cpu_util"]
            c_adapter = AsyncPrometheusConnector(connection=client_no_cur)
            cols2, rows2, _ = await c_adapter.execute_raw(
                "/api/v1/label/__name__/values"
            )
            assert cols2 == ["metric_name"]
            assert rows2 == [{"metric_name": "cpu_util"}]

            # test_connection
            t_res = await c_adapter.test_connection()
            assert t_res["status"] == "healthy"

            # introspect_schema success and error
            with patch(
                "query_builder.connectors.prometheus.introspect_prometheus",
                return_value={"tables": {}},
            ):
                assert await c_adapter.introspect_schema() == {"tables": {}}

            with (
                patch(
                    "query_builder.connectors.prometheus.introspect_prometheus",
                    side_effect=RuntimeError("Async prom introspect error"),
                ),
                pytest.raises(IntrospectionError),
            ):
                await c_adapter.introspect_schema()

        # Connect when driver does not have PrometheusConnect
        raw_driver = MagicMock(spec=["get"])
        with patch.dict(sys.modules, {"prometheus_api_client": raw_driver}):
            c_raw = AsyncPrometheusConnector()
            assert await c_raw.connect() is raw_driver

    asyncio.run(_test())


def test_victoriametrics_connector_lifecycle():
    # Cached connection
    existing_conn = MagicMock()
    cached_c = VictoriaMetricsConnector(connection=existing_conn)
    assert cached_c.connect() is existing_conn

    # Missing driver
    with (
        patch.dict(sys.modules, {"requests": None, "httpx": None}),
        pytest.raises(DriverNotInstalledError),
    ):
        VictoriaMetricsConnector().connect()

    # Connection failure
    mock_drv = MagicMock()
    mock_drv.Client.side_effect = RuntimeError("VM connect failed")
    mock_drv.Session.side_effect = RuntimeError("VM connect failed")
    with (
        patch.dict(sys.modules, {"httpx": mock_drv, "requests": mock_drv}),
        pytest.raises(ConnectionFailedError),
    ):
        VictoriaMetricsConnector().connect()

    # Successful connect
    mock_session = MagicMock()
    mock_drv.Client.side_effect = None
    mock_drv.Client.return_value = mock_session
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": ["vm_metric"]}
    mock_session.get.return_value = mock_resp
    with patch.dict(sys.modules, {"httpx": mock_drv, "requests": mock_drv}):
        c = VictoriaMetricsConnector()
        assert c.connect() is mock_session

        # preset cursor
        preset_cur = MagicMock()
        c_pre = VictoriaMetricsConnector(cursor=preset_cur)
        with c_pre.get_cursor() as cur:
            assert cur is preset_cur

        # conn with cursor()
        mock_conn_cur = MagicMock()
        mock_cur = MagicMock()
        mock_conn_cur.cursor.return_value = mock_cur
        c_cur = VictoriaMetricsConnector(connection=mock_conn_cur)
        with c_cur.get_cursor() as cur:
            assert cur is mock_cur
        mock_cur.close.assert_called_once()

        # conn with cursor() without close
        mock_conn_cur_nc = MagicMock(spec=["cursor"])
        mock_cur_nc = MagicMock(spec=["execute"])
        mock_conn_cur_nc.cursor.return_value = mock_cur_nc
        c_cur_nc = VictoriaMetricsConnector(connection=mock_conn_cur_nc)
        with c_cur_nc.get_cursor() as cur:
            assert cur is mock_cur_nc

        # adapter fallback
        c_adapt = VictoriaMetricsConnector(connection=MagicMock(spec=["get"]))
        with c_adapt.get_cursor() as cur:
            assert isinstance(cur, _VictoriaMetricsCursorAdapter)

        # test_connection
        res = c.test_connection()
        assert res["status"] == "healthy"

        # introspect_schema success and error
        with patch(
            "query_builder.connectors.victoriametrics.introspect_victoriametrics",
            return_value={"tables": {}},
        ):
            assert c.introspect_schema() == {"tables": {}}

        with (
            patch(
                "query_builder.connectors.victoriametrics.introspect_victoriametrics",
                side_effect=RuntimeError("VM introspect error"),
            ),
            pytest.raises(IntrospectionError),
        ):
            c.introspect_schema()

    # Connect when driver has no Client
    raw_driver = MagicMock(spec=["get"])
    with patch.dict(sys.modules, {"httpx": None, "requests": raw_driver}):
        c_raw = VictoriaMetricsConnector()
        assert c_raw.connect() is raw_driver


def test_async_victoriametrics_connector_lifecycle():
    async def _test():
        conn = AsyncVictoriaMetricsConnector()

        # Cached connection
        mock_conn = MagicMock()
        cached_c = AsyncVictoriaMetricsConnector(connection=mock_conn)
        assert await cached_c.connect() is mock_conn

        # Missing driver
        with (
            patch.dict(sys.modules, {"httpx": None, "requests": None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection error
        mock_drv = MagicMock()
        mock_drv.AsyncClient.side_effect = RuntimeError("VM async failed")
        with (
            patch.dict(sys.modules, {"httpx": mock_drv}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # execute_raw with cursor on conn
        mock_client = MagicMock()
        mock_cur = MagicMock()
        mock_cur.description = [("val",)]
        mock_cur.fetchall.return_value = [[42]]
        mock_client.cursor.return_value = mock_cur
        mock_drv.AsyncClient.side_effect = None
        mock_drv.AsyncClient.return_value = mock_client
        with patch.dict(sys.modules, {"httpx": mock_drv}):
            c_exec = AsyncVictoriaMetricsConnector()
            cols, rows, lat = await c_exec.execute_raw("SELECT 42", [1])
            assert cols == ["val"]
            assert rows == [{"val": 42}]
            assert lat >= 0

            # execute_raw with adapter
            client_no_cur = MagicMock(spec=["get"])
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"data": ["metric_vm"]}
            client_no_cur.get.return_value = mock_resp
            c_adapter = AsyncVictoriaMetricsConnector(connection=client_no_cur)
            cols2, rows2, _ = await c_adapter.execute_raw(
                "/api/v1/label/__name__/values"
            )
            assert cols2 == ["metric_name"]
            assert rows2 == [{"metric_name": "metric_vm"}]

            # test_connection
            t_res = await c_adapter.test_connection()
            assert t_res["status"] == "healthy"

            # introspect_schema success and error
            with patch(
                "query_builder.connectors.victoriametrics.introspect_victoriametrics",
                return_value={"tables": {}},
            ):
                assert await c_adapter.introspect_schema() == {"tables": {}}

            with (
                patch(
                    "query_builder.connectors.victoriametrics.introspect_victoriametrics",
                    side_effect=RuntimeError("Async VM introspect error"),
                ),
                pytest.raises(IntrospectionError),
            ):
                await c_adapter.introspect_schema()

            # Coroutine response handling with running loop
            async def coro_resp():
                r = MagicMock()
                r.json.return_value = {"data": ["vm_metric"]}
                return r

            http_async = MagicMock(spec=["get"])
            http_async.get.return_value = coro_resp()
            adapt_coro = _VictoriaMetricsCursorAdapter(http_async)
            adapt_coro.execute("/api/v1/label/__name__/values")
            assert adapt_coro.fetchall() == [["vm_metric"]]

            # Coroutine error branch
            async def bad_coro():
                raise RuntimeError("Coro failed")

            http_bad = MagicMock(spec=["get"])
            http_bad.get.return_value = bad_coro()
            adapt_bad = _VictoriaMetricsCursorAdapter(http_bad)
            adapt_bad.execute("/api/v1/label/__name__/values")

        # Connect when driver has no AsyncClient
        raw_driver = MagicMock(spec=["get"])
        with patch.dict(sys.modules, {"httpx": raw_driver}):
            c_raw = AsyncVictoriaMetricsConnector()
            assert await c_raw.connect() is raw_driver

    asyncio.run(_test())


def test_timestream_connector_lifecycle():
    # Cached connection
    existing_conn = MagicMock()
    cached_c = TimestreamConnector(connection=existing_conn)
    assert cached_c.connect() is existing_conn

    # Missing driver
    with (
        patch.dict(sys.modules, {"boto3": None}),
        pytest.raises(DriverNotInstalledError),
    ):
        TimestreamConnector().connect()

    # Connection failure
    mock_boto = MagicMock()
    mock_boto.client.side_effect = RuntimeError("Boto3 timestream failed")
    with (
        patch.dict(sys.modules, {"boto3": mock_boto}),
        pytest.raises(ConnectionFailedError),
    ):
        TimestreamConnector().connect()

    # Successful connect
    mock_client = MagicMock(spec=["query", "close"])
    mock_boto.client.side_effect = None
    mock_boto.client.return_value = mock_client
    with patch.dict(sys.modules, {"boto3": mock_boto}):
        c = TimestreamConnector()
        assert c.connect() is mock_client

        # preset cursor
        preset_cur = MagicMock()
        c_pre = TimestreamConnector(cursor=preset_cur)
        with c_pre.get_cursor() as cur:
            assert cur is preset_cur

        # conn with cursor()
        mock_conn_cur = MagicMock()
        mock_cur = MagicMock()
        mock_conn_cur.cursor.return_value = mock_cur
        c_cur = TimestreamConnector(connection=mock_conn_cur)
        with c_cur.get_cursor() as cur:
            assert cur is mock_cur
        mock_cur.close.assert_called_once()

        # cursor without close method
        mock_cur_noclose = MagicMock(spec=["execute"])
        mock_conn_nc = MagicMock(spec=["cursor"])
        mock_conn_nc.cursor.return_value = mock_cur_noclose
        c_nc = TimestreamConnector(connection=mock_conn_nc)
        with c_nc.get_cursor() as cur:
            assert cur is mock_cur_noclose

        # adapter fallback
        with c.get_cursor() as cur:
            assert isinstance(cur, _TimestreamCursorAdapter)

        # test_connection
        mock_client.query.return_value = {
            "ColumnInfo": [{"Name": "t"}],
            "Rows": [{"Data": [{"ScalarValue": "1"}]}],
        }
        res = c.test_connection()
        assert res["status"] == "healthy"

        # introspect_schema success and error
        with patch(
            "query_builder.connectors.timestream.introspect_timestream",
            return_value={"tables": {}},
        ):
            assert c.introspect_schema() == {"tables": {}}

        with (
            patch(
                "query_builder.connectors.timestream.introspect_timestream",
                side_effect=RuntimeError("Timestream introspect error"),
            ),
            pytest.raises(IntrospectionError),
        ):
            c.introspect_schema()


def test_async_timestream_connector_lifecycle():
    async def _test():
        conn = AsyncTimestreamConnector()

        # Cached connection
        mock_conn = MagicMock()
        cached_c = AsyncTimestreamConnector(connection=mock_conn)
        assert await cached_c.connect() is mock_conn

        # Missing driver
        with (
            patch.dict(sys.modules, {"boto3": None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection error
        mock_boto = MagicMock()
        mock_boto.client.side_effect = RuntimeError("Boto3 async fail")
        with (
            patch.dict(sys.modules, {"boto3": mock_boto}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # execute_raw with cursor on conn
        mock_client = MagicMock()
        mock_cur = MagicMock()
        mock_cur.description = [("val",)]
        mock_cur.fetchall.return_value = [[50]]
        mock_client.cursor.return_value = mock_cur
        mock_boto.client.side_effect = None
        mock_boto.client.return_value = mock_client
        with patch.dict(sys.modules, {"boto3": mock_boto}):
            c_exec = AsyncTimestreamConnector()
            cols, rows, lat = await c_exec.execute_raw("SELECT 50", [1])
            assert cols == ["val"]
            assert rows == [{"val": 50}]
            assert lat >= 0

            # execute_raw with adapter
            client_no_cur = MagicMock(spec=["query", "close"])
            client_no_cur.query.return_value = {
                "ColumnInfo": [{"Name": "res"}],
                "Rows": [{"Data": [{"ScalarValue": "val1"}]}],
            }
            c_adapter = AsyncTimestreamConnector(connection=client_no_cur)
            cols2, rows2, _ = await c_adapter.execute_raw("SELECT 1")
            assert cols2 == ["res"]
            assert rows2 == [{"res": "val1"}]

            # test_connection
            t_res = await c_adapter.test_connection()
            assert t_res["status"] == "healthy"

            # introspect_schema success and error
            with patch(
                "query_builder.connectors.timestream.introspect_timestream",
                return_value={"tables": {}},
            ):
                assert await c_adapter.introspect_schema() == {"tables": {}}

            with (
                patch(
                    "query_builder.connectors.timestream.introspect_timestream",
                    side_effect=RuntimeError("Async timestream introspect error"),
                ),
                pytest.raises(IntrospectionError),
            ):
                await c_adapter.introspect_schema()

    asyncio.run(_test())


def test_memgraph_connector_lifecycle():
    # Cached connection
    existing_conn = MagicMock()
    cached_c = MemgraphConnector(connection=existing_conn)
    assert cached_c.connect() is existing_conn

    # Missing driver
    with (
        patch.dict(sys.modules, {"neo4j": None, "gqlalchemy": None}),
        pytest.raises(DriverNotInstalledError),
    ):
        MemgraphConnector().connect()

    # Connection failure
    mock_neo = MagicMock()
    mock_neo.GraphDatabase.driver.side_effect = RuntimeError("Memgraph fail")
    with (
        patch.dict(sys.modules, {"neo4j": mock_neo}),
        pytest.raises(ConnectionFailedError),
    ):
        MemgraphConnector().connect()

    # Successful connect
    mock_driver = MagicMock(spec=["session", "close"])
    mock_session = MagicMock()
    mock_driver.session.return_value = mock_session
    mock_neo.GraphDatabase.driver.side_effect = None
    mock_neo.GraphDatabase.driver.return_value = mock_driver

    with patch.dict(sys.modules, {"neo4j": mock_neo}):
        c = MemgraphConnector()
        assert c.connect() is mock_driver

        # preset cursor
        preset_cur = MagicMock()
        c_pre = MemgraphConnector(cursor=preset_cur)
        with c_pre.get_cursor() as cur:
            assert cur is preset_cur

        # conn with session()
        with c.get_cursor() as cur:
            assert isinstance(cur, _MemgraphCursorAdapter)
        mock_session.close.assert_called_once()

        # session without close method
        sess_noclose = MagicMock(spec=["run"])
        conn_sess_nc = MagicMock(spec=["session"])
        conn_sess_nc.session.return_value = sess_noclose
        c_snc = MemgraphConnector(connection=conn_sess_nc)
        with c_snc.get_cursor() as cur:
            assert isinstance(cur, _MemgraphCursorAdapter)

        # conn with cursor()
        mock_conn_cur = MagicMock(spec=["cursor"])
        mock_cur = MagicMock()
        mock_conn_cur.cursor.return_value = mock_cur
        c_cur = MemgraphConnector(connection=mock_conn_cur)
        with c_cur.get_cursor() as cur:
            assert cur is mock_cur
        mock_cur.close.assert_called_once()

        # cursor without close method
        cur_noclose = MagicMock(spec=["execute"])
        mock_conn_cur_nc = MagicMock(spec=["cursor"])
        mock_conn_cur_nc.cursor.return_value = cur_noclose
        c_cnc = MemgraphConnector(connection=mock_conn_cur_nc)
        with c_cnc.get_cursor() as cur:
            assert cur is cur_noclose

        # adapter fallback (conn without session or cursor)
        conn_bare = MagicMock(spec=["execute"])
        c_bare = MemgraphConnector(connection=conn_bare)
        with c_bare.get_cursor() as cur:
            assert isinstance(cur, _MemgraphCursorAdapter)

        # test_connection
        mock_res = MagicMock()
        mock_res.keys.return_value = ["label"]
        mock_rec = MagicMock()
        mock_rec.values.return_value = ["Node"]
        mock_res.__iter__.return_value = [mock_rec]
        mock_session.run.return_value = mock_res
        res = c.test_connection()
        assert res["status"] == "healthy"

        # introspect_schema success and error
        with patch(
            "query_builder.connectors.memgraph.introspect_memgraph",
            return_value={"tables": {}},
        ):
            assert c.introspect_schema() == {"tables": {}}

        with (
            patch(
                "query_builder.connectors.memgraph.introspect_memgraph",
                side_effect=RuntimeError("Memgraph introspect error"),
            ),
            pytest.raises(IntrospectionError),
        ):
            c.introspect_schema()

    # Connect when driver has no GraphDatabase
    raw_neo = MagicMock(spec=["connect"])
    mock_raw_conn = MagicMock()
    raw_neo.connect.return_value = mock_raw_conn
    with patch.dict(sys.modules, {"neo4j": raw_neo}):
        c_raw = MemgraphConnector()
        assert c_raw.connect() is mock_raw_conn


def test_async_memgraph_connector_lifecycle():
    async def _test():
        conn = AsyncMemgraphConnector()

        # Cached connection
        mock_conn = MagicMock()
        cached_c = AsyncMemgraphConnector(connection=mock_conn)
        assert await cached_c.connect() is mock_conn

        # Missing driver
        with (
            patch.dict(sys.modules, {"neo4j": None, "mgclient": None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection error
        mock_neo = MagicMock()
        mock_neo.AsyncGraphDatabase.driver.side_effect = RuntimeError(
            "Memgraph async fail"
        )
        mock_neo.GraphDatabase.driver.side_effect = RuntimeError("Memgraph async fail")
        with (
            patch.dict(sys.modules, {"neo4j": mock_neo}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # execute_raw with cursor on conn
        mock_driver = MagicMock()
        mock_cur = MagicMock()
        mock_cur.description = [("node",)]
        mock_cur.fetchall.return_value = [["Person"]]
        mock_driver.cursor.return_value = mock_cur
        mock_neo.AsyncGraphDatabase.driver.side_effect = None
        mock_neo.AsyncGraphDatabase.driver.return_value = mock_driver
        with patch.dict(sys.modules, {"neo4j": mock_neo}):
            c_exec = AsyncMemgraphConnector()
            cols, rows, lat = await c_exec.execute_raw("MATCH (n) RETURN n", [1])
            assert cols == ["node"]
            assert rows == [{"node": "Person"}]
            assert lat >= 0

            # execute_raw with session/adapter
            driver_no_cur = MagicMock(spec=["session", "close"])
            mock_sess = MagicMock(spec=["run", "close"])
            mock_res = MagicMock()
            mock_res.keys.return_value = ["l"]
            mock_res.values.return_value = [["Label1"]]
            mock_sess.run.return_value = mock_res
            driver_no_cur.session.return_value = mock_sess
            c_adapter = AsyncMemgraphConnector(connection=driver_no_cur)
            cols2, rows2, _ = await c_adapter.execute_raw("MATCH (n) RETURN n")
            assert cols2 == ["l"]
            assert rows2 == [{"l": "Label1"}]

            # session without close
            driver_nc = MagicMock(spec=["session"])
            mock_sess_nc = MagicMock(spec=["run"])
            mock_sess_nc.run.return_value = mock_res
            driver_nc.session.return_value = mock_sess_nc
            c_anc = AsyncMemgraphConnector(connection=driver_nc)
            await c_anc.execute_raw("MATCH (n) RETURN n")

            # test_connection
            t_res = await c_adapter.test_connection()
            assert t_res["status"] == "healthy"

            # introspect_schema success and error
            with patch(
                "query_builder.connectors.memgraph.introspect_memgraph",
                return_value={"tables": {}},
            ):
                assert await c_adapter.introspect_schema() == {"tables": {}}

            with (
                patch(
                    "query_builder.connectors.memgraph.introspect_memgraph",
                    side_effect=RuntimeError("Async memgraph introspect error"),
                ),
                pytest.raises(IntrospectionError),
            ):
                await c_adapter.introspect_schema()

        # Fallback when driver only has GraphDatabase (not AsyncGraphDatabase)
        drv_sync_only = MagicMock(spec=["GraphDatabase"])
        drv_sync_only.GraphDatabase.driver.return_value = mock_driver
        with patch.dict(sys.modules, {"neo4j": drv_sync_only}):
            c_sync_drv = AsyncMemgraphConnector()
            assert await c_sync_drv.connect() is mock_driver

        # Fallback when driver is bare
        drv_bare = object()
        with patch.dict(sys.modules, {"neo4j": drv_bare}):
            c_bare_drv = AsyncMemgraphConnector()
            assert await c_bare_drv.connect() is drv_bare

    asyncio.run(_test())


def test_neptune_connector_lifecycle():
    # Cached connection
    existing_conn = MagicMock()
    cached_c = NeptuneConnector(connection=existing_conn)
    assert cached_c.connect() is existing_conn

    # Missing driver
    with (
        patch.dict(sys.modules, {"boto3": None, "neo4j": None}),
        pytest.raises(DriverNotInstalledError),
    ):
        NeptuneConnector().connect()

    # Connection failure
    mock_boto = MagicMock()
    mock_boto.client.side_effect = RuntimeError("Neptune connect fail")
    with (
        patch.dict(sys.modules, {"boto3": mock_boto}),
        pytest.raises(ConnectionFailedError),
    ):
        NeptuneConnector().connect()

    # Successful connect
    mock_client = MagicMock(spec=["execute_open_cypher_query", "close"])
    mock_boto.client.side_effect = None
    mock_boto.client.return_value = mock_client

    with patch.dict(sys.modules, {"boto3": mock_boto}):
        c = NeptuneConnector()
        assert c.connect() is mock_client

        # preset cursor
        preset_cur = MagicMock()
        c_pre = NeptuneConnector(cursor=preset_cur)
        with c_pre.get_cursor() as cur:
            assert cur is preset_cur

        # conn with session()
        mock_conn_sess = MagicMock(spec=["session"])
        mock_sess = MagicMock()
        mock_conn_sess.session.return_value = mock_sess
        c_sess = NeptuneConnector(connection=mock_conn_sess)
        with c_sess.get_cursor() as cur:
            assert isinstance(cur, _NeptuneCursorAdapter)
        mock_sess.close.assert_called_once()

        # session without close
        sess_nc = MagicMock(spec=["run"])
        mock_conn_snc = MagicMock(spec=["session"])
        mock_conn_snc.session.return_value = sess_nc
        c_snc = NeptuneConnector(connection=mock_conn_snc)
        with c_snc.get_cursor() as cur:
            assert isinstance(cur, _NeptuneCursorAdapter)

        # conn with cursor()
        mock_conn_cur = MagicMock(spec=["cursor"])
        mock_cur = MagicMock()
        mock_conn_cur.cursor.return_value = mock_cur
        c_cur = NeptuneConnector(connection=mock_conn_cur)
        with c_cur.get_cursor() as cur:
            assert cur is mock_cur
        mock_cur.close.assert_called_once()

        # cursor without close
        cur_nc = MagicMock(spec=["execute"])
        mock_conn_cnc = MagicMock(spec=["cursor"])
        mock_conn_cnc.cursor.return_value = cur_nc
        c_cnc = NeptuneConnector(connection=mock_conn_cnc)
        with c_cnc.get_cursor() as cur:
            assert cur is cur_nc

        # adapter fallback
        with c.get_cursor() as cur:
            assert isinstance(cur, _NeptuneCursorAdapter)

        # test_connection
        mock_client.execute_open_cypher_query.return_value = {
            "results": [{"label": "Entity"}]
        }
        res = c.test_connection()
        assert res["status"] == "healthy"

        # introspect_schema success and error
        with patch(
            "query_builder.connectors.neptune.introspect_neptune",
            return_value={"tables": {}},
        ):
            assert c.introspect_schema() == {"tables": {}}

        with (
            patch(
                "query_builder.connectors.neptune.introspect_neptune",
                side_effect=RuntimeError("Neptune introspect error"),
            ),
            pytest.raises(IntrospectionError),
        ):
            c.introspect_schema()

    # Connect when driver has GraphDatabase instead of client
    drv_graph = MagicMock(spec=["GraphDatabase"])
    mock_graph_client = MagicMock()
    drv_graph.GraphDatabase.driver.return_value = mock_graph_client
    with patch.dict(sys.modules, {"boto3": None, "neo4j": drv_graph}):
        c_graph = NeptuneConnector()
        assert c_graph.connect() is mock_graph_client

    # Connect when driver is bare
    drv_bare = object()
    with patch.dict(sys.modules, {"boto3": None, "neo4j": drv_bare}):
        c_bare = NeptuneConnector()
        assert c_bare.connect() is drv_bare


def test_async_neptune_connector_lifecycle():
    async def _test():
        conn = AsyncNeptuneConnector()

        # Cached connection
        mock_conn = MagicMock()
        cached_c = AsyncNeptuneConnector(connection=mock_conn)
        assert await cached_c.connect() is mock_conn

        # Missing driver
        with (
            patch.dict(sys.modules, {"boto3": None, "neo4j": None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection error
        mock_boto = MagicMock()
        mock_boto.AsyncGraphDatabase.driver.side_effect = RuntimeError(
            "Neptune async fail"
        )
        mock_boto.GraphDatabase.driver.side_effect = RuntimeError("Neptune async fail")
        with (
            patch.dict(sys.modules, {"boto3": mock_boto}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # execute_raw with cursor on conn
        mock_client = MagicMock()
        mock_cur = MagicMock()
        mock_cur.description = [("v",)]
        mock_cur.fetchall.return_value = [[1]]
        mock_client.cursor.return_value = mock_cur
        mock_boto.AsyncGraphDatabase.driver.side_effect = None
        mock_boto.AsyncGraphDatabase.driver.return_value = mock_client
        with patch.dict(sys.modules, {"boto3": mock_boto}):
            c_exec = AsyncNeptuneConnector()
            cols, rows, lat = await c_exec.execute_raw("MATCH (n) RETURN n", [1])
            assert cols == ["v"]
            assert rows == [{"v": 1}]
            assert lat >= 0

            # execute_raw with adapter
            client_no_cur = MagicMock(spec=["execute_open_cypher_query", "close"])
            client_no_cur.execute_open_cypher_query.return_value = {
                "results": [{"l": "Edge"}]
            }
            c_adapter = AsyncNeptuneConnector(connection=client_no_cur)
            cols2, rows2, _ = await c_adapter.execute_raw("MATCH (n) RETURN n")
            assert cols2 == ["l"]
            assert rows2 == [{"l": "Edge"}]

            # test_connection
            t_res = await c_adapter.test_connection()
            assert t_res["status"] == "healthy"

            # introspect_schema success and error
            with patch(
                "query_builder.connectors.neptune.introspect_neptune",
                return_value={"tables": {}},
            ):
                assert await c_adapter.introspect_schema() == {"tables": {}}

            with (
                patch(
                    "query_builder.connectors.neptune.introspect_neptune",
                    side_effect=RuntimeError("Async neptune introspect error"),
                ),
                pytest.raises(IntrospectionError),
            ):
                await c_adapter.introspect_schema()

        # Fallback when driver only has GraphDatabase
        drv_sync = MagicMock(spec=["GraphDatabase"])
        drv_sync.GraphDatabase.driver.return_value = mock_client
        with patch.dict(sys.modules, {"boto3": None, "neo4j": drv_sync}):
            c_sync = AsyncNeptuneConnector()
            assert await c_sync.connect() is mock_client

        # Fallback when driver is bare
        drv_bare = object()
        with patch.dict(sys.modules, {"boto3": None, "neo4j": drv_bare}):
            c_bare = AsyncNeptuneConnector()
            assert await c_bare.connect() is drv_bare

    asyncio.run(_test())


# ============================================================================
# 6. Introspection Tests (Phase 2)
# ============================================================================


def test_introspect_kusto_branches():
    mock_cur = MagicMock()
    mock_cur.execute.side_effect = [
        None,  # .show tables
        None,  # .show table Metrics schema
    ]
    mock_cur.fetchall.side_effect = [
        [["Metrics"], ["passwords"]],
        [["timestamp", "datetime"], ["user_id", "string"]],
    ]
    schema = introspect_kusto(mock_cur, database="mydb", filter_sensitive=True)
    assert any(k.lower() == "metrics" for k in schema["tables"])
    assert not any(k.lower() == "passwords" for k in schema["tables"])
    tbl_name = next(k for k in schema["tables"] if k.lower() == "metrics")
    col_names = [col["name"] for col in schema["tables"][tbl_name]["columns"]]
    assert "timestamp" in col_names
    assert "user_id" in col_names

    # Empty tables branch
    mock_empty_cur = MagicMock()
    mock_empty_cur.fetchall.return_value = []
    schema_empty = introspect_kusto(mock_empty_cur)
    assert schema_empty["tables"] == {}

    # Exception error wrapping
    mock_err_cur = MagicMock()
    mock_err_cur.execute.side_effect = RuntimeError("ADX syntax error")
    with pytest.raises(IntrospectionError):
        introspect_kusto(mock_err_cur)


def test_introspect_prometheus_branches():
    mock_cur = MagicMock()
    mock_cur.execute.side_effect = [
        None,  # metrics
        None,  # labels
    ]
    mock_cur.fetchall.side_effect = [
        [["http_requests_total"], ["process_cpu_seconds"]],
        [["method"], ["status"], ["user_id"]],
    ]
    schema = introspect_prometheus(mock_cur, filter_sensitive=True)
    assert any(k.lower() == "http_requests_total" for k in schema["tables"])
    tbl_name = next(k for k in schema["tables"] if k.lower() == "http_requests_total")
    cols = [c["name"] for c in schema["tables"][tbl_name]["columns"]]
    assert "timestamp" in cols
    assert "value" in cols
    assert "user_id" in cols

    # Empty metrics branch
    mock_empty = MagicMock()
    mock_empty.fetchall.return_value = []
    schema_empty = introspect_prometheus(mock_empty)
    assert "up" in schema_empty["tables"]

    # Error wrapping
    mock_err = MagicMock()
    mock_err.execute.side_effect = RuntimeError("Prom down")
    with pytest.raises(IntrospectionError):
        introspect_prometheus(mock_err)


def test_introspect_victoriametrics_branches():
    mock_cur = MagicMock()
    mock_cur.execute.side_effect = [
        None,
        None,
    ]
    mock_cur.fetchall.side_effect = [
        [["vm_requests_total"]],
        [["instance"], ["job"], ["secret_token"]],
    ]
    schema = introspect_victoriametrics(mock_cur, filter_sensitive=True)
    assert any(k.lower() == "vm_requests_total" for k in schema["tables"])
    tbl_name = next(k for k in schema["tables"] if k.lower() == "vm_requests_total")
    cols = [col["name"] for col in schema["tables"][tbl_name]["columns"]]
    assert "secret_token" not in cols

    # Empty branch
    mock_empty = MagicMock()
    mock_empty.fetchall.return_value = []
    schema_empty = introspect_victoriametrics(mock_empty)
    assert "vm_http_requests_total" in schema_empty["tables"]

    # Error wrapping
    mock_err = MagicMock()
    mock_err.execute.side_effect = RuntimeError("VM down")
    with pytest.raises(IntrospectionError):
        introspect_victoriametrics(mock_err)


def test_introspect_timestream_branches():
    mock_cur = MagicMock()
    mock_cur.execute.side_effect = [
        None,  # SHOW TABLES
        None,  # DESCRIBE mydb.IoTTelemetry
    ]
    mock_cur.fetchall.side_effect = [
        [["IoTTelemetry"]],
        [["time", "TIMESTAMP"], ["device_id", "VARCHAR"], ["temperature", "DOUBLE"]],
    ]
    schema = introspect_timestream(
        mock_cur, database_name="mydb", filter_sensitive=True
    )
    assert any(k.lower() == "iottelemetry" for k in schema["tables"])
    tbl_name = next(k for k in schema["tables"] if k.lower() == "iottelemetry")
    cols = [c["name"] for c in schema["tables"][tbl_name]["columns"]]
    assert "time" in cols
    assert "device_id" in cols

    # Empty tables branch
    mock_empty = MagicMock()
    mock_empty.fetchall.return_value = []
    schema_empty = introspect_timestream(mock_empty)
    assert schema_empty["tables"] == {}

    # Error wrapping
    mock_err = MagicMock()
    mock_err.execute.side_effect = RuntimeError("Timestream query error")
    with pytest.raises(IntrospectionError):
        introspect_timestream(mock_err)


def test_introspect_memgraph_branches():
    mock_cur = MagicMock()
    mock_cur.execute.side_effect = [
        None,  # labels
        None,  # constraint info
        None,  # relationship types
    ]
    mock_cur.fetchall.side_effect = [
        [["User"], ["Order"]],
        [["User", "id", "PRIMARY KEY"], ["User", "email", "UNIQUE"]],
        [["PLACED"], ["OWNS"]],
    ]
    schema = introspect_memgraph(mock_cur, filter_sensitive=True)
    assert any(k.lower() == "user" for k in schema["tables"])
    assert any(k.lower() == "order" for k in schema["tables"])

    # Empty branch
    mock_empty = MagicMock()
    mock_empty.fetchall.return_value = []
    schema_empty = introspect_memgraph(mock_empty)
    assert "Node" in schema_empty["tables"]

    # Error wrapping
    mock_err = MagicMock()
    mock_err.execute.side_effect = RuntimeError("Memgraph query error")
    with pytest.raises(IntrospectionError):
        introspect_memgraph(mock_err)


def test_introspect_neptune_branches():
    mock_cur = MagicMock()
    mock_cur.execute.side_effect = [
        None,  # db.labels
        None,  # db.propertyKeys
        None,  # db.relationshipTypes
    ]
    mock_cur.fetchall.side_effect = [
        [["Customer"], ["passwords"]],
        [["id"], ["name"]],
        [["PURCHASED"]],
    ]
    schema = introspect_neptune(mock_cur, filter_sensitive=True)
    assert any(k.lower() == "customer" for k in schema["tables"])
    assert not any(k.lower() == "passwords" for k in schema["tables"])
    tbl_name = next(k for k in schema["tables"] if k.lower() == "customer")
    cols = [col["name"] for col in schema["tables"][tbl_name]["columns"]]
    assert "id" in cols
    assert "user_id" in cols

    # Empty branch
    mock_empty = MagicMock()
    mock_empty.fetchall.return_value = []
    schema_empty = introspect_neptune(mock_empty)
    assert "Vertex" in schema_empty["tables"]

    # Error wrapping
    mock_err = MagicMock()
    mock_err.execute.side_effect = RuntimeError("Neptune query error")
    with pytest.raises(IntrospectionError):
        introspect_neptune(mock_err)
