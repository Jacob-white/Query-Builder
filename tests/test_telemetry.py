"""
Tests for Query Execution Telemetry Engine.
===========================================
Verifies SQL fingerprinting, ring-buffer event storage, percentile calculations,
tenant filtering, thread safety, and metrics resets.
"""

from __future__ import annotations

import concurrent.futures

from query_builder.telemetry import TelemetryCollector, hash_query


def test_hash_query_normalizes_whitespace():
    sql1 = "SELECT  id,   name\nFROM   users\nWHERE id = 1"
    sql2 = "SELECT id, name FROM users WHERE id = 1"
    sql3 = "\tSELECT   id,  name  FROM \t users  WHERE  id = 1\n"
    h1 = hash_query(sql1)
    h2 = hash_query(sql2)
    h3 = hash_query(sql3)
    assert len(h1) == 16
    assert h1 == h2 == h3


def test_hash_query_empty():
    assert hash_query("") == ""
    assert hash_query("   \n\t  ") == ""
    assert hash_query(None) == ""  # type: ignore
    assert hash_query(123) == ""  # type: ignore


def test_telemetry_record_success():
    tc = TelemetryCollector()
    event = tc.record_execution(
        sql="SELECT 1",
        latency_ms=12.34,
        row_count=1,
        status="success",
        dialect="postgres",
        tenant_id="t1",
        user_id="u1",
    )
    assert event.query_hash == hash_query("SELECT 1")
    assert event.status == "success"
    assert event.latency_ms == 12.34

    metrics = tc.get_metrics()
    assert metrics["total_queries"] == 1
    assert metrics["success_count"] == 1
    assert metrics["error_count"] == 0
    assert metrics["error_rate"] == 0.0
    assert metrics["avg_latency_ms"] == 12.34
    assert metrics["active_tenants_count"] == 1


def test_telemetry_record_error():
    tc = TelemetryCollector()
    tc.record_execution(
        sql="SELECT syntax error",
        latency_ms=5.0,
        status="error",
        error_message="Syntax error near 'syntax'",
        tenant_id="t2",
    )
    metrics = tc.get_metrics()
    assert metrics["total_queries"] == 1
    assert metrics["success_count"] == 0
    assert metrics["error_count"] == 1
    assert metrics["error_rate"] == 1.0


def test_telemetry_ring_buffer_overflow():
    tc = TelemetryCollector(max_size=3)
    tc.record_execution("SELECT 1", 1.0)
    tc.record_execution("SELECT 2", 2.0)
    tc.record_execution("SELECT 3", 3.0)
    tc.record_execution("SELECT 4", 4.0)

    recent = tc.get_recent_events(limit=10)
    assert len(recent) == 3
    # Newest first
    sqls = [e["sql"] for e in recent]
    assert sqls == ["SELECT 4", "SELECT 3", "SELECT 2"]


def test_telemetry_percentiles_calculation():
    tc = TelemetryCollector()
    # Insert 100 executions with latencies 1 through 100 ms
    for i in range(1, 101):
        tc.record_execution(f"SELECT {i}", float(i))

    metrics = tc.get_metrics()
    assert metrics["total_queries"] == 100
    assert metrics["avg_latency_ms"] == 50.5
    # For 0-indexed 100 elements: index 50 is 51.0, index 94 is 95.0, index 98 is 99.0
    assert metrics["p50_latency_ms"] in (50.0, 51.0)
    assert metrics["p95_latency_ms"] in (95.0, 96.0)
    assert metrics["p99_latency_ms"] in (99.0, 100.0)


def test_telemetry_metrics_empty():
    tc = TelemetryCollector()
    metrics = tc.get_metrics()
    assert metrics["total_queries"] == 0
    assert metrics["success_count"] == 0
    assert metrics["error_count"] == 0
    assert metrics["error_rate"] == 0.0
    assert metrics["avg_latency_ms"] == 0.0
    assert metrics["p50_latency_ms"] == 0.0
    assert metrics["p95_latency_ms"] == 0.0
    assert metrics["p99_latency_ms"] == 0.0
    assert metrics["active_tenants_count"] == 0


def test_telemetry_get_recent_events_filter():
    tc = TelemetryCollector()
    tc.record_execution("SELECT 1", 10.0, tenant_id="tA")
    tc.record_execution("SELECT 2", 20.0, tenant_id="tB")
    tc.record_execution("SELECT 3", 30.0, tenant_id="tA")

    events_a = tc.get_recent_events(limit=10, tenant_id="tA")
    assert len(events_a) == 2
    assert all(e["tenant_id"] == "tA" for e in events_a)

    events_b = tc.get_recent_events(limit=10, tenant_id="tB")
    assert len(events_b) == 1
    assert events_b[0]["sql"] == "SELECT 2"


def test_telemetry_clear():
    tc = TelemetryCollector()
    tc.record_execution("SELECT 1", 10.0, tenant_id="t1")
    assert tc.get_metrics()["total_queries"] == 1

    tc.clear()
    assert tc.get_metrics()["total_queries"] == 0
    assert tc.get_recent_events() == []


def test_telemetry_thread_safety():
    tc = TelemetryCollector(max_size=200)

    def worker(worker_id: int):
        for j in range(20):
            tc.record_execution(
                f"SELECT {worker_id}_{j}",
                float(j),
                tenant_id=f"t_{worker_id}",
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(worker, i) for i in range(5)]
        for f in futures:
            f.result()

    metrics = tc.get_metrics()
    assert metrics["total_queries"] == 100
    assert metrics["success_count"] == 100
    assert metrics["active_tenants_count"] == 5
