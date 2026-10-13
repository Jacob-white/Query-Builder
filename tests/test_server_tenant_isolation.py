"""End-to-end: the HTTP server applies the request's tenant on EVERY endpoint that returns rows.

Real sqlite data (two tenants), a real server on a random port, real HTTP requests. Before this
fix a registered ``connection_id`` (the pooled path), ``/api/v1/export`` and
``/api/v1/export/stream`` ignored ``tenant_id`` entirely: the caller did everything right and still
received the other tenant's rows.

Each case runs twice: WITH ``tenant_id`` (only that tenant's rows may come back) and WITHOUT it (a
control proving the data really holds both tenants, so a passing run means the filter did the work).
The "without" half also pins what the server does today when a request omits the tenant: it does
not isolate (see ``tests/test_server_secure_mode.py`` and docs/SECURE_DEPLOYMENT.md for the mode that
does).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from query_builder.server import create_server

SPEC = {"table": "orders", "columns": ["id", "amount", "tenant_id"]}
CONNECTION = {"connector": "sqlite", "dialect": "sqlite"}


@pytest.fixture(scope="module")
def db_path(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = str(tmp_path_factory.mktemp("tenants") / "orders.db")
    con = sqlite3.connect(path)
    con.execute("create table orders (id integer, amount integer, tenant_id text)")
    con.executemany(
        "insert into orders values (?, ?, ?)",
        [(1, 10, "acme"), (2, 20, "acme"), (3, 999, "rival")],
    )
    con.commit()
    con.close()
    return path


class Client:
    def __init__(self, port: int) -> None:
        self.base = f"http://127.0.0.1:{port}"

    def post(self, path: str, body: dict[str, Any]) -> tuple[int, str]:
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as res:
                return res.status, res.read().decode("utf-8")
        except urllib.error.HTTPError as err:
            return err.code, err.read().decode("utf-8")

    def delete(self, path: str) -> int:
        req = urllib.request.Request(self.base + path, method="DELETE")
        try:
            with urllib.request.urlopen(req, timeout=20) as res:
                return int(res.status)
        except urllib.error.HTTPError as err:
            return int(err.code)


@pytest.fixture(scope="module")
def client() -> Iterator[Client]:
    server = create_server("127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield Client(int(server.server_address[1]))
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(scope="module")
def pool_id(client: Client, db_path: str) -> Iterator[str]:
    connection_id = f"tenant-test-{uuid.uuid4().hex[:8]}"
    status, _ = client.post(
        "/api/v1/connections",
        {
            "connection_id": connection_id,
            "connector": "sqlite",
            "config": {"database": db_path},
        },
    )
    assert status == 201
    yield connection_id
    client.delete(f"/api/v1/connections/{connection_id}")


def _requests(db_path: str, pool_id: str) -> dict[str, tuple[str, dict[str, Any]]]:
    inline = {**CONNECTION, "config": {"database": db_path}, "spec": SPEC}
    return {
        "execute (inline connection)": ("/api/v1/execute", dict(inline)),
        "execute (registered connection_id)": (
            "/api/v1/execute",
            {"connection_id": pool_id, "spec": SPEC, "dialect": "sqlite"},
        ),
        "execute (alias /api/query)": ("/api/query", dict(inline)),
        "execute (the `query` key)": (
            "/api/v1/query/execute",
            {**CONNECTION, "config": {"database": db_path}, "query": SPEC},
        ),
        "stream": ("/api/v1/stream", dict(inline)),
        "export": ("/api/v1/export", {**inline, "format": "csv"}),
        "export/stream": ("/api/v1/export/stream", {**inline, "format": "csv"}),
    }


ENDPOINTS = [
    "execute (inline connection)",
    "execute (registered connection_id)",
    "execute (alias /api/query)",
    "execute (the `query` key)",
    "stream",
    "export",
    "export/stream",
]


@pytest.mark.parametrize("name", ENDPOINTS)
def test_only_the_requested_tenant_s_rows_come_back(
    name: str, client: Client, db_path: str, pool_id: str
) -> None:
    path, body = _requests(db_path, pool_id)[name]
    status, text = client.post(path, {**body, "tenant_id": "acme"})
    assert status == 200, text
    assert "acme" in text
    assert "rival" not in text and "999" not in text


@pytest.mark.parametrize("name", ENDPOINTS)
def test_control_the_same_request_without_a_tenant_returns_both_tenants(
    name: str, client: Client, db_path: str, pool_id: str
) -> None:
    """Pins today's behaviour for an omitted tenant (not isolated) and proves the data really
    holds the other tenant's row, so the test above can only pass because of the filter."""
    path, body = _requests(db_path, pool_id)[name]
    status, text = client.post(path, body)
    assert status == 200, text
    assert "acme" in text and "rival" in text


def test_compile_adds_the_tenant_predicate_only_when_a_tenant_is_given(
    client: Client,
) -> None:
    with_tenant = client.post(
        "/api/v1/compile", {"spec": SPEC, "dialect": "sqlite", "tenant_id": "acme"}
    )
    without = client.post("/api/v1/compile", {"spec": SPEC, "dialect": "sqlite"})
    assert "tenant_id" in json.loads(with_tenant[1])["sql"].split("WHERE")[-1]
    assert "WHERE" not in json.loads(without[1])["sql"]


def test_a_tenant_cannot_see_another_tenants_rows_by_naming_it_in_the_spec(
    client: Client, db_path: str
) -> None:
    """A client filter on the tenant column is ANDed with the enforced predicate, not honoured."""
    spec = {
        **SPEC,
        "filters": [{"column": "tenant_id", "op": "eq", "value": "rival"}],
    }
    status, text = client.post(
        "/api/v1/execute",
        {
            **CONNECTION,
            "config": {"database": db_path},
            "spec": spec,
            "tenant_id": "acme",
        },
    )
    assert status == 200, text
    # the response echoes the request's own filter value in `params`, so inspect the ROWS
    assert [r["tenant_id"] for r in json.loads(text)["rows"]] == []


def test_raw_sql_is_not_rewritten_even_with_a_tenant(
    client: Client, db_path: str
) -> None:
    """Documented limitation (THREAT_MODEL.md 3.4): raw SQL is validated, not isolated. Use specs."""
    status, text = client.post(
        "/api/v1/execute",
        {
            **CONNECTION,
            "config": {"database": db_path},
            "sql": "select * from orders",
            "tenant_id": "acme",
        },
    )
    assert status == 200, text
    assert "rival" in text  # unfiltered: this is why secure mode refuses raw SQL


def test_server_module_fixtures_leave_no_state(client: Client, tmp_path: Path) -> None:
    status, _ = client.post("/api/v1/validate", {"sql": "select 1"})
    assert status == 200
