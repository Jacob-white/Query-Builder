"""Vector database and vector-search engine dialects."""

from __future__ import annotations

from typing import Any

from query_builder.dialects.base import (
    BaseDialect,
    _validate_identifier,
)


class QdrantDialect(BaseDialect):
    """Qdrant vector search engine filter dialect."""

    name: str = "qdrant"
    placeholder: str = "%s"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"
    introspects_keys: bool = False

    def inspect_tables_query(
        self, schema_name: str = "default"
    ) -> tuple[str, list[Any]]:
        return "GET /collections", []

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return f"GET /collections/{table_name}", []
        return "GET /collections", []


class PineconeDialect(BaseDialect):
    """Pinecone managed vector database dialect."""

    name: str = "pinecone"
    placeholder: str = "%s"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"
    introspects_keys: bool = False

    def inspect_tables_query(
        self, schema_name: str = "default"
    ) -> tuple[str, list[Any]]:
        return "list_indexes", []

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return f"describe_index:{table_name}", []
        return "list_indexes", []


class WeaviateDialect(BaseDialect):
    """Weaviate modular vector database and knowledge graph dialect."""

    name: str = "weaviate"
    placeholder: str = "%s"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"
    introspects_keys: bool = False

    def inspect_tables_query(
        self, schema_name: str = "default"
    ) -> tuple[str, list[Any]]:
        return "collections.list_all", []

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return f"collections.get:{table_name}", []
        return "collections.list_all", []


class MilvusDialect(BaseDialect):
    """Milvus distributed cloud-native vector database dialect."""

    name: str = "milvus"
    placeholder: str = "%s"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"
    introspects_keys: bool = False

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def inspect_tables_query(
        self, schema_name: str = "default"
    ) -> tuple[str, list[Any]]:
        return "list_collections", []

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return f"describe_collection:{table_name}", []
        return "list_collections", []


class ChromaDialect(BaseDialect):
    """ChromaDB embedded and server AI vector database dialect."""

    name: str = "chroma"
    placeholder: str = "%s"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"
    introspects_keys: bool = False

    def inspect_tables_query(
        self, schema_name: str = "default"
    ) -> tuple[str, list[Any]]:
        return "list_collections", []

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return f"get_collection:{table_name}", []
        return "list_collections", []


class LanceDBDialect(BaseDialect):
    """LanceDB Apache Arrow-backed columnar vector database dialect."""

    name: str = "lancedb"
    placeholder: str = "?"
    ilike_template: str = "LOWER({col}) LIKE LOWER(?)"
    introspects_keys: bool = False

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return "LIMIT ? OFFSET ?", [limit, offset]

    def inspect_tables_query(
        self, schema_name: str = "default"
    ) -> tuple[str, list[Any]]:
        return "table_names", []

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return f"schema:{table_name}", []
        return "table_names", []


class RedisSearchDialect(BaseDialect):
    """Redis RediSearch secondary index query dialect."""

    name: str = "redis"
    placeholder: str = "%s"
    ilike_template: str = "{col}:{ph}%"
    introspects_keys: bool = False

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"@{part}" for part in parts)

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder} {self.placeholder}", [offset, limit]

    def inspect_tables_query(
        self, schema_name: str = "default"
    ) -> tuple[str, list[Any]]:
        return "FT._LIST", []

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return f"FT.INFO {table_name}", []
        return "FT._LIST", []
