"""Mock tests for the Elasticsearch SQL cursor and the MongoDB native introspection paths."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from query_builder.connectors import elasticsearch as es
from query_builder.connectors.base import (
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.mongodb import MongoDBAtlasSQLConnector

# ---------------------------------------------------------------- Elasticsearch


def _es_client(*pages: dict[str, Any]) -> MagicMock:
    client = MagicMock(spec=["sql"])
    client.sql.query.side_effect = list(pages)
    return client


def test_es_cursor_follows_pages_and_binds_params() -> None:
    client = _es_client(
        {"columns": [{"name": "a"}, {}], "rows": [[1, 2]], "cursor": "c1"},
        {"rows": [[3, 4]], "cursor": "c2"},
        {"rows": [[5, 6]]},
    )
    cur = es.ElasticsearchCursor(client)
    assert cur.execute("  SELECT a FROM t WHERE x = ?;  ", (9,)) is cur
    first = client.sql.query.call_args_list[0].kwargs
    assert first == {
        "query": "SELECT a FROM t WHERE x = ?",
        "format": "json",
        "params": [9],
    }
    assert client.sql.query.call_args_list[1].kwargs == {
        "cursor": "c1",
        "format": "json",
    }
    assert cur.description == [("a", None), ("", None)]
    assert cur.rowcount == 3
    assert cur.fetchone() == [1, 2]
    assert cur.fetchall() == [[3, 4], [5, 6]]
    assert cur.fetchone() is None and cur.fetchall() == []
    cur.close()
    assert cur.fetchall() == []


def test_es_cursor_no_params_and_page_cap_clears_cursor() -> None:
    client = MagicMock(spec=["sql"])
    client.sql.query.return_value = {"columns": [], "rows": [], "cursor": "again"}
    cur = es.ElasticsearchCursor(client)
    with patch.object(es, "_MAX_PAGES", 3):
        cur.execute("SELECT 1")
    assert "params" not in client.sql.query.call_args_list[0].kwargs
    assert client.sql.query.call_count == 4  # first + 3 followed pages
    client.sql.clear_cursor.assert_called_once_with(cursor="again")
    # a failing clear_cursor never breaks the query
    client.sql.clear_cursor.side_effect = RuntimeError("x")
    with patch.object(es, "_MAX_PAGES", 1):
        cur.execute("SELECT 1")
    assert cur.rowcount == 0


def test_es_connector_connect_paths() -> None:
    c = es.ElasticsearchConnector(endpoint="http://es:9200", http_auth=("u", "p"))
    assert c.config["url"] == "http://es:9200"
    fake_mod = MagicMock()
    with patch.dict(sys.modules, {"elasticsearch": fake_mod}):
        assert c.connect() is fake_mod.Elasticsearch.return_value
        fake_mod.Elasticsearch.assert_called_once_with(
            "http://es:9200", http_auth=("u", "p")
        )
        assert c.connect() is fake_mod.Elasticsearch.return_value  # cached
    with (
        patch.dict(sys.modules, {"elasticsearch": None}),
        pytest.raises(DriverNotInstalledError),
    ):
        es.ElasticsearchConnector().connect()
    boom = MagicMock()
    boom.Elasticsearch.side_effect = RuntimeError("down")
    with (
        patch.dict(sys.modules, {"elasticsearch": boom}),
        pytest.raises(ConnectionFailedError),
    ):
        es.ElasticsearchConnector().connect()


def test_es_get_cursor_wraps_sql_clients_only() -> None:
    client = MagicMock(spec=["sql"])
    conn = es.ElasticsearchConnector(connection=client)
    with conn.get_cursor() as cur:
        assert isinstance(cur, es.ElasticsearchCursor)
    dbapi = MagicMock()  # has cursor(): standard DB-API path
    conn2 = es.ElasticsearchConnector(connection=dbapi)
    with conn2.get_cursor() as cur2:
        assert cur2 is dbapi.cursor.return_value
    preset = MagicMock()
    with es.ElasticsearchConnector(cursor=preset).get_cursor() as cur3:
        assert cur3 is preset


def test_es_test_connection_version() -> None:
    client = MagicMock(spec=["sql", "info"])
    client.sql.query.return_value = {"columns": [{"name": "x"}], "rows": [[1]]}
    client.info.return_value = {"version": {"number": "8.13.0"}}
    conn = es.ElasticsearchConnector(connection=client)
    assert conn.test_connection()["engine_version"] == "Elasticsearch 8.13.0"
    client.info.return_value = {"version": {"number": 8}}
    assert conn.test_connection()["engine_version"] == "Elasticsearch SQL"
    client.info.side_effect = RuntimeError("no")
    assert conn.test_connection()["engine_version"] == "Elasticsearch SQL"
    bare = MagicMock(spec=["sql"])
    bare.sql.query.return_value = {"columns": [], "rows": []}
    assert es.ElasticsearchConnector(connection=bare).test_connection()[
        "engine_version"
    ] == ("Elasticsearch SQL")


def test_es_introspect_schema() -> None:
    client = _es_client(
        {
            "rows": [
                ["cluster", "logs", "TABLE", "INDEX"],
                ["cluster", ".kibana", "TABLE", "INDEX"],
                ["bare"],
            ]
        },
        {"rows": [["id", "KEYWORD", "keyword"], ["user_id", "LONG", "long"]]},
        {"rows": [["title", "TEXT", "text"]]},
    )
    snap = es.ElasticsearchConnector(connection=client).introspect_schema()
    assert set(snap["tables"]) == {"logs", "bare"}
    logs = snap["tables"]["logs"]
    assert logs["has_user_id"] is True
    assert [c["name"] for c in logs["columns"] if c["is_primary"]] == ["id"]
    assert client.sql.query.call_args_list[1].kwargs["query"] == 'DESCRIBE "logs"'
    failing = MagicMock(spec=["sql"])
    failing.sql.query.side_effect = RuntimeError("cluster down")
    with pytest.raises(IntrospectionError, match="cluster down"):
        es.ElasticsearchConnector(connection=failing).introspect_schema()


# ---------------------------------------------------------------------- MongoDB


class _Doc(dict):
    pass


def _native_db(collections: Any, docs: dict[str, list[dict[str, Any]]]) -> MagicMock:
    db = MagicMock()
    db.name = "app"
    db.list_collection_names.return_value = collections
    db.__getitem__.side_effect = lambda n: MagicMock(
        find=MagicMock(return_value=docs[n])
    )
    return db


def _mongo_conn(db: Any) -> MongoDBAtlasSQLConnector:
    raw = MagicMock()
    raw.database = db
    return MongoDBAtlasSQLConnector(database="app", connection=raw)


def test_mongo_connect_paths() -> None:
    fake = MagicMock()
    c = MongoDBAtlasSQLConnector(database="d", host="h")
    with patch.dict(sys.modules, {"pymongosql": fake}):
        assert c.connect() is fake.connect.return_value
        fake.connect.assert_called_once_with(database="d", host="h")
    with (
        patch.dict(sys.modules, {"pymongosql": None}),
        pytest.raises(DriverNotInstalledError),
    ):
        MongoDBAtlasSQLConnector().connect()
    boom = MagicMock()
    boom.connect.side_effect = RuntimeError("refused")
    with (
        patch.dict(sys.modules, {"pymongosql": boom}),
        pytest.raises(ConnectionFailedError),
    ):
        MongoDBAtlasSQLConnector().connect()


def test_mongo_native_db_detection() -> None:
    assert _mongo_conn(_native_db([], {}))._native_db() is not None
    assert _mongo_conn(object())._native_db() is None


def test_mongo_test_connection_pings_native_database() -> None:
    db = _native_db([], {})
    db.client.server_info.return_value = {"version": "7.0.5"}
    info = _mongo_conn(db).test_connection()
    db.command.assert_called_once_with("ping")
    assert info["engine_version"] == "MongoDB 7.0.5"
    assert info["status"] == "healthy" and info["database"] == "app"
    db.client.server_info.side_effect = RuntimeError("auth")
    assert _mongo_conn(db).test_connection()["engine_version"] == "MongoDB"


def test_mongo_test_connection_falls_back_to_generic_probe() -> None:
    raw = MagicMock()
    raw.database = None
    conn = MongoDBAtlasSQLConnector(database="app", connection=raw)
    info = conn.test_connection()
    assert info["engine_version"] == "MongoDB Atlas SQL" and info["database"] == "app"
    preset = MongoDBAtlasSQLConnector(cursor=MagicMock())
    assert preset.test_connection()["engine_version"] == "MongoDB Atlas SQL"


def test_mongo_introspect_native_samples_documents() -> None:
    docs = {
        "users": [{"_id": 1, "user_id": 5, "name": "a"}, {"_id": 2, "age": 3}],
        "orders": [],
    }
    db = _native_db(["users", "system.views", "orders"], docs)
    snap = _mongo_conn(db).introspect_schema()
    assert set(snap["tables"]) == {"users", "orders"}
    users = {c["name"]: c for c in snap["tables"]["users"]["columns"]}
    assert users["_id"]["is_primary"] is True and users["_id"]["is_nullable"] is False
    assert users["name"]["data_type"] == "str" and users["age"]["data_type"] == "int"
    assert snap["tables"]["users"]["has_user_id"] is True
    assert snap["tables"]["orders"]["has_user_id"] is False
    assert [c["name"] for c in snap["tables"]["orders"]["columns"]] == ["_id"]


def test_mongo_introspect_native_errors_and_fallbacks() -> None:
    db = _native_db(RuntimeError("not authorized"), {})
    db.list_collection_names.side_effect = RuntimeError("not authorized")
    with pytest.raises(IntrospectionError, match="not authorized"):
        _mongo_conn(db).introspect_schema()
    # a non-list answer means "not a real pymongo database": use the information_schema path
    weird = _native_db("nope", {})
    conn = _mongo_conn(weird)
    with patch(
        "query_builder.connectors.mongodb.introspect_information_schema",
        return_value={"tables": {"t": {}}},
    ) as intro:
        assert conn.introspect_schema(filter_sensitive=False) == {"tables": {"t": {}}}
    assert intro.call_args.kwargs["schema_name"] == "app"
    assert intro.call_args.kwargs["filter_sensitive"] is False
    with (
        patch(
            "query_builder.connectors.mongodb.introspect_information_schema",
            side_effect=RuntimeError("bad"),
        ),
        pytest.raises(IntrospectionError, match="bad"),
    ):
        MongoDBAtlasSQLConnector(cursor=MagicMock()).introspect_schema()


def test_mongo_introspect_without_native_database_uses_information_schema() -> None:
    conn = _mongo_conn(None)
    with patch(
        "query_builder.connectors.mongodb.introspect_information_schema",
        return_value={"tables": {}},
    ) as intro:
        assert conn.introspect_schema() == {"tables": {}}
    assert intro.call_args.kwargs["schema_name"] == "app"
