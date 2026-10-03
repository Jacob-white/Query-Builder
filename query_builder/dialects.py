"""
Pluggable SQL Dialects for Query Builder Engine.
================================================
Provides quote escaping, parameter placeholder handling, and dialect-specific
SQL syntax generation for PostgreSQL, Snowflake, Microsoft SQL Server, SQLite, and MySQL.
"""

from __future__ import annotations

import re
from typing import Any

IDENTIFIER_REGEX = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$")
MAX_IDENTIFIER_LENGTH = 128
MAX_ALIAS_LENGTH = 256


class DialectError(Exception):
    """Raised when identifier or alias formatting encounters an invalid pattern."""


def _validate_identifier(ident: str) -> None:
    if not isinstance(ident, str) or not IDENTIFIER_REGEX.match(ident):
        raise DialectError(f"Invalid identifier name: '{ident}'")
    parts = ident.split(".")
    if any(len(part) > MAX_IDENTIFIER_LENGTH for part in parts):
        raise DialectError(
            f"Identifier part exceeds maximum allowed length ({MAX_IDENTIFIER_LENGTH}): '{ident}'"
        )


def _validate_alias(alias_name: str) -> None:
    if not isinstance(alias_name, str):
        raise DialectError(f"Alias must be a string, got {type(alias_name).__name__}")
    if len(alias_name) > MAX_ALIAS_LENGTH:
        raise DialectError(
            f"Alias length ({len(alias_name)}) exceeds maximum limit of {MAX_ALIAS_LENGTH} characters."
        )
    if "\x00" in alias_name or any(
        ord(c) < 32 and c not in ("\t", "\n", "\r") for c in alias_name
    ):
        raise DialectError(
            f"Alias contains forbidden control characters: '{alias_name}'"
        )


class BaseDialect:
    """Base SQL dialect adhering to ANSI-SQL standards with parameter binding."""

    name: str = "base"
    placeholder: str = "%s"

    def quote_identifier(self, ident: str) -> str:
        """Quotes a schema, table, or column identifier."""
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f'"{part}"' for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        """Quotes an output projection alias safely."""
        _validate_alias(alias_name)
        cleaned = alias_name.replace('"', '""')
        return f'"{cleaned}"'

    def format_ilike(self, col_ref: str) -> str:
        """Formats a case-insensitive string matching expression."""
        return f"{col_ref} ILIKE {self.placeholder}"

    def format_like(self, col_ref: str) -> str:
        """Formats a case-sensitive string matching expression."""
        return f"{col_ref} LIKE {self.placeholder}"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        """Formats LIMIT and OFFSET clause with bind parameters."""
        return f"LIMIT {self.placeholder} OFFSET {self.placeholder}", [limit, offset]


class PostgresDialect(BaseDialect):
    """PostgreSQL dialect."""

    name: str = "postgres"


class SnowflakeDialect(BaseDialect):
    """Snowflake dialect."""

    name: str = "snowflake"


class MSSQLDialect(BaseDialect):
    """Microsoft SQL Server dialect using square bracket quoting and FETCH FIRST pagination."""

    name: str = "mssql"
    placeholder: str = "%s"

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"[{part}]" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        _validate_alias(alias_name)
        cleaned = alias_name.replace("]", "]]")
        return f"[{cleaned}]"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return (
            f"OFFSET {self.placeholder} ROWS FETCH NEXT {self.placeholder} ROWS ONLY",
            [offset, limit],
        )


class SQLiteDialect(BaseDialect):
    """SQLite dialect using double-quote escaping and question mark placeholders."""

    name: str = "sqlite"
    placeholder: str = "?"

    def format_ilike(self, col_ref: str) -> str:
        # SQLite LIKE is case-insensitive by default for ASCII
        return f"{col_ref} LIKE {self.placeholder}"


class MySQLDialect(BaseDialect):
    """MySQL dialect using backtick quoting."""

    name: str = "mysql"
    placeholder: str = "%s"

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


class DuckDBDialect(BaseDialect):
    """DuckDB dialect supporting native ILIKE and question mark placeholders."""

    name: str = "duckdb"
    placeholder: str = "?"

    def format_ilike(self, col_ref: str) -> str:
        return f"{col_ref} ILIKE {self.placeholder}"


class BigQueryDialect(BaseDialect):
    """Google BigQuery standard SQL dialect using backtick quoting."""

    name: str = "bigquery"
    placeholder: str = "%s"

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


class ClickHouseDialect(BaseDialect):
    """ClickHouse dialect using backtick quoting and native ILIKE."""

    name: str = "clickhouse"
    placeholder: str = "%s"

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        _validate_alias(alias_name)
        cleaned = alias_name.replace("`", "``")
        return f"`{cleaned}`"

    def format_ilike(self, col_ref: str) -> str:
        return f"{col_ref} ILIKE {self.placeholder}"


class OracleDialect(BaseDialect):
    """Oracle SQL dialect using standard ANSI double-quote escaping and OFFSET-FETCH pagination."""

    name: str = "oracle"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return (
            f"OFFSET {self.placeholder} ROWS FETCH NEXT {self.placeholder} ROWS ONLY",
            [offset, limit],
        )


class RedshiftDialect(BaseDialect):
    """Amazon Redshift dialect."""

    name: str = "redshift"
    placeholder: str = "%s"


class TrinoDialect(BaseDialect):
    """Trino SQL dialect using double-quote escaping and OFFSET/LIMIT pagination."""

    name: str = "trino"
    placeholder: str = "?"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return (
            f"OFFSET {self.placeholder} LIMIT {self.placeholder}",
            [offset, limit],
        )


class PrestoDialect(TrinoDialect):
    """Presto SQL dialect."""

    name: str = "presto"


class DatabricksDialect(BaseDialect):
    """Databricks and Apache Spark SQL dialect using backtick quoting."""

    name: str = "databricks"
    placeholder: str = "%s"

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


class AthenaDialect(BaseDialect):
    """AWS Athena dialect based on Presto/Trino standard SQL."""

    name: str = "athena"
    placeholder: str = "?"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"


class PolarsDialect(BaseDialect):
    """Polars SQLContext dialect with native ILIKE and question mark placeholders."""

    name: str = "polars"
    placeholder: str = "?"

    def format_ilike(self, col_ref: str) -> str:
        return f"{col_ref} ILIKE {self.placeholder}"


class DataFusionDialect(BaseDialect):
    """Apache Arrow DataFusion SQL dialect."""

    name: str = "datafusion"
    placeholder: str = "?"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"


class TimescaleDialect(PostgresDialect):
    """TimescaleDB time-series dialect extending PostgreSQL."""

    name: str = "timescaledb"


class CockroachDialect(PostgresDialect):
    """CockroachDB distributed SQL dialect extending PostgreSQL."""

    name: str = "cockroachdb"


class SpannerDialect(BaseDialect):
    """Google Cloud Spanner SQL dialect using backtick quoting."""

    name: str = "spanner"
    placeholder: str = "%s"

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


class QuestDBDialect(BaseDialect):
    """QuestDB time-series SQL dialect supporting native ILIKE."""

    name: str = "questdb"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f"{col_ref} ILIKE {self.placeholder}"


class ElasticsearchDialect(BaseDialect):
    """Elasticsearch / OpenSearch SQL dialect."""

    name: str = "elasticsearch"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"


class DynamoDBPartiQLDialect(BaseDialect):
    """Amazon DynamoDB PartiQL dialect."""

    name: str = "dynamodb"
    placeholder: str = "?"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder}", [limit]


class DremioDialect(BaseDialect):
    """Dremio SQL Lakehouse platform dialect using Arrow Flight / DB-API."""

    name: str = "dremio"
    placeholder: str = "?"


class FireboltDialect(BaseDialect):
    """Firebolt ultra-low latency cloud data warehouse dialect."""

    name: str = "firebolt"
    placeholder: str = "?"


class TiDBDialect(MySQLDialect):
    """TiDB distributed HTAP database dialect."""

    name: str = "tidb"


class SingleStoreDialect(MySQLDialect):
    """SingleStore / MemSQL distributed SQL dialect."""

    name: str = "singlestore"


class TeradataDialect(BaseDialect):
    """Teradata enterprise analytical data warehouse dialect."""

    name: str = "teradata"
    placeholder: str = "?"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return (
            f"OFFSET {self.placeholder} ROWS FETCH NEXT {self.placeholder} ROWS ONLY",
            [offset, limit],
        )


class CouchbaseDialect(BaseDialect):
    """Couchbase SQL++ / N1QL dialect using backtick quoting."""

    name: str = "couchbase"
    placeholder: str = "?"

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


class D1Dialect(SQLiteDialect):
    """Cloudflare D1 serverless edge SQL database dialect."""

    name: str = "d1"


class MongoDBSQLDialect(BaseDialect):
    """MongoDB Atlas SQL interface dialect."""

    name: str = "mongodb"
    placeholder: str = "?"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"


class NeonDialect(PostgresDialect):
    """Neon serverless PostgreSQL dialect."""

    name: str = "neon"


class SupabaseDialect(PostgresDialect):
    """Supabase managed PostgreSQL dialect."""

    name: str = "supabase"


DIALECTS: dict[str, BaseDialect] = {
    "postgres": PostgresDialect(),
    "postgresql": PostgresDialect(),
    "snowflake": SnowflakeDialect(),
    "mssql": MSSQLDialect(),
    "sqlserver": MSSQLDialect(),
    "sqlite": SQLiteDialect(),
    "mysql": MySQLDialect(),
    "duckdb": DuckDBDialect(),
    "bigquery": BigQueryDialect(),
    "clickhouse": ClickHouseDialect(),
    "oracle": OracleDialect(),
    "redshift": RedshiftDialect(),
    "trino": TrinoDialect(),
    "presto": PrestoDialect(),
    "databricks": DatabricksDialect(),
    "spark": DatabricksDialect(),
    "athena": AthenaDialect(),
    "polars": PolarsDialect(),
    "datafusion": DataFusionDialect(),
    "timescaledb": TimescaleDialect(),
    "timescale": TimescaleDialect(),
    "cockroachdb": CockroachDialect(),
    "cockroach": CockroachDialect(),
    "spanner": SpannerDialect(),
    "questdb": QuestDBDialect(),
    "elasticsearch": ElasticsearchDialect(),
    "opensearch": ElasticsearchDialect(),
    "dynamodb": DynamoDBPartiQLDialect(),
    "partiql": DynamoDBPartiQLDialect(),
    "dremio": DremioDialect(),
    "firebolt": FireboltDialect(),
    "tidb": TiDBDialect(),
    "singlestore": SingleStoreDialect(),
    "memsql": SingleStoreDialect(),
    "teradata": TeradataDialect(),
    "couchbase": CouchbaseDialect(),
    "n1ql": CouchbaseDialect(),
    "d1": D1Dialect(),
    "cloudflare_d1": D1Dialect(),
    "mongodb": MongoDBSQLDialect(),
    "mongo": MongoDBSQLDialect(),
    "atlas_sql": MongoDBSQLDialect(),
    "neon": NeonDialect(),
    "supabase": SupabaseDialect(),
}


def get_dialect(name: str = "postgres") -> BaseDialect:
    """Returns the dialect instance for the specified name (defaults to postgres)."""
    return DIALECTS.get(name.lower().strip(), DIALECTS["postgres"])


def quote_identifier(ident: str, dialect_name: str = "postgres") -> str:
    """Convenience helper to quote an identifier with the named dialect."""
    return get_dialect(dialect_name).quote_identifier(ident)


def quote_alias(alias_name: str, dialect_name: str = "postgres") -> str:
    """Convenience helper to quote an alias with the named dialect."""
    return get_dialect(dialect_name).quote_alias(alias_name)


def register_dialect(
    name: str | BaseDialect | type[BaseDialect],
    dialect: BaseDialect | type[BaseDialect] | None = None,
    aliases: list[str] | None = None,
) -> Any:
    """
    Registers a SQL dialect dynamically or as a class decorator.

    Supports:
    - Bare decorator: @register_dialect
    - Decorator with name: @register_dialect("my_sql", aliases=[...])
    - Functional registration: register_dialect("my_sql", dialect_or_cls, aliases=[...])
    """
    # Bare decorator: @register_dialect
    if dialect is None and isinstance(name, type) and issubclass(name, BaseDialect):
        instance = name()
        inferred_name = name.__dict__.get("name") or name.__name__.lower()
        clean_name = inferred_name.lower().strip()
        DIALECTS[clean_name] = instance
        if aliases:
            for alias in aliases:
                clean_alias = alias.lower().strip()
                if clean_alias:
                    DIALECTS[clean_alias] = instance
        return name

    # Decorator factory: @register_dialect("my_sql", aliases=[...])
    if dialect is None and isinstance(name, str):
        clean_name = name.lower().strip()
        if not clean_name:
            raise ValueError("Dialect name cannot be empty.")

        def decorator(cls: type[BaseDialect]) -> type[BaseDialect]:
            if not (isinstance(cls, type) and issubclass(cls, BaseDialect)):
                raise TypeError(
                    f"Dialect must be an instance or subclass of BaseDialect, got {type(cls).__name__}"
                )
            instance = cls()
            DIALECTS[clean_name] = instance
            if aliases:
                for alias in aliases:
                    clean_alias = alias.lower().strip()
                    if clean_alias:
                        DIALECTS[clean_alias] = instance
            return cls

        return decorator

    if dialect is None:
        raise TypeError(
            f"Dialect name must be a string or dialect class, got {type(name).__name__}"
        )

    # Functional registration: register_dialect("my_sql", dialect_or_cls, aliases=[...])
    if not isinstance(name, str):
        raise TypeError(f"Dialect name must be a string, got {type(name).__name__}")
    clean_name = name.lower().strip()
    if not clean_name:
        raise ValueError("Dialect name cannot be empty.")

    if isinstance(dialect, type) and issubclass(dialect, BaseDialect):
        instance = dialect()
    elif isinstance(dialect, BaseDialect):
        instance = dialect
    else:
        raise TypeError(
            f"Dialect must be an instance or subclass of BaseDialect, got {type(dialect).__name__}"
        )

    DIALECTS[clean_name] = instance
    if aliases:
        for alias in aliases:
            clean_alias = alias.lower().strip()
            if clean_alias:
                DIALECTS[clean_alias] = instance
    return instance


def unregister_dialect(name: str) -> None:
    """Removes a dialect from the registered dialects map."""
    clean_name = name.lower().strip()
    DIALECTS.pop(clean_name, None)


def list_dialects() -> list[str]:
    """Returns a sorted list of registered dialect names and aliases."""
    return sorted(DIALECTS.keys())
