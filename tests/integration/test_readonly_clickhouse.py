"""Live ClickHouse: the client refuses writes (``readonly = 2``); skipped when unreachable.
Settings: ``QB_IT_CLICKHOUSE_HOST`` (127.0.0.1), ``_PORT`` (8123 HTTP), ``_USER`` (default),
``_PASSWORD``."""

from __future__ import annotations

import os

import pytest

from query_builder.connectors.clickhouse import ClickHouseConnector

pytestmark = [pytest.mark.integration, pytest.mark.qb_category("write_refused")]


@pytest.fixture
def connector():
    pytest.importorskip("clickhouse_connect")
    from query_builder.config import SecurityConfig

    sec = SecurityConfig()
    sec.network.allow_private_networks = True
    sec.network.enforce_tls = False
    c = ClickHouseConnector(
        security=sec,
        host=os.environ.get("QB_IT_CLICKHOUSE_HOST", "127.0.0.1"),
        port=int(os.environ.get("QB_IT_CLICKHOUSE_PORT", "8123")),
        username=os.environ.get("QB_IT_CLICKHOUSE_USER", "default"),
        password=os.environ.get("QB_IT_CLICKHOUSE_PASSWORD", ""),
        connect_timeout=3,
    )
    try:
        client = c.connect()
        client.query("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ClickHouse not reachable: {type(exc).__name__}")
    yield c
    c.close()


def test_client_refuses_writes_and_ddl(connector) -> None:
    client = connector.connect()
    assert client.query("SELECT 1").result_rows == [(1,)]
    for stmt in (
        "CREATE TABLE qb_ro_probe (id Int32) ENGINE = Memory",
        "DROP DATABASE IF EXISTS qb_ro_probe",
    ):
        with pytest.raises(Exception, match="(?i)readonly"):  # noqa: B017
            client.command(stmt)
