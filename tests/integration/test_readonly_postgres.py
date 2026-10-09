"""Live PostgreSQL: the connector's session really refuses writes (skipped when unreachable).

Connection settings come from plain environment variables (no shared fixtures):
``QB_IT_POSTGRES_HOST`` (default 127.0.0.1), ``_PORT`` (5432), ``_USER`` (postgres),
``_PASSWORD``, ``_DB`` (postgres).  Also valid for CockroachDB / Timescale / Neon / AlloyDB
(same wire protocol and the same ``SET SESSION CHARACTERISTICS`` statement).
"""

from __future__ import annotations

import os

import pytest

from query_builder.connectors.postgres import PostgresConnector

pytestmark = pytest.mark.integration


def _settings() -> dict:
    return {
        "host": os.environ.get("QB_IT_POSTGRES_HOST", "127.0.0.1"),
        "port": int(os.environ.get("QB_IT_POSTGRES_PORT", "5432")),
        "user": os.environ.get("QB_IT_POSTGRES_USER", "postgres"),
        "password": os.environ.get("QB_IT_POSTGRES_PASSWORD", ""),
        "dbname": os.environ.get("QB_IT_POSTGRES_DB", "postgres"),
        "connect_timeout": 3,
    }


@pytest.fixture
def connector():
    pytest.importorskip("psycopg")
    from query_builder.config import SecurityConfig

    sec = SecurityConfig()
    sec.network.allow_private_networks = True
    sec.network.enforce_tls = False
    c = PostgresConnector(security=sec, **_settings())
    try:
        c.connect()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL not reachable: {type(exc).__name__}")
    yield c
    c.close()


def test_session_refuses_writes_and_ddl(connector) -> None:
    with connector.get_cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone()[0] == 1
        cur.execute("SHOW transaction_read_only")
        assert cur.fetchone()[0] == "on"
    for stmt in ("CREATE TABLE qb_ro_probe (id int)", "CREATE SCHEMA qb_ro_probe"):
        with pytest.raises(Exception, match="read-only|read only"):  # noqa: B017
            with connector.get_cursor() as cur:
                cur.execute(stmt)
        connector.connect().rollback()
