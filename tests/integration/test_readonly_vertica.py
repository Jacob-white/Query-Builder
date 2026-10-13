"""Live Vertica: the connector's session really refuses writes (skipped when unreachable).

Settings: ``QB_IT_VERTICA_HOST`` (127.0.0.1), ``_PORT`` (41053, the compose default), ``_USER``
(dbadmin), ``_PASSWORD``, ``_DB`` (qb_it).  Needs ``vertica-python``.
"""

from __future__ import annotations

import os

import pytest

from query_builder.connectors.vertica import VerticaConnector

pytestmark = [pytest.mark.integration, pytest.mark.qb_category("write_refused")]

TABLE = "qb_ro_probe"


def _make(*, read_only: bool) -> VerticaConnector:
    pytest.importorskip("vertica_python")
    from query_builder.config import SecurityConfig

    sec = SecurityConfig()
    sec.network.allow_private_networks = True
    sec.network.enforce_tls = False
    sec.execution.enforce_read_only_session = read_only
    return VerticaConnector(
        security=sec,
        host=os.environ.get("QB_IT_VERTICA_HOST", "127.0.0.1"),
        port=int(os.environ.get("QB_IT_VERTICA_PORT", "41053")),
        database=os.environ.get("QB_IT_VERTICA_DB", "qb_it"),
        user=os.environ.get("QB_IT_VERTICA_USER", "dbadmin"),
        password=os.environ.get("QB_IT_VERTICA_PASSWORD", ""),
        connection_timeout=5,
    )


def _connect(connector: VerticaConnector) -> VerticaConnector:
    try:
        connector.connect()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Vertica not reachable: {type(exc).__name__}")
    return connector


@pytest.fixture
def writer():
    """A connector with enforcement off: sets up and tears down the probe table."""
    c = _connect(_make(read_only=False))
    with c.get_cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {TABLE} CASCADE")
        cur.execute(f"CREATE TABLE {TABLE} (id int)")
        cur.execute(f"INSERT INTO {TABLE} VALUES (1)")
        cur.execute("COMMIT")
    yield c
    with c.get_cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {TABLE} CASCADE")
        cur.execute("COMMIT")
    c.close()


@pytest.fixture
def reader():
    c = _connect(_make(read_only=True))
    yield c
    c.close()


def _count(connector: VerticaConnector) -> int:
    with connector.get_cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {TABLE}")
        return int(cur.fetchone()[0])


def test_declared_enforced() -> None:
    assert VerticaConnector.read_only_support == "enforced"


def test_session_refuses_writes_and_ddl(writer, reader) -> None:
    with reader.get_cursor() as cur:
        cur.execute(f"SELECT id FROM {TABLE}")
        assert cur.fetchone()[0] == 1
    for stmt in (
        f"INSERT INTO {TABLE} VALUES (2)",
        f"UPDATE {TABLE} SET id = 9",
        f"DELETE FROM {TABLE}",
        f"TRUNCATE TABLE {TABLE}",
        f"DROP TABLE {TABLE}",
        "CREATE TABLE qb_ro_probe_new (id int)",
    ):
        with pytest.raises(Exception, match="(?i)read-only"):  # noqa: B017
            with reader.get_cursor() as cur:
                cur.execute(stmt)
    assert _count(writer) == 1


def test_refusal_survives_a_commit(writer, reader) -> None:
    """The setting is session-wide: a COMMIT does not lift it."""
    with reader.get_cursor() as cur:
        cur.execute("COMMIT")
    with pytest.raises(Exception, match="(?i)read-only"):  # noqa: B017
        with reader.get_cursor() as cur:
            cur.execute(f"INSERT INTO {TABLE} VALUES (3)")
    assert _count(writer) == 1


def test_control_same_writes_succeed_without_enforcement(writer) -> None:
    """Control: with enforcement off the same statements work, so the refusals above are
    caused by the session setting and not by privileges."""
    with writer.get_cursor() as cur:
        cur.execute(f"INSERT INTO {TABLE} VALUES (2)")
        cur.execute("COMMIT")
    assert _count(writer) == 2
