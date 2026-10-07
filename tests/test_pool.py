"""
Tests for Thread-Safe Database Connection Pool.
===============================================
Verifies connection acquisition, release, context manager semantics,
health checks, idle eviction, capacity limits, timeout, and thread safety.
"""

from __future__ import annotations

import concurrent.futures
import sqlite3
import time

import pytest

from query_builder.pool import (
    ConnectionPool,
    PoolClosedError,
    PoolTimeoutError,
)


class FailingConnection:
    """Simulates a broken connection whose cursor execution fails."""

    def __init__(self) -> None:
        self.is_closed = False

    def cursor(self):
        class BrokenCursor:
            def execute(self, sql):
                raise RuntimeError("Database disconnected.")

            def close(self):
                pass

        return BrokenCursor()

    def close(self):
        self.is_closed = True


def test_pool_acquire_and_release():
    pool = ConnectionPool(factory=lambda: sqlite3.connect(":memory:"), max_size=5)
    assert pool.size == 0
    assert pool.available_count == 0
    assert pool.in_use_count == 0

    conn = pool.acquire()
    assert pool.size == 1
    assert pool.in_use_count == 1
    assert pool.available_count == 0

    pool.release(conn)
    assert pool.size == 1
    assert pool.in_use_count == 0
    assert pool.available_count == 1

    # Releasing untracked connection does nothing
    pool.release(sqlite3.connect(":memory:"))

    pool.close_all()


def test_pool_context_manager_success():
    pool = ConnectionPool(factory=lambda: sqlite3.connect(":memory:"), max_size=2)
    with pool.connection() as conn:
        assert pool.in_use_count == 1
        cur = conn.cursor()
        cur.execute("SELECT 42")
        assert cur.fetchone()[0] == 42
    assert pool.in_use_count == 0
    assert pool.available_count == 1
    pool.close_all()


def test_pool_context_manager_exception():
    pool = ConnectionPool(factory=lambda: sqlite3.connect(":memory:"), max_size=2)
    with (
        pytest.raises(ValueError, match="Intentional error"),
        pool.connection(),
    ):
        assert pool.in_use_count == 1
        raise ValueError("Intentional error")

    assert pool.in_use_count == 0
    assert pool.available_count == 1
    pool.close_all()


def test_pool_health_check_success():
    pool = ConnectionPool(
        factory=lambda: sqlite3.connect(":memory:"),
        health_check_sql="SELECT 1",
    )
    conn = pool.acquire()
    pool.release(conn)

    # Second acquire will run health check and succeed
    conn2 = pool.acquire()
    assert conn2 is conn
    pool.release(conn2)
    pool.close_all()


def test_pool_health_check_failure_recreates():
    calls = 0

    def factory():
        nonlocal calls
        calls += 1
        if calls == 1:
            return FailingConnection()
        return sqlite3.connect(":memory:")

    pool = ConnectionPool(factory=factory, health_check_sql="SELECT 1")
    conn1 = pool.acquire()
    assert isinstance(conn1, FailingConnection)
    pool.release(conn1)

    # Next acquire runs health check which fails, so it recreates connection
    conn2 = pool.acquire()
    assert isinstance(conn2, sqlite3.Connection)
    assert conn1.is_closed is True
    pool.release(conn2)
    pool.close_all()


def test_pool_max_idle_eviction():
    pool = ConnectionPool(
        factory=lambda: sqlite3.connect(":memory:"),
        max_idle_seconds=0.01,  # 10ms idle cutoff
    )
    conn1 = pool.acquire()
    pool.release(conn1)

    # Sleep longer than idle seconds
    time.sleep(0.02)

    conn2 = pool.acquire()
    # New connection created due to idle eviction
    assert conn2 is not conn1
    pool.release(conn2)
    pool.close_all()


def test_pool_capacity_limit_and_timeout():
    pool = ConnectionPool(
        factory=lambda: sqlite3.connect(":memory:"),
        max_size=1,
        timeout=0.05,
    )
    conn1 = pool.acquire()
    assert pool.in_use_count == 1

    # Second acquire exceeds capacity and times out
    with pytest.raises(PoolTimeoutError, match="timed out"):
        pool.acquire()

    pool.release(conn1)
    pool.close_all()


def test_pool_close_all():
    pool = ConnectionPool(factory=lambda: sqlite3.connect(":memory:"), max_size=3)
    conn1 = pool.acquire()
    conn2 = pool.acquire()
    pool.release(conn1)

    assert pool.size == 2
    pool.close_all()
    assert pool.size == 0

    with pytest.raises(PoolClosedError, match="pool is closed"):
        pool.acquire()

    # Releasing after close closes the connection
    pool.release(conn2)


def test_pool_close_wakes_waiting_thread():
    pool = ConnectionPool(
        factory=lambda: sqlite3.connect(":memory:"),
        max_size=1,
        timeout=1.0,
    )
    conn = pool.acquire()

    def waiter():
        with pytest.raises(PoolClosedError):
            pool.acquire()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        fut = executor.submit(waiter)
        time.sleep(0.05)
        pool.close_all()
        fut.result()

    pool.release(conn)


def test_pool_multithreaded_concurrency():
    pool = ConnectionPool(
        factory=lambda: sqlite3.connect(":memory:"),
        max_size=5,
        timeout=5.0,
    )

    def worker(worker_id: int):
        for _ in range(5):
            with pool.connection() as conn:
                cur = conn.cursor()
                cur.execute(f"SELECT {worker_id}")
                res = cur.fetchone()[0]
                assert res == worker_id
                time.sleep(0.001)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(worker, i) for i in range(10)]
        for f in futures:
            f.result()

    assert pool.in_use_count == 0
    assert pool.size <= 5
    pool.close_all()


def test_pool_release_when_closed():
    pool = ConnectionPool(factory=lambda: sqlite3.connect(":memory:"), max_size=2)
    conn = pool.acquire()
    pool._closed = True
    pool.release(conn)
    assert pool.available_count == 0


def test_pool_min_size_prepopulates():
    pool = ConnectionPool(
        factory=lambda: sqlite3.connect(":memory:"),
        max_size=5,
        min_size=3,
    )
    assert pool.size == 3
    assert pool.available_count == 3
    assert pool.in_use_count == 0
    pool.close_all()


def test_pool_max_lifespan_eviction():
    pool = ConnectionPool(
        factory=lambda: sqlite3.connect(":memory:"),
        max_lifespan_seconds=0.01,
    )
    conn1 = pool.acquire()
    pool.release(conn1)
    time.sleep(0.02)
    conn2 = pool.acquire()
    assert conn2 is not conn1
    pool.release(conn2)
    pool.close_all()


def test_cancellation_token_lifecycle():
    from query_builder.pool import CancellationToken, QueryCancelledError

    token = CancellationToken()
    assert token.is_cancelled is False
    token.throw_if_cancelled()  # Does not raise

    called = []
    token.register_callback(lambda: called.append("hook1"))
    token.register_callback(
        lambda: (_ for _ in ()).throw(RuntimeError("hook error"))
    )  # Error resilient

    token.cancel()
    assert token.is_cancelled is True
    assert "hook1" in called

    # Double cancel does nothing
    token.cancel()

    # Registering callback after cancel runs immediately (including error resilience)
    token.register_callback(lambda: called.append("hook2"))
    token.register_callback(
        lambda: (_ for _ in ()).throw(ValueError("post-cancel hook error"))
    )
    assert "hook2" in called

    # Immediate throw when cancelled
    with pytest.raises(QueryCancelledError, match="Query execution was cancelled."):
        token.throw_if_cancelled()


def test_mask_credentials():
    from query_builder.pool import mask_credentials

    # String URI
    uri = "postgresql://myuser:supersecretpass@db.example.com:5432/mydb"
    masked_uri = mask_credentials(uri)
    assert "supersecretpass" not in masked_uri
    assert masked_uri == "postgresql://myuser:***@db.example.com:5432/mydb"

    # Dict with sensitive keys
    data = {
        "host": "localhost",
        "port": 5432,
        "password": "p@ssword123",
        "nested": {
            "api_key": "sk-1234567890",
            "token": "tok_abcdef",
            "name": "public_dataset",
        },
        "tags": ["prod", "db"],
        "tuple_items": ("admin", "secret_token_val"),
    }
    masked_data = mask_credentials(data)
    assert masked_data["password"] == "***"
    assert masked_data["nested"]["api_key"] == "***"
    assert masked_data["nested"]["token"] == "***"
    assert masked_data["nested"]["name"] == "public_dataset"
    assert masked_data["host"] == "localhost"
    assert masked_data["tags"] == ["prod", "db"]

    # Non-container types
    assert mask_credentials(12345) == 12345
    assert mask_credentials(None) is None


def test_connection_pool_manager_lifecycle():
    from query_builder.pool import (
        ConnectionPool,
        ConnectionPoolManager,
        PoolError,
    )

    mgr = ConnectionPoolManager()
    assert mgr.list_pools() == []

    # Invalid connection_id
    with pytest.raises(ValueError, match="non-empty string"):
        mgr.register_pool(
            "", ConnectionPool(factory=lambda: sqlite3.connect(":memory:"))
        )

    # Invalid pool type
    with pytest.raises(TypeError, match="instance of ConnectionPool"):
        mgr.register_pool("main", "not a pool")  # type: ignore

    pool1 = ConnectionPool(factory=lambda: sqlite3.connect(":memory:"), max_size=3)
    mgr.register_pool("db1", pool1, metadata={"dialect": "sqlite", "password": "pass"})
    assert mgr.has_pool("db1") is True
    assert mgr.has_pool("db2") is False
    assert mgr.get_pool("db1") is pool1

    # Overwrite pool with new instance closes old
    pool2 = ConnectionPool(factory=lambda: sqlite3.connect(":memory:"), max_size=2)
    mgr.register_pool("db1", pool2, metadata={"dialect": "sqlite"})
    assert pool1._closed is True
    assert mgr.get_pool("db1") is pool2

    # Listing pools masks secrets in metadata
    pools_list = mgr.list_pools()
    assert len(pools_list) == 1
    assert pools_list[0]["connection_id"] == "db1"
    assert pools_list[0]["metadata"]["dialect"] == "sqlite"

    # Context manager connection
    with mgr.connection("db1") as conn:
        cur = conn.cursor()
        cur.execute("SELECT 77")
        assert cur.fetchone()[0] == 77

    # Remove pool
    mgr.remove_pool("db1")
    assert mgr.has_pool("db1") is False
    assert pool2._closed is True
    with pytest.raises(PoolError, match="not registered"):
        mgr.get_pool("db1")

    # Close all
    pool3 = ConnectionPool(factory=lambda: sqlite3.connect(":memory:"), max_size=2)
    mgr.register_pool("db3", pool3)
    mgr.close_all()
    assert mgr.has_pool("db3") is False
    assert pool3._closed is True


def test_connection_pool_manager_test_connection():
    from query_builder.pool import ConnectionPool, ConnectionPoolManager

    mgr = ConnectionPoolManager()

    # 1. Test by registered ID
    pool = ConnectionPool(factory=lambda: sqlite3.connect(":memory:"))
    mgr.register_pool("test_id", pool, metadata={"dialect": "sqlite"})
    res1 = mgr.test_connection("test_id")
    assert res1["healthy"] is True
    assert res1["dialect"] == "sqlite"
    assert res1["latency_ms"] >= 0.0

    # 2. Test by ConnectionPool instance
    res2 = mgr.test_connection(pool)
    assert res2["healthy"] is True
    assert res2["dialect"] == "custom"

    # 3. Test by connector dict
    res3 = mgr.test_connection({"connector": "sqlite", "database": ":memory:"})
    assert res3["healthy"] is True
    assert res3["dialect"] == "sqlite"

    # 4. Test error handling on missing pool
    res_err = mgr.test_connection("non_existent_pool")
    assert res_err["healthy"] is False
    assert "not registered" in res_err["error"]

    # 5. Invalid target type
    res_type_err = mgr.test_connection(12345)  # type: ignore
    assert res_type_err["healthy"] is False
    assert "Invalid target type" in res_type_err["error"]

    mgr.close_all()


def test_connection_pool_manager_execution_and_cancellation():
    from query_builder.pool import (
        ConnectionPool,
        ConnectionPoolManager,
        QueryCancelledError,
    )

    mgr = ConnectionPoolManager()

    # Create execution token
    eid, token = mgr.create_execution("exec_1")
    assert mgr.get_execution("exec_1") is token

    # Re-creating with existing execution_id returns existing token
    eid_existing, token_existing = mgr.create_execution("exec_1")
    assert eid_existing == "exec_1"
    assert token_existing is token

    assert mgr.cancel_execution("exec_1") is True
    assert token.is_cancelled is True

    # Cancel non-existent
    assert mgr.cancel_execution("unknown_exec") is False

    mgr.unregister_execution("exec_1")
    assert mgr.get_execution("exec_1") is None

    # Execute query on pooled connection
    pool = ConnectionPool(factory=lambda: sqlite3.connect(":memory:"))
    with pool.connection() as conn:
        conn.execute("CREATE TABLE test_items (id INT, name TEXT)")
        conn.execute("INSERT INTO test_items VALUES (1, 'Widget'), (2, 'Gadget')")
        conn.commit()

    mgr.register_pool("sqlite_pool", pool, metadata={"dialect": "sqlite"})

    # Successful pooled query
    out = mgr.execute_query(
        sql_or_spec="SELECT * FROM test_items ORDER BY id",
        connection_id="sqlite_pool",
    )
    assert out["columns"] == ["id", "name"]
    assert len(out["rows"]) == 2
    assert out["rows"][0]["name"] == "Widget"

    # Pooled query on connection having .cancel hook instead of .interrupt
    class MockCancelConnection:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

        def cursor(self):
            class MockCursor:
                description = [("col",)]

                def execute(self, sql, params=None):
                    pass

                def fetchall(self):
                    return [(42,)]

                def close(self):
                    pass

            return MockCursor()

        def close(self):
            pass

    cancel_pool = ConnectionPool(factory=MockCancelConnection)
    mgr.register_pool("cancel_db", cancel_pool, metadata={"dialect": "custom"})
    out_cancel = mgr.execute_query("SELECT 42", connection_id="cancel_db")
    assert out_cancel["count"] == 1

    # Execute query with cancelled token raises QueryCancelledError
    _, cancel_tok = mgr.create_execution()
    cancel_tok.cancel()
    with pytest.raises(QueryCancelledError):
        mgr.execute_query(
            sql_or_spec="SELECT 1",
            connection_id="sqlite_pool",
            cancellation_token=cancel_tok,
        )

    # Execute query via ConnectorRegistry fallback
    out_registry = mgr.execute_query(
        sql_or_spec="SELECT 99 as val",
        dialect="sqlite",
        config={"database": ":memory:"},
    )
    assert out_registry["columns"] == ["val"]
    assert len(out_registry["rows"]) == 1

    # Execute compiled spec via pooled connection
    out_spec = mgr.execute_query(
        sql_or_spec={
            "table": "test_items",
            "columns": ["id"],
            "joins": [],
            "filters": [],
            "order_by": [],
            "limit": 10,
        },
        connection_id="sqlite_pool",
    )
    assert out_spec["count"] >= 0

    # Execute spec via ConnectorRegistry fallback
    from unittest.mock import MagicMock, patch
    from query_builder.connectors.registry import ConnectorRegistry

    mock_conn = MagicMock()
    mock_conn.execute.return_value = {"sql": "SELECT 1", "rows": [], "count": 0}
    with patch.object(ConnectorRegistry, "get", return_value=mock_conn):
        out_reg_spec = mgr.execute_query(
            sql_or_spec={"table": "dummy"},
            dialect="mock_db",
        )
        assert out_reg_spec["sql"] == "SELECT 1"

    mgr.close_all()


def test_connection_pool_manager_singleton():
    from unittest.mock import patch
    import query_builder.pool as pool_mod
    from query_builder.pool import (
        ConnectionPoolManager,
        get_connection_pool_manager,
        reset_connection_pool_manager,
    )

    reset_connection_pool_manager()
    mgr1 = get_connection_pool_manager()
    mgr2 = get_connection_pool_manager()
    assert mgr1 is mgr2

    # Test remove non-existent pool (line 308->exit)
    mgr1.remove_pool("non_existent_pool_id")

    # Test plain connection without interrupt or cancel methods (line 485->488)
    class PlainConn:
        def cursor(self):
            class Cur:
                def execute(self, sql, *args):
                    pass

                def fetchall(self):
                    return [(1,)]

                def close(self):
                    pass

                @property
                def description(self):
                    return [("col", None, None, None, None, None, None)]

            return Cur()

    plain_pool = ConnectionPool(factory=PlainConn, max_size=1)
    mgr1.register_pool("plain_pool", pool=plain_pool)
    res = mgr1.execute_query("SELECT 1", connection_id="plain_pool")
    assert res["count"] == 1

    # Test double-checked lock race condition (line 559->561)
    reset_connection_pool_manager()
    original_lock = pool_mod._GLOBAL_POOL_LOCK

    class RaceLock:
        def __enter__(self):
            original_lock.acquire()
            pool_mod._GLOBAL_POOL_MANAGER = ConnectionPoolManager()
            return self

        def __exit__(self, *args):
            original_lock.release()

    with patch.object(pool_mod, "_GLOBAL_POOL_LOCK", RaceLock()):
        mgr_raced = get_connection_pool_manager()
        assert mgr_raced is not None

    reset_connection_pool_manager()
    mgr3 = get_connection_pool_manager()
    assert mgr3 is not mgr1
    reset_connection_pool_manager()
