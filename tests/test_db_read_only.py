"""Database-side read-only enforcement (defense in depth, independent of the validator).

Real engines (SQLite, DuckDB): the database itself refuses writes even when the validator
is bypassed by a direct low-level call (``execute_raw`` / a raw cursor).  Server engines:
the exact statements issued are asserted through mocks (live checks are in
``tests/integration/test_readonly_<engine>.py``).
"""

from __future__ import annotations

import asyncio
import inspect
import sqlite3
from unittest.mock import MagicMock

import pytest

from query_builder.config import SecurityConfig
from query_builder.connectors import base as base_mod
from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import BaseConnector
from query_builder.connectors.clickhouse import ClickHouseConnector
from query_builder.connectors.mssql import MSSQLConnector
from query_builder.connectors.mysql import MySQLConnector
from query_builder.connectors.postgres import PostgresConnector
from query_builder.connectors.redshift import RedshiftConnector
from query_builder.connectors.singlestore import SingleStoreConnector
from query_builder.connectors.sqlite import SQLiteConnector


def _sec(enforce: bool = True) -> SecurityConfig:
    sec = SecurityConfig()
    sec.execution.enforce_read_only_session = enforce
    return sec


# ---------------------------------------------------------------- SQLite (real engine)


def test_sqlite_in_memory_refuses_writes_even_without_the_validator() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    c = SQLiteConnector(connection=conn, security=_sec())
    c.connect()
    # Direct low-level calls: no AST validator, no _is_mutating_sql check.
    for stmt in (
        "INSERT INTO t VALUES (2)",
        "UPDATE t SET id = 3",
        "DELETE FROM t",
        "CREATE TABLE z (a)",
        "DROP TABLE t",
        "ALTER TABLE t ADD COLUMN b",
    ):
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            c.execute_raw(stmt)
    assert c.execute_raw("SELECT COUNT(*) AS n FROM t")[1] == [{"n": 1}]


def test_sqlite_file_database_is_opened_read_only_at_the_vfs(tmp_path) -> None:
    path = tmp_path / "ro.db"
    setup = sqlite3.connect(path)
    setup.execute("CREATE TABLE t (id INTEGER)")
    setup.execute("INSERT INTO t VALUES (1)")
    setup.commit()
    setup.close()

    c = SQLiteConnector(str(path), security=_sec())
    conn = c.connect()
    assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        c.execute_raw("INSERT INTO t VALUES (2)")
    # Lifting query_only (as a bypassing attacker might) still hits the mode=ro VFS flag.
    conn.execute("PRAGMA query_only = OFF")
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        c.execute_raw("INSERT INTO t VALUES (3)")
    c.close()

    check = sqlite3.connect(path)
    assert check.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    check.close()


def test_sqlite_enforcement_off_allows_writes(tmp_path) -> None:
    path = tmp_path / "rw.db"
    c = SQLiteConnector(str(path), security=_sec(False))
    c.execute_raw("CREATE TABLE t (id INTEGER)")
    c.execute_raw("INSERT INTO t VALUES (1)")
    assert c.execute_raw("SELECT COUNT(*) AS n FROM t")[1] == [{"n": 1}]
    c.close()


def test_sqlite_missing_file_is_not_created_read_only_uri(tmp_path) -> None:
    c = SQLiteConnector(str(tmp_path / "new.db"), security=_sec())
    c.connect()  # nothing to open read-only yet: plain connect + query_only
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        c.execute_raw("CREATE TABLE t (id INTEGER)")
    c.close()


# ---------------------------------------------------------------- DuckDB (real engine)


def test_duckdb_file_database_is_opened_read_only(tmp_path) -> None:
    duckdb = pytest.importorskip("duckdb")
    from query_builder.connectors.duckdb import DuckDBConnector

    path = str(tmp_path / "ro.duckdb")
    setup = duckdb.connect(path)
    setup.execute("CREATE TABLE t (id INTEGER)")
    setup.execute("INSERT INTO t VALUES (1)")
    setup.close()

    c = DuckDBConnector(path, security=_sec())
    c.connect()
    for stmt in (
        "INSERT INTO t VALUES (2)",
        "UPDATE t SET id = 5",
        "DELETE FROM t",
        "CREATE TABLE z (a INTEGER)",
        "DROP TABLE t",
    ):
        with pytest.raises(Exception, match="(?i)read-only|read only"):  # noqa: B017
            c.execute_raw(stmt)
    assert c.execute_raw("SELECT COUNT(*) AS n FROM t")[1] == [{"n": 1}]
    c.close()


def test_duckdb_enforcement_off_allows_writes(tmp_path) -> None:
    pytest.importorskip("duckdb")
    from query_builder.connectors.duckdb import DuckDBConnector

    c = DuckDBConnector(str(tmp_path / "rw.duckdb"), security=_sec(False))
    c.execute_raw("CREATE TABLE t (id INTEGER)")
    c.execute_raw("INSERT INTO t VALUES (1)")
    c.close()


# ---------------------------------------------------------------- server engines (mocks)


def _executed(mock_conn: MagicMock) -> list[str]:
    return [c.args[0] for c in mock_conn.cursor.return_value.execute.call_args_list]


def test_postgres_issues_session_read_only_and_commits() -> None:
    conn = MagicMock()
    PostgresConnector(connection=conn, security=_sec()).connect()
    assert _executed(conn) == ["SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"]
    conn.commit.assert_called_once()


def test_postgres_family_inherits_the_statement() -> None:
    from query_builder.connectors.cockroachdb import CockroachConnector
    from query_builder.connectors.timescaledb import TimescaleConnector

    for cls in (CockroachConnector, TimescaleConnector):
        conn = MagicMock()
        cls(connection=conn, security=_sec()).connect()
        assert _executed(conn) == [
            "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"
        ]


def test_redshift_is_best_effort_with_the_same_statement() -> None:
    conn = MagicMock()
    c = RedshiftConnector(connection=conn, security=_sec())
    c.connect()
    assert c.read_only_support == "best_effort"
    assert _executed(conn) == ["SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"]


def test_mysql_issues_session_transaction_read_only() -> None:
    conn = MagicMock()
    MySQLConnector(connection=conn, security=_sec()).connect()
    assert _executed(conn) == ["SET SESSION TRANSACTION READ ONLY"]


def test_clickhouse_sets_readonly_client_setting() -> None:
    client = MagicMock()
    ClickHouseConnector(connection=client, security=_sec()).connect()
    client.set_client_setting.assert_called_once_with("readonly", 2)


def test_clickhouse_falls_back_to_set_statement() -> None:
    client = MagicMock(spec=["command"])
    ClickHouseConnector(connection=client, security=_sec()).connect()
    client.command.assert_called_once_with("SET readonly = 2")


@pytest.mark.parametrize("cls", [MSSQLConnector, SingleStoreConnector])
def test_engines_without_a_mechanism_issue_nothing_and_say_so(cls) -> None:
    conn = MagicMock()
    c = cls(connection=conn, security=_sec())
    c.connect()
    assert c.read_only_support == "none"
    conn.cursor.assert_not_called()


def test_not_applied_when_enforcement_is_off() -> None:
    conn = MagicMock()
    PostgresConnector(connection=conn, security=_sec(False)).connect()
    conn.cursor.assert_not_called()


def test_applied_once_per_connection_object() -> None:
    conn = MagicMock()
    c = PostgresConnector(connection=conn, security=_sec())
    c.connect()
    c.connect()
    assert len(_executed(conn)) == 1


def test_failure_to_apply_fails_the_connection_closed() -> None:
    conn = MagicMock()
    conn.cursor.return_value.execute.side_effect = RuntimeError("boom")
    c = PostgresConnector(connection=conn, security=_sec())
    with pytest.raises(RuntimeError):
        c.connect()
    assert getattr(c, "_read_only_applied_to", None) is None


def test_hook_exists_on_every_connector_and_is_declared() -> None:
    """Architectural: the hook is part of the base connect path, so it cannot be forgotten,
    and every concrete connector declares how strongly its engine enforces it."""
    assert "_ensure_read_only" in inspect.getsource(BaseConnector.__init_subclass__)
    assert "_ensure_read_only" in inspect.getsource(
        AsyncBaseConnector.__init_subclass__
    )

    import importlib
    import pkgutil

    import query_builder.connectors as pkg

    for m in pkgutil.iter_modules(pkg.__path__):
        try:
            importlib.import_module(f"query_builder.connectors.{m.name}")
        except Exception:  # noqa: BLE001, S112
            continue
    seen = 0
    for cls in _all_subclasses(BaseConnector) | _all_subclasses(AsyncBaseConnector):
        seen += 1
        assert cls.read_only_support in {"enforced", "best_effort", "none"}, cls
        if cls.read_only_support != "none":
            overridden = any(
                "apply_read_only" in vars(k)
                for k in cls.__mro__
                if k not in (BaseConnector, AsyncBaseConnector, object)
            )
            assert overridden, f"{cls.__name__} claims enforcement without a mechanism"
    assert seen > 50


def _all_subclasses(cls: type) -> set[type]:
    out: set[type] = set()
    for sub in cls.__subclasses__():
        out.add(sub)
        out |= _all_subclasses(sub)
    return out


def test_async_hook_is_awaited_from_the_wrapped_connect() -> None:
    calls: list[object] = []

    class _C(AsyncBaseConnector):
        dialect_name = "postgres"
        read_only_support = "enforced"

        async def connect(self):
            self._connection = self._connection or object()
            return self._connection

        async def apply_read_only(self, connection):
            calls.append(connection)

    async def run() -> None:
        c = _C(security=_sec())
        conn = await c.connect()
        await c.connect()
        assert calls == [conn]
        off = _C(security=_sec(False))
        await off.connect()
        assert calls == [conn]

    asyncio.run(run())


def test_base_module_exposes_the_hook() -> None:
    assert hasattr(base_mod.BaseConnector, "apply_read_only")
    assert BaseConnector.read_only_support == "none"
