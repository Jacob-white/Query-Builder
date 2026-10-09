"""Golden snapshot of the HTTP server's observable behaviour.

Every route (including alias paths, wrong-method and unknown paths, and the
error branches of each handler) is exercised against a live ``ThreadingHTTPServer``
and the status code, selected headers and body are compared with
``tests/golden/server.json`` (captured from the pre-refactor ``do_POST`` chain).
The OpenAPI document is compared byte-for-byte, so it cannot drift from the
routes unnoticed.

Regenerate deliberately with ``python tests/test_golden_server.py --update``.
"""

from __future__ import annotations

import http.client
import json
import re
import sqlite3
import sys
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from query_builder.nlq import NlqService
from query_builder.pool import ConnectionPoolManager
from query_builder.server import create_server
from query_builder.telemetry import TelemetryCollector
from query_builder.templates import TemplateStore

GOLDEN = Path(__file__).parent / "golden" / "server.json"

_VOLATILE = re.compile(
    r'"(latency_ms|elapsed_ms|created_at|updated_at|timestamp|execution_id|'
    r"avg_latency_ms|p50_latency_ms|p95_latency_ms|p99_latency_ms|max_latency_ms|"
    r'min_latency_ms|total_latency_ms|last_used_at|uptime_seconds|duration_ms)": '
    r'("[^"]*"|[-0-9.eE+]+|null)'
)
_HEADERS = (
    "content-type",
    "content-disposition",
    "transfer-encoding",
    "cache-control",
    "access-control-allow-origin",
    "access-control-allow-methods",
    "access-control-allow-headers",
    "access-control-expose-headers",
)


def _norm(text: str, db_path: str) -> str:
    text = text.replace(db_path, "<DB>").replace(db_path.replace("\\", "\\\\"), "<DB>")
    text = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<UUID>", text
    )
    return _VOLATILE.sub(lambda m: f'"{m.group(1)}": <V>', text)


class _Client:
    def __init__(self, port: int, db_path: str) -> None:
        self.port = port
        self.db_path = db_path

    def call(
        self,
        method: str,
        path: str,
        body: Any = None,
        headers: dict[str, str] | None = None,
        raw: bool = False,
    ) -> dict[str, Any]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        hdrs = dict(headers or {})
        data: bytes | None = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            hdrs.setdefault("Content-Length", str(len(data)))
        conn.request(method, path, body=data, headers=hdrs)
        try:
            resp = conn.getresponse()
        except http.client.RemoteDisconnected:
            # Handler raised before replying (e.g. non-object JSON body).
            conn.close()
            return {"status": "disconnected", "headers": {}, "body": None}
        payload = resp.read()
        rec: dict[str, Any] = {
            "status": resp.status,
            "headers": {
                h: resp.getheader(h) for h in _HEADERS if resp.getheader(h) is not None
            },
        }
        if payload.startswith(b"PK"):  # xlsx (zip) bytes embed timestamps
            payload = b"<zip>"
        text = _norm(payload.decode("utf-8", "replace"), self.db_path)
        rec["body"] = text if raw else _maybe_json(text)
        conn.close()
        return rec


def _maybe_json(text: str) -> Any:
    # Volatile placeholders are not valid JSON, so quote them first.
    try:
        return json.loads(text.replace(": <V>", ': "<V>"'))
    except ValueError:
        return text


@pytest.fixture(scope="module")
def client() -> Iterator[_Client]:
    tmp = tempfile.mkdtemp()
    db = str(Path(tmp) / "golden.db")
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    c.execute("INSERT INTO users VALUES (1, 'Alice'), (2, 'Bob'), (3, 'Cy')")
    c.commit()
    c.close()
    server = create_server(
        host="127.0.0.1",
        port=0,
        telemetry_collector=TelemetryCollector(),
        template_store=TemplateStore(),
        connection_pool_manager=ConnectionPoolManager(),
        nlq_service=NlqService(),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield _Client(server.server_address[1], db)
    server.shutdown()
    server.server_close()


def _scenarios(c: _Client) -> dict[str, dict[str, Any]]:
    db = {"database": c.db_path}
    out: dict[str, dict[str, Any]] = {}

    def rec(name: str, *args: Any, **kwargs: Any) -> None:
        assert name not in out, name
        out[name] = c.call(*args, **kwargs)

    # -- GET routes ------------------------------------------------------
    rec("get_health", "GET", "/health")
    rec("get_health_query", "GET", "/health?x=1")
    rec("get_openapi", "GET", "/openapi.json", raw=True)
    rec("get_docs", "GET", "/docs", raw=True)
    rec("get_telemetry_empty", "GET", "/api/v1/telemetry")
    rec("get_templates_empty", "GET", "/api/v1/templates")
    rec("get_nlq_providers", "GET", "/api/v1/nlq/providers")
    rec("get_connections_empty", "GET", "/api/v1/connections")
    rec("get_unknown", "GET", "/nope")
    rec("get_post_only_route", "GET", "/api/v1/compile")
    rec("get_trailing_slash", "GET", "/health/")
    rec("options_any", "OPTIONS", "/api/v1/compile")
    rec("options_unknown", "OPTIONS", "/whatever")

    # -- POST body parsing ----------------------------------------------
    rec("post_bad_json", "POST", "/api/v1/compile", b"{not json")
    rec("post_bad_json_unknown_path", "POST", "/nope", b"{not json")
    rec("post_bad_utf8", "POST", "/api/v1/compile", b"\xff\xfe")
    rec(
        "post_bad_content_length",
        "POST",
        "/api/v1/compile",
        None,
        headers={"Content-Length": "abc"},
    )
    rec("post_no_body_compile", "POST", "/api/v1/compile")
    rec("post_unknown", "POST", "/nope", {})
    rec("post_get_only_route", "POST", "/health", {})
    rec("post_nonobject_json", "POST", "/api/v1/validate", b"[1,2]")
    rec("post_nonobject_json_unknown", "POST", "/nope", b"[1,2]")

    # -- introspect ------------------------------------------------------
    rec(
        "introspect_sqlite",
        "POST",
        "/api/v1/introspect",
        {"connector": "sqlite", "config": db},
    )
    rec("introspect_default_memory", "POST", "/api/v1/introspect", {})
    rec(
        "introspect_bad_connector",
        "POST",
        "/api/v1/introspect",
        {"connector": "nonexistent_db"},
    )
    rec("introspect_config_not_dict", "POST", "/api/v1/introspect", {"config": "x"})

    # -- compile ---------------------------------------------------------
    spec = {
        "table": "users",
        "columns": ["id", "name"],
        "filters": [{"column": "id", "op": "gt", "value": 1}],
    }
    rec("compile_ok", "POST", "/api/v1/compile", {"spec": spec})
    for d in ("mysql", "mssql", "oracle", "snowflake"):
        rec(f"compile_{d}", "POST", "/api/v1/compile", {"spec": spec, "dialect": d})
    rec(
        "compile_tenant_policy",
        "POST",
        "/api/v1/compile",
        {"spec": spec, "tenant_id": "t1", "policy": {"enforce_tenant_isolation": True}},
    )
    rec(
        "compile_tenant_only",
        "POST",
        "/api/v1/compile",
        {"spec": spec, "tenant_id": "t1"},
    )
    rec(
        "compile_forbidden",
        "POST",
        "/api/v1/compile",
        {"spec": {"table": "secrets"}, "policy": {"restricted_tables": ["secrets"]}},
    )
    rec(
        "compile_policy_bad_kwargs",
        "POST",
        "/api/v1/compile",
        {"spec": spec, "policy": {"zzz": 1}},
    )
    rec("compile_missing_spec", "POST", "/api/v1/compile", {})
    rec("compile_empty_spec", "POST", "/api/v1/compile", {"spec": {}})
    rec("compile_spec_not_dict", "POST", "/api/v1/compile", {"spec": "x"})
    rec(
        "compile_invalid_spec",
        "POST",
        "/api/v1/compile",
        {"spec": {"table": "bad table;"}},
    )
    rec(
        "compile_bad_dialect_falls_back",
        "POST",
        "/api/v1/compile",
        {"spec": spec, "dialect": "zzz"},
    )

    # -- validate --------------------------------------------------------
    rec("validate_ok", "POST", "/api/v1/validate", {"sql": "SELECT a FROM firms;"})
    rec("validate_mutation", "POST", "/api/v1/validate", {"sql": "DELETE FROM firms;"})
    rec(
        "validate_schemas",
        "POST",
        "/api/v1/validate",
        {"sql": "SELECT a FROM other.firms", "allowed_schemas": ["public"]},
    )
    rec(
        "validate_bad_schemas",
        "POST",
        "/api/v1/validate",
        {"sql": "SELECT 1", "allowed_schemas": 5},
    )
    rec("validate_missing", "POST", "/api/v1/validate", {})
    rec("validate_not_string", "POST", "/api/v1/validate", {"sql": 5})

    # -- execute (three paths) ------------------------------------------
    for p in ("/api/v1/execute", "/api/v1/query/execute", "/api/query"):
        tag = p.strip("/").replace("/", "_")
        rec(f"exec_{tag}_raw", "POST", p, {"sql": "SELECT 1 AS val"})
        rec(
            f"exec_{tag}_spec",
            "POST",
            p,
            {
                "spec": {"table": "users", "columns": ["id", "name"]},
                "connector": "sqlite",
                "config": db,
            },
        )
        rec(f"exec_{tag}_missing", "POST", p, {})
        rec(
            f"exec_{tag}_forbidden",
            "POST",
            p,
            {"spec": {"table": "t"}, "policy": {"restricted_tables": ["t"]}},
        )
        rec(
            f"exec_{tag}_error",
            "POST",
            p,
            {"sql": "SELECT * FROM definitely_missing_xyz"},
        )
    rec(
        "exec_query_alias_key",
        "POST",
        "/api/v1/execute",
        {
            "query": {"table": "users", "columns": ["id"]},
            "dialect": "sqlite",
            "config": db,
        },
    )
    rec(
        "exec_raw_params",
        "POST",
        "/api/v1/execute",
        {"sql": "SELECT ? AS v", "params": [7], "limit": 5, "offset": 2},
    )
    rec(
        "exec_spec_tenant",
        "POST",
        "/api/v1/execute",
        {"spec": {"table": "users", "columns": ["id"]}, "tenant_id": "t", "config": db},
    )
    rec(
        "exec_bad_connector",
        "POST",
        "/api/v1/execute",
        {"sql": "SELECT 1", "connector": "nonexistent_db"},
    )
    cache_body = {
        "sql": "SELECT 424242 AS cached_val",
        "use_cache": True,
        "cache_ttl": 60,
    }
    rec("exec_cache_miss", "POST", "/api/v1/execute", cache_body)
    rec("exec_cache_hit", "POST", "/api/v1/execute", cache_body)
    cache_spec = {
        "spec": {"table": "users", "columns": ["name"]},
        "config": db,
        "use_cache": True,
    }
    rec("exec_cache_spec_miss", "POST", "/api/v1/execute", cache_spec)
    rec("exec_cache_spec_hit", "POST", "/api/v1/execute", cache_spec)
    rec(
        "exec_unknown_connection_id",
        "POST",
        "/api/v1/execute",
        {"sql": "SELECT 5 AS five", "connection_id": "nope"},
    )

    # -- connections -----------------------------------------------------
    rec("conn_register_missing_id", "POST", "/api/v1/connections", {})
    rec(
        "conn_register_nonstring_id",
        "POST",
        "/api/v1/connections",
        {"connection_id": 5},
    )
    rec(
        "conn_register_bad_size",
        "POST",
        "/api/v1/connections",
        {"connection_id": "bad", "max_size": "x"},
    )
    rec(
        "conn_register",
        "POST",
        "/api/v1/connections",
        {
            "connection_id": "c1",
            "connector": "sqlite",
            "config": db,
            "metadata": {"password": "s3cret", "team": "x"},
            "max_size": 2,
        },
    )
    rec("conn_list", "GET", "/api/v1/connections")
    rec("conn_test_id", "POST", "/api/v1/connections/test", {"connection_id": "c1"})
    rec(
        "conn_test_unknown",
        "POST",
        "/api/v1/connections/test",
        {"connection_id": "zzz"},
    )
    rec(
        "conn_test_inline",
        "POST",
        "/api/v1/connections/test",
        {"connector": "sqlite", "config": db},
    )
    rec("conn_test_empty", "POST", "/api/v1/connections/test", {})
    rec(
        "exec_via_pool_sql",
        "POST",
        "/api/v1/execute",
        {"sql": "SELECT name FROM users ORDER BY id", "connection_id": "c1"},
    )
    rec(
        "exec_via_pool_spec",
        "POST",
        "/api/v1/execute",
        {
            "spec": {"table": "users", "columns": ["id"]},
            "connection_id": "c1",
            "limit": 2,
        },
    )
    rec(
        "exec_via_pool_error",
        "POST",
        "/api/v1/execute",
        {"sql": "SELECT * FROM missing_tbl", "connection_id": "c1"},
    )
    rec("conn_cancel_missing", "POST", "/api/v1/connections/cancel", {})
    rec(
        "conn_cancel_nonstring",
        "POST",
        "/api/v1/connections/cancel",
        {"execution_id": 3},
    )
    rec(
        "conn_cancel_unknown",
        "POST",
        "/api/v1/connections/cancel",
        {"execution_id": "e-1"},
    )
    rec("conn_delete_query", "DELETE", "/api/v1/connections?connection_id=c1")
    rec("conn_delete_again", "DELETE", "/api/v1/connections/c1")
    rec("conn_delete_missing_id", "DELETE", "/api/v1/connections")
    rec(
        "conn_register_default_connector",
        "POST",
        "/api/v1/connections",
        {"connection_id": "c2"},
    )
    rec("conn_delete_path", "DELETE", "/api/v1/connections/c2")

    # -- stream ----------------------------------------------------------
    for p in ("/api/v1/stream", "/api/query/stream"):
        tag = p.strip("/").replace("/", "_")
        rec(
            f"stream_{tag}_spec",
            "POST",
            p,
            {
                "spec": {"table": "users", "columns": ["id", "name"]},
                "config": db,
                "batch_size": 2,
            },
            raw=True,
        )
        rec(f"stream_{tag}_sql", "POST", p, {"sql": "SELECT 1 AS a"}, raw=True)
        rec(f"stream_{tag}_missing", "POST", p, {})
        rec(
            f"stream_{tag}_forbidden",
            "POST",
            p,
            {"spec": {"table": "t"}, "policy": {"restricted_tables": ["t"]}},
        )
        rec(f"stream_{tag}_error", "POST", p, {"sql": "SELECT * FROM missing_tbl"})
    rec(
        "stream_batch_zero",
        "POST",
        "/api/v1/stream",
        {"spec": {"table": "users", "columns": ["id"]}, "config": db, "batch_size": 0},
        raw=True,
    )
    rec(
        "stream_batch_bad",
        "POST",
        "/api/v1/stream",
        {"sql": "SELECT 1", "batch_size": "x"},
    )
    rec(
        "stream_tenant",
        "POST",
        "/api/v1/stream",
        {"spec": {"table": "users", "columns": ["id"]}, "config": db, "tenant_id": "t"},
        raw=True,
    )

    # -- explain ---------------------------------------------------------
    for p in ("/api/v1/explain", "/api/query/explain"):
        tag = p.strip("/").replace("/", "_")
        rec(
            f"explain_{tag}_spec",
            "POST",
            p,
            {"spec": {"table": "users", "columns": ["id"]}},
        )
        rec(f"explain_{tag}_missing", "POST", p, {})
        rec(
            f"explain_{tag}_raw",
            "POST",
            p,
            {
                "raw_explain": [
                    {"id": 0, "parent": 0, "notused": 0, "detail": "SCAN users"}
                ],
                "dialect": "sqlite",
            },
        )
    rec(
        "explain_raw_bad",
        "POST",
        "/api/v1/explain",
        {"raw_explain": 5, "dialect": "postgres"},
    )
    rec(
        "explain_sql_sqlite",
        "POST",
        "/api/v1/explain",
        {"sql": "SELECT * FROM users", "connector": "sqlite", "config": db},
    )
    rec(
        "explain_sql_fallback",
        "POST",
        "/api/v1/explain",
        {"sql": "SELECT 1", "connector": "nonexistent_db"},
    )
    rec("explain_spec_bad", "POST", "/api/v1/explain", {"spec": {"zzz": 1}})

    # -- export ----------------------------------------------------------
    rows = [{"id": 1, "name": "a,b"}, {"id": 2, "name": "c"}]
    for fmt in ("csv", "json", "jsonl", "tsv", "xlsx", "html", "bogus"):
        rec(
            f"export_{fmt}",
            "POST",
            "/api/v1/export",
            {"format": fmt, "rows": rows},
            raw=True,
        )
    rec("export_default_format", "POST", "/api/v1/export", {"rows": rows}, raw=True)
    rec(
        "export_spec",
        "POST",
        "/api/v1/export",
        {
            "format": "csv",
            "spec": {"table": "users", "columns": ["id", "name"]},
            "config": db,
        },
        raw=True,
    )
    rec(
        "export_spec_error",
        "POST",
        "/api/v1/export",
        {"spec": {"table": "users"}, "connector": "nonexistent_db"},
    )
    rec("export_no_data", "POST", "/api/v1/export", {"format": "csv"})
    for fmt in ("csv", "json", "jsonl", "bogus"):
        rec(
            f"export_stream_{fmt}",
            "POST",
            "/api/v1/export/stream",
            {"format": fmt, "rows": rows, "chunk_size": 1},
            raw=True,
        )
    rec(
        "export_stream_chunk_zero",
        "POST",
        "/api/v1/export/stream",
        {"rows": rows, "chunk_size": 0},
        raw=True,
    )
    rec(
        "export_stream_chunk_bad",
        "POST",
        "/api/v1/export/stream",
        {"rows": rows, "chunk_size": "x"},
    )
    rec(
        "export_stream_spec",
        "POST",
        "/api/v1/export/stream",
        {"spec": {"table": "users", "columns": ["id"]}, "config": db},
        raw=True,
    )
    rec(
        "export_stream_sql",
        "POST",
        "/api/v1/export/stream",
        {"sql": "SELECT id FROM users WHERE id > ?", "params": [1], "config": db},
        raw=True,
    )
    rec(
        "export_stream_sql_error",
        "POST",
        "/api/v1/export/stream",
        {"sql": "SELECT * FROM missing_tbl", "config": db},
    )
    rec("export_stream_nodata", "POST", "/api/v1/export/stream", {})

    # -- templates -------------------------------------------------------
    tmpl = {
        "id": "tmpl-1",
        "title": "Users",
        "spec": {"table": "users", "columns": ["id"]},
        "tenant_id": "t1",
        "category": "cat",
    }
    rec("tmpl_create", "POST", "/api/v1/templates", tmpl)
    rec("tmpl_create_no_spec", "POST", "/api/v1/templates", {"title": "x"})
    rec("tmpl_create_invalid", "POST", "/api/v1/templates", {})
    rec("tmpl_list", "GET", "/api/v1/templates")
    rec(
        "tmpl_list_filter",
        "GET",
        "/api/v1/templates?tenant_id=t1&category=cat&search=Use",
    )
    rec("tmpl_list_filter_none", "GET", "/api/v1/templates?tenant_id=zzz")
    rec("tmpl_delete_wrong_tenant", "DELETE", "/api/v1/templates/tmpl-1?tenant_id=zzz")
    rec("tmpl_delete", "DELETE", "/api/v1/templates/tmpl-1?tenant_id=t1")
    rec("tmpl_delete_again", "DELETE", "/api/v1/templates/tmpl-1")
    rec("tmpl_delete_nested", "DELETE", "/api/v1/templates/a/b")

    # -- nlq -------------------------------------------------------------
    rec(
        "nlq_translate_ok",
        "POST",
        "/api/v1/nlq/translate",
        {
            "prompt": "show all users",
            "schema": {"tables": {"users": {"columns": {"id": "int", "name": "text"}}}},
        },
    )
    rec("nlq_translate_missing", "POST", "/api/v1/nlq/translate", {})
    rec("nlq_translate_blank", "POST", "/api/v1/nlq/translate", {"prompt": "   "})
    rec("nlq_translate_nonstring", "POST", "/api/v1/nlq/translate", {"prompt": 5})
    rec(
        "nlq_translate_bad_provider",
        "POST",
        "/api/v1/nlq/translate",
        {"prompt": "x", "provider": "zzz"},
    )
    with mock.patch(
        "query_builder.nlq.service.NlqService.translate",
        side_effect=RuntimeError("boom"),
    ):
        rec("nlq_translate_internal", "POST", "/api/v1/nlq/translate", {"prompt": "x"})
    rec(
        "nlq_explain_ok",
        "POST",
        "/api/v1/nlq/explain",
        {"query": {"table": "users", "columns": ["id"]}},
    )
    rec(
        "nlq_explain_spec_key",
        "POST",
        "/api/v1/nlq/explain",
        {"spec": {"table": "users"}, "dialect": "mysql"},
    )
    rec("nlq_explain_missing", "POST", "/api/v1/nlq/explain", {})
    rec("nlq_explain_not_dict", "POST", "/api/v1/nlq/explain", {"query": "x"})
    rec(
        "nlq_explain_bad_provider",
        "POST",
        "/api/v1/nlq/explain",
        {"query": {"table": "u"}, "provider": "zzz"},
    )

    # -- DELETE misc / telemetry after activity ---------------------------
    rec("delete_unknown", "DELETE", "/nope")
    rec("delete_health", "DELETE", "/health")
    rec("telemetry_after", "GET", "/api/v1/telemetry")
    return out


def test_server_matches_golden_snapshot(client: _Client) -> None:
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    actual = json.loads(json.dumps(_scenarios(client)))
    assert list(actual) == list(expected)
    for name, rec in expected.items():
        assert actual[name] == rec, name


def test_openapi_document_is_stable(client: _Client) -> None:
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))["get_openapi"]
    actual = client.call("GET", "/openapi.json", raw=True)
    assert actual == expected


if __name__ == "__main__":
    if "--update" in sys.argv:
        srv = create_server(
            host="127.0.0.1",
            port=0,
            telemetry_collector=TelemetryCollector(),
            template_store=TemplateStore(),
            connection_pool_manager=ConnectionPoolManager(),
            nlq_service=NlqService(),
        )
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        tmp = tempfile.mkdtemp()
        dbp = str(Path(tmp) / "golden.db")
        cn = sqlite3.connect(dbp)
        cn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        cn.execute("INSERT INTO users VALUES (1, 'Alice'), (2, 'Bob'), (3, 'Cy')")
        cn.commit()
        cn.close()
        data = _scenarios(_Client(srv.server_address[1], dbp))
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(data, indent=1), encoding="utf-8")
        print("wrote", GOLDEN, len(data), "scenarios")
        srv.shutdown()
