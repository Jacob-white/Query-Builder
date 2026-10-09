"""
More regression tests for defects found by the live integration suite
(SQL Server, Trino/Presto, QuestDB). See tests/test_live_findings_regressions.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from query_builder.compiler import QueryCompiler
from query_builder.connectors.base import IntrospectionError
from query_builder.connectors.introspection import introspect_information_schema
from query_builder.connectors.mssql import MSSQLConnector
from query_builder.connectors.prestodb import PrestoDBConnector
from query_builder.connectors.questdb import QuestDBConnector
from query_builder.connectors.trino import TrinoConnector


# --- SQL Server ---------------------------------------------------------------
def test_mssql_statement_timeout_sets_the_driver_level_query_timeout():
    cur = MagicMock()
    low = MagicMock(spec=["query_timeout"])  # pymssql: connection._conn.query_timeout
    conn = MagicMock()
    conn._conn = low
    MSSQLConnector(connection=conn).apply_statement_timeout(cur, 2500)
    assert low.query_timeout == 3  # whole seconds, rounded up
    cur.execute.assert_called_once_with("SET LOCK_TIMEOUT 2500;")

    odbc = MagicMock(spec=["timeout"])  # pyodbc: connection.timeout
    MSSQLConnector(connection=odbc).apply_statement_timeout(MagicMock(), 100)
    assert odbc.timeout == 1

    bare = MagicMock(spec=[])  # unknown driver: still sets the lock timeout
    cur2 = MagicMock()
    MSSQLConnector(connection=bare).apply_statement_timeout(cur2, 1000)
    cur2.execute.assert_called_once_with("SET LOCK_TIMEOUT 1000;")


def test_mssql_introspection_reads_foreign_keys_from_referential_constraints():
    cur = MagicMock()
    cur.fetchall.side_effect = [
        [("child",), ("parent",)],
        [("child", "id", "int", "NO"), ("child", "pid", "int", "YES")],
        [("child", "id"), ("parent", "id")],
        [("child", "pid", "parent", "id")],
    ]
    snap = MSSQLConnector(cursor=cur).introspect_schema()
    assert snap["foreign_keys"] == [
        {
            "table": "child",
            "column": "pid",
            "foreign_table": "parent",
            "foreign_column": "id",
        }
    ]
    assert "referential_constraints" in cur.execute.call_args_list[-1].args[0]


def test_mssql_dialect_nested_queries_and_aggregates_are_valid_tsql():
    cte = {
        "table": "hi",
        "ctes": [
            {
                "name": "hi",
                "query": {
                    "table": "t",
                    "columns": ["id"],
                    "order_by": [{"column": "id", "direction": "asc"}],
                },
            }
        ],
        "columns": ["id"],
        "order_by": [{"column": "id", "direction": "asc"}],
    }
    sql = QueryCompiler(cte, dialect="mssql").compile()[0]
    inner = sql.split("AS (", 1)[1].split("\n)", 1)[0]
    assert "ORDER BY" not in inner and "OFFSET" not in inner  # illegal in a CTE
    assert "OFFSET" in sql.rsplit("\n)", 1)[1]  # the outer query is still paged

    agg = {
        "table": "t",
        "columns": [
            {"column": "x", "agg": "avg", "alias": "m"},
            {"column": "y", "agg": "count_distinct", "alias": "d"},
        ],
    }
    out = QueryCompiler(agg, dialect="mssql").compile()[0]
    assert "AVG(CAST([t1].[x] AS FLOAT))" in out  # integer AVG truncates in T-SQL
    assert "COUNT(DISTINCT [t1].[y])" in out
    pg = QueryCompiler(agg, dialect="postgres").compile()[0]
    assert 'AVG("t1"."x")' in pg


def test_grouped_count_query_names_its_derived_column():
    spec = {
        "table": "t",
        "columns": ["a", {"column": "b", "agg": "sum", "alias": "s"}],
    }
    count_sql = QueryCompiler(spec, dialect="mssql").compile()[2]
    assert "SELECT 1 AS qb_one" in count_sql  # SQL Server error 8155 otherwise


# --- Trino / Presto -----------------------------------------------------------
def test_trino_family_catalog_queries_use_qmark_and_no_semicolon():
    cur = MagicMock()
    cur.execute.side_effect = [None, None, RuntimeError("no constraints"), None]
    cur.fetchall.side_effect = [[("t",)], [("t", "id", "integer", "NO")], []]
    snap = introspect_information_schema(
        cur, schema_name="default", placeholder="?", pk_guess=False
    )
    for call in cur.execute.call_args_list:
        sql = call.args[0]
        assert "%s" not in sql and not sql.rstrip().endswith(";")
    assert snap["tables"]["t"]["columns"][0]["is_primary"] is False  # no id-guess

    for cls in (TrinoConnector, PrestoDBConnector):
        c = MagicMock()
        c.fetchone.return_value = ("1",)
        cls(cursor=c).test_connection()
        assert c.execute.call_args_list[-1].args[0] == "SELECT version()"


def test_trino_and_presto_introspection_pass_qmark_placeholder():
    for cls in (TrinoConnector, PrestoDBConnector):
        cur = MagicMock()
        cur.fetchall.side_effect = [[("t",)], [("t", "id", "integer", "NO")], []]
        cls(cursor=cur).introspect_schema()
        assert "?" in cur.execute.call_args_list[0].args[0]
        assert "%s" not in cur.execute.call_args_list[0].args[0]


# --- QuestDB ---------------------------------------------------------------------
def test_questdb_pagination_and_aggregates():
    sql, params, _, _ = QueryCompiler(
        {"table": "t", "columns": ["a"], "limit": 5, "offset": 10}, dialect="questdb"
    ).compile()
    assert sql.endswith("LIMIT 10, 15") and params == []  # no OFFSET keyword
    default = QueryCompiler(
        {"table": "t", "columns": ["a"]}, dialect="questdb"
    ).compile()[0]
    assert default.endswith("LIMIT 0, 50")
    q = QueryCompiler(
        {
            "table": "t",
            "columns": [{"column": "a", "agg": "count_distinct", "alias": "n"}],
        },
        dialect="questdb",
    ).compile()[0]
    assert "count_distinct(" in q and "COUNT(DISTINCT" not in q


def test_questdb_introspection_uses_native_catalog_functions():
    cur = MagicMock()
    cur.fetchall.side_effect = [
        [("trades",), ("telemetry",), ("it's",)],
        [("ts", "TIMESTAMP"), ("user_id", "INT")],
        [("v", "DOUBLE")],
    ]
    snap = QuestDBConnector(cursor=cur).introspect_schema()
    assert sorted(snap["tables"]) == ["it's", "trades"]  # telemetry* is internal
    assert snap["tables"]["it's"]["has_user_id"] is True  # tables go in sorted order
    assert "table_columns('it''s')" in cur.execute.call_args_list[-2].args[0]

    bad = MagicMock()
    bad.execute.side_effect = RuntimeError("boom")
    with pytest.raises(IntrospectionError, match="QuestDB"):
        QuestDBConnector(cursor=bad).introspect_schema()
