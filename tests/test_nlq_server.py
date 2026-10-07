"""
Tests for server endpoints: /api/v1/nlq/providers, /api/v1/nlq/translate, and /api/v1/nlq/explain.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any
from unittest.mock import patch

import pytest

from query_builder.server import create_server


@pytest.fixture(scope="module")
def nlq_server_url():
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
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    req_headers = {"Content-Type": "application/json"}
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)

    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return exc.code, json.loads(raw)


def test_server_nlq_providers(nlq_server_url: str) -> None:
    status, data = _request(f"{nlq_server_url}/api/v1/nlq/providers")
    assert status == 200
    assert "providers" in data
    prov_names = [p["name"] for p in data["providers"]]
    assert "mock" in prov_names
    assert "gemini" in prov_names


def test_server_nlq_translate_success(nlq_server_url: str) -> None:
    payload = {
        "prompt": "Show all active users",
        "provider": "mock",
        "dialect": "postgres",
    }
    status, data = _request(
        f"{nlq_server_url}/api/v1/nlq/translate", method="POST", body=payload
    )
    assert status == 200
    assert data["spec"]["table"] == "users"
    assert data["confidence"] > 0.0
    assert "explanation" in data


def test_server_nlq_translate_missing_prompt(nlq_server_url: str) -> None:
    status, data = _request(
        f"{nlq_server_url}/api/v1/nlq/translate", method="POST", body={"prompt": "  "}
    )
    assert status == 400
    assert data["error"]["code"] == "BAD_REQUEST"


def test_server_nlq_translate_validation_error(nlq_server_url: str) -> None:
    # Patch mock provider to return empty table triggering NlqValidationError
    with patch(
        "query_builder.nlq.providers.MockNlqProvider.generate_ast",
        return_value=({"table": ""}, 10),
    ):
        status, data = _request(
            f"{nlq_server_url}/api/v1/nlq/translate",
            method="POST",
            body={"prompt": "test"},
        )
        assert status == 400
        assert data["error"]["code"] == "NLQ_ERROR"


def test_server_nlq_translate_internal_error(nlq_server_url: str) -> None:
    # Patch translate to raise unexpected runtime error
    with patch(
        "query_builder.nlq.service.NlqService.translate",
        side_effect=RuntimeError("unexpected explosion"),
    ):
        status, data = _request(
            f"{nlq_server_url}/api/v1/nlq/translate",
            method="POST",
            body={"prompt": "test"},
        )
        assert status == 500
        assert data["error"]["code"] == "INTERNAL_ERROR"


def test_server_nlq_explain_success(nlq_server_url: str) -> None:
    payload = {
        "spec": {"table": "customers", "limit": 20},
        "dialect": "duckdb",
        "provider": "mock",
    }
    status, data = _request(
        f"{nlq_server_url}/api/v1/nlq/explain", method="POST", body=payload
    )
    assert status == 200
    assert "summary" in data
    assert "explanation" in data
    assert len(data["steps"]) > 0


def test_server_nlq_explain_missing_query(nlq_server_url: str) -> None:
    status, data = _request(
        f"{nlq_server_url}/api/v1/nlq/explain", method="POST", body={}
    )
    assert status == 400
    assert data["error"]["code"] == "BAD_REQUEST"


def test_server_nlq_explain_error(nlq_server_url: str) -> None:
    with patch(
        "query_builder.nlq.service.NlqService.explain",
        side_effect=RuntimeError("explain failure"),
    ):
        payload = {"query": {"table": "orders"}}
        status, data = _request(
            f"{nlq_server_url}/api/v1/nlq/explain", method="POST", body=payload
        )
        assert status == 400
        assert data["error"]["code"] == "NLQ_ERROR"


def test_openapi_spec_includes_nlq_routes(nlq_server_url: str) -> None:
    status, data = _request(f"{nlq_server_url}/openapi.json")
    assert status == 200
    paths = data.get("paths", {})
    assert "/api/v1/nlq/translate" in paths
    assert "/api/v1/nlq/explain" in paths
    assert "/api/v1/nlq/providers" in paths
