"""Regression tests for real bugs that bringing modules under strict mypy exposed."""

from __future__ import annotations

import asyncio
from typing import Any

import query_builder as qb
from query_builder import middleware, pool
from query_builder.ai.byo_provider import BringYourOwnAiProvider
from query_builder.ai.client import _translate_with_byo
from query_builder.models import ForeignKey, QuerySpec, SchemaSnapshot, TableSchema
from query_builder.schema_converters import _extract_snapshot


def test_extract_snapshot_does_not_mutate_the_callers_foreign_key_list() -> None:
    fk = ForeignKey(
        table="orders", column="user_id", foreign_table="users", foreign_column="id"
    )
    snapshot = SchemaSnapshot(
        tables={"orders": TableSchema(name="orders", columns=[], foreign_keys=[fk])},
        foreign_keys=[],
        relationships=[],
    )
    _, fks = _extract_snapshot(snapshot)
    assert snapshot.foreign_keys == []
    assert fks == [
        {
            "table": "orders",
            "column": "user_id",
            "foreign_table": "users",
            "foreign_column": "id",
        }
    ]


def test_package_exports_both_query_cancelled_errors_distinctly() -> None:
    # The pool class owns the historical top-level name; the middleware one was
    # silently shadowed and is now reachable under an explicit alias.
    assert qb.QueryCancelledError is pool.QueryCancelledError
    assert qb.MiddlewareQueryCancelledError is middleware.QueryCancelledError
    assert qb.MiddlewareQueryCancelledError is not qb.QueryCancelledError


def test_byo_translation_populates_query_spec() -> None:
    def ai(_prompt: str) -> str:
        return '{"table": "users", "columns": ["id"], "limit": 5}'

    provider = BringYourOwnAiProvider(ai=ai)
    res = _translate_with_byo({"prompt": "users"}, provider, None, "postgres")
    assert isinstance(res.query_spec, QuerySpec)
    assert res.query_spec.table == "users"
    assert res.query_spec.limit == 5


def test_cancellation_callback_accepts_non_coroutine_awaitables() -> None:
    from query_builder.async_pool import AsyncCancellationToken

    ran: list[int] = []

    class Later:
        def __await__(self) -> Any:
            ran.append(1)
            return iter(())

    async def main() -> None:
        token = AsyncCancellationToken()
        await token.cancel()
        token.register_callback(lambda: Later())
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(main())
    assert ran == [1]
