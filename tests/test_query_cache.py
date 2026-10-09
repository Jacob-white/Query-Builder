"""
Tests for Query Caching Engine and SSE Streaming.
=================================================
Covers InMemoryLRUCache eviction, TTL expiration, thread safety, telemetry,
RedisQueryCache integration mocks, BaseConnector caching, and SSE streaming.
"""

from __future__ import annotations

import concurrent.futures
import json
import time
from unittest.mock import MagicMock

from query_builder.cache import (
    BaseQueryCache,
    InMemoryLRUCache,
    RedisQueryCache,
    compute_cache_key,
    get_global_cache,
    reset_global_cache,
    set_global_cache,
)
from query_builder.connectors.sqlite import SQLiteConnector
from query_builder.models import QuerySpec
from query_builder.server import create_server


def test_compute_cache_key_determinism():
    spec1 = {"table": "users", "columns": ["id", "name"], "limit": 10}
    spec2 = {"columns": ["id", "name"], "table": "users", "limit": 10}

    key1 = compute_cache_key(spec1, dialect="postgres")
    key2 = compute_cache_key(spec2, dialect="postgres")
    assert key1 == key2

    key_sqlite = compute_cache_key(spec1, dialect="sqlite")
    assert key1 != key_sqlite

    key_tenant1 = compute_cache_key(spec1, dialect="postgres", tenant_id="t1")
    key_tenant2 = compute_cache_key(spec1, dialect="postgres", tenant_id="t2")
    assert key_tenant1 != key_tenant2
    assert key1 != key_tenant1


def test_compute_cache_key_with_dataclass():
    spec_obj = QuerySpec(table="orders", columns=["id", "total"], limit=25)
    key = compute_cache_key(spec_obj, dialect="postgres")
    assert isinstance(key, str)
    assert len(key) == 64  # SHA256 hex string


def test_in_memory_lru_cache_basic_and_stats():
    cache = InMemoryLRUCache(max_entries=5, default_ttl=60)
    assert cache.get("k1") is None
    cache.set("k1", {"val": 1})
    assert cache.get("k1") == {"val": 1}

    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["size"] == 1
    assert stats["hit_ratio"] == 0.5


def test_in_memory_lru_cache_eviction():
    cache = InMemoryLRUCache(max_entries=3)
    cache.set("k1", 1)
    cache.set("k2", 2)
    cache.set("k3", 3)

    # Touch k1 to make k2 the least recently used
    _ = cache.get("k1")

    # Insert k4, should evict k2
    cache.set("k4", 4)
    assert cache.get("k2") is None
    assert cache.get("k1") == 1
    assert cache.get("k3") == 3
    assert cache.get("k4") == 4
    assert cache.stats()["evictions"] == 1


def test_in_memory_lru_cache_ttl_expiration():
    cache = InMemoryLRUCache(max_entries=10, default_ttl=1)
    cache.set("short_lived", "alive", ttl=0.05)
    assert cache.get("short_lived") == "alive"

    time.sleep(0.08)
    assert cache.get("short_lived") is None
    assert cache.stats()["expirations"] >= 1


def test_in_memory_lru_cache_delete_and_clear():
    cache = InMemoryLRUCache(max_entries=10)
    cache.set("a", 10)
    cache.set("b", 20)
    assert cache.delete("a") is True
    assert cache.delete("a") is False
    assert cache.get("a") is None

    cache.clear()
    assert cache.get("b") is None
    assert cache.stats()["size"] == 0


def test_in_memory_lru_cache_thread_safety():
    cache = InMemoryLRUCache(max_entries=100)

    def worker(worker_id: int):
        for i in range(50):
            k = f"key_{worker_id}_{i}"
            cache.set(k, i)
            _ = cache.get(k)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(worker, wid) for wid in range(4)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    assert cache.stats()["size"] <= 100
    assert cache.stats()["hits"] > 0


def test_redis_query_cache_mocked():
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps({"result": 42}).encode("utf-8")

    cache = RedisQueryCache(redis_client=mock_redis, prefix="qb:test:")
    val = cache.get("my_query")
    assert val == {"result": 42}
    mock_redis.get.assert_called_once_with("qb:test:my_query")

    cache.set("new_query", {"ans": 99}, ttl=120)
    mock_redis.set.assert_called_once_with(
        "qb:test:new_query", json.dumps({"ans": 99}), ex=120
    )

    cache.delete("new_query")
    mock_redis.delete.assert_called()

    stats = cache.stats()
    assert stats["type"] == "redis"
    assert stats["hits"] == 1


def test_compute_cache_key_with_raw_string():
    key = compute_cache_key("SELECT 1 FROM users")
    assert isinstance(key, str)
    assert len(key) == 64


def test_in_memory_lru_cache_update_existing():
    cache = InMemoryLRUCache(max_entries=5)
    cache.set("k1", 100)
    cache.set("k1", 200)
    assert cache.get("k1") == 200


def test_redis_query_cache_no_client(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "redis", None)  # `import redis` -> ImportError
    cache = RedisQueryCache(client=None)
    assert cache.client is None
    assert cache.get("k") is None
    cache.set("k", {"val": 1})
    assert cache.delete("k") is False
    cache.clear()
    stats = cache.stats()
    assert stats["connected"] is False
    assert stats["hits"] == 0


def test_redis_query_cache_ttl_zero_and_clear_keys():
    mock_redis = MagicMock()
    cache = RedisQueryCache(client=mock_redis)

    # ttl=0 should call client.set without an expiry
    cache.set("no_ttl", {"a": 1}, ttl=0)
    mock_redis.set.assert_called()

    # clear with keys
    mock_redis.scan_iter.return_value = iter(["qb:cache:k1", "qb:cache:k2"])
    cache.clear()
    mock_redis.scan_iter.assert_called_with(match="qb:cache:*", count=500)
    mock_redis.unlink.assert_called_with("qb:cache:k1", "qb:cache:k2")

    # clear when no keys match
    mock_redis.scan_iter.return_value = iter([])
    mock_redis.unlink.reset_mock()
    cache.clear()
    mock_redis.unlink.assert_not_called()


def test_redis_query_cache_default_init():
    # Tests default init path without passing client
    cache = RedisQueryCache()
    assert isinstance(cache, RedisQueryCache)


def test_redis_query_cache_miss_and_delete_error():
    mock_redis = MagicMock()
    mock_redis.get.return_value = None
    cache = RedisQueryCache(client=mock_redis)
    assert cache.get("missing_key") is None

    mock_redis.delete.side_effect = RuntimeError("Redis down")
    assert cache.delete("key") is False

    import sys

    fake_redis = MagicMock()
    sys.modules["redis"] = fake_redis
    try:
        c_url = RedisQueryCache()
        assert c_url.client is fake_redis.from_url.return_value
    finally:
        sys.modules.pop("redis", None)


def test_global_cache_singleton_management():
    import query_builder.cache

    query_builder.cache._global_cache_instance = None
    c_init = query_builder.cache.get_global_cache()
    assert isinstance(c_init, InMemoryLRUCache)

    reset_global_cache()
    c1 = get_global_cache()
    assert isinstance(c1, InMemoryLRUCache)

    class CustomCache(BaseQueryCache):
        def get(self, key):
            return "custom"

        def set(self, key, value, ttl=None):
            pass

        def delete(self, key):
            return True

        def clear(self):
            pass

        def stats(self):
            return {}

    custom = CustomCache()
    set_global_cache(custom)
    assert get_global_cache() is custom

    reset_global_cache()
    assert isinstance(get_global_cache(), InMemoryLRUCache)


def _writable_security():
    """These tests build their fixtures through the connector, so they opt out of the
    database-side read-only session (which now really refuses writes)."""
    from query_builder.config import SecurityConfig

    sec = SecurityConfig()
    sec.execution.enforce_read_only_session = False
    return sec


def test_sqlite_connector_caching_integration():
    reset_global_cache()
    conn = SQLiteConnector(":memory:", security=_writable_security())
    conn.execute_raw("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT);")
    conn.execute_raw("INSERT INTO items (name) VALUES ('Widget A'), ('Widget B');")

    spec = {"table": "items", "columns": ["id", "name"], "limit": 10}

    # First run without cache flag
    res1 = conn.execute(spec, use_cache=False)
    assert res1.get("cached") is False
    assert len(res1["rows"]) == 2

    # Second run with use_cache=True: should populate cache
    res2 = conn.execute(spec, use_cache=True)
    assert res2.get("cached") is False

    # Third run with use_cache=True: should return cached copy
    res3 = conn.execute(spec, use_cache=True)
    assert res3.get("cached") is True
    assert len(res3["rows"]) == 2


def test_server_execute_caching_and_sse_streaming(tmp_path):
    reset_global_cache()
    db_file = tmp_path / "test_stream.db"
    conn = SQLiteConnector(str(db_file), security=_writable_security())
    conn.execute_raw("CREATE TABLE products (id INTEGER, name TEXT);")
    for i in range(15):
        conn.execute_raw(f"INSERT INTO products VALUES ({i}, 'Prod {i}');")
    conn.connect().commit()

    server = create_server("127.0.0.1", 0)
    host, port = server.server_address
    import threading

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    import urllib.request

    base_url = f"http://{host}:{port}"

    try:
        # 1. Test Cached Execute
        payload = json.dumps(
            {
                "connector": "sqlite",
                "config": {"database": str(db_file)},
                "spec": {"table": "products", "columns": ["id", "name"], "limit": 10},
                "use_cache": True,
            }
        ).encode()

        req = urllib.request.Request(
            f"{base_url}/api/v1/execute",
            data=payload,
            headers={"Content-Type": "application/json", "Connection": "close"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            assert data["cached"] is False
            assert len(data["rows"]) == 10

        # Run again, should be cached
        req2 = urllib.request.Request(
            f"{base_url}/api/v1/execute",
            data=payload,
            headers={"Content-Type": "application/json", "Connection": "close"},
        )
        with urllib.request.urlopen(req2, timeout=5) as resp2:
            data2 = json.loads(resp2.read().decode())
            assert data2["cached"] is True
            assert len(data2["rows"]) == 10

        # 2. Test SSE Streaming
        stream_payload = json.dumps(
            {
                "connector": "sqlite",
                "config": {"database": str(db_file)},
                "spec": {"table": "products", "columns": ["id", "name"], "limit": 15},
                "batch_size": 5,
            }
        ).encode()

        stream_req = urllib.request.Request(
            f"{base_url}/api/v1/stream",
            data=stream_payload,
            headers={"Content-Type": "application/json", "Connection": "close"},
        )

        with urllib.request.urlopen(stream_req, timeout=5) as stream_resp:
            assert stream_resp.headers.get("Content-Type") == "text/event-stream"
            stream_body = stream_resp.read().decode()

            assert "event: metadata" in stream_body
            assert "event: batch" in stream_body
            assert "event: stats" in stream_body
            assert "event: done" in stream_body
            # 15 rows with batch_size=5 means 3 batch events
            assert stream_body.count("event: batch") == 3

    finally:
        server.shutdown()
        server.server_close()


def test_redis_query_cache_backs_off_after_connection_failure():
    mock_redis = MagicMock()
    mock_redis.get.side_effect = ConnectionError("down")
    cache = RedisQueryCache(client=mock_redis)

    assert cache.get("k") is None
    assert mock_redis.get.call_count == 1

    # Within the back-off window reads/writes do not touch Redis again...
    assert cache.get("k") is None
    cache.set("k", 1)
    assert mock_redis.get.call_count == 1
    mock_redis.set.assert_not_called()
    assert cache.stats()["connected"] is False
    # ...but invalidations are always attempted (see the dedicated tests below).
    mock_redis.delete.return_value = 1
    assert cache.delete("k") is True
    mock_redis.delete.assert_called_once_with("qb:cache:k")

    # After the window elapses it retries.
    cache._down_until = 0.0
    mock_redis.get.side_effect = None
    mock_redis.get.return_value = json.dumps({"ok": 1}).encode("utf-8")
    assert cache.get("k") == {"ok": 1}


def test_redis_query_cache_non_connection_errors_do_not_back_off():
    mock_redis = MagicMock()
    mock_redis.get.side_effect = ValueError("bad payload")
    mock_redis.set.side_effect = ValueError("bad payload")
    mock_redis.delete.side_effect = ValueError("bad payload")
    mock_redis.scan_iter.side_effect = ValueError("bad payload")
    cache = RedisQueryCache(client=mock_redis)

    assert cache.get("k") is None
    cache.set("k", 1)
    assert cache.delete("k") is False
    cache.clear()
    assert cache._down_until == 0.0


def test_redis_query_cache_connected_reflects_ping():
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True
    assert RedisQueryCache(client=mock_redis).stats()["connected"] is True

    # A failed health probe reports disconnected but must not disable caching by itself.
    mock_redis.ping.side_effect = OSError("refused")
    cache = RedisQueryCache(client=mock_redis)
    assert cache.stats()["connected"] is False
    assert cache._down_until == 0.0

    # Minimal duck-typed clients without `ping` are assumed reachable.
    assert (
        RedisQueryCache(client=MagicMock(spec=["get", "set"])).stats()["connected"]
        is True
    )


def test_redis_query_cache_clear_falls_back_to_keys_without_scan_iter():
    client = MagicMock(spec=["keys", "delete", "get", "set"])
    client.keys.return_value = ["qb:cache:a"]
    RedisQueryCache(client=client).clear()
    client.keys.assert_called_once_with("qb:cache:*")
    client.delete.assert_called_once_with("qb:cache:a")  # no unlink on this client


def test_redis_query_cache_failed_clear_keeps_counters_and_backs_off_on_connection_loss():
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps(1).encode("utf-8")
    cache = RedisQueryCache(client=mock_redis)
    assert cache.get("k") == 1
    mock_redis.scan_iter.side_effect = ConnectionError("down")
    cache.clear()
    assert cache.stats()["hits"] == 1  # not reset: nothing was cleared
    assert cache._down_until > 0.0


def test_redis_query_cache_stats_reuses_recent_health_probe():
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True
    cache = RedisQueryCache(client=mock_redis)
    for _ in range(5):
        assert cache.stats()["connected"] is True
    assert mock_redis.ping.call_count == 1

    # After the TTL the probe runs again and can flip the status.
    cache._health = (cache._health[0] - cache._HEALTH_TTL_SECONDS - 1, True)
    mock_redis.ping.return_value = False
    assert cache.stats()["connected"] is False
    assert mock_redis.ping.call_count == 2


def test_redis_query_cache_invalidations_ignore_read_backoff():
    mock_redis = MagicMock()
    mock_redis.get.side_effect = ConnectionError("blip")
    mock_redis.delete.return_value = 1
    mock_redis.scan_iter.return_value = iter(["qb:cache:a"])
    cache = RedisQueryCache(client=mock_redis)

    assert cache.get("k") is None  # transient read failure starts the back-off
    assert cache._down_until > 0.0

    assert cache.delete("k") is True  # still contacts Redis
    mock_redis.delete.assert_called_once_with("qb:cache:k")
    assert cache._down_until == 0.0  # success proves it is reachable again

    cache._down_until = time.monotonic() + 100
    cache.clear()
    mock_redis.unlink.assert_called_once_with("qb:cache:a")
    assert cache._down_until == 0.0


def test_redis_query_cache_invalidation_failures_extend_backoff():
    mock_redis = MagicMock()
    mock_redis.delete.side_effect = ConnectionError("down")
    cache = RedisQueryCache(client=mock_redis)
    assert cache.delete("k") is False
    assert cache._down_until > 0.0
    # and a following invalidation is still attempted
    assert cache.delete("k") is False
    assert mock_redis.delete.call_count == 2


def test_redis_query_cache_clear_deletes_in_bounded_batches():
    mock_redis = MagicMock()
    keys = [f"qb:cache:{i}" for i in range(1203)]
    mock_redis.scan_iter.return_value = iter(keys)
    RedisQueryCache(client=mock_redis).clear()
    sizes = [len(c.args) for c in mock_redis.unlink.call_args_list]
    assert sizes == [500, 500, 203]
    assert mock_redis.scan_iter.call_args.kwargs["count"] == 500
    mock_redis.delete.assert_not_called()

    # KEYS fallback is chunked too, and uses DEL when UNLINK is unavailable.
    client = MagicMock(spec=["keys", "delete", "get", "set"])
    client.keys.return_value = keys
    RedisQueryCache(client=client).clear()
    assert [len(c.args) for c in client.delete.call_args_list] == [500, 500, 203]


def test_redis_query_cache_clear_escapes_glob_metacharacters_in_prefix():
    mock_redis = MagicMock()
    mock_redis.scan_iter.return_value = iter([])
    RedisQueryCache(client=mock_redis, prefix=r"app[1]*?\:").clear()
    pattern = mock_redis.scan_iter.call_args.kwargs["match"]
    assert pattern == r"app\[1\]\*\?\\:*"


def test_redis_query_cache_clear_failure_mid_way_keeps_counters():
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps(1).encode("utf-8")
    mock_redis.scan_iter.return_value = iter(["qb:cache:a"])
    mock_redis.unlink.side_effect = ConnectionError("down")
    cache = RedisQueryCache(client=mock_redis)
    cache.get("k")
    cache.clear()
    assert cache.stats()["hits"] == 1
    assert cache._down_until > 0.0


def test_redis_query_cache_classifies_redis_py_subclasses_as_outages():
    import pytest

    redis_exceptions = pytest.importorskip("redis.exceptions")
    for name in (
        "ConnectionError",
        "TimeoutError",
        "BusyLoadingError",
        "AuthenticationError",
        "MaxConnectionsError",
    ):
        exc_cls = getattr(redis_exceptions, name)
        mock_redis = MagicMock()
        mock_redis.get.side_effect = exc_cls("x")
        cache = RedisQueryCache(client=mock_redis)
        cache.get("k")
        assert cache._down_until > 0.0, name

    # Server-side command errors are not outages.
    mock_redis = MagicMock()
    mock_redis.get.side_effect = redis_exceptions.ResponseError("WRONGTYPE")
    cache = RedisQueryCache(client=mock_redis)
    cache.get("k")
    assert cache._down_until == 0.0


def test_redis_query_cache_outage_classification_fallbacks():
    import sys

    class BusyLoadingError(Exception):  # look-alike, matched by class name
        pass

    class Custom(BusyLoadingError):
        pass

    for registry in (None, MagicMock()):
        saved = sys.modules.get("redis")
        saved_exc = sys.modules.get("redis.exceptions")
        # `None` makes `import redis` raise ImportError; a MagicMock exposes non-class attributes.
        sys.modules["redis"] = registry
        sys.modules["redis.exceptions"] = registry
        try:
            mock_redis = MagicMock()
            mock_redis.get.side_effect = Custom("x")
            cache = RedisQueryCache(client=mock_redis)
            cache.get("k")
            assert cache._down_until > 0.0
            mock_redis.get.side_effect = ValueError("x")
            cache2 = RedisQueryCache(client=mock_redis)
            cache2.get("k")
            assert cache2._down_until == 0.0
        finally:
            for name, mod in (("redis", saved), ("redis.exceptions", saved_exc)):
                if mod is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = mod


def test_redis_query_cache_timeouts_connect_short_commands_long():
    import sys

    fake_redis = MagicMock()
    sys.modules["redis"] = fake_redis
    try:
        RedisQueryCache()
        kwargs = fake_redis.from_url.call_args.kwargs
        assert kwargs["socket_connect_timeout"] == 2.0
        assert kwargs["socket_timeout"] == 30.0
        RedisQueryCache(connect_timeout=1.0, command_timeout=None)
        kwargs = fake_redis.from_url.call_args.kwargs
        assert kwargs["socket_connect_timeout"] == 1.0
        assert kwargs["socket_timeout"] is None
    finally:
        sys.modules.pop("redis", None)
