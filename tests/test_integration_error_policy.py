"""Error-message policy of the HTTP integrations.

Library errors keep their client-facing message; unexpected exceptions are logged server-side
and answered with a fixed message that never echoes driver / infrastructure details.
"""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from query_builder.capabilities import DisabledFeatureError
from query_builder.exceptions import CompilationError, SecurityError, ValidationError
from query_builder.export import ExportError
from query_builder.integrations._errors import public_error
from query_builder.integrations.fastapi import create_query_builder_router

LEAKY = "FATAL driver detail: connect to /var/lib/secret/db.sock failed"


@pytest.mark.parametrize(
    "exc",
    [
        CompilationError("bad spec"),
        ValidationError("bad field"),
        SecurityError("table restricted"),
        DisabledFeatureError("joins disabled"),
        ExportError("unsupported format"),
    ],
)
def test_library_errors_keep_their_message(exc):
    assert public_error("Failed", exc) == f"Failed: {exc}"


@pytest.mark.parametrize("exc", [RuntimeError(LEAKY), OSError(LEAKY), KeyError(LEAKY)])
def test_unexpected_errors_are_not_echoed_but_are_logged(exc, caplog):
    with caplog.at_level(logging.ERROR, logger="query_builder.integrations"):
        message = public_error("Query execution error", exc)
    assert message == "Query execution error"
    assert LEAKY not in message
    # The detail is preserved for operators via the logged exception info.
    record = caplog.records[-1]
    assert record.exc_info is not None and record.exc_info[1] is exc


class ExplodingConnector:
    """Minimal connector whose every operation fails with a leaky, unexpected error."""

    dialect_name = "sqlite"

    def execute(self, *args, **kwargs):
        raise RuntimeError(LEAKY)

    def execute_raw(self, *args, **kwargs):
        raise RuntimeError(LEAKY)

    def introspect_schema(self, *args, **kwargs):
        raise RuntimeError(LEAKY)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(create_query_builder_router(connector=ExplodingConnector()))
    return TestClient(app, raise_server_exceptions=False)


def test_fastapi_execute_does_not_leak_unexpected_error_text(client):
    resp = client.post("/execute", json={"sql": "SELECT 1"})
    assert resp.status_code == 400
    assert LEAKY not in resp.text
    assert "Query execution error" in resp.text


def test_fastapi_schema_does_not_leak_unexpected_error_text(client):
    resp = client.get("/schema")
    assert resp.status_code == 500
    assert LEAKY not in resp.text
    assert "Schema introspection failed" in resp.text


def test_fastapi_policy_errors_still_explain_why_a_query_was_refused(client):
    resp = client.post("/execute", json={"sql": "DROP TABLE users"})
    assert resp.status_code == 403
    assert "DROP" in resp.text


def test_validator_parse_crash_does_not_leak_exception_text(caplog):
    from unittest import mock

    from query_builder.ast_validator import validate_sql_ast

    with (
        mock.patch("sqlparse.parse", side_effect=ValueError(LEAKY)),
        caplog.at_level(logging.DEBUG, logger="query_builder.ast_validator"),
    ):
        result = validate_sql_ast("SELECT 1")

    assert result["valid"] is False
    assert LEAKY not in repr(result)
    assert result["violations"] == ["Malformed SQL failed AST parsing."]
    # Operators can still diagnose it from the debug log.
    assert any(r.exc_info and r.exc_info[1] is not None for r in caplog.records)


def test_fastapi_validate_endpoint_does_not_leak_parser_crash(client):
    from unittest import mock

    with mock.patch("sqlparse.parse", side_effect=ValueError(LEAKY)):
        resp = client.post("/validate", json={"sql": "SELECT 1"})
    assert LEAKY not in resp.text
    assert resp.json()["valid"] is False
