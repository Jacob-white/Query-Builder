"""Small mock tests closing branch gaps in recently rewritten connectors."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from query_builder.connectors import postgres as pg
from query_builder.connectors.cosmosdb import AsyncCosmosDBConnector, CosmosDBConnector
from query_builder.connectors.dynamodb import DynamoDBConnector


def test_pg_read_only_sets_session_default_and_commits() -> None:
    conn = MagicMock()
    pg._pg_read_only(conn)
    cur = conn.cursor.return_value
    cur.execute.assert_called_once_with(
        "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"
    )
    cur.close.assert_called_once()
    conn.commit.assert_called_once()


def test_pg_read_only_commits_even_when_cursor_close_fails() -> None:
    conn = MagicMock()
    conn.cursor.return_value.close.side_effect = RuntimeError("close err")
    pg._pg_read_only(conn)  # must not raise and must still commit
    conn.commit.assert_called_once()


def test_pg_read_only_tolerates_objects_without_close_or_commit() -> None:
    cur = SimpleNamespace(execute=MagicMock())
    conn = SimpleNamespace(cursor=lambda: cur)
    pg._pg_read_only(conn)
    cur.execute.assert_called_once()


def test_pg_read_only_closes_cursor_when_set_fails() -> None:
    conn = MagicMock()
    conn.cursor.return_value.execute.side_effect = RuntimeError("denied")
    with pytest.raises(RuntimeError, match="denied"):
        pg._pg_read_only(conn)
    conn.cursor.return_value.close.assert_called_once()
    conn.commit.assert_not_called()


def test_dynamodb_unmarshals_every_set_and_collection_type() -> None:
    f = DynamoDBConnector._unmarshal_value
    assert f({"SS": ["a", "b"]}) == ["a", "b"]
    assert f({"NS": ["1", "2.5"]}) == [1, 2.5]
    assert f({"L": [{"S": "x"}, {"NULL": True}]}) == ["x", None]
    assert f({"M": {"k": {"BOOL": False}}}) == {"k": False}


def test_cosmos_health_check_falls_back_to_generic_probe() -> None:
    cur = MagicMock(spec=["execute", "fetchone"])
    conn = CosmosDBConnector(cursor=cur)
    info = conn.test_connection()
    assert info["status"] == "healthy" and info["database"] == "default"
    cur.execute.assert_called_with("SELECT 1")
    # a client with neither get_database_client nor cursor(): nothing to probe, still reported
    bare = CosmosDBConnector(connection=SimpleNamespace())
    assert bare.test_connection()["status"] == "healthy"


def test_async_cosmos_introspection_skips_id_less_containers_and_wraps_errors() -> None:
    class Db:
        def list_containers(self) -> Any:
            return [{}, SimpleNamespace(id=None), {"id": "orders"}]

        def get_container_client(self, name: str) -> Any:
            assert name == "orders"
            return SimpleNamespace(query_items=lambda query: [{"id": "1", "sku": "x"}])

    client = SimpleNamespace(get_database_client=lambda name: Db())
    snap = asyncio.run(AsyncCosmosDBConnector(connection=client).introspect_schema())
    assert set(snap["tables"]) == {"orders"}
    assert {c["name"] for c in snap["tables"]["orders"]["columns"]} >= {"id", "sku"}

    def boom(name: str) -> Any:
        raise RuntimeError("403 forbidden")

    from query_builder.connectors.base import IntrospectionError

    with pytest.raises(IntrospectionError, match="403 forbidden"):
        asyncio.run(
            AsyncCosmosDBConnector(
                connection=SimpleNamespace(get_database_client=boom)
            ).introspect_schema()
        )
