"""
Tests for AsyncConnectionPool, AsyncConnectionPoolManager, and AsyncCancellationToken.
"""

import asyncio
import pytest
from query_builder import (
    AsyncCancellationToken,
    AsyncConnectionPool,
    get_async_connection_pool_manager,
    reset_async_connection_pool_manager,
)
from query_builder.pool import (
    PoolClosedError,
    PoolTimeoutError,
    QueryCancelledError,
)


class MockAsyncConnection:
    def __init__(self, conn_id: int):
        self.conn_id = conn_id
        self.is_closed = False
        self.queries_run: list[str] = []

    async def execute(self, sql: str) -> None:
        if self.is_closed:
            raise RuntimeError("Connection is closed.")
        self.queries_run.append(sql)

    async def close(self) -> None:
        self.is_closed = True


class MockCursor:
    def __init__(self):
        self.closed = False

    def execute(self, sql: str):
        pass

    def close(self):
        self.closed = True


class MockSyncConnection:
    def __init__(self, conn_id: int):
        self.conn_id = conn_id
        self.is_closed = False

    def cursor(self):
        return MockCursor()

    def close(self):
        self.is_closed = True


@pytest.mark.anyio
async def test_async_pool_acquire_and_release():
    conn_counter = 0

    async def factory():
        nonlocal conn_counter
        conn_counter += 1
        return MockAsyncConnection(conn_counter)

    pool = AsyncConnectionPool(factory=factory, max_size=3, min_size=1)
    await pool.initialize()

    assert pool.size == 1
    assert pool.available_count == 1
    assert pool.in_use_count == 0

    conn1 = await pool.acquire()
    assert conn1.conn_id == 1
    assert pool.in_use_count == 1
    assert pool.available_count == 0

    # Acquire second connection up to max_size
    conn2 = await pool.acquire()
    assert conn2.conn_id == 2
    assert pool.size == 2

    # Release back
    await pool.release(conn1)
    assert pool.in_use_count == 1
    assert pool.available_count == 1

    # Re-acquire reuses conn1
    reacquired = await pool.acquire()
    assert reacquired.conn_id == 1

    await pool.release(conn2)
    await pool.release(reacquired)
    await pool.close()

    assert pool.size == 0
    assert conn1.is_closed is True
    assert conn2.is_closed is True


@pytest.mark.anyio
async def test_async_pool_context_manager():
    async def factory():
        return MockAsyncConnection(99)

    pool = AsyncConnectionPool(factory=factory, max_size=2)
    async with pool.connection() as conn:
        assert conn.conn_id == 99
        assert pool.in_use_count == 1
    assert pool.in_use_count == 0
    assert pool.available_count == 1
    await pool.close()


@pytest.mark.anyio
async def test_async_pool_timeout():
    async def factory():
        return MockAsyncConnection(1)

    pool = AsyncConnectionPool(factory=factory, max_size=1, timeout=0.05)
    conn1 = await pool.acquire()

    with pytest.raises(PoolTimeoutError, match="Timeout waiting for connection"):
        await pool.acquire()

    await pool.release(conn1)
    await pool.close()


@pytest.mark.anyio
async def test_async_cancellation_token():
    token = AsyncCancellationToken()
    assert not token.is_cancelled

    cancelled_called = False

    def on_cancel():
        nonlocal cancelled_called
        cancelled_called = True

    token.register_callback(on_cancel)
    await token.cancel()

    assert token.is_cancelled
    assert cancelled_called is True

    with pytest.raises(QueryCancelledError, match="Query execution was cancelled"):
        token.throw_if_cancelled()


@pytest.mark.anyio
async def test_async_pool_cancellation_during_acquire():
    async def factory():
        return MockAsyncConnection(1)

    pool = AsyncConnectionPool(factory=factory, max_size=1)
    token = AsyncCancellationToken()
    await token.cancel()

    with pytest.raises(QueryCancelledError):
        await pool.acquire(token=token)

    await pool.close()


@pytest.mark.anyio
async def test_async_pool_idle_and_expired_eviction():
    counter = 0

    async def factory():
        nonlocal counter
        counter += 1
        return MockAsyncConnection(counter)

    # 0.05s max idle
    pool = AsyncConnectionPool(
        factory=factory, max_size=2, max_idle_seconds=0.05, max_lifespan_seconds=0.1
    )
    conn1 = await pool.acquire()
    assert conn1.conn_id == 1
    await pool.release(conn1)

    await asyncio.sleep(0.06)

    # Re-acquire should evict conn1 as idle and create conn2
    conn2 = await pool.acquire()
    assert conn2.conn_id == 2
    assert conn1.is_closed is True

    await pool.release(conn2)
    await pool.close()


@pytest.mark.anyio
async def test_async_pool_sync_factory_and_cursor_health_check():
    counter = 0

    def sync_factory():
        nonlocal counter
        counter += 1
        return MockSyncConnection(counter)

    pool = AsyncConnectionPool(factory=sync_factory, max_size=2)
    conn = await pool.acquire()
    assert conn.conn_id == 1
    await pool.release(conn)
    await pool.close()
    assert conn.is_closed is True


@pytest.mark.anyio
async def test_async_pool_closed_error():
    async def factory():
        return MockAsyncConnection(1)

    pool = AsyncConnectionPool(factory=factory)
    await pool.close()

    with pytest.raises(PoolClosedError):
        await pool.acquire()


@pytest.mark.anyio
async def test_async_pool_manager():
    await reset_async_connection_pool_manager()
    manager = get_async_connection_pool_manager()

    async def factory():
        return MockAsyncConnection(10)

    p1 = await manager.get_or_create("db1", factory=factory, max_size=5)
    assert p1 is not None
    assert manager.get_pool("db1") is p1

    conn = await p1.acquire()
    assert conn.conn_id == 10
    await p1.release(conn)

    await reset_async_connection_pool_manager()
    assert manager.get_pool("db1") is None
