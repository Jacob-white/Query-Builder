"""
Unit and Integration Tests for Hybrid Search & Reciprocal Rank Fusion (RRF).
=============================================================================
Tests HybridSearchSpec data model, validation, QuerySpec integration,
serialization, RRF / Linear fusion algorithms, SQL compiler dialects,
and connector query execution.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from query_builder import (
    HybridSearchSpec,
    QueryCompiler,
    QuerySpec,
    calculate_ast_complexity,
    linear_combination_fusion,
    reciprocal_rank_fusion,
)
from query_builder.connectors.chroma import _ChromaCursorAdapter
from query_builder.connectors.milvus import _MilvusCursorAdapter
from query_builder.connectors.qdrant import _QdrantCursorAdapter
from query_builder.connectors.weaviate import _WeaviateCursorAdapter
from query_builder.dialects import (
    ClickHouseDialect,
    PostgresDialect,
    SnowflakeDialect,
)


class TestHybridSearchSpecModel:
    """Tests for HybridSearchSpec dataclass and validation."""

    def test_hybrid_search_spec_defaults(self) -> None:
        hs = HybridSearchSpec(vector=[0.1, 0.2, 0.3])
        assert hs.vector == [0.1, 0.2, 0.3]
        assert hs.vector_column == "embedding"
        assert hs.query_text == ""
        assert hs.text_columns == []
        assert hs.alpha == 0.5
        assert hs.fusion == "rrf"
        assert hs.rrf_k == 60
        assert hs.top_k == 10
        assert hs.metric == "cosine"
        assert hs.include_scores is True

    def test_hybrid_search_spec_custom_fields(self) -> None:
        hs = HybridSearchSpec(
            vector=[1.0, -1.0],
            vector_column="doc_embedding",
            query_text="semantic database optimization",
            text_columns=["title", "summary"],
            alpha=0.8,
            fusion="linear",
            rrf_k=50,
            top_k=20,
            metric="l2",
            include_scores=False,
        )
        assert hs.vector == [1.0, -1.0]
        assert hs.vector_column == "doc_embedding"
        assert hs.query_text == "semantic database optimization"
        assert hs.text_columns == ["title", "summary"]
        assert hs.alpha == 0.8
        assert hs.fusion == "linear"
        assert hs.rrf_k == 50
        assert hs.top_k == 20
        assert hs.metric == "l2"
        assert hs.include_scores is False

    def test_hybrid_search_spec_to_dict(self) -> None:
        hs = HybridSearchSpec(
            vector=[0.5, 0.5],
            vector_column="vec",
            query_text="indexing",
            text_columns=["content"],
            alpha=0.3,
            fusion="rrf",
            rrf_k=60,
            top_k=5,
        )
        d = hs.to_dict()
        assert d == {
            "vector": [0.5, 0.5],
            "vector_column": "vec",
            "query_text": "indexing",
            "text_columns": ["content"],
            "alpha": 0.3,
            "fusion": "rrf",
            "rrf_k": 60,
            "top_k": 5,
            "metric": "cosine",
            "include_scores": True,
        }

    def test_hybrid_search_validation_empty_vector(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            HybridSearchSpec(vector=[])

    def test_hybrid_search_validation_invalid_vector_type(self) -> None:
        with pytest.raises(TypeError, match="must be a list or tuple"):
            HybridSearchSpec(vector="invalid")  # type: ignore

    def test_hybrid_search_validation_invalid_alpha(self) -> None:
        with pytest.raises(ValueError, match="alpha"):
            HybridSearchSpec(vector=[0.1], alpha=1.5)
        with pytest.raises(ValueError, match="alpha"):
            HybridSearchSpec(vector=[0.1], alpha=-0.1)

    def test_hybrid_search_validation_invalid_fusion(self) -> None:
        with pytest.raises(ValueError, match="fusion"):
            HybridSearchSpec(vector=[0.1], fusion="invalid_algo")

    def test_hybrid_search_validation_invalid_rrf_k(self) -> None:
        with pytest.raises(ValueError, match="rrf_k"):
            HybridSearchSpec(vector=[0.1], rrf_k=0)

    def test_hybrid_search_validation_invalid_top_k(self) -> None:
        with pytest.raises(ValueError, match="top_k"):
            HybridSearchSpec(vector=[0.1], top_k=-1)

    def test_hybrid_search_validation_invalid_metric(self) -> None:
        with pytest.raises(ValueError, match="metric"):
            HybridSearchSpec(vector=[0.1], metric="manhattan")

    def test_query_spec_hybrid_search_integration(self) -> None:
        spec = QuerySpec(
            table="documents",
            columns=["id", "title"],
            hybrid_search={
                "vector": [0.1, 0.2],
                "vector_column": "embedding",
                "query_text": "cloud storage",
                "text_columns": ["title"],
                "alpha": 0.6,
                "fusion": "rrf",
            },
        )
        assert isinstance(spec.hybrid_search, HybridSearchSpec)
        assert spec.hybrid_search.vector == [0.1, 0.2]
        assert spec.hybrid_search.alpha == 0.6
        d = spec.to_dict()
        assert "hybrid_search" in d
        assert d["hybrid_search"]["query_text"] == "cloud storage"


class TestFusionAlgorithms:
    """Tests for Reciprocal Rank Fusion (RRF) and Linear Combination fusion."""

    def test_rrf_merges_two_ranked_lists(self) -> None:
        dense = [
            {"id": "doc1", "title": "First Dense"},
            {"id": "doc2", "title": "Second Dense"},
            {"id": "doc3", "title": "Third Dense"},
        ]
        sparse = [
            {"id": "doc2", "title": "First Sparse"},
            {"id": "doc4", "title": "Second Sparse"},
            {"id": "doc1", "title": "Third Sparse"},
        ]

        fused = reciprocal_rank_fusion(dense, sparse, key="id", rrf_k=60, top_k=10)
        assert len(fused) == 4
        # doc2 ranked #2 in dense and #1 in sparse: 1/(60+2) + 1/(60+1) = 0.016129 + 0.016393 = ~0.0325
        # doc1 ranked #1 in dense and #3 in sparse: 1/(60+1) + 1/(60+3) = 0.016393 + 0.015873 = ~0.0322
        # doc2 should be ranked #1
        assert fused[0]["id"] == "doc2"
        assert fused[1]["id"] == "doc1"
        assert "_score" in fused[0]
        assert fused[0]["_score"] > fused[1]["_score"]

    def test_rrf_truncates_to_top_k(self) -> None:
        dense = [{"id": f"doc_{i}"} for i in range(20)]
        sparse = [{"id": f"doc_{i + 10}"} for i in range(20)]

        fused = reciprocal_rank_fusion(dense, sparse, key="id", top_k=5)
        assert len(fused) == 5

    def test_rrf_handles_empty_lists(self) -> None:
        assert reciprocal_rank_fusion([], [], key="id") == []
        one_side = reciprocal_rank_fusion([{"id": "d1"}], [], key="id")
        assert len(one_side) == 1
        assert one_side[0]["id"] == "d1"

    def test_linear_combination_fusion_balanced(self) -> None:
        dense = [
            {"id": "doc1", "_score": 0.9},
            {"id": "doc2", "_score": 0.5},
        ]
        sparse = [
            {"id": "doc2", "_score": 10.0},
            {"id": "doc1", "_score": 2.0},
        ]

        fused = linear_combination_fusion(dense, sparse, key="id", alpha=0.5, top_k=2)
        assert len(fused) == 2
        # doc1 dense norm = 1.0, sparse norm = 0.0 -> score = 0.5
        # doc2 dense norm = 0.0, sparse norm = 1.0 -> score = 0.5
        # both have normalized scores
        assert "_score" in fused[0]
        assert fused[0]["_score"] >= 0.0

    def test_linear_combination_fusion_pure_vector(self) -> None:
        dense = [{"id": "d1", "_score": 1.0}, {"id": "d2", "_score": 0.1}]
        sparse = [{"id": "d2", "_score": 100.0}, {"id": "d1", "_score": 0.0}]

        fused = linear_combination_fusion(dense, sparse, key="id", alpha=1.0)
        assert fused[0]["id"] == "d1"

    def test_linear_combination_fusion_disjoint_results(self) -> None:
        dense = [{"id": "d1", "title": "Dense Only", "_score": 0.9}]
        sparse = [{"id": "d2", "summary": "Sparse Only", "_score": 10.0}]

        fused = linear_combination_fusion(dense, sparse, key="id", alpha=0.5)
        assert len(fused) == 2
        ids = {doc["id"] for doc in fused}
        assert ids == {"d1", "d2"}

    def test_linear_combination_fusion_duplicate_dense_doc_id(self) -> None:
        dense = [
            {"id": "d1", "title": "Version 1", "_score": 0.9},
            {"id": "d1", "title": "Version 2", "_score": 0.8},
        ]
        sparse = [{"id": "d1", "summary": "Sparse", "_score": 5.0}]

        fused = linear_combination_fusion(dense, sparse, key="id", alpha=0.5)
        assert len(fused) == 1
        assert fused[0]["id"] == "d1"


class TestHybridSearchCompiler:
    """Tests for SQL compilation of HybridSearchSpec across dialects."""

    def test_postgres_hybrid_search_rrf_compilation(self) -> None:
        spec = QuerySpec(
            table="articles",
            columns=["id", "title"],
            hybrid_search=HybridSearchSpec(
                vector=[0.1, 0.2, 0.3],
                vector_column="embedding",
                query_text="database scaling",
                text_columns=["title", "content"],
                fusion="rrf",
                rrf_k=60,
                top_k=7,
            ),
        )

        compiler = QueryCompiler(spec, dialect=PostgresDialect())
        sql, params, _, _ = compiler.compile()

        # Check projections
        assert '"_score"' in sql
        assert 'DENSE_RANK() OVER (ORDER BY ("t1"."embedding" <=> %s) ASC)' in sql
        assert "ts_rank_cd(to_tsvector('english'" in sql
        # Check ordering and limit
        assert 'ORDER BY "_score" DESC' in sql
        assert "LIMIT %s OFFSET %s" in sql
        # Parameters: vector param, query_text param, limit, offset
        assert len(params) == 4
        assert params[0] == "[0.1, 0.2, 0.3]"
        assert params[1] == "%database scaling%"
        assert params[2] == 7
        assert params[3] == 0

    def test_postgres_hybrid_search_linear_compilation(self) -> None:
        spec = QuerySpec(
            table="articles",
            columns=["id"],
            hybrid_search=HybridSearchSpec(
                vector=[0.5, 0.5],
                vector_column="embedding",
                query_text="distributed search",
                text_columns=["body"],
                fusion="linear",
                alpha=0.7,
                top_k=15,
            ),
        )

        compiler = QueryCompiler(spec, dialect=PostgresDialect())
        sql, params, _, _ = compiler.compile()

        assert '0.7 * (1.0 / (1.0 + ("t1"."embedding" <=> %s)))' in sql
        assert "0.3 * (ts_rank_cd" in sql
        assert 'ORDER BY "_score" DESC' in sql
        assert params[0] == "[0.5, 0.5]"
        assert params[1] == "%distributed search%"

    def test_clickhouse_hybrid_search_compilation(self) -> None:
        spec = QuerySpec(
            table="logs",
            columns=["log_id"],
            hybrid_search=HybridSearchSpec(
                vector=[1.0, 2.0],
                vector_column="vec",
                query_text="timeout error",
                text_columns=["message"],
                fusion="linear",
                alpha=0.6,
                top_k=10,
            ),
        )

        compiler = QueryCompiler(spec, dialect=ClickHouseDialect())
        sql, _params, _, _ = compiler.compile()

        assert "cosineDistance(`t1`.`vec`, %s)" in sql
        assert "positionCaseInsensitive(`t1`.`message`, %s)" in sql
        assert "ORDER BY `_score` DESC" in sql

    def test_snowflake_hybrid_search_compilation(self) -> None:
        spec = QuerySpec(
            table="items",
            columns=["item_id"],
            hybrid_search=HybridSearchSpec(
                vector=[0.1, 0.2],
                vector_column="v",
                query_text="boots",
                text_columns=["description"],
                fusion="linear",
                alpha=0.5,
                top_k=5,
            ),
        )

        compiler = QueryCompiler(spec, dialect=SnowflakeDialect())
        sql, _params, _, _ = compiler.compile()

        assert 'VECTOR_COSINE_SIMILARITY("t1"."v", %s)' in sql
        assert 'CONTAINS(LOWER("t1"."description"), LOWER(%s))' in sql


class TestHybridSearchSecurityAndConnectors:
    """Tests for AST security complexity and connector dispatch for hybrid search."""

    def test_ast_complexity_hybrid_search_score(self) -> None:
        base_spec = QuerySpec(table="docs", columns=["id"])
        base_score = calculate_ast_complexity(base_spec)

        hybrid_spec = QuerySpec(
            table="docs",
            columns=["id"],
            hybrid_search=HybridSearchSpec(
                vector=[0.1, 0.2],
                query_text="search",
                text_columns=["title"],
            ),
        )
        hybrid_score = calculate_ast_complexity(hybrid_spec)
        assert hybrid_score == base_score + 8

    def test_qdrant_hybrid_score_query_dispatch(self) -> None:
        mock_conn = MagicMock(spec=["search"])
        mock_point = MagicMock()
        mock_point.id = "point_123"
        mock_point.score = 0.98
        mock_point.payload = {"text": "hybrid match"}
        mock_conn.search.return_value = [mock_point]

        cursor = _QdrantCursorAdapter(mock_conn)
        sql = 'SELECT id, title, _score FROM "articles" ORDER BY "_score" DESC LIMIT 5;'
        params = [json.dumps([0.1, 0.2, 0.3]), "%search%"]

        cursor.execute(sql, params)
        mock_conn.search.assert_called_once()
        assert cursor.fetchall() == [["point_123", 0.98, {"text": "hybrid match"}]]

    def test_chroma_hybrid_score_query_dispatch(self) -> None:
        mock_conn = MagicMock(spec=["query"])
        mock_conn.query.return_value = {
            "ids": [["c1"]],
            "documents": [["doc text"]],
            "distances": [[0.05]],
            "metadatas": [[{"title": "doc"}]],
        }

        cursor = _ChromaCursorAdapter(mock_conn)
        sql = 'SELECT id, _score FROM "docs" ORDER BY "_score" DESC LIMIT 5;'
        params = [json.dumps([0.1, 0.2]), "%keyword%"]

        cursor.execute(sql, params)
        mock_conn.query.assert_called_once()
        assert cursor.fetchall() == [["c1", "doc text", 0.05, {"title": "doc"}]]

    def test_milvus_hybrid_score_query_dispatch(self) -> None:
        mock_conn = MagicMock(spec=["search"])
        mock_hit = MagicMock()
        mock_hit.id = 999
        mock_hit.distance = 0.12
        mock_hit.entity = {"name": "entity1"}
        mock_conn.search.return_value = [[mock_hit]]

        cursor = _MilvusCursorAdapter(mock_conn)
        sql = 'SELECT id, _score FROM "items" ORDER BY "_score" DESC LIMIT 10;'
        params = [json.dumps([0.4, 0.5]), "%keyword%"]

        cursor.execute(sql, params)
        mock_conn.search.assert_called_once()
        assert cursor.fetchall() == [[999, 0.12, {"name": "entity1"}]]

    def test_weaviate_hybrid_score_query_dispatch(self) -> None:
        mock_conn = MagicMock(spec=["collections"])
        mock_coll = MagicMock()
        mock_obj = MagicMock()
        mock_obj.uuid = "weav_id"
        mock_obj.properties = {"title": "weaviate doc"}
        mock_obj.metadata = {"certainty": 0.98}
        mock_coll.query.near_vector.return_value.objects = [mock_obj]
        mock_conn.collections.get.return_value = mock_coll

        cursor = _WeaviateCursorAdapter(mock_conn)
        sql = 'SELECT id, _score FROM "weav_docs" ORDER BY "_score" DESC LIMIT 5;'
        params = [json.dumps([0.1, 0.2]), "%keyword%"]

        cursor.execute(sql, params)
        mock_coll.query.near_vector.assert_called_once()
        assert cursor.fetchall() == [
            ["weav_id", {"title": "weaviate doc"}, {"certainty": 0.98}]
        ]


def test_fusion_edge_cases():
    from query_builder.fusion import linear_combination_fusion, reciprocal_rank_fusion

    # 1. rrf_k <= 0 fallback
    res = reciprocal_rank_fusion([{"id": 1}], [{"id": 2}], rrf_k=0)
    assert len(res) == 2

    # 2. items without "id" key
    item_a = {"title": "No ID 1"}
    item_b = {"title": "No ID 2"}
    res_no_id = reciprocal_rank_fusion([item_a], [item_b])
    assert len(res_no_id) == 2

    # 3. Duplicate items in dense/sparse
    item_dup = {"id": 1, "title": "First"}
    item_dup2 = {"id": 1, "extra": "Val"}
    res_dup = reciprocal_rank_fusion([item_dup, item_dup2], [{"id": 1}])
    assert len(res_dup) == 1
    assert res_dup[0]["extra"] == "Val"

    # 4. linear_combination_fusion edge cases
    # Single item (max_v == min_v)
    lin_single = linear_combination_fusion(
        [{"id": 1, "score": 5.0}],
        [{"id": 1, "score": 10.0}],
        dense_score_key="score",
        sparse_score_key="score",
    )
    assert len(lin_single) == 1
    assert lin_single[0]["_score"] == 1.0

    # Invalid score values
    lin_inv = linear_combination_fusion(
        [{"id": 1, "score": "invalid"}],
        [{"id": 1, "score": 2.0}],
        dense_score_key="score",
        sparse_score_key="score",
    )
    assert len(lin_inv) == 1

    # Duplicate item across dense and sparse updating doc_map
    lin_dup = linear_combination_fusion(
        [{"id": 1, "score": 5.0, "dense": True}],
        [{"id": 1, "score": 10.0, "sparse": True}],
        dense_score_key="score",
        sparse_score_key="score",
    )
    assert len(lin_dup) == 1
    assert lin_dup[0]["dense"] is True
    assert lin_dup[0]["sparse"] is True

    # Empty inputs
    assert linear_combination_fusion([], []) == []
