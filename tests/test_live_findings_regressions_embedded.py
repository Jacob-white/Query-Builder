"""
Regression tests for defects found by running the embedded / in-process engines live
(tests/integration/engines_embedded.py). Each reproduces, without the engine, the behaviour
that failed against the real one.
"""

from __future__ import annotations

import sqlite3

import pytest

from query_builder.compiler import QueryCompiler
from query_builder.connectors.generic import GenericDBAPIConnector
from query_builder.dialects import get_dialect


def _compile(dialect: str, op: str, value: str) -> tuple[str, list]:
    spec = {
        "table": "t",
        "columns": ["id"],
        "filters": [{"column": "name", "op": op, "value": value}],
        "limit": 5,
    }
    sql, params, _, _ = QueryCompiler(spec=spec, dialect=get_dialect(dialect)).compile()
    return sql, params


# --- DataFusion: LIKE wildcards in user values were unescaped -------------------------
@pytest.mark.parametrize(
    ("op", "expected"),
    [
        ("contains", "%50\\%\\_x%"),
        ("starts_with", "50\\%\\_x%"),
        ("ends_with", "%50\\%\\_x"),
    ],
)
def test_datafusion_like_wildcards_are_escaped_and_declared(op, expected):
    sql, params = _compile("datafusion", op, "50%_x")
    assert "ESCAPE '\\'" in sql
    assert params[0] == expected


# --- Polars: LIKE has no ESCAPE at all -> regex match with an escaped literal ----------
@pytest.mark.parametrize(
    ("op", "expected"),
    [
        ("contains", "(?i)50%_x\\.\\(a\\)"),
        ("starts_with", "(?i)^50%_x\\.\\(a\\)"),
        ("ends_with", "(?i)50%_x\\.\\(a\\)$"),
    ],
)
def test_polars_substring_ops_use_an_escaped_regex_not_like(op, expected):
    sql, params = _compile("polars", op, "50%_x.(a)")
    assert " ~ ?" in sql
    assert "LIKE" not in sql.upper()
    assert params[0] == expected


def test_base_dialect_substring_param_unchanged():
    d = get_dialect("sqlite")
    assert d.substring_param("contains", "a%b") == "%a\\%b%"
    assert d.substring_param("starts", "a_b") == "a\\_b%"
    assert d.substring_param("ends", "ab") == "%ab"


# --- GenericDBAPIConnector: information_schema + %s broke embedded DB-API drivers ------
def _sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("CREATE TABLE d (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE e (id INTEGER PRIMARY KEY, d_id INTEGER REFERENCES d(id), x TEXT)"
    )
    return conn


def test_generic_connector_introspects_sqlite_connection():
    conn = GenericDBAPIConnector(connection=_sqlite_conn(), dialect="sqlite")
    schema = conn.introspect_schema(filter_sensitive=False)
    assert {"d", "e"} <= set(schema["tables"])
    assert any(f["table"] == "e" and f["foreign_table"] == "d" for f in schema["foreign_keys"])


def test_generic_connector_reports_engine_version():
    conn = GenericDBAPIConnector(connection=_sqlite_conn(), dialect="sqlite")
    info = conn.test_connection()
    assert info["engine_version"] == sqlite3.sqlite_version


def test_generic_connector_version_falls_back_to_driver_module():
    class Cur:
        def execute(self, sql, params=None):
            raise RuntimeError("no version()")

        def fetchone(self):  # pragma: no cover
            return None

        def close(self):
            pass

    class Conn:
        __module__ = "sqlite3.fake"

        def cursor(self):
            return Cur()

        def rollback(self):
            self.rolled_back = True

    c = GenericDBAPIConnector(connection=Conn(), dialect="postgres")
    version = c._probe_engine_version()
    assert version is not None
    assert c._connection.rolled_back is True


def test_generic_connector_uses_dialect_placeholder_for_information_schema(monkeypatch):
    seen = {}

    def fake(cursor, **kw):
        seen.update(kw)
        return {"tables": {}}

    monkeypatch.setattr(
        "query_builder.connectors.generic.introspect_information_schema", fake
    )
    GenericDBAPIConnector(connection=_sqlite_conn(), dialect="trino").introspect_schema()
    assert seen["placeholder"] == "?"
