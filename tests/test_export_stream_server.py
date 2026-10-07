"""
Integration Tests for Tabular Streaming Data Export HTTP Endpoint.
===================================================================
Tests /api/v1/export/stream with chunked transfer-encoding, content-disposition,
all formats (CSV, JSON, JSONL, Parquet, Arrow, Excel), spec-based export,
sql-based export, and error handling.
"""

from __future__ import annotations

import http.client
import io
import json
import sqlite3
import threading
import urllib.parse
from typing import Any

import polars as pl
import pytest

from query_builder.server import create_server, generate_openapi_spec


@pytest.fixture
def running_export_server(tmp_path):
    """Spins up a lightweight server instance on an ephemeral port with a test SQLite DB."""
    db_file = str(tmp_path / "export_test.db")
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE inventory (id INT, item TEXT, qty INT)")
    conn.execute(
        "INSERT INTO inventory VALUES (1, 'Apples', 50), (2, 'Oranges', 75), (3, 'Bananas', 120)"
    )
    conn.commit()
    conn.close()

    server = create_server("127.0.0.1", 0)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    try:
        yield base_url, db_file
    finally:
        server.shutdown()
        server.server_close()


def _raw_chunked_post(
    base_url: str,
    path: str,
    data: dict[str, Any] | str,
) -> tuple[int, dict[str, str], bytes]:
    """Helper to issue raw POST request and collect chunked response bytes."""
    parsed = urllib.parse.urlparse(base_url)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port)

    body = (
        json.dumps(data).encode("utf-8")
        if isinstance(data, dict)
        else data.encode("utf-8")
    )
    headers = {"Content-Type": "application/json"}
    conn.request("POST", path, body=body, headers=headers)
    resp = conn.getresponse()

    status = resp.status
    resp_headers = {k.lower(): v for k, v in resp.getheaders()}
    body_bytes = resp.read()
    conn.close()
    return status, resp_headers, body_bytes


def test_openapi_spec_includes_export_stream():
    spec = generate_openapi_spec()
    assert "/api/v1/export/stream" in spec["paths"]
    assert "post" in spec["paths"]["/api/v1/export/stream"]


def test_stream_export_csv_with_rows(running_export_server):
    base_url, _ = running_export_server
    payload = {
        "format": "csv",
        "chunk_size": 2,
        "rows": [
            {"id": 1, "name": "Alpha"},
            {"id": 2, "name": "Beta"},
            {"id": 3, "name": "Gamma"},
        ],
        "columns": ["id", "name"],
    }
    status, headers, body = _raw_chunked_post(
        base_url, "/api/v1/export/stream", payload
    )
    assert status == 200
    assert "text/csv" in headers.get("content-type", "")
    assert headers.get("transfer-encoding") == "chunked"
    assert 'attachment; filename="export.csv"' in headers.get("content-disposition", "")
    text = body.decode("utf-8")
    assert "id,name\n" in text
    assert "1,Alpha\n" in text
    assert "3,Gamma\n" in text


def test_stream_export_jsonl(running_export_server):
    base_url, _ = running_export_server
    payload = {
        "format": "jsonl",
        "rows": [{"val": 100}, {"val": 200}],
    }
    status, headers, body = _raw_chunked_post(
        base_url, "/api/v1/export/stream", payload
    )
    assert status == 200
    assert headers.get("content-type") == "application/x-ndjson"
    lines = [json.loads(line) for line in body.decode("utf-8").strip().split("\n")]
    assert len(lines) == 2
    assert lines[0] == {"val": 100}


def test_stream_export_json(running_export_server):
    base_url, _ = running_export_server
    payload = {
        "format": "json",
        "chunk_size": 1,
        "rows": [{"x": 1}, {"x": 2}],
    }
    status, headers, body = _raw_chunked_post(
        base_url, "/api/v1/export/stream", payload
    )
    assert status == 200
    assert headers.get("content-type") == "application/json"
    data = json.loads(body.decode("utf-8"))
    assert data == [{"x": 1}, {"x": 2}]


def test_stream_export_parquet(running_export_server):
    base_url, _ = running_export_server
    payload = {
        "format": "parquet",
        "rows": [{"col_a": "hello", "col_b": 42}],
    }
    status, headers, body = _raw_chunked_post(
        base_url, "/api/v1/export/stream", payload
    )
    assert status == 200
    assert headers.get("content-type") == "application/vnd.apache.parquet"
    assert 'filename="export.parquet"' in headers.get("content-disposition", "")
    df = pl.read_parquet(io.BytesIO(body))
    assert len(df) == 1
    assert df["col_a"][0] == "hello"


def test_stream_export_arrow(running_export_server):
    base_url, _ = running_export_server
    payload = {
        "format": "arrow",
        "rows": [{"metric": 9.99}],
    }
    status, headers, body = _raw_chunked_post(
        base_url, "/api/v1/export/stream", payload
    )
    assert status == 200
    assert headers.get("content-type") == "application/vnd.apache.arrow.stream"
    assert 'filename="export.arrow"' in headers.get("content-disposition", "")
    df = pl.read_ipc_stream(io.BytesIO(body))
    assert len(df) == 1
    assert df["metric"][0] == 9.99


def test_stream_export_excel(running_export_server):
    import zipfile

    base_url, _ = running_export_server
    payload = {
        "format": "excel",
        "rows": [{"sheet_item": "Row 1"}],
    }
    status, headers, body = _raw_chunked_post(
        base_url, "/api/v1/export/stream", payload
    )
    assert status == 200
    assert "spreadsheetml.sheet" in headers.get("content-type", "")
    assert 'filename="export.xlsx"' in headers.get("content-disposition", "")
    zf = zipfile.ZipFile(io.BytesIO(body))
    assert "xl/workbook.xml" in zf.namelist()


def test_stream_export_with_spec_execution(running_export_server):
    base_url, db_file = running_export_server
    payload = {
        "format": "csv",
        "connector": "sqlite",
        "config": {"database": db_file},
        "spec": {
            "table": "inventory",
            "columns": ["id", "item", "qty"],
            "joins": [],
            "filters": [],
            "filter_join": "AND",
            "order_by": [{"column": "qty", "direction": "DESC"}],
            "distinct": False,
            "limit": 10,
        },
    }
    status, headers, body = _raw_chunked_post(
        base_url, "/api/v1/export/stream", payload
    )
    assert status == 200
    text = body.decode("utf-8")
    assert "id,item,qty\n" in text
    assert "Bananas" in text


def test_stream_export_with_sql_execution(running_export_server):
    base_url, db_file = running_export_server
    payload = {
        "format": "jsonl",
        "connector": "sqlite",
        "config": {"database": db_file},
        "sql": "SELECT item, qty FROM inventory WHERE qty > ? ORDER BY qty ASC",
        "params": [60],
    }
    status, headers, body = _raw_chunked_post(
        base_url, "/api/v1/export/stream", payload
    )
    assert status == 200
    lines = [json.loads(line) for line in body.decode("utf-8").strip().split("\n")]
    assert len(lines) == 2
    assert lines[0] == {"item": "Oranges", "qty": 75}
    assert lines[1] == {"item": "Bananas", "qty": 120}


def test_stream_export_errors_and_edge_cases(running_export_server):
    base_url, _ = running_export_server

    # 1. Unsupported format
    status1, _, body1 = _raw_chunked_post(
        base_url, "/api/v1/export/stream", {"format": "invalid_format", "rows": []}
    )
    assert status1 == 400
    assert "Unsupported export format" in body1.decode("utf-8")

    # 2. Invalid JSON body
    status2, _, body2 = _raw_chunked_post(base_url, "/api/v1/export/stream", "NOT_JSON")
    assert status2 == 400
    assert "Invalid JSON" in body2.decode("utf-8")

    # 3. chunk_size <= 0 defaults to 1000
    status3, _, body3 = _raw_chunked_post(
        base_url,
        "/api/v1/export/stream",
        {"format": "csv", "chunk_size": 0, "rows": [{"a": 1}]},
    )
    assert status3 == 200
    assert "a\n1\n" in body3.decode("utf-8")

    # 4. Body without rows/spec/sql hits else: export_data = body
    status4, _, body4 = _raw_chunked_post(
        base_url,
        "/api/v1/export/stream",
        {"format": "csv"},
    )
    assert status4 == 400
    assert "must contain 'rows' key" in body4.decode("utf-8")
