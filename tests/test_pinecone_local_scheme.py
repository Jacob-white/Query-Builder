"""Pinecone Local serves plain http; index hosts must inherit the control-plane scheme."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from query_builder.connectors.pinecone import (
    _index_host,
    _index_plan,
    _open_index,
)


def test_index_host_inherits_the_scheme_of_the_explicit_host():
    info = SimpleNamespace(host="localhost:5081")
    assert _index_host(info, "http://localhost:5080") == "http://localhost:5081"
    assert _index_host({"host": "idx.svc"}, "https://api.pinecone.io") == (
        "https://idx.svc"
    )


def test_index_host_is_left_alone_without_a_scheme_to_inherit():
    assert _index_host(SimpleNamespace(host="h:1"), None) == "h:1"
    assert _index_host(SimpleNamespace(host="h:1"), "localhost:5080") == "h:1"
    assert _index_host(SimpleNamespace(host="http://h:1"), "https://x") == "http://h:1"
    assert _index_host(SimpleNamespace(host=None), "http://x") is None


def test_index_plan_passes_the_scheme_qualified_host():
    plan = _index_plan("t", "Index", "http://localhost:5080")
    assert next(plan) == ("describe_index", {"name": "t"})
    call = plan.send(SimpleNamespace(host="localhost:5081"))
    assert call == ("Index", {"host": "http://localhost:5081"})


def test_open_index_resolves_the_host_only_for_scheme_carrying_hosts():
    pc = MagicMock()
    pc.describe_index.return_value = SimpleNamespace(host="localhost:5081")
    _open_index(pc, "idx", "http://localhost:5080")
    pc.Index.assert_called_once_with(host="http://localhost:5081")

    pc2 = MagicMock()
    _open_index(pc2, "idx", None)
    pc2.Index.assert_called_once_with("idx")


def test_page_ids_accepts_plain_id_lists_and_legacy_page_objects():
    from query_builder.connectors.pinecone import _page_ids

    assert _page_ids(["1", "2"]) == ["1", "2"]
    legacy = SimpleNamespace(vectors=[SimpleNamespace(id=7), {"id": "8"}])
    assert _page_ids(legacy) == ["7", "8"]
    assert _page_ids(SimpleNamespace()) == []


def test_drive_async_leaves_sync_iterable_results_alone():
    import asyncio

    from query_builder.connectors._vector_sql import drive_async

    class Both:  # like pinecone's IndexList: sync-iterable and (uselessly) __aiter__
        def __iter__(self):
            return iter([1, 2])

        def __aiter__(self):
            raise TypeError("not a real async iterator")

    class Client:
        def listing(self):
            return Both()

    def plan():
        got = yield ("listing", {})
        return list(got)

    assert asyncio.run(drive_async(plan(), Client())) == [1, 2]
