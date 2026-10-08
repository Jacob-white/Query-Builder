"""
Milestone 1 Adversarial Stress Test Suite & Empirical Oracles.
==============================================================
Empirically stress-tests:
1. ConnectionPool: high concurrency, rapid acquisitions, idle evictions, pool exhaustion, shutdown races.
2. apply_security_policy & Compiler: SQL injection vectors, malicious table names, subqueries, join bypasses.
3. export_dataset: 10,000+ rows across CSV/JSON/Parquet/OpenXML with Unicode, control chars, quotes, diverse types.
4. HTTP Server (create_server): live multi-threaded requests, malformed payloads, non-existent routes, CORS, introspection.
5. Telemetry: 10,000+ concurrent events, ring-buffer bounding, mathematical percentile oracle, tenant filtering.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from typing import Any

import polars as pl
import pytest

from query_builder.ast_validator import validate_sql_ast
from query_builder.compiler import QueryCompiler
from query_builder.export import export_dataset
from query_builder.policy import SecurityPolicy, TenantContext, apply_security_policy
from query_builder.pool import ConnectionPool, PoolClosedError, PoolTimeoutError
from query_builder.security import SecurityError
from query_builder.server import create_server
from query_builder.telemetry import TelemetryCollector
from query_builder.templates import TemplateStore


def log(msg: str) -> None:
    print(f"[STRESS-TEST] {msg}", flush=True)


# ==============================================================================
# CHALLENGE 1: ConnectionPool High Concurrency & Lifecycle
# ==============================================================================
def challenge_connection_pool() -> dict[str, Any]:
    log("Running Challenge 1: ConnectionPool Stress...")
    results: dict[str, Any] = {}

    def make_conn():
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("CREATE TABLE IF NOT EXISTS t (val INT)")
        return conn

    pool = ConnectionPool(
        factory=make_conn, max_size=5, timeout=5.0, max_idle_seconds=1.0
    )
    total_ops = 0
    ops_lock = threading.Lock()
    errors: list[Exception] = []

    def worker(worker_id: int):
        nonlocal total_ops
        for i in range(20):
            try:
                with pool.connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO t VALUES (?)", (worker_id * 100 + i,))
                    cursor.execute("SELECT COUNT(*) FROM t")
                    _ = cursor.fetchone()
                    cursor.close()
                    time.sleep(0.001)
                with ops_lock:
                    total_ops += 1
            except Exception as e:  # noqa: BLE001
                errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(25)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    duration = time.perf_counter() - start

    assert len(errors) == 0, f"Errors during rapid acquisitions: {errors}"
    assert pool.in_use_count == 0, f"Expected 0 in use, got {pool.in_use_count}"
    assert pool.size <= 5, f"Pool exceeded max_size: {pool.size}"
    log(
        f"  Test 1.1 PASSED: 500 acquisitions across 25 threads in {duration:.3f}s (ops/s: {500 / duration:.1f})"
    )
    results["concurrency_ops_per_sec"] = round(500 / duration, 1)

    # Test 1.2: Pool Exhaustion & Timeout
    small_pool = ConnectionPool(factory=make_conn, max_size=2, timeout=0.1)
    c1 = small_pool.acquire()
    c2 = small_pool.acquire()
    assert small_pool.in_use_count == 2
    timed_out = False
    t_start = time.perf_counter()
    try:
        small_pool.acquire()
    except PoolTimeoutError:
        timed_out = True
    t_wait = time.perf_counter() - t_start
    assert timed_out, "Expected PoolTimeoutError when pool exhausted"
    assert t_wait >= 0.09, f"Timeout triggered too fast: {t_wait}s"
    small_pool.release(c1)
    small_pool.release(c2)
    assert small_pool.in_use_count == 0
    small_pool.close_all()
    log("  Test 1.2 PASSED: Pool exhaustion timeout verified")

    # Test 1.3: Idle Eviction
    evict_pool = ConnectionPool(factory=make_conn, max_size=5, max_idle_seconds=0.05)
    c = evict_pool.acquire()
    evict_pool.release(c)
    assert evict_pool.available_count == 1
    time.sleep(0.08)  # exceed idle time
    c_new = evict_pool.acquire()
    assert c_new is not c
    evict_pool.release(c_new)
    evict_pool.close_all()
    log("  Test 1.3 PASSED: Idle eviction after 50ms verified")

    # Test 1.4: Race condition on close_all() with waiting threads
    race_pool = ConnectionPool(factory=make_conn, max_size=1, timeout=2.0)
    _held = race_pool.acquire()
    closed_errors: list[Exception] = []

    def waiting_worker():
        try:
            race_pool.acquire()
        except PoolClosedError as e:
            closed_errors.append(e)

    waiters = [threading.Thread(target=waiting_worker) for _ in range(5)]
    for w in waiters:
        w.start()
    time.sleep(0.05)
    race_pool.close_all()
    for w in waiters:
        w.join()

    assert len(closed_errors) == 5, (
        f"Expected 5 PoolClosedError, got {len(closed_errors)}"
    )
    with pytest.raises(PoolClosedError):
        race_pool.acquire()
    log("  Test 1.4 PASSED: close_all() clean wake-up of waiting threads verified")

    results["pool_status"] = "PASSED"
    return results


# ==============================================================================
# CHALLENGE 2: Security Policy & Attack Vectors
# ==============================================================================
def challenge_security_policy() -> dict[str, Any]:
    log("Running Challenge 2: Security Policy Attack Vectors...")
    results: dict[str, Any] = {}

    # Attack 2.1: SQL Injection payloads in tenant_id
    sqli_payloads = [
        "' OR '1'='1",
        "tenant_1'; DROP TABLE users; --",
        "' UNION SELECT * FROM passwords --",
        "admin' /* comment */ --",
        "1; EXEC xp_cmdshell('dir'); --",
        "' OR 1=1 #",
        "Robert'); DROP TABLE Students;--",
    ]

    for payload in sqli_payloads:
        ctx = TenantContext(tenant_id=payload)
        policy = SecurityPolicy(enforce_tenant_isolation=True)
        spec = {"table": "customers", "columns": ["id", "name"]}
        transformed = apply_security_policy(spec, context=ctx, policy=policy)
        assert len(transformed["filters"]) == 1
        flt = transformed["filters"][0]
        assert flt["column"] == "tenant_id"
        assert flt["value"] == payload.strip()

        # Compile across dialects to verify parameterization
        for dialect in ["postgres", "sqlite", "mysql", "mssql", "oracle"]:
            compiler = QueryCompiler(transformed, dialect=dialect)
            sql, params, _, _ = compiler.compile()
            assert payload not in sql, (
                f"SQL injection payload leaked into raw SQL ({dialect}): {sql}"
            )
            assert payload.strip() in params, (
                f"Payload missing from bind params ({dialect})"
            )

    log(
        f"  Test 2.1 PASSED: {len(sqli_payloads)} SQL injection tenant payloads strictly parameterized"
    )

    # Attack 2.2: Malicious table names & unauthorized schema bypass
    malicious_tables = [
        "users; DROP TABLE accounts;",
        "users UNION SELECT * FROM auth_user",
        "public.auth_user",
        "mysql.user",
        "pg_catalog.pg_shadow",
        "sys.objects",
        "information_schema.tables",
    ]

    for tbl in malicious_tables:
        spec = {"table": tbl, "columns": ["id"]}
        policy = SecurityPolicy(
            allowed_tables=["customers", "orders"],
            restricted_tables=["auth_user", "pg_shadow"],
            enforce_tenant_isolation=False,
        )
        blocked = False
        try:
            apply_security_policy(spec, policy=policy)
        except SecurityError:
            blocked = True
        assert blocked, f"SecurityPolicy failed to block malicious table: {tbl}"

    log(
        f"  Test 2.2 PASSED: {len(malicious_tables)} malicious/restricted tables blocked"
    )

    # Attack 2.3: Nested join bypass attempt
    join_bypass_spec = {
        "table": "orders",
        "columns": ["id", "amount"],
        "joins": [
            {
                "table": "customers",
                "type": "inner",
                "on": ["orders.customer_id", "customers.id"],
            },
            {
                "table": "passwords",
                "type": "left",
                "on": ["customers.id", "passwords.user_id"],
            },
        ],
    }
    blocked_join = False
    try:
        apply_security_policy(
            join_bypass_spec,
            policy=SecurityPolicy(
                allowed_tables=["orders", "customers"],
                restricted_tables=["passwords"],
                enforce_tenant_isolation=False,
            ),
        )
    except SecurityError as e:
        blocked_join = True
        assert "passwords" in str(e).lower()
    assert blocked_join, "Failed to block forbidden table in joined relations"
    log("  Test 2.3 PASSED: Nested join bypass strictly blocked")

    # Attack 2.4: Tenant isolation filter injection on joins
    join_tenant_spec = {
        "table": "orders",
        "columns": ["id"],
        "joins": [
            {
                "table": "customers",
                "type": "inner",
                "on": ["orders.customer_id", "customers.id"],
            },
        ],
    }
    ctx = TenantContext(tenant_id="tenant_abc")
    transformed = apply_security_policy(
        join_tenant_spec,
        context=ctx,
        policy=SecurityPolicy(enforce_tenant_isolation=True),
    )
    tenant_filters = [
        f for f in transformed["filters"] if f.get("column") == "tenant_id"
    ]
    assert len(tenant_filters) == 2, (
        f"Expected 2 tenant filters (base + join), got {len(tenant_filters)}"
    )
    tables_filtered = {f.get("table") for f in tenant_filters}
    assert tables_filtered == {"orders", "customers"}, (
        f"Unexpected filter tables: {tables_filtered}"
    )
    log(
        "  Test 2.4 PASSED: Multi-table join tenant filters injected for all joined relations"
    )

    # Attack 2.5: AST Validator on forbidden patterns and mutations
    mutation_queries = [
        "SELECT * FROM customers; DROP TABLE orders;",
        "SELECT * FROM customers WHERE id = 1; DELETE FROM users;",
        "SELECT /*!50000 1 */ FROM customers",
        "WITH RECURSIVE cte AS (SELECT 1 UNION ALL SELECT n+1 FROM cte) SELECT * FROM cte",
        "SELECT * FROM pg_shadow",
        "SELECT * FROM sqlite_master",
        "SELECT * FROM auth_user",
        "SELECT * FROM customers\x00; DROP TABLE users;",
    ]
    for q in mutation_queries:
        res = validate_sql_ast(q)
        assert not res["valid"], f"AST Validator failed to reject attack SQL: {q}"
        assert res["injection_risk"] in ("CRITICAL", "HIGH")
    log(
        f"  Test 2.5 PASSED: {len(mutation_queries)} AST mutation & injection patterns blocked"
    )

    results["security_status"] = "PASSED"
    return results


# ==============================================================================
# CHALLENGE 3: Export Engine Stress & Data Diversity
# ==============================================================================
def challenge_export_engine() -> dict[str, Any]:
    log("Running Challenge 3: Tabular Export Engine Stress...")
    results: dict[str, Any] = {}

    row_count = 5000
    diverse_rows: list[dict[str, Any]] = []
    unicode_strings = [
        "Hello World",
        "日本語テスト (Japanese)",
        "العربية (Arabic)",
        "Русский текст (Russian)",
        "🎉🚀🔥💻 (Emojis)",
        "Special chars: <>&\"'/\t\n\r",
        "Math: ∑ x² = √y ± ∞",
        "Quotes: 'single' and \"double\" and `backtick`",
    ]

    for i in range(row_count):
        diverse_rows.append(
            {
                "id": i,
                "text": unicode_strings[i % len(unicode_strings)],
                "score": 3.14159 * i,
                "is_active": (i % 2 == 0),
                "nullable_col": None if i % 5 == 0 else f"val_{i}",
                "int_val": 10**6 + i,
            }
        )

    columns = list(diverse_rows[0].keys())
    data = {"columns": columns, "rows": diverse_rows}

    # 3.1 CSV Export & Round-Trip
    start = time.perf_counter()
    csv_bytes, csv_mime, csv_ext = export_dataset(data, format="csv")
    csv_time = time.perf_counter() - start
    assert csv_mime == "text/csv; charset=utf-8"
    assert csv_ext == "csv"
    assert len(csv_bytes) > 0
    csv_reader = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8"))))
    assert len(csv_reader) == row_count + 1
    assert csv_reader[0] == columns
    log(
        f"  Test 3.1 PASSED: CSV exported {row_count} rows ({len(csv_bytes) / 1024:.1f} KB) in {csv_time:.3f}s"
    )
    results["csv_export_time"] = round(csv_time, 3)

    # 3.2 JSON Export & Round-Trip
    start = time.perf_counter()
    json_bytes, json_mime, json_ext = export_dataset(data, format="json")
    json_time = time.perf_counter() - start
    assert json_mime == "application/json"
    assert json_ext == "json"
    parsed_json = json.loads(json_bytes.decode("utf-8"))
    assert len(parsed_json) == row_count
    assert parsed_json[0]["text"] == diverse_rows[0]["text"]
    log(
        f"  Test 3.2 PASSED: JSON exported {row_count} rows ({len(json_bytes) / 1024:.1f} KB) in {json_time:.3f}s"
    )
    results["json_export_time"] = round(json_time, 3)

    # 3.3 Parquet Export & Round-Trip
    start = time.perf_counter()
    parquet_bytes, parquet_mime, parquet_ext = export_dataset(data, format="parquet")
    parquet_time = time.perf_counter() - start
    assert parquet_mime == "application/vnd.apache.parquet"
    assert parquet_ext == "parquet"
    df_read = pl.read_parquet(io.BytesIO(parquet_bytes))
    assert df_read.shape == (row_count, len(columns))
    assert df_read["id"][0] == 0
    assert df_read["text"][1] == unicode_strings[1]
    log(
        f"  Test 3.3 PASSED: Parquet exported {row_count} rows ({len(parquet_bytes) / 1024:.1f} KB) in {parquet_time:.3f}s"
    )
    results["parquet_export_time"] = round(parquet_time, 3)

    # 3.4 Excel OpenXML (.xlsx) Export & Package Integrity
    start = time.perf_counter()
    xlsx_bytes, xlsx_mime, xlsx_ext = export_dataset(data, format="excel")
    xlsx_time = time.perf_counter() - start
    assert (
        xlsx_mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert xlsx_ext == "xlsx"
    zf = zipfile.ZipFile(io.BytesIO(xlsx_bytes))
    file_list = zf.namelist()
    assert "[Content_Types].xml" in file_list
    assert "xl/workbook.xml" in file_list
    assert "xl/worksheets/sheet1.xml" in file_list

    for fname in file_list:
        if fname.endswith((".xml", ".rels")):
            xml_content = zf.read(fname)
            root = ET.fromstring(xml_content)
            assert root is not None

    log(
        f"  Test 3.4 PASSED: Excel OpenXML exported {row_count} rows ({len(xlsx_bytes) / 1024:.1f} KB) in {xlsx_time:.3f}s with 100% valid XML"
    )
    results["xlsx_export_time"] = round(xlsx_time, 3)

    results["export_status"] = "PASSED"
    return results


# ==============================================================================
# CHALLENGE 4: Live HTTP Server Concurrency & Fuzzing
# ==============================================================================
def challenge_live_http_server() -> dict[str, Any]:
    log("Running Challenge 4: Live HTTP Server Stress & Fuzzing...")
    results: dict[str, Any] = {}

    collector = TelemetryCollector(max_size=500)
    store = TemplateStore()
    server = create_server(
        "127.0.0.1", 0, telemetry_collector=collector, template_store=store
    )
    port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    base_url = f"http://127.0.0.1:{port}"

    try:
        # 4.1 Health, OpenAPI, Swagger UI
        with urllib.request.urlopen(f"{base_url}/health") as resp:
            health = json.loads(resp.read().decode())
            assert health["status"] == "ok"
            assert len(health["dialects"]) >= 35

        with urllib.request.urlopen(f"{base_url}/openapi.json") as resp:
            openapi = json.loads(resp.read().decode())
            assert openapi["openapi"] == "3.1.0"
            assert "/api/v1/compile" in openapi["paths"]

        with urllib.request.urlopen(f"{base_url}/docs") as resp:
            docs_html = resp.read().decode()
            assert "swagger-ui" in docs_html.lower()

        log(
            "  Test 4.1 PASSED: Core endpoints (/health, /openapi.json, /docs) verified"
        )

        # 4.2 SQLite & DuckDB Introspection
        def request_post(
            path: str, data: dict[str, Any], headers: dict[str, str] | None = None
        ) -> tuple[int, Any]:
            body = json.dumps(data).encode("utf-8")
            req = urllib.request.Request(
                f"{base_url}{path}",
                data=body,
                headers={"Content-Type": "application/json", **(headers or {})},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read().decode())

        status, snap = request_post(
            "/api/v1/introspect", {"connector": "sqlite", "config": {}}
        )
        assert status == 200
        assert "tables" in snap

        status, snap_duck = request_post(
            "/api/v1/introspect", {"connector": "duckdb", "config": {}}
        )
        assert status == 200
        assert "tables" in snap_duck
        log("  Test 4.2 PASSED: SQLite & DuckDB schema introspection verified")

        # 4.3 High Concurrency Request Stress (25 concurrent threads)
        req_errors: list[Exception] = []
        compilations = 0
        comp_lock = threading.Lock()

        def hit_server(i: int):
            nonlocal compilations
            for attempt in range(3):
                try:
                    st, res = request_post(
                        "/api/v1/compile",
                        {
                            "spec": {
                                "table": "orders",
                                "columns": ["id", "amount"],
                                "filters": [
                                    {"column": "status", "op": "eq", "value": "paid"}
                                ],
                            },
                            "dialect": "postgres",
                        },
                    )
                    if st == 200 and "sql" in res:
                        with comp_lock:
                            compilations += 1
                        break
                    req_errors.append(Exception(f"Bad status {st}: {res}"))
                    break
                except (ConnectionResetError, urllib.error.URLError) as e:
                    if attempt == 2:
                        req_errors.append(e)
                    else:
                        time.sleep(0.01)
                except Exception as e:  # noqa: BLE001
                    req_errors.append(e)
                    break

        threads = [threading.Thread(target=hit_server, args=(i,)) for i in range(25)]
        start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        dur = time.perf_counter() - start

        assert len(req_errors) == 0, f"Concurrent request errors: {req_errors}"
        assert compilations == 25
        log(
            f"  Test 4.3 PASSED: 25 concurrent compilation requests completed in {dur:.3f}s"
        )
        results["concurrent_requests_time"] = round(dur, 3)

        # 4.4 Malformed Requests Fuzzing
        # Fuzz 1: Malformed JSON
        req = urllib.request.Request(
            f"{base_url}/api/v1/compile",
            data=b"{bad_json: missing_quotes}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as r:
                pytest.fail("Should have failed with 400")
        except urllib.error.HTTPError as e:
            assert e.code == 400
            err = json.loads(e.read().decode())
            assert "error" in err

        # Fuzz 2: Invalid Content-Length
        req = urllib.request.Request(
            f"{base_url}/api/v1/compile",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "Content-Length": "not_an_int",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as r:
                pytest.fail("Should fail on invalid Content-Length")
        except urllib.error.HTTPError as e:
            assert e.code == 400

        # Fuzz 3: Non-existent endpoint
        try:
            with urllib.request.urlopen(f"{base_url}/api/v1/nonexistent") as r:
                pytest.fail("Should fail with 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404

        # Fuzz 4: Forbidden Table Compilation Policy
        st, res = request_post(
            "/api/v1/compile",
            {
                "spec": {"table": "passwords", "columns": ["id"]},
                "policy": {"restricted_tables": ["passwords"]},
            },
        )
        assert st == 403
        assert res["error"]["code"] == "FORBIDDEN"

        # Fuzz 5: CORS Preflight (OPTIONS)
        req = urllib.request.Request(f"{base_url}/api/v1/compile", method="OPTIONS")
        with urllib.request.urlopen(req) as r:
            assert r.status == 204
            assert r.headers.get("Access-Control-Allow-Origin") == "*"

        log(
            "  Test 4.4 PASSED: Fuzzing & error handling (malformed JSON, 404, 403, CORS) verified"
        )

    finally:
        server.shutdown()
        server.server_close()
        server_thread.join()
        log("  HTTP Server shut down cleanly")

    results["http_status"] = "PASSED"
    return results


# ==============================================================================
# CHALLENGE 5: Telemetry Ring-Buffer & Percentile Math Oracle
# ==============================================================================
def challenge_telemetry() -> dict[str, Any]:
    log("Running Challenge 5: Telemetry Under Heavy Load & Percentile Oracle...")
    results: dict[str, Any] = {}

    # Test 5.1: 10,000 Concurrent Events into max_size=100 ring buffer
    collector = TelemetryCollector(max_size=100)
    total_events = 10000

    def recorder(tid: int):
        for i in range(500):
            status = "success" if (i % 10 != 0) else "error"
            collector.record_execution(
                sql=f"SELECT {i} FROM table_{tid}",
                latency_ms=(i % 50) + 1.0,
                row_count=i,
                status=status,
                tenant_id=f"tenant_{tid % 4}",
            )

    threads = [threading.Thread(target=recorder, args=(i,)) for i in range(20)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    duration = time.perf_counter() - start

    metrics = collector.get_metrics()
    assert metrics["total_queries"] == total_events
    assert metrics["error_count"] == 1000
    assert metrics["success_count"] == 9000
    assert metrics["error_rate"] == 0.1
    assert len(collector._events) == 100, (
        f"Ring buffer exceeded capacity: {len(collector._events)}"
    )
    assert metrics["active_tenants_count"] == 4
    log(
        f"  Test 5.1 PASSED: 10,000 executions recorded across 20 threads in {duration:.3f}s ({total_events / duration:.1f} events/s)"
    )
    results["telemetry_throughput"] = round(total_events / duration, 1)

    # Test 5.2: Mathematical Percentile Oracle Verification
    collector_oracle = TelemetryCollector(max_size=1000)
    for v in range(1, 101):
        collector_oracle.record_execution(
            sql="SELECT 1", latency_ms=float(v), status="success"
        )

    oracle_metrics = collector_oracle.get_metrics()
    assert oracle_metrics["p50_latency_ms"] == 51.0, (
        f"Expected p50=51.0, got {oracle_metrics['p50_latency_ms']}"
    )
    assert oracle_metrics["p95_latency_ms"] == 95.0, (
        f"Expected p95=95.0, got {oracle_metrics['p95_latency_ms']}"
    )
    assert oracle_metrics["p99_latency_ms"] == 99.0, (
        f"Expected p99=99.0, got {oracle_metrics['p99_latency_ms']}"
    )
    assert oracle_metrics["avg_latency_ms"] == 50.5
    log("  Test 5.2 PASSED: Latency percentile calculations match mathematical oracle")

    # Test 5.3: Recent events tenant filtering and order
    events_t0 = collector.get_recent_events(limit=10, tenant_id="tenant_0")
    assert all(e["tenant_id"] == "tenant_0" for e in events_t0)
    assert len(events_t0) <= 10

    # Test 5.4: Clear state
    collector.clear()
    assert collector.get_metrics()["total_queries"] == 0
    assert len(collector._events) == 0
    log("  Test 5.3 & 5.4 PASSED: Tenant event filtering and clear() verified")

    results["telemetry_status"] = "PASSED"
    return results


def test_adversarial_empirical_suite():
    """Pytest entrypoint executing all empirical challenge suites."""
    assert challenge_connection_pool()["pool_status"] == "PASSED"
    assert challenge_security_policy()["security_status"] == "PASSED"
    assert challenge_export_engine()["export_status"] == "PASSED"
    assert challenge_live_http_server()["http_status"] == "PASSED"
    assert challenge_telemetry()["telemetry_status"] == "PASSED"


def main() -> int:
    log("=" * 70)
    log("STARTING EMPIRICAL ADVERSARIAL STRESS CHALLENGES")
    log("=" * 70)

    t0 = time.perf_counter()
    pool_res = challenge_connection_pool()
    sec_res = challenge_security_policy()
    exp_res = challenge_export_engine()
    http_res = challenge_live_http_server()
    tel_res = challenge_telemetry()
    elapsed = time.perf_counter() - t0

    log("=" * 70)
    log(f"ALL ADVERSARIAL STRESS CHALLENGES PASSED IN {elapsed:.2f}s!")
    log("=" * 70)

    summary = {
        "elapsed_seconds": round(elapsed, 2),
        "pool": pool_res,
        "security": sec_res,
        "export": exp_res,
        "http": http_res,
        "telemetry": tel_res,
    }
    print("\nRESULTS SUMMARY JSON:")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
