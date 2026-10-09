"""Mock tests for the DB2 async connector paths and the version/schema scalar probes."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from query_builder.connectors import db2
from query_builder.connectors.base import IntrospectionError


def test_scalar_returns_first_value_or_none_on_error() -> None:
    cur = MagicMock()
    cur.fetchone.return_value = ("V11",)
    assert db2._scalar(cur, "SELECT x") == "V11"
    cur.execute.assert_called_with("SELECT x")
    cur.fetchone.return_value = (None,)
    assert db2._scalar(cur, "SELECT x") is None
    cur.fetchone.return_value = None
    assert db2._scalar(cur, "SELECT x") is None
    cur.execute.side_effect = RuntimeError("SQL0204N")
    assert db2._scalar(cur, "SELECT x") is None


def test_connect_returns_existing_connection() -> None:
    existing = MagicMock()
    assert db2.DB2Connector(connection=existing).connect() is existing
    assert asyncio.run(db2.AsyncDB2Connector(connection=existing).connect()) is existing


def test_engine_version_falls_back_to_plain_name() -> None:
    cur = MagicMock()
    cur.fetchone.return_value = ("DB2 v11.5",)
    assert db2._engine_version(cur) == "DB2 v11.5"
    cur.fetchone.return_value = (12,)
    assert db2._engine_version(cur) == "IBM DB2"


def _async_conn(
    version: object = ("DB2 v11.5",),
) -> tuple[db2.AsyncDB2Connector, MagicMock]:
    cur = MagicMock()
    cur.description = [("c",)]
    cur.fetchall.return_value = [(1,)]
    cur.fetchone.return_value = version
    conn = MagicMock()
    conn.cursor.return_value = cur
    return db2.AsyncDB2Connector(connection=conn), cur


def test_async_test_connection_reports_version_and_schema() -> None:
    connector, cur = _async_conn()
    connector.schema_name = "APP"
    info = asyncio.run(connector.test_connection())
    assert info["status"] == "healthy" and info["dialect"] == "db2"
    assert info["engine_version"] == "DB2 v11.5" and info["schema_name"] == "APP"
    statements = [c.args[0] for c in cur.execute.call_args_list]
    assert (
        statements[0] == "SELECT 1 FROM SYSIBM.SYSDUMMY1"
    )  # no FROM-less SELECT on Db2
    assert statements[-1] == db2._VERSION_SQL
    assert cur.close.call_count == 2


def test_async_introspect_schema_uses_explicit_or_current_schema() -> None:
    connector, cur = _async_conn()
    seen: dict[str, object] = {}

    def fake(c: object, schema_name: str, filter_sensitive: bool) -> dict[str, object]:
        seen.update(schema=schema_name, fs=filter_sensitive)
        return {"tables": {}}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(db2, "introspect_db2", fake)
        connector.schema_name = "APP"
        assert asyncio.run(connector.introspect_schema(filter_sensitive=False)) == {
            "tables": {}
        }
        assert seen == {"schema": "APP", "fs": False}
        connector.schema_name = None
        cur.fetchone.return_value = ("CUR",)
        asyncio.run(connector.introspect_schema())
        assert seen["schema"] == "CUR"
        cur.fetchone.return_value = None  # CURRENT SCHEMA unreadable -> SYSCAT
        asyncio.run(connector.introspect_schema())
        assert seen["schema"] == "SYSCAT"
        assert cur.close.called

        def broken(*a: object, **k: object) -> None:
            raise RuntimeError("SQL1013N")

        mp.setattr(db2, "introspect_db2", broken)
        with pytest.raises(IntrospectionError, match="SQL1013N"):
            asyncio.run(connector.introspect_schema())
