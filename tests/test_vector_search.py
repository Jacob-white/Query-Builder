"""
Comprehensive Unit and Integration Tests for Vector Search Support.
===================================================================
Tests VectorSearchSpec data models, validation, SQL compiler distance operators,
pgvector, ClickHouse, Snowflake, BigQuery, SQLite, AST complexity,
connector execution (Pinecone, Qdrant, Chroma, Milvus, LanceDB, Weaviate),
CLI --vector integration, and OpenAPI microservice documentation.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from query_builder import (
    QueryCompiler,
    QuerySpec,
    ValidationError,
    VectorSearchSpec,
    calculate_ast_complexity,
    generate_openapi_spec,
)
from query_builder.cli import main as cli_main
from query_builder.connectors.chroma import _ChromaCursorAdapter
from query_builder.connectors.lancedb import _LanceDBCursorAdapter
from query_builder.connectors.milvus import _MilvusCursorAdapter
from query_builder.connectors.pinecone import _PineconeCursorAdapter
from query_builder.connectors.qdrant import _QdrantCursorAdapter
from query_builder.connectors.weaviate import _WeaviateCursorAdapter
from query_builder.dialects import (
    BigQueryDialect,
    ClickHouseDialect,
    PostgresDialect,
    SnowflakeDialect,
    SQLiteDialect,
)


class TestVectorSearchSpecModel:
    """Tests for VectorSearchSpec dataclass and validation."""

    def test_vector_search_spec_defaults(self) -> None:
        vs = VectorSearchSpec(vector=[0.1, 0.2, 0.3])
        assert vs.vector == [0.1, 0.2, 0.3]
        assert vs.column == "embedding"
        assert vs.top_k == 10
        assert vs.metric == "cosine"
        assert vs.include_distances is True
        assert vs.min_score is None

    def test_vector_search_spec_custom_fields(self) -> None:
        vs = VectorSearchSpec(
            vector=[1.0, -1.0],
            column="doc_vec",
            top_k=25,
            metric="euclidean",
            include_distances=False,
            min_score=0.75,
        )
        assert vs.column == "doc_vec"
        assert vs.top_k == 25
        assert vs.metric == "euclidean"
        assert vs.include_distances is False
        assert vs.min_score == 0.75

        d = vs.to_dict()
        assert d["vector"] == [1.0, -1.0]
        assert d["column"] == "doc_vec"
        assert d["top_k"] == 25
        assert d["metric"] == "euclidean"
        assert d["include_distances"] is False
        assert d["min_score"] == 0.75

    def test_vector_search_spec_to_dict_without_min_score(self) -> None:
        vs = VectorSearchSpec(vector=[0.5, 0.5])
        d = vs.to_dict()
        assert "min_score" not in d

    def test_vector_search_spec_invalid_vector_type(self) -> None:
        with pytest.raises(TypeError, match="must be a list or tuple"):
            VectorSearchSpec(vector="not-a-list")  # type: ignore[arg-type]

    def test_vector_search_spec_empty_vector(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            VectorSearchSpec(vector=[])

    def test_vector_search_spec_invalid_top_k(self) -> None:
        with pytest.raises(ValueError, match="must be greater than 0"):
            VectorSearchSpec(vector=[0.1], top_k=0)

    def test_vector_search_spec_invalid_metric(self) -> None:
        with pytest.raises(ValueError, match="Invalid VectorSearchSpec 'metric'"):
            VectorSearchSpec(vector=[0.1], metric="manhattan")


class TestQuerySpecIntegration:
    """Tests for QuerySpec with vector_search field."""

    def test_query_spec_with_vector_search_dataclass(self) -> None:
        vs = VectorSearchSpec(vector=[0.1, 0.2], top_k=5)
        spec = QuerySpec(table="documents", vector_search=vs)
        assert isinstance(spec.vector_search, VectorSearchSpec)
        assert spec.vector_search.top_k == 5

        d = spec.to_dict()
        assert d["table"] == "documents"
        assert d["vector_search"]["vector"] == [0.1, 0.2]
        assert d["vector_search"]["top_k"] == 5

    def test_query_spec_with_vector_search_dict(self) -> None:
        spec = QuerySpec(
            table="documents",
            vector_search={"vector": [0.3, 0.4], "metric": "dot_product"},
        )
        assert isinstance(spec.vector_search, VectorSearchSpec)
        assert spec.vector_search.metric == "dot_product"

    def test_ast_complexity_scoring(self) -> None:
        base_spec = QuerySpec(table="items", columns=["id"])
        base_score = calculate_ast_complexity(base_spec)

        vec_spec = QuerySpec(
            table="items",
            columns=["id"],
            vector_search=VectorSearchSpec(vector=[0.1, 0.2]),
        )
        vec_score = calculate_ast_complexity(vec_spec)
        assert vec_score == base_score + 5


class TestDialectVectorFormatting:
    """Tests for dialect-specific vector distance expressions."""

    def test_postgres_pgvector_operators(self) -> None:
        pg = PostgresDialect()
        # Cosine distance
        assert pg.format_vector_distance('t1."embedding"', metric="cosine") == '(t1."embedding" <=> %s)'
        # Euclidean / L2
        assert pg.format_vector_distance('t1."embedding"', metric="euclidean") == '(t1."embedding" <-> %s)'
        assert pg.format_vector_distance('t1."embedding"', metric="l2") == '(t1."embedding" <-> %s)'
        # Dot product / Inner product
        assert pg.format_vector_distance('t1."embedding"', metric="dot_product") == '(t1."embedding" <#> %s)'
        assert pg.format_vector_distance('t1."embedding"', metric="inner_product") == '(t1."embedding" <#> %s)'

    def test_clickhouse_vector_functions(self) -> None:
        ch = ClickHouseDialect()
        assert ch.format_vector_distance("`embedding`", metric="cosine") == "cosineDistance(`embedding`, %s)"
        assert ch.format_vector_distance("`embedding`", metric="euclidean") == "L2Distance(`embedding`, %s)"
        assert ch.format_vector_distance("`embedding`", metric="dot_product") == "dotProduct(`embedding`, %s)"

    def test_snowflake_vector_functions(self) -> None:
        sf = SnowflakeDialect()
        assert "VECTOR_COSINE_SIMILARITY" in sf.format_vector_distance('"embedding"', metric="cosine")
        assert "VECTOR_L2_DISTANCE" in sf.format_vector_distance('"embedding"', metric="euclidean")
        assert "VECTOR_INNER_PRODUCT" in sf.format_vector_distance('"embedding"', metric="dot_product")

    def test_bigquery_vector_functions(self) -> None:
        bq = BigQueryDialect()
        assert "COSINE_DISTANCE" in bq.format_vector_distance("`embedding`", metric="cosine")
        assert "EUCLIDEAN_DISTANCE" in bq.format_vector_distance("`embedding`", metric="euclidean")
        assert "DOT_PRODUCT" in bq.format_vector_distance("`embedding`", metric="dot_product")

    def test_generic_sqlite_fallback(self) -> None:
        sq = SQLiteDialect()
        assert sq.placeholder == "?"
        assert sq.format_vector_distance('"embedding"', metric="cosine") == 'COSINE_DISTANCE("embedding", ?)'
        assert sq.format_vector_distance('"embedding"', metric="euclidean") == 'L2_DISTANCE("embedding", ?)'


class TestQueryCompilerVectorSearch:
    """Tests for QueryCompiler compiling queries with VectorSearchSpec."""

    def test_postgres_pgvector_query_compilation(self) -> None:
        spec = {
            "table": "articles",
            "columns": ["id", "title"],
            "vector_search": {
                "vector": [0.1, 0.2, 0.3],
                "column": "embedding",
                "top_k": 5,
                "metric": "cosine",
            },
        }
        compiler = QueryCompiler(spec, dialect="postgres")
        sql, params, _, _ = compiler.compile()

        # Check distance projection
        assert '("t1"."embedding" <=> %s) AS "_distance"' in sql
        # Check ordering
        assert 'ORDER BY "_distance" ASC' in sql
        # Check limit
        assert "LIMIT %s OFFSET %s" in sql
        # Check params: vector string followed by limit 5 and offset 0
        assert params[0] == str([0.1, 0.2, 0.3])
        assert params[1] == 5
        assert params[2] == 0

    def test_clickhouse_vector_query_compilation(self) -> None:
        spec = {
            "table": "products",
            "columns": ["id", "name"],
            "vector_search": {
                "vector": [0.5, -0.5],
                "column": "features",
                "top_k": 8,
                "metric": "euclidean",
            },
        }
        compiler = QueryCompiler(spec, dialect="clickhouse")
        sql, params, _, _ = compiler.compile()

        assert "L2Distance(`t1`.`features`, %s) AS `_distance`" in sql
        assert "ORDER BY `_distance` ASC" in sql
        assert params[0] == str([0.5, -0.5])
        assert params[1] == 8

    def test_vector_search_with_where_filters(self) -> None:
        spec = {
            "table": "docs",
            "columns": ["id", "category"],
            "filters": [{"column": "category", "op": "eq", "value": "finance"}],
            "vector_search": {
                "vector": [1.0, 0.0],
                "top_k": 3,
            },
        }
        compiler = QueryCompiler(spec, dialect="postgres")
        sql, params, _, _ = compiler.compile()

        assert 'WHERE ("t1"."category" = %s)' in sql
        assert '("t1"."embedding" <=> %s) AS "_distance"' in sql
        assert 'ORDER BY "_distance" ASC' in sql
        # Params: vector param, then category filter, then limit & offset
        assert params[0] == str([1.0, 0.0])
        assert params[1] == "finance"
        assert params[2] == 3
        assert params[3] == 0

    def test_vector_search_with_min_score_filter(self) -> None:
        spec = {
            "table": "items",
            "columns": ["id"],
            "vector_search": {
                "vector": [0.2, 0.4],
                "min_score": 0.8,
            },
        }
        compiler = QueryCompiler(spec, dialect="postgres")
        sql, params, _, _ = compiler.compile()

        assert 'WHERE ("t1"."embedding" <=> %s) <= %s' in sql
        assert params[0] == str([0.2, 0.4])
        assert params[1] == str([0.2, 0.4])
        assert params[2] == 0.8

    def test_vector_search_without_include_distances(self) -> None:
        spec = {
            "table": "items",
            "columns": ["id"],
            "vector_search": {
                "vector": [0.1, 0.2],
                "include_distances": False,
            },
        }
        compiler = QueryCompiler(spec, dialect="postgres")
        sql, params, _, _ = compiler.compile()

        assert '"_distance"' not in sql
        assert 'ORDER BY ("t1"."embedding" <=> %s) ASC' in sql
        assert params[0] == str([0.1, 0.2])

    def test_vector_search_custom_order_by_override(self) -> None:
        spec = {
            "table": "items",
            "columns": ["id", "rating"],
            "order_by": [{"column": "rating", "direction": "desc"}],
            "vector_search": {
                "vector": [0.1, 0.2],
            },
        }
        compiler = QueryCompiler(spec, dialect="postgres")
        sql, _, _, _ = compiler.compile()

        assert 'ORDER BY "t1"."rating" DESC' in sql

    def test_vector_search_validation_errors(self) -> None:
        # Empty vector
        with pytest.raises(ValidationError, match="non-empty list of numbers"):
            QueryCompiler({"table": "items", "vector_search": {"vector": []}}).compile()

        # Non-numeric vector elements
        with pytest.raises(ValidationError, match="must be numbers"):
            QueryCompiler(
                {"table": "items", "vector_search": {"vector": ["a", "b"]}}
            ).compile()

        # Negative top_k
        with pytest.raises(ValidationError, match="between 1 and"):
            QueryCompiler(
                {"table": "items", "vector_search": {"vector": [0.1], "top_k": -5}}
            ).compile()

        # Invalid metric
        with pytest.raises(ValidationError, match="Invalid vector_search 'metric'"):
            QueryCompiler(
                {"table": "items", "vector_search": {"vector": [0.1], "metric": "invalid"}}
            ).compile()

        # Invalid min_score type
        with pytest.raises(ValidationError, match="must be a number"):
            QueryCompiler(
                {"table": "items", "vector_search": {"vector": [0.1], "min_score": "high"}}
            ).compile()

        # Unknown field in vector_search
        with pytest.raises(ValidationError, match="Unexpected field"):
            QueryCompiler(
                {"table": "items", "vector_search": {"vector": [0.1], "extra_bad": 123}}
            ).compile()


class TestVectorConnectorsExecution:
    """Tests execution of vector search on vector connectors and cursor adapters."""

    def test_pinecone_adapter_with_vector_search(self) -> None:
        mock_conn = MagicMock(spec=["query"])
        mock_conn.query.return_value = {
            "matches": [
                {"id": "doc_1", "score": 0.95, "metadata": {"title": "Doc 1"}},
                {"id": "doc_2", "score": 0.88, "metadata": {"title": "Doc 2"}},
            ]
        }
        adapter = _PineconeCursorAdapter(mock_conn)
        adapter.execute(
            'SELECT "t1"."id", ("t1"."embedding" <=> %s) AS "_distance" FROM "articles" "t1" LIMIT 5',
            params=[json.dumps([0.1, 0.2]), 5, 0],
        )
        assert adapter.description == [("id",), ("score",), ("metadata",)]
        rows = adapter.fetchall()
        assert len(rows) == 2
        assert rows[0][0] == "doc_1"
        assert rows[0][1] == 0.95

    def test_qdrant_adapter_with_vector_search(self) -> None:
        mock_conn = MagicMock(spec=["search"])
        p1 = MagicMock()
        p1.id = "p1"
        p1.score = 0.92
        p1.payload = {"name": "Item 1"}
        mock_conn.search.return_value = [p1]

        adapter = _QdrantCursorAdapter(mock_conn)
        adapter.execute(
            'SELECT * FROM "vectors" ORDER BY "_distance" ASC LIMIT 10',
            params=[[0.1, 0.2, 0.3]],
        )
        mock_conn.search.assert_called_once()
        assert adapter.description == [("id",), ("score",), ("payload",)]
        assert adapter.fetchall() == [["p1", 0.92, {"name": "Item 1"}]]

    def test_chroma_adapter_with_vector_search(self) -> None:
        mock_conn = MagicMock(spec=["query"])
        mock_conn.query.return_value = {
            "ids": [["c1"]],
            "documents": [["hello chroma"]],
            "distances": [[0.12]],
            "metadatas": [[{"tag": "ai"}]],
        }
        adapter = _ChromaCursorAdapter(mock_conn)
        adapter.execute(
            'SELECT * FROM "collection" ORDER BY "_distance" ASC LIMIT 5',
            params=[json.dumps([0.1, 0.2])],
        )
        mock_conn.query.assert_called_once()
        assert adapter.description == [
            ("id",),
            ("document",),
            ("distance",),
            ("metadata",),
        ]
        assert adapter.fetchall() == [["c1", "hello chroma", 0.12, {"tag": "ai"}]]

    def test_milvus_adapter_with_vector_search(self) -> None:
        mock_conn = MagicMock(spec=["search"])
        hit = MagicMock()
        hit.id = 1001
        hit.distance = 0.05
        hit.entity = {"name": "Milvus Vector"}
        mock_conn.search.return_value = [[hit]]

        adapter = _MilvusCursorAdapter(mock_conn)
        adapter.execute(
            'SELECT * FROM "entities" WHERE ("distance" < 0.1) LIMIT 10',
            params=[[0.1, 0.2]],
        )
        mock_conn.search.assert_called_once()
        assert adapter.description == [("id",), ("distance",), ("entity",)]
        assert adapter.fetchall() == [[1001, 0.05, {"name": "Milvus Vector"}]]

    def test_lancedb_adapter_with_vector_search(self) -> None:
        mock_conn = MagicMock(spec=["open_table"])
        mock_tbl = MagicMock()
        mock_search = MagicMock()
        mock_arrow = MagicMock()
        field_a = MagicMock()
        field_a.name = "id"
        mock_arrow.schema = [field_a]
        mock_arrow.to_pylist.return_value = [{"id": "vec-1"}]
        mock_search.limit.return_value.to_arrow.return_value = mock_arrow
        mock_tbl.search.return_value = mock_search
        mock_conn.open_table.return_value = mock_tbl

        adapter = _LanceDBCursorAdapter(mock_conn)
        adapter.execute(
            'SELECT * FROM "vectors" LIMIT 5',
            params=[[0.1, 0.2]],
        )
        mock_tbl.search.assert_called_with([0.1, 0.2])
        assert adapter.description == [("id",)]
        assert adapter.fetchall() == [["vec-1"]]

    def test_weaviate_adapter_with_vector_search(self) -> None:
        mock_conn = MagicMock(spec=["collections"])
        mock_coll = MagicMock()
        mock_obj = MagicMock()
        mock_obj.uuid = "1234-uuid"
        mock_obj.properties = {"title": "Weaviate Article"}
        mock_obj.metadata = {"certainty": 0.98}
        mock_coll.query.near_vector.return_value.objects = [mock_obj]
        mock_conn.collections.get.return_value = mock_coll

        adapter = _WeaviateCursorAdapter(mock_conn)
        adapter.execute(
            'SELECT * FROM "articles" WHERE ("vector_search" = true)',
            params=[[0.1, 0.2, 0.3]],
        )
        mock_coll.query.near_vector.assert_called_once()
        assert adapter.description == [("uuid",), ("properties",), ("metadata",)]
        assert adapter.fetchall() == [
            ["1234-uuid", {"title": "Weaviate Article"}, {"certainty": 0.98}]
        ]


class TestCLIAndOpenAPIIntegration:
    """Tests CLI vector arguments and server OpenAPI documentation."""

    def test_openapi_schema_contains_vector_search(self) -> None:
        spec = generate_openapi_spec()
        assert "components" in spec
        assert "schemas" in spec["components"]
        assert "VectorSearchSpec" in spec["components"]["schemas"]
        vs_schema = spec["components"]["schemas"]["VectorSearchSpec"]
        assert "vector" in vs_schema["properties"]
        assert "metric" in vs_schema["properties"]
        assert "top_k" in vs_schema["properties"]

    def test_cli_compile_with_vector_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        spec_json = json.dumps({"table": "articles", "columns": ["id"]})
        exit_code = cli_main(
            ["compile", "--spec", spec_json, "--vector", "0.1,0.2,0.3", "--top-k", "7", "--json"]
        )
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert '("t1"."embedding" <=> %s) AS "_distance"' in data["main_sql"]
        assert data["params"][0] == str([0.1, 0.2, 0.3])
        assert data["params"][1] == 7
