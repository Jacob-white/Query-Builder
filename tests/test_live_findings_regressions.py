"""
Regression tests for defects found by the live integration suite
(tests/integration, docs/TESTING_LIVE.md). Each one reproduces, without a
database, the behaviour that failed against a real engine.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from query_builder.compiler import QueryCompiler
from query_builder.connectors.clickhouse import ClickHouseConnector, ClickHouseCursor
from query_builder.connectors.mysql import MySQLConnector
from query_builder.connectors.postgres import PostgresConnector
from query_builder.dialects import get_dialect


# --- ClickHouse: clickhouse-connect clients have no cursor()/execute() --------
class _FakeResult:
    def __init__(self, names, rows):
        self.column_names = names
        self.result_rows = rows


class _FakeClient:
    """Mimics clickhouse_connect's HttpClient surface (query/command only)."""

    def __init__(self):
        self.calls = []

    def query(self, sql, parameters=None, settings=None):
        self.calls.append(("query", sql, parameters, settings))
        return _FakeResult(["a", "b"], [(1, "x"), (2, "y")])

    def command(self, sql, parameters=None, settings=None):
        self.calls.append(("command", sql, parameters, settings))


def test_clickhouse_cursor_adapts_query_command_and_set_statements():
    client = _FakeClient()
    cur = ClickHouseCursor(client)
    cur.execute("SET max_execution_time = 4;")
    cur.execute("SET some_name = 'text'")
    assert client.calls == []  # SET is kept client-side
    assert cur.execute("SELECT a, b FROM t WHERE a = %s", [1]) is cur
    assert cur.description == [("a", None), ("b", None)]
    assert cur.fetchone() == (1, "x")
    assert cur.fetchall() == [(2, "y")]
    assert cur.fetchone() is None
    kind, _, params, settings = client.calls[-1]
    assert (kind, params) == ("query", [1])
    # join_use_nulls keeps OUTER JOIN misses NULL; the timeout rides as a setting
    assert settings == {
        "join_use_nulls": 1,
        "max_execution_time": 4,
        "some_name": "text",
    }
    cur.execute("(SELECT 1)")
    assert client.calls[-1][0] == "query"
    cur.execute("DELETE FROM t WHERE a = 1")
    assert client.calls[-1][0] == "command" and cur.description is None
    cur.execute("   ")
    assert client.calls[-1][1] == "   "
    cur.close()
    assert cur.fetchall() == []


def test_clickhouse_connector_wraps_cursorless_client_and_keeps_dbapi_path():
    client = _FakeClient()
    ch = ClickHouseConnector(connection=client)
    with ch.get_cursor() as cur:
        assert isinstance(cur, ClickHouseCursor)
        ch.apply_statement_timeout(cur, 3000)
        cur.execute("SELECT 1")
    assert client.calls[-1][3]["max_execution_time"] == 3
    assert ch.test_connection()["status"] == "healthy"

    dbapi_conn = MagicMock()
    ch2 = ClickHouseConnector(connection=dbapi_conn)
    with ch2.get_cursor() as cur2:
        assert cur2 is dbapi_conn.cursor.return_value
    explicit = MagicMock()
    ch3 = ClickHouseConnector(cursor=explicit)
    with ch3.get_cursor() as cur3:
        assert cur3 is explicit


def test_clickhouse_introspection_reads_primary_key_from_catalog():
    from query_builder.connectors.introspection import introspect_clickhouse

    cur = MagicMock()
    cur.fetchall.side_effect = [
        [("events",)],
        [
            ("events", "id", "Int32", 0),  # named id but NOT the key
            ("events", "ts", "DateTime", 1),
            ("events", "note", "Nullable(String)", 0),
        ],
    ]
    cols = introspect_clickhouse(cur, "db")["tables"]["events"]["columns"]
    assert {c["name"]: c["is_primary"] for c in cols} == {
        "id": False,
        "ts": True,
        "note": False,
    }
    # legacy 3-column rows (older mocks/servers) keep the name heuristic
    cur2 = MagicMock()
    cur2.fetchall.side_effect = [[("t",)], [("t", "id", "Int32")]]
    legacy = introspect_clickhouse(cur2, "db")["tables"]["t"]["columns"]
    assert legacy[0]["is_primary"] is True


# --- MariaDB: no max_execution_time variable ---------------------------------
def test_mysql_statement_timeout_falls_back_to_mariadb_variable():
    cur = MagicMock()
    cur.execute.side_effect = [
        RuntimeError("(1193, \"Unknown system variable 'max_execution_time'\")"),
        None,
        None,
    ]
    my = MySQLConnector(connection=MagicMock())
    my.apply_statement_timeout(cur, 2500)
    assert cur.execute.call_args_list[-1].args[0] == (
        "SET SESSION max_statement_time = 2.5;"
    )
    my.apply_statement_timeout(cur, 1000)  # remembered: goes straight to MariaDB
    assert cur.execute.call_args_list[-1].args[0] == (
        "SET SESSION max_statement_time = 1.0;"
    )
    assert cur.execute.call_count == 3


def test_mysql_statement_timeout_does_not_swallow_other_errors():
    cur = MagicMock()
    cur.execute.side_effect = RuntimeError("connection lost")
    with pytest.raises(RuntimeError, match="connection lost"):
        MySQLConnector(connection=MagicMock()).apply_statement_timeout(cur, 1000)
    ok = MagicMock()
    MySQLConnector(connection=MagicMock()).apply_statement_timeout(ok, 1000)
    ok.execute.assert_called_once_with("SET SESSION max_execution_time = 1000;")


# --- PostgreSQL: a failed statement must not poison the connection ------------
@pytest.mark.parametrize("cls", [PostgresConnector, MySQLConnector])
def test_failed_statement_rolls_the_connection_back(cls):
    conn = MagicMock()

    def _fail_only_the_bad_statement(sql, *args, **kwargs):
        # Connect-time session statements (e.g. the read-only SET) must succeed so the
        # failure under test happens inside the caller's statement, not during connect.
        if sql.startswith("SELEC "):
            raise RuntimeError("syntax error")

    conn.cursor.return_value.execute.side_effect = _fail_only_the_bad_statement
    c = cls(connection=conn)
    with pytest.raises(RuntimeError), c.get_cursor() as cur:
        cur.execute("SELEC 1")
    conn.rollback.assert_called_once()

    conn2 = MagicMock()
    with cls(connection=conn2).get_cursor():
        pass
    conn2.rollback.assert_not_called()  # success path is untouched

    conn3 = MagicMock()
    conn3.rollback.side_effect = RuntimeError("already closed")
    with pytest.raises(ValueError), cls(connection=conn3).get_cursor():
        raise ValueError("boom")  # rollback failure never masks the real error


# --- compiler: nested queries must not get an implicit page LIMIT ------------
def test_cte_and_subquery_bodies_are_not_silently_truncated():
    spec = {
        "table": "big",
        "ctes": [
            {
                "name": "big",
                "query": {
                    "table": "t",
                    "columns": ["id"],
                    "filters": [{"column": "x", "op": "gt", "value": 1}],
                },
            }
        ],
        "columns": ["id"],
        "limit": 10,
    }
    sql, params, _, _ = QueryCompiler(spec).compile()
    assert sql.count("LIMIT") == 1  # only the outer page limit
    assert params == [1, 10, 0]

    in_sub = {
        "table": "t",
        "columns": ["id"],
        "filters": [
            {
                "column": "id",
                "op": "in",
                "value": {"table": "u", "columns": ["t_id"]},
            }
        ],
        "limit": 5,
    }
    sql2, params2, _, _ = QueryCompiler(in_sub, dialect="mysql").compile()
    assert sql2.count("LIMIT") == 1 and params2 == [5, 0]

    # an explicit LIMIT/OFFSET inside the nested query is still honoured
    explicit = {
        "table": "t",
        "columns": ["id"],
        "filters": [
            {
                "column": "id",
                "op": "in",
                "value": {"table": "u", "columns": ["t_id"], "limit": 3},
            }
        ],
    }
    sql3, params3, _, _ = QueryCompiler(explicit).compile()
    assert sql3.count("LIMIT") == 2 and params3[0] == 3


# --- compiler: user text containing LIKE wildcards is literal ------------------
@pytest.mark.parametrize(
    ("dialect", "needs_clause"),
    [
        ("postgres", False),
        ("mysql", False),
        ("clickhouse", False),
        ("cockroachdb", False),
        ("sqlite", True),
        ("duckdb", True),
        ("mssql", True),
        ("trino", True),
    ],
)
@pytest.mark.parametrize(
    ("op", "pattern"),
    [
        ("contains", "%50\\%\\_x%"),
        ("starts_with", "50\\%\\_x%"),
        ("ends_with", "%50\\%\\_x"),
    ],
)
def test_substring_filters_escape_like_wildcards(dialect, needs_clause, op, pattern):
    spec = {
        "table": "t",
        "columns": ["id"],
        "filters": [{"column": "name", "op": op, "value": "50%_x"}],
    }
    sql, params, _, _ = QueryCompiler(spec, dialect=dialect).compile()
    assert params[0] == pattern
    assert ("ESCAPE '\\'" in sql) is needs_clause


def test_like_escape_edge_cases():
    pg = get_dialect("postgres")
    assert pg.escape_like("a\\b") == "a\\\\b"  # the escape character itself
    assert pg.escape_like(12) == "12"
    assert get_dialect("mssql").escape_like("[x]") == "\\[x]"
    # dialects not verified live keep the previous pass-through behaviour
    passthrough = get_dialect("db2")
    assert passthrough.escape_like("50%") == "50%"
    assert "ESCAPE" not in passthrough.format_substring_match('"c"')
    # Oracle was verified live and now escapes with an explicit ESCAPE clause
    oracle = get_dialect("oracle")
    assert oracle.escape_like("50%") == "50\\%"
    assert oracle.format_substring_match('"c"').endswith("ESCAPE '\\'")
    # explicit like/ilike patterns are the caller's pattern: never escaped
    spec = {
        "table": "t",
        "columns": ["id"],
        "filters": [{"column": "name", "op": "like", "value": "a%"}],
    }
    assert QueryCompiler(spec, dialect="postgres").compile()[1][0] == "a%"
