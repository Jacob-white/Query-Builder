"""Mock tests for newly added introspection helpers (Drill file workspaces and friends)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from query_builder.connectors import introspection as intro
from query_builder.connectors.base import IntrospectionError


class _ScriptedCursor:
    """A DB-API-ish cursor answering by SQL prefix: handler(sql) -> (description, rows)."""

    def __init__(self, handler: Callable[[str], tuple[Any, list[Any]]]) -> None:
        self.handler = handler
        self.sql: list[str] = []
        self.description: Any = None
        self._rows: list[Any] = []

    def execute(self, sql: str, params: Any = None) -> None:
        sql = " ".join(sql.split())
        self.sql.append(sql)
        self.description, self._rows = self.handler(sql)

    def fetchall(self) -> list[Any]:
        return self._rows


def test_drill_qualified_quotes_every_part() -> None:
    assert intro._drill_qualified("dfs.tmp", "t") == "`dfs`.`tmp`.`t`"
    assert intro._drill_qualified("", "a`b") == "`a``b`"
    assert intro._drill_qualified("dfs..tmp", "x") == "`dfs`.`tmp`.`x`"


def test_drill_file_tables_filters_hidden_and_non_data_files() -> None:
    def handler(sql: str) -> tuple[Any, list[Any]]:
        assert sql == "SHOW FILES IN `dfs`.`data`"
        return (
            [("name",), ("isDirectory",)],
            [
                ["people.parquet", "false"],
                ["_SUCCESS", "false"],
                [".hidden.csv", "false"],
                ["notes.txt", "false"],
                ["events", "true"],
                ["logs.JSON", "false"],
                ["a.csvh", "1"],
                ["b.json", "false"],
            ],
        )

    names = intro._drill_file_tables(_ScriptedCursor(handler), "dfs.data")
    assert names == ["a.csvh", "b.json", "events", "people.parquet"]
    # no description: first column is the name and nothing is a directory
    plain = _ScriptedCursor(lambda s: (None, [["x.csv"], ["dir"]]))
    assert intro._drill_file_tables(plain, "dfs.t") == ["x.csv"]
    # a failing SHOW FILES means "no file tables", not an error
    boom = _ScriptedCursor(
        lambda s: (_ for _ in ()).throw(RuntimeError("no workspace"))
    )
    assert intro._drill_file_tables(boom, "dfs.t") == []


def test_drill_probe_columns_reads_schema_from_limit_zero() -> None:
    cur = _ScriptedCursor(lambda s: ([("id", "BIGINT"), ("name",), ("x", None)], []))
    assert intro._drill_probe_columns(cur, "dfs.tmp", "p.parquet") == [
        ("id", "BIGINT"),
        ("name", "VARCHAR"),
        ("x", "VARCHAR"),
    ]
    assert cur.sql == ["SELECT * FROM `dfs`.`tmp`.`p.parquet` LIMIT 0"]
    bad = _ScriptedCursor(lambda s: (_ for _ in ()).throw(RuntimeError("x")))
    assert intro._drill_probe_columns(bad, "dfs.tmp", "t") == []


def test_introspect_drill_file_workspace_probes_each_file() -> None:
    def handler(sql: str) -> tuple[Any, list[Any]]:
        if "INFORMATION_SCHEMA.TABLES" in sql:
            return None, []  # file workspaces are not listed here
        if sql.startswith("SHOW FILES"):
            return [("name",), ("isDirectory",)], [["people.parquet", "false"]]
        if sql.startswith("SELECT * FROM"):
            return [
                ("id", "BIGINT"),
                ("password", "VARCHAR"),
                ("user_id", "INTEGER"),
            ], []
        raise AssertionError(sql)

    snap = intro.introspect_drill(_ScriptedCursor(handler), schema_name="dfs.tmp")
    cols = {c["name"]: c for c in snap["tables"]["people.parquet"]["columns"]}
    assert set(cols) == {"id", "user_id"}  # sensitive column filtered
    assert cols["id"]["is_primary"] is True and cols["id"]["data_type"] == "BIGINT"
    assert snap["tables"]["people.parquet"]["has_user_id"] is True
    unfiltered = intro.introspect_drill(
        _ScriptedCursor(handler), schema_name="dfs.tmp", filter_sensitive=False
    )
    assert "password" in {
        c["name"] for c in unfiltered["tables"]["people.parquet"]["columns"]
    }


def test_introspect_drill_catalog_and_describe_fallbacks() -> None:
    def handler(sql: str) -> tuple[Any, list[Any]]:
        if "INFORMATION_SCHEMA.TABLES" in sql:
            return None, [["t1"], [None], []]
        if "INFORMATION_SCHEMA.COLUMNS" in sql:
            raise RuntimeError("columns view unavailable")
        if sql.startswith("DESCRIBE `t1`"):
            return None, [["id", "INT"], ["secret_token", "VARCHAR"], ["n", "VARCHAR"]]
        raise AssertionError(sql)

    snap = intro.introspect_drill(_ScriptedCursor(handler))
    assert [c["name"] for c in snap["tables"]["t1"]["columns"]] == ["id", "n"]

    def show_tables(sql: str) -> tuple[Any, list[Any]]:
        if "INFORMATION_SCHEMA.TABLES" in sql:
            raise RuntimeError("no info schema")
        if sql == "SHOW TABLES;":
            return None, [["only"], [None]]
        if "INFORMATION_SCHEMA.COLUMNS" in sql:
            return None, [
                ["only", "a", "INT", "NO"],
                ["only", "b", "INT", "YES"],
                ["only", "api_key", "TEXT", "NO"],
            ]
        raise AssertionError(sql)

    snap2 = intro.introspect_drill(_ScriptedCursor(show_tables))
    cols = {c["name"]: c for c in snap2["tables"]["only"]["columns"]}
    assert cols["a"]["is_nullable"] is False and cols["b"]["is_nullable"] is True
    assert "api_key" not in cols  # sensitive columns are dropped by default


def test_introspect_drill_wraps_fatal_errors() -> None:
    def handler(sql: str) -> tuple[Any, list[Any]]:
        raise RuntimeError("cluster down")

    with pytest.raises(IntrospectionError, match="cluster down"):
        intro.introspect_drill(_ScriptedCursor(handler))


def test_arango_json_type_names() -> None:
    from datetime import datetime

    f = intro._arango_json_type
    assert f(True) == "boolean" and f(3) == "number" and f(2.5) == "number"
    assert f("s") == "string" and f([1]) == "array" and f({"a": 1}) == "object"
    assert f(None) == "null" and f(b"x") == "bytes" and f(bytearray(b"x")) == "bytes"
    assert f(datetime(2024, 1, 1)) == "timestamp"
    assert f(object()) == "object"


def test_arango_sample_fields_from_cursor_and_collection() -> None:
    cur = _ScriptedCursor(lambda s: ([("a",), ("b",)], [[1, None]]))
    assert intro._arango_sample_fields(cur, "c`x") == {"a": "number", "b": "null"}
    assert cur.sql == ["RETURN MERGE(FOR d IN `cx` LIMIT 100 RETURN d)"]
    coll = type(
        "Db",
        (),
        {
            "collection": lambda self, name: type(
                "C", (), {"all": lambda s, limit: [{"a": None}, {"a": "x"}, "junk"]}
            )()
        },
    )()
    assert intro._arango_sample_fields(coll, "c") == {"a": "string"}
    broken = _ScriptedCursor(lambda s: (_ for _ in ()).throw(RuntimeError("aql")))
    assert intro._arango_sample_fields(broken, "c") == {}
    assert intro._arango_sample_fields(object(), "c") == {}


def test_cosmos_snapshot_merges_sampled_types() -> None:
    snap = intro.cosmos_snapshot(
        {
            "c": [
                {"id": "1", "a": None, "_rid": "x", "user_id": "u"},
                "not a doc",
                {"a": 5, "b": [1]},
            ],
            "empty": [],
        },
        True,
    )
    cols = {c["name"]: c["data_type"] for c in snap["tables"]["c"]["columns"]}
    assert cols["a"] == "number" and cols["b"] == "array" and "_rid" not in cols
    assert snap["tables"]["c"]["has_user_id"] is True
    assert [c["name"] for c in snap["tables"]["empty"]["columns"]] == ["id"]


def test_redis_ft_info_parsing_resp2_and_resp3() -> None:
    assert intro._redis_text(b"abc") == "abc" and intro._redis_text(5) == "5"
    resp2 = [
        b"index_name",
        b"idx",
        b"attributes",
        [
            [b"identifier", b"title", b"attribute", b"title", b"type", b"TEXT"],
            [b"identifier", b"$.n", b"type", b"NUMERIC"],
            [b"type", b"TAG"],  # no name: skipped
            "scalar",  # neither mapping nor list: skipped
        ],
    ]
    cols = intro.parse_ft_info(resp2)
    assert [(c["name"], c["data_type"]) for c in cols] == [
        ("title", "text"),
        ("$.n", "numeric"),
    ]
    resp3 = {
        b"attributes": [
            {b"identifier": b"price", b"type": b"NUMERIC"},
            {b"attribute": b"t"},
        ]
    }
    assert [(c["name"], c["data_type"]) for c in intro.parse_ft_info(resp3)] == [
        ("price", "numeric"),
        ("t", "text"),
    ]
    assert intro.parse_ft_info({"other": 1}) == []
    assert intro.parse_ft_info(["attributes"]) == []
    assert intro.parse_ft_info(42) == []


def test_redis_index_columns_guards() -> None:
    assert intro._redis_index_columns(None, "i") == []
    assert intro._redis_index_columns(object(), "i") == []
    ok = type(
        "R", (), {"execute_command": lambda s, *a: ["attributes", [["attribute", "x"]]]}
    )()
    assert intro._redis_index_columns(ok, "i")[0]["name"] == "x"

    def boom(s: Any, *a: Any) -> None:
        raise RuntimeError("no module")

    assert (
        intro._redis_index_columns(type("R", (), {"execute_command": boom})(), "i")
        == []
    )


def test_chroma_sample_columns_variants() -> None:
    assert intro._chroma_sample_columns(None, "c") is None
    assert intro._chroma_sample_columns(object(), "c") is None

    def client(result: Any, raises: bool = False) -> Any:
        def get(**kw: Any) -> Any:
            if raises:
                raise RuntimeError("gone")
            return result

        coll = type("Coll", (), {"get": staticmethod(get)})()
        return type("Cl", (), {"get_collection": lambda s, n: coll})()

    assert intro._chroma_sample_columns(client({}, raises=True), "c") is None
    assert intro._chroma_sample_columns(client("notadict"), "c") is None
    assert intro._chroma_sample_columns(client({"metadatas": None}), "c") is None
    cols = intro._chroma_sample_columns(
        client(
            {"metadatas": [{"a": True, "b": 1, "c": 1.5, "d": "s"}, None, {"a": "x"}]}
        ),
        "c",
    )
    assert cols is not None
    kinds = {c["name"]: c["data_type"] for c in cols}
    assert kinds["id"] == "string" and kinds["document"] == "string"
    assert (kinds["a"], kinds["b"], kinds["c"], kinds["d"]) == (
        "boolean",
        "integer",
        "float",
        "string",
    )


def test_firestore_and_bigtable_schema_steps_skip_blank_rows() -> None:
    def run_fs(sql: str) -> Any:
        if sql == "collections":
            return [{}, {"name": "us`ers"}]
        assert sql == "SELECT * FROM `users` LIMIT 100"
        return [{"id": "d1", "name": "n", "user_id": "u"}]

    snap = intro.drive_steps(intro.firestore_schema_steps(), run_fs)
    assert set(snap["tables"]) == {"us`ers"}  # backtick only stripped from the SQL

    def run_bt(sql: str) -> Any:
        if sql == "list_tables":
            return [{}, {"name": "t`1"}]
        assert sql == "SELECT * FROM `t1` LIMIT 100"
        return [{"row_key": "k", "cf:q": b"v"}]

    snap2 = intro.drive_steps(intro.bigtable_schema_steps(), run_bt)
    cols = {c["name"]: c["data_type"] for c in snap2["tables"]["t`1"]["columns"]}
    assert cols == {"row_key": "bytes", "cf:q": "bytes"}
