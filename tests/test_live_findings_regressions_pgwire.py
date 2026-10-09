"""
Regression tests (mock level, default suite) for defects found by running the
Postgres/MySQL-wire connectors against real engines (tests/integration/engines_pgwire.py).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from query_builder.connectors.alloydb import AlloyDBConnector


def test_alloydb_reports_the_real_server_version() -> None:
    """The connector used to overwrite the server's own ``SELECT version()`` with a
    hardcoded marketing string, hiding the real engine version."""
    cur = MagicMock()
    cur.fetchone.return_value = ("PostgreSQL 16.8 on x86_64",)
    conn = AlloyDBConnector()
    conn._cursor = cur
    info = conn.test_connection()
    assert info["engine_version"] == "PostgreSQL 16.8 on x86_64"
    assert info["product"] == "Google Cloud AlloyDB for PostgreSQL"
