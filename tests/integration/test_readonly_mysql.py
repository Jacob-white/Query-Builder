"""Live MySQL / MariaDB: the connector's session really refuses writes (skipped when
unreachable).  Settings: ``QB_IT_MYSQL_HOST`` (127.0.0.1), ``_PORT`` (3306), ``_USER``
(root), ``_PASSWORD``, ``_DB`` (mysql)."""

from __future__ import annotations

import os

import pytest

from query_builder.connectors.mysql import MySQLConnector

pytestmark = pytest.mark.integration


@pytest.fixture
def connector():
    if not (_has("MySQLdb") or _has("pymysql")):
        pytest.skip("no MySQL driver installed")
    from query_builder.config import SecurityConfig

    sec = SecurityConfig()
    sec.network.allow_private_networks = True
    sec.network.enforce_tls = False
    c = MySQLConnector(
        security=sec,
        database=os.environ.get("QB_IT_MYSQL_DB", "mysql"),
        host=os.environ.get("QB_IT_MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("QB_IT_MYSQL_PORT", "3306")),
        user=os.environ.get("QB_IT_MYSQL_USER", "root"),
        passwd=os.environ.get("QB_IT_MYSQL_PASSWORD", ""),
        connect_timeout=3,
    )
    try:
        c.connect()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"MySQL not reachable: {type(exc).__name__}")
    yield c
    c.close()


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except ImportError:
        return False


def test_session_refuses_writes_and_ddl(connector) -> None:
    with connector.get_cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone()[0] == 1
    for stmt in ("CREATE TABLE qb_ro_probe (id int)", "CREATE DATABASE qb_ro_probe"):
        with pytest.raises(Exception, match="(?i)read.only"):  # noqa: B017
            with connector.get_cursor() as cur:
                cur.execute(stmt)
