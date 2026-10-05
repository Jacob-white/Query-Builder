"""
Comprehensive Unit Tests for Phase 4 Connectors: AI Vector & Cloud NoSQL Engines.
=================================================================================
Verifies 100% statement, function, and branch coverage across:
- Qdrant: QdrantConnector, AsyncQdrantConnector, _QdrantCursorAdapter, QdrantDialect, introspect_qdrant
- Pinecone: PineconeConnector, AsyncPineconeConnector, _PineconeCursorAdapter, PineconeDialect, introspect_pinecone
- Weaviate: WeaviateConnector, AsyncWeaviateConnector, _WeaviateCursorAdapter, WeaviateDialect, introspect_weaviate
- Milvus: MilvusConnector, AsyncMilvusConnector, _MilvusCursorAdapter, MilvusDialect, introspect_milvus
- ChromaDB: ChromaConnector, AsyncChromaConnector, ChromaDBConnector, AsyncChromaDBConnector, _ChromaCursorAdapter, ChromaDialect, introspect_chroma
- LanceDB: LanceDBConnector, AsyncLanceDBConnector, _LanceDBCursorAdapter, LanceDBDialect, introspect_lancedb
- Redis / RediSearch: RedisSearchConnector, AsyncRedisSearchConnector, _RedisSearchCursorAdapter, RedisSearchDialect, introspect_redis_search
- Google Cloud Firestore: FirestoreConnector, AsyncFirestoreConnector, _FirestoreCursorAdapter, FirestoreDialect, introspect_firestore
- Google Cloud Bigtable: BigtableConnector, AsyncBigtableConnector, _BigtableCursorAdapter, BigtableDialect, introspect_bigtable
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock, patch

import pytest

from query_builder.connectors import (
    AsyncBigtableConnector,
    AsyncChromaConnector,
    AsyncChromaDBConnector,
    AsyncFirestoreConnector,
    AsyncLanceDBConnector,
    AsyncMilvusConnector,
    AsyncPineconeConnector,
    AsyncQdrantConnector,
    AsyncRedisSearchConnector,
    AsyncWeaviateConnector,
    AsyncZillizConnector,
    BigtableConnector,
    ChromaConnector,
    ChromaDBConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    FirestoreConnector,
    IntrospectionError,
    LanceDBConnector,
    MilvusConnector,
    PineconeConnector,
    QdrantConnector,
    RedisSearchConnector,
    WeaviateConnector,
    ZillizConnector,
    get_connector,
    introspect_bigtable,
    introspect_chroma,
    introspect_firestore,
    introspect_lancedb,
    introspect_milvus,
    introspect_pinecone,
    introspect_qdrant,
    introspect_redis_search,
    introspect_weaviate,
    list_connectors,
)
from query_builder.connectors.bigtable import _BigtableCursorAdapter
from query_builder.connectors.chroma import _ChromaCursorAdapter
from query_builder.connectors.firestore import _FirestoreCursorAdapter
from query_builder.connectors.lancedb import _LanceDBCursorAdapter
from query_builder.connectors.milvus import _MilvusCursorAdapter
from query_builder.connectors.pinecone import _PineconeCursorAdapter
from query_builder.connectors.qdrant import _QdrantCursorAdapter
from query_builder.connectors.redis_search import _RedisSearchCursorAdapter
from query_builder.connectors.weaviate import _WeaviateCursorAdapter
from query_builder.dialects import (
    BigtableDialect,
    ChromaDialect,
    FirestoreDialect,
    LanceDBDialect,
    MilvusDialect,
    PineconeDialect,
    QdrantDialect,
    RedisSearchDialect,
    WeaviateDialect,
    get_dialect,
)

# ============================================================================
# 1. Dialect Tests
# ============================================================================


def test_phase4_dialects():
    # Qdrant
    qd = get_dialect("qdrant")
    assert isinstance(qd, QdrantDialect)
    assert qd.name == "qdrant"
    assert get_dialect("qdrant_vector").name == "qdrant"
    assert qd.format_ilike("c") == "LOWER(c) LIKE LOWER(%s)"
    assert qd.format_limit_offset(10, 5) == ("LIMIT %s OFFSET %s", [10, 5])
    assert qd.inspect_tables_query()[0] == "GET /collections"
    assert qd.inspect_columns_query(table_name="docs")[0] == "GET /collections/docs"
    assert qd.inspect_columns_query()[0] == "GET /collections"
    assert qd.inspect_primary_keys_query() == ("", [])
    assert qd.inspect_foreign_keys_query() == ("", [])

    # Pinecone
    pd = get_dialect("pinecone")
    assert isinstance(pd, PineconeDialect)
    assert pd.name == "pinecone"
    assert get_dialect("pinecone_vector").name == "pinecone"
    assert pd.format_limit_offset(10, 0) == ("LIMIT %s", [10])
    assert pd.inspect_tables_query()[0] == "list_indexes"
    assert pd.inspect_columns_query(table_name="idx")[0] == "describe_index:idx"
    assert pd.inspect_columns_query()[0] == "list_indexes"
    assert pd.inspect_primary_keys_query() == ("", [])
    assert pd.inspect_foreign_keys_query() == ("", [])

    # Weaviate
    wd = get_dialect("weaviate")
    assert isinstance(wd, WeaviateDialect)
    assert wd.name == "weaviate"
    assert get_dialect("weaviate_vector").name == "weaviate"
    assert wd.format_limit_offset(10, 5) == ("LIMIT %s OFFSET %s", [10, 5])
    assert wd.inspect_tables_query()[0] == "collections.list_all"
    assert (
        wd.inspect_columns_query(table_name="Article")[0] == "collections.get:Article"
    )
    assert wd.inspect_columns_query()[0] == "collections.list_all"
    assert wd.inspect_primary_keys_query() == ("", [])
    assert wd.inspect_foreign_keys_query() == ("", [])

    # Milvus
    md = get_dialect("milvus")
    assert isinstance(md, MilvusDialect)
    assert md.name == "milvus"
    assert get_dialect("zilliz").name == "milvus"
    assert md.quote_identifier("db.col") == "`db`.`col`"
    assert md.format_limit_offset(10, 5) == ("LIMIT %s OFFSET %s", [10, 5])
    assert md.inspect_tables_query()[0] == "list_collections"
    assert md.inspect_columns_query(table_name="c")[0] == "describe_collection:c"
    assert md.inspect_columns_query()[0] == "list_collections"
    assert md.inspect_primary_keys_query() == ("", [])
    assert md.inspect_foreign_keys_query() == ("", [])

    # Chroma
    cd = get_dialect("chroma")
    assert isinstance(cd, ChromaDialect)
    assert cd.name == "chroma"
    assert get_dialect("chromadb").name == "chroma"
    assert cd.format_limit_offset(10, 5) == ("LIMIT %s OFFSET %s", [10, 5])
    assert cd.inspect_tables_query()[0] == "list_collections"
    assert cd.inspect_columns_query(table_name="c")[0] == "get_collection:c"
    assert cd.inspect_columns_query()[0] == "list_collections"
    assert cd.inspect_primary_keys_query() == ("", [])
    assert cd.inspect_foreign_keys_query() == ("", [])

    # LanceDB
    ld = get_dialect("lancedb")
    assert isinstance(ld, LanceDBDialect)
    assert ld.name == "lancedb"
    assert get_dialect("lance").name == "lancedb"
    assert ld.format_ilike("c") == "LOWER(c) LIKE LOWER(?)"
    assert ld.format_limit_offset(10, 5) == ("LIMIT ? OFFSET ?", [10, 5])
    assert ld.inspect_tables_query()[0] == "table_names"
    assert ld.inspect_columns_query(table_name="t")[0] == "schema:t"
    assert ld.inspect_columns_query()[0] == "table_names"
    assert ld.inspect_primary_keys_query() == ("", [])
    assert ld.inspect_foreign_keys_query() == ("", [])

    # RedisSearch
    rd = get_dialect("redis")
    assert isinstance(rd, RedisSearchDialect)
    assert rd.name == "redis"
    assert get_dialect("redis_search").name == "redis"
    assert get_dialect("redisearch").name == "redis"
    assert rd.format_limit_offset(10, 5) == ("LIMIT %s %s", [5, 10])
    assert rd.inspect_tables_query()[0] == "FT._LIST"
    assert rd.inspect_columns_query(table_name="idx")[0] == "FT.INFO idx"
    assert rd.inspect_columns_query()[0] == "FT._LIST"
    assert rd.inspect_primary_keys_query() == ("", [])
    assert rd.inspect_foreign_keys_query() == ("", [])

    # Firestore
    fsd = get_dialect("firestore")
    assert isinstance(fsd, FirestoreDialect)
    assert fsd.name == "firestore"
    assert get_dialect("gcp_firestore").name == "firestore"
    assert fsd.format_limit_offset(10, 5) == ("LIMIT %s OFFSET %s", [10, 5])
    assert fsd.inspect_tables_query()[0] == "collections"
    assert fsd.inspect_columns_query(table_name="u")[0] == "collection:u"
    assert fsd.inspect_columns_query()[0] == "collections"
    assert fsd.inspect_primary_keys_query() == ("", [])
    assert fsd.inspect_foreign_keys_query() == ("", [])

    # Bigtable
    btd = get_dialect("bigtable")
    assert isinstance(btd, BigtableDialect)
    assert btd.name == "bigtable"
    assert get_dialect("gcp_bigtable").name == "bigtable"
    assert btd.format_limit_offset(10, 0) == ("LIMIT %s", [10])
    assert btd.inspect_tables_query()[0] == "list_tables"
    assert btd.inspect_columns_query(table_name="tbl")[0] == "list_column_families:tbl"
    assert btd.inspect_columns_query()[0] == "list_tables"
    assert btd.inspect_primary_keys_query() == ("", [])
    assert btd.inspect_foreign_keys_query() == ("", [])


# ============================================================================
# 2. Registry Tests
# ============================================================================


def test_phase4_registry():
    all_conns = list_connectors()
    for name in [
        "qdrant",
        "pinecone",
        "weaviate",
        "milvus",
        "chroma",
        "lancedb",
        "redis_search",
        "firestore",
        "bigtable",
    ]:
        assert name in all_conns
        assert f"async_{name}" in all_conns

    assert isinstance(get_connector("zilliz"), MilvusConnector)
    assert isinstance(get_connector("async_zilliz"), AsyncMilvusConnector)
    assert isinstance(get_connector("weaviate_vector"), WeaviateConnector)
    assert isinstance(get_connector("async_weaviate_vector"), AsyncWeaviateConnector)
    assert isinstance(get_connector("chromadb"), ChromaConnector)
    assert ChromaDBConnector is ChromaConnector
    assert AsyncChromaDBConnector is AsyncChromaConnector
    assert ZillizConnector is MilvusConnector
    assert AsyncZillizConnector is AsyncMilvusConnector


# ============================================================================
# 3. Parametric Cursor Adapter Tests (All 9 Adapters)
# ============================================================================


@pytest.mark.parametrize(
    "adapter_cls",
    [
        _QdrantCursorAdapter,
        _PineconeCursorAdapter,
        _WeaviateCursorAdapter,
        _MilvusCursorAdapter,
        _ChromaCursorAdapter,
        _LanceDBCursorAdapter,
        _RedisSearchCursorAdapter,
        _FirestoreCursorAdapter,
        _BigtableCursorAdapter,
    ],
)
def test_cursor_adapters_phase4_comprehensive(adapter_cls):
    # Branch 1: Connection with cursor() method having close
    mock_cursor = MagicMock()
    mock_cursor.description = [("id", 1), ("name", 2)]
    mock_cursor.fetchall.return_value = [[1, "Alice"], [2, "Bob"], [3, "Charlie"]]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    adapter = adapter_cls(mock_conn)
    adapter.execute("SELECT * FROM test;", [10])
    mock_cursor.execute.assert_called_with("SELECT * FROM test", [10])
    assert adapter.description == [("id", 1), ("name", 2)]

    # fetchone, fetchmany, fetchall
    row1 = adapter.fetchone()
    assert row1 == [1, "Alice"]
    many = adapter.fetchmany(1)
    assert many == [[2, "Bob"]]
    rest = adapter.fetchall()
    assert rest == [[3, "Charlie"]]
    assert adapter.fetchone() is None
    assert adapter.fetchmany(5) == []

    adapter.close()
    assert adapter.fetchall() == []

    # execute without params
    adapter.execute("SELECT * FROM test;")
    mock_cursor.execute.assert_called_with("SELECT * FROM test")

    # Connection with cursor() without close method
    mock_cur_noclose = MagicMock(spec=["execute", "fetchall", "description"])
    mock_cur_noclose.description = [("x",)]
    mock_cur_noclose.fetchall.return_value = [[1]]
    conn_noclose = MagicMock(spec=["cursor"])
    conn_noclose.cursor.return_value = mock_cur_noclose
    adapter_nc = adapter_cls(conn_noclose)
    adapter_nc.execute("SELECT 1")
    assert adapter_nc.fetchall() == [[1]]

    # Branch 2: Connection with execute() returning result object with fetchall
    mock_res = MagicMock(spec=["description", "fetchall"])
    mock_res.description = [("val", 0)]
    mock_res.fetchall.return_value = [[42], [43]]
    conn_with_exec = MagicMock(spec=["execute"])
    conn_with_exec.execute.return_value = mock_res

    adapter2 = adapter_cls(conn_with_exec)
    adapter2.execute("SELECT val FROM test", [1])
    assert adapter2.description == [("val", 0)]
    assert adapter2.fetchall() == [[42], [43]]

    # Connection with execute() returning list/tuple
    conn_with_list = MagicMock(spec=["execute"])
    conn_with_list.execute.return_value = [[100], [200]]
    adapter3 = adapter_cls(conn_with_list)
    adapter3.execute("SELECT val FROM test")
    assert adapter3.fetchall() == [[100], [200]]

    # Connection with execute() returning scalar
    conn_with_scalar = MagicMock(spec=["execute"])
    conn_with_scalar.execute.return_value = 1
    adapter4 = adapter_cls(conn_with_scalar)
    adapter4.execute("SELECT 1")
    adapter4.fetchall()

    # Branch 3: Bare connection without cursor or execute
    bare_conn = object()
    adapter5 = adapter_cls(bare_conn)
    adapter5.execute("SELECT 1")
    assert adapter5.fetchone() is None
    assert adapter5.fetchall() == []


# ============================================================================
# 4. Specialized Adapter Branch Coverage
# ============================================================================


def test_qdrant_adapter_specialized():
    # GET /collections with res.collections
    client = MagicMock(spec=["get_collections"])
    c1 = MagicMock()
    c1.name = "docs"
    res = MagicMock()
    res.collections = [c1]
    client.get_collections.return_value = res
    adapter = _QdrantCursorAdapter(client)
    adapter.execute("GET /collections")
    assert adapter.description == [("collection_name",)]
    assert adapter.fetchall() == [["docs"]]

    # GET /collections with list of strings
    client.get_collections.return_value = ["news"]
    adapter.execute("GET /collections")
    assert adapter.fetchall() == [["news"]]

    # scroll with FROM clause
    client_scroll = MagicMock(spec=["scroll"])
    p1 = MagicMock()
    p1.id = 101
    p1.payload = {"title": "AI"}
    client_scroll.scroll.return_value = ([p1], None)
    adapter2 = _QdrantCursorAdapter(client_scroll)
    adapter2.execute("SELECT * FROM articles;")
    client_scroll.scroll.assert_called_with(collection_name="articles", limit=10)
    assert adapter2.description == [("id",), ("payload",)]
    assert adapter2.fetchall() == [[101, {"title": "AI"}]]

    # scroll with list of points
    client_scroll.scroll.return_value = [p1]
    adapter2.execute("SELECT * FROM default;")
    assert adapter2.fetchall() == [[101, {"title": "AI"}]]

    # scroll with object having .points
    scroll_obj = MagicMock(spec=["points"])
    scroll_obj.points = [p1]
    client_scroll.scroll.return_value = scroll_obj
    adapter2.execute("SELECT 1;")
    assert adapter2.fetchall() == [[101, {"title": "AI"}]]


def test_pinecone_adapter_specialized():
    # list_indexes with callable names()
    client = MagicMock(spec=["list_indexes"])
    idx_resp = MagicMock()
    idx_resp.names.return_value = ["index-a", "index-b"]
    client.list_indexes.return_value = idx_resp
    adapter = _PineconeCursorAdapter(client)
    adapter.execute("list_indexes")
    assert adapter.description == [("index_name",)]
    assert adapter.fetchall() == [["index-a"], ["index-b"]]

    # list_indexes with list of objects
    i_obj = MagicMock()
    i_obj.name = "index-c"
    client.list_indexes.return_value = [i_obj]
    adapter.execute("list_indexes")
    assert adapter.fetchall() == [["index-c"]]

    # list_indexes returning single string
    client.list_indexes.return_value = "index-single"
    adapter.execute("list_indexes")
    assert adapter.fetchall() == [["index-single"]]

    # query on Index
    index_conn = MagicMock(spec=["query"])
    m1 = {"id": "v1", "score": 0.99, "metadata": {"text": "hello"}}
    index_conn.query.return_value = {"matches": [m1]}
    adapter2 = _PineconeCursorAdapter(index_conn)
    adapter2.execute("query", [1.0, 0.0])
    assert adapter2.description == [("id",), ("score",), ("metadata",)]
    assert adapter2.fetchall() == [["v1", 0.99, {"text": "hello"}]]

    # describe_index_stats
    stats_conn = MagicMock(spec=["describe_index_stats"])
    stats_conn.describe_index_stats.return_value = {
        "dimension": 128,
        "total_vector_count": 5000,
    }
    adapter3 = _PineconeCursorAdapter(stats_conn)
    adapter3.execute("describe")
    assert adapter3.description == [("dimension",), ("total_vector_count",)]
    assert adapter3.fetchall() == [[128, 5000]]


def test_weaviate_adapter_specialized():
    # collections.list_all with dict
    client = MagicMock(spec=["collections", "close"])
    client.collections.list_all.return_value = {"Article": 1, "Author": 2}
    adapter = _WeaviateCursorAdapter(client)
    adapter.execute("collections.list_all")
    assert adapter.description == [("class_name",)]
    assert adapter.fetchall() == [["Article"], ["Author"]]

    # collections.list_all with list
    client.collections.list_all.return_value = ["Product"]
    adapter.execute("collections.list_all")
    assert adapter.fetchall() == [["Product"]]

    # graphql.raw_query
    client_gql = MagicMock(spec=["graphql", "close"])
    client_gql.graphql.raw_query.return_value = {"data": {"Get": {"Article": []}}}
    adapter2 = _WeaviateCursorAdapter(client_gql)
    adapter2.execute("{ Get { Article { title } } }")
    assert adapter2.description == [("data",)]
    assert "Article" in adapter2.fetchall()[0][0]


def test_milvus_adapter_specialized():
    # list_collections
    client = MagicMock(spec=["list_collections"])
    client.list_collections.return_value = ["coll_a", "coll_b"]
    adapter = _MilvusCursorAdapter(client)
    adapter.execute("list_collections")
    assert adapter.description == [("collection_name",)]
    assert adapter.fetchall() == [["coll_a"], ["coll_b"]]

    # query with FROM clause
    client_q = MagicMock(spec=["query"])
    client_q.query.return_value = [{"id": 1, "text": "hello"}]
    adapter2 = _MilvusCursorAdapter(client_q)
    adapter2.execute("SELECT * FROM documents")
    client_q.query.assert_called_with(
        collection_name="documents", filter="SELECT * FROM documents"
    )
    assert adapter2.description == [("id",), ("text",)]
    assert adapter2.fetchall() == [[1, "hello"]]

    # query returning non-dict
    client_q.query.return_value = ["item1", "item2"]
    adapter2.execute("SELECT 1")
    assert adapter2.description == [("res",)]
    assert adapter2.fetchall() == [["item1"], ["item2"]]


def test_chroma_adapter_specialized():
    # list_collections with objects having name
    client = MagicMock(spec=["list_collections"])
    c1 = MagicMock()
    c1.name = "embeddings"
    client.list_collections.return_value = [c1]
    adapter = _ChromaCursorAdapter(client)
    adapter.execute("list_collections")
    assert adapter.description == [("collection_name",)]
    assert adapter.fetchall() == [["embeddings"]]

    # get with documents and metadatas
    coll = MagicMock(spec=["get"])
    coll.get.return_value = {
        "ids": ["id1"],
        "documents": ["doc1"],
        "metadatas": [{"cat": "news"}],
    }
    adapter2 = _ChromaCursorAdapter(coll)
    adapter2.execute("SELECT * FROM items")
    assert adapter2.description == [("id",), ("document",), ("metadata",)]
    assert adapter2.fetchall() == [["id1", "doc1", {"cat": "news"}]]


def test_lancedb_adapter_specialized():
    # table_names
    client = MagicMock(spec=["table_names"])
    client.table_names.return_value = ["t1", "t2"]
    adapter = _LanceDBCursorAdapter(client)
    adapter.execute("table_names")
    assert adapter.description == [("table_name",)]
    assert adapter.fetchall() == [["t1"], ["t2"]]

    # open_table with search().to_arrow()
    client_tbl = MagicMock(spec=["open_table"])
    tbl_mock = MagicMock()
    f1 = MagicMock()
    f1.name = "vector"
    schema_mock = [f1]
    arrow_mock = MagicMock()
    arrow_mock.schema = schema_mock
    arrow_mock.to_pylist.return_value = [{"vector": [0.1, 0.2]}]
    tbl_mock.search.return_value.limit.return_value.to_arrow.return_value = arrow_mock
    client_tbl.open_table.return_value = tbl_mock
    adapter2 = _LanceDBCursorAdapter(client_tbl)
    adapter2.execute("SELECT * FROM items")
    assert adapter2.description == [("vector",)]
    assert adapter2.fetchall() == [[[0.1, 0.2]]]

    # open_table with to_pandas()
    tbl_mock2 = MagicMock(spec=["to_pandas"])
    df_mock = MagicMock()
    df_mock.columns = ["col1"]
    df_mock.values = [[99]]
    tbl_mock2.to_pandas.return_value = df_mock
    client_tbl.open_table.return_value = tbl_mock2
    adapter2.execute("SELECT * FROM items")
    assert adapter2.description == [("col1",)]
    assert adapter2.fetchall() == [[99]]

    # open_table raising Exception
    client_tbl.open_table.side_effect = RuntimeError("Open table fail")
    adapter2.execute("SELECT * FROM items")
    assert adapter2.description == [("status",)]
    assert adapter2.fetchall() == [["ok"]]


def test_redis_search_adapter_specialized():
    # execute_command returning list of bytes
    conn = MagicMock(spec=["execute_command"])
    conn.execute_command.return_value = [b"1", b"doc:1", b"fields"]
    adapter = _RedisSearchCursorAdapter(conn)
    adapter.execute("FT.SEARCH idx *")
    assert adapter.description == [("result",)]
    assert adapter.fetchall() == [["1"], ["doc:1"], ["fields"]]

    # execute_command returning single value
    conn.execute_command.return_value = "PONG"
    adapter.execute("PING")
    assert adapter.fetchall() == [["PONG"]]

    # Coroutine execution in running loop
    async def _test():
        async def coro_cmd():
            return [b"OK"]

        conn_async = MagicMock(spec=["execute_command"])
        conn_async.execute_command.return_value = coro_cmd()
        adapter_coro = _RedisSearchCursorAdapter(conn_async)
        adapter_coro.execute("FT.INFO idx")
        assert adapter_coro.fetchall() == [["OK"]]

        # Coroutine error branch
        async def bad_cmd():
            raise RuntimeError("Redis error")

        conn_bad = MagicMock(spec=["execute_command"])
        conn_bad.execute_command.return_value = bad_cmd()
        adapter_bad = _RedisSearchCursorAdapter(conn_bad)
        adapter_bad.execute("PING")

    asyncio.run(_test())


def test_firestore_adapter_specialized():
    # collections
    conn = MagicMock(spec=["collections"])
    c1 = MagicMock()
    c1.id = "users"
    conn.collections.return_value = [c1]
    adapter = _FirestoreCursorAdapter(conn)
    adapter.execute("collections")
    assert adapter.description == [("collection_name",)]
    assert adapter.fetchall() == [["users"]]

    # collection stream with documents
    conn_coll = MagicMock(spec=["collection"])
    coll_ref = MagicMock()
    doc1 = MagicMock()
    doc1.id = "doc_1"
    doc1.to_dict.return_value = {"name": "Bob", "age": 30}
    coll_ref.limit.return_value.stream.return_value = [doc1]
    conn_coll.collection.return_value = coll_ref
    adapter2 = _FirestoreCursorAdapter(conn_coll)
    adapter2.execute("SELECT * FROM users")
    assert adapter2.description == [("id",), ("name",), ("age",)]
    assert adapter2.fetchall() == [["doc_1", "Bob", 30]]

    # collection raising exception
    conn_coll.collection.side_effect = RuntimeError("Firestore down")
    adapter2.execute("SELECT * FROM users")
    assert adapter2.description == [("id",), ("data",)]
    assert adapter2.fetchall() == []


def test_bigtable_adapter_specialized():
    # list_tables
    conn = MagicMock(spec=["list_tables"])
    t1 = MagicMock()
    t1.table_id = "metrics"
    conn.list_tables.return_value = [t1]
    adapter = _BigtableCursorAdapter(conn)
    adapter.execute("list_tables")
    assert adapter.description == [("table_id",)]
    assert adapter.fetchall() == [["metrics"]]

    # table read_rows
    conn_tbl = MagicMock(spec=["table"])
    tbl_obj = MagicMock()
    r1 = MagicMock()
    r1.row_key = b"key-001"
    r1.cells = {"cf": {"col": b"val"}}
    tbl_obj.read_rows.return_value = [r1]
    conn_tbl.table.return_value = tbl_obj
    adapter2 = _BigtableCursorAdapter(conn_tbl)
    adapter2.execute("SELECT * FROM metrics")
    assert adapter2.description == [("row_key",), ("user_id",), ("data",)]
    rows = adapter2.fetchall()
    assert rows[0][0] == "key-001"
    assert "cf" in rows[0][2]

    # table raising exception
    conn_tbl.table.side_effect = RuntimeError("Bigtable down")
    adapter2.execute("SELECT * FROM metrics")
    assert adapter2.description == [("row_key",), ("data",)]
    assert adapter2.fetchall() == []


# ============================================================================
# 5. Full Lifecycle Sync & Async Connector Tests (Phase 4)
# ============================================================================


def _test_sync_lifecycle(conn_cls, driver_path, mock_client, introspect_fn_name):
    # Cached connection
    existing_conn = MagicMock()
    cached_c = conn_cls(connection=existing_conn)
    assert cached_c.connect() is existing_conn

    # Missing driver
    with (
        patch.dict(sys.modules, {driver_path: None}),
        pytest.raises(DriverNotInstalledError),
    ):
        conn_cls().connect()

    # Connection failure
    sync_attrs = (
        "Client",
        "QdrantClient",
        "Pinecone",
        "MilvusClient",
        "connect",
        "connect_to_custom",
        "Redis",
    )
    mock_drv = MagicMock()
    for attr in sync_attrs:
        if hasattr(mock_drv, attr):
            getattr(mock_drv, attr).side_effect = RuntimeError("Connect fail")
    with (
        patch.dict(sys.modules, {driver_path: mock_drv}),
        pytest.raises(ConnectionFailedError),
    ):
        conn_cls().connect()

    # Successful connect
    for attr in sync_attrs:
        if hasattr(mock_drv, attr):
            getattr(mock_drv, attr).side_effect = None
            getattr(mock_drv, attr).return_value = mock_client

    with patch.dict(sys.modules, {driver_path: mock_drv}):
        c = conn_cls()
        conn = c.connect()
        assert conn is not None

        # preset cursor
        preset_cur = MagicMock()
        c_pre = conn_cls(cursor=preset_cur)
        with c_pre.get_cursor() as cur:
            assert cur is preset_cur

        # conn with cursor()
        mock_conn_cur = MagicMock()
        mock_cur = MagicMock()
        mock_conn_cur.cursor.return_value = mock_cur
        c_cur = conn_cls(connection=mock_conn_cur)
        with c_cur.get_cursor() as cur:
            assert cur is mock_cur
        mock_cur.close.assert_called_once()

        # conn with cursor() without close
        mock_conn_cur_nc = MagicMock(spec=["cursor"])
        mock_cur_nc = MagicMock(spec=["execute"])
        mock_conn_cur_nc.cursor.return_value = mock_cur_nc
        c_cur_nc = conn_cls(connection=mock_conn_cur_nc)
        with c_cur_nc.get_cursor() as cur:
            assert cur is mock_cur_nc

        # adapter fallback
        c_adapt = conn_cls(connection=MagicMock(spec=["execute"]))
        with c_adapt.get_cursor() as cur:
            assert cur is not None

        # test_connection
        res = c.test_connection()
        assert res["status"] == "healthy"

        # introspect_schema success and error
        with patch(
            f"{conn_cls.__module__}.{introspect_fn_name}",
            return_value={"tables": {}},
        ):
            assert c.introspect_schema() == {"tables": {}}

        with (
            patch(
                f"{conn_cls.__module__}.{introspect_fn_name}",
                side_effect=RuntimeError("Introspect error"),
            ),
            pytest.raises(IntrospectionError),
        ):
            c.introspect_schema()


def _test_async_lifecycle(async_conn_cls, driver_path, mock_client, introspect_fn_name):
    async def _test():
        conn = async_conn_cls()

        # Cached connection
        mock_conn = MagicMock()
        cached_c = async_conn_cls(connection=mock_conn)
        assert await cached_c.connect() is mock_conn

        # Missing driver
        with (
            patch.dict(sys.modules, {driver_path: None}),
            pytest.raises(DriverNotInstalledError),
        ):
            await conn.connect()

        # Connection error
        async_attrs = (
            "AsyncClient",
            "Client",
            "AsyncQdrantClient",
            "QdrantClient",
            "Pinecone",
            "MilvusClient",
            "connect",
            "connect_async",
            "connect_to_custom",
            "Redis",
            "from_url",
            "BigtableDataClientAsync",
            "AsyncHttpClient",
        )
        mock_drv = MagicMock()
        for attr in async_attrs:
            if hasattr(mock_drv, attr):
                getattr(mock_drv, attr).side_effect = RuntimeError("Async connect fail")
        if hasattr(mock_drv, "asyncio"):
            mock_drv.asyncio.Redis.side_effect = RuntimeError("Async redis fail")
            mock_drv.asyncio.from_url.side_effect = RuntimeError("Async redis fail")

        with (
            patch.dict(sys.modules, {driver_path: mock_drv}),
            pytest.raises(ConnectionFailedError),
        ):
            await conn.connect()

        # execute_raw with cursor on conn
        mock_conn_cur = MagicMock()
        mock_cur = MagicMock()
        mock_cur.description = [("val",)]
        mock_cur.fetchall.return_value = [[77]]
        mock_conn_cur.cursor.return_value = mock_cur

        c_exec = async_conn_cls(connection=mock_conn_cur)
        cols, rows, lat = await c_exec.execute_raw("SELECT 77", [1])
        assert cols == ["val"]
        assert rows == [{"val": 77}]
        assert lat >= 0

        # execute_raw with adapter
        conn_no_cur = MagicMock(spec=["execute"])
        res_obj = MagicMock(spec=["description", "fetchall"])
        res_obj.description = [("a",)]
        res_obj.fetchall.return_value = [[88]]
        conn_no_cur.execute.return_value = res_obj
        c_adapter = async_conn_cls(connection=conn_no_cur)
        cols2, rows2, _ = await c_adapter.execute_raw("SELECT 88")
        assert cols2 == ["a"]
        assert rows2 == [{"a": 88}]

        # test_connection
        t_res = await c_adapter.test_connection()
        assert t_res["status"] == "healthy"

        # introspect_schema success and error
        with patch(
            f"{async_conn_cls.__module__}.{introspect_fn_name}",
            return_value={"tables": {}},
        ):
            assert await c_adapter.introspect_schema() == {"tables": {}}

        with (
            patch(
                f"{async_conn_cls.__module__}.{introspect_fn_name}",
                side_effect=RuntimeError("Async introspect error"),
            ),
            pytest.raises(IntrospectionError),
        ):
            await c_adapter.introspect_schema()

    asyncio.run(_test())


def test_qdrant_connector_lifecycle():
    mock_client = MagicMock(spec=["get_collections", "close"])
    mock_client.get_collections.return_value = []
    _test_sync_lifecycle(
        QdrantConnector, "qdrant_client", mock_client, "introspect_qdrant"
    )
    _test_async_lifecycle(
        AsyncQdrantConnector, "qdrant_client", mock_client, "introspect_qdrant"
    )


def test_pinecone_connector_lifecycle():
    mock_client = MagicMock(spec=["list_indexes", "close"])
    mock_client.list_indexes.return_value = []
    _test_sync_lifecycle(
        PineconeConnector, "pinecone", mock_client, "introspect_pinecone"
    )
    _test_async_lifecycle(
        AsyncPineconeConnector, "pinecone", mock_client, "introspect_pinecone"
    )


def test_weaviate_connector_lifecycle():
    mock_client = MagicMock(spec=["collections", "is_ready", "close"])
    mock_client.collections.list_all.return_value = []
    mock_client.is_ready.return_value = True
    _test_sync_lifecycle(
        WeaviateConnector, "weaviate", mock_client, "introspect_weaviate"
    )
    _test_async_lifecycle(
        AsyncWeaviateConnector, "weaviate", mock_client, "introspect_weaviate"
    )


def test_milvus_connector_lifecycle():
    mock_client = MagicMock(spec=["list_collections", "close"])
    mock_client.list_collections.return_value = []
    _test_sync_lifecycle(MilvusConnector, "pymilvus", mock_client, "introspect_milvus")
    _test_async_lifecycle(
        AsyncMilvusConnector, "pymilvus", mock_client, "introspect_milvus"
    )


def test_chroma_connector_lifecycle():
    mock_client = MagicMock(spec=["list_collections", "close"])
    mock_client.list_collections.return_value = []
    _test_sync_lifecycle(ChromaConnector, "chromadb", mock_client, "introspect_chroma")
    _test_async_lifecycle(
        AsyncChromaConnector, "chromadb", mock_client, "introspect_chroma"
    )


def test_lancedb_connector_lifecycle():
    mock_client = MagicMock(spec=["table_names", "close"])
    mock_client.table_names.return_value = []
    _test_sync_lifecycle(LanceDBConnector, "lancedb", mock_client, "introspect_lancedb")
    _test_async_lifecycle(
        AsyncLanceDBConnector, "lancedb", mock_client, "introspect_lancedb"
    )


def test_redis_search_connector_lifecycle():
    mock_client = MagicMock(spec=["execute_command", "ping", "close"])
    mock_client.execute_command.return_value = ["idx:users"]
    mock_client.ping.return_value = True
    _test_sync_lifecycle(
        RedisSearchConnector, "redis", mock_client, "introspect_redis_search"
    )
    _test_async_lifecycle(
        AsyncRedisSearchConnector,
        "redis",
        mock_client,
        "introspect_redis_search",
    )


def test_firestore_connector_lifecycle():
    mock_client = MagicMock(spec=["collections", "close"])
    mock_client.collections.return_value = []
    _test_sync_lifecycle(
        FirestoreConnector,
        "google.cloud.firestore",
        mock_client,
        "introspect_firestore",
    )
    _test_async_lifecycle(
        AsyncFirestoreConnector,
        "google.cloud.firestore",
        mock_client,
        "introspect_firestore",
    )


def test_bigtable_connector_lifecycle():
    mock_client = MagicMock(spec=["list_tables", "close"])
    mock_client.list_tables.return_value = []
    _test_sync_lifecycle(
        BigtableConnector,
        "google.cloud.bigtable",
        mock_client,
        "introspect_bigtable",
    )
    _test_async_lifecycle(
        AsyncBigtableConnector,
        "google.cloud.bigtable",
        mock_client,
        "introspect_bigtable",
    )


# ============================================================================
# 6. Introspection Tests (Phase 4)
# ============================================================================


def test_introspect_qdrant_branches():
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [["documents"], ["passwords"]]
    schema = introspect_qdrant(mock_cur, filter_sensitive=True)
    assert any(k.lower() == "documents" for k in schema["tables"])
    assert not any(k.lower() == "passwords" for k in schema["tables"])
    tbl_name = next(k for k in schema["tables"] if k.lower() == "documents")
    cols = [col["name"] for col in schema["tables"][tbl_name]["columns"]]
    assert "id" in cols
    assert "user_id" in cols

    # Empty branch
    mock_empty = MagicMock()
    mock_empty.fetchall.return_value = []
    schema_empty = introspect_qdrant(mock_empty)
    assert "documents" in schema_empty["tables"]

    # Error wrapping
    mock_err = MagicMock()
    mock_err.execute.side_effect = RuntimeError("Qdrant query error")
    with pytest.raises(IntrospectionError):
        introspect_qdrant(mock_err)


def test_introspect_pinecone_branches():
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [["vectors"], ["passwords"]]
    schema = introspect_pinecone(mock_cur, filter_sensitive=True)
    assert any(k.lower() == "vectors" for k in schema["tables"])
    assert not any(k.lower() == "passwords" for k in schema["tables"])
    tbl_name = next(k for k in schema["tables"] if k.lower() == "vectors")
    cols = [col["name"] for col in schema["tables"][tbl_name]["columns"]]
    assert "id" in cols
    assert "metadata" in cols

    # Empty branch
    mock_empty = MagicMock()
    mock_empty.fetchall.return_value = []
    schema_empty = introspect_pinecone(mock_empty)
    assert "vectors" in schema_empty["tables"]

    # Error wrapping
    mock_err = MagicMock()
    mock_err.execute.side_effect = RuntimeError("Pinecone query error")
    with pytest.raises(IntrospectionError):
        introspect_pinecone(mock_err)


def test_introspect_weaviate_branches():
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [["Article"], ["passwords"]]
    schema = introspect_weaviate(mock_cur, filter_sensitive=True)
    assert any(k.lower() == "article" for k in schema["tables"])
    assert not any(k.lower() == "passwords" for k in schema["tables"])
    tbl_name = next(k for k in schema["tables"] if k.lower() == "article")
    cols = [col["name"] for col in schema["tables"][tbl_name]["columns"]]
    assert "id" in cols
    assert "user_id" in cols

    # Empty branch
    mock_empty = MagicMock()
    mock_empty.fetchall.return_value = []
    schema_empty = introspect_weaviate(mock_empty)
    assert "Article" in schema_empty["tables"]

    # Error wrapping
    mock_err = MagicMock()
    mock_err.execute.side_effect = RuntimeError("Weaviate query error")
    with pytest.raises(IntrospectionError):
        introspect_weaviate(mock_err)


def test_introspect_milvus_branches():
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [["embeddings"], ["passwords"]]
    schema = introspect_milvus(mock_cur, filter_sensitive=True)
    assert any(k.lower() == "embeddings" for k in schema["tables"])
    assert not any(k.lower() == "passwords" for k in schema["tables"])
    tbl_name = next(k for k in schema["tables"] if k.lower() == "embeddings")
    cols = [col["name"] for col in schema["tables"][tbl_name]["columns"]]
    assert "id" in cols
    assert "vector" in cols

    # Empty branch
    mock_empty = MagicMock()
    mock_empty.fetchall.return_value = []
    schema_empty = introspect_milvus(mock_empty)
    assert "embeddings" in schema_empty["tables"]

    # Error wrapping
    mock_err = MagicMock()
    mock_err.execute.side_effect = RuntimeError("Milvus query error")
    with pytest.raises(IntrospectionError):
        introspect_milvus(mock_err)


def test_introspect_chroma_branches():
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [["notes"], ["passwords"]]
    schema = introspect_chroma(mock_cur, filter_sensitive=True)
    assert any(k.lower() == "notes" for k in schema["tables"])
    assert not any(k.lower() == "passwords" for k in schema["tables"])
    tbl_name = next(k for k in schema["tables"] if k.lower() == "notes")
    cols = [col["name"] for col in schema["tables"][tbl_name]["columns"]]
    assert "id" in cols
    assert "document" in cols

    # Empty branch
    mock_empty = MagicMock()
    mock_empty.fetchall.return_value = []
    schema_empty = introspect_chroma(mock_empty)
    assert "notes" in schema_empty["tables"]

    # Error wrapping
    mock_err = MagicMock()
    mock_err.execute.side_effect = RuntimeError("Chroma query error")
    with pytest.raises(IntrospectionError):
        introspect_chroma(mock_err)


def test_introspect_lancedb_branches():
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [["vectors"], ["passwords"]]
    schema = introspect_lancedb(mock_cur, filter_sensitive=True)
    assert any(k.lower() == "vectors" for k in schema["tables"])
    assert not any(k.lower() == "passwords" for k in schema["tables"])
    tbl_name = next(k for k in schema["tables"] if k.lower() == "vectors")
    cols = [col["name"] for col in schema["tables"][tbl_name]["columns"]]
    assert "id" in cols
    assert "vector" in cols

    # Empty branch
    mock_empty = MagicMock()
    mock_empty.fetchall.return_value = []
    schema_empty = introspect_lancedb(mock_empty)
    assert "items" in schema_empty["tables"]

    # Error wrapping
    mock_err = MagicMock()
    mock_err.execute.side_effect = RuntimeError("LanceDB query error")
    with pytest.raises(IntrospectionError):
        introspect_lancedb(mock_err)


def test_introspect_redis_search_branches():
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [["idx:users"], ["passwords"]]
    schema = introspect_redis_search(mock_cur, filter_sensitive=True)
    assert any(k.lower() == "idx:users" for k in schema["tables"])
    assert not any(k.lower() == "passwords" for k in schema["tables"])
    tbl_name = next(k for k in schema["tables"] if k.lower() == "idx:users")
    cols = [col["name"] for col in schema["tables"][tbl_name]["columns"]]
    assert "id" in cols
    assert "user_id" in cols

    # Empty branch
    mock_empty = MagicMock()
    mock_empty.fetchall.return_value = []
    schema_empty = introspect_redis_search(mock_empty)
    assert "idx:users" in schema_empty["tables"]

    # Error wrapping
    mock_err = MagicMock()
    mock_err.execute.side_effect = RuntimeError("RedisSearch query error")
    with pytest.raises(IntrospectionError):
        introspect_redis_search(mock_err)


def test_introspect_firestore_branches():
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [["users"], ["passwords"]]
    schema = introspect_firestore(mock_cur, filter_sensitive=True)
    assert any(k.lower() == "users" for k in schema["tables"])
    assert not any(k.lower() == "passwords" for k in schema["tables"])
    tbl_name = next(k for k in schema["tables"] if k.lower() == "users")
    cols = [col["name"] for col in schema["tables"][tbl_name]["columns"]]
    assert "id" in cols
    assert "user_id" in cols

    # Empty branch
    mock_empty = MagicMock()
    mock_empty.fetchall.return_value = []
    schema_empty = introspect_firestore(mock_empty)
    assert "users" in schema_empty["tables"]

    # Error wrapping
    mock_err = MagicMock()
    mock_err.execute.side_effect = RuntimeError("Firestore query error")
    with pytest.raises(IntrospectionError):
        introspect_firestore(mock_err)


def test_introspect_bigtable_branches():
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [["events"], ["passwords"]]
    schema = introspect_bigtable(mock_cur, filter_sensitive=True)
    assert any(k.lower() == "events" for k in schema["tables"])
    assert not any(k.lower() == "passwords" for k in schema["tables"])
    tbl_name = next(k for k in schema["tables"] if k.lower() == "events")
    cols = [col["name"] for col in schema["tables"][tbl_name]["columns"]]
    assert "row_key" in cols
    assert "user_id" in cols

    # Empty branch
    mock_empty = MagicMock()
    mock_empty.fetchall.return_value = []
    schema_empty = introspect_bigtable(mock_empty)
    assert "metrics" in schema_empty["tables"]

    # Error wrapping
    mock_err = MagicMock()
    mock_err.execute.side_effect = RuntimeError("Bigtable query error")
    with pytest.raises(IntrospectionError):
        introspect_bigtable(mock_err)


# ============================================================================
# 7. Additional Granular Coverage Tests
# ============================================================================


def test_bigtable_coverage_branches():
    mock_conn = MagicMock(spec=["execute_query"])
    res_obj = MagicMock(spec=["description", "fetchall"])
    res_obj.description = [("col_a",)]
    res_obj.fetchall.return_value = [["val1"]]
    mock_conn.execute_query.return_value = res_obj
    adapter = _BigtableCursorAdapter(mock_conn)
    adapter.execute("SELECT * FROM t", [1])
    assert adapter.description == [("col_a",)]
    assert adapter.fetchall() == [["val1"]]
    adapter.execute("SELECT * FROM t")
    assert adapter.fetchall() == [["val1"]]

    mock_conn.execute_query.return_value = [["val2"]]
    adapter.execute("SELECT * FROM t")
    assert adapter.fetchall() == [["val2"]]

    mock_conn.execute_query.return_value = 123
    adapter.execute("SELECT * FROM t")
    assert adapter.fetchall() == []

    mock_conn_exec = MagicMock(spec=["execute"])
    mock_conn_exec.execute.return_value = res_obj
    adapter_exec = _BigtableCursorAdapter(mock_conn_exec)
    adapter_exec.execute("SELECT 1", [10])
    assert adapter_exec.fetchall() == [["val1"]]
    adapter_exec.execute("SELECT 1")
    assert adapter_exec.fetchall() == [["val1"]]
    mock_conn_exec.execute.return_value = [["val3"]]
    adapter_exec.execute("SELECT 1")
    assert adapter_exec.fetchall() == [["val3"]]
    mock_conn_exec.execute.return_value = 456
    adapter_exec.execute("SELECT 1")
    assert adapter_exec.fetchall() == []

    raw_conn = MagicMock(spec=[])
    adapter_none = _BigtableCursorAdapter(raw_conn)
    adapter_none.execute("FOO")
    assert adapter_none.description is None
    assert adapter_none.fetchall() == []

    mock_drv = MagicMock()
    mock_client = MagicMock()
    mock_inst = MagicMock()
    mock_client.instance.return_value = mock_inst
    mock_drv.Client.return_value = mock_client
    with patch.dict(sys.modules, {"google.cloud.bigtable": mock_drv}):
        c_inst = BigtableConnector(project_id="proj", instance_id="inst1")
        assert c_inst.connect() is mock_inst

    raw_driver = MagicMock(spec=["__call__"])
    raw_driver.return_value = raw_driver
    with patch.dict(sys.modules, {"google.cloud.bigtable": raw_driver}):
        c_raw = BigtableConnector()
        assert c_raw.connect() is raw_driver

    c_no_tbls = BigtableConnector(connection=MagicMock(spec=[]))
    assert c_no_tbls.test_connection()["status"] == "healthy"

    async def _test_async_bt():
        mock_async_drv = MagicMock()
        mock_async_client = MagicMock()
        mock_async_inst = MagicMock()
        mock_async_client.instance.return_value = mock_async_inst
        mock_async_drv.BigtableDataClientAsync.return_value = mock_async_client
        with patch.dict(
            sys.modules,
            {
                "google.cloud.bigtable.data": None,
                "google.cloud.bigtable": mock_async_drv,
            },
        ):
            c_async_inst = AsyncBigtableConnector(
                project_id="proj", instance_id="inst1"
            )
            assert await c_async_inst.connect() is mock_async_inst

            c_async_no_inst = AsyncBigtableConnector(project_id="proj")
            assert await c_async_no_inst.connect() is mock_async_client

        mock_conn_async = MagicMock(spec=["list_tables"])

        async def async_tables():
            return []

        mock_conn_async.list_tables.return_value = async_tables()
        c_test = AsyncBigtableConnector(connection=mock_conn_async)
        res = await c_test.test_connection()
        assert res["status"] == "healthy"

        mock_conn_sync_tbls = MagicMock(spec=["list_tables"])
        mock_conn_sync_tbls.list_tables.return_value = []
        c_test_sync = AsyncBigtableConnector(connection=mock_conn_sync_tbls)
        assert (await c_test_sync.test_connection())["status"] == "healthy"

        c_test2 = AsyncBigtableConnector(connection=MagicMock(spec=[]))
        res2 = await c_test2.test_connection()
        assert res2["status"] == "healthy"

    asyncio.run(_test_async_bt())


def test_chroma_coverage_branches():
    mock_drv = MagicMock()
    mock_http = MagicMock()
    mock_pers = MagicMock()
    mock_def = MagicMock()
    mock_drv.HttpClient.return_value = mock_http
    mock_drv.PersistentClient.return_value = mock_pers
    mock_drv.Client.return_value = mock_def

    with patch.dict(sys.modules, {"chromadb": mock_drv}):
        c_host = ChromaConnector(host="localhost", port=8000)
        assert c_host.connect() is mock_http
        c_path = ChromaConnector(path="/tmp/chroma")
        assert c_path.connect() is mock_pers
        c_def = ChromaConnector()
        assert c_def.connect() is mock_def

    c_hb = ChromaConnector(connection=MagicMock(spec=["heartbeat"]))
    assert c_hb.test_connection()["status"] == "healthy"
    c_lc = ChromaConnector(connection=MagicMock(spec=["list_collections"]))
    assert c_lc.test_connection()["status"] == "healthy"
    c_none = ChromaConnector(connection=MagicMock(spec=[]))
    assert c_none.test_connection()["status"] == "healthy"

    async def _test_async_chroma():
        mock_async_http = MagicMock()

        async def fake_async_client(*a, **kw):
            return mock_async_http

        mock_drv.AsyncHttpClient = fake_async_client
        with patch.dict(sys.modules, {"chromadb": mock_drv}):
            c_async_host = AsyncChromaConnector(host="localhost")
            assert await c_async_host.connect() is mock_async_http

            del mock_drv.AsyncHttpClient
            c_async_host2 = AsyncChromaConnector(host="localhost")
            assert await c_async_host2.connect() is mock_http

            c_async_path = AsyncChromaConnector(path="/tmp/chroma")
            assert await c_async_path.connect() is mock_pers

            c_async_def = AsyncChromaConnector()
            assert await c_async_def.connect() is mock_def

        c_a_hb = AsyncChromaConnector(connection=MagicMock(spec=["heartbeat"]))
        assert (await c_a_hb.test_connection())["status"] == "healthy"
        c_a_lc = AsyncChromaConnector(connection=MagicMock(spec=["list_collections"]))
        assert (await c_a_lc.test_connection())["status"] == "healthy"
        c_a_none = AsyncChromaConnector(connection=MagicMock(spec=[]))
        assert (await c_a_none.test_connection())["status"] == "healthy"

    asyncio.run(_test_async_chroma())


def test_firestore_coverage_branches():
    mock_conn = MagicMock(spec=["collection"])
    coll_mock = MagicMock()
    coll_mock.limit.return_value.stream.return_value = []
    mock_conn.collection.return_value = coll_mock
    adapter = _FirestoreCursorAdapter(mock_conn)
    adapter.execute("SELECT * FROM users")
    assert adapter.description == [("id",), ("data",)]
    assert adapter.fetchall() == []

    mock_conn_exec = MagicMock(spec=["execute"])
    res_obj = MagicMock(spec=["description", "fetchall"])
    res_obj.description = [("col1",)]
    res_obj.fetchall.return_value = [[123]]
    mock_conn_exec.execute.return_value = res_obj
    adapter_exec = _FirestoreCursorAdapter(mock_conn_exec)
    adapter_exec.execute("SELECT 1", [1])
    assert adapter_exec.fetchall() == [[123]]
    adapter_exec.execute("SELECT 1")
    assert adapter_exec.fetchall() == [[123]]
    mock_conn_exec.execute.return_value = [[456]]
    adapter_exec.execute("SELECT 1")
    assert adapter_exec.fetchall() == [[456]]
    mock_conn_exec.execute.return_value = "other"
    adapter_exec.execute("SELECT 1")
    assert adapter_exec.fetchall() == []

    c_none = FirestoreConnector(connection=MagicMock(spec=[]))
    assert c_none.test_connection()["status"] == "healthy"

    async def _test_async_fs():
        mock_drv = MagicMock()
        mock_client = MagicMock()
        mock_drv.AsyncClient.return_value = mock_client
        with patch.dict(sys.modules, {"google.cloud.firestore": mock_drv}):
            c_async = AsyncFirestoreConnector()
            assert await c_async.connect() is mock_client

        mock_conn_await = MagicMock(spec=["collections"])

        async def async_colls():
            return []

        mock_conn_await.collections.return_value = async_colls()
        c_a_colls = AsyncFirestoreConnector(connection=mock_conn_await)
        assert (await c_a_colls.test_connection())["status"] == "healthy"

        mock_conn_sync_colls = MagicMock(spec=["collections"])
        mock_conn_sync_colls.collections.return_value = []
        c_a_sync_colls = AsyncFirestoreConnector(connection=mock_conn_sync_colls)
        assert (await c_a_sync_colls.test_connection())["status"] == "healthy"

        c_a_none = AsyncFirestoreConnector(connection=MagicMock(spec=[]))
        assert (await c_a_none.test_connection())["status"] == "healthy"

    asyncio.run(_test_async_fs())


def test_lancedb_coverage_branches():
    mock_conn = MagicMock(spec=["open_table"])
    tbl_empty = MagicMock(spec=[])
    mock_conn.open_table.return_value = tbl_empty
    adapter = _LanceDBCursorAdapter(mock_conn)
    adapter.execute("SELECT * FROM items")
    assert adapter.description == [("status",)]
    assert adapter.fetchall() == [["ok"]]

    c_none = LanceDBConnector(connection=MagicMock(spec=[]))
    assert c_none.test_connection()["status"] == "healthy"

    async def _test_async_lance():
        mock_drv = MagicMock()
        mock_sync_conn = MagicMock()
        mock_drv.connect.return_value = mock_sync_conn

        async def fake_async_lance(*a, **kw):
            return mock_sync_conn

        mock_drv.connect_async = fake_async_lance
        with patch.dict(sys.modules, {"lancedb": mock_drv}):
            c_coro = AsyncLanceDBConnector()
            assert await c_coro.connect() is mock_sync_conn

            mock_drv.connect_async = MagicMock(return_value=mock_sync_conn)
            c_plain = AsyncLanceDBConnector()
            assert await c_plain.connect() is mock_sync_conn

            del mock_drv.connect_async
            c_fallback = AsyncLanceDBConnector()
            assert await c_fallback.connect() is mock_sync_conn

        mock_conn_await = MagicMock(spec=["table_names"])

        async def async_tbls():
            return []

        mock_conn_await.table_names.return_value = async_tbls()
        c_a_tbls = AsyncLanceDBConnector(connection=mock_conn_await)
        assert (await c_a_tbls.test_connection())["status"] == "healthy"

        mock_conn_sync_tbls = MagicMock(spec=["table_names"])
        mock_conn_sync_tbls.table_names.return_value = []
        c_a_sync_tbls = AsyncLanceDBConnector(connection=mock_conn_sync_tbls)
        assert (await c_a_sync_tbls.test_connection())["status"] == "healthy"

        c_a_none = AsyncLanceDBConnector(connection=MagicMock(spec=[]))
        assert (await c_a_none.test_connection())["status"] == "healthy"

    asyncio.run(_test_async_lance())


def test_milvus_coverage_branches():
    raw_driver = MagicMock(spec=[])
    with patch.dict(sys.modules, {"pymilvus": raw_driver}):
        c_raw = MilvusConnector()
        assert c_raw.connect() is raw_driver

    c_none = MilvusConnector(connection=MagicMock(spec=[]))
    assert c_none.test_connection()["status"] == "healthy"

    async def _test_async_milvus():
        with patch.dict(sys.modules, {"pymilvus": raw_driver}):
            c_a_raw = AsyncMilvusConnector()
            assert await c_a_raw.connect() is raw_driver

        mock_conn_lc = MagicMock(spec=["list_collections"])
        c_a_lc = AsyncMilvusConnector(connection=mock_conn_lc)
        assert (await c_a_lc.test_connection())["status"] == "healthy"
        mock_conn_lc.list_collections.assert_called_once()

        c_a_none = AsyncMilvusConnector(connection=MagicMock(spec=[]))
        assert (await c_a_none.test_connection())["status"] == "healthy"

    asyncio.run(_test_async_milvus())


def test_pinecone_coverage_branches():
    mock_conn = MagicMock(spec=["list_indexes"])
    idx_obj = MagicMock()
    idx_obj.name = "idx_one"
    indexes_mock = [idx_obj]
    mock_conn.list_indexes.return_value = indexes_mock
    adapter = _PineconeCursorAdapter(mock_conn)
    adapter.execute("list_indexes")
    assert adapter.fetchall() == [["idx_one"]]

    class _CustomIndexList(list):
        names = None

    idx_custom = _CustomIndexList([idx_obj])
    mock_conn.list_indexes.return_value = idx_custom
    adapter.execute("list_indexes")
    assert adapter.fetchall() == [["idx_one"]]

    mock_conn.list_indexes.return_value = 999
    adapter.execute("list_indexes")
    assert adapter.fetchall() == [["999"]]

    mock_drv = MagicMock()
    mock_pc = MagicMock()
    mock_idx = MagicMock()
    mock_pc.Index.return_value = mock_idx
    mock_drv.Pinecone.return_value = mock_pc
    with patch.dict(sys.modules, {"pinecone": mock_drv}):
        c_idx = PineconeConnector(index_name="my_idx")
        assert c_idx.connect() is mock_idx

        del mock_drv.Pinecone
        c_no_pc = PineconeConnector()
        assert c_no_pc.connect() is mock_drv

    c_none = PineconeConnector(connection=MagicMock(spec=[]))
    assert c_none.test_connection()["status"] == "healthy"

    async def _test_async_pinecone():
        mock_drv2 = MagicMock()
        mock_pc2 = MagicMock()
        mock_idx2 = MagicMock()
        mock_pc2.Index.return_value = mock_idx2
        mock_drv2.Pinecone.return_value = mock_pc2
        with patch.dict(sys.modules, {"pinecone": mock_drv2}):
            c_a_idx = AsyncPineconeConnector(index_name="my_idx")
            assert await c_a_idx.connect() is mock_idx2

            c_a_no_idx = AsyncPineconeConnector()
            assert await c_a_no_idx.connect() is mock_pc2

            del mock_drv2.Pinecone
            c_a_no_pc = AsyncPineconeConnector()
            assert await c_a_no_pc.connect() is mock_drv2

        mock_conn_li = MagicMock(spec=["list_indexes"])
        c_a_li = AsyncPineconeConnector(connection=mock_conn_li)
        assert (await c_a_li.test_connection())["status"] == "healthy"
        mock_conn_li.list_indexes.assert_called_once()

        c_a_none = AsyncPineconeConnector(connection=MagicMock(spec=[]))
        assert (await c_a_none.test_connection())["status"] == "healthy"

    asyncio.run(_test_async_pinecone())


def test_qdrant_coverage_branches():
    mock_drv = MagicMock()
    mock_client = MagicMock()
    mock_drv.QdrantClient.return_value = mock_client
    with patch.dict(sys.modules, {"qdrant_client": mock_drv}):
        c_url = QdrantConnector(url="http://remote:6333")
        assert c_url.connect() is mock_client

    c_none = QdrantConnector(connection=MagicMock(spec=[]))
    assert c_none.test_connection()["status"] == "healthy"

    async def _test_async_qdrant():
        mock_async_drv = MagicMock()
        mock_async_client = MagicMock()
        mock_async_drv.AsyncQdrantClient.return_value = mock_async_client
        with patch.dict(sys.modules, {"qdrant_client": mock_async_drv}):
            c_a_url = AsyncQdrantConnector(url="http://remote:6333")
            assert await c_a_url.connect() is mock_async_client

        mock_conn_gc = MagicMock(spec=["get_collections"])

        async def async_colls():
            return []

        mock_conn_gc.get_collections.return_value = async_colls()
        c_a_gc = AsyncQdrantConnector(connection=mock_conn_gc)
        assert (await c_a_gc.test_connection())["status"] == "healthy"

        mock_conn_sync_gc = MagicMock(spec=["get_collections"])
        mock_conn_sync_gc.get_collections.return_value = []
        c_a_sync_gc = AsyncQdrantConnector(connection=mock_conn_sync_gc)
        assert (await c_a_sync_gc.test_connection())["status"] == "healthy"

        c_a_none = AsyncQdrantConnector(connection=MagicMock(spec=[]))
        assert (await c_a_none.test_connection())["status"] == "healthy"

    asyncio.run(_test_async_qdrant())


def test_redis_search_coverage_branches():
    mock_conn = MagicMock(spec=["execute_command"])

    async def async_res():
        return [b"item1"]

    mock_conn.execute_command.return_value = async_res()
    adapter = _RedisSearchCursorAdapter(mock_conn)
    adapter.execute("FT.SEARCH idx *")
    assert adapter.fetchall() == [["item1"]]

    mock_conn.execute_command.return_value = b"OK"
    adapter.execute("SET key val")
    assert adapter.fetchall() == [["OK"]]

    c_none = RedisSearchConnector(connection=MagicMock(spec=[]))
    assert c_none.test_connection()["status"] == "healthy"

    async def _test_async_redis():
        mock_drv = MagicMock()
        mock_client = MagicMock()
        mock_drv.Redis.return_value = mock_client
        with patch.dict(sys.modules, {"redis": mock_drv}):
            c_async = AsyncRedisSearchConnector()
            assert await c_async.connect() is mock_client

        mock_native_conn = MagicMock(spec=["execute_command"])

        async def async_list():
            return [b"alpha", b"beta"]

        mock_native_conn.execute_command.return_value = async_list()
        c_native = AsyncRedisSearchConnector(connection=mock_native_conn)
        cols, rows, _ = await c_native.execute_raw("FT._LIST")
        assert cols == ["result"]
        assert rows == [{"result": "alpha"}, {"result": "beta"}]

        async def async_scalar():
            return b"PONG"

        mock_native_conn.execute_command.return_value = async_scalar()
        cols, rows, _ = await c_native.execute_raw("PING")
        assert rows == [{"result": "PONG"}]

        mock_native_conn.execute_command.return_value = ["x", "y"]
        cols, rows, _ = await c_native.execute_raw("FT._LIST")
        assert rows == [{"result": "x"}, {"result": "y"}]

        mock_native_conn.execute_command.return_value = "PONG"
        cols, rows, _ = await c_native.execute_raw("PING")
        assert rows == [{"result": "PONG"}]

        mock_conn_ping = MagicMock(spec=["ping"])

        async def async_ping():
            return True

        mock_conn_ping.ping.return_value = async_ping()
        c_a_ping = AsyncRedisSearchConnector(connection=mock_conn_ping)
        assert (await c_a_ping.test_connection())["status"] == "healthy"

        mock_conn_sync_ping = MagicMock(spec=["ping"])
        mock_conn_sync_ping.ping.return_value = True
        c_a_sync_ping = AsyncRedisSearchConnector(connection=mock_conn_sync_ping)
        assert (await c_a_sync_ping.test_connection())["status"] == "healthy"

        c_a_none = AsyncRedisSearchConnector(connection=MagicMock(spec=[]))
        assert (await c_a_none.test_connection())["status"] == "healthy"

    asyncio.run(_test_async_redis())


def test_weaviate_coverage_branches():
    mock_drv = MagicMock()
    mock_client = MagicMock()
    mock_drv.Client.return_value = mock_client
    del mock_drv.connect_to_custom

    with patch.dict(sys.modules, {"weaviate": mock_drv}):
        c_client = WeaviateConnector()
        assert c_client.connect() is mock_client

        raw_driver = MagicMock(spec=[])
        with patch.dict(sys.modules, {"weaviate": raw_driver}):
            c_raw = WeaviateConnector()
            assert c_raw.connect() is raw_driver

    mock_conn_colls = MagicMock(spec=["collections"])
    c_colls = WeaviateConnector(connection=mock_conn_colls)
    assert c_colls.test_connection()["status"] == "healthy"
    mock_conn_colls.collections.list_all.assert_called_once()

    c_none = WeaviateConnector(connection=MagicMock(spec=[]))
    assert c_none.test_connection()["status"] == "healthy"

    async def _test_async_weaviate():
        mock_async_drv = MagicMock()
        mock_async_client = MagicMock()
        mock_async_drv.Client.return_value = mock_async_client
        del mock_async_drv.connect_to_custom
        with patch.dict(sys.modules, {"weaviate": mock_async_drv}):
            c_a_client = AsyncWeaviateConnector()
            assert await c_a_client.connect() is mock_async_client

            raw_async_driver = MagicMock(spec=[])
            with patch.dict(sys.modules, {"weaviate": raw_async_driver}):
                c_a_raw = AsyncWeaviateConnector()
                assert await c_a_raw.connect() is raw_async_driver

        mock_conn_ir = MagicMock(spec=["is_ready"])

        async def async_ready():
            return True

        mock_conn_ir.is_ready.return_value = async_ready()
        c_a_ir = AsyncWeaviateConnector(connection=mock_conn_ir)
        assert (await c_a_ir.test_connection())["status"] == "healthy"

        mock_conn_sync_ir = MagicMock(spec=["is_ready"])
        mock_conn_sync_ir.is_ready.return_value = True
        c_a_sync_ir = AsyncWeaviateConnector(connection=mock_conn_sync_ir)
        assert (await c_a_sync_ir.test_connection())["status"] == "healthy"

        c_a_none = AsyncWeaviateConnector(connection=MagicMock(spec=[]))
        assert (await c_a_none.test_connection())["status"] == "healthy"

    asyncio.run(_test_async_weaviate())
