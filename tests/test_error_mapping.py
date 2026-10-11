"""Driver exceptions are mapped onto QueryExecutionError without breaking old handlers."""

import sqlite3

import pytest

from query_builder.connectors.base import (
    ConnectorError,
    QueryExecutionError,
    as_connector_error,
)
from query_builder.exceptions import SecurityError


def test_vendor_error_is_both_connector_and_vendor_error():
    original = sqlite3.OperationalError("no such table: t")
    mapped = as_connector_error(original)
    assert isinstance(mapped, QueryExecutionError)
    assert isinstance(mapped, ConnectorError)
    assert isinstance(mapped, sqlite3.OperationalError)  # old handlers keep working
    assert mapped.__cause__ is original
    assert "no such table" in str(mapped)


@pytest.mark.parametrize(
    "exc",
    [SecurityError("x"), ValueError("v"), TimeoutError("t"), QueryExecutionError("q")],
)
def test_our_own_and_validation_errors_pass_through(exc):
    assert as_connector_error(exc) is exc


def test_uncombinable_vendor_class_falls_back(monkeypatch):
    import query_builder.connectors.base as base

    def boom(vendor):
        raise TypeError("layout conflict")

    monkeypatch.setattr(base, "_compat_class", boom)
    fallback = base.as_connector_error(RuntimeError("r"))
    assert type(fallback) is QueryExecutionError


def test_vendor_str_that_needs_init_state_still_works():
    class Vendor(Exception):
        def __init__(self, message, nested):
            super().__init__(message)
            self.nested = nested

        def __str__(self):
            return f"{self.args[0]} (nested={self.nested})"

    original = Vendor("boom", nested="inner")
    mapped = as_connector_error(original)
    assert isinstance(mapped, QueryExecutionError)
    assert str(mapped)  # must not raise AttributeError
    assert mapped.__cause__ is original


def test_vendor_str_that_always_fails_falls_back():
    class Broken(Exception):
        def __str__(self):
            raise RuntimeError("cannot stringify")

    mapped = as_connector_error(Broken("x"))
    assert type(mapped) is QueryExecutionError
