"""
Regression tests for defects found by the live integration suite against the "other
relational / analytical SQL" engines (MonetDB, Firebird, Oracle, Vertica, Db2, Informix,
Exasol).  Each test reproduces, without a database, the behaviour that failed against a real
engine.  See tests/integration/engines_sql.py and docs/TESTING_LIVE.md.
"""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import MagicMock

from query_builder.ast_validator import validate_sql_ast
from query_builder.compiler import QueryCompiler
from query_builder.connectors.firebird import (
    AsyncFirebirdConnector,
    FirebirdConnector,
)
from query_builder.connectors.introspection import (
    introspect_monetdb,
    introspect_oracle,
)
from query_builder.connectors.monetdb import (
    AsyncMonetDBConnector,
    MonetDBConnector,
)
from query_builder.connectors.oracle import OracleConnector, to_numbered_binds
from query_builder.dialects import get_dialect

SPEC = {
    "table": "t",
    "columns": ["id", {"column": "n", "agg": "avg", "alias": "m"}],
    "filters": [{"column": "name", "op": "contains", "value": "50%_"}],
    "limit": 5,
    "offset": 10,
}


def _compile(dialect: str, spec: dict | None = None):
    return QueryCompiler(spec=spec or SPEC, dialect=get_dialect(dialect)).compile()


# --- MonetDB ----------------------------------------------------------------------
def test_monetdb_uses_the_pyformat_placeholder_pymonetdb_expects():
    # pymonetdb formats `operation % params`; a "?" made every parameterised query fail
    assert get_dialect("monetdb").placeholder == "%s"
    sql, params, _, _ = _compile("monetdb")
    assert "?" not in sql and sql.count("%s") == len(params)


def test_monetdb_like_wildcards_are_escaped_with_a_declared_escape_char():
    sql, params, _, _ = _compile("monetdb")
    assert "ESCAPE '!'" in sql  # MonetDB rejects a backslash ESCAPE
    assert "%50!%!_%" in params


def test_monetdb_introspection_queries_use_real_catalog_objects():
    cur = MagicMock()
    cur.fetchall.return_value = []
    introspect_monetdb(cur, "sys")
    sqls = " ".join(str(c.args[0]) for c in cur.execute.call_args_list)
    assert "sys.keycolumns" not in sqls  # not a MonetDB catalog table (sys.objects is)
    assert "sys.objects" in sqls
    assert 'c."null"' in sqls  # c.null is a syntax error
    assert "= ?" not in sqls and "= %s" in sqls


def test_monetdb_introspection_keeps_catalog_case_and_real_primary_keys():
    cur = MagicMock()
    cur.fetchall.side_effect = [
        [("QbitMixedCase",), ("t",)],  # tables
        [
            ("QbitMixedCase", "id", "int", False),
            ("QbitMixedCase", "val", "varchar", True),
            ("t", "id", "int", False),
        ],  # columns
        [("QbitMixedCase", "val")],  # primary keys: NOT "id"
        [],  # foreign keys
    ]
    snap = introspect_monetdb(cur, "sys", filter_sensitive=False)
    assert set(snap["tables"]) == {
        "QbitMixedCase",
        "t",
    }  # quoted names are case-sensitive
    cols = {
        c["name"]: c["is_primary"] for c in snap["tables"]["QbitMixedCase"]["columns"]
    }
    assert cols == {"id": False, "val": True}  # no "column called id is the key" guess


def test_monetdb_statement_timeout_sets_the_session_query_timeout():
    cur = MagicMock()
    MonetDBConnector(connection=MagicMock()).apply_statement_timeout(cur, 2500)
    cur.execute.assert_called_once_with("CALL sys.setquerytimeout(2)")


def test_monetdb_reports_the_real_server_version():
    cur = MagicMock()
    cur.fetchone.return_value = ("11.55.7",)
    conn = MagicMock()
    conn.cursor.return_value = cur
    assert MonetDBConnector(connection=conn).test_connection()["engine_version"] == (
        "MonetDB 11.55.7"
    )


class _ThreadProbeCursor:
    """Records which thread the (blocking) driver call ran on."""

    description = [("x",)]

    def __init__(self, threads):
        self.threads = threads

    def execute(self, sql, params=None):
        self.threads.append(threading.get_ident())

    def fetchall(self):
        return [(1,)]

    def close(self):
        pass


def _probe_connection(threads):
    conn = MagicMock()
    conn.cursor.return_value = _ThreadProbeCursor(threads)
    return conn


def test_async_monetdb_and_firebird_do_not_block_the_event_loop_thread():
    # the async classes called the BLOCKING driver inline: asyncio.wait_for could never time
    # a query out and one slow query froze every coroutine
    for cls in (AsyncMonetDBConnector, AsyncFirebirdConnector):
        threads: list[int] = []
        conn = cls(connection=_probe_connection(threads))
        _, rows, _ = asyncio.run(conn.execute_raw("SELECT 1"))
        assert rows == [{"x": 1}]
        assert threads and threads[0] != threading.get_ident(), cls.__name__


# --- Firebird ---------------------------------------------------------------------
def test_firebird_pagination_is_standard_offset_fetch_and_passes_the_ast_validator():
    sql, params, _, _ = _compile("firebird")
    # `ROWS ? TO ?` is not parseable by the structural validator: every query was rejected
    assert "ROWS %s TO" not in sql and "ROWS ?" not in sql
    assert "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY" in sql
    assert params[-2:] == [10, 5]
    assert validate_sql_ast(sql, dialect="firebird")["valid"]


def test_firebird_avg_is_not_integer_division_and_like_is_escaped():
    sql, params, _, _ = _compile("firebird")
    assert "AVG(CAST(" in sql and "DOUBLE PRECISION" in sql
    assert "ESCAPE '\\'" in sql
    assert "%50\\%\\_%" in [str(p).lower() for p in params]


def test_firebird_statement_timeout_and_transaction_hygiene():
    cur = MagicMock()
    FirebirdConnector(connection=MagicMock()).apply_statement_timeout(cur, 1500)
    cur.execute.assert_called_once_with("SET STATEMENT TIMEOUT 1500 MILLISECOND")
    cur.execute.side_effect = RuntimeError("Firebird 3: no statement timeout")
    FirebirdConnector(connection=MagicMock()).apply_statement_timeout(
        cur, 10
    )  # no raise

    conn = MagicMock()
    with FirebirdConnector(connection=conn).get_cursor():
        pass
    # a snapshot transaction kept open would never see rows committed by others
    conn.rollback.assert_called_once()


def test_firebird_reports_the_real_server_version():
    cur = MagicMock()
    cur.fetchone.return_value = ("5.0.4",)
    conn = MagicMock()
    conn.cursor.return_value = cur
    assert FirebirdConnector(connection=conn).test_connection()["engine_version"] == (
        "Firebird 5.0.4"
    )


# --- Oracle -----------------------------------------------------------------------
def test_oracle_placeholders_become_numbered_binds_outside_literals():
    assert to_numbered_binds("SELECT 1 FROM t WHERE a = %s AND b IN (%s, %s)") == (
        "SELECT 1 FROM t WHERE a = :1 AND b IN (:2, :3)"
    )
    # literals, quoted identifiers and comments are left alone
    assert to_numbered_binds("SELECT '%s', \"%s\" FROM t WHERE a = %s") == (
        "SELECT '%s', \"%s\" FROM t WHERE a = :1"
    )
    assert to_numbered_binds(
        "SELECT 'it''s %s' FROM t WHERE a = %s -- %s\n AND b = %s"
    ) == ("SELECT 'it''s %s' FROM t WHERE a = :1 -- %s\n AND b = :2")
    assert to_numbered_binds("SELECT /* %s */ 1 FROM t WHERE a = %s") == (
        "SELECT /* %s */ 1 FROM t WHERE a = :1"
    )
    assert to_numbered_binds("SELECT 1 FROM DUAL") == "SELECT 1 FROM DUAL"


def test_oracle_connector_cursor_translates_binds_for_the_driver():
    raw = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value = raw
    with OracleConnector(connection=conn).get_cursor() as cur:
        cur.execute("SELECT * FROM t WHERE a = %s", (5,))
        raw.execute.assert_called_once_with("SELECT * FROM t WHERE a = :1", [5])
        cur.execute("SELECT 1 FROM DUAL")
        raw.execute.assert_called_with("SELECT 1 FROM DUAL")


def test_oracle_pagination_and_like_escape():
    sql, params, _, _ = _compile("oracle")
    assert "OFFSET %s ROWS FETCH NEXT %s ROWS ONLY" in sql
    assert "ESCAPE '\\'" in sql


def test_oracle_statement_timeout_uses_the_driver_call_timeout():
    conn = MagicMock()
    cur = MagicMock()
    cur.connection = conn
    OracleConnector(connection=conn).apply_statement_timeout(cur, 1234)
    assert conn.call_timeout == 1234


def test_oracle_introspection_reads_keys_and_preserves_case():
    cur = MagicMock()
    cur.fetchall.side_effect = [
        [("qbit_employees",), ("QbitMixedCase",)],  # tables
        [
            ("qbit_employees", "id", "NUMBER", "N"),
            ("qbit_employees", "dept_id", "NUMBER", "Y"),
            ("QbitMixedCase", "val", "VARCHAR2", "N"),
        ],
        [("qbit_employees", "id")],  # primary keys
        [("qbit_employees", "dept_id", "qbit_departments", "id")],  # foreign keys
    ]
    snap = introspect_oracle(cur, filter_sensitive=False)
    assert set(snap["tables"]) == {"qbit_employees", "QbitMixedCase"}
    cols = {c["name"]: c for c in snap["tables"]["qbit_employees"]["columns"]}
    assert cols["id"]["is_primary"] and not cols["dept_id"]["is_primary"]
    assert cols["dept_id"]["is_nullable"] and not cols["id"]["is_nullable"]
    assert snap["foreign_keys"] == [
        {
            "table": "qbit_employees",
            "column": "dept_id",
            "foreign_table": "qbit_departments",
            "foreign_column": "id",
        }
    ]
    sqls = " ".join(c.args[0] for c in cur.execute.call_args_list)
    assert "%s" not in sqls  # introspection must not use the pyformat marker either


def test_oracle_derived_table_alias_has_no_as_keyword():
    # ORA-03048: Oracle rejects `) AS alias`, which broke every grouped query's COUNT(*)
    spec = {
        "table": "t",
        "columns": [
            {"column": "d", "alias": "d"},
            {"column": "x", "agg": "sum", "alias": "s"},
        ],
        "limit": 5,
    }
    _, _, count_sql, _ = _compile("oracle", spec)
    assert ") count_subquery" in count_sql and ") AS count_subquery" not in count_sql
    # other dialects keep the portable spelling
    _, _, count_sql, _ = _compile("postgres", spec)
    assert ") AS count_subquery" in count_sql
