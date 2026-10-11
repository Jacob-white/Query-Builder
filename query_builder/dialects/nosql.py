"""Document, wide-column, search, key-value and graph store dialects."""

from __future__ import annotations

import re
from typing import Any

from query_builder.dialects.base import (
    BaseDialect,
    _validate_alias,
    _validate_identifier,
)
from query_builder.exceptions import DialectError


class ElasticsearchDialect(BaseDialect):
    """Elasticsearch / OpenSearch SQL dialect."""

    name: str = "elasticsearch"
    placeholder: str = "?"  # the /_sql endpoint binds positional `?` parameters
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        # Elasticsearch SQL has no OFFSET and cannot bind LIMIT: inline the
        # (int-coerced) row count and refuse a skip it cannot honour.
        if int(offset) > 0:
            raise DialectError(
                "Elasticsearch SQL does not support OFFSET; page with a cursor instead."
            )
        return f"LIMIT {int(limit)}", []


class DynamoDBPartiQLDialect(BaseDialect):
    """Amazon DynamoDB PartiQL dialect."""

    name: str = "dynamodb"
    placeholder: str = "?"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder}", [limit]


class CouchbaseDialect(BaseDialect):
    """Couchbase SQL++ / N1QL dialect using backtick quoting."""

    name: str = "couchbase"
    placeholder: str = "?"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        _validate_alias(alias_name)
        cleaned = alias_name.replace("`", "``")
        return f"`{cleaned}`"


class MongoDBSQLDialect(BaseDialect):
    """MongoDB Atlas SQL interface dialect."""

    name: str = "mongodb"
    placeholder: str = "?"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"
    supports_table_aliases: bool = False

    def quote_identifier(self, ident: str) -> str:
        # pymongosql reads a double-quoted or backticked identifier as a string literal and
        # returns NULL for every row, so identifiers are emitted bare. They are validated
        # against the identifier whitelist first, so nothing unsafe can reach the SQL text.
        _validate_identifier(ident)
        return ident

    def quote_alias(self, alias_name: str) -> str:
        # pymongosql keeps the quotes in the result column name (`"name"`), so a plain
        # alias is emitted bare; anything else falls back to standard quoting.
        _validate_alias(alias_name)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias_name):
            return alias_name
        return super().quote_alias(alias_name)

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        # pymongosql cannot bind LIMIT/OFFSET (`Invalid LIMIT value '?'`) and then
        # silently returns no rows: inline the int-coerced values.
        clause = f"LIMIT {int(limit)}"
        if int(offset) > 0:
            clause += f" OFFSET {int(offset)}"
        return clause, []


class ScyllaDBDialect(BaseDialect):
    """ScyllaDB and Apache Cassandra CQL dialect."""

    name: str = "scylladb"
    placeholder: str = "%s"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder}", [limit]

    def inspect_tables_query(
        self, schema_name: str = "system"
    ) -> tuple[str, list[Any]]:
        return (
            f"SELECT table_name FROM system_schema.tables WHERE keyspace_name = {self.placeholder};",
            [schema_name],
        )

    def inspect_columns_query(
        self, schema_name: str = "system", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT table_name, column_name, type, kind FROM system_schema.columns WHERE keyspace_name = {self.placeholder} AND table_name = {self.placeholder};",
                [schema_name, table_name],
            )
        return (
            f"SELECT table_name, column_name, type, kind FROM system_schema.columns WHERE keyspace_name = {self.placeholder};",
            [schema_name],
        )

    def inspect_primary_keys_query(
        self, schema_name: str = "system", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT table_name, column_name FROM system_schema.columns WHERE keyspace_name = {self.placeholder} AND table_name = {self.placeholder} AND kind IN ('partition_key', 'clustering');",
                [schema_name, table_name],
            )
        return (
            f"SELECT table_name, column_name FROM system_schema.columns WHERE keyspace_name = {self.placeholder} AND kind IN ('partition_key', 'clustering');",
            [schema_name],
        )

    def inspect_foreign_keys_query(
        self, schema_name: str = "system", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])


class SurrealDBDialect(BaseDialect):
    """SurrealDB multi-model SurrealQL dialect."""

    name: str = "surrealdb"
    placeholder: str = "?"
    ilike_template: str = "string::lowercase({col}) CONTAINS string::lowercase({ph})"

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        _validate_alias(alias_name)
        cleaned = alias_name.replace("`", "``")
        return f"`{cleaned}`"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder} START {self.placeholder}", [limit, offset]

    def inspect_tables_query(self, schema_name: str = "test") -> tuple[str, list[Any]]:
        return ("INFO FOR DB;", [])

    def inspect_columns_query(
        self, schema_name: str = "test", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (f"INFO FOR TABLE `{table_name}`;", [])
        return ("INFO FOR DB;", [])

    def inspect_primary_keys_query(
        self, schema_name: str = "test", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (f"INFO FOR TABLE `{table_name}`;", [])
        return ("INFO FOR DB;", [])

    def inspect_foreign_keys_query(
        self, schema_name: str = "test", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])


class ArangoDBDialect(BaseDialect):
    """ArangoDB multi-model document and graph database dialect."""

    name: str = "arangodb"
    placeholder: str = "?"
    ilike_template: str = "CONTAINS(LOWER({col}), LOWER({ph}))"

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        _validate_alias(alias_name)
        cleaned = alias_name.replace("`", "``")
        return f"`{cleaned}`"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder}, {self.placeholder}", [offset, limit]

    def inspect_tables_query(
        self, schema_name: str = "_system"
    ) -> tuple[str, list[Any]]:
        return ("RETURN COLLECTIONS();", [])

    def inspect_columns_query(
        self, schema_name: str = "_system", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("RETURN COLLECTIONS();", [])

    def inspect_primary_keys_query(
        self, schema_name: str = "_system", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("RETURN COLLECTIONS();", [])

    def inspect_foreign_keys_query(
        self, schema_name: str = "_system", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])


class CassandraDialect(ScyllaDBDialect):
    """Apache Cassandra CQL dialect."""

    name: str = "cassandra"


class CosmosDBDialect(BaseDialect):
    """Azure Cosmos DB SQL API dialect."""

    name: str = "cosmosdb"
    placeholder: str = "@param"
    ilike_template: str = "CONTAINS(LOWER({col}), LOWER({ph}))"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"OFFSET {self.placeholder} LIMIT {self.placeholder}", [offset, limit]

    def inspect_tables_query(
        self, schema_name: str = "default"
    ) -> tuple[str, list[Any]]:
        return ("SELECT VALUE c.id FROM c;", [])

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("SELECT * FROM c OFFSET 0 LIMIT 1;", [])

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("SELECT VALUE c.id FROM c;", [])

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])


class OpenSearchDialect(ElasticsearchDialect):
    """OpenSearch distributed search & analytics SQL plugin dialect."""

    name: str = "opensearch"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        # The SQL plugin cannot bind LIMIT/OFFSET; inline the int-coerced values.
        clause = f"LIMIT {int(limit)}"
        if int(offset) > 0:
            clause += f" OFFSET {int(offset)}"
        return clause, []

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        _validate_alias(alias_name)
        cleaned = alias_name.replace("`", "``")
        return f"`{cleaned}`"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def inspect_tables_query(
        self, schema_name: str = "default"
    ) -> tuple[str, list[Any]]:
        return ("SHOW TABLES LIKE '%';", [])

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (f"DESCRIBE `{table_name}`;", [])
        return ("SHOW TABLES LIKE '%';", [])

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])


class Neo4jDialect(BaseDialect):
    """Neo4j graph database Cypher and SQL mapping dialect."""

    name: str = "neo4j"
    placeholder: str = "$param"
    ilike_template: str = "toLower({col}) CONTAINS toLower({ph})"

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        _validate_alias(alias_name)
        cleaned = alias_name.replace("`", "``")
        return f"`{cleaned}`"

    def format_like(self, col_ref: str) -> str:
        return f"{col_ref} CONTAINS {self.placeholder}"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"SKIP {self.placeholder} LIMIT {self.placeholder}", [offset, limit]

    def inspect_tables_query(self, schema_name: str = "neo4j") -> tuple[str, list[Any]]:
        return ("SHOW NODE LABELS;", [])

    def inspect_columns_query(
        self, schema_name: str = "neo4j", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (f"MATCH (n:`{table_name}`) RETURN keys(n) AS keys LIMIT 1;", [])
        if schema_name and schema_name != "neo4j":
            return (f"MATCH (n:`{schema_name}`) RETURN keys(n) AS keys LIMIT 1;", [])
        return ("CALL db.schema.nodeTypeProperties();", [])

    def inspect_primary_keys_query(
        self, schema_name: str = "neo4j", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("SHOW CONSTRAINTS;", [])

    def inspect_foreign_keys_query(
        self, schema_name: str = "neo4j", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("SHOW RELATIONSHIP TYPES;", [])


class KdbDialect(BaseDialect):
    """Kdb+ ultra-high performance financial vector and time-series database dialect."""

    name: str = "kdb"
    placeholder: str = "?"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"

    def inspect_tables_query(
        self, schema_name: str = "default"
    ) -> tuple[str, list[Any]]:
        return ("tables[]", [])

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (f"meta `{table_name}", [])
        return ("tables[]", [])

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (f"keys `{table_name}", [])
        return ("", [])

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])


class MemgraphDialect(BaseDialect):
    """Memgraph in-memory OpenCypher graph database dialect."""

    name: str = "memgraph"
    placeholder: str = "%s"
    ilike_template: str = "toLower({col}) CONTAINS toLower({ph})"

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"SKIP {self.placeholder} LIMIT {self.placeholder}", [offset, limit]

    def inspect_tables_query(
        self, schema_name: str = "public"
    ) -> tuple[str, list[Any]]:
        return "CALL mg.labels() YIELD label RETURN label;", []

    def inspect_columns_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "SHOW CONSTRAINT INFO;", []

    def inspect_primary_keys_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []

    def inspect_foreign_keys_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return (
            "CALL mg.relationship_types() YIELD relationship_type RETURN relationship_type;",
            [],
        )


class NeptuneDialect(BaseDialect):
    """Amazon Neptune managed graph database openCypher dialect."""

    name: str = "neptune"
    placeholder: str = "%s"
    ilike_template: str = "toLower({col}) CONTAINS toLower({ph})"

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"SKIP {self.placeholder} LIMIT {self.placeholder}", [offset, limit]

    def inspect_tables_query(
        self, schema_name: str = "public"
    ) -> tuple[str, list[Any]]:
        return "CALL db.labels();", []

    def inspect_columns_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "CALL db.propertyKeys();", []

    def inspect_primary_keys_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "", []

    def inspect_foreign_keys_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return "CALL db.relationshipTypes();", []


class FirestoreDialect(BaseDialect):
    """Google Cloud Firestore document database dialect."""

    name: str = "firestore"
    placeholder: str = "%s"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"
    introspects_keys: bool = False

    def inspect_tables_query(
        self, schema_name: str = "default"
    ) -> tuple[str, list[Any]]:
        return "collections", []

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return f"collection:{table_name}", []
        return "collections", []


class BigtableDialect(BaseDialect):
    """Google Cloud Bigtable wide-column database dialect."""

    name: str = "bigtable"
    placeholder: str = "%s"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"
    introspects_keys: bool = False

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder}", [limit]

    def inspect_tables_query(
        self, schema_name: str = "default"
    ) -> tuple[str, list[Any]]:
        return "list_tables", []

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return f"list_column_families:{table_name}", []
        return "list_tables", []
