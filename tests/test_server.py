"""
Tests for Native HTTP Microservice API.
========================================
Spawns ThreadingHTTPServer on an ephemeral port and tests OpenAPI 3.1, Swagger UI,
CORS, and REST APIs for compile, introspect, validate, execute, export, templates,
and telemetry.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from query_builder.export import MIME_TYPES
from query_builder.server import create_server


@pytest.fixture(scope="module")
def server_base_url():
    server = create_server(host="127.0.0.1", port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


def _request(
    url: str,
    method: str = "GET",
    body: dict | str | bytes | None = None,
    headers: dict | None = None,
) -> tuple[int, dict[str, str], bytes]:
    req_headers = headers or {}
    data: bytes | None = None

    if body is not None:
        if isinstance(body, dict):
            data = json.dumps(body).encode("utf-8")
            if "Content-Type" not in req_headers:
                req_headers["Content-Type"] = "application/json"
        elif isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = body

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, resp_headers, resp.read()
    except urllib.error.HTTPError as err:
        err_headers = {k.lower(): v for k, v in err.headers.items()}
        return err.code, err_headers, err.read()


def test_server_health_endpoint(server_base_url: str):
    status, headers, body = _request(f"{server_base_url}/health")
    assert status == 200
    assert "application/json" in headers.get("content-type", "")
    data = json.loads(body.decode("utf-8"))
    assert data["status"] == "ok"
    assert data["version"] == "1.0.0"
    assert isinstance(data["dialects"], list)
    assert "postgres" in data["dialects"]


def test_server_docs_endpoint(server_base_url: str):
    status, headers, body = _request(f"{server_base_url}/docs")
    assert status == 200
    assert "text/html" in headers.get("content-type", "")
    assert b"Swagger UI" in body
    assert b"/openapi.json" in body


def test_server_openapi_spec_endpoint(server_base_url: str):
    status, headers, body = _request(f"{server_base_url}/openapi.json")
    assert status == 200
    assert "application/json" in headers.get("content-type", "")
    spec = json.loads(body.decode("utf-8"))
    assert spec["openapi"] == "3.1.0"
    assert "/api/v1/compile" in spec["paths"]
    assert "/api/v1/execute" in spec["paths"]
    assert "/api/v1/export" in spec["paths"]


def test_server_cors_options_preflight(server_base_url: str):
    status, headers, _ = _request(f"{server_base_url}/api/v1/compile", method="OPTIONS")
    assert status == 204
    assert headers.get("access-control-allow-origin") == "*"
    assert "POST" in headers.get("access-control-allow-methods", "")


def test_server_introspect_sqlite(server_base_url: str, tmp_path: Path):
    db_file = tmp_path / "intro.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, sku TEXT)")
    conn.commit()
    conn.close()

    status, _, body = _request(
        f"{server_base_url}/api/v1/introspect",
        method="POST",
        body={"connector": "sqlite", "config": {"database": str(db_file)}},
    )
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert "tables" in res
    assert "products" in res["tables"]


def test_server_introspect_invalid_connector(server_base_url: str):
    status, _, body = _request(
        f"{server_base_url}/api/v1/introspect",
        method="POST",
        body={"connector": "nonexistent_db"},
    )
    assert status == 400
    res = json.loads(body.decode("utf-8"))
    assert res["error"]["code"] == "INTROSPECTION_ERROR"


def test_server_compile_endpoint(server_base_url: str):
    spec = {
        "table": "users",
        "columns": ["id", "email"],
        "filters": [{"column": "active", "op": "eq", "value": True}],
    }
    status, _, body = _request(
        f"{server_base_url}/api/v1/compile",
        method="POST",
        body={"spec": spec, "dialect": "postgres"},
    )
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert 'FROM "users" "t1"' in res["sql"]
    assert res["dialect"] == "postgres"
    assert "count_sql" in res


def test_server_compile_with_security_policy(server_base_url: str):
    spec = {"table": "orders", "columns": ["id", "amount"]}
    status, _, body = _request(
        f"{server_base_url}/api/v1/compile",
        method="POST",
        body={
            "spec": spec,
            "dialect": "postgres",
            "tenant_id": "tenant_xyz",
            "policy": {"enforce_tenant_isolation": True},
        },
    )
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert '"tenant_id" = %s' in res["sql"]
    assert "tenant_xyz" in res["params"]


def test_server_compile_forbidden_policy(server_base_url: str):
    spec = {"table": "secrets"}
    status, _, body = _request(
        f"{server_base_url}/api/v1/compile",
        method="POST",
        body={
            "spec": spec,
            "policy": {"restricted_tables": ["secrets"]},
        },
    )
    assert status == 403
    res = json.loads(body.decode("utf-8"))
    assert res["error"]["code"] == "FORBIDDEN"


def test_server_compile_invalid_spec(server_base_url: str):
    # Spec missing table
    status, _, _body = _request(
        f"{server_base_url}/api/v1/compile",
        method="POST",
        body={"spec": {}},
    )
    assert status == 400

    # Non-dictionary spec
    status2, _, _ = _request(
        f"{server_base_url}/api/v1/compile",
        method="POST",
        body={"spec": "not_a_dict"},
    )
    assert status2 == 400


def test_server_validate_safe_query(server_base_url: str):
    status, _, body = _request(
        f"{server_base_url}/api/v1/validate",
        method="POST",
        body={"sql": "SELECT legal_name FROM firms;"},
    )
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert res["valid"] is True
    assert res["statement_type"] == "SELECT"


def test_server_validate_mutation_query(server_base_url: str):
    status, _, body = _request(
        f"{server_base_url}/api/v1/validate",
        method="POST",
        body={"sql": "DELETE FROM firms;"},
    )
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert res["valid"] is False
    assert res["injection_risk"] == "CRITICAL"


def test_server_validate_missing_sql(server_base_url: str):
    status, _, _ = _request(
        f"{server_base_url}/api/v1/validate",
        method="POST",
        body={"sql": ""},
    )
    assert status == 400


def test_server_execute_sqlite_spec(server_base_url: str, tmp_path: Path):
    db_file = tmp_path / "exec.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE users (id INT, name TEXT)")
    conn.execute("INSERT INTO users VALUES (1, 'Alice'), (2, 'Bob')")
    conn.commit()
    conn.close()

    status, _, body = _request(
        f"{server_base_url}/api/v1/execute",
        method="POST",
        body={
            "spec": {"table": "users", "columns": ["id", "name"]},
            "connector": "sqlite",
            "config": {"database": str(db_file)},
        },
    )
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert res["count"] == 2
    assert len(res["rows"]) == 2
    assert res["rows"][0]["name"] == "Alice"


def test_server_execute_raw_sql(server_base_url: str):
    status, _, body = _request(
        f"{server_base_url}/api/v1/execute",
        method="POST",
        body={"sql": "SELECT 1 AS val"},
    )
    assert status == 200
    res = json.loads(body.decode("utf-8"))
    assert len(res["rows"]) == 1
    assert res["rows"][0]["val"] == 1


def test_server_execute_missing_body(server_base_url: str):
    status, _, body = _request(
        f"{server_base_url}/api/v1/execute",
        method="POST",
        body={},
    )
    assert status == 400
    res = json.loads(body.decode("utf-8"))
    assert res["error"]["code"] == "BAD_REQUEST"


def test_server_execute_forbidden_policy(server_base_url: str):
    status, _, body = _request(
        f"{server_base_url}/api/v1/execute",
        method="POST",
        body={
            "spec": {"table": "restricted_table"},
            "policy": {"restricted_tables": ["restricted_table"]},
        },
    )
    assert status == 403
    res = json.loads(body.decode("utf-8"))
    assert res["error"]["code"] == "FORBIDDEN"


def test_server_execute_error_handling(server_base_url: str):
    status, _, body = _request(
        f"{server_base_url}/api/v1/execute",
        method="POST",
        body={"sql": "SELECT * FROM definitely_nonexistent_table_xyz"},
    )
    assert status == 400
    res = json.loads(body.decode("utf-8"))
    assert res["error"]["code"] == "EXECUTION_ERROR"


def test_server_export_csv(server_base_url: str):
    rows = [{"id": 1, "name": "Item"}]
    status, headers, body = _request(
        f"{server_base_url}/api/v1/export",
        method="POST",
        body={"format": "csv", "rows": rows},
    )
    assert status == 200
    assert "text/csv" in headers.get("content-type", "")
    assert "attachment" in headers.get("content-disposition", "")
    assert "id,name\n1,Item\n" in body.decode("utf-8")


def test_server_export_json(server_base_url: str):
    rows = [{"id": 1}]
    status, headers, body = _request(
        f"{server_base_url}/api/v1/export",
        method="POST",
        body={"format": "json", "rows": rows},
    )
    assert status == 200
    assert "application/json" in headers.get("content-type", "")
    assert json.loads(body.decode("utf-8")) == rows


def test_server_export_excel(server_base_url: str):
    rows = [{"id": 1, "label": "test"}]
    status, headers, body = _request(
        f"{server_base_url}/api/v1/export",
        method="POST",
        body={"format": "excel", "rows": rows},
    )
    assert status == 200
    assert MIME_TYPES["excel"] in headers.get("content-type", "")
    assert len(body) > 100


def test_server_export_parquet(server_base_url: str):
    rows = [{"id": 1, "val": "abc"}]
    status, headers, body = _request(
        f"{server_base_url}/api/v1/export",
        method="POST",
        body={"format": "parquet", "rows": rows},
    )
    assert status == 200
    assert MIME_TYPES["parquet"] in headers.get("content-type", "")
    assert body.startswith(b"PAR1")


def test_server_export_with_spec(server_base_url: str, tmp_path: Path):
    db_file = tmp_path / "exp.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE t (id INT, v TEXT)")
    conn.execute("INSERT INTO t VALUES (1, 'val1')")
    conn.commit()
    conn.close()

    status, _headers, body = _request(
        f"{server_base_url}/api/v1/export",
        method="POST",
        body={
            "format": "csv",
            "spec": {"table": "t", "columns": ["id", "v"]},
            "connector": "sqlite",
            "config": {"database": str(db_file)},
        },
    )
    assert status == 200
    assert "val1" in body.decode("utf-8")


def test_server_export_unsupported_format(server_base_url: str):
    status, _, body = _request(
        f"{server_base_url}/api/v1/export",
        method="POST",
        body={"format": "invalid_format", "rows": []},
    )
    assert status == 400
    res = json.loads(body.decode("utf-8"))
    assert res["error"]["code"] == "EXPORT_ERROR"


def test_server_template_crud(server_base_url: str):
    # 1. Create template
    tmpl_data = {
        "title": "API Created Template",
        "spec": {"table": "accounts"},
        "category": "finance",
    }
    status, _, body = _request(
        f"{server_base_url}/api/v1/templates",
        method="POST",
        body=tmpl_data,
    )
    assert status == 201
    created = json.loads(body.decode("utf-8"))
    tmpl_id = created["id"]
    assert tmpl_id is not None
    assert created["title"] == "API Created Template"

    # 2. List templates
    status, _, body = _request(f"{server_base_url}/api/v1/templates?category=finance")
    assert status == 200
    items = json.loads(body.decode("utf-8"))
    assert any(i["id"] == tmpl_id for i in items)

    # 3. Delete template
    status, _, body = _request(
        f"{server_base_url}/api/v1/templates/{tmpl_id}",
        method="DELETE",
    )
    assert status == 200
    del_res = json.loads(body.decode("utf-8"))
    assert del_res["deleted"] is True


def test_server_template_create_validation_error(server_base_url: str):
    status, _, body = _request(
        f"{server_base_url}/api/v1/templates",
        method="POST",
        body={"title": ""},
    )
    assert status == 400
    res = json.loads(body.decode("utf-8"))
    assert res["error"]["code"] == "VALIDATION_ERROR"


def test_server_template_delete_not_found(server_base_url: str):
    status, _, body = _request(
        f"{server_base_url}/api/v1/templates/nonexistent_id",
        method="DELETE",
    )
    assert status == 404
    res = json.loads(body.decode("utf-8"))
    assert res["error"]["code"] == "NOT_FOUND"


def test_server_template_delete_cross_tenant_forbidden(server_base_url: str):
    # Create with tenant_id orgA
    status, _, body = _request(
        f"{server_base_url}/api/v1/templates",
        method="POST",
        body={
            "title": "Tenant Locked",
            "spec": {"table": "t"},
            "tenant_id": "orgA",
        },
    )
    tmpl_id = json.loads(body.decode("utf-8"))["id"]

    # Delete with tenant_id orgB
    status, _, body = _request(
        f"{server_base_url}/api/v1/templates/{tmpl_id}?tenant_id=orgB",
        method="DELETE",
    )
    assert status == 403
    res = json.loads(body.decode("utf-8"))
    assert res["error"]["code"] == "FORBIDDEN"


def test_server_telemetry_endpoint(server_base_url: str):
    status, _, body = _request(f"{server_base_url}/api/v1/telemetry")
    assert status == 200
    metrics = json.loads(body.decode("utf-8"))
    assert "total_queries" in metrics
    assert "p50_latency_ms" in metrics


def test_server_not_found_endpoint(server_base_url: str):
    status, _, body = _request(f"{server_base_url}/unknown_route")
    assert status == 404
    res = json.loads(body.decode("utf-8"))
    assert res["error"]["code"] == "NOT_FOUND"

    status_del, _, _ = _request(f"{server_base_url}/unknown_route", method="DELETE")
    assert status_del == 404


def test_server_bad_json_body(server_base_url: str):
    status, _, body = _request(
        f"{server_base_url}/api/v1/compile",
        method="POST",
        body="{invalid_json:",
        headers={"Content-Type": "application/json"},
    )
    assert status == 400
    res = json.loads(body.decode("utf-8"))
    assert res["error"]["code"] == "BAD_REQUEST"


def test_server_compile_compilation_error(server_base_url: str):
    status, _, body = _request(
        f"{server_base_url}/api/v1/compile",
        method="POST",
        body={
            "spec": {
                "table": "users",
                "filters": [{"column": "x", "op": "unknown_operator_op", "value": 1}],
            }
        },
    )
    assert status == 400
    res = json.loads(body.decode("utf-8"))
    assert res["error"]["code"] == "COMPILATION_ERROR"


def test_server_validate_exception(server_base_url: str):
    from unittest.mock import patch

    with patch(
        "query_builder.server.validate_sql_ast",
        side_effect=RuntimeError("Simulated validator crash"),
    ):
        status, _, body = _request(
            f"{server_base_url}/api/v1/validate",
            method="POST",
            body={"sql": "SELECT 1"},
        )
        assert status == 400
        res = json.loads(body.decode("utf-8"))
        assert res["error"]["code"] == "VALIDATION_ERROR"


def test_server_post_unknown_endpoint(server_base_url: str):
    status, _, body = _request(
        f"{server_base_url}/api/v1/unknown_action",
        method="POST",
        body={"test": 1},
    )
    assert status == 404
    res = json.loads(body.decode("utf-8"))
    assert res["error"]["code"] == "NOT_FOUND"


def test_server_export_empty_body(server_base_url: str):
    status, _, body = _request(
        f"{server_base_url}/api/v1/export",
        method="POST",
        body={"format": "csv"},
    )
    assert status == 400
    res = json.loads(body.decode("utf-8"))
    assert res["error"]["code"] == "EXPORT_ERROR"


def test_server_parse_json_no_content_length():
    from unittest.mock import MagicMock

    from query_builder.server import QueryBuilderHandler

    handler = MagicMock(spec=QueryBuilderHandler)
    handler.headers = {}
    assert QueryBuilderHandler.parse_json_body(handler) == {}


def test_server_content_length_headers(server_base_url: str):
    # Invalid integer Content-Length
    status, _, _body = _request(
        f"{server_base_url}/api/v1/compile",
        method="POST",
        body=b"{}",
        headers={"Content-Length": "not_an_int"},
    )
    assert status == 400

    # Content-Length 0 (empty body) -> missing spec
    status0, _, _body0 = _request(
        f"{server_base_url}/api/v1/compile",
        method="POST",
        body=b"",
        headers={"Content-Length": "0"},
    )
    assert status0 == 400


def test_server_send_bytes_response_without_filename():
    from io import BytesIO
    from unittest.mock import MagicMock

    from query_builder.server import QueryBuilderHandler

    handler = MagicMock(spec=QueryBuilderHandler)
    handler.wfile = BytesIO()
    QueryBuilderHandler.send_bytes_response(
        handler,
        content=b"raw_bytes",
        content_type="text/plain",
        filename=None,
        status=200,
    )
    handler.send_response.assert_called_once_with(200)
    handler.send_header.assert_any_call("Content-Type", "text/plain")
