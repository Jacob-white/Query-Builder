"""
Integration Tests for Live Execution & Driver Connection Pool Endpoints.
========================================================================
Tests /api/v1/query/execute, /api/v1/connections, /api/v1/connections/test,
/api/v1/connections/cancel, DELETE /api/v1/connections, and server pooling.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import pytest

from query_builder.pool import (
    ConnectionPool,
    ConnectionPoolManager,
    reset_connection_pool_manager,
)
from query_builder.server import create_server


def _make_request(
    server_url: str,
    path: str,
    method: str = "GET",
    data: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any] | list[Any]]:
    """Helper to issue HTTP requests against the test server."""
    url = f"{server_url}{path}"
    headers = {"Content-Type": "application/json"}
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read().decode("utf-8")
            return resp.status, json.loads(content) if content else {}
    except urllib.error.HTTPError as exc:
        content = exc.read().decode("utf-8")
        return exc.code, json.loads(content) if content else {}


@pytest.fixture
def running_server():
    """Spins up a lightweight server instance on an ephemeral port."""
    reset_connection_pool_manager()
    pool_mgr = ConnectionPoolManager()

    # Pre-register an in-memory SQLite pool with test data
    def factory():
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE products (id INT, name TEXT, price REAL)")
        conn.execute(
            "INSERT INTO products VALUES (1, 'Widget', 19.99), (2, 'Gadget', 49.99)"
        )
        conn.commit()
        return conn

    mem_pool = ConnectionPool(factory=factory, max_size=5)
    pool_mgr.register_pool(
        "mem_db",
        mem_pool,
        metadata={"dialect": "sqlite", "password": "supersecretpassword"},
    )

    server = create_server(
        host="127.0.0.1",
        port=0,
        connection_pool_manager=pool_mgr,
    )
    port = server.server_address[1]
    server_url = f"http://127.0.0.1:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield server_url, pool_mgr

    server.shutdown()
    server.server_close()
    reset_connection_pool_manager()


def test_get_connections_list(running_server):
    url, _ = running_server
    status, data = _make_request(url, "/api/v1/connections", method="GET")
    assert status == 200
    assert "connections" in data
    assert len(data["connections"]) == 1
    conn_info = data["connections"][0]
    assert conn_info["connection_id"] == "mem_db"
    assert conn_info["metadata"]["password"] == "***"


def test_post_connection_register_and_delete(running_server):
    url, mgr = running_server

    # Register new pool with min_size=1 (exercises factory lines 771-772)
    status, data = _make_request(
        url,
        "/api/v1/connections",
        method="POST",
        data={
            "connection_id": "new_sqlite",
            "connector": "sqlite",
            "config": {"database": ":memory:"},
            "min_size": 1,
            "metadata": {"token": "secret_token_123"},
        },
    )
    assert status == 201
    assert data["status"] == "registered"
    assert data["connection_id"] == "new_sqlite"
    assert data["metadata"]["token"] == "***"
    assert mgr.has_pool("new_sqlite") is True

    # Registration failure with invalid numeric parameter (lines 786-787)
    status, data = _make_request(
        url,
        "/api/v1/connections",
        method="POST",
        data={
            "connection_id": "bad_pool",
            "connector": "sqlite",
            "max_size": "not_an_int",
        },
    )
    assert status == 400
    assert data["error"]["code"] == "POOL_ERROR"

    # Missing connection_id returns 400
    status, data = _make_request(
        url,
        "/api/v1/connections",
        method="POST",
        data={"connector": "sqlite"},
    )
    assert status == 400
    assert "Missing required 'connection_id'" in data["error"]["message"]

    # Delete via query parameter
    status, data = _make_request(
        url,
        "/api/v1/connections?connection_id=new_sqlite",
        method="DELETE",
    )
    assert status == 200
    assert data["deleted"] is True
    assert mgr.has_pool("new_sqlite") is False

    # Delete non-existent pool returns 404
    status, data = _make_request(
        url,
        "/api/v1/connections?connection_id=does_not_exist",
        method="DELETE",
    )
    assert status == 404

    # Delete via path param
    mgr.register_pool(
        "another_pool", ConnectionPool(factory=lambda: sqlite3.connect(":memory:"))
    )
    status, data = _make_request(
        url,
        "/api/v1/connections/another_pool",
        method="DELETE",
    )
    assert status == 200
    assert data["deleted"] is True

    # Delete without ID returns 400
    status, data = _make_request(
        url,
        "/api/v1/connections",
        method="DELETE",
    )
    assert status == 400


def test_post_connection_test(running_server):
    url, _ = running_server

    # Test existing registered connection
    status, data = _make_request(
        url,
        "/api/v1/connections/test",
        method="POST",
        data={"connection_id": "mem_db"},
    )
    assert status == 200
    assert data["healthy"] is True
    assert data["dialect"] == "sqlite"

    # Test ad-hoc connector config
    status, data = _make_request(
        url,
        "/api/v1/connections/test",
        method="POST",
        data={"connector": "sqlite", "database": ":memory:"},
    )
    assert status == 200
    assert data["healthy"] is True

    # Test non-existent connection
    status, data = _make_request(
        url,
        "/api/v1/connections/test",
        method="POST",
        data={"connection_id": "unknown_db"},
    )
    assert status == 200
    assert data["healthy"] is False
    assert "not registered" in data["error"]

    # Connection test failure raising exception (lines 795-796)
    _, mgr = running_server
    orig_test = mgr.test_connection

    def _fail_test(_):
        raise RuntimeError("Simulated connection probe crash")

    mgr.test_connection = _fail_test
    try:
        status, data = _make_request(
            url,
            "/api/v1/connections/test",
            method="POST",
            data={"connection_id": "mem_db"},
        )
        assert status == 400
        assert data["error"]["code"] == "CONNECTION_TEST_ERROR"
    finally:
        mgr.test_connection = orig_test


def test_query_execute_pooled_connection(running_server):
    url, _ = running_server

    # Raw SQL via pooled connection
    status, data = _make_request(
        url,
        "/api/v1/query/execute",
        method="POST",
        data={
            "sql": "SELECT * FROM products ORDER BY id",
            "connection_id": "mem_db",
            "limit": 10,
        },
    )
    assert status == 200
    assert data["count"] == 2
    assert len(data["rows"]) == 2
    assert data["rows"][0]["name"] == "Widget"
    assert "execution_id" in data


def test_query_execute_compiled_spec(running_server):
    url, _ = running_server

    # Spec via pooled connection
    status, data = _make_request(
        url,
        "/api/v1/query/execute",
        method="POST",
        data={
            "query": {
                "table": "products",
                "columns": ["id", "name"],
                "joins": [],
                "filters": [],
                "order_by": [],
                "limit": 5,
            },
            "connection_id": "mem_db",
        },
    )
    assert status == 200
    assert "columns" in data


def test_query_execute_validation_and_cancellation(running_server):
    url, mgr = running_server

    # Missing query/sql returns 400
    status, data = _make_request(
        url,
        "/api/v1/query/execute",
        method="POST",
        data={},
    )
    assert status == 400
    assert (
        "Either 'spec', 'query', or 'sql' must be provided." in data["error"]["message"]
    )

    # Pre-cancel an execution token and verify 400 CANCELLED
    eid, token = mgr.create_execution("to_cancel")
    token.cancel()

    status, data = _make_request(
        url,
        "/api/v1/query/execute",
        method="POST",
        data={
            "sql": "SELECT 1",
            "connection_id": "mem_db",
            "execution_id": "to_cancel",
        },
    )
    assert status == 400
    assert data["error"]["code"] == "CANCELLED"


def test_connections_cancel_endpoint(running_server):
    url, mgr = running_server

    # Create token
    eid, token = mgr.create_execution("exec_cancel_test")
    assert token.is_cancelled is False

    # Call cancel endpoint
    status, data = _make_request(
        url,
        "/api/v1/connections/cancel",
        method="POST",
        data={"execution_id": "exec_cancel_test"},
    )
    assert status == 200
    assert data["cancelled"] is True
    assert token.is_cancelled is True

    # Cancel unknown
    status, data = _make_request(
        url,
        "/api/v1/connections/cancel",
        method="POST",
        data={"execution_id": "ghost_exec"},
    )
    assert status == 200
    assert data["cancelled"] is False

    # Missing execution_id
    status, data = _make_request(
        url,
        "/api/v1/connections/cancel",
        method="POST",
        data={},
    )
    assert status == 400


def test_create_server_with_pool_registers_default():
    dummy_pool = ConnectionPool(factory=lambda: sqlite3.connect(":memory:"))
    server = create_server(host="127.0.0.1", port=0, pool=dummy_pool)
    try:
        assert server.RequestHandlerClass.connection_pool is dummy_pool
        assert server.RequestHandlerClass.connection_pool_manager.has_pool("default")
    finally:
        server.server_close()
