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
