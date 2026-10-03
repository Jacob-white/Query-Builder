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

    def inspect_tables_query(
        self, schema_name: str = "public"
    ) -> tuple[str, list[Any]]:
        """Returns the SQL query and parameters to introspect tables for this dialect."""
        return (
            f"SELECT table_name FROM information_schema.tables WHERE table_schema = {self.placeholder} AND table_type = 'BASE TABLE' ORDER BY table_name;",
            [schema_name],
        )

    def inspect_columns_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        """Returns the SQL query and parameters to introspect columns for this dialect."""
        if table_name:
            return (
                f"SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = {self.placeholder} AND table_name = {self.placeholder} ORDER BY ordinal_position;",
                [schema_name, table_name],
            )
        return (
            f"SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = {self.placeholder} ORDER BY table_name, ordinal_position;",
            [schema_name],
        )

    def inspect_primary_keys_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        """Returns the SQL query and parameters to introspect primary keys for this dialect."""
        if table_name:
            return (
                f"SELECT kcu.table_name, kcu.column_name FROM information_schema.table_constraints AS tc JOIN information_schema.key_column_usage AS kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = {self.placeholder} AND tc.table_name = {self.placeholder};",
                [schema_name, table_name],
            )
        return (
            f"SELECT kcu.table_name, kcu.column_name FROM information_schema.table_constraints AS tc JOIN information_schema.key_column_usage AS kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = {self.placeholder};",
            [schema_name],
        )

    def inspect_foreign_keys_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        """Returns the SQL query and parameters to introspect foreign keys for this dialect."""
        if table_name:
            return (
                f"SELECT kcu.table_name AS src_table, kcu.column_name AS src_column, ccu.table_name AS tgt_table, ccu.column_name AS tgt_column FROM information_schema.table_constraints AS tc JOIN information_schema.key_column_usage AS kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema JOIN information_schema.constraint_column_usage AS ccu ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = {self.placeholder} AND tc.table_name = {self.placeholder};",
                [schema_name, table_name],
            )
        return (
            f"SELECT kcu.table_name AS src_table, kcu.column_name AS src_column, ccu.table_name AS tgt_table, ccu.column_name AS tgt_column FROM information_schema.table_constraints AS tc JOIN information_schema.key_column_usage AS kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema JOIN information_schema.constraint_column_usage AS ccu ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = {self.placeholder};",
            [schema_name],
        )


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

    def inspect_tables_query(self, schema_name: str = "main") -> tuple[str, list[Any]]:
        return (
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;",
            [],
        )

    def inspect_columns_query(
        self, schema_name: str = "main", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        tbl = table_name or "sqlite_master"
        return f'PRAGMA table_info("{tbl}");', []

    def inspect_primary_keys_query(
        self, schema_name: str = "main", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        tbl = table_name or "sqlite_master"
        return f'PRAGMA table_info("{tbl}");', []

    def inspect_foreign_keys_query(
        self, schema_name: str = "main", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        tbl = table_name or "sqlite_master"
        return f'PRAGMA foreign_key_list("{tbl}");', []


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

    def inspect_tables_query(
        self, schema_name: str = "default"
    ) -> tuple[str, list[Any]]:
        return (
            f"SELECT name FROM system.tables WHERE database = {self.placeholder} ORDER BY name;",
            [schema_name],
        )

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT table, name, type FROM system.columns WHERE database = {self.placeholder} AND table = {self.placeholder} ORDER BY position;",
                [schema_name, table_name],
            )
        return (
            f"SELECT table, name, type FROM system.columns WHERE database = {self.placeholder} ORDER BY table, position;",
            [schema_name],
        )


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

    def inspect_tables_query(
        self, schema_name: str = "SYSTEM"
    ) -> tuple[str, list[Any]]:
        return (
            f"SELECT table_name FROM all_tables WHERE owner = {self.placeholder} ORDER BY table_name;",
            [schema_name.upper()],
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


class DruidDialect(BaseDialect):
    """Apache Druid real-time analytical database dialect."""

    name: str = "druid"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def inspect_tables_query(self, schema_name: str = "druid") -> tuple[str, list[Any]]:
        return (
            f"SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = {self.placeholder} ORDER BY TABLE_NAME;",
            [schema_name],
        )

    def inspect_columns_query(
        self, schema_name: str = "druid", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = {self.placeholder} AND TABLE_NAME = {self.placeholder} ORDER BY ORDINAL_POSITION;",
                [schema_name, table_name],
            )
        return (
            f"SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = {self.placeholder} ORDER BY TABLE_NAME, ORDINAL_POSITION;",
            [schema_name],
        )


class PinotDialect(BaseDialect):
    """Apache Pinot distributed OLAP datastore dialect."""

    name: str = "pinot"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"


class StarRocksDialect(BaseDialect):
    """StarRocks distributed MPP analytical database dialect."""

    name: str = "starrocks"
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


class MaterializeDialect(PostgresDialect):
    """Materialize streaming SQL database engine dialect."""

    name: str = "materialize"


class RisingWaveDialect(PostgresDialect):
    """RisingWave distributed streaming SQL database dialect."""

    name: str = "risingwave"


class CrateDBDialect(BaseDialect):
    """CrateDB distributed SQL database dialect."""

    name: str = "cratedb"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f"{col_ref} ILIKE {self.placeholder}"

    def inspect_tables_query(self, schema_name: str = "doc") -> tuple[str, list[Any]]:
        return (
            f"SELECT table_name FROM information_schema.tables WHERE table_schema = {self.placeholder} ORDER BY table_name;",
            [schema_name],
        )

    def inspect_columns_query(
        self, schema_name: str = "doc", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = {self.placeholder} AND table_name = {self.placeholder} ORDER BY ordinal_position;",
                [schema_name, table_name],
            )
        return (
            f"SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = {self.placeholder} ORDER BY table_name, ordinal_position;",
            [schema_name],
        )


class InfluxDBDialect(BaseDialect):
    """InfluxDB v3 / IOx SQL time-series engine dialect."""

    name: str = "influxdb"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f"{col_ref} ILIKE {self.placeholder}"


class AlloyDBDialect(PostgresDialect):
    """Google Cloud AlloyDB for PostgreSQL dialect."""

    name: str = "alloydb"


class VerticaDialect(BaseDialect):
    """Vertica columnar analytical data warehouse dialect."""

    name: str = "vertica"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f"{col_ref} ILIKE {self.placeholder}"


class SAPHANADialect(BaseDialect):
    """SAP HANA in-memory database dialect."""

    name: str = "saphana"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def inspect_tables_query(
        self, schema_name: str = "SYSTEM"
    ) -> tuple[str, list[Any]]:
        return (
            f"SELECT TABLE_NAME FROM SYS.TABLES WHERE SCHEMA_NAME = {self.placeholder} ORDER BY TABLE_NAME;",
            [schema_name.upper()],
        )

    def inspect_columns_query(
        self, schema_name: str = "SYSTEM", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE_NAME, IS_NULLABLE FROM SYS.TABLE_COLUMNS WHERE SCHEMA_NAME = {self.placeholder} AND TABLE_NAME = {self.placeholder} ORDER BY POSITION;",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE_NAME, IS_NULLABLE FROM SYS.TABLE_COLUMNS WHERE SCHEMA_NAME = {self.placeholder} ORDER BY TABLE_NAME, POSITION;",
            [schema_name.upper()],
        )


class OceanBaseDialect(MySQLDialect):
    """OceanBase distributed SQL database dialect."""

    name: str = "oceanbase"


class ScyllaDBDialect(BaseDialect):
    """ScyllaDB and Apache Cassandra CQL dialect."""

    name: str = "scylladb"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

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


class SparkSQLDialect(BaseDialect):
    """Apache Spark SQL dialect using backticks and Hive metastore / Delta Lake conventions."""

    name: str = "sparksql"
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

    def inspect_tables_query(
        self, schema_name: str = "default"
    ) -> tuple[str, list[Any]]:
        return (
            f"SELECT table_name FROM information_schema.tables WHERE table_schema = {self.placeholder} ORDER BY table_name;",
            [schema_name],
        )

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = {self.placeholder} AND table_name = {self.placeholder} ORDER BY ordinal_position;",
                [schema_name, table_name],
            )
        return (
            f"SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = {self.placeholder} ORDER BY table_name, ordinal_position;",
            [schema_name],
        )

    def inspect_primary_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])

    def inspect_foreign_keys_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        return ("", [])


class ChDBDialect(ClickHouseDialect):
    """chDB in-process ClickHouse SQL OLAP dialect."""

    name: str = "chdb"


class GreptimeDBDialect(BaseDialect):
    """GreptimeDB cloud-native distributed time-series database dialect."""

    name: str = "greptimedb"
    placeholder: str = "%s"

    def format_ilike(self, col_ref: str) -> str:
        return f"{col_ref} ILIKE {self.placeholder}"

    def inspect_tables_query(
        self, schema_name: str = "public"
    ) -> tuple[str, list[Any]]:
        return (
            f"SELECT table_name FROM information_schema.tables WHERE table_schema = {self.placeholder} ORDER BY table_name;",
            [schema_name],
        )

    def inspect_columns_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = {self.placeholder} AND table_name = {self.placeholder} ORDER BY ordinal_position;",
                [schema_name, table_name],
            )
        return (
            f"SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = {self.placeholder} ORDER BY table_name, ordinal_position;",
            [schema_name],
        )


class TDengineDialect(BaseDialect):
    """TDengine big data IoT time-series database dialect."""

    name: str = "tdengine"
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

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"LIMIT {self.placeholder} OFFSET {self.placeholder}", [limit, offset]

    def inspect_tables_query(
        self, schema_name: str = "default"
    ) -> tuple[str, list[Any]]:
        return ("SHOW TABLES;", [])

    def inspect_columns_query(
        self, schema_name: str = "default", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (f"DESCRIBE `{table_name}`;", [])
        return ("SHOW TABLES;", [])


class SurrealDBDialect(BaseDialect):
    """SurrealDB multi-model SurrealQL dialect."""

    name: str = "surrealdb"
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
        return f"string::lowercase({col_ref}) CONTAINS string::lowercase({self.placeholder})"

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


class ArangoDBDialect(BaseDialect):
    """ArangoDB multi-model document and graph database dialect."""

    name: str = "arangodb"
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
        return f"CONTAINS(LOWER({col_ref}), LOWER({self.placeholder}))"

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


class CassandraDialect(ScyllaDBDialect):
    """Apache Cassandra CQL dialect."""

    name: str = "scylladb"


class ExasolDialect(BaseDialect):
    """Exasol high-performance in-memory MP-relational analytics dialect."""

    name: str = "exasol"
    placeholder: str = "?"

    def format_ilike(self, col_ref: str) -> str:
        return f"REGEXP_LIKE({col_ref}, {self.placeholder}, 'i')"

    def inspect_tables_query(
        self, schema_name: str = "PUBLIC"
    ) -> tuple[str, list[Any]]:
        return (
            f"SELECT TABLE_NAME FROM EXA_ALL_TABLES WHERE TABLE_SCHEMA = {self.placeholder} ORDER BY TABLE_NAME;",
            [schema_name.upper()],
        )

    def inspect_columns_query(
        self, schema_name: str = "PUBLIC", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT COLUMN_TABLE, COLUMN_NAME, COLUMN_TYPE, COLUMN_IS_NULLABLE FROM EXA_ALL_COLUMNS WHERE COLUMN_SCHEMA = {self.placeholder} AND COLUMN_TABLE = {self.placeholder} ORDER BY COLUMN_ORDINAL_POSITION;",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT COLUMN_TABLE, COLUMN_NAME, COLUMN_TYPE, COLUMN_IS_NULLABLE FROM EXA_ALL_COLUMNS WHERE COLUMN_SCHEMA = {self.placeholder} ORDER BY COLUMN_ORDINAL_POSITION;",
            [schema_name.upper()],
        )

    def inspect_primary_keys_query(
        self, schema_name: str = "PUBLIC", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT CONSTRAINT_TABLE, COLUMN_NAME FROM EXA_ALL_CONSTRAINT_COLUMNS WHERE CONSTRAINT_SCHEMA = {self.placeholder} AND CONSTRAINT_TABLE = {self.placeholder} AND CONSTRAINT_TYPE = 'PRIMARY KEY';",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT CONSTRAINT_TABLE, COLUMN_NAME FROM EXA_ALL_CONSTRAINT_COLUMNS WHERE CONSTRAINT_SCHEMA = {self.placeholder} AND CONSTRAINT_TYPE = 'PRIMARY KEY';",
            [schema_name.upper()],
        )


class DB2Dialect(BaseDialect):
    """IBM DB2 enterprise relational database dialect."""

    name: str = "db2"
    placeholder: str = "?"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return (
            f"OFFSET {self.placeholder} ROWS FETCH NEXT {self.placeholder} ROWS ONLY",
            [offset, limit],
        )

    def inspect_tables_query(
        self, schema_name: str = "SYSCAT"
    ) -> tuple[str, list[Any]]:
        return (
            f"SELECT TABNAME FROM SYSCAT.TABLES WHERE TABSCHEMA = {self.placeholder} AND TYPE = 'T' ORDER BY TABNAME;",
            [schema_name.upper()],
        )

    def inspect_columns_query(
        self, schema_name: str = "SYSCAT", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT TABNAME, COLNAME, TYPENAME, NULLS FROM SYSCAT.COLUMNS WHERE TABSCHEMA = {self.placeholder} AND TABNAME = {self.placeholder} ORDER BY COLNO;",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT TABNAME, COLNAME, TYPENAME, NULLS FROM SYSCAT.COLUMNS WHERE TABSCHEMA = {self.placeholder} ORDER BY TABNAME, COLNO;",
            [schema_name.upper()],
        )

    def inspect_primary_keys_query(
        self, schema_name: str = "SYSCAT", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT TABNAME, COLNAME FROM SYSCAT.KEYCOLUSE WHERE TABSCHEMA = {self.placeholder} AND TABNAME = {self.placeholder} ORDER BY COLSEQ;",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT TABNAME, COLNAME FROM SYSCAT.KEYCOLUSE WHERE TABSCHEMA = {self.placeholder} ORDER BY COLSEQ;",
            [schema_name.upper()],
        )

    def inspect_foreign_keys_query(
        self, schema_name: str = "SYSCAT", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT TABNAME AS src_table, FK_COLNAMES AS src_column, REFTABNAME AS tgt_table, PK_COLNAMES AS tgt_column FROM SYSCAT.REFERENCES WHERE TABSCHEMA = {self.placeholder} AND TABNAME = {self.placeholder};",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT TABNAME AS src_table, FK_COLNAMES AS src_column, REFTABNAME AS tgt_table, PK_COLNAMES AS tgt_column FROM SYSCAT.REFERENCES WHERE TABSCHEMA = {self.placeholder};",
            [schema_name.upper()],
        )


class CosmosDBDialect(BaseDialect):
    """Azure Cosmos DB SQL API dialect."""

    name: str = "cosmosdb"
    placeholder: str = "@param"

    def format_ilike(self, col_ref: str) -> str:
        return f"CONTAINS(LOWER({col_ref}), LOWER({self.placeholder}))"

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
    "prestodb": PrestoDialect(),
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
    "druid": DruidDialect(),
    "apache_druid": DruidDialect(),
    "pinot": PinotDialect(),
    "apache_pinot": PinotDialect(),
    "starrocks": StarRocksDialect(),
    "materialize": MaterializeDialect(),
    "mz": MaterializeDialect(),
    "risingwave": RisingWaveDialect(),
    "rw": RisingWaveDialect(),
    "cratedb": CrateDBDialect(),
    "crate": CrateDBDialect(),
    "influxdb": InfluxDBDialect(),
    "iox": InfluxDBDialect(),
    "influx": InfluxDBDialect(),
    "alloydb": AlloyDBDialect(),
    "vertica": VerticaDialect(),
    "saphana": SAPHANADialect(),
    "hana": SAPHANADialect(),
    "sap_hana": SAPHANADialect(),
    "oceanbase": OceanBaseDialect(),
    "scylladb": ScyllaDBDialect(),
    "scylla": ScyllaDBDialect(),
    "cassandra": CassandraDialect(),
    "cql": CassandraDialect(),
    "apache_cassandra": CassandraDialect(),
    "sparksql": SparkSQLDialect(),
    "spark_sql": SparkSQLDialect(),
    "pyspark": SparkSQLDialect(),
    "chdb": ChDBDialect(),
    "greptimedb": GreptimeDBDialect(),
    "greptime": GreptimeDBDialect(),
    "tdengine": TDengineDialect(),
    "taos": TDengineDialect(),
    "surrealdb": SurrealDBDialect(),
    "surreal": SurrealDBDialect(),
    "arangodb": ArangoDBDialect(),
    "arango": ArangoDBDialect(),
    "aql": ArangoDBDialect(),
    "exasol": ExasolDialect(),
    "db2": DB2Dialect(),
    "ibm_db2": DB2Dialect(),
    "cosmosdb": CosmosDBDialect(),
    "azure_cosmos": CosmosDBDialect(),
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
