import json
from unittest.mock import MagicMock, patch
import pytest

from query_builder import (
    QueryCompiler,
    ValidationError,
    VectorSearchSpec,
    get_dialect,
)
from query_builder.connectors.chroma import _ChromaCursorAdapter
from query_builder.connectors.lancedb import _LanceDBCursorAdapter
from query_builder.connectors.milvus import _MilvusCursorAdapter
from query_builder.connectors.pinecone import _PineconeCursorAdapter
from query_builder.connectors.qdrant import _QdrantCursorAdapter
from query_builder.connectors.weaviate import _WeaviateCursorAdapter
from query_builder.dialects import (
    BaseDialect,
    BigtableDialect,
    ChromaDialect,
    ClickHouseDialect,
    FirestoreDialect,
    LanceDBDialect,
    MilvusDialect,
    PineconeDialect,
    PostgresDialect,
    RedisSearchDialect,
    SnowflakeDialect,
    WeaviateDialect,
)


def test_vector_connectors_params_and_limits_branches():
    # 1. Chroma with list, json string, and invalid json string
    mock_chroma_conn = MagicMock(spec=["query"])
    mock_chroma_conn.query.return_value = {
        "ids": [["c1"]],
        "documents": [["doc1"]],
        "distances": [[0.05]],
        "metadatas": [[{}]],
    }
    cur_chroma = _ChromaCursorAdapter(mock_chroma_conn)
    cur_chroma.execute("SELECT * FROM items WHERE vector_search", params=[[0.1, 0.2]])
    cur_chroma.execute(
        "SELECT * FROM items WHERE vector_search LIMIT 20",
        params=[json.dumps([0.1, 0.2])],
    )
    cur_chroma.execute(
        "SELECT * FROM items WHERE vector_search", params=["invalid-json"]
    )
    assert cur_chroma.fetchall()

    # 2. LanceDB with list, json string, invalid json string, and no limit
    mock_lance_conn = MagicMock(spec=["open_table"])
    mock_tbl = MagicMock()
    mock_search = MagicMock()
    mock_arrow = MagicMock()
    mock_field = MagicMock()
    mock_field.name = "id"
    mock_arrow.schema = [mock_field]
    mock_arrow.to_pylist.return_value = [{"id": "1"}]
    mock_search.limit.return_value.to_arrow.return_value = mock_arrow
    mock_tbl.search.return_value = mock_search
    mock_lance_conn.open_table.return_value = mock_tbl

    cur_lance = _LanceDBCursorAdapter(mock_lance_conn)
    cur_lance.execute("SELECT * FROM items LIMIT 15", params=[[0.1, 0.2]])
    cur_lance.execute("SELECT * FROM items", params=[json.dumps([0.1, 0.2])])
    cur_lance.execute("SELECT * FROM items", params=["invalid-json"])
    assert cur_lance.fetchall()

    # 3. Milvus with json string and without limit
    mock_milvus_conn = MagicMock(spec=["search"])
    hit = MagicMock()
    hit.id = 1
    hit.distance = 0.1
    hit.entity = {"name": "test"}
    mock_milvus_conn.search.return_value = [[hit]]
    cur_milvus = _MilvusCursorAdapter(mock_milvus_conn)
    cur_milvus.execute(
        "SELECT * FROM items WHERE distance", params=[json.dumps([0.1, 0.2])]
    )
    cur_milvus.execute(
        "SELECT * FROM items WHERE distance LIMIT 25", params=["invalid-json"]
    )
    assert cur_milvus.fetchall()

    # 4. Pinecone with list and without limit
    mock_pine_conn = MagicMock(spec=["query"])
    mock_pine_conn.query.return_value = {
        "matches": [{"id": "p1", "score": 0.9, "metadata": {}}]
    }
    cur_pine = _PineconeCursorAdapter(mock_pine_conn)
    cur_pine.execute("SELECT * FROM items WHERE distance", params=[[0.1, 0.2]])
    cur_pine.execute(
        "SELECT * FROM items WHERE distance LIMIT 30", params=["invalid-json"]
    )
    assert cur_pine.fetchall()

    # 5. Qdrant with json string and without limit
    mock_qdrant_conn = MagicMock(spec=["search"])
    point = MagicMock()
    point.id = "q1"
    point.score = 0.9
    point.payload = {}
    mock_qdrant_conn.search.return_value = [point]
    cur_qdrant = _QdrantCursorAdapter(mock_qdrant_conn)
    cur_qdrant.execute(
        "SELECT * FROM items WHERE distance", params=[json.dumps([0.1, 0.2])]
    )
    cur_qdrant.execute(
        "SELECT * FROM items WHERE distance LIMIT 35", params=["invalid-json"]
    )
    assert cur_qdrant.fetchall()

    # 6. Weaviate with list, json string, and without limit
    mock_weaviate_conn = MagicMock(spec=["collections"])
    col_mock = MagicMock()
    obj_mock = MagicMock()
    obj_mock.uuid = "w1"
    obj_mock.metadata.distance = 0.1
    obj_mock.properties = {"title": "Doc"}
    col_mock.query.near_vector.return_value.objects = [obj_mock]
    mock_weaviate_conn.collections.get.return_value = col_mock
    cur_weaviate = _WeaviateCursorAdapter(mock_weaviate_conn)
    cur_weaviate.execute("SELECT * FROM items WHERE distance", params=[[0.1, 0.2]])
    cur_weaviate.execute(
        "SELECT * FROM items WHERE distance LIMIT 40", params=[json.dumps([0.1, 0.2])]
    )
    cur_weaviate.execute("SELECT * FROM items WHERE distance", params=["invalid-json"])
    assert cur_weaviate.fetchall()


def test_dialects_formatting_and_fallbacks():
    # Base dialect vector and text search
    base = BaseDialect()
    assert "INNER_PRODUCT" in base.format_vector_distance("vec", metric="dot_product")
    assert base.format_text_search([]) == "1.0"

    # Postgres empty text search
    pg = PostgresDialect()
    assert pg.format_text_search([]) == "1.0"

    # Snowflake vector and empty text search
    sf = SnowflakeDialect()
    assert "VECTOR_L2_DISTANCE" in sf.format_vector_distance("vec", metric="l2")
    assert "VECTOR_INNER_PRODUCT" in sf.format_vector_distance(
        "vec", metric="inner_product"
    )
    assert sf.format_text_search([]) == "1.0"

    # ClickHouse empty text search
    ch = ClickHouseDialect()
    assert ch.format_text_search([]) == "1.0"

    # format_ilike across modern dialects
    assert "LOWER" in PineconeDialect().format_ilike("col")
    assert "LOWER" in WeaviateDialect().format_ilike("col")
    assert "LOWER" in MilvusDialect().format_ilike("col")
    assert "LOWER" in ChromaDialect().format_ilike("col")
    assert "LOWER" in LanceDBDialect().format_ilike("col")
    assert "@users" in RedisSearchDialect().quote_identifier("users.id")
    assert "col:%s%" == RedisSearchDialect().format_ilike("col")
    assert "LOWER" in FirestoreDialect().format_ilike("col")
    assert "LOWER" in BigtableDialect().format_ilike("col")

    # get_dialect exception handling
    with patch(
        "query_builder.config.get_query_builder_config", side_effect=ImportError
    ):
        d = get_dialect(None)
        assert d.name == "postgres"


def test_compiler_vector_and_hybrid_validation_branches():
    # VectorSearchSpec as object in compiler
    vs_obj = VectorSearchSpec(
        vector=[0.1, 0.2], column="embed", top_k=5, metric="cosine"
    )
    sql, params, _, _ = QueryCompiler(
        {"table": "items", "vector_search": vs_obj}
    ).compile()
    assert "SELECT" in sql

    # Invalid vector_search type
    with pytest.raises(ValidationError, match="dictionary or VectorSearchSpec"):
        QueryCompiler({"table": "items", "vector_search": 123}).compile()

    # Hybrid search validation branches
    # Unexpected fields
    with pytest.raises(ValidationError, match="Unexpected field"):
        QueryCompiler(
            {"table": "items", "hybrid_search": {"vector": [0.1], "extra_bad": 123}}
        ).compile()

    # Invalid hybrid_search type
    with pytest.raises(ValidationError, match="dictionary or HybridSearchSpec"):
        QueryCompiler({"table": "items", "hybrid_search": "bad"}).compile()

    # vector not a list
    with pytest.raises(ValidationError, match="non-empty list of numbers"):
        QueryCompiler(
            {"table": "items", "hybrid_search": {"vector": "not_list"}}
        ).compile()

    # vector contains non-numbers
    with pytest.raises(ValidationError, match="must be numbers"):
        QueryCompiler(
            {"table": "items", "hybrid_search": {"vector": ["a", "b"]}}
        ).compile()

    # query_text not string
    with pytest.raises(ValidationError, match="must be a string"):
        QueryCompiler(
            {"table": "items", "hybrid_search": {"vector": [0.1], "query_text": 123}}
        ).compile()

    # text_columns not list
    with pytest.raises(ValidationError, match="must be a list of column names"):
        QueryCompiler(
            {"table": "items", "hybrid_search": {"vector": [0.1], "text_columns": 123}}
        ).compile()

    # alpha out of bounds
    with pytest.raises(ValidationError, match="alpha"):
        QueryCompiler(
            {"table": "items", "hybrid_search": {"vector": [0.1], "alpha": 2.5}}
        ).compile()

    # invalid fusion
    with pytest.raises(ValidationError, match="fusion"):
        QueryCompiler(
            {"table": "items", "hybrid_search": {"vector": [0.1], "fusion": "invalid"}}
        ).compile()

    # invalid rrf_k
    with pytest.raises(ValidationError, match="rrf_k"):
        QueryCompiler(
            {"table": "items", "hybrid_search": {"vector": [0.1], "rrf_k": -1}}
        ).compile()

    # invalid top_k
    with pytest.raises(ValidationError, match="top_k"):
        QueryCompiler(
            {"table": "items", "hybrid_search": {"vector": [0.1], "top_k": 0}}
        ).compile()

    # invalid metric
    with pytest.raises(ValidationError, match="metric"):
        QueryCompiler(
            {"table": "items", "hybrid_search": {"vector": [0.1], "metric": "invalid"}}
        ).compile()

    # Invalid schema type passed to QueryCompiler (else branch)
    c_inv_schema = QueryCompiler({"table": "items"}, schema="not_dict_or_snapshot")
    assert c_inv_schema.tables_meta == {}

    # Custom operator returning scalar (not tuple of list)
    from query_builder.compiler import register_filter_operator

    register_filter_operator("custom_scalar", lambda col, val, d: (f"{col} @@ %s", val))
    res_custom = QueryCompiler(
        {
            "table": "items",
            "filters": [
                {"column": "name", "operator": "custom_scalar", "value": "test"}
            ],
        }
    ).compile()
    assert "test" in res_custom[1]

    # Hybrid search with include_scores=False and without order_by
    res_no_scores = QueryCompiler(
        {
            "table": "items",
            "hybrid_search": {
                "vector": [0.1, 0.2],
                "vector_column": "embed",
                "query_text": "search",
                "text_columns": ["title"],
                "include_scores": False,
            },
        }
    ).compile()
    assert "ORDER BY" in res_no_scores[0]
