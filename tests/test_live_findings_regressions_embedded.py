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
    assert any(
        f["table"] == "e" and f["foreign_table"] == "d" for f in schema["foreign_keys"]
    )


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
    GenericDBAPIConnector(
        connection=_sqlite_conn(), dialect="trino"
    ).introspect_schema()
    assert seen["placeholder"] == "?"


# --- GenericDBAPIConnector: a failed statement left a PG transaction aborted ----------
def test_generic_connector_rolls_back_after_a_failed_statement():
    class Cur:
        def execute(self, sql, params=None):
            raise RuntimeError("boom")

        def close(self):
            pass

    class Conn:
        rolled_back = 0

        def cursor(self):
            return Cur()

        def rollback(self):
            self.rolled_back += 1

    conn = Conn()
    c = GenericDBAPIConnector(connection=conn, dialect="postgres")
    with pytest.raises(RuntimeError), c.get_cursor() as cur:
        cur.execute("SELECT 1")
    assert conn.rolled_back == 1


# --- Snowflake: key columns only exist behind SHOW; LIKE needs a declared escape --------
def test_snowflake_like_escape_is_declared():
    sql, params = _compile("snowflake", "contains", "50%_")
    assert "ESCAPE '!'" in sql
    assert params[0] == "%50!%!_%"


def test_snowflake_introspection_reads_keys_from_show_commands():
    from query_builder.connectors.snowflake import SnowflakeConnector

    class Cur:
        def __init__(self):
            self.description = None
            self.rows = []

        def execute(self, sql, params=None):
            if sql.startswith("SHOW PRIMARY KEYS"):
                self.description = [("table_name",), ("column_name",)]
                self.rows = [("T1", "k")]
            elif sql.startswith("SHOW IMPORTED KEYS"):
                self.description = [
                    ("pk_table_name",),
                    ("pk_column_name",),
                    ("pk_column_name",),  # duplicate header seen from the emulator
                    ("fk_table_name",),
                    ("fk_column_name",),
                ]
                self.rows = [("T0", "id", "ignored", "T1", "t0_id")]
            else:
                raise RuntimeError("information_schema is not consulted here")

        def fetchall(self):
            return self.rows

        def close(self):
            pass

    class Conn:
        def cursor(self):
            return Cur()

    snap = {
        "tables": {
            "t1": {
                "columns": [
                    {"name": "k", "is_primary": False},
                    {"name": "id", "is_primary": True},
                ]
            },
            "t0": {"columns": [{"name": "id", "is_primary": True}]},
        },
        "foreign_keys": [],
        "relationships": [],
    }
    c = SnowflakeConnector(connection=Conn())
    c._overlay_keys(Cur(), snap)
    cols = {c_["name"]: c_["is_primary"] for c_ in snap["tables"]["t1"]["columns"]}
    assert cols == {
        "k": True,
        "id": False,
    }  # the `id` guess is replaced by the real key
    assert snap["foreign_keys"] == [
        {
            "table": "t1",
            "column": "t0_id",
            "foreign_table": "t0",
            "foreign_column": "id",
        }
    ]


def test_snowflake_show_failure_keeps_the_ansi_result():
    from query_builder.connectors.snowflake import SnowflakeConnector

    class Cur:
        def execute(self, sql, params=None):
            raise RuntimeError("no privilege")

    snap = {"tables": {"t": {"columns": [{"name": "id", "is_primary": True}]}}}
    SnowflakeConnector(connection=object())._overlay_keys(Cur(), snap)
    assert snap["tables"]["t"]["columns"][0]["is_primary"] is True


# --- H2 / Derby: the driver was chosen by what is installed, not by the configuration ----
@pytest.mark.parametrize("mod", ["h2", "derby"])
def test_jdbc_config_selects_jaydebeapi_not_the_network_driver(mod):
    import importlib

    fits = importlib.import_module(f"query_builder.connectors.{mod}")._driver_fits
    assert fits("jaydebeapi", {"jclassname": "x", "url": "jdbc:foo:bar"})
    assert fits("jaydebeapi", {"url": "jdbc:foo:bar"})
    assert not fits("psycopg", {"url": "jdbc:foo:bar"})
    assert not fits("drda", {"jclassname": "x"})
    assert not fits("jaydebeapi", {"host": "h"})
    assert fits("jaydebeapi", {}) and fits("psycopg", {})
    assert fits("psycopg", {"host": "h"})


@pytest.mark.parametrize("mod", ["h2", "derby"])
def test_jdbc_connect_ignores_installed_network_driver(mod, monkeypatch):
    import importlib
    import sys
    import types

    module = importlib.import_module(f"query_builder.connectors.{mod}")
    jdbc = types.ModuleType("jaydebeapi")
    jdbc.connect = lambda **kw: ("jdbc", kw)
    other = types.ModuleType("psycopg")
    other.connect = lambda **kw: ("wrong", kw)
    for name, m in (
        ("jaydebeapi", jdbc),
        ("psycopg", other),
        ("psycopg2", other),
        ("drda", other),
    ):
        monkeypatch.setitem(sys.modules, name, m)
    cls = module.H2Connector if mod == "h2" else module.DerbyConnector
    conn = cls(jclassname="x", url="jdbc:a:b").connect()
    assert conn[0] == "jdbc"


@pytest.mark.parametrize("dialect", ["h2", "derby"])
def test_h2_and_derby_declare_their_like_escape(dialect):
    sql, params = _compile(dialect, "contains", "a%b")
    assert "ESCAPE '\\'" in sql
    assert params[0] == "%a\\%b%"


# --- chDB: `database` was stored but never applied; no timeout / read-only ----------------
def test_chdb_connect_selects_the_configured_database(monkeypatch):
    import sys
    import types

    from query_builder.connectors.chdb import ChDBConnector

    seen = []

    class Cur:
        def execute(self, sql, params=None):
            seen.append(sql)

        def close(self):
            pass

    class Conn:
        def cursor(self):
            return Cur()

    drv = types.ModuleType("chdb.dbapi")
    drv.connect = lambda **kw: Conn()
    monkeypatch.setitem(sys.modules, "chdb.dbapi", drv)
    c = ChDBConnector(database="qb_it", path="/tmp/x")
    c.connect()
    assert seen == ["USE `qb_it`", "SET readonly = 2"]  # then the read-only session
    with pytest.raises(Exception, match="Invalid chDB database"):
        ChDBConnector(database="a`b").connect()


def test_chdb_timeout_and_read_only_use_server_settings():
    from query_builder.connectors.chdb import ChDBConnector

    seen = []

    class Cur:
        def execute(self, sql, params=None):
            seen.append(sql)

        def close(self):
            pass

    class Conn:
        def cursor(self):
            return Cur()

    c = ChDBConnector(connection=Conn())
    c.apply_statement_timeout(Cur(), 2500)
    c.apply_read_only(Conn())
    assert seen == ["SET max_execution_time = 2", "SET readonly = 2"]


# --- LanceDB / ChromaDB: SQL was silently ignored (WHERE/ORDER BY/projection) -----------
def test_lancedb_adapter_applies_where_order_limit_and_projection():
    pa = pytest.importorskip("pyarrow")
    from unittest.mock import MagicMock

    from query_builder.connectors.lancedb import _LanceDBCursorAdapter

    data = pa.table({"name": ["b", "a", "c"], "age": [45, 30, 28]})
    tbl = MagicMock()
    tbl.search.return_value.where.return_value.limit.return_value.to_arrow.return_value = data
    conn = MagicMock(spec=["open_table"])
    conn.open_table.return_value = tbl
    cur = _LanceDBCursorAdapter(conn)
    cur.execute(
        "SELECT name FROM t WHERE age > ? ORDER BY age ASC LIMIT 2 OFFSET 1", [20]
    )
    assert cur.description == [("name",)]
    assert cur.fetchall() == [["a"], ["b"]]
    tbl.search.return_value.where.assert_called_with("age > 20", prefilter=True)


def test_chroma_adapter_translates_sql_to_collection_get():
    from unittest.mock import MagicMock

    from query_builder.connectors.chroma import (
        UnsupportedChromaQuery,
        _ChromaCursorAdapter,
    )

    col = MagicMock()
    col.get.return_value = {
        "ids": ["1", "2"],
        "documents": ["alice", "bob"],
        "metadatas": [{"age": 30}, {"age": 45}],
    }
    client = MagicMock(spec=["get_collection"])
    client.get_collection.return_value = col
    cur = _ChromaCursorAdapter(client)
    cur.execute(
        "SELECT id, age FROM people WHERE age >= 30 AND age < 50 ORDER BY age DESC LIMIT 1"
    )
    assert cur.fetchall() == [["2", 45]]
    kwargs = col.get.call_args.kwargs
    assert kwargs["where"] == {"$and": [{"age": {"$gte": 30}}, {"age": {"$lt": 50}}]}
    cur.execute("SELECT * FROM people WHERE id IN ('1', '2')")
    assert col.get.call_args.kwargs["ids"] == ["1", "2"]
    assert [d[0] for d in cur.description] == ["id", "document", "age"]
    for bad in (
        "SELECT count(*) FROM people",
        "SELECT a FROM people WHERE a LIKE 'x%'",
    ):
        with pytest.raises(UnsupportedChromaQuery):
            cur.execute(bad)


def test_chroma_introspection_reads_real_metadata_keys():
    from unittest.mock import MagicMock

    from query_builder.connectors.introspection import introspect_chroma

    col = MagicMock()
    col.get.return_value = {
        "metadatas": [{"name": "a", "age": 3, "ok": True, "x": 1.5}, None]
    }
    client = MagicMock(spec=["get_collection", "list_collections"])
    client.list_collections.return_value = [MagicMock(**{"name": "people"})]
    client.list_collections.return_value[0].name = "people"
    client.get_collection.return_value = col
    schema = introspect_chroma(client, filter_sensitive=False)
    kinds = {c["name"]: c["data_type"] for c in schema["tables"]["people"]["columns"]}
    assert kinds == {
        "id": "string",
        "document": "string",
        "name": "string",
        "age": "integer",
        "ok": "boolean",
        "x": "float",
    }
    assert schema["tables"]["people"]["has_user_id"] is False


def test_lancedb_vector_search_and_bad_vector():
    from unittest.mock import MagicMock

    from query_builder.connectors.lancedb import (
        UnsupportedLanceQuery,
        _inline_params,
        _LanceDBCursorAdapter,
    )

    pa = pytest.importorskip("pyarrow")
    tbl = MagicMock()
    tbl.search.return_value.limit.return_value.to_arrow.return_value = pa.table(
        {"id": [1], "_distance": [0.5]}
    )
    conn = MagicMock(spec=["open_table"])
    conn.open_table.return_value = tbl
    cur = _LanceDBCursorAdapter(conn)
    cur.execute(
        "SELECT * FROM t ORDER BY cosine_distance(vector, ?) LIMIT 3", [[0.1, 0.2]]
    )
    assert cur.fetchall() == [[1, 0.5]]
    tbl.search.assert_called_with([0.1, 0.2])
    cur.execute("SELECT * FROM t ORDER BY l2_distance(vector, ?)", ["[1, 2]"])
    assert cur.fetchall() == [[1, 0.5]]
    with pytest.raises(UnsupportedLanceQuery):
        cur.execute("SELECT * FROM t ORDER BY l2_distance(vector, ?)", ["nope"])
    assert (
        _inline_params(
            "a = ? AND b = %s AND c = ? AND d = ? AND e = '?'", ["x'y", None, True]
        )
        == "a = 'x''y' AND b = NULL AND c = TRUE AND d = ? AND e = '?'"
    )
    assert _inline_params("a = ? AND b = ?", [1, 2.5]) == "a = 1 AND b = 2.5"
