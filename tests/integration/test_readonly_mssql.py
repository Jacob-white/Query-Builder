"""SQL Server has NO session-level read-only mode (documented limitation).

``ApplicationIntent=ReadOnly`` only routes to a readable Availability Group secondary and
does not stop writes on a primary; ``pymssql`` does not support it at all.  The connector
therefore declares ``read_only_support == "none"`` and the guarantee must come from a
login that only has ``db_datareader``.  This live test just proves that stance holds:
when a server is reachable and a DATAREADER-only login is configured the write fails
(``QB_IT_MSSQL_*``), otherwise it is skipped.
"""

from __future__ import annotations

import os

import pytest

from query_builder.connectors.mssql import MSSQLConnector

pytestmark = [pytest.mark.integration, pytest.mark.qb_category("write_refused")]


def test_connector_declares_no_session_level_read_only() -> None:
    assert MSSQLConnector.read_only_support == "none"


def test_datareader_login_cannot_write() -> None:
    host = os.environ.get("QB_IT_MSSQL_HOST")
    user = os.environ.get("QB_IT_MSSQL_READER_USER")
    if not (host and user):
        pytest.skip(
            "set QB_IT_MSSQL_HOST and QB_IT_MSSQL_READER_USER (db_datareader login)"
        )
    pymssql = pytest.importorskip("pymssql")
    from query_builder.config import SecurityConfig

    sec = SecurityConfig()
    sec.network.allow_private_networks = True
    sec.network.enforce_tls = False
    c = MSSQLConnector(
        security=sec,
        server=host,
        user=user,
        password=os.environ.get("QB_IT_MSSQL_READER_PASSWORD", ""),
        database=os.environ.get("QB_IT_MSSQL_DB", "master"),
        login_timeout=3,
    )
    try:
        c.connect()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"SQL Server not reachable: {type(exc).__name__}")
    with pytest.raises(pymssql.Error), c.get_cursor() as cur:
        cur.execute("CREATE TABLE qb_ro_probe (id int)")
