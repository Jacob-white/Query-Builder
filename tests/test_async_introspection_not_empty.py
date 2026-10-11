"""An async connector must never inherit the empty-snapshot introspection default.

``AsyncBaseConnector.introspect_schema`` returns "no tables"; an async class that forgot to
override it reported an empty database no matter what the server held (found live on
StarRocks, Materialize, GreptimeDB).
"""

import asyncio
import importlib
from unittest.mock import MagicMock, patch

import pytest

from query_builder.connectors import registry
from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import IntrospectionError


def _registered_classes():
    registry_cls = next(v for v in vars(registry).values() if hasattr(v, "_registry"))
    return sorted(set(registry_cls._registry.values()), key=lambda c: c.__name__)


def test_no_async_connector_inherits_the_empty_default():
    offenders = [
        c.__name__
        for c in _registered_classes()
        if issubclass(c, AsyncBaseConnector)
        and next(k for k in c.__mro__ if "introspect_schema" in k.__dict__)
        is AsyncBaseConnector
    ]
    assert offenders == []


CASES = [
    ("exasol", "AsyncExasolConnector", "introspect_exasol", "PUBLIC", {}),
    ("greptimedb", "AsyncGreptimeDBConnector", "introspect_greptimedb", "public", {}),
    (
        "materialize",
        "AsyncMaterializeConnector",
        "introspect_information_schema",
        "public",
        {},
    ),
    (
        "prestodb",
        "AsyncPrestoDBConnector",
        "introspect_information_schema",
        "default",
        {"placeholder": "?", "pk_guess": False},
    ),
    (
        "risingwave",
        "AsyncRisingWaveConnector",
        "introspect_information_schema",
        "public",
        {},
    ),
    ("spark", "AsyncSparkSQLConnector", "introspect_sparksql", "default", {}),
    (
        "starrocks",
        "AsyncStarRocksConnector",
        "introspect_information_schema",
        "default",
        {},
    ),
]


@pytest.mark.parametrize(("module", "cls_name", "fn", "schema", "extra"), CASES)
def test_blocking_async_connectors_delegate_to_their_introspection(
    module, cls_name, fn, schema, extra
):
    mod = importlib.import_module(f"query_builder.connectors.{module}")
    conn_cls = getattr(mod, cls_name)
    cursor = MagicMock()
    connection = MagicMock()
    connection.cursor.return_value = cursor
    connector = conn_cls(connection=connection)
    snapshot = {"tables": {"t": {}}}

    with patch.object(mod, fn, return_value=snapshot) as introspect:
        assert asyncio.run(connector.introspect_schema(filter_sensitive=False)) == (
            snapshot
        )
    args, kwargs = introspect.call_args
    assert args == (cursor,)
    assert kwargs["filter_sensitive"] is False
    assert kwargs["schema_name"] == getattr(connector, "database", None) or kwargs[
        "schema_name"
    ] == getattr(connector, "schema_name", None)
    for key, value in extra.items():
        assert kwargs[key] == value
    cursor.close.assert_called_once()


def test_a_failing_introspection_is_wrapped():
    from query_builder.connectors import materialize

    connection = MagicMock()
    connector = materialize.AsyncMaterializeConnector(connection=connection)
    with (
        patch.object(
            materialize, "introspect_information_schema", side_effect=RuntimeError("x")
        ),
        pytest.raises(IntrospectionError, match="Materialize"),
    ):
        asyncio.run(connector.introspect_schema())


def test_cursor_without_close_is_tolerated():
    from query_builder.connectors import risingwave

    cursor = object()  # no close()
    connection = MagicMock()
    connection.cursor.return_value = cursor
    connector = risingwave.AsyncRisingWaveConnector(connection=connection)
    with patch.object(
        risingwave, "introspect_information_schema", return_value={"tables": {}}
    ):
        assert asyncio.run(connector.introspect_schema()) == {"tables": {}}


def test_information_schema_pk_falls_back_to_column_key_when_constraints_are_empty():
    from query_builder.connectors.introspection import introspect_information_schema

    cur = MagicMock()
    results = iter(
        [
            [("t",)],  # tables
            [("t", "id", "int", "NO"), ("t", "v", "int", "YES")],  # columns
            [],  # table_constraints primary keys: StarRocks lists none
            [("t", "id")],  # columns.column_key = 'PRI'
            [],  # foreign keys
        ]
    )
    cur.fetchall.side_effect = lambda: next(results)
    snap = introspect_information_schema(
        cur, schema_name="db", pk_column_key_fallback=True
    )
    cols = {c["name"]: c["is_primary"] for c in snap["tables"]["t"]["columns"]}
    assert cols == {"id": True, "v": False}
    assert any("column_key = 'PRI'" in c.args[0] for c in cur.execute.call_args_list)


def test_the_base_default_is_still_an_empty_snapshot_for_subclasses_that_opt_in():
    class Bare(AsyncBaseConnector):
        dialect_name = "postgres"

        async def connect(self):
            return None

    snapshot = asyncio.run(Bare().introspect_schema())
    assert snapshot["tables"] == {}
